"""#398 — the between-chronicle note: precomputed deltas only, honest silence.

Pins: the digest is assembled purely from records public endpoints already
serve (zero AI inference — no bedrock/ai_calls import), an empty period sends
nothing, an unchanged digest sends nothing (content-hash dedup), the email
carries no open tracking, and the kill switch is honored.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "emails"))

import between_chronicle_lambda as bc  # noqa: E402

SRC = open(os.path.join(_REPO, "lambdas/emails/between_chronicle_lambda.py")).read()


def _digest(**over):
    d = {"deltas": [], "unlocked": [], "decided": [], "stance_shifts": []}
    d.update(over)
    return d


def test_zero_new_inference():
    """No AI in this Lambda — it narrates nothing, it lists computed values."""
    for banned in ("bedrock", "ai_calls", "anthropic", "invoke_model"):
        assert banned not in SRC.lower(), f"between-chronicle must not touch {banned}"


def test_empty_period_sends_nothing(monkeypatch):
    monkeypatch.setattr(bc, "gather_digest", lambda: _digest())
    monkeypatch.setattr(bc, "_get_confirmed_subscribers", lambda: [{"email": "x@y.z"}])
    out = bc.lambda_handler({}, None)
    assert out["sent"] == 0 and out["skipped"] == "empty_period"


def test_unchanged_digest_sends_nothing(monkeypatch):
    d = _digest(
        deltas=[{"label": "Recovery", "this_month_avg": 62.1, "prior_month_avg": 58.4, "delta": 3.7, "unit": "%", "direction": "improved"}]
    )
    monkeypatch.setattr(bc, "gather_digest", lambda: d)

    class _T:
        def get_item(self, Key):
            return {"Item": {"content_hash": bc.digest_hash(d)}}

    monkeypatch.setattr(bc, "table", _T())
    out = bc.lambda_handler({}, None)
    assert out["sent"] == 0 and out["skipped"] == "unchanged"


def test_kill_switch_honored(monkeypatch):
    d = _digest(decided=[{"coach": "training", "claim": "c", "status": "confirmed", "notes": "", "decided_at": "2026-07-01"}])
    monkeypatch.setattr(bc, "gather_digest", lambda: d)

    class _T:
        def get_item(self, Key):
            return {}

    monkeypatch.setattr(bc, "table", _T())
    monkeypatch.setenv("EXTERNAL_EMAILS_ENABLED", "false")
    out = bc.lambda_handler({}, None)
    assert out["sent"] == 0 and out["skipped"] == "external_emails_disabled"


def test_email_numbers_match_the_record_and_no_tracking():
    d = _digest(
        deltas=[{"label": "Recovery", "this_month_avg": 62.1, "prior_month_avg": 58.4, "delta": 3.7, "unit": "%", "direction": "improved"}],
        decided=[
            {
                "coach": "training",
                "claim": "Recovery holds above 60",
                "status": "confirmed",
                "notes": "held at 64",
                "decided_at": "2026-07-01",
            }
        ],
        stance_shifts=[{"coach": "sleep", "shift": "The short nights matter more than I first read.", "stage": "Foundation"}],
    )
    subject, html = bc.build_email(d, "reader@example.com")
    # Numbers verbatim from the record — the same values /api/what_changed serves.
    assert "62.1" in html and "58.4" in html and "held at 64" in html
    # No open tracking: no image at all (the classic pixel vector), no campaign
    # params, no per-link redirect wrappers.
    for tracker in ("<img", "utm_", "open.gif", "1x1", "/r/?", "redirect?url="):
        assert tracker not in html.lower()
    assert "No open tracking on this email" in html
    assert "unsubscribe" in html
    assert "N=1" in html
    assert "3 things the machine found" in subject


def test_dry_run_builds_without_sending(monkeypatch):
    d = _digest(unlocked=[{"interpretation": "Sleep duration tracks with recovery", "r": 0.61}])
    monkeypatch.setattr(bc, "gather_digest", lambda: d)

    class _T:
        def get_item(self, Key):
            return {}

    monkeypatch.setattr(bc, "table", _T())

    def _no_send(**kw):
        raise AssertionError("dry_run must not send")

    monkeypatch.setattr(bc.ses, "send_email", _no_send)
    out = bc.lambda_handler({"dry_run": True}, None)
    assert out["dry_run"] is True and "Sleep duration tracks with recovery" in json.dumps(out["digest"])


def test_cdk_wiring_exists():
    stack = open(os.path.join(_REPO, "cdk/stacks/email_stack.py")).read()
    assert 'function_name="between-chronicle"' in stack
    assert "cron(0 17 ? * SUN *)" in stack
    policies = open(os.path.join(_REPO, "cdk/stacks/role_policies.py")).read()
    assert "def email_between_chronicle" in policies
    lm = json.load(open(os.path.join(_REPO, "ci/lambda_map.json")))
    assert lm["lambdas"]["lambdas/emails/between_chronicle_lambda.py"]["function"] == "between-chronicle"
