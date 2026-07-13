"""
Data Enrichment
===============
The core Jarvis Scholar pipeline: upload a title/DOI list -> PubMed +
OpenAlex + Crossref enriched data. This is the same thin-HTTP-client flow
that used to live in streamlit_app.py (now the dashboard home); it was moved
here so each capability is its own selectable tool on the dashboard.
"""
import hashlib
import io
import os
import time

import pandas as pd
import requests
import streamlit as st

_HERE = os.path.dirname(os.path.abspath(__file__))
import sys
sys.path.insert(0, os.path.dirname(_HERE))
from bibliometric_pipeline.branding import THEME_CSS, reactor_loader_html, jarvis_spinner, enrichment_template_bytes, how_to_use, brand_footer, enrichment_preview

try:
    _secret_url = st.secrets.get("API_BASE_URL")
except Exception:
    _secret_url = None
API_BASE_URL = (
    _secret_url
    or os.environ.get("JARVIS_API_URL")
    or "https://jarvis-scholar-extractor-production.up.railway.app"
).rstrip("/")

REQUIRED_COLUMNS = ["Sno", "Clean Title", "DOI"]

st.set_page_config(page_title="Jarvis Scholar - Data Enrichment", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)
from bibliometric_pipeline.auth import require_login, sidebar_account
require_login()
sidebar_account()
st.title("Data Enrichment")
st.caption(
    "Upload a title/DOI list → get back PubMed + OpenAlex + Crossref enriched data. "
    "Runs on the hosted backend, so the job keeps running (and your progress is kept) "
    "even if you close this tab."
)

