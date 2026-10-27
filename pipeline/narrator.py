"""Narrator Agent for turning a StructuredExplanation into a viewer-facing card.

The Narrator Agent is intentionally thin: it passes a deterministic prompt to the
configured Foundry deployment, validates the returned schema, and raises if the
response violates the project’s guarantees (length limits, Swahili gloss, and
claim consistency). The service is protected by a single-flight lock so
concurrent calls for the same ``(profile_key, moment_id)`` do not duplicate the
LLM request.
"""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from shared.models import Claim, GlossEn, NarrationRequest, NarratorResponse, NumericEvidence, StructuredExplanation
from shared.numbers import NUMBER_RE

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_FEW_SHOT_DIR = _ROOT / "config" / "few_shots"
_DEFAULT_MAX_HEADLINE = 60
_DEFAULT_MAX_BODY = 140

_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "body": {"type": "string"},
        "claims_list": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_type": {"type": "string"},
                    "value": {"type": "string"},
                    "metric": {
                        "type": "string",
                        "description": "Metric name for claim_type=metric; empty string otherwise.",
                    },
                },
                "required": ["claim_type", "value", "metric"],
                "additionalProperties": False,
            },
        },
        "gloss_en": {
            "type": "object",
            "properties": {
                "headline": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["headline", "body"],
            "additionalProperties": False,
        },
    },
    "required": ["headline", "body", "claims_list", "gloss_en"],
    "additionalProperties": False,
}


def _response_schema(language: str) -> dict[str, Any]:
    """Return a strict structured-output schema for the requested language.

    OpenAI strict schemas require every object property to be listed in
    ``required``. The Swahili schema includes the English gloss; English and
    French omit that property entirely rather than sending an optional field.
    """
    if _normalise_language(language) == "sw":
        return deepcopy(_RESPONSE_SCHEMA)
    schema = deepcopy(_RESPONSE_SCHEMA)
    schema["properties"].pop("gloss_en", None)
    schema["required"].remove("gloss_en")
    return schema


def _agent_key_for_language(language: str) -> str:
    """Map a target language to the configured deployment key."""
    if language == "sw":
        return "narrator_sw"
    return "narrator_en_fr"


def _normalise_language(language: str) -> str:
    """Accept common language aliases and normalise them to project codes."""
    value = (language or "en").lower()
    if value in {"sw", "swa", "swahili"}:
        return "sw"
    if value in {"fr", "fra", "french"}:
        return "fr"
    return "en"


def _normalise_mode(mode: str) -> str:
    """Normalise a mode value to the canonical project options."""
    value = (mode or "casual").lower()
    if value in {"analyst", "expert"}:
        return "analyst"
    return "casual"


