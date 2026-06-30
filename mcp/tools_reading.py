"""tools_reading.py — MCP tools for the reading / Mind pillar (Phase B, spec §9).

Seven read tools + one `manage_reading` write fat-tool (draft→dry_run→commit, the
same shape as `manage_hevy_routine`). The reading data layer lives in the shared
layer package `reading/` (ADR-097); these tools are thin wrappers over it — they
NEVER re-implement key/DDB logic (single source of truth).

Owner-facing surface: MCP is Matthew's own tool, so it sees private fields (the
public/private projection in `reading_visibility` is for the *public* site-api,
not here). Anti-black-box: `get_reading_recommendation` returns the decomposed
reason string + confidence; below the n-gate it is propose-and-dispose (one pick).
"""

from __future__ import annotations

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from reading import reading_enrich, reading_keys as rk, reading_onboarding, reading_recommender, reading_store

from mcp.config import logger, table
from mcp.utils import mcp_error

# ── helpers ───────────────────────────────────────────────────────────────────
_CONSTELLATION_MIN_NODES = 4  # honest empty state below this (brief §2)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _abandoned_shelf() -> list:
    """The 'set down' shelf — abandoned books (first-class, dignified; brief §4)."""
    items = reading_store.current_and_queue(statuses=("abandoned",))
    return items.get("abandoned", [])


def _input_streak(sessions: list) -> int:
    """Consecutive days with a reading session, counting back from today."""
    days = {s.get("date") for s in sessions if s.get("date")}
    streak, cursor = 0, datetime.now(timezone.utc).date()
    while cursor.isoformat() in days:
        streak += 1
        cursor = cursor.fromordinal(cursor.toordinal() - 1)
    return streak


def _week_color() -> str:
    """Read the platform's day color (adaptive_mode/computed_metrics) for capacity.
    Defaults to YELLOW (the no-signal baseline) — never fabricates a GREEN."""
    try:
        pk = "USER#matthew#SOURCE#adaptive_mode"
        resp = table.query(KeyConditionExpression=Key("pk").eq(pk), ScanIndexForward=False, Limit=1)
        items = resp.get("Items", [])
        if items:
            mode = (items[0].get("mode") or items[0].get("color") or "").upper()
            if mode in ("GREEN", "YELLOW", "RED"):
                return mode
    except Exception as e:  # noqa: BLE001 — capacity is best-effort; default safe
        logger.info("[reading] week_color lookup failed (%s) — default YELLOW", type(e).__name__)
    return "YELLOW"


def _count_by_status() -> tuple[int, int]:
    """(n_finished, n_abandoned) for the confidence n-gate."""
    finished = len(reading_store.finished())
    abandoned = len(_abandoned_shelf())
    return finished, abandoned


def _build_recommender_state() -> dict:
    """Assemble the recommender's state from reading + platform reads. Pure gather —
    no fabrication; missing signals fall back to honest neutral defaults."""
    profile = reading_store.get_profile() or {}
    n_finished, n_abandoned = _count_by_status()
    finished = reading_store.finished()
    last_finished = finished[-1] if finished else None
    return {
        "week_color": _week_color(),
        "wheel_distribution": reading_store.wheel_distribution(),
        "curriculum_phase": int(profile.get("curriculumPhase", 1)),
        "ratchet_position": float(profile.get("ratchetPosition", 0.4)),
        "trust_ladder_mode": profile.get("trustLadderMode", "propose"),
        "n_finished": n_finished,
        "n_abandoned": n_abandoned,
        "last_finished": last_finished,
        "last_2_books": list(reversed(finished[-2:])) if finished else [],
        "recent_streak_genre": (profile.get("recentStreakGenre")),
    }


def _candidates_from_queue() -> list:
    """The 'want' queue, joined to BOOK# facts — the candidate set to rank."""
    queue = reading_store.current_and_queue(statuses=("want",)).get("want", [])
    candidates = []
    for state in queue:
        book = reading_store.get_book(state.get("bookId", ""))
        if book:
            candidates.append(book)
    return candidates


