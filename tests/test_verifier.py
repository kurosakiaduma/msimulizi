"""Tests for the Verifier Agent pre-check, retry, and fallback flow."""

from __future__ import annotations

import asyncio

from pipeline.verifier import VerifierAgent
from shared.models import Claim, GlossEn, NarrationRequest, NarratorResponse, NumericEvidence, StructuredExplanation


def make_request(**overrides):
    request = NarrationRequest(
        profile_key="match-001.sw.casual.home",
        moment_id="match-001-km-0001",
        language="sw",
        mode="casual",
        club_perspective="home",
        match_id="match-001",
        minute=88,
        score="2-1",
        team="Ngome United",
        player="Amina Kivuva",
        trigger_tags=["goal"],
        structured_explanation=StructuredExplanation(
            theme="control_vs_chaos",
            reason="Ngome United turned the late push into the winning goal.",
            numeric_evidence=[NumericEvidence(metric="field_tilt_home", raw_value=0.61, display_value="61%", unit="percent")],
            evidence_event_ids=["match-001-000012"],
        ),
    )
    for key, value in overrides.items():
        setattr(request, key, value)
    return request


def make_response(**overrides):
    response = NarratorResponse(
        profile_key="match-001.sw.casual.home",
        moment_id="match-001-km-0001",
        headline="Gool! Amina Kivuva anafunga.",
        body="Dakika ya 88, Amina Kivuva anaiweka Ngome United mbele kwa 2-1; 61% ya nyanja ilikuwa katika udhibiti wake; event_id match-001-000012.",
        claims_list=[
            Claim(claim_type="player", value="Amina Kivuva"),
            Claim(claim_type="minute", value="88"),
            Claim(claim_type="score", value="2-1"),
            Claim(claim_type="metric", value="61%", metric="field_tilt_home"),
            Claim(claim_type="event_id", value="match-001-000012"),
        ],
        gloss_en=GlossEn(headline="Goal! Amina Kivuva scores.", body="In the 88th minute, Amina Kivuva puts Ngome United ahead 2-1 and the team controlled 61%; event_id match-001-000012."),
    )
    for key, value in overrides.items():
        setattr(response, key, value)
    return response


class TestVerifierAgent:
    def test_wrong_player_fails_precheck(self):
        request = make_request()
        response = make_response(claims_list=[
            Claim(claim_type="player", value="Someone Else"),
            Claim(claim_type="minute", value="88"),
            Claim(claim_type="score", value="2-1"),
            Claim(claim_type="metric", value="61%", metric="field_tilt_home"),
            Claim(claim_type="event_id", value="match-001-000012"),
        ])

        result = asyncio.run(VerifierAgent().verify(request, response))

        assert result.verdict == "fail"
        assert "Player claim" in (result.rejection_reason or "")

    def test_wrong_minute_score_metric_and_missing_event_id_fail_precheck(self):
        request = make_request()
        response = make_response(claims_list=[
            Claim(claim_type="player", value="Amina Kivuva"),
            Claim(claim_type="minute", value="89"),
            Claim(claim_type="score", value="2-1"),
            Claim(claim_type="metric", value="62%", metric="field_tilt_home"),
        ])

        result = asyncio.run(VerifierAgent().verify(request, response))

        assert result.verdict == "fail"
        assert result.rejection_reason is not None

    def test_digit_without_matching_claim_fails_precheck(self):
        request = make_request()
        response = make_response(
            headline="Amina Kivuva scores.",
            body="The match is 2-1 and the team controlled 61%.",
            claims_list=[
                Claim(claim_type="player", value="Amina Kivuva"),
            ],
        )

        result = asyncio.run(VerifierAgent().verify(request, response))

        assert result.verdict == "fail"
        assert "Number" in (result.rejection_reason or "")

    def test_claim_absent_from_text_fails_precheck(self):
        request = make_request()
        response = make_response(
            headline="Amina scores.",
            body="In the 88th minute, the team leads.",
            claims_list=[
                Claim(claim_type="player", value="Amina Kivuva"),
                Claim(claim_type="minute", value="88"),
                Claim(claim_type="score", value="2-1"),
            ],
            gloss_en=GlossEn(headline="Amina scores.", body="In the 88th minute, the team leads."),
        )

        result = asyncio.run(VerifierAgent().verify(request, response))

        assert result.verdict == "fail"
        assert "Claim value" in (result.rejection_reason or "")

    def test_length_failure_fails_precheck(self):
        request = make_request()
        response = make_response(headline="A" * 61, body="B" * 141)

        result = asyncio.run(VerifierAgent().verify(request, response))

        assert result.verdict == "fail"
        assert "exceeds" in (result.rejection_reason or "")

    def test_single_retry_then_pass(self):
        class Client:
            def __init__(self):
                self.calls = 0

            async def structured_output(self, *args, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    return {"verdict": "fail", "rejection_reason": "Wrong minute."}
                return {"verdict": "pass", "rejection_reason": None}

        class Narrator:
            async def generate(self, req):
                return make_response()

        agent = VerifierAgent(client=Client(), narrator=Narrator())
        request = make_request()
        response = make_response()

        result = asyncio.run(agent.verify(request, response))

        assert result.verdict == "pass"
        assert result.retry_attempted is True

    def test_double_fail_then_fallback(self):
        class Client:
            async def structured_output(self, *args, **kwargs):
                return {"verdict": "fail", "rejection_reason": "Incorrect."}

        class Narrator:
            async def generate(self, req):
                return make_response(claims_list=[Claim(claim_type="player", value="Amina Kivuva")])

        result = asyncio.run(VerifierAgent(client=Client(), narrator=Narrator()).verify(make_request(), make_response()))

        assert result.verdict == "fail"
        assert result.fallback_line is not None
        assert result.retry_attempted is True

    def test_timeout_then_fallback(self):
        class Client:
            async def structured_output(self, *args, **kwargs):
                await asyncio.sleep(0.2)
                return {"verdict": "pass", "rejection_reason": None}

        agent = VerifierAgent(client=Client(), timeout_seconds=0.01)
        result = asyncio.run(agent.verify(make_request(), make_response()))

        assert result.verdict == "fail"
        assert result.rejection_reason == "Verifier model timed out after 3 seconds."
        assert result.fallback_line is not None
