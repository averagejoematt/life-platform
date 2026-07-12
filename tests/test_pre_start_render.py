"""tests/test_pre_start_render.py — route-mocked render check for the pre-start
countdown state (#931).

Serves site/ locally (pr_render_gate's harness rules: catch-all route FIRST so
specific mocks win, service workers blocked so mocks aren't bypassed) and feeds
the pages the PRE-START payload contract — {pre_start, days_until_start,
start_date} with wiped/empty data everywhere else — then asserts what a reader
actually sees:

  * Home: the hero counts DOWN ("days until the experiment begins"), the family
    panel shows the awaiting-Day-1 state, no delta claim, no NaN/undefined leak.
  * Cockpit: the T−N banner ("The instruments are on"), no NaN/undefined leak.
  * Character sheet: the "record begins Day 1" pre-start banner, no dormant /
    atrophy / quiet-stretch framing.

Skips cleanly when Playwright (or its chromium) isn't installed — the backend
contract is pinned by tests/test_pre_start_countdown.py either way.
"""

import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)

pw = pytest.importorskip("playwright.sync_api", reason="playwright not installed — render check runs where it is")

from pr_render_gate import _serve, _wait_port  # noqa: E402

DAYS_UNTIL = 2
START_DATE = "2026-07-12"  # the staged genesis this state ships for
START_LABEL = "Sunday, July 12"

PRE_JOURNEY = {
    "journey": {
        "pre_start": True,
        "days_until_start": DAYS_UNTIL,
        "start_date": START_DATE,
        "day_n": 0,
        "week_n": 1,
        "start_weight_lbs": 315.0,
        "goal_weight_lbs": 185.0,
        "current_weight_lbs": 315,
        "lost_lbs": None,
        "remaining_lbs": None,
        "progress_pct": None,
        "weekly_rate_lbs": None,
        "rate_provisional": None,
        "weighin_span_days": None,
        "projected_goal_date": None,
        "projected_goal_date_earliest": None,
        "projected_goal_date_latest": None,
        "days_to_goal": None,
        "last_weighin_date": None,
        "started_date": START_DATE,
    }
}

PRE_PILLARS = [
    {"name": n, "raw_score": 0, "level": 1, "xp_delta": 0, "xp_debt": 0, "data_coverage": 0, "coverage_hold": True}
    for n in ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
]

PRE_CHARACTER = {
    "character": {"level": 1, "tier": "Foundation", "composite_score": 0, "xp_total": 0, "as_of_date": None, "character_mood": "steady"},
    "pillars": PRE_PILLARS,
}

PRE_SNAPSHOT = {
    "pre_start": True,
    "days_until_start": DAYS_UNTIL,
    "start_date": START_DATE,
    "vitals": None,
    "journey": PRE_JOURNEY,
    "character": PRE_CHARACTER,
    "readiness": None,
}

PRE_PULSE = {
    "pulse": {
        "pre_start": True,
        "days_until_start": DAYS_UNTIL,
        "start_date": START_DATE,
        "day_number": 0,
        "status": "quiet",
        "signals_reporting": 0,
        "signals_total": 8,
        "narrative": (
            f"T−{DAYS_UNTIL} days. The instruments are on; the experiment begins "
            f"{START_LABEL}. First baseline: that morning's weigh-in."
        ),
        "since_yesterday": [],
        "notable_signals": [],
        "glyphs": {},
    }
}

LEAK_TOKENS = ["NaN", "undefined", "[object Object]", "null lbs"]


def _routes(context):
    """Catch-all FIRST (reverse-match order), then the pre-start payloads."""

    def _json(payload):
        def _h(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

        return _h

    context.route("**/api/**", _json({}))
    context.route("**/api/journey", _json(PRE_JOURNEY))
    context.route("**/api/snapshot", _json(PRE_SNAPSHOT))
    context.route("**/api/pulse", _json(PRE_PULSE))
    context.route("**/api/character", _json(PRE_CHARACTER))
    context.route("**/public_stats.json", _json({"journey": {}, "vitals": {}}))
    context.route("**/journal/**", _json({}))


@pytest.fixture(scope="module")
def pre_start_pages():
    """One browser pass over the three pre-start surfaces; yields body texts + errors."""
    site_dir = os.path.join(REPO, "site")
    base_url, shutdown = _serve(site_dir)
    host, port = base_url.replace("http://", "").split(":")
    assert _wait_port(host, int(port)), "local static server never came up"

    out = {}
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(headless=True)
            except Exception as e:  # noqa: BLE001 — chromium not installed
                pytest.skip(f"playwright chromium unavailable: {e}")
            context = browser.new_context(viewport={"width": 1440, "height": 900}, service_workers="block")
            _routes(context)
            for path in ("/", "/cockpit/", "/data/character/"):
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda e, _errs=errors: _errs.append(str(e)))
                page.goto(base_url + path, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(1200)  # let the async renders settle
                out[path] = {"text": page.inner_text("body"), "errors": errors}
                page.close()
            browser.close()
    finally:
        shutdown()
    return out


def _assert_no_leaks(res, path):
    for tok in LEAK_TOKENS:
        assert tok not in res["text"], f"{path}: leaked '{tok}' into visitor-facing text"
    assert not res["errors"], f"{path}: page JS errors: {res['errors']}"


# NB: inner_text reflects CSS text-transform (the hero captions render UPPERCASE),
# so copy assertions compare lowercased text.


def test_home_counts_down(pre_start_pages):
    res = pre_start_pages["/"]
    text = res["text"].lower()
    assert "days until the experiment begins" in text
    assert START_LABEL.lower() in text
    assert "awaiting day 1" in text  # the family panel's neutral state
    assert "days into the experiment" not in text  # the running-state caption is gone
    assert "since june 14 2026" not in text  # the running-state genesis stamp is hidden
    _assert_no_leaks(res, "/")


def test_cockpit_pre_start_banner(pre_start_pages):
    res = pre_start_pages["/cockpit/"]
    text = res["text"].lower()
    assert "the instruments are on" in text
    assert f"t−{DAYS_UNTIL}" in text
    _assert_no_leaks(res, "/cockpit/")


def test_character_sheet_record_begins(pre_start_pages):
    res = pre_start_pages["/data/character/"]
    text = res["text"].lower()
    assert "until day 1" in text
    assert "the record begins day 1" in text
    # Anticipation, never neglect: no dormant/atrophy/quiet-stretch grammar pre-start.
    for tok in ("dormant", "atrophy", "days since a manual log"):
        assert tok not in text, f"/data/character/: pre-start must not read '{tok}'"
    _assert_no_leaks(res, "/data/character/")
