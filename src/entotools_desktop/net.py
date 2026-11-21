"""Outbound HTTP: one shared client, an identifying User-Agent, Nominatim's
1-request-per-second rule, and "offline" vs "service down" detection.

When a request can't connect, we check whether the internet is reachable at
all. If it isn't, OfflineError is raised immediately, without the retries and
back-off meant for a flaky service, so the UI can say "you're offline" within
seconds instead of after a long wait.
"""
from __future__ import annotations

import socket
import threading
import time

import httpx

from . import __version__

USER_AGENT = f"EntoTools-Desktop/{__version__} (+https://github.com/o-mettam/Entotools-Desktop)"
NOMINATIM_HOST = "nominatim.openstreetmap.org"
NOMINATIM_MIN_INTERVAL = 1.0  # seconds; OSM Nominatim usage policy

# Hosts tried when deciding "is the internet reachable?" (TCP connect only).
PROBE_HOSTS = (("1.1.1.1", 443), ("8.8.8.8", 443), ("api.open-meteo.com", 443))
PROBE_TIMEOUT = 2.0
PROBE_CACHE_SECONDS = 10.0


class OfflineError(Exception):
    """The computer has no working internet connection."""


class Net:
    def __init__(self, user_agent: str = USER_AGENT, transport: httpx.BaseTransport | None = None,
                 sleep=time.sleep, probe=None):
        self.client = httpx.Client(
            headers={"User-Agent": user_agent},
            timeout=httpx.Timeout(30.0, connect=8.0),
            follow_redirects=True,
            transport=transport,
        )
        self.sleep = sleep
        self._probe = probe or _tcp_probe
        self._online_cache: tuple[float, bool] | None = None
        self._nominatim_lock = threading.Lock()
        self._nominatim_last = 0.0

    # ── connectivity ─────────────────────────────────────────────
    def internet_reachable(self, force: bool = False) -> bool:
        now = time.monotonic()
        if not force and self._online_cache and now - self._online_cache[0] < PROBE_CACHE_SECONDS:
            return self._online_cache[1]
        ok = self._probe()
        self._online_cache = (now, ok)
        return ok

    # ── requests ─────────────────────────────────────────────────
    def get(self, url: str, params: dict | None = None, timeout: float | None = None) -> httpx.Response:
        if NOMINATIM_HOST in url:
            self._throttle_nominatim()
        try:
            kwargs = {"params": params}
            if timeout is not None:
                kwargs["timeout"] = timeout
            return self.client.get(url, **kwargs)
        except (httpx.ConnectError, httpx.ConnectTimeout) as err:
            if not self.internet_reachable(force=True):
                raise OfflineError(str(err)) from err
            raise

    def _throttle_nominatim(self) -> None:
        with self._nominatim_lock:
            wait = self._nominatim_last + NOMINATIM_MIN_INTERVAL - time.monotonic()
            if wait > 0:
                time.sleep(wait)
            self._nominatim_last = time.monotonic()

    def close(self) -> None:
        self.client.close()


def _tcp_probe() -> bool:
    for host, port in PROBE_HOSTS:
        try:
            with socket.create_connection((host, port), timeout=PROBE_TIMEOUT):
                return True
        except OSError:
            continue
    return False
