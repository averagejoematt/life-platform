#!/usr/bin/env python3
"""
build_bundle.py — the ONE staging implementation for Lambda code bundles (ADR: #781).

Every distribution path stages through this module, so what CDK deploys, what
deploy_lambda.sh hot-deploys, what deploy_fleet.sh pushes fleet-wide, and what
deploy_site_api.sh ships are byte-identical by construction. This replaces the
retired shared layer (life-platform-shared-utils) + build_layer.sh allowlist:
the bundle is the WHOLE lambdas/ tree, so a module can no longer be "missing
from the layer" (the #697 personal_baselines outage class) and layer-version
drift is structurally impossible.

Two bundle shapes:
  tree  — lambdas/ contents at the bundle root (handlers import subpackages as
          `ingestion.whoop_lambda`, shared modules flat as `import ai_calls`)
          + config/food_vocabulary.json at the root (meal_grouper.load_vocab
          looks alongside its own module first).
  mcp   — the tree bundle PLUS mcp_server.py and the mcp/ package at the root
          (life-platform-mcp + life-platform-mcp-warmer). MCP tools import the
          shared modules flat and `from reading import …`, both of which the
          tree provides. This retires the hand-curated MCP staging that kept
          re-breaking (reading/ omitted from the CI zip, hevy modules only on
          the layer).

Usage:
  python3 deploy/build_bundle.py --out DIR [--mcp] [--zip PATH]

Or import from CDK (cdk/stacks/lambda_helpers.py / mcp_stack.py) and call
stage_tree()/stage_mcp() directly at synth time.
"""

import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys
import zipfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# #2377: the fingerprint file every bundle carries. Read back out of a DEPLOYED
# bundle by deploy/verify_bundle_ancestry.sh so "which commit is live?" is a
# structural question, not a symbol-grep guess.
BUILD_INFO_NAME = "build_info.json"

# Mirror of the old CDK _ASSET_EXCLUDES — one list, one place.
EXCLUDE_DIRS = {"__pycache__", "dashboard", "cf-auth", "requirements"}
EXCLUDE_FILE_SUFFIXES = (".pyc", ".md")
EXCLUDE_FILE_NAMES = {".DS_Store"}


def _ignore(directory, names):
    ignored = set()
    for name in names:
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            if name in EXCLUDE_DIRS:
                ignored.add(name)
        elif name in EXCLUDE_FILE_NAMES or name.endswith(EXCLUDE_FILE_SUFFIXES):
            ignored.add(name)
    return ignored


def stage_qa_coverage(out_dir):
    """#1446: stage the QA-coverage snapshot the Monday ops green report reads.

    Derived from tests/qa_manifest.py (the ONE page registry, #1426) at bundle
    time via its `--emit coverage` emitter — never a hand-maintained number.
    The payload is deterministic by contract (sort_keys, NO timestamp) so the
    CDK asset hash only changes when the manifest itself changes.

    Fail-SOFT: a broken emitter must never block a deploy — the green report
    renders its honest "not collected" line when the file is absent.
    """
    try:
        proc = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "tests", "qa_manifest.py"), "--emit", "coverage"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip()[:300] or f"exit {proc.returncode}")
        json.loads(proc.stdout)  # must be valid JSON, or we stage nothing
        with open(os.path.join(out_dir, "qa_coverage_stats.json"), "w", encoding="utf-8") as f:
            f.write(proc.stdout)
    except Exception as e:
        print(
            f"⚠️  qa_coverage_stats.json not staged ({e}) — the Monday green report will show its honest absence line",
            file=sys.stderr,
        )


