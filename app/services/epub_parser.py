"""
EPUB parser — pure Python, zero external dependencies.

EPUBs are ZIP files containing XML + HTML. We:
  1. Read META-INF/container.xml to find the OPF package file
  2. Read the OPF to get the spine (reading order) and metadata
  3. Parse each spine document into plain text + word tokens
  4. Return a ParsedBook ready for the reader

Handles EPUB 2 and EPUB 3.
"""

import html as html_module
import json
import os
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional
import xml.etree.ElementTree as ET


# ------------------------------------------------------------------- data types

@dataclass
class Word:
    text: str       # the word itself (may include trailing punctuation)
    index: int      # position within this chapter (0-based)


@dataclass
class Chapter:
    title: str
    index: int          # chapter position in the book (0-based)
    words: list[Word]
    plain_text: str
    paragraphs: list[tuple[int, int]]  # (word_start, word_end) per paragraph, inclusive

    @property
    def word_count(self) -> int:
        return len(self.words)


@dataclass
class ParsedBook:
    title: str
    authors: list[str]
    language: str
    chapters: list[Chapter]

    @property
    def total_words(self) -> int:
        return sum(c.word_count for c in self.chapters)

    @property
    def total_chapters(self) -> int:
        return len(self.chapters)


# ---------------------------------------------------------------- public API

def parse_epub(epub_path: Path) -> ParsedBook:
    """
    Parse an EPUB file into a ParsedBook.
    Raises zipfile.BadZipFile if the file is corrupt.
    """
    with zipfile.ZipFile(epub_path, "r") as zf:
        all_names = set(zf.namelist())

        # Step 1: Find the OPF file
        container_xml = zf.read("META-INF/container.xml").decode("utf-8", errors="replace")
        opf_path = _find_opf_path(container_xml)

        # Fallback: scan ZIP for any .opf file if container.xml gave us nothing
        if not opf_path or opf_path not in all_names:
            opf_path = next(
                (n for n in sorted(all_names) if n.endswith(".opf")),
                None,
            )
        if not opf_path:
            raise ValueError("Could not locate OPF package file in this EPUB.")

        opf_dir = str(PurePosixPath(opf_path).parent)  # e.g. 'OEBPS' or '.'

        # Step 2: Parse OPF for title, authors, spine
        opf_xml = zf.read(opf_path).decode("utf-8", errors="replace")
        title, authors, language, spine_items = _parse_opf(opf_xml, opf_dir)

        # Step 3: Parse each spine item into a chapter
        chapters = []
        for seq, (chapter_title, item_path) in enumerate(spine_items):
            if item_path not in all_names:
                continue
            raw = zf.read(item_path).decode("utf-8", errors="replace")
            plain_text = _html_to_plain(raw)

            # Skip cover pages, TOC, etc. that have almost no text
            if len(plain_text.split()) < 50:
                continue

            words, paragraphs = _tokenize_with_paragraphs(plain_text)
            chapters.append(Chapter(
                title=chapter_title or f"Chapter {len(chapters) + 1}",
                index=len(chapters),
                words=words,
                plain_text=plain_text,
                paragraphs=paragraphs,
            ))

    return ParsedBook(
        title=title,
        authors=authors,
        language=language,
        chapters=chapters,
    )


# ------------------------------------------------------------------- internals

def _find_opf_path(container_xml: str) -> str:
    """
    Extract OPF path from META-INF/container.xml.
    Searches every element for a 'full-path' attribute that ends in .opf —
    namespace-agnostic so it works across EPUB 2 and EPUB 3.
    """
    root = ET.fromstring(container_xml)
    for elem in root.iter():
        full_path = elem.get("full-path", "")
        if full_path.endswith(".opf"):
            return full_path
    return ""  # caller will scan the ZIP for fallbacks


