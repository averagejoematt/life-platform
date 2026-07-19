"""tests/test_evening_ritual_nudge_links.py — #769 (ADR-124): the evening-nudge
lambda's one-tap ritual links (lambdas/emails/evening_nudge_lambda.py).

Covers:
  * _check_evening_ritual correctly detects fully-logged / partially-logged /
    not-logged-at-all for the day
  * minted links verify against ritual_link.verify_ritual_token (mint/verify agree)
  * the tap-link section is fail-soft: an unavailable signing secret must not
    crash the whole nudge email, it just omits the section
  * the section is only built for the metrics still missing (partial-completion
    doesn't re-prompt an already-logged metric)
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

# evening_nudge_lambda reads these at module-import time (os.environ[...], not .get).
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

from emails import evening_nudge_lambda as nudge  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from ritual_link import verify_ritual_token  # noqa: E402

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
    assert "1 tap left" in detail.lower()


def test_fully_logged_reports_both_values(monkeypatch):
    today = _set_ritual_record(monkeypatch, connection=3, mood_valence=1, intake_count=2)
    missing, detail = nudge._check_evening_ritual(today)
    assert missing == []
    assert "3/4" in detail
    assert "1/4" in detail
    assert "Intake 2" in detail


def test_sunday_adds_the_felt_probe_metrics(monkeypatch):
    # #1409: on Sundays the three weekly probe taps join the ritual's missing-set
    # (and the fully-logged weekday shape above is only "full" on a weekday).
    today = _set_ritual_record(monkeypatch, connection=3, mood_valence=1, intake_count=2, date=SUNDAY)
    missing, detail = nudge._check_evening_ritual(today)
    assert missing == sorted(["felt_vitality", "felt_rest", "felt_connection"])
    assert "3 taps left" in detail.lower()


# ── link minting agrees with the site-api verifier ──────────────────────────


def test_minted_link_token_verifies(monkeypatch):
    monkeypatch.setattr(nudge, "_get_ritual_secret", lambda: SECRET)
    today = nudge.pacific_today()
    url = nudge._ritual_link(SECRET, today, "connection", 2)
    assert f"date={today}" in url
    assert "metric=connection" in url
    assert "value=2" in url
    token = url.split("token=")[1]
    assert verify_ritual_token(SECRET, today, "connection", 2, token)
    # a different value must NOT verify against this token
    assert not verify_ritual_token(SECRET, today, "connection", 3, token)


# ── fail-soft section building ───────────────────────────────────────────────


def test_section_empty_when_nothing_missing(monkeypatch):
    monkeypatch.setattr(nudge, "_get_ritual_secret", lambda: SECRET)
    assert nudge._build_ritual_section(nudge.pacific_today(), []) == ""


def test_section_omitted_when_secret_unavailable(monkeypatch):
    monkeypatch.setattr(nudge, "_get_ritual_secret", lambda: None)
    html = nudge._build_ritual_section(nudge.pacific_today(), ["connection", "mood_valence"])
    assert html == ""


def test_section_only_covers_missing_metrics(monkeypatch):
    monkeypatch.setattr(nudge, "_get_ritual_secret", lambda: SECRET)
    today = nudge.pacific_today()
    html = nudge._build_ritual_section(today, ["mood_valence"])
    assert "Mood today?" in html
    assert "Felt connected today?" not in html
    assert "metric=mood_valence" in html
