"""lambdas/coach/commitment_grading.py — the #532 follow-through ledger, actually graded (#3553).

WHAT WAS WRONG (measured 2026-09-06, live DDB census over the seven COACH# partitions)
  503 COMMITMENT# records, 58 with a deterministic `action_check`, 52 past their due
  date — and **0 kept / 0 broken in the instrument's entire life**, across cycles 5-17.
  The platform published a commitment ledger and had never scored a commitment. Three
  co-equal causes, each of which alone was enough:

  1. **The grader could not see its own corpus.** `_fetch_commitments` was
     `with_phase_filter`'d, so every record a reset had tombstoned (`phase=pilot`)
     vanished from the query. All 58 checkable records were pilot-phase. The grader ran
     daily against an empty set and logged `kept=0 broken=0` — an honest log line about
     a corpus it was structurally forbidden to read.
  2. **The grade was anchored to TODAY, not to the commitment's own window.** The old
     code passed `today_str` into the directional evaluator, so a 7-day commitment made
     on 2026-07-06 would have been graded on September data. That is not a verdict about
     the promise; it is a verdict about a different fortnight.
  3. **No absence rule at birth (ADR-104).** 37 of the 58 bind to `total_protein_g`,
     whose source (MacroFactor) has recorded nothing since 2026-06-24. Those checks
     could never resolve, but they were born `pending` — a status that promises a
     verdict — and stayed there forever.

  And nothing read the grader's output, which is why it stayed dark for its whole life.

WHAT THIS MODULE IS
  The ONE place the commitment ledger's semantics live: the status vocabulary, the
  write-time gradeability rule, the grading loop, the public tally (with its Wilson
  interval and its n, ADR-105), and the dead-man predicate the CloudWatch alarm mirrors.
  It was extracted from `coach_prediction_evaluator.py` rather than added to it: that
  module sits one line under its #1665 size baseline, and the extract-don't-raise rule
  is what the baseline is for.

  Pure by construction — no boto3, no module-level AWS. Every I/O leg is an injected
  callable, which is also what lets `cdk/stacks/monitoring_prediction_alarms.py` import
  the dead-man constants directly instead of hand-typing the alarm's threshold twice.

THE STATUS VOCABULARY, and why `ungradeable` is not `unresolved`
  pending      the window is still open (or the 2x grace still runs) — a promise the
               evaluator WILL return a verdict.
  kept         the checked metric moved the committed way, by more than the noise band.
  broken       it moved the other way, or did not move at all (#801 — "nothing happened"
               is evidence against a commitment to move something, not a non-result).
  unresolved   a metric-LESS commitment whose window elapsed with no coach follow-up.
               A human could still have resolved it; nobody did.
  ungradeable  there was never a grading path. Either the metric had fewer than the
               EWMA floor of observations inside the window the commitment was due on
               (the data to grade it does not exist and never will), or the record was
               born against a dark/paused source and said so at birth.

  The distinction is the whole ADR-104 point: `unresolved` is a lapse, `ungradeable` is
  an absence of evidence, and a reader is owed the difference with its n. Neither is
  hidden from the public surface — labelling is the fix, dropping is not.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Callable, Iterable

# ── The status vocabulary ─────────────────────────────────────────────────────
STATUS_PENDING = "pending"
STATUS_KEPT = "kept"
STATUS_BROKEN = "broken"
STATUS_UNRESOLVED = "unresolved"
STATUS_UNGRADEABLE = "ungradeable"

#: The two statuses that are a VERDICT about follow-through — the n of the public rate.
GRADED_STATUSES = (STATUS_KEPT, STATUS_BROKEN)
#: Every terminal status. A record in one of these is never re-fetched by the grader.
TERMINAL_STATUSES = (STATUS_KEPT, STATUS_BROKEN, STATUS_UNRESOLVED, STATUS_UNGRADEABLE)
#: The counts every tally carries, in render order.
COUNT_KEYS = (STATUS_KEPT, STATUS_BROKEN, STATUS_UNRESOLVED, STATUS_UNGRADEABLE, STATUS_PENDING)

# ── The dead-man (#3553 acceptance box 1) ─────────────────────────────────────
#
# The reason this instrument was dark for its whole life is that NOTHING read its
# output. The evaluator logged `Commitment stats: kept=0 broken=0` on every run for 21
# days straight and no alarm, no test and no page ever looked at the line.
#
# So the grader emits two numbers every run, and one alarm reads them together:
#
#   CommitmentsDueCheckable — commitments past their due date that HAVE a deterministic
#                             check. The denominator: "there was work to grade".
#   CommitmentsGraded       — kept + broken this run, plus a per-outcome dimensioned
#                             copy. The numerator: "a verdict came out".
#
# ALARM when there was work and no verdict came out, sustained for DEADMAN_DAYS daily
# periods. Both halves matter: `graded == 0` alone fires on a legitimately quiet week,
# and `due > 0` alone fires on a healthy backlog. Missing data BREACHES — a grader that
# stops running emits neither metric, and silence is the exact failure this catches.
#
# The alarm math is defined HERE, next to the predicate the tests drive, so the CDK
# expression and the Python truth table cannot drift into disagreeing about what
# "the grader is dark" means.
DEADMAN_NAMESPACE = "LifePlatform/Predictions"
DEADMAN_METRIC_DUE = "CommitmentsDueCheckable"
DEADMAN_METRIC_GRADED = "CommitmentsGraded"
DEADMAN_ALARM_NAME = "commitments-ungraded"
DEADMAN_DAYS = 14
DEADMAN_EXPRESSION = "IF(due > 0 AND graded < 1, 1, 0)"


def deadman_breached(due_checkable, graded_total) -> bool:
    """True when the ledger had gradeable work and produced no verdict.

    The Python twin of DEADMAN_EXPRESSION. `tests/test_commitment_grading_3553.py`
    drives BOTH against the same truth table, so the alarm cannot silently mean
    something other than this function.
    """
    try:
        due = float(due_checkable or 0)
        graded = float(graded_total or 0)
    except (TypeError, ValueError):
        return False
    return due > 0 and graded < 1


# ── The write-time gradeability rule (#3553 acceptance box 2, ADR-104) ────────


def birth_block_reason(metric, source, availability, has_recent_data, *, lookback_days, min_points) -> str | None:
    """None when a commitment may be born gradeable; else WHY it cannot be.

    Called by `coach_state_updater._create_commitment_records` at the moment the record
    is written. The rule is deliberately the same shape as the #813 prediction liveness
    gate — a check whose metric is not being observed is not a check — but it lands a
    step further: a prediction falls back to `qualitative` (an honest "no grading path"),
    whereas a commitment used to be born `pending`, which is a promise.

    Two registry-derived causes plus one measured one, none of them hand-typed here:
      * the metric maps to no source at all (`measurable_metrics.METRIC_SOURCES`);
      * the source is PAUSED in `source_registry` — it CANNOT report (#3516's facet,
        whose caveat sentence is reused verbatim rather than reworded);
      * the source is live but the metric is dark — fewer than the evaluator's own EWMA
        floor of readings in the trailing window. This is the MacroFactor case: not
        paused, just silent since 2026-06-24, which no registry facet can express.
    """
    if not metric:
        return None
    if not source:
        return (
            f"ungradeable at birth: {metric!r} maps to no source in measurable_metrics.METRIC_SOURCES, "
            "so no deterministic check can ever read it."
        )
    facet = availability or {}
    if facet.get("status") == "paused":
        return f"ungradeable at birth: source {source!r} is paused, so it cannot report a follow-through signal. {facet.get('caveat', '')}".strip()
    if not has_recent_data:
        return (
            f"ungradeable at birth: source {source!r} recorded fewer than {min_points} {metric} values "
            f"in the last {lookback_days} days — the metric this check reads is dark, so the check could "
            "only ever come back inconclusive (ADR-104: an absent signal is a hole in the record, not a "
            "fact about Matthew)."
        )
    return None


# ── The grading loop (#3553 acceptance boxes 1 + 3) ──────────────────────────


def _parse(date_str):
    try:
        return datetime.strptime(str(date_str), "%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def due_date(created_date, window_days) -> str | None:
    """The day a commitment's window closes — the instant it is graded ON."""
    created = _parse(created_date)
    if created is None:
        return None
    try:
        window = int(window_days or 7)
    except (TypeError, ValueError):
        window = 7
    return (created + timedelta(days=max(1, window))).strftime("%Y-%m-%d")


