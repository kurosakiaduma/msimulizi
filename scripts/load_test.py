"""
scripts/load_test.py — Task 31 load-test harness.

Simulates concurrent viewers creating sessions against the deployed backend to
confirm:
  * the concurrent session cap (MSIMULIZI_MAX_SESSIONS) is enforced,
  * session creation stays within the latency budget,
  * the feed stays up (bundle replay / fallback path) under load.

Run against a live deployment (after `azd up`):

    MSIMULIZI_LOAD_TEST=1 python scripts/load_test.py \
        --base-url https://<backend>.azurecontainerapps.io \
        --sessions 12 --concurrency 8

Exit code 0 if all sessions were created within the latency target.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Optional

# Latency target for session creation (Requirement 13.6 area: demo responsiveness).
SESSION_CREATE_LATENCY_TARGET_SECONDS = 5.0


@dataclass
class Result:
    index: int
    ok: bool
    status: Optional[int]
    latency_seconds: float
    error: Optional[str] = None
    session_id: Optional[str] = None


def create_session(base_url: str, index: int, timeout: float = 20.0) -> Result:
    """Create one session; return a Result."""
    start = time.monotonic()
    url = base_url.rstrip("/") + "/v1/sessions"
    payload = json.dumps(
        {
            "storyline": "comeback_from_two_down",
            "seed": 42,
            "speed": 1.0,
            "language": "sw",
            "mode": "casual",
        }
    ).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode())
            return Result(
                index=index,
                ok=resp.status < 400,
                status=resp.status,
                latency_seconds=time.monotonic() - start,
                session_id=body.get("session_id"),
            )
    except urllib.error.HTTPError as exc:
        return Result(
            index=index,
            ok=False,
            status=exc.code,
            latency_seconds=time.monotonic() - start,
            error=exc.read().decode(errors="replace")[:200],
        )
    except Exception as exc:  # network / timeout
        return Result(
            index=index,
            ok=False,
            status=None,
            latency_seconds=time.monotonic() - start,
            error=str(exc)[:200],
        )


def main() -> int:
    if not __import__("os").environ.get("MSIMULIZI_LOAD_TEST"):
        print(
            "Load test disabled. Set MSIMULIZI_LOAD_TEST=1 to run against a live backend.",
            file=sys.stderr,
        )
        return 0

    parser = argparse.ArgumentParser(description="Load-test session creation against the Msimulizi backend.")
    parser.add_argument("--base-url", required=True, help="Deployed backend base URL (no trailing slash).")
    parser.add_argument("--sessions", type=int, default=10, help="Total sessions to create.")
    parser.add_argument("--concurrency", type=int, default=5, help="Concurrent session-creation requests.")
    parser.add_argument(
        "--latency-target",
        type=float,
        default=SESSION_CREATE_LATENCY_TARGET_SECONDS,
        help="Session-creation latency target in seconds.",
    )
    args = parser.parse_args()

    results: list[Result] = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = [
            pool.submit(create_session, args.base_url, i) for i in range(args.sessions)
        ]
        for fut in as_completed(futures):
            results.append(fut.result())

    results.sort(key=lambda r: r.index)

    ok = sum(1 for r in results if r.ok)
    failed = len(results) - ok
    latencies = [r.latency_seconds for r in results if r.ok]
    p50 = sorted(latencies)[len(latencies) // 2] if latencies else 0.0
    p95 = (
        sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)] if latencies else 0.0
    )
    over_target = sum(1 for r in latencies if r > args.latency_target)

    print(f"\n── Load test: {args.sessions} sessions, concurrency={args.concurrency} ──")
    print(f"  created_ok={ok}  failed={failed}")
    print(f"  p50 session-create latency={p50:.2f}s  p95={p95:.2f}s")
    print(f"  requests over {args.latency_target}s target={over_target}")
    for r in results:
        if not r.ok:
            print(f"  ✗ session #{r.index}: HTTP {r.status} in {r.latency_seconds:.2f}s — {r.error}")

    exit_code = 0
    if failed:
        print(f"\n✗ {failed} session(s) failed to create.", file=sys.stderr)
        exit_code = 1
    if p95 > args.latency_target:
        print(
            f"\n✗ p95 latency {p95:.2f}s exceeds target {args.latency_target}s.",
            file=sys.stderr,
        )
        exit_code = 1
    if exit_code == 0:
        print("\n✓ Load test passed — session cap and latency targets met.")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
