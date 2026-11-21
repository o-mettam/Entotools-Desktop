"""The local HTTP server the app window talks to (replaces the Cloudflare
Worker + static hosting).

Security model (PROJECT_LOG.md 1.1):
  * Listens on 127.0.0.1 only, on a random free port.
  * The Host header must be this exact 127.0.0.1/localhost:port, which
    defeats DNS-rebinding tricks from web pages.
  * A secret token is created at every launch. The window first opens
    /__launch?token=…, which sets it as an HttpOnly, SameSite=Strict cookie.
    Every other request (pages and API) must carry that cookie, so other
    programs, and websites open in the user's browser, can't use the API.
  * Write requests with an Origin header must come from this origin.
"""
from __future__ import annotations

import hmac
import json
import logging
import mimetypes
import re
import secrets
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import __version__, services
from .cache import Cache
from .csvio import CsvImportError
from .net import Net
from .paths import AppPaths
from .store import BackupScheduler, Store, StoreError
from .weather import WeatherService

log = logging.getLogger(__name__)

COOKIE_NAME = "ento_desktop"
SMALL_BODY = 64 * 1024          # search / normals / settings
LARGE_BODY = 60 * 1024 * 1024   # whole collection, imports
FLAGS = ["station-override", "season-normals", "collection-map"]  # D3: always on
MIME_EXTRA = {".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
              ".json": "application/json", ".svg": "image/svg+xml", ".woff2": "font/woff2",
              ".html": "text/html; charset=utf-8", ".png": "image/png", ".ico": "image/x-icon"}
KV_PATH = re.compile(r"/api/kv/([A-Za-z0-9_.:\-]{1,100})", re.ASCII)
PROXY_PATH = re.compile(r"/api/proxy/([a-z0-9\-]{1,40})", re.ASCII)


def default_web_root() -> Path:
    return Path(str(resources.files(__package__).joinpath("web")))


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


class App:
    """Everything one running copy of the app needs."""

    def __init__(self, paths: AppPaths, net: Net | None = None, web_root: Path | None = None,
                 token: str | None = None, backup_delay: float = 5.0):
        self.paths = paths.ensure()
        self.net = net or Net()
        self.cache = Cache(paths.http_cache)
        try:
            self.cache.purge()  # drop entries kept long past expiry (offline fallback window)
        except Exception:  # noqa: BLE001 — never block startup on housekeeping
            log.warning("cache purge failed", exc_info=True)
        self.weather = WeatherService(self.net, self.cache)
        self.store = Store(paths.database, paths.backups)
        self.backups = BackupScheduler(self.store, delay=backup_delay)
        self.token = token or secrets.token_urlsafe(32)
        self.web_root = (web_root or default_web_root()).resolve()
        self.httpd: ThreadingHTTPServer | None = None
        self.port = 0

    @property
    def origin(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def launch_url(self) -> str:
        return f"{self.origin}/__launch?token={self.token}"

    def start(self, port: int = 0) -> int:
        handler = type("Handler", (RequestHandler,), {"app": self})
        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, name="http", daemon=True).start()
        log.info("listening on %s", self.origin)
        return self.port

    def stop(self) -> None:
        self.backups.flush()
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        self.weather.pool.shutdown(wait=False, cancel_futures=True)
        self.store.close()
        self.cache.close()
        self.net.close()


