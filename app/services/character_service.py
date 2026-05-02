"""
Character library — per-profile story characters with locked visual identity.

Visual identity (canonical_description, style_descriptor, generation_seed,
provider_name, model_version) is immutable after first write. This is how
Biscuit looks like Biscuit on night 2, night 20, and night 200.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class Character:
    character_id: int
    profile_id: int
    name: str
    canonical_description: str
    style_descriptor: str
    generation_seed: str
    provider_name: str
    model_version: str
    avatar_emoji: str
    is_starter: bool
    times_featured: int
    last_featured_at: Optional[str]
    created_at: str

    def to_dict(self) -> dict:
        return {
            "character_id":          self.character_id,
            "name":                  self.name,
            "canonical_description": self.canonical_description,
            "style_descriptor":      self.style_descriptor,
            "avatar_emoji":          self.avatar_emoji,
            "is_starter":            self.is_starter,
            "times_featured":        self.times_featured,
        }


# The 4 suggested starters shown when the character library is empty.
# 4th starter is created dynamically using the child's own name + age.
_STARTER_TEMPLATES = [
    {
        "name":                  "Bruno",
        "canonical_description": "a big warm brown bear with round ears, a gentle face, and a cozy belly",
        "avatar_emoji":          "🐻",
    },
    {
        "name":                  "Fern",
        "canonical_description": "a clever rust-red fox with a bushy white-tipped tail and bright amber eyes",
        "avatar_emoji":          "🦊",
    },
    {
        "name":                  "Hoot",
        "canonical_description": "a wise speckled owl with large golden eyes and soft grey-brown feathers",
        "avatar_emoji":          "🦉",
    },
    {
        "name":                  "Splash",
        "canonical_description": "a curious octopus with eight curly tentacles, bright wide eyes, and shimmering teal skin",
        "avatar_emoji":          "🐙",
    },
    {
        "name":                  "Stella",
        "canonical_description": "a magical unicorn with a shimmering silver horn, flowing rainbow mane, and a coat of pale gold",
        "avatar_emoji":          "🦄",
    },
    {
        "name":                  "Rex",
        "canonical_description": "a friendly young T-rex with tiny arms, wide bright eyes, a big toothy grin, and cheerful green scales",
        "avatar_emoji":          "🦖",
    },
    {
        "name":                  "Stripe",
        "canonical_description": "a bold tiger cub with vivid orange and black stripes, a fluffy chest, and curious amber eyes",
        "avatar_emoji":          "🐯",
    },
    {
        "name":                  "Bay",
        "canonical_description": "a gentle blue whale with a wide friendly smile, a pale spotted belly, and soft round fins",
        "avatar_emoji":          "🐋",
    },
    {
        "name":                  "Shadow",
        "canonical_description": "a wise silver wolf with soft grey fur, bright moonlit eyes, and a thick bushy tail",
        "avatar_emoji":          "🐺",
    },
    {
        "name":                  "Mochi",
        "canonical_description": "a round fluffy panda with big black eye patches, a cheerful grin, and a bamboo sprig tucked behind one ear",
        "avatar_emoji":          "🐼",
    },
    {
        "name":                  "Scout",
        "canonical_description": "a majestic golden eagle with keen amber eyes, broad brown-and-white wings, and a proud upright crest",
        "avatar_emoji":          "🦅",
    },
]
_DEFAULT_STYLE = (
    "bold children's book illustration, thick expressive ink outlines, "
    "vivid jewel-tone colors, richly detailed environments, "
    "exaggerated expressive faces, dynamic poses, sense of wonder"
)


class CharacterService:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _row_to_character(self, row: sqlite3.Row) -> Character:
        return Character(
            character_id=row["character_id"],
            profile_id=row["profile_id"],
            name=row["name"],
            canonical_description=row["canonical_description"],
            style_descriptor=row["style_descriptor"],
            generation_seed=row["generation_seed"],
            provider_name=row["provider_name"],
            model_version=row["model_version"],
            avatar_emoji=row["avatar_emoji"],
            is_starter=bool(row["is_starter"]),
            times_featured=row["times_featured"],
            last_featured_at=row["last_featured_at"],
            created_at=row["created_at"],
        )

    def get_characters(self, profile_id: int) -> list[Character]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM characters WHERE profile_id = ?
                   ORDER BY times_featured DESC, created_at ASC""",
                (profile_id,),
            ).fetchall()
        return [self._row_to_character(r) for r in rows]

    def get_character(self, character_id: int) -> Optional[Character]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM characters WHERE character_id = ?",
                (character_id,),
            ).fetchone()
        return self._row_to_character(row) if row else None

    def create_character(
        self,
        profile_id: int,
        name: str,
        canonical_description: str = "",
        style_descriptor: str = _DEFAULT_STYLE,
        avatar_emoji: str = "🐾",
        is_starter: bool = False,
    ) -> Character:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO characters
                       (profile_id, name, canonical_description, style_descriptor,
                        avatar_emoji, is_starter)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (profile_id, name.strip(), canonical_description,
                 style_descriptor, avatar_emoji, int(is_starter)),
            )
        return self.get_character(cur.lastrowid)

    def lock_visual_identity(
        self,
        character_id: int,
        canonical_description: str,
        style_descriptor: str,
        generation_seed: str,
        provider_name: str,
        model_version: str,
    ) -> None:
        """Write visual identity fields — immutable after first write."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT provider_name FROM characters WHERE character_id = ?",
                (character_id,),
            ).fetchone()
            if existing and existing["provider_name"]:
                return  # already locked — refuse overwrite
            conn.execute(
                """UPDATE characters SET
                       canonical_description = ?,
                       style_descriptor      = ?,
                       generation_seed       = ?,
                       provider_name         = ?,
                       model_version         = ?
                   WHERE character_id = ?""",
                (canonical_description, style_descriptor, generation_seed,
                 provider_name, model_version, character_id),
            )

    def increment_featured(self, character_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE characters
                   SET times_featured   = times_featured + 1,
                       last_featured_at = datetime('now')
                   WHERE character_id = ?""",
                (character_id,),
            )

    def get_or_create_starters(
        self, profile_id: int, child_name: str, child_age: int
    ) -> list[Character]:
        """Seed the 4 starter characters for a new profile."""
        existing = self.get_characters(profile_id)
        if existing:
            return existing

        starters = []
        for tmpl in _STARTER_TEMPLATES:
            c = self.create_character(
                profile_id=profile_id,
                name=tmpl["name"],
                canonical_description=tmpl["canonical_description"],
                avatar_emoji=tmpl["avatar_emoji"],
                is_starter=True,
            )
            starters.append(c)

        # 4th starter: the child as a character
        child_char = self.create_character(
            profile_id=profile_id,
            name=child_name,
            canonical_description=(
                f"a {child_age}-year-old child with a bright smile and adventurous spirit"
            ),
            avatar_emoji="🧒",
            is_starter=True,
        )
        starters.append(child_char)
        return starters

    def get_most_used_in_window(
        self, profile_id: int, days: int = 7
    ) -> Optional[Character]:
        """Most-featured character from story_history in the last N days."""
        with self._connect() as conn:
            # story_history.characters is a JSON array of character_ids
            # We join via LIKE as a lightweight check for V1 (small dataset)
            rows = conn.execute(
                """SELECT c.character_id, c.times_featured
                   FROM characters c
                   WHERE c.profile_id = ?
                     AND c.last_featured_at >= datetime('now', ?)
                   ORDER BY c.times_featured DESC
                   LIMIT 1""",
                (profile_id, f"-{days} days"),
            ).fetchone()
        return self.get_character(rows["character_id"]) if rows else None

    def count(self, profile_id: int) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM characters WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        return row["n"] if row else 0
