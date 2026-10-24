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
                            days-since). #5127: before serving, an open
                            question on a paused source or past the 72 h
                            rotation window is retired (never a skip).
  log_coach_checkin       — record Matthew's answer (or an explicit skip —
                            always valid, zero penalty) verbatim.

Store: pk COACH#{coach_id}_coach / sk CHECKIN#{date}#{uuid8} — the shared
deterministic core is lambdas/coach_checkin.py.

NB: get_coach_checkin_queue carries a read verb ('get') but persists the
questions it generates, so mcp/audit.py names it in WRITE_TOOLS_BEHIND_READ_VERB
(#4401) and it is audited/annotated as a write. (PR #915 had left it classified
READ as a trade-off — the write is system-generated question text, never user
data — which also left the one persisting path outside the #753 trail.)
"""

from datetime import datetime
from typing import TYPE_CHECKING

from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_now, pacific_today  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days

from mcp.config import S3_BUCKET, USER_PREFIX, logger, s3_client, table as _table_ref
from mcp.core import decimal_to_float as _d2f
from mcp.tools_coach_intelligence import COACH_IDS, COACH_NAMES

try:
    # Shared, bundled modules (#781) — staged at zip root in the Lambda.
    from coach import coach_calibration as ccal, coach_checkin as cc, persona_registry
    from ingestion.source_registry import DEFAULT_STALE_HOURS, manual_capture_sources
except ImportError:  # pragma: no cover — MCP bundle always ships lambdas/ at root
    if not TYPE_CHECKING:
        from lambdas import coach_calibration as ccal, coach_checkin as cc, persona_registry
        from lambdas.ingestion.source_registry import DEFAULT_STALE_HOURS, manual_capture_sources

# Manual-capture source → the coach whose domain that channel informs. Sources
# without a mapping still appear in the snapshot but never drive coach choice.
MANUAL_SOURCE_COACH = {
    "apple_health": "glucose",  # the hand-captured HAE streams (CGM/BP/mood)
    "notion": "mind",  # journaling
    "measurements": "physical",  # body tape measurements (MCP channel)
    "food_delivery": "nutrition",  # delivery behavioral signal (MCP channel) — paused since #5006, so manual_capture_sources() omits it
    "macrofactor": "nutrition",  # food log
}

_SKIP_ACK = "Skip logged — always a valid answer, zero penalty. The coaches treat a decline as a boundary, not a gap."


# ── #1708 (epic #1686 S4): the Horizons feedback loop ────────────────────────


def _reaction_sensitivity_attrs(answer):
    """The #1673 fail-closed verdict to stamp on a stored Horizons reaction.

    Fail-SOFT on the import (a missing gate module simply stamps nothing) but
    fail-CLOSED on the outcome: `horizons_calibration.is_publishable_reaction` is a
    POSITIVE match on a cleared verdict, so an unstamped reaction is not publishable
    either. Recording the answer must never fail because of the gate.
    """
    try:
        from reading import horizons_calibration

        return horizons_calibration.sensitivity_attrs_for_reaction(answer)
    except Exception as e:  # noqa: BLE001 — the stamp is advisory; the absence is safe
        logger.warning(f"[#1708] sensitivity stamp unavailable ({type(e).__name__}: {e}) — reaction stays unpublishable")
        return {}


def _refresh_horizons_calibration():
    """Recompute the deterministic Horizons reaction ledger after a reaction lands.

    Fail-soft: a calibration failure must never lose Matthew's verbatim answer (which
    is already committed by the time this runs). Returns a compact summary or None.
    """
    try:
        from reading import horizons_calibration

        cal = horizons_calibration.refresh(_table_ref)
        return {"n_picks": cal.get("n_picks"), "n_reactions": cal.get("n_reactions"), "confidence": cal.get("confidence")}
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[#1708] horizons calibration refresh failed (non-fatal): {type(e).__name__}: {e}")
        return None


# ── live-context snapshot (what generation grounds itself in) ────────────────


def _presence_snapshot():
    """engagement_state STATE#current, trimmed to the fields the prompt needs."""
    try:
        item = _table_ref.get_item(Key={"pk": USER_PREFIX + "engagement_state", "sk": "STATE#current"}).get("Item") or {}
        item = _d2f(item)
        out = {
            k: item.get(k)
            for k in (
                "presence_class",
                "gap_days",
                "last_food_log_date",
                "returned",
                "resumed_after_days",
                "planned_pause",
                "planned_pause_reason",
                "passive_still_flowing",
            )
            if item.get(k) is not None
        }
        # #3294: the raw `channels_quiet` list is a category-level absence assertion
        # whose denominator is one source per label; this snapshot feeds a Bedrock
        # question-generation prompt, so an unlicensed label here becomes a coach
        # asking "why did you stop training?" over a window Strava recorded training
        # in. Same ONE address as every other narrative surface, same fail-closed
        # degradation (an import failure licenses nothing).
        try:
            from content.engagement_core import sourced_quiet

            split = sourced_quiet(item)
            licensed, withheld = list(split.licensed), list(split.withheld)
        except Exception:  # pragma: no cover — defensive; fail CLOSED, never pass through
            licensed, withheld = [], [str(c) for c in (item.get("channels_quiet") or [])]
        out["channels_quiet"] = licensed
        if withheld:
            out["channels_unverified"] = withheld
            out["channels_unverified_note"] = (
                "channels_unverified CANNOT be asserted as absences — the platform could not "
                "establish them from the sources it consulted. Never ask about them as if he stopped."
            )
        return out
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
    today = pacific_now().date()
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


