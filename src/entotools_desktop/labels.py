"""PDF specimen labels and field notes (Phase 4, D6 / D11).

Text: label lines are built exactly as the website's Label Data page builds
them (buildLabel1Html / buildLabel2Html / fmtDate / fmtTimeRange, verified
line for line in tests/test_labels.py by running that JavaScript in Node).

Layout: the website's print stylesheet, converted to points (1 CSS px =
0.75 pt) on US Letter with 0.5 in margins:
    9px Inter (6.75 pt), line-height 1.3, 1.5px border, padding 0.3rem/0.4rem,
    each box shrink-to-fit up to 2.5 in wide (border-box), 4px gaps, boxes
    flowing left→right and wrapping to new rows and pages.
Field notes get their own readable sheet layout (the website squeezed the
notes table into a 2.5 in label box).

Characters missing from Inter (e.g. ♀ ♂) are drawn with DejaVu Sans.
"""
from __future__ import annotations

import datetime as dt
import io
import math
from dataclasses import dataclass, field
from importlib import resources

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from . import __version__
from .jscompat import js_str

PX = 0.75                        # one CSS pixel in points
FONT_SIZE = 9 * PX               # 6.75 pt
LEADING = FONT_SIZE * 1.3
PAD_V, PAD_H = 0.3 * 16 * PX, 0.4 * 16 * PX
BORDER = 1.5 * PX
MAX_W = 2.5 * 72
GAP = 4 * PX
MARGIN = 0.5 * 72
PAGE_W, PAGE_H = letter
INK = HexColor("#1e293b")
MUTED = HexColor("#475569")
FAINT = HexColor("#94a3b8")
LINE = HexColor("#cbd5e1")

ROMAN_MONTHS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
MISSING = object()

# ── fonts ──────────────────────────────────────────────────────────
_FONTS = {"regular": ("EntoInter", "Inter-Regular.ttf"), "italic": ("EntoInter-Italic", "Inter-Italic.ttf"),
          "bold": ("EntoInter-Bold", "Inter-Bold.ttf")}
_FALLBACK = {"regular": ("EntoDejaVu", "DejaVuSans.ttf"), "italic": ("EntoDejaVu-Oblique", "DejaVuSans-Oblique.ttf"),
             "bold": ("EntoDejaVu", "DejaVuSans.ttf")}
_registered = False
_cmaps: dict[str, set[int]] = {}


def _register() -> None:
    global _registered
    if _registered:
        return
    base = resources.files(__package__).joinpath("data/fonts")
    for name, filename in list(_FONTS.values()) + list(_FALLBACK.values()):
        if name not in pdfmetrics.getRegisteredFontNames():
            with resources.as_file(base.joinpath(filename)) as path:
                font = TTFont(name, str(path))
            pdfmetrics.registerFont(font)
        _cmaps[name] = set(pdfmetrics.getFont(name).face.charToGlyph)
    _registered = True


def _runs(text: str, style: str) -> list[tuple[str, str]]:
    """Split text into (font, chunk) runs: Inter where it has the glyph,
    DejaVu otherwise."""
    main, fallback = _FONTS[style][0], _FALLBACK[style][0]
    runs: list[tuple[str, str]] = []
    for ch in text:
        name = main if ord(ch) in _cmaps[main] or ch in "\n\t" else fallback
        if runs and runs[-1][0] == name:
            runs[-1] = (name, runs[-1][1] + ch)
        else:
            runs.append((name, ch))
    return runs


def text_width(text: str, style: str, size: float) -> float:
    return sum(pdfmetrics.stringWidth(chunk, name, size) for name, chunk in _runs(text, style))


def draw_text(c: canvas.Canvas, x: float, y: float, text: str, style: str, size: float) -> None:
    for name, chunk in _runs(text, style):
        c.setFont(name, size)
        c.drawString(x, y, chunk)
        x += pdfmetrics.stringWidth(chunk, name, size)


def wrap(text: str, style: str, size: float, width: float) -> list[str]:
    """Greedy word wrap (CSS normal wrapping); over-long words are broken."""
    out: list[str] = []
    for para in text.split("\n"):
        words, line = para.split(" "), ""
        for w in words:
            candidate = w if not line else line + " " + w
            if text_width(candidate, style, size) <= width:
                line = candidate
                continue
            if line:
                out.append(line)
            while text_width(w, style, size) > width and len(w) > 1:  # break a long word
                cut = len(w)
                while cut > 1 and text_width(w[:cut], style, size) > width:
                    cut -= 1
                out.append(w[:cut])
                w = w[cut:]
            line = w
        out.append(line)
    return out


