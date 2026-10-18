"""Tests covering the Narrator Agent and recap generation."""

from __future__ import annotations

import asyncio

import pytest

from pipeline.narrator import NarratorAgent
from pipeline.recap_inputs import build_recap_request
from shared.foundry_client import MockFoundryClient
from shared.models import MatchState, NarrationRequest


@pytest.fixture
def match_state() -> MatchState:
    return MatchState(
        match_id="match-001",
        session_id="session-001",
        sequence_number=12,
        last_event_id="match-001-000012",
        minute=90,
        second=0,
        score_home=2,
        score_away=1,
        possession_home=0.58,
        field_tilt_home=0.61,
        field_tilt_away=0.39,
        xg_home=1.77,
        xg_away=0.82,
        momentum_home=63,
        momentum_away=37,
        pressure_rate_home=1.6,
        pressure_rate_away=1.1,
        tempo=5.2,
        player_stats={},
    )


@pytest.fixture
def narration_request(match_state: MatchState) -> NarrationRequest:
    return NarrationRequest(
        profile_key="match-001.sw.casual.home",
        moment_id="match-001-km-0001",
        language="sw",
        mode="casual",
        club_perspective="home",
        match_id=match_state.match_id,
        minute=88,
        score="2-1",
        team="Ngome United",
        player="Amina Kivuva",
        trigger_tags=["goal", "late_game"],
        structured_explanation={
            "theme": "control_vs_chaos",
            "reason": "Ngome United turned the late push into the winning goal.",
            "numeric_evidence": [{"metric": "field_tilt", "raw_value": 0.61, "display_value": "61%", "unit": "percent"}],
            "evidence_event_ids": ["match-001-000012"],
        },
    )


class TestNarratorAgent:
    def test_generate_validates_and_returns_response(self, narration_request: NarrationRequest) -> None:
        mock = MockFoundryClient()
        mock.add_response(
            "narrator_sw",
            {
                "headline": "Gooool! Amina Kivuva anavaa Ngome United",
                "body": "Dakika ya 88, Amina Kivuva anaiweka Ngome United mbele kwa 2-1.",
                "claims_list": [
                    {"claim_type": "player", "value": "Amina Kivuva"},
                    {"claim_type": "minute", "value": "88"},
                    {"claim_type": "score", "value": "2-1"},
                    {"claim_type": "metric", "value": "61%", "metric": "field_tilt"},
                ],
                "gloss_en": {
                    "headline": "Goal! Amina Kivuva wins it for Ngome United",
                    "body": "In the 88th minute, Amina Kivuva puts Ngome United ahead 2-1.",
                },
            },
        )
        agent = NarratorAgent(client=mock)

        result = asyncio.run(agent.generate(narration_request))

        assert result.profile_key == narration_request.profile_key
        assert result.moment_id == narration_request.moment_id
        assert result.gloss_en is not None
        assert result.claims_list[3].metric == "field_tilt"

    def test_single_flight_returns_one_llm_call_for_same_key(self, narration_request: NarrationRequest) -> None:
        mock = MockFoundryClient()
        mock.add_response(
            "narrator_sw",
            {
                "headline": "Gooool! Amina Kivuva anavaa Ngome United",
                "body": "Dakika ya 88, Amina Kivuva anaiweka Ngome United mbele kwa 2-1.",
                "claims_list": [
                    {"claim_type": "player", "value": "Amina Kivuva"},
                    {"claim_type": "minute", "value": "88"},
                    {"claim_type": "score", "value": "2-1"},
                    {"claim_type": "metric", "value": "61%", "metric": "field_tilt"},
                ],
                "gloss_en": {
                    "headline": "Goal! Amina Kivuva wins it for Ngome United",
                    "body": "In the 88th minute, Amina Kivuva puts Ngome United ahead 2-1.",
                },
            },
        )
        agent = NarratorAgent(client=mock)

        async def _run() -> None:
            await asyncio.gather(agent.generate(narration_request), agent.generate(narration_request))

        asyncio.run(_run())

        assert len(mock.calls) == 1

    def test_recap_request_builds_summary(self, match_state: MatchState) -> None:
        req = build_recap_request(
            profile_key="match-001.sw.casual.home",
            moment_id="match-001-km-9999",
            language="sw",
            mode="casual",
            club_perspective="home",
            match_id=match_state.match_id,
            match_state=match_state,
            key_moments=[],
        )

        assert req.recap is True
        assert req.structured_explanation is not None
        assert "Full time ended" in req.structured_explanation.reason

    def test_length_limits_are_enforced(self, narration_request: NarrationRequest) -> None:
        mock = MockFoundryClient()
        mock.add_response(
            "narrator_sw",
            {
                "headline": "A" * 61,
                "body": "Too long.",
                "claims_list": [{"claim_type": "score", "value": "2-1"}],
                "gloss_en": {"headline": "A" * 61, "body": "Too long."},
            },
        )
        agent = NarratorAgent(client=mock)

        with pytest.raises(ValueError):
            asyncio.run(agent.generate(narration_request))
