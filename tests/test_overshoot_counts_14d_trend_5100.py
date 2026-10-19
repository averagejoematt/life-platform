"""tests/test_overshoot_counts_14d_trend_5100.py — the overshoot rule counts the 14-day trend (#5100).

The `rate_overshoot` redline reads "14-day weight trend rate above the schedule's cap for 2
consecutive weeks", but the weekly list the critics counted was each week's OWN 7-day slope, which
runs far above the 14-day trend on a sawtooth week (weekend rebound). The weekly list now carries
the 14-day least-squares trend at each weekly checkpoint (`shared_quantities.weekly_loss_rate_weeks_from_rows`
— ONE helper; the deficit advocate's flag and the plan-side decision both read it).

Series are SYNTHETIC (no real weights): a steady drift plus a within-week sawtooth.
"""

from __future__ import annotations

import os
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from health import nutrition_critics as nc  # noqa: E402
from training import owner_redlines as rl  # noqa: E402

from mcp import shared_quantities as sq  # noqa: E402

GENESIS = "2026-09-06"
END = "2026-10-13"
SYN_WEIGHT = 300.0


def _series(drift, saw, n=24):
    return [{"date": sq.shift_day_key("2026-09-20", i), "weight_lbs": SYN_WEIGHT - drift * i + saw * ((i % 7) - 3)} for i in range(n)]


def _packet(rows):
    weeks = sq.weekly_loss_rate_weeks_from_rows(rows, END, genesis=GENESIS)
    rates = sq.weekly_loss_rates_from_rows(rows, END, genesis=GENESIS)
    inputs = {
        "weight_lb": SYN_WEIGHT,
        "weight_trend_lb_wk": -(sq.loss_rate_from_rows(rows, END, genesis=GENESIS)["rate_lb_wk"]),
        "weighin_count": 14,
        "weighin_span_days": 13,
        "rate_provisional": False,
        "weekly_loss_rates_lb_wk": rates,
        "weekly_loss_rate_weeks": weeks,
        "weeks_since_genesis": 6,
        "intake_kcal_by_day": [2100] * 14,
    }
    return nc.build_packets(inputs), weeks, rates, inputs


def _cap():
    return rl.rate_target_lb_per_wk(SYN_WEIGHT)["cap_lb_wk"]


def test_checkpoint_rates_are_the_14_day_trend_not_the_7_day_slope():
    rows = _series(0.4, 1.0)
    _, weeks, rates, _ = _packet(rows)
    slope7 = [sq.loss_rate_from_rows(rows, e, window_days=7, genesis=GENESIS)["rate_lb_wk"] for e in ("2026-10-06", END)]
    trend14 = [sq.loss_rate_from_rows(rows, e, genesis=GENESIS)["rate_lb_wk"] for e in ("2026-10-06", END)]
    assert rates == trend14 and all(s > t + 2 for s, t in zip(slope7, trend14)), (slope7, trend14)
    assert all(w["counted"] and w["trend_window"]["days"] == 14 for w in weeks)


def test_the_critic_quotes_the_14_day_checkpoint_trends_and_the_plan_side_agrees():
    rows = _series(0.4, 1.0)
    packets, _, rates, inputs = _packet(rows)
    cap = _cap()
    assert all(cap < r < cap + 1 for r in rates)  # just above the cap, while the 7-day slopes sit far above
    adv = packets["deficit_advocate"]
    (flag,) = [f for f in adv["flags"] if f["metric"] == "rate_over_cap_consecutive_weeks"]
    quoted = [float(x) for x in re.search(r"\(([\d., ]+)\)", flag["reason"]).group(1).split(",")]
    assert quoted == rates
    assert adv["numbers"]["rate_over_cap_consecutive_weeks"] == 2
    decisions = nc.decisions_offered([], inputs, already_logged=[])
    (over,) = [d for d in decisions if d["trigger"]["id"] == "rate_overshoot" and d["state"] == "pending"]
    assert over["trigger"]["values"]["weekly_loss_rates_lb_wk"] == rates  # the plan-side copy quotes the same figures


def test_negative_control_trend_under_cap_with_noisy_weekly_slopes_does_not_fire():
    rows = _series(0.2, 1.5)
    packets, _, rates, _ = _packet(rows)
    cap = _cap()
    slope7 = sq.loss_rate_from_rows(rows, END, window_days=7, genesis=GENESIS)["rate_lb_wk"]
    assert slope7 > cap > max(rates)  # each week alone would have tripped the old rule
    assert packets["deficit_advocate"]["numbers"]["rate_over_cap_consecutive_weeks"] == 0
    assert not [f for f in packets["deficit_advocate"]["flags"] if f["metric"] == "rate_over_cap_consecutive_weeks"]


def test_a_thin_window_is_unknown_never_a_pass():
    rows = [r for i, r in enumerate(_series(0.4, 1.0)) if i % 7 in (0, 1)]  # 2 weigh-ins a week
    weeks = sq.weekly_loss_rate_weeks_from_rows(rows, END, genesis=GENESIS)
    assert not any(w["counted"] for w in weeks)
    assert sq.weekly_loss_rates_from_rows(rows, END, genesis=GENESIS) is None


def test_no_critic_module_reads_the_endpoint_trend():
    """`tdee.weight_trend_lb_per_wk` stays for the calorie-model sanity check only."""
    for rel in ("lambdas/health/nutrition_critics.py", "mcp/nutrition_critics_inputs.py", "mcp/shared_quantities.py"):
        src = (REPO / rel).read_text()
        code = "\n".join(ln for ln in src.splitlines() if not ln.lstrip().startswith("#"))
        assert not re.search(r"\.weight_trend_lb_per_wk\(|import[^\n]*weight_trend_lb_per_wk", code), rel
