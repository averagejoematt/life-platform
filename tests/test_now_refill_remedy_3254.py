"""tests/test_now_refill_remedy_3254.py — #3254: the blocking `now_liveness` gate and
the sanctioned refill are one mechanism, not two documents.

THE GAP THIS FILE GUARDS
  `check_backlog_hygiene.rule_now_liveness` is BLOCKING (#1872) and fires when `Now`
  holds fewer than `NOW_LIVENESS_MIN` startable stories. Its entire message was
  "refill it (#1870's wrap step)". That step, `/wrap` (e9), walked `Next` ONLY, and on
  an empty `Next` it reported honestly and stopped. ADR-099's 2026-08-22 amendment ¶3
  declares a `Roadmap` promotion path but names no actor and no procedure. So the gate
  and its remedy were connected by prose in two files and by nothing executable.

  Measured on the live corpus 2026-08-27: `Now` held exactly 3 startable stories (the
  floor), `Next` held 1, `Later` held 0 — one closure away from a blocking gate whose
  named remedy was already one issue deep.

  Worse, the documented remedy did not even work. `gh issue edit <N> --milestone Now`
  is one half of a promotion; ADR-099 ¶5 requires the body's score-line arrow to equal
  the milestone, and `rule_score_line_canonical` enforces that at VIOLATION severity.
  Running (e9) verbatim therefore swaps one blocking finding for another and the wrap
  is still red. `test_the_documented_milestone_only_promotion_does_not_clear_the_gate`
  is that must-fail case, kept as a live regression rather than a memory.

WHAT IS ASSERTED HERE
  1. one floor, derived — `bc.NOW_LIVENESS_MIN` is the single source and the gate aliases it;
  2. the row-shape contract that lets the gate call the planner without a second parse;
  3. the plan's rules: story-only picks, donor order derived from MILESTONE_ORDER, the ¶3
     Roadmap cap enforced AND its held-back remainder counted;
  4. the connection itself — the gate's own message carries the derived plan;
  5. the loud-failure path — when the corpus cannot reach the floor, the finding says
     NO REMEDY IN THE CORPUS and names the levers, and never lowers the floor;
  6. the two-edit truth, proved by running the gate on both promotion shapes.
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import backlog_contract as bc  # noqa: E402
import backlog_next as bn  # noqa: E402
import check_backlog_hygiene as hy  # noqa: E402

WRAP = ROOT / ".claude" / "commands" / "wrap.md"


# ── fixtures as data (the house style) ──────────────────────────────────────────


def _score(value: float, milestone: str) -> str:
    """A canonical line whose arithmetic actually agrees with its value (Impact 3 fixed,
    Confidence solved) — a fixture that trips the advisory arithmetic check would make
    the end-to-end exit-code assertions below read as noise."""
    return f"**Score:** P2 · Impact 3 × Confidence {value / 3:.4f} / Effort S(1) = {value:.2f} → {milestone}"


# Everything else the ADR-099 contract demands of a story, so the end-to-end runs below
# measure the two rules under test and not a fixture's missing labels.
CONTRACT_LABELS = ("area:ops", "prio:P2")


def _issue(number: int, milestone: str, *, value: float = 1.00, labels=("type:story",), score_milestone=None, body_extra="", lane="opus"):
    score_milestone = score_milestone or milestone
    return {
        "number": number,
        "title": f"story {number}",
        "labels": [{"name": name} for name in tuple(labels) + CONTRACT_LABELS + (f"model:{lane}",)],
        "milestone": {"title": milestone} if milestone else None,
        "body": f"## Outcome\n**operator** — the queue stays live.\n\n{_score(value, score_milestone)}\n\n"
        f"**Epic:** none — stands alone\n\n## Acceptance\n- [ ] a\n- [ ] b\n- [ ] c\n{body_extra}",
        "updatedAt": "2026-08-27T00:00:00Z",
    }


def _rows(issues):
    return [bn.build_row(i) for i in issues]


def _ctxs(issues):
    return [hy.build_ctx(i) for i in issues]


def _now_queue(n: int):
    return [_issue(100 + i, "Now") for i in range(n)]


# ── 1. one floor, derived ───────────────────────────────────────────────────────


def test_the_liveness_floor_has_exactly_one_definition():
    """The gate that fires below the floor and the planner that sizes the refill must
    read ONE number. A `3` re-typed in the gate is how a remedy gets sized against a
    floor nobody enforces — the shape this whole issue is about, one level down."""
    assert hy.NOW_LIVENESS_MIN == bc.NOW_LIVENESS_MIN
    src = (ROOT / "scripts" / "check_backlog_hygiene.py").read_text(encoding="utf-8")
    assert "NOW_LIVENESS_MIN = bc.NOW_LIVENESS_MIN" in src, "the gate must alias the contract's floor, never restate the literal"
    assert bn.plan_now_refill([], floor=None).floor == bc.NOW_LIVENESS_MIN


# ── 2. the row-shape contract (the derivation guard for the gate→planner call) ──


def test_both_row_builders_produce_every_key_the_planner_reads():
    """`rule_now_liveness` hands the planner its OWN ctx dicts. That only works because
    both builders emit the same minimal shape — guard the SET, not one instance, so a
    key renamed on either side reds here instead of silently emptying the remedy."""
    issue = _issue(1, "Next")
    for name, built in (("backlog_next.build_row", bn.build_row(issue)), ("check_backlog_hygiene.build_ctx", hy.build_ctx(issue))):
        missing = [k for k in bn.PLAN_ROW_KEYS if k not in built]
        assert not missing, f"{name} is missing planner keys {missing}"


def test_the_planner_reads_hygiene_ctxs_and_backlog_rows_identically():
    issues = _now_queue(1) + [_issue(200, "Next", value=2.0)]
    assert bn.plan_now_refill(_rows(issues)) == bn.plan_now_refill(_ctxs(issues))


# ── 3. the plan's rules ─────────────────────────────────────────────────────────


def test_a_live_queue_plans_nothing():
    plan = bn.plan_now_refill(_rows(_now_queue(bc.NOW_LIVENESS_MIN)))
    assert (plan.short, plan.picks, plan.residual_short) == (0, [], 0)
    assert bn.refill_remedy_lines(plan) == []


def test_picks_are_stories_only_because_only_stories_clear_the_rule():
    """`now_liveness` counts `type:story`. Proposing a `type:bug` would be a remedy that
    provably does not clear the finding — the promotion happens and the gate stays red."""
    issues = _now_queue(2) + [
        _issue(300, "Next", value=9.0, labels=("type:bug",)),
        _issue(301, "Next", value=9.0, labels=("type:chore",)),
        _issue(302, "Next", value=0.5),
    ]
    plan = bn.plan_now_refill(_rows(issues))
    assert [p.number for p in plan.picks] == [302]


def test_blocked_candidates_are_never_picked_but_are_counted():
    issues = _now_queue(2) + [_issue(400, "Next", value=9.0, labels=("type:story", "gate:owner")), _issue(401, "Later", value=0.1)]
    plan = bn.plan_now_refill(_rows(issues))
    assert [p.number for p in plan.picks] == [401]
    assert 400 in plan.blocked_donors, "a gate:owner candidate must be reported as a lever, never silently dropped"


def test_donor_order_follows_the_milestone_order_not_the_score():
    """Next before Later before Roadmap, derived from `bc.MILESTONE_ORDER`. A pure
    score sort would pull a high-scored parked product idea ahead of live debt."""
    issues = _now_queue(0) + [
        _issue(500, "Roadmap", value=9.0),
        _issue(501, "Later", value=5.0),
        _issue(502, "Next", value=0.1),
    ]
    plan = bn.plan_now_refill(_rows(issues))
    assert [p.number for p in plan.picks] == [502, 501, 500]
    assert [p.donor for p in plan.picks] == list(bc.DONOR_MILESTONES)


def test_within_one_milestone_the_stored_score_is_the_order():
    issues = _now_queue(0) + [_issue(600, "Next", value=0.5), _issue(601, "Next", value=3.0), _issue(602, "Next", value=1.5)]
    assert [p.number for p in bn.plan_now_refill(_rows(issues)).picks] == [601, 602, 600]


def test_the_roadmap_cap_is_enforced_and_the_remainder_is_counted():
    """ADR-099 ¶3: at most about one product item per cycle. The cap is the point — and
    so is counting what it held back, because 'the debt corpus is drained and the only
    remaining work is parked product vision' is a state an operator must be told about."""
    issues = _now_queue(0) + [_issue(700 + i, "Roadmap", value=1.0 + i) for i in range(5)]
    plan = bn.plan_now_refill(_rows(issues))
    assert len([p for p in plan.picks if p.is_product_pick]) == bc.ROADMAP_PICKS_PER_REFILL
    assert plan.product_held_back == 4
    assert plan.residual_short == 2


