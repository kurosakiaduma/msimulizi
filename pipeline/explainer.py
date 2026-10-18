"""Explainer Agent for a deterministic, grounded Key Moment reason.

The Explainer chooses a theme and evidence set before invoking the LLM. It then
verifies that every numeric token in the generated reason appears in the selected
numeric evidence. When the LLM path fails or times out, the agent falls back to a
local deterministic template reason so the pipeline keeps moving without stale
moments.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import yaml

from shared.models import KeyMoment, MatchState, NumericEvidence, StructuredExplanation
from shared.numbers import NUMBER_RE, fmt_decimal, fmt_percent, fmt_score

_DEFAULT_RULES_PATH = Path(__file__).resolve().parents[1] / "explainer" / "theme_rules.yaml"
_DEFAULT_TEMPLATES_PATH = Path(__file__).resolve().parents[1] / "explainer" / "templates.yaml"


def _stable_theme_name(value: str | None) -> str:
    """Normalise a theme key so YAML and runtime names stay consistent."""
    if value is None:
        return "control_vs_chaos"
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def load_theme_rules(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load the deterministic Explainer theme rules from YAML."""
    path = Path(config_path) if config_path is not None else _DEFAULT_RULES_PATH
    fallback = {
        "default_theme": "control_vs_chaos",
        "themes": {
            "control_vs_chaos": {"possession_gap": 0.10, "field_tilt_gap": 0.10, "momentum_gap": 15.0},
            "pressure_change": {"pressure_shift": 0.10},
            "rhythm_shift": {"tempo_shift": 2.0},
        },
    }
    if not path.exists():
        return fallback

    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    if not isinstance(loaded, dict):
        return fallback

    themes = loaded.get("themes")
    if not isinstance(themes, dict):
        themes = fallback["themes"]
    merged = fallback["themes"].copy()
    for name, config in themes.items():
        merged[_stable_theme_name(str(name))] = config if isinstance(config, dict) else {}

    default_theme = _stable_theme_name(str(loaded.get("default_theme", fallback["default_theme"])))
    return {"default_theme": default_theme, "themes": merged}


