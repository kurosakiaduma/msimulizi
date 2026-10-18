"""Compare candidate Swahili Narrator deployments on a fixed set of moments.

Workflow:

1. ``python scripts/compare_swahili_models.py``
   Calls every candidate deployment with the same prompts, runs deterministic
   quality checks, writes ``evals/swahili_comparison.json`` and a blind review
   sheet ``evals/swahili_review.csv`` for a native speaker.
2. A native speaker fills in the rating columns of the sheet.
3. ``python scripts/compare_swahili_models.py --score``
   Combines the ratings with the automated checks and latency.
4. ``python scripts/compare_swahili_models.py --select narrator_sw``
   Records the decision in ``config/foundry_models.yaml``. This only works for
   a live run whose candidate has been fully rated.

``--mock`` runs the whole pipeline offline against ``MockFoundryClient`` to test
the plumbing. Mock output is marked ``"mode": "mock"``, never produces a review
sheet, and can never be selected.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import dataclasses
import inspect
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from random import Random
from typing import Any, cast

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared.foundry_client import FoundryClient, MockFoundryClient, QuotaExceeded  # noqa: E402

try:  # the project's canonical tokenizer, when available
    from shared.numbers import NUMBER_RE as NUMBER_RE  # noqa: E402
except ImportError:  # pragma: no cover - fallback keeps the script usable standalone
    NUMBER_RE = re.compile(r"\d+\+\d+|\d+-\d+|\d+\.\d+|\d+%|\d+")

CONFIG_PATH = ROOT / "config" / "foundry_models.yaml"
EVAL_PATH = ROOT / "evals" / "swahili_comparison.json"
SHEET_PATH = ROOT / "evals" / "swahili_review.csv"
SCORES_PATH = ROOT / "evals" / "swahili_scores.json"
FEW_SHOT_PATH = ROOT / "config" / "few_shots" / "sw.jsonl"
FEW_SHOT_DRAFT_PATH = ROOT / "config" / "few_shots" / "sw.draft.jsonl"

MAX_HEADLINE = 60
MAX_BODY = 140
DEFAULT_CANDIDATES = ["narrator_sw", "narrator_en_fr"]
RATING_COLUMNS = ["fluency_1_5", "idiom_1_5", "faithfulness_1_5"]
MIN_AUTO_PASS_RATE = 0.8

SWAHILI_NUMBER_WORDS = {
    "moja", "mbili", "tatu", "nne", "tano", "sita", "saba", "nane", "tisa", "kumi",
    "ishirini", "thelathini", "arobaini", "hamsini", "sitini", "sabini", "themanini",
    "tisini", "mia",
}

SYSTEM_PROMPT = (
    "You are the Swahili radio commentator for a football match intelligence system. "
    "You receive one structured match moment as JSON and answer with JSON only. "
    "Write the commentary natively in Swahili in lively radio style. Never write English first "
    "and translate it.\n"
    "Rules:\n"
    "1. Use only facts present in the input (minute, score, team and player names, reason, "
    "numeric_evidence). Invent nothing.\n"
    f"2. headline is at most {MAX_HEADLINE} characters and body is at most {MAX_BODY} characters.\n"
    "3. Write every number as digits, never as words. Copy each numeric_evidence display_value "
    "exactly as given (for example 61% or 0.46). Write scores as home-away digits, for example 2-1.\n"
    "4. Copy player names exactly as given.\n"
    "5. mode analyst: cite at least one numeric_evidence value. mode casual: plain language, no jargon, "
    "no metrics.\n"
    "6. club_perspective home or away: frame the moment from that side's viewpoint. neutral: no side.\n"
    "7. claims_list has one claim for each player name, the minute, the score and each metric value you "
    "wrote (claim_type is player, minute, score or metric; metric claims also carry the metric name).\n"
    "8. gloss_en is a faithful English translation of your headline and body, within the same limits."
)

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "headline": {"type": "string", "maxLength": MAX_HEADLINE},
        "body": {"type": "string", "maxLength": MAX_BODY},
        "claims_list": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim_type": {"type": "string", "enum": ["player", "minute", "score", "metric", "event_id"]},
                    "value": {"type": "string"},
                    "metric": {"type": "string"},
                },
                "required": ["claim_type", "value"],
                "additionalProperties": False,
            },
        },
        "gloss_en": {
            "type": "object",
            "properties": {
                "headline": {"type": "string", "maxLength": MAX_HEADLINE},
                "body": {"type": "string", "maxLength": MAX_BODY},
            },
            "required": ["headline", "body"],
            "additionalProperties": False,
        },
    },
    "required": ["headline", "body", "claims_list", "gloss_en"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Fixed benchmark moments (a hand-written comeback storyline with fictional names)
# ---------------------------------------------------------------------------

HOME_TEAM = "Kisima City"
AWAY_TEAM = "Mto wa Nuru"


def _moment(
    seq: int,
    minute: int,
    score: str,
    team: str,
    player: str | None,
    tags: list[str],
    priority: int,
    mode: str,
    perspective: str,
    theme: str,
    reason: str,
    evidence: list[tuple[str, str]],
) -> dict[str, Any]:
    return {
        "moment_id": f"bench-km-{seq:04d}",
        "minute": minute,
        "score": score,
        "team": team,
        "player": player,
        "trigger_tags": tags,
        "priority": priority,
        "mode": mode,
        "club_perspective": perspective,
        "theme": theme,
        "reason": reason,
        "numeric_evidence": [{"metric": name, "display_value": value} for name, value in evidence],
        "evidence_event_ids": [f"bench-{seq:06d}"],
    }


def fixture_moments() -> list[dict[str, Any]]:
    """Return the 10 fixed benchmark moments, covering every trigger type and both modes."""
    rows = [
        (9, "0-1", AWAY_TEAM, "Tariq Nyalu", ["goal", "lead_change"], 1, "analyst", "neutral", "pressure_change",
         "Mto wa Nuru won the ball high up the pitch and scored from their first shot on target.", [("xg", "0.31")]),
        (23, "0-2", AWAY_TEAM, "Khalifa Moyo", ["goal"], 1, "casual", "home", "control_vs_chaos",
         "A quick counterattack punished Kisima City while they were pushing forward.", [("field_tilt", "57%")]),
        (34, "0-2", HOME_TEAM, "Amina Kivuva", ["big_chance"], 2, "analyst", "home", "control_vs_chaos",
         "Kisima City's territorial control finally produced a clear chance, but it was missed.", [("xg", "0.46")]),
        (41, "0-2", HOME_TEAM, None, ["momentum_swing"], 3, "casual", "neutral", "rhythm_shift",
         "The rhythm of the match has shifted toward Kisima City, who now push Mto wa Nuru back.",
         [("momentum_diff", "18")]),
        (52, "0-2", AWAY_TEAM, "Dani Kibiriti", ["red_card"], 1, "analyst", "neutral", "pressure_change",
         "Mto wa Nuru lose a defender, which hands Kisima City the initiative.", [("possession", "61%")]),
        (58, "1-2", HOME_TEAM, "Amina Kivuva", ["goal"], 1, "casual", "home", "control_vs_chaos",
         "Kisima City's pressure against a weakened side finally paid off.", [("field_tilt", "68%")]),
        (67, "2-2", HOME_TEAM, "Zuri Amini", ["goal"], 1, "analyst", "neutral", "control_vs_chaos",
         "Sustained pressure with a man advantage produced the equaliser.", [("xg_total", "2.4")]),
        (71, "2-2", HOME_TEAM, "Lina Saidi", ["player_milestone"], 4, "casual", "home", "rhythm_shift",
         "Lina Saidi has become the engine of Kisima City's attacks.", [("passes_into_final_third", "10")]),
        (78, "3-2", HOME_TEAM, "Amina Kivuva", ["goal", "lead_change", "late_game"], 1, "casual", "home",
         "rhythm_shift", "Kisima City complete the comeback from two goals down.", [("momentum_diff", "26")]),
        (84, "3-2", AWAY_TEAM, "Tariq Nyalu", ["big_chance", "late_game"], 1, "analyst", "away",
         "pressure_change", "Mto wa Nuru pushed hard for an equaliser and created a late clear chance.",
         [("xg", "0.52")]),
    ]
    return [_moment(index + 1, *row) for index, row in enumerate(rows)]


def _model_input(moment: dict[str, Any]) -> dict[str, Any]:
    """The subset of a moment the Narrator actually sees."""
    keys = (
        "minute", "score", "team", "player", "trigger_tags", "mode", "club_perspective",
        "theme", "reason", "numeric_evidence", "evidence_event_ids",
    )
    return {"language": "sw", **{key: moment[key] for key in keys}}


# ---------------------------------------------------------------------------
# Few-shot examples (drafts must be reviewed by a native speaker before use)
# ---------------------------------------------------------------------------

DRAFT_FEW_SHOTS: list[dict[str, Any]] = [
    {
        "input": {
            "language": "sw", "minute": 14, "score": "1-0", "team": "Ngome United", "player": "Salma Juma",
            "trigger_tags": ["goal"], "mode": "casual", "club_perspective": "home", "theme": "control_vs_chaos",
            "reason": "Ngome United scored after winning the ball in midfield.",
            "numeric_evidence": [{"metric": "field_tilt", "display_value": "59%"}],
            "evidence_event_ids": ["draft-000001"],
        },
        "output": {
            "headline": "Gooool! Salma Juma anaifungia Ngome United!",
            "body": "Dakika ya 14, Salma Juma anaiweka Ngome United mbele kwa 1-0. Wenyeji wanaanza kwa kishindo!",
            "claims_list": [
                {"claim_type": "player", "value": "Salma Juma"},
                {"claim_type": "minute", "value": "14"},
                {"claim_type": "score", "value": "1-0"},
            ],
            "gloss_en": {
                "headline": "Goal! Salma Juma scores for Ngome United!",
                "body": "In the 14th minute, Salma Juma puts Ngome United ahead 1-0. The hosts start with a bang!",
            },
        },
    },
    {
        "input": {
            "language": "sw", "minute": 61, "score": "1-1", "team": "Pwani Athletic", "player": "Eli Baraka",
            "trigger_tags": ["red_card"], "mode": "analyst", "club_perspective": "neutral",
            "theme": "pressure_change", "reason": "Pwani Athletic lose a player, so Ngome United take control.",
            "numeric_evidence": [{"metric": "possession", "display_value": "54%"}],
            "evidence_event_ids": ["draft-000002"],
        },
        "output": {
            "headline": "Kadi nyekundu! Eli Baraka anatolewa nje",
            "body": "Dakika ya 61, Pwani Athletic wanabaki pungufu uwanjani. Ngome United wanamiliki mpira kwa 54%, matokeo ni 1-1.",
            "claims_list": [
                {"claim_type": "player", "value": "Eli Baraka"},
                {"claim_type": "minute", "value": "61"},
                {"claim_type": "score", "value": "1-1"},
                {"claim_type": "metric", "value": "54%", "metric": "possession"},
            ],
            "gloss_en": {
                "headline": "Red card! Eli Baraka is sent off",
                "body": "In the 61st minute, Pwani Athletic are down a man. Ngome United hold 54% of the ball with the score at 1-1.",
            },
        },
    },
    {
        "input": {
            "language": "sw", "minute": 37, "score": "1-0", "team": "Pwani Athletic", "player": "Kian Mwakile",
            "trigger_tags": ["big_chance"], "mode": "analyst", "club_perspective": "away",
            "theme": "control_vs_chaos", "reason": "Pwani Athletic created their best chance but the keeper saved it.",
            "numeric_evidence": [{"metric": "xg", "display_value": "0.41"}],
            "evidence_event_ids": ["draft-000003"],
        },
        "output": {
            "headline": "Nafasi kubwa! Kian Mwakile anazuiwa",
            "body": "Dakika ya 37, shuti la Kian Mwakile lenye xG 0.41 linaokolewa na kipa. Pwani Athletic bado wako nyuma kwa 1-0.",
            "claims_list": [
                {"claim_type": "player", "value": "Kian Mwakile"},
                {"claim_type": "minute", "value": "37"},
                {"claim_type": "score", "value": "1-0"},
                {"claim_type": "metric", "value": "0.41", "metric": "xg"},
            ],
            "gloss_en": {
                "headline": "Big chance! Kian Mwakile is denied",
                "body": "In the 37th minute, Kian Mwakile's 0.41 xG shot is saved by the keeper. Pwani Athletic still trail 1-0.",
            },
        },
    },
    {
        "input": {
            "language": "sw", "minute": 88, "score": "2-2", "team": "Pwani Athletic", "player": "Noel Msalaba",
            "trigger_tags": ["goal", "late_game"], "mode": "casual", "club_perspective": "away",
            "theme": "rhythm_shift", "reason": "A late equaliser rescues Pwani Athletic.",
            "numeric_evidence": [{"metric": "momentum_diff", "display_value": "22"}],
            "evidence_event_ids": ["draft-000004"],
        },
        "output": {
            "headline": "Sawa! Noel Msalaba anaisawazishia Pwani Athletic",
            "body": "Dakika ya 88, Noel Msalaba anafunga na kuirudisha Pwani Athletic mchezoni. Ni 2-2, na dakika zimebaki chache!",
            "claims_list": [
                {"claim_type": "player", "value": "Noel Msalaba"},
                {"claim_type": "minute", "value": "88"},
                {"claim_type": "score", "value": "2-2"},
            ],
            "gloss_en": {
                "headline": "Level! Noel Msalaba equalises for Pwani Athletic",
                "body": "In the 88th minute, Noel Msalaba scores and brings Pwani Athletic back into it. It is 2-2 with few minutes left!",
            },
        },
    },
]


def _ensure_draft_few_shots() -> None:
    """Write draft few-shots for native review, without ever overwriting existing files."""
    if FEW_SHOT_PATH.exists() or FEW_SHOT_DRAFT_PATH.exists():
        return
    FEW_SHOT_DRAFT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = "".join(json.dumps(shot, ensure_ascii=False) + "\n" for shot in DRAFT_FEW_SHOTS)
    _atomic_write(FEW_SHOT_DRAFT_PATH, lines)
    print(
        f"Wrote DRAFT few-shots to {FEW_SHOT_DRAFT_PATH}. Have a native speaker correct them, "
        f"then save the approved version as {FEW_SHOT_PATH}."
    )


def _load_few_shots() -> tuple[list[dict[str, Any]], str]:
    for path in (FEW_SHOT_PATH, FEW_SHOT_DRAFT_PATH):
        if path.exists():
            shots = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            return shots, path.name
    return [], "none"


# ---------------------------------------------------------------------------
# Serialisation helpers (the original script truncated its output file when a
# response object was not plain JSON; everything is now normalised and written atomically)
# ---------------------------------------------------------------------------


def _to_jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    model_dump = getattr(obj, "model_dump", None)
    if callable(model_dump):
        return model_dump()
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _as_dict(response: Any) -> dict[str, Any]:
    """Normalise a client response (str, dataclass, pydantic model, mapping) into plain JSON data."""
    if isinstance(response, str):
        response = json.loads(response)
    plain = json.loads(json.dumps(response, default=_to_jsonable))
    if not isinstance(plain, dict):
        raise TypeError(f"Expected a JSON object response, got {type(plain).__name__}")
    return plain


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_json(path: Path, payload: Any) -> None:
    # Serialise fully before touching the file so a failure can never leave a partial file behind.
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=_to_jsonable) + "\n"
    _atomic_write(path, text)


# ---------------------------------------------------------------------------
# Deterministic quality checks (a subset of the Verifier pre-check)
# ---------------------------------------------------------------------------


def _numbers_in(text: str) -> list[str]:
    return [match.group(0) for match in NUMBER_RE.finditer(text)]


def check_response(moment: dict[str, Any], response: Any) -> tuple[list[str], list[str]]:
    """Return (issues, warnings) for one model response against its source moment."""
    issues: list[str] = []
    warnings: list[str] = []
    if not isinstance(response, dict):
        return ["response_not_object"], warnings

    headline = response.get("headline")
    body = response.get("body")
    claims = response.get("claims_list")
    gloss = response.get("gloss_en")
    gloss_headline = gloss.get("headline") if isinstance(gloss, dict) else None
    gloss_body = gloss.get("body") if isinstance(gloss, dict) else None

    if not isinstance(headline, str) or not headline.strip():
        issues.append("missing_headline")
    if not isinstance(body, str) or not body.strip():
        issues.append("missing_body")
    if not isinstance(claims, list):
        issues.append("missing_claims_list")
    if not (isinstance(gloss, dict) and isinstance(gloss_headline, str) and isinstance(gloss_body, str)):
        issues.append("missing_gloss_en")
    if issues:
        return issues, warnings

    headline = cast(str, headline)
    body = cast(str, body)
    claims = cast(list[Any], claims)
    gloss = cast(dict[str, Any], gloss)
    gloss_headline = cast(str, gloss_headline)
    gloss_body = cast(str, gloss_body)

    if len(headline) > MAX_HEADLINE:
        issues.append(f"headline_too_long:{len(headline)}")
    if len(body) > MAX_BODY:
        issues.append(f"body_too_long:{len(body)}")
    if len(gloss_headline) > MAX_HEADLINE:
        issues.append(f"gloss_headline_too_long:{len(gloss_headline)}")
    if len(gloss_body) > MAX_BODY:
        issues.append(f"gloss_body_too_long:{len(gloss_body)}")

    evidence_values = {item["display_value"] for item in moment["numeric_evidence"]}
    players = {moment["player"]} if moment["player"] else set()
    claim_numbers: set[str] = set()
    player_claims: set[str] = set()
    metric_claims = 0

    for claim in claims:
        if not isinstance(claim, dict) or "claim_type" not in claim or "value" not in claim:
            issues.append("malformed_claim")
            continue
        claim_type, value = claim["claim_type"], str(claim["value"])
        if claim_type == "player":
            player_claims.add(value)
            if value not in players:
                issues.append(f"unknown_player:{value}")
        elif claim_type == "minute":
            claim_numbers.add(value)
            if value != str(moment["minute"]):
                issues.append(f"wrong_minute:{value}")
        elif claim_type == "score":
            claim_numbers.add(value)
            if value != moment["score"]:
                issues.append(f"wrong_score:{value}")
        elif claim_type == "metric":
            claim_numbers.add(value)
            metric_claims += 1
            if value not in evidence_values:
                issues.append(f"metric_not_in_evidence:{value}")
        elif claim_type == "event_id":
            if value not in moment["evidence_event_ids"]:
                issues.append(f"unknown_event_id:{value}")
        else:
            issues.append(f"unknown_claim_type:{claim_type}")

    text = f"{headline} {body}"
    tokens = _numbers_in(text)
    for token in tokens:
        if token not in claim_numbers:
            issues.append(f"number_without_claim:{token}")
    for value in claim_numbers:
        if value not in tokens:
            issues.append(f"claim_not_in_text:{value}")
    for name in player_claims:
        if name not in text:
            issues.append(f"player_not_in_text:{name}")
    for token in _numbers_in(f"{gloss['headline']} {gloss['body']}"):
        if token not in claim_numbers:
            issues.append(f"gloss_number_mismatch:{token}")

    if moment["mode"] == "analyst" and metric_claims == 0:
        issues.append("analyst_without_metric")
    if moment["mode"] == "casual" and metric_claims > 0:
        warnings.append("casual_with_metric")
    words = set(re.findall(r"[a-zA-Z]+", text.lower()))
    for word in sorted(words & SWAHILI_NUMBER_WORDS):
        warnings.append(f"number_word:{word}")

    return issues, warnings


# ---------------------------------------------------------------------------
# Running the candidates
# ---------------------------------------------------------------------------


def _candidate_keys() -> list[str]:
    if not CONFIG_PATH.exists():
        return list(DEFAULT_CANDIDATES)
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    deployments = cfg.get("deployments", {})
    return [key for key in DEFAULT_CANDIDATES if key in deployments] or list(DEFAULT_CANDIDATES)


def _build_client(use_mock: bool) -> Any:
    if use_mock:
        return MockFoundryClient()
    endpoint = os.getenv("FOUNDRY_ENDPOINT") or os.getenv("AZURE_OPENAI_ENDPOINT")
    api_key = os.getenv("FOUNDRY_API_KEY") or os.getenv("AZURE_OPENAI_API_KEY")
    if not (endpoint and api_key):
        raise SystemExit(
            "No Foundry credentials found (set FOUNDRY_ENDPOINT and FOUNDRY_API_KEY). "
            "Use --mock for an offline dry run of the plumbing."
        )
    return FoundryClient(endpoint=endpoint, api_key=api_key)  # adjust if your client authenticates differently


def _mock_response(moment: dict[str, Any]) -> dict[str, Any]:
    """A compliant but meaningless response, used only to exercise the plumbing offline."""
    who = moment["player"] or moment["team"]
    minute, score = moment["minute"], moment["score"]
    claims: list[dict[str, str]] = [
        {"claim_type": "minute", "value": str(minute)},
        {"claim_type": "score", "value": score},
    ]
    if moment["player"]:
        claims.append({"claim_type": "player", "value": moment["player"]})
    body = f"Dakika ya {minute}, {moment['team']}. Ni {score}."
    gloss_body = f"In the {minute}th minute, {moment['team']}. It is {score}."
    if moment["mode"] == "analyst":
        metric = moment["numeric_evidence"][0]
        body += f" {metric['display_value']}."
        gloss_body += f" {metric['display_value']}."
        claims.append({"claim_type": "metric", "value": metric["display_value"], "metric": metric["metric"]})
    return {
        "headline": f"{who}: dakika ya {minute}",
        "body": body,
        "claims_list": claims,
        "gloss_en": {"headline": f"{who}: minute {minute}", "body": gloss_body},
    }


def _build_messages(moment: dict[str, Any], few_shots: list[dict[str, Any]]) -> list[dict[str, str]]:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for shot in few_shots:
        messages.append({"role": "user", "content": json.dumps(shot["input"], ensure_ascii=False)})
        messages.append({"role": "assistant", "content": json.dumps(shot["output"], ensure_ascii=False)})
    messages.append({"role": "user", "content": json.dumps(_model_input(moment), ensure_ascii=False)})
    return messages


async def _call(client: Any, candidate_key: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    result = client.structured_output(candidate_key, messages, RESPONSE_SCHEMA)
    if inspect.isawaitable(result):
        result = await result
    return _as_dict(result)


async def _run_candidate(
    client: Any, candidate_key: str, moments: list[dict[str, Any]], few_shots: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for moment in moments:
        entry: dict[str, Any] = {
            "moment_id": moment["moment_id"],
            "response": None,
            "error": None,
            "latency_ms": None,
            "issues": [],
            "warnings": [],
            "auto_pass": False,
        }
        started = time.perf_counter()
        try:
            response = await _call(client, candidate_key, _build_messages(moment, few_shots))
            entry["latency_ms"] = round((time.perf_counter() - started) * 1000)
            entry["response"] = response
            entry["issues"], entry["warnings"] = check_response(moment, response)
            entry["auto_pass"] = not entry["issues"]
        except QuotaExceeded as exc:
            entry["error"] = f"quota_exceeded: {exc}"
        except Exception as exc:  # recorded as an error row, never disguised as model output
            entry["error"] = f"{type(exc).__name__}: {exc}"
        rows.append(entry)
    return rows


def _percentile(values: list[int], fraction: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(fraction * (len(ordered) - 1))))]


def _summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    answered = [row for row in rows if row["response"] is not None]
    latencies = [row["latency_ms"] for row in answered if row["latency_ms"] is not None]
    return {
        "calls": len(rows),
        "errors": len(rows) - len(answered),
        "auto_pass_rate": round(sum(1 for row in rows if row["auto_pass"]) / len(rows), 3) if rows else 0.0,
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
    }


async def _run_all(
    client: Any, keys: list[str], moments: list[dict[str, Any]], few_shots: list[dict[str, Any]]
) -> dict[str, list[dict[str, Any]]]:
    return {key: await _run_candidate(client, key, moments, few_shots) for key in keys}


# ---------------------------------------------------------------------------
# Blind review sheet and scoring
# ---------------------------------------------------------------------------


def _write_review_sheet(
    results: dict[str, list[dict[str, Any]]], moments: list[dict[str, Any]], blind_map: dict[str, str], seed: int
) -> None:
    by_id = {moment["moment_id"]: moment for moment in moments}
    label_for = {key: label for label, key in blind_map.items()}
    rows: list[dict[str, Any]] = []
    for key, entries in results.items():
        for entry in entries:
            if entry["response"] is None:
                continue
            moment = by_id[entry["moment_id"]]
            response = entry["response"]
            evidence = ", ".join(f"{e['metric']}={e['display_value']}" for e in moment["numeric_evidence"])
            rows.append(
                {
                    "variant": label_for[key],
                    "moment_id": moment["moment_id"],
                    "mode": moment["mode"],
                    "minute": moment["minute"],
                    "score": moment["score"],
                    "facts_en": f"{moment['reason']} [{evidence}]",
                    "headline": response["headline"],
                    "body": response["body"],
                    "gloss_headline_en": response["gloss_en"]["headline"],
                    "gloss_body_en": response["gloss_en"]["body"],
                    "auto_pass": entry["auto_pass"],
                    **{column: "" for column in RATING_COLUMNS},
                    "notes": "",
                }
            )
    Random(seed + 1).shuffle(rows)
    SHEET_PATH.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["variant"]
    with SHEET_PATH.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _number(cell: str | None) -> float | None:
    try:
        return float(cell) if cell and cell.strip() else None
    except ValueError:
        return None


def _score_command() -> int:
    if not EVAL_PATH.exists() or not SHEET_PATH.exists():
        print("Run the comparison first and have the review sheet filled in.")
        return 1
    data = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    if data.get("mode") != "live":
        print("The last run was a mock run; there is nothing to score.")
        return 1
    blind_map = data["blind_map"]
    ratings: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    with SHEET_PATH.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            candidate = blind_map.get(row.get("variant", ""))
            if not candidate:
                continue
            for column in RATING_COLUMNS:
                value = _number(row.get(column))
                if value is not None:
                    ratings[candidate][column].append(value)

    moment_count = len(fixture_moments())
    report: dict[str, Any] = {}
    for candidate, entry in data["candidates"].items():
        summary = entry["summary"]
        cols = ratings.get(candidate, {})
        rated = min((len(cols.get(column, [])) for column in RATING_COLUMNS), default=0)
        means = {column: (sum(cols[column]) / len(cols[column]) if cols.get(column) else None) for column in RATING_COLUMNS}
        known = [value for value in means.values() if value is not None]
        report[candidate] = {
            **summary,
            "rated_lines": rated,
            "mean_ratings": means,
            "human_score": round(sum(known) / len(known), 2) if known else None,
            "eligible": rated == moment_count and summary["errors"] == 0 and summary["auto_pass_rate"] >= MIN_AUTO_PASS_RATE,
        }

    eligible = {key: value for key, value in report.items() if value["eligible"] and value["human_score"] is not None}
    recommended = max(eligible, key=lambda key: eligible[key]["human_score"]) if eligible else None
    _write_json(SCORES_PATH, {"recommended": recommended, "candidates": report})
    for candidate, value in report.items():
        print(
            f"{candidate}: human={value['human_score']} rated={value['rated_lines']}/{moment_count} "
            f"auto_pass={value['auto_pass_rate']} errors={value['errors']} "
            f"p50={value['latency_p50_ms']}ms p95={value['latency_p95_ms']}ms eligible={value['eligible']}"
        )
    print(f"Recommended: {recommended or 'none (rate every line and clear errors first)'}")
    return 0


def _select_command(candidate: str) -> int:
    if not EVAL_PATH.exists():
        raise SystemExit("No comparison file found; run the comparison first.")
    data = json.loads(EVAL_PATH.read_text(encoding="utf-8"))
    if data.get("mode") != "live":
        raise SystemExit("Refusing to select from a mock run.")
    if not SCORES_PATH.exists():
        raise SystemExit("Run --score first so the decision rests on the native-speaker ratings.")
    scores = json.loads(SCORES_PATH.read_text(encoding="utf-8"))
    entry = scores["candidates"].get(candidate)
    if not entry or not entry["eligible"]:
        raise SystemExit(f"{candidate} is not eligible: every line must be rated, with no errors and enough automated passes.")
    if not CONFIG_PATH.exists():
        raise SystemExit(f"{CONFIG_PATH} does not exist.")
    cfg = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    deployments = cfg.get("deployments", {})
    if candidate not in deployments:
        raise SystemExit(f"{candidate} is not a deployment in {CONFIG_PATH.name}.")
    cfg["swahili_narrator"] = candidate
    for key, value in deployments.items():
        if isinstance(value, dict):
            value["chosen_after_eval"] = key == candidate
    _atomic_write(CONFIG_PATH, yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    data["selected_candidate"] = candidate
    _write_json(EVAL_PATH, data)
    print(f"Recorded {candidate} as the Swahili Narrator in {CONFIG_PATH} (YAML comments are not preserved).")
    return 0


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def _run_command(args: argparse.Namespace) -> int:
    moments = fixture_moments()
    keys = args.candidates or _candidate_keys()
    _ensure_draft_few_shots()
    few_shots, few_shot_source = _load_few_shots()
    client = _build_client(args.mock)
    if args.mock:
        for key in keys:
            for moment in moments:
                client.add_response(key, _mock_response(moment))

    results = asyncio.run(_run_all(client, keys, moments, few_shots))
    mode = "mock" if args.mock else "live"
    labels = [chr(ord("A") + index) for index in range(len(keys))]
    shuffled = list(keys)
    Random(args.seed).shuffle(shuffled)
    blind_map = dict(zip(labels, shuffled))

    payload = {
        "mode": mode,
        "seed": args.seed,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "few_shot_source": few_shot_source,
        "selected_candidate": None,
        "blind_map": blind_map,
        "moments": moments,
        "candidates": {key: {"summary": _summarise(rows), "results": rows} for key, rows in results.items()},
    }
    _write_json(EVAL_PATH, payload)
    print(f"Wrote {mode} benchmark to {EVAL_PATH}")
    for key, entry in payload["candidates"].items():
        print(f"  {key}: {entry['summary']}")

    if mode == "live":
        _write_review_sheet(results, moments, blind_map, args.seed)
        print(f"Wrote blind review sheet to {SHEET_PATH}. Fill in the rating columns, then run --score.")
    else:
        print("Mock run: no review sheet written and selection is disabled.")

    return 1 if any(entry["summary"]["calls"] == entry["summary"]["errors"] for entry in payload["candidates"].values()) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare candidate Swahili narration deployments.")
    parser.add_argument("--mock", action="store_true", help="Offline dry run against MockFoundryClient.")
    parser.add_argument("--seed", type=int, default=42, help="Seed for blind labelling and row order.")
    parser.add_argument("--candidates", nargs="+", help="Deployment keys to compare (default: from config).")
    parser.add_argument("--score", action="store_true", help="Combine native-speaker ratings with automated checks.")
    parser.add_argument("--select", metavar="KEY", help="Record the chosen deployment after review.")
    args = parser.parse_args(argv)

    if args.score:
        return _score_command()
    if args.select:
        return _select_command(args.select)
    return _run_command(args)


if __name__ == "__main__":
    raise SystemExit(main())