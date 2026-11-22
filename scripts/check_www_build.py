#!/usr/bin/env python3
"""scripts/check_www_build.py — the one build-side gate for the v9 site (`www/`, #5530).

Four of the owner's Phase 0 exit criteria are properties of the BUILD, not of a page, so
they are held here, by one entrypoint CI calls once (web-gate.yml) and anyone can run by
hand. Each check is run as a MUTATION where the property is "X must fail": a gate that
cannot fail is a green light wired to nothing (CHARTER §paved roads), so this script
exits 2 — "blind" — if a planted defect builds clean, and never grades on.

  reproducible   export the fixture snapshot, build twice, compare the tree hashes
  corrections    (#6177) the clean build renders the fixture's approved corrections; a build with them removed must
                 carry byte-identical chapter bodies (a correction sits beside a chapter, never in it)
  held           flip one public object to `held` in the snapshot → `astro build` MUST fail
  dangling       add one edge to a non-existent object → `astro build` MUST fail
  scan           the clean build carries no fixture sentinel, no inline <script>, no ISO date
                 outside a verbatim coach quotation (scripts/www_verbatim.py — the render gate's rule,
                 static, so the LIVE root deploy holds it too), no Coaching Room output beyond what the
                 committed `room_public` publishes (CR1 at "cr1"; CR1 + CR2 at "cr2"; a CR3 page, coach_room.json,
                 a CR3-only key or a private-build banner is refused whatever it says), no Laboratory output (L1, the same: a WEB_LAB=1 dist is
                 refused), no Human Story output (HS1, the same: a WEB_STORY=1 dist is refused), no tile, series or
                 Day label naming a number other than the one it prints (scripts/www_label_contract.py, #5953),
                 and (on the preview base) `noindex`
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
import html as html_lib
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WWW = os.path.join(REPO, "www")
DIST = os.path.join(WWW, "dist")
SNAPSHOT = os.path.join(WWW, "content", "snapshot")
OWNED_PATHS = os.path.join(WWW, "owned_paths.json")
REACH = os.path.join(WWW, "reach.json")
sys.path.insert(0, REPO)
from deploy import www_owned_paths  # noqa: E402 — the one reader of owned_paths.json (#5534)

sys.path.insert(0, os.path.join(REPO, "scripts"))
import www_label_contract  # noqa: E402 — #5953: each tile/series/Day label names the number printed beside it, fixture AND live
import www_launch_switch  # noqa: E402 — the committed go-live constants (LAB_LIVE, STORY_LIVE): a live feature is not a leak
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


_PUBLISHED_BODY = re.compile(
    r"<div data-published-body>([\s\S]*?)</div>\s*(?:<p class=\"muted\"[^>]*data-numbering-note|</article>|<div style=\"margin-top:48px\" id=\"days\")"
)


def published_bodies(dist: str) -> dict[str, str]:
    """{chapter page: the bytes inside its data-published-body} for every built chapter page."""
    out: dict[str, str] = {}
    for path in sorted(glob.glob(os.path.join(dist, "**", "story", "*", "index.html"), recursive=True)):
        with open(path, encoding="utf-8") as fh:
            m = _PUBLISHED_BODY.search(fh.read())
        if m:
            out[os.path.relpath(path, dist)] = m.group(1)
    return out


def check_corrections_mutation(preview: bool) -> int:
    """#6177: a dated public correction is placed BESIDE a chapter, never in it. The clean fixture build renders the
    sample approved corrections; the same build with chapter_corrections.json emptied must carry byte-identical chapter
    bodies — and must NOT carry the corrections (else the comparison proves nothing). 0 ok · 1 a body changed · 2 blind."""
    clean_bodies = published_bodies(DIST)
    clean_has = [p for p in clean_bodies if "data-chapter-corrections" in open(os.path.join(DIST, p), encoding="utf-8").read()]
    if not clean_bodies or not clean_has:
        log("  ✗ BLIND: the clean fixture build renders no chapter body or no correction to compare")
        return 2

    path = os.path.join(SNAPSHOT, "chapter_corrections.json")
    backup = path + ".bak"
    shutil.copyfile(path, backup)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        data["corrections"] = []
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
        cp = build(preview)
        if cp.returncode != 0:
            log(f"  ✗ the build without corrections failed:\n{cp.stderr[-1500:]}")
            return 1
        bare_bodies = published_bodies(DIST)
        still = [p for p in clean_has if "data-chapter-corrections" in open(os.path.join(DIST, p), encoding="utf-8").read()]
    finally:
        shutil.move(backup, path)
    if still:
        log(f"  ✗ BLIND: corrections still rendered with the file emptied: {still}")
        return 2
    changed = sorted(p for p in clean_bodies if bare_bodies.get(p) != clean_bodies[p])
    if changed or set(bare_bodies) != set(clean_bodies):
        log(f"  ✗ a correction changed a chapter's published body: {changed or sorted(set(bare_bodies) ^ set(clean_bodies))}")
        return 1
    log(f"  ✓ corrections render beside {len(clean_has)} chapter(s); all {len(clean_bodies)} chapter bodies byte-identical without them")
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
    issues.extend(spark_agreement(dist))
    issues.extend(chapter_agreement(dist))
    issues.extend(www_label_contract.issues(dist, snapshot_dir))
    issues.extend(room_leaks(dist))
    issues.extend(lab_leaks(dist))
    issues.extend(story_leaks(dist))
    issues.extend(readercall_leaks(dist))
    issues.extend(own_words_scope(dist, snapshot_dir))
    return issues


OWN_WORDS_JS = os.path.join(WWW, "src", "lib", "own_words.js")
_OWN_ENTRY = re.compile(
    r'^  (\w+): \{\s*date: "(\d{4}-\d{2}-\d{2})",\s*text: "((?:[^"\\\\]|\\\\.)*)",\s*sk: "([^"]+)",\s*scope: \[([^\]]*)\]', re.MULTILINE
)


def own_words_pins(own_js: str = OWN_WORDS_JS) -> dict[str, dict]:
    """The owner's approved lines as pinned in www/src/lib/own_words.js: key → {date, text, sk, scope}. Read off the
    file, never a hand copy; an unreadable file is no pins (and `own_words_scope` then refuses every served line)."""
    try:
        src = open(own_js, encoding="utf-8").read()
    except OSError:
        return {}
    pins = {}
    for key, day, text, sk, scope in _OWN_ENTRY.findall(src):
        pins[key] = {"date": day, "text": json.loads(f'"{text}"'), "sk": sk, "scope": re.findall(r'"([^"]+)"', scope)}
    return pins


def _scope_re(pattern: str) -> re.Pattern:
    return re.compile("^" + "[^/]+".join(re.escape(p) for p in pattern.split("*")) + "$")


def own_words_scope(dist: str, snapshot_dir: str = SNAPSHOT, own_js: str = OWN_WORDS_JS) -> list[str]:
    """His own words appear only where he approved them (owner ruling 2026-11-15). A built page may show one of the
    owner's first-person lines only when (a) the line is pinned in own_words.js, (b) the page is inside that pin's
    scope, and (c) the snapshot's own_words.json — the platform's /api/journal_quotes — serves that day and those words
    exactly. A served line with no pin is shown nowhere. Runs on every build and on the deploy's scan, so a revoked
    line, a line moved to a page he did not name, or a line edited by one character cannot reach the site."""
    pins = own_words_pins(own_js)
    try:
        with open(os.path.join(snapshot_dir, "own_words.json"), encoding="utf-8") as fh:
            doc = json.load(fh)
    except (OSError, ValueError):
        doc = {}
    served = (
        {(q.get("date"), q.get("quote")) for q in (doc.get("quotes") or []) if isinstance(q, dict)} if doc.get("state") == "ok" else set()
    )
    pinned_texts = {(p["date"], p["text"]) for p in pins.values()}
    out = []
    for dirpath, _d, files in os.walk(dist):
        for name in files:
            if not name.endswith(".html"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), dist)
            route = "/" + (os.path.dirname(rel) + "/" if os.path.dirname(rel) else "")
            page = html_lib.unescape(open(os.path.join(dirpath, name), encoding="utf-8", errors="replace").read())
            for key in sorted(set(re.findall(r'data-own-words="([^"]+)"', page))):
                if key not in pins:
                    out.append(f"{rel}: an own-words placement {key!r} that own_words.js does not pin")
            for key, pin in sorted(pins.items()):
                if pin["text"] not in page:
                    continue
                if not any(_scope_re(s).match(route) for s in pin["scope"]):
                    out.append(f"{rel}: the owner's line {key!r} is shown outside the page(s) he approved it for {pin['scope']}")
                if (pin["date"], pin["text"]) not in served:
                    out.append(f"{rel}: the owner's line {key!r} is shown but the snapshot does not serve it (revoked, or never marked)")
            for day, words in sorted(served - pinned_texts):
                if words and words in page:
                    out.append(f"{rel}: a served line of {day} with no approved placement is on the page")
    return out


ROOM_JS = os.path.join(WWW, "src", "lib", "room.js")


def room_paths(room_js: str = ROOM_JS) -> list[str]:
    """The Coaching Room's routes, read off www/src/lib/room.js (ROOM_ROUTES' `path:` values) — never a hand list."""
    try:
        text = open(room_js, encoding="utf-8").read()
    except OSError:
        return []
    return re.findall(r'\bpath:\s*"(/[^"]+/)"', text)


def room_routes(room_js: str = ROOM_JS) -> list[tuple[str, str]]:
    """``(path, release)`` per room route, read off www/src/lib/room.js — "cr1" ships with the calibration page; any
    other release (cr2, cr3) is never published by the committed switch. A route without a release reads as unpublishable."""
    try:
        text = open(room_js, encoding="utf-8").read()
    except OSError:
        return []
    out = []
    for m in re.finditer(r"\{[^{}]*?\bpath:\s*\"(/[^\"]+/)\"[^{}]*\}", text):
        rel = re.search(r'\brelease:\s*"(\w+)"', m.group(0))
        out.append((m.group(1), rel.group(1) if rel else "unreleased"))
    return out


def _room_list(name: str, room_js: str = ROOM_JS) -> list[str]:
    """A string-array constant of www/src/lib/room.js (CR1_MARKERS, CR23_DATA_KEYS, CR23_DATA_FILES) — never a hand list."""
    try:
        text = open(room_js, encoding="utf-8").read()
    except OSError:
        return []
    m = re.search(rf"export const {re.escape(name)}\s*=\s*\[([^\]]*)\]", text)
    return re.findall(r'"([^"]+)"', m.group(1)) if m else []


def room_data_files(room_js: str = ROOM_JS) -> list[str]:
    """The room's data-file names, read off www/src/lib/room.js (ROOM_DATA_FILES) — never a hand list."""
    return [f for f in _room_list("ROOM_DATA_FILES", room_js) if f.endswith(".json")]


