#!/usr/bin/env python3
"""tests/test_full_suite_premerge_3025.py — contracts for the pre-merge full suite (#3025).

The premerge marker selects 8,813 of 20,509 tests, so a PR redding only the
deselected ~11,700 read 7/7 green and redded main on landing (≥4 in 5 days:
08-18 ×2, #2907, #3013→#3020). pr-checks.yml's `full-suite` job closes the
class by running the SAME selection as ci-test.yml's coverage gate, pre-merge.
These tests are the contract that keeps the two lanes from silently diverging —
selection parity, dep parity, and the unpiped rule — plus the pure half of the
per-test duration warner (folding #2692's "one pathological test must not hide
inside a total budget" acceptance).

Repo-shape sweep (reads two workflow files) → classified pre-merge via
tests/conftest.py's _PREMERGE_EXTRA_FILES, per the #2372 contract.
"""

import os
import re

import conftest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
PR_CHECKS = os.path.join(REPO, ".github", "workflows", "pr-checks.yml")
CI_TEST = os.path.join(REPO, ".github", "workflows", "ci-test.yml")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _full_suite_pytest_lines():
    """EVERY pytest command line in the full-suite job.

    #3025 ran one command; since the parallel split it runs two — a `-m "not serial"`
    parallel pass and a `-m serial` single-process pass for the four modules that must
    mutate the checkout. Reading only the first line is how the second step would drift
    unwatched, so every contract below is asserted across the whole list.
    """
    src = _read(PR_CHECKS)
    block = src[src.index("  full-suite:") :]
    lines = re.findall(r"run:\s*(python3 -m pytest[^\n]*)", block)
    assert lines, "pr-checks.yml full-suite job no longer runs a pytest command"
    return lines


def _full_suite_pytest_line():
    """The PARALLEL pass — the one that carries the shared selection contract."""
    return _full_suite_pytest_lines()[0]


def _coverage_gate_pytest_lines():
    """EVERY pytest invocation in ci-test.yml's coverage-gate step, continuations joined.

    #3835: this job ran ONE serial pytest and was over its 1950s duration budget on 8 of
    9 consecutive green-main runs. #3797's two-pass lane — the remedy — had landed in
    `pr-checks.yml` only. Now that a SECOND copy of the two-pass idiom exists, the
    partition assertion has to cover it: two passes over one selection with no
    complement check is how a test falls into NEITHER pass while both steps stay green,
    and that failure mode is indistinguishable from a healthy run from the outside.

    ci-test.yml writes its invocations across backslash-continued lines, so they are
    joined here rather than matched line-wise — a line-wise regex silently reads only
    the first fragment, which carries no `-m` at all.

    #4252: the two passes now live in the `shard` matrix's coverage-pass step (each leg
    runs one of them; the parallel one over its half of the files) and the floor moved
    to the `test` job's combine step. Returned PARALLEL first, then serial, whatever
    order the step's if/else writes them in.
    """
    block = _shard_step_block()
    joined = re.sub(r"\\\n\s*", " ", block)
    lines = [re.sub(r"\s+", " ", m).strip() for m in re.findall(r"(python3 -m pytest[^\n]*)", joined)]
    assert lines, "ci-test.yml coverage gate no longer runs a pytest command"
    return sorted(lines, key=lambda ln: "-n auto" not in ln)


def _shard_step_block():
    src = _read(CI_TEST)
    block = src[src.index("      - name: Coverage pass — this leg's share of tests/") :]
    return block[: block.index("      - name: Upload this leg's coverage data")]


def _coverage_gate_ignores():
    """The --ignore set of ci-test.yml's coverage-gate pytest invocation."""
    src = _read(CI_TEST)
    m = re.search(r"python3 -m pytest tests/ \\\n(.*?)-q", src, re.S)
    assert m, "ci-test.yml coverage gate pytest invocation not found in its known shape"
    return set(re.findall(r"--ignore=(\S+)", m.group(1)))


