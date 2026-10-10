"""nightly_predraft.py — tomorrow's session, drafted and red-teamed before the evening chat (#4084).

WHY THIS EXISTS
  Across eight coaching chats (2026-09-14 → 09-22) the evening turn spent most of its length
  BUILDING tomorrow's session — stage 1, a draft, stage 2 — and the wrong calls clustered in
  that build. The owner's ask: have the draft already made and red-teamed by ~19:00 PT, so the
  chat REVIEWS a draft instead of building one.

WHAT A RUN DOES — nothing a chat turn could not already do, in the same order
  0. `sweep_expired` (#4732): ARCHIVE — never delete — the pre-draft's own uncommitted drafts whose
     day has passed, or whose day already has a committed routine of the same archetype. The owner
     usually commits his own routine in chat, so without this every night left a pair behind.
     Routines the pre-draft did not author are never touched. Fail-soft and reported as `sweep`.
  1. `scheduled_session(tomorrow)` — THE seam (below). No lifting session → the first-class
     `no_session` outcome, never a guessed one. Archetype-agnostic (full / upper / lower).
  2. Idempotency + ownership: a routine already on file for tomorrow decides the run —
     our own red-teamed pre-draft → `exists` (no-op); our own un-red-teamed pre-draft (a run
     that died mid-way) → resume at stage 2; ANY other routine (the owner drafted, or it is
     already committed / linked to Hevy) → `skipped_owner_routine`. The pre-draft never
     versions over a routine it did not author.
  3. `manage_hevy_routine draft` (`_action_draft`, called directly — never the dispatcher,
     so no action string can route this module to `commit`). Its freshness gate is honoured:
     a refusal is the outcome `blocked_stale_inputs`, never an override.
  4. Stamp `inputs_snapshot[MARKER]` on every routine the draft persisted — the ideal as
     `primary`, its floor / re-entry siblings as `sibling` (one version bump each) — BEFORE stage 2,
     because stage 2's commit binding (#4066) binds the version it writes — a stamp after it
     would un-bind the verdict.
  5. `plan_next_session(routine_id=…)` — stage 2, the four critics. Their model calls are
     gated by `budget_guard` feature `plan_critics` INSIDE stage 2 (`tools_plan._model_allowed`):
     at a paused tier the deterministic layer still runs and the record says the model did
     not. The outcome carries `model_ran` so the chat never reads a paused run as red-teamed.

WHAT A RUN NEVER DOES
  Commit. Nothing here reaches `_action_commit`, `hevy_write_client.create_routine` or
  `update_routine`; `tests/test_nightly_predraft_4084.py` pins that on the source (AST) and
  on a full run with the Hevy write client booby-trapped. Committing stays the owner's act in
  chat, after he has read the verdicts.

THE SEAM (#4110 coordination)
  `scheduled_session` is the ONE place this module learns what tomorrow's session is. Today it
  is the exact function stage 1 uses to put `constraint_block.session` on the block —
  `plan_engine._scheduled_session` over `program_structure`'s block calendar. #4110 (sessions
  follow a SEQUENCE: the next undone session is served on whatever day he trains) re-points
  THIS function, one line, and nothing else here changes. The draft itself is built by the
  generator, which reads the same calendar through its own seam — #4110 moves both.

SCHEDULE AND DEAD-MAN (the registry — `JOB` below is the one declaration)
  EventBridge `cron(0 2 * * ? *)` on the `life-platform-mcp-warmer` Lambda with the constant
  input `{"job": "nightly_predraft"}` (cdk/stacks/mcp_stack.py). EventBridge crons are fixed
  UTC, so 02:00Z is 19:00 PDT (mid-March → early November) and 18:00 PST in winter; the
  Pacific day is the same in both, so "tomorrow" is always the next PT day.
  Every run that reaches an HONEST terminal outcome (drafted, exists, no_session, skipped,
  blocked) emits `LifePlatform/HevyRoutine::PredraftOutcome{Job=nightly_predraft}` = 1 via EMF
  (stdout — no IAM). A run that FAILS emits the same series at 0 with `Outcome: failed` (#4568);
  a rule that stops firing (or a run killed before its last line) emits nothing. The alarm
  `nightly-predraft-missing` is `Sum < 1` over 24 consecutive hourly buckets with missing =
  BREACHING, so it goes red at the close of the 02:00–03:00Z bucket in BOTH cases — and the
  bucket's SampleCount tells them apart: 1 (Sum 0) is a run that crashed, 0 is a run that never
  happened. Before #4568 a crash emitted nothing and the two read the same.

THE READ SIDE
  `predraft_for(target_date)` is what `plan_next_session` stage 1 attaches as `predraft`, so
  the evening chat's first call shows the waiting draft and its verdicts before anything else.
  Writer (`_mark_draft`) and reader share `MARKER`; the round trip through the real routine IR
  serializer is the contract test.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("nightly_predraft")

MARKER = "nightly_predraft"
"""The inputs_snapshot key the writer stamps and `predraft_for` reads — one literal, both sides."""
PRIMARY = "primary"
SIBLING = "sibling"

ENGINE_VERSION = "1.0.0"

METRIC_NAMESPACE = "LifePlatform/HevyRoutine"
"""A module-level binding (not only a JOB key) so `deploy/emf_namespace_discovery.py` resolves the EMF
producer — the namespace's ledger row (`deploy/emf_namespace_ledger.py`) names this job."""