def evaluate(
    commitments: Iterable[dict],
    today_str: str,
    data_cache: dict,
    *,
    directional: Callable[[dict, dict, str], Any],
    observations: Callable[[str, dict, str], int],
    update_status: Callable[[dict, str, str, str], Any],
    min_observations: int,
    expiry_multiplier: int,
    logger=None,
) -> dict:
    """Grade every due commitment against the data of ITS OWN window.

    `end_date` is the commitment's due date, never today (cause 2 in the module header):
    the directional evaluator's 30-day EWMA window ending on the due date puts the
    "current" side of the comparison at the close of the commitment window and the
    "prior" side at roughly the day the commitment was made — which is the question the
    ledger claims to answer. Grading a July promise on September data was never that.

    Returns the stats dict the handler surfaces and the dead-man reads:
    kept/broken/unresolved/ungradeable/pending plus `due_checkable` (the alarm's
    denominator) and `graded` (its numerator).
    """
    today = _parse(today_str)
    stats = {
        STATUS_KEPT: 0,
        STATUS_BROKEN: 0,
        STATUS_UNRESOLVED: 0,
        STATUS_UNGRADEABLE: 0,
        STATUS_PENDING: 0,
        "due_checkable": 0,
        "graded": 0,
    }
    if today is None:
        return stats

    for c in commitments or []:
        created_dt = _parse(c.get("created_date"))
        if created_dt is None:
            continue
        try:
            window_days = max(1, int(c.get("window_days") or 7))
        except (TypeError, ValueError):
            window_days = 7
        due = created_dt + timedelta(days=window_days)
        if today < due:
            stats[STATUS_PENDING] += 1
            continue

        expired = (today - created_dt).days > window_days * expiry_multiplier
        action_check = c.get("action_check") if isinstance(c.get("action_check"), dict) else None
        metric = (action_check or {}).get("metric")
        direction = (action_check or {}).get("direction")

        if not (metric and direction):
            # No machine check — the coach owns following up. Expire stale ones so they
            # don't accumulate as forever-open (unchanged #532 behaviour).
            if expired:
                update_status(c, STATUS_UNRESOLVED, "No machine-checkable action; window elapsed without coach follow-up.", today_str)
                stats[STATUS_UNRESOLVED] += 1
            else:
                stats[STATUS_PENDING] += 1
            continue

        stats["due_checkable"] += 1
        end_date = min(due, today).strftime("%Y-%m-%d")
        spec = {"type": "directional", "metric": metric, "condition": direction}
        result = directional(spec, data_cache, end_date) or {}
        verdict = result.get("status", "inconclusive")

        if verdict == "confirmed":
            update_status(c, STATUS_KEPT, result.get("reason", ""), today_str)
            stats[STATUS_KEPT] += 1
            stats["graded"] += 1
        elif verdict == "refuted":
            update_status(c, STATUS_BROKEN, result.get("reason", ""), today_str)
            stats[STATUS_BROKEN] += 1
            stats["graded"] += 1
        elif expired:
            # Terminal, and terminal for a NAMED reason with its n. The 2x grace has
            # run, so late data is no longer coming; the honest verdict is that the
            # evidence to grade this promise does not exist.
            n = 0
            try:
                n = int(observations(metric, data_cache, end_date))
            except Exception:  # noqa: BLE001 — an observation-count failure must not block the verdict
                n = -1
            counted = "an unreadable number of" if n < 0 else str(n)
            update_status(
                c,
                STATUS_UNGRADEABLE,
                (
                    f"ungradeable: {metric} had {counted} observation(s) in the 30 days to {end_date} "
                    f"(the window this commitment was due on); the trend floor is {min_observations}. "
                    "Not a verdict on follow-through — the evidence to grade it does not exist."
                ),
                today_str,
            )
            stats[STATUS_UNGRADEABLE] += 1
        else:
            # Inside the 2x grace — a late reading can still decide it. Stays pending.
            stats[STATUS_PENDING] += 1

    if logger is not None:
        logger.info(
            "Commitment stats: kept=%d broken=%d unresolved=%d ungradeable=%d pending=%d due_checkable=%d graded=%d",
            stats[STATUS_KEPT],
            stats[STATUS_BROKEN],
            stats[STATUS_UNRESOLVED],
            stats[STATUS_UNGRADEABLE],
            stats[STATUS_PENDING],
            stats["due_checkable"],
            stats["graded"],
        )
    return stats


