# Jarvis Scholar - Phase 1 backend

A real background-job API sitting behind Phase 0's Streamlit app (or any
future frontend): FastAPI for the HTTP layer, Celery + Redis for the job
queue, Postgres for job metadata, and pluggable object storage (local disk
for dev, S3-compatible for production) for the actual files.

None of the matching/fetching logic changed to get here - this is plumbing
around the exact same `bibliometric_pipeline.pipeline.run_pipeline()`,
`matcher.py`, and `export_scopus_csv.convert_row()` that Phase 0 uses.

## Local development

```bash
cd bibliometric_pipeline_project
pip3 install -r requirements.txt -r backend/requirements.txt
cp backend/.env.example backend/.env   # edit BIBLIO_CONTACT_EMAIL at minimum
```

You need Redis running locally for the worker to pick up jobs (Postgres is
optional locally - DATABASE_URL defaults to a SQLite file if unset):

```bash
# macOS: brew install redis && brew services start redis
# or: docker run -p 6379:6379 redis
```

Then, in two separate terminals:

```bash
# Terminal 1 - the API
uvicorn backend.main:app --reload --port 8000

# Terminal 2 - the worker (actually runs extraction jobs)
celery -A backend.celery_app worker --loglevel=info
```

Try it:

```bash
curl -F "file=@/path/to/Test.xlsx" http://localhost:8000/jobs
# -> {"job_id": "...", "total_rows": N, "status": "queued"}

curl http://localhost:8000/jobs/<job_id>
# -> status/progress, updates as the worker processes it

curl http://localhost:8000/jobs/<job_id>/result -o output.xlsx
curl http://localhost:8000/jobs/<job_id>/scopus-csv -o scopus.csv
```

## Deploying on Railway

Railway suits this stack specifically because a FastAPI + Celery + Redis +
Postgres setup is four moving pieces, and Railway's one-click Redis/Postgres
plugins plus per-service env vars make wiring them together fast.

1. Push this repo to GitHub (already done for Phase 0 - same repo works,
   the `backend/` folder just adds to it).
2. On railway.app, **New Project -> Deploy from GitHub repo**, pick this repo.
3. Add plugins: **+ New -> Database -> PostgreSQL**, and **+ New -> Database
   -> Redis**. Railway auto-injects `DATABASE_URL` and `REDIS_URL` into
   every service in the same project - you don't need to copy/paste them.
4. Add a second service for the worker: **+ New -> GitHub Repo** (same
   repo again), then override its start command to
   `celery -A backend.celery_app worker --loglevel=info` (Settings ->
   Deploy -> Custom Start Command). The first service (the web one) uses
   the `Procfile`'s `web:` line automatically, or set its start command to
   `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` explicitly.
5. On both services, add the remaining env vars from `backend/.env.example`
   (`BIBLIO_CONTACT_EMAIL`, `STORAGE_BACKEND=s3`, `S3_BUCKET`,
   `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`) - both the
   web and worker services need identical storage/DB config since they're
   reading/writing the same jobs.
6. For object storage, the fastest option is Cloudflare R2 (S3-compatible,
   free tier, no egress fees): create a bucket, create an API token, plug
   the account-specific S3 endpoint URL + access keys into the env vars
   above. Without this step, `STORAGE_BACKEND=local` will "work" but files
   won't survive a redeploy - same ephemeral-disk caveat Phase 0 had.
7. Deploy. Railway builds both services from the same repo; the worker
   service will sit idle until the web service's `/jobs` endpoint queues a
   task, then pick it up via Redis.

## What's NOT in Phase 1 yet

User accounts/auth, per-institute workspaces, and billing are Phase 2
per the original 3-phase plan - Phase 1's job IDs are unauthenticated
bearer-style identifiers (anyone with a job_id can view/download/requeue
it), which is fine for internal/team use but not for a public multi-tenant
product. Also not yet built: a frontend that actually calls this API
(Phase 0's Streamlit app still runs the pipeline in-process; pointing it at
this API instead - so it becomes a thin client - is the natural next step
once this backend is deployed and confirmed working).
