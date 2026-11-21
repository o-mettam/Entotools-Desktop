"""JavaScript-compatible number helpers.

The backend is a port of the web Worker (JavaScript). Where the Worker's
output depends on JS number semantics, these helpers reproduce them exactly
so the desktop app gives the same answers as entotools.org:

- js_round:       Math.round (halves round toward +infinity; Python's
                  round() uses banker's rounding)
- js_str:         String(number), used in labels like "38.9072, -77.0369"
                  and in upstream query strings
- js_parse_float: parseFloat (leading-prefix parsing: " 38.9abc" -> 38.9)
- utf16_len / utf16_slice: String.length and .slice count UTF-16 code
                  units, not code points
"""
from __future__ import annotations

import math
import re
from decimal import Decimal

NAN = float("nan")


def js_round(x: float) -> float:
    """Math.round: nearest integer, ties toward +infinity."""
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return x
    f = math.floor(x)
    return float(f + 1 if x - f >= 0.5 else f)


def round_to(x: float, places: int) -> float:
    """Math.round(x * 10**places) / 10**places, as the Worker writes it."""
    scale = 10 ** places
    return js_round(x * scale) / scale


def js_str(x) -> str:
    """String(number) per ECMAScript Number::toString (radix 10)."""
    if isinstance(x, bool):
        return "true" if x else "false"
    if isinstance(x, int):
        return str(x)
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "0"  # includes -0
    sign = "-" if x < 0 else ""
    # Shortest round-trip digits (repr) -> digits d1..dk and exponent n,
    # where value = 0.d1..dk * 10**n (ECMAScript's k and n).
    t = Decimal(repr(abs(x))).normalize().as_tuple()
    digits = "".join(map(str, t.digits))
    k = len(digits)
    n = t.exponent + k
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        mant = digits[0] + ("." + digits[1:] if k > 1 else "")
        s = f"{mant}e{'+' if e >= 0 else '-'}{abs(e)}"
    return sign + s


_FLOAT_PREFIX = re.compile(r"[+-]?(?:Infinity|(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)", re.ASCII)


def js_parse_float(v) -> float:
    """parseFloat(v): numbers pass through; strings parse their numeric prefix."""
    if isinstance(v, bool) or v is None:
        return NAN
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return NAN
    m = _FLOAT_PREFIX.match(v.lstrip())
    if not m:
        return NAN
    text = m.group(0)
    if text.endswith("Infinity"):
        return -math.inf if text.startswith("-") else math.inf
    try:
        return float(text)
    except ValueError:  # e.g. "1e" — take the part before the dangling exponent
        return float(re.match(r"[+-]?(?:[0-9]+\.?[0-9]*|\.[0-9]+)", text).group(0))


def js_falsy(v) -> bool:
    """JavaScript truthiness: null/undefined, false, 0, NaN and '' are falsy."""
    if v is None or v is False:
        return True
    if isinstance(v, str):
        return v == ""
    if isinstance(v, (int, float)):
        return v == 0 or (isinstance(v, float) and math.isnan(v))
    return False


def utf16_len(s: str) -> int:
    return len(s.encode("utf-16-le")) // 2


def utf16_slice(s: str, n: int) -> str:
    """s.slice(0, n) counting UTF-16 code units (never splits a character)."""
    if utf16_len(s) <= n:
        return s
    out, used = [], 0
    for ch in s:
        w = 2 if ord(ch) > 0xFFFF else 1
        if used + w > n:
            break
        out.append(ch)
        used += w
    return "".join(out)
