"""tests/test_story_reply_desk_escalation_4546.py — an escalated coach ask reaches him by email (#4546, from #4916).

The ledger row is built the way the live one is: ``story_ledger.apply_budget`` appends the ask (the week-6 ask text,
byte-for-byte from the 2026-10-14 15:00Z ``wednesday-chronicle`` log, as in tests/test_story_desk.py) and carries it
``CARRIED_MAX_WEEKS`` installments. The reply is the real inline shape: the quoted question line, his answer typed under
it. No synthetic ask dict anywhere.
"""

from __future__ import annotations

import io
import json
import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("S3_BUCKET", "test-bucket")

from content import (
    story_ledger,  # noqa: E402
    story_questions as sq,  # noqa: E402
)
from emails import insight_email_parser_lambda as iep  # noqa: E402

WK6_ASK = (
    "Identify and name two landmarks: what a genuinely good week feels like from the inside, and the earliest signal "
    "that a hard stretch is coming — the thing that shows up 1–2 days before you would call it hard."
)
GENERATED = [
    "Did you think about skipping Thursday's session?",
    "What did Sunday's 8-mile walk feel like?",
    "Which coach was most wrong about you?",
]
OWNER_ADDR = "matthew@example.invalid"
SES_PASS = "amazonses.com; spf=pass (spf=pass) smtp.mailfrom=example.invalid; dkim=pass header.i=@example.invalid; dmarc=pass header.from=example.invalid;"


def _budget():
    return {
        "lead": {"thread_id": "volume", "angle": "", "why": "", "evidence": []},
        "thread_actions": [],
        "bet_scored": {"result": "none", "note": ""},
        "bet": {"claim": "", "metric": "recovery", "rule": ">=70 on 4 of 7", "window_days": 7},
        "featured_coaches": ["sleep_coach"],
        "beats_used": [],
        "arc_updates": [],
    }


def _escalated_ledger():
    """The live shape: the ask appended in week 5, carried weeks 6-8, escalated in week 8."""
    led = story_ledger.apply_budget(
        story_ledger.empty_ledger(),
        {**_budget(), "coach_asks": [{"coach_id": "mind_coach", "ask": WK6_ASK, "follow_up_by": "Sunday"}]},
        week=5,
        date="2026-10-07",
        title="t",
    )
    key = led["asks"][0]["id"]
    for i in range(story_ledger.CARRIED_MAX_WEEKS):
        fu = {**_budget(), "asks_followed_up": [{"ask_id": key, "ask": "", "outcome": "carried"}]}
        led = story_ledger.apply_budget(led, fu, week=6 + i, date=f"2026-10-{14 + 7 * i}", title="t")
    assert led["asks"][0]["status"] == "escalated" and story_ledger.open_asks(led) == []
    return led


def _inline_reply(questions, answer="Good week: I wake before the alarm. The early signal is skipping the walk. "):
    """His reply, typed under the quoted Q1 (the escalated ask) — the real inline shape."""
    quoted = "\n>\n".join(f"> Q{i}: {q}" for i, q in enumerate(questions, 1))
    return (
        "Quick ones, inline.\n\nOn Mon, Oct 19, 2026 at 9:00 AM The Measured Life <lifeplatform@example.invalid> wrote:\n"
        "> A few quick ones for Week 9. Just hit reply and type under any question.\n>\n"
        + quoted.replace(f"> Q1: {questions[0]}", f"> Q1: {questions[0]}\n{answer}", 1)
        + "\n"
    )


# ── the send: the escalated ask is Q1, tagged, ahead of the generated questions ──────────────────────────


def test_an_escalated_ask_is_the_first_numbered_question_tagged_with_its_id():
    led = _escalated_ledger()
    ask = led["asks"][0]
    esc = sq.escalated_questions(led)
    assert len(esc) == 1 and WK6_ASK in esc[0] and esc[0].endswith(f"[{ask['id']}]") and "mind coach" in esc[0] and "Week 5" in esc[0]
    questions = sq.compose(esc, GENERATED)
    assert questions[0] == esc[0] and questions[1:] == GENERATED  # escalated first, the gap questions after, in order
    e = sq.render_email(9, questions)
    body_lines = e["body"].split("\n")
    assert body_lines[2] == f"Q1: {esc[0]}" and body_lines[4] == f"Q2: {GENERATED[0]}"
    assert sq.week_from_subject(e["subject"]) == 9 and "4 quick questions" in e["subject"]
    assert story_ledger.ASK_TAG_RE.search(body_lines[2]).group(1) == ask["id"] == story_ledger.ask_id(WK6_ASK)


