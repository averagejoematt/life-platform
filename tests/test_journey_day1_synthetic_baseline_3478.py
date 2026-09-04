"""tests/test_journey_day1_synthetic_baseline_3478.py — Day 1 never reports a
weigh-in that did not happen (#3478).

`/api/journey`'s last-resort fallback mints ``(EXPERIMENT_START,
EXPERIMENT_BASELINE_WEIGHT_LBS)`` — a CONSTANT — and nothing downstream can tell
it apart from a reading. On Day 1 of a cycle, before the first weigh-in lands,
both real paths come up empty by construction:

  * the Withings window starts AT genesis, so it is one day wide and has no rows;
  * the G-4 ``_latest_item`` fallback cannot see the pre-genesis row either — the
    reset re-phases it to ``pilot``, which ADR-058 hides by default.

so the constant was served as measured: ``last_weighin_date`` = the genesis date,
``weighin_count`` = 1. That is the ghost #948 removed from the pre-start countdown
one day earlier, and ADR-104 gives it the same answer — an absence is reported as
absent.

**The fixture is the wire** (reference_fixture_must_be_the_wire): the table stub
below runs the REAL ``_query_source`` / ``_latest_item`` / ``with_phase_filter``,
honouring the sk range, the phase FilterExpression, and DynamoDB's Limit-BEFORE-
filter ordering — which is the exact reason ``_latest_item`` returns nothing when
the newest row is ``phase=pilot``. Stubbing those helpers out instead would hide
the mechanism this test exists to pin.

Genesis is derived from the real now(PT), so there is no wall-clock time bomb.
"""

import ast
import json
import os
import pathlib
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from web import (  # noqa: E402
    site_api_common as common,
    site_api_intelligence as intel,
    site_api_journey as journey_mod,
    site_api_vitals as vitals,
)

BASELINE = 324.6  # the cycle-16 shape: the genesis constant and the last real reading agree


def _today_pt():
    return datetime.now(common.PT).date()


def _iso(d):
    return d.strftime("%Y-%m-%d")


def _set_genesis(monkeypatch, iso):
    for mod in (common, vitals, intel, journey_mod):
        if hasattr(mod, "EXPERIMENT_START"):
            monkeypatch.setattr(mod, "EXPERIMENT_START", iso)


def _pk_and_range(cond):
    """Pull (pk, sk_lo, sk_hi) out of a boto3 KeyConditionExpression."""
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


class _WireTable:
    """A DynamoDB stand-in faithful to the three behaviours this bug lives in:
    the sk range, the phase FilterExpression, and Limit applied BEFORE the filter."""

    def __init__(self, rows):
        self.rows = rows  # {pk: [item, ...]}

    def query(self, **kwargs):
        pk, lo, hi = _pk_and_range(kwargs["KeyConditionExpression"])
        items = [i for i in self.rows.get(pk, []) if (lo is None or lo <= i["sk"] <= hi)]
        items.sort(key=lambda i: i["sk"], reverse=not kwargs.get("ScanIndexForward", True))
        if "Limit" in kwargs:
            items = items[: kwargs["Limit"]]  # DynamoDB limits the READ, then filters
        if kwargs.get("FilterExpression") is not None:  # ADR-058 phase filter engaged
            items = [i for i in items if i.get("phase") != "pilot"]
        return {"Items": items}


def _row(source, iso, weight, phase="live"):
    return {"pk": f"{common.USER_PREFIX}{source}", "sk": f"DATE#{iso}", "weight_lbs": weight, "phase": phase}


def _wire(monkeypatch, genesis, rows):
    _set_genesis(monkeypatch, genesis)
    by_pk: dict = {}
    for r in rows:
        by_pk.setdefault(r["pk"], []).append(r)
    monkeypatch.setattr(common, "table", _WireTable(by_pk))
    monkeypatch.setattr(common, "_get_profile", lambda: {"journey_start_weight_lbs": BASELINE, "goal_weight_lbs": 185.0})
    monkeypatch.setattr(vitals, "_get_profile", lambda: {"journey_start_weight_lbs": BASELINE, "goal_weight_lbs": 185.0})
    monkeypatch.setattr(journey_mod, "EXPERIMENT_BASELINE_WEIGHT_LBS", BASELINE)


def _journey(monkeypatch, genesis, rows):
    _wire(monkeypatch, genesis, rows)
    return json.loads(vitals.handle_journey()["body"])["journey"]


