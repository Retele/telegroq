"""Pluggable conversation-history stores.

A :class:`~telegroq.Character` keeps one conversation per user id. By default
it lives in memory and disappears on restart; pass ``store=SQLiteHistoryStore(
"history.db")`` to ``setCh`` to keep conversations across restarts, or subclass
:class:`HistoryStore` to use Redis, Postgres and so on.

A conversation is a list of ``{"role": "user" | "assistant", "content": str}``
dicts, oldest first. Trimming to ``max_history`` is done by the character, not
the store. The character serialises calls *per user*, but a store may be called
for different users from different threads at the same time, so implementations
must be thread-safe.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from abc import ABC, abstractmethod
from os import PathLike

__all__ = ["HistoryStore", "MemoryHistoryStore", "SQLiteHistoryStore"]

Turn = dict[str, str]


class HistoryStore(ABC):
    """Interface for conversation storage backends."""

    @abstractmethod
    def load(self, user_id: int) -> list[Turn]:
        """Return the stored conversation (empty list if none). Must return a copy."""

    @abstractmethod
    def save(self, user_id: int, messages: list[Turn]) -> None:
        """Replace the stored conversation of ``user_id``."""

    @abstractmethod
    def clear(self, user_id: int) -> None:
        """Delete the conversation of ``user_id`` (no error if there is none)."""

    def close(self) -> None:  # noqa: B027 - optional hook, intentionally not abstract
        """Release resources. Optional."""


class MemoryHistoryStore(HistoryStore):
    """Keeps conversations in a dict. Fast, but lost when the process exits."""

    def __init__(self) -> None:
        self._data: dict[int, list[Turn]] = {}
        self._lock = threading.Lock()

    def load(self, user_id: int) -> list[Turn]:
        with self._lock:
            return [dict(m) for m in self._data.get(user_id, [])]

    def save(self, user_id: int, messages: list[Turn]) -> None:
        with self._lock:
            self._data[user_id] = [dict(m) for m in messages]

    def clear(self, user_id: int) -> None:
        with self._lock:
            self._data.pop(user_id, None)


class SQLiteHistoryStore(HistoryStore):
    """Persists conversations in a SQLite file (standard library only).

    Args:
        path: Database file, created if missing. ``":memory:"`` gives a private
            in-memory database (handy for tests).
        table: Table name; letters, digits and underscores only. Use different
            tables to share one file between several characters.
    """

    def __init__(self, path: str | PathLike[str] = "telegroq_history.db", *, table: str = "history") -> None:
        if not table.replace("_", "a").isalnum():
            raise ValueError("table must contain only letters, digits and underscores")
        self._table = table
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        with self._lock, self._conn:
            self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} (user_id INTEGER PRIMARY KEY, data TEXT NOT NULL)"
            )

    def load(self, user_id: int) -> list[Turn]:
        with self._lock:
            row = self._conn.execute(f"SELECT data FROM {self._table} WHERE user_id = ?", (user_id,)).fetchone()
        return json.loads(row[0]) if row else []

    def save(self, user_id: int, messages: list[Turn]) -> None:
        payload = json.dumps(messages, ensure_ascii=False)
        with self._lock, self._conn:
            self._conn.execute(
                f"INSERT INTO {self._table} (user_id, data) VALUES (?, ?) "
                "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
                (user_id, payload),
            )

    def clear(self, user_id: int) -> None:
        with self._lock, self._conn:
            self._conn.execute(f"DELETE FROM {self._table} WHERE user_id = ?", (user_id,))

    def close(self) -> None:
        with self._lock:
            self._conn.close()
