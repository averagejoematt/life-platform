"""
hevy_restamp_lambda.py — Overnight branch re-stamp (#417 / TR-05).

Runs AFTER the overnight wearable sync. Reads the night's recovery signal and
RE-ORDERS / re-highlights which branch of the already-pushed routine is
recommended — so the morning's plan reflects the night's data WITHOUT taking
the choice away. It is a suggestion layer, nothing more. Since #417 2b, the
compiler (`hevy_compiler._primary_exercises`) pushes the RECOMMENDED branch's
own exercises as the routine's live set/rep list, so re-flagging here changes
what the reader's Hevy app actually shows, not just which line is starred in
the notes; every other branch still stays visible only in the notes menu.

Hard invariants (the reason this Lambda is safe to schedule):
  * FAILS OPEN. Any error, missing data, disabled gate, or skipped run leaves
    the last pushed routine FULLY usable. The handler NEVER raises — every path
    returns a JSON status dict. There is no DLQ semantics here on purpose: a
    missed re-stamp is a no-op, not an incident.
  * NEVER adds or removes a branch. It only toggles `recommended` and re-orders
    the branch list. Set/rep content of every individual branch is never
    touched — only WHICH already-authored branch becomes the pushed exercise
    list can change. Self-selection is preserved by construction — every
    branch stays visible and choosable via the notes menu.
  * Subtract-safe default. Absent / ambiguous recovery resolves to "the plan as
    written" (the authored recommendation is left in place, not escalated).

Gates (SSM, same shape as hevy-routine-cron):
  /life-platform/pause-mode              — 'paused' → no-op
  /life-platform/budget-tier             — >= 3     → no-op
  /life-platform/hevy/restamp_enabled    — not truthy → no-op (ships false)

The EventBridge rule (`hevy-restamp-daily`, cron(0 18 * * ? *)) is ENABLED as of
PR #711's deferred decision 2a — 18:00 UTC runs after Whoop recovery refreshes
(~17:30 UTC), so the re-stamp always sees fresh recovery. The SSM gate above
still ships "false"; it is flipped true as a deliberate post-merge/post-deploy
step so the enabled rule and this code both land before the first live run.
"""

from __future__ import annotations

import logging
import os
from datetime import date, datetime, timezone
from typing import Any

import boto3

try:
    from platform_logger import get_logger

    logger = get_logger("hevy-restamp")
except ImportError:
    logger = logging.getLogger("hevy-restamp")
    logger.setLevel(logging.INFO)

REGION = os.environ.get("AWS_REGION", "us-west-2")
PAUSE_PARAM = os.environ.get("PAUSE_MODE_PARAM", "/life-platform/pause-mode")
BUDGET_TIER_PARAM = os.environ.get("BUDGET_TIER_PARAM", "/life-platform/budget-tier")
RESTAMP_ENABLED_PARAM = os.environ.get("HEVY_RESTAMP_ENABLED_PARAM", "/life-platform/hevy/restamp_enabled")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")

# Whoop recovery bands (mirror mcp/recovery_authoring.BAND_THRESHOLDS — kept
# inline because recovery_authoring lives in mcp/, not the shared layer this
# Lambda ships on).
GREEN_MIN = 67
YELLOW_MIN = 34

_ssm = boto3.client("ssm", region_name=REGION)
_cw = boto3.client("cloudwatch", region_name=REGION)
_ddb = boto3.resource("dynamodb", region_name=REGION)


def _ssm_get(name: str, default: str = "") -> str:
    try:
        resp = _ssm.get_parameter(Name=name)
        return (resp.get("Parameter", {}).get("Value") or "").strip()
    except _ssm.exceptions.ParameterNotFound:
        return default
    except Exception as e:
        logger.warning(f"SSM read failed for {name}: {e}")
        return default


