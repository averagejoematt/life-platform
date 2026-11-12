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


def _report(*ids, carried=(), prs=()):
    return {
        "needs_human": [{"issue": f"issue {i}", "action": "do it", "signal_id": i} for i in ids],
        "carried": [{"signal_id": c, "first_seen": "2026-11-01", "renewals": 2} for c in carried],
        "prs": [{"summary": "fix", "pr": p} for p in prs],
    }


def _harness(monkeypatch, event="schedule"):
    s3, ses = _FakeS3(), _FakeSES()
    monkeypatch.setattr(agent, "_s3", s3)
    monkeypatch.setattr(agent, "_ses", ses)
    monkeypatch.setattr(agent.drift_report, "read_latest", lambda *_a: None)
    monkeypatch.setattr(agent.drift_report, "status_html", lambda *_a, **_k: "")
    monkeypatch.setattr(agent.drift_report, "quota_html", lambda *_a, **_k: "")
    monkeypatch.setenv("GITHUB_EVENT_NAME", event)
    return s3, ses


def test_first_send_emails_and_records_the_fingerprint(monkeypatch):
    s3, ses = _harness(monkeypatch)
    assert agent.email_report(_report("a@1", carried=["b@1"]), "shadow") is True
    assert len(ses.sent) == 1
    rec = json.loads(s3.objects[email_change.LAST_SENT_KEY])
    assert rec["fingerprint"] == email_change.fingerprint(_report("a@1", carried=["b@1"]))


def test_an_unchanged_needs_human_list_does_not_email(monkeypatch):
    """THE control: the same hand-off on the next run sends nothing."""
    s3, ses = _harness(monkeypatch)
    agent.email_report(_report("a@1", "b@1"), "shadow")
    # next run: #4034 moved both lines to `carried` (state unchanged) — same hand-off
    assert agent.email_report(_report(carried=["b@1", "a@1"]), "shadow") is False
    assert len(ses.sent) == 1, "an unchanged needs-human list sent a second email — the #5821 repeat"


def test_a_new_needs_human_line_emails(monkeypatch):
    s3, ses = _harness(monkeypatch)
    agent.email_report(_report("a@1"), "shadow")
    assert agent.email_report(_report("c@2", carried=["a@1"]), "shadow") is True
    assert len(ses.sent) == 2


def test_a_cleared_line_emails_once_then_quiet(monkeypatch):
    s3, ses = _harness(monkeypatch)
    agent.email_report(_report("a@1", "b@1"), "shadow")
    agent.email_report(_report(carried=["a@1"]), "shadow")  # b cleared — a change
    agent.email_report(_report(carried=["a@1"]), "shadow")  # unchanged
    assert len(ses.sent) == 2


def test_a_new_pr_awaiting_review_emails(monkeypatch):
    s3, ses = _harness(monkeypatch)
    agent.email_report(_report("a@1"), "shadow")
    agent.email_report(_report(carried=["a@1"], prs=["https://github.com/x/pull/9"]), "shadow")
    assert len(ses.sent) == 2


def test_manual_dispatch_always_emails(monkeypatch):
    s3, ses = _harness(monkeypatch)
    agent.email_report(_report("a@1"), "shadow")
    monkeypatch.setenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    agent.email_report(_report(carried=["a@1"]), "shadow")
    assert len(ses.sent) == 2


def test_an_unreadable_record_fails_open_to_sending(monkeypatch):
    s3, ses = _harness(monkeypatch)
    s3.objects[email_change.LAST_SENT_KEY] = b"{not json"
    assert agent.email_report(_report("a@1"), "shadow") is True


def test_a_failed_send_does_not_record_so_the_next_run_retries(monkeypatch):
    s3, ses = _harness(monkeypatch)

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
    assert len(ses.sent) == 2


def test_the_state_key_lives_under_the_prefix_the_role_already_writes():
    """No new infra: the remediation role's S3 write grant is `remediation-log/*`."""
    assert email_change.LAST_SENT_KEY.startswith("remediation-log/")
    assert not email_change.LAST_SENT_KEY.startswith("remediation-log/dispatch-dedupe/"), "that prefix expires in 1 day"
