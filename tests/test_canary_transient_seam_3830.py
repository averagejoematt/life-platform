"""tests/test_canary_transient_seam_3830.py — #3830 across the SEAM, not either side of it.

WHAT THIS ADDS THAT THE OTHER THREE #3830 SUITES DO NOT.

`test_canary_transient_lane_3830.py` proves the classifier: a hand-built results dict in,
a lane count out. `test_smoke_oracle_decision.py` proves the gate reader: a hand-built body
in, a verdict out. Both are green. Neither has ever run the REAL canary handler's REAL body
through the REAL oracle — the two halves are each graded against a fixture the other side
never produced.

That is the memory-class *"a comparison gate is blind when both sides agree"*: two
components tested against a shared idea of the payload will keep agreeing right up until
the payload changes shape, and the seam is exactly where #3830's 85-Lambda rollback
happened. So every test below walks the whole wire —

    canary_lambda.lambda_handler(...)  ->  response["body"]  ->  a Lambda-invoke result
                                       ->  smoke_oracle_decision.decide(...)  ->  exit code

— and asserts on the exit code the CI step would actually have taken.

THE INCIDENT. 2026-09-15T19:54:50Z, CI/CD run 35013357326. DDB, S3, MCP and the subscribe
flow all round-tripped clean; Bedrock answered `ServiceUnavailableException`. The canary's
alerter called that datapoint too weak to send an EMAIL about ("Suppressed first-occurrence
alert"); the deploy gate reverted 85 functions on it. The most destructive consumer of one
observation was the most confident.

THE FOUR ACCEPTANCE BOXES, and where each is answered here:

  1  a vendor transient does NOT gate, and is still alarmed + named in the CI log
     -> the seam tests in §1, the alarm control in §3, the CI-log controls in §4,
        and — because box 1 says *proved by a WATCHED mutation, not by reading* —
        §2, where each proof is re-run with the classification removed and must flip.
  2  `AccessDeniedException` on the SAME check still gates
     -> §1's paired control, end to end, and again inside every mutation.
  3  a single first-occurrence infra failure cannot revert a fleet
     -> §5 derives the alerter's evidence bar from the handler's own behaviour and
        asserts the gate never asks for less. The gate may not be more confident than
        the alerter, and that is now machine-checked rather than commented.
  4  the classification lives in `canary_lanes.py` alone
     -> §6 scans the gate reader and the wrapper for check names and exception classes.

Every permissive assertion below is paired with a restrictive one. A guard that only
demonstrates the permissive direction is how #2051 recurred as #3830.
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIB = os.path.join(_REPO, "deploy", "lib")
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "operational"), _LIB):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import canary_gate_retry as cgr  # noqa: E402
import canary_lambda as canary  # noqa: E402
import smoke_oracle_decision as oracle  # noqa: E402
from operational import canary_lanes as cl  # noqa: E402

# NB the import spelling above is load-bearing. `canary_lambda` does
# `from operational.canary_lanes import ...`, so `operational.canary_lanes` and a bare
# `canary_lanes` are TWO DISTINCT module objects on this sys.path (both `lambdas/` and
# `lambdas/operational/` are importable). Monkeypatching the wrong one mutates a module the
# handler never reads, and every mutation control in §2 would pass while proving nothing —
# the fixture would not be the wire.
assert cl is sys.modules[canary.lane_for_result.__module__], "the tests must patch the module the handler actually imported"

pytestmark = pytest.mark.premerge

# The real 2026-09-15T19:54:50Z failure, copied off the canary's own log rather than off a
# description of it: the botocore `Error.Code` AND the message the vendor actually sent.
INCIDENT_CODE = "ServiceUnavailableException"
INCIDENT_MESSAGE = "Bedrock ServiceUnavailableException: Bedrock is unable to process your request."
# What a bad DEPLOY looks like on the very same check: an IAM grant lost in a CDK change.
DEPLOY_PLAUSIBLE_CODE = "AccessDeniedException"
DEPLOY_PLAUSIBLE_MESSAGE = "Bedrock AccessDeniedException: not authorized to perform bedrock:InvokeModel"


class _StateDDB:
    """Scripted DynamoDB client for USER#system / CANARY#last_state.

    A plain class, never MagicMock: a MagicMock `get_item` returns a truthy Mock for
    `.get("Item")`, which would launder a missing read into a passing assertion.
    """

    def __init__(self, prev_failed=()):
        self.prev_failed = list(prev_failed)
        self.put_items: list = []

    def get_item(self, **kwargs):
        if not self.prev_failed:
            return {}
        return {"Item": {"failed_checks": {"SS": list(self.prev_failed)}}}

    def put_item(self, **kwargs):
        self.put_items.append(kwargs)
        return {}


def run_canary(monkeypatch, *, anthropic=None, ddb_ok=True, residue_rows=0, prev_failed=(), event=None):
    """Invoke the REAL handler with only the outward probes stubbed.

    `anthropic` is None for a healthy Bedrock round-trip, or a (code, message) pair for a
    failing one — the 4-tuple return is the live signature (#3831 gave `check_anthropic` a
    botocore `Error.Code` so `canary_lanes` can tell a vendor 503 from a deploy-plausible
    break on the same check). A fixture that is not the wire is how a signature change
    passes its own tests.

    Returns (response, body, alerts, metrics, state).
    """
    monkeypatch.setattr(canary, "check_dynamodb", lambda ts, p: (ddb_ok, "ddb msg", 10.0))
    monkeypatch.setattr(canary, "check_s3", lambda ts, p: (True, "s3 msg", 10.0))
    monkeypatch.setattr(canary, "check_mcp", lambda ts: (True, "83 tools listed", 10.0))
    if anthropic is None:
        monkeypatch.setattr(canary, "check_anthropic", lambda ts: (True, "Bedrock OK", 10.0, None))
    else:
        code, message = anthropic
        monkeypatch.setattr(canary, "check_anthropic", lambda ts: (False, message, 10.0, code))

    extras = {
        "subscribe_cleanup": {"ok": True, "message": "canary subscriber row deleted"},
        "subscribe_residue": {
            "ok": residue_rows == 0,
            "message": f"{residue_rows} synthetic canary row(s) survived cleanup (#1954)",
            "residue_rows": residue_rows,
        },
    }
    monkeypatch.setattr(canary, "check_subscribe_flow", lambda ts: (True, "subscribe flow OK", 10.0, extras))

    metrics: list = []
    monkeypatch.setattr(canary, "emit", lambda name, value, unit="Count": metrics.append(name))
    alerts: list = []
    monkeypatch.setattr(canary, "send_alert", lambda failures, ts, dry_run=False: alerts.append(failures))

    state = _StateDDB(prev_failed)

    class _FakeBoto3:
        def client(self, name, region_name=None):
            return state

    monkeypatch.setattr(canary, "boto3", _FakeBoto3())

    resp = canary.lambda_handler(event if event is not None else {}, None)
    return resp, json.loads(resp["body"]), alerts, metrics, state


def as_invoke_result(tmp_path, resp, name="canary.json"):
    """Write the handler's return value exactly as `aws lambda invoke` would land it.

    The full envelope, `body` left as the JSON-ENCODED STRING the handler produced — that
    encoding is half of the seam (#1831: the oracle never looked inside `body` at all for
    two years), so re-serialising it as a dict here would test a payload production never
    emits.
    """
    path = tmp_path / name
    path.write_text(json.dumps(resp), encoding="utf-8")
    return str(path)


def gate_exit_code(tmp_path, resp, name="canary.json"):
    """The number the 'Verify canary' step would have exited with, via the REAL oracle."""
    verdict, detail = oracle.decide(as_invoke_result(tmp_path, resp, name), ok_extra=("healthy",))
    return (0 if verdict == "PASS" else 1), verdict, detail


# ══════════════════════════════════════════════════════════════════════════════
# §1 — the seam, end to end: the incident, and its opposite-direction control
# ══════════════════════════════════════════════════════════════════════════════


def test_THE_INCIDENT_the_real_handler_body_no_longer_gates_the_real_oracle(monkeypatch, tmp_path):
    """Box 1, across the wire. The 2026-09-15 run, replayed through both components."""
    resp, body, _alerts, _metrics, _state = run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE))
    code, verdict, detail = gate_exit_code(tmp_path, resp)
    assert code == 0, (
        f"the 2026-09-15 payload still gates ({verdict}: {detail}) — this is `Auto-rollback (smoke failure)` "
        "stripping 85 Lambdas back out on a vendor 503 all over again"
    )
    assert body["failed_deploy_health"] == 0
    assert body["failed_external_transient"] == 1, "demoted, never dropped — a non-gating failure must still be counted"
    assert body["all_pass"] is False, "the union counter must stay honest: something DID fail"
    assert resp["statusCode"] == 200, "statusCode is the INFRA verdict, and infra was clean"


def test_THE_CONTROL_access_denied_on_the_SAME_check_still_gates_the_real_oracle(monkeypatch, tmp_path):
    """Box 2, across the wire — the load-bearing half.

    Losing `bedrock:InvokeModel` in a CDK change is precisely what a bad deploy looks like:
    the code that just shipped is a plausible cause and a rollback is a plausible fix. Same
    check, same handler, same oracle, opposite verdict. Without this the fix is a hole.
    """
    resp, body, _a, _m, _s = run_canary(monkeypatch, anthropic=(DEPLOY_PLAUSIBLE_CODE, DEPLOY_PLAUSIBLE_MESSAGE))
    code, verdict, _detail = gate_exit_code(tmp_path, resp)
    assert code == 1 and verdict == "FAIL", (
        "AccessDenied on the inference path no longer gates — a deploy that dropped bedrock:InvokeModel "
        "would now ship green. That is a strictly worse failure than the one #3830 fixed."
    )
    assert body["failed_deploy_health"] == 1
    assert body["failed_external_transient"] == 0
    assert resp["statusCode"] == 500


def test_a_real_infra_outage_on_OUR_OWN_round_trip_still_gates(monkeypatch, tmp_path):
    """The conservative default, end to end. DynamoDB is ours; its unavailability is
    exactly the thing this gate is for, and no failure code demotes it."""
    resp, body, _a, _m, _s = run_canary(monkeypatch, ddb_ok=False)
    code, _v, _d = gate_exit_code(tmp_path, resp)
    assert code == 1 and body["failed_deploy_health"] == 1
    assert body["failed_external_transient"] == 0


def test_2051_has_not_regressed_across_the_seam(monkeypatch, tmp_path):
    """A twelve-day-old synthetic subscriber row still does not gate, and still lands in
    `stored_state` rather than being swept into the new lane."""
    resp, body, _a, _m, _s = run_canary(monkeypatch, residue_rows=1)
    code, _v, _d = gate_exit_code(tmp_path, resp)
    assert code == 0
    assert body["failed_stored_state"] == 1 and body["failed_external_transient"] == 0


def test_a_fully_healthy_run_passes_and_claims_nothing(monkeypatch, tmp_path):
    """The vacuity control for this whole file: if the seam passed everything, every
    assertion above would be green for the wrong reason."""
    resp, body, _a, _m, _s = run_canary(monkeypatch)
    code, _v, _d = gate_exit_code(tmp_path, resp)
    assert code == 0 and body["all_pass"] is True
    assert body["failed_deploy_health"] == 0 and body["failed_external_transient"] == 0 and body["failed_stored_state"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# §2 — WATCHED MUTATIONS. Box 1 says "proved by a watched mutation, not by
#      reading", so each mutation removes one piece of the fix and asserts the
#      seam goes BACK to reverting the fleet. A mutation that does not flip the
#      verdict means the test above it is not measuring what it claims.
# ══════════════════════════════════════════════════════════════════════════════


def _registry_without(code):
    """A copy of TRANSIENT_FAILURE_CODES with `code` removed from every check."""
    return {k: frozenset(v) - {code} for k, v in cl.TRANSIENT_FAILURE_CODES.items()}


def test_MUTATION_removing_the_503_from_the_registry_makes_it_gate_again(monkeypatch, tmp_path):
    """M1 — the direct mutation of box 1's classification."""
    monkeypatch.setattr(cl, "TRANSIENT_FAILURE_CODES", _registry_without(INCIDENT_CODE))
    resp, body, _a, _m, _s = run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE))
    code, _v, _d = gate_exit_code(tmp_path, resp)
    assert code == 1, "mutation did not take — the incident test is not measuring the classification"
    assert body["failed_deploy_health"] == 1 and body["failed_external_transient"] == 0


