"""Capture reference outputs from the EntoTools web Worker (Phase 0, step 3).

These are the "golden" answers the Python backend must reproduce in Phase 1.

Usage:
    .venv/bin/python tools/capture_reference.py --base http://localhost:8788
    .venv/bin/python tools/capture_reference.py --base https://entotools.org --only search --verify

--base       Worker to query. Normals need the season-normals flag, which is only
             on for anonymous visitors in a local `wrangler pages dev` run with
             every flag set to 'ga' (see PROJECT_LOG.md, session 1).
--verify     Don't write files; compare the target's answers with the saved
             "exact" cases instead (used to prove local == production).

Each saved case is JSON: {name, kind, compare, request, status, response,
captured_at, source}. compare is "exact" (historical dates: must match) or
"shape" (reaches today/the future: forecast data changes daily, so only the
structure is compared).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "tests" / "reference"
TODAY = dt.date.today().isoformat()


def rng(start, end, label="Range 1"):
    return {"startDate": start, "endDate": end, "label": label}


# name -> (compare, body)
SEARCH_CASES: dict[str, tuple[str, dict]] = {
    # ── Successful lookups, historical (deterministic) ──
    "us_city_raleigh_2025_season": ("exact", {"mode": "city", "city": "Raleigh", "state": "North Carolina", "country": "", "dateRanges": [rng("2025-03-01", "2025-10-31")]}),
    "us_city_ithaca_two_seasons": ("exact", {"mode": "city", "city": "Ithaca", "state": "New York", "country": "", "dateRanges": [rng("2024-04-01", "2024-09-30", "2024"), rng("2025-04-01", "2025-09-30", "2025")]}),
    "us_latlon_dc_full_year": ("exact", {"mode": "latlon", "lat": "38.9072", "lon": "-77.0369", "dateRanges": [rng("2025-01-01", "2025-12-31")]}),
    "us_latlon_fairbanks_summer": ("exact", {"mode": "latlon", "lat": "64.8378", "lon": "-147.7164", "dateRanges": [rng("2025-06-01", "2025-08-31")]}),
    "us_latlon_three_ranges": ("exact", {"mode": "latlon", "lat": "40.4237", "lon": "-86.9212", "dateRanges": [rng("2023-05-01", "2023-08-31", "2023"), rng("2024-05-01", "2024-08-31", "2024"), rng("2025-05-01", "2025-08-31", "2025")]}),
    "nonus_latlon_london": ("exact", {"mode": "latlon", "lat": "51.5074", "lon": "-0.1278", "dateRanges": [rng("2025-04-01", "2025-09-30")]}),
    "nonus_city_toronto": ("exact", {"mode": "city", "city": "Toronto", "state": "Ontario", "country": "Canada", "dateRanges": [rng("2025-05-01", "2025-08-31")]}),
    "nonus_latlon_sydney": ("exact", {"mode": "latlon", "lat": "-33.8688", "lon": "151.2093", "dateRanges": [rng("2025-07-01", "2025-12-31")]}),
    "manual_station_raleigh": ("exact", {"mode": "city", "city": "Raleigh", "state": "North Carolina", "country": "", "station_id": "USW00013722", "dateRanges": [rng("2025-03-01", "2025-06-30")]}),
    "manual_station_ghcnd_prefix_lowercase": ("exact", {"mode": "latlon", "lat": "35.7796", "lon": "-78.6382", "station_id": "ghcnd:usw00013722", "dateRanges": [rng("2025-03-01", "2025-03-31")]}),
    "legacy_single_range_fields": ("exact", {"mode": "latlon", "lat": "38.9072", "lon": "-77.0369", "startDate": "2025-06-01", "endDate": "2025-06-30"}),
    # ── Reaching today / the future (forecast merge; structure only) ──
    "to_today_raleigh": ("shape", {"mode": "city", "city": "Raleigh", "state": "North Carolina", "country": "", "dateRanges": [rng("2026-03-01", TODAY)]}),
    "wholly_future_range": ("shape", {"mode": "latlon", "lat": "38.9072", "lon": "-77.0369", "dateRanges": [rng((dt.date.today() + dt.timedelta(days=3)).isoformat(), (dt.date.today() + dt.timedelta(days=10)).isoformat())]}),
    "nonus_to_today_london": ("shape", {"mode": "latlon", "lat": "51.5074", "lon": "-0.1278", "dateRanges": [rng("2026-09-01", TODAY)]}),
    # ── Validation errors (no upstream calls; deterministic) ──
    "err_bad_date_format": ("exact", {"mode": "latlon", "lat": "38.9", "lon": "-77.0", "dateRanges": [rng("06/01/2025", "2025-06-30")]}),
    "err_end_before_start": ("exact", {"mode": "latlon", "lat": "38.9", "lon": "-77.0", "dateRanges": [rng("2025-06-30", "2025-06-01")]}),
    "err_too_many_ranges": ("exact", {"mode": "latlon", "lat": "38.9", "lon": "-77.0", "dateRanges": [rng("2025-06-01", "2025-06-02", f"R{i}") for i in range(11)]}),
    "err_range_too_long": ("exact", {"mode": "latlon", "lat": "38.9", "lon": "-77.0", "dateRanges": [rng("2015-01-01", "2025-01-01")]}),
    "err_total_days_too_large": ("exact", {"mode": "latlon", "lat": "38.9", "lon": "-77.0", "dateRanges": [rng("2014-01-01", "2018-12-31", "A"), rng("2019-01-01", "2023-12-31", "B"), rng("2024-01-01", "2025-06-30", "C")]}),
    "err_missing_state": ("exact", {"mode": "city", "city": "Raleigh", "state": "", "dateRanges": [rng("2025-06-01", "2025-06-30")]}),
    "err_place_too_long": ("exact", {"mode": "city", "city": "x" * 101, "state": "NC", "dateRanges": [rng("2025-06-01", "2025-06-30")]}),
    "err_bad_latlon": ("exact", {"mode": "latlon", "lat": "95", "lon": "-77.0", "dateRanges": [rng("2025-06-01", "2025-06-30")]}),
    "err_bad_mode": ("exact", {"mode": "zip", "dateRanges": [rng("2025-06-01", "2025-06-30")]}),
    "err_station_id_format": ("exact", {"mode": "latlon", "lat": "38.9", "lon": "-77.0", "station_id": "ABC", "dateRanges": [rng("2025-06-01", "2025-06-30")]}),
    "err_station_not_found": ("exact", {"mode": "latlon", "lat": "38.9", "lon": "-77.0", "station_id": "USW99999999", "dateRanges": [rng("2025-06-01", "2025-06-30")]}),
    "err_manual_station_outside_us": ("exact", {"mode": "latlon", "lat": "51.5074", "lon": "-0.1278", "station_id": "USW00013722", "dateRanges": [rng("2025-06-01", "2025-06-30")]}),
}

# Normals take the location a search resolved. Previous-year data is 2025,
# which NCEI may still revise slightly, so these compare as "exact" with a
# small numeric tolerance (set in the Phase 1 tests).
NORMALS_CASES: dict[str, tuple[str, dict]] = {
    "normals_ncei_raleigh": ("exact", {"lat": 35.78, "lon": -78.64, "provider": "ncei", "station_id": "USW00013722"}),
    "normals_grid_london": ("exact", {"lat": 51.51, "lon": -0.13, "provider": "open-meteo"}),
    "normals_grid_sydney": ("exact", {"lat": -33.87, "lon": 151.21, "provider": "open-meteo"}),
    "normals_unknown_station_falls_back_to_grid": ("exact", {"lat": 38.91, "lon": -77.04, "provider": "ncei", "station_id": "USW99999999"}),
    "normals_err_bad_latlon": ("exact", {"lat": 200, "lon": 0}),
}


def post(client: httpx.Client, base: str, path: str, body: dict) -> tuple[int, object]:
    r = client.post(base + path, json=body, headers={"Origin": "https://entotools.org" if "entotools.org" in base else "http://localhost:8788"})
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text


def run(base: str, only: str | None, verify: bool) -> int:
    groups = []
    if only in (None, "search"):
        groups.append(("search", "/api/search", SEARCH_CASES))
    if only in (None, "normals"):
        groups.append(("normals", "/api/normals", NORMALS_CASES))
    mismatches = 0
    with httpx.Client(timeout=120) as client:
        for group, path, cases in groups:
            for name, (compare, body) in cases.items():
                out = REF / group / f"{name}.json"
                if verify and (compare != "exact" or not out.exists()):
                    continue
                t0 = time.time()
                status, resp = post(client, base, path, body)
                secs = time.time() - t0
                if verify:
                    saved = json.loads(out.read_text())
                    same = saved["status"] == status and saved["response"] == resp
                    mismatches += 0 if same else 1
                    print(f"{'same ' if same else 'DIFF '} {group}/{name} ({status}, {secs:.1f}s)")
                    continue
                out.write_text(json.dumps({
                    "name": name, "kind": group, "compare": compare,
                    "request": body, "status": status, "response": resp,
                    "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "source": base,
                }, indent=1, ensure_ascii=False) + "\n")
                print(f"saved {group}/{name}: HTTP {status} ({secs:.1f}s)")
                time.sleep(1.1)  # be gentle with Nominatim (1 req/s policy)
    return mismatches


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--only", choices=["search", "normals"])
    ap.add_argument("--verify", action="store_true")
    a = ap.parse_args()
    sys.exit(1 if run(a.base.rstrip("/"), a.only, a.verify) else 0)