# ── READ TOOLS ────────────────────────────────────────────────────────────────
def tool_get_reading_shelf(args):
    """The shelf: currently-reading, the queue, finished, and the 'set down' shelf."""
    cq = reading_store.current_and_queue(statuses=("reading", "want"))
    return {
        "reading": cq.get("reading", []),
        "queue": cq.get("want", []),
        "finished": reading_store.finished(),
        "set_down": _abandoned_shelf(),
        "as_of": _today(),
    }


def tool_get_reading_recommendation(args):
    """A curated next-read pick with a decomposed reason string + confidence.
    Below the n-gate it is propose-and-dispose (one pick, stated as a hypothesis)."""
    candidates = _candidates_from_queue()
    state = _build_recommender_state()
    top_n = int(args.get("limit", 3))
    result = reading_recommender.rank(candidates, state, top_n=top_n)
    if not candidates:
        result["note"] = "Nothing in the queue yet — add a book (manage_reading add_book) to get a pick."
    return result


def tool_get_reading_profile(args):
    """The reading calibration profile (taste hypothesis, ratchet, wheel, trust mode)."""
    profile = reading_store.get_profile()
    if not profile:
        return {"profile": None, "note": "No reading profile yet — run the onboarding interview (manage_reading onboard)."}
    return {"profile": profile, "as_of": _today()}


def tool_get_reading_history(args):
    """Reading-session history over a date range + the current input streak."""
    end = args.get("end_date", _today())
    start = args.get("start_date")
    if not start:
        # default trailing 90 days
        start = datetime.fromisoformat(end).date()
        start = start.fromordinal(start.toordinal() - 90).isoformat()
    sessions = reading_store.history(start, end)
    return {"sessions": sessions, "input_streak_days": _input_streak(sessions), "window": {"start": start, "end": end}}


def tool_get_due_recalls(args):
    """Spaced-retrieval prompts due now (the sparse-GSI1 sweep; private)."""
    due = reading_store.due_recalls()
    return {"due": due, "count": len(due), "as_of": datetime.now(timezone.utc).isoformat()}


def tool_get_reading_track_record(args):
    """Lena's recommendation track record (auditable hit rate)."""
    recs = reading_store.track_record(limit=int(args.get("limit", 50)))
    resolved = [r for r in recs if r.get("resolvedOutcome")]
    hits = [r for r in resolved if r.get("resolvedOutcome") in ("right", "surprised")]
    return {
        "recommendations": recs,
        "resolved_count": len(resolved),
        "hit_rate": round(len(hits) / len(resolved), 3) if resolved else None,
        "note": None if len(resolved) >= 5 else "Hit rate is low-confidence until more recommendations resolve.",
    }


def tool_get_constellation(args):
    """The Constellation idea-graph. Honest empty state below the node threshold
    (brief §2: never a sparse sad graph). Whole-graph enumeration is Phase E."""
    idea_id = args.get("idea_id")
    if idea_id:
        node = reading_store.idea(idea_id)
        if not node:
            return mcp_error(f"no idea node '{idea_id}'", error_code="NO_DATA")
        return {"idea": node, "edges": reading_store.idea_edges(idea_id)}
    return {
        "ready": False,
        "min_nodes": _CONSTELLATION_MIN_NODES,
        "note": "The constellation begins with the first idea you keep. (Full graph view ships in Phase E.)",
    }


# ── WRITE FAT-TOOL (draft → dry_run → commit) ─────────────────────────────────
_WRITE_ACTIONS = {
    "add_book",
    "update_status",
    "log_session",
    "add_note",
    "answer_recall",
    "debrief",
    "log_outcome",
    "update_profile",
    "onboard",
}


def _preview(action: str, plan: dict) -> dict:
    """A dry_run preview — what WOULD be written, with the inputs-current line."""
    return {
        "status": "preview",
        "action": action,
        "would_write": plan,
        "inputs_current_through": _today(),
        "note": "Dry run — nothing written. Re-call with dry_run=false to commit.",
    }


