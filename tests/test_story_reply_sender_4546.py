"""tests/test_story_reply_sender_4546.py — the reply desk's sender gate (#4546).

The Story Desk's Monday questions go TO the chronicle's EMAIL_RECIPIENT, with Reply-To the SES inbound address. A
reply typed from that inbox can arrive From an address the parser's ALLOWED_SENDERS does not list, and the parser
used to drop it with a WARN line — so "he did not answer" and "we threw his answer away" were indistinguishable.

What this pins:
  * STORY_REPLY_SENDERS defaults OFF (empty) — nothing about who may write changes until the owner sets it in CDK;
  * a [SQ-W<n>] reply from an address the parser will not accept is refused LOUDLY (InsightParseFailure + an envelope
    carrying sender/subject, never the body) instead of silently;
  * with the flag on, a listed address that SES's own verdict authenticates lands as paired answers — the real inline
    shape (questions quoted, answers typed under them);
  * that address reaches the desk's route and nothing else (no insight row, no confirmation mail), and an
    unauthenticated or forged-header message from it is refused.

Fully offline: fake S3 / DDB / CloudWatch / SES; no AWS, no network, no mail sent.
"""

import io
import json
import os
import sys

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
if LAMBDAS not in sys.path:
    sys.path.insert(0, LAMBDAS)

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_BUCKET", "test-bucket")

from content import story_questions as sq  # noqa: E402
from emails import insight_email_parser_lambda as iep  # noqa: E402

DESK_ADDR = "desk-inbox@example.invalid"  # stands in for the address the questions are delivered to
OWNER_ADDR = "matthew@example.invalid"  # stands in for an ALLOWED_SENDERS address
QS = [
    "Did you think about skipping Thursday's session?",
    "What did Sunday's 8-mile walk feel like?",
    "Which coach was most wrong about you?",
]
INLINE = f"""Quick ones, inline.

On Mon, Oct 5, 2026 at 9:00 AM The Measured Life <lifeplatform@example.invalid> wrote:
> A few quick ones for Week 5. Just hit reply and type under any question.
>
> Q1: {QS[0]}
No. Felt like I'd lose the thread if I stopped.
>
> Q2: {QS[1]}
Honestly the best part of the week. off record: my knee was sore after.
>
> Q3: {QS[2]}
"""

SES_PASS = "amazonses.com; spf=pass (spf=pass) smtp.mailfrom=example.invalid; dkim=pass header.i=@example.invalid; dmarc=pass header.from=example.invalid;"
SES_FAIL = "amazonses.com; spf=fail smtp.mailfrom=elsewhere.invalid; dkim=none; dmarc=fail header.from=example.invalid;"


def _email(sender, subject, body, auth_headers=()):
    head = "".join(f"Authentication-Results: {h}\r\n" for h in auth_headers)
    return (
        head + f"From: Matthew <{sender}>\r\n"
        "To: insight@aws.example.invalid\r\n"
        f"Subject: {subject}\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n" + body.replace("\n", "\r\n")
    ).encode("utf-8")


SQ_SUBJECT = "Re: The Measured Life · Week 5 · 3 quick questions [SQ-W5]"


class FakeTable:
    def __init__(self):
        self.puts = []

    def put_item(self, **kw):
        self.puts.append(kw["Item"])
        return {}

    def query(self, **kw):
        return {"Items": []}

    def get_item(self, **kw):
        return {}


class FakeS3:
    def __init__(self, raw):
        self.raw = raw
        self.puts = []

    def get_object(self, **kw):
        return {"Body": io.BytesIO(self.raw)}

    def put_object(self, **kw):
        self.puts.append({"Key": kw["Key"], "record": json.loads(kw["Body"])})
        return {}


class FakeCW:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


class FakeSes:
    def __init__(self):
        self.sends = []

    def send_email(self, **kw):
        self.sends.append(kw)
        return {"MessageId": "x"}


