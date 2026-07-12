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
import requests
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session, select
import io

from bibliometric_pipeline import config
from export_scopus_csv import convert_row, SCOPUS_COLUMNS, PROVENANCE_COLUMNS
from .models import init_db, engine, Job, User, new_job_id
from .celery_app import celery_app
from .tasks import run_extraction_job
from . import storage
from .review_logic import apply_review_decisions

MAX_ROWS = int(os.environ.get("JARVIS_MAX_ROWS", "20000"))

app = FastAPI(title="Jarvis Scholar API", version="0.1.0-phase1")


@app.on_event("startup")
def on_startup():
    init_db()


# ---------------------------------------------------------------------
# Auth (password accounts) — passwords hashed with stdlib PBKDF2 (no native
# deps). Each new signup is also POSTed to REGISTRATION_WEBHOOK_URL (e.g. a
# Google Apps Script that appends to a Sheet), best-effort.
# ---------------------------------------------------------------------
import base64
import hashlib
import hmac
import secrets
import json as _json
import urllib.request
from datetime import datetime, timezone


def _hash_password(pw: str) -> str:
    salt = secrets.token_bytes(16)
    iters = 200_000
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, iters)
    return f"pbkdf2${iters}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def _verify_password(pw: str, stored: str) -> bool:
    try:
        _algo, iters, salt_b64, hash_b64 = stored.split("$")
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), salt, int(iters))
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


def _post_registration_webhook(payload: dict):
    """Best-effort POST of each new signup to REGISTRATION_WEBHOOK_URL (e.g.
    a Google Apps Script that appends to a Sheet). Uses requests (handles the
    Apps Script 302 redirect reliably) and logs the outcome so a
    misconfigured webhook is visible in the Railway logs — but never raises,
    so a webhook problem can't break signup."""
    url = os.environ.get("REGISTRATION_WEBHOOK_URL")
    if not url:
        print("[webhook] REGISTRATION_WEBHOOK_URL not set — signup stored in DB only.")
        return
    try:
        import requests
        r = requests.post(url, json=payload, timeout=8, allow_redirects=True)
        print(f"[webhook] POST {r.status_code} to registration webhook for {payload.get('email')}")
    except Exception as e:
        print(f"[webhook] FAILED for {payload.get('email')}: {e}")


class SignupBody(BaseModel):
    email: str
    password: str
    name: str = ""
    last_name: str = ""
    institution: str = ""
    role: str = ""
    designation: str = ""


class LoginBody(BaseModel):
    email: str
    password: str


def _public_user(u: User) -> dict:
    return {"email": u.email, "name": u.name, "last_name": u.last_name,
            "institution": u.institution, "role": u.role, "designation": u.designation}


@app.post("/auth/signup")
def signup(body: SignupBody):
    email = (body.email or "").strip().lower()
    if "@" not in email or "." not in email:
        raise HTTPException(400, "Please enter a valid email address.")
    if len(body.password or "") < 6:
        raise HTTPException(400, "Password must be at least 6 characters.")
    with Session(engine) as session:
        if session.exec(select(User).where(User.email == email)).first():
            raise HTTPException(409, "An account with this email already exists — please log in.")
        u = User(email=email, name=body.name.strip(), last_name=body.last_name.strip(),
                 institution=body.institution.strip(), role=body.role.strip(),
                 designation=body.designation.strip(),
                 password_hash=_hash_password(body.password))
        session.add(u)
        session.commit()
        session.refresh(u)
        pub = _public_user(u)
        created = u.created_at.isoformat() if u.created_at else ""
    _post_registration_webhook({**pub, "created_at": created})
    return {"ok": True, **pub}


@app.post("/auth/login")
def login(body: LoginBody):
    email = (body.email or "").strip().lower()
    with Session(engine) as session:
        u = session.exec(select(User).where(User.email == email)).first()
        if not u or not _verify_password(body.password or "", u.password_hash):
            raise HTTPException(401, "Wrong email or password.")
        u.last_login = datetime.now(timezone.utc)
        session.add(u)
        session.commit()
        pub = _public_user(u)
    return {"ok": True, **pub}


