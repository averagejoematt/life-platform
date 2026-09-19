"""tests/test_absent_expected_job_3608.py — #3608 box 2: an ABSENT job is a RED.

THE DEFECT. `scripts/check_main_green.py` classified main by what the run's
jobs CONCLUDED. A job that never attached concludes nothing, so it produced no
record to classify, the run rolled up `success`, and the gate printed GREEN.
The forensic RCA of 2026-09-05 named the shape (devex ROW4) and Session W paid
for it: a deploy that was stranded rather than failed reads as no signal, and
no signal reads as fine.

THE FIX, derived rather than listed:
  * WHICH JOBS are expected comes from `.github/workflows/ci-cd.yml`'s own jobs
    block (`ci_cd_expected_jobs`) — a job added to the workflow is expected from
    the moment it is added, and a job with a job-level `if:` is excluded because
    it is conditional by construction.
  * WHETHER THE COMMIT IS IN SCOPE comes from `deploy/sentinel_github.py`'s
    `PUSH_TRIGGER_GLOBS` (`commit_is_in_push_trigger_scope`), whose parity with
    the live workflow filters is itself guarded in tests/test_drift_sentinel.py.

Both are read from the tree. Neither is restated here — this file asserts the
BEHAVIOUR (absence reds) and the DERIVATION (the expected set is the workflow's
own), not a copy of either list.
"""

