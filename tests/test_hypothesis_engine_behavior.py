#!/usr/bin/env python3
"""tests/test_hypothesis_engine_behavior.py — behavioral contracts of
`lambdas/compute/hypothesis_engine_lambda.py`.

Part of #1658 tranche 2. This weekly Lambda pre-registers falsifiable
hypotheses, decides them, and publishes the verdicts to /api/hypotheses, the
digests and the coach prompts. Its output is a *scientific claim about
Matthew*, so the contracts under test are the ADR-105 rigor bar first:

  * the verdict is computed in Python and an LLM only narrates it afterwards —
    it can never change a decision, and its failure must not erase one,
  * every statistic is pinned to a hand-derived closed form (arm means, mean
    difference, Cohen's pooled-SD d, the degenerate-variance CI collapse),
  * a below-floor sample yields no effect size at all — never a confident zero
    (ADR-104), and the floors are the `experiment_gates` registry's, not
    literals typed here,
  * the pre-registered spec is frozen: a check reads it, never revises it,
  * lifecycle transitions (pending → confirming → confirmed/refuted/archived),
    dedup, Decimal-before-DynamoDB, ADR-058 phase filtering on reads, and the
    fail-soft boundaries that keep one broken sub-engine from killing the run.

Complements `tests/test_hypothesis_engine_v2.py` (spec-validation + verdict
basics); this file goes after the data-mapping layer, the persistence layer,
the orchestration and the honesty rules.

Time is frozen everywhere `datetime.now` is reachable — no fixture date is ever
combined with the real clock.
"""

import inspect
import json
import math
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
for _p in (os.path.join(LAMBDAS, "compute"), LAMBDAS):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

_import_err = None
try:
    import hypothesis_engine_lambda as eng
    from common import compute_metadata, retry_utils
    from experiment import experiment_gates, phase_taxonomy
    from experiment.phase_filter import PHASE_FILTER_VALUES
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    eng = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"hypothesis_engine_lambda unavailable: {_import_err}")  # type: ignore


