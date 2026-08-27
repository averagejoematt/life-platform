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

  python3 scripts/backlog_next.py --refill-now
      THE REMEDY for check_backlog_hygiene.py's blocking `now_liveness` finding
      (#3254). Prints the derived promotion plan — which issues, in what order,
      with the exact `gh` commands and the rewritten score line each promotion
      needs — or an explicit NO REMEDY verdict when the corpus cannot reach the
      floor. See `plan_now_refill`.

EXIT CODE: always 0. This is an advisory selector, not a gate; a live-fetch
failure (no network/auth) prints one advisory line and exits 0, matching
check_backlog_hygiene.py's fail-open contract. `--refill-now` is no exception:
the BLOCKING half of this pair is the hygiene gate, and a second exit code here
would let a session satisfy the wrap by re-running the planner.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

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
    below stay trivially testable, per this repo's fixture-as-data house style.
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


# ── the `Now` refill plan (#3254) ───────────────────────────────────────────────
#
# THE GAP THIS CLOSES
#   `check_backlog_hygiene.rule_now_liveness` is BLOCKING and its whole message was
#   "refill it (#1870's wrap step)". That step walked `Next` only, and when `Next` was
#   empty it reported honestly and stopped — so the sanctioned remedy could be exhausted
#   while the gate stayed red, and ADR-099's own `Roadmap` promotion path (amendment
#   2026-08-22 ¶3) named no actor and no procedure. Measured 2026-08-27: `Now` held
#   exactly 3 live stories (the floor), `Next` held 1, `Later` held 0 — one closure away
#   from a blocking gate with no remedy the wrap knew how to reach.
#
# WHAT THE PLAN IS
#   A pure function over the same corpus the gate reads, so the gate can PRINT its own
#   remedy instead of naming a ritual. It answers, by construction: which issues, in
#   what order, from which milestone, under what budget, with what exact commands — and
#   when the corpus genuinely cannot reach the floor, it says NO REMEDY EXISTS and names
#   the levers, which is a different and much louder verdict than "refill it".

# The minimal row shape the planner needs. Both `build_row` (here) and
# `check_backlog_hygiene.build_ctx` produce every one of these keys — that agreement is
# what lets the gate call the planner without a second parse, and
# tests/test_now_refill_remedy_3254.py is the contract test that holds it.
PLAN_ROW_KEYS = ("number", "title", "labels", "milestone", "score", "blocking", "raw_score_line")

# `now_liveness` counts `type:story` specifically, so promoting a `type:bug` or a
# `type:chore` moves the queue's real depth and NOT the gate. The planner picks stories
# only; anything else would be a remedy that verifiably does not clear the finding.
STORY_LABEL = "type:story"


class RefillPick(NamedTuple):
    """One promotion the plan proposes, with both halves of the edit it needs."""

    number: Optional[int]
    title: str
    donor: str  # the milestone it is promoted FROM
    lane: Optional[str]  # its model:* lane — who can actually start it
    score_value: Optional[float]
    score_line: Optional[str]  # the stored line, verbatim
    retargeted_score_line: Optional[str]  # the same line with `→ Now`; None when unscored
    is_product_pick: bool  # True for the ADR-099 ¶3 Roadmap promotion


class RefillPlan(NamedTuple):
    """The whole derived answer to 'the Now queue is below the floor — now what?'."""

    live_now: int
    floor: int
    short: int
    picks: List[RefillPick]
    residual_short: int  # still short AFTER every sanctioned promotion — the NO REMEDY case
    blocked_now: List[Optional[int]]  # `Now` stories held by gate:owner/blocked:*
    blocked_donors: List[Optional[int]]  # donor-milestone stories blocked the same way
    product_held_back: int  # promotable Roadmap stories the ¶3 cap deliberately left parked
    lane: Optional[str]  # the lane the plan was scoped to, or None for the lane-blind count
    now_lanes: List[Any]  # (lane, count) over the STARTABLE `Now` stories — the composition
    off_lane_available: int  # startable donor stories this plan refused because of the lane


def _is_story(row: Dict[str, Any]) -> bool:
    return STORY_LABEL in row["labels"]


def lane_histogram(rows: List[Dict[str, Any]]) -> List[Any]:
    """(lane, count) over rows, every sanctioned lane present even at zero.

    Zeros are the point. "opus 0" is the fact a lane-blind count of 3 was hiding.
    """
    counts = {lane: 0 for lane in bc.MODEL_LANES}
    for row in rows:
        lane = bc.model_lane(row["labels"])
        if lane:
            counts[lane] = counts.get(lane, 0) + 1
        else:
            counts["(no model:* label)"] = counts.get("(no model:* label)", 0) + 1
    return [(lane, counts[lane]) for lane in counts]


def plan_now_refill(rows: List[Dict[str, Any]], floor: Optional[int] = None, lane: Optional[str] = None) -> RefillPlan:
    """The ordered promotions that bring `Now` back to the liveness floor. Pure.

    Donor order is `bc.DONOR_MILESTONES` — Next, then Later, then Roadmap — derived from
    MILESTONE_ORDER, never re-typed. Within a milestone the order is the issue's OWN stored
    score (`sort_key`), because re-scoring at selection time is the habit #1866 exists to
    kill. Roadmap contributes at most `bc.ROADMAP_PICKS_PER_REFILL` (¶3), and what the cap
    holds back is COUNTED rather than dropped, so "the debt corpus is drained and the only
    remaining work is parked product vision" reads as the distinct state it is.

    LANE SCOPING (the 2026-08-27 measurement). `now_liveness` counts stories, but work is
    partitioned by `model:*` lane and a session runs in exactly one of them. Measured that
    day: `Next` held 1 startable story and `Roadmap` held 11, and **all 12 were
    `model:fable`** while the running session was all-Opus. A lane-blind plan would have
    proposed promoting one of them, the count would have gone green, and zero work the
    session could start would have been added — a remedy dischargeable dishonestly is not
    a remedy. With `lane` set, only that lane's candidates can clear the shortfall and the
    rest are counted into `off_lane_available` so the refusal is stated, not silent. With
    `lane` None the count stays lane-blind (the historical contract) but `now_lanes` and
    every pick's `lane` are populated, so no caller can report a number without its
    composition.
    """
    floor = bc.NOW_LIVENESS_MIN if floor is None else floor
    now_stories = [r for r in rows if r["milestone"] == "Now" and _is_story(r)]
    startable_now = [r for r in now_stories if not r["blocking"]]
    in_lane = [r for r in startable_now if lane is None or bc.model_lane(r["labels"]) == lane]
    short = max(0, floor - len(in_lane))

    picks: List[RefillPick] = []
    blocked_donors: List[Optional[int]] = []
    product_held_back = 0
    off_lane_available = 0
    for donor in bc.DONOR_MILESTONES:
        pool = [r for r in rows if r["milestone"] == donor and _is_story(r)]
        blocked_donors.extend(r["number"] for r in pool if r["blocking"])
        startable = [r for r in pool if not r["blocking"]]
        candidates = sorted((r for r in startable if lane is None or bc.model_lane(r["labels"]) == lane), key=sort_key)
        off_lane_available += len(startable) - len(candidates)
        is_product = donor == bc.PRODUCT_MILESTONE
        budget = bc.ROADMAP_PICKS_PER_REFILL if is_product else len(candidates)
        take = min(len(candidates), budget, max(0, short - len(picks)))
        for row in candidates[:take]:
            score = row["score"]
            picks.append(
                RefillPick(
                    number=row["number"],
                    title=row["title"],
                    donor=donor,
                    lane=bc.model_lane(row["labels"]),
                    score_value=score.value if score else None,
                    score_line=score.raw if score else row["raw_score_line"],
                    retargeted_score_line=bc.retarget_score_line(score.raw if score else None, "Now"),
                    is_product_pick=is_product,
                )
            )
        if is_product:
            product_held_back = len(candidates) - take

    return RefillPlan(
        live_now=len(in_lane),
        floor=floor,
        short=short,
        picks=picks,
        residual_short=max(0, short - len(picks)),
        blocked_now=[r["number"] for r in now_stories if r["blocking"]],
        blocked_donors=blocked_donors,
        product_held_back=product_held_back,
        lane=lane,
        now_lanes=lane_histogram(startable_now),
        off_lane_available=off_lane_available,
    )


def refill_remedy_lines(plan: RefillPlan) -> List[str]:
    """The compact remedy `rule_now_liveness` embeds in its own blocking message.

    Deliberately short and deliberately NAMED: an actor ("the wrapping session, at
    /wrap (e9)"), specific issue numbers, and the fact that a promotion is two edits.
    A gate that prints a ritual's name is a gate whose remedy is "a human remembers".
    """
    if plan.short <= 0:
        return []
    scope = f" (lane model:{plan.lane})" if plan.lane else ""
    out = [
        f"REMEDY{scope} — the wrapping session does this at /wrap (e9); `python3 scripts/backlog_next.py --refill-now` prints the commands:"
    ]
    out.append("  `Now` startable by lane: " + lane_summary(plan.now_lanes))
    for pick in plan.picks:
        tag = " [ADR-099 ¶3 product pick — confirm none other this cycle]" if pick.is_product_pick else ""
        score = f"{pick.score_value:.2f}" if pick.score_value is not None else "unscored"
        out.append(f"  promote #{pick.number} ({pick.donor}, {score}, model:{pick.lane or '—'}){tag}: {pick.title[:70]}")
    if plan.picks:
        out.append("  each promotion is TWO edits — `gh issue edit N --milestone Now` AND the score line's `→` arrow retargeted to")
        out.append("  `→ Now`; the milestone edit alone swaps this blocking finding for a blocking `score_line_canonical` one.")
    if plan.lane is None and any(p.lane for p in plan.picks):
        out.append("  LANE-BLIND COUNT: these picks clear the NUMBER. A promotion in a lane your session does not run adds zero")
        out.append("  startable work — re-run with `--lane <sonnet|opus|fable>` to plan only work the running model can begin.")
    if plan.residual_short:
        out.append(
            f"  NO REMEDY IN THE CORPUS{scope}: {plan.residual_short} short even after every sanctioned promotion "
            f"({len(plan.picks)} available, {plan.product_held_back} Roadmap stories held back by the ¶3 one-per-cycle cap)."
        )
        if plan.off_lane_available:
            out.append(
                f"  {plan.off_lane_available} startable story(ies) exist OUTSIDE lane model:{plan.lane} and were refused: promoting one"
            )
            out.append("  would make the count green while adding nothing this session can start. That is not a remedy.")
        levers = ["FILE work (`/uplevel`, a review sweep)"]
        if plan.blocked_now or plan.blocked_donors:
            gated = ", ".join(f"#{n}" for n in (plan.blocked_now + plan.blocked_donors)[:6])
            levers.append(f"unblock a gate:owner/blocked:* story ({gated})")
        if plan.product_held_back:
            levers.append("amend ADR-099 ¶3 to raise the per-cycle product-pick rate")
        if plan.off_lane_available:
            levers.append("hand the wrap to a session in the lane that HAS the work, or re-lane an issue deliberately")
        out.append("  levers, in order: " + " · ".join(levers) + ".")
        out.append("  do NOT lower the floor to clear this — the floor is bc.NOW_LIVENESS_MIN and it only ratchets by ADR.")
    return out


def lane_summary(now_lanes: List[Any]) -> str:
    """`opus 2 · sonnet 0 · fable 0` — the composition, zeros included."""
    return " · ".join(f"{lane} {count}" for lane, count in now_lanes) or "(no stories)"


def render_refill(plan: RefillPlan) -> List[str]:
    """The full `--refill-now` report: the plan, the commands, the honest residual."""
    scope = f" · lane model:{plan.lane}" if plan.lane else " · LANE-BLIND (pass --lane to scope to the running model)"
    out = [
        "NOW-REFILL PLAN (#3254) — derived from the live corpus, run by the wrapping session at /wrap (e9)." + scope,
        "",
        f"`Now`: {plan.live_now} live story(ies) / floor {plan.floor} → {plan.short} short.",
        f"  startable by lane: {lane_summary(plan.now_lanes)}",
    ]
    if plan.blocked_now:
        held = ", ".join(f"#{n}" for n in plan.blocked_now)
        out.append(f"  {len(plan.blocked_now)} more `Now` story(ies) are gate:owner/blocked:* and NOT startable: {held}")
    if plan.short <= 0:
        out.append("")
        out.append("Nothing to do — the queue is live and `now_liveness` is not firing.")
        return out

    out.append("")
    if not plan.picks:
        out.append("NO PROMOTION IS AVAILABLE — the whole corpus offers zero startable stories outside `Now`.")
    else:
        out.append("PROMOTE, in this order (stored ADR-099 rank, never a fresh re-score):")
        out.append("")
    for index, pick in enumerate(plan.picks, start=1):
        score = f"{pick.score_value:5.2f}" if pick.score_value is not None else "    —"
        flag = "   <- ADR-099 ¶3 PRODUCT PICK" if pick.is_product_pick else ""
        out.append(f"  {index}. #{pick.number} · {score} · {pick.donor} · model:{pick.lane or '—'} · {pick.title}{flag}")
        out.append(f"       gh issue edit {pick.number} --milestone Now")
        if pick.retargeted_score_line:
            out.append(f"       then retarget the body's score line — {pick.score_line}")
            out.append(f"                                     to — {pick.retargeted_score_line}")
        else:
            out.append("       then WRITE a canonical score line ending `→ Now` — this issue has none to retarget,")
            out.append(
                f"       so `score_line_canonical` is already firing on it{' (' + pick.score_line + ')' if pick.score_line else ''}."
            )
        if pick.is_product_pick:
            out.append("       CONFIRM no other Roadmap→Now promotion was taken this experiment cycle. The corpus")
            out.append("       cannot derive that (promotion rewrites the arrow that would record it); this line is")
            out.append("       the check, and it is the ONLY human-memory step in the plan.")
        out.append("")

    reached = plan.live_now + len(plan.picks)
    if plan.residual_short:
        out.append(f"AFTER this plan `Now` reaches {reached} of {plan.floor} — STILL {plan.residual_short} SHORT.")
        # the exhaustion verdict verbatim from the shared remedy text — one wording, two surfaces
        tail = refill_remedy_lines(plan)
        start = next(i for i, line in enumerate(tail) if "NO REMEDY IN THE CORPUS" in line)
        out.extend(tail[start:])
    else:
        out.append(f"AFTER this plan `Now` reaches {reached} live story(ies) — `now_liveness` clears.")
    if plan.product_held_back:
        out.append(
            f"{plan.product_held_back} more promotable `Roadmap` story(ies) left parked deliberately — ¶3 caps the rate, not the supply."
        )
    return out


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
    parser.add_argument(
        "--refill-now",
        action="store_true",
        help="Print the derived `Now`-refill plan — the remedy for check_backlog_hygiene's blocking now_liveness finding (#3254).",
    )
    parser.add_argument(
        "--lane",
        choices=list(bc.MODEL_LANES),
        default=os.environ.get("BACKLOG_LANE") or None,
        help="Scope --refill-now to one model:* lane (env BACKLOG_LANE). Without it the plan counts work the session may not be able to start.",
    )
    args = parser.parse_args(argv)

    if args.issues_json:
        issues = json.loads(Path(args.issues_json).read_text(encoding="utf-8"))
    else:
        issues = _fetch_live_issues()
        if issues is None:
            return 0  # fail-open: no gh/network/auth available in this context

    rows = [build_row(i) for i in issues if is_rankable(i)]
    if args.refill_now:
        print("\n".join(render_refill(plan_now_refill(rows, lane=args.lane))))
        return 0
    result = select(rows, milestone=args.milestone, model=args.model, include_blocked=args.include_blocked)
    print("\n".join(render(result, rows, args)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
