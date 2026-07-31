"""Celery worker package."""

from app.workers.tasks import process_stage, enqueue_pipeline

# Local development mock: if no Redis available, run pipeline directly
# In production, this file is just for package init
