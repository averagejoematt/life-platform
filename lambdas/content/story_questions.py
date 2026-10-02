"""content/story_questions.py — the reply desk: the week's questions, by email, answered by hitting reply (#4546).

The red team's first finding was that the subject never speaks: five installments, not one line in his own words.
His journal is off the record and often quiet, and that is fine — so before each week is written, the desk sends
him three to five short questions about what the data cannot say (a decision, a moment, how something felt, what a
coach asked of him). He hits reply and types under any of them. His answers become "owner_voice" in that week's
dossier; the writers may quote at most two lines exactly.

Rules that keep it easy and safe:
  * questions are specific to this week's data and answerable in one line; never about vices, family, partner,
    work, or the journal; at most one about feelings;
  * nothing is required: no reply → the week is written as normal, and the absence is never narrated;
  * anything he marks "off record" (or "OTR") is background only and never quoted;
  * the email itself states those rules, so a reply is informed consent for what it does not mark off record.

The loop reuses the platform's existing inbound path: SES receipt rule ``insight-capture`` → S3 →
``insight-email-parser``, which routes a reply whose subject carries ``[SQ-W<n>]`` here.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional

REPLY_TO = "insight@aws.mattsusername.com"
SUBJECT_TOKEN = re.compile(r"\[SQ-W(\d+)\]")
QA_SK_PREFIX = "STORYQA#W"
MIN_QUESTIONS, MAX_QUESTIONS = 3, 5

# The fallback set — the features editor's ten, trimmed to the ones that need no week-specific data.
FALLBACK = [
    "What did you choose to do this week that the plan didn't ask for, and why?",
    "What did the hardest moment of the week look like, and when was it?",
    "Which coach was most wrong about you this week?",
    "Before you look at any data: rate the week 1-10, and one sentence why.",
    "What did you notice this week that you didn't notice in 2024-25?",
]

RUBRIC = """You are the series editor of "The Measured Life", a weekly chronicle and podcast about one man's year-long health
experiment. Before the week is written you send him a few questions by email. He answers by hitting reply and typing
a line under each — so every question must be answerable in ONE line, without thinking hard.

