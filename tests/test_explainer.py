"""Tests for the Explainer Agent fallback and grounding logic."""

from __future__ import annotations

import asyncio

import pytest

from pipeline.explainer import ExplainerAgent
from shared.models import KeyMoment, MatchState, StructuredExplanation


@pytest.fixture
def match_state() -> MatchState:
    return MatchState(
        match_id="match-001",
        session_id="session-001",
        sequence_number=7,
        last_event_id="match-001-000007",
        minute=52,
        second=11,
        score_home=0,
        score_away=2,
        possession_home=0.62,
        field_tilt_home=0.68,
        field_tilt_away=0.32,
        xg_home=0.74,
        xg_away=0.32,
        momentum_home=62,
        momentum_away=38,
        pressure_rate_home=2.0,
        pressure_rate_away=1.0,
        tempo=6.0,
        player_stats={},
    )


@pytest.fixture
def key_moment() -> KeyMoment:
    return KeyMoment(
        moment_id="match-001-km-0001",
        match_id="match-001",
        trigger_event_id="match-001-000007",
        trigger_tags=["red_card"],
        priority_rank=1,
        minute=52,
        second=11,
    )


class TestExplainerAgent:
    def test_cache_skip_returns_existing_explanation_without_llm(self, key_moment, match_state):
        cached = StructuredExplanation(
            theme="pressure_change",
            reason="The red card changed the pressure pattern.",
            numeric_evidence=[],
            evidence_event_ids=[key_moment.trigger_event_id],
        )
        store = {(key_moment.match_id, key_moment.trigger_event_id): cached}
        agent = ExplainerAgent(store=store)

        result = asyncio.run(agent.explain(key_moment, match_state))

        assert result is cached

    def test_hallucinated_number_triggers_regeneration_then_template(self, key_moment, match_state):
        class Client:
            def __init__(self):
                self.calls = 0

            async def structured_output(self, agent_key, messages, schema):
                self.calls += 1
                if self.calls == 1:
                    return {"reason": "The team held 42% of the ball and the lead drifted."}
                return {"reason": "The team held 93% of the ball and the lead drifted."}

        client = Client()
        agent = ExplainerAgent(client=client)
        result = asyncio.run(agent.explain(key_moment, match_state))

        assert result.partially_grounded is False
        assert result.reason in {
            "The red card changed the pressure profile and the balance of the match.",
            "The tension changed the pressure profile and the balance of the match.",
        } or "pressure" in result.reason.lower()

    def test_timeout_fallback_uses_template_and_flags_partial(self, key_moment, match_state):
        class Client:
            async def structured_output(self, agent_key, messages, schema):
                await asyncio.sleep(2)
                return {"reason": "Too slow to be useful."}

        agent = ExplainerAgent(client=Client(), timeout_seconds=0.01)
        result = asyncio.run(agent.explain(key_moment, match_state))

        assert result.partially_grounded is True
        assert "pressure" in result.reason.lower() or "balance" in result.reason.lower()

    def test_default_theme_and_templates_are_loaded(self, key_moment, match_state):
        agent = ExplainerAgent()
        assert "control_vs_chaos" in agent.theme_rules["themes"]
        assert "goal" in agent.templates["tag_overrides"]
        assert agent.theme_rules["default_theme"] == "control_vs_chaos"
