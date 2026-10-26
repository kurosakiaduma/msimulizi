"""Personaliser Agent for matching moments to profile-aware narration.

The Personaliser Agent is the routing layer between the deterministic moment
stream and the LLM-backed narration pipeline. It resolves a club perspective from
`favourite_club`, derives the active profile key, checks the narration cache, and
emits only cache misses as `NarrationRequest` objects. It also validates
spotlight eligibility for a favourite player using derived assist and tackle-won
signals while enforcing the 3-minute spacing rule for non-goal and non-card
moments.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from shared.models import Event, EventType, KeyMoment, NarrationRequest
from shared.profile_key import make_profile_key


@dataclass(frozen=True, init=False)
class SpotlightDecision:
    """Result of the favourite-player spotlight eligibility check.

    An explicit keyword-only __init__ is provided so static checkers (Pylance)
    can see the constructor parameter names and don't raise "no parameter named"
    diagnostics when callers use keyword arguments.
    """

    eligible: bool
    player: str | None = None
    event_id: str | None = None
    team: str | None = None
    reason: str | None = None
    match_seconds: float | None = None

    def __init__(
        self,
        *,
        eligible: bool,
        player: str | None = None,
        event_id: str | None = None,
        team: str | None = None,
        reason: str | None = None,
        match_seconds: float | None = None,
    ) -> None:
        object.__setattr__(self, "eligible", eligible)
        object.__setattr__(self, "player", player)
        object.__setattr__(self, "event_id", event_id)
        object.__setattr__(self, "team", team)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "match_seconds", match_seconds)


class PersonaliserAgent:
    """Build profile-aware narration requests and spotlight decisions."""

    def __init__(
        self,
        *,
        favourite_club: str | None = None,
        favourite_player: str | None = None,
        language: str = "en",
        mode: str = "casual",
        narration_cache: Any | None = None,
    ) -> None:
        self.favourite_club = favourite_club
        self.favourite_player = favourite_player
        self.language = language
        self.mode = mode
        self.narration_cache = narration_cache
        self._profile_updates: dict[str, Any] = {}
        self._last_spotlight_seconds: dict[str, float] = {}

    def update_profile(self, **kwargs: Any) -> dict[str, Any]:
        """Update the current profile settings for subsequent NarrationRequest builds."""
        for key, value in kwargs.items():
            if value is None:
                continue
            if key in {"club", "favourite_club"}:
                self.favourite_club = str(value)
            elif key in {"player", "favourite_player"}:
                self.favourite_player = str(value)
            elif key in {"language", "lang"}:
                self.language = str(value)
            elif key in {"mode"}:
                self.mode = str(value)
            self._profile_updates[key] = value
        return {"favourite_club": self.favourite_club, "favourite_player": self.favourite_player, "language": self.language, "mode": self.mode}

    def derive_club_perspective(self, team: str | None, *, favourite_club: str | None = None) -> str:
        """Map a club name to the project `home` / `away` / `neutral` perspective."""
        preferred_club = (favourite_club or self.favourite_club or "").strip()
        current_team = (team or "").strip()
        if not preferred_club or not current_team:
            return "neutral"
        if current_team.casefold() == preferred_club.casefold():
            return "home"
        return "away"

    def derive_profile_key(self, match_id: str, *, team: str | None = None, language: str | None = None, mode: str | None = None) -> str:
        """Create a canonical Profile Key for the active match and viewer preferences."""
        chosen_language = self._normalise_language(language or self.language)
        chosen_mode = self._normalise_mode(mode or self.mode)
        perspective = self.derive_club_perspective(team)
        return make_profile_key(match_id, chosen_language, chosen_mode, perspective)

    def _normalise_language(self, value: str) -> str:
        cleaned = (value or "en").lower()
        if cleaned in {"sw", "swa", "swahili"}:
            return "sw"
        if cleaned in {"fr", "fra", "french"}:
            return "fr"
        return "en"

    def _normalise_mode(self, value: str) -> str:
        cleaned = (value or "casual").lower()
        if cleaned in {"analyst", "expert"}:
            return "analyst"
        return "casual"

    def _cache_get(self, key: str) -> Any:
        if self.narration_cache is None:
            return None
        if isinstance(self.narration_cache, dict):
            return self.narration_cache.get(key)
        getter = getattr(self.narration_cache, "get", None)
        if callable(getter):
            return getter(key)
        return None

    def _cache_has(self, key: str) -> bool:
        return self._cache_get(key) is not None

    def _build_request(
        self,
        *,
        match_id: str,
        moment: KeyMoment,
        team: str | None = None,
        player: str | None = None,
        trigger_tags: Iterable[str] | None = None,
        explanation: Any = None,
        event: Event | None = None,
    ) -> NarrationRequest:
        """Construct a `NarrationRequest` for a cache miss."""
        perspective = self.derive_club_perspective(team)
        profile_key = make_profile_key(
            match_id,
            self._normalise_language(self.language),
            self._normalise_mode(self.mode),
            perspective,
        )
        return NarrationRequest(
            profile_key=profile_key,
            moment_id=moment.moment_id,
            language=self._normalise_language(self.language),
            mode=self._normalise_mode(self.mode),
            club_perspective=perspective,
            match_id=match_id,
            structured_explanation=getattr(moment, "structured_explanation", None) or explanation,
            minute=moment.minute if moment.minute is not None else (event.minute if event is not None else None),
            score=f"{event.score_home}-{event.score_away}" if event is not None else None,
            team=team or (event.team if event is not None else None),
            player=player or (event.player if event is not None else None),
            trigger_tags=list(trigger_tags or moment.trigger_tags),
            metadata={
                "favourite_club": self.favourite_club,
                "favourite_player": self.favourite_player,
                "source": "personaliser",
            },
        )

    def build_request(self, match_id: str, moment: KeyMoment, *, event: Event | None = None, team: str | None = None, player: str | None = None) -> NarrationRequest | None:
        """Create a request only when the same profile key is not already cached."""
        request_team = team or (event.team if event is not None else None)
        created = self._build_request(
            match_id=match_id,
            moment=moment,
            team=request_team,
            player=player or (event.player if event is not None else None),
            trigger_tags=moment.trigger_tags,
            event=event,
        )
        if self._cache_has(created.profile_key):
            return None
        return created

    def prepare_key_moment(self, moment: KeyMoment, *, event: Event | None = None, match_id: str | None = None) -> NarrationRequest | None:
        """Return a cache-miss request for a KeyMoment, or `None` for a cache hit."""
        resolved_match_id = match_id or moment.match_id or (event.match_id if event is not None else "synthetic-match")
        return self.build_request(resolved_match_id, moment, event=event, team=(event.team if event is not None else None))

    def prepare(self, moment: KeyMoment, *, event: Event | None = None, match_id: str | None = None) -> NarrationRequest | None:
        """Alias for `prepare_key_moment` used by orchestration code."""
        return self.prepare_key_moment(moment, event=event, match_id=match_id)

    def process_key_moment(self, moment: KeyMoment, *, event: Event | None = None, match_id: str | None = None) -> NarrationRequest | None:
        """Compatibility alias used by orchestration code."""
        return self.prepare_key_moment(moment, event=event, match_id=match_id)

    def _match_seconds(self, event: Event) -> float:
        return float((event.minute * 60) + event.second)

    def _assist_for_player(self, player_name: str, event: Event, recent_events: Iterable[Event]) -> bool:
        if event.event_type != EventType.goal:
            return False
        for candidate in recent_events:
            if candidate.match_id != event.match_id:
                continue
            if candidate.team != event.team:
                continue
            if candidate.player == event.player:
                continue
            if candidate.player != player_name:
                continue
            if candidate.event_type != EventType.pass_:
                continue
            if str(candidate.outcome or "").lower() != "success":
                continue
            if self._match_seconds(event) - self._match_seconds(candidate) <= 5.0:
                return True
        return False

    def _spotlight_spacing_ok(self, player_name: str, event: Event) -> bool:
        last_seconds = self._last_spotlight_seconds.get(player_name)
        if last_seconds is None:
            return True
        if event.event_type in {EventType.goal, EventType.card}:
            return True
        return (self._match_seconds(event) - last_seconds) >= 180.0

    def evaluate_spotlight(self, event: Event, *, recent_events: Iterable[Event] | None = None) -> SpotlightDecision | None:
        """Return a spotlight decision when the favourite player is involved in a notable event."""
        if not self.favourite_player:
            return None
        recent = list(recent_events or [])
        player_name = self.favourite_player.strip()
        event_type = event.event_type
        notable = {
            EventType.goal,
            EventType.shot,
            EventType.card,
            EventType.interception,
            EventType.tackle,
        }
        if event.player != player_name and not self._assist_for_player(player_name, event, recent):
            if event_type not in notable:
                return None
        if event.player != player_name and event.event_type == EventType.tackle:
            if not (str(event.outcome or "").lower() == "success" and player_name == event.player):
                return None
        if event.player != player_name and event.event_type == EventType.goal and not self._assist_for_player(player_name, event, recent):
            return None
        if event.player == player_name:
            if event_type not in notable and event_type != EventType.pass_:
                return None
        if event_type == EventType.tackle and str(event.outcome or "").lower() == "success" and event.player == player_name:
            reason = "tackle_won"
        elif event_type == EventType.goal and self._assist_for_player(player_name, event, recent):
            reason = "assist"
        elif event_type in notable and event.player == player_name:
            reason = event_type.value
        else:
            return None
        if not self._spotlight_spacing_ok(player_name, event):
            return None
        self._last_spotlight_seconds[player_name] = self._match_seconds(event)
        return SpotlightDecision(
            eligible=True,
            player=player_name,
            event_id=event.event_id,
            team=event.team,
            reason=reason,
            match_seconds=self._match_seconds(event),
        )

    def process_event(self, event: Event, *, recent_events: Iterable[Event] | None = None) -> SpotlightDecision | None:
        """Compatibility alias for `evaluate_spotlight`."""
        return self.evaluate_spotlight(event, recent_events=recent_events)

    def apply_metric_focus(self, moment: KeyMoment, *, has_metric: bool = False, base_duration_ms: int = 6000) -> tuple[bool, int, int]:
        """Return `(should_emit, priority_rank, duration_ms)` after metric-focus adjustments."""
        priority = int(moment.priority_rank)
        if priority == 1:
            return True, priority, base_duration_ms
        if priority in {4, 5} and not has_metric:
            return False, priority, 0
        if priority in {2, 3}:
            return True, priority, int(base_duration_ms * 0.5)
        return True, priority, base_duration_ms

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Convenience entrypoint for agent-style orchestration."""
        if args and isinstance(args[0], KeyMoment):
            return self.prepare_key_moment(args[0], event=kwargs.get("event"), match_id=kwargs.get("match_id"))
        if args and isinstance(args[0], Event):
            return self.evaluate_spotlight(args[0], recent_events=kwargs.get("recent_events"))
        return None


def derive_club_perspective(team: str | None, *, favourite_club: str | None) -> str:
    """Module-level helper for callers that do not instantiate the agent."""
    agent = PersonaliserAgent(favourite_club=favourite_club)
    return agent.derive_club_perspective(team, favourite_club=favourite_club)


def apply_metric_focus(moment: KeyMoment, *, has_metric: bool = False, base_duration_ms: int = 6000) -> tuple[bool, int, int]:
    """Module-level helper for metric-focus adjustments."""
    return PersonaliserAgent().apply_metric_focus(moment, has_metric=has_metric, base_duration_ms=base_duration_ms)


__all__ = [
    "PersonaliserAgent",
    "SpotlightDecision",
    "apply_metric_focus",
    "derive_club_perspective",
]
