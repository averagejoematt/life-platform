"""tests/test_phase_filter_third_wave_3444.py — #3444: the #2109 phase-filter
escape, third wave.

`weekly_correlation_compute_lambda.fetch_range` and `hypothesis_engine_lambda.
query_range` both call `digest_utils.query_range_list` with no `include_pilot`
argument at all — the shared reader defaults to `False` (#2150), so both sites
applied the ADR-058 phase filter unconditionally to RAW_TIMESERIES sources. The
experiment reset tags every pre-genesis row `phase=pilot` (ADR-077), so on a
fresh cycle the registry-published "90-day rolling window" (weekly_correlation)
and the hypothesis engine's 30-day deterministic checks both silently truncated
to the CYCLE'S AGE — the same #2109 class recurring through a caller
`test_gradability_liveness_cross_phase_2023`'s AST ratchet could not see behind,
because that scan only recognises a DIRECT `with_phase_filter(...)` call, not a
`digest_utils.query_range_list(...)` pass-through one.

Structure mirrors tests/test_genesis_blind_digest_and_readers_2150.py:

  1. the two fixed sites, each with a RAW_TIMESERIES positive case and an
     EXPERIMENT_SCOPED negative case (`computed_metrics` must stay hidden);
  2. the SETS of sources each site actually reads, checked against
     phase_taxonomy;
  3. the Time-Affluence consequence (#1408): a reproduction of "the meter has
     never scored a week" — pre-genesis history invisible under the OLD
     unqualified `digest_utils.query_range_list` call, visible and score-able
     through the FIXED `hypothesis_engine_lambda.query_range`.

Every date here is PINNED (`_GENESIS`); nothing does now-math against the wall
clock.
"""

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

import hypothesis_engine_lambda as he  # noqa: E402
import weekly_correlation_compute_lambda as wc  # noqa: E402
from common import digest_utils  # noqa: E402
from experiment import phase_taxonomy as tax  # noqa: E402
from experiment.phase_filter import source_reads_cross_phase  # noqa: E402
from health import time_affluence as ta  # noqa: E402
from test_genesis_blind_reads_2080_2081 import PhaseAwareFakeTable, _rows  # noqa: E402

# Pinned clock — the reset happened this morning, the worst case for this
# defect class (same convention as test_genesis_blind_digest_and_readers_2150).
_GENESIS = date(2026, 8, 3)
_GENESIS_ISO = _GENESIS.isoformat()
_BEFORE = [_GENESIS - timedelta(days=d) for d in (10, 5, 1)]
_AFTER = [_GENESIS + timedelta(days=d) for d in (0, 1, 2)]
_ALL_DAYS = sorted(_BEFORE + _AFTER)
_WINDOW_START = min(_ALL_DAYS).isoformat()
_WINDOW_END = max(_ALL_DAYS).isoformat()


def _daily_rows(pk: str, field: str, days: list[date], value=lambda i: 100.0 + i):
    return _rows(pk, field, {d: value(i) for i, d in enumerate(days)}, genesis=_GENESIS)


# ══════════════════════════════════════════════════════════════════════════════
# 1. weekly_correlation_compute_lambda.fetch_range — per-source, the #2109 idiom
# ══════════════════════════════════════════════════════════════════════════════


def test_weekly_correlation_fetch_range_reads_a_raw_timeseries_source_cross_phase(monkeypatch):
    """whoop is RAW_TIMESERIES and drives assemble_daily_series' 90-day window —
    a fresh cycle must not truncate the published window to the cycle's age."""
    assert tax.classify("USER#matthew#SOURCE#whoop") == tax.RAW_TIMESERIES
    rows = _daily_rows("USER#matthew#SOURCE#whoop", "hrv", _ALL_DAYS)
    monkeypatch.setattr(wc, "table", PhaseAwareFakeTable(rows))
    out = wc.fetch_range("whoop", _WINDOW_START, _WINDOW_END)
    assert len(out) == len(_ALL_DAYS), "a RAW_TIMESERIES source must read across the reset"


def test_weekly_correlation_fetch_range_keeps_computed_metrics_filtered(monkeypatch):
    """computed_metrics is EXPERIMENT_SCOPED — the negative case that proves the
    fix derives the flag rather than flipping it on for everything."""
    assert tax.classify("USER#matthew#SOURCE#computed_metrics") == tax.EXPERIMENT_SCOPED
    rows = _daily_rows("USER#matthew#SOURCE#computed_metrics", "readiness", _ALL_DAYS)
    monkeypatch.setattr(wc, "table", PhaseAwareFakeTable(rows))
    out = wc.fetch_range("computed_metrics", _WINDOW_START, _WINDOW_END)
    assert len(out) == len(_AFTER), "an EXPERIMENT_SCOPED source must stay hidden pre-genesis"


