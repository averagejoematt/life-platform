"""tests/test_ai_budget_ledger_3374.py — the per-feature AI budget ledger contract (#3374 R3).

Defect class owned: unbounded, unattributed AI spend growth — the Bedrock
`unknown` bucket reached $33.19/8,524 calls in August 2026 before anything
noticed, and no per-feature ceiling existed at all. The ledger
(scripts/ai_budget_ledger.py) is the registry; this file is its pre-merge
contract:

  * SET EQUALITY against ``budget_guard._FEATURE_CUTOFF`` (+ ``unknown``) — a
    new AI feature cannot ship without a budget row, a deleted one cannot leave
    a ghost row (the emf_namespace_ledger discipline, #2837);
  * the ``unknown`` budget is DOWN-ONLY, founded at $33.19 (the August actual)
    — pinned HERE as well as in the ledger, so raising it is a two-file,
    reviewed act, never a drive-by;
  * budgets follow the stated derivation rule (R2's 1.15 growth clause over the
    founding month, $1 floor) — recomputed, never trusted;
  * mutation controls both directions on ``validate()`` AND ``evaluate_close()``
    — a gate whose must-fail case cannot fail is decoration (the vacuous
    negative-control class).

#3447 (the Session S calculation-proof pass) found the founding guards above
were founding-MONTH snapshots, not invariants, and this file closes three of
the four legs (the fourth, secrets registry-vs-estate, is a close-time-only
check in ``scripts/monthly_close.py`` — it needs a live AWS read this file
deliberately never makes):

  * leg (b) — the down-only check above compared only against the FOUNDING
    pin, so ratchet-to-$5-then-reraise-to-$20 (still <= founding) was a quiet
    ONE-file edit. ``test_current_unknown_budget_matches_pin`` below pins the
    CURRENT committed value too, by equality — any move off it, anywhere in
    the range, now requires touching this file as well;
  * leg (a) — a named spend dimension claimed by no row and not ``unknown``
    was invisible to every close check (the founding $9.22/8-dimension
    escape); covered by the unclaimed-dimension tests below;
  * leg (c) — a founding->=$1 EXCLUSIVE row reading $0.00 graded as a clean
    bill; covered by the absent-emitter tests below.

The close-time half (spend vs. budget on live CloudWatch data) runs in
``scripts/monthly_close.py`` step [5/5]; nothing here calls AWS.
"""

import copy
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import ai_budget_ledger as ledger  # noqa: E402

# The founding value of the down-only unknown ratchet — the August 2026 actual.
# Deliberately restated here as a literal: the ledger's own constant asserting
# against itself would be a vacuous control.
UNKNOWN_FOUNDING_PIN = 33.19

# #3447 leg (b): the CURRENT committed unknown budget, pinned independently of
# the founding value above. Update this line AND the ledger's row together —
# that pairing IS the two-file, reviewed act for a move in EITHER direction,
# closing the sub-founding-range hole the founding-only pin left open.
CURRENT_UNKNOWN_BUDGET_PIN = 33.19


@pytest.fixture(autouse=True)
def _restore_ledger():
    """Mutation tests plant defects in the REAL module dict (so validate() reads
    exactly what the gate reads); restore it afterwards."""
    snapshot = copy.deepcopy(ledger.LEDGER)
    yield
    ledger.LEDGER.clear()
    ledger.LEDGER.update(snapshot)


def test_committed_ledger_is_sound():
    assert ledger.validate() == []


def test_set_equality_against_feature_cutoff():
    """Ledger keys == _FEATURE_CUTOFF keys + unknown — equality, not containment."""
    features = ledger.budget_guard_features()
    assert len(features) > 0
    assert set(ledger.LEDGER) == set(features) | {ledger.UNKNOWN_KEY}


def test_mutation_a_new_feature_without_a_row_fails():
    """The load-bearing direction: a feature budget_guard declares but the ledger
    doesn't must red — that is how a NEW AI caller is forced to declare a budget."""
    del ledger.LEDGER["ensemble"]
    assert any("no ledger row" in f for f in ledger.validate())


def test_mutation_a_ghost_row_fails():
    ledger.LEDGER["retired_feature_nobody_declares"] = dict(ledger.LEDGER["ensemble"])
    assert any("no longer declares" in f for f in ledger.validate())


