"""tests/test_staleness_honesty.py — the staleness honesty pack (truth audit 2026-07-10).

Pins the deterministic halves of the audit's findings:

  1. EIGHTSLEEP UTC DOUBLE-STAMP (fix 10): the ingestion framework derived "today"
     in UTC, so after 5 PM PT a refresh_today source fetched TOMORROW's Pacific
     DATE# key and wrote the same night under two dates. The framework now selects
     days in Pacific time — the after-5-PM-PT rollover is the regression pinned here.

  2. FIELD-NOTES FABRICATION (fix 11): the habits gatherer read a nonexistent
     `completion_rate` field off habit_scores records, so a zero-completion week fed
     the model nothing but days_scored=7 — and the published W27 note invented
     "you scored 6 of 7 days". The gatherer now derives the real tier-0 rate and
     states a zero week explicitly in the prompt context.

  3. MACHINE-SPEC LEAK (fix 12): coach report cards rendered raw grader notation
     ("[null-threshold machine spec re-routed to directional] recovery_score
     trend=down (slope=-0.0480), predicted=up") to readers. _reader_reason translates
     at the API boundary.

  4. NO-DATA CIRCADIAN FORECAST (fix 9a): "Tonight's sleep is at risk — act now"
     was scored from 3-of-4 no-data default anchors. Scorers now declare
     measured/unmeasured; the composite covers measured anchors only and refuses to
     score a zero-signal day.
"""

import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "compute"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "intelligence"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

import circadian_compliance_lambda as cc  # noqa: E402
import field_notes_lambda as fnl  # noqa: E402
import ingestion_framework as inf  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as coach_api  # noqa: E402

_PT = ZoneInfo("America/Los_Angeles")


class _QuietLogger:
    def info(self, *a, **k):
        pass

    def warning(self, *a, **k):
        pass


# ── 1. Ingestion framework: Pacific day selection (fix 10) ──────────────────────


def _missing_dates_at(monkeypatch, fake_now_pt):
    monkeypatch.setattr(inf, "pacific_now", lambda: fake_now_pt)
    config = inf.IngestionConfig(source_name="eightsleep", lookback_days=3, refresh_today=True)
    table = FakeDdbTable()  # every date reads as missing (query -> {"Items": []})
    return inf._find_missing_dates(table, config, _QuietLogger())


def test_framework_after_5pm_pt_rollover_stays_on_pacific_day(monkeypatch):
    # 2026-07-10 18:30 PT == 2026-07-11 01:30 UTC. The old UTC "today" made
    # refresh_today fetch 2026-07-11 — a Pacific TOMORROW — which is how the same
    # Eight Sleep night landed under both DATE#2026-07-10 and DATE#2026-07-11.
    missing = _missing_dates_at(monkeypatch, datetime(2026, 7, 10, 18, 30, tzinfo=_PT))
    assert "2026-07-10" in missing  # today (PT) is refreshed
    assert "2026-07-11" not in missing  # tomorrow (PT) is NEVER fetched
    assert max(missing) == "2026-07-10"


def test_framework_before_5pm_pt_unchanged(monkeypatch):
    # Midday PT: UTC and PT agree on the calendar day — behavior identical to before.
    missing = _missing_dates_at(monkeypatch, datetime(2026, 7, 10, 11, 0, tzinfo=_PT))
    assert "2026-07-10" in missing
    assert "2026-07-11" not in missing
    assert min(missing) == "2026-07-07"  # lookback_days=3


# ── 2. Field notes: a zero-completion week reads as zero (fix 11) ───────────────


def _habit_day(date, tier0_pct=None, tier0_done=None, tier0_total=None):
    rec = {"pk": "USER#matthew#SOURCE#habit_scores", "sk": f"DATE#{date}"}
    if tier0_pct is not None:
        rec["tier0_pct"] = tier0_pct
    if tier0_done is not None:
        rec["tier0_done"] = tier0_done
    if tier0_total is not None:
        rec["tier0_total"] = tier0_total
    return rec


def _gather_habits(records, monkeypatch):
    monkeypatch.setattr(fnl, "table", FakeDdbTable())
    monkeypatch.setattr(fnl, "_query_source", lambda src, s, e: records if src == "habit_scores" else [])
    monkeypatch.setattr(fnl, "_latest_item", lambda src: None)
    return fnl.gather_week_data("2026-06-29", "2026-07-05")


