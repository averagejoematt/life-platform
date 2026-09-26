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
from datetime import datetime, timezone
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


class _FrozenDatetime(datetime):
    """Pinned to `FROZEN_UTC`, correctly converting for ANY requested tzinfo (PT
    included) — the daily-metrics side calls `datetime.now(timezone.utc)`, the
    journey side calls `datetime.now(PT)`; both must read the one instant."""

    @classmethod
    def now(cls, tz=None):
        return FROZEN_UTC.astimezone(tz) if tz else FROZEN_UTC.replace(tzinfo=None)


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
    return [{"pk": pk, "sk": f"DATE#{d}", "weight_lbs": Decimal(str(w))} for d, w in _WITHINGS_ROWS]


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
    data, _, _ = dmc.assemble_data(YESTERDAY, {"goal_weight_lbs": GOAL_WEIGHT})
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
