#!/usr/bin/env python3
"""
tests/test_layer_version_consistency.py — Shared layer version consistency linter.

R13-F08: CI test to verify that the CDK stack definition references the same
shared layer version that is declared as current in ci/lambda_map.json.

Root cause it prevents: The 2026-03-09 P2 incident where 13 ingestion Lambdas
failed after a logger update because the layer was rebuilt but CDK was not
redeployed, leaving all consumers on the old version. The CI shell step in
ci-cd.yml catches this at deploy time; this pytest catches it at PR review time
on any developer machine without AWS credentials.

Rules:
  LV1  CDK stack source files that reference the shared layer must use the
       `life-platform-shared-utils` layer name (not a hardcoded ARN or version)
  LV2  All consumers listed in ci/lambda_map.json must be present in the
       CDK stack source that attaches layer consumers
  LV3  The shared layer module list in lambda_map.json must have all source
       files present on disk

Offline-only: these tests do NOT require AWS credentials and run in <1s.
The live AWS version check (comparing deployed version to latest published)
is handled by the CI shell step in .github/workflows/ci-cd.yml.

Run:  python3 -m pytest tests/test_layer_version_consistency.py -v

v1.0.0 — 2026-03-15 (R13-F08)
"""

import json
import os
import re
import sys

import pytest

# #416 / ADR-117: this file is in the deploy-critical lane (shared-layer wiring).
# The critical lane runs `-m "deploy_critical and not integration"`, so the live
# AWS test below (test_lv6, @pytest.mark.integration) is excluded from it.
pytestmark = pytest.mark.deploy_critical

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDA_MAP_PATH = os.path.join(ROOT, "ci", "lambda_map.json")
CDK_STACKS_DIR = os.path.join(ROOT, "cdk", "stacks")

SHARED_LAYER_NAME = "life-platform-shared-utils"


# ── Load lambda_map.json ──────────────────────────────────────────────────────


def _load_lambda_map():
    with open(LAMBDA_MAP_PATH) as f:
        return json.load(f)


_MAP = _load_lambda_map()
_LAYER_MODULES = _MAP.get("shared_layer", {}).get("modules", [])
_LAYER_CONSUMERS = _MAP.get("shared_layer", {}).get("consumers", [])


# ── CDK source files ──────────────────────────────────────────────────────────


def _get_cdk_python_sources():
    """Return .py files in cdk/stacks/, excluding constants.py.

    constants.py is excluded because it intentionally defines SHARED_LAYER_ARN
    with the concrete version number as the single source of truth. The CDK
    stacks import from there rather than hardcoding versions themselves, which
    is the correct pattern (one place to update on every layer rebuild).
    """
    sources = []
    if not os.path.isdir(CDK_STACKS_DIR):
        return sources
    EXCLUDE = {"constants.py"}  # intentionally holds the canonical layer version
    for fname in os.listdir(CDK_STACKS_DIR):
        if fname.endswith(".py") and not fname.startswith("__") and fname not in EXCLUDE:
            sources.append(os.path.join(CDK_STACKS_DIR, fname))
    return sources


def _read_cdk_sources():
    """Return concatenated content of all CDK stack sources."""
    content = ""
    for path in _get_cdk_python_sources():
        try:
            with open(path) as f:
                content += f"\n# FILE: {path}\n" + f.read()
        except Exception:
            pass
    return content


_CDK_SOURCE = _read_cdk_sources()


# ══════════════════════════════════════════════════════════════════════════════
# LV1 — CDK references layer by name, not hardcoded ARN/version
# ══════════════════════════════════════════════════════════════════════════════


def test_lv1_cdk_uses_layer_name_not_hardcoded_arn():
    """LV1: CDK stacks must reference the shared layer by name lookup, not a
    hardcoded ARN with a version number embedded.

    Hardcoded ARNs like:
      arn:aws:lambda:us-west-2:205930651321:layer:life-platform-shared-utils:9
    become stale the moment a new layer version is published. The CDK should
    use `from_layer_version_arn` with a dynamic lookup, or reference the layer
    name for `list_layer_versions` at deploy time.

    A hardcoded version number in an ARN in CDK source is the bug that caused
    the March 9 P2 — this test detects it before it reaches production.
    """
    if not _CDK_SOURCE:
        pytest.skip("No CDK stack sources found in cdk/stacks/")

    # Pattern: hardcoded layer ARN with a specific version (ends in :N)
    hardcoded_arn_re = re.compile(r"arn:aws:lambda:[^:]+:[^:]+:layer:" + re.escape(SHARED_LAYER_NAME) + r":\d+")
    matches = hardcoded_arn_re.findall(_CDK_SOURCE)

    assert not matches, (
        f"LV1 FAIL: {len(matches)} hardcoded layer ARN(s) with version numbers found in CDK stacks:\n"
        + "\n".join(f"  {m}" for m in matches)
        + "\n\nUse dynamic layer version lookup instead of hardcoding the version number. "
        "Hardcoded versions become stale after every layer rebuild."
    )


