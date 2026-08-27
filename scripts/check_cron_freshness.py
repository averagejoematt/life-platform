#!/usr/bin/env python3
"""scripts/check_cron_freshness.py — the dead-man for GitHub's cron scheduler (#3213,
epic #2799).

THE DEFECT THIS OWNS
--------------------
"A scheduled workflow stopped firing, and its absence is itself dark."

`scripts/advisory_failure_issue.py` (#1447) owns a scheduled run that FAILS. Nothing
owned a scheduled run that never happens. The two are different failures and this file
deliberately covers only the second — see NOT DUPLICATING THE ADVISORY FILER below.

WHAT IT DOES
------------
For every workflow ruled `watched` in `scripts/scheduled_workflow_registry.py`, ask the
Actions API for the newest run whose `event` is `schedule`, and compare its age against
that workflow's DERIVED cadence plus its declared grace window. Three verdicts, and the
first two are kept apart on purpose (#3213 box 3):

  ok           the newest scheduled run is inside cadence + grace
  stale        it fired before, and the newest fire is older than cadence + grace
  never-fired  the API reports ZERO scheduled runs for this workflow, ever — a
               workflow whose cron has never once been delivered (a bad cron
               expression, a disabled workflow, a file that was renamed). This is not
               "late"; nothing will ever auto-close it, and it reads identically to a
               healthy workflow on every other instrument in the repo.

Plus two states about the instrument rather than the subject, because a watcher that
cannot say "I could not look" is a watcher that reports health when it is blind:

  unverified   the API call for this workflow failed (auth, rate limit, network)
  unruled /    the registry and .github/workflows/ disagree — a scheduled workflow with
  orphaned     no ruling, or a ruling for a workflow that no longer has a cron. Reported
               as a finding, not skipped: that drift is this issue one layer down.

WHY THIS RUNS ON `push`, NOT ON A SCHEDULE (#3213 box 2 — the load-bearing constraint)
--------------------------------------------------------------------------------------
`.github/workflows/cron-freshness.yml` triggers on `push: branches: [main]` and
`workflow_dispatch`. It must NOT trigger on `schedule`, and the reason is not stylistic:

  * GitHub's two documented ways of silencing cron both act on the `schedule` trigger
    as a class. Scheduled runs "may be delayed or dropped during periods of high load",
    and scheduled workflows are AUTO-DISABLED after 60 days of repository inactivity.
    Either event silences every cron in the repo at once. A watcher on `schedule` is
    inside that blast radius and would go dark simultaneously with the thing it watches
    — it would be unable to detect its own absence, which is exactly the shape of the
    defect.
  * `push` is delivered by the repository-event path, not the cron scheduler. The
    inactivity auto-disable in particular CANNOT silence it, because a push IS the
    activity whose absence triggers that disable.

The residuals, stated rather than hidden:
  1. A push to main can mint zero workflow runs — the event-swallow class (#2662). That
     costs this check one push, not permanently: it holds no state between runs, so the
     next push re-evaluates from scratch. Bounded by push frequency, not by the length
     of the outage.
  2. If main receives no push for longer than a watched workflow's deadline, nothing
     reports. Bounded two ways: main takes multiple pushes on a normal working day, and
     `workflow_dispatch` plus this script's own CLI (run at session boot, offline-safe)
     cover the attended path. In a repo genuinely dormant for weeks the crons are being
     auto-disabled by GitHub anyway and there is no live surface to protect.
  3. This check reads GitHub's own API to learn about GitHub's own scheduler. An API
     that lies about run history defeats it. Not mitigated; it is the same trust
     boundary every other Actions-reading gate in this repo sits on.

NOT DUPLICATING THE ADVISORY FILER (#3213 box 3)
------------------------------------------------
`classify()` takes a TIMESTAMP and a deadline. It is not passed the run's `conclusion`
and has no parameter that could carry one, so "fired recently and failed" is structurally
indistinguishable from "fired recently and passed" here — both are `ok`. That is not a
convention to be remembered; it is the function signature, and
`tests/test_cron_freshness_3213.py` pins it with a failed-but-fresh run.

The workflow that runs this appends the SAME `.github/actions/advisory-failure-issue`
composite every other advisory workflow uses, under its own slug (`cron-freshness`). So
a detected stop becomes one deduped tracked issue that auto-closes on the next clean
run, reusing the filer rather than growing a second issue-filing path — and the slug
keeps it from ever colliding with the watched workflow's own auto-filed issue.

EXIT STATUS
-----------
  0  every watched workflow is inside its window (or --allow-unverified absorbed a
     blind run)
  1  at least one watched workflow is stale / never-fired, or the registry and
     .github/workflows/ have drifted apart
  2  the instrument is DARK — nothing could be verified at all. Deliberately not 0:
     "I could not look" reported as a pass is the single most repeated failure in this
     repo's incident log. Two distinct causes, and `--allow-unverified` covers only the
     first, on purpose:
       * every Actions lookup failed (no `gh`, no auth, rate limit, offline) — a
         property of the ENVIRONMENT the caller is in, so the offline local path may
         opt out with `--allow-unverified`, which is an explicit choice at that call
         site rather than a default;
       * PyYAML is not importable, so not one workflow could be PARSED — a broken
         install, not a blind network. That stays 2 with or without the flag: a run
         that cannot read its own subjects has no board to report on at all.

USAGE
-----
    python3 scripts/check_cron_freshness.py                    # gate
    python3 scripts/check_cron_freshness.py --json             # machine-readable
    python3 scripts/check_cron_freshness.py --allow-unverified # offline / no gh auth

v1.0.0 — 2026-08-27 (#3213, epic #2799)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scheduled_workflow_registry import (  # noqa: E402
    SCHEDULED_WORKFLOW_FLOOR,
    discover_scheduled_workflows,
    orphaned_policy_rows,
    unruled_workflows,
)

# Verdict vocabulary — module constants so the tests, the render and any future
# consumer share one spelling (check_main_green.py's shape).
OK = "ok"
STALE = "stale"
NEVER_FIRED = "never-fired"
UNVERIFIED = "unverified"
UNRULED = "unruled"
ORPHANED = "orphaned"

REPORTABLE = (STALE, NEVER_FIRED, UNRULED, ORPHANED)


# ── pure classification (offline-tested) ─────────────────────────────────────


def classify(newest_created_at: str | None, deadline_hours: float, now: datetime) -> tuple[str, float | None]:
    """(verdict, age_hours) for one watched workflow.

    `newest_created_at` is the ISO timestamp of the newest `event: schedule` run, or
    None when the API reported no scheduled run at all.

    THE SIGNATURE IS THE CONTRACT (#3213 box 3): there is no `conclusion` parameter, so
    this function cannot express an opinion about whether the run passed. A red run that
    happened on time is `ok` here and belongs to scripts/advisory_failure_issue.py.
    """
    if newest_created_at is None:
        return NEVER_FIRED, None
    fired = _parse_iso(newest_created_at)
    if fired is None:
        # An unparseable timestamp is not evidence of health.
        return UNVERIFIED, None
    age = (now - fired).total_seconds() / 3600.0
    return (STALE if age > deadline_hours else OK), age


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evaluate(rows: dict[str, dict[str, Any]], newest_by_file: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """One finding per WATCHED row. Pure: `newest_by_file` is injected, never fetched.

    A file mapped to the sentinel `False` means "the lookup itself failed" (as opposed
    to None, which means "the API answered, and the answer was zero runs"). Collapsing
    those two would let a rate-limited run report `never-fired` on a healthy workflow —
    the reverse of this instrument's whole purpose.
    """
    findings: list[dict[str, Any]] = []
    for name, row in sorted(rows.items()):
        if not row.get("watched"):
            continue
        lookup = newest_by_file.get(name, False)
        if lookup is False:
            verdict, age = UNVERIFIED, None
        else:
            verdict, age = classify(lookup, float(row["deadline_hours"]), now)
        findings.append(
            {
                "file": name,
                "name": row["name"],
                "crons": row["crons"],
                "cadence_hours": round(float(row["cadence_hours"]), 2),
                "grace_hours": row["grace_hours"],
                "deadline_hours": round(float(row["deadline_hours"]), 2),
                "newest_scheduled_run": lookup if lookup is not False else None,
                "age_hours": None if age is None else round(age, 2),
                "verdict": verdict,
            }
        )
    return findings


def render(findings: list[dict[str, Any]], unruled: list[str], orphaned: list[str], scheduled_total: int) -> tuple[int, str]:
    """(exit_code, report). Pure — the whole verdict is decided here and unit-tested."""
    lines: list[str] = []
    add = lines.append
    add("=" * 78)
    add("SCHEDULED-WORKFLOW CADENCE WATCH — #3213 (a cron that stopped, not one that failed)")
    add("=" * 78)

    if scheduled_total < SCHEDULED_WORKFLOW_FLOOR:
        add("")
        add(f"  DARK: derived only {scheduled_total} scheduled workflow(s), floor is {SCHEDULED_WORKFLOW_FLOOR}.")
        add("  The derivation has gone blind — this is NOT a clean board. Fix the discovery,")
        add("  do not lower the floor.")
        return 2, "\n".join(lines)

    verdicts = [f["verdict"] for f in findings]
    n_watched = len(findings)
    n_unverified = verdicts.count(UNVERIFIED)
    reportable = [f for f in findings if f["verdict"] in REPORTABLE]

    add("")
    add(f"  scheduled workflows found   n = {scheduled_total}   (derived from .github/workflows/*.yml)")
    add(f"  watched by the registry     n = {n_watched}")
    add(f"  deliberately unwatched      n = {scheduled_total - n_watched}   (each with a stated reason)")
    add(f"  could NOT be verified       n = {n_unverified}")
    add("")

    for f in findings:
        mark = {OK: "  ok  ", STALE: " STALE", NEVER_FIRED: " NEVER", UNVERIFIED: " ????? "}.get(f["verdict"], " ???? ")
        age = "n/a" if f["age_hours"] is None else f"{f['age_hours']}h"
        add(
            f"  [{mark}] {f['file']:<34} newest sched run {age} ago "
            f"(deadline {f['deadline_hours']}h = cadence {f['cadence_hours']}h + grace {f['grace_hours']}h)"
        )
        if f["verdict"] == STALE:
            add(f"           cron {f['crons']} — newest scheduled run {f['newest_scheduled_run']}")
            add("           GitHub has not delivered this cron inside its window. This is an")
            add("           ABSENCE, not a failure: the #1447 advisory filer is armed on a run's")
            add("           result and has nothing to be armed on.")
        if f["verdict"] == NEVER_FIRED:
            add(f"           cron {f['crons']} — the API reports ZERO `event: schedule` runs, ever.")
            add("           Check the cron expression, and whether the workflow is disabled.")
        if f["verdict"] == UNVERIFIED:
            add("           the Actions API lookup failed — this row is UNKNOWN, not healthy.")

    for f in unruled:
        add(f"  [UNRULED] {f} has a `cron:` and no row in WATCH_POLICY.")
        add("           Silence about a scheduled workflow is not a ruling (#3213 box 5):")
        add("           add a row saying watched=True with a grace window, or watched=False")
        add("           with the reason it is safe to lose.")
    for f in orphaned:
        add(f"  [ORPHANED] WATCH_POLICY rules on {f}, which has no `cron:` (or no longer exists).")
        add("           A registry that rules on a workflow that is gone reads as coverage")
        add("           it does not have.")

    add("")
    if n_watched and n_unverified == n_watched and not reportable and not unruled and not orphaned:
        add("  DARK: not one watched workflow could be verified. `gh` is missing, unauthenticated,")
        add("  rate-limited or offline. This is NOT a clean board — pass --allow-unverified only")
        add("  when you have decided a blind run is acceptable at this call site.")
        return 2, "\n".join(lines)
    if reportable or unruled or orphaned:
        add(f"  VERDICT: {len(reportable) + len(unruled) + len(orphaned)} finding(s). See above.")
        return 1, "\n".join(lines)
    add("  VERDICT: every watched scheduled workflow has fired inside its window.")
    if n_unverified:
        add(f"  ({n_unverified} row(s) unverified — their state is unknown, not green.)")
    return 0, "\n".join(lines)


# ── IO (thin, everything above is pure) ──────────────────────────────────────


def newest_scheduled_run(workflow_file: str) -> Any:
    """Newest `event: schedule` run's `created_at`, None if the API says there are none,
    or the sentinel False if the lookup itself failed."""
    try:
        out = subprocess.run(
            [
                "gh",
                "api",
                f"repos/{{owner}}/{{repo}}/actions/workflows/{workflow_file}/runs?event=schedule&per_page=1",
                "--jq",
                '(.workflow_runs[0].created_at) // ""',
            ],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        ).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return False
    return out or None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true", help="machine-readable findings on stdout")
    ap.add_argument(
        "--allow-unverified",
        action="store_true",
        help="a LOOKUP-blind run exits 0 instead of 2 (offline / no gh auth). Explicit by design. "
        "Does NOT cover an unimportable PyYAML — that is a broken install, not a blind network.",
    )
    args = ap.parse_args(argv)

    try:
        rows = discover_scheduled_workflows()
        unruled, orphaned = unruled_workflows(), orphaned_policy_rows()
    except ImportError:
        # NOT downgradable by --allow-unverified, deliberately: without a parser there
        # are no subjects, no registry cross-check and no board — nothing to opt out of.
        print("DARK: PyYAML is not importable, so no workflow could be parsed. NOT a clean board.", file=sys.stderr)
        return 2

    now = datetime.now(timezone.utc)
    newest = {name: newest_scheduled_run(name) for name, row in rows.items() if row.get("watched")}
    findings = evaluate(rows, newest, now)
    code, report = render(findings, unruled, orphaned, len(rows))

    if args.json:
        print(json.dumps({"now": now.isoformat(), "exit": code, "findings": findings, "unruled": unruled, "orphaned": orphaned}, indent=2))
    else:
        print(report)

    if code == 2 and args.allow_unverified:
        print("\n(--allow-unverified: the blind run is being treated as non-fatal at this call site.)")
        return 0
    return code


if __name__ == "__main__":
    sys.exit(main())
