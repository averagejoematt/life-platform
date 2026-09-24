"""tests/test_weekly_loss_rate_complete_weeks_4150.py — only complete weeks start the overshoot clock.

WHY THIS FILE EXISTS (#4150)

On 2026-09-23 the deficit_advocate packet read `rate_over_cap_consecutive_weeks = 1`. The
week it counted, 09-16..09-22, was clipped by the water-weeks floor (weeks 1-2, through
09-19) to 09-20..09-22 — three weigh-ins (316.92, 315.84, 314.97), a 6.82 lb/wk slope — and
`weekly_loss_rates_from_rows` returned it as a full week. That is one week toward v0.3's
"trend > cap for 2 consecutive weeks" overshoot rule, on three days of provisional evidence.

What these tests hold:

  1. THE SPECIMEN — genesis 2026-09-06, rows 09-20..22 only, end 09-22: no week is counted,
     the clipped week is REPORTED as `partial` (with its provisional rate and n), and the
     deficit_advocate packet counts 0 over-cap weeks (the field reads None — unknown, never
     a number — and no overshoot flag or decision fires).
  2. COMPLETE WEEKS COUNT — seven post-water days with >= MIN_WEEKLY_WEIGHINS weigh-ins.
  3. A THIN WEEK DOES NOT — a full week with 3 weigh-ins is `insufficient_weighins`.
  4. THE WATER RULE IS UNCHANGED — WATER_WEEKS_EXCLUDED is still 2 and a week inside it has
     no rate at all.
  5. CONSECUTIVE MEANS CONSECUTIVE — [over, under] counts 0 (the run starts at the newest).
  6. MUTATION CONTROL — count partial weeks (the pre-#4150 definition) and the specimen reads
     1 over-cap week, so assertion 1 reds.
"""

from __future__ import annotations

import os
import pathlib
import sys
from unittest.mock import patch

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from health import nutrition_critics as nc  # noqa: E402
from training import owner_redlines as rl  # noqa: E402

from mcp import (
    nutrition_critics_inputs as nci,  # noqa: E402
    shared_quantities as sq,  # noqa: E402
)

GENESIS = "2026-09-06"
END = "2026-09-22"
SPECIMEN = [
    {"date": "2026-09-20", "weight_lbs": 316.92},
    {"date": "2026-09-21", "weight_lbs": 315.84},
    {"date": "2026-09-22", "weight_lbs": 314.97},
]


def _packet(rates, weeks_report=None, weeks_since_genesis=3):
    inputs = {
        "weight_lb": 314.97,
        "weight_trend_lb_wk": -6.82,
        "weighin_count": 3,
        "weighin_span_days": 2,
        "rate_provisional": True,
        "weekly_loss_rates_lb_wk": rates,
        "weekly_loss_rate_weeks": weeks_report,
        "weeks_since_genesis": weeks_since_genesis,
        "intake_kcal_by_day": [2100] * 14,
    }
    return nc.build_packets(inputs)["deficit_advocate"]


def _live_inputs(rows):
    with patch.object(sq, "pacific_today", return_value="2026-09-23"), patch.object(sq, "_genesis", return_value=GENESIS):
        return nci.withings_trend(rows, nci.day_keys(END))


# ── 1. the specimen ─────────────────────────────────────────────────────────
def test_the_clipped_post_water_week_is_reported_partial_and_never_counted():
    weeks = sq.weekly_loss_rate_weeks_from_rows(SPECIMEN, END, genesis=GENESIS)
    assert [w["status"] for w in weeks] == ["water", "partial"]
    partial = weeks[-1]
    assert (partial["start"], partial["end"], partial["measured_start"]) == ("2026-09-16", END, "2026-09-20")
    assert partial["days_measured"] == 3 and partial["n_weighins"] == 3 and partial["counted"] is False
    assert partial["rate_lb_wk"] is not None and "never counted" in partial["reason"]
    assert sq.weekly_loss_rates_from_rows(SPECIMEN, END, genesis=GENESIS) is None


def test_the_specimen_packet_counts_zero_over_cap_weeks():
    t = _live_inputs(SPECIMEN)
    assert t["weekly_loss_rates_lb_wk"] is None
    assert [w["status"] for w in t["weekly_loss_rate_weeks"]] == ["water", "partial"]
    p = _packet(t["weekly_loss_rates_lb_wk"], t["weekly_loss_rate_weeks"])
    cap = rl.rate_target_lb_per_wk(314.97)["cap_lb_wk"]
    assert t["weekly_loss_rate_weeks"][-1]["rate_lb_wk"] == 6.82 > cap  # the live 09-23 number, over the cap...
    assert sum(1 for w in t["weekly_loss_rate_weeks"] if w["counted"] and w["rate_lb_wk"] > cap) == 0  # ...and not counted
    # no counted week -> the count is UNKNOWN (None, named in `unknown`), never a number argued from
    assert p["numbers"]["rate_over_cap_consecutive_weeks"] is None and "weekly_loss_rates_lb_wk" in p["unknown"]
    assert not any(f["metric"] == "rate_over_cap_consecutive_weeks" for f in p["flags"])
    assert p["numbers"]["weekly_loss_rate_weeks"][-1]["status"] == "partial"  # reported as such


