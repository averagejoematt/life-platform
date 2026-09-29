"""tests/test_premerge_lane.py — ADR-139's regression guard (#1344).

The pre-merge lane lives in git precisely because GitHub settings evaporate on
visibility flips (#1319). This guard pins the lane's existence and its three
checks so it can't silently vanish; the OTHER half of the posture is
GET-verified weekly by deploy/drift_sentinel.py against
deploy/github_posture.json.

As of #1662 / ADR-148 this lane is no longer advisory — its `fast-lane` job is
one of the two REQUIRED status checks on `main`. The additional invariants that
required-ness imposes (unfiltered trigger, no job-level `if:`, job `name:` ==
the required context string) are guarded by
tests/test_branch_protection_spec.py, which reads the real YAML; this file
stays deliberately stdlib-only.

Deliberately stdlib-only (string asserts, no yaml dep) — the guard for the
collection-error killer must never itself be a collection error.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "pr-checks.yml"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_premerge_lane_exists_and_triggers_on_pull_request():
    assert WORKFLOW.is_file(), "ADR-139: .github/workflows/pr-checks.yml is gone"
    text = _text()
    assert "pull_request:" in text, "ADR-139: the lane must trigger on pull_request"
    assert "branches: [main]" in text


def test_premerge_lane_carries_the_three_checks():
    text = _text()
    assert "--collect-only" in text, "ADR-139: the collection gate (the #1297 class) is gone"
    # #2258 widened this: the lane now selects the `premerge` marker, which
    # tests/conftest.py auto-applies to everything `deploy_critical` PLUS the whole
    # behaviour suite. ADR-117's subset is still covered — it is a superset, not a swap.
    assert "premerge and not integration" in text, "ADR-139/#2258: the pre-merge test lane is gone"
    assert "black --check" in text, "ADR-139: the format gate is gone"


def test_premerge_lane_is_read_only():
    assert "contents: read" in _text(), "ADR-139: the lane must stay read-only (no write permissions)"


# ══════════════════════════════════════════════════════════════════════════════
# #2258 — the two lanes must not drift apart again
# ══════════════════════════════════════════════════════════════════════════════
# The three checks above pin that the lane EXISTS and carries literal strings. They
# could not detect the actual defect: the lane existed, ran, and reported green while
# checking a strict SUBSET of what main checks. These assert the property that
# matters instead — one marker definition, referenced by both workflows, and equal
# dependency installs.

CI_TEST = ROOT / ".github" / "workflows" / "ci-test.yml"
CONFTEST = ROOT / "tests" / "conftest.py"
PYTEST_INI = ROOT / "pytest.ini"

_MARKER = "premerge"


def test_the_premerge_marker_is_registered_and_auto_applied():
    """The marker must exist in pytest.ini AND be applied by a derivation hook.
    A hand-applied marker would rot on the 35th behaviour file."""
    assert f"{_MARKER}:" in PYTEST_INI.read_text(encoding="utf-8"), "#2258: the `premerge` marker is no longer registered in pytest.ini"
    conftest = CONFTEST.read_text(encoding="utf-8")
    assert "pytest_collection_modifyitems" in conftest, "#2258: the auto-marking hook is gone — the marker would have to be hand-written"
    assert "_behavior.py" in conftest, "#2258: the hook no longer keys on the behaviour-suite filename"


_SELECTION = f"{_MARKER} and not integration"


def _fast_lane_pytest_selections():
    """(marker expression, command) for every marker-selecting pytest command in the
    `fast-lane` job — the collection gate carries no `-m` and is not one of them."""
    import re

    text = _text()
    block = text[text.index("  fast-lane:") : text.index("  full-suite:")]
    out = []
    for cmd in re.findall(r"(python3 -m pytest (?:tests/|\$SERIAL_FILES)[^\n]*)", block):
        m = re.search(r'-m "([^"]+)"', cmd.replace("python3 -m pytest", "", 1))
        if m:
            out.append((m.group(1), cmd))
    return out


def test_the_premerge_lane_runs_the_marker_not_a_hand_listed_subset():
    """#2258's property, rewritten for #4251's two-pass lane: every pass selects on the
    ONE marker expression (plus only the `serial` split), never a hand-listed subset."""
    sels = _fast_lane_pytest_selections()
    assert sels, "#2258: pr-checks.yml's fast lane no longer runs a marker-selected pytest"
    for expr, cmd in sels:
        assert expr.startswith(_SELECTION), (
            "#2258: pr-checks.yml no longer selects the `premerge` marker. The pre-merge "
            "lane must not go back to being a strict subset of the post-merge one — that "
            f"gap red-mained main three times in 24h on 2026-08-08. Got: {cmd}"
        )


def test_the_fast_lane_partitions_its_selection_into_a_parallel_and_a_serial_pass():
    """#4251: the lane ran ~12.3k tests in one process and was slower than the 30k-test
    parallel full suite on the same PR. It now runs the SAME selection as two passes —
    the full-suite job's idiom (#3025). Two silent failure modes look identical from
    outside, both green: a test in NEITHER pass stops running; a test in BOTH runs twice
    (and an in-tree writer races its own twin). The guarantee is structural — the two
    expressions are exact complements over `serial` on one shared selection — so it
    cannot drift with the suite's size."""
    sels = _fast_lane_pytest_selections()
    assert len(sels) == 2, f"expected a parallel pass and a serial pass in the fast lane, found {len(sels)}: {sels}"
    (par_expr, par), (ser_expr, ser) = sels
    assert par_expr == f"{_SELECTION} and not serial", f"the parallel pass must select `{_SELECTION} and not serial`: {par}"
    assert ser_expr == f"{_SELECTION} and serial", f"the serial pass must select the exact complement `{_SELECTION} and serial`: {ser}"
    assert "-n auto --dist loadfile" in par, f"the parallel pass lost the full suite's xdist flags: {par}"
    assert "-n " not in ser, f"the serial pass must be single-process — that is the whole point: {ser}"
    # Same pin as the full-suite job: the lane that passes -n must install xdist.
    text = _text()
    block = text[text.index("  fast-lane:") : text.index("  full-suite:")]
    assert "pytest-xdist" in block, "the fast lane passes -n auto but does not install pytest-xdist"
    # Both passes land in the capture the deselection report reads, and a red first pass
    # must not skip the second (#749) nor be swallowed (#2746).
    assert "| tee /tmp/premerge_lane_output.txt || status=$?" in par
    assert "| tee -a /tmp/premerge_lane_output.txt || status=$?" in ser
    assert "exit $status" in block, "the two-pass step no longer exits with its passes' status"


