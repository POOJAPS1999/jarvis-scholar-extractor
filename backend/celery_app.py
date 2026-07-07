"""
celery_app.py
=============
The Celery application object, kept in its own module (rather than inside
tasks.py) so both the worker process (`celery -A backend.celery_app worker`)
and the FastAPI process (which only needs to call `.delay()`) can import it
without also importing task bodies they don't need.

REDIS_URL doubles as both the message broker (queueing "run this job") and
the result backend (Celery bookkeeping) - Job progress itself lives in
Postgres (see models.py), not in Celery's result backend, since the API
needs to read progress via simple SQL regardless of which worker or Celery
task-id handled it.
"""
import os
from celery import Celery

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery("jarvis_scholar", broker=REDIS_URL, backend=REDIS_URL)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # A single extraction job can legitimately run for a long time (many
    # records x 3 sources x rate limits) - don't let Celery's default
    # visibility timeout silently redeliver an in-progress task to a
    # second worker and double-run it.
    broker_transport_options={"visibility_timeout": 6 * 60 * 60},
    task_track_started=True,
)

# Import task bodies so `celery -A backend.celery_app worker` discovers them
# without needing a separate --include/-A backend.tasks flag.
from . import tasks  # noqa: E402,F401