def _find_checkin(checkin_id, coach_hint=""):
    """Locate one CHECKIN# item — direct when a coach hint is given, else a
    search across all coaches. Returns (pk, item-as-floats) or (None, None)."""
    candidates = [coach_hint] if coach_hint else COACH_IDS
    for cid in candidates:
        try:
            item = _table_ref.get_item(Key={"pk": cc.checkin_pk(cid), "sk": checkin_id}).get("Item")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[#915] checkin lookup failed for {cid}: {e}")
            item = None
        if item:
            return cc.checkin_pk(cid), _d2f(item)
    return None, None


# ── tools ────────────────────────────────────────────────────────────────────


def _retire_stale(items):
    """#5127: take down every open question whose driving source is paused or that stood past
    the rotation window — status `retired` with the code and reason recorded on the row. The
    write is conditional on the row still being open, so an answer that lands first wins.
    Returns ([retired summaries], {(pk, sk) taken down}); a failed write is logged and the
    question is still left out of this call's queue (it is no longer the right one to ask)."""
    now = cc.utcnow()
    paused = cc.paused_sources()
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    retired, gone = [], set()
    for it in cc.open_checkins(items):
        verdict = cc.retire_verdict(it, now=now, paused=paused)
        if not verdict:
            continue
        code, reason = verdict
        gone.add((it.get("pk"), it.get("sk")))
        try:
            _table_ref.update_item(
                Key={"pk": it["pk"], "sk": it["sk"]},
                UpdateExpression="SET #st = :ret, retired_at = :ts, retired_code = :code, retired_reason = :why",
                ConditionExpression="#st = :open",
                ExpressionAttributeNames={"#st": "status"},
                ExpressionAttributeValues={":ret": cc.STATUS_RETIRED, ":ts": stamp, ":code": code, ":why": reason, ":open": cc.STATUS_OPEN},
            )
        except Exception as e:  # noqa: BLE001 — a lost retire write never blocks the queue
            logger.warning(f"[#5127] retire write failed for {it.get('sk')}: {type(e).__name__}: {e}")
            continue
        retired.append({"checkin_id": it.get("sk"), "coach_id": it.get("coach_id"), "retired_code": code, "retired_reason": reason})
    return retired, gone


def _stamp_served(items):
    """#5127: record that the queue handed these questions out — the nightly queue-age check
    tells a question nobody has looked at (fine) from one served past its rotation (stuck)."""
    stamp = cc.now_iso()
    for it in items:
        try:
            _table_ref.update_item(
                Key={"pk": it["pk"], "sk": it["sk"]},
                UpdateExpression="SET last_served_at = :ts ADD served_count :one",
                ExpressionAttributeValues={":ts": stamp, ":one": 1},
            )
        except Exception as e:  # noqa: BLE001 — bookkeeping only
            logger.warning(f"[#5127] served stamp failed for {it.get('sk')}: {type(e).__name__}: {e}")


def tool_get_coach_checkin_queue(args):
    """Up to 3 open coach check-in questions; generates (and persists) fresh
    ones only when the queue is empty. Re-calls return the same open questions.

    #5127: an open question leaves first when its driving source is paused or it has
    stood past the rotation window (cc.QUEUE_ROTATE_HOURS) — recorded as `retired`, never
    as a skip — so the queue rotates to the next coach instead of sticking."""
    args = args or {}
    recent = cc.recent_checkins(_table_ref, COACH_IDS)
    retired, gone = _retire_stale(recent)
    already_open = [it for it in cc.open_checkins(recent) if (it.get("pk"), it.get("sk")) not in gone]
    if already_open:
        served = already_open[: cc.MAX_OPEN_QUESTIONS]
        _stamp_served(served)
        out = {
            "open_questions": [_present(it) for it in served],
            "generated": False,
            "how_to_use": (
                "These are the coaches' standing questions — ask Matthew conversationally, one at a time, "
                "then call log_coach_checkin with his verbatim answer (or skip=true; skipping always carries zero penalty)."
            ),
        }
        if retired:
            out["retired"] = retired
        return out

    # Empty queue → one coach generates fresh questions, grounded in live context.
    count = args.get("count", cc.MAX_OPEN_QUESTIONS)
    try:
        count = max(1, min(int(count), cc.MAX_OPEN_QUESTIONS))
    except (TypeError, ValueError):
        count = cc.MAX_OPEN_QUESTIONS

    manual_signal = _manual_source_signal()
    snapshot = {
        "as_of": pacific_today(),
        "presence": _presence_snapshot(),
        "adaptive_mode": _adaptive_mode_snapshot(),
        "manual_sources_days_since": manual_signal,
    }

    requested_coach = cc.normalize_coach_id(args.get("coach_id") or "")
    if requested_coach:
        if requested_coach not in COACH_IDS:
            return {"error": f"unknown coach_id '{requested_coach}'. Valid: " + ", ".join(COACH_IDS)}
        coach_id, reason, source_key = requested_coach, "explicitly requested", None
    else:
        pick = cc.pick_asking_coach_detail(COACH_IDS, manual_signal, cc.recent_checkins(_table_ref, COACH_IDS, days=90))
        coach_id, reason, source_key = pick["coach"], pick["reason"], pick.get("source")

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
        if source_key:
            item["source_key"] = source_key  # #5127: the driving channel, so a later pause retires it by key
        if cycle is not None:
            item["cycle"] = int(cycle)
        _table_ref.put_item(Item=item)
        saved.append(_present(item))

    out = {
        "open_questions": saved,
        "generated": True,
        "generated_by": generated_by,
        "asking_coach": {"coach_id": coach_id, "coach_name": coach_name, "why": reason},
        "how_to_use": (
            "Ask Matthew these conversationally, one at a time — then call log_coach_checkin with his verbatim "
            "answer (or skip=true). Skipping is always valid with zero penalty. Never nag; this only makes the ask possible."
        ),
    }
    if retired:
        out["retired"] = retired
    return out


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
    found_pk, existing = _find_checkin(checkin_id, cc.normalize_coach_id(args.get("coach_id") or ""))
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

    # #1708 (epic #1686 S4): a reaction to the coach's weekly Horizons pick is stamped
    # with the #1673 fail-closed sensitivity verdict AT CAPTURE, exactly as the Social
    # Membrane stamps an inbound post. Deterministic + offline (no classifier wired ⇒
    # HELD), so a personal reaction can never become auto-publishable by default.
    is_prescription = str(existing.get("generated_by") or "") == "prescription_followup"
    if is_prescription and answer:
        for attr, value in _reaction_sensitivity_attrs(answer).items():
            update_parts.append(f"{attr} = :{attr}")
            expr_values[f":{attr}"] = value

    _table_ref.update_item(
        Key={"pk": found_pk, "sk": checkin_id},
        UpdateExpression="SET " + ", ".join(update_parts),
        ExpressionAttributeNames=expr_names,
        ExpressionAttributeValues=expr_values,
    )

    coach_name = existing.get("coach_name") or COACH_NAMES.get(existing.get("coach_id"), existing.get("coach_id"))
    # #1708: a reaction to a Horizons pick immediately recalibrates the deterministic
    # ledger the curating coach reads before the NEXT pick. A skip recalibrates too —
    # an unanswered pick is real signal about the pick, not about Matthew (ADR-104).
    calibration = _refresh_horizons_calibration() if is_prescription else None

    if status == cc.STATUS_SKIPPED:
        out = {"status": "saved", "outcome": "skipped", "coach_name": coach_name, "checkin_id": checkin_id, "message": _SKIP_ACK}
        if calibration:
            out["horizons_calibration"] = calibration
        return out
    result = {
        "status": "saved",
        "outcome": "answered",
        "coach_name": coach_name,
        "checkin_id": checkin_id,
        "message": (
            f"Answer recorded verbatim for {coach_name}. It becomes qualitative context the platform "
            "pairs with (or uses to explain the absence of) the quantitative data."
        ),
        "next_step": (
            "If this answer genuinely changed the coach's read, call log_coach_calibration (once per subdomain, "
            "max 2) so the coach re-grades its own confidence from the conversation — bounded, never required."
        ),
    }
    if calibration:
        result["horizons_calibration"] = calibration
        result["message"] += (
            " This one reacted to a Horizons pick, so it also recalibrated the coach's picking ledger "
            "(and the 6:30 AM enrichment pass will code it as a prescription_reaction signal)."
        )
    return result


def tool_log_coach_calibration(args):
    """#1481: the asking coach re-grades its per-subdomain confidence and
    records what it learned from an ANSWERED check-in — bounded and grounded
    in the verbatim answer by checkin_id (ADR-141, ADR-104)."""
    args = args or {}
    checkin_id = (args.get("checkin_id") or "").strip()
    if not checkin_id.startswith(cc.CHECKIN_SK_PREFIX):
        return {"error": "checkin_id required — the id of the ANSWERED check-in this calibration derives from (starts with 'CHECKIN#')"}

    found_pk, existing = _find_checkin(checkin_id, cc.normalize_coach_id(args.get("coach_id") or ""))
    if not found_pk:
        return {"error": f"check-in '{checkin_id}' not found — call get_coach_checkin_queue for the current questions"}
    if existing.get("status") == cc.STATUS_SKIPPED:
        return {"error": "this check-in was skipped — a skip is a boundary, never evidence; nothing to calibrate from (ADR-141)"}
    if existing.get("status") != cc.STATUS_ANSWERED or not str(existing.get("answer") or "").strip():
        return {"error": "this check-in has no answer yet — log Matthew's answer first (log_coach_checkin), then calibrate from it"}

    result = ccal.apply_conversation_calibration(
        _table_ref,
        {**existing, "pk": found_pk, "sk": checkin_id},
        subdomain=args.get("subdomain"),
        direction=args.get("direction"),
        takeaway=args.get("takeaway"),
        answer_excerpt=args.get("answer_excerpt"),
        weight=args.get("weight"),
        cycle=cc.read_cycle(),
    )
    if result.get("error"):
        return result

    coach_name = existing.get("coach_name") or COACH_NAMES.get(existing.get("coach_id"), existing.get("coach_id"))
    result["coach_name"] = coach_name
    if result.get("status") == "already_recorded":
        result["message"] = "This (answer, subdomain) calibration already exists — idempotent, nothing double-counted."
        return result
    conf = result.get("confidence")
    moved = (
        f"confidence on '{conf['subdomain']}' moved {conf['direction']} ({conf['mean_before']} → {conf['mean_after']}, weight {conf['weight']})"
        if conf
        else "confidence held (direction=hold) — learning recorded without a confidence move"
    )
    result["message"] = (
        f"{coach_name} recalibrated from Matthew's own words: {moved}. "
        "Recorded with channel=conversation provenance — it feeds the stance engine and track record, "
        "distinguished from data-derived verdicts and never counted in any hit rate."
    )
    return result
