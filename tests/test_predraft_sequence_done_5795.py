"""tests/test_predraft_sequence_done_5795.py — a pre-draft of a session already performed is never served (#5795).

THE INCIDENT (2026-11-11): the 19:00 PT pre-draft started at 03:00:07Z; the day's session ended at
03:01:30Z (19:01 PT on 2026-11-10) and reached the store on a later Hevy poll. The run read the
completed-session record before that session was in it, so it drafted the slot he had just performed,
and `predraft_for` served that draft as `ready`.

THE REPLAY, through the REAL routine repo (the #4732 in-memory table) and the REAL session sequence
(`session_sequence.next_session` / `completed_sessions` over Hevy-shaped rows):
  A. the clock run BEFORE the ingest drafts slot N for 11-11 and stamps `sequence_index` N;
  B. the session lands; `predraft_for(11-11)` now reads `stale_sequence_done`, not `ready`;
  C. the ingest-triggered run (`predraft_ingest.lambda_entry`) archives the slot-N draft
     (`sequence_done`, a new version — never a delete) and drafts slot N+1;
  D. negative control: the same evening's log is an off-program Flex session (#4312) — the ingest run is
     `not_credited`, nothing is swept, nothing drafted.
Mutation controls: `_slot_done` forced False → the stale draft is served `ready` and survives the sweep
(the pre-fix behaviour); the credit gate forced open → the Flex log triggers a run.
The poller side (`ingestion/predraft_trigger.py`) and the CDK grant are pinned below.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
from contextlib import ExitStack
from unittest.mock import patch

import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from ingestion import predraft_trigger  # noqa: E402
from training import routine_repo, session_sequence  # noqa: E402
from training.routine_generator import _new_routine_id  # noqa: E402
from training.routine_ir import RoutineSpec  # noqa: E402
from training.routine_title import ROUTINE_ARCHETYPE_KEY  # noqa: E402

from mcp import (
    invoke_gate,  # noqa: E402
    nightly_predraft as npd,  # noqa: E402
    predraft_ingest,  # noqa: E402
)
from tests.test_predraft_sweep_4732 import _Table  # noqa: E402

TODAY = "2026-11-10"  # 19:00 PT on 11-10 = 03:00Z on 11-11
TARGET = "2026-11-11"
GENESIS = "2026-09-06"
EVENING_WID = "hevy-1110-evening"


def _lift(day: str, wid: str | None = None, archetype: str | None = None) -> dict:
    """A loaded Hevy row reaching every role's anchor muscles (the #4110 test's generic lift)."""
    row = {
        "date": day,
        "sk": f"DATE#{day}#WORKOUT#{wid or 'L' + day}",
        "title": "Foundation",
        "source_workout_id": wid or "L" + day,
        "start_time": f"{day}T14:00:00Z",
        "exercises": [
            {"name": "Linear Leg Press", "sets": [{"type": "normal", "weight_kg": 90, "reps": 5}]},
            {"name": "Bench Press (Barbell)", "sets": [{"type": "normal", "weight_kg": 60, "reps": 5}]},
            {"name": "Lateral Raise (Dumbbell)", "sets": [{"type": "normal", "weight_kg": 10, "reps": 12}]},
        ],
    }
    if archetype:  # what the block-read seam's routine-index annotation leaves on the row (#4312)
        row[ROUTINE_ARCHETYPE_KEY] = {"archetype": archetype, "via": "hevy_routine_id"}
    return row


# The record before the evening session: program sessions since the cut-over (one per day, a rest day between some).
PRIOR = [_lift(d) for d in ("2026-11-03", "2026-11-04", "2026-11-05", "2026-11-07", "2026-11-08", "2026-11-09")]
EVENING = _lift(TODAY, EVENING_WID)  # 2026-11-10, over at 03:01:30Z on 11-11
EVENING_FLEX = _lift(TODAY, EVENING_WID, archetype="flex")


def _frozen_pacific_today():
    """Every handler clock read here (`pacific_today()`: the run's tomorrow, the ingest target, the poller's
    recent window) is frozen to the fixture's TODAY (#2376), so the dated literals cannot desync from it."""
    return patch("common.pacific_time.pacific_today", return_value=TODAY)


