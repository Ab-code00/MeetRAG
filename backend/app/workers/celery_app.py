from celery import Celery

from app.core.config import get_settings
from app.core.logging import configure_logging

settings = get_settings()
configure_logging()

celery_app = Celery(
    "meetai",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)
celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    result_expires=86400,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_routes={"app.workers.tasks.process_stage": {"queue": "pipeline"}},
)

