"""Tests for scripts/compare_swahili_models.py.

The script is intentionally pure and deterministic, so the tests focus on the
validation rules, serialization safety, and offline mock path rather than any
live Azure infrastructure.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_swahili_models.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("compare_swahili_models", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _moment(mod, minute):
    return next(m for m in mod.fixture_moments() if m["minute"] == minute)


def _good_response():
    return {
        "headline": "Kadi nyekundu! Dani Kibiriti atolewa nje",
        "body": "Dakika ya 52, Mto wa Nuru wanabaki pungufu. Kisima City wanamiliki mpira kwa 61%, wako nyuma kwa 0-2.",
        "claims_list": [
            {"claim_type": "player", "value": "Dani Kibiriti"},
            {"claim_type": "minute", "value": "52"},
            {"claim_type": "score", "value": "0-2"},
            {"claim_type": "metric", "value": "61%", "metric": "possession"},
        ],
        "gloss_en": {
            "headline": "Red card! Dani Kibiriti sent off",
            "body": "In the 52nd minute, Mto wa Nuru are a man down. Kisima City hold 61% but trail 0-2.",
        },
    }


class TestFixtureMoments:
    def test_fixture_has_expected_shape(self, mod):
        moments = mod.fixture_moments()
        assert len(moments) == 10
        assert len({m["moment_id"] for m in moments}) == 10
        assert [m["minute"] for m in moments] == sorted(m["minute"] for m in moments)
        assert all(len(m["score"].split("-")) == 2 for m in moments)
        assert {m["mode"] for m in moments} == {"analyst", "casual"}


class TestResponseValidation:
    def test_compliant_response_has_no_issues(self, mod):
        issues, _ = mod.check_response(_moment(mod, 52), _good_response())
        assert issues == []

    def test_number_without_claim_is_flagged(self, mod):
        response = _good_response()
        response["body"] += " Wamebaki 10 uwanjani."
        issues, _ = mod.check_response(_moment(mod, 52), response)
        assert "number_without_claim:10" in issues

    def test_claim_missing_from_text_and_wrong_values_are_flagged(self, mod):
        response = _good_response()
        response["claims_list"][1]["value"] = "53"
        response["claims_list"][3]["value"] = "99%"
        issues, _ = mod.check_response(_moment(mod, 52), response)
        assert "wrong_minute:53" in issues
        assert "metric_not_in_evidence:99%" in issues
        assert "claim_not_in_text:53" in issues

    def test_length_and_analyst_rules_are_enforced(self, mod):
        response = _good_response()
        response["headline"] = "x" * 61
        response["claims_list"] = [c for c in response["claims_list"] if c["claim_type"] != "metric"]
        response["body"] = response["body"].replace(" kwa 61%", "")
        issues, _ = mod.check_response(_moment(mod, 52), response)
        assert "headline_too_long:61" in issues
        assert "analyst_without_metric" in issues

    def test_missing_gloss_is_flagged(self, mod):
        response = _good_response()
        del response["gloss_en"]
        issues, _ = mod.check_response(_moment(mod, 52), response)
        assert issues == ["missing_gloss_en"]

    def test_swahili_number_words_are_reported_as_warnings(self, mod):
        response = _good_response()
        response["body"] = response["body"].replace("pungufu", "pungufu mchezaji mmoja tatu")
        _, warnings = mod.check_response(_moment(mod, 52), response)
        assert "number_word:tatu" in warnings


class TestSerializationAndDrafting:
    def test_dataclass_response_is_normalised_and_written(self, mod, tmp_path):
        @dataclasses.dataclass
        class Result:
            headline: str
            body: str

        plain = mod._as_dict(Result("h", "b"))
        assert plain == {"headline": "h", "body": "b"}

        target = tmp_path / "out.json"
        mod._write_json(target, {"response": Result("h", "b")})
        assert json.loads(target.read_text(encoding="utf-8")) == {"response": {"headline": "h", "body": "b"}}

    def test_failed_serialisation_never_leaves_a_partial_file(self, mod, tmp_path):
        target = tmp_path / "out.json"
        target.write_text('{"keep": true}\n', encoding="utf-8")

        with pytest.raises(TypeError):
            mod._write_json(target, {"response": object()})

        assert json.loads(target.read_text(encoding="utf-8")) == {"keep": True}

    def test_few_shot_files_are_never_overwritten(self, mod, tmp_path, monkeypatch):
        approved = tmp_path / "sw.jsonl"
        draft = tmp_path / "sw.draft.jsonl"
        approved.write_text("native-approved\n", encoding="utf-8")
        monkeypatch.setattr(mod, "FEW_SHOT_PATH", approved)
        monkeypatch.setattr(mod, "FEW_SHOT_DRAFT_PATH", draft)

        mod._ensure_draft_few_shots()

        assert approved.read_text(encoding="utf-8") == "native-approved\n"
        assert not draft.exists()

    def test_draft_few_shots_pass_their_own_checks(self, mod):
        for shot in mod.DRAFT_FEW_SHOTS:
            inp = shot["input"]
            moment = {
                "minute": inp["minute"],
                "score": inp["score"],
                "player": inp["player"],
                "mode": inp["mode"],
                "numeric_evidence": inp["numeric_evidence"],
                "evidence_event_ids": inp["evidence_event_ids"],
            }
            issues, _ = mod.check_response(moment, shot["output"])
            assert issues == [], (inp["player"], issues)


class TestSelectionGuard:
    def test_select_refuses_mock_runs(self, mod, tmp_path, monkeypatch):
        eval_path = tmp_path / "swahili_comparison.json"
        eval_path.write_text(json.dumps({"mode": "mock"}), encoding="utf-8")
        monkeypatch.setattr(mod, "EVAL_PATH", eval_path)

        with pytest.raises(SystemExit):
            mod._select_command("narrator_sw")
