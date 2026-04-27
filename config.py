import os
from pathlib import Path

BASE_DIR = Path(__file__).parent


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "atlas-dev-key-change-before-deploy")

    # Disk cache
    CACHE_DIR = BASE_DIR / "cache"
    BOOK_CACHE_DIR = CACHE_DIR / "books"
    AUDIO_CACHE_DIR = CACHE_DIR / "audio"
    IMAGE_CACHE_DIR = BASE_DIR / "app" / "static" / "img_cache"

    # SQLite — single file, WAL mode for concurrent reads
    DB_PATH = BASE_DIR / "atlas.db"

    # TTS defaults
    TTS_VOICE = "af_heart"   # warm American female
    TTS_SPEED = 1.0

    # Gutenberg
    GUTENDEX_URL = "https://gutendex.com/books"

    # AI story generation
    ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
    AI_PROVIDER       = os.environ.get("AI_PROVIDER", "claude")   # swap to "local" for on-device

    # On-device vocab enrichment (Ollama on Pi)
    OLLAMA_BASE_URL    = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_VOCAB_MODEL = os.environ.get("OLLAMA_VOCAB_MODEL", "gemma4:e2b")

    # Image generation (parent configures; no default key ever shipped)
    # Set IMAGE_PROVIDER to 'openai' or 'replicate'
    IMAGE_PROVIDER        = os.environ.get("IMAGE_PROVIDER", "openai")
    OPENAI_API_KEY        = os.environ.get("OPENAI_API_KEY", "")
    REPLICATE_API_KEY     = os.environ.get("REPLICATE_API_KEY", "")
    MONTHLY_IMAGE_BUDGET  = float(os.environ.get("MONTHLY_IMAGE_BUDGET", "5.0"))

    # Default reading settings (will move to user profile in DB phase)
    DEFAULT_AGE_BAND = "explorers"  # seedlings | explorers | adventurers
    DEFAULT_FONT_SIZE = 20          # px
    DEFAULT_THEME = "light"         # light | dark | redlight

    # ── Image search (parent configures in settings) ──────────────────
    # Atlas will NOT show image search results unless one of these is set.
    # Never show unfiltered image results to a child — safety first.
    #
    # Option A — Pixabay (recommended, free):
    #   Register free at https://pixabay.com/api/docs/
    #   Set PIXABAY_API_KEY in your environment or .env file
    #
    # Option B — Google Custom Search (best SafeSearch):
    #   1. Enable Custom Search API at console.cloud.google.com
    #   2. Create a search engine at cse.google.com (search whole web, image search on)
    #   3. Set both GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX
    PIXABAY_API_KEY     = os.environ.get("PIXABAY_API_KEY", "")
    GOOGLE_SEARCH_API_KEY = os.environ.get("GOOGLE_SEARCH_API_KEY", "")
    GOOGLE_SEARCH_CX    = os.environ.get("GOOGLE_SEARCH_CX", "")

    @classmethod
    def ensure_dirs(cls):
        cls.BOOK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cls.AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cls.IMAGE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