@pytest.fixture
def run(monkeypatch):
    """Drive the real handler on one raw email; return (table, s3, cw, ses, owner_words_calls)."""

    def _run(raw, story_senders=frozenset()):
        table, s3, cw, ses = FakeTable(), FakeS3(raw), FakeCW(), FakeSes()
        words = []
        monkeypatch.setattr(iep, "table", table)
        monkeypatch.setattr(iep, "s3", s3)
        monkeypatch.setattr(iep, "cloudwatch", cw)
        monkeypatch.setattr(iep, "ses", ses)
        monkeypatch.setattr(iep, "ALLOWED_SENDERS", {OWNER_ADDR})
        monkeypatch.setattr(iep, "STORY_REPLY_SENDERS", frozenset(story_senders))
        monkeypatch.setattr(iep, "experiment_stamp_for", lambda pk, sk, **kw: {})
        monkeypatch.setattr(iep, "_store_owner_words", lambda *a: words.append(a) or 0)
        resp = iep.lambda_handler({"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": "raw/inbound_email/m1"}}}]}, None)
        assert resp["statusCode"] == 200
        return table, s3, cw, ses, words

    return _run


def _qa_rows(table):
    return [r for r in table.puts if str(r.get("sk", "")).startswith(sq.QA_SK_PREFIX)]


def test_the_flag_defaults_off():
    if os.environ.get("STORY_REPLY_SENDERS"):
        pytest.skip("STORY_REPLY_SENDERS is set in this environment")
    assert iep.STORY_REPLY_SENDERS == frozenset(), "the reply desk's extra sender list must default to empty (OFF)"


def test_a_desk_reply_from_an_unlisted_sender_is_refused_loudly_never_silently(run):
    table, s3, cw, ses, words = run(_email(DESK_ADDR, SQ_SUBJECT, INLINE, [SES_PASS]))
    assert _qa_rows(table) == [] and words == [] and ses.sends == []
    assert [c["MetricData"][0]["MetricName"] for c in cw.calls] == ["InsightParseFailure"]
    assert len(s3.puts) == 1 and s3.puts[0]["record"]["reason"] == "story_reply_story_unknown_sender"
    env = json.dumps(s3.puts[0]["record"])
    assert DESK_ADDR in env and "lose the thread" not in env, "the envelope names who, never carries his words"


def test_flag_on_an_authenticated_desk_reply_lands_as_paired_answers(run):
    table, s3, cw, ses, words = run(_email(DESK_ADDR, SQ_SUBJECT, INLINE, [SES_PASS]), story_senders={DESK_ADDR})
    rows = _qa_rows(table)
    assert len(rows) == 1 and rows[0]["week"] == 5
    answers = json.loads(rows[0]["answers_json"])
    assert [(a["q"], a["question"], a["off_record"]) for a in answers] == [(1, QS[0], False), (2, QS[1], True)]
    assert answers[0]["answer"] == "No. Felt like I'd lose the thread if I stopped."
    assert len(words) == 1 and words[0][1] == 5, "the owner-words store is fed from the same reply"
    assert ses.sends == [] and cw.calls == [] and s3.puts == []


def test_flag_on_an_unauthenticated_or_forged_desk_reply_is_refused(run):
    forged = [SES_FAIL, SES_PASS]  # SES's own (topmost) verdict fails; a pass header below it is the sender's claim
    for headers in ([], forged, ["mx.attacker.invalid; dmarc=pass header.from=example.invalid"]):
        table, s3, cw, ses, words = run(_email(DESK_ADDR, SQ_SUBJECT, INLINE, headers), story_senders={DESK_ADDR})
        assert _qa_rows(table) == [] and words == [], headers
        assert [p["record"]["reason"] for p in s3.puts] == ["story_reply_story_unauthenticated"], headers


