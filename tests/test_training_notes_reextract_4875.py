"""
tests/test_training_notes_reextract_4875.py — `backfill_training_notes.py --re-extract` (#4875, ADR-132).

The hash cache already holds nearly every noted exercise-session, so the #4814 batch path saw ~17 uncached records and
always ran realtime. `--re-extract` collects the CACHED history as `build_jsonl_record` records:

  * box 1: without --apply it prints the record count and the mode a run would take, writes nothing, calls no model;
  * box 2: with --apply, 120 cached notes -> exactly ONE batch submission (mutation control: without the flag, 0 records /
    realtime), cap-checked on the record count before submit;
  * box 3: re-extracted answers land in the cache and charge the bulk lane exactly as on-demand ones.

Run:  python3 -m pytest tests/test_training_notes_reextract_4875.py -v
"""

import importlib.util
import json
import os
import sys
import types

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.dirname(__file__))

from ai import bedrock_batch as bb  # noqa: E402
from bundle_stubs import stub_bundled_module  # noqa: E402
from test_training_notes_batch_4814 import _GOOD, TAXONOMY, WireTable, _line, _notes, _reply  # noqa: E402
from training import training_notes as tn, training_notes_llm as tnl  # noqa: E402

OLD = [{"class": "form", "summary": "old extraction", "confidence": 0.5}]


@pytest.fixture
def calls(monkeypatch):
    stub = types.ModuleType("budget_guard")
    stub.current_tier = lambda: 0
    stub.allow = lambda feature: True
    stub_bundled_module(monkeypatch, "ai.budget_guard", stub)
    state = {"submitted": [], "lines": []}

    def _submit(records, model_name, in_uri, out_uri, role_arn, job_name=None):
        state["submitted"].append(records)
        return "arn:aws:bedrock:us-west-2:123:model-invocation-job/tn4875"

    monkeypatch.setattr(bb, "submit_batch", _submit)
    monkeypatch.setattr(bb, "batch_role_arn", lambda: "arn:aws:iam::123:role/x")
    monkeypatch.setattr(
        bb, "wait_for_batch", lambda a, d, poll_interval=60.0: {"status": "Completed", "done": True, "succeeded": True, "message": ""}
    )
    monkeypatch.setattr(bb, "_read_output", lambda uri, key: bb.parse_output_jsonl("\n".join(state["lines"])))
    monkeypatch.setattr(bb, "_cleanup", lambda i, o, log: None)
    monkeypatch.setattr(bb, "_meter_batch_record", lambda usage, model_id: None)
    monkeypatch.setattr(bb, "_dev_cap_projected", lambda records, model_name: None)
    return state


def _cached_table(notes):
    table = WireTable()
    for t in notes:
        tnl.cache_put(table, tn.note_hash(t), OLD)
    return table


