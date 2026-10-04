"""content/tuesday_question.py — the Tuesday question: one question on Telegram, his reply verbatim (#4584, epic #4580).

WHY
  The epic's second rule is that the person leads: his words sit above the AI's. The site had no weekly source of
  his words. The Story Desk's reply desk (#4546) already asks him, by email on Monday, three to five questions about
  the week. This asks ONE of them again on Tuesday evening, on the Telegram channel he already has open, and stores
  his reply word for word with the question and the date. Wednesday's edition leads with it.

WHO WRITES THE QUESTION
  Nobody new. Monday's ``StoryQuestionsMonday`` send already ran ``content.story_questions.generate`` (one model
  call, the false-premise guard of #4565, numbers grounded against the week's dossier) and stored its questions on
  the ``STORYQ#W{n}`` send marker. This module picks one of those: the first that he has not already answered by
  email and that still passes the guard's deterministic halves (no forbidden topic, no absolute claim). With no
  Monday set it falls back to the desk's fixed questions. It makes no model call and writes nothing in anyone's
  voice: every word it sends is either the desk's question or a fixed sentence in this file.

THE RECORD — pk ``USER#matthew#SOURCE#tuesday_question``
  ``TUESDAYQ#<PT Tuesday>#Q``                    the question: text, week, status (reserved | sent | send_failed),
                                                 the Telegram chat and message ids a reply must quote, sent_at.
  ``TUESDAYQ#<PT Tuesday>#R#<received_at>``      one row per reply message: the text EXACTLY as received, the
                                                 screen verdict (clean | held), and the hit KINDS (never the term).

  Absence semantics at birth (ADR-104): no Q row = no question that week; a Q row with no clean reply = no answer.
  Silence is printed as ``SILENCE_SENTENCE`` and never filled with generated first-person text.

THE FILTER — fail closed
  A reply passes ``privacy.broadcast_sensitivity_gate.deterministic_findings`` (``privacy_guard``'s off-repo vice
  vocabulary + the real-name guard + the PII patterns) plus the vocabulary's ``blocked_vices`` display names. An
  unavailable vocabulary is a hold, never a pass. An "off record" marker is a hold. ANY hold on ANY reply to a
  question withholds every reply to that question: a clean second message can lean on a held first one. Held rows
  are stored and never served. The serve path screens again, so a vocabulary that grew since the reply was taken
  still applies.

WHICH MESSAGE IS A REPLY
  Only a Telegram reply that quotes the question's own message (``reply_to_message.message_id`` in the same chat, on
  the same bot). The question is sent with ``force_reply`` so his phone opens the reply box on it. Anything else he
  types to the bot is a normal coach message — a coach question must never be published by accident.

VOICE NOTES
  The channel has no transcription. A voice note that replies to the question gets a plain answer saying so (type
  it, or dictate it with the keyboard's microphone) and is not stored.
"""

from __future__ import annotations

import json
import re
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

PK = "USER#matthew#SOURCE#tuesday_question"
SK_PREFIX = "TUESDAYQ#"
SOURCE_LABEL = "telegram_tuesday_question"

STATUS_RESERVED = "reserved"
STATUS_SENT = "sent"
STATUS_SEND_FAILED = "send_failed"

VERDICT_CLEAN = "clean"
VERDICT_HELD = "held"
HOLD_FILTER_UNAVAILABLE = "filter_unavailable"
HOLD_OFF_RECORD = "off_record"

# The served states. ``no_answer`` deliberately covers BOTH silence and a held reply: the public payload must not
# reveal that he said something the filter stopped.
STATE_ANSWERED = "answered"
STATE_NO_ANSWER = "no_answer"
STATE_NOT_ASKED = "not_asked"
STATE_READ_FAILED = "read_failed"

SILENCE_SENTENCE = "No answer to this week's question is on the record."
NOT_ASKED_SENTENCE = "No Tuesday question has been asked yet."

