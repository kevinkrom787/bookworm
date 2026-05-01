from pathlib import Path
from flask import Flask, redirect, request, session, url_for
from config import Config

_AUTH_EXEMPT = ("/auth/", "/static/")


def _run_migrations(db_path: Path) -> None:
    import sqlite3
    migrations_dir = Path(__file__).parent.parent / "migrations"
    if not migrations_dir.exists():
        return
    conn = sqlite3.connect(str(db_path))
    try:
        for sql_file in sorted(migrations_dir.glob("*.sql")):
            for stmt in sql_file.read_text(encoding="utf-8").split(";"):
                # Strip comment lines before emptiness check so leading comments
                # don't cause statements like "-- note\nALTER TABLE..." to be skipped
                stmt = "\n".join(
                    l for l in stmt.splitlines() if not l.strip().startswith("--")
                ).strip()
                if not stmt:
                    continue
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as exc:
                    # Ignore "duplicate column name" so ALTER TABLE is idempotent
                    if "duplicate column name" not in str(exc).lower():
                        raise
        conn.commit()
    finally:
        conn.close()


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Trust Fly.io's proxy so url_for() generates https:// URLs
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
    config_class.ensure_dirs()
    _run_migrations(config_class.DB_PATH)

    # Google OAuth
    from app.extensions import oauth
    oauth.init_app(app)
    if app.config.get("GOOGLE_CLIENT_ID"):
        oauth.register(
            name="google",
            client_id=app.config["GOOGLE_CLIENT_ID"],
            client_secret=app.config["GOOGLE_CLIENT_SECRET"],
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )

    # Register route blueprints
    from app.routes import (library, reader, flashcards, parent,
                            profiles as profiles_bp, stories as stories_bp,
                            auth as auth_bp)
    app.register_blueprint(auth_bp.bp)
    app.register_blueprint(library.bp)
    app.register_blueprint(reader.bp)
    app.register_blueprint(flashcards.bp)
    app.register_blueprint(parent.bp)
    app.register_blueprint(profiles_bp.bp)
    app.register_blueprint(stories_bp.bp)

    @app.before_request
    def require_family_session():
        if any(request.path.startswith(p) for p in _AUTH_EXEMPT):
            return None
        if "family_id" not in session:
            return redirect(url_for("auth.login", next=request.path))

    @app.context_processor
    def inject_profile():
        return {
            "active_profile_id":   session.get("profile_id"),
            "active_profile_name": session.get("profile_name"),
            "active_age_band":     session.get("age_band", config_class.DEFAULT_AGE_BAND),
            "current_family_name": session.get("family_name", ""),
        }

    @app.after_request
    def add_cache_headers(response):
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    return app
