#!/usr/bin/env python3
"""scripts/scheduled_workflow_registry.py — THE cadence registry for GitHub Actions
scheduled workflows (#3213, epic #2799 — the silent-failure floor).

WHAT THIS IS FOR
----------------
The advisory-watcher machinery (`scripts/advisory_failure_issue.py`, #1447) is armed on
the RESULT of a run. Its documented close policy is literally "auto-closes on the next
green run of this workflow". If the cron never fires, the filer never files, the tracker
issue neither opens nor re-comments, and the surface is silently unwatched — a green
board and an unrun board are indistinguishable from outside.

Measured at Session E boot (2026-08-26T22:09Z): `Visual QA (standalone)` had no run at
all that day, ~1.5h past due, while its auto-filer sat silent because there was no run
to be armed on. GitHub documents that scheduled workflows may be delayed or dropped
under load, and are auto-disabled after 60 days of repository inactivity. That is
expected vendor behaviour — which is exactly why the platform needs its own signal.

THE REGISTRY PRIMITIVE, APPLIED (charter: registry → derivation guard → ratchet →
contract → dead-man)
------------------------------------------------------------------------------------
`lambdas/ingestion/source_registry.py` is the canonical exemplar and this module follows
its shape: ONE dict of per-subject facet rows plus thin derivation helpers, with every
consumer reading the dict rather than growing a second list.

The split between DERIVED and DECLARED is the whole point, and it is deliberate:

  * **cadence is DERIVED, never declared.** `cadence_hours` for every row is computed
    from that workflow's own `on.schedule[].cron` expression by `cron_max_gap_hours()`.
    A hand-typed cadence that drifts from the real `cron:` line is the defect this issue
    is about, one layer down — so there is nowhere to type one.
  * **policy is DECLARED**, because it is a judgment no file can derive: is this
    workflow load-bearing enough to watch (`watched`), how much lateness is normal
    before absence is the better explanation (`grace_hours`, with a `basis` naming the
    measurement it came from), and — for an unwatched row — WHY (`reason`). Silence
    about a scheduled workflow is not a ruling, so `unruled_workflows()` reports any
    scheduled workflow with no row and `orphaned_policy_rows()` reports any row whose
    workflow no longer has a cron. `tests/test_cron_freshness_3213.py` reds on either.

Consumers:
  - `scripts/check_cron_freshness.py`     (the watcher — reports stale/never-fired)
  - `tests/test_cron_freshness_3213.py`   (completeness both directions + mutation proofs)

WHY GRACE WINDOWS ARE MEASURED, NOT ASSUMED (ADR-105 — state the n)
-------------------------------------------------------------------
GitHub's delivered cadence is not the declared cadence, and on this repo the gap is
large. Measured 2026-08-27T04:12Z over the 20 newest scheduled runs of
`deploy-wedge-watch.yml` (declared `*/15`, i.e. 15 minutes): observed inter-run gaps ran
20-209 minutes, median ~47 minutes, and the newest run was 4.3h old at the time of
measurement. Not one gap in the sample was 15 minutes. `Visual QA (standalone)` (declared
20:07 UTC daily) fired at 23:18Z on 2026-08-26 — 3h11m late.

So a grace window sized to "a bit more than the cron period" would page constantly on a
platform that is working. Every `grace_hours` below carries the `basis` it was chosen
from. The signal this registry exists to raise is **a cron that has STOPPED**, not one
that is late; the windows are sized for that and re-measuring them before trusting them
again is the standing instruction.

v1.0.0 — 2026-08-27 (#3213, epic #2799)
"""

from __future__ import annotations

import os
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOW_DIR = os.path.join(REPO_ROOT, ".github", "workflows")

# A repo with zero scheduled workflows would make every derivation below pass vacuously
# (the census's `vacuous-empty` shape). This floor is the population assertion: the
# derivation is only trusted while it finds at least this many scheduled workflows.
# 11 were live on 2026-08-27; the floor is set below that so adding/removing one is not
# a false red, but a derivation that has gone blind and returns [] is.
SCHEDULED_WORKFLOW_FLOOR = 8


