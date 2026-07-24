"""#1408 — Time-Affluence Meter: deterministic traces + honest absence semantics.

The whole point of this story is honesty: a missing probe or trace is a COVERAGE
GAP, never a 0 (ADR-104 measured-absence), and the candidate edge carries n_eff +
BH-FDR and is descriptive-only below the evidence floor (ADR-105). These tests pin
exactly those behaviours.
"""

from decimal import Decimal

import pytest
import time_affluence as ta

# ── week bucketing ───────────────────────────────────────────────────────────


def test_week_key_folds_mon_to_sun_into_closing_sunday():
    # 2026-07-20 is a Monday; its week closes Sunday 2026-07-26.
    assert ta.week_key("2026-07-20") == "2026-07-26"
    assert ta.week_key("2026-07-26") == "2026-07-26"  # the Sunday maps to itself
    assert ta.week_key("2026-07-25") == "2026-07-26"  # Saturday
    # a different week
    assert ta.week_key("2026-07-27") == "2026-08-02"


def test_week_key_failsoft_on_garbage():
    assert ta.week_key("not-a-date") is None
    assert ta.week_key(None) is None


# ── the three deterministic passive traces ───────────────────────────────────


def test_open_load_is_active_plus_overdue_mean():
    rows = [
        {"active_count": 10, "overdue_count": 2},
        {"active_count": 8, "overdue_count": 0},
    ]
    assert ta.week_open_load(rows) == pytest.approx((12 + 8) / 2)


def test_open_load_none_when_no_rows_not_zero():
    # ADR-104: absence is a gap, not a 0.
    assert ta.week_open_load([]) is None
    assert ta.week_open_load([{"overdue_count": 3}]) is None  # no active_count -> unusable


def test_evening_regularity_needs_three_timestamps_and_is_negated_stdev():
    rows = [
        {"connection_logged_at": "2026-07-20T21:00:00"},
        {"connection_logged_at": "2026-07-21T21:00:00"},
        {"connection_logged_at": "2026-07-22T21:00:00"},
    ]
    # identical times -> zero spread -> regularity 0.0 (the ceiling), not None
    assert ta.week_evening_regularity(rows) == 0.0
    # fewer than 3 timestamped evenings -> coverage gap
    assert ta.week_evening_regularity(rows[:2]) is None
    # more spread -> more negative (less regular)
    spread = [
        {"connection_logged_at": "2026-07-20T20:00:00"},
        {"connection_logged_at": "2026-07-21T21:00:00"},
        {"connection_logged_at": "2026-07-22T23:00:00"},
    ]
    assert ta.week_evening_regularity(spread) < 0.0


def test_unscheduled_days_fraction_of_observed_days():
    rows = [
        {"due_today_count": 0},
        {"due_today_count": 3},
        {"due_today_count": 0},
        {"due_today_count": 0},
    ]
    assert ta.week_unscheduled_days(rows) == pytest.approx(3 / 4)
    # unobserved due-counts don't inflate the denominator (a missing source is not a scheduled day)
    assert ta.week_unscheduled_days([{"foo": 1}]) is None
    assert ta.week_unscheduled_days([]) is None


def test_probe_reads_felt_time_and_is_none_when_absent():
    assert ta.week_probe([{"felt_time": 3}]) == 3.0
    assert ta.week_probe([{"felt_time": 0}]) == 0.0  # a real 0 answer is preserved
    assert ta.week_probe([{}]) is None  # unanswered -> gap, not 0
    assert ta.week_probe([]) is None


# ── standardisation drops uncalibratable traces ──────────────────────────────


def test_zscore_series_drops_trace_below_min_weeks():
    # only 3 present values but TRACE_MIN_WEEKS == 4 -> all None (can't standardise)
    out = ta._zscore_series([1.0, 2.0, 3.0, None])
    assert out == [None, None, None, None]


def test_zscore_series_standardises_when_enough_history():
    out = ta._zscore_series([1.0, 2.0, 3.0, 4.0, 5.0])
    # mean is centered on 3 -> the middle value standardises to ~0
    assert out[2] == pytest.approx(0.0, abs=1e-9)
    assert out[0] < 0 and out[-1] > 0


# ── the composite proxy: coverage-flagging, never zeroed ─────────────────────


def _daily(source_dates_vals):
    """Helper: build daily rows carrying a `date` field."""
    return [dict(date=d, **fields) for d, fields in source_dates_vals]


def _full_window_todoist():
    # 6 weeks x (a Monday) so open-load & unscheduled each get >= TRACE_MIN_WEEKS history.
    mondays = ["2026-06-15", "2026-06-22", "2026-06-29", "2026-07-06", "2026-07-13", "2026-07-20"]
    rows = []
    for i, m in enumerate(mondays):
        rows.append({"date": m, "active_count": 5 + i, "overdue_count": 0, "due_today_count": i % 2})
    return rows


