#!/usr/bin/env python3
"""
restart_chronicle_handler.py — ADR-058: Chronicle hide + archive for the
experiment restart. Reads genesis from lambdas/common/constants.py.

Per spec §7 + Matthew's D decision:
  - All chronicle DDB records: already tombstoned + hidden=true via §5 wipe
  - This script handles the S3 + frontend side:
      1. Move all chronicle HTML under blog/ to blog/archive/pilot/<key>
         (tombstone-overwrite original since IAM blocks DeleteObject)
      1b. Journal permalinks (/journal/posts/week-NN/) — archive a pristine copy
         under a CYCLE-KEYED prefix and inject an editor's-note archive banner in
         place, so a prior cycle's article stays readable at its permalink and
         reconciles its superseded numbers instead of asserting them as current
         (#3512, deploy/journal_archive_notice.py). Deliberately NOT step 1's
         copy-then-tombstone: that wrote raw JSON over a public URL, and its
         constant archive prefix collided per-slug so it archived nothing.
      2. Rewrite chronicle index page(s) to show empty Day-1 state
      3. Re-date the PRELAUNCH_CALENDAR arc (chronicle entries untombstoned +
         re-dated to genesis − days_before; podcast entries reported here and
         resurrected by restart_media_reset.py). --resurrect-sk is the legacy
         explicit override; --no-default-leadins opts out.

Date-agnostic. Idempotent — re-running won't re-archive already-archived
files (checks existence first).

Usage:
    python3 deploy/restart_chronicle_handler.py            # dry-run
    python3 deploy/restart_chronicle_handler.py --apply    # commit
    python3 deploy/restart_chronicle_handler.py --apply --resurrect-sk DATE#2026-05-16
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
# deploy/ itself, so the sibling import below resolves when this module is imported
# rather than run as a script (curate_prelaunch_leadins, restart_media_reset do both).
sys.path.insert(0, str(Path(__file__).resolve().parent))

import journal_archive_notice  # noqa: E402 — sibling deploy module (#3512), imported by leaf name like restart_media_reset does

from lambdas.common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS, EXPERIMENT_START_DATE

REGION = "us-west-2"
S3_BUCKET = "matthew-life-platform"

REDIRECTS_MAP_PATH = REPO_ROOT / "redirects.map"


def register_permalink_redirect(old_path: str, new_path: str, apply: bool) -> bool:
    """Idempotently append `old_path -> new_path` to redirects.map (#1805): a
    tombstoned public permalink must 301 at the edge, not serve its raw JSON
    tombstone marker at HTTP 200. No-op on dry-run or if already present.
    NOTE: editing redirects.map alone does not change live behavior — the
    v4-redirects CloudFront Function body is a separately generated+published
    artifact (deploy/v4_cutover.sh's generation step, deploy/generated/
    v4_redirects_function.js) that only Matthew re-publishes (console/CLI);
    nothing here touches CloudFront.
    """
    if not apply:
        return False
    try:
        text = REDIRECTS_MAP_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    if any(line.startswith(f"{old_path}\t") for line in text.splitlines()):
        return False
    if not text.endswith("\n"):
        text += "\n"
    text += f"{old_path}\t{new_path}\n"
    REDIRECTS_MAP_PATH.write_text(text, encoding="utf-8")
    return True


def unregister_permalink_redirect(old_path: str, apply: bool) -> bool:
    """The paired REMOVAL for register_permalink_redirect (#3284): drop
    `old_path`'s redirect line from redirects.map. Before this existed the
    register was a one-way ratchet — #1805 registered week-04/05/06 on the
    premise they were permanent orphans, the premise went false when cycle 14
    published week-04, and the live 301 blackholed the published article for
    every reader. Idempotent; no-op on dry-run, on a missing map, or when the
    line is already absent. Returns True iff a line was removed.
    Same NOTE as register: the live CloudFront function body is regenerated
    from redirects.map and re-published by Matthew — nothing here touches
    CloudFront.
    """
    if not apply:
        return False
    try:
        text = REDIRECTS_MAP_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    lines = text.splitlines()
    kept = [line for line in lines if not line.startswith(f"{old_path}\t")]
    if len(kept) == len(lines):
        return False
    REDIRECTS_MAP_PATH.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
    return True


# A journal permalink redirect source, as register_permalink_redirect writes it
# (week-{seq:02d}, so \d{2,} covers seq >= 100 too).
_JOURNAL_PERMALINK_RE = re.compile(r"^/journal/posts/week-\d{2,}/$")


def unregister_journal_permalink_redirects(apply: bool) -> list[str]:
    """Remove EVERY /journal/posts/week-NN/ redirect source from redirects.map
    (#3284). Called by untombstone_and_redate(): the moment any chronicle record
    is resurrected, the journal namespace is publishing again — the lead-ins
    re-render at week-01..0K and the Wednesday cadence continues the sequence —
    so no week-NN slug is a "permanent orphan" (the #1805 premise) anymore.
    The removal is deliberately the whole set, not the resurrected record's own
    slug: a record's sequence is assigned at render time by
    restart_leadin_pages.seq_for over the FULL visible set, so it is not
    derivable per-record here, and any armed week-NN 301 will eventually
    blackhole a published installment (the #3284 mechanism). The residual
    exposure — an unpublished week-NN serving its raw JSON tombstone at 200
    until the cadence reaches it — is bounded and unlinked (posts.json does not
    list it), whereas the 301 blackholes real published content.
    Returns the removed source paths ([] on dry-run).
    """
    if not apply:
        return []
    try:
        text = REDIRECTS_MAP_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    removed = [line.split("\t", 1)[0] for line in text.splitlines() if _JOURNAL_PERMALINK_RE.match(line.split("\t", 1)[0])]
    for old_path in removed:
        unregister_permalink_redirect(old_path, apply)
    return removed


# Each entry: (prefix, archive_prefix, index_key). index_key=None → no index page
# to rewrite for that prefix (the archive step still runs).
CHRONICLE_PREFIXES = [
    ("blog/", "blog/archive/pilot/", "blog/index.html"),
    ("dashboard/chronicle/posts/", "dashboard/chronicle/archive/pilot/posts/", "dashboard/chronicle/index.html"),
    ("site/chronicle/", "site/chronicle/archive/pilot/", "site/chronicle/index.html"),
    # NB the v4 article pages (generated/journal/posts/week-NN/index.html, served at
    # /journal/posts/week-NN/) were a member of this list until #3512 and now have
    # their OWN step — see step [1b] in main(). Two reasons they could not stay here:
    # (a) this list's archive prefixes carry no cycle segment, so a reused week-NN
    # slug collided with the 2026-07-10 cycle-4 archival — `archive_one` reported
    # "already archived" and did nothing for every reset since July
    # (`html_files_archived=0` in the 2026-09-04 report), leaving cycle 14/15
    # articles live at their permalinks quoting superseded baselines; and (b) the
    # tombstone-overwrite below writes raw JSON over a PUBLIC permalink, which is why
    # week-00/06/minus-1 still serve `{"tombstone": true, ...}` at HTTP 200 today. A
    # published article gets an editor's-note archive banner instead — the
    # frozen-artifact reconciliation `weight_truth_qa` actually checks for.
]

# ── Pre-launch content calendar (Matthew's rule, 2026-07-11) ─────────────────
# "Future resets re-date a whole PRE-LAUNCH ARC on a declared calendar — X days
# before: chronicle prequel 1, Y days before: podcast prequel, Z days before:
# chronicle prequel 2 — as part of the updating dates." The calendar IS the
# pre-launch arc; the days_before offsets are the tunables. Every reset re-dates
# each entry to genesis − days_before, so the story door opens on the genuine
# origin story, staged as a countdown, rather than a blank slate. The
# dormant-period auto-generated drafts are NOT kept — only this curated list.
#
# Entry kinds:
#   - "chronicle": a DDB chronicle record (sk) — this script untombstones it,
#     re-dates it to genesis − days_before, and sets phase=experiment/visible.
#     restart_leadin_pages.py then rebuilds its public page + the manifest.
#   - "podcast": an archived panelcast asset — DELEGATED to restart_media_reset.py
#     (it copies archive/pilot/<asset>.* back over the tombstones and writes
#     episodes.json/feed.xml with the entry dated genesis − days_before). This
#     script only reports podcast entries.
#
# An entry with a "skip_reason" key is skipped (and the reason printed) — the
# escape hatch for content that fails vetting (e.g. an audio artifact that can't
# be edited to comply).
#
# CRITICAL: each lead-in's PROSE must be DATE-AGNOSTIC — no specific calendar
# dates, holidays (e.g. Valentine's Day), or season-specific weather — because
# the reset re-dates them every cycle. (Week 1/2 were edited to this rule on
# 2026-06-21; DATE#2026-02-28 was repaired + vetted by restart_leadin_repair.py
# on 2026-07-11; re-dating chapters that still named February/March surfaced
# wrong timing references.) Privacy absolutes also hold: no named vices, no
# genome specifics, no real public figures (tests/test_no_real_names_in_chronicle.py).
# The reset auto-carries this calendar unless --no-default-leadins.
#
# CURATED 2026-07-12 (#1090, Matthew-directed editorial): "The Empty Journal"
# (DATE#2026-03-03) and "The Body Votes First" (DATE#2026-02-22) are RETIRED.
# The chronicle now opens on the two strongest beats: "Before the Numbers"
# (genesis−6, this calendar) followed by "The Plan, On the Record" — the
# genesis−1 pre-registration chapter, which is NOT a calendar entry: it is
# re-published after every pipeline run by publish_genesis_preregistration.py
# (see its WIPE WARNING) and sorts after the calendar lead-ins by date.
# Retiring the two records on the LIVE table (the 2026-07-10 reset already
# resurrected them) is deploy/curate_prelaunch_leadins.py's job.
PRELAUNCH_CALENDAR = [
    {"kind": "chronicle", "sk": "DATE#2026-02-28", "days_before": 6, "label": "Prologue · Before the Numbers"},
    {"kind": "podcast", "asset": "wk0", "days_before": 2, "title": "Prologue — Elena previews the experiment"},
    # 2026-07-26 (cycle-11 reset, Matthew-directed): "The Night Before Everything" —
    # the genesis-eve piece — joins the rolling arc at genesis−1. Prose was made
    # date-agnostic by deploy/vet_night_before_leadin.py (weekdays neutralized,
    # "for the first time" dropped, cycle-10 start-weight figure generalized).
    # The prereg chapter ("The Plan, On the Record") is ALSO genesis−1 by design
    # and is NOT a calendar entry — it re-publishes after every pipeline run and
    # sorts after this one within the day.
    {"kind": "chronicle", "sk": "DATE#2026-07-21", "days_before": 1, "label": "Prologue · The Night Before Everything"},
]

# Back-compat alias (pre-calendar name, 2026-06-21): the chronicle sks, in
# calendar order. Kept so older callers/notebooks that imported ORIGIN_LEAD_INS
# keep working; new code should read PRELAUNCH_CALENDAR.
ORIGIN_LEAD_INS = [e["sk"] for e in PRELAUNCH_CALENDAR if e["kind"] == "chronicle"]


def resolve_calendar(genesis: str, calendar: list[dict] | None = None) -> list[dict]:
    """Resolve the pre-launch calendar against a genesis date.

    Returns a copy of each entry with a concrete "date" key = genesis − days_before
    (ISO). Pure function — the single place offset arithmetic happens, shared by
    this script (chronicle entries) and restart_media_reset.py (podcast entries).
    """
    cal = PRELAUNCH_CALENDAR if calendar is None else calendar
    g = date.fromisoformat(genesis)
    out = []
    for entry in cal:
        e = dict(entry)
        e["date"] = (g - timedelta(days=int(e["days_before"]))).isoformat()
        out.append(e)
    return out


def list_chronicle_html(s3, prefix: str, archive_prefix: str, index_key: str) -> list[str]:
    """List all *.html under prefix excluding archive subtree and the index page."""
    out = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.startswith(archive_prefix):
                continue
            if key == index_key:
                continue
            if not key.endswith(".html"):
                continue
            out.append(key)
    return out


def s3_exists(s3, key: str) -> bool:
    try:
        s3.head_object(Bucket=S3_BUCKET, Key=key)
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def archive_one(s3, src_key: str, prefix: str, archive_prefix: str, apply: bool, now_iso: str) -> tuple[str, bool]:
    """Archive one chronicle HTML file. Returns (archive_key, did_archive)."""
    base = src_key[len(prefix) :]
    dest_key = f"{archive_prefix}{base}"
    if s3_exists(s3, dest_key):
        return dest_key, False
    if apply:
        s3.copy_object(
            Bucket=S3_BUCKET,
            Key=dest_key,
            CopySource={"Bucket": S3_BUCKET, "Key": src_key},
            MetadataDirective="REPLACE",
            Metadata={"tombstoned_at": now_iso, "tombstoned_reason": f"experiment_restart_{EXPERIMENT_START_DATE}"},
        )
        # Tombstone-overwrite the original (IAM denies DeleteObject).
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=src_key,
            Body=json.dumps(
                {
                    "tombstone": True,
                    "tombstoned_at": now_iso,
                    "archived_to": dest_key,
                    "tombstoned_reason": f"experiment_restart_{EXPERIMENT_START_DATE}",
                }
            ).encode(),
            ContentType="application/json",
        )
    return dest_key, True


def _build_chronicle_placeholder() -> str:
    """Render a full-template chronicle index 'first installment publishes Wed'
    placeholder. Uses the same chrome (nav, footer, styles) as the rest of the
    site so it doesn't look like a different page.

    ADR-058 launch-eve fix (2026-05-24): replaces the previous standalone
    527-byte HTML that lacked site styling.
    """
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <style>.nav-overlay{display:none}</style>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="description" content="The Measured Life — a weekly chronicle by Elena Voss documenting Matthew's 12-month health experiment.">
  <meta property="og:title" content="The Measured Life — Chronicle">
  <meta property="og:description" content="A weekly narrative journalism chronicle by Elena Voss.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="https://averagejoematt.com/chronicle/">
  <meta property="og:image" content="https://averagejoematt.com/assets/images/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="The Measured Life — Chronicle">
  <meta name="twitter:description" content="A weekly narrative chronicle by Elena Voss.">
  <meta name="twitter:image" content="https://averagejoematt.com/assets/images/og-image.png">
  <title>The Measured Life — Chronicle</title>
  <link rel="alternate" type="application/rss+xml" title="The Measured Life" href="/rss.xml">
  <link rel="icon" type="image/svg+xml" href="/assets/icons/favicon.svg">
  <link rel="icon" type="image/png" sizes="32x32" href="/assets/icons/favicon-32x32.png">
  <link rel="apple-touch-icon" sizes="180x180" href="/assets/icons/apple-touch-icon.png">
  <meta name="theme-color" content="#080c0a">
  <link rel="stylesheet" href="/assets/css/tokens.css">
  <link rel="stylesheet" href="/assets/css/base.css">
  <style>
    .chronicle-header {
      padding: var(--space-20) var(--page-padding) var(--space-16);
      border-bottom: 1px solid var(--border);
      max-width: var(--content-width);
      margin: 0 auto;
    }
    .chronicle-header__kicker {
      font-size: var(--text-xs);
      letter-spacing: var(--ls-tag);
      text-transform: uppercase;
      color: var(--accent-dim);
      margin-bottom: var(--space-6);
    }
    .chronicle-header__title {
      font-family: var(--font-display);
      font-size: var(--text-h1);
      line-height: var(--lh-display);
      color: var(--text);
      letter-spacing: var(--ls-display);
      margin-bottom: var(--space-8);
    }
    .chronicle-header__sub {
      font-size: var(--text-lg);
      color: var(--text-muted);
      line-height: var(--lh-body);
      max-width: var(--prose-width);
    }
    .chronicle-empty {
      padding: var(--space-20) var(--page-padding);
      max-width: var(--prose-width);
      margin: 0 auto;
      text-align: center;
    }
    .chronicle-empty__note {
      font-family: var(--font-serif);
      font-size: var(--text-lg);
      color: var(--text-muted);
      line-height: var(--lh-body);
      font-style: italic;
    }
  </style>
  <link rel="canonical" href="https://averagejoematt.com/chronicle/">
</head>
<body class="body-story">

<div id="amj-nav"></div>
<div id="amj-hierarchy-nav"></div>

<header class="chronicle-header animate-in">
  <p class="chronicle-header__kicker">The Measured Life</p>
  <h1 class="chronicle-header__title">Chronicle</h1>
  <p class="chronicle-header__sub">
    A weekly narrative chronicle by Elena Voss — embedded with Matthew, documenting the experiment as it unfolds.
  </p>
</header>

<section class="chronicle-empty animate-in">
  <p class="chronicle-empty__note">
    The first installment publishes Wednesday of the experiment's first full week.
  </p>
</section>

<div id="amj-reading-path"></div>
<div id="amj-footer"></div>

<script src="/assets/js/site_constants.js"></script>
<script src="/assets/js/components.js"></script>
</body>
</html>
"""


def rewrite_index(s3, index_key: str, apply: bool):
    """Replace a chronicle index page with a full-template Day-1 placeholder."""
    placeholder = _build_chronicle_placeholder()
    if apply:
        s3.put_object(
            Bucket=S3_BUCKET, Key=index_key, Body=placeholder.encode(), ContentType="text/html", CacheControl="public, max-age=60"
        )
    return placeholder


def _current_cycle() -> int | None:
    """Current cycle from SSM /life-platform/experiment-cycle (None if unreadable).

    By the time this handler runs inside the restart pipeline, the SSM bump has
    already happened, so this IS the new run's number — exactly what a live
    (visible, phase=experiment) record should carry per the ADR-077 write-time
    stamping convention.
    """
    try:
        ssm = boto3.client("ssm", region_name=REGION)
        return int(ssm.get_parameter(Name="/life-platform/experiment-cycle")["Parameter"]["Value"])
    except Exception as e:  # standalone runs without SSM access keep working
        print(f"    (warn: could not read experiment-cycle from SSM — cycle stamp skipped: {e})")
        return None


def untombstone_and_redate(ddb_table, sk: str, new_date: str, apply: bool, cycle: int | None = None):
    """Untombstone a chronicle DDB record, re-date it, and force it VISIBLE.

    The record's content stays — only flags update. ADR-077 fix: the wipe stamped
    phase=pilot on every chronicle (mode "all"); removing the tombstone alone left
    phase=pilot, so the read filter (phase=pilot OR tombstone → hidden) still hid
    the "resurrected" article. We now also SET phase=experiment so a kept issue is
    genuinely visible as a pinned pre-genesis lead-in.

    #951: also re-stamp `cycle` to the CURRENT run. The wipe stamps the closing
    cycle onto every tombstoned chronicle; resurrecting without re-stamping left a
    live phase=experiment Prologue chapter carrying the OLD cycle (DATE#2026-02-28
    kept cycle=4 while its freshly-written Prologue siblings carried 5), breaking
    the ADR-077 "archive navigable by reset generation" promise for that row.

    #3284: resurrection also UN-registers the journal permalink 301s — a
    resurrected record re-arms the journal publishing cadence, so leaving any
    /journal/posts/week-NN/ redirect behind blackholes the very content this
    call just made visible (cycle 14's Week 1 shipped unreachable exactly this
    way). See unregister_journal_permalink_redirects for why it is the set,
    not one slug.
    """
    if apply:
        if cycle is None:
            cycle = _current_cycle()
        update_expr = (
            "REMOVE tombstone, tombstoned_at, tombstoned_reason, #h " "SET #d = :d, #p = :exp, redated_at = :ts, redated_from_sk = :osk"
        )
        names = {"#d": "date", "#p": "phase", "#h": "hidden"}
        values = {
            ":d": new_date,
            ":exp": "experiment",
            ":ts": datetime.now(timezone.utc).isoformat(),
            ":osk": sk,
        }
        if cycle is not None:
            update_expr += ", #cyc = :cyc"
            names["#cyc"] = "cycle"
            values[":cyc"] = cycle
        ddb_table.update_item(
            Key={"pk": "USER#matthew#SOURCE#chronicle", "sk": sk},
            UpdateExpression=update_expr,
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=values,
        )
        # #3284: a resurrected record must not leave a live 301 behind.
        removed = unregister_journal_permalink_redirects(apply)
        if removed:
            print(f"      - redirects.map: unregistered {len(removed)} journal permalink 301(s): {', '.join(removed)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Commit writes (default: dry-run)")
    parser.add_argument(
        "--resurrect-sk",
        action="append",
        default=[],
        help="Chronicle DDB sk to keep + re-date as a pre-genesis lead-in (repeatable, max 2)",
    )
    parser.add_argument("--keep-days", type=int, default=5, help="Days before genesis to date the first kept chronicle (default 5)")
    parser.add_argument(
        "--no-default-leadins",
        action="store_true",
        help="Do NOT auto-carry the curated PRELAUNCH_CALENDAR entries (default: carry them)",
    )
    args = parser.parse_args()

    # Default behaviour (Matthew's pre-launch calendar rule, 2026-07-11): carry the
    # whole curated pre-launch arc, each entry re-dated to genesis − days_before.
    # Explicit --resurrect-sk overrides the calendar (legacy staggered offsets);
    # --no-default-leadins opts out entirely.
    calendar_mode = not args.resurrect_sk and not args.no_default_leadins

    if len(args.resurrect_sk) > len(ORIGIN_LEAD_INS) + 2:
        print(f"ERROR: at most {len(ORIGIN_LEAD_INS) + 2} chronicles can be kept as lead-ins.")
        sys.exit(1)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] chronicle handler. genesis={EXPERIMENT_START_DATE}")

    s3 = boto3.client("s3", region_name=REGION)
    ddb = boto3.resource("dynamodb", region_name=REGION).Table("life-platform")
    now_iso = datetime.now(timezone.utc).isoformat()
    # #951: one SSM read for the run — every resurrected record gets the same stamp.
    current_cycle = _current_cycle() if args.apply else None

    # ── 1. Archive all chronicle HTML across every chronicle prefix ──
    archived_count = 0
    skipped_count = 0
    total_html = 0
    print(f"\n[1/3] Archiving chronicle HTML across {len(CHRONICLE_PREFIXES)} prefix(es):")
    for prefix, archive_prefix, _ in CHRONICLE_PREFIXES:
        html_keys = list_chronicle_html(s3, prefix, archive_prefix, _)
        total_html += len(html_keys)
        if not html_keys:
            print(f"  [{prefix}] no files")
            continue
        print(f"  [{prefix}] {len(html_keys)} file(s):")
        for src in html_keys:
            dest, did = archive_one(s3, src, prefix, archive_prefix, args.apply, now_iso)
            if did:
                archived_count += 1
                print(f"    {('would archive' if not args.apply else 'archived')}: {src} → {dest}")
            else:
                skipped_count += 1

    # ── 1b. Journal permalinks: cycle-keyed archive + editor's-note banner (#3512) ──
    #
    # Deliberately NOT the copy-then-tombstone above. These are PUBLIC permalinks
    # that readers reach from email, RSS caches and search long after the manifest
    # stops listing them, and their prose quotes the closing cycle's baseline. The
    # sanctioned reconciliation for a frozen artifact is an editor's note, not a
    # rewrite and not a 301 that blackholes the prose (#3284's incident). The
    # pristine copy goes to an archive prefix that CARRIES THE CYCLE, which is the
    # dest-key collision fix: `archive/pilot/posts/week-NN/` was constant, so every
    # reused slug collided with the 2026-07-10 archival and nothing archived.
    #
    # keep_slugs is EMPTY here on purpose: at this point in the reset every live week
    # page belongs to the cycle that is closing (restart_leadin_pages.py re-renders
    # the slugs the NEW cycle reuses immediately after this script). That is what
    # makes the banner land by construction on every future reset rather than being a
    # one-time repair.
    print("\n[1b/3] Journal permalinks — cycle archive + archive notice (#3512):")
    journal_stats = journal_archive_notice.sweep_journal_permalinks(
        s3,
        cycle=current_cycle,
        genesis=EXPERIMENT_START_DATE,
        baseline_lbs=float(EXPERIMENT_BASELINE_WEIGHT_LBS),
        keep_slugs=frozenset(),
        apply=args.apply,
        now_iso=now_iso,
    )
    print(
        f"  scanned={journal_stats['scanned']} archived={journal_stats['archived']} "
        f"annotated={journal_stats['annotated']} already_current={journal_stats['already_current']} "
        f"not_html={journal_stats['not_html']} no_anchor={journal_stats['no_anchor']}"
    )

    # ── 2. Rewrite each index (prefixes with index_key=None have no hub page) ──
    print("\n[2/3] Rewriting chronicle index pages:")
    index_keys = [ik for _, _, ik in CHRONICLE_PREFIXES if ik]
    for index_key in index_keys:
        placeholder = rewrite_index(s3, index_key, args.apply)
        print(f"  ({'would write' if not args.apply else 'wrote'}) {index_key}  ({len(placeholder)} bytes, Day-1 placeholder)")

    # ── 3. Resurrect entries ──
    resurrected = 0
    if calendar_mode:
        # Pre-launch calendar (2026-07-11): each entry re-dated to genesis −
        # days_before. Chronicle entries are handled here; podcast entries are
        # DELEGATED to restart_media_reset.py (reported for visibility only).
        entries = resolve_calendar(EXPERIMENT_START_DATE)
        print(f"\n[3/3] Pre-launch calendar ({len(entries)} entries, genesis={EXPERIMENT_START_DATE}):")
        for e in entries:
            desc = e.get("label") or e.get("title") or e.get("sk") or e.get("asset")
            if e.get("skip_reason"):
                print(f"  SKIP  {e['kind']:9s} {desc} — {e['skip_reason']}")
                continue
            if e["kind"] == "chronicle":
                print(f"  {e['date']}  chronicle  {e['sk']}  \"{desc}\"  (genesis−{e['days_before']}, phase=experiment, visible)")
                if args.apply:
                    untombstone_and_redate(ddb, e["sk"], e["date"], args.apply, cycle=current_cycle)
                resurrected += 1
            elif e["kind"] == "podcast":
                print(
                    f"  {e['date']}  podcast    {e['asset']}  \"{desc}\"  (genesis−{e['days_before']} — restart_media_reset.py resurrects it)"
                )
            else:
                print(f"  SKIP  unknown calendar kind {e['kind']!r}: {e}")
    elif args.resurrect_sk:
        # Legacy override path (ADR-077 dec D): explicit keepers re-dated to
        # genesis − N days (default 5), staggered one day earlier per additional
        # keeper so multiple keepers preserve their original chronological order.
        genesis = date.fromisoformat(EXPERIMENT_START_DATE)
        new_dates = [(genesis - timedelta(days=args.keep_days + i)).isoformat() for i in range(len(args.resurrect_sk))]
        print(f"\n[3/3] Keeping {len(args.resurrect_sk)} chronicle(s) as pre-genesis lead-ins (explicit --resurrect-sk override):")
        for sk, new_date in zip(args.resurrect_sk, new_dates):
            print(f"  {sk} → re-dated to {new_date} (phase=experiment, visible)")
            if args.apply:
                untombstone_and_redate(ddb, sk, new_date, args.apply, cycle=current_cycle)
            resurrected += 1
    else:
        print("\n[3/3] --no-default-leadins: blank chronicle, fresh start on next Wed cycle.")

    # Report
    report_path = REPO_ROOT / "docs" / "restart" / "_chronicle_report.txt"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        f"chronicle handler report — mode={mode} — genesis={EXPERIMENT_START_DATE}\n"
        f"generated={now_iso}\n\n"
        f"html_files_total       = {total_html}\n"
        f"html_files_archived    = {archived_count}\n"
        f"html_files_already_archived = {skipped_count}\n"
        # #3512: the journal permalinks report SEPARATELY. Folding them into the
        # counters above is how `html_files_archived=0` read as "nothing to do" for
        # two months while three cycle-14/15 articles sat live at their permalinks.
        f"journal_pages_scanned  = {journal_stats['scanned']}\n"
        f"journal_pages_archived = {journal_stats['archived']}\n"
        f"journal_notices_written = {journal_stats['annotated']}\n"
        f"journal_notices_current = {journal_stats['already_current']}\n"
        f"journal_pages_no_prose = {journal_stats['not_html']}\n"
        f"journal_pages_no_anchor = {journal_stats['no_anchor']}\n"
        f"index_pages_rewritten  = {len(index_keys)}\n"
        f"chronicles_resurrected = {resurrected}\n"
    )
    print(f"\nReport written to: {report_path.relative_to(REPO_ROOT)}")
    if not args.apply:
        print("\n(dry-run) — pass --apply to commit.")


if __name__ == "__main__":
    main()
