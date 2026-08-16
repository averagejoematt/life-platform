"""#2654 — the between-chronicle privacy scrub fails CLOSED.

The 2026-08-14 bug bash found `_scrub` wrapped in a bare `except Exception`
returning the UNSCRUBBED text — a fail-open privacy path on an outbound email.
These tests pin the fix:

  1. A broken vocabulary loader (all channels dead, the REAL
     ContentFilterUnavailable raise — the loader is broken at the channel
     boundary, never stubbed with its own failure value, #2736 class) aborts
     the send: lambda_handler raises and ses.send_email is NEVER called.
     Asserted at the SEND boundary — "the handler returned an error" is a
     weaker claim than "nothing was handed to SES".
  2. The failure logs the distinct SCRUB_FAILED_TOKEN line (the alarm's signal).
  3. The CDK MetricFilter literal and the lambda's token constant are twins —
     parsed from both sources, so they cannot drift apart silently.
  4. The happy path is a planted-token end-to-end: a fake blocked term planted
     via the env channel (the documented config shape) travels
     content_filter_channel -> privacy_guard.scrub -> build_email and comes out
     redacted. Real loader, real guard, real renderer — no stubs in the path.
"""

import os
import re
import sys

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import between_chronicle_lambda as bc  # noqa: E402
from privacy import (
    content_filter_channel as channel,  # noqa: E402
    privacy_guard,  # noqa: E402
)

LAMBDA_SRC = open(os.path.join(_REPO, "lambdas/emails/between_chronicle_lambda.py")).read()
STACK_SRC = open(os.path.join(_REPO, "cdk/stacks/monitoring_stack.py")).read()

# A digest with real content in every scrubbed field class.
_PLANT = "zebrafish747"


def _real_digest(with_plant: bool = False) -> dict:
    note = f"Elena watched the {_PLANT} plan hold" if with_plant else "Elena watched the plan hold"
    return {
        "deltas": [
            {"label": "Recovery", "this_month_avg": 62.1, "prior_month_avg": 58.4, "delta": 3.7, "unit": "%", "direction": "improved"}
        ],
        "unlocked": [],
        "decided": [{"coach": "training", "claim": "deload week lands", "status": "confirmed", "notes": ""}],
        "stance_shifts": [],
        "elena_note": note,
    }


def _break_every_channel(monkeypatch):
    """All four vocabulary channels dead -> load(require=True) raises the REAL
    ContentFilterUnavailable from the channel's own code path."""
    monkeypatch.delenv(channel.ENV_VAR, raising=False)
    monkeypatch.setattr(channel, "_from_local_file", lambda: None)
    monkeypatch.setattr(channel, "_from_s3_boto", lambda bucket: None)
    monkeypatch.setattr(channel, "_from_s3_cli", lambda bucket: None)
    channel.reset_cache()
    privacy_guard.reset_vocabulary_cache()


def _arm_env_channel(monkeypatch):
    """The documented config shape (config/content_filter.example.json), with a
    fixture vocabulary — the same way CI arms the enforcement gates."""
    monkeypatch.setenv(channel.ENV_VAR, '{"blocked_vice_keywords": ["%s"], "blocked_vices": ["Zebrafish"]}' % _PLANT)
    channel.reset_cache()
    privacy_guard.reset_vocabulary_cache()


class _SesSpy:
    def __init__(self):
        self.calls = []

    def send_email(self, **kwargs):
        self.calls.append(kwargs)
        return {"MessageId": "spy"}


@pytest.fixture(autouse=True)
def _fresh_caches():
    yield
    channel.reset_cache()
    privacy_guard.reset_vocabulary_cache()


def test_broken_loader_aborts_send_nothing_reaches_ses(monkeypatch):
    """Box 4, mutation-proved: break the loader, assert NOTHING is handed to SES."""
    _break_every_channel(monkeypatch)
    spy = _SesSpy()
    monkeypatch.setattr(bc, "ses", spy)
    monkeypatch.setattr(bc, "gather_digest", lambda: _real_digest())

    class _T:
        def get_item(self, Key):
            return {}

        def put_item(self, Item):
            raise AssertionError("marker must not be written on an aborted send")

    monkeypatch.setattr(bc, "table", _T())
    monkeypatch.setattr(bc, "_get_confirmed_subscribers", lambda: [{"email": "friend@example.com"}])
    monkeypatch.delenv("EXTERNAL_EMAILS_ENABLED", raising=False)

    with pytest.raises(Exception):
        bc.lambda_handler({}, None)
    assert spy.calls == [], "a scrub that cannot run must abort BEFORE any send"


def test_broken_loader_fails_dry_run_too(monkeypatch):
    """dry_run renders through the same scrub — it must fail loudly, not preview raw text."""
    _break_every_channel(monkeypatch)
    monkeypatch.setattr(bc, "gather_digest", lambda: _real_digest())

    class _T:
        def get_item(self, Key):
            return {}

    monkeypatch.setattr(bc, "table", _T())
    with pytest.raises(Exception):
        bc.lambda_handler({"dry_run": True}, None)


def test_scrub_failure_logs_the_alarm_token(monkeypatch):
    """The record must pass through the lambda's logger at ERROR carrying the
    token — asserted with a handler on the logger instance itself (the platform
    logger is a detached singleton with propagate=False, so caplog/capsys
    cannot see it)."""
    import io
    import logging as _logging

    _break_every_channel(monkeypatch)
    buf = io.StringIO()
    h = _logging.StreamHandler(buf)
    bc.logger.addHandler(h)
    try:
        with pytest.raises(Exception):
            bc._scrub("any narrative text")
    finally:
        bc.logger.removeHandler(h)
    assert bc.SCRUB_FAILED_TOKEN in buf.getvalue(), "the alarm's log token must be emitted on scrub failure"


def test_metric_filter_token_twin():
    """The CDK filter literal and the lambda constant may not drift apart."""
    m = re.search(
        r'"ScrubFailFilterBetweenChronicle".*?FilterPattern\.literal\(\'"([^"]+)"\'\)',
        STACK_SRC,
        re.DOTALL,
    )
    assert m, "monitoring_stack.py must define ScrubFailFilterBetweenChronicle with a literal token pattern"
    assert m.group(1) == bc.SCRUB_FAILED_TOKEN
    # and the lambda actually logs the constant in the failure path (not a copy)
    assert "SCRUB_FAILED_TOKEN," in LAMBDA_SRC


def test_no_fail_open_return_remains():
    """The bug itself, pinned: no code path in _scrub returns the raw input on failure."""
    scrub_src = LAMBDA_SRC.split("def _scrub", 1)[1].split("\ndef ", 1)[0]
    assert "return str(text)" not in scrub_src, "fail-open return resurfaced in _scrub"
    assert "raise" in scrub_src


def test_planted_token_scrubbed_end_to_end(monkeypatch):
    """Real loader (env channel) -> real privacy_guard -> real build_email:
    a planted blocked term must come out redacted everywhere it was planted."""
    _arm_env_channel(monkeypatch)
    digest = _real_digest(with_plant=True)
    subject, html = bc.build_email(digest, "friend@example.com")
    assert _PLANT not in subject and _PLANT not in html, "planted token must never survive into the email"
    assert "[redacted]" in html
