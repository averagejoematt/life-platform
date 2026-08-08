#!/usr/bin/env python3
"""tests/test_coach_prediction_evaluator_behavior.py — behavioral contracts of
`lambdas/coach/coach_prediction_evaluator.py`.

Part of #1658 tranche 2. This Lambda is the platform's *accountability* surface:
it is the only code that turns a coach's (or the subject's own, #1841) dated
forecast into a public verdict, and the LEARNING#/CONFIDENCE# rows it writes are
what `/api/coaches`, `/api/wrong` and the observatory publish as a track record.

The contracts under test, in the order they matter:

  * ADR-105 "every forecast graded" — a forecast is gradable only against data
    that actually exists; a missing outcome is recorded as undecidable, never
    silently scored as a hit or a miss;
  * resolution windows — nothing is graded before its (domain-clamped) horizon,
    and nothing is quietly dropped after it;
  * hit/miss boundaries — every threshold here is hand-derived, never read back
    off the implementation;
  * track-record arithmetic — an undecidable, expired or unrecognised outcome
    moves neither side of the Beta posterior, and the published `n` counts only
    graded outcomes (#1787);
  * ADR-104 — absence is written as absence, never as a factual 0;
  * Decimal-before-DynamoDB, phase filtering on reads (ADR-058/077),
    idempotency, and the fail-soft boundaries.

Everything is offline. Time is frozen through a `datetime` subclass patched onto
the module, so no fixture date is ever combined with the real clock. Every
expectation over a growable set (the coach roster, the metric registry, the
subdomain vocabulary) is derived from that set's canonical home.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_import_err = None
try:
    import coach_prediction_evaluator as ev  # noqa: E402
    from coach import (
        coach_checkin as _coach_checkin,  # noqa: E402
        dispute_docket as _dispute_docket,  # noqa: E402
    )
    from coach.persona_registry import OPERATIONAL_COACH_IDS  # noqa: E402
    from common.constants import EXPERIMENT_PHASE_CURRENT  # noqa: E402
    from experiment.measurable_metrics import METRIC_SOURCES, METRIC_SUBDOMAIN  # noqa: E402
    from ingestion.source_registry import EXTRA_QUERYABLE_PARTITIONS, SOURCE_REGISTRY  # noqa: E402
except ImportError as _e:  # pragma: no cover — only when the bundle layout changes
    _import_err = _e
    ev = None  # type: ignore

if _import_err is not None:  # pragma: no cover
    pytestmark = pytest.mark.skip(reason=f"coach_prediction_evaluator unavailable: {_import_err}")  # type: ignore


FROZEN_NOW = datetime(2026, 5, 20, 18, 0, 0, tzinfo=timezone.utc)
TODAY = "2026-05-20"
YESTERDAY = "2026-05-19"


def days_before(n):
    return (FROZEN_NOW - timedelta(days=n)).strftime("%Y-%m-%d")


class _FrozenDatetime(datetime):
    """`datetime` subclass with a pinned `now()`.

    A subclass rather than a Mock so `strptime`, `timedelta` arithmetic and
    `.strftime` keep working — the module uses all of them on the same name.
    """

    @classmethod
    def now(cls, tz=None):
        return FROZEN_NOW if tz else FROZEN_NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return FROZEN_NOW.replace(tzinfo=None)


# ──────────────────────────────────────────────────────────────────────────────
# Test doubles — hand-rolled and bounded (never a MagicMock inside a page loop)
# ──────────────────────────────────────────────────────────────────────────────


class FakeTable:
    """DynamoDB Table stand-in keyed the way this module keys the real table.

    `items` maps (pk, sk) → item. `query()` honours the two shapes the module
    issues (`sk BETWEEN :s AND :e`, `begins_with(sk, :prefix)`) and records the
    full kwargs so a test can assert on the phase FilterExpression.
    `update_item()` applies the module's `SET a = :a, ...` expression generically
    so a graded record really does change status in the store.
    """

    def __init__(self, items=None):
        self.items = dict(items or {})
        self.puts = []
        self.updates = []
        self.queries = []
        self.gets = []
        self.query_error = None
        self.put_error = None
        self.update_error = None
        self.get_error = None
        self.error_pks = set()
        self.pages = None  # optional list of pre-built responses, consumed in order

    # -- writes --
    def put_item(self, Item=None, **kwargs):
        if self.put_error is not None:
            raise self.put_error
        self.puts.append(Item)
        self.items[(Item["pk"], Item["sk"])] = dict(Item)
        return {}

    def update_item(self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, **kwargs):
        if self.update_error is not None:
            raise self.update_error
        names = ExpressionAttributeNames or {}
        values = ExpressionAttributeValues or {}
        self.updates.append({"Key": dict(Key), "expr": UpdateExpression, "values": dict(values)})
        item = self.items.setdefault((Key["pk"], Key["sk"]), dict(Key))
        for assignment in UpdateExpression.split("SET", 1)[-1].split(","):
            if "=" not in assignment:
                continue
            lhs, rhs = (part.strip() for part in assignment.split("=", 1))
            if rhs in values:
                item[names.get(lhs, lhs)] = values[rhs]
        return {}

    # -- reads --
    def get_item(self, Key=None, **kwargs):
        self.gets.append(dict(Key))
        if self.get_error is not None or Key["pk"] in self.error_pks:
            raise self.get_error or RuntimeError("throttled")
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item is not None else {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        vals = kwargs.get("ExpressionAttributeValues", {})
        if self.query_error is not None or vals.get(":pk") in self.error_pks:
            raise self.query_error or RuntimeError("throttled")
        if self.pages:
            return self.pages.pop(0)
        pk = vals.get(":pk")
        rows = [v for (p, _s), v in self.items.items() if p == pk]
        if ":s" in vals and ":e" in vals:
            rows = [r for r in rows if vals[":s"] <= r["sk"] <= vals[":e"]]
        prefix = vals.get(":prefix")
        if prefix:
            rows = [r for r in rows if str(r["sk"]).startswith(prefix)]
        return {"Items": sorted(rows, key=lambda r: r["sk"])}


class FakeCloudWatch:
    def __init__(self):
        self.calls = []
        self.error = None

    def put_metric_data(self, **kwargs):
        if self.error is not None:
            raise self.error
        self.calls.append(kwargs)
        return {}

    def metric(self, name):
        """The last emitted value for a metric name, or None."""
        for call in reversed(self.calls):
            for datum in call.get("MetricData", []):
                if datum["MetricName"] == name:
                    return datum["Value"]
        return None


class FakeLambdaClient:
    def __init__(self):
        self.invokes = []
        self.error = None

    def invoke(self, **kwargs):
        if self.error is not None:
            raise self.error
        self.invokes.append(kwargs)
        return {"StatusCode": 202}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    """Freeze the clock and cut every real AWS edge before any test body runs.

    Autouse deliberately: a test that forgot to patch `table` would fall through
    to the module-level boto3 resource, and this module's fail-soft handlers
    would swallow the resulting credential error into a green-looking pass.
    """
    fake = SimpleNamespace(table=FakeTable(), cw=FakeCloudWatch(), lam=FakeLambdaClient())
    monkeypatch.setattr(ev, "datetime", _FrozenDatetime)
    monkeypatch.setattr(ev, "table", fake.table)
    monkeypatch.setattr(ev, "_cw", fake.cw)
    monkeypatch.setattr(ev, "_lambda_client", fake.lam)
    # Neutral defaults for the #534 stance-event side-lane: budget open, not sick.
    monkeypatch.setattr(ev, "_budget_allow", lambda feature: True)
    monkeypatch.setattr(ev, "check_sick_day", lambda *a, **k: None)
    # The provenance stamp's SSM read is fail-soft but would otherwise attempt a
    # real network call on every put_item (a failed read is deliberately uncached).
    monkeypatch.setattr(_coach_checkin, "read_cycle", lambda ssm_client=None: 12)
    return fake


@pytest.fixture
def table(env):
    return env.table


def seed(table, *rows):
    for row in rows:
        table.items[(row["pk"], row["sk"])] = row


def seed_metric(table, source, field, values_by_date):
    """Seed one source partition's DATE# rows with a single metric field."""
    for date_str, value in values_by_date.items():
        row = {"pk": ev.USER_PREFIX + source, "sk": f"DATE#{date_str}", "date": date_str}
        if value is not None:
            row[field] = Decimal(str(value))
        seed(table, row)


def daily_series(field, values, end_date=TODAY, source="whoop", table=None):
    """`values` laid out one per day, ending on `end_date`."""
    end = datetime.strptime(end_date, "%Y-%m-%d")
    mapping = {(end - timedelta(days=len(values) - 1 - i)).strftime("%Y-%m-%d"): v for i, v in enumerate(values)}
    if table is not None:
        seed_metric(table, source, field, mapping)
    return mapping


