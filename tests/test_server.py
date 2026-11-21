"""Phase 1.1 / 1.8 / 2.2 — the local server: access control, routes, offline."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx
import pytest

from entotools_desktop import csvio
from entotools_desktop.net import Net
from entotools_desktop.paths import AppPaths
from entotools_desktop.server import App
from samples import samples

PNG = b"\x89PNG\r\n\x1a\nfake-tile"


class Upstream:
    """Fake internet. `online=False` makes every connection fail."""

    def __init__(self):
        self.online = True
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(str(request.url))
        if not self.online:
            raise httpx.ConnectError("network unreachable", request=request)
        host = request.url.host
        if host == "tile.openstreetmap.org":
            return httpx.Response(200, content=PNG)
        if host == "api.open-meteo.com" and request.url.path == "/v1/elevation":
            return httpx.Response(200, json={"elevation": [113.0]})
        return httpx.Response(404, json={"error": "not mocked"})


class FakeDialogs:
    def __init__(self, tmp):
        self.tmp, self.answer, self.opened, self.revealed = tmp, "save", [], []

    def save_path(self, name):
        return None if self.answer == "cancel" else str(self.tmp / "out" / name)

    def choose_folder(self, start):
        return None if self.answer == "cancel" else str(self.tmp / "chosen")

    def open_url(self, url):
        self.opened.append(url)

    def reveal(self, path):
        self.revealed.append(path)


@pytest.fixture
def env(tmp_path):
    up = Upstream()
    net = Net(transport=httpx.MockTransport(up.handler), sleep=lambda s: None, probe=lambda: up.online)
    (tmp_path / "out").mkdir()
    app = App(AppPaths(tmp_path / "data", tmp_path / "cache", tmp_path / "backups"), net=net, backup_delay=0.05,
              dialogs=FakeDialogs(tmp_path))
    app.start()
    client = httpx.Client(base_url=app.origin, follow_redirects=False)
    yield app, client, up
    client.close()
    app.stop()


def signed_in(app, client):
    r = client.get(f"/__launch?token={app.token}")
    assert r.status_code == 302 and r.headers["location"] == "/"
    assert "HttpOnly" in r.headers["set-cookie"] and "SameSite=Strict" in r.headers["set-cookie"]
    return client


# ── access control ───────────────────────────────────────────────
def test_everything_is_forbidden_without_the_launch_cookie(env):
    app, client, _ = env
    for path in ("/", "/api/status/ping", "/api/collection", "/api/kv", "/tiles/0/0/0.png"):
        assert client.get(path).status_code == 403, path


def test_wrong_token_does_not_sign_in(env):
    app, client, _ = env
    assert client.get("/__launch?token=nope").status_code == 403
    assert client.get("/api/status/ping").status_code == 403


def test_foreign_host_header_is_refused_even_with_the_cookie(env):
    app, client, _ = env
    signed_in(app, client)
    assert client.get("/api/status/ping", headers={"Host": f"evil.example:{app.port}"}).status_code == 403
    assert client.get(f"/__launch?token={app.token}", headers={"Host": "evil.example"}).status_code == 403


def test_cross_origin_writes_are_refused(env):
    app, client, _ = env
    signed_in(app, client)
    r = client.put("/api/kv/ento_theme", json={"value": "dark"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert client.put("/api/kv/ento_theme", json={"value": "dark"}, headers={"Origin": app.origin}).status_code == 200


def test_launch_redirect_stays_on_this_origin(env):
    app, client, _ = env
    r = client.get(f"/__launch?token={app.token}&next=//evil.example/x")
    assert r.headers["location"] == "/"


# ── pages ────────────────────────────────────────────────────────
def test_static_pages_and_traversal(env):
    app, client, _ = env
    signed_in(app, client)
    r = client.get("/")
    assert r.status_code == 200 and "EntoTools" in r.text and r.headers["x-frame-options"] == "DENY"
    assert "connect-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/desktop.js").headers["content-type"].startswith("text/javascript")
    for p in ("/../server.py", "/%2e%2e/server.py", "/..%2fserver.py"):
        assert client.get(p).status_code == 404, p


# ── API ──────────────────────────────────────────────────────────
def test_basic_endpoints(env):
    app, client, _ = env
    signed_in(app, client)
    assert client.get("/api/status/ping").json()["ok"] is True
    assert client.get("/api/flags").json() == {"flags": ["station-override", "season-normals", "collection-map"]}
    assert client.get("/api/status/check?service=bogus").status_code == 400
    assert client.get("/api/nope").status_code == 404


def test_search_validation_through_http(env):
    app, client, up = env
    signed_in(app, client)
    r = client.post("/api/search", json={"mode": "latlon", "lat": "38.9", "lon": "-77", "dateRanges": [
        {"startDate": "2025-06-30", "endDate": "2025-06-01"}]})
    assert r.status_code == 400 and r.json()["error"] == "End date is before start date for 'a range'."
    assert client.post("/api/search", content=b"{nope", headers={"Content-Type": "application/json"}).status_code == 400
    assert up.calls == []


def test_impossible_dates_are_rejected(env):
    app, client, _ = env
    signed_in(app, client)
    r = client.post("/api/search", json={"mode": "latlon", "lat": "38.9", "lon": "-77", "dateRanges": [
        {"startDate": "2025-02-30", "endDate": "2025-03-05", "label": "Feb"}]})
    assert r.status_code == 400 and r.json()["error"] == "Invalid date format for 'Feb'."


def test_collection_kv_import_export_backup(env):
    app, client, _ = env
    signed_in(app, client)
    assert client.get("/api/collection").json() == {"json": None, "meta": {}}
    r = client.put("/api/collection", json={"schemaVersion": 2, "revision": 2, "entries": samples()})
    assert r.status_code == 200 and r.json()["revision"] == 2
    body = client.get("/api/collection").json()
    assert body["meta"]["revision"] == 2 and len(body["json"]["entries"]) == len(samples())

    csv = client.get("/api/collection/export.csv")
    assert csv.status_code == 200 and csv.headers["content-type"].startswith("text/csv") and "Record ID" in csv.text
    assert "Record ID" not in client.get("/api/collection/export.csv?layout=web").text

    again = client.post("/api/collection/import", json={"kind": "csv", "text": csv.text}).json()
    assert again["unchanged"] == len(samples())
    bad = client.post("/api/collection/import", json={"kind": "csv", "text": "x"})
    assert bad.status_code == 400 and "header row" in bad.json()["error"]

    assert client.put("/api/kv/ento_theme", json={"value": "dark"}).status_code == 200
    assert client.get("/api/kv").json() == {"items": {"ento_theme": "dark"}}
    assert client.put("/api/kv/ento_theme", json={"value": 3}).status_code == 400
    assert client.delete("/api/kv/ento_theme").status_code == 200

    time.sleep(0.3)  # the PUT above scheduled an automatic backup
    settings = client.get("/api/backup").json()
    assert settings["auto"] is True and settings["last_backup_file"]
    assert client.post("/api/backup/now").json()["written"] is True


def test_oversized_body_is_refused(env):
    app, client, _ = env
    signed_in(app, client)
    r = client.post("/api/search", content=b"{" + b" " * 70_000 + b"}", headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_proxy_allowlist_and_cache(env):
    app, client, up = env
    signed_in(app, client)
    assert client.get("/api/proxy/unknown").status_code == 404
    assert client.get("/api/proxy/om-elevation?latitude=1&longitude=2&evil=1").status_code == 400
    r1 = client.get("/api/proxy/om-elevation?latitude=35.83&longitude=-78.76")
    r2 = client.get("/api/proxy/om-elevation?latitude=35.83&longitude=-78.76")
    assert r1.json() == r2.json() == {"elevation": [113.0]}
    assert len([c for c in up.calls if "elevation" in c]) == 1  # second answer came from the cache


def test_tiles_validate_and_cache(env):
    app, client, up = env
    signed_in(app, client)
    assert client.get("/tiles/2/4/0.png").status_code == 404  # x out of range for zoom 2
    assert client.get("/tiles/20/0/0.png").status_code == 404
    r = client.get("/tiles/3/2/5.png")
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert (app.paths.tiles / "3" / "2" / "5.png").read_bytes() == PNG


# ── offline (1.8, D7) ────────────────────────────────────────────
def test_offline_search_answers_quickly_and_clearly(env):
    app, client, up = env
    signed_in(app, client)
    up.online = False
    t0 = time.monotonic()
    r = client.post("/api/search", json={"mode": "latlon", "lat": "38.9", "lon": "-77",
                                         "dateRanges": [{"startDate": "2025-06-01", "endDate": "2025-06-30"}]})
    assert time.monotonic() - t0 < 5
    assert r.status_code == 503 and r.json()["offline"] is True and "offline" in r.json()["error"]
    assert client.get("/api/connectivity").json() == {"online": False}


def test_offline_normals_and_status(env):
    app, client, up = env
    signed_in(app, client)
    up.online = False
    r = client.post("/api/normals", json={"lat": 35.78, "lon": -78.64, "provider": "open-meteo"})
    assert r.status_code == 503 and r.json()["offline"] is True
    assert client.get("/api/status/check?service=ncei").json()["error"] == "Offline"


def test_offline_serves_cached_proxy_answers_and_tiles(env):
    app, client, up = env
    signed_in(app, client)
    client.get("/api/proxy/om-elevation?latitude=35.83&longitude=-78.76")
    client.get("/tiles/3/2/5.png")
    # Make the cached copies "expired", then go offline: still served.
    app.cache._db.execute("UPDATE cache SET expires_at = 1")
    app.cache._db.commit()
    import os
    os.utime(app.paths.tiles / "3" / "2" / "5.png", (1, 1))
    up.online = False
    assert client.get("/api/proxy/om-elevation?latitude=35.83&longitude=-78.76").json() == {"elevation": [113.0]}
    assert client.get("/tiles/3/2/5.png").content == PNG
    r = client.get("/api/proxy/om-elevation?latitude=1&longitude=1")  # never fetched
    assert r.status_code == 503 and r.json()["offline"] is True
    assert client.get("/tiles/4/1/1.png").status_code == 503


def test_offline_collection_still_works(env):
    app, client, up = env
    signed_in(app, client)
    up.online = False
    assert client.put("/api/collection", json={"revision": 1, "entries": samples()}).status_code == 200
    assert client.post("/api/backup/now").json()["written"] is True
    csv = client.get("/api/collection/export.csv").text
    assert len(csvio.read_csv(csv)[0]) == len(samples())
    assert up.calls == []  # nothing here needed the internet


# ── Phase 3 endpoints ────────────────────────────────────────────
def test_boot_has_everything_a_page_needs(env):
    app, client, _ = env
    signed_in(app, client)
    client.put("/api/kv/ento_theme", json={"value": "dark"})
    client.put("/api/collection", json={"revision": 1, "entries": samples()[:2]})
    boot = client.get("/api/boot").json()
    assert boot["flags"] == ["station-override", "season-normals", "collection-map"]
    assert boot["kv"] == {"ento_theme": "dark"} and len(boot["collection"]["entries"]) == 2
    assert boot["backup"]["auto"] is True and boot["selftest"] is False


def test_save_as(env, tmp_path):
    app, client, _ = env
    signed_in(app, client)
    import base64
    r = client.post("/api/save", json={"filename": "chart.png", "data_b64": base64.b64encode(PNG).decode()}).json()
    assert r == {"saved": True, "path": str(tmp_path / "out" / "chart.png")}
    assert (tmp_path / "out" / "chart.png").read_bytes() == PNG
    client.put("/api/collection", json={"revision": 1, "entries": samples()})
    r = client.post("/api/save", json={"filename": "../../evil/col.csv", "collection_layout": "full"}).json()
    assert r["path"] == str(tmp_path / "out" / "col.csv")  # path parts stripped from the suggested name
    assert len(csvio.read_csv((tmp_path / "out" / "col.csv").read_text(encoding="utf-8"))[0]) == len(samples())
    assert client.post("/api/save", json={"filename": "x.exe", "data_b64": ""}).status_code == 400
    assert client.post("/api/save", json={"filename": "x.png", "data_b64": "@@@"}).status_code == 400
    app.dialogs.answer = "cancel"
    assert client.post("/api/save", json={"filename": "x.png", "data_b64": ""}).json() == {"saved": False}


def test_open_url_only_for_web_links(env):
    app, client, _ = env
    signed_in(app, client)
    assert client.post("/api/open-url", json={"url": "https://www.ncei.noaa.gov/"}).status_code == 200
    for bad in ("file:///etc/passwd", "javascript:alert(1)", "/local", "https://x y"):
        assert client.post("/api/open-url", json={"url": bad}).status_code == 400, bad
    assert app.dialogs.opened == ["https://www.ncei.noaa.gov/"]


def test_backup_folder_choose_and_open(env, tmp_path):
    app, client, _ = env
    signed_in(app, client)
    r = client.post("/api/backup/choose-folder").json()
    assert r["changed"] is True and r["dir"] == str(tmp_path / "chosen")
    client.post("/api/backup/open-folder")
    assert app.dialogs.revealed == [str(tmp_path / "chosen")] and (tmp_path / "chosen").is_dir()
    app.dialogs.answer = "cancel"
    assert client.post("/api/backup/choose-folder").json()["changed"] is False


def test_without_a_window_dialog_endpoints_say_so(tmp_path):
    app = App(AppPaths(tmp_path / "d", tmp_path / "c", tmp_path / "b"), net=Net(probe=lambda: True))
    app.start()
    try:
        c = signed_in(app, httpx.Client(base_url=app.origin, follow_redirects=False))
        assert c.post("/api/open-url", json={"url": "https://example.org"}).status_code == 501
    finally:
        app.stop()


def test_client_log_is_capped_and_selftest_script_is_off_by_default(env):
    app, client, _ = env
    signed_in(app, client)
    assert client.post("/api/client-log", json={"level": "error", "page": "/x", "message": "m" * 2000}).status_code == 200
    entries = client.get("/api/client-log").json()["entries"]
    assert len(entries[0]["message"]) == 500
    assert client.get("/api/selftest.js").status_code == 404


def test_every_page_csp_matches_its_inline_scripts(env):
    """The hashes in each page's CSP must be exactly its inline scripts, or
    the page would break (a script blocked) or be weaker than intended."""
    import base64
    import hashlib
    import re
    from entotools_desktop.server import default_web_root
    app, client, _ = env
    signed_in(app, client)
    root = default_web_root()
    for page in sorted(root.rglob("*.html")):
        rel = "/" + page.relative_to(root).as_posix().replace("index.html", "")
        r = client.get(rel)
        assert r.status_code == 200, rel
        scripts = re.findall(rb"<script(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script\s*>", page.read_bytes(), re.S | re.I)
        want = {"'sha256-" + base64.b64encode(hashlib.sha256(s).digest()).decode() + "'" for s in scripts}
        got = set(re.findall(r"'sha256-[^']+'", r.headers["content-security-policy"]))
        assert got == want, rel
        assert "unsafe-inline" not in r.headers["content-security-policy"].split("script-src")[1].split(";")[0]


# ── Phase 4: PDF labels ──────────────────────────────────────────
def test_labels_pdf_open_and_save(env, tmp_path):
    app, client, _ = env
    signed_in(app, client)
    items = [{"data": e["data"]} for e in samples()]
    r = client.post("/api/labels/pdf", json={"items": items, "which": "both"}).json()
    assert r["opened"] is True and app.dialogs.revealed == [r["path"]]
    opened = Path(r["path"])
    assert opened.parent == app.paths.cache / "printouts" and opened.name.startswith("EntoTools-labels-")
    assert opened.read_bytes().startswith(b"%PDF-")
    notes = client.post("/api/labels/pdf", json={"items": items[:1], "which": "notes"}).json()
    assert Path(notes["path"]).name.startswith("EntoTools-field-notes-")
    saved = client.post("/api/labels/pdf", json={"items": items, "which": "label2", "action": "save", "filename": "my labels"}).json()
    assert saved == {"saved": True, "path": str(tmp_path / "out" / "my labels.pdf")}
    assert (tmp_path / "out" / "my labels.pdf").read_bytes().startswith(b"%PDF-")


def test_labels_pdf_validation_and_cleanup(env):
    app, client, _ = env
    signed_in(app, client)
    assert client.post("/api/labels/pdf", json={"items": "x"}).status_code == 400
    assert client.post("/api/labels/pdf", json={"items": [1]}).status_code == 400
    assert client.post("/api/labels/pdf", json={"items": [], "which": "all"}).status_code == 400
    old = app.paths.cache / "printouts" / "EntoTools-labels-old.pdf"
    old.parent.mkdir(parents=True, exist_ok=True)
    old.write_bytes(b"%PDF-old")
    os.utime(old, (1, 1))
    client.post("/api/labels/pdf", json={"items": [], "which": "both"})
    assert not old.exists()  # printouts older than a week are removed
