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
import os
import shutil
import sys
import zipfile

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="staging directory (recreated fresh)")
    ap.add_argument("--mcp", action="store_true", help="stage the MCP bundle shape")
    ap.add_argument("--zip", dest="zip_path", help="also produce a zip at this path")
    args = ap.parse_args()

    out = stage_mcp(args.out) if args.mcp else stage_tree(args.out)
    n_files = sum(len(f) for _, _, f in os.walk(out))
    print(f"✅ Staged {'mcp' if args.mcp else 'tree'} bundle: {n_files} files → {out}")
    if args.zip_path:
        zip_dir(out, args.zip_path)
        size_mb = os.path.getsize(args.zip_path) / 1e6
        print(f"✅ Zipped → {args.zip_path} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
