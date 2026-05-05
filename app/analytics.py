"""
Lightweight event tracking — writes directly to the app's SQLite DB.

Usage:
    analytics.init(db_path)          # once at startup
    analytics.capture(family_id, "signed_up", {"method": "google"})

Each call opens a connection, inserts one row, and closes. No buffering,
no background threads, no data loss on Fly.io machine stops.
"""
import json
import sqlite3
from pathlib import Path
from typing import Optional

_db_path: Optional[Path] = None


def init(db_path: Path) -> None:
    global _db_path
    _db_path = db_path


def capture(family_id: Optional[int], event: str, props: Optional[dict] = None) -> None:
    if not _db_path:
        return
    try:
        with sqlite3.connect(str(_db_path)) as conn:
            conn.execute(
                "INSERT INTO events (family_id, event, props) VALUES (?, ?, ?)",
                (family_id, event, json.dumps(props or {})),
            )
    except Exception:
        pass  # analytics must never crash the app