def prediction(
    *,
    coach_id="sleep_coach",
    pred_id="pred_1",
    created_date=days_before(30),
    subdomain="sleep",
    status="pending",
    evaluation=None,
    **extra,
):
    return {
        "pk": f"COACH#{coach_id}" if coach_id else ev.DIARY_CLAIMS_PK,
        "sk": f"PREDICTION#{pred_id}",
        "prediction_id": pred_id,
        "coach_id": coach_id,
        "created_date": created_date,
        "subdomain": subdomain,
        "status": status,
        "evaluation": evaluation if evaluation is not None else {"type": "machine", "metric": "hrv", "condition": "gt", "threshold": 50},
        **extra,
    }


def confidence_rows(table):
    return [p for p in table.puts if str(p.get("sk", "")).startswith("CONFIDENCE#")]


def stored_posterior(coach_id="sleep_coach", subdomain="sleep", **fields):
    """An existing CONFIDENCE# row, with Decimal-typed Beta counts as DDB holds them."""

    def is_count(v):
        return isinstance(v, (int, float)) and not isinstance(v, bool)

    numeric = {k: Decimal(str(v)) for k, v in fields.items() if is_count(v)}
    rest = {k: v for k, v in fields.items() if not is_count(v)}
    return {"pk": f"COACH#{coach_id}", "sk": f"CONFIDENCE#{subdomain}", **numeric, **rest}


def learning_rows(table):
    return [p for p in table.puts if str(p.get("sk", "")).startswith("LEARNING#")]


# ══════════════════════════════════════════════════════════════════════════════
# A. ADR-105 — a forecast is gradable only against data that exists
# ══════════════════════════════════════════════════════════════════════════════


class TestGradabilityIsNotAVerdict:
    def test_a_machine_call_whose_metric_has_no_data_is_undecidable_not_refuted(self, table):
        result = ev._evaluate_machine({}, {"metric": "hrv", "condition": "gt", "threshold": 50}, {}, TODAY)
        assert result["status"] == "inconclusive"
        assert result["actual_value"] is None
        assert "hrv" in result["reason"]

    def test_an_undecidable_grade_never_claims_to_have_beaten_the_null(self, table):
        result = ev._evaluate_machine({}, {"metric": "hrv", "condition": "gt", "threshold": 50}, {}, TODAY)
        assert result["beats_null"] is False

    def test_a_metric_with_no_source_mapping_is_undecidable_rather_than_guessed(self, table):
        result = ev._evaluate_machine({}, {"metric": "vibes", "condition": "gt", "threshold": 1}, {}, TODAY)
        assert result["status"] == "inconclusive"
        assert result["actual_value"] is None

    def test_a_directional_call_with_too_little_history_is_undecidable_not_refuted(self, table):
        daily_series("hrv", [50, 51, 52], table=table)
        result = ev._evaluate_directional({}, {"metric": "hrv", "condition": "up"}, {}, TODAY)
        assert result["status"] == "inconclusive"
        assert result["beats_null"] is False

    def test_an_unreadable_comparison_is_undecidable_rather_than_a_miss(self, table):
        daily_series("hrv", [60], table=table)
        result = ev._evaluate_machine({}, {"metric": "hrv", "condition": "approximately", "threshold": 50}, {}, TODAY)
        assert result["status"] == "inconclusive"
        assert result["actual_value"] == 60.0  # the reading is reported; the verdict is not invented

    def test_an_undecidable_outcome_moves_neither_side_of_the_posterior(self, table):
        evaluations, stats = ev._evaluate_all([prediction(created_date=days_before(20))], TODAY)
        assert stats["inconclusive"] == 1
        assert evaluations[0]["bayesian_update"] is None
        assert confidence_rows(table) == []

    def test_an_expired_outcome_moves_neither_side_of_the_posterior(self, table):
        evaluations, stats = ev._evaluate_all([prediction(created_date=days_before(60))], TODAY)
        assert stats["expired"] == 1
        assert evaluations[0]["bayesian_update"] is None
        assert confidence_rows(table) == []

    def test_an_absent_reading_is_omitted_from_the_learning_row_never_stored_as_zero(self, table):
        """ADR-104: absence is absence. A stored 0.0 would render as a real measurement."""
        ev._write_learning_record("sleep_coach", TODAY, {"prediction_id": "p1", "status": "inconclusive", "actual_value": None})
        row = learning_rows(table)[0]
        assert "actual_value" not in row

    def test_a_prediction_with_no_creation_date_is_skipped_rather_than_graded(self, table):
        pred = prediction()
        pred.pop("created_date")
        evaluations, stats = ev._evaluate_all([pred], TODAY)
        assert (evaluations, stats["skipped_error"]) == ([], 1)

    def test_a_prediction_with_an_unparseable_creation_date_is_skipped_rather_than_graded(self, table):
        evaluations, stats = ev._evaluate_all([prediction(created_date="last tuesday")], TODAY)
        assert (evaluations, stats["skipped_error"]) == ([], 1)

    def test_an_unsupported_evaluation_type_is_skipped_rather_than_graded(self, table):
        pred = prediction(evaluation={"type": "vibes_based", "metric": "hrv"})
        evaluations, stats = ev._evaluate_all([pred], TODAY)
        assert (evaluations, stats["skipped_error"]) == ([], 1)

    def test_a_malformed_spec_is_skipped_rather_than_graded(self, table):
        """No metric at all — there is nothing to measure, so there is no verdict."""
        assert ev._evaluate_machine({}, {"condition": "gt", "threshold": 5}, {}, TODAY) is None
        assert ev._evaluate_directional({}, {"condition": "up"}, {}, TODAY) is None
        assert ev._evaluate_directional({}, {"metric": "hrv"}, {}, TODAY) is None

    def test_an_evaluator_crash_is_contained_to_the_one_prediction(self, table, monkeypatch):
        monkeypatch.setattr(ev, "_evaluate_machine", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        evaluations, stats = ev._evaluate_all([prediction()], TODAY)
        assert (evaluations, stats["skipped_error"]) == ([], 1)


# ══════════════════════════════════════════════════════════════════════════════
# B. Resolution windows — not before the horizon, not dropped after it
# ══════════════════════════════════════════════════════════════════════════════


class TestResolutionWindows:
    SEVEN_DAY_SPEC = {"type": "machine", "metric": "hrv", "condition": "gt", "threshold": 50, "evaluation_window_days": 7}

    def test_a_call_is_not_graded_before_its_horizon_elapses(self, table):
        # A 7-day window on a 7-day-minimum subdomain: on day 6 the call is open.
        pred = prediction(created_date=days_before(6), evaluation=self.SEVEN_DAY_SPEC)
        evaluations, stats = ev._evaluate_all([pred], TODAY)
        assert (evaluations, stats["skipped_window"]) == ([], 1)
        assert table.updates == []

    def test_a_call_is_graded_on_the_day_its_horizon_closes(self, table):
        # Created exactly 7 days ago + a 7-day window -> the deadline IS today.
        pred = prediction(created_date=days_before(7), evaluation=self.SEVEN_DAY_SPEC)
        evaluations, _ = ev._evaluate_all([pred], TODAY)
        assert len(evaluations) == 1

    def test_an_unstated_window_defaults_to_a_fortnight_before_the_domain_clamp(self):
        assert ev._get_effective_window({}, "sleep") == 14  # 14-day default > the 7-day sleep floor
        assert ev._get_effective_window({}, "cholesterol") == 60  # the labs floor wins

    def test_a_stated_window_shorter_than_the_domain_minimum_does_not_shorten_the_horizon(self, table):
        """A 3-day sleep call still waits the domain's 7 days (#813)."""
        pred = prediction(
            created_date=days_before(4),
            evaluation={"type": "machine", "metric": "hrv", "condition": "gt", "threshold": 50, "evaluation_window_days": 3},
        )
        _, stats = ev._evaluate_all([pred], TODAY)
        assert stats["skipped_window"] == 1

    def test_a_stated_window_longer_than_the_domain_minimum_is_honoured(self):
        assert ev._get_effective_window({"evaluation_window_days": 45}, "sleep") == 45

    def test_an_unknown_subdomain_falls_back_to_the_conservative_training_window(self):
        assert ev._get_effective_window({"evaluation_window_days": 5}, "astrology") == ev.DOMAIN_MIN_WINDOWS["training"]

    def test_every_registered_subdomain_resolves_to_its_own_domain_minimum(self):
        """Derived from the registry, so a new subdomain cannot leave this test
        asserting the old vocabulary."""
        for subdomain, domain in ev.SUBDOMAIN_TO_DOMAIN.items():
            expected = ev.DOMAIN_MIN_WINDOWS[domain]
            assert ev._get_effective_window({"evaluation_window_days": 1}, subdomain) == expected, subdomain

    def test_every_domain_the_subdomain_map_points_at_declares_a_minimum_window(self):
        """A domain with no entry silently takes the 14-day `.get` default."""
        missing = set(ev.SUBDOMAIN_TO_DOMAIN.values()) - set(ev.DOMAIN_MIN_WINDOWS)
        assert missing == set()

    def test_every_subdomain_the_metric_registry_emits_is_a_known_subdomain(self):
        """`measurable_metrics.metric_subdomain` is what the diary-claims writer
        stamps on a record; an unmapped value clamps the window to 21 days."""
        emitted = set(METRIC_SUBDOMAIN.values()) | {"general"}
        assert emitted - set(ev.SUBDOMAIN_TO_DOMAIN) == set()

    def test_expiry_is_exactly_twice_the_effective_window(self):
        today = datetime.strptime(TODAY, "%Y-%m-%d")
        assert ev._check_expiry({"created_date": days_before(28)}, 14, today) is False
        assert ev._check_expiry({"created_date": days_before(29)}, 14, today) is True

    def test_expiry_needs_a_parseable_creation_date(self):
        today = datetime.strptime(TODAY, "%Y-%m-%d")
        assert ev._check_expiry({}, 14, today) is False
        assert ev._check_expiry({"created_date": "2026-13-45"}, 14, today) is False

    def test_a_long_undecidable_call_is_retired_as_expired_with_its_elapsed_days_on_the_record(self, table):
        evaluations, stats = ev._evaluate_all([prediction(created_date=days_before(60))], TODAY)
        assert evaluations[0]["status"] == "expired"
        assert "60 days elapsed" in evaluations[0]["reason"]
        assert stats["expired"] == 1

    def test_an_expired_call_is_written_back_so_it_stops_being_rescanned(self, table):
        ev._evaluate_all([prediction(created_date=days_before(60))], TODAY)
        assert table.items[("COACH#sleep_coach", "PREDICTION#pred_1")]["status"] == "expired"


# ══════════════════════════════════════════════════════════════════════════════
# C. Hit / miss boundaries — every threshold hand-derived
# ══════════════════════════════════════════════════════════════════════════════


class TestConditionBoundaries:
    @pytest.mark.parametrize(
        "condition,actual,threshold,expected",
        [
            ("gt", 50.0, 50.0, False),
            ("gt", 50.1, 50.0, True),
            ("gte", 50.0, 50.0, True),
            ("gte", 49.9, 50.0, False),
            ("lt", 50.0, 50.0, False),
            ("lt", 49.9, 50.0, True),
            ("lte", 50.0, 50.0, True),
            ("lte", 50.1, 50.0, False),
        ],
    )
    def test_each_comparison_is_decided_at_its_exact_boundary(self, condition, actual, threshold, expected):
        assert ev._evaluate_condition(actual, condition, threshold) is expected

    def test_equality_holds_inside_one_hundredth_and_fails_at_it(self):
        assert ev._evaluate_condition(0.009, "eq", 0.0) is True
        assert ev._evaluate_condition(0.01, "eq", 0.0) is False

    def test_an_unknown_comparison_operator_is_undecidable_not_false(self):
        """Undecidable and False are different verdicts — False would be a miss."""
        assert ev._evaluate_condition(50.0, "roughly", 50.0) is None

    def test_a_missing_reading_or_threshold_is_undecidable(self):
        assert ev._evaluate_condition(None, "gt", 50.0) is None
        assert ev._evaluate_condition(50.0, "gt", None) is None

    def test_a_met_condition_reads_as_confirmed_and_reports_the_measurement(self, table):
        daily_series("hrv", [60.5], table=table)
        result = ev._evaluate_machine({}, {"metric": "hrv", "condition": "gt", "threshold": 50}, {}, TODAY)
        assert (result["status"], result["actual_value"]) == ("confirmed", 60.5)

    def test_a_failed_condition_reads_as_refuted_and_reports_the_measurement(self, table):
        daily_series("hrv", [40.25], table=table)
        result = ev._evaluate_machine({}, {"metric": "hrv", "condition": "gt", "threshold": 50}, {}, TODAY)
        assert (result["status"], result["actual_value"], result["beats_null"]) == ("refuted", 40.25, False)


class TestDirectionalNoiseBand:
    def test_a_move_exactly_at_the_noise_threshold_is_not_enough_to_confirm(self, monkeypatch):
        """`> threshold`, not `>=`: a move of exactly the band is still noise."""
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("up", ev.DIRECTIONAL_NOISE_THRESHOLD))
        result = ev._evaluate_directional({}, {"metric": "hrv", "condition": "up"}, {}, TODAY)
        assert (result["status"], result["beats_null"]) == ("refuted", False)

    def test_a_move_just_past_the_noise_threshold_confirms(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("up", ev.DIRECTIONAL_NOISE_THRESHOLD + 1e-6))
        result = ev._evaluate_directional({}, {"metric": "hrv", "condition": "up"}, {}, TODAY)
        assert (result["status"], result["beats_null"]) == ("confirmed", True)

    def test_a_confirmed_direction_publishes_the_slope_as_its_measurement(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("down", -0.4))
        result = ev._evaluate_directional({}, {"metric": "hrv", "condition": "down"}, {}, TODAY)
        assert result["actual_value"] == -0.4

    def test_a_predicted_direction_outside_the_vocabulary_is_undecidable(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("up", 0.5))
        result = ev._evaluate_directional({}, {"metric": "hrv", "condition": "sideways"}, {}, TODAY)
        assert result["status"] == "inconclusive"

    def test_the_predicted_direction_is_read_case_and_whitespace_insensitively(self, monkeypatch):
        monkeypatch.setattr(ev, "_get_ewma_trend", lambda *a, **k: ("up", 0.5))
        result = ev._evaluate_directional({}, {"metric": "hrv", "condition": "  UP  "}, {}, TODAY)
        assert result["status"] == "confirmed"


