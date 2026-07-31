from app.services.transcription import _deepgram_drafts, _segment_drafts


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


def test_deepgram_drafts_map_utterances_to_segments() -> None:
    payload = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "Hello. Hi there.",
                            "utterances": [
                                {
                                    "start": 0.0,
                                    "end": 1.5,
                                    "transcript": "Hello.",
                                    "speaker": 0,
                                    "confidence": 0.99,
                                },
                                {
                                    "start": 1.5,
                                    "end": 3.0,
                                    "transcript": "Hi there.",
                                    "speaker": 1,
                                    "confidence": 0.98,
                                },
                            ],
                        }
                    ]
                }
            ]
        },
        "metadata": {"duration": 3.0},
    }

    drafts = _deepgram_drafts(payload, "Hello. Hi there.")

    assert [(d.start_ms, d.end_ms) for d in drafts] == [(0, 1500), (1500, 3000)]
    assert [d.speaker for d in drafts] == ["Speaker 0", "Speaker 1"]
    assert drafts[0].provider_data["speaker"] == 0


def test_deepgram_drafts_fall_back_to_unlabeled_transcript() -> None:
    payload = {"results": {"channels": [{"alternatives": [{"transcript": "Full transcript"}]}]},
               "metadata": {"duration": 2.5}}

    drafts = _deepgram_drafts(payload, "Full transcript")

    assert len(drafts) == 1
    assert drafts[0].speaker is None
    assert drafts[0].text == "Full transcript"
    assert drafts[0].end_ms == 2500


def test_deepgram_drafts_group_words_by_speaker() -> None:
    payload = {
        "results": {
            "channels": [
                {
                    "alternatives": [
                        {
                            "transcript": "Hello there. Goodbye now.",
                            "words": [
                                {"word": "Hello", "start": 0.0, "end": 0.4, "speaker": 0, "confidence": 0.9},
                                {"word": "there", "start": 0.4, "end": 0.8, "speaker": 0, "confidence": 0.8},
                                {"word": ".", "start": 0.8, "end": 0.9, "speaker": 0, "confidence": 0.9},
                                {"word": "Goodbye", "start": 0.9, "end": 1.4, "speaker": 1, "confidence": 0.95},
                                {"word": "now", "start": 1.4, "end": 1.9, "speaker": 1, "confidence": 0.85},
                            ],
                        }
                    ]
                }
            ]
        },
        "metadata": {"duration": 2.0},
    }

    drafts = _deepgram_drafts(payload, payload["results"]["channels"][0]["alternatives"][0]["transcript"])

    assert len(drafts) == 2
    assert drafts[0].speaker == "Speaker 0"
    assert drafts[0].text == "Hello there."
    assert (drafts[0].start_ms, drafts[0].end_ms) == (0, 900)
    assert drafts[1].speaker == "Speaker 1"
    assert drafts[1].text == "Goodbye now"
    assert (drafts[1].start_ms, drafts[1].end_ms) == (900, 1900)
