"""training/lab_priorities.py — the SEAM that carries owner-only lab-driven priorities into the coach context (#5111, #4639).

The repo carries the seam, never the content. The owner writes ONE row into his own clinical partition
(`USER#matthew#SOURCE#clinical`, sk `PRIORITIES#current`, TIER_INTERNAL — the partition `health.clinical_facts` already reads) with a
`text` field: a few plain lines naming what the coach should weight. `from_rows` picks that row out of the clinical rows a caller has
ALREADY read (no second read, no new partition) and `training.coach_context.assemble(lab_priorities=...)` renders it on the owner
channel only. Absent row, empty text or a failed read -> None, and the context says nothing (ADR-104: no invented priority).

PRIVACY (PUBLIC repo): this module names no result, marker or diagnosis. Owner-only by construction: a published context
(`published=True`) drops it, and `tests/test_calibration_cadence_5061.py` holds that no `lambdas/web/` or `lambdas/emails/` module
names the row or imports this one.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

SK = "PRIORITIES#current"
MAX_CHARS = 600


def from_rows(rows: Any) -> Optional[dict[str, Any]]:
    """The priorities row among the clinical partition's rows, or None. Pure."""
    if not isinstance(rows, Iterable) or isinstance(rows, (str, bytes, dict)):
        return None
    for r in rows:
        if isinstance(r, dict) and str(r.get("sk") or "") == SK:
            text = " ".join(str(r.get("text") or "").split())
            if not text:
                return None
            return {"text": text[:MAX_CHARS], "updated_at": str(r.get("updated_at") or "")[:10] or None, "source": f"clinical {SK}"}
    return None
