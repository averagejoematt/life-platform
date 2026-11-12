"""tests/test_stage1_reads_5813.py — plan_next_session's stage-1 read set: one read per partition/range per call.

Live, 2026-11-11 (read-only profile, draft_custom routine f4569682, every non-read AWS call refused, model off):
stage 1 made ~420 DynamoDB queries in 13-21 s on a laptop, and 252 of them were ONE function —
`training.training_notes.training_notes_health`, the note layer's ~28-query health sweep — run once in stage 1
and once more per drafted exercise inside `tool_get_exercise_notes`. The rest of the duplicates were
`core.query_source` re-reading the same (source, window) for several readers and the template alias registry
(three S3 reads) once per drafted exercise. `plan_call_scope` now memoizes each per call (#5813), handing every
caller its own copy; nothing is cached across calls.

This file holds:
  1. THE RATCHET (down-only). The per-call DynamoDB call count of a draft_custom stage-1 read, on a fixed synthetic
     world served by a fake botocore layer that counts every call, is pinned at `MAX_STAGE_1_DDB_CALLS`. A change that
     adds reads reds here; one that removes reads should lower the pin in the same PR.
  2. NO BEHAVIOUR CHANGE. The same world, read with the #5813 memos switched off (the pre-#5813 call) and on: the
     stage-1 output is byte-equal once `timing_ms` is removed, and the memo run makes strictly fewer calls.
  3. The memos' contract: one read per call, a copy per caller, a plain read outside a plan call.
  4. `timing_ms.stage_1` carries every `STAGE_1_READERS` key, and that list covers every `_read` label stage 1 uses.

Mutation controls (run on the lane, recorded on the PR): (M1) drop NOTES_HEALTH from `plan_call_scope._CALL_KINDS`
-> the ratchet reds (and the memo test); (M2) drop SOURCE_RANGE -> the ratchet reds; (M3) `memo_get` returns the
stored object, not a copy -> the copy test reds.
"""

from __future__ import annotations

import ast
import copy
import json
import os
import re
import sys
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import boto3  # noqa: E402
import botocore.client  # noqa: E402
import common.pacific_time as pacific_time  # noqa: E402
from boto3.dynamodb.conditions import ConditionBase  # noqa: E402
from botocore.exceptions import ClientError  # noqa: E402
from reading_fakes import _eval  # noqa: E402 — the repo's boto3 Key-condition evaluator
from training import routine_repo  # noqa: E402
from training.routine_ir import ExerciseBlock, RoutineSpec, Set  # noqa: E402

from mcp import (  # noqa: E402
    core,
    plan_call_scope,
    tools_plan as tp,  # noqa: E402
)

# The pin. Measured on this fixture when #5813 landed: 97 DynamoDB calls with the memos (the pre-#5813 read set: 137).
# +2 (#5774, owner ruling 2026-11-11 item 2): the week-commitment check reads the program week's committed routines once per
# stage-1 call (`week_commitments.attach`: one routine-index Query + one GetItem for the routine this fixture holds) — a
# new read the ruling requires (departures count at the week level), not a memo that stopped holding.
MAX_STAGE_1_DDB_CALLS = 99

_TARGET = "2026-09-20"
_NOW = datetime(2026, 9, 20, 19, 0, tzinfo=timezone.utc)  # noon Pacific on the target day — the clock is frozen
_TEMPLATES = (("A1B2C3D4", "Squat (Barbell)"), ("B2C3D4E5", "Leg Extension (Machine)"), ("C3D4E5F6", "Romanian Deadlift (Barbell)"))
_U = "USER#matthew#SOURCE#"


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return _NOW if tz is None else _NOW.astimezone(tz)


def _day(offset: int) -> str:
    return (datetime.fromisoformat(_TARGET) - timedelta(days=offset)).date().isoformat()


def _dec(obj):
    return json.loads(json.dumps(obj), parse_float=Decimal)


