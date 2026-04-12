from flask import Blueprint, jsonify, render_template, request, current_app, g
from app.services.flashcard_service import FlashcardService

bp = Blueprint("flashcards", __name__, url_prefix="/flashcards")


def _svc() -> FlashcardService:
    """Lazy-load service once per request context."""
    if "fc_svc" not in g:
        g.fc_svc = FlashcardService(current_app.config["DB_PATH"])
    return g.fc_svc


def _uid() -> str:
    return request.args.get("user_id", "default")


# ── Page routes ───────────────────────────────────────────────────────────────

@bp.route("/")
def index():
    age_band = request.args.get("band", current_app.config["DEFAULT_AGE_BAND"])
    svc = _svc()
    stats       = svc.get_stats()
    word_counts = svc.get_vocab_word_counts(age_band)
    return render_template("flashcards/index.html", age_band=age_band, stats=stats,
                           word_counts=word_counts)


@bp.route("/quiz")
def quiz_setup():
    age_band  = request.args.get("band", current_app.config["DEFAULT_AGE_BAND"])
    card_type = request.args.get("type", "number")
    return render_template("flashcards/quiz.html", age_band=age_band, card_type=card_type)


@bp.route("/review")
def review():
    age_band = request.args.get("band", current_app.config["DEFAULT_AGE_BAND"])
    return render_template(
        "flashcards/review.html",
        age_band=age_band,
        filter_type=request.args.get("type", ""),
        filter_book=request.args.get("book", ""),
        single_card_id=request.args.get("card_id", type=int),
        set_min=request.args.get("set_min", type=int),
        set_max=request.args.get("set_max", type=int),
        set_label=request.args.get("set_label", ""),
        quiz_count=request.args.get("count", type=int),
    )


# ── JSON APIs ─────────────────────────────────────────────────────────────────

@bp.route("/api/cards", methods=["GET"])
def api_list():
    cards = _svc().get_cards(
        user_id=_uid(),
        card_type=request.args.get("type") or None,
        source_book=request.args.get("book") or None,
        due_only=request.args.get("due_only") == "1",
        limit=min(500, int(request.args.get("limit", 200))),
        offset=int(request.args.get("offset", 0)),
    )
    return jsonify({"cards": [c.to_dict() for c in cards]})


@bp.route("/api/cards", methods=["POST"])
def api_create():
    data = request.get_json(silent=True) or {}
    card_type  = (data.get("card_type") or "").strip()
    front_data = data.get("front_data") or {}
    back_data  = data.get("back_data")  or {}

    if not card_type:
        return jsonify({"error": "card_type is required"}), 400
    if not isinstance(front_data, dict) or not isinstance(back_data, dict):
        return jsonify({"error": "front_data and back_data must be objects"}), 400

    card = _svc().create_card(
        card_type=card_type,
        front_data=front_data,
        back_data=back_data,
        source_book=data.get("source_book") or None,
        source_chapter=data.get("source_chapter") or None,
        user_id=data.get("user_id", "default"),
    )
    return jsonify(card.to_dict()), 201


@bp.route("/api/cards/<int:card_id>", methods=["DELETE"])
def api_delete(card_id: int):
    deleted = _svc().delete_card(card_id, user_id=_uid())
    if not deleted:
        return jsonify({"error": "Card not found"}), 404
    return jsonify({"deleted": True})


@bp.route("/api/cards/<int:card_id>/review", methods=["POST"])
def api_review(card_id: int):
    data   = request.get_json(silent=True) or {}
    rating = data.get("rating")
    if rating not in (1, 2, 3):
        return jsonify({"error": "rating must be 1 (Hard), 2 (Good), or 3 (Easy)"}), 400

    result = _svc().submit_review(card_id, rating=rating, user_id=data.get("user_id", "default"))
    if not result:
        return jsonify({"error": "Card not found"}), 404

    return jsonify({
        "card_id":          result.card_id,
        "new_ease_factor":  result.new_ease_factor,
        "new_interval":     result.new_interval,
        "new_repetitions":  result.new_repetitions,
        "new_due_date":     result.new_due_date,
    })


@bp.route("/api/stats", methods=["GET"])
def api_stats():
    s = _svc().get_stats(user_id=_uid())
    return jsonify({
        "total":     s.total,
        "due_today": s.due_today,
        "new_cards": s.new_cards,
        "by_type":   s.by_type,
        "by_book":   s.by_book,
    })


@bp.route("/api/books", methods=["GET"])
def api_books():
    return jsonify({"books": _svc().get_books(user_id=_uid())})


@bp.route("/api/quiz-sessions", methods=["POST"])
def api_save_quiz_session():
    data = request.get_json(silent=True) or {}
    session_id = _svc().save_quiz_session(
        card_type=data.get("card_type", "number"),
        questions_total=int(data.get("questions_total", 0)),
        questions_correct=int(data.get("questions_correct", 0)),
        set_label=data.get("set_label") or None,
        user_id=data.get("user_id", "default"),
    )
    return jsonify({"id": session_id, "ok": True}), 201


@bp.route("/api/quiz-sessions", methods=["GET"])
def api_get_quiz_sessions():
    sessions = _svc().get_quiz_sessions(
        user_id=_uid(),
        card_type=request.args.get("type") or None,
    )
    return jsonify({"sessions": sessions})


# ── Word list ─────────────────────────────────────────────────────────────────

@bp.route("/word-list")
def word_list():
    age_band = request.args.get("band", current_app.config["DEFAULT_AGE_BAND"])
    svc = _svc()
    counts = svc.get_vocab_word_counts(age_band)
    # Fall back to seedlings if the requested band has no curated words yet
    if counts["total"] == 0:
        age_band = "seedlings"
        counts = svc.get_vocab_word_counts(age_band)
    return render_template("flashcards/word_list.html", age_band=age_band, word_counts=counts)


@bp.route("/api/vocab-words", methods=["GET"])
def api_vocab_words():
    age_band = request.args.get("band", "seedlings")
    level    = request.args.get("level", type=int)
    words    = _svc().get_vocab_words(age_band=age_band, level=level, user_id=_uid())
    return jsonify({"words": words, "band": age_band})


@bp.route("/api/vocab-words/add", methods=["POST"])
def api_add_vocab_word():
    data = request.get_json(silent=True) or {}
    vid  = data.get("vocab_word_id")
    if not vid:
        return jsonify({"error": "vocab_word_id required"}), 400
    card = _svc().add_vocab_word_to_deck(
        vocab_word_id=int(vid),
        user_id=data.get("user_id", "default"),
    )
    if card is None:
        return jsonify({"error": "Word not found or already in deck"}), 409
    return jsonify(card.to_dict()), 201


@bp.route("/api/vocab-words/add-level", methods=["POST"])
def api_add_vocab_level():
    data  = request.get_json(silent=True) or {}
    band  = data.get("band", "seedlings")
    level = data.get("level")
    if not level:
        return jsonify({"error": "level required"}), 400
    result = _svc().add_vocab_level_to_deck(
        age_band=band,
        level=int(level),
        user_id=data.get("user_id", "default"),
    )
    return jsonify(result)