Ask about what the data CANNOT say: a decision he made, a moment that stood out, how something the data shows felt
from the inside, whether he did what a coach asked, what he would tell someone starting this. Anchor each question
in a specific thing from this week's dossier (a day, a session, a number) so it is concrete. 3 to 5 questions.
At most ONE about feelings. Never ask about vices or substances, family, partner, his job, his journal, or his
weight goal as a feeling. Never lead the witness. Plain, friendly, short (under 25 words each)."""

_SCHEMA = {
    "type": "object",
    "properties": {"questions": {"type": "array", "items": {"type": "string"}}},
    "required": ["questions"],
    "additionalProperties": False,
}


def generate(dossier: Dict[str, Any], ledger_view: Dict[str, Any], *, invoke: Optional[Callable[..., Dict[str, Any]]] = None) -> List[str]:
    """3-5 gap questions for the week; falls back to the fixed set on any failure (the questions must never block)."""
    body = {
        "system": RUBRIC,
        "messages": [
            {
                "role": "user",
                "content": f"THIS WEEK'S DOSSIER:\n{json.dumps(dossier, default=str)[:60000]}\n\nTHE SEASON SO FAR:\n{json.dumps(ledger_view, default=str)[:8000]}\n\nReturn the questions.",
            }
        ],
        "max_tokens": 1200,
        "temperature": 0.5,
        "output_config": {"format": {"type": "json_schema", "schema": _SCHEMA}},
    }
    try:
        if invoke is None:
            from ai import bedrock_client
            from ai.model_defaults import NARRATIVE_MODEL

            resp = bedrock_client.invoke_with_retry(body, NARRATIVE_MODEL)
        else:
            resp = invoke(body, "test")
        if resp.get("stop_reason") != "end_turn":
            raise ValueError(f"stop_reason={resp.get('stop_reason')}")
        text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        qs = [q.strip() for q in json.loads(text).get("questions", []) if q and q.strip()]
        qs = [q for q in qs if not _forbidden(q)][:MAX_QUESTIONS]
        if len(qs) >= MIN_QUESTIONS:
            return qs
    except Exception:  # noqa: BLE001 — the questions are optional; never the reason a week does not ship
        pass
    return FALLBACK[:4]


_FORBIDDEN = re.compile(
    r"\b(?:journal|alcohol|drink|vape|wife|girlfriend|partner|mother|father|mom|dad|family|job|boss|work)\b", re.IGNORECASE
)


def _forbidden(q: str) -> bool:
    return bool(_FORBIDDEN.search(q))


def render_email(week: int, questions: List[str]) -> Dict[str, str]:
    """Subject + plain-text body. The rules ride in the body so a reply is informed."""
    lines = [f"Q{i}: {q}" for i, q in enumerate(questions, 1)]
    body = (
        f"A few quick ones for Week {week}. Just hit reply and type under any question — one line is plenty. Skip any.\n\n"
        + "\n\n".join(lines)
        + "\n\n—\nYour answers may be quoted (exactly, at most two short lines) in this week's chronicle or episode. "
        'Put "off record" in an answer to keep it as background only. No reply is fine; the week publishes either way.'
    )
    return {"subject": f"The Measured Life · Week {week} · {len(questions)} quick questions [SQ-W{week}]", "body": body}


def week_from_subject(subject: str) -> Optional[int]:
    m = SUBJECT_TOKEN.search(subject or "")
    return int(m.group(1)) if m else None


_Q_LINE = re.compile(r"^\s*(?:>\s*)*Q(\d+)\s*[:.)-]\s*(.*)$", re.IGNORECASE)
_NUM_LINE = re.compile(r"^\s*(\d+)\s*[:.)-]\s+(.*)$")
_QUOTE_HEADER = re.compile(r"^\s*On .{3,120}wrote:\s*$|^-{2,}\s*Original Message", re.IGNORECASE)
_OFF = re.compile(r"\b(?:off[ -]?(?:the[ -])?record|OTR)\b", re.IGNORECASE)


def parse_reply(body: str, questions: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Pair answers with questions from a reply body. Handles the two ways people answer:
    inline (typed under each quoted 'Q3: …' line) and top-posted ('1. …' / 'Q1: …' above the quote)."""
    lines = (body or "").replace("\r\n", "\n").split("\n")
    answers: Dict[int, List[str]] = {}
    quoted_q: Dict[int, str] = {}
    current: Optional[int] = None
    seen_inline = False
    for raw in lines:
        if _QUOTE_HEADER.match(raw):
            current = None
            continue
        is_quoted = raw.lstrip().startswith(">")
        m = _Q_LINE.match(raw)
        if m and is_quoted:  # a quoted question: answers typed below it belong to it
            current = int(m.group(1))
            quoted_q[current] = m.group(2).strip()
            seen_inline = True
            continue
        if is_quoted:
            continue
        if m and not is_quoted:  # "Q2: my answer" typed by him
            current = int(m.group(1))
            if m.group(2).strip():
                answers.setdefault(current, []).append(m.group(2).strip())
            continue
        n = _NUM_LINE.match(raw)
        if n and not seen_inline:
            current = int(n.group(1))
            answers.setdefault(current, []).append(n.group(2).strip())
            continue
        if current is not None and raw.strip() and not raw.strip().startswith("—"):
            answers.setdefault(current, []).append(raw.strip())
    out = []
    for q_no in sorted(answers):
        text = " ".join(answers[q_no]).strip()
        if not text:
            continue
        q_text = questions[q_no - 1] if questions and 0 < q_no <= len(questions) else quoted_q.get(q_no)
        out.append({"q": q_no, "question": q_text, "answer": _clean(text), "off_record": bool(_OFF.search(text))})
    return out


