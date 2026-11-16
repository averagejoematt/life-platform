#!/usr/bin/env python3
"""scripts/check_public_copies.py — every public copy of the site, held to the rules the root is held to (#6083).

A privacy fix to the root is not finished while another address still serves the old content. On 2026-11-15 two did:
the rehearsal preview `/next/v9/` (ten days stale, plus 500 call pages on retired addresses — the sync never deletes)
and the nightly archive `/archive/latest.tar.gz` (pre-fix API responses, and every stale preview page, re-published
nightly). This is the one guard over all of them (owner ruling 2026-11-16): a declared inventory and four rules.

THE INVENTORY (`COPIES`, derived from the bucket listing; `PUBLIC_RESOURCES` and `ORIGIN_PATHS` classify every
anonymously readable resource in deploy/bucket_policy.json and every S3 origin path in cdk/stacks/web_stack.py, and
tests/test_check_public_copies_6083.py fails on one that is not classified — guard the set, not the instance):

  root      the v9 build's documents at site/            (rules A C D)
  preview   site/next/v9/                                  (rules A B C)
  legacy    site/ documents the v9 build does not own      (rules C D; the location check)
  retired   site/_v9_previous/ — the old public rollback copy, retired 2026-11-14   (rule B: must hold nothing)
  archive   /archive/latest.tar.gz (generated/archive/)    (rules A B C)
  private, not in scope: www-previous/ (the rollback copies since 2026-11-14), backups/, and prior object versions —
  no anonymous s3:GetObject / s3:GetObjectVersion is granted on them (deploy/bucket_policy.json; GET answers 403).

THE RULES
  A  no orphans: a document under a v9 copy root that the root's NEWEST build did not write. `aws s3 sync` re-uploads
     every file of a fresh build (its mtime is newer), so a document older than the build marker (the root's
     index.html) by more than SYNC_WINDOW is one the build no longer writes. The archive's form: a member the current
     admission registry refuses, or whose object is no longer served.
  B  no stale copy: the preview is EMPTY outside a rehearsal, or no more than PREVIEW_MAX_LAG behind the root (the
     2026-11-16 decision, www/README.md § Deploy); a retired location holds nothing; the archive is younger than
     ARCHIVE_MAX_AGE (--check) or newer than the newest root and preview builds (--remediation).
  C  the publication policy on every copy, against a FRESH live snapshot (scripts/publish_snapshot.py --mode live —
     what the API will not serve today, no copy may show): check_www_build's publication members (sentinels,
     own_words_scope, room/lab/story leaks) over each copy's documents; qa/age_inversion_lib.py::audit over the
     archive's api/ members; and no archived api/ record carries words for a record the live route serves without.
     The build's correctness members (label contract, chapter agreement, dates in words) are NOT re-run on a copy: the
     build gated them pre-sync, and against a later snapshot they move with the daily data, not with a publication.
  D  every URL in the sitemaps and feeds resolves to an object that is served and is not a rule-A orphan.

Usage:
  python3 scripts/check_public_copies.py --check          # read-only; exit 1 on any violation (the deploy's gate)
  python3 scripts/check_public_copies.py --remediation    # + the stricter archive rule; prints the commands a human runs
  [--snapshot DIR] reuse a live snapshot · [--github-output] write summary= for the workflow's rollback scope check

Read-only by construction: s3:ListBucket (the read-only role) and anonymous HTTPS GETs. It writes nothing anywhere
but a temp dir, and it never runs a remediation command — it prints them (deploy/quarantine_public_copy.sh is the
human's, attended). Exit: 0 clean · 1 a violation · 3 setup error (listing or download failed).
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (REPO, os.path.join(REPO, "scripts"), os.path.join(REPO, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_www_build  # noqa: E402 — the build scan's publication members
from operational import public_archive_registry as reg  # noqa: E402 — the archive's admission rule

from deploy import www_owned_paths  # noqa: E402 — the one reader of www/owned_paths.json
from qa import age_inversion_lib  # noqa: E402 — the age-inversion attack, run over the archive

BUCKET = "matthew-life-platform"
S3_ORIGIN = f"https://{BUCKET}.s3.us-west-2.amazonaws.com"
SITE_ORIGIN = reg.PUBLIC_ORIGIN
SITE_DIR = os.path.join(REPO, "site")
DOC_SUFFIXES = reg.SITE_DOCUMENT_SUFFIXES  # the documents the archive admits are the documents this guard reads

PREVIEW_PREFIX = "site/next/v9/"
RETIRED_PREFIXES = {"site/_v9_previous/": "the previous green root build, public under site/ until 2026-11-14 (now www-previous/)"}
SYNC_WINDOW = timedelta(minutes=15)  # a v9 sync writes ~1,300 objects in seconds (measured 2026-11-16: 3 s and 6 s)
PREVIEW_MAX_LAG = timedelta(hours=24)  # a rehearsal lives one root cycle (the daily 15:30 UTC rebuild); then empty it
ARCHIVE_MAX_AGE = timedelta(hours=26)  # the nightly cadence plus two hours of slack
ARCHIVE_PUBLIC_URL = SITE_ORIGIN + reg.ARCHIVE_PUBLIC_PATH

COPIES = {
    "root": ("site/ (the v9 build's paths)", "/", "A C D"),
    "preview": (PREVIEW_PREFIX, "/next/v9/", "A B C"),
    "legacy": ("site/ (not the v9 build's)", "/", "C D"),
    "retired": (", ".join(RETIRED_PREFIXES), "/_v9_previous/", "B"),
    "archive": (reg.ARCHIVE_TARBALL_KEY, reg.ARCHIVE_PUBLIC_PATH, "A B C"),
}
PRIVATE = {
    "www-previous/": "the previous green root builds (the rollback source) — no anonymous read in deploy/bucket_policy.json",
    "backups/": "root snapshots, the preview snapshot, quarantined copies — no anonymous read in deploy/bucket_policy.json",
    "prior object versions": "the bucket is versioned; s3:GetObjectVersion is granted to no anonymous principal",
}
#: Every resource deploy/bucket_policy.json lets `Principal: *` GetObject, classified: a copy of the site, or why not.
NOT_A_COPY = "a Lambda-written artefact served once at its own path, not a copy of a site page; no older copy is published"
PUBLIC_RESOURCES = {
    "site/*": "copies: root, preview, legacy, retired",
    "generated/archive/*": "copy: archive",
    "generated/podcast/*": "audio — " + NOT_A_COPY,
    "generated/panelcast/*": "audio — " + NOT_A_COPY,
    "generated/moments/*": NOT_A_COPY + " (rule D resolves the feeds that link it)",
    "generated/board_answers/*": NOT_A_COPY,
    "generated/experiments/prereg/*": NOT_A_COPY,
    "generated/public_stats.json": NOT_A_COPY,
    "generated/pulse.json": NOT_A_COPY,
    "generated/data/character_stats.json": NOT_A_COPY,
    "generated/journal/posts.json": NOT_A_COPY,
    "generated/journal/posts/week-*": NOT_A_COPY + " (rule D resolves the feeds that link it)",
    "generated/assets/images/og-*": "share-card images, redrawn daily from current data — " + NOT_A_COPY,
    "generated/assets/images/editorial/*": "illustration — " + NOT_A_COPY,
    "generated/covers/*": "book covers — " + NOT_A_COPY,
}
#: Every S3 origin path in cdk/stacks/web_stack.py, classified.
ORIGIN_PATHS = {
    "/site": "the averagejoematt.com default origin — copies root, preview, legacy, retired",
    "/generated": "the averagejoematt.com generated origin — copy: archive (the rest: PUBLIC_RESOURCES)",
    "/dashboard": "another distribution; the bucket policy grants no anonymous read on dashboard/ — not public",
    "/blog": "another distribution; the bucket policy grants no anonymous read on blog/ — not public",
    "/buddy": "another distribution; the bucket policy grants no anonymous read on buddy/ — not public",
}
#: Top-level site/ locations neither the repo's site/ tree nor the v9 build writes, each in scope for rules C and D.
LEGACY_LOCATIONS = {
    "chronicle": "the pre-v9 chronicle and its archive copies (deploy/restart_chronicle_handler.py); /chronicle/ 301s at the edge",
    "evidence": "the v4 evidence pages (last written 2026-06-24); 301 at the edge, still readable at the S3 website endpoint",
    "now": "the v4 /now/ page (last written 2026-07-12); 301 at the edge, still readable at the S3 website endpoint",
}
_ID_KEYS = ("id", "item_id", "prediction_id", "topic_slug")
_COMPOSITE = ("coach_id", "date", "metric", "due_date", "eval_type")


def is_doc(key: str) -> bool:
    return key.lower().endswith(DOC_SUFFIXES)


# ── the inventory: classify every site/ object ───────────────────────────────────────────────────────────────────────
def _v9_claims(owned: dict) -> tuple[set[str], list[str], list[str]]:
    """(exact site-relative paths, fnmatch patterns, prefixes) the v9 build writes — www/owned_paths.json, plus each
    owned file's family (`data/series/*.json`: a live build writes more series than the fixture lists)."""
    exact = set(www_owned_paths.owned_relpaths(owned))
    pats = [p.strip("/") + "/index.html" for p in owned["route_patterns"]]
    pats += sorted({f"{os.path.dirname(f)}/*{os.path.splitext(f)[1]}" for f in owned["files"] if "/" in f})
    return exact, pats, list(owned["prefixes"])