def test_the_serial_pass_file_set_is_exactly_the_marked_files():
    """#4251: the serial pass collects `grep -l 'mark\\.serial' tests/test_*.py`, not the
    whole tree (a whole-tree collection is ~160s on the runner for 46 tests). That covers every serial test
    only while `serial` reaches a test ONLY through the literal marker in its own file. If
    tests/conftest.py ever applied it by hook, those tests would be deselected by the
    parallel pass and never collected by the serial one — in neither pass, both green."""
    import re

    conftest = CONFTEST.read_text(encoding="utf-8")
    assert not re.search(r"""mark\.serial|add_marker\(\s*["']serial""", conftest), (
        "tests/conftest.py now applies the `serial` marker — the fast lane's serial pass "
        "greps test files for the literal marker and would miss those tests"
    )
    block = _text()[_text().index("  fast-lane:") : _text().index("  full-suite:")]
    assert "SERIAL_FILES=$(grep -l 'mark\\.serial' tests/test_*.py" in block
    marked = sorted(p.name for p in (ROOT / "tests").glob("*.py") if "mark.serial" in p.read_text(encoding="utf-8"))
    assert marked, "no test file carries the serial marker — the serial pass would silently select nothing"
    outside_glob = [n for n in marked if not n.startswith("test_")]
    assert not outside_glob, f"serial-marked file(s) outside the lane's tests/test_*.py glob: {outside_glob}"


def test_both_lanes_reference_the_same_marker_definition():
    """ci-test.yml must name the marker too, so a rename cannot silently update one
    workflow and leave the other selecting nothing."""
    assert _MARKER in CI_TEST.read_text(encoding="utf-8"), (
        "#2258: ci-test.yml no longer mentions the `premerge` marker. Both lanes must "
        "reference the same definition so they cannot drift."
    )


