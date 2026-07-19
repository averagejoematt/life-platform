#!/usr/bin/env python3
"""
deploy/drift_sentinel.py — weekly "live state vs. code" drift sentinel (#394).

CI's `cdk diff --all` compares the CDK app to the deployed *template* — it is blind to
drift that happens OUT of band: a resource edited in the console, a stack resource
deleted, a Lambda config mutated by hand, a bucket policy loosened. This closes that
gap with a read-only sweep that a human never has to remember to run.

What it checks (all read-only; CloudFormation drift-detection API calls are free):

  1. CFN DRIFT — `detect_stack_drift` across all 9 stacks, then reports every
     MODIFIED / DELETED resource (`describe_stack_resource_drifts`). This is the live
     state vs. the deployed template, which `cdk diff` cannot see.
  2. POSTFLIGHT REUSE — the human-invoked-only checks from session_postflight:
     layer retirement (#781: zero shared-utils references), lambda config
     drift, bundled-asset completeness.
  3. NO FUNCTIONS OUTSIDE IaC — every live Lambda in the region must be a member of one
     of our CloudFormation stacks. A function that exists live but in no stack's
     resource list was created out of band (orphan) — surfaced, minus a small allowlist
     of CDK-toolkit infra.
  4. BUCKET-POLICY DELETE-PROTECTION — the `ProtectDataFromDeployScripts` Deny statement
     that guards raw data (raw/*, config/*, uploads/*, …) is verified live against the
     source of truth (deploy/bucket_policy.json). A loosened or dropped Deny is loud.
  5. SITE/MAIN SHA ANCESTRY (#751) — the live https://averagejoematt.com/version.json
     build SHA must be an ancestor of (or equal to) origin/main HEAD. CI's I22
     (tests/test_integration_aws.py::test_i22_site_version_sha_on_main) checks this
     right after a deploy; this is the STANDING scheduled version that catches
     out-of-band drift BETWEEN deploys (no new always-on infra — read-only HTTPS GET
     + local `git merge-base --is-ancestor`).
  6. GITHUB CONFIG POSTURE (#1320, epic #1355) — GET-only `gh api` asserts of the
     GitHub-side controls the docs make claims about, against the checked-in
     documented posture in deploy/github_posture.json: `production` environment
     protection (the #1319 dead-approval-gate class), the `main` branch ruleset
     (id 19162901: force-push + deletion blocks, #1325), and vulnerability/
     Dependabot-alert enablement (ADR-082's CVE-remediation channel). Never
     mutates GitHub. Fail-soft on token-scope gaps: an unreadable surface reports
     an honest "credential lacks scope X" needs-owner line (with the exact
     fine-grained-PAT permission to add), never a red.
  7. MAIN-PUSH RUN LIVENESS (#1544) — push-event workflow runs stopped QUEUING
     for six consecutive merges on 2026-07-19 (~3h, not red — ABSENT). This
     compares /commits on main vs /actions/runs?event=push: a trigger-matching
     merge older than the grace window with no queued run is the alarm. Path-
     filter aware (a commit touching only e.g. handovers/ legitimately triggers
     nothing — see PUSH_TRIGGER_GLOBS).

Output: a findings record written to s3://<bucket>/drift-log/{latest,<date>}.json
(mirrors the Coherence Sentinel's coherence-log pattern) so the remediation agent can
ingest it into its curated report — and a loud human summary to stdout. A clean week
reports explicitly clean; it is never silent.

This runs as a STEP in an existing scheduled workflow (the remediation agent, weekly on
Mondays) with the remediation role's read-only access — NO new always-on infrastructure.

Run locally (needs read-only AWS creds):
    python3 deploy/drift_sentinel.py            # write the record, exit 0
    python3 deploy/drift_sentinel.py --strict   # exit non-zero if drift/degraded (CI gate)
    python3 deploy/drift_sentinel.py --no-write  # print only, don't touch S3
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

REGION = os.environ.get("AWS_REGION", "us-west-2")
BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The 9 CDK stacks and the region each deploys to (Web is us-east-1 for CloudFront).
# Source of truth: cdk/app.py.
STACKS = {
    "LifePlatformCore": REGION,
    "LifePlatformIngestion": REGION,
    "LifePlatformCompute": REGION,
    "LifePlatformEmail": REGION,
    "LifePlatformOperational": REGION,
    "LifePlatformServe": REGION,
    "LifePlatformMcp": REGION,
    "LifePlatformMonitoring": REGION,
    "LifePlatformWeb": "us-east-1",
}

# Live Lambdas that are legitimately not one of OUR create_platform_lambda functions:
# CDK toolkit / bootstrap infra and provider framework functions. A live function whose
# name starts with one of these is not treated as an out-of-IaC orphan.
_ORPHAN_ALLOW_PREFIXES = (
    "cdk-hnb659fds-",  # CDK bootstrap (asset publishing, image build)
    "StackSet-",  # StackSets admin
)

_DRIFT_STATUSES = ("MODIFIED", "DELETED")


def _client(service, region=REGION):
    import boto3

    return boto3.client(service, region_name=region)


# ── 1. CloudFormation drift ──────────────────────────────────────────────────


def check_cfn_drift(per_stack_timeout=180):
    """detect_stack_drift on each stack, then collect MODIFIED/DELETED resources.

    Fail-soft per stack: a stack that errors or times out is recorded as an error, not a
    crash. Returns {"status": clean|drift|degraded, "stacks": {name: {...}}}."""
    out = {}
    saw_drift = False
    saw_error = False
    # Group stacks by region so we reuse one client per region.
    by_region: dict[str, list[str]] = {}
    for name, region in STACKS.items():
        by_region.setdefault(region, []).append(name)

    for region, names in by_region.items():
        try:
            cfn = _client("cloudformation", region)
        except Exception as e:  # noqa: BLE001
            for name in names:
                out[name] = {"status": "error", "detail": f"client init: {e}"}
            saw_error = True
            continue
        for name in names:
            try:
                det = cfn.detect_stack_drift(StackName=name)["StackDriftDetectionId"]
                status = _poll_drift(cfn, det, per_stack_timeout)
                if status is None:
                    out[name] = {"status": "error", "detail": "detection timed out"}
                    saw_error = True
                    continue
                if status.get("DetectionStatus") == "DETECTION_FAILED":
                    out[name] = {"status": "error", "detail": status.get("DetectionStatusReason", "detection failed")}
                    saw_error = True
                    continue
                if status.get("StackDriftStatus") != "DRIFTED":
                    out[name] = {"status": "clean", "drift_status": status.get("StackDriftStatus", "IN_SYNC")}
                    continue
                resources = _drifted_resources(cfn, name)
                out[name] = {"status": "drift", "drifted": resources}
                saw_drift = True
            except Exception as e:  # noqa: BLE001 — surface as error, never crash the sweep
                out[name] = {"status": "error", "detail": str(e)[:300]}
                saw_error = True

    status = "drift" if saw_drift else ("degraded" if saw_error else "clean")
    # #1227: a DEAD capability must not report as a soft "degraded". If every stack
    # errored AND every error is an AccessDenied, the cfn_drift check is dead-on-arrival
    # (a missing IAM action, not a transient) — escalate to a first-class "error" so it
    # surfaces as needs-human instead of being buried in "degraded" behind continue-on-
    # error. The IAM-parity lesson: verify the capability, don't report a dead one soft.
    if (
        out
        and all(v.get("status") == "error" for v in out.values())
        and all("AccessDenied" in (v.get("detail") or "") for v in out.values())
    ):
        status = "error"
        return {"status": status, "stacks": out, "dead_capability": "all stacks AccessDenied (missing IAM action)"}
    return {"status": status, "stacks": out}


def _poll_drift(cfn, detection_id, timeout):
    """Poll describe_stack_drift_detection_status until complete/failed or timeout."""
    waited = 0
    interval = 5
    while waited < timeout:
        st = cfn.describe_stack_drift_detection_status(StackDriftDetectionId=detection_id)
        if st.get("DetectionStatus") in ("DETECTION_COMPLETE", "DETECTION_FAILED"):
            return st
        time.sleep(interval)
        waited += interval
    return None


def _drifted_resources(cfn, stack):
    """List MODIFIED/DELETED resources for a drifted stack (paginated)."""
    drifted = []
    token = None
    while True:
        kw = {"StackName": stack, "StackResourceDriftStatusFilters": list(_DRIFT_STATUSES)}
        if token:
            kw["NextToken"] = token
        resp = cfn.describe_stack_resource_drifts(**kw)
        for d in resp.get("StackResourceDrifts", []):
            drifted.append(
                {
                    "logical_id": d.get("LogicalResourceId"),
                    "type": d.get("ResourceType"),
                    "drift": d.get("StackResourceDriftStatus"),
                    "physical_id": d.get("PhysicalResourceId"),
                }
            )
        token = resp.get("NextToken")
        if not token:
            break
    return drifted


# ── 2. Postflight reuse (layer / config / asset) ─────────────────────────────


def check_postflight():
    """Reuse the human-invoked-only checks from session_postflight (AC2)."""
    sys.path.insert(0, os.path.join(_ROOT, "deploy"))
    import session_postflight as pf

    result = {}
    try:
        latest, behind = pf.check_layer_uniformity()
        result["layer_uniformity"] = {
            "status": "drift" if behind else "clean",
            "latest": latest,
            "behind": [{"function": fn, "on": v} for fn, v in behind],
        }
    except Exception as e:  # noqa: BLE001
        result["layer_uniformity"] = {"status": "error", "detail": str(e)[:300]}
    try:
        drift = pf.check_config_drift()
        result["config_drift"] = {
            "status": "drift" if drift else "clean",
            "items": [{"function": d.get("function_name"), "issue": d.get("issue")} for d in drift] if drift else [],
        }
    except Exception as e:  # noqa: BLE001
        result["config_drift"] = {"status": "error", "detail": str(e)[:300]}
    try:
        incomplete = pf.check_asset_completeness()
        result["asset_completeness"] = {
            "status": "drift" if incomplete else "clean",
            "incomplete": [{"function": fn, "missing": m} for fn, m in incomplete],
        }
    except Exception as e:  # noqa: BLE001
        result["asset_completeness"] = {"status": "error", "detail": str(e)[:300]}
    return result


# ── 3. No functions outside IaC ──────────────────────────────────────────────


def check_orphan_functions():
    """Every live Lambda (in REGION) must be a resource of one of our CFN stacks.

    A function that exists live but in no stack's resource list was created out of band.
    Authoritative (CloudFormation is the IaC record) and cheap (one ListStackResources
    per region-local stack + one ListFunctions). Web/us-east-1 Lambdas — none today; the
    Web stack's edge logic is CloudFront Functions, not Lambda — so we scope to REGION."""
    try:
        lam = _client("lambda")
        live = set()
        paginator = lam.get_paginator("list_functions")
        for page in paginator.paginate():
            for fn in page.get("Functions", []):
                live.add(fn["FunctionName"])
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"list_functions: {e}"}

    try:
        cfn = _client("cloudformation")
        managed = set()
        for name, region in STACKS.items():
            if region != REGION:
                continue  # region-local stacks only (matches the live set above)
            token = None
            while True:
                kw = {"StackName": name}
                if token:
                    kw["NextToken"] = token
                resp = cfn.list_stack_resources(**kw)
                for r in resp.get("StackResourceSummaries", []):
                    if r.get("ResourceType") == "AWS::Lambda::Function" and r.get("PhysicalResourceId"):
                        managed.add(r["PhysicalResourceId"])
                token = resp.get("NextToken")
                if not token:
                    break
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"list_stack_resources: {e}"}

    orphans = sorted(fn for fn in live - managed if not fn.startswith(_ORPHAN_ALLOW_PREFIXES))
    return {"status": "drift" if orphans else "clean", "orphans": orphans, "live_count": len(live), "managed_count": len(managed)}