class _World:
    """The seams the pre-draft reaches, wired to the real repo + sequence. `rows` is the Hevy record."""

    def __init__(self, rows):
        self.rows = list(rows)
        self.table = _Table()
        self.drafts = 0

    def block_record(self, target):
        return [r for r in self.rows if r["date"] < target]

    def scheduled(self, target, deload_records=None):
        s = session_sequence.next_session(target, self.block_record(target))
        return {**s, "prescription": {"exposures": ["stub"]}}

    def draft(self, target, switch):
        self.drafts += 1
        s = self.scheduled(target)
        rid = _new_routine_id(target, s["archetype"], "ideal")
        cur = routine_repo.get_current(rid)
        v = int(cur.version) + 1 if cur else 1
        routine_repo.put_versioned(
            RoutineSpec(
                routine_id=rid,
                target_date=target,
                archetype=s["archetype"],
                variant="ideal",
                status="draft",
                version=v,
                parent_version=v - 1 if v > 1 else None,
                created_by="cron",
                created_at=f"{TODAY}T03:00:10Z",
                inputs_snapshot={"calendar": {"session_role": s["session_role"]}},
            )
        )
        return {"status": "drafted", "ideal_routine_id": rid}

    def stage_2(self, target, rid):
        ir = routine_repo.get_current(rid)
        rec = {"verdicts": [{"critic": "load", "verdict": "pass"}], "binding": {"version": int(ir.version)}, "model_ran": True}
        ir.inputs_snapshot = {**(ir.inputs_snapshot or {}), "critics": rec}
        ir.parent_version, ir.version = int(ir.version), int(ir.version) + 1
        routine_repo.put_versioned(ir)
        return {"critics": {**rec, "routine_version": int(ir.version)}}

    def patches(self, stack: ExitStack) -> None:
        stack.enter_context(patch.object(routine_repo, "_table", self.table))
        stack.enter_context(patch("training.routine_repo._live_genesis", return_value=GENESIS))
        stack.enter_context(_frozen_pacific_today())
        stack.enter_context(patch.object(npd, "_block_record", side_effect=self.block_record))
        stack.enter_context(patch.object(npd, "scheduled_session", side_effect=self.scheduled))
        stack.enter_context(patch.object(npd, "_switch", return_value={"source": "charter", "shadow": {"due": False}}))
        stack.enter_context(patch.object(npd, "_disruption", return_value={}))
        stack.enter_context(patch.object(npd, "_draft_by_source", side_effect=self.draft))
        stack.enter_context(patch.object(npd, "_stage_2", side_effect=self.stage_2))
        stack.enter_context(patch.object(npd, "_note_lint", return_value={"state": "off"}))
        stack.enter_context(patch.object(npd, "coach_context_brief", return_value={}))


def _ingest_event(*wids):
    return {"job": "nightly_predraft", "trigger": npd.INGEST_TRIGGER, "workout_ids": list(wids)}


def _marker(ir):
    return (ir.inputs_snapshot or {}).get(npd.MARKER) or {}


def _replay(evening_row, *, slot_done=None, gate_open=False):
    """Phases A-C of the 2026-11-11 shape; returns everything the assertions read."""
    w = _World(PRIOR)
    with ExitStack() as stack:
        w.patches(stack)
        if slot_done is not None:
            stack.enter_context(patch.object(npd, "_slot_done", side_effect=slot_done))
        if gate_open:
            stack.enter_context(patch.object(predraft_ingest, "credited_ids", side_effect=lambda ids, rows, day: list(ids)))
        clock = npd.run()  # A: 03:00:07Z — the evening session is not in the record yet
        first = routine_repo.get_current(clock["routine_id"])
        w.rows.append(evening_row)  # 03:01:30Z: the session is over; the poll writes it
        read_after_ingest = npd.predraft_for(TARGET)  # B
        drafts_before_ingest = w.drafts
        ingest = json.loads(predraft_ingest.lambda_entry(_ingest_event(EVENING_WID))["body"])  # C
        first_after = routine_repo.get_current(first.routine_id)
        live = [r for r in routine_repo.list_by_date_range(TARGET, TARGET) if npd._is_primary(r) and r.status != "archived"]
        read_final = npd.predraft_for(TARGET)
        served_now = w.scheduled(TARGET)
    return {
        "clock": clock,
        "first": first,
        "first_after": first_after,
        "read_after_ingest": read_after_ingest,
        "ingest": ingest,
        "live": live,
        "read_final": read_final,
        "served_now": served_now,
        "drafts_by_ingest": w.drafts - drafts_before_ingest,
        "table": w.table,
    }


