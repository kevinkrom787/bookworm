"""
Auth routes — /auth/
Google OAuth is the primary path. Email/password routes kept as fallback.
"""
from flask import (Blueprint, redirect, render_template,
                   request, session, url_for, current_app)
from app.services.family_service import FamilyService
from app.extensions import oauth

bp = Blueprint("auth", __name__, url_prefix="/auth")

_GUEST_COOKIE = "atlas_guest"
_GUEST_COOKIE_AGE = 365 * 24 * 3600  # 1 year


def _svc() -> FamilyService:
    return FamilyService(current_app.config["DB_PATH"])


def _profiles_for(family_id: int) -> list:
    from app.services.profile_service import ProfileService
    return ProfileService(current_app.config["DB_PATH"]).list_profiles(family_id)


# ── Main login page ────────────────────────────────────────────────────────────

@bp.route("/login", methods=["GET"])
def login():
    if "family_id" in session:
        return redirect(url_for("profiles.select"))
    google_enabled = bool(current_app.config.get("GOOGLE_CLIENT_ID"))
    return render_template("auth/login.html", google_enabled=google_enabled)


# ── Google OAuth ───────────────────────────────────────────────────────────────

@bp.route("/google")
def google_login():
    if not current_app.config.get("GOOGLE_CLIENT_ID"):
        return redirect(url_for("auth.login"))
    redirect_uri = url_for("auth.google_callback", _external=True)
    return oauth.google.authorize_redirect(redirect_uri)


@bp.route("/google/callback")
def google_callback():
    if not current_app.config.get("GOOGLE_CLIENT_ID"):
        return redirect(url_for("auth.login"))
    try:
        token    = oauth.google.authorize_access_token()
        userinfo = token.get("userinfo") or {}
    except Exception:
        return redirect(url_for("auth.login"))

    email = (userinfo.get("email") or "").lower().strip()
    name  = (userinfo.get("name") or email.split("@")[0]).strip()
    if not email:
        return redirect(url_for("auth.login"))

    family = _svc().find_or_create_google(email=email, name=name)
    session["family_id"]   = family.id
    session["family_name"] = family.name
    session.permanent      = True

    profiles = _profiles_for(family.id)
    return redirect(url_for("profiles.select") if profiles else url_for("profiles.new"))


# ── Guest ─────────────────────────────────────────────────────────────────────

def _set_guest_profile_session(family_id: int) -> None:
    """Find or create the guest's single profile and put it in session."""
    from app.services.profile_service import ProfileService
    svc = ProfileService(current_app.config["DB_PATH"])
    profiles = svc.list_profiles(family_id)
    if profiles:
        p = profiles[0]
    else:
        p = svc.create_profile(
            name="Explorer",
            age=8,
            family_id=family_id,
            avatar_emoji="🦄",
            avatar_color="#f97316",
        )
    session["profile_id"]   = p.id
    session["profile_name"] = p.name
    session["age_band"]     = p.age_band


@bp.route("/guest")
def guest():
    # Resume an existing guest account from the persistent cookie
    raw = request.cookies.get(_GUEST_COOKIE, "")
    if raw:
        try:
            fid    = int(raw)
            family = _svc().get_by_id(fid)
            if family and family.plan == "guest":
                session["family_id"]   = family.id
                session["family_name"] = "Guest"
                session.permanent      = True
                _set_guest_profile_session(fid)
                return redirect(url_for("stories.new"))
        except (ValueError, TypeError):
            pass

    # New guest — auto-create family + profile, skip the wizard entirely
    family = _svc().create_guest()
    session["family_id"]   = family.id
    session["family_name"] = "Guest"
    session.permanent      = True
    _set_guest_profile_session(family.id)
    resp = redirect(url_for("stories.new"))
    resp.set_cookie(_GUEST_COOKIE, str(family.id),
                    max_age=_GUEST_COOKIE_AGE, samesite="Lax", httponly=True)
    return resp


# ── Email / password fallback (existing accounts) ─────────────────────────────

@bp.route("/signup", methods=["GET"])
def signup():
    if "family_id" in session:
        return redirect(url_for("profiles.select"))
    return render_template("auth/signup.html")


@bp.route("/signup", methods=["POST"])
def signup_post():
    name     = (request.form.get("name")     or "").strip()
    email    = (request.form.get("email")    or "").strip().lower()
    password = (request.form.get("password") or "")
    confirm  = (request.form.get("confirm")  or "")

    error = None
    if not name or not email or not password:
        error = "All fields are required."
    elif password != confirm:
        error = "Passwords don't match."
    elif len(password) < 8:
        error = "Password must be at least 8 characters."

    if error:
        return render_template("auth/signup.html", error=error, name=name, email=email), 422

    family = _svc().create_family(name=name, email=email, password=password)
    if family is None:
        return render_template("auth/signup.html",
                               error="An account with that email already exists.",
                               name=name, email=email), 422

    session["family_id"]   = family.id
    session["family_name"] = family.name
    session.permanent      = True
    return redirect(url_for("profiles.select"))


@bp.route("/login", methods=["POST"])
def login_post():
    email    = (request.form.get("email")    or "").strip().lower()
    password = (request.form.get("password") or "")

    family = _svc().authenticate(email=email, password=password)
    if not family:
        google_enabled = bool(current_app.config.get("GOOGLE_CLIENT_ID"))
        return render_template("auth/login.html",
                               error="Incorrect email or password.",
                               email=email,
                               google_enabled=google_enabled), 401

    session["family_id"]   = family.id
    session["family_name"] = family.name
    session.permanent      = True

    next_url = request.args.get("next", "")
    return redirect(next_url if next_url.startswith("/") else url_for("profiles.select"))


# ── Logout ────────────────────────────────────────────────────────────────────

@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
