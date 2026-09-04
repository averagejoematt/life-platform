"""tests/test_restart_verify_gates_3477.py — #3477's contract test.

The sweep exists because `restart_pipeline.py` ran ONE doc gate while Docs CI ran twelve.
Its whole value is that the list is DERIVED, so the next CI gate is covered the day it
lands. Two things must therefore be true forever, and neither is provable by running it
on a clean tree (which passes for free):

  1. the derivation actually reaches the live workflow and finds every gate in it;
  2. a derivation that comes back EMPTY raises instead of reporting a clean sweep —
     the absence-read-as-success class this file's subject is entirely about.
"""

from __future__ import annotations

import os
import re
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


def test_every_derived_gate_is_a_read_only_check_form():
    """The sweep runs inside a reset, after the writes. It must never mutate: a gate that
    took `--apply` here would make the sweep a second writer with no ordering contract."""
    for cmd in rvg.docs_ci_gate_commands():
        assert "--apply" not in cmd, f"{' '.join(cmd)} mutates — the sweep is read-only by contract"


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


def test_the_genesis_fixture_check_names_a_file_that_exists():
    """The reset breaks these every cycle; a stale path here would silently stop checking."""
    assert rvg.GENESIS_FIXTURE_TESTS, "the genesis-fixture list is empty — the reset's own breakage is unwatched"
    for rel in rvg.GENESIS_FIXTURE_TESTS:
        assert os.path.isfile(os.path.join(_REPO, rel)), f"{rel} does not exist — re-point the sweep"


def test_the_pipeline_runs_the_sweep_last():
    """The wire: the sweep is worthless if the pipeline does not call it, and wrong if it
    runs before sync_doc_metadata has converged the literals it judges."""
    sys.path.insert(0, os.path.join(_REPO, "deploy"))
    import restart_pipeline as pipeline

    names = [n for n, _ in pipeline.build_sub_scripts(False, [], "2026-06-14", 4)]
    assert names[-1] == "restart_verify_gates"
    assert names.index("restart_verify_gates") > names.index("sync_doc_metadata")