def test_a_clipped_week_is_partial_even_with_enough_weigh_ins():
    """09-18..09-24 clipped to 09-20..09-24: 5 weigh-ins (>= the minimum), still 5 of 7 days."""
    rows = [{"date": sq.shift_day_key("2026-09-20", i), "weight_lbs": 316.0 - 0.5 * i} for i in range(5)]
    (w,) = sq.weekly_loss_rate_weeks_from_rows(rows, "2026-09-24", weeks=1, genesis=GENESIS)
    assert w["n_weighins"] == 5 >= sq.MIN_WEEKLY_WEIGHINS
    assert w["status"] == "partial" and w["days_measured"] == 5 and not w["counted"]


# ── 2 / 3. complete vs thin weeks ───────────────────────────────────────────
def _daily(start, n, first=316.0, step=0.5, skip=()):
    rows = []
    for i in range(n):
        d = sq.shift_day_key(start, i)
        if d not in skip:
            rows.append({"date": d, "weight_lbs": first - step * i})
    return rows


def test_a_complete_post_water_week_with_enough_weigh_ins_is_counted():
    rows = _daily("2026-09-20", 14)  # 09-20..10-03
    weeks = sq.weekly_loss_rate_weeks_from_rows(rows, "2026-10-03", genesis=GENESIS)
    assert [w["status"] for w in weeks] == ["complete", "complete"]
    assert sq.weekly_loss_rates_from_rows(rows, "2026-10-03", genesis=GENESIS) == [3.5, 3.5]


def test_a_full_week_under_the_minimum_weigh_ins_is_not_counted():
    assert sq.MIN_WEEKLY_WEIGHINS == 4 and "ADR-105" in sq.MIN_WEEKLY_WEIGHINS_PROVENANCE
    rows = _daily("2026-09-27", 7, skip=("2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01"))  # 3 weigh-ins
    (w,) = sq.weekly_loss_rate_weeks_from_rows(rows, "2026-10-03", weeks=1, genesis=GENESIS)
    assert w["status"] == "insufficient_weighins" and w["n_weighins"] == 3 and not w["counted"]
    rows4 = _daily("2026-09-27", 7, skip=("2026-09-28", "2026-09-29", "2026-09-30"))
    (w4,) = sq.weekly_loss_rate_weeks_from_rows(rows4, "2026-10-03", weeks=1, genesis=GENESIS)
    assert w4["status"] == "complete" and w4["counted"]


# ── 4. the water rule stays ─────────────────────────────────────────────────
def test_the_water_weeks_exclusion_is_unchanged():
    assert sq.WATER_WEEKS_EXCLUDED == 2
    r = sq.loss_rate_from_rows(SPECIMEN, END, genesis=GENESIS)
    assert r["water_weeks_excluded_through"] == "2026-09-19" and r["window"]["start"] == "2026-09-20"


# ── 5. consecutive ─────────────────────────────────────────────────────────
def test_consecutive_counts_back_from_the_newest_counted_week():
    cap = rl.rate_target_lb_per_wk(314.97)["cap_lb_wk"]
    assert _packet([cap + 1, cap - 1])["numbers"]["rate_over_cap_consecutive_weeks"] == 0
    assert _packet([cap - 1, cap + 1])["numbers"]["rate_over_cap_consecutive_weeks"] == 1
    assert _packet([cap + 1, cap + 1])["numbers"]["rate_over_cap_consecutive_weeks"] == 2


# ── 6. mutation control ─────────────────────────────────────────────────────
def test_mutation_control_counting_partial_weeks_reds_the_specimen():
    def _pre_4150(rows, end, *, weeks=2, genesis=None):
        rated = [w["rate_lb_wk"] for w in sq.weekly_loss_rate_weeks_from_rows(rows, end, weeks=weeks, genesis=genesis)]
        return [r for r in rated if r is not None] or None

    with patch.object(sq, "weekly_loss_rates_from_rows", _pre_4150):
        t = _live_inputs(SPECIMEN)
    assert t["weekly_loss_rates_lb_wk"] and t["weekly_loss_rates_lb_wk"][0] > 6
    p = _packet(t["weekly_loss_rates_lb_wk"], t["weekly_loss_rate_weeks"])
    assert p["numbers"]["rate_over_cap_consecutive_weeks"] == 1