_FIGURE_PROMPT = (
    "You are a scientometrics and bibliometrics expert helping a researcher write up their "
    "analysis. Interpret this figure in clear, plain language suitable for a paper's Results/"
    "Discussion. Cover: (1) what the figure shows and how to read it, (2) the main patterns — "
    "the largest/most central items, distinct clusters or groups and what they seem to represent, "
    "and any notable outliers, and (3) 2–4 concrete takeaways a reader should draw. Be specific "
    "and reference actual labels/values you can see. Do not invent numbers you cannot see. Keep it "
    "concise (roughly 150–250 words). {context}"
)


def _anthropic_vision(key, media, b64, prompt):
    model = os.environ.get("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")
    body = {"model": model, "max_tokens": 900, "messages": [{"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": media, "data": b64}},
        {"type": "text", "text": prompt}]}]}
    r = requests.post("https://api.anthropic.com/v1/messages",
                      headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                               "content-type": "application/json"}, json=body, timeout=90)
    if not r.ok:
        raise HTTPException(502, f"Anthropic error {r.status_code}: {r.text[:300]}")
    data = r.json()
    text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text").strip()
    return text, f"anthropic:{model}"


def _gemini_pick_model(key):
    """Query the account's available models and pick a vision-capable Flash
    model that supports generateContent (self-heals when Google retires a
    model name)."""
    try:
        lst = requests.get(
            f"https://generativelanguage.googleapis.com/v1beta/models?key={key}",
            timeout=30).json()
    except Exception:
        return None
    names = []
    for m in lst.get("models", []):
        if "generateContent" not in m.get("supportedGenerationMethods", []):
            continue
        short = m.get("name", "").split("/")[-1]
        low = short.lower()
        if any(x in low for x in ("embedding", "aqa", "imagen", "veo", "tts")):
            continue
        names.append(short)
    # prefer stable flash models, newest-looking first
    flash = sorted([n for n in names if "flash" in n.lower() and "thinking" not in n.lower()],
                   reverse=True)
    return (flash or names or [None])[0]


def _gemini_vision(key, media, b64, prompt):
    """Google Gemini — has a free tier (Google AI Studio key)."""
    body = {"contents": [{"parts": [
        {"inline_data": {"mime_type": media, "data": b64}},
        {"text": prompt}]}]}

    def _call(m):
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={key}"
        return requests.post(url, json=body, timeout=90)

    model = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
    r = _call(model)
    if r.status_code == 404:  # model retired/renamed → discover a live one
        discovered = _gemini_pick_model(key)
        if discovered:
            model = discovered
            r = _call(model)
    if not r.ok:
        raise HTTPException(502, f"Gemini error {r.status_code}: {r.text[:300]}")
    data = r.json()
    text = ""
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            text += part.get("text", "")
    return text.strip(), f"gemini:{model}"


@app.post("/ai/interpret-figure")
async def interpret_figure(file: UploadFile = File(...), context: str = Form("")):
    """Vision-model interpretation of a bibliometric figure. Uses whichever
    provider is configured: GEMINI_API_KEY (free tier) or ANTHROPIC_API_KEY.
    Keys are read from the environment, never hardcoded."""
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
    if not (gemini_key or anthropic_key):
        raise HTTPException(400, "AI figure interpretation isn't configured — set a (free) "
                                 "GEMINI_API_KEY, or an ANTHROPIC_API_KEY, on the server.")
    raw = await file.read()
    if len(raw) > 5 * 1024 * 1024:
        raise HTTPException(400, "Image too large (max 5 MB).")
    media = (file.content_type or "").lower()
    if media in ("image/jpg", "image/jpeg"):
        media = "image/jpeg"
    elif media not in ("image/png", "image/gif", "image/webp"):
        media = "image/png"
    import base64 as _b64
    b64 = _b64.b64encode(raw).decode()
    ctx = f"Context provided by the user about this figure: {context.strip()}" if context.strip() else ""
    prompt = _FIGURE_PROMPT.format(context=ctx)
    try:
        if gemini_key:          # prefer the free provider if configured
            text, model = _gemini_vision(gemini_key, media, b64, prompt)
        else:
            text, model = _anthropic_vision(anthropic_key, media, b64, prompt)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(502, f"Could not reach the AI service: {e}")
    if not text:
        raise HTTPException(502, "AI service returned no interpretation.")
    return {"interpretation": text, "model": model}