# ── 4. the connection itself ────────────────────────────────────────────────────


def test_the_blocking_finding_carries_the_derived_plan():
    """THE issue. Before #3254 the message was 'refill it (#1870's wrap step)' — a
    ritual's name. It must now contain the actual issue numbers to promote."""
    issues = _now_queue(1) + [_issue(800, "Next", value=2.0), _issue(801, "Roadmap", value=4.0)]
    findings = hy.rule_now_liveness(_ctxs(issues))
    assert [f.rule for f in findings] == ["now_liveness"]
    message = findings[0].message
    assert "#800" in message and "#801" in message, "the gate must name the promotions, not the ritual"
    assert "ADR-099 ¶3 product pick" in message, "a Roadmap promotion must be flagged as the budgeted product pick"
    assert "TWO edits" in message, "the milestone-only promotion is the measured failure; the message must say so"
    assert "--refill-now" in message, "the message must route to the command that prints the exact edits"


def test_the_finding_stays_a_single_blocking_violation():
    """The remedy is extra TEXT on one finding, not extra findings — a rule that starts
    emitting N findings would inflate every violation count that reads this report."""
    findings = hy.rule_now_liveness(_ctxs(_now_queue(0) + [_issue(900, "Next")]))
    assert len(findings) == 1 and findings[0].severity == hy.VIOLATION and findings[0].number is None


