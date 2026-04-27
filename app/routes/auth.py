"""
Auth routes — /auth/
Handles family account signup, login, and logout.
"""
from flask import (Blueprint, redirect, render_template,
                   request, session, url_for, current_app)
from app.services.family_service import FamilyService

bp = Blueprint("auth", __name__, url_prefix="/auth")


def _svc() -> FamilyService:
    return FamilyService(current_app.config["DB_PATH"])


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


@bp.route("/login", methods=["GET"])
def login():
    if "family_id" in session:
        return redirect(url_for("profiles.select"))
    return render_template("auth/login.html")


@bp.route("/login", methods=["POST"])
def login_post():
    email    = (request.form.get("email")    or "").strip().lower()
    password = (request.form.get("password") or "")

    family = _svc().authenticate(email=email, password=password)
    if not family:
        return render_template("auth/login.html",
                               error="Incorrect email or password.",
                               email=email), 401

    session["family_id"]   = family.id
    session["family_name"] = family.name
    session.permanent      = True

    next_url = request.args.get("next", "")
    return redirect(next_url if next_url.startswith("/") else url_for("profiles.select"))


@bp.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect(url_for("auth.login"))
