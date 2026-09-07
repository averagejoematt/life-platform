#!/usr/bin/env python3
"""scripts/check_job_timeout_headroom.py — #3678 box 2: a `timeout-minutes` ceiling
must not sit inside its own job's noise band.

THE DEFECT THIS CLOSES
-----------------------
`Collect + deploy-critical + format` carried `timeout-minutes: 15` against an
observed 13m57s-15m22s band. The config's own comment asked for a re-measurement
before the number was trusted again — "Re-measure before trusting this number
again; do not bump silently" — and that instruction sat un-obeyed until #3678.
A comment cannot enforce itself: this is the SCRIPT the comment asked for, so a
THIRD stale-budget instance (after #3134's suite budget and #3403's Unit-Tests
budget-at-the-mean) cannot land silently the way the first two did.

THE RULE, ONE LINE
-------------------
For every job in every `.github/workflows/*.yml` that declares `timeout-minutes`
(enumerated from `ci_job_timeouts.py` — never hand-listed, so the census cannot
go stale by omission): measure that job's own duration over its trailing
`--window` completed runs, take the p95, and RED when
`timeout_minutes < p95_minutes * HEADROOM_MULTIPLIER`.

WHY p95 OF *GENUINE* COMPLETIONS, NOT EVERY OBSERVATION
---------------------------------------------------------
A run whose own job conclusion is `cancelled` was, by construction, killed AT (or
just past) the very ceiling this check evaluates — its "duration" is CENSORED,
not observed: the job might have needed 20 minutes or 90, the timeout never let
it say which. Folding a censored sample into the percentile would make a job
that is ACTUALLY badly under-budgeted look merely borderline (its worst cases get
truncated to the ceiling instead of counted at their real, larger cost). Only
samples where the job's own conclusion is `success` or `failure` — it ran to a
real end, on its own terms — are genuine completions and go into the percentile.
A job needs at least `MIN_GENUINE_SAMPLES` of those before this check asserts
anything about it; below that it is reported `INSUFFICIENT-DATA`, never silently
skipped and never a false RED.

WHY HEADROOM_MULTIPLIER = 1.2, STATED
---------------------------------------
The fast-lane job's ORIGINAL derivation (`pr-checks.yml`'s own comment, since
superseded) used "observed max x 1.23" — this check keeps that idiom's shape
(a ~20% margin over the worst normal case) but anchors it to p95 of genuine
completions rather than a single observed max, because a max is one data point
and a p95 is a distribution: the whole point of #3678 is that a number derived
from ONE observation goes stale the moment the suite grows past it again. 1.2 is
a round, deliberately-chosen value, not a re-derivation of 1.23 — recorded here
so the next re-measurement changes ONE constant, not a comment buried in a YAML
file three layers down.

MUST-FAIL PROOF (the positive control, #3678's own acceptance bar)
--------------------------------------------------------------------
`tests/test_check_job_timeout_headroom_3678.py::test_reds_on_todays_stale_15_minute_ceiling_positive_control`
feeds this module SYNTHETIC durations shaped exactly like the real trailing-30-run
measurement taken 2026-09-07 (genuine p95 ≈ 891.6s = 14.86min) against the
UNCHANGED `timeout-minutes: 15` and asserts `main()` returns 1 with `RED` printed
for `Collect + deploy-critical + format` — watched fail BEFORE `pr-checks.yml`'s
ceiling was raised in the same PR that adds this file.

USAGE
  python3 scripts/check_job_timeout_headroom.py                 # live, gh-backed, all jobs
  python3 scripts/check_job_timeout_headroom.py --window 30
  python3 scripts/check_job_timeout_headroom.py --json
  python3 scripts/check_job_timeout_headroom.py --job "Collect + deploy-critical + format"

Exit codes: 0 = every measured job clears its headroom (or nothing to assert
yet); 1 = at least one job's `timeout-minutes` sits below its own p95 x headroom,
OR the population floor was breached (the derivation itself looks broken).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from typing import Any, Callable

_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import ci_job_timeouts  # noqa: E402 — must follow the sys.path insert above

REPO = "averagejoematt/life-platform"

HEADROOM_MULTIPLIER = 1.2
DEFAULT_WINDOW = 30  # trailing completed runs — matches the issue's own Set query
MIN_GENUINE_SAMPLES = 5

# A repo with zero timeout-minutes jobs would make this check pass vacuously.
# 10 were live on 2026-09-07 (`python3 scripts/ci_job_timeouts.py`); the floor sits
# below that so adding/removing one job is not a false red, but a derivation gone
# blind (finds nothing) is.
JOB_TIMEOUT_FLOOR = 5

_TS_FMT = "%Y-%m-%dT%H:%M:%SZ"

RunLister = Callable[[str, int], list]
JobsFetcher = Callable[[Any], list | None]


def _duration_seconds(job: dict) -> float | None:
    started, completed = job.get("started_at"), job.get("completed_at")
    if not started or not completed:
        return None
    try:
        return (datetime.strptime(completed, _TS_FMT) - datetime.strptime(started, _TS_FMT)).total_seconds()
    except (ValueError, TypeError):
        return None


def percentile(values: list[float], pct: float) -> float | None:
    """Linear-interpolated percentile (the common "linear" method). Pure, no numpy dep."""
    if not values:
        return None
    vals = sorted(values)
    if len(vals) == 1:
        return vals[0]
    k = (pct / 100.0) * (len(vals) - 1)
    f = int(k)
    c = min(f + 1, len(vals) - 1)
    if f == c:
        return vals[f]
    return vals[f] * (c - k) + vals[c] * (k - f)


def measure_job_durations(
    workflow_file: str, job_name: str, window: int, run_lister: RunLister, jobs_fetcher: JobsFetcher
) -> list[tuple[str | None, str | None, float | None]]:
    """`[(run_conclusion, job_conclusion, duration_seconds), ...]` for `job_name`'s
    trailing `window` completed runs of `workflow_file`.

    Pure by injection: `run_lister(workflow_file, window) -> [{"databaseId",
    "conclusion", "status"}, ...]` and `jobs_fetcher(run_id) -> jobs | None` are
    the only impure parts, faked in tests exactly like `ci_run_verdicts.fetch_run_jobs`.
    """
    runs = run_lister(workflow_file, window) or []
    out: list[tuple[str | None, str | None, float | None]] = []
    for r in runs:
        if not isinstance(r, dict) or r.get("status") != "completed":
            continue
        jobs = jobs_fetcher(r.get("databaseId"))
        for j in jobs or []:
            if not isinstance(j, dict) or j.get("name") != job_name:
                continue
            out.append((r.get("conclusion"), j.get("conclusion"), _duration_seconds(j)))
    return out


def genuine_durations(samples: list[tuple]) -> list[float]:
    """Durations from samples that ran to a real end (`success`/`failure`), never
    `cancelled` — see the module docstring for why a censored sample is excluded
    rather than counted at its truncated value."""
    return [d for (_run_c, job_c, d) in samples if job_c in ("success", "failure") and d is not None]


def evaluate_job(
    entry: dict, samples: list[tuple], headroom_multiplier: float = HEADROOM_MULTIPLIER, min_samples: int = MIN_GENUINE_SAMPLES
) -> dict:
    """One report row for a single job's declared ceiling vs. its measured p95. Pure."""
    name, file_ = entry["job_name"], entry["file"]
    ceiling = entry["timeout_minutes"]
    if entry.get("templated"):
        return {"job_name": name, "file": file_, "timeout_minutes": ceiling, "status": "SKIPPED-TEMPLATED", "n_genuine": 0}
    genuine = genuine_durations(samples)
    if len(genuine) < min_samples:
        return {
            "job_name": name,
            "file": file_,
            "timeout_minutes": ceiling,
            "status": "INSUFFICIENT-DATA",
            "n_genuine": len(genuine),
            "n_total": len(samples),
        }
    p95_seconds = percentile(genuine, 95)
    p95_minutes = p95_seconds / 60.0
    required_minutes = p95_minutes * headroom_multiplier
    ok = ceiling >= required_minutes
    return {
        "job_name": name,
        "file": file_,
        "timeout_minutes": ceiling,
        "p95_minutes": round(p95_minutes, 2),
        "headroom_multiplier": headroom_multiplier,
        "required_minutes": round(required_minutes, 2),
        "n_genuine": len(genuine),
        "n_total": len(samples),
        "status": "OK" if ok else "RED",
    }


