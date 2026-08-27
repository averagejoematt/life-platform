"""tests/test_reconcile_literal_verdict_2578.py — #2578: an instrument must not report
success while leaving its job undone.

TWO INSTANCES OF ONE CLASS, both found and fixed together.

1. THE RECONCILE JOB (the #3234 class, unfixed). #3234 fixed the INSTANCE: `ci-cd.yml`'s
   reconcile job could not `import yaml`, so the gate-census fact was skipped honestly,
   the generators left the tree byte-identical, the job printed "already match config
   truth" and went green — and `test / Unit Tests` in the same run failed on the drift
   the job had declined to fix. Main went red twice on 2026-08-27 with a green reconcile
   job above it. Installing PyYAML fixed that fact; it gave the job no way to notice the
   next one. The job now runs `sync_doc_metadata.py --check` on the tree it is leaving
   and fails loudly if it is still non-zero.

   Note what is NOT being changed: an underivable fact outside `--check` SHOULD skip with
   a printed reason. That is #3156's behaviour and it is correct. The defect is the JOB
   concluding success on a tree it left drifted.

2. AN INCOMPLETE CENSUS SWEEP (the same shape, one layer down, found while writing (1)).
   `build_census()` has two families that skip themselves on an unusable input and say so
   in a LOG LINE. A log line is not a value: the returned gate list came back short by
   that family's n with nothing in the structure to say so, and
   `sync_census_fact.discover_gate_census_count()` reported the short number with
   `error=None` — a successful-looking measurement. Measured on this tree with
   `tests/premerge_derivation.py`'s import blocked: **554 -> 450**, and an `--apply` run
   in that lane would have stamped 450 into docs/PROPORTIONALITY.md as the live count.

Both decision functions here are pure and take their input as an argument, so the
must-fail case can be MADE to fail rather than reasoned about (the #3223 lesson: a
negative control that cannot fail is indistinguishable from one that passes).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
WORKFLOW = REPO / ".github" / "workflows" / "ci-cd.yml"

# The literal the verdict step must invoke, split so this file's own text cannot be
# mistaken for the step by a future grep-based check.
_CHECK_INVOCATION = ("deploy/sync_doc_metadata.py", "--check")


# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — the reconcile job's verdict step
# ══════════════════════════════════════════════════════════════════════════════


def verdict_step_defects(steps: list) -> list[str]:
    """Pure decision function over a job's `steps` list. Empty == contract met.

    Deliberately takes the parsed steps rather than reading the workflow itself, so the
    RULE is provable against a synthetic job that violates it — see the mutation proofs
    below. Three things are required, and each has cost this repo a red main:

      * the verdict runs `sync_doc_metadata.py --check` at all;
      * it exits non-zero on failure (a step that only PRINTS is the "gate that cannot
        fail" shape — a green check that states a problem is still a green check);
      * it runs AFTER the generators, because a `--check` before them measures the tree
        the job was handed, not the tree it leaves.
    """
    gen_idx = None
    verdict_idx = None
    verdict_run = ""
    for i, step in enumerate(steps):
        run = (step or {}).get("run") or ""
        if "sync_doc_metadata.py --apply" in run:
            gen_idx = i
        if all(tok in run for tok in _CHECK_INVOCATION) and "--apply" not in run:
            verdict_idx = i
            verdict_run = run

    defects: list[str] = []
    if verdict_idx is None:
        defects.append(
            "the reconcile job never runs `python3 deploy/sync_doc_metadata.py --check` on the tree it leaves — "
            "so it can report success while the very next job fails on that tree's literal drift (#3234)"
        )
        return defects
    if "exit 1" not in verdict_run:
        defects.append("the verdict step does not exit non-zero — a step that only prints a problem is a gate that cannot fail")
    if gen_idx is None:
        defects.append("no generator step found (`sync_doc_metadata.py --apply`) — the verdict has nothing to verify")
    elif verdict_idx < gen_idx:
        defects.append(f"the verdict step (index {verdict_idx}) runs BEFORE the generators (index {gen_idx}) — it measures the wrong tree")
    return defects


def _reconcile_steps() -> list:
    import yaml  # local: module-level `import yaml` in tests is itself flagged (#2699/#2732)

    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc["jobs"]["reconcile"]["steps"]


def test_the_live_reconcile_job_carries_the_verdict_step():
    defects = verdict_step_defects(_reconcile_steps())
    assert not defects, "\n".join(defects)


def test_the_rule_reds_when_the_verdict_step_is_absent():
    """The must-fail case, made to fail: today's real job with the verdict step deleted
    is exactly the job that redded main twice, and the rule must say so."""
    steps = [s for s in _reconcile_steps() if "--check" not in ((s or {}).get("run") or "")]
    defects = verdict_step_defects(steps)
    assert defects, "removing the verdict step must red this rule"
    assert "never runs" in defects[0]


def test_the_rule_reds_when_the_verdict_only_prints():
    ordered = [
        {"run": "python3 deploy/sync_doc_metadata.py --apply"},
        {"run": "python3 deploy/sync_doc_metadata.py --check || echo drifted"},
    ]
    defects = verdict_step_defects(ordered)
    assert any("exit non-zero" in d for d in defects)


def test_the_rule_reds_when_the_verdict_runs_before_the_generators():
    inverted = [
        {"run": "python3 deploy/sync_doc_metadata.py --check\nexit 1"},
        {"run": "python3 deploy/sync_doc_metadata.py --apply"},
    ]
    defects = verdict_step_defects(inverted)
    assert any("BEFORE the generators" in d for d in defects)


# ══════════════════════════════════════════════════════════════════════════════
# Part 2 — an incomplete census sweep is refused, not reported
# ══════════════════════════════════════════════════════════════════════════════


def _census_fact_module():
    sys.path.insert(0, str(REPO / "deploy"))
    import sync_census_fact

    return sync_census_fact


def test_a_complete_sweep_is_still_reported_normally():
    """The positive control. Without it, every assertion below could be passing because
    the function refuses everything."""
    fact = _census_fact_module()
    count, error = fact.discover_gate_census_count(REPO)
    assert error is None, error
    assert count and count > 100, count


def test_an_incomplete_sweep_is_refused_rather_than_reported(monkeypatch):
    """The mutation: `build_census()` returns 450 gates and admits one family did not
    run. Before this change the caller read 450 as a measurement."""
    fact = _census_fact_module()
    sys.path.insert(0, str(REPO / "scripts"))
    import gate_census

    partial = {
        "gates": [{"id": f"synthetic::{i}"} for i in range(450)],
        "families_skipped": [{"family": "structural", "reason": "tests/premerge_derivation.py not importable (ImportError: blocked)"}],
    }
    monkeypatch.setattr(gate_census, "build_census", lambda root: partial)
    count, error = fact.discover_gate_census_count(REPO)
    assert count is None, "a sweep missing a whole family must not be reported as a count"
    assert "incomplete sweep" in error
    assert "structural" in error and "450" in error


def test_the_same_stub_without_the_skip_is_reported(monkeypatch):
    """The other half of the mutation — proof the refusal keys on the SKIP and not on
    something incidental about the stub."""
    fact = _census_fact_module()
    sys.path.insert(0, str(REPO / "scripts"))
    import gate_census

    complete = {"gates": [{"id": f"synthetic::{i}"} for i in range(450)], "families_skipped": []}
    monkeypatch.setattr(gate_census, "build_census", lambda root: complete)
    count, error = fact.discover_gate_census_count(REPO)
    assert (count, error) == (450, None)


def test_a_really_blocked_structural_family_reports_its_skip(monkeypatch):
    """Not a stub — the real discoverer, with the real import really broken.

    `sys.modules[name] = None` is the technique that WORKS: an earlier attempt at this
    proof used a `sys.meta_path` finder with `find_module`, removed in Python 3.12, so
    the import succeeded and the control passed vacuously (#2578, Session F).
    """
    sys.path.insert(0, str(REPO / "scripts"))
    import gate_census
    import gate_census_structural

    def _run():
        return gate_census_structural.discover_structural_test_gates(
            REPO, gate_census.Gate, gate_census._read, gate_census._static_source_flags, lambda _m: None
        )

    healthy_gates, healthy_counters = _run()
    assert healthy_gates, "positive control: the structural family must find gates on a healthy tree"
    assert "skipped_reason" not in healthy_counters

    monkeypatch.setitem(sys.modules, "premerge_derivation", None)
    with pytest.raises(ImportError):
        import premerge_derivation  # noqa: F401  — the control: the block really blocks

    blocked_gates, blocked_counters = _run()
    assert blocked_gates == [], "a family that cannot run must contribute no gates"
    assert "not importable" in blocked_counters["skipped_reason"]


def test_the_blocked_family_travels_all_the_way_to_the_fact(monkeypatch):
    """End to end on the real census: block the import, and the doc-sync fact refuses.

    This is the measured 554 -> 450 defect. The assertion is deliberately on the REFUSAL
    and not on either number — the count moves with the inventory, the refusal must not.
    """
    fact = _census_fact_module()
    monkeypatch.setitem(sys.modules, "premerge_derivation", None)
    count, error = fact.discover_gate_census_count(REPO)
    assert count is None, "a census missing its structural family must not be handed to the doc-sync layer"
    assert "incomplete sweep" in error
    assert "structural" in error
