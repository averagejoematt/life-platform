"""#3217 — `regen_once`'s keep/discard predicate must not let a composite finding count
veto a correctness fix.

The defect, measured: on the 2026-08-26 17:00Z brief `nutrition_coach`'s draft cited
``326.3`` — the upper bound of a weight-prediction interval that appears nowhere in the
data it was given. A corrective rewrite REMOVED that figure, the rewrite's TOTAL finding
count did not fall, and `regen_once` discarded it on ``len(after) < len(before)``. The
draft carrying the invented number is the one that reached the blocking quality gate, with
no ``grounding self-corrected`` line anywhere in the log.

Both directions are pinned here, and both are mutation-proved against the pre-#3217
predicate (each keep/discard assertion carries the count arithmetic that shows what the old
one-line rule would have decided, so neither test can pass vacuously):

  * a rewrite that removes a `fabricated_number` but scores EQUAL OR WORSE on the composite
    is KEPT      -> `test_removing_the_fabricated_number_is_kept_even_when_the_total_grows`
  * a rewrite that removes NOTHING and scores worse is still DISCARDED
               -> `test_rewrite_that_removes_nothing_and_scores_worse_is_discarded`

The findings are produced by the REAL `grounding_findings` over the REAL draft sentence
pulled out of the retained `EVALRET#coach_brief` record — not hand-rolled dicts.

Run with:  python3 -m pytest tests/test_regen_keep_predicate_3217.py -v
"""

import os
import sys
from unittest import mock

LAMBDAS_DIR = os.path.join(os.path.dirname(__file__), "..", "lambdas")
sys.path.insert(0, os.path.abspath(LAMBDAS_DIR))

from ai import (
    grounded_generation as gg,  # noqa: E402
    regen_keep_predicate as rkp,  # noqa: E402
)

# ── the wire ─────────────────────────────────────────────────────────────────────────
# Verbatim from the held `nutrition_coach` draft (DDB `EVALRET#coach_brief`,
# sk `TS#2026-08-26T17:03:55.233094+00:00#3affa4f6`, verdict `flagged_dropped`), with the
# en-dash normalised to a hyphen. 326.3 is the fabricated figure; 320.5 / 314.7 / 326.2 are
# real and 80 is the interval width.
DRAFT = (
    "The weight prediction I had on the books called for 320.5 lb (80% interval 314.7-326.3 lb) "
    "- your logged weight of 326.2 lb sits at the edge of that interval."
)
_SOURCE = "prediction 320.5 lb, 80% interval lower bound 314.7 lb, logged weight 326.2 lb"
ALLOWED = gg.allowed_numbers(_SOURCE)


def _findings(text):
    """The real grounder, with the self-graded-verdict class armed (zero predictions
    evaluated this cycle — the state the 08-26 brief was actually in)."""
    return gg.grounding_findings(text, allowed=ALLOWED, evaluated_predictions=0)


def _types(findings):
    return sorted(f["type"] for f in findings)


# ── the wire reproduces ──────────────────────────────────────────────────────────────


def test_the_real_draft_yields_exactly_the_fabricated_326_3():
    """Non-vacuity anchor: the fixture is the wire, and it flags what the incident flagged."""
    findings = _findings(DRAFT)
    assert _types(findings) == ["fabricated_number"]
    assert findings[0]["claimed"] == 326.3


# ── direction 1: the bug. Removing the figure wins, whatever the composite did ────────

# Removes 326.3 (keeps every real figure) and, in doing so, picks up THREE framing-class
# findings: the coach grades its own still-pending calls. Total 1 -> 3.
REWRITE_FIXES_FIGURE_SCORES_WORSE = (
    "The weight prediction I had on the books called for 320.5 lb, and your logged weight of 326.2 lb "
    "sits at the edge of that interval. That is a hit. I was right about the direction. "
    "Week-one protein consistency exceeded my predictions."
)


def test_removing_the_fabricated_number_is_kept_even_when_the_total_grows():
    before, after = _findings(DRAFT), _findings(REWRITE_FIXES_FIGURE_SCORES_WORSE)

    # MUTATION PROOF, direction 1. The pre-#3217 predicate was `len(after) < len(before)`;
    # spelled out here so this assertion cannot pass by accident. It is FALSE, so the old
    # rule discarded this rewrite — the exact 326.3 defect.
    assert len(after) >= len(before), "fixture must reproduce the veto: the composite must NOT improve"
    assert not (len(after) < len(before))

    assert "fabricated_number" not in _types(after), "the rewrite must actually fix the figure"
    keep, arm, note = rkp.keep_rewrite(before, after)
    assert keep is True, "a rewrite that removes an invented figure must be kept"
    assert arm == rkp.KEEP_FIGURE_REMOVED
    assert "figures 1->0" in note


