"""tests/test_subscriber_promise_1951.py — #1951 (epic #1890 growth-1 finding):
/subscribe/ and the confirmation email promised "The Measured Life every
Wednesday" unconditionally, while the three subscriber-facing weekly senders
(chronicle-email-sender, weekly-signal, between-chronicle) had
EXTERNAL_EMAILS_ENABLED pinned "false" since 2026-04-23 — a confirmed
subscriber could opt in and receive nothing, forever, with every dashboard
green.

Owner decision (issue #1951 comment, 2026-08-02): LIFT the switch rather than
disclose a pause. This suite covers the DURABLE half that survives either
direction — a regression guard, not a one-time fix:

  AC2  operational.qa_check_subscriber_promise — the pure assessor + the
       live-fetching wrapper, proving it actually FAILS on the real defect
       shape (soliciting + confirmed subscribers + a disabled sender), not
       just that it passes on a healthy one.
  Also pins that the guard is wired into qa_smoke_lambda's nightly run, and
  that the three named senders match the owner-decision set (not
  partner-weekly-email, which is a separate private-recipient posture).

AC3 (the kill-switch-skip CloudWatch alarm) is CDK infra, verified by
`cdk synth` in the PR, not unit-tested here.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from operational import qa_check_subscriber_promise as qsp  # noqa: E402 — the SOURCE module (a re-export is not a patch point)

# ── the assessor: pure, no AWS/HTTP ─────────────────────────────────────────


def test_ok_when_site_not_soliciting():
    ok, msg = qsp.assess_subscriber_promise_truth(False, 5, {"chronicle-email-sender": "false"})
    assert ok is True
    assert "not live-soliciting" in msg


def test_ok_when_zero_confirmed_subscribers():
    ok, msg = qsp.assess_subscriber_promise_truth(True, 0, {"chronicle-email-sender": "false"})
    assert ok is True
    assert "0 confirmed" in msg


def test_ok_when_soliciting_subscribers_exist_and_all_senders_enabled():
    flags = {name: "true" for name in qsp.SUBSCRIBER_FACING_SENDERS}
    ok, msg = qsp.assess_subscriber_promise_truth(True, 1, flags)
    assert ok is True
    assert "agree" in msg


def test_fails_on_the_actual_defect_shape():
    """The real incident: page soliciting, a confirmed subscriber exists,
    every subscriber-facing sender still pinned false — exactly the state
    #1951 found live (docs/reviews/FULLREVIEW_2026-08-02_DELTA.md)."""
    flags = {name: "false" for name in qsp.SUBSCRIBER_FACING_SENDERS}
    ok, msg = qsp.assess_subscriber_promise_truth(True, 1, flags)
    assert ok is False
    assert "chronicle-email-sender" in msg
    assert "weekly-signal" in msg
    assert "between-chronicle" in msg


def test_fails_when_only_one_sender_lags_behind():
    flags = {name: "true" for name in qsp.SUBSCRIBER_FACING_SENDERS}
    flags["between-chronicle"] = "false"
    ok, msg = qsp.assess_subscriber_promise_truth(True, 3, flags)
    assert ok is False
    assert "between-chronicle" in msg
    assert "1/3" in msg


def test_fails_when_a_sender_flag_is_missing_or_unreadable():
    """A flag that can't be read must fail closed, not silently pass — from a
    waiting subscriber's seat an unreadable switch and a paused one are the
    same defect."""
    flags = {name: "true" for name in qsp.SUBSCRIBER_FACING_SENDERS}
    flags["weekly-signal"] = "unreadable (not found)"
    ok, msg = qsp.assess_subscriber_promise_truth(True, 2, flags)
    assert ok is False
    assert "weekly-signal" in msg


def test_case_insensitive_true_value():
    """A live env var literal 'True'/'TRUE' must still read as enabled."""
    flags = {name: "True" for name in qsp.SUBSCRIBER_FACING_SENDERS}
    ok, _ = qsp.assess_subscriber_promise_truth(True, 1, flags)
    assert ok is True