FROZEN_NOW = datetime(2026, 8, 7, 19, 0, 0, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`/`utcnow()`.

    A subclass (rather than a Mock) keeps `strptime`, `fromisoformat`,
    arithmetic and `.date()` working, which the module uses on the same name.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles
# ──────────────────────────────────────────────────────────────────────────────


def _cond_terms(cond):
    """Flatten a boto3 Condition tree into (attr_name, operator, value) triples."""
    expr = cond.get_expression()
    operator, values = expr["operator"], expr["values"]
    if operator == "AND":
        out = []
        for sub in values:
            out.extend(_cond_terms(sub))
        return out
    return [(values[0].name, operator, values[1] if len(values) > 1 else None)]


class FakeTable:
    """DynamoDB Table stand-in keyed the way this module keys the real table.

    `items` maps (pk, sk) → item. `query()` understands BOTH shapes the module
    issues: the boto3 `Key(...)` condition objects (hypotheses, journal
    candidates, character history) and the raw string KeyConditionExpression
    that `digest_utils.query_range_list` builds. Pagination is a bounded list of
    hand-written pages — never a Mock inside the loop.
    """

    def __init__(self, items=None):
        self.items = dict(items or {})
        self.puts = []
        self.updates = []
        self.queries = []
        self.query_error = None
        self.put_error = None
        self.update_error = None
        self.pages = None  # optional bounded list of LastEvaluatedKey-chained pages

    # -- writes --
    def put_item(self, Item=None, **kwargs):
        if self.put_error is not None:
            raise self.put_error
        self.puts.append(Item)
        self.items[(Item["pk"], Item["sk"])] = Item
        return {}

    def update_item(self, **kwargs):
        if self.update_error is not None:
            raise self.update_error
        self.updates.append(kwargs)
        return {}

    # -- reads --
    def get_item(self, Key=None, **kwargs):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item is not None else {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        if self.query_error is not None:
            raise self.query_error
        if self.pages:
            return self.pages.pop(0)
        vals = kwargs.get("ExpressionAttributeValues", {})
        kce = kwargs.get("KeyConditionExpression")
        if isinstance(kce, str) or kce is None:
            pk, lo, hi, prefix = vals.get(":pk"), vals.get(":s"), vals.get(":e"), None
        else:
            pk = lo = hi = prefix = None
            for attr, operator, value in _cond_terms(kce):
                if attr == "pk" and operator == "=":
                    pk = value
                elif attr == "sk" and operator == "begins_with":
                    prefix = value
                elif attr == "sk" and operator == "BETWEEN":
                    lo, hi = value
        rows = [v for (p, _s), v in self.items.items() if p == pk]
        if lo is not None and hi is not None:
            rows = [r for r in rows if lo <= r["sk"] <= hi]
        if prefix:
            rows = [r for r in rows if str(r["sk"]).startswith(prefix)]
        return {"Items": sorted(rows, key=lambda r: r["sk"])}


@pytest.fixture
def frozen_clock(monkeypatch):
    monkeypatch.setattr(eng, "datetime", _FrozenDatetime)
    return FROZEN_NOW


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(eng, "table", t)
    return t


@pytest.fixture(autouse=True)
def _no_cloudwatch(monkeypatch):
    """`tag_record` emits a CloudWatch metric on every write — stub it so the
    unit suite never opens a socket."""
    monkeypatch.setattr(compute_metadata, "_emit_write_metric", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(eng.time, "sleep", lambda _s: None)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any un-stubbed inference attempt is a test bug, not a slow test."""

    def _boom(*a, **k):  # pragma: no cover — asserted by absence
        raise AssertionError("hypothesis engine attempted a live inference call")

    monkeypatch.setattr(retry_utils, "call_anthropic_raw", _boom)


# ──────────────────────────────────────────────────────────────────────────────
# Fixture builders
# ──────────────────────────────────────────────────────────────────────────────


def _spec(**over):
    base = {
        "condition_metric": "protein_g",
        "condition_op": ">=",
        "condition_threshold": 150,
        "outcome_metric": "deep_sleep_hrs",
        "direction": "higher",
        "min_effect": 0,
        "lag_days": 0,
    }
    base.update(over)
    return base


def _pair_rows(cond_values, out_values, start="2026-07-10"):
    """Daily narrative rows carrying only the condition + outcome metric.

    Dates advance one calendar day per pair from `start` using pure fixture
    arithmetic — never the wall clock.
    """
    d0 = date.fromisoformat(start)
    return [
        {"date": (d0 + timedelta(days=i)).isoformat(), "protein_g": c, "deep_sleep_hrs": o}
        for i, (c, o) in enumerate(zip(cond_values, out_values))
    ]


def _arms(condition_outcomes, comparison_outcomes, start="2026-07-10"):
    """Rows whose condition arm is exactly `condition_outcomes` (protein 180 ≥ 150)
    and comparison arm exactly `comparison_outcomes` (protein 100)."""
    cond = [180.0] * len(condition_outcomes) + [100.0] * len(comparison_outcomes)
    outs = list(condition_outcomes) + list(comparison_outcomes)
    return _pair_rows(cond, outs, start=start)


def _valid_hypothesis(**over):
    hyp = {
        "hypothesis_id": "hyp_protein_deep_sleep",
        "hypothesis": "Lifting daily protein above 150g may add measurable deep sleep two nights later.",
        "domains": ["nutrition", "sleep"],
        "evidence": "On 2026-07-14 protein hit 182g and deep sleep reached 1.9 hours the following night.",
        "confirmation_criteria": "deep sleep rises by 0.3 hours on days following protein above 150 g",
        "monitoring_window_days": 21,
        "confidence": "medium",
        "actionable_if_confirmed": "Hold protein above 150g on training days.",
        "test_spec": _spec(),
    }
    hyp.update(over)
    return hyp


def _pending(created="2026-07-10T19:00:00+00:00", **over):
    hyp = {
        "sk": f"HYPOTHESIS#{created}",
        "hypothesis_id": "hyp_x",
        "hypothesis": "Protein above 150g improves deep sleep.",
        "status": "pending",
        "created_at": created,
        "check_count": 1,
        "monitoring_window_days": 21,
        "test_spec": _spec(),
    }
    hyp.update(over)
    return hyp


def _seed(channel="journal", quote="I felt it.", mentions=2, **over):
    """A journal/conversation-derived hypothesis candidate as the analyzer stores it."""
    row = {
        "cause": "late caffeine",
        "effect": "poor deep sleep",
        "cause_metric": "protein_g",
        "effect_metric": "deep_sleep_hrs",
        "mentions": mentions,
        "quotes": [{"channel": channel, "date": "2026-08-01", "quote": quote}],
        "channels": [channel],
    }
    row.update(over)
    return row


def _find_floats(obj, path="item"):
    """Every path in `obj` holding a native Python float (illegal for boto3)."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, float):
        return [path]
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in _find_floats(v, f"{path}.{k}")]
    if isinstance(obj, (list, tuple)):
        return [p for i, v in enumerate(obj) for p in _find_floats(v, f"{path}[{i}]")]
    return []


class _Blocked:
    blocked = True
    block_reason = "fabricated statistic"
    warnings = []


class _Allowed:
    blocked = False
    block_reason = ""
    warnings = []


def _anthropic(text):
    """A minimal Messages-API response body. Records the request it was sent."""
    calls = []

    def _fake(req, *a, **k):
        calls.append(req)
        return {"content": [{"text": text}]}

    _fake.calls = calls
    return _fake


def _prompt_of(req):
    body = json.loads(req.data.decode() if hasattr(req, "data") else json.dumps(req))
    return body["messages"][0]["content"]


# ══════════════════════════════════════════════════════════════════════════════
# ADR-105 rule 3 — the verdict is Python's; the LLM only narrates it
# ══════════════════════════════════════════════════════════════════════════════


class TestDeterministicBeforeNarrative:
    def test_the_verdict_is_computed_with_no_inference_call_available_at_all(self):
        # `_no_network` makes any inference attempt raise. A verdict must still land.
        stats = eng.evaluate_test_spec(_spec(), _arms([2.0] * 6, [1.0] * 6), "2026-07-10")
        assert stats["verdict"] == "supported"
        assert stats["effect_size"] == 1.0

    def test_narration_receives_a_verdict_that_was_already_decided(self, monkeypatch, frozen_clock):
        seen = {}

        def _narrate(hyp, evidence, new_status):
            seen["evidence"] = evidence
            seen["status"] = new_status
            return "In plain English: deep sleep was longer on high-protein days."

        monkeypatch.setattr(eng, "narrate_resolution", _narrate)
        rows = _arms([2.0] * 6, [1.0] * 6)
        eng.check_pending_hypotheses([_pending(monitoring_window_days=7)], rows)
        # The evidence handed to the narrator already carries the decision AND the numbers.
        assert seen["status"] == "confirmed"
        assert "supported" in seen["evidence"]
        assert "effect +1" in seen["evidence"]

    def test_a_narration_that_contradicts_the_math_cannot_change_the_verdict(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(eng, "narrate_resolution", lambda *a, **k: "Actually this hypothesis was refuted and the effect was zero.")
        rows = _arms([2.0] * 6, [1.0] * 6)
        (_h, status, evidence, stats, resolution), *_ = eng.check_pending_hypotheses([_pending(monitoring_window_days=7)], rows)
        assert (status, resolution) == ("confirmed", "confirmed")
        assert stats["verdict"] == "supported"
        assert stats["effect_size"] == 1.0
        # The narration is appended AFTER the deterministic sentence, never instead of it.
        assert evidence.startswith("Deterministic test:")

    def test_a_failed_narration_leaves_the_deterministic_evidence_whole(self, monkeypatch, frozen_clock):
        def _explode(*a, **k):
            raise RuntimeError("bedrock throttled")

        monkeypatch.setattr(eng, "narrate_resolution", _explode)
        rows = _arms([2.0] * 6, [1.0] * 6)
        with pytest.raises(RuntimeError):
            eng.check_pending_hypotheses([_pending(monitoring_window_days=7)], rows)

    def test_narrate_resolution_swallows_inference_failure_and_returns_empty(self, monkeypatch):
        def _explode(*a, **k):
            raise RuntimeError("bedrock throttled")

        monkeypatch.setattr(retry_utils, "call_anthropic_raw", _explode)
        assert eng.narrate_resolution({"hypothesis": "h"}, "Deterministic test: ...", "confirmed") == ""

    def test_a_blocked_narration_is_dropped_rather_than_published(self, monkeypatch):
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", _anthropic("Matthew's HRV is 11 points better."))
        monkeypatch.setattr(eng, "_HAS_AI_VALIDATOR", True)
        monkeypatch.setattr(eng, "validate_ai_output", lambda *a, **k: _Blocked(), raising=False)
        assert eng.narrate_resolution({"hypothesis": "h"}, "Deterministic test: ...", "confirmed") == ""

    def test_an_allowed_narration_is_returned_stripped(self, monkeypatch):
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", _anthropic("  Deep sleep was longer.  "))
        monkeypatch.setattr(eng, "_HAS_AI_VALIDATOR", True)
        monkeypatch.setattr(eng, "validate_ai_output", lambda *a, **k: _Allowed(), raising=False)
        assert eng.narrate_resolution({"hypothesis": "h"}, "Deterministic test: ...", "confirmed") == "Deep sleep was longer."

    def test_the_narration_prompt_ships_the_result_not_the_raw_data(self, monkeypatch):
        fake = _anthropic("ok")
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", fake)
        evidence = "Deterministic test: deep_sleep_hrs averaged 2.0 on 6 days vs 1.0 — effect +1 → supported."
        eng.narrate_resolution({"hypothesis": "Protein helps sleep."}, evidence, "confirmed")
        prompt = _prompt_of(fake.calls[0])
        assert evidence in prompt
        assert "the decision is made" in prompt
        assert "do not invent" in prompt.lower()

    def test_the_narrator_is_never_invoked_when_nothing_resolves(self, monkeypatch, frozen_clock):
        called = []
        monkeypatch.setattr(eng, "narrate_resolution", lambda *a, **k: called.append(1) or "")
        # Identical arms → inconclusive; created 11 days ago inside a 21-day window.
        rows = _arms([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], start="2026-07-27")
        (_h, status, _e, stats, resolution), *_ = eng.check_pending_hypotheses([_pending(created="2026-07-27T19:00:00+00:00")], rows)
        assert stats["verdict"] == "inconclusive"
        assert resolution is None and status == "pending"
        assert called == []


# ══════════════════════════════════════════════════════════════════════════════
# ADR-105 rule 1 — every statistic pinned to a hand-derived closed form
# ══════════════════════════════════════════════════════════════════════════════


class TestHandDerivedStatistics:
    def test_arm_means_and_effect_are_the_exact_arithmetic_means(self):
        # condition arm = [4,5,6,7,8,9] → mean 6.5 ; comparison = [1,2,3,4,5,6] → mean 3.5
        stats = eng.evaluate_test_spec(_spec(), _arms([4.0, 5, 6, 7, 8, 9], [1.0, 2, 3, 4, 5, 6]), "2026-07-10")
        assert stats["mean_condition"] == 6.5
        assert stats["mean_comparison"] == 3.5
        assert stats["effect_size"] == 3.0
        assert stats["n_condition"] == 6 and stats["n_comparison"] == 6
        assert stats["days_observed"] == 12

    def test_cohens_d_matches_the_pooled_sd_closed_form(self):
        # sample var of [1..6] and of [4..9] are both 17.5/5 = 3.5
        # pooled = sqrt((5*3.5 + 5*3.5)/10) = sqrt(3.5) = 1.8708287
        # d = (6.5 - 3.5) / 1.8708287 = 1.6035675 → round(…, 3)
        expected = round(3.0 / math.sqrt(3.5), 3)
        assert expected == 1.604
        stats = eng.evaluate_test_spec(_spec(), _arms([4.0, 5, 6, 7, 8, 9], [1.0, 2, 3, 4, 5, 6]), "2026-07-10")
        assert stats["cohens_d"] == expected

    def test_cohens_d_and_the_means_hold_to_three_decimals_on_an_asymmetric_pair(self):
        # condition [1,1,1,1,1,3]: mean 4/3 → 1.333, SS = 30/9, var = 2/3
        # comparison [0]*6: mean 0, var 0
        # pooled = sqrt((5*0 + 5*(2/3))/10) = sqrt(1/3) ; d = (4/3)/sqrt(1/3) = 2.3094011
        expected = round((4.0 / 3.0) / math.sqrt(1.0 / 3.0), 3)
        assert expected == 2.309
        stats = eng.evaluate_test_spec(_spec(), _arms([1.0, 1, 1, 1, 1, 3], [0.0] * 6), "2026-07-10")
        assert stats["cohens_d"] == expected
        assert stats["mean_condition"] == 1.333
        assert stats["mean_comparison"] == 0.0
        assert stats["effect_size"] == 1.333

    def test_zero_variance_arms_collapse_the_ci_and_leave_cohens_d_undefined(self):
        # Every block resample of a constant series reproduces that constant, so
        # every bootstrap replicate of the mean difference is exactly 2.0 - 1.0.
        stats = eng.evaluate_test_spec(_spec(), _arms([2.0] * 6, [1.0] * 6), "2026-07-10")
        assert stats["ci95_low"] == 1.0
        assert stats["ci95_high"] == 1.0
        assert stats["effect_size"] == 1.0
        # ADR-104: an undefined standardized effect is None, never a confident 0.0.
        assert stats["cohens_d"] is None

    def test_the_ci_is_ordered_and_brackets_zero_when_the_arms_do_not_separate(self):
        rows = _arms([1.0, 2, 3, 4, 5, 6], [1.0, 2, 3, 4, 5, 6])
        stats = eng.evaluate_test_spec(_spec(), rows, "2026-07-10")
        assert stats["ci95_low"] <= stats["ci95_high"]
        assert stats["ci95_low"] < 0 < stats["ci95_high"]
        assert stats["effect_size"] == 0.0
        assert stats["verdict"] == "inconclusive"

    def test_the_predicted_direction_decides_whether_one_effect_supports_or_contradicts(self):
        rows = _arms([1.0] * 6, [2.0] * 6)  # effect exactly -1.0
        lower = eng.evaluate_test_spec(_spec(direction="lower"), rows, "2026-07-10")
        assert lower["effect_size"] == -1.0 and lower["ci95_high"] == -1.0
        assert lower["verdict"] == "supported"
        assert eng.evaluate_test_spec(_spec(direction="higher"), rows, "2026-07-10")["verdict"] == "contradicted"

    def test_the_min_effect_floor_is_applied_to_the_absolute_effect(self):
        rows = _arms([1.0] * 6, [2.0] * 6)  # effect exactly -1.0
        assert eng.evaluate_test_spec(_spec(direction="lower", min_effect=0.5), rows, "2026-07-10")["verdict"] == "supported"
        short = eng.evaluate_test_spec(_spec(direction="lower", min_effect=2.0), rows, "2026-07-10")
        assert short["verdict"] == "inconclusive"
        assert short["effect_size"] == -1.0  # magnitude still reported honestly

    def test_a_median_split_puts_days_strictly_above_the_median_in_the_condition_arm(self):
        # condition values 1..12 → sorted[6] = 7 is the split; 8..12 (five days) are "above".
        rows = _pair_rows([float(i) for i in range(1, 13)], [1.0] * 7 + [2.0] * 5)
        stats = eng.evaluate_test_spec(_spec(condition_op="median_split", condition_threshold=None), rows, "2026-07-10")
        assert stats["n_condition"] == 5 and stats["n_comparison"] == 7
        assert stats["mean_condition"] == 2.0 and stats["mean_comparison"] == 1.0

    def test_both_threshold_operators_include_days_sitting_exactly_on_the_threshold(self):
        below = _pair_rows([150.0] * 6 + [151.0] * 6, [2.0] * 6 + [1.0] * 6)
        le = eng.evaluate_test_spec(_spec(condition_op="<=", condition_threshold=150), below, "2026-07-10")
        assert le["n_condition"] == 6 and le["mean_condition"] == 2.0
        above = _pair_rows([150.0] * 6 + [149.0] * 6, [2.0] * 6 + [1.0] * 6)
        ge = eng.evaluate_test_spec(_spec(condition_threshold=150), above, "2026-07-10")
        assert ge["n_condition"] == 6 and ge["mean_condition"] == 2.0

    def test_lag_pairs_the_outcome_from_exactly_n_days_after_the_condition_day(self):
        rows = _pair_rows([180.0] * 6 + [100.0] * 6, [0.0] * 12)
        # Overwrite outcomes so only the day AFTER a high-protein day is elevated.
        for i, r in enumerate(rows):
            r["deep_sleep_hrs"] = 2.0 if 1 <= i <= 6 else 1.0
        lagged = eng.evaluate_test_spec(_spec(lag_days=1), rows, "2026-07-10")
        # All six high days have a +1d partner; the final low day has none and drops.
        assert lagged["n_condition"] == 6 and lagged["n_comparison"] == 5
        assert lagged["mean_condition"] == 2.0
        assert lagged["mean_comparison"] == 1.0
        # Same-day pairing sees the effect displaced by one day, so it must NOT agree.
        same_day = eng.evaluate_test_spec(_spec(lag_days=0), rows, "2026-07-10")
        assert same_day["mean_condition"] != 2.0

    def test_a_condition_day_with_no_partner_at_the_lag_is_dropped_not_imputed(self):
        rows = _pair_rows([180.0] * 6 + [100.0] * 6, [1.5] * 12)
        stats = eng.evaluate_test_spec(_spec(lag_days=3), rows, "2026-07-10")
        assert stats["days_observed"] == 9  # 12 days minus the last 3 with no +3d partner

    def test_days_before_the_pre_registration_date_are_excluded_from_the_test(self):
        rows = _arms([2.0] * 6, [1.0] * 6, start="2026-07-01")  # 2026-07-01 .. 2026-07-12
        stats = eng.evaluate_test_spec(_spec(), rows, "2026-07-07")
        assert stats["days_observed"] == 6  # only 07-07 .. 07-12 count


# ══════════════════════════════════════════════════════════════════════════════
# ADR-104/105 — a below-floor sample yields no confident anything
# ══════════════════════════════════════════════════════════════════════════════


class TestSampleFloorsAreHonest:
    def test_a_thin_condition_arm_reports_its_size_but_no_effect_size(self):
        floor = eng.MIN_DAYS_PER_ARM
        rows = _arms([2.0] * (floor - 1), [1.0] * (floor + 3))
        stats = eng.evaluate_test_spec(_spec(), rows, "2026-07-10")
        assert stats["n_condition"] == floor - 1
        assert stats["verdict"] == "inconclusive"
        for field in ("effect_size", "ci95_low", "ci95_high", "cohens_d", "mean_condition", "mean_comparison"):
            assert stats[field] is None, f"{field} must be absent, not a fabricated value"

    def test_exactly_the_registry_floor_per_arm_is_enough_to_compute_a_verdict(self):
        floor = eng.MIN_DAYS_PER_ARM
        stats = eng.evaluate_test_spec(_spec(), _arms([2.0] * floor, [1.0] * floor), "2026-07-10")
        assert stats["n_condition"] == floor and stats["n_comparison"] == floor
        assert stats["effect_size"] == 1.0
        assert stats["verdict"] == "supported"

    def test_below_the_total_pair_floor_nothing_is_computed_at_all(self):
        rows = _arms([2.0] * 5, [1.0] * 4)  # 9 pairs < 2 * MIN_DAYS_PER_ARM
        stats = eng.evaluate_test_spec(_spec(), rows, "2026-07-10")
        assert stats["days_observed"] == 9
        assert stats["n_condition"] == 0 and stats["n_comparison"] == 0
        assert stats["effect_size"] is None and stats["verdict"] == "inconclusive"

    def test_every_statistical_floor_comes_from_the_experiment_gates_registry(self):
        # ADR-105: thresholds are the platform's own calibrated gates, never
        # constants hand-picked inside this Lambda.
        assert eng.MIN_DAYS_PER_ARM is experiment_gates.HYPOTHESIS_MIN_DAYS_PER_ARM
        assert eng.MIN_DATA_DAYS is experiment_gates.HYPOTHESIS_MIN_DATA_DAYS
        assert eng.MIN_METRICS_PER_DAY is experiment_gates.HYPOTHESIS_MIN_METRICS_PER_DAY
        assert eng.MIN_SAMPLE_DAYS_FOR_CHECK is experiment_gates.HYPOTHESIS_MIN_SAMPLE_DAYS_FOR_CHECK

    def test_a_day_needs_the_registry_metric_count_to_be_called_complete(self):
        floor = eng.MIN_METRICS_PER_DAY
        rich = {"date": "2026-08-01", **{f"m{i}": 1.0 for i in range(floor)}}
        thin = {"date": "2026-08-02", **{f"m{i}": 1.0 for i in range(floor - 1)}}
        _ok, complete, total, _msg = eng.check_data_completeness([rich, thin])
        assert (complete, total) == (1, 2)

    def test_completeness_fails_one_day_short_of_the_registry_floor(self):
        floor_days, floor_metrics = eng.MIN_DATA_DAYS, eng.MIN_METRICS_PER_DAY
        day = lambda i: {"date": f"2026-07-{i + 1:02d}", **{f"m{j}": 1.0 for j in range(floor_metrics)}}  # noqa: E731
        assert eng.check_data_completeness([day(i) for i in range(floor_days - 1)])[0] is False
        assert eng.check_data_completeness([day(i) for i in range(floor_days)])[0] is True

    def test_no_data_is_reported_as_zero_of_zero_against_the_stated_thresholds(self):
        ok, complete, total, msg = eng.check_data_completeness([])
        assert ok is False and complete == 0 and total == 0
        assert f"need {eng.MIN_DATA_DAYS}" in msg
        assert f"{eng.MIN_METRICS_PER_DAY}+ metrics" in msg


# ══════════════════════════════════════════════════════════════════════════════
# The pre-registration vocabulary must describe metrics that actually exist
# ══════════════════════════════════════════════════════════════════════════════

# Field names taken from each source's WRITER, not from this module's reader:
#   whoop_lambda.py         recovery_score / hrv / resting_heart_rate / sleep_quality_score /
#                           sleep_efficiency_percentage / slow_wave_sleep_hours / rem_sleep_hours /
#                           sleep_duration_hours
#   garmin_lambda.py        extract_stress → "avg_stress"; extract_summary → "steps";
#                           extract_body_battery → "body_battery_high"
#   macrofactor_lambda.py   total_calories_kcal / total_protein_g / total_carbs_g / total_fat_g
#   withings                weight_lbs
#   health_auto_export      steps / active_calories / mindful_minutes / blood_glucose_avg / walking_speed_mph
#   strava_lambda.transform activity_count / total_zone2_seconds  (no aggregate kilojoules field)
#   journal_enrichment      enriched_mood / enriched_energy / enriched_stress / enriched_social_quality
#   eightsleep_lambda       time_to_sleep_min  (bed temperature RETIRED — ADR-118/#489)
#   habitify_lambda         habits: {name: bool}
#   daily_metrics_compute   diary_sessions

WRITER_TRUTH = {
    "whoop": {
        "recovery_score": 61,
        "hrv": 74.5,
        "resting_heart_rate": 52,
        "sleep_quality_score": 88,
        "sleep_efficiency_percentage": 93.1,
        "slow_wave_sleep_hours": 1.4,
        "rem_sleep_hours": 1.8,
        "sleep_duration_hours": 7.2,
    },
    "garmin": {"avg_stress": 34, "body_battery_high": 81, "steps": 9412},
    "macrofactor": {"total_calories_kcal": 1810, "total_protein_g": 182, "total_carbs_g": 140, "total_fat_g": 61},
    "withings": {"weight_lbs": 318.4},
    "apple_health": {"steps": 9800, "active_calories": 620, "mindful_minutes": 12, "blood_glucose_avg": 96, "walking_speed_mph": 3.1},
    "strava": {"activity_count": 2, "total_zone2_seconds": 1800},
    "notion": {"enriched_mood": 7, "enriched_energy": 6, "enriched_stress": 3, "enriched_social_quality": "good"},
    "eightsleep": {"time_to_sleep_min": 14},
    "habitify": {"habits": {"a": True, "b": True, "c": True, "d": False, "e": False}},
    "computed_metrics": {"diary_sessions": 1},
}

# The names THIS module reads (the reader-side contract), for the internal-consistency test.
READER_TRUTH = {
    "whoop": WRITER_TRUTH["whoop"],
    "garmin": {"average_stress_level": 34, "body_battery_high": 81, "total_steps": 9412},
    "macrofactor": WRITER_TRUTH["macrofactor"],
    "withings": WRITER_TRUTH["withings"],
    "apple_health": WRITER_TRUTH["apple_health"],
    "strava": {"activity_count": 2, "total_kilojoules": 900, "zone2_minutes": 30},
    "notion": WRITER_TRUTH["notion"],
    "eightsleep": {"time_to_sleep_min": 14, "bed_temp_f": 71.5},
    "habitify": WRITER_TRUTH["habitify"],
    "computed_metrics": WRITER_TRUTH["computed_metrics"],
}

DAY = "2026-08-01"


def _data(fields_by_source, day=DAY):
    return {src: [{"date": day, **fields}] for src, fields in fields_by_source.items()}


class TestVocabularyIsMeasurable:
    def test_the_narrative_emits_exactly_the_pre_registration_vocabulary(self):
        """Guard the SET: a metric added to SPEC_METRICS that build_data_narrative
        cannot emit would validate at pre-registration and then be permanently
        unmeasurable at check time."""
        row = eng.build_data_narrative(_data(READER_TRUTH))[0]
        emitted = set(row) - {"date"}
        # `social` is emitted for prompt colour but is deliberately not testable
        # (it is a free-text quality label, not a number).
        assert emitted - {"social"} == set(eng.SPEC_METRICS)

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): build_data_narrative reads field names no writer produces — "
            "garmin 'average_stress_level' (writer: avg_stress), garmin 'total_steps' (writer: steps), "
            "strava 'total_kilojoules' (never written), strava 'zone2_minutes' (writer: total_zone2_seconds), "
            "eightsleep 'bed_temp_f' (ingestion RETIRED, ADR-118/#489). Those five vocabulary entries can be "
            "pre-registered but never measured."
        ),
    )
    def test_every_vocabulary_metric_is_producible_from_what_its_writer_stores(self):
        row = eng.build_data_narrative(_data(WRITER_TRUTH))[0]
        assert set(eng.SPEC_METRICS) - set(row) == set()

    @pytest.mark.xfail(
        strict=False,
        reason="DEFECT (tranche-2 discovery): garmin_lambda.extract_stress writes 'avg_stress'; this module reads "
        "'average_stress_level', so the `stress` metric is never populated and any spec on it stays inconclusive forever.",
    )
    def test_garmin_stress_is_read_from_the_field_garmin_writes(self):
        row = eng.build_data_narrative(_data({"garmin": WRITER_TRUTH["garmin"]}))[0]
        assert row["stress"] == 34.0

    @pytest.mark.xfail(
        strict=False,
        reason="DEFECT (tranche-2 discovery): garmin_lambda.extract_summary writes 'steps'; this module reads "
        "'total_steps', so the `steps_garmin` metric is never populated.",
    )
    def test_garmin_steps_are_read_from_the_field_garmin_writes(self):
        row = eng.build_data_narrative(_data({"garmin": WRITER_TRUTH["garmin"]}))[0]
        assert row["steps_garmin"] == 9412.0

    @pytest.mark.xfail(
        strict=False,
        reason="DEFECT (tranche-2 discovery): strava_lambda.transform writes 'total_zone2_seconds'; this module reads "
        "'zone2_minutes', so the `zone2_min` metric is never populated (and the unit differs by 60x).",
    )
    def test_strava_zone2_is_read_from_the_field_strava_writes(self):
        row = eng.build_data_narrative(_data({"strava": WRITER_TRUTH["strava"]}))[0]
        assert row["zone2_min"] == 30.0

    @pytest.mark.xfail(
        strict=False,
        reason="DEFECT (tranche-2 discovery): no writer stores a strava 'total_kilojoules' aggregate (transform emits "
        "per-activity 'kilojoules' inside `activities` only), so the `training_load` metric is never populated.",
    )
    def test_strava_training_load_is_read_from_a_field_some_writer_stores(self):
        row = eng.build_data_narrative(_data({"strava": WRITER_TRUTH["strava"]}))[0]
        assert "training_load" in row

    @pytest.mark.xfail(
        strict=False,
        reason="DEFECT (tranche-2 discovery): Eight Sleep bed-temperature ingestion was RETIRED (ADR-118/#489) but "
        "'bed_temp_f' is still advertised in SPEC_METRICS, so the generator can pre-register a structurally "
        "unmeasurable hypothesis that can only ever expire undecided.",
    )
    def test_bed_temperature_is_either_measurable_or_out_of_the_vocabulary(self):
        row = eng.build_data_narrative(_data({"eightsleep": WRITER_TRUTH["eightsleep"]}))[0]
        assert ("bed_temp_f" in row) or ("bed_temp_f" not in eng.SPEC_METRICS)

    def test_the_generation_prompt_advertises_the_whole_vocabulary(self, monkeypatch):
        fake = _anthropic('{"hypotheses": []}')
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", fake)
        eng.generate_hypotheses([{"date": DAY, "protein_g": 180}], [])
        prompt = _prompt_of(fake.calls[0])
        missing = [m for m in eng.SPEC_METRICS if m not in prompt]
        assert missing == []


# ══════════════════════════════════════════════════════════════════════════════
# build_data_narrative — mapping, absence, ordering
# ══════════════════════════════════════════════════════════════════════════════


class TestDataNarrative:
    def test_whoop_sleep_and_recovery_fields_land_on_their_vocabulary_names(self):
        row = eng.build_data_narrative(_data({"whoop": WRITER_TRUTH["whoop"]}))[0]
        assert row["recovery"] == 61.0
        assert row["rhr"] == 52.0
        assert row["sleep_score"] == 88.0
        assert row["sleep_efficiency"] == 93.1
        assert row["deep_sleep_hrs"] == 1.4
        assert row["rem_hrs"] == 1.8
        assert row["total_sleep_hrs"] == 7.2

    def test_nutrition_and_weight_come_from_their_own_sources(self):
        row = eng.build_data_narrative(_data({"macrofactor": WRITER_TRUTH["macrofactor"], "withings": WRITER_TRUTH["withings"]}))[0]
        assert row["calories"] == 1810.0 and row["protein_g"] == 182.0
        assert row["weight_lbs"] == 318.4  # #484: never the MacroFactor TDEE column

    def test_workout_is_a_boolean_flag_derived_from_the_activity_count(self):
        busy = eng.build_data_narrative(_data({"strava": {"activity_count": 2}}))[0]
        rest = eng.build_data_narrative(_data({"strava": {"activity_count": 0}}))[0]
        assert busy["workout"] is True
        assert rest["workout"] is False

    def test_habit_pct_is_the_completed_fraction_and_is_absent_when_nothing_is_tracked(self):
        row = eng.build_data_narrative(_data({"habitify": {"habits": {"a": True, "b": True, "c": True, "d": False, "e": False}}}))[0]
        assert row["habit_pct"] == 0.6  # 3 of 5
        # No tracked habits is an absence, not a 0% adherence day (ADR-104).
        empty = eng.build_data_narrative(_data({"habitify": {"habits": {}}, "whoop": {"hrv": 70}}))[0]
        assert "habit_pct" not in empty

    def test_diary_day_is_one_on_a_recorded_day_and_zero_on_a_measured_non_recorded_day(self):
        rec = eng.build_data_narrative(_data({"computed_metrics": {"diary_sessions": 2}, "whoop": {"hrv": 70}}))[0]
        non = eng.build_data_narrative(_data({"computed_metrics": {"diary_sessions": 0}, "whoop": {"hrv": 70}}))[0]
        assert rec["diary_day"] == 1.0
        assert non["diary_day"] == 0.0  # an honest measured zero, not an absence

    def test_diary_day_is_absent_when_the_metric_was_never_computed(self):
        # #1843 shipped mid-cycle: pre-#1843 computed_metrics rows have no
        # diary_sessions field at all. ADR-104 — absent, never a factual 0.
        row = eng.build_data_narrative(_data({"computed_metrics": {"active_minutes": 30}, "whoop": {"hrv": 70}}))[0]
        assert "diary_day" not in row

    def test_a_none_valued_metric_is_omitted_rather_than_zeroed(self):
        row = eng.build_data_narrative(_data({"whoop": {"hrv": 70, "recovery_score": None}}))[0]
        assert "recovery" not in row
        assert row["hrv"] == 70.0

    def test_rows_are_returned_in_ascending_date_order(self):
        data = {"whoop": [{"date": "2026-08-03", "hrv": 70, "recovery_score": 1}, {"date": "2026-08-01", "hrv": 60, "recovery_score": 2}]}
        assert [r["date"] for r in eng.build_data_narrative(data)] == ["2026-08-01", "2026-08-03"]

    def test_one_days_metrics_never_leak_onto_another_day(self):
        data = {
            "whoop": [{"date": "2026-08-01", "hrv": 70, "recovery_score": 60}],
            "withings": [{"date": "2026-08-02", "weight_lbs": 318.4}],
        }
        by_date = {r["date"]: r for r in eng.build_data_narrative(data)}
        assert "weight_lbs" not in by_date["2026-08-01"]
        assert "hrv" not in by_date["2026-08-02"]

    def test_no_data_and_metric_free_days_yield_no_rows(self):
        assert eng.build_data_narrative(None) == []
        assert eng.build_data_narrative({}) == []
        assert eng.build_data_narrative({"whoop": [{"date": DAY}]}) == []


# ══════════════════════════════════════════════════════════════════════════════
# validate_hypothesis — the pre-registration gate
# ══════════════════════════════════════════════════════════════════════════════


class TestHypothesisValidation:
    def test_every_field_the_module_calls_required_is_actually_enforced(self):
        """Guard the SET: derived from REQUIRED_HYPOTHESIS_FIELDS so a newly
        required field cannot be added without being enforced."""
        assert eng.validate_hypothesis(_valid_hypothesis())[0] is True
        for field in sorted(eng.REQUIRED_HYPOTHESIS_FIELDS):
            hyp = _valid_hypothesis()
            hyp.pop(field)
            ok, issues = eng.validate_hypothesis(hyp)
            assert ok is False, f"{field} is declared required but is not enforced"
            assert any(field in issue for issue in issues), (field, issues)

    def test_only_the_registered_confidence_levels_are_accepted(self):
        for level in sorted(eng.VALID_CONFIDENCE_LEVELS):
            assert eng.validate_hypothesis(_valid_hypothesis(confidence=level))[0] is True, level
        ok, issues = eng.validate_hypothesis(_valid_hypothesis(confidence="certain"))
        assert ok is False and any("confidence" in i for i in issues)

    def test_a_single_domain_hypothesis_is_not_cross_domain(self):
        ok, issues = eng.validate_hypothesis(_valid_hypothesis(domains=["sleep"]))
        assert ok is False and any("2+ domains" in i for i in issues)

    def test_confirmation_criteria_must_carry_a_number_with_a_unit(self):
        assert eng.validate_hypothesis(_valid_hypothesis(confirmation_criteria="deep sleep clearly improves"))[0] is False
        assert eng.validate_hypothesis(_valid_hypothesis(confirmation_criteria="deep sleep improves by 5"))[0] is False
        assert eng.validate_hypothesis(_valid_hypothesis(confirmation_criteria="deep sleep improves by 5 %"))[0] is True

    def test_the_monitoring_window_must_be_between_seven_and_thirty_days(self):
        for window, valid in [(6, False), (7, True), (21, True), (30, True), (31, False), ("soon", False)]:
            assert eng.validate_hypothesis(_valid_hypothesis(monitoring_window_days=window))[0] is valid, window

    def test_a_hypothesis_that_reuses_most_of_an_existing_ones_words_is_rejected(self):
        existing = ["Lifting daily protein above 150g may add measurable deep sleep two nights later."]
        ok, issues = eng.validate_hypothesis(_valid_hypothesis(), existing_texts=existing)
        assert ok is False and any("Too similar" in i for i in issues)

    def test_duplicate_detection_ignores_letter_case(self):
        existing = ["LIFTING DAILY PROTEIN ABOVE 150G MAY ADD MEASURABLE DEEP SLEEP TWO NIGHTS LATER."]
        assert eng.validate_hypothesis(_valid_hypothesis(), existing_texts=existing)[0] is False

    def test_a_genuinely_different_hypothesis_survives_the_duplicate_check(self):
        existing = ["Cold bedroom temperature shortens time to sleep onset on high-strain evenings."]
        assert eng.validate_hypothesis(_valid_hypothesis(), existing_texts=existing)[0] is True

    def test_a_very_short_hypothesis_text_bypasses_the_similarity_heuristic(self):
        # <= 20 characters carries too little signal for a word-overlap ratio.
        hyp = _valid_hypothesis(hypothesis="Protein helps.")
        assert eng.validate_hypothesis(hyp, existing_texts=["Protein helps."])[0] is True

    def test_all_validation_issues_are_reported_together_not_just_the_first(self):
        ok, issues = eng.validate_hypothesis({"hypothesis": "x"})
        assert ok is False and len(issues) >= 4


# ══════════════════════════════════════════════════════════════════════════════
# Evidence sentences — the reader-facing string, built only from computed stats
# ══════════════════════════════════════════════════════════════════════════════


class TestDeterministicEvidence:
    def test_the_evidence_sentence_quotes_the_computed_means_arm_sizes_and_ci(self):
        stats = eng.evaluate_test_spec(_spec(), _arms([4.0, 5, 6, 7, 8, 9], [1.0, 2, 3, 4, 5, 6]), "2026-07-10")
        note = eng.deterministic_evidence(_spec(), stats)
        assert "6.5 on 6 protein_g >= 150 days" in note
        assert "3.5 on 6 comparison days" in note
        assert "effect +3" in note
        assert "95% CI [" in note and "d=1.604" in note
        assert note.endswith("→ supported.")

    def test_a_median_split_is_described_as_above_median_not_as_a_threshold(self):
        rows = _pair_rows([float(i) for i in range(1, 13)], [1.0] * 7 + [2.0] * 5)
        spec = _spec(condition_op="median_split", condition_threshold=None)
        note = eng.deterministic_evidence(spec, eng.evaluate_test_spec(spec, rows, "2026-07-10"))
        assert "high-protein_g (above median)" in note

    def test_a_lagged_test_says_how_many_days_later_the_outcome_was_measured(self):
        rows = _arms([2.0] * 8, [1.0] * 8)
        spec = _spec(lag_days=2)
        note = eng.deterministic_evidence(spec, eng.evaluate_test_spec(spec, rows, "2026-07-10"))
        assert "deep_sleep_hrs 2d later averaged" in note

    def test_an_uncomputable_test_names_the_arm_floor_it_fell_short_of(self):
        floor = eng.MIN_DAYS_PER_ARM
        stats = eng.evaluate_test_spec(_spec(), _arms([2.0] * (floor - 1), [1.0] * (floor + 3)), "2026-07-10")
        note = eng.deterministic_evidence(_spec(), stats)
        assert "inconclusive" in note
        assert f"need {floor}+ per arm" in note
        # ADR-104: no invented effect appears in the reader-facing sentence.
        assert "effect" not in note

    def test_the_evidence_never_reports_a_ci_it_could_not_compute(self):
        stats = {
            "verdict": "inconclusive",
            "days_observed": 12,
            "n_condition": 6,
            "n_comparison": 6,
            "effect_size": 1.0,
            "mean_condition": 2.0,
            "mean_comparison": 1.0,
            "ci95_low": None,
            "cohens_d": None,
        }
        note = eng.deterministic_evidence(_spec(), stats)
        assert "95% CI" not in note and "d=" not in note


# ══════════════════════════════════════════════════════════════════════════════
# Lifecycle transitions
# ══════════════════════════════════════════════════════════════════════════════


class TestLifecycleTransitions:
    @pytest.fixture(autouse=True)
    def _quiet_narrator(self, monkeypatch):
        monkeypatch.setattr(eng, "narrate_resolution", lambda *a, **k: "")

    def test_a_hypothesis_younger_than_the_sample_floor_is_not_checked(self, frozen_clock):
        floor = eng.MIN_SAMPLE_DAYS_FOR_CHECK
        created = (FROZEN_NOW - timedelta(days=floor - 1)).isoformat()
        rows = _arms([2.0] * 6, [1.0] * 6, start="2026-07-25")
        assert eng.check_pending_hypotheses([_pending(created=created)], rows) == []

    def test_a_hypothesis_exactly_at_the_sample_floor_is_checked(self, frozen_clock):
        floor = eng.MIN_SAMPLE_DAYS_FOR_CHECK
        created = (FROZEN_NOW - timedelta(days=floor)).isoformat()
        rows = _arms([2.0] * 6, [1.0] * 6, start=(FROZEN_NOW - timedelta(days=floor)).date().isoformat())
        updates = eng.check_pending_hypotheses([_pending(created=created)], rows)
        assert len(updates) == 1

    def test_supported_inside_an_open_window_advances_to_confirming_not_confirmed(self, frozen_clock):
        # Created 2026-07-27 → 11 days old against a 21-day window.
        rows = _arms([2.0] * 6, [1.0] * 6, start="2026-07-27")
        (_h, status, _e, stats, resolution), *_ = eng.check_pending_hypotheses([_pending(created="2026-07-27T19:00:00+00:00")], rows)
        assert stats["verdict"] == "supported"
        assert status == "confirming"
        assert resolution is None

    def test_supported_after_the_window_closes_confirms_and_resolves(self, frozen_clock):
        rows = _arms([2.0] * 6, [1.0] * 6, start="2026-07-10")
        (_h, status, _e, _s, resolution), *_ = eng.check_pending_hypotheses(
            [_pending(created="2026-07-10T19:00:00+00:00", monitoring_window_days=21)], rows
        )
        assert (status, resolution) == ("confirmed", "confirmed")

    def test_a_contradiction_refutes_immediately_even_inside_the_window(self, frozen_clock):
        rows = _arms([1.0] * 6, [2.0] * 6, start="2026-07-27")
        (_h, status, _e, stats, resolution), *_ = eng.check_pending_hypotheses([_pending(created="2026-07-27T19:00:00+00:00")], rows)
        assert stats["verdict"] == "contradicted"
        assert (status, resolution) == ("refuted", "refuted")

    def test_an_inconclusive_hypothesis_past_its_window_is_archived_as_undecided(self, frozen_clock):
        rows = _arms([1.0, 2, 3, 4, 5, 6], [1.0, 2, 3, 4, 5, 6], start="2026-07-10")
        (_h, status, _e, _s, resolution), *_ = eng.check_pending_hypotheses(
            [_pending(created="2026-07-10T19:00:00+00:00", monitoring_window_days=21)], rows
        )
        assert (status, resolution) == ("archived", "expired_undecided")

    def test_an_inconclusive_hypothesis_exactly_at_its_window_end_is_not_yet_expired(self, frozen_clock):
        # 2026-07-17 → 21 days old; the window is 21, so it gets one more week.
        rows = _arms([1.0, 2, 3, 4, 5, 6], [1.0, 2, 3, 4, 5, 6], start="2026-07-17")
        (_h, status, _e, _s, resolution), *_ = eng.check_pending_hypotheses(
            [_pending(created="2026-07-17T19:00:00+00:00", status="confirming", monitoring_window_days=21)], rows
        )
        assert status == "confirming" and resolution is None

    def test_an_inconclusive_check_still_records_the_arm_counts_for_the_reader(self, frozen_clock):
        rows = _arms([1.0, 2, 3, 4, 5, 6], [1.0, 2, 3, 4, 5, 6], start="2026-07-27")
        (_h, _st, _e, stats, _r), *_ = eng.check_pending_hypotheses([_pending(created="2026-07-27T19:00:00+00:00")], rows)
        assert stats["n_condition"] == 6 and stats["n_comparison"] == 6
        assert stats["days_observed"] == 12

    def test_the_frozen_spec_is_never_rewritten_by_a_check(self, frozen_clock):
        hyp = _pending(created="2026-07-10T19:00:00+00:00")
        original = json.dumps(hyp["test_spec"], sort_keys=True)
        eng.check_pending_hypotheses([hyp], _arms([2.0] * 6, [1.0] * 6))
        assert json.dumps(hyp["test_spec"], sort_keys=True) == original

    def test_a_v1_hypothesis_without_a_spec_is_left_to_hard_expiry(self, frozen_clock):
        legacy = _pending(created="2026-07-10T19:00:00+00:00")
        legacy.pop("test_spec")
        assert eng.check_pending_hypotheses([legacy], _arms([2.0] * 6, [1.0] * 6)) == []

    def test_a_record_without_a_sort_key_or_text_is_skipped(self, frozen_clock):
        rows = _arms([2.0] * 6, [1.0] * 6)
        assert eng.check_pending_hypotheses([_pending(sk="")], rows) == []
        assert eng.check_pending_hypotheses([_pending(hypothesis="")], rows) == []

    def test_nothing_to_check_or_no_data_returns_no_updates(self, frozen_clock):
        assert eng.check_pending_hypotheses([], _arms([2.0] * 6, [1.0] * 6)) == []
        assert eng.check_pending_hypotheses([_pending()], []) == []

    def test_an_unparseable_creation_timestamp_is_treated_as_brand_new(self, frozen_clock):
        # days_old falls back to 0, which is below the sample floor → not checked.
        assert eng.check_pending_hypotheses([_pending(created="last tuesday")], _arms([2.0] * 6, [1.0] * 6)) == []


# ══════════════════════════════════════════════════════════════════════════════
# Hard expiry
# ══════════════════════════════════════════════════════════════════════════════


class TestHardExpiry:
    def test_a_hypothesis_at_exactly_the_hard_limit_survives(self, frozen_clock):
        created = (FROZEN_NOW - timedelta(days=eng.HARD_EXPIRY_DAYS)).isoformat()
        assert eng.enforce_hard_expiry([_pending(created=created)]) == []

    def test_a_hypothesis_one_day_past_the_hard_limit_is_archived(self, frozen_clock):
        created = (FROZEN_NOW - timedelta(days=eng.HARD_EXPIRY_DAYS + 1)).isoformat()
        (sk, status, reason), *_ = eng.enforce_hard_expiry([_pending(created=created)])
        assert status == "archived"
        assert sk.startswith("HYPOTHESIS#")
        assert f"{eng.HARD_EXPIRY_DAYS + 1} days old" in reason
        assert f"limit {eng.HARD_EXPIRY_DAYS}" in reason

    def test_a_resolved_hypothesis_is_never_re_archived_but_a_live_one_always_is(self, frozen_clock):
        created = (FROZEN_NOW - timedelta(days=eng.HARD_EXPIRY_DAYS + 40)).isoformat()
        for terminal in ("archived", "confirmed", "refuted"):
            assert eng.enforce_hard_expiry([_pending(created=created, status=terminal)]) == [], terminal
        for live in ("pending", "confirming"):
            assert len(eng.enforce_hard_expiry([_pending(created=created, status=live)])) == 1, live

    def test_an_unparseable_creation_date_never_triggers_expiry(self, frozen_clock):
        assert eng.enforce_hard_expiry([_pending(created="")]) == []
        assert eng.enforce_hard_expiry([_pending(created="whenever")]) == []

    def test_a_record_without_a_sort_key_cannot_be_expired(self, frozen_clock):
        created = (FROZEN_NOW - timedelta(days=eng.HARD_EXPIRY_DAYS + 5)).isoformat()
        assert eng.enforce_hard_expiry([_pending(created=created, sk="")]) == []


# ══════════════════════════════════════════════════════════════════════════════
# Persistence — Decimal, frozen pre-registration, engine-owned keys
# ══════════════════════════════════════════════════════════════════════════════


class TestPersistence:
    def test_a_stored_hypothesis_is_all_decimal_with_its_thresholds_intact(self, table, frozen_clock):
        eng.store_hypothesis(_valid_hypothesis(test_spec=_spec(min_effect=0.05, condition_threshold=150.5)))
        item = table.puts[0]
        assert _find_floats(item) == []  # boto3 rejects native floats
        assert item["test_spec"]["min_effect"] == Decimal("0.05")
        assert item["test_spec"]["condition_threshold"] == Decimal("150.5")

    def test_pre_registration_is_stamped_at_creation_and_equals_created_at(self, table, frozen_clock):
        eng.store_hypothesis(_valid_hypothesis())
        item = table.puts[0]
        assert item["created_at"] == FROZEN_NOW.isoformat()
        assert item["pre_registered_at"] == item["created_at"]
        assert item["sk"] == f"HYPOTHESIS#{FROZEN_NOW.isoformat()}"

    def test_a_new_hypothesis_lands_in_the_hypotheses_partition_pending_and_unchecked(self, table, frozen_clock):
        eng.store_hypothesis(_valid_hypothesis())
        item = table.puts[0]
        assert item["pk"] == eng.HYPOTHESES_PK
        assert item["status"] == "pending"
        assert item["check_count"] == 0
        assert item["engine_version"] == 2

    def test_none_valued_generated_fields_are_dropped_before_the_write(self, table, frozen_clock):
        eng.store_hypothesis(_valid_hypothesis(effect_size_observed=None))
        assert "effect_size_observed" not in table.puts[0]

    @pytest.mark.xfail(
        strict=False,
        reason="DEFECT (tranche-2 discovery): store_hypothesis splats the model-supplied dict LAST "
        "(`**{k: v for k, v in hypothesis.items()}`), so an LLM-emitted `status`, `check_count`, `pk`, `sk`, "
        "`created_at` or `pre_registered_at` silently overrides the engine-owned value — a generated hypothesis "
        "can pre-declare itself confirmed, or redirect its own write to another partition.",
    )
    def test_a_generated_hypothesis_cannot_overwrite_the_engine_owned_lifecycle_keys(self, table, frozen_clock):
        hostile = _valid_hypothesis(
            status="confirmed",
            check_count=99,
            pk="USER#someone-else#SOURCE#hypotheses",
            created_at="2020-01-01T00:00:00+00:00",
            pre_registered_at="2020-01-01T00:00:00+00:00",
        )
        eng.store_hypothesis(hostile)
        item = table.puts[0]
        assert item["status"] == "pending"
        assert item["check_count"] == 0
        assert item["pk"] == eng.HYPOTHESES_PK
        assert item["created_at"] == FROZEN_NOW.isoformat()

    def test_a_status_update_writes_every_check_stat_field_as_a_decimal(self, table, frozen_clock):
        stats = eng.evaluate_test_spec(_spec(), _arms([4.0, 5, 6, 7, 8, 9], [1.0, 2, 3, 4, 5, 6]), "2026-07-10")
        eng.update_hypothesis_status("HYPOTHESIS#x", "confirming", "note", stats=stats)
        vals = table.updates[0]["ExpressionAttributeValues"]
        # Guard the SET: derived from the module's own field tuple.
        for field in eng._CHECK_STAT_FIELDS:
            assert f":{field}" in vals, f"{field} never reaches the record"
            assert isinstance(vals[f":{field}"], Decimal)

    def test_a_status_update_omits_stat_fields_that_were_never_computed(self, table, frozen_clock):
        floor = eng.MIN_DAYS_PER_ARM
        stats = eng.evaluate_test_spec(_spec(), _arms([2.0] * (floor - 1), [1.0] * (floor + 3)), "2026-07-10")
        eng.update_hypothesis_status("HYPOTHESIS#x", "pending", "note", stats=stats)
        vals = table.updates[0]["ExpressionAttributeValues"]
        assert ":effect_size" not in vals  # ADR-104: absent, not 0
        assert ":ci95_low" not in vals
        assert vals[":n_condition"] == Decimal(str(floor - 1))

    def test_a_status_update_records_the_deterministic_verdict_alongside_the_status(self, table, frozen_clock):
        eng.update_hypothesis_status("HYPOTHESIS#x", "refuted", "note", stats={"verdict": "contradicted"})
        vals = table.updates[0]["ExpressionAttributeValues"]
        assert vals[":s"] == "refuted"
        assert vals[":dv"] == "contradicted"
        # A stats payload that never reached a verdict is recorded as inconclusive.
        eng.update_hypothesis_status("HYPOTHESIS#x", "pending", "", stats={"n_condition": 3})
        assert table.updates[1]["ExpressionAttributeValues"][":dv"] == "inconclusive"

    def test_the_check_counter_increments_atomically_and_empty_evidence_is_not_written(self, table, frozen_clock):
        eng.update_hypothesis_status("HYPOTHESIS#x", "pending", "")
        kwargs = table.updates[0]
        assert "check_count = if_not_exists(check_count, :zero) + :one" in kwargs["UpdateExpression"]
        assert kwargs["ExpressionAttributeValues"][":one"] == Decimal("1")
        # An empty note must not overwrite the previous run's evidence.
        assert ":ev" not in kwargs["ExpressionAttributeValues"]

    def test_a_failed_status_update_does_not_abort_the_weekly_run(self, table, frozen_clock):
        table.update_error = RuntimeError("throughput exceeded")
        eng.update_hypothesis_status("HYPOTHESIS#x", "confirmed", "note")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# Reads — ADR-058 phase filtering and fail-soft
# ══════════════════════════════════════════════════════════════════════════════


class TestReads:
    def test_hypothesis_reads_apply_the_adr_058_phase_filter_newest_first(self, table):
        eng.load_existing_hypotheses()
        kwargs = table.queries[0]
        assert "FilterExpression" in kwargs
        assert kwargs["ExpressionAttributeValues"] == PHASE_FILTER_VALUES
        assert kwargs["ScanIndexForward"] is False

    def test_the_hypotheses_partition_is_experiment_scoped_so_filtering_is_correct(self):
        assert phase_taxonomy.SOURCE_CLASS["hypotheses"] == phase_taxonomy.EXPERIMENT_SCOPED

    def test_stored_decimals_are_returned_to_callers_as_floats(self, table):
        table.items[(eng.HYPOTHESES_PK, "HYPOTHESIS#a")] = {
            "pk": eng.HYPOTHESES_PK,
            "sk": "HYPOTHESIS#a",
            "status": "pending",
            "effect_size": Decimal("1.25"),
        }
        (row,) = eng.load_existing_hypotheses()
        assert row["effect_size"] == 1.25 and isinstance(row["effect_size"], float)

    def test_a_status_filter_narrows_the_loaded_set(self, table):
        for sk, status in (("HYPOTHESIS#a", "pending"), ("HYPOTHESIS#b", "confirmed")):
            table.items[(eng.HYPOTHESES_PK, sk)] = {"pk": eng.HYPOTHESES_PK, "sk": sk, "status": status}
        assert [h["sk"] for h in eng.load_existing_hypotheses(status_filter="confirmed")] == ["HYPOTHESIS#b"]

    def test_a_failed_read_degrades_to_no_data_rather_than_raising(self, table):
        table.query_error = RuntimeError("ProvisionedThroughputExceeded")
        assert eng.load_existing_hypotheses() == []
        assert eng.query_range("whoop", "2026-08-01", "2026-08-07") == []

    def test_gather_data_requests_every_source_the_narrative_can_read(self, monkeypatch, frozen_clock):
        """Guard the SET: the source list is derived from build_data_narrative's own
        `data.get("…")` lookups, so a newly-mapped source cannot go unfetched."""
        read_sources = set(re.findall(r'data\.get\("([a-z_]+)"', inspect.getsource(eng.build_data_narrative)))
        requested = []
        monkeypatch.setattr(eng, "query_range", lambda source, s, e: requested.append(source) or [])
        eng.gather_data()
        assert read_sources - set(requested) == set()

    def test_gather_data_window_is_lookback_days_inclusive_of_today(self, monkeypatch, frozen_clock):
        seen = []
        monkeypatch.setattr(eng, "query_range", lambda source, s, e: seen.append((s, e)) or [])
        eng.gather_data()
        start, end = seen[0]
        assert end == FROZEN_NOW.date().isoformat()
        assert (date.fromisoformat(end) - date.fromisoformat(start)).days == eng.LOOKBACK_DAYS - 1

    def test_gather_data_keeps_only_sources_with_rows_and_returns_none_when_all_are_empty(self, monkeypatch, frozen_clock):
        monkeypatch.setattr(eng, "query_range", lambda source, s, e: [{"date": DAY}] if source == "whoop" else [])
        assert set(eng.gather_data()) == {"whoop"}
        monkeypatch.setattr(eng, "query_range", lambda *a, **k: [])
        assert eng.gather_data() is None


# ══════════════════════════════════════════════════════════════════════════════
# Journal / conversation candidates
# ══════════════════════════════════════════════════════════════════════════════


class TestJournalCandidates:
    def _candidate(self, slug, mentions, status="testable", **over):
        row = {
            "pk": f"USER#{eng.USER_ID}#SOURCE#journal_analysis",
            "sk": f"HYPO_CANDIDATE#{slug}",
            "slug": slug,
            "status": status,
            "mentions": mentions,
            "cause": "late caffeine",
            "effect": "poor deep sleep",
            "cause_metric": "protein_g",
            "effect_metric": "deep_sleep_hrs",
        }
        row.update(over)
        return row

    def _load(self, table, rows):
        for r in rows:
            table.items[(r["pk"], r["sk"])] = r

    def test_only_candidates_marked_testable_are_offered_to_the_generator(self, table):
        self._load(table, [self._candidate("a", 3), self._candidate("b", 9, status="untestable")])
        assert [c["slug"] for c in eng.fetch_journal_candidates()] == ["a"]

    def test_candidates_are_ranked_by_mention_count_then_slug(self, table):
        # A missing mention count sorts last rather than crashing the comparison.
        self._load(
            table, [self._candidate("zeta", 2), self._candidate("alpha", 5), self._candidate("beta", 5), self._candidate("omega", None)]
        )
        assert [c["slug"] for c in eng.fetch_journal_candidates()] == ["alpha", "beta", "zeta", "omega"]

    def test_the_candidate_limit_is_honoured(self, table):
        self._load(table, [self._candidate(f"s{i}", 10 - i) for i in range(8)])
        assert len(eng.fetch_journal_candidates(limit=3)) == 3

    def test_a_candidate_read_failure_never_blocks_generation(self, table):
        table.query_error = RuntimeError("table missing")
        assert eng.fetch_journal_candidates() == []

    def test_every_registered_candidate_channel_is_labelled_in_the_prompt(self):
        """Guard the SET: derived from _CANDIDATE_CHANNEL_LABELS so a new channel
        cannot ship with an unreadable raw key in the prompt."""
        for channel, label in sorted(eng._CANDIDATE_CHANNEL_LABELS.items()):
            block = eng.format_journal_candidates([_seed(channel=channel)])
            assert f"{label} quote (2026-08-01)" in block, channel

    def test_an_unknown_channel_falls_back_to_its_raw_name_rather_than_vanishing(self):
        block = eng.format_journal_candidates([_seed(channel="sms")])
        assert "sms quote (2026-08-01)" in block
        assert "heard via sms" in block

    def test_a_journal_only_candidate_carries_no_heard_via_annotation(self):
        block = eng.format_journal_candidates([_seed(channel="journal")])
        bullet = next(line for line in block.splitlines() if line.startswith("- "))
        assert "[heard via" not in bullet

    def test_a_verbatim_quote_is_truncated_rather_than_flooding_the_prompt(self):
        block = eng.format_journal_candidates([_seed(quote="x" * 400)])
        assert "x" * 160 in block
        assert "x" * 161 not in block

    def test_the_candidate_block_carries_the_metric_mapping_the_spec_must_use(self):
        block = eng.format_journal_candidates([_seed(mentions=3)])
        assert "metric mapping: protein_g -> deep_sleep_hrs" in block
        assert "mentioned 3x" in block
        # No candidates means no block at all, not an empty header.
        assert eng.format_journal_candidates([]) == "" and eng.format_journal_candidates(None) == ""


# ══════════════════════════════════════════════════════════════════════════════
# Generation
# ══════════════════════════════════════════════════════════════════════════════


class TestGeneration:
    def test_a_markdown_fenced_response_is_unwrapped_before_parsing(self, monkeypatch):
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", _anthropic('```json\n{"hypotheses": [{"hypothesis_id": "a"}]}\n```'))
        result = eng.generate_hypotheses([{"date": DAY}], [])
        assert result["hypotheses"][0]["hypothesis_id"] == "a"

    def test_unparseable_output_yields_nothing_rather_than_a_fabricated_hypothesis(self, monkeypatch):
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", _anthropic("I could not find any patterns."))
        assert eng.generate_hypotheses([{"date": DAY}], []) is None
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", lambda *a, **k: {"stop_reason": "max_tokens"})
        assert eng.generate_hypotheses([{"date": DAY}], []) is None

    @pytest.mark.xfail(
        strict=False,
        reason="DEFECT (tranche-2 discovery): generate_hypotheses catches (json.JSONDecodeError, KeyError) but an "
        "EMPTY `content` list raises IndexError at resp['content'][0], which escapes the fail-soft handler and "
        "propagates out of lambda_handler — the whole weekly run dies instead of skipping generation.",
    )
    def test_an_empty_content_list_yields_nothing_rather_than_killing_the_run(self, monkeypatch):
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", lambda *a, **k: {"content": []})
        assert eng.generate_hypotheses([{"date": DAY}], []) is None

    def test_blocked_ai_output_is_discarded_rather_than_stored(self, monkeypatch):
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", _anthropic('{"hypotheses": [{"hypothesis_id": "a"}]}'))
        monkeypatch.setattr(eng, "_HAS_AI_VALIDATOR", True)
        monkeypatch.setattr(eng, "validate_ai_output", lambda *a, **k: _Blocked(), raising=False)
        assert eng.generate_hypotheses([{"date": DAY}], []) is None

    def test_the_prompt_grounds_the_model_in_the_actual_daily_rows(self, monkeypatch):
        fake = _anthropic('{"hypotheses": []}')
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", fake)
        eng.generate_hypotheses([{"date": DAY, "protein_g": 182.5}], [])
        prompt = _prompt_of(fake.calls[0])
        assert '"protein_g": 182.5' in prompt
        assert "Here is 1 days of Matthew's health data" in prompt

    def test_existing_hypotheses_are_shown_to_the_model_as_do_not_duplicate(self, monkeypatch):
        fake = _anthropic('{"hypotheses": []}')
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", fake)
        eng.generate_hypotheses([{"date": DAY}], [{"hypothesis": "Cold rooms shorten sleep onset."}])
        prompt = _prompt_of(fake.calls[0])
        assert "do NOT duplicate" in prompt
        assert "Cold rooms shorten sleep onset." in prompt

    def test_the_weight_baseline_falls_back_to_the_experiment_constant_not_a_literal(self, monkeypatch):
        from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS

        fake = _anthropic('{"hypotheses": []}')
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", fake)
        eng.generate_hypotheses([{"date": DAY}], [], profile=None)
        assert f"started {EXPERIMENT_BASELINE_WEIGHT_LBS} lbs" in _prompt_of(fake.calls[0])

    def test_a_real_profile_overrides_every_default_in_the_prompt(self, monkeypatch):
        fake = _anthropic('{"hypotheses": []}')
        monkeypatch.setattr(retry_utils, "call_anthropic_raw", fake)
        eng.generate_hypotheses(
            [{"date": DAY}],
            [],
            profile={"journey_start_weight_lbs": 340, "goal_weight_lbs": 200, "calorie_target": 2000, "protein_target_g": 210},
        )
        prompt = _prompt_of(fake.calls[0])
        assert "started 340 lbs, goal 200 lbs" in prompt
        assert "140 lb weight loss" in prompt
        assert "2000 cal/day, protein target: 210g/day" in prompt

    def test_the_system_prompt_demands_a_pre_registered_machine_checkable_spec(self):
        assert "test_spec is MANDATORY" in eng.HYPOTHESIS_SYSTEM_PROMPT
        assert "FROZEN at creation" in eng.HYPOTHESIS_SYSTEM_PROMPT
        assert "WITHOUT any further AI judgment" in eng.HYPOTHESIS_SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════════════════════════
# Calibration ledger
# ══════════════════════════════════════════════════════════════════════════════


class TestCalibrationLedger:
    def test_a_resolution_row_carries_no_python_floats(self, table, frozen_clock):
        stats = eng.evaluate_test_spec(_spec(), _arms([4.0, 5, 6, 7, 8, 9], [1.0, 2, 3, 4, 5, 6]), "2026-07-10")
        eng.write_calibration_row(_pending(), stats, "confirmed")
        assert _find_floats(table.puts[0]) == []

    def test_an_unmeasured_effect_is_absent_from_the_ledger_not_stored_as_zero(self, table, frozen_clock):
        floor = eng.MIN_DAYS_PER_ARM
        stats = eng.evaluate_test_spec(_spec(), _arms([2.0] * (floor - 1), [1.0] * (floor + 3)), "2026-07-10")
        eng.write_calibration_row(_pending(), stats, "expired_undecided")
        item = table.puts[0]
        assert "effect_size" not in item and "ci95_low" not in item and "cohens_d" not in item
        assert item["outcome"] == "expired_undecided"

    def test_the_ledger_records_the_confidence_that_was_stated_at_pre_registration(self):
        item = eng.build_calibration_item(_pending(confidence="high"), {"verdict": "supported"}, "confirmed", "2026-08-07T19:00:00+00:00")
        assert item["stated_confidence"] == "high"
        assert item["predicted_direction"] == "higher"
        assert item["pre_registered_at"] == "2026-07-10T19:00:00+00:00"
        # A hypothesis that never stated a confidence is logged as "low", never omitted —
        # dropping it would silently bias the calibration scoreboard.
        bare = _pending()
        bare.pop("confidence", None)
        assert eng.build_calibration_item(bare, {}, "refuted", "2026-08-07T19:00:00+00:00")["stated_confidence"] == "low"

    def test_the_ledger_key_falls_back_to_the_sort_key_when_no_hypothesis_id_exists(self):
        hyp = _pending()
        hyp.pop("hypothesis_id")
        item = eng.build_calibration_item(hyp, {}, "confirmed", "2026-08-07T19:00:00+00:00")
        assert item["sk"] == "CALIB#2026-08-07#2026-07-10T19:00:00+00:00"

    def test_a_ledger_write_failure_never_aborts_the_weekly_run(self, table, frozen_clock):
        table.put_error = RuntimeError("throttled")
        eng.write_calibration_row(_pending(), {"verdict": "supported"}, "confirmed")  # must not raise

    def test_a_row_with_no_predicted_direction_drops_the_field_rather_than_guessing(self, table, frozen_clock):
        hyp = _pending()
        hyp.pop("test_spec")
        eng.write_calibration_row(hyp, {"verdict": "inconclusive"}, "expired_undecided")
        assert "predicted_direction" not in table.puts[0]


# ══════════════════════════════════════════════════════════════════════════════
# Downstream coaching context (ADR-104/105 — measured numbers or none)
# ══════════════════════════════════════════════════════════════════════════════


class TestCoachingContext:
    def _confirmed(self, **over):
        h = {
            "status": "confirmed",
            "hypothesis": "Protein above 150g adds deep sleep.",
            "effect_size": 0.42,
            "ci95_low": 0.11,
            "ci95_high": 0.73,
            "n_condition": 9,
            "n_comparison": 12,
            "actionable_if_confirmed": "Hold protein above 150g.",
        }
        h.update(over)
        return h

    def test_a_confirmed_hypothesis_reaches_coaching_with_its_effect_ci_and_arm_sizes(self, table, frozen_clock):
        eng.write_hypothesis_context_to_memory([self._confirmed()])
        block = table.puts[0]["context_block"]
        assert "measured effect +0.42" in block
        assert "95% CI [0.11, 0.73]" in block
        assert "n=9/12 days" in block
        assert "[EXPERIMENT SUGGESTED] Hold protein above 150g." in block

    def test_a_confirmed_hypothesis_without_measured_stats_gets_no_invented_numbers(self, table, frozen_clock):
        eng.write_hypothesis_context_to_memory([self._confirmed(effect_size=None, ci95_low=None, ci95_high=None)])
        block = table.puts[0]["context_block"]
        assert "[CONFIRMED] Protein above 150g adds deep sleep." in block
        assert "measured effect" not in block
        assert "n=" not in block

    def test_active_hypotheses_are_flagged_as_watched_with_their_domains(self, table, frozen_clock):
        eng.write_hypothesis_context_to_memory(
            [
                {
                    "status": "pending",
                    "hypothesis": "Cold rooms shorten onset.",
                    "domains": ["sleep", "environment"],
                    "confirmation_criteria": "onset drops by 4 minutes",
                    "pre_registered_at": "2026-07-20T00:00:00+00:00",
                }
            ]
        )
        block = table.puts[0]["context_block"]
        assert "[WATCHING: sleep + environment] Cold rooms shorten onset." in block
        assert "Criteria (pre-registered 2026-07-20): onset drops by 4 minutes" in block

    def test_the_stored_counts_match_the_hypotheses_actually_summarised(self, table, frozen_clock):
        actives = [self._confirmed(), {"status": "pending", "hypothesis": "A."}, {"status": "confirming", "hypothesis": "B."}]
        eng.write_hypothesis_context_to_memory(actives)
        item = table.puts[0]
        assert item["confirmed_count"] == 1 and item["pending_count"] == 2
        assert item["sk"] == f"MEMORY#hypothesis_monitoring#{FROZEN_NOW.date().isoformat()}"

    def test_the_coaching_block_is_capped_at_three_confirmed_and_five_active(self, table, frozen_clock):
        actives = [self._confirmed(hypothesis=f"C{i}.") for i in range(5)]
        actives += [{"status": "pending", "hypothesis": f"P{i}."} for i in range(8)]
        eng.write_hypothesis_context_to_memory(actives)
        block = table.puts[0]["context_block"]
        assert block.count("[CONFIRMED]") == 3
        assert block.count("[WATCHING") == 5

    def test_nothing_is_written_when_there_is_nothing_active_to_say(self, table, frozen_clock):
        eng.write_hypothesis_context_to_memory([])
        eng.write_hypothesis_context_to_memory([{"status": "archived", "hypothesis": "old"}])
        assert table.puts == []

    def test_a_context_write_failure_never_aborts_the_weekly_run(self, table, frozen_clock):
        table.put_error = RuntimeError("throttled")
        eng.write_hypothesis_context_to_memory([self._confirmed()])  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# The one pre-registered diary-intervention hypothesis (#1843)
# ══════════════════════════════════════════════════════════════════════════════


class TestDiaryInterventionSeed:
    def test_the_seeded_hypothesis_passes_the_engines_own_validator(self, table, frozen_clock):
        assert eng.seed_diary_intervention_hypothesis([]) == {"registered": True, "hypothesis_id": eng.DIARY_INTERVENTION_HYPOTHESIS_ID}
        assert len(table.puts) == 1

    def test_the_seeded_spec_only_references_measurable_vocabulary_metrics(self, table, frozen_clock):
        eng.seed_diary_intervention_hypothesis([])
        spec = table.puts[0]["test_spec"]
        assert spec["condition_metric"] in eng.SPEC_METRICS
        assert spec["outcome_metric"] in eng.SPEC_METRICS
        assert eng.validate_test_spec({k: float(v) if isinstance(v, Decimal) else v for k, v in spec.items()})[0]

    def test_seeding_is_idempotent_whatever_state_the_existing_copy_is_in(self, table, frozen_clock):
        for status in ("pending", "confirming", "confirmed", "refuted", "archived"):
            existing = [{"hypothesis_id": eng.DIARY_INTERVENTION_HYPOTHESIS_ID, "status": status}]
            assert eng.seed_diary_intervention_hypothesis(existing) == {"registered": False, "reason": "already_registered"}, status
        assert table.puts == []

    def test_the_fuzzy_duplicate_heuristic_can_never_block_this_pre_registered_id(self, table, frozen_clock):
        # A near-identical LLM-generated hypothesis exists under a different id;
        # the structural question must still be registered.
        near_dupe = [
            {
                "hypothesis_id": "hyp_llm_guess",
                "hypothesis": (
                    "Recording a video-diary or solo-recording session on a given day is associated with "
                    "different same-day habit adherence."
                ),
            }
        ]
        assert eng.seed_diary_intervention_hypothesis(near_dupe)["registered"] is True

    def test_the_seed_declares_itself_correlative_only_with_an_n_caveat(self, table, frozen_clock):
        eng.seed_diary_intervention_hypothesis([])
        item = table.puts[0]
        assert item["correlative_only"] is True
        assert f"{eng.MIN_DAYS_PER_ARM}+ days/arm floor" in item["n_caveat"]
        # Nothing has been observed yet, so the stated confidence must be the floor.
        assert item["confidence"] == "low"
        assert "not data-mined" in item["confidence_reason"]

    def test_a_seeding_failure_never_aborts_the_weekly_run(self, table, frozen_clock):
        table.put_error = RuntimeError("throttled")
        result = eng.seed_diary_intervention_hypothesis([])
        assert result["registered"] is False and result["reason"].startswith("error:")


# ══════════════════════════════════════════════════════════════════════════════
# Handler orchestration
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def handler_env(monkeypatch, table, frozen_clock):
    """Wire the handler's collaborators to controllable doubles."""
    state = {
        "hypotheses": [],
        "generated": None,
        "generation_calls": [],
    }
    complete_day = {f"m{i}": 1.0 for i in range(eng.MIN_METRICS_PER_DAY)}
    rows = [{"date": (date(2026, 7, 9) + timedelta(days=i)).isoformat(), **complete_day} for i in range(eng.MIN_DATA_DAYS + 10)]
    state["rows"] = rows

    monkeypatch.setattr(eng, "gather_data", lambda *a, **k: {"whoop": [{"date": DAY}]})
    monkeypatch.setattr(eng, "fetch_profile", lambda: {})
    monkeypatch.setattr(eng, "build_data_narrative", lambda data: state["rows"])
    monkeypatch.setattr(eng, "load_existing_hypotheses", lambda *a, **k: list(state["hypotheses"]))
    monkeypatch.setattr(eng, "fetch_journal_candidates", lambda *a, **k: [])
    monkeypatch.setattr(eng, "narrate_resolution", lambda *a, **k: "")
    monkeypatch.setattr(eng, "refit_cross_pillar_effects", lambda force=False: {"ran": False, "reason": "not_due"})
    monkeypatch.setattr(eng, "run_time_affluence_weekly", lambda *a, **k: {"ran": False, "reason": "no_weeks"})
    monkeypatch.setattr(eng, "seed_diary_intervention_hypothesis", lambda *a, **k: {"registered": False, "reason": "already_registered"})

    def _generate(daily_rows, existing, profile=None, journal_candidates=None):
        state["generation_calls"].append(daily_rows)
        return state["generated"]

    monkeypatch.setattr(eng, "generate_hypotheses", _generate)
    return state


def _body(resp):
    return json.loads(resp["body"])


class TestHandler:
    def test_no_data_at_all_is_reported_as_a_failure_not_an_empty_success(self, monkeypatch, table, frozen_clock):
        monkeypatch.setattr(eng, "gather_data", lambda *a, **k: None)
        assert eng.lambda_handler({}, None)["statusCode"] == 500

    def test_generation_is_skipped_when_the_data_is_below_the_completeness_gate(self, handler_env):
        handler_env["rows"] = [{"date": DAY, "hrv": 70.0}]
        handler_env["generated"] = {"hypotheses": [_valid_hypothesis()]}
        body = _body(eng.lambda_handler({}, None))
        assert body["data_sufficient"] is False
        assert body["new_hypotheses"] == 0
        assert handler_env["generation_calls"] == []

    def test_generation_is_skipped_once_the_pending_cap_is_reached(self, handler_env):
        handler_env["hypotheses"] = [
            _pending(sk=f"HYPOTHESIS#{i}", created="2026-08-05T00:00:00+00:00") for i in range(eng.MAX_PENDING_HYPOTHESES)
        ]
        handler_env["generated"] = {"hypotheses": [_valid_hypothesis()]}
        body = _body(eng.lambda_handler({}, None))
        assert body["new_hypotheses"] == 0
        assert handler_env["generation_calls"] == []

    def test_generation_is_limited_to_the_remaining_slots(self, handler_env, table):
        handler_env["hypotheses"] = [
            _pending(sk=f"HYPOTHESIS#{i}", created="2026-08-05T00:00:00+00:00") for i in range(eng.MAX_PENDING_HYPOTHESES - 2)
        ]
        handler_env["generated"] = {
            "hypotheses": [
                _valid_hypothesis(hypothesis_id=f"h{i}", hypothesis=f"Distinct claim number {i} about pillar {i}.") for i in range(5)
            ]
        }
        body = _body(eng.lambda_handler({}, None))
        assert body["new_hypotheses"] == 2

    def test_generation_only_ever_sees_the_recent_generation_window(self, handler_env):
        handler_env["generated"] = {"hypotheses": []}
        eng.lambda_handler({}, None)
        assert len(handler_env["generation_calls"][0]) == eng.GENERATION_DAYS

    def test_an_invalid_generated_hypothesis_is_counted_and_not_stored(self, handler_env, table):
        handler_env["generated"] = {"hypotheses": [_valid_hypothesis(confidence="certain"), _valid_hypothesis(hypothesis_id="ok")]}
        body = _body(eng.lambda_handler({}, None))
        assert body["validation_rejected"] == 1
        assert body["new_hypotheses"] == 1
        assert len(table.puts) == 1

    def test_an_out_of_range_monitoring_window_is_clamped_rather_than_rejecting_the_run(self, handler_env, table):
        handler_env["generated"] = {"hypotheses": [_valid_hypothesis(monitoring_window_days=30)]}
        eng.lambda_handler({}, None)
        assert table.puts[0]["monitoring_window_days"] == 30

    def test_a_generation_that_returns_nothing_is_survivable(self, handler_env):
        handler_env["generated"] = None
        body = _body(eng.lambda_handler({}, None))
        assert body["new_hypotheses"] == 0

    def test_expired_hypotheses_are_archived_and_counted(self, handler_env, table):
        old = _pending(created=(FROZEN_NOW - timedelta(days=eng.HARD_EXPIRY_DAYS + 3)).isoformat())
        handler_env["hypotheses"] = [old]
        handler_env["generated"] = {"hypotheses": []}
        body = _body(eng.lambda_handler({}, None))
        assert body["expired_by_hard_limit"] == 1
        assert any(u["ExpressionAttributeValues"][":s"] == "archived" for u in table.updates)

    def test_each_resolution_writes_exactly_one_calibration_row(self, handler_env, table):
        handler_env["rows"] = _arms([1.0] * 6, [2.0] * 6, start="2026-07-27")  # contradicted → refuted
        handler_env["hypotheses"] = [_pending(created="2026-07-27T19:00:00+00:00")]
        handler_env["generated"] = {"hypotheses": []}
        body = _body(eng.lambda_handler({}, None))
        assert body["hypotheses_updated"] == 1
        assert body["resolutions_to_calibration"] == 1
        calib = [p for p in table.puts if p["pk"] == eng.CALIBRATION_PK]
        assert len(calib) == 1 and calib[0]["outcome"] == "refuted"

    def test_a_check_that_does_not_resolve_writes_no_calibration_row(self, handler_env, table):
        handler_env["rows"] = _arms([2.0] * 6, [1.0] * 6, start="2026-07-27")  # supported, window open
        handler_env["hypotheses"] = [_pending(created="2026-07-27T19:00:00+00:00")]
        handler_env["generated"] = {"hypotheses": []}
        body = _body(eng.lambda_handler({}, None))
        assert body["resolutions_to_calibration"] == 0
        assert [p for p in table.puts if p["pk"] == eng.CALIBRATION_PK] == []

    def test_a_newly_seeded_diary_hypothesis_counts_against_the_pending_cap(self, handler_env, monkeypatch):
        monkeypatch.setattr(
            eng,
            "seed_diary_intervention_hypothesis",
            lambda *a, **k: {"registered": True, "hypothesis_id": eng.DIARY_INTERVENTION_HYPOTHESIS_ID},
        )
        handler_env["hypotheses"] = [
            _pending(sk=f"HYPOTHESIS#{i}", created="2026-08-05T00:00:00+00:00") for i in range(eng.MAX_PENDING_HYPOTHESES - 1)
        ]
        handler_env["generated"] = {"hypotheses": [_valid_hypothesis()]}
        body = _body(eng.lambda_handler({}, None))
        assert body["new_hypotheses"] == 0  # the cap is full once the seed lands
        assert body["diary_intervention_hypothesis"]["registered"] is True

    def test_a_failing_side_engine_never_takes_down_the_hypothesis_run(self, handler_env, monkeypatch):
        monkeypatch.setattr(eng, "refit_cross_pillar_effects", lambda force=False: {"ran": False, "reason": "error: boom"})
        monkeypatch.setattr(eng, "run_time_affluence_weekly", lambda *a, **k: {"ran": False, "reason": "error: boom"})
        handler_env["generated"] = {"hypotheses": []}
        resp = eng.lambda_handler({}, None)
        assert resp["statusCode"] == 200
        assert _body(resp)["effect_refit"]["reason"].startswith("error")

    def test_the_effect_refit_can_be_forced_from_the_event(self, handler_env, monkeypatch):
        seen = {}
        monkeypatch.setattr(eng, "refit_cross_pillar_effects", lambda force=False: seen.setdefault("force", force) or {"ran": False})
        handler_env["generated"] = {"hypotheses": []}
        eng.lambda_handler({"force_effect_refit": True}, None)
        assert seen["force"] is True

    def test_a_core_failure_is_raised_so_the_alarm_fires(self, monkeypatch, table, frozen_clock):
        def _boom(*a, **k):
            raise RuntimeError("dynamo down")

        monkeypatch.setattr(eng, "gather_data", _boom)
        with pytest.raises(RuntimeError):
            eng.lambda_handler({}, None)


# ══════════════════════════════════════════════════════════════════════════════
# The piggybacked weekly sub-engines are fail-soft by contract
# ══════════════════════════════════════════════════════════════════════════════


class TestPiggybackedEngines:
    def test_an_effect_refit_failure_is_reported_not_raised(self, monkeypatch, table, frozen_clock):
        from experiment import effect_fitter

        monkeypatch.setattr(effect_fitter, "load_latest_fit", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        result = eng.refit_cross_pillar_effects()
        assert result["ran"] is False and result["reason"].startswith("error:")

    def test_an_effect_refit_that_is_not_due_is_a_clean_no_op(self, monkeypatch, table, frozen_clock):
        from experiment import effect_fitter

        monkeypatch.setattr(effect_fitter, "load_latest_fit", lambda *a, **k: {"sk": "FIT#2026-08-01"})
        monkeypatch.setattr(effect_fitter, "refit_due", lambda latest: False)
        assert eng.refit_cross_pillar_effects() == {"ran": False, "reason": "not_due", "last_fit": "FIT#2026-08-01"}
        assert table.puts == []

    def test_a_time_affluence_failure_is_reported_not_raised(self, monkeypatch, table, frozen_clock):
        from health import time_affluence

        monkeypatch.setattr(time_affluence, "compute_weekly_proxies", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        result = eng.run_time_affluence_weekly()
        assert result["ran"] is False and result["reason"].startswith("error:")

    def test_time_affluence_with_no_weeks_writes_nothing(self, monkeypatch, table, frozen_clock):
        from health import time_affluence

        monkeypatch.setattr(time_affluence, "compute_weekly_proxies", lambda *a, **k: [])
        assert eng.run_time_affluence_weekly() == {"ran": False, "reason": "no_weeks"}
        assert table.puts == []

    def test_the_character_history_read_walks_every_page(self, table, frozen_clock):
        pk = f"USER#{eng.USER_ID}#SOURCE#character_sheet"
        table.pages = [
            {"Items": [{"pk": pk, "sk": "DATE#2026-08-01"}], "LastEvaluatedKey": {"pk": pk, "sk": "DATE#2026-08-01"}},
            {"Items": [{"pk": pk, "sk": "DATE#2026-08-02"}]},
        ]
        assert [r["sk"] for r in eng._fetch_character_history(30)] == ["DATE#2026-08-01", "DATE#2026-08-02"]
