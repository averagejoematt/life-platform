"""plan_stage2_run.py — stage 2 of `plan_next_session` (the red team, #3752), verdict written FIRST (#5781).

WHY THE ORDER. Until #5781 stage 2 assembled everything — the four critics' deterministic verdicts, their model
replies, the applied changes — and wrote it in ONE step at the end, gated on the #5313 write deadline
(`plan_call_scope.STAGE_2_WRITE_DEADLINE_SECS`, below the MCP cap `mcp.handler.TOOL_TIMEOUT_SECS`). On 2026-11-11 a
`draft_custom` routine (f4569682) missed that deadline three runs in a row (27.2 / 27.8 / 28.1 s): nothing was
stored and every commit was refused. A read-only profile of the same call (laptop, live reads, every non-read call
refused, model off) put the time in the stage-1 reads (~32 s there, ~420 DynamoDB queries) and, AFTER the critics'
model wait, `critic_set_floors` — a draft_custom routine carries no stored generator floors, so the commit gate's
floors are re-derived from history (~3.5 s there) — then the thread row. The model step itself was cut at its 1 s
floor; the JSON response (~300 KB) serialises in ~10 ms.

THE ORDER NOW, each phase timed on the result (`timing_ms`, stable keys):

  1. `reads`          stage 1 — every reader, up to the moment stage 2 starts;
  2. `critics`        the commit gate's floors (the one read stage 2 makes) and the DETERMINISTIC verdicts, applied;
  3. `verdict_write`  that record, bound to the routine, STORED — before any model call, so a slow or late model
                      step can never cost the verdicts. Past the deadline nothing is written (the #5313 guarantee);
  4. `narration`      the critics' model calls (bounded by the time left), the reconciled verdicts re-applied to the
                      coach's draft and, if still before the deadline, stored on top as the next version. A model
                      step that ends late leaves the deterministic record standing — `written` stays true and
                      `next` says the model replies were not stored. With under `MODEL_MIN_SECS` left it is skipped;
  5. `thread_write`   the coach-thread row, once, for whichever record landed — skipped (and named) past the deadline;
  6. `response_build` the notes preview and the result.

A paused model tier (or a dry run, #4076) has no narration step, so it keeps the single write it always had.

The names the tests patch live on `mcp.tools_plan` (`_model_allowed`, `_write_thread`, `_record_override_correction`,
`_place_block_on_first_exercise`, `pacific_today`) and are read through that module at call time.
"""

from __future__ import annotations

import copy
import json
import time
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Callable

from training.commit_binding import binding_for

from mcp import plan_call_scope, plan_stage2_writes

# A model step with less than this left before the write deadline is not started: on 2026-11-11 all four critics hit
# the 1 s floor and the deterministic layer decided every one anyway — a spend and a second write for nothing.
MODEL_MIN_SECS = 3.0
TIMING_KEYS = ("reads", "critics", "verdict_write", "narration", "thread_write", "response_build")
CHECKPOINT_REASON = "stored before the model step (#5781): deterministic layer only, unless a later version carries the model replies"


class _Clock:
    """Per-phase milliseconds on the plan call's own clock (`plan_call_scope.elapsed_secs`, wall time outside one)."""

    def __init__(self) -> None:
        e = plan_call_scope.elapsed_secs()
        self._t0 = time.monotonic() - (e or 0.0)
        self.ms = {k: 0 for k in TIMING_KEYS}
        self.ms["reads"] = round((e or 0.0) * 1000)
        self._mark = time.monotonic()

    def lap(self, phase: str) -> None:
        now = time.monotonic()
        self.ms[phase] += round((now - self._mark) * 1000)
        self._mark = now

    def result(self) -> dict[str, int]:
        return {**self.ms, "total": round((time.monotonic() - self._t0) * 1000)}


def _once(record: Callable[[dict[str, Any], str, str], str]) -> Callable[[dict[str, Any], str, str], str]:
    """The override ledger write, once per (item, words, class) across both passes — the narration pass re-applies the
    owner's override to fresh verdicts and must not log his words a second time."""
    seen: dict[str, str] = {}

    def wrapped(item_ref: dict[str, Any], words: str, error_class: str) -> str:
        key = json.dumps([item_ref, words, error_class], sort_keys=True, default=str)
        if key not in seen:
            seen[key] = record(item_ref, words, error_class)
        return seen[key]

    return wrapped


