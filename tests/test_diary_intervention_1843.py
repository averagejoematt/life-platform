"""tests/test_diary_intervention_1843.py — #1843: diary-days as an intervention
variable — measurement reactivity is a finding, not noise.

Covers all three ACs:
  AC1 — daily_metrics_compute_lambda.compute_diary_sessions() counts video-diary /
        solo-recording sessions per date (0 is honest absence, not a gap), and
        store_computed_metrics() writes it (including 0) onto SOURCE#computed_metrics.
  AC2 — weekly_correlation_compute_lambda exposes diary_sessions as a candidate
        variable (assemble_daily_series + one CORRELATION_PAIRS entry), and
        hypothesis_engine_lambda exposes diary_day + habit_pct in the SPEC_METRICS
        vocabulary and build_data_narrative().
  AC3 — hypothesis_engine_lambda.seed_diary_intervention_hypothesis() registers
        exactly ONE pre-registered, correlative-only, n-flagged hypothesis
        (diary-days vs non-diary days on habit adherence), idempotently.

No AWS — daily_metrics_compute_lambda and hypothesis_engine_lambda are imported
with boto3.resource/boto3.client patched (mirrors tests/test_business_logic.py and
tests/test_hypothesis_engine_v2.py); weekly_correlation_compute_lambda's pure
functions are driven directly with fetch_range monkeypatched (mirrors
tests/test_cross_domain_edges_1406.py). compute_metadata's CloudWatch metric emit
is monkeypatched to a no-op so store_computed_metrics never attempts a real AWS call.
"""

import os
import sys
import unittest.mock as mock
from decimal import Decimal

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))

with mock.patch("boto3.resource"), mock.patch("boto3.client"):
    import daily_metrics_compute_lambda as dmc  # noqa: E402
    import hypothesis_engine_lambda as eng  # noqa: E402

import compute_metadata  # noqa: E402
import weekly_correlation_compute_lambda as wc  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════════
# AC1 — compute_diary_sessions() + store_computed_metrics()
# ══════════════════════════════════════════════════════════════════════════════


def _entry(channel=None, template=None):
    e = {"date": "2026-07-20"}
    if channel is not None:
        e["channel"] = channel
    if template is not None:
        e["template"] = template
    return e


def test_compute_diary_sessions_counts_explicit_channels():
    entries = [
        _entry(channel="video_diary"),
        _entry(channel="solo_recording"),
        _entry(channel="journal"),  # typed entry — not a diary session
        _entry(channel="morning"),  # not a valid channel value in practice, still excluded
    ]
    assert dmc.compute_diary_sessions(entries) == 2


def test_compute_diary_sessions_falls_back_to_template():
    """Rows written before the channel stamp (#1572/#1573) still classify correctly
    via flourishing.entry_channel()'s Template fallback."""
    entries = [_entry(template="Video Diary"), _entry(template="Solo Recording"), _entry(template="Morning")]
    assert dmc.compute_diary_sessions(entries) == 2


def test_compute_diary_sessions_honest_zero_not_none():
    assert dmc.compute_diary_sessions([]) == 0
    assert dmc.compute_diary_sessions(None) == 0


def test_compute_diary_sessions_multiple_per_day():
    """Video Diary/Solo Recording explicitly allow multiple entries per day
    (notion_lambda.py) — the count must not collapse to a boolean."""
    entries = [_entry(channel="video_diary"), _entry(channel="video_diary"), _entry(channel="solo_recording")]
    assert dmc.compute_diary_sessions(entries) == 3


def _minimal_store_kwargs(diary_sessions):
    return dict(
        date_str="2026-07-20",
        day_grade_score=85,
        grade="B",
        component_scores={},
        component_details={},
        readiness_score=70,
        readiness_colour="green",
        streak_data={"tier0_streak": 3, "tier01_streak": 5, "vice_streaks": {}},
        tsb=1.2,
        hrv_7d=52.0,
        hrv_30d=50.0,
        sleep_debt_7d_hrs=0.5,
        latest_weight=200.0,
        week_ago_weight=201.0,
        avatar_weight=200.0,
        diary_sessions=diary_sessions,
    )


def _stored_item(monkeypatch, diary_sessions):
    # No real AWS: compute_metadata.tag_record emits a CloudWatch metric — swap for
    # a no-op so this stays hermetic (mirrors the module's own "safe to call
    # multiple times" contract, just never touching a real client).
    monkeypatch.setattr(compute_metadata, "tag_record", lambda record, source_id="unknown", phase=None: record)
    with mock.patch.object(dmc, "table") as mock_table:
        dmc.store_computed_metrics(**_minimal_store_kwargs(diary_sessions))
        assert mock_table.put_item.called
        return mock_table.put_item.call_args.kwargs["Item"]