def test_weekly_correlation_fetch_range_window_still_bounds_a_cross_phase_read(monkeypatch):
    rows = _daily_rows("USER#matthew#SOURCE#whoop", "hrv", _ALL_DAYS)
    monkeypatch.setattr(wc, "table", PhaseAwareFakeTable(rows))
    assert wc.fetch_range("whoop", "2020-01-01", "2020-01-05") == []


def test_weekly_correlations_own_source_set_is_never_hidden_except_computed_metrics():
    """The set this issue actually closes: every source assemble_daily_series
    (plus the withings/hevy/strava windows further down the module) calls
    fetch_range with is RAW_TIMESERIES, except the one EXPERIMENT_SCOPED caller
    that must stay filtered."""
    always_cross_phase = ("whoop", "strava", "macrofactor", "apple_health", "habitify", "flourishing", "withings", "hevy")
    for source in always_cross_phase:
        cls = tax.SOURCE_CLASS.get(source)
        assert cls in (tax.RAW_TIMESERIES, tax.CROSS_PHASE), f"{source} is {cls}; would silently widen a scoped read"
        assert source_reads_cross_phase(source) is True
    assert tax.classify("USER#matthew#SOURCE#computed_metrics") == tax.EXPERIMENT_SCOPED
    assert source_reads_cross_phase("computed_metrics") is False


# ══════════════════════════════════════════════════════════════════════════════
# 2. hypothesis_engine_lambda.query_range — same idiom
# ══════════════════════════════════════════════════════════════════════════════


def test_hypothesis_engine_query_range_reads_a_raw_timeseries_source_cross_phase(monkeypatch):
    """notion (journal) is RAW_TIMESERIES and sits in COMPUTE_INPUTS['hypothesis-
    engine'] — a fresh cycle must not truncate the 30-day deterministic checks."""
    assert tax.classify("USER#matthew#SOURCE#notion") == tax.RAW_TIMESERIES
    rows = _daily_rows("USER#matthew#SOURCE#notion", "word_count", _ALL_DAYS)
    monkeypatch.setattr(he, "table", PhaseAwareFakeTable(rows))
    out = he.query_range("notion", _WINDOW_START, _WINDOW_END)
    assert len(out) == len(_ALL_DAYS), "a RAW_TIMESERIES source must read across the reset"


def test_hypothesis_engine_query_range_keeps_computed_metrics_filtered(monkeypatch):
    """computed_metrics is added on top of COMPUTE_INPUTS in gather_data and is
    EXPERIMENT_SCOPED — it must stay current-cycle even though the read now goes
    through the shared per-source derivation."""
    assert tax.classify("USER#matthew#SOURCE#computed_metrics") == tax.EXPERIMENT_SCOPED
    rows = _daily_rows("USER#matthew#SOURCE#computed_metrics", "readiness", _ALL_DAYS)
    monkeypatch.setattr(he, "table", PhaseAwareFakeTable(rows))
    out = he.query_range("computed_metrics", _WINDOW_START, _WINDOW_END)
    assert len(out) == len(_AFTER), "an EXPERIMENT_SCOPED source must stay hidden pre-genesis"


def test_hypothesis_engines_compute_inputs_are_all_never_hidden():
    """COMPUTE_INPUTS['hypothesis-engine'] is entirely RAW_TIMESERIES/CROSS_PHASE
    today, so the #3444 fix reaches the whole deterministic-check input set for
    free — a future EXPERIMENT_SCOPED addition would fail this and must be
    re-reasoned about, not silently inherit the cross-phase read."""
    from common.input_manifest import COMPUTE_INPUTS

    for source in COMPUTE_INPUTS["hypothesis-engine"]:
        cls = tax.SOURCE_CLASS.get(source)
        assert cls in (tax.RAW_TIMESERIES, tax.CROSS_PHASE), f"{source} is {cls}; would silently widen a scoped read"
        assert source_reads_cross_phase(source) is True


def test_time_affluences_own_sources_are_never_hidden():
    """The four sources run_time_affluence_weekly reads directly (todoist,
    evening_ritual, the meter's own probe partition, habitify) are all
    RAW_TIMESERIES — the class the Time-Affluence consequence below depends on."""
    for source in ("todoist", "evening_ritual", ta.TIME_AFFLUENCE_SOURCE, "habitify"):
        assert tax.SOURCE_CLASS.get(source) == tax.RAW_TIMESERIES, source
        assert source_reads_cross_phase(source) is True


# ══════════════════════════════════════════════════════════════════════════════
# 3. The Time-Affluence consequence (#1408): never scored a week, until now
# ══════════════════════════════════════════════════════════════════════════════


def _weekly_todoist_history(mondays, genesis):
    """One todoist DATE# row per Monday, with both fields week_open_load and
    week_unscheduled_days need (mirrors tests/test_time_affluence_1408.py's
    _full_window_todoist), tagged phase=pilot for every date before genesis —
    exactly what the reset tagger writes."""
    rows = []
    for i, m in enumerate(mondays):
        row = {
            "pk": "USER#matthew#SOURCE#todoist",
            "sk": "DATE#" + m,
            "date": m,
            "active_count": 5 + i,
            "overdue_count": 0,
            "due_today_count": i % 2,
        }
        if date.fromisoformat(m) < genesis:
            row["phase"] = "pilot"
        rows.append(row)
    return rows