def test_the_set_is_capped_with_the_escalated_asks_kept_and_nothing_repeated():
    esc = [f"ask {i} [ask-0000000{i}]" for i in range(2)]
    qs = sq.compose(esc, ["g1", "g2", esc[0], "g3", "g4"])
    assert qs == esc + ["g1", "g2", "g3"] and len(qs) == sq.MAX_QUESTIONS
    assert sq.compose([f"a{i}" for i in range(7)], GENERATED) == [f"a{i}" for i in range(sq.MAX_QUESTIONS)]
    assert sq.compose([], GENERATED) == GENERATED  # no escalated asks: Monday's send is exactly what it was


def test_the_oldest_escalated_ask_goes_first():
    led = _escalated_ledger()
    newer = {**led["asks"][0], "id": "ask-ffffffff", "ask": "Name the one meal you would not give up.", "week": 7}
    led["asks"].insert(0, newer)
    assert [a["week"] for a in story_ledger.escalated_asks(led)] == [5, 7]
    assert "Week 5" in sq.escalated_questions(led)[0] and "[ask-ffffffff]" in sq.escalated_questions(led)[1]


def test_the_sender_wires_the_escalated_asks_ahead_of_the_generated_questions():
    """The Monday send (wednesday_chronicle_lambda._send_story_questions) composes escalated + generated and logs the outcome."""
    src = open(os.path.join(_REPO, "lambdas", "emails", "wednesday_chronicle_lambda.py"), encoding="utf-8").read()
    body = src[src.index("def _send_story_questions(") : src.index("def lambda_handler(")]
    assert "story_questions.escalated_questions(ledger)" in body
    assert "story_questions.compose(escalated, story_questions.generate(" in body
    assert "logger.info(" in body and "escalated ask(s)" in body
    assert body.index("escalated_questions(ledger)") < body.index("story_questions.send(")


# ── the reply: the inline extractor pairs the answer to the tagged question, the ledger marks the ask answered ──


def test_the_parsed_inline_reply_marks_the_escalated_ask_answered_when_the_week_publishes():
    led = _escalated_ledger()
    questions = sq.compose(sq.escalated_questions(led), GENERATED)
    answers = sq.parse_reply(_inline_reply(questions))  # Monday: the parser has no question list from the subject
    assert [a["q"] for a in answers] == [1] and story_ledger.tagged_ask_id(answers[0]) == led["asks"][0]["id"]
    assert answers[0]["answer"].startswith("Good week: I wake before the alarm.")
    # Wednesday: the publish path hands the week's owner_voice answers to the ledger
    new = story_ledger.apply_budget(led, _budget(), week=9, date="2026-11-04", title="t", owner_answers=answers)
    ask = new["asks"][0]
    assert ask["status"] == "answered" and ask["answered_week"] == 9 and ask["answer"] == answers[0]["answer"]
    assert story_ledger.escalated_asks(new) == [] and sq.escalated_questions(new) == []  # next Monday does not re-ask
    assert led["asks"][0]["status"] == "escalated"  # apply_budget never mutates the previous ledger


def test_an_off_record_answer_marks_the_ask_answered_but_keeps_his_words_out_of_the_ledger():
    led = _escalated_ledger()
    questions = sq.compose(sq.escalated_questions(led), GENERATED)
    answers = sq.parse_reply(_inline_reply(questions, answer="off record: the signal is a fight with my sleep."))
    assert answers[0]["off_record"] is True
    new = story_ledger.apply_budget(led, _budget(), week=9, date="d", title="t", owner_answers=answers)
    assert new["asks"][0]["status"] == "answered" and new["asks"][0]["answer"] is None
    assert "fight with my sleep" not in json.dumps(new)


def test_an_answer_under_a_generated_question_marks_nothing():
    led = _escalated_ledger()
    questions = sq.compose(sq.escalated_questions(led), GENERATED)
    body = _inline_reply(questions, answer="")  # nothing under Q1
    body = body.replace(f"> Q2: {GENERATED[0]}", f"> Q2: {GENERATED[0]}\nNo, never crossed my mind.")
    answers = sq.parse_reply(body, questions)
    assert [a["q"] for a in answers] == [2] and story_ledger.tagged_ask_id(answers[0]) is None
    new = story_ledger.apply_budget(led, _budget(), week=9, date="d", title="t", owner_answers=answers)
    assert new["asks"][0]["status"] == "escalated"


def test_mutation_control_the_untagged_send_never_lets_the_reply_reach_the_ask():
    """Before this change Monday's send carried only the generated questions: an escalated ask was never sent, and an
    answer with no tag in its question text marks nothing — the silent retirement this closes."""
    led = _escalated_ledger()
    old_send = sq.render_email(9, sq.generate({}, {}, invoke=lambda *_: {"stop_reason": "refused"}))  # the pre-#4546 path
    assert WK6_ASK not in old_send["body"] and not story_ledger.ASK_TAG_RE.search(old_send["body"])
    untagged = sq.compose([sq.escalated_questions(led)[0].rsplit(" [", 1)[0]], GENERATED)  # the tag stripped
    answers = sq.parse_reply(_inline_reply(untagged))
    assert [a["q"] for a in answers] == [1] and WK6_ASK in answers[0]["question"]
    new = story_ledger.apply_budget(led, _budget(), week=9, date="d", title="t", owner_answers=answers)
    assert new["asks"][0]["status"] == "escalated" and story_ledger.mark_answered(led, answers, week=9) == []


