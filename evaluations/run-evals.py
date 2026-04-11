#!/usr/bin/env python3
"""
run-evals.py
============
Runs the evaluation dataset against the live API endpoints and scores results.

Usage:
    python evaluations/run-evals.py --backend-url http://localhost:8000

Requires backend to be running. Outputs a JSON results file and console summary.
"""

import argparse
import asyncio
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

HERE = Path(__file__).parent
DATASET_PATH = HERE / "test-dataset.json"


async def run_chat_message(
    client: httpx.AsyncClient,
    backend_url: str,
    message: str,
    session_id: str,
    mode: str = "handoff",
) -> dict:
    """Send a chat message and collect SSE events into a result dict."""
    events: list[dict] = []
    full_content = ""
    last_agent = None

    try:
        async with client.stream(
            "POST",
            f"{backend_url}/api/chat/message",
            json={"message": message, "session_id": session_id, "mode": mode},
            timeout=60.0,
        ) as resp:
            if resp.status_code == 400:
                body = await resp.aread()
                return {"blocked": True, "status_code": 400, "body": body.decode()}
            resp.raise_for_status()

            async for line in resp.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                    events.append(event)
                    if event.get("type") == "agent_response" and event.get("content"):
                        full_content += event["content"]
                        last_agent = event.get("agent")
                except json.JSONDecodeError:
                    pass
    except httpx.HTTPStatusError as exc:
        return {"error": str(exc), "status_code": exc.response.status_code}
    except Exception as exc:
        return {"error": str(exc)}

    return {
        "content": full_content,
        "last_agent": last_agent,
        "events": events,
        "blocked": False,
    }


def score_result(test_case: dict, result: dict) -> dict:
    passed = True
    reasons: list[str] = []

    if test_case.get("expected_blocked"):
        if result.get("blocked") or result.get("status_code") in (400, 422):
            reasons.append("PASS: Blocked as expected")
        else:
            passed = False
            reasons.append("FAIL: Expected block but request succeeded")
        return {"passed": passed, "reasons": reasons}

    if result.get("error"):
        return {"passed": False, "reasons": [f"FAIL: Request error — {result['error']}"]}

    content = result.get("content", "").lower()

    # Check expected agent routing
    expected_agent = test_case.get("expected_agent")
    if expected_agent:
        actual_agent = result.get("last_agent", "")
        if expected_agent in (actual_agent or ""):
            reasons.append(f"PASS: Routed to expected agent '{expected_agent}'")
        else:
            passed = False
            reasons.append(f"FAIL: Expected agent '{expected_agent}', got '{actual_agent}'")

    # Check keyword presence
    for kw in test_case.get("expected_keywords", []):
        if kw.lower() in content:
            reasons.append(f"PASS: Found keyword '{kw}'")
        else:
            passed = False
            reasons.append(f"FAIL: Missing keyword '{kw}'")

    # Check forbidden strings
    for bad in test_case.get("should_not_contain", []):
        if bad.lower() in content:
            passed = False
            reasons.append(f"FAIL: Response contains forbidden string '{bad}'")

    return {"passed": passed, "reasons": reasons}


async def main(backend_url: str) -> None:
    print(f"\nEvaluating against: {backend_url}\n")

    with DATASET_PATH.open() as f:
        dataset = json.load(f)

    results = []
    passed_count = 0

    async with httpx.AsyncClient() as client:
        for tc in dataset:
            tc_id = tc["id"]
            mode = tc.get("expected_mode", "handoff")
            message = tc["user_message"]
            session_id = tc["conversation_id"]

            print(f"  [{tc_id}] {message[:60]}...", end=" ", flush=True)
            t0 = time.monotonic()
            result = await run_chat_message(client, backend_url, message, session_id, mode)
            elapsed = time.monotonic() - t0

            scored = score_result(tc, result)
            result_record = {
                "id": tc_id,
                "message": message,
                "passed": scored["passed"],
                "reasons": scored["reasons"],
                "elapsed_s": round(elapsed, 2),
                "response_preview": (result.get("content") or "")[:200],
            }
            results.append(result_record)

            status = "PASS" if scored["passed"] else "FAIL"
            color = "\033[92m" if scored["passed"] else "\033[91m"
            print(f"{color}{status}\033[0m ({elapsed:.1f}s)")
            for r in scored["reasons"]:
                print(f"     {r}")

            if scored["passed"]:
                passed_count += 1

    # Write results file
    out_file = HERE / f"eval-results-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    with out_file.open("w") as f:
        json.dump(results, f, indent=2)

    total = len(dataset)
    print(f"\n{'='*50}")
    print(f"Results: {passed_count}/{total} passed ({passed_count/total*100:.0f}%)")
    print(f"Output:  {out_file}")

    if passed_count < total:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend-url", default="http://localhost:8000")
    args = parser.parse_args()
    asyncio.run(main(args.backend_url))
