"""#5796 — prescription reconciliation.

(a) A movement above its prescribed working sets three complete weeks running comes back as a PROPOSAL to raise its
    prescription (`training.self_added_volume.propose_set_raises`), carried on the plan's constraint block beside the
    ceiling-change proposal. Never applied.
(b) A cardio machine swap that `adherence_calc._extra_cardio_shapes` pairs with the missing programmed block is graded
    under #5505's one counting rule (`cardio_menu.swap_counts`) in three states (owner ruling 2026-11-11): `met` (RPE
    logged at or above the served kind's band floor, duration complete), `done_effort_not_logged` (duration complete, no
    RPE — never met, reported on its own) and `not_met`. The effort is the set row's RPE first, his note's second; a
    drafted cardio note opens with an `RPE _` prompt. The real 2026-10-29..11-10 swap days are replayed from a fixture
    read off DynamoDB (his notes stripped).
"""

from __future__ import annotations

import json
from pathlib import Path

from health import adherence_calc
from health.adherence_calc import calculate_adherence
from training import cardio_menu, self_added_volume
from training.routine_ir import ExerciseBlock, RoutineSpec, Set

FIXTURE = Path(__file__).parent / "fixtures" / "prescription_reconciliation_5796" / "swap_days_2026_10_29_to_11_10.json"
REAL_DAYS = json.loads(FIXTURE.read_text())["days"]


# ── (b) the cardio swap ─────────────────────────────────────────────────────────────────────────────────────────────
def _ir(day: dict) -> RoutineSpec:
    return RoutineSpec(
        routine_id=f"r-5796-{day['date']}",
        target_date=day["date"],
        archetype="upper",
        exercises=[
            ExerciseBlock(
                movement_key=b["movement_key"],
                rationale_tag=b["rationale_tag"],
                notes=b["notes"],
                sets=[Set(duration_seconds=s) for s in b["duration_seconds"]],
            )
            for b in day["served"]
        ],
    )


def _performed(day: dict, note: str | None = None, minutes: int | None = None) -> dict:
    exs = []
    for ex in day["performed"]:
        sets = [{**s, "duration_seconds": minutes * 60} if minutes is not None else dict(s) for s in ex["sets"]]
        exs.append({**ex, "notes": ex["notes"] if note is None else note, "sets": sets})
    return {"exercises": exs}


def _served_kind(day: dict) -> str:
    return day["served"][0]["rationale_tag"].split(":")[3]


def _floor(day: dict) -> int:
    return cardio_menu.wire_band(_served_kind(day))[0]


def _cardio(out: dict) -> dict:
    return out["as_prescribed_by_kind"]["cardio"]


def _pre_fix(monkeypatch, ir, performed):
    """The pre-#5796 grade: the swap is paired and read, never credited (the carve-out this issue retires)."""
    with monkeypatch.context() as m:
        m.setattr(adherence_calc, "_swap_credit", lambda *a, **k: None)
        return calculate_adherence(ir, performed)


def test_the_fixture_is_the_real_week_every_swap_read_no():
    assert [d["date"] for d in REAL_DAYS] == [
        "2026-10-29",
        "2026-10-30",
        "2026-11-02",
        "2026-11-03",
        "2026-11-05",
        "2026-11-09",
        "2026-11-10",
    ]
    assert all(d["stored_cardio_verdict"] == "no" for d in REAL_DAYS)


def test_real_swap_days_replay_no_before_effort_not_logged_as_logged_and_met_with_the_effort(monkeypatch):
    """Every real swap day read `no` on the live row. Replayed with his notes as logged (none logs an RPE; each swap ran at
    least the served minutes) every one reads `done_effort_not_logged` — never `yes`, never `no`. With the served band's
    floor logged it reads `yes` with `substituted_by` named. The pre-fix grader (the must-fail control) reads `no` on both."""
    offenders = []
    for day in REAL_DAYS:
        ir, gone = _ir(day), day["served"][0]["movement_key"]
        swap_key = cardio_menu.machine_template_ids(adherence_calc._load_catalog())[day["performed"][0]["exercise_template_id"]]
        as_logged = _cardio(calculate_adherence(ir, _performed(day)))
        if as_logged["verdict"] != "done_effort_not_logged" or as_logged.get("effort_not_logged") != {gone: swap_key}:
            offenders.append(f"{day['date']} as logged: {as_logged['verdict']} {as_logged['reasons']}")
        if "substituted_by" in as_logged:
            offenders.append(f"{day['date']} as logged was credited as met")
        logged = _performed(day, note=f"RPE {_floor(day)}")
        after = _cardio(calculate_adherence(ir, logged))
        if after["verdict"] != "yes" or after.get("substituted_by") != {gone: swap_key}:
            offenders.append(f"{day['date']} with RPE logged: {after['verdict']} {after['reasons']} {after.get('substituted_by')}")
        for name, performed in (("as logged", _performed(day)), ("with RPE", logged)):
            before = _cardio(_pre_fix(monkeypatch, ir, performed))
            if before["verdict"] != "no":
                offenders.append(f"{day['date']} pre-fix control {name}: {before['verdict']}")
    assert not offenders, offenders