def _format_report_line(rep: dict) -> str:
    status = rep["status"]
    name, file_ = rep["job_name"], rep["file"]
    if status == "SKIPPED-TEMPLATED":
        return f"⏭️  {file_}: {name!r} — templated job name, cannot be matched to a real check-run (not asserted)"
    if status == "INSUFFICIENT-DATA":
        return f"❔ {file_}: {name!r} — only {rep['n_genuine']} genuine (non-cancelled) sample(s), need >= {MIN_GENUINE_SAMPLES} (not asserted)"
    marker = "✅" if status == "OK" else "🔴"
    return (
        f"{marker} {file_}: {name!r} timeout-minutes={rep['timeout_minutes']} vs. p95={rep['p95_minutes']}min "
        f"x {rep['headroom_multiplier']} = {rep['required_minutes']}min required "
        f"(n={rep['n_genuine']} genuine / {rep['n_total']} total) — {status}"
    )


def _gh_run_lister(workflow_file: str, window: int) -> list:
    out = subprocess.run(
        [
            "gh",
            "run",
            "list",
            "--repo",
            REPO,
            "--workflow",
            workflow_file,
            "--limit",
            str(window),
            "--json",
            "databaseId,conclusion,status",
        ],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise RuntimeError(out.stderr.strip() or f"gh run list failed for {workflow_file}")
    return json.loads(out.stdout)


def _gh_jobs_fetcher(run_id) -> list | None:
    if not run_id:
        return None
    out = subprocess.run(["gh", "api", f"repos/{REPO}/actions/runs/{run_id}/jobs?per_page=100"], capture_output=True, text=True)
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout).get("jobs")
    except (json.JSONDecodeError, AttributeError):
        return None


