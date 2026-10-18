"""Unit tests for shared/profile_key.py — round-trip and validation."""

import pytest

from shared.profile_key import make_profile_key, parse_profile_key, ParsedProfileKey


VALID_ARGS = ("abc123", "sw", "casual", "home")


class TestMakeProfileKey:
    def test_produces_dot_separated_string(self):
        key = make_profile_key(*VALID_ARGS)
        assert key == "abc123.sw.casual.home"

    def test_all_languages(self):
        for lang in ("sw", "en", "fr"):
            key = make_profile_key("m1", lang, "analyst", "neutral")
            assert key.split(".")[1] == lang

    def test_all_modes(self):
        for mode in ("analyst", "casual"):
            key = make_profile_key("m1", "en", mode, "neutral")
            assert key.split(".")[2] == mode

    def test_all_club_perspectives(self):
        for cp in ("home", "away", "neutral"):
            key = make_profile_key("m1", "en", "analyst", cp)
            assert key.split(".")[3] == cp

    def test_invalid_language_raises(self):
        with pytest.raises(ValueError):
            make_profile_key("m1", "de", "analyst", "home")

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError):
            make_profile_key("m1", "en", "expert", "home")

    def test_invalid_club_perspective_raises(self):
        with pytest.raises(ValueError):
            make_profile_key("m1", "en", "analyst", "both")

    def test_empty_match_id_raises(self):
        with pytest.raises(ValueError):
            make_profile_key("", "en", "analyst", "home")

    def test_match_id_with_dot_raises(self):
        with pytest.raises(ValueError):
            make_profile_key("abc.123", "en", "analyst", "home")


class TestParseProfileKey:
    def test_round_trip(self):
        key = make_profile_key(*VALID_ARGS)
        parsed = parse_profile_key(key)
        assert parsed == ParsedProfileKey(
            match_id="abc123",
            language="sw",
            mode="casual",
            club_perspective="home",
        )

    def test_round_trip_all_18_combinations(self):
        """All 18 valid Profile Key combinations survive a round trip."""
        for lang in ("sw", "en", "fr"):
            for mode in ("analyst", "casual"):
                for cp in ("home", "away", "neutral"):
                    key = make_profile_key("matchXYZ", lang, mode, cp)
                    parsed = parse_profile_key(key)
                    assert parsed.match_id == "matchXYZ"
                    assert parsed.language == lang
                    assert parsed.mode == mode
                    assert parsed.club_perspective == cp

    def test_too_few_parts_raises(self):
        with pytest.raises(ValueError):
            parse_profile_key("abc123.sw.casual")

    def test_too_many_parts_raises(self):
        with pytest.raises(ValueError):
            parse_profile_key("abc123.sw.casual.home.extra")

    def test_invalid_language_in_key_raises(self):
        with pytest.raises(ValueError):
            parse_profile_key("abc123.de.casual.home")
