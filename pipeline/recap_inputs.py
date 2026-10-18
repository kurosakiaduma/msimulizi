"""Deterministic recap inputs for the Narrator Agent.

The full-time recap is assembled from the match summary rather than from a fresh
LLM prompt. This keeps recap generation stable, traceable, and consistent with
`StructuredExplanation` objects already used elsewhere in the pipeline.
"""

from __future__ import annotations

from typing import Any, Sequence

from shared.models import KeyMoment, MatchState, NarrationRequest, NumericEvidence, StructuredExplanation
from shared.numbers import fmt_percent, fmt_score


def _score_display(score_home: int, score_away: int) -> str:
    """Return the canonical score text used across the pipeline."""
    return fmt_score(score_home, score_away)


def build_recap_explanation(
    match_state: MatchState,
    key_moments: Sequence[KeyMoment] | None = None,
) -> StructuredExplanation:
    """Build a grounded, deterministic recap explanation at full time."""
    moments = list(key_moments or [])
    home_score = int(match_state.score_home)
    away_score = int(match_state.score_away)
    score_text = _score_display(home_score, away_score)
    xg_home = float(match_state.xg_home)
    xg_away = float(match_state.xg_away)
    possession_home = float(match_state.possession_home)
    event_ids = [moment.trigger_event_id for moment in moments[:3]]
    evidence = [
        NumericEvidence(
            metric="score",
            raw_value=float(home_score - away_score),
            display_value=score_text,
            unit="score",
        ),
        NumericEvidence(
            metric="xg_home",
            raw_value=xg_home,
            display_value=f"{xg_home:.2f}",
            unit="decimal",
        ),
        NumericEvidence(
            metric="xg_away",
            raw_value=xg_away,
            display_value=f"{xg_away:.2f}",
            unit="decimal",
        ),
        NumericEvidence(
            metric="possession_home",
            raw_value=possession_home,
            display_value=fmt_percent(possession_home),
            unit="percent",
        ),
    ]
    reason = (
        f"Full time ended with a {score_text} scoreline. "
        f"The match delivered {len(moments)} key moments and the home side ended with {fmt_percent(possession_home)} possession. "
        f"xG settled at {xg_home:.2f} to {xg_away:.2f}."
    )
    return StructuredExplanation(
        theme="rhythm_shift",
        reason=reason,
        numeric_evidence=evidence,
        evidence_event_ids=event_ids,
        partially_grounded=False,
    )


def build_recap_request(
    *,
    profile_key: str,
    moment_id: str,
    language: str,
    mode: str,
    club_perspective: str,
    match_id: str,
    match_state: MatchState,
    key_moments: Sequence[KeyMoment] | None = None,
    **metadata: Any,
) -> NarrationRequest:
    """Construct a recap narration request from match state and moment history."""
    request = NarrationRequest(
        profile_key=profile_key,
        moment_id=moment_id,
        language=language,
        mode=mode,
        club_perspective=club_perspective,
        match_id=match_id,
        structured_explanation=build_recap_explanation(match_state, key_moments),
        minute=match_state.minute,
        score=_score_display(match_state.score_home, match_state.score_away),
        team="match",
        player=None,
        trigger_tags=["full_time"],
        recap=True,
        metadata=dict(metadata),
    )
    return request


make_recap_explanation = build_recap_explanation
make_recap_request = build_recap_request


__all__ = [
    "build_recap_explanation",
    "build_recap_request",
    "make_recap_explanation",
    "make_recap_request",
]
