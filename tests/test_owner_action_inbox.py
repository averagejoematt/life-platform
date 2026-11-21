"""tests/test_owner_action_inbox.py — ADR-170: the owner's inbox carries only steps he must take.

DEFECT CLASS OWNED: *an email nobody can act on*. For six months the daily LP digest listed
every alarm and the urgent topic mailed a raw "ALARM: …" per transition; the owner acted on
none of it (2026-11-21). Now every alarm still reaches the digest queue and the full record is
logged, but the email is sent only when an `operational/owner_actions.py` entry is live, with
the instruction as its subject.

Held here:
  1. every registry pattern matches a REAL producer — a declared CDK alarm, or a notice whose
     subject literal is in the producing Lambda — so an entry cannot outlive what it matches;
  2. each action reads as an instruction (subject-sized `short`, a `do` and a `why_you`);
  3. the handler, fed live-shaped payloads: a code/config alarm sends nothing, an owner alarm
     sends "Do: …", a plain-text urgent-topic notice is matched by its Subject, a standing
     owner red is a weekly (Monday) reminder, a recovered owner alarm sends nothing, and one
     transition arriving through both topics is one fire;
  4. mutation: a registry that claims everything makes the code-alarm control email.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(ROOT, "lambdas"), os.path.join(ROOT, "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from operational import owner_actions as oa  # noqa: E402

# A notice pattern (a plain-text SNS publish, not a CloudWatch alarm) → the producer file and
# the subject literal that must still be in it.
NOTICE_PRODUCERS = {
    "[panel] episode wk* held for review*": (
        "lambdas/emails/coach_panel_podcast_lambda.py",
        'Subject=f"[Panel] Episode wk{week} HELD for review"',
    ),
    "*budget tier raised *→3*": ("lambdas/operational/cost_governor_lambda.py", "Budget tier {direction} {prev}→{new}"),
}
SATURDAY, MONDAY = "2026-11-21", "2026-11-23"


def _declared_alarms() -> set[str]:
    import platform_model_alarms as pma

    return set(pma.extract_alarms())


# ── 1. every pattern has a live producer ──────────────────────────────────────


def test_every_owner_pattern_matches_a_real_producer():
    import fnmatch

    alarms = _declared_alarms()
    for action in oa.OWNER_ACTIONS:
        for pattern in action.patterns:
            if pattern in NOTICE_PRODUCERS:
                path, literal = NOTICE_PRODUCERS[pattern]
                src = open(os.path.join(ROOT, path), encoding="utf-8").read()
                assert literal in src, f"{pattern!r}: its producer no longer publishes {literal!r} ({path})"
                continue
            hits = [a for a in alarms if fnmatch.fnmatchcase(a.lower(), pattern.lower())]
            assert hits, f"owner pattern {pattern!r} matches no declared alarm — the producer is gone or renamed"


def test_the_notice_patterns_match_their_real_subjects():
    assert oa.owner_action_for("[Panel] Episode wk12 HELD for review").short.startswith("approve or drop")
    assert oa.owner_action_for("🛑 Budget tier raised 2→3: Hard cutoff").short.startswith("decide on AI spend")
    assert oa.owner_action_for("⚠️ Budget tier raised 0→1: Caution") is None, "tiers 1-2 resume by themselves — not an owner action"


def test_code_and_config_alarms_are_not_the_owners():
    for name in (
        "site-api-p95-latency-sustained",
        "site-api-errors",
        "life-platform-ingestion-dlq-messages",
        "field-notes-missing",
        "qa-smoke-warnings",
    ):
        assert oa.owner_action_for(name) is None, f"{name} is session work, not an owner action"


# ── 2. each entry reads as an instruction ─────────────────────────────────────


def test_each_action_is_an_instruction():
    shorts = set()
    for a in oa.OWNER_ACTIONS:
        assert a.patterns and a.short and a.do and a.why_you
        assert len("Do: " + a.short) <= 60, f"subject too long for a phone: {a.short!r}"
        assert a.short[0].islower(), "short completes 'Do: …' — lower-case verb first"
        assert a.do[0].isupper() and a.do.rstrip().endswith((".", ")")), f"do must be a whole sentence: {a.do!r}"
        assert a.short not in shorts, f"duplicate short {a.short!r}"
        shorts.add(a.short)


# ── 3. the handler ────────────────────────────────────────────────────────────


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("DIGEST_QUEUE_URL", "https://sqs.fake/queue")
    monkeypatch.setenv("EMAIL_RECIPIENT", "test@example.com")
    monkeypatch.setenv("EMAIL_SENDER", "test@example.com")
    monkeypatch.setenv("AWS_REGION", "us-west-2")


def _mod(today=SATURDAY, standing=()):
    sys.modules.pop("alert_digest_lambda", None)
    sys.modules.pop("operational.alert_digest_lambda", None)
    with patch("boto3.client") as client:
        sqs, ses, cw = MagicMock(), MagicMock(), MagicMock()
        cw.describe_alarms.return_value = {"MetricAlarms": list(standing), "CompositeAlarms": []}
        client.side_effect = lambda svc, **kw: {"sqs": sqs, "sesv2": ses, "cloudwatch": cw}[svc]
        from operational import alert_digest_lambda as mod
    mod.sqs, mod.ses, mod.cloudwatch = sqs, ses, cw
    mod.pacific_today = lambda: today
    return mod


def _alarm(name, state="ALARM", t="2026-11-21T02:20:41Z", reason="threshold crossed"):
    return json.dumps({"AlarmName": name, "NewStateValue": state, "NewStateReason": reason, "StateChangeTime": t})


def _envelope(message, subject=None, t="2026-11-21T02:20:41Z"):
    """The SNS envelope a non-raw SQS subscription delivers (the urgent topic, ADR-170)."""
    env = {"Type": "Notification", "Message": message, "Timestamp": t}
    if subject:
        env["Subject"] = subject
    return json.dumps(env)


def _run(mod, *bodies):
    mod.sqs.receive_message.side_effect = [
        {"Messages": [{"MessageId": str(i), "ReceiptHandle": f"h{i}", "Body": b} for i, b in enumerate(bodies)]},
        {"Messages": []},
    ]
    return mod.lambda_handler({}, None)


def _sent(mod):
    kw = mod.ses.send_email.call_args.kwargs["Content"]["Simple"]
    return kw["Subject"]["Data"], kw["Body"]["Text"]["Data"]


def test_the_2026_11_21_night_sends_nothing(env):
    """The inbox in the screenshot: 8 latency flaps via the urgent topic + digest lines. None is the owner's."""
    mod = _mod()
    flaps = [
        _envelope(_alarm("site-api-p95-latency-sustained", t=f"2026-11-21T10:{m:02d}:41Z"), subject="ALARM: x") for m in range(20, 60, 5)
    ]
    result = _run(mod, *flaps, _alarm("site-api-p95-latency-high"), _alarm("qa-smoke-warnings"))
    assert result["sent"] is False and result["owner_items"] == 0
    mod.ses.send_email.assert_not_called()
    assert "site-api-p95-latency-sustained" in result["record"], "the record is still kept (logged) for sessions"


