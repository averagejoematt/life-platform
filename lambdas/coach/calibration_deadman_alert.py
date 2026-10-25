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
send — or a claim the ledger could not WRITE (as opposed to one already taken) — logs `CALIB_DEADMAN_TELEGRAM_FAILED`
loudly; the email alarm is the independent second channel.

EVERY RETURN PATH LOGS (#5203, the 2026-10-24 16:00Z read). That run claimed both rows (`EVENT#CALIB_DEADMAN#tape#…`
and `…#photos#…` under `pk=COACH#outbound_events`, written 16:00:21Z/16:00:22Z) and called Telegram with no failure
logged, yet CloudWatch held no `[calib-deadman]` line: the module logged through a bare `logging.getLogger(__name__)`,
whose INFO records propagate to a Lambda root logger that only surfaces WARNING (the #3283 box-3 class). So the
logger is the worker's platform logger (its own stdout handler, INFO), and every path — quiet hours, none due, dark,
read failed, and the per-kind claim outcome — ends in exactly one `[calib-deadman] reason=… due=[…]` line. The line
carries kinds, event ids (kind + cycle-start date) and counts only — never a reading, a photo key or a chat id.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Mapping, Optional

try:  # the worker's own logger: a handler of its own at INFO, so these lines reach CloudWatch (#3283 / #5203)
    from common.platform_logger import get_logger

    logger: logging.Logger = get_logger("telegram-worker")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("telegram-worker")
    logger.setLevel(logging.INFO)

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


def _summary(reason: str, kinds: list, outcomes: Optional[dict] = None) -> None:
    """The ONE closing line of every run — one grep (`[calib-deadman] reason=`) tells the whole story."""
    tail = " " + " ".join(f"{k}={v}" for k, v in outcomes.items()) if outcomes else ""
    logger.info("[calib-deadman] reason=%s due=[%s]%s", reason.replace(" ", "_"), ",".join(kinds), tail)


def run(
    table: Any,
    now_pt: Any,
    seat: Callable[[str], tuple],
    send: Callable[[str, Any, str], Any],
    *,
    block: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Send each new dead-man alert as one plain text. Never raises; the result is identity-free and safe to log.

    `seat(persona) -> (token, chat_id)` and `send(token, chat_id, text)` are the worker's transport (injected); a
    `send` that returns False (the worker's `_tg` swallows its own errors) is a failed send, like one that raises.
    `block` defaults to `calibration_cadence.read(table, today)`. Every return path logs one
    `[calib-deadman] reason=… due=[…]` line.
    """
    from coach import coach_outbound

    if coach_outbound.in_quiet_hours(now_pt):
        _summary("quiet hours", [])
        return {"reason": "quiet hours", "sent": []}
    today = now_pt.strftime("%Y-%m-%d")
    try:
        if block is None:
            from training import calibration_cadence as cc

            block = cc.read(table, today)
        alerts = due(block)
    except Exception as e:  # noqa: BLE001 — the email alarm is the other channel; never break the sweep
        logger.warning("[calib-deadman] %s cadence read failed (%s)", FAILED_TOKEN, type(e).__name__)
        _summary("read_failed", [])
        return {"reason": "read_failed", "sent": []}
    kinds = [a["kind"] for a in alerts]
    if not alerts:
        _summary("none due", kinds)
        return {"reason": "none due", "sent": []}
    token, chat_id = seat(PERSONA)
    if not token or chat_id is None:
        logger.warning("[calib-deadman] %d dead-man alert(s) due but the lead's seat is dark — the email alarm carries it", len(alerts))
        _summary("dark", kinds)
        return {"reason": "dark", "sent": [], "due": kinds}
    sent: list[str] = []
    outcomes: dict[str, str] = {}
    for a in alerts:
        claim = coach_outbound.claim_event_outcome(table, a["event_id"])
        if claim == coach_outbound.ALREADY_CLAIMED:
            outcomes[a["kind"]] = "already-claimed"  # delivered this cycle already — quiet, by design
            continue
        if claim != coach_outbound.CLAIMED:
            # The ledger could not be written: stand down (never double-send) but LOUDLY — a silent stand-down here
            # is indistinguishable from "already told him", which is the silence this module exists to break.
            outcomes[a["kind"]] = "claim-failed"
            logger.warning("[calib-deadman] %s kind=%s claim write failed — not sent; the email alarm carries it", FAILED_TOKEN, a["kind"])
            continue
        try:
            ok = send(token, chat_id, a["text"])
        except Exception as e:  # noqa: BLE001
            outcomes[a["kind"]] = "send-failed"
            logger.warning("[calib-deadman] %s kind=%s (%s)", FAILED_TOKEN, a["kind"], type(e).__name__)
            continue
        if ok is False:
            outcomes[a["kind"]] = "send-failed"
            logger.warning("[calib-deadman] %s kind=%s (send returned False)", FAILED_TOKEN, a["kind"])
            continue
        outcomes[a["kind"]] = "sent"
        sent.append(a["kind"])
        logger.info("[calib-deadman] sent kind=%s event=%s", a["kind"], a["event_id"])
    failed = [k for k, v in outcomes.items() if v.endswith("-failed")]
    reason = "sent" if sent else ("failed" if failed else "already sent")
    _summary(reason, kinds, outcomes)
    out: dict[str, Any] = {"reason": reason, "sent": sent, "due": kinds, "outcomes": outcomes}
    return out