JOB: dict[str, Any] = {
    "name": "nightly_predraft",
    # the rule's constant input — mcp.handler dispatches on event["job"] == JOB["event"]["job"]
    "event": {"job": "nightly_predraft"},
    # fixed UTC (CLAUDE.md): 19:00 PDT / 18:00 PST — both on the same Pacific day
    "schedule_utc": "cron(0 2 * * ? *)",
    "function": "life-platform-mcp-warmer",
    "target_offset_days": 1,
    "metric_namespace": METRIC_NAMESPACE,
    "metric_name": "PredraftOutcome",
    "metric_dimension": {"Job": "nightly_predraft"},
    "deadman_alarm": "nightly-predraft-missing",
    # 24 consecutive empty hourly buckets: red at the close of the 02:00-03:00Z bucket the
    # run should have landed in — i.e. "no pre-draft by 03:00Z" (the issue's box).
    "deadman_period_s": 3600,
    "deadman_periods": 24,
}

# Terminal outcomes. Each is an HONEST answer, so each emits the dead-man datapoint.
DRAFTED = "drafted"
EXISTS = "exists"
NO_SESSION = "no_session"
SKIPPED_OWNER_ROUTINE = "skipped_owner_routine"
BLOCKED_STALE_INPUTS = "blocked_stale_inputs"
HONEST_OUTCOMES = (DRAFTED, EXISTS, NO_SESSION, SKIPPED_OWNER_ROUTINE, BLOCKED_STALE_INPUTS)
FAILED = "failed"  # NOT honest-terminal: emits PredraftOutcome = 0, so the dead-man (Sum < 1) still fires
SWEEP_LOOKBACK_DAYS = 120
"""#4732: how far back the expired-draft sweep looks (the orphan census's own lookback), floored at the genesis."""
SWEEP_LIMIT = 500
"""#4732: the index Query page the sweep reads — the same bound `routine_repo.stale_draft_census` uses."""
GENERATOR_VARIANTS = ("ideal", "floor", "re_entry")
"""The variants `routine_generator` persists for a lifting session — with the date and the archetype,
each is one routine PARTITION (`_new_routine_id`, #3115)."""


# ── THE seam ────────────────────────────────────────────────────────────────────────────
def _block_record(target_date: str) -> list[dict[str, Any]] | None:
    """Stage 1's completed-session record since the block start (`plan_hevy_windows._block_workouts`).
    A read that RAISES is None — the session then says `sequence_unreadable` by name."""
    from mcp.plan_hevy_windows import _block_workouts

    try:
        return _block_workouts(target_date)
    except Exception as e:  # noqa: BLE001 — named on the session as sequence_unreadable, never a silent session 1
        logger.warning(f"nightly predraft: the Hevy record since the block start was not read ({type(e).__name__}: {e})")
        return None