def test_each_state_and_its_controls():
    day = next(d for d in REAL_DAYS if d["date"] == "2026-11-05")  # a 30-minute tempo served, a treadmill walk done
    ir = _ir(day)
    cases = {
        # name: (performed, expected verdict, expected state)
        "met": (_performed(day, note=f"RPE {_floor(day)}"), "yes", "met"),
        "not logged": (_performed(day, note="3.1 mph / 5 incline"), "done_effort_not_logged", "done_effort_not_logged"),
        "shorter, logged": (_performed(day, note=f"RPE {_floor(day)}", minutes=20), "no", "not_met"),
        "shorter, not logged": (_performed(day, note="", minutes=20), "no", "not_met"),
        "under the floor": (_performed(day, note=f"RPE {_floor(day) - 1}"), "no", "not_met"),
        "the unfilled prompt": (_performed(day, note="RPE _"), "done_effort_not_logged", "done_effort_not_logged"),
        # a copied prescription line is never his logged effort
        "prescription line": (_performed(day, note=day["served"][0]["notes"]), "done_effort_not_logged", "done_effort_not_logged"),
    }
    offenders = []
    for name, (performed, verdict, state) in cases.items():
        c = _cardio(calculate_adherence(ir, performed))
        got = c["shape"]["treadmill"]["counting"]["state"]
        if c["verdict"] != verdict or got != state or (("substituted_by" in c) != (state == "met")):
            offenders.append(f"{name}: {c['verdict']} / {got}")
    assert not offenders, offenders


def test_the_set_row_rpe_is_read_before_the_note():
    """Hevy's wire carries an `rpe` slot on a duration set (always null in his history so far): when it is filled it is the
    effort, ahead of the note."""
    day = next(d for d in REAL_DAYS if d["date"] == "2026-11-05")
    performed = _performed(day, note=f"RPE {_floor(day) - 2}")
    performed["exercises"][0]["sets"] = [{**st, "rpe": float(_floor(day))} for st in performed["exercises"][0]["sets"]]
    c = _cardio(calculate_adherence(_ir(day), performed))
    counting = c["shape"]["treadmill"]["counting"]
    assert counting["rpe_source"] == "set_row" and counting["state"] == "met" and c["verdict"] == "yes"
    # control: the same note without the set-row RPE is under the floor
    assert _cardio(calculate_adherence(_ir(day), _performed(day, note=f"RPE {_floor(day) - 2}")))["verdict"] == "no"


def test_a_met_swap_is_still_graded_against_the_blocks_ceiling():
    """Meeting the #5505 floor counts the swap; the block's own ceiling (plus the charter tolerance) still grades it."""
    day = next(d for d in REAL_DAYS if d["date"] == "2026-11-02")  # easy, RPE 4–5 served
    c = _cardio(calculate_adherence(_ir(day), _performed(day, note="RPE 9")))
    assert c["shape"]["treadmill"]["counts_as_performed"] is True
    assert c["verdict"] == "no" and any(r.startswith("intensity:") for r in c["reasons"])


def test_the_programmed_block_reads_its_note_rpe_the_same_way():
    """No asymmetry on a logged effort: the served block on the served machine with the same note grades as the met swap."""
    day = next(d for d in REAL_DAYS if d["date"] == "2026-11-05")
    ride = {
        "exercise_template_id": "D8F7F851",
        "title": "Cycling",
        "notes": "RPE 6",
        "sets": [{"type": "normal", "duration_seconds": 1800}],
    }
    on_machine = _cardio(calculate_adherence(_ir(day), {"exercises": [ride]}))
    swapped = _cardio(calculate_adherence(_ir(day), _performed(day, note="RPE 6")))
    assert on_machine["verdict"] == swapped["verdict"] == "yes"
    silent = _cardio(calculate_adherence(_ir(day), {"exercises": [{**ride, "notes": ""}]}))
    assert silent["verdict"] == "unknown"  # absence stays absence (ADR-104)


