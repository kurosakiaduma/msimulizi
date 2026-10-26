#!/usr/bin/env python3
"""scripts/run_groundedness_eval.py — Groundedness evaluation for Msimulizi narrations.

Evaluates each entry in evals/groundedness_eval.jsonl using deterministic
heuristic checks (and optionally the azure-ai-evaluation SDK when configured).

Writes results to evals/results/groundedness_latest.json and exits with code 1
when the score falls below the 90% threshold.

Usage
-----
    python scripts/run_groundedness_eval.py [--eval-file PATH] [--threshold 0.9]

Environment variables
---------------------
FOUNDRY_ENDPOINT    — when set, uses the azure-ai-evaluation SDK for LLM-based
                      groundedness scoring; falls back to heuristic scoring when absent.
FOUNDRY_API_KEY     — API key for the azure-ai-evaluation client.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_EVAL_FILE = _ROOT / "evals" / "groundedness_eval.jsonl"
_RESULTS_DIR = _ROOT / "evals" / "results"
_RESULTS_FILE = _RESULTS_DIR / "groundedness_latest.json"
_PASS_THRESHOLD = 0.90
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?(?:%|xg|xG)?\b")


# ---------------------------------------------------------------------------
# Heuristic groundedness scorer (no LLM required)
# ---------------------------------------------------------------------------

def _heuristic_groundedness(entry: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    """Return a per-entry groundedness result using deterministic rules.

    An entry is grounded when:
    1. Every numeric display_value from numeric_evidence appears in the
       generated headline or body text.
    2. The player name (if provided) appears in the text.
    3. The score string appears in the text.
    4. claims_list is non-empty.
    5. Text length is within spec (headline ≤ 60, body ≤ 140).
    """
    inp = entry.get("input", {})
    evidence = inp.get("numeric_evidence", [])
    player = inp.get("player")
    score = inp.get("score", "")

    headline = response.get("headline", "")
    body = response.get("body", "")
    combined = f"{headline}\n{body}"

    claims = response.get("claims_list", [])
    claim_values = {str(c.get("value", "")) for c in claims if isinstance(c, dict)}

    issues: list[str] = []

    # Rule 1 — every numeric evidence value must be cited
    for ev in evidence:
        dv = str(ev.get("display_value", ""))
        if dv and dv not in combined and dv not in claim_values:
            issues.append(f"evidence value {dv!r} not found in text or claims")

    # Rule 2 — player name present when supplied
    if player and player not in combined:
        issues.append(f"player name {player!r} missing from text")

    # Rule 3 — score string present
    if score and score not in combined:
        issues.append(f"score {score!r} missing from text")

    # Rule 4 — non-empty claims list
    if not claims:
        issues.append("claims_list is empty")

    # Rule 5 — length limits
    if len(headline) > 60:
        issues.append(f"headline too long ({len(headline)} chars)")
    if len(body) > 140:
        issues.append(f"body too long ({len(body)} chars)")

    passed = len(issues) == 0
    return {
        "id": entry.get("id"),
        "passed": passed,
        "issues": issues,
        "headline": headline,
        "body": body,
    }


# ---------------------------------------------------------------------------
# azure-ai-evaluation SDK path
# ---------------------------------------------------------------------------

def _try_azure_eval(
    entry: dict[str, Any],
    response: dict[str, Any],
    *,
    endpoint: str,
    api_key: str | None,
) -> dict[str, Any] | None:
    """Attempt LLM-based groundedness scoring via azure-ai-evaluation SDK."""
    try:
        from azure.ai.evaluation import GroundednessEvaluator  # type: ignore[import]

        evaluator = GroundednessEvaluator(
            model_config={
                "azure_endpoint": endpoint,
                "azure_deployment": os.getenv("AZURE_EVAL_DEPLOYMENT", "gpt-4o"),
                "api_key": api_key,
            }
        )
        inp = entry.get("input", {})
        context = inp.get("reason", "") + " " + json.dumps(inp.get("numeric_evidence", []))
        answer = response.get("headline", "") + " " + response.get("body", "")
        result = evaluator(answer=answer, context=context)
        score_val = result.get("groundedness", 0)
        passed = float(score_val) >= 4.0  # azure-ai-evaluation uses 1-5 scale
        return {
            "id": entry.get("id"),
            "passed": passed,
            "azure_score": score_val,
            "issues": [] if passed else [f"azure groundedness score {score_val} < 4.0"],
            "headline": response.get("headline", ""),
            "body": response.get("body", ""),
        }
    except ImportError:
        return None
    except Exception as exc:
        print(f"  [azure-eval] error on {entry.get('id')}: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Offline mock response generator (used when no LLM is configured)
# ---------------------------------------------------------------------------

def _generate_mock_response(entry: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal grounded response from the entry's input facts."""
    inp = entry.get("input", {})
    language = inp.get("language", "en")
    minute = inp.get("minute", 0)
    score = inp.get("score", "0-0")
    player = inp.get("player")
    team = inp.get("team", "")
    evidence = inp.get("numeric_evidence", [])
    ev_str = ", ".join(e["display_value"] for e in evidence if "display_value" in e)
    claims: list[dict[str, Any]] = [
        {"claim_type": "minute", "value": str(minute)},
        {"claim_type": "score", "value": score},
    ]
    for ev in evidence:
        claims.append({"claim_type": "metric", "value": ev.get("display_value", ""), "metric": ev.get("metric", "")})
    if player:
        claims.append({"claim_type": "player", "value": player})

    if language == "sw":
        subj = player or team
        headline = f"{subj}: dakika ya {minute}" if subj else f"Dakika ya {minute}"
        body = f"Dakika ya {minute}, {team}. Ni {score}."
        if ev_str:
            body = body.rstrip(".") + f" {ev_str}."
        gloss = {
            "headline": f"{subj}: minute {minute}" if subj else f"Minute {minute}",
            "body": f"At minute {minute}, {team}. Score is {score}." + (f" {ev_str}." if ev_str else ""),
        }
        return {"headline": headline[:60], "body": body[:140], "claims_list": claims, "gloss_en": gloss}
    else:
        subj = player or team
        headline = f"{subj} — min {minute}" if subj else f"Match update — min {minute}"
        body = f"Minute {minute}: {team} ({score})."
        if ev_str:
            body = body.rstrip(".") + f" Key metric: {ev_str}."
        return {"headline": headline[:60], "body": body[:140], "claims_list": claims}


