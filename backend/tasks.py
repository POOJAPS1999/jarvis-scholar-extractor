"""
tasks.py
========
The Celery task that actually runs an extraction job in the background.

This is almost entirely plumbing around bibliometric_pipeline.pipeline's
run_pipeline() - the matching/fetching logic itself is untouched (same as
Phase 0's Streamlit app, same as the CLI). What this module adds:

  - Job status bookkeeping in Postgres (queued -> running -> completed/failed)
  - Bridging object storage <-> the local temp file paths run_pipeline()
    expects (it reads/writes checkpoint + output as file paths, not bytes)
  - Genuine crash-resume: whenever run_pipeline() saves a checkpoint
    locally (every config.CHECKPOINT_EVERY records), this uploads that
    checkpoint to storage immediately - so if the worker process dies or
    is restarted mid-job, re-queuing the same job_id resumes from the last
    uploaded checkpoint instead of starting over. That's the Phase 1
    equivalent of Phase 0's "close the tab, re-upload the same file, it
    resumes" - except automatic, not dependent on the user re-uploading.
"""
import os
import sys
import tempfile
import traceback
from datetime import datetime, timezone

# Make the existing pipeline package importable regardless of cwd - this
# file lives in backend/, the pipeline package is a sibling directory.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bibliometric_pipeline.pipeline import run_pipeline  # noqa: E402
from .celery_app import celery_app  # noqa: E402
from .models import get_session_direct, Job  # noqa: E402
from . import storage  # noqa: E402


def _load_optional_column_groups(job_id):
    """Read the per-job config file (jobs/{id}/config.json) written by the
    API when the job was created. Returns the list of optional column groups
    (e.g. ["icmr_flags", "icmr_institute"] for ICMR mode), or None if there
    is no config file — in which case run_pipeline falls back to the
    process-wide env default, preserving the old behaviour for any job
    created before this feature existed."""
    import json
    key = f"jobs/{job_id}/config.json"
    try:
        if not storage.exists(key):
            return None
        cfg = json.loads(storage.load(key).decode("utf-8"))
    except Exception:
        return None
    groups = cfg.get("optional_column_groups")
    return groups if isinstance(groups, list) else None


def _update_job(job_id, **fields):
    with get_session_direct() as session:
        job = session.get(Job, job_id)
        if not job:
            return
        for k, v in fields.items():
            setattr(job, k, v)
        job.updated_at = datetime.now(timezone.utc)
        session.add(job)
        session.commit()


@celery_app.task(bind=True, name="jarvis_scholar.run_extraction_job")
def run_extraction_job(self, job_id: str):
    with get_session_direct() as session:
        job = session.get(Job, job_id)
        if not job:
            return {"error": f"job {job_id} not found"}
        input_key = job.input_key
        checkpoint_key = job.checkpoint_key
        output_key = job.output_key

    optional_column_groups = _load_optional_column_groups(job_id)

    _update_job(job_id, status="running", progress_message="Starting...")

    with tempfile.TemporaryDirectory() as tmpdir:
        local_checkpoint = os.path.join(tmpdir, "checkpoint.csv")
        local_output = os.path.join(tmpdir, "output.xlsx")

        # Resume support: if a checkpoint already exists in storage from a
        # prior (possibly crashed/killed) attempt at this same job_id,
        # pull it down first so run_pipeline's load_checkpoint() picks up
        # where it left off instead of starting from zero.
        if storage.exists(checkpoint_key):
            with open(local_checkpoint, "wb") as f:
                f.write(storage.load(checkpoint_key))

        try:
            df_in = storage.load_dataframe_excel(input_key)
        except Exception as e:
            _update_job(job_id, status="failed", error_message=f"Could not read input file: {e}")
            return {"error": str(e)}

        def on_progress(done, total, message):
            fields = {"done_rows": done, "total_rows": total, "progress_message": message}
            _update_job(job_id, **fields)
            # Whenever the pipeline just wrote a local checkpoint, mirror it
            # to durable storage immediately - this is what makes a
            # worker crash mid-job recoverable by re-queuing the same job_id.
            if "checkpoint saved" in message and os.path.exists(local_checkpoint):
                with open(local_checkpoint, "rb") as f:
                    storage.save(checkpoint_key, f.read())

        try:
            final_df, summary = run_pipeline(
                df_in,
                checkpoint_path=local_checkpoint,
                output_path=local_output,
                progress_callback=on_progress,
                optional_column_groups=optional_column_groups,
            )
        except Exception as e:
            tb = traceback.format_exc()
            _update_job(job_id, status="failed", error_message=f"{e}\n{tb}"[:4000])
            # Still push whatever checkpoint progress exists, so a re-queue
            # of this job_id doesn't lose completed records.
            if os.path.exists(local_checkpoint):
                with open(local_checkpoint, "rb") as f:
                    storage.save(checkpoint_key, f.read())
            return {"error": str(e)}

        # Final checkpoint + output both go to durable storage.
        with open(local_checkpoint, "rb") as f:
            storage.save(checkpoint_key, f.read())
        with open(local_output, "rb") as f:
            storage.save(output_key, f.read())

    _update_job(
        job_id,
        status="completed",
        done_rows=summary["done"],
        total_rows=summary["total"],
        progress_message="Done.",
    )
    return {
        "status": "completed",
        "done": summary["done"],
        "total": summary["total"],
        "status_counts": summary["status_counts"],
    }
