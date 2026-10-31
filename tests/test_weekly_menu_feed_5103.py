"""#5103 box 4 — the two food emails consume the code-built menu: `health.weekly_menu_feed` reads it for every planned
day after today, prints it by code above the model's column, and feeds it to the prompt with the rule that the
numbers are final. The emails ship with or without a menu; an unbuildable or unreadable menu is named, never a raise.
"""

from __future__ import annotations

import copy
import json
import os
import pathlib
import sys

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO))
sys.path.insert(0, str(_REPO / "tests"))

from health import (
    weekly_menu as wm,  # noqa: E402
    weekly_menu_feed as feed,  # noqa: E402
)
from test_weekly_menu_5103 import ANCHORS, WEEK, _plan  # noqa: E402  — the fixture menu the fitter's own tests build

FRIDAY = wm.shift_day_key(WEEK, 4) if hasattr(wm, "shift_day_key") else None


def _friday():
    from common.pacific_time import shift_day_key

    return shift_day_key(WEEK, 4)


def _next_week():
    from common.pacific_time import shift_day_key

    return shift_day_key(WEEK, 7)


@pytest.fixture(scope="module")
def built_menu():
    menu = wm.build(_plan(), anchors_raw=copy.deepcopy(ANCHORS))
    assert menu["built"], menu
    return menu


# ── 1. which weeks, which days ───────────────────────────────────────────────────────────────────────────────────
def test_the_weeks_ahead_are_this_week_while_a_day_remains_and_the_coming_week():
    assert feed.weeks_ahead("2026-10-30") == ["2026-10-26", "2026-11-02"]  # a Friday: the weekend + next week
    assert feed.weeks_ahead("2026-11-01") == ["2026-11-02"]  # a Sunday: nothing of this week is ahead
    assert feed.weeks_ahead("2026-11-02") == ["2026-11-02", "2026-11-09"]  # a Monday: Tue–Sun + next week


def test_menus_ahead_cuts_each_week_to_the_days_after_today_and_shops_only_the_coming_week(built_menu):
    friday = _friday()
    seen = []

    def read(week):
        seen.append(week)
        return built_menu if week == WEEK else {"built": False, "reason_code": wm.NO_ANCHOR_TABLE, "reason": "no table"}

    ahead = feed.menus_ahead(table=None, today=friday, read=read)
    assert seen == [WEEK, _next_week()]
    this, nxt = ahead["weeks"]
    assert [d["date"] for d in this["days"]] == [d["date"] for d in built_menu["days"] if d["date"] > friday]
    assert len(this["days"]) == 2 and this["shop"] is False  # Saturday and Sunday, shopped for last Saturday
    assert nxt["days"] == [] and nxt["shop"] is True
    assert ahead["tier"] == "owner_only" and ahead["calendar_basis"] == feed.CALENDAR_BASIS


# ── 2. the feed: templates over the code's numbers ───────────────────────────────────────────────────────────────
def test_the_feed_carries_one_line_per_day_ahead_the_coming_weeks_grocery_and_each_unbuilt_weeks_reason(built_menu):
    friday = _friday()
    from common.pacific_time import shift_day_key

    # the coming week's menu: the same fit, seven days on (the fixture plan is one week; the fitter is deterministic)
    nxt = copy.deepcopy(built_menu)
    nxt["week_start"] = _next_week()
    for d in nxt["days"]:
        d["date"] = shift_day_key(d["date"], 7)
    ahead = feed.menus_ahead(table=None, today=friday, read=lambda week: built_menu if week == WEEK else nxt)
    fd = feed.feed(ahead)
    assert fd["built"] is True and fd["reason"] is None
    weekend = [d for d in built_menu["days"] if d["date"] > friday]
    assert len(fd["days"]) == 2 + 7
    assert fd["days"][0].startswith(f"{weekend[0]['weekday']} {weekend[0]['date']}")  # the day line verbatim from `lines`
    assert fd["days"][0] in built_menu["lines"]
    assert fd["grocery"] == wm.grocery_lines(nxt) and fd["grocery"]  # the coming week's shop only, once
    assert all(q.startswith("week of ") and "Food quality:" in q for q in fd["quality"]) and len(fd["quality"]) == 2

    half = feed.feed(
        feed.menus_ahead(
            table=None, today=friday, read=lambda week: built_menu if week == WEEK else {"built": False, "reason_code": "x", "reason": "y"}
        )
    )
    assert half["built"] is True and half["grocery"] == [] and half["reason"] == f"week of {_next_week()}: x — y"

    none = feed.feed(feed.menus_ahead(table=None, today=friday, read=lambda week: {"built": False, "reason_code": "x", "reason": "y"}))
    assert none["built"] is False and none["days"] == [] and "x — y" in none["reason"]


