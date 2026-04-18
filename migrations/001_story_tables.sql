-- Migration 001: My Story feature tables
-- Applied by _run_migrations() in app/__init__.py at startup.
-- Uses CREATE TABLE IF NOT EXISTS so re-running is safe.

CREATE TABLE IF NOT EXISTS characters (
    character_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id            INTEGER NOT NULL,
    name                  TEXT    NOT NULL,
    canonical_description TEXT    NOT NULL DEFAULT '',
    style_descriptor      TEXT    NOT NULL DEFAULT 'watercolor children''s book illustration, soft warm palette',
    generation_seed       TEXT    NOT NULL DEFAULT '',
    provider_name         TEXT    NOT NULL DEFAULT '',
    model_version         TEXT    NOT NULL DEFAULT '',
    avatar_emoji          TEXT    NOT NULL DEFAULT '🐾',
    is_starter            INTEGER NOT NULL DEFAULT 0,
    times_featured        INTEGER NOT NULL DEFAULT 0,
    last_featured_at      TEXT,
    created_at            TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_characters_profile ON characters (profile_id);

CREATE TABLE IF NOT EXISTS story_history (
    story_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id          INTEGER NOT NULL,
    title               TEXT    NOT NULL DEFAULT '',
    characters          TEXT    NOT NULL DEFAULT '[]',
    story_type          TEXT    NOT NULL DEFAULT '',
    length_bucket       TEXT    NOT NULL DEFAULT 'medium',
    virtue_focus        TEXT    NOT NULL DEFAULT '',
    vocabulary_used     TEXT    NOT NULL DEFAULT '[]',
    model_used          TEXT    NOT NULL DEFAULT '',
    full_story_json     TEXT    NOT NULL DEFAULT '{}',
    moderation_events   TEXT    NOT NULL DEFAULT '[]',
    generation_status   TEXT    NOT NULL DEFAULT 'ready',
    completed           INTEGER NOT NULL DEFAULT 0,
    saved_to_library    INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_story_history_profile ON story_history (profile_id, created_at);

CREATE TABLE IF NOT EXISTS vocab_encounters (
    encounter_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    profile_id    INTEGER NOT NULL,
    word          TEXT    NOT NULL,
    story_id      INTEGER NOT NULL,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_vocab_profile ON vocab_encounters (profile_id, word);

CREATE TABLE IF NOT EXISTS streaks (
    profile_id              INTEGER PRIMARY KEY,
    days_read_current       INTEGER NOT NULL DEFAULT 0,
    days_read_longest       INTEGER NOT NULL DEFAULT 0,
    last_read_date          TEXT,
    total_stories_completed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS portrait_cache (
    cache_key      TEXT    PRIMARY KEY,
    profile_id     INTEGER NOT NULL,
    character_id   INTEGER,
    scene_hash     TEXT    NOT NULL DEFAULT '',
    image_url      TEXT    NOT NULL DEFAULT '',
    provider_used  TEXT    NOT NULL DEFAULT '',
    created_at     TEXT    NOT NULL DEFAULT (datetime('now')),
    last_used_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_portrait_profile ON portrait_cache (profile_id);

CREATE TABLE IF NOT EXISTS cloud_spend (
    profile_id    INTEGER NOT NULL,
    month         TEXT    NOT NULL,
    story_spend   REAL    NOT NULL DEFAULT 0.0,
    image_spend   REAL    NOT NULL DEFAULT 0.0,
    last_updated  TEXT    NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (profile_id, month)
);

CREATE TABLE IF NOT EXISTS virtue_rotation (
    profile_id        INTEGER PRIMARY KEY,
    last_virtues_used TEXT    NOT NULL DEFAULT '[]'
);
