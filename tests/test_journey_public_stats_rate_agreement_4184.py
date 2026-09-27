"""tests/test_journey_public_stats_rate_agreement_4184.py — #4184 contract: the two
computations of the ONE weight-trajectory RATE — `/api/journey` (`web.site_api_journey`)
and the daily-metrics-compute Lambda whose `weight_traj` feeds `public_stats.json` —
must agree, given the same raw `withings` series.

**Why this is a plain contract test, not a `tests/pair_contract_registry.py` entry.**
That registry's harness (`tests/pair_contract.py`) tests a PRODUCER-EMITS-FIELD /
CONSUMER-READS-FIELD relationship: `register()` requires at least one `Mutation` that
must (a) exist at a real path in the producer's actual output and (b) change the real
consumer's answer when perturbed. This pair isn't that shape — `/api/journey` never
reads daily-metrics-compute's output at all. Both call sites independently re-derive
the SAME rate from the SAME raw `withings` rows through the ONE shared
`health.weight_trend.weight_trajectory`. There is no payload field to mutate; the
invariant is equality between two independent computations over one input series —
exactly the "plain contract test" #4184's acceptance criteria names as acceptable when
the full PairContract shape is out of proportion.

Both sides are frozen to the SAME Pacific instant (`FROZEN_UTC`) and read the SAME
seeded `withings` rows (pre- and post-genesis), so a producer/consumer disagreement on
`weekly_rate_lbs`, either CI bound, `rate_provisional` or `projected_goal_date` reds
this test rather than shipping to two surfaces silently, which is exactly how #4184 was
found live (`/api/journey` -4.58 provisional vs `public_stats.json` -4.36 firm).
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import compute.daily_metrics_compute_lambda as dmc  # noqa: E402
from health import weight_trend  # noqa: E402 — the ONE shared computation both sides call
from pacific_clock import freeze_pacific  # noqa: E402 — #2811: pin the PT clock each module actually calls
from web import site_api_common as common, site_api_vitals as vitals  # noqa: E402

GENESIS = "2026-04-20"
FROZEN_UTC = datetime(2026, 5, 5, 17, 40, 0, tzinfo=timezone.utc)
TODAY = "2026-05-05"
YESTERDAY = "2026-05-04"
GOAL_WEIGHT = 185.0

# One withings series, fed identically to both sides. The 2026-04-14 row is INSIDE the
# old flat 28-day fetch (today - 28d = 2026-04-07) but before genesis — the exact row
# #4184's clamp exists to keep out of the rate.
_WITHINGS_ROWS = [
    ("2026-04-14", 210.0),  # pre-genesis
    ("2026-04-21", 200.0),
    ("2026-04-28", 195.0),
    ("2026-05-01", 192.0),
    (YESTERDAY, 190.0),
]


_SCENARIO = {"now": FROZEN_UTC, "rows": _WITHINGS_ROWS}


class _FrozenDatetime(datetime):
    """Pinned to `FROZEN_UTC`, correctly converting for ANY requested tzinfo (PT
    included) — the daily-metrics side calls `datetime.now(timezone.utc)`, the
    journey side calls `datetime.now(PT)`; both must read the one instant."""

    @classmethod
    def now(cls, tz=None):
        now = _SCENARIO["now"]
        return now.astimezone(tz) if tz else now.replace(tzinfo=None)


def _pk_and_range(cond):
    """(pk, sk_lo, sk_hi) out of a boto3 KeyConditionExpression (`_query_source`'s shape)."""
    pk = lo = hi = None
    stack = [cond]
    while stack:
        expr = stack.pop().get_expression()
        op, values = expr["operator"], expr["values"]
        if op == "AND":
            stack.extend(values)
        elif op == "=" and getattr(values[0], "name", None) == "pk":
            pk = values[1]
        elif op == "BETWEEN" and getattr(values[0], "name", None) == "sk":
            lo, hi = values[1], values[2]
    return pk, lo, hi


class _SharedFixtureTable:
    """One fake table honouring BOTH query shapes in play: `_query_source`'s boto3
    `Key(...).between(...)` (site_api_common) and `fetch_range`'s raw
    `ExpressionAttributeValues` dict (daily_metrics_compute_lambda). Withings is
    RAW_TIMESERIES on both sides (cross-phase), so no FilterExpression is ever engaged
    and these rows carry no `phase` attribute."""

    def __init__(self, rows):
        self.rows = rows  # list of {"pk": ..., "sk": ..., "weight_lbs": ...}

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        if cond is not None and hasattr(cond, "get_expression"):
            pk, lo, hi = _pk_and_range(cond)
        else:
            vals = kwargs.get("ExpressionAttributeValues", {})
            pk, lo, hi = vals.get(":pk"), vals.get(":s"), vals.get(":e")
        items = [r for r in self.rows if r["pk"] == pk and (lo is None or lo <= r["sk"] <= hi)]
        return {"Items": sorted(items, key=lambda r: r["sk"])}

    def get_item(self, Key=None, **_kw):
        for r in self.rows:
            if r["pk"] == Key["pk"] and r["sk"] == Key["sk"]:
                return {"Item": r}
        return {}


def _rows(source):
    pk = f"USER#matthew#SOURCE#{source}"
    return [{"pk": pk, "sk": f"DATE#{d}", "weight_lbs": Decimal(str(w))} for d, w in _SCENARIO["rows"]]


def _wire_common(monkeypatch, table):
    monkeypatch.setattr(common, "table", table)
    monkeypatch.setattr(common, "EXPERIMENT_START", GENESIS)
    monkeypatch.setattr(vitals, "EXPERIMENT_START", GENESIS)
    monkeypatch.setattr(vitals, "datetime", _FrozenDatetime)
    monkeypatch.setattr(common, "_get_profile", lambda: {"goal_weight_lbs": GOAL_WEIGHT})
    monkeypatch.setattr(vitals, "_get_profile", lambda: {"goal_weight_lbs": GOAL_WEIGHT})
    freeze_pacific(monkeypatch, weight_trend, _FrozenDatetime)  # journey() calls weight_trajectory() with no ref_dt


def _journey_traj(monkeypatch):
    table = _SharedFixtureTable(_rows("withings"))
    _wire_common(monkeypatch, table)
    body = json.loads(vitals.handle_journey()["body"])["journey"]
    return {
        "weekly_rate_lbs": body["weekly_rate_lbs"],
        "weekly_rate_ci_low": body["weekly_rate_ci_low"],
        "weekly_rate_ci_high": body["weekly_rate_ci_high"],
        "rate_provisional": body["rate_provisional"],
        "projected_goal_date": body["projected_goal_date"],
    }


def _daily_metrics_traj(monkeypatch):
    table = _SharedFixtureTable(_rows("withings"))
    monkeypatch.setattr(dmc, "table", table)
    monkeypatch.setattr(dmc, "datetime", _FrozenDatetime)
    monkeypatch.setattr(dmc, "EXPERIMENT_START_DATE", GENESIS)
    freeze_pacific(monkeypatch, dmc, _FrozenDatetime)
    yesterday = (_SCENARIO["now"].date() - timedelta(days=1)).isoformat()
    data, _, _ = dmc.assemble_data(yesterday, {"goal_weight_lbs": GOAL_WEIGHT})
    traj = data["weight_traj"]
    return {
        "weekly_rate_lbs": traj["weekly_rate_lbs"],
        "weekly_rate_ci_low": traj["weekly_rate_ci_low"],
        "weekly_rate_ci_high": traj["weekly_rate_ci_high"],
        "rate_provisional": traj["rate_provisional"],
        "projected_goal_date": traj["projected_goal_date"],
    }


def test_journey_and_daily_metrics_compute_agree_on_the_one_rate(monkeypatch):
    journey_out = _journey_traj(monkeypatch)
    dmc_out = _daily_metrics_traj(monkeypatch)

    assert journey_out == dmc_out, (
        "the two producers of ONE weight-trajectory rate disagree on the same input series "
        f"— /api/journey={journey_out!r} vs daily-metrics-compute={dmc_out!r}"
    )
    # a positive control: prove the assertion isn't vacuously true over an empty/degenerate
    # trajectory (that would pass by both sides returning all-None).
    assert dmc_out["rate_provisional"] is True
    assert dmc_out["weekly_rate_lbs"] != 0.0


# ── #4184's tail: the window must END where /api/journey's does (TODAY) ─────────────
# PR #4193 clamped the START to the genesis, and the 2026-09-27 16:40Z run proved it
# (computed_metrics: -4.36, CI [-4.74, -2.75], provisional) — yet /api/journey served
# -4.04, CI [-4.55, -2.29], FIRM, goal 2027-05-09, because the compute window still
# ENDED YESTERDAY: the 09-27 morning weigh-in took the API's span to 21 days (over the
# floor) while the compute side stopped at 20. The fixture above never had a weigh-in
# ON today, so it could not see this. This one reproduces the live shape: genesis + 21 d.
_CROSSING_NOW = datetime(2026, 5, 11, 16, 40, 0, tzinfo=timezone.utc)  # 09:40 PT — the compute's slot
_CROSSING_ROWS = [
    ("2026-04-14", 210.0),  # pre-genesis — still excluded
    ("2026-04-20", 201.0),  # ON genesis
    ("2026-04-25", 198.0),
    ("2026-05-01", 195.5),
    ("2026-05-06", 193.0),
    ("2026-05-10", 191.5),  # yesterday — where the old window stopped (span 20, provisional)
    ("2026-05-11", 191.8),  # TODAY's weigh-in — span 21, firm
]


def test_a_weighin_on_today_that_crosses_the_floor_agrees_on_both_sides(monkeypatch):
    monkeypatch.setitem(_SCENARIO, "now", _CROSSING_NOW)
    monkeypatch.setitem(_SCENARIO, "rows", _CROSSING_ROWS)
    journey_out = _journey_traj(monkeypatch)
    dmc_out = _daily_metrics_traj(monkeypatch)
    assert journey_out == dmc_out, (
        "the compute window must end TODAY, as /api/journey's does " f"— /api/journey={journey_out!r} vs daily-metrics-compute={dmc_out!r}"
    )
    # positive control: this scenario IS the firm side of the floor, with a dated goal —
    # so equality here is not two sides agreeing on "provisional, no date".
    assert dmc_out["rate_provisional"] is False
    assert dmc_out["projected_goal_date"] is not None


def test_mutation_control_a_yesterday_ended_window_disagrees(monkeypatch):
    """The control for the test above: the SAME rows fed through the shared computation
    with the window ending YESTERDAY (the pre-fix compute shape) must disagree with what
    /api/journey serves — provisional flips, the goal date vanishes. If the fix is ever
    reverted, the test above goes red exactly this way."""
    monkeypatch.setitem(_SCENARIO, "now", _CROSSING_NOW)
    monkeypatch.setitem(_SCENARIO, "rows", _CROSSING_ROWS)
    journey_out = _journey_traj(monkeypatch)
    yesterday_ended = [(d, w) for d, w in _CROSSING_ROWS if GENESIS <= d <= "2026-05-10"]
    stale = weight_trend.weight_trajectory(yesterday_ended, yesterday_ended[-1][1], GOAL_WEIGHT, ref_dt=_CROSSING_NOW)
    assert stale["rate_provisional"] is True and journey_out["rate_provisional"] is False
    assert stale["projected_goal_date"] is None and journey_out["projected_goal_date"] is not None


def test_the_window_is_genesis_clamped_and_ends_today():
    assert weight_trend.experiment_rate_window("2026-05-11", GENESIS) == (GENESIS, "2026-05-11")
    assert weight_trend.experiment_rate_window("2026-06-30", GENESIS) == ("2026-06-02", "2026-06-30")
