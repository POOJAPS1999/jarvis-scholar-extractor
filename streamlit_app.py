"""
streamlit_app.py
=================
Jarvis Scholar - Phase 0 (Streamlit wrapper).

Thin UI over the existing extraction pipeline. Does NOT reimplement any
matching/fetching logic - it calls bibliometric_pipeline.pipeline.run_pipeline()
(the UI-agnostic core added for this purpose) and export_scopus_csv.convert_row()
for the download step. The CLI path (run_extractor.py -> pipeline.run()) is
untouched and keeps working exactly as before.

USAGE (local):
    pip3 install -r requirements.txt streamlit
    streamlit run streamlit_app.py

DEPLOY (free), on share.streamlit.io / Streamlit Community Cloud:
  1. Push this repo (bibliometric_pipeline_project/) to GitHub.
  2. New app -> pick the repo/branch -> main file path: streamlit_app.py
     (requirements.txt at this same folder's root is picked up automatically).
  3. App -> Settings -> Secrets, add (TOML format):
         BIBLIO_CONTACT_EMAIL = "you@example.com"
         NCBI_API_KEY = "..."        # optional, raises OpenAlex/PubMed rate limits
         OPENALEX_API_KEY = "..."    # optional, raises OpenAlex daily budget 10x
     These land in st.secrets, which this file bridges into os.environ
     before config.py is imported (config.py itself only reads env vars).
  4. Deploy. Community Cloud's disk is EPHEMERAL - the jobs/ checkpoint
     folder survives across page reloads and tab closes within the same
     running app instance (that's what makes "come back later" work), but
     is wiped on a redeploy or an app reboot after inactivity. For runs
     that must survive that, use the local CLI (run_extractor.py) instead,
     or wait for Phase 1's real (Postgres-backed) job storage.

DESIGN NOTES (per the Phase-0 plan):
  - Every job gets its OWN checkpoint file (named from an md5 of the
    uploaded file's bytes + row count), stored in ./jobs/. This is what
    lets someone close the tab and come back later to the same job - the
    checkpoint on disk is what "come back later" actually means here - and
    it's what keeps two different uploads from corrupting each other's
    progress (the single shared config.CHECKPOINT_FILE the CLI script
    uses would not be safe for this).
  - Streamlit reruns the whole script top-to-bottom on every interaction,
    and the free tier has a memory/time ceiling, so this caps public runs
    at MAX_FREE_ROWS titles - large jobs should run via the CLI script
    instead, at least until Phase 1's proper job queue exists.
  - Progress is reported via a callback into st.progress + st.empty(),
    instead of pipeline.py's normal print() statements.
"""
import hashlib
import os
import time
from pathlib import Path

import pandas as pd
import streamlit as st

# Streamlit Community Cloud's "Secrets" panel populates st.secrets, NOT
# os.environ - but config.py reads os.environ (so it works unchanged for
# the existing .env-based CLI flow too). Bridge the two here, before
# config.py is imported, so BIBLIO_CONTACT_EMAIL / NCBI_API_KEY /
# OPENALEX_API_KEY set as app secrets actually take effect. Wrapped in
# try/except because st.secrets raises if no secrets.toml exists at all
# (the normal case for local runs using a plain .env file instead).
try:
    for _key in ("BIBLIO_CONTACT_EMAIL", "NCBI_API_KEY", "OPENALEX_API_KEY",
                 "BIBLIO_CHECKPOINT_EVERY"):
        if _key in st.secrets:
            os.environ.setdefault(_key, str(st.secrets[_key]))
except Exception:
    pass

# A contact email is required at import time by config.py. Fall back to
# Pooja's own email if no BIBLIO_CONTACT_EMAIL secret/env var is set, so
# the app doesn't hard-crash on first load for anyone testing it.
os.environ.setdefault("BIBLIO_CONTACT_EMAIL", "poojaps1999@gmail.com")

from bibliometric_pipeline import config
from bibliometric_pipeline.pipeline import run_pipeline, load_checkpoint, save_results, write_final
from export_scopus_csv import convert_row, SCOPUS_COLUMNS, PROVENANCE_COLUMNS
# Shared with the Phase 1 FastAPI backend (backend/review_logic.py) - this
# is the single implementation of what Accept/Reject/Retry actually do to
# a checkpoint, so Phase 0 and Phase 1 can never drift apart on this logic.
from backend.review_logic import apply_review_decisions

JOBS_DIR = Path(__file__).parent / "jobs"
JOBS_DIR.mkdir(exist_ok=True)