def _action_add_book(args, dry_run):
    meta = {k: args.get(k) for k in ("title", "author", "isbn13", "olid", "pageCount", "format") if args.get(k) is not None}
    if not meta.get("title"):
        return mcp_error("add_book requires a title", error_code="MISSING_ARG")
    bid = args.get("bookId") or rk.book_id(
        isbn13=meta.get("isbn13"), olid=meta.get("olid"), title=meta.get("title"), author=meta.get("author")
    )
    if dry_run:
        enrich = reading_enrich.enrich_book(meta) if args.get("preview_enrich") else {"note": "enrichment runs on commit"}
        return _preview("add_book", {"bookId": bid, "book": meta, "initial_status": args.get("status", "want"), "enrichment": enrich})
    bid = reading_store.add_book(meta, initial_status=args.get("status", "want"))
    return {"status": "committed", "action": "add_book", "bookId": bid, "note": "Cover fetch is a separate step (reading-cover-pipeline)."}


def _action_update_status(args, dry_run):
    bid, status = args.get("bookId"), (args.get("status") or "").lower()
    if not bid or status not in rk.VALID_STATUSES:
        return mcp_error(f"update_status requires bookId + status in {rk.VALID_STATUSES}", error_code="MISSING_ARG")
    if status == "abandoned" and (args.get("abandon_reason") or "").lower() not in rk.VALID_ABANDON_REASONS:
        return mcp_error(f"abandon requires abandon_reason in {rk.VALID_ABANDON_REASONS}", error_code="MISSING_ARG")
    if dry_run:
        return _preview("update_status", {"bookId": bid, "status": status, "abandon_reason": args.get("abandon_reason")})
    item = reading_store.update_reading_status(bid, status, abandon_reason=args.get("abandon_reason"))
    return {"status": "committed", "action": "update_status", "state": item}


def _action_log_session(args, dry_run):
    bid = args.get("bookId")
    if not bid or args.get("minutes") is None:
        return mcp_error("log_session requires bookId + minutes", error_code="MISSING_ARG")
    plan = {"bookId": bid, "minutes": args.get("minutes"), "pages": args.get("pages"), "date": args.get("date")}
    if dry_run:
        return _preview("log_session", plan)
    item = reading_store.log_session(
        bid,
        minutes=float(args["minutes"]),
        pages=args.get("pages"),
        date=args.get("date"),
        location=args.get("location"),
        mood_snapshot=args.get("mood_snapshot"),
    )
    return {"status": "committed", "action": "log_session", "session": item}


def _action_add_note(args, dry_run):
    bid, text = args.get("bookId"), args.get("text")
    if not bid or not text:
        return mcp_error("add_note requires bookId + text", error_code="MISSING_ARG")
    note_id = args.get("note_id") or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    plan = {"bookId": bid, "noteId": note_id, "type": args.get("type", "reflection"), "public": bool(args.get("public", False))}
    if dry_run:
        return _preview("add_note", {**plan, "text": text})
    item = reading_store.add_note(
        bid, note_id=note_id, type=args.get("type", "reflection"), text=text, public=bool(args.get("public", False))
    )
    return {"status": "committed", "action": "add_note", "note": item}


def _action_answer_recall(args, dry_run):
    bid, prompt_id = args.get("bookId"), args.get("prompt_id")
    if not bid or not prompt_id:
        return mcp_error("answer_recall requires bookId + prompt_id", error_code="MISSING_ARG")
    if dry_run:
        return _preview("answer_recall", {"bookId": bid, "prompt_id": prompt_id, "next_due": args.get("next_due")})
    # advance the prompt: record the answer, set the next interval (or retire → drops from GSI1)
    item = reading_store.put_recall(
        bid,
        prompt_id=prompt_id,
        prompt=args.get("prompt", ""),
        interval_index=int(args.get("interval_index", 1)),
        next_due=args.get("next_due"),
        performance_history=args.get("performance_history"),
    )
    return {"status": "committed", "action": "answer_recall", "recall": item}


def _action_debrief(args, dry_run):
    """Record the post-book debrief note(s). (The Third Wall render is Phase D; this
    persists the takeaway as a note.)"""
    bid, takeaway = args.get("bookId"), args.get("takeaway")
    if not bid or not takeaway:
        return mcp_error("debrief requires bookId + takeaway", error_code="MISSING_ARG")
    note_id = "debrief-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    if dry_run:
        return _preview("debrief", {"bookId": bid, "noteId": note_id, "public": bool(args.get("public", True))})
    item = reading_store.add_note(bid, note_id=note_id, type="synthesis", text=takeaway, public=bool(args.get("public", True)))
    return {"status": "committed", "action": "debrief", "note": item, "note2": "Prediction reconciliation lands in Phase D."}


