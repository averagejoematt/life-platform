#!/usr/bin/env python3
"""scripts/backlog_next.py — the ranked backlog selector (#1866, epic #1863).

THE PROBLEM
  The stored rank was never read at selection time. `/uplevel` Phase 2 re-scores
  candidates from scratch on Loop / Audience / Returnability / Honesty / Effort
  and never reads the issue's own `Impact × Confidence / Effort` line; the
  milestone only filters the seed set. So the whole ADR-099 scoring apparatus was
  written and never consumed — the exact failure the SDLC review's C-anchor
  names: "score lines are unexplained ceremony".

  There was no consumer to read it with. The only backlog query in the repo was a
  hand-rolled jq one-liner in `uplevel.md` that filtered `gate:owner` and returned
  unsorted titles — no score, no outcome, no ordering. And it returned `[]`: all
  three open `Now` stories carried `gate:owner`, so a session seeding from the
  documented command found nothing it could do (epic finding 1).

THE FIX
  One command that answers "what do I work on next, and why does it matter":
  ranked by the issue's own stored score, with the audience-named `## Outcome`
  line printed on every row, and every silence made loud —

    - `gate:owner` / `blocked:*` are hidden but COUNTED, never silently dropped.
    - an empty `Now` FALLS THROUGH to `Next` and says so; an empty result is
      never returned where a fall-through was possible.
    - issues whose score line is a retired grammar rank last as UNSCORED and are
      counted in the summary, rather than vanishing from the ranking.
    - open issues with no milestone are counted too — they are invisible to every
      ranked query, which is a filing-contract defect worth seeing (finding 11).

  The score-line and `## Outcome` parsers live in `scripts/backlog_contract.py`,
  shared with the #1867 hygiene linter — one contract, two consumers.

USAGE
  python3 scripts/backlog_next.py
      Live: `gh issue list` the open corpus, rank the `Now` milestone (falling
      through to `Next` when `Now` has nothing actionable).

  python3 scripts/backlog_next.py --milestone Next --model opus --limit 5
  python3 scripts/backlog_next.py --include-blocked
  python3 scripts/backlog_next.py --milestone all
  python3 scripts/backlog_next.py --issues-json FIXTURE.json
      Offline mode for tests/CI — same JSON shape, no network.

EXIT CODE: always 0. This is an advisory selector, not a gate; a live-fetch
failure (no network/auth) prints one advisory line and exits 0, matching
check_story_labels.py's fail-open contract.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backlog_contract as bc  # noqa: E402

REPO = "averagejoematt/life-platform"

# The selector ranks work, and an epic is a container, not work.
EXCLUDED_TYPE_LABELS = ("type:epic",)


def is_rankable(issue: Dict[str, Any]) -> bool:
    """Open issues that represent work — everything except epics."""
    labels = bc.label_names(issue)
    return not any(name in EXCLUDED_TYPE_LABELS for name in labels)


def build_row(issue: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the ranker needs about one issue, parsed once.

    A plain dict (not a class) so fixtures read as data and the pure functions
    below stay trivially testable, per the check_story_labels.py house style.
    """
    labels = bc.label_names(issue)
    body = issue.get("body") or ""
    score = bc.parse_score_line(body)
    return {
        "number": issue.get("number"),
        "title": issue.get("title") or "",
        "labels": labels,
        "milestone": bc.milestone_title(issue),
        "score": score,
        "raw_score_line": bc.find_score_line(body),
        "outcome": bc.outcome_line(body),
        "legacy_outcome": bc.legacy_outcome_line(body),
        "acceptance": bc.acceptance_items(body),
        "blocking": bc.blocking_labels(labels),
        "model": bc.model_lane(labels),
        "prio_label": next((n for n in labels if n.startswith("prio:")), None),
        "areas": [n for n in labels if n.startswith("area:")],
    }


def sort_key(row: Dict[str, Any]):
    """Score desc, then milestone (Now first), then issue number.

    Unscored rows sort after every scored row — visible, but never ahead of work
    whose value was actually stated.
    """
    score = row["score"]
    return (
        0 if score else 1,
        -(score.value if score else 0.0),
        bc.milestone_rank(row["milestone"]),
        row["number"] or 0,
    )


