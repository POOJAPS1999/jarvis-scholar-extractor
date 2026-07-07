"""
gap_fill_by_doi.py
====================
Standalone, additive script for backfilling your merged/deduplicated
combined sheet (your original extraction + the "AR" sheet + the "EX"
sheet). Reuses the main pipeline's own fetch/merge logic (matcher.py) so
it automatically benefits from every correctness fix made this session
(DOI-mismatch guard, length-guard fuzzy scoring, dash normalization,
Reconciliation Notes, the new Corresponding Author Affiliation column,
etc.) - but it does NOT re-run fuzzy title matching. It assumes every row
already has a DOI (per your confirmation) and does a straight, fast
DOI-based re-fetch from OpenAlex/PubMed/Crossref for rows that need it.

STRICT "ONLY FILL EMPTY CELLS" BEHAVIOR:
For each row, this script checks the target columns (every column in the
current pipeline schema except pure identity/input fields - see
TARGET_COLUMNS below). If ALL of them are already filled, the row is
skipped entirely - no fetch, no API calls, no changes. If ANY are blank,
the row is re-fetched fresh from all 3 sources by its existing DOI, and
ONLY the blank cells are filled in from that fresh data. Every already-
filled cell - even if the fresh fetch would compute something different -
is left completely untouched. This matches exactly what you asked for:
"we will pull only for the data where the cells are empty."

COLUMNS NEVER TOUCHED (identity/input, must already exist in your sheet):
  Sno., Clean Title, DOI

COLUMNS ALWAYS RECOMPUTED IF BLANK (including synthetic IDs, which are
cheap deterministic hashes of DOI/PMID and safe to generate any time):
  everything else in the current schema - see TARGET_COLUMNS.

CHECKPOINTING: this can be a long run over potentially 1000+ merged rows,
same rate limits as the main pipeline apply. Saves progress every 25 rows
so it can be safely interrupted and resumed (skips rows already confirmed
complete in the checkpoint).

REQUIRES a live internet connection (OpenAlex/PubMed/Crossref) - run this
on your machine, not in an offline/sandboxed environment.

Usage:
  python3 gap_fill_by_doi.py --input merged_deduped.xlsx \
                              --output merged_deduped_gapfilled.xlsx \
                              --checkpoint gapfill_checkpoint.csv
"""

import argparse
import sys

import pandas as pd

sys.path.insert(0, ".")
from bibliometric_pipeline import matcher, config  # noqa: E402
from bibliometric_pipeline.sources import openalex, crossref  # noqa: E402
from bibliometric_pipeline.http_utils import FetchError  # noqa: E402
from bibliometric_pipeline.text_utils import normalize_doi  # noqa: E402

# Never touched - must already be present in your merged sheet.
IDENTITY_COLUMNS = {"Sno.", "Clean Title", "DOI"}

# Everything else in the current schema is a fill-if-empty target.
TARGET_COLUMNS = [c for c in matcher.OUTPUT_COLUMNS if c not in IDENTITY_COLUMNS]


def _blank(v):
    return v is None or (isinstance(v, float) and pd.isna(v)) or str(v).strip() == "" or str(v).strip().lower() == "nan"


def _read_any(path):
    if str(path).lower().endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_excel(path)


# Excel's hard limit is 32,767 characters per cell - openpyxl/xlsxwriter
# silently truncate mid-string (even mid-word) past that with only a
# console UserWarning, easy to miss in a long run's output. Confirmed real
# data loss from this: References, Author_Affiliation_Map, Authors,
# Affliation, and COI all hit this on a few rows in a 3,815-row run. This
# margin (500 chars under the hard limit) leaves room for the truncation
# marker itself.
MAX_SAFE_CELL_LEN = 32000