def _normalise_club_perspective(value: str) -> str:
    """Normalise a perspective value for internal profile keys and prompts."""
    perspective = (value or "neutral").lower()
    if perspective in {"home", "away", "neutral"}:
        return perspective
    return "neutral"


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Load a JSONL few-shot file if one exists."""
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _load_few_shots(language: str, *, path: str | Path | None = None) -> list[dict[str, Any]]:
    """Return the few-shot examples for the requested language."""
    if path is not None:
        rows = _read_jsonl(Path(path))
        if rows:
            return rows

    lang = _normalise_language(language)
    target = _DEFAULT_FEW_SHOT_DIR / f"{lang}.jsonl"
    if target.exists():
        rows = _read_jsonl(target)
        if rows:
            return rows
    if lang == "sw":
        draft = _DEFAULT_FEW_SHOT_DIR / "sw.draft.jsonl"
        rows = _read_jsonl(draft)
        if rows:
            return rows
    return []


def _system_prompt(language: str, *, max_headline: int = _DEFAULT_MAX_HEADLINE, max_body: int = _DEFAULT_MAX_BODY) -> str:
    """Return the project system prompt for the Narrator Agent."""
    if _normalise_language(language) == "sw":
        return (
            "You are the Swahili football radio commentator for a synthetic football match intelligence system. "
            "Write with native Swahili radio style and never translate an English line into Swahili. "
            "Use only facts from the structured explanation, the score, minute, player name, event tags, and the numeric evidence. "
            f"Headline must be <= {max_headline} characters and body must be <= {max_body} characters. "
            "Write every number as digits; copy each numeric display_value verbatim; use score strings like 2-1; do not invent data. "
            "Return JSON only with headline, body, claims_list, and gloss_en. "
            "Every claims_list item must include claim_type, value, and metric; use an empty string for metric on non-metric claims. "
            "Include a faithful English gloss for every Swahili response."
        )
    return (
        "You are the football narrator for a synthetic match intelligence system. "
        "Write in the requested language with compelling radio style, using only the supplied facts. "
        f"Headline must be <= {max_headline} characters and body must be <= {max_body} characters. "
        "Write every number as digits; copy each numeric display_value verbatim; do not invent data. "
        "Return JSON only with headline, body, and claims_list. "
        "Every claims_list item must include claim_type, value, and metric; use an empty string for metric on non-metric claims."
    )


def _coerce_structured_explanation(value: Any) -> StructuredExplanation | None:
    """Convert a dict-based explanation to the canonical dataclass form."""
    if value is None:
        return None
    if isinstance(value, StructuredExplanation):
        return value
    if isinstance(value, dict):
        numeric = value.get("numeric_evidence", [])
        coerced_numeric: list[NumericEvidence] = []
        for entry in numeric:
            if isinstance(entry, NumericEvidence):
                coerced_numeric.append(entry)
            elif isinstance(entry, dict):
                coerced_numeric.append(
                    NumericEvidence(
                        metric=str(entry.get("metric", "")),
                        raw_value=float(entry.get("raw_value", 0.0)),
                        display_value=str(entry.get("display_value", "")),
                        unit=str(entry.get("unit", "integer")),
                    )
                )
        return StructuredExplanation(
            theme=str(value.get("theme", "control_vs_chaos")),
            reason=str(value.get("reason", "")),
            numeric_evidence=coerced_numeric,
            evidence_event_ids=[str(item) for item in value.get("evidence_event_ids", [])],
            partially_grounded=bool(value.get("partially_grounded", False)),
        )
    raise TypeError(f"Unsupported explanation payload: {type(value).__name__}")


def _build_prompt_messages(
    request: NarrationRequest,
    *,
    examples: list[dict[str, Any]] | None = None,
) -> list[dict[str, str]]:
    """Build the OpenAI-style prompt payload for a single narration request."""
    explanation = _coerce_structured_explanation(request.structured_explanation)
    messages: list[dict[str, str]] = [{"role": "system", "content": _system_prompt(request.language)}]
    for example in examples or []:
        example_input = example.get("input")
        example_output = example.get("output")
        if not isinstance(example_input, dict) or not isinstance(example_output, dict):
            continue
        messages.append({"role": "user", "content": json.dumps(example_input, ensure_ascii=False)})
        messages.append({"role": "assistant", "content": json.dumps(example_output, ensure_ascii=False)})

    user_payload = {
        "language": _normalise_language(request.language),
        "mode": _normalise_mode(request.mode),
        "club_perspective": _normalise_club_perspective(request.club_perspective),
        "profile_key": request.profile_key,
        "moment_id": request.moment_id,
        "match_id": request.match_id or request.profile_key.split(".", 1)[0],
        "minute": request.minute,
        "score": request.score,
        "team": request.team,
        "player": request.player,
        "trigger_tags": request.trigger_tags,
        "recap": request.recap,
    }
    if explanation is not None:
        user_payload["reason"] = explanation.reason
        user_payload["numeric_evidence"] = [
            {"metric": item.metric, "display_value": item.display_value, "unit": item.unit}
            for item in explanation.numeric_evidence
        ]
        user_payload["evidence_event_ids"] = explanation.evidence_event_ids
    messages.append({"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)})
    return messages


def _validate_claims(claims: list[dict[str, Any]], request: NarrationRequest) -> None:
    """Ensure claim values are consistent with the request data."""
    if not isinstance(claims, list):
        raise ValueError("claims_list must be a list")
    explanation = _coerce_structured_explanation(request.structured_explanation)

    seen_values: set[str] = set()
    for item in claims:
        if not isinstance(item, dict):
            raise ValueError("claim entries must be dictionaries")
        claim_type = item.get("claim_type")
        value = item.get("value")
        if not isinstance(claim_type, str):
            raise ValueError("Every claim needs a claim_type")
        if not isinstance(value, str):
            raise ValueError("Every claim needs a string value")
        seen_values.add(value)
        if claim_type == "metric":
            metric_name = item.get("metric")
            if not isinstance(metric_name, str) or not metric_name:
                raise ValueError("metric claims require a metric name")
            evidence = explanation.numeric_evidence if explanation else []
            allowed = {entry.display_value for entry in evidence}
            if value not in allowed:
                raise ValueError(f"metric value {value!r} is not present in the numeric evidence")
        elif claim_type == "minute":
            if request.minute is not None and value != str(request.minute):
                raise ValueError(f"minute claim mismatch: {value!r} != {request.minute!r}")
        elif claim_type == "score":
            if request.score is not None and value != request.score:
                raise ValueError(f"score claim mismatch: {value!r} != {request.score!r}")
        elif claim_type == "player":
            if request.player is not None and value != request.player:
                raise ValueError(f"player claim mismatch: {value!r} != {request.player!r}")
        elif claim_type == "event_id":
            evidence_ids = explanation.evidence_event_ids if explanation else []
            if evidence_ids and value not in evidence_ids:
                raise ValueError(f"event_id claim {value!r} is not in the evidence ids")

    if explanation is not None:
        metric_values = {entry.display_value for entry in explanation.numeric_evidence}
        if request.mode.lower() == "analyst" and not any(value in metric_values for value in seen_values):
            raise ValueError("analyst mode narration must include at least one metric claim")


def _validate_response(response: dict[str, Any], request: NarrationRequest) -> dict[str, Any]:
    """Validate the LLM response against project schema and narrative rules."""
    if not isinstance(response, dict):
        raise ValueError("Narrator response must be a dictionary")
    headline = response.get("headline")
    body = response.get("body")
    if not isinstance(headline, str) or not isinstance(body, str):
        raise ValueError("Narrator response must include string headline and body")
    if len(headline) > _DEFAULT_MAX_HEADLINE:
        raise ValueError(f"headline exceeds {_DEFAULT_MAX_HEADLINE} characters: {headline!r}")
    if len(body) > _DEFAULT_MAX_BODY:
        raise ValueError(f"body exceeds {_DEFAULT_MAX_BODY} characters: {body!r}")

    claims = response.get("claims_list")
    if not isinstance(claims, list):
        raise ValueError("Narrator response must include a claims_list")
    _validate_claims(claims, request)

    language = _normalise_language(request.language)
    if language == "sw":
        gloss = response.get("gloss_en")
        if not isinstance(gloss, dict):
            raise ValueError("Swahili narration requires a gloss_en object")
        gloss_headline = gloss.get("headline")
        gloss_body = gloss.get("body")
        if not isinstance(gloss_headline, str) or not isinstance(gloss_body, str):
            raise ValueError("gloss_en must include headline and body strings")
        if len(gloss_headline) > _DEFAULT_MAX_HEADLINE or len(gloss_body) > _DEFAULT_MAX_BODY:
            raise ValueError("gloss_en exceeds the allowed length limits")

    combined_text = f"{headline}\n{body}"
    all_numbers = NUMBER_RE.findall(combined_text)
    claim_values = [claim["value"] for claim in claims if isinstance(claim, dict) and "value" in claim]
    if any(number not in "\n".join(claim_values) for number in all_numbers):
        raise ValueError("Narrator text contains numbers that are not backed by a claim value")
    return response


class NarratorAgent:
    """Narrator Agent that turns a `StructuredExplanation` into final card text."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        few_shot_path: str | Path | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        self.client = client
        self.few_shot_path = few_shot_path
        self.timeout_seconds = timeout_seconds
        self._inflight: dict[tuple[str, str], asyncio.Task[NarratorResponse]] = {}
        self._state_lock = asyncio.Lock()

    async def _await_or_create(self, request: NarrationRequest) -> NarratorResponse:
        """Ensure a single in-flight task exists per ``(profile_key, moment_id)``."""
        key = (request.profile_key, request.moment_id)
        async with self._state_lock:
            task = self._inflight.get(key)
            if task is not None:
                return await task
            task = asyncio.create_task(self._generate_once(request))
            self._inflight[key] = task
        try:
            return await task
        finally:
            async with self._state_lock:
                current = self._inflight.get(key)
                if current is task:
                    self._inflight.pop(key, None)

    async def _call_llm(self, request: NarrationRequest) -> dict[str, Any]:
        """Invoke the configured Foundry deployment for the narration call."""
        if self.client is None:
            raise RuntimeError("NarratorAgent requires a client to call the LLM")
        agent_key = _agent_key_for_language(request.language)
        messages = _build_prompt_messages(
            request,
            examples=_load_few_shots(request.language, path=self.few_shot_path),
        )
        result = self.client.structured_output(agent_key, messages, _response_schema(request.language))
        if asyncio.iscoroutine(result):
            result = await result
        if not isinstance(result, dict):
            raise TypeError(f"Unexpected Narrator response type: {type(result).__name__}")
        return _validate_response(result, request)

    async def _generate_once(self, request: NarrationRequest) -> NarratorResponse:
        """Generate and validate a single narration response."""
        response = await asyncio.wait_for(self._call_llm(request), timeout=self.timeout_seconds)
        raw_claims = response.get("claims_list", [])
        claims: list[Claim] = []
        for claim in raw_claims:
            if not isinstance(claim, dict):
                continue
            claim_type = claim.get("claim_type")
            value = claim.get("value")
            if not isinstance(claim_type, str) or not isinstance(value, str):
                continue
            payload: dict[str, str] = {"claim_type": claim_type, "value": value}
            metric_name = claim.get("metric")
            if isinstance(metric_name, str) and metric_name:
                payload["metric"] = metric_name
            claims.append(Claim(**payload))

        gloss = response.get("gloss_en")
        gloss_en = None
        if isinstance(gloss, dict):
            gloss_en = GlossEn(headline=str(gloss.get("headline", "")), body=str(gloss.get("body", "")))
        return NarratorResponse(
            profile_key=request.profile_key,
            moment_id=request.moment_id,
            headline=str(response["headline"]),
            body=str(response["body"]),
            claims_list=claims,
            gloss_en=gloss_en,
        )

    async def generate(self, request: NarrationRequest) -> NarratorResponse:
        """Generate a `NarratorResponse` for the supplied request, deduplicating concurrent same-key calls."""
        return await self._await_or_create(request)

    def process(self, request: NarrationRequest) -> NarratorResponse:
        """Synchronous helper for callers without async execution."""
        return asyncio.run(self.generate(request))

    async def __call__(self, request: NarrationRequest) -> NarratorResponse:
        """Support direct agent-style invocation in async code paths."""
        return await self.generate(request)


__all__ = [
    "NarratorAgent",
    "_build_prompt_messages",
    "_load_few_shots",
    "_validate_response",
    "_agent_key_for_language",
]
