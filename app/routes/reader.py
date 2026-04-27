import base64
from flask import Blueprint, jsonify, render_template, request, current_app, session, redirect, url_for
from app.services.gutenberg import GutenbergService
from app.services.epub_parser import parse_epub, save_parsed_book, load_parsed_book
from app.services.tts import TTSService

bp = Blueprint("reader", __name__)


def _uid() -> str:
    from flask import session
    return str(session.get("profile_id", "default"))

# Singleton TTS service — lazy-loaded on first request
_tts = None  # type: TTSService


def _get_tts() -> TTSService:
    global _tts
    if _tts is None:
        _tts = TTSService()
    return _tts


def _gutenberg() -> GutenbergService:
    return GutenbergService(current_app.config["BOOK_CACHE_DIR"])


# ----------------------------------------------------------------- page routes

@bp.route("/")
def home():
    if not session.get("profile_id"):
        from app.services.profile_service import ProfileService
        svc = ProfileService(current_app.config["DB_PATH"])
        if svc.list_profiles(family_id=session.get("family_id")):
            return redirect(url_for("profiles.select"))
        else:
            return redirect(url_for("profiles.new"))
    age_band = session.get("age_band", current_app.config["DEFAULT_AGE_BAND"])
    return render_template("home/index.html", age_band=age_band)


@bp.route("/read/<int:book_id>")
def read(book_id: int):
    from app.services.flashcard_service import FlashcardService
    age_band  = request.args.get("band",      current_app.config["DEFAULT_AGE_BAND"])
    font_size = int(request.args.get("font_size", current_app.config["DEFAULT_FONT_SIZE"]))
    theme     = request.args.get("theme",     current_app.config["DEFAULT_THEME"])

    # If the caller didn't specify a chapter, restore from DB progress
    progress_svc = FlashcardService(current_app.config["DB_PATH"])
    if "chapter" not in request.args:
        saved = progress_svc.get_reading_progress(book_id, user_id=_uid())
        chapter_index = saved["chapter_index"] if saved else 0
        saved_word    = saved["word_index"]    if saved else 0
    else:
        chapter_index = max(0, int(request.args["chapter"]))
        saved_word    = 0  # explicit navigation — start from top of chapter

    try:
        svc = _gutenberg()
        meta = svc.get_book(book_id)
        if not meta:
            return render_template("reader/error.html", error="Book not found.", book_id=book_id), 404

        # Check if EPUB is already cached — if not, show a loading page that
        # auto-refreshes. This prevents a 30-second silent hang on first open.
        epub_path = current_app.config["BOOK_CACHE_DIR"] / f"{book_id}.epub"
        if not epub_path.exists():
            return render_template(
                "reader/loading.html",
                meta=meta,
                book_id=book_id,
                chapter_index=chapter_index,
                age_band=age_band,
                font_size=font_size,
                theme=theme,
            )

        # EPUB is cached — use the JSON parse cache when fresh, else re-parse
        parsed_cache = current_app.config["BOOK_CACHE_DIR"] / f"{book_id}.parsed.json"
        if (parsed_cache.exists() and
                parsed_cache.stat().st_mtime >= epub_path.stat().st_mtime):
            book = load_parsed_book(parsed_cache)
        else:
            book = parse_epub(epub_path)
            try:
                save_parsed_book(book, parsed_cache)
            except Exception:
                pass  # cache write failure is non-fatal

        if not book.chapters:
            return render_template("reader/error.html", error="Could not parse this book.", book_id=book_id), 500

        chapter_index = min(chapter_index, len(book.chapters) - 1)
        chapter = book.chapters[chapter_index]

        return render_template(
            "reader/index.html",
            meta=meta,
            book=book,
            chapter=chapter,
            chapter_index=chapter_index,
            total_chapters=book.total_chapters,
            age_band=age_band,
            font_size=font_size,
            theme=theme,
            tts_available=_get_tts().is_available,
            saved_word=saved_word,
        )
    except Exception as e:
        return render_template("reader/error.html", error=str(e), book_id=book_id), 500


# ------------------------------------------------------------------ JSON APIs

