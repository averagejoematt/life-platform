"""tests/test_brief_compact_6240.py — the compact Morning Brief replaces the whole email (#6240, owner ruling 2026-11-23).

What is pinned, by the ruling's own sections:

  §1 THE BUDGET — ≤ 250 words outside verified alerts, ≤ 3 metrics, ≤ 2 recommendations (ceilings, not quotas), one
     voice, one detail link, a plain-text part, inline-styled tables; a quiet day of 50–100 words with no recommendation.
  §2 PENDING IS NOT MISSED — on the email AND on the public day page, read through ONE shared determination.
  §3 EXPLICIT ACTIVATION — only the exact word "compact" selects it; absent / unreadable / malformed is OFF (main's
     behaviour, pinned); "off" and "hybrid" send what they sent before, and compact never appends the legacy render.
  §4 SAFE FAILURE — a render failure or a hard budget violation sends a short failure notice (never the legacy report),
     keeps the verified alerts, records `fallback` on the send row and raises after the send (the Errors alarms).
  §5 NOTHING IMPORTANT HIDDEN — verified critical alerts survive the word ceiling; no clearance reading of a score; no
     categorical "nothing" while data is unknown; "what changed" only past the stated thresholds.
  §6 REPETITION — an unchanged repeat is suppressed; it returns when its evidence changes; nothing is manufactured.
  §7 THE RENDERED EXPERIENCE — the checker on the real render, a NEGATIVE CONTROL (the long report's shape fails it),
     mutation proofs for every hard rule, and the real layout at 390 px and 1280 px in a headless browser.

Fixtures are synthetic and wire-shaped (Decimal numbers, DATE# keys, the real field names). No AWS: the handler runs
inside test_daily_brief_behavior's fakes.
"""

from __future__ import annotations

import json
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from coach import brief_recommendations as rr
from common import food_log_state
from content import brief_budget as bb, brief_compact as bc, brief_editorial, brief_hybrid
from emails import brief_trial as bt

DAY = "2026-11-08"  # the data day (a Sunday)
TODAY = "2026-11-09"
SHORT = "Mon Nov 9"
SITE = "https://averagejoematt.com"
PERSONA = bc.persona_names()


def _whoop(day, rec, **kw):
    return {"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#" + day, "date": day, "recovery_score": Decimal(str(rec)), **kw}


WEEK = [("2026-11-02", 52), ("2026-11-03", 61), ("2026-11-04", 49), ("2026-11-05", 57), ("2026-11-06", 72), ("2026-11-07", 55), (DAY, 58)]


def _data(**over):
    d = {
        "date": DAY,
        "whoop": _whoop(DAY, 58, hrv=Decimal("51.2"), sleep_duration_hours=Decimal("7.4")),
        "whoop_today": _whoop(TODAY, 66, hrv=Decimal("53.0")),
        "whoop_7d": [_whoop(day, r) for day, r in WEEK] + [{"sk": "DATE#" + DAY + "#WORKOUT#w1", "strain": Decimal("9.1")}],
        "hrv": {"hrv_yesterday": Decimal("51.2"), "hrv_30d": Decimal("55.0")},
        "latest_weight": Decimal("291.4"),
        "weight_recency": {"current_weight_as_of": DAY, "current_weight_is_stale": False},
        "weekly_rate_lbs": Decimal("-2.1"),
        "weekly_rate_ci_low": Decimal("-2.6"),
        "weekly_rate_ci_high": Decimal("-1.5"),
        "computed_metrics": {"acwr": Decimal("1.05"), "acwr_zone": "safe", "acwr_alert": False},
        "anomaly": {},
        "strava": {"activities": [{"sport_type": "Ride", "moving_time_seconds": Decimal("3600")}]},
        "hevy": [{"sk": "DATE#" + DAY + "#WORKOUT#a1", "title": "Upper"}],
        # the newest export landed the day BEFORE the data day: the data day's food is pending, never "not logged"
        "brief_editorial": {"nutrition": {"last_arrival_day": "2026-11-07", "last_intake_day": "2026-11-06"}},
    }
    d.update(over)
    return d


def _status(data, **over):
    s = bt.status_inputs(data, data.get("computed_metrics"), {}, {}, 64, "yellow", 3, 70, "C", [])
    s.update(sessions=1, minutes=95)  # the day's count is training.session_count's (pinned in its own tests)
    s.update(over)
    return s


GUIDANCE = [
    "🚶 Steps were low on Sunday — a 30-minute walk after lunch is the simplest move today.",
    "🥩 Protein logged as zero — pair your first meal with a 50 g shake.",
    "💧 Hydration ran light — keep a bottle at your desk this afternoon.",
    "📋 Open the food log and enter one meal before noon.",
]


def _view(data=None, status=None, guidance=GUIDANCE, history=None, prev_weight=("2026-11-07", 291.9), prev_acwr=1.02, alerts=None):
    data = data or _data()
    status = status or _status(data)
    return bt.compact_view(
        data=data,
        status=status,
        guidance_items=guidance,
        history=history or {},
        alerts=bc.critical_alerts(data) if alerts is None else alerts,
        previous_weight=prev_weight,
        previous_acwr=prev_acwr,
        site_url=SITE,
        persona=PERSONA,
    )


