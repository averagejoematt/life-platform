"""tests/test_grader_fixes_5533.py — the five evaluator fixes and the correction ledger (#5533, epic #5529).

The 2026-10-31 audit (Stage 4 plan §F Phase 3) found five grading defects the v9 ledger
would print beside every call. Each gets its failing-then-passing case here, on the
evaluator's OWN path (``coach_prediction_evaluator``) over a fake table that applies the
grader's real update expressions:

  (a) every graded row carries ``quality_flags`` ⊆ {logging_gap, low_power, proxy_metric} and
      an ``evaluator_version``; ``coach_record.quality_counts`` exposes a clean count BESIDE
      K of N, never instead of it;
  (b) a retired coach's sealed row is scanned and graded;
  (c) a zero-entry MacroFactor day is absent from a direction window (its n drops), and a
      window that falls below the minimum readings is inconclusive, never graded on the
      pre-filled default;
  (d) the point grader's ``_7day_avg`` branch honours ``after_day``;
  (e) an HRV / RHR / recovery window spanning the 2026-10-10 marker is re-baselined per
      ``health.hr_regime`` with the boundary named in ``outcome_notes``; a number call
      priced before the marker and due after it is inconclusive (and expires by the rules);

plus the ledger (``coach.grade_corrections``): the CORRECTION# row is written before the
grade changes, ``original_grade`` is snapshotted once, a second correction appends, the
Brier pairs and the record read the corrected status, every write is Decimal-safe; and
``deploy/regrade_predictions.py`` selects only the rows the fixes touch, prints the
before/after tables, writes nothing without --apply and writes the summary row with it.

Every date is fixed; the evaluator is driven with an explicit ``today_str`` and the ledger
with an explicit ``now`` — nothing here reaches the clock (#4848). The 2026-10-10 marker is
``health.hr_regime``'s own registry entry, read from it.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

import pytest  # noqa: E402
import regrade_predictions as regrade  # noqa: E402
from coach import (  # noqa: E402
    coach_baseline,
    coach_checkin,
    coach_prediction_evaluator as ev,
    coach_record,
    grade_corrections as gc,
    grading_quality as gq,
    prediction_point_grader as ppg,
)
from coach.persona_registry import OPERATIONAL_COACH_IDS, RETIRED_COACH_IDS  # noqa: E402
from experiment import calibration_core  # noqa: E402
from health import hr_regime  # noqa: E402
from pacific_clock import freeze_pacific  # noqa: E402 — #2811: the PT clock the evaluator actually calls

MARKER = hr_regime.HR_REGIME_MARKERS[0]["date"]  # 2026-10-10 — read, never retyped
assert MARKER == "2026-10-10", "the fixture dates below straddle the registry's first marker"
TODAY = "2026-10-20"
NOW = datetime(2026, 10, 20, 18, 0, 0, tzinfo=timezone.utc)
GENESIS = "2026-09-01"
RETIRED = RETIRED_COACH_IDS[0]


class _FrozenDatetime(datetime):
    """The evaluator's `datetime` pinned to NOW (its `updated_at` / `created_at` stamps), a
    subclass so strptime/timedelta keep working on the same name (#2376 — never a dated
    fixture against a live handler clock)."""

    @classmethod
    def now(cls, tz=None):
        return NOW if tz else NOW.replace(tzinfo=None)

    @classmethod
    def utcnow(cls):
        return NOW.replace(tzinfo=None)


COACH = OPERATIONAL_COACH_IDS[0]


def _day(start: str, offset: int) -> str:
    return (datetime.strptime(start, "%Y-%m-%d") + timedelta(days=offset)).strftime("%Y-%m-%d")


# ── a table that applies the grader's and the ledger's real update expressions ──────────


class ConditionFailed(Exception):
    pass


class FakeTable:
    """Keyed like the live table. ``update_item`` applies ``SET a = :a, list_append(if_not_exists(..))``
    and ``if_not_exists(..)`` generically and honours the two conditions the code under test
    writes (``#status = :prior``, ``attribute_not_exists(x)``). ``query`` honours ``sk BETWEEN``
    and ``begins_with``. Every write is recorded in order, so a test can assert what was
    written first."""

    def __init__(self):
        self.items: dict = {}
        self.writes: list = []  # ("put"|"update", key)

    def seed(self, *rows):
        for r in rows:
            self.items[(r["pk"], r["sk"])] = dict(r)

    def put_item(self, Item=None, **_kw):
        self.items[(Item["pk"], Item["sk"])] = dict(Item)
        self.writes.append(("put", (Item["pk"], Item["sk"]), dict(Item)))
        return {}

    def update_item(
        self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, ConditionExpression=None, **_kw
    ):
        names, values = ExpressionAttributeNames or {}, ExpressionAttributeValues or {}
        item = self.items.setdefault((Key["pk"], Key["sk"]), dict(Key))
        if ConditionExpression:
            for clause in ConditionExpression.split(" AND "):
                clause = clause.strip()
                if clause.startswith("attribute_not_exists("):
                    if names.get(clause[21:-1], clause[21:-1]) in item:
                        raise ConditionFailed(clause)
                elif clause.startswith("attribute_exists("):
                    if names.get(clause[17:-1], clause[17:-1]) not in item:
                        raise ConditionFailed(clause)
                elif " = " in clause:
                    lhs, rhs = (p.strip() for p in clause.split(" = ", 1))
                    if item.get(names.get(lhs, lhs)) != values.get(rhs):
                        raise ConditionFailed(clause)
        body = UpdateExpression.split("SET", 1)[-1]
        depth, cur, parts = 0, "", []
        for ch in body:
            depth += ch == "("
            depth -= ch == ")"
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        for assignment in parts:
            if "=" not in assignment:
                continue
            lhs, rhs = (p.strip() for p in assignment.split("=", 1))
            attr = names.get(lhs, lhs)
            if rhs.startswith("list_append(if_not_exists("):
                inner = rhs[len("list_append(if_not_exists(") : -1]
                base_attr, empty, appended = inner.replace(")", "").replace(" ", "").split(",")
                item[attr] = list(item.get(base_attr, values[empty])) + list(values[appended])
            elif rhs.startswith("if_not_exists("):
                base_attr, default = rhs[len("if_not_exists(") : -1].replace(" ", "").split(",")
                if base_attr not in item:
                    item[attr] = values[default]
            else:
                item[attr] = values[rhs]
        self.writes.append(("update", (Key["pk"], Key["sk"]), dict(values)))
        return {}

    def get_item(self, Key=None, **_kw):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item is not None else {}

    def query(self, **kwargs):
        vals = kwargs.get("ExpressionAttributeValues", {})
        pk = vals.get(":pk")
        if pk is None:  # boto3 conditions object (the re-grade script's partition read)
            cond = kwargs["KeyConditionExpression"]
            pk = cond._values[0]._values[1]
            prefix = cond._values[1]._values[1]
            rows = [v for (p, s), v in self.items.items() if p == pk and s.startswith(prefix)]
            return {"Items": sorted(rows, key=lambda r: r["sk"])}
        rows = [v for (p, _s), v in self.items.items() if p == pk]
        if ":s" in vals and ":e" in vals:
            rows = [r for r in rows if vals[":s"] <= r["sk"] <= vals[":e"]]
        if vals.get(":prefix"):
            rows = [r for r in rows if str(r["sk"]).startswith(vals[":prefix"])]
        return {"Items": sorted(rows, key=lambda r: r["sk"])}


@pytest.fixture
def table(monkeypatch):
    t = FakeTable()
    monkeypatch.setattr(ev, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, ev, _FrozenDatetime)
    monkeypatch.setattr(ev, "table", t)
    monkeypatch.setattr(ev, "_cw", type("CW", (), {"put_metric_data": lambda self, **k: {}})())
    monkeypatch.setattr(coach_checkin, "read_cycle", lambda ssm_client=None: 17)  # the stamp's fail-soft SSM read, cut
    return t


def seed_metric(table, source, field, values_by_date, **extra):
    for d, v in values_by_date.items():
        row = {"pk": ev.USER_PREFIX + source, "sk": f"DATE#{d}", "date": d, "source": source, **extra}
        if v is not None:
            row[field] = Decimal(str(v))
        table.seed(row)


def prediction(pred_id="p1", coach_id=COACH, created=_day(TODAY, -20), status="pending", claim="", evaluation=None, **extra):
    return {
        "pk": f"COACH#{coach_id}",
        "sk": f"PREDICTION#{pred_id}",
        "prediction_id": pred_id,
        "coach_id": coach_id,
        "created_date": created,
        "claim_natural": claim,
        "subdomain": "protein",
        "status": status,
        "evaluation": evaluation or {"type": "directional", "metric": "total_protein_g", "condition": "up", "evaluation_window_days": 14},
        "confidence": 0.7,
        "outcome": status if status in ("confirmed", "refuted") else None,
        "outcome_date": _day(TODAY, -3) if status in ("confirmed", "refuted") else None,
        "outcome_notes": json.dumps({"reason": "old", "algo_version": "1.0"}) if status in ("confirmed", "refuted") else None,
        **extra,
    }


def _notes(row):
    return json.loads(row["outcome_notes"])


# ══════════════════════════════════════════════════════════════════════════════════════════
# (c) a zero-entry behavioral day is missing, not a default
# ══════════════════════════════════════════════════════════════════════════════════════════

PROTEIN_START = _day(TODAY, -20)


def _protein_days(table, zero_entry=()):
    """15 MacroFactor days rising 120 → 190 g; the ``zero_entry`` days carry the #5519 stub shape
    (``entries_count=0``, ``food_log=[]``, 15 g) instead of a logged total."""
    days = {_day(PROTEIN_START, i): 120 + 5 * i for i in range(15)}
    for d, v in days.items():
        stub = d in zero_entry
        seed_metric(
            table,
            "macrofactor",
            "total_protein_g",
            {d: 15 if stub else v},
            entries_count=Decimal(0) if stub else Decimal(6),
            food_log=[] if stub else [{"name": "x"}],
            _format="daily_summary",
        )
    return days


def test_a_zero_entry_row_is_the_5519_stub_shape_and_a_logged_row_is_not():
    stub = {"entries_count": Decimal(0), "food_log": [], "total_protein_g": Decimal(15), "_format": "daily_summary"}
    assert gq.is_zero_entry_day(stub) is True
    assert gq.is_zero_entry_day({"entries_count": 4, "food_log": [{}], "total_protein_g": 150}) is False
    assert gq.is_zero_entry_day({"entries_count": 0, "food_log": [{"name": "late entry"}]}) is False
    assert gq.is_zero_entry_day({"total_protein_g": 150}) is False, "a row without the field is not judged"
    assert gq.is_zero_entry_day({"weight_lbs": 320}) is False


def test_a_zero_entry_day_yields_no_reading_and_the_window_n_drops(table):
    gap = {_day(PROTEIN_START, 5), _day(PROTEIN_START, 6)}
    _protein_days(table, zero_entry=gap)
    rows = ev._fetch_range("macrofactor", PROTEIN_START, TODAY)
    series = ev._extract_metric_series(rows, "total_protein_g")
    assert {d for d, _ in series}.isdisjoint(gap), "the stub's 15 g must never be a reading"
    assert len(series) == 13
    pred = prediction(created=PROTEIN_START)
    result = ev._evaluate_directional(pred, pred["evaluation"], {}, TODAY)
    assert result["status"] == "confirmed" and result["window"]["readings"] == 13  # 15 days, two unlogged
    assert result["window"]["start"] == PROTEIN_START


def test_a_window_that_falls_below_the_minimum_readings_is_inconclusive_never_graded_on_the_default(table):
    # Six days in the window, four of them zero-entry stubs: two real readings remain — below WINDOW_MIN_READINGS.
    days = [_day(PROTEIN_START, i) for i in (0, 2, 5, 7, 10, 14)]
    for i, d in enumerate(days):
        stub = i in (1, 2, 3, 4)
        seed_metric(
            table, "macrofactor", "total_protein_g", {d: 15 if stub else 120 + 10 * i}, entries_count=Decimal(0 if stub else 3), food_log=[]
        )
    pred = prediction(created=PROTEIN_START)
    result = ev._evaluate_directional(pred, pred["evaluation"], {}, TODAY)
    assert result["status"] == "inconclusive"
    assert "2 reading(s)" in result["reason"]
    # The same stubs read as intake would have graded a 15 → 15 "flat" refutation. They do not.
    assert "flat" not in result["reason"]


def test_the_grader_flags_the_logging_gap_on_the_row_and_in_its_notes(table):
    gap = {_day(PROTEIN_START, 5)}
    _protein_days(table, zero_entry=gap)
    row = prediction(created=PROTEIN_START, claim="Protein intake will rise over the next two weeks.")
    table.seed(row)
    evaluations, stats = ev._evaluate_all([row], TODAY)
    assert stats["confirmed"] == 1
    stored = table.items[(row["pk"], row["sk"])]
    assert stored["quality_flags"] == ["logging_gap"]
    assert stored["evaluator_version"] == ev.ALGO_VERSION == gq.EVALUATOR_VERSION == "1.1"
    assert _notes(stored)["quality_flags"] == ["logging_gap"] and _notes(stored)["evaluator_version"] == "1.1"
    assert evaluations[0]["quality_flags"] == ["logging_gap"]


# ══════════════════════════════════════════════════════════════════════════════════════════
# (a) the other two flags, and the clean count beside K of N
# ══════════════════════════════════════════════════════════════════════════════════════════


def test_low_power_is_a_band_or_tolerance_at_least_35_percent_of_the_value():
    assert gq.low_power({"type": "point", "threshold": 60, "tolerance": 25}, {}) is True  # 41.7%
    assert gq.low_power({"type": "point", "threshold": 60, "tolerance": 18}, {}) is False  # 30%
    assert gq.low_power({"type": "point", "threshold": 0, "tolerance": 1}, {}) is True, "a band around zero is all noise"
    assert gq.low_power({"type": "directional"}, {"noise_band": 0.36}) is True
    assert gq.low_power({"type": "directional"}, {"noise_band": 0.02}) is False
    assert gq.low_power({"type": "machine", "threshold": 50}, {}) is False
    assert gq.low_power({"type": "directional"}, {"noise_band": 0.9, "evaluation_type": "count"}) is False


def test_proxy_metric_is_derived_from_the_sentence_and_never_from_an_absence():
    assert gq.claim_names_metric("Recovery score will be around 60% tomorrow", "recovery_score") is True
    assert gq.claim_names_metric("Sleep will improve this week.", "recovery_score") is False
    assert gq.claim_names_metric("He will be under 320 lbs by Friday", "weight_lbs") is True  # the unit names it
    assert gq.claim_names_metric("Daily protein will hold 170 g", "total_protein_g_7day_avg") is True
    assert gq.claim_names_metric("", "recovery_score") is None and gq.claim_names_metric("anything", None) is None
    spec = {"type": "directional", "metric": "recovery_score", "condition": "up"}
    assert gq.quality_flags(
        {"claim_natural": "Sleep will improve this week."}, spec, {"noise_band": 0.01}, {}, start="2026-10-01", end="2026-10-05"
    ) == ["proxy_metric"]
    assert gq.quality_flags({"claim_natural": ""}, spec, {"noise_band": 0.01}, {}, start="2026-10-01", end="2026-10-05") == []
    assert gq.quality_flags({}, spec, {"noise_band": 0.01, "metric": "hrv"}, {}, start="2026-10-01", end="2026-10-05") == ["proxy_metric"]


def test_every_flag_is_in_the_closed_vocabulary_and_a_clean_row_carries_an_empty_list(table):
    _protein_days(table)
    row = prediction(created=PROTEIN_START, claim="Protein will climb over the next two weeks.")
    table.seed(row)
    ev._evaluate_all([row], TODAY)
    stored = table.items[(row["pk"], row["sk"])]
    assert stored["quality_flags"] == [] and set(gq.FLAGS) == {"logging_gap", "low_power", "proxy_metric"}
    assert gq.is_clean(stored) is True and gq.is_clean({"status": "confirmed"}) is None


def test_quality_counts_sit_beside_k_of_n_and_never_replace_it():
    rows = [
        {"prediction_id": "a", "sk": "PREDICTION#a", "status": "confirmed", "outcome_date": "2026-10-02", "quality_flags": []},
        {"prediction_id": "b", "sk": "PREDICTION#b", "status": "refuted", "outcome_date": "2026-10-03", "quality_flags": ["logging_gap"]},
        {"prediction_id": "c", "sk": "PREDICTION#c", "status": "confirmed", "outcome_date": "2026-10-04"},  # graded before the flags
        {"prediction_id": "d", "sk": "PREDICTION#d", "status": "pending"},
    ]
    record = coach_record.record_from_rows(rows, genesis=GENESIS, as_of="2026-10-05")
    assert set(record) == {"confirmed", "refuted", "n", "through"} and record["n"] == 3, "the record's shape is untouched (ADR-157)"
    q = coach_record.quality_counts(coach_record.decided_rows(rows, genesis=GENESIS))
    assert q == {"clean": 1, "flagged": 1, "unassessed": 1, "n": 3, "by_flag": {"logging_gap": 1, "low_power": 0, "proxy_metric": 0}}
    assert q["clean"] + q["flagged"] + q["unassessed"] == record["n"]
    assert "#qf" in coach_record._PROJECTION_NAMES and coach_record._PROJECTION_NAMES["#qf"] == "quality_flags"


# ══════════════════════════════════════════════════════════════════════════════════════════
# (b) a retired coach's sealed row is graded
# ══════════════════════════════════════════════════════════════════════════════════════════


def test_a_retired_coachs_sealed_bet_is_scanned_and_graded(table):
    _protein_days(table)
    sealed = prediction(pred_id="sealed", coach_id=RETIRED, created=PROTEIN_START, pre_registered=True, claim="Protein will rise.")
    table.seed(sealed)
    evaluable, _ = ev._fetch_predictions()
    assert [p["sk"] for p in evaluable] == ["PREDICTION#sealed"], "the retired seat's partition is read"
    ev._evaluate_all(evaluable, TODAY)
    assert table.items[(sealed["pk"], sealed["sk"])]["status"] == "confirmed"
    assert RETIRED not in ev.COACH_IDS and RETIRED in ev.GRADING_COACH_IDS, "closed to new emissions, open to the grade it owes"


# ══════════════════════════════════════════════════════════════════════════════════════════
# (d) the aggregate branch honours after_day
# ══════════════════════════════════════════════════════════════════════════════════════════


def test_a_7day_average_on_the_target_day_reads_only_readings_after_the_filing_day():
    filed, target = "2026-09-14", "2026-09-16"
    rows = [{"date": _day("2026-09-08", i), "recovery_score": 100.0} for i in range(7)] + [
        {"date": "2026-09-15", "recovery_score": 50.0},
        {"date": "2026-09-16", "recovery_score": 50.0},
    ]
    io = {"get_source_data": lambda *a, **k: rows, "extract_metric_series": ev._extract_metric_series}
    value, on = ppg.metric_value_on("recovery_score_7day_avg", {}, TODAY, target, after_day=filed, **io)
    assert (value, on) == (50.0, target), "the seven-day mean was built from readings the coach had on the page"
    unbounded, _ = ppg.metric_value_on("recovery_score_7day_avg", {}, TODAY, target, **io)
    assert unbounded > 50.0  # the defect, reproduced: without the bound five pre-call 100s enter the mean
    none, _ = ppg.metric_value_on("recovery_score_7day_avg", {}, TODAY, "2026-09-14", after_day=filed, **io)
    assert none is None, "no reading after the filing day → no aggregate, not a borrowed one"


# ══════════════════════════════════════════════════════════════════════════════════════════
# (e) the HR regime marker
# ══════════════════════════════════════════════════════════════════════════════════════════


def _hrv_days(table):
    """Whoop HRV 10-01 → 10-19: flat ~40 before the marker, a spike on the marker day, then rising 50 → 66 after it."""
    for i in range(19):
        d = _day("2026-10-01", i)
        if d < MARKER:
            v = 40 + (i % 2)
        elif d == MARKER:
            v = 120
        else:
            v = 50 + 2 * (i - 10)
        seed_metric(table, "whoop", "hrv", {d: v})


def _hr_call(created, days, metric="hrv", kind="directional", **extra):
    spec = {"type": kind, "metric": metric, "condition": "up", "evaluation_window_days": days}
    if kind == "point":
        spec.update(condition="within", threshold=55.0, tolerance=4.0, target_date=_day(created, days))
    return prediction(pred_id=f"hr_{created}_{kind}", created=created, claim="HRV will climb.", evaluation=spec, subdomain="hrv", **extra)


def test_hr_metrics_are_derived_from_the_registry_not_listed():
    assert gq.HR_METRICS == {"hrv", "resting_heart_rate", "recovery_score"}
    assert gq.is_hr_metric("hrv_7day_avg") and gq.is_hr_metric("resting_heart_rate") and not gq.is_hr_metric("weight_lbs")


def test_a_direction_window_spanning_the_marker_is_rebaselined_after_it_and_names_the_boundary(table):
    _hrv_days(table)
    call = _hr_call("2026-10-03", 14)  # stated window 10-03 → 10-17 straddles 10-10
    result = ev._evaluate_directional(call, call["evaluation"], {}, TODAY)
    w = result["window"]
    assert (w["start"], w["end"]) == (_day(MARKER, 1), "2026-10-17"), "graded from the day after the marker to the stated end"
    assert w["first_value"] >= 50 and result["status"] == "confirmed"
    assert result["hr_regime"]["marker_date"] == MARKER and result["hr_regime"]["requested_start"] == "2026-10-03"
    assert result["reason"].startswith(gq.REGIME_MARKER) and MARKER in result["reason"]
    # The marker's own transition day (the 120 spike) never enters the series.
    assert w["first_date"] == _day(MARKER, 1)


def test_the_marker_is_named_in_the_written_outcome_notes(table):
    _hrv_days(table)
    call = _hr_call("2026-10-03", 14)
    table.seed(call)
    ev._evaluate_all([call], TODAY)
    notes = _notes(table.items[(call["pk"], call["sk"])])
    assert notes["hr_regime"]["marker_date"] == MARKER and notes["hr_regime"]["since"] == _day(MARKER, 1)
    assert MARKER in notes["reason"]


def test_a_device_rhythm_day_is_excluded_from_the_rebaselined_series(table):
    _hrv_days(table)
    excluded = _day(MARKER, 3)
    seed_metric(table, "withings", hr_regime.DEVICE_RHYTHM_FIELD, {excluded: 1})  # a classification other than "not detected"
    call = _hr_call("2026-10-03", 14)
    result = ev._evaluate_directional(call, call["evaluation"], {}, TODAY)
    assert result["window"]["readings"] == 6 and result["hr_regime"]["excluded_days_n"] == 1  # 10-11..10-17 is 7 days, one excluded


def test_a_window_entirely_inside_one_regime_or_on_a_non_hr_metric_is_untouched(table):
    _hrv_days(table)
    after = _hr_call(_day(MARKER, 1), 7)
    result = ev._evaluate_directional(after, after["evaluation"], {}, TODAY)
    assert "hr_regime" not in result and not result["reason"].startswith(gq.REGIME_MARKER)
    before = _hr_call("2026-10-01", 7)  # 10-01 → 10-08, ends before the marker
    result = ev._evaluate_directional(before, before["evaluation"], {}, TODAY)
    assert "hr_regime" not in result
    weight = prediction(
        created="2026-10-03", evaluation={"type": "directional", "metric": "weight_lbs", "condition": "down", "evaluation_window_days": 14}
    )
    assert gq.regime_adjust(weight, weight["evaluation"], 14, TODAY, ev._extract_metric_series)[3] is None


def test_a_number_call_priced_before_the_marker_and_due_after_it_is_inconclusive_then_expires(table):
    _hrv_days(table)
    call = _hr_call("2026-10-05", 7, kind="point")  # target 10-12, after the marker
    result = ev._evaluate_point(call, call["evaluation"], {}, TODAY)
    assert result["status"] == "inconclusive" and MARKER in result["reason"] and result["hr_regime"]["marker_date"] == MARKER
    table.seed(call)
    _, stats = ev._evaluate_all([call], TODAY)
    # 15 days since filing > 2 × its 7-day window: retired by the existing expiry rule, moving no confidence.
    assert stats["expired"] == 1 and table.items[(call["pk"], call["sk"])]["status"] == "expired"
    assert not [k for k in table.items if k[1].startswith("CONFIDENCE#")]


# ══════════════════════════════════════════════════════════════════════════════════════════
# the correction ledger
# ══════════════════════════════════════════════════════════════════════════════════════════


def _graded_row(status="refuted"):
    return prediction(
        pred_id="p9", status=status, claim="Protein will rise.", baseline={"rule": "nothing_changes", "version": 1, "right": True}
    )


def _corrected(status="confirmed"):
    return {
        "status": status,
        "outcome_date": TODAY,
        "outcome_notes": json.dumps({"reason": "new", "algo_version": "1.1"}),
        "quality_flags": ["logging_gap"],
    }


def _walk_floats(obj):
    if isinstance(obj, float):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _walk_floats(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _walk_floats(v)


def test_the_ledger_row_is_written_before_the_grade_changes_and_the_original_is_kept(table):
    row = _graded_row()
    table.seed(row)
    e = gc.apply_correction(table, row, _corrected(), reason="#5533 (c) …", evaluator_version="1.1", now=NOW)
    kinds = [(w[0], w[1][1].split("#")[0]) for w in table.writes]
    assert kinds == [("put", "CORRECTION"), ("update", "PREDICTION")], "the ledger row lands first"
    ledger = table.items[(row["pk"], f"CORRECTION#p9#{e['corrected_at']}")]
    assert e["corrected_at"] == "2026-10-20T18:00:00Z"
    assert {k: ledger[k] for k in gc.ENTRY_FIELDS} == e
    assert (e["original_status"], e["original_outcome_date"], e["corrected_status"]) == ("refuted", row["outcome_date"], "confirmed")
    assert e["original_outcome_notes"] == row["outcome_notes"] and e["reason"] == "#5533 (c) …" and e["evaluator_version"] == "1.1"
    stored = table.items[(row["pk"], row["sk"])]
    assert stored["status"] == stored["outcome"] == "confirmed" and stored["outcome_date"] == TODAY
    assert stored["original_grade"]["status"] == "refuted" and stored["original_grade"]["outcome_notes"] == row["outcome_notes"]
    assert stored["original_grade"]["baseline"] == row["baseline"] and stored["original_grade"]["snapshot_at"] == e["corrected_at"]
    assert stored["corrections"] == [e] and stored["quality_flags"] == ["logging_gap"] and stored["evaluator_version"] == "1.1"


def test_a_second_correction_appends_and_the_first_snapshot_is_never_overwritten(table):
    row = _graded_row()
    table.seed(row)
    first = gc.apply_correction(table, row, _corrected("confirmed"), reason="r1", evaluator_version="1.1", now=NOW)
    stored = dict(table.items[(row["pk"], row["sk"])])
    second = gc.apply_correction(
        table, stored, _corrected("inconclusive"), reason="r2", evaluator_version="1.2", now=NOW + timedelta(days=1)
    )
    final = table.items[(row["pk"], row["sk"])]
    assert final["corrections"] == [first, second] and final["status"] == "inconclusive"
    assert second["original_status"] == "confirmed", "the second entry's original is the first correction's result"
    assert final["original_grade"]["status"] == "refuted", "the first grade survives every later correction"
    ledger = sorted(sk for (_pk, sk) in table.items if sk.startswith("CORRECTION#"))
    assert len(ledger) == 2 and all(sk.startswith("CORRECTION#p9#") for sk in ledger)
    assert gc.already_corrected(final, evaluator_version="1.1", reason_prefix="r1") and not gc.already_corrected(
        final, evaluator_version="1.3"
    )


def test_a_stale_plan_writes_no_grade(table):
    row = _graded_row()
    table.seed(dict(row, status="confirmed"))  # the row moved on since the plan read it
    with pytest.raises(ConditionFailed):
        gc.apply_correction(table, row, _corrected("inconclusive"), reason="r", evaluator_version="1.1", now=NOW)
    assert table.items[(row["pk"], row["sk"])]["status"] == "confirmed" and "corrections" not in table.items[(row["pk"], row["sk"])]


def test_every_ledger_write_is_decimal_safe(table):
    row = _graded_row()
    row["baseline"]["filed_value"] = 151.2
    table.seed(row)
    corrected = _corrected()
    corrected["baseline"] = {"rule": "nothing_changes", "version": 1, "right": False, "filed_value": 151.2}
    gc.apply_correction(table, row, corrected, reason="r", evaluator_version="1.1", now=NOW)
    gc.write_summary(table, {"headline": {"before": {"k": 1, "n": 2}, "share": 0.5}}, now=NOW)
    for kind, _key, payload in table.writes:
        assert not list(_walk_floats(payload)), (kind, payload)
    summary = table.items[(gc.SUMMARY_PK, f"CORRECTION#SUMMARY#{gc.now_iso(NOW)}")]
    assert summary["headline"]["share"] == Decimal("0.5")


def test_brier_the_record_and_the_comparison_read_the_corrected_status(table):
    row = _graded_row("refuted")
    table.seed(row)
    gc.apply_correction(table, row, _corrected("confirmed"), reason="r", evaluator_version="1.1", now=NOW)
    stored = table.items[(row["pk"], row["sk"])]
    assert calibration_core.pairs_from_prediction_records([stored]) == [(0.7, 1)]
    assert calibration_core.pairs_from_prediction_records([row]) == [(0.7, 0)], "the original scored 0; the corrected row scores 1"
    record = coach_record.record_from_rows([stored], genesis=GENESIS, as_of=TODAY)
    assert (record["confirmed"], record["refuted"], record["through"]) == (1, 0, TODAY)
    block = coach_baseline.comparison_block(coach_record.decided_rows([stored], genesis=GENESIS))
    assert block["records"]["direction"]["coach_right"] == 1


# ══════════════════════════════════════════════════════════════════════════════════════════
# deploy/regrade_predictions.py — select, recompute, report, write only on --apply
# ══════════════════════════════════════════════════════════════════════════════════════════


def _corpus(table):
    """One row per selection, two that must be left alone, on partitions the FIXED grader scans."""
    _protein_days(table, zero_entry={_day(PROTEIN_START, 5)})
    _hrv_days(table)
    seed_metric(table, "withings", "weight_lbs", {_day(TODAY, -20 + i): 320 - i for i in range(15)})
    rows = {
        "retired": prediction(pred_id="sealed", coach_id=RETIRED, created=PROTEIN_START, pre_registered=True, claim="Protein will rise."),
        "food": prediction(pred_id="food", created=PROTEIN_START, status="refuted", claim="Protein will rise."),
        "agg": prediction(
            pred_id="agg",
            created="2026-09-20",
            status="confirmed",
            claim="7-day protein average will be about 150 g",
            evaluation={
                "type": "point",
                "metric": "total_protein_g_7day_avg",
                "condition": "within",
                "threshold": 150.0,
                "tolerance": 10.0,
                "target_date": "2026-09-27",
                "evaluation_window_days": 7,
            },
        ),
        "hr": dict(
            _hr_call("2026-10-03", 14),
            status="refuted",
            outcome="refuted",
            outcome_date="2026-10-18",
            outcome_notes=json.dumps({"reason": "old", "algo_version": "1.0"}),
        ),
        "weight": prediction(
            pred_id="weight",
            created=_day(TODAY, -20),
            status="confirmed",
            claim="Weight will fall.",
            evaluation={"type": "directional", "metric": "weight_lbs", "condition": "down", "evaluation_window_days": 14},
            subdomain="weight",
        ),
        "docket": prediction(
            pred_id="docket", created=PROTEIN_START, status="refuted", source="dispute_docket", claim="Protein will rise."
        ),
        "done": prediction(
            pred_id="done",
            created=PROTEIN_START,
            status="refuted",
            claim="Protein will rise.",
            corrections=[{"evaluator_version": "1.1", "reason": "#5533 (c)"}],
        ),
    }
    table.seed(*rows.values())
    return rows


def _rows_by_pk(table):
    return {pk: regrade.partition_rows(table, pk) for pk in regrade.partitions(ev)}


def test_the_plan_selects_only_the_rows_the_fixes_touch(table):
    rows = _corpus(table)
    zero = regrade.zero_entry_days(ev, GENESIS, TODAY)
    assert zero == {_day(PROTEIN_START, 5)}
    entries = regrade.plan(_rows_by_pk(table), today=TODAY, zero_days=zero, ev=ev)
    by_id = {e["prediction_id"]: e for e in entries}
    assert set(by_id) == {
        "sealed",
        "food",
        "agg",
        "hr_2026-10-03_directional",
    }, "the weight call, the docket row and the already-corrected row are left alone"
    assert by_id["sealed"]["reasons"] == [regrade.RETIRED] and by_id["sealed"]["action"] == regrade.FIRST_GRADE
    assert (
        by_id["food"]["reasons"] == [regrade.FOOD] and by_id["food"]["action"] == regrade.REGRADE
    )  # refuted → confirmed with the stub gone
    assert by_id["food"]["after"]["quality_flags"] == ["logging_gap"]
    assert by_id["agg"]["reasons"] == [regrade.AGGREGATE]
    assert by_id["hr_2026-10-03_directional"]["reasons"] == [regrade.HR] and by_id["hr_2026-10-03_directional"]["action"] == regrade.REGRADE
    assert MARKER in by_id["hr_2026-10-03_directional"]["after"]["reason"]
    assert rows["food"]["status"] == "refuted", "the plan mutates nothing"
    assert not [w for w in table.writes], "a plan writes nothing"


def test_the_tables_count_before_and_after_from_the_one_record_producer(table):
    _corpus(table)
    rows_by_pk = _rows_by_pk(table)
    entries = regrade.plan(rows_by_pk, today=TODAY, zero_days=regrade.zero_entry_days(ev, GENESIS, TODAY), ev=ev)
    ctable = regrade.coach_table(rows_by_pk, entries, genesis=GENESIS, today=TODAY)
    coach = ctable[COACH]
    assert coach["before"]["refuted"] >= 1 and coach["after"]["confirmed"] > coach["before"]["confirmed"]
    retired = ctable[RETIRED]
    assert (retired["before"]["pending"], retired["after"]["pending"], retired["after"]["n"]) == (1, 0, 1)
    # The aggregate call has no reading after its filing day in this corpus: inconclusive → expired by
    # the existing rules, so it LEAVES the record (n −1) while the retired seat's first grade joins it (n +1).
    by_id = {e["prediction_id"]: e for e in entries}
    assert by_id["agg"]["after"]["status"] == "expired" and by_id["sealed"]["after"]["status"] == "confirmed"
    head = regrade.headline(ctable)
    assert head["delta"] == {"k": head["after"]["k"] - head["before"]["k"], "n": 0}
    assert head["after"]["n"] == sum(c["after"]["n"] for c in ctable.values()) and retired["before"]["n"] == 0
    summ = regrade.summary(entries, ctable, today=TODAY, evaluator_version=ev.ALGO_VERSION)
    assert summ["issue"] == "#5533" and summ["actions"][regrade.FIRST_GRADE] == 1 and summ["reasons"][regrade.HR] == 1
    text = regrade.report(entries, ctable, summ)
    for column in (
        "confirmed before → after",
        "refuted before → after",
        "pending before → after",
        "expired before → after",
        "K of N before → after",
    ):
        assert column in text
    assert "dry run" in text and MARKER not in text.split("### Rows")[0]  # the boundary is a row's reason, not a headline


def test_apply_writes_the_ledger_the_first_grade_and_the_summary_and_a_second_run_changes_nothing(table):
    _corpus(table)
    rows_by_pk = _rows_by_pk(table)
    zero = regrade.zero_entry_days(ev, GENESIS, TODAY)
    entries = regrade.plan(rows_by_pk, today=TODAY, zero_days=zero, ev=ev)
    ctable = regrade.coach_table(rows_by_pk, entries, genesis=GENESIS, today=TODAY)
    summ = regrade.summary(entries, ctable, today=TODAY, evaluator_version=ev.ALGO_VERSION)
    done, item = regrade.apply(table, entries, ev, today=TODAY, summ=summ, now=NOW)
    assert done["failed"] == 0 and done[regrade.FIRST_GRADE] == 1 and done[regrade.REGRADE] >= 2
    sealed = table.items[(f"COACH#{RETIRED}", "PREDICTION#sealed")]
    assert sealed["status"] == "confirmed" and sealed["corrections"][0]["original_status"] == "pending"
    assert any(
        sk.startswith("LEARNING#") for (pk, sk) in table.items if pk == f"COACH#{RETIRED}"
    ), "a first grade takes the evaluator's own path"
    food = table.items[(f"COACH#{COACH}", "PREDICTION#food")]
    assert (
        food["status"] == "confirmed"
        and food["original_grade"]["status"] == "refuted"
        and food["corrections"][0]["reason"].startswith("#5533 (c)")
    )
    ledger = [sk for (_pk, sk) in table.items if sk.startswith("CORRECTION#") and not sk.startswith("CORRECTION#SUMMARY#")]
    assert len(ledger) == done[regrade.REGRADE] + done[regrade.FIRST_GRADE]
    summary = table.items[(gc.SUMMARY_PK, f"CORRECTION#SUMMARY#{gc.now_iso(NOW)}")]
    assert summary is not table.items.get(("x", "y")) and (item["pk"], item["sk"]) == (
        gc.SUMMARY_PK,
        f"CORRECTION#SUMMARY#{gc.now_iso(NOW)}",
    )
    assert summary["issue"] == "#5533" and summary["applied"][regrade.REGRADE] == done[regrade.REGRADE]
    assert summary["changes"] and all(c["before"]["status"] != c["after"] for c in summary["changes"])
    assert table.writes[-1][0] == "put" and table.writes[-1][1] == (gc.SUMMARY_PK, item["sk"]), "the summary is the last write"
    # Second run: every corrected row carries a #5533 entry under this version and is not selected again.
    again = regrade.plan(_rows_by_pk(table), today=TODAY, zero_days=zero, ev=ev)
    assert not [e for e in again if e["action"] in (regrade.REGRADE, regrade.FIRST_GRADE)]


def test_main_refuses_to_apply_with_a_pinned_day_and_defaults_to_a_dry_run(monkeypatch, capsys, table):
    assert regrade.main(["--apply", "--today", TODAY]) == 2
    _corpus(table)
    monkeypatch.setattr(regrade, "EXPERIMENT_START_DATE", GENESIS)
    assert regrade.main(["--today", TODAY]) == 0
    out = capsys.readouterr().out
    assert "dry run — nothing written" in out and "### Per coach" in out
    assert not [w for w in table.writes]