def _room_dirs(dist: str, path: str) -> list[str]:
    """The dist directories one room path names. A `[param]` segment (CR2's per-coach record) is one directory level:
    it becomes a glob `*`, with every glob metacharacter in the literal parts escaped."""
    parts = re.split(r"(\[[^\]]+\])", path.strip("/"))
    pattern = "".join("*" if re.fullmatch(r"\[[^\]]+\]", s) else glob.escape(s) for s in parts)
    # directories only: `system/docket/[id]/` must not read the docket's own index.html as an entry (CR3)
    return sorted(d for d in glob.glob(os.path.join(glob.escape(dist), pattern)) if os.path.isdir(d))


ROOM_MARKER_RX = re.compile(r'\bdata-room="([^"]*)"')
ROOM_PRIVATE_MARKER = "data-room-private"


def room_leaks(dist: str, room_js: str = ROOM_JS, published: str | None = None) -> list[str]:
    """The Coaching Room in a dist the deploy is about to sync. `published` is the committed switch (www/owned_paths.json
    `room_public`, read through deploy/www_owned_paths.py when None): "off", "cr1" (owner GO 2026-11-10) or "cr2" (owner
    GO 2026-11-11, second message).

      * off: no room page, no room data file, no `data-room` marker — a room build is private and never deployed;
      * cr1: the CR1 pages (/system/calibration/, /system/ledger/refuted/) and the CR1 markers (calibration, refuted,
        entry) are allowed; a CR2/CR3 page, a CR2/CR3 marker or a CR2/CR3-only key is still refused;
      * cr2: CR1, plus each coach's record page (/system/coaches/<id>/record/) and the CR2 markers (coach-record,
        coach-entry); a CR3 page, a CR3 marker or a CR3-only (docket) key is still refused;
      * always: the room's data files (calibration.json is CR1's and may ride a published dist; coach_room.json never),
        the private-build banner (`data-room-private`, every WEB_ROOM build) and every CR3-only data key.

    This scan runs on every deploy (`--scan-only`). www/tests/room.test.mjs holds the finer checks."""
    if published is None:
        published = www_owned_paths.room_public()
    published = published if published in ("cr1", "cr2") else "off"
    releases = {"off": set(), "cr1": {"cr1"}, "cr2": {"cr1", "cr2"}}[published]
    out = []
    data_files = set(room_data_files(room_js))
    allowed_files = {"calibration.json"} if published != "off" else set()
    markers = set()
    if published in ("cr1", "cr2"):
        markers |= set(_room_list("CR1_MARKERS", room_js))
    if published == "cr2":
        markers |= set(_room_list("CR2_MARKERS", room_js))
    cr2_keys = _room_list("CR2_DATA_KEYS", room_js)
    cr3_keys = _room_list("CR3_DATA_KEYS", room_js)
    refused_keys = cr3_keys + ([] if published == "cr2" else cr2_keys)
    for p, release in room_routes(room_js):
        if release in releases:
            continue
        for d in _room_dirs(dist, p):
            rel = os.path.relpath(d, dist)
            if published != "off":
                out.append(f"{rel}/: a {release.upper()} Coaching Room page in the dist — not published (room_public={published})")
            else:
                out.append(f"{rel}/: a Coaching Room page in the dist — a room build is private and is never deployed (room_public=off)")
    for dirpath, _d, files in os.walk(dist):
        for name in files:
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, dist)
            if name in data_files and name not in allowed_files:
                out.append(f"{rel}: the Coaching Room's data file in the dist")
                continue
            if not name.endswith((".html", ".json", ".js", ".xml", ".txt")):
                continue
            text = open(path, encoding="utf-8", errors="replace").read()
            for k in refused_keys:
                if f'"{k}"' in text or f"&quot;{k}&quot;" in text or f"&#34;{k}&#34;" in text:
                    kind = "CR3" if published == "cr2" else "CR2/CR3"
                    out.append(f"{rel}: carries the {kind}-only key {k!r}")
            if not name.endswith(".html"):
                continue
            if ROOM_PRIVATE_MARKER in text:
                out.append(f"{rel}: carries the private-build banner {ROOM_PRIVATE_MARKER} — a WEB_ROOM build is never deployed")
            for v in sorted(set(ROOM_MARKER_RX.findall(text))):
                if v not in markers:
                    out.append(f"{rel}: carries the Coaching Room marker data-room={v!r} — not published (room_public={published})")
    return out


