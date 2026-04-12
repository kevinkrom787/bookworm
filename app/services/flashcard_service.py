"""
Flashcard service — SQLite storage + SM-2 spaced repetition.

Extensibility: card types are open JSON blobs. To add a new type:
  1. Pick a type key string, e.g. 'phonics'
  2. Define its front_data / back_data shape in your feature docs
  3. Add a renderer in CARD_RENDERERS on the client (flashcards JS)
  No server-side schema changes needed.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional


# ── Schema ─────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    card_type       TEXT    NOT NULL,
    user_id         TEXT    NOT NULL DEFAULT 'default',
    front_data      TEXT    NOT NULL DEFAULT '{}',
    back_data       TEXT    NOT NULL DEFAULT '{}',
    source_book     TEXT,
    source_chapter  TEXT,
    date_added      TEXT    NOT NULL DEFAULT (datetime('now')),
    ease_factor     REAL    NOT NULL DEFAULT 2.5,
    interval        INTEGER NOT NULL DEFAULT 0,
    repetitions     INTEGER NOT NULL DEFAULT 0,
    due_date        TEXT    NOT NULL DEFAULT (date('now')),
    last_reviewed   TEXT,
    review_count    INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cards_user_due  ON cards (user_id, due_date);
CREATE INDEX IF NOT EXISTS idx_cards_type      ON cards (card_type);
CREATE INDEX IF NOT EXISTS idx_cards_book      ON cards (source_book);
CREATE INDEX IF NOT EXISTS idx_cards_vocab_word
    ON cards (lower(json_extract(front_data, '$.word')))
    WHERE card_type='vocabulary';

CREATE TABLE IF NOT EXISTS quiz_sessions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           TEXT    NOT NULL DEFAULT 'default',
    card_type         TEXT    NOT NULL,
    set_label         TEXT,
    questions_total   INTEGER NOT NULL,
    questions_correct INTEGER NOT NULL,
    score_pct         REAL    NOT NULL,
    completed_at      TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_quiz_user ON quiz_sessions (user_id, completed_at);

CREATE TABLE IF NOT EXISTS vocab_words (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    word        TEXT    NOT NULL,
    phonetic    TEXT    NOT NULL DEFAULT '',
    definition  TEXT    NOT NULL DEFAULT '',
    example     TEXT    NOT NULL DEFAULT '',
    age_band    TEXT    NOT NULL,
    level       INTEGER NOT NULL DEFAULT 1,
    category    TEXT    NOT NULL DEFAULT 'sight_words'
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_vocab_words_word_band ON vocab_words (word, age_band);

CREATE TABLE IF NOT EXISTS word_cache (
    word        TEXT PRIMARY KEY,
    phonetic    TEXT    NOT NULL DEFAULT '',
    audio_url   TEXT    NOT NULL DEFAULT '',
    definitions TEXT    NOT NULL DEFAULT '[]',
    fetched_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS reading_progress (
    user_id       TEXT    NOT NULL DEFAULT 'default',
    book_id       INTEGER NOT NULL,
    chapter_index INTEGER NOT NULL DEFAULT 0,
    word_index    INTEGER NOT NULL DEFAULT 0,
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (user_id, book_id)
);
"""


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class Card:
    id: int
    card_type: str
    user_id: str
    front_data: dict
    back_data: dict
    source_book: Optional[str]
    source_chapter: Optional[str]
    date_added: str
    ease_factor: float
    interval: int
    repetitions: int
    due_date: str
    last_reviewed: Optional[str]
    review_count: int

    @property
    def is_due(self) -> bool:
        return self.due_date <= date.today().isoformat()

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "card_type":      self.card_type,
            "user_id":        self.user_id,
            "front_data":     self.front_data,
            "back_data":      self.back_data,
            "source_book":    self.source_book,
            "source_chapter": self.source_chapter,
            "date_added":     self.date_added,
            "ease_factor":    self.ease_factor,
            "interval":       self.interval,
            "repetitions":    self.repetitions,
            "due_date":       self.due_date,
            "last_reviewed":  self.last_reviewed,
            "review_count":   self.review_count,
            "is_due":         self.is_due,
        }