def rank(
    rows: List[Dict[str, Any]],
    milestone: Optional[str] = None,
    model: Optional[str] = None,
    include_blocked: bool = False,
) -> Dict[str, Any]:
    """Filter + sort one milestone's rows. Pure: no I/O, no fall-through policy.

    Returns the visible rows plus the counts of what was withheld, so the caller
    can report the hidden set instead of dropping it.
    """
    pool = rows if milestone is None else [r for r in rows if r["milestone"] == milestone]
    if model:
        pool = [r for r in pool if r["model"] == model]
    blocked = [r for r in pool if r["blocking"]]
    visible = pool if include_blocked else [r for r in pool if not r["blocking"]]
    visible = sorted(visible, key=sort_key)
    return {
        "milestone": milestone,
        "rows": visible,
        "blocked_count": len(blocked),
        "blocked": blocked,
        "pool_count": len(pool),
    }


def select(
    rows: List[Dict[str, Any]],
    milestone: str = "Now",
    model: Optional[str] = None,
    include_blocked: bool = False,
) -> Dict[str, Any]:
    """`rank`, plus the fall-through policy that makes finding 1 impossible.

    When the requested milestone yields no visible rows and a later milestone
    exists in the ordering, walk forward and record every milestone tried. An
    empty result is only ever returned when there was nothing left to fall
    through to.
    """
    if milestone == "all":
        result = rank(rows, None, model, include_blocked)
        result["fell_through_from"] = []
        return result

    order = list(bc.MILESTONE_ORDER)
    start = order.index(milestone) if milestone in order else 0
    tried: List[Dict[str, Any]] = []
    for candidate in order[start:]:
        result = rank(rows, candidate, model, include_blocked)
        if result["rows"]:
            result["fell_through_from"] = tried
            return result
        tried.append(result)
    # Nothing anywhere: report the originally-requested milestone, with the
    # whole walk attached so the caller can say what it looked at.
    empty = dict(tried[0]) if tried else rank(rows, milestone, model, include_blocked)
    empty["fell_through_from"] = tried
    empty["exhausted"] = True
    return empty


# ── rendering ───────────────────────────────────────────────────────────────────


def format_row(row: Dict[str, Any]) -> List[str]:
    """The printable lines for one issue: the ranked row, then its outcome."""
    score = row["score"]
    score_cell = f"{score.value:>5.2f}" if score else "    —"
    if row["prio_label"]:
        prio = f"prio:{row['prio_label'].split(':', 1)[1]}"
    elif score:
        prio = f"prio:~{score.prio}"  # ~ = derived from the body, no prio:* label
    else:
        prio = "prio:—"
    area = ",".join(a.split(":", 1)[1] for a in row["areas"]) or "—"
    model = f"model:{row['model']}" if row["model"] else "model:—"
    milestone = row["milestone"] or "no-milestone"
    blocked = f"  [{', '.join(row['blocking'])}]" if row["blocking"] else ""

    lines = [f"#{row['number']:<5} · {score_cell} · {prio} · area:{area} · {model} · {milestone} · {row['title']}{blocked}"]

    if row["outcome"]:
        lines.append(f"        ↳ {row['outcome']}")
    elif row["legacy_outcome"]:
        lines.append(f"        ↳ (legacy outcome_if_fixed) {row['legacy_outcome']}")
    else:
        lines.append("        ↳ — no ## Outcome line")

    if not score:
        if row["raw_score_line"]:
            lines.append(f"        ! unscored — score line is not the ADR-099 canonical grammar: {row['raw_score_line']}")
        else:
            lines.append("        ! unscored — no **Score:** line at all")
    if not row["acceptance"]:
        lines.append("        ! no ## Acceptance checkboxes — readiness unstated")
    return lines