def test_regen_once_end_to_end_keeps_the_figure_fixing_rewrite():
    """Through the real harness, not just the predicate."""
    text, findings, corrected = gg.regen_once(DRAFT, _findings, lambda _corr: REWRITE_FIXES_FIGURE_SCORES_WORSE, surface="test_3217")
    assert corrected is True
    assert text == REWRITE_FIXES_FIGURE_SCORES_WORSE
    assert "fabricated_number" not in _types(findings)


def test_regen_once_does_not_log_a_discard_when_the_figure_arm_fires():
    with mock.patch.object(gg._regen_telemetry, "log_discard") as m:
        gg.regen_once(DRAFT, _findings, lambda _corr: REWRITE_FIXES_FIGURE_SCORES_WORSE, surface="test_3217")
    assert m.call_count == 0, "a KEPT rewrite is not a discard"


# ── direction 2: the fix must not degenerate into 'always keep the rewrite' ───────────

# Removes nothing (326.3 survives verbatim) and adds a second invented figure.
REWRITE_REMOVES_NOTHING_SCORES_WORSE = (
    "The weight prediction I had on the books called for 320.5 lb (80% interval 314.7-326.3 lb) "
    "- your logged weight of 326.2 lb sits at the edge of that interval, and your trailing average is 331.9 lb."
)


def test_rewrite_that_removes_nothing_and_scores_worse_is_discarded():
    before, after = _findings(DRAFT), _findings(REWRITE_REMOVES_NOTHING_SCORES_WORSE)

    # MUTATION PROOF, direction 2: 326.3 is still there AND a new figure joined it.
    assert 326.3 in [f.get("claimed") for f in after], "fixture must not fix anything"
    assert len(after) > len(before)

    keep, arm, _note = rkp.keep_rewrite(before, after)
    assert keep is False
    assert arm == rkp.DISCARD_FIGURE_INTRODUCED


def test_identical_rewrite_is_discarded():
    """The no-op case: a 'rewrite' that changed nothing must never be kept."""
    before = after = _findings(DRAFT)
    keep, arm, _note = rkp.keep_rewrite(before, after)
    assert keep is False and arm == rkp.DISCARD_NOT_BETTER


def test_more_framing_findings_alone_never_keeps_a_rewrite():
    """No figure finding on either side, composite strictly worse -> discard. Guards the
    asymmetry from leaking into 'any change is an improvement'."""
    clean = "Your logged weight of 326.2 lb sits at the edge of that interval."
    worse = clean + " That is a hit. I was right about the direction."
    before, after = _findings(clean), _findings(worse)
    assert before == [] and len(after) >= 1
    keep, arm, _note = rkp.keep_rewrite(before, after)
    assert keep is False and arm == rkp.DISCARD_NOT_BETTER


# ── the ruling: removes one figure, introduces another -> DISCARD ─────────────────────

# Drops 326.3 and invents 312.8 in its place. Composite total is IDENTICAL (1 -> 1), so the
# old rule discarded it too — but for the wrong reason (the count), and the new dispositive
# arm must not rescue it.
REWRITE_SWAPS_ONE_FIGURE_FOR_ANOTHER = (
    "The weight prediction I had on the books called for 320.5 lb (80% interval 312.8-326.2 lb) "
    "- your logged weight of 326.2 lb sits at the edge of that interval."
)


def test_removing_one_figure_while_introducing_another_is_discarded():
    before, after = _findings(DRAFT), _findings(REWRITE_SWAPS_ONE_FIGURE_FOR_ANOTHER)
    assert [f["claimed"] for f in before] == [326.3]
    assert [f["claimed"] for f in after] == [312.8], "the swap must be a genuine removes-one/adds-one"

    keep, arm, _note = rkp.keep_rewrite(before, after)
    assert keep is False, "trading one invented figure for another is not a correctness improvement"
    assert arm == rkp.DISCARD_FIGURE_INTRODUCED


def test_swap_across_figure_classes_is_also_discarded():
    """The cross-class form of the same trade: fabricated_number out, fabricated_date in.
    Both are FIGURE classes, so the sub-multiset test must catch it."""
    before = [{"type": "fabricated_number", "claimed": 326.3, "detail": "..."}]
    after = [{"type": "fabricated_date", "claimed": "2026-01-02", "detail": "..."}]
    keep, arm, _note = rkp.keep_rewrite(before, after)
    assert keep is False and arm == rkp.DISCARD_FIGURE_INTRODUCED


def test_a_figure_removed_and_a_framing_finding_added_is_kept():
    """The deliberate asymmetry, stated as a test so a future reader sees it was chosen."""
    before = [{"type": "fabricated_number", "claimed": 326.3, "detail": "..."}]
    after = [{"type": "stale_phase", "detail": "..."}, {"type": "ungrounded_behavioral", "detail": "..."}]
    keep, arm, _note = rkp.keep_rewrite(before, after)
    assert keep is True and arm == rkp.KEEP_FIGURE_REMOVED


# ── the pre-#3217 arm is preserved ────────────────────────────────────────────────────