def _ir() -> RoutineSpec:
    return RoutineSpec(
        routine_id="r-5813",
        target_date=_TARGET,
        archetype="legs",
        version=1,
        source_action="draft_custom",
        notes="Legs.",
        exercises=[
            ExerciseBlock(movement_key=f"tmpl:{tid}", rationale_tag=name, sets=[Set(weight_kg=80, reps=5) for _ in range(3)])
            for tid, name in _TEMPLATES
        ],
    )


def _world() -> dict[str, list[dict]]:
    """A fixed, synthetic world — enough rows that every reader walks its real path (no live data in a public repo)."""
    items: list[dict] = []
    for i, offset in enumerate((1, 3, 5, 8, 10, 12, 15, 19, 24)):
        d, wid = _day(offset), f"w{i:03d}"
        exs = [
            {
                "template_id": tid,
                "name": name,
                "notes": "felt solid" if (i + j) % 2 == 0 else "",
                "sets": [{"type": "normal", "weight_kg": 80 + i, "reps": 5, "rpe": 7} for _ in range(3)],
            }
            for j, (tid, name) in enumerate(_TEMPLATES)
        ]
        items.append(
            {
                "pk": _U + "hevy",
                "sk": f"DATE#{d}#WORKOUT#{wid}",
                "date": d,
                "source_workout_id": wid,
                "workout_uid": f"hevy:{wid}",
                "title": "Legs",
                "start_time": f"{d}T17:00:00Z",
                "end_time": f"{d}T18:00:00Z",
                "phase": "experiment",
                "exercises": exs,
            }
        )
        for j, (tid, _name) in enumerate(_TEMPLATES):
            if (i + j) % 2 == 0:
                items.append(
                    {
                        "pk": f"{_U}training_notes#EXERCISE#{tid}",
                        "sk": f"DATE#{d}#WORKOUT#{wid}#OCC#0",
                        "date": d,
                        "note_raw": "felt solid",
                        "pain_flag": False,
                        "degraded": False,
                    }
                )
    for offset in range(0, 30):
        d = _day(offset)
        items.append({"pk": _U + "whoop", "sk": f"DATE#{d}", "date": d, "recovery_score": 60, "hrv": 40, "phase": "experiment"})
        items.append({"pk": _U + "withings", "sk": f"DATE#{d}", "date": d, "weight_lbs": 318.0 - offset * 0.2, "phase": "experiment"})
        items.append({"pk": _U + "macrofactor", "sk": f"DATE#{d}", "date": d, "total_protein_g": 190, "total_calories_kcal": 2200})
        items.append({"pk": _U + "apple_health", "sk": f"DATE#{d}", "date": d, "steps": 9000, "phase": "experiment"})
        items.append(
            {
                "pk": _U + "strava",
                "sk": f"DATE#{d}",
                "date": d,
                "activities": [{"type": "Walk", "sport_type": "Walk", "moving_time_seconds": 3600, "start_date_local": f"{d}T08:00:00"}],
            }
        )
    ir = _ir()
    items.extend(routine_repo.versioned_items(ir))
    world: dict[str, list[dict]] = {}
    for it in _dec(items):
        world.setdefault(it["pk"], []).append(it)
    for rows in world.values():
        rows.sort(key=lambda r: r["sk"])
    return world


_TOKEN = re.compile(
    r"\s*(?:(?P<fn>begins_with)\(\s*(?P<fa>[#\w]+)\s*,\s*(?P<fv>:\w+)\s*\)|(?P<a>[#\w]+)\s*(?P<op>=|<=|>=|<|>|BETWEEN)\s*(?P<v1>:\w+)(?:\s+AND\s+(?P<v2>:\w+))?)\s*"
)


