"""tests/test_nightly_predraft_4084.py — the nightly pre-draft (#4084).

Three must-agree pairs, each tested on the real shape rather than a restatement:

  1. `mcp.nightly_predraft.JOB` (the one declaration) ↔ `cdk/stacks/mcp_stack.py` — the rule's
     cron, its constant input, its target function, and the dead-man alarm's metric identity.
     Read from the stack's AST, so a CDK edit that drifts from the module reds here.
  2. The rule's constant input ↔ `mcp.handler.lambda_handler`'s dispatch — driven through the
     real handler, so the literal the handler matches is the one the rule sends.
  3. The marker writer (`_mark_draft`) ↔ the reader (`predraft_for`) — round-tripped through the real
     routine IR serializer, the shape DynamoDB actually stores.

Plus the three behaviour contracts the issue names: never commits (source AST + a run with the
Hevy write client booby-trapped), idempotent per target date, honest absence.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from training import hevy_write_client as wc  # noqa: E402
from training.routine_ir import RoutineSpec, deserialize, serialize  # noqa: E402

from mcp import nightly_predraft as npd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STACK = ROOT / "cdk" / "stacks" / "mcp_stack.py"
TARGET = "2026-09-24"
LIFTING = {"label": "Thu full-body A — week 3", "archetype": "full", "session_role": "a", "prescription": {"exposures": []}}
WALK = {"label": "Fri walk — week 3", "archetype": "aerobic"}


# ── fake routine repository: the IR goes through serialize/deserialize on every write ──
class _Repo:
    def __init__(self, routines=()):
        self.items: dict[str, dict] = {}
        self.puts = 0
        for r in routines:
            self.items[r.routine_id] = serialize(r)

    def get_current(self, rid):
        item = self.items.get(rid)
        return deserialize(json.loads(json.dumps(item, default=str))) if item else None

    def put_versioned(self, ir):
        self.puts += 1
        self.items[ir.routine_id] = serialize(ir)
        return ir

    def list_by_date_range(self, start, end):
        return [self.get_current(rid) for rid, it in self.items.items() if start <= it["target_date"] <= end]


def _ir(rid="r-ideal", **kw):
    base = dict(routine_id=rid, target_date=TARGET, archetype="full")
    base.update(kw)
    return RoutineSpec(**base)


def _critics_record(model_ran=True, veto=False):
    return {
        "verdicts": [{"critic": "joints_tendons", "verdict": "approve"}, {"critic": "rate_advocate", "verdict": "change"}],
        "binding": {"routine_id": "r-ideal", "version": 3, "content_hash": "x"},
        "model_ran": model_ran,
        "model_paused_reason": None if model_ran else "budget tier 2 — plan_critics paused; deterministic layer only",
        "veto": veto,
        "recheck": {"passed": True},
        "ran_at": "2026-09-24T02:00:10Z",
    }


@pytest.fixture
def repo():
    r = _Repo()
    with (
        patch("training.routine_repo.get_current", side_effect=r.get_current),
        patch("training.routine_repo.put_versioned", side_effect=r.put_versioned),
        patch("training.routine_repo.list_by_date_range", side_effect=r.list_by_date_range),
    ):
        yield r


def _fake_draft(repo):
    def draft(target_date):
        # the real `_action_draft` persists EVERY variant — the ideal and its floor sibling
        repo.put_versioned(_ir(created_by="cron"))
        repo.put_versioned(_ir("r-floor", variant="floor", created_by="cron"))
        return {"status": "drafted", "ideal_routine_id": "r-ideal", "floor_routine_id": "r-floor"}

    return draft


def _fake_stage_2(repo, model_ran=True):
    def stage_2(target_date, rid):
        ir = repo.get_current(rid)
        rec = _critics_record(model_ran=model_ran)
        ir.inputs_snapshot = {**ir.inputs_snapshot, "critics": rec}
        ir.version += 1
        repo.put_versioned(ir)
        return {"critics": {**rec, "routine_version": ir.version}}

    return stage_2


# ── 1. JOB ↔ the CDK stack ────────────────────────────────────────────────────────────
def _literal(node):
    return ast.literal_eval(node)


def _calls(tree, attr):
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) == attr]


def _kw(call, name):
    return next((k.value for k in call.keywords if k.arg == name), None)


def test_cdk_rule_and_deadman_match_the_job_declaration():
    tree = ast.parse(STACK.read_text(encoding="utf-8"))
    consts = {
        t.id: n.value.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant)
        for t in n.targets
        if isinstance(t, ast.Name)
    }

    rules = [c for c in _calls(tree, "Rule") if c.args[1:] and _literal(c.args[1]) == "NightlyPredraft"]
    assert len(rules) == 1, "exactly one NightlyPredraft rule in mcp_stack.py"
    sched = _kw(rules[0], "schedule")
    assert _literal(sched.args[0]) == npd.JOB["schedule_utc"]
    assert _kw(rules[0], "enabled") is None, "the rule must ship enabled — a disabled rule is not a schedule"

    inputs = [c for c in _calls(tree, "from_object") if _literal(c.args[0]) == npd.JOB["event"]]
    assert len(inputs) == 1, f"the rule's constant input must be exactly {npd.JOB['event']}"
    target = next(c for c in _calls(tree, "LambdaFunction") if any(s is inputs[0] for s in ast.walk(c)))
    target_var = target.args[0].id
    fn_assign = next(
        n for n in ast.walk(tree) if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == target_var for t in n.targets)
    )
    fn_name = _kw(fn_assign.value, "function_name")
    assert consts.get(getattr(fn_name, "id", None)) == npd.JOB["function"]

    alarms = [
        c for c in _calls(tree, "Alarm") if _kw(c, "alarm_name") is not None and _literal(_kw(c, "alarm_name")) == npd.JOB["deadman_alarm"]
    ]
    assert len(alarms) == 1
    alarm = alarms[0]
    metric = _kw(alarm, "metric")
    assert _literal(_kw(metric, "namespace")) == npd.JOB["metric_namespace"]
    assert _literal(_kw(metric, "metric_name")) == npd.JOB["metric_name"]
    assert _literal(_kw(metric, "dimensions_map")) == npd.JOB["metric_dimension"]
    assert _literal(_kw(metric, "period").args[0]) == npd.JOB["deadman_period_s"]
    assert _literal(_kw(alarm, "evaluation_periods")) == npd.JOB["deadman_periods"]
    assert _literal(_kw(alarm, "datapoints_to_alarm")) == npd.JOB["deadman_periods"]
    assert _kw(alarm, "treat_missing_data").attr == "BREACHING", "absence must be the failure (missing = BREACHING)"
    # the window must close on the 02:00-03:00Z bucket: 24 hourly buckets == one day
    assert npd.JOB["deadman_period_s"] * npd.JOB["deadman_periods"] == 86400


def test_emf_line_carries_the_alarms_metric_identity_and_only_for_honest_outcomes():
    for outcome in npd.HONEST_OUTCOMES:
        rec = json.loads(npd.emf_line(outcome))
        spec = rec["_aws"]["CloudWatchMetrics"][0]
        assert spec["Namespace"] == npd.JOB["metric_namespace"]
        assert spec["Metrics"][0]["Name"] == npd.JOB["metric_name"]
        assert spec["Dimensions"] == [sorted(npd.JOB["metric_dimension"])]
        for k, v in npd.JOB["metric_dimension"].items():
            assert rec[k] == v
        assert rec[npd.JOB["metric_name"]] == 1
    assert npd.emf_line(npd.FAILED) is None, "a failed run must emit NOTHING — the dead-man reads absence"


# ── 2. the rule's input ↔ the handler's dispatch ─────────────────────────────────────
def test_the_handler_routes_the_rules_input_to_the_predraft_and_not_the_warmer():
    from mcp import handler

    with (
        patch("mcp.nightly_predraft.lambda_entry", return_value={"statusCode": 200, "body": "{}"}) as entry,
        patch.object(handler, "nightly_cache_warmer", side_effect=AssertionError("warmer must not run")),
    ):
        handler.lambda_handler(dict(npd.JOB["event"]), None)
    entry.assert_called_once()


# ── 3. never commits ─────────────────────────────────────────────────────────────────
_FORBIDDEN = {
    "_action_commit",
    "create_routine",
    "update_routine_with_guard",
    "create_template",
    "create_folder",
    "tool_manage_hevy_routine",
    "_DISPATCH",
    "hevy_write_client",
}


def test_the_module_source_cannot_reach_a_commit():
    tree = ast.parse(Path(npd.__file__).read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names} | {
        n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    }
    hits = (names | imported) & _FORBIDDEN
    hits |= {m for m in imported if m.endswith("hevy_write_client")}
    assert not hits, f"nightly_predraft must never reach a commit path: {sorted(hits)}"


def test_a_full_run_never_touches_the_hevy_write_client(repo):
    def no_writes(method, *a, **kw):
        raise AssertionError(f"the pre-draft must never write to Hevy (attempted {method})")

    with (
        patch.object(wc, "_request", side_effect=no_writes),
        patch.object(npd, "scheduled_session", return_value=LIFTING),
        patch.object(npd, "_draft", side_effect=_fake_draft(repo)),
        patch.object(npd, "_stage_2", side_effect=_fake_stage_2(repo)),
    ):
        out = npd.run(TARGET)
    assert out["outcome"] == npd.DRAFTED and out["committed"] is False
    stored = repo.get_current("r-ideal")
    assert stored.status == "draft" and not stored.hevy_routine_id


# ── idempotency + ownership ─────────────────────────────────────────────────────────
def test_second_run_for_the_same_date_is_a_no_op(repo):
    draft = _fake_draft(repo)
    with (
        patch.object(npd, "scheduled_session", return_value=LIFTING),
        patch.object(npd, "_draft", side_effect=draft) as d,
        patch.object(npd, "_stage_2", side_effect=_fake_stage_2(repo)) as s2,
    ):
        first = npd.run(TARGET)
        puts_after_first = repo.puts
        second = npd.run(TARGET)
    assert first["outcome"] == npd.DRAFTED
    assert second["outcome"] == npd.EXISTS and second["routine_id"] == "r-ideal"
    assert d.call_count == 1 and s2.call_count == 1 and repo.puts == puts_after_first


def test_a_run_that_died_before_stage_2_resumes_rather_than_redrafting(repo):
    repo.put_versioned(_ir(inputs_snapshot={npd.MARKER: {"drafted_at": "earlier", "role": npd.PRIMARY}}))
    with (
        patch.object(npd, "scheduled_session", return_value=LIFTING),
        patch.object(npd, "_draft", side_effect=AssertionError("must not redraft")),
        patch.object(npd, "_stage_2", side_effect=_fake_stage_2(repo)) as s2,
    ):
        out = npd.run(TARGET)
    assert out["outcome"] == npd.DRAFTED and out["resumed"] is True
    s2.assert_called_once_with(TARGET, "r-ideal")


def test_a_routine_the_predraft_did_not_author_is_never_versioned_over():
    """One test over both owner shapes (a census gate per test, not per parameter)."""
    owner_shapes = [
        _ir("r-owner", created_by="chat"),  # the owner already drafted in chat
        _ir("r-committed", status="active", hevy_routine_id="hv-1"),  # already committed
    ]
    offenders = []
    for owner_ir in owner_shapes:
        r = _Repo([owner_ir])
        with (
            patch("training.routine_repo.get_current", side_effect=r.get_current),
            patch("training.routine_repo.put_versioned", side_effect=r.put_versioned),
            patch("training.routine_repo.list_by_date_range", side_effect=r.list_by_date_range),
            patch.object(npd, "scheduled_session", return_value=LIFTING),
            patch.object(npd, "_draft", side_effect=AssertionError("must not draft over the owner's routine")),
            patch.object(npd, "_stage_2", side_effect=AssertionError("must not red-team the owner's routine")),
        ):
            out = npd.run(TARGET)
        if out["outcome"] != npd.SKIPPED_OWNER_ROUTINE or out["routines"][0]["routine_id"] != owner_ir.routine_id or r.puts:
            offenders.append((owner_ir.routine_id, out.get("outcome"), r.puts))
    assert not offenders, offenders


# ── honest absence ──────────────────────────────────────────────────────────────────
def test_no_lifting_session_is_reported_not_guessed(repo):
    """A walk day, and an order-based seam that serves nothing (#4110 v0.4), are both first-class absence."""
    got = {}
    for name, served in (("walk", WALK), ("none", None), ("no_prescription", {"archetype": "upper", "label": "Upper-heavy"})):
        with (
            patch.object(npd, "scheduled_session", return_value=served),
            patch.object(npd, "_draft", side_effect=AssertionError("no session, no draft")),
        ):
            got[name] = npd.run(TARGET)["outcome"]
    assert got == {"walk": npd.NO_SESSION, "none": npd.NO_SESSION, "no_prescription": npd.NO_SESSION}
    assert npd.predraft_for(TARGET)["status"] == "none"


def test_the_draft_decision_is_archetype_agnostic(repo):
    """v0.4 serves `upper` / `lower`: a prescribed session drafts whatever its archetype (#4110)."""
    upper = {"label": "Upper-heavy (session 1 of 4)", "archetype": "upper", "session_role": "upper_heavy", "prescription": {"x": 1}}
    with (
        patch.object(npd, "scheduled_session", return_value=upper),
        patch.object(npd, "_draft", side_effect=_fake_draft(repo)),
        patch.object(npd, "_stage_2", side_effect=_fake_stage_2(repo)),
    ):
        out = npd.run(TARGET)
    assert out["outcome"] == npd.DRAFTED and out["session"]["archetype"] == "upper"
    marker = repo.get_current("r-ideal").inputs_snapshot[npd.MARKER]
    assert marker["session_role"] == "upper_heavy" and marker["role"] == npd.PRIMARY


def test_a_refused_draft_is_blocked_not_overridden(repo):
    with (
        patch.object(npd, "scheduled_session", return_value=LIFTING),
        patch.object(npd, "_draft", return_value={"status": "blocked_stale_inputs", "gaps": [{"input": "recovery"}], "note": "stale"}),
    ):
        out = npd.run(TARGET)
    assert out["outcome"] == npd.BLOCKED_STALE_INPUTS and out["gaps"] == [{"input": "recovery"}]


def test_a_crash_is_failed_and_emits_no_datapoint(capsys):
    with patch.object(npd, "run", side_effect=RuntimeError("boom")):
        resp = npd.lambda_entry(dict(npd.JOB["event"]))
    body = json.loads(resp["body"])
    assert body["outcome"] == npd.FAILED and "RuntimeError" in body["error"]
    assert npd.JOB["metric_name"] not in capsys.readouterr().out


# ── the writer ↔ reader marker contract ──────────────────────────────────────────────
def test_marker_round_trips_and_the_reader_reports_ready_with_the_model_state(repo):
    with (
        patch.object(npd, "scheduled_session", return_value=LIFTING),
        patch.object(npd, "_draft", side_effect=_fake_draft(repo)),
        patch.object(npd, "_stage_2", side_effect=_fake_stage_2(repo, model_ran=False)),
    ):
        npd.run(TARGET)
    got = npd.predraft_for(TARGET)
    assert got["status"] == "ready" and got["routine_id"] == "r-ideal"
    assert got["drafted_at"], "the marker the writer stamped must be readable back through the IR serializer"
    assert got["critics"]["model_ran"] is False
    assert "did not run" in got["how_to_use"], "a paused-model run must never read as red-teamed"


def test_reader_names_an_unfinished_predraft(repo):
    repo.put_versioned(_ir(inputs_snapshot={npd.MARKER: {"drafted_at": "t", "role": npd.PRIMARY}}))
    assert npd.predraft_for(TARGET)["status"] == "drafted_not_red_teamed"


def test_stage_1_attaches_the_predraft_first():
    from training import plan_engine

    from mcp import tools_plan

    def absent(name, fn, *a, **kw):
        return None, plan_engine.input_status(plan_engine.ABSENT, "stubbed")

    ready = {"status": "ready", "how_to_use": "REVIEW the overnight draft.", "routine_id": "r-ideal"}
    with (
        patch.object(tools_plan, "_read", side_effect=absent),
        patch.object(tools_plan, "_catalog_and_ceiling", return_value=(None, 2)),
        patch.object(tools_plan, "_nutrition_critics_block", return_value={"verdicts": []}),
        patch("training.training_notes.training_notes_health", side_effect=RuntimeError("no table")),
        patch("mcp.nightly_predraft.predraft_for", return_value=ready) as pf,
    ):
        out = tools_plan.tool_plan_next_session({"target_date": TARGET})
    pf.assert_called_once_with(TARGET)
    assert out["predraft"] == ready
    assert out["how_to_use"].startswith("REVIEW the overnight draft.")


def test_the_seam_is_the_function_stage_1_uses():
    """#4110 re-points ONE function. Pin that it is stage 1's own session picker today."""
    with (
        patch("mcp.plan_helpers._catalog_and_ceiling", return_value=({"m": {}}, 3)),
        patch("training.plan_engine._scheduled_session", return_value=LIFTING) as picker,
    ):
        assert npd.scheduled_session(TARGET) is LIFTING
    picker.assert_called_once_with(TARGET, {"m": {}}, 3)


def test_an_unreadable_predraft_is_named_never_read_as_none():
    out = {"how_to_use": "stage 1"}
    with patch.object(npd, "predraft_for", side_effect=RuntimeError("ddb down")):
        npd.attach_to_stage_1(out, TARGET)
    assert out["predraft"]["status"] == "unreadable" and "RuntimeError" in out["predraft"]["error"]
    assert out["how_to_use"] == "stage 1"