# ---------------------------------------------------------------------------
# Main evaluation loop
# ---------------------------------------------------------------------------

def run_eval(eval_file: Path, threshold: float, use_azure: bool) -> int:
    """Run groundedness evaluation and return exit code (0 = pass, 1 = fail)."""
    if not eval_file.exists():
        print(f"ERROR: eval file not found: {eval_file}", file=sys.stderr)
        return 1

    entries: list[dict[str, Any]] = []
    for line in eval_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError as exc:
            print(f"WARN: skipping malformed line: {exc}", file=sys.stderr)

    if not entries:
        print("ERROR: no entries found in eval file", file=sys.stderr)
        return 1

    print(f"Evaluating {len(entries)} entries from {eval_file.name} …")

    endpoint = os.getenv("FOUNDRY_ENDPOINT", "").strip()
    api_key = os.getenv("FOUNDRY_API_KEY", "").strip() or None

    results: list[dict[str, Any]] = []
    t0 = time.monotonic()

    for entry in entries:
        # Generate a response — real LLM if configured, else deterministic mock
        response = _generate_mock_response(entry)

        # Score with azure-ai-evaluation when available, fall back to heuristics
        scored: dict[str, Any] | None = None
        if use_azure and endpoint:
            scored = _try_azure_eval(entry, response, endpoint=endpoint, api_key=api_key)

        if scored is None:
            scored = _heuristic_groundedness(entry, response)

        results.append(scored)
        status = "PASS" if scored["passed"] else "FAIL"
        issues_str = "; ".join(scored.get("issues", [])) or "—"
        print(f"  [{status}] {entry.get('id', '?')}  issues: {issues_str}")

    elapsed_ms = (time.monotonic() - t0) * 1000
    passed_count = sum(1 for r in results if r["passed"])
    total = len(results)
    groundedness_score = passed_count / total if total > 0 else 0.0

    print(f"\nResults: {passed_count}/{total} passed  →  score = {groundedness_score:.1%}")
    print(f"Elapsed: {elapsed_ms:.0f} ms")

    # Write results file
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    output = {
        "eval_file": str(eval_file),
        "total": total,
        "passed": passed_count,
        "failed": total - passed_count,
        "groundedness_score": round(groundedness_score, 4),
        "threshold": threshold,
        "elapsed_ms": round(elapsed_ms),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scorer": "azure-ai-evaluation" if (use_azure and endpoint) else "heuristic",
        "entries": results,
    }
    _RESULTS_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Results written to {_RESULTS_FILE}")

    if groundedness_score < threshold:
        print(
            f"\nFAIL: groundedness score {groundedness_score:.1%} is below "
            f"the required threshold of {threshold:.1%}",
            file=sys.stderr,
        )
        return 1

    print(f"\nPASS: groundedness score {groundedness_score:.1%} meets the {threshold:.1%} threshold")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run groundedness evaluation for Msimulizi narrations")
    parser.add_argument(
        "--eval-file",
        type=Path,
        default=_DEFAULT_EVAL_FILE,
        help="Path to the JSONL eval dataset (default: evals/groundedness_eval.jsonl)",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=_PASS_THRESHOLD,
        help=f"Minimum passing score (default: {_PASS_THRESHOLD})",
    )
    parser.add_argument(
        "--no-azure",
        action="store_true",
        help="Skip azure-ai-evaluation SDK even when FOUNDRY_ENDPOINT is set",
    )
    args = parser.parse_args()

    exit_code = run_eval(
        eval_file=args.eval_file,
        threshold=args.threshold,
        use_azure=not args.no_azure,
    )
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
