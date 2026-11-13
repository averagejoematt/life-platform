"""public_brief_qa.py — the dead-man for the weekly public-safe coaching brief (owner approval 2026-11-12).

WHAT IT GUARDS. ``coach-history-summarizer`` runs ``{"mode": "public_brief"}`` every Monday at 09:00 Pacific
(config/schedules.json ``coach-history-summarizer#PublicBrief``). ``coach.public_brief.run`` never raises, so a run that
writes nothing (every coach held, a crash caught inside, a schedule that never fired) is silent to every error alarm.
The Lambda door (``public_brief.handle_event``) stamps ``COACH#public_brief / RUN#<cycle>`` with each coach's outcome on
every scheduled run; this check reads it on the nightly qa-smoke run (11:30 PT, so the Monday run is judged the same
day) and reds the ``qa-smoke-failures`` alarm.

THE VERDICT, for the newest DUE cycle (its Monday at 09:00 PT + ``GRACE_MINUTES``; never before ``FIRST_CYCLE``):
  * FAIL — no stamp (the run never happened or died before stamping); the run itself refused or errored; any brief
    coach (``public_brief.brief_coaches()``, the registry — guard the set) with no outcome, an ``error``, a ``refused``
    or a ``held`` for any reason other than its required inputs being absent; or an outcome of ``written``/``exists``
    with no ``PUBLIC_BRIEF#<cycle>`` row behind it.
  * WARN — the budget paused the run (a sanctioned tier state, ADR-125, but a missed week is never backfilled), or a
    coach was held because its required inputs were absent (e.g. no glucose readings) or stale (``inputs_stale``: no
    reading in the coach's freshness window, e.g. no MacroFactor export since mid-week), or had too few readings.
  * OK — every brief coach has its brief row for the cycle.
The stamp persists for the week, so a FAIL stays red until a re-run (``{"mode": "public_brief", "coach_ids": [...]}``)
writes the missing briefs and merges its outcomes into the stamp. A dry run never stamps and is never judged.

CONTENT_TRUTH, not DEPLOY_HEALTH: a weekly cron artifact is not evidence about the deploy in flight.
"""

from __future__ import annotations

from datetime import timedelta

# config/schedules.json coach-history-summarizer#PublicBrief: cron(0 9 ? * MON *) on the Pacific wall clock
# (tests/test_public_brief_deadman.py pins this hour against the schedule row).
DUE_HOUR_PT = 9
GRACE_MINUTES = 60  # the run makes one Haiku call per coach inside a 600 s Lambda ceiling; an hour is ample

SANCTIONED_WARN = ("insufficient_data",)  # statuses that are honest but publish nothing for the coach


def due_cycle(now_pt) -> str:
    """The newest cycle whose Monday run window has closed (a Pacific-aware datetime in, a cycle id out)."""
    from common import public_brief_policy as POL

    cycle = POL.cycle_of(now_pt.date())
    monday = now_pt.replace(hour=DUE_HOUR_PT, minute=0, second=0, microsecond=0) - timedelta(days=now_pt.weekday())
    if now_pt < monday + timedelta(minutes=GRACE_MINUTES):
        cycle = POL.cycle_of(now_pt.date() - timedelta(days=7))
    return cycle


