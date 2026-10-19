"""guidance_freshness.py — is the owner's guidance record older than his latest logged appointment? (#5059)

WHY THIS EXISTS
  The owner-only guidance record (`GUIDANCE#current` in `USER#matthew#SOURCE#clinical`, loaded by
  `scripts/load_clinical_record.py` from a file kept outside this public repo) carries an `effective`
  date. Nothing compared that date with the latest appointment he logged, so a record overtaken by a
  newer appointment kept reading as current. This module answers one question and nothing else:
  should he load the latest instructions?

REFERENCE, NEVER A GATE (owner ruling 7, 2026-10-18)
  He is cleared with no exercise restrictions; the record is background context. The flag rides
  `plan_next_session`'s constraint block, the coach packet and #5071's one coaching context (the
  clinical-guidance section, owner channel only, derived from the same partition read) as REFERENCE
  ONLY: no critic, generator,
  ceiling or progression reads it, and `tests/test_guidance_freshness_5059.py` builds the plan and runs
  the critics with a STALE flag and without one and asserts the prescriptions are identical.

THE APPOINTMENT SOURCE
  A read of the partition (2026-10-19) found no `EVENT#` row of an appointment kind and no `DOC#` row
  whose kind names one, so the source is a new owner-only family, `APPT#<YYYY-MM-DD>#<slug>`, written by
  the same off-repo loader from its `appointments[]` list (docs/SCHEMA.md). Only the DATE in the sort key
  is read here; no other field of an appointment row is touched.

THE FOUR STATES
  fresh           the record's `effective` date is on or after the latest logged appointment
  stale           the latest logged appointment is AFTER the record's `effective` date — the prompt asks
                  him to load the latest instructions (owner channel only)
  no_appointment  the partition holds no appointment on or before today — nothing to compare against
  unreadable      the partition read failed, there is no guidance record, or a date could not be parsed:
                  stated as such, never read as `fresh` (ADR-105)

PRIVACY
  The flag (`freshness`) carries two dates and a prompt — owner channel only (MCP). There is no published
  form: a published coaching context omits the flag (`training.coach_context._freshness_view`). Nothing here logs a
  value: a failed read logs its exception CLASS only. No `lambdas/web/` or `lambdas/emails/` module may
  import this one (the privacy test).
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

FRESH = "fresh"
STALE = "stale"
NO_APPOINTMENT = "no_appointment"
UNREADABLE = "unreadable"
STATES = (FRESH, STALE, NO_APPOINTMENT, UNREADABLE)

GUIDANCE_SK = "GUIDANCE#current"
APPT_PREFIX = "APPT#"
LOADER = "scripts/load_clinical_record.py"
ROLE = "reference — never a gate on intensity (owner ruling 7, 2026-10-18)"

_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _day(value: Any) -> Optional[str]:
    """A YYYY-MM-DD day key, or None. Day keys compare as ISO strings (#3609)."""
    s = str(value or "").strip()[:10]
    return s if _DAY.match(s) else None


def _appointment_day(row: Any) -> Optional[str]:
    """The day of one appointment: a bare day string, or an `APPT#<day>#…` row's sort key (else its `date`)."""
    if isinstance(row, str):
        return _day(row)
    if not isinstance(row, dict):
        return None
    sk = str(row.get("sk") or "")
    if sk.startswith(APPT_PREFIX):
        return _day(sk.split("#")[1])
    return _day(row.get("date"))


def _result(
    state: str, effective: Optional[str] = None, latest: Optional[str] = None, reason: str = "", read_failed: bool = False
) -> dict[str, Any]:
    prompt = None
    if state == STALE:
        prompt = (
            f"A logged appointment ({latest}) is newer than your guidance record (effective {effective}). "
            f"Load the latest instructions: python3 {LOADER} <record.json> --apply"
        )
    return {
        "state": state,
        "guidance_effective": effective,
        "latest_appointment_date": latest,
        "prompt": prompt,
        "reason": reason,
        "read_failed": read_failed,  # True only when the partition read itself broke (vs. a record that is not there)
        "role": ROLE,
        "gates_intensity": False,
    }


def freshness(guidance_row: Optional[dict], appointments: Optional[Iterable[Any]], today: Optional[str] = None) -> dict[str, Any]:
    """THE comparison (pure). `appointments` None = the read failed; [] = none logged.

    `today` (YYYY-MM-DD) drops a booked appointment that has not happened yet; None compares every row."""
    if appointments is None:
        return _result(UNREADABLE, reason="the clinical partition could not be read", read_failed=True)
    if not isinstance(guidance_row, dict):
        return _result(UNREADABLE, reason="no guidance record is on file")
    effective = _day(guidance_row.get("effective"))
    if effective is None:
        return _result(UNREADABLE, reason="the guidance record carries no readable effective date")
    days = []
    for row in appointments:
        d = _appointment_day(row)
        if d is None:
            return _result(UNREADABLE, effective, reason="an appointment row carries no readable date")
        days.append(d)
    cutoff = _day(today)
    past = [d for d in days if cutoff is None or d <= cutoff]
    if not past:
        return _result(NO_APPOINTMENT, effective, reason="no appointment is logged on or before today")
    latest = max(past)
    if latest > effective:
        return _result(STALE, effective, latest, reason="the latest logged appointment is newer than the guidance record")
    return _result(FRESH, effective, latest, reason="the guidance record is on or after the latest logged appointment")


def from_rows(rows: Optional[list], today: Optional[str] = None) -> dict[str, Any]:
    """`freshness` over the partition's rows as `clinical_facts.fetch_clinical_rows` returns them (None = failed)."""
    if rows is None:
        return freshness(None, None, today)
    guidance = next((r for r in rows if isinstance(r, dict) and str(r.get("sk")) == GUIDANCE_SK), None)
    appts = [r for r in rows if isinstance(r, dict) and str(r.get("sk") or "").startswith(APPT_PREFIX)]
    return freshness(guidance, appts, today)


def read_freshness(table, today: Optional[str] = None, user_id: str = "matthew") -> dict[str, Any]:
    """The flag over a live read. Never raises: a broken read is `unreadable`, logged by exception class only."""
    if table is None:
        return freshness(None, None, today)
    try:
        from health import clinical_facts

        return from_rows(clinical_facts.fetch_clinical_rows(table, user_id), today)
    except Exception as e:  # noqa: BLE001 — reference only; a broken read is stated, never raised into a plan
        logger.warning("[guidance_freshness] clinical partition read failed (%s)", type(e).__name__)
        return freshness(None, None, today)
