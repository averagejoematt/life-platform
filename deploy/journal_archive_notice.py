#!/usr/bin/env python3
"""journal_archive_notice.py — #3512: the archive-notice mechanism for prior-cycle
journal permalinks.

THE DEFECT
----------
Every reset rebuilds `generated/journal/posts.json`, but the per-post HTML persists
at its permalink. `/journal/posts/week-03/` kept serving cycle 15's "The Plan, On the
Record" — "326.24 lbs at the start" — on Day 0 of cycle 16, unreachable from the
manifest and fully reachable by URL (email, RSS cache, search). `week-04`/`week-05`
were the same. qa-smoke's `reader_truth:frozen_artifacts` leg went red on exactly
this and `qa-smoke-failures` sat in ALARM from 2026-09-03T11:31 PT.

The reset's archive step DID fire; it was a silent no-op. `restart_chronicle_handler.
archive_one` returns "already archived" when the DESTINATION key exists, and the
destination prefix had no cycle segment (`generated/journal/archive/pilot/posts/`),
so every `week-NN` slug collided with the 2026-07-10 cycle-4 archival and no reset
since July archived, tombstoned or redirected a reused week page.

THE MECHANISM (and why it is a banner, not a rewrite)
-----------------------------------------------------
A frozen artifact is never rewritten — that is what "frozen" means, and editing the
historical figure would be the defect (ADR-104, #1985). The sanctioned reconciliation
is an editor's note, which is precisely what `lambdas/operational/weight_truth_qa.py::
assess_frozen_artifact_weights` looks for (`_EDITORS_NOTE_MARKERS`). So this module:

  1. archives a PRISTINE copy (notice stripped) to a CYCLE-KEYED prefix —
     `generated/journal/archive/cycle-<N>/posts/<slug>/index.html` — which is the
     dest-key collision fix: the archive is now navigable by reset generation
     (ADR-077) and a reused slug can never collide with a prior cycle's copy;
  2. injects an archive notice at the top of the LIVE page, in place. The original
     prose stays byte-for-byte below it; the notice names the attempt, the current
     genesis and the current baseline, so the superseded figure is reconciled rather
     than hidden. The page keeps serving 200 and stays readable — which a 301 to a
     hub would not (and #3284 is the record of what a week-NN 301 does to a
     republished installment).

The notice carries a STAMP (`data-archive-notice="cycle-16|2026-09-05|324.64"`). Re-
running with a different genesis/baseline REPLACES a stale notice instead of skipping
it — without that, the second reset after an annotation would leave a banner quoting
a now-superseded baseline while `is_annotated()` stayed True, i.e. a silently-wrong
page behind a green check.

WHERE IT RUNS
-------------
  - `deploy/restart_chronicle_handler.py` step [1b] calls `sweep_journal_permalinks`
    on every reset with `keep_slugs=frozenset()` — at that point every live week page
    belongs to the closing cycle, so all of them get the notice. `restart_leadin_pages
    .py` then re-renders the slugs the NEW cycle reuses, overwriting those keys with
    clean pages. That is why the fix survives the next reset by construction.
  - Standalone, for repairing a surface the reset already passed over:
        python3 deploy/journal_archive_notice.py            # dry-run
        python3 deploy/journal_archive_notice.py --apply
    Default mode reads the live `generated/journal/posts.json` and annotates only the
    week pages the manifest does NOT list. `--ignore-manifest` is the reset's mode.

OUT OF SCOPE (stated, not forgotten)
------------------------------------
Sibling artifacts — the `/moments/share-kits/week-NN/kit.json` payloads and their OG
PNGs — are NOT touched here. A share kit is a JSON payload with no prose surface for
an editor's note, so it needs withdrawal semantics rather than annotation (the driver
withdrew cycle 15's week-04 kit by hand on #3485). That belongs to epic #3490.
Likewise the three pre-existing raw-JSON tombstones (`week-00`, `week-06`,
`week-minus-1`, written by the 2026-07-10 archival) are reported and skipped: they
carry no prose to annotate, and restoring them is a content decision, not this
mechanism's.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"

JOURNAL_POSTS_PREFIX = "generated/journal/posts/"
JOURNAL_MANIFEST_KEY = "generated/journal/posts.json"

# `week-01`, `week-100`, `week-minus-1` — every shape the journal has ever written.
WEEK_KEY_RE = re.compile(r"^generated/journal/posts/(week-[A-Za-z0-9-]+)/index\.html$")
_MANIFEST_URL_RE = re.compile(r"^/journal/posts/(week-[A-Za-z0-9-]+)/$")

# The idempotency + staleness stamp. Everything the notice ASSERTS is in it, so a
# re-run whose assertions changed replaces the block instead of skipping it.
NOTICE_ATTR = "data-archive-notice"
_NOTICE_BLOCK_RE = re.compile(rf'<aside\b[^>]*\b{NOTICE_ATTR}="([^"]*)"[^>]*>.*?</aside>\n?', re.IGNORECASE | re.DOTALL)

# Insertion anchors, most specific first. The journal article shell opens
# `<main id="post"><div class="post-wrap"><div class="post-header">` — the notice goes
# ABOVE the headline so a reader meets it before the superseded stats line.
_ANCHORS_BEFORE = (re.compile(r'<div class="post-header"', re.IGNORECASE),)
_ANCHORS_AFTER = (
    re.compile(r'<main\b[^>]*id="post"[^>]*>', re.IGNORECASE),
    re.compile(r"<body\b[^>]*>", re.IGNORECASE),
)

_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def human_date(iso: str) -> str:
    """`2026-09-05` -> `September 5, 2026`. Falls back to the input on garbage."""
    try:
        d = date.fromisoformat(iso)
    except (TypeError, ValueError):
        return str(iso)
    return f"{_MONTHS[d.month - 1]} {d.day}, {d.year}"


def notice_stamp(cycle: int | None, genesis: str, baseline_lbs: float) -> str:
    """The assertions the notice makes, as one comparable token."""
    return f"cycle-{cycle if cycle is not None else 'unknown'}|{genesis}|{baseline_lbs}"


def build_archive_notice(cycle: int | None, genesis: str, baseline_lbs: float) -> str:
    """The archive notice, as an HTML fragment.

    Contract with the oracle: the visible text contains the literal "Editor's note",
    which is what `weight_truth_qa.is_annotated` tests for, and it NAMES the governing
    baseline so the reconciliation is real rather than a marker that satisfies a
    regex. Both facts live in one text node — `reader_truth_qa.html_to_text` joins
    separate nodes with newlines, so a marker split across tags would not be found.

    Styling is inline on purpose: these are frozen pages that no longer get rebuilt,
    so the notice must not depend on a stylesheet edit shipping with it. `var(...)`
    with a literal fallback keeps it themed where the tokens exist.
    """
    attempt = f"attempt {cycle}" if cycle is not None else "a later attempt"
    stamp = notice_stamp(cycle, genesis, baseline_lbs)
    label_css = (
        "margin:0 0 .5rem;font-family:var(--font-mono,ui-monospace,SFMono-Regular,monospace);"
        "font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;color:var(--ember,#DD7A37);"
    )
    body_css = "margin:0;font-size:.95rem;line-height:1.55;color:var(--ink-muted,#A99F8C);"
    aside_css = (
        "max-width:var(--content-width,72ch);margin:0 auto var(--sp-5,1.25rem);padding:1rem 1.15rem;"
        "border:1px solid var(--ember,#DD7A37);border-left-width:4px;border-radius:var(--radius,6px);"
        "background:rgba(221,122,55,.08);"
    )
    return (
        f'<aside class="archive-notice" {NOTICE_ATTR}="{stamp}" role="note" style="{aside_css}">\n'
        f'  <p style="{label_css}">Editor\'s note — archived record</p>\n'
        f'  <p style="{body_css}">This article is the published record of an earlier attempt of the experiment. '
        f"Its numbers are preserved exactly as filed and have not been revised. The experiment restarted on "
        f"{human_date(genesis)} ({attempt}) and now runs on a starting weight of {baseline_lbs} lbs. Read what "
        f"follows as the record of the attempt it was written in — the live numbers are in "
        f'<a href="/cockpit/" style="color:inherit;">the cockpit</a>, and the current writing is at '
        f'<a href="/story/journal/" style="color:inherit;">the story door</a>.</p>\n'
        f"</aside>\n"
    )


def existing_notice_stamp(html: str) -> str | None:
    """The stamp of the notice already on the page, or None if there isn't one."""
    m = _NOTICE_BLOCK_RE.search(html or "")
    return m.group(1) if m else None


