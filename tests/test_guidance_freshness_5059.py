"""tests/test_guidance_freshness_5059.py — the guidance freshness flag: reference, never a gate (#5059).

Owner ruling 7 (2026-10-18): he is cleared with no exercise restrictions; the owner guidance record is
background context. The engine flags a record older than the latest logged appointment and prompts him to
load the latest instructions — and nothing that prescribes reads the flag. Each rule below names the
mutation that reds it. Every date and value here is synthetic; no real record value is in this file.
"""

# premerge-gate: #5059: os.walk over lambdas/ + mcp/ — the guidance-freshness flag's reader set is closed (never a gate, never published)
from __future__ import annotations

import copy
import json
import logging
import os
import re
from pathlib import Path

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common.pacific_time import shift_day_key  # noqa: E402
from health import guidance_freshness as gf  # noqa: E402
from training import plan_engine  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
TODAY = "2026-11-04"
SENTINEL = "SENTINEL-RULE-TEXT-do-not-leak"
GUIDANCE = {
    "pk": "USER#matthew#SOURCE#clinical",
    "sk": "GUIDANCE#current",
    "effective": "2026-10-01",
    "review_after": "2026-12-01",
    "rules": [SENTINEL + " full"],
    "public_rules": [SENTINEL + " public"],
}


def _appt(day: str, slug: str = "example-visit") -> dict:
    return {"pk": "USER#matthew#SOURCE#clinical", "sk": f"APPT#{day}#{slug}", "date": day, "kind": SENTINEL}


# ── the four states (the clock is the `today` argument — never a live read, #4848) ─────────
def test_fresh_when_the_record_is_on_or_after_the_latest_appointment():
    """Mutation: compare with `>=` instead of `>` in `freshness` — the same-day case reads stale and this reds."""
    for appts in ([_appt("2026-09-20")], [_appt("2026-09-20"), _appt("2026-10-01")]):
        f = gf.freshness(GUIDANCE, appts, TODAY)
        assert f["state"] == gf.FRESH and f["prompt"] is None, appts
        assert f["guidance_effective"] == "2026-10-01" and f["latest_appointment_date"] == max(a["date"] for a in appts)


def test_stale_when_a_logged_appointment_is_newer_and_the_prompt_asks_for_the_load():
    """Mutation: take `min(past)` instead of `max(past)` — the newer appointment is missed and this reds."""
    f = gf.freshness(GUIDANCE, [_appt("2026-09-20"), _appt("2026-10-15"), _appt("2026-10-02")], TODAY)
    assert f["state"] == gf.STALE and f["latest_appointment_date"] == "2026-10-15"
    assert "load the latest instructions" in f["prompt"].lower() and gf.LOADER in f["prompt"]
    assert "2026-10-15" in f["prompt"] and "2026-10-01" in f["prompt"]
    assert f["gates_intensity"] is False and "never a gate" in f["role"]


def test_no_appointment_when_none_is_logged_or_every_one_is_still_ahead():
    """A booked appointment that has not happened cannot make the record stale. Mutation: drop the `today`
    cutoff — the future row makes this read stale and it reds."""
    assert gf.freshness(GUIDANCE, [], TODAY)["state"] == gf.NO_APPOINTMENT
    f = gf.freshness(GUIDANCE, [_appt("2026-12-10")], TODAY)
    assert f["state"] == gf.NO_APPOINTMENT and f["latest_appointment_date"] is None and f["prompt"] is None
    assert gf.freshness(GUIDANCE, [_appt("2026-12-10"), _appt("2026-10-20")], TODAY)["latest_appointment_date"] == "2026-10-20"


def test_unreadable_is_stated_never_read_as_fresh():
    """ADR-105: a failed read, a missing record, an undated record and an undated appointment are each
    `unreadable` with a reason. Only the broken READ carries read_failed=True."""
    failed = gf.freshness(GUIDANCE, None, TODAY)
    assert failed["state"] == gf.UNREADABLE and failed["read_failed"] is True
    for guidance, appts in (
        (None, [_appt("2026-10-15")]),
        ({**GUIDANCE, "effective": "soon"}, [_appt("2026-10-15")]),
        ({k: v for k, v in GUIDANCE.items() if k != "effective"}, []),
        (GUIDANCE, [{"sk": "APPT#undated#x"}]),
    ):
        f = gf.freshness(guidance, appts, TODAY)
        assert f["state"] == gf.UNREADABLE and f["reason"] and f["prompt"] is None and f["read_failed"] is False


def test_from_rows_reads_only_the_guidance_row_and_the_appt_family():
    """An EVENT# / DOC# row dated after the record is not an appointment. Mutation: widen the family filter to
    every dated row — this reads stale and reds."""
    rows = [GUIDANCE, _appt("2026-09-01"), {"sk": "EVENT#2026-10-20#example"}, {"sk": "DOC#2026-10-21#example"}]
    assert gf.from_rows(rows, TODAY)["state"] == gf.FRESH
    assert gf.from_rows(rows + [_appt("2026-10-20")], TODAY)["state"] == gf.STALE
    assert gf.from_rows(None, TODAY)["read_failed"] is True