def _render(view):
    return bc.render_html(view, SHORT), bc.render_text(view, SHORT)


def _check(view):
    html, text = _render(view)
    return bb.check(html, text, persona_names=PERSONA, pending_inputs=tuple(view.pending_inputs))


def _quiet_data(**over):
    base = {
        "brief_editorial": {"nutrition": {"last_arrival_day": TODAY, "last_intake_day": DAY}},
        "macrofactor": {"total_calories_kcal": Decimal("2010")},
    }
    return _data(**{**base, **over})


# ══════════════════════════════════════════════════════════════════════════════
# §1 the budget, on the rendered email
# ══════════════════════════════════════════════════════════════════════════════


def test_a_busy_day_renders_inside_every_ceiling_with_no_violation():
    view = _view()
    html, text = _render(view)
    m = bb.measure(html, text)
    assert m["words"] <= bc.WORD_CEILING and m["text_words"] <= bc.WORD_CEILING
    assert m["n_metrics"] == 3 and m["n_recs"] <= bc.REC_CEILING
    assert _check(view) == []
    assert html.count("data-detail-link") == 1 and SITE + "/data/day/" + DAY + "/" in html


def test_three_new_recommendations_are_capped_at_two():
    many = [
        "🚶 A 30-minute walk after lunch is the simplest move today.",
        "💧 Keep a water bottle at your desk this afternoon.",
        "📓 Write two lines in your journal tonight.",
    ]
    view = _view(data=_quiet_data(), guidance=many)
    assert len(view.recs) == bc.REC_CEILING and bb.measure(_render(view)[0])["n_recs"] == bc.REC_CEILING


def test_the_ceilings_are_not_quotas_and_nothing_is_manufactured():
    view = _view(guidance=[])
    html, _ = _render(view)
    assert view.recs == [] and 'data-rec="' not in html  # no guidance -> no recommendation slot filled
    assert bb.measure(html)["n_recs"] == 0


def test_one_editorial_voice_a_persona_named_recommendation_is_dropped_not_shown():
    named = PERSONA[0] + " says a 30-minute walk after lunch is the move today."
    view = _view(guidance=[named])
    html, text = _render(view)
    assert view.dropped_voice == 1 and view.recs == []
    for name in PERSONA:
        assert name not in html and name not in text, name
    assert "Board of Directors" in PERSONA and len(PERSONA) >= 8  # the registry was read, not an empty list


def test_the_email_is_inline_styled_tables_with_a_plain_text_part():
    html, text = _render(_view())
    assert '<table role="presentation"' in html and "<style" not in html and "class=" not in html
    assert text.strip() and "Morning Brief" in text and bb.words(text) <= bc.WORD_CEILING


def test_no_legacy_section_marker_appears_in_the_compact_email():
    html, _ = _render(_view())
    for marker in bb.LEGACY_MARKERS:
        assert marker not in html, marker


# ══════════════════════════════════════════════════════════════════════════════
# §2 pending is not missed — the email, the day page, one determination
# ══════════════════════════════════════════════════════════════════════════════


def test_a_pending_food_export_is_never_worded_as_missed_and_the_lead_is_conditional():
    for view in (_view(), _view(guidance=[])):
        html, text = _render(view)
        assert view.pending_inputs == ["food"]
        assert "has not arrived" in text and "data on its way" in text
        assert not bc.MISSED_RE.search(text) and not bc.MISSED_RE.search(html)
        assert bc.QUIET_LEAD not in html and not bb.CATEGORICAL_RE.search(html)
        assert all(r.key not in brief_hybrid.FOOD_KEYS for r in view.recs)  # food asks written from a pending log: held back
    assert view.lead_kind == "unknown" and "not known yet" in view.lead  # no decision: the lead says something is unknown


def test_an_arrived_export_without_the_day_is_not_pending():
    data = _data(brief_editorial={"nutrition": {"last_arrival_day": TODAY, "last_intake_day": "2026-11-07"}})
    view = _view(data=data)
    assert view.pending_inputs == [] and "has not arrived" not in bc.render_text(view, SHORT)