# ══════════════════════════════════════════════════════════════════════════════
# D. The trend engine
# ══════════════════════════════════════════════════════════════════════════════


class TestEwma:
    def test_the_ewma_of_a_flat_series_is_that_constant(self):
        assert ev._compute_ewma([10.0] * 9, ev.EWMA_DECAY) == pytest.approx(10.0)

    def test_the_ewma_weights_the_most_recent_observation_most_heavily(self):
        # Hand-derived for decay=0.87 over [1, 2]:
        #   weights = [(1-0.87)*0.87, (1-0.87)*1] = [0.1131, 0.13]
        #   ewma    = (0.1131*1 + 0.13*2) / 0.2431 = 0.3731 / 0.2431
        assert ev._compute_ewma([1, 2], 0.87) == pytest.approx(0.3731 / 0.2431)
        assert ev._compute_ewma([1, 2], 0.87) > 1.5  # pulled toward the recent value

    def test_the_ewma_of_an_empty_series_is_absent_not_zero(self):
        assert ev._compute_ewma([], ev.EWMA_DECAY) is None

    def test_a_degenerate_decay_yields_absence_rather_than_a_divide_by_zero(self):
        assert ev._compute_ewma([1, 2, 3], 1.0) is None


class TestEwmaTrend:
    """The whole 14-point series is seeded as real DATE# rows, so these exercise
    the read path (`_fetch_range` -> `_extract_metric_series`) too."""

    RISING = [50.0] * 7 + [60.0] * 7
    FALLING = [60.0] * 7 + [50.0] * 7
    DRIFTING = [50.0] * 7 + [50.4] * 7

    def test_a_rising_series_reads_up_with_the_hand_derived_slope(self, table):
        # prior EWMA over the first 7 (all 50.0) = 50.0; current EWMA over all 14
        # = 57.260820610094186 -> slope = (57.2608206... - 50)/50.
        daily_series("hrv", self.RISING, table=table)
        direction, slope = ev._get_ewma_trend("hrv", {}, TODAY)
        assert direction == "up"
        assert slope == pytest.approx((57.260820610094186 - 50.0) / 50.0)

    def test_a_falling_series_reads_down_with_a_negative_slope(self, table):
        daily_series("hrv", self.FALLING, table=table)
        direction, slope = ev._get_ewma_trend("hrv", {}, TODAY)
        assert direction == "down"
        assert slope == pytest.approx(-0.12101367683490322)

    def test_a_drift_inside_the_noise_band_reads_flat(self, table):
        # 50.0 -> 50.4 is a 0.58% EWMA move, well inside the 2% band.
        daily_series("hrv", self.DRIFTING, table=table)
        direction, slope = ev._get_ewma_trend("hrv", {}, TODAY)
        assert direction == "flat"
        assert abs(slope) < ev.DIRECTIONAL_NOISE_THRESHOLD

    def test_an_aggregate_suffixed_metric_trends_on_its_base_metric(self, table):
        daily_series("hrv", self.RISING, table=table)
        assert ev._get_ewma_trend("hrv_7day_avg", {}, TODAY)[0] == "up"

    def test_a_metric_with_no_source_has_no_trend_rather_than_a_default_one(self, table):
        assert ev._get_ewma_trend("vibes", {}, TODAY) == (None, None)

    def test_eight_observations_do_not_yield_a_trend(self, table):
        """Characterisation of the real floor: the prior EWMA is computed over
        `values[:len-7]`, which needs >= 2 entries, so 9 points are required."""
        daily_series("hrv", [50.0, 51, 52, 53, 54, 55, 56, 57], table=table)
        assert ev._get_ewma_trend("hrv", {}, TODAY) == (None, None)

    def test_nine_observations_do_yield_a_trend(self, table):
        daily_series("hrv", [50.0, 51, 52, 53, 54, 55, 56, 57, 58], table=table)
        assert ev._get_ewma_trend("hrv", {}, TODAY)[0] == "up"

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): _get_ewma_trend documents and guards a five-observation "
            "floor (`if len(values) < 5: return None, None`) but the prior-EWMA branch below it needs "
            "`len(values) - 7 >= 2`, so 5-8 observations always return (None, None). Any directional "
            "forecast on a sparse metric (withings weigh-ins, dexa) is graded 'insufficient data' "
            "while the code claims five points are enough."
        ),
    )
    def test_the_documented_five_observation_floor_is_the_real_floor(self, table):
        daily_series("hrv", [50.0, 52, 54, 56, 58], table=table)
        assert ev._get_ewma_trend("hrv", {}, TODAY)[0] is not None


