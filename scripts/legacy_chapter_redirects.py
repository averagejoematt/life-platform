#!/usr/bin/env python3
"""scripts/legacy_chapter_redirects.py — a chapter's legacy address follows its served edition (#6193).

Owner ruling 2026-11-22 (final edition rehearsal §4): once a chapter's corrected edition is public, its legacy article
URL ``/journal/posts/<page>/`` must stop serving the uncorrected first edition and send the reader to the canonical
chapter ``/story/<id>/``. The rules — the mapping, the redirect document, what withdrawn and retired chapters do — are
``lambdas/content/legacy_chapter_addresses.py``; this is the one writer.

WHAT IT DOES, per chapter the live snapshot serves an edition of (and whose live ``/story/<id>/`` page shows it):
  1. proves the original is kept privately: the chapter's first-edition pointer (``CHAPTER_EDITION#<id>#01``, written by
     ``scripts/chronicle_edition_backup.py``) and its restore rehearsal (``…#01#restore``) exist, the pointer names THIS
     journal page (else the page and the chapter disagree, and nothing is replaced), and the page as it stands now hashes
     to the sha256 the pointer recorded. A page that changed since then is copied write-once to
     ``backups/legacy-chapter-addresses/<stamp>/s3/<key>`` and read back first. Prior object versions are a second copy.
  2. replaces the journal page with the redirect document (``WebsiteRedirectLocation`` = the story path: the website
     endpoint answers 301);
  3. sets the chapter's ``posts.json`` excerpt and its share kit to the edition's summary (and the kit's canonical URL to
     the chapter), each after a write-once private copy of the object as it stood;
  4. a chapter marked by an earlier run whose edition is no longer served (withdrawn) gets its original excerpt and kit
     back from the earliest private copy; its legacy page keeps redirecting to the canonical chapter, which is the
     governed page whichever edition it serves;
  5. reads every write back, then invalidates the touched paths.

SAFETY. Dry run by default: reads only (the public site, the bucket, the table) and prints every step. ``--apply`` is an
S3 write under ``generated/`` plus a CloudFront invalidation: owner-attended (CLAUDE.md, the ask list), after the build
that serves the edition. Nothing is deleted. No served edition = nothing to do (the switch off, or none approved).

    python3 scripts/legacy_chapter_redirects.py [--chapter week-12]            # the plan, read-only
    python3 scripts/legacy_chapter_redirects.py --chapter week-12 --apply      # attended
    python3 scripts/verify_legacy_chapter_redirects.py --chapter week-12       # then verify, read-only

ROLLBACK (per object): restore its prior version (``aws s3api list-object-versions`` → ``copy-object`` from the
``VersionId`` before this run), or copy the private backup this run printed back over it; then invalidate the path.

Exit: 0 ok (or nothing to do) · 2 refused (nothing written for that chapter) · 3 a write did not read back equal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Callable, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "lambdas"))
from content import (
    chapter_editions as CE,  # noqa: E402
    legacy_chapter_addresses as LA,  # noqa: E402
)

BUCKET = "matthew-life-platform"
TABLE = "life-platform"
USER_ID = "matthew"
DISTRIBUTION_ID = "E3S424OXQZ8NBE"
EDITION_MARK = "data-edition-line"  # www/src/pages/story/[id].astro prints it only for a served edition


class Refused(Exception):
    """This chapter's step cannot be taken as asked — nothing was written for it."""


class Unverified(Exception):
    """A write did not read back equal."""


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def load_snapshot(snapshot_dir: str) -> tuple[list, list]:
    def one(name: str, field: Optional[str]) -> list:
        try:
            with open(os.path.join(snapshot_dir, name), encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError):
            return []
        doc = doc.get(field) if field and isinstance(doc, dict) else doc
        return doc if isinstance(doc, list) else []

    return one("chapter_editions.json", "editions"), one("chapters.json", None)


def fresh_snapshot(dest: str) -> str:
    cp = subprocess.run(
        [sys.executable, os.path.join(_HERE, "publish_snapshot.py"), "--mode", "live", "--out", dest], capture_output=True, text=True
    )
    if cp.returncode != 0:
        raise SystemExit(f"legacy_chapter_redirects: the live snapshot failed (exit {cp.returncode}):\n{cp.stderr[-1500:]}")
    return dest


def http_get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "life-platform-legacy-chapters/1.0 (#6193)"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310 — the public site
        return resp.read()


def s3_get(s3, key: str) -> Optional[bytes]:
    try:
        return s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    except Exception as exc:  # noqa: BLE001
        if "NoSuchKey" in type(exc).__name__ or "NoSuchKey" in str(exc) or "404" in str(exc):
            return None
        raise


