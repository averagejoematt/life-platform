"""tests/test_chronicle_weekday_grounding.py — #1220 deterministic weekday↔date guard.

The pending cycle-6 chronicle draft (DDB pk=USER#matthew#SOURCE#chronicle
sk=DATE#2026-07-14, status=draft) called 2026-07-13 a "Sunday" — it was a Monday
(stale cycle-5 genesis leak; cycle-5's 2026-07-12 genesis WAS a Sunday). The
ADR-104 number gate never looked at weekday↔date pairs, so it passed a
mechanically checkable falsehood.

These tests prove:
  * grounded_generation.weekday_date_findings FAILS on the exact draft text and
    PASSES on the corrected pairing (non-vacuous),
  * build_calendar_facts emits the correct day-of-week for the covered window +
    genesis (computed from datetime, never hardcoded),
  * installment_grounding_findings (the LIVE chronicle gate) now surfaces the
    mismatch when the data packet's week-ending date pins the year.

All offline — no AWS, no AI.

Run with:   python3 -m pytest tests/test_chronicle_weekday_grounding.py -q
"""

import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "noreply@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import grounded_generation as gg  # noqa: E402
import wednesday_chronicle_lambda as chron  # noqa: E402

# The exact falsehood from the issue's evidence pointer (content_markdown of the
# status=draft record). 2026-07-13 was a MONDAY, 2026-07-14 a TUESDAY.
DRAFT_BAD = (
    "The experiment begins on a Sunday in July, another Sunday in a long series of "
    "Sundays. On the morning of July 13th, Matthew's recovery score reads 90 percent."
)


# ── the deterministic check (non-vacuous) ──


def test_guard_fails_on_the_issue_draft_text():
    """Proves the guard is NOT vacuous: it flags the shipped falsehood."""
    findings = gg.weekday_date_findings(DRAFT_BAD, year=2026)
    assert findings, "guard must flag the Sunday/July-13th falsehood"
    f = findings[0]
    assert f["type"] == "weekday_mismatch"
    assert f["stated_weekday"] == "Sunday"
    assert f["date"] == "2026-07-13"
    assert f["actual_weekday"] == "Monday"


def test_guard_passes_on_the_corrected_pairing():
    corrected = "On the morning of Monday, July 13th, Matthew's recovery score reads 90 percent."
    assert gg.weekday_date_findings(corrected, year=2026) == []


def test_guard_catches_the_nth_form_with_month_hint():
    """'on Monday the 14th' — the 14th of July 2026 was a Tuesday."""
    findings = gg.weekday_date_findings("The Monday walks happened on Monday the 14th.", year=2026, month_hint=7)
    assert any(f["date"] == "2026-07-14" and f["actual_weekday"] == "Tuesday" for f in findings)


def test_guard_clean_narrative_with_no_dates_is_silent():
    assert gg.weekday_date_findings("It was a hard Monday, and then a harder Friday.", year=2026) == []


def test_guard_no_false_positive_when_weekday_far_from_date():
    text = "Monday set the tone. " + ("Word " * 40) + "The report landed July 13th."
    assert gg.weekday_date_findings(text, year=2026) == []


def test_guard_ignores_impossible_date():
    # Feb 29 2026 is not a real date — resolve to None, never a bogus finding.
    assert gg.weekday_date_findings("A grim Sunday, February 29th.", year=2026) == []


# ── the calendar facts injected into the data packet ──


def test_build_calendar_facts_has_correct_weekdays_and_genesis():
    block = chron.build_calendar_facts("2026-07-08", "2026-07-14", genesis="2026-07-13")
    assert "2026-07-13 was a Monday (experiment genesis)" in block
    assert "2026-07-14 was a Tuesday" in block
    assert "2026-07-08 was a Wednesday" in block
    # The genesis (inside the window here) is tagged exactly once.
    assert block.count("(experiment genesis)") == 1


def test_build_calendar_facts_includes_genesis_outside_window():
    block = chron.build_calendar_facts("2026-07-15", "2026-07-21", genesis="2026-07-13")
    assert "2026-07-13 was a Monday (experiment genesis)" in block


def test_build_calendar_facts_empty_on_bad_dates():
    assert chron.build_calendar_facts(None, "2026-07-14") == ""


# ── the live gate wiring ──


def test_installment_gate_flags_weekday_mismatch_from_packet_year():
    """The live chronicle gate pins the year off 'Week ending:' and catches it."""
    user_message = "=== WEEKLY DATA PACKET ===\nWeek ending: 2026-07-14\n" + chron.build_calendar_facts(
        "2026-07-08", "2026-07-14", genesis="2026-07-13"
    )
    findings = chron.installment_grounding_findings("Elena system prompt", user_message, DRAFT_BAD)
    assert any(f["type"] == "weekday_mismatch" and f["date"] == "2026-07-13" for f in findings)


def test_installment_gate_passes_correct_weekday():
    user_message = "Week ending: 2026-07-14\n" + chron.build_calendar_facts("2026-07-08", "2026-07-14", genesis="2026-07-13")
    good = "On Monday, July 13th, the experiment began; the recovery score read 90 percent."
    assert [f for f in chron.installment_grounding_findings("sys", user_message, good) if f["type"] == "weekday_mismatch"] == []


# ── correction prompt renders the weekday fix ──


def test_correction_prompt_names_the_real_weekday():
    findings = gg.weekday_date_findings(DRAFT_BAD, year=2026)
    corr = gg.correction_prompt(findings)
    assert "Monday" in corr and "never guess a weekday" in corr
