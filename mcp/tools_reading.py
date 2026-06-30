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

import json
import os
from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key
from reading import (
    reading_constellation,
    reading_enrich,
    reading_keys as rk,
    reading_onboarding,
    reading_recall,
    reading_recommender,
    reading_store,
)

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
    """Cora's recommendation track record (auditable hit rate)."""
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
    (brief §2: never a sparse sad graph) — the graph fills as ideas are kept
    (manage_reading map_ideas on a debriefed book)."""
    idea_id = args.get("idea_id")
    if idea_id:
        node = reading_store.idea(idea_id)
        if not node:
            return mcp_error(f"no idea node '{idea_id}'", error_code="NO_DATA")
        return {"idea": node, "edges": reading_store.idea_edges(idea_id)}
    graph = reading_store.all_ideas()
    ready = reading_constellation.is_ready(graph["node_count"])
    if not ready:
        return {
            "ready": False,
            "node_count": graph["node_count"],
            "min_nodes": _CONSTELLATION_MIN_NODES,
            "note": "The constellation begins with the first idea you keep.",
        }
    return {"ready": True, "nodes": graph["nodes"], "edges": graph["edges"], "node_count": graph["node_count"]}


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
    "map_ideas",
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


_COVER_FN = os.environ.get("COVER_PIPELINE_FN", "reading-cover-pipeline")
_lambda_client = None


def _trigger_cover(book_id, meta):
    """Fire-and-forget invoke of the cover pipeline so a freshly-added book gets a
    cover (Open Library → Google Books → designed placeholder). Fail-soft: a
    cover-invoke failure never breaks add_book — the cover can be fetched later."""
    global _lambda_client
    try:
        import boto3

        if _lambda_client is None:
            _lambda_client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        payload = {k: meta.get(k) for k in ("isbn13", "olid", "title", "author")}
        payload["bookId"] = book_id
        _lambda_client.invoke(FunctionName=_COVER_FN, InvocationType="Event", Payload=json.dumps(payload).encode("utf-8"))
        return True
    except Exception as e:  # noqa: BLE001 — cover is best-effort, never blocks the add
        logger.info("[reading] cover trigger failed (%s) — fetch it later", type(e).__name__)
        return False


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
    cover_triggered = _trigger_cover(bid, meta)
    return {
        "status": "committed",
        "action": "add_book",
        "bookId": bid,
        "cover_fetch": "triggered" if cover_triggered else "deferred (invoke reading-cover-pipeline to fetch)",
    }


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
    """Answer a due probe (Phase D): score the gist, advance the interval, recompute
    the n-gated PRIVATE retentionScore. The two-clock model — this is the retention
    clock, not the immediate debrief."""
    bid, prompt_id = args.get("bookId"), args.get("prompt_id")
    answer = args.get("answer")
    if not bid or not prompt_id or not answer:
        return mcp_error("answer_recall requires bookId + prompt_id + answer", error_code="MISSING_ARG")
    if dry_run:
        return _preview("answer_recall", {"bookId": bid, "prompt_id": prompt_id, "answer": answer})
    recall = reading_store._get(rk.recall_key(bid, prompt_id))  # noqa: SLF001 — intra-domain read
    if not recall:
        return mcp_error(f"no recall prompt '{prompt_id}' for book", error_code="NO_DATA")
    result = reading_recall.record_answer(recall, answer)
    reading_store.put_recall(
        bid,
        prompt_id=prompt_id,
        prompt=recall.get("prompt", ""),
        interval_index=result["intervalIndex"],
        next_due=result["nextDue"],
        performance_history=result["performanceHistory"],
    )
    # retentionScore + lastProbeAt are PRIVATE — live on the READING#/STATE row.
    state = reading_store.get_reading_state(bid) or {"status": "finished"}
    reading_store.put_reading_state(
        bid,
        state.get("status", "finished"),
        fields={
            "retentionScore": result["retentionScore"],
            "lastProbeAt": result["lastProbeAt"],
            **{k: v for k, v in state.items() if k not in ("status", "statusChangedAt", "bookId")},
        },
    )
    return {
        "status": "committed",
        "action": "answer_recall",
        "next_due": result["nextDue"],
        "interval_index": result["intervalIndex"],
        "retention_score": result["retentionScore"],  # None until the n-gate passes
        "probes": len(result["performanceHistory"]),
    }


def _action_debrief(args, dry_run):
    """The post-book debrief (Phase D): the immediate reaction → the public takeaway,
    AND it STARTS the retention clock (creates the first spaced probe). The two clocks
    are never merged — this is reaction; the probe weeks later is retention."""
    bid, takeaway = args.get("bookId"), args.get("takeaway")
    if not bid or not takeaway:
        return mcp_error("debrief requires bookId + takeaway", error_code="MISSING_ARG")
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    note_id = "debrief-" + now
    probe_id = "probe-" + now
    book = reading_store.get_book(bid) or {}
    prompt = f"A few weeks back you read {book.get('title', 'this book')} — what's stayed with you? Reconstruct the heart of it."
    if dry_run:
        return _preview(
            "debrief",
            {"bookId": bid, "noteId": note_id, "first_probe": probe_id, "probe_prompt": prompt, "public": bool(args.get("public", True))},
        )
    item = reading_store.add_note(bid, note_id=note_id, type="synthesis", text=takeaway, public=bool(args.get("public", True)))
    # start the retention clock — the first probe, due in INTERVALS[0] days (sparse GSI1)
    fp = reading_recall.first_probe()
    reading_store.put_recall(bid, prompt_id=probe_id, prompt=prompt, interval_index=0, next_due=fp["nextDue"])
    return {
        "status": "committed",
        "action": "debrief",
        "note": item,
        "first_probe_due": fp["nextDue"],
        "note2": "Retention clock started — the first memory check is weeks out, kept separate from this reaction.",
    }


def _action_map_ideas(args, dry_run):
    """Constellation FILL (Phase E, gated): distill the durable ideas he KEPT from a
    finished book's own takeaway/notes (grounded, never invented) into idea nodes +
    same-book edges. The graph stays honestly empty until enough ideas accrue."""
    bid = args.get("bookId")
    if not bid:
        return mcp_error("map_ideas requires bookId", error_code="MISSING_ARG")
    book = reading_store.get_book(bid) or {}
    notes = reading_store.notes(bid)
    source = "\n\n".join(n.get("text", "") for n in notes if n.get("type") in ("synthesis", "reflection") and n.get("text"))
    if not source.strip():
        return mcp_error("no takeaway/reflection notes to distill — debrief the book first", error_code="NO_DATA")
    ideas = reading_constellation.extract_ideas(book.get("title", "this book"), source)
    if not ideas:
        return {
            "status": "committed",
            "action": "map_ideas",
            "ideas": [],
            "note": "No durable idea distilled (kept honest — nothing invented).",
        }
    if dry_run:
        return _preview("map_ideas", {"bookId": bid, "ideas": ideas})
    for idea in ideas:
        reading_store.put_idea(idea, source_book_id=bid)
    # same-book co-occurrence edges (the simplest honest link; richer linking is gated)
    for i in range(len(ideas)):
        for j in range(i + 1, len(ideas)):
            reading_store.put_edge(
                ideas[i]["ideaId"], ideas[j]["ideaId"], weight=0.5, rationale=f"both kept from {book.get('title', 'the same book')}"
            )
    count = reading_store.all_ideas()["node_count"]
    return {
        "status": "committed",
        "action": "map_ideas",
        "ideas": ideas,
        "constellation_nodes": count,
        "ready": reading_constellation.is_ready(count),
    }


def _action_log_outcome(args, dry_run):
    """Resolve a RECOMMENDATION#'s outcome (feeds Cora's track record)."""
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
    "map_ideas": _action_map_ideas,
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