def has_archive_notice(html: str) -> bool:
    return existing_notice_stamp(html) is not None


def strip_archive_notice(html: str) -> str:
    """Remove any archive notice — the pristine form, and the negative control."""
    return _NOTICE_BLOCK_RE.sub("", html or "")


def is_article_html(body: str) -> bool:
    """True for a rendered article shell; False for the raw-JSON tombstone markers
    the 2026-07-10 archival left at week-00/week-06/week-minus-1 (and for anything
    else without a document body to annotate)."""
    low = (body or "").lstrip().lower()
    if low.startswith("{") or low.startswith("["):
        return False
    return "<body" in low and "</html>" in low


def inject_archive_notice(html: str, notice: str) -> tuple[str, str]:
    """Return (new_html, outcome).

    outcome is one of: ``injected`` | ``replaced`` | ``current`` | ``no-anchor``.
    ``current`` means an identical notice is already there (idempotent no-op);
    ``replaced`` means a notice with DIFFERENT assertions was swapped out, which is
    the case a plain "already annotated -> skip" would have silently gotten wrong.
    """
    html = html or ""
    new_stamp = (re.search(rf'{NOTICE_ATTR}="([^"]*)"', notice) or [None, ""])[1]
    old_stamp = existing_notice_stamp(html)
    if old_stamp is not None:
        if old_stamp == new_stamp:
            return html, "current"
        html = strip_archive_notice(html)
    outcome = "replaced" if old_stamp is not None else "injected"
    # Always insert at a LINE BOUNDARY, with the notice ending in a newline, so that
    # strip_archive_notice() restores the original file BYTE-FOR-BYTE. That round-trip
    # is what makes the archived pristine copy pristine, and what lets the test suite
    # assert "a frozen artifact is never rewritten" as an equality rather than a vibe.
    for pat in _ANCHORS_BEFORE:
        m = pat.search(html)
        if m:
            at = html.rfind("\n", 0, m.start()) + 1
            return html[:at] + notice + html[at:], outcome
    for pat in _ANCHORS_AFTER:
        m = pat.search(html)
        if m:
            nl = html.find("\n", m.end())
            at = len(html) if nl == -1 else nl + 1
            return html[:at] + notice + html[at:], outcome
    return html, "no-anchor"