# ══════════════════════════════════════════════════════════════════════════════
# E. Metric resolution
# ══════════════════════════════════════════════════════════════════════════════


class TestMetricResolution:
    def test_a_raw_metric_resolves_to_its_most_recent_reading(self, table):
        daily_series("hrv", [40.0, 45.0, 55.0], table=table)
        assert ev._resolve_metric_value("hrv", {}, TODAY) == 55.0

    def test_a_reading_older_than_the_lookback_window_does_not_resolve(self, table):
        seed_metric(table, "whoop", "hrv", {days_before(10): 55.0})
        assert ev._resolve_metric_value("hrv", {}, TODAY) is None

    def test_a_seven_day_average_is_the_mean_of_the_last_seven_readings(self, table):
        # The window is end-7 .. end (8 days); `series[-7:]` keeps the last seven,
        # so 1..8 averages to (2+3+4+5+6+7+8)/7 = 35/7 = 5.0.
        daily_series("hrv", [1, 2, 3, 4, 5, 6, 7, 8], table=table)
        assert ev._resolve_metric_value("hrv_7day_avg", {}, TODAY) == pytest.approx(5.0)

    def test_an_average_over_an_empty_window_is_absent_not_zero(self, table):
        assert ev._resolve_metric_value("hrv_30day_avg", {}, TODAY) is None

    def test_an_average_of_an_unmapped_metric_is_absent(self, table):
        assert ev._compute_metric_average("vibes", {}, TODAY, 7) is None

    def test_every_gradable_metric_maps_to_a_partition_the_platform_actually_writes(self):
        """Derived from the source registry: a metric pointing at a partition that
        does not exist grades 'no data' forever (the #813 failure mode)."""
        known = set(SOURCE_REGISTRY) | set(EXTRA_QUERYABLE_PARTITIONS)
        assert set(METRIC_SOURCES.values()) - known == set()


class TestSeriesExtraction:
    def test_an_absent_value_is_dropped_rather_than_scored_as_zero(self):
        records = [{"date": "2026-05-01", "hrv": 50}, {"date": "2026-05-02"}, {"date": "2026-05-03", "hrv": None}]
        assert ev._extract_metric_series(records, "hrv") == [("2026-05-01", 50.0)]

    def test_a_non_numeric_reading_is_treated_as_absent(self):
        assert ev._extract_metric_series([{"date": "2026-05-01", "hrv": "n/a"}], "hrv") == []

    def test_a_numeric_string_reading_is_still_a_reading(self):
        assert ev._extract_metric_series([{"date": "2026-05-01", "hrv": "50.5"}], "hrv") == [("2026-05-01", 50.5)]

    def test_the_date_falls_back_to_the_sort_key_when_the_field_is_missing(self):
        assert ev._extract_metric_series([{"sk": "DATE#2026-05-01", "hrv": 50}], "hrv") == [("2026-05-01", 50.0)]

    def test_a_row_with_neither_a_date_nor_a_sort_key_is_dropped(self):
        assert ev._extract_metric_series([{"hrv": 50}], "hrv") == []

    def test_the_series_is_chronological_regardless_of_query_order(self):
        records = [{"date": "2026-05-03", "hrv": 3}, {"date": "2026-05-01", "hrv": 1}, {"date": "2026-05-02", "hrv": 2}]
        assert [v for _d, v in ev._extract_metric_series(records, "hrv")] == [1.0, 2.0, 3.0]

    def test_safe_float_returns_the_caller_default_for_an_unreadable_field(self):
        assert ev._safe_float({"hrv": "abc"}, "hrv", default=-1) == -1
        assert ev._safe_float({}, "hrv") is None
        assert ev._safe_float(None, "hrv") is None


class TestSourceCache:
    def test_a_source_window_is_fetched_once_per_run(self, table):
        daily_series("hrv", [50.0], table=table)
        cache = {}
        ev._get_source_data("whoop", cache, TODAY, lookback_days=7)
        ev._get_source_data("whoop", cache, TODAY, lookback_days=7)
        assert len([q for q in table.queries if ":s" in q["ExpressionAttributeValues"]]) == 1

    def test_the_cache_key_ignores_the_end_date_so_a_shared_cache_is_date_blind(self, table):
        """Documented trap (#534 audit): the key is `{source}:{lookback}` with no
        date component, so a cache reused across two as-of dates serves the first
        date's window for both. `_detect_milestone_event` passes a fresh cache per
        call precisely because of this; any new caller must do the same."""
        daily_series("hrv", [50.0], table=table)
        cache = {}
        today_value = ev._resolve_metric_value("hrv", cache, TODAY)
        yesterday_value = ev._resolve_metric_value("hrv", cache, days_before(9))
        assert today_value == yesterday_value == 50.0


# ══════════════════════════════════════════════════════════════════════════════
# F. Conditional predictions
# ══════════════════════════════════════════════════════════════════════════════


SPEC_CONDITIONAL = {
    "type": "conditional",
    "condition_metric": "steps",
    "condition_threshold": 8000,
    "condition_condition": "gte",
    "metric": "hrv",
    "condition": "gt",
    "threshold": 50,
}


class TestConditionalPredictions:
    def test_a_conditional_waits_while_its_precondition_has_no_data(self, table):
        result = ev._evaluate_conditional({}, SPEC_CONDITIONAL, {}, TODAY)
        assert result["status"] == "pending"
        assert "steps" in result["reason"]

    def test_a_conditional_waits_while_its_precondition_is_unmet(self, table):
        daily_series("steps", [3000], source="apple_health", table=table)
        result = ev._evaluate_conditional({}, SPEC_CONDITIONAL, {}, TODAY)
        assert result["status"] == "pending"
        assert "does not satisfy" in result["reason"]

    def test_a_conditional_grades_its_outcome_once_the_precondition_holds(self, table):
        daily_series("steps", [9000], source="apple_health", table=table)
        daily_series("hrv", [60.0], table=table)
        result = ev._evaluate_conditional({}, SPEC_CONDITIONAL, {}, TODAY)
        assert result["status"] == "confirmed"
        assert result["reason"].startswith("Precondition met (steps=9000")

    def test_a_conditional_whose_outcome_metric_is_missing_is_undecidable_not_refuted(self, table):
        daily_series("steps", [9000], source="apple_health", table=table)
        result = ev._evaluate_conditional({}, SPEC_CONDITIONAL, {}, TODAY)
        assert result["status"] == "inconclusive"

    def test_a_malformed_conditional_is_skipped_rather_than_graded(self, table):
        assert ev._evaluate_conditional({}, {"type": "conditional", "metric": "hrv"}, {}, TODAY) is None
        assert ev._evaluate_conditional({}, {**SPEC_CONDITIONAL, "condition_threshold": None}, {}, TODAY) is None

    def test_a_waiting_conditional_is_never_written_back(self, table):
        pred = prediction(evaluation=SPEC_CONDITIONAL, subdomain="training", created_date=days_before(30))
        evaluations, stats = ev._evaluate_all([pred], TODAY)
        assert (evaluations, stats["pending"]) == ([], 1)
        assert table.updates == []

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): _evaluate_all applies _check_expiry only to the "
            "'inconclusive' branch, so a conditional whose precondition never materialises stays "
            "'pending' forever — past 1x window, past the 2x EXPIRY_MULTIPLIER, indefinitely. It is "
            "re-fetched and re-evaluated every day, never decided and never retired, so it inflates "
            "GradableCount forever while ADR-105's 'every forecast graded' is silently unmet."
        ),
    )
    def test_a_conditional_whose_precondition_never_arrives_is_eventually_retired(self, table):
        pred = prediction(evaluation=SPEC_CONDITIONAL, subdomain="training", created_date=days_before(200))
        evaluations, _ = ev._evaluate_all([pred], TODAY)
        assert [e["status"] for e in evaluations] == ["expired"]