MAX_FREE_ROWS = 1000  # cap for a public/free-tier deployment; see design notes above

st.set_page_config(page_title="Jarvis Scholar - Extractor", layout="wide")
st.title("Jarvis Scholar - Bibliometric Extractor")
st.caption("Upload a title/DOI list -> get back PubMed + OpenAlex + Crossref enriched data, "
           "with checkpointing so a job survives closing the tab.")

with st.sidebar:
    st.header("How it works")
    st.markdown(
        "1. Upload an Excel file with `Sno`, `Clean Title`, and `DOI` columns.\n"
        "2. Click **Run**. Progress is saved every "
        f"{config.CHECKPOINT_EVERY} records.\n"
        "3. If you close this tab, re-upload the **same file** later and "
        "click Run again - it resumes from the last checkpoint instead of "
        "starting over.\n"
        f"4. Public runs are capped at {MAX_FREE_ROWS} titles for now; for "
        "bigger batches use the local CLI script (`run_extractor.py`)."
    )
    st.divider()
    st.caption(f"Contact email in use: {config.CONTACT_EMAIL}")


def job_id_for(file_bytes: bytes, n_rows: int) -> str:
    h = hashlib.md5(file_bytes).hexdigest()[:12]
    return f"{h}_{n_rows}rows"


uploaded = st.file_uploader("Upload title/DOI list (.xlsx)", type=["xlsx"])

