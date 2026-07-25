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


def decide(path, ok_extra=()):
    """Return (verdict, detail).

    verdict is one of "PASS", "FAIL", "PARSE_ERROR". The logic mirrors the
    prior inline shell exactly for PASS/FAIL; the only behavioral change is
    that the CALLER now gates on PARSE_ERROR instead of warning-and-passing.
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