def _script(monkeypatch, table, workouts, writes):
    spec = importlib.util.spec_from_file_location("backfill_tn_4875", os.path.join(ROOT, "deploy", "backfill_training_notes.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.boto3, "resource", lambda *a, **k: types.SimpleNamespace(Table=lambda name: table))
    monkeypatch.setattr(mod, "_noted_workouts", lambda t, since, until="9999": workouts)
    monkeypatch.setattr(mod, "report_overwrites", lambda t, since: print("REPORT-OVERWRITES (stub)"))

    def _write(t, date, uid, exs, dry_run, llm_fn):
        writes.append({"dry_run": dry_run, "answers": [llm_fn(e["notes"], TAXONOMY) for e in exs] if llm_fn else None})
        return {"records": len(exs), "wrote": 0, "skipped": 0, "versioned": len(exs), "items": []}

    monkeypatch.setattr(mod.tn, "write_workout_notes", _write)
    return mod


def _workouts(notes):
    return [{"date": "2026-09-01", "workout_uid": f"w{i}", "exercises": [{"title": "Row", "notes": n}]} for i, n in enumerate(notes)]


def test_reextract_apply_submits_one_batch_job_over_120_cached_notes(calls, monkeypatch, capsys):
    notes = _notes(120)
    table = _cached_table(notes)
    calls["lines"] = [_line(tn.note_hash(t), _reply(_GOOD)) for t in notes]
    writes = []
    mod = _script(monkeypatch, table, _workouts(notes), writes)
    monkeypatch.setattr(sys, "argv", ["x", "--re-extract", "--apply"])
    mod.main()
    out = capsys.readouterr().out
    assert len(calls["submitted"]) == 1 and len(calls["submitted"][0]) == 120
    assert "mode=batch" in out
    # box 3: the cache now holds the NEW answer, the bulk lane was charged once per record, the live lane untouched
    assert tnl.cache_get(table, tn.note_hash(notes[0]))[0]["class"] == "limiter"
    assert tnl.monthly_calls(table, lane="bulk") == 120 and tnl.monthly_calls(table, lane="live") == 0
    # the sweep read the re-extracted answers (cache hit, no model call)
    assert len(writes) == 120 and writes[0]["answers"][0][0]["class"] == "limiter"


def test_mutation_control_without_the_flag_nothing_is_submitted(calls, monkeypatch, capsys):
    notes = _notes(120)
    table = _cached_table(notes)
    writes = []
    mod = _script(monkeypatch, table, _workouts(notes), writes)
    monkeypatch.setattr(sys, "argv", ["x", "--apply"])
    mod.main()
    out = capsys.readouterr().out
    assert calls["submitted"] == [] and "0 uncached distinct notes · mode=realtime" in out
    assert writes[0]["answers"][0][0]["class"] == "form"  # the old cached answer stood


def test_reextract_over_the_cap_submits_nothing_and_writes_nothing(calls, monkeypatch, capsys):
    notes = _notes(120)
    table = _cached_table(notes)
    writes = []
    mod = _script(monkeypatch, table, _workouts(notes), writes)
    monkeypatch.setattr(tnl, "DEFAULT_MONTHLY_CAP", 119)
    monkeypatch.setattr(tnl.bulk_prefetch, "__kwdefaults__", {**tnl.bulk_prefetch.__kwdefaults__, "monthly_cap": 119})
    monkeypatch.setattr(sys, "argv", ["x", "--re-extract", "--apply"])
    mod.main()
    out = capsys.readouterr().out
    assert calls["submitted"] == [] and writes == [] and "monthly cap 119" in out


def test_reextract_dry_run_reports_count_and_mode_and_touches_nothing(calls, monkeypatch, capsys):
    notes = _notes(120)
    table = _cached_table(notes)
    before = dict(table.store)
    ops = []
    for name in ("put_item", "update_item"):
        orig = getattr(table, name)
        monkeypatch.setattr(table, name, lambda *a, _o=orig, _n=name, **k: ops.append(_n) or _o(*a, **k))
    writes = []
    mod = _script(monkeypatch, table, _workouts(notes), writes)
    monkeypatch.setattr(mod.tl if hasattr(mod, "tl") else tnl, "_haiku_call", lambda *a, **k: pytest.fail("model called"))
    monkeypatch.setattr(sys, "argv", ["x", "--re-extract"])
    mod.main()
    out = capsys.readouterr().out
    assert "RE-EXTRACT (dry-run" in out and "120 records · mode=batch" in out
    assert ops == [] and writes == [] and calls["submitted"] == [] and table.store == before


def test_reextract_dry_run_below_the_floor_says_realtime(calls, monkeypatch, capsys):
    notes = _notes(40)
    table = _cached_table(notes)
    mod = _script(monkeypatch, table, _workouts(notes), [])
    monkeypatch.setattr(sys, "argv", ["x", "--re-extract"])
    mod.main()
    assert "40 records · mode=realtime" in capsys.readouterr().out


def test_reextract_apply_below_the_floor_refuses_and_writes_nothing(calls, monkeypatch, capsys):
    notes = _notes(40)
    writes = []
    mod = _script(monkeypatch, _cached_table(notes), _workouts(notes), writes)
    monkeypatch.setattr(sys, "argv", ["x", "--re-extract", "--apply"])
    mod.main()
    assert writes == [] and calls["submitted"] == [] and "nothing was re-extracted" in capsys.readouterr().out


def test_reextract_flag_conflicts(monkeypatch):
    mod = _script(monkeypatch, WireTable(), [], [])
    for extra in (["--realtime", "--apply"], ["--value-census"], ["--migrate"]):
        monkeypatch.setattr(sys, "argv", ["x", "--re-extract", *extra])
        with pytest.raises(SystemExit):
            mod.main()


def test_json_dummy_import_used():
    assert json.dumps(_GOOD)
