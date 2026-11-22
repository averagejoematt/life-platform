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
  4. the chat history and the coach's compressed notes with redundant repeats removed — a theme the
     coach has already made in MAX_PER_THEME newer places is not carried again (his own words are
     never removed);
  5. the corrections he has made (already in the memory block since #6153 — kept, after the notes);
  6. what the coach can and cannot remember, worded so it cannot be read as "I have no memory".

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
NOTES_HEADER = "4. YOUR OWN NOTES AND THIS CHAT (repeats already left out):"
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
    "keep earlier sessions; if a specific thing is not in your notes, say that thing is not in your notes."
)

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
_SEGMENT_SPLIT = re.compile(r"((?<=[.!?])\s+|\s+·\s+)")


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
    """(notes, corrections): the corrections block (#6153) is never de-duplicated and stays after the notes."""
    from coach.coach_corrections import CHAT_CORRECTIONS_HEADER

    idx = (memory or "").find(CHAT_CORRECTIONS_HEADER)
    if idx < 0:
        return memory or "", ""
    return memory[:idx].rstrip(), memory[idx:].strip()


def dedupe(notes: str, thread: list[dict], cap: int = MAX_PER_THEME) -> tuple[str, list[dict], dict[str, int]]:
    """Drop the coach's own repeats across the chat thread and its compressed notes.

    Units, newest first: the coach's replies in the thread (newest to oldest), then the note segments
    (last line to first — the summaries render oldest first). Matthew's messages are never units and
    never dropped. A dropped reply is replaced by a short placeholder so the turn order he sees is kept."""
    from coach import coach_chat

    thread = list(thread or [])
    coach_idx = [i for i in range(len(thread) - 1, -1, -1) if thread[i].get("role") == coach_chat.ROLE_COACH and thread[i].get("text")]
    lines = (notes or "").split("\n")
    seg_index: list[tuple[int, int]] = []
    parts_by_line: dict[int, list[str]] = {}
    for li in range(len(lines) - 1, -1, -1):
        line = lines[li]
        if not line.strip() or line.rstrip().endswith(":"):
            continue
        parts = _SEGMENT_SPLIT.split(line)  # one capture group: [segment, separator, segment, ...]
        parts_by_line[li] = parts
        seg_index += [(li, pi) for pi in reversed(range(0, len(parts), 2)) if parts[pi].strip()]
    units = [thread[i]["text"] for i in coach_idx] + [parts_by_line[li][pi] for li, pi in seg_index]
    keep = select_units(units, cap)
    dropped_turns = {coach_idx[k] for k in range(len(coach_idx)) if not keep[k]}
    dropped_segs = {seg_index[k - len(coach_idx)] for k in range(len(coach_idx), len(units)) if not keep[k]}
    new_thread = [dict(t, text=OMITTED_REPLY) if i in dropped_turns else t for i, t in enumerate(thread)]
    out_lines = []
    for li, line in enumerate(lines):
        if li not in parts_by_line:
            out_lines.append(line)
            continue
        parts = parts_by_line[li]
        kept = [parts[pi] for pi in range(0, len(parts), 2) if (li, pi) not in dropped_segs and parts[pi].strip()]
        if kept:
            out_lines.append(" ".join(kept))
    return "\n".join(out_lines).strip(), new_thread, {"replies_left_out": len(dropped_turns), "note_segments_left_out": len(dropped_segs)}


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
    notes, new_thread, removed = dedupe(notes, list(thread or []))
    sections = {
        "lead": LEAD_LINE if persona_id == rr.LEAD_COACH_ID else "",
        "priorities": priorities_section(table, persona_id, day),
        "planned_session": session_section(persona_id, day),
        "recommendations": recommendations_section(views, persona_id, day, follow_up),
        "notes": f"{NOTES_HEADER}\n{notes}" if notes else "",
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
