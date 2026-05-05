"""
Profile routes — /profiles/
"""
from flask import (Blueprint, jsonify, redirect, render_template,
                   request, session, url_for, current_app)
from app.services.profile_service import ProfileService, INTERESTS, AVATARS, COLORS
from app import analytics

bp = Blueprint("profiles", __name__, url_prefix="/profiles")


def _svc() -> ProfileService:
    return ProfileService(current_app.config["DB_PATH"])


def _fid() -> int:
    return session.get("family_id")


def active_band() -> str:
    """Return the active profile's age band, falling back to config default."""
    return session.get("age_band", current_app.config["DEFAULT_AGE_BAND"])


# ── Page routes ───────────────────────────────────────────────────────────────

@bp.route("/")
def select():
    profiles = _svc().list_profiles(family_id=_fid())
    if not profiles:
        return redirect(url_for("profiles.new"))
    return render_template("profiles/select.html", profiles=profiles)


@bp.route("/new")
def new():
    return render_template("profiles/setup.html",
                           interests=INTERESTS, avatars=AVATARS, colors=COLORS,
                           profile=None)


@bp.route("/<int:profile_id>/edit")
def edit(profile_id: int):
    profile = _svc().get_profile(profile_id, family_id=_fid())
    if not profile:
        return redirect(url_for("profiles.select"))
    return render_template("profiles/setup.html",
                           interests=INTERESTS, avatars=AVATARS, colors=COLORS,
                           profile=profile)


# ── JSON APIs ─────────────────────────────────────────────────────────────────

@bp.route("/api", methods=["POST"])
def api_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    profile = _svc().create_profile(
        name=name,
        age=int(data.get("age", 7)),
        avatar_emoji=data.get("avatar_emoji", "🦁"),
        avatar_color=data.get("avatar_color", "#6C8EF5"),
        interests=data.get("interests", []),
        fun_facts=data.get("fun_facts", {}),
        family_id=_fid(),
    )
    _set_session(profile)
    analytics.capture(_fid(), "profile_created", {"age_band": profile.age_band})
    return jsonify(profile.to_dict()), 201


@bp.route("/api/<int:profile_id>", methods=["PUT"])
def api_update(profile_id: int):
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Name is required"}), 400
    profile = _svc().update_profile(
        profile_id=profile_id,
        name=name,
        age=int(data.get("age", 7)),
        avatar_emoji=data.get("avatar_emoji", "🦁"),
        avatar_color=data.get("avatar_color", "#6C8EF6"),
        interests=data.get("interests", []),
        fun_facts=data.get("fun_facts", {}),
        family_id=_fid(),
    )
    if not profile:
        return jsonify({"error": "Not found"}), 404
    if session.get("profile_id") == profile_id:
        _set_session(profile)
    return jsonify(profile.to_dict())


@bp.route("/api/<int:profile_id>/activate", methods=["POST"])
def api_activate(profile_id: int):
    profile = _svc().get_profile(profile_id, family_id=_fid())
    if not profile:
        return jsonify({"error": "Not found"}), 404
    _set_session(profile)
    return jsonify({"ok": True})


@bp.route("/api/<int:profile_id>", methods=["DELETE"])
def api_delete(profile_id: int):
    deleted = _svc().delete_profile(profile_id, family_id=_fid())
    if session.get("profile_id") == profile_id:
        session.pop("profile_id", None)
        session.pop("profile_name", None)
        session.pop("age_band", None)
    return jsonify({"deleted": deleted})


def _set_session(profile) -> None:
    session["profile_id"]   = profile.id
    session["profile_name"] = profile.name
    session["age_band"]     = profile.age_band
    session.permanent       = True
