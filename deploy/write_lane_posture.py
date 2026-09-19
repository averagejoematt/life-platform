#!/usr/bin/env python3
"""deploy/write_lane_posture.py — #3608 box 4: `typical_seconds` is WRITTEN, not stored.

THE DEFECT. "Green and fast" had no measured bar. `deploy/github_posture.json`
carried `typical_seconds: 90` for the required check `Collect + deploy-critical
+ format` (a snapshot someone typed after PR #2094), `tests/conftest.py` carried
"8,813 tests in 155s" in a comment, and #3678 separately measured the SAME lane's
genuine p95 at 14.87min. Three numbers, three eras, no reconciliation, and
nothing that reds when any of them drifts.

THE FIX, in two halves:
  * The lane emits its OWN wall-clock. `.github/workflows/pr-checks.yml`'s
    fast-lane stamps `LANE_START` in its dependency-install step and emits a
    one-line JSON `::notice::` (title `lane-wallclock`) from its LAST step,
    which carries `if: always()` so a red gate still reports the duration. No
    new step was added — the emit rides an existing one.
  * THIS script writes that measurement into the posture file, with its
    provenance. There is no path that sets `typical_seconds` by hand and passes
    `tests/test_lane_wallclock_ratchet_3608.py`, which requires the provenance
    fields to be present, dated and self-consistent.

WHO RUNS IT. The wrap. `/wrap`'s gate phase already runs
`scripts/check_main_green.py` and the doc gates against live GitHub; this is one
more read-only `gh` call in that phase:

    python3 deploy/write_lane_posture.py --measure          # live, trailing window
    python3 deploy/write_lane_posture.py --seconds 1037 --n 21   # from an emitted notice

Both write the same shape. `--measure` reuses `scripts/check_job_timeout_headroom.py`'s
own sampler (the #3678 instrument) rather than a second definition of "how long
did that job take" — a measurement with two implementations is two numbers
again, which is the defect.

WHY p95 OF GENUINE COMPLETIONS. Same reasoning as #3678, quoted rather than
re-derived: a run killed by its own `timeout-minutes` is a CENSORED observation
(it says "at least 18 minutes", not "18 minutes"), so including it drags the
statistic toward the ceiling and makes the ceiling look justified by the runs it
broke. Genuine completions only.

READ-ONLY toward AWS and GitHub: `gh run list` / `gh api .../jobs` are GETs.
The only write is to the posture file in the working tree.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

_DEPLOY_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(_DEPLOY_DIR)
POSTURE_PATH = os.path.join(REPO_ROOT, "deploy", "github_posture.json")

# The required check this script measures. Read from the posture file itself in
# `--measure` mode so a renamed check moves the measurement with it; the literal
# here is only the default selector.
DEFAULT_CONTEXT = "Collect + deploy-critical + format"

# Provenance keys written beside `typical_seconds`. The ratchet test requires
# every one of them — a bare number is exactly what #3608 box 4 was filed against.
PROVENANCE_KEYS = ("typical_measured_on", "typical_measured_by", "typical_statistic", "typical_n")


def load_posture(path: str = POSTURE_PATH) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_check(posture: dict, context: str) -> dict | None:
    for check in posture.get("main_required_checks_ruleset", {}).get("required_status_checks", []):
        if check.get("context") == context:
            return check
    return None


def measure_live(context: str, window: int = 30, workflow_file: str | None = None) -> tuple[float, int]:
    """(p95 seconds, n genuine) for `context`, via #3678's sampler. Live `gh`.

    `workflow_file` defaults to the one the POSTURE FILE declares for this check
    — derived, so a check that moves workflows is still measured rather than
    silently sampled from the wrong file and written as if it were current."""
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import check_job_timeout_headroom as hh  # noqa: E402

    if workflow_file is None:
        entry = find_check(load_posture(), context) or {}
        workflow_file = entry.get("workflow") or "pr-checks.yml"
    samples = hh.measure_job_durations(workflow_file, context, window, hh._gh_run_lister, hh._gh_jobs_fetcher)
    genuine = hh.genuine_durations(samples)
    if not genuine:
        raise SystemExit(
            f"no genuine (non-timed-out) completions for {context!r} in {workflow_file}'s trailing {window} runs — nothing to write"
        )
    p95 = hh.percentile(genuine, 95)
    return float(p95), len(genuine)


def apply_measurement(posture: dict, context: str, seconds: float, n: int, by: str, statistic: str, today: str) -> dict:
    check = find_check(posture, context)
    if check is None:
        raise SystemExit(f"{context!r} is not a declared required check in deploy/github_posture.json")
    check["typical_seconds"] = int(round(seconds))
    check["typical_measured_on"] = today
    check["typical_measured_by"] = by
    check["typical_statistic"] = statistic
    check["typical_n"] = int(n)
    return posture


def emit_wallclock(started_epoch: int, context: str, now_epoch: int | None = None) -> str:
    """The lane's own measurement, as ONE line of JSON inside a `::notice::`.

    Emitted from the fast-lane's LAST step (which carries `if: always()`), so a
    red gate still reports its duration — a lane that only measures itself when
    it passes measures the wrong distribution. A notice annotation is readable
    with `gh api .../check-runs/<id>/annotations`, so this needs no
    upload-artifact step and adds no step to the job at all.
    """
    import time

    now = int(now_epoch if now_epoch is not None else time.time())
    payload = {
        "kind": "lane-wallclock",
        "context": context,
        "seconds": max(0, now - int(started_epoch)),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "sha": os.environ.get("GITHUB_SHA"),
        "measured_on": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }
    return "::notice title=lane-wallclock::" + json.dumps(payload, separators=(",", ":"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--context", default=DEFAULT_CONTEXT)
    ap.add_argument("--measure", action="store_true", help="sample the trailing window live via gh (#3678's sampler)")
    ap.add_argument("--window", type=int, default=30)
    ap.add_argument("--seconds", type=float, help="a duration emitted by the lane's own ::notice:: (lane-wallclock)")
    ap.add_argument("--n", type=int, default=1)
    ap.add_argument("--statistic", default=None, help="p95 (default for --measure) or wall-clock (default for --seconds)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--emit-wallclock-since",
        type=int,
        help="epoch seconds the lane started; prints the ::notice:: and exits (used by pr-checks.yml's fast-lane)",
    )
    args = ap.parse_args(argv)

    if args.emit_wallclock_since is not None:
        line = emit_wallclock(args.emit_wallclock_since, args.context)
        print(line)
        summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with open(summary, "a", encoding="utf-8") as f:
                f.write(f"\n**Lane wall-clock (#3608 box 4)** — `{args.context}`: {line.split('::', 2)[-1]}\n")
        return 0

    if args.measure == bool(args.seconds is not None):
        ap.error("pass exactly one of --measure or --seconds")

    if args.measure:
        seconds, n = measure_live(args.context, args.window)
        by, statistic = "scripts/check_job_timeout_headroom.py sampler (trailing window, genuine completions)", "p95"
    else:
        seconds, n = float(args.seconds), args.n
        by, statistic = "pr-checks.yml fast-lane ::notice:: lane-wallclock", "wall-clock"
    statistic = args.statistic or statistic

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    posture = apply_measurement(load_posture(), args.context, seconds, n, by, statistic, today)

    rendered = json.dumps(posture, indent=2, ensure_ascii=False) + "\n"
    if args.dry_run:
        print(f"[dry-run] {args.context}: typical_seconds -> {int(round(seconds))} ({statistic}, n={n}, {today})")
        return 0
    with open(POSTURE_PATH, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(
        f"✅ {args.context}: typical_seconds = {int(round(seconds))}s ({statistic}, n={n}, measured {today}) written to deploy/github_posture.json"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