def test_the_two_lanes_install_the_same_dependencies():
    """A dep the post-merge lane installs and the pre-merge lane does not is invisible
    to `--collect-only` when it is imported INSIDE a function — exactly how the PyYAML
    miss reached main on 2026-08-08."""

    def _pins(text):
        """The package NAMES a lane installs.

        #2609 removed the literal `tool==version` from both lanes — the versions now
        come from requirements-dev.txt via scripts/ci_pins.py, so the workflow line is
        a list of bare names. This parses that list; the property being guarded (equal
        dependency SETS across the two lanes) is name-level and unchanged.
        """
        for line in text.splitlines():
            if "ci_pins.py" in line and "pytest" in line:
                body = line.split("ci_pins.py", 1)[1].split(")", 1)[0]
                return {p.split("==")[0].strip() for p in body.split() if p.strip() and not p.startswith("-")}
        raise AssertionError("no `ci_pins.py …pytest…` install step found (#2609: the lanes resolve pins from requirements-dev.txt)")

    pre = _pins(_text())
    post = _pins(CI_TEST.read_text(encoding="utf-8"))
    # pytest-cov is legitimately post-merge-only (the coverage gate); black is
    # legitimately pre-merge-only (the format gate runs there).
    missing = post - pre - {"pytest-cov"}
    assert not missing, (
        f"#2258: ci-test.yml installs {sorted(missing)} but pr-checks.yml does not. "
        "A dep imported inside a function is invisible pre-merge and reds main on landing."
    )


def test_the_post_merge_lane_does_not_run_the_whole_suite_twice():
    """#2259: the standalone full-suite step ran the coverage gate's exact selection a
    second time (493s + 705s against a 1200s budget)."""
    text = CI_TEST.read_text(encoding="utf-8")
    assert "name: Full test suite" not in text, "#2259: the duplicated full-suite step is back — the suite would run twice again"


# ══════════════════════════════════════════════════════════════════════════════
# 2026-08-09 — the OTHER half of the pre-merge gap: the structural gates
# ══════════════════════════════════════════════════════════════════════════════
# #2258 moved the behaviour suite left. What stayed post-merge-only was every gate
# whose verdict is a pure function of the repo tree: the two size ceilings, the two
# registries a new module has to join, the mypy clean set, and ruff. Main went red
# four times on 2026-08-08 on exactly those, each red knowable from the PR's own diff.

CI_LINT = ROOT / ".github" / "workflows" / "ci-lint.yml"


def test_the_structural_gates_run_pre_merge():
    """Every gate whose failure depends only on the repo tree must be in the lane.

    Derived, not asserted against a copy of the list: this reads the real set out of
    tests/conftest.py's `_PREMERGE_EXTRA_FILES` and checks each file exists, so a
    rename or deletion fails here instead of silently shrinking the lane.
    """
    import tests.conftest as conftest  # noqa: PLC0415 — imported here to keep this module stdlib-only at import time

    extra = conftest._PREMERGE_EXTRA_FILES
    assert extra, "the structural-gate source is empty — the size ceilings and registry guards are post-merge-only again"
    missing = sorted(n for n in extra if not (ROOT / "tests" / n).is_file())
    assert not missing, (
        f"_PREMERGE_EXTRA_FILES names test file(s) that do not exist: {missing}. "
        "A renamed guard silently leaves the pre-merge lane — repoint the entry."
    )
    # UP-ONLY, the same ratchet shape as mypy_clean_set.py's DIRTY denylist. Existence
    # alone would not catch the real regression: quietly DROPPING an entry puts that gate
    # back to post-merge-only with every test still green. Removing a name here is only
    # correct when the guard itself is gone (and then the existence check above covers it).
    floor = {
        "test_lambda_size_gate.py",
        "test_module_size_guard.py",
        "test_phase_context_coverage.py",
        "test_grounding_wiring_1967.py",
        "test_mypy_clean_modules.py",
        # +18 on 2026-08-09 after test_time_invariant_helpers_1964 red-mained main hours
        # after the first five landed. Deriving the real population (tree-sweeping,
        # non-behaviour test files) found 20; these are the repo-shape ratchets among them.
        "test_handler_type_hints.py",
        "test_api_schema_completeness.py",
        "test_og_card_coverage.py",
        "test_hae_datatype_liveness_468.py",
        "test_restart_pipeline_hooks.py",
        "test_time_invariant_helpers_1964.py",
        "test_raw_key_registry_guard.py",
        "test_no_hardcoded_feature_tier.py",
        "test_budget_guard_ladder.py",
        "test_lambdas_packaging_guard.py",
        "test_root_clutter_guard.py",
        "test_no_conflict_markers.py",
        "test_no_dead_intelligence_functions.py",
        "test_hevy_compiler_isolation.py",
        "test_public_surface_pii_guard.py",
        "test_leak_token_sweep.py",
        "test_csp_native_embeds_1678.py",
        "test_archive_handover.py",
    }
    dropped = sorted(n for n in floor if n not in extra and (ROOT / "tests" / n).is_file())
    assert not dropped, (
        f"_PREMERGE_EXTRA_FILES dropped {dropped} while the file still exists. That gate is "
        "post-merge-only again — which is how main went red four times on 2026-08-08."
    )
    # The lane must still select them via the ONE marker, not a second hand-list in YAML.
    assert (
        'pytest tests/ -m "premerge' in _text()
    ), "the lane no longer selects the whole tests/ tree by marker — the extra files would not be picked up"


