"""tests/test_predraft_shadow_switch_5080.py — the plan-source switch, the v0.4 shadow, the frozen v0.4 builder (#5080).

The contracts the issue names, each on the real path:
  * the switch, both directions of the flip, through `nightly_predraft.run` — exactly ONE plan is persisted;
  * FAIL-SAFE: a missing parameter and a missing `ssm:GetParameter` grant both resolve to the default (`charter`);
  * the 60-s cache; the owner-decision default and the one-command revert pinned;
  * the diff report's shape, written Decimal-safe to `SHADOW#<date>`; the shadow window bounds itself;
  * the frozen v0.4 builder is pure and reads nothing live (the charter raising changes nothing);
  * the IAM grant is in the stack and the parameter is NOT CDK-owned (a deploy must never undo a revert).
"""

from __future__ import annotations

import ast
import json
import os
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from botocore.exceptions import ClientError  # noqa: E402
from training import program_v04  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set, deserialize, serialize  # noqa: E402

from mcp import (
    nightly_predraft as npd,  # noqa: E402
    predraft_shadow as ps,  # noqa: E402
)

ROOT = Path(__file__).resolve().parents[1]
# premerge-gate: reads every cdk/stacks/*.py to prove no stack owns the switch parameter (#5080)
TARGET = "2026-10-21"
SESSION = {"label": "Upper-heavy", "archetype": "upper", "session_role": "upper_heavy", "prescription": {"exposures": []}, "deload": False}
CATALOG = json.loads((ROOT / "config" / "movement_catalog.json").read_text(encoding="utf-8"))["movements"]


@pytest.fixture(autouse=True)
def _fresh_cache():
    ps._reset_cache()
    yield
    ps._reset_cache()


def _client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "GetParameter")


# ── the switch ─────────────────────────────────────────────────────────────────────────
def test_the_owner_decision_default_and_the_revert_command_are_pinned():
    assert ps.DEFAULT_SOURCE == ps.CHARTER, "OWNER DECISION (#5080 PR): absence = the charter engine, what is live today"
    assert ps.REVERT_COMMAND == "aws ssm put-parameter --name /life-platform/training-plan-source --value v04 --type String --overwrite"
    assert ps.FORWARD_COMMAND.endswith("--value charter --type String --overwrite")


def test_every_unreadable_switch_is_the_default_and_names_why():
    def raising(exc):
        def get(_name):
            raise exc

        return get

    cases = {
        "parameter_absent": raising(_client_error("ParameterNotFound")),
        "no_permission": raising(_client_error("AccessDeniedException")),
        "read_failed:EndpointConnectionError": raising(type("EndpointConnectionError", (Exception,), {})()),
    }
    offenders = []
    for reason, getter in cases.items():
        ps._reset_cache()
        got = ps.plan_source(getter, now=0.0)
        if (got["source"], got["read"], got["reason"]) != (ps.DEFAULT_SOURCE, "default", reason):
            offenders.append((reason, got))
    ps._reset_cache()
    junk = ps.plan_source(lambda _n: "v0.4-please", now=0.0)
    if junk["source"] != ps.DEFAULT_SOURCE or "unrecognised" not in junk["reason"]:
        offenders.append(("junk value", junk))
    assert not offenders, offenders


def test_both_values_are_read_and_the_read_is_cached_for_60_seconds():
    calls = []

    def get(name):
        calls.append(name)
        return values[-1]

    values = ["v04"]
    assert ps.plan_source(get, now=100.0)["source"] == "v04"
    values.append("charter")
    cached = ps.plan_source(get, now=159.0)
    assert (cached["source"], cached["cached"]) == ("v04", True) and calls == [ps.PARAM_NAME]
    fresh = ps.plan_source(get, now=161.0)
    assert (fresh["source"], fresh["cached"]) == ("charter", False) and len(calls) == 2


# ── the run: both directions of the flip, exactly one plan persisted ───────────────────
class _Repo:
    def __init__(self):
        self.items: dict[str, dict] = {}

    def get_current(self, rid):
        item = self.items.get(rid)
        return deserialize(json.loads(json.dumps(item, default=str))) if item else None

    def put_versioned(self, ir):
        self.items[ir.routine_id] = serialize(ir)
        return ir

    def list_by_date_range(self, start, end, limit=100):
        return [self.get_current(rid) for rid, it in self.items.items() if start <= it["target_date"] <= end]