def test_MUTATION_an_empty_registry_regates_every_transient(monkeypatch, tmp_path):
    """M2 — the vacuity control. An empty registry must reproduce the pre-#3831 world
    exactly, which is the world in which 85 Lambdas were reverted."""
    monkeypatch.setattr(cl, "TRANSIENT_FAILURE_CODES", {})
    resp, body, _a, _m, _s = run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE))
    code, _v, _d = gate_exit_code(tmp_path, resp)
    assert code == 1, "mutation did not take — an empty registry must not still demote"
    assert body["failed_external_transient"] == 0


def test_MUTATION_a_lane_resolver_that_ignores_the_failure_code_regates_the_503(monkeypatch, tmp_path):
    """M3 — the pre-#3830 resolver: lane from the CHECK alone. #2051's split, unextended.

    Patched in BOTH namespaces on purpose: `canary_lambda` binds `lane_for_result` into its
    own module for `record()`, while `lane_counts`/`lane_summary` call it through
    `canary_lanes`' globals. Patching one and not the other would leave half the body still
    classified the new way — a mutation that half-takes is worse than none.
    """
    monkeypatch.setattr(canary, "lane_for_result", lambda key, entry: cl.lane_for(key))
    monkeypatch.setattr(cl, "lane_for_result", lambda key, entry: cl.lane_for(key))
    resp, body, _a, _m, _s = run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE))
    code, _v, _d = gate_exit_code(tmp_path, resp)
    assert code == 1, "mutation did not take — classifying the FAILURE, not just the check, is what the seam depends on"


