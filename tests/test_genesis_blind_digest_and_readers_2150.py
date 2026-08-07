"""tests/test_genesis_blind_digest_and_readers_2150.py — #2150: the genesis-blind
remainder #2109 deliberately left as declared debt.

#2109 fixed the compute layer's seven `fetch_range`/`fetch_series`/inventory
readers to derive `include_pilot` per source from `experiment.phase_filter.
source_reads_cross_phase` instead of applying the ADR-058 phase filter
unconditionally. Three sites were left in `_KNOWN_CROSS_CYCLE_DEBT` on purpose
(#2109 was scoped ahead of a same-day reset, and each of these touches a
different Lambda with a different deploy surface):

  * `lambdas/common/digest_utils.py::query_range` / `query_range_list` — the ROOT
    ENABLER: the shared paginated raw-source reader took no `include_pilot`
    parameter at all, so no caller could opt in even if it wanted to.
  * `lambdas/emails/monthly_digest_lambda.py::fetch_range` — its own local
    reader (does not go through digest_utils), driving the 30d current-vs-
    prior-month comparison arms and the 60d Strava Banister window. In a reset
    month the prior-month arm sat entirely pre-genesis and blanked.
  * `lambdas/web/site_api_vitals.py::handle_timeline` — the SOURCE#life_events
    query is RAW_TIMESERIES (those rows caption the transformation arc), so a
    reset hid every narrative annotation predating it while the weight line
    (already genesis-clamped via EXPERIMENT_START) stayed intact.

The fix is the same #2109 idiom throughout: `include_pilot` is derived per
source from `phase_taxonomy` (via `source_reads_cross_phase`) rather than fixed
at the call site, so a call on an EXPERIMENT_SCOPED source (computed_metrics,
experiments, character_sheet) keeps the filter it needs while a call on a
never-hidden source (whoop, strava, life_events, ...) reads across the reset.
digest_utils' two readers get a slightly different shape: they're the shared
chokepoint many unrelated digests call expecting the pre-#2150 default-filtered
behaviour, so `include_pilot` there is a plain pass-through parameter
(default False) rather than a derivation baked into the function itself — the
same shape as `site_api_common._query_source`.

Every date here is PINNED (`_GENESIS`); nothing does now-math against the wall
clock, so this file cannot start failing on a calendar boundary.
"""

from __future__ import annotations

import json
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
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT / "lambdas" / "emails"))

import monthly_digest_lambda as md  # noqa: E402
from common import digest_utils  # noqa: E402
from experiment import phase_taxonomy as tax  # noqa: E402
from experiment.phase_filter import source_reads_cross_phase  # noqa: E402
from test_genesis_blind_reads_2080_2081 import PhaseAwareFakeTable, _rows  # noqa: E402
from web import site_api_vitals as vitals  # noqa: E402

# Pinned clock — the reset happened this morning, the worst case for this
# defect class and the one cycle 12 actually shipped (a same-day genesis).
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
# 1. digest_utils.query_range / query_range_list — the root enabler
# ══════════════════════════════════════════════════════════════════════════════


def test_query_range_default_still_hides_pilot_rows():
    """Regression pin: omitting include_pilot must keep the pre-#2150 behaviour
    every existing caller (weekly_digest, wednesday_chronicle, hypothesis_engine,
    challenge_generator, partner_email, weekly_plate, nutrition_review,
    weekly_correlation_compute, chronicle_data) relies on."""
    rows = _daily_rows("USER#matthew#SOURCE#whoop", "hrv", _ALL_DAYS)
    table = PhaseAwareFakeTable(rows)
    out = digest_utils.query_range(table, "whoop", _WINDOW_START, _WINDOW_END)
    assert len(out) == len(_AFTER), "default query_range must still hide pilot-tagged pre-genesis rows"
    assert all(date.fromisoformat(d) >= _GENESIS for d in out)


def test_query_range_include_pilot_true_sees_the_full_history():
    rows = _daily_rows("USER#matthew#SOURCE#whoop", "hrv", _ALL_DAYS)
    table = PhaseAwareFakeTable(rows)
    out = digest_utils.query_range(table, "whoop", _WINDOW_START, _WINDOW_END, include_pilot=True)
    assert len(out) == len(_ALL_DAYS)


def test_query_range_list_default_still_hides_pilot_rows():
    rows = _daily_rows("USER#matthew#SOURCE#hevy", "workout_count", _ALL_DAYS)
    table = PhaseAwareFakeTable(rows)
    out = digest_utils.query_range_list(table, "hevy", _WINDOW_START, _WINDOW_END)
    assert len(out) == len(_AFTER)


