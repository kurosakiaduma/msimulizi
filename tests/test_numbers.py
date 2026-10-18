"""Unit tests for shared/numbers.py — all five canonical number formats."""

import pytest

from shared.numbers import (
    NUMBER_RE,
    fmt_decimal,
    fmt_integer,
    fmt_percent,
    fmt_score,
    fmt_stoppage,
    extract_numbers,
)


class TestFmtPercent:
    def test_ratio_to_percent(self):
        assert fmt_percent(0.62) == "62%"

    def test_already_percent_value(self):
        assert fmt_percent(62.4) == "62%"

    def test_zero(self):
        assert fmt_percent(0.0) == "0%"

    def test_one(self):
        assert fmt_percent(1.0) == "100%"

    def test_with_decimal_places(self):
        assert fmt_percent(0.625, decimal_places=1) == "62.5%"


class TestFmtDecimal:
    def test_default_two_places(self):
        assert fmt_decimal(0.46) == "0.46"

    def test_uses_point_not_comma(self):
        result = fmt_decimal(1.5, decimal_places=1)
        assert "," not in result
        assert result == "1.5"

    def test_zero(self):
        assert fmt_decimal(0.0) == "0.00"


class TestFmtScore:
    def test_normal_score(self):
        assert fmt_score(2, 1) == "2-1"

    def test_nil_nil(self):
        assert fmt_score(0, 0) == "0-0"

    def test_high_score(self):
        assert fmt_score(5, 3) == "5-3"


class TestFmtStoppage:
    def test_stoppage_time(self):
        assert fmt_stoppage(90, 2) == "90+2"

    def test_second_half_stoppage(self):
        assert fmt_stoppage(45, 5) == "45+5"


class TestFmtInteger:
    def test_small_int(self):
        assert fmt_integer(3) == "3"

    def test_zero(self):
        assert fmt_integer(0) == "0"

    def test_large_int_no_separator(self):
        result = fmt_integer(1000)
        assert result == "1000"
        assert "," not in result


class TestNumberRE:
    """NUMBER_RE must match each of the five canonical formats."""

    @pytest.mark.parametrize("text,expected", [
        ("62%", ["62%"]),
        ("0.46", ["0.46"]),
        ("2-1", ["2-1"]),
        ("90+2", ["90+2"]),
        ("3", ["3"]),
    ])
    def test_each_format_matched(self, text, expected):
        assert NUMBER_RE.findall(text) == expected

    def test_stoppage_not_split_into_integers(self):
        # "90+2" must be a single token, not ["90", "2"]
        tokens = NUMBER_RE.findall("90+2")
        assert tokens == ["90+2"]

    def test_score_not_split_into_integers(self):
        tokens = NUMBER_RE.findall("2-1")
        assert tokens == ["2-1"]

    def test_mixed_sentence(self):
        text = "Field tilt 62%, xG 0.46, score 2-1, added time 90+2, shots 3"
        tokens = extract_numbers(text)
        assert "62%" in tokens
        assert "0.46" in tokens
        assert "2-1" in tokens
        assert "90+2" in tokens
        assert "3" in tokens

    def test_no_numbers_returns_empty(self):
        assert NUMBER_RE.findall("no numbers here") == []
