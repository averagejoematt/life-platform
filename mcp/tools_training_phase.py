"""mcp/tools_training_phase.py — `manage_training_phase`: the computed training phase's door (#5575). OWNER-ONLY.

The weekly evaluator (`mcp/phase_evaluator_leg.py`, a leg on the Monday panel-grade run) writes the phase rows; this tool
reads them and carries the owner's two writes the #5574 ruling keeps for him: the VETO of a pending proposal (the phase
then stays put through the next block start) and the OVERRIDE (forward only — the phase never regresses). The rules are
`training.stage_machine.veto` / `override`; the rows are the leg's (`_put`, the same stamp and Decimal round-trip).
"""

from __future__ import annotations

from typing import Any, Optional

from training import phase_evaluator as pe, stage_machine as sm

from mcp.phase_evaluator_leg import _now_iso, _put, _state_of, latest_eval, read_state, transitions

MANAGE_TRAINING_PHASE_DESCRIPTION = (
    "OWNER-ONLY. The training phase (Foundation -> Build -> Forge -> Sustain) computed from the charter's phase gates "
    "(#5574/#5575). action='status' (default): the current phase and since when, the pending proposal if any, the newest "
    "weekly evaluation — every gate as met / not_met / unknown with its measured value, and the ONE gate that stands "
    "between him and the next phase — plus the transitions so far. action='veto' (optional words): refuse the pending "
    "proposal; the phase then stays put through the next block start, after which the evaluator may propose again. "
    "action='override' with `to` (a phase id or title, later than the current one; optional words): move the phase now. "
    "The phase never moves backwards. Only veto or override on his explicit say-so. Never quoted on the site or in an email."
)

MANAGE_TRAINING_PHASE_INPUT = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["status", "veto", "override"], "description": "status (default), veto, or override."},
        "to": {"type": "string", "description": "action='override': the phase to move to (id or title, later than the current)."},
        "words": {"type": "string", "description": "action='veto'/'override': his words, verbatim (optional)."},
    },
    "required": [],
}


def _status(table: Any, charter: dict[str, Any]) -> dict[str, Any]:
    stored = read_state(table)
    return {
        "state": stored,
        "stored": stored is not None,
        "latest_evaluation": latest_eval(table),
        "transitions": transitions(table),
        "order": pe.order(charter),
        "note": None if stored else "no phase state is stored yet — the first weekly evaluation (Monday's panel-grade run) seeds it",
    }


def tool_manage_training_phase(args: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    from common.pacific_time import pacific_today
    from training.training_charter import load_charter

    from mcp.config import table
    from mcp.utils import mcp_error

    args = args or {}
    action = str(args.get("action") or "status").strip().lower()
    charter = load_charter()
    if action == "status":
        return _status(table, charter)
    if action not in ("veto", "override"):
        return mcp_error("action must be one of: status, veto, override", error_code="INVALID_ACTION")
    stored = read_state(table)
    if stored is None:
        return mcp_error(
            "no phase state is stored yet; nothing to veto or override until the first weekly evaluation", error_code="NOT_FOUND"
        )
    state, today, now, words = _state_of(stored), pacific_today(), _now_iso(), args.get("words")
    try:
        if action == "veto":
            new_state, transition = sm.veto(state, on=today, words=words), None
        else:
            target = str(args.get("to") or "")
            target = target if target in pe.order(charter) else (pe.phase_id_for_title(charter, target) or target)
            moved = sm.override(pe.order(charter), state, to=target, on=today, words=words)
            new_state, transition = moved["state"], moved["transition"]
    except ValueError as e:  # nothing pending to veto (no such record), or an override that is not forward
        return mcp_error(str(e), error_code="NOT_FOUND" if action == "veto" else "INVALID_ARG")
    if transition:
        _put(table, pe.transition_row(charter, transition, recorded_at=now))
    _put(table, pe.state_row(charter, new_state, updated_at=now))
    return {"action": action, "state": new_state, "transition": transition}