def classify(listing: list[dict], owned: dict, site_dir: str = SITE_DIR) -> dict[str, list[dict]]:
    """Every site/ object → its copy: root | preview | legacy | retired. A v9 document is one the build claims (and the
    repo's site/ tree does not own), or any document written inside the newest root build's window."""
    exact, pats, prefixes = _v9_claims(owned)
    marker = _marker(listing, "site/index.html")
    out: dict[str, list[dict]] = {"root": [], "preview": [], "legacy": [], "retired": []}
    for o in listing:
        key = o["Key"]
        if not key.startswith("site/"):
            continue
        rel = key[len("site/") :]
        if key.startswith(PREVIEW_PREFIX):
            out["preview"].append(o)
        elif any(key.startswith(p) for p in RETIRED_PREFIXES):
            out["retired"].append(o)
        elif os.path.isfile(os.path.join(site_dir, rel)) and rel not in exact:
            out["legacy"].append(o)
        elif (
            rel in exact
            or any(fnmatch.fnmatchcase(rel, p) for p in pats)
            or any(rel.startswith(p) for p in prefixes)
            or (marker and o["LastModified"] >= marker - SYNC_WINDOW)
        ):
            out["root"].append(o)
        else:
            out["legacy"].append(o)
    return out


def _marker(listing: list[dict], key: str):
    for o in listing:
        if o["Key"] == key:
            return o["LastModified"]
    return None