def test_the_publish_path_hands_the_weeks_owner_voice_to_the_ledger():
    src = open(os.path.join(_REPO, "lambdas", "content", "story_pipeline.py"), encoding="utf-8").read()
    assert 'owner_answers=(dossier.get("owner_voice") or {}).get("answers")' in src


# ── the wire: the parser reads Monday's sent questions from the marker, so a quote-stripped reply still pairs ──


class _Table:
    def __init__(self, marker=None):
        self.puts, self.marker = [], marker

    def put_item(self, **kw):
        self.puts.append(kw["Item"])
        return {}

    def query(self, **kw):
        return {"Items": []}

    def get_item(self, **kw):
        return {"Item": self.marker} if self.marker and kw["Key"]["sk"] == self.marker["sk"] else {}


class _S3:
    def __init__(self, raw):
        self.raw, self.puts = raw, []

    def get_object(self, **kw):
        return {"Body": io.BytesIO(self.raw)}

    def put_object(self, **kw):
        self.puts.append(kw)
        return {}


class _Sink:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)

    def send_email(self, **kw):
        self.calls.append(kw)
        return {"MessageId": "x"}


def _email(subject, body):
    return (
        f"Authentication-Results: {SES_PASS}\r\nFrom: Matthew <{OWNER_ADDR}>\r\nTo: insight@aws.example.invalid\r\n"
        f"Subject: {subject}\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n" + body.replace("\n", "\r\n")
    ).encode("utf-8")


@pytest.fixture
def run(monkeypatch):
    def _run(raw, marker=None):
        table, s3, sink = _Table(marker), _S3(raw), _Sink()
        monkeypatch.setattr(iep, "table", table)
        monkeypatch.setattr(iep, "s3", s3)
        monkeypatch.setattr(iep, "cloudwatch", sink)
        monkeypatch.setattr(iep, "ses", sink)
        monkeypatch.setattr(iep, "ALLOWED_SENDERS", {OWNER_ADDR})
        monkeypatch.setattr(iep, "STORY_REPLY_SENDERS", frozenset())
        monkeypatch.setattr(iep, "experiment_stamp_for", lambda pk, sk, **kw: {})
        monkeypatch.setattr(iep, "_store_owner_words", lambda *a: 0)
        resp = iep.lambda_handler({"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": "raw/inbound_email/m1"}}}]}, None)
        assert resp["statusCode"] == 200
        return [r for r in table.puts if str(r.get("sk", "")).startswith(sq.QA_SK_PREFIX)]

    return _run


def test_a_quote_stripped_reply_pairs_to_the_tagged_ask_through_the_sent_marker(run):
    led = _escalated_ledger()
    questions = sq.compose(sq.escalated_questions(led), GENERATED)
    marker = {"pk": "USER#matthew#SOURCE#chronicle", "sk": "STORYQ#W009", "questions_json": json.dumps(questions)}
    raw = _email(
        "Re: The Measured Life · Week 9 · 4 quick questions [SQ-W9]", "1. I wake before the alarm; the signal is skipping the walk.\n"
    )
    rows = run(raw, marker)
    answers = json.loads(rows[0]["answers_json"])
    assert story_ledger.tagged_ask_id(answers[0]) == led["asks"][0]["id"] and answers[0]["question"] == questions[0]
    assert story_ledger.apply_budget(led, _budget(), week=9, date="d", title="t", owner_answers=answers)["asks"][0]["status"] == "answered"
    # control: no marker → the same reply pairs by number with no question text, so no ask can be marked
    answers = json.loads(run(raw)[0]["answers_json"])
    assert answers[0]["question"] is None and story_ledger.tagged_ask_id(answers[0]) is None


def test_the_marker_read_fails_soft_and_the_tuesday_question_still_wins():
    class Boom:
        def get_item(self, **kw):
            raise RuntimeError("ProvisionedThroughputExceeded")

    assert sq.sent_questions(Boom(), "pk", 9) is None and sq.sent_questions(_Table(), "pk", 9) is None
    assert sq.sent_questions(_Table({"sk": "STORYQ#W009", "questions_json": "[]"}), "pk", 9) is None
    assert sq.questions_for_subject("Week 9 · one question for Wednesday [SQ-W9]") == [sq.tuesday_question(9)]
