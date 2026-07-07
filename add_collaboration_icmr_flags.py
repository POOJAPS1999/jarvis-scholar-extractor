"""
add_collaboration_icmr_flags.py
=================================
Standalone, additive script (per your instruction: NOT wired into the main
pipeline/matcher.py for now - this only ever reads an existing finished
Excel/CSV and writes a new file with 4 extra columns added; nothing else in
the file is touched).

Adds:
  - Collaboration Type (National/International)
        Derived from the existing "Country Count" column (same rule the
        main pipeline itself uses in matcher.py, so this agrees with any
        future live pipeline run): "International" if Country Count >= 2,
        "National" if Country Count == 1, blank if Country Count is
        missing/unusable for that row.
  - First Author from ICMR              (Yes / No / blank)
  - Corresponding Author from ICMR      (Yes / No / blank)
  - Any Author from ICMR                (Yes / No / blank)
        "Yes"/"No" are based on whether the relevant affiliation text
        mentions ICMR (same is_icmr() check the main pipeline uses:
        "icmr" or "indian council of medical research", case-insensitive).
        Blank ONLY when there's no affiliation text at all to check for
        that row/column (so blank never means "confirmed not ICMR" - it
        means "couldn't tell").

        Every one of these ALSO checks the "Author_Affiliation_Map" JSON
        column (that author's own name looked up in the per-author map),
        not just the flat "First/Corresponding Author Affiliation" column
        text. This matters: confirmed on real data that the flat "First
        Author Affiliation" column can hold a coarser, institution-only
        value for some legacy rows (e.g. "National Institute of
        Epidemiology") even when that SAME author's entry in
        Author_Affiliation_Map has the fuller text that actually says
        "ICMR" (e.g. "ICMR - National Institute for Research in
        Environmental Health (NIREH)...") - 16/2632 rows where relying on
        the flat column alone would have wrongly said "No". "Any Author
        from ICMR" additionally checks every OTHER author's map entry too,
        so a co-author who is neither first nor corresponding author still
        gets checked.

Usage:
  python3 add_collaboration_icmr_flags.py \
      --input Included_studies.xlsx \
      --output Included_studies_with_flags.xlsx
"""

import argparse
import json
import sys

import pandas as pd

sys.path.insert(0, ".")
try:
    from bibliometric_pipeline.text_utils import is_icmr
except ImportError:
    print("WARNING: could not import bibliometric_pipeline - run this script from the "
          "bibliometric_pipeline_project folder. Using a local fallback is_icmr() instead.")

    def is_icmr(text):
        if not text:
            return False
        t = str(text).lower()
        return ("icmr" in t) or ("indian council of medical research" in t)


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


def _split_names(joined):
    """Handles both this project's own '; '-joined convention and legacy
    ','-joined author lists (same delimiter-detection approach used
    elsewhere in this project, e.g. export_scopus_csv.py)."""
    if _blank(joined):
        return []
    s = str(joined)
    if ";" in s:
        return [n.strip() for n in s.split(";") if n.strip()]
    if "," in s:
        return [n.strip() for n in s.split(",") if n.strip()]
    return [s.strip()] if s.strip() else []


def _collab_type(country_count):
    """Mirrors matcher.py's own collab_type rule exactly, so a value
    computed here agrees with what a live pipeline run would produce."""
    if _blank(country_count):
        return ""
    try:
        n = int(float(country_count))
    except (TypeError, ValueError):
        return ""  # e.g. a stray non-numeric value in that cell
    if n >= 2:
        return "International"
    if n == 1:
        return "National"
    return ""


def _icmr_flag_from_texts(texts):
    """Yes/No, or blank ONLY when there's no affiliation text at all to
    check (never means 'confirmed not ICMR')."""
    non_blank = [t for t in texts if not _blank(t)]
    if not non_blank:
        return ""
    return "Yes" if any(is_icmr(t) for t in non_blank) else "No"


def _named_role_icmr_flag(col_text, names, amap):
    """Yes/No/blank for a specific author role (first author, corresponding
    author). Checks BOTH the flat column text AND (for each candidate name
    in that role) the SAME author's own entry in Author_Affiliation_Map -
    confirmed on real data that the flat column can hold a coarser,
    institution-only value for some legacy rows even when that author's
    fuller per-author map text actually says "ICMR"."""
    texts = [col_text] + [amap[n] for n in names if n in amap]
    return _icmr_flag_from_texts(texts)


def _any_icmr_flag(row, amap):
    texts = [row.get(c, "") for c in AFF_COLS] + list(amap.values())
    return _icmr_flag_from_texts(texts)


def _compute_icmr_flags(row):
    amap = _parse_aff_map(row.get("Author_Affiliation_Map", ""))
    first_names = _split_names(row.get("First Author", ""))
    corr_names = _split_names(row.get("Corresponding Author", ""))
    return pd.Series({
        "First Author from ICMR": _named_role_icmr_flag(
            row.get("First Author Affiliation", ""), first_names, amap),
        "Corresponding Author from ICMR": _named_role_icmr_flag(
            row.get("Corresponding Author Affiliation", ""), corr_names, amap),
        "Any Author from ICMR": _any_icmr_flag(row, amap),
    })


def _read_any(path):
    if str(path).lower().endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_excel(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="Path to the existing Excel/CSV (e.g. Included_studies.xlsx)")
    ap.add_argument("--output", required=True, help="Path to write the augmented file")
    args = ap.parse_args()

    df = _read_any(args.input)
    print(f"Read {len(df)} rows from {args.input}")

    missing = [c for c in AFF_COLS + ["Country Count"] if c not in df.columns]
    if missing:
        print(f"WARNING: missing expected column(s) {missing} - related flags may come out blank/less accurate.")

    df["Collaboration Type (National/International)"] = (
        df["Country Count"].apply(_collab_type) if "Country Count" in df.columns
        else pd.Series([""] * len(df), index=df.index)
    )

    icmr_flags = df.apply(_compute_icmr_flags, axis=1)
    df["First Author from ICMR"] = icmr_flags["First Author from ICMR"]
    df["Corresponding Author from ICMR"] = icmr_flags["Corresponding Author from ICMR"]
    df["Any Author from ICMR"] = icmr_flags["Any Author from ICMR"]

    df.to_excel(args.output, index=False)
    print(f"\nWrote {len(df)} rows to {args.output}")

    print("\n--- Summary ---")
    for col in ["Collaboration Type (National/International)", "First Author from ICMR",
                "Corresponding Author from ICMR", "Any Author from ICMR"]:
        print(f"\n{col}:")
        print(df[col].fillna("(blank)").replace("", "(blank)").value_counts().to_string())


if __name__ == "__main__":
    main()