def check_public_brief_liveness(table, check_cls, partition, pt_now, *, coaches=None):
    from coach import public_brief as PB
    from common import public_brief_policy as POL

    c = check_cls("public_brief:cycle_liveness", "Data Freshness", partition)
    cycle = due_cycle(pt_now())
    if cycle < POL.FIRST_CYCLE:
        c.ok(f"public brief pending: the first cycle is {POL.FIRST_CYCLE}; none is due yet")
        return [c]
    expected = list(coaches) if coaches is not None else PB.brief_coaches()
    try:
        stamp = table.get_item(Key={"pk": PB.RUN_PK, "sk": PB.run_sk(cycle)}).get("Item")
    except Exception as exc:  # noqa: BLE001
        c.fail(f"public brief run stamp - DDB error: {exc}")
        return [c]
    if not stamp:
        c.fail(
            f"public brief cycle {cycle}: no run stamp after Monday {DUE_HOUR_PT}:00 PT + {GRACE_MINUTES} min - the scheduled "
            'run never fired or died before stamping (coach-history-summarizer logs; re-run with {"mode": "public_brief"})'
        )
        return [c]
    status = str(stamp.get("status") or "")
    if status == "paused":
        c.warn(f"public brief cycle {cycle}: the budget paused the run ({stamp.get('feature') or 'coach_narrative'}); no brief this week")
        return [c]
    if status != "ok":
        c.fail(f"public brief cycle {cycle}: the run ended '{status}' ({stamp.get('reason') or stamp.get('error') or 'no reason'})")
        return [c]
    results = stamp.get("results") or {}
    bad, warn, written = [], [], []
    for cid in expected:
        r = results.get(cid) or {}
        st, why = str(r.get("status") or "no outcome"), str(r.get("reason") or "")
        if st in ("written", "exists"):
            try:
                row = table.get_item(Key={"pk": f"COACH#{cid}", "sk": POL.brief_sk(cycle)}).get("Item")
            except Exception as exc:  # noqa: BLE001
                bad.append(f"{cid}=brief row unreadable ({exc})")
                continue
            (written if row else bad).append(cid if row else f"{cid}={st} but no brief row")
        elif st == "held" and why == PB.HELD_FOR_INPUTS:
            warn.append(f"{cid}=held, required inputs absent: {', '.join(r.get('missing') or []) or 'unnamed'}")
        elif st == "held" and why == PB.HELD_STALE:
            stale = ", ".join(r.get("stale") or []) or "unnamed"
            warn.append(f"{cid}=held, inputs stale ({stale}: no reading on or after {r.get('fresh_from') or 'the floor'})")
        elif st in SANCTIONED_WARN:
            warn.append(f"{cid}={st}")
        else:
            bad.append(f"{cid}={st}" + (f" ({why})" if why else ""))
    if bad:
        c.fail(f"public brief cycle {cycle}: {len(bad)} of {len(expected)} coach(es) not briefed: " + "; ".join(bad))
    elif warn:
        c.warn(f"public brief cycle {cycle}: {len(written)} of {len(expected)} briefed; " + "; ".join(warn))
    else:
        c.ok(f"public brief cycle {cycle}: all {len(written)} coach(es) briefed")
    return [c]


# ── the pre-run signal: MacroFactor's manual export, needed by the Monday brief ─────────────────────
#: MacroFactor arrives ONLY as a manual export landing in s3://<bucket>/uploads/macrofactor/ (the Dropbox poller or a
#: hand upload; ``ingestion.macrofactor_lambda`` writes the rows). Nothing else refreshes it, so a week without an
#: export holds the nutrition coach's brief (``inputs_stale`` / ``required_inputs_absent``) on Monday. This leg says so
#: from Saturday, while there is still time to upload one. Advisory: it WARNs, never FAILs.
EXPORT_WARN_DAYS = 3  # an export older than this from Saturday on is a WARN
EXPORT_SOURCE = "macrofactor"
UPLOAD_PREFIX = "uploads/macrofactor/"
LOOKBACK_DAYS = 21


def _watch_window(now_pt) -> bool:
    """Saturday, Sunday, and Monday until the run's deadline (09:00 PT + grace)."""
    if now_pt.weekday() in (5, 6):
        return True
    deadline = now_pt.replace(hour=DUE_HOUR_PT, minute=0, second=0, microsecond=0) + timedelta(minutes=GRACE_MINUTES)
    return now_pt.weekday() == 0 and now_pt < deadline


def _next_cycle(now_pt) -> str:
    """The cycle whose Monday run is next (today's, when it is Monday before the deadline)."""
    from common import public_brief_policy as POL

    if _watch_window(now_pt) and now_pt.weekday() == 0:
        return POL.cycle_of(now_pt.date())
    return POL.cycle_of(now_pt.date() + timedelta(days=7))


