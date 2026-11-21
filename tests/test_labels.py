"""Phase 4 — PDF labels.

* Label text equals what the website's Label Data page builds (its own
  buildLabel1Html / buildLabel2Html, run in Node), line for line, italics too.
* PDFs are valid, US Letter, embed only our fonts, contain the expected text,
  and lay boxes out within the page margins.
"""
from __future__ import annotations

import copy
import html
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter

from entotools_desktop import labels
from samples import samples

PAGE = Path(__file__).resolve().parent.parent / "src" / "entotools_desktop" / "web" / "sample-collection" / "index.html"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")


def extract(src: str, name: str) -> str:
    i = src.index(f"function {name}(")
    j, depth = src.index("{", i), 0
    for k in range(j, len(src)):
        depth += {"{": 1, "}": -1}.get(src[k], 0)
        if depth == 0:
            return src[i:k + 1]
    raise AssertionError(name)


def website_label_lines(items: list[dict]) -> list[list[list[tuple[str, bool]] | None]]:
    """Run the page's own builders in Node; return [label1, label2] per item
    as lists of (text, italic) lines."""
    src = PAGE.read_text(encoding="utf-8")
    roman = re.search(r"const ROMAN_MONTHS = \[[^\]]*\];", src).group(0)
    fns = "\n".join(extract(src, n) for n in ("fmtDate", "fmtTime12", "fmtTimeRange", "buildLabel1Html", "buildLabel2Html"))
    # esc() as ento-gdd.js does it (text-node round trip + quotes), without a DOM.
    esc = ("function esc(s){ s = s == null ? '' : String(s); return s.replace(/&/g,'&amp;').replace(/</g,'&lt;')"
           ".replace(/>/g,'&gt;').replace(/\\u00a0/g,'&nbsp;').replace(/\"/g,'&quot;').replace(/'/g,'&#39;'); }")
    js = f"{esc}\n{roman}\n{fns}\nconst items = {json.dumps(items)};\n" \
         "console.log(JSON.stringify(items.map(d => [buildLabel1Html(d), buildLabel2Html(d)])));"
    out = json.loads(subprocess.check_output(["node", "-e", js], text=True))

    def lines(h):
        if h is None:
            return None
        res = []
        for div in re.findall(r"<div>(.*?)</div>", h, re.S):
            italic = div.startswith("<em>")
            res.append((html.unescape(re.sub(r"<[^>]+>", "", div)), italic))
        return res
    return [[lines(a), lines(b)] for a, b in out]


def ours(d):
    l1 = [(ln.text, ln.style == "italic") for ln in labels.label1_lines(d)]
    l2 = labels.label2_lines(d)
    return [l1, None if l2 is None else [(ln.text, ln.style == "italic") for ln in l2]]


def edge_cases() -> list[dict]:
    base = samples()[0]["data"]
    cases = [e["data"] for e in samples()]
    cases += [
        dict(base, siteName="", collector="", inputMode="city"),                     # optional lines absent, APPROX.
        dict(base, identification="Photinus pyralis ♂", identifier="", specimenId=""),  # only an identification
        dict(base, identification="", identifier="", specimenId=""),                 # no label 2
        dict(base, location=None, elevation=None, gddStart=None),                   # nulls
        {k: v for k, v in base.items() if k not in ("gddStart", "lat")},             # missing keys → "undefined"
        dict(base, timeStart="12:05", timeEnd="00:30"),                              # noon / midnight
        dict(base, timeStart="", timeEnd="", timeOfCollection="7:5"),                # odd time text
        dict(base, dateStart="not-a-date", isRange=True, dateEnd="2025-13-40"),      # invalid dates
        dict(base, siteName="<b>&amp; \"quoted\" 'x'</b>", collector="O'Brien & Sons"),  # HTML-looking text
        dict(base, lat=40, lon=-105.0, elevation=0, gddStart=0.1 + 0.2),             # JS number formatting
    ]
    return cases


@needs_node
def test_label_text_matches_the_website_line_for_line():
    cases = edge_cases()
    theirs = website_label_lines(cases)
    for d, expected in zip(cases, theirs):
        assert ours(d) == expected, json.dumps(d)[:200]


def pdf_text(data: bytes) -> str:
    """Text the PDF shows, via pdftotext if available, else the raw stream
    check is skipped."""
    exe = shutil.which("pdftotext")
    if not exe:
        pytest.skip("pdftotext not installed")
    return subprocess.run([exe, "-layout", "-", "-"], input=data, capture_output=True, check=True).stdout.decode()


def test_label_pdf_is_valid_us_letter_with_our_fonts_only():
    items = [{"data": e["data"]} for e in samples()]
    items[0]["data"]["identification"] = "Photinus pyralis ♂"
    pdf = labels.build_pdf(items, "both")
    assert pdf.startswith(b"%PDF-") and pdf.rstrip().endswith(b"%%EOF")
    assert b"/MediaBox [ 0 0 612 792 ]" in pdf  # US Letter
    fonts = set(re.findall(rb"/BaseFont /([A-Z]{6}\+)?([A-Za-z-]+)", pdf))
    names = {n.decode() for _, n in fonts}
    assert names <= {"Inter-Regular", "Inter-Italic", "Inter-Bold", "DejaVuSans", "DejaVuSans-Oblique"}, names
    assert "DejaVuSans-Oblique" in names  # the ♂ in the italic identification needed the fallback


def test_pdfs_are_reproducible():
    items = [{"data": e["data"]} for e in samples()]
    assert labels.build_pdf(items, "both") == labels.build_pdf(items, "both")


def test_layout_stays_inside_the_margins_and_paginates():
    labels._register()
    items = [{"data": e["data"]} for e in samples()] * 30
    boxes = []
    for it in items:
        boxes.append(labels.Box(labels.label1_lines(it["data"])).measure())
    assert all(b.w <= labels.MAX_W + 1e-6 for b in boxes)
    pdf = labels.build_pdf(items, "both")
    pages = pdf.count(b"/Type /Page\n") or len(re.findall(rb"/Type /Page[^s]", pdf))
    assert pages >= 2


def test_long_words_and_lines_wrap_within_the_box():
    labels._register()
    d = dict(samples()[0]["data"], siteName="Supercalifragilisticexpialidocious" * 4)
    b = labels.Box(labels.label1_lines(d)).measure()
    inner = labels.MAX_W - 2 * (labels.PAD_H + labels.BORDER)
    assert b.w <= labels.MAX_W + 1e-6
    assert all(labels.text_width(ln.text, ln.style, labels.FONT_SIZE) <= inner + 1e-6 for ln in b.wrapped)


def test_which_and_notes():
    items = [{"data": e["data"]} for e in samples()[:2]]
    for which in ("both", "label1", "label2", "notes"):
        assert labels.build_pdf(items, which).startswith(b"%PDF-")
    with pytest.raises(ValueError):
        labels.build_pdf(items, "everything")
    assert labels.build_pdf([], "both").startswith(b"%PDF-")


def test_pdf_contains_the_label_text():
    d = copy.deepcopy(samples()[0]["data"])
    text = pdf_text(labels.build_pdf([{"data": d}], "both"))
    for needle in ("Umstead SP", "14-VI-2025, 9:15 PM", "COLL. A. Eargle", "DET. O. Mettam", "mGDD: 1234.5, Elev. 113 m"):
        assert needle in text, needle
