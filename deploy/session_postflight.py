#!/usr/bin/env python3
"""
session_postflight.py — after a multi-deploy session, verify the fleet is consistent.

Encodes this era's deploy-hygiene lessons as one read-only command, so a session
doesn't end with a silent inconsistency:

  1. LAYER RETIREMENT (#781) — NO function references the retired
     `life-platform-shared-utils` layer (shared code ships inside every
     bundle now). Historical context — the v89/v91 stall: a new layer was
     published but consumers were left on the old version, and the Plan gate
     blocked the next deploy until the fleet was made uniform.

  2. LAMBDA CONFIG DRIFT — the CDK-declared timeout/memory matches what's live.
     CI deploys CODE only; config (Handler/Memory/Timeout/Env/Layers) ships via
     `cdk deploy`, so a merged config change can sit undeployed for months
     (observed: og-image handler, ~3 months). Reuses check_lambda_config_drift.

  3. HOOK FRESHNESS (#1326) — the INSTALLED .git/hooks/pre-commit matches what
     scripts/install_hooks.sh would write today. A hook is a local, untracked
     file: it does not get refreshed by `git pull`, so it can drift from its
     installer silently. Observed: #818 deleted scripts/update_architecture_header.sh
     and retired its indirection, but the already-installed hook kept calling it
     for weeks — masked by a `[[ -f ]]` fail-open guard, so the doc-sync half of
     the hook went silently dead. Filesystem-only (no AWS calls).

Read-only (describe/list/get only; the hook-freshness check reads files but never
writes .git/hooks/pre-commit). Exits non-zero if any inconsistency, so it can gate
a session wrap or run in CI.

Run from the repo root:
    python3 deploy/session_postflight.py
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

REGION = os.environ.get("AWS_REGION", "us-west-2")
LAYER_NAME = "life-platform-shared-utils"
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_INSTALLER_REL_PATH = os.path.join("scripts", "install_hooks.sh")


def _lambda():
    import boto3

    return boto3.client("lambda", region_name=REGION)


def check_layer_uniformity():
    """#781: the shared layer is RETIRED — uniformity now means ZERO references.

    Returns (0, [(function, attached_version), ...]) for any function still
    referencing life-platform-shared-utils (drift from before the collapse, or
    a regression re-attaching it). Shared code ships inside every bundle."""
    cl = _lambda()
    offenders = []
    paginator = cl.get_paginator("list_functions")
    for page in paginator.paginate():
        for fn in page["Functions"]:
            attached = [int(l["Arn"].rsplit(":", 1)[-1]) for l in fn.get("Layers", []) if LAYER_NAME in l["Arn"]]
            if attached:
                offenders.append((fn["FunctionName"], max(attached)))
    return 0, offenders


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


def _extract_installer_heredoc(installer_text):
    """Pull the literal hook body scripts/install_hooks.sh writes to the hook file.

    The heredoc is quoted (`<< 'EOF'`) so bash copies it byte-for-byte with zero
    shell interpolation — extraction is a plain text slice between the markers,
    no need to actually execute the installer."""
    m = re.search(r"cat > \"\$HOOK_FILE\" << 'EOF'\n(.*?)\nEOF\n", installer_text, re.S)
    if not m:
        raise ValueError("install_hooks.sh heredoc markers not found — installer format changed, update this check")
    # bash's heredoc writes a trailing newline after the last content line (that's
    # how `cat > file << 'EOF'` terminates the file) — the regex above stops just
    # short of it, so restore it or every fresh install hashes as "stale".
    return m.group(1) + "\n"


def _git_common_dir(root):
    """Resolve the hooks directory git actually consults for commits made from
    `root`. This must NOT be assumed to be `root/.git/hooks` — inside a git
    worktree, `root/.git` is a FILE (a `gitdir:` pointer), not a directory, and
    hooks are shared from the common repo's `.git/hooks`, never per-worktree.
    Falls back to `root/.git` if git isn't invokable (e.g. no git on PATH)."""
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", root, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        ).stdout.strip()
        return out if os.path.isabs(out) else os.path.join(root, out)
    except Exception:
        return os.path.join(root, ".git")


def check_hook_freshness(root=None, hook_path=None):
    """#1326: assert the INSTALLED pre-commit hook matches what
    scripts/install_hooks.sh would write today (sha256 of the heredoc body vs the
    installed file). Returns None if fresh (or the installer itself is missing —
    nothing to compare against), else a problem string. Filesystem-only, no AWS.

    `hook_path` overrides hook-location discovery (tests only) — production
    callers should leave it as None so the common-dir resolution in
    `_git_common_dir` applies (see its docstring for why worktrees need it)."""
    root = root or _ROOT
    installer_path = os.path.join(root, _INSTALLER_REL_PATH)

    if not os.path.exists(installer_path):
        return None

    with open(installer_path) as f:
        expected = _extract_installer_heredoc(f.read())
    expected_hash = hashlib.sha256(expected.encode()).hexdigest()

    if hook_path is None:
        hook_path = os.path.join(_git_common_dir(root), "hooks", "pre-commit")

    if not os.path.exists(hook_path):
        return "pre-commit hook is NOT installed — run `bash scripts/install_hooks.sh`"

    with open(hook_path) as f:
        installed_hash = hashlib.sha256(f.read().encode()).hexdigest()

    if installed_hash != expected_hash:
        return "installed pre-commit hook is STALE (does not match scripts/install_hooks.sh) — re-run `bash scripts/install_hooks.sh`"
    return None


def main() -> int:
    problems = 0
    print("── session postflight ──")

    try:
        _, behind = check_layer_uniformity()
        if behind:
            problems += 1
            print(f"  🔴 layer retirement: {len(behind)} function(s) still reference the RETIRED shared layer:")
            for fn, v in behind:
                print(f"       {fn} on v{v} — cdk deploy its stack to drop the reference (#781)")
        else:
            print("  🟢 layer retirement: no function references life-platform-shared-utils")
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

    try:
        stale = check_hook_freshness()
        if stale:
            problems += 1
            print(f"  🔴 hook freshness: {stale}")
        else:
            print("  🟢 hook freshness: installed pre-commit hook matches scripts/install_hooks.sh")
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️  hook-freshness check skipped: {e}")

    print("✅ fleet consistent" if problems == 0 else f"❌ {problems} consistency issue(s) — see above")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
