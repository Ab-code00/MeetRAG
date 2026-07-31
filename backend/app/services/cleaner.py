import re

NOISE_MARKERS = re.compile(
    r"\[(?:inaudible|crosstalk|noise|music|silence|laughter|unintelligible)(?:[^\]]*)\]",
    re.IGNORECASE,
)
FILLER_WORDS = re.compile(
    r"(?<![\w-])(?:um+|uh+|erm+|hmm+|you know|I mean)(?![\w-])[,]?",
    re.IGNORECASE,
)
REPEATED_FRAGMENT = re.compile(r"\b(\w+(?:\s+\w+){0,3})\s+\1\b", re.IGNORECASE)
SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([,.!?;:])")
MULTISPACE = re.compile(r"[ \t]+")


def clean_transcript_text(text: str) -> str:
    """Deterministically normalize speech without summarizing or changing facts."""
    cleaned = NOISE_MARKERS.sub(" ", text)
    cleaned = FILLER_WORDS.sub(" ", cleaned)
    for _ in range(3):
        replacement = REPEATED_FRAGMENT.sub(r"\1", cleaned)
        if replacement == cleaned:
            break
        cleaned = replacement
    cleaned = cleaned.replace("\r", " ").replace("\n", " ")
    cleaned = MULTISPACE.sub(" ", cleaned).strip()
    cleaned = SPACE_BEFORE_PUNCTUATION.sub(r"\1", cleaned)
    cleaned = re.sub(r"([.!?])([A-Za-z])", r"\1 \2", cleaned)
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned

