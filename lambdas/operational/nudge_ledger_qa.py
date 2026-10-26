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
     re-evaluated. #3651: this leg now REAPS it rather than only reporting it —
     a fail-soft ``put_item`` overwrites the row to ``status=expired``
     (``build_expired_ledger_item``, same idempotent-overwrite shape as the
     streak write in ``qa_smoke_lambda``), so a genuinely stuck reservation gets
     a terminal disposition from the SAME scheduled run that found it, instead
     of sitting as a permanent red only a human DDB edit could ever clear. The
     reap is reported by name (never silently); if the write itself fails, the
     row still surfaces as ``stuck`` exactly as before #3651 — reaping degrades
     to reporting, never the other way around.
  2. **A terminal row must point at a record that exists.** ``sent``/``blocked``
     both assert "a NUDGE# item was written"; ``failed`` (added by #3569) and
     ``expired`` (added by #3651) deliberately do not. A ``sent`` row whose
     ``NUDGE#`` item is missing is a delivered nudge with nothing to grade —
     the #3569 signature exactly, and the check says so by name when EVERY
     terminal row is orphaned.

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
from coach.coach_nudge_engine import (
    LEDGER_PK,
    LEDGER_SK_PREFIX,
    STATUS_ATTEMPTING,
    STATUS_FAILED,
    STATUSES_WITH_RECORD,
    build_expired_ledger_item,
)

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


def scan_stuck_reservations(table, now, stuck_hours=STUCK_HOURS):
    """Every `attempting` row in the WHOLE partition, regardless of age (#3651 round 2).

    WHY THIS IS NOT BOUNDED BY retention_days, which is the entire bug it fixes:

    One query was answering two questions that need opposite windows.

      "is the nudge system alive?"     -> a RECENT window is correct. Scanning all
                                          history would make a long-dead system look busy.
      "is any reservation stuck?"      -> a recent window is WRONG. A dead reservation does
                                          not become acceptable by ageing; it becomes worse.
                                          Bounding this scan by recency means the longer a row
                                          is stuck, the LESS likely anything is to notice.

    Measured consequence before this split (live, 2026-09-16): four rows sat at `attempting`
    — DAY#2026-07-26, DAY#2026-08-06, DAY#2026-08-07 and DAY#2026-08-30, the last being the
    exact row #3651 was filed on, by then ~400h stuck. The liveness floor that day was
    DAY#2026-09-08, so ALL FOUR were outside the query meant to find them, and
    `coach_nudge:ledger_liveness` reported clean. The check was green BECAUSE the failure was
    old.

    Paginated: the partition is small today, but a scan that silently truncates at the first
    page is the same class of blindness one page further out.
    """
    stuck, kwargs = [], {"KeyConditionExpression": Key("pk").eq(LEDGER_PK) & Key("sk").begins_with(LEDGER_SK_PREFIX)}
    while True:
        resp = table.query(**kwargs)
        for row in resp.get("Items") or []:
            if str(row.get("status") or "") != STATUS_ATTEMPTING:
                continue
            age = _stamped_age_hours(row, now)
            if age is None or age > stuck_hours:
                stuck.append((row, age))
        last = resp.get("LastEvaluatedKey")
        if not last:
            return stuck
        kwargs["ExclusiveStartKey"] = last


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

    # #3651 round 2: the stuck scan runs on its OWN window (the whole partition) and must
    # run BEFORE the quiet-week early return. A quiet week is exactly when a stuck row from
    # two months ago is most likely to be the only thing in the ledger worth saying.
    stuck, reaped, orphaned, failed, terminal = [], [], [], [], 0
    try:
        for row, age in scan_stuck_reservations(table, now, stuck_hours):
            sk = str(row.get("sk") or "?")
            if age is None:
                # Can't confirm it is past the bar — conservative: report, never reap
                # something whose age is unknown.
                stuck.append(f"{sk} (undateable, coach={row.get('coach_id')!r})")
                continue
            # A dead reservation with no path to a terminal status is a PERMANENT red
            # otherwise — reap it on the same scheduled run that found it. Fail-soft: if the
            # write does not land, this degrades to a report, never to silence.
            try:
                table.put_item(Item=build_expired_ledger_item(row, now, stuck_hours, age))
                reaped.append(f"{sk} ({age:.0f}h, coach={row.get('coach_id')!r})")
            except Exception as exc:  # noqa: BLE001 — reap must never crash the sweep
                stuck.append(f"{sk} ({age:.0f}h, coach={row.get('coach_id')!r}, reap failed: {str(exc)[:120]})")
    except Exception as exc:  # noqa: BLE001 — the stuck scan must never crash the liveness leg
        stuck.append(f"(stuck scan failed: {str(exc)[:160]})")

    if not rows:
        # Honest absence: no nudge was ATTEMPTED in the LIVENESS window. Nudges are rare by
        # design (≤1/day, and only when a trigger fires), so this is a normal quiet week — it
        # is deliberately not read as either health or fault. But a stuck row found by the
        # unbounded scan above still gets said out loud.
        if not stuck and not reaped:
            c.ok(f"no coach-nudge ledger row in the last {retention_days}d — no nudge attempted (the feature is quiet, not dark)")
            return [c]
        rows = []
    for row in rows:
        sk = str(row.get("sk") or "?")
        status = str(row.get("status") or "")
        if status == STATUS_ATTEMPTING:
            # Handled by the UNBOUNDED scan below, not here — see scan_stuck_reservations.
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

    # #3651: a successful reap clears the board it happened on — it is reported,
    # never hidden, but it is not a problem the ledger is still carrying.
    reap_note = f" ({len(reaped)} stuck reservation(s) reaped to 'expired' (#3651): {'; '.join(reaped)})" if reaped else ""
    if problems:
        c.fail(" | ".join(problems)[:900] + reap_note).with_details(problems + ([f"reaped: {r}" for r in reaped] if reaped else []))
    else:
        c.ok(f"{len(rows)} ledger row(s) in the last {retention_days}d, every one terminal with its NUDGE# record present" + reap_note)
    return [c]


# #5056: the steps-nudge dead-man. The pass stamps `COACH#steps_nudge / EVAL#<date>` on EVERY in-window tick (sent or
# not), so a completed Pacific day with no eval row means the pass never ran in its 19:00-21:00 PT window.
STEPS_LEDGER_PK = "COACH#steps_nudge"
STEPS_EVAL_PREFIX = "EVAL#"
STEPS_LOOKBACK_DAYS = 3
STEPS_ARMED_ON = "2026-10-23"  # first Pacific day the pass can exist on (merge + deploy follow the 10-22 hold); earlier is no evidence


def check_steps_nudge_liveness(table, Check, tier, pt_now, *, lookback_days=STEPS_LOOKBACK_DAYS, armed_on=STEPS_ARMED_ON):
    return _eval_liveness(table, Check, tier, pt_now, STEPS_LEDGER_PK, "steps", "#5056 - the 19:00 PT pass", lookback_days, armed_on)


# #5098: the protein breakfast-nudge dead-man — the same shape on its own ledger row (`COACH#protein_nudge / EVAL#<date>`),
# stamped on every tick inside the charter's breakfast window (`nutrition.protein.breakfast_nudge`).
PROTEIN_LEDGER_PK = "COACH#protein_nudge"
PROTEIN_ARMED_ON = "2026-10-27"  # first Pacific day the pass can exist on (the nutrition wave merges + deploys after 10-22)


def check_protein_nudge_liveness(table, Check, tier, pt_now, *, lookback_days=STEPS_LOOKBACK_DAYS, armed_on=PROTEIN_ARMED_ON):
    return _eval_liveness(table, Check, tier, pt_now, PROTEIN_LEDGER_PK, "protein", "#5098 - the breakfast pass", lookback_days, armed_on)


# #5106: the evening check-in prompt's dead-man — the same shape on `COACH#evening_checkin / EVAL#<date>`, stamped by
# every scheduled 20:00 PT run (sent, dark, quiet, already logged), so a completed day with no row = the rule stopped.
EVENING_CHECKIN_LEDGER_PK = "COACH#evening_checkin"  # = coach.evening_checkin.LEDGER_PK (contract test)
EVENING_CHECKIN_ARMED_ON = "2026-10-27"  # first Pacific day the rule can exist on (the nutrition wave + the Serve apply)


def check_evening_checkin_liveness(table, Check, tier, pt_now, *, lookback_days=STEPS_LOOKBACK_DAYS, armed_on=EVENING_CHECKIN_ARMED_ON):
    what = "#5106 - the 20:00 PT check-in prompt"
    return _eval_liveness(table, Check, tier, pt_now, EVENING_CHECKIN_LEDGER_PK, "evening_checkin", what, lookback_days, armed_on)


def _eval_liveness(table, Check, tier, pt_now, ledger_pk, name, what, lookback_days, armed_on):
    c = Check(f"{name}_nudge:eval_liveness", "Data Freshness", tier)
    today = pt_now().date()
    days = [(today - timedelta(days=n)).isoformat() for n in range(1, lookback_days + 1)]
    days = [d for d in days if d >= armed_on]
    if not days:
        c.ok(f"{name} nudge pending: armed on {armed_on}, no completed day to judge yet")
        return [c]
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(ledger_pk)
            & Key("sk").between(f"{STEPS_EVAL_PREFIX}{min(days)}", f"{STEPS_EVAL_PREFIX}{max(days)}")
        )
        have = {str(r.get("sk"))[len(STEPS_EVAL_PREFIX) :] for r in resp.get("Items") or []}
    except Exception as exc:  # noqa: BLE001
        c.fail(f"{name} nudge ledger - DDB error: {exc}")
        return [c]
    missing = [d for d in days if d not in have]
    if missing:
        c.fail(f"{name} nudge evaluated on none of {len(missing)} completed day(s): {', '.join(sorted(missing))} ({what} did not run)")
    else:
        c.ok(f"{name} nudge evaluated on each of the last {len(days)} completed day(s)")
    return [c]


# #5211: the next-morning check-in / intake pair writer's dead-man. ``scenario-explorer`` (12:10Z) writes
# ``checkin_intake_pairs / DATE#<previous Pacific day>`` EVERY run, with or without a check-in (``has_checkin``), so a
# completed day with no row means the writer stopped or failed. The QA run is 18:30Z, after the writer.
CHECKIN_PAIR_PK = "USER#matthew#SOURCE#checkin_intake_pairs"  # = health.checkin_intake_pairs.PK (contract test)
CHECKIN_PAIR_ARMED_ON = "2026-10-27"  # first Pacific day a row can exist for (the row lands the morning after the deploy)


def check_checkin_pair_liveness(table, Check, tier, pt_now, *, lookback_days=STEPS_LOOKBACK_DAYS, armed_on=CHECKIN_PAIR_ARMED_ON):
    c = Check("checkin_pair:day_row_liveness", "Data Freshness", tier)
    today = pt_now().date()
    days = [d for d in ((today - timedelta(days=n)).isoformat() for n in range(1, lookback_days + 1)) if d >= armed_on]
    if not days:
        c.ok(f"check-in pair writer pending: armed on {armed_on}, no completed day to judge yet")
        return [c]
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(CHECKIN_PAIR_PK) & Key("sk").between(f"DATE#{min(days)}", f"DATE#{max(days)}")
        )
        have = {str(r.get("sk"))[len("DATE#") :] for r in resp.get("Items") or []}
    except Exception as exc:  # noqa: BLE001
        c.fail(f"check-in pair rows - DDB error: {exc}")
        return [c]
    missing = [d for d in days if d not in have]
    if missing:
        c.fail(
            f"check-in pair row missing for {len(missing)} completed day(s): {', '.join(sorted(missing))} (#5211 - scenario-explorer's step did not write)"
        )
    else:
        c.ok(f"check-in pair row present for each of the last {len(days)} completed day(s)")
    return [c]