def load_templates(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load the local deterministic template reasons for fallback use."""
    path = Path(config_path) if config_path is not None else _DEFAULT_TEMPLATES_PATH
    fallback = {
        "default": {
            "control_vs_chaos": "The control pattern shifted and changed the game state.",
            "pressure_change": "The pressure pattern shifted and changed the balance of the match.",
            "rhythm_shift": "The tempo shifted and the rhythm of the match changed.",
        },
        "tag_overrides": {
            "goal": "The goal changed the scoreline and shifted the momentum.",
            "red_card": "The red card changed the pressure profile and the game state.",
            "big_chance": "The big chance created a decisive opportunity and turned the pressure.",
            "lead_change": "The lead changed hands and the match swung direction.",
            "momentum_swing": "The momentum swing changed the rhythm and direction of the game.",
            "player_milestone": "The player milestone reinforced the team's control of the match.",
            "full_time": "Full time ended the phase of play and settled the match.",
        },
    }
    if not path.exists():
        return fallback

    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}

    if not isinstance(loaded, dict):
        return fallback

    default_value = loaded.get("default")
    override_value = loaded.get("tag_overrides")
    default_dict: dict[str, Any] = dict(fallback["default"])
    if isinstance(default_value, dict):
        default_dict.update({str(key): value for key, value in default_value.items()})
    override_dict: dict[str, Any] = dict(fallback["tag_overrides"])
    if isinstance(override_value, dict):
        override_dict.update({str(key): value for key, value in override_value.items()})
    return {"default": default_dict, "tag_overrides": override_dict}


def _format_display_value(metric: str, raw_value: float | int) -> str:
    """Convert a numeric metric to the canonical display string used by the project."""
    metric_name = str(metric).lower()
    if any(token in metric_name for token in ("possession", "field_tilt", "pressure_rate", "tempo")):
        return fmt_percent(float(raw_value) / 100.0 if float(raw_value) > 1.0 else float(raw_value))
    if "momentum" in metric_name:
        return str(int(round(float(raw_value))))
    if "score" in metric_name:
        return str(raw_value)
    if "xg" in metric_name:
        return fmt_decimal(float(raw_value), decimal_places=2)
    if "minute" in metric_name:
        return str(int(round(float(raw_value))))
    return fmt_decimal(float(raw_value), decimal_places=2) if abs(float(raw_value)) < 1.0 else str(int(round(float(raw_value))))


def _coerce_numeric_evidence(metric: str, raw_value: float | int, *, unit: str | None = None) -> NumericEvidence:
    """Build a canonical NumericEvidence record from a metric name and raw value."""
    metric_name = str(metric)
    numeric_value = float(raw_value)
    if unit is None:
        if any(token in metric_name.lower() for token in ("possession", "field_tilt", "pressure_rate")):
            unit = "percent"
        elif "momentum" in metric_name.lower() or "minute" in metric_name.lower() or "score" in metric_name.lower():
            unit = "integer"
        else:
            unit = "decimal"
    if unit == "percent":
        display = fmt_percent(numeric_value if numeric_value <= 1.0 else numeric_value)
    elif unit == "score":
        display = fmt_score(int(numeric_value), 0)
    else:
        display = _format_display_value(metric_name, numeric_value)
    return NumericEvidence(metric=metric_name, raw_value=numeric_value, display_value=display, unit=unit)


def _theme_from_tags(key_moment: KeyMoment) -> str:
    """Pick a stable theme to use when the trigger tags already imply a likely narrative."""
    tags = {str(tag).strip().lower() for tag in key_moment.trigger_tags}
    if "red_card" in tags:
        return "pressure_change"
    if "goal" in tags or "lead_change" in tags or "big_chance" in tags:
        return "control_vs_chaos"
    if "momentum_swing" in tags:
        return "rhythm_shift"
    if "player_milestone" in tags:
        return "rhythm_shift"
    return "control_vs_chaos"


def _select_theme(key_moment: KeyMoment, match_state: MatchState, rules: dict[str, Any]) -> str:
    """Use deterministic rules to select the explanation theme for a key moment."""
    tags_theme = _theme_from_tags(key_moment)
    if tags_theme in rules.get("themes", {}):
        return tags_theme

    scope = rules.get("themes", {}).get("control_vs_chaos", {})
    momentum_gap = abs(float(match_state.momentum_home) - float(match_state.momentum_away))
    possession_gap = abs(float(match_state.possession_home) - 0.5)
    field_tilt_gap = abs(float(match_state.field_tilt_home) - float(match_state.field_tilt_away))
    if momentum_gap >= float(scope.get("momentum_gap", 15.0)) or possession_gap >= float(scope.get("possession_gap", 0.10)) or field_tilt_gap >= float(scope.get("field_tilt_gap", 0.10)):
        return "control_vs_chaos"

    pressure_shift = abs(float(match_state.pressure_rate_home) - float(match_state.pressure_rate_away))
    if pressure_shift >= float(rules.get("themes", {}).get("pressure_change", {}).get("pressure_shift", 0.10)):
        return "pressure_change"

    tempo_shift = abs(float(match_state.tempo) - 0.0)
    if tempo_shift >= float(rules.get("themes", {}).get("rhythm_shift", {}).get("tempo_shift", 2.0)):
        return "rhythm_shift"

    default = rules.get("default_theme", "control_vs_chaos")
    return _stable_theme_name(default)


def _candidate_evidence(key_moment: KeyMoment, match_state: MatchState) -> list[tuple[str, float, str | None]]:
    """Return up to three evidence metrics from the current match state."""
    candidates: list[tuple[str, float, str | None]] = []
    candidates.append(("possession_home", float(match_state.possession_home), "percent"))
    candidates.append(("field_tilt_home", float(match_state.field_tilt_home), "percent"))
    candidates.append(("momentum_home", float(match_state.momentum_home), "integer"))
    candidates.append(("momentum_away", float(match_state.momentum_away), "integer"))
    candidates.append(("tempo", float(match_state.tempo), "decimal"))
    if match_state.score_home != match_state.score_away:
        candidates.append(("score", float(match_state.score_home - match_state.score_away), "score"))
    if key_moment.trigger_tags:
        candidates.append(("trigger_tags", float(len(key_moment.trigger_tags)), "integer"))
    return candidates[:3]


def _template_reason_for(key_moment: KeyMoment, theme: str, templates: dict[str, Any]) -> str:
    """Return a deterministic template reason for the active key moment."""
    tags = {str(tag).strip().lower().replace("-", "_") for tag in key_moment.trigger_tags}
    for tag in sorted(tags):
        if tag in templates.get("tag_overrides", {}):
            return str(templates["tag_overrides"][tag])
    return str(templates.get("default", {}).get(theme, templates.get("default", {}).get("control_vs_chaos", "The match pivoted at a decisive point.")))


def _encode_prompt(theme: str, evidence: list[NumericEvidence], event_ids: list[str]) -> str:
    """Build the deterministic prompt sent to the Explainer LLM."""
    metrics = "; ".join(f"{item.metric}={item.display_value}" for item in evidence)
    ids = ", ".join(event_ids)
    return (
        "Write a single-sentence reason in English using ONLY the supplied evidence. "
        f"Theme: {theme}. "
        f"Evidence: {metrics}. "
        f"Evidence event IDs: {ids}. "
        "Keep it to one sentence, grounded in the evidence, and avoid any numbers not listed in the evidence."
    )


def _numbers_in_reason(reason: str) -> list[str]:
    """Return all numeric tokens in a generated reason using the project regex."""
    return [match.group(0) for match in NUMBER_RE.finditer(reason)]


def _reason_is_grounded(reason: str, evidence: list[NumericEvidence]) -> bool:
    """Return True when every matched number in the reason is present in the evidence."""
    values = {item.display_value for item in evidence}
    numbers = _numbers_in_reason(reason)
    return all(number in values for number in numbers)


class ExplainerAgent:
    """Deterministic explanation generator with LLM and template fallback paths."""

    def __init__(
        self,
        *,
        client: Any | None = None,
        store: Any | None = None,
        theme_rules_path: str | Path | None = None,
        templates_path: str | Path | None = None,
        timeout_seconds: float = 1.0,
    ) -> None:
        self.client = client
        self.store = store
        self.timeout_seconds = timeout_seconds
        self.theme_rules = load_theme_rules(theme_rules_path)
        self.templates = load_templates(templates_path)

    def _lookup_store(self, match_id: str, trigger_event_id: str) -> StructuredExplanation | None:
        """Read an existing explanation from the configured store if present."""
        if self.store is None:
            return None

        lookup = getattr(self.store, "get", None)
        if callable(lookup):
            candidate = lookup((match_id, trigger_event_id))
            if isinstance(candidate, StructuredExplanation):
                return candidate
            if isinstance(candidate, dict):
                return StructuredExplanation(**candidate)

        if isinstance(self.store, dict):
            candidate = self.store.get((match_id, trigger_event_id))
            if isinstance(candidate, StructuredExplanation):
                return candidate
            if isinstance(candidate, dict):
                return StructuredExplanation(**candidate)

        fetcher = None
        for method_name in ("get_explanation", "get_structured_explanation", "fetch_explanation", "get_by_event"):
            fetcher = getattr(self.store, method_name, None)
            if callable(fetcher):
                candidate = fetcher(match_id, trigger_event_id)
                if isinstance(candidate, StructuredExplanation):
                    return candidate
                if isinstance(candidate, dict):
                    return StructuredExplanation(**candidate)
                break
        return None

    def _persist_store(self, match_id: str, trigger_event_id: str, explanation: StructuredExplanation) -> None:
        """Persist an explanation to the configured store if possible."""
        if self.store is None:
            return

        setter = getattr(self.store, "set", None)
        if callable(setter):
            setter((match_id, trigger_event_id), explanation)
            return

        if isinstance(self.store, dict):
            self.store[(match_id, trigger_event_id)] = explanation
            return

        for method_name in ("save_explanation", "store_explanation", "upsert_explanation"):
            writer = getattr(self.store, method_name, None)
            if callable(writer):
                writer(match_id, trigger_event_id, explanation)
                return

    def _build_explanation(self, key_moment: KeyMoment, match_state: MatchState, *, theme: str | None = None, template_reason: str | None = None) -> StructuredExplanation:
        """Create a grounded explanation object from the match state and key moment."""
        selected_theme = _stable_theme_name(theme or _select_theme(key_moment, match_state, self.theme_rules))
        evidence = [
            _coerce_numeric_evidence(name, value, unit=unit)
            for name, value, unit in _candidate_evidence(key_moment, match_state)
        ]
        if not evidence:
            evidence = [
                NumericEvidence(metric="score_gap", raw_value=float(match_state.score_home - match_state.score_away), display_value=str(int(match_state.score_home - match_state.score_away)), unit="integer")
            ]
        event_ids = [key_moment.trigger_event_id]
        reason = template_reason or _template_reason_for(key_moment, selected_theme, self.templates)
        return StructuredExplanation(
            theme=selected_theme,
            reason=reason,
            numeric_evidence=evidence,
            evidence_event_ids=event_ids,
            partially_grounded=False,
        )

    async def _call_llm(self, prompt: str) -> str:
        """Invoke the configured Foundry client for the Explainer LLM call."""
        if self.client is None:
            raise RuntimeError("ExplainerAgent requires a client to call the LLM")

        schema = {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
            "required": ["reason"],
            "additionalProperties": False,
        }
        result = self.client.structured_output("explainer", [{"role": "user", "content": prompt}], schema)
        if inspect.isawaitable(result):
            result = await result
        if not isinstance(result, dict):
            raise TypeError(f"Unexpected Explainer response type: {type(result).__name__}")
        reason = result.get("reason")
        if not isinstance(reason, str):
            raise ValueError("Explainer response did not include a string 'reason'.")
        return reason

    async def explain(self, key_moment: KeyMoment, match_state: MatchState) -> StructuredExplanation:
        """Return the structured explanation for a key moment, using the cache when available."""
        cached = self._lookup_store(key_moment.match_id, key_moment.trigger_event_id)
        if cached is not None:
            return cached

        theme = _select_theme(key_moment, match_state, self.theme_rules)
        evidence = [
            _coerce_numeric_evidence(name, value, unit=unit)
            for name, value, unit in _candidate_evidence(key_moment, match_state)
        ]
        event_ids = [key_moment.trigger_event_id]
        if not evidence:
            evidence = [
                NumericEvidence(metric="score_gap", raw_value=float(match_state.score_home - match_state.score_away), display_value=str(int(match_state.score_home - match_state.score_away)), unit="integer")
            ]

        reason: str | None = None
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                prompt = _encode_prompt(theme, evidence, event_ids)
                reason = await asyncio.wait_for(self._call_llm(prompt), timeout=self.timeout_seconds)
                if reason and _reason_is_grounded(reason, evidence):
                    explanation = StructuredExplanation(
                        theme=theme,
                        reason=reason,
                        numeric_evidence=evidence,
                        evidence_event_ids=event_ids,
                        partially_grounded=False,
                    )
                    self._persist_store(key_moment.match_id, key_moment.trigger_event_id, explanation)
                    return explanation
                last_error = ValueError(f"Reason contains numbers not found in evidence: {reason!r}")
            except asyncio.TimeoutError as exc:
                last_error = exc
                break
            except Exception as exc:  # pragma: no cover - left for real client failures
                last_error = exc
                if attempt == 1:
                    break

        template_reason = _template_reason_for(key_moment, theme, self.templates)
        explanation = StructuredExplanation(
            theme=theme,
            reason=template_reason,
            numeric_evidence=evidence,
            evidence_event_ids=event_ids,
            partially_grounded=isinstance(last_error, asyncio.TimeoutError),
        )
        self._persist_store(key_moment.match_id, key_moment.trigger_event_id, explanation)
        return explanation

    def process(self, key_moment: KeyMoment, match_state: MatchState) -> StructuredExplanation:
        """Blocking convenience wrapper for callers that do not use async patterns."""
        return asyncio.run(self.explain(key_moment, match_state))

    def generate(self, key_moment: KeyMoment, match_state: MatchState) -> StructuredExplanation:
        """Compatibility alias for deterministic orchestration code."""
        return self.process(key_moment, match_state)

    async def __call__(self, key_moment: KeyMoment, match_state: MatchState) -> StructuredExplanation:
        """Support direct agent-style invocation in async code paths."""
        return await self.explain(key_moment, match_state)


__all__ = [
    "ExplainerAgent",
    "_select_theme",
    "load_templates",
    "load_theme_rules",
    "_template_reason_for",
    "_reason_is_grounded",
]
