"""tests/test_site_deploy_workflow.py — #750: the site deploys through CI on merge.

Guards the structural contract of .github/workflows/site-deploy.yml (the workflow
that killed the manual-deploy drift class) and the single-owner invariant: the
in-pipeline site deploy that #393 put inside ci-cd.yml's approval-gated deploy job
is retired, so a site push can never double-deploy or sit behind the production
approval gate ("merged but not deployed" was the drift class itself).

Text-based on purpose (like test_deploy_bundle_paths.py): CI's test job installs
only pytest/boto3, so no PyYAML dependency for the load-bearing assertions.
"""

import os
import re

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_SITE_DEPLOY = os.path.join(_REPO, ".github", "workflows", "site-deploy.yml")
_CI_CD = os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def _strip_comments(text):
    """Drop full-line and trailing YAML comments so retired-machinery assertions
    don't trip on the pointer comments that document the move. Also join shell
    line-continuations so multi-line `aws` commands match as one statement."""
    text = "\n".join(re.sub(r"(^|\s)#.*$", "", line) for line in text.splitlines())
    return text.replace("\\\n", " ")


def test_site_deploy_workflow_exists_and_triggers_on_site_pushes():
    text = _read(_SITE_DEPLOY)
    assert "branches: [main]" in text, "site-deploy must fire on push to main"
    assert "'site/**'" in text, "site-deploy must be path-filtered to site/** (skip cleanly otherwise)"
    assert "workflow_dispatch" in text, "manual re-deploy of merged main must stay possible"


def test_site_deploy_has_no_manual_approval_gate():
    # The whole point of #750: a site merge deploys WITHOUT waiting on the
    # `environment: production` approval used by ci-cd.yml's deploy job.
    code = _strip_comments(_read(_SITE_DEPLOY))
    assert "environment:" not in code, "site-deploy.yml must not reintroduce an approval environment (the drift class)"


def test_site_deploy_uses_canonical_path_not_reimplemented_sync():
    code = _strip_comments(_read(_SITE_DEPLOY))
    assert "deploy/deploy_site.sh" in code, "site deploy must go through the canonical deploy_site.sh → sync_site_to_s3.sh path"
    # Never reimplement the sync: the ONLY raw `aws s3 sync` allowed here is the
    # explicit fonts companion step (additive, prefix-scoped).
    syncs = re.findall(r"aws s3 sync\s+(\S+)\s+(\S+)", code)
    assert syncs, "the explicit fonts sync step is required (sync_site_to_s3.sh excludes assets/* non-CSS/JS)"
    for src, dst in syncs:
        assert src.rstrip("/") == "site/assets/fonts", f"unexpected raw sync source {src} — use the canonical scripts"
        assert "s3://matthew-life-platform/site/assets/fonts" in dst, f"fonts sync must target the site/assets/fonts prefix, got {dst}"
    # safe_sync semantics: no --delete anywhere in this workflow, and no sync
    # targeting the bucket root.
    assert "--delete" not in code, "site-deploy.yml must never sync --delete (safe_sync semantics)"
    assert not re.search(r"s3://matthew-life-platform/?[\"'\s]", code), "no step may target the bucket root"


def test_site_deploy_wires_rollback_and_gates():
    text = _read(_SITE_DEPLOY)
    code = _strip_comments(text)
    assert "deploy/rollback_site.sh" in code, "the failure path must roll back via rollback_site.sh (#418 semantics)"
    assert '"HEAD~1"' in code, "auto-rollback restores the previous good site build (squash-merge convention)"
    assert "deploy/smoke_test_site.sh" in code, "the HTTP/content smoke gate must run post-deploy"
    assert "tests/visual_qa.py --screenshot --ai-qa" in code, "the visual/AI-QA gate must run post-deploy"
    assert "tests/accuracy_audit.py --live" in code, "the accuracy gate must run post-deploy"
    assert "sns publish" in code, "rollback/failure must alert via SNS"
    # Rollback fires only after a successful deploy, on a failed gate.
    assert "needs.deploy-site.result == 'success'" in text
    assert "needs.smoke.result == 'failure'" in text
    assert "needs.visual-qa.result == 'failure'" in text


#: Local composites whose contents pin a TOOLCHAIN, and therefore must be referenced in
#: lockstep across workflows. Everything else local is version-free by construction.
_TOOLCHAIN_LOCAL_ACTIONS = {"./.github/actions/setup-ci"}