def test_selection_parity_with_postmerge_coverage_gate():
    """Same target, same --ignore set: the pre-merge full suite runs what the
    post-merge coverage gate runs (minus instrumentation). If either side changes
    its selection, this fails on the PR that did it, not on main afterward."""
    lines = _full_suite_pytest_lines()
    for line in lines:
        assert " tests/ " in line + " ", f"full-suite no longer targets tests/: {line}"
        assert "--cov" not in line, "coverage instrumentation is a post-merge concern (~1.4x, #2259) — do not add it here"
        assert "--durations=25" in line, f"the durations block is the #2692 measurement channel — keep it on every pass: {line}"
        assert (
            set(re.findall(r"--ignore=(\S+)", line)) == _coverage_gate_ignores()
        ), f"selection divergence on a pass: {line} vs coverage gate {sorted(_coverage_gate_ignores())}"
    line = lines[0]
    premerge_ignores = set(re.findall(r"--ignore=(\S+)", line))
    assert premerge_ignores == _coverage_gate_ignores(), (
        f"selection divergence: full-suite ignores {sorted(premerge_ignores)} vs "
        f"coverage gate {sorted(_coverage_gate_ignores())} — the #3025 class reopens "
        "the moment these differ"
    )
    assert "--cov" not in line, "coverage instrumentation is a post-merge concern (~1.4x, #2259) — do not add it here"
    assert "--durations=25" in line, "the durations block is the #2692 measurement channel — keep it"


def test_full_suite_command_is_unpiped():
    """`pytest ... | tail` exits with tail's status — the gate-that-cannot-fail
    class (#2746). The full-suite step must stay a bare pytest invocation."""
    for line in _full_suite_pytest_lines():
        assert "|" not in line, f"a full-suite pytest command is piped — its exit status is no longer the gate's: {line}"


def test_dep_parity_with_ci_test():
    """Install pins = ci-test.yml's list minus pytest-cov, the #2258/#3013 rule.
    A dep present post-merge but absent here is invisible until main reds."""
    src = _read(PR_CHECKS)
    job_start = src.index("  full-suite:")
    m = re.search(r"ci_pins\.py ([^\)\n]+)", src[job_start:])
    assert m, "full-suite job no longer installs via scripts/ci_pins.py"
    ours = set(m.group(1).split())
    m2 = re.search(r"ci_pins\.py ([^\)\n]+)", _read(CI_TEST))
    assert m2, "ci-test.yml no longer installs via scripts/ci_pins.py"
    theirs = set(m2.group(1).split())
    assert ours == theirs - {
        "pytest-cov"
    }, f"dep divergence: full-suite {sorted(ours)} vs ci-test-minus-cov {sorted(theirs - {'pytest-cov'})}"


def test_full_suite_job_has_no_paths_filter_or_job_if():
    """The #1662 lesson pre-applied: a paths: filter on the pull_request trigger or
    a job-level if: would make this check silently skippable per-PR."""
    src = _read(PR_CHECKS)
    trigger = src[src.index("\non:") : src.index("\npermissions:")]
    assert "paths" not in trigger, "pr-checks.yml grew a paths filter — the full-suite gate can now silently not run"
    job = src[src.index("  full-suite:") : src.index("  # ════", src.index("  full-suite:"))]
    assert not re.search(r"^    if:", job, re.M), "full-suite grew a job-level if: — silently skippable"


# ── The per-test duration warner (pure half; conftest.py owns the hooks) ──────
def test_warner_emits_above_bar_only():
    lines = conftest.slow_test_warning_lines([("tests/slow.py::test_a", 181.0), ("tests/fast.py::test_b", 12.0)], bar=90.0)
    assert len(lines) == 1 and "test_a" in lines[0] and "181.0s" in lines[0]
    assert lines[0].startswith("::warning"), "must be a ::warning annotation — the e11 wrap gate reads those"