def _string_condition(expr: str, names: dict, values: dict):
    """The string KeyConditionExpression forms the readers use: `pk = :pk [AND sk <op> :v | BETWEEN | begins_with]`."""
    tests = []
    for part in re.split(r"\s+AND\s+(?=begins_with|[#\w]+\s*(?:=|<|>|BETWEEN))", expr.strip()):
        m = _TOKEN.fullmatch(part)
        if not m:
            raise NotImplementedError(f"fake DynamoDB: unparsed key condition {expr!r}")
        if m["fn"]:
            attr, op, lo, hi = names.get(m["fa"], m["fa"]), "begins_with", values[m["fv"]], None
        else:
            attr, op = names.get(m["a"], m["a"]), m["op"]
            lo, hi = values[m["v1"]], values.get(m["v2"]) if m["v2"] else None
        tests.append((attr, op, lo, hi))

    def match(item):
        for attr, op, lo, hi in tests:
            v = item.get(attr)
            if v is None:
                return False
            ok = {
                "=": lambda: v == lo,
                "<": lambda: v < lo,
                "<=": lambda: v <= lo,
                ">": lambda: v > lo,
                ">=": lambda: v >= lo,
                "BETWEEN": lambda: lo <= v <= hi,
                "begins_with": lambda: str(v).startswith(lo),
            }[op]()
            if not ok:
                return False
        return True

    return match


class _FakeAws:
    """Replaces `BaseClient._make_api_call`: DynamoDB reads served from the world and COUNTED; S3/SSM/secrets answer
    not-found; any write raises (stage 1 writes nothing)."""

    def __init__(self, world):
        self.world = world
        self.ddb_calls: list[tuple[str, str]] = []

    def __call__(self, client, op, params):
        svc = client.meta.service_model.service_name
        if svc == "dynamodb":
            return self._ddb(op, params)
        if svc == "s3" and op in ("ListObjectsV2", "ListObjects"):
            return {"Contents": [], "KeyCount": 0}
        if op.startswith(("Get", "Head", "List", "Describe", "Query", "Scan", "BatchGet")):
            raise ClientError({"Error": {"Code": "NoSuchKey" if svc == "s3" else "ResourceNotFoundException", "Message": "fixture"}}, op)
        raise AssertionError(f"stage 1 made a non-read AWS call: {svc}.{op}")

    def _ddb(self, op, params):
        if op == "GetItem":
            key = params["Key"]
            self.ddb_calls.append((op, key["pk"]))
            hit = next((r for r in self.world.get(key["pk"], []) if r["sk"] == key["sk"]), None)
            return {"Item": copy.deepcopy(hit)} if hit else {}
        if op != "Query":
            if op in ("Scan", "BatchGetItem"):
                self.ddb_calls.append((op, ""))
                return {"Items": [], "Count": 0, "Responses": {}}
            raise AssertionError(f"stage 1 made a DynamoDB write: {op}")
        kce = params["KeyConditionExpression"]
        if isinstance(kce, ConditionBase):
            match = lambda item: _eval(kce, item)  # noqa: E731
        else:
            match = _string_condition(kce, params.get("ExpressionAttributeNames") or {}, params.get("ExpressionAttributeValues") or {})
        if params.get("IndexName"):
            rows = [r for rows in self.world.values() for r in rows if match(r)]
        else:
            pk = next(
                (v for v in (params.get("ExpressionAttributeValues") or {}).values() if isinstance(v, str) and v.startswith("USER#")), None
            )
            pool = self.world.get(pk) if pk else None
            rows = [r for r in (pool if pool is not None else [r for rs in self.world.values() for r in rs]) if match(r)]
        self.ddb_calls.append((op, rows[0]["pk"] if rows else str(pk if not isinstance(kce, ConditionBase) else "")))
        if params.get("ScanIndexForward") is False:
            rows = list(reversed(rows))
        if params.get("Limit"):
            rows = rows[: int(params["Limit"])]
        if params.get("Select") == "COUNT":
            return {"Count": len(rows), "Items": []}
        return {"Items": copy.deepcopy(rows), "Count": len(rows)}


_REPO = Path(__file__).resolve().parents[1]
_TABLE_ATTRS = ("table", "_table", "_ddb_table")


