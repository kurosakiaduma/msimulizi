"""
Unit tests for shared/content_safety.py.

Covers:
- MockContentSafetyClient pass (Allowed) path
- MockContentSafetyClient block (Blocked) path, including logged context
- Blocked result carries correct category, severity, and context
- Calls are recorded for assertion
- SafetyResult protocol (Allowed / Blocked are distinguishable)
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from shared.content_safety import (
    Allowed,
    Blocked,
    MockContentSafetyClient,
    SafetyResult,
)


def run(coro):
    return asyncio.run(coro)


class TestMockContentSafetyClientAllowed:
    def test_unknown_text_is_allowed(self):
        mock = MockContentSafetyClient()
        result = run(mock.check("clean text about football", context="key_moment"))
        assert isinstance(result, Allowed)
        assert result.text == "clean text about football"

    def test_allowed_result_is_not_blocked(self):
        mock = MockContentSafetyClient()
        result = run(mock.check("Mamadou shoots from distance!", context="stat_card"))
        assert not isinstance(result, Blocked)

    def test_calls_are_logged(self):
        mock = MockContentSafetyClient()
        run(mock.check("some text", context="correction_edit"))
        assert len(mock.calls) == 1
        assert mock.calls[0]["text"] == "some text"
        assert mock.calls[0]["context"] == "correction_edit"


class TestMockContentSafetyClientBlocked:
    def test_registered_text_is_blocked(self):
        mock = MockContentSafetyClient()
        mock.add_blocked("offensive content", category="Hate", severity=4)
        result = run(mock.check("offensive content", context="key_moment"))
        assert isinstance(result, Blocked)

    def test_blocked_carries_category_and_severity(self):
        mock = MockContentSafetyClient()
        mock.add_blocked("bad words", category="Violence", severity=6)
        result = run(mock.check("bad words", context="stat_card"))
        assert isinstance(result, Blocked)
        assert result.category == "Violence"
        assert result.severity == 6

    def test_blocked_carries_context(self):
        mock = MockContentSafetyClient()
        mock.add_blocked("harmful text", category="SelfHarm", severity=3)
        result = run(mock.check("harmful text", context="correction_edit"))
        assert isinstance(result, Blocked)
        assert result.context == "correction_edit"

    def test_blocked_carries_original_text(self):
        mock = MockContentSafetyClient()
        mock.add_blocked("flagged", category="Sexual", severity=2)
        result = run(mock.check("flagged", context="spotlight_card"))
        assert isinstance(result, Blocked)
        assert result.text == "flagged"

    def test_blocked_is_logged(self, caplog):
        mock = MockContentSafetyClient()
        mock.add_blocked("bad text", category="Hate", severity=5)
        with caplog.at_level(logging.WARNING, logger="shared.content_safety"):
            run(mock.check("bad text", context="key_moment"))
        assert any("blocked" in record.message.lower() for record in caplog.records)

    def test_unlisted_text_is_still_allowed_after_block_registered(self):
        mock = MockContentSafetyClient()
        mock.add_blocked("only this is blocked", category="Hate", severity=4)
        result = run(mock.check("this is fine", context="key_moment"))
        assert isinstance(result, Allowed)

    def test_multiple_blocked_texts_independent(self):
        mock = MockContentSafetyClient()
        mock.add_blocked("text A", category="Hate", severity=4)
        mock.add_blocked("text B", category="Violence", severity=6)
        result_a = run(mock.check("text A", context="ctx"))
        result_b = run(mock.check("text B", context="ctx"))
        assert isinstance(result_a, Blocked)
        assert isinstance(result_b, Blocked)
        assert result_a.category == "Hate"
        assert result_b.category == "Violence"

    def test_calls_recorded_for_both_allowed_and_blocked(self):
        mock = MockContentSafetyClient()
        mock.add_blocked("bad", category="Hate", severity=4)
        run(mock.check("good text", context="a"))
        run(mock.check("bad", context="b"))
        assert len(mock.calls) == 2
        assert mock.calls[0]["text"] == "good text"
        assert mock.calls[1]["text"] == "bad"


class TestSafetyResultTypes:
    def test_allowed_and_blocked_are_distinguishable(self):
        allowed = Allowed(text="ok")
        blocked = Blocked(text="no", category="Hate", severity=4, context="test")
        assert isinstance(allowed, Allowed)
        assert isinstance(blocked, Blocked)
        assert not isinstance(allowed, Blocked)
        assert not isinstance(blocked, Allowed)

    def test_allowed_is_hashable(self):
        """Frozen dataclass — safe to use in sets."""
        a = Allowed(text="hello")
        assert {a}  # no TypeError

    def test_blocked_is_hashable(self):
        b = Blocked(text="x", category="Hate", severity=4, context="ctx")
        assert {b}
