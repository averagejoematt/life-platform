"""#3378 — every push to main must mint a real CI verdict.

THE DEFECT THIS HOLDS SHUT. ci-cd.yml used to carry a `paths:` filter enumerating the
"code-ish" surface. A push touching only an unlisted path minted no run, and because the
branch badge shows the last *verdict*, that tip INHERITED the previous commit's green.
Absence of a run rendered as absence of a problem — the class docs/INCIDENT_LOG.md calls
"absence read as success". Three measured instances, the last of which is why this file
exists (59773c2d4, 2026-09-01: a docs-only wrap left INCIDENT_LOG's derived Patterns
section stale, because the `--apply` that regenerates it lives in ci-cd's `reconcile` job
which the filter skipped, while the `--check` that asserts it lives in docs-ci.yml which
the filter did not).

WHY A TEST RATHER THAN A COMMENT. Every previous version of that list was wrong in the
same direction — DEVOPS-01 (2026-06-30) added cdk/ci/config/workflows after IAM and alarm
changes reached main with no pipeline; #2881 (2026-08-18) added deploy/ after the file
that gates every site deploy earned exactly one workflow run. `scripts/**` was never on it
at all, though ci-cd's own lint job black-checks that directory. The list IS the defect, so
re-adding one has to red here rather than look like tidying.

The other three assertions are the COST invariants the removal rests on. Without them,
"removing the filter is free" quietly stops being true: a `deploy` job that no longer gates
on has_deploys would deploy on every docs push, and a `visual-qa` job detached from
`deploy` would fire the Bedrock vision pass (~$0.05/run, and 15min) on every wrap.
"""

from pathlib import Path

import pytest

# The deploy-critical lane installs only pytest/boto3/botocore/hypothesis, and a
# module-scope third-party import there crashes COLLECTION for the whole lane, not just
# this file (#2699/#2732). The full suite has PyYAML and runs every assertion below.
yaml = pytest.importorskip("yaml")

ROOT = Path(__file__).resolve().parents[1]
CI_CD = ROOT / ".github" / "workflows" / "ci-cd.yml"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _filters_on(push: dict) -> list[str]:
    """THE predicate. Both the live assertion and its negative control call this one
    function — a control that re-implements the check proves only that the copy agrees
    with itself (docs/INCIDENT_LOG.md, the vacuous-negative-control class)."""
    return sorted(k for k in ("paths", "paths-ignore") if k in push)


def _push_trigger(doc: dict) -> dict:
    # PyYAML resolves the bare key `on:` to the boolean True (YAML 1.1 truthiness).
    on = doc.get("on", doc.get(True))
    assert on is not None, "ci-cd.yml has no `on:` trigger block"
    return on["push"]


def test_ci_cd_push_to_main_carries_no_path_filter():
    push = _push_trigger(_load(CI_CD))
    assert push["branches"] == ["main"]
    offenders = _filters_on(push)
    assert not offenders, (
        f"ci-cd.yml's push trigger re-acquired {offenders} — #3378. A path filter on main "
        "means some pushes mint no verdict and inherit the previous commit's badge. If a "
        "narrower trigger is genuinely wanted, that is an ADR, not an edit: read the "
        "rationale block above the trigger first."
    )


def test_the_filter_assertion_can_actually_fail():
    """Negative control (#2578) — the check above must reject a filtered trigger.

    A shape assertion that has only ever been run against the shape it wants is not yet
    evidence. This drives the same predicate over a synthetic filtered trigger and
    requires it to be rejected.
    """
    assert _filters_on({"branches": ["main"], "paths": ["lambdas/**"]}) == [
        "paths"
    ], "the predicate cannot see a `paths:` filter — it proves nothing"
    assert _filters_on({"branches": ["main"], "paths-ignore": ["docs/**"]}) == [
        "paths-ignore"
    ], "the predicate cannot see a `paths-ignore:` filter"
    # Positive control: the shape the live workflow is asserted to have must pass.
    assert _filters_on({"branches": ["main"]}) == []


def test_deploy_still_gates_on_has_deploys():
    """Cost invariant: an unfiltered trigger must not start deploying on docs pushes."""
    deploy = _load(CI_CD)["jobs"]["deploy"]
    cond = deploy.get("if") or ""
    assert "needs.plan.outputs.has_deploys == 'true'" in cond, (
        "ci-cd's `deploy` job no longer gates on has_deploys. With no path filter on main "
        "(#3378) that gate is the only thing keeping a docs-only push from reaching the "
        "production approval gate."
    )