# ── 4. Bucket-policy delete-protection ───────────────────────────────────────


def check_oidc_iam():
    """The OIDC identities (deploy/remediation/golden-eval/diagnosis roles + provider)
    must match the checked-in JSON under infra/iam/ exactly (#687 S-E6-01).

    Delegates to deploy/verify_oidc_iam.py — the same read-only comparator CI's
    post-deploy checks run — so an out-of-band trust or permission change is caught
    within a week even if no deploy happens."""
    import subprocess

    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(_ROOT, "deploy", "verify_oidc_iam.py")],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"verify_oidc_iam: {e}"}
    if proc.returncode == 0:
        return {"status": "clean"}
    drift_lines = [ln.strip() for ln in proc.stdout.splitlines() if "[DRIFT]" in ln]
    return {"status": "drift", "detail": "OIDC/IAM identities differ from infra/iam/", "mismatches": drift_lines[:10]}


def check_bucket_policy():
    """The live bucket policy must still Deny s3:DeleteObject on every protected prefix.

    Source of truth: deploy/bucket_policy.json's `ProtectDataFromDeployScripts` statement.
    A dropped statement or a missing prefix (data no longer delete-protected) is loud."""
    try:
        with open(os.path.join(_ROOT, "deploy", "bucket_policy.json")) as f:
            expected_pol = json.load(f)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"read source policy: {e}"}
    expected = _protect_prefixes(expected_pol)

    try:
        s3 = _client("s3")
        live_pol = json.loads(s3.get_bucket_policy(Bucket=BUCKET)["Policy"])
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"get_bucket_policy: {e}"}
    live = _protect_prefixes(live_pol)

    if not live:
        return {"status": "drift", "detail": "no ProtectDataFromDeployScripts Deny found live", "missing_prefixes": sorted(expected)}
    missing = sorted(expected - live)
    return {
        "status": "drift" if missing else "clean",
        "missing_prefixes": missing,
        "expected_count": len(expected),
        "live_count": len(live),
    }