def test_owner_decision_sender_set_excludes_partner_email():
    """partner-weekly-email sends to one private recipient — never part of the
    /subscribe/ promise to readers, and NOT named in the owner's #1951
    decision comment. It must not sneak into the guarded set."""
    assert "partner-weekly-email" not in qsp.SUBSCRIBER_FACING_SENDERS
    assert set(qsp.SUBSCRIBER_FACING_SENDERS) == {"chronicle-email-sender", "weekly-signal", "between-chronicle"}


# ── the check wrapper: fetch/introspection wiring + fail-soft ──────────────


def _run_check(monkeypatch, *, site_up=True, count_response=None, sender_flags=None, raise_on=None):
    def fake_site_up(path="/subscribe/", timeout=15):
        if raise_on == "site_up":
            raise TimeoutError("timed out")
        return site_up

    def fake_fetch_json(path, timeout=15):
        if raise_on == "fetch_json":
            raise TimeoutError("timed out")
        return count_response if count_response is not None else {"count": 0}

    def fake_sender_flags():
        if raise_on == "sender_flags":
            raise RuntimeError("AccessDenied")
        return sender_flags or {name: "true" for name in qsp.SUBSCRIBER_FACING_SENDERS}

    monkeypatch.setattr(qsp, "_site_up", fake_site_up)
    monkeypatch.setattr(qsp, "_fetch_json", fake_fetch_json)
    monkeypatch.setattr(qsp, "_live_sender_flags", fake_sender_flags)
    checks = qsp.check_subscriber_promise_truth()
    assert len(checks) == 1
    return checks[0]


def test_check_passes_on_a_healthy_live_state(monkeypatch):
    c = _run_check(monkeypatch, site_up=True, count_response={"count": 2})
    assert c.passed is True


def test_check_fails_on_the_actual_regression(monkeypatch):
    """Proves the check REPORTS a failure, not just that the assessor does."""
    flags = {name: "false" for name in qsp.SUBSCRIBER_FACING_SENDERS}
    c = _run_check(monkeypatch, site_up=True, count_response={"count": 1}, sender_flags=flags)
    assert c.passed is False
    assert c.chronic is not True  # a live promise the infra can't keep — never chronic, must hold the alarm


def test_check_warns_fail_soft_on_subscribe_fetch_error(monkeypatch):
    c = _run_check(monkeypatch, raise_on="site_up")
    assert c.passed is None


def test_check_warns_fail_soft_on_sub_count_fetch_error(monkeypatch):
    c = _run_check(monkeypatch, raise_on="fetch_json")
    assert c.passed is None


def test_check_warns_fail_soft_on_sender_introspection_error(monkeypatch):
    c = _run_check(monkeypatch, raise_on="sender_flags")
    assert c.passed is None


def test_check_wired_into_qa_smoke_lambda():
    """qa_smoke_lambda re-exports check_subscriber_promise_truth and calls it
    in lambda_handler — the same contract check_content_cadence's wiring test
    pins (#1972)."""
    qa_smoke_path = os.path.join(_REPO, "lambdas", "operational", "qa_smoke_lambda.py")
    src = open(qa_smoke_path, encoding="utf-8").read()
    assert "from operational.qa_check_subscriber_promise import" in src
    assert "check_subscriber_promise_truth" in src
    assert "all_checks += check_subscriber_promise_truth()" in src


def test_live_sender_flags_uses_list_functions_not_get_function_configuration():
    """No new IAM grant: the qa-smoke role already has lambda:ListFunctions
    (#1665's check_lambda_secrets); a call to get_function_configuration would
    need a NEW per-function IAM statement this PR does not add."""
    src = open(os.path.join(_REPO, "lambdas", "operational", "qa_check_subscriber_promise.py"), encoding="utf-8").read()
    assert "list_functions" in src
    assert "get_function_configuration" not in src
