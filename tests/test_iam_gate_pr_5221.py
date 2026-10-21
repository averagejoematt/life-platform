"""#5221 — the additive-IAM gate at PR time: the PR's synth against the base tip's synth.

The negative control is the 2026-10-20 incident shape on the REAL wire: the #2834 fixture is
a slice of an actual `cdk synth` of LifePlatformEmail that already carries an EventBridge
schedule rule targeting the daily-brief Lambda plus the `AWS::Lambda::Permission`
CloudFormation needs for it. The base side is that slice with the rule + permission removed,
the head side is the slice as synthesized — i.e. "a PR adding an EventBridge rule that targets
a Lambda". It must red, naming the stack and the permission; the rule ALONE (no permission)
must not, so the control discriminates on the resource policy and not on "something changed".

The driver is run through its real CLI entry (`main`) with pre-synthesized dirs, so the
gate subprocess, the decision record and the annotation lines are all exercised; only the
`cdk synth` legs are skipped (they are proved on the lane by a real synth of the incident
commits, stated on the PR).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))
sys.path.insert(0, str(ROOT / "tests"))

import check_iam_additive_pr as pr  # noqa: E402
import workflow_path_checks as wpc  # noqa: E402
from cdk_constants_env import committed_cdk_constants  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "iam_additive_gate" / "LifePlatformEmail.slice.template.json"
WORKFLOW = ROOT / ".github" / "workflows" / "iam-gate-pr.yml"
STACK = "LifePlatformEmail"
RULE = "DailyBriefSchedule99515B48"
PERMISSION = "DailyBriefScheduleAllowEventRuleLifePlatformEmailDailyBriefDC5205DAA1BA5E7D"
ACCOUNT_ENV = "aws://205930651321/us-west-2"


def _slice() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _cdk_out(path: Path, templates: dict[str, dict]) -> Path:
    path.mkdir(parents=True)
    artifacts = {}
    for stack, template in templates.items():
        (path / f"{stack}.template.json").write_text(json.dumps(template), encoding="utf-8")
        artifacts[stack] = {
            "type": "aws:cloudformation:stack",
            "environment": ACCOUNT_ENV,
            "properties": {"templateFile": f"{stack}.template.json"},
        }
    (path / "manifest.json").write_text(json.dumps({"artifacts": artifacts}), encoding="utf-8")
    return path


def _without(template: dict, *logical_ids: str) -> dict:
    out = copy.deepcopy(template)
    for lid in logical_ids:
        del out["Resources"][lid]
    return out


def _argv(tmp_path: Path, head: dict[str, dict], base: dict[str, dict], *extra: str) -> list[str]:
    h = _cdk_out(tmp_path / "head", head)
    b = _cdk_out(tmp_path / "base", base)
    return ["check_iam_additive_pr.py", "--head-synth", str(h), "--base-synth", str(b), "--work", str(tmp_path / "work"), *extra]


@pytest.fixture
def run(tmp_path, capsys, monkeypatch):
    monkeypatch.delenv("IAM_GATE_ACK", raising=False)

    def _go(head: dict[str, dict], base: dict[str, dict], *extra: str) -> tuple[int, str]:
        argv = _argv(tmp_path, head, base, *extra)
        with committed_cdk_constants():
            code = pr.main(argv)
        return code, capsys.readouterr().out

    return _go


def test_fixture_carries_the_incident_pair():
    res = _slice()["Resources"]
    assert res[RULE]["Type"] == "AWS::Events::Rule"
    assert res[PERMISSION]["Type"] == "AWS::Lambda::Permission"
    assert res[PERMISSION]["Properties"]["Principal"] == "events.amazonaws.com"


def test_negative_control_a_new_rule_targeting_a_lambda_reds_naming_stack_and_statement(run):
    code, out = run({STACK: _slice()}, {STACK: _without(_slice(), RULE, PERMISSION)})
    assert code == 1, out
    assert f"::error title=IAM gate OWNER-REQUIRED: {STACK}::new-iam-resource {PERMISSION}: AWS::Lambda::Permission" in out
    assert f"::error title=IAM gate OWNER-REQUIRED::{STACK} — this PR would strand main's Plan" in out


def test_the_rule_alone_does_not_red__the_control_discriminates_on_the_permission(run):
    head = _without(_slice(), PERMISSION)
    code, out = run({STACK: head}, {STACK: _without(_slice(), RULE, PERMISSION)})
    assert code == 0, out
    assert "::error" not in out


def test_identical_synths_pass(run):
    code, out = run({STACK: _slice()}, {STACK: _slice()})
    assert code == 0, out
    assert "no stack reads OWNER-REQUIRED" in out


def test_ack_label_downgrades_to_a_warning_that_still_names_the_statement(run):
    code, out = run({STACK: _slice()}, {STACK: _without(_slice(), RULE, PERMISSION)}, "--ack")
    assert code == 0, out
    assert "::error" not in out
    assert f"::warning title=IAM gate OWNER-REQUIRED: {STACK}::new-iam-resource {PERMISSION}" in out
    assert "owner-required-ack" in out


def test_ack_arrives_from_the_workflow_env(run, monkeypatch):
    monkeypatch.setenv("IAM_GATE_ACK", "true")
    code, out = run({STACK: _slice()}, {STACK: _without(_slice(), RULE, PERMISSION)})
    assert code == 0 and "::warning title=IAM gate acknowledged" in out


def test_a_new_stack_absent_from_the_base_fails_closed(run):
    code, out = run({STACK: _slice(), "LifePlatformNew": _slice()}, {STACK: _slice()})
    assert code == 1, out
    assert "LifePlatformNew::unevaluable" in out


def test_a_broken_synth_is_red_even_with_the_label(tmp_path, capsys):
    """No manifest = nothing was decided: the gate records `<manifest>` unevaluable, and the label cannot excuse it."""
    missing = str(tmp_path / "missing")
    with committed_cdk_constants():
        code = pr.main(["x", "--head-synth", missing, "--base-synth", missing, "--work", str(tmp_path / "w"), "--ack"])
    out = capsys.readouterr().out
    assert code == 1, out
    assert "::error title=IAM gate unevaluable" in out
    assert pr.decide(2, None, ack=True)[0] == 1


def test_decide_is_exit_zero_only_on_a_clean_gate_or_an_acknowledged_finding():
    rec = {"stacks": {STACK: {"verdict": "OWNER-REQUIRED", "findings": [{"kind": "k", "logical_id": "L", "detail": "d"}]}}}
    assert pr.decide(0, rec, ack=False)[0] == 0
    assert pr.decide(1, rec, ack=False)[0] == 1
    assert pr.decide(1, rec, ack=True)[0] == 0
    assert pr.decide(1, {"stacks": {STACK: {"verdict": "NO-IAM-CHANGE"}}}, ack=False)[0] == 1  # nonzero with nothing named


# ── the workflow wiring ──────────────────────────────────────────────────────


def _wf() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_triggers_on_the_issue_paths_and_on_label_changes():
    on = _wf().get("on") or _wf().get(True)
    prt = on["pull_request"]
    assert prt["branches"] == ["main"]
    assert {"labeled", "unlabeled", "synchronize", "opened"} <= set(prt["types"])
    assert {"cdk/**", "config/schedules.json", "deploy/check_iam_additive_pr.py", "deploy/iam_additive_gate.py"} <= set(prt["paths"])


def test_path_filter_attaches_the_check_through_the_watcher_derivation():
    name = _wf()["jobs"]["gate"]["name"]
    for changed in (["cdk/stacks/serve_stack.py"], ["config/schedules.json"]):
        assert name in wpc.checks_for_paths(changed), changed
    assert name not in wpc.checks_for_paths(["docs/README.md"])


def test_gate_step_is_unpiped_blocking_and_needs_no_aws():
    wf = _wf()
    assert "id-token" not in (wf.get("permissions") or {})
    steps = wf["jobs"]["gate"]["steps"]
    gate = [s for s in steps if "check_iam_additive_pr.py" in (s.get("run") or "")]
    assert len(gate) == 1
    step = gate[0]
    assert "continue-on-error" not in step
    assert "|" not in step["run"] and "||" not in step["run"]
    assert "--base-sha" in step["run"]
    assert "owner-required-ack" in step["env"]["IAM_GATE_ACK"]
    assert not any("aws-role" in (s.get("with") or {}) for s in steps)
