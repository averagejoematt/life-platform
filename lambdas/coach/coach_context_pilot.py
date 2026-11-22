"""coach/coach_context_pilot.py — the coach's context, in the owner's priority order (#6158, ruling 2026-11-22 §1).

THE SWITCH. `LIVE` below, committed False. While it is False nothing here runs on a live path:
the Telegram worker and the coach session packet call `for_turn` / `packet_context`, which return their
inputs untouched. Turning it on is a one-line merge plus a deploy of the two consumers (the
`telegram-coach-worker` function and the MCP server); rollback is the same line set back to False. The
private evaluation harness turns it on for one process only (`LIVE = True` in-process, or call
`build_turn_context` directly — it ignores the switch and writes nothing).

WHY. Two blind runs (2026-11-21) showed prompt wording does not fix the coach: it misstates his record
because of the context it is handed. A thread that repeated one theme seven times outweighed a labelled
block naming his recorded priority, "this chat cannot save" was read as "I have no memory", and the lead
had no recommendation of its own on record. So this module changes CONTEXT, not the model and not the
conversation rules, and it does not carry the failed conversation-layer prompt.

THE ORDER (the owner's, verbatim in intent):
  1. his currently recorded priorities — his DECISION# rows, newest first, plus what he told his AI in
     conversation (platform memory, with its "(shared in confidence)" marker kept), placed AHEAD of the
     coach's own notes and chat history;
  2. today's planned training session when relevant (the lead and the Performance seat) — read through
     `training.session_sequence`, the program's own derivation; nothing in `lambdas/training/` changes;
  3. the recommendations on record (`coach.recommendation_record`) with HIS recorded answers only;
  4. the coach's compressed notes, exactly as rendered (never edited — round 3 of the blind evaluation
     showed editing them lost dates and order), and the chat THREAD with the coach's own repeated themes
     capped: the newest MAX_PER_THEME replies carrying a theme are kept, older repeats left out (his own
     words are never removed);
  5. the corrections he has made (already in the memory block since #6153 — kept, after the notes);
  6. what the coach can and cannot remember, worded so it cannot be read as "I have no memory", and that
     what he DID comes only from his recorded answer, never from his data.

DATED THREAD (#6149, round 4 of the blind evaluation, pass-bar item 6). The notes are dated but the stored chat
thread reached the prompt undated, and it is often NEWER than the newest note — so asked "what did you last
tell me to do", the coach cited an old note over a newer chat message. Under the switch each stored turn
carries its row's own `created_at` (`thread_turns`), the thread is put in time order (`order_thread`: the
CHAT# sort key's suffix is random within a day, so key order is not send order), and `thread_dates_section`
names the Pacific day of every message the model will see plus where the newest one falls against the newest
note. A turn with no stored timestamp is called undated, never given a guessed day. Nothing here reads whether
he followed anything; section 6's rule stands.

CYCLE CALENDAR (#6149, pass-bar item 5). The domain pack's "Experiment: Day N of cycle C" line was quoted in a
reflective reply as "N days of tracking". Under the switch `frame_label` re-labels that one line for what it
is — a calendar position, not a measurement and not a tracking length — and says when it is worth naming.

THE LEAD. Eli Marsh coordinates: he sees every coach's open recommendations and is the one who asks
about a due follow-up — ONE recommendation, once, inside a reply or a scheduled message that already
exists. Specialists keep their voice and see their own. No orchestration, no new model call. This module
shows no graded coach record; if it ever does, it reads it through `coach_record` (#6172), never a count
of its own.

FOLLOW-UP, ASKED ONCE. When the lead's context carries a due follow-up, `record_extra` names it, and the
worker stores that id on the coach's own CHAT# reply row (`follow_up_rec_id`) — the write it already
makes. A follow-up whose id is on any lead reply since its agreed date is not offered again. That marker
records that the coach RAISED it; it is never an answer. Only the owner's tool records an answer.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any, Optional

from coach import recommendation_record as rr

try:  # the worker's own logger: a handler of its own at INFO, so these lines reach CloudWatch (#3283 / #5106)
    from common.platform_logger import get_logger

    logger: logging.Logger = get_logger("telegram-worker")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("telegram-worker")
    logger.setLevel(logging.INFO)

#: THE SWITCH (#6158 Part B). False = production behaves exactly as before this module existed.
LIVE = False

USER_ID = "matthew"
PRIORITY_LOOKBACK_DAYS = 90
PRIORITY_MAX = 5
OPEN_RECS_MAX_LEAD = 5
OPEN_RECS_MAX_SPECIALIST = 3
CLOSED_RECS_MAX = 2
CLOSED_LOOKBACK_DAYS = 30
MAX_PER_THEME = 2
LINE_CAP = 280
SESSION_PERSONAS = frozenset({rr.LEAD_COACH_ID, "physical_coach"})
FOLLOW_UP_FIELD = "follow_up_rec_id"
OMITTED_REPLY = "(an earlier reply of yours, left out here because a later message of yours already makes the same point)"

PRIORITIES_HEADER = (
    "1. WHAT MATTHEW HAS DECIDED — his recorded decisions, newest first. These are HIS priorities and they come "
    "before anything in your own notes or in this chat's history: where they disagree, his recorded decision wins, "
    "and a newer decision replaces an older one on the same subject."
)
SESSION_HEADER = "2. TODAY'S PLANNED TRAINING SESSION"
RECS_HEADER = (
    "3. RECOMMENDATIONS ON RECORD and what he answered. Only his explicit answers count: 'not recorded' means he "
    "has not answered, and you never read an answer into his training, food or wearable data."
)
NOTES_HEADER = (
    "4. YOUR OWN NOTES FROM EARLIER CHATS, oldest first and each with its date — the NEWEST note is the last one. "
    "When you say what you told him, name the date of the note you are citing:"
)
LEAD_LINE = (
    "You are the lead coach: you hold the thread across his coaches so he never has to repeat himself. Bring a "
    "specialist in by name only when their lane genuinely decides the answer."
)
CAPABILITY = (
    "6. WHAT YOU CAN AND CANNOT REMEMBER. You do have a memory of him: this chat's recent messages, your notes "
    "from earlier chats, his recorded decisions, the recommendations on record with his answers, and his "
    "corrections, all above. When he asks what you told him or what he decided, answer from them and name the "
    "day. You do not have word-for-word transcripts of older chats, and you cannot save anything new from this "
    "chat — that is all the WRITES rule below means. Never tell him you have no memory or that this chat does not "
    "keep earlier sessions; if a specific thing is not in your notes, say that thing is not in your notes. "
    "Never state or imply that he did or did not do something because of his sensor, nutrition or training data "
    "(an average, a count, a logged workout or meal): only his own recorded answer says what he did. If he has not "
    "told you, say you do not know."
)

STAMP_FIELD = "sent_at"
THREAD_DATES_HEADER = (
    "4b. THE DAY EACH MESSAGE OF THIS CHAT WAS SENT (Pacific), in the order the conversation after this prompt shows "
    "them, oldest first — the last line is the newest message:"
)
UNDATED = "undated (no timestamp stored)"
FRAME_LABEL = (
    "Cycle calendar (a position in the calendar, not a measurement of him and not how long he has been tracking; "
    "name it only if he asks where he is in the cycle or the program): Day {day}{cycle} (week {week})."
)
_FRAME = re.compile(r"^Experiment: Day (\d+)((?: of cycle \d+)?) \(week (\d+)\)\.$", re.M)
_NOTE_DAY = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\]", re.M)

_STOP = frozenset(
    "that this with have just your youre what from been they them then than when were will would could should about into "
    "over more less still only also some like really think know going make good today yesterday week weeks last next days "
    "time here there their which while because after before those these much very even back want need feel sure right "
    "well okay yeah matthew said told doing done does didnt dont thats being every other thing things first same each "
    "around through where something anything nothing maybe might pretty though enough again yours youve youll "
    "cant wont isnt wasnt lets shes theyre".split()
)
_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_TOKEN = re.compile(r"[a-z][a-z']{3,}|\d+(?:\.\d+)?")


def _clip(text: Any, n: int = LINE_CAP) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _today() -> str:
    from common.pacific_time import pacific_today

    return pacific_today()


def _in_words(day: str) -> str:
    try:
        from common.pacific_time import day_in_words

        return day_in_words(day)
    except Exception:  # noqa: BLE001 — a date label is never load-bearing
        return day


# ── 4. de-duplication: one theme may not dominate ───────────────────────────────────────────


def theme_terms(text: str) -> set[str]:
    """Salient words and numbers of one unit — dates, years, single digits and filler words removed."""
    out = set()
    for tok in _TOKEN.findall(_DATE.sub(" ", str(text or "").lower())):
        tok = tok.replace("'", "")
        if tok in _STOP or (tok[0].isdigit() and (len(tok.split(".")[0]) < 2 or re.fullmatch(r"(19|20)\d\d", tok))):
            continue
        out.add(tok)
    return out


def select_units(units: list[str], cap: int = MAX_PER_THEME) -> list[bool]:
    """Which units to keep, in the order given (newest first). A DOMINANT term is one carried by more
    than `cap` units; a unit is dropped when a dominant term it carries is already in `cap` kept units.
    Deterministic, and it never drops a unit that carries no dominant term."""
    terms = [theme_terms(u) for u in units]
    counts = Counter(t for ts in terms for t in ts)
    dominant = {t for t, c in counts.items() if c > cap}
    kept_per: Counter = Counter()
    keep = []
    for ts in terms:
        dom = ts & dominant
        if any(kept_per[t] >= cap for t in dom):
            keep.append(False)
            continue
        keep.append(True)
        kept_per.update(dom)
    return keep


def _split_memory_core(memory: str) -> tuple[str, str]:
    """(notes, corrections): the corrections block (#6153) is kept as given and stays after the notes."""
    from coach.coach_corrections import CHAT_CORRECTIONS_HEADER

    idx = (memory or "").find(CHAT_CORRECTIONS_HEADER)
    if idx < 0:
        return memory or "", ""
    return memory[:idx].rstrip(), memory[idx:].strip()


def dedupe_thread(thread: list[dict], cap: int = MAX_PER_THEME) -> tuple[list[dict], dict[str, int]]:
    """Cap the coach's own repeated themes in the CHAT THREAD only.

    Round 3 of the blind evaluation (2026-11-22) showed that editing the compressed notes was harmful: splitting
    them into sentences stripped date labels, cut a sentence at "vs.", emptied one coach's notes and halved the
    time-gap line, and the coach then quoted its OLDEST surviving note as its latest. So the notes are never
    edited here; they reach the prompt exactly as `_memory_block` rendered them, every date label intact.

    In the thread the units are whole coach replies, newest first: the NEWEST `cap` replies carrying a dominant
    theme are kept and older repeats are replaced by a placeholder (so the turn order he saw is kept). Matthew's
    messages are never touched, and the newest coach reply is always kept."""
    from coach import coach_chat

    thread = list(thread or [])
    coach_idx = [i for i in range(len(thread) - 1, -1, -1) if thread[i].get("role") == coach_chat.ROLE_COACH and thread[i].get("text")]
    keep = select_units([thread[i]["text"] for i in coach_idx], cap)
    if keep:
        keep[0] = True  # the newest reply is the coach's latest word — never left out
    dropped = {coach_idx[k] for k in range(len(coach_idx)) if not keep[k]}
    new_thread = [dict(t, text=OMITTED_REPLY) if i in dropped else t for i, t in enumerate(thread)]
    return new_thread, {"replies_left_out": len(dropped)}


# ── 4b. the thread, dated (#6149) ───────────────────────────────────────────────────────────


def thread_turns(rows: list, *, live: Optional[bool] = None) -> list[dict]:
    """The worker's thread projection. Switch off: exactly the `{role, text}` it always built. On: each turn
    also carries its stored row's `created_at` as STAMP_FIELD (None when the row has none)."""
    if not (LIVE if live is None else live):
        return [{"role": i.get("role"), "text": i.get("text")} for i in rows]
    return [{"role": i.get("role"), "text": i.get("text"), STAMP_FIELD: i.get("created_at")} for i in rows]


def _sent(turn: dict):
    from common.pacific_time import parse_iso_utc

    return parse_iso_utc(turn.get(STAMP_FIELD))


def _sent_day(turn: dict) -> Optional[str]:
    from common.pacific_time import pacific_date_of

    stamp = turn.get(STAMP_FIELD)
    return pacific_date_of(str(stamp)) if stamp else None


def order_thread(thread: list) -> list:
    """Send order, by each turn's stored timestamp (a stable sort). The CHAT# key is `CHAT#<day>#<random>`, so
    within a day key order is not send order. If ANY turn is undated the order is left as stored: there is
    no honest place to put an undated turn."""
    thread = list(thread or [])
    if not thread or any(_sent(t) is None for t in thread):
        return thread
    return sorted(thread, key=_sent)


def _visible(thread: list) -> list:
    """The turns `coach_chat.format_thread` actually sends: the last MAX_THREAD_TURNS with text, minus any
    leading coach turns (a prompt must open on his message)."""
    from coach import coach_chat

    turns = [t for t in thread if (t or {}).get("text")][-coach_chat.MAX_THREAD_TURNS :]
    while turns and turns[0].get("role") != coach_chat.ROLE_MATTHEW:
        turns.pop(0)
    return turns


def _day_label(day: Optional[str]) -> str:
    return f"{_in_words(day)} ({day})" if day else UNDATED


def thread_dates_section(thread: list, notes: str) -> str:
    """Every visible message's Pacific send day, oldest first, then where the coach's newest message falls
    against its newest dated note — so "the newest thing you said to him" is decidable from dates alone."""
    from coach import coach_chat

    turns = _visible(thread)
    if not turns:
        return ""
    lines = [THREAD_DATES_HEADER]
    for t in turns:
        who = "him" if t.get("role") == coach_chat.ROLE_MATTHEW else "you"
        left_out = " (an earlier reply of yours, left out)" if t.get("text") == OMITTED_REPLY else ""
        lines.append(f"- {who}{left_out}: {_day_label(_sent_day(t))}")
    note_days = _NOTE_DAY.findall(notes or "")
    newest_note = max(note_days) if note_days else None
    mine = [d for d in (_sent_day(t) for t in turns if t.get("role") == coach_chat.ROLE_COACH) if d]
    newest_mine = max(mine) if mine else None
    if newest_mine and newest_note:
        if newest_mine > newest_note:
            rel = "LATER than your newest note"
        elif newest_mine == newest_note:
            rel = "the SAME day as your newest note"
        else:
            rel = "EARLIER than your newest note"
        lines.append(f"Your newest message in this chat was sent {_day_label(newest_mine)}: {rel}, dated {_day_label(newest_note)}.")
    elif newest_mine:
        lines.append(f"Your newest message in this chat was sent {_day_label(newest_mine)}. None of your notes is dated.")
    elif newest_note:
        lines.append(f"None of your messages in this chat is dated. Your newest note is dated {_day_label(newest_note)}.")
    undated = sum(1 for t in turns if not _sent_day(t))
    if undated:
        lines.append(f"{undated} of these messages are undated: when they were sent, and whether before or after a note, is not known.")
    return "\n".join(lines)


def frame_label(domain: str, *, live: Optional[bool] = None) -> str:
    """The domain pack with its cycle-day line labelled for what it is. Switch off: `domain` untouched."""
    if not (LIVE if live is None else live) or not domain:
        return domain
    return _FRAME.sub(lambda m: FRAME_LABEL.format(day=m.group(1), cycle=m.group(2), week=m.group(3)), domain)


# ── 1. priorities ───────────────────────────────────────────────────────────────────────────


def recorded_decisions(table, day: str, user_id: str = USER_ID) -> list[dict[str, Any]]:
    """His DECISION# rows inside the lookback, newest first, tombstones and other cycles out."""
    from boto3.dynamodb.conditions import Key
    from experiment.phase_filter import with_phase_filter

    kwargs = with_phase_filter(
        {
            "KeyConditionExpression": Key("pk").eq(f"USER#{user_id}#SOURCE#decisions") & Key("sk").begins_with("DECISION#"),
            "ScanIndexForward": False,
            "Limit": 60,
        }
    )
    floor = rr.shift_day(day, -PRIORITY_LOOKBACK_DAYS)
    rows = [r for r in table.query(**kwargs).get("Items") or [] if not r.get("tombstone")]
    rows = [r for r in rows if floor <= str(r.get("date") or "") <= day and str(r.get("decision") or "").strip()]
    return [
        {"date": r.get("date"), "decision": _clip(r.get("decision"), 300), "note": _clip(r.get("note"), 200) if r.get("note") else None}
        for r in rows[:PRIORITY_MAX]
    ]


def priorities_section(table, persona_id: str, day: str) -> str:
    lines = []
    for d in recorded_decisions(table, day):
        words = f' — in his words: "{d["note"]}"' if d.get("note") else ""
        lines.append(f"- [{_in_words(d['date'])}] {d['decision']}{words}")
    block = PRIORITIES_HEADER + "\n" + ("\n".join(lines) if lines else "- none recorded in the last 90 days")
    from ai.platform_memory import platform_memory_block
    from common.pacific_time import parse_day_key

    told = platform_memory_block(coach_id=persona_id, table=table, today=parse_day_key(day))
    return f"{block}\n{told}" if told else block


# ── 2. today's planned session ──────────────────────────────────────────────────────────────


def planned_session(day: str) -> dict[str, Any]:
    """The program's next undone session as of `day` — `training.session_sequence`, read only."""
    from training import deload_word, program_structure, session_sequence

    if not getattr(program_structure, "ACTIVE", False):
        return {"state": "absent", "why": "no active training program"}
    workouts = session_sequence.load_block_workouts(day)
    nxt = session_sequence.next_session(day, workouts, deload_word.load_records_failsoft())
    if not nxt:
        return {"state": "absent", "why": f"before the program's first session ({session_sequence.block_start()})"}
    if not nxt.get("label"):
        return {"state": "read_failed", "why": "the record of lifted sessions could not be read"}
    return {"state": "measured", "label": nxt["label"], "session_role": nxt.get("session_role"), "deload": bool(nxt.get("deload"))}


def session_section(persona_id: str, day: str) -> str:
    if persona_id not in SESSION_PERSONAS:
        return ""
    try:
        s = planned_session(day)
    except Exception as e:  # noqa: BLE001 — named in the prompt, never a guessed session
        logger.warning("[context_pilot] planned session unreadable: %s", type(e).__name__)
        s = {"state": "read_failed", "why": "the program's record could not be read"}
    if s["state"] == "measured":
        return f"{SESSION_HEADER} (the program's next undone session as of this morning): {s['label']}."
    return f"{SESSION_HEADER}: not available — {s['why']}. If he asks, say so; never guess the session."


# ── 3. recommendations + the one due follow-up ──────────────────────────────────────────────


def _rec_line(v: dict[str, Any]) -> str:
    said = f', in his words: "{_clip(v["response_words"], 160)}"' if v.get("response_words") else ""
    parts = [f"his answer: {v['response_label']}{said}"]
    parts.append(f"follow-up agreed for {_in_words(v['follow_up_on'])}" if v.get("follow_up_on") else "no follow-up agreed")
    if v.get("outcome"):
        parts.append(f"outcome he recorded: {_clip(v['outcome'].get('outcome_notes'), 160)}")
    if v.get("corrections"):
        parts.append(f"he has corrected this advice {len(v['corrections'])} time(s) since")
    return f'- [{_in_words(v["date"])} · {v["coach_id"]} · {v["channel"]} · {v["rec_id"]}] "{_clip(v["text"], 240)}" — ' + "; ".join(parts)


def visible_recommendations(views: list[dict[str, Any]], persona_id: str, day: str) -> tuple[list, list]:
    """(open, recently closed) for this seat: the lead sees every coach's, a specialist its own."""
    lead = persona_id == rr.LEAD_COACH_ID
    mine = views if lead else [v for v in views if v.get("coach_id") == persona_id]
    open_ = [v for v in mine if not rr.is_closed(v)][: OPEN_RECS_MAX_LEAD if lead else OPEN_RECS_MAX_SPECIALIST]
    floor = rr.shift_day(day, -CLOSED_LOOKBACK_DAYS)
    closed = [v for v in mine if rr.is_closed(v) and str(v.get("date") or "") >= floor][:CLOSED_RECS_MAX]
    return open_, closed


def already_raised(table, rec_id: str, since_day: str) -> bool:
    """True when a lead reply since the agreed day already carries this follow-up (asked once)."""
    from boto3.dynamodb.conditions import Key

    from coach import coach_chat

    resp = table.query(
        KeyConditionExpression=Key("pk").eq(coach_chat.chat_pk(rr.LEAD_COACH_ID))
        & Key("sk").between(f"{coach_chat.CHAT_SK_PREFIX}{since_day}", f"{coach_chat.CHAT_SK_PREFIX}9999-12-31~"),
        ScanIndexForward=False,
        Limit=200,
    )
    return any(r.get(FOLLOW_UP_FIELD) == rec_id for r in resp.get("Items") or [])


def follow_up_to_raise(table, views: list[dict[str, Any]], persona_id: str, day: str) -> Optional[dict[str, Any]]:
    """The ONE due follow-up the lead raises now, or None (specialists never raise one)."""
    if persona_id != rr.LEAD_COACH_ID:
        return None
    for v in rr.due_follow_ups(views, day):
        if not already_raised(table, v["rec_id"], str(v["follow_up_on"])):
            return v
    return None


def recommendations_section(views: list[dict[str, Any]], persona_id: str, day: str, follow_up: Optional[dict[str, Any]]) -> str:
    open_, closed = visible_recommendations(views, persona_id, day)
    if not open_ and not closed and not follow_up:
        return f"{RECS_HEADER}\n- none on record"
    lines = [RECS_HEADER] + [_rec_line(v) for v in open_]
    if closed:
        lines.append("Recently closed:")
        lines += [_rec_line(v) for v in closed]
    if follow_up:
        lines.append(
            f"FOLLOW-UP DUE: he agreed to check back on {_in_words(follow_up['follow_up_on'])} about "
            f'"{_clip(follow_up["text"], 200)}" ({follow_up["rec_id"]}). Ask about this ONE recommendation, once, in one '
            "short line, after you have answered what he actually said. No list, no form, no other recommendation."
        )
    return "\n".join(lines)


# ── assembly ───────────────────────────────────────────────────────────────────────────────


def build_turn_context(table, persona_id: str, day: str, *, memory: str = "", thread: Optional[list] = None) -> dict[str, Any]:
    """The pilot context for one coach on one day. READS ONLY — it sends nothing and writes nothing,
    ignores the switch, and is what the private harness calls (with the worker's `_assemble` output).

    Returns {memory, thread, record_extra, follow_up, sections, dedupe}: `memory` replaces the worker's
    memory block, `thread` its stored thread, and `record_extra` rides on the reply row the worker stores."""
    views = rr.fold(rr.read_rows(table, USER_ID))
    follow_up = follow_up_to_raise(table, views, persona_id, day)
    notes, corrections = _split_memory_core(memory)
    new_thread, removed = dedupe_thread(order_thread(thread or []))
    sections = {
        "lead": LEAD_LINE if persona_id == rr.LEAD_COACH_ID else "",
        "priorities": priorities_section(table, persona_id, day),
        "planned_session": session_section(persona_id, day),
        "recommendations": recommendations_section(views, persona_id, day, follow_up),
        "notes": f"{NOTES_HEADER}\n{notes}" if notes else "",
        "thread_dates": thread_dates_section(new_thread, notes),
        "corrections": corrections,
        "capability": CAPABILITY,
    }
    return {
        "memory": "\n\n".join(s for s in sections.values() if s),
        "thread": new_thread,
        "record_extra": {FOLLOW_UP_FIELD: follow_up["rec_id"]} if follow_up else {},
        "follow_up": follow_up,
        "sections": sections,
        "dedupe": removed,
    }


def for_turn(table, persona_id: str, memory: str, thread: list, *, live: Optional[bool] = None, day: Optional[str] = None):
    """The worker's seam: (memory, thread, record_extra). Switch off -> the inputs, untouched.
    Fail-soft: any error -> the inputs, untouched (a context read can never cost him a reply)."""
    if not (LIVE if live is None else live):
        return memory, thread, {}
    try:
        table = table() if callable(table) else table  # the worker passes its lazy getter: no client is built while dark
        ctx = build_turn_context(table, persona_id, day or _today(), memory=memory, thread=thread)
        return ctx["memory"], ctx["thread"], ctx["record_extra"]
    except Exception as e:  # noqa: BLE001
        logger.warning("[context_pilot] context unavailable for %s, production context used: %s", persona_id, type(e).__name__)
        return memory, thread, {}


PACKET_HOW_TO_USE = (
    "Read this before the training fields. `priorities` are his recorded decisions, newest first — they outrank anything "
    "else here and a newer one replaces an older one on the same subject; `told_in_chat` is what he told his AI (lines marked "
    "(shared in confidence) shape your read but are not restated). The planned session is `fields.block_position`. "
    "`recommendations` are on record with HIS answers only ('not recorded' = not answered; never infer one from data). "
    "If `follow_up_due` is set, ask about that ONE recommendation once, at the end, and record his answer with "
    "manage_coach_recommendation (action respond / outcome / follow_up). Record a new material recommendation you make with "
    "action record. Unlike the Telegram chat, this chat can save."
)


def packet_context(table, day: str, *, live: Optional[bool] = None) -> Optional[dict[str, Any]]:
    """The coach session packet's `coaching_context` (lead's view), or None while the switch is off."""
    if not (LIVE if live is None else live):
        return None
    try:
        from ai.platform_memory import platform_memory_block
        from common.pacific_time import parse_day_key

        views = rr.fold(rr.read_rows(table, USER_ID))
        open_, closed = visible_recommendations(views, rr.LEAD_COACH_ID, day)
        due = rr.due_follow_ups(views, day)
        slim = ("rec_id", "coach_id", "channel", "date", "text", "response", "response_label", "response_words", "follow_up_on", "outcome")
        return {
            "state": "measured",
            "lead": rr.LEAD_COACH_ID,
            "priorities": recorded_decisions(table, day),
            "told_in_chat": platform_memory_block(coach_id=None, table=table, today=parse_day_key(day)) or None,
            "recommendations": [{k: v.get(k) for k in slim} for v in open_],
            "recently_closed": [{k: v.get(k) for k in slim} for v in closed],
            "follow_up_due": {k: due[0].get(k) for k in slim} if due else None,
            "how_to_use": PACKET_HOW_TO_USE,
        }
    except Exception as e:  # noqa: BLE001 — named, never an empty context dressed as a real one
        logger.warning("[context_pilot] packet context unavailable: %s", type(e).__name__)
        return {"state": "read_failed", "error": type(e).__name__}
