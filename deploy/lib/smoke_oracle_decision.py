#!/usr/bin/env python3
"""Smoke-oracle decision — parse a qa-smoke / canary Lambda invoke result and
decide PASS / FAIL / PARSE_ERROR for ci-cd.yml's post-deploy smoke-test job.

#1345 — closes the two fail-open paths in the smoke oracle. Previously an
UNPARSEABLE smoke or canary response (`PARSE_ERROR`) emitted a `::warning` and
the step PASSED — a silently-broken oracle could not fail the pipeline, so the
Lambda-side auto-rollback (rollback-on-smoke-failure) could never fire on a
mangled response. That is the backend half of the detect-and-revert story and
it was documentation-verified only. Here PARSE_ERROR is GATING (exit 1): an
oracle whose output we cannot read is treated as a failure, never a pass.

#1831 — closes the fail-open path for a COMPLETED invocation that reports a
real health failure. The old logic only string-matched the top-level
status/statusCode for the substrings "error"/"fail" — a numeric failure like
canary_lambda's `statusCode: 500` (set when `all_ok` is False) contains
neither substring and isn't in OK_BASE, so it fell through to PASS. Worse,
qa_smoke_lambda ALWAYS returns `statusCode: 200` and buries the real failure
count inside a JSON-ENCODED STRING under `body` (Lambda-proxy convention) —
the oracle never looked there at all. Net effect: the smoke-test job could
only fail on a total crash or unparseable payload, never on a completed
invocation reporting an unhealthy system — exactly the failure class the
auto-rollback gate exists to catch. `decide()` now also treats a numeric
status/statusCode >= 400 as FAIL, and parses the `body` (dict or JSON string)
for `failed` (truthy/nonzero) or `all_pass: false`.

The parse/decision logic used to live inline in two shell steps of
ci-cd.yml. It is extracted here so it is unit-testable (tests/
test_smoke_oracle_decision.py) and shared byte-for-byte by both the qa-smoke
step and the canary step — the workflow now just calls this script and lets its
exit code gate the step.

Usage:
    smoke_oracle_decision.py <result.json> <label> [--ok-extra STATUS ...]

Exit codes:
    0  PASS       — the oracle reported healthy.
    1  FAIL       — the oracle reported a failure/unhealthy status.
    1  PARSE_ERROR — the result could not be parsed as a status-bearing JSON
                     object (GATING as of #1345; was fail-open before).
"""

import argparse
import json
import sys

# Statuses accepted as healthy for every oracle. The canary additionally
# accepts "healthy" via --ok-extra (preserving the prior per-step behavior).
OK_BASE = ("ok", "pass", "200")


def _numeric_status(value):
    """Return an int if `value` parses cleanly as one (e.g. 500 or "500"), else None.

    Non-numeric statuses ("ok", "healthy", "error: timeout") are the normal
    case and correctly return None here — they're handled by the string match
    below, unchanged from the pre-#1831 behavior.
    """
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _parse_body(result):
    """Return the Lambda-proxy `body` as a dict, or None if absent/unparseable.

    canary_lambda and qa_smoke_lambda both return `{"statusCode": ..., "body":
    json.dumps({...})}` — the real failure detail (`all_pass`, `failed`) lives
    inside that JSON-ENCODED STRING, not at the top level. Accept a `body`
    that's already a dict too (non-proxy invokes / test fixtures). Any parse
    failure here is non-fatal to the overall decision — it just means there's
    no body-level signal to add, and the top-level status still applies.
    """
    body = result.get("body")
    if isinstance(body, dict):
        return body
    if isinstance(body, str):
        try:
            parsed = json.loads(body)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def decide(path, ok_extra=()):
    """Return (verdict, detail).

    verdict is one of "PASS", "FAIL", "PARSE_ERROR". The PASS/FAIL string
    matching mirrors the prior inline shell exactly for the healthy case (kept
    byte-compatible per #1345's CLI-contract lesson); #1831 adds two FAIL
    paths ahead of it — numeric statusCode >= 400, and a failing `body` — that
    the old logic never reached.
    """
    try:
        with open(path) as f:
            result = json.load(f)
    except Exception as e:  # noqa: BLE001 — any read/parse failure is a PARSE_ERROR
        return "PARSE_ERROR", str(e)

    # A non-object payload (list/scalar) has no status field to read — the old
    # inline code hit AttributeError on `.get(...)` and fell into PARSE_ERROR.
    if not isinstance(result, dict):
        return "PARSE_ERROR", f"expected a JSON object, got {type(result).__name__}"

    status = result.get("status", result.get("statusCode", ""))
    s = str(status).lower()
    ok = set(OK_BASE) | {str(x).lower() for x in ok_extra}

    # #1831: a numeric status/statusCode >= 400 is an unambiguous HTTP-level
    # failure (canary_lambda sets statusCode=500 when all_ok is False) that
    # the string match below can miss entirely — "500" contains neither
    # "error" nor "fail" and isn't in OK_BASE, so it used to fall through to
    # PASS.
    numeric_status = _numeric_status(status)
    if numeric_status is not None and numeric_status >= 400:
        return "FAIL", str(status)

    # #1831: qa_smoke_lambda ALWAYS returns statusCode 200 and puts the real
    # failure count inside body.failed; canary_lambda's body carries
    # all_pass. A completed-but-unhealthy invocation must not read as PASS
    # just because the top-level status/statusCode looks fine.
    body = _parse_body(result)
    if isinstance(body, dict):
        failed = body.get("failed")
        if failed:
            return "FAIL", f"body failed={failed!r} (status={status})"
        if body.get("all_pass") is False:
            return "FAIL", f"body all_pass=false (status={status})"

    if s in ok or (s and "error" not in s and "fail" not in s):
        return "PASS", str(status)
    return "FAIL", str(status)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Smoke-oracle PASS/FAIL/PARSE_ERROR decision (#1345).")
    parser.add_argument("result", help="path to the Lambda invoke result JSON")
    parser.add_argument("label", help="human label for annotations, e.g. 'Smoke test' or 'Canary'")
    parser.add_argument(
        "--ok-extra",
        nargs="*",
        default=[],
        help="additional status strings to accept as healthy (canary uses 'healthy')",
    )
    args = parser.parse_args(argv)

    verdict, detail = decide(args.result, args.ok_extra)

    if verdict == "PASS":
        print(f"✅ {args.label} passed")
        return 0

    if verdict == "PARSE_ERROR":
        # #1345: GATING. Was previously `::warning` + pass (fail-open) — an
        # unparseable oracle response must never silently pass the pipeline.
        print(
            f"::error::Could not parse {args.label} output as JSON ({detail}) — "
            "treating as FAILURE (smoke oracle must not fail-open, #1345)"
        )
        return 1

    print(f"::error::{args.label} reported failure: {detail}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
