"""
deduplicate_output.py
======================
Standalone, additive script: detects rows in a finished pipeline output that
resolved to the SAME DOI (i.e. the same paper was submitted more than once
under a different Sno - confirmed to happen in real batches, e.g. one row
had the full citation string pasted in as the "title" instead of just the
title, and separately got matched to the same paper as a cleaner duplicate
entry). Never deletes or overwrites anything - writes a new file with two
extra columns added, so every original row and its provenance is still
fully visible and auditable.

WHY THIS MATTERS: Biblioshiny/VOSviewer build co-authorship, citation, and
keyword-co-occurrence networks by counting each row as one paper. A paper
appearing twice inflates those counts and quietly distorts the analysis -
this is the kind of silent corruption this project has been careful to
catch and flag rather than let slide (see the earlier DOI-mismatch bug).

NEW COLUMNS ADDED (nothing else in the file is changed):
  - Duplicate Group ID   : shared numeric ID for every row sharing a DOI
                           with >=1 other row; blank if this row's DOI is
                           unique in the file.
  - Dedup Status         : "Unique" | "Primary (kept for analysis)" |
                           "Duplicate (same DOI as Sno <primary_sno> -
                           excluded from Biblioshiny/VOSviewer export)"

HOW THE "PRIMARY" ROW IS CHOSEN within a duplicate-DOI group: the row whose
own Clean Title (the raw input title) is the closest fuzzy match to the
final matched TITLE wins - in practice this picks whichever original
submission was the cleanest ONE-LINE title, rather than e.g. a row where
someone pasted a full citation string ("Author, Year. Title. Journal.
https://doi.org/...") into the title field. Ties broken by lowest Sno
(first submission wins). This is a documented heuristic, not a guarantee -
spot-check the "Duplicate Group ID" groups in the output if in doubt.

export_scopus_csv.py automatically skips any row whose Dedup Status starts
with "Duplicate" IF this column is present, so the recommended workflow is:

    python3 deduplicate_output.py --input bibliometric_output_full.xlsx \
                                   --output bibliometric_output_full_deduped.xlsx
    python3 export_scopus_csv.py --input bibliometric_output_full_deduped.xlsx \
                                  --output scopus_ready.csv
"""

import argparse
import re
import unicodedata

import pandas as pd

try:
    from rapidfuzz import fuzz as _rf_fuzz

    def fuzzy_score(a, b):
        return float(_rf_fuzz.token_set_ratio(a, b))
except Exception:
    import difflib

    def fuzzy_score(a, b):
        return difflib.SequenceMatcher(None, a, b).ratio() * 100.0


_DASH_LIKE = "‐‑‒–—―−"
_DASH_TRANS = str.maketrans({c: "-" for c in _DASH_LIKE})


def _clean_for_match(s):
    """Mirrors bibliometric_pipeline/text_utils.py's clean_for_match() -
    including the dash-translation fix (see that file for why: unicode
    dash-like characters get silently DROPPED, not converted to a
    separator, by ascii-encode-ignore, which can merge two words into one
    token and deflate fuzzy scores)."""
    if not s:
        return ""
    s = str(s).translate(_DASH_TRANS)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# ---------------------------------------------------------------------
# Citation-dump detection: fuzzy score ALONE is not reliable for picking
# the "cleanest" original title. Real example found in this batch: one
# duplicate had a minor spacing glitch ("andMD", "ofNewly" - missing
# spaces), which LOWERED its fuzzy score against the true title, while the
# other duplicate had the ENTIRE citation pasted in as the title
# ("...Efficacy. ChemistrySelect. 2025 Jan;10(3):e202404121.") - which
# scored HIGHER purely because it contains the correctly-spaced true title
# as a substring, plus extra tokens token_set_ratio mostly ignores. Picking
# by score alone would have kept the messy citation-dump row as primary.
# So: detect citation-dump patterns explicitly and always rank them below
# non-dump titles, regardless of fuzzy score.
# ---------------------------------------------------------------------
_CITATION_DUMP_PATTERNS = [
    re.compile(r"10\.\d{4,9}/\S+"),                                   # embedded DOI
    re.compile(r"https?://doi\.org", re.I),                           # DOI URL
    re.compile(r"\(\d+\):\s*\S"),                                     # "(3):e202404121" vol(issue):page
    re.compile(r";\s*\d+\s*:\s*\d+"),                                 # ";362:123364" vol;page
    re.compile(r"\b\d{4}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\b"),  # "2025 Jan" / "2025 Feb 1"
    re.compile(r"^[A-Z][a-zA-Z'\-]{1,20}\s?[A-Z]?\.?,\s+[A-Z][a-zA-Z'\-]{1,20}\s?[A-Z]?\.?,"),  # "Surname X, Surname Y," author-list start
    re.compile(r"\bet al\."),                                         # "et al."
]