def location_issues(copies: dict[str, list[dict]], owned: dict, site_dir: str = SITE_DIR) -> list[tuple[str, str, str]]:
    """A NEW place holding public documents is a new copy until someone declares it: every top-level site/ location (and
    every site/next/ child) must be the repo's, the v9 build's, the preview, retired, or a declared legacy location."""
    exact, pats, prefixes = _v9_claims(owned)
    v9_tops = {p.split("/")[0] for p in list(exact) + pats + prefixes}
    seen: dict[str, int] = {}
    for o in copies["legacy"] + copies["root"]:
        rel = o["Key"][len("site/") :]
        parts = rel.split("/")
        if len(parts) < 2 or not is_doc(rel):
            continue
        loc = "/".join(parts[:2]) if parts[0] == "next" and len(parts) > 2 else parts[0]
        if os.path.exists(os.path.join(site_dir, loc)) or loc in v9_tops or loc in LEGACY_LOCATIONS:
            continue
        seen[loc] = seen.get(loc, 0) + 1
    return [
        ("legacy", "location", f"site/{loc}/ holds {n} public document(s) and is not a declared location")
        for loc, n in sorted(seen.items())
    ]


# ── rules A and B over the bucket ─────────────────────────────────────────────────────────────────────────────────────
def orphans(docs: list[dict], marker) -> list[dict]:
    if marker is None:
        return []
    return sorted((o for o in docs if is_doc(o["Key"]) and o["LastModified"] < marker - SYNC_WINDOW), key=lambda o: o["Key"])


