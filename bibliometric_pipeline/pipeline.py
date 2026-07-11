"""
pipeline.py
===========
Checkpointed run loop. Same resumability behaviour as the original script,
plus a duplicate-Sno guard that was missing before.

Two entry points now:
  - run()          - original CLI path, reads everything from config.py
                     (env vars / .env), unchanged behaviour for existing
                     scripted use.
  - run_pipeline() - UI-agnostic core used by the Streamlit app (and any
                     future frontend/backend): takes the input DataFrame,
                     an explicit per-job checkpoint path, and an optional
                     progress_callback instead of reading fixed paths from
                     config and printing to stdout. This is the one thing
                     that MUST be per-job, not shared: two concurrent runs
                     using the same checkpoint file would corrupt each
                     other's state, which the CLI's single fixed
                     config.CHECKPOINT_FILE was never designed to avoid.
"""

import os
import sys

import pandas as pd

from . import config
from .matcher import process_record, build_row, OUTPUT_COLUMNS


def load_checkpoint(checkpoint_file=None):
    """Returns (results, done) where results is {sno: row_dict}.

    A row only counts as "done" (never touched again) if it has no
    outstanding Fetch Issues, OR its Retry Count already hit the cap - i.e.
    every source either returned data or a clean 404, or we've given up
    retrying. A row with unresolved Fetch Issues and retries left is kept
    OUT of `done`, so the next run picks it back up automatically instead
    of leaving whatever partial data (e.g. missing affiliations) it got on
    the failed attempt baked in forever."""
    checkpoint_file = checkpoint_file or config.CHECKPOINT_FILE
    if not os.path.exists(checkpoint_file):
        return {}, set()
    try:
        df = pd.read_csv(checkpoint_file, dtype={"Sno.": str})
        records = df.to_dict("records")
        results = {}
        done = set()
        n_retry = 0
        for r in records:
            sno = str(r.get("Sno."))
            results[sno] = r
            issues = str(r.get("Fetch Issues") or "").strip()
            try:
                retries_so_far = int(r.get("Retry Count") or 0)
            except (ValueError, TypeError):
                retries_so_far = 0
            if issues and retries_so_far < config.MAX_FETCH_RETRIES:
                n_retry += 1
            else:
                done.add(sno)
        print(f"Resuming: {len(done)} record(s) done in checkpoint, "
              f"{n_retry} flagged for automatic retry (earlier fetch issues).")
        return results, done
    except Exception as e:
        print(f"Could not read checkpoint ({e}); starting fresh.")
        return {}, set()


def save_results(results, path, output_columns=None):
    output_columns = output_columns or OUTPUT_COLUMNS
    rows = list(results.values()) if isinstance(results, dict) else results
    df = pd.DataFrame(rows)
    for c in output_columns:
        if c not in df.columns:
            df[c] = ""
    df = df[output_columns]
    if path.lower().endswith(".csv"):
        df.to_csv(path, index=False)
    else:
        df.to_excel(path, index=False)


def write_final(results, input_order, output_file=None, output_columns=None):
    output_file = output_file or config.OUTPUT_FILE
    output_columns = output_columns or OUTPUT_COLUMNS
    by_sno = dict(results) if isinstance(results, dict) else {str(r["Sno."]): r for r in results}
    ordered = [by_sno[s] for s in input_order if s in by_sno]
    seen = set(input_order)
    for sno, r in by_sno.items():
        if sno not in seen:
            ordered.append(r)
    df = pd.DataFrame(ordered)
    for c in output_columns:
        if c not in df.columns:
            df[c] = ""
    df = df[output_columns]
    df.to_excel(output_file, index=False)
    print(f"\nFinal file written: {output_file}  ({len(df)} rows)")
    return df


