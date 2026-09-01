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
    """The ratchet's whole point: attribution landing lets the bucket shrink with
    no ceremony beyond the edit itself."""
    ledger.LEDGER[ledger.UNKNOWN_KEY]["monthly_budget_usd"] = 5.00
    assert ledger.validate() == []


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