def _ir(rid, archetype="upper", movements=("barbell_bench_press",)):
    blocks = [ExerciseBlock(movement_key=m, sets=[Set(weight_kg=80.0, reps=5)] * 3, rest_seconds=120) for m in movements]
    return RoutineSpec(routine_id=rid, target_date=TARGET, archetype=archetype, exercises=blocks)


def _stage_2(repo):
    def stage_2(target_date, rid):
        ir = repo.get_current(rid)
        rec = {"verdicts": [], "binding": {"routine_id": rid}, "model_ran": False, "ran_at": "x"}
        ir.inputs_snapshot = {**ir.inputs_snapshot, "critics": rec}
        ir.version += 1
        repo.put_versioned(ir)
        return {"critics": {**rec, "routine_version": ir.version}}

    return stage_2


def _run(repo, source, *, shadow_due=False, put=None):
    switch = {"source": source, "read": "ssm", "reason": "test", "shadow": {"due": shadow_due, "reason": "test"}}
    persisted = []

    def charter_draft(target_date):
        persisted.append("charter")
        repo.put_versioned(_ir("r-charter", movements=("barbell_bench_press", "db_lateral_raise")))
        return {"status": "drafted", "ideal_routine_id": "r-charter"}

    def v04_draft(target_date, plan):
        persisted.append("v04")
        repo.put_versioned(_ir("r-v04", movements=tuple(e["movement_key"] for e in plan["exercises"])))
        return {"status": "drafted", "ideal_routine_id": "r-v04", "plan_source": "v04"}

    writes = []
    with (
        patch("training.routine_repo.get_current", side_effect=repo.get_current),
        patch("training.routine_repo.put_versioned", side_effect=repo.put_versioned),
        patch("training.routine_repo.list_by_date_range", side_effect=repo.list_by_date_range),
        patch.object(npd, "_switch", return_value=switch),
        patch.object(npd, "sweep_expired", return_value={}),
        patch.object(npd, "scheduled_session", return_value=SESSION),
        patch.object(npd, "_disruption", return_value={"phase": None}),
        patch.object(npd, "_block_record", return_value=[]),
        patch.object(npd, "_draft", side_effect=charter_draft),
        patch.object(ps, "draft_v04", side_effect=v04_draft),
        patch.object(ps, "_history_index", return_value={}),
        patch.object(ps, "charter_preview", return_value=_ir("r-preview", movements=("barbell_bench_press", "db_lateral_raise"))),
        patch.object(ps, "write_report", side_effect=lambda report, put=None: writes.append(report)),
        patch.object(npd, "_stage_2", side_effect=_stage_2(repo)),
    ):
        out = npd.run(TARGET)
        out["_reader"] = npd.predraft_for(TARGET)  # what the evening chat's stage 1 shows
    return out, persisted, writes


def test_the_flip_runs_both_directions_and_persists_exactly_one_plan():
    offenders = []
    for source, rid in (("v04", "r-v04"), ("charter", "r-charter"), ("v04", "r-v04")):
        repo = _Repo()
        out, persisted, _ = _run(repo, source)
        marker = (repo.get_current(rid).inputs_snapshot or {}).get(npd.MARKER) or {}
        if (
            out["outcome"] != npd.DRAFTED
            or persisted != [source]
            or out["routine_id"] != rid
            or marker.get("plan_source") != source
            or out["_reader"].get("plan_source") != source
        ):
            offenders.append((source, out.get("outcome"), persisted, marker.get("plan_source")))
        if len(repo.items) != 1:
            offenders.append((source, "more than one routine persisted", sorted(repo.items)))
    assert not offenders, offenders


def test_a_shadow_night_writes_one_report_and_persists_nothing_more():
    for source in ("charter", "v04"):
        repo = _Repo()
        out, persisted, writes = _run(repo, source, shadow_due=True)
        assert persisted == [source] and len(repo.items) == 1, (source, persisted, sorted(repo.items))
        assert out["shadow"]["outcome"] == "recorded" and len(writes) == 1, out["shadow"]
        rep = writes[0]
        assert (rep["persisted"], rep["shadow"]) == (source, "v04" if source == "charter" else "charter")
        assert rep["v04"]["session_role"] in program_v04.V04_TEMPLATES and rep["charter"]["session_role"] == "upper_heavy"


def test_a_failing_shadow_never_changes_the_outcome():
    repo = _Repo()
    with patch.object(ps, "_catalog", side_effect=RuntimeError("s3 down")):
        out, persisted, writes = _run(repo, "charter", shadow_due=True)
    assert out["outcome"] == npd.DRAFTED and persisted == ["charter"] and not writes
    assert out["shadow"]["outcome"] == "failed" and "RuntimeError" in out["shadow"]["error"]


