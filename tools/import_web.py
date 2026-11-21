"""Copy the EntoTools pages from the website repo and adapt them for desktop.

    .venv/bin/python tools/import_web.py [--web-repo ../EntoTools-Production] [--commit f948578]

Reads files with `git show <commit>:<path>` (the website's working tree is
never touched), applies every desktop change below as an exact, checked edit,
and writes the result into src/entotools_desktop/web/. If the website's code
changes so that an edit no longer matches, the script stops and names it;
nothing is half-applied. Desktop-owned files (desktop.js, desktop.css,
vendor/) are never overwritten.

Every change is listed here so a future re-import is a one-command job.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "src" / "entotools_desktop" / "web"
OVERRIDES = Path(__file__).resolve().parent / "web_overrides"
DEFAULT_COMMIT = "f948578"
DESKTOP_DATE = "November 21, 2026"

PAGES = {  # website template → served path
    "templates/entotools.html": "index.html",
    "templates/degree_day_calculator.html": "degree-day-calculator/index.html",
    "templates/gdd_lookup.html": "gdd-lookup/index.html",
    "templates/label_data.html": "sample-collection/index.html",
    "templates/collection_database.html": "collection-database/index.html",
    "templates/documentation.html": "documentation/index.html",
    "templates/privacy_policy.html": "privacy/index.html",
    "templates/terms_of_use.html": "terms/index.html",
    "templates/status.html": "status/index.html",
    "templates/404.html": "404.html",
    "templates/500.html": "500.html",
    "templates/503.html": "503.html",
}
ASSETS = {
    "public/theme.js": "theme.js",
    "public/theme.css": "theme.css",
    "public/tailwind.css": "tailwind.css",
    "public/ento-gdd.js": "ento-gdd.js",
    "public/log-capture.js": "log-capture.js",
    "public/sync/sync-core.js": "sync/sync-core.js",
}


@dataclass
class Edit:
    why: str
    old: str
    new: str
    count: int | None = 1      # exact number of matches required; None = any (0+)
    regex: bool = False
    max_lines: int | None = None  # refuse a match spanning more lines (guards runaway removals)
    template: bool = False        # regex `new` uses \1-style groups; otherwise it is inserted literally


def apply(name: str, text: str, edits: list[Edit]) -> str:
    for e in edits:
        if e.regex:
            n = len(re.findall(e.old, text, flags=re.M | re.S))
        else:
            n = text.count(e.old)
        if e.count is not None and n != e.count:
            sys.exit(f"✗ {name}: '{e.why}' expected {e.count} match(es), found {n}. The website changed; update tools/import_web.py.")
        if e.max_lines and e.regex:
            for m in re.finditer(e.old, text, flags=re.M | re.S):
                lines = m.group(0).count("\n") + 1
                if lines > e.max_lines:
                    sys.exit(f"✗ {name}: '{e.why}' would remove {lines} lines (limit {e.max_lines}). The website changed; check the edit.")
        if n:
            if e.regex:
                repl = e.new if e.template else (lambda _m, new=e.new: new)
                text = re.sub(e.old, repl, text, flags=re.M | re.S)
            else:
                text = text.replace(e.old, e.new)
    return text


def between(start: str, end: str) -> str:
    """Regex for start…end (inclusive), shortest match."""
    return re.escape(start) + r".*?" + re.escape(end)


# ── edits for every page ──────────────────────────────────────────
COMMON = [
    Edit("Google Fonts preconnect → none (fonts are bundled)",
         r'^[ \t]*<link rel="preconnect" href="https://fonts\.googleapis\.com">\n', "", None, regex=True),
    Edit("Google Fonts stylesheet → bundled Inter",
         r'<link href="https://fonts\.googleapis\.com/css2\?family=Inter[^"]*" rel="stylesheet">',
         '<link rel="stylesheet" href="/vendor/inter/inter.css">', None, regex=True),
    Edit("load desktop.css + desktop.js before theme.js (theme.js reads EntoKV)",
         r'^([ \t]*)<script src="/theme\.js\?v=2"></script>',
         r'\1<link rel="stylesheet" href="/desktop.css">\n\1<script src="/desktop.js"></script>\n\1<script src="/theme.js?v=2"></script>',
         1, regex=True, template=True),
    Edit("remove account.js (no accounts on desktop)", r'^[ \t]*<script src="/account\.js[^"]*"[^>]*></script>\n', "", None, regex=True),
    Edit("remove feedback.js (D5 undecided)", r'^[ \t]*<script src="/feedback\.js[^"]*"[^>]*></script>\n', "", None, regex=True),
    Edit("remove Google OAuth config", r'^[ \t]*<script src="/sync/config\.js[^"]*"></script>\n', "", None, regex=True),
    Edit("remove account sync provider", r'^[ \t]*<script src="/sync/provider-account\.js[^"]*"></script>\n', "", None, regex=True),
    Edit("remove the Google Drive settings block",
         between('<div id="cloud-backup"', '>Sync now</button>\n                            </div>\n'), "", None, regex=True),
    Edit("remove the Google Drive loader comment",
         between("    <!-- Google Drive sync (provider-gdrive.js", "-->\n"), "", None, regex=True),
    Edit("remove the Google Drive set-up code (initCloudBackup, loadScriptOnce)",
         between('        /* ── Cloud Backup (Google Drive) — gated behind the "gdrive-sync"', "        let cloudBackupInitialised = false;\n"),
         "        /* Desktop: no Google Drive or account sync. The collection is saved in the\n"
         "           app's database and backed up as CSV automatically (desktop.js). */\n",
         None, regex=True, max_lines=100),
    Edit("Chart.js from the bundle", "https://cdn.jsdelivr.net/npm/chart.js@4.5.1", "/vendor/chartjs/chart.umd.min.js", None),
    Edit("datalabels plugin from the bundle", "https://cdn.jsdelivr.net/npm/chartjs-plugin-datalabels@2.2.0", "/vendor/chartjs/datalabels.min.js", None),
    Edit("annotation plugin from the bundle", "https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3.1.0", "/vendor/chartjs/annotation.min.js", None),
    Edit("storage → EntoKV (desktop.js)", "localStorage", "EntoKV", None),
    Edit("settings wording", "saved searches from your browser.", "saved searches from this computer.", None),
    Edit("GitHub link → the desktop repo", "https://github.com/o-mettam/EntoTools-Production", "https://github.com/o-mettam/Entotools-Desktop", None),
]

PAGE_EDITS: dict[str, list[Edit]] = {
    "templates/label_data.html": [
        Edit("remove the account/Drive start-up listener (account.js never runs on desktop)",
             between("        // account.js fires this once it knows whether the visitor is logged\n",
                     "failed to load Drive sync scripts:', err);\n            });\n        });\n"),
             "", 1, regex=True, max_lines=40),
        Edit("Nominatim reverse → proxy (no browser User-Agent header)",
             "fetch(`https://nominatim.openstreetmap.org/reverse?lat=${lat}&lon=${lon}&format=json&zoom=10`, {\n"
             "                    headers: { 'User-Agent': 'EntoTools/1.0 (educational-project)' }\n"
             "                });",
             "fetch(`/api/proxy/nominatim-reverse?lat=${lat}&lon=${lon}&format=json&zoom=10`);"),
        Edit("elevation → proxy", "https://api.open-meteo.com/v1/elevation?", "/api/proxy/om-elevation?"),
        Edit("sunset → proxy", "https://api.sunrise-sunset.org/json?", "/api/proxy/sunrise-sunset?"),
        Edit("hourly humidity → proxy", "https://archive-api.open-meteo.com/v1/archive?", "/api/proxy/om-archive?"),
        Edit("print one label / the field notes → PDF (Phase 4; replaces the pop-up + print())",
             between("        function printLabel(elementId) {\n", "setTimeout(() => win.print(), 300);\n        }"),
             """        function printLabel(elementId) {
            // Desktop: an exact-size PDF opens in the system's PDF viewer, to print or save.
            if (!collectionData || !collectionData.dateStart) { console.warn('[LabelData] printLabel called but no generated collection'); return; }
            const which = { label1: 'label1', label2: 'label2', 'notes-content': 'notes' }[elementId] || 'both';
            EntoDesktop.printLabels([{ data: collectionData }], which);
        }""", 1, regex=True, max_lines=30),
        Edit("print the whole sheet → PDF",
             between("        function printSheet() {\n", "setTimeout(() => win.print(), 300);\n        }"),
             """        function printSheet() {
            if (labelSheet.length === 0) { console.warn('[LabelData] printSheet called but sheet is empty'); return; }
            console.log('[LabelData] printing sheet with', labelSheet.length, 'label(s)');
            EntoDesktop.printLabels(labelSheet.map((item) => ({ data: item.data || {} })), 'both');
        }""", 1, regex=True, max_lines=35),
        Edit("CSV downloads → Save As…",
             between("        function downloadBlob(blob, filename) {\n", "setTimeout(() => URL.revokeObjectURL(url), 0);\n        }"),
             "        function downloadBlob(blob, filename) {\n            EntoDesktop.saveBlob(blob, filename);\n        }",
             1, regex=True),
    ],
    "templates/collection_database.html": [
        Edit("map entry point: shown from the desktop flags event (was inside the account listener)",
             between("        // account.js fires this once it knows whether the visitor is logged\n",
                     "failed to load Drive sync scripts:', err);\n            });\n        });\n"),
             """        // Desktop: features are always on (D3). desktop.js fires entoflags:updated
        // once the page has loaded; show the collection map's entry point then.
        document.addEventListener('entoflags:updated', () => {
            const mapOn = !!(window.EntoFlags && window.EntoFlags.has('collection-map'));
            document.getElementById('collection-map-section').classList.toggle('hidden', !mapOn);
            if (!mapOn && collectionMapOpen) toggleCollectionMap();
        });