with st.expander("📋 Required format — and download a blank template", expanded=False):
    st.markdown(
        "Your file must be an **.xlsx** with exactly these column headers:\n\n"
        "- **Sno** — a serial number (any unique value per row)\n"
        "- **Clean Title** — the article title\n"
        "- **DOI** — the DOI (may be blank if unknown; a title is then used to match)\n\n"
        "Download the template, fill it in, and upload it below."
    )
    st.download_button(
        "⬇ Download blank enrichment template (.xlsx)",
        data=enrichment_template_bytes(),
        file_name="jarvis_scholar_enrichment_template.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

with st.sidebar:
    st.caption(f"Backend: {API_BASE_URL}")
    with st.expander("Recent jobs on this backend"):
        try:
            recent = requests.get(f"{API_BASE_URL}/jobs", params={"limit": 10}, timeout=15).json()
        except Exception as e:
            recent = None
            st.caption(f"Could not reach backend: {e}")
        if recent:
            st.dataframe(
                pd.DataFrame(recent)[["id", "filename", "status", "done_rows", "total_rows"]],
                hide_index=True,
            )


def api_get(path, **kw):
    r = requests.get(f"{API_BASE_URL}{path}", timeout=30, **kw)
    r.raise_for_status()
    return r


def api_post(path, **kw):
    r = requests.post(f"{API_BASE_URL}{path}", timeout=60, **kw)
    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise RuntimeError(detail)
    return r


def file_hash(b: bytes) -> str:
    return hashlib.md5(b).hexdigest()[:12]


uploaded = st.file_uploader("Upload title/DOI list (.xlsx)", type=["xlsx"])

if uploaded is not None:
    file_bytes = uploaded.getvalue()
    fid = file_hash(file_bytes)
    job_key = f"job_id_{fid}"

    try:
        df_preview = pd.read_excel(io.BytesIO(file_bytes))
    except Exception as e:
        st.error(f"Could not read that file as Excel: {e}")
        st.stop()

    missing = [c for c in REQUIRED_COLUMNS if c not in df_preview.columns]
    if missing:
        st.error(f"Missing required column(s): {missing}. Found: {list(df_preview.columns)}")
        st.stop()

    st.write(f"**{len(df_preview)}** rows found.")

    job_id = st.session_state.get(job_key)

    if not job_id:
        icmr_mode = st.checkbox(
            "ICMR mode — add ICMR institute + author-flag columns",
            value=False,
            help="Tags each record with its ICMR constituent institute (current "
                 "name, handling former names/acronyms) and adds First/Corresponding/"
                 "Any-author-from-ICMR flag columns to the output. Leave off for "
                 "general (non-ICMR) datasets.",
        )
        if st.button("Start extraction", type="primary"):
            with jarvis_spinner("Uploading and queueing job..."):
                try:
                    resp = api_post(
                        "/jobs",
                        files={"file": (
                            uploaded.name, file_bytes,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )},
                        data={"icmr_mode": "true" if icmr_mode else "false"},
                    )
                except Exception as e:
                    st.error(f"Could not start job: {e}")
                    st.stop()
            st.session_state[job_key] = resp.json()["job_id"]
            st.rerun()
    else:
        try:
            job = api_get(f"/jobs/{job_id}").json()
        except Exception as e:
            st.error(f"Could not fetch job status: {e}")
            if st.button("Forget this job and start over"):
                del st.session_state[job_key]
                st.rerun()
            st.stop()

        status = job["status"]
        total = job.get("total_rows") or 0
        done = job.get("done_rows") or 0

        if status in ("queued", "running"):
            loader = st.empty()
            progress_bar = st.progress(min(done / total, 1.0) if total else 0.0)
            status_box = st.empty()
            loader.markdown(reactor_loader_html("JARVIS is enriching your records…"),
                            unsafe_allow_html=True)
            status_box.text(f"[{done}/{total}] {job.get('progress_message') or status}")

            # Poll the backend for progress. Every network call here is
            # wrapped: a transient blip talking to Railway must never throw an
            # unhandled exception (that crashes the whole Streamlit app with
            # "Error running app"). On repeated failures we stop watching and
            # let the user refresh, rather than crashing.
            consecutive_errors = 0
            for _ in range(150):  # ~5 minutes of active polling before we give up watching
                time.sleep(2)
                try:
                    job = api_get(f"/jobs/{job_id}").json()
                    consecutive_errors = 0
                except Exception:
                    consecutive_errors += 1
                    if consecutive_errors >= 5:
                        status_box.warning(
                            "Lost contact with the backend while watching progress. "
                            "The job keeps running — refresh this page to check again."
                        )
                        break
                    continue
                status = job.get("status", status)
                total = job.get("total_rows") or total
                done = job.get("done_rows") or done
                try:
                    progress_bar.progress(min(done / total, 1.0) if total else 0.0)
                    status_box.text(f"[{done}/{total}] {job.get('progress_message') or status}")
                except Exception:
                    pass
                if status in ("completed", "failed"):
                    break
            loader.empty()

            if status in ("queued", "running"):
                st.info(
                    "Still running. The job keeps going on the backend even if you close "
                    "this tab - come back later and re-upload the same file to check again."
                )
                st.stop()

        if status == "failed":
            st.error(f"Job failed: {job.get('error_message') or 'unknown error'}")
            col1, col2 = st.columns(2)
            if col1.button("Retry", key=f"retry_{job_id}"):
                api_post(f"/jobs/{job_id}/requeue")
                st.rerun()
            if col2.button("Forget this job and start over", key=f"forget_{job_id}"):
                del st.session_state[job_key]
                st.rerun()
            st.stop()

        # status == "completed"
        st.success(f"Done. {done}/{total} records completed.")

        # --- Manual review ---
        try:
            review_rows = api_get(f"/jobs/{job_id}/review").json().get("rows", [])
        except Exception:
            review_rows = []

        if review_rows:
            review_df = pd.DataFrame(review_rows)
            st.subheader(f"Manual review ({len(review_df)} record(s))")
            st.caption(
                "Matched with low confidence. Accept the candidate if it's correct, "
                "reject it to exclude the record, or supply the correct DOI and "
                "retry to refetch clean data for it."
            )
            display_cols = list(review_df.columns)
            editor_df = review_df.reset_index(drop=True).copy()
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
                key=f"review_editor_{job_id}",
            )

            if st.button("Apply review decisions", key=f"apply_review_{job_id}"):
                decisions = []
                for _, row in edited.iterrows():
                    if row["Decision"] == "Keep as-is":
                        continue
                    decisions.append({
                        "sno": str(row["Sno."]),
                        "decision": row["Decision"],
                        "corrected_doi": row.get("Corrected DOI", "") or "",
                    })
                if not decisions:
                    st.info("No changes selected.")
                else:
                    try:
                        result = api_post(
                            f"/jobs/{job_id}/review", json={"decisions": decisions}
                        ).json()
                    except Exception as e:
                        st.error(f"Could not submit review: {e}")
                        st.stop()

                    for w in result.get("warnings", []):
                        st.warning(w)
                    counts = result.get("counts", {})
                    parts = []
                    if counts.get("accept"):
                        parts.append(f"{counts['accept']} accepted")
                    if counts.get("reject"):
                        parts.append(f"{counts['reject']} rejected")
                    if counts.get("retry"):
                        parts.append(f"{counts['retry']} queued for retry")
                    st.success("Applied: " + ", ".join(parts) if parts else "No changes applied.")

                    # Only a "Retry with corrected DOI" decision needs a real
                    # re-run (the backend reports this via needs_requeue).
                    # Accept/Reject are recorded straight into the output by
                    # the backend with no re-extraction, so we must NOT requeue
                    # for them - that was the bug where accepting a reviewed
                    # row kicked off a full extraction again.
                    if result.get("needs_requeue"):
                        api_post(f"/jobs/{job_id}/requeue")
                    st.rerun()

        # --- Downloads ---
        try:
            output_bytes = api_get(f"/jobs/{job_id}/result").content
        except Exception as e:
            output_bytes = None
            st.error(f"Could not fetch result file: {e}")

        if output_bytes:
            out_df = pd.read_excel(io.BytesIO(output_bytes))
            if "Match Status" in out_df.columns:
                st.subheader("Match status breakdown")
                counts = out_df["Match Status"].value_counts()
                st.table(pd.DataFrame(
                    sorted(counts.items(), key=lambda x: -x[1]),
                    columns=["Match Status", "Count"],
                ))

            dcol1, dcol2 = st.columns(2)
            dcol1.download_button(
                "⬇ Download enriched Excel",
                data=output_bytes,
                file_name=f"bibliometric_output_{job_id}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            # Scopus-format CSV, generated inline from the enriched output (no
            # extra click, no page reset) — same converter as the standalone tool.
            try:
                from export_scopus_csv import to_scopus_csv_bytes
                scopus_bytes = to_scopus_csv_bytes(out_df)
                dcol2.download_button(
                    "⬇ Download Scopus-format CSV (Biblioshiny / VOSviewer)",
                    data=scopus_bytes,
                    file_name=f"scopus_format_{job_id}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )
            except Exception as e:
                dcol2.caption(f"Scopus CSV unavailable: {e}")
            brand_footer(note=f"{done}/{total} records enriched")

        if st.button("Start a new job (different file)", key=f"reset_{job_id}"):
            del st.session_state[job_key]
            st.rerun()
else:
    st.info("Upload a file to get started, or download the template above first.")

st.markdown("---")
how_to_use([
    ("📄", "Get your input file right",
     "You need an .xlsx with three columns: Sno, Clean Title, DOI. Download the blank template above if you’re not sure."),
    ("📤", "Upload & (optionally) tick ICMR mode",
     "Upload the file. Turn on ‘ICMR mode’ only if you want ICMR institute + author-flag columns added."),
    ("🛰", "Start extraction",
     "Click ‘Start extraction’. It runs on the hosted backend — the JARVIS loader tracks progress and the job survives closing the tab."),
    ("✅", "Review low-confidence matches",
     "Accept, reject, or retry-with-a-corrected-DOI. Accept/Reject are recorded instantly — only a corrected-DOI retry re-runs that row."),
    ("⬇️", "Download results",
     "Grab the enriched Excel, or the Scopus-format CSV right there on the results page (for Biblioshiny/VOSviewer)."),
], preview_image=enrichment_preview(),
   preview_caption="Exactly three columns: Sno, Clean Title, DOI (download the template above)")