def test_MUTATION_classifying_AccessDenied_as_transient_would_open_the_hole(monkeypatch, tmp_path):
    """M4 — the hole control, and the one that matters most.

    If someone widens the registry to cover `AccessDeniedException`, the box-2 test above
    must go red. This proves it would: with the mutation applied, a lost IAM grant ships
    green. A guard whose restrictive direction cannot fail is not a guard.
    """
    widened = dict(cl.TRANSIENT_FAILURE_CODES)
    widened["anthropic"] = frozenset(widened.get("anthropic", frozenset())) | {DEPLOY_PLAUSIBLE_CODE}
    monkeypatch.setattr(cl, "TRANSIENT_FAILURE_CODES", widened)
    resp, _body, _a, _m, _s = run_canary(monkeypatch, anthropic=(DEPLOY_PLAUSIBLE_CODE, DEPLOY_PLAUSIBLE_MESSAGE))
    code, _v, _d = gate_exit_code(tmp_path, resp)
    assert code == 0, "mutation did not take — the AccessDenied control is not measuring what it claims"


def test_MUTATION_dropping_the_counter_from_the_body_makes_the_CI_log_silent(monkeypatch, tmp_path):
    """M5 — the mutation for the LOUDNESS half of box 1, not the gating half.

    De-gating is only defensible if it is not also a mute. Remove the lane counter from the
    body and the annotator must fall silent — which is what proves the annotation test in
    §4 is reading the real counter rather than printing unconditionally.
    """
    resp, _body, _a, _m, _s = run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE))
    body = json.loads(resp["body"])
    body.pop("failed_external_transient")
    resp = {**resp, "body": json.dumps(body)}
    lines: list = []
    printed = oracle.print_non_gating_annotations(as_invoke_result(tmp_path, resp, "muted.json"), "Canary", out=lines.append)
    assert printed == {} and lines == [], "mutation did not take — the annotator prints without reading the counter"


