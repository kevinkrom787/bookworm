"""
Tests for My Story feature.

Run with:  python -m pytest tests/test_story_builder.py -v
"""
import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.services.story_builder import (
    VIRTUES,
    StoryBuilder,
    _cache_key,
    _moderation_tier,
    _parse_json,
)
from app.services.character_service import CharacterService
from app.services.streak_service import StreakService


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test.db"
    # Apply migrations
    migrations = Path(__file__).parent.parent / "migrations" / "001_story_tables.sql"
    conn = sqlite3.connect(str(path))
    conn.executescript(migrations.read_text())
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def mock_config(tmp_path):
    cfg = MagicMock()
    cfg.ANTHROPIC_API_KEY   = "test-key"
    cfg.AI_PROVIDER         = "claude"
    cfg.IMAGE_PROVIDER      = "replicate"
    cfg.REPLICATE_API_KEY   = ""
    cfg.MONTHLY_IMAGE_BUDGET = 5.0
    return cfg


@pytest.fixture
def builder(db_path, mock_config):
    return StoryBuilder(db_path=db_path, config=mock_config)


@pytest.fixture
def char_svc(db_path):
    return CharacterService(db_path=db_path)


@pytest.fixture
def streak_svc(db_path):
    return StreakService(db_path=db_path)


@pytest.fixture
def mock_profile():
    p = MagicMock()
    p.id       = 1
    p.name     = "Jax"
    p.age      = 6
    p.age_band = "seedlings"
    p.interests = ["animals", "space"]
    return p


# ── Virtue rotation ───────────────────────────────────────────────────────────

def test_virtue_rotation_no_repeat_in_window(builder, mock_profile):
    seen = []
    for _ in range(6):
        v = builder._rotate_virtue(mock_profile.id)
        seen.append(v)

    # No virtue should appear in two consecutive nights within a 3-night window
    for i in range(3, len(seen)):
        window = seen[i-3:i]
        assert seen[i] not in window, (
            f"Virtue {seen[i]!r} repeated within 3-night window: {window}"
        )


def test_virtue_rotation_uses_all_virtues(builder, mock_profile):
    seen = set()
    # 20x the virtue count is enough to make missing one astronomically unlikely
    for _ in range(len(VIRTUES) * 20):
        v = builder._rotate_virtue(mock_profile.id)
        seen.add(v)
    assert seen == set(VIRTUES)


def test_virtue_rotation_persists_between_calls(builder, mock_profile, db_path):
    v1 = builder._rotate_virtue(mock_profile.id)
    # New builder instance, same DB — should not repeat v1 for 3 nights
    builder2 = StoryBuilder(db_path=db_path, config=builder.config)
    v2 = builder2._rotate_virtue(mock_profile.id)
    v3 = builder2._rotate_virtue(mock_profile.id)
    assert v1 not in [v2, v3]


# ── Moderation ────────────────────────────────────────────────────────────────

def test_moderation_ok_text():
    assert _moderation_tier("The dog found a cozy spot under the stars.") == "ok"


def test_moderation_mild_word():
    assert _moderation_tier("He felt stupid for forgetting.") == "mild"


def test_moderation_alert_word():
    assert _moderation_tier("They drank alcohol.") == "alert"


def test_moderation_case_insensitive():
    assert _moderation_tier("STUPID mistake") == "mild"
    assert _moderation_tier("ALCOHOL at the party") == "alert"


def test_moderation_fallback_path(builder, mock_profile, db_path, mock_config):
    """When a page trips mild twice, fallback paragraph is used."""
    mild_page  = {"page_number": 2, "text": "He felt stupid and hurt.", "on_stage_characters": [], "illustration_moment": None}
    clean_page = {"page_number": 1, "text": "It was a wonderful morning.", "on_stage_characters": [], "illustration_moment": None}

    story_json = {
        "title": "Test",
        "pages": [clean_page, mild_page],
        "illustration_scenes": [],
        "virtue_focus": "courage",
        "vocabulary_used": [],
        "recap": {"lesson": "x", "talk_about_it": "y"},
    }

    ai_mock = MagicMock()
    # First complete() call → story JSON
    # Second call (regen) → still mild
    ai_mock.complete.side_effect = [
        json.dumps(story_json),
        "He felt really hurt and stupid after all.",
    ]
    ai_mock.MODEL = "test-model"

    story_id = builder.create_placeholder(mock_profile.id, [], "adventure", "short")

    with patch.object(builder, "_get_ai", return_value=ai_mock), \
         patch.object(builder, "_get_img", return_value=MagicMock(is_configured=lambda: False)):
        builder._build(story_id, mock_profile, [], "adventure", "short")

    data = builder.get_story_data(story_id)
    pages = data["full_story_json"]["pages"]
    fallback_text = "Sometimes the best adventures are the quiet ones"
    assert any(fallback_text in p["text"] for p in pages)
    assert any(e["action"] == "fallback" for e in data["moderation_events"])


# ── Skip-and-defer image logic ────────────────────────────────────────────────

def test_image_url_attached_to_correct_page(builder, mock_profile, db_path):
    """_attach_image writes image_url into the correct page in full_story_json."""
    story_json = {
        "title": "x",
        "pages": [
            {"page_number": 1, "text": "p1", "on_stage_characters": [], "illustration_moment": None},
            {"page_number": 2, "text": "p2", "on_stage_characters": [], "illustration_moment": 2},
            {"page_number": 3, "text": "p3", "on_stage_characters": [], "illustration_moment": None},
        ],
        "illustration_scenes": [],
        "virtue_focus": "courage",
        "vocabulary_used": [],
        "recap": {"lesson": "", "talk_about_it": ""},
    }
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """INSERT INTO story_history (profile_id, title, full_story_json, generation_status)
           VALUES (1, 'x', ?, 'ready')""",
        (json.dumps(story_json),),
    )
    story_id = cur.lastrowid
    conn.commit()
    conn.close()

    builder._attach_image(story_id, 2, "https://example.com/img.webp")

    data = builder.get_story_data(story_id)
    pages = {p["page_number"]: p for p in data["full_story_json"]["pages"]}
    assert pages[2].get("image_url") == "https://example.com/img.webp"
    assert "image_url" not in pages[1]
    assert "image_url" not in pages[3]


