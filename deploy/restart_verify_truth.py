#!/usr/bin/env python3
"""
restart_verify_truth.py — the AI reader-truth gate after a reset (#1097).

The reset is the highest-risk moment for truth regressions (every pre-start
leak in the 2026-07-11 review was reset residue), and until now restart verify
had no truth pass: restart_verify_rendered.py proves the surface RENDERS,
restart_verify_semantic.py (#1093) asserts deterministic facts about what it
SAYS — this gate adds the third layer, the same phase-aware Bedrock rubric
that ships as CI `--reader-truth` and the nightly qa_smoke pass (#1140,
lambdas/reader_truth_qa.py). ONE rubric, now THREE hooks — this script adds
zero prompt logic of its own, so the rubric still cannot fork.

Invoked by restart_pipeline.py right after restart_verify_semantic (hard gate,
apply only); standalone-runnable any time — the R2.3 reset drill (#1094) calls
it directly and captures docs/restart/_verify_truth_report.txt.

Failure semantics (mirrors both existing hooks, blocks like the render gate):
  - any HIGH finding            → FAIL, exit 1 (restart_pipeline aborts/re-runs)
  - med/low findings            → WARN, exit 0 (reported, never silent)
  - budget tier pauses the pass → SKIP LOUDLY, exit 0 (internal QA pauses at
    tier >= 1 per ADR-125; a paused budget must never block a reset, and a
    silent green here would be a lie — the skip is printed AND in the report)
  - Bedrock/fetch outage        → SKIP LOUDLY, exit 0 (a missing verdict is
    advisory, not a pass OR a fail — same posture as the nightly hook)

Usage:
    python3 deploy/restart_verify_truth.py                 # full run (live site)
    python3 deploy/restart_verify_truth.py --base-url URL  # drill/staging target
    python3 deploy/restart_verify_truth.py --today DATE    # phase-anchor override
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

BASE = "https://averagejoematt.com"
REPORT = REPO_ROOT / "docs" / "restart" / "_verify_truth_report.txt"

# Reset-critical narrative surfaces — the pages where the 2026-07-11 review
# found wiped-cycle prose still on the air, plus the two API payloads whose
# narrative values they bind. All paths verified against the 40-URL v4 surface
# (deploy/restart_verify_rendered.py PAGES/JSON_ENDPOINTS + the nightly
# qa_smoke READER_TRUTH set). 8 surfaces = 2 Haiku batches, pennies per run.
SURFACES = [
    ("/", "Home"),
    ("/cockpit/", "Cockpit"),
    ("/coaching/", "Coaching read"),
    ("/story/chronicle/", "Story · chronicle"),
    ("/story/journal/", "Story · journal"),
    ("/data/vitals/", "Data · vitals"),
    ("/api/vitals", "API · vitals"),
    ("/api/coaches", "API · coaches"),
]

PASS, FAIL, WARN, SKIP = "PASS", "FAIL", "WARN", "SKIP"


def fetch_surfaces(base_url: str = BASE) -> tuple[list[dict], list[str]]:
    """Fetch the reset-critical surface set. Returns (surfaces, fetch_warnings).

    Pages are tag-stripped to visible-ish text (reader_truth_qa.html_to_text —
    the same static-HTML approximation the nightly hook uses); API payloads go
    in as raw JSON text. Every failure is a warning string, never an exception.
    """
    import reader_truth_qa

    surfaces, warnings = [], []
    for path, name in SURFACES:
        try:
            req = urllib.request.Request(base_url + path, headers={"User-Agent": "restart-verify-truth/1.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                body = r.read().decode("utf-8", "replace")
            prose = body if path.startswith("/api/") else reader_truth_qa.html_to_text(body)
            surfaces.append({"name": name, "path": path, "prose": prose})
        except Exception as e:
            warnings.append(f"{name} ({path}) — fetch failed: {str(e)[:120]}")
    return surfaces, warnings


def gate(findings: list[dict], errors: list[str], n_surfaces: int, day_label: str) -> tuple[str, int, list[str]]:
    """Pure verdict logic (fixture-tested): (status, exit_code, report_lines).

    Mirrors the CI + nightly hooks exactly: only a HIGH finding gates; med/low
    are loud warnings; all-batches-errored is a loud advisory skip, never a
    pass or a fail (reader_truth_qa's false-positive rails — normalized
    severities, lifetime/pre-start allowances — are upstream in the rubric).
    """
    lines = [f"AI batch error (fail-soft): {e}" for e in errors]
    highs = [f for f in findings if f["severity"] == "high"]
    lower = [f for f in findings if f["severity"] != "high"]

    def _fmt(f: dict) -> str:
        return f"[{f['severity']}] {f['page']} ({f['category']}): {f['note']}"

    lines.extend(_fmt(f) for f in highs + lower)
    if highs:
        return FAIL, 1, [f"{len(highs)} HIGH truth finding(s) at {day_label} — the reset surface is lying to readers"] + lines
    if lower:
        return WARN, 0, [f"{len(lower)} low/med truth finding(s) at {day_label} (non-gating, review them)"] + lines
    if errors and not findings:
        return SKIP, 0, [f"no verdict at {day_label} — all {len(errors)} AI batch(es) errored (advisory skip, NOT a pass)"] + lines
    return PASS, 0, [f"{n_surfaces} surfaces clean at {day_label} — no truth findings"] + lines


def write_report(status: str, lines: list[str], day_label: str) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    body = [f"verify_truth report — {status} at {day_label}", ""] + [f"    {ln}" for ln in lines]
    REPORT.write_text("\n".join(body) + "\n")
    print(f"Report: {REPORT.relative_to(REPO_ROOT)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default=BASE, help=f"site to read (default {BASE}) — the #1094 drill can point elsewhere")
    ap.add_argument("--today", help="phase-anchor override YYYY-MM-DD (default: today PT; the phase itself comes from constants.py)")
    args = ap.parse_args()

    import reader_truth_qa

    phase = reader_truth_qa.phase_context(args.today)
    day_label = f"{phase['days_until_start']}d pre-start" if phase["pre_start"] else f"Day {phase['day_n']}"
    print(f"\nrestart_verify_truth — genesis={phase['start_date']} today={phase['today']} ({day_label})\n")

    # Budget gate — internal QA pauses first (ADR-125). LOUD skip, never silent:
    # a paused budget must not block a reset, but it must be visible that the
    # truth layer did NOT run.
    try:
        import budget_guard

        if not budget_guard.allow(reader_truth_qa.BUDGET_FEATURE):
            tier = budget_guard.current_tier()
            lines = [f"budget tier {tier} pauses feature {reader_truth_qa.BUDGET_FEATURE!r} (internal QA pauses first, ADR-125)"]
            print(f"  ⏸ SKIP — reader-truth AI paused at budget tier {tier}. The truth layer did NOT run this reset.")
            write_report(SKIP, lines, day_label)
            return 0
    except ImportError:
        pass  # fail-open, same posture as the guard itself

    try:
        import bedrock_client
    except Exception as e:
        print(f"  ⏸ SKIP — bedrock_client unavailable ({str(e)[:120]}). The truth layer did NOT run this reset.")
        write_report(SKIP, [f"bedrock_client unavailable: {str(e)[:200]}"], day_label)
        return 0

    surfaces, fetch_warnings = fetch_surfaces(args.base_url)
    for w in fetch_warnings:
        print(f"  ⚠ {w}")
    if not surfaces:
        # Reachability is the RENDER gate's job — it already failed the pipeline
        # if the site is down. Here it degrades to a loud advisory skip.
        print("  ⏸ SKIP — zero surfaces fetched (see warnings above). The truth layer did NOT run this reset.")
        write_report(SKIP, ["zero surfaces fetched"] + fetch_warnings, day_label)
        return 0

    findings, errors = reader_truth_qa.assess_prose(surfaces, bedrock_client.invoke, today_iso=args.today)
    status, rc, lines = gate(findings, errors, len(surfaces), day_label)
    lines = lines + [f"(fetch warning) {w}" for w in fetch_warnings]

    mark = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "○"}[status]
    print(f"\n  {mark} {status}: {lines[0]}")
    for ln in lines[1:]:
        print(f"      {ln}")
    write_report(status, lines, day_label)
    return rc


if __name__ == "__main__":
    sys.exit(main())