def test_flag_on_the_desk_sender_reaches_the_desk_route_and_nothing_else(run):
    raw = _email(DESK_ADDR, "Re: Daily Brief", "track this: sleep debt is driving the afternoon craving window\n", [SES_PASS])
    table, s3, cw, ses, words = run(raw, story_senders={DESK_ADDR})
    assert table.puts == [] and ses.sends == [] and words == [], "no insight row, no confirmation mail"
    assert cw.calls == [] and s3.puts == [], "a non-desk mail from that address is the ordinary silent ignore"


def test_the_verdict_never_extends_a_desk_sender_beyond_a_desk_subject(monkeypatch):
    import email
    from email import policy

    monkeypatch.setattr(iep, "ALLOWED_SENDERS", {OWNER_ADDR})
    monkeypatch.setattr(iep, "STORY_REPLY_SENDERS", frozenset({DESK_ADDR}))
    msg = email.message_from_bytes(_email(DESK_ADDR, "Re: Daily Brief", "x", [SES_PASS]), policy=policy.default)
    assert iep.story_reply_sender_verdict(DESK_ADDR, "Re: Daily Brief", msg) == "rejected"
    assert iep.story_reply_sender_verdict(DESK_ADDR, SQ_SUBJECT, msg) == "story_only"
    assert iep.story_reply_sender_verdict(OWNER_ADDR, "Re: Daily Brief", msg) == "allowed"


def test_an_allowed_sender_still_lands_a_desk_reply_without_the_flag(run):
    table, s3, cw, ses, words = run(_email(OWNER_ADDR, SQ_SUBJECT, INLINE))
    assert len(_qa_rows(table)) == 1 and cw.calls == []


def test_ses_verdict_reading():
    import email
    from email import policy

    def m(*hs):
        return email.message_from_bytes(_email(DESK_ADDR, SQ_SUBJECT, "x", hs), policy=policy.default)

    assert iep._ses_authenticated(m(SES_PASS), DESK_ADDR)
    assert iep._ses_authenticated(m("amazonses.com; spf=pass; dkim=pass header.i=@example.invalid; dmarc=none"), DESK_ADDR)
    assert not iep._ses_authenticated(
        m("amazonses.com; dkim=pass header.i=@other.invalid; dmarc=pass header.from=other.invalid"), DESK_ADDR
    )
    assert not iep._ses_authenticated(m("amazonses.com; dkim=pass header.i=@example.invalid.evil; dmarc=fail"), DESK_ADDR)
    assert not iep._ses_authenticated(m(), DESK_ADDR)


def test_the_wire_shape_of_ses_header_reads_as_authenticated():
    """The header exactly as SES wrote it on a real inbound message in raw/inbound_email/ (2026-02-27, read 2026-10-10;
    folded across lines, the SPF clause carrying its own ';'-separated client-ip/envelope-from/helo) — addresses and
    IP swapped for .invalid / documentation values."""
    import email
    from email import policy

    raw = (
        "X-SES-Spam-Verdict: PASS\r\n"
        "X-SES-Virus-Verdict: PASS\r\n"
        "Received-SPF: pass (spfCheck: domain of example.invalid designates 192.0.2.16 as permitted sender) "
        "client-ip=192.0.2.16; envelope-from=desk-inbox@example.invalid; helo=mail.example.invalid;\r\n"
        "Authentication-Results: amazonses.com;\r\n"
        " spf=pass (spfCheck: domain of example.invalid designates 192.0.2.16 as permitted sender) client-ip=192.0.2.16;"
        " envelope-from=desk-inbox@example.invalid; helo=mail.example.invalid;\r\n"
        " dkim=pass header.i=@example.invalid;\r\n"
        " dmarc=pass header.from=example.invalid;\r\n"
        f"From: Throwaway <{DESK_ADDR}>\r\n"
        f"Subject: {SQ_SUBJECT}\r\n\r\nbody\r\n"
    )
    msg = email.message_from_string(raw, policy=policy.default)
    assert iep._ses_authenticated(msg, DESK_ADDR)
    assert not iep._ses_authenticated(msg, "someone@other.invalid")