LAB_JS = os.path.join(WWW, "src", "lib", "lab.js")


def lab_leaks(dist: str, lab_js: str = LAB_JS, live: bool | None = None) -> list[str]:
    """L1 (built dark, owner brief 2026-11-08): the Laboratory is NEVER deployed — the room's rule for its own switch. A
    dist that holds anything under a Lab route (read off www/src/lib/lab.js LAB_ROUTES' `path:` values), the Lab's data
    file or the `data-lab` marker is a WEB_LAB=1 build and is refused here, on every deploy (`--scan-only`).
    www/tests/lab.test.mjs holds the finer flag-off checks.
    Once the owner's go commits LAB_LIVE (www/src/lib/lab.js, read by scripts/www_launch_switch.py) the Lab's pages and
    marker are ordinary build output and are not refused; the data file is never build output, live or not."""
    live = www_launch_switch.lab_live(lab_js) if live is None else live
    out = []
    for p in [] if live else sorted(set(room_paths(lab_js))):
        if os.path.exists(os.path.join(dist, p.strip("/"))):
            out.append(f"{p.strip('/')}/: a Laboratory page in the dist — a WEB_LAB=1 build is private and is never deployed")
    for dirpath, _d, files in os.walk(dist):
        for name in files:
            rel = os.path.relpath(os.path.join(dirpath, name), dist)
            if name == "lab.json":
                out.append(f"{rel}: the Laboratory's data file in the dist")
            elif (
                not live
                and name.endswith(".html")
                and 'data-lab="' in open(os.path.join(dirpath, name), encoding="utf-8", errors="replace").read()
            ):
                out.append(f"{rel}: carries the Laboratory marker data-lab — a WEB_LAB=1 build is never deployed")
    return out


