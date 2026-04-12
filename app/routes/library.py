from flask import Blueprint, jsonify, render_template, request, current_app
from app.services.gutenberg import GutenbergService

bp = Blueprint("library", __name__, url_prefix="/library")


def _gutenberg() -> GutenbergService:
    return GutenbergService(current_app.config["BOOK_CACHE_DIR"])


@bp.route("/")
def index():
    age_band = request.args.get("band", current_app.config["DEFAULT_AGE_BAND"])
    return render_template("library/index.html", age_band=age_band)


# ------------------------------------------------------------------ JSON APIs
# The library page loads books asynchronously via these endpoints.

@bp.route("/api/featured")
def featured():
    try:
        books = _gutenberg().get_featured_books()
        return jsonify({"books": [_to_dict(b) for b in books]})
    except Exception as e:
        return jsonify({"error": str(e), "books": []}), 200  # soft fail for UI


@bp.route("/api/search")
def search():
    query = request.args.get("q", "").strip()
    page = max(1, int(request.args.get("page", 1)))
    if not query:
        return jsonify({"books": [], "total": 0, "next_page": None})
    try:
        results = _gutenberg().search(query, page=page)
        return jsonify({
            "books": [_to_dict(b) for b in results.books],
            "total": results.total,
            "next_page": results.next_page,
        })
    except Exception as e:
        return jsonify({"error": str(e), "books": [], "total": 0}), 200


@bp.route("/api/book/<int:book_id>")
def book_detail(book_id: int):
    try:
        meta = _gutenberg().get_book(book_id)
        if not meta:
            return jsonify({"error": "Not found"}), 404
        return jsonify(_to_dict(meta))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _to_dict(book) -> dict:
    return {
        "id": book.id,
        "title": book.title,
        "authors": book.authors,
        "subjects": book.subjects[:5],  # cap subjects to keep response small
        "cover_url": book.cover_url,
        "download_count": book.download_count,
        "languages": book.languages,
    }
