"""tests/test_restart_verify_gates_3477.py — the contract test for the ONE derivation.

The sweep exists because `restart_pipeline.py` ran ONE doc gate while Docs CI ran twelve.
Its whole value is that the list is DERIVED, so the next CI gate is covered the day it
lands. Two things must therefore be true forever, and neither is provable by running it
on a clean tree (which passes for free):

  1. the derivation actually reaches the live workflow and finds every gate in it;
  2. a derivation that comes back EMPTY raises instead of reporting a clean sweep —
     the absence-read-as-success class this file's subject is entirely about.

#3529/#3531/#3534 extend the same contract to the three places the derivation had not
reached, each of which had already cost a red main or a hand-remembered step:

  3. THE PYTEST LEG (#3529) — the sweep ran Docs CI's python gates and `node --test` and
     ZERO pytest, so every python test that reads `deploy/generated/**` shipped unchecked.
     The derived file set must be non-empty and must contain the three files that actually
     red-mained (test_plan_literal_reconciliation, test_prereg_hash_stamp,
     test_prereg_seal_1980).
  4. THE WRAP BATTERY (#3531) — `scripts/wrap_gates.py` hand-listed four of the twelve. Its
     argv set must now be a SUPERSET of the derived set, minus only the declared mutating
     gates.
  5. READ-ONLY BY EFFECT (#3534) — the old assertion grepped argv for `--apply`, which is a
     phrase test that `skill_lint.py --self-test` walks straight through. The proof here is
     a measurement: run the sweep and compare `git status --porcelain` byte-for-byte, with a
     negative control (a gate that DOES write) proving the measurement can fail.

Every derivation below carries a NEGATIVE CONTROL — a fixture workflow with a gate added,
or with the derivation's input removed — because a derivation guard that cannot fail is
precisely the class these three issues are about.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "deploy"))

import restart_verify_gates as rvg  # noqa: E402

_WORKFLOW = os.path.join(_REPO, ".github", "workflows", "docs-ci.yml")


def _workflow_python_gates() -> list[str]:
    """Independently re-derived here — a test that reuses the module's own parser would
    agree with it even when both are wrong."""
    out = []
    with open(_WORKFLOW, encoding="utf-8") as fh:
        for line in fh:
            m = re.match(r"^\s*run:\s*(python3\s+\S+.*?)\s*$", line.rstrip("\n"))
            if m:
                out.append(m.group(1))
    return out


def test_the_gate_list_is_derived_from_the_live_workflow():
    derived = [" ".join(c) for c in rvg.docs_ci_gate_commands()]
    expected = _workflow_python_gates()
    assert derived == expected, "the sweep's derived gate list disagrees with docs-ci.yml"
    assert len(derived) >= 10, f"only {len(derived)} gates derived — the parser has gone blind to the workflow"


def test_no_derived_gate_carries_apply_outside_the_declared_mutating_set():
    """A cheap FIRST line, explicitly not the proof.

    #3534: this assertion used to be the whole read-only claim, and it is a PHRASE test —
    `scripts/skill_lint.py --self-test` carries no `--apply` and edits a tracked file
    anyway, so the claim was false while the test was green. The proof is
    `test_the_sweep_is_read_only_by_effect` below, which measures. This stays only to catch
    the blatant case early.
    """
    for cmd in rvg.docs_ci_gate_commands():
        if " ".join(cmd[1:]) in rvg.MUTATING_GATES:
            continue
        assert "--apply" not in cmd, f"{' '.join(cmd)} mutates — the sweep is read-only by contract"


def test_every_declared_mutating_gate_is_actually_a_derived_gate():
    """A stale entry in MUTATING_GATES is an exemption covering nothing — and worse, it
    would silently exempt a future gate that happened to be spelled the same way."""
    derived = {" ".join(c[1:]) for c in rvg.docs_ci_gate_commands()}
    for label, reason in rvg.MUTATING_GATES.items():
        assert label in derived, f"MUTATING_GATES declares {label!r}, which docs-ci.yml no longer runs"
        assert len(reason) > 60, f"{label}: a declared exception needs a written reason, not a label"


def test_an_empty_derivation_raises_rather_than_reporting_a_clean_sweep(tmp_path, monkeypatch):
    """The dead-man. If the workflow shape changes and the parser matches nothing, the
    sweep must FAIL LOUDLY. Returning [] would print '0 gates, all passed' — a check that
    cannot fail, which is the exact defect #3477 filed against the pipeline."""
    empty = tmp_path / "docs-ci.yml"
    empty.write_text("jobs:\n  wiki-gates:\n    steps:\n      - uses: actions/checkout@v7\n", encoding="utf-8")
    monkeypatch.setattr(rvg, "WORKFLOW", empty)
    with pytest.raises(RuntimeError, match="ZERO gates"):
        rvg.docs_ci_gate_commands()