def _clean(text: str) -> str:
    """His words as typed, minus an off-record marker (and the colon that introduced it). Never trims his punctuation:
    an answer is quotable only exactly."""
    t = _OFF.sub(" ", text)
    t = re.sub(r"\s+:\s*", " ", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def qa_row(pk: str, week: int, answers: List[Dict[str, Any]], *, received_at: str, source_key: str) -> Dict[str, Any]:
    return {
        "pk": pk,
        "sk": f"{QA_SK_PREFIX}{week:03d}#{received_at}",
        "record_type": "story_qa",
        "week": week,
        "answers_json": json.dumps(answers),
        "received_at": received_at,
        "source_key": source_key,
        "privacy": "owner_voice: quotable exactly unless off_record",
        "phase": "experiment",
    }


def owner_voice(table: Any, pk: str, week: int) -> Dict[str, Any]:
    """The week's answers for the dossier; empty when he did not reply (never an error)."""
    try:
        from boto3.dynamodb.conditions import Key

        resp = table.query(KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(f"{QA_SK_PREFIX}{week:03d}#"))
        answers: List[Dict[str, Any]] = []
        for it in resp.get("Items", []):
            answers += json.loads(it.get("answers_json") or "[]")
        return {"answers": answers, "rules": "quote at most two short lines exactly; never an off_record answer"} if answers else {}
    except Exception:  # noqa: BLE001 — absence of his voice is a normal week
        return {}


def send(ses: Any, *, week: int, questions: List[str], to: str, sender: str) -> Dict[str, Any]:
    """Send the week's questions with Reply-To pointed at the platform's inbound address (the missing piece that kept
    the reply loop silent since February). Returns the SES response."""
    e = render_email(week, questions)
    return ses.send_email(
        FromEmailAddress=sender,
        Destination={"ToAddresses": [to]},
        ReplyToAddresses=[REPLY_TO],
        Content={"Simple": {"Subject": {"Data": e["subject"]}, "Body": {"Text": {"Data": e["body"]}}}},
    )


# ── the quotable form of an answer ───────────────────────────────────────────
#
# He answers fast, on a phone, in lowercase. A newsroom quotes a written answer with its spelling and capitalization
# fixed and every word kept — never a [sic] parade, never commentary on how he typed. The copyedit is a model pass held
# to that brief by code: a result that changes more than COPYEDIT_MAX_CHANGE of the words is rejected and the raw
# answer is used instead (quoted exactly, or paraphrased).

COPYEDIT_MAX_CHANGE = 0.15
_COPYEDIT = (
    "Copyedit this reply for publication as a quote. Fix ONLY spelling, capitalization and punctuation. Do not add, remove, "
    "reorder or replace words (contractions may gain their apostrophe). Return only the corrected text."
)


def copyedit(answer: str, *, invoke: Optional[Callable[..., Dict[str, Any]]] = None) -> str:
    import difflib

    body = {"system": _COPYEDIT, "messages": [{"role": "user", "content": answer}], "max_tokens": 1500, "temperature": 0}
    try:
        if invoke is None:
            from ai import bedrock_client
            from ai.model_defaults import NARRATIVE_MODEL

            resp = bedrock_client.invoke_with_retry(body, NARRATIVE_MODEL)
        else:
            resp = invoke(body, "test")
        if resp.get("stop_reason") != "end_turn":
            return answer
        fixed = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text").strip()
    except Exception:  # noqa: BLE001 — the raw answer is always a valid fallback
        return answer

    def words(s: str) -> List[str]:
        return re.findall(r"[a-z0-9]+", s.lower().replace("'", ""))

    a, b = words(answer), words(fixed)
    changed = 1 - difflib.SequenceMatcher(a=a, b=b).ratio()
    return fixed if fixed and changed <= COPYEDIT_MAX_CHANGE else answer
