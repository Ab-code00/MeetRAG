from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from groq import Groq
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Meeting, Recording, TranscriptRaw, TranscriptSegmentRaw
from app.models.enums import MeetingStatus, RecordingStatus
from app.services.storage import download_recording


@dataclass(frozen=True)
class SegmentDraft:
    start_ms: int
    end_ms: int
    speaker: str | None
    text: str
    confidence: float | None
    provider_data: dict[str, Any]


def _seconds_to_ms(value: object) -> int:
    try:
        return max(0, round(float(value) * 1000))
    except (TypeError, ValueError):
        return 0


def _optional_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _response_payload(response: object) -> dict[str, Any]:
    if isinstance(response, Mapping):
        return dict(response)
    to_dict = getattr(response, "to_dict", None)
    if callable(to_dict):
        payload = to_dict(mode="json")
        if isinstance(payload, Mapping):
            return dict(payload)
    raise RuntimeError("Groq returned an unsupported transcription response")


def _segment_drafts(payload: Mapping[str, Any], raw_text: str) -> list[SegmentDraft]:
    drafts: list[SegmentDraft] = []
    provider_segments = payload.get("segments")
    if isinstance(provider_segments, list):
        for item in provider_segments:
            if not isinstance(item, Mapping):
                continue
            provider_data = dict(item)
            text = str(provider_data.get("text") or "")
            if not text.strip():
                continue
            start_ms = _seconds_to_ms(provider_data.get("start"))
            end_ms = max(start_ms, _seconds_to_ms(provider_data.get("end")))
            speaker_value = provider_data.get("speaker")
            drafts.append(
                SegmentDraft(
                    start_ms=start_ms,
                    end_ms=end_ms,
                    speaker=str(speaker_value) if speaker_value else None,
                    text=text,
                    confidence=_optional_float(provider_data.get("confidence")),
                    provider_data=provider_data,
                )
            )
    if drafts:
        return drafts

    duration_ms = _seconds_to_ms(payload.get("duration"))
    return [
        SegmentDraft(
            start_ms=0,
            end_ms=duration_ms,
            speaker=None,
            text=raw_text,
            confidence=None,
            provider_data={},
        )
    ]


def transcribe_recording(db: Session, meeting: Meeting) -> dict[str, Any]:
    settings = get_settings()
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured")

    existing = db.scalar(
        select(TranscriptRaw).where(
            TranscriptRaw.meeting_id == meeting.id,
            TranscriptRaw.tenant_id == meeting.tenant_id,
            TranscriptRaw.stt_model == settings.groq_stt_model,
        )
    )
    if existing is not None:
        segment_count = db.scalar(
            select(func.count(TranscriptSegmentRaw.id)).where(
                TranscriptSegmentRaw.transcript_raw_id == existing.id,
                TranscriptSegmentRaw.tenant_id == meeting.tenant_id,
            )
        )
        meeting.status = MeetingStatus.TRANSCRIBED
        return {
            "transcript_id": existing.id,
            "segment_count": segment_count or 0,
            "duration_ms": existing.duration_ms,
            "stt_model": existing.stt_model,
            "reused": True,
        }

    recording = db.scalar(
        select(Recording)
        .where(
            Recording.meeting_id == meeting.id,
            Recording.tenant_id == meeting.tenant_id,
            Recording.status == RecordingStatus.VERIFIED,
        )
        .order_by(Recording.created_at)
        .limit(1)
    )
    if recording is None:
        raise RuntimeError("No verified recording is available for transcription")

    suffix = Path(recording.original_filename).suffix[:16]
    with TemporaryDirectory(prefix="meetai-transcription-") as temporary_directory:
        local_path = Path(temporary_directory) / f"recording{suffix}"
        download_recording(recording.object_key, str(local_path))
        if not local_path.exists():
            raise RuntimeError(f"Recording file not found: {recording.object_key}")
        with local_path.open("rb") as audio_file:
            response = Groq(api_key=settings.groq_api_key).audio.transcriptions.create(
                model=settings.groq_stt_model,
                file=(recording.original_filename, audio_file, recording.content_type),
                response_format="verbose_json",
                timestamp_granularities=["segment"],
                temperature=0,
            )

    payload = _response_payload(response)
    raw_text = str(payload.get("text") or "")
    if not raw_text.strip():
        raise RuntimeError("Groq returned an empty transcript")
    drafts = _segment_drafts(payload, raw_text)
    duration_ms = _seconds_to_ms(payload.get("duration"))
    if duration_ms == 0:
        duration_ms = max((draft.end_ms for draft in drafts), default=0)
    language_value = payload.get("language")
    now = datetime.now(UTC)
    transcript = TranscriptRaw(
        tenant_id=meeting.tenant_id,
        meeting_id=meeting.id,
        recording_id=recording.id,
        stt_provider="groq",
        stt_model=settings.groq_stt_model,
        language=str(language_value) if language_value else None,
        raw_text=raw_text,
        provider_response=payload,
        duration_ms=duration_ms,
        created_at=now,
    )
    db.add(transcript)
    db.flush()
    for ordinal, draft in enumerate(drafts):
        db.add(
            TranscriptSegmentRaw(
                tenant_id=meeting.tenant_id,
                meeting_id=meeting.id,
                transcript_raw_id=transcript.id,
                ordinal=ordinal,
                start_ms=draft.start_ms,
                end_ms=draft.end_ms,
                speaker=draft.speaker,
                text=draft.text,
                confidence=draft.confidence,
                provider_data=draft.provider_data,
                created_at=now,
            )
        )
    meeting.status = MeetingStatus.TRANSCRIBED
    return {
        "transcript_id": transcript.id,
        "segment_count": len(drafts),
        "duration_ms": duration_ms,
        "stt_model": settings.groq_stt_model,
        "reused": False,
    }