def test_query_range_list_include_pilot_true_sees_the_full_history():
    rows = _daily_rows("USER#matthew#SOURCE#hevy", "workout_count", _ALL_DAYS)
    table = PhaseAwareFakeTable(rows)
    out = digest_utils.query_range_list(table, "hevy", _WINDOW_START, _WINDOW_END, include_pilot=True)
    assert len(out) == len(_ALL_DAYS)


# ══════════════════════════════════════════════════════════════════════════════
# 2. monthly_digest_lambda.fetch_range — per-source, the #2109 idiom
# ══════════════════════════════════════════════════════════════════════════════


def test_fetch_range_reads_a_raw_timeseries_source_cross_phase(monkeypatch):
    """strava is RAW_TIMESERIES and sits in monthly_digest's own `sources` list
    (the current-vs-prior-month comparison + the 60d Banister window) — a fresh
    cycle's prior-month arm must not blank."""
    assert tax.classify("USER#matthew#SOURCE#strava") == tax.RAW_TIMESERIES
    rows = _daily_rows("USER#matthew#SOURCE#strava", "moving_time_seconds", _ALL_DAYS)
    monkeypatch.setattr(md, "table", PhaseAwareFakeTable(rows))
    out = md.fetch_range("strava", _WINDOW_START, _WINDOW_END)
    assert len(out) == len(_ALL_DAYS), "a RAW_TIMESERIES source must read across the reset"


def test_fetch_range_keeps_an_experiment_scoped_source_filtered(monkeypatch):
    """computed_metrics is EXPERIMENT_SCOPED (the #2109 negative-case source) —
    derived intelligence the reset tombstones on purpose, so it must stay
    current-cycle even though the read now goes through the shared derivation."""
    assert tax.classify("USER#matthew#SOURCE#computed_metrics") == tax.EXPERIMENT_SCOPED
    rows = _daily_rows("USER#matthew#SOURCE#computed_metrics", "readiness", _ALL_DAYS)
    monkeypatch.setattr(md, "table", PhaseAwareFakeTable(rows))
    out = md.fetch_range("computed_metrics", _WINDOW_START, _WINDOW_END)
    assert len(out) == len(_AFTER), "an EXPERIMENT_SCOPED source must stay hidden pre-genesis"


def test_fetch_range_window_still_bounds_a_cross_phase_read(monkeypatch):
    """Cross-phase is not unbounded — the date window is still what answers
    'recent', exactly as the #2109 contract states."""
    rows = _daily_rows("USER#matthew#SOURCE#strava", "moving_time_seconds", _ALL_DAYS)
    monkeypatch.setattr(md, "table", PhaseAwareFakeTable(rows))
    assert md.fetch_range("strava", "2020-01-01", "2020-01-05") == []


def test_monthly_digests_own_source_list_is_all_never_hidden():
    """The set this issue actually closes: every source monthly_digest's
    gather_all calls fetch_range with is RAW_TIMESERIES or CROSS_PHASE, so the
    #2150 fix reaches the whole current-vs-prior-month comparison for free."""
    sources = ["whoop", "withings", "strava", "eightsleep", "hevy", "macrofactor", "todoist", "chronicling"]
    for source in sources:
        cls = tax.SOURCE_CLASS.get(source)
        assert cls in (tax.RAW_TIMESERIES, tax.CROSS_PHASE), f"{source} is {cls}; would silently widen a scoped read"
        assert source_reads_cross_phase(source) is True


# ══════════════════════════════════════════════════════════════════════════════
# 3. site_api_vitals.handle_timeline — three calls, one per-source decision each
# ══════════════════════════════════════════════════════════════════════════════


def _life_event(d: date, title: str, pilot: bool):
    row = {
        "pk": "USER#matthew#SOURCE#life_events",
        "sk": f"DATE#{d.isoformat()}#EVENT#{title}",
        "date": d.isoformat(),
        "title": title,
        "type": "milestone",
        "emotional_weight": 4,
    }
    if pilot:
        row["phase"] = "pilot"
    return row


def _experiment(d: date, name: str, pilot: bool):
    row = {
        "pk": "USER#matthew#SOURCE#experiments",
        "sk": f"EXP#{name}",
        "name": name,
        "start_date": d.isoformat(),
        "status": "active",
    }
    if pilot:
        row["phase"] = "pilot"
    return row


