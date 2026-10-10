"""tests/test_ci_test_shards_4252.py — #4252 box 4: the post-merge suite runs as shard legs.

ci-test.yml's Unit Tests job ran the whole suite on one 4-core runner and was the long
pole of every push to main (18.5-23.6 min against the 20-min bar). It now runs as a
`shard` matrix — two legs of the `-m "not serial"` pass, each over half of the test
FILES (tests/ci_shard.py), plus the `-m serial` pass on its own leg — and a `test` job
(still named `Unit Tests`, the name scripts/find_test_verdict_owner.py and
check_main_green.py read) combines their coverage data and grades the floor once.

What has to stay true, and fails here if it stops:
  * the file split is EXACT — every test file in exactly one parallel leg;
  * the matrix's parallel legs are exactly 1/N..N/N for one N, plus one serial leg;
  * the verdict job needs every leg, runs when one is red, refuses a red leg and a
    missing leg's data, and is the ONLY place the floor is graded;
  * the combine step really does that — executed below with real coverage data.

Reads one workflow file and lists tests/ (a repo-shape sweep), so it is classified in
tests/conftest.py's _PREMERGE_EXTRA_FILES per the #2372 contract.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap

import ci_shard
import pytest
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
CI_TEST = os.path.join(REPO, ".github", "workflows", "ci-test.yml")
COMBINE_STEP = "Test coverage gate (regression floor, ADR-080)"
SHARD_STEP = "Coverage pass — this leg's share of tests/"


def _wf():
    with open(CI_TEST, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _step(job, name):
    for step in _wf()["jobs"][job]["steps"]:
        if step.get("name") == name:
            return step
    raise AssertionError(f"ci-test.yml job {job!r} has no step named {name!r}")


def _legs():
    return _wf()["jobs"]["shard"]["strategy"]["matrix"]["include"]


def _parallel_total():
    specs = [leg["shard"] for leg in _legs() if leg["shard"]]
    totals = {ci_shard.parse_spec(s)[1] for s in specs}
    assert len(totals) == 1, f"the parallel legs disagree on N: {specs}"
    return totals.pop()


def _test_files():
    return sorted(n for n in os.listdir(HERE) if ci_shard.is_test_module(n) and os.path.isfile(os.path.join(HERE, n)))


# ── the split ─────────────────────────────────────────────────────────────────


def test_the_matrix_is_one_serial_leg_plus_parallel_legs_1_to_N():
    legs = _legs()
    serial = [leg for leg in legs if not leg["shard"]]
    assert [leg["leg"] for leg in serial] == ["serial"], f"exactly one unsharded leg, named serial: {legs}"
    n = _parallel_total()
    specs = sorted(leg["shard"] for leg in legs if leg["shard"])
    assert specs == [f"{k}/{n}" for k in range(1, n + 1)], f"parallel legs must be exactly 1/N..N/N: {specs}"
    assert n >= 2, "one parallel leg is the pre-#4252 single runner again"
    assert len({leg["leg"] for leg in legs}) == len(legs), "leg names name the artifacts — they must be unique"
    assert _wf()["jobs"]["shard"]["strategy"].get("fail-fast") is False, "one red leg must not cancel the others"


def test_every_test_file_lands_in_exactly_one_parallel_leg():
    n = _parallel_total()
    files = _test_files()
    assert len(files) > 500, f"tests/ listing looks wrong ({len(files)} files)"
    owners = {}
    for name in files:
        kept = [k for k in range(1, n + 1) if not ci_shard.excluded(os.path.join(HERE, name), f"{k}/{n}")]
        assert len(kept) == 1, f"{name} is kept by legs {kept} — the split must be exact"
        owners[name] = kept[0]
    sizes = [sum(1 for v in owners.values() if v == k) for k in range(1, n + 1)]
    # A hash split, not a balanced one: hold it to a loose band so a degenerate split
    # (everything on one leg, which reads green and is slow) fails here.
    assert min(sizes) > len(files) / n * 0.75, f"a leg holds too few files: {sizes}"


def test_unsharded_runs_and_non_test_paths_are_never_excluded():
    assert not ci_shard.excluded(os.path.join(HERE, "test_anything.py"), "")
    for helper in ("conftest.py", "ci_shard.py", "fixtures", "repo_scan_cache.py"):
        for k in (1, 2):
            assert not ci_shard.excluded(os.path.join(HERE, helper), f"{k}/2"), helper


def test_a_malformed_shard_spec_raises_rather_than_running_everything_or_nothing():
    quiet = []
    for bad in ("2", "0/2", "3/2", "a/b", "1/0", "1/2/3"):
        try:
            ci_shard.excluded(os.path.join(HERE, "test_x.py"), bad)
        except ValueError:
            continue
        quiet.append(bad)
    assert not quiet, f"malformed CI_TEST_SHARD value(s) accepted silently: {quiet}"


def test_the_conftest_hook_reads_the_shard_env(monkeypatch):
    import conftest

    n = _parallel_total()
    name = _test_files()[0]
    mine = ci_shard.shard_of(name, n)
    other = mine % n + 1
    path = os.path.join(HERE, name)
    monkeypatch.setenv(ci_shard.SHARD_ENV, f"{mine}/{n}")
    assert conftest.pytest_ignore_collect(path, None) is None
    monkeypatch.setenv(ci_shard.SHARD_ENV, f"{other}/{n}")
    assert conftest.pytest_ignore_collect(path, None) is True
    monkeypatch.delenv(ci_shard.SHARD_ENV)
    assert conftest.pytest_ignore_collect(path, None) is None


# ── the workflow wiring ───────────────────────────────────────────────────────


def test_the_shard_step_feeds_the_leg_spec_and_writes_per_leg_outputs():
    step = _step("shard", SHARD_STEP)
    assert step["env"]["CI_TEST_SHARD"] == "${{ matrix.shard }}"
    assert step["env"]["LEG"] == "${{ matrix.leg }}"
    run = step["run"]
    assert run.index("set -o pipefail") < run.index("python3 -m pytest")
    assert 'mv .coverage "shard-out/coverage-$LEG.dat"' in run
    for bad in ("--cov-fail-under", "--fail-under", "xml:coverage.xml", "--cov-append"):
        assert bad not in run, f"a leg grades or reports on a SUBSET of the suite ({bad}) — only `test` may"
    upload = _wf()["jobs"]["shard"]["steps"][-1]
    assert upload["uses"].startswith("actions/upload-artifact@") and upload["if"] == "always()"
    assert upload["with"]["name"] == "unit-tests-shard-${{ matrix.leg }}" and upload["with"]["path"] == "shard-out/"


def test_the_verdict_job_keeps_its_name_needs_every_leg_and_runs_when_one_is_red():
    job = _wf()["jobs"]["test"]
    assert job["name"] == "Unit Tests", "scripts/find_test_verdict_owner.py reads `test / Unit Tests`"
    assert job["needs"] == "shard"
    cond = job["if"]
    assert "!cancelled()" in cond and "inputs.owner_run == ''" in cond, cond
    assert _wf()["jobs"]["shard"]["if"] == "inputs.owner_run == ''"
    dl = next(s for s in job["steps"] if str(s.get("uses", "")).startswith("actions/download-artifact@"))
    assert dl["with"]["pattern"] == "unit-tests-shard-*" and dl["with"]["merge-multiple"] is True
    assert dl["with"]["path"] == "shard-out"


def test_the_combine_step_expects_every_leg_and_carries_the_only_floor():
    step = _step("test", COMBINE_STEP)
    assert int(step["env"]["EXPECTED_LEGS"]) == len(_legs())
    assert step["env"]["SHARD_RESULT"] == "${{ needs.shard.result }}"
    run = step["run"]
    assert re.search(r"coverage report --fail-under=\d+", run)
    text = open(CI_TEST, encoding="utf-8").read()
    assert len(re.findall(r"--(?:cov-)?fail-under=\d+", text)) == 1, "the floor is graded in exactly one place"


def test_the_sections_read_every_legs_junit():
    # The YAML name parses as "...(ratchet," — the ` #1206…` tail is a YAML comment.
    run = next(s for s in _wf()["jobs"]["test"]["steps"] if str(s.get("name", "")).startswith("Coverage regression gate"))["run"]
    m = re.search(r"ci_test_sections\.py ([^\n|]+)", run)
    assert m
    assert set(m.group(1).split()) == {f"shard-out/junit-{leg['leg']}.xml" for leg in _legs()}


# ── the combine step, executed ────────────────────────────────────────────────

_MOD = textwrap.dedent("""\
    import sys


    def a():
        return 1


    def b():
        return 2


    def c():
        return 3


    def d():
        return 4


    for name in sys.argv[1:]:
        globals()[name]()
    """)


def _leg_data(tmp_path, leg, calls):
    out = tmp_path / "shard-out"
    out.mkdir(exist_ok=True)
    env = dict(os.environ, COVERAGE_FILE=str(out / f"coverage-{leg}.dat"))
    subprocess.run([sys.executable, "-m", "coverage", "run", "mod.py", *calls], cwd=tmp_path, env=env, check=True, capture_output=True)


def _combine(tmp_path, shard_result="success"):
    step = _step("test", COMBINE_STEP)
    body = step["run"].replace("python3 -m coverage", f"{sys.executable} -m coverage")
    env = dict(os.environ, SHARD_RESULT=shard_result, EXPECTED_LEGS=str(step["env"]["EXPECTED_LEGS"]))
    env.pop("COVERAGE_FILE", None)
    return subprocess.run(["bash", "-e", "-c", body], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120)


@pytest.fixture
def legs_tree(tmp_path):
    pytest.importorskip("coverage")
    (tmp_path / "mod.py").write_text(_MOD, encoding="utf-8")
    return tmp_path


def test_combined_legs_pass_the_floor_that_no_single_leg_would(legs_tree):
    names = [leg["leg"] for leg in _legs()]
    calls = [["a", "b"], ["c", "d"]] + [[] for _ in names[2:]]
    for leg, c in zip(names, calls):
        _leg_data(legs_tree, leg, c)
    p = _combine(legs_tree)
    assert p.returncode == 0, p.stdout + p.stderr
    assert (legs_tree / "coverage.xml").is_file()
    assert "100%" in p.stdout


def test_a_red_leg_reds_the_verdict_even_with_full_data(legs_tree):
    for leg in _legs():
        _leg_data(legs_tree, leg["leg"], ["a", "b", "c", "d"])
    p = _combine(legs_tree, shard_result="failure")
    assert p.returncode == 1 and "a shard leg did not pass" in p.stdout


def test_a_missing_legs_data_reds_rather_than_grading_a_subset(legs_tree):
    for leg in _legs()[:-1]:
        _leg_data(legs_tree, leg["leg"], ["a", "b", "c", "d"])
    p = _combine(legs_tree)
    assert p.returncode == 1 and "the floor would grade a subset" in p.stdout


def test_combined_coverage_under_the_floor_reds(legs_tree):
    for leg in _legs():
        _leg_data(legs_tree, leg["leg"], [])
    p = _combine(legs_tree)
    assert p.returncode != 0, p.stdout
    assert (legs_tree / "coverage.xml").is_file(), "the xml is written BEFORE the floor so the ratchet step still reads it"
