"""
icmr_institute_tagger.py
==========================
Standalone script for tagging an EXISTING file (one that never went
through the pipeline's own extraction run - e.g. a manually-curated,
already-final Included_studies.xlsx) with which ICMR institute each row
belongs to.

As of this version, the actual matching logic (the 28-institute list and
all the matching rules) lives in bibliometric_pipeline/icmr_institutes.py,
the SAME module the main pipeline now uses automatically (see matcher.py,
enabled via the "icmr_institute" column group in
BIBLIO_OPTIONAL_COLUMN_GROUPS). This script just re-imports it, so a fresh
pipeline run and a post-hoc tag of an older file always agree, and any
future fix to the matching rules only has to be made in one place.

MULTIPLE INSTITUTES PER ROW: a single record can list co-authors from more
than one ICMR institute (real multi-site collaborations - confirmed in
144/2632 rows of one real dataset). This script tags a row with EVERY
distinct institute it can identify across all its affiliation columns,
semicolon-joined - not just the first one found.

ALSO CHECKS Author_Affiliation_Map: the three flat affiliation columns
(Affliation / First Author Affiliation / Corresponding Author Affiliation)
don't always carry every author's institute-specific text - e.g. a middle
co-author's specific institute can be missing from all three, or the
"Affliation" rollup can be coarser than the per-author detail. If the file
has an "Author_Affiliation_Map" column (a JSON dict of author name ->
affiliation text, added by the pipeline), each author's own affiliation
text is ALSO checked - confirmed to surface an additional 47/2632 rows'
worth of institute detail the three flat columns alone missed.

PER-SEGMENT MATCHING (not whole-blob): "Affliation" is a semicolon-joined
list of every co-author's own affiliation string. Each entry is checked
SEPARATELY rather than matching against the whole joined blob at once -
matching the whole blob let a signal from ONE co-author's segment
(e.g. a bare "ICMR" mention, or the word "NIHR") wrongly validate an
unrelated match found only in a DIFFERENT co-author's segment. Confirmed
on real data: one row had a co-author from an unrelated "NIMS University"
whose bare "NIMS" acronym got matched to ICMR's National Institute for
Research in Digital Health only because a DIFFERENT co-author's segment
happened to mention "ICMR-DHR" elsewhere in the same row - a false
positive fixed by checking each co-author's segment on its own.

Reads an existing pipeline output file and writes a new file with one
extra column added: "ICMR Institute (Current Name)" - blank if the
affiliation doesn't mention ICMR at all, or a generic label ("ICMR
Collaborating Centre of Excellence..." / "ICMR Headquarters...") if ICMR
is mentioned but no specific institute could be pinned down. Per explicit
instruction, a bare/generic "ICMR" mention that can't be pinned to a
specific institute is classified as ICMR Headquarters (there used to be a
separate "institute not identified" label for this case - it's now folded
into the Headquarters label).

Usage:
  python3 icmr_institute_tagger.py --input Included_studies.xlsx --output Included_studies_icmr_tagged.xlsx
"""

import argparse
import json
import sys

import pandas as pd

from bibliometric_pipeline.icmr_institutes import resolve_all_icmr_institutes

_CCOE_LABEL = "ICMR Collaborating Centre of Excellence (external partner institution, not one of the 28 core institutes)"
_HQ_LABEL = "ICMR Headquarters, New Delhi (not a constituent institute)"
_PSEUDO_LABELS = {_CCOE_LABEL, _HQ_LABEL}  # can appear ALONGSIDE a real institute in a multi-value cell
_GENERIC_LABELS = {_CCOE_LABEL, _HQ_LABEL}  # can appear ON THEIR OWN (no real institute)


def _read_any(path):
    if str(path).lower().endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_excel(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="Path to the pipeline output (.xlsx or .csv)")
    ap.add_argument("--output", required=True, help="Path to write the tagged copy")
    args = ap.parse_args()

    df = _read_any(args.input)
    print(f"Read {len(df)} rows from {args.input}")

    aff_cols = [c for c in ("Affliation", "First Author Affiliation", "Corresponding Author Affiliation") if c in df.columns]
    if not aff_cols:
        sys.exit("ERROR: no affiliation column found (expected 'Affliation' or similar).")

    has_aff_map = "Author_Affiliation_Map" in df.columns
    if has_aff_map:
        print("Found 'Author_Affiliation_Map' - also checking each author's own affiliation text.")

    def _per_author_texts(raw_json):
        if not raw_json or (isinstance(raw_json, float)):
            return []
        try:
            amap = json.loads(raw_json)
        except (TypeError, ValueError):
            return []
        if not isinstance(amap, dict):
            return []
        return list(amap.values())

    def _split_segments(text):
        """Splits a semicolon-joined affiliation field back into its
        individual per-author entries, so each is matched on its own
        instead of as part of one combined blob (see PER-SEGMENT MATCHING
        note above)."""
        if not text or (isinstance(text, float)):
            return []
        return [s.strip() for s in str(text).split(";") if s.strip()]

    def resolve_row(row):
        texts = []
        for col in aff_cols:
            texts.extend(_split_segments(row.get(col, "")))
        if has_aff_map:
            texts.extend(_per_author_texts(row.get("Author_Affiliation_Map")))
        return resolve_all_icmr_institutes(*texts)

    df["ICMR Institute (Current Name)"] = df.apply(resolve_row, axis=1)

    col = df["ICMR Institute (Current Name)"]
    # Explode every non-blank cell into its individual values so a real
    # institute name and a co-mentioned HQ/CCoE label (now additive, not
    # mutually exclusive - see icmr_institutes.py) are counted separately
    # rather than muddled together as one opaque multi-value string.
    exploded_all = col[col != ""].str.split("; ").explode()
    is_pseudo = exploded_all.isin(_PSEUDO_LABELS)
    is_real_institute = ~is_pseudo

    n_specific_rows = int((is_real_institute.groupby(level=0).any()).sum()) if len(exploded_all) else 0
    n_multi_institute_rows = int(exploded_all[is_real_institute].groupby(level=0).size().gt(1).sum()) if is_real_institute.any() else 0

    print(f"Rows with an identifiable ICMR institute: {n_specific_rows}")
    print(f"  of which mention 2+ distinct institutes: {n_multi_institute_rows}")
    print(f"Mentions of ICMR Headquarters (may co-occur with a specific institute in the same row; "
          f"also includes generic 'ICMR mentioned but no specific institute identifiable' cases): "
          f"{int((exploded_all == _HQ_LABEL).sum())}")
    print(f"Mentions of an ICMR Collaborating Centre of Excellence (may co-occur with a specific institute): "
          f"{int((exploded_all == _CCOE_LABEL).sum())}")
    print()
    print("Breakdown by institute (a row mentioning 2+ institutes counts once toward each; "
          "HQ/CCoE excluded here - see totals above):")
    counts = exploded_all[is_real_institute].value_counts()
    for name, n in counts.items():
        print(f"  {n:4d}  {name}")

    df.to_excel(args.output, index=False)
    print(f"\nWrote {len(df)} rows to {args.output}")


if __name__ == "__main__":
    main()