def _emit_metric(metric_name: str, value: float = 1.0, unit: str = "Count") -> None:
    try:
        _cw.put_metric_data(
            Namespace="LifePlatform/HevyRoutine",
            MetricData=[{"MetricName": metric_name, "Value": value, "Unit": unit}],
        )
    except Exception as e:
        logger.warning(f"metric emit failed for {metric_name}: {e}")


def _target_date_for_event(event: dict[str, Any]) -> str:
    if event.get("target_date"):
        return event["target_date"]
    return date.today().isoformat()


def _gates(event: dict[str, Any]) -> dict[str, Any]:
    pause = _ssm_get(PAUSE_PARAM, "active").lower()
    enabled = _ssm_get(RESTAMP_ENABLED_PARAM, "false").lower() in ("1", "true", "yes")
    budget_tier_raw = _ssm_get(BUDGET_TIER_PARAM, "0")
    try:
        budget_tier = int(budget_tier_raw)
    except ValueError:
        budget_tier = 0
    return {
        "pause": pause,
        "enabled": enabled,
        "budget_tier": budget_tier,
        "force": bool(event.get("force")),
    }


# ── Pure branch-selection core (unit-testable without AWS) ────────────────────


def preference_for_recovery(recovery_score: float | None) -> list[str]:
    """Ordered branch-label preference for a recovery score. Subtract-safe.

    None / ambiguous → prefer the plan as written (no escalation). Green may
    reach for a harder branch IF one exists; red steps down to the easiest
    branch present. This only expresses PREFERENCE — the caller intersects it
    with the branches that actually exist and never invents one.
    """
    if recovery_score is None:
        return ["as-written"]
    if recovery_score >= GREEN_MIN:
        return ["harder", "as-written"]
    if recovery_score >= YELLOW_MIN:
        return ["as-written"]
    return ["easier", "re-entry", "as-written"]


def pick_label(recovery_score: float | None, labels_present: list[str]) -> str | None:
    """First preferred label that actually exists among the branches, else None
    (None ⇒ leave whatever is currently recommended untouched)."""
    present = set(labels_present)
    for lab in preference_for_recovery(recovery_score):
        if lab in present:
            return lab
    return None


def restamp_branches(branches: list, recovery_score: float | None) -> tuple[list, str | None, bool]:
    """Re-order + re-flag branches by recovery. NEVER adds or removes a branch.

    Returns (reordered_branches, chosen_label, changed). `changed` is False when
    the recommendation and order already match — the caller then no-ops rather
    than re-pushing an identical routine. Enforces the count invariant in code:
    the returned list is a permutation of the input.
    """
    if not branches:
        return [], None, False

    original_count = len(branches)
    labels_present = [b.label for b in branches]
    chosen = pick_label(recovery_score, labels_present)
    if chosen is None:
        # No preference resolvable → keep the authored recommendation as-is.
        return list(branches), None, False

    ordered = sorted(branches, key=lambda b: b.order)
    reordered = [b for b in ordered if b.label == chosen] + [b for b in ordered if b.label != chosen]

    assert len(reordered) == original_count, "restamp must never add or remove a branch"

    changed = False
    for i, b in enumerate(reordered):
        new_recommended = b.label == chosen
        if b.recommended != new_recommended or b.order != i:
            changed = True
        b.recommended = new_recommended
        b.order = i
    return reordered, chosen, changed


# ── I/O (fail-open) ───────────────────────────────────────────────────────────


def _latest_recovery_score() -> float | None:
    """Newest Whoop recovery_score, or None. Never raises."""
    try:
        from boto3.dynamodb.conditions import Key

        table = _ddb.Table(TABLE_NAME)
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#whoop") & Key("sk").begins_with("DATE#"),
            Limit=1,
            ScanIndexForward=False,
        )
        items = resp.get("Items", [])
        if not items:
            return None
        val = items[0].get("recovery_score")
        return float(val) if val is not None else None
    except Exception as e:
        logger.warning(f"recovery read failed (re-stamp will use safe default): {e}")
        return None


