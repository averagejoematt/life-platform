"""tests/test_ci_dark_flag_sweep_3315.py — the dark-flag class, pinned as a SET (#3315).

#2938 found the deploy-gating visual-qa job invoking `--ai-qa` while never installing
boto3: the flag printed `⚠ unavailable` and the job reported success for months. Its
closing comment left one box unclaimed — "sweep the sibling class: any other CI step
invoking a flag whose dependency the job never installs" — and #3315 is that carrier.

The sweep itself is scripts/ci_dark_flag_sweep.py (read its docstring for the method:
per-job installed set, transitive import closure of every invoked script including the
`bash deploy/*.sh` layer, waivers that must stay live). This file is the guard that
keeps the class closed:

  * the live tree has zero unwaived reaches and zero stale waivers;
  * coverage is reported with n and the unevaluated steps are NAMED (ADR-105);
  * mutation proofs — the sweep FAILS on each shape it exists to catch, built from the
    real tree (the pre-#3315 fresh-eyes install line, the bare-system-python wedge watch,
    a `--cov` flag without pytest-cov, a string mention that must NOT count), so a
    future edit that quietly weakens the detector reds here.

PyYAML is imported lazily by the sweep and is absent from the deploy-critical lane, so
this module importorskips it (the #2699/#2732 shape). It sweeps `.github/workflows/`
itself (every file on disk must be in the evaluation), so it is a structural gate in the
census's sense: registered in `tests/conftest.py::_PREMERGE_EXTRA_FILES` (runs in the
pre-merge fast lane, which installs pyyaml) and proved in
`scripts/gate_census_mutations.py` as `structural::test_ci_dark_flag_sweep_3315.py`.
"""

import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("yaml")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

import ci_dark_flag_sweep as sweep  # noqa: E402

_CHECKOUT = {"uses": "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"}
_SETUP = {"uses": "./.github/actions/setup-ci"}


@pytest.fixture(scope="module")
def live_results():
    return sweep.evaluate_repo(_REPO)


# ── the live tree ──────────────────────────────────────────────────────────────────


def test_no_ci_step_reaches_a_dependency_its_job_never_installs(live_results):
    bad = sweep.violations(live_results)
    assert bad == [], (
        "CI step(s) reach a third-party import their job never installs — install it in that job, or add a LIVE, "
        "reasoned waiver to ALLOWED_ABSENT:\n  " + "\n  ".join(bad)
    )


def test_every_waiver_is_still_live(live_results):
    stale = sweep.stale_waivers(live_results)
    assert (
        stale == []
    ), "ALLOWED_ABSENT entries whose reach no longer exists (or whose dist is now installed) — delete them:\n  " + "\n  ".join(stale)


def test_coverage_is_reported_with_n_and_names_what_it_could_not_evaluate(live_results):
    cov = sweep.coverage(live_results)
    assert cov["jobs"] >= 30 and cov["steps_total"] >= 200, cov
    assert cov["by_kind"].get("python", 0) >= 80, cov["by_kind"]
    # Every step lands in exactly one class — nothing is silently dropped.
    assert sum(cov["by_kind"].values()) == cov["steps_total"]
    # The unevaluated list is an explicit artefact, never an implicit skip.
    assert isinstance(cov["unevaluated"], list)
    assert cov["unresolved_scripts"] == [], cov["unresolved_scripts"]


def test_every_workflow_file_on_disk_is_in_the_sweep(live_results):
    """The inventory is the directory, not a hand-kept list: every `*.yml` under
    .github/workflows/ must appear in the evaluation, and the sweep must not report a
    workflow that is not on disk. n is the file count, stated in the failure."""
    on_disk = {p.name for p in Path(_REPO, ".github", "workflows").rglob("*.yml")}
    swept = {r.workflow for r in live_results}
    assert (
        on_disk and on_disk == swept
    ), f"{len(on_disk)} workflow file(s) on disk, {len(swept)} swept — missing {sorted(on_disk - swept)}, phantom {sorted(swept - on_disk)}"


def test_the_known_instances_are_evaluated_not_skipped(live_results):
    """The four jobs #3315 fixed must all be swept as python-invoking steps (a regex regression
    that stopped seeing them would otherwise read as a clean sweep)."""
    seen = {(r.workflow, r.job, s.script) for r in live_results for s in r.scripts}
    assert ("fresh-eyes.yml", "discover", "scripts/fresh_eyes_discovery.py") in seen
    assert ("deploy-wedge-watch.yml", "watch", "scripts/check_main_green.py") in seen
    assert ("site-deploy.yml", "deploy-site", "scripts/render_portraits.py") in seen  # via deploy_site.sh > sync_site_to_s3.sh
    assert ("site-deploy.yml", "deploy-site", "scripts/v4_build_stack_manifest.py") in seen
    assert ("site-deploy.yml", "smoke", "deploy/deploy_convergence.py") in seen  # via smoke_test_site.sh


# ── mutation proofs: the detector can fail ─────────────────────────────────────────


def _job(*runs, setup=True):
    steps = [_CHECKOUT] + ([_SETUP] if setup else [])
    steps += [{"name": f"step {i}", "run": r} for i, r in enumerate(runs)]
    return {"steps": steps}