def run_pipeline(df_in, checkpoint_path, output_path=None, progress_callback=None,
                  sno_col=None, title_col=None, doi_col=None,
                  optional_column_groups=None):
    """UI-agnostic core of the extraction run loop.

    Same resumability/dedup/retry logic as run(), but:
      - takes the input DataFrame directly (caller already read the upload)
      - writes/reads checkpoints at an explicit per-job path (caller must
        pass a path unique to this job - e.g. derived from a session id -
        so concurrent jobs never share a checkpoint file)
      - reports progress via progress_callback(done, total, message) instead
        of printing to stdout, so a Streamlit (or any other) frontend can
        drive a progress bar / status line
      - returns (final_df, summary_dict) instead of writing a fixed output
        file path and exiting; if output_path is given, also writes the
        final Excel there

    This does not change run()'s behaviour at all - run() still uses fixed
    config paths and print() for the existing CLI workflow.
    """
    sno_col = sno_col or config.COL_SNO
    title_col = title_col or config.COL_TITLE
    doi_col = doi_col or config.COL_DOI

    # Per-run output projection. If the caller passed an explicit list of
    # optional column groups (e.g. a single job requesting "ICMR mode"), use
    # it INSTEAD of the process-wide env default, so one job's choice never
    # leaks into another job running in the same long-lived worker. If None,
    # fall back to the module-level OUTPUT_COLUMNS (env-driven) — unchanged
    # behaviour for the CLI and any caller that doesn't pass this.
    if optional_column_groups is None:
        output_columns = OUTPUT_COLUMNS
    else:
        from .matcher import build_output_columns
        output_columns = build_output_columns(optional_column_groups)

    def report(done, total, message):
        if progress_callback:
            try:
                progress_callback(done, total, message)
            except Exception:
                pass  # a broken UI callback should never kill the run

    for col in (sno_col, title_col, doi_col):
        if col not in df_in.columns:
            raise ValueError(f"expected column '{col}' not found. Found: {list(df_in.columns)}")

    # duplicate Sno guard - same fix as run()
    sno_series = df_in[sno_col].astype(str)
    dupes = sno_series[sno_series.duplicated(keep=False)].unique().tolist()
    dupe_warning = None
    if dupes:
        dupe_warning = (f"{len(dupes)} duplicate Sno value(s) found in input "
                         f"(keeping first occurrence of each): {dupes[:20]}"
                         f"{' ...' if len(dupes) > 20 else ''}")
        report(0, len(df_in), dupe_warning)
        df_in = df_in[~sno_series.duplicated(keep="first")]

    input_order = [str(s) for s in df_in[sno_col].tolist()]

    results, done = load_checkpoint(checkpoint_path)
    total = len(df_in)
    processed_now = 0
    status_counts = {}

    report(len(done), total, f"Resuming: {len(done)} already done in checkpoint.")

    for _, rec in df_in.iterrows():
        sno = str(rec[sno_col])
        if sno in done:
            continue

        title = rec[title_col]
        doi = rec[doi_col]

        prior = results.get(sno) or {}
        try:
            prior_retries = int(prior.get("Retry Count") or 0)
        except (ValueError, TypeError):
            prior_retries = 0

        try:
            row, matched_by, match_status, incomplete = process_record(sno, title, doi, retry_count=prior_retries)
        except Exception as e:
            row = build_row(sno, "" if pd.isna(title) else str(title),
                             "" if pd.isna(doi) else str(doi),
                             {}, {}, {}, [f"ERROR: {e}"],
                             match_status="Error", match_score=0, match_source="",
                             candidate_title="")
            match_status = "Error"
            incomplete = False

        results[sno] = row
        if incomplete:
            row["Retry Count"] = prior_retries + 1
        else:
            done.add(sno)
        status_counts[match_status] = status_counts.get(match_status, 0) + 1
        processed_now += 1

        snippet = (row.get("TITLE") or row.get("Clean Title") or "")[:60]
        report(len(done), total, f"Sno {sno} | {match_status} | {snippet}")

        if processed_now % config.CHECKPOINT_EVERY == 0:
            save_results(results, checkpoint_path, output_columns=output_columns)
            report(len(done), total, f"checkpoint saved ({len(results)} records)")

    save_results(results, checkpoint_path, output_columns=output_columns)
    final_df = (write_final(results, input_order, output_file=output_path,
                            output_columns=output_columns)
                if output_path else None)
    if final_df is None:
        by_sno = dict(results)
        ordered = [by_sno[s] for s in input_order if s in by_sno]
        final_df = pd.DataFrame(ordered)
        for c in output_columns:
            if c not in final_df.columns:
                final_df[c] = ""
        final_df = final_df[output_columns]

    n_review = status_counts.get("Needs manual review", 0)
    n_pending_retry = sum(1 for sno in results if sno not in done)
    summary = {
        "status_counts": status_counts,
        "n_review": n_review,
        "n_pending_retry": n_pending_retry,
        "dupe_warning": dupe_warning,
        "total": total,
        "done": len(done),
    }
    report(len(done), total, "Done.")
    return final_df, summary


