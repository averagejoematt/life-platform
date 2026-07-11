"""tools_coach_checkin.py — the ad-hoc coach check-in loop (#915).

Matthew talks to his coaches from Claude chat. Mirrors the #422
habit-reflection idiom (tools_habits): a READ-shaped tool surfaces what to ask,
a WRITE tool records the answer verbatim.

  get_coach_checkin_queue — up to 3 open questions from the coaches. Open
                            questions are PERSISTED: a re-call returns the same
                            queue instead of regenerating. When the queue is
                            empty, one coach (rotated toward the most
                            informative current signal — the longest-dark
                            manual channel) generates fresh questions via the
                            Bedrock chokepoint, grounded in a compact live
                            snapshot (presence, adaptive mode, manual-source
                            days-since).
  log_coach_checkin       — record Matthew's answer (or an explicit skip —
                            always valid, zero penalty) verbatim.

Store: pk COACH#{coach_id}_coach / sk CHECKIN#{date}#{uuid8} — the shared
deterministic core is lambdas/coach_checkin.py.

NB: get_coach_checkin_queue classifies as a READ in mcp/audit.py (verb 'get')
but persists the questions it generates — a deliberate trade-off documented in
PR #915 (the write is system-generated question text, never user data).
"""

from datetime import datetime, timezone

from boto3.dynamodb.conditions import Key

from mcp.config import S3_BUCKET, USER_PREFIX, logger, s3_client, table as _table_ref
from mcp.core import decimal_to_float as _d2f
from mcp.tools_coach_intelligence import COACH_IDS, COACH_NAMES

try:
    # Shared, bundled modules (#781) — staged at zip root in the Lambda.
    import coach_checkin as cc
    import persona_registry
    from source_registry import DEFAULT_STALE_HOURS, manual_capture_sources
except ImportError:  # pragma: no cover — MCP bundle always ships lambdas/ at root
    from lambdas import coach_checkin as cc, persona_registry
    from lambdas.source_registry import DEFAULT_STALE_HOURS, manual_capture_sources

# Manual-capture source → the coach whose domain that channel informs. Sources
# without a mapping still appear in the snapshot but never drive coach choice.
MANUAL_SOURCE_COACH = {
    "apple_health": "glucose",  # the hand-captured HAE streams (CGM/BP/mood)
    "notion": "mind",  # journaling
    "measurements": "physical",  # body tape measurements (MCP channel)
    "food_delivery": "nutrition",  # delivery behavioral signal (MCP channel)
    "macrofactor": "nutrition",  # food log
}

_SKIP_ACK = "Skip logged — always a valid answer, zero penalty. The coaches treat a decline as a boundary, not a gap."


# ── live-context snapshot (what generation grounds itself in) ────────────────


def _presence_snapshot():
    """engagement_state STATE#current, trimmed to the fields the prompt needs."""
    try:
        item = _table_ref.get_item(Key={"pk": USER_PREFIX + "engagement_state", "sk": "STATE#current"}).get("Item") or {}
        item = _d2f(item)
        return {
            k: item.get(k)
            for k in (
                "presence_class",
                "gap_days",
                "last_food_log_date",
                "channels_quiet",
                "returned",
                "resumed_after_days",
                "planned_pause",
                "planned_pause_reason",
                "passive_still_flowing",
            )
            if item.get(k) is not None
        }
    except Exception as e:  # noqa: BLE001 — fail-soft
        logger.warning(f"[#915] presence read failed: {e}")
        return {}