def _protect_prefixes(policy):
    """Return the set of resource ARNs under the delete-protection Deny statement."""
    out: set[str] = set()
    for st in policy.get("Statement", []):
        if st.get("Sid") != "ProtectDataFromDeployScripts":
            continue
        if st.get("Effect") != "Deny":
            continue
        actions = st.get("Action")
        actions = [actions] if isinstance(actions, str) else (actions or [])
        if "s3:DeleteObject" not in actions:
            continue
        res = st.get("Resource")
        res = [res] if isinstance(res, str) else (res or [])
        out.update(res)
    return out


def _fetch_live_version(url):
    """GET /version.json and parse it. Raises on any network/parse failure — the
    caller turns that into a soft 'error' status, never a crash."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=10) as r:  # noqa: S310 — fixed https URL
        return json.loads(r.read())


def _git_fetch_main():
    """Best-effort `git fetch origin main` so the local ref is current. Non-fatal:
    a stale-but-present ref is still useful, so failures are swallowed."""
    import subprocess

    subprocess.run(["git", "fetch", "origin", "main", "--quiet"], check=True, capture_output=True, cwd=_ROOT, timeout=30)


def _merge_base_is_ancestor(sha, ref="origin/main"):
    """Return the `git merge-base --is-ancestor` CompletedProcess (returncode 0 = sha
    is an ancestor of/equal to ref; 1 = exists but diverged; 128 = sha unknown)."""
    import subprocess

    return subprocess.run(["git", "merge-base", "--is-ancestor", sha, ref], cwd=_ROOT, capture_output=True, timeout=30)


def check_site_sha_ancestry():
    """#751: the LIVE site's /version.json build SHA must be an ancestor of (or equal
    to) origin/main HEAD. CI's I22 (tests/test_integration_aws.py) catches this right
    after a deploy, but only runs on a deploy and needs a full-history checkout. This is
    the STANDING scheduled check that catches drift BETWEEN deploys — e.g. a manual
    site sync from a stale/unmerged branch, or a rollback that never got a matching
    merge. Read-only: one HTTPS GET + a local `git merge-base --is-ancestor`."""
    url = os.environ.get("SITE_VERSION_URL", "https://averagejoematt.com/version.json")
    try:
        version_data = _fetch_live_version(url)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"fetch {url}: {e}"}

    live_sha = (version_data.get("build") or "").strip()
    if not live_sha:
        return {"status": "error", "detail": "version.json has no 'build' field"}

    try:
        _git_fetch_main()
    except Exception:  # noqa: BLE001 — non-fatal; fall back to whatever ref is local
        pass

    try:
        result = _merge_base_is_ancestor(live_sha)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"merge-base check: {e}", "live_sha": live_sha}

    if result.returncode == 0:
        return {"status": "clean", "live_sha": live_sha}
    if result.returncode == 128:
        return {
            "status": "drift",
            "live_sha": live_sha,
            "detail": f"live SHA {live_sha!r} not found in git history at all — deployed from an unmerged branch or a different clone",
        }
    return {
        "status": "drift",
        "live_sha": live_sha,
        "detail": f"live SHA {live_sha!r} exists but is not an ancestor of origin/main — site has diverged from main",
    }


def check_doc_literals():
    """#791: live counts vs the documented literals in sync_doc_metadata.PLATFORM_FACTS.

    The R22 review found live alarms (122) had silently outrun the documented
    count (110) — doc literals only got reconciled when a session happened to
    notice. This closes the loop weekly: compare the live CloudWatch alarm
    count and live Lambda count against PLATFORM_FACTS. A mismatch is 'drift'
    (it lands in the weekly curated report, not an alarm) with the exact
    reconcile command. Alarm-count remediation is tracked in #795/#809."""
    try:
        sys.path.insert(0, os.path.join(_ROOT, "deploy"))
        import sync_doc_metadata as sdm

        facts = dict(sdm.PLATFORM_FACTS)
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"import sync_doc_metadata: {e}"}

    mismatches = []
    try:
        cw = _client("cloudwatch")
        live_alarms = 0
        token = None
        while True:
            kw = {"MaxRecords": 100}
            if token:
                kw["NextToken"] = token
            resp = cw.describe_alarms(**kw)
            live_alarms += len(resp.get("MetricAlarms", [])) + len(resp.get("CompositeAlarms", []))
            token = resp.get("NextToken")
            if not token:
                break
        doc_alarms = facts.get("alarm_count")
        if doc_alarms is not None and live_alarms != doc_alarms:
            mismatches.append(
                {
                    "fact": "alarm_count",
                    "documented": doc_alarms,
                    "live": live_alarms,
                    "fix": "reconcile the count (see #809 audit), then update PLATFORM_FACTS + run sync_doc_metadata --apply",
                }
            )
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"describe_alarms: {e}"}

    return {"status": "drift" if mismatches else "clean", "mismatches": mismatches}


