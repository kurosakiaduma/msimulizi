"""
shared/models.py — canonical data models for the Msimulizi pipeline.

All agents and the renderer import from here so the type contract is
centralised and change-resistant.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# EventType
# ---------------------------------------------------------------------------

class EventType(str, Enum):
    # Control / lifecycle events
    metadata = "metadata"          # first event in every match stream
    period_start = "period_start"  # kick-off or second-half start
    half_time = "half_time"        # half-time whistle
    full_time = "full_time"        # final whistle

    # Play events
    pass_ = "pass"
    goal = "goal"
    shot = "shot"
    tackle = "tackle"
    interception = "interception"
    foul = "foul"
    card = "card"
    corner = "corner"
    free_kick = "free_kick"
    goal_kick = "goal_kick"
    throw_in = "throw_in"
    save = "save"
    clearance = "clearance"
    dribble = "dribble"
    pressure = "pressure"
    carry = "carry"
    duel = "duel"
    substitution = "substitution"
    offside = "offside"
    error = "error"


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------

@dataclass
class Event:
    """A single discrete occurrence in the match stream."""

    event_id: str          # "{match_id}-{sequence:06d}"
    match_id: str
    period: int            # 1 or 2
    minute: int
    second: int
    team: str
    player: str
    event_type: EventType
    x_start: float         # 0–100 pitch coordinate
    y_start: float
    x_end: float | None
    y_end: float | None
    outcome: str | None    # e.g. "success", "fail"
    xg: float | None       # shots only; computed by shared.xg.compute_xg
    is_header: bool        # shots only
    is_penalty: bool       # shots only
    pressure: bool         # whether the player was under pressure
    score_home: int
    score_away: int


# ---------------------------------------------------------------------------
# PlayerStats
# ---------------------------------------------------------------------------

@dataclass
class PlayerStats:
    """Accumulated statistics for one player within a session."""

    player: str
    team: str
    passes_attempted: int = 0
    passes_completed: int = 0
    pass_distance_total: float = 0.0    # metres (pitch units)
    shots: int = 0
    shots_on_target: int = 0
    xg_total: float = 0.0
    goals: int = 0
    tackles_attempted: int = 0
    tackles_won: int = 0
    interceptions: int = 0
    cards: int = 0                      # yellow + red combined


# ---------------------------------------------------------------------------
# MatchState  (one in-memory instance per active session)
# ---------------------------------------------------------------------------

@dataclass
class MatchState:
    """Rolling aggregate maintained by the Interpreter Agent."""

    match_id: str
    session_id: str
    sequence_number: int          # event sequence number (deterministic per match)
    last_event_id: str            # f"{match_id}-{sequence_number:06d}"
    minute: int
    second: int
    score_home: int
    score_away: int
    possession_home: float        # 0.0–1.0 share
    field_tilt_home: float        # share of home passes in opp final third
    field_tilt_away: float        # share of away passes in opp final third
    xg_home: float
    xg_away: float
    momentum_home: float          # 0–100
    momentum_away: float          # 0–100
    pressure_rate_home: float     # pressure events per minute (5-min window)
    pressure_rate_away: float
    tempo: float                  # events per minute (5-min window)
    player_stats: dict[str, PlayerStats] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# NumericEvidence
# ---------------------------------------------------------------------------

@dataclass
class NumericEvidence:
    """A single metric-value pair attached to a StructuredExplanation."""

    metric: str           # e.g. "field_tilt_home"
    raw_value: float      # e.g. 0.62
    display_value: str    # canonical ASCII, e.g. "62%"
    unit: str             # "percent" | "decimal" | "score" | "stoppage" | "integer"


# ---------------------------------------------------------------------------
# StructuredExplanation
# ---------------------------------------------------------------------------

@dataclass
class StructuredExplanation:
    """Language-neutral internal object attached to every KeyMoment."""

    theme: str                                   # "control_vs_chaos" | "pressure_change" | "rhythm_shift"
    reason: str                                  # single English sentence from the Explainer LLM
    numeric_evidence: list[NumericEvidence] = field(default_factory=list)
    evidence_event_ids: list[str] = field(default_factory=list)
    partially_grounded: bool = False


# ---------------------------------------------------------------------------
# KeyMoment
# ---------------------------------------------------------------------------

@dataclass
class KeyMoment:
    """A detected occurrence of high significance in the match."""

    moment_id: str              # "{match_id}-km-{sequence:04d}"
    match_id: str
    trigger_event_id: str
    trigger_tags: list[str]     # e.g. ["goal", "lead_change"]
    priority_rank: int          # 1 (highest) – 5
    minute: int
    second: int
    structured_explanation: StructuredExplanation | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Claim  (entry in the Claims List of a NarratorResponse)
# ---------------------------------------------------------------------------

@dataclass
class Claim:
    """A single verifiable fact stated in a NarratorResponse."""

    claim_type: str    # "player" | "minute" | "score" | "metric" | "event_id"
    value: str         # for metric claims: the display_value from NumericEvidence
    metric: str | None = None    # populated only when claim_type == "metric"


# ---------------------------------------------------------------------------
# GlossEn
# ---------------------------------------------------------------------------

@dataclass
class GlossEn:
    """Faithful English translation of a Swahili NarratorResponse."""

    headline: str    # ≤ 60 chars
    body: str        # ≤ 140 chars


# ---------------------------------------------------------------------------
# NarratorResponse
# ---------------------------------------------------------------------------

@dataclass
class NarrationRequest:
    """A single narration task for a match moment or recap card."""

    profile_key: str
    moment_id: str
    language: str = "en"
    mode: str = "casual"
    club_perspective: str = "neutral"
    match_id: str = ""
    structured_explanation: StructuredExplanation | None = None
    minute: int | None = None
    score: str | None = None
    team: str | None = None
    player: str | None = None
    trigger_tags: list[str] = field(default_factory=list)
    recap: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NarratorResponse:
    """Structured object returned by the Narrator Agent per Profile Key."""

    profile_key: str        # "match_id.lang.mode.club_perspective"
    moment_id: str
    headline: str           # ≤ 60 chars in target language
    body: str               # ≤ 140 chars in target language
    claims_list: list[Claim] = field(default_factory=list)
    gloss_en: GlossEn | None = None    # required for language == "sw"
    generated_at: datetime = field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# OverlayCard  (written to Cosmos DB by the Renderer)
# ---------------------------------------------------------------------------

@dataclass(init=False)
class OverlayCard:
    """
    Machine-readable timed JSON card for broadcast lower-third overlays.

    ``display_from`` is NOT stored here; it is computed per session by the
    WebSocket gateway from ``match_seconds`` and the SessionClock.
    """

    card_id: str
    match_id: str
    profile_key: str
    match_clock: dict[str, Any]      # {"period": int, "minute": int, "second": int}
    match_seconds: float             # absolute match position in seconds (pipeline clock)
    display_duration_ms: int
    card_type: str                   # "goal" | "key_moment" | "stat" | "player_spotlight" | "recap"
    priority: int
    player_ref: str | None
    team_ref: str
    text: dict[str, dict[str, str]]  # {"sw": {"headline": ..., "body": ...}, "en": {...}, "fr": {...}}
    gloss_en: GlossEn | None         # for Swahili cards
    structured_explanation: StructuredExplanation | None
    evidence_event_ids: list[str] = field(default_factory=list)
    stat_payload: dict[str, Any] = field(default_factory=dict)
    audio_url: str | None = None
    synthetic_ai_generated: bool = True
    from_bundle: bool = False

    def __init__(
        self,
        *,
        card_id: str,
        match_id: str,
        profile_key: str,
        match_clock: dict[str, Any],
        match_seconds: float,
        display_duration_ms: int,
        card_type: str,
        priority: int,
        player_ref: str | None,
        team_ref: str,
        text: dict[str, dict[str, str]],
        gloss_en: GlossEn | None,
        structured_explanation: StructuredExplanation | None,
        evidence_event_ids: list[str] | None = None,
        stat_payload: dict[str, Any] | None = None,
        audio_url: str | None = None,
        synthetic_ai_generated: bool = True,
        from_bundle: bool = False,
    ) -> None:
        self.card_id = card_id
        self.match_id = match_id
        self.profile_key = profile_key
        self.match_clock = match_clock
        self.match_seconds = match_seconds
        self.display_duration_ms = display_duration_ms
        self.card_type = card_type
        self.priority = priority
        self.player_ref = player_ref
        self.team_ref = team_ref
        self.text = text
        self.gloss_en = gloss_en
        self.structured_explanation = structured_explanation
        self.evidence_event_ids = evidence_event_ids if evidence_event_ids is not None else []
        self.stat_payload = stat_payload if stat_payload is not None else {}
        self.audio_url = audio_url
        self.synthetic_ai_generated = synthetic_ai_generated
        self.from_bundle = from_bundle