# #5132: the morning check-in's dead-man. ``telegram-coach-worker`` stamps ``COACH#morning_checkin / EVAL#<Pacific day>``
# on every weekday run (``coach.morning_checkin_ledger``): ``reason`` is ``sent`` or the skip that stood it down.
MORNING_CHECKIN_LEDGER_PK = "COACH#morning_checkin"  # = coach.morning_checkin_ledger.LEDGER_PK (contract test)
MORNING_CHECKIN_ARMED_ON = "2026-10-27"  # first Pacific day a stamp can exist on (the deploy follows the 10-26 first live send)
MORNING_CHECKIN_LOOKBACK_DAYS = 14  # calendar days; enough weekdays to see a repeating skip across two weekends
MORNING_SILENT_FAIL = 2  # consecutive completed weekdays with neither a send nor a sanctioned skip
MORNING_REPEAT_WARN = 5  # consecutive completed weekdays with the SAME sanctioned skip and no send in between


def check_morning_checkin_liveness(
    table, Check, tier, pt_now, *, lookback_days=MORNING_CHECKIN_LOOKBACK_DAYS, armed_on=MORNING_CHECKIN_ARMED_ON
):
    """#5132: the weekday morning check-in must either send or stand down for a named reason.

    Judged over COMPLETED Pacific weekdays (yesterday and earlier) on or after ``armed_on``; Saturday and Sunday
    never count (the rule is MON-FRI and the worker stamps nothing on a weekend), so a Fri->Mon gap is two days
    apart but ONE weekday apart. Per weekday the row's ``reason`` is:

      * ``sent`` or a sanctioned skip (``dark``, ``quiet_hours``, ``silence_respected``, ``budget``, ``capped``,
        ``held`` — ``coach.morning_checkin_ledger.SANCTIONED``): the rule ran and said why. Alive.
      * anything else (``empty``, ``error:<class>``, an unknown token) or NO row: the rule did not run or did not
        complete. Silent.

    FAIL when the newest ``MORNING_SILENT_FAIL`` (2) completed weekdays are all silent. WARN when the newest
    ``MORNING_REPEAT_WARN`` (5) completed weekdays carry the same sanctioned skip and no send: an alive rule that
    never speaks is the 2026-10-01 ... 10-25 ``silence_respected`` latch, which nothing was reading. A single
    silent weekday, or fewer completed weekdays than a rule needs, is OK — the check never judges thin evidence.
    """
    c = Check("morning_checkin:weekday_liveness", "Data Freshness", tier)
    today = pt_now().date()
    days = [today - timedelta(days=n) for n in range(1, lookback_days + 1)]
    days = [d.isoformat() for d in days if d.weekday() < 5 and d.isoformat() >= armed_on]  # newest first
    if not days:
        c.ok(f"morning check-in pending: armed on {armed_on}, no completed weekday to judge yet")
        return [c]
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(MORNING_CHECKIN_LEDGER_PK)
            & Key("sk").between(f"{STEPS_EVAL_PREFIX}{min(days)}", f"{STEPS_EVAL_PREFIX}{max(days)}")
        )
        reasons = {str(r.get("sk"))[len(STEPS_EVAL_PREFIX) :]: str(r.get("reason") or "") for r in resp.get("Items") or []}
    except Exception as exc:  # noqa: BLE001
        c.fail(f"morning check-in ledger - DDB error: {exc}")
        return [c]
    from coach.morning_checkin_ledger import SANCTIONED, SENT

    outcomes = [(d, reasons.get(d)) for d in days]  # (day, reason or None), newest first
    silent = [d for d, r in outcomes if r not in SANCTIONED]
    if len(days) >= MORNING_SILENT_FAIL and all(r not in SANCTIONED for _, r in outcomes[:MORNING_SILENT_FAIL]):
        shown = ", ".join(f"{d}={r or 'no row'}" for d, r in outcomes[:MORNING_SILENT_FAIL])
        c.fail(
            f"morning check-in silent on the last {MORNING_SILENT_FAIL} weekdays with neither a send nor a sanctioned skip: {shown} "
            "(#5132 - the 17:15Z worker run did not complete)"
        )
        return [c]
    window = outcomes[:MORNING_REPEAT_WARN]
    first = window[0][1]
    if len(window) >= MORNING_REPEAT_WARN and first in SANCTIONED and first != SENT and all(r == first for _, r in window):
        c.warn(
            f"morning check-in has stood down as '{first}' on each of the last {MORNING_REPEAT_WARN} weekdays "
            f"({window[-1][0]} .. {window[0][0]}) and sent nothing - the rule is alive but is not speaking"
        )
        return [c]
    sent = sum(1 for _, r in outcomes if r == SENT)
    c.ok(f"morning check-in accounted for on {len(days) - len(silent)} of the last {len(days)} completed weekday(s) ({sent} sent)")
    return [c]
