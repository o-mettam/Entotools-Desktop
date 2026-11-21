"""Phase 2 — database, import rules and automatic backups."""
from __future__ import annotations

import copy
import json
import time

import pytest

from entotools_desktop import csvio
from entotools_desktop.store import BackupScheduler, Store, StoreError
from samples import samples
from test_csvio import normalized


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "entotools.db", tmp_path / "backups")
    yield s
    s.close()


def put(store, entries, revision=1):
    return store.save_envelope({"schemaVersion": 2, "revision": revision, "entries": copy.deepcopy(entries)})


def test_empty_store_has_no_envelope(store):
    assert store.get_envelope() is None


def test_envelope_round_trip_keeps_order_and_tombstones(store):
    entries = samples()
    entries[2]["deleted"] = True
    put(store, entries, revision=7)
    env = store.get_envelope()
    assert env["revision"] == 7 and env["schemaVersion"] == 2 and env["deviceId"]
    assert env["entries"] == entries
    assert [e["id"] for e in store.active_entries()] == [e["id"] for e in entries if not e["deleted"]]


def test_entries_get_ids_and_timestamps(store):
    put(store, [{"data": {"dateStart": "2025-01-01"}}])
    e = store.get_envelope()["entries"][0]
    assert e["id"] and e["createdAt"] and e["updatedAt"] and e["deleted"] is False


def test_malformed_snapshots_are_refused(store):
    for bad in (None, [], {"entries": "x"}, {"entries": [1]}):
        with pytest.raises(StoreError):
            store.save_envelope(bad)


def test_database_survives_reopen(tmp_path):
    s = Store(tmp_path / "db.sqlite", tmp_path / "b")
    put(s, samples())
    s.close()
    s2 = Store(tmp_path / "db.sqlite", tmp_path / "b")
    assert len(s2.active_entries()) == len(samples())
    s2.close()


# ── import rules ──────────────────────────────────────────────────
def test_restoring_a_full_backup_into_an_empty_database_is_lossless(store):
    text = csvio.build_csv(samples(), "full")
    result = store.import_text("csv", text)
    assert result["added"] == len(samples()) and result["problems"] == []
    assert [normalized(e) for e in store.active_entries()] == [normalized(e) for e in samples()]


def test_reimporting_the_same_backup_changes_nothing(store):
    text = csvio.build_csv(samples(), "full")
    store.import_text("csv", text)
    rev = store.get_envelope()["revision"]
    result = store.import_text("csv", text)
    assert result["unchanged"] == len(samples()) and result["added"] == result["updated"] == 0
    assert store.get_envelope()["revision"] == rev


def test_newer_row_updates_older_row_is_ignored(store):
    put(store, samples())
    newer, older = copy.deepcopy(samples()[0]), copy.deepcopy(samples()[1])
    newer["data"]["collector"], newer["updatedAt"] = "Edited later", "2030-01-01T00:00:00.000Z"
    older["data"]["collector"], older["updatedAt"] = "Stale edit", "2001-01-01T00:00:00.000Z"
    result = store.import_text("csv", csvio.build_csv([newer, older], "full"))
    assert (result["updated"], result["kept_newer"]) == (1, 1)
    by_id = {e["id"]: e for e in store.active_entries()}
    assert by_id[newer["id"]]["data"]["collector"] == "Edited later"
    assert by_id[older["id"]]["data"]["collector"] == "A. Eargle"


def test_an_old_backup_does_not_bring_back_a_deleted_record(store):
    entries = samples()
    old_backup = csvio.build_csv(entries, "full")
    entries[0].update(deleted=True, updatedAt="2026-01-01T00:00:00.000Z")
    put(store, entries)
    result = store.import_text("csv", old_backup)
    assert result["kept_newer"] == 1
    assert entries[0]["id"] not in {e["id"] for e in store.active_entries()}


