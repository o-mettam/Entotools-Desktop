"""CSV backup format: reading and writing collection records.

Two layouts, one reader:

* WEB layout ("simple"): the 33 columns the website exports
  (public/sync/sync-core.js EntoCsv). Readable, but lossy: no record IDs,
  times flattened to "1:00 PM – 4:00 PM", humidity/range/mGDD merged.
* FULL layout: the same 33 columns first (so it still reads well in Excel and
  still imports into the website), then machine columns that make it lossless:
  Record ID, Created/Updated At, Time Start/End, Input Mode, Is Range, mGDD
  Start/End, humidity values, Country Code, City, State, and "Extra Fields
  (JSON)" for anything outside the known schema.

Import rules (see store.Store.import_records):
  * A row with a Record ID updates the record with that ID if the row's
    Updated At is newer; otherwise it is added with that ID.
  * A row without one (a web export) is converted like the website does, and
    skipped if an identical record already exists, so re-importing the same
    file never duplicates records.
  * In the FULL layout, the machine columns are authoritative for fields that
    also have a display column (mGDD, Time of Collection, Coordinates
    Estimated, Humidity). Editing those display cells in Excel has no effect.

Formula guard: cells beginning with = + - @ tab or CR get a leading apostrophe
so spreadsheets treat them as text, EXCEPT plain numbers ("-77.0369"). The
website guards numbers too, which corrupts negative coordinates and
temperatures on re-import (finding F9); the reader removes that apostrophe.
"""
from __future__ import annotations

import json
import math
import re

from .jscompat import js_parse_float, js_str

FORMAT_MARKER = "Record ID"

WEB_HEADERS = [
    "Specimen ID", "Specimen Identification", "Number of Specimens",
    "Site Name", "Location", "Country", "Latitude", "Longitude", "Coordinates Estimated", "Elevation (m)",
    "Date Start", "Date End", "Sunset", "Time of Collection",
    "Collector", "Determiner",
    "High Temp (F)", "Low Temp (F)", "Avg Temp (F)", "Temp at Collection (F)", "mGDD",
    "Humidity (%)", "Rainfall Last 7 Days (in)", "Rainfall Last 30 Days (in)",
    "Weather Station", "Station ID", "Station Distance (mi)", "Data Provider",
    "mGDD Base Temp (F)", "mGDD Max Temp (F)", "mGDD Accum Start Date",
    "Collection Method", "Notes",
]

MACHINE_HEADERS = [
    "Record ID", "Created At", "Updated At",
    "Time Start", "Time End", "Time Text", "Input Mode", "Is Range",
    "mGDD Start", "mGDD End", "Daily mGDD Start",
    "Humidity at Collection (%)", "Humidity Daily Avg (%)",
    "Country Code", "City", "State",
    "Extra Fields (JSON)",
]
FULL_HEADERS = WEB_HEADERS + MACHINE_HEADERS

# data key → column, for fields stored exactly in one column.
TEXT_FIELDS = {
    "specimenId": "Specimen ID", "identification": "Specimen Identification",
    "numSpecimens": "Number of Specimens", "siteName": "Site Name", "location": "Location",
    "country": "Country", "dateStart": "Date Start", "dateEnd": "Date End", "sunset": "Sunset",
    "collector": "Collector", "identifier": "Determiner", "stationName": "Weather Station",
    "stationId": "Station ID", "provider": "Data Provider", "accumStartMD": "mGDD Accum Start Date",
    "collectionMethod": "Collection Method", "userNotes": "Notes",
    "timeStart": "Time Start", "timeEnd": "Time End", "timeOfCollection": "Time Text",
    "inputMode": "Input Mode", "countryCode": "Country Code", "city": "City", "state": "State",
}
NUMBER_FIELDS = {
    "lat": "Latitude", "lon": "Longitude", "elevation": "Elevation (m)",
    "highTemp": "High Temp (F)", "lowTemp": "Low Temp (F)", "avgTemp": "Avg Temp (F)",
    "tempAtTime": "Temp at Collection (F)", "rainfallWeek": "Rainfall Last 7 Days (in)",
    "rainfallMonth": "Rainfall Last 30 Days (in)", "stationDist": "Station Distance (mi)",
    "baseTemp": "mGDD Base Temp (F)", "maxTemp": "mGDD Max Temp (F)",
    "gddStart": "mGDD Start", "gddEnd": "mGDD End", "dailyGddStart": "Daily mGDD Start",
}
KNOWN_FIELDS = set(TEXT_FIELDS) | set(NUMBER_FIELDS) | {"isRange", "humidity"}
REQUIRED_COLUMNS = ("Date Start", "Latitude", "Longitude")


