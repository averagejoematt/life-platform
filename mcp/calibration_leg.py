"""calibration_leg.py — the tape / photo dead-man check on the nightly pre-draft run (#5061).

A second, fail-soft leg on `nightly_predraft.lambda_entry` (the same shape as the May-tracker leg): it reads
`training.calibration_cadence`, and when a kind has gone `dead_man_missed_cycles` cycles with nothing logged it
writes one log line carrying the token `CALIB_DEADMAN` (kind, missed cycles, last logged — dates and counts, never a
reading or a photo key). The owner-facing alert is the Telegram sweep's dead-man candidate
(`coach_event_triggers.detect_calibration`, once per cycle); this leg is the nightly witness a log metric filter can
alarm on. It never raises into the pre-draft and never changes its outcome.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def calibration_leg(today: str | None = None) -> dict[str, Any]:
    try:
        from common.pacific_time import pacific_today
        from training import calibration_cadence as cc

        from mcp import core

        block = cc.read(core.table, today or pacific_today())
    except Exception as e:  # noqa: BLE001 — named on the run result, never raised into the pre-draft
        logger.warning("[calibration] nightly leg failed (%s)", type(e).__name__)
        return {"outcome": "failed", "error": type(e).__name__}
    dead = cc.deadman_kinds(block)
    for kind in dead:
        row = block["kinds"][kind]
        logger.warning(
            "%s kind=%s missed_cycles=%s last_logged=%s", cc.DEADMAN_TOKEN, kind, row.get("missed_cycles"), row.get("last_logged")
        )
    return {"outcome": "checked", "states": {k: r.get("state") for k, r in block["kinds"].items()}, "deadman": dead}
