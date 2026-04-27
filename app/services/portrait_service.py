"""
Portrait service — generates and caches character group portraits.

Portraits are keyed by sorted character IDs so they're reused across every
story featuring those same characters. Single character → solo hero portrait.
Multiple characters → side-by-side group portrait.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_SOLO_PREFIX  = "char_portrait_"
_GROUP_PREFIX = "group_portrait_"


class PortraitService:
    def __init__(self, db_path: Path, config):
        self.db_path = db_path
        self.config  = config

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_img(self):
        from app.image_provider import get_image_provider
        return get_image_provider(self.config)

    # ── Public ─────────────────────────────────────────────────────────────

    def get_portrait(self, character_ids: list[int]) -> Optional[str]:
        """Return cached portrait URL, or None if not yet generated."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT image_url FROM portrait_cache WHERE cache_key = ?",
                (self._cache_key(character_ids),),
            ).fetchone()
        return row["image_url"] if row and row["image_url"] else None

    def ensure_portrait_async(self, character_ids: list[int], characters: list) -> None:
        """Fire-and-forget: generate portrait if not cached."""
        if not character_ids or not characters:
            return
        if self.get_portrait(character_ids):
            return
        img = self._get_img()
        if not img.is_configured():
            return
        threading.Thread(
            target=self._generate_and_cache,
            args=(character_ids, characters, img),
            daemon=True,
        ).start()

    # ── Internals ───────────────────────────────────────────────────────────

    def _cache_key(self, character_ids: list[int]) -> str:
        ids = "_".join(str(i) for i in sorted(character_ids))
        prefix = _SOLO_PREFIX if len(character_ids) == 1 else _GROUP_PREFIX
        return f"{prefix}{ids}"

    def _build_prompt(self, characters: list) -> str:
        style = characters[0].style_descriptor if characters else (
            "watercolor children's book illustration, soft warm palette"
        )
        if len(characters) == 1:
            c = characters[0]
            return (
                f"{style}. {c.canonical_description}, facing the viewer with a warm "
                f"heroic expression, centered portrait composition, dramatic warm "
                f"backlighting, lush magical forest background. "
                f"Child-safe, warm, inviting. No text or letters in the image."
            )
        descs = " and ".join(c.canonical_description for c in characters[:3])
        return (
            f"{style}. {descs} standing side by side, all facing the viewer with "
            f"big warm smiles. Side-by-side hero group portrait, centered composition, "
            f"dramatic warm golden backlighting, beautiful magical setting. "
            f"Child-safe, warm, inviting. No text or letters in the image."
        )

    def _image_cache_dir(self):
        if isinstance(self.config, dict):
            return self.config.get("IMAGE_CACHE_DIR")
        return getattr(self.config, "IMAGE_CACHE_DIR", None)

    def _generate_and_cache(self, character_ids: list[int], characters: list, img) -> None:
        cache_key  = self._cache_key(character_ids)
        prompt     = self._build_prompt(characters)
        result     = img.generate(prompt)
        if not result.ok:
            log.warning("Portrait generation failed key=%s: %s", cache_key, result.error)
            return

        from app.image_provider import cache_image_locally
        cache_dir = self._image_cache_dir()
        local_url = cache_image_locally(result.url, cache_dir) if cache_dir else result.url

        profile_id = characters[0].profile_id if characters else 0
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO portrait_cache
                       (cache_key, profile_id, character_id, scene_hash,
                        image_url, provider_used, last_used_at)
                   VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
                (
                    cache_key,
                    profile_id,
                    character_ids[0] if len(character_ids) == 1 else None,
                    cache_key[:16],
                    local_url,
                    type(img).__name__,
                ),
            )
        log.info("Portrait cached key=%s url=%s", cache_key, local_url)