# ══════════════════════════════════════════════════════════════════════════════
# §3 — box 1's other half: demoted is not disarmed
# ══════════════════════════════════════════════════════════════════════════════


def test_the_demoted_transient_STILL_reaches_its_alarm(monkeypatch):
    """`CanaryAnthropicFail` feeds `life-platform-canary-anthropic-failure`. The lane
    decides what GATES; it must not decide what is observed."""
    _resp, _body, _a, metrics, _s = run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE))
    assert "CanaryAnthropicFail" in metrics, "the demoted failure stopped emitting its metric — de-gated has become dark"
    assert "CanaryAnthropicPass" not in metrics


def test_the_demoted_transient_is_STILL_counted_in_the_union(monkeypatch):
    """`failures` and `all_pass` are the honest union across lanes and must not be
    quietly netted off by the demotion."""
    _resp, body, _a, _m, _s = run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE))
    assert body["failures"] == 1 and body["all_pass"] is False
    assert body["lanes"]["external_transient"]["failed_checks"] == ["anthropic"], "the lane must name the check, not just count it"


def test_the_handler_names_the_demoted_failure_in_its_own_log(monkeypatch, capsys):
    """The canary's CloudWatch log is the second place this must be readable."""
    run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE))
    out = capsys.readouterr().out
    assert "EXTERNAL TRANSIENT" in out and INCIDENT_CODE in out
    assert "external-transient 1" in out