# ── 5. the loud-failure path ────────────────────────────────────────────────────


def test_an_unreachable_floor_says_no_remedy_and_names_the_levers():
    """When the corpus cannot reach the floor, silence and a generic nudge are the same
    failure. The verdict has to be distinct, and it must never suggest lowering the floor."""
    issues = _now_queue(0) + [_issue(1000, "Next", labels=("type:story", "gate:owner"))]
    message = hy.rule_now_liveness(_ctxs(issues))[0].message
    assert "NO REMEDY IN THE CORPUS" in message
    assert "FILE work" in message
    assert "#1000" in message, "the blocked story is a lever and must be named"
    assert "do NOT lower the floor" in message


def test_a_reachable_floor_does_not_claim_no_remedy():
    """The negative control for the rule above: a plan that reaches the floor must NOT
    print the exhausted verdict, or the loud line stops meaning anything."""
    message = hy.rule_now_liveness(_ctxs(_now_queue(2) + [_issue(1100, "Next")]))[0].message
    assert "NO REMEDY IN THE CORPUS" not in message


# ── 6. the two-edit truth, proved by running the real gate ──────────────────────


def _run_gate(tmp_path, issues, name, extra=()):
    import json

    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(issues), encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_backlog_hygiene.py"),
            "--issues-json",
            str(path),
            "--now",
            "2026-08-27T00:00:00Z",
            *extra,
        ],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={**os.environ, "PYTHONPATH": str(ROOT / "scripts")},
    )
    return proc.returncode, proc.stdout


def test_the_documented_milestone_only_promotion_does_not_clear_the_gate(tmp_path):
    """THE MUST-FAIL CASE, kept live. `/wrap` (e9) said `gh issue edit <N> --milestone
    Now` and nothing else. Applying it verbatim leaves the wrap red — `now_liveness`
    goes green and `score_line_canonical` fires in its place, both blocking. This is
    why the remedy text says TWO edits; delete that and this test is the record of why."""
    promoted = _issue(1200, "Now", value=2.0, score_milestone="Next")  # milestone moved, arrow left behind
    code, out = _run_gate(tmp_path, _now_queue(2) + [promoted], "milestone_only")
    assert code == 1, "the documented remedy must still be measurably insufficient, or this guard is vacuous"
    assert "score_line_canonical" in out
    assert "! [now_liveness]" not in out, "the count went green — that is exactly what makes the swap easy to miss"


def test_the_full_two_edit_promotion_clears_the_gate(tmp_path):
    """The green half. Same corpus, arrow retargeted too — exit 0."""
    promoted = _issue(1200, "Now", value=2.0)  # both halves applied
    code, out = _run_gate(tmp_path, _now_queue(2) + [promoted], "both_edits")
    assert code == 0, out