def archive_prefix_for(cycle: int | None, genesis: str) -> str:
    """The cycle-keyed archive prefix — the dest-key collision fix (#3512).

    N is the cycle that PERFORMED the archival, not the cycle that authored the
    article — the authoring cycle is not recoverable from the S3 object, and the
    archiving cycle is what makes the key unique (a given slug is archived at most
    once per reset). That uniqueness is the whole fix: `archive/pilot/posts/` was
    constant, so week-03 collided with its 2026-07-10 copy every time.

    Never falls back to the constant `archive/pilot/posts/` prefix: that constant
    prefix IS the bug, and a fallback onto it would restore the silent no-op the
    moment SSM was unreadable. With no cycle we key on the genesis date, which is
    equally unique per reset.
    """
    seg = f"cycle-{cycle}" if cycle is not None else f"genesis-{genesis}"
    return f"generated/journal/archive/{seg}/posts/"


def slugs_in_manifest(manifest: dict | list | None) -> set[str]:
    """The week slugs the LIVE posts.json publishes. Anything else under
    `generated/journal/posts/` is an orphaned permalink."""
    posts = manifest.get("posts", []) if isinstance(manifest, dict) else (manifest or [])
    out = set()
    for p in posts:
        if not isinstance(p, dict):
            continue
        m = _MANIFEST_URL_RE.match(str(p.get("url") or ""))
        if m:
            out.add(m.group(1))
    return out


# ── S3 side ──────────────────────────────────────────────────────────────────────


def _list_week_keys(s3, bucket: str) -> list[str]:
    keys = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=JOURNAL_POSTS_PREFIX):
        for obj in page.get("Contents", []):
            if WEEK_KEY_RE.match(obj["Key"]):
                keys.append(obj["Key"])
    return sorted(keys)


def _read_manifest(s3, bucket: str):
    try:
        body = s3.get_object(Bucket=bucket, Key=JOURNAL_MANIFEST_KEY)["Body"].read().decode("utf-8", "replace")
        return json.loads(body)
    except Exception:
        return None


