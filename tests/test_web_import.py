"""Phase 3 — the pages in src/entotools_desktop/web are exactly what
tools/import_web.py produces from the pinned website commit (no hand edits
that a re-import would silently undo), and none of them reaches the internet
directly."""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "src" / "entotools_desktop" / "web"
WEB_REPO = ROOT.parent / "EntoTools-Production"


@pytest.mark.skipif(not (WEB_REPO / ".git").exists(), reason="website repo not checked out next to this one")
def test_imported_files_match_a_fresh_import():
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "import_web.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_manifest_hashes_match_files():
    import hashlib
    lines = [l for l in (WEB / "IMPORTED.txt").read_text().splitlines() if l and not l.startswith("#")]
    assert len(lines) >= 18
    for line in lines:
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((WEB / rel).read_bytes()).hexdigest() == digest, rel


def test_no_page_loads_anything_from_the_internet():
    for f in list(WEB.rglob("*.html")) + [p for p in WEB.rglob("*.js") if "vendor" not in p.parts]:
        text = f.read_text(encoding="utf-8")
        # src= / href= to another site in markup, or fetch() of an absolute URL in code
        loads = re.findall(r'<(?:script|link|img)[^>]+(?:src|href)="https?://', text)
        fetches = re.findall(r"fetch\(\s*[`'\"]https?://", text)
        assert not loads and not fetches, (f.name, loads, fetches)