def test_the_2026_11_11_race_the_ingest_run_archives_the_performed_slot_and_drafts_the_next():
    r = _replay(EVENING)
    slot_n = r["clock"]["session"] and r["first"] and _marker(r["first"]).get("sequence_index")
    offenders = []
    if r["clock"].get("outcome") != npd.DRAFTED or slot_n != len(PRIOR):
        offenders.append(("A: the clock run did not draft slot N with the slot stamped", r["clock"].get("outcome"), slot_n))
    if r["read_after_ingest"].get("status") != "stale_sequence_done" or r["read_after_ingest"].get("sequence_index") != slot_n:
        offenders.append(("B: the performed slot's draft is served as current", r["read_after_ingest"]))
    sweep = {a["routine_id"]: a["reason"] for a in (r["ingest"].get("sweep") or {}).get("archived", [])}
    if sweep.get(r["first"].routine_id) != npd.SEQUENCE_DONE:
        offenders.append(("C: the ingest run's sweep did not archive slot N as sequence_done", r["ingest"].get("sweep")))
    if r["first_after"].status != "archived" or int(r["first_after"].version) <= int(r["first"].version):
        offenders.append(("C: slot N's draft was not archived as its NEXT version", r["first_after"].status, r["first_after"].version))
    if (r["first"].routine_id, r["first"].version) and not any(
        k == (f"USER#matthew#ROUTINE#{r['first'].routine_id}", f"VERSION#{int(r['first'].version):06d}") for k in r["table"].items
    ):
        offenders.append(("C: the drafted version vanished — archive, never delete",))
    if r["ingest"].get("outcome") != npd.DRAFTED or r["ingest"].get("credited_workout_ids") != [EVENING_WID]:
        offenders.append(("C: the ingest run did not draft", r["ingest"].get("outcome"), r["ingest"].get("credited_workout_ids")))
    if [_marker(x).get("sequence_index") for x in r["live"]] != [slot_n + 1] or r["served_now"]["sequence_index"] != slot_n + 1:
        offenders.append(("C: the live pre-draft is not slot N+1", [_marker(x) for x in r["live"]], r["served_now"]["sequence_index"]))
    if r["read_final"].get("status") != "ready":
        offenders.append(("C: the new draft is not served ready", r["read_final"]))
    if r["ingest"].get("trigger") != npd.INGEST_TRIGGER or r["ingest"].get("target_date") != TARGET:
        offenders.append(("C: the ingest run is not labelled / targeted", r["ingest"]))
    assert not offenders, offenders


def test_negative_control_an_off_program_flex_log_triggers_nothing():
    r = _replay(EVENING_FLEX)
    offenders = []
    if r["ingest"].get("outcome") != predraft_ingest.NOT_CREDITED or "sweep" in r["ingest"]:
        offenders.append(("the Flex log ran the pre-draft", r["ingest"]))
    if r["drafts_by_ingest"] or r["first_after"].status != "draft" or int(r["first_after"].version) != int(r["first"].version):
        offenders.append(("the Flex log touched the pre-draft", r["drafts_by_ingest"], r["first_after"].status))
    if r["read_after_ingest"].get("status") != "ready":  # the slot was NOT performed: the draft is still the next session
        offenders.append(("an uncredited log made the draft stale", r["read_after_ingest"]))
    assert not offenders, offenders