def render(result: Dict[str, Any], rows: List[Dict[str, Any]], args: argparse.Namespace) -> List[str]:
    """The whole report, as lines. Pure, so tests assert on text without capsys."""
    out: List[str] = []

    for skipped in result.get("fell_through_from", []):
        ms = skipped["milestone"]
        if skipped["pool_count"] == 0:
            out.append(f"{ms}: no open issues match this filter — falling through.")
        else:
            out.append(f"{ms}: {skipped['pool_count']} open, ALL gate:owner/blocked:* — nothing a session can start. Falling through.")

    milestone = result["milestone"] or "all milestones"
    shown = result["rows"][: args.limit] if args.limit else result["rows"]

    if not result["rows"]:
        if result.get("exhausted"):
            walk = " → ".join(bc.MILESTONE_ORDER)
            out.append(f"NOTHING ACTIONABLE anywhere in {walk} for this filter — the backlog needs a refill, not a retry.")
        else:
            out.append(f"{milestone}: no rows match this filter.")
    else:
        out.append(f"RANKED — {milestone} ({len(shown)} of {len(result['rows'])} shown, by stored ADR-099 score):")
        out.append("")
        for row in shown:
            out.extend(format_row(row))
            out.append("")

    if result["blocked_count"]:
        verb = "shown inline" if args.include_blocked else "hidden"
        out.append(
            f"{result['blocked_count']} issue(s) {verb}: gate:owner / blocked:* — blocked on a human-only act, not session-startable."
        )
        if not args.include_blocked:
            out.append("   (re-run with --include-blocked to see them)")

    unscored = [r for r in shown if not r["score"]]
    legacy = [r for r in unscored if r["raw_score_line"]]
    if unscored:
        out.append(
            f"{len(unscored)} shown row(s) UNSCORED ({len(legacy)} on a retired grammar) — ranked last, not dropped. #1868 backfills."
        )
    no_outcome = [r for r in shown if not r["outcome"]]
    if no_outcome:
        out.append(f"{len(no_outcome)} shown row(s) have no canonical `## Outcome` line — value unstated on the page.")

    unmilestoned = [r for r in rows if r["milestone"] is None]
    if unmilestoned:
        numbers = ", ".join(f"#{r['number']}" for r in unmilestoned[:8])
        more = f" (+{len(unmilestoned) - 8} more)" if len(unmilestoned) > 8 else ""
        out.append(f"{len(unmilestoned)} open issue(s) carry NO milestone and are invisible to every ranked query: {numbers}{more}")

    out.append("legend: `prio:~P2` = read from the body score line; the issue carries no prio:* label (#1864).")
    return out


# ── I/O ─────────────────────────────────────────────────────────────────────────


def _fetch_live_issues() -> Optional[List[Dict[str, Any]]]:
    try:
        result = subprocess.run(
            [
                "gh",
                "issue",
                "list",
                "-R",
                REPO,
                "--state",
                "open",
                "--json",
                "number,title,labels,milestone,body",
                "--limit",
                "500",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            print(f"backlog_next: gh issue list exited {result.returncode}: {result.stderr[:300]}; skipping (advisory).")
            return None
        return json.loads(result.stdout or "[]")
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
        print(f"backlog_next: could not fetch live issues via gh ({e}); skipping (advisory).")
        return None


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Rank the open backlog by its own ADR-099 score line and print what to work on next.")
    parser.add_argument("--milestone", default="Now", choices=list(bc.MILESTONE_ORDER) + ["all"], help="Starting milestone (default: Now).")
    parser.add_argument("--model", choices=list(bc.MODEL_LANES), help="Filter to one fan-out lane (model:sonnet|opus|fable).")
    parser.add_argument("--limit", type=int, default=0, help="Show at most N ranked rows (0 = all).")
    parser.add_argument("--include-blocked", action="store_true", help="Show gate:owner / blocked:* issues instead of counting them.")
    parser.add_argument("--issues-json", help="Offline fixture path (gh issue list --json number,title,labels,milestone,body output).")
    args = parser.parse_args(argv)

    if args.issues_json:
        issues = json.loads(Path(args.issues_json).read_text(encoding="utf-8"))
    else:
        issues = _fetch_live_issues()
        if issues is None:
            return 0  # fail-open: no gh/network/auth available in this context

    rows = [build_row(i) for i in issues if is_rankable(i)]
    result = select(rows, milestone=args.milestone, model=args.model, include_blocked=args.include_blocked)
    print("\n".join(render(result, rows, args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