# ── 6/7. GitHub config posture (#1320) + main-push run liveness (#1544) ──────

GITHUB_POSTURE_FILE = os.path.join(_ROOT, "deploy", "github_posture.json")
DEFAULT_REPO = "averagejoematt/life-platform"

# The one-time owner fix for every scope-gapped surface below (#1320 gate:owner
# remainder): a fine-grained PAT scoped to this repo, stored as the repo secret
# GH_POSTURE_TOKEN (the sentinel prefers it over the ambient GH_TOKEN when set).
PAT_FIX = (
    "fix: create a fine-grained PAT scoped to this repo with repository permissions "
    "Administration:read + Actions:read + Contents:read (+ the implied Metadata:read) "
    "and store it as the GH_POSTURE_TOKEN repo secret — the workflow's built-in "
    "GITHUB_TOKEN can never carry Administration:read"
)

# Path globs that trigger push-event workflows on main. MAINTAINED LITERAL: the
# union of every push-triggered workflow's `on.push.paths` filters — a main
# commit matching NONE of these legitimately queues zero runs, so the #1544
# detector must not alarm on it. tests/test_drift_sentinel.py::
# test_push_trigger_globs_match_workflows parses the live workflow YAMLs and
# reds CI when this set drifts (the PLATFORM_FACTS maintained-literal pattern).
PUSH_TRIGGER_GLOBS = (
    # ci-cd.yml
    "lambdas/**",
    "mcp/**",
    "mcp_server.py",
    "tests/**",
    "cdk/**",
    "ci/**",
    "config/**",
    ".github/workflows/**",
    "requirements*.txt",
    "pyproject.toml",
    ".flake8",
    # docs-ci.yml
    "docs/**",
    "README.md",
    "CLAUDE.md",
    ".claude/commands/**",
    "deploy/sync_doc_metadata.py",
    "scripts/check_doc_*.py",
    "scripts/generate_adr_index.py",
    "scripts/generate_mcp_tool_catalog.py",
    # site-deploy.yml (+ v4-gate.yml shares site/**)
    "site/**",
    ".github/workflows/site-deploy.yml",
    # v4-gate.yml
    "scripts/v4_*.py",
    "tests/js/**",
    "package.json",
)


def _load_github_posture():
    with open(GITHUB_POSTURE_FILE) as f:
        return json.load(f)


