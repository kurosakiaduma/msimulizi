"""
shared/numbers.py — canonical number-format helpers and NUMBER_RE.

All five canonical ASCII formats used throughout the Msimulizi pipeline:

    percent      "62%"       (integer, no space before %)
    decimal      "0.46"      (decimal point, not comma)
    score        "2-1"       (hyphen, no spaces)
    stoppage     "90+2"      (plus sign, no spaces)
    integer      "3"         (plain digits, no separators)

NUMBER_RE matches any of the five formats.  The Explainer uses it to verify
that every number token in the generated reason appears as a display_value in
numeric_evidence.  The Verifier's Text Consistency Check uses it to scan
headline, body, and gloss_en.

Order in the alternation matters: longer/more-specific patterns come first so
that "90+2" is not captured as two separate integers, and "2-1" is not split.
"""

from __future__ import annotations

import re

# Matches all five canonical formats.  Longer patterns are anchored first.
NUMBER_RE = re.compile(r"\d+\+\d+|\d+-\d+|\d+\.\d+|\d+%|\d+")


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_percent(value: float, *, decimal_places: int = 0) -> str:
    """
    Format a 0–1 ratio (or 0–100 value) as a percentage string.

    Values ≤ 1.0 are treated as ratios and multiplied by 100.
    Values > 1.0 are treated as already-percentage numbers.

    Examples:
        fmt_percent(0.62)  → "62%"
        fmt_percent(62.4)  → "62%"
        fmt_percent(0.625, decimal_places=1)  → "62.5%"
    """
    pct = value * 100 if value <= 1.0 else value
    if decimal_places == 0:
        return f"{int(round(pct))}%"
    return f"{pct:.{decimal_places}f}%"


def fmt_decimal(value: float, *, decimal_places: int = 2) -> str:
    """
    Format a float as a decimal string using a decimal point (never a comma).

    Example:
        fmt_decimal(0.46)  → "0.46"
        fmt_decimal(1.5, decimal_places=1)  → "1.5"
    """
    return f"{value:.{decimal_places}f}"


def fmt_score(home: int, away: int) -> str:
    """
    Format a score pair as "home-away".

    Example:
        fmt_score(2, 1)  → "2-1"
    """
    return f"{home}-{away}"


def fmt_stoppage(base_minute: int, added: int) -> str:
    """
    Format a stoppage-time minute as "base+added".

    Example:
        fmt_stoppage(90, 2)  → "90+2"
    """
    return f"{base_minute}+{added}"


def fmt_integer(value: int) -> str:
    """
    Format an integer (no thousands separator).

    Example:
        fmt_integer(3)  → "3"
    """
    return str(value)


def extract_numbers(text: str) -> list[str]:
    """
    Return all number tokens found in *text* using NUMBER_RE.

    Tokens appear in the order they are found in the string.
    """
    return NUMBER_RE.findall(text)