def _session_from(target_date: str, block_workouts: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    from training import plan_engine

    from mcp.plan_helpers import _catalog_and_ceiling

    catalog, ceiling = _catalog_and_ceiling()
    return plan_engine._scheduled_session(target_date, catalog, ceiling, block_workouts)


def scheduled_session(target_date: str) -> dict[str, Any] | None:
    """The session the program serves on `target_date` — the SAME function stage 1 uses (#4064).

    #4110 / #4147 (PR #4120 — v0.4 Upper/Lower, ORDER-BASED: the next undone session in the
    sequence is served on whatever day he trains): the session picker is handed the same
    completed-session record stage 1 passes (`plan_hevy_windows._block_workouts`, re-exported as
    `tools_plan._block_workouts`). A read that RAISES hands it None, so the session says
    `sequence_unreadable` by name and carries no prescription — the first-class `no_session`
    outcome, never a silent session 1. Nothing here assumes a weekday grid or an archetype: a
    session is draftable iff it carries a `prescription` (`is_lifting_session`), whatever its
    archetype (`upper`, `lower`; `full` for v0.3 history).
    """
    return _session_from(target_date, _block_record(target_date))


def is_lifting_session(session: dict[str, Any] | None) -> bool:
    """A draftable session is one the program prescribes lifts for — nothing else is guessed."""
    return bool((session or {}).get("prescription"))


# ── registry reads ──────────────────────────────────────────────────────────────────────
def _routines_for(target_date: str) -> list[Any]:
    from training.routine_repo import list_by_date_range

    return list_by_date_range(target_date, target_date)


def _is_ours(ir: Any) -> bool:
    return bool((getattr(ir, "inputs_snapshot", None) or {}).get(MARKER))


def _is_primary(ir: Any) -> bool:
    """The routine the pre-draft red-teams — never one of the draft's floor / re-entry siblings."""
    return ((getattr(ir, "inputs_snapshot", None) or {}).get(MARKER) or {}).get("role") == PRIMARY


def _critics(ir: Any) -> dict[str, Any]:
    return (getattr(ir, "inputs_snapshot", None) or {}).get("critics") or {}


def _red_teamed(ir: Any) -> bool:
    rec = _critics(ir)
    return bool(rec.get("verdicts") is not None and rec.get("binding"))


def _is_owner_routine(ir: Any) -> bool:
    """Any live routine the pre-draft did not author — including a committed one."""
    if getattr(ir, "status", None) == "archived":
        return False
    return not _is_ours(ir) or bool(getattr(ir, "hevy_routine_id", None)) or getattr(ir, "status", None) == "active"


def _routine_role(ir: Any) -> tuple[str, str | None]:
    """(archetype, session_role or None) of a routine. The role is the generator's calendar stamp or
    the pre-draft marker's; a chat-authored routine carries only its archetype."""
    snap = getattr(ir, "inputs_snapshot", None) or {}
    role = (snap.get("calendar") or {}).get("session_role") or (snap.get(MARKER) or {}).get("session_role")
    return str(getattr(ir, "archetype", "") or "").lower(), role


def _performed_hevy_ids(block_workouts: list[dict[str, Any]] | None) -> set[str]:
    """Hevy routine ids of the loaded sessions already performed since the block start."""
    from training import training_streaks

    return {
        str(w.get("hevy_routine_id"))
        for w in block_workouts or []
        if w.get("hevy_routine_id") and not w.get("tombstone") and training_streaks.is_loaded_session(w)
    }


def _blocks_served_session(ir: Any, session: dict[str, Any], performed: set[str] | frozenset[str]) -> bool:
    """#4110/#4147: an owner routine blocks the pre-draft only when it IS the session the sequence
    now serves — the same role (or, for a chat-authored routine with no role stamp, the same
    archetype) — AND it has not been performed. The date alone decides nothing: under an ORDER a
    routine stamped for tomorrow can be done today (the committed Lower-heavy stamped 09-25,
    performed 09-24), and tomorrow's served session is then a different one. A superseded v0.3
    `full` draft is never the served v0.4 session."""
    if not _is_owner_routine(ir):
        return False
    hid = str(getattr(ir, "hevy_routine_id", None) or "")
    if hid and hid in performed:
        return False
    archetype, role = _routine_role(ir)
    if role:
        return role == session.get("session_role")
    return bool(archetype) and archetype == str(session.get("archetype") or "").lower()


# ── write side ──────────────────────────────────────────────────────────────────────────
def _draft_partitions(target_date: str, session: dict[str, Any]) -> set[str]:
    """The routine ids a draft of `session` on `target_date` lands on. Ids are SEMANTIC since #3115
    — `sha256(target_date, archetype, variant)` — so a draft does not mint a routine: it becomes the
    next VERSION of whatever already sits on that partition (`routine_repo.draft_versioned`)."""
    from training.routine_generator import _new_routine_id

    archetype = str(session.get("archetype") or "").lower()
    return {_new_routine_id(target_date, archetype, variant) for variant in GENERATOR_VARIANTS}


def _mark_draft(
    target_date: str,
    primary_id: str,
    session: dict[str, Any],
    run_at: str,
    before: dict[str, int] | None = None,
    owner_ids: frozenset[str] = frozenset(),
) -> None:
    """Stamp the marker on EVERY routine the draft just persisted (ideal + its floor / re-entry
    siblings — `_action_draft` writes all of them), each as its next version, before stage 2 (see
    module doc). Only `primary_id` is red-teamed; the siblings are marked so a re-run does not read
    them as the owner's routines.

    WHICH routines the draft persisted is read off the VERSION, never the id (#4568). `before` is
    {routine_id: version} for the date as it stood before the draft: a routine the draft wrote is one
    that is new OR whose version moved. The earlier rule — "any id already on the date is not ours"
    (#4110) — was wrong the first night a draft landed on an existing partition: ids are derived
    from (date, archetype, variant), so a draft for a date that already held an ARCHIVED lower/ideal
    became that routine's next version, was skipped as pre-existing, and the run died with nothing
    marked (2026-10-03: 8409f757… v2 archived → v3 drafted → "not readable back").

    `owner_ids` are the live routines the pre-draft did not author. A draft that moved one of them
    is refused here by name — `run` skips before drafting when a partition is the owner's, so this
    is the backstop for an id recipe that drifts from `_draft_partitions`."""
    from training.routine_repo import put_versioned

    before = before or {}
    written = [
        ir
        for ir in _routines_for(target_date)
        if getattr(ir, "status", None) != "archived" and (ir.routine_id not in before or int(ir.version) != int(before[ir.routine_id]))
    ]
    trampled = sorted(ir.routine_id for ir in written if ir.routine_id in owner_ids)
    if trampled:
        raise RuntimeError(f"the draft for {target_date} versioned over routine(s) the pre-draft did not author: {trampled}")
    if primary_id not in {ir.routine_id for ir in written}:
        raise LookupError(f"drafted routine {primary_id} is not readable back for {target_date}")
    for ir in written:
        ir.inputs_snapshot = {
            **(getattr(ir, "inputs_snapshot", None) or {}),
            MARKER: {
                "engine": ENGINE_VERSION,
                "role": PRIMARY if ir.routine_id == primary_id else SIBLING,
                "primary_routine_id": primary_id,
                "drafted_at": run_at,
                "session_label": session.get("label"),
                "session_role": session.get("session_role"),
                "optional": bool(session.get("optional")),
                "seam": "plan_engine._scheduled_session",
            },
        }
        ir.parent_version = ir.version
        ir.version = int(ir.version) + 1
        put_versioned(ir)


def _draft(target_date: str) -> dict[str, Any]:
    """`manage_hevy_routine draft` for the date — the action function itself, never the dispatcher."""
    from mcp.tools_hevy_routine import _action_draft

    return _action_draft({"target_date": target_date})


def _stage_2(target_date: str, routine_id: str) -> dict[str, Any]:
    from mcp.tools_plan import tool_plan_next_session

    return tool_plan_next_session({"target_date": target_date, "routine_id": routine_id})


def _critics_summary(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "model_ran": rec.get("model_ran"),
        "model_paused_reason": rec.get("model_paused_reason"),
        "veto": rec.get("veto"),
        "ran_at": rec.get("ran_at"),
        "verdicts": [{"critic": v.get("critic"), "verdict": v.get("verdict")} for v in rec.get("verdicts") or []],
        "recheck_passed": (rec.get("recheck") or {}).get("passed"),
    }


# ── #4732: the pre-draft archives what it left behind ───────────────────────────────────
# Every night drafts a primary + a floor sibling for tomorrow. In chat the owner reviews it and
# usually commits a DIFFERENT routine (his own draft) for the session, so the pre-draft's pair
# stays `draft` forever — nothing commits it and nothing archived it. The routine repo on
# 2026-10-09 held 19 live-cycle drafts older than 7 days; 14 of them were these marked pairs
# (09-26 → 10-02), which is the ~+2/day the `data:orphan_routine_drafts` census counted.
def _committed(ir: Any) -> bool:
    return bool(getattr(ir, "hevy_routine_id", None)) or getattr(ir, "status", None) == "active"


def _sweep_reason(ir: Any, today: str, on_date: list[Any]) -> str | None:
    """Why the pre-draft's OWN uncommitted draft is dead, or None to leave it.

    Only a routine the pre-draft stamped (`_is_ours`), still `draft`, never pushed to Hevy. Expired:
    its target day is before `today`. Superseded: a committed routine of the same archetype is on its
    date (the owner committed a session for that day — his own, or this primary, for a sibling)."""
    if not _is_ours(ir) or getattr(ir, "status", None) != "draft" or getattr(ir, "hevy_routine_id", None):
        return None
    day = str(getattr(ir, "target_date", "") or "")
    if not day or day > today:
        return None
    if day < today:
        return "expired"
    archetype = str(getattr(ir, "archetype", "") or "").lower()
    for other in on_date:
        if other.routine_id != ir.routine_id and _committed(other) and str(getattr(other, "archetype", "") or "").lower() == archetype:
            return "superseded"
    return None


def sweep_expired(today: str, run_at: str, genesis: str | None = None) -> dict[str, Any]:
    """Archive the pre-draft's own expired / superseded drafts — NEVER delete (#4732).

    The archive is `manage_hevy_routine archive`'s local-only branch (`_action_archive` for a routine
    never pushed to Hevy): status `archived` as the routine's next version, so every prior version stays
    readable. A routine the pre-draft did not author is never touched here — that stays the owner's call.
    Never targets a day after `today`, so tonight's draft (tomorrow) is never in reach."""
    from common.pacific_time import shift_day_key
    from training.routine_repo import list_by_date_range, put_versioned

    if genesis is None:
        from training.routine_repo import _live_genesis

        genesis = _live_genesis()
    start = shift_day_key(today, -SWEEP_LOOKBACK_DAYS)
    if genesis and genesis > start:
        start = genesis  # a pre-genesis draft is history, never this sweep's business
    rows = list_by_date_range(start, today, limit=SWEEP_LIMIT)
    by_date: dict[str, list[Any]] = {}
    for ir in rows:
        by_date.setdefault(str(ir.target_date), []).append(ir)
    archived: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for ir in rows:
        reason = _sweep_reason(ir, today, by_date.get(str(ir.target_date), []))
        if not reason:
            continue
        snap = dict(getattr(ir, "inputs_snapshot", None) or {})
        snap[MARKER] = {**(snap.get(MARKER) or {}), "archived": {"at": run_at, "reason": reason, "by": "nightly_predraft.sweep_expired"}}
        ir.inputs_snapshot = snap
        ir.status = "archived"
        ir.parent_version = int(ir.version)
        ir.version = int(ir.version) + 1
        try:
            put_versioned(ir)
        except Exception as e:  # noqa: BLE001 — one refused write never stops the rest; it is named
            errors.append({"routine_id": ir.routine_id, "error": f"{type(e).__name__}: {e}"[:200]})
            continue
        archived.append({"routine_id": ir.routine_id, "target_date": ir.target_date, "reason": reason})
    return {"window": {"start": start, "end": today}, "scanned": len(rows), "archived": archived, "errors": errors}


def run(target_date: str | None = None) -> dict[str, Any]:
    """One pre-draft for `target_date` (default: tomorrow, Pacific). Never commits."""
    from common.pacific_time import pacific_today, shift_day_key

    target = target_date or shift_day_key(pacific_today(), JOB["target_offset_days"])
    run_at = datetime.now(timezone.utc).isoformat()
    out: dict[str, Any] = {"job": JOB["name"], "target_date": target, "run_at": run_at, "engine": ENGINE_VERSION}
    # #4732: archive last nights' leftovers first. "Today" is the run's own day (target − offset), so a
    # back-dated run never reaches past its own target. Fail-soft: a sweep error is named, never fatal.
    try:
        out["sweep"] = sweep_expired(shift_day_key(target, -JOB["target_offset_days"]), run_at)
    except Exception as e:  # noqa: BLE001 — the draft still runs; the sweep's failure is on the record
        logger.warning(f"nightly predraft: the expired-draft sweep failed ({type(e).__name__}: {e})")
        out["sweep"] = {"error": f"{type(e).__name__}: {e}"[:300]}

    session = scheduled_session(target) or {}
    # #4161: the week counter's basis (sessions AND days) and the deload ride with the pre-draft too
    keys = ("label", "archetype", "session_role", "optional", "source", "week", "deload", "week_basis", "advance_blocked_by", "note")
    out["session"] = {k: session.get(k) for k in keys}
    if not is_lifting_session(session):
        out.update(
            outcome=NO_SESSION,
            reason=f"the program serves no lifting session on {target} ({session.get('label') or session.get('note') or 'no session returned'})",
        )
        return out

    existing = _routines_for(target)
    mine = [r for r in existing if _is_primary(r) and getattr(r, "status", None) != "archived"]
    owners = [r for r in existing if _blocks_served_session(r, session, frozenset())]
    if owners:  # the served role is on file: read the record once to drop any already PERFORMED
        performed = _performed_hevy_ids(_block_record(target))
        owners = [r for r in owners if _blocks_served_session(r, session, performed)]
    if owners:
        out.update(
            outcome=SKIPPED_OWNER_ROUTINE,
            reason=(
                f"a routine the pre-draft did not author is already on file for this date AND is the session the sequence serves "
                f"({session.get('session_role')}, not yet performed) — it is never versioned over"
            ),
            routines=[{"routine_id": r.routine_id, "status": r.status, "hevy_linked": bool(r.hevy_routine_id)} for r in owners],
        )
        return out
    others = [r for r in existing if _is_owner_routine(r)]
    if others:  # on file for the date but NOT the served session — named, never blocking, never touched
        out["other_routines_on_date"] = [
            {"routine_id": r.routine_id, "archetype": _routine_role(r)[0], "session_role": _routine_role(r)[1]} for r in others
        ]
    done = [r for r in mine if _red_teamed(r)]
    if done:
        r = done[0]
        out.update(outcome=EXISTS, routine_id=r.routine_id, routine_version=int(r.version), critics=_critics_summary(_critics(r)))
        return out

    if mine:  # a run that died between the draft and stage 2 — resume, never redraft
        routine_id = mine[0].routine_id
        out["resumed"] = True
    else:
        # #4568: a draft lands on the (date, archetype, variant) partition. An ARCHIVED routine there
        # is simply re-drafted as its next version; a LIVE one the pre-draft did not author would be
        # versioned over (and its Hevy link carried), so that is a skip — before anything is written.
        taken = _draft_partitions(target, session)
        in_the_way = [r for r in others if r.routine_id in taken]
        if in_the_way:
            out.update(
                outcome=SKIPPED_OWNER_ROUTINE,
                reason=(
                    f"a live routine the pre-draft did not author already holds the partition a {session.get('archetype')} draft for "
                    "this date is written to (same date, archetype and variant, a different session) — drafting would version over "
                    "it, so nothing is drafted; archive it or draft in chat"
                ),
                routines=[{"routine_id": r.routine_id, "status": r.status, "hevy_linked": bool(r.hevy_routine_id)} for r in in_the_way],
            )
            return out
        drafted = _draft(target)
        if drafted.get("status") != "drafted" or not drafted.get("ideal_routine_id"):
            out.update(
                outcome=BLOCKED_STALE_INPUTS if drafted.get("status") == "blocked_stale_inputs" else FAILED,
                reason=drafted.get("note") or drafted.get("error") or f"draft returned status {drafted.get('status')!r}",
                gaps=drafted.get("gaps"),
            )
            return out
        routine_id = drafted["ideal_routine_id"]
        _mark_draft(
            target,
            routine_id,
            session,
            run_at,
            {r.routine_id: int(r.version) for r in existing},
            frozenset(r.routine_id for r in others),
        )

    res = _stage_2(target, routine_id)
    rec = (res or {}).get("critics") or {}
    if not rec:
        out.update(
            outcome=FAILED, routine_id=routine_id, reason=f"stage 2 returned no critics record: {str((res or {}).get('error'))[:200]}"
        )
        return out
    out.update(
        outcome=DRAFTED,
        routine_id=routine_id,
        routine_version=rec.get("routine_version"),
        critics=_critics_summary(rec),
        committed=False,
    )
    return out


# ── the dead-man datapoint ──────────────────────────────────────────────────────────────
def emf_line(outcome: str) -> str:
    """The EMF record for a run's outcome: 1 for an honest terminal outcome, 0 for anything else.

    #4568: a failed run used to emit NOTHING, so the dead-man could not tell a run that crashed
    from a rule that never fired. It now emits the same series at 0 — the alarm is `Sum < 1`, so a
    0 keeps the bucket breaching exactly as absence did, while the datapoint (SampleCount 1) and its
    `Outcome` property say the run happened and failed."""
    dims = JOB["metric_dimension"]
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": METRIC_NAMESPACE,
                        "Dimensions": [sorted(dims)],
                        "Metrics": [{"Name": JOB["metric_name"], "Unit": "Count"}],
                    }
                ],
            },
            **dims,
            JOB["metric_name"]: 1 if outcome in HONEST_OUTCOMES else 0,
            "Outcome": outcome,
        }
    )


