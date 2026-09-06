"""nudge_ledger_qa.py — #3569: the coach-nudge ledger dead-man.

coach-nudge (#1382) reserves a Pacific day by conditional-putting a
``COACH#nudge_ledger`` row at ``status=attempting``, then writes the verbatim
``NUDGE#`` record and overwrites the reservation with the terminal status. From
the day the feature shipped, the second half never happened once: ``_finalize``
had no Decimal coercion and ``trigger_payload`` carries a real float, so every
attempt raised ``TypeError: Float types are not supported`` — 3 crashes on
record (2026-08-06, 08-07, 08-30), 4 ledger rows all reading ``attempting``, and
**zero** ``NUDGE#`` rows across all nine coach partitions. Nothing anywhere read
the ledger, so 25 days of total feature failure produced no signal at all.

This is the dead-man that class lacked. Two independent legs, both derived from
the ledger's own contract rather than from a remembered symptom:

  1. **A reservation must reach a terminal status.** A row still at
     ``attempting`` more than ``STUCK_HOURS`` after it was stamped means the run
     that claimed the day died between the reservation and the record — and,
     because ``graded=True``, that day is consumed forever and can never be
     re-evaluated. RED.
  2. **A terminal row must point at a record that exists.** ``sent``/``blocked``
     both assert "a NUDGE# item was written"; ``failed`` (added by #3569)
     deliberately does not. A ``sent`` row whose ``NUDGE#`` item is missing is a
     delivered nudge with nothing to grade — the #3569 signature exactly, and
     the check says so by name when EVERY terminal row is orphaned.

Scoped to the trailing ``RETENTION_DAYS`` so the check measures liveness rather
than accumulating history: an old stuck row is a fact about the past, and a
permanently-red nightly check is a check nobody reads.

Sibling of acwr_liveness_qa / chronicle_manifest_qa / raw_archive_qa: every
collaborator (table, Check class, partition, clock) arrives as an argument, so
qa_smoke_lambda stays a registry and this logic is testable with no AWS.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from boto3.dynamodb.conditions import Key
from coach.coach_nudge_engine import LEDGER_PK, LEDGER_SK_PREFIX, STATUS_ATTEMPTING, STATUS_FAILED, STATUSES_WITH_RECORD

# #1964/#2811: the one Pacific frame and the one ISO parser. Both matter here —
# a `DAY#` sk is the handler's PACIFIC calendar day (`now_pt.date()`), so both
# the retention window and the sk-date age anchor must be read in that frame. A
# UTC `.date()` would shift the window by a day for the 7–8 evening PT hours
# that are already tomorrow in UTC.
from common.pacific_time import PACIFIC, parse_iso_utc

# A reservation older than this with no terminal status is stuck. One nudge run
# is a single Lambda invocation of at most a few seconds; 24h is ~4 orders of
# magnitude of slack, so a trip is a real fault and never a slow day.
STUCK_HOURS = 24

# How far back the check looks. The ledger has no TTL, so without a window the
# four pre-fix stuck rows (2026-07-26 … 2026-08-30) would red this check forever
# — history, not liveness.
RETENTION_DAYS = 7


def _stamped_age_hours(row: dict, as_of):
    """Hours since the row was written, or None if it cannot be dated.

    Prefers the explicit stamp (``attempted_at``, added to the reservation by
    #3569; ``sent_at`` on terminal rows), parsed by the ONE parser so a tz-less
    stamp can never be read in the runner's zone (#1964). Pre-#3569 reservations
    carry NO timestamp of any kind and fall back to the day their sk names,
    anchored at that PACIFIC day's LAST instant — the frame that named the key
    (#2817/#3257) — so the age is understated, never overstated: the fallback can
    only delay a red, never manufacture one.

    ``as_of`` and the parsed stamp may sit in different frames; both are aware, so
    the subtraction is exact either way.
    """
    stamped = parse_iso_utc(row.get("attempted_at") or row.get("sent_at"))
    if stamped is not None:
        return (as_of - stamped).total_seconds() / 3600.0
    day = str(row.get("sk") or "").replace(LEDGER_SK_PREFIX, "")
    try:
        end_of_day = datetime.strptime(day, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=PACIFIC)
    except ValueError:
        return None
    return (as_of - end_of_day).total_seconds() / 3600.0


def check_nudge_ledger_liveness(table, Check, tier, pt_now, *, stuck_hours=STUCK_HOURS, retention_days=RETENTION_DAYS):
    c = Check("coach_nudge:ledger_liveness", "Data Freshness", tier)
    now = pt_now()  # aware PACIFIC instant — the frame the DAY# sk is written in
    floor = f"{LEDGER_SK_PREFIX}{(now.date() - timedelta(days=retention_days)).isoformat()}"
    try:
        resp = table.query(KeyConditionExpression=Key("pk").eq(LEDGER_PK) & Key("sk").gte(floor))
        rows = [r for r in (resp.get("Items") or []) if str(r.get("sk") or "").startswith(LEDGER_SK_PREFIX)]
    except Exception as exc:  # noqa: BLE001
        c.fail(f"coach-nudge ledger — DDB error: {exc}")
        return [c]

    if not rows:
        # Honest absence: no nudge was ATTEMPTED in the window. Nudges are rare
        # by design (≤1/day, and only when a trigger fires), so this is a normal
        # quiet week — it is deliberately not read as either health or fault.
        c.ok(f"no coach-nudge ledger row in the last {retention_days}d — no nudge attempted (the feature is quiet, not dark)")
        return [c]

    stuck, orphaned, failed, terminal = [], [], [], 0
    for row in rows:
        sk = str(row.get("sk") or "?")
        status = str(row.get("status") or "")
        if status == STATUS_ATTEMPTING:
            age = _stamped_age_hours(row, now)
            if age is None:
                stuck.append(f"{sk} (undateable, coach={row.get('coach_id')!r})")
            elif age > stuck_hours:
                stuck.append(f"{sk} ({age:.0f}h, coach={row.get('coach_id')!r})")
            continue
        if status == STATUS_FAILED:
            failed.append(f"{sk} ({str(row.get('error') or 'no error recorded')[:160]})")
            continue
        if status not in STATUSES_WITH_RECORD:
            continue
        terminal += 1
        nudge_pk, nudge_sk = row.get("nudge_pk"), row.get("nudge_sk")
        if not nudge_pk or not nudge_sk:
            orphaned.append(f"{sk} (status={status}, no record pointer)")
            continue
        try:
            record = table.get_item(Key={"pk": nudge_pk, "sk": nudge_sk}).get("Item")
        except Exception as exc:  # noqa: BLE001
            c.fail(f"coach-nudge ledger — DDB error reading {nudge_pk}/{nudge_sk}: {exc}")
            return [c]
        if not record:
            orphaned.append(f"{sk} (status={status}, {nudge_pk}/{nudge_sk} missing)")

    problems = []
    if stuck:
        problems.append(
            f"{len(stuck)} reservation(s) stuck at '{STATUS_ATTEMPTING}' past {stuck_hours}h — "
            f"the day is consumed and the nudge was never recorded (#3569): {'; '.join(stuck)}"
        )
    if orphaned:
        if terminal and len(orphaned) == terminal:
            problems.append(
                f"ZERO NUDGE# records behind {terminal} terminal ledger row(s) — the sender ran and persisted "
                f"nothing (#3569): {'; '.join(orphaned)}"
            )
        else:
            problems.append(f"{len(orphaned)} ledger row(s) point at a missing NUDGE# record (#3569): {'; '.join(orphaned)}")
    if failed:
        problems.append(f"{len(failed)} nudge record write(s) failed: {'; '.join(failed)}")

    if problems:
        c.fail(" | ".join(problems)[:900]).with_details(problems)
    else:
        c.ok(f"{len(rows)} ledger row(s) in the last {retention_days}d, every one terminal with its NUDGE# record present")
    return [c]