def test_one_rule_two_readers():
    """`kind_of_performed` (the week's conditioning count) and adherence's `swap_counts` give one answer on every note."""
    offenders = []
    for kind in cardio_menu.HARD:
        machine = "cycling" if not cardio_menu.fits_machine(kind, "treadmill") else "elliptical"
        for note in ("", "steady", "RPE _", "RPE 3", "RPE 5", "RPE 6", "rpe 6.5", "RPE 7", "RPE 8", "RPE 9"):
            counts = cardio_menu.swap_counts(kind, note)["counts"]
            if (cardio_menu.kind_of_performed(machine, note, swap_kind=kind) == kind) is not counts:
                offenders.append((kind, note, counts))
    assert not offenders, offenders


def _week(*sessions):
    """A cardio index for one machine (the treadmill) and the bike's template id, served hills on the bike each day."""
    catalog = adherence_calc._load_catalog()
    tid = next(t for t, k in cardio_menu.machine_template_ids(catalog).items() if k == "treadmill")
    return {tid: [{"date": d, "note": n, "duration_sec": 2700, "hevy_routine_id": f"r{d}"} for d, n in sessions]}, catalog


def test_the_weekly_count_reports_effort_not_logged_on_its_own(monkeypatch):
    """In the conditioning count a swap with no effort logged is neither conditioning nor a miss: its own list."""
    index, catalog = _week(("2026-11-02", ""), ("2026-11-03", "RPE 7"), ("2026-11-04", "RPE 3"))
    served = {f"r{d}": {"cycling": "hills"} for d in ("2026-11-02", "2026-11-03", "2026-11-04")}
    annotated = cardio_menu.annotate_served(index, served, catalog)

    class _R:
        def __init__(self, d):
            self.target_date, self.hevy_routine_id, self.status, self.version = d, f"r{d}", "pushed", 1
            self.exercises = [ExerciseBlock(movement_key="cycling", rationale_tag="cardio:cycling:menu:hills")]

    routines = [_R(d) for d in ("2026-11-02", "2026-11-03", "2026-11-04")]
    monkeypatch.setattr(cardio_menu, "reoffers_per_wk", lambda: 0)
    hist = cardio_menu.history_context(annotated, catalog, "2026-11-05", routines=routines)
    assert hist["effort_not_logged_kinds"] == ["hills"]  # 11-02: done, no RPE
    assert hist["week_kinds"].count("hills") == 1  # 11-03: met at RPE 7
    assert hist["missed_kinds"] == ["hills"]  # 11-04: RPE 3, under the floor — the only miss
    assert hist["counted_kinds"].count("hills") == 2  # the met one + the dropped miss; never the not-logged one
    # must-fail control: read as a miss (the pre-ruling count), the not-logged day would be dropped into the count
    monkeypatch.setattr(cardio_menu, "effort_not_logged_rows", lambda *a, **k: [])
    assert cardio_menu.history_context(annotated, catalog, "2026-11-05", routines=routines)["counted_kinds"].count("hills") == 3


def test_the_drafted_note_opens_with_the_rpe_prompt_and_lints_clean():
    from training import cardio_note, hevy_note_grammar as g, hevy_note_lint as lint

    offenders = []
    for kind in cardio_menu.KINDS:
        for machine in ("cycling", "treadmill", "elliptical", "rowing_machine"):
            note, _ = cardio_note.compose(movement_key=machine, minutes=30, target_date="2026-11-11", kind=kind, facts={"last_level": 11})
            if not note.startswith(g.CARDIO_RPE_CAPTURE_LINE + "\n"):
                offenders.append(f"{kind}/{machine}: no prompt")
            problems = []
            lint._lint_cardio(note, "x", False, problems)
            if problems:
                offenders.append(f"{kind}/{machine}: {[p.message for p in problems]}")
            if cardio_note.read_line1(note) is None:
                offenders.append(f"{kind}/{machine}: line 1 unread behind the prompt")
    assert not offenders, offenders


def test_the_prompt_anywhere_but_the_top_or_filled_in_fails_the_linter():
    """Must-fail controls for the linter's one accommodation: only the unfilled prompt, only as the first line."""
    from training import cardio_note, hevy_note_lint as lint

    note, _ = cardio_note.compose(movement_key="cycling", minutes=30, target_date="2026-11-11", kind="easy", facts={"last_level": 11})
    body = cardio_note.without_capture(note)
    for bad in (body + "\nRPE _", "RPE 7\n" + body, "RPE ?\n" + body):
        problems = []
        lint._lint_cardio(bad, "x", False, problems)
        assert any(p.rule == "L3" for p in problems), bad


