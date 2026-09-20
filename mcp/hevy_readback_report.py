"""
hevy_readback_report.py — the prescribed-vs-performed readbacks (#412, #3714, #3928).

`training.stall_detector` is the pure core: session points in, verdict out, no I/O. This
is the half that has to go and GET the two things it needs — what was performed (Hevy
`/v1/workouts`) and what was PRESCRIBED for each of those days (the ROUTINE# IR) — and
pair them per session.

It lives in its own module for the reason `mcp/hevy_routine_commit_report.py` does: at the
time of writing `mcp/tools_hevy_routine.py` measures 994 logical lines against the #1665
ratchet's 1,000-line hard ceiling. The ratchet's own instruction is *extract, don't raise
the cap* — so the tool file gains an import and a dispatch row, and the work lands here.

THE ONE RULE THIS FILE ENFORCES BY SHAPE
----------------------------------------
Every session point it builds carries its prescription or explicitly carries None. There
is no path that hands the detector a performed-only series while quietly implying a plan
existed: an unmatched workout, an ambiguous day (two routines pushed, neither a confident
match) and a movement performed off-plan all arrive as `prescribed_* = None`, which is
what makes the detector refuse to call a stall rather than guess (ADR-104).

READ-ONLY. It resolves movement→template through `hevy_template_cache.peek_template_id`,
not `resolve_movement`, because the latter writes a hint promotion back to S3 and a report
must never mutate `config/` to answer a question.
"""

from __future__ import annotations

import logging
from typing import Any

from common.pacific_time import pacific_date_of  # #2798: a Hevy start_time is a UTC instant; its DAY is Pacific

from mcp.utils import mcp_error

logger = logging.getLogger("hevy_readback_report")

PAGE_SIZE = 10  # Hevy's own /v1/workouts page cap
MAX_PAGES = 5  # ≤50 workouts walked — bounded I/O, never an open-ended crawl
DEFAULT_SESSIONS = 6
MIN_SESSIONS = 3
MAX_SESSIONS = 20


def _template_map_for(ir: Any) -> dict[str, str]:
    """movement_key → Hevy template id for one IR, read-only (see module docstring)."""
    from training.hevy_template_cache import peek_template_id

    out: dict[str, str] = {}
    for ex in getattr(ir, "exercises", []) or []:
        key = getattr(ex, "movement_key", "") or ""
        try:
            tid = peek_template_id(key)
        except Exception as e:  # noqa: BLE001 — an unresolvable movement is a None, not a 500
            logger.warning("template peek failed for %s (non-fatal): %s", key, e)
            tid = None
        if tid:
            out[key] = tid
    return out


def _prescription_for(workout: dict[str, Any]) -> tuple[Any | None, str | None]:
    """The routine IR that was pushed for this workout, or (None, None).

    Two tiers, mirroring `health.adherence_calc.derive_adherence`: the exact reverse
    lookup on the Hevy routine id the workout was started from, then the single routine
    pushed for that Pacific day. A day with two pushed routines is DELIBERATELY not
    resolved — "we don't know which plan this was" is reported as no prescription, and
    the detector then cannot call a stall on it.
    """
    from training import routine_repo

    try:
        hevy_rid = str(workout.get("routine_id") or "").strip()
        if hevy_rid:
            rid = routine_repo.lookup_routine_id(hevy_rid)
            if rid:
                ir = routine_repo.get_current(rid)
                if ir:
                    return ir, "hevy_routine_id"
        pac = pacific_date_of(workout.get("start_time"))
        if pac:
            candidates = routine_repo.list_by_date_range(pac, pac)
            if len(candidates) == 1:
                return candidates[0], "date_single"
            if len(candidates) > 1:
                return None, "ambiguous"
    except Exception as e:  # noqa: BLE001 — a missing plan is a finding, never an error
        logger.warning("prescription lookup failed (non-fatal): %s", e)
    return None, None


