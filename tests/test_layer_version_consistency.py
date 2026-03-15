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
    """Return all .py files in cdk/stacks/."""
    sources = []
    if not os.path.isdir(CDK_STACKS_DIR):
        return sources
    for fname in os.listdir(CDK_STACKS_DIR):
        if fname.endswith(".py") and not fname.startswith("__"):
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
    hardcoded_arn_re = re.compile(
        r"arn:aws:lambda:[^:]+:[^:]+:layer:" + re.escape(SHARED_LAYER_NAME) + r":\d+"
    )
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
# LV4 — Consumer count sanity check
# ══════════════════════════════════════════════════════════════════════════════

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
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)
