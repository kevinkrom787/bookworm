"""
Story builder — orchestrates the full My Story pipeline:
  profile fetch → virtue rotation → prompt assembly →
  AI call → per-page moderation → image dispatch → DB write
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Optional

_MAX_JSON_RETRIES = 2

log = logging.getLogger(__name__)

VIRTUES = [
    "courage", "honesty", "kindness", "perseverance", "curiosity",
    "patience", "generosity", "forgiveness", "humility", "fairness",
]

LENGTH_BUCKETS: dict[str, dict] = {
    "short":  {"words": 300,  "pages": 8,  "label": "Short (5 min)"},
    "medium": {"words": 700,  "pages": 12, "label": "Just right (10 min)"},
    "long":   {"words": 1200, "pages": 18, "label": "Long (15 min)"},
}

STORY_TYPES = [
    {"key": "adventure", "label": "Adventure", "emoji": "🌋"},
    {"key": "funny",     "label": "Funny",     "emoji": "😄"},
    {"key": "mystery",   "label": "Mystery",   "emoji": "🔍"},
    {"key": "cozy",      "label": "Cozy",      "emoji": "🌙"},
    {"key": "brave",     "label": "Brave",     "emoji": "🦁"},
]

_MODERATION_FALLBACK = (
    "The friends looked at each other and smiled. "
    "Sometimes the best adventures are the quiet ones, "
    "when you stop and notice how beautiful the world already is."
)

_MILD_WORDS  = {"kill", "die", "dead", "stupid", "idiot", "blood", "gun", "weapon"}
_ALERT_WORDS = {"sex", "naked", "drugs", "alcohol", "murder", "abuse", "suicide", "porn", "violence"}


def _moderation_tier(text: str) -> str:
    lower = text.lower()
    if any(w in lower for w in _ALERT_WORDS):
        return "alert"
    if any(w in lower for w in _MILD_WORDS):
        return "mild"
    return "ok"


class StoryBuilder:
    def __init__(self, db_path: Path, config):
        self.db_path = db_path
        self.config  = config

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _get_ai(self):
        from app.ai_provider import get_ai_provider
        return get_ai_provider(self.config)

    def _get_img(self):
        from app.image_provider import get_image_provider
        return get_image_provider(self.config)

    # ── Public entry points ────────────────────────────────────────────────

    def create_placeholder(
        self,
        profile_id: int,
        character_ids: list[int],
        story_type: str,
        length_bucket: str,
    ) -> int:
        """Insert a 'generating' row and return the story_id immediately."""
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO story_history
                       (profile_id, title, characters, story_type, length_bucket,
                        generation_status)
                   VALUES (?, 'Generating…', ?, ?, ?, 'generating')""",
                (profile_id, json.dumps(character_ids), story_type, length_bucket),
            )
        return cur.lastrowid

    def build_async(self, story_id: int, profile, character_ids: list[int],
                    story_type: str, length_bucket: str) -> None:
        """Kick off generation in a background thread."""
        from flask import current_app
        app = current_app._get_current_object()

        def _run():
            with app.app_context():
                try:
                    self._build(story_id, profile, character_ids, story_type, length_bucket)
                except Exception as exc:
                    log.error("Story build failed for story_id=%s: %s", story_id, exc)
                    self._set_status(story_id, "error")

        threading.Thread(target=_run, daemon=True).start()

    # ── Core pipeline ──────────────────────────────────────────────────────

    def _build(
        self, story_id: int, profile,
        character_ids: list[int], story_type: str, length_bucket: str,
    ) -> None:
        from app.services.character_service import CharacterService
        char_svc = CharacterService(self.db_path)
        ai       = self._get_ai()
        img      = self._get_img()

        characters = [char_svc.get_character(cid) for cid in character_ids]
        characters = [c for c in characters if c is not None]

        virtue       = self._rotate_virtue(profile.id)
        system_prompt = _load_system_prompt(profile.age)
        user_prompt   = self._assemble_user_prompt(
            profile, characters, virtue, story_type, length_bucket
        )

        story_json = None
        for attempt in range(_MAX_JSON_RETRIES + 1):
            raw = ai.complete(system=system_prompt, user=user_prompt, max_tokens=4096)
            try:
                story_json = _parse_json(raw)
                break
            except (json.JSONDecodeError, ValueError) as exc:
                if attempt < _MAX_JSON_RETRIES:
                    log.warning("JSON parse failed (attempt %d) for story_id=%s, retrying: %s",
                                attempt + 1, story_id, exc)
                else:
                    raise

        moderation_events = []
        clean_pages       = []
        stopped           = False

        all_pages = story_json.get("pages", [])
        page_text_by_num = {p["page_number"]: p["text"] for p in all_pages}

        for page in all_pages:
            tier = _moderation_tier(page["text"])

            if tier == "alert":
                moderation_events.append(
                    {"page": page["page_number"], "tier": "alert", "action": "stop"}
                )
                log.warning("MODERATION ALERT on story_id=%s page=%s", story_id, page["page_number"])
                stopped = True
                break

            if tier == "mild":
                pn   = page["page_number"]
                prev = page_text_by_num.get(pn - 1, "")
                nxt  = page_text_by_num.get(pn + 1, "")
                ctx  = (
                    f"Story title: {story_json.get('title', '')}\n"
                    f"Characters: {', '.join(c.name for c in characters)}\n"
                    + (f"Page {pn-1}: {prev}\n" if prev else "")
                    + f"Page {pn} (rewrite this): {page['text']}\n"
                    + (f"Page {pn+1}: {nxt}\n" if nxt else "")
                )
                regen = ai.complete(
                    system="You are a children's bedtime story editor. Rewrite only the flagged page so it flows naturally before and after the surrounding pages. Same plot point, same characters, same tone — only remove any language that is not appropriate for young children. Return only the rewritten page text, no commentary.",
                    user=ctx,
                    max_tokens=512,
                )
                if _moderation_tier(regen) != "ok":
                    page["text"] = _MODERATION_FALLBACK
                    moderation_events.append(
                        {"page": page["page_number"], "tier": tier, "action": "fallback"}
                    )
                else:
                    page["text"] = regen.strip()
                    moderation_events.append(
                        {"page": page["page_number"], "tier": tier, "action": "regenerated"}
                    )

            clean_pages.append(page)

        story_json["pages"] = clean_pages
        final_status = "stopped" if stopped else "ready"

        # Update the placeholder row with the full story
        model_name = getattr(ai, "MODEL", "unknown")
        with self._connect() as conn:
            conn.execute(
                """UPDATE story_history SET
                       title             = ?,
                       virtue_focus      = ?,
                       vocabulary_used   = ?,
                       model_used        = ?,
                       full_story_json   = ?,
                       moderation_events = ?,
                       generation_status = ?
                   WHERE story_id = ?""",
                (
                    story_json.get("title", "My Story"),
                    virtue,
                    json.dumps(story_json.get("vocabulary_used", [])),
                    model_name,
                    json.dumps(story_json),
                    json.dumps(moderation_events),
                    final_status,
                    story_id,
                ),
            )

        if stopped:
            return

        # Increment featured count for each character
        for c in characters:
            char_svc.increment_featured(c.character_id)

        # Dispatch story images + character portrait in parallel
        scenes = story_json.get("illustration_scenes", [])
        if img.is_configured() and self._check_budget(profile.id) != "stop":
            log.info("Dispatching %d image(s) for story_id=%s via %s",
                     len(scenes), story_id, type(img).__name__)
            self._dispatch_images(story_id, scenes, profile.id, characters, img)
            # Generate group portrait alongside story images (fire-and-forget)
            from app.services.portrait_service import PortraitService
            PortraitService(self.db_path, self.config).ensure_portrait_async(
                [c.character_id for c in characters], characters
            )
        else:
            log.info("Skipping images for story_id=%s — provider configured=%s budget=%s",
                     story_id, img.is_configured(), self._check_budget(profile.id))

    def _set_status(self, story_id: int, status: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE story_history SET generation_status = ? WHERE story_id = ?",
                (status, story_id),
            )

    # ── Virtue rotation ────────────────────────────────────────────────────

    def _rotate_virtue(self, profile_id: int) -> str:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT last_virtues_used FROM virtue_rotation WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        used   = json.loads(row["last_virtues_used"]) if row else []
        window = used[-3:]

        available = [v for v in VIRTUES if v not in window] or VIRTUES
        import random
        virtue = random.choice(available)

        window_new = (used + [virtue])[-10:]
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO virtue_rotation (profile_id, last_virtues_used)
                   VALUES (?, ?)
                   ON CONFLICT(profile_id) DO UPDATE SET last_virtues_used = excluded.last_virtues_used""",
                (profile_id, json.dumps(window_new)),
            )
        return virtue

    # ── Prompt assembly ────────────────────────────────────────────────────

    def _assemble_user_prompt(
        self, profile, characters: list, virtue: str,
        story_type: str, length_bucket: str,
    ) -> str:
        length_info = LENGTH_BUCKETS.get(length_bucket, LENGTH_BUCKETS["medium"])
        word_count  = length_info["words"]
        page_count  = length_info["pages"]

        level_map = {
            "seedlings":   "early reader — very simple vocabulary, short sentences",
            "explorers":   "mid-level reader — clear vocabulary, moderate sentence length",
            "adventurers": "confident reader — richer vocabulary, varied sentence structure",
        }
        reading_level = level_map.get(profile.age_band, "mid-level reader")
        from app.services.profile_service import INTERESTS as _INTEREST_LIST
        _interest_label = {i["key"]: i["label"] for i in _INTEREST_LIST}
        interests = ", ".join(
            _interest_label.get(k, k) for k in profile.interests
        ) if profile.interests else "adventures, animals"

        fun_facts = profile.fun_facts or {}
        pet_name  = fun_facts.get("pet_name", "").strip()
        pet_type  = fun_facts.get("pet_type", "").strip()
        siblings  = fun_facts.get("siblings", "").strip()
        fav_food  = fun_facts.get("fav_food", "").strip()

        personal_lines = []
        if pet_type and pet_type != "other":
            if pet_name:
                personal_lines.append(f"Pet: {pet_name} the {pet_type}")
            else:
                personal_lines.append(f"Pet: a {pet_type} (no name given)")
        elif pet_type == "other":
            if pet_name:
                personal_lines.append(f"Pet: {pet_name} (some kind of animal)")
            else:
                personal_lines.append("Pet: some kind of animal (no name given)")
        elif pet_name:
            personal_lines.append(f"Pet: {pet_name}")
        if siblings:
            personal_lines.append(f"Siblings: {siblings}")
        if fav_food:
            personal_lines.append(f"Favorite food: {fav_food}")
        personal_str = "\n".join(f"- {l}" for l in personal_lines) if personal_lines else "(none provided)"

        char_lines = "\n".join(
            f"- {c.name}: {c.canonical_description}" for c in characters
        ) if characters else "- (no specific characters; invent engaging ones)"

        vocab_words: list[str] = []
        try:
            from app.services.flashcard_service import FlashcardService
            fc    = FlashcardService(self.db_path)
            words = fc.get_vocab_words(age_band=profile.age_band, user_id="default")
            vocab_words = [w["word"] for w in words if w.get("in_deck") and not w.get("mastered")][:5]
        except Exception:
            pass

        vocab_str = "\n".join(f"- {w}" for w in vocab_words) if vocab_words else "(none this session)"

        return (
            f"## About tonight's reader\n"
            f"Name: {profile.name}, age {profile.age}\n"
            f"Reading level: {reading_level}\n"
            f"Interests: {interests}\n"
            f"Personal details (use these IN the story — not as background, as fuel):\n{personal_str}\n"
            f"Vocabulary currently practicing:\n{vocab_str}\n"
            f"Tonight's virtue focus: {virtue}\n\n"
            f"## Tonight's story\n"
            f"Characters to feature:\n{char_lines}\n"
            f"Story type: {story_type}\n"
            f"Target length: {word_count} words, roughly {page_count} pages"
        )

    # ── Image dispatch ─────────────────────────────────────────────────────

    def _dispatch_images(
        self, story_id: int, scenes: list[dict],
        profile_id: int, characters: list, img,
    ) -> None:
        # Serialize all _attach_image calls — each does a read-modify-write on
        # full_story_json, so concurrent workers would drop each other's writes.
        attach_lock = threading.Lock()

        def generate_one(scene: dict) -> None:
            try:
                char_names  = scene.get("characters_present", [])
                char_descs  = [
                    f"{c.name}: {c.canonical_description}"
                    for c in characters if c.name in char_names
                ]
                style       = characters[0].style_descriptor if characters else (
                    "bold children's book illustration, thick expressive ink outlines, "
                    "vivid jewel-tone colors, richly detailed environments, "
                    "exaggerated expressive faces, dynamic poses, sense of wonder"
                )
                scene_desc  = scene["scene_description"]
                prompt      = (
                    f"{style}. {scene_desc}. "
                    + (f"Characters: {'; '.join(char_descs)}. " if char_descs else "")
                    + "Child-safe, warm, inviting. No text or letters in the image. "
                    + "Composition: main subject(s) positioned in the upper two-thirds of the frame; "
                    + "lower third is simple open background (sky, ground, grass, or floor) with no characters or important details."
                )
                cache_key   = _cache_key(profile_id, scene.get("page_number", 0), prompt)

                with self._connect() as conn:
                    cached = conn.execute(
                        "SELECT image_url FROM portrait_cache WHERE cache_key = ?",
                        (cache_key,),
                    ).fetchone()
                    if cached:
                        conn.execute(
                            "UPDATE portrait_cache SET last_used_at = datetime('now') WHERE cache_key = ?",
                            (cache_key,),
                        )
                        with attach_lock:
                            self._attach_image(story_id, scene["page_number"], cached["image_url"])
                        return

                result = img.generate(prompt)
                if result.ok:
                    from app.image_provider import cache_image_locally
                    image_cache_dir = (self.config.get("IMAGE_CACHE_DIR")
                                       if isinstance(self.config, dict)
                                       else getattr(self.config, "IMAGE_CACHE_DIR", None))
                    local_url = cache_image_locally(result.url, image_cache_dir) if image_cache_dir else result.url
                    with self._connect() as conn:
                        conn.execute(
                            """INSERT OR IGNORE INTO portrait_cache
                                   (cache_key, profile_id, scene_hash, image_url, provider_used)
                               VALUES (?, ?, ?, ?, ?)""",
                            (cache_key, profile_id, cache_key[:16],
                             local_url, type(img).__name__),
                        )
                    with attach_lock:
                        self._attach_image(story_id, scene["page_number"], local_url)
                    self._track_image_spend(profile_id)
            except Exception as exc:
                log.warning("Image job failed for story_id=%s page=%s: %s",
                            story_id, scene.get("page_number"), exc)

        with ThreadPoolExecutor(max_workers=3) as pool:
            pool.map(generate_one, scenes[:10])  # 10-image per-session cap

    def _attach_image(self, story_id: int, page_number: int, image_url: str) -> None:
        """Write image_url into the page entry inside full_story_json."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT full_story_json FROM story_history WHERE story_id = ?",
                (story_id,),
            ).fetchone()
            if not row:
                return
            data = json.loads(row["full_story_json"])
            for p in data.get("pages", []):
                if p["page_number"] == page_number:
                    p["image_url"] = image_url
                    break
            conn.execute(
                "UPDATE story_history SET full_story_json = ? WHERE story_id = ?",
                (json.dumps(data), story_id),
            )

    def _track_image_spend(self, profile_id: int, cost: float = 0.003) -> None:
        month = date.today().strftime("%Y-%m")
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO cloud_spend (profile_id, month, image_spend)
                   VALUES (?, ?, ?)
                   ON CONFLICT(profile_id, month) DO UPDATE SET
                       image_spend  = image_spend + excluded.image_spend,
                       last_updated = datetime('now')""",
                (profile_id, month, cost),
            )

    def _check_budget(self, profile_id: int) -> str:
        """Returns 'ok', 'warn', or 'stop'."""
        _get = (lambda k, d=None: self.config.get(k, d)) if isinstance(self.config, dict) else (lambda k, d=None: getattr(self.config, k, d))
        budget = float(_get("MONTHLY_IMAGE_BUDGET", 5.0) or 5.0)
        month  = date.today().strftime("%Y-%m")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT image_spend FROM cloud_spend WHERE profile_id = ? AND month = ?",
                (profile_id, month),
            ).fetchone()
        if not row:
            return "ok"
        spent = row["image_spend"]
        if spent >= budget:
            return "stop"
        if spent >= budget * 0.8:
            return "warn"
        return "ok"

    # ── Story lifecycle ────────────────────────────────────────────────────

    def complete_story(self, story_id: int, profile_id: int) -> None:
        """Mark story completed, populate vocab_encounters, update streaks."""
        from app.services.streak_service import StreakService
        svc = StreakService(self.db_path)

        with self._connect() as conn:
            conn.execute(
                "UPDATE story_history SET completed = 1 WHERE story_id = ? AND profile_id = ?",
                (story_id, profile_id),
            )
            row = conn.execute(
                "SELECT vocabulary_used FROM story_history WHERE story_id = ?",
                (story_id,),
            ).fetchone()

        if row:
            words = json.loads(row["vocabulary_used"])
            with self._connect() as conn:
                for entry in words:
                    word = entry["word"] if isinstance(entry, dict) else entry
                    conn.execute(
                        """INSERT INTO vocab_encounters (profile_id, word, story_id)
                           VALUES (?, ?, ?)""",
                        (profile_id, word.lower().strip(), story_id),
                    )
        svc.update_on_complete(profile_id)

    def save_to_library(self, story_id: int, profile_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE story_history SET saved_to_library = 1 WHERE story_id = ? AND profile_id = ?",
                (story_id, profile_id),
            )

    def get_story_data(self, story_id: int) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM story_history WHERE story_id = ?",
                (story_id,),
            ).fetchone()
        if not row:
            return None
        data                      = dict(row)
        data["full_story_json"]   = json.loads(data["full_story_json"])
        data["characters"]        = json.loads(data["characters"])
        data["vocabulary_used"]   = json.loads(data["vocabulary_used"])
        data["moderation_events"] = json.loads(data["moderation_events"])
        return data

    def get_generation_status(self, story_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT generation_status FROM story_history WHERE story_id = ?",
                (story_id,),
            ).fetchone()
        return row["generation_status"] if row else None

    def get_last_story_type(self, profile_id: int) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                """SELECT story_type FROM story_history
                   WHERE profile_id = ? AND generation_status = 'ready'
                   ORDER BY created_at DESC LIMIT 1""",
                (profile_id,),
            ).fetchone()
        return row["story_type"] if row else None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _load_system_prompt(age: int) -> str:
    path = Path(__file__).parent.parent / "templates" / "prompts" / "bedtime_story.txt"
    return path.read_text(encoding="utf-8").replace("{AGE}", str(age))


def _parse_json(raw: str) -> dict:
    """Extract and parse JSON from LLM output, tolerating fences and preamble."""
    text = raw.strip()
    # Strip markdown code fences (```json ... ``` or ``` ... ```)
    text = re.sub(r'^```(?:json)?\s*\n?', '', text, flags=re.MULTILINE)
    text = re.sub(r'\n?```\s*$', '', text, flags=re.MULTILINE)
    text = text.strip()
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Fall back: carve out the outermost { ... } block
    start = text.find('{')
    end   = text.rfind('}')
    if start != -1 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("No valid JSON object found in LLM output")


def _cache_key(profile_id: int, page_number: int, prompt: str) -> str:
    h = hashlib.sha256(f"{profile_id}:{page_number}:{prompt}".encode()).hexdigest()
    return h[:32]
