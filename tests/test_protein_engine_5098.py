"""#5098 — the protein engine: the charter's protein range, four feedings, ONE hit definition, the breakfast nudge.

Every protein figure below is DERIVED from the charter's range low (`FLOOR`), never typed: the fixture week is the
#5003 shape (a day four grams under the floor that the old macros view, with its 5 % tolerance, called a hit while the
`protein_floor_missed` tripwire counted it missed), rebuilt relative to whatever the floor is.

No live clock: every entrypoint takes its instant as an argument (`nudge_decide(now_pt=TICK)`, `runner.run(table,
send, TICK_UTC, tier)`, the dead-man's injected `pt_now`), and the macros view is driven with explicit dates.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

import pytest

_REPO = os.path.join(os.path.dirname(__file__), "..")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, _REPO)

from common import constants  # noqa: E402
from common.pacific_time import PACIFIC  # noqa: E402
from emails import protein_nudge_runner as runner  # noqa: E402
from health import (
    protein_engine as pe,  # noqa: E402
    scoring_engine,  # noqa: E402
)
from operational import nudge_ledger_qa  # noqa: E402
from training import redline_rate, training_charter  # noqa: E402

DAY = "2026-10-20"
TICK = datetime(2026, 10, 20, 10, 10, tzinfo=PACIFIC)  # 10:10 PT: the first hourly tick inside the breakfast window
TICK_UTC = TICK.astimezone(timezone.utc)


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    """The bundled PUBLIC charter only: no owner twin from the laptop's env, no live S3 probe."""
    monkeypatch.delenv(training_charter.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(training_charter, "_from_s3", lambda key: None)
    training_charter.reset_cache()
    yield
    training_charter.reset_cache()


def _floor() -> float:
    return float(pe.range_low())


def _threshold() -> float:
    return float(training_charter.charter_value("nutrition.protein.feeding_threshold_g"))


# ── the charter read ───────────────────────────────────────────────────────────────────────────────────────────
def test_the_charter_owns_the_protein_block():
    p = training_charter.charter_value("nutrition.protein")
    assert p and {"range_g", "days_of_7", "feedings_per_day", "feeding_threshold_g", "feeding_merge_minutes", "breakfast_nudge"} <= set(p)
    assert p["range_g"]["low"] < p["range_g"]["high"]
    assert p["feedings_per_day"] == 4 and p["feeding_threshold_g"] == 40  # R2's panel default (four feedings of 40 g+)
    assert "pending R2" in p["basis"]
    entry = next(e for e in training_charter.charter_value("change_log") if "#5098" in e.get("by", "") + e.get("what", ""))
    assert entry["version"] == "1.9.0"


def test_the_range_low_and_the_plan_floor_are_one_number():
    """The must-agree pair: the charter's range low, the generated constant and the sealed plan root."""
    with open(os.path.join(_REPO, "config", "user_goals.json"), encoding="utf-8") as f:
        goals = json.load(f)

    def find(node):
        if isinstance(node, dict):
            if "daily_protein_min_g" in node:
                return node["daily_protein_min_g"]
            for v in node.values():
                hit = find(v)
                if hit is not None:
                    return hit
        return None

    assert pe.range_low() == constants.PLAN_DAILY_PROTEIN_MIN_G == find(goals)


def test_owner_redlines_read_the_protein_values_from_the_charter():
    from training import owner_redlines

    r = owner_redlines.REDLINES["protein_floor_g"]
    p = training_charter.charter_value("nutrition.protein")
    assert r["target_g"] == p["range_g"]["high"] and r["days_of_7"] == p["days_of_7"]
    assert r["feedings"] == p["feedings_per_day"] and r["feeding_g"] == p["feeding_target_g"]
    assert r["value"] == p["range_g"]["low"]


# ── ONE hit definition: the two views that disagreed in #5003 now agree ───────────────────────────────────────
def _week():
    f = _floor()
    grams = [f + 3, f - 15, f - 4, f - 18, f - 72, f - 4, f - 37]  # the #5003 shape: two days just under the floor
    return [{"date": f"2026-10-{11 + i:02d}", "total_protein_g": g, "total_calories_kcal": 2000.0} for i, g in enumerate(grams)]


def test_macros_view_and_protein_floor_missed_agree_on_the_5003_week(monkeypatch):
    from mcp import tools_nutrition

    week = _week()
    monkeypatch.setattr(tools_nutrition, "query_source_cross_phase", lambda src, a, b: list(week))
    out = tools_nutrition._get_macro_targets({"start_date": "2026-10-11", "end_date": "2026-10-17", "calorie_target": 2000})
    hits = sum(1 for r in out["daily_breakdown"] if r["hit_protein_target"])
    missed, measured = redline_rate.protein_days_missed([r["total_protein_g"] for r in week])
    assert measured == 7 and hits == 1 and missed == 6, (hits, missed)
    assert hits + missed == measured
    # the day four grams under: a miss in BOTH views (the old 0.95 tolerance called it a hit)
    under = next(r for r in week if r["total_protein_g"] == _floor() - 4)
    assert pe.hit(under["total_protein_g"]) is False
    assert out["adherence"]["protein_target_hit_pct"] == round(100 / 7, 1)


def test_scoring_and_critics_use_the_same_hit():
    from health import nutrition_critics

    f = _floor()
    for g, expect in ((f, True), (f - 4, False), (f + 0.5, True)):
        assert pe.hit(g) is expect
        _, details = scoring_engine.score_nutrition({"macrofactor": {"total_protein_g": g}}, {})
        assert (details["protein_score"] == 100) is expect, (g, details)
    grams = [r["total_protein_g"] for r in _week()]
    packet = nutrition_critics.build_muscle_defense_packet({"protein_g_by_day": grams + grams})
    assert packet["numbers"]["protein_days_missed_7d"] == redline_rate.protein_days_missed(grams)[0] == 6


def test_an_unlogged_day_is_unknown_never_a_miss():
    assert pe.hit(None) is None
    assert redline_rate.protein_days_missed([None, None]) == (None, 0)
    assert pe.evaluate_day(None)["hit"] is None


# ── feedings: unknown vs 0 ──────────────────────────────────────────────────────────────────────────────────────
def _row(*entries, total=None):
    log = [{"time": t, "protein_g": g, "food_name": "x"} if t else {"protein_g": g, "food_name": "x"} for t, g in entries]
    return {"date": DAY, "total_protein_g": total if total is not None else sum(g for _, g in entries), "food_log": log}


def test_feeding_count_is_zero_only_when_timed_rows_exist():
    t = _threshold()
    below = pe.evaluate_day(_row(("08:00", t - 10), ("13:00", t - 1), ("19:00", t - 5)))
    assert below["feedings_40g"] == 0 and len(below["feedings"]) == 3
    untimed = pe.evaluate_day(_row((None, t + 20), (None, t + 30)))
    assert untimed["feedings"] is None and untimed["feedings_40g"] is None
    assert pe.evaluate_day(None)["feedings_40g"] is None
    assert pe.evaluate_day({"date": DAY, "total_protein_g": 150, "food_log": []})["feedings_40g"] is None  # daily-summary export


def test_rows_inside_the_merge_window_are_one_feeding():
    t = _threshold()
    merge = int(training_charter.charter_value("nutrition.protein.feeding_merge_minutes"))
    day = pe.evaluate_day(_row(("07:30", t / 2), (f"07:{30 + merge - 1}" if merge < 30 else "07:59", t / 2), ("12:00", t + 5)))
    assert day["feedings_40g"] == 2 and day["feedings"][0]["time"] == "07:30"
    assert set(day) >= {"total_g", "range_low", "range_high", "hit", "feedings", "feedings_40g", "first_feeding_behind", "charter_version"}
    assert day["charter_version"] == training_charter.charter_version()


# ── the breakfast nudge: behind / not-behind boundary, rails ──────────────────────────────────────────────────
def decide(row, **kw):
    args = dict(date=DAY, now_pt=TICK, row=row, already_sent=False, budget_tier=0)
    args.update(kw)
    return pe.nudge_decide(**args)


def test_boundary_a_threshold_feeding_at_the_cutoff_is_on_track():
    t = _threshold()
    cutoff = training_charter.charter_value("nutrition.protein.breakfast_nudge.cutoff_pt")
    assert decide(_row((cutoff, t)))["reason"] == "on_track"
    v = decide(_row((cutoff, t - 0.1)))
    assert v["send"] and v["reason"] == "behind_logged_below" and str(int(t)) in v["text"]


def test_a_feeding_after_the_cutoff_but_before_the_tick_counts():
    assert decide(_row(("10:05", _threshold() + 5)))["reason"] == "on_track"
    assert decide(_row(("10:30", _threshold() + 5)))["send"]  # logged for later than the tick: not eaten yet


def test_no_same_day_row_withholds_untimed_withholds():
    """The food log is an end-of-day upload: no row at breakfast is the upload's lag, not a missed feeding.
    The nudge withholds (no daily unconditional reminder) — the review's blocking finding on PR #5186."""
    for absent in (None, {}):
        v = decide(absent)
        assert not v["send"] and v["reason"] == "no_same_day_log" and "text" not in v
    assert decide(_row((None, 60)))["reason"] == "feedings_unknown"


def test_a_malformed_total_is_unknown_never_a_crash():
    for bad in ("n/a", "12g", [1]):
        day = pe.evaluate_day({"date": DAY, "total_protein_g": bad, "food_log": []})
        assert day["total_g"] is None and day["hit"] is None


def test_no_charter_merge_rule_means_unknown_feedings(monkeypatch):
    real = pe._cv
    monkeypatch.setattr(pe, "_cv", lambda path, default=None: None if path == "feeding_merge_minutes" else real(path, default))
    assert pe.feedings([{"time": "08:00", "protein_g": 50}]) is None


def test_rails_window_budget_already_sent():
    from coach import coach_nudge_engine

    assert pe.BUDGET_SILENCE_TIER == coach_nudge_engine.BUDGET_SILENCE_TIER
    assert decide(None, budget_tier=2)["reason"] == "budget_tier_2"
    assert decide(None, already_sent=True)["reason"] == "already_sent"
    assert decide(None, now_pt=TICK.replace(hour=9, minute=59))["reason"] == "outside_window"
    assert decide(None, now_pt=TICK.replace(hour=12, minute=0))["reason"] == "outside_window"


# ── the runner: once a day, the claim, the dead-man stamp ─────────────────────────────────────────────────────
class _Table:
    def __init__(self, rows=None):
        self.items = {}
        for r in rows or []:
            self.items[(r["pk"], r["sk"])] = dict(r)

    def get_item(self, Key):
        it = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None):
        k = (Item["pk"], Item["sk"])
        if ConditionExpression and k in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[k] = dict(Item)

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues):
        it = self.items[(Key["pk"], Key["sk"])]
        it["status"], it["text"], it["error"] = (ExpressionAttributeValues[x] for x in (":s", ":t", ":e"))