# ── The public tally (#3553 acceptance box 4, ADR-105) ───────────────────────


def tally(records: Iterable[dict]) -> dict:
    """The follow-through numbers a reader is served — every one with its n.

    `follow_through_pct` is kept / (kept + broken) and is None when nothing has been
    graded: a rate off an empty denominator is not 0%, it is unmeasured, and rendering
    it as 0% is the exact class of claim #3553 was filed for. It ships with its 95%
    Wilson interval (the ONE sanctioned proportion interval on this platform,
    `common.stats_core.wilson_interval`) so a 5-of-14 rate never reads as a precise 36%.

    `ungradeable_by_metric` exists so the surface can NAME what could not be graded
    rather than quietly shrinking the denominator — the difference between an honest
    ledger and a flattering one.
    """
    from common.stats_core import wilson_interval  # local: keeps this module CDK-importable

    counts = {k: 0 for k in COUNT_KEYS}
    total = 0
    checkable = 0
    ungradeable_by_metric: dict[str, int] = {}
    for rec in records or []:
        total += 1
        status = str((rec or {}).get("status") or STATUS_PENDING)
        counts[status if status in counts else STATUS_PENDING] += 1
        check = (rec or {}).get("action_check")
        metric = check.get("metric") if isinstance(check, dict) else None
        if metric:
            checkable += 1
            if status == STATUS_UNGRADEABLE:
                ungradeable_by_metric[metric] = ungradeable_by_metric.get(metric, 0) + 1

    graded = counts[STATUS_KEPT] + counts[STATUS_BROKEN]
    pct = round(counts[STATUS_KEPT] / graded * 100, 1) if graded else None
    ci = wilson_interval(counts[STATUS_KEPT], graded) if graded else None
    return {
        "total": total,
        "checkable": checkable,
        **counts,
        "graded": graded,
        "follow_through_pct": pct,
        "follow_through_ci95": ([round(ci[0] * 100, 1), round(ci[1] * 100, 1)] if ci else None),
        "ungradeable_by_metric": dict(sorted(ungradeable_by_metric.items(), key=lambda kv: (-kv[1], kv[0]))),
    }


