"""Pipeline stage execution — reusable both inline (sync) and via Celery.

Extracts the pure execution logic from ``app.workers.tasks`` so that
the same pipeline stages can be driven synchronously during local
development without Redis / Celery.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import hashlib
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

import structlog
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import (
    Meeting,
    ProcessingJob,
    QdrantDocument,
    TranscriptChunk,
    TranscriptChunkClean,
    TranscriptRaw,
    TranscriptSegmentRaw,
)
from app.models.enums import JobStage, JobStatus, MeetingStatus
from app.services.chunker import SourceSegment, chunk_segments
from app.services.openrouter import embed_texts
from app.services.transcription import transcribe_recording
from qdrant_client import models as qmodels
from app.services.vector_store import deactivate_meeting_points, upsert_points

logger = structlog.get_logger()


# Reusable thread pool for running async code from sync contexts
# (avoids creating/destroying a thread on every call)
_ASYNC_RUNNER = concurrent.futures.ThreadPoolExecutor(max_workers=1)


def _run_async(coro):
    """
    Run a coroutine from a synchronous context, even when an event loop
    is already running (e.g. inside an async FastAPI endpoint).

    Falls back to ``asyncio.run()`` when there is no running loop;
    otherwise dispatches to a thread with its own loop.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already inside an event loop — run in a dedicated thread with its own loop
    return _ASYNC_RUNNER.submit(asyncio.run, coro).result()

STAGE_VERSION: dict[JobStage, Callable[..., str]] = {
    JobStage.TRANSCRIBE: lambda: get_settings().stt_model,
    JobStage.CLEAN: lambda: get_settings().cleaning_version,
    JobStage.CHUNK: lambda: get_settings().chunking_version,
    JobStage.EMBED_INDEX: lambda: get_settings().openrouter_embedding_model,
}

NEXT_STAGE: dict[JobStage, JobStage] = {
    JobStage.TRANSCRIBE: JobStage.CLEAN,
    JobStage.CLEAN: JobStage.CHUNK,
    JobStage.CHUNK: JobStage.EMBED_INDEX,
}


# ── Idempotency helpers ──


def idempotency_key(meeting_id: str, stage: JobStage, run_id: str | None) -> str:
    version = STAGE_VERSION[stage]()
    return f"{meeting_id}:{stage.value}:{version}:{run_id or 'default'}"


