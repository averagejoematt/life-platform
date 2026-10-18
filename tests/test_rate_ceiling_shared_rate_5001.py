"""tests/test_rate_ceiling_shared_rate_5001.py — one stated loss rate, and `rate_ceiling` evaluated over it (#5001).

THE SPECIMEN (owner's live MCP session, 2026-10-18; brief §A3)

  * `plan_next_session` stage 2 carried `current_rate_lb_wk: 4.12` beside the schedule step above
    295 lb (`cap: 4.0`); the rate-advocate critic approved, its sentence saying the rate was "within
    bounds"; `rate_ceiling` and `rate_overshoot` both sat in `unevaluated_tripwires`.
  * `get_nutrition` printed `calorie_target_check.weight_trend_lb_per_wk: -4.38` over 14 days.

THE WIRE — `WITHINGS` below is a field-projected copy of the live `USER#matthew#SOURCE#withings`
DATE# rows 2026-10-03..2026-10-17, read 2026-10-18 (read-only query; there is NO row for 10-11).
Replayed through the platform's own code:

  4.12   = `shared_quantities.loss_rate_from_rows` over 10-04..10-17 (13 weigh-ins, least-squares) —
           the plan's number, from the partition, every date a real row;
  -4.375 = `health.tdee.weight_trend_lb_per_wk` over 10-03..10-17 (first-vs-last endpoint) — the
           -4.38 get_nutrition printed: the TDEE back-solve's input, a different quantity.

Every clock is pinned (#4848): dates and `today` are passed in, never read off the wall.
EACH TEST NAMES THE MUTATION THAT REDS IT.
"""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from coach import critics  # noqa: E402
from health import tdee  # noqa: E402
from training import owner_redlines, plan_engine, redline_rate  # noqa: E402

from mcp import shared_quantities as sq  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
GENESIS = "2026-09-06"
TODAY = "2026-10-18"
WEIGHT_LB = 302.22  # the 10-17 weigh-in — the schedule step above 295 lb, cap 4.0

_LIVE = {
    "2026-10-03": 310.97,
    "2026-10-04": 312.11,
    "2026-10-05": 311.09,
    "2026-10-06": 308.87,
    "2026-10-07": 308.31,
    "2026-10-08": 307.18,
    "2026-10-09": 306.13,
    "2026-10-10": 306.52,
    # 2026-10-11: no row in the partition
    "2026-10-12": 308.29,
    "2026-10-13": 305.4,
    "2026-10-14": 305.56,
    "2026-10-15": 304.46,
    "2026-10-16": 304.03,
    "2026-10-17": 302.22,
}
WITHINGS = [
    {"pk": "USER#matthew#SOURCE#withings", "sk": f"DATE#{d}", "date": d, "weight_lbs": w, "phase": "experiment"} for d, w in _LIVE.items()
]


def _quantity(rows=None, end="2026-10-17"):
    return sq.loss_rate_quantity_from_rows(WITHINGS if rows is None else rows, end, genesis=GENESIS)


def _block(loss_rate, weight=WEIGHT_LB):
    return plan_engine.constraint_block(date=TODAY, weight_lb=weight, loss_rate=loss_rate)


def _row(block):
    return next(t for t in block["tripwires"] if t["id"] == "rate_ceiling")


def _advocate(block, rate=None, provisional=False):
    q = block["shared_quantities"]["loss_rate_lb_wk"] or {}
    return critics.build_rate_advocate_packet(
        {"total_sets": 20},
        tripwires=block["tripwires"],
        walking=block["walking"],
        rate_target=block["rate_target"],
        current_rate_lb_wk=q.get("value") if rate is None else rate,
        rate_provisional=provisional,
        lifting_sessions_7d=2,
    )


def _model(verdict, metric, sentence):
    def invoke(_body):
        text = json.dumps({"verdict": verdict, "metric": metric, "value": None, "field": None, "to": None, "sentence": sentence})
        return {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}

    return invoke


# ── 1. reproduce ─────────────────────────────────────────────────────────────────────
def test_both_live_figures_replay_from_the_withings_partition():
    """4.12 is the shared least-squares rate over 10-04..10-17; -4.38 is the TDEE endpoint over 10-03..10-17."""
    q = _quantity()
    assert q["value"] == 4.12 and q["provisional"] is False
    assert q["window"] == {"start": "2026-10-04", "end": "2026-10-17"} and q["window_days"] == 14
    assert q["n_weigh_ins"] == 13 and q["source"] == "withings" and q["method"] == sq.LOSS_RATE_METHOD
    endpoint, span = tdee.weight_trend_lb_per_wk([r for r in WITHINGS if "2026-10-03" <= r["date"] <= "2026-10-17"])
    assert round(endpoint, 2) == -4.38 and span == 14


