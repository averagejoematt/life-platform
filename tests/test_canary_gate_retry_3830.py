"""tests/test_canary_gate_retry_3830.py — #3830 box 3: retry-before-gate on the canary.

THE CLASS, measured: on 2026-09-15T19:55Z a Bedrock `ServiceUnavailableException` reached
three consumers of ONE datapoint. The alerter suppressed it as a first occurrence, the
alarm fired and self-cleared in 15 minutes, and the deploy gate reverted 85 Lambdas. The
most destructive consumer was the most confident, on the least evidence.

These tests hold BOTH directions. The permissive one (a transient does not gate) is
useless without its opposite (a persistent fault still does) — a guard that only
demonstrates the permissive direction is how #2051 recurred, which is #3830's own box 2.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
LIB = ROOT / "deploy" / "lib"


def _load():
    spec = importlib.util.spec_from_file_location("_canary_gate_retry_3830", LIB / "canary_gate_retry.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


cgr = _load()


def scripted(*verdicts):
    """An `invoke` that returns the given verdicts in order, recording the call count."""
    calls = []

    def invoke(n):
        calls.append(n)
        return verdicts[n - 1]

    invoke.calls = calls
    return invoke


def drive(*verdicts, attempts=2):
    inv = scripted(*verdicts)
    got = cgr.run_attempts(inv, attempts, delay=0, sleep=lambda _s: None, log=lambda *_a: None)
    return inv, got, cgr.gate(got)


# ── the permissive direction: the incident, replayed ─────────────────────────────────────
def test_THE_INCIDENT_a_transient_then_green_does_NOT_gate_the_deploy():
    """attempt 1 FAIL (the Bedrock 503), attempt 2 PASS → exit 0. 85 Lambdas stay deployed."""
    _inv, _got, (code, summary) = drive(("FAIL", "body failed_deploy_health=1"), ("PASS", "200"))
    assert code == 0
    assert "attempt 2 of 2" in summary and "did NOT gate" in summary


def test_the_retry_is_VISIBLE_in_the_log_by_name_not_silent():
    """A retry nobody can see is indistinguishable from a gate that stopped working."""
    lines = []
    cgr.run_attempts(scripted(("FAIL", "503"), ("PASS", "200")), 2, delay=0, sleep=lambda _s: None, log=lines.append)
    assert len(lines) == 1
    assert "attempt 1/2" in lines[0] and "#3830" in lines[0] and "re-invoking" in lines[0]
    assert lines[0].startswith("::warning::"), "the retry must surface as a CI annotation, not buried in stdout"


# ── the opposite direction: the must-fail control ────────────────────────────────────────
def test_MUST_FAIL_a_persistent_failure_across_every_attempt_STILL_GATES():
    """Without this the change is not a retry, it is a disabled gate."""
    _inv, _got, (code, summary) = drive(("FAIL", "failed_deploy_health=3"), ("FAIL", "failed_deploy_health=3"))
    assert code == 1
    assert "all 2 attempt(s) failed" in summary and "not a first-occurrence transient" in summary


def test_a_persistent_access_denied_still_gates_through_every_attempt():
    """#3830 box 2's opposite-direction control, and note HOW it is satisfied: by
    repetition, not by an exemption list. Nothing here reads the words 'AccessDenied' —
    a persistent fault simply fails the second look too."""
    _inv, _got, (code, _s) = drive(
        ("FAIL", "AccessDeniedException on bedrock:InvokeModel"),
        ("FAIL", "AccessDeniedException on bedrock:InvokeModel"),
    )
    assert code == 1
    src = (LIB / "canary_gate_retry.py").read_text(encoding="utf-8")
    assert "AccessDenied" not in src.replace(
        "AccessDenied direction", ""
    ), "the retry must not string-match a check or exception (#3830 box 4)"


@pytest.mark.parametrize("bad", ["FAIL", "PARSE_ERROR"])
def test_every_gating_verdict_is_retried_and_still_gates_when_it_persists(bad):
    _inv, _got, (code, _s) = drive((bad, "x"), (bad, "x"))
    assert code == 1
    assert cgr.is_gating(bad)


def test_a_parse_error_that_clears_on_the_retry_does_not_gate():
    """#1345 made an unreadable oracle gating. A truncated payload is as likely to be a
    one-off as an unhealthy system, so it earns the same second look."""
    _inv, _got, (code, _s) = drive(("PARSE_ERROR", "Expecting value"), ("PASS", "healthy"))
    assert code == 0


# ── cost and shape ───────────────────────────────────────────────────────────────────────
def test_a_healthy_canary_costs_exactly_ONE_invocation():
    inv, got, (code, summary) = drive(("PASS", "200"), ("PASS", "200"))
    assert inv.calls == [1], "a passing first look must not pay for a second invoke"
    assert len(got) == 1 and code == 0 and "first look" in summary


def test_it_stops_at_the_first_pass_rather_than_running_the_whole_budget():
    inv, got, (code, _s) = drive(("FAIL", "x"), ("PASS", "ok"), ("FAIL", "x"), attempts=3)
    assert inv.calls == [1, 2] and len(got) == 2 and code == 0


def test_an_empty_verdict_list_GATES_rather_than_failing_open():
    code, summary = cgr.gate([])
    assert code == 1 and "never fail open" in summary or "gating rather than failing open" in summary


def test_the_attempt_budget_is_bounded():
    """A deploy gate that retries all afternoon is its own outage."""
    assert cgr.MAX_ATTEMPTS <= 5 and cgr.DEFAULT_ATTEMPTS == 2


def test_the_verdict_vocabulary_comes_from_the_shared_oracle_not_a_second_copy():
    """One oracle, one definition of healthy (#1345's CLI contract)."""
    src = (LIB / "canary_gate_retry.py").read_text(encoding="utf-8")
    assert "import smoke_oracle_decision as oracle" in src
    assert "oracle.decide(" in src
    assert "failed_deploy_health" not in src, "the lane decision belongs to the oracle + canary_lanes.py, not here"


def test_MUTATION_treating_a_gating_verdict_as_non_gating_would_break_the_must_fail_control(monkeypatch):
    """Prove the control can actually fail: widen GATING_VERDICTS to nothing and the
    persistent-failure case flips to PASS. If this mutation did NOT flip it, the
    must-fail test above would be passing for the wrong reason."""
    monkeypatch.setattr(cgr, "GATING_VERDICTS", frozenset())
    code, _s = cgr.gate([("FAIL", "x"), ("FAIL", "x")])
    assert code == 0, "mutation did not take — the must-fail control is not measuring what it claims"


# ── the workflow seam ────────────────────────────────────────────────────────────────────
def test_the_ci_workflow_gates_the_canary_THROUGH_this_wrapper():
    """A retry nothing calls is not a fix. The 'Verify canary' step must route through
    here rather than calling the oracle on a single invoke."""
    wf = (ROOT / ".github" / "workflows" / "ci-cd.yml").read_text(encoding="utf-8")
    verify = wf.split("- name: Verify canary", 1)
    assert len(verify) == 2, "the 'Verify canary' step was renamed — re-point this assertion, do not delete it"
    step = verify[1].split("\n  # ", 1)[0].split("\n      - name:", 1)[0]
    assert "canary_gate_retry.py" in step, "the canary step does not go through retry-before-gate (#3830 box 3)"
    assert "smoke_oracle_decision.py /tmp/canary.json" not in step, "the canary still gates on a single un-retried invoke"


def test_the_cli_runs_offline_and_its_exit_code_is_the_verdict(tmp_path):
    """End-to-end through the real CLI with a planted unhealthy payload and attempts=1,
    so no AWS is touched but the exit-code contract is exercised."""
    payload = tmp_path / "canary.json"
    # statusCode 200 deliberately: the numeric >=400 path short-circuits before the body is
    # read, and the lane-aware body is the path this gate actually depends on.
    payload.write_text(json.dumps({"statusCode": 200, "body": {"failed_deploy_health": 2}}), encoding="utf-8")
    out = subprocess.run(
        [sys.executable, str(LIB / "smoke_oracle_decision.py"), str(payload), "Canary", "--ok-extra", "healthy"],
        capture_output=True,
        text=True,
    )
    assert out.returncode == 1, out.stdout + out.stderr
    verdict, detail = cgr.oracle.decide(str(payload), ok_extra=("healthy",))
    assert verdict == "FAIL" and cgr.is_gating(verdict) and "failed_deploy_health" in detail