def _ctype(key: str) -> str:
    return "application/json" if key.endswith(".json") else "text/html; charset=utf-8"


def backup_step(key: str, body: bytes, stamp: str) -> dict:
    return {"kind": "backup", "key": f"{LA.BACKUP_ROOT}{stamp}/s3/{key}", "body": body, "source": key}


def _earliest_backups(s3, key: str) -> list[bytes]:
    """Every private copy this mechanism ever took of ``key``, oldest first (the stamp sorts by time)."""
    keys: list[str] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=LA.BACKUP_ROOT):
        keys += [o["Key"] for o in page.get("Contents") or [] if o["Key"].endswith("/s3/" + key)]
    return [b for b in (s3_get(s3, k) for k in sorted(keys)) if b is not None]


def chapter_steps(entry: dict, s3, table, stamp: str) -> list[dict]:
    """The steps for one served chapter's journal page and share kit. Raises Refused."""
    pk = CE.pk(USER_ID)
    pointer = table.get_item(Key={"pk": pk, "sk": CE.sk_original(entry["chapter_id"])}, ConsistentRead=True).get("Item")
    restore = table.get_item(Key={"pk": pk, "sk": CE.sk_restore(entry["chapter_id"])}, ConsistentRead=True).get("Item")
    if not pointer or not restore:
        raise Refused(f"{entry['chapter_id']}: no first-edition backup pointer and restore rehearsal; the original is not proven kept")
    src = f"s3:{entry['legacy_key']}"
    kept = next((o for o in pointer.get("objects") or [] if o.get("source") == src), None)
    if kept is None:
        named = [o.get("source") for o in pointer.get("objects") or [] if str(o.get("source", "")).startswith("s3:generated/journal/")]
        raise Refused(f"{entry['chapter_id']}: the backup pointer names {named}, not {src}; the page and the chapter disagree")
    steps: list[dict] = []
    current = s3_get(s3, entry["legacy_key"])
    if current is not None and LA.redirect_target(current) != entry["story_path"]:
        if sha(current) != kept.get("sha256"):  # changed since the edition backup: keep this version too
            steps.append(backup_step(entry["legacy_key"], current, stamp))
        else:
            back = s3_get(s3, kept["backup_key"])
            if back is None or sha(back) != kept["sha256"]:
                raise Refused(f"{entry['chapter_id']}: the edition backup {kept['backup_key']} does not read back to its sha256")
        page = LA.redirect_page(entry).encode("utf-8")
        steps.append({"kind": "page", "key": entry["legacy_key"], "body": page, "redirect": entry["story_path"]})
    kit = s3_get(s3, entry["share_kit_key"])
    if kit is not None:
        new = json.dumps(LA.share_kit_update(json.loads(kit), entry), indent=2).encode("utf-8")
        if json.loads(new) != json.loads(kit):
            steps += [backup_step(entry["share_kit_key"], kit, stamp), {"kind": "kit", "key": entry["share_kit_key"], "body": new}]
    return steps


def manifest_steps(entries: list[dict], s3, stamp: str, now: str, keep: frozenset = frozenset()) -> list[dict]:
    """posts.json: every served chapter's excerpt → its edition summary; a withdrawn one back to its original, with its
    share kit restored from the earliest private copy. Raises Refused (LA.PlanError) when an original is missing."""
    current = s3_get(s3, LA.POSTS_KEY)
    if current is None:
        return []
    originals: dict[str, str] = {}
    for b in _earliest_backups(s3, LA.POSTS_KEY):
        for p in json.loads(b).get("posts") or []:
            if isinstance(p, dict) and "edition" not in p and p.get("url") not in originals:
                originals[p["url"]] = p.get("excerpt")
    try:
        doc, changed = LA.manifest_update(json.loads(current), entries, originals, now, keep)
    except LA.PlanError as exc:
        raise Refused(str(exc)) from exc
    if not changed:
        return []
    steps = [
        backup_step(LA.POSTS_KEY, current, stamp),
        {"kind": "manifest", "key": LA.POSTS_KEY, "body": json.dumps(doc, indent=2).encode()},
    ]
    planned = {x["legacy_path"] for x in entries} | set(keep)
    for url in (u for u in changed if u not in planned):  # withdrawn: the kit as it stood before the first replacement
        kit_key = LA.share_kit_key(url)
        old = _earliest_backups(s3, kit_key)
        if old and s3_get(s3, kit_key) != old[0]:
            steps.append({"kind": "kit", "key": kit_key, "body": old[0]})
    return steps