# ── label text (ports of label_data.html) ─────────────────────────
def js_val(d: dict, key: str) -> str:
    """`${d.key}` in a JS template literal."""
    v = d.get(key, MISSING)
    if v is MISSING:
        return "undefined"
    if v is None:
        return "null"
    return js_str(v) if isinstance(v, (int, float)) else str(v)


def esc_text(v) -> str:
    """What esc(v) displays: null/undefined → '', numbers as JS prints them."""
    if v is None or v is MISSING:
        return ""
    return js_str(v) if isinstance(v, (int, float)) else str(v)


def fmt_date(d) -> str:
    try:
        day = dt.date.fromisoformat(str(d))
    except (TypeError, ValueError):
        return "" if d is None or d is MISSING else str(d)
    return f"{day.day:02d}-{ROMAN_MONTHS[day.month - 1]}-{day.year}"


def _js_number(s: str) -> float:
    s = s.strip()
    if s == "":
        return 0.0
    try:
        return float(s)
    except ValueError:
        return math.nan


def fmt_time12(t) -> str:
    if not t:
        return ""
    parts = str(t).split(":")
    h = _js_number(parts[0])
    m = _js_number(parts[1]) if len(parts) > 1 else math.nan
    ampm = "PM" if h >= 12 else "AM"
    hr = math.fmod(h, 12) if not math.isnan(h) else math.nan
    hr = 12 if (math.isnan(hr) or hr == 0) else hr
    return f"{js_str(hr)}:{js_str(m).rjust(2, '0')} {ampm}"


def fmt_time_range(d: dict) -> str:
    if d.get("timeStart") and d.get("timeEnd"):
        return fmt_time12(d["timeStart"]) + " – " + fmt_time12(d["timeEnd"])
    if d.get("timeStart"):
        return fmt_time12(d["timeStart"])
    toc = d.get("timeOfCollection")
    if toc and " - " in toc:
        parts = toc.split(" - ")
        return fmt_time12(parts[0].strip()) + " – " + fmt_time12(parts[1].strip())
    return fmt_time12(toc) if toc else ""


@dataclass
class Line:
    text: str
    style: str = "regular"


def label1_lines(d: dict) -> list[Line]:
    if d.get("isRange"):
        date_display = f"{fmt_date(d.get('dateStart', MISSING))} – {fmt_date(d.get('dateEnd', MISSING))}"
        gdd_display = f"mGDD: {js_val(d, 'gddStart')} – {js_val(d, 'gddEnd')}"
    else:
        date_display = fmt_date(d.get("dateStart", MISSING))
        gdd_display = f"mGDD: {js_val(d, 'gddStart')}"
    time_display = fmt_time_range(d)
    prefix = "" if d.get("inputMode") == "latlon" else "APPROX. "
    lines = []
    if d.get("siteName"):
        lines.append(Line(esc_text(d["siteName"])))
    lines.append(Line(esc_text(d.get("location"))))
    lines.append(Line(f"{prefix}{js_val(d, 'lat')}, {js_val(d, 'lon')}"))
    lines.append(Line(date_display + (", " + time_display if time_display else "")))
    elev = esc_text(d.get("elevation")) + " m" if d.get("elevation") is not None else "—"
    lines.append(Line(f"{gdd_display}, Elev. {elev}"))
    if d.get("collector"):
        lines.append(Line("COLL. " + esc_text(d["collector"])))
    return lines


def label2_lines(d: dict) -> list[Line] | None:
    if not (d.get("identifier") or d.get("identification") or d.get("specimenId")):
        return None
    lines = []
    if d.get("specimenId"):
        lines.append(Line(esc_text(d["specimenId"])))
    if d.get("identification"):
        lines.append(Line(esc_text(d["identification"]), "italic"))
    if d.get("identifier"):
        lines.append(Line("DET. " + esc_text(d["identifier"])))
    return lines