# ══════════════════════════════════════════════════════════════════════════════
# G. What is scanned, what is re-graded (idempotency), phase discipline
# ══════════════════════════════════════════════════════════════════════════════


class TestPredictionScan:
    def test_every_operational_coach_partition_and_the_diary_claims_are_scanned(self, table):
        """Derived from the persona registry — a ninth coach must not be able to
        vanish from grading without this failing."""
        ev._fetch_predictions()
        scanned = {q["ExpressionAttributeValues"][":pk"] for q in table.queries}
        expected = {f"COACH#{c}" for c in OPERATIONAL_COACH_IDS} | {ev.DIARY_CLAIMS_PK}
        assert scanned == expected

    def test_the_evaluator_roster_is_the_canonical_operational_roster(self):
        """Order is display-only and differs between the two lists; membership is
        the contract — a coach absent here is a coach whose calls are never graded."""
        assert set(ev.COACH_IDS) == set(OPERATIONAL_COACH_IDS)

    @pytest.mark.parametrize("status", sorted(ev.EVALUABLE_STATUSES))
    def test_an_open_prediction_is_picked_up_for_grading(self, table, status):
        seed(table, prediction(status=status))
        assert len(ev._fetch_predictions()) == 1

    @pytest.mark.parametrize("status", ["confirmed", "refuted", "expired"])
    def test_an_already_decided_prediction_is_never_re_graded(self, table, status):
        """Idempotency: a second run must not double-count a coach's hit or miss."""
        seed(table, prediction(status=status))
        assert ev._fetch_predictions() == []

    def test_a_qualitative_prediction_is_never_machine_graded(self, table):
        seed(table, prediction(evaluation={"type": "qualitative", "metric": "mood"}))
        assert ev._fetch_predictions() == []

    def test_a_duplicate_grader_victim_is_reclaimed_for_one_real_pass(self, table):
        seed(table, prediction(status="inconclusive", outcome_notes=json.dumps({"beats_null": False})))
        assert len(ev._fetch_predictions()) == 1

    def test_a_record_this_evaluator_already_decided_is_not_reclaimed_again(self, table):
        seed(table, prediction(status="inconclusive", outcome_notes=json.dumps({"algo_version": ev.ALGO_VERSION})))
        assert ev._fetch_predictions() == []

    def test_the_scan_follows_pagination_to_the_last_page(self, table):
        table.pages = [
            {"Items": [prediction(pred_id="a")], "LastEvaluatedKey": {"pk": "COACH#sleep_coach", "sk": "PREDICTION#a"}},
            {"Items": [prediction(pred_id="b")]},
        ] + [{"Items": []}] * len(OPERATIONAL_COACH_IDS)
        assert len(ev._fetch_predictions()) == 2

    def test_one_unreadable_partition_does_not_lose_the_other_coaches_forecasts(self, table):
        table.error_pks.add("COACH#sleep_coach")
        seed(table, prediction(coach_id="mind_coach", pred_id="p2"))
        assert [p["prediction_id"] for p in ev._fetch_predictions()] == ["p2"]

    def test_prediction_reads_exclude_other_experiment_cycles(self, table):
        ev._fetch_predictions()
        assert all("FilterExpression" in q for q in table.queries)


class TestSourceReads:
    def test_source_reads_exclude_other_experiment_cycles(self, table):
        ev._fetch_range("whoop", days_before(7), TODAY)
        assert "FilterExpression" in table.queries[-1]

    def test_a_range_read_is_bounded_by_the_requested_dates(self, table):
        seed_metric(table, "whoop", "hrv", {days_before(10): 1, days_before(3): 2, TODAY: 3})
        got = ev._fetch_range("whoop", days_before(7), TODAY)
        assert [r["hrv"] for r in got] == [2.0, 3.0]

    def test_a_range_read_returns_floats_not_decimals(self, table):
        seed_metric(table, "whoop", "hrv", {TODAY: "55.5"})
        assert not isinstance(ev._fetch_range("whoop", days_before(7), TODAY)[0]["hrv"], Decimal)

    def test_a_range_read_follows_pagination_to_the_last_page(self, table):
        row = {"pk": ev.USER_PREFIX + "whoop", "sk": f"DATE#{TODAY}", "hrv": Decimal("50")}
        table.pages = [{"Items": [row], "LastEvaluatedKey": {"pk": "x", "sk": "y"}}, {"Items": [row]}]
        assert len(ev._fetch_range("whoop", days_before(7), TODAY)) == 2

    def test_a_failed_source_read_yields_an_empty_window_rather_than_a_crash(self, table):
        table.query_error = RuntimeError("throttled")
        assert ev._fetch_range("whoop", days_before(7), TODAY) == []

    def test_an_empty_window_grades_undecidable_rather_than_refuted(self, table):
        """The fail-soft read above must never be laundered into a miss."""
        table.query_error = RuntimeError("throttled")
        result = ev._evaluate_machine({}, {"metric": "hrv", "condition": "gt", "threshold": 50}, {}, TODAY)
        assert result["status"] == "inconclusive"


# ══════════════════════════════════════════════════════════════════════════════
# H. Track-record arithmetic — the published posterior
# ══════════════════════════════════════════════════════════════════════════════


class TestBayesianPosterior:
    def _row(self, table):
        return confidence_rows(table)[-1]

    def test_a_success_adds_one_to_alpha_from_the_uninformed_prior(self, table):
        ev._update_bayesian_confidence("sleep_coach", "sleep", "success")
        row = self._row(table)
        assert (float(row["alpha"]), float(row["beta_param"])) == (2.0, 1.0)
        assert float(row["mean_confidence"]) == pytest.approx(2 / 3)

    def test_a_failure_adds_one_to_beta_from_the_uninformed_prior(self, table):
        ev._update_bayesian_confidence("sleep_coach", "sleep", "failure")
        row = self._row(table)
        assert (float(row["alpha"]), float(row["beta_param"])) == (1.0, 2.0)
        assert float(row["mean_confidence"]) == pytest.approx(1 / 3)

    def test_an_unrecognised_verdict_moves_neither_parameter(self, table):
        ev._update_bayesian_confidence("sleep_coach", "sleep", "sort_of")
        row = self._row(table)
        assert (float(row["alpha"]), float(row["beta_param"]), float(row["mean_confidence"])) == (1.0, 1.0, 0.5)

    def test_an_existing_posterior_is_extended_not_restarted(self, table):
        seed(table, stored_posterior(alpha=5, beta_param=3))
        ev._update_bayesian_confidence("sleep_coach", "sleep", "success")
        row = self._row(table)
        assert (float(row["alpha"]), float(row["beta_param"])) == (6.0, 3.0)

    def test_the_published_sample_size_counts_only_graded_outcomes(self, table):
        # Beta(6,3) over the Beta(1,1) prior == 7 graded observations.
        seed(table, stored_posterior(alpha=5, beta_param=3))
        ev._update_bayesian_confidence("sleep_coach", "sleep", "success")
        assert int(self._row(table)["sample_size"]) == 7

    def test_conversational_pseudo_observations_are_excluded_from_the_published_n(self, table):
        """#1787: the same Beta carries #1481's fractional conversation weight;
        publishing it as graded evidence would overstate the track record."""
        seed(table, stored_posterior(alpha=5, beta_param=3, conversation_alpha=2, conversation_beta=1))
        ev._update_bayesian_confidence("sleep_coach", "sleep", "success")
        assert int(self._row(table)["sample_size"]) == 4  # (6+3-2) - 3

    def test_the_conversational_accumulators_survive_a_data_side_update(self, table):
        seed(table, stored_posterior(alpha=5, beta_param=3, conversation_alpha=2, conversation_beta=1))
        ev._update_bayesian_confidence("sleep_coach", "sleep", "success")
        row = self._row(table)
        assert (row["conversation_alpha"], row["conversation_beta"]) == (Decimal("2"), Decimal("1"))

    def test_the_published_sample_size_is_never_negative(self, table):
        """A conversation-only posterior would otherwise publish n = -1."""
        seed(table, stored_posterior(alpha=1.5, beta_param=1, conversation_alpha=1.5))
        ev._update_bayesian_confidence("sleep_coach", "sleep", "sort_of")
        assert int(self._row(table)["sample_size"]) >= 0

    def test_a_tombstoned_prior_cycle_posterior_is_not_inherited(self, table):
        """ADR-077: a previous cycle's Beta counts must not seed the new one."""
        seed(table, stored_posterior(alpha=50, beta_param=4, tombstone=True))
        ev._update_bayesian_confidence("sleep_coach", "sleep", "success")
        row = self._row(table)
        assert (float(row["alpha"]), float(row["beta_param"])) == (2.0, 1.0)
        assert "tombstone" not in row  # the full-item put must not resurrect it

    def test_a_prior_cycle_row_carrying_only_a_phase_stamp_is_still_inherited(self, table):
        """Characterisation of the sanctioned exemption in
        tests/test_singleton_tombstone_guards.py: this reader checks `tombstone`
        explicitly but not `phase`, unlike `_habit_scores_for` in the same module.
        A phase-stamped row that escaped the reset wipe keeps its counts."""
        seed(table, stored_posterior(alpha=50, beta_param=4, phase="a_previous_cycle"))
        ev._update_bayesian_confidence("sleep_coach", "sleep", "success")
        assert float(self._row(table)["alpha"]) == 51.0

    def test_every_stored_posterior_number_is_a_decimal(self, table):
        ev._update_bayesian_confidence("sleep_coach", "sleep", "success")
        row = self._row(table)
        for field in ("alpha", "beta_param", "mean_confidence", "sample_size"):
            assert isinstance(row[field], Decimal), field

    def test_the_posterior_declares_the_data_channel_and_its_experiment_generation(self, table):
        ev._update_bayesian_confidence("sleep_coach", "sleep", "success")
        row = self._row(table)
        assert row["source"] == "data"  # vs "conversation" (ADR-141)
        assert row["phase"] == EXPERIMENT_PHASE_CURRENT

    def test_a_posterior_write_failure_never_sinks_the_run(self, table):
        table.put_error = RuntimeError("throttled")
        ev._update_bayesian_confidence("sleep_coach", "sleep", "success")  # must not raise

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): asymmetric Bayesian credit on the machine path. "
            "_evaluate_machine sets beats_null=True only when eval_spec['null_hypothesis'] is "
            "truthy, and NO writer in the repo ever emits one (coach_state_updater."
            "_build_prediction_eval_spec hard-codes null_hypothesis=None; diary_claims omits the "
            "key), so a confirmed thresholded call yields bayesian_update=None while every refuted "
            "call yields 'failure'. Beta(alpha,beta) can then only move toward beta and the "
            "published mean_confidence can only fall. (The `beats_null_if` branch is also dead: all "
            "three arms assign True.)"
        ),
    )
    def test_a_confirmed_call_credits_alpha_the_way_a_refuted_call_debits_beta(self, table):
        daily_series("hrv", [60.0], table=table)
        spec = {"type": "machine", "metric": "hrv", "condition": "gt", "threshold": 50}
        evaluations, _ = ev._evaluate_all([prediction(evaluation=spec, subdomain="hrv", created_date=days_before(30))], TODAY)
        assert evaluations[0]["status"] == "confirmed"
        assert evaluations[0]["bayesian_update"] == "success"


