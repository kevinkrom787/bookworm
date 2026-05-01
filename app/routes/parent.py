"""
Parent dashboard — /parent

No link from the kid UI. Shows reading activity, vocabulary progress,
and quiz history. PIN protection can be added later.
"""

import json
import sqlite3
from flask import Blueprint, render_template, current_app, session, abort
from app.services.flashcard_service import FlashcardService
from app.services.gutenberg import GutenbergService

bp = Blueprint("parent", __name__, url_prefix="/parent")

_ADMIN_EMAIL = "kevin@unstructured.io"


@bp.route("/admin")
def admin():
    db_path = current_app.config["DB_PATH"]
    # Gate: look up the logged-in family's email
    family_id = session.get("family_id")
    if not family_id:
        abort(403)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT email FROM families WHERE id = ?", (family_id,)).fetchone()
    if not row or row["email"].lower() != _ADMIN_EMAIL:
        conn.close()
        actual = row["email"] if row else "unknown"
        abort(403, description=f"Admin requires {_ADMIN_EMAIL!r}. You're logged in as {actual!r}.")

    families = conn.execute("""
        SELECT
            f.id, f.name, f.email, f.plan,
            strftime('%Y-%m-%d', f.created_at) AS joined,
            COUNT(DISTINCT cp.id)              AS profiles,
            COUNT(DISTINCT sh.story_id)        AS stories,
            strftime('%Y-%m-%d', MAX(sh.created_at)) AS last_story
        FROM families f
        LEFT JOIN child_profiles cp ON cp.family_id = f.id
        LEFT JOIN story_history  sh ON sh.profile_id = cp.id
        GROUP BY f.id
        ORDER BY f.created_at DESC
    """).fetchall()
    conn.close()

    return render_template("parent/admin.html", families=families)


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
