"""Phase 1.1 / 1.8 / 2.2 — the local server: access control, routes, offline."""
from __future__ import annotations

import json
import time

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


@pytest.fixture
def env(tmp_path):
    up = Upstream()
    net = Net(transport=httpx.MockTransport(up.handler), sleep=lambda s: None, probe=lambda: up.online)
    app = App(AppPaths(tmp_path / "data", tmp_path / "cache", tmp_path / "backups"), net=net, backup_delay=0.05)
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
    assert r.headers["x-content-type-options"] == "nosniff"
    assert client.get("/placeholder.js").headers["content-type"].startswith("text/javascript")
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
