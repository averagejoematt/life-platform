"""coach_presence_gate.py — the generation-side glue of the absent-coach rule (#4217).

`health.instrument_presence` decides WHICH coaches are absent (a dark domain
instrument, by the same liveness `/api/source_freshness` serves). This module is the
small, shared way the three generation Lambdas — the daily read (ai_expert_analyzer),
the stance writer (coach_history_summarizer) and docket admission (dispute_docket) —
ask that question and record the skip, so the fail-open posture and the skip shapes
are written once:

  * the read is FAIL-OPEN with a logged warning — a sentinel read failing must never
    silence eight coaches; the caller's run summary says the check failed;
  * an absent coach is skipped BEFORE any prompt is built, so no Bedrock call is spent
    and no OUTPUT#/STANCE#/docket row can quote a sensor that stopped.
"""

# gate-entrypoint: the absence gate — `absent_or_empty()` names the coaches whose sensor
# is dark and the CALLERS do the blocking (the analyzer `continue`s past the coach before any
# prompt is built; the stance writer skips `_run_stance`; docket admission refuses the pair).
# Nothing here raises by design (fail-open, #4217), so the census's exit/raise scan cannot see
# it; the gate can still FAIL — proved in scripts/gate_census_proofs.py (GUARD_PROOFS).

from __future__ import annotations

import logging
from typing import Any, Callable

from coach.persona_registry import OPERATIONAL_COACH_IDS


def absent_or_empty(read: Callable[[], dict], logger: logging.Logger, label: str) -> tuple[dict, str | None]:
    """Run the module's presence read fail-open. Returns ``(absent, error)``: the
    ``{coach_id: instrument_state}`` map (empty on failure) and the failure text, or
    None — so the caller can both keep every coach running AND say the check failed."""
    try:
        return read() or {}, None
    except Exception as e:  # noqa: BLE001 — fail-open is the contract here
        logger.warning("%s instrument presence check failed (fail-open, every coach runs): %s", label, e)
        return {}, str(e)


def full_coach_id(expert_key: str) -> str | None:
    """The persona id behind an analyzer short key ('glucose' -> 'glucose_coach'), from
    the roster — never string surgery on the key."""
    for cid in OPERATIONAL_COACH_IDS:
        if cid.replace("_coach", "") == expert_key:
            return cid
    return None


def skipped_read(state: dict[str, Any]) -> dict[str, Any]:
    """The analyzer's per-coach result for a skipped daily read."""
    return {
        "status": "skipped_absent",
        "reason": state.get("reason"),
        "instrument": {"source": state.get("source"), "datatype": state.get("datatype")},
    }


def skipped_stance(state: dict[str, Any]) -> dict[str, Any]:
    """The stance writer's per-coach result when the instrument is dark."""
    return {"written": False, "reason": "instrument_dark", "instrument_reason": state.get("reason")}