def _own_the_tables(st: ExitStack) -> None:
    """Point every loaded repo module's module-level DynamoDB table at a REAL boto3 Table, so every read goes through
    the botocore fake below. A test elsewhere in the same xdist worker may have left a stand-in there — CI, 2026-11-12:
    `tests/test_mcp_oauth.py::setup_function` assigns `core.table = _FakeTable()` (no `query`) and never restores it, so
    every query_source reader failed before reaching the fake, both arms made the same 33 calls, and the memo
    comparison went vacuous (#5813)."""
    real = boto3.resource("dynamodb", region_name="us-west-2").Table(os.environ.get("TABLE_NAME") or "test-table")
    roots = (str(_REPO / "mcp"), str(_REPO / "lambdas"))
    for mod in list(sys.modules.values()):
        path = str(getattr(mod, "__file__", None) or "")
        if not path.startswith(roots):
            continue
        for attr in _TABLE_ATTRS:
            value = getattr(mod, attr, None)
            if value is None or callable(value) or isinstance(value, (str, bytes, int, float, dict, list, tuple)):
                continue
            if any(hasattr(value, m) for m in ("query", "get_item", "put_item")) or "Table" in type(value).__name__:
                st.enter_context(patch.object(mod, attr, real))


def _stage1(routine: bool = True, memos: bool = True) -> tuple[dict, int, int]:
    """(stage-1 output, DynamoDB calls before stage 2 starts, all calls) for one plan call on the fixture."""
    fake = _FakeAws(_world())
    seen: dict[str, int] = {}

    def stage_2_stub(*_a, **_kw):
        seen["at_stage_2"] = len(fake.ddb_calls)
        return {"stage_2": "not run in this test"}

    def no_network(*_a, **_kw):
        raise OSError("no network in the #5813 fixture")

    kinds = plan_call_scope._CALL_KINDS if memos else (plan_call_scope.ANCHOR_INDEXES, plan_call_scope.BLOCK_WORKOUTS)
    with ExitStack() as st:
        st.enter_context(patch.object(botocore.client.BaseClient, "_make_api_call", lambda self, op, params: fake(self, op, params)))
        _own_the_tables(st)
        st.enter_context(patch.object(pacific_time, "datetime", _Frozen))
        st.enter_context(patch("urllib.request.urlopen", side_effect=no_network))
        st.enter_context(patch.object(plan_call_scope, "_CALL_KINDS", kinds))
        st.enter_context(patch("mcp.tools_plan._model_allowed", return_value=(False, "fixture: model off")))
        st.enter_context(patch("mcp.tools_plan._run_stage_2", side_effect=stage_2_stub))
        args = {"target_date": _TARGET, **({"routine_id": "r-5813"} if routine else {})}
        out = tp.tool_plan_next_session(args)
    assert "error" not in out, out
    # The world must actually be READ: a reader that fails before reaching the fake makes no call in either arm, and a
    # count comparison over two failed reads proves nothing (the CI flake this guard names).
    failed = sorted(k for k, v in (out["constraint_block"].get("inputs") or {}).items() if (v or {}).get("state") == "read_failed")
    assert not failed, f"fixture readers failed instead of reading the fake world: {failed}"
    return out, seen.get("at_stage_2", len(fake.ddb_calls)), len(fake.ddb_calls)


def _strip_timing(o):
    if isinstance(o, dict):
        return {k: _strip_timing(v) for k, v in o.items() if k != "timing_ms"}
    if isinstance(o, list):
        return [_strip_timing(x) for x in o]
    return o


def test_the_draft_custom_stage_1_read_count_never_grows():
    """The down-only ratchet. Mutation: drop NOTES_HEALTH or SOURCE_RANGE from `_CALL_KINDS` -> this reds."""
    _stage1()  # one warm-up: per-container caches (config/charter loaders) settle, so the pinned call is the steady one
    out, stage_1, _total = _stage1()
    assert out["critics"] == {"stage_2": "not run in this test"}
    assert stage_1 <= MAX_STAGE_1_DDB_CALLS, (
        f"a draft_custom stage-1 read now makes {stage_1} DynamoDB calls (pin {MAX_STAGE_1_DDB_CALLS}). A reader added a read, "
        "or a memo stopped holding — memoize it per call through mcp.plan_call_scope (one read per partition/range per call, "
        "a copy per caller) rather than raising the pin (#5813)."
    )


