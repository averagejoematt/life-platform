"""tests/test_som_checkin_frame_3914.py — #3914.

``evening_nudge_lambda.py:138`` reads ``apple_health[DATE#pacific_today()]`` for
``som_check_in_count`` at the 8 PM PT send. ``apple_health``'s ``DATE#`` key names
a **UTC** day (TD-19 Phase 2, #3677's KEEP-UTC ruling): every reading taken from
17:00 PT until Pacific midnight lands on the FOLLOWING Pacific day's key. A How We
Feel check-in logged 17:00-20:00 PT therefore sits on tomorrow's key while the
nudge queries today's, and reports "No How We Feel check-in today" hours after one
was actually recorded (audited read-only in
``docs/audits/TD-19_DATE_PARTITION_AUDIT.md`` Box B, "the sharpest one").

The fix is a frame-aware read (the ``reached_in_pacific`` shape from #3287): fold
the next UTC day's row into the same evening's count, without touching
apple_health's stored key frame (#3677's ruling stands — this is the reader, not a
re-key).

``_check_how_we_feel`` takes ``date_str`` directly rather than deriving "now"
internally, so the 17:00-20:00 PT window is pinned by SEEDING the fixture on the
next UTC day's key, not by freezing a clock — exactly the shape the acceptance
box asks for.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

from emails import evening_nudge_lambda as nudge  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

# Pacific "today" for the nudge send. The UTC-keyed row a 17:00-20:00 PT
# check-in actually lands on is the FOLLOWING calendar date (#3677's audit
# section names this exactly: "lands on the FOLLOWING Pacific day's key").
PACIFIC_TODAY = "2026-09-19"
NEXT_UTC_DAY = "2026-09-20"


def _seed(monkeypatch, today_item=None, next_day_item=None):
    store_items = []
    if today_item is not None:
        store_items.append({"pk": nudge.USER_PREFIX + "apple_health", "sk": f"DATE#{PACIFIC_TODAY}", **today_item})
    if next_day_item is not None:
        store_items.append({"pk": nudge.USER_PREFIX + "apple_health", "sk": f"DATE#{NEXT_UTC_DAY}", **next_day_item})
    ft = FakeDdbTable(rows=[], store_items=store_items)
    monkeypatch.setattr(nudge, "table", ft)
    return ft


# ── the defect: an evening check-in landed only on tomorrow's UTC-day key ──────


def test_evening_checkin_on_next_utc_day_counts_today(monkeypatch):
    """A 17:00-20:00 PT check-in — stored on the NEXT UTC day's row, nothing on
    today's — is counted complete on the SAME evening's nudge, not deferred."""
    _seed(monkeypatch, today_item=None, next_day_item={"som_check_in_count": 1})
    complete, detail = nudge._check_how_we_feel(PACIFIC_TODAY)
    assert complete is True
    assert "1 How We Feel check-in" in detail


def test_negative_control_todays_bare_key_is_empty(monkeypatch):
    """Same fixture: today's OWN key carries nothing — proves the fixture
    actually exercises the boundary (a pre-#3914 read of only ``DATE#today``
    would have found this empty and reported the check-in missing), rather
    than the fix passing by the fixture being trivially satisfiable."""
    _seed(monkeypatch, today_item=None, next_day_item={"som_check_in_count": 1})
    assert nudge._fetch_date("apple_health", PACIFIC_TODAY) is None


def test_both_rows_contribute_when_both_present(monkeypatch):
    """A morning check-in (today's key) and an evening one (next UTC day's key)
    both count — the fix folds the boundary row IN, it doesn't replace today's."""
    _seed(monkeypatch, today_item={"som_check_in_count": 2}, next_day_item={"som_check_in_count": 1})
    complete, detail = nudge._check_how_we_feel(PACIFIC_TODAY)
    assert complete is True
    assert "3 How We Feel check-in" in detail


def test_no_checkin_anywhere_reports_incomplete(monkeypatch):
    _seed(monkeypatch, today_item=None, next_day_item=None)
    complete, detail = nudge._check_how_we_feel(PACIFIC_TODAY)
    assert complete is False
    assert detail == "No How We Feel check-in today"


def test_zero_count_on_next_day_row_does_not_falsely_complete(monkeypatch):
    """A next-day apple_health row that exists (other HAE fields written) but
    carries a zero/absent som_check_in_count must not manufacture a check-in."""
    _seed(monkeypatch, today_item=None, next_day_item={"steps": 500})
    complete, detail = nudge._check_how_we_feel(PACIFIC_TODAY)
    assert complete is False
    assert detail == "No How We Feel check-in today"


# ── frame is registry-derived, not hardcoded to apple_health's current facet ───


def test_uses_the_registry_facet_not_a_hardcoded_frame(monkeypatch):
    """If apple_health's day_key_frame were ever flipped away from 'utc', the
    next-day fold-in must stop (it would double-count a Pacific-keyed source,
    since a Pacific key can never name a day Pacific hasn't reached — the same
    per-source guard #3287's own docstring calls out)."""
    monkeypatch.setattr(nudge, "day_key_frame_for", lambda source: "pacific")
    _seed(monkeypatch, today_item=None, next_day_item={"som_check_in_count": 1})
    complete, detail = nudge._check_how_we_feel(PACIFIC_TODAY)
    assert complete is False
    assert detail == "No How We Feel check-in today"


# ── no change to the stored key frame (#3677's ruling stands) ──────────────────


def test_apple_health_day_key_frame_still_utc():
    from ingestion.source_registry import day_key_frame_for

    assert day_key_frame_for("apple_health") == "utc"