STORY_JS = os.path.join(WWW, "src", "lib", "story_dark.js")


def story_leaks(dist: str, story_js: str = STORY_JS, live: bool | None = None) -> list[str]:
    """HS1 (built dark, owner brief 2026-11-08): the Human Story's timeline and episode index are NEVER deployed. A dist
    that holds a story page, the story's data file or the data-story-dark marker is a WEB_STORY=1 build; this scan runs
    on every deploy (`--scan-only`), so such a dist is refused before it can reach S3. www/tests/story_dark.test.mjs
    holds the finer flag-off checks. The routes are read off story_dark.js (STORY_ROUTES' `path:` values).
    Once the owner's go commits STORY_LIVE (read by scripts/www_launch_switch.py) the story's pages and marker are
    ordinary build output and are not refused; the data file is never build output, live or not."""
    live = www_launch_switch.story_live(story_js) if live is None else live
    out = []
    for p in [] if live else room_paths(story_js):
        if os.path.exists(os.path.join(dist, p.strip("/"))):
            out.append(f"{p.strip('/')}/: a Human Story page in the dist — a WEB_STORY=1 build is private and is never deployed")
    for dirpath, _d, files in os.walk(dist):
        for name in files:
            rel = os.path.relpath(os.path.join(dirpath, name), dist)
            if name == "story.json":
                out.append(f"{rel}: the Human Story's data file in the dist")
            elif (
                not live
                and name.endswith(".html")
                and 'data-story-dark="' in open(os.path.join(dirpath, name), encoding="utf-8", errors="replace").read()
            ):
                out.append(f"{rel}: carries the Human Story marker data-story-dark — a WEB_STORY=1 build is never deployed")
    return out


