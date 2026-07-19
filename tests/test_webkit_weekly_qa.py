"""tests/test_webkit_weekly_qa.py — #1434: the weekly ADVISORY WebKit (iOS-Safari
engine) mobile-viewport run.

Two guards:

1. The pure tier filter (visual_qa.sweep_pages) the run selects pages with:
   None = unchanged full coverage (what every existing gating run passes),
   max_tier=2 = flagship doors + live-data topic pages, missing tier = always
   included (an untiered page must never vanish from coverage by accident —
   same semantics as ai_qa_targets, #1428).

2. The structural contract of .github/workflows/webkit-mobile-qa.yml —
   text-based on purpose (CI's `test` job installs no PyYAML; same style as
   test_site_deploy_workflow.py):
     - weekly `schedule:` cron (fixed UTC, repo convention) + workflow_dispatch
     - installs the WEBKIT engine (`playwright install --with-deps webkit`)
     - drives tests/visual_qa.py with --browser webkit --mobile --max-tier 2
     - ADVISORY: no rollback scripts, no deploy scripts, no cdk deploy —
       a red here must never be able to roll back or mutate anything
     - failure surfaces loudly (if: failure() -> SNS publish; the visual-qa.yml
       pattern until the #1447 issue-on-failure helper exists)
     - upload-artifact carries continue-on-error: true (an account-wide
       artifact-quota exhaustion must not red the QA verdict —
       reference_ci_artifact_quota_rollback / #1331 class)
     - the playwright pin matches ci-cd.yml's enforced pin (CQ-01 class drift:
       a different engine version here would make a red mean something else)
"""

import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_WORKFLOW = os.path.join(_REPO, ".github", "workflows", "webkit-mobile-qa.yml")
_CI_CD = os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from visual_qa import sweep_pages  # noqa: E402

# ── 1. the tier filter ────────────────────────────────────────────────────────


def test_sweep_pages_none_is_identity():
    pages = [{"path": "/", "tier": 1}, {"path": "/x/", "tier": 4}]
    assert sweep_pages(pages, None) is pages  # unchanged object: zero risk to existing gating callers


def test_sweep_pages_max_tier_2_keeps_tier_1_and_2_drops_3_and_4():
    pages = [
        {"path": "/a/", "tier": 1},
        {"path": "/b/", "tier": 2},
        {"path": "/c/", "tier": 3},
        {"path": "/d/", "tier": 4},
    ]
    assert [p["path"] for p in sweep_pages(pages, 2)] == ["/a/", "/b/"]


def test_sweep_pages_missing_tier_always_included():
    pages = [{"path": "/untiered/"}, {"path": "/none/", "tier": None}, {"path": "/late/", "tier": 3}]
    assert [p["path"] for p in sweep_pages(pages, 1)] == ["/untiered/", "/none/"]


def test_sweep_pages_over_manifest_tier_2_is_nonempty_and_excludes_editorial():
    """Non-vacuous against the real manifest: the weekly WebKit selection must
    cover the flagship doors + live-data topic pages and exclude tier-3/4."""
    from qa_manifest import visual_pages

    pages = visual_pages()
    selected = sweep_pages(pages, 2)
    assert len(selected) >= 20, "tier<=2 selection suspiciously small — manifest tiers moved?"
    assert len(selected) < len(pages), "tier filter selected everything — tier facet missing from visual_pages()?"
    assert all(p["tier"] <= 2 for p in selected)
    assert any(p["path"] == "/cockpit/" for p in selected), "flagship door missing from the weekly WebKit selection"


# ── 2. the workflow contract ──────────────────────────────────────────────────


def _workflow_text():
    assert os.path.exists(_WORKFLOW), "webkit-mobile-qa.yml missing — the weekly WebKit run (#1434) is gone"
    with open(_WORKFLOW, encoding="utf-8") as f:
        return f.read()


def test_workflow_is_weekly_scheduled_and_dispatchable():
    text = _workflow_text()
    m = re.search(r"cron:\s*'([^']+)'", text)
    assert m, "no schedule cron in webkit-mobile-qa.yml"
    fields = m.group(1).split()
    assert len(fields) == 5
    # weekly = a specific day-of-week (not '*'), at a fixed UTC minute/hour
    assert fields[4] != "*", f"cron '{m.group(1)}' is not weekly (day-of-week is *)"
    assert fields[0].isdigit() and fields[1].isdigit(), "cron minute/hour must be fixed (UTC, repo convention)"
    assert "workflow_dispatch:" in text, "must be manually triggerable for on-demand iOS-engine checks"


def test_workflow_installs_webkit_and_drives_the_mobile_tier2_sweep():
    text = _workflow_text()
    assert re.search(r"playwright install --with-deps webkit", text), "webkit engine not installed"
    run = re.search(r"python3 tests/visual_qa\.py([^\n]*)", text)
    assert run, "workflow never invokes python3 tests/visual_qa.py"
    args = run.group(1)
    for flag in ("--browser webkit", "--mobile", "--max-tier 2"):
        assert flag in args, f"visual_qa.py invocation missing {flag}: {args.strip()}"


def test_workflow_is_advisory_no_rollback_no_deploy():
    text = _workflow_text()
    for forbidden in ("rollback_site.sh", "rollback_lambda.sh", "cdk deploy", "deploy_lambda.sh", "deploy_site_api.sh", "sync_site_to_s3"):
        assert forbidden not in text, f"advisory workflow must never contain '{forbidden}' — it gates and mutates NOTHING"


def test_workflow_failure_surfaces_loudly():
    """#1434 AC3: a red run must notify (SNS digest — the visual-qa.yml pattern),
    not just sit in the Actions history nobody reads. Replace with the #1447
    issue-on-failure helper when that lands."""
    text = _workflow_text()
    assert "if: failure()" in text, "no failure-only step — a red run would surface nowhere"
    assert "sns publish" in text, "failure step doesn't notify (sns publish missing)"


def test_workflow_artifact_upload_cannot_flip_the_verdict():
    text = _workflow_text()
    uploads = [chunk for chunk in re.split(r"\n(?=      - )", text) if "actions/upload-artifact@" in chunk]
    assert uploads, "no artifact upload — screenshots/report are the debugging evidence for a WebKit-only failure"
    for chunk in uploads:
        assert "continue-on-error: true" in chunk, "artifact upload can red the run on quota noise (#1331 class)"


def test_workflow_playwright_pin_matches_ci_gate():
    """CQ-01 class: the WebKit run must drive the SAME pinned Playwright as the
    enforced ci-cd.yml gate, or a red here can mean 'different engine version',
    not 'iOS Safari breakage'."""

    def pins(path):
        with open(path, encoding="utf-8") as f:
            return set(re.findall(r"\bplaywright==([0-9][0-9A-Za-z.\-]*)", f.read()))

    wk, ci = pins(_WORKFLOW), pins(_CI_CD)
    assert wk, "webkit-mobile-qa.yml does not pin playwright"
    assert wk <= ci, f"playwright pin drifted: webkit-mobile-qa={sorted(wk)} vs ci-cd.yml={sorted(ci)}"
