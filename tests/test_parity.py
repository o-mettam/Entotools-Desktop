"""Phase 1.7 — the Python port gives the web Worker's answers.

Validation-error cases run offline (they must never touch the network).
Lookups talk to the real services, so they only run with
ENTOTOOLS_NETWORK_TESTS=1. Comparison rules: PROJECT_LOG.md → "Reference data".
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
from pathlib import Path

import pytest

from entotools_desktop.cache import Cache
from entotools_desktop.net import Net
from entotools_desktop.weather import WeatherService

REF = Path(__file__).parent / "reference"
NETWORK = os.environ.get("ENTOTOOLS_NETWORK_TESTS") == "1"


def load(group):
    return [json.loads(p.read_text()) for p in sorted((REF / group).glob("*.json"))]


class NoNetwork(Net):
    def get(self, *a, **k):  # pragma: no cover — failing here is the test failure
        raise AssertionError("validation errors must be decided before any network call")


@pytest.fixture(scope="module")
def live_service(tmp_path_factory):
    svc = WeatherService(Net(), Cache(tmp_path_factory.mktemp("c") / "cache.db"))
    yield svc
    svc.net.close()


# ── validation errors: exact, offline ─────────────────────────────
ERROR_CASES = [c for c in load("search") + load("normals") if c["status"] != 200]


@pytest.mark.parametrize("case", ERROR_CASES, ids=lambda c: c["name"])
def test_validation_errors_match_exactly(case, tmp_path):
    svc = WeatherService(NoNetwork(), Cache(tmp_path / "c.db"))
    fn = svc.search if case["kind"] == "search" else svc.normals
    assert fn(case["request"]) == (case["status"], case["response"])


# ── live lookups ──────────────────────────────────────────────────
def close(a, b, tol):
    if a is None or b is None:
        return a is b
    return abs(a - b) <= tol


def assert_temps_equal(ref_ranges, got_ranges):
    assert len(got_ranges) == len(ref_ranges)
    for r, g in zip(ref_ranges, got_ranges):
        assert (g["label"], g["startDate"], g["endDate"]) == (r["label"], r["startDate"], r["endDate"])
        assert len(g["temperatures"]) == len(r["temperatures"])
        for rt, gt in zip(r["temperatures"], g["temperatures"]):
            assert gt == rt, f"{rt['date']}: expected {rt}, got {gt}"


def compare_search(case, svc):
    ref = case["response"]
    status, got = svc.search(case["request"])
    assert status == case["status"], got
    for k in ("provider", "is_fallback", "provider_fallback", "country_code", "forecast_unavailable"):
        assert got[k] == ref[k], k
    assert close(got["search_lat"], ref["search_lat"], 1e-3) and close(got["search_lon"], ref["search_lon"], 1e-3)
    if case["request"]["mode"] == "latlon":
        assert got["location"] == ref["location"]

    if got["station"]["station_id"] == ref["station"]["station_id"]:
        for k, v in ref["station"].items():
            if k == "distance_miles":
                assert close(got["station"][k], v, 0.11)
            else:
                assert got["station"][k] == v, k
        assert_temps_equal(ref["ranges"], got["ranges"])
        return "same station"
    # Rule 3: automatic station choice drifted. Check the data itself by
    # asking for the reference's station explicitly.
    assert ref["station"].get("selection") == "auto", "only automatic picks may drift"
    body = dict(case["request"], station_id=ref["station"]["station_id"])
    status, pinned = svc.search(body)
    assert status == 200, pinned
    assert_temps_equal(ref["ranges"], pinned["ranges"])
    return f"station drifted {ref['station']['station_id']} → {got['station']['station_id']}; data matches when pinned"


SEARCH_OK = [c for c in load("search") if c["status"] == 200 and c["compare"] == "exact"]


@pytest.mark.network
@pytest.mark.skipif(not NETWORK, reason="set ENTOTOOLS_NETWORK_TESTS=1")
@pytest.mark.parametrize("case", SEARCH_OK, ids=lambda c: c["name"])
def test_search_matches_reference(case, live_service, capsys):
    note = compare_search(case, live_service)
    with capsys.disabled():
        print(f"\n    {case['name']}: {note}", end="")


SHAPE = [c for c in load("search") if c["compare"] == "shape"]


@pytest.mark.network
@pytest.mark.skipif(not NETWORK, reason="set ENTOTOOLS_NETWORK_TESTS=1")
@pytest.mark.parametrize("case", SHAPE, ids=lambda c: c["name"])
def test_forecast_cases_have_reference_shape(case, live_service):
    """Ranges reaching today: structure only, plus the F1 fix."""
    req = json.loads(json.dumps(case["request"]))
    today = dt.date.today()
    if case["name"].startswith("wholly_future"):
        req["dateRanges"][0].update(startDate=(today + dt.timedelta(days=3)).isoformat(),
                                    endDate=(today + dt.timedelta(days=10)).isoformat())
    else:
        req["dateRanges"][0]["endDate"] = today.isoformat()
    status, got = live_service.search(req)
    assert status == 200, got
    assert set(got) == set(case["response"])
    temps = got["ranges"][0]["temperatures"]
    assert set(temps[0]) <= {"date", "TMIN", "TMAX", "PRCP", "PRCP_ACCUM", "is_forecast"}
    if not case["name"].startswith("wholly_future"):
        # F1: a range ending on the LOCAL today gets the forecast horizon past it.
        assert temps[-1]["date"] > today.isoformat(), "forecast should extend past today"


NORMALS_OK = [c for c in load("normals") if c["status"] == 200]


@pytest.mark.network
@pytest.mark.skipif(not NETWORK, reason="set ENTOTOOLS_NETWORK_TESTS=1")
@pytest.mark.parametrize("case", NORMALS_OK, ids=lambda c: c["name"])
def test_normals_match_reference(case, live_service):
    ref = case["response"]
    status, got = live_service.normals(case["request"])
    assert status == 200, got
    assert (got["source"], got["period"], got["years_used"]) == (ref["source"], ref["period"], ref["years_used"])
    assert set(got["years"]) == set(ref["years"])
    for y, days in ref["years"].items():
        assert len(got["years"][y]) == len(days), y
        for (rlo, rhi), (glo, ghi) in zip(days, got["years"][y]):
            assert close(glo, rlo, 0.1) and close(ghi, rhi, 0.1), y
    if case.get("upstream_failure_at_capture"):
        return  # reference is incomplete for a recorded upstream reason
    if ref["previous_year"] is None:
        assert got["previous_year"] is None
    else:
        assert got["previous_year"]["year"] == ref["previous_year"]["year"]
        rdays, gdays = ref["previous_year"]["days"], got["previous_year"]["days"]
        assert len(gdays) == len(rdays)
        diffs = sum(1 for (a, b), (c, d) in zip(rdays, gdays) if not (close(c, a, 0.1) and close(d, b, 0.1)))
        assert diffs <= 3, f"{diffs} days of the previous year differ (NCEI revisions allow a few)"
