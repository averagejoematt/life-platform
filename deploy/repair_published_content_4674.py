#!/usr/bin/env python3
"""
repair_published_content_4674.py — correct two already-published reader surfaces (#4674).

PR #4734 fixed the WRITERS: the Panel's episode takes the chapter's title, and a cut builder
term holds a week at the story door. The content published BEFORE that fix is not rewritten
by any natural run, so this is the repair for exactly those two objects:

  week 2   the Panel episode is titled "EP2 · Nine Days and Counting" in
           generated/panelcast/episodes.json and generated/panelcast/feed.xml, while the
           chapter is "Nine Days and No Rest". The episode takes the chapter's title, the
           one rule both writers now follow (panelcast_desk.episode_title).
  week 4   the chapter's excerpt in generated/journal/posts.json says "the pace flag is
           live" — a builder term the glossary rules `cut` (site/data/glossary.json). The
           clause is dropped; the sentence keeps what the data showed. Pass --excerpt to
           put different words in its place.

Nothing else on either object is touched: every other post, episode and feed item is
byte-for-byte what it was, and the script refuses (exit 3) when the live object no longer
carries the text it expects, so it never writes a guess.

Read-only by default: it fetches the three objects, prints each change as a diff, and
exits. --apply backs each object up under generated/_repairs/4674/<name>.<utc stamp>
first, then writes it back with its own content type, then invalidates the three public
paths on CloudFront. The apply is an S3 write: owner-attended (CLAUDE.md, the ask list).

  python3 deploy/repair_published_content_4674.py            # dry-run
  python3 deploy/repair_published_content_4674.py --apply    # write + invalidate
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from datetime import datetime, timezone

BUCKET = "matthew-life-platform"
REGION = "us-west-2"
DISTRIBUTION = "E3S424OXQZ8NBE"
BACKUP_PREFIX = "generated/_repairs/4674"

POSTS_KEY = "generated/journal/posts.json"
EPISODES_KEY = "generated/panelcast/episodes.json"
FEED_KEY = "generated/panelcast/feed.xml"
PUBLIC_PATHS = ("/journal/posts.json", "/panelcast/episodes.json", "/panelcast/feed.xml")

WEEK2 = 2
OLD_TITLE = "EP2 · Nine Days and Counting"
NEW_TITLE = "EP2 · Nine Days and No Rest"
WEEK4 = 4
OLD_CLAUSE = ", but the pace flag is live and the streak is the question"
NEW_CLAUSE = ", and the streak is the question"
CUT_TERM = re.compile(r"\bpace[\s_\-‑–]flag\b", re.IGNORECASE)


class Unchanged(Exception):
    """The live object does not carry the text this repair expects — nothing is written."""


# ── pure rewrites (unit-tested on the live captures) ──────────────────────────


def rewrite_posts(doc: dict, excerpt: str | None = None) -> dict:
    """The manifest with the week-4 excerpt's cut clause dropped (or replaced by `excerpt`)."""
    posts = [p for p in doc.get("posts") or [] if p.get("week") == WEEK4]
    if len(posts) != 1:
        raise Unchanged(f"posts.json has {len(posts)} week-{WEEK4} posts, expected 1")
    post = posts[0]
    old = str(post.get("excerpt") or "")
    if excerpt is not None:
        new = excerpt
    elif OLD_CLAUSE in old:
        new = old.replace(OLD_CLAUSE, NEW_CLAUSE)
    else:
        raise Unchanged(f"week-{WEEK4} excerpt no longer carries {OLD_CLAUSE!r}")
    if CUT_TERM.search(new):
        raise Unchanged("the replacement excerpt still carries the cut term")
    out = json.loads(json.dumps(doc))
    for p in out["posts"]:
        if p.get("week") == WEEK4:
            p["excerpt"] = new
    return out