def test_warner_silent_when_nothing_slow():
    assert conftest.slow_test_warning_lines([("tests/fast.py::test_b", 12.0)], bar=90.0) == []


def test_warner_bar_sits_between_honest_slow_and_pathological():
    """90s: above the slowest honest test observed on CI (55s, platform-model
    determinism) and far below the 180.85s pathological case that motivated it.
    Moving the bar is fine — but do it against a fresh --durations reading."""
    assert 55 < conftest.PER_TEST_WARN_SECONDS < 180


def test_the_two_passes_partition_the_suite_exactly():
    """The split is only safe if every test lands in EXACTLY ONE pass.

    Two passes over one selection have two silent failure modes and they look identical
    from the outside — both report a green check:

      * a test in NEITHER pass is a test that stopped running, and the job is green
      * a test in BOTH passes runs twice, which is waste, and worse, an in-tree writer
        running concurrently with its own serial twin is the exact race the `serial`
        marker exists to prevent

    The guarantee here is STRUCTURAL rather than a count: the two marker expressions
    must be exact complements over one marker name, so the partition is a property of
    the selection grammar and cannot drift with the suite's size. A count would go stale
    the next time anyone adds a test.

    MEASURED once to back the reasoning, 2026-09-15, on this branch's own rebased tree,
    by `--collect-only` on all three selections and diffing NODE IDS, not totals:

        full selection            26,401
        -m "not serial"           26,353
        -m serial                      48
        in ALL, in NEITHER pass:   (empty)
        in a pass, not in ALL:     (empty)
        in BOTH passes:            (empty)

    That also settles an open question I posted on the PR: an apparent five-test
    arithmetic gap between an implied collected count and the reported outcomes. There
    is no gap. The two numbers came from different runs on different trees, and the
    suite had grown by five tests between them. The partition itself was always exact,
    and this test is what keeps saying so without anyone re-running the measurement.
    """
    _assert_exact_complement_partition(_full_suite_pytest_lines(), "pr-checks.yml full-suite")


def _assert_exact_complement_partition(lines, where):
    """The partition contract, ONE definition, applied to every lane that runs two passes.

    #3835 added a second copy of the two-pass idiom (ci-test.yml's coverage gate). A
    second copy of the IDIOM with only one copy of the ASSERTION is the same shape as the
    defect this whole file guards — so this is shared, not duplicated.
    """
    assert len(lines) == 2, f"expected exactly two full-suite pytest passes in {where}, found {len(lines)}: {lines}"

    exprs = []
    for line in lines:
        # `python3 -m pytest` carries its own `-m`; strip the interpreter's module flag
        # first or every line looks like it selects on a marker named "pytest".
        args = re.sub(r"^\s*python3?\s+-m\s+pytest\b", "", line)
        m = re.findall(r"""-m\s+(?:"([^"]+)"|'([^']+)'|(\S+))""", args)
        assert len(m) == 1, f"a pass must carry exactly one -m marker expression: {line}"
        exprs.append(next(g for g in m[0] if g).strip())

    assert sorted(exprs) == ["not serial", "serial"], (
        f"[{where}] the two passes must select on exact complements of ONE marker; got {exprs!r}. "
        "Anything else (a second marker, an `and`/`or` clause, a renamed marker on one "
        "side only) breaks the partition and a test can fall into neither pass while "
        "both steps stay green."
    )

    # ...and the marker they complement over must be the registered one, or `-m serial`
    # selects nothing and pytest's strict-marker setting is the only thing standing
    # between that and a silently empty serial pass.
    with open(os.path.join(REPO, "pytest.ini"), encoding="utf-8") as fh:
        ini = fh.read()
    assert re.search(r"^\s*serial:", ini, re.M), "the `serial` marker is not registered in pytest.ini — see #3025"


# ── #3835: the POST-MERGE lane gets the same guarantees ─────────────────────


