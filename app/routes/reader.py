import base64
from flask import Blueprint, jsonify, render_template, request, current_app
from app.services.gutenberg import GutenbergService
from app.services.epub_parser import parse_epub, save_parsed_book, load_parsed_book
from app.services.tts import TTSService

bp = Blueprint("reader", __name__)

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
    age_band = current_app.config["DEFAULT_AGE_BAND"]
    return render_template("home/index.html", age_band=age_band)


@bp.route("/read/<int:book_id>")
def read(book_id: int):
    chapter_index = max(0, int(request.args.get("chapter", 0)))
    age_band = request.args.get("band", current_app.config["DEFAULT_AGE_BAND"])
    font_size = int(request.args.get("font_size", current_app.config["DEFAULT_FONT_SIZE"]))
    theme = request.args.get("theme", current_app.config["DEFAULT_THEME"])

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
    Return definition + audio pronunciation + image for a word.

    Data sources (all free, no API key):
      - Free Dictionary API  → definitions, phonetic text, audio MP3 URL
      - Wikipedia REST API   → thumbnail image for concrete words

    Schema note: when the DB is built, vocab_words will store
    image_url and audio_url columns so these load instantly offline.
    """
    word = (request.args.get("word") or "").strip().lower()
    word = word.strip(".,!?;:\"'()")
    if not word:
        return jsonify({"error": "word is required"}), 400

    result = {
        "word": word,
        "definitions": [],
        "phonetic": "",
        "audio_url": None,    # direct MP3 link — browser plays it natively
        "image_url": None,    # thumbnail for the vocab card
        "source": "offline_stub",
    }

    # ── 1. Free Dictionary API — definitions + audio ──────────────────
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
                result["phonetic"] = entry.get("phonetic", "")

                # Grab the first phonetics entry that has an audio URL
                for ph in entry.get("phonetics", []):
                    audio = ph.get("audio", "")
                    if audio:
                        result["audio_url"] = audio
                        # Use this entry's text if root phonetic is missing
                        if not result["phonetic"]:
                            result["phonetic"] = ph.get("text", "")
                        break

                # Definitions — up to 2 parts of speech, 1 definition each
                for meaning in entry.get("meanings", [])[:2]:
                    for defn in meaning.get("definitions", [])[:1]:
                        result["definitions"].append({
                            "part_of_speech": meaning.get("partOfSpeech", ""),
                            "definition": defn.get("definition", ""),
                            "example": defn.get("example", ""),
                        })

                result["source"] = "online"
    except Exception:
        pass

    # ── 2. Auto-image disabled ────────────────────────────────────────
    # Wikipedia and Wikimedia Commons have no SafeSearch — not appropriate
    # for a kids product. Image association is a parent-initiated action
    # via the image search panel, which requires a configured API key
    # (Pixabay or Google) with SafeSearch enforced. image_url stays None.

    # ── Offline fallback ──────────────────────────────────────────────
    if not result["definitions"]:
        result["definitions"] = [{
            "part_of_speech": "",
            "definition": "Definition unavailable offline. A local dictionary is coming in the next build.",
            "example": "",
        }]

    return jsonify(result)


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
    existing_id = svc.word_exists(word)
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
