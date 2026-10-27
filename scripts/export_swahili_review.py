"""Export signed-off native-speaker reviews for a defensible quality claim.

The dashboard stores individual reviews. This script is the gate between
"someone rated some lines" and "we published an average". It refuses to export
a score until the requested number of distinct lines have a complete review,
a named reviewer, an English gloss, and no open blocking issue.

Examples
--------
    python scripts/export_swahili_review.py --min-lines 30
    MSIMULIZI_API_BASE=https://... MSIMULIZI_REVIEWER_KEY=... \\
        python scripts/export_swahili_review.py --out evals/swahili_signed.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "evals" / "swahili_review_signed.json"


def fetch_queue(api_base: str, reviewer_key: str) -> dict[str, Any]:
    url = f"{api_base.rstrip('/')}/v1/review/swahili"
    request = urllib.request.Request(
        url,
        headers={"X-Reviewer-Key": reviewer_key},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"Review API returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Review API unreachable: {exc.reason}") from exc


def signed_off(item: dict[str, Any]) -> bool:
    review = item.get("review")
    if not isinstance(review, dict):
        return False
    if not all(
        isinstance(review.get(key), int) and 1 <= review[key] <= 5
        for key in ("fluency", "idiom", "faithfulness")
    ):
        return False
    if review.get("blocking"):
        return False
    if review.get("requires_second_review"):
        return False
    if not str(review.get("reviewer") or "").strip():
        return False
    return bool(str(item.get("gloss_headline") or "").strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-base", default=os.getenv("MSIMULIZI_API_BASE", "http://localhost:8000"))
    parser.add_argument("--reviewer-key", default=os.getenv("MSIMULIZI_REVIEWER_KEY", ""))
    parser.add_argument("--min-lines", type=int, default=30)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    if not args.reviewer_key:
        raise SystemExit("Set MSIMULIZI_REVIEWER_KEY or pass --reviewer-key")

    payload = fetch_queue(args.api_base, args.reviewer_key)
    items = payload.get("items") or []
    approved = [item for item in items if signed_off(item)]

    if len(approved) < args.min_lines:
        print(
            f"Refusing to publish: {len(approved)} signed-off line(s), "
            f"{args.min_lines} required. Open /review and finish the queue.",
            file=sys.stderr,
        )
        return 2

    rows = []
    total = 0.0
    for item in approved:
        review = item["review"]
        mean = (review["fluency"] + review["idiom"] + review["faithfulness"]) / 3
        total += mean
        rows.append(
            {
                "id": item["id"],
                "minute": item.get("minute", 0),
                "swahili_headline": item.get("headline", ""),
                "swahili_body": item.get("body", ""),
                "gloss_headline": item.get("gloss_headline", ""),
                "gloss_body": item.get("gloss_body", ""),
                "reviewer": review.get("reviewer", ""),
                "fluency": review["fluency"],
                "idiom": review["idiom"],
                "faithfulness": review["faithfulness"],
                "mean": round(mean, 2),
                "note": review.get("note", ""),
                "submitted_at": review.get("submitted_at", ""),
            }
        )

    result = {
        "schema": "msimulizi.swahili-review.v1",
        "line_count": len(rows),
        "average": round(total / len(rows), 2),
        "rows": rows,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Exported {len(rows)} signed-off lines to {args.out}")
    print(f"Average: {result['average']} / 5")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