def test_the_mypy_gate_runs_pre_merge_with_the_same_command():
    """ci-lint.yml's Mypy gate is ENFORCED and was invisible on a PR. Both lanes must run
    the identical command against the identical authoritative module list, so a change to
    tests/mypy_clean_set.py cannot move one lane and leave the other behind."""
    pre, lint = _text(), CI_LINT.read_text(encoding="utf-8")
    command = "mypy --config-file mypy.ini $(python3 tests/mypy_clean_set.py)"
    assert (
        command in pre
    ), f"pr-checks.yml no longer runs the tier-2 mypy gate (`{command}`) — a var-annotated error red-mained main twice on 2026-08-08"
    assert (
        "tests/mypy_clean_set.py" in lint
    ), "ci-lint.yml no longer reads the authoritative clean set — the two lanes would be checking different module sets"


def test_the_lane_installs_mypy_so_its_own_gate_cannot_be_vacuous():
    """tests/test_mypy_clean_modules.py carries `skipif(not _mypy_available())`. In a lane
    without mypy installed that test reports green while checking nothing — the exact
    shape of the coverage gate that could never fail (#2259)."""
    # #2609: the lane resolves versions from requirements-dev.txt, so the tell is the
    # package NAME in the ci_pins.py call, not a literal `mypy==`. The property is
    # identical — mypy must be installed in this lane or its gate is a silent skip.
    text = _text()
    installed = {n for line in text.splitlines() if "ci_pins.py" in line for n in line.split("ci_pins.py", 1)[1].split(")", 1)[0].split()}
    assert "mypy" in installed, "pr-checks.yml stopped installing mypy — test_mypy_clean_modules.py silently degrades to a skip"


def test_the_ruff_gate_runs_pre_merge():
    """Same class as mypy: ENFORCED post-merge, invisible on a PR. The six-directory set
    is load-bearing — running a subset is how a ruff red reaches main."""
    dirs = "lambdas/ mcp/ cdk/ tests/ scripts/ deploy/"
    assert f"ruff check {dirs}" in _text(), "pr-checks.yml no longer runs the ruff gate over the full six-directory set"


def test_the_lane_gates_report_independently():
    """#749: sequential gates mean the first red masks the rest — one push per layer for
    an agent. Every check step carries `if: always()` so all violations surface at once."""
    text = _text()
    body = text[text.index("jobs:") :]
    steps = [s for s in body.split("      - name: ")[1:]]
    checks = [s for s in steps if not s.split("\n")[0].lower().startswith("install")]
    masked = [s.split("\n")[0] for s in checks if "if: always()" not in s]
    assert not masked, f"pre-merge gate step(s) without `if: always()` will be masked by an earlier red: {masked}"


