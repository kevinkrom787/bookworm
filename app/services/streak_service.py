"""
Streak and stats service — tracks reading streaks and home screen counters.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path


class StreakService:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _empty_streak(self) -> dict:
        return {
            "days_read_current":       0,
            "days_read_longest":       0,
            "last_read_date":          None,
            "total_stories_completed": 0,
        }

    def get_streak(self, profile_id: int) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM streaks WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        return dict(row) if row else self._empty_streak()

    def update_on_complete(self, profile_id: int) -> dict:
        today = date.today().isoformat()
        current = self.get_streak(profile_id)

        last = current["last_read_date"]
        streak = current["days_read_current"]

        if last == today:
            pass  # already counted today
        elif last and _days_between(last, today) == 1:
            streak += 1
        else:
            streak = 1  # gap — reset

        longest = max(current["days_read_longest"], streak)
        total   = current["total_stories_completed"] + 1

        with self._connect() as conn:
            conn.execute(
                """INSERT INTO streaks
                       (profile_id, days_read_current, days_read_longest,
                        last_read_date, total_stories_completed)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(profile_id) DO UPDATE SET
                       days_read_current       = excluded.days_read_current,
                       days_read_longest       = excluded.days_read_longest,
                       last_read_date          = excluded.last_read_date,
                       total_stories_completed = excluded.total_stories_completed""",
                (profile_id, streak, longest, today, total),
            )
        return self.get_streak(profile_id)

    def get_stats(self, profile_id: int) -> dict:
        """Returns the four home screen stat values."""
        streak = self.get_streak(profile_id)
        with self._connect() as conn:
            vocab_row = conn.execute(
                "SELECT COUNT(DISTINCT word) AS n FROM vocab_encounters WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
            char_row = conn.execute(
                "SELECT COUNT(*) AS n FROM characters WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        return {
            "days_read":   streak["days_read_current"],
            "words_saved": vocab_row["n"] if vocab_row else 0,
            "words_tested": 0,  # TODO v0.2: wire to flashcard quiz results
            "characters":  char_row["n"] if char_row else 0,
        }


def _days_between(d1: str, d2: str) -> int:
    a = date.fromisoformat(d1)
    b = date.fromisoformat(d2)
    return (b - a).days
