"""tests/test_milestone_digest_1623.py — private milestone digest (#1623).

Hermetic (FakeDdbTable + patched SES/secrets/breaker, no AWS). Pins the ACs:
  AC-recipients — list lives outside git; no secret => disarmed no-op.
  AC-source     — notes fire only from announced MILESTONE# ledger events;
                  first run BASELINES pre-existing history (no old news).
  AC-breaker    — spiral breaker gates the send, fail-closed, cursor untouched
                  (synthetic tripped-breaker fixture).
  AC-tone       — plain text, real Reply-To, no links/CTA/unsubscribe.
  AC-cooldown   — >=10-day gap between actual sends, on top of the ledger's
                  12-day announcement spacing.
"""

import os
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "sender@example.com")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import emails.milestone_digest_lambda as shell  # noqa: E402
from coach import spiral_breaker  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402

PK = "USER#matthew#SOURCE#milestones"
TODAY = "2026-08-20"

RECIPIENTS = {
    "reply_to": "matthew-real@example.com",
    "recipients": [
        {"name": "Sam", "email": "sam@example.com"},
        {"name": "Jo", "email": "jo@example.com"},
        {"name": "Ada", "email": "ada@example.com"},
        {"name": "Kit", "email": "kit@example.com"},
        {"name": "Max", "email": "max@example.com"},
    ],
}


class FakeSes:
    def __init__(self, fail_all=False):
        self.sends = []
        self.fail_all = fail_all

    def send_email(self, **kwargs):
        if self.fail_all:
            raise RuntimeError("SES down")
        self.sends.append(kwargs)
        return {"MessageId": f"m{len(self.sends)}"}


def _event(mid, event_date, label=None):
    return {
        "pk": PK,
        "sk": f"MILESTONE#{mid}",
        "milestone_id": mid,
        "label": label or f"Milestone {mid}",
        "category": "weight",
        "description": f"Description of {mid}",
        "event_date": event_date,
        "announce": True,
        "origin": "crossing",
    }


def _digest_sent(mid, sent_date):
    return {
        "pk": PK,
        "sk": f"DIGEST#sent#{mid}",
        "milestone_id": mid,
        "origin": "sent",
        "sent_date": sent_date,
        "recorded_at": sent_date,
    }


GENESIS_ROW = {"pk": PK, "sk": "DIGEST#genesis", "armed_date": "2026-08-01", "recorded_at": "2026-08-01"}


@pytest.fixture(autouse=True)
def _wire(monkeypatch):
    monkeypatch.setattr(shell, "pacific_today", lambda: TODAY)
    monkeypatch.setattr(shell, "experiment_stamp", lambda *a, **k: {"phase": "test", "cycle": 11})
    monkeypatch.setattr(shell, "get_secret_json", lambda *a, **k: dict(RECIPIENTS))
    monkeypatch.setattr(spiral_breaker, "check_celebration_allowed", lambda *a, **k: (True, {"suppressed": False}))
    ses = FakeSes()
    monkeypatch.setattr(shell, "ses", ses)
    yield ses


def _run(rows, monkeypatch=None):
    table = FakeDdbTable(rows=rows)
    monkeypatch.setattr(shell, "table", table)
    result = shell.lambda_handler({}, None)
    return result, table


def test_disarmed_without_recipients_secret(monkeypatch, _wire):
    monkeypatch.setattr(shell, "get_secret_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no secret")))
    result, table = _run([_event("w300", "2026-08-18")], monkeypatch=monkeypatch)
    assert result["status"] == "disarmed"
    assert _wire.sends == []
    assert table.puts == []