def test_the_coverage_gate_can_actually_fail_the_build():
    """#2259: `pytest … | tail -100` under GitHub's default `bash -e {0}` exits with
    tail's status, so --cov-fail-under and every test failure were discarded. The gate
    reported green for its entire existence. `set -o pipefail` is what makes it real."""
    text = CI_TEST.read_text(encoding="utf-8")
    idx = text.index("Test coverage gate")
    # The step carries a long rationale comment before its `run:`; anchor on the
    # run block itself rather than guessing a character window.
    block = text[text.index("run: |", idx) :][:1600]
    assert "| tail" in block, "coverage step no longer pipes — if the pipe is gone this guard can be removed"
    assert "set -o pipefail" in block, (
        "#2259: the coverage gate pipes pytest into `tail` without `set -o pipefail`, so "
        "its exit code is tail's (always 0). --cov-fail-under=74 and any test failure "
        "are silently swallowed and the step reports success unconditionally."
    )


# ══════════════════════════════════════════════════════════════════════════════
# #4252 — a push to main re-runs black/ruff/mypy only when no required PR check did
# ══════════════════════════════════════════════════════════════════════════════
DEPENDABOT_AUTOMERGE = ROOT / ".github" / "workflows" / "dependabot-automerge.yml"


def _ci_lint_step(name_prefix):
    text = CI_LINT.read_text(encoding="utf-8")
    start = text.index(f"      - name: {name_prefix}")
    nxt = text.find("\n      - ", start + 10)
    return text[start : nxt if nxt != -1 else len(text)]


def test_ci_lint_skips_the_pr_proven_gates_only_on_a_single_squash_merge():
    """The three gates pr-checks.yml's required lane already ran carry the skip condition;
    the decision lives in the install step (no new step: the census ids are positional)
    and requires every clause of the squash-merge shape. A clause dropped from the
    decision would let a reconcile / reset / multi-commit push skip them."""
    decide = _ci_lint_step("Install black + ruff")
    assert "id: proven" in decide
    for clause in (
        '"$EVENT_NAME" = "push"',
        '"$BUILD_SHA" != "$PUSHED_SHA"',
        '"$PARENTS" != "2"',
        '"$PARENT" != "$BEFORE_SHA"',
        '"$COMMITTER" != "noreply@github.com"',
        '[[ "$SUBJECT" =~ \\(#[0-9]+\\)$ ]]',
        'echo "pr_proven=$PROVEN" >> "$GITHUB_OUTPUT"',
    ):
        assert clause in decide, f"#4252: the PR-proven decision lost a clause: {clause}"
    assert decide.index("PROVEN=false") < decide.index("PROVEN=true"), "the decision must default to running the gates"
    for gate in ("Format gate (black", "Lint gate (ruff", "Mypy gate (ENFORCED"):
        assert "if: always() && steps.proven.outputs.pr_proven != 'true'" in _ci_lint_step(gate), gate
    # gitleaks is the one scan of a direct push (secret-scan.yml is pull_request-only).
    assert "steps.proven" not in _ci_lint_step("Secret scan (gitleaks")


def test_dependabot_automerge_keys_off_pr_checks_and_requires_the_full_suite():
    """#4252 box 3: dependabot-validate.yml is deleted; automerge fires on the PR checks
    workflow and must see the full suite green. The full suite is NOT a ruleset-required
    context, so an automerge that waited only on the required ones could land a bump
    whose behaviour tests are red."""
    assert not (ROOT / ".github" / "workflows" / "dependabot-validate.yml").exists()
    text = DEPENDABOT_AUTOMERGE.read_text(encoding="utf-8")
    assert 'workflows: ["PR checks"]' in text and "name: PR checks" in _text()
    assert "github.event.workflow_run.conclusion == 'success'" in text
    required = text[text.index("REQUIRED_GREEN: |") : text.index("run: |")]
    for ctx in ("Collect + deploy-critical + format", "gitleaks (PR commit range only, not full history)"):
        assert ctx in required, ctx
    full = re.search(r"^\s+name: (Full unit suite[^\n]*)$", _text(), re.M).group(1).strip()
    assert full in required, f"automerge does not require the full-suite check by its exact name ({full})"
    assert '"$HEAD" != "$GREEN_SHA"' in text, "a newer, unvalidated head could be merged"
    assert "--match-head-commit" in text