def test_visual_qa_stays_downstream_of_deploy():
    """Cost invariant: the Bedrock vision pass must not fire on a push that deploys nothing.

    It is skipped today because a skipped dependency skips the dependent — `needs: deploy`
    with no `always()`. Either half of that removed, and every wrap commit buys a 15-minute
    AI gate run.
    """
    job = _load(CI_CD)["jobs"]["visual-qa"]
    assert "deploy" in (job.get("needs") or []), "visual-qa no longer needs `deploy` — #3378 cost invariant"
    cond = job.get("if") or ""
    assert "always()" not in cond, (
        "visual-qa gained an `always()` condition, so it now runs even when `deploy` is "
        "skipped — i.e. on every docs-only push to main. #3378's cost basis assumed it does not."
    )


# ─────────────────────────────────────────────────────────────────────────────
# #4252 — one full-suite verdict per sha. `scripts/find_test_verdict_owner.py` lets a run
# skip its 33-min unit-test pass ONLY when build_sha is a later push with its own CI/CD
# run. Every case below is a real sha pair from main's 2026-09-27 history.
# ─────────────────────────────────────────────────────────────────────────────
import importlib.util  # noqa: E402
import sys  # noqa: E402

_spec = importlib.util.spec_from_file_location("find_test_verdict_owner", ROOT / "scripts" / "find_test_verdict_owner.py")
owner_mod = importlib.util.module_from_spec(_spec)
sys.modules["find_test_verdict_owner"] = owner_mod  # a @dataclass resolves its module by name
_spec.loader.exec_module(owner_mod)
RunInfo = owner_mod.RunInfo

_WF = ".github/workflows/ci-cd.yml"
_H_76A, _B_62B = "76a4a554f" + "0" * 31, "62bd98a71" + "0" * 31
_H_306, _B_440 = "306e29780" + "0" * 31, "440eabc46" + "0" * 31


def _run(run_id, head, status="in_progress", concl=None, event="push", path=_WF):
    return RunInfo(run_id=run_id, head_sha=head, event=event, path=path, status=status, unit_tests_conclusion=concl)


def _decide(decide, **kw):
    base = dict(event="push", head_sha=_H_76A, build_sha=_B_62B, run_id=36349231787, candidates=[])
    base.update(kw)
    return decide(**base)[0]


def _assert_rule(decide):
    """THE predicate both the live assertion and the mutation control drive."""
    # FIRES: 76a4a554f's run reconciled to the tip 62bd98a71, whose own push run exists.
    assert _decide(decide, candidates=[_run(36349258182, _B_62B)]) == 36349258182
    assert _decide(decide, candidates=[_run(36349258182, _B_62B, "completed", "failure")]) == 36349258182
    # DOES NOT FIRE — the run is testing its own head (62bd98a71's own run).
    assert _decide(decide, head_sha=_B_62B, candidates=[_run(36349258182, _B_62B)]) is None
    # DOES NOT FIRE — build_sha has no push run: 440eabc46 (#4350) was a GITHUB_TOKEN
    # Dependabot merge that minted none; 306e29780's run was its only tester.
    assert _decide(decide, head_sha=_H_306, build_sha=_B_440, candidates=[]) is None
    # DOES NOT FIRE — the only candidate is a different sha, a different workflow, or
    # not a push.
    assert _decide(decide, candidates=[_run(1, _H_306)]) is None
    assert _decide(decide, candidates=[_run(1, _B_62B, path=".github/workflows/docs-ci.yml")]) is None
    assert _decide(decide, candidates=[_run(1, _B_62B, event="workflow_dispatch")]) is None
    # DOES NOT FIRE — the owner ended without a Unit Tests verdict (its reconcile failed).
    assert _decide(decide, candidates=[_run(1, _B_62B, "completed", "skipped")]) is None
    assert _decide(decide, candidates=[_run(1, _B_62B, "completed", None)]) is None
    # DOES NOT FIRE — a manual dispatch always tests.
    assert _decide(decide, event="workflow_dispatch", candidates=[_run(36349258182, _B_62B)]) is None


def test_verdict_owner_rule_fires_only_on_an_owned_later_sha():
    _assert_rule(owner_mod.decide)


def test_verdict_owner_rule_mutation_control():
    """Negative control: a rule that skips whenever the sha moved (no owner lookup) must red."""

    def skip_whenever_sha_moved(*, event, head_sha, build_sha, run_id, candidates):
        return (1, "") if event == "push" and build_sha != head_sha else (None, "")

    with pytest.raises(AssertionError):
        _assert_rule(skip_whenever_sha_moved)


