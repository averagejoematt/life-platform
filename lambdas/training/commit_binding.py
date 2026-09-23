"""commit_binding.py — a commit is bound to the routine the stage-2 red team verdicted (#4066).

THE INCIDENT (2026-09-22, read off DynamoDB). Three Legs routines were drafted for 09-22.
`21bffbdc…` went through stage 2 (four critics, 03:27:27Z) and was committed at 03:27:50Z;
`cdb6ef…` — drafted at 03:29:49Z, NEVER red-teamed (no `critics` record on any version) — was
committed at 03:30:09Z and is the routine Hevy still holds (21bffbdc's Hevy copy reads 404 now). The
commit said so in one line (`critics: not run — this routine was NOT red-teamed`) and pushed
anyway: a warning in a result the chat is free to summarise away is not a gate.

THE RULING (#4066, in the PR): REFUSE, with an explicit owner override. Stage 2 stamps a
`binding` on its verdict record — the routine_id, the version it wrote, and a content hash of
everything the compiler will push. Commit recomputes the hash and refuses when:

  * the routine carries no stage-2 verdict at all (`not_red_teamed`) — and the refusal NAMES
    the routines for the same target_date that do carry one, so "you meant 21bffbdc" is in
    the error rather than in someone's memory;
  * the verdict predates binding (`unbound`) — re-run stage 2, one call;
  * the verdict names a different routine_id (`other_routine`);
  * the content changed since the verdict (`content_changed`).

The override is `owner_override_redteam: true` plus a non-empty `override_reason`. It does not
touch the critic veto (that is #4076's path), it is stamped into the stored IR, and the commit
result carries it as a warning — overriding is allowed, overriding quietly is not.

DELETED ROUTINES (#4066 comment, owner item 12). On 2026-09-22 03:27:02Z a commit of
`9191760b…`, whose Hevy copy had been deleted in the app, came back as "Hevy rejected the
routine — HTTP 404", naming neither id nor the cause. `deleted_routine_error` turns a 404 on
the update branch into `HEVY_ROUTINE_DELETED`, naming the platform routine_id AND the Hevy id.
(Read live 2026-09-23: GET /v1/routines/<deleted id> → 404 {"error":"Routine not found"}.)

WHY training/ AND NOT mcp/: the MCP tool layer owns only the error ENVELOPE, which the caller
passes in as `err` (`mcp.utils.mcp_error`); the binding itself is plain routine-IR logic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

BINDING_ERROR_CODE = "REDTEAM_BINDING"
DELETED_ERROR_CODE = "HEVY_ROUTINE_DELETED"
OVERRIDE_ARG = "owner_override_redteam"
REASON_ARG = "override_reason"


def _norm(v: Any) -> Any:
    """Canonical form for hashing: every number as a fixed-precision string, so a DynamoDB
    round trip (int -> Decimal -> float) can never move the hash of an unchanged routine."""
    if isinstance(v, bool) or v is None or isinstance(v, str):
        return v
    if isinstance(v, (int, float, Decimal)):
        return f"{float(v):.4f}"
    if isinstance(v, dict):
        return {str(k): _norm(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_norm(x) for x in v]
    return str(v)


def content_hash(ir: Any) -> str:
    """sha256 over what the compiler pushes: date, variant, exercises (sets, loads, notes) and
    branches. Not the title (compiler-rendered), not inputs_snapshot (the audit trail)."""
    from dataclasses import asdict, is_dataclass

    def dump(x: Any) -> Any:
        return asdict(x) if is_dataclass(x) and not isinstance(x, type) else x

    payload = {
        "target_date": getattr(ir, "target_date", None),
        "variant": getattr(ir, "variant", None),
        "exercises": [dump(e) for e in getattr(ir, "exercises", None) or []],
        "branches": [dump(b) for b in getattr(ir, "branches", None) or []],
    }
    return hashlib.sha256(json.dumps(_norm(payload), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def binding_for(ir: Any) -> dict[str, Any]:
    """The stamp stage 2 writes on its verdict record, AFTER its changes and notes are applied."""
    return {"routine_id": ir.routine_id, "version": int(ir.version), "content_hash": content_hash(ir)}


def _verdicted_siblings(ir: Any, lister: Any = None) -> list[str]:
    """Other routines for the same target_date that DO carry a bound stage-2 verdict. Fail-soft:
    a failed lookup is named in the list rather than read as 'there are none'."""
    try:
        if lister is None:
            from training.routine_repo import list_by_date_range as lister
        rows = lister(ir.target_date, ir.target_date)
    except Exception as e:  # noqa: BLE001
        return [f"(lookup failed: {type(e).__name__})"]
    out = []
    for r in rows or []:
        rec = (getattr(r, "inputs_snapshot", None) or {}).get("critics") or {}
        if r.routine_id != ir.routine_id and rec.get("verdicts"):
            b = rec.get("binding") or {}
            out.append(f"{r.routine_id} (v{b.get('version', '?')}, status {r.status})")
    return out


def check(ir: Any, lister: Any = None) -> dict[str, Any]:
    """{"bound": bool, "reason": code|None, "message": str}. Pure apart from the sibling lookup."""
    rec = (getattr(ir, "inputs_snapshot", None) or {}).get("critics") or {}
    b = rec.get("binding") or {}
    if not rec.get("verdicts"):
        sib = _verdicted_siblings(ir, lister)
        where = (
            f" Red-teamed routine(s) for {ir.target_date}: {', '.join(sib)}." if sib else f" No routine for {ir.target_date} carries one."
        )
        return {"bound": False, "reason": "not_red_teamed", "message": f"routine {ir.routine_id} has NO stage-2 verdict.{where}"}
    if not b.get("content_hash"):
        return {"bound": False, "reason": "unbound", "message": f"routine {ir.routine_id}'s stage-2 verdict predates binding (#4066)."}
    if b.get("routine_id") != ir.routine_id:
        return {
            "bound": False,
            "reason": "other_routine",
            "message": f"the stage-2 verdict on routine {ir.routine_id} was issued for routine {b.get('routine_id')}.",
        }
    now = content_hash(ir)
    if now != b["content_hash"]:
        return {
            "bound": False,
            "reason": "content_changed",
            "message": (
                f"routine {ir.routine_id} changed after stage 2: verdicted v{b.get('version')} hash {b['content_hash'][:12]}, "
                f"committing v{ir.version} hash {now[:12]}."
            ),
        }
    return {"bound": True, "reason": None, "message": f"bound — stage-2 verdict v{b.get('version')} hash {now[:12]} matches (#4066)"}


def preflight(ir: Any, args: dict[str, Any], err: Any, lister: Any = None) -> tuple[dict[str, Any] | None, str, list[str]]:
    """(refusal | None, status line for the result, warnings). Stamps an override. `err` is the
    caller's error-envelope builder (message, error_code=..., detail=...)."""
    verdict = check(ir, lister)
    if verdict["bound"]:
        return None, verdict["message"], []
    override = args.get(OVERRIDE_ARG) is True or str(args.get(OVERRIDE_ARG)).lower() == "true"
    reason = str(args.get(REASON_ARG) or "").strip()
    if not override:
        return (
            err(
                f"Refusing to commit — not the red-teamed routine (#4066): {verdict['message']} Run plan_next_session with "
                f"routine_id={ir.routine_id} (stage 2) and commit what it verdicts, or pass {OVERRIDE_ARG}=true with "
                f"{REASON_ARG} in the owner's words.",
                error_code=BINDING_ERROR_CODE,
                detail=verdict,
            ),
            "",
            [],
        )
    if not reason:
        return err(f"{OVERRIDE_ARG}=true requires a non-empty {REASON_ARG} (#4066).", error_code="MISSING_ARG"), "", []
    stamp = {"overridden": True, "reason": reason, "binding_reason": verdict["reason"], "at": datetime.now(timezone.utc).isoformat()}
    ir.inputs_snapshot = {**(getattr(ir, "inputs_snapshot", None) or {}), "redteam_binding": stamp}
    warn = f"OWNER OVERRIDE (#4066): committed WITHOUT a matching stage-2 verdict — {verdict['message']} Reason: {reason!r}"
    return None, warn, [warn]


def deleted_routine_error(status: int, body_text: str, ir: Any, took_update_branch: bool, err: Any) -> dict[str, Any] | None:
    """A 404 on the update branch means Hevy no longer holds the routine — say so, naming both ids."""
    if status != 404 or not took_update_branch:
        return None
    return err(
        f"Refusing to report success — routine_id={ir.routine_id} points at Hevy routine {ir.hevy_routine_id}, which Hevy "
        f"no longer holds (HTTP 404: {body_text[:200] or 'empty body'}) — it was deleted in the app. Nothing was written. "
        "Draft a new routine (draft_custom), red-team it (plan_next_session with routine_id), then commit that.",
        error_code=DELETED_ERROR_CODE,
    )
