#!/usr/bin/env python3
"""curate_prelaunch_leadins.py — reconcile the LIVE chronicle with the curated
PRELAUNCH_CALENDAR (#1090, Matthew-directed editorial).

WHY: the 2026-07-10 cycle-5 reset resurrected the then-current 3-lead-in calendar,
so "The Empty Journal" (sk DATE#2026-03-03, re-dated genesis−4) and "The Body
Votes First" (sk DATE#2026-02-22, re-dated genesis−3) are LIVE visible records.
#1090 retires them from PRELAUNCH_CALENDAR — which fixes every FUTURE reset — but
the live table needs a one-shot reconcile so the chronicle opens on "Before the
Numbers" followed by the genesis−1 pre-registration chapter.

WHAT IT DOES (idempotent — a re-run finds nothing left to do):
  1. Query the visible (phase=experiment, non-tombstoned) chronicle installments.
  2. RETIRE every visible PRE-GENESIS record that is neither a curated
     PRELAUNCH_CALENDAR chronicle entry nor the genesis−1 pre-registration
     chapter (protected by sk AND by its pre_registration flag): re-apply the
     wipe's tombstone shape (tombstone/tombstoned_at/tombstoned_reason,
     phase=pilot, hidden=true) and restore `date` to the sk's original date —
     the exact inverse of untombstone_and_redate(). Post-genesis records are
     never touched. `cycle` is left as stamped (ADR-077 archive navigability).
  3. Rebuild the public pages + /journal/posts.json via restart_leadin_pages.run()
     (render parity with the Wednesday publish by construction). OG moment cards
     and subscriber onboarding read posts.json at run time, so they follow.
  4. Sweep now-orphaned generated/journal/posts/week-NN/ pages (seq beyond the
     post-curation count): archive-copy to
     generated/journal/archive/pilot/posts/curation-1090/ then tombstone-overwrite
     the source (IAM denies DeleteObject on generated/*) + CloudFront-invalidate.

Dry-run (default) prints exactly which DDB records would be tombstoned and which
S3 pages would be archived, with no writes.

Usage:
    python3 deploy/curate_prelaunch_leadins.py            # dry-run
    python3 deploy/curate_prelaunch_leadins.py --apply    # DDB + S3 + CloudFront
    python3 deploy/curate_prelaunch_leadins.py --apply --no-invalidate
"""

import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import boto3

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "deploy"))
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

import restart_chronicle_handler as handler  # noqa: E402  (the curated calendar)
import restart_leadin_pages as leadin  # noqa: E402  (page/manifest rebuild — reused, not copied)
from constants import EXPERIMENT_START_DATE  # noqa: E402

REGION = "us-west-2"
TABLE_NAME = "life-platform"
S3_BUCKET = "matthew-life-platform"
CLOUDFRONT_DISTRIBUTION_ID = "E3S424OXQZ8NBE"  # averagejoematt.com

CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
TOMBSTONE_REASON = "editorial_curation_1090"
ORPHAN_ARCHIVE_PREFIX = "generated/journal/archive/pilot/posts/curation-1090/"

_WEEK_PAGE_RE = re.compile(r"^generated/journal/posts/week-(\d{2})/index\.html$")


def prereg_sk(genesis: str) -> str:
    """sk of the genesis−1 pre-registration chapter (publish_genesis_preregistration.py)."""
    return f"DATE#{(date.fromisoformat(genesis) - timedelta(days=1)).isoformat()}"


def calendar_chronicle_sks(calendar: list[dict] | None = None) -> set[str]:
    cal = handler.PRELAUNCH_CALENDAR if calendar is None else calendar
    return {e["sk"] for e in cal if e["kind"] == "chronicle"}


def retirement_plan(visible: list[dict], genesis: str, calendar: list[dict] | None = None) -> list[dict]:
    """The visible PRE-GENESIS chronicle records that are no longer sanctioned lead-ins.

    Pure function over the visible-installment list: retire a record only if its
    date is strictly pre-genesis, its sk is not a curated calendar entry, and it
    is not the pre-registration chapter (protected by sk AND by flag — either
    alone is sufficient). Post-genesis installments are structurally untouchable.
    """
    protected = calendar_chronicle_sks(calendar) | {prereg_sk(genesis)}
    plan = []
    for item in visible:
        d = str(item.get("date", ""))
        if not d or d >= genesis:
            continue
        if item.get("sk") in protected or item.get("pre_registration"):
            continue
        plan.append(item)
    return plan


