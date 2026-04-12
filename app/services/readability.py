"""
Readability scoring — pure Python, no dependencies.

Flesch-Kincaid Grade Level is the standard algorithm used by US schools.
Grade 1 ≈ first grade (age 6), Grade 6 ≈ sixth grade (age 12).

We map grade level to Atlas age bands:
  Seedlings  (grade 1-2)  → ages 4-6
  Explorers  (grade 3-5)  → ages 7-9
  Adventurers (grade 6+)  → ages 10-12
"""

import re


def flesch_kincaid_grade(text: str) -> float:
    """
    Flesch-Kincaid Grade Level.
    Returns a float from 1.0 (very easy) to 16.0 (college level).
    """
    words = _count_words(text)
    sentences = _count_sentences(text)
    syllables = _count_syllables_in_text(text)

    if sentences == 0 or words == 0:
        return 1.0

    grade = 0.39 * (words / sentences) + 11.8 * (syllables / words) - 15.59
    return round(max(1.0, min(grade, 16.0)), 1)


def reading_ease(text: str) -> float:
    """
    Flesch Reading Ease score. 100 = very easy, 0 = very hard.
    60-70 is considered standard plain English.
    """
    words = _count_words(text)
    sentences = _count_sentences(text)
    syllables = _count_syllables_in_text(text)

    if sentences == 0 or words == 0:
        return 100.0

    ease = 206.835 - 1.015 * (words / sentences) - 84.6 * (syllables / words)
    return round(max(0.0, min(ease, 100.0)), 1)


def age_band_for_grade(grade: float) -> str:
    """Map a Flesch-Kincaid grade to an Atlas age band."""
    if grade <= 2.5:
        return "seedlings"
    elif grade <= 5.5:
        return "explorers"
    else:
        return "adventurers"


def score_book_sample(text: str) -> dict:
    """
    Score a text sample. Pass the first ~2000 words of a book for a fast estimate.
    Returns a dict suitable for JSON response.
    """
    grade = flesch_kincaid_grade(text)
    return {
        "grade_level": grade,
        "reading_ease": reading_ease(text),
        "age_band": age_band_for_grade(grade),
        "approximate_age": max(6, min(18, int(grade) + 5)),
    }


# ------------------------------------------------------------------ internals

def _count_words(text: str) -> int:
    return len(text.split())


def _count_sentences(text: str) -> int:
    parts = re.split(r"[.!?]+", text)
    return max(1, len([p for p in parts if p.strip()]))


def _count_syllables_in_text(text: str) -> int:
    total = 0
    for word in text.split():
        clean = re.sub(r"[^a-zA-Z]", "", word).lower()
        if clean:
            total += _syllables_in_word(clean)
    return max(total, _count_words(text))  # at least one syllable per word


def _syllables_in_word(word: str) -> int:
    """Estimate syllable count using vowel-group heuristic."""
    if not word:
        return 0

    # Count vowel groups (each group = one syllable)
    count = len(re.findall(r"[aeiouy]+", word))

    # Silent 'e' at end: "make" → 1 syllable, not 2
    if word.endswith("e") and len(word) > 2 and word[-2] not in "aeiouy":
        count -= 1

    # "le" ending counts (e.g., "table" → 2)
    if word.endswith("le") and len(word) > 2 and word[-3] not in "aeiouy":
        count += 1

    return max(1, count)
