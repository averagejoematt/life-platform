#!/usr/bin/env python3
"""deploy/lib/canary_gate_retry.py — retry-before-gate for the canary deploy gate (#3830 box 3).

THE INCIDENT THIS CLOSES
  2026-09-15T19:55Z. Bedrock returned a `ServiceUnavailableException` to the canary's
  Anthropic round-trip. DDB, S3, MCP and the subscribe flow were all green. **One
  datapoint reached three consumers and each drew a different conclusion:**

    the alerter      "Suppressed first-occurrence alert"   — declined to email
    the alarm        fired, then self-cleared in 15 min    — loud, proportionate
    the deploy gate  reverted 85 Lambdas                   — the most destructive,
                                                             and the most confident

  The most destructive consumer was the most confident, on the *least* evidence: the
  alerter waited for a second occurrence before it would even send mail, while the gate
  stripped a verified-correct fleet deploy on the first.

  #3831 fixed the classification half (`LANE_EXTERNAL_TRANSIENT` in `canary_lanes.py`), so
  a *recognised* vendor transient no longer lands in the gating lane. This file fixes the
  other half, which is not about recognition at all: **no single observation should be
  able to revert a fleet, whatever its cause.** A classifier can only demote failure modes
  someone has already named; this is the backstop for the ones nobody has named yet.

WHAT IT DOES
  Invokes the canary. If the verdict is GATING, waits and invokes again. Gates only when
  EVERY attempt is gating. That is first-occurrence parity with the alerter, stated in the
  only currency the deploy gate has: a second look.

  It also prints the shared oracle's non-gating lane annotations for every attempt
  (`smoke_oracle_decision.print_non_gating_annotations`). Those lines used to be printed by
  `smoke_oracle_decision.main()`, which this wrapper replaced in the canary step — so
  between #3839 and #3830's completion the canary's stored-state warning (#2051) silently
  stopped appearing, and `failed_external_transient` never had one. De-gating a finding and
  then not printing it is a mute, not a re-route; the annotator is called here so both stay
  loud in the run's own log. It is the oracle's function, keyed on lane counters, so no
  per-check string matching enters this file (#3830 box 4).

WHAT IT DELIBERATELY DOES NOT DO
  * **No per-check string matching.** This file never reads a check name, a failure
    message, or an exception class. It reads the shared oracle's verdict and counts it.
    #3830 box 4 requires the lane/failure classification to live in `canary_lanes.py`
    alone, and a retry that peeked at "is this one transient?" would put a second, drifting
    copy of that judgement here.
  * **It does not weaken the AccessDenied direction, and does so structurally.** A
    persistent fault — a real IAM denial, a broken deploy, a genuinely down dependency —
    fails every attempt and still gates. The permissive direction is bought with
    *repetition*, not with a suppression list, so nothing needs to be exempted for the
    gate to keep working. (The opposite-direction control is
    `test_a_persistent_access_denied_still_gates_through_every_attempt`.)
  * **It does not retry a PASS.** A healthy first look costs exactly one invocation.
  * **Its retry does not become the alerter's second occurrence.** Every attempt after the
    first carries `{"gate_recheck": true}`, which tells the canary this is the same look
    taken again rather than a second RUN: it leaves `USER#system / CANARY#last_state`
    untouched and sends no email. Without it this wrapper would buy gate/alerter parity
    and immediately spend it — the alerter emails when the SAME check fails in two
    consecutive runs (two runs of `rate(4 hours)`), and a re-invoke 20 seconds later reads
    the state attempt 1 just wrote, so a 30-second vendor blip would mail the operator
    "persistent failure" about the datapoint the alerter had already suppressed. The
    canary keeps running every check and emitting every CloudWatch metric on a re-check,
    so the alarms stay exactly as loud; only the email window is left alone. An older
    deployed canary ignores the unknown key and behaves as it does today, so the flag is
    safe to ship ahead of the fleet deploy that honours it.

WHY NOT IN THE WORKFLOW'S SHELL
  The decision this makes is worth a must-fail control, and a `||` chain in a YAML `run:`
  block cannot have one. The logic is pure and injected (`invoke=`), so the whole matrix —
  transient-then-green, persistent-failure, parse-error, no-wasted-retry — is exercised
  offline in tests/test_canary_gate_retry_3830.py with no AWS.

USAGE
    canary_gate_retry.py --function life-platform-canary --region us-west-2 \
        --out /tmp/canary.json --label Canary --ok-extra healthy [--attempts 2] [--delay 20]

EXIT CODES — identical contract to smoke_oracle_decision.py, which it wraps:
    0  PASS  — some attempt reported healthy
    1  FAIL / PARSE_ERROR — EVERY attempt was gating
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))

import smoke_oracle_decision as oracle  # noqa: E402  — sibling module, same dir

# A verdict that would gate the deploy. PARSE_ERROR is included because #1345 made an
# unreadable oracle GATING, and an unreadable response is exactly as likely to be a
# one-off (a truncated payload, a throttled invoke) as an unhealthy one.
GATING_VERDICTS = frozenset({"FAIL", "PARSE_ERROR"})

DEFAULT_ATTEMPTS = 2  # first-occurrence parity: one failure is an observation, two are a signal
DEFAULT_DELAY_SECONDS = 20.0
MAX_ATTEMPTS = 5  # a deploy gate that retries all afternoon is its own outage


def is_gating(verdict: str) -> bool:
    return verdict in GATING_VERDICTS


def gate(verdicts: list) -> tuple:
    """Pure. The whole decision, given the verdict of each attempt in order.

    → (exit_code, summary). PASS if ANY attempt passed; gating only if EVERY attempt
    gated. An empty list is a programming error and gates — never fail open.
    """
    if not verdicts:
        return 1, "no attempts were made — gating rather than failing open"
    passed = [i for i, (v, _d) in enumerate(verdicts, 1) if not is_gating(v)]
    rendered = "; ".join(f"attempt {i}: {v} ({d})" for i, (v, d) in enumerate(verdicts, 1))
    if passed:
        if len(verdicts) == 1:
            return 0, f"PASS on the first look — {rendered}"
        return 0, (
            f"PASS on attempt {passed[0]} of {len(verdicts)} — the earlier failure did NOT gate the deploy "
            f"(#3830: first-occurrence parity with the alerter). {rendered}"
        )
    return 1, f"GATING — all {len(verdicts)} attempt(s) failed, so this is not a first-occurrence transient. {rendered}"


def run_attempts(invoke, attempts: int, delay: float, sleep=time.sleep, log=print) -> list:
    """Pure-ish driver. `invoke(n)` performs attempt n and returns (verdict, detail).

    Stops at the first non-gating verdict — a healthy canary costs one invocation.
    """
    verdicts: list = []
    for n in range(1, attempts + 1):
        verdict, detail = invoke(n)
        verdicts.append((verdict, detail))
        if not is_gating(verdict):
            return verdicts
        if n < attempts:
            log(
                f"::warning::Canary attempt {n}/{attempts} was {verdict} ({detail}) — "
                f"re-invoking in {delay:g}s before gating the deploy (#3830). "
                f"A single observation must not revert a fleet; a persistent fault will fail this retry too. "
                f"The re-invoke carries gate_recheck=true, so it reports its verdict without touching the "
                f"alerter's first-occurrence window."
            )
            sleep(delay)
    return verdicts


#: The payload for attempt 1: an ordinary canary run, byte-identical to the scheduled one.
FIRST_LOOK_PAYLOAD = "{}"
#: The payload for every attempt AFTER the first. `gate_recheck` is read by
#: `lambdas/operational/canary_lambda.is_gate_recheck`: the run reports its verdict in full
#: but takes no part in the alerter's consecutive-runs window and sends no email. This is
#: not a check name and not a failure classification — the lane decision stays entirely in
#: `canary_lanes.py` (#3830 box 4).
RECHECK_PAYLOAD = json.dumps({"gate_recheck": True})


def payload_for(attempt: int) -> str:
    """Attempt 1 is a run; every later attempt is the same look, taken again."""
    return FIRST_LOOK_PAYLOAD if attempt <= 1 else RECHECK_PAYLOAD


def _aws_invoke(function: str, region: str, out: Path, label: str, ok_extra: tuple):
    """The live attempt: invoke the canary, then hand the payload to the SHARED oracle."""

    def attempt(n: int):
        target = out if n == 1 else out.with_name(f"{out.stem}.attempt{n}{out.suffix}")
        cmd = [
            "aws", "lambda", "invoke",
            "--function-name", function,
            "--payload", payload_for(n),
            "--region", region,
            "--cli-binary-format", "raw-in-base64-out",
            str(target),
        ]  # fmt: skip
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            # The invoke itself failed (throttle, transport). Treat as a gating verdict so
            # the retry applies, rather than crashing the step with no second look.
            return "FAIL", f"aws lambda invoke exited {proc.returncode}: {proc.stderr.strip()[:200]}"
        try:
            print(f"Canary result (attempt {n}):")
            print(json.dumps(json.loads(target.read_text()), indent=2)[:4000])
        except Exception:  # noqa: BLE001 — printing is best-effort; the oracle reads the file itself
            print(f"Canary result (attempt {n}): <unprintable>")
        if n != 1:
            # The LAST attempt is what the workflow's later steps read.
            out.write_text(target.read_text())
        # #3830: every non-gating lane this attempt reported gets named here, by the
        # SHARED oracle's own annotator. Wrapping `decide()` rather than `main()` is
        # what made the retry possible, and it also skipped the `::warning` lines
        # `main()` printed — so from #3839 until now the canary's stored-state
        # annotation (#2051) was absent from the CI log and the external-transient
        # lane never had one at all. A finding that no longer gates AND no longer
        # prints has been muted rather than re-routed, which is the same inversion
        # this file exists to undo. Annotated per ATTEMPT, not once at the end: a
        # transient that clears on the retry is precisely the case worth naming, and
        # by then its payload is no longer the one the verdict came from.
        oracle.print_non_gating_annotations(str(target), label if n == 1 else f"{label} (attempt {n})")
        return oracle.decide(str(target), ok_extra=ok_extra)

    return attempt


def build_arg_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Retry-before-gate wrapper around the canary smoke oracle (#3830).")
    ap.add_argument("--function", default="life-platform-canary")
    ap.add_argument("--region", default=os.environ.get("AWS_REGION", "us-west-2"))
    ap.add_argument("--out", default="/tmp/canary.json")
    ap.add_argument("--label", default="Canary")
    ap.add_argument("--ok-extra", action="append", default=[])
    ap.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    ap.add_argument("--delay", type=float, default=DEFAULT_DELAY_SECONDS)
    return ap


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)
    attempts = max(1, min(args.attempts, MAX_ATTEMPTS))
    invoke = _aws_invoke(args.function, args.region, Path(args.out), args.label, tuple(args.ok_extra))
    verdicts = run_attempts(invoke, attempts, args.delay)
    code, summary = gate(verdicts)
    print(f"{args.label} decision: {'PASS' if code == 0 else 'FAIL'} — {summary}")
    if code == 0 and len(verdicts) > 1:
        print(f"::warning::{args.label} needed {len(verdicts)} attempts — the first was a transient, not a deploy defect (#3830).")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