# How far back a reply may reach: a reply to a question older than this many questions is not matched.
RECENT_QUESTIONS = 8
MAX_REPLY_CHARS = 4000

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"

# ── the fixed sentences (no model writes any of these) ─────────────────────────────────────────────────────────────

INTRO = "This week's question, for Wednesday's front page:"
INSTRUCTIONS = (
    "Reply to this message to answer. Type it, or dictate it with the keyboard microphone. One line is plenty. "
    'It is published word for word unless the privacy filter holds it. Put "off record" in it to keep it private. '
    "No reply is fine; the page will say there was no answer."
)
ACK_CLEAN = "Got it. It goes on the site word for word, under this week's question."
ACK_HELD = "Stored, and held: the privacy filter matched something in it, so nothing from this week's answer goes on the site."
ACK_OFF_RECORD = "Stored as off the record. Nothing from this week's answer goes on the site."
ACK_UNAVAILABLE = "Stored, and held: the privacy filter could not be loaded, so nothing from this week's answer goes on the site."
ACK_VOICE = (
    "Voice notes are not transcribed on this channel, so this one was not kept. Reply to the question again and type "
    "it, or dictate it with the keyboard microphone."
)


def question_sk(day: str) -> str:
    return f"{SK_PREFIX}{day}#Q"


def reply_sk(day: str, received_at: str) -> str:
    return f"{SK_PREFIX}{day}#R#{received_at}"


def _day_of_sk(sk: str) -> str:
    return str(sk)[len(SK_PREFIX) : len(SK_PREFIX) + 10]


# ── choosing the question ────────────────────────────────────────────────────────────────────────────────────────


def passes_guard(q: str) -> bool:
    """The deterministic halves of the desk's question guard (#4565): no forbidden topic, no absolute claim. The
    number half needs the week's dossier and already ran when Monday's set was generated."""
    from content import story_questions

    q = (q or "").strip()
    return bool(q) and not story_questions._forbidden(q) and not story_questions._ABSOLUTE.search(q)


def pick_question(monday_questions: List[str], answered: set) -> Tuple[str, str]:
    """``(question, origin)`` — the first of Monday's questions he has not answered by email and that passes the
    guard; else the first passing fixed question that Monday's set did not already ask."""
    from content import story_questions

    for i, q in enumerate(monday_questions or [], 1):
        if i not in answered and passes_guard(q):
            return q.strip(), "monday_set"
    asked = {(q or "").strip() for q in monday_questions or []}
    for q in story_questions.FALLBACK:
        if q not in asked and passes_guard(q):
            return q, "fallback"
    return story_questions.FALLBACK[0], "fallback"


def monday_questions(table: Any, user_id: str, week: int) -> List[str]:
    """The questions Monday's send stored on its ``STORYQ#W{n}`` marker ([] when it never ran)."""
    item = table.get_item(Key={"pk": f"USER#{user_id}#SOURCE#chronicle", "sk": f"STORYQ#W{week:03d}"}).get("Item") or {}
    try:
        qs = json.loads(item.get("questions_json") or "[]")
    except (TypeError, ValueError):
        return []
    return [str(q) for q in qs if isinstance(q, str)]


def answered_by_email(table: Any, user_id: str, week: int) -> set:
    """The question numbers he already answered by replying to Monday's email (the ``STORYQA#W`` rows)."""
    from boto3.dynamodb.conditions import Key

    from content import story_questions

    pfx = f"{story_questions.QA_SK_PREFIX}{week:03d}#"
    resp = table.query(KeyConditionExpression=Key("pk").eq(f"USER#{user_id}#SOURCE#insights") & Key("sk").begins_with(pfx))
    out: set = set()
    for it in resp.get("Items", []):
        try:
            out |= {int(a.get("q")) for a in json.loads(it.get("answers_json") or "[]") if a.get("q") is not None}
        except (TypeError, ValueError):
            continue
    return out


