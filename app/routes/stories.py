"""
Story routes — /stories/
"""
from flask import (Blueprint, jsonify, redirect, render_template,
                   request, session, url_for, current_app, g)

from app.services.profile_service import ProfileService
from app.services.character_service import CharacterService
from app.services.streak_service import StreakService
from app.services.story_builder import StoryBuilder, STORY_TYPES, LENGTH_BUCKETS
from app.routes.profiles import active_band

bp = Blueprint("stories", __name__, url_prefix="/stories")


# ── Service helpers ────────────────────────────────────────────────────────────

def _builder() -> StoryBuilder:
    if "story_builder" not in g:
        g.story_builder = StoryBuilder(
            db_path=current_app.config["DB_PATH"],
            config=current_app.config,
        )
    return g.story_builder


def _char_svc() -> CharacterService:
    if "char_svc" not in g:
        g.char_svc = CharacterService(current_app.config["DB_PATH"])
    return g.char_svc


def _streak_svc() -> StreakService:
    if "streak_svc" not in g:
        g.streak_svc = StreakService(current_app.config["DB_PATH"])
    return g.streak_svc


def _active_profile():
    pid = session.get("profile_id")
    fid = session.get("family_id")
    if not pid or not fid:
        return None
    return ProfileService(current_app.config["DB_PATH"]).get_profile(pid, family_id=fid)


# ── Bedtime story flow ─────────────────────────────────────────────────────────

@bp.route("/")
def index():
    return redirect(url_for("stories.new"))

@bp.route("/new")
def new():
    """Setup screen — Screen 1."""
    profile = _active_profile()
    if not profile:
        return redirect(url_for("profiles.select"))

    char_svc   = _char_svc()
    characters = char_svc.get_characters(profile.id)

    # Seed starters if library is empty
    if not characters:
        characters = char_svc.get_or_create_starters(profile.id, profile.name, profile.age)

    # Pre-select most-used character from last 7 nights
    preselected_char_id = None
    top = char_svc.get_most_used_in_window(profile.id, days=7)
    if top:
        preselected_char_id = top.character_id
    elif characters:
        preselected_char_id = characters[0].character_id

    # Pre-select most recently used story type
    last_type    = _builder().get_last_story_type(profile.id)
    preset_types = [t["key"] for t in STORY_TYPES]
    preselected_type = last_type if last_type in preset_types else STORY_TYPES[0]["key"]

    return render_template(
        "stories/setup.html",
        profile=profile,
        characters=[c.to_dict() for c in characters],
        story_types=STORY_TYPES,
        length_buckets=LENGTH_BUCKETS,
        preselected_char_id=preselected_char_id,
        preselected_type=preselected_type,
    )


@bp.route("/start", methods=["POST"])
def start():
    """Kick off generation. Returns immediately; generation runs in background."""
    profile = _active_profile()
    if not profile:
        return redirect(url_for("profiles.select"))

    data         = request.form
    char_ids_raw = request.form.getlist("character_ids")
    character_ids = [int(x) for x in char_ids_raw if x.isdigit()][:3]
    story_type    = data.get("story_type", "adventure")
    length_bucket = data.get("length_bucket", "medium")

    if not current_app.config.get("ANTHROPIC_API_KEY"):
        return render_template("stories/setup.html",
                               error="ANTHROPIC_API_KEY is not configured.",
                               profile=profile,
                               characters=[c.to_dict() for c in _char_svc().get_characters(profile.id)],
                               story_types=STORY_TYPES,
                               length_buckets=LENGTH_BUCKETS,
                               preselected_char_id=None,
                               preselected_type=story_type)

    builder  = _builder()
    story_id = builder.create_placeholder(
        profile_id=profile.id,
        character_ids=character_ids,
        story_type=story_type,
        length_bucket=length_bucket,
    )
    builder.build_async(story_id, profile, character_ids, story_type, length_bucket)

    return redirect(url_for("stories.generating", story_id=story_id))


@bp.route("/bedtime/<int:story_id>/generating")
def generating(story_id: int):
    """Screen 2 — loading/generating."""
    profile = _active_profile()
    if not profile:
        return redirect(url_for("profiles.select"))

    data = _builder().get_story_data(story_id)
    if not data:
        return redirect(url_for("stories.new"))

    # Gather character names for the "Tonight's story stars…" line
    char_svc   = _char_svc()
    char_names = []
    for cid in data.get("characters", []):
        c = char_svc.get_character(cid)
        if c:
            char_names.append(c.name)

    return render_template(
        "stories/generating.html",
        profile=profile,
        story_id=story_id,
        char_names=char_names,
    )


