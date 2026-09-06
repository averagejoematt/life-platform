"""#3390 — the supersede reflex's editor's-note leg.

`deploy/supersede_baseline_editors_note.py` generalises the cycle-11 one-shot
(`fix_prologue_part3_editors_note.py`, #1985) so a reset that anchors on
`--override-weight-lbs` can be reconciled in ANY cycle without a fresh hardcoded
pair of literals. These tests pin the three properties that make that safe:

  1. the repair SET is decided by the gate's own assessor, never by a slug literal;
  2. the spliced note actually clears `assess_frozen_artifact_weights` — the check
     it exists to satisfy — rather than merely containing the words "editor's note"
     in a shape nobody re-ran the gate against;
  3. a note whose figures went stale is REPLACED, not skipped. That is the failure
     the one-shot could not have (it ran once); a reusable script that skipped on a
     stale stamp would leave a superseded figure behind a green `is_annotated()`.

Negative controls throughout: each must-fire case is paired with a must-NOT-fire one.
"""

import importlib.util
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO, os.path.join(REPO, "lambdas"), os.path.join(REPO, "deploy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from operational import weight_truth_qa  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "supersede_baseline_editors_note", os.path.join(REPO, "deploy", "supersede_baseline_editors_note.py")
)
sen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sen)


# The live cycle-16 shape: Prologue III presents the override as the start weight.
PROSE_UNRECONCILED = (
    "The Plan, On the Record. 324.64 lbs at the start · 185 lbs the target. "
    "The destination. 324.64 pounds on the morning of Day 1. 185 pounds twelve months later."
)
MANIFEST = {
    "posts": [
        {"url": "/journal/posts/week-03/", "date": "2026-09-04", "title": "The Plan, On the Record"},
        {"url": "/journal/posts/week-01/", "date": "2026-08-30", "title": "Before the Numbers"},
    ]
}


def _surface(prose, path="/journal/posts/week-03/"):
    return {"name": "Prologue III", "path": path, "prose": prose, "frozen": True}


# ── 1. the set comes from the gate ────────────────────────────────────────────


def test_plan_repairs_targets_exactly_what_the_gate_flags():
    repairs, problems = sen.plan_repairs([_surface(PROSE_UNRECONCILED)], 326.2, MANIFEST, 16)
    assert problems == []
    assert len(repairs) == 1
    assert repairs[0]["sk"] == "DATE#2026-09-04"  # resolved through the manifest, not hardcoded
    assert repairs[0]["superseded"] == [324.64]


def test_negative_control_a_baseline_inside_tolerance_plans_nothing():
    """The must-NOT-fire twin: 324.64 vs 325.0 is inside the 1.5 lb tolerance, so the
    gate is silent and so is the repair. A planner that fired here would annotate
    pages the gate never asked about."""
    repairs, problems = sen.plan_repairs([_surface(PROSE_UNRECONCILED)], 325.0, MANIFEST, 16)
    assert (repairs, problems) == ([], [])


def test_a_slug_absent_from_the_manifest_is_a_problem_not_a_guess():
    repairs, problems = sen.plan_repairs([_surface(PROSE_UNRECONCILED, "/journal/posts/week-09/")], 326.2, MANIFEST, 16)
    assert repairs == []
    assert problems and "week-09" in problems[0]


# ── 2. the note clears the gate it exists for ─────────────────────────────────


def test_the_spliced_note_clears_the_assessor_that_demanded_it():
    """End-to-end on the real rule: annotate, then re-run the SAME assessor."""
    baseline = 326.2
    before = weight_truth_qa.assess_frozen_artifact_weights([_surface(PROSE_UNRECONCILED)], baseline)
    assert len(before) == 1, "positive control: the un-annotated page must fail first"

    stamp = sen.stamp_for(16, [324.64], baseline)
    _, note_md = sen.render_note(sen.note_text([324.64], baseline, "2026-09-05"), stamp)
    annotated, action = sen.splice(PROSE_UNRECONCILED, note_md, stamp)
    assert action == "added"

    after = weight_truth_qa.assess_frozen_artifact_weights([_surface(annotated)], baseline)
    assert after == [], f"the note did not clear the gate: {after}"
    assert "324.64" in annotated, "the frozen prose keeps its original figure — that is what frozen means"
    assert "326.2" in annotated, "the note must NAME the governing figure"


# ── 3. idempotency, and the staleness case that idempotency alone gets wrong ──


def test_rerunning_with_the_same_figures_is_a_no_op():
    stamp = sen.stamp_for(16, [324.64], 326.2)
    _, note = sen.render_note("n", stamp)
    once, a1 = sen.splice(PROSE_UNRECONCILED, note, stamp)
    twice, a2 = sen.splice(once, note, stamp)
    assert (a1, a2) == ("added", "unchanged")
    assert twice == once


def test_a_stale_note_is_replaced_rather_than_skipped():
    old_stamp = sen.stamp_for(16, [324.64], 326.2)
    _, old_note = sen.render_note(sen.note_text([324.64], 326.2, "2026-09-05"), old_stamp)
    annotated, _ = sen.splice(PROSE_UNRECONCILED, old_note, old_stamp)

    new_stamp = sen.stamp_for(17, [326.2], 330.0)
    _, new_note = sen.render_note(sen.note_text([326.2], 330.0, "2026-10-01"), new_stamp)
    out, action = sen.splice(annotated, new_note, new_stamp)

    assert action == "replaced"
    assert out.count("supersede-note:start") == 1, "exactly one note block survives"
    assert "330" in out and old_stamp not in out


def test_the_stamp_moves_when_any_asserted_figure_moves():
    base = sen.stamp_for(16, [324.64], 326.2)
    assert base != sen.stamp_for(16, [324.64], 326.3)
    assert base != sen.stamp_for(17, [324.64], 326.2)
    assert base != sen.stamp_for(16, [324.0], 326.2)


# ── stats_line: a live claim, re-anchored; frozen prose, never ───────────────


@pytest.mark.parametrize(
    "stats,expected",
    [
        (
            "324.64 lbs at the start · 185 lbs the target · 14 board predictions filed",
            "326.2 lbs at the start · 185 lbs the target · 14 board predictions filed",
        ),
        # negative control: an un-flagged figure is left exactly alone.
        ("321.09 lbs at the start · 185 lbs the target", "321.09 lbs at the start · 185 lbs the target"),
        ("Prologue | Before Day 1 | Seattle, WA", "Prologue | Before Day 1 | Seattle, WA"),
    ],
)
def test_reanchor_touches_only_the_flagged_start_figure(stats, expected):
    assert sen.reanchor_stats_line(stats, [324.64], 326.2) == expected


def test_reanchor_never_touches_the_target_weight():
    out = sen.reanchor_stats_line("324.64 lbs at the start · 185 lbs the target", [324.64], 326.2)
    assert "185 lbs the target" in out


def test_fmt_reads_like_prose():
    assert (sen.fmt(326.2), sen.fmt(326.0), sen.fmt(324.64)) == ("326.2", "326", "324.64")
