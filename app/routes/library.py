from flask import Blueprint, jsonify, render_template, request, current_app
from app.services.gutenberg import GutenbergService
from app.services.flashcard_service import FlashcardService

bp = Blueprint("library", __name__, url_prefix="/library")


def _gutenberg() -> GutenbergService:
    return GutenbergService(current_app.config["BOOK_CACHE_DIR"])

def _progress() -> FlashcardService:
    return FlashcardService(current_app.config["DB_PATH"])


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


@bp.route("/api/my-books")
def my_books():
    """Books already downloaded to this device, most-recently-opened first."""
    cache_dir = current_app.config["BOOK_CACHE_DIR"]
    svc       = _gutenberg()
    prog_svc  = _progress()

    epub_files = sorted(
        cache_dir.glob("*.epub"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    books = []
    for epub_path in epub_files:
        try:
            book_id = int(epub_path.stem)
        except ValueError:
            continue
        meta = svc.get_book(book_id)
        if not meta:
            continue
        progress = prog_svc.get_reading_progress(book_id)
        entry = _to_dict(meta)
        entry["progress"] = progress  # {chapter_index, word_index} or None
        books.append(entry)

    return jsonify({"books": books})


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