def test_verdict_owner_fails_open_to_testing(monkeypatch, tmp_path):
    """A lookup error must leave owner_run EMPTY (the suite runs), and exit 0."""

    def boom(*a, **k):
        raise RuntimeError("api down")

    out = tmp_path / "out"
    monkeypatch.setattr(owner_mod, "fetch_candidates", boom)
    monkeypatch.setattr(owner_mod, "POLL_ATTEMPTS", 1)
    for k, v in dict(GITHUB_EVENT_NAME="push", GITHUB_SHA=_H_76A, BUILD_SHA=_B_62B, GITHUB_OUTPUT=str(out)).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert owner_mod.main() == 0
    assert out.read_text() == "owner_run=\n"


def test_unit_tests_job_is_skipped_only_by_an_owner():
    """Workflow shape: the caller `test` job stays UNCONDITIONAL (so check_main_green's
    #3608 expected-job set still holds it, and a skip attaches as `skipped`, never absent);
    the only skip is ci-test.yml's job-level `if:` on the owner input. The deploy chain
    never waits on `test-owner`."""
    jobs = _load(CI_CD)["jobs"]
    assert "if" not in jobs["test"], "ci-cd `test` must stay unconditional (#4252 / #3608)"
    assert "test-owner" in jobs["test"]["needs"]
    assert jobs["test"]["with"]["owner_run"] == "${{ needs.test-owner.outputs.owner_run }}"
    inner = _load(CI_CD.parent / "ci-test.yml")["jobs"]["test"]
    assert inner.get("if") == "inputs.owner_run == ''", "ci-test.yml's Unit Tests must skip ONLY on an owner"
    for gated in ("test-critical", "plan", "deploy"):
        needs = jobs[gated].get("needs") or []
        assert "test-owner" not in (needs if isinstance(needs, list) else [needs]), f"{gated} must not wait on test-owner"


# ── #4252 box 5 — push concurrency on the full suite ──────────────────────────────
# A burst of pushes must not run one full suite per push, and the only runs allowed to
# evict one are runs that will really test. The group expression is EVALUATED below (a
# minimal translation of the GitHub expression to Python), not just string-matched.


def _eval_gh_expr(expr: str, ctx: dict) -> str:
    import re

    body = expr.strip()
    assert body.startswith("${{") and body.endswith("}}"), expr
    body = body[3:-2].strip()
    for name, value in ctx.items():
        body = body.replace(name, repr(value))
    body = body.replace("&&", " and ").replace("||", " or ")
    body = re.sub(r"\bformat\(", "_fmt(", body)
    return eval(body, {"_fmt": lambda f, *a: f.format(*a)})  # noqa: S307 - a test-only, repo-controlled string


def _test_group(event: str, owner_run: str, run_id: str) -> str:
    conc = _load(CI_CD)["jobs"]["test"]["concurrency"]
    ctx = {
        "github.event_name": event,
        "needs.test-owner.outputs.owner_run": owner_run,
        "github.run_id": run_id,
        "github.ref": "refs/heads/main",
    }
    return _eval_gh_expr(conc["group"], ctx)


def test_only_a_testing_push_run_joins_the_shared_unit_test_group():
    conc = _load(CI_CD)["jobs"]["test"]["concurrency"]
    assert conc["cancel-in-progress"] is True
    shared = _test_group("push", "", "101")
    assert shared == _test_group("push", "", "202"), "two testing push runs must share one group (the newer evicts the older)"
    assert "101" not in shared
    skipping = _test_group("push", "99", "101")
    assert skipping != shared and "101" in skipping, "a run that SKIPS (owner elsewhere) must never evict a run that is testing"
    dispatch = _test_group("workflow_dispatch", "", "101")
    assert dispatch != shared and "101" in dispatch, "a dispatch tests on its own and evicts nothing"


def test_push_concurrency_never_reaches_the_deploy_chain():
    jobs = _load(CI_CD)["jobs"]
    assert jobs["deploy"]["concurrency"]["cancel-in-progress"] is False, "a mid-flight deploy must complete"
    for job in ("reconcile", "lint", "test-critical", "test-owner", "plan", "deploy-iam"):
        assert "concurrency" not in jobs[job], f"{job} must not queue behind or be evicted by another run"
    assert "github.run_id" in _load(CI_CD)["concurrency"]["group"], "the workflow-level group stays run-unique"