def test_the_v04_draft_honours_the_stale_refusal_and_authors_through_draft_custom_only():
    plan = program_v04.build_session(TARGET, {"credited_sessions": 3, "e1rm_kg": {"squat_barbell": 120.0}})
    with (
        patch("mcp.tools_hevy_routine._authoring_freshness_gate", return_value={"ok": False, "gaps": [{"input": "whoop"}]}),
        patch("mcp.tools_hevy_routine._action_draft_custom", side_effect=AssertionError("must not author on stale inputs")),
    ):
        blocked = ps.draft_v04(TARGET, plan)
    assert blocked["status"] == "blocked_stale_inputs" and blocked["gaps"] == [{"input": "whoop"}]

    seen = []
    with (
        patch("mcp.tools_hevy_routine._authoring_freshness_gate", return_value={"ok": True}),
        patch(
            "mcp.tools_hevy_routine._action_draft_custom",
            side_effect=lambda a: seen.append(a) or {"status": "drafted_custom", "routine_id": "r1"},
        ),
        patch("mcp.tools_hevy_routine._action_draft", side_effect=AssertionError("the charter draft must not run on the v04 path")),
    ):
        ok = ps.draft_v04(TARGET, plan)
    assert ok == {"status": "drafted", "ideal_routine_id": "r1", "plan_source": "v04"}
    sent = seen[0]
    assert sent["archetype"] == plan["archetype"] and [e["movement_key"] for e in sent["exercises"]] == [
        e["movement_key"] for e in plan["exercises"]
    ]
    assert all(len(e["notes"]) <= 150 and "v0.4" in e["notes"] for e in sent["exercises"]), "a short note that carries its reason"


