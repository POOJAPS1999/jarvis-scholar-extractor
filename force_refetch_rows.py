"""
force_refetch_rows.py
========================
Standalone, targeted tool: for a specific, small list of Sno. values where
you've manually corrected the DOI (because the original match was wrong -
e.g. the length-guard false-positive bug), this FULLY OVERWRITES every
enrichment field for just those rows with fresh data re-fetched from the
corrected DOI. This is deliberately different from gap_fill_by_doi.py,
which only ever fills blank cells - here the existing data is known to be
WRONG (not just incomplete), so it needs to be replaced outright, not
preserved.

Columns NEVER touched: Sno., Clean Title (your original input - kept as
the historical record of what was originally submitted).
DOI IS touched: whatever corrected DOI is already in that row's DOI cell
is what gets fetched and re-written back (normalized).

Everything else in the current pipeline schema gets overwritten with
fresh data from OpenAlex/PubMed/Crossref (via matcher.py's own DOI-fetch +
merge logic, including the DOI-mismatch safety net, so a fresh row here
gets exactly the same correctness guarantees as a normal pipeline run).

Usage (pick one way to specify which rows):
  python3 force_refetch_rows.py --input publications.xlsx --output publications_corrected.xlsx --sno-list "Ex-1005,Ex-1215,Ex-1297"
  python3 force_refetch_rows.py --input publications.xlsx --output publications_corrected.xlsx --sno-file corrected_snos.txt
    (one Sno per line in the file)
"""

import argparse
import re
import sys

import pandas as pd

sys.path.insert(0, ".")
from bibliometric_pipeline import matcher  # noqa: E402
from bibliometric_pipeline.sources import openalex, crossref, pubmed  # noqa: E402
from bibliometric_pipeline.text_utils import normalize_doi  # noqa: E402

IDENTITY_COLUMNS = {"Sno.", "Clean Title"}
OVERWRITE_COLUMNS = [c for c in matcher.OUTPUT_COLUMNS if c not in IDENTITY_COLUMNS]

_DOI_IN_URL_RE = re.compile(r"10\.\d{4,9}/[^\s?#]+", re.I)
_PUBMED_PMID_RE = re.compile(r"pubmed\.ncbi\.nlm\.nih\.gov/(\d+)", re.I)


def resolve_doi_from_source_link(source_link):
    """Real-world case that prompted this: the DOI column itself was wrong
    (ACS journals' '.s001'/'.s002'/'.s003' Supporting-Information suffix
    got captured instead of the actual article DOI), but the user
    corrected the Source Link instead of the DOI cell. Extract the real
    DOI from that corrected link:
      1. Most publisher URLs (pubs.acs.org/doi/..., onlinelibrary.wiley.com/
         doi/..., etc.) embed a normal DOI directly in the path - regex it
         out directly.
      2. A PubMed URL (pubmed.ncbi.nlm.nih.gov/<PMID>/) has no DOI in it at
         all - resolve the PMID to its real DOI via a live PubMed lookup
         first.
    Returns (doi, note) - doi is "" if nothing could be resolved.
    """
    link = str(source_link or "").strip()
    if not link:
        return "", "Source Link is empty"

    m = _DOI_IN_URL_RE.search(link)
    if m:
        return normalize_doi(m.group(0)), f"DOI extracted directly from Source Link: {link}"

    m = _PUBMED_PMID_RE.search(link)
    if m:
        pmid = m.group(1)
        try:
            rec = pubmed.pubmed_by_pmid(pmid)
        except Exception as e:
            return "", f"Source Link is a PubMed URL (PMID {pmid}) but the PMID->DOI lookup failed: {e}"
        if rec and rec.get("doi"):
            return normalize_doi(rec["doi"]), f"DOI resolved from PubMed PMID {pmid} (via Source Link)"
        return "", f"Source Link is a PubMed URL (PMID {pmid}) but that record has no DOI on file"

    return "", f"Could not find a DOI or a recognizable PubMed URL in Source Link: {link}"


def _read_any(path):
    if str(path).lower().endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_excel(path)