def _git(args, cwd=REPO_ROOT):
    """Run a git command, returning stripped stdout or None (never raises)."""
    try:
        proc = subprocess.run(["git"] + list(args), cwd=cwd, capture_output=True, text=True, timeout=30)
    except Exception:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def git_fingerprint(repo_root=REPO_ROOT, now=None):
    """Build the {git_sha, built_at, …} payload staged as build_info.json (#2377).

    Resolution order for the commit sha — CI first, because a GitHub Actions
    checkout of a merge ref can leave HEAD pointing at something that isn't the
    sha the run was dispatched for:
      1. BUNDLE_GIT_SHA  (explicit override, used by tests + replays)
      2. GITHUB_SHA      (the CI run's commit)
      3. `git rev-parse HEAD`

    Never raises: a bundle built outside a git checkout stages a fingerprint
    with git_sha=None, which the ancestry check reads as "unknown" (warn, don't
    refuse) rather than as a false clean bill of health.
    """
    sha = os.environ.get("BUNDLE_GIT_SHA") or os.environ.get("GITHUB_SHA") or _git(["rev-parse", "HEAD"], repo_root)
    if sha:
        sha = sha.strip().lower()
    # Dirty only means anything for a locally-built bundle; when the sha came
    # from the environment we are describing that commit, not this worktree.
    dirty = None
    if sha and not (os.environ.get("BUNDLE_GIT_SHA") or os.environ.get("GITHUB_SHA")):
        porcelain = _git(["status", "--porcelain"], repo_root)
        dirty = bool(porcelain)
    built = now or datetime.datetime.now(datetime.timezone.utc)
    return {
        "git_sha": sha,
        "git_short_sha": sha[:8] if sha else None,
        "built_at": built.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "dirty": dirty,
        "builder": os.environ.get("GITHUB_WORKFLOW") or os.environ.get("USER") or "unknown",
        "schema": 1,
    }


def stage_build_info(out_dir, info=None):
    """Write build_info.json at the bundle root (#2377).

    WHY this is in the bundle and not a tag/timestamp: a LastModified stamp only
    proves *a* deploy happened. The fingerprint has to travel with the code, so
    the only way to read it back is to pull what AWS actually holds.

    Cost note: this DOES make the CDK asset hash change per commit (the sha is in
    the file), so a `cdk deploy` after any commit re-uploads code even when
    lambdas/ is untouched. That is the deliberate trade — the "unexpected 0-diff"
    tell is replaced by a stronger one: an explicit sha comparison (#2377).
    """
    payload = info if info is not None else git_fingerprint()
    path = os.path.join(out_dir, BUILD_INFO_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, sort_keys=True, indent=2)
        f.write("\n")
    return path


# ── Bundled non-lambda config trigger registry (#2920) ─────────────────────
# stage_tree() copies a handful of files from OUTSIDE lambdas/ into every
# bundle (food_vocabulary.json, config/personas.json, config/coaches/*.json,
# redirects.map — see below). CI's Plan job used to hand-type a SEPARATE
# pathspec to decide whether one of those changes should trigger a fleet
# deploy: food_vocabulary.json got an explicit special case, personas.json
# never did, and they diverged (ac185e1c shipped an a11y fix nowhere, #2920).
# bundled_extra_paths() is the single derivation both CI and the guard test
# (tests/test_bundle_deploy_trigger_registry.py) read — a file that
# stage_tree() starts copying becomes a deploy trigger by construction, not
# by someone remembering to add a second hand-typed line.
#
# Two files stage_tree() ALSO writes are generated at build time, not copied
# from a fixed repo source path, so they can't be a git-diff pathspec entry —
# they're dated exemptions instead, with the guard test proving every extra
# file a staged bundle contains is accounted for one way or the other.
GENERATED_BUNDLE_EXEMPTIONS = {
    BUILD_INFO_NAME: "2026-08-20 #2920: per-build fingerprint (#2377), generated at stage time — no fixed source path to diff",
    "qa_coverage_stats.json": (
        "2026-08-20 #2920: fail-soft derived snapshot of tests/qa_manifest.py (#1446) — "
        "not a runtime-behavior file, not addressed by this issue"
    ),
}


