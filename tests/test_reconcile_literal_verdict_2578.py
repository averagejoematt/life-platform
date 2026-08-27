"""tests/test_reconcile_literal_verdict_2578.py — #2578: an instrument must not report
success while leaving its job undone.

TWO INSTANCES OF ONE CLASS, both found and fixed together.

1. THE RECONCILE JOB (the #3234 class, unfixed). #3234 fixed the INSTANCE: `ci-cd.yml`'s
   reconcile job could not `import yaml`, so the gate-census fact was skipped honestly,
   the generators left the tree byte-identical, the job printed "already match config
   truth" and went green — and `test / Unit Tests` in the same run failed on the drift
   the job had declined to fix. Main went red twice on 2026-08-27 with a green reconcile
   job above it. Installing PyYAML fixed that fact; it gave the job no way to notice the
   next one.

   THE FIRST FIX FOR THIS WAS WRONG AND THE GUARD THAT CAUGHT IT WAS RIGHT. The obvious
   step — run `sync_doc_metadata --check` in the reconcile job — is a DOC GATE inside the
   deploy pipeline, which is #1908's one-way trap: it fails on a code push, its
   remediation is by definition a docs edit, `docs/**` is not in ci-cd.yml's `paths:`
   filter, so the fix cannot re-run the workflow it fixed, and clearing it costs a manual
   dispatch through Plan -> Deploy. Three occurrences in three days (#1900/#1906/#1914),
   and once more at this session's boot. `tests/test_docs_ci_owns_doc_gates.py` failed on
   the first draft of this file's subject, correctly.

   What landed instead is a SELF-CHECK: `deploy/verify_doc_facts_derivable.py` asks not
   "does the committed tree match derived truth?" (docs) but "could this job derive the
   facts it owns at all?" (environment). Its only gating failures are a missing dependency
   and an incomplete census sweep, both fixed by a code edit inside this workflow's paths
   filter — so the trap cannot form. The drift verdict stays in `docs-ci.yml`, which
   already runs it as a blocking gate and already triggers on both halves of the coupling.

   Note what is NOT being changed: an underivable fact outside `--check` SHOULD skip with
   a printed reason. That is #3156's behaviour and it is correct. The defect is the JOB
   concluding success while unable to derive what it was there to reconcile.

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

_SELFCHECK_SCRIPT = "deploy/verify_doc_facts_derivable.py"

# Split so this file's own text is not itself an occurrence of the doc gate that
# tests/test_docs_ci_owns_doc_gates.py forbids inside the deploy pipeline.
_DOC_GATE_INVOCATION = ("deploy/sync_doc_metadata.py", " --check")


# ══════════════════════════════════════════════════════════════════════════════
# Part 1 — the reconcile job's self-check (and it must NOT be a doc gate)
# ══════════════════════════════════════════════════════════════════════════════


def selfcheck_defects(steps: list) -> list[str]:
    """Pure decision function over a job's `steps` list. Empty == contract met.

    Takes the parsed steps rather than reading the workflow itself, so the RULE is
    provable against a synthetic job that violates it. Three requirements, and the third
    is the one that cost a design round:

      * the self-check runs at all;
      * it runs AFTER the generators — a check before them describes the tree the job was
        handed, not the tree it leaves;
      * it is NOT `sync_doc_metadata --check`. That is a doc gate, and a doc gate in the
        deploy pipeline is #1908's one-way trap: it fails on a code push, its remediation
        is a docs edit, and `docs/**` cannot re-trigger this workflow. The first draft of
        this step WAS that gate; `tests/test_docs_ci_owns_doc_gates.py` caught it. This
        assertion is here so the same mistake cannot be re-made in this job under a
        different name — and it is deliberately duplicated with that guard, because the
        two say different things: that one guards the whole pipeline, this one records
        why THIS step is shaped the way it is.
    """
    gen_idx = None
    check_idx = None
    for i, step in enumerate(steps):
        run = (step or {}).get("run") or ""
        if "sync_doc_metadata.py --apply" in run:
            gen_idx = i
        if _SELFCHECK_SCRIPT in run:
            check_idx = i

    defects: list[str] = []
    for i, step in enumerate(steps):
        run = (step or {}).get("run") or ""
        if "".join(_DOC_GATE_INVOCATION) in run:
            defects.append(
                f"step {i} runs the doc gate `{''.join(_DOC_GATE_INVOCATION)}` inside the deploy pipeline — "
                "#1908: its remediation is a docs edit and docs/** cannot re-trigger this workflow. "
                "docs-ci.yml is the gates' single home."
            )
    if check_idx is None:
        defects.append(
            f"the reconcile job never runs `{_SELFCHECK_SCRIPT}` — so it can report success while it was "
            "unable to derive a fact it owns, which is exactly #3234 (main red twice, 2026-08-27)"
        )
        return defects
    if gen_idx is None:
        defects.append("no generator step found (`sync_doc_metadata.py --apply`) — the self-check has nothing to verify")
    elif check_idx < gen_idx:
        defects.append(f"the self-check (index {check_idx}) runs BEFORE the generators (index {gen_idx})")
    return defects


def _reconcile_steps() -> list:
    import yaml  # local: module-level `import yaml` in tests is itself flagged (#2699/#2732)

    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return doc["jobs"]["reconcile"]["steps"]


def test_the_live_reconcile_job_carries_the_self_check():
    defects = selfcheck_defects(_reconcile_steps())
    assert not defects, "\n".join(defects)


def test_the_rule_reds_when_the_self_check_is_absent():
    """The must-fail case, made to fail: today's real job with the self-check deleted is
    exactly the job that redded main twice, and the rule must say so."""
    steps = [s for s in _reconcile_steps() if _SELFCHECK_SCRIPT not in ((s or {}).get("run") or "")]
    defects = selfcheck_defects(steps)
    assert defects, "removing the self-check must red this rule"
    assert "never runs" in defects[0]


def test_the_rule_reds_when_the_self_check_runs_before_the_generators():
    inverted = [
        {"run": f"python3 {_SELFCHECK_SCRIPT}"},
        {"run": "python3 deploy/sync_doc_metadata.py --apply"},
    ]
    defects = selfcheck_defects(inverted)
    assert any("BEFORE the generators" in d for d in defects)


def test_the_rule_reds_on_the_doc_gate_this_step_must_never_become():
    """The #1908 regression, pinned at the step that tried to be it."""
    trap = [
        {"run": "python3 deploy/sync_doc_metadata.py --apply"},
        {"run": f"python3 {_SELFCHECK_SCRIPT}"},
        {"run": "python3 " + "".join(_DOC_GATE_INVOCATION)},
    ]
    defects = selfcheck_defects(trap)
    assert any("#1908" in d for d in defects)