def test_mutation_the_pre_3315_fresh_eyes_install_line_is_caught():
    """The shipped-before line: `ci_pins.py playwright boto3` — no pillow, while the script's
    capture path raises without it."""
    before = _job(
        "python -m pip install --upgrade pip\nPINS=$(python3 scripts/ci_pins.py playwright boto3)\npython -m pip install $PINS\n"
        "python -m playwright install --with-deps chromium",
        "python3 scripts/fresh_eyes_discovery.py",
    )
    bad = sweep.violations(sweep.evaluate_job("fresh-eyes.yml", "discover", before, _REPO))
    assert any("fresh_eyes_discovery.py" in v and "pillow" in v for v in bad), bad
    after = _job(
        "PINS=$(python3 scripts/ci_pins.py playwright boto3 botocore pillow)\npython -m pip install $PINS\n"
        "python -m playwright install --with-deps chromium",
        "python3 scripts/fresh_eyes_discovery.py",
    )
    assert sweep.violations(sweep.evaluate_job("fresh-eyes.yml", "discover", after, _REPO)) == []


def test_mutation_system_python_counts_as_nothing_installed():
    """The pre-#3315 deploy-wedge-watch shape: no setup-python, no install, a script whose flagged
    branch imports yaml."""
    before = _job("python3 scripts/check_main_green.py --head-coverage-check | tee v.txt", setup=False)
    res = sweep.evaluate_job("deploy-wedge-watch.yml", "watch", before, _REPO)
    assert res[-1].runtime == "system"
    bad = sweep.violations(res)
    assert any("check_main_green.py" in v and "pyyaml" in v for v in bad), bad
    after = _job(
        "PINS=$(python3 scripts/ci_pins.py pyyaml)\npip install --quiet $PINS", "python3 scripts/check_main_green.py --head-coverage-check"
    )
    assert sweep.violations(sweep.evaluate_job("deploy-wedge-watch.yml", "watch", after, _REPO)) == []


def test_mutation_a_pytest_plugin_flag_without_the_plugin_is_caught():
    job = _job(
        "PINS=$(python3 scripts/ci_pins.py pytest)\npip install $PINS", "python3 -m pytest tests/test_shared_modules.py --cov=lambdas -q"
    )
    bad = sweep.violations(sweep.evaluate_job("x.yml", "j", job, _REPO))
    assert any("pytest-cov" in v for v in bad), bad
    ok = _job("PINS=$(python3 scripts/ci_pins.py pytest pytest-cov)\npip install $PINS", "python3 -m pytest tests/ --cov=lambdas -q")
    assert sweep.violations(sweep.evaluate_job("x.yml", "j", ok, _REPO)) == []


def test_mutation_the_shell_layer_is_followed_and_fail_open_is_named():
    """`bash deploy/deploy_site.sh` → sync_site_to_s3.sh → `python3 …/render_portraits.py || echo skipped`:
    the sweep must reach the builder AND flag that a `|| echo` hides the failure."""
    job = _job("bash deploy/deploy_site.sh")
    res = sweep.evaluate_job("site-deploy.yml", "deploy-site", job, _REPO)
    scripts = {s.script: s for r in res for s in r.scripts}
    assert "scripts/render_portraits.py" in scripts, sorted(scripts)
    assert "sync_site_to_s3.sh" in scripts["scripts/render_portraits.py"].via
    assert scripts["scripts/render_portraits.py"].fail_open
    bad = sweep.violations(res)
    assert any("render_portraits.py" in v and "pillow" in v and "FAIL-OPEN" in v for v in bad), bad


def test_mutation_a_string_mention_is_not_an_invocation():
    """Documentation inside an echo must not be swept as a call (the pre-fix detector counted
    `echo "… bash deploy/rollback_site.sh HEAD~1"` as running the whole site build)."""
    job = _job(
        'echo "If the sync died, roll back: bash deploy/rollback_site.sh HEAD~1"\necho "or run python3 scripts/check_main_green.py --head-coverage-check"'
    )
    res = sweep.evaluate_job("x.yml", "j", job, _REPO)
    assert all(not r.scripts for r in res), [s.script for r in res for s in r.scripts]


def test_installing_boto3_makes_botocore_importable():
    """boto3 pins botocore exactly; a job that installs boto3 must not be told botocore is missing."""
    job = _job("PINS=$(python3 scripts/ci_pins.py boto3)\npip install $PINS", "python3 deploy/config_twin_sync.py --strict")
    bad = sweep.violations(sweep.evaluate_job("x.yml", "j", job, _REPO))
    assert not any("botocore" in v for v in bad), bad


def test_a_waiver_whose_reach_vanished_is_reported_stale(live_results):
    phantom = (("nowhere.yml", "nojob", "scripts/ci_pins.py", "boto3", "a reach that does not exist"),)
    assert sweep.stale_waivers(live_results, allowed=phantom) == [
        "nowhere.yml::nojob::scripts/ci_pins.py::boto3 — a reach that does not exist",
    ]


def test_a_waiver_needs_the_exact_job_not_just_the_script():
    """A reason written for one job must not silently cover another job's copy of the script."""
    job = _job(
        "PINS=$(python3 scripts/ci_pins.py playwright)\npython -m pip install $PINS\npython -m playwright install --with-deps chromium",
        "python3 tests/pr_render_gate.py",
    )
    other_job = sweep.violations(sweep.evaluate_job("some-other.yml", "render", job, _REPO))
    assert any("pr_render_gate.py" in v and "pillow" in v for v in other_job), other_job
    waived = sweep.violations(sweep.evaluate_job("v4-gate.yml", "render-accuracy-gate", job, _REPO))
    assert not any("pillow" in v for v in waived), waived
