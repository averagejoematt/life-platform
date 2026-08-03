#!/usr/bin/env python3
"""fix_prologue_part3_editors_note.py — one-shot, idempotent repair for #1985.

Prologue Part III ("The Plan, On the Record", DATE#2026-07-26) asserts a start
weight of 317.61 lbs. The scale actually read 321.09 on the morning of Day 1.
Part I already carries a Margaret Calloway editor's note reconciling its own
working numbers; Part III — the chain-of-authority terminus, whose own text says
"Nothing here can be quietly revised later" — carries none. The asymmetry is the
defect.

WHAT THE NUMBERS ACTUALLY ARE (verified against DDB, not assumed)
-----------------------------------------------------------------
    DATE#2026-07-20  withings  321.38
    DATE#2026-07-22  withings  317.61   <- most recent reading when the plan was filed (07-26)
    DATE#2026-07-27  withings  321.09   <- Day 1, and EXPERIMENT_BASELINE_WEIGHT_LBS

So 317.61 was not careless: it was the current number when the plan was written,
and the body moved over the five days before Day 1. The note says exactly that.

WHAT IS **NOT** TOUCHED
-----------------------
``deploy/generated/genesis_preregistration.json`` contains 317.61 and is
SHA-256 sealed (#1378, `prereg_sha256` adece752…, publicly verifiable at
/experiments/prereg/genesis-2026-07-27.json). It is never edited here — editing
a sealed pre-registration is precisely the edit-laundering the seal exists to
prevent. The frozen prose of Part III is likewise preserved verbatim, including
the board predictions that quote 317.61: those are graded against the numbers
they were filed with. Only an editor's note is APPENDED, exactly as Part I did.

THREE SURFACES, ONE REPAIR
--------------------------
The page is a stored artifact, not a rendered-on-read view, so a DDB-only fix
would leave the live page unchanged (the stored-artifact class in
SITE_UPLEVEL_PLAYBOOK). All three move together or none do:

    1. DDB   USER#matthew#SOURCE#chronicle / DATE#2026-07-26
             → content_html, content_markdown, stats_line
    2. S3    generated/journal/posts/week-03/index.html   (the served page)
    3. S3    generated/journal/posts.json                 (the story index)

Surface 3 matters on its own: the index shows "317.61 lbs at the start" where
NO editor's note is visible, so a reader scanning the story door sees the bare
superseded figure. The stats line re-anchors to 321.09; the article prose does
not change.

Idempotent: re-running after a successful apply is a no-op on every surface
(the note is detected by its marker and never appended twice).

Usage:
    python3 deploy/fix_prologue_part3_editors_note.py            # dry-run (default)
    python3 deploy/fix_prologue_part3_editors_note.py --apply    # commit
"""

from __future__ import annotations

import argparse
import json
import sys

import boto3

REGION = "us-west-2"
BUCKET = "matthew-life-platform"
TABLE = "life-platform"

PK = "USER#matthew#SOURCE#chronicle"
SK = "DATE#2026-07-26"

PAGE_KEY = "generated/journal/posts/week-03/index.html"
INDEX_KEY = "generated/journal/posts.json"

SUPERSEDED = "317.61"
ACTUAL = "321.09"

# The marker that makes every surface idempotent. Present ⇒ already repaired.
MARKER = "Editor&rsquo;s note &mdash; Margaret Calloway"
MARKER_PLAIN = "Editor's note — Margaret Calloway"

# ── the note ────────────────────────────────────────────────────────────────
# Voice and structure mirror Part I's note verbatim in form: same speaker, same
# blockquote class, same "preserved as written" close. Facts are the DDB
# readings above. APPROVED BY MATTHEW before this script was run with --apply.
NOTE_TEXT = (
    "Filed the day before Day 1, when 317.61 lbs — the scale's reading of July 22 — was the most recent number "
    "on record. On the morning of July 27 it read 321.09, and that is the figure the experiment actually runs on: "
    "the waypoints below re-anchor from it, and the cockpit has carried it since Day 1. The plan is preserved "
    "exactly as filed, its predictions included — they are graded against the numbers they were written with, and "
    "the pre-registration they cite stays sealed and publicly verifiable. A commitment device that could be quietly "
    "re-baselined would not be one."
)

NOTE_HTML = f'<blockquote class="editors-note"><strong>Editor\'s note — Margaret Calloway:</strong> {NOTE_TEXT}</blockquote>'
NOTE_MD = f"> **Editor's note — Margaret Calloway:** {NOTE_TEXT}"

# The served page is HTML-entity encoded by the renderer; match its house style.
NOTE_PAGE_HTML = (
    '<blockquote class="editors-note"><strong>Editor&rsquo;s note &mdash; Margaret Calloway:</strong> '
    + NOTE_TEXT.replace("—", "&mdash;").replace("'", "&rsquo;")
    + "</blockquote>"
)

NEW_STATS_LINE = f"{ACTUAL} lbs at the start · 185 lbs the target · 16 board predictions filed | Prologue — the plan before Day 1"