def _make_safe_for_excel(df, sno_col="Sno."):
    """Scans every cell (not just ones this run just filled - pre-existing
    long values from earlier extractions are just as much at risk) and
    replaces anything over MAX_SAFE_CELL_LEN with a truncated value plus a
    clear marker, instead of letting Excel silently cut it mid-word with no
    trace beyond a console warning. Returns (df, overflow_rows) where
    overflow_rows is a list of dicts with the FULL untruncated text, meant
    to be written to a companion file so nothing is actually lost - it just
    can't live inside a single Excel cell."""
    overflow_rows = []
    truncated_fields_col = []
    for i, row in df.iterrows():
        truncated_here = []
        for col in df.columns:
            if col in (sno_col, "Truncated Fields"):
                continue
            val = row[col]
            if isinstance(val, str) and len(val) > MAX_SAFE_CELL_LEN:
                overflow_rows.append({"Sno.": row.get(sno_col, i), "Column": col, "Full Text": val})
                marker = f" ...[TRUNCATED - {len(val)} chars total, full text in overflow file]"
                df.at[i, col] = val[:MAX_SAFE_CELL_LEN - len(marker)] + marker
                truncated_here.append(col)
        truncated_fields_col.append("; ".join(truncated_here))
    df["Truncated Fields"] = truncated_fields_col
    return df, overflow_rows


def row_needs_fill(row):
    return any(c in row.index and _blank(row.get(c)) for c in TARGET_COLUMNS)