def _mf(row):
    return {"pk": "USER#matthew#SOURCE#macrofactor", "sk": f"DATE#{DAY}", **row}


def test_runner_sends_at_most_once_a_day_and_stamps_every_tick():
    t, sent = _Table([_mf(_row(("08:15", _threshold() - 5)))]), []
    first = runner.run(t, sent.append, TICK_UTC, 0)
    second = runner.run(t, sent.append, TICK_UTC.replace(minute=40), 0)
    assert first["send"] and first["key"] == f"PROTEIN_NUDGE#{DAY}"
    assert not second["send"] and second["reason"] == "already_sent" and len(sent) == 1
    assert t.items[(runner.LEDGER_PK, f"PROTEIN_NUDGE#{DAY}")]["status"] == "sent"
    assert (runner.LEDGER_PK, f"EVAL#{DAY}") in t.items


def test_runner_racing_claim_never_double_sends():
    t, sent = _Table([{"pk": runner.LEDGER_PK, "sk": f"PROTEIN_NUDGE#{DAY}"}]), []
    assert runner.run(t, sent.append, TICK_UTC, 0)["reason"] == "already_sent" and not sent


def test_runner_on_track_sends_nothing_but_stamps():
    t, sent = _Table([_mf(_row(("08:15", _threshold() + 2)))]), []
    assert runner.run(t, sent.append, TICK_UTC, 0)["reason"] == "on_track" and not sent
    assert t.items[(runner.LEDGER_PK, f"EVAL#{DAY}")]["send"] is False


