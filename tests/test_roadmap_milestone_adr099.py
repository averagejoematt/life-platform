"""ADR-099 amendment 2026-08-22: the `Roadmap` milestone — product vision parked
outside the debt corpus.

Three behaviors, each mutation-provable by reverting one edit:

1. `→ Roadmap` is a canonical score-line milestone (SCORE_LINE_RE / MILESTONE_ORDER).
2. The default ranked walk (Now → Next → Later) never falls through to Roadmap
   while any debt milestone has rows — a Roadmap item can only be surfaced by an
   explicit `--milestone Roadmap` ask.
3. `later_staleness` ignores Roadmap: a parked idea untouched for months is not
   stale debt.
"""

import os
import sys
from datetime import datetime, timedelta, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import backlog_contract as bc  # noqa: E402
import backlog_next as bn  # noqa: E402
from check_backlog_hygiene import rule_later_staleness  # noqa: E402


def _row(number, milestone, score=1.0):
    """A rankable issue on `milestone`, built through bn's own loader (the wire)."""
    body = (
        "## Outcome\n\n**operator** — value.\n\n"
        f"**Score:** P3 · Impact 3 × Confidence 1.0 / Effort S(1) = {score:.2f} → {milestone}\n\n"
        "## Acceptance\n\n- [ ] do the thing\n"
    )
    issue = {
        "number": number,
        "title": f"issue {number}",
        "labels": [{"name": "type:story"}, {"name": "model:fable"}],
        "milestone": {"title": milestone},
        "body": body,
    }
    assert bn.is_rankable(issue)
    return bn.build_row(issue)


def test_roadmap_is_a_canonical_score_line_milestone():
    line = "**Score:** P3 · Impact 2 × Confidence 0.75 / Effort M(2) = 0.75 → Roadmap"
    score = bc.parse_score_line(line)
    assert score is not None and score.milestone == "Roadmap"
    assert bc.MILESTONE_ORDER == ("Now", "Next", "Later", "Roadmap")
    # Ranked LAST — after every debt milestone, before only the unknown bucket.
    assert bc.milestone_rank("Roadmap") == 3
    assert bc.milestone_rank("Later") < bc.milestone_rank("Roadmap")


def test_default_walk_never_reaches_roadmap_while_debt_rows_exist():
    rows = [_row(1, "Later"), _row(2, "Roadmap")]
    result = bn.select(rows, milestone="Now")
    assert result["milestone"] == "Later"
    assert [r["number"] for r in result["rows"]] == [1]


def test_roadmap_reachable_only_when_all_debt_milestones_are_empty():
    rows = [_row(2, "Roadmap")]
    result = bn.select(rows, milestone="Now")
    assert result["milestone"] == "Roadmap"
    assert [r["number"] for r in result["rows"]] == [2]


def test_later_staleness_exempts_roadmap():
    now = datetime(2026, 8, 22, tzinfo=timezone.utc)
    old = (now - timedelta(days=200)).isoformat()
    ctxs = [
        {"number": 1, "milestone": "Later", "updated_at": old},
        {"number": 2, "milestone": "Roadmap", "updated_at": old},
    ]
    findings = rule_later_staleness(ctxs, now)
    assert [f.number for f in findings] == [1], findings
