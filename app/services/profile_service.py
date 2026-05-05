"""
Profile service — child profiles for personalized learning.
"""
from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


_SCHEMA = """
CREATE TABLE IF NOT EXISTS child_profiles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    age          INTEGER NOT NULL DEFAULT 7,
    age_band     TEXT    NOT NULL DEFAULT 'explorers',
    avatar_emoji TEXT    NOT NULL DEFAULT '🦁',
    avatar_color TEXT    NOT NULL DEFAULT '#6C8EF5',
    interests    TEXT    NOT NULL DEFAULT '[]',
    fun_facts    TEXT    NOT NULL DEFAULT '{}',
    family_id    INTEGER REFERENCES families(id),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""

INTERESTS = [
    {"key": "dinosaurs",   "emoji": "🦕", "label": "Dinosaurs"},
    {"key": "space",       "emoji": "🚀", "label": "Space"},
    {"key": "animals",     "emoji": "🐾", "label": "Animals"},
    {"key": "sports",      "emoji": "⚽", "label": "Sports"},
    {"key": "art",         "emoji": "🎨", "label": "Art & Drawing"},
    {"key": "music",       "emoji": "🎵", "label": "Music"},
    {"key": "vehicles",    "emoji": "🚗", "label": "Cars & Trucks"},
    {"key": "nature",      "emoji": "🌿", "label": "Nature"},
    {"key": "fantasy",     "emoji": "🏰", "label": "Fantasy"},
    {"key": "superheroes", "emoji": "🦸", "label": "Superheroes"},
    {"key": "cooking",     "emoji": "🍳", "label": "Cooking"},
    {"key": "science",     "emoji": "🔬", "label": "Science"},
    {"key": "ocean",       "emoji": "🐋", "label": "Ocean"},
    {"key": "robots",      "emoji": "🤖", "label": "Robots"},
    {"key": "royalty",     "emoji": "👑", "label": "Royalty"},
    {"key": "building",    "emoji": "🏗️", "label": "Building"},
]

AVATARS = ["🦁", "🐯", "🐻", "🦊", "🐼", "🐨", "🦄", "🐸", "🐙", "🐬", "🦋", "🐺", "🦝", "🐰", "🐧", "🦖"]
COLORS  = ["#FF6B6B", "#FFB347", "#FFD93D", "#6BCB77", "#4ECDC4", "#6C8EF5", "#C77DFF", "#FF85A1", "#A8DADC", "#F4A261"]


def age_to_band(age: int) -> str:
    if age <= 6:  return "seedlings"
    if age <= 9:  return "explorers"
    return "adventurers"


@dataclass
class ChildProfile:
    id: int
    name: str
    age: int
    age_band: str
    avatar_emoji: str
    avatar_color: str
    interests: list
    fun_facts: dict
    created_at: str

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "name":         self.name,
            "age":          self.age,
            "age_band":     self.age_band,
            "avatar_emoji": self.avatar_emoji,
            "avatar_color": self.avatar_color,
            "interests":    self.interests,
            "fun_facts":    self.fun_facts,
            "created_at":   self.created_at,
        }


class ProfileService:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _row_to_profile(self, row: sqlite3.Row) -> ChildProfile:
        return ChildProfile(
            id=row["id"],
            name=row["name"],
            age=row["age"],
            age_band=row["age_band"],
            avatar_emoji=row["avatar_emoji"],
            avatar_color=row["avatar_color"],
            interests=json.loads(row["interests"]),
            fun_facts=json.loads(row["fun_facts"]),
            created_at=row["created_at"],
        )

    def list_profiles(self, family_id: int) -> list:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM child_profiles WHERE family_id = ? ORDER BY created_at ASC",
                (family_id,)
            ).fetchall()
        return [self._row_to_profile(r) for r in rows]

    def get_profile(self, profile_id: int, family_id: int) -> Optional[ChildProfile]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM child_profiles WHERE id = ? AND family_id = ?",
                (profile_id, family_id)
            ).fetchone()
        return self._row_to_profile(row) if row else None

    def create_profile(
        self,
        name: str,
        age: int,
        family_id: int,
        avatar_emoji: str = "🦁",
        avatar_color: str = "#6C8EF5",
        interests: list = None,
        fun_facts: dict = None,
    ) -> ChildProfile:
        band = age_to_band(age)
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO child_profiles
                       (name, age, age_band, avatar_emoji, avatar_color, interests, fun_facts, family_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (name.strip(), age, band, avatar_emoji, avatar_color,
                 json.dumps(interests or []), json.dumps(fun_facts or {}), family_id),
            )
        return self.get_profile(cur.lastrowid, family_id)

    def update_profile(self, profile_id: int, name: str, age: int,
                       avatar_emoji: str, avatar_color: str,
                       interests: list, fun_facts: dict,
                       family_id: int) -> Optional[ChildProfile]:
        band = age_to_band(age)
        with self._connect() as conn:
            conn.execute(
                """UPDATE child_profiles SET
                       name=?, age=?, age_band=?, avatar_emoji=?, avatar_color=?,
                       interests=?, fun_facts=?
                   WHERE id=? AND family_id=?""",
                (name.strip(), age, band, avatar_emoji, avatar_color,
                 json.dumps(interests), json.dumps(fun_facts), profile_id, family_id),
            )
        return self.get_profile(profile_id, family_id)

    def delete_profile(self, profile_id: int, family_id: int) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM child_profiles WHERE id = ? AND family_id = ?",
                (profile_id, family_id)
            )
        return cur.rowcount > 0