def packet_builder(block, reference, evidence, protein_missed, protein_measured, dismissals) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """`draft -> {critic: packet}` over the already-fetched evidence — no model, no I/O (`critics.recheck` reuses it)."""
    from coach import critics

    from mcp import tools_plan as tp

    by_idx = {e["idx"]: e for e in evidence["exercises"]}
    rate, provisional = tp._loss_rate_of(reference, tp._block_rate(block))

    def build(draft: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            "muscle_defense": critics.build_muscle_defense_packet(
                draft,
                anchor_trends={i: e for i, e in by_idx.items() if e.get("drop_pct") is not None},
                program_week=block.get("program_week"),
                protein_days_missed_7d=protein_missed,
                protein_days_measured_7d=protein_measured,
            ),
            "joints_tendons": critics.build_joints_packet(
                draft,
                pain_by_idx={i: e for i, e in by_idx.items() if "pain_flag_any" in e},
                days_since_by_idx={i: e.get("days_since") for i, e in by_idx.items()},
                loaded_lifting_streak=evidence.get("loaded_lifting_streak"),
                pain_layer_status=evidence.get("pain_layer_status"),
                dismissals=dismissals,  # #4036 — the owner's own override of a flag instance
                stale_by_idx={i: e["stale"] for i, e in by_idx.items() if e.get("stale")},  # #4161: the cap scales with the gap
                fatigue=evidence.get("fatigue"),  # #4161: performance / readiness, not a loaded-day count
                recent_aerobic=block.get("recent_aerobic"),  # #4387: what his legs did in the last 48-72 h
            ),
            "rate_advocate": critics.build_rate_advocate_packet(
                draft,
                tripwires=block.get("tripwires"),
                walking=block.get("walking"),
                rate_target=block.get("rate_target"),
                # #4068/#5001: THE loss rate — the constraint block's `shared_quantities.loss_rate_lb_wk` first, the SAME
                # quantity its rate_ceiling row was evaluated over, so the advocate's rate and its tripwire never disagree.
                current_rate_lb_wk=rate,
                rate_provisional=provisional,
                lifting_sessions_7d=evidence.get("lifting_sessions_7d"),
            ),
            "blueprint_historian": critics.build_historian_packet(
                draft, reference=reference, weeks_in_block=evidence.get("weeks_in_block")
            ),
        }

    return build