def _action_log_outcome(args, dry_run):
    """Resolve a RECOMMENDATION#'s outcome (feeds Lena's track record)."""
    ts, outcome = args.get("ts"), (args.get("resolved_outcome") or "").lower()
    if not ts or outcome not in ("right", "surprised", "unexpected", "miss"):
        return mcp_error("log_outcome requires ts + resolved_outcome in right|surprised|unexpected|miss", error_code="MISSING_ARG")
    if dry_run:
        return _preview("log_outcome", {"ts": ts, "resolved_outcome": outcome})
    existing = reading_store._get(rk.rec_key(ts)) or {}  # noqa: SLF001 — intra-domain read
    existing = {k: v for k, v in existing.items() if k not in ("pk", "sk")}
    existing.update({"ts": ts, "resolvedOutcome": outcome, "resolvedAt": _today(), "status": "resolved"})
    item = reading_store.put_recommendation(existing)
    return {"status": "committed", "action": "log_outcome", "recommendation": item}


def _action_update_profile(args, dry_run):
    profile = reading_store.get_profile() or {}
    profile = {k: v for k, v in profile.items() if k not in ("pk", "sk")}
    for key in ("curriculumPhase", "ratchetPosition", "trustLadderMode", "seasonBias", "tasteHypothesis", "recentStreakGenre"):
        if key in args:
            profile[key] = args[key]
    if dry_run:
        return _preview("update_profile", {"profile": profile})
    item = reading_store.put_profile(profile)
    return {"status": "committed", "action": "update_profile", "profile": item}


def _action_onboard(args, dry_run):
    """Run the taste-archaeology synthesis on interview answers → tasteHypothesis."""
    answers = args.get("answers")
    if not answers:
        return {
            "status": "questions",
            "action": "onboard",
            "questions": reading_onboarding.QUESTION_BANK,
            "note": "Answer ~6-8 of these conversationally, then call onboard with answers={question: answer}.",
        }
    hypothesis = reading_onboarding.synthesize_taste(answers)
    if dry_run:
        return _preview("onboard", {"tasteHypothesis": hypothesis})
    profile = reading_store.get_profile() or {}
    profile = {k: v for k, v in profile.items() if k not in ("pk", "sk")}
    profile["tasteHypothesis"] = hypothesis
    profile.setdefault("trustLadderMode", "propose")
    profile.setdefault("curriculumPhase", 1)
    item = reading_store.put_profile(profile)
    return {"status": "committed", "action": "onboard", "tasteHypothesis": hypothesis, "profile": item}


_DISPATCH = {
    "add_book": _action_add_book,
    "update_status": _action_update_status,
    "log_session": _action_log_session,
    "add_note": _action_add_note,
    "answer_recall": _action_answer_recall,
    "debrief": _action_debrief,
    "log_outcome": _action_log_outcome,
    "update_profile": _action_update_profile,
    "onboard": _action_onboard,
}


def tool_manage_reading(args=None):
    """Single write fat-tool for the reading library (draft→dry_run→commit).
    Every mutating action previews by default (dry_run=true) and writes only on an
    explicit dry_run=false — commit on explicit confirmation, never inferred."""
    args = args or {}
    action = (args.get("action") or "").strip().lower()
    if action not in _WRITE_ACTIONS:
        return mcp_error(f"action must be one of: {sorted(_WRITE_ACTIONS)}", error_code="INVALID_ACTION")
    dry_run = args.get("dry_run", True)
    if isinstance(dry_run, str):
        dry_run = dry_run.strip().lower() not in ("false", "0", "no")
    try:
        return _DISPATCH[action](args, bool(dry_run))
    except Exception as e:  # noqa: BLE001 — surface a clean MCP error, never a stack trace
        logger.exception("[reading] manage_reading %s failed", action)
        return mcp_error(f"{action} failed: {type(e).__name__}", error_code="INTERNAL")