def _github_repo():
    return os.environ.get("GITHUB_REPOSITORY", DEFAULT_REPO)


def _matches_push_trigger(path):
    """True if a changed file at `path` matches any push-workflow path filter.

    GitHub glob semantics, approximated for the actual pattern set: `x/**` is a
    prefix match, a bare filename is exact, anything else with a `*` is fnmatch."""
    import fnmatch

    for pat in PUSH_TRIGGER_GLOBS:
        if pat.endswith("/**"):
            if path.startswith(pat[:-2]):
                return True
        elif "*" in pat:
            if fnmatch.fnmatch(path, pat):
                return True
        elif path == pat:
            return True
    return False


def _gh_api_result(path, timeout=60):
    """GET-only `gh api <path>` → (data, None) on success, (None, errinfo) on failure.

    errinfo = {"classification": "scope"|"absent"|"error", "detail": "..."} — "scope"
    means the credential can't read the surface (403 / resource-not-accessible /
    missing-scope), "absent" is a semantic 404 (the thing doesn't exist / is off),
    "error" is everything else (transient, parse, gh missing). Never raises. This
    NEVER mutates GitHub: plain `gh api` issues a GET.

    Prefers the GH_POSTURE_TOKEN env var (the owner-supplied fine-grained PAT — see
    PAT_FIX) over the ambient GH_TOKEN when set and non-empty."""
    import subprocess

    env = dict(os.environ)
    posture_token = env.get("GH_POSTURE_TOKEN")
    if posture_token:
        env["GH_TOKEN"] = posture_token
    try:
        out = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=timeout, cwd=_ROOT, env=env)
    except Exception as e:  # noqa: BLE001
        return None, {"classification": "error", "detail": f"gh api {path}: {e}"[:300]}
    if out.returncode == 0:
        try:
            return (json.loads(out.stdout) if out.stdout.strip() else {}), None
        except Exception as e:  # noqa: BLE001
            return None, {"classification": "error", "detail": f"gh api {path}: parse: {e}"[:300]}
    text = ((out.stdout or "") + " " + (out.stderr or "")).strip()
    low = text.lower()
    if "http 403" in low or "resource not accessible" in low or "must have admin" in low or ("needs the" in low and "scope" in low):
        cls = "scope"
    elif "http 404" in low:
        cls = "absent"
    else:
        cls = "error"
    return None, {"classification": cls, "detail": text[:300]}


def _parse_gh_date(s):
    return datetime.fromisoformat((s or "").replace("Z", "+00:00"))