# ── The DDB legs (injected handles — this module stays boto3-free) ────────────


def fetch_pending(table, coach_ids, with_phase_filter, decimal_to_float, logger) -> list:
    """Every pending COMMITMENT# record across `coach_ids` — CROSS-PHASE, by rule.

    #3553: this read used to be `with_phase_filter`'d, and that one line is why the
    ledger never graded anything. A reset tombstones the open commitments
    (`phase=pilot`), and cycles 13/14/15/16 lasted 15/15/3/1 days — so no commitment
    with a 7-90 day window ever survived inside its own phase long enough to be seen at
    its due date. The 2026-09-06 census found ALL 58 checkable records at `phase=pilot`:
    the grader was querying a set it was structurally forbidden to read, and honestly
    logging kept=0 about it.

    The rule, stated once: **a commitment is graded on the window it was made for,
    whatever cycle the platform is in now.** A reset re-anchors the EXPERIMENT; it does
    not un-make a promise, and the data the promise is graded against (raw source
    timeseries) is itself cross-phase (#2023). This is the read shape `/api/predictions`
    already uses for the career scorecard — one unfiltered partition fetch, with season
    derived from it by `singleton_visible` rather than by a second query.
    """
    out: list = []
    for coach_id in coach_ids:
        try:
            kwargs = {
                "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                "ExpressionAttributeValues": {":pk": f"COACH#{coach_id}", ":prefix": "COMMITMENT#"},
            }
            while True:
                resp = table.query(**with_phase_filter(kwargs, include_pilot=True))
                for item in (decimal_to_float(i) for i in resp.get("Items", [])):
                    if item.get("status", "") == STATUS_PENDING:
                        out.append(item)
                if "LastEvaluatedKey" not in resp:
                    break
                kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        except Exception as e:  # noqa: BLE001 — one bad partition must not sink the pass
            logger.warning("Failed to fetch commitments for %s: %s", coach_id, e)
    logger.info("Total pending commitments fetched: %d", len(out))
    return out