# 13 weeks of Monday history (>= PROXY_WINDOW_WEEKS + 1), all dated well before
# genesis — the shape of a reset that lands mid-cycle with real accumulated
# history behind it, the case the issue's "10 rows, all null since birth" describes.
_TA_GENESIS = date(2026, 8, 3)
_TA_END = _TA_GENESIS + timedelta(days=2)  # the reset happened two days ago
_TA_MONDAYS = [(_TA_GENESIS - timedelta(weeks=w, days=_TA_GENESIS.weekday())).isoformat() for w in range(1, 14)]
_TA_WINDOW_START = (_TA_END - timedelta(weeks=ta.PROXY_WINDOW_WEEKS + 2)).isoformat()  # +1wk margin past the oldest Monday
_TA_WINDOW_END = _TA_END.isoformat()


def test_time_affluence_fixture_is_all_pre_genesis():
    """Non-vacuous anchor: every Monday in the fixture predates genesis, so a
    phase-filtered read sees none of it — the fixture actually models the bug."""
    assert all(date.fromisoformat(m) < _TA_GENESIS for m in _TA_MONDAYS)
    assert len(_TA_MONDAYS) >= ta.PROXY_WINDOW_WEEKS + 1


def test_old_unqualified_query_range_list_call_starves_the_meter():
    """The bug, reproduced directly: the OLD call shape — digest_utils.
    query_range_list with no include_pilot, exactly what both sites used to
    write — sees nothing in this window, so compute_weekly_proxies has no weeks
    to score at all. This is the mechanism behind '10 rows, all null since birth'."""
    rows = _weekly_todoist_history(_TA_MONDAYS, _TA_GENESIS)
    table = PhaseAwareFakeTable(rows)
    old_call = digest_utils.query_range_list(table, "todoist", _TA_WINDOW_START, _TA_WINDOW_END, user_id="matthew")
    assert old_call == [], "the pre-fix call shape must see zero pre-genesis rows"
    weeks = ta.compute_weekly_proxies(old_call, [], [])
    assert weeks == [], "no rows in means no weeks out — the meter had nothing to score"


def test_fixed_query_range_lets_the_meter_score_its_first_week(monkeypatch):
    """The consequence, closed: through the FIXED hypothesis_engine_lambda.
    query_range, the same window sees the full pre-genesis history (todoist is
    RAW_TIMESERIES) and compute_weekly_proxies emits at least one 'scored' week —
    the Time-Affluence Meter's first non-null PROXY week."""
    rows = _weekly_todoist_history(_TA_MONDAYS, _TA_GENESIS)
    monkeypatch.setattr(he, "table", PhaseAwareFakeTable(rows))
    todoist_rows = he.query_range("todoist", _TA_WINDOW_START, _TA_WINDOW_END)
    assert len(todoist_rows) == len(_TA_MONDAYS), "the fixed reader must see the full pre-genesis history"
    weeks = ta.compute_weekly_proxies(todoist_rows, [], [])
    scored = [wk for wk in weeks if wk["state"] == "scored"]
    assert scored, "the meter must score at least one week once its inputs read cross-phase"
    assert all(wk["score"] is not None for wk in scored)


# ══════════════════════════════════════════════════════════════════════════════
# 4. The docstring ledger that recorded these two as relying on the old default
#    (test_genesis_blind_digest_and_readers_2150.py) must be re-read, not left
#    stale — enforced structurally: both callers now pass a non-literal
#    include_pilot, which the AST ratchet extension below (test_gradability_
#    liveness_cross_phase_2023) grades PER_SOURCE_READ, not the old default.
# ══════════════════════════════════════════════════════════════════════════════


def test_both_sites_now_pass_a_derived_include_pilot_not_the_bare_default():
    """Mechanism check, not just outcome: prove the fixed call sites pass a
    non-literal include_pilot (source_reads_cross_phase(source)), the same
    per-call decision monthly_digest_lambda.fetch_range uses — a caller that
    reverted to omitting the kwarg would fail this the same way it fails the
    AST ratchet in test_gradability_liveness_cross_phase_2023."""
    import ast
    import inspect

    for fn in (wc.fetch_range, he.query_range):
        src = inspect.getsource(fn)
        tree = ast.parse(src)
        found_call = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "query_range_list":
                found_call = True
                kw = next((k for k in node.keywords if k.arg == "include_pilot"), None)
                assert kw is not None, f"{fn.__qualname__} must pass include_pilot explicitly"
                assert not (isinstance(kw.value, ast.Constant)), f"{fn.__qualname__} must derive include_pilot per source, not hard-code it"
        assert found_call, f"{fn.__qualname__} no longer calls digest_utils.query_range_list — update this test"
