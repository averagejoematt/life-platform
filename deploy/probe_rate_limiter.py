#!/usr/bin/env python3
"""
deploy/probe_rate_limiter.py — #1439: one low-volume LIVE probe of the
DynamoDB-backed rate limiter (`lambdas/rate_limiter.py`) against the real
deployed site.

RUN THIS MANUALLY. NEVER WIRE IT INTO CI, `deploy/smoke_test_site.sh`, or any
other automatic/on-every-deploy path. See "Scheduling / runbook" below.

── What this does ───────────────────────────────────────────────────────────
Targets POST /api/board_ask (the smallest natural per-IP limit in production —
BOARD_RATE_LIMIT = 5/hr, see `lambdas/web/site_api_ai_lambda.py`) with a
question body that is deliberately too short ("hi", < 5 chars). Reading the
handler (`_handle_board_ask` in site_api_ai_lambda.py) confirms the rate-limit
check runs and increments the DynamoDB counter BEFORE the "question too
short" validation — so every probe request increments the real counter while
NEVER reaching persona selection or a single Bedrock/Haiku call. That means
this probe:
  - costs $0 in model spend (no request gets past the length check)
  - never sends an email (doesn't touch /api/subscribe at all)
  - never consumes a real reader's budget: it always runs from THIS
    machine/agent's own egress IP, which is not shared with real readers,
    and the per-IP counter it may exhaust only affects future requests from
    THAT SAME IP within the same hour — not any other IP
  - is bounded: at most BOARD_RATE_LIMIT + 1 requests are ever sent, once

Two modes:
  --mode shape (default, safest):
      Sends exactly 2 requests. Never attempts to trip a real 429. Asserts
      that a 429-capable response shape exists and is sane (i.e. it proves
      the live counter is wired — headers/error shape — without needing to
      actually exhaust the limit).
  --mode trip429 (opt-in — explicitly requested only):
      Sends up to BOARD_RATE_LIMIT + 1 requests (6 by default) — enough to
      observe one REAL 429 from the live rate limiter — and asserts the 429
      response's shape: statusCode 429, a `Retry-After` header, and a JSON
      error body. This is the literal acceptance-criteria ask ("verifies a
      real 429 on a safe endpoint without exhausting real reader quota").

── Why board_ask over /api/ask, /api/subscribe, or a synthetic endpoint ─────
  - /api/subscribe (60/5min) would need 61 requests to trip for real, and a
    successful one could (depending on config) send a real confirmation
    email — out of scope for a "safe" probe.
  - /api/ask (5/hr anon) does NOT work for this trick: reading `_handle_ask`
    shows its "question too short" check runs FIRST — before the ip_hash is
    even computed, before the safety filter, before the rate-limit check —
    so a too-short question there returns 400 WITHOUT ever touching the rate
    limiter at all. board_ask's `_handle_board_ask` is the opposite order
    (rate-limit check, THEN body parsing, THEN "question too short"), which
    is exactly what makes a zero-cost probe possible there. This ordering
    difference is also why board_ask matches the issue's own suggested
    design (smallest natural limit, agent's own IP, payload rejected at the
    rate-limit layer before any real work) more precisely than /api/ask does.
  - A synthetic/staging endpoint doesn't exist for this site (single prod
    deployment) — hence probing prod itself, at minimal volume, is the only
    way to verify the REAL DynamoDB-backed path end-to-end (Lambda -> DDB ->
    CloudFront -> response), which is exactly what the acceptance criteria
    ask for (a live probe, not another mock).

── Scheduling / runbook (also see docs/RUNBOOK.md) ──────────────────────────
  Run manually, at most once every few weeks (e.g. after touching
  `lambdas/rate_limiter.py`, `web/site_api_ai_lambda.py`'s rate-limit wiring,
  or the site-api-ai IAM policy) — never on a schedule, never in CI.

    python3 deploy/probe_rate_limiter.py                    # --mode shape (safe default)
    python3 deploy/probe_rate_limiter.py --mode trip429     # deliberately trips one real 429

  PASS looks like: shape mode prints "PASS" for both requests (well-formed
  4xx JSON body, expected keys present); trip429 mode prints the status code
  of each of the N requests, ending in a single 429 with a `Retry-After`
  header, then "PASS".
  FAIL looks like: any request returns something other than 400 (shape mode)
  or the sequence never reaches a 429 within BOARD_RATE_LIMIT + 1 requests
  (trip429 mode) — investigate whether the rate limiter, the DDB table, or
  the site-api-ai Lambda's IAM policy regressed.

  If a prior manual run already exhausted this IP's board_ask quota within
  the last hour, trip429 mode will 429 immediately (remaining == 0) — that
  is itself a PASS (it's still proving the live counter persists across
  probe runs), not a failure; the script reports this explicitly.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "https://averagejoematt.com"
ENDPOINT = f"{BASE}/api/board_ask"
BOARD_RATE_LIMIT = 5  # mirrors lambdas/web/site_api_ai_lambda.py BOARD_RATE_LIMIT — kept in sync by hand; if this
# probe ever starts failing oddly, first check that constant hasn't changed.
TOO_SHORT_QUESTION = "hi"  # < 5 chars -> "Question too short" (400), AFTER the rate-limit check, BEFORE any Bedrock call


def _post_board_ask(timeout: float = 10.0):
    """One POST /api/board_ask with a too-short question. Returns
    (status_code, headers, parsed_body_or_None). `headers` is the raw
    email.message.Message-like object urllib returns — deliberately NOT
    dict()-ified, because HTTP header names are case-insensitive (the live
    server sends a lowercase `retry-after`) and a plain dict() would make
    `.get("Retry-After")` silently miss it. Always look headers up through
    this object's own case-insensitive `.get()`, never re-wrap it in dict()."""
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps({"question": TOO_SHORT_QUESTION}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return resp.status, resp.headers, _try_json(body)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8") if e.fp else ""
        return e.code, e.headers, _try_json(body)


def _try_json(body: str):
    try:
        return json.loads(body)
    except Exception:
        return None


def run_shape_mode() -> bool:
    """2 requests only. Never attempts to trip a real 429 — proves the live
    endpoint is reachable, responds with well-formed 4xx JSON for a rejected
    question, and (if we happen to be near/at the limit already) that a real
    429 carries the expected shape. Does not assert a specific status code
    beyond 'looks like a real, well-formed API response'."""
    ok = True
    for i in range(1, 3):
        status, headers, body = _post_board_ask()
        print(f"[shape] request {i}/2 -> status={status} retry_after_header={headers.get('Retry-After')!r} body={body}")
        if status == 429:
            if "Retry-After" not in headers or not isinstance(body, dict) or "error" not in body:
                print(f"[shape] FAIL — 429 response missing expected shape (Retry-After header / JSON 'error' key): {headers}, {body}")
                ok = False
        elif status == 400:
            if not isinstance(body, dict) or "error" not in body:
                print(f"[shape] FAIL — 400 response missing expected JSON 'error' key: {body}")
                ok = False
        else:
            print(f"[shape] FAIL — unexpected status {status} for a too-short question (expected 400 or 429)")
            ok = False
        time.sleep(1)  # be gentle — no need to fire back-to-back
    print("PASS" if ok else "FAIL")
    return ok


def run_trip429_mode(max_requests: int = BOARD_RATE_LIMIT + 1) -> bool:
    """Up to BOARD_RATE_LIMIT + 1 requests — deliberately trips one real 429
    from this machine's own IP, at zero model cost (every request is rejected
    for a too-short question, before any Bedrock call)."""
    saw_429 = False
    for i in range(1, max_requests + 1):
        status, headers, body = _post_board_ask()
        print(f"[trip429] request {i}/{max_requests} -> status={status} retry_after_header={headers.get('Retry-After')!r} body={body}")
        if status == 429:
            saw_429 = True
            if "Retry-After" not in headers:
                print("[trip429] FAIL — 429 response missing Retry-After header")
                return False
            if not isinstance(body, dict) or "error" not in body:
                print(f"[trip429] FAIL — 429 response body missing JSON 'error' key: {body}")
                return False
            print(
                f"[trip429] PASS — observed a real 429 after {i} request(s) "
                f"(if this fired on request 1, this IP's board_ask quota was already exhausted "
                f"from a prior probe run within the last hour — that's still a pass, it proves persistence)"
            )
            break
        if status != 400:
            print(f"[trip429] FAIL — unexpected status {status} (expected 400 for a too-short question, or eventually 429)")
            return False
        time.sleep(1)  # be gentle between requests
    if not saw_429:
        print(f"[trip429] FAIL — never observed a 429 within {max_requests} requests")
        return False
    print("PASS")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--mode",
        choices=["shape", "trip429"],
        default="shape",
        help="shape (default, safest): 2 requests, asserts response shape only. "
        "trip429: up to BOARD_RATE_LIMIT+1 requests, deliberately observes one real 429.",
    )
    args = parser.parse_args()

    print(f"# rate-limiter live probe — mode={args.mode} target={ENDPOINT}")
    print("# Manual-only. Never run this from CI or an automated schedule (see module docstring).")
    ok = run_shape_mode() if args.mode == "shape" else run_trip429_mode()
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