def test_mutation_control_without_the_slot_check_the_stale_draft_is_served_ready():
    """The pre-fix behaviour, reproduced: no slot check → B reads `ready` and C finds it `exists`."""
    r = _replay(EVENING, slot_done=lambda ir, credited: False)
    assert r["read_after_ingest"].get("status") == "ready"
    assert r["first_after"].status == "draft" and r["ingest"].get("outcome") == npd.EXISTS


def test_mutation_control_an_open_credit_gate_lets_the_flex_log_run_the_pre_draft():
    r = _replay(EVENING_FLEX, gate_open=True)
    assert r["ingest"].get("outcome") == npd.EXISTS and "sweep" in r["ingest"]


def test_the_ingest_run_emits_no_dead_man_datapoint_and_runs_no_side_legs(capsys):
    with (
        patch.object(predraft_ingest, "_gate_and_run", return_value={"outcome": npd.DRAFTED}),
        patch.object(npd, "_may_tracker_leg", side_effect=AssertionError("no legs on an ingest run")),
        patch.object(npd, "_titration_leg", side_effect=AssertionError("no legs on an ingest run")),
        _frozen_pacific_today(),
    ):
        body = json.loads(npd.lambda_entry(_ingest_event(EVENING_WID))["body"])
    assert body["outcome"] == npd.DRAFTED and body["trigger"] == npd.INGEST_TRIGGER
    assert npd.JOB["metric_name"] not in capsys.readouterr().out


def test_a_failing_ingest_run_is_named_never_raised():
    with (
        patch.object(npd, "_block_record", side_effect=RuntimeError("ddb down")),
        _frozen_pacific_today(),
    ):
        body = json.loads(predraft_ingest.lambda_entry(_ingest_event(EVENING_WID))["body"])
    assert body["outcome"] == npd.FAILED and "RuntimeError" in body["error"]


def test_sweep_reason_sequence_done_rules():
    """Unit rules of the new reason: only a stamped slot, only when credited past it, never an unknown record."""

    def ir(day, idx, status="draft", hevy=None):
        m = {"role": npd.PRIMARY}
        if idx is not None:
            m["sequence_index"] = idx
        return RoutineSpec(
            routine_id=f"r-{day}-{idx}",
            target_date=day,
            archetype="upper",
            status=status,
            hevy_routine_id=hevy,
            inputs_snapshot={npd.MARKER: m},
        )

    cases = [
        (ir(TARGET, 6), lambda d: 7, npd.SEQUENCE_DONE),  # tomorrow's draft, slot credited since
        (ir(TARGET, 7), lambda d: 7, None),  # the slot the sequence serves
        (ir(TARGET, None), lambda d: 9, None),  # a pre-#5795 draft carries no slot
        (ir(TARGET, 6), lambda d: None, None),  # the record was not read: never read as done
        (ir(TARGET, 6, status="active", hevy="hv"), lambda d: 9, None),  # committed: never the sweep's
        (ir(TODAY, 6), lambda d: 7, npd.SEQUENCE_DONE),  # today's, slot already done before today
        (ir("2026-11-01", 6), lambda d: 9, "expired"),
    ]
    got = [(c[0].routine_id, npd._sweep_reason(c[0], TODAY, [], c[1]), c[2]) for c in cases]
    assert [g for g in got if g[1] != g[2]] == []
    assert npd._sweep_reason(ir(TARGET, 6), TODAY, []) is None  # no credited lookup: the #4732 behaviour


# ── the poller side ──────────────────────────────────────────────────────────────────────


def test_poller_candidates_are_recent_loaded_sessions_only():
    walk = {"date": TODAY, "source_workout_id": "walk", "exercises": [{"name": "Walking", "sets": [{"duration_sec": 3600}]}]}
    old = _lift("2026-11-01", "old")
    yesterday = _lift("2026-11-09", "yday")
    assert predraft_trigger.candidates([EVENING, walk, old, yesterday], TODAY) == sorted([EVENING_WID, "yday"])