# ── cell helpers ───────────────────────────────────────────────────
_PLAIN_NUMBER = re.compile(r"-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?", re.ASCII)
_GUARDED = re.compile(r"'[=+\-@\t\r]")


def num_text(v) -> str:
    """A number as the website would print it (String(n)); '' for null."""
    if v is None or v == "":
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return js_str(v)
    return str(v)


def guard(text: str, web_style: bool = False) -> str:
    if not text or text[0] not in "=+-@\t\r":
        return text
    if not web_style and _PLAIN_NUMBER.fullmatch(text):
        return text  # FULL layout: never mangle a number
    return "'" + text


def unguard(text: str) -> str:
    return text[1:] if _GUARDED.match(text) else text


def cell(v: str) -> str:
    return '"' + v.replace('"', '""') + '"'


def line(values) -> str:
    return ",".join(cell(v) for v in values)


# ── time helpers (ports of collection_database.html / sync-core.js) ─
def time12(t) -> str:
    if not t:
        return ""
    parts = str(t).split(":")
    try:
        h, m = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return ""
    return f"{(h + 11) % 12 + 1}:{m:02d} {'PM' if h >= 12 else 'AM'}"


def time_range_text(d: dict) -> str:
    if d.get("timeStart") and d.get("timeEnd"):
        return time12(d["timeStart"]) + " – " + time12(d["timeEnd"])
    if d.get("timeStart"):
        return time12(d["timeStart"])
    toc = d.get("timeOfCollection")
    if toc and " - " in toc:
        a, b = toc.split(" - ")[:2]
        return time12(a.strip()) + " – " + time12(b.strip())
    return time12(toc) if toc else ""