def test_the_shadow_modules_cannot_reach_a_commit():
    forbidden = {
        "_action_commit",
        "create_routine",
        "update_routine_with_guard",
        "tool_manage_hevy_routine",
        "_DISPATCH",
        "hevy_write_client",
    }
    tree = ast.parse((ROOT / "mcp" / "predraft_shadow.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names} | {
        n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
    }
    assert not ((names | imported) & forbidden), sorted((names | imported) & forbidden)


# ── the shadow window ───────────────────────────────────────────────────────────────────
def test_the_shadow_window_bounds_itself():
    rows = [f"SHADOW#2026-10-{d}" for d in range(20, 20 + ps.SHADOW_NIGHTS)]
    cases = [
        (ps.shadow_due(TARGET, lambda: rows[:2]), True),
        (ps.shadow_due("2026-10-30", lambda: rows), False),
        (ps.shadow_due(rows[0][len("SHADOW#") :], lambda: rows), True),  # tonight's own row: a re-run rewrites it
    ]

    def boom():
        raise RuntimeError("ddb down")

    cases.append((ps.shadow_due(TARGET, boom), False))  # an unbounded shadow never runs
    assert [c[0]["due"] for c in cases] == [c[1] for c in cases], cases


# ── the diff report ─────────────────────────────────────────────────────────────────────
def test_the_diff_report_shape_and_its_decimal_safe_write():
    history = {
        "79D0BB3A": [
            {"date": "2026-10-10", "sets": [{"weight_kg": 90.0, "reps": 5}]},
            {"date": TARGET, "sets": [{"weight_kg": 200.0, "reps": 5}]},
        ]
    }
    plan = ps.v04_plan(TARGET, [], history_index=history, catalog=CATALOG)
    assert plan["session_role"] == program_v04.SESSION_SEQUENCE["first_role"], "no credited session: v0.4's first role"
    charter = ps.charter_side(_ir("r", movements=("barbell_bench_press", "db_lateral_raise")), SESSION, CATALOG)
    report = ps.diff_report(TARGET, ps.CHARTER, charter, ps.v04_side(plan, CATALOG), "2026-10-21T02:00:00Z")
    expected_keys = {
        "sk",
        "target_date",
        "persisted",
        "shadow",
        "charter",
        "v04",
        "diff",
        "summary",
        "revert_command",
        "recorded_at",
        "tier",
    }
    side_keys = {"session_role", "exercises", "total_sets", "lifting_minutes", "cardio_blocks", "steps_target", "deload"}
    diff_keys = {"role", "only_charter", "only_v04", "total_sets", "lifting_minutes", "cardio_blocks", "steps_target", "deload"}
    offenders = [k for k in expected_keys if k not in report]
    offenders += [f"charter.{k}" for k in side_keys if k not in report["charter"]] + [
        f"v04.{k}" for k in side_keys if k not in report["v04"]
    ]
    offenders += [f"diff.{k}" for k in diff_keys if k not in report["diff"]]
    assert not offenders, offenders
    assert report["sk"] == f"SHADOW#{TARGET}" and report["v04"]["steps_target"] is None and report["charter"]["steps_target"]["floor"]
    assert "db_lateral_raise" in report["diff"]["only_charter"] and "\n" not in report["summary"] and "vs v0.4" in report["summary"]

    put = []
    ps.write_report(report, put.append)
    item = put[0]
    assert item["pk"] == "USER#matthew#SOURCE#training_constraints" and item["sk"] == f"SHADOW#{TARGET}"

    def floats(o):
        if isinstance(o, float):
            return [o]
        if isinstance(o, dict):
            return [f for v in o.values() for f in floats(v)]
        if isinstance(o, list):
            return [f for v in o for f in floats(v)]
        return []

    assert floats(item) == [] and isinstance(item["charter"]["lifting_minutes"], Decimal), "boto3 rejects float"


def test_e1rm_ignores_sessions_on_or_after_the_target_day():
    history = {
        "79D0BB3A": [
            {"date": "2026-10-10", "sets": [{"weight_kg": 90.0, "reps": 5}]},
            {"date": TARGET, "sets": [{"weight_kg": 200.0, "reps": 5}]},
        ]
    }
    got = ps.e1rm_by_movement(TARGET, history, CATALOG, ["barbell_bench_press", "machine_row"])
    assert got == {"barbell_bench_press": 105.0}


# ── the frozen v0.4 builder ─────────────────────────────────────────────────────────────
def test_the_frozen_builder_is_pure_and_reads_nothing_live():
    def no_live(*a, **k):
        raise AssertionError("the frozen v0.4 builder read a live charter value")

    with patch("training.training_charter.charter_value", side_effect=no_live):
        plan = program_v04.build_session("2026-10-21", {"credited_sessions": 5, "e1rm_kg": {"barbell_bench_press": 110.0}})
    assert (
        plan["program_version"] == "0.4" and plan["steps_target"] is None and plan["cardio_block"] is None and plan["progression"] is None
    )


def test_the_frozen_builder_serves_v04s_order_ramp_and_deload():
    roles = [program_v04.v04_role(n) for n in range(5)]
    assert roles == ["lower_heavy", "upper_volume", "lower_volume", "upper_heavy", "lower_heavy"]
    assert program_v04.v04_week("2026-09-24", 0) == 1 and program_v04.v04_week("2026-10-21", 8) == 3  # sessions AND days
    wk1 = program_v04.build_session("2026-09-25", {"role": "upper_heavy", "e1rm_kg": {"barbell_bench_press": 100.0}})
    top = wk1["exercises"][0]["sets"][0]
    assert wk1["ramp_pct"] == 60 and top["kind"] == "top" and top["load_lb"] == 130.0  # 60 % x 100 kg = 132 lb -> 130
    on = program_v04.build_session("2026-11-05", {"role": "upper_volume"})
    off = program_v04.build_session("2026-11-12", {"role": "upper_volume"})
    assert on["deload"]["on"] and not off["deload"]["on"] and on["total_sets"] < off["total_sets"]


def test_every_frozen_movement_is_in_the_catalog():
    keys = {a[2] for t in program_v04.V04_TEMPLATES.values() for a in t["anchors"]} | {
        k for t in program_v04.V04_TEMPLATES.values() for k in t["accessories"]
    }
    assert sorted(k for k in keys if k not in CATALOG) == []
    assert set(program_v04.V04_TEMPLATES) == set(program_v04.SESSION_SEQUENCE["session_roles"])


# ── the stack: the read grant is there; the parameter is not CDK-owned ──────────────────
def test_the_grant_exists_and_the_parameter_is_not_cdk_owned():
    import sys

    sys.path.insert(0, str(ROOT / "cdk"))
    from stacks import role_policies_serve as rp

    arns = [r for st in rp.mcp_server() for r in st.resources if ":ssm:" in r]
    assert any(a.endswith(f"parameter{ps.PARAM_NAME}") for a in arns), arns
    stacks = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "cdk" / "stacks").glob("*.py"))
    assert "StringParameter" not in stacks, "a CDK-owned value would be re-asserted on every deploy and undo a revert"
