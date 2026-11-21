"""Phase 0: the captured reference cases are present and well-formed.

Phase 1 adds tests that run the Python backend against these same requests.
"""
import json
from pathlib import Path

import pytest

REF = Path(__file__).parent / "reference"
CASES = sorted(REF.glob("*/*.json"))


def test_cases_exist():
    assert len(list(REF.glob("search/*.json"))) >= 20
    assert len(list(REF.glob("normals/*.json"))) >= 4


@pytest.mark.parametrize("path", CASES, ids=lambda p: f"{p.parent.name}/{p.stem}")
def test_case_shape(path):
    case = json.loads(path.read_text())
    assert {"name", "kind", "compare", "request", "status", "response"} <= case.keys()
    assert case["compare"] in ("exact", "shape")
    if case["status"] == 200 and case["kind"] == "search":
        r = case["response"]
        assert r["provider"] in ("ncei", "open-meteo")
        assert r["ranges"] and all(rng["temperatures"] for rng in r["ranges"])
    elif case["status"] != 200:
        assert "error" in case["response"]