def notes_rows(d: dict) -> list[tuple[str, str, str]]:
    """renderNotes() rows as (label, value, suffix-in-grey)."""
    hum = d.get("humidity") or {}
    deg = lambda k: f"{js_val(d, k)}°F" if d.get(k) is not None else "—"  # noqa: E731
    rows = [("Sunset", esc_text(d.get("sunset")) or "—", ""),
            ("High / Low Temp", f"{deg('highTemp')} / {deg('lowTemp')}", "")]
    if d.get("avgTemp") is not None:
        rows.append(("Average Temp", f"{js_val(d, 'avgTemp')}°F", ""))
    has_time = d.get("timeStart") or d.get("timeOfCollection")
    if has_time:
        rows.append(("Time of Collection", fmt_time_range(d), ""))
    if has_time and d.get("tempAtTime") is not None:
        rows.append(("Temp at Collection", f"{js_val(d, 'tempAtTime')}°F", ""))
    elif has_time and d.get("avgTemp") is not None:
        rows.append(("Temp at Collection", f"{js_val(d, 'avgTemp')}°F", "(daily avg)"))
    if has_time and hum.get("atTime") is not None:
        rows.append(("Humidity at Collection", f"{esc_text(hum['atTime'])}%", ""))
    elif hum.get("avg") is not None:
        rows.append(("Humidity at Collection", f"{esc_text(hum['avg'])}%", ""))
    rows.append(("Rainfall (last 7 days)", f"{js_val(d, 'rainfallWeek')} in", ""))
    rows.append(("Rainfall (last 30 days)", f"{js_val(d, 'rainfallMonth')} in", ""))
    gdd = f"{js_val(d, 'gddStart')} – {js_val(d, 'gddEnd')}" if d.get("isRange") else js_val(d, "gddStart")
    rows.append(("mGDD", gdd, ""))
    rows.append(("Elevation", f"{esc_text(d.get('elevation'))} m" if d.get("elevation") is not None else "—", ""))
    rows.append(("Weather Station", f"{esc_text(d.get('stationName'))} ({esc_text(d.get('stationId'))})", ""))
    if d.get("numSpecimens"):
        rows.append(("Specimens Collected", esc_text(d["numSpecimens"]), ""))
    if d.get("collectionMethod"):
        rows.append(("Collection Method", esc_text(d["collectionMethod"]), ""))
    return rows


# ── layout ─────────────────────────────────────────────────────────
@dataclass
class Box:
    lines: list[Line]
    wrapped: list[Line] = field(default_factory=list)
    w: float = 0.0
    h: float = 0.0

    def measure(self) -> "Box":
        inner = MAX_W - 2 * (PAD_H + BORDER)
        self.wrapped = [Line(t, ln.style) for ln in self.lines for t in wrap(ln.text, ln.style, FONT_SIZE, inner)]
        widest = max((text_width(ln.text, ln.style, FONT_SIZE) for ln in self.wrapped), default=0)
        self.w = min(MAX_W, widest + 2 * (PAD_H + BORDER))
        self.h = len(self.wrapped) * LEADING + 2 * (PAD_V + BORDER)
        return self


def _baseline_offset() -> float:
    """Distance from a line box's top to its baseline (CSS half-leading)."""
    ascent, descent = pdfmetrics.getAscentDescent(_FONTS["regular"][0], FONT_SIZE)
    return (LEADING - (ascent - descent)) / 2 + ascent


def _draw_box(c: canvas.Canvas, b: Box, x: float, top: float) -> None:
    c.setStrokeColor(INK)
    c.setLineWidth(BORDER)
    c.rect(x + BORDER / 2, top - b.h + BORDER / 2, b.w - BORDER, b.h - BORDER, stroke=1, fill=0)
    c.setFillColor(INK)
    y = top - BORDER - PAD_V - _baseline_offset()
    for ln in b.wrapped:
        draw_text(c, x + BORDER + PAD_H, y, ln.text, ln.style, FONT_SIZE)
        y -= LEADING


def _new_canvas(buf, title: str) -> canvas.Canvas:
    # Start on Inter so the PDF never declares ReportLab's default Helvetica.
    c = canvas.Canvas(buf, pagesize=letter, invariant=True, pageCompression=1,
                      initialFontName=_FONTS["regular"][0], initialFontSize=FONT_SIZE)
    c.setTitle(title)
    c.setAuthor("EntoTools")
    c.setCreator(f"EntoTools desktop {__version__}")
    return c