def test_the_brief_and_the_day_page_read_one_determination(monkeypatch):
    """The contract the ruling asks for (§2: the email and its destination cannot contradict each other)."""
    calls = []
    real = food_log_state.arrival

    def spy(day, last):
        calls.append((day, last))
        return real(day, last)

    monkeypatch.setattr(food_log_state, "arrival", spy)
    assert brief_editorial.nutrition_arrival(_data()) == "not_arrived"
    brief_calls = len(calls)

    class _T:
        def query(self, **kw):
            return {
                "Items": [{"sk": "DATE#2026-11-06", "total_calories_kcal": Decimal("1900"), "ingested_at": "2026-11-07T15:00:00+00:00"}]
            }

    block = food_log_state.served_block(_T(), "USER#matthew#SOURCE#", "2026-11-05", TODAY, ["2026-11-05", "2026-11-06"])
    assert brief_calls >= 1 and len(calls) > brief_calls, "both the brief and the API answer through food_log_state.arrival"
    assert block == {"pending_days": ["2026-11-07", "2026-11-08", TODAY], "arrival_known": True}
    # the same grid through both doors: the brief's "not_arrived" <=> the page's "pending"
    for day in ("2026-11-05", "2026-11-06", "2026-11-07", "2026-11-08"):
        for last in ("2026-11-05", "2026-11-07", "2026-11-09", None):
            data = {"date": day, "brief_editorial": {"nutrition": {"last_arrival_day": last}}}
            page = food_log_state.pending_days([day], [], last)
            assert (brief_editorial.nutrition_arrival(data) == "not_arrived") == (page == [day]), (day, last)


def test_the_site_api_serves_the_pending_days_additively():
    from web import site_api_nutrition as sn

    rows = [
        {"pk": "USER#matthew#SOURCE#macrofactor", "sk": "DATE#2026-11-06", "date": "2026-11-06", "total_calories_kcal": Decimal("1900")},
    ]

    class _T:
        def query(self, **kw):
            return {"Items": [dict(rows[0], ingested_at="2026-11-07T15:00:00+00:00")]}

    g = {
        "_query_source": lambda src, a, b, **k: [dict(r) for r in rows] if src == "macrofactor" else [],
        "_experiment_date": lambda n: "2026-11-01",
        "EXPERIMENT_START": "2026-11-01",
        "table": _T(),
    }
    body = json.loads(sn.nutrition_overview(_g=g, window=("2026-11-01", TODAY))["body"])
    assert body["food_log"]["arrival_known"] is True
    assert body["food_log"]["pending_days"] == ["2026-11-07", "2026-11-08", TODAY]
    g["table"] = None  # an unreadable source claims nothing either way
    body = json.loads(sn.nutrition_overview(_g=g, window=("2026-11-01", TODAY))["body"])
    assert body["food_log"] == {"pending_days": [], "arrival_known": False}


def test_the_day_page_says_pending_for_a_day_the_api_marks_pending():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import publish_snapshot_day as pd

    cover = {"workouts": {DAY}, "sleep": {DAY}, "nutrition": {DAY}}
    pending = pd.day_detail(DAY, workouts=[], night_row=None, food_row=None, covered=cover, gap_days=set(), pending_food={DAY})
    missed = pd.day_detail(DAY, workouts=[], night_row=None, food_row=None, covered=cover, gap_days=set(), pending_food=set())
    assert pending["food_state"] == "pending" and missed["food_state"] == "not logged"
    assert "pending" in pd.FOOD_STATES
    assert pd.pending_of({"food_log": {"pending_days": [DAY, "bad"], "arrival_known": True}}) == {DAY}
    assert pd.pending_of({"food_log": {"pending_days": [DAY], "arrival_known": False}}) == set()
    assert pd.pending_of({"nutrition_trend": []}) == set()  # an API without the field: the page says what it said


# ══════════════════════════════════════════════════════════════════════════════
# freshness, contradiction, attribution
# ══════════════════════════════════════════════════════════════════════════════


def test_every_metric_carries_its_source_and_the_day_it_describes():
    html, _ = _render(_view())
    for key, src in (("recovery", "Whoop"), ("weight", "Withings"), ("training", "Hevy and Strava")):
        assert f'data-metric="{key}" data-source="{src}"' in html, key
    assert 'data-as-of="' + TODAY + '"' in html  # this morning's recovery is labelled with this morning


def test_a_stale_weight_is_dropped_and_named_and_an_unscored_morning_is_labelled():
    data = _data(whoop_today={}, weight_recency={"current_weight_as_of": "2026-10-20", "current_weight_is_stale": True})
    view = _view(data=data)
    keys = [m.key for m in view.metrics]
    assert "weight" not in keys and any("too old to show as current" in u for u in view.unknown)
    rec = next(m for m in view.metrics if m.key == "recovery")
    assert rec.as_of == DAY and "the morning of Sunday, November 8" in rec.text
    assert any("was not scored" in u for u in view.unknown)


def test_one_number_per_quantity_and_the_lead_cannot_contradict_the_lines_below():
    for view in (_view(), _view(data=_quiet_data(), guidance=[]), _view(guidance=[])):
        html, text = _render(view)
        assert not [v for v in bb.check(html, text, persona_names=PERSONA) if v.code == "contradiction"]
        if view.lead_kind == "quiet":
            assert not view.unknown and not view.recs and not view.has_change and not view.alerts


# ══════════════════════════════════════════════════════════════════════════════
# §5 what changed, alerts, clearance
# ══════════════════════════════════════════════════════════════════════════════


