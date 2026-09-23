#!/usr/bin/env python3
"""backfill_routine_specs.py — #4079 acceptance box 2: every routine committed since
2026-09-21 gets a spec at its new durable home, back-filled.

DRY-RUN BY DEFAULT, like every restart_* / reconcile_* / backfill_* tool in this
directory. Nothing is written to S3 without an explicit ``--apply``.

The problem
-----------
Before mcp/routine_spec_ledger.py (#4079), a routine committed through
`manage_hevy_routine commit` (mcp/tools_hevy_routine.py::_action_commit) had no
durable spec of its own — the coaching skill hand-authored a markdown file into
docs/coaching/routines/<type>/ and asked the chat session to `git commit` it, a
step chat cannot perform. docs/coaching/routines/README.md's index has been stale
since 2026-09-19 while routines kept committing underneath it. This script covers
the gap for everything committed 2026-09-21 -> today, the window the issue names,
using the SAME `mcp.routine_spec_ledger.save_routine_spec` the live commit path now
calls, so a backfilled spec and a freshly-committed one are byte-for-byte the same
shape.

Scope + source of truth
------------------------
Reads `training.routine_repo.list_by_date_range` — the date-sorted
`USER#matthew#SOURCE#routine_index` partition (a bounded Query), never a
full-table Scan — over [2026-09-21, today], then keeps only rows that actually
reached Hevy: `status in {"active", "unverified"}` and a non-empty
`hevy_routine_id`. A `draft` that was never committed gets no spec — there is
nothing to back-fill; the live `commit` call will write one the day it ships.

One spec per routine_id (the CURRENT version), matching the live path and the
docs/coaching/routines/ convention of "bump the file when the routine materially
changes" rather than one row per historical version.

`committed_at` is pinned to the routine's own `hevy_pushed_at` (its real, original
commit instant), not "now" — see `routine_spec_ledger.build_spec`'s `committed_at`
param.

Usage
-----
    python3 deploy/backfill_routine_specs.py                       # dry-run (default)
    python3 deploy/backfill_routine_specs.py --end-date 2026-09-30 # widen the window
    python3 deploy/backfill_routine_specs.py --apply                # write S3

Never run by this agent — dry-run counts only; --apply is the driver's call
(#4079: PutObject on config/* is a live write, out of scope for a read-only lane).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))
sys.path.insert(0, str(REPO_ROOT))

CUTOFF_DATE = "2026-09-21"  # the issue's own back-fill window start


def _committed_since_cutoff(end_date: str):
    """Every committed (status active/unverified, hevy_routine_id set) routine in
    [CUTOFF_DATE, end_date]. Returns the live RoutineSpec objects — read-only."""
    from training.routine_repo import list_by_date_range

    routines = list_by_date_range(CUTOFF_DATE, end_date, limit=500)
    return [ir for ir in routines if (ir.status or "").lower() in ("active", "unverified") and ir.hevy_routine_id]


def plan(end_date: str) -> list[dict]:
    """The dry-run plan: one row per routine that would get a spec written, with
    the key and hash it would carry — no S3 call, ever, in plan mode."""
    from mcp.routine_spec_ledger import content_hash, spec_key

    rows = []
    for ir in _committed_since_cutoff(end_date):
        rows.append(
            {
                "routine_id": ir.routine_id,
                "archetype": ir.archetype,
                "target_date": ir.target_date,
                "hevy_routine_id": ir.hevy_routine_id,
                "session_role": ir.created_by,
                "committed_at": ir.hevy_pushed_at,
                "key": spec_key(ir.archetype, ir.routine_id),
                "content_hash": content_hash(ir),
            }
        )
    return sorted(rows, key=lambda r: (r["target_date"], r["routine_id"]))


def apply(end_date: str) -> list[dict]:
    """Write every planned spec via the same `save_routine_spec` the live commit
    path calls. Only reachable with --apply."""
    from mcp.routine_spec_ledger import save_routine_spec

    out = []
    for ir in _committed_since_cutoff(end_date):
        result = save_routine_spec(ir, committed_at=ir.hevy_pushed_at)
        out.append({"routine_id": ir.routine_id, **result})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default=None, help="last target_date to scan (default: today, Pacific)")
    parser.add_argument("--apply", action="store_true", help="write S3 (default: dry-run, prints the plan only)")
    args = parser.parse_args()

    from common.pacific_time import pacific_today

    end_date = args.end_date or pacific_today()

    rows = plan(end_date)
    print(f"#4079 routine-spec backfill — window [{CUTOFF_DATE}, {end_date}] — {len(rows)} committed routine(s) found")
    for r in rows:
        print(f"  {r['target_date']}  {r['archetype']:<10} {r['routine_id']}  role={r['session_role']:<5}  -> {r['key']}")

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to write these specs to S3.")
        return 0

    print("\n--apply: writing...")
    results = apply(end_date)
    saved = sum(1 for r in results if r.get("saved"))
    failed = [r for r in results if not r.get("saved")]
    print(f"wrote {saved}/{len(results)} spec(s)")
    for r in failed:
        print(f"  FAILED routine_id={r['routine_id']}: {r.get('error')}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
