"""tests/test_remediation_email_change_5821.py — the remediation email sends only on a change (#5821).

Owner ruling 2026-11-11: the Mon/Wed/Fri (+ dispatch) remediation email goes out only when the
needs-human hand-off changed since the last send. These drive the REAL `agent.email_report`
against a fake S3 (holding the last-sent record) and a fake SES, so "an unchanged list does not
email" is the function's behaviour, not a helper's return value, and each control has a mutation.
"""

import io
import json
import os
import sys

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "remediation"))

import agent  # noqa: E402
import email_change  # noqa: E402


class _FakeS3:
    def __init__(self):
        self.objects = {}

    def get_object(self, Bucket, Key):  # noqa: N803 — boto3 kwarg names
        if Key not in self.objects:
            err = Exception("NoSuchKey")
            err.response = {"Error": {"Code": "NoSuchKey"}}
            raise err
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, Bucket, Key, Body, **_kw):  # noqa: N803
        self.objects[Key] = Body if isinstance(Body, bytes) else Body.encode()


class _FakeSES:
    def __init__(self):
        self.sent = []

    def send_email(self, **kw):
        self.sent.append(kw["Content"]["Simple"]["Subject"]["Data"])


class _FakeSNS:
    """The digest topic (#5821, ruling 2026-11-15): a changed hand-off on a scheduled run is digest
    lines, not an email. `fail=True` stands in for the role without its OpsDigestLine grant."""

    def __init__(self, fail=False):
        self.lines, self.fail = [], fail

    def publish(self, TopicArn, Message, **_kw):  # noqa: N803 — boto3 kwarg names
        if self.fail:
            raise RuntimeError("AuthorizationError: not authorized to perform sns:Publish")
        assert TopicArn.endswith(":life-platform-alerts-digest"), TopicArn
        self.lines.append(json.loads(Message))


def _report(*ids, carried=(), prs=()):
    return {
        "needs_human": [{"issue": f"issue {i}", "action": "do it", "signal_id": i} for i in ids],
        "carried": [{"signal_id": c, "first_seen": "2026-11-01", "renewals": 2} for c in carried],
        "prs": [{"summary": "fix", "pr": p} for p in prs],
    }


def _harness(monkeypatch, event="schedule", sns=None):
    s3, ses = _FakeS3(), _FakeSES()
    sns = sns if sns is not None else _FakeSNS()
    monkeypatch.setattr(agent, "_s3", s3)
    monkeypatch.setattr(agent, "_ses", ses)
    monkeypatch.setattr(agent, "_sns", sns)
    s3.sns = sns  # reachable from the tests that count deliveries
    monkeypatch.setattr(agent.drift_report, "read_latest", lambda *_a: None)
    monkeypatch.setattr(agent.drift_report, "status_html", lambda *_a, **_k: "")
    monkeypatch.setattr(agent.drift_report, "quota_html", lambda *_a, **_k: "")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    return s3, ses


def _deliveries(s3, ses):
    """One delivery = one email, or one digest SUMMARY line (each run queues exactly one)."""
    summaries = [x for x in s3.sns.lines if x["AlarmName"] == "remediation-agent: hand-off changed"]
    return len(ses.sent) + len(summaries)


def test_first_send_delivers_and_records_the_fingerprint(monkeypatch):
    s3, ses = _harness(monkeypatch)
    assert agent.email_report(_report("a@1", carried=["b@1"]), "shadow") is True
    assert _deliveries(s3, ses) == 1
    rec = json.loads(s3.objects[email_change.LAST_SENT_KEY])
    assert rec["fingerprint"] == email_change.fingerprint(_report("a@1", carried=["b@1"]))


def test_an_unchanged_needs_human_list_does_not_email(monkeypatch):
    """THE control: the same hand-off on the next run sends nothing."""
    s3, ses = _harness(monkeypatch)
    agent.email_report(_report("a@1", "b@1"), "shadow")
    # next run: #4034 moved both lines to `carried` (state unchanged) — same hand-off
    assert agent.email_report(_report(carried=["b@1", "a@1"]), "shadow") is False
    assert _deliveries(s3, ses) == 1, "an unchanged needs-human list was delivered again — the #5821 repeat"


def test_a_new_needs_human_line_emails(monkeypatch):
    s3, ses = _harness(monkeypatch)
    agent.email_report(_report("a@1"), "shadow")
    assert agent.email_report(_report("c@2", carried=["a@1"]), "shadow") is True
    assert _deliveries(s3, ses) == 2


def test_a_cleared_line_emails_once_then_quiet(monkeypatch):
    s3, ses = _harness(monkeypatch)
    agent.email_report(_report("a@1", "b@1"), "shadow")
    agent.email_report(_report(carried=["a@1"]), "shadow")  # b cleared — a change
    agent.email_report(_report(carried=["a@1"]), "shadow")  # unchanged
    assert _deliveries(s3, ses) == 2


