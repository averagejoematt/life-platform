"""tests/test_brief_editorial_6163.py — #6163: what the Morning Brief may claim about a day it has not fully seen.

Four behaviours, each pinned with invented fixture data (no stored brief text):

  1. a day with no food row says "export not arrived" (with the last export's date) unless an
     export has landed since the day ended — only then "not logged";
  2. a grade computed without the day's food log is labelled PROVISIONAL, naming what is missing,
     and the grade itself is unchanged;
  3. the READINESS SIGNAL's figures name the morning they describe, labelled as an earlier morning;
  4. a guidance item / protocol bullet identical to the previous brief's folds into one
     "unchanged since <date>" line.

Plus the read side (`emails.brief_editorial_inputs`): read-only, fail-soft.
"""

import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from content import (  # noqa: E402
    brief_editorial as be,  # noqa: E402
    brief_hr_regime,
    html_builder,
)
from emails import brief_editorial_inputs as bei  # noqa: E402

DAY = "2031-03-11"  # an invented data day (a Tuesday); the brief is read Wednesday 2031-03-12
_LOG = logging.getLogger("test-6163")


def _data(**over):
    d = {"date": DAY, "macrofactor": None, "whoop": {"recovery_score": 61, "strain": 9.4, "resting_heart_rate": 55}}
    d.update(over)
    return d


def _ed(data, **editorial):
    return {**data, "brief_editorial": editorial}


# ── 1. not arrived vs not logged ──────────────────────────────────────────────


def test_no_food_row_before_any_later_export_says_not_arrived_and_asks_nothing():
    d = _ed(_data(), nutrition={"last_arrival_day": "2031-03-09", "last_intake_day": "2031-03-08"})
    html = be.nutrition_absent_html(d)
    assert "MacroFactor export not arrived for Tuesday, March 11" in html
    assert "the last export arrived Sunday, March 9 and runs through Saturday, March 8" in html
    assert "not a missed log" in html
    assert "logged yesterday" not in html and "log a meal" not in html.lower()


def test_an_export_that_arrived_on_the_day_itself_has_not_spoken_for_the_whole_day():
    d = _ed(_data(), nutrition={"last_arrival_day": DAY, "last_intake_day": "2031-03-10"})
    assert be.nutrition_arrival(d) == "not_arrived"
    same = _ed(_data(), nutrition={"last_arrival_day": "2031-03-10", "last_intake_day": "2031-03-10"})
    assert "the last export arrived Monday, March 10 and runs through that day." in be.nutrition_absent_html(same)


def test_an_export_landed_after_the_day_without_it_is_the_only_not_logged_case():
    d = _ed(_data(), nutrition={"last_arrival_day": "2031-03-12", "last_intake_day": "2031-03-10"})
    assert be.nutrition_arrival(d) == "arrived"
    assert be.nutrition_absent_html(d) == be.NOT_LOGGED_HTML


def test_unknown_freshness_keeps_the_pre_6163_line_byte_for_byte():
    assert be.nutrition_absent_html(_data()) == be.NOT_LOGGED_HTML
    assert be.NOT_LOGGED_HTML == '<p style="color:#64748b;font-size:12px;margin:0;">No nutrition data logged yesterday.</p>'


def test_nutrition_freshness_reads_the_newest_rows_arrival_and_intake():
    rows = [
        {"sk": "DATE#2031-03-12", "summary_projected_ingested_at": "2031-03-10T06:00:00Z"},  # projection, no intake
        {"sk": "DATE#2031-03-10", "total_calories_kcal": 1500, "ingested_at": "2031-03-10T06:00:00Z"},
        {"sk": "DATE#2031-03-09", "total_calories_kcal": 1400, "ingested_at": "2031-03-08T05:00:00Z"},
    ]

    class _T:
        def query(self, **kw):
            assert kw["ScanIndexForward"] is False and kw["Limit"] == bei._NEWEST_ROWS
            return {"Items": rows}

    # 06:00Z on 03-10 is 22:00/23:00 PT on 03-09: the arrival day is the PACIFIC day
    assert bei.nutrition_freshness(_T(), "USER#x#SOURCE#") == {"last_arrival_day": "2031-03-09", "last_intake_day": "2031-03-10"}


# ── 2. provisional grade ──────────────────────────────────────────────────────


def _header(data, score=57):
    return html_builder._brief_header("standard", data, score, "C", None, None, "#1a1a2e", "Wednesday, March 12")


def test_a_grade_without_the_days_food_log_is_provisional_and_names_what_is_missing():
    d = _ed(_data(), nutrition={"last_arrival_day": "2031-03-09"})
    html = _header(d)
    assert "57/100" in html and ">C</p>" in html  # the grade itself is untouched
    assert "PROVISIONAL" in html and "food log not arrived for March 11" in html


def test_a_genuinely_unlogged_day_is_still_provisional_but_says_no_food_log():
    html = _header(_ed(_data(), nutrition={"last_arrival_day": "2031-03-12"}))
    assert "PROVISIONAL" in html and "no food log for March 11" in html


def test_a_grade_with_the_food_log_is_not_provisional():
    assert "PROVISIONAL" not in _header(_data(macrofactor={"total_calories_kcal": 1650}))