def test_unknown_budget_is_down_only():
    """The committed unknown budget may equal the founding pin or sit below it —
    never above. Both the ledger's constant and its committed budget are checked
    against THIS file's pin, so a quiet raise in the module cannot pass."""
    assert ledger.UNKNOWN_FOUNDING_USD == UNKNOWN_FOUNDING_PIN
    budget = ledger.LEDGER[ledger.UNKNOWN_KEY]["monthly_budget_usd"]
    assert budget is not None and budget <= UNKNOWN_FOUNDING_PIN


def test_mutation_raising_the_unknown_budget_fails():
    ledger.LEDGER[ledger.UNKNOWN_KEY]["monthly_budget_usd"] = UNKNOWN_FOUNDING_PIN + 0.01
    assert any("down-only" in f for f in ledger.validate())


def test_lowering_the_unknown_budget_is_quiet():
    """``validate()`` in isolation still permits a quiet lower — the ratchet's
    whole point: attribution landing lets the bucket shrink with no ceremony
    beyond the edit itself. (The FULL contract still requires the current-pin
    test below to match the committed file, which is what makes a real commit
    a two-file act; this test is only about validate()'s own permissiveness.)"""
    ledger.LEDGER[ledger.UNKNOWN_KEY]["monthly_budget_usd"] = 5.00
    assert ledger.validate() == []


def test_current_unknown_budget_matches_pin():
    """#3447 leg (b): the CURRENT committed value, not just the founding one, is
    pinned here by EQUALITY. This is the full-range companion to the founding
    pin above — it closes the sub-founding hole where a value anywhere in
    [$0, founding] passed the old down-only check with no test-file edit."""
    assert ledger.LEDGER[ledger.UNKNOWN_KEY]["monthly_budget_usd"] == CURRENT_UNKNOWN_BUDGET_PIN


def test_mutation_the_founding_exploit_shape_fails_the_current_pin():
    """The exact #3447 leg (b) finding, reproduced and then closed: ratchet the
    unknown budget down to $5, then re-raise it to $20 — still <= founding
    $33.19, so the OLD down-only guard (checked here via validate()) stays
    quiet on both moves. The new current-value pin is what catches it."""
    ledger.LEDGER[ledger.UNKNOWN_KEY]["monthly_budget_usd"] = 5.00
    assert ledger.validate() == []  # the founding-only guard: quiet
    ledger.LEDGER[ledger.UNKNOWN_KEY]["monthly_budget_usd"] = 20.00
    assert ledger.validate() == []  # still <= founding — this WAS the one-file hole
    # the current-pin equality is what a real PR's test suite would catch:
    assert ledger.LEDGER[ledger.UNKNOWN_KEY]["monthly_budget_usd"] != CURRENT_UNKNOWN_BUDGET_PIN


def test_mutation_a_budget_off_the_stated_rule_fails():
    ledger.LEDGER["daily_brief_ai"]["monthly_budget_usd"] = 40.00
    assert any("stated rule" in f for f in ledger.validate())


def test_mutation_a_shared_row_with_a_budget_fails():
    """Per-feature dollars don't exist for a shared dimension value — a budget
    there would grade a number that measures the wrong thing."""
    ledger.LEDGER["chronicle"]["monthly_budget_usd"] = 1.00
    assert any("cannot carry a budget" in f for f in ledger.validate())


# ── close-time evaluation: controls both directions ──────────────────────────


def _attribution(rows):
    return {"features": [{"feature": k, "cost_usd": v} for k, v in rows.items()]}


def _baseline_rows():
    """A synthetic month where everything sits exactly at budget (boundary green)."""
    rows = {}
    for name, row in ledger.LEDGER.items():
        if row["monthly_budget_usd"] is None:
            continue
        keys = row["attribution_keys"]
        rows[keys[0]] = row["monthly_budget_usd"]
        for k in keys[1:]:
            rows[k] = 0.0
    return rows


def test_close_at_budget_is_quiet():
    assert ledger.evaluate_close(_attribution(_baseline_rows())) == []


def test_close_overage_fails_and_names_the_feature():
    rows = _baseline_rows()
    rows["daily-brief"] += 0.02
    failures = ledger.evaluate_close(_attribution(rows))
    assert any(f.startswith("daily_brief_ai:") for f in failures)