def rewrite_episodes(doc: dict) -> dict:
    """The episode list with the week-2 episode titled as its chapter is."""
    eps = [e for e in doc.get("episodes") or [] if e.get("week") == WEEK2]
    if len(eps) != 1:
        raise Unchanged(f"episodes.json has {len(eps)} week-{WEEK2} episodes, expected 1")
    if eps[0].get("title") != OLD_TITLE:
        raise Unchanged(f"week-{WEEK2} episode is titled {eps[0].get('title')!r}, not {OLD_TITLE!r}")
    out = json.loads(json.dumps(doc))
    for e in out["episodes"]:
        if e.get("week") == WEEK2:
            e["title"] = NEW_TITLE
    return out


def rewrite_feed(xml: str) -> str:
    """The RSS feed with the one week-2 <title> changed and nothing else."""
    needle = f"<title>{OLD_TITLE}</title>"
    if xml.count(needle) != 1:
        raise Unchanged(f"feed.xml carries {xml.count(needle)} of {needle!r}, expected 1")
    return xml.replace(needle, f"<title>{NEW_TITLE}</title>", 1)


def changes(posts: dict, episodes: dict, feed: str, excerpt: str | None = None) -> list:
    """[(key, old_text, new_text, content_type)] — the three rewrites, or an Unchanged raised."""
    dump = lambda d: json.dumps(d, ensure_ascii=False, indent=2) + "\n"  # noqa: E731
    return [
        (POSTS_KEY, dump(posts), dump(rewrite_posts(posts, excerpt)), "application/json"),
        (EPISODES_KEY, dump(episodes), dump(rewrite_episodes(episodes)), "application/json"),
        (FEED_KEY, feed, rewrite_feed(feed), "application/rss+xml"),
    ]


def unified(key: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(old.splitlines(True), new.splitlines(True), f"live/{key}", f"repaired/{key}", n=1))


# ── AWS ───────────────────────────────────────────────────────────────────────


def _read(s3, key: str):
    obj = s3.get_object(Bucket=BUCKET, Key=key)
    return obj["Body"].read().decode("utf-8"), obj.get("ContentType") or ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="back up, write and invalidate (owner-attended)")
    ap.add_argument("--excerpt", default=None, help="the week-4 excerpt to publish instead of the default rewrite")
    args = ap.parse_args(argv)

    import boto3

    s3 = boto3.client("s3", region_name=REGION)
    posts_text, posts_ct = _read(s3, POSTS_KEY)
    episodes_text, episodes_ct = _read(s3, EPISODES_KEY)
    feed_text, feed_ct = _read(s3, FEED_KEY)
    try:
        plan = changes(json.loads(posts_text), json.loads(episodes_text), feed_text, args.excerpt)
    except Unchanged as e:
        print(f"REFUSED — {e}")
        return 3
    # Write back what was read, re-serialised the same way, so the diff shows only the repair.
    for key, old, new, _ct in plan:
        print(unified(key, old, new) or f"{key}: no change\n")
    if not args.apply:
        print("dry-run: nothing written. Re-run with --apply to back up, write and invalidate.")
        return 0

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    live_ct = {POSTS_KEY: posts_ct, EPISODES_KEY: episodes_ct, FEED_KEY: feed_ct}
    for key, _old, new, ct in plan:
        backup = f"{BACKUP_PREFIX}/{os.path.basename(key)}.{stamp}"
        s3.copy_object(Bucket=BUCKET, CopySource={"Bucket": BUCKET, "Key": key}, Key=backup)
        print(f"backed up {key} -> {backup}")
        s3.put_object(
            Bucket=BUCKET, Key=key, Body=new.encode("utf-8"), ContentType=live_ct.get(key) or ct, CacheControl="public, max-age=300"
        )
        print(f"wrote {key} ({len(new)} bytes)")
    cf = boto3.client("cloudfront")
    inv = cf.create_invalidation(
        DistributionId=DISTRIBUTION,
        InvalidationBatch={
            "Paths": {"Quantity": len(PUBLIC_PATHS), "Items": list(PUBLIC_PATHS)},
            "CallerReference": f"repair-4674-{stamp}",
        },
    )
    print("invalidation", inv["Invalidation"]["Id"], "for", ", ".join(PUBLIC_PATHS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
