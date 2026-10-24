"""tests/test_workflow_needs_status_guard_5298.py — a job downstream of a skippable job carries a status function (#5298).

GitHub Actions gives a job with no status function in its ``if:`` an implicit ``success()``, and
``success()`` is false when ANY job in the transitive ``needs`` chain was skipped — not only the jobs
the condition names. After the deploy-iam split (ADR-158), ``deploy-iam`` is skipped on every push
with no additive-IAM grant, and ``deploy`` still ran (its ``if:`` opens with ``!cancelled()``), but
``smoke-test`` and ``visual-qa`` (no ``if:``) and ``post-deploy-checks`` (``if:
needs.deploy.result == 'success'``, no status function) were skipped on every such deploy for
about three weeks. Auto-rollback keys on a smoke FAILURE, so it was effectively off too.

The class, not the specimen: for every workflow under .github/workflows, a job whose transitive
``needs`` includes a job that CAN be skipped (one carrying its own ``if:``) must put a status
function — ``always()``, ``!cancelled()``/``cancelled()``, ``success()`` or ``failure()`` — in its
own ``if:``. A job that genuinely wants "skip me when anything upstream skipped" writes
``success()`` explicitly, which says so.
"""

# premerge-gate: a repo-shape gate over every .github/workflows/*.yml — a job that loses its status function skips every post-deploy safety job silently, and nothing downstream of the merge can see a job that never ran (#5298).

import pathlib
import re

import yaml

_REPO = pathlib.Path(__file__).resolve().parent.parent
_WF = _REPO / ".github" / "workflows"
_STATUS_FN = re.compile(r"\b(always|cancelled|success|failure)\s*\(")
# The specimen jobs #5298 fixed — each must still be found downstream of a skippable job, so the
# sweep cannot go blind by a rename or a restructure that drops the chain.
_SPECIMENS = ("smoke-test", "visual-qa", "post-deploy-checks")


def _needs(job: dict) -> list:
    n = (job or {}).get("needs") or []
    return [n] if isinstance(n, str) else list(n)


def skippable_ancestors(jobs: dict, name: str) -> set:
    """Every job in `name`'s transitive needs chain that carries its own `if:` (so can be skipped)."""
    seen: set = set()
    stack = _needs(jobs.get(name))
    while stack:
        dep = stack.pop()
        if dep in seen or dep not in jobs:
            continue
        seen.add(dep)
        stack.extend(_needs(jobs[dep]))
    return {d for d in seen if "if" in (jobs[d] or {})}


def offenders_in(doc: dict, label: str) -> list:
    jobs = (doc or {}).get("jobs") or {}
    out = []
    for name, job in jobs.items():
        skippable = skippable_ancestors(jobs, name)
        if not skippable:
            continue
        cond = str((job or {}).get("if", ""))
        if not _STATUS_FN.search(cond):
            out.append(
                f"{label}::{name}: needs-chain includes skippable {sorted(skippable)} but its if: "
                f"{cond!r} has no status function — the implicit success() skips it whenever one of "
                f"those is skipped (write `!cancelled() && ...`, #5298)"
            )
    return out


def _workflows() -> list:
    return sorted(_WF.glob("*.yml"))


def test_every_job_below_a_skippable_job_carries_a_status_function():
    files = _workflows()
    assert len(files) >= 20, f"only {len(files)} workflows found under {_WF} — the sweep has gone blind"
    bad = []
    for path in files:
        bad.extend(offenders_in(yaml.safe_load(path.read_text(encoding="utf-8")), path.name))
    assert not bad, "jobs that a skipped ancestor silently skips:\n  " + "\n  ".join(bad)


def test_the_specimen_jobs_are_still_in_scope_and_run_on_a_successful_deploy():
    jobs = yaml.safe_load((_WF / "ci-cd.yml").read_text(encoding="utf-8"))["jobs"]
    assert "if" in jobs["deploy-iam"], "deploy-iam no longer carries an if: — re-read #5298 before deleting this test"
    for name in _SPECIMENS:
        assert "deploy-iam" in skippable_ancestors(jobs, name), f"{name}: deploy-iam left its needs chain — the sweep lost its specimen"
        cond = re.sub(r"\s+", " ", str(jobs[name].get("if", "")))
        assert "!cancelled()" in cond and "needs.deploy.result == 'success'" in cond, f"{name}: if: {cond!r}"


def test_the_detector_reds_on_the_incident_shape_and_greens_on_the_fix():
    incident = {
        "jobs": {
            "plan": {},
            "deploy-iam": {"needs": "plan", "if": "x == 'y'"},
            "deploy": {"needs": ["plan", "deploy-iam"], "if": "!cancelled() && needs.plan.result == 'success'"},
            "smoke": {"needs": ["deploy"]},
            "checks": {"needs": ["deploy"], "if": "needs.deploy.result == 'success'"},
            "rollback": {"needs": ["smoke"], "if": "always() && needs.smoke.result == 'failure'"},
            "unrelated": {"needs": ["plan"]},
        }
    }
    got = offenders_in(incident, "synthetic")
    assert [o.split(":")[2] for o in got] == ["smoke", "checks"], got
    for j in ("smoke", "checks"):
        incident["jobs"][j]["if"] = "${{ !cancelled() && needs.deploy.result == 'success' }}"
    assert offenders_in(incident, "synthetic") == []
