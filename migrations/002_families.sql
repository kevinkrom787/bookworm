-- Migration 002: Family accounts (multi-tenant auth)
-- Applied by _run_migrations() at startup. Idempotent.

CREATE TABLE IF NOT EXISTS families (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT    NOT NULL,
    email              TEXT    NOT NULL UNIQUE,
    password_hash      TEXT    NOT NULL,
    plan               TEXT    NOT NULL DEFAULT 'free',
    stripe_customer_id TEXT,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- Ensure child_profiles exists with family_id (handles fresh DB before profile_service runs)
CREATE TABLE IF NOT EXISTS child_profiles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT    NOT NULL,
    age          INTEGER NOT NULL DEFAULT 7,
    age_band     TEXT    NOT NULL DEFAULT 'explorers',
    avatar_emoji TEXT    NOT NULL DEFAULT '🦁',
    avatar_color TEXT    NOT NULL DEFAULT '#6C8EF5',
    interests    TEXT    NOT NULL DEFAULT '[]',
    fun_facts    TEXT    NOT NULL DEFAULT '{}',
    family_id    INTEGER REFERENCES families(id),
    created_at   TEXT    NOT NULL DEFAULT (datetime('now'))
);

-- For existing DBs: add family_id column.
-- Silently ignored if column already exists (see _run_migrations error handling).
ALTER TABLE child_profiles ADD COLUMN family_id INTEGER REFERENCES families(id);