def test_poller_flag_off_reports_and_never_invokes(monkeypatch):
    monkeypatch.delenv(predraft_trigger.FLAG_ENV, raising=False)
    out = predraft_trigger.after_poll([EVENING], TODAY, invoke=lambda p: pytest.fail("invoked with the flag off"))
    assert out == {"state": "off", "candidates": [EVENING_WID]}


def test_poller_flag_on_invokes_the_warmer_with_an_event_the_gate_dispatches_to_the_ingest_entry(monkeypatch):
    monkeypatch.setenv(predraft_trigger.FLAG_ENV, "on")
    sent = []
    out = predraft_trigger.after_poll([EVENING], TODAY, invoke=sent.append)
    assert out["state"] == "invoked" and len(sent) == 1
    ev = sent[0]
    assert invoke_gate.privileged_kind(ev) == "nightly_predraft" == npd.JOB["name"]
    assert ev["trigger"] == npd.INGEST_TRIGGER and ev["workout_ids"] == [EVENING_WID]
    assert predraft_trigger.WARMER_FUNCTION_NAME == invoke_gate.WARMER_FUNCTION_NAME == npd.JOB["function"]


def test_poller_never_raises_and_nothing_written_invokes_nothing(monkeypatch):
    monkeypatch.setenv(predraft_trigger.FLAG_ENV, "on")

    def boom(p):
        raise RuntimeError("AccessDenied")

    assert predraft_trigger.after_poll([EVENING], TODAY, invoke=boom)["state"] == "failed"
    assert predraft_trigger.after_poll([], TODAY, invoke=boom) == {"state": "no_candidate"}


def test_the_poll_summary_carries_the_trigger(monkeypatch):
    import hevy_backfill_lambda as mod

    for name, val in {
        "_INGEST_HEALTH_AVAILABLE": False,
        "_HAS_AUTH_BREAKER": False,
        "load_since": lambda: "2026-11-10T00:00:00Z",
        "save_since": lambda ts: None,
        "archive_raw": lambda wid, raw: None,
        "write_normalized": lambda rec: None,
        "_derive_training_notes": lambda rec: None,
        "_attach_adherence": lambda rec, raw: None,
        "_load_event_failures": lambda: {},
        "resolve_tombstones": lambda: {"resolved": 0},
        "_rejoin_cardio_hr": lambda: {},
        "fetch_events_page": lambda since, page=1, page_size=10: {
            "page_count": 1,
            "events": [{"type": "updated", "workout": {"id": "w1"}}],
        },
        "normalize_workout": lambda ev: {**EVENING, "set_count": 3, "total_volume_kg": 1.0},
    }.items():
        monkeypatch.setattr(mod, name, val)
    monkeypatch.setattr(mod.cardio_hr_store, "attach", lambda *a, **k: None)
    import common.pacific_time as pt

    monkeypatch.setattr(pt, "pacific_today", lambda: TODAY)
    monkeypatch.delenv(predraft_trigger.FLAG_ENV, raising=False)
    body = json.loads(mod.lambda_handler({}, None)["body"])
    assert body["ingested"] == 1 and body["predraft_trigger"] == {"state": "off", "candidates": [EVENING_WID]}
    assert "tombstones" in body and "cardio_hr_rejoin" in body


# ── the CDK side: OWNER-REQUIRED additive IAM; flag ON (owner ruling 2026-11-12) ─────────────────────────────


def test_cdk_grants_only_the_warmer_and_ships_the_flag_on():
    src = (REPO / "cdk" / "stacks" / "role_policies_ingestion.py").read_text()
    body = src.split("def ingestion_hevy_backfill", 1)[1].split("\ndef ", 1)[0]
    assert 'sid="PredraftOnIngestInvoke"' in body and 'actions=["lambda:InvokeFunction"]' in body
    assert f'function:{invoke_gate.WARMER_FUNCTION_NAME}"' in body and "function:*" not in body
    stack = (REPO / "cdk" / "stacks" / "ingestion_stack.py").read_text()
    hevy = stack.split('"HevyBackfill"', 1)[1].split("custom_policies", 1)[0]
    assert f'"{predraft_trigger.FLAG_ENV}": "on"' in hevy
