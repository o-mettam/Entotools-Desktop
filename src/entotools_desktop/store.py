"""The app's database (SQLite): the collection, page preferences, settings,
plus import and automatic CSV backups.

The collection keeps the web store's shape (public/sync/sync-core.js):
an envelope {schemaVersion, deviceId, revision, updatedAt, entries[]} where
each entry is {id, createdAt, updatedAt, deleted, data, ...}. Deleted
entries stay as tombstones so a backup made before a deletion can't bring the
record back by accident on import.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import uuid
from pathlib import Path

from . import csvio

log = logging.getLogger(__name__)

SCHEMA_VERSION = 1           # this database's layout (PRAGMA user_version)
ENVELOPE_SCHEMA_VERSION = 2  # the web store's envelope version
MAX_ENTRIES = 100_000
KV_KEY_RE = re.compile(r"[A-Za-z0-9_.:\-]{1,100}", re.ASCII)
KV_MAX_VALUE = 5_000_000
BACKUP_PATTERN = re.compile(r"EntoTools-backup-\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(-\d+)?\.csv")
DEFAULT_BACKUP_KEEP = 30


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _ts(v) -> float:
    """Date.parse-ish: ISO timestamp → epoch seconds, 0 if missing/invalid."""
    if not isinstance(v, str) or not v:
        return 0.0
    try:
        return dt.datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _canonical(v):
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)  # 88.0 and 88 are the same value (JSON and CSV write it as 88)
    if isinstance(v, dict):
        return {k: _canonical(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_canonical(x) for x in v]
    return v


def content_key(data: dict) -> str:
    """Fingerprint of a record's *values*: key order, 88 vs 88.0, a missing
    text field vs '', and a missing isRange vs false are all ignored, since
    a CSV round trip can't tell them apart."""
    d = _canonical(dict(data))
    for k in csvio.TEXT_FIELDS:
        if d.get(k) is None:
            d[k] = ""
    for k in csvio.NUMBER_FIELDS:
        d.setdefault(k, None)
    d["isRange"] = bool(d.get("isRange"))
    hum = d.get("humidity") or {}
    d["humidity"] = {"atTime": hum.get("atTime"), "avg": hum.get("avg")}
    return json.dumps(d, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class StoreError(ValueError):
    pass


class Store:
    def __init__(self, db_path: Path | str, default_backup_dir: Path | str):
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self.default_backup_dir = Path(default_backup_dir)
        self._migrate()

    # ── schema ───────────────────────────────────────────────────
    def _migrate(self) -> None:
        with self._lock:
            version = self._db.execute("PRAGMA user_version").fetchone()[0]
            if version < 1:
                self._db.executescript("""
                    BEGIN;
                    CREATE TABLE IF NOT EXISTS collection_entries (
                        id TEXT PRIMARY KEY,
                        position INTEGER NOT NULL,
                        created_at TEXT,
                        updated_at TEXT,
                        deleted INTEGER NOT NULL DEFAULT 0,
                        entry_json TEXT NOT NULL
                    );
                    CREATE TABLE IF NOT EXISTS collection_meta (k TEXT PRIMARY KEY, v TEXT);
                    CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
                    CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                    PRAGMA user_version = 1;
                    COMMIT;
                """)
            if version > SCHEMA_VERSION:
                log.warning("database is newer (v%s) than this app (v%s)", version, SCHEMA_VERSION)

    # ── settings (backend-only) ──────────────────────────────────
    def get_setting(self, key: str, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_setting(self, key: str, value) -> None:
        with self._lock:
            self._db.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                             (key, json.dumps(value)))

    # ── kv (the pages' former localStorage) ──────────────────────
    def kv_all(self) -> dict[str, str]:
        with self._lock:
            return dict(self._db.execute("SELECT key, value FROM kv").fetchall())

    def kv_set(self, key: str, value: str) -> None:
        if not KV_KEY_RE.fullmatch(key or ""):
            raise StoreError("Invalid key.")
        if not isinstance(value, str) or len(value) > KV_MAX_VALUE:
            raise StoreError("Value must be text of at most 5 MB.")
        with self._lock:
            self._db.execute("INSERT INTO kv (key, value, updated_at) VALUES (?, ?, ?) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                             (key, value, now_iso()))

    def kv_delete(self, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM kv WHERE key = ?", (key,))

    # ── collection ───────────────────────────────────────────────
    def _meta(self) -> dict:
        rows = dict(self._db.execute("SELECT k, v FROM collection_meta").fetchall())
        if "deviceId" not in rows:
            rows["deviceId"] = str(uuid.uuid4())
            self._db.execute("INSERT INTO collection_meta (k, v) VALUES ('deviceId', ?)", (rows["deviceId"],))
        return rows

    def _set_meta(self, **kw) -> None:
        for k, v in kw.items():
            self._db.execute("INSERT INTO collection_meta (k, v) VALUES (?, ?) ON CONFLICT(k) DO UPDATE SET v = excluded.v", (k, str(v)))

    def _entries(self) -> list[dict]:
        return [json.loads(r[0]) for r in self._db.execute("SELECT entry_json FROM collection_entries ORDER BY position")]

    def get_envelope(self) -> dict | None:
        with self._lock:
            meta = self._meta()
            if "revision" not in meta:
                return None
            return {"schemaVersion": ENVELOPE_SCHEMA_VERSION, "deviceId": meta["deviceId"],
                    "revision": int(meta["revision"]), "updatedAt": meta.get("updatedAt"),
                    "entries": self._entries()}

    @staticmethod
    def _normalize(e: dict) -> dict:
        if not isinstance(e, dict):
            raise StoreError("Every entry must be an object.")
        e = dict(e)
        if not isinstance(e.get("id"), str) or not e["id"]:
            e["id"] = str(uuid.uuid4())
        e.setdefault("createdAt", now_iso())
        e.setdefault("updatedAt", e["createdAt"])
        e["deleted"] = bool(e.get("deleted", False))
        return e

    def _write_entries(self, entries: list[dict]) -> None:
        self._db.execute("DELETE FROM collection_entries")
        self._db.executemany(
            "INSERT INTO collection_entries (id, position, created_at, updated_at, deleted, entry_json) VALUES (?, ?, ?, ?, ?, ?)",
            [(e["id"], i, e.get("createdAt"), e.get("updatedAt"), int(e["deleted"]),
              json.dumps(e, ensure_ascii=False, separators=(",", ":"))) for i, e in enumerate(entries)])

    def save_envelope(self, snapshot: dict) -> dict:
        """PUT /api/collection — the page sends its whole store."""
        if not isinstance(snapshot, dict) or not isinstance(snapshot.get("entries"), list):
            raise StoreError("Malformed snapshot.")
        if len(snapshot["entries"]) > MAX_ENTRIES:
            raise StoreError(f"Collection is too large (limit {MAX_ENTRIES:,} entries).")
        entries = [self._normalize(e) for e in snapshot["entries"]]
        seen = set()
        for e in entries:  # duplicate ids: keep the first, re-id the rest
            if e["id"] in seen:
                e["id"] = str(uuid.uuid4())
            seen.add(e["id"])
        revision = snapshot.get("revision")
        revision = int(revision) if isinstance(revision, (int, float)) and revision >= 1 else 1
        updated = now_iso()
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                self._write_entries(entries)
                self._meta()
                self._set_meta(revision=revision, updatedAt=updated)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return {"modifiedTime": updated, "revision": revision}

    def active_entries(self) -> list[dict]:
        with self._lock:
            return [e for e in self._entries() if not e.get("deleted")]

    # ── import ───────────────────────────────────────────────────
    def import_records(self, incoming: list[dict]) -> dict:
        """Merge records into the collection. Returns counts.

        With an id: newer Updated At wins (an older or equal row never
        overwrites, and never revives a deleted record). Without an id
        (website CSV): added unless an identical active record exists."""
        counts = {"added": 0, "updated": 0, "unchanged": 0, "kept_newer": 0, "duplicates": 0}
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                entries = self._entries()
                by_id = {e["id"]: e for e in entries}
                fingerprints = {content_key(e.get("data") or {}) for e in entries if not e.get("deleted")}
                now = now_iso()
                for rec in incoming:
                    data = rec.get("data") or {}
                    rid = rec.get("id")
                    existing = by_id.get(rid) if rid else None
                    if existing is None:
                        # Website rows have no id: skip one that matches a record
                        # that was already here, so re-importing a file is safe.
                        # (Only pre-existing records count: two identical rows in
                        # one file can be two real specimens.)
                        if not rid and content_key(data) in fingerprints:
                            counts["duplicates"] += 1
                            continue
                        new = {"id": rid or str(uuid.uuid4()), "createdAt": rec.get("createdAt") or now,
                               "updatedAt": rec.get("updatedAt") or now, "deleted": False, "data": data}
                        entries.append(new)
                        by_id[new["id"]] = new
                        counts["added"] += 1
                    elif _ts(rec.get("updatedAt")) > _ts(existing.get("updatedAt")):
                        existing.update({"data": data, "updatedAt": rec["updatedAt"], "deleted": False})
                        if rec.get("createdAt"):
                            existing["createdAt"] = rec["createdAt"]
                        counts["updated"] += 1
                    elif not existing.get("deleted") and content_key(existing.get("data") or {}) == content_key(data):
                        counts["unchanged"] += 1
                    else:
                        counts["kept_newer"] += 1
                if counts["added"] or counts["updated"]:
                    self._write_entries(entries)
                    meta = self._meta()
                    self._set_meta(revision=int(meta.get("revision", 0)) + 1, updatedAt=now)
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return counts

    def import_text(self, kind: str, text: str) -> dict:
        """POST /api/collection/import — a CSV (desktop or website) or a JSON
        export (website account export, or a raw store envelope)."""
        problems: list[str] = []
        if kind == "csv":
            records, problems = csvio.read_csv(text)
        elif kind == "json":
            try:
                doc = json.loads(text)
            except ValueError as e:
                raise StoreError("That file isn't valid JSON.") from e
            env = doc.get("collection") if isinstance(doc, dict) and "collection" in doc else doc
            if not isinstance(env, dict) or not isinstance(env.get("entries"), list):
                raise StoreError("No collection found in that file.")
            records = [e for e in env["entries"] if isinstance(e, dict) and not e.get("deleted") and isinstance(e.get("data"), dict)]
        else:
            raise StoreError("Unsupported file type.")
        counts = self.import_records(records)
        return {**counts, "problems": problems}

    def export_csv(self, layout: str = "full") -> str:
        return csvio.build_csv(self.active_entries(), layout)

    # ── automatic backups ────────────────────────────────────────
    def backup_settings(self) -> dict:
        return {
            "dir": self.get_setting("backup_dir", str(self.default_backup_dir)),
            "keep": int(self.get_setting("backup_keep", DEFAULT_BACKUP_KEEP)),
            "auto": bool(self.get_setting("backup_auto", True)),
            "last_backup_at": self.get_setting("last_backup_at"),
            "last_backup_file": self.get_setting("last_backup_file"),
        }

    def update_backup_settings(self, body: dict) -> dict:
        if "dir" in body:
            d = Path(str(body["dir"])).expanduser()
            if not d.is_absolute():
                raise StoreError("Choose a full folder path.")
            self.set_setting("backup_dir", str(d))
        if "keep" in body:
            keep = body["keep"]
            if not isinstance(keep, int) or not 1 <= keep <= 1000:
                raise StoreError("Keep between 1 and 1000 backups.")
            self.set_setting("backup_keep", keep)
        if "auto" in body:
            self.set_setting("backup_auto", bool(body["auto"]))
        return self.backup_settings()

    def backup_now(self, force: bool = False) -> dict:
        """Write a FULL CSV backup if the collection changed since the last
        one (or force). Keeps the newest `keep` backup files."""
        cfg = self.backup_settings()
        text = self.export_csv("full")
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if not force and digest == self.get_setting("last_backup_sha256"):
            return {"written": False, "reason": "unchanged", **cfg}
        folder = Path(cfg["dir"])
        folder.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = folder / f"EntoTools-backup-{stamp}.csv"
        n = 1
        while path.exists():
            path = folder / f"EntoTools-backup-{stamp}-{n}.csv"
            n += 1
        tmp = path.with_suffix(".csv.tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
        self.set_setting("last_backup_sha256", digest)
        self.set_setting("last_backup_at", now_iso())
        self.set_setting("last_backup_file", str(path))
        backups = sorted((p for p in folder.iterdir() if BACKUP_PATTERN.fullmatch(p.name)), key=lambda p: p.name)
        for old in backups[:-cfg["keep"]]:
            try:
                old.unlink()
            except OSError as e:
                log.warning("could not remove old backup %s: %s", old.name, e)
        return {"written": True, "file": str(path), **self.backup_settings()}

    def close(self) -> None:
        with self._lock:
            self._db.close()


class BackupScheduler:
    """Runs a backup a few seconds after the last change (debounced), so a
    burst of edits produces one backup file, not dozens."""

    def __init__(self, store: Store, delay: float = 5.0):
        self.store = store
        self.delay = delay
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()

    def changed(self) -> None:
        if not self.store.backup_settings()["auto"]:
            return
        with self._lock:
            if self._timer:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, self._run)
            self._timer.daemon = True
            self._timer.start()

    def _run(self) -> None:
        try:
            self.store.backup_now()
        except Exception:  # noqa: BLE001
            log.exception("automatic backup failed")

    def flush(self) -> None:
        """On quit: write any pending backup now."""
        with self._lock:
            pending = self._timer is not None and self._timer.is_alive()
            if self._timer:
                self._timer.cancel()
                self._timer = None
        if pending:
            self._run()