class TestVerdictRouting:
    def test_a_confirmed_directional_call_credits_the_coachs_posterior(self, table):
        daily_series("hrv", TestEwmaTrend.RISING, table=table)
        spec = {"type": "directional", "metric": "hrv", "condition": "up"}
        evaluations, stats = ev._evaluate_all([prediction(evaluation=spec, subdomain="hrv", created_date=days_before(30))], TODAY)
        assert (evaluations[0]["status"], evaluations[0]["bayesian_update"]) == ("confirmed", "success")
        assert float(confidence_rows(table)[-1]["alpha"]) == 2.0
        assert stats["confirmed"] == 1

    def test_a_refuted_directional_call_debits_the_coachs_posterior(self, table):
        daily_series("hrv", TestEwmaTrend.FALLING, table=table)
        spec = {"type": "directional", "metric": "hrv", "condition": "up"}
        evaluations, stats = ev._evaluate_all([prediction(evaluation=spec, subdomain="hrv", created_date=days_before(30))], TODAY)
        assert (evaluations[0]["status"], evaluations[0]["bayesian_update"]) == ("refuted", "failure")
        assert float(confidence_rows(table)[-1]["beta_param"]) == 2.0
        assert stats["refuted"] == 1

    def test_a_verdict_with_no_subdomain_still_lands_in_the_public_learning_trail(self, table):
        daily_series("hrv", TestEwmaTrend.FALLING, table=table)
        spec = {"type": "directional", "metric": "hrv", "condition": "up"}
        pred = prediction(evaluation=spec, subdomain="", created_date=days_before(30))
        ev._evaluate_all([pred], TODAY)
        assert confidence_rows(table) == []  # nowhere to file the posterior
        assert len(learning_rows(table)) == 1  # but the miss is still published

    def test_a_null_threshold_legacy_spec_is_rescued_onto_the_directional_path(self, table):
        """#813: a pre-C-3 machine spec has threshold=None + a constant 'gt'; the
        claim text is the only honest direction source."""
        daily_series("hrv", TestEwmaTrend.RISING, table=table)
        spec = {"type": "machine", "metric": "hrv", "condition": "gt", "threshold": None}
        result = ev._evaluate_machine({"claim_natural": "HRV will improve"}, spec, {}, TODAY)
        assert result["status"] == "confirmed"
        assert result["reason"].startswith("[null-threshold machine spec re-routed to directional]")

    def test_a_null_threshold_spec_with_no_inferable_direction_stays_undecidable(self, table):
        spec = {"type": "machine", "metric": "hrv", "condition": "gt", "threshold": None}
        result = ev._evaluate_machine({"claim_natural": "something will happen"}, spec, {}, TODAY)
        assert (result["status"], result["beats_null"]) == ("inconclusive", False)


# ══════════════════════════════════════════════════════════════════════════════
# I. The written record — diary claims, idempotency, Decimals, fail-soft
# ══════════════════════════════════════════════════════════════════════════════


class TestWrittenRecord:
    def test_a_graded_prediction_is_written_back_with_its_verdict_and_date(self, table):
        daily_series("hrv", TestEwmaTrend.FALLING, table=table)
        spec = {"type": "directional", "metric": "hrv", "condition": "up"}
        ev._evaluate_all([prediction(evaluation=spec, subdomain="hrv", created_date=days_before(30))], TODAY)
        stored = table.items[("COACH#sleep_coach", "PREDICTION#pred_1")]
        assert (stored["status"], stored["outcome"], stored["outcome_date"]) == ("refuted", "refuted", TODAY)

    def test_the_write_back_stamps_the_algo_version_so_a_regrade_is_one_way(self, table):
        """The #813 reclaim discriminator: without this the record could be
        reclaimed and re-graded on every future run."""
        ev._update_prediction_status(prediction(), {"status": "inconclusive", "evaluated_date": TODAY, "prediction_id": "p1"})
        notes = json.loads(table.updates[-1]["values"][":notes"])
        assert notes["algo_version"] == ev.ALGO_VERSION

    def test_the_write_back_falls_back_to_the_composite_key_when_the_record_lacks_one(self, table):
        pred = {"coach_id": "mind_coach", "prediction_id": "p9"}
        ev._update_prediction_status(pred, {"status": "refuted", "evaluated_date": TODAY})
        assert table.updates[-1]["Key"] == {"pk": "COACH#mind_coach", "sk": "PREDICTION#p9"}

    def test_a_write_back_failure_never_sinks_the_run(self, table):
        table.update_error = RuntimeError("throttled")
        ev._update_prediction_status(prediction(), {"status": "refuted", "evaluated_date": TODAY})  # must not raise

    def test_the_learning_row_is_keyed_deterministically_so_a_regrade_overwrites(self, table):
        evaluation = {"prediction_id": "pred_1", "status": "refuted", "actual_value": -0.1}
        ev._write_learning_record("sleep_coach", TODAY, evaluation)
        ev._write_learning_record("sleep_coach", TODAY, evaluation)
        assert len({(r["pk"], r["sk"]) for r in learning_rows(table)}) == 1

    def test_the_learning_row_declares_the_data_channel_and_its_experiment_generation(self, table):
        ev._write_learning_record("sleep_coach", TODAY, {"prediction_id": "p1", "status": "refuted"})
        row = learning_rows(table)[0]
        assert row["channel"] == "data"  # ADR-141: not a private conversation learning
        assert row["phase"] == EXPERIMENT_PHASE_CURRENT

    def test_numeric_learning_fields_are_stored_as_decimals(self, table):
        ev._write_learning_record("sleep_coach", TODAY, {"prediction_id": "p1", "actual_value": 1.5, "threshold": 50})
        row = learning_rows(table)[0]
        assert isinstance(row["actual_value"], Decimal) and isinstance(row["threshold"], Decimal)

    def test_a_learning_write_failure_never_sinks_the_run(self, table):
        table.put_error = RuntimeError("throttled")
        ev._write_learning_record("sleep_coach", TODAY, {"prediction_id": "p1", "status": "refuted"})  # must not raise

    def test_a_subjects_diary_claim_never_writes_a_coach_learning_row(self, table):
        """#1841: a LEARNING# row on a coachless COACH# partition would be counted
        by every hit-rate surface that scans that prefix."""
        ev._write_learning_record("", TODAY, {"prediction_id": "claim_1", "status": "refuted"})
        assert learning_rows(table) == []

    def test_a_subjects_diary_claim_is_graded_but_moves_no_coachs_posterior(self, table):
        daily_series("hrv", TestEwmaTrend.FALLING, table=table)
        spec = {"type": "directional", "metric": "hrv", "condition": "up"}
        claim = prediction(coach_id="", pred_id="claim_1", evaluation=spec, subdomain="hrv", created_date=days_before(30))
        evaluations, _ = ev._evaluate_all([claim], TODAY)
        assert evaluations[0]["status"] == "refuted"
        assert (confidence_rows(table), learning_rows(table)) == ([], [])

    def test_a_subjects_refuted_claim_never_triggers_a_coachs_stance_refresh(self):
        assert ev._detect_prediction_miss_events([{"coach_id": "", "status": "refuted", "metric": "hrv"}]) == {}

    def test_the_learning_slug_is_url_safe_and_bounded(self):
        slug = ev._slugify("Pred ABC_123!! — Confirmed?")
        assert slug == "pred-abc-123-confirmed"
        assert len(ev._slugify("x" * 200)) <= 60