if uploaded is not None:
    file_bytes = uploaded.getvalue()
    try:
        df_in = pd.read_excel(uploaded)
    except Exception as e:
        st.error(f"Could not read that file as Excel: {e}")
        st.stop()

    missing = [c for c in (config.COL_SNO, config.COL_TITLE, config.COL_DOI) if c not in df_in.columns]
    if missing:
        st.error(f"Missing required column(s): {missing}. Found: {list(df_in.columns)}")
        st.stop()

    n_rows = len(df_in)
    st.write(f"**{n_rows}** rows found.")

    if n_rows > MAX_FREE_ROWS:
        st.warning(
            f"This file has {n_rows} rows, above the {MAX_FREE_ROWS}-row cap for this "
            "hosted version. Trim the file, or run it locally with "
            "`python3 run_extractor.py` instead (no cap there)."
        )
        st.stop()

    jid = job_id_for(file_bytes, n_rows)
    checkpoint_path = JOBS_DIR / f"{jid}_checkpoint.csv"
    output_path = JOBS_DIR / f"{jid}_output.xlsx"
    overrides_key = f"doi_overrides_{jid}"

    # Apply any manually-corrected DOIs queued from a previous review pass
    # (see the "Manual review" section below) before this run starts, so
    # the corrected DOI is what actually gets (re-)fetched.
    doi_overrides = st.session_state.get(overrides_key, {})
    if doi_overrides:
        sno_str = df_in[config.COL_SNO].astype(str)
        mask = sno_str.isin(doi_overrides.keys())
        df_in.loc[mask, config.COL_DOI] = sno_str[mask].map(doi_overrides)
        st.caption(f"{mask.sum()} DOI override(s) from manual review will be used on the next Run.")

    if checkpoint_path.exists():
        st.info(f"Found a saved checkpoint for this file ({checkpoint_path.name}) - "
                 "Run will resume from where it left off rather than restart.")

    run_clicked = st.button("Run", type="primary")

    if run_clicked:
        progress_bar = st.progress(0)
        status_box = st.empty()
        start = time.time()

        def on_progress(done, total, message):
            frac = min(done / total, 1.0) if total else 0.0
            progress_bar.progress(frac)
            status_box.text(f"[{done}/{total}] {message}")

        with st.spinner("Running extraction - this can take a while for large batches..."):
            final_df, summary = run_pipeline(
                df_in,
                checkpoint_path=str(checkpoint_path),
                output_path=str(output_path),
                progress_callback=on_progress,
            )

        elapsed = time.time() - start
        st.success(f"Done in {elapsed:.0f}s. {summary['done']}/{summary['total']} records completed.")

        if summary.get("dupe_warning"):
            st.warning(summary["dupe_warning"])

        st.subheader("Match status breakdown")
        st.table(pd.DataFrame(
            sorted(summary["status_counts"].items(), key=lambda x: -x[1]),
            columns=["Match Status", "Count"],
        ))

        if summary["n_review"]:
            st.warning(f"{summary['n_review']} record(s) need manual review - see the "
                       "'Match Status' column in the downloaded file.")
        if summary["n_pending_retry"]:
            st.info(f"{summary['n_pending_retry']} record(s) had a transient fetch failure. "
                    "Click Run again (same file) to retry them automatically.")

        st.session_state["last_final_df"] = final_df
        st.session_state["last_output_path"] = str(output_path)

    # Manual review - reads directly from the checkpoint on disk, so it
    # shows up on any rerun (not only right after clicking Run), and it's
    # what "Needs manual review" rows actually resolve to: the matcher
    # already ran, it just wasn't confident enough to auto-accept.
    if checkpoint_path.exists():
        ckpt_df = pd.read_csv(checkpoint_path, dtype={"Sno.": str})
        if "Match Status" in ckpt_df.columns:
            review_mask = ckpt_df["Match Status"] == "Needs manual review"
            review_df = ckpt_df[review_mask].copy()
        else:
            review_df = ckpt_df.iloc[0:0]

        if len(review_df):
            st.subheader(f"Manual review ({len(review_df)} record(s))")
            st.caption(
                "Matched with low confidence. Accept the candidate if it's correct, "
                "reject it to exclude the record, or supply the correct DOI and "
                "re-run to refetch clean data for it."
            )
            display_cols = [c for c in
                             ["Sno.", "Clean Title", "DOI", "Candidate Title (unverified)",
                              "Match Score", "Match Source"]
                             if c in review_df.columns]
            editor_df = review_df[display_cols].reset_index(drop=True).copy()
            editor_df["Decision"] = "Keep as-is"
            editor_df["Corrected DOI"] = ""

            edited = st.data_editor(
                editor_df,
                column_config={
                    "Decision": st.column_config.SelectboxColumn(
                        options=["Keep as-is", "Accept candidate", "Reject (exclude)",
                                 "Retry with corrected DOI"],
                        required=True,
                    ),
                    "Corrected DOI": st.column_config.TextColumn(
                        help="Only used when Decision = 'Retry with corrected DOI'"
                    ),
                },
                disabled=display_cols,
                hide_index=True,
                key=f"review_editor_{jid}",
            )

            if st.button("Apply review decisions", key=f"apply_review_{jid}"):
                overrides = st.session_state.get(overrides_key, {})
                ckpt_df, overrides, counts, warns = apply_review_decisions(ckpt_df, edited, overrides)
                st.session_state[overrides_key] = overrides
                for w in warns:
                    st.warning(w)
                ckpt_df.to_csv(checkpoint_path, index=False)

                # Regenerate the downloadable output file from the updated
                # checkpoint immediately, so Accept/Reject decisions are
                # reflected without needing to click Run again.
                results = {str(r["Sno."]): r for r in ckpt_df.to_dict("records")}
                input_order = [str(s) for s in df_in[config.COL_SNO].tolist()]
                write_final(results, input_order, output_file=str(output_path))

                parts = []
                if counts["accept"]:
                    parts.append(f"{counts['accept']} accepted")
                if counts["reject"]:
                    parts.append(f"{counts['reject']} rejected")
                if counts["retry"]:
                    parts.append(f"{counts['retry']} queued for retry - click Run again to refetch")
                st.success("Applied: " + ", ".join(parts) if parts else "No changes selected.")
                st.rerun()

    # Downloads - shown whenever a completed run exists for this job,
    # even on a later rerun (not just immediately after clicking Run)
    if output_path.exists():
        with open(output_path, "rb") as f:
            st.download_button(
                "Download enriched Excel",
                data=f.read(),
                file_name=f"bibliometric_output_{jid}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        if st.button("Also prepare Scopus-format CSV (for Biblioshiny / VOSviewer)"):
            with st.spinner("Converting to Scopus CSV format..."):
                out_df = pd.read_excel(output_path)
                if "Dedup Status" in out_df.columns:
                    is_dup = out_df["Dedup Status"].astype(str).str.startswith("Duplicate")
                    if is_dup.any():
                        st.caption(f"Skipping {int(is_dup.sum())} row(s) flagged as duplicates.")
                    out_df = out_df[~is_dup]
                scopus_rows = [convert_row(row) for _, row in out_df.iterrows()]
                scopus_df = pd.DataFrame(scopus_rows, columns=SCOPUS_COLUMNS + PROVENANCE_COLUMNS)
                csv_bytes = scopus_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
            st.download_button(
                "Download Scopus-format CSV",
                data=csv_bytes,
                file_name=f"scopus_format_{jid}.csv",
                mime="text/csv",
            )
else:
    st.info("Upload a file to get started.")