def test_retarget_score_line_is_the_second_edit_and_refuses_what_it_cannot_parse():
    raw = _score(2.0, "Roadmap")
    moved = bc.retarget_score_line(raw, "Now")
    assert moved is not None and moved.endswith("→ Now")
    assert bc.parse_score_line(moved).milestone == "Now"
    assert bc.parse_score_line(moved).value == 2.0
    # a legacy grammar cannot be retargeted — it has to be written, and saying so beats guessing
    assert bc.retarget_score_line("**Score:** P2*1.0/L=4 = 0.75 (Next)", "Now") is None
    assert bc.retarget_score_line(None, "Now") is None
    assert bc.retarget_score_line(raw, "Nowish") is None


def test_an_unscored_pick_is_offered_with_the_honest_instruction():
    """A promotable story with no canonical score line still gets picked (dropping it
    would hide the only remedy), but the plan says 'write one', never 'retarget one'."""
    unscored = {
        "number": 1300,
        "title": "no score line",
        "labels": [{"name": n} for n in ("type:story", "model:opus") + CONTRACT_LABELS],
        "milestone": {"title": "Next"},
        "body": "## Outcome\n**operator** — x.\n",
        "updatedAt": "2026-08-27T00:00:00Z",
    }
    plan = bn.plan_now_refill(_rows(_now_queue(2) + [unscored]))
    assert [p.number for p in plan.picks] == [1300]
    assert plan.picks[0].retargeted_score_line is None
    report = "\n".join(bn.render_refill(plan))
    assert "WRITE a canonical score line" in report


# ── 7. the lane half: startable-for-the-running-model, not merely present ───────
#
# Measured on the live corpus 2026-08-27 (the numbers below are that shape, minimised):
#   `Now`      3 stories, 1 newly `blocked:date` -> 2 startable, both model:opus
#   `Next`     1 startable -> model:fable
#   `Roadmap` 11 startable -> model:fable, all eleven
# So the ENTIRE sanctioned refill supply was 12 stories, 12 of them in a lane the running
# (all-Opus) session could not start. A lane-blind plan proposes one, the count goes green,
# and zero startable work is added. A remedy dischargeable dishonestly is not a remedy.


def _measured_2026_08_27():
    """The live shape above, in fixture form."""
    return (
        [_issue(2999, "Now", labels=("type:story",)), _issue(2848, "Now", labels=("type:story",))]
        + [_issue(2978, "Now", labels=("type:story", "blocked:date"))]
        + [_issue(2849, "Next", value=0.75, labels=("type:story",), lane="fable")]
        + [_issue(1400 + i, "Roadmap", value=1.0 + i, labels=("type:story",), lane="fable") for i in range(11)]
    )


def test_the_lane_blind_plan_is_gameable_on_the_measured_corpus():
    """The defect, stated as a test rather than as prose. Lane-blind, the plan proposes a
    `model:fable` promotion that takes the count to the floor — while the opus session
    that ran the wrap still has exactly two startable stories."""
    rows = _rows(_measured_2026_08_27())
    blind = bn.plan_now_refill(rows)
    assert blind.residual_short == 0, "lane-blind, the corpus 'reaches' the floor"
    assert [p.lane for p in blind.picks] == ["fable"]
    opus_startable_after = len([r for r in rows if r["milestone"] == "Now" and not r["blocking"] and r["model"] == "opus"])
    assert opus_startable_after == 2, "…and the running lane's startable count did not move"
    message = "\n".join(bn.refill_remedy_lines(blind))
    assert "LANE-BLIND COUNT" in message, "if the count can be cleared by off-lane work, the report must say so"
    assert "--lane" in message


def test_the_lane_scoped_plan_refuses_the_dishonest_discharge():
    """Same corpus, `--lane opus`: the twelve fable candidates are refused and COUNTED,
    and the verdict is NO REMEDY rather than a green number."""
    plan = bn.plan_now_refill(_rows(_measured_2026_08_27()), lane="opus")
    assert plan.picks == [], "no opus-startable candidate exists anywhere in the corpus"
    assert plan.residual_short == 1
    assert plan.off_lane_available == 12, "the refused supply is counted, never silently dropped"
    message = "\n".join(bn.refill_remedy_lines(plan))
    assert "NO REMEDY IN THE CORPUS (lane model:opus)" in message
    assert "12 startable story(ies) exist OUTSIDE lane model:opus" in message
    assert "That is not a remedy." in message
    assert "hand the wrap to a session in the lane that HAS the work" in message