# ══════════════════════════════════════════════════════════════════════════════
# LV2 — All lambda_map.json consumers appear in CDK source
# ══════════════════════════════════════════════════════════════════════════════


def test_lv2_all_consumers_referenced_in_cdk():
    """LV2: Every consumer listed in ci/lambda_map.json shared_layer.consumers
    must be referenced somewhere in CDK stack source.

    If a Lambda function name appears in the consumers list but not in CDK,
    it will never have the layer attached automatically on CDK deploy — meaning
    it stays on whatever version was last manually attached.
    """
    if not _CDK_SOURCE:
        pytest.skip("No CDK stack sources found in cdk/stacks/")

    if not _LAYER_CONSUMERS:
        pytest.skip("No consumers defined in ci/lambda_map.json shared_layer.consumers")

    missing = []
    for consumer in _LAYER_CONSUMERS:
        # Function names appear in CDK as string literals — check for the name
        # in quotes or as part of a function_name= assignment
        if consumer not in _CDK_SOURCE:
            missing.append(consumer)

    assert not missing, (
        f"LV2 FAIL: {len(missing)} shared layer consumer(s) not found in CDK stack sources:\n"
        + "\n".join(f"  '{c}'" for c in missing)
        + "\n\nThese Lambdas are listed as layer consumers in ci/lambda_map.json but are "
        "not referenced in any CDK stack. They may not have the layer attached on CDK deploy."
    )


# ══════════════════════════════════════════════════════════════════════════════
# LV3 — All layer module source files exist on disk
# ══════════════════════════════════════════════════════════════════════════════


def test_lv3_all_layer_modules_exist_on_disk():
    """LV3: Every module listed in ci/lambda_map.json shared_layer.modules must
    have a corresponding source file on disk.

    If a module is listed but the file doesn't exist, `build_layer.sh` will
    silently skip it (it prints a warning but exits 0), producing a layer zip
    that's missing a module. This causes ImportModuleError at Lambda runtime.

    Catches: deleted files not removed from lambda_map.json, renamed modules,
    typos in the modules list.
    """
    if not _LAYER_MODULES:
        pytest.skip("No modules defined in ci/lambda_map.json shared_layer.modules")

    missing = []
    for module_path in _LAYER_MODULES:
        full_path = os.path.join(ROOT, module_path)
        if not os.path.isfile(full_path):
            missing.append(module_path)

    assert not missing, (
        f"LV3 FAIL: {len(missing)} shared layer module(s) listed in lambda_map.json "
        f"but not found on disk:\n"
        + "\n".join(f"  {m}" for m in missing)
        + "\n\nbuild_layer.sh will silently skip these, creating an incomplete layer. "
        "Either restore the file or remove it from ci/lambda_map.json shared_layer.modules."
    )


# ══════════════════════════════════════════════════════════════════════════════
# LV4 — shared_layer.modules must match build_layer.sh
# ══════════════════════════════════════════════════════════════════════════════


def test_lv4_layer_modules_match_build_script():
    """LV4: ci/lambda_map.json shared_layer.modules must exactly match the
    MODULES list in deploy/build_layer.sh (the source of truth for what ships
    in the layer).

    If they drift, CI's layer-change detection (which reads lambda_map) won't
    fire when a module that IS in the layer is edited — so new Lambda code
    deploys against a stale layer (a silent prod-incident class). 2026-05-28:
    they had drifted by 10 modules (bedrock_client, phase_filter, numeric, …).
    """
    import re

    build_sh = os.path.join(ROOT, "deploy", "build_layer.sh")
    inblock = False
    build_mods = set()
    for ln in open(build_sh).read().splitlines():
        if re.match(r"\s*MODULES=\(", ln):
            inblock = True
            continue
        if inblock:
            if re.match(r"\s*\)\s*$", ln):
                break
            code = ln.split("#", 1)[0]  # strip inline comments (they contain ".py()"-like text)
            build_mods.update(re.findall(r"[A-Za-z_][A-Za-z0-9_]*\.py", code))

    map_mods = {os.path.basename(m) for m in _LAYER_MODULES}
    only_build = build_mods - map_mods
    only_map = map_mods - build_mods
    assert not only_build and not only_map, (
        "LV4 FAIL: shared_layer.modules drifted from build_layer.sh MODULES.\n"
        f"  in build_layer.sh but missing from lambda_map: {sorted(only_build)}\n"
        f"  in lambda_map but not in build_layer.sh: {sorted(only_map)}\n"
        "Sync ci/lambda_map.json shared_layer.modules to deploy/build_layer.sh."
    )