def apply(steps: list[dict], s3, log: Callable = print) -> list[str]:
    """Backups first (write-once, read back), then the public objects (read back). Returns the paths to invalidate."""
    for st in sorted(steps, key=lambda s: s["kind"] != "backup"):
        extra = {"IfNoneMatch": "*"} if st["kind"] == "backup" else {"CacheControl": "max-age=300"}
        if st.get("redirect"):
            extra["WebsiteRedirectLocation"] = st["redirect"]
        s3.put_object(Bucket=BUCKET, Key=st["key"], Body=st["body"], ContentType=_ctype(st.get("source") or st["key"]), **extra)
        back = s3_get(s3, st["key"])
        if back is None or sha(back) != sha(st["body"]):
            raise Unverified(f"{st['key']} did not read back equal")
        if st.get("redirect"):
            head = s3.head_object(Bucket=BUCKET, Key=st["key"])
            if head.get("WebsiteRedirectLocation") != st["redirect"]:
                raise Unverified(f"{st['key']} carries no WebsiteRedirectLocation {st['redirect']}")
        log(f"  wrote {st['kind']:<8} s3://{BUCKET}/{st['key']} (sha256 {sha(st['body'])[:12]}…)")
    paths = []
    for st in steps:
        if st["kind"] == "page":
            paths.append("/" + st["key"][len("generated/") :].rsplit("/", 1)[0] + "/*")
        elif st["kind"] in ("manifest", "kit"):
            paths.append("/" + st["key"][len("generated/") :])
    return sorted(set(paths))


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--chapter", action="append", help="limit to these chapter ids (week-NN); default: every served edition")
    ap.add_argument("--snapshot", help="a live snapshot dir to reuse (default: export a fresh one)")
    ap.add_argument("--apply", action="store_true", help="write (owner-attended); default is a read-only plan")
    args = ap.parse_args(argv)
    import boto3  # noqa: PLC0415 — only the live run needs it

    s3 = boto3.client("s3", region_name="us-west-2")
    table = boto3.resource("dynamodb", region_name="us-west-2").Table(TABLE)
    now = datetime.now(timezone.utc)
    stamp, iso = now.strftime("%Y%m%dT%H%M%SZ"), now.isoformat()
    with tempfile.TemporaryDirectory(prefix="legacy-chapters-") as tmp:
        editions, chapters = load_snapshot(args.snapshot or fresh_snapshot(tmp))
    p = LA.plan(editions, chapters)
    for cid, why in p["refused"]:
        print(f"  ✗ {cid}: {why}")
    entries = [x for x in p["chapters"] if not args.chapter or x["chapter_id"] in args.chapter]
    held = []
    for x in list(entries):
        try:
            live = http_get(LA.ORIGIN + x["story_path"]).decode("utf-8", "replace")
        except (urllib.error.URLError, OSError):
            live = ""
        if EDITION_MARK not in live:
            held.append(x["chapter_id"])
            entries.remove(x)
    for cid in held:
        print(f"  ✗ {cid}: the live /story/{cid}/ does not show the edition yet — rebuild the site first; nothing done for it")
    steps, rc, ready = [], 0, []
    for x in entries:
        try:
            s = chapter_steps(x, s3, table, stamp)
        except Refused as exc:
            print(f"  ✗ REFUSED {exc}")
            rc = 2
            continue
        print(f"  {x['chapter_id']}: {x['legacy_path']} → {x['story_path']} ({len(s)} step(s))")
        steps += s
        ready.append(x)
    try:
        # served chapters this run does not touch (filtered out, held or refused) keep their manifest entry exactly as it is
        keep = frozenset(x["legacy_path"] for x in p["chapters"]) - {x["legacy_path"] for x in ready}
        steps += manifest_steps(ready, s3, stamp, iso, keep)
    except Refused as exc:
        print(f"  ✗ REFUSED posts.json: {exc}")
        rc = 2
    for st in steps:
        print(f"    {'WOULD ' if not args.apply else ''}{st['kind']:<8} s3://{BUCKET}/{st['key']} ({len(st['body'])} bytes)")
    if not steps:
        print("nothing to do: no served edition needs its legacy address changed")
        return rc
    if not args.apply:
        print("dry run — nothing written. Re-run with --apply (owner-attended).")
        return rc
    try:
        paths = apply(steps, s3)
    except Unverified as exc:
        print(f"  ✗ {exc}")
        return 3
    boto3.client("cloudfront").create_invalidation(
        DistributionId=DISTRIBUTION_ID,
        InvalidationBatch={"Paths": {"Quantity": len(paths), "Items": paths}, "CallerReference": f"legacy-chapters-{stamp}"},
    )
    print(f"invalidated {paths}. Verify: python3 scripts/verify_legacy_chapter_redirects.py")
    return rc


if __name__ == "__main__":
    sys.exit(main())
