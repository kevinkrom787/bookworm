-- Migration 005: User event tracking (funnel analytics)
-- One row per event. props is a JSON blob for any extra context.

CREATE TABLE IF NOT EXISTS events (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id  INTEGER,
    event      TEXT NOT NULL,
    props      TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_events_event      ON events(event);
CREATE INDEX IF NOT EXISTS idx_events_family_id  ON events(family_id);
CREATE INDEX IF NOT EXISTS idx_events_created_at ON events(created_at)
