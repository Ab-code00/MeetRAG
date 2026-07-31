from dataclasses import dataclass

from app.services.cleaner import clean_transcript_text


@dataclass(frozen=True)
class SourceSegment:
    id: str
    start_ms: int
    end_ms: int
    speaker: str | None
    text: str


@dataclass(frozen=True)
class ChunkDraft:
    start_ms: int
    end_ms: int
    speakers: list[str]
    source_segment_ids: list[str]
    source_text: str
    cleaned_text: str


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _render(segments: list[SourceSegment], *, clean: bool) -> str:
    lines: list[str] = []
    for segment in segments:
        text = clean_transcript_text(segment.text) if clean else segment.text.strip()
        if not text:
            continue
        speaker = segment.speaker or "Unknown speaker"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _draft(segments: list[SourceSegment]) -> ChunkDraft:
    speakers = list(dict.fromkeys(item.speaker or "Unknown speaker" for item in segments))
    return ChunkDraft(
        start_ms=segments[0].start_ms,
        end_ms=segments[-1].end_ms,
        speakers=speakers,
        source_segment_ids=[item.id for item in segments],
        source_text=_render(segments, clean=False),
        cleaned_text=_render(segments, clean=True),
    )


def chunk_segments(
    segments: list[SourceSegment],
    *,
    target_tokens: int = 700,
    max_tokens: int = 900,
    overlap_ratio: float = 0.15,
) -> list[ChunkDraft]:
    if not segments:
        return []
    drafts: list[ChunkDraft] = []
    current: list[SourceSegment] = []
    current_tokens = 0

    for segment in segments:
        cleaned = clean_transcript_text(segment.text)
        if not cleaned:
            continue
        segment_tokens = estimate_tokens(cleaned) + estimate_tokens(segment.speaker or "Unknown speaker")
        would_exceed = current and current_tokens + segment_tokens > max_tokens
        at_natural_boundary = (
            current
            and current_tokens >= target_tokens
            and segment.speaker != current[-1].speaker
            and current[-1].text.rstrip().endswith((".", "?", "!"))
        )
        if would_exceed or at_natural_boundary:
            drafts.append(_draft(current))
            overlap_budget = max(1, int(target_tokens * overlap_ratio))
            overlap: list[SourceSegment] = []
            overlap_tokens = 0
            for previous in reversed(current):
                tokens = estimate_tokens(clean_transcript_text(previous.text))
                if overlap and overlap_tokens + tokens > overlap_budget:
                    break
                overlap.insert(0, previous)
                overlap_tokens += tokens
            current = overlap
            current_tokens = overlap_tokens
        current.append(segment)
        current_tokens += segment_tokens

    if current:
        last = _draft(current)
        if not drafts or last.source_segment_ids != drafts[-1].source_segment_ids:
            drafts.append(last)
    return drafts

