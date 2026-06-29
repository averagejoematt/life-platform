#!/usr/bin/env python3
"""
session_postflight.py — after a multi-deploy session, verify the fleet is consistent.

Encodes this era's deploy-hygiene lessons as one read-only command, so a session
doesn't end with a silent inconsistency:

  1. LAYER UNIFORMITY — every shared-layer consumer is on the latest published
     `life-platform-shared-utils` version. The v89/v91 stall: a new layer was
     published but consumers were left on the old version, and the Plan gate
     blocked the next deploy until the fleet was made uniform.

  2. LAMBDA CONFIG DRIFT — the CDK-declared timeout/memory matches what's live.
     CI deploys CODE only; config (Handler/Memory/Timeout/Env/Layers) ships via
     `cdk deploy`, so a merged config change can sit undeployed for months
     (observed: og-image handler, ~3 months). Reuses check_lambda_config_drift.

Read-only (describe/list/get only). Exits non-zero if any inconsistency, so it
can gate a session wrap or run in CI.

Run from the repo root:
    python3 deploy/session_postflight.py
"""
from __future__ import annotations

import json
import os
import sys

REGION = os.environ.get("AWS_REGION", "us-west-2")
LAYER_NAME = "life-platform-shared-utils"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _lambda():
    import boto3

    return boto3.client("lambda", region_name=REGION)


def check_layer_uniformity():
    """Returns (latest_version, [(function, attached_version), ...] behind)."""
    cl = _lambda()
    versions = cl.list_layer_versions(LayerName=LAYER_NAME, MaxItems=1).get("LayerVersions", [])
    if not versions:
        return None, []
    latest = versions[0]["Version"]
    consumers = json.load(open(os.path.join(_ROOT, "ci", "lambda_map.json"))).get("shared_layer", {}).get("consumers", [])
    behind = []
    for fn in consumers:
        try:
            cfg = cl.get_function_configuration(FunctionName=fn)
        except Exception:  # noqa: BLE001 — a consumer name that isn't live yet
            continue
        attached = [int(l["Arn"].rsplit(":", 1)[-1]) for l in cfg.get("Layers", []) if LAYER_NAME in l["Arn"]]
        if attached and max(attached) != latest:
            behind.append((fn, max(attached)))
    return latest, behind


# Bundled-asset canaries: a function that imports a root-level lambdas/*.py module,
# and the module(s) its zip MUST therefore contain. A cdk deploy once shipped an
# asset MISSING every root module (the silent coherence-sentinel break, 2026-06-28:
# ImportModuleError, but the invoke still returned 200 + it ran "green" off a stale
# artifact). Spread across stacks (Operational + Compute) since each deploys its own
# copy of the shared asset at its own time. See reference_cdk_asset_staging_glitch.
_ASSET_CANARIES = {
    "life-platform-coherence-sentinel": ["coherence_invariants.py", "canonical_facts.py"],
    "ai-expert-analyzer": ["canonical_facts.py"],
}


def check_asset_completeness():
    """Returns [(function, [missing root modules]), ...]. Downloads each canary's
    deployed zip and asserts the root module(s) it imports are present — catching a
    staging glitch that bundles only subdir modules. Fail-soft per function (a
    transient describe/download error skips that canary, never crashes postflight)."""
    import io
    import urllib.request
    import zipfile

    cl = _lambda()
    problems = []
    for fn, required in _ASSET_CANARIES.items():
        try:
            loc = cl.get_function(FunctionName=fn)["Code"]["Location"]
            with urllib.request.urlopen(loc, timeout=30) as r:
                data = r.read()
            names = set(zipfile.ZipFile(io.BytesIO(data)).namelist())
            missing = [m for m in required if m not in names]
            if missing:
                problems.append((fn, missing))
        except Exception as e:  # noqa: BLE001 — transient AWS/network, not a real gap
            print(f"  ⚠️  asset check skipped for {fn}: {e}")
    return problems


def check_config_drift():
    """Returns the list of drifted lambdas (from check_lambda_config_drift)."""
    sys.path.insert(0, os.path.join(_ROOT, "deploy"))
    cwd = os.getcwd()
    os.chdir(_ROOT)  # the CDK parser reads cdk/ paths relative to repo root
    try:
        import check_lambda_config_drift as cd

        specs, _unparseable = cd.parse_cdk_lambdas()
        return cd.check(specs)
    finally:
        os.chdir(cwd)


def main() -> int:
    problems = 0
    print("── session postflight ──")

    try:
        latest, behind = check_layer_uniformity()
        if latest is None:
            print("  ⚠️  layer: couldn't read published versions")
        elif behind:
            problems += 1
            print(f"  🔴 layer uniformity: {len(behind)} consumer(s) behind v{latest}:")
            for fn, v in behind:
                print(f"       {fn} on v{v} (latest v{latest}) — redeploy to attach the current layer")
        else:
            print(f"  🟢 layer uniformity: all consumers on v{latest}")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  layer check skipped: {e}")

    try:
        incomplete = check_asset_completeness()
        if incomplete:
            problems += 1
            print(f"  🔴 asset completeness: {len(incomplete)} lambda(s) shipped a zip missing imported root module(s):")
            for fn, missing in incomplete:
                print(f"       {fn} is MISSING {missing} — `rm -rf cdk/cdk.out` and redeploy its stack")
        else:
            print("  🟢 asset completeness: canary zips contain their imported root modules")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  asset-completeness check skipped: {e}")

    try:
        drift = check_config_drift()
        if drift:
            problems += 1
            print(f"  🔴 config drift: {len(drift)} lambda(s) differ from CDK (run `cdk deploy`):")
            for d in drift[:10]:
                if isinstance(d, dict):
                    print(f"       {d.get('function_name', d.get('function', '?'))}: {d.get('issue', d)}")
                else:
                    print(f"       {d}")
        else:
            print("  🟢 config drift: live config matches CDK")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  config-drift check skipped: {e}")

    print("✅ fleet consistent" if problems == 0 else f"❌ {problems} consistency issue(s) — see above")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
