#!/usr/bin/env python3
"""
phase_filter_checkpoint.py — ADR-058 §13: scheduled 30/60/90-day re-evaluation
of the experiment-restart phase filter (#383, epic #348).

Context: ADR-058's read-path filter hides `phase=pilot` (pre-genesis) data
from public surfaces, coaching, and scoring by default. The 2026-07 product
review (RESTART-PHASE-FILTER-REEVAL) recorded a promise to revisit that
default at 30/60/90 days post-genesis, because "how much history should stay
hidden" is an empirical call, not a one-time decision — but the promise was
never actually written into ADR-058 itself. This script is the mechanism that
makes the promise self-enforcing: it computes when each checkpoint is due
(relative to `EXPERIMENT_START_DATE`, so it re-derives correctly across any
future restart), gathers a deterministic diagnostic snapshot to inform the
human review, and records the verdict — even "no change" — to a durable audit
trail so the 60- and 90-day follow-ups can't silently lapse.

This is a **recurring** operational script (re-run at each checkpoint), not a
one-off — exempt from ADR-059's 30-day one-off-script archive convention.

The diagnostic snapshot is static and read-only (no AWS calls): it inventories
every `include_pilot=True` call site in lambdas/ and mcp/ (the deliberate
bypasses of the default hide-pilot behavior) plus the current EXPERIMENT_SCOPED
source list from `phase_taxonomy.py`, so the reviewer has a concrete "where is
pre-reset data already visible, and what's still hidden" picture rather than
having to reconstruct it from memory.

The actual verdict (keep-as-is / widen specific read paths / adjust the
taxonomy) is a human judgment call about real usage — this script does not
guess it. `--record` requires an explicit --verdict/--notes and refuses to
record a checkpoint before its due date unless --force is passed (testing only).

Usage:
    python3 deploy/phase_filter_checkpoint.py                     # status (default)
    python3 deploy/phase_filter_checkpoint.py status
    python3 deploy/phase_filter_checkpoint.py record --checkpoint 30 \\
        --verdict keep-as-is --notes "..." [--reviewer matthew] [--force]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

import phase_taxonomy as taxonomy  # noqa: E402  (ADR-077 registry)

from lambdas.constants import EXPERIMENT_START_DATE  # noqa: E402

CHECKPOINT_SCHEDULE_DAYS = (30, 60, 90)
VALID_VERDICTS = ("keep-as-is", "widen-read-paths", "adjust-taxonomy")

STATE_PATH = REPO_ROOT / "docs" / "reviews" / "PHASE_FILTER_CHECKPOINTS.json"
NARRATIVE_PATH = REPO_ROOT / "docs" / "reviews" / "PHASE_FILTER_CHECKPOINTS.md"

_INCLUDE_PILOT_TRUE_RE = re.compile(r"include_pilot\s*=\s*True")
_SCAN_DIRS = ("lambdas", "mcp")
_SKIP_FILES = {"phase_filter.py"}


def genesis_date() -> date:
    return date.fromisoformat(EXPERIMENT_START_DATE)


def checkpoint_due_date(genesis: date, checkpoint_days: int) -> date:
    return genesis + timedelta(days=checkpoint_days)


@dataclass
class BypassSite:
    file: str
    line: int
    text: str


def scan_include_pilot_bypasses(repo_root: Path = REPO_ROOT) -> list[BypassSite]:
    """Static inventory of every deliberate `include_pilot=True` call site.

    Read-only, no AWS calls — greps lambdas/ and mcp/ for the literal bypass
    of the default hide-pilot filter, so the checkpoint review starts from a
    concrete list of where pre-reset data is already surfaced.
    """
    sites: list[BypassSite] = []
    for dirname in _SCAN_DIRS:
        base = repo_root / dirname
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if path.name in _SKIP_FILES:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if _INCLUDE_PILOT_TRUE_RE.search(line):
                    sites.append(BypassSite(file=str(path.relative_to(repo_root)), line=lineno, text=line.strip()))
    return sites


def diagnostic_snapshot() -> dict:
    bypasses = scan_include_pilot_bypasses()
    return {
        "include_pilot_true_call_sites": [asdict(b) for b in bypasses],
        "include_pilot_true_call_site_count": len(bypasses),
        "experiment_scoped_sources": list(taxonomy.SCOPED_SOURCES),
        "cross_phase_sources": list(taxonomy.CROSS_PHASE_SOURCES),
        "raw_timeseries_sources": list(taxonomy.RAW_TIMESERIES_SOURCES),
    }


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"checkpoints": []}
    return json.loads(STATE_PATH.read_text(encoding="utf-8"))


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def recorded_checkpoints(state: dict) -> dict[int, dict]:
    return {entry["checkpoint_days"]: entry for entry in state.get("checkpoints", [])}


def build_status(today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    genesis = genesis_date()
    days_elapsed = (today - genesis).days
    state = load_state()
    recorded = recorded_checkpoints(state)

    checkpoints = []
    next_actionable = None
    for n in CHECKPOINT_SCHEDULE_DAYS:
        due = checkpoint_due_date(genesis, n)
        entry = recorded.get(n)
        if entry is not None:
            status = "recorded"
        elif today >= due:
            status = "due"
        else:
            status = "upcoming"
        row = {
            "checkpoint_days": n,
            "due_date": due.isoformat(),
            "status": status,
            "recorded": entry,
        }
        checkpoints.append(row)
        if status == "due" and next_actionable is None:
            next_actionable = row

    result = {
        "today": today.isoformat(),
        "genesis": genesis.isoformat(),
        "days_elapsed": days_elapsed,
        "checkpoints": checkpoints,
        "next_actionable_checkpoint": next_actionable["checkpoint_days"] if next_actionable else None,
    }
    if next_actionable is not None:
        result["diagnostic_snapshot"] = diagnostic_snapshot()
    return result


def _print_status(result: dict) -> None:
    print(f"Genesis (EXPERIMENT_START_DATE): {result['genesis']}")
    print(f"Today: {result['today']}  (day {result['days_elapsed']} since genesis)")
    print()
    for row in result["checkpoints"]:
        marker = {"recorded": "[x]", "due": "[!]", "upcoming": "[ ]"}[row["status"]]
        line = f"  {marker} {row['checkpoint_days']:>2}-day checkpoint — due {row['due_date']} — {row['status']}"
        if row["recorded"]:
            r = row["recorded"]
            line += f" ({r['recorded_date']}, verdict={r['verdict']}, reviewer={r['reviewer']})"
        print(line)
    print()
    if result["next_actionable_checkpoint"] is not None:
        n = result["next_actionable_checkpoint"]
        snap = result["diagnostic_snapshot"]
        print(f"Checkpoint {n} is DUE and unrecorded. Diagnostic snapshot for the review:")
        print(f"  - {snap['include_pilot_true_call_site_count']} deliberate include_pilot=True call sites (lambdas/, mcp/):")
        for site in snap["include_pilot_true_call_sites"]:
            print(f"      {site['file']}:{site['line']}")
        print(
            f"  - {len(snap['experiment_scoped_sources'])} EXPERIMENT_SCOPED sources hidden by default: "
            f"{', '.join(snap['experiment_scoped_sources'])}"
        )
        print()
        print("This is the diagnostic substrate only — the verdict (keep-as-is / widen-read-paths /")
        print("adjust-taxonomy) is a human judgment call about real usage. Record it with:")
        print(f'  python3 deploy/phase_filter_checkpoint.py record --checkpoint {n} --verdict <verdict> --notes "..."')
    else:
        upcoming = [row for row in result["checkpoints"] if row["status"] == "upcoming"]
        if upcoming:
            nxt = upcoming[0]
            print(f"No checkpoint due yet. Next: {nxt['checkpoint_days']}-day checkpoint on {nxt['due_date']}.")
        else:
            print("All scheduled checkpoints (30/60/90 days) have been recorded.")


def cmd_status(args: argparse.Namespace) -> int:
    today = date.fromisoformat(args.today) if args.today else None
    result = build_status(today)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        _print_status(result)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    today = date.fromisoformat(args.today) if args.today else datetime.now(timezone.utc).date()
    genesis = genesis_date()
    due = checkpoint_due_date(genesis, args.checkpoint)
    state = load_state()
    recorded = recorded_checkpoints(state)

    if args.checkpoint in recorded and not args.force:
        existing = recorded[args.checkpoint]
        print(
            f"error: checkpoint {args.checkpoint} was already recorded on {existing['recorded_date']} "
            f"(verdict={existing['verdict']}). Pass --force to overwrite.",
            file=sys.stderr,
        )
        return 1

    if today < due and not args.force:
        print(
            f"error: checkpoint {args.checkpoint} is not due until {due.isoformat()} "
            f"(today is {today.isoformat()}). Pass --force only for testing.",
            file=sys.stderr,
        )
        return 1

    entry = {
        "checkpoint_days": args.checkpoint,
        "due_date": due.isoformat(),
        "recorded_date": today.isoformat(),
        "verdict": args.verdict,
        "reviewer": args.reviewer,
        "notes": args.notes,
        "diagnostic_snapshot": diagnostic_snapshot(),
    }
    state["checkpoints"] = [e for e in state.get("checkpoints", []) if e["checkpoint_days"] != args.checkpoint] + [entry]
    state["checkpoints"].sort(key=lambda e: e["checkpoint_days"])
    save_state(state)
    _append_narrative(entry)

    print(f"Recorded checkpoint {args.checkpoint} ({today.isoformat()}, verdict={args.verdict}).")
    remaining = [n for n in CHECKPOINT_SCHEDULE_DAYS if n not in {e["checkpoint_days"] for e in state["checkpoints"]}]
    if remaining:
        for n in remaining:
            print(f"  Next: {n}-day checkpoint due {checkpoint_due_date(genesis, n).isoformat()} — still armed, not lapsed.")
    else:
        print("  All 30/60/90-day checkpoints are now recorded.")
    return 0


def _append_narrative(entry: dict) -> None:
    NARRATIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not NARRATIVE_PATH.exists():
        NARRATIVE_PATH.write_text(_narrative_header(), encoding="utf-8")
    section = (
        f"\n## {entry['checkpoint_days']}-day checkpoint — recorded {entry['recorded_date']}\n\n"
        f"- **Due:** {entry['due_date']}\n"
        f"- **Reviewer:** {entry['reviewer']}\n"
        f"- **Verdict:** {entry['verdict']}\n"
        f"- **Notes:** {entry['notes']}\n"
        f"- **Diagnostic snapshot at review time:** "
        f"{entry['diagnostic_snapshot']['include_pilot_true_call_site_count']} include_pilot=True call sites, "
        f"{len(entry['diagnostic_snapshot']['experiment_scoped_sources'])} EXPERIMENT_SCOPED sources hidden by default.\n"
    )
    with NARRATIVE_PATH.open("a", encoding="utf-8") as f:
        f.write(section)


def _narrative_header() -> str:
    return (
        "# Phase filter checkpoints — ADR-058 §13\n\n"
        "Paper trail for the scheduled 30/60/90-day re-evaluation of the experiment-restart "
        "phase filter (`lambdas/phase_filter.py`, ADR-058). Generated/appended by "
        "`deploy/phase_filter_checkpoint.py record`. Machine-readable state lives alongside at "
        "`PHASE_FILTER_CHECKPOINTS.json`.\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--today", help="Override today's date (YYYY-MM-DD), for testing.")
    sub = parser.add_subparsers(dest="command")

    status_p = sub.add_parser("status", help="Show checkpoint schedule + diagnostic snapshot if one is due (default).")
    status_p.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of the text report.")
    status_p.set_defaults(func=cmd_status)

    record_p = sub.add_parser("record", help="Record a checkpoint's outcome to the audit trail.")
    record_p.add_argument("--checkpoint", type=int, choices=CHECKPOINT_SCHEDULE_DAYS, required=True)
    record_p.add_argument("--verdict", choices=VALID_VERDICTS, required=True)
    record_p.add_argument("--notes", required=True, help="Free-text summary of what the review found.")
    record_p.add_argument("--reviewer", default="matthew")
    record_p.add_argument("--force", action="store_true", help="Allow recording before the due date or overwrite an existing record.")
    record_p.set_defaults(func=cmd_record)

    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        args.json = False
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
