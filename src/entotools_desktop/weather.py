"""Weather search and season normals: a port of the web Worker
(EntoTools-Production/src/index.js at f948578, handleSearch / handleNormals).

Behaviour matches the Worker except where noted "DESKTOP:":
  - "today" is the computer's local date, not UTC (finding F1)
  - impossible calendar dates (2025-02-30) are rejected; JS silently rolled
    them over to the next month
  - no network → a clear "offline" answer (503, offline: true)
Every function returns (http_status, json_body) so the HTTP layer stays thin.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import math
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from importlib import resources

from .cache import Cache
from .jscompat import js_falsy, js_parse_float, js_str, round_to, utf16_len, utf16_slice
from .net import Net, OfflineError

log = logging.getLogger(__name__)

NCEI_BASE_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"

MAX_RETRIES = 3
RETRYABLE = {429, 500, 502, 503, 504}

MAX_DATE_RANGES = 10
MAX_RANGE_DAYS = 366 * 5
MAX_TOTAL_DAYS = 366 * 10
MAX_PLACE_LEN = 100
MAX_LABEL_LEN = 60
GEOCODE_TTL = 86400

ISO_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")  # used with fullmatch (JS /^\d{4}-\d{2}-\d{2}$/)
STATION_ID_RE = re.compile(r"(?:GHCND:)?([A-Za-z0-9]{11})", re.IGNORECASE | re.ASCII)
TEMP_LIKELY_RE = re.compile(r"^(USW|USC|USR)")
NEARBY_STATIONS_MAX = 6

COUNTRY_PROVIDER_MAP = {"us": "ncei"}
DEFAULT_PROVIDER = "open-meteo"

NORMALS_FIRST_YEAR = 1991
NORMALS_LAST_YEAR = 2020
NORMALS_MIN_COMPLETE_YEARS = 20
NORMALS_YEAR_COMPLETENESS = 0.9
PREV_YEAR_CACHE_TTL = 30 * 86400
GRID_NORMALS_CACHE_TTL = 90 * 86400

OFFLINE_MESSAGE = ("You appear to be offline. Weather lookups need an internet connection — "
                   "your collection, labels, CSV backups and PDF printing still work offline.")


def offline_response():
    return 503, {"error": OFFLINE_MESSAGE, "offline": True,
                 "service_error": {"transient": True, "service": "internet connection"}}


class UpstreamError(Exception):
    pass


# ── small helpers ──────────────────────────────────────────────────
def to_rad(deg: float) -> float:
    return deg * math.pi / 180


def haversine(lat1, lon1, lat2, lon2) -> float:
    d_lat = to_rad(lat2 - lat1)
    d_lon = to_rad(lon2 - lon1)
    a = math.sin(d_lat / 2) ** 2 + math.cos(to_rad(lat1)) * math.cos(to_rad(lat2)) * math.sin(d_lon / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(a))  # miles


def _get(record: dict, key: str):
    """Case-insensitive field access for NCEI records."""
    for k in (key, key.lower(), key.upper()):
        v = record.get(k)
        if v is not None:
            return v
    return None


def _num(v) -> float | None:
    """parseFloat on an NCEI value that is known to be present."""
    f = js_parse_float(v)
    return None if math.isnan(f) else f


def daterange(start: str, end: str):
    cur = dt.date.fromisoformat(start)
    stop = dt.date.fromisoformat(end)
    while cur <= stop:
        yield cur.isoformat()
        cur += dt.timedelta(days=1)


def calculate_precip_accumulation(records: list[dict]) -> list[dict]:
    accum = 0.0
    out = []
    for rec in records:
        accum += rec.get("PRCP") or 0
        out.append({**rec, "PRCP_ACCUM": round_to(accum, 2)})
    return out


def celsius_to_f(c: float) -> float:
    return round_to(c * 9 / 5 + 32, 1)


def mm_to_in(mm: float) -> float:
    return round_to(mm / 25.4, 2)


# ── stations ───────────────────────────────────────────────────────
class Stations:
    def __init__(self, stations: list[dict] | None = None):
        self._list = stations
        self._by_id = None

    @property
    def all(self) -> list[dict]:
        if self._list is None:
            with resources.files(__package__).joinpath("data/stations.json").open("rb") as f:
                self._list = json.load(f)
        return self._list

    def by_id(self, station_id: str) -> dict | None:
        if self._by_id is None:
            self._by_id = {s["id"].upper(): s for s in self.all}
        return self._by_id.get(station_id.upper())


def normalize_station_id(raw) -> str | None:
    if not isinstance(raw, str):
        return None
    m = STATION_ID_RE.fullmatch(raw.strip())
    return m.group(1) if m else None


def station_result(s: dict, lat: float, lon: float, selection: str) -> dict:
    return {
        "station_id": s["id"],
        "station_name": s["name"],
        "station_lat": s["lat"],
        "station_lon": s["lon"],
        "distance_miles": round_to(haversine(lat, lon, s["lat"], s["lon"]), 1),
        "selection": selection,
    }


# ── the service ────────────────────────────────────────────────────
class WeatherService:
    def __init__(self, net: Net, cache: Cache, stations: Stations | None = None, today=None):
        self.net = net
        self.cache = cache
        self.stations = stations or Stations()
        self._today = today or dt.date.today  # DESKTOP: local date (F1)
        self.pool = ThreadPoolExecutor(max_workers=8, thread_name_prefix="weather")

    def today(self) -> str:
        return self._today().isoformat()

    # ── upstream calls ───────────────────────────────────────────
    def _retrying_get(self, url, params, label: str, final_status_raises: bool):
        """nceiFetch (final_status_raises=False) / fetchWithRetry (True)."""
        last_err = None
        for attempt in range(MAX_RETRIES):
            try:
                resp = self.net.get(url, params)
                if resp.status_code in RETRYABLE:
                    if attempt < MAX_RETRIES - 1:
                        self.net.sleep(2 ** attempt)
                        continue
                    if final_status_raises:
                        raise UpstreamError(f"{label} returned {resp.status_code} after {MAX_RETRIES} attempts")
                return resp
            except OfflineError:
                raise
            except Exception as err:  # noqa: BLE001 — mirrors the Worker's catch-all retry
                last_err = err
                if attempt < MAX_RETRIES - 1:
                    self.net.sleep(2 ** attempt)
        raise last_err or UpstreamError(f"{label} failed after {MAX_RETRIES} retries")

    def nominatim_get(self, params: dict):
        key = "nominatim:" + json.dumps(sorted(params.items()))
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        try:
            resp = self.net.get(NOMINATIM_URL, params)
        except OfflineError:
            stale = self.cache.get(key, allow_stale=True)
            if stale is not None:
                return stale
            raise
        if resp.status_code != 200:
            raise UpstreamError(f"Nominatim returned {resp.status_code}")
        data = resp.json()
        self.cache.put(key, data, GEOCODE_TTL)
        return data

    def geocode_city_state(self, city, state, country):
        params = {"city": city, "state": state, "format": "json", "limit": "1", "addressdetails": "1"}
        if country:
            params["country"] = country
        data = self.nominatim_get(params)
        if data:
            first = data[0]
            cc = (first.get("address") or {}).get("country_code") or None
            return {
                "lat": js_parse_float(first.get("lat")),
                "lon": js_parse_float(first.get("lon")),
                "label": first.get("display_name") or "",
                "country_code": cc.lower() if cc else None,
            }
        return None

    def reverse_geocode(self, lat, lon):
        key = "reverse:" + json.dumps([lat, lon])
        cached = self.cache.get(key)
        if cached is not None:
            return cached
        resp = self.net.get(NOMINATIM_REVERSE_URL, {"lat": js_str(lat), "lon": js_str(lon), "format": "json", "addressdetails": "1"})
        if resp.status_code != 200:
            return {"country_code": None}
        data = resp.json()
        cc = (data.get("address") or {}).get("country_code") or None
        result = {"country_code": cc.lower() if cc else None}
        self.cache.put(key, result, GEOCODE_TTL)
        return result

    def find_nearest_station(self, lat, lon, max_candidates=50):
        stations = self.stations.all
        cos_lat = max(math.cos(to_rad(lat)), 0.1)
        nearby: list[dict] = []
        margin = 2.0
        while margin <= 16.0:
            lat_m, lon_m = margin, margin / cos_lat
            nearby = [s for s in stations if abs(s["lat"] - lat) <= lat_m and abs(s["lon"] - lon) <= lon_m]
            if len(nearby) >= max_candidates:
                break
            margin *= 2
        if not nearby:
            nearby = stations
        ranked = sorted(({"dist": haversine(lat, lon, s["lat"], s["lon"]), "station": s} for s in nearby),
                        key=lambda r: r["dist"])
        likely = [r for r in ranked if TEMP_LIKELY_RE.match(r["station"]["id"])]
        unlikely = [r for r in ranked if not TEMP_LIKELY_RE.match(r["station"]["id"])]
        candidates = (likely + unlikely)[:max_candidates]

        today = self._today()
        params = {
            "dataset": "daily-summaries", "dataTypes": "TMIN,TMAX,PRCP",
            "stations": ",".join(c["station"]["id"] for c in candidates),
            "startDate": (today - dt.timedelta(days=30)).isoformat(), "endDate": today.isoformat(),
            "format": "json", "units": "standard",
        }
        resp = self._retrying_get(NCEI_BASE_URL, params, "NCEI", final_status_raises=False)
        if resp.status_code != 200:
            return None, []
        data = resp.json()
        if not data:
            return None, []

        def has(rec, k):
            v = _get(rec, k)
            return v is not None and v != ""

        ids_with_temps = {_get(rec, "station") for rec in data if _get(rec, "station") and (has(rec, "TMIN") or has(rec, "TMAX"))}
        with_temps = [station_result(c["station"], lat, lon, "auto")
                      for c in sorted((c for c in candidates if c["station"]["id"] in ids_with_temps), key=lambda c: c["dist"])][:NEARBY_STATIONS_MAX]
        for c in candidates:
            if c["station"]["id"] in ids_with_temps:
                return station_result(c["station"], lat, lon, "auto"), with_temps
        return None, with_temps

    def ncei_daily(self, station_id, start, end):
        params = {
            "dataset": "daily-summaries", "dataTypes": "TMIN,TMAX,PRCP", "stations": station_id,
            "startDate": start, "endDate": end, "format": "json",
            "includeStationName": "true", "includeStationLocation": "true", "units": "standard",
        }
        resp = self._retrying_get(NCEI_BASE_URL, params, "NCEI", final_status_raises=False)
        if resp.status_code != 200:
            raise UpstreamError(f"NCEI returned {resp.status_code}")
        by_date: dict[str, dict] = {}
        for rec in resp.json():
            d = str(_get(rec, "date") or "")[:10]
            if not d:
                continue
            row = by_date.setdefault(d, {"date": d, "TMIN": None, "TMAX": None, "PRCP": None})
            tmin, tmax, prcp = _get(rec, "TMIN"), _get(rec, "TMAX"), _get(rec, "PRCP")
            if tmin is not None and tmin != "" and _num(tmin) is not None:
                row["TMIN"] = round_to(_num(tmin), 1)
            if tmax is not None and tmax != "" and _num(tmax) is not None:
                row["TMAX"] = round_to(_num(tmax), 1)
            if prcp is not None and prcp != "" and _num(prcp) is not None:
                row["PRCP"] = round_to(_num(prcp), 2)
        return [by_date.get(d) or {"date": d, "TMIN": None, "TMAX": None, "PRCP": None} for d in daterange(start, end)]

    def open_meteo_archive(self, lat, lon, start, end):
        params = {
            "latitude": js_str(lat), "longitude": js_str(lon), "start_date": start, "end_date": end,
            "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum", "timezone": "UTC",
        }
        resp = self._retrying_get(OPEN_METEO_ARCHIVE_URL, params, "Open-Meteo Archive", final_status_raises=True)
        if resp.status_code != 200:
            raise UpstreamError(f"Open-Meteo returned {resp.status_code}")
        daily = resp.json().get("daily") or {}
        dates = daily.get("time") or []
        tmins = daily.get("temperature_2m_min") or []
        tmaxs = daily.get("temperature_2m_max") or []
        prcps = daily.get("precipitation_sum") or []
        pick = lambda arr, i: arr[i] if i < len(arr) else None  # noqa: E731
        by_date = {}
        for i, d in enumerate(dates):
            tmin, tmax, prcp = pick(tmins, i), pick(tmaxs, i), pick(prcps, i)
            by_date[d] = {
                "date": d,
                "TMIN": celsius_to_f(tmin) if tmin is not None else None,
                "TMAX": celsius_to_f(tmax) if tmax is not None else None,
                "PRCP": mm_to_in(prcp) if prcp is not None else None,
            }
        return [by_date.get(d) or {"date": d, "TMIN": None, "TMAX": None, "PRCP": None} for d in daterange(start, end)]

    def open_meteo_forecast(self, lat, lon):
        params = {
            "latitude": js_str(lat), "longitude": js_str(lon),
            "daily": "temperature_2m_min,temperature_2m_max,precipitation_sum",
            "temperature_unit": "fahrenheit", "precipitation_unit": "inch",
            "forecast_days": "16", "past_days": "5", "timezone": "UTC",
        }
        resp = self._retrying_get(OPEN_METEO_FORECAST_URL, params, "Open-Meteo Forecast", final_status_raises=True)
        if resp.status_code != 200:
            raise UpstreamError(f"Open-Meteo Forecast returned {resp.status_code}")
        daily = resp.json().get("daily") or {}
        dates = daily.get("time") or []
        tmins = daily.get("temperature_2m_min") or []
        tmaxs = daily.get("temperature_2m_max") or []
        precs = daily.get("precipitation_sum") or []
        out = []
        for i, d in enumerate(dates):
            tmin = tmins[i] if i < len(tmins) else None
            tmax = tmaxs[i] if i < len(tmaxs) else None
            if tmin is not None and tmax is not None:
                p = precs[i] if i < len(precs) else None
                out.append({"date": d, "TMIN": round_to(tmin, 1), "TMAX": round_to(tmax, 1),
                            "PRCP": round_to(p, 2) if p is not None else 0, "is_forecast": True})
        return out

    # ── /api/search ──────────────────────────────────────────────
    def search(self, body) -> tuple[int, dict]:
        try:
            return self._search(body)
        except OfflineError:
            return offline_response()
        except Exception:  # noqa: BLE001
            log.exception("search: unexpected error")
            return 500, {"error": "An unexpected server error occurred. Please try again."}

    def _search(self, body) -> tuple[int, dict]:
        if not isinstance(body, dict):
            return 400, {"error": "Invalid request body — expected JSON."}
        err = lambda msg: (400, {"error": msg})  # noqa: E731

        # Step 0 — validate date ranges before any upstream call.
        raw_ranges = body.get("dateRanges")
        has_ranges = not js_falsy(raw_ranges) and (
            (isinstance(raw_ranges, (list, str)) and len(raw_ranges) > 0))
        if not has_ranges:
            raw_ranges = [{"startDate": body.get("startDate"), "endDate": body.get("endDate"), "label": "Range 1"}]
        if not isinstance(raw_ranges, list):
            return err("Invalid date ranges.")
        if len(raw_ranges) > MAX_DATE_RANGES:
            return err(f"Too many date ranges (max {MAX_DATE_RANGES}).")

        ranges = []
        total_days = 0
        for dr in raw_ranges:
            if dr is None or not isinstance(dr, (dict, list)):
                return err("Invalid date ranges.")
            dr = dr if isinstance(dr, dict) else {}
            label = utf16_slice(dr["label"], MAX_LABEL_LEN) if isinstance(dr.get("label"), str) else ""
            name = label or "a range"
            sd, ed = dr.get("startDate"), dr.get("endDate")
            if js_falsy(sd) or js_falsy(ed):
                return err(f"Missing start or end date for '{name}'.")
            if not (isinstance(sd, str) and isinstance(ed, str) and ISO_DATE_RE.fullmatch(sd) and ISO_DATE_RE.fullmatch(ed)):
                return err(f"Invalid date format for '{name}'.")
            try:  # DESKTOP: impossible dates are rejected rather than rolled over
                sd_date, ed_date = dt.date.fromisoformat(sd), dt.date.fromisoformat(ed)
            except ValueError:
                return err(f"Invalid date format for '{name}'.")
            if ed_date < sd_date:
                return err(f"End date is before start date for '{name}'.")
            span = (ed_date - sd_date).days + 1
            if span > MAX_RANGE_DAYS:
                return err(f"Date range '{name}' is too large (max {MAX_RANGE_DAYS} days).")
            total_days += span
            ranges.append({"label": label, "startDate": sd, "endDate": ed})
        if total_days > MAX_TOTAL_DAYS:
            return err(f"Combined date ranges are too large (max {MAX_TOTAL_DAYS} days total).")

        # Optional manual NCEI station (always available on desktop — D3).
        manual = None
        if body.get("station_id") is not None and body.get("station_id") != "":
            sid = normalize_station_id(body.get("station_id"))
            if not sid:
                return err("NCEI station IDs are 11 letters and digits, for example USW00013891.")
            manual = self.stations.by_id(sid)
            if not manual:
                return err(f"Station {sid} isn't in the NCEI station list. Check the ID, or clear the field to use the nearest station.")

        # Step 1 — location + country.
        mode = body.get("mode")
        country_code = None
        try:
            if mode == "city":
                text = lambda v: v.strip() if isinstance(v, str) else ""  # noqa: E731
                city, state, country = text(body.get("city")), text(body.get("state")), text(body.get("country"))
                if not city or not state:
                    return err("Please enter both city and state/province.")
                if max(utf16_len(city), utf16_len(state), utf16_len(country)) > MAX_PLACE_LEN:
                    return err(f"City, state and country must each be {MAX_PLACE_LEN} characters or fewer.")
                geo = self.geocode_city_state(city, state, country)
                if not geo:
                    return 404, {"error": "Could not resolve that location."}
                lat, lon, location_label, country_code = geo["lat"], geo["lon"], geo["label"], geo["country_code"]
            elif mode == "latlon":
                lat, lon = js_parse_float(body.get("lat")), js_parse_float(body.get("lon"))
                if math.isnan(lat) or math.isnan(lon):
                    return err("Invalid latitude / longitude values.")
                if lat < -90 or lat > 90 or lon < -180 or lon > 180:
                    return err("Latitude must be between -90 and 90, and longitude between -180 and 180.")
                location_label = f"{js_str(lat)}, {js_str(lon)}"
                try:
                    country_code = self.reverse_geocode(lat, lon)["country_code"]
                except OfflineError:
                    raise
                except Exception as e:  # noqa: BLE001
                    log.warning("reverse geocode failed — defaulting provider: %s", e)
            else:
                return err("Invalid search mode.")
        except OfflineError:
            raise
        except Exception as e:  # noqa: BLE001
            log.error("geocoding failed: %s", e)
            return 500, {"error": "Could not resolve that location. Please try again."}

        provider = COUNTRY_PROVIDER_MAP.get(country_code.lower(), DEFAULT_PROVIDER) if country_code else DEFAULT_PROVIDER
        is_fallback = bool(country_code) and country_code.lower() not in COUNTRY_PROVIDER_MAP
        provider_fallback = False
        fallback_reason = ""

        if manual and provider != "ncei":
            return err("A specific NCEI station can only be used for locations in the United States. Clear the station ID to search this location.")

        # Step 2 — data source.
        def om_station():
            return {"station_id": f"OM:{lat:.4f},{lon:.4f}", "station_name": "Open-Meteo Grid Point",
                    "station_lat": lat, "station_lon": lon, "distance_miles": 0}

        station = None
        nearby: list[dict] = []
        recommended = None
        nearby_future = None
        if manual:
            station = station_result(manual, lat, lon, "manual")

            def nearby_lookup():
                try:
                    return self.find_nearest_station(lat, lon)
                except Exception as e:  # noqa: BLE001
                    log.warning("nearby station lookup failed (manual station in use): %s", e)
                    return None, []
            nearby_future = self.pool.submit(nearby_lookup)
        elif provider == "ncei":
            try:
                station, nearby = self.find_nearest_station(lat, lon)
                recommended = station["station_id"] if station else None
            except OfflineError:
                raise
            except Exception as e:  # noqa: BLE001
                provider, provider_fallback = "open-meteo", True
                fallback_reason = f"NCEI station lookup failed ({e}). Using Open-Meteo as a fallback data source."
                station = om_station()
            if not station:
                provider, provider_fallback = "open-meteo", True
                fallback_reason = ("No NCEI weather stations with recent temperature data were found near this "
                                   "location. Using Open-Meteo as a fallback data source.")
                station = om_station()
        else:
            station = om_station()

        # Step 3 — forecast once, then every range in parallel.
        forecast_unavailable = False
        try:
            forecast_days = self.open_meteo_forecast(lat, lon)
        except Exception as e:  # noqa: BLE001 — includes offline; the data fetch reports that
            log.warning("forecast fetch failed — forecast will be skipped: %s", e)
            forecast_days, forecast_unavailable = [], True
        today = self.today()
        horizon_end = max((f["date"] for f in forecast_days), default=today)

        state = {"fallback": provider_fallback, "reason": fallback_reason, "observed": 0, "service_errors": []}
        state_lock = threading.Lock()

        def fetch_range(r):
            sd, ed, label = r["startDate"], r["endDate"], r["label"]
            if provider == "ncei":
                try:
                    temps = self.ncei_daily(station["station_id"], sd, ed)
                    observed = sum(1 for t in temps if t["TMIN"] is not None or t["TMAX"] is not None)
                    with state_lock:
                        state["observed"] += observed
                except OfflineError:
                    raise
                except Exception as ncei_err:  # noqa: BLE001
                    try:
                        temps = self.open_meteo_archive(lat, lon, sd, ed)
                    except OfflineError:
                        raise
                    except Exception as om_err:  # noqa: BLE001
                        state["service_errors"].append({"service": "Open-Meteo", "error": str(om_err)})
                        raise UpstreamError(f"Both NCEI and Open-Meteo are unavailable: {ncei_err} / {om_err}") from om_err
                    with state_lock:
                        if not state["fallback"]:
                            state["fallback"] = True
                            state["reason"] = (f"NCEI data request failed ({ncei_err}). Some or all date ranges used "
                                               "Open-Meteo as a fallback data source.")
            else:
                try:
                    temps = self.open_meteo_archive(lat, lon, sd, ed)
                except OfflineError:
                    raise
                except Exception as om_err:  # noqa: BLE001
                    state["service_errors"].append({"service": "Open-Meteo", "error": str(om_err)})
                    raise

            last_actual = next((t["date"] for t in reversed(temps) if t["TMIN"] is not None and t["TMAX"] is not None), None)
            cutoff = horizon_end if ed >= today else ed
            forecast = [f for f in forecast_days
                        if f["date"] <= cutoff and (f["date"] >= sd if last_actual is None else f["date"] > last_actual)]
            by_date = {f["date"]: f for f in forecast}
            temp_dates = {t["date"] for t in temps}
            merged = [by_date.get(t["date"], t) for t in temps]
            extra = sorted((f for f in forecast if f["date"] not in temp_dates), key=lambda f: f["date"])
            combined = merged + extra
            return {"label": label, "startDate": sd,
                    "endDate": combined[-1]["date"] if combined else ed,
                    "temperatures": calculate_precip_accumulation(combined)}

        futures = [self.pool.submit(fetch_range, r) for r in ranges]
        results, first_error = [], None
        for fut in futures:
            try:
                results.append(fut.result())
            except Exception as e:  # noqa: BLE001
                first_error = first_error or e
        if first_error is not None:
            if nearby_future:
                nearby_future.cancel()
            if isinstance(first_error, OfflineError):
                raise first_error
            message = str(first_error)
            transient = bool(re.search(r"502|503|504|after \d+ attempts", message))
            service = state["service_errors"][0]["service"] if state["service_errors"] else "the weather data provider"
            user_message = (f"{service} is currently experiencing an outage and is not responding. Please try again in a few minutes."
                            if transient else "Failed to retrieve weather data. Please try again later.")
            return 503, {"error": user_message, "service_error": {"transient": transient, "service": service}}

        provider_fallback, fallback_reason = state["fallback"], state["reason"]
        if manual and not provider_fallback and state["observed"] == 0 and any(r["startDate"] <= today for r in ranges):
            return 422, {"error": f"Station {station['station_id']} ({station['station_name']}) has no temperature readings for the selected dates. Choose another station, or clear the station ID to use the nearest one."}
        if nearby_future:
            auto_station, nearby = nearby_future.result()
            recommended = auto_station["station_id"] if auto_station else None

        return 200, {
            "location": location_label,
            "search_lat": lat,
            "search_lon": lon,
            "country_code": country_code,
            "provider": provider,
            "is_fallback": is_fallback,
            "provider_fallback": provider_fallback,
            "fallback_reason": fallback_reason,
            "forecast_unavailable": forecast_unavailable,
            "station": station,
            "nearby_stations": nearby if provider == "ncei" else [],
            "recommended_station_id": recommended if provider == "ncei" else None,
            "ranges": results,
        }

    # ── /api/normals ─────────────────────────────────────────────
    def normals(self, body) -> tuple[int, dict]:
        try:
            return self._normals(body)
        except OfflineError:
            return offline_response()
        except Exception:  # noqa: BLE001
            log.exception("normals: unexpected error")
            return 503, {"error": "Could not load historical data. Please try again later."}

    def _cached(self, key, ttl, produce):
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        try:
            value = produce()
        except OfflineError:
            stale = self.cache.get(key, allow_stale=True)
            if stale is not None:
                return stale
            raise
        self.cache.put(key, value, ttl)
        return value

    def _fetch_years(self, source, station_id, lat, lon, first, last):
        chunks = [(y, min(y + 9, last)) for y in range(first, last + 1, 10)]
        if source == "ncei":
            futs = [self.pool.submit(self.ncei_daily, station_id, f"{a}-01-01", f"{b}-12-31") for a, b in chunks]
        else:
            futs = [self.pool.submit(self.open_meteo_archive, lat, lon, f"{a}-01-01", f"{b}-12-31") for a, b in chunks]
        years: dict[str, list] = {}
        for f in futs:
            for r in f.result():
                years.setdefault(r["date"][:4], []).append([r["TMIN"], r["TMAX"]])
        return years

    @staticmethod
    def _complete_years(years: dict) -> list[str]:
        return [y for y, days in years.items()
                if sum(1 for lo, hi in days if lo is not None and hi is not None) >= NORMALS_YEAR_COMPLETENESS * len(days)]

    def _normals(self, body) -> tuple[int, dict]:
        if not isinstance(body, dict):
            return 400, {"error": "Invalid request body."}
        lat = round_to(js_parse_float(body.get("lat")), 2)
        lon = round_to(js_parse_float(body.get("lon")), 2)
        if math.isnan(lat) or math.isnan(lon) or lat < -90 or lat > 90 or lon < -180 or lon > 180:
            return 400, {"error": "Invalid latitude / longitude values."}
        station_id = None
        sid = body.get("station_id")
        if body.get("provider") == "ncei" and isinstance(sid, str) and re.fullmatch(r"[A-Za-z0-9]{11}", sid):
            known = self.stations.by_id(sid)
            station_id = known["id"] if known else None
        grid_key = f"{lat:.2f},{lon:.2f}"
        prev_year = self._today().year - 1  # DESKTOP: local year

        normals = None
        if station_id:
            try:
                normals = self._cached(f"normals:v1:ncei:{station_id}", 0, lambda: {
                    "source": "ncei",
                    "years": self._fetch_years("ncei", station_id, lat, lon, NORMALS_FIRST_YEAR, NORMALS_LAST_YEAR)})
                if len(self._complete_years(normals["years"])) < NORMALS_MIN_COMPLETE_YEARS:
                    normals = None
            except OfflineError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("NCEI normals failed — using grid: %s", e)
                normals = None
        if not normals:
            normals = self._cached(f"normals:v1:om:{grid_key}", GRID_NORMALS_CACHE_TTL, lambda: {
                "source": "open-meteo",
                "years": self._fetch_years("open-meteo", None, lat, lon, NORMALS_FIRST_YEAR, NORMALS_LAST_YEAR)})
        used = self._complete_years(normals["years"])

        previous = None
        try:
            ident = f"ncei:{station_id}" if normals["source"] == "ncei" else f"om:{grid_key}"
            previous = self._cached(f"prevyear:v1:{ident}:{prev_year}", PREV_YEAR_CACHE_TTL, lambda: {
                "year": prev_year,
                "days": self._fetch_years(normals["source"], station_id, lat, lon, prev_year, prev_year).get(str(prev_year), [])})
        except Exception as e:  # noqa: BLE001 — previous year is optional, offline included
            log.warning("previous year fetch failed: %s", e)

        return 200, {
            "source": normals["source"],
            "period": [NORMALS_FIRST_YEAR, NORMALS_LAST_YEAR],
            "years_used": len(used),
            "years": {y: normals["years"][y] for y in used},
            "previous_year": previous,
        }