def sets_by_template(workout: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    """One performed workout → {Hevy template id: its performed sets}.

    THE ONE PLACE in this feature that reads the Hevy wire key
    (`tests/test_hevy_compiler_isolation.py` — "an API change touches one file"). The
    pure detector takes this mapping, never the raw payload. Both spellings are read:
    the raw `/v1/workouts` item says `exercise_template_id`, the normalized DDB record
    says `template_id`.
    """
    out: dict[str, list[dict[str, Any]]] = {}
    for ex in workout.get("exercises") or []:
        tid = str(ex.get("exercise_template_id") or ex.get("template_id") or "")
        if not tid:
            continue
        out.setdefault(tid, []).extend(ex.get("sets") or [])
    return out


def stall_check(args: dict[str, Any], *, get_workouts: Any = None) -> dict[str, Any]:
    """Prescribed-vs-performed stall check for ONE movement.

    Args: `movement_key` OR `template_id` (required), `sessions` (how many of that
    movement's most recent sessions to read; 3–20, default 6).

    `get_workouts` is a test seam — production passes nothing and the real Hevy client
    is used.
    """
    from training.stall_detector import assess_stall, diff_prescribed_vs_performed, session_point_from_diff, top_working_set

    movement_key = str(args.get("movement_key") or "").strip()
    template_id = str(args.get("template_id") or "").strip()
    if not movement_key and not template_id:
        return mcp_error("stall_check requires movement_key or template_id", error_code="MISSING_ARG")

    try:
        wanted = int(args.get("sessions") or DEFAULT_SESSIONS)
    except (TypeError, ValueError):
        wanted = DEFAULT_SESSIONS
    wanted = max(MIN_SESSIONS, min(wanted, MAX_SESSIONS))

    if not template_id:
        from training.hevy_template_cache import peek_template_id

        template_id = peek_template_id(movement_key) or ""
    if not template_id:
        return mcp_error(
            f"movement_key={movement_key!r} does not resolve to a Hevy template id — pass template_id explicitly.",
            error_code="UNRESOLVED_MOVEMENT",
        )

    if get_workouts is None:
        from training import hevy_write_client as wc

        get_workouts = wc.get_workouts

    points: list[Any] = []
    provenance: list[dict[str, Any]] = []
    for page in range(1, MAX_PAGES + 1):
        workouts = (get_workouts(page=page, page_size=PAGE_SIZE) or {}).get("workouts") or []
        if not workouts:
            break
        for w in workouts:
            grouped = sets_by_template(w)
            performed_sets = grouped.get(template_id) or []
            if not performed_sets:
                continue
            when = pacific_date_of(w.get("start_time")) or str(w.get("start_time") or "")[:10]
            ir, method = _prescription_for(w)
            row: dict[str, Any] = {}
            if ir is not None:
                diff = diff_prescribed_vs_performed(ir, grouped, _template_map_for(ir))
                for key, candidate in diff.items():
                    if str(candidate.get("template_id") or "") == template_id:
                        row = candidate
                        movement_key = movement_key or key
                        break
            if not row:
                # No plan on file for this session (unmatched, ambiguous, or the movement
                # was performed off-plan). Say so by carrying None — never by omitting it.
                top = top_working_set(performed_sets)
                row = {
                    "performed_load_kg": top["weight_kg"],
                    "performed_reps": top["reps"],
                    "performed_rpe": top["rpe"],
                    "prescribed_load_kg": None,
                    "prescribed_reps": None,
                    "match": "unreadable",
                }
            points.append(session_point_from_diff(when, row))
            provenance.append({"date": when, "prescription": method or "none", "match": row.get("match")})
            if len(points) >= wanted:
                break
        if len(points) >= wanted:
            break

    points.reverse()  # the detector reads OLDEST first
    provenance.reverse()
    verdict = assess_stall(points, movement_key=movement_key or f"tmpl:{template_id}")
    return {
        "status": "ok",
        "movement_key": movement_key or None,
        "template_id": template_id,
        "sessions_examined": len(points),
        "sessions_requested": wanted,
        "prescription_provenance": provenance,
        "stall": verdict,
    }


def action_adherence(args: dict[str, Any]) -> dict[str, Any]:
    """`manage_hevy_routine action=adherence` — one session, programmed vs performed."""
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error("adherence requires routine_id", error_code="MISSING_ARG")
    from health.adherence_calc import calculate_adherence
    from training import hevy_write_client as wc
    from training.routine_repo import get_current

    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    workouts = wc.get_workouts(page=1, page_size=10).get("workouts") or []
    performed: dict[str, Any] = {}
    for w in workouts:
        # #2798: `start_time` is a UTC instant; its DAY is Pacific (`health.adherence_calc`
        # already resolves it that way). A raw [:10] compared an evening workout to tomorrow.
        if pacific_date_of(w.get("start_time")) == ir.target_date:
            performed = w
            break
    if not performed:
        return {"status": "no_workout_for_date", "routine_id": routine_id, "target_date": ir.target_date}
    return {"status": "ok", "routine_id": routine_id, "adherence": calculate_adherence(ir, performed)}
