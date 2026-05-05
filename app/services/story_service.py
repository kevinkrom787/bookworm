"""
Story service — AI-generated personalized stories for child profiles.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import anthropic


_SCHEMA = """
CREATE TABLE IF NOT EXISTS stories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id   INTEGER NOT NULL,
    title        TEXT    NOT NULL DEFAULT 'My Story',
    content      TEXT    NOT NULL,
    theme        TEXT    NOT NULL DEFAULT '',
    vocab_words  TEXT    NOT NULL DEFAULT '[]',
    age_band     TEXT    NOT NULL,
    generated_at TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_stories_profile ON stories (profile_id, generated_at);
"""

THEMES = [
    {"key": "adventure",  "emoji": "🗺️",  "label": "Big Adventure"},
    {"key": "mystery",    "emoji": "🔍",  "label": "Solve a Mystery"},
    {"key": "funny",      "emoji": "😂",  "label": "Super Silly"},
    {"key": "magical",    "emoji": "✨",  "label": "Magic & Wonder"},
    {"key": "science",    "emoji": "🔬",  "label": "Science Quest"},
    {"key": "friendship", "emoji": "🤝",  "label": "Best Friends"},
    {"key": "sports",     "emoji": "🏆",  "label": "Sports Day"},
    {"key": "animals",    "emoji": "🐾",  "label": "Animal Friends"},
]

LOADING_MSGS = [
    "Sharpening pencils… ✏️",
    "Thinking of adventures… 🤔",
    "Adding exciting plot twists… 🌀",
    "Consulting the story dragons… 🐉",
    "Picking just the right words… 📖",
    "Making it extra fun… ⚡",
    "Almost there… 🎉",
]


@dataclass
class Story:
    id: int
    profile_id: int
    title: str
    content: str
    theme: str
    vocab_words: list
    age_band: str
    generated_at: str

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "profile_id":   self.profile_id,
            "title":        self.title,
            "content":      self.content,
            "theme":        self.theme,
            "vocab_words":  self.vocab_words,
            "age_band":     self.age_band,
            "generated_at": self.generated_at,
        }

    @property
    def word_count(self) -> int:
        return len(self.content.split())

    @property
    def read_minutes(self) -> int:
        return max(1, round(self.word_count / 120))  # kids read ~120 wpm


class StoryService:
    def __init__(self, db_path: Path, api_key: str):
        self.db_path = db_path
        self.api_key = api_key
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _row_to_story(self, row: sqlite3.Row) -> Story:
        return Story(
            id=row["id"],
            profile_id=row["profile_id"],
            title=row["title"],
            content=row["content"],
            theme=row["theme"],
            vocab_words=json.loads(row["vocab_words"]),
            age_band=row["age_band"],
            generated_at=row["generated_at"],
        )

    # ── Generation ────────────────────────────────────────────────────

    def generate(
        self,
        profile,
        theme: str,
        vocab_words: list[str],
    ) -> Story:
        """Call Claude, parse response, save story + return it."""
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY is not set")

        prompt = _build_prompt(profile, theme, vocab_words)
        client = anthropic.Anthropic(api_key=self.api_key)

        message = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        raw = message.content[0].text.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)
        title     = data.get("title", "My Story")
        content   = data.get("story", "")
        questions = data.get("questions", [])

        story = self._save(
            profile_id=profile.id,
            title=title,
            content=content,
            theme=theme,
            vocab_words=vocab_words,
            age_band=profile.age_band,
        )

        return story, questions

    def _save(
        self,
        profile_id: int,
        title: str,
        content: str,
        theme: str,
        vocab_words: list,
        age_band: str,
    ) -> Story:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO stories
                       (profile_id, title, content, theme, vocab_words, age_band)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (profile_id, title, content, theme,
                 json.dumps(vocab_words), age_band),
            )
        return self.get_story(cur.lastrowid)

    # ── Reads ─────────────────────────────────────────────────────────

    def list_stories(self, profile_id: int) -> list[Story]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM stories WHERE profile_id=? ORDER BY generated_at DESC",
                (profile_id,),
            ).fetchall()
        return [self._row_to_story(r) for r in rows]

    def get_story(self, story_id: int) -> Optional[Story]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM stories WHERE id=?", (story_id,)
            ).fetchone()
        return self._row_to_story(row) if row else None

    def delete_story(self, story_id: int, profile_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM stories WHERE id=? AND profile_id=?",
                (story_id, profile_id),
            )
        return cur.rowcount > 0


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_prompt(profile, theme: str, vocab_words: list[str]) -> str:
    age  = profile.age
    name = profile.name

    if age <= 6:
        length_guide = "120–160 words"
        style_guide  = "Very short sentences (5–8 words each). Simple words only. Lots of action and sound effects like 'WHOOSH!' and 'WOW!'"
    elif age <= 9:
        length_guide = "220–300 words"
        style_guide  = "Clear, engaging sentences. Mix of short and medium length. Some descriptive language."
    else:
        length_guide = "380–480 words"
        style_guide  = "Varied sentence structure. Richer descriptions. Can include mild tension and resolution."

    interests = profile.interests or []
    interests_str = ", ".join(interests) if interests else "adventures"

    ff       = profile.fun_facts or {}
    pet_line = sib_line = food_line = ""
    if ff.get("pet_name") and ff.get("pet_type"):
        pet_line = f"- Has a {ff['pet_type']} named {ff['pet_name']} (include them if it fits naturally)"
    if ff.get("siblings"):
        sib_line = f"- Siblings: {ff['siblings']} (can appear if natural)"
    if ff.get("fav_food"):
        food_line = f"- Loves eating {ff['fav_food']} (fun to mention)"

    vocab_str = ""
    if vocab_words:
        shown = vocab_words[:5]
        vocab_str = f"""
Use these vocabulary words naturally in the story (weave them in, don't force it):
{', '.join(shown)}"""

    theme_note = f"Theme / setting: {theme}" if theme else "Theme: exciting adventure"

    return f"""Write a personalized story for a {age}-year-old named {name}.

{theme_note}
Child's interests: {interests_str}
{pet_line}
{sib_line}
{food_line}
{vocab_str}

Story rules:
- {name} is the hero
- {length_guide} total
- {style_guide}
- Positive, satisfying ending
- Fun and exciting throughout

Then write 3 comprehension questions (multiple choice, 4 options each, one correct answer).

Respond ONLY with this exact JSON structure (no markdown, no extra text):
{{
  "title": "Short exciting title (5 words or less)",
  "story": "Full story text here...",
  "questions": [
    {{"question": "...", "choices": ["A...", "B...", "C...", "D..."], "correct_index": 0, "explanation": "Because..."}},
    {{"question": "...", "choices": ["A...", "B...", "C...", "D..."], "correct_index": 1, "explanation": "Because..."}},
    {{"question": "...", "choices": ["A...", "B...", "C...", "D..."], "correct_index": 2, "explanation": "Because..."}}
  ]
}}"""
