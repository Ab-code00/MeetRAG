from typing import Annotated, cast

from fastapi import APIRouter, File, Header, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.deps import Auth, DbSession, correlation_id
from app.core.config import get_settings
from app.models import (
    Meeting,
    ProcessingJob,
    Recording,
    TranscriptChunk,
    TranscriptChunkClean,
    TranscriptRaw,
    TranscriptSegmentRaw,
)
from app.models.enums import JobStage, MeetingStatus, RecordingStatus, UserRole
from app.schemas.meetings import (
    CleanChunkResponse,
    JobResponse,
    MeetingCreateRequest,
    MeetingDetailResponse,
    MeetingListResponse,
    ReprocessRequest,
    TranscriptResponse,
    UploadCompleteRequest,
    UploadTarget,
)
from app.services.audit import add_audit_log
from app.services.storage import (
    create_upload_url,
    get_local_path,
    head_recording,
    recording_object_key,
    save_file_locally,
)

router = APIRouter(prefix="/meetings", tags=["meetings"])


async def _tenant_meeting(db: DbSession, meeting_id: str, tenant_id: str) -> Meeting:
    meeting = await db.scalar(
        select(Meeting)
        .options(selectinload(Meeting.recordings))
        .where(Meeting.id == meeting_id, Meeting.tenant_id == tenant_id, Meeting.deleted_at.is_(None))
    )
    if meeting is None:
        raise HTTPException(status_code=404, detail="Meeting not found")
    return meeting


@router.post("", response_model=UploadTarget, status_code=status.HTTP_201_CREATED)
async def create_meeting(
    payload: MeetingCreateRequest,
    request: Request,
    auth: Auth,
    db: DbSession,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> UploadTarget:
    if idempotency_key:
        existing = await db.scalar(
            select(Meeting)
            .where(
                Meeting.tenant_id == auth.tenant_id,
                Meeting.external_meeting_id == f"upload:{idempotency_key[:200]}",
            )
            .options(selectinload(Meeting.recordings))
        )
        if existing and existing.recordings:
            recording = existing.recordings[0]
            return UploadTarget(
                meeting_id=existing.id,
                recording_id=recording.id,
                upload_url=create_upload_url(
                    object_key=recording.object_key, content_type=recording.content_type
                ),
                upload_headers={
                    "Content-Type": recording.content_type,
                    "x-amz-server-side-encryption": "AES256",
                },
            )
    meeting = Meeting(
        tenant_id=auth.tenant_id,
        created_by_user_id=auth.user_id,
        title=payload.title,
        meeting_date=payload.meeting_date,
        project=payload.project,
        department=payload.department,
        source=payload.source,
        external_meeting_id=(
            f"upload:{idempotency_key[:200]}" if idempotency_key else payload.external_meeting_id
        ),
        status=MeetingStatus.PENDING,
    )
    db.add(meeting)
    await db.flush()
    recording = Recording(
        tenant_id=auth.tenant_id,
        meeting_id=meeting.id,
        bucket=get_settings().aws_s3_bucket,
        object_key="pending",
        original_filename=payload.filename,
        content_type=payload.content_type,
        status=RecordingStatus.PENDING_UPLOAD,
    )
    db.add(recording)
    await db.flush()
    recording.object_key = recording_object_key(
        auth.tenant_id, meeting.id, recording.id, payload.filename
    )
    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="MEETING_CREATE",
        resource_type="meeting",
        resource_id=meeting.id,
        correlation_id=correlation_id(request),
        details={"source": payload.source},
    )
    await db.commit()

    # Try S3 presigned URL; fall back to API-based direct upload when S3 is unavailable
    upload_url = ""
    upload_headers: dict[str, str] = {}
    try:
        upload_url = create_upload_url(
            object_key=recording.object_key, content_type=recording.content_type
        )
        upload_headers = {
            "Content-Type": recording.content_type,
            "x-amz-server-side-encryption": "AES256",
        }
    except RuntimeError:
        # S3 not configured — frontend should use POST /meetings/{id}/upload instead
        upload_url = ""

    return UploadTarget(
        meeting_id=meeting.id,
        recording_id=recording.id,
        upload_url=upload_url,
        upload_headers=upload_headers,
        expires_in=0 if not upload_url else 900,
    )