def bundled_extra_paths(repo_root=REPO_ROOT):
    """Repo-relative source paths stage_tree()/stage_mcp() copy from OUTSIDE
    lambdas/ — the derived deploy-trigger set for #2920.

    Discovered by listing the real config/ directory (same logic stage_tree()
    uses below), not a hand-typed enumeration — a new file dropped into
    config/coaches/ becomes a trigger automatically, no second edit required.
    """
    paths = []
    vocab = os.path.join(repo_root, "config", "food_vocabulary.json")
    if os.path.isfile(vocab):
        paths.append("config/food_vocabulary.json")
    personas = os.path.join(repo_root, "config", "personas.json")
    if os.path.isfile(personas):
        paths.append("config/personas.json")
    coaches_src = os.path.join(repo_root, "config", "coaches")
    if os.path.isdir(coaches_src):
        for name in sorted(os.listdir(coaches_src)):
            if name.endswith(".json") and not name.endswith("_stance.json"):
                paths.append(f"config/coaches/{name}")
    redirects_map = os.path.join(repo_root, "redirects.map")
    if os.path.isfile(redirects_map):
        paths.append("redirects.map")
    return sorted(paths)


def stage_tree(out_dir):
    """Stage the full lambdas/ tree + food_vocabulary.json into out_dir (fresh)."""
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    shutil.copytree(os.path.join(REPO_ROOT, "lambdas"), out_dir, ignore=_ignore)
    # meal_grouper.load_vocab() searches alongside its own module first; the repo
    # canonical copy lives in config/ (not lambdas/), so stage it at the root.
    vocab = os.path.join(REPO_ROOT, "config", "food_vocabulary.json")
    if os.path.isfile(vocab):
        shutil.copy2(vocab, os.path.join(out_dir, "food_vocabulary.json"))
    else:
        print("⚠️  config/food_vocabulary.json missing — meal grouping will fail to load vocab", file=sys.stderr)
    # Persona layer offline fallback: common.repo_config searches upward, so a
    # config/ dir at the bundle root is what makes persona_registry/persona_core
    # readable WITHOUT S3 — the Telegram worker ran nameless ("I'm mind_coach")
    # because neither the S3 grant nor this fallback existed. Personas + voice
    # specs only (~120 KB); stance files stay S3-only (volatile, engine-written).
    cfg_out = os.path.join(out_dir, "config")
    os.makedirs(cfg_out, exist_ok=True)
    personas = os.path.join(REPO_ROOT, "config", "personas.json")
    if os.path.isfile(personas):
        shutil.copy2(personas, os.path.join(cfg_out, "personas.json"))
    else:
        print("⚠️  config/personas.json missing — persona registry will be S3-only", file=sys.stderr)
    coaches_src = os.path.join(REPO_ROOT, "config", "coaches")
    if os.path.isdir(coaches_src):
        coaches_out = os.path.join(cfg_out, "coaches")
        os.makedirs(coaches_out, exist_ok=True)
        for name in sorted(os.listdir(coaches_src)):
            if name.endswith(".json") and not name.endswith("_stance.json"):
                shutil.copy2(os.path.join(coaches_src, name), os.path.join(coaches_out, name))
    else:
        print("⚠️  config/coaches/ missing — voice specs will be S3-only", file=sys.stderr)
    # #1430: redirects.map for qa_smoke_lambda's weekly legacy-redirect spot-check
    # (lambdas/redirect_spotcheck.py searches alongside its own module first, same
    # pattern as food_vocabulary.json above).
    redirects_map = os.path.join(REPO_ROOT, "redirects.map")
    if os.path.isfile(redirects_map):
        shutil.copy2(redirects_map, os.path.join(out_dir, "redirects.map"))
    else:
        print("⚠️  redirects.map missing — the #1430 weekly redirect spot-check will warn+skip", file=sys.stderr)
    # #1446: QA-coverage snapshot for the Monday ops green report (fail-soft).
    stage_qa_coverage(out_dir)
    # #2377: commit fingerprint — every bundle, every path, no exceptions.
    stage_build_info(out_dir)
    return out_dir


def stage_mcp(out_dir):
    """Stage the MCP bundle: full tree + mcp_server.py + mcp/ package."""
    stage_tree(out_dir)
    shutil.copy2(os.path.join(REPO_ROOT, "mcp_server.py"), out_dir)
    shutil.copytree(
        os.path.join(REPO_ROOT, "mcp"),
        os.path.join(out_dir, "mcp"),
        ignore=_ignore,
    )
    return out_dir