def _s3_exists(s3, bucket: str, key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        s3.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def sweep_journal_permalinks(
    s3,
    *,
    cycle: int | None,
    genesis: str,
    baseline_lbs: float,
    keep_slugs=None,
    apply: bool = False,
    bucket: str = S3_BUCKET,
    now_iso: str | None = None,
    log=print,
) -> dict:
    """Annotate + cycle-archive every orphaned `/journal/posts/week-NN/` permalink.

    ``keep_slugs=None`` reads the LIVE manifest and keeps what it publishes (the
    standalone repair mode). ``keep_slugs=frozenset()`` annotates every live week
    page — the reset's mode, where every page belongs to the closing cycle and the
    new cycle's own renders land afterwards.

    Returns a counters dict; writes nothing unless ``apply``.
    """
    now_iso = now_iso or datetime.now(timezone.utc).isoformat()
    if keep_slugs is None:
        keep_slugs = slugs_in_manifest(_read_manifest(s3, bucket))
        log(f"  manifest keeps {len(keep_slugs)} slug(s): {', '.join(sorted(keep_slugs)) or '(none)'}")
    keep_slugs = set(keep_slugs)

    notice = build_archive_notice(cycle, genesis, baseline_lbs)
    dest_prefix = archive_prefix_for(cycle, genesis)
    reason = f"experiment_restart_{genesis}"
    stats = {"scanned": 0, "kept_live": 0, "not_html": 0, "annotated": 0, "already_current": 0, "archived": 0, "no_anchor": 0}
    touched: list[str] = []

    for key in _list_week_keys(s3, bucket):
        stats["scanned"] += 1
        slug = WEEK_KEY_RE.match(key).group(1)
        if slug in keep_slugs:
            stats["kept_live"] += 1
            log(f"    keep     {slug} — published by the live manifest")
            continue
        body = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8", "replace")
        if not is_article_html(body):
            stats["not_html"] += 1
            log(f"    skip     {slug} — no prose to annotate (raw tombstone/stub, left as-is)")
            continue

        dest_key = f"{dest_prefix}{slug}/index.html"
        if _s3_exists(s3, bucket, dest_key):
            log(f"    archived {slug} — already at {dest_key}")
        else:
            stats["archived"] += 1
            log(f"    {'would archive' if not apply else 'archive '} {slug} → {dest_key}")
            if apply:
                s3.put_object(
                    Bucket=bucket,
                    Key=dest_key,
                    Body=strip_archive_notice(body).encode("utf-8"),
                    ContentType="text/html",
                    CacheControl="max-age=300",
                    Metadata={"archived_at": now_iso, "archived_reason": reason},
                )

        new_html, outcome = inject_archive_notice(body, notice)
        if outcome == "current":
            stats["already_current"] += 1
            log(f"    notice   {slug} — already carries the current archive notice")
            continue
        if outcome == "no-anchor":
            stats["no_anchor"] += 1
            log(f"    WARN     {slug} — no insertion anchor found; page left untouched")
            continue
        stats["annotated"] += 1
        touched.append(f"/journal/posts/{slug}/")
        log(f"    {'would annotate' if not apply else 'annotate'} {slug} — archive notice {outcome}")
        if apply:
            s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=new_html.encode("utf-8"),
                ContentType="text/html",
                CacheControl="max-age=300",
                Metadata={"archive_notice_at": now_iso, "archive_notice_reason": reason},
            )

    stats["touched_paths"] = touched
    return stats


def _current_cycle():
    try:
        import boto3

        ssm = boto3.client("ssm", region_name=REGION)
        return int(ssm.get_parameter(Name="/life-platform/experiment-cycle")["Parameter"]["Value"])
    except Exception as e:
        print(f"  (warn: could not read /life-platform/experiment-cycle from SSM: {e})")
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Annotate + cycle-archive orphaned journal permalinks (#3512).")
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run)")
    parser.add_argument(
        "--ignore-manifest",
        action="store_true",
        help="Annotate EVERY live week page, not just the ones absent from posts.json (the reset's mode)",
    )
    parser.add_argument("--cycle", type=int, default=None, help="Override the cycle number (default: SSM)")
    args = parser.parse_args()

    import boto3

    from lambdas.common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE

    mode = "APPLY" if args.apply else "DRY-RUN"
    cycle = args.cycle if args.cycle is not None else _current_cycle()
    print(f"[{mode}] journal archive notice — genesis={EXPERIMENT_START_DATE} baseline={EXPERIMENT_BASELINE_WEIGHT_LBS} cycle={cycle}")
    s3 = boto3.client("s3", region_name=REGION)
    stats = sweep_journal_permalinks(
        s3,
        cycle=cycle,
        genesis=EXPERIMENT_START_DATE,
        baseline_lbs=float(EXPERIMENT_BASELINE_WEIGHT_LBS),
        keep_slugs=frozenset() if args.ignore_manifest else None,
        apply=args.apply,
    )
    print(
        f"\n  scanned={stats['scanned']} kept_live={stats['kept_live']} not_html={stats['not_html']} "
        f"archived={stats['archived']} annotated={stats['annotated']} already_current={stats['already_current']} "
        f"no_anchor={stats['no_anchor']}"
    )
    if stats["touched_paths"]:
        paths = " ".join(f'"{p}*"' for p in stats["touched_paths"])
        print(
            f"\n  CloudFront invalidation for the touched permalinks:\n    aws cloudfront create-invalidation --distribution-id E3S424OXQZ8NBE --paths {paths}"
        )
    if not args.apply:
        print("\n(dry-run) — pass --apply to commit.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