def _parse_opf(opf_xml: str, opf_dir: str) -> tuple[str, list[str], str, list[tuple[str, str]]]:
    """
    Parse the OPF package document.
    Returns (title, authors, language, spine_items).
    spine_items is a list of (chapter_title, file_path_in_zip).
    """
    root = ET.fromstring(opf_xml)
    base = PurePosixPath(opf_dir) if opf_dir and opf_dir != "." else PurePosixPath("")

    def find_text(local_tag: str, namespace: str) -> str:
        el = root.find(f".//{{{namespace}}}{local_tag}")
        return (el.text or "").strip() if el is not None else ""

    title = find_text("title", "http://purl.org/dc/elements/1.1/") or "Unknown Title"
    language = find_text("language", "http://purl.org/dc/elements/1.1/") or "en"
    authors = [
        el.text.strip()
        for el in root.findall(".//{http://purl.org/dc/elements/1.1/}creator")
        if el.text
    ]

    # Build manifest: id → href (namespace-agnostic)
    manifest: dict[str, str] = {}
    for item in root.iter():
        if item.tag.endswith("}item") or item.tag == "item":
            item_id = item.get("id", "")
            href = item.get("href", "")
            if item_id and href:
                # Resolve href relative to OPF directory
                full = str(base / href) if str(base) else href
                manifest[item_id] = full

    # Build spine order
    spine_items = []
    for itemref in root.iter():
        if itemref.tag.endswith("}itemref") or itemref.tag == "itemref":
            idref = itemref.get("idref", "")
            if idref in manifest:
                spine_items.append(("", manifest[idref]))

    return title, authors, language, spine_items


def _html_to_plain(html_content: str) -> str:
    """Strip HTML tags and decode entities. Returns plain text with \\n\\n paragraph breaks."""
    # Drop <script> and <style> blocks entirely
    cleaned = re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        "",
        html_content,
        flags=re.DOTALL | re.IGNORECASE,
    )
    # Block-level elements become paragraph breaks
    cleaned = re.sub(r"<(p|div|h[1-6]|li)[^>]*>", "\n\n", cleaned, flags=re.IGNORECASE)
    # Line breaks become single newlines
    cleaned = re.sub(r"<br[^>]*/?>", "\n", cleaned, flags=re.IGNORECASE)
    # Strip remaining tags
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    # Decode HTML entities (&amp; &quot; etc.)
    cleaned = html_module.unescape(cleaned)
    # Normalize: collapse inline whitespace per line, preserve paragraph breaks
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in cleaned.splitlines()]
    cleaned = "\n".join(lines)
    # Collapse 3+ newlines to a single paragraph break
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _tokenize_with_paragraphs(plain_text: str) -> tuple[list[Word], list[tuple[int, int]]]:
    """
    Split paragraph-marked plain text into Word objects and paragraph boundaries.
    Paragraphs are separated by \\n\\n. Returns (words, paragraphs).
    Each entry in paragraphs is (word_start, word_end) — inclusive word indices.
    Falls back to treating the whole text as one paragraph if no \\n\\n is found.
    """
    words: list[Word] = []
    paragraphs: list[tuple[int, int]] = []

    for para_text in re.split(r"\n\n+", plain_text):
        para_text = para_text.strip()
        if not para_text:
            continue
        raw_words = [w for w in para_text.split() if w.strip()]
        if not raw_words:
            continue
        start = len(words)
        for raw in raw_words:
            words.append(Word(text=raw, index=len(words)))
        paragraphs.append((start, len(words) - 1))

    return words, paragraphs


# ---------------------------------------------------------------- parse cache

def save_parsed_book(book: ParsedBook, path: Path) -> None:
    """Serialize a ParsedBook to JSON so subsequent loads skip the EPUB unzip."""
    data = {
        "title": book.title,
        "authors": book.authors,
        "language": book.language,
        "chapters": [
            {
                "title": ch.title,
                "index": ch.index,
                "plain_text": ch.plain_text,
                "words": [w.text for w in ch.words],  # index is implicit
                "paragraphs": [[s, e] for s, e in ch.paragraphs],
            }
            for ch in book.chapters
        ],
    }
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False))
    tmp.rename(path)  # atomic replace


def load_parsed_book(path: Path) -> ParsedBook:
    """Deserialize a ParsedBook from the JSON cache written by save_parsed_book."""
    data = json.loads(path.read_text())
    chapters = [
        Chapter(
            title=ch["title"],
            index=ch["index"],
            plain_text=ch["plain_text"],
            words=[Word(text=w, index=i) for i, w in enumerate(ch["words"])],
            paragraphs=[(p[0], p[1]) for p in ch.get("paragraphs", [])],
        )
        for ch in data["chapters"]
    ]
    return ParsedBook(
        title=data["title"],
        authors=data["authors"],
        language=data["language"],
        chapters=chapters,
    )