# ══════════════════════════════════════════════════════════════════════════════
# LV5 — Layer version only in constants
# ══════════════════════════════════════════════════════════════════════════════


def test_lv5_layer_version_only_in_constants():
    """LV5: The hardcoded layer version number must only appear in constants.py,
    not copied into individual stack files.

    After the refactor: ingestion_stack.py and email_stack.py import
    SHARED_LAYER_ARN from stacks.constants rather than defining it locally.
    This test catches regressions where someone copies the ARN back into a
    stack file instead of using the import.
    """
    if not _CDK_SOURCE:
        pytest.skip("No CDK stack sources found in cdk/stacks/")

    hardcoded_re = re.compile(r"arn:aws:lambda:[^:]+:[^:]+:layer:" + re.escape(SHARED_LAYER_NAME) + r":\d+")
    matches = hardcoded_re.findall(_CDK_SOURCE)

    assert not matches, (
        f"LV5 FAIL: {len(matches)} hardcoded layer ARN(s) with version numbers found "
        f"in CDK stack files (other than constants.py):\n"
        + "\n".join(f"  {m}" for m in matches)
        + "\n\nImport SHARED_LAYER_ARN from stacks.constants instead of copying the ARN."
    )


def test_lv4_consumer_count_sanity():
    """LV4: The shared layer consumer list must have at least a minimum count.

    Guards against accidental truncation of the consumers list in lambda_map.json.
    If the list drops below the minimum, either the file was corrupted or consumers
    were removed without a corresponding CDK change.
    """
    MIN_CONSUMERS = 5  # conservative floor — we have ~14 consumers
    actual = len(_LAYER_CONSUMERS)
    assert actual >= MIN_CONSUMERS, (
        f"LV4 FAIL: Only {actual} layer consumer(s) in lambda_map.json "
        f"(expected at least {MIN_CONSUMERS}). "
        "The consumer list may have been accidentally truncated."
    )


# ══════════════════════════════════════════════════════════════════════════════
# LV6 — CDK constant matches latest published layer (AWS-aware, V2 P0.2 follow-up)
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_lv6_cdk_constant_matches_latest_published_layer():
    """LV6: cdk/stacks/constants.py SHARED_LAYER_VERSION must equal the latest
    published version of life-platform-shared-utils in AWS.

    Failure mode this catches: a layer rebuild publishes vN+1 to AWS but the
    constant in CDK source still says vN. The next `cdk deploy --all` would
    silently point every Lambda at vN, downgrading every consumer.

    This is the V2 P0.2 bug: constants.py was 43 while prod was 50. The first
    5 LV tests above did NOT catch it because they're offline static-pattern
    checks. This test queries AWS and asserts source-of-truth alignment.

    Fix when this fails:
      sed -i '' 's/SHARED_LAYER_VERSION = N/SHARED_LAYER_VERSION = M/' \\
        cdk/stacks/constants.py
    """
    constants_path = os.path.join(ROOT, "cdk", "stacks", "constants.py")
    src = open(constants_path).read()
    m = re.search(r"^SHARED_LAYER_VERSION\s*=\s*(\d+)", src, re.MULTILINE)
    if not m:
        pytest.skip("SHARED_LAYER_VERSION not found in constants.py")
    cdk_version = int(m.group(1))

    try:
        import boto3
    except ImportError:
        pytest.skip("boto3 unavailable")
    try:
        lc = boto3.client("lambda", region_name="us-west-2")
        versions = lc.list_layer_versions(LayerName=SHARED_LAYER_NAME)["LayerVersions"]
    except Exception as e:
        pytest.skip(f"Could not query layer versions: {e}")
    if not versions:
        pytest.skip(f"Layer {SHARED_LAYER_NAME} has no versions")
    latest = int(versions[0]["Version"])

    assert cdk_version == latest, (
        f"LV6 FAIL: CDK constants.py SHARED_LAYER_VERSION = v{cdk_version}, "
        f"but latest published is v{latest}.\n"
        f"  Next `cdk deploy --all` would silently regress Lambdas to v{cdk_version}.\n"
        f"  Fix: update SHARED_LAYER_VERSION to {latest} in cdk/stacks/constants.py."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess

    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)