def test_the_memos_change_no_output_and_strictly_cut_the_reads():
    """Before/after on one fixed world: the pre-#5813 read set (memos off) and the #5813 one return the same stage 1."""
    for routine in (True, False):
        _stage1(routine=routine)
        before, before_n, _ = _stage1(routine=routine, memos=False)
        after, after_n, _ = _stage1(routine=routine, memos=True)
        a = json.dumps(_strip_timing(before), sort_keys=True, default=str)
        b = json.dumps(_strip_timing(after), sort_keys=True, default=str)
        assert a == b, f"routine={routine}: the #5813 memos changed the stage-1 output"
        assert after_n < before_n, f"routine={routine}: {after_n} calls with the memos, {before_n} without"


def test_the_note_layer_health_sweep_runs_once_per_call_and_each_caller_gets_its_own_copy():
    calls = []

    def sweep(_table, **_kw):
        calls.append(1)
        return {"checked": True, "noted": 3, "unreadable": {}}

    with patch("training.training_notes.training_notes_health", side_effect=sweep):

        @plan_call_scope.plan_call
        def one_call():
            a, b = plan_call_scope.notes_health("t"), plan_call_scope.notes_health("t")
            a["noted"] = 99
            return {"a": a, "b": b, "c": plan_call_scope.notes_health("t")}

        out = one_call()
        assert len(calls) == 1, "one health sweep per plan call"
        assert out["b"]["noted"] == 3 and out["c"]["noted"] == 3, "a caller's mutation never reaches another caller"
        plan_call_scope.notes_health("t")
        plan_call_scope.notes_health("t")
        assert len(calls) == 3, "outside a plan call it is a plain read — no cache across calls"


def test_query_source_reads_a_window_once_per_call_and_hands_out_copies(monkeypatch):
    queries = []

    class _Table:
        def query(self, **kw):
            queries.append(kw)
            return {
                "Items": [{"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-09-19", "date": "2026-09-19", "recovery_score": Decimal(60)}]
            }

    monkeypatch.setattr(core, "table", _Table())

    @plan_call_scope.plan_call
    def one_call():
        a = core.query_source("whoop", "2026-09-13", "2026-09-19")
        a[0]["recovery_score"] = -1
        a.append({"injected": True})
        b = core.query_source("whoop", "2026-09-13", "2026-09-19")
        b[0]["recovery_score"] = -2  # a memo hit is a copy too: this must not reach the next caller
        b.append({"injected": True})
        d = core.query_source("whoop", "2026-09-13", "2026-09-19")
        c = core.query_source("whoop", "2026-09-12", "2026-09-19")  # another window is another read
        return {"d": d, "c": c}

    out = one_call()
    assert len(queries) == 2
    assert out["d"] == [{"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-09-19", "date": "2026-09-19", "recovery_score": 60.0}]
    core.query_source("whoop", "2026-09-13", "2026-09-19")
    assert len(queries) == 3, "outside a plan call every query_source reads"


def test_timing_ms_stage_1_names_every_reader_and_the_reader_list_covers_every_stage_1_read_label():
    out, _n, _t = _stage1()
    t = out["timing_ms"]
    assert set(t) == {"stage_1", "total"}
    assert set(plan_call_scope.STAGE_1_READERS) <= set(t["stage_1"]) and {"other", "total"} <= set(t["stage_1"])
    assert all(isinstance(v, int) and v >= 0 for v in t["stage_1"].values())
    named = sum(v for k, v in t["stage_1"].items() if k not in ("other", "total"))
    assert named <= t["stage_1"]["total"] + len(t["stage_1"]), "only the outermost reader is timed — the parts never pass the whole"

    # every literal `_read("<label>", ...)` the stage-1 path makes is a named reader (stable keys, #5813)
    labels = set()
    for rel in ("mcp/tools_plan.py", "mcp/plan_event_reads.py"):
        tree = ast.parse(Path(__file__).resolve().parents[1].joinpath(rel).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) in ("_read", "read_fn") and node.args:
                if isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                    labels.add(node.args[0].value)
    owner_words = {"deload_records", "disruption_records"}  # `_owner_word_records` reads them through a loop variable
    missing = sorted((labels | owner_words) - set(plan_call_scope.STAGE_1_READERS))
    assert not missing, f"stage-1 read labels missing from plan_call_scope.STAGE_1_READERS: {missing}"
