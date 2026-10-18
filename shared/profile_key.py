"""
shared/profile_key.py — Profile Key construction and parsing.

A Profile Key is the cache key for a narrated Overlay Card:
    "{match_id}.{language}.{mode}.{club_perspective}"

Dots are used as separators because they are safe in filenames,
URL path segments, and Cosmos DB partition keys.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ParsedProfileKey:
    match_id: str
    language: str          # "sw" | "en" | "fr"
    mode: str              # "analyst" | "casual"
    club_perspective: str  # "home" | "away" | "neutral"


def make_profile_key(
    match_id: str,
    language: str,
    mode: str,
    club_perspective: str,
) -> str:
    """
    Build a dot-separated Profile Key from its four components.

    Example:
        make_profile_key("abc123", "sw", "casual", "home")
        # → "abc123.sw.casual.home"
    """
    if not match_id:
        raise ValueError("match_id must not be empty")
    if "." in match_id:
        raise ValueError("match_id must not contain dots")
    if language not in ("sw", "en", "fr"):
        raise ValueError(f"language must be 'sw', 'en', or 'fr'; got {language!r}")
    if mode not in ("analyst", "casual"):
        raise ValueError(f"mode must be 'analyst' or 'casual'; got {mode!r}")
    if club_perspective not in ("home", "away", "neutral"):
        raise ValueError(
            f"club_perspective must be 'home', 'away', or 'neutral'; got {club_perspective!r}"
        )
    return f"{match_id}.{language}.{mode}.{club_perspective}"


def parse_profile_key(profile_key: str) -> ParsedProfileKey:
    """
    Parse a dot-separated Profile Key back into its four components.

    Raises ValueError if the key does not have exactly four dot-separated
    parts or if any component fails validation.
    """
    parts = profile_key.split(".")
    if len(parts) != 4:
        raise ValueError(
            f"Profile Key must have exactly 4 dot-separated parts; got {len(parts)}: {profile_key!r}"
        )
    match_id, language, mode, club_perspective = parts
    # Re-use make_profile_key for validation, then return the parsed object.
    make_profile_key(match_id, language, mode, club_perspective)
    return ParsedProfileKey(
        match_id=match_id,
        language=language,
        mode=mode,
        club_perspective=club_perspective,
    )