# ─────────────────────────────────────────────────────────────────────────────
# The registry. One row per scheduled workflow, keyed by workflow FILENAME (the
# stable key: `name:` is prose and gets edited, the filename is the API path
# segment `/actions/workflows/{file}/runs`).
#
# Facets:
#   watched      — bool. Is this workflow load-bearing enough that its silent
#                  disappearance is a defect worth reporting? Box 5 of #3213: every
#                  scheduled workflow gets an explicit ruling in one direction or the
#                  other, and the ruling carries its argument.
#   grace_hours  — float. Added to the DERIVED cadence to form the report deadline.
#                  Only read when watched.
#   basis        — str. Where grace_hours came from. A number with no basis is the
#                  thing ADR-105 exists to forbid.
#   reason       — str. Why watched, or why deliberately not. Never blank.
# ─────────────────────────────────────────────────────────────────────────────
WATCH_POLICY: dict[str, dict[str, Any]] = {
    # ── watched ──────────────────────────────────────────────────────────────
    "visual-qa.yml": {
        "watched": True,
        "grace_hours": 14.0,
        "basis": "declared 20:07Z daily; observed fires 20:31-23:18Z over 8 runs (2026-08-19..26), "
        "worst lateness 3h11m. 14h clears that ~4x and still reports before the SECOND "
        "daily fire is missed.",
        "reason": "The origin case. It is the daily live-site reader-truth + Playwright sweep, it "
        "gates nothing, and its #1447 auto-filer is armed on a run's RESULT — so a cron "
        "that stops leaves the site's only daily semantic QA dark with an empty (or "
        "stale-open) tracker issue that reads as healthy.",
    },
    "operating-calendar.yml": {
        "watched": True,
        "grace_hours": 14.0,
        "basis": "same class as visual-qa (daily, mid-afternoon UTC); observed 16:37Z against a "
        "declared 15:40Z on 2026-08-26 (~57m late).",
        "reason": "This IS the platform's dead-man for judgment rituals (#2832, charter primitive "
        "5) — an overdue review reds this run. A dead-man that stops firing reports "
        "'nothing overdue' by silence, which is the exact inversion it was built to "
        "prevent. Watching the watchman is the highest-value row here.",
    },
    "deploy-wedge-watch.yml": {
        "watched": True,
        "grace_hours": 8.0,
        "basis": "declared */15; MEASURED 20-209 min between the 20 newest scheduled runs "
        "(2026-08-26, median ~47 min) and 4.3h since the newest at 2026-08-27T04:12Z. "
        "GitHub throttles high-frequency crons hard, so grace is set from the observed "
        "tail, not the declared period: 8h is ~2.3x the worst observed gap.",
        "reason": "The fifth-recurrence escape hatch for a wedged ci-cd run (#2052) — it exists "
        "to observe the pipeline from OUTSIDE. If it stops, a stranded deploy sits "
        "invisible for exactly as long as nobody looks, which is the incident it was "
        "built after.",
    },
    "config-drift.yml": {
        "watched": True,
        "grace_hours": 14.0,
        "basis": "daily class; observed 16:34Z against a declared 15:20Z on 2026-08-26.",
        "reason": "Config twin drift is a silent-until-it-matters class: nothing else notices that "
        "the deployed config and the repo copy disagree. An unrun drift check is "
        "indistinguishable from a clean one.",
    },
    "hae-webhook-ingress-drift.yml": {
        "watched": True,
        "grace_hours": 14.0,
        "basis": "daily class; observed 16:55Z against a declared 16:10Z on 2026-08-26.",
        "reason": "Same shape as config-drift, on the webhook ingest path — the near-real-time "
        "sources (CGM, water, BP, State of Mind) have no other daily structural check.",
    },
    "remediation-agent.yml": {
        "watched": True,
        "grace_hours": 12.0,
        "basis": "Mon/Wed/Fri -> derived worst gap 72h (Fri->Mon); named in #3213 as ~80 min late "
        "on 2026-08-26. 12h is one sixth of the cadence — enough that a merely-late run "
        "never reports, little enough that a wholly missed Monday does.",
        "reason": "The triage channel itself. Its curated email is how alarms, failed CI, DLQ "
        "depth and QA-smoke results reach a human at all — including, per its own "
        "design note in operating-calendar.yml, red scheduled workflows. If IT stops, "
        "the reporting path for everything else stops with it and nothing says so.",
    },
    "golden-brief-eval.yml": {
        "watched": True,
        "grace_hours": 24.0,
        "basis": "weekly (Mon) -> derived 168h cadence; grace 24h = one day, so a wholly skipped "
        "Monday reports on Tuesday rather than waiting a second week.",
        "reason": "Enrolled in the #1447 advisory filer, so it carries the armed-on-result defect "
        "by construction. It is the weekly voice/gate drift check on the daily brief — "
        "the surface a reader actually receives.",
    },
    "fresh-eyes.yml": {
        "watched": True,
        "grace_hours": 24.0,
        "basis": "weekly (Sun) -> derived 168h cadence; same one-day grace as golden-brief-eval.",
        "reason": "Also enrolled in the #1447 advisory filer, same armed-on-result defect. It is "
        "the only scheduled discovery pass; its absence produces no output to miss, "
        "which is precisely why nobody would notice.",
    },
    # ── deliberately NOT watched (each with its argument) ─────────────────────
    "codeql.yml": {
        "watched": False,
        "grace_hours": None,
        "basis": None,
        "reason": "DELIBERATELY UNWATCHED — not because it does not matter, but because GitHub "
        "already owns this absence. CodeQL results are surfaced on the repo's Security "
        "tab with their own scan-staleness state, and code scanning re-runs on every "
        "push and pull_request here, so the weekly cron is a backstop rather than the "
        "only fire. Watching it from here would be a second copy of a signal GitHub "
        "reports natively. RE-RULE IF: the push/PR triggers are ever removed, leaving "
        "the cron as the sole scan trigger.",
    },
    "webkit-mobile-qa.yml": {
        "watched": True,
        "grace_hours": 24.0,
        "basis": "weekly (Tue 21:37Z) -> derived 168h cadence; grace 24h = one day, same as the other "
        "weekly rows (golden-brief-eval, fresh-eyes), so a wholly skipped Tuesday reports "
        "on Wednesday rather than waiting a second week.",
        "reason": "RE-RULED 2026-08-30 (#3277). The 2026-08-27 ruling called its coverage 'a strict "
        "subset of a watched row' — false: it was the ONLY sweep that ever ran axe in a "
        "390px context (every gating Chromium run audited desktop only), and it had been "
        "reporting exactly the 390px scrollable-region-focusable finding every week to "
        "a surface that swallowed it (SNS publish failing AuthorizationError — the "
        "diagnosis role has no sns: grant, deliberately not added — and no #1447 filer). "
        "#3277 wired the filer (a red run now files a tracked issue) and gave the gating "
        "sweeps their own mobile axe pass, but this lane stays the one place the "
        "iOS-Safari ENGINE is driven at all; a cron that quietly stops here is a week of "
        "engine coverage lost with nothing to say so. Enrolled in the #1447 filer, so it "
        "carries the armed-on-result defect by construction — the reason every enrolled "
        "row is watched.",
    },
    "eval-harvest.yml": {
        "watched": False,
        "grace_hours": None,
        "basis": None,
        "reason": "DELIBERATELY UNWATCHED — monthly cadence makes the derived deadline ~31 days, "
        "so this instrument could not report a stop in less than a month; the signal "
        "would arrive later than the attended step it feeds. Its output is a run "
        "ARTIFACT proposed for HUMAN review (#812 — candidates are never auto-"
        "committed), so a missed month is noticed by the human who goes looking for "
        "candidates and finds none, which is a faster and more reliable detector than "
        "this one. n=1 scheduled run in its whole history at time of ruling. "
        "RE-RULE IF: harvesting is ever automated past the human review step.",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Cron derivation. Everything below computes FROM the workflow's own `cron:` line.
# ─────────────────────────────────────────────────────────────────────────────


def _field(spec: str, lo: int, hi: int) -> set[int]:
    """Expand one cron field (`*`, `*/n`, `a`, `a-b`, `a-b/n`, comma lists) to its values."""
    values: set[int] = set()
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            raise ValueError(f"empty cron field element in {spec!r}")
        step = 1
        if "/" in part:
            part, _, step_s = part.partition("/")
            step = int(step_s)
            if step < 1:
                raise ValueError(f"cron step must be >= 1 in {spec!r}")
        if part == "*":
            start, end = lo, hi
        elif "-" in part.lstrip("-"):
            start_s, _, end_s = part.partition("-")
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(part)
        if start < lo or end > hi or start > end:
            raise ValueError(f"cron field {part!r} out of range [{lo},{hi}] in {spec!r}")
        values.update(range(start, end + 1, step))
    if not values:
        raise ValueError(f"cron field {spec!r} expanded to nothing")
    return values


def _dow_set(spec: str) -> set[int]:
    """Cron day-of-week, normalised to Python weekday() (Mon=0..Sun=6).

    Cron numbers Sunday as BOTH 0 and 7; both must map to Python 6 or a `* * * * 0`
    weekly job silently matches Monday and the derived cadence is wrong by a day.
    """
    raw = _field(spec, 0, 7)
    return {(v - 1) % 7 for v in raw}


def cron_max_gap_hours(expr: str, horizon_days: int = 800) -> float:
    """The LONGEST gap, in hours, between two consecutive fires of `expr`. Pure.

    This is the cadence a freshness check needs: `45 14 * * 1,3,5` fires three times a
    week but its worst legitimate silence is 72h (Fri -> Mon), and a deadline built from
    the average would report every weekend. Likewise `23 16 3 * *` is "monthly" but its
    worst gap is 31 days, not 30.

    Computed exactly, not sampled: the fire times of a cron expression are
    (matching day) x (matching minute-of-day), so the worst gap is either the largest
    hole between two minute-slots inside one day, or the hole from the last slot of one
    matching day to the first slot of the next matching day. Both are O(slots + days);
    enumerating every fire time would be up to ~1.15M datetimes for a `*/1` expression.

    `horizon_days` must span at least two matching days — 800 covers a 31-day month
    boundary, a leap February, and `* * * * *`-style rarities like `0 0 29 2 *`. A cron
    that fires fewer than twice in that horizon raises rather than guessing.
    """
    fields = str(expr).split()
    if len(fields) != 5:
        raise ValueError(f"cron expression must have 5 fields, got {len(fields)}: {expr!r}")
    minute_s, hour_s, dom_s, month_s, dow_s = fields

    minutes = sorted(_field(minute_s, 0, 59))
    hours = sorted(_field(hour_s, 0, 23))
    months = _field(month_s, 1, 12)
    slots = sorted(h * 60 + m for h in hours for m in minutes)

    # Vixie-cron day semantics, which GitHub follows: when BOTH day-of-month and
    # day-of-week are restricted the day matches if EITHER matches (an OR, not an AND).
    # When one is `*` the other governs alone. Getting this backwards turns a
    # `0 0 1 * 1` expression from "1st or Monday" into "the 1st, if it is a Monday",
    # which understates the cadence by ~7x.
    dom_restricted = dom_s.strip() != "*"
    dow_restricted = dow_s.strip() != "*"
    doms = _field(dom_s, 1, 31)
    dows = _dow_set(dow_s)

    import datetime as _dt

    epoch = _dt.date(2026, 1, 1)
    days: list[int] = []
    for offset in range(horizon_days):
        day = epoch + _dt.timedelta(days=offset)
        if day.month not in months:
            continue
        if dom_restricted and dow_restricted:
            day_ok = day.day in doms or day.weekday() in dows
        elif dom_restricted:
            day_ok = day.day in doms
        elif dow_restricted:
            day_ok = day.weekday() in dows
        else:
            day_ok = True
        if day_ok:
            days.append(offset)

    if len(days) < 2 and len(slots) < 2:
        raise ValueError(f"cron {expr!r} fires fewer than twice in {horizon_days} days — cadence undeterminable")

    intra = max((b - a for a, b in zip(slots, slots[1:])), default=0)
    cross = max(((d2 - d1) * 1440 + slots[0] - slots[-1] for d1, d2 in zip(days, days[1:])), default=0)
    return max(intra, cross) / 60.0


def workflow_crons(yaml_text: str) -> list[str]:
    """Every `on.schedule[].cron` expression in a workflow document. Pure — takes text.

    Kept text-in so tests can drive it with synthetic workflows and so nothing here
    reads a path the caller did not choose.
    """
    import yaml  # local import: keeps the module importable where PyYAML is absent

    doc = yaml.safe_load(yaml_text) or {}
    if not isinstance(doc, dict):
        return []
    # PyYAML resolves a bare `on:` key to the boolean True (YAML 1.1 truthiness), which
    # is why the fallback below is not paranoia — every workflow in this repo hits it.
    triggers = doc.get("on", doc.get(True))
    if not isinstance(triggers, dict):
        return []
    schedule = triggers.get("schedule") or []
    if not isinstance(schedule, list):
        return []
    return [str(e["cron"]).strip() for e in schedule if isinstance(e, dict) and e.get("cron")]


def discover_scheduled_workflows(workflow_dir: str | None = None) -> dict[str, dict[str, Any]]:
    """Every workflow in `workflow_dir` carrying a `schedule:` trigger, with its facets.

    Returns {filename: {file, name, crons, cadence_hours, watched, grace_hours, basis,
    reason, deadline_hours}}. `cadence_hours` is DERIVED from `crons`; `deadline_hours`
    is cadence + grace and is None for an unwatched row. A workflow with no policy row
    comes back with `watched=None` — the unruled state, which `unruled_workflows()`
    turns into a finding rather than a default.
    """
    import yaml  # noqa: F401  (imported for the clear ImportError at the top of the call)

    directory = workflow_dir or WORKFLOW_DIR
    found: dict[str, dict[str, Any]] = {}
    for entry in sorted(os.listdir(directory)):
        if not entry.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(directory, entry), encoding="utf-8") as fh:
            text = fh.read()
        crons = workflow_crons(text)
        if not crons:
            continue
        doc = yaml.safe_load(text) or {}
        cadence = min(cron_max_gap_hours(c) for c in crons)
        policy = WATCH_POLICY.get(entry)
        watched = None if policy is None else bool(policy.get("watched"))
        grace = (policy or {}).get("grace_hours")
        found[entry] = {
            "file": entry,
            "name": (doc.get("name") if isinstance(doc, dict) else None) or entry,
            "crons": crons,
            "cadence_hours": cadence,
            "watched": watched,
            "grace_hours": grace,
            "basis": (policy or {}).get("basis"),
            "reason": (policy or {}).get("reason"),
            "deadline_hours": (cadence + float(grace)) if (watched and grace is not None) else None,
        }
    return found


def unruled_workflows(workflow_dir: str | None = None) -> list[str]:
    """Scheduled workflows with NO row in WATCH_POLICY — box 5's "silence is not a ruling"."""
    return sorted(f for f, row in discover_scheduled_workflows(workflow_dir).items() if row["watched"] is None)


def orphaned_policy_rows(workflow_dir: str | None = None) -> list[str]:
    """Rows in WATCH_POLICY whose workflow no longer exists or no longer has a `cron:`.

    The other direction of the same rot: a registry that keeps ruling on a workflow that
    is gone reads as coverage it does not have.
    """
    live = set(discover_scheduled_workflows(workflow_dir))
    return sorted(f for f in WATCH_POLICY if f not in live)


def watched_workflows(workflow_dir: str | None = None) -> dict[str, dict[str, Any]]:
    """The rows the watcher actually reports on: watched=True, with a derived deadline."""
    return {f: row for f, row in discover_scheduled_workflows(workflow_dir).items() if row["watched"]}
