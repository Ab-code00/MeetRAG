import time
import uuid
from datetime import UTC, datetime
from typing import Any

import structlog
from celery import Task

from app.db.sync_session import SyncSessionLocal
from app.models import ProcessingJob
from app.models.enums import JobStage, JobStatus, MeetingStatus
from app.services.pipeline import (
    NEXT_STAGE,
    create_or_get_job,
    execute_stage,
    tenant_meeting,
)
from app.workers.celery_app import celery_app

logger = structlog.get_logger()


def enqueue_pipeline(
    meeting_id: str,
    tenant_id: str,
    correlation_id: str,
    from_stage: JobStage,
    *,
    force: bool = False,
) -> str:
    """Enqueue a pipeline stage via Celery, or run inline if Celery/Redis is unavailable."""
    from app.core.config import get_settings

    settings = get_settings()

    # In development mode without Celery, run synchronously
    if settings.app_env == "development":
        result = _run_inline(
            meeting_id=meeting_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            from_stage=from_stage,
            force=force,
        )
        return str(result.get("task_id", "inline-execution"))

    # Production: use Celery
    run_id = str(uuid.uuid4()) if force else None
    celery_result = process_stage.apply_async(
        kwargs={
            "meeting_id": meeting_id,
            "tenant_id": tenant_id,
            "stage_value": from_stage.value,
            "correlation_id": correlation_id,
            "run_id": run_id,
        },
        queue="pipeline",
    )
    return str(celery_result.id)


def _run_inline(
    meeting_id: str,
    tenant_id: str,
    correlation_id: str,
    from_stage: JobStage,
    *,
    force: bool = False,
) -> dict[str, str]:
    """Run pipeline stages synchronously (no Celery)."""
    from app.services.pipeline import run_pipeline_sync

    with SyncSessionLocal() as db:
        pipeline_run_id = str(uuid.uuid4()) if force else None
        result = run_pipeline_sync(
            db,
            meeting_id=meeting_id,
            tenant_id=tenant_id,
            correlation_id=correlation_id,
            from_stage=from_stage,
            run_id=pipeline_run_id,
        )
        return {"task_id": "inline", "status": result.get("status", "unknown")}


@celery_app.task(bind=True, max_retries=5, name="app.workers.tasks.process_stage")
def process_stage(
    self: Task,
    *,
    meeting_id: str,
    tenant_id: str,
    stage_value: str,
    correlation_id: str,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Celery task that executes a single pipeline stage and chains to the next."""
    from typing import Any

    stage = JobStage(stage_value)
    with SyncSessionLocal() as db:
        job, created = create_or_get_job(
            db,
            meeting_id=meeting_id,
            tenant_id=tenant_id,
            stage=stage,
            correlation_id=correlation_id,
            task_id=self.request.id,
            run_id=run_id,
        )
        if not created and job.status == JobStatus.SUCCEEDED:
            return {"status": "already_completed", "job_id": job.id}

        meeting = tenant_meeting(db, meeting_id, tenant_id)
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        job.retry_count = self.request.retries

        status_by_stage = {
            JobStage.TRANSCRIBE: MeetingStatus.TRANSCRIBING,
            JobStage.CLEAN: MeetingStatus.CLEANING,
            JobStage.CHUNK: MeetingStatus.CHUNKING,
            JobStage.EMBED_INDEX: MeetingStatus.EMBEDDING,
        }
        meeting.status = status_by_stage[stage]
        db.commit()

        started = time.perf_counter()
        logger.info(
            "stage_started",
            meeting_id=meeting_id,
            tenant_id=tenant_id,
            stage=stage.value,
            job_id=job.id,
            correlation_id=correlation_id,
            retry_count=self.request.retries,
        )

        try:
            metadata = execute_stage(db, stage, meeting)
            job.status = JobStatus.SUCCEEDED
            job.finished_at = datetime.now(UTC)
            job.latency_ms = round((time.perf_counter() - started) * 1000)
            job.metadata_json = metadata
            job.failure_reason = None
            db.commit()
        except Exception as exc:
            db.rollback()
            refreshed_job = db.get(ProcessingJob, job.id)
            if refreshed_job is None:
                raise RuntimeError("Processing job disappeared during rollback") from exc
            job = refreshed_job
            meeting = tenant_meeting(db, meeting_id, tenant_id)
            job.retry_count = self.request.retries + 1
            job.failure_reason = str(exc)[:4000]
            job.finished_at = datetime.now(UTC)
            job.latency_ms = round((time.perf_counter() - started) * 1000)
            if self.request.retries >= self.max_retries:
                job.status = JobStatus.DEAD_LETTERED
                meeting.status = MeetingStatus.FAILED
                meeting.failure_reason = f"{stage.value}: {str(exc)[:2000]}"
                db.commit()
                logger.exception("stage_dead_lettered", job_id=job.id, stage=stage.value)
                raise
            job.status = JobStatus.RETRYING
            db.commit()
            logger.exception("stage_retrying", job_id=job.id, stage=stage.value)
            raise self.retry(
                exc=exc, countdown=min(30 * (2**self.request.retries), 900)
            ) from exc

    next_stage = NEXT_STAGE.get(stage)
    if next_stage:
        enqueue_pipeline(meeting_id, tenant_id, correlation_id, next_stage, force=run_id is not None)
    return {"status": "completed", "job_id": job.id, "metadata": metadata}
