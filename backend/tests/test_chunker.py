from app.services.chunker import SourceSegment, chunk_segments


def _segment(index: int, speaker: str, text: str) -> SourceSegment:
    return SourceSegment(
        id=f"s-{index}", start_ms=index * 1000, end_ms=(index + 1) * 1000, speaker=speaker, text=text
    )


def test_chunker_preserves_lineage_and_time_range() -> None:
    segments = [
        _segment(0, "Amina", "We will ship the reporting API on Friday."),
        _segment(1, "Noah", "I will own the migration checklist."),
    ]
    [chunk] = chunk_segments(segments, target_tokens=100, max_tokens=120)
    assert chunk.source_segment_ids == ["s-0", "s-1"]
    assert chunk.start_ms == 0
    assert chunk.end_ms == 2000
    assert chunk.speakers == ["Amina", "Noah"]


def test_chunker_adds_bounded_overlap() -> None:
    segments = [
        _segment(index, "A" if index % 2 == 0 else "B", f"Decision number {index} is recorded here.")
        for index in range(12)
    ]
    chunks = chunk_segments(segments, target_tokens=18, max_tokens=25, overlap_ratio=0.15)
    assert len(chunks) > 1
    assert set(chunks[0].source_segment_ids) & set(chunks[1].source_segment_ids)