def _adaptive_mode_snapshot():
    """Latest adaptive_mode record (DATE# desc, limit 1), trimmed."""
    try:
        resp = _table_ref.query(
            KeyConditionExpression=Key("pk").eq(USER_PREFIX + "adaptive_mode") & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items") or []
        if not items:
            return {}
        item = _d2f(items[0])
        return {k: item.get(k) for k in ("date", "brief_mode", "mode_label", "engagement_score") if item.get(k) is not None}
    except Exception as e:  # noqa: BLE001 — fail-soft
        logger.warning(f"[#915] adaptive_mode read failed: {e}")
        return {}


def _manual_source_signal():
    """Days-since-last-record per manual-capture source (#746 registry), with
    each source's own staleness threshold and owning coach. Partition-level —
    the cheap, honest 'how dark is this channel' signal."""
    out = []
    today = datetime.now(timezone.utc).date()
    for src, meta in manual_capture_sources().items():
        days_since = None
        try:
            resp = _table_ref.query(
                KeyConditionExpression=Key("pk").eq(USER_PREFIX + src) & Key("sk").begins_with("DATE#"),
                ScanIndexForward=False,
                Limit=1,
            )
            items = resp.get("Items") or []
            if items:
                last = items[0].get("sk", "").replace("DATE#", "")[:10]
                days_since = (today - datetime.strptime(last, "%Y-%m-%d").date()).days
        except Exception as e:  # noqa: BLE001 — one dark partition never hides the rest
            logger.warning(f"[#915] manual-source probe failed for {src}: {e}")
        stale_hours = meta.get("stale_hours") or DEFAULT_STALE_HOURS
        out.append(
            {
                "source": src,
                "label": meta.get("label", src),
                "channel": meta.get("channel"),
                "days_since": days_since,
                "stale_days": max(1, round(stale_hours / 24)),
                "coach": MANUAL_SOURCE_COACH.get(src),
            }
        )
    return out


def _coach_bio(coach_id):
    """short_bio + domain from the canonical persona registry (S3-backed,
    5-min cached); fail-soft empty."""
    try:
        p = persona_registry.resolve(f"{coach_id}_coach", s3_client, S3_BUCKET) or {}
        bio = (p.get("short_bio") or "").strip()
        domain = (p.get("domain") or "").replace("_", " ")
        return f"{bio} Your domain: {domain}." if bio or domain else ""
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[#915] persona lookup failed for {coach_id}: {e}")
        return ""


def _present(item):
    """The queue-facing shape of one CHECKIN# item."""
    it = _d2f(item)
    return {
        "checkin_id": it.get("sk"),
        "coach_id": it.get("coach_id"),
        "coach_name": it.get("coach_name") or COACH_NAMES.get(it.get("coach_id"), it.get("coach_id")),
        "question": it.get("question"),
        "tags": it.get("tags") or [],
        "asked_at": it.get("asked_at"),
        "context_reason": it.get("context_reason"),
    }


# ── tools ────────────────────────────────────────────────────────────────────


def tool_get_coach_checkin_queue(args):
    """Up to 3 open coach check-in questions; generates (and persists) fresh
    ones only when the queue is empty. Re-calls return the same open questions."""
    args = args or {}
    already_open = cc.open_checkins(cc.recent_checkins(_table_ref, COACH_IDS))
    if already_open:
        return {
            "open_questions": [_present(it) for it in already_open[: cc.MAX_OPEN_QUESTIONS]],
            "generated": False,
            "how_to_use": (
                "These are the coaches' standing questions — ask Matthew conversationally, one at a time, "
                "then call log_coach_checkin with his verbatim answer (or skip=true; skipping always carries zero penalty)."
            ),
        }

    # Empty queue → one coach generates fresh questions, grounded in live context.
    count = args.get("count", cc.MAX_OPEN_QUESTIONS)
    try:
        count = max(1, min(int(count), cc.MAX_OPEN_QUESTIONS))
    except (TypeError, ValueError):
        count = cc.MAX_OPEN_QUESTIONS

    manual_signal = _manual_source_signal()
    snapshot = {
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "presence": _presence_snapshot(),
        "adaptive_mode": _adaptive_mode_snapshot(),
        "manual_sources_days_since": manual_signal,
    }

    requested_coach = cc.normalize_coach_id(args.get("coach_id") or "")
    if requested_coach:
        if requested_coach not in COACH_IDS:
            return {"error": f"unknown coach_id '{requested_coach}'. Valid: " + ", ".join(COACH_IDS)}
        coach_id, reason = requested_coach, "explicitly requested"
    else:
        coach_id, reason = cc.pick_asking_coach(COACH_IDS, manual_signal, cc.recent_checkins(_table_ref, COACH_IDS, days=90))

    coach_name = COACH_NAMES.get(coach_id, coach_id)
    questions = cc.generate_questions(coach_id, coach_name, _coach_bio(coach_id), snapshot, count)
    generated_by = "bedrock"
    if not questions:
        fallback = cc.FALLBACK_QUESTIONS.get(coach_id)
        if not fallback:
            return {"error": "question generation unavailable and no fallback for this coach — try again later"}
        questions = [{"question": fallback, "tags": ["fallback"]}]
        generated_by = "fallback"

    now = cc.now_iso()
    cycle = cc.read_cycle()
    saved = []
    for q in questions:
        item = {
            "pk": cc.checkin_pk(coach_id),
            "sk": cc.new_checkin_sk(),
            "record_type": "coach_checkin",
            "coach_id": coach_id,
            "coach_name": coach_name,
            "question": q["question"],
            "tags": q.get("tags") or [],
            "status": cc.STATUS_OPEN,
            "asked_at": now,
            "provenance": cc.PROVENANCE,
            "context_reason": reason,
            "generated_by": generated_by,
        }
        if cycle is not None:
            item["cycle"] = int(cycle)
        _table_ref.put_item(Item=item)
        saved.append(_present(item))

    return {
        "open_questions": saved,
        "generated": True,
        "generated_by": generated_by,
        "asking_coach": {"coach_id": coach_id, "coach_name": coach_name, "why": reason},
        "how_to_use": (
            "Ask Matthew these conversationally, one at a time — then call log_coach_checkin with his verbatim "
            "answer (or skip=true). Skipping is always valid with zero penalty. Never nag; this only makes the ask possible."
        ),
    }


def tool_log_coach_checkin(args):
    """Record Matthew's answer to a coach check-in question VERBATIM (ADR-104)
    — or an explicit skip, which is always valid with zero penalty."""
    args = args or {}
    checkin_id = (args.get("checkin_id") or "").strip()
    if not checkin_id.startswith(cc.CHECKIN_SK_PREFIX):
        return {"error": "checkin_id required — the id returned by get_coach_checkin_queue (starts with 'CHECKIN#')"}

    answer = (args.get("answer") or "").strip()[: cc.MAX_ANSWER_CHARS]
    skip = bool(args.get("skip"))
    if not answer and not skip:
        return {"error": "provide answer (Matthew's words, verbatim) or skip=true (always valid, zero penalty)"}

    # Locate the question — direct when coach_id is given, else search all coaches.
    coach_hint = cc.normalize_coach_id(args.get("coach_id") or "")
    candidates = [coach_hint] if coach_hint else COACH_IDS
    found_pk = None
    existing = None
    for cid in candidates:
        try:
            item = _table_ref.get_item(Key={"pk": cc.checkin_pk(cid), "sk": checkin_id}).get("Item")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[#915] checkin lookup failed for {cid}: {e}")
            item = None
        if item:
            found_pk = cc.checkin_pk(cid)
            existing = _d2f(item)
            break
    if not found_pk:
        return {"error": f"check-in '{checkin_id}' not found — call get_coach_checkin_queue for the current open questions"}

    tags = [str(t).strip().lower() for t in (args.get("tags") or []) if str(t).strip()][:5]
    now = cc.now_iso()
    status = cc.STATUS_SKIPPED if skip and not answer else cc.STATUS_ANSWERED

    update_parts = ["#st = :st", "skipped = :sk", "answered_at = :ts", "provenance = :prov"]
    expr_names = {"#st": "status"}
    expr_values = {":st": status, ":sk": status == cc.STATUS_SKIPPED, ":ts": now, ":prov": cc.PROVENANCE}
    if answer:
        update_parts.append("answer = :ans")
        expr_values[":ans"] = answer  # verbatim — never paraphrased (ADR-104)
    if tags:
        update_parts.append("tags = :tags")
        expr_values[":tags"] = tags

    _table_ref.update_item(
        Key={"pk": found_pk, "sk": checkin_id},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )

    coach_name = existing.get("coach_name") or COACH_NAMES.get(existing.get("coach_id"), existing.get("coach_id"))
    if status == cc.STATUS_SKIPPED:
        return {"status": "saved", "outcome": "skipped", "coach_name": coach_name, "checkin_id": checkin_id, "message": _SKIP_ACK}
    return {
        "status": "saved",
        "outcome": "answered",
        "coach_name": coach_name,
        "checkin_id": checkin_id,
        "message": (
            f"Answer recorded verbatim for {coach_name}. It becomes qualitative context the platform "
            "pairs with (or uses to explain the absence of) the quantitative data."
        ),
    }