""", 1, regex=True, max_lines=40),
        Edit("import accepts CSV and JSON exports", 'accept=".csv" class="hidden" data-change="importCSV"',
             'accept=".csv,.json" class="hidden" data-change="importCSV"'),
        Edit("Export CSV → Save As… (full, lossless layout from the app database)",
             between("            // The anchor must be in the document and the object URL must outlive\n            // the click, or some browsers cancel the download.\n            const blob = new Blob([EntoCsv.buildCsv(entries)]",
                     "setTimeout(() => URL.revokeObjectURL(url), 0);\n        }"),
             "            EntoDesktop.saveCollectionCsv(`collection_database_${new Date().toLocaleDateString('en-CA')}.csv`, 'full');\n        }",
             1, regex=True),
        Edit("Import → app database (merges; reads desktop and website CSV/JSON)",
             between("        function importCSV(input) {\n", "            reader.readAsText(file);\n        }"),
             """        function importCSV(input) {
            // Desktop: the app merges the file into its database (newer edits win,
            // no duplicates, website exports' negative numbers repaired — F9).
            if (input && input.target) input = input.target;
            const file = input.files[0];
            if (!file) return;
            console.log('[CollectionDB] importing file (' + file.size + ' bytes)');
            input.value = '';
            EntoDesktop.importFile(file).then((r) => {
                dirtyThisSession = true;
                expandedIdx = -1;
                renderTable();
                const parts = [`${r.added} added`, `${r.updated} updated`];
                if (r.unchanged) parts.push(`${r.unchanged} already up to date`);
                if (r.duplicates) parts.push(`${r.duplicates} duplicate${r.duplicates !== 1 ? 's' : ''} skipped`);
                if (r.kept_newer) parts.push(`${r.kept_newer} kept as is (your copy is newer)`);
                let msg = 'Import complete: ' + parts.join(', ') + '.';
                if (r.problems && r.problems.length) {
                    msg += '\\n\\n' + r.problems.length + ' row(s) skipped:\\n' + r.problems.slice(0, 10).join('\\n') + (r.problems.length > 10 ? '\\n…' : '');
                }
                alert(msg);
            }).catch((err) => {
                console.error('[CollectionDB] import error:', err);
                alert('Import failed: ' + err.message);
            });
        }""",
             1, regex=True),
        Edit("no leave-page warning (changes are saved and backed up immediately)",
             "            if (!dirtyThisSession) return;\n",
             "            return; // desktop: every change is saved immediately and backed up automatically\n"),
        Edit("Leaflet JS from the bundle", "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.js", "/vendor/leaflet/leaflet.js"),
        Edit("Leaflet CSS from the bundle", "https://cdn.jsdelivr.net/npm/leaflet@1.9.4/dist/leaflet.css", "/vendor/leaflet/leaflet.css"),
        Edit("map tiles through the app (cached, offline-capable)", "https://tile.openstreetmap.org/{z}/{x}/{y}.png", "/tiles/{z}/{x}/{y}.png"),
    ],
    "templates/degree_day_calculator.html": [
        Edit("save-search name: in-page dialog instead of prompt()", "        function promptSaveSearch() {", "        async function promptSaveSearch() {"),
        Edit("save-search name: await the dialog", "const name = prompt('Name this search:');", "const name = await EntoDesktop.prompt('Name this search:');"),
        Edit("chart PNG → Save As…",
             between("            tempCanvas.toBlob(function(blob) {\n", "            }, 'image/png');"),
             "            tempCanvas.toBlob(function(blob) {\n"
             "                EntoDesktop.saveBlob(blob, `${filename}-${new Date().toLocaleDateString('en-CA')}.png`);\n"
             "            }, 'image/png');",
             1, regex=True),
        Edit("table CSV → Save As…",
             between("            const url = URL.createObjectURL(blob);\n            const a = document.createElement('a');\n            a.href = url;\n            a.download = `${filename}-${new Date().toISOString().split('T')[0]}.csv`;",
                     "URL.revokeObjectURL(url);\n        }"),
             "            EntoDesktop.saveBlob(blob, `${filename}-${new Date().toLocaleDateString('en-CA')}.csv`);\n        }",
             1, regex=True),
    ],
    "templates/documentation.html": [
        Edit("docs: cache location", "Forward geocode results are cached in Cloudflare KV for 24 hours",
             "Forward geocode results are cached on this computer for 24 hours"),
        Edit("docs: saved searches", "Search results can be saved to your browser's local storage for quick access later.",
             "Search results can be saved in the app for quick access later."),
        Edit("docs: label sheet storage",
             "Label sheet data is stored in your browser's local storage. It persists between sessions but will be lost if you clear your browser cache.",
             "Label sheet data is saved in the app's database on this computer and included in the automatic CSV backups."),
        Edit("docs: collection database warning",
             "This is a <strong>local browser database</strong>. If you clear your cache or reset your browser, <strong>the database will be lost</strong>. It is highly recommended to export the CSV file after each session.",
             "Your collection is saved on <strong>this computer</strong>, and a CSV backup is written automatically after every change (Settings → Data &amp; backups shows where). Copy those backups somewhere safe, such as another drive, from time to time."),
        Edit("docs: storage summary",
             r"<li><strong>Local Storage:</strong> Saved searches, label sheets, and the collection database are stored in your browser\..*?</li>",
             "<li><strong>Your data:</strong> Saved searches, label sheets and the collection database are stored on this computer, with automatic CSV backups in the folder shown under Settings → Data &amp; backups. To move to another computer, import a backup CSV in the Collection Database.</li>",
             1, regex=True, max_lines=1),
    ],
    "templates/status.html": [
        Edit("status: describe the local app service", "description: 'Our own worker handling search, feedback, and data processing',",
             "description: 'The app\u2019s own local service (weather search, your collection and backups)',"),
        Edit("status: GitHub is for updates now", "name: 'GitHub API',\n                description: 'Used for feedback/issue submission',",
             "name: 'GitHub',\n                description: 'Used to check for app updates',"),
    ],
    "templates/privacy_policy.html": [
        Edit("desktop privacy text", between('<main class="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8">\n', "    </main>"),
             '<main class="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8">\n' + (OVERRIDES / "privacy_main.html").read_text() + "    </main>",
             1, regex=True),
        Edit("date", r"Last updated: [A-Z][a-z]+ \d{1,2}, \d{4}\.", f"Last updated: {DESKTOP_DATE}.", 1, regex=True),
    ],
    "templates/terms_of_use.html": [
        Edit("desktop terms text", between('<main class="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8">\n', "    </main>"),
             '<main class="max-w-4xl mx-auto px-4 sm:px-6 py-6 sm:py-8">\n' + (OVERRIDES / "terms_main.html").read_text() + "    </main>",
             1, regex=True),
        Edit("date", r"Last updated: [A-Z][a-z]+ \d{1,2}, \d{4}\.", f"Last updated: {DESKTOP_DATE}.", 1, regex=True),
    ],
}

ASSET_EDITS: dict[str, list[Edit]] = {
    "public/theme.js": [
        Edit("version shown in the footer = the desktop app's", re.escape("var APP_VERSION = '") + r"[0-9.]+';",
             "var APP_VERSION = window.ENTO_DESKTOP_VERSION || 'desktop';", 1, regex=True),
        Edit("storage → EntoKV", "localStorage", "EntoKV", None),
    ],
    "public/sync/sync-core.js": [
        Edit("storage → EntoKV (the collection key is routed to the app database)", "localStorage", "EntoKV", None),
    ],
}

# Nothing on these lists may survive in any output file.
FORBIDDEN = [
    "fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net", "localStorage",
    "/account.js", "/feedback.js", "accounts.google.com", "provider-gdrive", "/sync/config.js",
    "nominatim.openstreetmap.org/reverse?", "api.open-meteo.com/v1", "archive-api.open-meteo.com/v1",
    "api.sunrise-sunset.org/json", "tile.openstreetmap.org/{z}", 'id="cloud-backup"',
    "entoaccount:ready', (e)", "initCloudBackup()", "EntoAccountProvider",
    "win.print()", "window.open(",
]


# The documentation page names these services' addresses in its text (it
# explains where data comes from); that is not a request, so it's allowed.
DOC_MENTIONS = {"templates/documentation.html": ("api.open-meteo.com/v1", "archive-api.open-meteo.com/v1", "api.sunrise-sunset.org/json")}


def git_show(repo: Path, commit: str, path: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(repo), "show", f"{commit}:{path}"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--web-repo", type=Path, default=ROOT.parent / "EntoTools-Production")
    ap.add_argument("--commit", default=DEFAULT_COMMIT)
    ap.add_argument("--check", action="store_true", help="don't write; exit 1 if the files on disk differ from a fresh import")
    a = ap.parse_args()

    outputs: dict[str, bytes] = {}
    for src, dst in {**PAGES, **ASSETS}.items():
        raw = git_show(a.web_repo, a.commit, src)
        if dst.endswith(".css"):
            outputs[dst] = raw
            continue
        text = raw.decode("utf-8")
        edits = (COMMON + PAGE_EDITS.get(src, [])) if src in PAGES else ASSET_EDITS.get(src, [])
        text = apply(src, text, edits)
        bad = [f for f in FORBIDDEN if f in text and f not in DOC_MENTIONS.get(src, ())]
        if bad:
            sys.exit(f"✗ {src}: still contains {bad}. Add an edit for it.")
        if src in PAGES and '<script src="/desktop.js"></script>' not in text:
            sys.exit(f"✗ {src}: desktop.js not loaded.")
        outputs[dst] = text.encode("utf-8")

    if a.check:
        stale = [dst for dst, data in outputs.items() if not (OUT / dst).is_file() or (OUT / dst).read_bytes() != data]
        if stale:
            sys.exit("✗ these files differ from a fresh import (edited by hand, or the import changed): " + ", ".join(sorted(stale)))
        print(f"✓ {len(outputs)} imported files match a fresh import from {a.commit}")
        return

    manifest = [f"# Imported by tools/import_web.py from EntoTools-Production @ {a.commit}", "# sha256  path"]
    for dst, data in sorted(outputs.items()):
        target = OUT / dst
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest.append(f"{hashlib.sha256(data).hexdigest()}  {dst}")
    (OUT / "IMPORTED.txt").write_text("\n".join(manifest) + "\n")
    print(f"✓ {len(outputs)} files written to {OUT.relative_to(ROOT)} (from {a.commit})")


if __name__ == "__main__":
    main()