def test_site_deploy_uses_same_pinned_actions_as_ci_cd():
    """Action SHAs must match ci-cd.yml exactly, so pin bumps happen in lockstep."""
    site, ci = _read(_SITE_DEPLOY), _read(_CI_CD)
    uses = set(re.findall(r"uses:\s*(\S+)", site))
    assert uses, "no pinned actions found in site-deploy.yml"
    for ref in uses:
        action, _, sha = ref.partition("@")
        if action.startswith("./"):
            # Local composite action (#1655) — pinned by tree, not by SHA, so the only
            # thing that CAN drift is a pinned toolchain, and exactly one local composite
            # owns one: setup-ci (python + aws-credentials + ci_pins for every caller).
            # #3352: ./.github/actions/advisory-failure-issue pins nothing (stdlib python3
            # on the runner) and is already shared by advisory workflows ci-cd.yml has
            # never used — requiring ci-cd.yml to reference it would enforce nothing and
            # block the intended reuse. So lockstep applies to the toolchain composite.
            if ref in _TOOLCHAIN_LOCAL_ACTIONS:
                assert ref in ci, f"{ref} local action must be referenced in lockstep with ci-cd.yml"
            continue
        assert re.fullmatch(r"[0-9a-f]{40}", sha), f"{action} is not SHA-pinned in site-deploy.yml"
        assert ref in ci, f"{ref} is pinned differently from ci-cd.yml — bump the pins in lockstep"
    assert "role/github-actions-deploy-role" in site, "must assume the standard OIDC deploy role"


def test_site_deploy_playwright_pin_matches_ci_cd():
    """visual-qa steps are mirrored across ci-cd.yml / visual-qa.yml / site-deploy.yml —
    the Playwright version must not drift between the copies (CQ-01 class).

    #2609 removed the drift rather than comparing it: no workflow carries a version any
    more, all three resolve playwright from requirements-dev.txt via scripts/ci_pins.py.
    So the assertion is identity of source plus the absence of a re-introduced literal,
    which is strictly stronger than the old set-subset comparison.
    """

    def resolves_playwright(path):
        return [args for args in re.findall(r"ci_pins\.py([^)\n]*)", _read(path)) if "playwright" in args.split()]

    def literals(path):
        return sorted(set(re.findall(r"playwright==([0-9][0-9A-Za-z.\-]*)", _read(path))))

    assert resolves_playwright(_SITE_DEPLOY), "site-deploy.yml no longer resolves playwright from requirements-dev.txt (#2609)"
    assert resolves_playwright(_CI_CD), "ci-cd.yml no longer resolves playwright from requirements-dev.txt (#2609)"
    for path, name in ((_SITE_DEPLOY, "site-deploy.yml"), (_CI_CD, "ci-cd.yml")):
        assert not literals(
            path
        ), f"{name} hardcodes a playwright version again ({literals(path)}) — resolve it instead, or the copies can drift (#2609)"


def test_ci_cd_no_longer_owns_the_site_deploy():
    """Single-owner invariant: if the #393 machinery reappears in ci-cd.yml, a site
    push would deploy twice (once ungated, once behind the approval gate)."""
    code = _strip_comments(_read(_CI_CD))
    assert "deploy/deploy_site.sh" not in code, "ci-cd.yml deploys the site again — #750 moved that to site-deploy.yml"
    assert "deploy/rollback_site.sh" not in code, "ci-cd.yml rolls back the site again — #750 moved that to site-deploy.yml"
    assert "site_changed" not in code, "site_changed detection is back in ci-cd.yml — retire it or retire site-deploy.yml"


def test_site_deploy_yaml_parses_and_needs_resolve():
    yaml = pytest.importorskip("yaml")  # not in CI's minimal test env; runs locally/dev
    doc = yaml.safe_load(_read(_SITE_DEPLOY))
    jobs = doc["jobs"]
    expected = {"deploy-site", "smoke", "visual-qa", "rollback-site-on-failure", "notify-deploy-failure"}
    assert expected <= set(jobs), f"jobs drifted: {sorted(jobs)}"
    for name, job in jobs.items():
        needs = job.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        for n in needs:
            assert n in jobs, f"job {name} needs unknown job {n}"
    # Both trigger forms present (yaml parses `on:` as True).
    on = doc.get("on") or doc.get(True)
    assert "push" in on and "workflow_dispatch" in on


# ── #3352: the rollback scope check ──────────────────────────────────────────────
#
# The rollback used to run `deploy/rollback_site.sh` unconditionally on any gate red.
# Two measured incidents where that reached nothing and reported success:
#   • 2026-08-31 P1 — the /data/* door was served application/json by a step-ordering
#     defect in sync_site_to_s3.sh; the rollback re-ran that same script and re-broke it.
#   • 2026-08-27 (Session G) — it reverted a wanted published build beat over a
#     DynamoDB-sourced defect it was structurally incapable of fixing.
# These are text-based for the same reason as everything above: CI's test job has no
# PyYAML, and a guard that only runs locally is not a guard.


