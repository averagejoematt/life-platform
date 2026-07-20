"""
tests/test_ai_review_pack.py — the weekly AI review-pack email (#1442, QA D3).

Covers lambdas/emails/ai_review_pack_lambda.py:
  - the trailing-window date math
  - gather_week: archive grouping, newest-first ordering, fail-soft read errors
  - the HTML: per-surface sections, empty-state notes, screenshot links, header counts
  - graceful degradation on a totally-quiet week
  - lambda_handler wiring (SES + status-record), fully mocked (no AWS)

Run:  python3 -m pytest tests/test_ai_review_pack.py -v
"""

import os
import sys
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(REPO, "lambdas"))
sys.path.insert(0, os.path.join(REPO, "lambdas", "emails"))

import ai_review_pack_lambda as arp  # noqa: E402


def _entry(surface, text, archived_at, variant=None, meta=None):
    # gather_week always stamps _key onto each entry; mirror that so the pure
    # render helpers can be unit-tested in isolation.
    return {
        "schema": 1,
        "surface": surface,
        "variant": variant,
        "date": archived_at[:10],
        "archived_at": archived_at,
        "text": text,
        "meta": meta or {},
        "_key": f"generated/qa_archive/text/{archived_at[:10]}/{surface}--{archived_at[11:19]}.json",
    }


# ── date window ───────────────────────────────────────────────────────────────


def test_week_dates_is_seven_days_oldest_first_ending_today():
    end = date(2026, 7, 20)
    dates = arp.week_dates(end=end)
    assert len(dates) == 7
    assert dates[0] == "2026-07-14"
    assert dates[-1] == "2026-07-20"
    assert dates == sorted(dates)


def test_console_url_targets_the_archive_object():
    url = arp._console_url("generated/qa_archive/text/2026-07-20/chronicle--143005--abcd1234.json")
    assert url.startswith("https://us-west-2.console.aws.amazon.com/s3/object/")
    assert "matthew-life-platform" in url
    # the key rides the prefix param (slashes preserved — that is what the S3
    # console expects for a nested object prefix)
    assert "prefix=generated/qa_archive/text/2026-07-20" in url


# ── gather_week ───────────────────────────────────────────────────────────────


def test_gather_week_groups_by_surface_newest_first(monkeypatch):
    text_by_day = {
        "2026-07-19": ["k/chronicle-old", "k/board-1"],
        "2026-07-20": ["k/chronicle-new"],
    }
    bodies = {
        "k/chronicle-old": _entry("chronicle", "old", "2026-07-19T10:00:00+00:00"),
        "k/board-1": _entry("board_ask", "answer", "2026-07-19T11:00:00+00:00", variant="coach_a"),
        "k/chronicle-new": _entry("chronicle", "new", "2026-07-20T09:00:00+00:00"),
    }

    def fake_list_day(d, kind="text"):
        if kind == "text":
            return text_by_day.get(d, [])
        return ["s/shot-a", "s/shot-b"] if d == "2026-07-20" else []

    monkeypatch.setattr(arp.qa_archive, "list_day", fake_list_day)
    monkeypatch.setattr(arp.qa_archive, "read_entry", lambda k: bodies[k])

    by_surface, shots, errs = arp.gather_week(["2026-07-19", "2026-07-20"])
    assert errs == 0
    assert [e["text"] for e in by_surface["chronicle"]] == ["new", "old"]  # newest-first
    assert by_surface["board_ask"][0]["variant"] == "coach_a"
    assert shots["2026-07-20"] == ["s/shot-a", "s/shot-b"]


def test_gather_week_is_failsoft_on_a_corrupt_object(monkeypatch):
    monkeypatch.setattr(arp.qa_archive, "list_day", lambda d, kind="text": ["k/good", "k/bad"] if kind == "text" else [])

    def read(k):
        if k == "k/bad":
            raise ValueError("corrupt json")
        return _entry("chronicle", "fine", "2026-07-20T09:00:00+00:00")

    monkeypatch.setattr(arp.qa_archive, "read_entry", read)
    by_surface, _, errs = arp.gather_week(["2026-07-20"])
    assert errs == 1
    assert len(by_surface["chronicle"]) == 1


