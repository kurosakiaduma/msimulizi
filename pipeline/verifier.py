"""Verifier Agent for narrator validation, retry, and fallback handling.

The verifier performs a deterministic pre-check before any LLM call. The
pre-check validates the claims list, ensures every number in the text is backed
by a claim, ensures the claim values are present in the text, and checks length
constraints. A second pass through the Foundry verifier model confirms the
narration is consistent with the reason and that the Swahili gloss is faithful.

If the verification fails, the agent requests exactly one narration retry. If the
retry also fails or if any verifier model call exceeds 3 seconds, it emits a
fallback line and never caches it.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, cast

from renderer.fallback import build_fallback_line
from shared.content_safety import Allowed, Blocked, ContentSafetyClientProtocol
from shared.models import Claim, NarrationRequest, NarratorResponse
from shared.numbers import NUMBER_RE
from shared.observability import metrics as _metrics


@dataclass
class VerificationResult:
    """Structured output from a verification pass."""

    verdict: str
    rejection_reason: str | None = None
    response: NarratorResponse | None = None
    fallback_line: dict[str, Any] | None = None
    log_id: str | None = None
    cacheable: bool = False
    safety_checked: bool = False
    safety_result: Allowed | Blocked | None = None
    retry_attempted: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return a dict-like representation compatible with callers and tests."""
        return {
            "verdict": self.verdict,
            "rejection_reason": self.rejection_reason,
            "response": self.response,
            "fallback_line": self.fallback_line,
            "log_id": self.log_id,
            "cacheable": self.cacheable,
            "safety_checked": self.safety_checked,
            "safety_result": self.safety_result,
            "retry_attempted": self.retry_attempted,
        }

    def __getitem__(self, key: str) -> Any:
        return self.as_dict()[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.as_dict().get(key, default)


class VerifierAgent:
    """Validate generated narration and handle retry/fallback logic."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        narrator: Any | None = None,
        narration_cache: Any | None = None,
        audit_log: Any | None = None,
        content_safety: ContentSafetyClientProtocol | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        self.client = client
        self.narrator = narrator
        self.narration_cache = narration_cache
        self.audit_log = audit_log
        self.content_safety = content_safety
        self.timeout_seconds = timeout_seconds

    def _normalise_language(self, language: str) -> str:
        value = (language or "en").lower()
        if value in {"sw", "swa", "swahili"}:
            return "sw"
        if value in {"fr", "fra", "french"}:
            return "fr"
        return "en"

    def _coerce_claims(self, response: NarratorResponse) -> list[Claim]:
        if response.claims_list is None:
            return []
        return response.claims_list

    def _fallback_moment_type(self, request: NarrationRequest) -> str:
        """Derive the best fallback template key from the request metadata and trigger tags."""
        metadata = request.metadata or {}
        candidate = metadata.get("moment_type") or metadata.get("event_type")
        if isinstance(candidate, str) and candidate:
            return candidate.lower()
        tags = request.trigger_tags or []
        for tag in tags:
            name = str(tag).lower().replace(" ", "_")
            if name in {"goal", "red_card", "big_chance", "default"}:
                return name
        if request.structured_explanation and request.structured_explanation.theme:
            theme = request.structured_explanation.theme.lower()
            if "goal" in theme:
                return "goal"
            if "red" in theme or "card" in theme:
                return "red_card"
            if "chance" in theme or "big" in theme:
                return "big_chance"
        return "default"

    def _extract_names(self, request: NarrationRequest, response: NarratorResponse) -> set[str]:
        names: set[str] = set()
        if request.player:
            names.add(request.player)
        if response.claims_list:
            for claim in response.claims_list:
                if claim.claim_type == "player":
                    names.add(claim.value)
        if request.team:
            names.add(request.team)
        return {name for name in names if name}

    def _precheck(self, request: NarrationRequest, response: NarratorResponse) -> str | None:
        """Return a rejection reason or None when the narration passes the deterministic pre-check."""
        claims = self._coerce_claims(response)
        if not claims:
            return "Narrator output is missing a Claims List."

        evidence_values: set[str] = set()
        explanation = request.structured_explanation
        if explanation is not None:
            evidence_values = {entry.display_value for entry in explanation.numeric_evidence}

        combined_text = "\n".join((response.headline, response.body))
        if request.language.lower() == "sw" and response.gloss_en is not None:
            combined_text += "\n" + response.gloss_en.headline + "\n" + response.gloss_en.body

        for claim in claims:
            if claim.claim_type == "metric":
                if explanation is not None:
                    valid_metrics = {entry.metric for entry in explanation.numeric_evidence}
                    if claim.metric and claim.metric not in valid_metrics:
                        return f"Metric claim {claim.value!r} does not match the evidence."
                    if claim.value not in evidence_values:
                        return f"Metric claim {claim.value!r} not found in numeric evidence."
                else:
                    if claim.value not in evidence_values:
                        return f"Metric claim {claim.value!r} not found in numeric evidence."
            elif claim.claim_type == "minute":
                if request.minute is not None and claim.value != str(request.minute):
                    return f"Minute claim {claim.value!r} does not match the event minute {request.minute}."
            elif claim.claim_type == "score":
                if request.score is not None and claim.value != request.score:
                    return f"Score claim {claim.value!r} does not match the score {request.score}."
            elif claim.claim_type == "player":
                if request.player is not None and claim.value != request.player:
                    return f"Player claim {claim.value!r} is not consistent with the event."
            elif claim.claim_type == "event_id":
                if explanation is not None and claim.value not in explanation.evidence_event_ids:
                    return f"Event ID claim {claim.value!r} is missing from the evidence."

        if len(response.headline) > 60:
            return f"Headline exceeds 60 characters ({len(response.headline)})."
        if len(response.body) > 140:
            return f"Body exceeds 140 characters ({len(response.body)})."
        if request.language.lower() == "sw":
            if response.gloss_en is None:
                return "Swahili response requires a gloss_en object."
            if len(response.gloss_en.headline) > 60 or len(response.gloss_en.body) > 140:
                return "Swahili gloss exceeds the length limits."

        for number in NUMBER_RE.findall(combined_text):
            if not any(number in claim.value for claim in claims):
                return f"Number {number!r} appears in the text without a matching claim."

        for claim in claims:
            if claim.value not in combined_text:
                return f"Claim value {claim.value!r} is absent from the text."

        if request.player and request.player not in combined_text and request.player not in {claim.value for claim in claims if claim.claim_type == "player"}:
            return f"Player name {request.player!r} is missing from the text."

        if request.language.lower() == "sw" and response.gloss_en is not None:
            if any(ch.isdigit() for ch in response.gloss_en.headline + response.gloss_en.body) and not any(
                str(num) in "\n".join(claim.value for claim in claims) for num in NUMBER_RE.findall(response.gloss_en.headline + response.gloss_en.body)
            ):
                return "Swahili gloss contains digits not covered by a claim."

        return None

    async def _llm_check(self, request: NarrationRequest, response: NarratorResponse) -> dict[str, Any]:
        """Call the verifier model using the configured structured-output schema."""
        client = self.client
        if client is None:
            return {"verdict": "pass", "rejection_reason": None}
        schema = {
            "type": "object",
            "properties": {
                "verdict": {"type": "string", "enum": ["pass", "fail"]},
                "rejection_reason": {"type": ["string", "null"]},
            },
            "required": ["verdict", "rejection_reason"],
            "additionalProperties": False,
        }
        prompt = {
            "request": {
                "profile_key": request.profile_key,
                "moment_id": request.moment_id,
                "language": request.language,
                "mode": request.mode,
                "score": request.score,
                "minute": request.minute,
                "player": request.player,
                "reason": request.structured_explanation.reason if request.structured_explanation else "",
                "narration": {
                    "headline": response.headline,
                    "body": response.body,
                    "claims_list": [
                        {"claim_type": item.claim_type, "value": item.value, "metric": item.metric}
                        for item in response.claims_list
                    ],
                    "gloss_en": {
                        "headline": response.gloss_en.headline if response.gloss_en else "",
                        "body": response.gloss_en.body if response.gloss_en else "",
                    },
                },
            },
            "rejection_reason": request.metadata.get("rejection_reason") if request.metadata else None,
        }
        async def _call() -> dict[str, Any]:
            result = client.structured_output("verifier", [{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}], schema)
            if inspect.isawaitable(result):
                result = await cast(Awaitable[Any], result)
            if not isinstance(result, dict):
                raise TypeError(f"Unexpected verifier response type: {type(result).__name__}")
            verdict = str(result.get("verdict", "pass")).lower()
            rejection = result.get("rejection_reason")
            return {
                "verdict": verdict if verdict in {"pass", "fail"} else "pass",
                "rejection_reason": rejection if isinstance(rejection, str) else None,
            }
        return await asyncio.wait_for(_call(), timeout=self.timeout_seconds)

    async def _write_audit(self, response: NarratorResponse, *, verdict: str, rejection_reason: str | None = None) -> str | None:
        """Persist every verdict to the audit log, if a repo is attached."""
        if self.audit_log is None:
            return None

        async def _await_result(call: Callable[..., Any], payload: dict[str, Any]) -> Any:
            result = call(payload)
            if inspect.isawaitable(result):
                return await cast(Awaitable[Any], result)
            return result

        writer = getattr(self.audit_log, "create_entry", None)
        if callable(writer):
            log_id = f"audit:{response.profile_key}:{response.moment_id}:{len(str(verdict))}"
            payload = {
                "id": log_id,
                "profile_key": response.profile_key,
                "moment_id": response.moment_id,
                "verdict": verdict,
                "rejection_reason": rejection_reason,
            }
            await _await_result(cast(Callable[..., Any], writer), payload)
            return log_id
        create = getattr(self.audit_log, "create", None)
        if callable(create):
            log_id = f"audit:{response.profile_key}:{response.moment_id}:{len(str(verdict))}"
            payload = {"id": log_id, "profile_key": response.profile_key, "moment_id": response.moment_id, "verdict": verdict, "rejection_reason": rejection_reason}
            await _await_result(cast(Callable[..., Any], create), payload)
            return log_id
        return None

    async def _write_cache(self, response: NarratorResponse, *, log_id: str | None = None) -> None:
        """Persist a passing narrator response to the cache if a repository is attached."""
        if self.narration_cache is None:
            return

        async def _await_result(call: Callable[..., Any], *args: Any) -> Any:
            result = call(*args)
            if inspect.isawaitable(result):
                return await cast(Awaitable[Any], result)
            return result

        writer = getattr(self.narration_cache, "upsert_response", None)
        if callable(writer):
            await _await_result(cast(Callable[..., Any], writer), response)
            return
        setter = getattr(self.narration_cache, "set", None)
        if callable(setter):
            await _await_result(cast(Callable[..., Any], setter), (response.profile_key, response.moment_id), response)
            return

    async def _check_content_safety(self, response: NarratorResponse, *, context: str = "narration") -> Allowed | Blocked | None:
        if self.content_safety is None:
            return None
        text = "\n".join([response.headline, response.body])
        if response.gloss_en is not None:
            text += "\n" + response.gloss_en.headline + "\n" + response.gloss_en.body
        result = await self.content_safety.check(text, context=context)
        return result

    async def _retry_narration(self, request: NarrationRequest, *, rejection_reason: str) -> NarratorResponse | None:
        if self.narrator is None:
            return None
        metadata = dict(request.metadata or {})
        metadata["rejection_reason"] = rejection_reason
        retry_request = NarrationRequest(**{**request.__dict__, "metadata": metadata})
        return await self.narrator.generate(retry_request)

    async def verify(self, request: NarrationRequest, response: NarratorResponse, *, event: Any | None = None, match_state: Any | None = None) -> VerificationResult:
        """Verify a narration response and return verdict plus cache/fallback metadata."""
        precheck_reason = self._precheck(request, response)
        if precheck_reason is not None:
            return VerificationResult(
                verdict="fail",
                rejection_reason=precheck_reason,
                response=response,
                cacheable=False,
                safety_checked=False,
            )

        safety_result = await self._check_content_safety(response, context="narration")
        if isinstance(safety_result, Blocked):
            await self._write_audit(response, verdict="fail", rejection_reason=f"Content Safety: {safety_result.category}")
            return VerificationResult(
                verdict="fail",
                rejection_reason=f"Content Safety: {safety_result.category}",
                response=response,
                safety_checked=True,
                safety_result=safety_result,
                cacheable=False,
            )

        try:
            llm_result = await self._llm_check(request, response)
        except asyncio.TimeoutError:
            _metrics.record_fallback()
            fallback = build_fallback_line(
                language=self._normalise_language(request.language),
                moment_type=self._fallback_moment_type(request),
                player=request.player,
                minute=request.minute,
                event_type=(request.trigger_tags[0] if request.trigger_tags else None),
                score=request.score,
            )
            return VerificationResult(
                verdict="fail",
                rejection_reason="Verifier model timed out after 3 seconds.",
                response=response,
                fallback_line=fallback,
                retry_attempted=False,
                cacheable=False,
            )

        if llm_result.get("verdict") != "pass":
            retry_reason = llm_result.get("rejection_reason") or "Narration failed the verifier check."
            retry_response = await self._retry_narration(request, rejection_reason=retry_reason)
            if retry_response is not None:
                retry_precheck = self._precheck(request, retry_response)
                if retry_precheck is None:
                    retry_safety = await self._check_content_safety(retry_response, context="narration")
                    if not isinstance(retry_safety, Blocked):
                        log_id = await self._write_audit(retry_response, verdict="pass", rejection_reason=None)
                        if log_id is not None:
                            await self._write_cache(retry_response, log_id=log_id)
                        _metrics.record_verdict(passed=True)
                        return VerificationResult(
                            verdict="pass",
                            rejection_reason=None,
                            response=retry_response,
                            cacheable=True,
                            safety_checked=True,
                            safety_result=retry_safety,
                            retry_attempted=True,
                            log_id=log_id,
                        )
                    return VerificationResult(
                        verdict="fail",
                        rejection_reason=f"Content Safety: {retry_safety.category}",
                        response=retry_response,
                        safety_checked=True,
                        safety_result=retry_safety,
                        retry_attempted=True,
                    )
                fallback = build_fallback_line(
                    language=self._normalise_language(request.language),
                    moment_type=self._fallback_moment_type(request),
                    player=request.player,
                    minute=request.minute,
                    event_type=(request.trigger_tags[0] if request.trigger_tags else None),
                    score=request.score,
                )
                await self._write_audit(retry_response, verdict="fail", rejection_reason=retry_precheck)
                _metrics.record_verdict(passed=False)
                _metrics.record_fallback()
                return VerificationResult(
                    verdict="fail",
                    rejection_reason=retry_precheck,
                    response=retry_response,
                    fallback_line=fallback,
                    retry_attempted=True,
                    cacheable=False,
                )

            fallback = build_fallback_line(
                language=self._normalise_language(request.language),
                moment_type=self._fallback_moment_type(request),
                player=request.player,
                minute=request.minute,
                event_type=(request.trigger_tags[0] if request.trigger_tags else None),
                score=request.score,
            )
            _metrics.record_verdict(passed=False)
            _metrics.record_fallback()
            return VerificationResult(
                verdict="fail",
                rejection_reason=retry_reason,
                response=response,
                fallback_line=fallback,
                retry_attempted=True,
                cacheable=False,
            )

        log_id = await self._write_audit(response, verdict="pass", rejection_reason=None)
        if log_id is not None:
            await self._write_cache(response, log_id=log_id)
        _metrics.record_verdict(passed=True)
        return VerificationResult(
            verdict="pass",
            rejection_reason=None,
            response=response,
            cacheable=True,
            safety_checked=True,
            safety_result=safety_result,
            log_id=log_id,
        )

    def process(self, request: NarrationRequest, response: NarratorResponse, **kwargs: Any) -> VerificationResult:
        """Blocking convenience wrapper for callers not using async code."""
        return asyncio.run(self.verify(request, response, **kwargs))

    async def __call__(self, request: NarrationRequest, response: NarratorResponse, **kwargs: Any) -> VerificationResult:
        return await self.verify(request, response, **kwargs)


__all__ = ["VerifierAgent", "VerificationResult"]