def lambda_entry(event: dict[str, Any]) -> dict[str, Any]:
    """The scheduled entry. Never raises: a failure is logged with its class and emits the
    datapoint at 0 (#4568), so the dead-man — not a misattributed warmer Errors alarm — reports it."""
    try:
        result = run((event or {}).get("target_date"))
    except Exception as e:  # noqa: BLE001 — reported by name; the dead-man reads the 0
        logger.exception("nightly pre-draft failed")
        result = {"job": JOB["name"], "outcome": FAILED, "error": f"{type(e).__name__}: {e}"[:300]}
    print(emf_line(result.get("outcome") or FAILED))
    logger.info("NIGHTLY_PREDRAFT %s", json.dumps(result, default=str)[:4000])
    return {"statusCode": 200, "body": json.dumps(result, default=str), "headers": {"Content-Type": "application/json"}}


# ── read side: what plan_next_session stage 1 shows the evening chat ────────────────────
def predraft_for(target_date: str) -> dict[str, Any]:
    """The nightly pre-draft waiting for `target_date`, or an honest statement that none is."""
    mine = [r for r in _routines_for(target_date) if _is_primary(r) and getattr(r, "status", None) != "archived"]
    if not mine:
        return {
            "status": "none",
            "target_date": target_date,
            "detail": (
                f"no nightly pre-draft on file for {target_date} — either no lifting session is served that day, a routine "
                "already existed, the draft was refused on stale inputs, or the run did not happen (the "
                f"`{JOB['deadman_alarm']}` alarm covers the last). Build the session as usual."
            ),
        }
    r = mine[0]
    rec = _critics(r)
    base = {"target_date": target_date, "routine_id": r.routine_id, "routine_version": int(r.version), "status_in_repo": r.status}
    base["drafted_at"] = ((r.inputs_snapshot or {}).get(MARKER) or {}).get("drafted_at")
    if not _red_teamed(r):
        return {**base, "status": "drafted_not_red_teamed", "how_to_use": "Run stage 2 on this routine_id before anything else."}
    summary = _critics_summary(rec)
    how = (
        "A draft for this date was built and red-teamed overnight — REVIEW it rather than building a new one: "
        "manage_hevy_routine dry_run with this routine_id shows the body; the critics' verdicts are below. "
        "It is NOT committed; commit stays Matthew's call."
    )
    if not summary.get("model_ran"):
        how += " The critics' MODEL did not run (see model_paused_reason) — the deterministic layer only; say so."
    if summary.get("veto"):
        how += " A veto stands: redraft or re-run stage 2 with veto_override before any commit."
    return {**base, "status": "ready", "critics": summary, "how_to_use": how}


def attach_to_stage_1(out: dict[str, Any], target_date: str) -> None:
    """Put `predraft` on a stage-1 payload and, when a red-teamed draft is waiting, lead `how_to_use`
    with it. A failed read is reported `unreadable`, never as "no pre-draft" (ADR-104)."""
    try:
        pre = predraft_for(target_date)
    except Exception as e:  # noqa: BLE001 — stage 1 must still answer; the read's failure is named
        pre = {"status": "unreadable", "target_date": target_date, "error": f"{type(e).__name__}: {e}"[:200]}
    out["predraft"] = pre
    if pre.get("status") == "ready":
        out["how_to_use"] = pre["how_to_use"] + " " + str(out.get("how_to_use") or "")