def parse_12h_to_24h(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    if re.fullmatch(r"[0-9]{1,2}:[0-9]{2}", s):
        return s
    m = re.fullmatch(r"([0-9]{1,2}):([0-9]{2})\s*(AM|PM)", s, re.IGNORECASE)
    if not m:
        return ""
    h = int(m.group(1))
    ampm = m.group(3).upper()
    if ampm == "PM" and h != 12:
        h += 12
    if ampm == "AM" and h == 12:
        h = 0
    return f"{h:02d}:{m.group(2)}"


def time_range_start(s: str) -> str:
    if not s:
        return ""
    if " - " in s and re.match(r"[0-9]{2}:[0-9]{2}", s):
        return s.split(" - ")[0].strip()
    sep = "–" if "–" in s else (" - " if " - " in s else None)
    return parse_12h_to_24h(s.split(sep)[0].strip()) if sep else parse_12h_to_24h(s.strip())


def time_range_end(s: str) -> str:
    if not s:
        return ""
    if " - " in s and re.match(r"[0-9]{2}:[0-9]{2}", s):
        parts = s.split(" - ")
        return parts[1].strip() if len(parts) > 1 else ""
    sep = "–" if "–" in s else (" - " if " - " in s else None)
    if sep:
        parts = s.split(sep)
        return parse_12h_to_24h(parts[1].strip()) if len(parts) > 1 else ""
    return ""


# ── writing ───────────────────────────────────────────────────────
def web_row(d: dict) -> list[str]:
    """sync-core.js rowFromData, cell for cell. `t` is String(v ?? ''); `o`
    is for the fields the website writes as `v || ''` (falsy → blank)."""
    t = num_text
    o = lambda v: num_text(v) if v else ""  # noqa: E731
    hum = d.get("humidity") or {}
    gdd = f"{t(d.get('gddStart'))} - {t(d.get('gddEnd'))}" if d.get("isRange") else t(d.get("gddStart"))
    return [
        t(d.get("specimenId")), t(d.get("identification")), t(d.get("numSpecimens")),
        t(d.get("siteName")), t(d.get("location")), o(d.get("country") or d.get("countryCode")),
        t(d.get("lat")), t(d.get("lon")), "No" if d.get("inputMode") == "latlon" else "Yes",
        t(d.get("elevation")),
        t(d.get("dateStart")), t(d.get("dateEnd")), o(d.get("sunset")), time_range_text(d),
        t(d.get("collector")), t(d.get("identifier")),
        t(d.get("highTemp")), t(d.get("lowTemp")), t(d.get("avgTemp")),
        t(d.get("tempAtTime")), gdd,
        o(hum.get("atTime") or hum.get("avg")), t(d.get("rainfallWeek")), t(d.get("rainfallMonth")),
        t(d.get("stationName")), t(d.get("stationId")), t(d.get("stationDist")), o(d.get("provider")),
        t(d.get("baseTemp")), t(d.get("maxTemp")), t(d.get("accumStartMD")),
        o(d.get("collectionMethod")), o(d.get("userNotes")),
    ]


def full_row(entry: dict) -> list[str]:
    d = entry.get("data") or {}
    row = web_row(d)
    row[WEB_HEADERS.index("Country")] = num_text(d.get("country"))  # exact, no country-code fallback
    hum = d.get("humidity") or {}
    extra = {k: v for k, v in d.items() if k not in KNOWN_FIELDS}
    row += [
        str(entry.get("id") or ""), str(entry.get("createdAt") or ""), str(entry.get("updatedAt") or ""),
        str(d.get("timeStart") or ""), str(d.get("timeEnd") or ""), str(d.get("timeOfCollection") or ""),
        str(d.get("inputMode") or ""), "Yes" if d.get("isRange") else "No",
        num_text(d.get("gddStart")), num_text(d.get("gddEnd")), num_text(d.get("dailyGddStart")),
        num_text(hum.get("atTime")), num_text(hum.get("avg")),
        str(d.get("countryCode") or ""), str(d.get("city") or ""), str(d.get("state") or ""),
        json.dumps(extra, ensure_ascii=False, separators=(",", ":"), sort_keys=True) if extra else "",
    ]
    return row


def build_csv(entries: list[dict], layout: str = "full") -> str:
    """Active (non-deleted) entries → CSV text with a BOM (Excel-friendly)."""
    web = layout == "web"
    headers = WEB_HEADERS if web else FULL_HEADERS
    out = [line(headers)]
    for e in entries:
        if e.get("deleted") or not e.get("data"):
            continue
        values = web_row(e["data"]) if web else full_row(e)
        out.append(line(guard(v, web_style=web) for v in values))
    return "﻿" + "\n".join(out) + "\n"


# ── reading ───────────────────────────────────────────────────────
def parse_csv(text: str) -> list[list[str]]:
    """Port of collection_database.html parseCSV: quoted fields, trimmed
    cells, CRLF/LF, BOM stripped, blank rows dropped."""
    src = text[1:] if text.startswith("﻿") else text
    rows, row, field, in_quotes = [], [], [], False
    i, n = 0, len(src)

    def push_field():
        row.append("".join(field).strip())
        field.clear()

    def push_row():
        nonlocal row
        push_field()
        if any(c != "" for c in row):
            rows.append(row)
        row = []

    while i < n:
        ch = src[i]
        if in_quotes:
            if ch == '"':
                if i + 1 < n and src[i + 1] == '"':
                    field.append('"')
                    i += 1
                else:
                    in_quotes = False
            else:
                field.append(ch)
        elif ch == '"':
            in_quotes = True
        elif ch == ",":
            push_field()
        elif ch == "\r":
            if i + 1 < n and src[i + 1] == "\n":
                i += 1
            push_row()
        elif ch == "\n":
            push_row()
        else:
            field.append(ch)
        i += 1
    if field or row:
        push_row()
    return rows


def _num_or_none(text: str):
    if text == "":
        return None
    f = js_parse_float(text)
    if math.isnan(f):
        return None
    return int(f) if f.is_integer() and re.fullmatch(r"-?[0-9]+", text.strip()) else f


def web_row_to_data(get) -> dict:
    """collection_database.html csvRowToData, for files without Record IDs."""
    num = lambda name: _num_or_none(get(name))  # noqa: E731
    gdd_raw = get("mGDD")
    m = re.fullmatch(r"\s*(-?[0-9]+(?:\.[0-9]+)?)\s*[-–]\s*(-?[0-9]+(?:\.[0-9]+)?)\s*", gdd_raw)
    if m:
        gdd_start, gdd_end, is_range = _float0(m.group(1)), _float0(m.group(2)), True
    else:
        gdd_start = _float0(gdd_raw)
        gdd_end, is_range = gdd_start, False
    date_end = get("Date End")
    if date_end and date_end != get("Date Start"):
        is_range = True
    toc = get("Time of Collection")
    return {
        "specimenId": get("Specimen ID"), "identification": get("Specimen Identification"),
        "numSpecimens": get("Number of Specimens"), "siteName": get("Site Name"), "location": get("Location"),
        "country": get("Country"), "lat": num("Latitude"), "lon": num("Longitude"),
        "inputMode": "city" if get("Coordinates Estimated").lower() == "yes" else "latlon",
        "elevation": num("Elevation (m)"), "dateStart": get("Date Start"), "dateEnd": date_end or get("Date Start"),
        "isRange": is_range, "sunset": get("Sunset"), "timeOfCollection": toc,
        "timeStart": time_range_start(toc), "timeEnd": time_range_end(toc),
        "collector": get("Collector"), "identifier": get("Determiner"),
        "highTemp": num("High Temp (F)"), "lowTemp": num("Low Temp (F)"), "avgTemp": num("Avg Temp (F)"),
        "tempAtTime": num("Temp at Collection (F)"), "gddStart": gdd_start, "gddEnd": gdd_end,
        "humidity": {"atTime": None, "avg": num("Humidity (%)")},
        "rainfallWeek": num("Rainfall Last 7 Days (in)"), "rainfallMonth": num("Rainfall Last 30 Days (in)"),
        "stationName": get("Weather Station"), "stationId": get("Station ID"), "stationDist": num("Station Distance (mi)"),
        "provider": get("Data Provider"), "baseTemp": num("mGDD Base Temp (F)"), "maxTemp": num("mGDD Max Temp (F)"),
        "accumStartMD": get("mGDD Accum Start Date"), "collectionMethod": get("Collection Method"), "userNotes": get("Notes"),
    }


def _float0(text: str):
    """parseFloat(x) || 0"""
    f = js_parse_float(text)
    if math.isnan(f) or f == 0:
        return 0
    return int(f) if f.is_integer() else f


def full_row_to_entry(get) -> dict:
    data = {}
    for key, col in TEXT_FIELDS.items():
        data[key] = get(col)
    for key, col in NUMBER_FIELDS.items():
        data[key] = _num_or_none(get(col))
    data["isRange"] = get("Is Range").lower() == "yes"
    data["humidity"] = {"atTime": _num_or_none(get("Humidity at Collection (%)")),
                        "avg": _num_or_none(get("Humidity Daily Avg (%)"))}
    extra = get("Extra Fields (JSON)")
    if extra:
        try:
            parsed = json.loads(extra)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    data.setdefault(k, v)
        except ValueError:
            pass
    return {"id": get("Record ID"), "createdAt": get("Created At") or None,
            "updatedAt": get("Updated At") or None, "data": data}


class CsvImportError(ValueError):
    pass


def read_csv(text: str) -> tuple[list[dict], list[str]]:
    """CSV text → (entries, problems). Entries from a FULL file carry an id;
    entries from a web file have id None. Rows missing a start date or
    coordinates are skipped (as the website does) and reported."""
    rows = parse_csv(text)
    if len(rows) < 2:
        raise CsvImportError("CSV must have a header row and at least one data row.")
    header = {h.strip(): i for i, h in enumerate(rows[0])}
    missing = [h for h in REQUIRED_COLUMNS if h not in header]
    if missing:
        raise CsvImportError("CSV is missing required columns: " + ", ".join(missing))
    full = FORMAT_MARKER in header
    entries, problems = [], []
    for r, vals in enumerate(rows[1:], start=2):
        if len(vals) < 3:
            continue
        get = lambda name, vals=vals: unguard(vals[header[name]]) if name in header and header[name] < len(vals) else ""  # noqa: E731
        entry = full_row_to_entry(get) if full and get(FORMAT_MARKER) else {"id": None, "createdAt": None, "updatedAt": None, "data": web_row_to_data(get)}
        d = entry["data"]
        if not d.get("dateStart") or d.get("lat") is None or d.get("lon") is None:
            problems.append(f"Row {r}: skipped — missing date or coordinates.")
            continue
        entries.append(entry)
    return entries, problems