def _export_coaches(personas=None) -> list:
    """``(coach_id, fresh_within_days)`` for each brief coach with a required input read from MacroFactor — derived from
    the registry and the metric sources, never a hand list."""
    from coach import public_brief as PB
    from common import public_brief_policy as POL

    out = []
    for cid in PB.brief_coaches(personas):
        if any(EXPORT_SOURCE in (POL.metric_sources(m) or []) for m in PB.required_metrics(cid, personas)):
            out.append((cid, PB.fresh_within_days(cid, personas)))
    return out


def _export_rows(table, user_prefix, start, end):
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :s AND :e",
        "ExpressionAttributeValues": {":pk": f"{user_prefix}{EXPORT_SOURCE}", ":s": "DATE#" + start, ":e": "DATE#" + end + "~"},
        "ProjectionExpression": "sk, #d, ingested_at, entries_count, food_log",
        "ExpressionAttributeNames": {"#d": "date"},
    }
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def check_macrofactor_export_age(table, check_cls, partition, pt_now, *, user_prefix="USER#matthew#SOURCE#", bucket=None, personas=None):
    """MacroFactor export age, needed by the Monday brief: the newest upload (the rows' ``ingested_at``) and the newest
    LOGGED day (``coach.grading_quality.is_zero_entry_day``: a summary-only stub is not a logged day). From Saturday
    until Monday's run it WARNs when the export is older than ``EXPORT_WARN_DAYS``, or when the logged days end before
    the brief's freshness floor (so the coach would be held). Reports ages and days only — never an intake value."""
    from datetime import timezone

    from coach.grading_quality import is_zero_entry_day
    from common.pacific_time import parse_iso_utc

    c = check_cls("public_brief:macrofactor_export_age", "Data Freshness", partition)
    now_pt = pt_now()
    coaches = _export_coaches(personas)
    if not coaches:
        c.ok("no brief coach requires a MacroFactor input; the export is not watched")
        return [c]
    start = (now_pt.date() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    try:
        rows = _export_rows(table, user_prefix, start, now_pt.date().isoformat())
    except Exception as exc:  # noqa: BLE001
        c.warn(f"MacroFactor export age unreadable (DDB error: {exc}) - check {UPLOAD_PREFIX} by hand before Monday's brief")
        return [c]
    stamps = sorted(str(r.get("ingested_at")) for r in rows if r.get("ingested_at"))
    logged = sorted(str(r.get("date") or str(r.get("sk", ""))[5:15])[:10] for r in rows if not is_zero_entry_day(r))
    where = f"s3://{bucket}/{UPLOAD_PREFIX}" if bucket else UPLOAD_PREFIX
    cycle = _next_cycle(now_pt)
    names = ", ".join(cid for cid, _ in coaches)
    if not stamps:
        age_txt, age_days = f"no upload in the last {LOOKBACK_DAYS} days", None
    else:
        last = parse_iso_utc(stamps[-1])
        if last is None:
            age_txt, age_days = f"last upload stamp unreadable ({stamps[-1][:32]})", None
        else:
            age_days = (now_pt.astimezone(timezone.utc) - last).total_seconds() / 86400
            age_txt = f"export {age_days:.1f} d old (last upload {stamps[-1][:16]}Z)"
    through = logged[-1] if logged else None
    floors = [cycle_floor for cycle_floor in (_floor(cycle, d) for _cid, d in coaches) if cycle_floor]
    floor = max(floors) if floors else None
    head = f"MacroFactor {age_txt}, logged days through {through or 'none'}; needed by the {cycle} brief ({names})"
    if not _watch_window(now_pt):
        c.ok(head + " - watched from Saturday")
        return [c]
    problems = []
    if age_days is None or age_days > EXPORT_WARN_DAYS:
        problems.append(f"older than {EXPORT_WARN_DAYS} d")
    if floor and now_pt.weekday() != 5 and (through is None or through < floor):
        problems.append(f"no logged day on or after {floor}, so the coach would be held")
    if problems:
        c.warn(head + ": " + "; ".join(problems) + f" - upload a fresh MacroFactor export to {where} before Monday {DUE_HOUR_PT}:00 PT")
    else:
        c.ok(head)
    return [c]


def _floor(cycle, days):
    from coach import public_brief as PB

    return PB.fresh_floor(cycle, days) if days else None
