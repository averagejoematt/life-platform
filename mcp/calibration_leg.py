"""calibration_leg.py — the tape / photo dead-man check on the nightly pre-draft run (#5061).

A second, fail-soft leg on `nightly_predraft.lambda_entry` (the same shape as the May-tracker leg): it reads
`training.calibration_cadence`, and when a kind has gone `dead_man_missed_cycles` cycles with nothing logged it
writes one log line carrying the token `CALIB_DEADMAN` (kind, missed cycles, last logged — dates and counts, never a
reading or a photo key). The owner-facing Telegram alert is the plain fixed-text message
(`coach.calibration_deadman_alert`, plain text at any budget tier, once per cycle — #5203); this leg is the nightly
witness the email alarm reads: every check that read its kinds emits ONE EMF datapoint,
`LifePlatform/HevyRoutine::CalibrationDeadman{Job=calibration}` = the number of kinds at the dead-man (0 on a clean
night), and `calibration-deadman` (cdk/stacks/mcp_stack.py, alerts topic = email) breaches on >= 1. A failed read
(or a clean night with any kind `read_failed`) emits nothing — the pre-draft's own dead-man (`nightly-predraft-missing`) covers a run that never happened. It never
raises into the pre-draft and never changes its outcome.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

METRIC_NAMESPACE = "LifePlatform/HevyRoutine"  # the pre-draft's own namespace — no new namespace
METRIC_NAME = "CalibrationDeadman"
METRIC_DIMENSIONS = {"Job": "calibration"}


def emf_line(dead_count: int) -> str:
    """One EMF datapoint: how many kinds are at the dead-man tonight (0 = clean)."""
    return json.dumps(
        {
            "_aws": {
                "Timestamp": int(time.time() * 1000),
                "CloudWatchMetrics": [
                    {
                        "Namespace": METRIC_NAMESPACE,
                        "Dimensions": [sorted(METRIC_DIMENSIONS)],
                        "Metrics": [{"Name": METRIC_NAME, "Unit": "Count"}],
                    }
                ],
            },
            **METRIC_DIMENSIONS,
            METRIC_NAME: int(dead_count),
        }
    )


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
    # #5203: the email alarm's datapoint. A dead-man is always emitted; a clean 0 only when every kind was read, so an
    # unreadable night is no datapoint (absent, not a false "clean") — never a fabricated zero over a broken read.
    if dead or not any(r.get("state") == cc.READ_FAILED for r in block["kinds"].values()):
        print(emf_line(len(dead)))
    for kind in dead:
        row = block["kinds"][kind]
        logger.warning(
            "%s kind=%s missed_cycles=%s last_logged=%s", cc.DEADMAN_TOKEN, kind, row.get("missed_cycles"), row.get("last_logged")
        )
    return {"outcome": "checked", "states": {k: r.get("state") for k, r in block["kinds"].items()}, "deadman": dead}
