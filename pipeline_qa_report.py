"""
pipeline_qa_report.py
======================
Standalone, read-only QA report over a finished (or in-progress) pipeline
output/checkpoint file. Never modifies the input - writes a fresh multi-
sheet .xlsx report next to it. Same "separate script, don't touch the
pipeline" pattern as scopus_gap_filler.py and export_scopus_csv.py.

Produces five sheets:

  1. Summary            - PRISMA-STYLE matching/retrieval flow (identified ->
                           matched via DOI -> matched via Title -> needs
                           manual review -> no match -> pending retry), plus
                           top-line coverage stats. NOTE: this documents the
                           pipeline's DOI/title-matching funnel, which is a
                           legitimate thing to report in a bibliometric
                           methods section - it is NOT a substitute for a
                           full systematic-review PRISMA diagram, which
                           requires eligibility screening against research
                           criteria that this pipeline does not perform.
  2. Duplicate DOIs      - groups of rows that resolved to the same DOI
                           (same paper submitted more than once under a
                           different Sno). These will double-count a paper
                           in Biblioshiny/VOSviewer network stats (co-
                           authorship, citations, keyword co-occurrence)
                           unless deduplicated before import.
  3. Duplicate EIDs      - sanity check only; should always be empty since
                           EIDs are a deterministic hash of DOI/PMID/Sno+title.
                           A non-empty result here would indicate a real bug,
                           not a data issue.
  4. Reconciliation Flags - every row with a non-empty Reconciliation Notes
                           value (cross-source Title/Year/Journal/Citation
                           disagreements), for manual spot-checking. If the
                           column doesn't exist yet (rows processed before
                           this feature was added), this sheet says so
                           instead of silently being empty.
  5. Threshold Sensitivity - score-bucket breakdown of Title-matched rows,
                           to inform the FUZZY_AUTO_ACCEPT decision (currently
                           85%) with real data: how many rows would flip from
                           "Needs manual review" to "Auto-accepted" at each
                           candidate threshold (80/82/85%).

Usage:
  python3 pipeline_qa_report.py --input /path/to/output_or_checkpoint.csv-or-xlsx \
                                 --output /path/to/qa_report.xlsx
"""

import argparse
import sys

import pandas as pd

# Re-uses the pipeline's own (fixed) fuzzy-scoring logic so this check stays
# in sync with matcher.py automatically. Run this script from the project
# root (same directory as the bibliometric_pipeline package).
sys.path.insert(0, ".")
try:
    from bibliometric_pipeline.text_utils import clean_for_match, fuzzy_score
except ImportError:
    clean_for_match = fuzzy_score = None


def _read_any(path):
    if str(path).lower().endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_excel(path)


def _blank_mask(series):
    return series.isna() | (series.astype(str).str.strip() == "") | (series.astype(str).str.strip().str.lower() == "nan")


def build_summary(df):
    total = len(df)
    status_counts = df["Match Status"].value_counts(dropna=False) if "Match Status" in df.columns else pd.Series(dtype=int)

    def count_status(*prefixes):
        # Prefix match, not exact - gap_fill_by_doi.py adds its own status
        # variants that extend these same base strings (e.g. "Auto-accepted
        # (DOI) [gap-filled retroactively]", "No match (gap-fill: DOI not
        # found in any source)") rather than introducing wholly new labels.
        return int(sum(n for status, n in status_counts.items()
                        if any(str(status).startswith(p) for p in prefixes)))

    identified = total
    auto_doi = count_status("Auto-accepted (DOI)")
    auto_title = count_status("Auto-accepted (Title)")
    manual_review = count_status("Needs manual review")
    no_match = count_status("No match")
    pending = count_status("Pending retry (DOI fetch error)", "Pending retry (title fetch error)")
    other = identified - (auto_doi + auto_title + manual_review + no_match + pending)

    rows = [
        ("Records identified (input rows)", identified, ""),
        ("  -> Auto-accepted via DOI match", auto_doi, "Direct DOI lookup succeeded in >=1 source"),
        ("  -> Auto-accepted via Title match", auto_title, f"Fuzzy title score >= auto-accept threshold"),
        ("  -> Needs manual review", manual_review, "Fuzzy title score between review-floor and auto-accept threshold"),
        ("  -> No match found", no_match, "Below review floor in all sources, or no candidates at all"),
        ("  -> Pending retry (transient fetch error)", pending, "Network/rate-limit issue - re-run pipeline to resolve"),
    ]
    if other:
        rows.append(("  -> Other/unrecognized status", other, "Check Match Status values manually"))

    summary_df = pd.DataFrame(rows, columns=["Stage", "Count", "Notes"])

    coverage_rows = []
    for col, label in [("DOI", "DOI present"), ("EID", "EID present (required for Biblioshiny import)"),
                        ("Affliation", "Affiliation present"), ("Authors", "Authors present"),
                        ("Journal", "Journal present"), ("References", "References present")]:
        if col in df.columns:
            present = (~_blank_mask(df[col])).sum()
            coverage_rows.append((label, present, total, f"{present/total*100:.1f}%" if total else "n/a"))
    coverage_df = pd.DataFrame(coverage_rows, columns=["Field", "Present", "Total", "Coverage %"])

    return summary_df, coverage_df


