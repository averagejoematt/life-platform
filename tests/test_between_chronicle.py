"""#398 — the between-chronicle note: precomputed deltas only, honest silence.

Pins: the digest is assembled purely from records public endpoints already
serve (zero AI inference — no bedrock/ai_calls import), an empty period sends
nothing, an unchanged digest sends nothing (content-hash dedup), the email
carries no open tracking, and the kill switch is honored.
"""

import glob
import json
import os
import sys

import pytest
import schedule_rows  # noqa: E402 - tests/ is on sys.path; #4284 the schedule table

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import between_chronicle_lambda as bc  # noqa: E402

SRC = open(os.path.join(_REPO, "lambdas/emails/between_chronicle_lambda.py")).read()


#: #6244: a fixed Pacific day — every dated fixture below is relative to it, and the handler's clock seam is pinned to it.
TODAY = "2026-11-29"


def _digest(**over):
    d = {"deltas": [], "unlocked": [], "decided": [], "stance_shifts": []}
    d.update(over)
    return d


def _call(**over):
    c = {
        "coach": "training",
        "claim": "Recovery holds above 60",
        "status": "confirmed",
        "reason": "Morning recovery score came in at 64 against a call of 60 — within its usual day-to-day range",
        "decided_at": "2026-11-25",
    }
    c.update(over)
    return c


@pytest.fixture(autouse=True)
def _pinned_day(monkeypatch):
    monkeypatch.setattr(bc, "_today", lambda: TODAY)


def _released(monkeypatch):
    monkeypatch.setattr(bc, "OWNER_RELEASE", {"by": "owner", "released_on": "2026-11-28", "reviewed_render": "fixture"})


def test_zero_new_inference():
    """No AI in this Lambda — it narrates nothing, it lists computed values."""
    for banned in ("bedrock", "ai_calls", "anthropic", "invoke_model"):
        assert banned not in SRC.lower(), f"between-chronicle must not touch {banned}"


def test_empty_period_sends_nothing(monkeypatch):
    monkeypatch.setattr(bc, "gather_digest", lambda: _digest())
    monkeypatch.setattr(bc, "_get_confirmed_subscribers", lambda: [{"email": "x@y.z"}])
    out = bc.lambda_handler({}, None)
    assert out["sent"] == 0 and out["skipped"] == "empty_period"


def test_averages_alone_are_a_quiet_week(monkeypatch):
    """#6244: the month's rolling averages move every week — on their own they are not news, and nothing is sent."""
    d = _digest(
        deltas=[{"label": "Recovery", "this_month_avg": 62.1, "prior_month_avg": 58.4, "delta": 3.7, "unit": "%"}],
        window_start="2026-10-29",
        window_end="2026-11-27",
    )
    monkeypatch.setattr(bc, "gather_digest", lambda: d)
    out = bc.lambda_handler({}, None)
    assert out["sent"] == 0 and out["skipped"] == "empty_period"


def test_unchanged_digest_sends_nothing(monkeypatch):
    d = _digest(decided=[_call()])
    monkeypatch.setattr(bc, "gather_digest", lambda: d)
    curated = bc.curate(d, TODAY)

    class _T:
        def get_item(self, Key):
            return {"Item": {"content_hash": bc.digest_hash({k: v for k, v in curated.items() if k != "today"})}}

    monkeypatch.setattr(bc, "table", _T())
    out = bc.lambda_handler({}, None)
    assert out["sent"] == 0 and out["skipped"] == "unchanged"


def test_kill_switch_honored(monkeypatch):
    _released(monkeypatch)
    monkeypatch.setattr(bc, "gather_digest", lambda: _digest(decided=[_call()]))

    class _T:
        def get_item(self, Key):
            return {}

    monkeypatch.setattr(bc, "table", _T())
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "false")
    out = bc.lambda_handler({}, None)
    assert out["sent"] == 0 and out["skipped"] == "external_emails_disabled"


def test_email_numbers_are_the_records_rounded_and_no_tracking():
    d = _digest(
        deltas=[{"label": "Recovery", "this_month_avg": 62.1, "prior_month_avg": 58.4, "delta": 3.7, "unit": "%"}],
        window_start="2026-10-29",
        window_end="2026-11-27",
        decided=[_call()],
        stance_shifts=[
            {"coach": "sleep", "shift": "The short nights matter more than I first read.", "stage": "Foundation", "as_of": "2026-11-27"}
        ],
    )
    subject, html = bc.build_email(d, "reader@example.com", TODAY)
    text = bc.visible_text(html)
    # #6244: the record's numbers at reading precision, with the window they cover.
    assert "Recovery: 62%, up from 58%" in text
    assert "October 29 to November 27" in text
    assert "graded November 25" in text and "on November 27" in text
    # No open tracking: no image at all (the classic pixel vector), no campaign
    # params, no per-link redirect wrappers.
    for tracker in ("<img", "utm_", "open.gif", "1x1", "/r/?", "redirect?url="):
        assert tracker not in html.lower()
    assert "No open tracking on this email" in html
    assert "unsubscribe" in html
    assert "N=1" in html
    assert "2 things the machine found" in subject


def test_dry_run_builds_without_sending_while_held(monkeypatch):
    d = _digest(decided=[_call()])
    monkeypatch.setattr(bc, "gather_digest", lambda: d)

    class _T:
        def get_item(self, Key):
            return {}

    monkeypatch.setattr(bc, "table", _T())

    def _no_send(**kw):
        raise AssertionError("dry_run must not send")

    monkeypatch.setattr(bc.ses, "send_email", _no_send)
    out = bc.lambda_handler({"dry_run": True}, None)
    assert out["dry_run"] is True and out["held"] is True
    assert "Recovery holds above 60" in json.dumps(out["digest"])


def test_cdk_wiring_exists():
    stack = open(os.path.join(_REPO, "cdk/stacks/email_stack.py")).read()
    assert 'function_name="between-chronicle"' in stack
    assert schedule_rows.expr("between-chronicle") == "cron(0 10 ? * SUN *)"  # #4284: the table row, Pacific wall clock (ADR-165)
    # #2604: role_policies.py is a facade over role_policies_*.py siblings — read the family.
    policies = "".join(open(p).read() for p in sorted(glob.glob(os.path.join(_REPO, "cdk/stacks/role_policies*.py"))))
    assert "def email_between_chronicle" in policies
    lm = json.load(open(os.path.join(_REPO, "ci/lambda_map.json")))
    assert lm["lambdas"]["lambdas/emails/between_chronicle_lambda.py"]["function"] == "between-chronicle"