@dataclass
class ReviewResult:
    card_id: int
    new_ease_factor: float
    new_interval: int
    new_repetitions: int
    new_due_date: str


@dataclass
class DeckStats:
    total: int
    due_today: int
    new_cards: int
    by_type: dict
    by_book: dict


# ── SM-2 algorithm ─────────────────────────────────────────────────────────────

def _sm2(
    ease_factor: float,
    interval: int,
    repetitions: int,
    rating: int,          # 1=Hard, 2=Good, 3=Easy
) -> tuple[float, int, int]:
    """
    SM-2 spaced repetition.

    Maps our 3-button UI to SM-2 quality scale:
      Hard → q=3  (correct but significant difficulty)
      Good → q=4  (correct after hesitation)
      Easy → q=5  (perfect recall)

    Returns (new_ease_factor, new_interval_days, new_repetitions).
    """
    q = {1: 3, 2: 4, 3: 5}.get(rating, 4)

    if q < 3:
        # Failed — reset streak, show again soon
        return max(1.3, ease_factor - 0.2), 1, 0

    # Passed — advance interval
    if repetitions == 0:
        new_interval = 1
    elif repetitions == 1:
        new_interval = 6
    else:
        new_interval = round(interval * ease_factor)

    new_ef = ease_factor + (0.1 - (5 - q) * (0.08 + (5 - q) * 0.02))
    new_ef = max(1.3, new_ef)

    return new_ef, new_interval, repetitions + 1


# ── Seedlings vocabulary seed data ────────────────────────────────────────────
# Tuples: (word, phonetic, definition, example, level, category)

