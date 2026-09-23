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

#2051 — closes the fail-CLOSED path in the other direction: a finding that is
not about the deploy at all must not revert it. A body that declares lanes
(`failed_deploy_health` present, as qa-smoke does since #1921 and the canary
does since #2051) is gated on that key ALONE; the union counters (`all_pass`,
`failures`) no longer re-admit the non-gating lane. Bodies without a lane
declaration are unaffected — every failure still gates.

#3830 — the non-gating annotations stopped being `main()`'s private business.
`deploy/lib/canary_gate_retry.py` (retry-before-gate) wraps `decide()` directly,
so from #3839 the canary's gating step reached a verdict without ever reaching
these `::warning` lines and #2051's stored-state annotation quietly stopped
appearing in the CI log. `print_non_gating_annotations()` is now the one shared
shout, called by BOTH entry points, and it grows a third lane:
`failed_external_transient` — a vendor 503 / throttle / timeout on a live
round-trip, demoted out of the gating lane by #3831 after one of them reverted
85 Lambdas on 2026-09-15. Each lane is read as ONE counter by key; no per-check
string matching lives here, and the lane decision stays in
`lambdas/operational/canary_lanes.py` (#3830 box 4).

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
        # #1921: gate on DEPLOY-HEALTH failures only. qa-smoke answers two
        # unrelated questions — "is the code that just shipped broken?" and "is
        # the published content honest right now?" — and only the first is
        # evidence about the deploy in flight. Wiring both to this exit code
        # reverted healthy fleets three times (2026-07-27: 98 functions on a
        # dashboard-freshness check; 2026-08-01 00:18Z: 100 functions on a
        # reader_truth finding about a defect that had been live for weeks).
        # Reverting code cannot un-publish a stale number, so for that class the
        # rollback was not just disproportionate — it was ineffective.
        #
        # Fallback is deliberately CONSERVATIVE and preserves #1831's contract:
        # when `failed_deploy_health` is absent (an older qa-smoke zip, the
        # canary — which has no partitions and whose every check IS deploy
        # health) we fall back to the total `failed`, i.e. exactly the
        # pre-#1921 behaviour. The oracle never fails open on a missing key.
        #
        # #2051 extends the same reasoning to the CANARY, which is where it was
        # missing and where it cost a deploy. On 2026-08-02 every canary
        # round-trip passed (DDB, S3, MCP, Bedrock) and the run still returned
        # 500 because ONE synthetic subscriber row, written twelve days
        # earlier, had survived cleanup (#1954's postcondition). The rollback
        # fired and stripped out a verified-correct fleet deploy — and while
        # that row existed no session's deploy could have survived. The canary
        # now publishes `failed_deploy_health` (infra round-trips) alongside
        # `failed_stored_state` (residue postconditions), so the two lanes land
        # on opposite sides of this branch.
        if "failed_deploy_health" in body:
            gating = body.get("failed_deploy_health")
            if gating:
                return "FAIL", f"body failed_deploy_health={gating!r} (status={status})"
            # A LANE-AWARE body has already told us which failures are about
            # this deploy. `all_pass` is the honest UNION across lanes, so
            # consulting it here would re-admit exactly the non-gating findings
            # the branch above just excluded — #1921's mistake, one path over.
        else:
            failed = body.get("failed")
            if failed:
                return "FAIL", f"body failed={failed!r} (status={status})"
            # Legacy/unlaned bodies keep the pre-#2051 contract untouched: no
            # lane declaration means every failure is treated as gating.
            if body.get("all_pass") is False:
                return "FAIL", f"body all_pass=false (status={status})"

    if s in ok or (s and "error" not in s and "fail" not in s):
        return "PASS", str(status)
    return "FAIL", str(status)


def _body_count(path, key):
    """Read one integer counter out of the oracle's body, or 0.

    Used for the non-gating CI annotations only. Kept out of `decide()` so that
    function's (verdict, detail) contract — and every test asserting on it —
    stays byte-compatible.
    """
    try:
        with open(path) as f:
            result = json.load(f)
        body = _parse_body(result) if isinstance(result, dict) else None
        return int(body.get(key) or 0) if isinstance(body, dict) else 0
    except Exception:  # noqa: BLE001 — annotation only; never affect the verdict
        return 0


def content_truth_count(path):
    """#1921: how many CONTENT_TRUTH failures this oracle reported, or 0.

    A content-truth failure no longer gates the pipeline, which is precisely
    why it has to be shouted at the surface where the deploy happened; the
    re-routing is only defensible if it is not also a mute.
    """
    return _body_count(path, "failed_content_truth")


def stored_state_count(path):
    """#2051: how many STORED-STATE failures this oracle reported, or 0.

    The canary's residue/cleanup postconditions. Same deal as content-truth:
    de-gated, so it must be louder, not quieter. This is the annotation that
    would have named the 2026-08-02 stray row in the run's own log instead of
    letting "smoke failure" stand in for "a test row from twelve days ago".
    """
    return _body_count(path, "failed_stored_state")


def external_transient_count(path):
    """#3830: how many EXTERNAL-TRANSIENT failures this oracle reported, or 0.

    The newest non-gating lane and the one this file exists to stop reverting a
    fleet: a live round-trip that failed because the dependency on the far end
    of it was transiently unavailable (`canary_lanes.LANE_EXTERNAL_TRANSIENT` —
    a vendor 503, a throttle, a read timeout). `failed_deploy_health` already
    excludes it by construction, so the deploy no longer gates on it; this
    counter is the other half of that bargain.

    Note what is NOT here: no check name, no exception class, no message
    substring. This reads ONE lane counter by key, exactly as its two siblings
    do. The decision of which failures land in that counter is made once, in
    `lambdas/operational/canary_lanes.py`, and #3830 box 4 requires it to stay
    there — a second copy of that judgement in the gate reader is the scattering
    that lost #1921's reasoning in the first place.
    """
    return _body_count(path, "failed_external_transient")


#: The non-gating lanes, in one list, each with the sentence that has to appear in
#: the log when it is non-zero. Every entry here is a finding that was DELIBERATELY
#: taken out of the rollback path, and the rule all three share is #1921's: the
#: re-routing is only defensible if it is not also a mute. A de-gated lane with no
#: line in the run's own log is indistinguishable from a check that never ran.
NON_GATING_ANNOTATIONS = (
    (
        "failed_content_truth",
        "content-truth",
        "#1921: content findings describe published state, not the code that just shipped, "
        "and a rollback cannot un-publish them. "
        "The qa-smoke failure email and the ContentTruthFailCount alarm carry the detail.",
    ),
    (
        "failed_stored_state",
        "stored-state",
        "#2051: a residue postcondition describes data written possibly weeks ago, not the code "
        "that just shipped, and a rollback cannot delete a row. "
        "Fix the DATA: the canary alert email and the canary-subscribe-residue alarm carry the detail.",
    ),
    (
        "failed_external_transient",
        "external-transient",
        "#3830: the dependency on the far end of a live round-trip was transiently unavailable "
        "(a vendor 503, a throttle, a timeout) — the deploy cannot have caused it and a rollback "
        "cannot fix it. On 2026-09-15 one of these reverted 85 Lambdas from this step while the "
        "alerter, reading the same datapoint, declined to even send mail. "
        "The failing check still emits its own Fail metric, so its alarm is exactly as loud as "
        "before; lambdas/operational/canary_lanes.py names the check and the failure code.",
    ),
)


def print_non_gating_annotations(path, label, out=print):
    """Shout every non-gating lane this oracle reported. Returns the counts printed.

    Split out of `main()` (#3830) because `main()` stopped being the only caller.
    `deploy/lib/canary_gate_retry.py` wraps `decide()` directly for the retry, so
    from #3839 until this change the canary path reached the verdict WITHOUT ever
    reaching these annotations — #2051's stored-state line silently stopped
    appearing in the CI log the moment retry-before-gate went in front of it.
    That is the same defect as the one it annotates, one layer up: a finding that
    no longer gates and no longer prints has been muted, not re-routed.
    """
    printed = {}
    for key, lane_label, why in NON_GATING_ANNOTATIONS:
        count = _body_count(path, key)
        if not count:
            continue
        printed[key] = count
        out(f"::warning::{label}: {count} {lane_label} failure(s) — NOT gating this deploy ({why})")
    return printed


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

    # #1921/#2051/#3830: surface every non-gating lane loudly, regardless of the
    # verdict. None of them is evidence about this deploy — which is exactly why
    # each one has to be named in the run's own log rather than disappearing
    # behind the word "smoke".
    print_non_gating_annotations(args.result, args.label)

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
