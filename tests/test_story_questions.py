"""tests/test_story_questions.py — the reply desk's parser and email (#4546). Fixtures are the two real ways a
person answers an email: inline under each quoted question, and top-posted above the quote."""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from content import story_questions as q  # noqa: E402

QS = ["Did you take the rest day Max suggested?", "What did Sunday's 8-mile walk feel like?", "Which coach was most wrong about you?"]

INLINE = """Mostly yes.

On Mon, Oct 5, 2026 at 9:00 AM The Measured Life <lifeplatform@mattsusername.com> wrote:
> A few quick ones for Week 5.
>
> Q1: Did you take the rest day Max suggested?
No. Felt like I'd lose the thread if I stopped.
>
> Q2: What did Sunday's 8-mile walk feel like?
Honestly the best part of the week. off record: my knee was sore after.
>
> Q3: Which coach was most wrong about you?
"""

TOP_POSTED = """1. No, I trained anyway.
2. Best part of the week.

On Mon, Oct 5, 2026 at 9:00 AM wrote:
> Q1: Did you take the rest day Max suggested?
> Q2: What did Sunday's 8-mile walk feel like?
"""


def test_inline_answers_pair_with_their_questions():
    a = q.parse_reply(INLINE, QS)
    assert [(x["q"], x["off_record"]) for x in a] == [(1, False), (2, True)]
    assert a[0]["answer"] == "No. Felt like I'd lose the thread if I stopped."
    assert a[0]["question"] == QS[0]
    # the unanswered Q3 is simply absent — never an empty quote


def test_top_posted_answers_pair_by_number():
    a = q.parse_reply(TOP_POSTED, QS)
    assert [(x["q"], x["answer"]) for x in a] == [(1, "No, I trained anyway."), (2, "Best part of the week.")]


def test_the_old_extractor_would_have_dropped_inline_answers():
    """Mutation control for the bug this route exists to avoid: cutting at the first quoted line loses every
    inline answer."""
    cut = INLINE.split("\n> ")[0]
    assert q.parse_reply(cut, QS) == []


def test_the_email_carries_its_rules_and_routing_token():
    e = q.render_email(5, QS)
    assert q.week_from_subject(e["subject"]) == 5
    assert "off record" in e["body"] and "No reply is fine" in e["body"]
    assert e["body"].count("\nQ") + e["body"].startswith("Q") >= 3


def test_forbidden_topics_never_reach_him():
    def fake(body, model):
        return {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": '{"questions": ["How was work?", "Did you journal?", "What did the walk feel like?"]}'}],
        }

    assert q.generate({}, {}, invoke=fake) == q.FALLBACK[:4]  # 1 survivor < 3 → the fallback set


def test_a_failed_generation_never_blocks():
    def boom(body, model):
        raise RuntimeError("bedrock down")

    assert q.generate({}, {}, invoke=boom) == q.FALLBACK[:4]


def test_the_parser_writes_what_the_dossier_reads():
    """Producer/consumer contract on the real row shape: qa_row (written by insight-email-parser) round-trips through
    owner_voice (read by the week dossier). Mutation control: a different week reads nothing."""
    rows = []

    class _T:
        def put_item(self, Item):
            rows.append(Item)

        def query(self, KeyConditionExpression):
            # emulate begins_with on the sk the reader asks for
            want = KeyConditionExpression.get_expression()["values"][1].get_expression()["values"][1]
            return {"Items": [r for r in rows if r["sk"].startswith(want)]}

    pk = "USER#matthew#SOURCE#insights"
    _T().put_item(q.qa_row(pk, 5, q.parse_reply(INLINE, QS), received_at="2026-10-05T16:00:00Z", source_key="raw/inbound_email/x"))
    ov = q.owner_voice(_T(), pk, 5)
    assert [a["q"] for a in ov["answers"]] == [1, 2] and ov["answers"][1]["off_record"] is True
    assert q.owner_voice(_T(), pk, 6) == {}


def test_copyedit_fixes_spelling_but_cannot_rewrite_him():
    raw = "i think im probably tougher on myself this time because of how disappointed i am having conqured it so recently"

    def tidy(body, model):
        return {
            "stop_reason": "end_turn",
            "content": [
                {
                    "type": "text",
                    "text": "I think I'm probably tougher on myself this time because of how disappointed I am having conquered it so recently.",
                }
            ],
        }

    def rewrite(body, model):
        return {
            "stop_reason": "end_turn",
            "content": [
                {"type": "text", "text": "This time the stakes feel higher, and I am harder on myself after such a recent victory."}
            ],
        }

    assert q.copyedit(raw, invoke=tidy).startswith("I think I'm probably tougher")
    assert q.copyedit(raw, invoke=rewrite) == raw  # mutation control: a rewrite is rejected, the raw answer stands
