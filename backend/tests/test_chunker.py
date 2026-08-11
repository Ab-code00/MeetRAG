from app.models.enums import ChunkType
from app.services.chunker import SourceSegment, chunk_segments


def _segment(index: int, speaker: str, text: str) -> SourceSegment:
    return SourceSegment(
        id=f"s-{index}", start_ms=index * 1000, end_ms=(index + 1) * 1000, speaker=speaker, text=text
    )


def _segment_ids(segments: list[SourceSegment]) -> list[str]:
    return [segment.id for segment in segments]


def test_turn_chunks_preserve_lineage_and_time_range() -> None:
    segments = [
        _segment(0, "Amina", "We will ship the reporting API on Friday."),
        _segment(1, "Noah", "I will own the migration checklist."),
    ]
    plan = chunk_segments(segments, target_tokens=100, max_tokens=120, min_turns=2, max_turns=4)
    assert [chunk.chunk_type for chunk in plan.turn_chunks] == [ChunkType.TURN, ChunkType.TURN]

    first = plan.turn_chunks[0]
    assert first.source_segment_ids == ["s-0"]
    assert first.start_ms == 0
    assert first.end_ms == 1000
    assert first.speakers == ["Amina"]
    assert first.turn_start == 0
    assert first.turn_end == 0

    [context] = plan.context_chunks
    assert context.chunk_type == ChunkType.CONTEXT
    assert context.source_segment_ids == ["s-0", "s-1"]
    assert context.start_ms == 0
    assert context.end_ms == 2000
    assert context.speakers == ["Amina", "Noah"]
    assert (context.turn_start, context.turn_end) == (0, 1)


def test_context_chunks_never_split_a_turn() -> None:
    segments = [
        _segment(index, "A" if index % 2 == 0 else "B", f"Decision number {index} is recorded here.")
        for index in range(12)
    ]
    plan = chunk_segments(
        segments, target_tokens=18, max_tokens=25, min_turns=4, max_turns=10, overlap_turns=2
    )
    assert len(plan.context_chunks) > 1
    all_turn_ids = _segment_ids(segments)
    for chunk in plan.context_chunks:
        ids = chunk.source_segment_ids
        # Whole turns only: ids must be a contiguous slice of the source list.
        positions = [all_turn_ids.index(item) for item in ids]
        assert positions == list(range(positions[0], positions[-1] + 1))


def test_context_chunks_respect_turn_bounds() -> None:
    segments = [
        _segment(index, "A" if index % 2 == 0 else "B", f"Decision number {index} is recorded here.")
        for index in range(30)
    ]
    plan = chunk_segments(
        segments, target_tokens=18, max_tokens=25, min_turns=4, max_turns=8, overlap_turns=2
    )
    assert len(plan.context_chunks) > 1
    for chunk in plan.context_chunks:
        turns = chunk.turn_end - chunk.turn_start + 1
        assert turns <= 8
        assert turns >= 2  # at least the overlap + one new turn


def test_overlap_carries_whole_turns() -> None:
    segments = [
        _segment(index, "A" if index % 2 == 0 else "B", f"Decision number {index} is recorded here.")
        for index in range(12)
    ]
    plan = chunk_segments(
        segments, target_tokens=18, max_tokens=25, min_turns=4, max_turns=10, overlap_turns=2
    )
    assert set(plan.context_chunks[0].source_segment_ids) & set(
        plan.context_chunks[1].source_segment_ids
    )
    overlap = set(plan.context_chunks[0].source_segment_ids) & set(
        plan.context_chunks[1].source_segment_ids
    )
    assert len(overlap) <= 2


def test_every_turn_links_to_a_containing_parent_context() -> None:
    segments = [
        _segment(index, "A" if index % 2 == 0 else "B", f"Decision number {index} is recorded here.")
        for index in range(12)
    ]
    plan = chunk_segments(
        segments, target_tokens=18, max_tokens=25, min_turns=4, max_turns=10, overlap_turns=2
    )
    assert plan.turn_chunks
    for turn in plan.turn_chunks:
        assert turn.parent_context_index is not None
        parent = plan.context_chunks[turn.parent_context_index]
        assert turn.source_segment_ids[0] in parent.source_segment_ids


def test_empty_and_single_turn_meetings() -> None:
    assert chunk_segments([]).context_chunks == []
    assert chunk_segments([]).turn_chunks == []

    plan = chunk_segments([_segment(0, "Amina", "Short statement.")])
    assert len(plan.turn_chunks) == 1
    assert len(plan.context_chunks) == 1
    assert plan.context_chunks[0].source_segment_ids == ["s-0"]
    assert plan.turn_chunks[0].parent_context_index == 0
