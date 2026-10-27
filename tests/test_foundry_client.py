"""
Unit tests for shared/foundry_client.py and shared/budget.py.

Covers:
- MockFoundryClient FIFO responses and call logging
- MockFoundryClient raises queued exceptions (QuotaExceeded, FoundryTimeoutError)
- BudgetGuard per-minute exhaustion raises QuotaExceeded
- BudgetGuard per-day exhaustion raises QuotaExceeded
- BudgetGuard live_llm_allowed speed rule (4x boundary)
- get_deployment config loading
"""

from __future__ import annotations

import asyncio

import pytest

from shared.foundry_client import (
    FoundryClient,
    FoundryTimeoutError,
    MockFoundryClient,
    QuotaExceeded,
    get_deployment,
)
from shared.budget import BudgetGuard


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# MockFoundryClient
# ---------------------------------------------------------------------------

class TestMockFoundryClient:
    _schema: dict = {"type": "object", "properties": {}}
    _messages = [{"role": "user", "content": "test"}]

    def test_returns_scripted_response(self):
        mock = MockFoundryClient()
        mock.add_response("explainer", {"theme": "control_vs_chaos", "reason": "Test."})
        result = run(mock.structured_output("explainer", self._messages, self._schema))
        assert result["theme"] == "control_vs_chaos"

    def test_fifo_ordering(self):
        mock = MockFoundryClient()
        mock.add_response("explainer", {"seq": 1})
        mock.add_response("explainer", {"seq": 2})
        first = run(mock.structured_output("explainer", self._messages, self._schema))
        second = run(mock.structured_output("explainer", self._messages, self._schema))
        assert first["seq"] == 1
        assert second["seq"] == 2

    def test_independent_queues_per_agent(self):
        mock = MockFoundryClient()
        mock.add_response("explainer", {"agent": "explainer"})
        mock.add_response("verifier", {"agent": "verifier"})
        res_e = run(mock.structured_output("explainer", self._messages, self._schema))
        res_v = run(mock.structured_output("verifier", self._messages, self._schema))
        assert res_e["agent"] == "explainer"
        assert res_v["agent"] == "verifier"

    def test_exhausted_queue_raises_runtime_error(self):
        mock = MockFoundryClient()
        with pytest.raises(RuntimeError, match="no pre-scripted response"):
            run(mock.structured_output("explainer", self._messages, self._schema))

    def test_set_raise_quota_exceeded(self):
        mock = MockFoundryClient()
        mock.set_raise("narrator_sw", QuotaExceeded("429", agent="narrator_sw"))
        with pytest.raises(QuotaExceeded):
            run(mock.structured_output("narrator_sw", self._messages, self._schema))

    def test_set_raise_timeout(self):
        mock = MockFoundryClient()
        mock.set_raise("verifier", FoundryTimeoutError("timeout"))
        with pytest.raises(FoundryTimeoutError):
            run(mock.structured_output("verifier", self._messages, self._schema))

    def test_calls_logged(self):
        mock = MockFoundryClient()
        mock.add_response("explainer", {"ok": True})
        run(mock.structured_output("explainer", self._messages, self._schema))
        assert len(mock.calls) == 1
        assert mock.calls[0]["agent_key"] == "explainer"

    def test_raise_then_success(self):
        """Exception is consumed; subsequent call returns the queued response."""
        mock = MockFoundryClient()
        mock.set_raise("explainer", QuotaExceeded("429"))
        mock.add_response("explainer", {"ok": True})
        with pytest.raises(QuotaExceeded):
            run(mock.structured_output("explainer", self._messages, self._schema))
        result = run(mock.structured_output("explainer", self._messages, self._schema))
        assert result["ok"] is True


# ---------------------------------------------------------------------------
# BudgetGuard — limit exhaustion
# ---------------------------------------------------------------------------

class TestBudgetGuard:
    def test_consume_llm_within_limits(self):
        guard = BudgetGuard(llm_per_minute=10, llm_per_day=100)
        guard.consume_llm(1)  # should not raise
        assert guard.llm_minute_available < 10

    def test_consume_llm_per_minute_exhaustion(self):
        guard = BudgetGuard(llm_per_minute=3, llm_per_day=1000)
        guard.consume_llm(3)
        with pytest.raises(QuotaExceeded, match="llm_per_minute"):
            guard.consume_llm(1)

    def test_consume_llm_per_day_exhaustion(self):
        guard = BudgetGuard(llm_per_minute=1000, llm_per_day=2)
        guard.consume_llm(2)
        with pytest.raises(QuotaExceeded, match="llm_per_day"):
            guard.consume_llm(1)

    def test_consume_speech_per_minute_exhaustion(self):
        guard = BudgetGuard(speech_per_minute=2, speech_per_day=1000)
        guard.consume_speech(2)
        with pytest.raises(QuotaExceeded, match="speech_per_minute"):
            guard.consume_speech(1)

    def test_consume_speech_per_day_exhaustion(self):
        guard = BudgetGuard(speech_per_minute=1000, speech_per_day=1)
        guard.consume_speech(1)
        with pytest.raises(QuotaExceeded, match="speech_per_day"):
            guard.consume_speech(1)

    def test_quota_exceeded_is_foundry_client_exception(self):
        """QuotaExceeded imported from foundry_client should be the same class."""
        guard = BudgetGuard(llm_per_minute=0.5, llm_per_day=1000)
        with pytest.raises(QuotaExceeded):
            guard.consume_llm(1)

    # ------------------------------------------------------------------
    # live_llm_allowed speed rule
    # ------------------------------------------------------------------

    @pytest.mark.parametrize("speed,expected", [
        (0.1, True),
        (1.0, True),
        (4.0, True),   # boundary — exactly 4x is allowed
        (4.01, False),
        (8.0, False),
    ])
    def test_live_llm_allowed_speed_boundary(self, speed, expected):
        guard = BudgetGuard()
        assert guard.live_llm_allowed(speed) is expected


# ---------------------------------------------------------------------------
# get_deployment config loading
# ---------------------------------------------------------------------------

class TestGetDeployment:
    def test_known_agent_key(self):
        dep = get_deployment("explainer")
        assert dep["deployment_name"] == "msimulizi-explainer"
        assert dep["model"] == "gpt-5.4-mini"
        assert dep["api_version"] == "v1"

    def test_all_configured_agents(self):
        for key in (
            "explainer",
            "narrator_sw",
            "narrator_en_fr",
            "verifier",
            "spoken_script_sw",
            "spoken_script_en_fr",
        ):
            dep = get_deployment(key)
            assert "deployment_name" in dep

    def test_unknown_key_raises(self):
        with pytest.raises(KeyError):
            get_deployment("nonexistent_agent")


# ---------------------------------------------------------------------------
# FoundryClient live-client construction
# ---------------------------------------------------------------------------

class TestFoundryClientConstruction:
    def test_uses_v1_endpoint_and_key(self):
        client = FoundryClient(
            "https://example.openai.azure.com/",
            api_key="test-key",
        )
        sdk = client._build_client()

        assert str(sdk.base_url).startswith(
            "https://example.openai.azure.com/openai/v1"
        )
        assert sdk.api_key == "test-key"

        run(client.aclose())

    def test_managed_identity_builds_async_token_provider(self):
        client = FoundryClient("https://example.openai.azure.com/")
        sdk = client._build_client()

        assert client._credential is not None
        assert str(sdk.base_url).startswith(
            "https://example.openai.azure.com/openai/v1"
        )

        run(client.aclose())
        assert client._credential is None