def _find_pushed_routine(target_date: str):
    """The pushed, branch-carrying routine for target_date, or None. Never raises."""
    try:
        import routine_repo as repo

        candidates = repo.list_by_date_range(target_date, target_date)
        pushed = [r for r in candidates if getattr(r, "hevy_routine_id", None) and getattr(r, "branches", None)]
        if not pushed:
            return None
        # Prefer an active routine; otherwise the most recently pushed.
        pushed.sort(key=lambda r: (r.status != "active", -(r.version or 0)))
        return pushed[0]
    except Exception as e:
        logger.warning(f"routine lookup failed: {e}")
        return None


def lambda_handler(event, context):
    """Fail-open. Always returns a status dict; never raises."""
    try:
        gates = _gates(event or {})
        logger.info(f"gates={gates}")

        if gates["pause"] == "paused" and not gates["force"]:
            _emit_metric("RestampNoOpPaused")
            return {"status": "noop", "reason": "pause-mode=paused"}
        if not gates["enabled"] and not gates["force"]:
            _emit_metric("RestampNoOpDisabled")
            return {"status": "noop", "reason": "restamp_enabled=false"}
        if gates["budget_tier"] >= 3 and not gates["force"]:
            _emit_metric("RestampNoOpBudgetTier3")
            return {"status": "noop", "reason": "budget_tier>=3"}

        target_date = _target_date_for_event(event or {})

        ir = _find_pushed_routine(target_date)
        if ir is None:
            _emit_metric("RestampNoOpNoRoutine")
            return {"status": "noop", "reason": "no-pushed-branched-routine", "target_date": target_date}

        recovery = _latest_recovery_score()
        _, chosen, changed = restamp_branches(ir.branches, recovery)
        if not changed:
            _emit_metric("RestampNoOpUnchanged")
            return {
                "status": "noop",
                "reason": "recommendation-already-current",
                "target_date": target_date,
                "recovery_score": recovery,
                "recommended": chosen,
            }

        # Re-compile + re-push. A conflict (in-app edit) fails open: leave the
        # last routine, do not clobber.
        import hevy_write_client as wc
        import routine_repo as repo
        from hevy_compiler import from_hevy_response, to_update_body
        from hevy_template_cache import resolve_movement
        from routine_title import build_title_context, format_why_note

        try:
            title_ctx = build_title_context(ir)
            why = format_why_note(ir)
            body = to_update_body(ir, resolve_movement, title_context=title_ctx, why_note=why)
            resp = wc.update_routine_with_guard(ir.hevy_routine_id, body, ir.hevy_updated_at)
            parsed = from_hevy_response(resp)
            if parsed.get("updated_at"):
                ir.hevy_updated_at = parsed["updated_at"]
            ir.hevy_pushed_at = datetime.now(timezone.utc).isoformat()
            ir.version = int(ir.version) + 1
            ir.parent_version = ir.version - 1
            ir.source_action = "restamp"
            repo.put_versioned(ir)
            _emit_metric("RestampApplied")
            return {
                "status": "ok",
                "target_date": target_date,
                "recovery_score": recovery,
                "recommended": chosen,
                "hevy_routine_id": ir.hevy_routine_id,
                "branches": [b.label for b in ir.branches],
            }
        except wc.HevyConflict as e:
            # Matthew edited the routine in-app — his edit wins. Fail open.
            logger.warning(f"HevyConflict on re-stamp for {ir.routine_id}: {e}; leaving last routine untouched")
            _emit_metric("RestampNoOpConflict")
            return {"status": "noop", "reason": "in-app-edit-conflict", "target_date": target_date}

    except Exception:
        # FAIL OPEN: log, emit, and return a no-op success. A failed re-stamp
        # must NEVER corrupt or block the morning's routine.
        logger.exception("hevy-restamp failed; failing open (last routine left usable)")
        _emit_metric("RestampFailOpen")
        return {"status": "noop", "reason": "error-failed-open"}
