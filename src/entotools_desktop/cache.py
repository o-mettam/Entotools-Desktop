"""SQLite key/value cache with expiry: the desktop stand-in for Cloudflare KV.

Expired entries are kept (not deleted) so that, when the computer is offline,
the last known answer can still be served (`allow_stale=True`). They are
trimmed by `purge()` once they are well past their expiry.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

STALE_KEEP_SECONDS = 365 * 86400  # how long an expired entry is kept for offline use


class Cache:
    def __init__(self, path: Path | str):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS cache ("
            " key TEXT PRIMARY KEY, value TEXT NOT NULL,"
            " stored_at REAL NOT NULL, expires_at REAL)"  # NULL = never expires
        )
        self._db.commit()

    def get(self, key: str, allow_stale: bool = False):
        with self._lock:
            row = self._db.execute("SELECT value, expires_at FROM cache WHERE key = ?", (key,)).fetchone()
        if not row:
            return None
        value, expires_at = row
        if expires_at is not None and expires_at < time.time() and not allow_stale:
            return None
        return json.loads(value)

    def put(self, key: str, value, ttl_seconds: float | None) -> None:
        now = time.time()
        expires = None if not ttl_seconds else now + ttl_seconds
        with self._lock:
            self._db.execute(
                "INSERT INTO cache (key, value, stored_at, expires_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value, stored_at = excluded.stored_at, expires_at = excluded.expires_at",
                (key, json.dumps(value, separators=(",", ":")), now, expires),
            )
            self._db.commit()

    def purge(self) -> int:
        cutoff = time.time() - STALE_KEEP_SECONDS
        with self._lock:
            n = self._db.execute("DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at < ?", (cutoff,)).rowcount
            self._db.commit()
        return n

    def close(self) -> None:
        with self._lock:
            self._db.close()
