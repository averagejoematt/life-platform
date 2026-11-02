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
  owned-paths    (#5534) the build's committed route manifest www/owned_paths.json and the reach
                 census www/reach.json equal what the clean build just emitted (drift = someone
                 changed a route and did not commit the artifact the deploy excludes by), the
                 static routes are a subset of the built routes, and no built route lands on a
                 kept site/ page outside deploy/www_owned_paths.REPLACED_ROUTES

Usage:
  python3 scripts/check_www_build.py                 # all five, from the fixture snapshot
  python3 scripts/check_www_build.py --scan-only     # scan an existing www/dist (the deploy path)
  python3 scripts/check_www_build.py --no-noindex    # scan a production-base build (Phase 4)
  python3 scripts/check_www_build.py --owned-paths   # only the owned-paths check (one clean build)

Exit: 0 pass · 1 a check failed · 2 a mutation did NOT fail (blind gate) · 3 setup error.
No AWS, no network: `npm ci` must already have run in www/.
"""

from __future__ import annotations

import argparse
import glob
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
OWNED_PATHS = os.path.join(WWW, "owned_paths.json")
REACH = os.path.join(WWW, "reach.json")
sys.path.insert(0, REPO)
from deploy import www_owned_paths  # noqa: E402 — the one reader of owned_paths.json (#5534)

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


TAG = re.compile(r"<[^>]+>")


def raw_ids(snapshot: str = SNAPSHOT) -> set[str]:
    """The coach domain identifiers in the exported snapshot (`coaches.json` → each record's `domain`): snake_case ids
    that a page must render through `domainWords()` (#5568 — `nutrition_science` reached the live
    System page and coach pages on launch day). Derived from the data, never a hand list."""
    out: set[str] = set()
    for path in [os.path.join(snapshot, "coaches.json"), *glob.glob(os.path.join(snapshot, "coach*", "*.json"))]:
        try:
            with open(path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        records = (
            data
            if isinstance(data, list)
            else (data.get("items") or data.get("records") or list(data.values())) if isinstance(data, dict) else []
        )
        for rec in records if isinstance(records, list) else [records]:
            v = rec.get("domain") if isinstance(rec, dict) else None
            if isinstance(v, str) and "_" in v:
                out.add(v)
    return out


def scan(dist: str, require_noindex: bool, forbidden_ids: set[str] | None = None) -> list[str]:
    issues: list[str] = []
    pages = 0
    ids = raw_ids() if forbidden_ids is None else forbidden_ids
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
                    if ids:
                        visible = TAG.sub(" ", text)
                        for raw in sorted(ids):
                            if re.search(rf"(?<![\w-]){re.escape(raw)}(?![\w-])", visible):
                                issues.append(f"{rel}: raw domain id {raw!r} rendered as text (#5568 — route it through domainWords())")
    if pages == 0:
        issues.append("no html pages in dist")
    return issues


def _read_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


def check_owned_paths(committed: dict[str, bytes | None], dist: str = DIST) -> list[str]:
    """#5534 — the committed owned_paths.json / reach.json equal the fresh emit, and the routes are sane.

    `committed` holds the bytes of the two artifacts as they were BEFORE the build (the postbuild
    step rewrites them on every build, so the comparison has to be against a snapshot taken first).
    """
    issues: list[str] = []
    for path in (OWNED_PATHS, REACH):
        before = committed.get(path)
        after = _read_bytes(path)
        rel = os.path.relpath(path, REPO)
        if before is None:
            issues.append(f"{rel}: not committed — run `npm run build` in www/ and commit the file")
        elif after is None:
            issues.append(f"{rel}: the build did not emit it (www/scripts/postbuild.mjs)")
        elif before != after:
            issues.append(f"{rel}: DRIFT — the build emits a different file; commit the regenerated one (the deploy excludes by it)")
    try:
        data = www_owned_paths.load(OWNED_PATHS)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return issues + [f"owned_paths.json unreadable: {exc}"]
    if not isinstance(data.get("live_at_root"), bool):
        issues.append("owned_paths.json: live_at_root must be a boolean (the cut-over switch)")
    missing = sorted(set(data["static_routes"]) - set(data["routes"]))
    if missing:
        issues.append(f"owned_paths.json: static routes not in the built routes: {missing}")
    if "/" not in data["routes"] or "404.html" not in data["files"]:
        issues.append("owned_paths.json: the build must own `/` and 404.html")
    routes, files = www_owned_paths.dist_routes(dist)
    if set(data["routes"]) != routes or not set(files) <= set(data["files"]):
        issues.append("owned_paths.json: routes/files disagree with the dist that was just built")
    for bad in www_owned_paths.collisions(routes, files):
        issues.append(f"collision — {bad}")
    return issues


def main() -> int:
    ap = argparse.ArgumentParser(description="The v9 build gate: reproducible · held · dangling · scan · owned-paths.")
    ap.add_argument("--scan-only", action="store_true", help="only scan the existing www/dist")
    ap.add_argument("--no-noindex", action="store_true", help="production base: do not require noindex")
    ap.add_argument("--owned-paths", action="store_true", help="only the owned-paths drift check (one clean build)")
    ap.add_argument("--dist", default=DIST)
    args = ap.parse_args()
    preview = not args.no_noindex
    if not os.path.isdir(os.path.join(WWW, "node_modules")):
        print("www/node_modules missing — run `npm ci` in www/ first", file=sys.stderr)
        return 3
    # Snapshot the committed artifacts BEFORE anything builds (postbuild rewrites them).
    committed = {OWNED_PATHS: _read_bytes(OWNED_PATHS), REACH: _read_bytes(REACH)}

    if args.owned_paths:
        export_fixture_snapshot()
        if build(preview).returncode != 0:
            log("  ✗ build failed")
            return 1
        log("owned paths")
        issues = check_owned_paths(committed, args.dist)
        for i in issues:
            log(f"  ✗ {i}")
        if issues:
            return 1
        log("  ✓ owned_paths.json + reach.json match the build; no collision outside the replaced set")
        return 0

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
    if not args.scan_only:
        log("owned paths")
        issues = check_owned_paths(committed, args.dist)
        for i in issues:
            log(f"  ✗ {i}")
        if issues:
            return 1
        log("  ✓ owned_paths.json + reach.json match the build; no collision outside the replaced set")
    log("✅ www build gate passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