def run():
    print("=" * 70)
    print("Bibliometric extractor  (OpenAlex + PubMed + Crossref)")
    print(f"Input : {config.INPUT_FILE}")
    print(f"Output: {config.OUTPUT_FILE}")
    print("=" * 70)

    if not os.path.exists(config.INPUT_FILE):
        sys.exit(f"ERROR: input file not found: {config.INPUT_FILE}")

    df_in = pd.read_excel(config.INPUT_FILE)
    for col in (config.COL_SNO, config.COL_TITLE, config.COL_DOI):
        if col not in df_in.columns:
            sys.exit(f"ERROR: expected column '{col}' not found. Found: {list(df_in.columns)}")

    # ---------- duplicate Sno guard (FIX: original script would silently
    # let a later duplicate overwrite an earlier record) ----------
    sno_series = df_in[config.COL_SNO].astype(str)
    dupes = sno_series[sno_series.duplicated(keep=False)].unique().tolist()
    if dupes:
        preview = dupes[:20]
        print(f"WARNING: {len(dupes)} duplicate Sno value(s) found in input: {preview}"
              f"{' ...' if len(dupes) > 20 else ''}")
        print("Keeping only the FIRST occurrence of each duplicate Sno; "
              "later rows sharing that Sno are skipped. Fix the input file "
              "if that's not what you want.")
        df_in = df_in[~sno_series.duplicated(keep="first")]

    input_order = [str(s) for s in df_in[config.COL_SNO].tolist()]

    results, done = load_checkpoint()
    total = len(df_in)
    processed_now = 0
    status_counts = {}

    for _, rec in df_in.iterrows():
        sno = str(rec[config.COL_SNO])
        if sno in done:
            continue

        title = rec[config.COL_TITLE]
        doi = rec[config.COL_DOI]

        prior = results.get(sno) or {}
        try:
            prior_retries = int(prior.get("Retry Count") or 0)
        except (ValueError, TypeError):
            prior_retries = 0

        try:
            row, matched_by, match_status, incomplete = process_record(sno, title, doi, retry_count=prior_retries)
        except Exception as e:  # never let one record kill the run
            sys.stderr.write(f"[row {sno}] unexpected error: {e}\n")
            row = build_row(sno, "" if pd.isna(title) else str(title),
                             "" if pd.isna(doi) else str(doi),
                             {}, {}, {}, [f"ERROR: {e}"],
                             match_status="Error", match_score=0, match_source="",
                             candidate_title="")
            match_status = "Error"
            incomplete = False

        results[sno] = row
        if incomplete:
            row["Retry Count"] = prior_retries + 1
        else:
            done.add(sno)
        status_counts[match_status] = status_counts.get(match_status, 0) + 1
        processed_now += 1

        tag = " [retry pending]" if incomplete else ""
        snippet = (row.get("TITLE") or row.get("Clean Title") or "")[:60]
        print(f"[{len(done)}/{total}] Sno {sno:>6} | {match_status:<24}{tag} | {snippet}")

        if processed_now % config.CHECKPOINT_EVERY == 0:
            save_results(results, config.CHECKPOINT_FILE)
            print(f"   --- checkpoint saved ({len(results)} records) ---")

    save_results(results, config.CHECKPOINT_FILE)
    write_final(results, input_order)

    print("\nSummary")
    for status, n in sorted(status_counts.items(), key=lambda x: -x[1]):
        print(f"  {status:<28}: {n}")
    n_review = status_counts.get("Needs manual review", 0)
    if n_review:
        print(f"\n{n_review} record(s) need manual review - see the 'Match Status' "
              f"column in {config.OUTPUT_FILE}")
    n_pending_retry = sum(1 for sno in results if sno not in done)
    if n_pending_retry:
        print(f"{n_pending_retry} record(s) had a transient fetch failure (timeout/rate-limit) - "
              f"see the 'Fetch Issues' column. Just run the script again to retry them "
              f"(up to {config.MAX_FETCH_RETRIES} times total) without re-fetching anything "
              f"that already succeeded.")
    print("Done.")
