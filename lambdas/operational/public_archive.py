#!/usr/bin/env python3
"""Builds the nightly public permanence archive (#1400).

Pure-ish builder: every AWS client and every network call is injected, so the
whole thing runs offline under test. ``lambdas/operational/permanence_lambda.py``
owns the clients and the schedule; this module owns the contents.

Three arms feed the archive, all of them gated by
``public_archive_registry`` — see that module for the admission rule:

* the published ``generated/`` objects (the chronicle, the pre-registrations,
  the public JSON the site renders),
* the published ``site/`` documents (the pages, the methods, the feeds),
* an anonymous snapshot of every declared read-only ``/api/*`` route.

Two invariants this file is responsible for:

1. **Nothing enters unadmitted.** Every S3 member passes
   ``reg.admits_generated_key`` / ``reg.admits_site_key`` before it is read, and
   the API arm only ever walks ``reg.ARCHIVE_ROUTES``. There is no third path
   that appends to ``members``.
2. **The archive reports what it left out.** The manifest carries the
   registry's exclusion list verbatim and an honest captured/declared count for
   the API arm. A partial run says so rather than looking complete (ADR-104).
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import tarfile
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from common.pacific_time import PACIFIC  # #2798: the archive is named for its Pacific day

from operational import permanence_terms as terms, public_archive_registry as reg

try:
    from common.platform_logger import get_logger

    logger = get_logger("public-archive")
except ImportError:  # pragma: no cover - logging fallback only
    logger = logging.getLogger("public-archive")
    logger.setLevel(logging.INFO)

MANIFEST_SCHEMA = "public-archive/1"
MEMBER_ROOT_PREFIX = "web"

# A ceiling, not a target. The archive is ~7 MB of documents today; anything
# approaching this means an admission rule changed shape and the run should
# fail loudly rather than quietly ship a 200 MB nightly download.
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024

USER_AGENT = "life-platform-public-archive/1.0 (+https://averagejoematt.com/)"
FETCH_TIMEOUT_SECONDS = 20
FETCH_PAUSE_SECONDS = 0.15


# ── S3 arms ─────────────────────────────────────────────────────────────────
def _iter_keys(s3, bucket: str, prefix: str) -> Iterable[tuple[str, int]]:
    """Yield (key, size) under a prefix, paginating."""
    token: Optional[str] = None
    while True:
        kwargs: dict = {"Bucket": bucket, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        resp = s3.list_objects_v2(**kwargs)
        for obj in resp.get("Contents") or []:
            yield obj["Key"], int(obj.get("Size") or 0)
        if not resp.get("IsTruncated"):
            return
        token = resp.get("NextContinuationToken")
        if not token:
            return


def _member_name(public_path: str) -> str:
    """``/method/index.html`` -> ``web/method/index.html``."""
    return f"{MEMBER_ROOT_PREFIX}{public_path}"


def collect_s3_members(s3, bucket: str) -> tuple[dict[str, bytes], dict]:
    """Collect the admitted ``generated/`` and ``site/`` objects.

    Generated is collected first and wins any collision, because CloudFront
    resolves the same way: the generated-origin behaviours are more specific
    than the default site behaviour, so what a reader actually receives at a
    contested path is the generated object.
    """
    members: dict[str, bytes] = {}
    stats = {"generated": 0, "site": 0, "collisions": 0, "unreadable": 0}

    def _pull(key: str, member: str) -> bool:
        if member in members:
            stats["collisions"] += 1
            return False
        try:
            body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
        except Exception as exc:  # a single unreadable object must not lose the archive
            stats["unreadable"] += 1
            logger.warning("archive: could not read one object (%s)", type(exc).__name__)
            return False
        members[member] = body
        return True

    for key, _size in _iter_keys(s3, bucket, reg.GENERATED_PREFIX):
        if not reg.admits_generated_key(key):
            continue
        path = reg.public_path_for_generated_key(key)
        if path is None:
            continue
        if _pull(key, _member_name(path)):
            stats["generated"] += 1

    for key, _size in _iter_keys(s3, bucket, reg.SITE_PREFIX):
        if not reg.admits_site_key(key):
            continue
        path = reg.public_path_for_site_key(key)
        if path is None:
            continue
        if _pull(key, _member_name(path)):
            stats["site"] += 1

    return members, stats


# ── API arm ─────────────────────────────────────────────────────────────────
def default_fetch(url: str) -> tuple[int, bytes]:
    """Anonymous GET over stdlib urllib. No credentials, ever — that is the
    property that makes the API arm safe: the archive receives exactly what an
    unauthenticated reader receives, so no subscriber- or owner-tier projection
    can reach it."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:  # nosec B310 - fixed https origin
        return int(resp.status or 0), resp.read()


