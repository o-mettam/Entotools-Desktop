# EntoTools Desktop — Project Log

The single source of truth for this project. **Read it at the start of every session, and add to it at the end.** Every step taken is logged under "Session log", newest last, with what was done, why, and how it was checked.

---

## Start here (new session checklist)

```bash
cd ~/Documents/"AI Access"/EntoTools-Desktop
.venv/bin/python -m pytest -q                # should pass before you change anything
git log --oneline -5
```
- Python for development: Homebrew Python 3.13 at `/opt/homebrew/bin/python3.13`. Don't use `/usr/bin/python3`: that's Apple's Python 3.9, which is end-of-life.
- **The venv lives outside iCloud**, at `~/.venvs/entotools-desktop`; `.venv` in the repo is a symlink to it (F11). If it's missing:
  `/opt/homebrew/bin/python3.13 -m venv ~/.venvs/entotools-desktop && ln -sfn ~/.venvs/entotools-desktop .venv && .venv/bin/python -m pip install -e ".[dev]"`
- Live tests (real NOAA/Open-Meteo/Nominatim, ~1 min): `ENTOTOOLS_NETWORK_TESTS=1 .venv/bin/python -m pytest -q`
- Run the app: `.venv/bin/python -m entotools_desktop` (add `--debug` for console logs and the web inspector). Logs: `~/Library/Caches/EntoTools/entotools.log` (macOS).
- Run against throwaway data: `ENTOTOOLS_HOME=/tmp/ento-test .venv/bin/python -m entotools_desktop`
- The website's code lives in the sibling repo `../EntoTools-Production`. The front end is copied from it in Phase 3. The **source commit for the copy is `f948578`** (web v1.12.3, `main`).
- Then jump to **"Next steps"** at the bottom.

---

## Decisions

| # | Date | Decision |
|---|---|---|
| D1 | 2026-11-20 | **Architecture:** Python backend + **pywebview** native window, reusing the existing HTML/JS front end. Not a Python GUI toolkit rewrite: ~6,000 lines of UI with Chart.js charts, a Leaflet map and precise label layouts would take months to rebuild. |
| D2 | 2026-11-20 | **Website:** keep entotools.org running alongside the desktop app for now, with a plan to retire it (Phase 8). |
| D3 | 2026-11-20 | **Feature flags:** all three ship, always on: manual station choice (`station-override`), season vs. normal (`season-normals`), collection map (`collection-map`). Share links (`share-links`) don't fit a desktop app and become "Save search to file". Google Drive (`gdrive-sync`) is removed. |
| D4 | 2026-11-20 | **Code signing:** none for now (no Apple Developer Program, no Windows certificate). Users approve the app by hand on first launch; the install guide must walk them through it (Phase 6). |
| D5 | 2026-11-20 | **Feedback:** undecided. Options: pre-filled GitHub issue (needs a GitHub account) or email. Not blocking until Phase 3. |
| D6 | 2026-11-20 | **PDF labels at launch.** Exact-size PDFs generated in Python (ReportLab), replacing the browser popup and `print()`. |
| D7 | 2026-11-20 | **Offline mode:** collections, labels, the collection database, CSV import/export and PDF printing must work with no internet connection. Weather lookups need internet; previously fetched results and map tiles are served from the local cache. |
| D8 | 2026-11-20 | **In-app updates:** users can check for updates and install them from inside the app, with no reinstalling. Because the app isn't OS-signed, every update must be **signed with our own key** and verified before installing. First candidate: `tufup` (TUF-based, PyInstaller-compatible). |
| D9 | 2026-11-20 | **Storage:** SQLite in the per-user data folder is the working store. CSV is the primary *backup* format and must round-trip with no loss. |
| D10 | 2026-11-20 | **Separate repo** (`EntoTools-Desktop`), so the live website is never affected by desktop work. GitHub: **https://github.com/o-mettam/Entotools-Desktop** (public), so in-app updates can download from its Releases. |
| D11 | 2026-11-21 | **Label PDFs use US Letter (8.5 × 11 in)** for now. A4 can be added later as a setting. |
| D12 | 2026-11-21 | **Saved searches and page preferences live in the `kv` table**, under the same keys the pages used in `localStorage`. This replaces the separate `saved_searches` table first planned, so Phase 3 is a drop-in swap. |
| D13 | 2026-11-21 | **Full-backup CSV = the website's 33 columns + 17 machine columns** (`csvio.py`). It stays readable in Excel and still imports into the website. Machine columns win over display columns on import. Unknown fields ride in "Extra Fields (JSON)". |
| D14 | 2026-11-21 | **Desktop accepts only real calendar dates.** `2025-02-30` is rejected; the website silently rolls it to March 2 (F10). |
| D15 | 2026-11-21 | **Server stack: Python standard library** (`ThreadingHTTPServer`), not Bottle or Flask. It's one less dependency to package, and the API is small. |

