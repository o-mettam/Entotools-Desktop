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
- **Real-window flow test** (opens a window, uses live services, ~1.5 min): `.venv/bin/python tests/selftest/run_window_flows.py`
- **Pages come from the website via `tools/import_web.py`. Never hand-edit files listed in `src/entotools_desktop/web/IMPORTED.txt`**; add an `Edit` to the script and re-run it (`--check` verifies). Desktop-owned: `desktop.js`, `desktop.css`, `vendor/`.
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
| D16 | 2026-11-21 | **Pages keep the website's code; `desktop.js` fills the gaps.** `localStorage` → `EntoKV` (text substitution at import; writes are synchronous so nothing is lost when a page navigates away). The collection key goes to the collection table, so `sync-core.js` is unchanged in logic. |
| D17 | 2026-11-21 | **Strict per-page Content-Security-Policy**: the page's own inline scripts by hash, everything else same-origin, `connect-src 'self'` (all internet access goes through Python). No `'unsafe-eval'`, even though that blocks pywebview's `evaluate_js` in tests (F15). |
| D18 | 2026-11-21 | **Page errors are logged locally**: `desktop.js` sends uncaught errors, `console.error` and CSP blocks to `/api/client-log`, which writes them to the app's log. A self-test switch (`ENTOTOOLS_SELFTEST=1`) lets the test harness read them. |
| D19 | 2026-11-21 | **Share links are not shipped** (the flag is off on desktop, D3). Saved searches cover reopening a search. "Save search to file" remains an optional extra (3.5b). |
| D20 | 2026-11-21 | **Printing opens a PDF in the system's PDF viewer** (Preview on macOS, the default viewer on Windows). People print or save from there. Files go to `<cache>/printouts/` and are removed after 7 days. `EntoDesktop.saveLabelsPdf` (Save As) exists for a future button. |
| D21 | 2026-11-21 | **Label layout = the website's print layout** (open question 2 resolved by default): 9 px Inter (6.75 pt), line-height 1.3, 1.5 px border, 0.3/0.4 rem padding, shrink-to-fit up to 2.5 in, 4 px gaps, flowing across US Letter with 0.5 in margins. **Field notes get their own readable sheet layout** instead of the website's notes table squeezed into a 2.5 in box. |

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
- [x] 3.1 Copy pages from web commit `f948578`. Remove accounts, passkeys, feedback widget, Drive sync, flags, CSP and admin. Flagged features always on.
- [x] 3.2 Replace every `localStorage` use (~20) with an `EntoKV` module backed by `/api/kv`
- [x] 3.3 Bundle Chart.js (+ annotation, datalabels), Leaflet and the Inter font locally (no CDN), so the UI works offline
- [x] 3.4 Downloads (CSV, PNG, JSON) → backend + native Save dialog
- [x] 3.5 Replace `prompt()` with an in-page dialog (done). Share links: not shipped (D19).
- [ ] 3.5b (optional) "Save search to file" / "Open search file"
- [x] 3.6 Offline mode in the UI: banner when offline; weather actions disabled with an explanation; collection, labels, CSV and PDF unaffected *(Banner via `/api/connectivity`; the server answers weather requests with a clear offline message rather than disabling buttons.)*
- [ ] 3.7 Feedback, per D5
- [x] 3.8 Rewrite the Privacy and Terms pages for a desktop app *(Also the Documentation page's storage wording and the Status page's service descriptions.)*