def test_the_quantity_lists_the_partition_rows_it_read_and_the_day_it_could_not():
    """The brief's validation rule: the rate's evidence is the partition's own DATE# rows. Mutation control:
    interpolate a 10-11 weigh-in into the series — `days_without_a_weigh_in` empties and this reds."""
    v = _quantity()["validation"]
    assert v["partition"] == "USER#matthew#SOURCE#withings"
    assert [w["date"] for w in v["weigh_ins"]] == [d for d in _LIVE if d >= "2026-10-04"]
    assert v["days_without_a_weigh_in"] == ["2026-10-11"]
    assert _quantity()["window_provenance"].startswith("owner")


# ── 2. rate_ceiling is evaluated ─────────────────────────────────────────────────────
def test_rate_ceiling_is_evaluated_and_trips_at_4_12_above_295():
    """Mutation control: put `evaluated_by_engine: False` back on `rate_ceiling` — the row vanishes."""
    assert "rate_ceiling" not in owner_redlines.unevaluated_tripwires()
    block = _block(_quantity())
    assert "rate_ceiling" not in block["unevaluated_tripwires"]
    row = _row(block)
    assert row["state"] == "tripped" and row["observed"] == 4.12
    ev = row["evidence"]
    assert ev["threshold_lb_wk"] == 4.0 and ev["band_cap_lb_wk"] == 4.0 and ev["band_above_lb"] == 295
    assert ev["threshold_provenance"].startswith("owner")
    assert "rate_ceiling" in block["tripped"]
    assert block["shared_quantities"]["loss_rate_lb_wk"]["value"] == 4.12


def test_the_threshold_is_the_band_cap_and_never_looser_than_the_absolute_ceiling():
    """At 280 lb the step cap is 3.75: 3.8 trips, 3.7 is clear. Mutation control: compare against the
    tripwire's absolute 4.0 instead of the band cap — 3.8 reads clear and this reds."""

    def at(value, weight):
        return redline_rate.rate_ceiling_check({"value": value, "provisional": False, "experiment_week": 7}, weight)

    assert at(3.8, 280.0)["state"] == "tripped" and at(3.8, 280.0)["threshold_lb_wk"] == 3.75
    assert at(3.7, 280.0)["state"] == "clear"
    assert at(4.01, None)["state"] == "tripped" and at(4.01, None)["threshold_lb_wk"] == 4.0
    for w in (330.0, 300.0, 280.0, 262.0, 241.0, 221.0, 211.0, 206.0, 199.0):
        assert at(0.0, w)["threshold_lb_wk"] <= 4.0, w


def test_an_unreadable_provisional_or_early_rate_is_never_clear():
    absent = _row(_block(None))
    assert absent["state"] == "unknown"
    two_points = _quantity([r for r in WITHINGS if r["date"] in ("2026-10-16", "2026-10-17")])
    prov = _row(_block(two_points))
    assert prov["state"] == "unknown" and prov["evidence"]["state_if_firm"] == "tripped"
    early = redline_rate.rate_ceiling_check({"value": 6.0, "provisional": False, "experiment_week": 3}, WEIGHT_LB)
    assert early["state"] == "not_yet_active" and early["state_if_active"] == "tripped"


# ── 3. the acceptance fixture ────────────────────────────────────────────────────────
def test_a_14_day_trend_of_4_12_above_295_is_a_rate_advocate_change_naming_rate_ceiling():
    """THE #5001 acceptance. Mutation control: drop `_rate_ceiling_flag(tw, flags)` from the advocate —
    the deterministic verdict is approve and this reds."""
    packet = _advocate(_block(_quantity()))
    assert packet["numbers"]["rate_ceiling"] == "tripped"
    v = critics.deterministic_verdict(packet)
    assert v["verdict"] == "change" and v["metric"] == "rate_ceiling"
    assert "`rate_ceiling` TRIPPED" in v["reason"] and "NOT within bounds" in v["reason"] and "4.12" in v["reason"]