---

## Architecture (target)

```
┌──────────────── EntoTools.app / EntoTools.exe (PyInstaller) ────────────────┐
│  pywebview window (WKWebView on macOS, WebView2 on Windows)                  │
│     └─ loads http://127.0.0.1:<random port>/ … existing pages from web/      │
│        every API call carries a per-launch secret token                      │
│                                                                              │
│  Python backend (local HTTP server, 127.0.0.1 only)  — src/entotools_desktop/ │
│     server.py   access control + routing        weather.py  search, normals  │
│     services.py status, proxies, tiles          store.py    SQLite, import,  │
│     csvio.py    CSV formats                                  backups         │
│     /api/search, /api/normals, /api/status/{ping,check}, /api/connectivity    │
│     /api/proxy/{nominatim-reverse,om-elevation,om-archive,sunrise-sunset}     │
│     /tiles/{z}/{x}/{y}.png                      (proxied + disk cache)        │
│     /api/collection (GET/PUT), /api/collection/import, /export.csv            │
│     /api/kv[/key], /api/backup, /api/backup/now, /api/flags, /api/version     │
│     (Phase 3) native Save dialog   (Phase 4) /api/labels.pdf                  │
│     (Phase 5) /api/update/*                                                   │
│                                                                              │
│  Data: <user data dir>/entotools.db  (platformdirs)                          │
│  Backups: ~/Documents/EntoTools Backups/*.csv (auto, rotated)                │
│  Cache:  <user cache dir>/  (HTTP responses, map tiles)                      │
└──────────────────────────────────────────────────────────────────────────────┘
Outbound (internet): NOAA NCEI · Open-Meteo · Nominatim · Sunrise-Sunset · OSM tiles · GitHub Releases (updates)
```

---

## Plan and status

Legend: `[x]` done · `[~]` in progress · `[ ]` not started

