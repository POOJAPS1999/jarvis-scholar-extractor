"""
main.py
=======
FastAPI app for Jarvis Scholar Phase 1.

Routes:
  POST /jobs                 - upload a title/DOI Excel file, creates a Job
                                row, queues extraction on the Celery worker
  GET  /jobs                 - list recent jobs (most recent first)
  GET  /jobs/{job_id}        - status/progress for one job
  GET  /jobs/{job_id}/result - download the enriched output .xlsx
  GET  /jobs/{job_id}/scopus-csv - download Biblioshiny/VOSviewer-ready
                                Scopus-format CSV, built on the fly from
                                the completed output (reuses
                                export_scopus_csv.convert_row exactly as
                                Phase 0's Streamlit app does)
  GET  /jobs/{job_id}/review - rows flagged "Needs manual review"
  POST /jobs/{job_id}/review - submit accept/reject/retry decisions
                                (reuses backend.review_logic.apply_review_decisions,
                                the same function the Streamlit app uses)
  POST /jobs/{job_id}/requeue - re-run (resumes from last checkpoint if the
                                worker crashed, or re-fetches records queued
                                for retry via manual review's corrected DOI)

Run locally: uvicorn backend.main:app --reload --port 8000
(from the bibliometric_pipeline_project/ directory, so the bibliometric_pipeline
and export_scopus_csv modules import correctly - same working-directory
requirement Phase 0's streamlit_app.py already has.)
"""
import os
import sys
from typing import List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select
import io

from bibliometric_pipeline import config
from export_scopus_csv import convert_row, SCOPUS_COLUMNS, PROVENANCE_COLUMNS
from .models import init_db, engine, Job, new_job_id
from .celery_app import celery_app
from .tasks import run_extraction_job
from . import storage
from .review_logic import apply_review_decisions

MAX_ROWS = int(os.environ.get("JARVIS_MAX_ROWS", "20000"))

app = FastAPI(title="Jarvis Scholar API", version="0.1.0-phase1")


@app.on_event("startup")
def on_startup():
    init_db()


def _job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "filename": job.filename,
        "status": job.status,
        "total_rows": job.total_rows,
        "done_rows": job.done_rows,
        "progress_message": job.progress_message,
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


@app.post("/jobs")
async def create_job(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Only .xlsx files are accepted.")

    raw = await file.read()
    try:
        df_in = pd.read_excel(io.BytesIO(raw))
    except Exception as e:
        raise HTTPException(400, f"Could not read that file as Excel: {e}")

    missing = [c for c in (config.COL_SNO, config.COL_TITLE, config.COL_DOI) if c not in df_in.columns]
    if missing:
        raise HTTPException(400, f"Missing required column(s): {missing}. Found: {list(df_in.columns)}")

    if len(df_in) > MAX_ROWS:
        raise HTTPException(
            400,
            f"This file has {len(df_in)} rows, above the {MAX_ROWS}-row limit "
            f"for a single job. Split it into smaller batches."
        )

    # Generate the id upfront so storage keys (which embed it) can be set
    # in the same single insert, instead of an insert-then-update dance.
    job_id = new_job_id()
    input_key = f"jobs/{job_id}/input.xlsx"
    checkpoint_key = f"jobs/{job_id}/checkpoint.csv"
    output_key = f"jobs/{job_id}/output.xlsx"

    with Session(engine) as session:
        job = Job(
            id=job_id,
            filename=file.filename,
            total_rows=len(df_in),
            input_key=input_key,
            checkpoint_key=checkpoint_key,
            output_key=output_key,
        )
        session.add(job)
        session.commit()

    storage.save(input_key, raw)

    run_extraction_job.delay(job_id)

    return {"job_id": job_id, "total_rows": len(df_in), "status": "queued"}


@app.get("/jobs")
def list_jobs(limit: int = 20):
    with Session(engine) as session:
        jobs = session.exec(select(Job).order_by(Job.created_at.desc()).limit(limit)).all()
        return [_job_to_dict(j) for j in jobs]


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        return _job_to_dict(job)


@app.post("/jobs/{job_id}/requeue")
def requeue_job(job_id: str):
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        job.status = "queued"
        job.error_message = ""
        session.add(job)
        session.commit()
    run_extraction_job.delay(job_id)
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}/result")
def download_result(job_id: str):
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job.status != "completed":
            raise HTTPException(409, f"Job is '{job.status}', not completed yet.")
    data = storage.load(job.output_key)
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="bibliometric_output_{job_id}.xlsx"'},
    )


