"""
streamlit_app.py
=================
Jarvis Scholar - Phase 0 UI, now a THIN CLIENT of the Phase 1 API.

This file used to run bibliometric_pipeline.pipeline.run_pipeline() directly,
in-process, on Streamlit Community Cloud's own compute. It no longer does
that - all extraction work happens on the Phase 1 backend (FastAPI + Celery +
Redis + Postgres, deployed on Railway). This file only ever does HTTP calls
to that backend's /jobs API. Benefits of the switch:
  - Jobs survive closing this tab AND surviving a Streamlit app reboot
    (Community Cloud's disk is ephemeral; Railway's Postgres/object storage
    is not).
  - No more MAX_FREE_ROWS row cap tied to Streamlit's free-tier compute -
    the backend's own JARVIS_MAX_ROWS limit (much higher) applies instead.
  - This file no longer needs BIBLIO_CONTACT_EMAIL / NCBI_API_KEY /
    OPENALEX_API_KEY at all - those only matter to whatever process is
    actually calling PubMed/OpenAlex/Crossref, which is now the Railway
    worker, not this Streamlit app.

USAGE (local):
    pip3 install streamlit requests pandas openpyxl
    streamlit run streamlit_app.py
    (optionally set JARVIS_API_URL env var to point at a local
    `uvicorn backend.main:app --port 8000` instead of the deployed backend)

DEPLOY, on share.streamlit.io / Streamlit Community Cloud:
  1. Push this repo to GitHub (same repo as the backend - no extra steps).
  2. New app -> pick the repo/branch -> main file path: streamlit_app.py
  3. (Optional) App -> Settings -> Secrets:
         API_BASE_URL = "https://jarvis-scholar-extractor-production.up.railway.app"
     Only needed if the backend's URL ever changes - it defaults to the
     current Railway URL below.
"""
import hashlib
import io
import os
import time

import pandas as pd
import requests
import streamlit as st

# Which backend to talk to. Priority: Streamlit secret > env var > the
# current Railway deployment's public URL.
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

st.set_page_config(page_title="Jarvis Scholar - Extractor", layout="wide")
st.title("Jarvis Scholar - Bibliometric Extractor")
st.caption(
    "Upload a title/DOI list -> get back PubMed + OpenAlex + Crossref enriched data. "
    "Runs on Jarvis Scholar's hosted backend, so the job keeps running (and your "
    "progress is kept) even if you close this tab."
)

with st.sidebar:
    st.header("How it works")
    st.markdown(
        "1. Upload an Excel file with `Sno`, `Clean Title`, and `DOI` columns.\n"
        "2. Click **Start extraction**. It runs on the hosted backend.\n"
        "3. Come back any time and re-upload the **same file** to check "
        "progress or grab your results - you don't need to keep this tab open.\n"
    )
    st.divider()
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
        if st.button("Start extraction", type="primary"):
            with st.spinner("Uploading and queueing job..."):
                try:
                    resp = api_post(
                        "/jobs",
                        files={"file": (
                            uploaded.name, file_bytes,
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        )},
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
            progress_bar = st.progress(min(done / total, 1.0) if total else 0.0)
            status_box = st.empty()
            status_box.text(f"[{done}/{total}] {job.get('progress_message') or status}")

            with st.spinner("Extraction running on the hosted backend..."):
                for _ in range(150):  # ~5 minutes of active polling before we give up watching
                    time.sleep(2)
                    job = api_get(f"/jobs/{job_id}").json()
                    status = job["status"]
                    total = job.get("total_rows") or total
                    done = job.get("done_rows") or done
                    progress_bar.progress(min(done / total, 1.0) if total else 0.0)
                    status_box.text(f"[{done}/{total}] {job.get('progress_message') or status}")
                    if status in ("completed", "failed"):
                        break

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

                    # The backend only regenerates the downloadable output
                    # file as part of a full (re-)run, so requeue any time a
                    # decision changed the checkpoint - even accept/reject
                    # only, not just corrected-DOI retries - so the
                    # downloaded file actually reflects these decisions.
                    if any(counts.get(k) for k in ("accept", "reject", "retry")):
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

            st.download_button(
                "Download enriched Excel",
                data=output_bytes,
                file_name=f"bibliometric_output_{job_id}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            if st.button("Also prepare Scopus-format CSV (for Biblioshiny / VOSviewer)"):
                with st.spinner("Converting to Scopus CSV format..."):
                    try:
                        csv_bytes = api_get(f"/jobs/{job_id}/scopus-csv").content
                    except Exception as e:
                        st.error(f"Could not generate Scopus CSV: {e}")
                        csv_bytes = None
                if csv_bytes:
                    st.download_button(
                        "Download Scopus-format CSV",
                        data=csv_bytes,
                        file_name=f"scopus_format_{job_id}.csv",
                        mime="text/csv",
                    )

        if st.button("Start a new job (different file)", key=f"reset_{job_id}"):
            del st.session_state[job_key]
            st.rerun()
else:
    st.info("Upload a file to get started.")