def test_store_computed_metrics_writes_honest_zero(monkeypatch):
    item = _stored_item(monkeypatch, diary_sessions=0)
    assert "diary_sessions" in item  # 0 must be PRESENT, not omitted (AC1)
    assert item["diary_sessions"] == Decimal("0")


def test_store_computed_metrics_writes_nonzero_count(monkeypatch):
    item = _stored_item(monkeypatch, diary_sessions=2)
    assert item["diary_sessions"] == Decimal("2")


def test_store_computed_metrics_omits_field_when_not_passed(monkeypatch):
    """The sick-day path never calls store_computed_metrics at all (separate
    minimal record) — but if some other caller genuinely has no count (None),
    the field must be omitted rather than fabricating a 0."""
    monkeypatch.setattr(compute_metadata, "tag_record", lambda record, source_id="unknown", phase=None: record)
    kwargs = _minimal_store_kwargs(diary_sessions=None)
    with mock.patch.object(dmc, "table") as mock_table:
        dmc.store_computed_metrics(**kwargs)
        item = mock_table.put_item.call_args.kwargs["Item"]
    assert "diary_sessions" not in item


# ══════════════════════════════════════════════════════════════════════════════
# AC2 — correlation engine candidate variable
# ══════════════════════════════════════════════════════════════════════════════


def test_diary_pair_registered_in_correlation_pairs():
    by_label = {p[2]: p for p in wc.CORRELATION_PAIRS}
    assert "diary_day_vs_habit_pct" in by_label
    metric_a, metric_b, label, lag_days = by_label["diary_day_vs_habit_pct"]
    assert metric_a == "diary_sessions"
    assert metric_b == "habit_pct"
    assert lag_days == 0  # cross-sectional: same-day adherence, not a next-day claim


def test_diary_pair_has_expected_direction():
    assert wc.EXPECTED_DIRECTIONS["diary_day_vs_habit_pct"] == "positive"


def test_assemble_daily_series_extracts_diary_sessions_including_honest_zero(monkeypatch):
    def fake_fetch(source, start, end):
        if source == "computed_metrics":
            return [
                {"date": "2026-07-20", "diary_sessions": 0},
                {"date": "2026-07-21", "diary_sessions": 2},
            ]
        return []

    monkeypatch.setattr(wc, "fetch_range", fake_fetch)
    series = wc.assemble_daily_series("2026-07-19", "2026-07-22")
    assert series["2026-07-20"]["diary_sessions"] == 0.0  # honest absence, not None
    assert series["2026-07-21"]["diary_sessions"] == 2.0


def test_assemble_daily_series_diary_sessions_absent_when_not_computed(monkeypatch):
    monkeypatch.setattr(wc, "fetch_range", lambda source, start, end: [])
    series = wc.assemble_daily_series("2026-07-19", "2026-07-22")
    # No computed_metrics row at all for a date → no series entry, not a fabricated 0.
    assert "2026-07-20" not in series


def test_diary_pair_not_sdt_gated():
    # Habit adherence is a behavioural outcome, not an identity/values signal — the
    # SDT-autonomy guardrail (#1406) doesn't apply here.
    assert "diary_day_vs_habit_pct" not in wc.SDT_SENSITIVE_EDGES


def test_compute_correlations_diary_pair_is_cross_sectional():
    from datetime import date, timedelta

    d0 = date(2026, 6, 1)
    days = [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(20)]
    series = {}
    for i, d in enumerate(days):
        series[d] = {"diary_sessions": float(i % 3), "habit_pct": 0.5 + 0.1 * (i % 3)}
    results = wc.compute_correlations(series)
    edge = results["diary_day_vs_habit_pct"]
    assert edge["correlation_type"] == "cross_sectional"
    assert edge["lag_days"] is None  # 0 lag renders as None, matching every other cross-sectional pair
    assert "fdr_significant" in edge  # published even if not significant — a null is a finding


# ══════════════════════════════════════════════════════════════════════════════
# AC2 (cont.) — hypothesis engine candidate variables
# ══════════════════════════════════════════════════════════════════════════════


def test_spec_metrics_include_diary_day_and_habit_pct():
    assert "diary_day" in eng.SPEC_METRICS
    assert "habit_pct" in eng.SPEC_METRICS


def test_gather_data_sources_include_computed_metrics():
    import inspect

    src = inspect.getsource(eng.gather_data)
    assert '"computed_metrics"' in src


def test_build_data_narrative_extracts_habit_pct():
    data = {"habitify": [{"date": "2026-07-20", "habits": {"a": True, "b": True, "c": False, "d": True}}]}
    rows = eng.build_data_narrative(data)
    row = next(r for r in rows if r["date"] == "2026-07-20")
    assert row["habit_pct"] == 0.75