class _Run:
    """One stage-2 run's fixed inputs: the routine, the coach's draft as critiqued, the packets, the floors."""

    def __init__(self, ir, block, build, target_date, overrides, recorder) -> None:
        from coach import critics

        from mcp import tools_plan as tp
        from mcp.hevy_prescription_gate import critic_set_floors

        # LIVE FINDING 2026-09-20 (routine 73bc228c v5 -> v6): a re-run on an already-critiqued routine compounded the
        # joints critic's cut (22 -> 18 -> 14). Stage 2 re-EVALUATES the coach's draft, never cuts its own output: restore
        # the pre-critics exercise list first, and keep that snapshot on the record so the next run can do the same.
        prior = (getattr(ir, "inputs_snapshot", None) or {}).get("critics") or {}
        self.ir, self.build, self.target_date, self.overrides, self.recorder = ir, build, target_date, overrides or [], recorder
        self.draft_exercises = prior.get("draft_exercises") or None
        self.restore()
        self.draft_exercises = [asdict(e) for e in ir.exercises]
        self.draft = critics.draft_summary(ir)
        self.packets = tp.critics_with_charter(build(self.draft), target_date, block)  # #5071: the one context
        # #5781: the commit gate's floors, read ONCE and BEFORE any model call — a draft_custom routine re-derives them
        # from history (~3.5 s on the 2026-11-11 profile), which used to sit between the model wait and the write.
        self.floors = critic_set_floors(ir)  # #4149: a critic change is held to the commit gate's floor

    def restore(self) -> None:
        if self.draft_exercises:
            from training.routine_ir import _exercise_from_raw

            self.ir.exercises = [_exercise_from_raw(dict(e)) for e in self.draft_exercises]

    def record(self, verdicts: list[dict[str, Any]], model_ran: bool, paused: str | None, block: dict[str, Any]) -> dict[str, Any]:
        """Apply `verdicts` to the draft and return the critics record (`inputs_snapshot["critics"]`), unbound."""
        from coach import critic_overrides, critics
        from training import session_block
        from training.cardio_note import apply_after_lines

        from mcp.tools_hevy_routine import _validate_ir_for_hevy

        ir = self.ir
        ran_at = datetime.now(timezone.utc).isoformat()
        # #4076: the owner's override marks ONLY the named critic's veto; it runs before the changes so the record is
        # complete, and it moves no change — `apply_changes` sees every other verdict exactly as the critics returned it.
        override_records = critic_overrides.apply_overrides(
            verdicts,
            self.overrides,
            at=ran_at,
            routine_id=getattr(ir, "routine_id", None),
            target_date=self.target_date,
            record_correction=self.recorder,
        )
        changes = critics.apply_changes(ir, verdicts, set_floors=self.floors)
        apply_after_lines(ir.exercises)  # #5428: a swap or drop moves what follows the cardio — re-stamp `After:`
        session_block.sync_low_energy(ir)  # #5428 re-grade #2: and can change whether the session has easy cardio
        overridden = {v["critic"] for v in verdicts if critics.is_overridden(v)}
        rc = critics.recheck(ir, self.build, overridden=overridden)
        precheck = _validate_ir_for_hevy(ir)
        rc["hevy_precheck_errors"] = precheck["errors"]
        rc["passed"] = bool(rc["passed"] and not precheck["errors"])
        return {
            "engine": critics.CRITICS_VERSION,
            "ran_at": ran_at,
            "target_date": self.target_date,
            "model_ran": model_ran,
            "model_paused_reason": paused,
            "verdicts": verdicts,
            "changes": changes,
            "recheck": rc,
            "veto": bool(critics.standing_vetoes(verdicts)),
            "owner_overrides": override_records,  # #4076: every override asked for, applied or not, his words verbatim
            "packet_numbers": {cid: p["numbers"] for cid, p in self.packets.items()},
            # #4387: the per-activity rows the joints critic argued from, on the stored record (the live-proof read)
            "recent_aerobic": {k: (block.get("recent_aerobic") or {}).get(k) for k in ("window", "rows", "totals", "cardio_pick")},
            "draft_exercises": self.draft_exercises,  # the coach's draft as critiqued — a re-run re-evaluates THIS
        }

    def store(self, record: dict[str, Any], *, dry_run: bool = False) -> str | None:
        """Stamp `record` onto the routine as its next version and write it; the refusal sentence past the deadline."""
        from training.routine_repo import put_versioned

        from mcp import tools_plan as tp

        late = None if dry_run else plan_call_scope.past_write_deadline()
        if late:
            return late
        ir = self.ir
        ir.inputs_snapshot = {**(getattr(ir, "inputs_snapshot", None) or {}), "critics": record}
        tp._place_block_on_first_exercise(ir)  # #5428: verdicts are STORED, never on a Hevy note; strips a legacy block
        ir.parent_version = ir.version
        ir.version = int(ir.version) + 1
        # #4066: bind the verdict to THIS routine and THIS content, stamped after every change — commit refuses any other.
        record["binding"] = binding_for(ir)
        if not dry_run:
            put_versioned(ir)
        return None


def _narrate(run: _Run, block: dict[str, Any], dry_run: bool) -> tuple[dict[str, Any] | None, str | None]:
    """The critics' model calls over the same packets, the reconciled verdicts re-applied to the coach's draft and
    stored on top. (record, None) when it landed; (None, why) when it did not — the routine is then left exactly as the
    deterministic write stored it. A dry run is never refused for time: it writes nothing that could race the cap."""
    from ai.bedrock_client import invoke
    from coach import critics

    wait = plan_call_scope.model_budget_secs()
    if not dry_run and wait is not None and wait < MODEL_MIN_SECS:
        return None, f"model step not started: {wait:.1f}s left before the write deadline (under {MODEL_MIN_SECS:.0f}s)"
    verdicts = critics.run_critics(run.packets, run.draft, invoke=invoke, model_allowed=True, model_timeout_s=wait)
    saved = copy.deepcopy(run.ir)
    run.restore()
    record = run.record(verdicts, True, None, block)
    if run.store(record, dry_run=dry_run):
        run.ir.__dict__.update(saved.__dict__)  # the stored routine is the deterministic one; so is the one in hand
        return None, "the model replies arrived after the write deadline and were NOT stored"
    return record, None