def test_website_csv_reimport_does_not_duplicate(store):
    web = csvio.build_csv(samples(), "web")
    first = store.import_text("csv", web)
    second = store.import_text("csv", web)
    assert first["added"] == len(samples())
    assert second["duplicates"] == len(samples()) and second["added"] == 0
    assert len(store.active_entries()) == len(samples())


def test_two_identical_rows_in_one_website_file_are_both_kept(store):
    one = samples()[:1]
    web = csvio.build_csv(one + copy.deepcopy(one), "web")
    assert store.import_text("csv", web)["added"] == 2


def test_website_account_json_export_imports(store):
    env = {"schemaVersion": 2, "revision": 3, "entries": samples()}
    env["entries"][1]["deleted"] = True
    doc = {"exported_at": "2026-11-01T00:00:00Z", "source": "entotools.org",
           "account": {"id": "u", "email": "a@b.co"}, "passkeys": [], "feature_flags": [], "collection": env}
    result = store.import_text("json", json.dumps(doc))
    assert result["added"] == len(samples()) - 1  # deleted entries are not imported


def test_bad_import_files(store):
    with pytest.raises(StoreError):
        store.import_text("json", "{not json")
    with pytest.raises(StoreError):
        store.import_text("json", json.dumps({"hello": 1}))
    with pytest.raises(csvio.CsvImportError):
        store.import_text("csv", "just one line")
    with pytest.raises(StoreError):
        store.import_text("xlsx", "")


# ── kv ────────────────────────────────────────────────────────────
def test_kv(store):
    store.kv_set("ento_theme", "dark")
    store.kv_set("ento_saved_searches", json.dumps([{"name": "Raleigh"}]))
    assert store.kv_all() == {"ento_theme": "dark", "ento_saved_searches": '[{"name": "Raleigh"}]'}
    store.kv_delete("ento_theme")
    assert "ento_theme" not in store.kv_all()
    for key, value in (("bad key!", "x"), ("", "x"), ("ok", 5), ("ok", "x" * 5_000_001)):
        with pytest.raises(StoreError):
            store.kv_set(key, value)


# ── backups ───────────────────────────────────────────────────────
def test_backup_writes_full_csv_and_skips_when_unchanged(store, tmp_path):
    put(store, samples())
    first = store.backup_now()
    assert first["written"] and first["file"].startswith(str(tmp_path / "backups"))
    back, _ = csvio.read_csv(open(first["file"], encoding="utf-8").read())
    assert len(back) == len(samples())
    assert store.backup_now()["written"] is False
    assert store.backup_now(force=True)["written"] is True


def test_backups_are_pruned_to_keep(store, tmp_path):
    store.update_backup_settings({"keep": 3})
    (tmp_path / "backups").mkdir()
    (tmp_path / "backups" / "my-notes.csv").write_text("not ours")  # never touched
    for i in range(6):
        put(store, samples()[: i % 5 + 1])
        store.backup_now(force=True)
    files = sorted(p.name for p in (tmp_path / "backups").iterdir())
    assert len([f for f in files if f.startswith("EntoTools-backup-")]) == 3
    assert "my-notes.csv" in files


def test_backup_settings_validation(store):
    for bad in ({"keep": 0}, {"keep": "5"}, {"dir": "relative/path"}):
        with pytest.raises(StoreError):
            store.update_backup_settings(bad)


def test_scheduler_debounces_and_flushes(store, tmp_path):
    put(store, samples())
    sched = BackupScheduler(store, delay=0.2)
    for _ in range(5):
        sched.changed()
    time.sleep(0.6)
    assert len(list((tmp_path / "backups").glob("EntoTools-backup-*.csv"))) == 1
    put(store, samples()[:2])
    sched.changed()
    sched.flush()  # quitting before the delay still writes it
    assert len(list((tmp_path / "backups").glob("EntoTools-backup-*.csv"))) == 2


def test_auto_backup_can_be_turned_off(store, tmp_path):
    store.update_backup_settings({"auto": False})
    put(store, samples())
    sched = BackupScheduler(store, delay=0.05)
    sched.changed()
    time.sleep(0.2)
    assert not (tmp_path / "backups").exists()
