"""coach_calibration.py — conversational self-calibration (#1481, ADR-141).

After a coach check-in conversation (#915), the ASKING coach updates its own
read of Matthew from his answer: it re-grades its per-subdomain confidence and
records what it learned — so qualitative conversation moves the SAME
calibration machinery that data does (the Beta-distribution CONFIDENCE# rows
and the LEARNING# audit trail written by coach/coach_prediction_evaluator.py).

Store (single-table; same COACH# partition family):
  pk = COACH#{coach_id}_coach
  sk = LEARNING#{date}#conv-{checkin_uid}-{subdomain}     (deterministic — idempotent
                                                           per (answer, subdomain))
  pk = COACH#{coach_id}_coach / sk = CONFIDENCE#{subdomain} (updated in place)

The rules this module enforces deterministically (ADR-141 — no LLM anywhere in
this write path):

  * GROUNDING (ADR-104): every conversation learning is attributable BY ID to
    the CHECKIN# answer it derives from, and carries a VERBATIM quote of that
    answer (`answer_quote`). A caller-supplied excerpt must actually appear in
    the stored answer (whitespace/case-insensitively) or the write is refused —
    no invented context can enter the calibration trail.
  * BOUNDS: one conversation can never move confidence more than ONE
    data-derived outcome would. The confidence move is a fractional
    pseudo-observation, weight clamped to [0.1, 1.0] (default 0.5), at most
    MAX_CALIBRATIONS_PER_CHECKIN subdomains per answer, and exactly one write
    per (answer, subdomain) — a re-log is a no-op, never a double count.
  * PROVENANCE: the CONFIDENCE# row records `source: "conversation"` (and keeps
    running `conversation_alpha`/`conversation_beta` accumulators); the
    LEARNING# row is tagged `channel: "conversation"` with a status
    (`insight`) that is deliberately OUTSIDE the confirmed/refuted vocabulary,
    so every hit-rate surface stays data-derived by construction.
  * A SKIP is a boundary, never evidence — only an ANSWERED check-in can move
    calibration (enforced by the caller-facing validation here).

Consumers: coach_history_summarizer (STANCE#/COMPRESSED# fold conversation
learnings in, distinguished from data verdicts), mcp get_coach_track_record
(by_channel provenance), coach_observatory_renderer (confidence provenance).
The ADR-108 quality gate consumes these transitively: gate inputs are coach
outputs generated FROM the compressed state this feeds.

Privacy (ADR-141): `answer_quote`/`takeaway` quote Matthew's verbatim check-in
answers — Matthew-private tier. Public surfaces (lambdas/web/site_api_coach.py)
must never render channel=conversation learning text; they filter explicitly.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)

CHANNEL_CONVERSATION = "conversation"
CHANNEL_DATA = "data"

DIRECTION_UP = "up"
DIRECTION_DOWN = "down"
DIRECTION_HOLD = "hold"
DIRECTIONS = (DIRECTION_UP, DIRECTION_DOWN, DIRECTION_HOLD)

# Bounds (ADR-141): one chat never outweighs one graded prediction.
DEFAULT_WEIGHT = 0.5
MIN_WEIGHT = 0.1
MAX_WEIGHT_PER_ANSWER = 1.0
MAX_CALIBRATIONS_PER_CHECKIN = 2

MAX_TAKEAWAY_CHARS = 600
MAX_QUOTE_CHARS = 280
MAX_SUBDOMAIN_CHARS = 40

# Deliberately outside the confirmed/refuted vocabulary — a conversation
# learning is context, never a graded verdict, so no hit-rate can absorb it.
LEARNING_STATUS = "insight"
EVALUATION_TYPE = "conversation_calibration"

_CHECKIN_SK_RE = re.compile(r"^CHECKIN#(\d{4}-\d{2}-\d{2})#([A-Za-z0-9]+)$")


# ── pure helpers ─────────────────────────────────────────────────────────────


def normalize_subdomain(subdomain) -> str:
    """Canonical subdomain slug (underscore style, matching the evaluator's
    SUBDOMAIN_TO_DOMAIN vocabulary: 'sleep_quality', 'protein_intake', ...)."""
    slug = re.sub(r"[^a-z0-9]+", "_", str(subdomain or "").strip().lower()).strip("_")
    return slug[:MAX_SUBDOMAIN_CHARS]


def parse_checkin_sk(checkin_sk) -> Optional[tuple]:
    """(date, uid) from 'CHECKIN#YYYY-MM-DD#uid', or None if malformed."""
    m = _CHECKIN_SK_RE.match(str(checkin_sk or ""))
    return (m.group(1), m.group(2)) if m else None


def _normalize_text(text) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().casefold()


def excerpt_in_answer(answer, excerpt) -> bool:
    """True when the excerpt genuinely appears in the stored answer
    (whitespace/case-insensitive) — the deterministic ADR-104 grounding gate."""
    needle = _normalize_text(excerpt)
    return bool(needle) and needle in _normalize_text(answer)


def grounding_quote(answer, excerpt=None) -> str:
    """The verbatim quote stored on the learning: the validated excerpt if one
    was supplied, else the head of the answer. Always a real substring."""
    if excerpt and excerpt_in_answer(answer, excerpt):
        return str(excerpt).strip()[:MAX_QUOTE_CHARS]
    return str(answer or "").strip()[:MAX_QUOTE_CHARS]


def clamp_weight(weight) -> float:
    """Confidence-move weight clamped to [MIN_WEIGHT, MAX_WEIGHT_PER_ANSWER]."""
    try:
        w = float(weight) if weight is not None else DEFAULT_WEIGHT
    except (TypeError, ValueError):
        w = DEFAULT_WEIGHT
    return max(MIN_WEIGHT, min(MAX_WEIGHT_PER_ANSWER, w))


def calibration_sk_prefix(checkin_sk) -> Optional[str]:
    """The LEARNING# prefix shared by every calibration from one answer —
    what makes the per-answer cap a cheap begins_with count."""
    parsed = parse_checkin_sk(checkin_sk)
    if not parsed:
        return None
    date, uid = parsed
    return f"LEARNING#{date}#conv-{uid}-"


def calibration_learning_sk(checkin_sk, subdomain) -> Optional[str]:
    """Deterministic learning SK — one per (answer, subdomain), so a re-log
    collides with the conditional put instead of double-counting."""
    prefix = calibration_sk_prefix(checkin_sk)
    sub = normalize_subdomain(subdomain)
    if not prefix or not sub:
        return None
    return f"{prefix}{sub}"


def _dec(val) -> Decimal:
    return Decimal(str(round(float(val), 6)))


# ── the write path ───────────────────────────────────────────────────────────


def apply_conversation_calibration(
    table,
    checkin_item: dict,
    *,
    subdomain,
    direction,
    takeaway,
    answer_excerpt=None,
    weight=None,
    now: Optional[str] = None,
    cycle: Optional[int] = None,
) -> dict:
    """Record one conversation-sourced calibration: a LEARNING# (channel=
    conversation, grounded in the answer by id + verbatim quote) and, unless
    direction='hold', a bounded CONFIDENCE# move with source=conversation.

    `checkin_item` is the stored CHECKIN# record (must be status=answered with
    a non-empty answer). Returns {"status": "saved", ...} on success,
    {"status": "already_recorded", ...} on an idempotent replay, or
    {"error": ...} when a rule refuses the write. Deterministic — no LLM.
    """
    checkin_item = checkin_item or {}
    pk = checkin_item.get("pk") or ""
    checkin_sk = checkin_item.get("sk") or ""
    answer = str(checkin_item.get("answer") or "").strip()

    if checkin_item.get("status") != "answered" or not answer:
        return {"error": "only an ANSWERED check-in can move calibration — a skip is a boundary, never evidence (ADR-141)"}
    if not pk.startswith("COACH#"):
        return {"error": f"check-in record has no COACH# partition (pk={pk!r})"}

    parsed = parse_checkin_sk(checkin_sk)
    if not parsed:
        return {"error": f"malformed checkin_id {checkin_sk!r} — expected CHECKIN#YYYY-MM-DD#uid"}
    date, _uid = parsed

    sub = normalize_subdomain(subdomain)
    if not sub:
        return {"error": "subdomain required — reuse the coach's existing CONFIDENCE# subdomain vocabulary where one fits"}

    d = str(direction or "").strip().lower()
    if d not in DIRECTIONS:
        return {"error": f"direction must be one of {'/'.join(DIRECTIONS)}"}

    text = str(takeaway or "").strip()[:MAX_TAKEAWAY_CHARS]
    if not text:
        return {"error": "takeaway required — what the coach actually learned from this answer"}

    if answer_excerpt and not excerpt_in_answer(answer, answer_excerpt):
        return {
            "error": "answer_excerpt is not a substring of the stored answer — a learning must quote the CHECKIN# answer it cites (ADR-104), never invented context"
        }

    w = clamp_weight(weight)
    quote = grounding_quote(answer, answer_excerpt)
    coach_id = pk.removeprefix("COACH#")
    stamp = now or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ── per-answer cap (bound #2) ────────────────────────────────────────────
    prefix = calibration_sk_prefix(checkin_sk)
    learning_sk = calibration_learning_sk(checkin_sk, sub)
    try:
        from boto3.dynamodb.conditions import Key

        resp = table.query(KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(prefix))
        existing = [it.get("sk") for it in resp.get("Items", [])]
    except Exception as e:  # noqa: BLE001 — a cap probe failure must not corrupt the cap
        logger.warning("[coach_calibration] cap probe failed for %s: %s", pk, e)
        existing = []
    if learning_sk in existing:
        return {"status": "already_recorded", "learning_sk": learning_sk, "confidence_moved": False}
    if len(existing) >= MAX_CALIBRATIONS_PER_CHECKIN:
        return {
            "error": (
                f"calibration bound: this check-in answer already produced {len(existing)} calibration(s) "
                f"(max {MAX_CALIBRATIONS_PER_CHECKIN} per answer — ADR-141). No ±3-tier swings off one chat."
            )
        }

    # ── LEARNING# (channel=conversation) — conditional, idempotent ──────────
    learning = {
        "pk": pk,
        "sk": learning_sk,
        "record_type": "coach_learning",
        "coach_id": coach_id,
        "date": date,
        "channel": CHANNEL_CONVERSATION,
        "source": CHANNEL_CONVERSATION,
        "evaluation_type": EVALUATION_TYPE,
        "status": LEARNING_STATUS,
        "subdomain": sub,
        "takeaway": text,
        "checkin_id": checkin_sk,
        "question": str(checkin_item.get("question") or "")[:300],
        "answer_quote": quote,  # verbatim from the stored answer — ADR-104
        "confidence_direction": d,
        "confidence_weight": _dec(w if d != DIRECTION_HOLD else 0),
        "created_at": stamp,
    }
    if cycle is not None:
        learning["cycle"] = int(cycle)
    try:
        table.put_item(Item=learning, ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001 — only the conditional-collision class is expected
        if "ConditionalCheckFailed" in str(e) or "ConditionalCheckFailed" in type(e).__name__:
            return {"status": "already_recorded", "learning_sk": learning_sk, "confidence_moved": False}
        raise

    # ── CONFIDENCE# move (bound #1) — same Beta machinery as the data path ──
    confidence = None
    if d != DIRECTION_HOLD:
        conf_sk = f"CONFIDENCE#{sub}"
        try:
            item = table.get_item(Key={"pk": pk, "sk": conf_sk}).get("Item") or {}
        except Exception as e:  # noqa: BLE001
            logger.warning("[coach_calibration] confidence read failed for %s/%s: %s", pk, conf_sk, e)
            item = {}
        alpha = float(item.get("alpha", 1) or 1)
        beta_val = float(item.get("beta_param", 1) or 1)
        conv_alpha = float(item.get("conversation_alpha", 0) or 0)
        conv_beta = float(item.get("conversation_beta", 0) or 0)
        mean_before = alpha / (alpha + beta_val)

        if d == DIRECTION_UP:
            alpha += w
            conv_alpha += w
        else:
            beta_val += w
            conv_beta += w
        mean_after = alpha / (alpha + beta_val)

        table.put_item(
            Item={
                "pk": pk,
                "sk": conf_sk,
                "alpha": _dec(alpha),
                "beta_param": _dec(beta_val),
                "mean_confidence": _dec(mean_after),
                "sample_size": Decimal(str(max(0, int(alpha + beta_val - 2)))),
                "subdomain": sub,
                "coach_id": coach_id,
                "updated_at": stamp,
                # Provenance (ADR-141): the last update's channel + the running
                # conversational contribution, so the split stays auditable even
                # as the data path keeps incrementing the same Beta.
                "source": CHANNEL_CONVERSATION,
                "last_checkin_id": checkin_sk,
                "conversation_alpha": _dec(conv_alpha),
                "conversation_beta": _dec(conv_beta),
            }
        )
        confidence = {
            "subdomain": sub,
            "direction": d,
            "weight": round(w, 3),
            "mean_before": round(mean_before, 3),
            "mean_after": round(mean_after, 3),
        }
        logger.info(
            "[coach_calibration] %s/%s %s by %.2f from %s: %.3f -> %.3f",
            coach_id,
            sub,
            d,
            w,
            checkin_sk,
            mean_before,
            mean_after,
        )

    return {
        "status": "saved",
        "learning_sk": learning_sk,
        "checkin_id": checkin_sk,
        "channel": CHANNEL_CONVERSATION,
        "answer_quote": quote,
        "confidence_moved": confidence is not None,
        "confidence": confidence,
    }