_SEEDLINGS_WORDS: list[tuple] = [
    # ── Level 1 — Beginner (pre-primer sight words + core vocabulary) ──────────
    ("a",      "/eɪ/",       "Used before a thing you talk about",                  "A cat is soft.",                        1, "sight_words"),
    ("and",    "/ænd/",      "Connects two things together",                         "I like cats and dogs.",                 1, "sight_words"),
    ("big",    "/bɪɡ/",      "Very large in size",                                   "The elephant is big.",                  1, "describing"),
    ("can",    "/kæn/",      "Being able to do something",                           "I can jump very high!",                 1, "sight_words"),
    ("cat",    "/kæt/",      "A furry animal that says meow",                        "The cat is soft and fluffy.",           1, "animals"),
    ("come",   "/kʌm/",      "To move toward someone or something",                  "Come here, please!",                    1, "sight_words"),
    ("dog",    "/dɔɡ/",      "A furry animal that says woof",                        "My dog likes to fetch.",                1, "animals"),
    ("go",     "/ɡoʊ/",      "To move somewhere",                                    "Let's go to the park!",                 1, "sight_words"),
    ("I",      "/aɪ/",       "Yourself — the person who is talking!",                "I love to read books.",                 1, "sight_words"),
    ("in",     "/ɪn/",       "Inside something",                                     "The cat is in the box.",                1, "sight_words"),
    ("is",     "/ɪz/",       "Shows what something is right now",                    "The sky is blue.",                      1, "sight_words"),
    ("it",     "/ɪt/",       "A thing you are talking about",                        "It is raining outside.",                1, "sight_words"),
    ("jump",   "/dʒʌmp/",    "To push off the ground with your legs",                "I can jump so high!",                   1, "actions"),
    ("little", "/ˈlɪt.əl/",  "Very small in size",                                   "A little mouse hid away.",              1, "describing"),
    ("look",   "/lʊk/",      "To use your eyes to see something",                    "Look at that butterfly!",               1, "sight_words"),
    ("me",     "/miː/",      "Yourself — same as I!",                                "Give the toy to me, please.",           1, "sight_words"),
    ("my",     "/maɪ/",      "Something that belongs to you",                        "That is my ball.",                      1, "sight_words"),
    ("not",    "/nɑt/",      "The opposite of something",                            "I am not sleepy.",                      1, "sight_words"),
    ("play",   "/pleɪ/",     "To have fun and enjoy yourself",                       "Let's play in the yard!",               1, "actions"),
    ("red",    "/rɛd/",      "A bright color like a fire truck or an apple",         "The apple is red.",                     1, "colors"),
    ("run",    "/rʌn/",      "To move very fast on your feet",                       "I can run really fast!",                1, "actions"),
    ("see",    "/siː/",      "To look at something with your eyes",                  "I see a rainbow!",                      1, "sight_words"),
    ("the",    "/ðə/",       "Points to a specific thing",                           "The dog is so cute!",                   1, "sight_words"),
    ("to",     "/tuː/",      "Moving toward a place or thing",                       "Let's go to the park!",                 1, "sight_words"),
    ("up",     "/ʌp/",       "Higher, toward the sky",                               "The bird flew up high.",                1, "sight_words"),
    ("we",     "/wiː/",      "You and other people together",                        "We love to play!",                      1, "sight_words"),
    ("yes",    "/jɛs/",      "Agreeing that something is true",                      "Yes, I want to play!",                  1, "sight_words"),
    ("you",    "/juː/",      "The person you are talking to",                        "I like playing with you!",              1, "sight_words"),

    # ── Level 2 — Growing (primer sight words + thematic vocabulary) ───────────
    ("all",    "/ɔːl/",      "Every single one of something",                        "I ate all my vegetables.",              2, "sight_words"),
    ("ate",    "/eɪt/",      "Ate food — this already happened",                     "She ate all her dinner.",               2, "actions"),
    ("ball",   "/bɔːl/",     "A round toy you can throw and catch",                  "I threw the ball high!",                2, "things"),
    ("bird",   "/bɜːrd/",    "An animal with wings and feathers that can fly",       "A little bird sang to me.",             2, "animals"),
    ("blue",   "/bluː/",     "A color like the sky or the ocean",                    "My favorite shirt is blue.",            2, "colors"),
    ("book",   "/bʊk/",      "Pages with words and pictures to read",                "I love reading books!",                 2, "things"),
    ("did",    "/dɪd/",      "Something that already happened",                      "Did you brush your teeth?",             2, "sight_words"),
    ("do",     "/duː/",      "To make something happen",                             "Can you do a cartwheel?",               2, "sight_words"),
    ("eat",    "/iːt/",      "To put food in your mouth and swallow it",             "I love to eat pizza!",                  2, "actions"),
    ("fish",   "/fɪʃ/",      "An animal that swims in water",                        "The fish swims so fast!",               2, "animals"),
    ("get",    "/ɡɛt/",      "To receive something or go bring it back",             "Can you get your shoes?",               2, "sight_words"),
    ("good",   "/ɡʊd/",      "Something nice, helpful, or done well",                "You did a good job!",                   2, "describing"),
    ("green",  "/ɡriːn/",    "A color like grass and leaves",                        "Frogs are often green.",                2, "colors"),
    ("have",   "/hæv/",      "To own something",                                     "I have a toy car.",                     2, "sight_words"),
    ("he",     "/hiː/",      "Used when talking about a boy or man",                 "He is my best friend.",                 2, "sight_words"),
    ("like",   "/laɪk/",     "To enjoy something",                                   "I like sunny warm days!",               2, "sight_words"),
    ("no",     "/noʊ/",      "The opposite of yes",                                  "No, that is not mine.",                 2, "sight_words"),
    ("on",     "/ɑn/",       "On top of or touching something",                      "The cup is on the table.",              2, "sight_words"),
    ("out",    "/aʊt/",      "Outside or away from inside",                          "Let's go out and play!",                2, "sight_words"),
    ("rain",   "/reɪn/",     "Water drops falling from clouds",                      "The rain made big puddles.",            2, "world"),
    ("said",   "/sɛd/",      "Words that someone spoke out loud",                    "She said hello to me.",                 2, "sight_words"),
    ("she",    "/ʃiː/",      "Used when talking about a girl or woman",              "She has a red hat.",                    2, "sight_words"),
    ("so",     "/soʊ/",      "Very much, or because of that",                        "I am so happy today!",                  2, "sight_words"),
    ("sun",    "/sʌn/",      "The big bright star in the sky",                       "The sun keeps us warm.",                2, "world"),
    ("that",   "/ðæt/",      "A thing a little far from you",                        "Look at that butterfly!",               2, "sight_words"),
    ("they",   "/ðeɪ/",      "More than one person or thing",                        "They are playing tag.",                 2, "sight_words"),
    ("tree",   "/triː/",     "A tall plant with a trunk and branches",               "I climbed the big tree.",               2, "world"),
    ("was",    "/wɑz/",      "How something was in the past",                        "I was so happy yesterday.",             2, "sight_words"),

    # ── Level 3 — Blooming (grade 1 sight words + richer vocabulary) ──────────
    ("again",  "/əˈɡɛn/",    "One more time",                                        "Read it to me again, please!",          3, "sight_words"),
    ("could",  "/kʊd/",      "Might be able to do something",                        "I could hear the music.",               3, "sight_words"),
    ("every",  "/ˈɛv.ri/",   "Each one — all of them",                               "I brush my teeth every night.",         3, "sight_words"),
    ("friend", "/frɛnd/",    "Someone you like and love spending time with",          "You are my best friend!",               3, "people"),
    ("from",   "/frʌm/",     "Where something started or came from",                 "This letter is from grandma.",          3, "sight_words"),
    ("funny",  "/ˈfʌn.i/",   "Something that makes you laugh",                       "That joke was so funny!",               3, "describing"),
    ("give",   "/ɡɪv/",      "To hand something to someone else",                    "Please give me a hug!",                 3, "sight_words"),
    ("happy",  "/ˈhæp.i/",   "Feeling joyful and glad inside",                       "I feel happy on my birthday!",          3, "feelings"),
    ("help",   "/hɛlp/",     "To make things easier for someone",                    "Can you help me, please?",              3, "sight_words"),
    ("how",    "/haʊ/",      "The way something is done",                            "How did you do that?",                  3, "sight_words"),
    ("just",   "/dʒʌst/",    "Only, or a very short time ago",                       "I just brushed my teeth.",              3, "sight_words"),
    ("know",   "/noʊ/",      "To have information in your mind",                     "I know how to tie my shoes!",           3, "sight_words"),
    ("mom",    "/mɑm/",      "Your mother — the woman who takes care of you",        "My mom gives the best hugs.",           3, "people"),
    ("once",   "/wʌns/",     "One single time",                                      "I rode a horse once!",                  3, "sight_words"),
    ("open",   "/ˈoʊ.pən/",  "Not closed, or to make something open",                "Open the present!",                     3, "sight_words"),
    ("over",   "/ˈoʊ.vər/",  "Above something, or all done",                         "The rainbow arched over the hill.",     3, "sight_words"),
    ("please", "/pliːz/",    "A polite word when asking for something",              "Please pass the crackers.",             3, "sight_words"),
    ("some",   "/sʌm/",      "A few of something, but not all",                      "I want some of your cookies.",          3, "sight_words"),
    ("stop",   "/stɑp/",     "To not move or not do something anymore",              "Stop and look both ways.",              3, "sight_words"),
    ("take",   "/teɪk/",     "To pick something up and bring it with you",           "Take an umbrella for the rain.",        3, "sight_words"),
    ("thank",  "/θæŋk/",     "To show you are grateful for something",               "Thank you so much!",                    3, "sight_words"),
    ("walk",   "/wɔːk/",     "To move on your feet at a normal speed",               "Let's walk to the park.",               3, "actions"),
    ("went",   "/wɛnt/",     "Moved to somewhere in the past",                       "We went to the beach.",                 3, "sight_words"),
    ("when",   "/wɛn/",      "At the time something happens",                        "When does dinner start?",               3, "sight_words"),
]