def build_duplicate_dois(df):
    if "DOI" not in df.columns:
        return pd.DataFrame([{"Note": "No DOI column in this file"}])
    dois = df["DOI"].astype(str).str.strip()
    valid = dois[(dois != "") & (dois.str.lower() != "nan")]
    dup_vals = valid[valid.duplicated(keep=False)]
    if dup_vals.empty:
        return pd.DataFrame([{"Note": "No duplicate DOIs found"}])
    cols = [c for c in ["Sno.", "DOI", "Clean Title", "TITLE", "Match Score", "Match Status"] if c in df.columns]
    dup_rows = df[df["DOI"].astype(str).str.strip().isin(dup_vals.unique())][cols].sort_values("DOI")
    return dup_rows


def build_duplicate_eids(df):
    if "EID" not in df.columns:
        return pd.DataFrame([{"Note": "No EID column in this file"}])
    eids = df["EID"].astype(str).str.strip()
    valid = eids[(eids != "") & (eids.str.lower() != "nan")]
    dup_vals = valid[valid.duplicated(keep=False)]
    if dup_vals.empty:
        return pd.DataFrame([{"Note": "No duplicate EIDs found (expected - this is a sanity check)"}])
    cols = [c for c in ["Sno.", "EID", "DOI", "Clean Title", "TITLE"] if c in df.columns]
    dup_rows = df[df["EID"].astype(str).str.strip().isin(dup_vals.unique())][cols].sort_values("EID")
    return dup_rows


def build_reconciliation_flags(df):
    if "Reconciliation Notes" not in df.columns:
        return pd.DataFrame([{"Note": "This file has no 'Reconciliation Notes' column - it was produced before "
                                       "that feature was added to the pipeline. Rows processed BEFORE the feature "
                                       "was added will never retroactively get this column on checkpoint resume; "
                                       "only rows processed after the change will have it."}])
    flagged = df[~_blank_mask(df["Reconciliation Notes"])]
    if flagged.empty:
        return pd.DataFrame([{"Note": "No reconciliation conflicts flagged in any row"}])
    cols = [c for c in ["Sno.", "Clean Title", "TITLE", "DOI", "Match Score", "Reconciliation Notes"] if c in df.columns]
    return flagged[cols]


def build_length_guard_recheck(df):
    """Retroactively re-scores every row's Clean Title vs TITLE using the
    CURRENT (fixed) fuzzy_score(), which guards against a confirmed
    false-positive failure mode: a short, generic candidate title (e.g. a
    2-word drug-bulletin blurb like 'Withania-somnifera') can score a
    perfect 100% against a much longer, completely unrelated real title
    that merely happens to share that vocabulary - because the old scoring
    treated a full token-subset match as equivalent to a real match,
    regardless of length. That row was Auto-accepted at the HIGHEST
    confidence tier with no manual-review flag - this check is the only
    way to retroactively find others like it in rows already processed
    under the old (unguarded) scoring, without re-fetching anything from
    any API - it only re-compares text already stored in this file.

    A row is flagged if the ORIGINAL recorded Match Score was high (>=
    review floor) but the RECOMPUTED guarded score drops meaningfully
    below that - i.e. exactly the pattern that let a bad match slip
    through undetected the first time.
    """
    if clean_for_match is None or fuzzy_score is None:
        return pd.DataFrame([{"Note": "Could not import bibliometric_pipeline.text_utils - "
                                       "run this script from the project root directory."}])
    if "Clean Title" not in df.columns or "TITLE" not in df.columns or "Match Score" not in df.columns:
        return pd.DataFrame([{"Note": "Missing Clean Title/TITLE/Match Score columns"}])

    flagged = []
    for _, row in df.iterrows():
        clean_title = str(row.get("Clean Title", "") or "")
        title = str(row.get("TITLE", "") or "")
        try:
            orig_score = float(row.get("Match Score", 0) or 0)
        except (TypeError, ValueError):
            continue
        if not clean_title or not title or orig_score < 75:
            continue
        recomputed = fuzzy_score(clean_for_match(clean_title), clean_for_match(title))
        if recomputed < 75 and orig_score >= 75:
            flagged.append({
                "Sno.": row.get("Sno.", ""),
                "Clean Title (input)": clean_title[:150],
                "TITLE (matched)": title[:150],
                "DOI": row.get("DOI", ""),
                "Journal": row.get("Journal", ""),
                "Original Match Score": orig_score,
                "Recomputed (guarded) Score": round(recomputed, 1),
                "Match Status": row.get("Match Status", ""),
            })
    if not flagged:
        return pd.DataFrame([{"Note": "No rows found where the fixed length-guard scoring would have "
                                       "rejected a previously-accepted match - none detected in this file"}])
    return pd.DataFrame(flagged).sort_values("Recomputed (guarded) Score")