PAGE_BODY_ANCHOR = '<article class="post-body">\n    <div class="prose">\n      '


def _already(hay: str) -> bool:
    return MARKER in hay or MARKER_PLAIN in hay


def repair_ddb(dry: bool) -> bool:
    ddb = boto3.client("dynamodb", region_name=REGION)
    item = ddb.get_item(TableName=TABLE, Key={"pk": {"S": PK}, "sk": {"S": SK}}).get("Item")
    if not item:
        print("  DDB   ✗ record not found — aborting (nothing else runs)")
        return False

    html = item["content_html"]["S"]
    md = item["content_markdown"]["S"]
    stats = item.get("stats_line", {}).get("S", "")

    if _already(html) and _already(md) and SUPERSEDED not in stats:
        print("  DDB   ✓ already repaired (no-op)")
        return True

    new_html = html if _already(html) else NOTE_HTML + "\n" + html
    new_md = md if _already(md) else NOTE_MD + "\n\n" + md
    new_stats = NEW_STATS_LINE if SUPERSEDED in stats else stats

    print(f"  DDB   content_html    {len(html)} → {len(new_html)} bytes")
    print(f"  DDB   content_markdown {len(md)} → {len(new_md)} bytes")
    print(f"  DDB   stats_line      {stats!r}")
    print(f"  DDB              →     {new_stats!r}")
    if dry:
        return True
    ddb.update_item(
        TableName=TABLE,
        Key={"pk": {"S": PK}, "sk": {"S": SK}},
        UpdateExpression="SET content_html = :h, content_markdown = :m, stats_line = :s",
        ExpressionAttributeValues={":h": {"S": new_html}, ":m": {"S": new_md}, ":s": {"S": new_stats}},
    )
    print("  DDB   ✓ updated")
    return True


def repair_page(dry: bool) -> bool:
    s3 = boto3.client("s3", region_name=REGION)
    body = s3.get_object(Bucket=BUCKET, Key=PAGE_KEY)["Body"].read().decode("utf-8")

    changed = body
    if not _already(changed):
        if PAGE_BODY_ANCHOR not in changed:
            print("  PAGE  ✗ body anchor not found — renderer markup changed; ABORT rather than guess")
            return False
        changed = changed.replace(PAGE_BODY_ANCHOR, PAGE_BODY_ANCHOR + NOTE_PAGE_HTML + "\n      ", 1)
    changed = changed.replace(
        f'<div class="post-header__stats">{SUPERSEDED} lbs at the start',
        f'<div class="post-header__stats">{ACTUAL} lbs at the start',
        1,
    )

    if changed == body:
        print("  PAGE  ✓ already repaired (no-op)")
        return True
    print(f"  PAGE  {len(body)} → {len(changed)} bytes · note={'added' if not _already(body) else 'present'}")
    if dry:
        return True
    s3.put_object(
        Bucket=BUCKET,
        Key=PAGE_KEY,
        Body=changed.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        CacheControl="max-age=300, public",
    )
    print("  PAGE  ✓ written")
    return True


def repair_index(dry: bool) -> bool:
    s3 = boto3.client("s3", region_name=REGION)
    raw = s3.get_object(Bucket=BUCKET, Key=INDEX_KEY)["Body"].read().decode("utf-8")
    if SUPERSEDED not in raw:
        print("  INDEX ✓ already repaired (no-op)")
        return True
    data = json.loads(raw)
    hits = 0
    for post in data if isinstance(data, list) else data.get("posts", []):
        for field in ("stats_line", "stats", "dek", "summary"):
            v = post.get(field)
            if isinstance(v, str) and SUPERSEDED in v:
                post[field] = v.replace(f"{SUPERSEDED} lbs", f"{ACTUAL} lbs")
                hits += 1
    if not hits:
        print(f"  INDEX ✗ {SUPERSEDED} present but in no known field — ABORT rather than blind-replace")
        return False
    out = json.dumps(data, ensure_ascii=False, indent=2)
    print(f"  INDEX re-anchored {hits} field(s) {SUPERSEDED} → {ACTUAL}")
    if dry:
        return True
    s3.put_object(
        Bucket=BUCKET, Key=INDEX_KEY, Body=out.encode("utf-8"), ContentType="application/json", CacheControl="max-age=300, public"
    )
    print("  INDEX ✓ written")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="commit the repair (default: dry-run)")
    args = ap.parse_args()
    dry = not args.apply

    print(f"{'DRY RUN' if dry else 'APPLYING'} — Prologue Part III editor's note (#1985)\n")
    ok = repair_ddb(dry) and repair_page(dry) and repair_index(dry)
    print()
    if not ok:
        print("ABORTED — a surface did not match its expected shape; nothing partial was written.")
        return 1
    if dry:
        print("Dry run only. Re-run with --apply to commit, then invalidate /journal/posts/week-03/ and /journal/posts.json.")
    else:
        print("Done. Invalidate the CloudFront VIEWER paths: /journal/posts/week-03/ and /journal/posts.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