READERCALL_NEEDLES = ("data-readercall", "/api/reader_call")


def readercall_leaks(dist: str, live: bool | None = None) -> list[str]:
    """#6088 (built dark, owner ruling 2026-11-16: develop and test privately): while dark, the reader-call control is
    never deployed. A dist with the control's marker (`data-readercall`, on the page and in the island's chunk) or its route
    (`/api/reader_call`) in any page, script or data file is a WEB_READERCALL=1 build; this scan runs on every deploy
    (`--scan-only`), so such a dist is refused before it can reach S3. #6114: once READERCALL_LIVE is committed true (read by
    scripts/www_launch_switch.py, unreadable = dark) the control is ordinary build output and is not refused."""
    live = www_launch_switch.readercall_live() if live is None else live
    if live:
        return []
    out = []
    for dirpath, _d, files in os.walk(dist):
        for name in files:
            if not name.endswith((".html", ".js", ".mjs", ".json", ".xml")):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), dist)
            text = open(os.path.join(dirpath, name), encoding="utf-8", errors="replace").read()
            hits = [n for n in READERCALL_NEEDLES if n in text]
            if hits:
                out.append(f"{rel}: carries {', '.join(hits)} — a WEB_READERCALL=1 build is private and is never deployed")
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


_SPARK = re.compile(r'<span class="spark"[^>]*data-spark-of="([^"]+)"(?:[^>]*data-latest="([^"]*)")?[^>]*>(<svg[\s\S]*?</svg>)')