def test_what_changed_uses_the_stated_thresholds_not_day_to_day_noise():
    # recovery inside the previous seven mornings' range: no change
    assert _view(data=_quiet_data(), guidance=[]).changed == bc.NO_CHANGE
    # outside it: a change, stated against the range
    high = _view(data=_quiet_data(whoop_today=_whoop(TODAY, 81)), guidance=[])
    assert high.has_change and "above the previous week's range (49 to 72)" in high.changed
    # too little history: never a change
    short = _quiet_data(whoop_7d=[_whoop("2026-11-07", 50), _whoop(DAY, 51)], whoop_today=_whoop(TODAY, 95))
    assert not _view(data=short, guidance=[]).has_change
    # weight: under the day-to-day threshold is noise, at it is a change
    assert not _view(data=_quiet_data(), guidance=[], prev_weight=("2026-11-07", 291.4 + bc.WEIGHT_DAY_NOISE_LB - 0.1)).has_change
    assert _view(data=_quiet_data(), guidance=[], prev_weight=("2026-11-07", 291.4 + bc.WEIGHT_DAY_NOISE_LB)).has_change
    # load: a crossing out of the band is a change; sitting outside it is not new
    low = {"acwr": Decimal("0.72"), "acwr_zone": "detraining", "acwr_alert": True}
    assert _view(data=_quiet_data(computed_metrics=low), guidance=[], prev_acwr=1.0).has_change
    assert not _view(data=_quiet_data(computed_metrics=low), guidance=[], prev_acwr=0.75).has_change


def _alert_data():
    rhythm = [
        "Irregular rhythm notifications: 1 recorded in the 7 days to " + DAY + " (0 recorded in the 7 days before).",
        "Events in the 7 days to " + DAY + ", newest first: " + DAY + " 06:12 irregular rhythm notification.",
        "Counts are of stored records.",
        "Discuss with your clinician.",
    ]
    data = _data(
        computed_metrics={"acwr": Decimal("1.62"), "acwr_zone": "danger", "acwr_alert": True},
        anomaly={
            "severity": "high",
            "anomalous_metrics": [
                {"source": "whoop", "field": "resting_heart_rate", "label": "Resting heart rate"},
                {"source": "whoop", "field": "hrv", "label": "HRV"},
                {"source": "withings", "field": "weight_lbs", "label": "Weight"},
                {"source": "apple_health", "field": "steps", "label": "Steps"},
            ],
        },
    )
    return data, rhythm


def test_verified_critical_alerts_are_kept_even_past_the_word_ceiling():
    data, rhythm = _alert_data()
    alerts = bc.critical_alerts(data, rhythm)
    assert [a.kind for a in alerts] == ["training_load", "anomaly", "heart_rhythm"]
    view = _view(data=data, alerts=alerts)
    html, text = _render(view)
    m = bb.measure(html, text)
    assert m["n_critical_alerts"] == 3 and m["n_metrics"] <= bc.METRIC_CEILING  # alerts are not metrics
    assert m["words"] + m["alert_words"] > bc.WORD_CEILING, "the fixture must push the whole email past 250 words"
    assert m["words"] <= bc.WORD_CEILING and not [v for v in _check(view) if v.hard]  # it still sends, alerts intact
    assert "1.62" in html and "Resting heart rate" in html and "irregular rhythm notification" in html
    assert view.lead_kind == "alert" and not bb.CATEGORICAL_RE.search(html)


def test_what_is_not_a_verified_critical_alert():
    single = _data(anomaly={"severity": "none", "anomalous_metrics": [{"source": "withings", "field": "weight_lbs", "label": "Weight"}]})
    # the detector's multi-source verdict on a weigh-in below baseline (the goal's direction) plus a habit dip is not one
    goal_and_habits = _data(
        anomaly={
            "severity": "moderate",
            "anomalous_metrics": [
                {"source": "withings", "field": "weight_lbs", "label": "Weight", "direction": "low"},
                {"source": "habitify", "field": "completion_pct", "label": "P40 Habits", "direction": "low"},
            ],
        }
    )
    assert bc.critical_alerts(goal_and_habits) == []
    old_rhythm = ["Events in the 7 days to " + DAY + ", newest first: 2026-11-03 06:12 irregular rhythm notification."]
    detraining = _data(computed_metrics={"acwr": Decimal("0.7"), "acwr_zone": "detraining", "acwr_alert": True})
    assert bc.critical_alerts(single, old_rhythm) == [] and bc.critical_alerts(detraining) == []


def test_no_sentence_reads_a_score_as_clearance():
    cleared = "✅ Recovery is green — you're cleared for hard training today."
    view = _view(data=_quiet_data(whoop_today=_whoop(TODAY, 96)), guidance=[cleared])
    html, text = _render(view)
    assert view.dropped_clearance == 1 and not bc.CLEARANCE_RE.search(html) and not bc.CLEARANCE_RE.search(text)
    assert "Ready: hard training" not in html  # the readiness call (a fixed-weight, unvalidated score) is not shown


# ══════════════════════════════════════════════════════════════════════════════
# §6 repetition
# ══════════════════════════════════════════════════════════════════════════════