def test_a_new_pr_awaiting_review_emails(monkeypatch):
    s3, ses = _harness(monkeypatch)
    agent.email_report(_report("a@1"), "shadow")
    agent.email_report(_report(carried=["a@1"], prs=["https://github.com/x/pull/9"]), "shadow")
    assert _deliveries(s3, ses) == 2


def test_manual_dispatch_always_emails(monkeypatch):
    s3, ses = _harness(monkeypatch)
    agent.email_report(_report("a@1"), "shadow")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    agent.email_report(_report(carried=["a@1"]), "shadow")
    assert _deliveries(s3, ses) == 2
    assert len(ses.sent) == 1, "the manual dispatch is the run the owner is waiting on — it must EMAIL (#5821)"


def test_an_unreadable_record_fails_open_to_sending(monkeypatch):
    s3, ses = _harness(monkeypatch)
    s3.objects[email_change.LAST_SENT_KEY] = b"{not json"
    assert agent.email_report(_report("a@1"), "shadow") is True


def test_a_failed_send_does_not_record_so_the_next_run_retries(monkeypatch):
    s3, ses = _harness(monkeypatch, sns=_FakeSNS(fail=True))

    def boom(**_kw):
        raise RuntimeError("ses down")

    monkeypatch.setattr(ses, "send_email", boom)
    assert agent.email_report(_report("a@1"), "shadow") is False
    assert email_change.LAST_SENT_KEY not in s3.objects


def test_mutation_without_the_gate_an_unchanged_list_emails(monkeypatch):
    """MUTATION: the pre-#5821 posture (always send) must red the unchanged-list control."""
    s3, ses = _harness(monkeypatch)
    monkeypatch.setattr(agent.email_change, "should_send", lambda *_a, **_k: (True, "pre-#5821: every run sends"))
    agent.email_report(_report("a@1"), "shadow")
    agent.email_report(_report(carried=["a@1"]), "shadow")
    assert _deliveries(s3, ses) == 2


def test_the_state_key_lives_under_the_prefix_the_role_already_writes():
    """No new infra: the remediation role's S3 write grant is `remediation-log/*`."""
    assert email_change.LAST_SENT_KEY.startswith("remediation-log/")
    assert not email_change.LAST_SENT_KEY.startswith("remediation-log/dispatch-dedupe/"), "that prefix expires in 1 day"


# ── #5821 ruling 2026-11-15: the summary is a digest line, not its own email ─────────────────


def test_a_changed_hand_off_on_a_scheduled_run_is_digest_lines_not_an_email(monkeypatch):
    """THE control: a scheduled (or alarm-dispatched) run queues the hand-off in the LP digest —
    one summary line plus one line per new needs-you item — and sends NO email."""
    for event in ("schedule", "repository_dispatch"):
        s3, ses = _harness(monkeypatch, event=event)
        assert agent.email_report(_report("a@1", "b@2", carried=["c@3"]), "shadow") is True
        assert ses.sent == [], f"{event}: the remediation summary emailed on its own — the pre-ruling posture"
        names = [x["AlarmName"] for x in s3.sns.lines]
        assert names == ["remediation-agent: hand-off changed", "remediation-agent: needs you a@1", "remediation-agent: needs you b@2"]
        assert "2 need you" in s3.sns.lines[0]["NewStateReason"] and "1 still open" in s3.sns.lines[0]["NewStateReason"]
        assert "issue a@1" in s3.sns.lines[1]["NewStateReason"]
        # the fingerprint is recorded, so the unchanged next run stays quiet
        assert email_change.LAST_SENT_KEY in s3.objects


def test_a_digest_publish_failure_falls_back_to_the_email(monkeypatch):
    """Fail towards delivery: the role without its OpsDigestLine grant still gets the hand-off out."""
    s3, ses = _harness(monkeypatch, sns=_FakeSNS(fail=True))
    assert agent.email_report(_report("a@1"), "shadow") is True
    assert len(ses.sent) == 1


def test_mutation_without_the_digest_route_the_scheduled_run_emails(monkeypatch):
    """MUTATION: the pre-ruling posture (digest_report never queues) must red the digest control."""
    s3, ses = _harness(monkeypatch)
    monkeypatch.setattr(agent, "digest_report", lambda *_a, **_k: False)
    agent.email_report(_report("a@1"), "shadow")
    assert len(ses.sent) == 1 and s3.sns.lines == [], "the mutation did not restore the old email"


def test_needs_you_lines_are_capped_and_the_rest_are_counted(monkeypatch):
    s3, ses = _harness(monkeypatch)
    ids = [f"s{i}@1" for i in range(agent.DIGEST_NEEDS_YOU_LINES + 3)]
    agent.email_report(_report(*ids), "shadow")
    assert len(s3.sns.lines) == 1 + agent.DIGEST_NEEDS_YOU_LINES
    assert "3 more need-you lines" in s3.sns.lines[0]["NewStateReason"]