def test_first_run_baselines_history_and_never_mails(monkeypatch, _wire):
    rows = [_event("w310", "2026-07-30"), _event("w300", "2026-08-14")]
    result, table = _run(rows, monkeypatch=monkeypatch)
    assert result == {"status": "baselined", "baselined": 2}
    assert _wire.sends == []
    sks = {p["sk"] for p in table.puts}
    assert sks == {"DIGEST#sent#w310", "DIGEST#sent#w300", "DIGEST#genesis"}
    for p in table.puts:
        if p["sk"].startswith("DIGEST#sent#"):
            assert p["origin"] == "baseline" and p["sent_date"] is None
        assert p["cycle"] == 11  # experiment_stamp on every cursor write


def test_new_crossing_sends_to_all_and_marks_cursor(monkeypatch, _wire):
    rows = [GENESIS_ROW, _event("w300", "2026-08-18", label="Weekly average under 300")]
    result, table = _run(rows, monkeypatch=monkeypatch)
    assert result["status"] == "sent" and result["delivered"] == 5
    assert len(_wire.sends) == 5
    first = _wire.sends[0]
    body = first["Content"]["Simple"]["Body"]["Text"]["Data"]
    assert first["ReplyToAddresses"] == ["matthew-real@example.com"]
    assert "Weekly average under 300" in body
    assert "Hi Sam," in body
    # AC-tone: no links, no tracking, no unsubscribe funnel, no website CTA.
    assert "http" not in body.lower()
    assert "unsubscribe" not in body.lower()
    assert "Html" not in first["Content"]["Simple"]["Body"]
    marks = [p for p in table.puts if p["sk"] == "DIGEST#sent#w300"]
    assert len(marks) == 1 and marks[0]["origin"] == "sent" and marks[0]["delivered"] == 5


def test_breaker_tripped_suppresses_and_leaves_cursor(monkeypatch, _wire):
    monkeypatch.setattr(
        spiral_breaker, "check_celebration_allowed", lambda *a, **k: (False, {"suppressed": True, "reasons": ["synthetic downturn"]})
    )
    rows = [GENESIS_ROW, _event("w300", "2026-08-18")]
    result, table = _run(rows, monkeypatch=monkeypatch)
    assert result["status"] == "suppressed"
    assert _wire.sends == [] and table.puts == []


def test_breaker_exception_fails_closed(monkeypatch, _wire):
    monkeypatch.setattr(spiral_breaker, "check_celebration_allowed", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("ddb down")))
    rows = [GENESIS_ROW, _event("w300", "2026-08-18")]
    result, table = _run(rows, monkeypatch=monkeypatch)
    assert result["status"] == "suppressed"
    assert _wire.sends == [] and table.puts == []


def test_cooldown_defers_within_ten_days(monkeypatch, _wire):
    rows = [GENESIS_ROW, _digest_sent("w310", "2026-08-15"), _event("w310", "2026-08-14"), _event("w300", "2026-08-19")]
    result, table = _run(rows, monkeypatch=monkeypatch)
    assert result == {"status": "cooldown_deferred", "pending": 1}
    assert _wire.sends == [] and table.puts == []


def test_quiet_when_everything_already_sent(monkeypatch, _wire):
    rows = [GENESIS_ROW, _digest_sent("w310", "2026-08-01"), _event("w310", "2026-07-30")]
    result, table = _run(rows, monkeypatch=monkeypatch)
    assert result == {"status": "quiet"}
    assert _wire.sends == []


def test_zero_deliveries_raises_and_leaves_cursor(monkeypatch, _wire):
    monkeypatch.setattr(shell, "ses", FakeSes(fail_all=True))
    rows = [GENESIS_ROW, _event("w300", "2026-08-18")]
    table = FakeDdbTable(rows=rows)
    monkeypatch.setattr(shell, "table", table)
    with pytest.raises(RuntimeError):
        shell.lambda_handler({}, None)
    assert table.puts == []


def test_oldest_pending_goes_first(monkeypatch, _wire):
    rows = [GENESIS_ROW, _event("w300", "2026-08-18"), _event("w310", "2026-08-02")]
    result, _ = _run(rows, monkeypatch=monkeypatch)
    assert result["milestone_id"] == "w310"