def build_threshold_sensitivity(df, current_auto_accept=85, current_review_min=75):
    if "Match Score" not in df.columns or "Match Source" not in df.columns:
        return pd.DataFrame([{"Note": "Missing Match Score/Match Source columns"}])
    title_rows = df[df["Match Source"] == "TITLE"].copy() if "Match Source" in df.columns else pd.DataFrame()
    if title_rows.empty:
        # fall back: any row whose Match Status mentions Title
        title_rows = df[df.get("Match Status", pd.Series(dtype=str)).astype(str).str.contains("Title", na=False)]
    if title_rows.empty:
        return pd.DataFrame([{"Note": "No title-matched rows found to analyze"}])

    scores = pd.to_numeric(title_rows["Match Score"], errors="coerce").dropna()
    buckets = [(100, 100, "100% (exact)"), (95, 99.9, "95-99.9%"), (90, 94.9, "90-94.9%"),
               (85, 89.9, "85-89.9% (current auto-accept cutoff)"),
               (80, 84.9, "80-84.9%"), (75, 79.9, "75-79.9% (current review floor)"),
               (0, 74.9, "<75% (below review floor - should not appear as a real match)")]
    rows = []
    for lo, hi, label in buckets:
        n = int(((scores >= lo) & (scores <= hi)).sum())
        rows.append((label, n))
    bucket_df = pd.DataFrame(rows, columns=["Score range", "Count"])

    would_flip_80 = int(((scores >= 80) & (scores < current_auto_accept)).sum())
    would_flip_82 = int(((scores >= 82) & (scores < current_auto_accept)).sum())
    note_rows = pd.DataFrame([
        ("Current settings", f"auto-accept >= {current_auto_accept}%, review floor >= {current_review_min}%", ""),
        ("If auto-accept lowered to 80%", f"{would_flip_80} row(s) would flip from 'Needs manual review' to 'Auto-accepted'", ""),
        ("If auto-accept lowered to 82%", f"{would_flip_82} row(s) would flip from 'Needs manual review' to 'Auto-accepted'", ""),
    ], columns=["Item", "Value", ""])

    return pd.concat([bucket_df, pd.DataFrame([["", ""]], columns=["Score range", "Count"]), note_rows.rename(
        columns={"Item": "Score range", "Value": "Count"})], ignore_index=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="Path to the pipeline output/checkpoint file (.xlsx or .csv)")
    ap.add_argument("--output", required=True, help="Path to write the QA report .xlsx")
    args = ap.parse_args()

    df = _read_any(args.input)
    print(f"Read {len(df)} rows from {args.input}")

    summary_df, coverage_df = build_summary(df)
    dup_dois = build_duplicate_dois(df)
    dup_eids = build_duplicate_eids(df)
    recon_flags = build_reconciliation_flags(df)
    threshold = build_threshold_sensitivity(df)
    length_guard = build_length_guard_recheck(df)

    with pd.ExcelWriter(args.output, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False, startrow=0)
        coverage_df.to_excel(writer, sheet_name="Summary", index=False, startrow=len(summary_df) + 3)
        dup_dois.to_excel(writer, sheet_name="Duplicate DOIs", index=False)
        dup_eids.to_excel(writer, sheet_name="Duplicate EIDs", index=False)
        recon_flags.to_excel(writer, sheet_name="Reconciliation Flags", index=False)
        threshold.to_excel(writer, sheet_name="Threshold Sensitivity", index=False)
        length_guard.to_excel(writer, sheet_name="Suspect Short-Candidate Matches", index=False)

    print(f"Wrote QA report to {args.output}")
    print("\n--- Quick summary ---")
    print(summary_df.to_string(index=False))
    n_dup_dois = 0 if "Note" in dup_dois.columns else dup_dois["DOI"].nunique()
    n_dup_eids = 0 if "Note" in dup_eids.columns else dup_eids["EID"].nunique()
    n_recon = 0 if "Note" in recon_flags.columns else len(recon_flags)
    n_length_guard = 0 if "Note" in length_guard.columns else len(length_guard)
    print(f"\nDuplicate DOI groups: {n_dup_dois}")
    print(f"Duplicate EID groups: {n_dup_eids} (should always be 0)")
    print(f"Rows with reconciliation conflicts flagged: {n_recon}")
    print(f"Rows flagged by retroactive length-guard recheck (likely wrong matches): {n_length_guard}")
    if n_length_guard:
        print("  ^ WARNING: these rows were auto-accepted under the old (unguarded) scoring - manually verify them.")


if __name__ == "__main__":
    main()