def labels_pdf(items: list[dict], which: str = "both") -> bytes:
    """Label boxes for each item's data, in order: Label 1 then (if any)
    Label 2 per item. which = both | label1 | label2."""
    _register()
    boxes: list[Box] = []
    for item in items:
        d = item.get("data") or {}
        if which in ("both", "label1"):
            boxes.append(Box(label1_lines(d)).measure())
        if which in ("both", "label2"):
            l2 = label2_lines(d)
            if l2:
                boxes.append(Box(l2).measure())
    buf = io.BytesIO()
    c = _new_canvas(buf, "EntoTools labels")
    x, top, row_h = MARGIN, PAGE_H - MARGIN, 0.0
    for b in boxes:
        if x > MARGIN and x + b.w > PAGE_W - MARGIN:  # wrap to the next row
            x, top, row_h = MARGIN, top - row_h - GAP, 0.0
        if top - b.h < MARGIN and top < PAGE_H - MARGIN:  # next page
            c.showPage()
            x, top, row_h = MARGIN, PAGE_H - MARGIN, 0.0
        _draw_box(c, b, x, top)
        x += b.w + GAP
        row_h = max(row_h, b.h)
    if not boxes:
        c.setFont(_FONTS["regular"][0], 10)
        c.drawString(MARGIN, PAGE_H - MARGIN - 10, "No labels to print.")
    c.showPage()
    c.save()
    return buf.getvalue()


def notes_pdf(items: list[dict]) -> bytes:
    """One field-notes block per item: title, the website's notes rows, and a
    notes box with the user's notes."""
    _register()
    size, lead = 9.0, 9.0 * 1.45
    label_w = 1.7 * 72
    value_x = MARGIN + label_w
    value_w = PAGE_W - MARGIN - value_x
    buf = io.BytesIO()
    c = _new_canvas(buf, "EntoTools field notes")
    y = PAGE_H - MARGIN

    def need(height):
        nonlocal y
        if y - height < MARGIN:
            c.showPage()
            y = PAGE_H - MARGIN

    for i, item in enumerate(items):
        d = item.get("data") or {}
        title = " — ".join(t for t in (esc_text(d.get("siteName")), esc_text(d.get("location"))) if t) or "Collection"
        prefix = "" if d.get("inputMode") == "latlon" else "APPROX. "
        sub = f"{prefix}{js_val(d, 'lat')}, {js_val(d, 'lon')}"
        title_lines = wrap(title, "bold", 12, PAGE_W - 2 * MARGIN)
        need(len(title_lines) * 15 + 30)
        c.setFillColor(INK)
        for t in title_lines:
            y -= 15
            draw_text(c, MARGIN, y, t, "bold", 12)
        c.setFillColor(MUTED)
        y -= 13
        draw_text(c, MARGIN, y, f"{fmt_date(d.get('dateStart', MISSING))} · {sub}", "regular", size)
        y -= 8
        for label, value, suffix in notes_rows(d):
            vlines = wrap(value + (" " + suffix if suffix else ""), "regular", size, value_w)
            need(len(vlines) * lead + 4)
            y -= lead
            c.setFillColor(MUTED)
            draw_text(c, MARGIN, y, label, "bold", size)
            c.setFillColor(INK)
            for j, vl in enumerate(vlines):
                if j:
                    y -= lead
                if suffix and j == len(vlines) - 1 and vl.endswith(suffix):
                    main = vl[: -len(suffix)]
                    draw_text(c, value_x, y, main, "regular", size)
                    c.setFillColor(FAINT)
                    draw_text(c, value_x + text_width(main, "regular", size), y, suffix, "regular", size)
                    c.setFillColor(INK)
                else:
                    draw_text(c, value_x, y, vl, "regular", size)
        # Notes box (min height 60px as on the website)
        note_lines = wrap(esc_text(d.get("userNotes")), "regular", size, value_w - 12) if d.get("userNotes") else []
        box_h = max(60 * PX, len(note_lines) * lead + 12)
        need(box_h + lead + 8)
        y -= lead + 4
        c.setFillColor(MUTED)
        draw_text(c, MARGIN, y, "Notes", "bold", size)
        top = y + size
        c.setStrokeColor(LINE)
        c.setLineWidth(0.75)
        c.roundRect(value_x, top - box_h, value_w, box_h, 4.5, stroke=1, fill=0)
        c.setFillColor(INK)
        ny = top - 6 - size
        for nl in note_lines:
            draw_text(c, value_x + 6, ny, nl, "regular", size)
            ny -= lead
        y = top - box_h - 22
        if i < len(items) - 1:
            c.setStrokeColor(LINE)
            c.line(MARGIN, y + 10, PAGE_W - MARGIN, y + 10)
    if not items:
        c.setFont(_FONTS["regular"][0], 10)
        c.drawString(MARGIN, PAGE_H - MARGIN - 10, "No field notes to print.")
    c.showPage()
    c.save()
    return buf.getvalue()


def build_pdf(items: list[dict], which: str) -> bytes:
    if which == "notes":
        return notes_pdf(items)
    if which not in ("both", "label1", "label2"):
        raise ValueError("which must be both, label1, label2 or notes")
    return labels_pdf(items, which)
