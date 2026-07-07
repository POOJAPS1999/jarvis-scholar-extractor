"""
add_icmr_division.py
======================
Standalone, additive script (not wired into the pipeline - reads an
existing finished Excel/CSV, e.g. the ICMR-institute-tagged file, and
writes a new file with one extra column added; nothing else is touched).

For every row, identifies each ICMR institute mentioned (same matching
logic as icmr_institute_tagger.py / the pipeline's "icmr_institute" column
group - imported from the same shared module, so this always agrees with
those) and, when the source affiliation text says so explicitly, ALSO
extracts the division/department mentioned alongside that institute (e.g.
"Division of Immunology, National Institute of Malaria Research,
Ghaziabad" -> institute = ICMR-National Institute of Malaria Research,
Delhi; division = "Immunology").

Only extracts the well-structured, unambiguous phrasings - "Division of
X", "Department of X", "X Division", "X Department" - confirmed against
real data these cover the clear majority of cases that use this
terminology at all (706/1976 real ICMR-institute affiliation segments in
one dataset). Doesn't try to guess at more heterogeneous sub-unit names
("Animal Facility", "Field Unit Guwahati", "Clinical Research
Laboratory") - those are too varied to extract reliably without risking a
wrong label, so they're left blank rather than guessed.

Division is attached to the SPECIFIC institute it was mentioned alongside
in the same affiliation segment (not just the first institute in the
row), so a multi-institute row doesn't cross-attribute one author's
division to a different author's institute. When a single segment
mentions 2+ institutes at once (rare - confirmed 23/1976 segments in real
data), division attribution is skipped for that segment since there's no
reliable way to tell which institute the division phrase belongs to.

Adds ONE new column, "ICMR Division" - per instruction, this holds ONLY
the division/department text itself, NOT the institute name (the
institute is already in the separate "ICMR Institute (Current Name)"
column carried through from the tagged input file). Only institutes that
actually had a division phrase contribute an entry here - an institute
with no division found for it is simply not represented, rather than
padding the list with a blank placeholder. E.g. for a row with two
institutes where only one had a "Division of X" phrase, this column shows
just:
  "Immunology"
Multiple divisions (from different institutes in the same row) are
semicolon-joined, e.g. "Immunology; Epidemiology". Blank if no division
phrase was found anywhere in the row (this does NOT mean no ICMR
institute was identified - check "ICMR Institute (Current Name)" for
that).

Usage:
  python3 add_icmr_division.py --input Included_studies_ICMR_tagged.xlsx \
                                --output Included_studies_ICMR_tagged_with_division.xlsx
"""

import argparse
import json
import sys

import pandas as pd

sys.path.insert(0, ".")
try:
    from bibliometric_pipeline.icmr_institutes import match_institutes_with_divisions
except ImportError:
    sys.exit("ERROR: could not import bibliometric_pipeline - run this script from the "
             "bibliometric_pipeline_project folder.")

AFF_COLS = ["Affliation", "First Author Affiliation", "Corresponding Author Affiliation"]


def _blank(v):
    return (v is None or (isinstance(v, float) and pd.isna(v))
            or str(v).strip() == "" or str(v).strip().lower() == "nan")


def _parse_aff_map(raw_json):
    if _blank(raw_json):
        return {}
    try:
        amap = json.loads(raw_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return amap if isinstance(amap, dict) else {}


def _row_segments(row):
    """Every distinct per-author-ish affiliation segment available for this
    row: the combined 'Affliation' column AND the flat First/Corresponding
    Author Affiliation columns, each split back into individual
    (semicolon-joined) entries, plus every value in the
    Author_Affiliation_Map JSON if present - the same sources
    icmr_institute_tagger.py and add_collaboration_icmr_flags.py already
    check for institute/ICMR-flag purposes, just kept as SEPARATE segments
    here so division extraction stays attributable to the right author.

    Splitting First/Corresponding Author Affiliation on ";" too (not just
    "Affliation") matters: confirmed on real data that a single
    "Corresponding Author Affiliation" cell can itself list that person's
    OWN two unrelated affiliations semicolon-joined (e.g. "Academy of
    Scientific and Innovative Research, AcSIR Headquarters, Ghaziabad;
    Division of Vector Borne Diseases, ICMR-National Institute for
    Research in Tribal Health, Jabalpur") - checking it as ONE combined
    string let "AcSIR Headquarters" get mistaken for "ICMR Headquarters"
    purely because the word "icmr" appeared elsewhere in the same cell."""
    segments = []
    for col in ("Affliation", "First Author Affiliation", "Corresponding Author Affiliation"):
        v = row.get(col, "")
        if not _blank(v):
            segments.extend(s.strip() for s in str(v).split(";") if s.strip())
    amap = _parse_aff_map(row.get("Author_Affiliation_Map", ""))
    segments.extend(v for v in amap.values() if v and not _blank(v))
    return segments


def _format_divisions_only(pairs):
    """Per instruction: the output column holds ONLY division text, not
    the institute name. Institutes with no division found contribute
    nothing to this string (rather than a blank placeholder), so the
    count of entries here does not necessarily match the count of
    institutes in "ICMR Institute (Current Name)" for the same row."""
    divisions = [division for _name, division in pairs if division]
    return "; ".join(divisions)


def _read_any(path):
    if str(path).lower().endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_excel(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="Path to the existing Excel/CSV (e.g. Included_studies_ICMR_tagged.xlsx)")
    ap.add_argument("--output", required=True, help="Path to write the augmented file")
    args = ap.parse_args()

    df = _read_any(args.input)
    print(f"Read {len(df)} rows from {args.input}")

    missing = [c for c in AFF_COLS if c not in df.columns]
    if missing:
        print(f"WARNING: missing expected column(s) {missing} - results may be less complete.")

    n_with_institute = 0
    n_with_division = 0

    def resolve_row(row):
        nonlocal n_with_institute, n_with_division
        segments = _row_segments(row)
        pairs = match_institutes_with_divisions(*segments)
        if pairs:
            n_with_institute += 1
        if any(division for _name, division in pairs):
            n_with_division += 1
        return _format_divisions_only(pairs)

    df["ICMR Division"] = df.apply(resolve_row, axis=1)

    print(f"\nRows with an identified ICMR institute/label: {n_with_institute}")
    print(f"Rows where at least one institute also got a division extracted: {n_with_division}")

    df.to_excel(args.output, index=False)
    print(f"\nWrote {len(df)} rows to {args.output}")


if __name__ == "__main__":
    main()
