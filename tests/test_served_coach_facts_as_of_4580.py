"""#4580 — a served coach line is judged as-of the day it was written, not against today's window.

The 2026-10-31 specimen: "30 logged days" written 10-30 against that day's 30-day window; on 10-31 the
served trend holds 29 rows (10-01 dropped off the front, 10-31 not exported yet), so a CORRECT line read
as a contradiction. Fixture shape is the wire: `/api/nutrition_overview.nutrition_trend[]` and
`/api/coaching-dashboard.moves.lines[]` (+ the undated `/api/coach/<id>.daily` twin).
"""

import importlib.util
import os
import sys
from datetime import date, timedelta

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "lambdas"))
_spec = importlib.util.spec_from_file_location("check_served_coach_facts", os.path.join(REPO, "scripts", "check_served_coach_facts.py"))
chk = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chk)

TODAY = "2026-10-31"
LINE = "On 30 logged days, Matthew's food log held while his journal did not, and the two gaps are separate habits."
JOURNEY = {"journey": {"current_weight_lbs": 250.0, "weekly_rate_lbs": -1.5}}


def _overview():
    d0 = date(2026, 10, 2)  # served window: 10-02 .. 10-30 = 29 rows (10-01 dropped, 10-31 not exported)
    trend = [
        {"date": (d0 + timedelta(days=i)).isoformat(), "calories": 2000, "protein_g": 150.0 + i, "carbs_g": 200.0, "fat_g": 60.0}
        for i in range(29)
    ]
    return {"nutrition_trend": trend}


def _payloads(line_date):
    return {
        "/api/coaching-dashboard": {"moves": {"date": line_date, "lines": [{"coach_id": "mind_coach", "text": LINE, "date": line_date}]}},
        "/api/coach/mind_coach": {"daily": LINE},
    }


def _run(line_date):
    payloads = _payloads(line_date)
    texts = chk.served_texts(payloads)
    facts = chk.facts_from_served(_overview(), JOURNEY, today=TODAY)
    return chk.findings(
        texts,
        facts,
        today=TODAY,
        dates=chk.line_dates(payloads),
        facts_for=lambda day: chk.facts_from_served(_overview(), JOURNEY, today=TODAY, as_of=day),
    )


def test_line_dates_join_the_undated_daily_twin():
    assert chk.line_dates(_payloads("2026-10-30")) == {LINE: "2026-10-30"}


def test_yesterdays_line_with_a_since_dropped_day_is_not_a_contradiction():
    assert _run("2026-10-30") == []


def test_todays_line_overclaiming_still_fires():
    hits = [f for _p, f in _run(TODAY) if f.get("metric") == "days_logged"]
    assert hits and {h.get("cited") for h in hits} == {30} and hits[0].get("canonical") == 29


def test_undated_text_keeps_todays_comparison():
    texts = [("/api/coach/x $.daily", LINE)]
    facts = chk.facts_from_served(_overview(), JOURNEY, today=TODAY)
    assert [f.get("metric") for _p, f in chk.findings(texts, facts, today=TODAY, dates={}, facts_for=None)] == ["days_logged"]


def test_as_of_is_not_a_blanket_tolerance():
    """Two days before: the window then started 10-01 too, so 31 days was never possible."""
    line = LINE.replace("30", "31")
    payloads = {"/api/coaching-dashboard": {"moves": {"lines": [{"text": line, "date": "2026-10-30"}]}}}
    facts = chk.facts_from_served(_overview(), JOURNEY, today=TODAY)
    hits = chk.findings(
        chk.served_texts({"/x": {"t": line}}),
        facts,
        today=TODAY,
        dates=chk.line_dates(payloads),
        facts_for=lambda day: chk.facts_from_served(_overview(), JOURNEY, today=TODAY, as_of=day),
    )
    assert [f.get("metric") for _p, f in hits] == ["days_logged"]