@app.get("/jobs/{job_id}/scopus-csv")
def download_scopus_csv(job_id: str):
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
        if job.status != "completed":
            raise HTTPException(409, f"Job is '{job.status}', not completed yet.")
    out_df = storage.load_dataframe_excel(job.output_key)
    if "Dedup Status" in out_df.columns:
        is_dup = out_df["Dedup Status"].astype(str).str.startswith("Duplicate")
        out_df = out_df[~is_dup]
    scopus_rows = [convert_row(row) for _, row in out_df.iterrows()]
    scopus_df = pd.DataFrame(scopus_rows, columns=SCOPUS_COLUMNS + PROVENANCE_COLUMNS)
    csv_bytes = scopus_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="scopus_format_{job_id}.csv"'},
    )


@app.get("/jobs/{job_id}/review")
def get_review_rows(job_id: str):
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found")
    if not storage.exists(job.checkpoint_key):
        return {"rows": []}
    ckpt_df = storage.load_dataframe_csv(job.checkpoint_key, dtype={"Sno.": str})
    if "Match Status" not in ckpt_df.columns:
        return {"rows": []}
    review_df = ckpt_df[ckpt_df["Match Status"] == "Needs manual review"]
    cols = [c for c in ["Sno.", "Clean Title", "DOI", "Candidate Title (unverified)",
                         "Match Score", "Match Source"] if c in review_df.columns]
    return {"rows": review_df[cols].to_dict("records")}


class ReviewDecision(BaseModel):
    sno: str
    decision: str  # "Accept candidate" | "Reject (exclude)" | "Retry with corrected DOI"
    corrected_doi: Optional[str] = ""


class ReviewSubmission(BaseModel):
    decisions: List[ReviewDecision]


@app.post("/jobs/{job_id}/review")
def submit_review(job_id: str, submission: ReviewSubmission):
    with Session(engine) as session:
        job = session.get(Job, job_id)
        if not job:
            raise HTTPException(404, "Job not found")

    if not storage.exists(job.checkpoint_key):
        raise HTTPException(409, "No checkpoint exists yet for this job.")

    ckpt_df = storage.load_dataframe_csv(job.checkpoint_key, dtype={"Sno.": str})
    edited_df = pd.DataFrame([
        {"Sno.": d.sno, "Decision": d.decision, "Corrected DOI": d.corrected_doi or ""}
        for d in submission.decisions
    ])

    # DOI overrides queued by "Retry with corrected DOI" decisions need to
    # land back in the ORIGINAL input file's DOI column before the next
    # run, exactly like Phase 0's session_state-based override did -
    # except here it has to be durable (a different worker process may
    # pick up the requeue), so it's written into the stored input file
    # directly rather than kept in memory.
    new_ckpt, overrides, counts, warnings = apply_review_decisions(ckpt_df, edited_df, {})

    storage.save_dataframe_csv(job.checkpoint_key, new_ckpt)

    if overrides:
        df_in = storage.load_dataframe_excel(job.input_key)
        sno_str = df_in[config.COL_SNO].astype(str)
        mask = sno_str.isin(overrides.keys())
        df_in.loc[mask, config.COL_DOI] = sno_str[mask].map(overrides)
        storage.save_dataframe_excel(job.input_key, df_in)

    return {"counts": counts, "warnings": warnings, "queued_for_retry": list(overrides.keys())}
