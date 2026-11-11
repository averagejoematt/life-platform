"""tests/test_tripwire_audit_5802.py — every owner tripwire is read by named code, or is an owner ruling away (#5802).

On 2026-11-11 `owner_redlines.unevaluated_tripwires()` returned 19 of 28 tripwires and 16 of them
had no reader anywhere; `weight_stall_with_adherence` was "evaluated" by plan_engine over two inputs
`mcp/tools_plan.py` marked `not_read`, so it could never leave `unknown`. The audit gave each of the
20 a disposition:

  WIRE            a report-only reader in `health.tripwire_readers` (or plan_engine for volume_ceiling)
  EVALUATED       already read by `health.nutrition_critics` — now marked `evaluated_by` it
  MERGE           pointed at the one evaluation that covers it (`merged_into`, or plan_engine reading
                  nutrition_critics' stall evaluation instead of computing its own)
  PROPOSE-DELETE  left in place, unread, for an owner ruling recorded in `training.redline_changelog`

What this pins:
  1. `unevaluated_tripwires()` is EXACTLY the propose-delete set — a new unread tripwire, or a
     proposal wired without updating this list, reds here.
  2. `READER_IDS` and the `evaluated_by: health.tripwire_readers` marks are the same set, both ways.
  3. Every reader reads `unknown` on an empty input dict — an unreadable input is never a pass.
  4. Each reader trips and clears on fixtures built from the redline's own thresholds.
  5. plan_engine's stall row is nutrition_critics' evaluation (one evaluation, two readers).
  6. Report-only: the rows never move a critic verdict.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

from health import (
    nutrition_critics as nc,  # noqa: E402
    tripwire_readers as tr,  # noqa: E402
)
from training import (
    owner_redlines as rl,  # noqa: E402
    plan_engine,  # noqa: E402
)

TW = {t["id"]: t for t in rl.TRIPWIRES}

# The owner's decision list. Each entry: why it cannot be read by measured inputs today.
PROPOSE_DELETE = {
    "leverage_not_deterioration": "action is 'log it; no action' — an interpretation note on anchor_lift_strength_drop, not a tripwire",
    "medical_stop_lines": "symptoms are self-report and the labs cadence is not wired — a human stop line, not a machine one",
    "mood_declared": "PHQ-9 is not instrumented; the declaration is his — no measured input exists",
    "joy": "no weekly yes/no instrument exists",
    "post_goal_walking": "maintenance-phase only and needs the cut-phase walking mean — dormant until the landing",
}
WIRED_HERE = {
    "loss_acceptable",
    "loss_insufficient_adherent",
    "loss_insufficient_nonadherent",
    "under_floor",
    "walking_vs_fork",
    "weigh_in_dark",
    "lean_mass",
    "sleep",
}
EVALUATED_BY_CRITICS = {"rate_overshoot", "intake_floor_breached", "logging_dark", "weight_stall_with_adherence"}
MERGED = {"loss_excessive_clean": "rate_overshoot", "loss_excessive_flagged": "rate_overshoot"}
AUDITED = set(PROPOSE_DELETE) | WIRED_HERE | EVALUATED_BY_CRITICS | set(MERGED) | {"volume_ceiling"}


def _inputs(**over):
    """An adherent fortnight at 317 lb, losing exactly the served target, walking above the floor, sleeping enough."""
    base = {
        "window_end": "2026-09-20",
        "intake_kcal_by_day": [2000] * 14,
        "protein_g_by_day": [205] * 14,
        "lifting_day_flags": [True, True, False, True, True, True, False] * 2,
        "weight_lb": 317.0,
        "rate_provisional": False,
        "weeks_since_genesis": 6,
        "walking_hr_this_wk": rl.REDLINES["walking_floor_hr_wk"]["value"] + 1,
        "walking_hr_last_wk": rl.REDLINES["walking_floor_hr_wk"]["value"] + 1,
        "last_weighin_date": "2026-09-20",
        "weighin_count": 12,
        "sleep_hours_by_day": [TW["sleep"]["threshold_hours"] + 1] * 14,
        "dxa_scans": [],
    }
    base.update(over)
    target = tr._target(base)
    base.setdefault("weight_trend_lb_wk", -target)
    base.setdefault("weekly_loss_rates_lb_wk", [target, target])
    return base


def _rows(inputs):
    return {r["id"]: r for r in tr.evaluate(inputs)}


# ── 1/2. the disposition table is the code ────────────────────────────────────────────────
def test_unevaluated_tripwires_is_exactly_the_propose_delete_set():
    assert rl.unevaluated_tripwires() == [t["id"] for t in rl.TRIPWIRES if t["id"] in PROPOSE_DELETE]
    assert set(rl.unevaluated_tripwires()) == set(PROPOSE_DELETE)
    assert rl.summary()["unevaluated_tripwires"] == rl.unevaluated_tripwires()


def test_every_audited_tripwire_has_exactly_one_disposition_and_it_is_in_the_data():
    groups = [set(PROPOSE_DELETE), WIRED_HERE, EVALUATED_BY_CRITICS, set(MERGED), {"volume_ceiling"}]
    assert sum(len(g) for g in groups) == len(AUDITED) == 20, "one disposition per tripwire — the issue's 19 plus the stall"
    assert AUDITED <= set(TW)
    elsewhere = rl.evaluated_elsewhere()
    problems = []
    for tid in WIRED_HERE:
        if elsewhere.get(tid) != "health.tripwire_readers":
            problems.append(f"{tid}: wired here but marked {elsewhere.get(tid)!r}")
    for tid in EVALUATED_BY_CRITICS:
        if TW[tid].get("evaluated_by") != "health.nutrition_critics":
            problems.append(f"{tid}: not marked evaluated_by health.nutrition_critics")
    for tid, into in MERGED.items():
        if TW[tid].get("merged_into") != into or into not in elsewhere:
            problems.append(f"{tid}: must merge into {into}, itself read by a named module")
    if TW["volume_ceiling"].get("evaluated_by_engine", True) is not True or TW["volume_ceiling"].get("tripwire_class") != "report_only":
        problems.append("volume_ceiling: an engine row, report-only")
    assert not problems, problems


def test_reader_ids_and_the_evaluated_by_marks_are_one_set_both_ways():
    marked = {t["id"] for t in rl.TRIPWIRES if t.get("evaluated_by") == "health.tripwire_readers"}
    assert marked == set(tr.READER_IDS) == WIRED_HERE
    assert set(tr._READERS) == set(tr.READER_IDS)


def test_mutation_control_an_unmarked_reader_reappears_as_unevaluated(monkeypatch):
    patched = [dict(t) for t in rl.TRIPWIRES]
    for t in patched:
        if t["id"] == "sleep":
            t.pop("evaluated_by")
            t["evaluated_by_engine"] = False
    monkeypatch.setattr(rl, "TRIPWIRES", patched)
    assert "sleep" in rl.unevaluated_tripwires()


def test_every_engine_evaluated_tripwire_has_an_engine_row_and_no_other_does():
    """An unmarked tripwire defaults to `evaluated_by_engine` — so the engine's rows must be exactly that set, or a
    tripwire stripped of its marks would claim an evaluation nobody runs."""
    rows = [r["id"] for r in plan_engine.constraint_block(date="2026-09-21")["tripwires"]]
    assert sorted(rows) == sorted(t["id"] for t in rl.engine_evaluated_tripwires())


# ── 3. unknown is never a pass ────────────────────────────────────────────────────────────
def test_every_reader_reads_unknown_on_empty_inputs_and_every_row_is_report_only():
    rows = tr.evaluate({})
    assert [r["id"] for r in rows] == list(tr.READER_IDS)
    bad = [(r["id"], r["state"]) for r in rows if r["state"] != "unknown"]
    assert not bad, f"an absent input read as a verdict: {bad}"
    assert all(r["report_only"] and r["evaluated_by"] == "health.tripwire_readers" for r in rows)


def test_a_raising_reader_reads_read_failed_and_the_rest_still_report(monkeypatch):
    monkeypatch.setitem(tr._READERS, "sleep", lambda inputs: 1 / 0)
    rows = _rows(_inputs())
    assert rows["sleep"]["state"] == "read_failed" and "ZeroDivisionError" in rows["sleep"]["detail"]
    assert rows["under_floor"]["state"] == "clear"


def test_a_provisional_rate_reads_unknown_never_on_schedule():
    rows = _rows(_inputs(rate_provisional=True))
    assert rows["loss_acceptable"]["state"] == "unknown" and "rate_provisional" in rows["loss_acceptable"]["unknown"]


# ── 4. each reader trips and clears from the redline's own thresholds ─────────────────────
def test_the_clean_fortnight_reads_on_schedule_and_every_other_reader_clear():
    rows = _rows(_inputs())
    assert rows["loss_acceptable"]["state"] == "tripped"  # 'tripped' = on schedule, the computed base case
    others = {k: r["state"] for k, r in rows.items() if k not in ("loss_acceptable", "lean_mass")}
    assert set(others.values()) == {"clear"}, others
    assert rows["lean_mass"]["state"] == "unknown"  # no DXA interval in the fixture


def test_the_rate_rules_trip_on_a_slow_trend():
    target = tr._target(_inputs())
    slow = target * TW["loss_insufficient_adherent"]["threshold_pct_of_target"] / 100 * 0.5
    adherent = _rows(_inputs(weight_trend_lb_wk=-slow, weekly_loss_rates_lb_wk=[slow, slow]))
    assert adherent["loss_insufficient_adherent"]["state"] == "tripped"
    assert adherent["loss_insufficient_nonadherent"]["state"] == "clear"
    assert adherent["loss_acceptable"]["state"] == "clear"
    dark = [2000] * 9 + [None] * 5
    nonadherent = _rows(_inputs(weight_trend_lb_wk=-slow, weekly_loss_rates_lb_wk=[slow, slow], intake_kcal_by_day=dark))
    assert nonadherent["loss_insufficient_nonadherent"]["state"] == "tripped"
    assert nonadherent["loss_insufficient_adherent"]["state"] == "clear"


def test_the_nonadherent_arm_is_unknown_when_the_adherence_half_cannot_be_read():
    target = tr._target(_inputs())
    slow = target * 0.1
    row = _rows(_inputs(weight_trend_lb_wk=-slow, walking_hr_this_wk=None, intake_kcal_by_day=None))["loss_insufficient_nonadherent"]
    assert row["state"] == "unknown"


def test_under_floor_counts_logged_days_only():
    t = TW["under_floor"]
    low = t["threshold_kcal"] - 100
    n = int(t["threshold_days"])
    assert _rows(_inputs(intake_kcal_by_day=[2000] * (14 - n) + [low] * n))["under_floor"]["state"] == "tripped"
    assert _rows(_inputs(intake_kcal_by_day=[2000] * (14 - n) + [None] * n))["under_floor"]["state"] == "clear"


def test_walking_vs_fork_needs_both_weeks_under_the_floor_while_on_target():
    floor = rl.REDLINES["walking_floor_hr_wk"]["value"]
    assert _rows(_inputs(walking_hr_this_wk=floor - 1, walking_hr_last_wk=floor - 1))["walking_vs_fork"]["state"] == "tripped"
    assert _rows(_inputs(walking_hr_this_wk=floor - 1))["walking_vs_fork"]["state"] == "clear"


def test_weigh_in_dark_counts_from_the_last_weigh_in_and_an_empty_read_is_dark():
    assert _rows(_inputs(last_weighin_date="2026-09-16"))["weigh_in_dark"]["state"] == "tripped"
    assert _rows(_inputs(last_weighin_date="2026-09-19"))["weigh_in_dark"]["state"] == "clear"
    assert _rows(_inputs(last_weighin_date=None, weighin_count=0))["weigh_in_dark"]["state"] == "tripped"
    assert _rows(_inputs(last_weighin_date=None, weighin_count=None))["weigh_in_dark"]["state"] == "unknown"


def _scan(date, total, lean):
    return {"scan_date": date, "body_composition": {"total_mass_lb": total, "lean_mass_lb": lean, "bone_mineral_content_lb": 8.0}}


def test_lean_mass_reads_the_last_dxa_interval():
    th = TW["lean_mass"]["threshold"]
    lost = 40.0  # synthetic scans, 8 weeks apart
    lean_ok, lean_bad = lost * (th["lean_share_pct"] - 10) / 100, lost * (th["lean_share_pct"] + 10) / 100
    ok = [_scan("2026-03-30", 300.0, 150.0), _scan("2026-05-25", 300.0 - lost, 150.0 - min(lean_ok, th["lean_lb_wk"] * 8 - 1))]
    bad = [_scan("2026-03-30", 300.0, 150.0), _scan("2026-05-25", 300.0 - lost, 150.0 - lean_bad)]
    assert _rows(_inputs(dxa_scans=ok))["lean_mass"]["state"] == "clear"
    assert _rows(_inputs(dxa_scans=bad))["lean_mass"]["state"] == "tripped"
    assert _rows(_inputs(dxa_scans=ok[:1]))["lean_mass"]["state"] == "unknown"


def test_sleep_trips_only_when_every_trailing_mean_is_under_the_line():
    line = TW["sleep"]["threshold_hours"]
    assert _rows(_inputs(sleep_hours_by_day=[line - 1] * 14))["sleep"]["state"] == "tripped"
    assert _rows(_inputs(sleep_hours_by_day=[line - 1] * 13 + [line + 20]))["sleep"]["state"] == "clear"
    assert _rows(_inputs(sleep_hours_by_day=[line - 1] * 4 + [None] * 10))["sleep"]["state"] == "unknown"


# ── 5. one stall evaluation, two readers ──────────────────────────────────────────────────
def _stall_inputs():
    lo, hi = nc._energy({"window_end": "2026-09-20"})["prescribed"]
    return _inputs(intake_kcal_by_day=[(lo + hi) // 2] * 14, weight_trend_lb_wk=0.1, weekly_loss_rates_lb_wk=[0.0, -0.1])


def test_stall_from_block_maps_every_decisions_offered_state():
    tid = "weight_stall_with_adherence"
    assert tr.stall_from_block({"decisions_offered": []})["state"] == "clear"
    unev = {"decisions_offered": [{"state": "unevaluable", "trigger": {"id": tid}, "unknown": ["intake_kcal_by_day"]}]}
    assert tr.stall_from_block(unev)["state"] == "unknown" and "intake_kcal_by_day" in tr.stall_from_block(unev)["detail"]
    done = {"decisions_offered": [{"state": "already_decided", "trigger": {"id": tid}, "already_decided": "DECISION#1"}]}
    assert tr.stall_from_block(done)["state"] == "tripped"
    assert tr.stall_from_block({"error": "boom", "decisions_offered": []})["state"] == "read_failed"
    assert tr.stall_from_block(None)["state"] == "read_failed"


def test_plan_engine_reads_nutrition_critics_stall_evaluation_not_its_own():
    block = nc.block(_stall_inputs())
    offered = [d for d in block["decisions_offered"] if d["trigger"]["id"] == "weight_stall_with_adherence"]
    assert offered and offered[0]["state"] == "pending"
    ev, status = plan_engine.stall_input(block)
    plan = plan_engine.constraint_block(date="2026-09-21", weight_stall_evaluation=ev, input_status={"weight_stall_evaluation": status})
    row = next(r for r in plan["tripwires"] if r["id"] == "weight_stall_with_adherence")
    assert row["state"] == "tripped" and row["evaluated_by"] == "health.nutrition_critics"
    assert row["input_state"]["state"] == "measured"
    clean = plan_engine.stall_input(nc.block(_inputs()))
    assert clean[0]["state"] == "clear"
    failed_ev, failed_status = plan_engine.stall_input({"error": "ddb down"})
    plan = plan_engine.constraint_block(
        date="2026-09-21", weight_stall_evaluation=failed_ev, input_status={"weight_stall_evaluation": failed_status}
    )
    row = next(r for r in plan["tripwires"] if r["id"] == "weight_stall_with_adherence")
    assert row["state"] == "read_failed" and "weight_stall_with_adherence" in plan["failed_read_tripwires"]


def test_the_engine_has_no_stall_input_path_of_its_own():
    assert "weight_stall_days" not in plan_engine.ENGINE_INPUTS and "adherence_on_plan" not in plan_engine.ENGINE_INPUTS
    src = (REPO / "mcp" / "tools_plan.py").read_text(encoding="utf-8")
    assert "weight_stall_days" not in src and "adherence_on_plan" not in src


# ── volume_ceiling: an engine row, report-only ────────────────────────────────────────────
def test_volume_ceiling_reports_the_muscles_above_the_band_top():
    ceiling = TW["volume_ceiling"]["threshold"]["sets_per_muscle_wk"]
    plan = plan_engine.constraint_block(date="2026-09-21", muscle_volume={"chest": ceiling + 2, "back": ceiling - 2})
    row = next(r for r in plan["tripwires"] if r["id"] == "volume_ceiling")
    assert row["state"] == "tripped" and set(row["observed"]) == {"chest"} and row["report_only"] is True
    plan = plan_engine.constraint_block(date="2026-09-21", muscle_volume={"back": ceiling})
    assert next(r for r in plan["tripwires"] if r["id"] == "volume_ceiling")["state"] == "clear"
    plan = plan_engine.constraint_block(date="2026-09-21")
    assert next(r for r in plan["tripwires"] if r["id"] == "volume_ceiling")["state"] == "unknown"


# ── 6. report-only ────────────────────────────────────────────────────────────────────────
def test_the_report_rows_never_move_a_critic_verdict():
    inputs = _inputs(intake_kcal_by_day=[1000] * 14, sleep_hours_by_day=[3.0] * 14, last_weighin_date="2026-09-01")
    assert {r["id"] for r in nc.block(inputs)["tripwire_reports"] if r["state"] == "tripped"} >= {"sleep", "weigh_in_dark", "under_floor"}
    assert [v["verdict"] for v in nc.block(inputs)["verdicts"]] == [v["verdict"] for v in nc.run(inputs)["verdicts"]]