def test_compute_weekly_proxies_never_zeros_absent_components():
    todoist = _full_window_todoist()
    weeks = ta.compute_weekly_proxies(todoist, ritual_rows=[], probe_rows=[])
    assert weeks, "expected weekly proxy rows"
    for wk in weeks:
        # ritual + probe never had data -> they must be ABSENT, never a 0 component.
        assert ta.TRACE_RITUAL_REGULARITY in wk["components_absent"]
        assert ta.PROBE_COMPONENT in wk["components_absent"]
        assert ta.TRACE_RITUAL_REGULARITY not in wk["components"]
        assert wk["probe_answered"] is False
        # coverage reflects only the present components (2 of 4 here)
        assert wk["coverage"] <= 0.5 + 1e-9


def test_compute_weekly_proxies_insufficient_signal_below_floor():
    # Only ONE trace ever present (open-load): coverage 1/4 < 0.5 -> no score emitted.
    mondays = ["2026-06-15", "2026-06-22", "2026-06-29", "2026-07-06", "2026-07-13"]
    todoist = [{"date": m, "active_count": 5 + i} for i, m in enumerate(mondays)]  # no due_today_count
    weeks = ta.compute_weekly_proxies(todoist, [], [])
    assert all(wk["state"] == "insufficient_signal" for wk in weeks)
    assert all(wk["score"] is None for wk in weeks)  # never a fabricated 0


def test_compute_weekly_proxies_scores_when_covered_and_flags_probe():
    todoist = _full_window_todoist()
    # add a probe answer on one week's Sunday
    probe = [{"date": "2026-07-26", "felt_time": 4}]
    # ritual regularity on the same window (>=4 weeks, >=3 evenings each)
    ritual = []
    for m in ["2026-06-15", "2026-06-22", "2026-06-29", "2026-07-06", "2026-07-20"]:
        base = int(m.split("-")[2])
        for off, hour in ((0, "20:00:00"), (1, "21:00:00"), (2, "22:00:00")):
            day = f"2026-{m[5:7]}-{base + off:02d}"
            ritual.append({"date": day, "connection_logged_at": f"{day}T{hour}"})
    weeks = ta.compute_weekly_proxies(todoist, ritual, probe)
    scored = [wk for wk in weeks if wk["state"] == "scored"]
    assert scored, "expected at least one scored week"
    # the probe week must be flagged answered and include the probe component
    probe_week = next((wk for wk in weeks if wk["week"] == "2026-07-26"), None)
    assert probe_week is not None and probe_week["probe_answered"] is True


# ── the candidate edge: n_eff + BH-FDR, descriptive below floor ──────────────


def _scored_weeks(scores):
    return [{"week": w, "score": s, "state": "scored"} for w, s in scores]


def test_edge_reports_neff_and_fdr_for_every_lag():
    # 8 weeks of proxy + adherence, keyed by consecutive Sundays.
    sundays = [f"2026-{5 + (i // 4):02d}-{(3 + i * 7) % 28 + 1:02d}" for i in range(8)]
    # keep it simple: explicit consecutive Sundays
    sundays = [
        "2026-05-03",
        "2026-05-10",
        "2026-05-17",
        "2026-05-24",
        "2026-05-31",
        "2026-06-07",
        "2026-06-14",
        "2026-06-21",
    ]
    proxy = _scored_weeks([(s, float(i)) for i, s in enumerate(sundays)])
    adherence = {s: 0.5 + 0.05 * i for i, s in enumerate(sundays)}
    edge = ta.test_edge(proxy, adherence)
    assert edge["is_proxy"] is True
    assert edge["edge"] == "time_affluence -> adherence"
    lags = {r["lag_weeks"]: r for r in edge["lags"]}
    assert set(lags) == {0, 1}
    for r in edge["lags"]:
        assert "n_eff" in r and "p_fdr" in r and "verdict" in r
        assert r["verdict"] in {"descriptive", "no_effect", "supported_positive", "supported_negative"}


def test_edge_is_descriptive_below_effective_n_floor():
    # only 3 aligned weeks -> n_eff well below EDGE_MIN_N_EFF -> descriptive, never asserted
    sundays = ["2026-05-03", "2026-05-10", "2026-05-17"]
    proxy = _scored_weeks([(s, float(i)) for i, s in enumerate(sundays)])
    adherence = {s: 0.5 + 0.1 * i for i, s in enumerate(sundays)}
    edge = ta.test_edge(proxy, adherence)
    for r in edge["lags"]:
        assert r["verdict"] == "descriptive"


