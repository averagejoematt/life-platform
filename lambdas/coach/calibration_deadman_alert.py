"""coach/calibration_deadman_alert.py — the calibration dead-man's plain Telegram text (#5203, carrier for #5061).

THE RULING (owner, 2026-10-23, #5203): the missed tape / photo alert reaches him by BOTH channels —
  * this one: a plain, fixed-text Telegram message — no model call, so it is sent at ANY budget tier and costs $0;
  * the `calibration-deadman` CloudWatch alarm (cdk/stacks/mcp_stack.py) on the nightly witness's
    `LifePlatform/HevyRoutine::CalibrationDeadman{Job=calibration}` datapoint (`mcp/calibration_leg.py`), routed
    to the alerts topic, which is email.

WHY A SEPARATE PATH. The event sweep (`coach_event_triggers.run_sweep`) stands down with `reason: budget` at
tier >= `coach_chat._PAUSE_TIER` BEFORE it gathers signals, because every candidate it speaks is an AI turn. A
dead-man is not a coaching nudge; it must not be silenced by AI spend (the live read 2026-10-20 that filed
#5203). So the dead-man candidate left the AI sweep (`coach_event_triggers.detect_calibration` no longer emits
it) and is sent here instead. This module never imports `coach_chat`, `ai.*` or the budget guard, and never reads
the tier — `tests/test_calibration_deadman_alert_5203.py` holds that structurally and delivers it at tier 2 and 3.

WHAT IT SAYS. `calibration_cadence.deadman_alert(row)` — a fixed template filled with the kind, the missed-cycle
count and the last-logged date (or the row's own named alert, the #5096 titration case). Dates and counts only;
never a reading or a photo key. Owner-only: it goes to the program lead's PRIVATE 1:1 chat (the worker's seat),
never the board room.

WHAT IT RESPECTS, AND WHAT IT DOES NOT.
  * Quiet hours — yes (the 16:00Z sweep is outside them; a later run delivers).
  * Once per cycle — yes: the write-once `coach_outbound.claim_event` on `CALIB_DEADMAN#<kind>#<cycle_start>`
    (the same id the AI sweep used, so an alert already delivered before this change is never repeated).
  * The daily outbound cap and the "two ignored, stand down" courtesy — NO. Those govern coaching chat; a dead-man
    that stood down because he ignored two pings would be exactly the silence it exists to break.
  * A dark seat (no bot registered) sends nothing and says so; the email alarm still fires.

Claim-then-send (the reserve-then-act idiom): a crash between the two never licenses a second text, and a failed
send logs `CALIB_DEADMAN_TELEGRAM_FAILED` loudly — the email alarm is the independent second channel.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

PERSONA = "eli_marsh"  # the program lead's seat (coach_event_triggers.LEAD_OWNER) — owner-only by construction
PREFIX = "Calibration dead-man: "
FAILED_TOKEN = "CALIB_DEADMAN_TELEGRAM_FAILED"  # noqa: S105 — a log token, not a credential


def message(row: Mapping[str, Any]) -> str:
    """The fixed text for one dead-man row. Deterministic; no model."""
    from training import calibration_cadence as cc

    return PREFIX + cc.deadman_alert(row)


def due(block: Optional[Mapping[str, Any]]) -> list[dict[str, str]]:
    """[{kind, event_id, text}] for every kind at the dead-man. Pure."""
    from training import calibration_cadence as cc

    out = []
    for kind in cc.deadman_kinds(block or {}):
        row = (block or {})["kinds"][kind]
        out.append({"kind": kind, "event_id": cc.deadman_key(kind, row["cycle_start"]), "text": message(row)})
    return out


def run(
    table: Any,
    now_pt: Any,
    seat: Callable[[str], tuple],
    send: Callable[[str, Any, str], Any],
    *,
    block: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Send each new dead-man alert as one plain text. Never raises; the result is identity-free and safe to log.

    `seat(persona) -> (token, chat_id)` and `send(token, chat_id, text)` are the worker's transport (injected).
    `block` defaults to `calibration_cadence.read(table, today)`.
    """
    from coach import coach_outbound

    if coach_outbound.in_quiet_hours(now_pt):
        return {"reason": "quiet hours", "sent": []}
    today = now_pt.strftime("%Y-%m-%d")
    try:
        if block is None:
            from training import calibration_cadence as cc

            block = cc.read(table, today)
        alerts = due(block)
    except Exception as e:  # noqa: BLE001 — the email alarm is the other channel; never break the sweep
        logger.warning("[calib-deadman] %s cadence read failed (%s)", FAILED_TOKEN, type(e).__name__)
        return {"reason": "read_failed", "sent": []}
    if not alerts:
        return {"reason": "none due", "sent": []}
    token, chat_id = seat(PERSONA)
    if not token or chat_id is None:
        logger.warning("[calib-deadman] %d dead-man alert(s) due but the lead's seat is dark — the email alarm carries it", len(alerts))
        return {"reason": "dark", "sent": [], "due": [a["kind"] for a in alerts]}
    sent = []
    for a in alerts:
        if not coach_outbound.claim_event(table, a["event_id"]):
            continue  # already delivered this cycle (or the ledger is unreadable — stand down, never double-send)
        try:
            send(token, chat_id, a["text"])
        except Exception as e:  # noqa: BLE001
            logger.warning("[calib-deadman] %s kind=%s (%s)", FAILED_TOKEN, a["kind"], type(e).__name__)
            continue
        sent.append(a["kind"])
        logger.info("[calib-deadman] sent kind=%s event=%s", a["kind"], a["event_id"])
    return {"reason": "sent" if sent else "already sent", "sent": sent}
