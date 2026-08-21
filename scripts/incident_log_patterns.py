#!/usr/bin/env python3
"""incident_log_patterns.py — derive INCIDENT_LOG's pattern distribution from its rows (#2840).

WHY THIS EXISTS. `docs/INCIDENT_LOG.md`'s "Patterns & Observations" section was a
hand-tallied list ("Deployment errors — 9 incidents", "CDK drift — 3 incidents", ...)
written during the V2 audit and stamped **2026-05-19**. It never moved again. By
2026-08-21 the corpus held well over a hundred dated rows, most of them post-June, and the
three classes that dominate the recent record — lane-subset/union-breach main reds,
deploy-plane wedges/strands/races, and QA-oracle false positives — appeared in it
**nowhere**. Only the "Last updated" line moved per session, which is the worst possible
combination: a section that looks maintained and is three months stale.

(No row count is quoted in this docstring on purpose. Run the script — quoting one here
would be the same stale-literal defect, one file to the left. The live numbers live in the
generated output and in `docs/INCIDENT_LOG.md`, which a guard keeps in sync.)

A hand recount would buy one correct snapshot and then rot exactly the same way. So the
section is DERIVED instead: this script reads the table and emits the distribution, and
`tests/test_incident_log_patterns_2840.py` fails when the committed section disagrees with
what the rows actually say.

WHAT IT DOES NOT DO. Classification is keyword-based over each row's Summary + Root Cause,
which is a coarse instrument on free prose — a row can match two classes, and some match
none. That is stated in the output rather than hidden: `unclassified` is printed, and the
guard asserts it stays a minority. This is a distribution, not a taxonomy with a
correctness proof. Refining a class means editing `CLASSES` here, in one place, and
re-running — not re-tallying the whole table by hand.

THE SILENCE AXIS. Silence is scored ORTHOGONALLY (loud/silent × class), not as a class of
its own, because it cuts across classes and is the single strongest predictor of
time-to-detect in this corpus. The TTD asymmetry it produces is the finding worth keeping.

Usage:
    python3 scripts/incident_log_patterns.py            # human-readable
    python3 scripts/incident_log_patterns.py --json     # machine-readable (the guard reads this)
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INCIDENT_LOG = REPO_ROOT / "docs" / "INCIDENT_LOG.md"

# A dated table row: | YYYY-MM-DD | <severity> | summary | root cause | TTD | TTR | ...
#
# The severity cell is read GENERICALLY and normalized, never pattern-matched against one
# spelling. The first version of this script required `**Pn**` exactly and silently dropped
# 18 of the rows then present — the older unbolded `P3`, the annotated `**P4** (false positive)`, and the
# non-P severities `Low` / `**Info**` / `**DR drill**`. A derivation that quietly discards
# 13% of its population is the same defect as the frozen hand-tally it replaces, so the
# guard now asserts this parser sees every dated row a bare date-match finds.
_ROW = re.compile(r"^\|\s*(20\d{2}-\d{2}-\d{2})\s*\|([^|]*)\|(.*)$")
_SEVERITY = re.compile(r"\b(P[1-4]|Low|Info|DR drill)\b", re.I)

# Root-cause classes, keyed on vocabulary the rows actually use. Ordered most-specific
# first; a row is credited to EVERY class it matches (they are not mutually exclusive —
# a lane-subset red on a deploy-plane change is genuinely both).
CLASSES: dict[str, tuple[str, ...]] = {
    "lane-subset / union-breach main red": (
        "deselect",
        "pre-merge lane",
        "main red",
        "red main",
        "red-main",
        "collection",
        "collect",
        "union",
    ),
    "deploy-plane wedge / strand / race": (
        "wedge",
        "stranded",
        "strand",
        "approval gate",
        "cancel-in-progress",
        "queued behind",
        "lease",
        "invalidation race",
        "asset race",
    ),
    "QA-oracle false positive": (
        "false positive",
        "false red",
        "auto-rollback",
        "rolled back",
        "rollback reverted",
        "healthy deploy",
        "canary residue",
        "cold-start",
        "cold lambda",
    ),
    "timezone / wallclock": ("timezone", "utc", "pacific", "wallclock", "dst", "midnight"),
    "IAM / permission": ("iam", "accessdenied", "permission", "policy", "grant", "role"),
    "deployment error": ("deploy", "bundle", "zip", "packaging", "handler", "cdk drift"),
    "stale config / literal drift": ("stale", "literal", "drift", "hardcoded", "env var"),
    "data quality / scoring": ("scoring", "dedup", "sign error", "zero-score", "arithmetic"),
    "secret / credential": ("secret", "credential", "token", "re-auth", "oauth"),
}

# The orthogonal axis. A row is SILENT when it failed without announcing itself — nothing
# paged, nothing reddened, and it was found by someone looking. These are the phrases the
# corpus uses for that.
_SILENT_MARKERS = (
    "silent",
    "silently",
    "swallow",
    "no alarm",
    "nothing alarms",
    "went green",
    "reads green",
    "unnoticed",
    "invisible",
    "no signal",
    "dark",
    "undetected",
)


def _parse_ttd(cell: str) -> float | None:
    """Minutes from a TTD cell, or None when it states no duration.

    Deliberately conservative: it reads the FIRST duration in the cell and ignores prose.
    A cell like "~2 min — the post-merge run check, not a notification" is 2.0; a cell like
    "Real-time (deploy watcher)" is 0.0; anything it cannot read is None and is excluded
    from the medians rather than counted as zero.
    """
    text = cell.lower()
    if "real-time" in text or "immediate" in text or "realtime" in text:
        return 0.0
    m = re.search(r"(\d+(?:\.\d+)?)\s*(d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes|wk|week|weeks)\b", text)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2)
    if unit.startswith("d"):
        return value * 1440
    if unit.startswith("w"):
        return value * 10080
    if unit.startswith(("h",)):
        return value * 60
    return value


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2


def parse_rows(path: Path | None = None) -> list[dict]:
    """Every dated incident row, with its class matches and silence verdict."""
    text = (path or INCIDENT_LOG).read_text(encoding="utf-8")
    rows: list[dict] = []
    for line in text.splitlines():
        m = _ROW.match(line)
        if not m:
            continue
        date, sev_cell, rest = m.group(1), m.group(2), m.group(3)
        sev_match = _SEVERITY.search(sev_cell)
        severity = (
            sev_match.group(1).upper().replace("DR DRILL", "DR drill").replace("LOW", "Low").replace("INFO", "Info")
            if sev_match
            else "unlabelled"
        )
        cells = [c.strip() for c in rest.split("|")]
        body = " ".join(cells[:2]).lower()  # summary + root cause
        ttd_cell = cells[2] if len(cells) > 2 else ""
        matched = [name for name, kws in CLASSES.items() if any(k in body for k in kws)]
        rows.append(
            {
                "date": date,
                "month": date[:7],
                "severity": severity,
                "classes": matched,
                "silent": any(k in body for k in _SILENT_MARKERS),
                "ttd_minutes": _parse_ttd(ttd_cell),
            }
        )
    return rows


def build(path: Path | None = None) -> dict:
    rows = parse_rows(path)
    silent = [r for r in rows if r["silent"]]
    loud = [r for r in rows if not r["silent"]]
    return {
        "total_rows": len(rows),
        "by_month": dict(sorted(Counter(r["month"] for r in rows).items())),
        "by_severity": dict(sorted(Counter(r["severity"] for r in rows).items())),
        "by_class": dict(Counter(c for r in rows for c in r["classes"]).most_common()),
        "unclassified": sum(1 for r in rows if not r["classes"]),
        "post_june_rows": sum(1 for r in rows if r["month"] >= "2026-07"),
        "silence_axis": {
            "silent_rows": len(silent),
            "loud_rows": len(loud),
            "median_ttd_minutes_silent": _median([r["ttd_minutes"] for r in silent if r["ttd_minutes"] is not None]),
            "median_ttd_minutes_loud": _median([r["ttd_minutes"] for r in loud if r["ttd_minutes"] is not None]),
            "silent_by_class": dict(Counter(c for r in silent for c in r["classes"]).most_common()),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args()
    data = build()
    if args.json:
        print(json.dumps(data, indent=2))
        return 0

    print(f"INCIDENT_LOG — {data['total_rows']} dated rows ({data['post_june_rows']} post-June)\n")
    print("By month:")
    for month, n in data["by_month"].items():
        print(f"  {month}  {n:3}  {'#' * n}")
    print("\nBy severity:")
    for sev, n in data["by_severity"].items():
        print(f"  {sev}  {n:3}")
    print("\nBy root-cause class (a row may match several):")
    for name, n in data["by_class"].items():
        print(f"  {n:3}  {name}")
    print(f"  {data['unclassified']:3}  (unclassified — no keyword matched)")
    axis = data["silence_axis"]
    print("\nSilence axis (orthogonal to class):")
    print(f"  silent rows {axis['silent_rows']}   loud rows {axis['loud_rows']}")
    print(f"  median TTD  silent {axis['median_ttd_minutes_silent']}  loud {axis['median_ttd_minutes_loud']}  (minutes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