class TestDecimalCoercion:
    def test_a_reading_is_rounded_to_six_places_before_storage(self):
        assert ev._scalar_to_decimal(1.23456789) == Decimal("1.234568")

    def test_a_numeric_string_is_accepted(self):
        assert ev._scalar_to_decimal("3") == Decimal("3.0")

    def test_absence_is_preserved_as_absence(self):
        assert ev._scalar_to_decimal(None) is None

    def test_an_unparseable_value_becomes_absence_rather_than_zero(self):
        assert ev._scalar_to_decimal("not a number") is None
        assert ev._scalar_to_decimal({"a": 1}) is None


# ══════════════════════════════════════════════════════════════════════════════
# J. Commitments (#532) — the same honesty rules for follow-through
# ══════════════════════════════════════════════════════════════════════════════


def commitment(**extra):
    base = {
        "pk": "COACH#training_coach",
        "sk": "COMMITMENT#c1",
        "commitment_id": "c1",
        "coach_id": "training_coach",
        "created_date": days_before(30),
        "window_days": 7,
        "status": "pending",
    }
    base.update(extra)
    return base


METRIC_CHECK = {"metric": "hrv", "direction": "up"}


class TestCommitments:
    def test_only_pending_commitments_are_collected(self, table):
        seed(table, commitment(), commitment(sk="COMMITMENT#c2", commitment_id="c2", status="kept"))
        assert [c["commitment_id"] for c in ev._fetch_commitments()] == ["c1"]

    def test_commitment_reads_exclude_other_experiment_cycles(self, table):
        ev._fetch_commitments()
        assert all("FilterExpression" in q for q in table.queries)

    def test_an_unreadable_coach_partition_does_not_lose_the_others(self, table):
        table.error_pks.add("COACH#sleep_coach")
        seed(table, commitment())
        assert len(ev._fetch_commitments()) == 1

    def test_a_commitment_is_not_graded_before_its_window_closes(self, table):
        stats = ev._evaluate_commitments([commitment(created_date=days_before(3))], TODAY, {})
        assert stats == {"kept": 0, "broken": 0, "unresolved": 0, "pending": 1}
        assert table.updates == []

    def test_a_metric_backed_commitment_the_data_supports_is_kept(self, table):
        daily_series("hrv", TestEwmaTrend.RISING, table=table)
        stats = ev._evaluate_commitments([commitment(action_check=METRIC_CHECK)], TODAY, {})
        assert stats["kept"] == 1
        assert table.items[("COACH#training_coach", "COMMITMENT#c1")]["status"] == "kept"

    def test_a_metric_backed_commitment_the_data_contradicts_is_broken(self, table):
        daily_series("hrv", TestEwmaTrend.FALLING, table=table)
        stats = ev._evaluate_commitments([commitment(action_check=METRIC_CHECK)], TODAY, {})
        assert stats["broken"] == 1

    def test_a_commitment_whose_metric_never_moved_is_broken_not_excused(self, table):
        """#801: 'nothing happened' is evidence against the commitment."""
        daily_series("hrv", TestEwmaTrend.DRIFTING, table=table)
        assert ev._evaluate_commitments([commitment(action_check=METRIC_CHECK)], TODAY, {})["broken"] == 1

    def test_a_metric_backed_commitment_with_no_data_waits_until_its_expiry(self, table):
        stats = ev._evaluate_commitments([commitment(created_date=days_before(10), action_check=METRIC_CHECK)], TODAY, {})
        assert stats == {"kept": 0, "broken": 0, "unresolved": 0, "pending": 1}

    def test_a_metric_backed_commitment_with_no_data_is_unresolved_past_twice_its_window(self, table):
        stats = ev._evaluate_commitments([commitment(created_date=days_before(30), action_check=METRIC_CHECK)], TODAY, {})
        assert stats["unresolved"] == 1
        assert table.items[("COACH#training_coach", "COMMITMENT#c1")]["outcome"] == "unresolved"

    def test_a_commitment_with_no_machine_check_waits_for_the_coach_then_expires(self, table):
        assert ev._evaluate_commitments([commitment(created_date=days_before(10))], TODAY, {})["pending"] == 1
        assert ev._evaluate_commitments([commitment(created_date=days_before(30))], TODAY, {})["unresolved"] == 1

    def test_a_commitment_with_an_unparseable_creation_date_is_skipped_not_graded(self, table):
        stats = ev._evaluate_commitments([commitment(created_date=None)], TODAY, {})
        assert stats == {"kept": 0, "broken": 0, "unresolved": 0, "pending": 0}

    def test_the_commitment_outcome_carries_the_algo_version(self, table):
        ev._update_commitment_status(commitment(), "kept", "because", TODAY)
        assert json.loads(table.updates[-1]["values"][":notes"])["algo_version"] == ev.ALGO_VERSION

    def test_a_commitment_write_failure_never_sinks_the_run(self, table):
        table.update_error = RuntimeError("throttled")
        ev._update_commitment_status(commitment(), "kept", "because", TODAY)  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# K. #727 scientific liveness — a stall must be visible
# ══════════════════════════════════════════════════════════════════════════════


class TestGradingLiveness:
    def test_decided_counts_only_confirmed_and_refuted(self, table, env):
        stats = {"confirmed": 2, "refuted": 1, "inconclusive": 9, "expired": 4, "pending": 7}
        payload = ev.emit_grading_liveness(stats, gradable_count=23, today_str=TODAY)
        assert payload["decided_count"] == 3
        assert env.cw.metric("DecidedCount") == 3.0

    def test_the_gradable_floor_is_reported_even_when_nothing_decided(self, table, env):
        payload = ev.emit_grading_liveness({}, gradable_count=40, today_str=TODAY)
        assert (payload["decided_count"], payload["gradable_count"]) == (0, 40)
        assert env.cw.metric("GradableCount") == 40.0

    def test_a_run_that_decided_nothing_does_not_restamp_the_marker(self, table):
        seed(table, {"pk": ev._LAST_DECIDED_PK, "sk": ev._LAST_DECIDED_SK, "date": days_before(9)})
        payload = ev.emit_grading_liveness({"confirmed": 0, "refuted": 0}, 5, TODAY)
        assert payload["days_since_last_decided"] == 9
        assert table.puts == []

    def test_a_run_that_decided_something_resets_the_gauge_to_zero(self, table):
        payload = ev.emit_grading_liveness({"confirmed": 1, "refuted": 0}, 5, TODAY)
        assert payload["days_since_last_decided"] == 0
        assert table.items[(ev._LAST_DECIDED_PK, ev._LAST_DECIDED_SK)]["date"] == TODAY

    def test_never_having_decided_emits_the_sentinel_not_a_comforting_zero(self, table):
        payload = ev.emit_grading_liveness({}, 0, TODAY)
        assert payload["days_since_last_decided"] == ev._NEVER_DECIDED_DAYS

    def test_an_unparseable_marker_reads_as_never_decided(self, table):
        seed(table, {"pk": ev._LAST_DECIDED_PK, "sk": ev._LAST_DECIDED_SK, "date": "whenever"})
        assert ev.emit_grading_liveness({}, 0, TODAY)["days_since_last_decided"] == ev._NEVER_DECIDED_DAYS

    def test_the_gauge_is_never_negative(self):
        assert ev._days_since(TODAY, days_before(-5)) == 0

    def test_an_unreadable_marker_does_not_sink_the_run(self, table):
        table.get_error = RuntimeError("throttled")
        assert ev.emit_grading_liveness({}, 0, TODAY)["days_since_last_decided"] == ev._NEVER_DECIDED_DAYS

    def test_an_unwritable_marker_does_not_sink_the_run(self, table):
        table.put_error = RuntimeError("throttled")
        assert ev.emit_grading_liveness({"confirmed": 1}, 1, TODAY)["days_since_last_decided"] == 0

    def test_a_metric_emit_failure_never_sinks_the_run(self, table, env):
        env.cw.error = RuntimeError("cloudwatch down")
        assert ev.emit_grading_liveness({"confirmed": 1}, 1, TODAY)["decided_count"] == 1

    def test_the_liveness_marker_is_read_by_exact_key_not_a_phase_filtered_query(self, table):
        """Operational system-state, deliberately outside the experiment cycle —
        a reset must not make grading look permanently stalled."""
        ev.emit_grading_liveness({}, 0, TODAY)
        assert {"pk": ev._LAST_DECIDED_PK, "sk": ev._LAST_DECIDED_SK} in table.gets