def check_github_config():
    """#1320 — GET-only asserts of documented GitHub config vs. live state.

    Three surfaces, each compared against deploy/github_posture.json (the
    machine-readable mirror of the doc claims — never a hardcoded wish):

      * environment_production — the `production` environment's protection rules
        must include `required_reviewers` iff the posture says so. As of
        2026-07-19 the docs still claim the manual-approval gate while live has
        only branch_policy (the #1319 private-flip drop) — so this fires, by
        design, until #1319 reconciles docs + posture + live.
      * main_ruleset — ruleset 19162901 must be `active` with exactly the
        documented rule types (deletion + non_fast_forward) on refs/heads/main.
      * vulnerability_alerts — Dependabot/vulnerability alerts enablement must
        match the posture (docs claim Dependabot as the CVE remediation channel;
        live-disabled is the SDLC-review P2-4 finding).

    Fail-soft: a surface the credential can't read reports status "unavailable"
    plus a needs_owner line naming the exact fine-grained-PAT permission (see
    PAT_FIX) — never a red. Overall: drift > error > unavailable > clean."""
    try:
        posture = _load_github_posture()
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"read github_posture.json: {e}"}

    repo = _github_repo()
    surfaces = {}
    scope_gaps = []

    # 1. production environment protection (the #1319 class)
    want_env = posture.get("environment_production", {})
    data, err = _gh_api_result(f"repos/{repo}/environments/{want_env.get('name', 'production')}")
    if err:
        if err["classification"] == "scope":
            surfaces["environment_production"] = {"status": "unavailable", "detail": err["detail"]}
            scope_gaps.append("environments/production (needs fine-grained Actions:read)")
        elif err["classification"] == "absent":
            surfaces["environment_production"] = {"status": "drift", "detail": "the `production` environment does not exist live"}
        else:
            surfaces["environment_production"] = {"status": "error", "detail": err["detail"]}
    else:
        rule_types = sorted(r.get("type") for r in data.get("protection_rules", []) if r.get("type"))
        has_reviewers = "required_reviewers" in rule_types
        if bool(want_env.get("required_reviewers")) == has_reviewers:
            surfaces["environment_production"] = {"status": "clean", "live_protection_rule_types": rule_types}
        else:
            surfaces["environment_production"] = {
                "status": "drift",
                "documented": {"required_reviewers": bool(want_env.get("required_reviewers"))},
                "live_protection_rule_types": rule_types,
                "detail": f"documented posture requires_reviewers={bool(want_env.get('required_reviewers'))} "
                f"but live protection rules are {rule_types} (source: {want_env.get('source', 'github_posture.json')[:120]}…)",
            }

    # 2. main branch ruleset (#1325 posture)
    want_rs = posture.get("main_ruleset", {})
    data, err = _gh_api_result(f"repos/{repo}/rulesets/{want_rs.get('id')}")
    if err:
        if err["classification"] == "scope":
            surfaces["main_ruleset"] = {"status": "unavailable", "detail": err["detail"]}
            scope_gaps.append(f"rulesets/{want_rs.get('id')} (needs fine-grained Administration:read)")
        elif err["classification"] == "absent":
            surfaces["main_ruleset"] = {
                "status": "drift",
                "detail": f"ruleset {want_rs.get('id')} ({'/'.join(want_rs.get('rule_types', []))}) no longer exists — "
                "force-push/deletion protection on main is GONE",
            }
        else:
            surfaces["main_ruleset"] = {"status": "error", "detail": err["detail"]}
    else:
        problems = []
        if data.get("enforcement") != want_rs.get("enforcement", "active"):
            problems.append(f"enforcement={data.get('enforcement')!r} (documented {want_rs.get('enforcement', 'active')!r})")
        live_rules = sorted(r.get("type") for r in data.get("rules", []) if r.get("type"))
        want_rules = sorted(want_rs.get("rule_types", []))
        if live_rules != want_rules:
            problems.append(f"rules={live_rules} (documented exactly {want_rules})")
        include = (data.get("conditions", {}).get("ref_name", {}) or {}).get("include", [])
        for ref in want_rs.get("include_refs", []):
            if ref not in include:
                problems.append(f"{ref} missing from ref_name.include={include}")
        if problems:
            surfaces["main_ruleset"] = {"status": "drift", "detail": "; ".join(problems)}
        else:
            surfaces["main_ruleset"] = {"status": "clean", "live_rules": live_rules}

    # 3. vulnerability / Dependabot alerts enablement (ADR-082's remediation channel)
    want_va = bool(posture.get("vulnerability_alerts", {}).get("enabled"))
    data, err = _gh_api_result(f"repos/{repo}/vulnerability-alerts")
    if err is None:
        live_va = True  # 204 No Content = enabled
    elif err["classification"] == "absent" and "disabled" in err["detail"].lower():
        live_va = False  # semantic 404: "Vulnerability alerts are disabled."
    elif err["classification"] in ("scope", "absent"):
        # A generic 404/403 here means the token lacks admin read (GitHub hides the
        # surface) — indistinguishable from disabled, so report it honestly as a gap.
        surfaces["vulnerability_alerts"] = {"status": "unavailable", "detail": err["detail"]}
        scope_gaps.append("vulnerability-alerts (needs fine-grained Administration:read)")
        live_va = None
    else:
        surfaces["vulnerability_alerts"] = {"status": "error", "detail": err["detail"]}
        live_va = None
    if live_va is not None:
        if live_va == want_va:
            surfaces["vulnerability_alerts"] = {"status": "clean", "enabled": live_va}
        else:
            surfaces["vulnerability_alerts"] = {
                "status": "drift",
                "documented": {"enabled": want_va},
                "live": {"enabled": live_va},
                "detail": f"documented posture enabled={want_va} but live enabled={live_va} "
                "(one-click owner toggle: repo Settings → Advanced Security)",
            }

    statuses = [s["status"] for s in surfaces.values()]
    if "drift" in statuses:
        status = "drift"
    elif "error" in statuses:
        status = "error"
    elif "unavailable" in statuses:
        status = "unavailable"
    else:
        status = "clean"
    result = {"status": status, "surfaces": surfaces}
    if scope_gaps:
        result["needs_owner"] = f"GitHub posture surface(s) unreadable with the current token: {'; '.join(scope_gaps)}. {PAT_FIX}."
    return result


def _is_bot_commit(c):
    """True for commits committed by a [bot] identity (e.g. github-actions[bot] —
    the ci-cd reconcile commits). GITHUB_TOKEN pushes structurally never trigger
    push-event workflows (GitHub's recursive-workflow prevention), so expecting a
    run for them would false-alarm on every merge-queue reconcile."""
    for login in ((c.get("author") or {}).get("login"), (c.get("committer") or {}).get("login")):
        if login and login.endswith("[bot]"):
            return True
    name = ((c.get("commit") or {}).get("committer") or {}).get("name", "")
    return bool(name) and name.endswith("[bot]")


def _commit_files(repo, sha):
    """Changed-file paths for one commit; None (soft) if unreadable."""
    data, err = _gh_api_result(f"repos/{repo}/commits/{sha}")
    if err:
        return None
    return [f.get("filename", "") for f in data.get("files", [])]