def test_lane_scoping_still_finds_work_when_the_lane_actually_has_some():
    """The negative control. If `--lane opus` never planned anything the test above would
    be vacuous — scoping must be a filter, not an off switch."""
    corpus = _measured_2026_08_27() + [_issue(3300, "Next", value=5.0, labels=("type:story",), lane="opus")]
    plan = bn.plan_now_refill(_rows(corpus), lane="opus")
    assert [p.number for p in plan.picks] == [3300] and plan.residual_short == 0


def test_now_lane_coverage_fires_when_the_count_reads_live_and_is_lying():
    """Three startable stories on `Now`, all one lane: `now_liveness` is silent (the count
    is fine) and this advisory is the only thing that says two of three session lanes have
    nothing to do."""
    corpus = [_issue(3400 + i, "Now", labels=("type:story",), lane="fable") for i in range(3)]
    ctxs = _ctxs(corpus)
    assert hy.rule_now_liveness(ctxs) == [], "the lane-blind count is at the floor — that is the trap"
    hits = hy.rule_now_lane_coverage(ctxs)
    assert [(f.rule, f.severity) for f in hits] == [("now_lane_coverage", hy.ADVISORY)]
    assert "sonnet/opus session finds ZERO startable stories" in hits[0].message
    assert "fable 3" in hits[0].message and "opus 0" in hits[0].message, "the composition, zeros included, is the finding"


def test_now_lane_coverage_is_silent_on_a_lane_covered_queue():
    """Negative control: one startable story per lane and the advisory must not fire, or
    it degrades into an always-on line nobody reads."""
    corpus = [_issue(3500 + i, "Now", labels=("type:story",), lane=lane) for i, lane in enumerate(bc.MODEL_LANES)]
    assert hy.rule_now_lane_coverage(_ctxs(corpus)) == []


def test_now_lane_coverage_defers_to_now_liveness_below_the_floor():
    """One fact, one place. Below the floor the composition is already inside
    `now_liveness`'s own message, and printing it twice trains a reader to skim both."""
    corpus = [_issue(3600, "Now", labels=("type:story",), lane="fable")]
    assert hy.rule_now_liveness(_ctxs(corpus)) != []
    assert hy.rule_now_lane_coverage(_ctxs(corpus)) == []
    assert "fable 1" in hy.rule_now_liveness(_ctxs(corpus))[0].message, "…so it must be in the blocking message instead"


def test_the_gate_lane_flag_scopes_the_floor_end_to_end(tmp_path):
    """The whole path: `--lane opus` on the measured corpus exits 1 with the lane named,
    and the same corpus lane-blind exits 1 too — but for a different, weaker reason."""
    code, out = _run_gate(tmp_path, _measured_2026_08_27(), "lane_opus", extra=["--lane", "opus"])
    assert code == 1
    assert "in lane model:opus" in out and "NO REMEDY IN THE CORPUS (lane model:opus)" in out


# ── the CLI + the wrap step that owns the procedure ─────────────────────────────


def test_refill_now_cli_prints_the_plan_and_always_exits_zero(tmp_path, capsys):
    import json

    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(_now_queue(1) + [_issue(1400, "Next", value=2.0)]), encoding="utf-8")
    assert bn.main(["--issues-json", str(path), "--refill-now"]) == 0, "the selector stays advisory; the hygiene gate is the blocking half"
    out = capsys.readouterr().out
    assert "NOW-REFILL PLAN" in out and "gh issue edit 1400 --milestone Now" in out
    assert "→ Now" in out


def test_wrap_e9_names_the_planner_the_product_pick_and_the_second_edit():
    """The procedure ADR-099 ¶3 never wrote down. (e9) must name the command that
    derives the plan, the Roadmap path with its budget, and the score-line edit."""
    body = WRAP.read_text(encoding="utf-8").split("### (e9)", 1)[1].split("### (", 1)[0]
    assert "backlog_next.py --refill-now" in body
    assert "Roadmap" in body and "ADR-099" in body
    assert "score line" in body, "(e9) must state that a promotion is two edits, or it re-creates the measured failure"
    assert "NO REMEDY IN THE CORPUS" in body, "(e9) must say what to do when the plan cannot reach the floor"