def test_zero_completion_week_feeds_honest_zero(monkeypatch):
    records = [_habit_day(f"2026-06-{d}", tier0_pct=0) for d in range(29, 31)] + [
        _habit_day(f"2026-07-0{d}", tier0_pct=0) for d in range(1, 6)
    ]
    data = _gather_habits(records, monkeypatch)
    h = data["habits"]
    assert h["days_scored"] == 7
    assert h["days_with_any_completion"] == 0
    assert h["avg_tier0_completion_pct"] == 0
    assert "zero habit completions" in h["note"]
    # The prompt itself must carry the honest zero — this is what the model reads.
    prompt = fnl.build_prompt("2026-W27", data, [])
    assert "zero habit completions" in prompt
    assert '"days_with_any_completion": 0' in prompt
    # The phantom field that enabled the fabrication is gone from the context.
    assert "completion_rate" not in prompt


def test_normal_week_rates_derive_from_tier0(monkeypatch):
    records = [
        _habit_day("2026-06-29", tier0_pct=80),
        _habit_day("2026-06-30", tier0_pct=100),
        _habit_day("2026-07-01", tier0_done=3, tier0_total=4),  # derived path: 75
    ]
    data = _gather_habits(records, monkeypatch)
    h = data["habits"]
    assert h["days_scored"] == 3
    assert h["days_with_any_completion"] == 3
    assert h["avg_tier0_completion_pct"] == 85  # (80 + 100 + 75) / 3
    assert "note" not in h


# ── 3. Coach report cards: machine-spec reasons translate at the boundary (fix 12)


def test_reader_reason_translates_directional_reroute():
    raw = "[null-threshold machine spec re-routed to directional] recovery_score trend=down (slope=-0.0480), predicted=up"
    out = coach_api._reader_reason(raw)
    assert "[" not in out and "slope" not in out and "trend=" not in out
    assert out == "graded on direction — no numeric threshold was set; recovery score trended down, the call said up"


def test_reader_reason_strips_unknown_machine_prefix():
    out = coach_api._reader_reason("[some other machine tag] sleep held above 7h as predicted")
    assert out == "sleep held above 7h as predicted"


def test_reader_reason_passes_plain_text_through():
    plain = "recovery recovered above baseline as the coach predicted"
    assert coach_api._reader_reason(plain) == plain
    assert coach_api._reader_reason(None) == ""


# ── 4. Circadian forecast: measured anchors only (fix 9a) ───────────────────────


def _no_signal(monkeypatch):
    monkeypatch.setattr(cc, "fetch_journal_today", lambda d: [])
    monkeypatch.setattr(cc, "fetch_source_date", lambda src, d: None)
    monkeypatch.setattr(cc, "fetch_range", lambda src, s, e: [])


def test_circadian_zero_signal_day_refuses_to_score(monkeypatch):
    _no_signal(monkeypatch)
    result = cc.compute_circadian_score("2026-07-10")
    assert result["score"] is None
    assert result["category"] == "unmeasured"
    assert result["measured_count"] == 0
    assert result["weakest_component"] is None
    assert all(c["measured"] is False and c["score"] is None for c in result["components"].values())
    # The old default-anchor sum scored this exact day 44/100 "at risk — act now".
    assert "act now" not in result["prescription"]
    assert "no forecast" in result["prescription"].lower()


def test_circadian_partial_signal_scores_measured_anchors_only(monkeypatch):
    _no_signal(monkeypatch)
    # One real signal: a food log with a 17:00 last meal (5.5h before the 22:30
    # target -> 25/25). Everything else stays unmeasured.
    monkeypatch.setattr(
        cc,
        "fetch_source_date",
        lambda src, d: ({"food_log": [{"logged_at": "17:00"}]} if src == "macrofactor" else None),
    )
    result = cc.compute_circadian_score("2026-07-10")
    assert result["measured_count"] == 1
    assert result["score"] == 100  # 25 of 25 measured points, normalized — not 25+defaults
    assert result["weakest_component"] == "meal_timing"  # weakest among MEASURED only
    assert "1 of 4 anchors measured" in result["prescription"]
    comps = result["components"]
    assert comps["meal_timing"]["measured"] is True
    assert comps["morning_light"]["measured"] is False


def test_circadian_full_signal_matches_percent_scale(monkeypatch):
    monkeypatch.setattr(cc, "fetch_journal_today", lambda d: [])
    monkeypatch.setattr(
        cc,
        "fetch_source_date",
        lambda src, d: ({"food_log": [{"logged_at": "20:30"}]} if src == "macrofactor" else None),
    )
    # 8 nights of identical onsets -> SD 0 min -> 25/25 measured consistency.
    monkeypatch.setattr(cc, "fetch_range", lambda src, s, e: [{"sleep_start": "22:00"} for _ in range(8)])
    result = cc.compute_circadian_score("2026-07-10")
    # meal 20:30 -> 2h before 22:30 target -> 10 pts; consistency 25. 35/50 -> 70.
    assert result["measured_count"] == 2
    assert result["score"] == 70
    assert result["category"] == "good"