def bucket_rules(copies: dict[str, list[dict]], listing: list[dict]) -> tuple[list[tuple[str, str, str]], dict]:
    """Rules A and B over the S3 copies. Returns (violations, facts) — facts carry the markers and orphan keys."""
    out: list[tuple[str, str, str]] = []
    root_marker = _marker(listing, "site/index.html")
    preview_marker = _marker(listing, PREVIEW_PREFIX + "index.html")
    facts = {"root_marker": root_marker, "preview_marker": preview_marker, "orphans": {}}
    for name, marker in (("root", root_marker), ("preview", preview_marker)):
        found = orphans(copies[name], marker)
        facts["orphans"][name] = [o["Key"] for o in found]
        for o in found:
            out.append((name, "A", f"{o['Key']} — written {_iso(o['LastModified'])}, before the newest build ({_iso(marker)})"))
    preview_docs = [o for o in copies["preview"] if is_doc(o["Key"])]
    if preview_docs and root_marker and (preview_marker is None or root_marker - preview_marker > PREVIEW_MAX_LAG):
        out.append(
            (
                "preview",
                "B",
                f"{len(preview_docs)} document(s) built {_iso(preview_marker)}, more than {_hours(PREVIEW_MAX_LAG)} behind the root "
                f"({_iso(root_marker)}) — empty it, or rebuild it with target=preview",
            )
        )
    for o in copies["retired"]:
        out.append(("retired", "B", f"{o['Key']} — a retired location holds a public object"))
    return out, facts


# ── rule D: the sitemaps and feeds ────────────────────────────────────────────────────────────────────────────────────
_URL = re.compile(r"<(?:loc|link|guid)\b[^>]*>\s*([^<\s]+)\s*</(?:loc|link|guid)>|<link\b[^>]*\bhref=\"([^\"]+)\"")
_OWN_URL = re.compile(r"^https?://(?:www\.)?averagejoematt\.com(/[^?#]*)")


def is_feed(key: str) -> bool:
    name = key.rsplit("/", 1)[-1]
    return (
        key.startswith("site/") and not key.startswith(PREVIEW_PREFIX) and (name.startswith("sitemap") or name in ("rss.xml", "feed.xml"))
    )


def derived_issues(feeds: dict[str, str], listing_keys: set[str], orphan_keys: set[str]) -> list[tuple[str, str, str]]:
    """Every averagejoematt.com URL a sitemap or feed advertises must resolve to a served object that is not an orphan
    (a sitemap entry for a retired page keeps the retired address alive)."""
    out = []
    for key, text in sorted(feeds.items()):
        for m in _URL.finditer(text):
            url = m.group(1) or m.group(2)
            hit = _OWN_URL.match(url or "")
            if not hit or hit.group(1).startswith("/api/"):
                continue
            path = urllib.parse.unquote(hit.group(1))
            cands = [f"site{path}", f"site{path.rstrip('/')}/index.html", f"generated{path}", f"generated{path.rstrip('/')}/index.html"]
            found = [c for c in cands if c in listing_keys]
            if not found:
                out.append(("root" if "sitemap-0" in key else "legacy", "D", f"{key} lists {path} — no object serves it"))
            elif found and all(c in orphan_keys for c in found):
                out.append(("root", "D", f"{key} lists {path} — served only by an orphan the newest build did not write"))
    return out


# ── rule C: the publication policy over a downloaded tree ─────────────────────────────────────────────────────────────
def policy_issues(tree: str, snapshot_dir: str) -> list[str]:
    """The build scan's PUBLICATION members (not its correctness members — see the module docstring) over one copy."""
    out = []
    for dirpath, _d, files in os.walk(tree):
        for name in files:
            if not name.endswith(DOC_SUFFIXES):
                continue
            path = os.path.join(dirpath, name)
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for s in check_www_build.SENTINELS:
                if s in text:
                    out.append(f"{os.path.relpath(path, tree)}: sentinel {s!r}")
    out += check_www_build.own_words_scope(tree, snapshot_dir)
    out += check_www_build.room_leaks(tree)
    out += check_www_build.lab_leaks(tree)
    out += check_www_build.story_leaks(tree)
    return out