class RequestHandler(BaseHTTPRequestHandler):
    app: App
    server_version = f"EntoTools-Desktop/{__version__}"
    sys_version = ""

    def log_message(self, fmt, *args):  # no query strings in logs (they can hold locations)
        log.debug("%s %s", self.command, urlsplit(self.path).path)

    # ── plumbing ─────────────────────────────────────────────────
    def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data) -> None:
        self._send(status, json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
                   "application/json; charset=utf-8", {"Cache-Control": "no-store"})

    def _body(self, limit: int):
        length = self.headers.get("Content-Length")
        if length is None or not length.isdigit():
            raise HttpError(411, "Content-Length required.")
        if int(length) > limit:
            raise HttpError(413, "Request is too large.")
        raw = self.rfile.read(int(length))
        try:
            return json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError) as e:
            raise HttpError(400, "Invalid request body — expected JSON.") from e

    def _authorized(self) -> bool:
        port = self.app.port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return False
        cookie = SimpleCookie(self.headers.get("Cookie") or "")
        got = cookie[COOKIE_NAME].value if COOKIE_NAME in cookie else ""
        return hmac.compare_digest(got, self.app.token)

    def _launch(self, query: dict) -> None:
        port = self.app.port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            return self._send(403, b"Forbidden", "text/plain")
        if not hmac.compare_digest((query.get("token") or [""])[0], self.app.token):
            return self._send(403, b"Forbidden", "text/plain")
        nxt = (query.get("next") or ["/"])[0]
        if not nxt.startswith("/") or nxt.startswith("//"):
            nxt = "/"
        self._send(302, b"", "text/plain", {
            "Location": nxt,
            "Set-Cookie": f"{COOKIE_NAME}={self.app.token}; Path=/; HttpOnly; SameSite=Strict",
            "Cache-Control": "no-store",
        })

    def _dispatch(self) -> None:
        url = urlsplit(self.path)
        query = parse_qs(url.query, keep_blank_values=True)
        if url.path == "/__launch" and self.command == "GET":
            return self._launch(query)
        if not self._authorized():
            return self._send(403, b"Forbidden", "text/plain")
        if self.command not in ("GET", "HEAD"):
            origin = self.headers.get("Origin")
            if origin and origin not in (self.app.origin, f"http://localhost:{self.app.port}"):
                return self._send(403, b"Forbidden", "text/plain")
        try:
            if url.path.startswith("/api/"):
                return self._api(url.path, query)
            m = services.TILE_PATH_RE.fullmatch(url.path)
            if m and self.command == "GET":
                status, png = services.tile(self.app.net, self.app.paths.tiles, *map(int, m.groups()))
                if png is None:
                    return self._send(status, b"", "image/png", {"Cache-Control": "no-store"})
                return self._send(200, png, "image/png", {"Cache-Control": "max-age=86400"})
            if self.command in ("GET", "HEAD"):
                return self._static(url.path)
            raise HttpError(405, "Method not allowed.")
        except HttpError as e:
            return self._json(e.status, {"error": str(e)})
        except Exception:  # noqa: BLE001
            log.exception("unhandled error for %s %s", self.command, url.path)
            return self._json(500, {"error": "An unexpected error occurred. Please try again."})

    do_GET = do_HEAD = do_POST = do_PUT = do_DELETE = _dispatch

    # ── API ──────────────────────────────────────────────────────
    def _api(self, path: str, query: dict) -> None:
        app, m, c = self.app, None, self.command
        if path == "/api/status/ping" and c == "GET":
            return self._json(200, {"ok": True, "ts": int(time.time() * 1000)})
        if path == "/api/status/check" and c == "GET":
            service = (query.get("service") or [""])[0]
            if service not in services.STATUS_SERVICES:
                return self._json(400, {"error": "Unknown service"})
            return self._json(200, services.check_service(app.net, service))
        if path == "/api/connectivity" and c == "GET":
            return self._json(200, {"online": app.net.internet_reachable(force=True)})
        if path == "/api/flags" and c == "GET":
            return self._json(200, {"flags": FLAGS})
        if path == "/api/version" and c == "GET":
            return self._json(200, {"version": __version__})
        if path == "/api/search" and c == "POST":
            return self._json(*app.weather.search(self._body(SMALL_BODY)))
        if path == "/api/normals" and c == "POST":
            return self._json(*app.weather.normals(self._body(SMALL_BODY)))
        if (m := PROXY_PATH.fullmatch(path)) and c == "GET":
            return self._json(*services.proxy(app.net, app.cache, m.group(1), {k: v[-1] for k, v in query.items()}))

        if path == "/api/collection" and c == "GET":
            env = app.store.get_envelope()
            meta = {"revision": env["revision"], "updatedAt": env["updatedAt"]} if env else {}
            return self._json(200, {"json": env, "meta": meta})
        if path == "/api/collection" and c == "PUT":
            try:
                result = app.store.save_envelope(self._body(LARGE_BODY))
            except StoreError as e:
                raise HttpError(400, str(e)) from e
            app.backups.changed()
            return self._json(200, result)
        if path == "/api/collection/import" and c == "POST":
            body = self._body(LARGE_BODY) or {}
            try:
                result = app.store.import_text(body.get("kind"), body.get("text") or "")
            except (StoreError, CsvImportError) as e:
                raise HttpError(400, str(e)) from e
            if result["added"] or result["updated"]:
                app.backups.changed()
            return self._json(200, result)
        if path == "/api/collection/export.csv" and c == "GET":
            layout = (query.get("layout") or ["full"])[0]
            if layout not in ("full", "web"):
                raise HttpError(400, "layout must be full or web.")
            return self._send(200, app.store.export_csv(layout).encode("utf-8"), "text/csv; charset=utf-8",
                              {"Cache-Control": "no-store",
                               "Content-Disposition": f'attachment; filename="entotools-collection-{layout}.csv"'})

        if path == "/api/kv" and c == "GET":
            return self._json(200, {"items": app.store.kv_all()})
        if m := KV_PATH.fullmatch(path):
            if c == "PUT":
                body = self._body(LARGE_BODY) or {}
                try:
                    app.store.kv_set(m.group(1), body.get("value"))
                except StoreError as e:
                    raise HttpError(400, str(e)) from e
                return self._json(200, {"ok": True})
            if c == "DELETE":
                app.store.kv_delete(m.group(1))
                return self._json(200, {"ok": True})

        if path == "/api/backup" and c == "GET":
            return self._json(200, app.store.backup_settings())
        if path == "/api/backup" and c == "PUT":
            try:
                return self._json(200, app.store.update_backup_settings(self._body(SMALL_BODY) or {}))
            except StoreError as e:
                raise HttpError(400, str(e)) from e
        if path == "/api/backup/now" and c == "POST":
            try:
                return self._json(200, app.store.backup_now(force=True))
            except OSError as e:
                raise HttpError(500, f"Could not write the backup: {e.strerror or e}") from e

        raise HttpError(404, "Not found")

    # ── static pages ─────────────────────────────────────────────
    def _static(self, path: str) -> None:
        rel = path.lstrip("/")
        target = (self.app.web_root / rel).resolve()
        if self.app.web_root not in target.parents and target != self.app.web_root:
            raise HttpError(404, "Not found")
        if target.is_dir():
            if not path.endswith("/"):
                return self._send(301, b"", "text/plain", {"Location": path + "/"})
            target = target / "index.html"
        if not target.is_file():
            notfound = self.app.web_root / "404.html"
            body = notfound.read_bytes() if notfound.is_file() else b"Not found"
            return self._send(404, body, "text/html; charset=utf-8")
        ctype = MIME_EXTRA.get(target.suffix.lower()) or mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        extra = {"Cache-Control": "no-cache"}
        if ctype.startswith("text/html"):
            extra["X-Frame-Options"] = "DENY"
        return self._send(200, target.read_bytes(), ctype, extra)


HTTPStatus  # re-exported for tests