def render_question(question: str) -> str:
    return f"{INTRO}\n\n{question}\n\n{INSTRUCTIONS}"


# ── sending (urllib, per the no-HTTP-libraries rule) ──────────────────────────────────────────────────────────────


def send_question(token: str, chat_id: Any, question: str, *, urlopen: Callable[..., Any] = urllib.request.urlopen) -> Optional[int]:
    """Send the question with ``force_reply`` and return Telegram's message id, or None on any failure. The id is the
    whole point: a reply is recognised only by quoting it."""
    import urllib.parse

    payload = {
        "chat_id": chat_id,
        "text": render_question(question),
        "reply_markup": json.dumps({"force_reply": True, "input_field_placeholder": "Your answer"}),
    }
    req = urllib.request.Request(
        TELEGRAM_API.format(token=token, method="sendMessage"),
        data=urllib.parse.urlencode(payload).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        with urlopen(req, timeout=15) as r:
            body = json.loads(r.read() or b"{}")
        mid = (body.get("result") or {}).get("message_id") if body.get("ok") else None
        return int(mid) if mid is not None else None
    except Exception:  # noqa: BLE001 — the caller records send_failed; never retried into a double send
        return None


def reserve(table: Any, day: str, row: Dict[str, Any]) -> bool:
    """Claim this Tuesday BEFORE sending (reserve-then-act, #1382): a second invoke, or EventBridge's retry, finds the
    claim and sends nothing. A previous ``send_failed`` claim may be retaken."""
    try:
        table.put_item(
            Item={**row, "pk": PK, "sk": question_sk(day), "status": STATUS_RESERVED},
            ConditionExpression="attribute_not_exists(sk) OR #s = :failed",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":failed": STATUS_SEND_FAILED},
        )
        return True
    except Exception as e:  # noqa: BLE001
        if e.__class__.__name__ == "ConditionalCheckFailedException":
            return False
        raise


def question_row(*, day: str, week: Optional[int], question: str, origin: str, route: str, chat_id: Any) -> Dict[str, Any]:
    return {
        "date": day,
        "week": week,
        "question": question,
        "question_origin": origin,
        "route": route,
        "chat_id": str(chat_id),
        "source": SOURCE_LABEL,
    }


def send_tuesday_question(
    *,
    table: Any,
    now_pt: datetime,
    user_id: str,
    seat: Tuple[Optional[str], Any, Optional[str]],
    quiet: Callable[[datetime], bool],
    send: Callable[..., Optional[int]] = send_question,
    stamp: Callable[[str, str], Dict[str, Any]] = lambda pk, sk: {},
    force: bool = False,
) -> Dict[str, Any]:
    """The scheduled half. ``seat`` is ``(token, chat_id, route)`` for the lead's bot, or Nones when it is dark.

    The cron fires at a fixed UTC instant (Wednesday 02:00 UTC); this re-checks that it is Tuesday in Pacific time,
    which it is in both offsets (19:00 PDT, 18:00 PST). Returns a status dict; every skip names its reason."""
    from content import story_dossier

    day = now_pt.strftime("%Y-%m-%d")
    if now_pt.weekday() != 1 and not force:
        return {"ok": True, "reason": "not_tuesday_pt", "date": day}
    token, chat_id, route = seat
    if not token or chat_id is None or not route:
        return {"ok": True, "reason": "dark", "date": day}
    if quiet(now_pt) and not force:
        return {"ok": True, "reason": "quiet_hours", "date": day}

    wk = story_dossier.week_containing(day)
    week = int(wk["week"]) if wk else None
    qs: List[str] = []
    answered: set = set()
    if week is not None:
        try:
            qs = monday_questions(table, user_id, week)
            answered = answered_by_email(table, user_id, week)
        except Exception:  # noqa: BLE001 — the fixed questions are a valid fallback
            qs, answered = [], set()
    question, origin = pick_question(qs, answered)

    row = question_row(day=day, week=week, question=question, origin=origin, route=route, chat_id=chat_id)
    row.update(stamp(PK, question_sk(day)))
    if not reserve(table, day, row):
        return {"ok": True, "reason": "already_sent", "date": day}
    message_id = send(token, chat_id, question)
    sent_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    if message_id is None:
        table.put_item(Item={**row, "pk": PK, "sk": question_sk(day), "status": STATUS_SEND_FAILED, "failed_at": sent_at})
        return {"ok": False, "reason": "send_failed", "date": day}
    table.put_item(Item={**row, "pk": PK, "sk": question_sk(day), "status": STATUS_SENT, "message_id": message_id, "sent_at": sent_at})
    return {"ok": True, "status": STATUS_SENT, "date": day, "week": week, "origin": origin}