# ── meta line ─────────────────────────────────────────────────────────────────


def test_meta_line_renders_per_surface_context():
    board = _entry("board_ask", "a", "2026-07-20T09:00:00+00:00", variant="coach_a", meta={"question": "Why?", "grounded": True})
    assert "coach_a" in arp._meta_line(board)
    assert "Q: Why?" in arp._meta_line(board)
    assert "grounded" in arp._meta_line(board)

    som = _entry("state_of_matthew", "a", "2026-07-20T09:00:00+00:00", meta={"narrated": False})
    assert "fallback" in arp._meta_line(som)


# ── HTML ──────────────────────────────────────────────────────────────────────


def test_build_html_shows_sections_counts_and_screenshot_links():
    dates = arp.week_dates(end=date(2026, 7, 20))
    by_surface = {
        "chronicle": [_entry("chronicle", "The week in review", "2026-07-20T09:00:00+00:00", meta={"title": "W30", "week_number": 30})],
    }
    shots = {"2026-07-20": ["generated/qa_archive/screenshots/2026-07-20/coaching.png"]}
    html = arp.build_html(dates, by_surface, shots, read_errors=0)
    assert "Weekly AI Review Pack" in html
    assert "1</span> generation(s)" in html
    assert "The week in review" in html
    assert "Chronicle" in html
    # a surface that generated nothing shows an explicit note
    assert "Nothing generated this week." in html
    # screenshot leg links to the console object
    assert "coaching.png" in html
    assert "console.aws.amazon.com" in html


def test_build_html_quiet_week_still_renders():
    dates = arp.week_dates(end=date(2026, 7, 20))
    html = arp.build_html(dates, {}, {}, read_errors=0)
    assert "0</span> generation(s)" in html
    # every known surface is present with its empty note
    assert html.count("Nothing generated this week.") == len(arp.SURFACE_ORDER)


def test_build_html_surfaces_read_error_banner():
    dates = arp.week_dates(end=date(2026, 7, 20))
    html = arp.build_html(dates, {}, {}, read_errors=3)
    assert "3 archived object(s) could not be read" in html


def test_unknown_surface_still_renders(monkeypatch):
    # An archived surface not in SURFACE_ORDER must not be dropped (fail-open).
    dates = arp.week_dates(end=date(2026, 7, 20))
    by_surface = {"brand_new_surface": [_entry("brand_new_surface", "hi", "2026-07-20T09:00:00+00:00")]}
    html = arp.build_html(dates, by_surface, {}, read_errors=0)
    assert "Brand New Surface" in html


# ── handler wiring ────────────────────────────────────────────────────────────


def test_lambda_handler_sends_and_records(monkeypatch):
    monkeypatch.setattr(arp.qa_archive, "list_day", lambda d, kind="text": ["k/1"] if (kind == "text" and d == "2026-07-20") else [])
    monkeypatch.setattr(arp.qa_archive, "read_entry", lambda k: _entry("chronicle", "hi", "2026-07-20T09:00:00+00:00"))

    class _FixedDate(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 7, 20, 18, 0, 0, tzinfo=tz or timezone.utc)

    monkeypatch.setattr(arp, "datetime", _FixedDate)

    sent = {}
    ses = MagicMock()
    ses.send_email.side_effect = lambda **kw: sent.update(kw)
    table = MagicMock()
    fake_boto3 = MagicMock()
    fake_boto3.client.return_value = ses
    fake_boto3.resource.return_value.Table.return_value = table
    monkeypatch.setattr(arp, "boto3", fake_boto3)

    resp = arp.lambda_handler({}, None)
    assert resp["statusCode"] == 200
    assert ses.send_email.called
    assert "Weekly AI Review Pack" in sent["Content"]["Simple"]["Subject"]["Data"]
    assert table.put_item.called  # status record written