# ── the defect ────────────────────────────────────────────────────────────────


def test_day1_before_the_first_weighin_reports_no_weighin(monkeypatch):
    """Genesis == today, zero same-day rows, the prior reading re-phased to pilot."""
    genesis = _iso(_today_pt())
    prior = _iso(_today_pt() - timedelta(days=1))
    j = _journey(monkeypatch, genesis, [_row("withings", prior, BASELINE + 0.04, phase="pilot")])

    assert j["pre_start"] is False, "genesis is today — this is Day 1, not the countdown"
    assert j["day_n"] == 1
    # The claim that started it: a weigh-in date for a weigh-in that never happened.
    assert j["last_weighin_date"] is None, f"served a weigh-in dated {j['last_weighin_date']!r} with no reading behind it"
    assert j["weighin_count"] == 0, "the synthetic genesis baseline is not a measurement"
    # #948 — the weight and its as-of anchor travel together.
    assert j["current_weight_lbs"] is None
    assert j["lost_lbs"] is None
    assert j["progress_pct"] is None
    assert j["weighin_span_days"] is None
    # The non-claim anchors survive: the reader still sees where this started and where it's going.
    assert j["start_weight_lbs"] == BASELINE
    assert j["goal_weight_lbs"] == 185.0


def test_pre_start_count_does_not_contradict_its_own_null_date(monkeypatch):
    """The same defect one day earlier: the countdown nulled the date but kept the
    count, so /api/journey served `weighin_count: 1, last_weighin_date: null`."""
    genesis = _iso(_today_pt() + timedelta(days=1))
    j = _journey(monkeypatch, genesis, [_row("withings", _iso(_today_pt()), BASELINE, phase="pilot")])

    assert j["pre_start"] is True
    assert j["last_weighin_date"] is None
    assert j["weighin_count"] == 0, "a count of measurements with no dates behind it"


# ── positive controls: the fix must not suppress real readings ────────────────


def test_day1_with_a_real_withings_weighin_flows(monkeypatch):
    """A weigh-in ON genesis day is a measurement — nothing is suppressed."""
    genesis = _iso(_today_pt())
    j = _journey(monkeypatch, genesis, [_row("withings", genesis, 323.0)])

    assert j["last_weighin_date"] == genesis
    assert j["weighin_count"] == 1
    assert j["current_weight_lbs"] == 323.0
    assert j["lost_lbs"] == 1.6  # 324.6 − 323.0, off the DISPLAYED values (#1225)


def test_day1_apple_health_weighin_on_genesis_supersedes_the_constant(monkeypatch):
    """The travel-scale path (#491/M-6). Against a synthetic anchor the old strictly-
    newer test compared EQUAL to the genesis date and lost to a constant."""
    genesis = _iso(_today_pt())
    j = _journey(monkeypatch, genesis, [_row("apple_health", genesis, 322.4)])

    assert j["last_weighin_date"] == genesis
    assert j["current_weight_lbs"] == 322.4
    assert j["weighin_count"] == 1


def test_mid_cycle_series_is_untouched(monkeypatch):
    """The inert-path proof: a normal cycle-day journey is unchanged."""
    start = _today_pt() - timedelta(days=30)
    rows = [_row("withings", _iso(start + timedelta(days=i)), BASELINE - i * 0.5) for i in range(0, 28, 3)]
    j = _journey(monkeypatch, _iso(start), rows)

    assert j["weighin_count"] == 10
    assert j["last_weighin_date"] == _iso(start + timedelta(days=27))
    assert j["current_weight_lbs"] is not None and j["lost_lbs"] > 0


# ── guard the SET, not the instance ───────────────────────────────────────────


def test_both_absence_branches_go_through_the_one_helper():
    """#948's list was restated inline in ONE branch, which is how the Day-1 branch
    came to null a different (empty) subset. Neither branch may re-list the fields."""
    src = pathlib.Path(journey_mod.__file__).read_text()
    fn = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.FunctionDef) and n.name == "journey")
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_null_weight_block"]
    assert len(calls) == 2, f"expected the pre-start and Day-1 branches to share the helper, found {len(calls)} call(s)"
    assert "last_weighin_date" in journey_mod._WEIGHT_ABSENT_FIELDS
    assert "current_weight_lbs" in journey_mod._WEIGHT_ABSENT_FIELDS