# ── Service ────────────────────────────────────────────────────────────────────

class FlashcardService:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    # ── Internal ──────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")  # connection-level setting
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")  # persists in the DB file
            conn.executescript(_SCHEMA)
            # Migration: add mastered column to existing databases
            try:
                conn.execute(
                    "ALTER TABLE cards ADD COLUMN mastered INTEGER NOT NULL DEFAULT 0"
                )
            except Exception:
                pass  # column already exists
        self._seed_numbers()
        self._seed_vocab_words()

    def _seed_numbers(self) -> None:
        """Populate number cards 0–20 on first run. Idempotent."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE card_type='number'"
            ).fetchone()[0]
        if existing > 0:
            return

        _WORDS = [
            "zero","one","two","three","four","five","six","seven","eight","nine",
            "ten","eleven","twelve","thirteen","fourteen","fifteen","sixteen",
            "seventeen","eighteen","nineteen","twenty",
        ]
        # Emoji that naturally repeats n times to show quantity
        _EMOJI = [
            "🫥","⭐","👁️","🍎","🐾","🖐️","🎯","🌈","🐙","🎈",
            "🙌","🌸","🥚","🍀","❤️","🌙","🎮","🔮","🏆","🚀","🎉",
        ]
        _EXAMPLES = [
            ["Zero means nothing is there", "0 cookies left"],
            ["1 sun in the sky", "You have 1 nose"],
            ["2 eyes on your face", "A bicycle has 2 wheels"],
            ["3 sides on a triangle", "A tricycle has 3 wheels"],
            ["4 legs on a dog", "A square has 4 sides"],
            ["5 fingers on one hand", "A starfish has 5 arms"],
            ["6 sides on a cube", "An insect has 6 legs"],
            ["7 days in a week", "A rainbow has 7 colors"],
            ["8 legs on a spider", "An octopus has 8 arms"],
            ["9 planets were counted long ago", "A cat has 9 lives (they say!)"],
            ["10 fingers on two hands", "10 toes on two feet"],
            ["11 players on a soccer team", "11 comes after 10"],
            ["12 months in a year", "12 eggs in a dozen"],
            ["13 is a baker's dozen", "13 stripes on the US flag"],
            ["14 days in two weeks", "A fortnight is 14 days"],
            ["15 minutes in a quarter hour", "15 players on a rugby team"],
            ["16 ounces in a pound", "Sweet sixteen birthday"],
            ["17 comes between 16 and 18", "A prime number"],
            ["18 holes on a golf course", "18 wheels on a big truck"],
            ["19 comes right before 20", "A prime number"],
            ["20 fingers and toes together", "20/20 is perfect vision"],
        ]

        for n in range(21):
            front = {"digit": n, "emoji": _EMOJI[n]}
            back  = {
                "word_form": _WORDS[n],
                "examples":  _EXAMPLES[n],
            }
            self.create_card("number", front, back)

    def _seed_vocab_words(self) -> None:
        """Populate vocab_words for Seedlings on first run. Idempotent."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) FROM vocab_words WHERE age_band='seedlings'"
            ).fetchone()[0]
        if existing > 0:
            return
        with self._connect() as conn:
            conn.executemany(
                """INSERT OR IGNORE INTO vocab_words
                       (word, phonetic, definition, example, age_band, level, category)
                   VALUES (?,?,?,?,?,?,?)""",
                [
                    (word, phonetic, defn, example, "seedlings", level, category)
                    for word, phonetic, defn, example, level, category in _SEEDLINGS_WORDS
                ],
            )

    def _row_to_card(self, row: sqlite3.Row) -> Card:
        return Card(
            id=row["id"],
            card_type=row["card_type"],
            user_id=row["user_id"],
            front_data=json.loads(row["front_data"]),
            back_data=json.loads(row["back_data"]),
            source_book=row["source_book"],
            source_chapter=row["source_chapter"],
            date_added=row["date_added"],
            ease_factor=row["ease_factor"],
            interval=row["interval"],
            repetitions=row["repetitions"],
            due_date=row["due_date"],
            last_reviewed=row["last_reviewed"],
            review_count=row["review_count"],
        )

    # ── Reads ─────────────────────────────────────────────────────────

    def get_cards(
        self,
        user_id: str = "default",
        card_type: Optional[str] = None,
        source_book: Optional[str] = None,
        due_only: bool = False,
        include_mastered: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Card]:
        clauses = ["user_id = ?"]
        params: list = [user_id]
        if card_type:
            clauses.append("card_type = ?")
            params.append(card_type)
        if source_book:
            clauses.append("source_book = ?")
            params.append(source_book)
        if due_only:
            clauses.append("due_date <= ?")
            params.append(date.today().isoformat())
        if not include_mastered:
            clauses.append("mastered = 0")

        where = " AND ".join(clauses)
        params += [limit, offset]
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM cards WHERE {where} ORDER BY due_date ASC LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self._row_to_card(r) for r in rows]

    def get_card(self, card_id: int, user_id: str = "default") -> Optional[Card]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM cards WHERE id = ? AND user_id = ?",
                (card_id, user_id),
            ).fetchone()
        return self._row_to_card(row) if row else None

    def get_stats(self, user_id: str = "default") -> DeckStats:
        today = date.today().isoformat()
        with self._connect() as conn:
            # Three scalar aggregates in one pass
            agg = conn.execute(
                """SELECT
                       COUNT(*) AS total,
                       SUM(due_date <= ?) AS due_today,
                       SUM(review_count = 0) AS new_cards
                   FROM cards WHERE user_id=?""",
                (today, user_id),
            ).fetchone()
            by_type = {
                r["card_type"]: r["n"]
                for r in conn.execute(
                    "SELECT card_type, COUNT(*) as n FROM cards WHERE user_id=? GROUP BY card_type",
                    (user_id,),
                ).fetchall()
            }
            by_book = {
                r["source_book"]: r["n"]
                for r in conn.execute(
                    "SELECT source_book, COUNT(*) as n FROM cards"
                    " WHERE user_id=? AND source_book IS NOT NULL GROUP BY source_book",
                    (user_id,),
                ).fetchall()
            }
        return DeckStats(
            total=agg["total"] or 0,
            due_today=agg["due_today"] or 0,
            new_cards=agg["new_cards"] or 0,
            by_type=by_type,
            by_book=by_book,
        )

    def get_books(self, user_id: str = "default") -> list[str]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT source_book FROM cards"
                " WHERE user_id=? AND source_book IS NOT NULL ORDER BY source_book",
                (user_id,),
            ).fetchall()
        return [r["source_book"] for r in rows]

    def get_vocab_words(
        self,
        age_band: str,
        level: Optional[int] = None,
        user_id: str = "default",
    ) -> list[dict]:
        """Return curated word list for an age band with in-deck status per word."""
        clauses = ["age_band = ?"]
        params: list = [age_band]
        if level is not None:
            clauses.append("level = ?")
            params.append(level)

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM vocab_words WHERE {' AND '.join(clauses)} ORDER BY level, category, word",
                params,
            ).fetchall()
            card_rows = conn.execute(
                "SELECT id, front_data, mastered FROM cards WHERE card_type='vocabulary' AND user_id=?",
                (user_id,),
            ).fetchall()

        # Map word → {card_id, mastered}
        card_by_word: dict[str, dict] = {}
        for r in card_rows:
            try:
                fd = json.loads(r["front_data"])
                word = fd.get("word", "").lower()
                card_by_word[word] = {"card_id": r["id"], "mastered": bool(r["mastered"])}
            except Exception:
                pass

        return [
            {
                "id":         row["id"],
                "word":       row["word"],
                "phonetic":   row["phonetic"],
                "definition": row["definition"],
                "example":    row["example"],
                "age_band":   row["age_band"],
                "level":      row["level"],
                "category":   row["category"],
                "in_deck":    row["word"].lower() in card_by_word,
                "mastered":   card_by_word.get(row["word"].lower(), {}).get("mastered", False),
                "card_id":    card_by_word.get(row["word"].lower(), {}).get("card_id", None),
            }
            for row in rows
        ]

    def get_vocab_word_counts(self, age_band: str) -> dict:
        """Return total word count and per-level counts for an age band."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT level, COUNT(*) as n FROM vocab_words WHERE age_band=? GROUP BY level",
                (age_band,),
            ).fetchall()
        by_level = {r["level"]: r["n"] for r in rows}
        return {"total": sum(by_level.values()), "by_level": by_level}

    # ── Writes ────────────────────────────────────────────────────────

    def create_card(
        self,
        card_type: str,
        front_data: dict,
        back_data: dict,
        source_book: Optional[str] = None,
        source_chapter: Optional[str] = None,
        user_id: str = "default",
    ) -> Card:
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO cards
                       (card_type, user_id, front_data, back_data, source_book, source_chapter)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    card_type, user_id,
                    json.dumps(front_data), json.dumps(back_data),
                    source_book, source_chapter,
                ),
            )
        return self.get_card(cur.lastrowid, user_id)

    def word_exists(self, word: str, user_id: str = "default") -> Optional[int]:
        """Return card_id if a vocabulary card for this word already exists, else None."""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id FROM cards
                   WHERE card_type='vocabulary' AND user_id=?
                     AND lower(json_extract(front_data, '$.word')) = lower(?)""",
                (user_id, word),
            ).fetchone()
        return row["id"] if row else None

    def delete_card(self, card_id: int, user_id: str = "default") -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM cards WHERE id = ? AND user_id = ?",
                (card_id, user_id),
            )
        return cur.rowcount > 0

    def add_vocab_word_to_deck(
        self,
        vocab_word_id: int,
        user_id: str = "default",
    ) -> Optional[Card]:
        """Create a vocabulary flashcard from a pre-seeded word. Returns None if already in deck."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM vocab_words WHERE id = ?", (vocab_word_id,)
            ).fetchone()
        if not row:
            return None
        if self.word_exists(row["word"], user_id):
            return None
        front = {"word": row["word"], "phonetic": row["phonetic"], "image_url": ""}
        back  = {"definition": row["definition"], "example_sentence": row["example"]}
        return self.create_card("vocabulary", front, back, user_id=user_id)

    def add_vocab_level_to_deck(
        self,
        age_band: str,
        level: int,
        user_id: str = "default",
    ) -> dict:
        """Add all words from a level to the deck. Returns {added, skipped}."""
        words = self.get_vocab_words(age_band=age_band, level=level, user_id=user_id)
        added = skipped = 0
        for w in words:
            if w["in_deck"]:
                skipped += 1
                continue
            card = self.add_vocab_word_to_deck(w["id"], user_id=user_id)
            if card:
                added += 1
            else:
                skipped += 1
        return {"added": added, "skipped": skipped}

    def mark_card_mastered(self, card_id: int, user_id: str = "default") -> bool:
        """Archive a card — removes it from all future review queues."""
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE cards SET mastered=1 WHERE id=? AND user_id=?",
                (card_id, user_id),
            )
        return cur.rowcount > 0

    def unmaster_card(self, card_id: int, user_id: str = "default") -> bool:
        """Return a mastered card to active learning (resets SM-2 streak)."""
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE cards SET mastered=0, due_date=?, repetitions=0,
                       interval=0, ease_factor=2.5
                   WHERE id=? AND user_id=?""",
                (date.today().isoformat(), card_id, user_id),
            )
        return cur.rowcount > 0

    # ── Word definition cache ─────────────────────────────────────────────────

    def get_cached_word(self, word: str) -> Optional[dict]:
        """Return cached definition for a word, or None if not cached."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT phonetic, audio_url, definitions FROM word_cache WHERE word = ?",
                (word.lower(),),
            ).fetchone()
        if not row:
            return None
        return {
            "phonetic":    row["phonetic"],
            "audio_url":   row["audio_url"] or None,
            "definitions": json.loads(row["definitions"]),
        }

    def cache_word(
        self,
        word: str,
        phonetic: str,
        audio_url: str,
        definitions: list[dict],
    ) -> None:
        """Persist a word's definition data so future lookups work offline."""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO word_cache (word, phonetic, audio_url, definitions, fetched_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(word) DO UPDATE SET
                       phonetic    = excluded.phonetic,
                       audio_url   = excluded.audio_url,
                       definitions = excluded.definitions,
                       fetched_at  = excluded.fetched_at""",
                (word.lower(), phonetic, audio_url or "", json.dumps(definitions)),
            )

    def get_vocab_word_definition(self, word: str) -> Optional[dict]:
        """Look up a word in the curated vocab_words table. Returns None if absent."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT phonetic, definition, example FROM vocab_words WHERE word = ? LIMIT 1",
                (word.lower(),),
            ).fetchone()
        if not row or not row["definition"]:
            return None
        return {
            "phonetic":    row["phonetic"],
            "audio_url":   None,
            "definitions": [{"part_of_speech": "", "definition": row["definition"], "example": row["example"]}],
        }

    # ── Reading progress ──────────────────────────────────────────────────────

    def save_reading_progress(
        self,
        book_id: int,
        chapter_index: int,
        word_index: int,
        user_id: str = "default",
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO reading_progress (user_id, book_id, chapter_index, word_index, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now'))
                   ON CONFLICT(user_id, book_id) DO UPDATE SET
                       chapter_index = excluded.chapter_index,
                       word_index    = excluded.word_index,
                       updated_at    = excluded.updated_at""",
                (user_id, book_id, chapter_index, word_index),
            )

    def get_reading_progress(
        self,
        book_id: int,
        user_id: str = "default",
    ) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT chapter_index, word_index FROM reading_progress WHERE user_id=? AND book_id=?",
                (user_id, book_id),
            ).fetchone()
        if not row:
            return None
        return {"chapter_index": row["chapter_index"], "word_index": row["word_index"]}

    def submit_review(
        self,
        card_id: int,
        rating: int,           # 1=Hard, 2=Good, 3=Easy
        user_id: str = "default",
    ) -> Optional[ReviewResult]:
        card = self.get_card(card_id, user_id)
        if not card:
            return None

        new_ef, new_iv, new_reps = _sm2(card.ease_factor, card.interval, card.repetitions, rating)
        new_due = (date.today() + timedelta(days=new_iv)).isoformat()
        now = datetime.utcnow().isoformat()

        with self._connect() as conn:
            conn.execute(
                """UPDATE cards
                   SET ease_factor=?, interval=?, repetitions=?, due_date=?,
                       last_reviewed=?, review_count=review_count+1
                   WHERE id=? AND user_id=?""",
                (new_ef, new_iv, new_reps, new_due, now, card_id, user_id),
            )
        return ReviewResult(
            card_id=card_id,
            new_ease_factor=new_ef,
            new_interval=new_iv,
            new_repetitions=new_reps,
            new_due_date=new_due,
        )

    # ── Quiz sessions ─────────────────────────────────────────────

    def save_quiz_session(
        self,
        card_type: str,
        questions_total: int,
        questions_correct: int,
        set_label: Optional[str] = None,
        user_id: str = "default",
    ) -> int:
        score_pct = round(questions_correct / questions_total * 100, 1) if questions_total else 0
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO quiz_sessions
                       (user_id, card_type, set_label, questions_total, questions_correct, score_pct)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (user_id, card_type, set_label, questions_total, questions_correct, score_pct),
            )
        return cur.lastrowid

    def get_quiz_sessions(
        self,
        user_id: str = "default",
        card_type: Optional[str] = None,
        limit: int = 50,
    ) -> list[dict]:
        clauses = ["user_id = ?"]
        params: list = [user_id]
        if card_type:
            clauses.append("card_type = ?")
            params.append(card_type)
        where = " AND ".join(clauses)
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM quiz_sessions WHERE {where} ORDER BY completed_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [dict(r) for r in rows]