def test_an_unchanged_repeat_is_suppressed_and_counted():
    walk = ["🚶 A 30-minute walk after lunch is the simplest move today."]
    view = _view(data=_quiet_data(), guidance=walk, history={"2026-11-07": {"movement"}})
    assert view.recs == [] and view.repeats_suppressed == 1


def test_a_repeat_returns_when_its_evidence_changed_and_says_why():
    easy = ["🧘 Make today a recovery day — easy zone 2 only."]
    hist = {"2026-11-07": {"recovery_day"}}
    same = _view(data=_quiet_data(), guidance=easy, history=hist)
    assert same.recs == [] and same.repeats_suppressed == 1
    dropped = _view(data=_quiet_data(whoop_today=_whoop(TODAY, 31)), guidance=easy, history=hist)
    assert [r.status for r in dropped.recs] == ["REPEAT"] and dropped.recs[0].changed_because
    html, text = _render(dropped)
    assert "Shown again because" in text and 'data-changed-because="1"' in html
    assert not [v for v in _check(dropped) if v.code == "unchanged_repeat"]


def test_a_due_follow_up_takes_a_recommendation_slot_never_a_third():
    view = _view(data=_quiet_data())
    view.follow_up = {"text": "Book the blood panel", "follow_up_on": TODAY, "date": "2026-11-02"}
    bt._fit_follow_up(view)
    html, _ = _render(view)
    assert bb.measure(html)["n_recs"] <= bc.REC_CEILING and "Follow-up due" in html


# ══════════════════════════════════════════════════════════════════════════════
# a quiet day
# ══════════════════════════════════════════════════════════════════════════════


def test_a_quiet_day_is_fifty_to_one_hundred_words_with_no_recommendation():
    view = _view(data=_quiet_data(), guidance=[])
    html, text = _render(view)
    m = bb.measure(html, text)
    assert view.lead_kind == "quiet" and view.lead == bc.QUIET_LEAD and m["quiet_day"]
    assert bc.QUIET_WORDS[0] <= m["words"] <= bc.QUIET_WORDS[1], m["words"]
    assert m["n_recs"] == 0 and _check(view) == []
    assert bc.subject(view, SHORT) == "Morning Brief | Mon Nov 9 | Nothing changed, nothing needed"


# ══════════════════════════════════════════════════════════════════════════════
# §7 the checker: negative control + mutation proofs
# ══════════════════════════════════════════════════════════════════════════════


def _legacy_html():
    """The CURRENT long report's shape, through the real html_builder: synthetic coach reads of about 500 words."""
    from content import html_builder as hb

    long_read = " ".join(["Your recovery trend and the protein floor both deserve a closer look this week."] * 38)
    kw = dict(
        data={"date": DAY, "hrv": {"hrv_7d": None, "hrv_30d": None}},
        profile={"calorie_target": 1500, "journey_start_date": "2024-01-01", "habit_registry": {}},
        day_grade_score=62,
        grade="C",
        component_scores={},
        component_details={},
        readiness_score=64,
        readiness_colour="yellow",
        tldr_guidance={"tldr": "A steady day.", "guidance": GUIDANCE},
        bod_insight=long_read,
        training_nutrition={"training": long_read, "nutrition": long_read},
        journal_coach_text="",
        mvp_streak=0,
        full_streak=0,
        vice_streaks={},
    )
    coaches = {k: long_read for k in ("sleep_coach_v2_text", "nutrition_coach_v2_text", "mind_coach_v2_text", "physical_coach_v2_text")}
    return hb.build_html(**kw, **coaches)


def test_negative_control_the_long_report_shape_fails_the_checker():
    html = _legacy_html()
    codes = {v.code for v in bb.check(html, "", persona_names=PERSONA, pending_inputs=("food",))}
    assert {"words_over", "legacy_section", "voice", "text_missing", "detail_link"} <= codes, codes


MUTATIONS = {
    # code -> a mutation of a clean compact render (html, text) that must trip exactly that rule
    "words_over": lambda h, t: (
        h.replace("</td></tr></table></td>", "<p>" + "extra words here " * 90 + "</p></td></tr></table></td>", 1),
        t,
    ),
    "text_words_over": lambda h, t: (h, t + " more" * 260),
    "text_missing": lambda h, t: (h, ""),
    "metrics_over": lambda h, t: (
        h.replace(
            'data-metric="training"',
            'data-metric="training"></p><p data-metric="x" data-source="Whoop" data-as-of="d" data-q="x2" data-v="1">Whoop',
            1,
        ),
        t,
    ),
    "recs_over": lambda h, t: (h + '<p data-rec="a" data-status="NEW"></p>' * 3, t),
    "voice": lambda h, t: (h.replace("What changed.", "What changed, says " + PERSONA[0].upper() + ".", 1), t),
    "legacy_section": lambda h, t: (h + "<!-- S:training -->", t),
    "detail_link": lambda h, t: (h.replace("data-detail-link", "data-nolink"), t),
    "missed_wording": lambda h, t: (h.replace("What changed.", "Food was not logged.", 1), t),
    "categorical_with_unknowns": lambda h, t: (h.replace("What changed.", "Nothing needs your attention.", 1), t),
    "clearance": lambda h, t: (h.replace("What changed.", "You are cleared for hard training.", 1), t),
    "contradiction": lambda h, t: (
        h.replace('data-q="weight" data-v="291.4"', 'data-q="weight" data-v="290.0"').replace(
            "</td></tr></table></td>", '<p data-q="weight" data-v="291.4">291.4</p></td></tr></table></td>', 1
        ),
        t,
    ),
    "attribution": lambda h, t: (h.replace('data-source="Withings"', 'data-source=""'), t),
    "unchanged_repeat": lambda h, t: (h + '<p data-rec="r" data-rec-key="movement" data-status="REPEAT">walk</p>', t),
}