# ── Vocab extraction ──────────────────────────────────────────────────────────

def test_vocab_encounters_populated_on_complete(builder, mock_profile, db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """INSERT INTO story_history
               (profile_id, title, full_story_json, vocabulary_used, generation_status, completed)
           VALUES (?, 'x', '{}', ?, 'ready', 0)""",
        (mock_profile.id, json.dumps(["luminous", "persevere"])),
    )
    story_id = cur.lastrowid
    conn.commit()
    conn.close()

    builder.complete_story(story_id, mock_profile.id)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT word FROM vocab_encounters WHERE profile_id = ?",
        (mock_profile.id,),
    ).fetchall()
    conn.close()

    words = {r["word"] for r in rows}
    assert "luminous" in words
    assert "persevere" in words


# ── Streak updates ────────────────────────────────────────────────────────────

def test_streak_increments_on_consecutive_days(streak_svc):
    from datetime import date, timedelta
    pid = 42
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    conn = sqlite3.connect(str(streak_svc.db_path))
    conn.execute(
        """INSERT INTO streaks (profile_id, days_read_current, days_read_longest,
               last_read_date, total_stories_completed)
           VALUES (?, 3, 3, ?, 5)""",
        (pid, yesterday),
    )
    conn.commit()
    conn.close()

    result = streak_svc.update_on_complete(pid)
    assert result["days_read_current"] == 4
    assert result["days_read_longest"] == 4


def test_streak_resets_on_gap(streak_svc):
    from datetime import date, timedelta
    pid = 43
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()

    conn = sqlite3.connect(str(streak_svc.db_path))
    conn.execute(
        """INSERT INTO streaks (profile_id, days_read_current, days_read_longest,
               last_read_date, total_stories_completed)
           VALUES (?, 5, 7, ?, 10)""",
        (pid, two_days_ago),
    )
    conn.commit()
    conn.close()

    result = streak_svc.update_on_complete(pid)
    assert result["days_read_current"] == 1
    assert result["days_read_longest"] == 7  # longest preserved


# ── Integration: mock provider end-to-end ────────────────────────────────────

def test_integration_mock_provider(builder, mock_profile, db_path, mock_config):
    """Full pipeline from placeholder → ready using a mock AI provider."""
    char_svc = CharacterService(db_path)
    biscuit  = char_svc.create_character(
        profile_id=mock_profile.id,
        name="Biscuit",
        canonical_description="a golden terrier",
        is_starter=True,
    )

    story_json = {
        "title": "Biscuit and the Bright Moon",
        "pages": [
            {"page_number": 1, "text": "Once there was a dog named Biscuit.", "on_stage_characters": ["Biscuit"], "illustration_moment": None},
            {"page_number": 2, "text": "He felt curious about the glowing moon.", "on_stage_characters": ["Biscuit"], "illustration_moment": 2},
            {"page_number": 3, "text": "He ran home and found the warmth he needed.", "on_stage_characters": ["Biscuit"], "illustration_moment": None},
        ],
        "illustration_scenes": [
            {"page_number": 2, "scene_description": "A small golden dog looking up at a large glowing moon.", "characters_present": ["Biscuit"]},
        ],
        "virtue_focus": "curiosity",
        "vocabulary_used": ["luminous", "curious"],
        "recap": {
            "lesson": "Curiosity leads us to beautiful discoveries.",
            "talk_about_it": "What's something you've always wondered about?",
        },
    }

    ai_mock       = MagicMock()
    ai_mock.complete.return_value = json.dumps(story_json)
    ai_mock.MODEL = "mock-model"

    story_id = builder.create_placeholder(
        mock_profile.id, [biscuit.character_id], "adventure", "short"
    )

    with patch.object(builder, "_get_ai", return_value=ai_mock), \
         patch.object(builder, "_get_img", return_value=MagicMock(is_configured=lambda: False)):
        builder._build(story_id, mock_profile, [biscuit.character_id], "adventure", "short")

    data = builder.get_story_data(story_id)
    assert data["generation_status"] == "ready"
    assert data["full_story_json"]["title"] == "Biscuit and the Bright Moon"
    # virtue_focus is set by the builder's rotation, not by the mock AI's JSON
    assert data["virtue_focus"] in VIRTUES
    assert len(data["full_story_json"]["pages"]) == 3
    assert not data["moderation_events"]

    # Complete the story
    builder.complete_story(story_id, mock_profile.id)
    data = builder.get_story_data(story_id)
    assert data["completed"] == 1

    # Vocab encounters populated
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    words = {r["word"] for r in conn.execute(
        "SELECT word FROM vocab_encounters WHERE profile_id = ?",
        (mock_profile.id,),
    ).fetchall()}
    conn.close()
    assert "luminous" in words
    assert "curious" in words


# ── JSON parse helper ─────────────────────────────────────────────────────────

def test_parse_json_strips_fences():
    raw = '```json\n{"title": "x"}\n```'
    assert _parse_json(raw) == {"title": "x"}


def test_parse_json_plain():
    raw = '{"title": "y"}'
    assert _parse_json(raw) == {"title": "y"}
