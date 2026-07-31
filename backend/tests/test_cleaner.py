from app.services.cleaner import clean_transcript_text


def test_cleaner_removes_noise_and_fillers_without_changing_facts() -> None:
    raw = "Um, the launch is June 12, 2026 [crosstalk] you know with Project Atlas"
    assert clean_transcript_text(raw) == "the launch is June 12, 2026 with Project Atlas."


def test_cleaner_collapses_repeated_fragments() -> None:
    assert clean_transcript_text("We should should deploy deploy Friday") == "We should deploy Friday."


def test_cleaner_is_deterministic() -> None:
    text = "Uh, keep API-v2 and 42."
    assert clean_transcript_text(text) == clean_transcript_text(text)

