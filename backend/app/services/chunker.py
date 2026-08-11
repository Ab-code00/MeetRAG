"""Two-level, speaker-aware chunking for meeting transcripts.

Implements the strategy in ``chunking_strategy.md``:

- **TURN chunks** — one speaker turn each, indexed separately for precision
  (exact quotes, speaker-filtered search, timestamps).
- **CONTEXT chunks** — rolling windows of consecutive speaker turns for
  understanding (decisions, Q&A exchanges, discussion context). Windows never
  split a speaker turn, carry a small whole-turn overlap, and each TURN chunk
  links to the CONTEXT chunk that contains it (``parent_context_index``) so
  retrieval can return the parent conversation window.
"""

from dataclasses import dataclass

from app.models.enums import ChunkType
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
    chunk_type: ChunkType
    # Index of the first/last source segment (0-based position in the ordered
    # usable-segment list covered by this chunk — i.e. after segments that
    # clean to nothing have been dropped, so NOT TranscriptSegmentRaw.ordinal).
    turn_start: int
    turn_end: int
    # For TURN chunks: index into the plan's context_chunks list of the parent
    # window. None for CONTEXT chunks.
    parent_context_index: int | None
    start_ms: int
    end_ms: int
    speakers: list[str]
    source_segment_ids: list[str]
    source_text: str
    cleaned_text: str


@dataclass(frozen=True)
class ChunkPlan:
    context_chunks: list[ChunkDraft]
    turn_chunks: list[ChunkDraft]

    @property
    def all_chunks(self) -> list[ChunkDraft]:
        return self.context_chunks + self.turn_chunks


def estimate_tokens(text: str) -> int:
    return max(1, (len(text) + 3) // 4)


def _segment_tokens(segment: SourceSegment) -> int:
    cleaned = clean_transcript_text(segment.text)
    if not cleaned:
        return 0
    return estimate_tokens(cleaned) + estimate_tokens(segment.speaker or "Unknown speaker")


def _usable_segments(segments: list[SourceSegment]) -> list[SourceSegment]:
    """Drop segments that clean down to nothing (pure filler/noise)."""
    return [segment for segment in segments if clean_transcript_text(segment.text)]


def _render(segments: list[SourceSegment], *, clean: bool) -> str:
    lines: list[str] = []
    for segment in segments:
        text = clean_transcript_text(segment.text) if clean else segment.text.strip()
        if not text:
            continue
        speaker = segment.speaker or "Unknown speaker"
        lines.append(f"{speaker}: {text}")
    return "\n".join(lines)


def _draft(
    chunk_type: ChunkType,
    segments: list[SourceSegment],
    *,
    turn_start: int,
    turn_end: int,
    parent_context_index: int | None,
) -> ChunkDraft:
    speakers = list(dict.fromkeys(item.speaker or "Unknown speaker" for item in segments))
    return ChunkDraft(
        chunk_type=chunk_type,
        turn_start=turn_start,
        turn_end=turn_end,
        parent_context_index=parent_context_index,
        start_ms=segments[0].start_ms,
        end_ms=segments[-1].end_ms,
        speakers=speakers,
        source_segment_ids=[item.id for item in segments],
        source_text=_render(segments, clean=False),
        cleaned_text=_render(segments, clean=True),
    )


def _build_context_windows(
    segments: list[SourceSegment],
    *,
    target_tokens: int,
    max_tokens: int,
    min_turns: int,
    max_turns: int,
    overlap_turns: int,
) -> list[tuple[int, list[SourceSegment]]]:
    """
    Group consecutive speaker turns into rolling context windows.

    Returns ``(first_index, window)`` pairs where ``first_index`` is the
    0-based position of ``window[0]`` in ``segments``. Windows never split a
    turn; the overlap is a whole number of trailing turns.
    """
    windows: list[tuple[int, list[SourceSegment]]] = []
    current: list[SourceSegment] = []
    current_tokens = 0
    first_index = 0

    for index, segment in enumerate(segments):
        segment_tokens = _segment_tokens(segment)
        if current:
            at_minimum = len(current) >= min_turns
            over_budget = at_minimum and current_tokens + segment_tokens > max_tokens
            at_turn_cap = at_minimum and len(current) >= max_turns
            # Prefer ending after a completed exchange: next speaker differs and
            # the previous turn finished with sentence punctuation.
            natural_boundary = (
                at_minimum
                and current_tokens >= target_tokens
                and segment.speaker != current[-1].speaker
                and current[-1].text.rstrip().endswith((".", "?", "!"))
            )
            if over_budget or at_turn_cap or natural_boundary:
                windows.append((first_index, current))
                overlap = current[-overlap_turns:] if overlap_turns > 0 else []
                current = list(overlap)
                current_tokens = sum(_segment_tokens(item) for item in overlap)
                first_index = index - len(current)
        current.append(segment)
        current_tokens += segment_tokens

    if current:
        windows.append((first_index, current))
    return windows


def chunk_segments(
    segments: list[SourceSegment],
    *,
    target_tokens: int = 700,
    max_tokens: int = 900,
    min_turns: int = 4,
    max_turns: int = 10,
    overlap_turns: int = 2,
) -> ChunkPlan:
    """Chunk a transcript into turn-level and context-level drafts."""
    usable = _usable_segments(segments)
    if not usable:
        return ChunkPlan(context_chunks=[], turn_chunks=[])

    windows = _build_context_windows(
        usable,
        target_tokens=target_tokens,
        max_tokens=max_tokens,
        min_turns=min_turns,
        max_turns=max_turns,
        overlap_turns=overlap_turns,
    )

    context_chunks = [
        _draft(
            ChunkType.CONTEXT,
            window,
            turn_start=first_index,
            turn_end=first_index + len(window) - 1,
            parent_context_index=None,
        )
        for first_index, window in windows
    ]

    # Every turn belongs to at least one window; the last containing window
    # wins so overlapping (carried-forward) turns get the most complete context.
    parent_of_turn: dict[int, int] = {}
    for window_index, (first_index, window) in enumerate(windows):
        for offset in range(len(window)):
            parent_of_turn[first_index + offset] = window_index

    turn_chunks = [
        _draft(
            ChunkType.TURN,
            [segment],
            turn_start=index,
            turn_end=index,
            parent_context_index=parent_of_turn.get(index),
        )
        for index, segment in enumerate(usable)
    ]

    return ChunkPlan(context_chunks=context_chunks, turn_chunks=turn_chunks)
