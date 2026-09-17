"""tests/test_backlog_closeability_3861.py — rank by what a session can FINISH (#3861).

THE MEASUREMENT THAT FORCED THIS. Session AH merged 6 PRs and closed 2 issues. The 6 PRs
satisfied roughly 10 acceptance boxes across FOUR issues — #3792, #3785, #3835, #3601 —
and closed none of those four. Both closures came from issues that happened to have one
box of work left, which was luck rather than selection.

Measured over the 69 session-shippable open issues on 2026-09-17:

    295 acceptance boxes, mean 4.3 per issue
    boxes CHECKED: 0 of 401 on open issues, 6 of 238 across the last 60 closed

So "remaining work" cannot be read off checkbox state — the checkboxes are decorative in
practice. It has to be derived from what the issue IS.

AND THE RANKING WAS ACTIVELY POINTING AWAY FROM CLOSURES. Live on 2026-09-17, the default
top five held THREE items no session can close: #3715 (its last criterion is an owner
ruling), #3563 and #3671 (both `closure:live-proof` — they close on an observation, not a
merge; #3671 is implemented, merged, and correctly still open). `--closeable` leads with
#3614, whose closure also closes epic #3491.

WHY THIS IS NOT A NEW SCORE, and must not become one. #1866 exists because re-scoring at
selection time was the habit being fixed, and the score line states VALUE. Closeability
states something different and equally real: whether one session can finish it. They are
two columns, sorted one at a time — folding them into a single number would hide both.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import backlog_contract as bc  # noqa: E402
import backlog_next as bn  # noqa: E402


def _issue(number, *, title="t", labels=(), milestone="Now", boxes=3, score=3.00, epic=None, extra=""):
    body = "## Outcome\nsomebody gets something.\n\n## Acceptance\n"
    body += "".join(f"- [ ] criterion {i}\n" for i in range(boxes))
    body += f"\n**Score:** P2 · Impact 3 × Confidence 1.0 / Effort S(1) = {score:.2f} → {milestone}\n"
    body += f"**Epic:** {'#%d' % epic if epic else 'none'}\n" + extra
    return {
        "number": number,
        "title": title,
        "labels": [{"name": n} for n in labels],
        "milestone": {"title": milestone},
        "body": body,
    }


def _rows(issues):
    return bn.annotate_closeability([bn.build_row(i) for i in issues])


# ── the epic-parent parser ───────────────────────────────────────────────────


def test_the_epic_parent_is_read_from_the_TEMPLATE_LINE_not_from_prose():
    assert bc.epic_parent("**Epic:** #3491") == 3491
    assert bc.epic_parent("**Epic:** none — a standalone defect") is None
    assert bc.epic_parent("## Problem\nthis is like #3491 but different.\n\n**Epic:** none") is None, (
        "a prose mention of an epic number was read as parentage — the same scoping rule " "acceptance_items applies to checkboxes"
    )
    assert bc.epic_parent("") is None and bc.epic_parent(None) is None


# ── last_child_of: a property of the LIVE graph, never a stored flag ─────────


def test_THE_2FOR1_a_lone_open_child_carries_its_epic():
    rows = _rows([_issue(100, labels=["type:epic"]), _issue(101, epic=100)])
    child = next(r for r in rows if r["number"] == 101)
    assert child["last_child_of"] == 100, "closing the only open child does not register as closing its epic"


def test_a_SECOND_open_sibling_removes_the_2for1_from_BOTH():
    """The reason this is computed over the whole row set rather than stored per issue: it
    changes the moment a sibling appears or closes."""
    rows = _rows([_issue(100, labels=["type:epic"]), _issue(101, epic=100), _issue(102, epic=100)])
    for n in (101, 102):
        assert next(r for r in rows if r["number"] == n)["last_child_of"] is None


def test_an_epic_is_never_its_OWN_last_child():
    rows = _rows([_issue(100, labels=["type:epic"], epic=100)])
    assert next(r for r in rows if r["number"] == 100)["last_child_of"] is None


def test_a_child_of_a_CLOSED_epic_claims_no_2for1():
    """The epic is not in the open set, so there is nothing to close alongside it. A
    parent id alone must not mint the bonus."""
    rows = _rows([_issue(101, epic=999)])
    assert next(r for r in rows if r["number"] == 101)["last_child_of"] is None


# ── the classes ──────────────────────────────────────────────────────────────


def test_a_gate_owner_issue_is_BLOCKED_not_merely_low():
    rows = _rows([_issue(101, labels=["gate:owner"], boxes=1)])
    assert rows[0]["closeability"] == bn.CLOSEABILITY_BLOCKED, "a one-box owner-gated issue still cannot be closed by merging"


def test_a_live_proof_issue_NEEDS_AN_OBSERVATION_even_with_one_box():
    """#3671 is the worked example: implemented, merged, and correctly still open, because
    its proof is a real reset that must not be manufactured."""
    rows = _rows([_issue(101, labels=["closure:live-proof"], boxes=1)])
    assert rows[0]["closeability"] == bn.CLOSEABILITY_OBSERVATION


def test_boxes_are_COUNTED_from_the_acceptance_section_only():
    rows = _rows([_issue(101, boxes=5, extra="\n## Stories\n- [ ] not acceptance\n- [ ] also not\n")])
    assert rows[0]["boxes"] == 5, "a task list outside ## Acceptance was counted as remaining work"


# ── the ordering, which is the whole point ───────────────────────────────────


def test_THE_INVERSION_closeability_outranks_score_and_score_still_breaks_ties():
    issues = [
        _issue(100, labels=["type:epic"]),
        _issue(1, score=4.00, boxes=8),  # highest value, most work
        _issue(2, score=1.00, boxes=3, epic=100),  # lowest value, 2-for-1
        _issue(3, score=2.00, boxes=3),  # ties #2 on boxes, loses the 2-for-1
        _issue(4, score=3.50, boxes=3),  # ties on boxes, no 2-for-1, higher score than #3
    ]
    rows = [r for r in _rows(issues) if not r["is_epic"]]
    order = [r["number"] for r in sorted(rows, key=bn.closeability_key)]
    assert order[0] == 2, f"the 2-for-1 did not lead: {order}"
    assert order[1] == 4 and order[2] == 3, f"score must break the 3-box tie, highest first: {order}"
    assert order[-1] == 1, f"the 8-box item must rank last however valuable: {order}"

    by_score = [r["number"] for r in sorted(rows, key=bn.sort_key)]
    assert by_score[0] == 1, "the DEFAULT ranking must be unchanged — score still leads there"
    assert order != by_score, "the two rankings are identical, so the flag changes nothing"


def test_blocked_and_observation_rows_sort_BELOW_everything_finishable():
    issues = [
        _issue(1, score=4.00, boxes=1, labels=["gate:owner"]),
        _issue(2, score=4.00, boxes=1, labels=["closure:live-proof"]),
        _issue(3, score=0.25, boxes=8),
    ]
    rows = _rows(issues)
    order = [r["number"] for r in sorted(rows, key=bn.closeability_key)]
    assert order == [3, 2, 1], f"an 8-box finishable item must outrank a 1-box unfinishable one: {order}"


# ── the CLI, end to end, against a fixture ───────────────────────────────────


def test_the_CLI_flag_changes_the_printed_order_and_prints_the_cell(tmp_path):
    issues = [_issue(100, labels=["type:epic"]), _issue(1, score=4.00, boxes=8), _issue(2, score=1.00, boxes=3, epic=100)]
    fx = tmp_path / "issues.json"
    fx.write_text(json.dumps(issues), encoding="utf-8")

    def run(*flags):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "backlog_next.py"), "--issues-json", str(fx), *flags],
            capture_output=True,
            text=True,
            cwd=ROOT,
        ).stdout

    default, closeable = run(), run("--closeable")
    assert default.index("#1 ") < default.index("#2 "), "default order changed — score must still lead without the flag"
    assert closeable.index("#2 ") < closeable.index("#1 "), "--closeable did not reorder anything"
    assert "2for1→#100" in closeable, "the 2-for-1 is not visible in the output, so a reader cannot act on it"
    assert "8box" in default, "the box count is not printed"