# ══════════════════════════════════════════════════════════════════════════════
# §4 — box 1's "named in the CI log", at the surface where the rollback happened
#
# THE REGRESSION THIS CLOSES. #3839 put `canary_gate_retry.py` in front of the
# oracle in the 'Verify canary' step. The wrapper calls `oracle.decide()`, and the
# `::warning` lines lived in `oracle.main()` — so from that merge the canary's
# stored-state annotation (#2051) stopped appearing in the CI log entirely, and
# the external-transient lane never had one. Both lanes were de-gated ON PURPOSE
# and then muted BY ACCIDENT, which is the same inversion at one remove.
# ══════════════════════════════════════════════════════════════════════════════


def _drive_wrapper(monkeypatch, tmp_path, resp, attempts=1):
    """Run the wrapper's REAL live-invoke path with `aws lambda invoke` faked out.

    Fakes `subprocess.run`, not the attempt function, so the annotation call under test is
    reached through the code the workflow actually executes.
    """

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output=False, text=False):
        with open(cmd[-1], "w", encoding="utf-8") as f:
            json.dump(resp, f)
        return _Proc()

    monkeypatch.setattr(cgr.subprocess, "run", fake_run)
    out = tmp_path / "canary.json"
    code = cgr.main(["--out", str(out), "--label", "Canary", "--ok-extra", "healthy", "--attempts", str(attempts)])
    return code


def test_THE_REGRESSION_the_gating_step_names_the_transient_lane_in_the_CI_log(monkeypatch, tmp_path, capsys):
    """Box 1's log half, through the exact path `ci-cd.yml` runs."""
    resp, _body, _a, _m, _s = run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE))
    code = _drive_wrapper(monkeypatch, tmp_path, resp)
    out = capsys.readouterr().out
    assert code == 0, "the transient must not gate through the wrapper either"
    assert "::warning::Canary: 1 external-transient failure(s)" in out, (
        "the demoted lane is not named in the CI log — a finding that no longer gates and no longer " "prints has been muted, not re-routed"
    )
    assert "NOT gating this deploy" in out and "#3830" in out


def test_THE_REGRESSION_the_gating_step_names_the_stored_state_lane_again(monkeypatch, tmp_path, capsys):
    """#2051's annotation, restored to the canary path. This test fails on the tree as it
    stood between #3839 and this change: the wrapper reached a verdict without ever
    reaching the `::warning` that #2051 shipped."""
    resp, _body, _a, _m, _s = run_canary(monkeypatch, residue_rows=1)
    code = _drive_wrapper(monkeypatch, tmp_path, resp)
    out = capsys.readouterr().out
    assert code == 0
    assert "::warning::Canary: 1 stored-state failure(s)" in out, "the canary path lost #2051's annotation again"


def test_a_clean_canary_run_prints_NO_non_gating_warnings(monkeypatch, tmp_path, capsys):
    """The silence control. An annotation that always prints is noise, and noise is how a
    real one gets skipped."""
    resp, _body, _a, _m, _s = run_canary(monkeypatch)
    code = _drive_wrapper(monkeypatch, tmp_path, resp)
    out = capsys.readouterr().out
    assert code == 0
    assert "external-transient failure(s)" not in out and "stored-state failure(s)" not in out


def test_a_retry_attempt_labels_which_LOOK_the_finding_came_from(monkeypatch, tmp_path, capsys):
    """When the gate looks twice, the log must say which look it is annotating — otherwise
    two identical warnings read as two findings."""
    resp, _body, _a, _m, _s = run_canary(monkeypatch, anthropic=(DEPLOY_PLAUSIBLE_CODE, DEPLOY_PLAUSIBLE_MESSAGE), residue_rows=1)
    code = _drive_wrapper(monkeypatch, tmp_path, resp, attempts=2)
    out = capsys.readouterr().out
    assert code == 1, "a persistent deploy-plausible failure must still gate after the retry"
    assert "::warning::Canary: 1 stored-state failure(s)" in out
    assert "::warning::Canary (attempt 2): 1 stored-state failure(s)" in out