### Phase 4 — PDF labels (required at launch)
- [x] 4.1 Measure the current label layout (web labels use a 2.5 in max width, 9 px type) and choose a page layout on **US Letter** (D11): label size, margins, labels per sheet
- [x] 4.2 ReportLab generator for Label 1 (locality/date/GDD/collector) and Label 2 (ID/determination), single label and full sheet
- [x] 4.3 "Print labels" → PDF → open in the system viewer (D20); Save from the viewer. *(A separate "Save PDF" button is optional; the backend supports it.)*
- [x] 4.4 Visual check against the web's print output; test with long names and special characters (é, ü, ×, °)

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
| F13 | 2026-11-21 | After the history rewrite, GitHub still serves the orphaned commit `67d8a7c` to anyone who has its exact ID (normal GitHub behaviour). It's not in any branch and isn't reachable by browsing. | Left as is: it only revealed a macOS username. GitHub Support can purge cached views on request. |
| F14 | 2026-11-21 | Collection Database revealed the **map** only inside the account script's `entoaccount:ready` listener. Removing account code would have silently hidden the map. Caught because the import's first attempt also swallowed the map code and the checks stopped it. | The import replaces that listener with one on `entoflags:updated` (fired by `desktop.js`), and regex removals now have a `max_lines` guard. The flow test confirms the map opens. |
| F15 | 2026-11-21 | pywebview's `evaluate_js` runs code through `eval()`, which the strict CSP (D17) blocks, by design. | Tests read page state through `/api/client-log` and the self-test script instead (D18). Production never uses `evaluate_js`. |
| F16 | 2026-11-21 | Label printing used `window.open` + `print()` (F5), which pywebview doesn't support reliably. | **Fixed in Phase 4:** `printLabel` / `printSheet` now produce PDFs (import edits). The import refuses any `window.open(` or `win.print()` left in a page. |
| F17 | 2026-11-21 | **Inter has no ♀ / ♂** (common on insect labels). ReportLab doesn't substitute fonts automatically. | Character-level fallback to DejaVu Sans (and Oblique for italics), bundled. Tested: the PDF uses `DejaVuSans-Oblique` for "Photinus pyralis ♂". |
| F18 | 2026-11-21 | **iCloud duplicates in the website repo:** `migrations/0011_single_use_tokens 2.sql` (untracked, byte-identical to the real migration) and `.git/index 2` (inside git's own folder). These are the iCloud-vs-git conflicts warned about in open question 4. | Not deleted (the user's call). Both are safe to delete. Moving both repos out of iCloud-synced `~/Documents` prevents more. |

---

## Open questions

1. **Feedback route** (D5): GitHub issue or email?
2. **Label size** (4.1): paper is US Letter (D11); the size of each label and labels per sheet are still to be settled. The default is to match the web's on-screen labels.
3. **Website overlap** (8.2): how long should both run?
4. **Move the repo out of iCloud?** The repo is in `~/Documents`, which iCloud syncs (F11). iCloud and git don't mix well: conflicted copies like `index 2`, and evicted files with "Optimize Mac Storage". Suggest moving it to e.g. `~/Developer/EntoTools-Desktop`. Your call; nothing depends on the current path except these notes.

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
21. Committed and pushed (now `e497b67` after the history rewrite in session 4).
22. **Mistake caught after pushing:** `.gitignore` said `.venv/`, which matches only folders, so the `.venv` *symlink* was committed. Its target exposed the local macOS username in the public repo. Untracked, and the rule is now `.venv`. The history was scrubbed in session 4.



### Session 4 — 2026-11-21 (history scrub, Phase 3)

**History scrub (open question 5 → done)**
1. Confirmed that only `67d8a7c` contained `.venv`. Kept a safety branch, ran `git filter-branch --index-filter 'git rm --cached --ignore-unmatch .venv' -- 22d819b..main`, and checked that no commit contains `.venv` and every other file is byte-identical.
2. Updated the log's commit references, then `git push --force-with-lease=main:f1a0f72` (it refuses to overwrite anything unexpected). Verified on GitHub: no commit on `main` contains `.venv`. GitHub still serves the orphan by exact ID (F13).
3. Deleted the safety branch and `refs/original`, expired the reflog and ran `gc --prune=now`; the old commit is gone locally.

**Phase 3 — the real pages**