# ── the archive ───────────────────────────────────────────────────────────────────────────────────────────────────────
def read_archive(blob: bytes) -> dict[str, bytes]:
    """Member name (root stripped) → bytes. Untrusted input: names are never used as filesystem paths unchecked."""
    members: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tf:
        for info in tf.getmembers():
            if not info.isfile():
                continue
            _root, _sep, rel = info.name.partition("/")
            fh = tf.extractfile(info)
            if rel and fh is not None:
                members[rel] = fh.read()
    return members


def _safe_write(tree: str, rel: str, body: bytes) -> None:
    target = os.path.normpath(os.path.join(tree, rel))
    if not target.startswith(os.path.normpath(tree) + os.sep):
        return  # a name that climbs out of the tree is not written (and cannot be a served page anyway)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "wb") as fh:
        fh.write(body)


def archive_admission(members: dict[str, bytes], listing_keys: set[str]) -> list[tuple[str, str, str]]:
    """Rule A for the archive: each web/ member is one the CURRENT registry admits, from an object still served."""
    refused, gone = [], []
    for name in sorted(members):
        if not name.startswith("web/"):
            continue
        path = name[len("web") :]
        gen_ok = reg.generated_decision(path)[0] == reg.INCLUDE
        if not gen_ok and not reg.admits_site_key("site" + path):
            refused.append(path)
        elif ("generated" + path if gen_ok else "site" + path) not in listing_keys:
            gone.append(path)
    out = []
    if refused:
        out.append(("archive", "A", f"{len(refused)} member(s) the admission registry now refuses, e.g. {', '.join(refused[:3])}"))
    if gone:
        out.append(("archive", "A", f"{len(gone)} member(s) whose page is no longer served, e.g. {', '.join(gone[:3])}"))
    return out


def withheld_words(archived, live, path: str = "") -> list[str]:
    """Paths where the archived copy carries WORDS (a string of three words or more) and the live route serves the same
    record with none ("" or null). Lists align on a record id; a list without one is not compared. Paths only — the
    words are never printed (the CI log is public)."""
    out: list[str] = []
    if isinstance(archived, dict) and isinstance(live, dict):
        for k, v in archived.items():
            if k in live and k != "_meta":
                out += withheld_words(v, live[k], f"{path}.{k}" if path else k)
    elif isinstance(archived, list) and isinstance(live, list):
        n_live, n_arch = Counter(_record_id(x) for x in live), Counter(_record_id(x) for x in archived)
        live_by = {_record_id(x): x for x in live}
        for x in archived:
            rid = _record_id(x)
            if rid and n_live[rid] == 1 and n_arch[rid] == 1:  # an id two records share cannot align: skipped, never guessed
                out += withheld_words(x, live_by[rid], f"{path}[{rid}]")
    elif isinstance(archived, str) and len(archived.split()) >= 3 and live in ("", None):
        out.append(path)
    return out


def _record_id(x) -> str | None:
    if not isinstance(x, dict):
        return None
    for k in _ID_KEYS:
        if isinstance(x.get(k), (str, int)) and x.get(k) != "":
            return f"{k}={x[k]}"
    if x.get("coach_id") and x.get("date"):
        return "|".join(str(x.get(k)) for k in _COMPOSITE)
    return None


def _has_records(node) -> bool:
    if isinstance(node, list):
        return any(_record_id(x) for x in node) or any(_has_records(x) for x in node)
    if isinstance(node, dict):
        return any(_has_records(v) for v in node.values())
    return False