def _step_block(text, step_name):
    """The lines of one workflow step, from its `- name: <step_name>` to the next
    step at the same indentation. Text-based (no PyYAML) on purpose."""
    lines = text.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("- name:") and step_name in ln)
    indent = len(lines[start]) - len(lines[start].lstrip())
    out = [lines[start]]
    for ln in lines[start + 1 :]:
        stripped = ln.strip()
        if stripped.startswith("- name:") and (len(ln) - len(ln.lstrip())) <= indent:
            break
        out.append(ln)
    return "\n".join(out)


def test_visual_qa_exports_a_machine_readable_surface_verdict():
    text = _read(_SITE_DEPLOY)
    assert "tests/visual_qa_verdict.py" in text, "the visual-QA job must classify the failing surface (#3352)"
    for output in ("site_reachable:", "surfaces:", "summary:"):
        assert output in text, f"visual-qa must export {output} for the rollback's scope check"
    # A job output can only be set by a step that RAN — if the classifier sat behind the
    # sweep's success it would be absent exactly when it matters (every failing run).
    verdict_step = _step_block(text, "Classify the failing surface")
    assert "if: always()" in verdict_step, "the classifier must run even when the sweep failed — that is the only case it exists for"
    assert "id: verdict" in verdict_step


def test_the_rollback_is_guarded_by_the_verdict_and_cannot_re_run_the_deploy_script():
    """Box 6 of #3352: when the verdict says the failing surface is not site/**-reachable,
    `rollback_site.sh` (which re-runs the canonical sync_site_to_s3.sh) must NOT run."""
    text = _read(_SITE_DEPLOY)
    step = _step_block(text, "Roll back site to previous build")
    assert "needs.visual-qa.outputs.site_reachable" in step, "the rollback must read the scope verdict"
    guard = step.index('SITE_REACHABLE:-}" = "false"')
    exit_early = step.index("exit 0", guard)
    rollback = step.index("bash deploy/rollback_site.sh", guard)
    assert exit_early < rollback, "the declined path must exit BEFORE rollback_site.sh — re-running the sync re-runs the P1 defect"
    # The decision is a bash `if` inside the step, never a job-level `if:` — a skipped
    # job is indistinguishable from "nothing failed", which is the class this fixes.
    job = text.split("rollback-site-on-failure:", 1)[1].split("\n  resolve-gate-unreachable-issue:", 1)[0]
    header = job.split("steps:", 1)[0]
    assert "site_reachable" not in header, "the scope check must not be a job-level if: (a skipped job says nothing)"


def test_a_declined_rollback_alerts_by_name_instead_of_silently_skipping():
    text = _read(_SITE_DEPLOY)
    assert "site-deploy-gate-unreachable" in text, "a declined rollback must file the #1447 tracked issue"
    assert "./.github/actions/advisory-failure-issue" in text
    assert "issues: write" in text, "the #1447 filer needs the GitHub token scope (not an IAM change)"
    assert "Rollback: DECLINED (surface=" in text, "the SNS alert must say DECLINED with the surface, never 'AUTO-ROLLBACK'"
    # ...and the auto-filed issue's own close policy ("auto-closes on the next green run
    # of this workflow") must be implemented, not merely claimed.
    assert "resolve-gate-unreachable-issue:" in text
    assert "job-status: success" in text


def test_only_a_workflow_dispatch_can_inject_a_synthetic_failure():
    """#3352 box 3's live-proof hook. `github.event.inputs.*` is empty on a push, so a
    merge can never inject — but only if that is the ONLY source of the env var."""
    text = _read(_SITE_DEPLOY)
    assert "qa_inject_failure:" in text, "the live-proof dispatch input is missing"
    sources = re.findall(r"VISUAL_QA_INJECT_SURFACE:\s*(.+)", text)
    assert sources, "the sweep must receive the injection choice through VISUAL_QA_INJECT_SURFACE"
    for src in sources:
        assert src.strip() == "${{ github.event.inputs.qa_inject_failure }}", f"injection reachable from a non-dispatch source: {src}"
    # The input lives under workflow_dispatch, never under `on.push`.
    push_block = text.split("  push:", 1)[1].split("  workflow_dispatch:", 1)[0]
    assert "qa_inject_failure" not in push_block