4. **Vendored the CDN files** into `web/vendor/`: Chart.js 4.5.1 with the datalabels 2.2.0 and annotation 3.1.0 plugins, and Leaflet 1.9.4 (+ images). **All five SRI hashes match the ones the website pins.** Also Inter via `@fontsource-variable/inter@5.3.0` (all subsets, 224 KB, family renamed to `Inter`). Licenses and provenance are in `web/vendor/README.md`.
5. **Server additions** (`server.py`):
   - `/api/boot`: flags, kv, collection, backup settings and version in one request.
   - `/api/save`: native Save As; only csv/png/json/pdf/txt; suggested names are stripped of path parts; written via a `.part` temp file.
   - `/api/open-url`: http(s) only.
   - `/api/backup/choose-folder` and `/api/backup/open-folder`.
   - `/api/client-log` (D18).
   - A per-page CSP computed from each page's inline scripts and cached by mtime (D17).
   - Native UI sits behind a `Dialogs` interface: `desktop_ui.WebviewDialogs` in the app, fakes in tests.
6. **`web/desktop.js` + `desktop.css`**: `EntoKV`, flags plus the `entoflags:updated` event, toasts, in-page prompt, Save As helpers, import helper, outside links → default browser, offline banner, the Settings → "Data & backups" section (last backup, Back up now, Change folder…, Open folder, auto on/off, version), and error reporting.
7. **Desktop Privacy and Terms text** (`tools/web_overrides/`) written to match the app's actual behaviour: data stays local, which services see which data, no tracking, the one in-window cookie.
8. **`tools/import_web.py`**: copies 12 pages + 6 assets from website commit `f948578` using `git show` (the website's working tree is never touched) and applies about 45 checked edits. Each edit names its reason and its exact expected match count. Afterwards it refuses any leftover CDN, Google Fonts, account, Drive or direct outside-API reference, and writes `web/IMPORTED.txt` (sha256 manifest). `--check` compares the disk with a fresh import.
9. **Import problems caught by its own checks** before anything was written:
   - leftover Google sign-in loader;
   - the Drive-removal regex swallowing the map code (F14);
   - documentation text that only mentions API addresses (allow-listed for that page);
   - a `defer` attribute on the Status page's feedback script;
   - a backslash in the Windows path breaking regex replacement (replacements are now literal).
10. **Real-window page sweep** (all 10 pages, plus a missing page for the 404): **zero JS errors and zero CSP blocks**. On every page `EntoKV` is active, the backups section appears in Settings, Inter is loaded from the bundle, and all three flags are on. Chart.js loads with SRI against the bundled copy, and the map entry point is visible.
11. **Real-window flow test** (`tests/selftest/run_window_flows.py` + `flows.js`) — **13/13 PASS**:
    - live calculator search (DC, Mar–Jun 2025) shows results and 4 charts, and the result cache is saved;
    - Save Search uses the in-page dialog and stores the search;
    - dark mode is stored and persists to the next page;
    - adding a label writes to the collection table;
    - the label CSV and the full collection export go through Save As;
    - a website CSV with `'-77.03` (F9) imports correctly;
    - the map opens and loads 14 tiles through `/tiles`;
    - an automatic backup is written;
    - no page errors.

    A check I first wrote for theme persistence couldn't fail; it was fixed before being relied on.
12. **Tests**: +7 server tests (boot, Save As with cancel and path stripping, open-url allow-list, folder choose/open, 501 without a window, client-log cap, **every page's CSP equals its inline-script hashes**) and `test_web_import.py` (fresh-import check, manifest hashes, no page loads anything from the internet). **118 passed** (with `ENTOTOOLS_NETWORK_TESTS=1`).
13. Documentation page: replaced 5 passages about browser storage and Cloudflare with desktop wording (as import edits).
14. **Second username exposure found before committing:** the start-here `cd` line in this log contained the full `/Users/<name>/…` path, in every commit since Phase 0. The line now uses `~`. All earlier commits were rewritten to replace that one line (`git filter-branch --tree-filter`, then verified that no commit in the history contains the username) and force-pushed with `--force-with-lease`. Commit IDs from before session 4 in this log refer to the pre-rewrite history.



### Session 5 — 2026-11-21 (history push, Phase 4)

1. **Force-pushed the cleaned history** (user chose option 1): `git push --force-with-lease=main:6e28e94`. Verified GitHub's `main` matches local, with 0 occurrences of the username in any commit. Removed the local safety branch, `refs/original` and old objects.
2. **Found iCloud duplicates** in the website repo while the user had one open (F18). Not deleted.
3. **Fonts for PDFs** (`src/entotools_desktop/data/fonts/`, provenance in its README):
   - **Inter 4.1** static Regular / Italic / Bold TTFs from the official release zip (SHA-256 recorded; extracted in an isolated folder).
   - **DejaVu Sans** + Oblique 2.37.3 as the fallback after finding ♀ / ♂ missing (F17).
   - Checked glyph coverage: accents, Greek, Cyrillic, µ, ×, °, «» are all present in Inter.
4. **`labels.py`**:
   - Ports of the website's `fmtDate` (DD-roman-YYYY), `fmtTime12`, `fmtTimeRange`, `buildLabel1Html`, `buildLabel2Html` and the notes rows from `renderNotes`, including JS quirks (`${undefined}`, number formatting).
   - The website's print layout in points (D21), greedy word wrap that also breaks over-long words, fallback-font runs per character, and an invariant (reproducible) PDF that starts on Inter so Helvetica is never declared.
   - A separate field-notes sheet.
5. **Looked at the output:** rendered sample sheets to PNG and checked them visually. The long site name wraps inside 2.5 in, identifications are italic, ♂ renders, boxes flow across rows, and the notes rows and notes box (line break preserved) are correct.
6. **`tests/test_labels.py`:**
   - **label text equals the website's own builders run in Node, on 15 cases** (all samples + nulls, missing keys, noon/midnight, invalid dates, HTML-looking text, 0.1+0.2, only-identification, no label 2);
   - valid US Letter PDF with only our fonts;
   - reproducible output;
   - layout within the margins, with pagination;
   - long words wrap inside the box;
   - every `which` option works.

   The tests caught ReportLab declaring Helvetica; fixed with `initialFontName`.
7. **`/api/labels/pdf`** (`server.py`): `{items, which: both|label1|label2|notes, action: open|save, filename}`. Validated (≤ 5,000 items), written to `<cache>/printouts/` and opened via `Dialogs.reveal` (now documented as "open a folder, or a file in its default app"). Printouts older than 7 days are removed. Save goes through the native Save As.
8. **`desktop.js`**: `EntoDesktop.printLabels(items, which)` and `saveLabelsPdf(...)`.
9. **Import edits:** Label Data's `printLabel(elementId)` (label1 / label2 / notes-content) and `printSheet()` now call `printLabels`. `window.open(` and `win.print()` are added to the import's forbidden list.
10. **Real-window flow test: 14/14 PASS**, now including "print buttons open PDFs (label, field notes, sheet)". The first run showed only 2 PDFs because the test added a record behind the page's back, so "Print sheet" saw an empty list; the test now calls the page's own `loadSheet()` first. Not an app bug.
11. **Tests: 126 passed, 1 skipped** (`pdftotext` not installed) with `ENTOTOOLS_NETWORK_TESTS=1`; import `--check` clean.


---

## Next steps

1. **Phase 5 — in-app updates.** Evaluate `tufup` (5.1); generate the update-signing key and store it only as a GitHub secret plus an offline backup (5.2, needs the user); check/download/verify/install/restart (5.3–5.6). This depends on Phase 6's builds existing, so the natural order is: a PyInstaller build locally → a GitHub Actions build for macOS + Windows (which also covers 0.6) → the updater on top.
2. **Try the app yourself:** `.venv/bin/python -m entotools_desktop`. Printing opens Preview.
3. Open decisions: feedback route (D5 / 3.7), the repos in iCloud (open question 4, F18).
4. Web repo follow-ups: F9, F1, F10.