def build_retire_update(sk: str, now_iso: str) -> tuple[str, dict, dict]:
    """UpdateItem args that exactly invert untombstone_and_redate() and re-apply
    the wipe's chronicle tombstone shape (restart_intelligence_wipe.build_update:
    tombstone + tombstoned_at + tombstoned_reason + phase=pilot + hidden=true).
    `date` is restored to the sk's original date so the archived record no longer
    claims a re-dated pre-genesis slot."""
    update_expr = (
        "SET tombstone = :t, tombstoned_at = :ts, tombstoned_reason = :r, #p = :pilot, #h = :h, #d = :d "
        "REMOVE redated_at, redated_from_sk"
    )
    names = {"#p": "phase", "#h": "hidden", "#d": "date"}
    values = {
        ":t": True,
        ":ts": now_iso,
        ":r": TOMBSTONE_REASON,
        ":pilot": "pilot",
        ":h": True,
        ":d": sk.split("DATE#", 1)[1],
    }
    return update_expr, names, values


def list_week_page_keys(s3) -> list[str]:
    """All keys under generated/journal/posts/ (the archive lives under a sibling
    prefix, so it is never listed here)."""
    out = []
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=S3_BUCKET, Prefix="generated/journal/posts/"):
        for obj in page.get("Contents", []):
            out.append(obj["Key"])
    return out


def orphan_week_pages(keys: list[str], keep_count: int) -> list[tuple[str, int]]:
    """(key, seq) for week-NN article pages whose seq exceeds the post-curation
    installment count — the pages restart_leadin_pages.run() no longer rewrites."""
    out = []
    for key in keys:
        m = _WEEK_PAGE_RE.match(key)
        if not m:
            continue
        seq = int(m.group(1))
        if seq > keep_count:
            out.append((key, seq))
    return sorted(out, key=lambda t: t[1])


def _is_tombstone_page(s3, key: str) -> bool:
    """Idempotency probe: True if the object is already a tombstone marker."""
    try:
        body = s3.get_object(Bucket=S3_BUCKET, Key=key)["Body"].read(512)
        return bool(json.loads(body).get("tombstone"))
    except Exception:
        return False


def archive_and_tombstone_page(s3, key: str, seq: int, apply: bool, now_iso: str) -> str:
    """Archive-copy an orphaned article page, then tombstone-overwrite the source
    (same marker shape as restart_chronicle_handler.archive_one; DeleteObject is
    IAM-blocked on generated/*). The curation-1090 archive namespace avoids
    colliding with pilot pages the reset already archived at week-NN."""
    dest = f"{ORPHAN_ARCHIVE_PREFIX}week-{seq:02d}/index.html"
    if apply:
        s3.copy_object(
            Bucket=S3_BUCKET,
            Key=dest,
            CopySource={"Bucket": S3_BUCKET, "Key": key},
            MetadataDirective="REPLACE",
            Metadata={"tombstoned_at": now_iso, "tombstoned_reason": TOMBSTONE_REASON},
        )
        s3.put_object(
            Bucket=S3_BUCKET,
            Key=key,
            Body=json.dumps(
                {"tombstone": True, "tombstoned_at": now_iso, "archived_to": dest, "tombstoned_reason": TOMBSTONE_REASON}
            ).encode(),
            ContentType="application/json",
        )
    return dest


def invalidate(paths: list[str]):
    """Fail-soft CloudFront invalidation (pages carry max-age<=300 anyway)."""
    try:
        cf = boto3.client("cloudfront", region_name="us-east-1")
        ref = f"curate-1090-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        inv = cf.create_invalidation(
            DistributionId=CLOUDFRONT_DISTRIBUTION_ID,
            InvalidationBatch={"Paths": {"Quantity": len(paths), "Items": paths}, "CallerReference": ref},
        )
        print(f"  CloudFront invalidation {inv['Invalidation']['Id']} created for: {', '.join(paths)}")
    except Exception as e:
        print(f"  WARNING: CloudFront invalidation failed (objects ARE written; caches expire in <=300s): {e}")


