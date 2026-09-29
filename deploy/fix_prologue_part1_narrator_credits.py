#!/usr/bin/env python3
"""fix_prologue_part1_narrator_credits.py — one-shot, idempotent repair for #4363.

Prologue Part I ("Before the Numbers", DDB DATE#2026-02-28, served at
/journal/posts/week-01/) has Elena Voss introduce herself with a piece in Harper's,
a story for The Ringer and a profile for Wired. Elena is the site's AI narrator: those
are invented bylines at real publications, stated as fact, on a page that never said
she was an AI. The biography paragraph is REWRITTEN (the credits dropped, the AI
authorship stated in her own voice) and the served page gains the same narrator note
every newly rendered post now carries (content.chronicle_schema.AI_NARRATOR_NOTE_HTML).

THREE SURFACES, ONE REPAIR
--------------------------
The page is a stored artifact, not a rendered-on-read view, so a DDB-only fix would
leave the live page unchanged (the stored-artifact class in SITE_UPLEVEL_PLAYBOOK):

    1. DDB   USER#matthew#SOURCE#chronicle / DATE#2026-02-28
             → content_markdown, content_html (the paragraph)
    2. S3    generated/journal/posts/week-01/index.html
             → the paragraph + the narrator note after the series line
    3. CloudFront invalidation of /journal/posts/week-01/*

The manifest (generated/journal/posts.json) is NOT touched: its week-01 excerpt opens
on the charging cables and never reaches the biography paragraph. The repo's legacy
copy (site/legacy/chronicle/posts/week-00/index.html) is fixed in the same PR and
ships with the normal site deploy.

Idempotent: every surface is detected by content — a surface already free of the
credits and already carrying the note is a no-op.

Usage:
    python3 deploy/fix_prologue_part1_narrator_credits.py            # dry-run (default)
    python3 deploy/fix_prologue_part1_narrator_credits.py --apply    # commit
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lambdas"))
from content import chronicle_schema  # noqa: E402

REGION = "us-west-2"
BUCKET = "matthew-life-platform"
TABLE = "life-platform"
CLOUDFRONT_DISTRIBUTION_ID = "E3S424OXQZ8NBE"

PK = "USER#matthew#SOURCE#chronicle"
SK = "DATE#2026-02-28"
PAGE_KEY = "generated/journal/posts/week-01/index.html"
INVALIDATION_PATH = "/journal/posts/week-01/*"

# The paragraph as it was published — its opening is stable across every copy (DDB
# markdown, DDB html, the S3 page, the legacy page); the tail differs only in HTML
# wrapping, so the replacement is anchored on the opening and the sentence that ends it.
PARAGRAPH_OPENING = "My name is Elena Voss. I'm a freelance journalist based in Brooklyn"
PARAGRAPH_CLOSING = "what I found had almost nothing to do with sleep."

REWRITTEN_PARAGRAPH = (
    "My name is Elena Voss. I should say plainly what I am: the narrator of this series is an AI, "
    "a character written by a language model from Matthew's own data. I have no bylines anywhere else, "
    "no editor at a magazine, no career before this one. What I have instead is access &mdash; to every "
    "sensor on and around his body, to the system that grades his days, and to the emotional weather of "
    "his journal &mdash; and one job: to stay long enough to find the story underneath the story."
)


def rewrite_paragraph(text: str, *, html_entities: bool = True) -> str:
    """Replace the credit-bearing biography paragraph in `text` with REWRITTEN_PARAGRAPH.
    Returns `text` unchanged when the paragraph is absent (already repaired). Markdown
    callers pass html_entities=False so the stored markdown carries plain dashes."""
    start = text.find(PARAGRAPH_OPENING)
    if start < 0:
        return text
    end = text.find(PARAGRAPH_CLOSING, start)
    if end < 0:
        raise ValueError("found the paragraph opening but not its closing sentence — refusing a partial rewrite")
    new = REWRITTEN_PARAGRAPH if html_entities else REWRITTEN_PARAGRAPH.replace("&mdash;", "—")
    return text[:start] + new + text[end + len(PARAGRAPH_CLOSING) :]


def add_narrator_note(page_html: str) -> str:
    """Insert the shared narrator note (and its style rule) into an already-rendered post
    page, after the series line — the same place chronicle_render / restart_leadin_pages
    now render it. No-op when the page already carries it."""
    if "data-ai-narrator" in page_html:
        return page_html
    series_end = page_html.find("</div>", page_html.find('class="post-header__series"'))
    style_end = page_html.find("</style>")
    if series_end < 0 or style_end < 0:
        raise ValueError("page has no post-header__series line or <style> block — not a chronicle post template")
    series_end += len("</div>")
    out = page_html[:series_end] + "\n    " + chronicle_schema.AI_NARRATOR_NOTE_HTML + page_html[series_end:]
    return out.replace("</style>", "    " + chronicle_schema.AI_NARRATOR_NOTE_CSS + "\n  </style>", 1)


def repair_page(page_html: str) -> str:
    return add_narrator_note(rewrite_paragraph(page_html))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--apply", action="store_true", help="write DDB + S3 + invalidate (default: dry-run)")
    args = ap.parse_args()

    import boto3

    ddb = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    s3 = boto3.client("s3", region_name=REGION)

    item = ddb.get_item(Key={"pk": PK, "sk": SK}).get("Item")
    if not item:
        print(f"ERROR: {PK} / {SK} not found")
        return 1
    md_old, html_old = item.get("content_markdown") or "", item.get("content_html") or ""
    md_new, html_new = rewrite_paragraph(md_old, html_entities=False), rewrite_paragraph(html_old)
    page_old = s3.get_object(Bucket=BUCKET, Key=PAGE_KEY)["Body"].read().decode("utf-8")
    page_new = repair_page(page_old)

    residual = {
        name: chronicle_schema.real_publication_credit_findings(text)
        for name, text in (("content_markdown", md_new), ("content_html", html_new), ("page", page_new))
    }
    for name, found in residual.items():
        if found:
            print(f"ERROR: {name} still claims a real-publication credit after the rewrite: {found}")
            return 1

    ddb_changed = (md_new, html_new) != (md_old, html_old)
    page_changed = page_new != page_old
    print(f"DDB {SK}: {'REWRITE' if ddb_changed else 'already repaired'}")
    print(f"S3  {PAGE_KEY}: {'REWRITE + narrator note' if page_changed else 'already repaired'}")
    if not args.apply:
        print("dry-run — re-run with --apply to write")
        return 0
    if ddb_changed:
        ddb.update_item(
            Key={"pk": PK, "sk": SK},
            UpdateExpression="SET content_markdown = :m, content_html = :h, credits_repaired_at = :t",
            ExpressionAttributeValues={":m": md_new, ":h": html_new, ":t": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
        )
    if page_changed:
        s3.put_object(
            Bucket=BUCKET,
            Key=PAGE_KEY,
            Body=page_new.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
            CacheControl="max-age=300",
        )
        boto3.client("cloudfront").create_invalidation(
            DistributionId=CLOUDFRONT_DISTRIBUTION_ID,
            InvalidationBatch={"Paths": {"Quantity": 1, "Items": [INVALIDATION_PATH]}, "CallerReference": f"4363-{int(time.time())}"},
        )
    print("applied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