def fetch_and_build_fresh_row(sno, clean_title, doi):
    oa_raw, pm_raw, cr_raw, fetch_errors = matcher._fetch_doi_all(doi)

    oa_parsed, pm_parsed, cr_parsed = {}, {}, {}
    notes = []

    if oa_raw:
        oa_parsed = openalex.parse_openalex(oa_raw)
        if matcher._doi_mismatch(doi, oa_parsed):
            notes.append("DISCARDED OpenAlex DOI result: mismatch")
            oa_parsed = {}
    if pm_raw:
        pm_parsed = pm_raw
        if matcher._doi_mismatch(doi, pm_parsed):
            notes.append("DISCARDED PubMed DOI result: mismatch")
            pm_parsed = {}
    if cr_raw:
        cr_parsed = crossref.parse_crossref(cr_raw)
        if matcher._doi_mismatch(doi, cr_parsed):
            notes.append("DISCARDED Crossref DOI result: mismatch")
            cr_parsed = {}

    found_anything = bool(oa_parsed or pm_parsed or cr_parsed)
    notes.append("Manually corrected DOI - force re-fetched and overwritten (see force_refetch_rows.py)")
    match_status = "Auto-accepted (DOI) [manually corrected + force re-fetched]" if found_anything else \
        "No match (force re-fetch: corrected DOI not found in any source - verify the DOI is right)"

    fresh_row = matcher.build_row(
        sno, clean_title, doi, oa_parsed, pm_parsed, cr_parsed, notes,
        match_status=match_status, match_score=100.0 if found_anything else 0.0,
        match_source="DOI", fetch_errors=fetch_errors, retry_count=0,
    )
    return fresh_row, fetch_errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="Path to the sheet containing the corrected DOI(s) (.xlsx or .csv)")
    ap.add_argument("--output", required=True, help="Path to write the corrected .xlsx")
    ap.add_argument("--sno-list", help="Comma-separated Sno. values to force-refetch")
    ap.add_argument("--sno-file", help="Path to a text file with one Sno. per line")
    ap.add_argument("--doi-source", choices=["doi-column", "source-link"], default="doi-column",
                     help="Where to get the corrected identifier from: the DOI column itself (default), "
                          "or extract/resolve it from the Source Link column instead (use this if you "
                          "corrected Source Link rather than DOI - e.g. the DOI column had an ACS "
                          "Supporting-Information suffix like '.s001' instead of the real article DOI).")
    args = ap.parse_args()

    if not args.sno_list and not args.sno_file:
        print("ERROR: provide --sno-list or --sno-file")
        sys.exit(1)

    target_snos = set()
    if args.sno_list:
        target_snos |= {s.strip() for s in args.sno_list.split(",") if s.strip()}
    if args.sno_file:
        with open(args.sno_file) as f:
            target_snos |= {line.strip() for line in f if line.strip()}

    df = _read_any(args.input)
    print(f"Read {len(df)} rows from {args.input}")
    print(f"Force re-fetching {len(target_snos)} specific row(s): {sorted(target_snos)}")

    for col in OVERWRITE_COLUMNS:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(object)

    n_done, n_no_doi, n_not_found, n_error = 0, 0, 0, 0

    for i, row in df.iterrows():
        sno = str(row.get("Sno.", ""))
        if sno not in target_snos:
            continue

        if args.doi_source == "source-link":
            doi, note = resolve_doi_from_source_link(row.get("Source Link", ""))
            if not doi:
                print(f"  Sno {sno}: SKIPPED - {note}")
                n_no_doi += 1
                continue
            print(f"  Sno {sno}: {note}")
            df.at[i, "DOI"] = doi  # the old DOI cell was wrong - overwrite it with the resolved correct one
        else:
            doi = normalize_doi(row.get("DOI", ""))
            if not doi:
                print(f"  Sno {sno}: SKIPPED - no DOI present to re-fetch from")
                n_no_doi += 1
                continue

        clean_title = row.get("Clean Title", "")
        print(f"  Sno {sno}: force re-fetching by corrected DOI {doi} ...")
        try:
            fresh_row, fetch_errors = fetch_and_build_fresh_row(sno, clean_title, doi)
        except Exception as e:
            print(f"    ERROR: {e}")
            n_error += 1
            continue

        if fetch_errors:
            print(f"    fetch issue(s): {fetch_errors} - not overwritten, try again")
            n_error += 1
            continue

        for col in OVERWRITE_COLUMNS:
            if col in fresh_row:
                df.at[i, col] = fresh_row[col]

        if "No match" in str(fresh_row.get("Match Status", "")):
            print(f"    WARNING: corrected DOI {doi} was not found in any source - double-check it's correct")
            n_not_found += 1
        else:
            print(f"    overwritten with fresh data: {fresh_row.get('TITLE', '')[:80]!r}")
        n_done += 1

    missing = target_snos - set(df["Sno."].astype(str))
    if missing:
        print(f"\nWARNING: these Sno. values were not found in the input file at all: {sorted(missing)}")

    df.to_excel(args.output, index=False)
    print(f"\nWrote {len(df)} rows to {args.output}")
    print(f"Rows force re-fetched and overwritten: {n_done}")
    print(f"  of which corrected DOI still not found in any source (needs another look): {n_not_found}")
    print(f"Rows skipped (no DOI present): {n_no_doi}")
    print(f"Rows with a fetch error (re-run to retry): {n_error}")


if __name__ == "__main__":
    main()