def run_checks(
    window: int = DEFAULT_WINDOW,
    headroom_multiplier: float = HEADROOM_MULTIPLIER,
    job_filter: str | None = None,
    workflow_dir: str | None = None,
    run_lister: RunLister = _gh_run_lister,
    jobs_fetcher: JobsFetcher = _gh_jobs_fetcher,
) -> list[dict]:
    """The full enumerate-measure-evaluate pass. Pure aside from the injected I/O."""
    entries = ci_job_timeouts.iter_job_timeouts(workflow_dir)
    reports = []
    for e in entries:
        if job_filter and e["job_name"] != job_filter:
            continue
        if e["templated"]:
            reports.append(evaluate_job(e, [], headroom_multiplier))
            continue
        try:
            samples = measure_job_durations(e["file"], e["job_name"], window, run_lister, jobs_fetcher)
        except Exception as exc:  # noqa: BLE001 — any gh/network failure degrades to a named UNVERIFIED row
            reports.append(
                {
                    "job_name": e["job_name"],
                    "file": e["file"],
                    "timeout_minutes": e["timeout_minutes"],
                    "status": "UNVERIFIED",
                    "error": str(exc),
                }
            )
            continue
        reports.append(evaluate_job(e, samples, headroom_multiplier))
    return reports


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--window", type=int, default=DEFAULT_WINDOW, help=f"trailing completed runs per job (default {DEFAULT_WINDOW})")
    p.add_argument(
        "--headroom", type=float, default=HEADROOM_MULTIPLIER, help=f"required multiplier over p95 (default {HEADROOM_MULTIPLIER})"
    )
    p.add_argument("--job", default=None, help="only evaluate the job with this exact check-run name")
    p.add_argument("--json", action="store_true", help="emit the raw report list as JSON instead of the human summary")
    args = p.parse_args(argv)

    population = ci_job_timeouts.iter_job_timeouts()
    if len(population) < JOB_TIMEOUT_FLOOR:
        print(
            f"⚠️  population floor breached: found {len(population)} job(s) declaring timeout-minutes, "
            f"expected >= {JOB_TIMEOUT_FLOOR} — the derivation may be reading the wrong directory.",
            file=sys.stderr,
        )
        return 1

    # `_gh_run_lister`/`_gh_jobs_fetcher` are looked up by NAME here rather than
    # relying on `run_checks`'s own default parameters — a default value is bound
    # once at function-definition time, so a test monkeypatching the module-level
    # names would silently miss it if `run_checks`'s defaults were what fired.
    reports = run_checks(
        window=args.window, headroom_multiplier=args.headroom, job_filter=args.job, run_lister=_gh_run_lister, jobs_fetcher=_gh_jobs_fetcher
    )

    if args.json:
        print(json.dumps(reports, indent=2))
    else:
        for rep in reports:
            print(_format_report_line(rep))

    if any(r.get("status") == "UNVERIFIED" for r in reports):
        print("⚠️  one or more jobs could not be measured (gh/network failure) — see UNVERIFIED rows above.", file=sys.stderr)

    return 1 if any(r.get("status") == "RED" for r in reports) else 0


if __name__ == "__main__":
    sys.exit(main())