def test_the_html_block_prints_the_feeds_lines_escaped_and_names_a_missing_menu():
    fd = {
        "version": "v",
        "built": True,
        "days": ["Sat 2026-10-31 (<rest>): fits"],
        "grocery": ["Grocery list, protein: a & b"],
        "quality": ["week of x — Food quality: every target met"],
        "reason": None,
    }
    out = feed.html_block(fd)
    assert "Sat 2026-10-31 (&lt;rest&gt;): fits" in out and "a &amp; b" in out and "The shop (coming week)" in out
    assert "every target met" in out and feed.CALENDAR_BASIS in out and "<script" not in out
    missing = feed.html_block({"built": False, "reason": "week of w: no_anchor_table — no table"})
    assert "No code-built menu this week: week of w: no_anchor_table — no table." in missing and "The shop" not in missing


# ── 3. never raises ──────────────────────────────────────────────────────────────────────────────────────────────
def test_a_failed_plan_read_or_build_is_a_named_unreadable_menu_never_a_raise():
    boom = feed.read_menu("2026-11-02", table=None, today="2026-10-30", plan_reader=lambda *a, **k: 1 / 0)
    assert boom["built"] is False and boom["reason_code"] == feed.MENU_UNREADABLE and "ZeroDivisionError" in boom["reason"]
    none = feed.read_menu("2026-11-02", table=None, today="2026-10-30", plan_reader=lambda *a, **k: None)
    assert none["built"] is False and none["reason_code"] == wm.NO_PLAN


def test_the_prompt_note_has_no_braces_so_a_formatted_prompt_survives_it():
    assert "{" not in feed.PROMPT_NOTE and "}" not in feed.PROMPT_NOTE
    assert "menu_ahead" in feed.PROMPT_NOTE and "built" in feed.PROMPT_NOTE


# ── 4. the two emails are wired: prompt, payload, page ───────────────────────────────────────────────────────────
def _env():
    for k, v in {
        "TABLE_NAME": "life-platform",
        "AWS_DEFAULT_REGION": "us-west-2",
        "AWS_REGION": "us-west-2",
        "EMAIL_RECIPIENT": "reader@example.invalid",
        "EMAIL_SENDER": "plate@example.invalid",
        "S3_BUCKET": "test-bucket",
        "AI_VALIDATOR_AUTOLOAD": "off",
    }.items():
        os.environ.setdefault(k, v)


def test_the_weekly_plate_prints_the_block_above_the_column_and_feeds_the_prompt():
    _env()
    sys.path.insert(0, str(_REPO / "lambdas" / "emails"))
    import weekly_plate_lambda as wp

    assert "{menu_note}" in wp.SYSTEM_PROMPT
    rendered = wp.SYSTEM_PROMPT.format(
        weight_context="w", calorie_target=1, protein_target_g=2, eating_window="e", menu_note=feed.PROMPT_NOTE
    )
    assert "THE MENU AHEAD" in rendered
    page = wp.build_email_html("<p id=ai>AI</p>", {"end": "2026-10-30"}, None, "<div id=menu>M</div>")
    assert page.index("<div id=menu>") < page.index("<p id=ai>")
    assert wp.build_email_html("<p id=ai>AI</p>", {"end": "2026-10-30"}, None).count("id=menu") == 0  # the default page is unchanged
    payload = json.loads(
        wp.build_user_message(
            {"macrofactor": {}, "withings": {}, "profile": {}, "menu_feed": {"built": True, "days": ["d"], "grocery": []}}
        )
    )
    assert payload["menu_ahead"] == {"built": True, "days": ["d"], "grocery": []}
    assert json.loads(wp.build_user_message({"macrofactor": {}, "withings": {}, "profile": {}}))["menu_ahead"]["built"] is False


def test_the_nutrition_review_renders_the_note_into_both_prompt_paths_and_prints_the_block():
    _env()
    sys.path.insert(0, str(_REPO / "lambdas" / "emails"))
    import nutrition_review_lambda as nr

    assert feed.PROMPT_NOTE in nr._FALLBACK_SYSTEM_PROMPT
    rendered = nr._FALLBACK_SYSTEM_PROMPT.format(calorie_target=1, protein_target_g=2, feeding_threshold_g="30 g", eating_window="e")
    assert "THE MENU AHEAD" in rendered and nr.MICRONUTRIENT_SCOPE_NOTE in rendered
    src = pathlib.Path(nr.__file__).read_text()
    assert "{weekly_menu_feed.PROMPT_NOTE}" in src  # the S3 board-config path, the SERVED prompt
    page = nr.build_email_html(
        "<table id=s></table>",
        "<p id=ai>AI</p>",
        {"this_start": "2026-10-24", "this_end": "2026-10-30"},
        None,
        "<div id=t>T</div>",
        "<div id=menu>M</div>",
    )
    assert page.index("<div id=t>") < page.index("<div id=menu>") < page.index("<p id=ai>")