@bp.route("/api/book/<int:book_id>/download", methods=["POST"])
def download_book(book_id: int):
    """
    Trigger EPUB download in the foreground and report progress.
    Called by the loading page via fetch(). Returns JSON status.
    """
    try:
        svc = _gutenberg()
        svc.download_epub(book_id)
        return jsonify({"status": "ready"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@bp.route("/api/tts/synthesize", methods=["POST"])
def tts_synthesize():
    """
    Generate speech for a chunk of text.
    Returns base64-encoded WAV audio + word timing array.
    The browser plays the audio and highlights words in sync.
    """
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    voice = data.get("voice") or current_app.config["TTS_VOICE"]
    speed = float(data.get("speed") or current_app.config["TTS_SPEED"])

    if not text:
        return jsonify({"error": "text is required"}), 400

    tts = _get_tts()
    result = tts.synthesize(text, voice=voice, speed=speed)

    return jsonify({
        "audio_b64": base64.b64encode(result.audio_bytes).decode(),
        "duration_ms": result.duration_ms,
        "word_timings": [
            {
                "word": wt.word,
                "start_ms": wt.start_ms,
                "end_ms": wt.end_ms,
                "index": wt.word_index,
            }
            for wt in result.word_timings
        ],
        "voice": result.voice,
        "is_stub": result.is_stub,
    })


@bp.route("/api/vocab/define")
def vocab_define():
    """
    Return definition + audio pronunciation for a word.

    Lookup order (fastest/most-offline first):
      1. word_cache DB table  — instant, fully offline, grows with use
      2. vocab_words table    — curated words have kid-friendly definitions
      3. Free Dictionary API  — requires internet; result saved to cache
      4. Stub                 — last resort when offline and word is unknown

    Image search is intentionally separate (requires a SafeSearch API key).
    """
    from app.services.flashcard_service import FlashcardService
    word = (request.args.get("word") or "").strip().lower()
    word = word.strip(".,!?;:\"'()")
    if not word:
        return jsonify({"error": "word is required"}), 400

    svc = FlashcardService(current_app.config["DB_PATH"])

    # ── 1. DB cache (instant, offline) ───────────────────────────────
    cached = svc.get_cached_word(word)
    if cached and cached["definitions"]:
        return jsonify({"word": word, "image_url": None, "source": "cache", **cached})

    # ── 2. Curated vocab_words table ─────────────────────────────────
    curated = svc.get_vocab_word_definition(word)
    if curated and curated["definitions"]:
        # Don't cache vocab_words — they're already in the DB
        return jsonify({"word": word, "image_url": None, "source": "curated", **curated})

    # ── 3. Free Dictionary API (online) ──────────────────────────────
    phonetic    = ""
    audio_url   = ""
    definitions = []
    try:
        import requests as req
        resp = req.get(
            f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}",
            timeout=4,
        )
        if resp.status_code == 200:
            entries = resp.json()
            if entries and isinstance(entries, list):
                entry = entries[0]
                phonetic = entry.get("phonetic", "")
                for ph in entry.get("phonetics", []):
                    if ph.get("audio"):
                        audio_url = ph["audio"]
                        if not phonetic:
                            phonetic = ph.get("text", "")
                        break
                for meaning in entry.get("meanings", [])[:2]:
                    for defn in meaning.get("definitions", [])[:1]:
                        definitions.append({
                            "part_of_speech": meaning.get("partOfSpeech", ""),
                            "definition":     defn.get("definition", ""),
                            "example":        defn.get("example", ""),
                        })
    except Exception:
        pass

    if definitions:
        svc.cache_word(word, phonetic, audio_url, definitions)
        return jsonify({
            "word":        word,
            "phonetic":    phonetic,
            "audio_url":   audio_url or None,
            "image_url":   None,
            "definitions": definitions,
            "source":      "online",
        })

    # ── 4. Stub ───────────────────────────────────────────────────────
    return jsonify({
        "word":        word,
        "phonetic":    "",
        "audio_url":   None,
        "image_url":   None,
        "definitions": [{"part_of_speech": "", "definition": "No definition found. Connect to the internet to look this word up.", "example": ""}],
        "source":      "offline_stub",
    })


@bp.route("/api/progress", methods=["POST"])
def save_progress():
    """Save reading position. Called fire-and-forget on every page turn."""
    from app.services.flashcard_service import FlashcardService
    data = request.get_json(silent=True) or {}
    book_id       = data.get("book_id")
    chapter_index = data.get("chapter_index")
    word_index    = data.get("word_index", 0)
    if book_id is None or chapter_index is None:
        return jsonify({"error": "book_id and chapter_index required"}), 400
    FlashcardService(current_app.config["DB_PATH"]).save_reading_progress(
        book_id=int(book_id),
        chapter_index=int(chapter_index),
        word_index=int(word_index),
        user_id=_uid(),
    )
    return jsonify({"saved": True})


@bp.route("/api/vocab/save", methods=["POST"])
def vocab_save():
    """Save a word from the reader popover as a vocabulary flashcard."""
    from app.services.flashcard_service import FlashcardService
    data = request.get_json(silent=True) or {}
    word = (data.get("word") or "").strip()
    if not word:
        return jsonify({"error": "word required"}), 400

    svc = FlashcardService(current_app.config["DB_PATH"])

    # Avoid duplicates
    existing_id = svc.word_exists(word, user_id=_uid())
    if existing_id:
        return jsonify({"duplicate": True, "card_id": existing_id}), 200

    front_data = {
        "word": word,
        "phonetic": data.get("phonetic") or "",
        "image_url": data.get("image_url") or None,
    }
    back_data = {
        "definition": data.get("definition") or "",
        "example_sentence": data.get("example_sentence") or "",
    }
    card = svc.create_card(
        card_type="vocabulary",
        front_data=front_data,
        back_data=back_data,
        source_book=data.get("source_book") or None,
        source_chapter=data.get("source_chapter") or None,
        user_id=_uid(),
    )
    return jsonify({"saved": True, "card_id": card.id}), 201


@bp.route("/api/vocab/image-search")
def vocab_image_search():
    """
    SafeSearch image lookup for vocab cards.

    Provider priority (first configured wins):
      1. Pixabay  — free API key, safesearch=true, 1,500 req/hr free
      2. Google Custom Search — best SafeSearch, 100/day free then $5/1000

    If neither is configured: returns setup_required=true.
    We NEVER fall back to unfiltered sources on a kids device.

    Setup:
      Pixabay  → set PIXABAY_API_KEY env var (free at pixabay.com/api/docs)
      Google   → set GOOGLE_SEARCH_API_KEY + GOOGLE_SEARCH_CX env vars
    """
    query = (request.args.get("q") or "").strip()
    if not query:
        return jsonify({"images": [], "setup_required": False}), 400

    pixabay_key = current_app.config.get("PIXABAY_API_KEY", "")
    google_key  = current_app.config.get("GOOGLE_SEARCH_API_KEY", "")
    google_cx   = current_app.config.get("GOOGLE_SEARCH_CX", "")

    # ── No key configured — fail safe ────────────────────────────────
    if not pixabay_key and not (google_key and google_cx):
        return jsonify({
            "images": [],
            "setup_required": True,
            "message": "Image search needs a free API key to keep results safe for kids.",
        }), 200

    import requests as req

    # ── Provider 1: Pixabay ───────────────────────────────────────────
    if pixabay_key:
        try:
            resp = req.get(
                "https://pixabay.com/api/",
                params={
                    "key":         pixabay_key,
                    "q":           query,
                    "safesearch":  "true",
                    "image_type":  "photo",
                    "per_page":    8,
                    "min_width":   200,
                },
                timeout=6,
            )
            data = resp.json()
            images = [
                {"thumb": h["previewURL"], "full": h["webformatURL"]}
                for h in data.get("hits", [])[:8]
            ]
            return jsonify({"images": images, "provider": "pixabay"})
        except Exception as e:
            pass  # fall through to Google if Pixabay fails

    # ── Provider 2: Google Custom Search ─────────────────────────────
    if google_key and google_cx:
        try:
            resp = req.get(
                "https://www.googleapis.com/customsearch/v1",
                params={
                    "key":        google_key,
                    "cx":         google_cx,
                    "q":          query,
                    "searchType": "image",
                    "safe":       "active",   # Google SafeSearch ON
                    "num":        8,
                    "imgSize":    "medium",
                },
                timeout=6,
            )
            data = resp.json()
            images = [
                {"thumb": item.get("image", {}).get("thumbnailLink", ""),
                 "full":  item.get("link", "")}
                for item in data.get("items", [])[:8]
                if item.get("link")
            ]
            return jsonify({"images": images, "provider": "google"})
        except Exception as e:
            return jsonify({"images": [], "error": str(e)}), 200

    return jsonify({"images": [], "error": "No image provider available"}), 200