# ── the reply ────────────────────────────────────────────────────────────────────────────────────────────────────


def screen(text: str, *, vocabulary: Optional[Dict[str, Any]] = None) -> Tuple[str, List[str]]:
    """``(verdict, hit_kinds)``. Fail closed: an unavailable vocabulary or any error is a hold. Kinds only — the
    matched term never leaves this function (a leak through the audit trail is still a leak)."""
    from content import story_questions

    if story_questions._OFF.search(text or ""):  # the desk's own off-record marker, one spelling
        return VERDICT_HELD, [HOLD_OFF_RECORD]
    try:
        from privacy import broadcast_sensitivity_gate, content_filter_channel

        data = vocabulary if vocabulary is not None else content_filter_channel.load(require=True)
        if not data:
            return VERDICT_HELD, [HOLD_FILTER_UNAVAILABLE]
        kinds = list(broadcast_sensitivity_gate.deterministic_findings(text or ""))
        lowered = (text or "").lower()
        # The display names, and the keywords of THIS vocabulary (privacy_guard reads the channel's own copy; an
        # injected or freshly-grown vocabulary must still bite).
        names = [
            v.strip().lower()
            for v in (data.get("blocked_vices") or []) + (data.get("blocked_vice_keywords") or [])
            if isinstance(v, str) and v.strip()
        ]
        vice = broadcast_sensitivity_gate.CATEGORY_VICE
        if any(re.search(r"\b" + re.escape(n) + r"\b", lowered) for n in names) and vice not in kinds:
            kinds.append(vice)
        return (VERDICT_HELD, kinds) if kinds else (VERDICT_CLEAN, [])
    except Exception:  # noqa: BLE001 — ContentFilterUnavailable and every other failure: hold, never pass
        return VERDICT_HELD, [HOLD_FILTER_UNAVAILABLE]


def recent_questions(table: Any, limit: int = RECENT_QUESTIONS * 4) -> List[Dict[str, Any]]:
    """The newest rows of the partition, newest first (questions and replies interleaved by sk)."""
    resp = table.query(
        KeyConditionExpression="pk = :pk AND begins_with(sk, :pfx)",
        ExpressionAttributeValues={":pk": PK, ":pfx": SK_PREFIX},
        ScanIndexForward=False,
        Limit=limit,
    )
    return list(resp.get("Items") or [])


def match_question(rows: List[Dict[str, Any]], *, chat_id: Any, reply_to_message_id: Any, route: str) -> Optional[Dict[str, Any]]:
    """The SENT question this message quotes, or None. Telegram message ids are per chat, so the chat and the bot
    both have to match as well as the id."""
    if reply_to_message_id is None:
        return None
    qs = [r for r in rows if str(r.get("sk", "")).endswith("#Q") and r.get("status") == STATUS_SENT][:RECENT_QUESTIONS]
    for r in qs:
        if str(r.get("message_id")) == str(reply_to_message_id) and str(r.get("chat_id")) == str(chat_id) and r.get("route") == route:
            return r
    return None