def test_the_postmerge_coverage_gate_also_runs_the_two_pass_lane():
    """#3797's remedy landed in `pr-checks.yml` only, so the post-merge job stayed a
    single serial invocation and sat over its 1950s duration budget on 8 of 9 consecutive
    green-main runs (median 2850s, 1.46x; measured on #3835). This asserts the shed was
    applied rather than the budget raised — the class record is explicit that it was
    "raised every time up to #3106 then SHED twice running"."""
    lines = _coverage_gate_pytest_lines()
    assert len(lines) == 2, f"the coverage gate is not running the two-pass lane: {lines}"
    assert "-n auto --dist loadfile" in lines[0], f"the parallel pass is not parallel: {lines[0]}"
    assert "-n auto" not in lines[1], f"the serial pass must be single-process — that is the whole point: {lines[1]}"


def test_the_postmerge_passes_partition_the_suite_exactly():
    """The SAME contract as the pre-merge lane, through the same helper.

    A second copy of the two-pass idiom with only one copy of the partition assertion is
    exactly the shape #3835 exists to fix, one level up."""
    _assert_exact_complement_partition(_coverage_gate_pytest_lines(), "ci-test.yml coverage gate")


def test_the_coverage_FLOOR_is_measured_over_BOTH_passes_not_one():
    """The splitting hazard that has nothing to do with the partition.

    Coverage is produced by several invocations. If the floor rode any one of them it
    would grade the suite on a SUBSET — redding a correct build, or (on the ~48 serial
    tests alone) passing trivially and gating nothing.

    #4252: the passes run on separate shard legs, so NO pass carries a floor, an append
    or the xml report; the `test` job's combine step grades the floor once, over every
    leg's data, and refuses to run on a missing leg. That step is EXECUTED against real
    coverage data in tests/test_ci_test_shards_4252.py (union passes where no single leg
    would; a missing leg and a red leg both red the verdict).
    """
    for ln in _coverage_gate_pytest_lines():
        for flag in ("--cov-fail-under", "--cov-append", "xml:coverage.xml"):
            assert flag not in ln, f"a single pass carries {flag} — it would grade or publish a SUBSET of the suite: {ln}"
    src = _read(CI_TEST)
    combine = src[src.index("      - name: Test coverage gate") :]
    combine = combine[: combine.index("      - name: Coverage regression gate")]
    assert "coverage combine" in combine and "coverage report --fail-under=" in combine
    assert "coverage xml -o coverage.xml" in combine