class _Table:
    def __init__(self, rows=None, exc=None):
        self.rows, self.exc = rows, exc

    def query(self, **kw):
        if self.exc:
            raise self.exc
        return {"Items": list(self.rows or [])}


def test_read_freshness_never_raises_and_logs_the_class_only(caplog):
    """Mutation: log `%s` with the exception itself — the sentinel in its message reaches the log and this reds."""
    caplog.set_level(logging.DEBUG)
    f = gf.read_freshness(_Table(exc=RuntimeError(SENTINEL + " 2026-10-15")), TODAY)
    assert f["state"] == gf.UNREADABLE and f["read_failed"] is True
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "RuntimeError" in logged and SENTINEL not in logged and "2026-10-15" not in logged
    assert gf.read_freshness(_Table([GUIDANCE, _appt("2026-10-15")]), TODAY)["state"] == gf.STALE
    assert gf.read_freshness(None, TODAY)["state"] == gf.UNREADABLE


# ── privacy ───────────────────────────────────────────────────────────────────────────────
def test_no_record_value_rides_the_flag_and_the_published_form_is_the_state_word_only(caplog):
    """The flag copies two DATES and nothing else from the record; the published-safe form is one word; the
    pure path logs nothing. Mutation: spread the guidance row into `_result` — the sentinel rides the flag."""
    caplog.set_level(logging.DEBUG)
    for appts in ([], [_appt("2026-10-15")], [_appt("2026-09-01")], None):
        f = gf.freshness(GUIDANCE, appts, TODAY)
        assert SENTINEL not in json.dumps(f)
        pub = gf.published_view(f)
        assert set(pub) == {"state"} and pub["state"] in gf.STATES
        assert not re.search(r"\d{4}-\d{2}-\d{2}", json.dumps(pub))
    assert gf.published_view(None) == {"state": gf.UNREADABLE} and gf.published_view({"state": "x"}) == {"state": gf.UNREADABLE}
    assert not caplog.records


# The closed reader set: the flag is written onto the plan's block and the coach packet and read by nothing else.
# A critic, the generator, a ceiling, a progression rule or a commit gate that started reading it would make the
# owner's guidance record a gate on intensity (ruling 7); a web/email module that imported it could publish it.
_ALLOWED_READERS = {
    "lambdas/health/guidance_freshness.py",
    "mcp/tools_plan.py",
    "mcp/tools_coach_packet.py",
}


def _py_files(*dirs: str):
    for d in dirs:
        for base, subdirs, files in os.walk(ROOT / d):
            subdirs[:] = [s for s in subdirs if s not in ("__pycache__", "node_modules", "cdk.out")]
            for name in files:
                if name.endswith(".py"):
                    path = Path(base) / name
                    yield path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8", errors="replace")


def test_the_flag_has_a_closed_reader_set_and_no_web_or_email_module_reaches_it():
    """Mutation: add `from health import guidance_freshness` (or read block['guidance_freshness']) in
    lambdas/coach/critics.py or any lambdas/web/ module — it lands in `offenders` and this reds."""
    offenders = sorted(rel for rel, text in _py_files("lambdas", "mcp") if "guidance_freshness" in text and rel not in _ALLOWED_READERS)
    assert not offenders, f"a module outside the reference surfaces reads the guidance freshness flag: {offenders}"
    # tools_plan: the flag is assigned onto the block AFTER the engine and stage 2 never receives it by name.
    src = (ROOT / "mcp/tools_plan.py").read_text()
    assert src.count('block["guidance_freshness"] = _guidance_freshness()') == 1
    stage2 = src[src.index("def _run_stage_2(") :]
    assert "guidance_freshness" not in stage2


# ── never a gate: the same plan, the same verdicts, stale or not ───────────────────────────
def _lift(day: str) -> dict:
    return {
        "date": day,
        "sk": f"DATE#{day}#WORKOUT#{day}",
        "source_workout_id": day,
        "exercises": [
            {"name": "Linear Leg Press", "sets": [{"type": "normal", "weight_kg": 90, "reps": 8}]},
            {"name": "Bench Press (Barbell)", "sets": [{"type": "normal", "weight_kg": 60, "reps": 8}]},
        ],
    }


def _block():
    rows = [_lift(shift_day_key("2026-10-19", i)) for i in range(12)]
    return plan_engine.constraint_block(
        date=TODAY, weight_lb=300.0, block_workouts=rows, deload_records=[], disruption_records=[], walk_hr_wk_now=9.0
    )


