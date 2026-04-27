"""
Family service — account + auth for multi-tenant isolation.
Each family is a billing unit; child profiles are scoped under it.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import bcrypt

_SCHEMA = """
CREATE TABLE IF NOT EXISTS families (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    name               TEXT    NOT NULL,
    email              TEXT    NOT NULL UNIQUE,
    password_hash      TEXT    NOT NULL,
    plan               TEXT    NOT NULL DEFAULT 'free',
    stripe_customer_id TEXT,
    created_at         TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass
class Family:
    id: int
    name: str
    email: str
    plan: str
    stripe_customer_id: Optional[str]
    created_at: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "email": self.email, "plan": self.plan}


class FamilyService:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    def _row_to_family(self, row: sqlite3.Row) -> Family:
        return Family(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            plan=row["plan"],
            stripe_customer_id=row["stripe_customer_id"],
            created_at=row["created_at"],
        )

    def create_family(self, name: str, email: str, password: str) -> Optional[Family]:
        """Returns None if email is already registered."""
        pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
        try:
            with self._connect() as conn:
                cur = conn.execute(
                    "INSERT INTO families (name, email, password_hash) VALUES (?, ?, ?)",
                    (name.strip(), email.lower(), pw_hash),
                )
            return self.get_by_id(cur.lastrowid)
        except sqlite3.IntegrityError:
            return None

    def authenticate(self, email: str, password: str) -> Optional[Family]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM families WHERE email = ?", (email.lower(),)
            ).fetchone()
        if not row:
            return None
        if bcrypt.checkpw(password.encode("utf-8"), row["password_hash"].encode("utf-8")):
            return self._row_to_family(row)
        return None

    def get_by_id(self, family_id: int) -> Optional[Family]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM families WHERE id = ?", (family_id,)
            ).fetchone()
        return self._row_to_family(row) if row else None