def test_no_grade_means_no_provisional_label():
    assert "PROVISIONAL" not in _header(_data(), score=None)


# ── 3. the morning of each readiness figure ───────────────────────────────────


def test_readiness_figures_name_their_morning_and_say_todays_was_not_scored():
    html = brief_hr_regime.readiness_signal_html(_data(), "yellow")
    assert "61%" in html
    assert "From the morning of Tuesday, March 11 — an earlier morning" in html
    assert "this morning's recovery (Wednesday, March 12) was not scored when this brief was built." in html


def test_when_this_mornings_recovery_is_scored_the_label_gives_it():
    html = brief_hr_regime.readiness_signal_html(_data(whoop_today={"recovery_score": 74}), "yellow")
    assert "this morning's recovery (Wednesday, March 12) is 74%." in html


def test_no_figures_means_no_morning_label():
    assert "From the morning" not in brief_hr_regime.readiness_signal_html(_data(whoop={}), "gray")


# ── 4. unchanged since the previous brief ─────────────────────────────────────

_RECS = [
    {"pillar": "sleep", "dropped": False, "protocols": ["Dim lights at 20:00", {"name": "Cool room"}]},
    {"pillar": "mind", "dropped": True, "protocols": ["Ten quiet minutes"]},
]


def test_identical_protocol_bullets_fold_into_one_unchanged_line():
    html = be.protocols_html(_RECS, _ed(_data(), previous_protocol_recs=_RECS))
    assert "PROTOCOLS TO TRY" in html
    assert "Dim lights" not in html and "Cool room" not in html and "Ten quiet minutes" not in html
    assert "3 protocols unchanged since the Tuesday, March 11 brief." in html


def test_a_changed_bullet_still_renders_beside_the_folded_ones():
    prev = [{"pillar": "sleep", "protocols": ["Dim lights at 20:00", "Cool room"]}]
    html = be.protocols_html(_RECS, _ed(_data(), previous_protocol_recs=prev))
    assert "Cool room" not in html and "Dim lights" not in html
    assert "↓ Mind:" in html and "Ten quiet minutes" in html
    assert "2 protocols unchanged since" in html


def test_without_a_previous_brief_the_protocol_block_is_the_pre_6163_markup():
    html = be.protocols_html(_RECS, _data())
    assert "unchanged" not in html
    assert "⚠ Sleep:" in html and "• Dim lights at 20:00" in html and "• Cool room" in html and "↓ Mind:" in html


def test_identical_guidance_folds_and_the_callers_dict_is_untouched():
    tg = {"tldr": "t", "guidance": ["Walk twenty minutes after lunch.", "A new item today."]}
    d = _ed(_data(), previous_guidance=["yesterday's tl;dr", "Walk  twenty minutes after lunch."])
    out = be.collapse_guidance(tg, d)
    assert out["guidance"] == ["A new item today.", "1 guidance item unchanged since the Tuesday, March 11 brief."]
    assert out["tldr"] == "t"
    assert tg["guidance"] == ["Walk twenty minutes after lunch.", "A new item today."]


def test_guidance_without_a_previous_brief_is_returned_as_is():
    tg = {"guidance": ["x"]}
    assert be.collapse_guidance(tg, _data()) is tg


# ── wiring: build_html carries the inputs on a render-local copy ──────────────


def test_build_html_renders_the_editorial_and_never_writes_into_the_callers_data():
    data = _data(macrofactor=None)
    html = html_builder.build_html(
        data=data,
        profile={},
        day_grade_score=57,
        grade="C",
        component_scores={},
        component_details={},
        readiness_score=58,
        readiness_colour="red",
        tldr_guidance={"tldr": "t", "guidance": ["Same as before."]},
        bod_insight=None,
        training_nutrition=None,
        journal_coach_text=None,
        mvp_streak=0,
        full_streak=0,
        editorial={"nutrition": {"last_arrival_day": "2031-03-09"}, "previous_guidance": ["Same as before."]},
    )
    assert "brief_editorial" not in data
    assert "MacroFactor export not arrived for Tuesday, March 11" in html
    assert "PROVISIONAL" in html and "From the morning of Tuesday, March 11" in html
    assert "1 guidance item unchanged since the Tuesday, March 11 brief." in html


# ── read side: fail-soft, read-only ───────────────────────────────────────────


def test_gather_reads_the_previous_days_stored_brief_and_drops_a_failed_read(monkeypatch):
    calls = []

    def fetch_date(source, day):
        calls.append((source, day))
        if source == "computed_insights":
            return {"guidance_given": json.dumps(["tldr", "item"])}
        raise RuntimeError("character sheet unreadable")

    class _T:
        def query(self, **kw):
            raise RuntimeError("throttled")

    out = bei.gather(_T(), fetch_date, "USER#x#SOURCE#", DAY, _LOG)
    assert out == {"previous_guidance": ["tldr", "item"]}
    assert ("computed_insights", "2031-03-10") in calls and ("character_sheet", "2031-03-10") in calls


def test_gather_has_no_write_path():
    src = (ROOT / "lambdas" / "emails" / "brief_editorial_inputs.py").read_text()
    for verb in ("put_item", "update_item", "delete_item", "batch_write", "put_object"):
        assert verb not in src
