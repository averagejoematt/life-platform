"""regen_deadline.py — a late coach is HELD, not regenerated past the run's budget (#4343).

The daily brief runs seven domain coaches in series, then the head coach's lead read
(#4188), then the send. Each coach whose draft the N-06 quality gate fails gets one
corrective regeneration (`ai_calls._enforce_quality_gate`) — one more generation and one
more gate call. Nothing read the Lambda's clock, so on 2026-09-27 (request `c016d078`,
every coach regenerated) the run took 728.7 s of its 900 s timeout: a regeneration spent
late in the run is spent from the tail that carries the lead read and the send.

The rule here: the handler ARMS the deadline with its Lambda context; before any
regeneration, `regeneration_allowed()` asks whether the remaining time still covers
RESERVE_SECONDS. Below it the draft is HELD without the rewrite (the gate's existing
hold path — the same terminal outcome a failed rewrite reaches, one gate call sooner),
and the skip is logged. The lead read and the send are never gated by this module.

RESERVE_SECONDS = 180, from the measured tail (CloudWatch `/aws/lambda/daily-brief`):
  * 09-27: last coach 17:10:56.3 → lead read written 17:11:17.9 (21.6 s) → `Sent:`
    17:12:10.7 (52.9 s) — a 74.4 s tail after the last coach;
  * 09-26 / 09-25 (no lead read yet): last coach → `Sent:` 51.0 s / 50.1 s;
  * one regeneration = generation 15–21 s + gate 12–24 s ≈ up to 45 s (#4343's per-coach
    breakdown);
  so a rewrite started with 180 s left finishes with ≥ 135 s — the 74 s tail, the lead
  read's 30–60 s upper band (#4188 sized it at one Haiku call plus reads), and a margin.

Unarmed (every other caller of `ai_calls` — the analyzer, the chat surfaces) it always
allows: the rule belongs to the run that armed it. Pure stdlib, no I/O.
"""

from __future__ import annotations

from typing import Any, Optional

RESERVE_SECONDS = 180.0

_state: dict = {"context": None}


def arm(context: Any) -> None:
    """Bind this invocation's Lambda context (replaces any prior one — warm containers
    re-arm per invocation, so a stale context can never outlive its run)."""
    _state["context"] = context


def remaining_seconds() -> Optional[float]:
    """Seconds left in the armed run, or None when unarmed / the context has no clock."""
    getter = getattr(_state.get("context"), "get_remaining_time_in_millis", None)
    if getter is None:
        return None
    try:
        return float(getter()) / 1000.0
    except Exception:  # noqa: BLE001 — an unreadable clock is "unknown", never "late"
        return None


def regeneration_allowed(coach_id: str) -> bool:
    """False — and one log line — when the armed run is inside its reserved tail."""
    left = remaining_seconds()
    if left is None or left >= RESERVE_SECONDS:
        return True
    print(
        f"[COACH-QUALITY-GATE:{coach_id}] regeneration SKIPPED — {left:.0f}s left < {RESERVE_SECONDS:.0f}s reserve "
        "for the lead read + send (#4343); holding the draft"
    )
    return False