def collect_api_members(
    fetch: Optional[Callable[[str], tuple[int, bytes]]] = None,
    routes: Optional[Iterable[str]] = None,
    pause_seconds: Optional[float] = None,
) -> tuple[dict[str, bytes], dict]:
    """Snapshot the declared read-only API routes.

    Fail-soft per route: one 500 must not cost the whole archive. Every failure
    is recorded and surfaces in the manifest as a captured/declared count, so a
    thin archive is legible as thin rather than passing for complete.
    """
    do_fetch = fetch or default_fetch
    pause = FETCH_PAUSE_SECONDS if pause_seconds is None else pause_seconds
    declared = tuple(routes) if routes is not None else reg.ARCHIVE_ROUTES
    members: dict[str, bytes] = {}
    failures: list[dict] = []

    for route in declared:
        url = reg.PUBLIC_ORIGIN + route
        try:
            status, body = do_fetch(url)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            failures.append({"path": route, "error": type(exc).__name__})
            continue
        except Exception as exc:  # defensive: an odd fetcher must not lose the run
            failures.append({"path": route, "error": type(exc).__name__})
            continue
        if status != 200 or not body:
            failures.append({"path": route, "error": f"http {status}"})
            continue
        members[reg.api_member_name(route)] = body
        if pause:
            time.sleep(pause)

    stats = {
        "routes_declared": len(declared),
        "routes_captured": len(members),
        "failures": failures,
    }
    return members, stats


# ── Manifest + tarball ──────────────────────────────────────────────────────
def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_manifest(
    members: dict[str, bytes], s3_stats: dict, api_stats: dict, generated_at: str, continuity: Optional[dict] = None
) -> dict:
    """The archive's own inventory: every member with a size and a checksum,
    the totals, and the registry's exclusion list verbatim.

    This is the document that makes the promise checkable rather than
    assertable — the reader can recompute every number in it from the tarball.

    Two members are deliberately absent from ``entries``: ``MANIFEST.json``
    itself (a manifest cannot carry its own checksum) and the ``README.txt``
    generated beside it. Everything else in the tarball is listed.
    """
    entries: list[dict] = [{"member": name, "bytes": len(body), "sha256": _sha256(body)} for name, body in sorted(members.items())]
    total = sum(int(e["bytes"]) for e in entries)
    return {
        "schema": MANIFEST_SCHEMA,
        "generated_at": generated_at,
        "terms_version": terms.TERMS_VERSION,
        "terms_effective": terms.TERMS_EFFECTIVE,
        "entry_count": len(entries),
        "uncompressed_bytes": total,
        "sources": {
            "site_documents": s3_stats.get("site", 0),
            "generated_artifacts": s3_stats.get("generated", 0),
            "api_snapshots": api_stats.get("routes_captured", 0),
            "path_collisions_resolved": s3_stats.get("collisions", 0),
            "objects_unreadable": s3_stats.get("unreadable", 0),
        },
        "api": {
            "routes_declared": api_stats.get("routes_declared", 0),
            "routes_captured": api_stats.get("routes_captured", 0),
            "failures": api_stats.get("failures", []),
        },
        "excluded": [dict(x) for x in reg.excluded_categories()],
        "continuity": dict(continuity) if continuity else None,
        "entries": entries,
    }