def test_a_model_saying_within_bounds_can_neither_approve_nor_speak_for_the_verdict():
    """The live failure, replayed: the model approves with "within bounds". The floor holds AND the model's
    sentence stays on `model`. Mutation control: restore `out["sentence"] = model["sentence"]` ahead of the
    rank check in `reconcile` — the change verdict carries "within bounds" and this reds."""
    block = _block(_quantity())
    packets = {cid: {"critic": cid, "numbers": {}, "flags": [], "unknown": [], "violations": []} for cid in critics.CRITIC_IDS}
    packets["rate_advocate"] = _advocate(block)
    said = "The 4.12 lb/wk loss rate is within bounds for the schedule."
    vs = critics.run_critics(packets, {"total_sets": 20, "exercises": []}, invoke=_model("approve", None, said), model_allowed=True)
    v = next(x for x in vs if x["critic"] == "rate_advocate")
    assert v["verdict"] == "change" and v["metric"] == "rate_ceiling"
    assert said not in (v.get("sentence") or "") and said not in v["reason"] and "NOT within bounds" in v["reason"]
    assert v["model"]["sentence"] == said and v["model_overruled"]


def test_a_model_veto_on_rate_ceiling_stays_a_change():
    """`governed`: the advocate is not a gate. Mutation control: drop `governed=True` — this becomes a veto."""
    block = _block(_quantity())
    packets = {cid: {"critic": cid, "numbers": {}, "flags": [], "unknown": [], "violations": []} for cid in critics.CRITIC_IDS}
    packets["rate_advocate"] = _advocate(block)
    vs = critics.run_critics(
        packets, {"total_sets": 20, "exercises": []}, invoke=_model("veto", "rate_ceiling", "Veto."), model_allowed=True
    )
    assert next(x for x in vs if x["critic"] == "rate_advocate")["verdict"] == "change"


def test_a_clear_rate_ceiling_adds_no_objection():
    """Negative control: 3.2 lb/wk above 295 is under the cap — no change on rate_ceiling."""
    rows = [{"date": r["date"], "weight_lbs": 312.0 - 3.2 / 7 * i} for i, r in enumerate(WITHINGS)]
    packet = _advocate(_block(_quantity(rows)))
    assert packet["numbers"]["rate_ceiling"] == "clear"
    assert not [f for f in packet["flags"] if f["metric"] == "rate_ceiling"]


# ── 4. one quantity, two tools ───────────────────────────────────────────────────────
def test_the_plan_and_get_nutrition_read_one_stated_quantity():
    """Both readers return the same dict for the same body on the same day. Mutation control: have
    `_shared_loss_rate` compute its own rate — the two dicts differ and this reds."""
    from mcp import tools_nutrition

    def read(source, start, end):
        assert source == "withings"
        return [r for r in WITHINGS if start <= r["date"] <= end]

    with patch.object(sq, "_genesis", return_value=GENESIS):
        plan = sq.loss_rate_lb_wk(TODAY, today=TODAY, read=read)
        with patch.object(sq, "pacific_today", return_value=TODAY), patch.object(sq._core, "query_source", side_effect=read):
            nutrition = tools_nutrition._shared_loss_rate("2026-10-17")
    assert plan == nutrition and plan["value"] == 4.12 and plan["experiment_week"] == 6
    labelled = tools_nutrition._labelled_trend_check({"weight_trend_lb_per_wk": -4.38})
    assert "NOT the loss rate" in labelled["weight_trend_is_not_the_loss_rate"]


def _references(path: str, fn: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == fn)
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def test_every_reader_of_the_rate_reaches_the_shared_quantity():
    """Mutation control: point any one site at its own derivation — the offender is named."""
    sites = {
        ("mcp/tools_plan.py", "tool_plan_next_session"): "loss_rate_lb_wk",  # stage 1 reads it
        ("mcp/tools_plan.py", "_run_stage_2"): "_block_rate",  # the advocate's rate IS the block's quantity
        ("mcp/tools_nutrition.py", "_get_macro_targets"): "_shared_loss_rate",  # get_nutrition view=macros
        ("mcp/tools_nutrition.py", "_shared_loss_rate"): "loss_rate_lb_wk",
        ("lambdas/training/plan_engine.py", "_tripwire_states"): "rate_ceiling_check",
        ("lambdas/coach/critics.py", "build_rate_advocate_packet"): "_rate_ceiling_flag",
    }
    offenders = [f"{p}::{fn} no longer reads {need}" for (p, fn), need in sites.items() if need not in _references(p, fn)]
    assert offenders == []