# ── (a) the set-raise proposal ──────────────────────────────────────────────────────────────────────────────────────
_CATALOG = {"movements": {"lateral_raise": {"title": "Lateral Raise", "primary_muscle": "side_delts"}}}


def _row(day: str, prescribed: int, performed: int, key: str = "lateral_raise") -> dict:
    return {
        "date": day,
        "sk": f"DATE#{day}#WORKOUT#x",
        "adherence": {
            "status": "matched",
            "movements": [
                {"movement_key": key, "programmed_working_sets": prescribed, "performed_working_sets": performed, "intensity": {}},
            ],
            "extra": [],
        },
    }


# Mondays of four consecutive weeks; the plan day 2026-11-11 sits in the fourth, in progress
_WEEKS = ("2026-10-19", "2026-10-26", "2026-11-02")


def _proposal(rows, date="2026-11-11"):
    return self_added_volume.propose_set_raises(self_added_volume.weekly_excess(rows, date), 3, _CATALOG)


def test_three_weeks_running_proposes_the_raise_with_its_evidence_and_headroom():
    rows = [_row(d, 3, 4) for d in _WEEKS]
    out = _proposal(rows)
    assert out["state"] == "proposed" and out["auto_applied"] is False
    (p,) = out["proposals"]
    assert p["movement_key"] == "lateral_raise" and p["prescribed_sets_per_session"] == 3 and p["proposed_sets_per_session"] == 4
    assert [w["sessions"][0]["performed_sets"] for w in p["weeks"]] == [4, 4, 4]
    vc = p["volume_ceiling"]
    assert vc["redline"] == "volume_ceiling" and vc["muscle"] == "side_delts"
    assert vc["headroom_sets"] == vc["ceiling_sets_per_muscle_wk"] - 3 and vc["added_sets_per_wk"] == 1 and vc["fits"] is True
    assert "Nothing changes until you approve" in p["text"]


def test_a_two_week_run_proposes_nothing():
    """Negative control: the week before the run was at the prescription."""
    rows = [_row(_WEEKS[0], 3, 3), _row(_WEEKS[1], 3, 4), _row(_WEEKS[2], 3, 4)]
    assert _proposal(rows)["state"] == "none"
    # must-fail control: the same rows read as a 2-week rule DO propose — the run length is what held it back
    assert self_added_volume.propose_set_raises(self_added_volume.weekly_excess(rows, "2026-11-11"), 2, _CATALOG)["state"] == "proposed"


def test_the_in_progress_week_never_counts_and_a_missing_week_is_insufficient():
    rows = [_row(_WEEKS[1], 3, 4), _row(_WEEKS[2], 3, 4), _row("2026-11-10", 3, 4)]
    assert _proposal(rows)["state"] == "insufficient"


def test_the_proposed_count_is_the_fewest_he_performed_and_never_at_the_prescription():
    rows = [_row(_WEEKS[0], 3, 5), _row(_WEEKS[1], 3, 4), _row(_WEEKS[2], 3, 5)]
    assert _proposal(rows)["proposals"][0]["proposed_sets_per_session"] == 4


def test_the_run_length_is_the_charters_and_the_window_covers_it():
    assert self_added_volume.set_raise_weeks() == 3
    assert self_added_volume.set_raise_weeks() <= self_added_volume.LOOKBACK_WEEKS  # the plan's prescription window reads this many


def test_the_plan_carries_it_and_an_unread_window_is_unknown_never_none():
    rows = [_row(d, 3, 4) for d in _WEEKS]
    out = self_added_volume.set_raise_for_plan("2026-11-11", rows, "measured", _CATALOG["movements"])
    assert out["state"] == "proposed" and out["auto_applied"] is False
    unread = self_added_volume.set_raise_for_plan("2026-11-11", None, None, _CATALOG["movements"])
    assert unread["state"] == "unknown" and unread["proposals"] == []


def test_an_unread_charter_is_unknown_on_the_block_never_a_failed_plan(monkeypatch):
    rows = [_row(d, 3, 4) for d in _WEEKS]
    monkeypatch.setattr("training.training_charter.charter_value", lambda *a, **k: None)
    out = self_added_volume.set_raise_for_plan("2026-11-11", rows, "measured", _CATALOG["movements"])
    assert out["state"] == "unknown" and "charter" in out["reason"] and out["proposals"] == []