def test_close_sums_a_multi_key_row():
    """coach_narrative's budget covers the PIPELINE — spread the overage across
    two of its lambdas and the sum must still trip."""
    rows = _baseline_rows()
    rows["coach-narrative-orchestrator"] = ledger.LEDGER["coach_narrative"]["monthly_budget_usd"] - 1.00
    rows["coach-state-updater"] = 1.02
    failures = ledger.evaluate_close(_attribution(rows))
    assert any(f.startswith("coach_narrative:") for f in failures)


def test_close_unknown_growth_fails_shrink_is_quiet():
    rows = _baseline_rows()
    rows["unknown"] = ledger.LEDGER[ledger.UNKNOWN_KEY]["monthly_budget_usd"] + 0.02
    assert any(f.startswith("unknown:") and "down-only" in f for f in ledger.evaluate_close(_attribution(rows)))
    rows["unknown"] = 1.23  # shrinking NEVER reds — that is the ratchet's success state
    assert ledger.evaluate_close(_attribution(rows)) == []


def test_close_dead_men():
    """Absence is failure, never success: an empty measurement and a missing
    `unknown` datapoint are both indistinguishable from a broken query."""
    assert any("no stamped spend" in f for f in ledger.evaluate_close(_attribution({})))
    rows = _baseline_rows()
    rows.pop("unknown", None)
    assert any("no `unknown` datapoint" in f for f in ledger.evaluate_close(_attribution(rows)))


# ── #3447 leg (a): unclaimed named dimensions ─────────────────────────────────


def test_close_unclaimed_dimension_fails_and_names_it():
    """The founding finding, reproduced: named LambdaFunction dimensions with
    real spend, claimed by no row and not `unknown`, must red — the $9.22/
    8-dimension escape this leg exists to catch."""
    rows = _baseline_rows()
    rows["ai-expert-analyzer"] = 4.45
    rows["coach-quality-gate"] = 2.66
    failures = ledger.evaluate_close(_attribution(rows))
    hit = next((f for f in failures if f.startswith("unclaimed named dimension")), None)
    assert hit is not None
    assert "ai-expert-analyzer" in hit and "coach-quality-gate" in hit
    assert "$7.11" in hit


def test_close_a_tiny_unclaimed_dimension_under_the_floor_is_quiet():
    """A cent of noise under an unrecognized dimension name is not the defect
    class — only real, floor-clearing unclaimed spend should red (positive
    control for the floor itself, not just its presence)."""
    rows = _baseline_rows()
    rows["some-new-experimental-lambda"] = 0.03
    assert ledger.evaluate_close(_attribution(rows)) == []


def test_close_a_claimed_dimension_never_counts_as_unclaimed():
    """Negative control: a dimension already named in a SHARED row's
    attribution_keys (e.g. wednesday-chronicle) is claimed — carrying its
    normal spend must never trip the unclaimed-dimension check."""
    rows = _baseline_rows()
    rows["wednesday-chronicle"] = 0.29  # chronicle + chronicle_editor's real Aug combined figure
    assert ledger.evaluate_close(_attribution(rows)) == []


# ── #3447 leg (c): absent/renamed-emitter flag ────────────────────────────────


def test_close_a_dead_founding_emitter_is_flagged_not_passed():
    """The rename-mode finding: a founding->=$1 EXCLUSIVE row reading exactly
    $0.00 must be flagged as a probable absent/renamed emitter, never pass
    quietly the way `spend.get(k, 0.0)` alone would let it."""
    rows = _baseline_rows()
    rows["daily-brief"] = 0.0
    failures = ledger.evaluate_close(_attribution(rows))
    assert any(f.startswith("daily_brief_ai:") and "absent or renamed emitter" in f for f in failures)


def test_close_a_sub_dollar_founding_row_at_zero_is_not_flagged():
    """Negative control: coach_nudge founded at $0.00 — genuinely idle is its
    normal state, not a broken emitter; the floor must not fire on it."""
    rows = _baseline_rows()
    rows["coach-nudge"] = 0.0
    assert ledger.evaluate_close(_attribution(rows)) == []


def test_close_unknown_at_zero_is_never_flagged_as_absent():
    """`unknown` reading $0.00 means attribution reached 100% — the ratchet's
    own success state — never a broken-emitter flag; it has its own dedicated
    (missing-datapoint) absence check above instead."""
    rows = _baseline_rows()
    rows["unknown"] = 0.0
    assert ledger.evaluate_close(_attribution(rows)) == []