def test_runner_no_same_day_row_sends_nothing_but_feeds_the_dead_man():
    t, sent = _Table(), []
    assert runner.run(t, sent.append, TICK_UTC, 0)["reason"] == "no_same_day_log" and not sent
    stamp = t.items[(runner.LEDGER_PK, f"EVAL#{DAY}")]
    assert stamp["send"] is False and stamp["reason"] == "no_same_day_log"
    assert (runner.LEDGER_PK, f"PROTEIN_NUDGE#{DAY}") not in t.items


def test_runner_outside_window_touches_nothing():
    t = _Table()
    assert runner.run(t, lambda s: None, TICK_UTC.replace(hour=3), 0)["reason"] == "outside_window" and not t.items


def test_runner_send_failure_is_recorded_not_raised():
    def boom(_):
        raise RuntimeError("ses down")

    t = _Table([_mf(_row(("08:15", _threshold() - 5)))])
    assert runner.run(t, boom, TICK_UTC, 0)["reason"] == "send_failed"
    assert t.items[(runner.LEDGER_PK, f"PROTEIN_NUDGE#{DAY}")]["status"] == "failed"


# ── the dead-man ───────────────────────────────────────────────────────────────────────────────────────────────
class _Check:
    def __init__(self, name, cat, tier):
        self.name, self.ok_msg, self.fail_msg = name, None, None

    def ok(self, m):
        self.ok_msg = m

    def fail(self, m):
        self.fail_msg = m


class _QTable:
    def __init__(self, days):
        self.days = days

    def query(self, **kw):
        return {"Items": [{"sk": f"EVAL#{d}"} for d in self.days]}


def _pt_at():
    return datetime(2026, 10, 23, 9, 0, tzinfo=PACIFIC)


def test_deadman_reds_when_a_completed_day_has_no_eval():
    red = nudge_ledger_qa.check_protein_nudge_liveness(_QTable(["2026-10-22"]), _Check, "t", _pt_at, armed_on="2026-10-20")[0]
    assert red.name == "protein_nudge:eval_liveness" and "2026-10-21" in red.fail_msg and "#5098" in red.fail_msg
    days = ["2026-10-22", "2026-10-21", "2026-10-20"]
    green = nudge_ledger_qa.check_protein_nudge_liveness(_QTable(days), _Check, "t", _pt_at, armed_on="2026-10-20")[0]
    assert green.ok_msg and not green.fail_msg
    pending = nudge_ledger_qa.check_protein_nudge_liveness(_QTable([]), _Check, "t", _pt_at)[0]
    assert pending.ok_msg.startswith("protein nudge pending")
