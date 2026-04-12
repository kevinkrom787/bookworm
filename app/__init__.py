from flask import Flask, request
from config import Config


def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    config_class.ensure_dirs()

    # Register route blueprints
    from app.routes import library, reader, flashcards
    app.register_blueprint(library.bp)
    app.register_blueprint(reader.bp)
    app.register_blueprint(flashcards.bp)

    # Cache static assets for 1 hour in the browser
    @app.after_request
    def add_cache_headers(response):
        if request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "public, max-age=3600"
        return response

    return app