def check_github_push_runs(max_file_lookups=15):
    """#1544 — the "push-event runs stopped queuing" detector.

    Compares the last N commits on main against push-event workflow runs:

      * STALLED (drift, ≥1): a trigger-matching commit OLDER than the grace
        window, NEWER than the newest run-covered commit, with no push-event run
        whose head_sha matches — the live "merges are landing, nothing queues"
        state (six merges sat in exactly this state for ~3h on 2026-07-19).
      * HISTORICAL GAP (drift at ≥ gap_cluster_threshold): trigger-matching
        commits older than the newest covered commit that never got a run even
        though runs resumed — the class where a site/-touching merge silently
        missed its site-deploy (the superseded-skip trap). A SINGLE gap is
        reported but not drift: a non-head commit of a multi-commit push
        legitimately has no run of its own (only the push head gets runs).

    Path-filter aware via PUSH_TRIGGER_GLOBS — commits touching only e.g.
    handovers/ trigger nothing and are never counted. Commits committed by a
    [bot] identity (the ci-cd reconcile commits, pushed with a workflow's
    GITHUB_TOKEN) are exempt: GitHub deliberately never creates push-event runs
    for GITHUB_TOKEN pushes (recursive-workflow prevention — ci-cd.yml documents
    this and compensates in-workflow), verified live 2026-07-19 on two reconcile
    commits. Commits younger than grace_minutes are never judged (runs may still
    be queuing). Commits older than the fetched runs window are skipped
    (coverage unknown, stated). All thresholds live in deploy/github_posture.json's
    push_run_detector block. GET-only; fail-soft "unavailable" (never red) when
    the token lacks Actions:read for /actions/runs."""
    try:
        cfg = _load_github_posture().get("push_run_detector", {})
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"read github_posture.json: {e}"}
    grace_min = int(cfg.get("grace_minutes", 30))
    lookback_days = int(cfg.get("lookback_days", 7))
    max_commits = int(cfg.get("max_commits", 30))
    cluster = int(cfg.get("gap_cluster_threshold", 2))

    repo = _github_repo()
    commits, err = _gh_api_result(f"repos/{repo}/commits?sha=main&per_page={max_commits}")
    if err:
        if err["classification"] == "scope":
            return {
                "status": "unavailable",
                "detail": err["detail"],
                "needs_owner": f"commits on main unreadable with the current token (needs Contents:read). {PAT_FIX}.",
            }
        return {"status": "error", "detail": err["detail"]}

    runs_data, err = _gh_api_result(f"repos/{repo}/actions/runs?event=push&branch=main&per_page=100")
    if err:
        if err["classification"] == "scope":
            return {
                "status": "unavailable",
                "detail": err["detail"],
                "needs_owner": f"/actions/runs unreadable with the current token (needs Actions:read). {PAT_FIX}.",
            }
        return {"status": "error", "detail": err["detail"]}
    runs = runs_data.get("workflow_runs", [])
    covered_shas = {r.get("head_sha") for r in runs}
    oldest_run_dt = None
    if runs:
        try:
            oldest_run_dt = min(_parse_gh_date(r.get("created_at")) for r in runs if r.get("created_at"))
        except Exception:  # noqa: BLE001
            oldest_run_dt = None

    now = datetime.now(timezone.utc)
    window = []
    bots_skipped = 0
    for i, c in enumerate(commits or []):
        try:
            dt = _parse_gh_date(c["commit"]["committer"]["date"])
        except Exception:  # noqa: BLE001
            continue
        if i > 0 and (now - dt).total_seconds() > lookback_days * 86400:
            break  # past the lookback (the head commit is always considered)
        if _is_bot_commit(c):
            bots_skipped += 1  # GITHUB_TOKEN pushes never get push-event runs (GitHub rule)
            continue
        window.append({"sha": c["sha"], "date": dt, "age_min": (now - dt).total_seconds() / 60})

    newest_covered_idx = next((i for i, w in enumerate(window) if w["sha"] in covered_shas), None)

    stalled, gaps, notes = [], [], []
    file_lookups = 0
    for idx, w in enumerate(window):
        if w["sha"] in covered_shas or w["age_min"] < grace_min:
            continue
        if oldest_run_dt is not None and w["date"] < oldest_run_dt:
            notes.append(f"{w['sha'][:8]} predates the fetched runs window — coverage unknown, skipped")
            continue
        if file_lookups < max_file_lookups:
            file_lookups += 1
            files = _commit_files(repo, w["sha"])
        else:
            files = None
        if files is None:
            notes.append(f"{w['sha'][:8]} files unreadable/capped — conservatively treated as trigger-matching")
            triggers = True
        else:
            triggers = any(_matches_push_trigger(p) for p in files)
        if not triggers:
            continue  # e.g. a handovers/-only wrap commit — zero runs is correct
        entry = {"sha": w["sha"], "date": w["date"].isoformat(), "waiting_min": round(w["age_min"], 1)}
        if newest_covered_idx is None or idx < newest_covered_idx:
            stalled.append(entry)
        else:
            gaps.append(entry)

    detail_parts = []
    if stalled:
        detail_parts.append(
            f"push-event runs are NOT QUEUING: {len(stalled)} trigger-matching merge(s) on main newer than the last "
            f"run-covered commit have zero workflow runs after the {grace_min}-min grace window (the #1544 class) — "
            "check githubstatus.com + the Actions spending limit, and deploy manually from main until resolved"
        )
    if len(gaps) >= cluster:
        detail_parts.append(
            f"historical gap: {len(gaps)} trigger-matching merge(s) got zero push-event runs even though runs resumed — "
            "their per-path deploys (site-deploy/docs-ci) never fired; verify the live surfaces are at HEAD"
        )
    status = "drift" if detail_parts else "clean"
    result = {
        "status": status,
        "commits_checked": len(window),
        "bot_commits_exempt": bots_skipped,
        "runs_seen": len(runs),
        "stalled": stalled,
        "gap_commits": gaps,
    }
    if detail_parts:
        result["detail"] = "; ".join(detail_parts)
    if gaps and len(gaps) < cluster:
        result["note"] = (
            f"{len(gaps)} uncovered commit(s) below the cluster threshold ({cluster}) — could be non-head commits "
            "of a multi-commit push (only the push head gets runs); reported, not alarmed"
        )
    if notes:
        result["skipped"] = notes[:10]
    return result