def test_a_missing_workflow_raises_rather_than_passing(tmp_path, monkeypatch):
    monkeypatch.setattr(rvg, "WORKFLOW", tmp_path / "does-not-exist.yml")
    with pytest.raises(RuntimeError, match="cannot read"):
        rvg.docs_ci_gate_commands()


def test_the_js_leg_runs_the_whole_suite_not_a_subset():
    """#3479: it ran ONE file, so the v4 site gate redded on a different JS test the sweep
    never executed. A sweep that runs a SUBSET of a gate can promise nothing about it."""
    assert rvg.JS_SUITE_CMD == ["node", "--test"], (
        f"the JS leg is {rvg.JS_SUITE_CMD!r} — it must be the v4 site gate's own bare "
        "`node --test`, which discovers the whole suite; naming individual files re-opens #3479"
    )


def test_the_pipeline_runs_the_sweep_last():
    """The wire: the sweep is worthless if the pipeline does not call it, and wrong if it
    runs before sync_doc_metadata has converged the literals it judges."""
    sys.path.insert(0, os.path.join(_REPO, "deploy"))
    import restart_pipeline as pipeline

    names = [n for n, _ in pipeline.build_sub_scripts(False, [], "2026-06-14", 4)]
    assert names[-1] == "restart_verify_gates"
    assert names.index("restart_verify_gates") > names.index("sync_doc_metadata")


# ══════════════════════════════════════════════════════════════════════════════════════
# #3534 — a `run: |` block gate cannot go dark
# ══════════════════════════════════════════════════════════════════════════════════════


def _yaml_steps() -> list[tuple[str, str]]:
    """[(step name, run body)] for every step in docs-ci.yml, parsed with PyYAML.

    Deliberately a DIFFERENT parser from the module's: a test that re-used the module's
    own line regex would agree with it about exactly the blocks the regex cannot see.
    """
    yaml = pytest.importorskip("yaml", reason="PyYAML is the second, independent parser this assertion needs")
    with open(_WORKFLOW, encoding="utf-8") as fh:
        doc = yaml.safe_load(fh)
    out = []
    for job in (doc.get("jobs") or {}).values():
        for step in job.get("steps") or []:
            if isinstance(step, dict) and "run" in step:
                out.append((str(step.get("name", "<unnamed step>")).strip(), str(step["run"])))
    return out


def test_every_python3_step_in_the_workflow_is_derived_or_declared():
    """#3534 box 3. A future `run: |` gate must not be able to go dark.

    The line parser in the module matches `run: python3 …` only. A block scalar invoking
    python3 is, to it, simply absent — the exact "derived silently as nothing" shape #3477
    was filed about. So every step whose run text invokes python3 must be EITHER in the
    derived single-line set OR named in MULTILINE_RUN_EXEMPT with a written reason.
    """
    derived = set(_workflow_python_gates())
    for name, run in _yaml_steps():
        if not re.search(r"(?<![\w./-])python3(?![\w-])", run):
            continue
        single = run.strip()
        if "\n" not in single and single in derived:
            continue
        assert name in rvg.MULTILINE_RUN_EXEMPT, (
            f"docs-ci.yml step {name!r} invokes python3 in a form the sweep does not derive.\n"
            "Give it a single-line `run: python3 …` form, or declare it in "
            "restart_verify_gates.MULTILINE_RUN_EXEMPT with a written reason."
        )
        assert len(rvg.MULTILINE_RUN_EXEMPT[name]) > 60, f"{name}: a declared non-gate needs a reason, not a label"


def test_multiline_exemptions_still_name_live_workflow_steps():
    """A renamed step would leave a stale exemption quietly covering a REAL gate."""
    live = {name for name, _ in _yaml_steps()}
    for name in rvg.MULTILINE_RUN_EXEMPT:
        assert name in live, f"MULTILINE_RUN_EXEMPT names {name!r}, which is not a step in docs-ci.yml any more"


