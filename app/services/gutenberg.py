"""
Gutenberg service — fetches book metadata and EPUBs from Project Gutenberg.

Uses the gutendex.com public API for search/metadata (MIT-licensed API).
All content is public domain. No API key needed.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Optional

import requests

# Gutenberg cover URL pattern — works for almost all books
def _cover(gid: int) -> str:
    return f"https://www.gutenberg.org/cache/epub/{gid}/pg{gid}.cover.medium.jpg"

def _epub(gid: int) -> str:
    return f"https://www.gutenberg.org/ebooks/{gid}.epub.images"

# Hardcoded curated list — loads instantly, no network needed for the library page.
# Covers are fetched lazily by the browser from Gutenberg's CDN.
FEATURED_BOOKS_STATIC: list["BookMeta"] = []  # filled after class definition


@dataclass
class BookMeta:
    id: int
    title: str
    authors: list[str]
    subjects: list[str]
    cover_url: Optional[str]
    epub_url: Optional[str]
    download_count: int
    languages: list[str]


@dataclass
class SearchResults:
    books: list[BookMeta]
    total: int
    next_page: Optional[int]


class GutenbergService:
    SEARCH_URL = "https://gutendex.com/books"

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir

    # ------------------------------------------------------------------ search

    def search(self, query: str, page: int = 1) -> SearchResults:
        """Search Gutenberg via gutendex.com. Raises on network error."""
        params = {"search": query, "page": page, "languages": "en"}
        resp = requests.get(self.SEARCH_URL, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        books = [self._parse_book(b) for b in data.get("results", [])]
        return SearchResults(
            books=books,
            total=data.get("count", 0),
            next_page=page + 1 if data.get("next") else None,
        )

    # ---------------------------------------------------------------- metadata

    def get_book(self, gutenberg_id: int) -> Optional[BookMeta]:
        """
        Return book metadata. Lookup order (fastest first):
          1. Static featured list  — instant, no I/O
          2. Disk cache            — fast, no network
          3. gutendex.com API      — slow, requires internet
        """
        # 1. Static list (covers all 15 featured books with zero latency)
        for book in FEATURED_BOOKS_STATIC:
            if book.id == gutenberg_id:
                return book

        # 2. Disk cache
        meta_path = self.cache_dir / f"{gutenberg_id}.meta.json"
        if meta_path.exists():
            return BookMeta(**json.loads(meta_path.read_text()))

        # 3. Network (search results, non-featured books)
        resp = requests.get(f"{self.SEARCH_URL}/{gutenberg_id}", timeout=10)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        meta = self._parse_book(resp.json())
        self._save_meta(meta, meta_path)
        return meta

    def get_featured_books(self) -> list[BookMeta]:
        """Return curated kids classics instantly from the hardcoded list."""
        return list(FEATURED_BOOKS_STATIC)

    # ---------------------------------------------------------- EPUB download

    def download_epub(self, gutenberg_id: int) -> Path:
        """
        Download EPUB and cache to disk. Returns local path.
        Safe to call repeatedly — returns cached file if already downloaded.
        """
        epub_path = self.cache_dir / f"{gutenberg_id}.epub"
        if epub_path.exists():
            return epub_path

        meta = self.get_book(gutenberg_id)
        url = (
            meta.epub_url
            if meta and meta.epub_url
            else f"https://www.gutenberg.org/ebooks/{gutenberg_id}.epub.images"
        )

        resp = requests.get(url, timeout=60, stream=True)
        if resp.status_code == 404:
            # Try the no-images variant
            url = f"https://www.gutenberg.org/ebooks/{gutenberg_id}.epub3.images"
            resp = requests.get(url, timeout=60, stream=True)
        resp.raise_for_status()

        tmp_path = epub_path.with_suffix(".epub.tmp")
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=16384):
                f.write(chunk)
        tmp_path.rename(epub_path)  # atomic rename
        return epub_path

    # ---------------------------------------------------------------- helpers

    def _parse_book(self, data: dict) -> BookMeta:
        formats = data.get("formats", {})
        cover_url = formats.get("image/jpeg")
        epub_url = formats.get("application/epub+zip") or formats.get("application/epub")
        return BookMeta(
            id=data["id"],
            title=data.get("title", "Unknown Title"),
            authors=[p["name"] for p in data.get("authors", [])],
            subjects=data.get("subjects", []),
            cover_url=cover_url,
            epub_url=epub_url,
            download_count=data.get("download_count", 0),
            languages=data.get("languages", ["en"]),
        )

    def _save_meta(self, meta: BookMeta, path: Path) -> None:
        path.write_text(json.dumps({
            "id": meta.id, "title": meta.title, "authors": meta.authors,
            "subjects": meta.subjects, "cover_url": meta.cover_url,
            "epub_url": meta.epub_url, "download_count": meta.download_count,
            "languages": meta.languages,
        }))


# ── Curated featured list ────────────────────────────────────────────────────
# Pre-filled so the library page loads instantly without any network calls.
# Covers are served from Gutenberg's CDN and load lazily in the browser.
def _bm(gid, title, authors):
    return BookMeta(
        id=gid, title=title, authors=authors, subjects=[],
        cover_url=_cover(gid), epub_url=_epub(gid),
        download_count=0, languages=["en"],
    )

FEATURED_BOOKS_STATIC = [
    _bm(11,    "Alice's Adventures in Wonderland",  ["Carroll, Lewis"]),
    _bm(55,    "The Wonderful Wizard of Oz",         ["Baum, L. Frank"]),
    _bm(289,   "The Wind in the Willows",            ["Grahame, Kenneth"]),
    _bm(16,    "Peter Pan",                          ["Barrie, J. M."]),
    _bm(120,   "Treasure Island",                    ["Stevenson, Robert Louis"]),
    _bm(35997, "The Jungle Book",                    ["Kipling, Rudyard"]),
    _bm(2781,  "Just So Stories",                    ["Kipling, Rudyard"]),
    _bm(19003, "A Little Princess",                  ["Burnett, Frances Hodgson"]),
    _bm(17396, "The Secret Garden",                  ["Burnett, Frances Hodgson"]),
    _bm(271,   "Black Beauty",                       ["Sewell, Anna"]),
    _bm(514,   "Little Women",                       ["Alcott, Louisa May"]),
    _bm(74,    "The Adventures of Tom Sawyer",       ["Twain, Mark"]),
    _bm(11339, "Aesop's Fables",                     ["Aesop"]),
    _bm(2591,  "Grimm's Fairy Tales",                ["Grimm, Jacob", "Grimm, Wilhelm"]),
    _bm(500,   "The Adventures of Pinocchio",        ["Collodi, Carlo"]),
]