def test_every_hard_rule_is_proven_able_to_fail_by_a_mutation_of_a_clean_render():
    html, text = _render(_view())
    assert bb.check(html, text, persona_names=PERSONA, pending_inputs=("food",)) == []
    missed = []
    for code, mutate in MUTATIONS.items():
        h, t = mutate(html, text)
        got = {v.code for v in bb.check(h, t, persona_names=PERSONA, pending_inputs=("food",))}
        if code not in got:
            missed.append((code, sorted(got)))
    assert not missed, missed
    assert set(MUTATIONS) == set(bb.HARD), "every HARD rule carries a mutation proof"


# ══════════════════════════════════════════════════════════════════════════════
# §3 / §4 through the real handler (fakes only)
# ══════════════════════════════════════════════════════════════════════════════

import test_daily_brief_behavior as _dbb  # noqa: E402 — the handler harness (fakes only, no AWS)

brief, computed_row = _dbb.brief, _dbb.computed_row
frozen_clock, _every_day_is_a_narrative_day = _dbb.frozen_clock, _dbb._every_day_is_a_narrative_day
handler_env, ses, table = _dbb.handler_env, _dbb.ses, _dbb.table
SWITCH_KEY = (brief.USER_PREFIX + "brief_trial", "SWITCH#format")


def _seed(store):
    p = brief.USER_PREFIX
    y, t = _dbb.YESTERDAY, _dbb.TODAY
    for i, rec in enumerate((52, 61, 49, 57, 72, 55, 58)):
        day = (_dbb.datetime(2026, 7, 31) + _dbb.timedelta(days=i)).strftime("%Y-%m-%d")
        store[(p + "whoop", "DATE#" + day)] = {"pk": p + "whoop", "sk": "DATE#" + day, "date": day, "recovery_score": Decimal(str(rec))}
    store[(p + "whoop", "DATE#" + t)] = {"pk": p + "whoop", "sk": "DATE#" + t, "date": t, "recovery_score": Decimal("66")}
    store[(p + "withings", "DATE#" + y)] = {"pk": p + "withings", "sk": "DATE#" + y, "date": y, "weight_lbs": Decimal("316.6")}
    mf = "2026-08-04"
    store[(p + "macrofactor", "DATE#" + mf)] = {
        "pk": p + "macrofactor",
        "sk": "DATE#" + mf,
        "date": mf,
        "total_calories_kcal": Decimal("1880"),
        "ingested_at": "2026-08-05T16:00:00+00:00",
    }


def _run(env, switch=None, event=None, expect_raise=False):
    env["ses"].sent.clear()
    store = env["table"].store
    store.pop(SWITCH_KEY, None)
    if switch is not None:
        store[SWITCH_KEY] = {"pk": SWITCH_KEY[0], "sk": SWITCH_KEY[1], "value": switch}
    if expect_raise:
        with pytest.raises(bt.CompactBriefFallback):
            brief.lambda_handler({"force_send": True, **(event or {})}, None)
    else:
        brief.lambda_handler({"force_send": True, **(event or {})}, None)
    if not env["ses"].sent:
        return None
    return env["ses"].sent[-1]


def _sends(env):
    return [p for p in env["table"].puts if str(p.get("pk", "")).endswith("#brief_trial") and str(p.get("sk", "")).startswith("SEND#")]


@pytest.fixture
def env(handler_env):
    r = computed_row(acwr=Decimal("1.05"), acwr_zone="safe", acwr_alert=False)
    handler_env["table"].store[(r["pk"], r["sk"])] = r
    _seed(handler_env["table"].store)
    return handler_env