def spark_agreement(dist: str) -> list[str]:
    """One series, one picture (review 2026-11-14 dataviz-2; owner ruling 2026-11-14: "identical measurements presented
    in multiple places"). Every metric whose weekly spark is drawn on BOTH the front page and the data room must be the
    same SVG and the same latest reading on both: the two doors once scaled the same eight weekly means differently, so
    one read as flat and the other as a collapse. The spark comes from www/src/lib/spark.js on both; this is the build's
    own check that a page has not grown a scale of its own."""
    seen: dict[str, dict[str, tuple[str, str]]] = {}
    for page in ("index.html", os.path.join("data", "index.html")):
        path = os.path.join(dist, page)
        if not os.path.exists(path):
            continue
        for metric, latest, svg in _SPARK.findall(open(path, encoding="utf-8").read()):
            seen.setdefault(metric, {})[page] = (svg, latest)
    out = []
    for metric, pages in sorted(seen.items()):
        if len(pages) < 2:
            continue
        (pa, (svg_a, latest_a)), (pb, (svg_b, latest_b)) = sorted(pages.items())
        if svg_a != svg_b:
            out.append(f"{metric}: its weekly spark differs between {pa} and {pb} — one series must be one picture (lib/spark.js)")
        if latest_a != latest_b:
            out.append(f"{metric}: latest reading {latest_a!r} on {pa} but {latest_b!r} on {pb}")
    return out


# ── One chapter, one name (#6081) ──────────────────────────────────────────────────────────────────────────────────
# Every page that names a chapter marks it: an element carrying data-chapter="<id>" holds the number (data-ch-no, or the
# moment card's data-ch-week), the days (data-ch-window) and the publication (data-published) it prints. The chapter page
# is the reference; every other page in the set must print the same three, short forms read as their long forms.
_CH_FIELDS = ("data-ch-no", "data-ch-week", "data-ch-window", "data-published")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")
_SPELLED = "no one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty".split()


