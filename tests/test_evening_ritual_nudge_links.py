"""tests/test_evening_ritual_nudge_links.py — #769 (ADR-124): the evening-nudge
lambda's evening-ritual row (lambdas/emails/evening_nudge_lambda.py).

Covers:
  * _check_evening_ritual correctly detects fully-logged / partially-logged /
    not-logged-at-all for the day
  * #6243 (owner ruling 2026-11-23): the one-tap ritual section is GONE from the
    nudge (0 taps in 4 weeks). Pinned on the rendered email of the REAL handler,
    with the signing secret available — so the section's absence is the builder's,
    not a fail-soft skip — under the committed consolidation AND its rollback; the
    ritual row, the morning-note link and the 14-day stale rule are unchanged.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

# evening_nudge_lambda reads these at module-import time (os.environ[...], not .get).
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

from emails import evening_nudge_lambda as nudge  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

SECRET = "test-nudge-ritual-secret"


# Pinned dates, NOT pacific_today(): #1409 adds the weekly felt-probe metrics
# to the missing-set on Sundays (PT), so wall-clock dates made these tests red
# every Sunday (first fired genesis Sunday 2026-07-19, redding main CI). The
# weekday cases pin a Saturday; the probe case pins a Sunday explicitly.
SATURDAY = "2026-07-18"
SUNDAY = "2026-07-19"


def _set_ritual_record(monkeypatch, connection=None, mood_valence=None, intake_count=None, date=SATURDAY):
    rec = {}
    if connection is not None:
        rec["connection"] = connection
    if mood_valence is not None:
        rec["mood_valence"] = mood_valence
    store_items = [{"pk": nudge.USER_PREFIX + "evening_ritual", "sk": "DATE#" + date, **rec}] if rec else []
    if intake_count is not None:
        # #1405: the intake count lives in its own Matthew-private partition.
        store_items.append({"pk": nudge.USER_PREFIX + "private_intake", "sk": "DATE#" + date, "intake_count": intake_count})
    # query() always answers empty here — only get_item (keyed by pk/sk) is used.
    ft = FakeDdbTable(rows=[], store_items=store_items)
    monkeypatch.setattr(nudge, "table", ft)
    return date


# ── _check_evening_ritual ────────────────────────────────────────────────────


def test_not_logged_at_all(monkeypatch):
    today = _set_ritual_record(monkeypatch)
    missing, detail = nudge._check_evening_ritual(today)
    assert set(missing) == {"connection", "mood_valence", "intake_count"}
    assert "not logged" in detail.lower()


def test_partially_logged_only_flags_the_missing_metric(monkeypatch):
    today = _set_ritual_record(monkeypatch, connection=3, intake_count=0)
    missing, detail = nudge._check_evening_ritual(today)
    assert missing == ["mood_valence"]
    assert "1 left" in detail.lower() and "tap" not in detail.lower()


def test_fully_logged_reports_both_values(monkeypatch):
    today = _set_ritual_record(monkeypatch, connection=3, mood_valence=1, intake_count=2)
    missing, detail = nudge._check_evening_ritual(today)
    assert missing == []
    assert "3/4" in detail
    assert "1/4" in detail
    assert "Intake 2" in detail


def test_sunday_adds_the_felt_probe_metrics(monkeypatch):
    # #1409: on Sundays the three felt-reality probe taps join the ritual's
    # missing-set. #1408: the Time-Affluence probe (felt_time) rides the same
    # Sunday cadence from its own partition — so the Sunday set is now four taps.
    today = _set_ritual_record(monkeypatch, connection=3, mood_valence=1, intake_count=2, date=SUNDAY)
    missing, detail = nudge._check_evening_ritual(today)
    assert missing == sorted(["felt_vitality", "felt_rest", "felt_connection", "felt_time"])
    assert "4 left" in detail.lower() and "tap" not in detail.lower()


# ── #6243: the tap section is gone; the rest of the email is not ─────────────


def _render(monkeypatch, consolidated: bool):
    """Drive the REAL lambda_handler for a Saturday; return the one sent email's subject and HTML."""
    from common import outbound_trial

    for item in outbound_trial.ITEMS:  # conftest starts every item rolled back; set the state under test
        monkeypatch.setitem(outbound_trial.TRIAL, item, consolidated)
    sent = []
    monkeypatch.setattr(nudge, "pacific_today", lambda: SATURDAY)
    monkeypatch.setattr(nudge, "_run_named_human_contact_leg", lambda *a: None)
    monkeypatch.setattr(nudge.send_ledger, "should_skip_replay", lambda *a, **k: False)
    monkeypatch.setattr(nudge.send_ledger, "record_sent", lambda *a, **k: None)
    monkeypatch.setattr(nudge, "guarded_send_email", lambda ses, dry, **kw: sent.append(kw))
    monkeypatch.setattr(nudge, "manual_capture_sources", lambda: {})
    monkeypatch.setattr(nudge, "_get_ritual_secret", lambda: SECRET)  # available: an absent section is the builder's
    # Everything logged yesterday, nothing yet today: no item is stale, so the 14-day rule keeps all four rows.
    monkeypatch.setattr(nudge, "_check_supplements", lambda d: (d != SATURDAY, ""))
    monkeypatch.setattr(nudge, "_check_journal", lambda d: (d != SATURDAY, "No journal entries"))
    monkeypatch.setattr(nudge, "_check_how_we_feel", lambda d: (d != SATURDAY, ""))
    monkeypatch.setattr(
        nudge,
        "_check_evening_ritual",
        lambda d: (["connection", "mood_valence", "intake_count"], "Not logged yet") if d == SATURDAY else ([], "done"),
    )
    nudge.lambda_handler({}, None)
    assert len(sent) == 1, sent
    simple = sent[0]["Content"]["Simple"]
    return simple["Subject"]["Data"], simple["Body"]["Html"]["Data"]


def test_the_rendered_nudge_carries_no_ritual_tap_section(monkeypatch):
    for consolidated in (True, False):  # the committed state, and the evening_one_channel rollback
        subject, html = _render(monkeypatch, consolidated)
        assert "one tap each" not in html and "/api/ritual_log" not in html and "token=" not in html.split("#note=")[0]
        for title in ("Felt connected today?", "Mood today?", "Drinks this evening?"):
            assert title not in html, title
        # unchanged: the four rows, the subject count, the morning-note link
        assert subject == "Evening nudge · 4 thing(s) to log before bed", subject
        for row in ("Supplements", "Journal", "How We Feel", "Evening Ritual"):
            assert row in html, row
        assert "Open the morning note" in html


def test_the_ritual_section_builders_are_gone():
    for name in ("_build_ritual_section", "_ritual_metric_block", "_ritual_link", "RITUAL_LABELS", "RITUAL_METRIC_TITLES"):
        assert not hasattr(nudge, name), name