def main():
    ap = argparse.ArgumentParser(description="Reconcile the live chronicle with the curated PRELAUNCH_CALENDAR (#1090)")
    ap.add_argument("--apply", action="store_true", help="write DDB + S3 + CloudFront (default: dry-run)")
    ap.add_argument("--no-invalidate", action="store_true", help="with --apply: skip CloudFront invalidations")
    args = ap.parse_args()

    mode = "APPLY" if args.apply else "DRY-RUN"
    genesis = EXPERIMENT_START_DATE
    print(f"[{mode}] prologue curation (#1090). genesis={genesis}")
    print(f"  curated calendar chronicle sk(s): {sorted(calendar_chronicle_sks())}")
    print(f"  protected pre-registration sk:    {prereg_sk(genesis)} (also protected by its pre_registration flag)")

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    s3 = boto3.client("s3", region_name=REGION)
    now_iso = datetime.now(timezone.utc).isoformat()

    # ── 1. What is live? ──
    visible = leadin.fetch_visible_installments(table)
    print(f"\n[1/4] Visible (phase=experiment, non-tombstoned) chronicle installments: {len(visible)}")
    for it in visible:
        print(f'  {it.get("date", "?")}  {it.get("sk")}  "{it.get("title", "")}"')

    # ── 2. Retire the uncurated lead-ins ──
    plan = retirement_plan(visible, genesis)
    if not plan:
        print("\n[2/4] Nothing to retire — the live table already matches the curated calendar.")
    else:
        verb = "tombstoning" if args.apply else "would tombstone"
        print(f"\n[2/4] Retiring {len(plan)} record(s) — tombstone ({TOMBSTONE_REASON}) + hidden + phase=pilot + date restored to sk:")
        for it in plan:
            sk = it["sk"]
            print(f'  {verb}: {sk}  "{it.get("title", "")}"  (live date {it.get("date")} → restored {sk.split("DATE#", 1)[1]})')
            if args.apply:
                expr, names, values = build_retire_update(sk, now_iso)
                table.update_item(
                    Key={"pk": CHRONICLE_PK, "sk": sk},
                    UpdateExpression=expr,
                    ExpressionAttributeNames=names,
                    ExpressionAttributeValues=values,
                )

    keep_count = len(visible) - len(plan)

    # ── 3. Rebuild pages + manifest from the curated table ──
    print(f"\n[3/4] Rebuilding journal pages + posts.json via restart_leadin_pages.run() — {keep_count} installment(s) post-curation:")
    if args.apply:
        rc = leadin.run(apply=True, no_invalidate=args.no_invalidate)
        if rc != 0:
            sys.exit(rc)
    else:
        print("  (dry-run — the plan below still reflects the CURRENT, pre-curation table; post-curation the retired entries drop out)")
        leadin.run(apply=False)

    # ── 4. Sweep the orphaned week-NN pages the rebuild no longer covers ──
    orphans = orphan_week_pages(list_week_page_keys(s3), keep_count)
    if not orphans:
        print(f"\n[4/4] No orphaned week-NN pages beyond week-{keep_count:02d}.")
    else:
        print(f"\n[4/4] Orphaned article pages beyond week-{keep_count:02d} (archive-copy + tombstone-overwrite):")
        paths = []
        for key, seq in orphans:
            if _is_tombstone_page(s3, key):
                print(f"  already tombstoned: {key}")
                continue
            dest = archive_and_tombstone_page(s3, key, seq, args.apply, now_iso)
            print(f"  {'tombstoned' if args.apply else 'would tombstone'}: {key} → archived to {dest}")
            paths.append(f"/journal/posts/week-{seq:02d}/*")
        if args.apply and paths and not args.no_invalidate:
            invalidate(paths)

    print(
        "\nDownstream surfaces derive from posts.json — OG moment cards regenerate on the next"
        "\ndaily og-image run and subscriber onboarding reads it per send; rss.xml regenerates on"
        "\nthe next site deploy (scripts/v4_build_rss.py reads the live /journal/posts.json)."
    )
    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply to commit.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