@router.post("/{meeting_id}/recordings/{recording_id}/complete", response_model=MeetingDetailResponse)
async def complete_upload(
    meeting_id: str,
    recording_id: str,
    payload: UploadCompleteRequest,
    request: Request,
    auth: Auth,
    db: DbSession,
) -> MeetingDetailResponse:
    meeting = await _tenant_meeting(db, meeting_id, auth.tenant_id)
    recording = next((item for item in meeting.recordings if item.id == recording_id), None)
    if recording is None:
        raise HTTPException(status_code=404, detail="Recording not found")
    if recording.status in {RecordingStatus.VERIFIED, RecordingStatus.UPLOADED}:
        return cast(MeetingDetailResponse, meeting)
    try:
        metadata = head_recording(recording.object_key)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="Uploaded object could not be verified") from exc
    actual_size = int(metadata.get("ContentLength", 0))
    if actual_size <= 0 or (payload.size_bytes and actual_size != payload.size_bytes):
        raise HTTPException(status_code=409, detail="Uploaded object size does not match")
    recording.size_bytes = actual_size
    recording.checksum_sha256 = payload.checksum_sha256
    recording.status = RecordingStatus.VERIFIED
    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="RECORDING_UPLOAD_COMPLETE",
        resource_type="recording",
        resource_id=recording.id,
        correlation_id=correlation_id(request),
        details={"size_bytes": actual_size},
    )
    await db.commit()
    from app.workers.tasks import enqueue_pipeline

    enqueue_pipeline(meeting.id, auth.tenant_id, correlation_id(request), JobStage.TRANSCRIBE)
    return cast(MeetingDetailResponse, meeting)


@router.post("/{meeting_id}/upload", status_code=status.HTTP_200_OK)
async def upload_recording_direct(
    meeting_id: str,
    request: Request,
    auth: Auth,
    db: DbSession,
    file: UploadFile = File(...),
) -> MeetingDetailResponse:
    """
    Direct file upload (multipart) — bypasses S3 presigned URLs.

    Used during local development when S3 / LocalStack is not available.
    Saves the file to the local filesystem and starts the pipeline.
    """
    meeting = await _tenant_meeting(db, meeting_id, auth.tenant_id)

    if not meeting.recordings:
        raise HTTPException(status_code=404, detail="No recordings found for this meeting")

    recording = meeting.recordings[0]
    content = await file.read()

    if not content:
        raise HTTPException(status_code=400, detail="Empty file uploaded")

    if recording.object_key == "pending":
        recording.object_key = recording_object_key(
            auth.tenant_id, meeting.id, recording.id, file.filename or "recording"
        )

    save_file_locally(recording.object_key, content)
    recording.size_bytes = len(content)
    recording.status = RecordingStatus.VERIFIED

    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="RECORDING_UPLOAD_DIRECT",
        resource_type="recording",
        resource_id=recording.id,
        correlation_id=correlation_id(request),
        details={"size_bytes": len(content), "filename": file.filename},
    )
    await db.commit()

    from app.workers.tasks import enqueue_pipeline

    enqueue_pipeline(meeting.id, auth.tenant_id, correlation_id(request), JobStage.TRANSCRIBE)
    return cast(MeetingDetailResponse, meeting)


