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
    coach was held because its required inputs were absent (e.g. no glucose readings), or had too few readings.
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
