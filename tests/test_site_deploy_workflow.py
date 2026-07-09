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


def test_site_deploy_uses_same_pinned_actions_as_ci_cd():
    """Action SHAs must match ci-cd.yml exactly, so pin bumps happen in lockstep."""
    site, ci = _read(_SITE_DEPLOY), _read(_CI_CD)
    uses = set(re.findall(r"uses:\s*(\S+)", site))
    assert uses, "no pinned actions found in site-deploy.yml"
    for ref in uses:
        action, _, sha = ref.partition("@")
        assert re.fullmatch(r"[0-9a-f]{40}", sha), f"{action} is not SHA-pinned in site-deploy.yml"
        assert ref in ci, f"{ref} is pinned differently from ci-cd.yml — bump the pins in lockstep"
    assert "role/github-actions-deploy-role" in site, "must assume the standard OIDC deploy role"


def test_site_deploy_playwright_pin_matches_ci_cd():
    """visual-qa steps are mirrored across ci-cd.yml / visual-qa.yml / site-deploy.yml —
    the Playwright pin must not drift between the copies (CQ-01 class)."""
    site_pins = set(re.findall(r"playwright==([0-9][0-9A-Za-z.\-]*)", _read(_SITE_DEPLOY)))
    ci_pins = set(re.findall(r"playwright==([0-9][0-9A-Za-z.\-]*)", _read(_CI_CD)))
    assert site_pins, "playwright not pinned in site-deploy.yml"
    assert site_pins <= ci_pins, f"playwright pin drifted: site-deploy={sorted(site_pins)} vs ci-cd={sorted(ci_pins)}"


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