# ══════════════════════════════════════════════════════════════════════════════
# L. The #534 stance-event side-lane must never endanger grading
# ══════════════════════════════════════════════════════════════════════════════


class TestStanceEventFailSoft:
    def test_an_unreadable_habit_row_yields_no_relapse_event(self, table):
        table.get_error = RuntimeError("throttled")
        assert ev._habit_scores_for(TODAY) == {}
        assert ev._detect_relapse_event(TODAY, YESTERDAY) is None

    def test_a_sick_day_check_failure_yields_no_event(self, table, monkeypatch):
        monkeypatch.setattr(ev, "check_sick_day", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert ev._detect_sick_day_event(TODAY, YESTERDAY) is None

    def test_a_milestone_check_failure_yields_no_event(self, table, monkeypatch):
        monkeypatch.setattr(ev, "_resolve_metric_value", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        assert ev._detect_milestone_event(TODAY, YESTERDAY) is None

    def test_an_unreadable_cap_counter_does_not_block_the_run(self, table):
        table.get_error = RuntimeError("throttled")
        assert ev._event_refresh_count_today(TODAY) == 0

    def test_an_invoke_failure_is_reported_not_raised(self, table, env):
        env.lam.error = RuntimeError("lambda down")
        out = ev._fire_event_stance_refreshes({"mind_coach": {"type": "vice_relapse", "detail": "x"}}, TODAY)
        assert (out["detected"], out["fired"]) == (1, 0)


# ══════════════════════════════════════════════════════════════════════════════
# M. The handler — one daily pass, everything else fail-soft around it
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def quiet_docket(monkeypatch):
    monkeypatch.setattr(_dispute_docket, "resolve_due", lambda today_str: {"resolved": 0})


class TestHandler:
    def _due_directional(self, table, values):
        daily_series("hrv", values, table=table)
        seed(
            table,
            prediction(
                pred_id="p1",
                subdomain="hrv",
                created_date=days_before(30),
                evaluation={"type": "directional", "metric": "hrv", "condition": "up"},
            ),
        )

    def test_the_handler_publishes_what_it_found_and_what_it_decided(self, table, quiet_docket):
        self._due_directional(table, TestEwmaTrend.RISING)
        out = ev.lambda_handler({}, None)
        assert out["statusCode"] == 200
        assert (out["predictions_found"], out["predictions_evaluated"]) == (1, 1)
        assert out["stats"]["confirmed"] == 1
        assert out["liveness"]["decided_count"] == 1
        assert out["algo_version"] == ev.ALGO_VERSION

    def test_the_handler_grades_against_the_current_date(self, table, quiet_docket):
        assert ev.lambda_handler({}, None)["date"] == TODAY

    def test_a_run_with_nothing_open_still_emits_the_liveness_heartbeat(self, table, quiet_docket):
        """A silent run is exactly the stall #727 exists to make visible."""
        out = ev.lambda_handler({}, None)
        assert out["stats"] == {}
        assert out["liveness"] == {"decided_count": 0, "gradable_count": 0, "days_since_last_decided": ev._NEVER_DECIDED_DAYS}

    def test_commitments_are_graded_even_on_a_day_with_no_open_predictions(self, table, quiet_docket):
        daily_series("hrv", TestEwmaTrend.RISING, table=table)
        seed(table, commitment(action_check=METRIC_CHECK))
        assert ev.lambda_handler({}, None)["commitment_stats"]["kept"] == 1

    def test_a_commitment_failure_does_not_sink_the_prediction_run(self, table, monkeypatch, quiet_docket):
        self._due_directional(table, TestEwmaTrend.RISING)
        monkeypatch.setattr(ev, "_fetch_commitments", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        out = ev.lambda_handler({}, None)
        assert (out["statusCode"], out["predictions_evaluated"], out["commitment_stats"]) == (200, 1, {})

    def test_a_stance_detection_failure_does_not_sink_the_prediction_run(self, table, monkeypatch, quiet_docket):
        self._due_directional(table, TestEwmaTrend.RISING)
        monkeypatch.setattr(ev, "_detect_stance_events", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        out = ev.lambda_handler({}, None)
        assert (out["statusCode"], out["stance_refresh_stats"]) == (200, {})

    def test_a_dispute_docket_failure_does_not_sink_the_prediction_run(self, table, monkeypatch):
        self._due_directional(table, TestEwmaTrend.RISING)
        monkeypatch.setattr(_dispute_docket, "resolve_due", lambda today_str: (_ for _ in ()).throw(RuntimeError("boom")))
        out = ev.lambda_handler({}, None)
        assert (out["statusCode"], out["docket_stats"], out["predictions_evaluated"]) == (200, {}, 1)

    def test_a_liveness_failure_does_not_sink_the_prediction_run(self, table, monkeypatch, quiet_docket):
        self._due_directional(table, TestEwmaTrend.RISING)
        monkeypatch.setattr(ev, "emit_grading_liveness", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        out = ev.lambda_handler({}, None)
        assert (out["statusCode"], out["liveness"], out["predictions_evaluated"]) == (200, {}, 1)

    def test_the_docket_resolver_is_run_in_the_same_deterministic_lane(self, table, monkeypatch):
        seen = {}
        monkeypatch.setattr(_dispute_docket, "resolve_due", lambda today_str: seen.setdefault("date", today_str) and {"n": 1})
        ev.lambda_handler({}, None)
        assert seen["date"] == TODAY

    def test_a_scan_failure_reports_an_error_rather_than_a_false_clean_run(self, table, monkeypatch, quiet_docket):
        monkeypatch.setattr(ev, "_fetch_predictions", lambda: (_ for _ in ()).throw(RuntimeError("table gone")))
        out = ev.lambda_handler({}, None)
        assert out["statusCode"] == 500
        assert "table gone" in out["error"]

    def test_a_refuted_call_fires_exactly_one_stance_refresh_for_its_own_coach(self, table, env, quiet_docket):
        self._due_directional(table, TestEwmaTrend.FALLING)
        out = ev.lambda_handler({}, None)
        assert out["stance_refresh_stats"]["coaches"] == ["sleep_coach"]
        payload = json.loads(env.lam.invokes[0]["Payload"].decode())
        assert (payload["mode"], payload["coach_id"]) == ("event_stance_refresh", "sleep_coach")


# ══════════════════════════════════════════════════════════════════════════════
# N. Re-grading after the data arrives (the second-look contract)
# ══════════════════════════════════════════════════════════════════════════════


class TestSecondLook:
    def test_an_undecidable_grade_is_written_back_as_a_terminal_outcome(self, table):
        """Characterisation: the first undecidable pass terminalises the record —
        it is stamped with algo_version, which is exactly what the #813 reclaim
        discriminator uses to refuse a second pass."""
        ev._evaluate_all([prediction(created_date=days_before(20))], TODAY)
        stored = table.items[("COACH#sleep_coach", "PREDICTION#pred_1")]
        assert stored["status"] == "inconclusive"
        assert json.loads(stored["outcome_notes"])["algo_version"] == ev.ALGO_VERSION

    @pytest.mark.xfail(
        strict=False,
        reason=(
            "DEFECT (tranche-2 discovery): a forecast graded 'inconclusive' purely because the "
            "metric had no reading on the day its window closed is terminal. _evaluate_all writes "
            "the outcome with algo_version, so _fetch_predictions' EVALUABLE_STATUSES filter and "
            "the #813 reclaim discriminator both refuse it forever — even though data arriving one "
            "day later would have decided it, and even though _check_expiry/EXPIRY_MULTIPLIER "
            "clearly intend a 2x-window grace period. As a result EXPIRY_MULTIPLIER is unreachable "
            "for any prediction the daily run sees on schedule."
        ),
    )
    def test_a_forecast_undecidable_for_lack_of_data_gets_a_second_look_before_expiry(self, table):
        seed(table, prediction(created_date=days_before(20)))
        ev._evaluate_all(ev._fetch_predictions(), TODAY)  # day 20: no readings yet
        daily_series("hrv", [60.0], table=table)  # the reading lands the next day
        assert len(ev._fetch_predictions()) == 1
