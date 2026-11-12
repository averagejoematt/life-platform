"""mcp/tools_advice_queue.py — `get_advice_link_queue`: the coaches' recent asks beside what Matthew recorded (owner 2026-11-12).

WHY. The coaches have made hundreds of asks (``COMMITMENT#`` rows) and there are no advice links, so every ask on the
CR2 record pages reads "not recorded". The one way a link is made is the owner tool ``log_advice_link``, and only with
Matthew's own words as evidence (#5612, ruling F: "Do not infer that I followed advice simply because my subsequent
behavior happened to align with it"). This tool is the READ that makes that ask possible: for the asks due in the last
N days it lays each one beside the words he has already recorded in that window, so he can say what he did.

WHAT IT RETURNS — three blocks, never mixed:
  ``asks``                 each ask: coach, the day it was asked, the ask text, the due day, the grader's status.
  ``his_words``            what HE recorded in the window: decisions, owner notes, answered check-ins. An ask lists the
                           ids of the entries that fall inside its own window — same window, never a link.
  ``context_not_evidence`` documented activity (Hevy workouts, MacroFactor days, Habitify completions), labelled as
                           context. Activity that matches an ask is NOT evidence that he acted on it, and nothing in
                           this block may be passed to ``log_advice_link`` as evidence.

WHAT IT NEVER DOES. It writes nothing (no put/update/delete; ``tests/test_advice_links_5612.py`` and
``tests/test_advice_queue.py`` hold that by AST), never touches the advice-link record family, never assigns or proposes a state,
and never reads a journal, State of Mind or video-diary source. Habitify rows go through
``common.activity_publication.public_habit_statuses`` (so the journal habits, owner-private and unclassified habits,
and every free-text field drop out), and a check-in whose driving source is private, unclassified, or a public
partition that carries a private sub-stream (``activity_publication.PRIVATE_SOURCE_FIELDS``: State of Mind rides
``apple_health``) is left out entirely.

ORDER. Most answerable first: an ask with more of his own recorded words inside its window (a check-in answer to the
same coach counts most, then a decision, then a note) leads; ties go to the most recently due (the freshest memory).
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from boto3.dynamodb.conditions import Key
from coach import coach_checkin as cc
from coach.persona_registry import OPERATIONAL_COACH_IDS, RETIRED_COACH_IDS, short_id_names
from common import activity_publication as AP
from common.pacific_time import pacific_today, parse_day_key
from content import owner_words

from mcp.config import USER_ID, USER_PREFIX, table as _table_ref
from mcp.core import _apply_phase_filter, decimal_to_float, query_source

DEFAULT_DAYS = 14
MAX_DAYS = 30
DEFAULT_MAX_ASKS = 15
MAX_ASKS = 40
#: How far before the window's first day an ask's own window may reach for his words (a 7-day ask due on day 1).
LOOKBACK_DAYS = 30
ASK_CHARS = 280
WORDS_CHARS = 400
MAX_DECISIONS = 25
MAX_NOTES = 15
MAX_CHECKINS = 20
MAX_HABITS_PER_DAY = 25
#: The whole answer stays under this many characters; context is trimmed first (oldest day out), then asks.
MAX_PAYLOAD_CHARS = 40000

#: Commitment partitions: every engine coach, plus the retired ones whose asks are still on the record.
COMMITMENT_COACH_IDS = list(OPERATIONAL_COACH_IDS) + [c for c in RETIRED_COACH_IDS if c not in OPERATIONAL_COACH_IDS]
_NAMES = short_id_names(include_retired=True)

#: Public partitions that carry a private sub-stream (State of Mind inside apple_health, the diary count inside
#: computed_metrics): a check-in driven by one of them could be about the private stream, so it is left out.
_MIXED_SOURCES = frozenset(AP.PRIVATE_SOURCE_FIELDS)

CONTEXT_LABEL = (
    "context, not evidence — documented activity in the window. Activity that happens to match an ask is NOT evidence "
    "that Matthew acted on it (#5612, ruling F); never pass anything here to log_advice_link as evidence."
)
HOW_TO_RECORD = (
    "Ask Matthew, one ask at a time, what he did with it, and record only what he says, in his words. An entry under "
    "same_window_ids shares the ask's dates; it is not a link and is not evidence on its own. To record his answer: "
    "log it with log_decision (his words) — or use a decision he already logged that answers it — then call "
    "log_advice_link with that decision_sk, ref_kind='commitment', ref_id=<ask_id>, coach_id=<coach_id>, the state "
    "he names, and his own words as evidence_text; that tool refuses an ask's "
    "state without them. If he does not say, record nothing: the ask stays unknown. Never pass the grader_status or "
    "anything under context_not_evidence as evidence."
)

ADVICE_QUEUE_DESCRIPTION = (
    "READ-ONLY. The coaches' asks due in the last N days (default 14), most answerable first, each beside what "
    "Matthew recorded in its window — decisions, owner notes, check-in answers — so he can say what he did with it. "
    "Also returns documented activity (Hevy, MacroFactor, Habitify) labelled CONTEXT, NOT EVIDENCE: a workout or a "
    "meal that matches an ask never shows he acted on it, and must never be passed to log_advice_link. Writes "
    "nothing and proposes no link. Journal, State of Mind and video-diary data are never read."
)
# A LITERAL dict: scripts/generate_mcp_tool_catalog.py reads it by ast.literal_eval.
ADVICE_QUEUE_INPUT = {
    "type": "object",
    "properties": {
        "days": {"type": "number", "description": "Asks due in the last N days (default 14, max 30)."},
        "coach_id": {"type": "string", "description": "Optional: one coach (e.g. 'sleep' or 'sleep_coach')."},
        "max_asks": {"type": "number", "description": "How many asks to return (default 15, max 40)."},
    },
    "required": [],
}


def _clip(value, n: int):
    s = str(value or "").strip()
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _int_arg(args: dict, key: str, default: int, hi: int) -> int:
    try:
        v = int(args.get(key, default))
    except (TypeError, ValueError):
        v = default
    return max(1, min(hi, v))


def _query_all(kwargs: dict) -> list:
    items: list = []
    while True:
        resp = _table_ref.query(**kwargs)
        items.extend(resp.get("Items", []))
        if not resp.get("LastEvaluatedKey"):
            return decimal_to_float(items)
        kwargs = {**kwargs, "ExclusiveStartKey": resp["LastEvaluatedKey"]}


# ── the reads (each fail-soft: one bad partition never hides the rest) ─────────────────────────────


def _asks(coach_ids: list, start: str, end: str) -> list:
    out = []
    for cid in coach_ids:
        try:
            rows = _query_all(
                _apply_phase_filter({"KeyConditionExpression": Key("pk").eq(f"COACH#{cid}") & Key("sk").begins_with("COMMITMENT#")})
            )
        except Exception:  # noqa: BLE001
            continue
        for r in rows:
            due = str(r.get("due_date") or "")
            if r.get("tombstone") or not (start <= due <= end):
                continue
            short = cid.removesuffix("_coach")
            out.append(
                {
                    "coach_id": cid,
                    "coach": _NAMES.get(short, short),
                    "ask_id": r.get("commitment_id") or str(r.get("sk", "")).removeprefix("COMMITMENT#"),
                    "asked_on": str(r.get("created_date") or str(r.get("created_at") or "")[:10]),
                    "due": due,
                    "ask": _clip(r.get("commitment_natural") or r.get("public_ask"), ASK_CHARS),
                    # The grader's metric check (commitment_grading), NOT his account of what he did.
                    "grader_status": r.get("status") or "pending",
                }
            )
    return out


def _decisions(start: str, end: str) -> list:
    try:
        rows = _query_all(
            _apply_phase_filter({"KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}decisions") & Key("sk").begins_with("DECISION#")})
        )
    except Exception:  # noqa: BLE001
        return []
    out = [
        {
            "id": r.get("sk"),
            "date": str(r.get("date") or ""),
            "decision": _clip(r.get("decision"), WORDS_CHARS),
            **({"outcome_notes": _clip(r.get("outcome_notes"), WORDS_CHARS)} if r.get("outcome_notes") else {}),
        }
        for r in rows
        if not r.get("tombstone") and start <= str(r.get("date") or "") <= end
    ]
    return sorted(out, key=lambda d: d["id"] or "", reverse=True)


def _owner_notes(start: str, end: str) -> tuple[list, int]:
    """His notes (chat + email inlets). Only clean, on-record entries carry their text; the rest are counted."""
    try:
        rows = _query_all({"KeyConditionExpression": Key("pk").eq(owner_words.PK) & Key("sk").between(f"WORDS#{start}", f"WORDS#{end}~")})
    except Exception:  # noqa: BLE001
        return [], 0
    shown, not_shown = [], 0
    for r in rows:
        if r.get("verdict") != owner_words.VERDICT_CLEAN or r.get("off_record"):
            not_shown += 1
            continue
        shown.append(
            {
                "id": r.get("sk"),
                "date": str(r.get("date") or ""),
                "text": _clip(r.get("text"), WORDS_CHARS),
                **({"prompt": _clip(r.get("prompt"), ASK_CHARS)} if r.get("prompt") else {}),
            }
        )
    return sorted(shown, key=lambda n: n["id"] or "", reverse=True), not_shown


def checkin_is_shareable(item: dict) -> bool:
    """False for a check-in whose driving source is private, unclassified, or a partition carrying a private stream."""
    src = cc.question_source(item)
    if not src:
        return True
    return src not in _MIXED_SOURCES and AP.source_is_public(src)


def _checkin_answers(coach_ids: list, start: str, end: str) -> list:
    out = []
    for cid in coach_ids:
        try:
            rows = _query_all(
                {"KeyConditionExpression": Key("pk").eq(cc.checkin_pk(cid)) & Key("sk").between(f"CHECKIN#{start}", f"CHECKIN#{end}~")}
            )
        except Exception:  # noqa: BLE001
            continue
        for r in rows:
            if r.get("status") != cc.STATUS_ANSWERED or not r.get("answer") or not checkin_is_shareable(r):
                continue
            out.append(
                {
                    "id": r.get("sk"),
                    "coach_id": cid,
                    "answered_on": str(r.get("answered_at") or "")[:10] or str(r.get("sk", ""))[8:18],
                    "question": _clip(r.get("question"), ASK_CHARS),
                    "answer": _clip(r.get("answer"), WORDS_CHARS),
                }
            )
    return sorted(out, key=lambda c: c["answered_on"], reverse=True)


def _context(start: str, end: str) -> dict:
    """Documented activity, per day. Structured fields only — no free text, no private habit, no private field."""
    hevy, mf, hab = [], [], []
    try:
        for w in query_source("hevy", start, end):
            if "#WORKOUT#" not in str(w.get("sk", "")):
                continue
            hevy.append(
                {
                    "date": str(w.get("date") or ""),
                    "title": _clip(w.get("title"), 80),
                    "minutes": round(float(w.get("duration_sec") or 0) / 60),
                    "sets": w.get("set_count"),
                    "volume_kg": round(float(w.get("total_volume_kg") or 0)),
                }
            )
    except Exception:  # noqa: BLE001
        pass
    try:
        for d in query_source("macrofactor", start, end):
            mf.append(
                {
                    "date": str(d.get("date") or ""),
                    "calories": round(float(d.get("total_calories_kcal") or 0)),
                    "protein_g": round(float(d.get("total_protein_g") or 0)),
                    "entries": d.get("entries_count"),
                }
            )
    except Exception:  # noqa: BLE001
        pass
    try:
        registry = _habit_registry()
        for d in query_source("habitify", start, end):
            pub = AP.public_habit_statuses(d.get("habit_statuses") or {}, registry)
            done = sorted(n for n, st in pub.items() if st.get("status") == "completed")
            hab.append({"date": str(d.get("date") or ""), "completed": done[:MAX_HABITS_PER_DAY], "public_habits_tracked": len(pub)})
    except Exception:  # noqa: BLE001
        pass
    by_date = lambda rows: sorted(rows, key=lambda r: r["date"], reverse=True)  # noqa: E731
    return {"label": CONTEXT_LABEL, "hevy": by_date(hevy), "macrofactor": by_date(mf), "habitify": by_date(hab)}


def _habit_registry() -> dict:
    try:
        item = _table_ref.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"}).get("Item") or {}
        reg = item.get("habit_registry") or {}
        return reg if isinstance(reg, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# ── shaping ────────────────────────────────────────────────────────────────────────────────────────


def rank_asks(asks: list, decisions: list, notes: list, checkins: list) -> list:
    """Attach each ask's same-window ids and its answerability, then order most answerable first."""
    for a in asks:
        lo, hi = a["asked_on"] or a["due"], a["due"]
        ids = {
            "checkin_answers": [c["id"] for c in checkins if c["coach_id"] == a["coach_id"] and lo <= c["answered_on"] <= hi],
            "decisions": [d["id"] for d in decisions if lo <= d["date"] <= hi],
            "owner_notes": [n["id"] for n in notes if lo <= n["date"] <= hi],
        }
        a["same_window_ids"] = {k: v for k, v in ids.items() if v}
        a["answerability"] = 3 * len(ids["checkin_answers"]) + 2 * len(ids["decisions"]) + len(ids["owner_notes"])
    return sorted(asks, key=lambda a: (-a["answerability"], _neg_day(a["due"]), a["coach_id"], a["ask_id"]))


