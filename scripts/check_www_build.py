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
  scan           the clean build carries no fixture sentinel, no inline <script>, no ISO date
                 outside a verbatim coach quotation (scripts/www_verbatim.py — the render gate's rule,
                 static, so the LIVE root deploy holds it too), no Coaching Room output (CR1 is built dark:
                 a WEB_ROOM=1 dist is refused), no Laboratory output (L1, the same: a WEB_LAB=1 dist is
                 refused), and (on the preview base) `noindex`
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

sys.path.insert(0, os.path.join(REPO, "scripts"))
import www_verbatim  # noqa: E402 — dates in words, quote-aware (owner ruling 2026-11-02); a page-universal rule, fixture AND live

SENTINELS = ("SENTINEL", "DO-NOT-PUBLISH", "POISON-HELD")
SAMPLE_CHIP = "Sample content, for layout only"  # fixture-only (#5581): on a LIVE build it is a false claim on a real page
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
            pid = rec.get("id") if isinstance(rec, dict) else None
            if isinstance(pid, str) and pid.endswith("_coach"):
                out.add(pid)  # #5572: a persona id is never prose; render the coach's name
    return out


def snapshot_mode(snapshot_dir: str = SNAPSHOT) -> str | None:
    try:
        with open(os.path.join(snapshot_dir, "manifest.json"), encoding="utf-8") as fh:
            return json.load(fh).get("mode")
    except (OSError, ValueError, AttributeError):
        return None


def scan(dist: str, require_noindex: bool, forbidden_ids: set[str] | None = None, snapshot_dir: str = SNAPSHOT) -> list[str]:
    issues: list[str] = []
    live = snapshot_mode(snapshot_dir) == "live"
    pages = 0
    ids = raw_ids() if forbidden_ids is None else forbidden_ids
    quotes = www_verbatim.verbatim_strings(snapshot_dir)  # the coach strings this build was made from
    for dirpath, _d, files in os.walk(dist):
        for name in files:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, dist)
            if name.endswith((".html", ".css", ".js", ".json", ".xml", ".txt")):
                text = open(path, encoding="utf-8", errors="replace").read()
                for s in SENTINELS:
                    if s in text:
                        issues.append(f"{rel}: sentinel {s!r}")
                if live and SAMPLE_CHIP in text:
                    issues.append(f"{rel}: fixture-only {SAMPLE_CHIP!r} on a LIVE build (#5581)")
                if name.endswith(".html"):
                    pages += 1
                    for tag in SCRIPT_TAG.findall(text):
                        if "src=" not in tag.lower():
                            issues.append(f"{rel}: inline <script>")
                    issues.extend(www_verbatim.page_issues(text, rel, quotes))
                    if require_noindex and not NOINDEX.search(text):
                        issues.append(f"{rel}: missing noindex")
                    if ids:
                        visible = TAG.sub(" ", text)
                        for raw in sorted(ids):
                            if re.search(rf"(?<![\w-]){re.escape(raw)}(?![\w-])", visible):
                                issues.append(f"{rel}: raw id {raw!r} rendered as text (#5568 domainWords() / #5572 coach name)")
    if pages == 0:
        issues.append("no html pages in dist")
    issues.extend(heart_coverage(dist, fixture=snapshot_mode(snapshot_dir) == "fixture"))
    issues.extend(room_leaks(dist))
    issues.extend(lab_leaks(dist))
    return issues


ROOM_JS = os.path.join(WWW, "src", "lib", "room.js")


def room_paths(room_js: str = ROOM_JS) -> list[str]:
    """The Coaching Room's routes, read off www/src/lib/room.js (ROOM_ROUTES' `path:` values) — never a hand list."""
    try:
        text = open(room_js, encoding="utf-8").read()
    except OSError:
        return []
    return re.findall(r'\bpath:\s*"(/[^"]+/)"', text)


def room_data_files(room_js: str = ROOM_JS) -> list[str]:
    """The room's data-file names, read off www/src/lib/room.js (ROOM_DATA_FILES) — never a hand list."""
    try:
        text = open(room_js, encoding="utf-8").read()
    except OSError:
        return []
    m = re.search(r"ROOM_DATA_FILES\s*=\s*\[([^\]]*)\]", text)
    return re.findall(r'"([^"]+\.json)"', m.group(1)) if m else []


def _room_dirs(dist: str, path: str) -> list[str]:
    """The dist directories one room path names. A `[param]` segment (CR2's per-coach record) is one directory level:
    it becomes a glob `*`, with every glob metacharacter in the literal parts escaped."""
    parts = re.split(r"(\[[^\]]+\])", path.strip("/"))
    pattern = "".join("*" if re.fullmatch(r"\[[^\]]+\]", s) else glob.escape(s) for s in parts)
    return sorted(glob.glob(os.path.join(glob.escape(dist), pattern)))