@bp.route("/bedtime/<int:story_id>/read")
def bedtime_read(story_id: int):
    """Screen 3 — page-by-page story reader."""
    profile = _active_profile()
    if not profile:
        return redirect(url_for("profiles.select"))

    data = _builder().get_story_data(story_id)
    if not data or data["generation_status"] not in ("ready", "stopped"):
        return redirect(url_for("stories.generating", story_id=story_id))

    if data["generation_status"] == "stopped":
        return render_template("stories/moderation_stop.html", profile=profile)

    # Look up the character group portrait for the splash page
    from app.services.portrait_service import PortraitService
    char_ids   = data.get("characters", [])
    char_svc   = _char_svc()
    characters = [c for c in (char_svc.get_character(cid) for cid in char_ids) if c]
    char_names = [c.name for c in characters]

    portrait_svc = PortraitService(current_app.config["DB_PATH"], current_app.config)
    portrait_url = portrait_svc.get_portrait(char_ids) or ""
    # If portrait not ready yet, kick off generation for next time
    if not portrait_url and characters:
        portrait_svc.ensure_portrait_async(char_ids, characters)

    return render_template(
        "stories/bedtime_read.html",
        profile=profile,
        story_id=story_id,
        story=data["full_story_json"],
        portrait_url=portrait_url,
        char_names=char_names,
    )


@bp.route("/bedtime/<int:story_id>/recap")
def recap(story_id: int):
    """Screen 4 — recap."""
    profile = _active_profile()
    if not profile:
        return redirect(url_for("profiles.select"))

    data = _builder().get_story_data(story_id)
    if not data:
        return redirect(url_for("stories.new"))

    streak  = _streak_svc().get_streak(profile.id)
    story_j = data["full_story_json"]
    recap_d = story_j.get("recap", {})
    vocab   = story_j.get("vocabulary_used", [])[:3]
    images  = [p["image_url"] for p in story_j.get("pages", []) if p.get("image_url")][:6]

    return render_template(
        "stories/recap.html",
        profile=profile,
        story_id=story_id,
        title=story_j.get("title", "The End"),
        lesson=recap_d.get("lesson", ""),
        talk_about_it=recap_d.get("talk_about_it", ""),
        vocab_words=vocab,
        streak=streak["days_read_current"],
        images=images,
    )


# ── Bedtime story API ──────────────────────────────────────────────────────────

@bp.route("/api/bedtime/<int:story_id>/status")
def api_status(story_id: int):
    status = _builder().get_generation_status(story_id)
    if status is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"status": status})


@bp.route("/api/bedtime/<int:story_id>/images")
def api_images(story_id: int):
    """Returns current image URLs keyed by page_number. Reader polls this."""
    data = _builder().get_story_data(story_id)
    if not data:
        return jsonify({"images": {}})
    images = {
        str(p["page_number"]): p["image_url"]
        for p in data["full_story_json"].get("pages", [])
        if p.get("image_url")
    }
    return jsonify({"images": images})


@bp.route("/api/bedtime/<int:story_id>/complete", methods=["POST"])
def api_complete(story_id: int):
    profile = _active_profile()
    if not profile:
        return jsonify({"error": "No active profile"}), 401
    _builder().complete_story(story_id, profile.id)
    return jsonify({"ok": True})


@bp.route("/api/bedtime/<int:story_id>/save", methods=["POST"])
def api_save(story_id: int):
    profile = _active_profile()
    if not profile:
        return jsonify({"error": "No active profile"}), 401
    _builder().save_to_library(story_id, profile.id)
    return jsonify({"ok": True})


# ── Characters API ─────────────────────────────────────────────────────────────

@bp.route("/api/characters")
def api_characters():
    profile = _active_profile()
    if not profile:
        return jsonify({"error": "No active profile"}), 401
    chars = _char_svc().get_characters(profile.id)
    return jsonify({"characters": [c.to_dict() for c in chars]})


@bp.route("/api/characters", methods=["POST"])
def api_create_character():
    profile = _active_profile()
    if not profile:
        return jsonify({"error": "No active profile"}), 401
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    char = _char_svc().create_character(
        profile_id=profile.id,
        name=name,
        canonical_description=data.get("canonical_description", ""),
        avatar_emoji=data.get("avatar_emoji", "🐾"),
    )
    return jsonify(char.to_dict()), 201


# ── Stats API (home screen stat bar) ──────────────────────────────────────────

@bp.route("/api/stats")
def api_stats():
    profile = _active_profile()
    if not profile:
        return jsonify({"days_read": 0, "words_saved": 0, "words_tested": 0, "characters": 0})
    return jsonify(_streak_svc().get_stats(profile.id))


