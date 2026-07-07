#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scopus_gap_filler.py
=====================
A SEPARATE, standalone script - it does NOT import or modify anything in
bibliometric_pipeline/ (matcher.py, pipeline.py, config.py, sources/*, .env
are all untouched). If this script has a bug or Scopus access doesn't work
out, your existing OpenAlex/PubMed/Crossref pipeline is completely
unaffected - this only ever reads your pipeline's output and writes to a
brand-new file.

WHAT IT DOES
------------
1. Reads an existing bibliometric_output.xlsx (the output of the main
   pipeline).
2. Finds rows where ANY of the target fields below are blank AND a DOI is
   present - i.e. exactly the gaps the other three sources (OpenAlex/
   PubMed/Crossref) couldn't fill:
     - Affiliation-related: Affliation, First Author Affiliation,
       Author_Affiliation_Map, All Country, Country Count, Multi Institution
     - Abstract (from Scopus's coredata.dc:description - present even when
       the FULL view's author-group detail isn't entitled)
     - Corresponding Author fields: Corresponding Author, Corresponding
       Author Country, Corresponding Author Affiliation (from Scopus's own
       dedicated 'correspondence' element - a first-class, explicitly-
       tagged field in Scopus's schema, unlike OpenAlex's patchy
       is_corresponding flag or PubMed's narrow "Electronic address"
       text-heuristic, both of which came back empty for the vast majority
       of records in this pipeline's own gap-fill run).
   One Scopus API call per DOI supplies all of the above at once, so a row
   missing several of these gets them all filled from a single request.
3. Fills in ONLY the blank cells for those rows. Every other column, and
   every row that's already fully populated, is left completely untouched.
4. Writes the result to a NEW file - never overwrites your original output.

WHY SEPARATE FROM THE MAIN PIPELINE
------------------------------------
You mentioned you only have general (not fully verified) Scopus API access,
so this is deliberately isolated: worst case, this script fails or the API
key doesn't authenticate, and you still have your original, working
OpenAlex/PubMed/Crossref output exactly as it was.

SETUP
-----
1. Copy .env.scopus.example to .env.scopus (same folder as this script) and
   fill in SCOPUS_API_KEY (from https://dev.elsevier.com/apikey/manage).
   Leave SCOPUS_INST_TOKEN blank unless your library gave you one for
   off-campus access.
2. IMPORTANT: the Scopus API authenticates by IP range. It only works when
   this script runs from your institution's network or VPN (unless you have
   an InstToken). Off-campus without a token, every call will fail with a
   401/403 - that's expected, not a bug in this script.

USAGE
-----
    cd bibliometric_pipeline_project
    python3 scopus_gap_filler.py --input ~/Desktop/bibliometric_output.xlsx

    (Run it again later to resume - it checkpoints progress and respects
    Scopus's weekly quota; if the quota runs out mid-run, it stops cleanly
    and picks back up next time you run it.)
"""

import argparse
import json
import os
import sys
import time

import pandas as pd
import requests

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


# ---------------------------------------------------------------------
# Config - loaded from .env.scopus (next to this script), NOT the main
# pipeline's .env.
# ---------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_SCOPUS_PATH = os.path.join(SCRIPT_DIR, ".env.scopus")

if load_dotenv is not None and os.path.exists(ENV_SCOPUS_PATH):
    load_dotenv(ENV_SCOPUS_PATH)

SCOPUS_API_KEY = os.environ.get("SCOPUS_API_KEY", "").strip()
SCOPUS_INST_TOKEN = os.environ.get("SCOPUS_INST_TOKEN", "").strip()
SCOPUS_CONTACT_EMAIL = os.environ.get("SCOPUS_CONTACT_EMAIL", "").strip()

BASE_URL = "https://api.elsevier.com/content/abstract/doi"

# Columns this script is allowed to touch. Everything else in the sheet is
# copied through unchanged.
AFFILIATION_COLUMNS = [
    "Affliation", "First Author Affiliation", "Author_Affiliation_Map",
    "All Country", "Country Count", "Multi Institution",
]
ABSTRACT_COLUMNS = ["Abstract"]
CORRESPONDENCE_COLUMNS = [
    "Corresponding Author", "Corresponding Author Country", "Corresponding Author Affiliation",
]
TARGET_COLUMNS = AFFILIATION_COLUMNS + ABSTRACT_COLUMNS + CORRESPONDENCE_COLUMNS
NEW_STATUS_COLUMN = "Scopus Gap-Fill Status"

MIN_INTERVAL_SECONDS = 1.0  # polite pacing; adjust if your quota allows more

# A 401/403 on ONE record often just means "your subscription isn't
# entitled to this particular publisher's content" (Elsevier's
# AUTHORIZATION_ERROR), not a broken key/network - so it shouldn't halt the
# whole run. But if the key/network really is broken, EVERY call will fail
# this way, so we only treat it as fatal once too many happen in a row.
MAX_CONSECUTIVE_AUTH_FAILURES = 5


# ---------------------------------------------------------------------
# Defensive helpers - Elsevier's JSON collapses a list of one item down to
# a bare dict, so every nested field needs this before you can iterate it.
# ---------------------------------------------------------------------
def _as_list(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _text(x):
    """Elsevier text nodes are sometimes {'$': 'value'}, sometimes a bare string."""
    if x is None:
        return ""
    if isinstance(x, dict):
        return str(x.get("$", "")).strip()
    return str(x).strip()


def _org_names(affiliation_node):
    """Extract organization name(s) from an author-group 'affiliation' node."""
    if not affiliation_node:
        return []
    orgs = _as_list(affiliation_node.get("organization"))
    names = [_text(o) for o in orgs]
    return [n for n in names if n]


# ---------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------
def scopus_fetch_by_doi(doi, session):
    """Returns (json_dict_or_None, status_note).

    status_note is one of: 'ok', 'not_found', 'quota_exceeded',
    'auth_failed', 'error:<detail>'
    """
    if not SCOPUS_API_KEY:
        return None, "error:no SCOPUS_API_KEY set in .env.scopus"

    headers = {
        "X-ELS-APIKey": SCOPUS_API_KEY,
        "Accept": "application/json",
    }
    if SCOPUS_INST_TOKEN:
        headers["X-ELS-Insttoken"] = SCOPUS_INST_TOKEN
    if SCOPUS_CONTACT_EMAIL:
        headers["User-Agent"] = f"jarvis-scholar-scopus-gap-filler (mailto:{SCOPUS_CONTACT_EMAIL})"

    url = f"{BASE_URL}/{doi}"

    def _do_request(view):
        params = {"httpAccept": "application/json"}
        if view:
            params["view"] = view
        return session.get(url, headers=headers, params=params, timeout=25)

    try:
        # view=FULL is required to get per-author affiliation detail
        # (item.bibrecord.head.author-group) - the default view only
        # returns the paper-level affiliation list, which is all the
        # first real run got us.
        r = _do_request("FULL")
        if r.status_code in (401, 403):
            # FULL might not be entitled at this subscription tier - fall
            # back to the default view rather than losing what already
            # worked (the paper-level affiliation list).
            r_default = _do_request(None)
            if r_default.status_code == 200:
                r = r_default
    except Exception as e:
        return None, f"error:{e}"

    remaining = r.headers.get("X-RateLimit-Remaining")
    if remaining is not None:
        try:
            if int(remaining) <= 0:
                return None, "quota_exceeded"
        except ValueError:
            pass

    if r.status_code == 404:
        return None, "not_found"
    if r.status_code == 429:
        return None, "quota_exceeded"
    if r.status_code in (401, 403):
        # Elsevier's gateway sometimes returns 401/403 for "over quota" or
        # a mis-set requestor header instead of a clean 429 - the response
        # body usually names the real reason (e.g. "QUOTA_EXCEEDED",
        # "AUTHENTICATION_ERROR"), so surface it instead of guessing.
        try:
            body_snippet = r.text[:200].replace("\n", " ")
        except Exception:
            body_snippet = ""
        return None, f"auth_failed: {body_snippet}"
    if r.status_code != 200:
        return None, f"error:HTTP {r.status_code}"

    try:
        return r.json(), "ok"
    except Exception as e:
        return None, f"error:bad JSON ({e})"


# ---------------------------------------------------------------------
# Parsing - defensive; a schema surprise on one record must not kill the run
# ---------------------------------------------------------------------
def parse_scopus_affiliations(data):
    """Extract what we can from a Scopus abstracts-retrieval-response.

    Returns a dict with whatever of these keys it managed to fill:
      institutes (list[str]), first_author_aff (str),
      aff_map (dict[name->aff]), countries (list[str])
    Anything it can't confidently extract is simply omitted, not guessed.
    """
    out = {"institutes": [], "first_author_aff": "", "aff_map": {}, "countries": []}
    root = (data or {}).get("abstracts-retrieval-response") or {}

    # --- Path 1: top-level 'affiliation' list - paper-level institutions,
    # not tied to a specific author, but reliable and simple. ---
    for aff in _as_list(root.get("affiliation")):
        name = _text(aff.get("affilname"))
        country = _text(aff.get("affiliation-country"))
        if name:
            out["institutes"].append(name)
        if country:
            out["countries"].append(country)

    # --- Path 2: item.bibrecord.head.author-group - per-author affiliation,
    # used for first_author_aff / aff_map. Wrapped separately: if Elsevier's
    # schema doesn't match what we expect here, Path 1's data still stands. ---
    try:
        head = ((root.get("item") or {}).get("bibrecord") or {}).get("head") or {}
        groups = _as_list(head.get("author-group"))
        for group in groups:
            org_names = _org_names(group.get("affiliation"))
            city = _text((group.get("affiliation") or {}).get("city"))
            country = _text((group.get("affiliation") or {}).get("country"))
            aff_text = ", ".join([n for n in (org_names[0] if org_names else "", city, country) if n]) \
                if org_names else ", ".join([x for x in (city, country) if x])
            if country and country not in out["countries"]:
                out["countries"].append(country)
            for au in _as_list(group.get("author")):
                given = _text(au.get("ce:given-name"))
                surname = _text(au.get("ce:surname"))
                indexed = _text(au.get("ce:indexed-name"))
                name = indexed or " ".join(x for x in (given, surname) if x)
                if name and aff_text:
                    out["aff_map"][name] = aff_text
                    if not out["first_author_aff"]:
                        out["first_author_aff"] = aff_text
    except Exception as e:
        sys.stderr.write(f"   [scopus parse] author-group parsing skipped: {e}\n")

    out["institutes"] = list(dict.fromkeys(out["institutes"]))  # dedupe, keep order
    out["countries"] = list(dict.fromkeys(out["countries"]))
    return out


def parse_scopus_abstract_and_correspondence(data):
    """Extract the abstract text and the corresponding author's
    name/affiliation/country from a Scopus abstracts-retrieval-response.

    Abstract lives in 'coredata' (dc:description), which is present
    regardless of view/entitlement level - it's paper-level metadata, not
    gated behind the FULL view like per-author affiliation detail.

    Corresponding author lives in item.bibrecord.head.correspondence - a
    dedicated, explicitly-tagged field in Scopus's own schema (unlike
    OpenAlex's patchy is_corresponding flag or PubMed's narrow "Electronic
    address" heuristic). Only present in FULL view and only when the
    publisher submitted this info to Elsevier - defensively wrapped so a
    missing/differently-shaped node just means an empty result, not a crash.

    Returns a dict with whatever of these keys it managed to fill:
      abstract (str), corresponding_author (str),
      corresponding_country (str), corresponding_affiliation (str)
    """
    out = {"abstract": "", "corresponding_author": "", "corresponding_country": "", "corresponding_affiliation": ""}
    root = (data or {}).get("abstracts-retrieval-response") or {}

    # --- Abstract ---
    try:
        coredata = root.get("coredata") or {}
        out["abstract"] = _text(coredata.get("dc:description"))
    except Exception as e:
        sys.stderr.write(f"   [scopus parse] abstract parsing skipped: {e}\n")

    # --- Corresponding author ---
    try:
        head = ((root.get("item") or {}).get("bibrecord") or {}).get("head") or {}
        corr = head.get("correspondence")
        if corr:
            # A record can in principle list more than one correspondence
            # entry - take the first, consistent with how this pipeline
            # already treats "corresponding author" as a single value.
            corr = _as_list(corr)[0]
            person = corr.get("person") or {}
            given = _text(person.get("ce:given-name"))
            surname = _text(person.get("ce:surname"))
            indexed = _text(person.get("ce:indexed-name"))
            out["corresponding_author"] = indexed or " ".join(x for x in (given, surname) if x)

            corr_aff = corr.get("affiliation") or {}
            org_names = _org_names(corr_aff)
            city = _text(corr_aff.get("city"))
            country = _text(corr_aff.get("country"))
            out["corresponding_country"] = country
            out["corresponding_affiliation"] = ", ".join(
                [n for n in (org_names[0] if org_names else "", city, country) if n]
            )
    except Exception as e:
        sys.stderr.write(f"   [scopus parse] correspondence parsing skipped: {e}\n")

    return out


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="Path to the existing pipeline output (.xlsx)")
    ap.add_argument("--output", default=None,
                     help="Path to write the filled copy (default: <input>_scopus_filled.xlsx)")
    ap.add_argument("--checkpoint", default=None,
                     help="Path for this script's own checkpoint (default: <input>_scopus_checkpoint.csv)")
    args = ap.parse_args()

    input_path = os.path.expanduser(args.input)
    if not os.path.exists(input_path):
        sys.exit(f"ERROR: input file not found: {input_path}")

    base, ext = os.path.splitext(input_path)
    output_path = os.path.expanduser(args.output) if args.output else f"{base}_scopus_filled.xlsx"
    checkpoint_path = os.path.expanduser(args.checkpoint) if args.checkpoint else f"{base}_scopus_checkpoint.csv"

    print("=" * 70)
    print("Scopus affiliation gap-filler (standalone - main pipeline untouched)")
    print(f"Input     : {input_path}")
    print(f"Output    : {output_path}")
    print(f"Checkpoint: {checkpoint_path}")
    print("=" * 70)

    if not SCOPUS_API_KEY:
        sys.exit(f"ERROR: no SCOPUS_API_KEY found. Copy .env.scopus.example to "
                  f"{ENV_SCOPUS_PATH} and fill in your key.")

    df = pd.read_excel(output_path if os.path.exists(output_path) else input_path)
    for col in TARGET_COLUMNS + [NEW_STATUS_COLUMN]:
        if col not in df.columns:
            df[col] = ""
        # Force object dtype so writing a string into a currently-all-blank
        # (NaN/float64) column doesn't hit pandas' dtype-mismatch warning.
        df[col] = df[col].astype(object)

    sno_col = "Sno." if "Sno." in df.columns else ("Sno" if "Sno" in df.columns else None)
    if sno_col is None:
        sys.exit("ERROR: expected a 'Sno.' or 'Sno' column in the input file - is this really "
                  "the pipeline's output file?")
    if "DOI" not in df.columns:
        sys.exit("ERROR: expected a 'DOI' column in the input file.")

    # Resume support: skip Sno values already attempted (success OR a final
    # no-record/auth-failure - only true quota-exceeded stops get retried).
    already_done = set()
    if os.path.exists(checkpoint_path):
        ck = pd.read_csv(checkpoint_path, dtype={sno_col: str})
        already_done = set(ck[sno_col].astype(str))
        print(f"Resuming: {len(already_done)} record(s) already attempted per checkpoint.")

    def _blank(v):
        # NB: pandas represents a blank cell as NaN (a float), and
        # `float('nan') or ""` evaluates to nan (NaN is truthy in Python) -
        # so this must use pd.isna(), not `or ""`, to correctly detect
        # blank cells.
        return pd.isna(v) or str(v).strip() == "" or str(v).strip().lower() == "nan"

    def needs_fill(row):
        doi = "" if pd.isna(row.get("DOI")) else str(row.get("DOI")).strip()
        if not doi or doi.lower() == "nan":
            return False
        return any(_blank(row.get(c)) for c in TARGET_COLUMNS)

    targets = df[df.apply(needs_fill, axis=1)]
    targets = targets[~targets[sno_col].astype(str).isin(already_done)]
    print(f"{len(targets)} row(s) need a Scopus lookup (blank affiliation/abstract/corresponding-author "
          f"+ DOI present, not yet attempted).")

    if len(targets) == 0:
        print("Nothing to do. Writing output unchanged.")
        df.to_excel(output_path, index=False)
        return

    session = requests.Session()
    checkpoint_rows = []
    if os.path.exists(checkpoint_path):
        checkpoint_rows = pd.read_csv(checkpoint_path, dtype={sno_col: str}).to_dict("records")

    stopped_early = False
    consecutive_auth_failures = 0
    proven_working = False  # True once we've seen ANY non-auth-error response
    last_call = 0.0
    for idx, row in targets.iterrows():
        sno = str(row[sno_col])
        doi = str(row["DOI"]).strip()

        elapsed = time.monotonic() - last_call
        if elapsed < MIN_INTERVAL_SECONDS:
            time.sleep(MIN_INTERVAL_SECONDS - elapsed)
        data, note = scopus_fetch_by_doi(doi, session)
        last_call = time.monotonic()

        if note == "quota_exceeded":
            print(f"[{sno}] Scopus weekly quota exhausted - stopping here. "
                  f"Run this script again later to pick up where it left off.")
            stopped_early = True
            break

        if note.startswith("auth_failed"):
            # A 401/403 on one record usually means Elsevier's entitlement
            # doesn't cover THIS record's publisher/content type - not that
            # your key or network is broken. This can legitimately happen
            # several times in a row if the input file has several DOIs
            # from the same unauthorized publisher back to back (this is
            # exactly what happened with a run of 10.55487/... DOIs) - so
            # once we've PROVEN the key/network works (any successful or
            # clean-404 response so far in this run), we no longer treat
            # a run of auth errors as a reason to stop.
            consecutive_auth_failures += 1
            reason = note[len('auth_failed:'):].strip()
            df.at[idx, NEW_STATUS_COLUMN] = f"Scopus authorization error (skipped): {reason}"
            print(f"[{sno}] Scopus authorization error (not entitled for this record) - skipping. {reason}")
            checkpoint_rows.append({sno_col: sno, "note": note})
            pd.DataFrame(checkpoint_rows).to_csv(checkpoint_path, index=False)
            df.to_excel(output_path, index=False)

            if not proven_working and consecutive_auth_failures >= MAX_CONSECUTIVE_AUTH_FAILURES:
                print(f"\n{MAX_CONSECUTIVE_AUTH_FAILURES} authorization errors in a row with NO successful "
                      f"call yet this run - this looks like a systemic problem (key/network/entitlement), "
                      f"not per-record. Stopping here so we don't burn through your quota on calls that will "
                      f"just fail the same way.")
                stopped_early = True
                break
            continue

        consecutive_auth_failures = 0
        proven_working = True

        if note == "ok" and data:
            filled_fields = []

            # NB: every write below is guarded by _blank(df.at[idx, col]) -
            # needs_fill() only requires ONE target column to be blank to
            # trigger a fetch, so a row can easily have (say) Affliation
            # blank but Abstract already filled from the main pipeline.
            # Without the guard, Scopus's own abstract text could silently
            # clobber a perfectly good, already-filled cell - breaking the
            # same "only fill empty cells" contract gap_fill_by_doi.py
            # established for the main pipeline's own gap-filler.
            parsed = parse_scopus_affiliations(data)
            if parsed["institutes"] and _blank(df.at[idx, "Affliation"]):
                df.at[idx, "Affliation"] = "; ".join(parsed["institutes"])
                filled_fields.append("Affliation")
            if parsed["first_author_aff"] and _blank(df.at[idx, "First Author Affiliation"]):
                df.at[idx, "First Author Affiliation"] = parsed["first_author_aff"]
                filled_fields.append("First Author Affiliation")
            if parsed["aff_map"] and _blank(df.at[idx, "Author_Affiliation_Map"]):
                df.at[idx, "Author_Affiliation_Map"] = json.dumps(parsed["aff_map"], ensure_ascii=False)
                filled_fields.append("Author_Affiliation_Map")
            if parsed["countries"] and _blank(df.at[idx, "All Country"]):
                df.at[idx, "All Country"] = "; ".join(parsed["countries"])
                df.at[idx, "Country Count"] = len(parsed["countries"])
                df.at[idx, "Multi Institution"] = "Yes" if len(parsed["institutes"]) > 1 else (
                    "No" if parsed["institutes"] else "")
                filled_fields.append("All Country/Country Count/Multi Institution")

            corr = parse_scopus_abstract_and_correspondence(data)
            if corr["abstract"] and _blank(df.at[idx, "Abstract"]):
                df.at[idx, "Abstract"] = corr["abstract"]
                filled_fields.append("Abstract")
            if corr["corresponding_author"] and _blank(df.at[idx, "Corresponding Author"]):
                df.at[idx, "Corresponding Author"] = corr["corresponding_author"]
                filled_fields.append("Corresponding Author")
            if corr["corresponding_country"] and _blank(df.at[idx, "Corresponding Author Country"]):
                df.at[idx, "Corresponding Author Country"] = corr["corresponding_country"]
                filled_fields.append("Corresponding Author Country")
            if corr["corresponding_affiliation"] and _blank(df.at[idx, "Corresponding Author Affiliation"]):
                df.at[idx, "Corresponding Author Affiliation"] = corr["corresponding_affiliation"]
                filled_fields.append("Corresponding Author Affiliation")

            if filled_fields:
                status = f"Filled from Scopus: {', '.join(filled_fields)}"
            else:
                # Confirmed via dump_scopus_raw.py: when view=FULL gets a
                # 401/403 and falls back to the default view, the response
                # has ONLY top-level 'affiliation' + 'coredata' - no 'item'
                # key at all. That's where author-group, correspondence, AND
                # the abstract's full detail all live - so "nothing
                # extracted" in that case is a genuine entitlement gap
                # (your institutional key isn't entitled to FULL view for
                # this record/publisher), not a parser bug or schema
                # surprise. Distinguishing the two so this status column is
                # actually diagnostic instead of always pointing at stderr.
                has_full_view = "item" in ((data or {}).get("abstracts-retrieval-response") or {})
                if has_full_view:
                    status = ("Scopus record found (FULL view) but no target fields extracted - "
                               "genuine schema surprise, worth checking with dump_scopus_raw.py")
                else:
                    status = ("Scopus record found but FULL view not entitled for this record/publisher "
                               "(fell back to basic view - no abstract or per-author/correspondence "
                               "detail available in any view this key can access)")
            df.at[idx, NEW_STATUS_COLUMN] = status
            print(f"[{sno}] {status}")
        elif note == "not_found":
            df.at[idx, NEW_STATUS_COLUMN] = "No Scopus record for this DOI"
            print(f"[{sno}] No Scopus record for this DOI.")
        else:
            df.at[idx, NEW_STATUS_COLUMN] = f"Fetch error: {note}"
            print(f"[{sno}] Fetch error: {note}")

        checkpoint_rows.append({sno_col: sno, "note": note})
        pd.DataFrame(checkpoint_rows).to_csv(checkpoint_path, index=False)
        df.to_excel(output_path, index=False)

    print(f"\nWrote {output_path}")
    if stopped_early:
        print("Stopped early (quota or auth) - re-run the same command later to resume.")
    print("Done. Original pipeline output was never modified.")


if __name__ == "__main__":
    main()