def test_the_standalone_oracle_CLI_still_prints_all_three_lanes(tmp_path, capsys):
    """The qa-smoke step still calls `main()` directly; the refactor must not have moved
    the annotations out from under it."""
    payload = {
        "statusCode": 200,
        "body": json.dumps(
            {
                "failed_deploy_health": 0,
                "failed_content_truth": 2,
                "failed_stored_state": 1,
                "failed_external_transient": 3,
            }
        ),
    }
    path = tmp_path / "smoke.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert oracle.main([str(path), "Smoke test"]) == 0
    out = capsys.readouterr().out
    assert "2 content-truth failure(s)" in out
    assert "1 stored-state failure(s)" in out
    assert "3 external-transient failure(s)" in out


def test_every_non_gating_lane_the_canary_publishes_has_an_annotation(monkeypatch, tmp_path):
    """The registry guard. A future fourth non-gating lane must not be able to land
    counted-but-silent — which is exactly how this one did."""
    annotated = {key for key, _label, _why in oracle.NON_GATING_ANNOTATIONS}
    resp, body, _a, _m, _s = run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE), residue_rows=1)
    published = {k for k in body if k.startswith("failed_") and k != "failed_deploy_health"}
    assert published <= annotated, f"the canary publishes non-gating counters with no CI-log annotation: {sorted(published - annotated)}"
    # and the gating counter must NOT be annotated as non-gating
    assert "failed_deploy_health" not in annotated
    del resp, tmp_path


# ══════════════════════════════════════════════════════════════════════════════
# §5 — box 3: the gate may not be more confident than the alerter
# ══════════════════════════════════════════════════════════════════════════════


def test_the_alerter_needs_TWO_observations_before_it_will_email(monkeypatch):
    """Derived from the handler's behaviour, not from a constant or a comment — the bar the
    gate has to match is whatever the alerter actually does."""
    _r, _b, first_run_alerts, _m, _s = run_canary(monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE))
    assert first_run_alerts == [], "the alerter emailed on a first occurrence — the premise of #3830 has changed"
    _r2, _b2, second_run_alerts, _m2, _s2 = run_canary(
        monkeypatch, anthropic=(INCIDENT_CODE, INCIDENT_MESSAGE), prev_failed=(cl.label_for("anthropic"),)
    )
    assert len(second_run_alerts) == 1, "the alerter never emails at all — the suppression has become a mute"


def test_the_gate_asks_for_AT_LEAST_as_much_evidence_as_the_alerter(monkeypatch):
    """#3830 in one assertion. The 2026-09-15 inversion was the gate acting on ONE
    observation while the alerter, looking at the same one, waited for a second. Whatever
    the alerter's bar is, the gate's attempt budget must not be below it."""
    alerter_observations = 2  # asserted behaviourally by the test above
    assert cgr.DEFAULT_ATTEMPTS >= alerter_observations, (
        f"the deploy gate acts on {cgr.DEFAULT_ATTEMPTS} observation(s) where the alerter requires "
        f"{alerter_observations} — the most destructive consumer is once again the most confident (#3830)"
    )


def test_a_single_transient_observation_cannot_gate_even_when_UNCLASSIFIED(monkeypatch, tmp_path):
    """Box 3 is the backstop for the failure modes nobody has named yet. With the registry
    emptied — so the classifier cannot help at all — a failure that clears on the second
    look still must not revert a fleet."""
    monkeypatch.setattr(cl, "TRANSIENT_FAILURE_CODES", {})
    bad, _b, _a, _m, _s = run_canary(monkeypatch, anthropic=("SomeCodeNobodyHasClassifiedYet", "transient"))
    good, _b2, _a2, _m2, _s2 = run_canary(monkeypatch)
    payloads = [bad, good]

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, capture_output=False, text=False):
        with open(cmd[-1], "w", encoding="utf-8") as f:
            json.dump(payloads.pop(0), f)
        return _Proc()

    monkeypatch.setattr(cgr.subprocess, "run", fake_run)
    monkeypatch.setattr(cgr.time, "sleep", lambda s: None)
    code = cgr.main(["--out", str(tmp_path / "c.json"), "--label", "Canary", "--ok-extra", "healthy", "--attempts", "2", "--delay", "0"])
    assert code == 0, "a single unclassified observation still reverts the fleet — box 3's backstop is not holding"
    assert payloads == [], "the retry never happened"