def test_off_and_hybrid_send_exactly_what_they_sent_before_and_compact_replaces_the_whole_email(env):
    baseline = _run(env)
    simple = baseline["Content"]["Simple"]
    assert set(simple["Body"]) == {"Html"} and "THE BRIEF" in simple["Body"]["Html"]["Data"]
    assert _run(env, "off") == baseline
    hybrid = _run(env, "hybrid")["Content"]["Simple"]
    assert set(hybrid["Body"]) == {"Html"} and "<!-- S:hybrid_brief -->" in hybrid["Body"]["Html"]["Data"]
    compact = _run(env, "compact")["Content"]["Simple"]
    html, text = compact["Body"]["Html"]["Data"], compact["Body"]["Text"]["Data"]
    assert "THE BRIEF" not in html and "S:hybrid_brief" not in html  # the legacy render is not appended
    assert 'data-lead="' in html and text.startswith("Morning Brief")
    assert compact["Subject"]["Data"].startswith("Morning Brief | ") and "Grade" not in compact["Subject"]["Data"]
    assert _run(env, "off") == baseline  # rollback: one switch value, no deploy
    again = _run(env, "hybrid")["Content"]["Simple"]  # its token and NEW/REPEAT labels move per send; its shape does not
    assert set(again["Body"]) == {"Html"} and again["Body"]["Html"]["Data"].endswith("THE BRIEF</body></html>")


@pytest.mark.parametrize("raw", [None, "", "on", "true", "compactt", "comp act", ["compact"], {"value": "compact"}, Decimal("1")])
def test_an_absent_or_malformed_switch_is_never_compact(raw):
    item = None if raw is None else {"value": raw}
    tbl = MagicMock()
    tbl.get_item.return_value = {"Item": item} if item else {}
    assert bt.read_switch(tbl, "USER#matthew#SOURCE#") == "off"
    tbl.get_item.side_effect = RuntimeError("AccessDenied")
    assert bt.read_switch(tbl, "USER#matthew#SOURCE#") == "off"


def test_an_absent_or_unreadable_switch_sends_mains_brief(env, monkeypatch):
    baseline = _run(env)
    real = env["table"].get_item

    def failing(Key=None, **kw):
        if (Key["pk"], Key["sk"]) == SWITCH_KEY:
            raise RuntimeError("ProvisionedThroughputExceeded")
        return real(Key=Key, **kw)

    monkeypatch.setattr(env["table"], "get_item", failing)
    assert _run(env, "compact") == baseline and _sends(env) == []


def test_the_compact_send_row_carries_the_attention_measures(env):
    _run(env, "compact")
    row = _sends(env)[-1]
    for k in ("words", "read_seconds_est", "n_metrics", "n_recs", "repeats_suppressed", "quiet_day", "n_critical_alerts", "fallback"):
        assert k in row, k
    assert row["variant"] == "compact" and row["fallback"] is False and row["budget_violations"] == []
    assert row["lead_kind"] == "unknown" and row["food_pending"] is True  # the seeded export predates the data day
    assert row["format_version"] == bc.FORMAT_VERSION and "rec_pilot_state" not in row  # #6158 pilot stays dark


def test_a_render_failure_sends_the_short_notice_never_the_legacy_report(env, monkeypatch):
    def boom(*a, **k):
        raise KeyError("render")

    monkeypatch.setattr(bc, "render_html", boom)
    sent = _run(env, "compact", expect_raise=True)
    simple = sent["Content"]["Simple"]
    html = simple["Body"]["Html"]["Data"]
    assert simple["Subject"]["Data"].endswith("| Not prepared today")
    assert bc.FALLBACK_LEAD in html and "THE BRIEF" not in html and 'data-metric="' not in html
    assert bb.words(simple["Body"]["Text"]["Data"]) < 80
    row = _sends(env)[-1]
    assert row["fallback"] is True and row["fallback_reason"] == "render:KeyError"
    # the send is still recorded as a send (DIL-025's replay guard refuses the Lambda retry the raise causes)
    assert any(str(p.get("pk", "")).endswith("#email_log#daily_brief") for p in env["table"].puts)