def _neg_day(day: str) -> int:
    d = parse_day_key(day)
    return -d.toordinal() if d else 0


def _day(day: str) -> date:
    d = parse_day_key(day)
    if d is None:
        raise ValueError(f"not a day key: {day!r}")
    return d


def cap_payload(out: dict, limit: int = MAX_PAYLOAD_CHARS) -> dict:
    """Trim until the JSON fits: oldest context day first, then the least answerable asks."""
    ctx = out["context_not_evidence"]
    while len(json.dumps(out, default=str)) > limit:
        longest = max((k for k, v in ctx.items() if isinstance(v, list)), key=lambda k: len(ctx[k]))
        if ctx[longest]:
            ctx[longest].pop()
            out["truncated"]["context"] = True
        elif len(out["asks"]) > 1:
            out["asks"].pop()
            out["truncated"]["asks"] = True
        else:
            break
    out["asks_shown"] = len(out["asks"])
    return out


def tool_get_advice_link_queue(args):
    args = args or {}
    days = _int_arg(args, "days", DEFAULT_DAYS, MAX_DAYS)
    max_asks = _int_arg(args, "max_asks", DEFAULT_MAX_ASKS, MAX_ASKS)
    coach_ids = COMMITMENT_COACH_IDS
    if args.get("coach_id"):
        want = f"{cc.normalize_coach_id(str(args['coach_id']))}_coach"
        if want not in COMMITMENT_COACH_IDS:
            return {
                "error": f"unknown coach_id {args['coach_id']!r}; one of {', '.join(c.removesuffix('_coach') for c in COMMITMENT_COACH_IDS)}"
            }
        coach_ids = [want]

    today = pacific_today()
    start = (_day(today) - timedelta(days=days)).isoformat()
    asks = _asks(coach_ids, start, today)
    floor = (_day(start) - timedelta(days=LOOKBACK_DAYS)).isoformat()
    words_from = max(floor, min([a["asked_on"] for a in asks if a["asked_on"]] or [start]))

    decisions = _decisions(words_from, today)[:MAX_DECISIONS]
    notes, notes_not_shown = _owner_notes(words_from, today)
    notes = notes[:MAX_NOTES]
    checkins = _checkin_answers(coach_ids, words_from, today)[:MAX_CHECKINS]

    ranked = rank_asks(asks, decisions, notes, checkins)
    out = {
        "read_only": True,
        "window": {"days": days, "asks_due_from": start, "asks_due_to": today, "his_words_from": words_from},
        "how_to_record": HOW_TO_RECORD,
        "asks_total": len(ranked),
        "asks_shown": 0,
        "truncated": {"asks": len(ranked) > max_asks, "context": False},
        "asks": ranked[:max_asks],
        "his_words": {
            "decisions": decisions,
            "owner_notes": notes,
            "owner_notes_not_shown": notes_not_shown,
            "checkin_answers": checkins,
        },
        "context_not_evidence": _context(start, today),
        "never_read": "journal, State of Mind and video-diary sources are not read by this tool, in any form.",
    }
    return cap_payload(out)