def test_edge_lag1_pairs_edge_week_with_next_week_adherence():
    sundays = ["2026-05-03", "2026-05-10", "2026-05-17"]
    proxy = _scored_weeks([(sundays[0], 1.0), (sundays[1], 2.0)])
    # adherence only exists for week 2 and 3; lag-1 must pair proxy[wk1]->adh[wk2]
    adherence = {sundays[1]: 0.6, sundays[2]: 0.9}
    edge = ta.test_edge(proxy, adherence, lags=(1,))
    lag1 = edge["lags"][0]
    assert lag1["n"] == 2  # proxy wk1->adh wk2 AND proxy wk2->adh wk3


# ── DDB item builders: Decimal + legible absence ─────────────────────────────


def test_build_proxy_item_shape_and_decimal():
    wk = {
        "week": "2026-07-26",
        "score": 0.42,
        "state": "scored",
        "coverage": 0.75,
        "components": {ta.TRACE_OPEN_LOAD: -0.3, ta.PROBE_COMPONENT: 1.1},
        "components_absent": [ta.TRACE_UNSCHEDULED],
        "probe_answered": True,
    }
    item = ta.build_proxy_item(wk, "matthew")
    assert item["pk"] == "USER#matthew#SOURCE#time_affluence"
    assert item["sk"] == "PROXY#2026-07-26"
    assert item["is_proxy"] is True
    assert isinstance(item["score"], Decimal)
    assert isinstance(item["coverage"], Decimal)
    assert all(isinstance(v, Decimal) for v in item["components"].values())
    assert item["components_absent"] == [ta.TRACE_UNSCHEDULED]


def test_build_proxy_item_preserves_none_score_not_zero():
    wk = {
        "week": "2026-07-26",
        "score": None,
        "state": "insufficient_signal",
        "coverage": 0.25,
        "components": {},
        "components_absent": list(ta.COMPONENTS),
        "probe_answered": False,
    }
    item = ta.build_proxy_item(wk, "matthew")
    assert item["score"] is None  # absence stays absent — never cast to Decimal(0)
    assert item["state"] == "insufficient_signal"


def test_build_edge_item_decimal_and_pk():
    edge = ta.test_edge(
        _scored_weeks([("2026-05-03", 1.0), ("2026-05-10", 2.0), ("2026-05-17", 3.0)]),
        {"2026-05-03": 0.5, "2026-05-10": 0.6, "2026-05-17": 0.7},
    )
    item = ta.build_edge_item(edge, "2026-05-17", "matthew")
    assert item["pk"] == "USER#matthew#SOURCE#time_affluence"
    assert item["sk"] == "EDGE#2026-05-17"
    assert item["is_proxy"] is True
    assert isinstance(item["n_weeks_scored"], Decimal)
    assert item["lags"] and all(isinstance(lag["n_eff"], Decimal) for lag in item["lags"])


# ── the probe rides the existing evening-ritual rail into its own partition ───


def test_felt_time_routes_to_time_affluence_partition():
    from ritual_link import RITUAL_METRICS, TIME_AFFLUENCE_PROBE_METRICS, TIME_AFFLUENCE_SOURCE

    assert "felt_time" in RITUAL_METRICS  # a signed one-tap link can be minted for it
    assert "felt_time" in TIME_AFFLUENCE_PROBE_METRICS
    assert TIME_AFFLUENCE_SOURCE == "time_affluence"
    # it must NOT leak into the felt_probe or private sets
    from ritual_link import PRIVATE_RITUAL_METRICS, WEEKLY_PROBE_METRICS

    assert "felt_time" not in WEEKLY_PROBE_METRICS
    assert "felt_time" not in PRIVATE_RITUAL_METRICS


def test_time_affluence_probe_token_roundtrips():
    from ritual_link import sign_ritual_token, verify_ritual_token

    tok = sign_ritual_token("s3cr3t", "2026-07-26", "felt_time", 3)
    assert verify_ritual_token("s3cr3t", "2026-07-26", "felt_time", 3, tok)
    assert not verify_ritual_token("s3cr3t", "2026-07-26", "felt_time", 4, tok)  # value-bound


# ── reset behaviour: the new source is classified (no silent default) ────────


def test_phase_taxonomy_classifies_time_affluence_as_raw_timeseries():
    import phase_taxonomy as pt

    assert pt.SOURCE_CLASS["time_affluence"] == pt.RAW_TIMESERIES
    # classify() resolves DATE#, PROXY# and EDGE# skus all to the same source class
    for sk in ("DATE#2026-07-26", "PROXY#2026-07-26", "EDGE#2026-07-26"):
        assert pt.classify("USER#matthew#SOURCE#time_affluence", sk) == pt.RAW_TIMESERIES
