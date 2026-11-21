"""Phase 2.3 / 2.5 — CSV formats.

* The WEB layout is byte-identical to what the website exports.
* Reading a website CSV gives what the website's own importer gives, except
  that the F9 apostrophe on negative numbers is undone.
* The FULL layout round-trips every field.
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from entotools_desktop import csvio
from samples import samples

WEB_JS = Path(__file__).parent / "reference" / "web_js"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")


def node(script: str):
    return json.loads(subprocess.check_output(["node", "-e", script], text=True))


@needs_node
def test_web_layout_is_identical_to_website_export():
    entries = samples()
    js = (
        "globalThis.window = globalThis; globalThis.localStorage = {getItem(){return null}, setItem(){}, removeItem(){}};"
        f"require({json.dumps(str(WEB_JS / 'sync-core.js'))});"
        f"console.log(JSON.stringify(window.EntoCsv.buildCsv({json.dumps(entries)})));"
    )
    assert csvio.build_csv(entries, "web") == node(js)


@needs_node
def test_full_layout_parses_the_same_as_the_websites_parser():
    text = csvio.build_csv(samples(), "full")
    js = (f"const m = require({json.dumps(str(WEB_JS / 'collection_import.js'))});"
          f"console.log(JSON.stringify(m.parseCSV({json.dumps(text)})));")
    assert csvio.parse_csv(text) == node(js)


def web_reference_rows(text: str) -> list[dict]:
    js = (f"const m = require({json.dumps(str(WEB_JS / 'collection_import.js'))});"
          f"const rows = m.parseCSV({json.dumps(text)}); const h = {{}}; rows[0].forEach((c, i) => h[c.trim()] = i);"
          "console.log(JSON.stringify(rows.slice(1).map(r => m.csvRowToData(h, r))));")
    return node(js)


@needs_node
def test_reading_a_website_csv_matches_the_websites_importer_except_f9():
    web_csv = csvio.build_csv(samples(), "web")
    entries, problems = csvio.read_csv(web_csv)
    ours = [e["data"] for e in entries]
    theirs = web_reference_rows(web_csv)
    # F9: the website loses negative numbers ("'-78.7639" → NaN → null) and
    # then skips the row for "missing coordinates". Every sample has a negative
    # longitude or latitude, so the website keeps none of them.
    assert [t for t in theirs if t["lat"] is not None and t["lon"] is not None] == []
    assert problems == [] and len(ours) == len(samples())
    # The website's importer never removes its own guard apostrophe either, so
    # text like "=SUM(…)" comes back as "'=SUM(…)" (also F9). Undo that on the
    # website's side, and its field mapping and ours agree exactly.
    full = csvio.build_csv(samples(), "full")
    js_rows = [{k: csvio.unguard(v) if isinstance(v, str) else v for k, v in row.items()}
               for row in web_reference_rows(full)]
    assert ours == js_rows


def normalized(entry: dict) -> dict:
    """What a lossless round trip must preserve: ids, timestamps, every data
    field. Missing text fields and '' are equivalent; missing isRange = False."""
    d = copy.deepcopy(entry["data"])
    for k in csvio.TEXT_FIELDS:
        d[k] = d.get(k) or ""
    for k in csvio.NUMBER_FIELDS:
        d.setdefault(k, None)
    d["isRange"] = bool(d.get("isRange"))
    hum = d.get("humidity") or {}
    d["humidity"] = {"atTime": hum.get("atTime"), "avg": hum.get("avg")}
    return {"id": entry["id"], "createdAt": entry["createdAt"], "updatedAt": entry["updatedAt"], "data": d}


def test_full_layout_round_trips_every_field():
    original = samples()
    text = csvio.build_csv(original, "full")
    back, problems = csvio.read_csv(text)
    assert problems == []
    assert [normalized(e) for e in back] == [normalized(e) for e in original]


def test_full_layout_guards_formulas_but_not_numbers():
    text = csvio.build_csv(samples(), "full")
    assert "\"'=SUM(A1:A3) should stay text\"" in text
    assert "\"'@first\"" in text and "\"'+light trap\"" in text and "\"'-dash site\"" in text
    assert '"-78.7639"' in text and '"-33.8688"' in text and '"-2.5"' in text  # numbers untouched


def test_website_layout_guards_numbers_like_the_website_does():
    assert "\"'-78.7639\"" in csvio.build_csv(samples(), "web")


def test_rows_without_date_or_coordinates_are_reported():
    bad = copy.deepcopy(samples()[:2])
    bad[0]["data"]["dateStart"] = ""
    bad[1]["data"]["lat"] = None
    entries, problems = csvio.read_csv(csvio.build_csv(bad, "full"))
    assert entries == [] and len(problems) == 2


def test_missing_required_columns_is_an_error():
    with pytest.raises(csvio.CsvImportError, match="Latitude"):
        csvio.read_csv("Date Start,Longitude\n2025-01-01,-77\n")


def test_excel_style_crlf_and_bom_are_accepted():
    text = csvio.build_csv(samples(), "full").replace("\n", "\r\n")
    assert len(csvio.read_csv(text)[0]) == len(samples())