import importlib.util
import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load():
    spec = importlib.util.spec_from_file_location("cmg_3608", os.path.join(REPO_ROOT, "scripts", "check_main_green.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


cmg = _load()

_GREEN_RUN = {
    "databaseId": 4242,
    "status": "completed",
    "conclusion": "success",
    "headSha": "c" * 40,
    "createdAt": "2026-09-19T12:00:00Z",
}


def _jobs_for(expected: dict) -> list[dict]:
    """A full, honest job list for an expected set — every job present under its
    real display name. This is the CONTROL the planted miss is measured against."""
    return [{"name": display} for display in expected.values()]


# ══════════════════════════════════════════════════════════════════════════
# 1. The derivation — the expected set is the workflow file's own jobs.
# ══════════════════════════════════════════════════════════════════════════


def test_the_derivation_lives_in_its_own_module():
    """#1665: `check_main_green.py` hit the 1000-logical-line hard ceiling and was
    paid by extraction, not by a baseline entry. The names below are RE-EXPORTED
    from `check_main_green` so every consumer keeps one import site — but a
    re-export is not ownership (reference_reexport_is_not_a_patch_point), so this
    pins where the derivation actually lives. If it ever collapses back into the
    classifier, this reds before the size guard does."""
    for fn in (cmg.ci_cd_expected_jobs, cmg.absent_expected_jobs, cmg.commit_is_in_push_trigger_scope, cmg.ci_cd_push_paths):
        assert fn.__module__ == "main_green_expected_jobs", f"{fn.__name__} is defined in {fn.__module__}, not the derivation module"


def test_expected_jobs_are_parsed_from_the_workflow_not_listed():
    expected = cmg.ci_cd_expected_jobs("""
name: CI/CD
on:
  push:
    branches: [main]
jobs:
  lint:
    runs-on: ubuntu-latest
  test:
    name: Unit Tests
    runs-on: ubuntu-latest
  deploy:
    name: Deploy
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
""")
    # `lint` has no `name:` → it reports under its id. `test` reports under its
    # declared display name. `deploy` is job-level conditional → NOT expected.
    assert expected == {"lint": "lint", "test": "Unit Tests"}


def test_the_live_workflow_yields_a_non_empty_expected_set():
    """The derivation has to actually resolve against the real file — an empty
    set would make every assertion below vacuously green (the #3863 shape: a box
    that catches nothing on its own founding incident)."""
    expected = cmg.load_ci_cd_expected_jobs()
    assert expected, "no expected jobs derived from the live ci-cd.yml — the absent-job check would be inert"
    assert "lint" in expected and "test" in expected, expected
    # The conditional jobs must NOT be expected: a Deploy that legitimately does
    # not attach (no approval, no deployable change) is the design, not a red.
    assert "deploy" not in expected, expected


def test_scope_is_derived_from_push_trigger_globs():
    """`commit_is_in_push_trigger_scope` must consult the sentinel's globs, not
    a local restatement. ci-cd.yml carries no `paths:` filter since #3378, so
    the union contains `**` and every real commit is in scope — which is the
    point: absence can no longer be excused as an ordinary path-filter skip."""
    assert cmg.commit_is_in_push_trigger_scope(["lambdas/web/site_api.py"]) is True
    assert cmg.commit_is_in_push_trigger_scope(["handovers/HANDOVER_LATEST.md"]) is True
    assert cmg.commit_is_in_push_trigger_scope([]) is False  # nothing changed → no claim


# ══════════════════════════════════════════════════════════════════════════
# 2. The behaviour — absence reds, presence does not.
# ══════════════════════════════════════════════════════════════════════════


def test_a_complete_green_run_stays_green():
    """The must-not-over-fire control. Every expected job present under its real
    display name (including the `test / Unit Tests` reusable-workflow rendering)
    → the verdict is unchanged."""
    expected = cmg.load_ci_cd_expected_jobs()
    jobs = _jobs_for(expected) + [{"name": "test / Unit Tests"}, {"name": "Deploy"}]
    state = cmg.classify_pipeline([_GREEN_RUN], completed_jobs=jobs, expected_jobs=expected)
    assert state["kind"] == cmg.GREEN, state
    assert state["missing_jobs"] == []
    assert cmg.render(state)[0] == 0


def test_a_planted_path_filter_miss_reds():
    """THE MUTATION, run as a test: take the honest job list and delete ONE
    expected job — exactly what a reintroduced `paths:` filter on ci-cd.yml (or
    on the reusable workflow a job calls) produces. The run still rolls up
    `success`; the gate must no longer call it green."""
    expected = cmg.load_ci_cd_expected_jobs()
    jobs = [j for j in _jobs_for(expected) if j["name"] != expected["plan"]]
    state = cmg.classify_pipeline([_GREEN_RUN], completed_jobs=jobs, expected_jobs=expected)
    assert state["kind"] == cmg.MISSING_JOB, state
    assert state["missing_jobs"] == ["plan"], state["missing_jobs"]
    code, message = cmg.render(state)
    assert code == 1, message
    assert "EXPECTED JOB ABSENT" in message and "`plan`" in message
    assert "#3608" in message


def test_the_reusable_workflow_rendering_is_not_a_false_absence():
    """`test` reports as `test / Unit Tests`, never as `test`. A matcher that
    only compared ids would call it absent and red every single run — the
    over-fire that would train readers to skip this gate."""
    expected = {"test": "test", "lint": "lint"}
    assert cmg.absent_expected_jobs([{"name": "test / Unit Tests"}, {"name": "lint"}], expected) == []


def test_an_unprobed_job_list_makes_no_absence_claim():
    """A gate that cannot see must not mint a verdict. `None` jobs (the `gh`
    read failed) is NOT the same as an empty job list, and must not red."""
    expected = cmg.load_ci_cd_expected_jobs()
    state = cmg.classify_pipeline([_GREEN_RUN], completed_jobs=None, expected_jobs=expected)
    assert state["kind"] == cmg.GREEN
    assert state["missing_jobs"] == []


def test_an_already_red_run_keeps_its_own_louder_verdict():
    """Precedence: a run classified RED/stranded carries recovery instructions
    this classifier would erase. The absence check only refines a GREEN."""
    red = dict(_GREEN_RUN, conclusion="failure")
    state = cmg.classify_pipeline([red], completed_jobs=[], expected_jobs=cmg.load_ci_cd_expected_jobs())
    assert state["kind"] == cmg.RED, state


def test_an_out_of_scope_commit_suppresses_the_claim():
    """If ci-cd.yml ever regains a `paths:` filter narrow enough that a commit
    misses it, an absent job IS the design. Proven with an empty changed-path
    list, which `commit_is_in_push_trigger_scope` reports out of scope."""
    expected = cmg.load_ci_cd_expected_jobs()
    state = cmg.classify_pipeline([_GREEN_RUN], completed_jobs=[], expected_jobs=expected, changed_paths=[])
    assert state["kind"] == cmg.GREEN, state