def _readme(generated_at: str, manifest: dict) -> bytes:
    """A plain-text front door for someone who unpacks this in ten years."""
    lines = [
        "The Permanence Contract — public archive",
        "=" * 40,
        "",
        f"Built:            {generated_at}",
        f"Contract version: {terms.TERMS_VERSION} (effective {terms.TERMS_EFFECTIVE})",
        f"Files:            {manifest['entry_count']}",
        f"Uncompressed:     {manifest['uncompressed_bytes']} bytes",
        "",
        "This is everything averagejoematt.com already publishes, packaged as one",
        "download and rebuilt every night: the pages and their methods (web/), and a",
        "snapshot of every public read-only API response (api/).",
        "",
        "MANIFEST.json lists every file with its size and SHA-256, and names what this",
        "archive deliberately leaves out and why. You do not need this project, or an",
        "internet connection, to check it — this is the whole procedure:",
        "",
        "    python3 - <<'EOF'",
        "    import hashlib, json, tarfile",
        "    tf = tarfile.open('latest.tar.gz')",
        "    root = tf.getnames()[0].split('/')[0]",
        "    m = json.load(tf.extractfile(root + '/MANIFEST.json'))",
        "    bad = [e['member'] for e in m['entries']",
        "           if hashlib.sha256(tf.extractfile(root + '/' + e['member']).read()).hexdigest()",
        "              != e['sha256']]",
        "    print('files:', len(m['entries']), 'mismatched:', bad or 'none')",
        "    EOF",
        "",
        "The terms below are the contract this archive exists to keep. They are",
        "reproduced in full so the archive stays readable without the website.",
        "",
    ]
    for c in terms.CLAUSES:
        lines.append(f"[{c['id']}] {c['title']}")
        lines.append("")
        for chunk in _wrap(c["text"], 78):
            lines.append("    " + chunk)
        lines.append("")
    lines.append("Amendment history")
    lines.append("-" * 17)
    for a in terms.AMENDMENTS:
        lines.append(f"  {a['version']}  {a['date']}  {a['summary']}")
    lines.append("")
    return ("\n".join(lines)).encode("utf-8")


def _wrap(text: str, width: int) -> list[str]:
    out: list[str] = []
    line = ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        out.append(line)
    return out


def build_tarball(members: dict[str, bytes], root: str, mtime: int) -> bytes:
    """Pack members into a deterministic .tar.gz.

    Deterministic on purpose: same inputs, same bytes, so a reader who mirrors
    two consecutive nights can tell whether anything actually changed. Uniform
    mtime/uid/gid, sorted members, and gzip's own timestamp field zeroed.
    """
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w") as tar:
        for name in sorted(members):
            body = members[name]
            info = tarfile.TarInfo(name=f"{root}/{name}")
            info.size = len(body)
            info.mtime = mtime
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            tar.addfile(info, io.BytesIO(body))
    packed = io.BytesIO()
    import gzip  # noqa: PLC0415 - local: only this function compresses

    with gzip.GzipFile(fileobj=packed, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return packed.getvalue()


def build_archive(
    s3,
    bucket: str,
    now: Optional[datetime] = None,
    fetch: Optional[Callable[[str], tuple[int, bytes]]] = None,
    pause_seconds: Optional[float] = None,
    continuity: Optional[dict] = None,
) -> dict:
    """Assemble the archive. Returns ``{tarball, manifest, root, day}``.

    Writes nothing — the caller decides whether to publish, so a dry run can
    build the whole thing and report on it without touching S3.
    """
    ts = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:  # a caller-supplied naive stamp is UTC (#1964's one semantic)
        ts = ts.replace(tzinfo=timezone.utc)
    generated_at = ts.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    # #2798: `generated_at` is the INSTANT and stays UTC; the archive's DAY-name is Pacific,
    # matching every other day this platform publishes.
    day = ts.astimezone(PACIFIC).strftime("%Y-%m-%d")
    root = f"public-archive-{day}"

    members, s3_stats = collect_s3_members(s3, bucket)
    api_members, api_stats = collect_api_members(fetch=fetch, pause_seconds=pause_seconds)
    for name, body in api_members.items():
        if name in members:
            s3_stats["collisions"] = s3_stats.get("collisions", 0) + 1
            continue
        members[name] = body

    total = sum(len(b) for b in members.values())
    if total > MAX_UNCOMPRESSED_BYTES:
        raise RuntimeError(f"public archive would be {total} bytes, over the {MAX_UNCOMPRESSED_BYTES}-byte ceiling — refusing to publish")

    manifest = build_manifest(members, s3_stats, api_stats, generated_at, continuity=continuity)
    members["MANIFEST.json"] = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    members["README.txt"] = _readme(generated_at, manifest)

    tarball = build_tarball(members, root, int(ts.timestamp()))
    manifest["archive"] = {
        "path": reg.ARCHIVE_PUBLIC_PATH,
        "url": reg.PUBLIC_ORIGIN + reg.ARCHIVE_PUBLIC_PATH,
        "bytes": len(tarball),
        "sha256": _sha256(tarball),
        "root": root,
    }
    return {"tarball": tarball, "manifest": manifest, "root": root, "day": day}