def handle_reply(*, table: Any, question: Dict[str, Any], text: str, received_at: str, message_id: Any, stamp=None) -> str:
    """Store one reply verbatim with its verdict; return the fixed acknowledgement to send back."""
    day = _day_of_sk(question["sk"])
    verdict, kinds = screen(text)
    sk = reply_sk(day, received_at)
    item = {
        "pk": PK,
        "sk": sk,
        "date": day,
        "question": question.get("question"),
        "text": (text or "")[:MAX_REPLY_CHARS],
        "received_at": received_at,
        "telegram_message_id": message_id,
        "verdict": verdict,
        "hold_kinds": kinds,
        "source": SOURCE_LABEL,
        "input": "typed",
    }
    if stamp is not None:
        item.update(stamp(PK, sk))
    table.put_item(Item=item)
    if verdict == VERDICT_CLEAN:
        return ACK_CLEAN
    if HOLD_OFF_RECORD in kinds:
        return ACK_OFF_RECORD
    if HOLD_FILTER_UNAVAILABLE in kinds:
        return ACK_UNAVAILABLE
    return ACK_HELD


# ── serving (read-only; /api/tuesday_question) ───────────────────────────────────────────────────────────────────


def _week_view(q: Dict[str, Any], replies: List[Dict[str, Any]], *, vocabulary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from common.pacific_time import day_in_words, pacific_date_of

    day = _day_of_sk(q["sk"])
    out: Dict[str, Any] = {"asked_on": day, "asked_on_text": day_in_words(day), "question": q.get("question"), "answer": None}
    ordered = sorted(replies, key=lambda r: str(r.get("received_at") or ""))
    # Any hold withholds the whole week, and the serve path screens again (the vocabulary can have grown since).
    clean = bool(ordered) and all(
        r.get("verdict") == VERDICT_CLEAN and screen(str(r.get("text") or ""), vocabulary=vocabulary)[0] == VERDICT_CLEAN for r in ordered
    )
    if clean and screen(str(q.get("question") or ""), vocabulary=vocabulary)[0] == VERDICT_CLEAN:
        first = str(ordered[0].get("received_at") or "")
        out["answer"] = {
            "text": "\n\n".join(str(r.get("text") or "") for r in ordered),
            "received_at": first,
            "date": pacific_date_of(first),
            "messages": len(ordered),
        }
        out["state"] = STATE_ANSWERED
        out["sentence"] = None
    else:
        out["state"] = STATE_NO_ANSWER
        out["sentence"] = SILENCE_SENTENCE
    return out


def public_view(rows: List[Dict[str, Any]], *, vocabulary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """``{state, latest, latest_answered, sentence}`` from the partition's newest rows. ``latest`` is the newest SENT
    question (answered or not); ``latest_answered`` is the newest week with a served answer (may be ``latest``)."""
    sent = [r for r in rows if str(r.get("sk", "")).endswith("#Q") and r.get("status") == STATUS_SENT]
    sent.sort(key=lambda r: str(r.get("sk")), reverse=True)
    if not sent:
        return {"state": STATE_NOT_ASKED, "latest": None, "latest_answered": None, "sentence": NOT_ASKED_SENTENCE}
    by_day: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        if "#R#" in str(r.get("sk", "")):
            by_day.setdefault(_day_of_sk(r["sk"]), []).append(r)
    weeks = [_week_view(q, by_day.get(_day_of_sk(q["sk"]), []), vocabulary=vocabulary) for q in sent[:RECENT_QUESTIONS]]
    latest = weeks[0]
    answered = next((w for w in weeks if w["state"] == STATE_ANSWERED), None)
    return {"state": latest["state"], "latest": latest, "latest_answered": answered, "sentence": latest["sentence"]}


def read_public(table: Any) -> Dict[str, Any]:
    """The served payload, or ``{state: read_failed}`` — a failed read is never shown as silence."""
    try:
        rows = recent_questions(table)
    except Exception:  # noqa: BLE001
        return {"state": STATE_READ_FAILED, "latest": None, "latest_answered": None, "sentence": None}
    return public_view(rows)