@router.get("", response_model=MeetingListResponse)
async def list_meetings(
    auth: Auth,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[MeetingStatus | None, Query(alias="status")] = None,
) -> MeetingListResponse:
    filters = [Meeting.tenant_id == auth.tenant_id, Meeting.deleted_at.is_(None)]
    if status_filter:
        filters.append(Meeting.status == status_filter)
    total = await db.scalar(select(func.count(Meeting.id)).where(*filters))
    meetings = list(
        (
            await db.scalars(
                select(Meeting)
                .where(*filters)
                .order_by(Meeting.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        ).all()
    )
    return MeetingListResponse(items=meetings, total=total or 0, limit=limit, offset=offset)


@router.get("/{meeting_id}", response_model=MeetingDetailResponse)
async def get_meeting(meeting_id: str, auth: Auth, db: DbSession) -> MeetingDetailResponse:
    return cast(MeetingDetailResponse, await _tenant_meeting(db, meeting_id, auth.tenant_id))


@router.get("/{meeting_id}/transcript", response_model=TranscriptResponse)
async def get_transcript(meeting_id: str, request: Request, auth: Auth, db: DbSession) -> TranscriptResponse:
    await _tenant_meeting(db, meeting_id, auth.tenant_id)
    raw = await db.scalar(
        select(TranscriptRaw).where(
            TranscriptRaw.meeting_id == meeting_id, TranscriptRaw.tenant_id == auth.tenant_id
        )
    )
    segments = []
    if raw:
        segments = list(
            (
                await db.scalars(
                    select(TranscriptSegmentRaw)
                    .where(
                        TranscriptSegmentRaw.transcript_raw_id == raw.id,
                        TranscriptSegmentRaw.tenant_id == auth.tenant_id,
                    )
                    .order_by(TranscriptSegmentRaw.ordinal)
                )
            ).all()
        )
    rows = (
        await db.execute(
            select(TranscriptChunk, TranscriptChunkClean)
            .join(TranscriptChunkClean, TranscriptChunkClean.chunk_id == TranscriptChunk.id)
            .where(
                TranscriptChunk.meeting_id == meeting_id,
                TranscriptChunk.tenant_id == auth.tenant_id,
                TranscriptChunk.is_active.is_(True),
            )
            .order_by(TranscriptChunk.ordinal)
        )
    ).all()
    clean_chunks = [
        CleanChunkResponse(
            chunk_id=chunk.id,
            clean_chunk_id=clean.id,
            ordinal=chunk.ordinal,
            start_ms=chunk.start_ms,
            end_ms=chunk.end_ms,
            speaker_set=chunk.speaker_set,
            source_segment_ids=chunk.source_segment_ids,
            source_text=chunk.source_text,
            cleaned_text=clean.cleaned_text,
            cleaning_version=clean.cleaning_version,
            chunk_strategy_version=chunk.chunk_strategy_version,
        )
        for chunk, clean in rows
    ]
    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="TRANSCRIPT_VIEW",
        resource_type="meeting",
        resource_id=meeting_id,
        correlation_id=correlation_id(request),
    )
    await db.commit()
    return TranscriptResponse(
        meeting_id=meeting_id,
        raw_text=raw.raw_text if raw else None,
        stt_model=raw.stt_model if raw else None,
        segments=segments,
        clean_chunks=clean_chunks,
    )


@router.get("/{meeting_id}/jobs", response_model=list[JobResponse])
async def list_jobs(meeting_id: str, auth: Auth, db: DbSession) -> list[ProcessingJob]:
    await _tenant_meeting(db, meeting_id, auth.tenant_id)
    return list(
        (
            await db.scalars(
                select(ProcessingJob)
                .where(
                    ProcessingJob.meeting_id == meeting_id,
                    ProcessingJob.tenant_id == auth.tenant_id,
                )
                .order_by(ProcessingJob.created_at.desc())
            )
        ).all()
    )


@router.post("/{meeting_id}/reprocess", status_code=status.HTTP_202_ACCEPTED)
async def reprocess(
    meeting_id: str,
    payload: ReprocessRequest,
    request: Request,
    auth: Auth,
    db: DbSession,
) -> dict[str, str]:
    if auth.role not in {UserRole.OWNER, UserRole.ADMIN}:
        raise HTTPException(status_code=403, detail="Admin role required")
    meeting = await _tenant_meeting(db, meeting_id, auth.tenant_id)
    meeting.failure_reason = None
    add_audit_log(
        db,
        tenant_id=auth.tenant_id,
        user_id=auth.user_id,
        action="MEETING_REPROCESS",
        resource_type="meeting",
        resource_id=meeting_id,
        correlation_id=correlation_id(request),
        details={"from_stage": payload.from_stage.value},
    )
    await db.commit()
    from app.workers.tasks import enqueue_pipeline

    task_id = enqueue_pipeline(
        meeting_id, auth.tenant_id, correlation_id(request), payload.from_stage, force=True
    )
    return {"task_id": task_id, "status": "accepted"}