def test_the_lambda_retry_after_a_fallback_raise_sends_no_second_email(env, monkeypatch):
    monkeypatch.setattr(bc, "render_html", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    _run(env, "compact", expect_raise=True)
    env["ses"].sent.clear()
    brief.lambda_handler({}, None)  # the async retry carries the original event (no force_send)
    assert env["ses"].sent == []


def test_a_long_second_recommendation_is_dropped_to_fit_never_the_whole_brief(env, monkeypatch):
    from ai import budget_guard

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    long_one = "💧 " + " ".join(["Keep a water bottle at your desk and refill it at every meeting break this afternoon."] * 9)
    for name in ("call_board_of_directors", "call_journal_coach"):
        monkeypatch.setattr(brief.ai_calls, name, MagicMock(return_value="note"))
    monkeypatch.setattr(brief.ai_calls, "call_training_nutrition_coach", MagicMock(return_value={"training": "t", "nutrition": "n"}))
    guidance = ["🚶 A 30-minute walk after lunch is the simplest move today.", long_one]
    monkeypatch.setattr(brief.ai_calls, "call_tldr_and_guidance", MagicMock(return_value={"tldr": "A day.", "guidance": guidance}))
    sent = _run(env, "compact")["Content"]["Simple"]
    row = _sends(env)[-1]
    assert row["fallback"] is False and row["dropped_for_length"] == 1 and row["n_recs"] == 1
    assert "30-minute walk" in sent["Body"]["Html"]["Data"] and "water bottle" not in sent["Body"]["Html"]["Data"]


def test_a_hard_budget_violation_is_a_failure_notice_too(env, monkeypatch):
    monkeypatch.setattr(bc, "WORD_CEILING", 20)
    sent = _run(env, "compact", expect_raise=True)
    assert bc.FALLBACK_LEAD in sent["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert _sends(env)[-1]["fallback_reason"].startswith("budget:") and "words_over" in _sends(env)[-1]["fallback_reason"]


def test_the_failure_notice_keeps_the_verified_alerts_and_a_dry_run_does_not_raise(env, monkeypatch):
    p = brief.USER_PREFIX
    env["table"].store[(p + "anomalies", "DATE#" + _dbb.YESTERDAY)] = {
        "pk": p + "anomalies",
        "sk": "DATE#" + _dbb.YESTERDAY,
        "severity": "high",
        "anomalous_metrics": [
            {"source": "whoop", "field": "hrv", "label": "HRV"},
            {"source": "whoop", "field": "resting_heart_rate", "label": "Resting heart rate"},
            {"source": "withings", "field": "weight_lbs", "label": "Weight"},
        ],
    }
    monkeypatch.setattr(bc, "render_html", lambda *a, **k: (_ for _ in ()).throw(ValueError("x")))
    sent = _run(env, "compact", expect_raise=True)
    html = sent["Content"]["Simple"]["Body"]["Html"]["Data"]
    assert 'data-alert="anomaly"' in html and "HRV" in html
    assert _run(env, "compact", event={"dry_run": True}) is None  # a dry run sends nothing and raises nothing


def test_compact_leaves_the_coach_pipeline_and_its_model_call_count_unchanged(env, monkeypatch):
    from ai import budget_guard

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    m = brief
    counts = {}
    for name in (
        "call_sleep_coach_v2",
        "call_nutrition_coach_v2",
        "call_mind_coach_v2",
        "call_physical_coach_v2",
        "call_glucose_coach_v2",
        "call_labs_coach_v2",
        "call_explorer_coach_v2",
        "call_board_of_directors",
        "call_journal_coach",
    ):
        monkeypatch.setattr(m.ai_calls, name, MagicMock(return_value="A short synthetic note."))
    monkeypatch.setattr(m.ai_calls, "call_training_nutrition_coach", MagicMock(return_value={"training": "t", "nutrition": "n"}))
    monkeypatch.setattr(m.ai_calls, "call_tldr_and_guidance", MagicMock(return_value={"tldr": "A steady day.", "guidance": GUIDANCE[:2]}))
    monkeypatch.setattr(m.ai_calls, "daily_brief_shared_system", MagicMock(return_value="system"))

    def total():
        return sum(getattr(m.ai_calls, n).call_count for n in dir(m.ai_calls) if isinstance(getattr(m.ai_calls, n), MagicMock))

    _run(env, "off")
    counts["off"] = total()
    _run(env, "compact")
    counts["compact"] = total() - counts["off"]
    assert counts["off"] > 0 and counts["compact"] == counts["off"], counts


def test_the_recommendation_record_pilot_stays_dark():
    assert rr.CANONICAL_INTAKE_LIVE is False


# ══════════════════════════════════════════════════════════════════════════════
# the real layout: a headless browser at 390 px and 1280 px
# ══════════════════════════════════════════════════════════════════════════════


def test_the_compact_email_fits_a_phone_and_a_desktop_without_horizontal_scroll():
    pytest.importorskip("playwright")
    from playwright.sync_api import Error as PwError, sync_playwright

    busy, _ = _render(_view())
    quiet, _ = _render(_view(data=_quiet_data(), guidance=[]))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                out = {}
                for name, html in (("busy", busy), ("quiet", quiet)):
                    for width in (390, 1280):
                        page = browser.new_page(viewport={"width": width, "height": 120}, device_scale_factor=1)  # height = content
                        page.route("**/*", lambda r: r.abort())  # offline: the email loads nothing
                        page.set_content(html, wait_until="domcontentloaded")
                        out[(name, width)] = page.evaluate(
                            "({h: document.documentElement.scrollHeight, sw: document.documentElement.scrollWidth, w: window.innerWidth})"
                        )
                        page.close()
            finally:
                browser.close()
    except PwError as e:  # pragma: no cover — no Chromium on this runner
        pytest.skip(f"chromium unavailable: {e}")
    for (name, width), m in out.items():
        assert m["sw"] <= m["w"], f"{name} at {width}px scrolls sideways: {m}"
    assert out[("busy", 390)]["h"] <= bb.HEIGHT_BUDGET_PX, out[("busy", 390)]
    assert out[("quiet", 390)]["h"] <= bb.PHONE_SCREEN_PX, out[("quiet", 390)]
    assert out[("busy", 1280)]["h"] <= out[("busy", 390)]["h"]
