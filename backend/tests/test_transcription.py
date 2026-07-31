from app.services.transcription import _segment_drafts


def test_segment_drafts_preserve_provider_timestamps() -> None:
    payload = {
        "text": "First sentence. Second sentence.",
        "duration": 3.5,
        "segments": [
            {"start": 0.25, "end": 1.5, "text": " First sentence."},
            {"start": 1.5, "end": 3.5, "text": " Second sentence."},
        ],
    }

    drafts = _segment_drafts(payload, payload["text"])

    assert [(draft.start_ms, draft.end_ms) for draft in drafts] == [
        (250, 1500),
        (1500, 3500),
    ]
    assert drafts[0].provider_data["start"] == 0.25


def test_segment_drafts_fall_back_to_complete_transcript() -> None:
    drafts = _segment_drafts({"duration": 2.25}, "Complete transcript")

    assert len(drafts) == 1
    assert drafts[0].start_ms == 0
    assert drafts[0].end_ms == 2250
    assert drafts[0].text == "Complete transcript"
