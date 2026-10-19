#!/usr/bin/env python3
"""scripts/panel_rubric_gate.py — the panel rubric's regression gate over the golden plan cases (#5072).

WHAT IT GATES. A change to the training charter, the engine templates, the planning skills or the coach
prompts can make the plan worse without any test noticing — the 2026-10-18 panel review had no baseline.
This gate grades the golden cases in `tests/fixtures/panel_golden_5072/` with the panel rubric
(`config/panel_rubric.json`: the code pre-score, then the judge) and FAILS when:

  * the good charter plan drops below the charter's `panel_target` (overall letter, every seat's floor), or
  * a NEGATIVE CONTROL (frozen accessories + no progression; a scheduled deload; a 2.5 h session; cardio
    with no dose) meets the target, or scores at/above the seat floor on a criterion it exists to fail —
    a rubric that cannot tell the bad plan from the good one is not a gate.

TWO MODES.
  --recorded (default) replays `recorded_judge.json` for the judge's criteria: offline, free, no AWS. The
             unit suite runs this mode on every PR (tests/test_panel_rubric_5072.py), so the deterministic
             half — every code criterion, the combination, the controls — gates every change.
  --live     asks the model on route `charter.judge_gate` (feature `charter_judge_gate`, a band-3 CI gate:
             it pauses only at the hard stop). Path-filtered in CI to the files named above. A budget pause
             prints SKIPPED-BY-BUDGET and a ::warning:: annotation; the deterministic verdict still gates.
             A judge that ERRORS (e.g. AccessDeniedException, a throttle past the retries) or returns no
             gradeable seat is a FAIL with an ::error:: annotation on every case it hit — the live mode
             cannot go green on the code criteria alone. In CI the workflow passes the OIDC step's outcome as
             PANEL_JUDGE_CREDS: anything but `success` (the role's trust admits refs/heads/main only, so a
             pull_request is refused) prints "live judge NOT run" + a ::warning:: and exits 0 — the recorded
             step already gated that run. Unset (a laptop run) means the ambient credentials are used.
             Cost: one Sonnet call per case, back-to-back on the cached charter block (~$0.15 a run, 5 cases);
             a laptop run is also held by the dev-session cap ($5 a run).

EXIT: 0 every case behaved; 1 a case did not (each named); 2 the gate could not run (rubric/fixtures unreadable).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

FIXTURES = ROOT / "tests" / "fixtures" / "panel_golden_5072"
RECORDED = "recorded_judge.json"
GOOD_KIND = "good"
CONTROL_KIND = "negative_control"
JUDGE_FAILED = ("error", "unparsed")  # live mode: a red. "paused" (the budget guard) is the only soft path.


def golden_cases(fixtures: Path = FIXTURES) -> list[dict[str, Any]]:
    """Every plan case in the fixture dir (not the recorded replies), good plans first, then by name."""
    cases = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(fixtures.glob("*.json")) if p.name != RECORDED]
    return sorted(cases, key=lambda c: (c.get("kind") != GOOD_KIND, c.get("case_id") or ""))


def _replay(reply: Any):
    text = json.dumps(reply)
    return lambda body: {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn", "usage": {}}


def case_failures(case: dict[str, Any], grade: dict[str, Any]) -> list[str]:
    """Why this case did NOT behave: a good plan below target, or a control that passed what it must fail."""
    from training import panel_judge  # noqa: PLC0415

    if case.get("kind") == CONTROL_KIND:
        return panel_judge.failed_expectations(grade, list(case.get("expect_fail") or []))
    out = []
    if not grade["target_met"]:
        tgt = grade["target"]
        out.append(
            f"overall {grade['overall']['letter']} ({grade['overall']['score']}) / seats below {tgt.get('every_seat_at_least')}: "
            f"{grade['seats_below_floor']} / concessions not held: {grade['concessions_not_held']} (target {tgt.get('overall')})"
        )
    return out


def run(mode: str, fixtures: Path = FIXTURES) -> tuple[int, list[str]]:
    from training import panel_judge, panel_rubric  # noqa: PLC0415

    rubric = panel_rubric.load_rubric()
    cases = golden_cases(fixtures)
    if rubric is None or not cases or not any(c.get("kind") == GOOD_KIND for c in cases):
        return 2, [f"cannot run: rubric {'ok' if rubric else 'UNREADABLE'}, {len(cases)} golden case(s) in {fixtures}"]
    recorded = json.loads((fixtures / RECORDED).read_text(encoding="utf-8")).get("responses") or {} if mode == "recorded" else {}
    lines, failed, cost = [], 0, 0.0
    for case in cases:
        call = _replay(recorded.get(case["case_id"])) if mode == "recorded" else None
        grade = panel_judge.grade_case(case, rubric, route=panel_judge.CI_ROUTE, call=call)
        why = case_failures(case, grade)
        cost += float(grade["judge"].get("cost_usd") or 0)
        judge_state = grade["judge"]["status"]
        if judge_state == "paused":
            lines.append(f"SKIPPED-BY-BUDGET {case['case_id']}: the judge is paused — the code criteria still gate")
            print(f"::warning title=panel rubric gate::judge paused by the budget guard — {case['case_id']} graded on code criteria only")
        elif mode == "live" and (judge_state in JUDGE_FAILED or grade.get("unscored")):
            # The live step's whole job is the judge: a judge that could not answer is a red, never a code-only green.
            # Only the budget pause is soft (ADR-104 — a number we could not compute is not a pass).
            reason = next((r for r in grade.get("degraded_reasons") or [] if r.startswith("judge ")), f"judge {judge_state}")
            judge_state = judge_state if judge_state in JUDGE_FAILED else "partial"
            why.append(f"live judge did not grade ({reason}) — {len(grade.get('unscored') or [])} judge criteria unscored")
            print(f"::error title=panel rubric gate::{case['case_id']}: live judge {judge_state} — {reason}")
        failed += bool(why)
        seats = " ".join(f"{s}={v['score']}" for s, v in grade["seats"].items())
        lines.append(
            f"{'FAIL' if why else 'ok  '} {case['case_id']} [{case.get('kind')}] overall {grade['overall']['letter']} "
            f"{grade['overall']['score']} target_met={grade['target_met']} judge={judge_state} | {seats}"
        )
        lines += [f"     - {w}" for w in why]
    lines.append(f"panel rubric gate ({mode}): {len(cases) - failed} of {len(cases)} cases behaved; judge cost ~${cost:.4f}")
    return (1 if failed else 0), lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--recorded", action="store_true", help="replay the recorded judge replies (default; offline)")
    g.add_argument("--live", action="store_true", help="ask the model on route charter.judge_gate (Bedrock spend)")
    args = ap.parse_args(argv)
    creds = os.environ.get("PANEL_JUDGE_CREDS", "success")
    if args.live and creds != "success":
        code, lines = 0, [f"live judge NOT run: the OIDC credential step was {creds!r} (the role's trust admits refs/heads/main only)"]
        print(f"::warning title=panel rubric gate::{lines[0]} — the recorded verdict alone gated this run")
    else:
        code, lines = run("live" if args.live else "recorded")
    print("\n".join(lines))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write("\n".join(["```", *lines, "```", ""]))
    return code


if __name__ == "__main__":
    sys.exit(main())
