#!/usr/bin/env python3
"""scripts/check_www_build.py — the one build-side gate for the v9 site (`www/`, #5530).

Four of the owner's Phase 0 exit criteria are properties of the BUILD, not of a page, so
they are held here, by one entrypoint CI calls once (web-gate.yml) and anyone can run by
hand. Each check is run as a MUTATION where the property is "X must fail": a gate that
cannot fail is a green light wired to nothing (CHARTER §paved roads), so this script
exits 2 — "blind" — if a planted defect builds clean, and never grades on.

  reproducible   export the fixture snapshot, build twice, compare the tree hashes
  held           flip one public object to `held` in the snapshot → `astro build` MUST fail
  dangling       add one edge to a non-existent object → `astro build` MUST fail
  scan           the clean build carries no fixture sentinel, no inline <script>, and
                 (on the preview base) `noindex` on every page

Usage:
  python3 scripts/check_www_build.py                 # all four, from the fixture snapshot
  python3 scripts/check_www_build.py --scan-only     # scan an existing www/dist (the deploy path)
  python3 scripts/check_www_build.py --no-noindex    # scan a production-base build (Phase 4)

Exit: 0 pass · 1 a check failed · 2 a mutation did NOT fail (blind gate) · 3 setup error.
No AWS, no network: `npm ci` must already have run in www/.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(REPO, "www")
DIST = os.path.join(WWW, "dist")
SNAPSHOT = os.path.join(WWW, "content", "snapshot")
SENTINELS = ("SENTINEL", "DO-NOT-PUBLISH", "POISON-HELD")
SCRIPT_TAG = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
NOINDEX = re.compile(r'<meta name="robots" content="noindex', re.IGNORECASE)


def log(msg: str) -> None:
    print(msg, flush=True)


def run(cmd: list[str], cwd: str = WWW, env: dict | None = None) -> subprocess.CompletedProcess:
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    return subprocess.run(cmd, cwd=cwd, env=full_env, capture_output=True, text=True)


def build(preview: bool = True) -> subprocess.CompletedProcess:
    return run(["npm", "run", "build:preview" if preview else "build", "--silent"])


def tree_hash(root: str) -> str:
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            h.update(rel.encode("utf-8"))
            with open(path, "rb") as fh:
                h.update(hashlib.sha256(fh.read()).digest())
    return h.hexdigest()


def export_fixture_snapshot() -> None:
    cp = run([sys.executable, os.path.join(REPO, "scripts", "publish_snapshot.py"), "--mode", "fixture", "--out", SNAPSHOT], cwd=REPO)
    if cp.returncode != 0:
        raise SystemExit(f"fixture export failed (exit {cp.returncode}):\n{cp.stderr[-2000:]}")


def check_reproducible(preview: bool) -> bool:
    export_fixture_snapshot()
    a = build(preview)
    if a.returncode != 0:
        log(f"  ✗ first build failed:\n{a.stderr[-1500:]}")
        return False
    h1 = tree_hash(DIST)
    b = build(preview)
    if b.returncode != 0:
        log(f"  ✗ second build failed:\n{b.stderr[-1500:]}")
        return False
    h2 = tree_hash(DIST)
    ok = h1 == h2
    log(f"  {'✓' if ok else '✗'} reproducible: {h1[:16]}… {'==' if ok else '!='} {h2[:16]}…")
    return ok


def _with_mutated_snapshot(filename: str, mutate, preview: bool) -> tuple[int, str]:
    """Mutate one snapshot file in place, build, restore. Returns (exit, stderr)."""
    path = os.path.join(SNAPSHOT, filename)
    backup = path + ".bak"
    shutil.copyfile(path, backup)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        mutate(data)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        cp = build(preview)
        return cp.returncode, cp.stderr + cp.stdout
    finally:
        shutil.move(backup, path)


def check_held_mutation(preview: bool) -> int:
    """0 = the mutation failed the build (good) · 2 = it built (blind)."""

    def flip(data):
        data[0]["visibility"] = "held"
        data[0]["title"] = "POISON-HELD-TITLE"

    code, out = _with_mutated_snapshot("chapters.json", flip, preview)
    if code == 0:
        log("  ✗ BLIND: a held object built clean")
        return 2
    named = 'expected "public"' in out
    log(f"  ✓ held object refused by the build (exit {code}{', the schema named visibility' if named else ''})")
    return 0


def check_dangling_mutation(preview: bool) -> int:
    def dangle(data):
        data[0]["edges"].append({"type": "metric", "id": "does_not_exist_anywhere"})

    code, out = _with_mutated_snapshot("predictions.json", dangle, preview)
    if code == 0:
        log("  ✗ BLIND: a dangling edge built clean")
        return 2
    named = "dangling edge" in out
    log(f"  ✓ dangling edge refused by the build (exit {code}{', named' if named else ''})")
    return 0


def scan(dist: str, require_noindex: bool) -> list[str]:
    issues: list[str] = []
    pages = 0
    for dirpath, _d, files in os.walk(dist):
        for name in files:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, dist)
            if name.endswith((".html", ".css", ".js", ".json", ".xml", ".txt")):
                text = open(path, encoding="utf-8", errors="replace").read()
                for s in SENTINELS:
                    if s in text:
                        issues.append(f"{rel}: sentinel {s!r}")
                if name.endswith(".html"):
                    pages += 1
                    for tag in SCRIPT_TAG.findall(text):
                        if "src=" not in tag.lower():
                            issues.append(f"{rel}: inline <script>")
                    if require_noindex and not NOINDEX.search(text):
                        issues.append(f"{rel}: missing noindex")
    if pages == 0:
        issues.append("no html pages in dist")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="The v9 build gate: reproducible · held · dangling · scan.")
    ap.add_argument("--scan-only", action="store_true", help="only scan the existing www/dist")
    ap.add_argument("--no-noindex", action="store_true", help="production base: do not require noindex")
    ap.add_argument("--dist", default=DIST)
    args = ap.parse_args()
    preview = not args.no_noindex
    if not os.path.isdir(os.path.join(WWW, "node_modules")):
        print("www/node_modules missing — run `npm ci` in www/ first", file=sys.stderr)
        return 3

    if not args.scan_only:
        log("reproducible build")
        if not check_reproducible(preview):
            return 1
        log("mutation: held object")
        code = check_held_mutation(preview)
        if code:
            return code
        log("mutation: dangling edge")
        code = check_dangling_mutation(preview)
        if code:
            return code
        # the clean build again, so the scan grades what the mutations restored
        if build(preview).returncode != 0:
            log("  ✗ rebuild after the mutations failed")
            return 1

    log("scan")
    issues = scan(args.dist, require_noindex=preview)
    for i in issues:
        log(f"  ✗ {i}")
    if issues:
        return 1
    pages = sum(1 for _d, _s, f in os.walk(args.dist) for n in f if n.endswith(".html"))
    log(f"  ✓ {pages} pages: no sentinel, no inline script{', noindex everywhere' if preview else ''}")
    log("✅ www build gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
