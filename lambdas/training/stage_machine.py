"""training/stage_machine.py — the ordered-stage machine: gates, verdicts, proposals, transitions (#5575).

ONE small primitive, shaped so the conditioning stages (`docs/FRONTIER.md` §CS-4) can adopt it later instead of
building a second one (the #5574 ruling's proportionality note: "build the small evaluator in a shape CS-4 can adopt
later, not a generic engine now"). It knows nothing about training: stages are an ordered list of ids, gates are
already-evaluated verdicts, and the I/O (reads, the store) belongs to the caller. Pure — no clock, no I/O.

VERDICTS. A gate is `met`, `not_met` or `unknown`. Missing data is `unknown`: it never passes, and it is never
reported as `not_met` (a missing weigh-in is not a failed one).

  all_of(verdicts)   any not_met -> not_met; else any unknown -> unknown; else met (an empty list is met: a stage
                     with no gate of its own is gated by the shared rules alone)
  any_of(verdicts)   any met -> met; else any unknown -> unknown; else not_met
  held(series, n)    a gate that must hold for `n` consecutive evaluations, newest first: met only when the newest
                     `n` are all met; not_met when any of them is not_met; otherwise unknown

THE STEP (`step`). One weekly evaluation against the stored state:

  * the stage never moves backwards (`advance.regression: false`) — `step` can only name a LATER stage;
  * when every gate of the NEXT stage is met and nothing is pending, a PROPOSAL is written (`pending`);
  * a pending proposal takes effect at the first block start AFTER the evaluation that proposed it, unless the owner
    vetoed it — the transition's `effective_on` is that block start, applied by the first evaluation that sees it;
  * a veto holds until the next block start after the veto: from then the evaluator may propose again;
  * a block-start read that failed (`boundaries is None`) applies nothing and clears nothing — unknown, not "no block".

The owner override (`override`) moves the stage forward at once and clears any pending proposal; a backwards override is
refused by the same no-regression rule.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

STAGE_MACHINE_VERSION = "stage-machine@1.0.0"

MET, NOT_MET, UNKNOWN = "met", "not_met", "unknown"
VERDICTS = (MET, NOT_MET, UNKNOWN)

PENDING, VETOED = "pending", "vetoed"
ORIGIN_EVALUATOR, ORIGIN_OVERRIDE, ORIGIN_SEED = "evaluator", "owner_override", "seed"


def all_of(verdicts: Iterable[str]) -> str:
    vs = list(verdicts)
    if NOT_MET in vs:
        return NOT_MET
    return UNKNOWN if UNKNOWN in vs else MET


def any_of(verdicts: Iterable[str]) -> str:
    vs = list(verdicts)
    if MET in vs:
        return MET
    return UNKNOWN if UNKNOWN in vs or not vs else NOT_MET


def held(series: Sequence[str], n: int) -> str:
    """`n` consecutive evaluations, newest first. Fewer than `n` readings is unknown (not yet held, not failed)."""
    window = list(series[: max(1, int(n))])
    if NOT_MET in window:
        return NOT_MET
    if len(window) < max(1, int(n)) or UNKNOWN in window:
        return UNKNOWN
    return MET


def next_stage(order: Sequence[str], current: str) -> Optional[str]:
    """The stage after `current` in `order`; None at the last stage (or for a stage the order does not name)."""
    if current not in order:
        return None
    i = list(order).index(current)
    return order[i + 1] if i + 1 < len(order) else None


def is_forward(order: Sequence[str], current: str, target: str) -> bool:
    """True only for a stage strictly LATER than `current` — the no-regression rule in one place."""
    return current in order and target in order and list(order).index(target) > list(order).index(current)


def first_after(boundaries: Optional[Iterable[str]], day: str) -> Optional[str]:
    """The first block start strictly after `day`, or None (none yet, or the boundaries were not read)."""
    if boundaries is None:
        return None
    later = sorted(b for b in boundaries if str(b) > str(day))
    return later[0] if later else None


def step(
    order: Sequence[str],
    state: Mapping[str, Any],
    *,
    as_of: str,
    next_verdict: str,
    boundaries: Optional[Iterable[str]],
    eval_key: Optional[str] = None,
) -> dict[str, Any]:
    """One evaluation. `state` is `{stage, since, pending}` (`pending` None or `{to, proposed_on, status, ...}`);
    `next_verdict` is the combined verdict for the stage after `state['stage']`; `boundaries` the block starts read
    for this run (None = not read). Returns `{state, transition, proposal, action}` — `transition` is the row to write
    when the stage changed (None otherwise), `proposal` the new pending proposal when one was written."""
    current = str(state.get("stage"))
    pending = dict(state["pending"]) if isinstance(state.get("pending"), Mapping) else None
    new_state = {**dict(state), "pending": pending}
    out: dict[str, Any] = {"state": new_state, "transition": None, "proposal": None, "action": "none"}
    boundaries = None if boundaries is None else [str(b) for b in boundaries]

    if pending and pending.get("status") == PENDING:
        effective = first_after(boundaries, str(pending.get("proposed_on")))
        if effective is not None and effective <= as_of and is_forward(order, current, str(pending.get("to"))):
            transition = {
                "from": current,
                "to": str(pending["to"]),
                "effective_on": effective,
                "proposed_on": pending.get("proposed_on"),
                "proposal_eval": pending.get("eval_key"),
                "origin": ORIGIN_EVALUATOR,
                "applied_by_eval": eval_key,
            }
            new_state.update(stage=transition["to"], since=effective, pending=None, origin=ORIGIN_EVALUATOR)
            out.update(transition=transition, action="applied")
            return out
        out["action"] = "pending" if boundaries is not None else "pending_block_unread"
        return out

    if pending and pending.get("status") == VETOED:
        if first_after(boundaries, str(pending.get("vetoed_on") or pending.get("proposed_on"))) is None:
            out["action"] = "vetoed_until_next_block" if boundaries is not None else "vetoed_block_unread"
            return out
        new_state["pending"] = None  # the vetoed block has passed: the evaluator may propose again

    target = next_stage(order, current)
    if target is not None and next_verdict == MET:
        proposal = {"to": target, "proposed_on": as_of, "status": PENDING, "eval_key": eval_key}
        new_state["pending"] = proposal
        out.update(proposal=proposal, action="proposed")
    elif target is None:
        out["action"] = "final_stage"
    return out


def veto(state: Mapping[str, Any], *, on: str, words: Optional[str] = None) -> dict[str, Any]:
    """The owner's veto of the pending proposal. Raises ValueError when nothing is pending."""
    pending = state.get("pending")
    if not isinstance(pending, Mapping) or pending.get("status") != PENDING:
        raise ValueError("no pending proposal to veto")
    return {**dict(state), "pending": {**dict(pending), "status": VETOED, "vetoed_on": on, "veto_words": words}}


def override(order: Sequence[str], state: Mapping[str, Any], *, to: str, on: str, words: Optional[str] = None) -> dict[str, Any]:
    """The owner override: the stage moves to `to` now. Returns `{state, transition}`. Raises ValueError for an unknown
    stage or a move that is not forward (the stage never regresses)."""
    current = str(state.get("stage"))
    if to not in order:
        raise ValueError(f"unknown stage {to!r}; the order is {list(order)}")
    if not is_forward(order, current, to):
        raise ValueError(f"the stage never moves backwards or sideways: {current} -> {to} is refused")
    transition = {
        "from": current,
        "to": to,
        "effective_on": on,
        "proposed_on": None,
        "origin": ORIGIN_OVERRIDE,
        "words": words,
    }
    return {"state": {**dict(state), "stage": to, "since": on, "pending": None, "origin": ORIGIN_OVERRIDE}, "transition": transition}