def archive_api_issues(members: dict[str, bytes], live_get, facts: dict | None = None) -> list[tuple[str, str, str]]:
    """Rule C over the archived API: the age-inversion attack, and no record's words the live route now withholds."""
    api = {}
    for name, body in members.items():
        if name.startswith("api/") and name.endswith(".json"):
            try:
                api["/api/" + name[len("api/") : -len(".json")].replace("__", "/")] = json.loads(body)
            except ValueError:
                continue
    out = [("archive", "C", f"api/ — {line}") for line, bad in age_inversion_lib.audit(lambda p: api.get(p) or {}) if bad]
    compared = sorted(r for r, doc in api.items() if _has_records(doc))
    if facts is not None:
        facts["api_compared"] = len(compared)
    for route in compared:
        try:
            live = live_get(route)
        except (urllib.error.URLError, OSError, ValueError) as exc:
            out.append(("archive", "C", f"{route}: the live route could not be read to compare ({type(exc).__name__})"))
            continue
        paths = withheld_words(api[route], live)
        if paths:
            out.append(("archive", "C", f"{route}: {len(paths)} archived string(s) of words the live route serves empty, e.g. {paths[0]}"))
    return out


def archive_age_issue(manifest: dict, mode: str, now: datetime, markers: list) -> list[tuple[str, str, str]]:
    """Rule B for the archive."""
    try:
        built = datetime.fromisoformat(str(manifest.get("generated_at")).replace("Z", "+00:00"))
    except ValueError:
        return [("archive", "B", "the archive's MANIFEST.json carries no readable generated_at")]
    if mode == "remediation":
        newest = max((m for m in markers if m), default=None)
        if newest and built < newest:
            return [("archive", "B", f"built {_iso(built)}, before the newest site build ({_iso(newest)}) — regenerate it")]
    elif now - built > ARCHIVE_MAX_AGE:
        return [("archive", "B", f"built {_iso(built)}, older than {_hours(ARCHIVE_MAX_AGE)} — the nightly run has not replaced it")]
    return []


# ── I/O (injected in tests) ───────────────────────────────────────────────────────────────────────────────────────────
def list_bucket(prefixes=("site/", "generated/")) -> list[dict]:
    import boto3  # noqa: PLC0415 — only the live run needs it

    s3 = boto3.client("s3", region_name="us-west-2")
    out = []
    for prefix in prefixes:
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
            out += [{"Key": o["Key"], "LastModified": o["LastModified"], "Size": o.get("Size", 0)} for o in page.get("Contents") or []]
    return out