def _next_line(record: dict[str, Any], overridden: set[str]) -> str:
    if record["veto"]:
        return (
            "VETO — redraft (manage_hevy_routine draft), then run stage 2 again; commit will refuse until no veto "
            "stands. If Matthew overrules one critic, re-run with veto_override={critic, owner_words} (#4076)."
        )
    if overridden:
        return (
            f"no standing veto — {', '.join(sorted(overridden))} OVERRIDDEN by the owner (his words are on the record); "
            "every other critic's changes are applied. manage_hevy_routine dry_run shows the revised body, then commit."
        )
    return "no veto — manage_hevy_routine dry_run shows the revised body, then commit."


def run(
    ir: Any,
    block: dict[str, Any],
    reference: dict[str, Any] | None,
    evidence: dict[str, Any],
    protein_missed,
    protein_measured,
    target_date: str,
    dismissals: list[dict[str, Any]] | None = None,
    overrides: list[dict[str, Any]] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """The red team, in the #5781 order (module docstring). `dry_run` (#4076) runs every step and WRITES NOTHING: each
    put is returned under `would_write` (`mcp.plan_stage2_writes`)."""
    from coach import critics

    from mcp import tools_plan as tp

    clock = _Clock()
    build = packet_builder(block, reference, evidence, protein_missed, protein_measured, dismissals)
    would: list[dict[str, Any]] = []
    recorder = _once(plan_stage2_writes.dry_ledger(would) if dry_run else tp._record_override_correction)
    run_ = _Run(ir, block, build, target_date, overrides, recorder)
    allowed, paused = tp._model_allowed()
    verdicts = critics.run_critics(run_.packets, run_.draft, invoke=None, model_allowed=allowed, model_paused_reason=paused)
    record = run_.record(verdicts, False, CHECKPOINT_REASON if allowed else paused, block)
    clock.lap("critics")
    late = run_.store(record, dry_run=dry_run)
    clock.lap("verdict_write")
    if late:  # #5313: past the deadline, store NOTHING and say so — never race the MCP cap
        return {
            **record,
            "routine_id": ir.routine_id,
            "written": False,
            "verdict_state": "not_written",
            "next": late,
            "timing_ms": clock.result(),
        }
    if dry_run and allowed:
        would.extend(plan_stage2_writes.version_puts(ir))  # the live run's first write, in its place in the order
    model_note = None
    if allowed:
        landed, model_note = _narrate(run_, block, dry_run)
        record = landed or record
        clock.lap("narration")
    if dry_run:
        out = plan_stage2_writes.dry_run_result(record, ir, would, tp.pacific_today(), critics.notes_block(ir))
        return {**out, "timing_ms": clock.result()}
    out = dict(record)
    out["routine_id"], out["routine_version"], out["written"] = ir.routine_id, ir.version, True
    out["verdict_state"] = "landed" if model_note is None else "landed_deterministic"
    if plan_call_scope.past_write_deadline():
        out["thread"] = {"written": False, "reason": "past the write deadline — the verdicts are stored, the coach-thread row is not"}
    else:
        out["thread"] = tp._write_thread(ir, tp.pacific_today())
    clock.lap("thread_write")
    out["notes_preview"] = critics.notes_block(ir)
    out["next"] = _next_line(record, {v["critic"] for v in record["verdicts"] if critics.is_overridden(v)})
    if model_note:
        out["model_step"] = model_note
        out["next"] = (
            f"STORED — the deterministic verdicts (v{ir.version}) are the red-team record and commit binds to them; "
            f"{model_note}. " + out["next"]
        )
    clock.lap("response_build")
    out["timing_ms"] = clock.result()
    return out