def _looks_like_citation_dump(title):
    if not title:
        return False
    t = str(title)
    if len(t) > 220:
        return True
    return any(p.search(t) for p in _CITATION_DUMP_PATTERNS)


def _blank(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "" or str(v).strip().lower() == "nan"


def _sno_sort_key(sno):
    """Numeric-aware sort key for the 'lowest Sno wins' tiebreak. Sno values
    are typically plain integers as strings ('94', '994', '1005') with no
    zero-padding - sorting the STRING directly is a real bug here, since
    '1005' < '94' lexicographically (the '1'..'9' first-character compare)
    even though 94 < 1005 numerically. Falls back to the raw string for any
    non-numeric Sno (e.g. 'AR-1045', 'Ex-94') so those still sort
    deterministically, just not usefully-numerically - fine, since this
    tiebreak only matters when every earlier tiebreak already tied."""
    s = str(sno)
    try:
        return (0, int(s))
    except ValueError:
        return (1, s)


def _read_any(path):
    if str(path).lower().endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_excel(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="Path to the pipeline's output/checkpoint (.xlsx or .csv)")
    ap.add_argument("--output", required=True, help="Path to write the augmented .xlsx (adds 2 columns, changes nothing else)")
    args = ap.parse_args()

    df = _read_any(args.input)
    print(f"Read {len(df)} rows from {args.input}")

    if "DOI" not in df.columns:
        print("No DOI column found - nothing to deduplicate against. Writing file through unchanged.")
        df["Duplicate Group ID"] = ""
        df["Dedup Status"] = "Unique"
        df.to_excel(args.output, index=False)
        return

    doi_clean = df["DOI"].astype(str).str.strip()
    doi_clean = doi_clean.where(~doi_clean.str.lower().isin(["", "nan"]), other="")

    dup_group_id = pd.Series("", index=df.index, dtype=object)
    dedup_status = pd.Series("Unique", index=df.index, dtype=object)

    group_counter = 0
    n_groups = 0
    n_duplicate_rows = 0

    for doi, idxs in doi_clean.groupby(doi_clean).groups.items():
        if not doi or len(idxs) < 2:
            continue
        group_counter += 1
        n_groups += 1
        gid = f"DUPGRP-{group_counter:04d}"

        # Rank each row in the group: non-citation-dump titles always beat
        # citation-dump titles first; within the same tier, higher fuzzy
        # score to the final matched TITLE wins; then shorter title (more
        # likely to be "just the title"); then lowest Sno as final tiebreak.
        scored = []
        for idx in idxs:
            row = df.loc[idx]
            own_title_raw = row.get("Clean Title", "")
            own_title = _clean_for_match(own_title_raw)
            matched_title = _clean_for_match(row.get("TITLE", ""))
            score = fuzzy_score(own_title, matched_title) if own_title and matched_title else 0.0
            is_dump = _looks_like_citation_dump(own_title_raw)
            sno = row.get("Sno.", idx)
            scored.append((is_dump, -score, len(str(own_title_raw)), _sno_sort_key(sno), idx))
        scored.sort()
        primary_idx = scored[0][4]
        primary_sno = df.loc[primary_idx].get("Sno.", primary_idx)

        for is_dump, neg_score, tlen, sno, idx in scored:
            dup_group_id.loc[idx] = gid
            if idx == primary_idx:
                dedup_status.loc[idx] = "Primary (kept for analysis)"
            else:
                dedup_status.loc[idx] = (f"Duplicate (same DOI as Sno {primary_sno} - "
                                          f"excluded from Biblioshiny/VOSviewer export)")
                n_duplicate_rows += 1

    df["Duplicate Group ID"] = dup_group_id
    df["Dedup Status"] = dedup_status
    df.to_excel(args.output, index=False)

    print(f"Wrote {len(df)} rows to {args.output} (all original rows preserved)")
    print(f"\nDuplicate-DOI groups found: {n_groups}")
    print(f"Rows flagged as secondary duplicates (excluded from downstream export): {n_duplicate_rows}")
    print(f"Rows kept as primary/unique: {len(df) - n_duplicate_rows}")
    if n_groups:
        print("\nSpot-check these groups before trusting the auto-picked primary row:")
        for gid in sorted(set(g for g in dup_group_id if g)):
            grp = df[dup_group_id == gid]
            cols = [c for c in ["Sno.", "Clean Title", "Dedup Status"] if c in df.columns]
            print(f"\n  {gid}:")
            for _, r in grp[cols].iterrows():
                print(f"    {r.to_dict()}")


if __name__ == "__main__":
    main()