def room_leaks(dist: str, room_js: str = ROOM_JS) -> list[str]:
    """CR1 (built dark, owner ruling 2026-11-08): the Coaching Room is NEVER deployed. A dist that holds a room page, the
    room's data file or the room marker is a WEB_ROOM=1 build; this scan runs on every deploy (`--scan-only`), so such a
    dist is refused before it can reach S3. www/tests/room.test.mjs holds the finer flag-off checks."""
    out = []
    data_files = set(room_data_files(room_js))
    for p in room_paths(room_js):
        for d in _room_dirs(dist, p):
            rel = os.path.relpath(d, dist)
            out.append(f"{rel}/: a Coaching Room page in the dist — a WEB_ROOM=1 build is private and is never deployed")
    for dirpath, _d, files in os.walk(dist):
        for name in files:
            rel = os.path.relpath(os.path.join(dirpath, name), dist)
            if name in data_files:
                out.append(f"{rel}: the Coaching Room's data file in the dist")
            elif name.endswith(".html") and 'data-room="' in open(os.path.join(dirpath, name), encoding="utf-8", errors="replace").read():
                out.append(f"{rel}: carries the Coaching Room marker data-room — a WEB_ROOM=1 build is never deployed")
    return out


LAB_JS = os.path.join(WWW, "src", "lib", "lab.js")


def lab_leaks(dist: str, lab_js: str = LAB_JS) -> list[str]:
    """L1 (built dark, owner brief 2026-11-08): the Laboratory is NEVER deployed — the room's rule for its own switch. A
    dist that holds anything under a Lab route (read off www/src/lib/lab.js LAB_ROUTES' `path:` values), the Lab's data
    file or the `data-lab` marker is a WEB_LAB=1 build and is refused here, on every deploy (`--scan-only`).
    www/tests/lab.test.mjs holds the finer flag-off checks."""
    out = []
    for p in sorted(set(room_paths(lab_js))):
        if os.path.exists(os.path.join(dist, p.strip("/"))):
            out.append(f"{p.strip('/')}/: a Laboratory page in the dist — a WEB_LAB=1 build is private and is never deployed")
    for dirpath, _d, files in os.walk(dist):
        for name in files:
            rel = os.path.relpath(os.path.join(dirpath, name), dist)
            if name == "lab.json":
                out.append(f"{rel}: the Laboratory's data file in the dist")
            elif name.endswith(".html") and 'data-lab="' in open(os.path.join(dirpath, name), encoding="utf-8", errors="replace").read():
                out.append(f"{rel}: carries the Laboratory marker data-lab — a WEB_LAB=1 build is never deployed")
    return out


HEART_CHARTS = ("Resting heart rate", "Heart-rate variability")


def heart_coverage(dist: str, fixture: bool = True) -> list[str]:
    """The Journey carries BOTH heart charts with inspectable points (resting HR and HRV). On the FIXTURE build the front
    page must not link the HRV metric either: the fixture keeps HRV inside journey.json so the reach ratchet's link
    budget is unchanged (#5598; acceptance item 7). A live build publishes the real HRV metric, which Start has always
    linked — that half applies to the fixture only (the first root deploy of #5604 refused on it, run 41519666090).
    A build without the Journey page (an absent journey) is not graded here."""
    path = os.path.join(dist, "data", "journey", "index.html")
    if not os.path.exists(path):
        return []
    html = open(path, encoding="utf-8").read()
    out = []
    figures = re.findall(r"<figure[^>]*data-heart[\s\S]*?</figure>", html)
    for name in HEART_CHARTS:
        fig = next((f for f in figures if name in f), None)
        if fig is None:
            out.append(f"data/journey/index.html: the {name} chart is missing (#5598 heart coverage)")
        elif "data-points" not in fig or 'data-points="[]"' in fig:
            out.append(f"data/journey/index.html: the {name} chart has no inspectable points")
    front = os.path.join(dist, "index.html")
    if fixture and os.path.exists(front) and re.search(r'href="[^"]*/data/hrv/"', open(front, encoding="utf-8").read()):
        out.append("index.html: the front page links /data/hrv/ — HRV coverage must not move Start's link budget (#5598)")
    return out


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
    blind = www_verbatim.self_test()
    if blind:
        log(f"  ✗ BLIND: the dates-in-words rule misjudged its planted cases: {blind}")
        return 2
    issues = scan(args.dist, require_noindex=preview)
    for i in issues:
        log(f"  ✗ {i}")
    if issues:
        return 1
    pages = sum(1 for _d, _s, f in os.walk(args.dist) for n in f if n.endswith(".html"))
    log(
        f"  ✓ {pages} pages: no sentinel, no inline script, dates in words outside verbatim quotations{', noindex everywhere' if preview else ''}"
    )
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