### Phase 0 — Decisions and setup
- [x] 0.1 Record decisions (above)
- [x] 0.2 Create the repo, the Python 3.13 venv and the package skeleton
- [x] 0.3 Capture reference outputs from the web Worker (`tests/reference/`)
- [x] 0.4 Prove the reference outputs equal production
- [x] 0.5 Smoke-test a pywebview window on macOS
- [ ] 0.6 Smoke-test a pywebview window on **Windows** (needs a Windows machine or VM; can be done via GitHub Actions in Phase 6)
- [x] 0.7 GitHub repo connected and pushed (https://github.com/o-mettam/Entotools-Desktop, public)

### Phase 1 — Python backend (port of the Worker)
- [x] 1.1 Local HTTP server on 127.0.0.1, random port, per-launch token, Host-header check
- [x] 1.2 Port `/api/search` (geocode, station lookup from `stations.json`, NCEI with retries, Open-Meteo fallback, forecast merge, input limits). **Use the computer's local date for "today"** (see finding F1).
- [x] 1.3 Port `/api/normals` and `/api/status/*`
- [x] 1.4 Proxy the outside calls Label Data makes today (Nominatim reverse, elevation, sunrise/sunset, humidity), with an identifying User-Agent and Nominatim limited to 1 request/second. *(Backend done; pages switch over in 3.1.)*
- [x] 1.5 Map-tile proxy with a disk cache (also serves tiles offline)
- [x] 1.6 SQLite HTTP cache (replaces Cloudflare KV): 24 h geocode, 90 days grid normals, no expiry for station normals, 30 days previous year
- [x] 1.7 Parity tests against `tests/reference/` (rules in "Reference data" below)
- [x] 1.8 Offline detection: clear "you're offline" responses instead of long timeouts

### Phase 2 — Storage, CSV and offline data
- [x] 2.1 SQLite schema: `collection_entries`, `collection_meta`, `kv`, `settings` (version in `PRAGMA user_version`). The HTTP cache is a separate file. Saved searches live in `kv` (D12).
- [x] 2.2 `/api/collection` (same envelope shape as the web's account sync) and `/api/kv`
- [x] 2.3 Lossless **full-backup CSV** format (adds Record ID, Created, Updated, Time Start, Time End, Input Mode, Is Range, mGDD Start/End, humidity values). Import updates records with a matching Record ID and adds the rest. Old-format CSVs still import as new records.
- [x] 2.4 Automatic CSV backup after changes, to a user-chosen folder, keeping the last N copies. *(Backend done: 5-second debounce, skipped when unchanged, flushed on quit, default keeps 30. The folder picker UI comes in Phase 3.)*
- [x] 2.5 Round-trip test: export → import into an empty database → every field identical
- [x] 2.6 Import from the website: accept the web CSV export and the account JSON export (for users moving over)

### Phase 3 — Front end
- [ ] 3.1 Copy pages from web commit `f948578`. Remove accounts, passkeys, feedback widget, Drive sync, flags, CSP and admin. Flagged features always on.
- [ ] 3.2 Replace every `localStorage` use (~20) with an `EntoKV` module backed by `/api/kv`
- [ ] 3.3 Bundle Chart.js (+ annotation, datalabels), Leaflet and the Inter font locally (no CDN), so the UI works offline
- [ ] 3.4 Downloads (CSV, PNG, JSON) → backend + native Save dialog
- [ ] 3.5 Replace `prompt()` with an in-page dialog. Share links → "Save search to file" / "Open search file"
- [ ] 3.6 Offline mode in the UI: banner when offline; weather actions disabled with an explanation; collection, labels, CSV and PDF unaffected
- [ ] 3.7 Feedback, per D5
- [ ] 3.8 Rewrite the Privacy and Terms pages for a desktop app

### Phase 4 — PDF labels (required at launch)
- [ ] 4.1 Measure the current label layout (web labels use a 2.5 in max width, 9 px type) and choose a page layout on **US Letter** (D11): label size, margins, labels per sheet
- [ ] 4.2 ReportLab generator for Label 1 (locality/date/GDD/collector) and Label 2 (ID/determination), single label and full sheet
- [ ] 4.3 "Print labels" → PDF → open in the system viewer, plus "Save PDF"
- [ ] 4.4 Visual check against the web's print output; test with long names and special characters (é, ü, ×, °)

### Phase 5 — In-app updates
- [ ] 5.1 Evaluate `tufup` (check maintenance status, macOS `.app` and Windows support). Fallback: a small custom updater with an Ed25519-signed manifest.
- [ ] 5.2 Generate the update-signing key pair. **Private key kept only in a GitHub Actions secret and an offline backup — never in the repo.**
- [ ] 5.3 Settings → "Check for updates" (also an optional check on launch). Shows the version, release notes and size.
- [ ] 5.4 Download → verify signature and hash → install → restart. Back up the database before installing; keep the previous version so it can be rolled back.
- [ ] 5.5 Windows: install per-user under `%LOCALAPPDATA%\Programs\EntoTools`, so updates never need admin rights
- [ ] 5.6 macOS: replace the `.app` in place. Test that files our updater downloads don't get the quarantine flag (`xattr -l`), so the user doesn't have to approve the app again after each update.
- [ ] 5.7 End-to-end test: install v0.1.0, publish v0.1.1, update from inside the app, data intact

### Phase 6 — Packaging and release
- [ ] 6.1 `tools/build_stations.py`: regenerate `stations.json` from NOAA's station list (the generator isn't in the web repo; see F4)
- [ ] 6.2 PyInstaller builds: macOS (Apple Silicon + Intel, or universal2) and Windows x64
- [ ] 6.3 GitHub Actions: build on `macos-latest` and `windows-latest` and attach to a GitHub Release with the signed update metadata
- [ ] 6.4 Windows: check for the WebView2 runtime on first launch and link to Microsoft's installer if missing
- [ ] 6.5 Install guide with screenshots for approving an unsigned app: macOS (Privacy & Security → "Open Anyway") and Windows (SmartScreen → "More info" → "Run anyway"). Also cover Windows **Smart App Control**, which can block unsigned apps outright; test this.
- [ ] 6.6 Third-party notices: Chart.js (MIT), Leaflet (BSD-2), OSM data (ODbL attribution), Open-Meteo (CC BY 4.0; free API is for non-commercial use), NOAA (public domain)

### Phase 7 — Testing and first release
- [ ] 7.1 Clean-machine tests on Windows 11 and macOS: every tool, offline mode, PDF, CSV round-trip, update
- [ ] 7.2 Release v0.1.0 (beta) to a few users

### Phase 8 — Website retirement (later; D2)
- [ ] 8.1 Banner on entotools.org: "EntoTools is now a desktop app — download, and export your collection as CSV"
- [ ] 8.2 Run both for an agreed overlap period; announce a shutdown date
- [ ] 8.3 Final reminder to export; then retire Cloudflare: Pages, D1, KV, Access, DNS

---

## Reference data (Phase 0.3)

`tests/reference/{search,normals}/*.json`: 26 search and 5 normals cases, captured with `tools/capture_reference.py`.

- **Source:** the web Worker at commit `f948578` (v1.12.3), run locally with `wrangler pages dev` and **every feature flag on** (normals are hidden from anonymous visitors on the live site).
- **Equivalence with production:** all 23 deterministic search cases were re-run against https://entotools.org and were **identical byte for byte** (2026-11-21 02:20 UTC).
- **`compare: exact`:** historical dates and validation errors. **`compare: shape`:** ranges reaching today or the future (forecasts change daily).
- **Rules for the Phase 1 parity tests:**
  1. Validation errors: status and message must match exactly.
  2. Weather values for a given station and date: exact match.
  3. **Automatic station choice can drift over time** even for old dates: it picks the nearest station that reported temperatures *in the last 30 days*, so a station going offline changes the pick. When the station differs, test the data using the reference's station (manual override) instead of failing.
  4. Geocoding: lat/lon within 0.001°; `location` text may differ (OSM edits).
  5. Normals: years used must match; values within 0.1 °F (NCEI can revise recent data).
- Re-capture: run the Worker locally (see session 1, step 6), then `.venv/bin/python tools/capture_reference.py --base http://localhost:8788`

---

## Findings and known issues

| # | Found | Issue | Action |
|---|---|---|---|
| F1 | 2026-11-20 | **Web bug:** the Worker decides "today" in **UTC**. In US evenings (after ~7–8 pm Eastern), a range ending on the user's local today is treated as historical, so the 16-day forecast is left off and the latest days can show gaps. Seen in `to_today_raleigh` (captured 9:18 pm EST, already Nov 21 in UTC: no forecast past Nov 20, Nov 15 null). | Desktop: use the local date (1.2). Web: send the client's local date with the search (fix in the web repo). |
| F2 | 2026-11-20 | **CSV export loses data**: no record IDs or created/updated dates; times flattened to 12-hour text; humidity, range flag, mGDD start/end and input mode merged or dropped. Import always appends, so re-importing a backup duplicates every record. | Full-backup CSV format (2.3) and round-trip test (2.5). |
| F3 | 2026-11-20 | Front end stores everything in `localStorage` (~20 places). In a web view served from `127.0.0.1:<random port>`, a different port is a different origin, so the data would seem to vanish between launches. | All storage moves to the backend (2.2, 3.2). |
| F4 | 2026-11-20 | `stations.json` (6.6 MB) is generated from `ghcnd-stations.txt` (11 MB), but the generator script isn't in the web repo. | Write `tools/build_stations.py` (6.1). |
| F5 | 2026-11-20 | Label printing uses `window.open` + `document.write` + `print()`. Popups and `print()` are unreliable in pywebview, especially on macOS. | PDF labels (Phase 4). |
| F6 | 2026-11-20 | Downloads use `<a download>` (5 places), which doesn't save files in a web view. | Native Save dialog (3.4). |
| F7 | 2026-11-20 | Smoke test: the JS → Python bridge call (`window.pywebview.api.ping`) came back empty, because the test called it before the bridge was ready. The design uses HTTP for the API, so nothing depends on it. | Re-check in 1.1 if the bridge is used for native dialogs. |
| F8 | 2026-11-20 | The feedback widget creates GitHub issues using a server-side token. A desktop app can't safely carry a token. | Per D5 (3.7). |
| F9 | 2026-11-21 | **Web bug (data loss): the website's CSV export can't be re-imported.** Its spreadsheet-formula guard puts an apostrophe before *every* cell starting with `-`, numbers included, so longitude `-77.0369` is written as `'-77.0369`. Its importer reads that as blank and skips the row for "missing coordinates". **Every record with a western longitude or southern latitude (all of the Americas) is silently dropped on re-import**, and negative temperatures become blank. The importer also never removes the apostrophe from text, so `=SUM…` comes back as `'=SUM…`. Reproduced in Node and in `test_csvio.py`. | Desktop: numbers are never guarded, and the reader removes the apostrophe, so **web CSV backups restore correctly in the desktop app**. Web: fix `csvSafe()` to skip plain numbers, and strip the guard in `importCSV` (web repo). |
| F10 | 2026-11-21 | Web: impossible dates (`2025-02-30`) pass validation, because JS rolls them over to March 2. The original string is then sent to NOAA. | Desktop rejects them (D14). Web: optional fix. |
| F11 | 2026-11-21 | **`~/Documents` is synced by iCloud**, which re-applies the macOS `hidden` flag to dot-folders. Python 3.13 deliberately ignores hidden `.pth` files, so the editable install "disappeared" (`No module named entotools_desktop`). | Venv moved to `~/.venvs/entotools-desktop`, linked as `.venv`. pytest also sets `pythonpath = ["src"]`. See open question 4 about the repo itself. |
| F12 | 2026-11-21 | During the Phase 0 capture, Open-Meteo rate-limited the Worker (HTTP 429), so one reference normals case is missing its previous year. | Fixture annotated (`upstream_failure_at_capture`); the test skips only that comparison. Packing many normals requests into seconds can hit Open-Meteo's free-tier limits; one person using the app won't. |

---

## Open questions

1. **Feedback route** (D5): GitHub issue or email?
2. **Label size** (4.1): paper is US Letter (D11); the size of each label and labels per sheet are still to be settled. The default is to match the web's on-screen labels.
3. **Website overlap** (8.2): how long should both run?
4. **Move the repo out of iCloud?** The repo is in `~/Documents`, which iCloud syncs (F11). iCloud and git don't mix well: conflicted copies like `index 2`, and evicted files with "Optimize Mac Storage". Suggest moving it to e.g. `~/Developer/EntoTools-Desktop`. Your call; nothing depends on the current path except these notes.
5. **Scrub the `.venv` symlink from git history?** It only reveals the macOS username in a local path (session 3, step 22). Removing it means rewriting history and force-pushing `main`, which is fine now while you're the only one working on the repo. Say the word, or leave it.

---

## Session log

### Session 1 — 2026-11-20 (Phase 0)

1. **Evaluated the web codebase** (repo `EntoTools-Production`, commit `f948578`). Sizes: calculator 2,984 lines, label data 1,162, collection DB 1,013, GDD lookup 670; Worker `src/index.js` 1,542, of which ~1,000 lines of weather logic are worth porting. Inventory of keep / port / remove and findings F1–F8 above.
2. **Recorded decisions** D1–D10.
3. **Installed Python 3.13** with Homebrew (`brew install python@3.13` → 3.13.18). The machine only had Apple's Python 3.9.6.
4. **Created this repo** at `../EntoTools-Desktop` (`git init -b main`) with the layout `src/entotools_desktop/`, `tests/reference/`, `tools/`, `web/` (empty until Phase 3), `docs/`.
5. **Created `.venv`** and installed pinned packages: pywebview 6.2.1 (pulls in pyobjc 13.0 and bottle 0.13.4 on macOS), httpx 0.28.1, platformdirs 4.14.8, reportlab 5.1.0, pytest 9.2.0. Recorded in `pyproject.toml`; `pip install -e ".[dev]"`.
6. **Ran the web Worker locally** to capture normals, which the live site hides from anonymous visitors:
   - In the web repo, applied `migrations/0001–0011` to a **throwaway local D1** stored in the session scratchpad, so nothing was written to the web repo or to production (`wrangler d1 execute entotools-accounts --local --persist-to <tmp> --file=…`).
   - Set every flag to `ga` in that local database only.
   - `wrangler pages dev public/ --port 8788 --persist-to <tmp>`; stopped afterwards.
7. **Wrote `tools/capture_reference.py`** and captured 31 cases:
   - 11 historical lookups: US city and lat/lon (NCEI), non-US (Open-Meteo), multiple ranges, manual station including the `ghcnd:` lowercase form, the legacy single-range fields.
   - 3 to-today / future cases.
   - 12 validation errors.
   - 5 normals.

   Checked each one: US cases used NCEI with no fallback; non-US used Open-Meteo; normals had 30 years for NCEI and both grids.
8. **Verified against production:** `--base https://entotools.org --verify` → all 23 deterministic cases identical.
9. **Found the UTC "today" bug** (F1) while checking the to-today case.
10. **Smoke-tested pywebview:** a native window opened on macOS 27.2.1 using WKWebView and JS ran. Bridge result inconclusive (F7).
11. **Added the skeleton:** `pyproject.toml`, `.gitignore` (excludes signing keys), a placeholder `__main__.py` window, and `tests/test_reference_fixtures.py`. **`pytest`: 32 passed.**
12. **Researched the updater:** `tufup` is the first candidate (TUF-signed metadata, works with PyInstaller). For macOS, files downloaded by an app's own network code normally don't get the quarantine flag; this must be tested (5.6) before relying on it.
13. **Committed** Phase 0 locally (`62b2bf2`).

### Session 2 — 2026-11-21 (Phase 0 wrap-up)

1. **Repo provided:** https://github.com/o-mettam/Entotools-Desktop. Checked it before pushing: it is public (GitHub API 200) and held one commit, "Initial commit" (`be9a0aa`), containing only a README with the tagline *"Entotools.org, but downloadable to your desktop."*
2. **Combined histories instead of overwriting:** added it as `origin` and merged `origin/main` with `--allow-unrelated-histories`. The README conflict was resolved by keeping the GitHub tagline as the README's opening line, followed by the development notes.
3. **Recorded D11:** label PDFs use US Letter. Updated D10 with the repo URL; marked 0.7 done.
4. **Pushed `main`** to GitHub.


### Session 3 — 2026-11-21 (Phase 1 and Phase 2)

**Phase 1 — backend port**
1. **Re-read the web sources** that Phases 1–2 must reproduce: `src/index.js` (search, normals, retries, forecast merge), `stations.json` (75,846 stations: `id, lat, lon, state, name`), the four direct calls in `label_data.html`, `collectionData`'s fields, and `csvRowToData` / `parseCSV` / `EntoCsv`.
2. **Checked JS date behaviour in Node:** `new Date("2025-02-30T00:00:00Z")` → March 2 (F10). Decided to reject such dates (D14).
3. **`jscompat.py`:** `Math.round` (ties toward +∞), `String(number)`, `parseFloat`, JS truthiness, UTF-16 lengths. **Fuzz-tested against Node: 0 mismatches** in 1,519 values for `String()`, 14,000 for `Math.round`, and 14 edge strings for `parseFloat`.
4. **Hit F11** (iCloud hides `.venv`, so Python skips the `.pth`). Recreated the venv at `~/.venvs/entotools-desktop`, symlinked as `.venv`, and added `pythonpath = ["src"]` to pytest.
5. **`paths.py`** (platformdirs folders; `ENTOTOOLS_HOME` override for tests) and **`cache.py`** (SQLite cache with expiry; expired entries kept a year so they can be served offline).
6. **`net.py`:** a shared httpx client with User-Agent `EntoTools-Desktop/<version> (+repo URL)` and Nominatim throttled to 1 request/s. On a connection failure it probes 1.1.1.1, 8.8.8.8 and api.open-meteo.com; if none answer it raises `OfflineError` immediately, with no retries.
7. **Copied `stations.json`** into the package (SHA-256 matches the web copy).
8. **`weather.py`:** line-by-line port of `handleSearch` and `handleNormals` (geocoding, nearest-station search, NCEI and Open-Meteo with the same retry rules, forecast merge, precipitation totals, every validation message), with a thread pool for parallel ranges and decades. Desktop differences are marked `DESKTOP:` in the code (local date, F1; impossible dates; offline). Added a lock around the shared range counters.
9. **`tests/test_parity.py`:**
   - 13 validation-error cases are **identical, with the network disabled**.
   - Live: **all 11 historical searches identical to the website, every daily value**; 3 forecast cases have the right shape and **confirm the F1 fix**; normals match on 4 of 4 after annotating F12.
10. **`services.py`:** status checks (port of `status.js`, plus "Offline"); allow-listed proxies (`nominatim-reverse`, `om-elevation`, `om-archive`, `sunrise-sunset`) with caching; map-tile proxy (zoom 0–19, range-checked x/y, PNG check, 7-day freshness, stale copy served offline).

**Phase 2 — storage, CSV, backups**

11. **Confirmed F9 in Node:** the website's export → import drops every western-hemisphere record.
12. **Snapshotted the website's CSV code** (from commit `f948578`) into `tests/reference/web_js/`: `sync-core.js` verbatim, and `collection_import.js` with `parseCSV`, `csvRowToData` and the time parsers extracted verbatim. The tests run them in Node.
13. **`csvio.py`:** website layout (exact port), full-backup layout (D13), the website's parser port, and the reader for both, which undoes the apostrophe (F9).
14. **`store.py`:**
    - SQLite `entotools.db` with `collection_entries`, `collection_meta`, `kv` and `settings`.
    - The envelope API matches the website's account sync.
    - Imports merge: newer Updated At wins, a deleted record is never revived, and re-importing a website CSV doesn't duplicate (two identical rows in one file are both kept).
    - Also imports the website's account JSON export.
    - Backups: written only when the data changed, the newest N kept, other files in the folder never touched. The `BackupScheduler` debounces changes and flushes on quit.
15. **Bug found and fixed by the tests:** CSV turns `88.0` into `88`, so unchanged records looked "edited". The record fingerprint now compares values, not number formatting.
16. **`server.py`:**
    - `ThreadingHTTPServer` on 127.0.0.1 with a random port (D15).
    - A per-launch token handed over by `/__launch` as an HttpOnly, SameSite=Strict cookie; Host-header check; cross-origin writes refused.
    - Body size limits (64 KB / 60 MB), `nosniff`, `no-referrer`, `X-Frame-Options: DENY` on pages, and protection against `../` paths.
    - All the API routes in the architecture diagram.
    - Placeholder page in `src/entotools_desktop/web/` until Phase 3.
17. **`__main__.py`:** starts the server, opens the window on the launch URL, logs to a rotating file, flushes the pending backup on close. `--debug` turns on the web inspector.
18. **Tests added:**
    - `test_csvio.py` (9): the website layout is **byte-identical** to `EntoCsv.buildCsv`, our parser equals `parseCSV`, the full layout round-trips every field, F9 is reproduced, plus formula-guard checks.
    - `test_store.py` (19).
    - `test_server.py` (17): access control, every route, tile and proxy caching, and offline behaviour. Offline search answers in under 5 s with `offline: true`; cached proxy answers and tiles are served after expiry; the collection, backups and export work with no network.
19. **Real window check (macOS):**
    - WKWebView accepted the launch cookie and the page reached the backend (`status: ok`).
    - A search run from *inside the window* returned NCEI data for DC, June 1–3 2025: TMAX 70/75/81. Identical to the reference.
20. **Full suite: 108 passed** (with `ENTOTOOLS_NETWORK_TESTS=1`).
21. Committed and pushed `67d8a7c`.
22. **Mistake caught after pushing:** `.gitignore` said `.venv/`, which matches only folders, so the `.venv` *symlink* was committed. Its target, `/Users/<you>/.venvs/entotools-desktop`, exposes the local macOS username in the public repo. Fixed in `bef368c`: untracked, and the rule is now `.venv`. **It is still in the history of `67d8a7c`.** Removing it from history needs a force-push, which is the owner's call (open question 5).


---

## Next steps

1. **Phase 3.1** — copy the pages from web commit `f948578` into `src/entotools_desktop/web/`. Remove accounts, feedback, Drive and the admin page. Point Label Data's four outside calls at `/api/proxy/*` and the map at `/tiles/…`.
2. **Phase 3.2** — the `EntoKV` swap (saved searches and preferences → `/api/kv`, D12), and `EntoStore` → `/api/collection`.
3. **Phase 4** can start alongside: the PDF label layout on US Letter. Settle open question 2 (label size) first, or default to the website's on-screen labels.
4. Web repo follow-ups to raise with the user: **F9 (data loss on CSV re-import)**, F1 (UTC today), F10.
