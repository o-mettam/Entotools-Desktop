"""Drive real user flows inside the real app window (macOS/Windows GUI needed).

    .venv/bin/python tests/selftest/run_window_flows.py

Not part of `pytest` (it opens a window and talks to the real weather
services). Prints one line per step and exits non-zero on any failure.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

import webview

HERE = Path(__file__).resolve().parent
TMP = Path(tempfile.mkdtemp(prefix="entotools-selftest-"))
os.environ.update(ENTOTOOLS_HOME=str(TMP), ENTOTOOLS_SELFTEST="1", ENTOTOOLS_SELFTEST_SCRIPT=str(HERE / "flows.js"))

from entotools_desktop.paths import default_paths  # noqa: E402
from entotools_desktop.server import App  # noqa: E402


class FakeDialogs:
    def __init__(self):
        self.saved, self.opened = [], []

    def save_path(self, name):
        path = TMP / "saved" / name
        path.parent.mkdir(exist_ok=True)
        self.saved.append(path)
        return str(path)

    def choose_folder(self, start):
        return str(TMP / "chosen")

    def open_url(self, url):
        self.opened.append(url)

    def reveal(self, path):
        pass


dialogs = FakeDialogs()
app = App(default_paths(), dialogs=dialogs, backup_delay=0.5)
app.start()
PLAN = [("/degree-day-calculator/", 40), ("/sample-collection/", 6), ("/collection-database/", 20)]


def drive(w):
    time.sleep(1.5)
    for path, seconds in PLAN:
        w.load_url(app.origin + path)
        time.sleep(seconds)
    w.destroy()


window = webview.create_window("EntoTools flow test", app.launch_url, width=1280, height=860)
webview.start(drive, window)
log = list(app.client_log)
app.backups.flush()
backups = sorted(p.name for p in app.paths.backups.glob("EntoTools-backup-*.csv"))
app.stop()

steps = {}
for e in log:
    if e["level"] == "flow":
        d = json.loads(e["message"])
        steps[d.pop("step")] = d
problems = [e for e in log if e["level"] in ("error", "csp", "console")]

checks = [
    ("calculator search shows results + charts", steps.get("search", {}).get("resultsShown") and steps["search"]["canvases"] > 0),
    ("search results cached in the app database", steps.get("search", {}).get("resultCacheSaved")),
    ("save-search uses the in-page dialog and stores the search", steps.get("save-search", {}).get("dialogShown") and steps["save-search"]["saved"]),
    ("theme toggle stored", steps.get("theme", {}).get("toggled")),
    ("theme persists to the next page", "theme-persisted" in steps and "theme" in steps and steps["theme-persisted"]["dark"] == steps["theme"]["darkNow"]),
    ("adding a label saves to the collection table", steps.get("add-to-collection", {}).get("entries") == 1),
    ("label CSV download → Save As", any(p.name == "selftest-label.csv" and p.exists() for p in dialogs.saved)),
    ("collection table shows the saved record", steps.get("table", {}).get("rows") == 1),
    ("website CSV import (F9 negative longitude) adds the row", steps.get("import", {}).get("result", {}).get("added") == 1 and steps["import"]["rows"] == 2),
    ("collection export → Save As (full CSV)", any(p.name == "selftest-collection.csv" and p.exists() and "Record ID" in p.read_text(encoding="utf-8-sig") for p in dialogs.saved)),
    ("map opens with tiles through the app", steps.get("map", {}).get("leaflet") == "object" and steps["map"]["tilesLoaded"] > 0),
    ("automatic CSV backup written", bool(backups)),
    ("no page errors or CSP blocks", not problems and "exception" not in steps),
]
for name, ok in checks:
    print(("PASS " if ok else "FAIL ") + name)
for name, d in steps.items():
    print(f"   {name}: {json.dumps(d)[:220]}")
for e in problems:
    print(f"   ! [{e['level']}] {e['page']} {e['message'][:200]}")
sys.exit(0 if all(ok for _, ok in checks) else 1)