def create_or_get_job(
    db: Session,
    *,
    meeting_id: str,
    tenant_id: str,
    stage: JobStage,
    correlation_id: str,
    task_id: str | None = None,
    run_id: str | None = None,
) -> tuple[ProcessingJob, bool]:
    """Create a ProcessingJob row, or return existing if already completed."""
    from sqlalchemy.exc import IntegrityError

    key = idempotency_key(meeting_id, stage, run_id)
    existing = db.scalar(
        select(ProcessingJob).where(
            ProcessingJob.tenant_id == tenant_id,
            ProcessingJob.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing, False
    job = ProcessingJob(
        tenant_id=tenant_id,
        meeting_id=meeting_id,
        stage=stage,
        status=JobStatus.PENDING,
        idempotency_key=key,
        correlation_id=correlation_id,
        celery_task_id=task_id,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(ProcessingJob).where(
                ProcessingJob.tenant_id == tenant_id,
                ProcessingJob.idempotency_key == key,
            )
        )
        if existing is None:
            raise
        return existing, False
    return job, True


def tenant_meeting(db: Session, meeting_id: str, tenant_id: str) -> Meeting:
    meeting = db.scalar(
        select(Meeting).where(Meeting.id == meeting_id, Meeting.tenant_id == tenant_id)
    )
    if meeting is None:
        raise RuntimeError("Tenant-scoped meeting not found")
    return meeting


# ── Stage execution functions ──


def run_clean(db: Session, meeting: Meeting) -> dict[str, Any]:
    """Stage: mark as cleaned (actual cleaning happens inline in chunk stage)."""
    settings = get_settings()
    raw = db.scalar(
        select(TranscriptRaw).where(
            TranscriptRaw.meeting_id == meeting.id,
            TranscriptRaw.tenant_id == meeting.tenant_id,
            TranscriptRaw.stt_model == settings.stt_model,
        )
    )
    if raw is None:
        raise RuntimeError("Raw transcript is not available")
    segment_count = db.query(TranscriptSegmentRaw).filter(
        TranscriptSegmentRaw.transcript_raw_id == raw.id,
        TranscriptSegmentRaw.tenant_id == meeting.tenant_id,
    ).count()
    if segment_count == 0:
        raise RuntimeError("Raw transcript contains no segments")
    meeting.status = MeetingStatus.CLEANED
    return {"cleaning_version": settings.cleaning_version, "segment_count": segment_count}


def run_chunk(db: Session, meeting: Meeting) -> dict[str, Any]:
    """Stage: chunk the cleaned transcript segments."""
    settings = get_settings()
    raw = db.scalar(
        select(TranscriptRaw).where(
            TranscriptRaw.meeting_id == meeting.id,
            TranscriptRaw.tenant_id == meeting.tenant_id,
            TranscriptRaw.stt_model == settings.stt_model,
        )
    )
    if raw is None:
        raise RuntimeError("Raw transcript is not available")

    # Check if chunks already exist for this version
    existing = db.scalar(
        select(TranscriptChunk)
        .join(TranscriptChunkClean, TranscriptChunkClean.chunk_id == TranscriptChunk.id)
        .where(
            TranscriptChunk.meeting_id == meeting.id,
            TranscriptChunk.tenant_id == meeting.tenant_id,
            TranscriptChunk.chunk_strategy_version == settings.chunking_version,
            TranscriptChunkClean.cleaning_version == settings.cleaning_version,
            TranscriptChunk.is_active.is_(True),
        )
        .limit(1)
    )
    if existing is not None:
        count = db.query(TranscriptChunk).filter(
            TranscriptChunk.meeting_id == meeting.id,
            TranscriptChunk.chunk_strategy_version == settings.chunking_version,
            TranscriptChunk.is_active.is_(True),
        ).count()
        meeting.status = MeetingStatus.CHUNKED
        return {"chunk_count": count, "reused": True}

    raw_segments = db.scalars(
        select(TranscriptSegmentRaw)
        .where(
            TranscriptSegmentRaw.transcript_raw_id == raw.id,
            TranscriptSegmentRaw.tenant_id == meeting.tenant_id,
        )
        .order_by(TranscriptSegmentRaw.ordinal)
    ).all()

    drafts = chunk_segments(
        [
            SourceSegment(
                id=item.id,
                start_ms=item.start_ms,
                end_ms=item.end_ms,
                speaker=item.speaker,
                text=item.text,
            )
            for item in raw_segments
        ],
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_ratio=settings.chunk_overlap_ratio,
    )

    # Deactivate old chunks
    db.execute(
        update(TranscriptChunk)
        .where(
            TranscriptChunk.meeting_id == meeting.id,
            TranscriptChunk.tenant_id == meeting.tenant_id,
            TranscriptChunk.is_active.is_(True),
        )
        .values(is_active=False)
    )

    now = datetime.now(UTC)
    for ordinal, draft in enumerate(drafts):
        chunk = TranscriptChunk(
            tenant_id=meeting.tenant_id,
            meeting_id=meeting.id,
            transcript_raw_id=raw.id,
            ordinal=ordinal,
            start_ms=draft.start_ms,
            end_ms=draft.end_ms,
            speaker_set=draft.speakers,
            source_segment_ids=draft.source_segment_ids,
            source_text=draft.source_text,
            chunk_strategy_version=settings.chunking_version,
            is_active=True,
            created_at=now,
        )
        db.add(chunk)
        db.flush()

        metadata_parts = [
            f"Meeting: {meeting.title}",
            f"Date: {meeting.meeting_date.isoformat()}" if meeting.meeting_date else None,
            f"Project: {meeting.project}" if meeting.project else None,
            f"Department: {meeting.department}" if meeting.department else None,
            f"Speakers: {', '.join(draft.speakers)}",
        ]
        metadata = " | ".join(part for part in metadata_parts if part)
        text_for_embedding = f"{metadata}\n\n{draft.cleaned_text}"

        db.add(
            TranscriptChunkClean(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                chunk_id=chunk.id,
                cleaning_version=settings.cleaning_version,
                cleaned_text=draft.cleaned_text,
                text_for_embedding=text_for_embedding,
                content_hash=hashlib.sha256(text_for_embedding.encode()).hexdigest(),
                created_at=now,
            )
        )

    meeting.status = MeetingStatus.CHUNKED
    return {"chunk_count": len(drafts), "reused": False}


def run_embed_index(db: Session, meeting: Meeting) -> dict[str, Any]:
    """Stage: embed chunks and index into Qdrant."""
    settings = get_settings()

    rows = db.execute(
        select(TranscriptChunk, TranscriptChunkClean)
        .join(TranscriptChunkClean, TranscriptChunkClean.chunk_id == TranscriptChunk.id)
        .where(
            TranscriptChunk.meeting_id == meeting.id,
            TranscriptChunk.tenant_id == meeting.tenant_id,
            TranscriptChunk.is_active.is_(True),
            TranscriptChunkClean.cleaning_version == settings.cleaning_version,
        )
        .order_by(TranscriptChunk.ordinal)
    ).all()

    if not rows:
        raise RuntimeError("No active clean chunks are available")

    # Deactivate old Qdrant points + MySQL records
    try:
        _run_async(deactivate_meeting_points(meeting.tenant_id, meeting.id))
    except Exception as e:
        logger.warning("qdrant_deactivate_failed", error=str(e))

    db.execute(
        update(QdrantDocument)
        .where(
            QdrantDocument.meeting_id == meeting.id,
            QdrantDocument.tenant_id == meeting.tenant_id,
            QdrantDocument.is_active.is_(True),
        )
        .values(is_active=False)
    )

    indexed = 0
    for start in range(0, len(rows), 32):
        batch = rows[start : start + 32]
        vectors = _run_async(embed_texts([clean.text_for_embedding for _, clean in batch]))

        points = []
        pending_documents: list[QdrantDocument] = []
        for (chunk, clean), vector in zip(batch, vectors, strict=True):
            document = db.scalar(
                select(QdrantDocument).where(
                    QdrantDocument.clean_chunk_id == clean.id,
                    QdrantDocument.embedding_model == settings.openrouter_embedding_model,
                )
            )
            if document is None:
                document = QdrantDocument(
                    tenant_id=meeting.tenant_id,
                    meeting_id=meeting.id,
                    chunk_id=chunk.id,
                    clean_chunk_id=clean.id,
                    qdrant_point_id=str(uuid.uuid4()),
                    collection_name=settings.qdrant_collection,
                    embedding_model=settings.openrouter_embedding_model,
                    embedding_dimension=settings.embedding_dimension,
                    content_hash=clean.content_hash,
                    is_active=True,
                )
                db.add(document)
            else:
                document.content_hash = clean.content_hash
                document.is_active = True

            pending_documents.append(document)

            points.append(
                qmodels.PointStruct(
                    id=document.qdrant_point_id,
                    vector=vector,
                    payload={
                        "tenant_id": meeting.tenant_id,
                        "meeting_id": meeting.id,
                        "chunk_id": chunk.id,
                        "clean_chunk_id": clean.id,
                        "meeting_title": meeting.title,
                        "meeting_date": (
                            f"{meeting.meeting_date.isoformat()}T00:00:00Z"
                            if meeting.meeting_date
                            else None
                        ),
                        "start_ms": chunk.start_ms,
                        "end_ms": chunk.end_ms,
                        "speaker_set": chunk.speaker_set,
                        "project": meeting.project,
                        "department": meeting.department,
                        "chunk_strategy_version": chunk.chunk_strategy_version,
                        "cleaning_version": clean.cleaning_version,
                        "embedding_model": settings.openrouter_embedding_model,
                        "is_active": True,
                    },
                )
            )

        # Upsert to Qdrant — graceful fallback if unavailable
        try:
            _run_async(upsert_points(points))
        except Exception as e:
            logger.warning("qdrant_upsert_failed", error=str(e))

        db.flush()
        indexed += len(pending_documents)

    meeting.status = MeetingStatus.READY
    return {"indexed_count": indexed, "embedding_model": settings.openrouter_embedding_model}


def execute_stage(db: Session, stage: JobStage, meeting: Meeting) -> dict[str, Any]:
    """Execute a single pipeline stage by name."""
    if stage == JobStage.TRANSCRIBE:
        return transcribe_recording(db, meeting)
    if stage == JobStage.CLEAN:
        return run_clean(db, meeting)
    if stage == JobStage.CHUNK:
        return run_chunk(db, meeting)
    if stage == JobStage.EMBED_INDEX:
        return run_embed_index(db, meeting)
    raise RuntimeError(f"Unsupported stage: {stage}")


def run_pipeline_sync(
    db: Session,
    *,
    meeting_id: str,
    tenant_id: str,
    correlation_id: str,
    from_stage: JobStage,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run pipeline stages synchronously from a given starting stage.

    This is used **instead of Celery** during local development.
    Each stage runs inline, one after another, with full job tracking.
    """
    last_result: dict[str, Any] = {"status": "no_stages_executed"}
    stages = [from_stage]
    current = from_stage
    while current in NEXT_STAGE:
        stages.append(NEXT_STAGE[current])
        current = NEXT_STAGE[current]

    for stage in stages:
        job, created = create_or_get_job(
            db,
            meeting_id=meeting_id,
            tenant_id=tenant_id,
            stage=stage,
            correlation_id=correlation_id,
            run_id=run_id,
        )
        if not created and job.status == JobStatus.SUCCEEDED:
            last_result = {"status": "already_completed", "job_id": job.id, "stage": stage.value}
            continue

        meeting = tenant_meeting(db, meeting_id, tenant_id)

        status_by_stage = {
            JobStage.TRANSCRIBE: MeetingStatus.TRANSCRIBING,
            JobStage.CLEAN: MeetingStatus.CLEANING,
            JobStage.CHUNK: MeetingStatus.CHUNKING,
            JobStage.EMBED_INDEX: MeetingStatus.EMBEDDING,
        }
        meeting.status = status_by_stage[stage]
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        db.commit()

        started = time.perf_counter()
        logger.info(
            "stage_started",
            meeting_id=meeting_id,
            tenant_id=tenant_id,
            stage=stage.value,
            job_id=job.id,
            correlation_id=correlation_id,
        )

        try:
            metadata = execute_stage(db, stage, meeting)
            job.status = JobStatus.SUCCEEDED
            job.finished_at = datetime.now(UTC)
            job.latency_ms = round((time.perf_counter() - started) * 1000)
            job.metadata_json = metadata
            job.failure_reason = None
            db.commit()
            last_result = {"status": "completed", "job_id": job.id, "metadata": metadata}
        except Exception as exc:
            db.rollback()
            refreshed_job = db.get(ProcessingJob, job.id)
            if refreshed_job is not None:
                refreshed_job.retry_count = (refreshed_job.retry_count or 0) + 1
                refreshed_job.failure_reason = str(exc)[:4000]
                refreshed_job.finished_at = datetime.now(UTC)
                refreshed_job.latency_ms = round((time.perf_counter() - started) * 1000)
                refreshed_job.status = JobStatus.FAILED
                meeting = tenant_meeting(db, meeting_id, tenant_id)
                meeting.status = MeetingStatus.FAILED
                meeting.failure_reason = f"{stage.value}: {str(exc)[:2000]}"
                db.commit()
                logger.exception("stage_failed", job_id=refreshed_job.id, stage=stage.value)
            else:
                logger.exception("stage_failed_job_not_found", stage=stage.value)
            last_result = {"status": "failed", "job_id": job.id, "error": str(exc)}
            break

    return last_result
