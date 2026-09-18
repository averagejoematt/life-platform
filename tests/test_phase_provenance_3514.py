"""tests/test_phase_provenance_3514.py — a CROSS_PHASE row never carries scoped provenance.

THE DEFECT (#3514, DA-6)
  `phase_taxonomy.should_phase_stamp(pk, sk)` has answered "may this row carry a write-time
  phase stamp?" since #2520. **No writer consulted it.** Every stamping writer called the
  unguarded `experiment_stamp()` and merged the result into whatever it was putting, so a
  CROSS_PHASE row got the same `phase`/`cycle` as an EXPERIMENT_SCOPED one.

  Measured live on 2026-09-17, before the fix (deploy/reconcile_provenance_2026_09.py
  --only 3514, dry-run): **22 rows** — 7 `COACH#*/RELATIONSHIP#state` singletons carrying
  `phase=experiment cycle=17`, and 15 `CHAT#` rows carrying `cycle=17`. Those are the
  partitions ADR-153 deliberately made cross-phase so Matthew's coach conversation history
  would survive every reset; a cycle stamp on one says it belongs to a single run.

  The reconcile classed all 22 `writer-restamped`: correct to remove, and put straight back
  by the live writer on its next run. **That is why this file guards the WRITER and not the
  rows** — a data fix without it reverts within a day.

WHAT IS PINNED HERE
  1. The gate itself (`experiment_stamp_for`) returns `{}` for every non-taggable class.
  2. The real writers, exercised end to end against a recording table, put no provenance on
     a CROSS_PHASE row and still stamp an EXPERIMENT_SCOPED one.
  3. The SET: every remaining direct `experiment_stamp(` call in `lambdas/` is enumerated
     from source and must carry a written exemption. A new ungated writer reds this file.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from experiment import phase_taxonomy as taxonomy  # noqa: E402

# ── 1. the gate ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "pk,sk",
    [
        ("COACH#sleep_coach", "RELATIONSHIP#state"),
        ("COACH#sleep_coach", "RELATIONSHIP#bits"),
        ("COACH#nutrition_coach", "CHAT#2026-09-15#21771f87"),
        ("COACH#physical_coach", "CHAT#summary#2026-08-12"),
    ],
)
def test_a_cross_phase_row_gets_no_stamp(pk, sk):
    assert taxonomy.classify(pk, sk) == taxonomy.CROSS_PHASE
    assert taxonomy.experiment_stamp_for(pk, sk) == {}


@pytest.mark.parametrize("pk,sk", [("COACH#nudge_ledger", "DAY#2026-09-01"), ("COACH#outbound_ledger", "DAY#2026-09-01")])
def test_a_system_state_row_gets_no_stamp(pk, sk):
    assert taxonomy.experiment_stamp_for(pk, sk) == {}


def test_an_experiment_scoped_row_STILL_gets_one():
    """The must-not-overshoot control. A gate that returned {} for everything would pass
    every assertion above while silently creating the #3513 defect (an unstamped scoped
    row passes PHASE_FILTER_EXPRESSION forever and is served as current)."""
    stamp = taxonomy.experiment_stamp_for("COACH#sleep_coach", "OUTPUT#2026-09-17")
    assert stamp.get("phase"), f"an EXPERIMENT_SCOPED row lost its stamp: {stamp}"


def test_an_unclassifiable_row_is_unstamped_not_raised():
    """`classify()` raises on an unknown pk by design. Every caller here is a fail-soft
    writer whose `except` would swallow that as a failed PUT and LOSE THE ROW — so the gate
    absorbs it and logs instead. Unstamped-and-announced is repairable; a dropped write is
    not."""
    assert taxonomy.experiment_stamp_for("NOSUCHPREFIX#x", "Y#1") == {}


# ── 2. the real writers ──────────────────────────────────────────────────────


class _RecordingTable:
    def __init__(self):
        self.written = []

    def put_item(self, Item=None, **_kw):  # noqa: N803 — boto3's own casing
        self.written.append(dict(Item or {}))
        return {}


@pytest.mark.parametrize(
    "module_path,helper",
    [
        ("coach.coach_state_updater", "_put_item"),
        ("coach.coach_history_summarizer", "_put_item"),
        ("coach.coach_ensemble_digest", "_put_item"),
    ],
)
@pytest.mark.parametrize("sk", ["RELATIONSHIP#state", "CHAT#2026-09-15#abc", "CHAT#summary#2026-08-10"])
def test_the_real_writers_put_no_provenance_on_a_cross_phase_row(monkeypatch, module_path, helper, sk):
    """End to end through the shipped helper, not through a re-implementation of it."""
    import importlib

    mod = importlib.import_module(module_path)
    rec = _RecordingTable()
    monkeypatch.setattr(mod, "table", rec)
    getattr(mod, helper)({"pk": "COACH#sleep_coach", "sk": sk, "payload": "x"})

    assert len(rec.written) == 1, f"{module_path}.{helper} wrote {len(rec.written)} items"
    item = rec.written[0]
    forbidden = [a for a in taxonomy.PROVENANCE_ATTRS if a in item]
    assert not forbidden, f"{module_path}.{helper} stamped a CROSS_PHASE row with {forbidden}: {item}"


@pytest.mark.parametrize(
    "module_path,helper",
    [
        ("coach.coach_state_updater", "_put_item"),
        ("coach.coach_history_summarizer", "_put_item"),
        ("coach.coach_ensemble_digest", "_put_item"),
    ],
)
def test_the_same_writers_STILL_stamp_a_scoped_row(monkeypatch, module_path, helper):
    """The must-fail control for the test above: if the gate were simply switched off, the
    four assertions above would all pass and this one would not."""
    import importlib

    mod = importlib.import_module(module_path)
    rec = _RecordingTable()
    monkeypatch.setattr(mod, "table", rec)
    getattr(mod, helper)({"pk": "COACH#sleep_coach", "sk": "OUTPUT#2026-09-17", "payload": "x"})

    assert rec.written and rec.written[0].get("phase"), f"{module_path}.{helper} dropped the stamp on a scoped row"


# ── 3. the SET ───────────────────────────────────────────────────────────────

# Direct `experiment_stamp(...)` calls that remain ungated, each with the reason. A new
# one reds this test: the point is that "which sks does this writer put?" stops being a
# fact a reader has to re-derive per module.
#
# The NAME deliberately matches none of `gate_census._REGISTRY_NAME`'s patterns (an
# `*_EXEMPT*` binding here would be expanded entry-by-entry by the family-3 walk into one
# phantom gate per ROW, injecting three verdict-less gates into the census — the #3315
# class). Same reasoning, and the same fix, as `gate_census_enforcement.
# NOT_APPLICABLE_REASONS`. The gate is the assertion below; these are its exemptions.
UNGATED_STAMP_CALL_REASONS = {
    # Both compute ONE stamp and hand it to a helper that writes to
    # USER#matthew#SOURCE#{achievements,milestone_ledger} — SOURCE# partitions, which hold
    # no CROSS_PHASE sk class, so there is no row here the gate would change. Threading a
    # pk/sk through those helpers would be motion without a defect behind it.
    "lambdas/compute/daily_metrics_compute_lambda.py": "SOURCE#achievements / SOURCE#milestone_ledger — no CROSS_PHASE sk on either partition",
    "lambdas/emails/milestone_digest_lambda.py": "SOURCE#milestone_ledger — same partition, same reason",
    # The gate's own implementation.
    "lambdas/experiment/phase_taxonomy.py": "defines experiment_stamp and the gate that wraps it",
}


def _modules_calling_experiment_stamp_directly() -> dict:
    """Every file under lambdas/ with a CALL to `experiment_stamp` (not
    `experiment_stamp_for`), by AST — never by grep, which reads the docstrings that
    explain the call and would report the Set as larger than it is."""
    found = {}
    for path in sorted((REPO_ROOT / "lambdas").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
            if name == "experiment_stamp":
                found.setdefault(str(path.relative_to(REPO_ROOT)), []).append(node.lineno)
    return found


def test_every_ungated_stamp_call_is_a_registered_exemption():
    calls = _modules_calling_experiment_stamp_directly()
    unregistered = {m: lines for m, lines in calls.items() if m not in UNGATED_STAMP_CALL_REASONS}
    assert not unregistered, (
        "these writers call experiment_stamp() directly and are not in UNGATED_STAMP_CALL_REASONS — "
        "use experiment_stamp_for(pk, sk) so the row's CLASS decides, or register the "
        f"exemption with the reason it is safe: {unregistered}"
    )


def test_the_ast_enumeration_is_not_vacuous():
    """If the walker matched nothing, the assertion above is empty and would pass over any
    number of ungated writers. The exemptions are the known-present members, so finding
    them proves the walker resolves real calls."""
    calls = _modules_calling_experiment_stamp_directly()
    assert calls, "the AST walk found ZERO experiment_stamp calls — the enumeration is broken, not clean"
    assert set(calls) == set(UNGATED_STAMP_CALL_REASONS), f"exemption registry drifted from the live Set: found {sorted(calls)}"


def test_the_gated_variant_is_actually_in_use():
    """The inverse non-vacuity check: prove the conversion happened rather than assuming
    an empty unregistered set means it did."""
    users = set()
    for path in sorted((REPO_ROOT / "lambdas").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.id if isinstance(fn, ast.Name) else (fn.attr if isinstance(fn, ast.Attribute) else None)
                if name == "experiment_stamp_for":
                    users.add(str(path.relative_to(REPO_ROOT)))
    assert len(users) >= 9, f"expected the gate at every converted writer, found {sorted(users)}"


# ── 4. the shared predicate the nightly audit and the reconcile both use ──────


def test_forbidden_provenance_names_exactly_the_attributes_the_class_forbids():
    item = {"phase": "experiment", "cycle": 17, "tombstone": True, "payload": "x"}
    assert taxonomy.forbidden_provenance("COACH#sleep_coach", "RELATIONSHIP#state", item) == ["phase", "cycle", "tombstone"]
    assert taxonomy.forbidden_provenance("COACH#sleep_coach", "RELATIONSHIP#state", {"payload": "x"}) == []
    # scoped rows are allowed all of it — this is the CROSS_PHASE predicate, not a general one
    assert taxonomy.forbidden_provenance("COACH#sleep_coach", "OUTPUT#2026-09-17", item) == []
