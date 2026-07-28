"""coach_nudge_lambda.py — the delivery/IO shell for proactive coach nudges (#1382).

Runs hourly (UTC-fixed cron, email stack). Every invocation:
  1. GRADES any sent-but-ungraded nudge whose 2h outcome window has elapsed
     (AC3 — a sent nudge with no graded outcome is a bug, so grading runs
     unconditionally on every schedule tick, before anything else).
  2. Applies the deterministic rails + trigger evaluation from
     ``lambdas/coach_nudge_engine.py`` (the pure core — NO LLM in the decision
     path, ADR-105) and, if exactly one nudge is due, phrases it with Haiku
     over ONLY the precomputed trigger payload, runs it through the SDT lint +
     grounding gate + coach quality gate (blocked ⇒ dropped silently, never
     regenerated — AC4, ``max_regenerations=0``), and delivers it.

Channel (AC5, decided in the PR): SES email — the platform's existing
outbound channel (7 email lambdas, verified identity). Native web-push does
NOT exist here yet (site/sw.js is a cache-only PWA worker: no push handler,
no VAPID keys, no subscription store), so "whichever the platform already
has" is email; the record's ``channel`` field keeps the door open for a
future web-push sender without a schema change.

Daily cap: an atomic conditional put on the ledger row
(pk=COACH#nudge_ledger, sk=DAY#{PT-date}) reserves the day BEFORE any model
call — ≤1 attempt per Pacific day even across racing invocations, and a
gate-blocked attempt consumes the day (anti-nag: silence, not retry-until-
something-passes).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from ai import budget_guard
from ai.grounded_generation import allowed_dates, allowed_numbers, grounding_findings
from boto3.dynamodb.conditions import Key
from coach import coach_nudge_engine as engine
from coach.coach_checkin import read_cycle
from coach.persona_registry import OPERATIONAL_COACH_IDS
from common.pacific_time import PACIFIC

logger = logging.getLogger()
logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
RECIPIENT = os.environ.get("EMAIL_RECIPIENT", "")
SENDER = os.environ.get("EMAIL_SENDER", "")

# Fallback display names (persona registry is the live source; this keeps the
# subject line honest if the S3 read fails).
_FALLBACK_NAMES = {cid: cid.replace("_coach", "").title() + " Coach" for cid in OPERATIONAL_COACH_IDS}

# Nutrition-domain tags for "a nutrition experiment is active" — MUST equal
# coach_narrative_orchestrator.COACH_DOMAINS["nutrition_coach"] (pinned by
# tests/test_coach_nudge_1382.py so the two can't drift).
NUTRITION_DOMAIN_TAGS = {"nutrition", "metabolic"}

PREDICTION_EVALUABLE_STATUSES = {"pending", "confirming"}

# Lazy client refs — tests monkeypatch these module attributes directly.
_table_ref = None
_ses_ref = None
_lambda_ref = None


def _table():
    global _table_ref
    if _table_ref is None:
        _table_ref = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    return _table_ref


def _ses():
    global _ses_ref
    if _ses_ref is None:
        _ses_ref = boto3.client("sesv2", region_name=REGION)
    return _ses_ref


def _lambda_client():
    global _lambda_ref
    if _lambda_ref is None:
        _lambda_ref = boto3.client("lambda", region_name=REGION)
    return _lambda_ref


def _coach_name(coach_id: str) -> str:
    """Display name from the persona registry, fail-soft to a derived name."""
    try:
        from coach.persona_registry import by_engine_id

        _persona_id, persona = by_engine_id(coach_id)
        if persona and persona.get("name"):
            return persona["name"]
    except Exception as e:  # noqa: BLE001 — a name lookup must never block a nudge
        logger.info("[nudge] persona lookup failed for %s: %s", coach_id, e)
    return _FALLBACK_NAMES.get(coach_id, coach_id)


# ── context gathering (I/O only — all decisions live in the engine) ──────────


def _item_exists(pk: str, sk: str) -> bool:
    try:
        return bool(_table().get_item(Key={"pk": pk, "sk": sk}).get("Item"))
    except Exception as e:  # noqa: BLE001
        logger.warning("[nudge] get_item(%s, %s) failed: %s", pk, sk, e)
        return False


def _active_nutrition_experiments() -> list:
    """Names of active experiments whose tags intersect the nutrition domain."""
    try:
        from experiment.phase_filter import with_phase_filter

        resp = _table().query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"USER#{USER_ID}#SOURCE#experiments") & Key("sk").begins_with("EXP#"),
                }
            )
        )
        out = []
        for e in resp.get("Items", []):
            if e.get("status") != "active":
                continue
            tags = {str(t).lower() for t in (e.get("tags") or [])}
            if tags & NUTRITION_DOMAIN_TAGS:
                out.append(str(e.get("name") or e.get("experiment_id") or "experiment"))
        return out
    except Exception as e:  # noqa: BLE001
        logger.warning("[nudge] experiments query failed: %s", e)
        return []


def _acwr_readings() -> tuple:
    """(latest, previous) {date, acwr, zone} from computed_metrics, else (None, None)."""
    try:
        # #1793: computed_metrics is EXPERIMENT_SCOPED — without the phase filter,
        # the first reads after a reset return tombstoned dead-cycle rows and an
        # ACWR nudge presents a discarded cycle's training load as today's fact.
        from experiment.phase_filter import with_phase_filter

        resp = _table().query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"USER#{USER_ID}#SOURCE#computed_metrics") & Key("sk").begins_with("DATE#"),
                    "ScanIndexForward": False,
                    "Limit": 10,
                }
            )
        )
        readings = []
        for it in resp.get("Items", []):
            if it.get("acwr_zone") is None or it.get("acwr") is None:
                continue
            readings.append(
                {
                    "date": it.get("sk", "").replace("DATE#", ""),
                    "acwr": float(it["acwr"]),
                    "zone": str(it["acwr_zone"]),
                }
            )
            if len(readings) == 2:
                break
        latest = readings[0] if readings else None
        previous = readings[1] if len(readings) > 1 else None
        return latest, previous
    except Exception as e:  # noqa: BLE001
        logger.warning("[nudge] acwr query failed: %s", e)
        return None, None


def _resolution_window_days(evaluation: dict, subdomain: str) -> int:
    """The evaluator's own effective-window rule (lazy import so this module
    stays cheap to import); falls back to the stated window."""
    try:
        from coach.coach_prediction_evaluator import _get_effective_window

        return int(_get_effective_window(evaluation or {}, subdomain))
    except Exception:  # noqa: BLE001 — stated-window fallback keeps the trigger alive
        try:
            return int((evaluation or {}).get("evaluation_window_days", 14))
        except (TypeError, ValueError):
            return 14


def _verdicts_resolving_tomorrow(tomorrow_pt: str) -> list:
    """Pending/confirming predictions whose evaluation window completes tomorrow."""
    out = []
    for coach_id in OPERATIONAL_COACH_IDS:
        try:
            # #1793: COACH#/PREDICTION# is EXPERIMENT_SCOPED — unfiltered, a wiped
            # cycle's ~348 pending predictions keep "resolving tomorrow" for weeks
            # after a reset, burning the daily nudge cap on dead intelligence.
            from experiment.phase_filter import with_phase_filter

            resp = _table().query(
                **with_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq(f"COACH#{coach_id}") & Key("sk").begins_with("PREDICTION#"),
                    }
                )
            )
        except Exception as e:  # noqa: BLE001 — one bad partition never hides the rest
            logger.warning("[nudge] prediction query failed for %s: %s", coach_id, e)
            continue
        for pred in resp.get("Items", []):
            if pred.get("status") not in PREDICTION_EVALUABLE_STATUSES:
                continue
            created = pred.get("created_date")
            if not created:
                continue
            try:
                created_d = datetime.strptime(str(created), "%Y-%m-%d").date()
            except ValueError:
                continue
            window = _resolution_window_days(pred.get("evaluation") or {}, str(pred.get("subdomain") or ""))
            resolution = (created_d + timedelta(days=window)).isoformat()
            if resolution == tomorrow_pt:
                out.append(
                    {
                        "coach_id": coach_id,
                        "prediction_id": pred.get("prediction_id") or pred.get("sk", "").replace("PREDICTION#", ""),
                        "claim": pred.get("claim_natural") or "",
                        "resolution_date": resolution,
                        "confidence": float(pred["confidence"]) if pred.get("confidence") is not None else None,
                    }
                )
    return out


def gather_context(now_pt) -> dict:
    """Assemble the precomputed-fact dict the pure engine evaluates over."""
    yesterday_pt = (now_pt.date() - timedelta(days=1)).isoformat()
    tomorrow_pt = (now_pt.date() + timedelta(days=1)).isoformat()
    latest, previous = _acwr_readings()
    return {
        "now_pt": now_pt,
        "yesterday_pt": yesterday_pt,
        "nutrition_logged_yesterday": _item_exists(f"USER#{USER_ID}#SOURCE#macrofactor", f"DATE#{yesterday_pt}"),
        "active_nutrition_experiments": _active_nutrition_experiments(),
        "acwr_latest": latest,
        "acwr_previous": previous,
        "verdicts_resolving_tomorrow": _verdicts_resolving_tomorrow(tomorrow_pt),
    }


# ── grading pass (AC3) ───────────────────────────────────────────────────────


def _probe_found(sent_at_iso: str, probe: dict) -> bool:
    kind = (probe or {}).get("kind")
    if kind == "item_exists":
        return _item_exists(probe["pk"], probe["sk"])
    if kind == "decision_logged_within":
        lo, hi = engine.probe_key_range(sent_at_iso, probe)
        try:
            resp = _table().query(
                KeyConditionExpression=Key("pk").eq(probe["pk"]) & Key("sk").between(lo, hi),
                Limit=1,
            )
            return bool(resp.get("Items"))
        except Exception as e:  # noqa: BLE001
            logger.warning("[nudge] probe query failed: %s", e)
            return False
    logger.warning("[nudge] unknown probe kind %r — grading as miss", kind)
    return False


def run_grading_pass(now_utc: datetime) -> int:
    """Grade every sent-but-ungraded nudge whose outcome window has elapsed.
    Returns the number graded. Fail-soft per row."""
    start = (now_utc.date() - timedelta(days=3)).isoformat()
    try:
        resp = _table().query(
            KeyConditionExpression=Key("pk").eq(engine.LEDGER_PK)
            & Key("sk").between(f"{engine.LEDGER_SK_PREFIX}{start}", f"{engine.LEDGER_SK_PREFIX}~"),
        )
        rows = resp.get("Items", [])
    except Exception as e:  # noqa: BLE001
        logger.warning("[nudge] ledger scan failed: %s", e)
        return 0

    graded = 0
    for row in rows:
        if row.get("status") != engine.STATUS_SENT or row.get("graded"):
            continue
        sent_at = row.get("sent_at")
        if not sent_at or not engine.grade_due(sent_at, now_utc):
            continue
        try:
            nudge = _table().get_item(Key={"pk": row["nudge_pk"], "sk": row["nudge_sk"]}).get("Item")
            if not nudge:
                logger.warning("[nudge] ledger points at missing nudge %s/%s", row.get("nudge_pk"), row.get("nudge_sk"))
                continue
            outcome = engine.grade_outcome(_probe_found(sent_at, nudge.get("probe") or {}))
            brier = engine.brier_for(float(nudge.get("prior") or 0.5), outcome)
            _table().update_item(
                Key={"pk": row["nudge_pk"], "sk": row["nudge_sk"]},
                UpdateExpression="SET outcome = :o, graded_at = :g, brier = :b",
                ExpressionAttributeValues={
                    ":o": outcome,
                    ":g": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                    ":b": str(brier),
                },
            )
            _table().put_item(Item={**row, "graded": True, "outcome": outcome})
            graded += 1
            logger.info("[nudge] graded %s → %s (brier %s)", row.get("nudge_sk"), outcome, brier)
        except Exception as e:  # noqa: BLE001
            logger.warning("[nudge] grading failed for %s: %s", row.get("sk"), e)
    return graded


# ── the send path ────────────────────────────────────────────────────────────


def _reserve_day(date_pt: str, firing: dict) -> bool:
    """Atomically claim the daily nudge slot. False if already claimed."""
    try:
        _table().put_item(
            Item={
                "pk": engine.LEDGER_PK,
                "sk": engine.ledger_sk(date_pt),
                "record_type": "coach_nudge_ledger",
                "status": "attempting",
                "trigger_type": firing["trigger_type"],
                "coach_id": firing["coach_id"],
                "graded": True,  # flipped to False only once a nudge is actually SENT
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return True
    except Exception as e:  # noqa: BLE001 — ConditionalCheckFailed = day already claimed
        if "ConditionalCheckFailed" in type(e).__name__ or "ConditionalCheckFailed" in str(e):
            logger.info("[nudge] day %s already claimed — standing down", date_pt)
        else:
            logger.warning("[nudge] ledger reserve failed (%s) — standing down", e)
        return False


def _phrase(firing: dict, coach_name: str) -> str:
    """Haiku phrases ONLY the trigger payload (ADR-062 chokepoint via ai_calls).
    Returns '' on any failure — the caller blocks silently."""
    from ai.ai_calls import AI_MODEL_HAIKU, call_anthropic

    system, user = engine.build_phrasing_prompt(coach_name, firing)
    try:
        text = call_anthropic(user, system=system, max_tokens=300, model=AI_MODEL_HAIKU)
    except Exception as e:  # noqa: BLE001 — BudgetExceeded/throttle ⇒ silent drop
        logger.warning("[nudge] phrasing call failed: %s", e)
        return ""
    if not text or "[AI_UNAVAILABLE]" in text:
        return ""
    return text.strip()


def _gate(copy_text: str, firing: dict, coach_name: str) -> list:
    """All content gates (AC4), deterministic first. Returns findings; empty =
    pass. A non-empty result means DROP SILENTLY — never regenerate."""
    findings = [f"sdt:{p}" for p in engine.sdt_violations(copy_text)]

    grounding = grounding_findings(
        copy_text,
        allowed=allowed_numbers(firing["payload"], firing["invited_action"]),
        allowed_dates=allowed_dates(firing["payload"]),
    )
    findings.extend(f"grounding:{f.get('type')}:{f.get('detail', '')}" for f in grounding)
    if findings:
        return findings  # deterministic gates failed — skip the quality-gate invoke

    try:
        from ai.ai_calls import _enforce_quality_gate

        brief = f"proactive {firing['trigger_type']} nudge from {coach_name} phrasing only the deterministic trigger payload"
        final, report = _enforce_quality_gate(
            _lambda_client(),
            firing["coach_id"],
            copy_text,
            brief,
            regenerate_fn=lambda note: "",  # AC4: a blocked nudge is never regenerated
            max_regenerations=0,
        )
        if final is None:
            findings.append(f"quality_gate:held:score={report.get('score')}")
    except Exception as e:  # noqa: BLE001 — gate INFRA errors fail open (matches ai_calls)
        logger.warning("[nudge] quality gate infra error (fail-open): %s", e)
    return findings


def _send_email(coach_name: str, copy_text: str) -> None:
    subject = f"A note from {coach_name}"
    html = (
        "<div style='font-family:Georgia,serif;max-width:540px;margin:0 auto;padding:24px;color:#1a1a1a'>"
        f"<p style='font-size:16px;line-height:1.6'>{copy_text}</p>"
        f"<p style='font-size:13px;color:#666;margin-top:24px'>— {coach_name}</p>"
        "<p style='font-size:12px;color:#999;margin-top:16px'>Proactive nudge · deterministic trigger · "
        "fine to ignore — nothing is waiting on a reply.</p>"
        "</div>"
    )
    _ses().send_email(
        FromEmailAddress=SENDER,
        Destination={"ToAddresses": [RECIPIENT]},
        Content={
            "Simple": {
                "Subject": {"Data": subject, "Charset": "UTF-8"},
                "Body": {"Html": {"Data": html, "Charset": "UTF-8"}},
            }
        },
    )


def _finalize(date_pt: str, nudge_item: dict) -> None:
    """Write the verbatim COACH# record + the final ledger row (overwrites the
    'attempting' reservation)."""
    _table().put_item(Item=nudge_item)
    _table().put_item(Item=engine.build_ledger_item(date_pt, nudge_item))


def lambda_handler(event: dict, context) -> dict:
    now_utc = datetime.now(timezone.utc)
    now_pt = now_utc.astimezone(PACIFIC)
    date_pt = now_pt.date().isoformat()

    # 1. Grading pass — unconditional, before any rail (AC3).
    graded = run_grading_pass(now_utc)

    # 2. Rails — cheap checks first so a silenced day does zero data reads.
    tier = budget_guard.current_tier()
    sent_today = _item_exists(engine.LEDGER_PK, engine.ledger_sk(date_pt))
    if tier >= engine.BUDGET_SILENCE_TIER or not engine.within_send_window(now_pt) or sent_today:
        chosen, reason = engine.apply_rails([], budget_tier=tier, sent_today=sent_today, now_pt=now_pt)
    else:
        ctx = gather_context(now_pt)
        firings = engine.evaluate_triggers(ctx)
        chosen, reason = engine.apply_rails(firings, budget_tier=tier, sent_today=sent_today, now_pt=now_pt)

    if not chosen:
        return {"statusCode": 200, "graded": graded, "nudge": None, "reason": reason}

    # 3. Reserve the day atomically BEFORE any model call.
    if not _reserve_day(date_pt, chosen):
        return {"statusCode": 200, "graded": graded, "nudge": None, "reason": "daily_cap_race"}

    coach_name = _coach_name(chosen["coach_id"])
    cycle = read_cycle()

    copy_text = _phrase(chosen, coach_name)
    if not copy_text:
        item = engine.build_nudge_item(
            chosen, "", engine.STATUS_BLOCKED, date_pt=date_pt, now_utc=now_utc, gate_findings=["ai_unavailable"], cycle=cycle
        )
        _finalize(date_pt, item)
        return {"statusCode": 200, "graded": graded, "nudge": "blocked", "reason": "ai_unavailable"}

    findings = _gate(copy_text, chosen, coach_name)
    if findings:
        # AC4: dropped SILENTLY — stored verbatim for audit, never delivered,
        # never regenerated, and the day stays consumed (anti-nag).
        item = engine.build_nudge_item(
            chosen, copy_text, engine.STATUS_BLOCKED, date_pt=date_pt, now_utc=now_utc, gate_findings=findings, cycle=cycle
        )
        _finalize(date_pt, item)
        logger.info("[nudge] blocked by gates: %s", findings)
        return {"statusCode": 200, "graded": graded, "nudge": "blocked", "reason": "gate", "findings": findings}

    try:
        _send_email(coach_name, copy_text)
    except Exception as e:  # noqa: BLE001
        logger.error("[nudge] SES send failed: %s", e)
        item = engine.build_nudge_item(
            chosen, copy_text, engine.STATUS_BLOCKED, date_pt=date_pt, now_utc=now_utc, gate_findings=[f"ses_error:{e}"], cycle=cycle
        )
        _finalize(date_pt, item)
        return {"statusCode": 500, "graded": graded, "nudge": "error", "reason": "ses_error"}

    item = engine.build_nudge_item(chosen, copy_text, engine.STATUS_SENT, date_pt=date_pt, now_utc=now_utc, cycle=cycle)
    _finalize(date_pt, item)
    logger.info("[nudge] SENT %s nudge from %s (%s)", chosen["trigger_type"], chosen["coach_id"], item["sk"])
    return {
        "statusCode": 200,
        "graded": graded,
        "nudge": "sent",
        "trigger": chosen["trigger_type"],
        "coach_id": chosen["coach_id"],
        "sk": item["sk"],
    }