def zip_dir(src_dir, zip_path):
    """Deterministic-ish zip of a staged dir (sorted walk, no extra metadata)."""
    if os.path.exists(zip_path):
        os.remove(zip_path)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(src_dir):
            dirs.sort()
            for fname in sorted(files):
                full = os.path.join(root, fname)
                zf.write(full, os.path.relpath(full, src_dir))
    return zip_path


def verify_boot(out_dir, shape):
    """Import every module out of the bundle we just staged (#2632).

    WHY HERE. scripts/verify_bundle_boot.py existed since #1653 and was wired to
    nothing — the census that found it (#2631) flagged it `unreferenced-entrypoint`.
    This is the right call site because the staged bundle *exists* at this moment:
    the gate reads the real artifact instead of rebuilding a copy of it, and it
    runs before the first AWS mutation in every deploy script (all `set -e`).

    It is in main(), NOT in stage_tree()/stage_mcp(), on purpose. CDK imports those
    two directly at synth time and must not pay for a boot probe on every synth —
    and CDK's asset is checked by CI's own pre-merge run of the same script.

    Measured cost: 4.0-4.8s (397 modules tree / 436 mcp) — negligible next to the
    S3 upload and update-function-code calls that follow.

    Escape hatch: SKIP_BUNDLE_BOOT_CHECK=1, or --no-verify-boot. Both print why.
    """
    if os.environ.get("SKIP_BUNDLE_BOOT_CHECK"):
        print("⏭️  bundle-boot check SKIPPED (SKIP_BUNDLE_BOOT_CHECK is set) — the bundle is NOT proven to import")
        return 0
    sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
    import verify_bundle_boot

    print("🔎 Bundle-boot gate (#2632): importing every staged module with Lambda's sys.path …")
    return verify_bundle_boot.gate_staged_bundle(out_dir, shape=shape)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", help="staging directory (recreated fresh)")
    ap.add_argument("--mcp", action="store_true", help="stage the MCP bundle shape")
    ap.add_argument("--zip", dest="zip_path", help="also produce a zip at this path")
    ap.add_argument(
        "--no-verify-boot",
        action="store_true",
        help="skip the #2632 bundle-boot gate (the bundle is then NOT proven to import)",
    )
    ap.add_argument(
        "--print-bundled-config-paths",
        action="store_true",
        help="print the #2920 derived bundled-config deploy-trigger paths (one per line) and exit — no staging performed",
    )
    args = ap.parse_args()

    if args.print_bundled_config_paths:
        for p in bundled_extra_paths():
            print(p)
        return

    if not args.out:
        ap.error("--out is required unless --print-bundled-config-paths is given")

    out = stage_mcp(args.out) if args.mcp else stage_tree(args.out)
    n_files = sum(len(f) for _, _, f in os.walk(out))
    print(f"✅ Staged {'mcp' if args.mcp else 'tree'} bundle: {n_files} files → {out}")

    # Before the zip, so a bundle that cannot boot never becomes a deployable artifact.
    if args.no_verify_boot:
        print("⏭️  bundle-boot check SKIPPED (--no-verify-boot) — the bundle is NOT proven to import")
    elif verify_boot(out, "mcp" if args.mcp else "tree") != 0:
        print("❌ Refusing to package a bundle that cannot boot. Fix the import above, or see #2632.", file=sys.stderr)
        sys.exit(1)

    try:
        with open(os.path.join(out, BUILD_INFO_NAME), encoding="utf-8") as f:
            bi = json.load(f)
        print(
            f"   🔖 {BUILD_INFO_NAME}: {bi.get('git_short_sha')} built {bi.get('built_at')}" + (" (DIRTY tree)" if bi.get("dirty") else "")
        )
    except Exception:
        pass
    if args.zip_path:
        zip_dir(out, args.zip_path)
        size_mb = os.path.getsize(args.zip_path) / 1e6
        print(f"✅ Zipped → {args.zip_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