def _verdicts(block: dict) -> list:
    from coach import critics

    ex = {"idx": 0, "movement_key": "bench_press_barbell", "label": "Bench Press (Barbell)", "n_sets": 4, "n_working_sets": 4}
    ex.update({"top_weight_lbs": 135.0, "top_reps": 8, "to_failure": False, "axial": None, "duration_seconds": None})
    draft = {"routine_id": "r", "target_date": TODAY, "archetype": "upper", "total_sets": 4, "exercises": [ex]}
    packets = {
        "muscle_defense": critics.build_muscle_defense_packet(
            draft, anchor_trends={}, program_week=block.get("program_week"), protein_days_missed_7d=0, protein_days_measured_7d=7
        ),
        "joints_tendons": critics.build_joints_packet(
            draft,
            pain_by_idx={},
            days_since_by_idx={},
            loaded_lifting_streak=2,
            pain_layer_status="ok",
            recent_aerobic=block.get("recent_aerobic"),
        ),
        "rate_advocate": critics.build_rate_advocate_packet(
            draft,
            tripwires=block.get("tripwires"),
            walking=block.get("walking"),
            rate_target=block.get("rate_target"),
            current_rate_lb_wk=3.2,
            lifting_sessions_7d=4,
        ),
        "blueprint_historian": critics.build_historian_packet(draft, reference=None, weeks_in_block=2),
    }
    return critics.run_critics(packets, draft, invoke=None, model_allowed=False, model_paused_reason="test")


def test_a_stale_flag_changes_no_prescription_and_no_critic_verdict():
    """Build the plan block and run the four critics with a STALE flag on the block and with none: everything
    but the flag itself is identical — the session, the rate target, the progression and effort limits, the
    tripwires, the steps ramp, the deload recommendation, every verdict. Mutation: have constraint_block or a
    critic packet read `guidance_freshness` and trim on `stale` — the two sides diverge and this reds."""
    plain = _block()
    stale = copy.deepcopy(plain)
    stale["guidance_freshness"] = gf.freshness(GUIDANCE, [_appt("2026-10-15")], TODAY)
    assert stale["guidance_freshness"]["state"] == gf.STALE
    assert {k: v for k, v in stale.items() if k != "guidance_freshness"} == plain
    for key in ("session", "rate_target", "progression", "tripwires", "steps_ramp", "deload_recommendation", "block_model"):
        assert key in plain, key
    assert _verdicts(stale) == _verdicts(plain)
    # and a fresh one is the same answer again
    fresh = {**copy.deepcopy(plain), "guidance_freshness": gf.freshness(GUIDANCE, [_appt("2026-09-01")], TODAY)}
    assert _verdicts(fresh) == _verdicts(plain)


def test_the_plan_tool_attaches_the_flag_from_its_own_seam(monkeypatch):
    """The helper reads through `read_freshness` with today's Pacific day — a broken read is `unreadable`."""
    from mcp import config, tools_plan

    monkeypatch.setattr(config, "table", _Table([GUIDANCE, _appt("2026-10-15")]))
    monkeypatch.setattr(tools_plan, "pacific_today", lambda: "2026-10-10")
    assert tools_plan._guidance_freshness()["state"] == gf.NO_APPOINTMENT  # the appointment is still ahead on that day
    monkeypatch.setattr(tools_plan, "pacific_today", lambda: "2026-10-20")
    assert tools_plan._guidance_freshness()["state"] == gf.STALE
    monkeypatch.setattr(config, "table", _Table(exc=RuntimeError("down")))
    assert tools_plan._guidance_freshness()["state"] == gf.UNREADABLE


def test_the_coach_packet_carries_the_flag_and_a_broken_read_is_read_failed(monkeypatch):
    from mcp import tools_coach_packet as pkt, tools_plan

    monkeypatch.setattr(tools_plan, "_guidance_freshness", lambda: gf.freshness(GUIDANCE, [_appt("2026-10-15")], TODAY))
    value, status = pkt._guidance_freshness(TODAY)
    assert status["state"] == "measured" and value["state"] == gf.STALE and value["prompt"]
    monkeypatch.setattr(tools_plan, "_guidance_freshness", lambda: gf.freshness(GUIDANCE, None, TODAY))
    value, status = pkt._guidance_freshness(TODAY)
    assert status["state"] == "read_failed" and value["state"] == gf.UNREADABLE


# ── the writer + the family's classification ─────────────────────────────────────────────
def test_the_loader_writes_appointments_as_the_appt_family():
    import importlib.util

    spec = importlib.util.spec_from_file_location("load_clinical_record_5059", ROOT / "scripts/load_clinical_record.py")
    loader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loader)
    record = {"appointments": [{"date": "2026-10-15", "kind": "Example Visit"}, {"date": "2026-10-20T09:00"}]}
    sks = [i["sk"] for i in loader.build_items(record, now="2026-10-21T00:00:00+00:00")]
    assert sks == ["APPT#2026-10-15#example-visit", "APPT#2026-10-20#appointment"]
    try:
        loader.build_items({"appointments": [{"kind": "x"}]})
    except ValueError as e:
        assert "appointment" in str(e)
    else:
        raise AssertionError("an undated appointment must be refused")
    assert gf.from_rows([GUIDANCE] + loader.build_items(record), TODAY)["state"] == gf.STALE


def test_the_appt_family_is_cross_phase_like_the_rest_of_the_record():
    from experiment import phase_taxonomy as pt

    assert pt.classify("USER#matthew#SOURCE#clinical", "APPT#2026-01-01#example") == pt.classify(
        "USER#matthew#SOURCE#clinical", "GUIDANCE#current"
    )
