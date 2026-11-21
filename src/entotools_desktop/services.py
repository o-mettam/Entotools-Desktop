"""Health checks, pass-through proxies and the map-tile proxy.

Proxies replace the calls Label Data made straight from the browser
(Nominatim reverse, Open-Meteo elevation and hourly archive, Sunrise-Sunset),
so every outbound request carries the app's User-Agent, obeys Nominatim's rate
limit, and is cached. When offline, the last cached answer is served.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import httpx

from .cache import Cache
from .net import Net, OfflineError

log = logging.getLogger(__name__)

# ── /api/status/* (port of src/lib/status.js) ─────────────────────
STATUS_SERVICES = {
    "ncei": {"name": "NOAA NCEI", "timeout": 10.0,
             "url": "https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries&stations=USW00094728&startDate=2024-01-01&endDate=2024-01-01&dataTypes=TMAX&format=json"},
    "open-meteo": {"name": "Open-Meteo", "timeout": 8.0,
                   "url": "https://api.open-meteo.com/v1/forecast?latitude=40&longitude=-74&current_weather=true"},
    "nominatim": {"name": "Nominatim (OpenStreetMap)", "timeout": 8.0,
                  "url": "https://nominatim.openstreetmap.org/search?q=New+York&format=json&limit=1"},
    "github": {"name": "GitHub (updates)", "timeout": 8.0, "url": "https://api.github.com/rate_limit"},
}


def check_service(net: Net, service_id: str) -> dict:
    cfg = STATUS_SERVICES.get(service_id)
    if not cfg:
        return {"ok": False, "error": "Unknown service", "latency": 0}
    start = time.monotonic()
    try:
        resp = net.get(cfg["url"], timeout=cfg["timeout"])
        latency = round((time.monotonic() - start) * 1000)
        if resp.status_code != 200:
            return {"ok": False, "error": f"HTTP {resp.status_code}", "latency": latency}
        return {"ok": True, "latency": latency}
    except OfflineError:
        return {"ok": False, "error": "Offline", "latency": round((time.monotonic() - start) * 1000)}
    except httpx.TimeoutException:
        return {"ok": False, "error": "Timeout", "latency": round((time.monotonic() - start) * 1000)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e), "latency": round((time.monotonic() - start) * 1000)}


# ── /api/proxy/<name> ─────────────────────────────────────────────
# name → (upstream URL, allowed query parameters, cache seconds)
PROXIES = {
    "nominatim-reverse": ("https://nominatim.openstreetmap.org/reverse",
                          {"lat", "lon", "format", "zoom", "addressdetails"}, 30 * 86400),
    "om-elevation": ("https://api.open-meteo.com/v1/elevation", {"latitude", "longitude"}, 365 * 86400),
    "om-archive": ("https://archive-api.open-meteo.com/v1/archive",
                   {"latitude", "longitude", "start_date", "end_date", "hourly", "daily",
                    "temperature_unit", "precipitation_unit", "timezone"}, 86400),
    "sunrise-sunset": ("https://api.sunrise-sunset.org/json", {"lat", "lng", "date", "formatted"}, 365 * 86400),
}
MAX_PARAM_LEN = 200


def proxy(net: Net, cache: Cache, name: str, query: dict[str, str]) -> tuple[int, dict]:
    """Returns (status, json). Unknown names / parameters are refused."""
    spec = PROXIES.get(name)
    if not spec:
        return 404, {"error": "Not found"}
    url, allowed, ttl = spec
    extra = set(query) - allowed
    if extra or any(len(v) > MAX_PARAM_LEN for v in query.values()):
        return 400, {"error": "Unsupported parameters: " + ", ".join(sorted(extra)) if extra else "Parameter too long."}
    key = f"proxy:{name}:" + json.dumps(sorted(query.items()))
    hit = cache.get(key)
    if hit is not None:
        return 200, hit
    try:
        resp = net.get(url, query)
    except OfflineError:
        stale = cache.get(key, allow_stale=True)
        if stale is not None:
            return 200, stale
        return 503, {"error": "Offline", "offline": True}
    except Exception as e:  # noqa: BLE001
        log.warning("proxy %s failed: %s", name, e)
        return 502, {"error": "Upstream service unavailable."}
    try:
        data = resp.json()
    except ValueError:
        return 502, {"error": "Upstream service returned an unexpected response."}
    if resp.status_code == 200:
        cache.put(key, data, ttl)
    return resp.status_code, data


# ── /tiles/{z}/{x}/{y}.png ────────────────────────────────────────
TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
TILE_FRESH_SECONDS = 7 * 86400   # OSM tile policy: cache for at least 7 days
TILE_MAX_ZOOM = 19
TILE_PATH_RE = re.compile(r"/tiles/([0-9]{1,2})/([0-9]{1,7})/([0-9]{1,7})\.png", re.ASCII)


def tile(net: Net, tiles_dir: Path, z: int, x: int, y: int) -> tuple[int, bytes | None]:
    if not (0 <= z <= TILE_MAX_ZOOM and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return 404, None
    path = tiles_dir / str(z) / str(x) / f"{y}.png"
    cached = path.read_bytes() if path.exists() else None
    if cached is not None and time.time() - path.stat().st_mtime < TILE_FRESH_SECONDS:
        return 200, cached
    try:
        resp = net.get(TILE_URL.format(z=z, x=x, y=y))
    except Exception as e:  # noqa: BLE001 — offline or OSM unreachable: fall back to any cached copy
        if cached is not None:
            return 200, cached
        log.info("tile %s/%s/%s unavailable: %s", z, x, y, e)
        return 503, None
    if resp.status_code != 200 or not resp.content.startswith(b"\x89PNG"):
        return (200, cached) if cached is not None else (502, None)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(resp.content)
    os.replace(tmp, path)
    return 200, resp.content