def write_status(table, commitment, status, reason, today_str, algo_version, logger) -> None:
    """Stamp a commitment's follow-through outcome. Fail-soft per record."""
    import json

    try:
        pk = commitment.get("pk") or f"COACH#{commitment.get('coach_id', '')}"
        sk = commitment.get("sk") or f"COMMITMENT#{commitment.get('commitment_id', '')}"
        table.update_item(
            Key={"pk": pk, "sk": sk},
            UpdateExpression="SET #status = :status, outcome = :outcome, outcome_date = :odate, outcome_notes = :notes",
            ExpressionAttributeNames={"#status": "status"},
            ExpressionAttributeValues={
                ":status": status,
                ":outcome": status,
                ":odate": today_str,
                ":notes": json.dumps({"reason": reason, "algo_version": algo_version}),
            },
        )
        logger.info("Commitment %s -> %s", commitment.get("commitment_id", "?"), status)
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to update commitment %s: %s", commitment.get("commitment_id", "?"), e)


def emit_liveness(cw, stats, logger) -> dict:
    """The dead-man's two numbers, emitted EVERY run (even a zero one).

    Unconditional for the same reason #727's gauges are: an alarm with no daily
    datapoint cannot tell "healthy" from "the Lambda stopped running", and the second is
    exactly the failure that hid this instrument for its whole life. `CommitmentsGraded`
    also carries a per-outcome dimensioned copy so the kept/broken split is legible on
    the dashboard without re-querying DDB. Fail-soft — a metrics error must never sink
    the grading pass it is reporting on.
    """
    due = int((stats or {}).get("due_checkable", 0))
    graded = int((stats or {}).get("graded", 0))
    data = [
        {"MetricName": DEADMAN_METRIC_DUE, "Value": float(due), "Unit": "Count"},
        {"MetricName": DEADMAN_METRIC_GRADED, "Value": float(graded), "Unit": "Count"},
    ]
    for outcome in (STATUS_KEPT, STATUS_BROKEN, STATUS_UNRESOLVED, STATUS_UNGRADEABLE):
        data.append(
            {
                "MetricName": DEADMAN_METRIC_GRADED,
                "Dimensions": [{"Name": "Outcome", "Value": outcome}],
                "Value": float((stats or {}).get(outcome, 0)),
                "Unit": "Count",
            }
        )
    try:
        cw.put_metric_data(Namespace=DEADMAN_NAMESPACE, MetricData=data)
    except Exception as e:  # noqa: BLE001
        logger.warning("[liveness] commitment metric emit failed (non-fatal): %s", e)
    if deadman_breached(due, graded):
        logger.warning("[liveness] commitment dead-man: %d due&checkable this run, 0 graded", due)
    return {"due_checkable": due, "graded": graded, "emitted": data}