@app.get("/auth/registrations")
def export_registrations(key: str = ""):
    """Download all registrations as CSV. Protected by the ADMIN_KEY env var."""
    admin = os.environ.get("ADMIN_KEY")
    if not admin or key != admin:
        raise HTTPException(403, "Forbidden — pass ?key=<ADMIN_KEY>.")
    import csv
    with Session(engine) as session:
        users = session.exec(select(User)).all()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["email", "name", "last_name", "institution", "role", "designation",
                "created_at", "last_login"])
    for u in users:
        w.writerow([u.email, u.name, u.last_name, u.institution, u.role, u.designation,
                    u.created_at.isoformat() if u.created_at else "",
                    u.last_login.isoformat() if u.last_login else ""])
    return StreamingResponse(io.BytesIO(buf.getvalue().encode("utf-8-sig")),
                             media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="registrations.csv"'})


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
async def create_job(file: UploadFile = File(...), icmr_mode: bool = Form(False)):
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

    # Per-job options are persisted as a small JSON file in the SAME object
    # storage as the input/checkpoint/output (NOT a new Postgres column, so
    # no live DB migration is needed). The worker and the /requeue path both
    # read it back, so an "ICMR mode" choice survives a requeue and never
    # leaks into a different job running in the same worker process.
    _save_job_config(job_id, {"optional_column_groups":
                              ["icmr_flags", "icmr_institute"] if icmr_mode else []})

    run_extraction_job.delay(job_id)

    return {"job_id": job_id, "total_rows": len(df_in), "status": "queued",
            "icmr_mode": bool(icmr_mode)}


def _config_key(job_id: str) -> str:
    return f"jobs/{job_id}/config.json"


def _save_job_config(job_id: str, cfg: dict) -> None:
    import json
    storage.save(_config_key(job_id), json.dumps(cfg).encode("utf-8"))


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

    # A "Retry with corrected DOI" decision is the ONLY one that needs a
    # real re-run (it has to re-fetch that row with the new DOI). Accept and
    # Reject are pure bookkeeping on data we already have - they must NOT
    # trigger another extraction. For those, regenerate the downloadable
    # output straight from the (already-updated) checkpoint so the decision
    # shows up immediately, with no fetch loop and no "running" state.
    needs_requeue = bool(overrides)
    if not needs_requeue:
        _rebuild_output_from_checkpoint(job)

    return {
        "counts": counts,
        "warnings": warnings,
        "needs_requeue": needs_requeue,
        "queued_for_retry": list(overrides.keys()),
    }


def _rebuild_output_from_checkpoint(job):
    """Rewrite the job's output .xlsx directly from the current checkpoint,
    ordered by the input file's Sno order — WITHOUT running the pipeline /
    any network fetching. Used after Accept/Reject-only review decisions so
    the manual-review Match Status ('Confirmed (manual review)' /
    'Rejected (manual review)') lands in the downloadable file without
    re-extracting anything. The checkpoint already carries exactly the
    output columns (it was written by the same projection), so this is a
    pure reorder-and-save."""
    ckpt_df = storage.load_dataframe_csv(job.checkpoint_key, dtype={"Sno.": str})
    try:
        df_in = storage.load_dataframe_excel(job.input_key)
        order = [str(s) for s in df_in[config.COL_SNO].tolist()]
        pos = {s: i for i, s in enumerate(order)}
        ckpt_df["_ord"] = ckpt_df["Sno."].astype(str).map(lambda s: pos.get(s, 10**9))
        ckpt_df = ckpt_df.sort_values("_ord", kind="stable").drop(columns=["_ord"])
    except Exception:
        pass  # if input ordering can't be recovered, save in checkpoint order
    storage.save_dataframe_excel(job.output_key, ckpt_df)
