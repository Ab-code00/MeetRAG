from datetime import date, datetime

from pydantic import BaseModel, Field

from app.models.enums import JobStage, JobStatus, MeetingStatus, RecordingStatus


class MeetingCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    meeting_date: date | None = None
    project: str | None = Field(default=None, max_length=200)
    department: str | None = Field(default=None, max_length=200)
    filename: str = Field(min_length=1, max_length=500)
    content_type: str = Field(pattern=r"^(audio|video)/[A-Za-z0-9.+-]+$")
    source: str = Field(default="WEB_UPLOAD", max_length=50)
    external_meeting_id: str | None = Field(default=None, max_length=255)


class UploadTarget(BaseModel):
    meeting_id: str
    recording_id: str
    upload_url: str
    upload_method: str = "PUT"
    upload_headers: dict[str, str]
    expires_in: int = 900


class RecordingResponse(BaseModel):
    id: str
    original_filename: str
    content_type: str
    size_bytes: int | None
    status: RecordingStatus

    model_config = {"from_attributes": True}


class MeetingResponse(BaseModel):
    id: str
    title: str
    meeting_date: date | None
    project: str | None
    department: str | None
    source: str
    status: MeetingStatus
    duration_ms: int | None
    failure_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class MeetingDetailResponse(MeetingResponse):
    recordings: list[RecordingResponse]


class MeetingListResponse(BaseModel):
    items: list[MeetingResponse]
    total: int
    limit: int
    offset: int


class UploadCompleteRequest(BaseModel):
    size_bytes: int | None = Field(default=None, ge=1)
    checksum_sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")


class TranscriptSegmentResponse(BaseModel):
    id: str
    ordinal: int
    start_ms: int
    end_ms: int
    speaker: str | None
    text: str
    confidence: float | None

    model_config = {"from_attributes": True}


class CleanChunkResponse(BaseModel):
    chunk_id: str
    clean_chunk_id: str
    ordinal: int
    start_ms: int
    end_ms: int
    speaker_set: list[str]
    source_segment_ids: list[str]
    source_text: str
    cleaned_text: str
    cleaning_version: str
    chunk_strategy_version: str


class TranscriptResponse(BaseModel):
    meeting_id: str
    raw_text: str | None
    stt_model: str | None
    segments: list[TranscriptSegmentResponse]
    clean_chunks: list[CleanChunkResponse]


class ReprocessRequest(BaseModel):
    from_stage: JobStage = JobStage.CLEAN


class JobResponse(BaseModel):
    id: str
    stage: JobStage
    status: JobStatus
    retry_count: int
    max_retries: int
    correlation_id: str
    started_at: datetime | None
    finished_at: datetime | None
    latency_ms: int | None
    failure_reason: str | None
    created_at: datetime

    model_config = {"from_attributes": True}

