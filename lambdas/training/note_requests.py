"""note_requests.py — Hevy notes that ask the platform for something get a row, one reply and a status (#5573).

Hevy notes are where Matthew talks to the platform mid-session, and until this module they flowed one way: the
note layer (`training.training_notes`) classified "I may need research or youtube emailed me on form" as
`form_technique` and nothing ever answered it. The note layer now carries an `owner_request` signal (subtypes
`form_guidance` / `question` / `rule_request`, spec §5d); this module turns each one into a REQUEST ROW, replies
once where code can, and records how the request ended.

THE ROW (owner-only — `training_constraints` is TIER_OWNER_ONLY with no public projection, `privacy.field_tiers`)

    pk  USER#matthew#SOURCE#training_constraints        (literal below; the partition his own training words live in)
    sk  REQUEST#<YYYY-MM-DD>#<workout id>#<template id>#<occurrence>

    request_id, kind="owner_request", date (the workout's Pacific day), workout_id, workout_uid, exercise_name,
    template_id, occurrence, note_raw (VERBATIM), note_hash, subtype, detected_by (deterministic | haiku), matched,
    status (open | answered | declined), opened_at (UTC instant), and on resolution channel + answered_at / declined_at
    (UTC instants) + reply / decline_reason.

ONE REPLY, ONCE

  * The row is written ONCE, under `attribute_not_exists(sk)`. A re-extraction, a re-ingest or a second sweep over
    the same note never rewrites it, so an answered request is never re-opened and never answered twice.
  * `form_guidance` with a cue sheet for the movement (`training.form_cue_sheets`) is answered at raise time: the
    reply is the sheet plus the catalog facts for that movement (`config/movement_catalog.json`), labelled general
    guidance and not an assessment of his form, and the channel is the coach packet (`get_coach_session_packet`
    field `note_requests`, plus `get_capture_queues`) — both owner-only MCP reads.
  * `rule_request` is answered at raise time with a DRAFTED backlog-story suggestion: never filed, never applied.
  * `question` — and a `form_guidance` request on a movement with no cue sheet — stays OPEN. The packet lists it
    so the coach chat answers it in conversation, then records the answer with
    `get_exercise_notes action='answer_request'` (or `'decline_request'` with the reason). Code never writes an
    answer to a question: an answer about training evidence is the coach's, grounded (ADR-104/105).
  * Open more than OVERDUE_DAYS after the note was written ⇒ counted on the packet as overdue. A count, not an alarm.

WHAT IS NEVER READ: a Hevy note can say anything, so nothing here reads or joins journal, State of Mind or
video-diary data. The inputs are the note-layer item and the movement catalog only.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# literal (orphan-gate greppable); == training_context_registry.DISMISSAL_PK's partition
REQUEST_PK = "USER#matthew#SOURCE#training_constraints"
REQUEST_SK_PREFIX = "REQUEST#"
KIND = "owner_request"

SUBTYPES = ("form_guidance", "question", "rule_request")
STATUS_OPEN, STATUS_ANSWERED, STATUS_DECLINED = "open", "answered", "declined"
STATUSES = (STATUS_OPEN, STATUS_ANSWERED, STATUS_DECLINED)
CHANNEL_PACKET = "coach_packet"  # the reply rides get_coach_session_packet.note_requests + get_capture_queues
CHANNEL_CHAT = "coach_chat"  # answered in a coach conversation, recorded through get_exercise_notes
CHANNELS = (CHANNEL_PACKET, CHANNEL_CHAT)

# A request still open this many days after the note was written is counted as overdue on the packet (#5573).
OVERDUE_DAYS = 7
# Only notes this recent raise a row. A backfill over 2021 history must never mint a queue of five-year-old asks
# (the same posture as `training_notes._is_historical_pain_note`). Fourteen days covers a late re-extraction.
RAISE_LOOKBACK_DAYS = 14
# An LLM-only owner_request (the deterministic pass missed it) raises a row only at this confidence or above.
LLM_MIN_CONFIDENCE = 0.7
# Answered rows stay on the packet this long, so the reply is in front of the coach chat after it was written.
ANSWERED_VISIBLE_DAYS = 14

GENERAL_GUIDANCE_LABEL = "General guidance for this movement, not an assessment of your form."
NO_VIDEO_LINE = (
    "No video link: there is no owner-approved reference for this movement yet (the catalog's form_reference_urls is "
    "empty), and the platform never fetches or picks one itself."
)
RULE_DRAFT_LABEL = "Drafted backlog-story suggestion. Not filed and not applied; it becomes work only if you file it."
_REPLY_MAX_CHARS = 1600


def _now_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def request_sk(date: str, workout_id: str, template_id: str, occurrence: int = 0) -> str:
    return f"{REQUEST_SK_PREFIX}{date}#{workout_id}#{template_id}#{int(occurrence)}"


def request_id_of(sk: str) -> str:
    return str(sk or "")[len(REQUEST_SK_PREFIX) :] if str(sk or "").startswith(REQUEST_SK_PREFIX) else ""  # noqa: E203


def request_signal(item: dict) -> dict | None:
    """The note item's owner request that warrants a row, or None.

    The deterministic pass (`training_notes.owner_request_of`, re-run here on the stored verbatim note so the answer
    never depends on what a model wrote into `value`) always qualifies. A model-only `owner_request` signal qualifies
    when it names a valid subtype at LLM_MIN_CONFIDENCE or above — a request row is a promise to reply, so a guess
    does not raise one.
    """
    from training.training_notes import owner_request_of

    if not any(s.get("class") == KIND for s in item.get("signals") or []):
        return None
    det = owner_request_of(str(item.get("note_raw") or ""))
    if det:
        return {"subtype": det["subtype"], "matched": list(det["matched"]), "detected_by": "deterministic"}
    for s in item.get("signals") or []:
        if s.get("class") != KIND:
            continue
        val = s.get("value") if isinstance(s.get("value"), dict) else {}
        subtype = str(val.get("subtype") or "")
        try:
            conf = float(s.get("confidence") or 0)
        except (TypeError, ValueError):
            conf = 0.0
        if subtype in SUBTYPES and conf >= LLM_MIN_CONFIDENCE:
            return {"subtype": subtype, "matched": [], "detected_by": "haiku"}
    return None


def _days_between(earlier: str, later: str) -> int | None:
    """Whole calendar days from one day key to another, or None if either does not parse (`parse_day_key`, #3741)."""
    from common.pacific_time import parse_day_key

    a, b = parse_day_key(str(earlier or "")[:10]), parse_day_key(str(later or "")[:10])
    return (b - a).days if a is not None and b is not None else None


def is_recent(note_date: str, today: str) -> bool:
    """True when the note is within RAISE_LOOKBACK_DAYS of `today` (Pacific days). An unreadable date is NOT recent:
    unlike the pain floor, a missed request costs a reply, and a raised stale one costs a false promise."""
    d = _days_between(note_date, today)
    return d is not None and 0 <= d <= RAISE_LOOKBACK_DAYS


# ── the catalog side of a reply ─────────────────────────────────────────────────────────────
def catalog_entry(template_id: str, exercise_name: str, movements: dict | None = None) -> tuple[str | None, dict]:
    """(catalog key, entry) for the movement — by Hevy template id first, then by exact title; (None, {}) if absent."""
    if movements is None:
        from training.routine_generator import _load_json  # the generator's own catalog read (local, else S3)

        movements = (_load_json("movement_catalog.json") or {}).get("movements") or {}
    tid = str(template_id or "")
    for key, e in movements.items():
        if tid and str(e.get("hevy_template_id_hint") or "") == tid:
            return key, e
    name = " ".join(str(exercise_name or "").lower().split())
    for key, e in movements.items():
        if name and " ".join(str(e.get("title") or "").lower().split()) == name:
            return key, e
    return None, {}


def approved_reference_urls(entry: dict) -> list[str]:
    """The curated, owner-approved video links on a catalog entry (`form_reference_urls`), https only.

    An item is `{"url": "https://…", "approved_by_owner": "<YYYY-MM-DD>"}`; anything without the approval stamp, or
    not https, is ignored. Nothing is fetched, checked or added here — the list is the owner's, verbatim.
    """
    out = []
    for it in entry.get("form_reference_urls") or []:
        if not isinstance(it, dict):
            continue
        url = str(it.get("url") or "")
        if url.startswith("https://") and it.get("approved_by_owner"):
            out.append(url)
    return out


def form_guidance_reply(exercise_name: str, template_id: str, movements: dict | None = None) -> dict | None:
    """The cue-sheet reply for one movement, or None when no sheet exists (the request then stays open)."""
    from training import form_cue_sheets

    key, entry = catalog_entry(template_id, exercise_name, movements)
    title = entry.get("title") or exercise_name
    sheet = form_cue_sheets.sheet_for(title) or form_cue_sheets.sheet_for(exercise_name)
    if sheet is None:
        return None
    urls = approved_reference_urls(entry)
    rep = entry.get("default_rep_range") or {}
    facts = {
        "catalog_key": key,
        "title": title,
        "primary_muscle": entry.get("primary_muscle"),
        "equipment": entry.get("equipment"),
        "default_rep_range": [int(rep["start"]), int(rep["end"])] if rep.get("start") and rep.get("end") else None,
    }
    lines = [f"{title} — form cue sheet. {GENERAL_GUIDANCE_LABEL}", f"Setup: {sheet['setup']}"]
    lines += [f"Cue {i}: {c}" for i, c in enumerate(sheet["cues"], 1)]
    lines += [f"Common fault: {sheet['common_fault']}", f"What right feels like: {sheet['feels_right']}"]
    lines.append(("Owner-approved reference: " + ", ".join(urls)) if urls else NO_VIDEO_LINE)
    return {
        "kind": "form_cue_sheet",
        "label": GENERAL_GUIDANCE_LABEL,
        "text": "\n".join(lines)[:_REPLY_MAX_CHARS],
        "sheet": sheet,
        "catalog": facts,
        "reference_urls": urls,
    }


def rule_request_reply(row: dict) -> dict:
    """A drafted backlog-story suggestion, built from the note itself — never filed, never applied."""
    ex = row.get("exercise_name") or row.get("template_id") or "an exercise"
    title = f"Rule request from a Hevy note: {ex} ({row.get('date')})"
    body = "\n".join(
        [
            f"## Problem\nSource: owner, Hevy exercise note on {ex}, {row.get('date')} (workout {row.get('workout_id')}), verbatim: "
            f"\"{row.get('note_raw')}\"",
            "## Outcome\nThe rule the note asks for is stated, applied where the platform reads this movement, and tested.",
            "## Acceptance\n- [ ] The rule is written down in his words and confirmed by him before any code changes.",
        ]
    )
    return {
        "kind": "story_draft",
        "label": RULE_DRAFT_LABEL,
        "text": f"{RULE_DRAFT_LABEL}\nTitle: {title}\n\n{body}"[:_REPLY_MAX_CHARS],
        "draft": {"title": title, "body": body},
    }


# ── the row ─────────────────────────────────────────────────────────────────────────────────
def build_request_row(item: dict, req: dict, *, now_iso: str | None = None, movements: dict | None = None) -> dict:
    """One request row from a note-layer head item (`training_notes.build_note_item`) and its request signal.

    The reply, where code can write one, is composed HERE — at raise time — so the row is born answered with its
    channel and instant, and the conditional first write is the only write: answered at most once by construction.
    """
    from training.training_notes_keys import workout_id_from_uid

    now_iso = now_iso or _now_z()
    wid = workout_id_from_uid(item.get("workout_uid") or "")
    tid = str(item.get("exercise_template") or "")
    occ = int(item.get("occurrence") or 0)
    sk = request_sk(str(item.get("date") or ""), wid, tid, occ)
    row: dict[str, Any] = {
        "pk": REQUEST_PK,
        "sk": sk,
        "request_id": request_id_of(sk),
        "kind": KIND,
        "date": item.get("date"),
        "workout_id": wid,
        "workout_uid": item.get("workout_uid"),
        "exercise_name": item.get("exercise_name"),
        "template_id": tid,
        "occurrence": occ,
        "note_raw": item.get("note_raw"),  # VERBATIM — owner-only partition
        "note_hash": item.get("note_hash"),
        "subtype": req["subtype"],
        "detected_by": req["detected_by"],
        "matched": req["matched"],
        "status": STATUS_OPEN,
        "opened_at": now_iso,
    }
    reply = None
    if req["subtype"] == "form_guidance":
        try:
            reply = form_guidance_reply(row["exercise_name"], tid, movements)
        except Exception as e:  # noqa: BLE001 — a catalog read failure leaves the request open, never unraised
            logger.warning("note_requests: cue-sheet reply failed for %s: %s", sk, type(e).__name__)
            row["reply_pending"] = f"catalog read failed ({type(e).__name__}); the coach chat answers it"
        if reply is None and "reply_pending" not in row:
            row["reply_pending"] = "no cue sheet for this movement; the coach chat answers it"
    elif req["subtype"] == "rule_request":
        reply = rule_request_reply(row)
    else:
        row["reply_pending"] = "a question is answered by the training coach in conversation, grounded (ADR-104/105)"
    if reply is not None:
        row.update({"status": STATUS_ANSWERED, "channel": CHANNEL_PACKET, "answered_at": now_iso, "reply": reply})
    return row


def _not_exists():
    try:
        from boto3.dynamodb.conditions import Attr

        return Attr("sk").not_exists()
    except Exception:  # noqa: BLE001 — the pure-core unit path
        return None


def _already_written(exc: BaseException) -> bool:
    return "ConditionalCheckFailed" in type(exc).__name__ or "ConditionalCheckFailed" in str(exc)


def raise_requests(table, items, *, today: str | None = None, now_iso: str | None = None, movements: dict | None = None) -> dict:
    """Write one request row per note-layer item that carries an owner request (#5573). Never raises.

    `items` are `write_workout_notes(...)["items"]` — every non-empty note of the workout, written or skipped.
    Write-once: an existing row (open, answered or declined) is never touched.
    """
    from common.numeric import floats_to_decimal
    from common.pacific_time import pacific_today

    today = today or pacific_today()
    out: dict[str, Any] = {"requests": 0, "raised": 0, "already": 0, "historical": 0, "failed": 0, "subtypes": []}
    for it in items or []:
        req = request_signal(it)
        if req is None:
            continue
        out["requests"] += 1
        if not is_recent(str(it.get("date") or ""), today):
            out["historical"] += 1
            continue
        try:
            row = build_request_row(it, req, now_iso=now_iso, movements=movements)
            assert row["pk"] == REQUEST_PK and row["sk"].startswith(REQUEST_SK_PREFIX), row["sk"]
            cond = _not_exists()
            table.put_item(Item=floats_to_decimal(row), **({"ConditionExpression": cond} if cond is not None else {}))
            out["raised"] += 1
            out["subtypes"].append(row["subtype"])
        except Exception as e:  # noqa: BLE001
            if _already_written(e):
                out["already"] += 1
                continue
            out["failed"] += 1
            logger.warning("note_requests: raise failed for %s: %s", it.get("sk"), type(e).__name__)  # never the note text
    return out


# ── reads ───────────────────────────────────────────────────────────────────────────────────
def read_rows(table) -> list[dict]:
    """Every request row, newest note first. Read failures PROPAGATE — "could not read" is not "none open"."""
    from boto3.dynamodb.conditions import Key

    items: list[dict] = []
    kw: dict[str, Any] = {}
    while True:
        r = table.query(KeyConditionExpression=Key("pk").eq(REQUEST_PK) & Key("sk").begins_with(REQUEST_SK_PREFIX), **kw)
        items.extend(r.get("Items") or [])
        if not r.get("LastEvaluatedKey"):
            break
        kw = {"ExclusiveStartKey": r["LastEvaluatedKey"]}
    return sorted(items, key=lambda x: str(x.get("sk") or ""), reverse=True)


def age_days(note_date: str, today: str) -> int | None:
    return _days_between(note_date, today)


def present(row: dict, today: str, *, with_reply: bool = True) -> dict:
    """One row as the packet / capture queue show it. `overdue` = open and older than OVERDUE_DAYS."""
    age = age_days(str(row.get("date") or ""), today)
    from common.pacific_time import pacific_weekday

    out: dict[str, Any] = {
        "request_id": row.get("request_id") or request_id_of(str(row.get("sk") or "")),
        "date": row.get("date"),
        "weekday": pacific_weekday(str(row.get("date") or "")[:10]) if row.get("date") else None,  # #5274: quote it, never derive it
        "exercise": row.get("exercise_name"),
        "template_id": row.get("template_id"),
        "subtype": row.get("subtype"),
        "status": row.get("status"),
        "note": row.get("note_raw"),
        "age_days": age,
        "overdue": row.get("status") == STATUS_OPEN and age is not None and age > OVERDUE_DAYS,
    }
    if row.get("reply_pending") and row.get("status") == STATUS_OPEN:
        out["reply_pending"] = row["reply_pending"]
    for k in ("channel", "answered_at", "declined_at", "decline_reason"):
        if row.get(k):
            out[k] = row[k]
    if with_reply and isinstance(row.get("reply"), dict):
        out["reply"] = {"kind": row["reply"].get("kind"), "label": row["reply"].get("label"), "text": row["reply"].get("text")}
    return out


def view(rows: list[dict], today: str) -> dict:
    """The packet's `note_requests` value: every open request, the overdue count, and the recently answered ones."""
    opened = [present(r, today) for r in rows if r.get("status") == STATUS_OPEN]
    recent = []
    for r in rows:
        if r.get("status") not in (STATUS_ANSWERED, STATUS_DECLINED):
            continue
        a = age_days(str(r.get("answered_at") or r.get("declined_at") or "")[:10], today)
        if a is not None and a <= ANSWERED_VISIBLE_DAYS:
            recent.append(present(r, today))
    return {
        "open_count": len(opened),
        "overdue_count": sum(1 for o in opened if o["overdue"]),
        "overdue_after_days": OVERDUE_DAYS,
        "open": opened,
        "answered_recent": recent,
        "answered_visible_days": ANSWERED_VISIBLE_DAYS,
    }


# ── resolution (the coach chat's write, through get_exercise_notes) ──────────────────────────
def resolve(table, request_id: str, *, status: str, text: str, channel: str = CHANNEL_CHAT, now_iso: str | None = None) -> dict:
    """Move ONE open request to answered (with the reply text) or declined (with the reason). Once only.

    The write is conditional on the stored row still being `open`, so a second answer — from a replay, a second chat,
    or a raise-time reply that already landed — is refused by the store, not by a read that could be stale.
    """
    if status not in (STATUS_ANSWERED, STATUS_DECLINED):
        raise ValueError(f"status must be {STATUS_ANSWERED!r} or {STATUS_DECLINED!r}")
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {CHANNELS}")
    text = str(text or "").strip()
    if not text:
        raise ValueError("an answer needs its reply text; a decline needs its reason")
    rid = str(request_id or "").strip()
    if rid.startswith(REQUEST_SK_PREFIX):
        rid = request_id_of(rid)
    sk = f"{REQUEST_SK_PREFIX}{rid}"
    stored = (table.get_item(Key={"pk": REQUEST_PK, "sk": sk}) or {}).get("Item")
    if not stored:
        return {"wrote": False, "error": f"refused: no request {rid!r}"}
    if stored.get("status") != STATUS_OPEN:
        return {
            "wrote": False,
            "error": f"refused: request {rid!r} is already {stored.get('status')} — a request is answered once",
            "row": stored,
        }
    now_iso = now_iso or _now_z()
    new = dict(stored)
    new.pop("reply_pending", None)
    new.update({"status": status, "channel": channel})
    if status == STATUS_ANSWERED:
        new.update(
            {
                "answered_at": now_iso,
                "reply": {"kind": "coach_answer", "label": "Answered in a coach conversation.", "text": text[:_REPLY_MAX_CHARS]},
            }
        )
    else:
        new.update({"declined_at": now_iso, "decline_reason": text[:_REPLY_MAX_CHARS]})
    try:
        from boto3.dynamodb.conditions import Attr

        table.put_item(Item=new, ConditionExpression=Attr("status").eq(STATUS_OPEN))
    except Exception as e:  # noqa: BLE001
        if _already_written(e):
            return {"wrote": False, "error": f"refused: request {rid!r} was resolved by another writer first"}
        raise
    return {"wrote": True, "row": new}