# ══════════════════════════════════════════════════════════════════════════════
# §6 — box 4: the classification lives in canary_lanes.py alone
# ══════════════════════════════════════════════════════════════════════════════


#: A named exception CLASS, not the bare builtin — `except Exception:` is control flow,
#: `"ServiceUnavailableException"` is a classification decision.
_EXCEPTION_CLASS = re.compile(r"\b[A-Z][A-Za-z]{2,}Exception\b")


def _live_string_literals(path):
    """Every string literal in a module EXCEPT docstrings, via AST.

    Deliberately narrower than a grep over the file. Box 4 forbids the gate side from
    *deciding* anything per-check; it does not forbid the incident narrative, and both of
    these files earn their keep by carrying it. Comments vanish with the parse and
    docstrings are excluded explicitly, so what is left is the literals the code can
    actually branch on.
    """
    tree = ast.parse(open(path, encoding="utf-8").read())
    docs = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            first = node.body[0] if node.body else None
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docs.add(id(first.value))
    return [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


@pytest.mark.parametrize("module", ["smoke_oracle_decision.py", "canary_gate_retry.py"])
def test_the_gate_side_names_no_check_and_no_exception_class(module):
    """Neither the gate reader nor the retry wrapper may grow per-check string matching.
    They read lane COUNTERS by key; which failures land in which counter is decided once,
    in `lambdas/operational/canary_lanes.py`. That scattering is how #1921's reasoning got
    lost, and re-scattering it is how #3830 comes back."""
    literals = _live_string_literals(os.path.join(_LIB, module))
    named = sorted(lit for lit in literals if lit in cl.CHECK_LANES)
    assert not named, f"{module} carries the check name(s) {named} as a live literal (#3830 box 4)"
    classes = sorted({m for lit in literals for m in _EXCEPTION_CLASS.findall(lit)})
    assert not classes, f"{module} names exception classes {classes} — that judgement belongs to canary_lanes.py"


def test_the_workflow_step_names_no_check_and_no_exception_class():
    """Same rule at the outermost layer. The 'Verify canary' step calls the wrapper and
    reads its exit code; it must not have grown an `if` on a failure string."""
    wf = open(os.path.join(_REPO, ".github", "workflows", "ci-cd.yml"), encoding="utf-8").read()
    parts = wf.split("- name: Verify canary", 1)
    assert len(parts) == 2, "the 'Verify canary' step was renamed — re-point this assertion, do not delete it"
    step = parts[1].split("\n      - name:", 1)[0].split("\n  # ", 1)[0]
    # Comments are stripped first: the step's comment block tells the 2026-09-15 story by
    # name and should. What box 4 forbids is the SHELL branching on it.
    runnable = "\n".join(line for line in step.splitlines() if not line.lstrip().startswith("#"))
    assert _EXCEPTION_CLASS.search(runnable) is None, "the workflow step matches on an exception class (#3830 box 4)"
    assert "failed_external_transient" not in runnable, "the workflow reads a lane counter itself instead of trusting the wrapper"
    assert "canary_gate_retry.py" in runnable


def test_the_registry_of_lanes_is_still_the_single_source(monkeypatch):
    """The handler resolves its lanes through `canary_lanes`, not a local copy — proved by
    mutating the module and watching the handler's output change."""
    monkeypatch.setattr(cl, "CHECK_LANES", {**cl.CHECK_LANES, "anthropic": cl.LANE_STORED_STATE})
    _r, body, _a, _m, _s = run_canary(monkeypatch, anthropic=(DEPLOY_PLAUSIBLE_CODE, DEPLOY_PLAUSIBLE_MESSAGE))
    assert (
        body["failed_stored_state"] == 1 and body["failed_deploy_health"] == 0
    ), "mutation did not take — the handler is not reading canary_lanes.CHECK_LANES at call time"
