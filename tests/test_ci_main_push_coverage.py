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