def test_the_live_workflow_has_no_undeclared_multiline_python_step():
    assert rvg.undeclared_multiline_python_steps() == []


def test_an_undeclared_multiline_python_gate_makes_the_sweep_UNEVALUABLE(tmp_path, monkeypatch, capsys):
    """NEGATIVE CONTROL for the above. Plant a `run: |` gate and prove the sweep refuses.

    Without this, "no undeclared multiline steps" is indistinguishable from "the detector
    returns [] for everything" — a vacuous negative control is a passing one.
    """
    wf = tmp_path / "docs-ci.yml"
    wf.write_text(
        "jobs:\n"
        "  wiki-gates:\n"
        "    steps:\n"
        "      - name: A gate hiding in a block scalar\n"
        "        run: |\n"
        "          python3 scripts/check_doc_links.py\n"
        "      - name: A normal gate\n"
        "        run: python3 scripts/check_doc_links.py\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(rvg, "WORKFLOW", wf)
    assert [n for n, _ in rvg.undeclared_multiline_python_steps()] == ["A gate hiding in a block scalar"]
    monkeypatch.setattr(sys, "argv", ["restart_verify_gates.py"])
    assert rvg.main() == 2, "an underivable gate must be UNEVALUABLE (exit 2), never a pass"
    assert "UNEVALUABLE" in capsys.readouterr().out


# ══════════════════════════════════════════════════════════════════════════════════════
# #3477/#3531 — the derivation picks up a NEW gate the day it lands
# ══════════════════════════════════════════════════════════════════════════════════════


def test_a_gate_added_to_the_workflow_is_picked_up_without_editing_the_sweep():
    """NEGATIVE CONTROL for the whole derivation, on a scratch copy of the real workflow.

    The claim "a thirteenth gate joins with no edit here" is exactly the kind that is never
    tested and then turns out false. Add one; prove it appears.
    """
    import pathlib
    import tempfile

    live = pathlib.Path(_WORKFLOW).read_text(encoding="utf-8")
    before = len(rvg.docs_ci_gate_commands())
    with tempfile.TemporaryDirectory() as td:
        scratch = pathlib.Path(td) / "docs-ci.yml"
        scratch.write_text(
            live + "\n      - name: Thirteenth gate\n        if: always()\n        run: python3 scripts/nonexistent_new_gate.py --check\n"
        )
        original = rvg.WORKFLOW
        try:
            rvg.WORKFLOW = scratch
            after = rvg.docs_ci_gate_commands()
        finally:
            rvg.WORKFLOW = original
    assert len(after) == before + 1
    assert after[-1] == ["python3", "scripts/nonexistent_new_gate.py", "--check"]


# ══════════════════════════════════════════════════════════════════════════════════════
# #3529 — the pytest leg over the artifacts the reset regenerates
# ══════════════════════════════════════════════════════════════════════════════════════


def test_the_pytest_leg_is_derived_and_covers_the_files_that_red_mained():
    """The sweep ran ZERO pytest, so every reset shipped past the tests that read its own
    regenerated artifacts. 13 tests red on 2026-08-31, then 5 consecutive runs on
    2026-09-04. Those three files are the floor, not the definition — the SET is derived."""
    files = rvg.reset_artifact_test_files()
    assert files, "the pytest leg derived nothing — an empty leg reporting 0 passed is the #3477 defect"
    names = {os.path.basename(f) for f in files}
    for required in ("test_plan_literal_reconciliation.py", "test_prereg_hash_stamp.py", "test_prereg_seal_1980.py"):
        assert required in names, f"{required} reads the reset's own artifacts and red-mained; the derivation must reach it"


def test_the_pytest_leg_derivation_is_independently_reproducible():
    """Re-derived here with a different expression of the same rule — a test that called
    the module's own function would agree with it even when both are wrong."""
    import pathlib

    repo = pathlib.Path(_REPO)
    writers = [
        f"deploy/{p.name}"
        for p in sorted((repo / "deploy").glob("*.py"))
        if p.name != "restart_verify_gates.py"
        and ('"generated"' in p.read_text(errors="replace") or "deploy/generated" in p.read_text(errors="replace"))
    ]
    assert writers, "no deploy script writes deploy/generated/ — the writer derivation went blind"
    needles = ["deploy/generated/"] + writers
    expected = sorted(
        f"tests/{p.name}" for p in (repo / "tests").glob("test_*.py") if any(n in p.read_text(errors="replace") for n in needles)
    )
    assert rvg.reset_artifact_test_files() == expected


def test_an_empty_pytest_derivation_raises_rather_than_running_nothing(tmp_path):
    """The dead-man for the pytest leg: no writers found must RAISE, never return []."""
    (tmp_path / "deploy").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "deploy" / "unrelated.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="ZERO writers"):
        rvg.reset_artifact_writers(tmp_path)
    with pytest.raises(RuntimeError, match="ZERO writers"):
        rvg.reset_artifact_test_files(tmp_path)


def test_an_empty_pytest_derivation_raises_when_no_test_reads_the_artifacts(tmp_path):
    (tmp_path / "deploy").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "deploy" / "writer.py").write_text('P = ROOT / "generated" / "x.json"\n', encoding="utf-8")
    (tmp_path / "tests" / "test_unrelated.py").write_text("def test_x():\n    pass\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="ZERO tests"):
        rvg.reset_artifact_test_files(tmp_path)


def test_the_pytest_leg_runs_this_interpreter_not_a_bare_pytest():
    """A bare `pytest` on PATH is whatever venv happened to be active; the reset must test
    with the interpreter it is running under."""
    cmd = rvg.pytest_leg_command()
    assert cmd[:3] == [sys.executable, "-m", "pytest"]
    assert all(f.startswith("tests/") for f in cmd[3 : 3 + len(rvg.reset_artifact_test_files())])


def test_the_named_selection_is_declared_in_the_module_docstring():
    """The subset is allowed to be a subset — it is NOT allowed to read as full coverage.
    #3479's lesson in one assertion: say which N of M, and say what is not covered."""
    import inspect

    doc = rvg.__doc__ or ""
    assert "NAMED SELECTION" in doc, "the module docstring must say the pytest leg is a selection, not the suite"
    src = inspect.getsource(rvg)
    assert "IS NOT" in src and "IS  " in src, "the derivation must state, in words, what it covers AND what it does not"


# ══════════════════════════════════════════════════════════════════════════════════════
# #3534 — read-only by EFFECT, with a control that proves the measurement can fail
# ══════════════════════════════════════════════════════════════════════════════════════


def _porcelain() -> str:
    return subprocess.run(["git", "status", "--porcelain"], cwd=_REPO, capture_output=True, text=True).stdout


def test_the_sweep_is_read_only_by_effect(tmp_path, monkeypatch):
    """Run the sweep over a fixture workflow and assert `git status --porcelain` is
    byte-identical before and after. A fixture workflow (not the live twelve) keeps this
    a test of the SWEEP's effect rather than a 40-second re-run of every doc gate."""
    noop = tmp_path / "noop_gate.py"
    noop.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    wf = tmp_path / "docs-ci.yml"
    wf.write_text(f"jobs:\n  g:\n    steps:\n      - name: noop\n        run: python3 {noop}\n", encoding="utf-8")
    monkeypatch.setattr(rvg, "WORKFLOW", wf)
    monkeypatch.setattr(sys, "argv", ["restart_verify_gates.py", "--skip-js", "--skip-pytest"])
    before = _porcelain()
    assert rvg.main() == 0
    assert _porcelain() == before, "the sweep changed the working tree — it runs after the reset's writes and must not"


def test_a_gate_that_writes_is_CAUGHT_by_effect(tmp_path, monkeypatch, capsys):
    """NEGATIVE CONTROL. Without it, "porcelain unchanged" is indistinguishable from a
    measurement that never looks. Plant a gate that creates a file inside the repo and
    prove the sweep reds and names it."""
    witness = os.path.join(_REPO, ".rvg_readonly_control.tmp")
    writer = tmp_path / "writer_gate.py"
    writer.write_text(f"open({witness!r}, 'w').write('x')\n", encoding="utf-8")
    wf = tmp_path / "docs-ci.yml"
    wf.write_text(f"jobs:\n  g:\n    steps:\n      - name: writer\n        run: python3 {writer}\n", encoding="utf-8")
    monkeypatch.setattr(rvg, "WORKFLOW", wf)
    monkeypatch.setattr(sys, "argv", ["restart_verify_gates.py", "--skip-js", "--skip-pytest"])
    try:
        rc = rvg.main()
        out = capsys.readouterr().out
    finally:
        if os.path.exists(witness):
            os.unlink(witness)
    assert rc == 1, "a gate that mutated the tree must fail the sweep"
    assert "READ-ONLY VIOLATION" in out and "MUTATED the working tree" in out


def test_the_declared_mutating_gate_runs_last():
    """Ordering is the contract: everything that must observe an unmutated corpus runs
    before the one gate that plants a defect in it."""
    import inspect

    src = inspect.getsource(rvg.main)
    assert src.index("for cmd in readonly:") < src.index("for cmd in mutating:")


# ══════════════════════════════════════════════════════════════════════════════════════
# #3531 — the wrap battery is the same derived set
# ══════════════════════════════════════════════════════════════════════════════════════


def _wrap_gates_module():
    sys.path.insert(0, os.path.join(_REPO, "scripts"))
    import wrap_gates

    return wrap_gates


def test_wrap_battery_runs_every_docs_ci_gate():
    """#3531. It hand-listed FOUR of twelve, and ran check_doc_index WITHOUT `--strict`
    while Docs CI runs it WITH — so the wrap battery reported green over eight gates the
    very next push (docs/**, CLAUDE.md, .claude/** — Docs CI's own trigger) would fail on."""
    wg = _wrap_gates_module()
    battery = {" ".join(g.cmd) for g in wg.GATHER} | {" ".join(g.cmd) for g in wg.VERIFY}
    derived = {" ".join(c) for c in rvg.docs_ci_gate_commands()}
    expected = {c for c in derived if " ".join(c.split()[1:]) not in rvg.MUTATING_GATES}
    missing = expected - battery
    assert not missing, f"the wrap battery omits Docs CI gate(s) it will be judged by: {sorted(missing)}"


def test_the_wrap_batterys_only_omission_is_the_declared_mutating_set():
    """A subset is allowed. A SILENT subset is not — the omission must be exactly the set
    that carries a written reason, and nothing else."""
    wg = _wrap_gates_module()
    battery = {" ".join(g.cmd) for g in wg.GATHER} | {" ".join(g.cmd) for g in wg.VERIFY}
    omitted = {" ".join(c.split()[1:]) for c in {" ".join(x) for x in rvg.docs_ci_gate_commands()} - battery}
    assert omitted == set(rvg.MUTATING_GATES), f"undeclared omission(s) from the wrap battery: {sorted(omitted - set(rvg.MUTATING_GATES))}"


def test_the_wrap_battery_runs_doc_index_strict():
    """The fifth discrepancy #3531 found, and the cheapest to regress: bare vs `--strict`."""
    wg = _wrap_gates_module()
    (gate,) = [g for g in wg.GATHER if "check_doc_index.py" in " ".join(g.cmd)]
    assert "--strict" in gate.cmd, "Docs CI runs check_doc_index --strict; a bare local run is the 2026-07-27 incident"


def test_the_wrap_battery_does_not_hand_list_the_doc_gates():
    """The regression that matters is a helpful future edit re-typing the list. If the
    literal script paths reappear as constants in wrap_gates.py, the derivation is dead."""
    import pathlib

    src = pathlib.Path(_REPO, "scripts", "wrap_gates.py").read_text(encoding="utf-8")
    body = src.split("# \u2500\u2500 the gather battery", 1)[1]
    for hand_listed in ('"scripts/check_doc_links.py"', '"scripts/check_doc_tombstones.py"', '"scripts/check_doc_index.py"'):
        assert hand_listed not in body, f"{hand_listed} is hand-listed again in the wrap battery — derive it (#3531)"


def test_every_derived_artifact_reader_is_in_the_premerge_lane():
    """#3529 the other half: the reset is not the only way these artifacts get regenerated.

    A PR that lands a regenerated `deploy/generated/**` artifact must red on the PR, not on
    whoever pushes next — that is the same misattribution #2975 cost a session over. The
    hand-written names in conftest are not the source of truth; this derivation is, and
    this assertion is what stops the two drifting apart.
    """
    sys.path.insert(0, os.path.join(_REPO, "tests"))
    import conftest

    derived = {os.path.basename(f) for f in rvg.reset_artifact_test_files()}
    missing = derived - set(conftest._PREMERGE_EXTRA_FILES)
    assert not missing, (
        f"these read the reset's regenerated artifacts but run only AFTER a merge: {sorted(missing)}. "
        "Add them to _PREMERGE_EXTRA_FILES in tests/conftest.py."
    )


def test_the_wrap_skill_points_at_the_derivation_instead_of_restating_it():
    """#3531 box 3. `.claude/skills/wrap/SKILL.md` restated the same four-of-twelve list by
    hand, so fixing the script alone would have left the doc teaching the subset."""
    import pathlib

    skill = pathlib.Path(_REPO, ".claude", "skills", "wrap", "SKILL.md").read_text(encoding="utf-8")
    assert "docs_ci_gate_commands" in skill, "the wrap skill must name the derivation it relies on"
    hand_listed = sum(
        1
        for cmd in (
            "python3 scripts/check_doc_links.py",
            "python3 scripts/check_doc_tombstones.py",
            "python3 scripts/generate_adr_index.py --check",
        )
        if cmd in skill
    )
    assert hand_listed == 0, "the wrap skill is restating the doc-gate list again — point at the derivation (#3531)"


def test_a_declared_mutating_gate_that_DOES_NOT_RESTORE_is_caught(tmp_path, monkeypatch, capsys):
    """The other failure path of the MUTATING_GATES exemption, and the one that matters.

    `skill_lint.py --self-test` restores the file it plants a defect in, so on a good day the
    exemption suppresses nothing — which would make it a declaration with no teeth. The teeth
    are here: a declared mutating gate is contracted to put the tree back, and a run that
    does not is a reset about to commit a planted defect.
    """
    witness = os.path.join(_REPO, ".rvg_restore_control.tmp")
    gate = tmp_path / "leaky_gate.py"
    gate.write_text(f"open({witness!r}, 'w').write('x')\n", encoding="utf-8")
    wf = tmp_path / "docs-ci.yml"
    wf.write_text(f"jobs:\n  g:\n    steps:\n      - name: leaky\n        run: python3 {gate}\n", encoding="utf-8")
    monkeypatch.setattr(rvg, "WORKFLOW", wf)
    monkeypatch.setattr(rvg, "MUTATING_GATES", {str(gate): "fixture: declared mutating, deliberately does not restore"})
    monkeypatch.setattr(sys, "argv", ["restart_verify_gates.py", "--skip-js", "--skip-pytest"])
    try:
        rc = rvg.main()
        out = capsys.readouterr().out
    finally:
        if os.path.exists(witness):
            os.unlink(witness)
    assert rc == 1
    assert "DID NOT RESTORE THE TREE" in out


def test_main_ACTUALLY_INVOKES_the_pytest_and_js_legs(tmp_path, monkeypatch):
    """THE WIRE. A derived, well-tested file set that `main()` never executes is #3200's
    shape exactly: verdict-closed, sixty green tests, non-functional. Capture what the
    sweep really runs.
    """
    noop = tmp_path / "noop_gate.py"
    noop.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
    wf = tmp_path / "docs-ci.yml"
    wf.write_text(f"jobs:\n  g:\n    steps:\n      - name: noop\n        run: python3 {noop}\n", encoding="utf-8")
    monkeypatch.setattr(rvg, "WORKFLOW", wf)
    seen: list[list[str]] = []

    def fake_run(cmd):
        seen.append(list(cmd))
        return 0, ""

    monkeypatch.setattr(rvg, "_run", fake_run)
    monkeypatch.setattr(rvg, "JS_SUITE_CMD", ["node", "--test"])
    monkeypatch.setattr(sys, "argv", ["restart_verify_gates.py"])
    assert rvg.main() == 0

    pytest_legs = [c for c in seen if c[:3] == [sys.executable, "-m", "pytest"]]
    assert len(pytest_legs) == 1, f"the sweep did not run the derived pytest leg — it ran {seen}"
    assert set(rvg.reset_artifact_test_files()) <= set(pytest_legs[0])
    assert ["node", "--test"] in seen, "the sweep did not run the v4 site gate's JS suite"