def fetch_and_build_fresh_row(sno, clean_title, doi):
    """Re-fetch by DOI and build a fresh, fully-populated row using the
    CURRENT pipeline schema/logic - mirrors matcher.process_record()'s DOI
    path, but simpler since there's no title-matching fallback needed."""
    oa_raw, pm_raw, cr_raw, fetch_errors = matcher._fetch_doi_all(doi)

    oa_parsed, pm_parsed, cr_parsed = {}, {}, {}
    notes = []

    if oa_raw:
        oa_parsed = openalex.parse_openalex(oa_raw)
        if matcher._doi_mismatch(doi, oa_parsed):
            notes.append(f"DISCARDED OpenAlex DOI result: mismatch")
            oa_parsed = {}
    if pm_raw:
        pm_parsed = pm_raw
        if matcher._doi_mismatch(doi, pm_parsed):
            notes.append(f"DISCARDED PubMed DOI result: mismatch")
            pm_parsed = {}
    if cr_raw:
        cr_parsed = crossref.parse_crossref(cr_raw)
        if matcher._doi_mismatch(doi, cr_parsed):
            notes.append(f"DISCARDED Crossref DOI result: mismatch")
            cr_parsed = {}

    found_anything = bool(oa_parsed or pm_parsed or cr_parsed)
    match_status = "Auto-accepted (DOI) [gap-filled retroactively]" if found_anything else "No match (gap-fill: DOI not found in any source)"

    fresh_row = matcher.build_row(
        sno, clean_title, doi, oa_parsed, pm_parsed, cr_parsed, notes,
        match_status=match_status, match_score=100.0 if found_anything else 0.0,
        match_source="DOI", fetch_errors=fetch_errors, retry_count=0,
    )
    return fresh_row, fetch_errors


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, help="Path to your merged/deduplicated sheet (.xlsx or .csv)")
    ap.add_argument("--output", required=True, help="Path to write the gap-filled .xlsx")
    ap.add_argument("--checkpoint", required=True, help="Path to a checkpoint .csv for safe resume")
    args = ap.parse_args()

    df = _read_any(args.input)
    print(f"Read {len(df)} rows from {args.input}")
    if "DOI" not in df.columns or "Sno." not in df.columns:
        print("ERROR: input must have 'Sno.' and 'DOI' columns.")
        sys.exit(1)

    # IMPORTANT: "done" tracking is keyed by ROW INDEX (position in the
    # file), NOT by Sno. - real merged sheets can and do contain duplicate
    # Sno. values (confirmed: 17 in one real merge), and a Sno.-keyed
    # checkpoint would silently skip every row after the first one sharing
    # that Sno., leaving it never gap-filled with no error or warning. Row
    # position is stable across runs as long as you don't reorder/re-sort
    # the input file between runs of this script.
    # Force every target column to object dtype BEFORE any assignment.
    # Root cause of a real crash: a column that is entirely blank when an
    # .xlsx file is read comes back as an all-NaN float64 column (Excel has
    # no distinct "empty string" type - openpyxl/pandas collapse blank
    # cells to NaN on read, and pandas then infers float64 for an all-NaN
    # column). Writing a normal text value into a float64-dtyped cell via
    # .at[] then raises "Invalid value ... for dtype" instead of silently
    # upcasting. Concretely hit this on 'Corresponding Author Affiliation'
    # (added as a brand-new blank column, then round-tripped through Excel)
    # the first time a real affiliation string was written into it.
    for col in TARGET_COLUMNS:
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].astype(object)

    done_indices = set()
    try:
        chk = pd.read_csv(args.checkpoint)
        if "_row_index" in chk.columns:
            done_indices = set(chk["_row_index"].astype(int))
            print(f"Resuming: {len(done_indices)} row(s) already confirmed complete in checkpoint")
            chk_indexed = chk.set_index(chk["_row_index"].astype(int))
            for idx in done_indices:
                if idx in df.index and idx in chk_indexed.index:
                    for col in TARGET_COLUMNS:
                        if col in chk_indexed.columns and _blank(df.at[idx, col]) and not _blank(chk_indexed.at[idx, col]):
                            df.at[idx, col] = chk_indexed.at[idx, col]
    except FileNotFoundError:
        pass

    n_skipped_complete = 0
    n_skipped_no_doi = 0
    n_filled = 0
    n_fetch_error = 0
    cells_filled_total = 0

    for i, row in df.iterrows():
        sno = str(row.get("Sno.", ""))
        if i in done_indices:
            continue
        if not row_needs_fill(row):
            n_skipped_complete += 1
            done_indices.add(i)
            continue

        doi = normalize_doi(row.get("DOI", ""))
        if not doi:
            n_skipped_no_doi += 1
            print(f"  [{i+1}/{len(df)}] Sno {sno}: SKIPPED - no DOI, cannot gap-fill")
            continue

        clean_title = row.get("Clean Title", "")
        print(f"  [{i+1}/{len(df)}] Sno {sno}: fetching by DOI {doi} ...")
        try:
            fresh_row, fetch_errors = fetch_and_build_fresh_row(sno, clean_title, doi)
        except Exception as e:
            print(f"    ERROR building fresh row: {e}")
            n_fetch_error += 1
            continue

        if fetch_errors:
            print(f"    fetch issue(s): {fetch_errors} - will retry on next run")
            n_fetch_error += 1
            continue  # don't mark done - leave for retry on next run

        filled_this_row = 0
        for col in TARGET_COLUMNS:
            if _blank(df.at[i, col]) and col in fresh_row and not _blank(fresh_row[col]):
                df.at[i, col] = fresh_row[col]
                filled_this_row += 1
        cells_filled_total += filled_this_row
        n_filled += 1
        done_indices.add(i)
        print(f"    filled {filled_this_row} empty cell(s)")

        if (i + 1) % 25 == 0:
            snap = df.loc[sorted(done_indices)].copy()
            snap.insert(0, "_row_index", sorted(done_indices))
            snap.to_csv(args.checkpoint, index=False)
            print(f"  [checkpoint saved: {len(done_indices)} rows done]")

    snap = df.loc[sorted(done_indices)].copy()
    snap.insert(0, "_row_index", sorted(done_indices))
    snap.to_csv(args.checkpoint, index=False)

    df, overflow_rows = _make_safe_for_excel(df)
    df.to_excel(args.output, index=False)

    if overflow_rows:
        overflow_path = args.output.rsplit(".", 1)[0] + "_overflow.csv"
        pd.DataFrame(overflow_rows).to_csv(overflow_path, index=False)
        print(f"\nWARNING: {len(overflow_rows)} cell(s) across {len(set(r['Sno.'] for r in overflow_rows))} row(s) "
              f"exceeded Excel's 32,767-char cell limit and were truncated (with a marker) in {args.output}.")
        print(f"Full untruncated text for every one of them was saved to {overflow_path} - "
              f"see the 'Truncated Fields' column in the main output to find which rows/columns are affected.")

    print(f"\nWrote {len(df)} rows to {args.output}")
    print(f"Rows already fully complete (skipped, no fetch needed): {n_skipped_complete}")
    print(f"Rows skipped (no DOI to gap-fill from): {n_skipped_no_doi}")
    print(f"Rows gap-filled this run: {n_filled} (total {cells_filled_total} empty cells filled)")
    print(f"Rows with a fetch error (will retry - just run this script again): {n_fetch_error}")


if __name__ == "__main__":
    main()