def test_strictly_fewer_still_fires_and_is_named_as_the_old_arm():
    before = [{"type": "stale_phase", "detail": "a"}, {"type": "stale_phase", "detail": "b"}]
    after = [{"type": "stale_phase", "detail": "a"}]
    keep, arm, _note = rkp.keep_rewrite(before, after)
    assert keep is True and arm == rkp.KEEP_STRICTLY_FEWER


def test_the_new_arm_is_purely_ADDITIVE_over_the_old_predicate():
    """The non-regression invariant, over the whole small-multiset space rather than one
    example: #3217 may turn a pre-#3217 DISCARD into a keep, but must NEVER turn a
    pre-#3217 KEEP into a discard. `len(after) < len(before)` still implies keep.

    This is the guard against a subtler version of the bug — a dispositive arm that also
    quietly TIGHTENED the composite arm would strand rewrites that used to correct fine.
    """
    import itertools

    universe = [
        {"type": "fabricated_number", "claimed": 1.0, "detail": "a"},
        {"type": "fabricated_number", "claimed": 2.0, "detail": "b"},
        {"type": "contradiction", "claimed": 3.0, "detail": "c"},
        {"type": "stale_phase", "detail": "d"},
        {"type": "ungrounded_behavioral", "detail": "e"},
    ]
    combos = [list(c) for n in range(4) for c in itertools.combinations_with_replacement(universe, n)]
    checked = 0
    for before in combos:
        for after in combos:
            keep, arm, _n = rkp.keep_rewrite(before, after)
            if len(after) < len(before):
                assert keep is True and arm == rkp.KEEP_STRICTLY_FEWER, f"regressed an old keep: {before} -> {after}"
                checked += 1
            if keep and arm == rkp.KEEP_FIGURE_REMOVED:
                # The new arm only ever fires where the old one did NOT.
                assert len(after) >= len(before)
                assert not (rkp.figure_census(after) - rkp.figure_census(before))
    assert checked > 100, f"space too small to be evidence (only {checked} old-keep pairs)"


def test_discard_telemetry_names_the_predicate_that_dropped_it():
    """Acceptance box 3: the 326.3 case was invisible except by replaying the draft."""
    with mock.patch.object(gg._regen_telemetry, "log_discard") as m:
        text, _f, corrected = gg.regen_once(DRAFT, _findings, lambda _corr: REWRITE_SWAPS_ONE_FIGURE_FOR_ANOTHER, surface="test_3217_swap")
    assert not corrected and text == DRAFT
    assert m.call_count == 1
    args, kwargs = m.call_args
    assert args[0] == rkp.DISCARD_FIGURE_INTRODUCED
    assert args[1] == "test_3217_swap"
    assert "figures 1->1" in kwargs["reason"] and "total 1->1" in kwargs["reason"]


# ── registry drift: the figure set must stay a superset of the gate's numeric set ─────


def test_numeric_finding_types_are_a_subset():
    """#3202 split the finding registry into 'ungrounded number' vs 'grounding violation'
    for the corrective note's label (`coach_quality_gate._NUMERIC_FINDING_TYPES`). This
    predicate's FIGURE_TYPES is deliberately a superset — a fabricated date / guessed
    weekday / stale baseline is the same 'the value is not real' defect in a token class the
    number gate cannot see (#1242). Pinned so the two cannot drift apart silently."""
    from coach.coach_quality_gate import _NUMERIC_FINDING_TYPES

    assert _NUMERIC_FINDING_TYPES <= rkp.FIGURE_TYPES
    assert rkp.FIGURE_TYPES - _NUMERIC_FINDING_TYPES == {"fabricated_date", "weekday_mismatch", "stale_baseline"}


def test_every_figure_type_is_a_type_the_grounder_can_actually_emit():
    """Guard the SET, not the instance: a typo'd class name would silently make the
    dispositive arm unreachable for that class and nothing else would notice."""
    import re

    emitted = set()
    for path in ("ai/grounded_generation.py", "ai/baseline_freshness.py", "ai/night_scope.py"):
        src = open(os.path.join(os.path.abspath(LAMBDAS_DIR), path), encoding="utf-8").read()
        emitted |= set(re.findall(r'"type":\s*"([a-z_]+)"', src))
    missing = rkp.FIGURE_TYPES - emitted
    assert not missing, f"FIGURE_TYPES names class(es) no grounder emits: {sorted(missing)}"


# ── fail-soft ─────────────────────────────────────────────────────────────────────────


def test_malformed_findings_never_raise():
    assert rkp.keep_rewrite(None, None) == (False, rkp.DISCARD_NOT_BETTER, "figures 0->0 total 0->0")
    # Non-dict entries still COUNT toward the composite (they are findings the caller
    # produced); they simply contribute nothing to the figure census.
    junk_before = ["not a dict", 7]
    junk_after = [{"type": "fabricated_number", "claimed": 1.0}, "still not a dict"]
    assert rkp.keep_rewrite(junk_before, junk_after) == (False, rkp.DISCARD_FIGURE_INTRODUCED, "figures 0->1 total 2->2")