def test_build_data_narrative_extracts_diary_day_including_honest_zero():
    data = {
        "computed_metrics": [
            {"date": "2026-07-20", "diary_sessions": 0},
            {"date": "2026-07-21", "diary_sessions": 3},
        ],
        # A second source so both dates clear the "more than just date" row filter.
        "habitify": [
            {"date": "2026-07-20", "habits": {"a": True}},
            {"date": "2026-07-21", "habits": {"a": True}},
        ],
    }
    rows = eng.build_data_narrative(data)
    by_date = {r["date"]: r for r in rows}
    assert by_date["2026-07-20"]["diary_day"] == 0.0  # honest absence, not dropped
    assert by_date["2026-07-21"]["diary_day"] == 1.0


def test_build_data_narrative_diary_day_absent_pre_1843():
    """A date with no computed_metrics row at all (pre-#1843, or the field genuinely
    wasn't computed) must NOT get a fabricated diary_day — it's an unmeasured gap,
    distinct from an honest 0-session day."""
    data = {"habitify": [{"date": "2026-07-20", "habits": {"a": True}}]}
    rows = eng.build_data_narrative(data)
    row = next(r for r in rows if r["date"] == "2026-07-20")
    assert "diary_day" not in row


# ══════════════════════════════════════════════════════════════════════════════
# AC3 — the one pre-registered hypothesis
# ══════════════════════════════════════════════════════════════════════════════


def test_seed_registers_when_absent(monkeypatch):
    stored = {}
    monkeypatch.setattr(eng, "store_hypothesis", lambda hyp: stored.update(hyp))

    result = eng.seed_diary_intervention_hypothesis([])

    assert result == {"registered": True, "hypothesis_id": eng.DIARY_INTERVENTION_HYPOTHESIS_ID}
    assert stored["hypothesis_id"] == eng.DIARY_INTERVENTION_HYPOTHESIS_ID
    assert stored["test_spec"]["condition_metric"] == "diary_day"
    assert stored["test_spec"]["outcome_metric"] == "habit_pct"
    # AC3: correlative-only, n flagged, explicitly on the record.
    assert stored["correlative_only"] is True
    assert "n_caveat" in stored and "n" in stored["n_caveat"]
    assert "correlative" in stored["confidence_reason"].lower() or "correlative" in stored["evidence"].lower()


def test_seed_is_idempotent(monkeypatch):
    calls = []
    monkeypatch.setattr(eng, "store_hypothesis", lambda hyp: calls.append(hyp))
    existing = [{"hypothesis_id": eng.DIARY_INTERVENTION_HYPOTHESIS_ID, "status": "confirmed"}]

    result = eng.seed_diary_intervention_hypothesis(existing)

    assert result == {"registered": False, "reason": "already_registered"}
    assert calls == []  # never re-registered once it exists, in ANY status


def test_seed_hypothesis_passes_validate_hypothesis(monkeypatch):
    """Defense in depth: the pre-registered content itself must satisfy the same
    gate a generated hypothesis has to pass (required fields, numeric threshold in
    confirmation_criteria, a valid pre-registered test_spec)."""
    stored = {}
    monkeypatch.setattr(eng, "store_hypothesis", lambda hyp: stored.update(hyp))
    eng.seed_diary_intervention_hypothesis([])

    is_valid, issues = eng.validate_hypothesis(stored, existing_texts=None)
    assert is_valid, issues


def test_seed_hypothesis_test_spec_is_machine_checkable():
    hyp_test_spec = {
        "condition_metric": "diary_day",
        "condition_op": ">=",
        "condition_threshold": 1,
        "outcome_metric": "habit_pct",
        "direction": "higher",
        "min_effect": 0.05,
        "lag_days": 0,
    }
    is_valid, issues = eng.validate_test_spec(hyp_test_spec)
    assert is_valid, issues


def test_seed_hypothesis_evaluates_deterministically_end_to_end(monkeypatch):
    """The registered spec, run against a synthetic 30-day window where diary days
    really do carry higher adherence, resolves to 'supported' — proving the pair
    (test_spec + build_data_narrative's row shape) actually fits together, not just
    that each half validates in isolation."""
    from datetime import date, timedelta

    stored = {}
    monkeypatch.setattr(eng, "store_hypothesis", lambda hyp: stored.update(hyp))
    eng.seed_diary_intervention_hypothesis([])
    spec = stored["test_spec"]

    d0 = date(2026, 6, 1)
    rows = []
    for i in range(30):
        d = (d0 + timedelta(days=i)).strftime("%Y-%m-%d")
        diary = 1.0 if i % 2 == 0 else 0.0
        habit_pct = 0.9 if diary else 0.5
        rows.append({"date": d, "diary_day": diary, "habit_pct": habit_pct})

    stats = eng.evaluate_test_spec(spec, rows, since_date="2026-06-01")
    assert stats["verdict"] == "supported"
    assert stats["n_condition"] >= eng.MIN_DAYS_PER_ARM
    assert stats["n_comparison"] >= eng.MIN_DAYS_PER_ARM