def test_the_self_check_script_reads_no_committed_doc_content():
    """The load-bearing property that makes this a self-check and not a relocated doc
    gate: it must not compare against docs. If it ever grows a `--check`/RULES/doc-path
    comparison it has become the trap again, whatever it is called."""
    text = (REPO / _SELFCHECK_SCRIPT).read_text(encoding="utf-8")
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    body = body.split('"""')[0] + '"""'.join(body.split('"""')[2:])  # drop the module docstring
    for forbidden in ("RULES", "--check", "PLATFORM_FACTS["):
        assert forbidden not in body, f"{_SELFCHECK_SCRIPT} must not compare committed doc content — found {forbidden!r}"


# ══════════════════════════════════════════════════════════════════════════════
# Part 1b — the verdict rule, mutation-proven on synthetic reports
# ══════════════════════════════════════════════════════════════════════════════


def _verify_module():
    sys.path.insert(0, str(REPO / "deploy"))
    import verify_doc_facts_derivable

    return verify_doc_facts_derivable


def test_a_clean_report_passes():
    v = _verify_module()
    ok, msg = v.verdict({"dependency_failures": [], "families_skipped": [], "fallbacks": [], "derived": [{"fact": "x", "value": "1"}]})
    assert ok, msg


def test_a_missing_dependency_reds_the_job():
    """#3234 in one assertion: the census fact could not be derived because PyYAML was
    absent, and the job went green anyway."""
    v = _verify_module()
    ok, msg = v.verdict(
        {
            "dependency_failures": [{"fact": "gate_census_count", "error": "ModuleNotFoundError: No module named 'yaml'"}],
            "families_skipped": [],
            "derived": [],
        }
    )
    assert not ok
    assert "MISSING DEPENDENCY" in msg and "gate_census_count" in msg


def test_an_incomplete_sweep_reds_the_job():
    v = _verify_module()
    ok, msg = v.verdict(
        {"dependency_failures": [], "families_skipped": [{"family": "structural", "reason": "not importable"}], "derived": []}
    )
    assert not ok
    assert "INCOMPLETE SWEEP" in msg


def test_a_silent_fallback_is_reported_and_does_NOT_red_the_job():
    """The deliberate non-gate. `_count_adrs` reads docs/DECISIONS.md, so gating on a
    plain None would let a docs edit red the deploy pipeline — #1908's trap rebuilt by
    hand. Reported, never gating; the residual is named in the script's docstring."""
    v = _verify_module()
    ok, _ = v.verdict(
        {"dependency_failures": [], "families_skipped": [], "fallbacks": [{"fact": "_count_adrs", "why": "returned None"}], "derived": []}
    )
    assert ok, "a silent fallback must not gate — its cause can be a docs edit"


def test_the_probe_set_is_derived_and_covers_the_extracted_discoverer():
    """The probe set must be found by introspection, not typed. The regression it pins is
    real and was measured while writing this: an earlier `fn.__module__ == mod.__name__`
    filter silently dropped `_auto_discover_alarm_count`, which lives in
    deploy/alarm_discovery.py — a probe set with a hole in it."""
    v = _verify_module()
    sys.path.insert(0, str(REPO / "deploy"))
    import sync_doc_metadata

    names = {n for n, _ in v._probe_functions(sync_doc_metadata)}
    assert "_auto_discover_alarm_count" in names, "the re-exported alarm discoverer must be probed"
    assert "_auto_discover_tool_count" in names
    assert len(names) >= 15, names
    assert "_ast_literal_str_list_len" not in names, "helpers taking arguments are not discoverers"


def test_the_live_environment_derives_every_fact():
    """The real probe against this checkout — the positive control for everything above."""
    v = _verify_module()
    report = v.probe_all(REPO)
    ok, msg = v.verdict(report)
    assert ok, msg


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
