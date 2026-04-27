"""
Parent dashboard — /parent

No link from the kid UI. Shows reading activity, vocabulary progress,
and quiz history. PIN protection can be added later.
"""

import json
from flask import Blueprint, render_template, current_app, session
from app.services.flashcard_service import FlashcardService
from app.services.gutenberg import GutenbergService

bp = Blueprint("parent", __name__, url_prefix="/parent")


@bp.route("/")
def index():
    db_path   = current_app.config["DB_PATH"]
    cache_dir = current_app.config["BOOK_CACHE_DIR"]
    svc       = FlashcardService(db_path)
    gutenberg = GutenbergService(cache_dir)

    uid = str(session.get("profile_id", "default"))

    # ── Reading progress ──────────────────────────────────────────────
    progress_rows = svc.get_all_reading_progress(user_id=uid)
    books = []
    for row in progress_rows:
        book_id = row["book_id"]
        meta    = gutenberg.get_book(book_id)
        if not meta:
            continue

        total_chapters = _total_chapters(cache_dir, book_id)
        last_read      = row["updated_at"][:10]  # YYYY-MM-DD

        books.append({
            "id":             book_id,
            "title":          meta.title,
            "author":         meta.authors[0] if meta.authors else "",
            "cover_url":      meta.cover_url or "",
            "chapter_index":  row["chapter_index"],
            "chapter_human":  row["chapter_index"] + 1,
            "total_chapters": total_chapters,
            "last_read":      last_read,
        })

    # ── Vocab + quiz summary ──────────────────────────────────────────
    summary = svc.get_parent_summary(user_id=uid)

    return render_template(
        "parent/index.html",
        books=books,
        summary=summary,
    )


def _total_chapters(cache_dir, book_id: int) -> int:
    """Read chapter count from the parsed JSON cache — fast, no EPUB unzip."""
    parsed = cache_dir / f"{book_id}.parsed.json"
    if not parsed.exists():
        return 0
    try:
        data = json.loads(parsed.read_text())
        return len(data.get("chapters", []))
    except Exception:
        return 0