def test_every_postmerge_pass_keeps_pipefail_in_its_step():
    """#2259: GitHub's default shell is `bash -e {0}` and `-e` does not imply pipefail, so
    `pytest … | tail` exits with tail's status — always 0. That defect made this exact
    gate unable to fail for its whole life. Splitting one piped invocation into two does
    not double the risk; it doubles the number of pipes one `set -o pipefail` has to
    cover, so assert the line is still there and still ABOVE both."""
    block = _shard_step_block()  # #4252: the passes live in the shard legs' step now
    pipefail = block.index("set -o pipefail")
    for ln in re.finditer(r"python3 -m pytest", block):
        assert ln.start() > pipefail, "a pytest pass runs BEFORE `set -o pipefail` — its exit code is tail's (#2259)"
    # Counted off the PARSED commands, not off the step's text. Counting `"| tail -"`
    # occurrences in the block reads the prose too — this step's own comments quote the
    # #2259 defect (`pytest … | tail -100`) and the `tail widened 100 -> 160` note, so a
    # text count returns 4 for two commands. Same shape as #3785's enrolment leg, which
    # matched `_built_at` on a comment line.
    piped = [ln for ln in _coverage_gate_pytest_lines() if re.search(r"\|\s*tail -", ln)]
    assert len(piped) == len(_coverage_gate_pytest_lines()), (
        "a coverage pass is not piped to tail — harmless on its own, but this step's whole "
        "history is about a pipe swallowing an exit code; keep the shape uniform (#2259)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# #4252 — no single-file pytest step beside the coverage passes; the labels survive
# ══════════════════════════════════════════════════════════════════════════════
# ci-test.yml ran eleven files one at a time and then ran them again in the coverage
# passes (the whole tests/ tree). The single-file steps are gone and their labels are
# printed as sections by scripts/ci_test_sections.py from the passes' JUnit XML.


def _ci_test_job_pytest_commands():
    src = _read(CI_TEST)
    return re.findall(r"python3 -m pytest ([^\n\\]*)", src)


def test_ci_test_runs_no_single_file_pytest_step():
    """Every pytest command in the Unit Tests job selects the whole tests/ tree. A
    `python3 -m pytest tests/test_x.py` step would run that file twice per push again."""
    cmds = _ci_test_job_pytest_commands()
    assert cmds, "ci-test.yml runs no pytest command at all"
    single = [c for c in cmds if re.match(r"tests/test_\S+\.py", c.strip())]
    assert not single, f"#4252: a single-file pytest step is back in ci-test.yml (it also runs in the coverage passes): {single}"


def test_both_coverage_passes_write_the_junit_the_sections_read():
    lines = _coverage_gate_pytest_lines()
    assert len(lines) == 2
    # #4252: one JUnit per shard leg, uploaded with its coverage data; the sections read
    # all of them (the leg set itself is held by tests/test_ci_test_shards_4252.py).
    assert '--junitxml="shard-out/junit-$LEG.xml"' in lines[0] and "--junitxml=shard-out/junit-serial.xml" in lines[1], lines
    src = _read(CI_TEST)
    drift = src[src.index("      - name: Coverage regression gate") :]
    assert (
        "python3 scripts/ci_test_sections.py shard-out/junit-parallel-1.xml shard-out/junit-parallel-2.xml shard-out/junit-serial.xml"
        in drift
    )
    assert "if: always()" in drift[: drift.index("run: |")], "the sections report must run when a coverage pass is red"


def test_every_section_label_names_a_real_test_file():
    import importlib.util

    spec = importlib.util.spec_from_file_location("ci_test_sections", os.path.join(REPO, "scripts", "ci_test_sections.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert len(mod.SECTIONS) == 11, "the eleven former single-file steps each keep a label"
    missing = [p for p in mod.SECTIONS.values() if not os.path.isfile(os.path.join(REPO, p))]
    assert not missing, f"#4252: section label(s) point at test files that no longer exist: {missing}"


def test_sections_report_names_a_failure_by_its_label_and_never_exits_non_zero(tmp_path, capsys):
    import importlib.util

    spec = importlib.util.spec_from_file_location("ci_test_sections", os.path.join(REPO, "scripts", "ci_test_sections.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    xml = (
        '<testsuites><testsuite name="pytest">'
        '<testcase classname="tests.test_role_policies" name="test_a"/>'
        '<testcase classname="tests.test_role_policies.TestX" name="test_b"><failure message="boom"/></testcase>'
        '<testcase classname="tests.test_upstream_contracts" name="test_c"><skipped/></testcase>'
        "</testsuite></testsuites>"
    )
    p = tmp_path / "j.xml"
    p.write_text(xml, encoding="utf-8")
    assert mod.main(["x", str(p), str(tmp_path / "absent.xml")]) == 0
    out = capsys.readouterr().out
    assert "::error title=IAM policy linter (test_role_policies.py)::1 failed in tests/test_role_policies.py" in out
    assert "IAM policy linter (test_role_policies.py): 1 passed, 1 failed, 0 skipped" in out
    assert "Upstream-API contract tests (test_upstream_contracts.py): 0 passed, 0 failed, 1 skipped" in out
    assert "::warning title=Run unit tests::tests/test_shared_modules.py ran no tests" in out
    bad = tmp_path / "bad.xml"
    bad.write_text("<not closed", encoding="utf-8")
    assert mod.main(["x", str(bad)]) == 0
