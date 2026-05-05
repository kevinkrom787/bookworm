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


# ── Number card seed data (module-level so _ensure_number_cards can reference) ─

_NUMBER_WORDS = [
    "zero","one","two","three","four","five","six","seven","eight","nine",
    "ten","eleven","twelve","thirteen","fourteen","fifteen","sixteen",
    "seventeen","eighteen","nineteen","twenty",
]
_NUMBER_EMOJI = [
    "🫥","⭐","👁️","🍎","🐾","🖐️","🎯","🌈","🐙","🎈",
    "🙌","🌸","🥚","🍀","❤️","🌙","🎮","🔮","🏆","🚀","🎉",
]
_NUMBER_EXAMPLES = [
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


# ── Vocabulary seed data ──────────────────────────────────────────────────────
# Tuples: (word, phonetic, definition, example, level, category)
# level 1 = Adjectives, level 2 = Verbs, level 3 = Nouns (all bands)

_SEEDLINGS_WORDS: list[tuple] = [
    # ── Level 1 — Adjectives ──────────────────────────────────────────────────
    ("big",    "/bɪɡ/",         "Large in size.",                               "The elephant is big.",                      1, "adjectives"),
    ("small",  "/smɔːl/",       "Little in size.",                              "A mouse is small.",                         1, "adjectives"),
    ("happy",  "/ˈhæp.i/",      "Feeling good and joyful.",                     "I feel happy on my birthday!",              1, "adjectives"),
    ("sad",    "/sæd/",          "Feeling unhappy.",                             "She was sad when it rained.",               1, "adjectives"),
    ("fast",   "/fæst/",         "Moving quickly.",                              "The cheetah is very fast.",                 1, "adjectives"),
    ("slow",   "/sloʊ/",         "Moving without speed.",                        "A turtle moves slow.",                      1, "adjectives"),
    ("hot",    "/hɑt/",          "Having a high temperature.",                   "The soup is too hot to eat.",               1, "adjectives"),
    ("cold",   "/koʊld/",        "Having a low temperature.",                    "The ice cream is cold.",                    1, "adjectives"),
    ("soft",   "/sɔːft/",        "Easy to touch, not hard.",                     "The bunny feels soft.",                     1, "adjectives"),
    ("hard",   "/hɑːrd/",        "Firm and not soft.",                           "The rock is very hard.",                    1, "adjectives"),
    ("loud",   "/laʊd/",         "Making a big sound.",                          "The drum is loud!",                         1, "adjectives"),
    ("quiet",  "/ˈkwaɪ.ət/",     "Making little or no sound.",                   "The library is very quiet.",                1, "adjectives"),
    ("bright", "/braɪt/",        "Full of light.",                               "The sun is bright today.",                  1, "adjectives"),
    ("dark",   "/dɑːrk/",        "With little or no light.",                     "It gets dark at night.",                    1, "adjectives"),
    ("clean",  "/kliːn/",        "Not dirty.",                                   "My hands are clean now.",                   1, "adjectives"),
    ("dirty",  "/ˈdɜːr.ti/",     "Not clean.",                                   "His boots were dirty from the mud.",        1, "adjectives"),
    ("sweet",  "/swiːt/",        "Tasting like sugar.",                          "This mango is sweet!",                      1, "adjectives"),
    ("sour",   "/saʊər/",        "Having a sharp taste.",                        "Lemons are sour.",                          1, "adjectives"),
    ("heavy",  "/ˈhɛv.i/",       "Hard to lift.",                                "That box is too heavy for me.",             1, "adjectives"),
    ("light",  "/laɪt/",         "Easy to lift.",                                "A feather is very light.",                  1, "adjectives"),

    # ── Level 2 — Verbs ───────────────────────────────────────────────────────
    ("run",    "/rʌn/",          "To move fast on your feet.",                   "I love to run at the park!",                2, "verbs"),
    ("jump",   "/dʒʌmp/",        "To push off the ground into the air.",         "Can you jump over the puddle?",             2, "verbs"),
    ("eat",    "/iːt/",          "To put food in your mouth and swallow it.",    "I love to eat apples!",                     2, "verbs"),
    ("drink",  "/drɪŋk/",        "To swallow liquid.",                           "Remember to drink your water.",             2, "verbs"),
    ("sleep",  "/sliːp/",        "To rest with your eyes closed.",               "I sleep with my teddy bear.",               2, "verbs"),
    ("wake",   "/weɪk/",         "To stop sleeping.",                            "I wake up when the sun rises.",             2, "verbs"),
    ("play",   "/pleɪ/",         "To have fun with toys or games.",              "Let's play in the yard!",                   2, "verbs"),
    ("walk",   "/wɔːk/",         "To move on your feet slowly.",                 "We walk to school together.",               2, "verbs"),
    ("sit",    "/sɪt/",          "To rest on your bottom.",                      "Please sit down for storytime.",            2, "verbs"),
    ("stand",  "/stænd/",        "To be on your feet.",                          "Stand up tall like a tree!",                2, "verbs"),
    ("clap",   "/klæp/",         "To hit your hands together.",                  "Clap your hands to the music!",             2, "verbs"),
    ("laugh",  "/læf/",          "To make a happy sound when something is funny.", "The joke made me laugh.",                 2, "verbs"),
    ("cry",    "/kraɪ/",         "To make sounds when you are sad or hurt.",     "She started to cry when she fell.",         2, "verbs"),
    ("look",   "/lʊk/",          "To use your eyes to see.",                     "Look at that rainbow!",                     2, "verbs"),
    ("listen", "/ˈlɪs.ən/",      "To pay attention to sounds.",                  "Listen to the birds singing.",              2, "verbs"),
    ("build",  "/bɪld/",         "To make something by putting parts together.", "We can build a tower with blocks!",         2, "verbs"),

    # ── Level 3 — Nouns ───────────────────────────────────────────────────────
    ("dog",    "/dɔɡ/",          "An animal that barks and can be a pet.",       "My dog wags his tail.",                     3, "nouns"),
    ("cat",    "/kæt/",          "A small animal that meows.",                   "The cat sat on the mat.",                   3, "nouns"),
    ("house",  "/haʊs/",         "A place where people live.",                   "Our house has a red door.",                 3, "nouns"),
    ("car",    "/kɑːr/",         "A vehicle that people drive.",                 "Dad drives a blue car.",                    3, "nouns"),
    ("ball",   "/bɔːl/",         "A round object used in games.",                "Kick the ball to me!",                      3, "nouns"),
    ("tree",   "/triː/",         "A tall plant with a trunk and leaves.",        "I climbed the big tree.",                   3, "nouns"),
    ("sun",    "/sʌn/",          "The bright star in the sky that gives light.", "The sun warms our faces.",                  3, "nouns"),
    ("moon",   "/muːn/",         "The object that shines at night.",             "The moon glows in the dark sky.",           3, "nouns"),
    ("water",  "/ˈwɔː.tər/",     "A clear liquid we drink.",                     "I drink water every day.",                  3, "nouns"),
    ("food",   "/fuːd/",         "Things we eat to live.",                       "My favorite food is pasta.",                3, "nouns"),
    ("friend", "/frɛnd/",        "Someone you like and play with.",              "She is my best friend.",                    3, "nouns"),
    ("family", "/ˈfæm.ɪ.li/",    "People who live with you or care for you.",   "I love spending time with my family.",      3, "nouns"),
    ("toy",    "/tɔɪ/",          "Something you play with.",                     "My favorite toy is a train.",               3, "nouns"),
    ("book",   "/bʊk/",          "Pages with words or pictures to read.",        "I read a book before bed.",                 3, "nouns"),
]

_EXPLORERS_WORDS: list[tuple] = [
    # ── Level 1 — Adjectives ──────────────────────────────────────────────────
    ("careful",   "/ˈkɛr.fəl/",     "Paying attention to avoid mistakes.",         "Be careful on the slippery path.",          1, "adjectives"),
    ("helpful",   "/ˈhɛlp.fəl/",    "Giving help to others.",                      "It's kind to be helpful.",                  1, "adjectives"),
    ("honest",    "/ˈɒn.ɪst/",      "Telling the truth.",                          "Always be honest with your friends.",       1, "adjectives"),
    ("fair",      "/fɛr/",           "Treating people equally.",                    "Taking turns is fair.",                     1, "adjectives"),
    ("proud",     "/praʊd/",         "Feeling good about something you did.",       "I felt proud after finishing the race.",    1, "adjectives"),
    ("nervous",   "/ˈnɜːr.vəs/",    "Feeling worried or unsure.",                  "I was nervous before the big test.",        1, "adjectives"),
    ("excited",   "/ɪkˈsaɪ.tɪd/",   "Feeling very happy and eager.",               "She was excited to open her present.",      1, "adjectives"),
    ("bored",     "/bɔːrd/",         "Feeling tired of something.",                 "He was bored on a rainy afternoon.",        1, "adjectives"),
    ("strong",    "/strɔŋ/",         "Having power or strength.",                   "You have to be strong to carry that.",      1, "adjectives"),
    ("weak",      "/wiːk/",          "Not strong.",                                 "He felt weak after being sick.",            1, "adjectives"),
    ("early",     "/ˈɜːr.li/",       "Before the usual time.",                      "She arrived early to save a seat.",         1, "adjectives"),
    ("late",      "/leɪt/",          "After the expected time.",                    "The bus was late this morning.",            1, "adjectives"),
    ("simple",    "/ˈsɪm.pəl/",      "Easy to understand.",                         "The instructions were simple.",             1, "adjectives"),
    ("difficult", "/ˈdɪf.ɪ.kəlt/",  "Hard to do or understand.",                   "The puzzle was difficult.",                 1, "adjectives"),
    ("important", "/ɪmˈpɔːr.tənt/", "Having great value or meaning.",              "Eating breakfast is important.",            1, "adjectives"),

    # ── Level 2 — Verbs ───────────────────────────────────────────────────────
    ("explain",   "/ɪkˈspleɪn/",    "To make something clear by describing it.",   "Can you explain how it works?",             2, "verbs"),
    ("discover",  "/dɪˈskʌv.ər/",   "To find something for the first time.",       "Scientists discover new stars.",            2, "verbs"),
    ("create",    "/kriˈeɪt/",       "To make something new.",                      "She loves to create artwork.",              2, "verbs"),
    ("decide",    "/dɪˈsaɪd/",       "To choose after thinking.",                   "I had to decide which book to read.",       2, "verbs"),
    ("improve",   "/ɪmˈpruːv/",      "To make something better.",                   "Practice can improve your skills.",         2, "verbs"),
    ("solve",     "/sɑlv/",           "To find an answer to a problem.",             "We worked together to solve the puzzle.",   2, "verbs"),
    ("remember",  "/rɪˈmɛm.bər/",   "To keep something in your mind.",             "Remember to bring your lunch!",             2, "verbs"),
    ("forget",    "/fərˈɡɛt/",       "To not remember something.",                  "Don't forget your umbrella.",               2, "verbs"),
    ("imagine",   "/ɪˈmædʒ.ɪn/",    "To form ideas or pictures in your mind.",     "Imagine you're on a tropical island.",      2, "verbs"),
    ("measure",   "/ˈmɛʒ.ər/",       "To find the size or amount of something.",    "We used a ruler to measure the desk.",      2, "verbs"),
    ("collect",   "/kəˈlɛkt/",       "To gather things together.",                  "She likes to collect rocks.",               2, "verbs"),
    ("organize",  "/ˈɔːr.ɡə.naɪz/", "To arrange things in order.",                "Let's organize the books on the shelf.",    2, "verbs"),
    ("practice",  "/ˈpræk.tɪs/",    "To do something again to get better.",        "Practice makes perfect.",                   2, "verbs"),
    ("notice",    "/ˈnoʊ.tɪs/",      "To see or become aware of something.",        "Did you notice the bird outside?",          2, "verbs"),
    ("describe",  "/dɪˈskraɪb/",    "To tell what something is like.",             "Can you describe what you saw?",            2, "verbs"),
    ("predict",   "/prɪˈdɪkt/",      "To say what will happen next.",               "Can you predict the weather?",              2, "verbs"),
    ("compare",   "/kəmˈpɛr/",       "To look for similarities and differences.",   "Compare the two pictures.",                 2, "verbs"),
    ("protect",   "/prəˈtɛkt/",      "To keep safe.",                               "Sunscreen helps protect your skin.",        2, "verbs"),

    # ── Level 3 — Nouns ───────────────────────────────────────────────────────
    ("problem",   "/ˈprɒb.ləm/",    "Something that needs a solution.",            "We need to solve this problem together.",   3, "nouns"),
    ("answer",    "/ˈæn.sər/",       "A response or solution.",                     "What is the answer to question three?",    3, "nouns"),
    ("idea",      "/aɪˈdɪə/",        "A thought or plan.",                          "I had a great idea for the project.",       3, "nouns"),
    ("plan",      "/plæn/",           "A way to do something.",                      "What's your plan for the weekend?",         3, "nouns"),
    ("team",      "/tiːm/",           "A group working together.",                   "Our team won the game!",                    3, "nouns"),
    ("goal",      "/ɡoʊl/",           "Something you want to achieve.",              "My goal is to read ten books this year.",   3, "nouns"),
    ("rule",      "/ruːl/",           "A guide for how to act.",                     "The rule is to raise your hand first.",     3, "nouns"),
    ("habit",     "/ˈhæb.ɪt/",       "Something you do often.",                     "Reading before bed is a good habit.",       3, "nouns"),
    ("skill",     "/skɪl/",           "Something you are good at doing.",            "Drawing is a skill you can learn.",         3, "nouns"),
    ("effort",    "/ˈɛf.ərt/",        "Trying hard to do something.",                "Her effort on the project was great.",      3, "nouns"),
    ("result",    "/rɪˈzʌlt/",        "What happens in the end.",                    "The result of the experiment surprised us.", 3, "nouns"),
    ("example",   "/ɪɡˈzæm.pəl/",   "Something that shows what something is like.", "Can you give me an example?",              3, "nouns"),
    ("pattern",   "/ˈpæt.ərn/",      "Something that repeats.",                     "The wallpaper has a flower pattern.",       3, "nouns"),
    ("choice",    "/tʃɔɪs/",          "A decision between options.",                 "It was a difficult choice.",                3, "nouns"),
    ("reason",    "/ˈriː.zən/",       "Why something happens.",                      "What is your reason for being late?",       3, "nouns"),
    ("energy",    "/ˈɛn.ər.dʒi/",    "The ability to do work or move.",             "The sun gives off lots of energy.",         3, "nouns"),
    ("solution",  "/səˈluː.ʃən/",    "The answer to a problem.",                    "We found a solution to the problem.",       3, "nouns"),
]

_ADVENTURERS_WORDS: list[tuple] = [
    # ── Level 1 — Adjectives ──────────────────────────────────────────────────
    ("accurate",    "/ˈæk.jʊ.rɪt/",      "Correct and exact.",                       "The measurement was accurate.",             1, "adjectives"),
    ("relevant",    "/ˈrɛl.ɪ.vənt/",     "Related to the topic.",                    "Only add relevant information.",            1, "adjectives"),
    ("significant", "/sɪɡˈnɪf.ɪ.kənt/", "Important or meaningful.",                 "The discovery was significant.",            1, "adjectives"),
    ("complex",     "/ˈkɒm.plɛks/",      "Made of many parts.",                      "The puzzle was complex.",                   1, "adjectives"),
    ("efficient",   "/ɪˈfɪʃ.ənt/",       "Working well with little waste.",           "An efficient engine uses less fuel.",       1, "adjectives"),
    ("logical",     "/ˈlɒdʒ.ɪ.kəl/",    "Based on clear reasoning.",                "Her argument was logical.",                 1, "adjectives"),
    ("consistent",  "/kənˈsɪs.tənt/",    "Staying the same over time.",              "He was consistent in his efforts.",         1, "adjectives"),
    ("reliable",    "/rɪˈlaɪ.ə.bəl/",   "Able to be trusted.",                      "She was a reliable teammate.",              1, "adjectives"),
    ("flexible",    "/ˈflɛk.sɪ.bəl/",   "Able to change easily.",                   "Be flexible when plans change.",            1, "adjectives"),
    ("independent", "/ˌɪn.dɪˈpɛn.dənt/","Not relying on others.",                   "He was independent in his work.",           1, "adjectives"),
    ("critical",    "/ˈkrɪt.ɪ.kəl/",    "Involving careful judgment.",              "Critical thinking helps solve problems.",   1, "adjectives"),
    ("creative",    "/kriˈeɪ.tɪv/",      "Using imagination to make new ideas.",     "She gave a creative solution.",             1, "adjectives"),
    ("objective",   "/əbˈdʒɛk.tɪv/",    "Based on facts, not feelings.",            "Try to be objective in your review.",       1, "adjectives"),
    ("subjective",  "/səbˈdʒɛk.tɪv/",   "Based on personal opinions.",              "Taste in music is subjective.",             1, "adjectives"),
    ("precise",     "/prɪˈsaɪs/",        "Exact and accurate.",                      "The scientist was precise with measurements.", 1, "adjectives"),

    # ── Level 2 — Verbs ───────────────────────────────────────────────────────
    ("analyze",     "/ˈæn.ə.laɪz/",     "To study something carefully in parts.",    "We will analyze the data.",                 2, "verbs"),
    ("evaluate",    "/ɪˈvæl.jʊ.eɪt/",  "To judge the value or quality of something.", "Evaluate the pros and cons.",             2, "verbs"),
    ("interpret",   "/ɪnˈtɜːr.prɪt/",  "To explain the meaning of something.",      "How do you interpret this graph?",          2, "verbs"),
    ("summarize",   "/ˈsʌm.ə.raɪz/",   "To give the main points briefly.",          "Can you summarize the chapter?",            2, "verbs"),
    ("justify",     "/ˈdʒʌs.tɪ.faɪ/",  "To give reasons for something.",            "Justify your answer with evidence.",        2, "verbs"),
    ("demonstrate", "/ˈdɛm.ən.streɪt/", "To show how something works.",              "She will demonstrate the experiment.",      2, "verbs"),
    ("investigate", "/ɪnˈvɛs.tɪ.ɡeɪt/","To look into something carefully.",         "Scientists investigate new medicines.",     2, "verbs"),
    ("construct",   "/kənˈstrʌkt/",     "To build or form something.",               "They will construct a model bridge.",       2, "verbs"),
    ("generate",    "/ˈdʒɛn.ər.eɪt/",  "To produce or create.",                     "Solar panels generate electricity.",        2, "verbs"),
    ("transform",   "/trænsˈfɔːrm/",   "To change form.",                           "Heat can transform ice into water.",        2, "verbs"),
    ("maintain",    "/meɪnˈteɪn/",      "To keep something in good condition.",      "We must maintain the park's cleanliness.",  2, "verbs"),
    ("adapt",       "/əˈdæpt/",         "To adjust to new conditions.",              "Animals adapt to their environments.",      2, "verbs"),
    ("contrast",    "/ˈkɒn.træst/",     "To show differences.",                      "Contrast the two characters in the story.", 2, "verbs"),
    ("classify",    "/ˈklæs.ɪ.faɪ/",   "To group by type.",                         "We can classify animals by what they eat.", 2, "verbs"),
    ("conclude",    "/kənˈkluːd/",      "To decide based on evidence.",              "What can we conclude from this data?",      2, "verbs"),
    ("infer",       "/ɪnˈfɜːr/",        "To figure out using clues and reasoning.",  "What can you infer from the passage?",      2, "verbs"),

    # ── Level 3 — Nouns ───────────────────────────────────────────────────────
    ("evidence",    "/ˈɛv.ɪ.dəns/",    "Facts that support a claim.",               "What evidence supports your theory?",       3, "nouns"),
    ("argument",    "/ˈɑːr.ɡjʊ.mənt/", "A claim supported by reasons.",             "Build a strong argument for your position.", 3, "nouns"),
    ("conclusion",  "/kənˈkluː.ʒən/",  "A final decision or judgment.",             "What is your conclusion?",                  3, "nouns"),
    ("theory",      "/ˈθɪər.i/",        "An explanation based on evidence.",         "Darwin's theory changed how we see life.",  3, "nouns"),
    ("process",     "/ˈprɒ.sɛs/",       "A series of steps.",                        "Explain the process step by step.",         3, "nouns"),
    ("system",      "/ˈsɪs.təm/",       "Parts working together.",                   "The solar system has eight planets.",       3, "nouns"),
    ("concept",     "/ˈkɒn.sɛpt/",      "An idea or general understanding.",         "Gravity is a scientific concept.",          3, "nouns"),
    ("factor",      "/ˈfæk.tər/",       "Something that affects a result.",          "Weather is a factor in the game.",          3, "nouns"),
    ("impact",      "/ˈɪm.pækt/",       "A strong effect or influence.",             "Technology has a big impact on our lives.", 3, "nouns"),
    ("structure",   "/ˈstrʌk.tʃər/",   "How something is arranged.",               "Study the structure of the poem.",          3, "nouns"),
    ("function",    "/ˈfʌŋk.ʃən/",     "The purpose of something.",                "What is the function of the heart?",        3, "nouns"),
    ("data",        "/ˈdeɪ.tə/",        "Information collected for study.",          "The data showed a clear pattern.",          3, "nouns"),
    ("method",      "/ˈmɛθ.əd/",        "A way of doing something.",                 "Which method will you use?",                3, "nouns"),
    ("context",     "/ˈkɒn.tɛkst/",    "The situation around something.",           "Always read words in context.",             3, "nouns"),
    ("variable",    "/ˈvɛr.i.ə.bəl/",  "Something that can change.",               "Change one variable at a time in tests.",   3, "nouns"),
    ("consequence", "/ˈkɒn.sɪ.kwəns/", "A result of an action.",                   "Think about the consequences first.",       3, "nouns"),
    ("motivation",  "/ˌmoʊ.tɪˈveɪ.ʃən/","The reason for doing something.",          "What is your motivation for this project?", 3, "nouns"),
    ("assumption",  "/əˈsʌmp.ʃən/",    "Something believed without proof.",         "Don't make assumptions without checking.",  3, "nouns"),
    ("perspective", "/pərˈspɛk.tɪv/",  "A way of thinking about something.",        "Each person has a different perspective.",  3, "nouns"),
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
            # Migration: replace old Dolch-based word list with new curated lists
            try:
                old_seed = conn.execute(
                    "SELECT id FROM vocab_words WHERE word='a' AND age_band='seedlings'"
                ).fetchone()
                if old_seed:
                    conn.execute("DELETE FROM vocab_words")
                    conn.execute(
                        "DELETE FROM cards WHERE card_type='vocabulary' AND source_book IS NULL"
                    )
            except Exception:
                pass
        self._seed_numbers()
        self._seed_vocab_words()

    def _seed_numbers(self) -> None:
        self._ensure_number_cards("default")

    def _ensure_number_cards(self, user_id: str) -> None:
        """Seed number cards 0–20 for a user on first access. Idempotent."""
        with self._connect() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) FROM cards WHERE card_type='number' AND user_id=?",
                (user_id,)
            ).fetchone()[0]
        if existing > 0:
            return
        for n in range(21):
            front = {"digit": n, "emoji": _NUMBER_EMOJI[n]}
            back  = {"word_form": _NUMBER_WORDS[n], "examples": _NUMBER_EXAMPLES[n]}
            self.create_card("number", front, back, user_id=user_id)

    def _seed_vocab_words(self) -> None:
        """Populate vocab_words for all age bands on first run. Idempotent."""
        for band, words in [
            ("seedlings",   _SEEDLINGS_WORDS),
            ("explorers",   _EXPLORERS_WORDS),
            ("adventurers", _ADVENTURERS_WORDS),
        ]:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT COUNT(*) FROM vocab_words WHERE age_band=?", (band,)
                ).fetchone()[0]
            if existing > 0:
                continue
            with self._connect() as conn:
                conn.executemany(
                    """INSERT OR IGNORE INTO vocab_words
                           (word, phonetic, definition, example, age_band, level, category)
                       VALUES (?,?,?,?,?,?,?)""",
                    [
                        (word, phonetic, defn, example, band, level, category)
                        for word, phonetic, defn, example, level, category in words
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
        category: Optional[str] = None,
        due_only: bool = False,
        include_mastered: bool = False,
        limit: int = 200,
        offset: int = 0,
    ) -> list[Card]:
        self._ensure_number_cards(user_id)
        clauses = ["user_id = ?"]
        params: list = [user_id]
        if card_type:
            clauses.append("card_type = ?")
            params.append(card_type)
        if source_book:
            clauses.append("source_book = ?")
            params.append(source_book)
        if category:
            clauses.append("json_extract(front_data, '$.category') = ?")
            params.append(category)
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
        self._ensure_number_cards(user_id)
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

    def get_vocab_word_by_name(self, word: str, age_band: str = ""):
        """Look up a word in the curated vocab_words table. Returns the best match or None."""
        with self._connect() as conn:
            # Prefer exact age-band match; fall back to any band
            row = conn.execute(
                """SELECT word, phonetic, definition, example FROM vocab_words
                   WHERE lower(word) = lower(?)
                   ORDER BY CASE WHEN age_band = ? THEN 0 ELSE 1 END LIMIT 1""",
                (word, age_band),
            ).fetchone()
        return dict(row) if row else None

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
        front = {
            "word":     row["word"],
            "phonetic": row["phonetic"],
            "image_url": "",
            "category": row["category"],
            "level":    row["level"],
            "age_band": row["age_band"],
        }
        back = {"definition": row["definition"], "example_sentence": row["example"]}
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

    def ensure_vocab_in_deck(
        self,
        age_band: str,
        level: Optional[int] = None,
        user_id: str = "default",
    ) -> dict:
        """Auto-add all vocab words for a band (or specific level) that aren't yet in deck."""
        words = self.get_vocab_words(age_band=age_band, level=level, user_id=user_id)
        added = skipped = 0
        for w in words:
            if w["in_deck"] or w["mastered"]:
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

    # ── Story word cards ──────────────────────────────────────────────────────

    def add_story_word_to_deck(
        self,
        word: str,
        story_id: int,
        story_title: str,
        phonetic: str = "",
        definition: str = "",
        example: str = "",
        user_id: str = "default",
    ) -> Optional[Card]:
        """Create a story_word flashcard. Returns None if already in deck for this story."""
        with self._connect() as conn:
            existing = conn.execute(
                """SELECT id FROM cards
                   WHERE user_id=? AND card_type='story_word'
                     AND lower(json_extract(front_data,'$.word'))=lower(?)
                     AND json_extract(front_data,'$.story_id')=?""",
                (user_id, word, story_id),
            ).fetchone()
        if existing:
            return None
        front = {"word": word, "phonetic": phonetic, "story_id": story_id, "story_title": story_title}
        back  = {"definition": definition, "example_sentence": example}
        return self.create_card("story_word", front, back, user_id=user_id)

    def get_story_words_status(
        self,
        story_id: int,
        words: list,
        user_id: str = "default",
    ) -> dict:
        """Returns {word: bool} indicating which words are already in deck for this story."""
        if not words:
            return {}
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT lower(json_extract(front_data,'$.word')) AS word FROM cards
                   WHERE user_id=? AND card_type='story_word'
                     AND json_extract(front_data,'$.story_id')=?""",
                (user_id, story_id),
            ).fetchall()
        in_deck = {r["word"] for r in rows}
        return {w: w.lower() in in_deck for w in words}

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

    def get_all_reading_progress(self, user_id: str = "default") -> list[dict]:
        """All books with saved progress, most-recently-read first."""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT book_id, chapter_index, word_index, updated_at
                   FROM reading_progress WHERE user_id=? ORDER BY updated_at DESC""",
                (user_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_parent_summary(self, user_id: str = "default") -> dict:
        """All stats needed for the parent dashboard in one DB round-trip."""
        with self._connect() as conn:
            # Vocab card breakdown
            card_rows = conn.execute(
                """SELECT card_type,
                          COUNT(*)                                        AS total,
                          SUM(CASE WHEN mastered=1 THEN 1 ELSE 0 END)    AS mastered,
                          SUM(CASE WHEN date_added >= date('now','-7 days')
                                   THEN 1 ELSE 0 END)                    AS added_week,
                          SUM(CASE WHEN source_book IS NOT NULL
                                   THEN 1 ELSE 0 END)                    AS from_books
                   FROM cards WHERE user_id=? GROUP BY card_type""",
                (user_id,),
            ).fetchall()

            # Quiz sessions — last 5 + 30-day average
            recent_quizzes = conn.execute(
                """SELECT card_type, set_label, questions_total, questions_correct,
                          score_pct, completed_at
                   FROM quiz_sessions WHERE user_id=? ORDER BY completed_at DESC LIMIT 5""",
                (user_id,),
            ).fetchall()
            avg_row = conn.execute(
                """SELECT AVG(score_pct) AS avg, COUNT(*) AS n
                   FROM quiz_sessions
                   WHERE user_id=? AND completed_at >= date('now','-30 days')""",
                (user_id,),
            ).fetchone()

            # Words ever looked up
            lookup_count = conn.execute(
                "SELECT COUNT(*) AS n FROM word_cache"
            ).fetchone()["n"]

        # Aggregate card stats
        vocab = {"total": 0, "mastered": 0, "added_week": 0, "from_books": 0, "by_type": {}}
        for r in card_rows:
            vocab["total"]      += r["total"]
            vocab["mastered"]   += r["mastered"] or 0
            vocab["added_week"] += r["added_week"] or 0
            vocab["from_books"] += r["from_books"] or 0
            vocab["by_type"][r["card_type"]] = {
                "total":    r["total"],
                "mastered": r["mastered"] or 0,
            }

        return {
            "vocab": vocab,
            "quizzes": {
                "recent":        [dict(r) for r in recent_quizzes],
                "avg_score_30d": round(avg_row["avg"], 1) if avg_row["avg"] else None,
                "total_30d":     avg_row["n"],
            },
            "words_looked_up": lookup_count,
        }

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