# ── Assemble + persist ───────────────────────────────────────────────────────


def run_sweep():
    checks = {
        "cfn_drift": check_cfn_drift(),
        **check_postflight(),
        "orphan_functions": check_orphan_functions(),
        "bucket_policy": check_bucket_policy(),
        "oidc_iam": check_oidc_iam(),
        "doc_literals": check_doc_literals(),
        "site_sha_ancestry": check_site_sha_ancestry(),
        "github_config": check_github_config(),
        "github_push_runs": check_github_push_runs(),
    }
    statuses = [c.get("status") for c in checks.values()]
    if "drift" in statuses:
        status = "drift"
    elif "error" in statuses or "degraded" in statuses:
        status = "degraded"
    else:
        status = "clean"
    now = datetime.now(timezone.utc)
    return {
        "date": now.strftime("%Y-%m-%d"),
        "generated_at": now.isoformat(),
        "status": status,
        "summary": _summary(status, checks),
        "checks": checks,
    }


def _summary(status, checks):
    if status == "clean":
        n = len(STACKS)
        return f"All clear: {n}/{n} stacks in sync, no config/layer/asset drift, no orphan functions, data delete-protection intact."
    parts = []
    cfn = checks["cfn_drift"]
    drifted_stacks = [s for s, v in cfn.get("stacks", {}).items() if v.get("status") == "drift"]
    if drifted_stacks:
        parts.append(f"{len(drifted_stacks)} stack(s) drifted: {', '.join(drifted_stacks)}")
    for key, label in (
        ("config_drift", "config drift"),
        ("layer_uniformity", "retired-layer reference(s)"),
        ("asset_completeness", "asset gap"),
        ("orphan_functions", "orphan function(s)"),
        ("bucket_policy", "delete-protection gap"),
        ("doc_literals", "doc-literal drift"),
        ("site_sha_ancestry", "live site SHA not on main"),
        ("github_config", "GitHub config diverges from documented posture"),
        ("github_push_runs", "main-push workflow runs not queuing"),
    ):
        c = checks.get(key, {})
        if c.get("status") == "drift":
            parts.append(label)
    errored = [k for k, v in checks.items() if v.get("status") == "error"]
    if errored:
        parts.append(f"{len(errored)} check(s) could not run: {', '.join(errored)}")
    return "; ".join(parts) or f"status={status}"


def persist(record):
    s3 = _client("s3")
    body = json.dumps(record, indent=2, default=str).encode()
    for key in (f"drift-log/{record['date']}.json", "drift-log/latest.json"):
        s3.put_object(Bucket=BUCKET, Key=key, Body=body, ContentType="application/json")
    return f"s3://{BUCKET}/drift-log/latest.json"


def print_summary(record):
    icon = {"clean": "🟢", "drift": "🔴", "degraded": "🟡"}.get(record["status"], "·")
    print("── weekly drift sentinel ──")
    print(f"{icon} {record['status'].upper()}: {record['summary']}")
    for name, c in record["checks"].items():
        st = c.get("status")
        mark = {"clean": "🟢", "drift": "🔴", "error": "🟡", "unavailable": "⚪"}.get(st, "·")
        detail = ""
        if st == "drift":
            if name == "cfn_drift":
                ds = [s for s, v in c.get("stacks", {}).items() if v.get("status") == "drift"]
                detail = f" — {', '.join(ds)}"
            elif name == "orphan_functions":
                detail = f" — {', '.join(c.get('orphans', []))}"
            elif name == "bucket_policy":
                detail = f" — missing {c.get('missing_prefixes')}"
            elif name == "config_drift":
                detail = f" — {[i.get('function') for i in c.get('items', [])]}"
            elif name == "layer_uniformity":
                detail = f" — {[b.get('function') for b in c.get('behind', [])]}"
            elif name == "asset_completeness":
                detail = f" — {[i.get('function') for i in c.get('incomplete', [])]}"
            elif name == "doc_literals":
                detail = f" — {[(m['fact'], m['documented'], 'live', m['live']) for m in c.get('mismatches', [])]}"
            elif name == "site_sha_ancestry":
                detail = f" — {c.get('detail', '')}"
            elif name == "github_config":
                bad = {k: v.get("detail", "") for k, v in c.get("surfaces", {}).items() if v.get("status") == "drift"}
                detail = f" — {bad}"
            elif name == "github_push_runs":
                detail = f" — {c.get('detail', '')}"
        elif st == "error":
            detail = f" — {c.get('detail', '')}"
        print(f"   {mark} {name}: {st}{detail}")
        # #1320 fail-soft honesty: a scope-gapped GitHub surface surfaces its
        # needs-owner line (the exact PAT permission to add) — visible, never red.
        if name in ("github_config", "github_push_runs") and c.get("needs_owner"):
            print(f"      [needs-owner] {c['needs_owner']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true", help="exit non-zero if drift/degraded")
    ap.add_argument("--no-write", action="store_true", help="print only, don't write S3")
    args = ap.parse_args()

    record = run_sweep()
    print_summary(record)
    if not args.no_write:
        try:
            print(f"written: {persist(record)}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] persist failed: {e}")
    if args.strict and record["status"] != "clean":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