class _ChapterMarks(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth, self.open, self.field, self.marks, self.counts, self.nexts = 0, [], None, [], [], []
        self.loose = None  # a data-ch-count / data-next-chapter being read

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in _VOID:
            return
        self.depth += 1
        if "data-chapter" in a and a["data-chapter"]:
            self.open.append(
                {"id": a["data-chapter"], "status": a.get("data-status"), "tag": tag, "href": a.get("href"), "at": self.depth, "f": {}}
            )
            self.marks.append(self.open[-1])
        if "data-next-chapter" in a:
            self.nexts.append(a["data-next-chapter"] or "")
        if "data-ch-count" in a and self.loose is None:
            self.loose = [self.depth, ""]
        hit = next((k for k in _CH_FIELDS if k in a), None)
        if hit and self.open and self.field is None:
            self.field = [hit, self.depth, ""]

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        if self.field and self.depth == self.field[1]:
            self.open[-1]["f"][self.field[0]] = self.field[2]
            self.field = None
        if self.loose and self.depth == self.loose[0]:
            self.counts.append(self.loose[1])
            self.loose = None
        if self.open and self.depth == self.open[-1]["at"]:
            self.open.pop()
        self.depth -= 1

    def handle_data(self, data):
        if self.field:
            self.field[2] += data
        if self.loose:
            self.loose[1] += data


def _norm_number(key: str, text: str) -> str | None:
    t = " ".join(text.split())
    if key == "data-ch-week" and t.lower().startswith("prologue"):
        return "00"
    m = re.search(r"\d+", t)
    return m.group(0).zfill(2) if m else None


def _norm_window(text: str) -> str:
    t = " ".join(text.split())
    for full in _MONTHS:
        t = re.sub(rf"\b{full[:3]}\b(?!\w)", full, t)
    head, _, dates = t.rpartition(" · ") if t.lower().startswith("day") else ("", "", t)
    pre = re.match(r"(program week )?(.*)$", dates)
    dates = re.sub(r"^(\d+)–(\d+) ", r"\1 to \2 ", pre.group(2).replace(" – ", " to "))
    return (f"{head} · " if head else "") + (pre.group(1) or "") + dates


def _norm_count(text: str) -> str:
    words = " ".join(text.lower().split()).split(" ")
    return " ".join(str(_SPELLED.index(w)) if w in _SPELLED else w for w in words)


def chapter_agreement(dist: str) -> list[str]:
    """#6081 — one number, one window and one publication date for a chapter on every page that names it (the front page,
    /story/, the chapter page, /story/so-far/, /story/moments/); the count of chapters said once; the next chapter's
    number the one /story/ lists unpublished; no unpublished /story/ row linking to another chapter's address."""

    def marks(rel):
        path = os.path.join(dist, rel)
        if not os.path.exists(path):
            return None
        p = _ChapterMarks()
        p.feed(open(path, encoding="utf-8").read())
        return p

    out: list[str] = []
    ref: dict[str, dict] = {}
    for path in sorted(glob.glob(os.path.join(glob.escape(dist), "story", "*", "index.html"))):
        rel = os.path.relpath(path, dist)
        p = marks(rel)
        own = [m for m in p.marks if m["id"] == os.path.basename(os.path.dirname(path))] if p else []
        if own:
            ref[own[0]["id"]] = own[0]
    pages = {rel: marks(rel) for rel in ("index.html", "story/index.html", "story/so-far/index.html", "story/moments/index.html")}
    want = lambda m, k: m["f"].get(k)  # noqa: E731
    for rel, p in pages.items():
        for m in p.marks if p else []:
            r = ref.get(m["id"])
            if r is None:
                if m["tag"] == "a" and m["href"] and not m["href"].rstrip("/").endswith(f"/story/{m['id']}"):
                    out.append(f"{rel}: the {m['status']} row {m['id']} links to {m['href']}, another chapter's address")
                continue
            got_no = (
                _norm_number("data-ch-no", m["f"]["data-ch-no"])
                if "data-ch-no" in m["f"]
                else _norm_number("data-ch-week", m["f"].get("data-ch-week", ""))
            )
            if got_no != _norm_number("data-ch-no", want(r, "data-ch-no") or ""):
                out.append(f"{rel}: {m['id']} is numbered {got_no!r}, its page {_norm_number('data-ch-no', want(r, 'data-ch-no') or '')!r}")
            for key, norm in (("data-ch-window", _norm_window), ("data-published", lambda t: " ".join(t.lower().split()))):
                a, b = want(m, key), want(r, key)
                if (a is None) != (b is None) or (a is not None and norm(a) != norm(b)):
                    out.append(f"{rel}: {m['id']} {key[5:]} {a!r}, its page {b!r}")
    for cid, r in sorted(ref.items()):
        if r["status"] != "published":
            continue
        for rel in ("story/index.html", "story/so-far/index.html"):
            if pages[rel] is not None and not any(m["id"] == cid for m in pages[rel].marks):
                out.append(f"{rel}: the published chapter {cid} is not named")
    story = pages["story/index.html"]
    if story is not None and not story.marks:
        out.append("story/index.html: names no chapter with data-chapter — the chapter agreement cannot be read (#6081)")
    for m in story.marks if story else []:
        if m["status"] == "published" and m["id"] not in ref:
            out.append(f"story/index.html: {m['id']} is listed published but its page carries no chapter marks")
    counts = {_norm_count(c) for p in pages.values() if p for c in p.counts}
    if len(counts) > 1:
        out.append(f"the chapters are counted {len(counts)} ways: {sorted(counts)}")
    pending = {
        _norm_number("data-ch-no", m["f"].get("data-ch-no", "")) for m in (story.marks if story else []) if m["status"] != "published"
    }
    for n in {x for p in pages.values() if p for x in p.nexts if x}:
        if n.zfill(2) not in pending:
            out.append(f"index.html: the next chapter is numbered {n}, which /story/ does not list as an unpublished week")
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
    if data.get("room_public") not in www_owned_paths.ROOM_PUBLIC_VALUES:
        issues.append(f"owned_paths.json: room_public must be one of {www_owned_paths.ROOM_PUBLIC_VALUES} (the Coaching Room's switch)")
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
        log("corrections beside the text (#6177)")
        code = check_corrections_mutation(preview)
        if code:
            return code
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
    blind = www_label_contract.self_test()
    if blind:
        log(f"  ✗ BLIND: the label contract missed a planted wrong label: {blind}")
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