def http_get(url: str, accept: str = "*/*", timeout: float = 30.0) -> bytes:
    """An anonymous GET — exactly what a reader receives. No credentials, ever."""
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform-public-copies/1.0 (#6083)", "Accept": accept})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — fixed https origins
        return resp.read()


def s3_object_url(key: str) -> str:
    return f"{S3_ORIGIN}/{urllib.parse.quote(key, safe='/')}"


#: A read that fails is tried again this many times, one at a time, before the key is called unreadable. Measured on
#: production 2026-11-16: two consecutive runs over ~1,570 documents each lost ONE read to a transient error (a
#: different key each time), and a guard that aborts on that is red most days for nothing.
DOWNLOAD_RETRIES = 3
RETRY_PAUSE_S = 1.5


def download(keys: list[str], tree: str, strip: str, get=None, pause: float = RETRY_PAUSE_S) -> list[str]:
    """Fetch each key anonymously into tree/<key minus strip>. Returns the keys that could not be read — after
    ``DOWNLOAD_RETRIES`` further tries each, so a key named here is one a reader persistently cannot fetch."""
    get = get or (lambda k: http_get(s3_object_url(k)))
    failed: list[str] = []

    def one(key: str) -> None:
        try:
            _safe_write(tree, key[len(strip) :], get(key))
        except (urllib.error.URLError, OSError):
            failed.append(key)

    with ThreadPoolExecutor(max_workers=16) as pool:
        list(pool.map(one, keys))
    for _ in range(DOWNLOAD_RETRIES):
        if not failed:
            break
        again, failed[:] = sorted(failed), []
        time.sleep(pause)
        for key in again:
            one(key)
    return failed


def live_json(route: str) -> dict:
    return json.loads(http_get(SITE_ORIGIN + route, accept="application/json"))


def fresh_snapshot(dest: str) -> str:
    cp = subprocess.run(
        [sys.executable, os.path.join(REPO, "scripts", "publish_snapshot.py"), "--mode", "live", "--out", dest],
        capture_output=True,
        text=True,
    )
    if cp.returncode != 0:
        raise SystemExit(
            f"check_public_copies: the live snapshot failed (exit {cp.returncode}) — cannot judge rule C:\n{cp.stderr[-1500:]}"
        )
    return dest


# ── the run ───────────────────────────────────────────────────────────────────────────────────────────────────────────
def evaluate(listing, archive_blob, snapshot_dir, mode, now, fetch_key=None, live_get=live_json, owned=None, site_dir=SITE_DIR):
    """Every rule over every copy. Pure apart from the injected readers; returns (violations, facts)."""
    owned = owned if owned is not None else www_owned_paths.load()
    copies = classify(listing, owned, site_dir)
    violations, facts = bucket_rules(copies, listing)
    violations += location_issues(copies, owned, site_dir)
    keys = {o["Key"] for o in listing}
    orphan_keys = {k for ks in facts["orphans"].values() for k in ks}
    fetch_key = fetch_key or (lambda k: http_get(s3_object_url(k)))
    facts["counts"] = {name: sum(1 for o in objs if is_doc(o["Key"])) for name, objs in copies.items()}
    with tempfile.TemporaryDirectory(prefix="public-copies-") as tmp:
        for name, strip in (("preview", PREVIEW_PREFIX), ("site", "site/")):
            docs = [o["Key"] for o in (copies["preview"] if name == "preview" else copies["root"] + copies["legacy"]) if is_doc(o["Key"])]
            failed = download(docs, os.path.join(tmp, name), strip, fetch_key)
            if failed:
                raise SystemExit(f"check_public_copies: {len(failed)} {name} document(s) could not be read anonymously, e.g. {failed[:3]}")
            violations += [
                ("preview" if name == "preview" else "root/legacy", "C", i) for i in policy_issues(os.path.join(tmp, name), snapshot_dir)
            ]
        feeds = {k: fetch_key(k).decode("utf-8", "replace") for k in sorted(keys) if is_feed(k)}
        violations += derived_issues(feeds, keys, orphan_keys)
        facts["archive_members"] = 0
        if archive_blob is None:
            violations.append(("archive", "B", f"{ARCHIVE_PUBLIC_URL} could not be downloaded"))
        else:
            members = read_archive(archive_blob)
            facts["archive_members"] = len(members)
            facts["archive_built"] = json.loads(members.get("MANIFEST.json") or b"{}").get("generated_at")
            violations += archive_age_issue(
                json.loads(members.get("MANIFEST.json") or b"{}"), mode, now, [facts["root_marker"], facts["preview_marker"]]
            )
            violations += archive_admission(members, keys)
            for sub, pre in (("archive-preview", "web/next/v9/"), ("archive-web", "web/")):
                tree = os.path.join(tmp, sub)
                for n, body in members.items():
                    if n.startswith(pre) and (sub == "archive-preview" or not n.startswith("web/next/v9/")):
                        _safe_write(tree, n[len(pre) :], body)
                if os.path.isdir(tree):
                    violations += [("archive", "C", f"{pre}{i}") for i in policy_issues(tree, snapshot_dir)]
            violations += archive_api_issues(members, live_get, facts)
    return violations, facts


def _iso(t) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ") if t else "never"


def _hours(d: timedelta) -> str:
    return f"{int(d.total_seconds() // 3600)} h"


def report(violations, facts, mode: str) -> str:
    lines = [
        f"Public copies of the site — {mode} (#6083)",
        "",
        f"{'copy':<9} {'where':<40} {'public at':<24} {'docs':>6}  newest build       rules",
    ]
    built = {"root": facts.get("root_marker"), "preview": facts.get("preview_marker")}
    for name, (where, url, rules) in COPIES.items():
        n = facts.get("archive_members", 0) if name == "archive" else facts["counts"].get(name, 0)
        if name == "archive":
            when = (facts.get("archive_built") or "—")[:16] + "Z"
        else:
            when = _iso(built[name]) if name in built else "—"
        lines.append(f"{name:<9} {where:<40} {url:<24} {n:>6}  {when:<18} {rules}")
    for where, why in PRIVATE.items():
        lines.append(f"{'private':<9} {where:<40} not public — {why}")
    if "api_compared" in facts:
        lines.append(
            f"archive api/: the age-inversion attack ran; {facts['api_compared']} record-bearing route(s) compared with the live route"
        )
    lines.append("")
    if not violations:
        lines.append("✅ no violation: no orphan, no stale copy, the publication policy holds on every copy")
        return "\n".join(lines)
    lines.append(f"❌ {len(violations)} violation(s):")
    lines += [f"  [{copy}] rule {rule}: {detail}" for copy, rule, detail in violations]
    return "\n".join(lines)


def remediation_commands(violations, facts) -> str:
    """What a human runs, attended, in this order. The guard runs none of them."""
    copies = {c for c, _r, _d in violations}
    orphan = [k for ks in facts["orphans"].values() for k in ks]
    out = ["", "Remediation — run by a human, in this order (nothing below has run):"]
    if "preview" in copies:
        out += [
            "  # the preview: empty it (the default outside a rehearsal), preserving every object privately",
            f"  bash deploy/quarantine_public_copy.sh --prefix {PREVIEW_PREFIX}            # dry run: prints every step",
            f"  bash deploy/quarantine_public_copy.sh --prefix {PREVIEW_PREFIX} --apply    # or rehearse again: gh workflow run web-preview-deploy.yml -f target=preview",
        ]
    if orphan:
        out += [
            f"  # {len(orphan)} orphan(s): copy to a private prefix, verify, then remove the public object",
            "  python3 scripts/check_public_copies.py --check --orphans-out /tmp/orphans-6083.txt",
            "  bash deploy/quarantine_public_copy.sh --keys /tmp/orphans-6083.txt [--apply]",
        ]
    if "archive" in copies or "preview" in copies or orphan:
        out += [
            "  # the archive, AFTER the copies above are clean (it packages what site/ holds)",
            "  aws lambda invoke --function-name life-platform-permanence --region us-west-2 /tmp/permanence-6083.json",
            "  DIST_ID=$(aws cloudformation describe-stacks --region us-east-1 --stack-name LifePlatformWeb "
            "--query \"Stacks[0].Outputs[?OutputKey=='AmjDistributionId'].OutputValue\" --output text)",
            "  aws cloudfront create-invalidation --distribution-id $DIST_ID --paths '/archive/*'",
        ]
    out.append("  python3 scripts/check_public_copies.py --remediation    # again, until it exits 0")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="read-only; exit 1 on any violation")
    mode.add_argument("--remediation", action="store_true", help="the stricter archive rule + the human's commands")
    ap.add_argument("--snapshot", help="a live snapshot dir to reuse (default: export a fresh one)")
    ap.add_argument("--orphans-out", help="write the rule-A orphan keys here, one per line (input to quarantine_public_copy.sh)")
    ap.add_argument("--github-output", action="store_true", help="write summary= to $GITHUB_OUTPUT")
    args = ap.parse_args(argv)
    run_mode = "remediation" if args.remediation else "check"
    try:
        listing = list_bucket()
    except Exception as exc:  # noqa: BLE001 — any listing failure is a setup error, never a pass
        print(f"check_public_copies: could not list the bucket ({type(exc).__name__}: {exc})", file=sys.stderr)
        return 3
    try:
        archive_blob = http_get(ARCHIVE_PUBLIC_URL, timeout=120)
    except (urllib.error.URLError, OSError):
        archive_blob = None
    with tempfile.TemporaryDirectory(prefix="public-copies-snap-") as snap:
        snapshot_dir = args.snapshot or fresh_snapshot(snap)
        violations, facts = evaluate(listing, archive_blob, snapshot_dir, run_mode, datetime.now(timezone.utc))
    print(report(violations, facts, run_mode))
    if args.orphans_out:
        with open(args.orphans_out, "w", encoding="utf-8") as fh:
            fh.write("".join(k + "\n" for ks in facts["orphans"].values() for k in ks))
    if violations and run_mode == "remediation":
        print(remediation_commands(violations, facts))
    if args.github_output and os.environ.get("GITHUB_OUTPUT"):
        summary = f"{len(violations)} violation(s) across {sorted({c for c, _r, _d in violations})}" if violations else "clean"
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as fh:
            fh.write(f"summary={summary}\n")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