def test_an_owner_alarm_sends_one_instruction_email(env):
    mod = _mod()
    result = _run(mod, _alarm("chronicle-delivery-heartbeat"), _alarm("site-api-errors"))
    assert result["sent"] is True and result["owner_items"] == 1
    subject, body = _sent(mod)
    assert subject == "Do: approve or hold the chronicle draft"
    assert "press Approve" in body and "Why you:" in body and "chronicle-delivery-heartbeat" in body
    assert "site-api-errors" not in body, "a code alarm must not ride along in the owner email"
    assert "Not for you: 1 other alarm(s)" in body


def test_a_plain_text_urgent_notice_is_matched_by_its_subject(env):
    mod = _mod()
    held = _envelope("The weekly Panel episode for week 12 was held (not published).", subject="[Panel] Episode wk12 HELD for review")
    result = _run(mod, held)
    assert result["sent"] is True
    subject, body = _sent(mod)
    assert subject == "Do: approve or drop the held Panel episode"
    assert "week 12 was held" in body


def test_two_owner_actions_share_one_email(env):
    mod = _mod()
    _run(mod, _alarm("ingest-auth-unhealthy-whoop"), _alarm("calibration-deadman"))
    subject, body = _sent(mod)
    assert subject.startswith("Do: ") and subject.endswith("(+1 more)")
    assert "1. " in body and "2. " in body
    mod.ses.send_email.assert_called_once()


def test_a_recovered_owner_alarm_sends_nothing(env):
    mod = _mod()
    result = _run(
        mod,
        _alarm("chronicle-delivery-heartbeat", t="2026-11-21T01:00:00Z"),
        _alarm("chronicle-delivery-heartbeat", state="OK", t="2026-11-21T03:00:00Z"),
    )
    assert result["sent"] is False


def test_one_transition_through_both_topics_is_one_fire(env):
    mod = _mod()
    raw = _alarm("chronicle-delivery-heartbeat")
    result = _run(mod, raw, _envelope(raw, subject='ALARM: "chronicle-delivery-heartbeat"'))
    assert "×1" in result["record"] and "×2" not in result["record"]


def _standing(name, days):
    return {
        "AlarmName": name,
        "StateValue": "ALARM",
        "StateReason": "r",
        "StateTransitionedTimestamp": datetime.now(timezone.utc) - timedelta(days=days),
    }


def test_a_standing_owner_red_is_a_monday_reminder_not_a_daily_one(env):
    for today, expect in ((SATURDAY, False), (MONDAY, True)):
        mod = _mod(today=today, standing=[_standing("calibration-deadman", 28), _standing("qa-smoke-warnings", 20)])
        result = _run(mod)
        assert result["sent"] is expect, f"{today}: standing owner red sent={result['sent']}"
    _, body = _sent(mod)
    assert "still waiting on you, red for 28d" in body
    assert "Not for you: 1 other alarm(s)" in body


def test_mutation_a_registry_that_claims_everything_emails_the_code_alarm(env, monkeypatch):
    """MUTATION: if every alarm were the owner's, the 11-21 night control would email."""
    mod = _mod()
    everything = oa.OwnerAction(patterns=("*",), short="look at everything", do="Look.", why_you="Nobody else will.")
    monkeypatch.setattr(oa, "OWNER_ACTIONS", (everything,))
    result = _run(mod, _alarm("site-api-p95-latency-sustained"))
    assert result["sent"] is True, "the no-email control cannot fail — it is wired to nothing"