def _setup_timeline(monkeypatch, rows):
    monkeypatch.setattr(vitals, "EXPERIMENT_START", _GENESIS_ISO)
    table = PhaseAwareFakeTable(rows)
    monkeypatch.setattr(vitals, "table", table)
    # Isolate handle_timeline from the weight series / profile reads, which are
    # not part of this issue — the weight line is already genesis-clamped via
    # EXPERIMENT_START and untouched by #2150.
    monkeypatch.setattr(vitals, "_query_source", lambda *a, **k: [])
    monkeypatch.setattr(vitals, "_get_profile", lambda: {})
    return table


def test_timeline_shows_a_pre_genesis_life_event_caption(monkeypatch):
    """The acceptance instance: life_events is RAW_TIMESERIES, so a caption
    written before genesis must still render on the transformation timeline."""
    rows = [
        _life_event(_GENESIS - timedelta(days=30), "Started the platform", pilot=True),
        _life_event(_GENESIS + timedelta(days=1), "Day 2 workout", pilot=False),
    ]
    _setup_timeline(monkeypatch, rows)
    body = json.loads(vitals.handle_timeline()["body"])
    titles = {e["title"] for e in body["timeline"]["life_events"]}
    assert "Started the platform" in titles, "a pre-genesis life-event caption vanished after the reset"
    assert "Day 2 workout" in titles


def test_timeline_hides_a_pre_genesis_experiment(monkeypatch):
    """The negative case at the same call site: experiments is EXPERIMENT_SCOPED,
    so a pre-genesis experiment record must stay hidden — unchanged behaviour."""
    rows = [
        _experiment(_GENESIS - timedelta(days=20), "pilot-era-experiment", pilot=True),
        _experiment(_GENESIS + timedelta(days=1), "cycle-12-experiment", pilot=False),
    ]
    _setup_timeline(monkeypatch, rows)
    body = json.loads(vitals.handle_timeline()["body"])
    names = {e["name"] for e in body["timeline"]["experiments"]}
    assert "cycle-12-experiment" in names
    assert "pilot-era-experiment" not in names, "an EXPERIMENT_SCOPED record leaked across the reset"


def test_timeline_life_events_call_carries_no_filter_expression(monkeypatch):
    """The mechanism, not just the outcome: the life_events query must be the
    one of the three with no phase FilterExpression at all."""
    table = _setup_timeline(monkeypatch, [])
    vitals.handle_timeline()
    assert len(table.query_calls) == 3, "handle_timeline must issue exactly its three direct queries"
    life_events_call, experiments_call, character_sheet_call = table.query_calls
    assert "FilterExpression" not in life_events_call, "life_events must read cross-phase"
    assert "FilterExpression" in experiments_call, "experiments must stay phase-filtered"
    assert "FilterExpression" in character_sheet_call, "character_sheet must stay phase-filtered"


def test_the_three_timeline_sources_agree_with_the_taxonomy():
    """Guard the derivation, not just today's fixture: life_events is the only
    one of handle_timeline's three raw sources that is never-hidden."""
    assert tax.classify("USER#matthew#SOURCE#life_events") == tax.RAW_TIMESERIES
    assert tax.classify("USER#matthew#SOURCE#experiments") == tax.EXPERIMENT_SCOPED
    assert tax.classify("USER#matthew#SOURCE#character_sheet") == tax.EXPERIMENT_SCOPED
    assert source_reads_cross_phase("life_events") is True
    assert source_reads_cross_phase("experiments") is False
    assert source_reads_cross_phase("character_sheet") is False


def test_handle_timeline_routes_all_three_calls_through_the_shared_decision():
    """A revert-catcher at the source level (the #2109 idiom): none of the three
    calls may hard-code include_pilot — each must derive it from
    source_reads_cross_phase, so a call site added later inherits the right
    behaviour from its source's own taxonomy class."""
    import ast

    # #1654: the timeline body moved to web/site_api_journey.py behind the unchanged
    # site_api_vitals facade; resolve_handler follows the facade's delegator to it.
    from site_api_family import resolve_handler

    _path, src, func = resolve_handler("site_api_vitals", "handle_timeline")
    seg = (ast.get_source_segment(src, func) or "").replace(" ", "").replace("\n", "")
    assert seg.count("with_phase_filter(") == 3
    assert seg.count("source_reads_cross_phase(") == 3, "all three raw calls must derive include_pilot from the taxonomy"
