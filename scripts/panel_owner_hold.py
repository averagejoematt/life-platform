#!/usr/bin/env python3
"""scripts/panel_owner_hold.py — record, verify or release the OWNER's hold on a Panel week (#6112).

OWNER ACT (the driver runs it on the owner's ruling). Dry-run is the default and writes nothing; ``--apply`` writes.
The record shape, its validation and the publishers' refusal live in ``lambdas/emails/panelcast_hold.py``.

What ``--apply`` writes, in order:

  1. BACKUP   the live episodes.json and any hold already on the key → ``--backup-dir`` (local, required), with the
              S3 VersionIds printed (the bucket is versioned, so every pre-image is also restorable by version).
  2. RECORD   ``panelcast-holds/wk{N}.json`` (private): hold_class "owner", status "held", decided_at / decided_by /
              ruling / reason, the blocking findings it preserves, what lifts it, and the sha256 of the exact script
              and findings it holds (``bound_to``). The findings' TEXT is copied from the chronicle row's
              ``desk_findings_json`` into this private object only — never printed, never committed. An automated hold
              already on the key is kept whole under ``superseded_hold``.
  3. PUBLIC   episodes.json's ``held`` list, re-derived from the hold store (``panelcast_hold.public_entry``: week,
              date, decider, a reason with no private detail); a ``pending`` marker naming the week is dropped.
  4. CDN      invalidates /panelcast/episodes.json.
  5. VERIFY   the read-back below.

``--verify`` (read-only, also run after every ``--apply``): the private record is complete
(``panelcast_hold.record_problems``), the public line is a hold qa-smoke accepts (``public_problems``) on S3 AND over
HTTPS, and qa-smoke's own ``story_season_qa.episode_verdicts`` — run on the live chronicle rows and the live
episodes.json — puts the week in ``held``, not ``missing``.

``--release --apply`` is the explicit owner release (and the rollback of a mistaken ``--apply``): the record is copied
to ``panelcast-holds/wk{N}.released-<ts>.json`` with who/when/why, the key is restored to the automated hold it
superseded (or deleted), and the public ``held`` line is re-derived. Nothing is published by a release — the next
Panel run for the week goes through every gate as before.

    python3 scripts/panel_owner_hold.py --week 10 --row DATE#2026-11-10 --expect-findings 2 \\
        --decided 2026-11-16 --ruling "owner ruling 2026-11-16" --reason "script retained two blocking findings"
    ... --backup-dir <dir> --apply
    python3 scripts/panel_owner_hold.py --week 10 --verify
    python3 scripts/panel_owner_hold.py --week 10 --release --note "<why>" --backup-dir <dir> --apply
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from emails import panelcast_hold  # noqa: E402

REGION = "us-west-2"
TABLE = "life-platform"
BUCKET = "matthew-life-platform"
HOLD_PREFIX = "panelcast-holds"
PANEL_PREFIX = "generated/panelcast"
EPISODES_KEY = f"{PANEL_PREFIX}/episodes.json"
CHRONICLE_PK = "USER#matthew#SOURCE#chronicle"
SITE = "https://averagejoematt.com"
CF_DISTRIBUTION_ID = "E3S424OXQZ8NBE"
DEFAULT_LIFT = (
    "an explicit owner release only: scripts/panel_owner_hold.py --week {week} --release --note <why> --apply. "
    "No schedule, retry, redrive, force or owner_approved invoke lifts it."
)
_WRAPPER = re.compile(r"^(?:dek:\s*|turn\s+\d+\s*\([^)]*\):\s*)+", re.IGNORECASE)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hold_key(week: int) -> str:
    return f"{HOLD_PREFIX}/wk{week}.json"


def blocking_findings(raw: str, row_ref: str) -> List[Dict[str, Any]]:
    """The episode half of the desk's findings that block, each as {id, category, sha256, source, text}. The text is for
    the PRIVATE record only; ``redacted`` strips it before anything is printed."""
    from content import autopublish_audit

    found = json.loads(raw)
    blocking = set(autopublish_audit.episode_blocking(raw))
    out = []
    for i, f in enumerate(found.get("episode") or []):
        if f"desk episode: {f}" not in blocking:
            continue
        category = _WRAPPER.sub("", str(f)).split(":", 1)[0].strip().lower()[:40] or "uncategorised"
        out.append(
            {
                "id": f"desk_findings_json.episode[{i}]",
                "category": category,
                "sha256": sha256(str(f)),
                "source": f"dynamodb://{TABLE}/{row_ref}#desk_findings_json (and this record's `text`)",
                "text": str(f),
            }
        )
    return out


def redacted(rec: Dict[str, Any]) -> Dict[str, Any]:
    """The record as it may be printed: every finding's text replaced by its length; a superseded draft elided."""
    out = json.loads(json.dumps(rec, default=str))
    for f in out.get("findings") or []:
        if "text" in f:
            f["text"] = f"<{len(str(f['text']))} chars — private, written only to s3://{BUCKET}/{HOLD_PREFIX}/>"
    if isinstance(out.get("superseded_hold"), dict):
        out["superseded_hold"] = {k: v for k, v in out["superseded_hold"].items() if k in ("hold_class", "held_at", "first_held_at")}
    return out


def _get_json(s3: Any, key: str) -> tuple:
    """(doc, version_id) or (None, None) when the key does not exist."""
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
    except s3.exceptions.NoSuchKey:
        return None, None
    return json.loads(obj["Body"].read()), obj.get("VersionId")


def build(args: Any, table: Any, s3: Any) -> Dict[str, Any]:
    """The record ``--apply`` would write, from the chronicle row read now. Refuses (SystemExit) on any mismatch."""
    findings: List[Dict[str, Any]] = []
    bound: Dict[str, Any] = {}
    if args.row:
        row = table.get_item(Key={"pk": CHRONICLE_PK, "sk": args.row}).get("Item") or {}
        if not row:
            raise SystemExit(f"no chronicle row {args.row}")
        if str(row.get("week_number")) != str(args.week):
            raise SystemExit(f"{args.row} is week {row.get('week_number')!r}, not {args.week}")
        ref = f"{CHRONICLE_PK}/{args.row}"
        bound = {"chronicle_row": ref, "chronicle_status": row.get("status")}
        if row.get("desk_findings_json"):
            findings = blocking_findings(str(row["desk_findings_json"]), ref)
            bound["desk_findings_sha256"] = sha256(str(row["desk_findings_json"]))
        if row.get("desk_episode_json"):
            bound["desk_episode_sha256"] = sha256(str(row["desk_episode_json"]))
    if args.expect_findings is not None and len(findings) != args.expect_findings:
        raise SystemExit(f"the row carries {len(findings)} blocking episode finding(s), --expect-findings says {args.expect_findings}")
    prior, _ = _get_json(s3, hold_key(args.week))
    if panelcast_hold.is_owner_hold(prior) and not args.re_record:
        raise SystemExit(f"week {args.week} already carries an owner hold — pass --re-record to replace it (first_held_at is kept)")
    rec = panelcast_hold.build_record(
        args.week,
        decided_at=args.decided,
        decided_by=args.decided_by,
        ruling=args.ruling,
        reason=args.reason,
        findings=findings,
        lift=DEFAULT_LIFT.format(week=args.week),
        refs=args.refs,
        bound_to=bound,
        prior=None if panelcast_hold.is_owner_hold(prior) else prior,
    )
    if args.public_reason.strip():
        rec["public_reason"] = args.public_reason.strip()
    if panelcast_hold.is_owner_hold(prior):
        rec["first_held_at"] = prior.get("first_held_at") or rec["first_held_at"]
    problems = panelcast_hold.record_problems(rec)
    if problems:
        raise SystemExit(f"the record would not be a complete owner hold: {problems}")
    return rec


def public_doc(s3: Any, doc: Optional[Dict[str, Any]], week: int) -> Dict[str, Any]:
    """episodes.json with its ``held`` list re-derived from the hold store, and a ``pending`` marker for the week dropped."""
    out = dict(doc or {"episodes": []})
    aired = {str(e.get("week")) for e in out.get("episodes") or []}
    owner = panelcast_hold.owner_held_weeks(s3, BUCKET, HOLD_PREFIX)
    held = [panelcast_hold.public_entry(owner[w]) for w in sorted(owner) if str(w) not in aired]
    if held:
        out[panelcast_hold.PUBLIC_KEY] = held
    else:
        out.pop(panelcast_hold.PUBLIC_KEY, None)
    pending = out.get("pending")
    if isinstance(pending, dict) and str(pending.get("week")) == str(week):
        out.pop("pending")
    return out


def _write_public(s3: Any, doc: Dict[str, Any]) -> None:
    from common import journal_silence

    s3.put_object(
        Bucket=BUCKET,
        Key=EPISODES_KEY,
        Body=journal_silence.public_body(json.dumps(doc, indent=1)),
        ContentType="application/json",
        CacheControl="max-age=3600, public",
    )
    import boto3

    boto3.client("cloudfront", region_name=REGION).create_invalidation(
        DistributionId=CF_DISTRIBUTION_ID,
        InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/panelcast/episodes.json"]},
            "CallerReference": f"panel-owner-hold-{datetime.now(timezone.utc).timestamp()}",
        },
    )


def _backup(dest: str, name: str, doc: Any, version: Optional[str]) -> None:
    os.makedirs(dest, exist_ok=True)
    with open(os.path.join(dest, name), "w", encoding="utf-8") as fh:
        json.dump({"version_id": version, "body": doc}, fh, indent=1, default=str)
    print(f"BACKUP {name}: version {version} → {os.path.join(dest, name)}")


def apply_hold(args: Any, table: Any, s3: Any) -> int:
    rec = build(args, table, s3)
    doc, doc_version = _get_json(s3, EPISODES_KEY)
    if any(str(e.get("week")) == str(args.week) for e in (doc or {}).get("episodes") or []):
        raise SystemExit(f"week {args.week} has a published episode — an owner hold is for a week that has not aired")
    print(json.dumps({"would_write": hold_key(args.week), "record": redacted(rec)}, indent=1, default=str))
    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --backup-dir <dir> --apply (owner act).")
        return 0
    if not args.backup_dir:
        raise SystemExit("--apply needs --backup-dir (the pre-images are written there first)")
    prior, prior_version = _get_json(s3, hold_key(args.week))
    _backup(args.backup_dir, f"wk{args.week}.hold.before.json", prior, prior_version)
    _backup(args.backup_dir, "episodes.before.json", doc, doc_version)
    s3.put_object(Bucket=BUCKET, Key=hold_key(args.week), Body=json.dumps(rec, indent=1).encode("utf-8"), ContentType="application/json")
    print(f"WROTE s3://{BUCKET}/{hold_key(args.week)}")
    _write_public(s3, public_doc(s3, doc, args.week))
    print(f"WROTE s3://{BUCKET}/{EPISODES_KEY} (held list re-derived) + invalidated /panelcast/episodes.json")
    return verify(args.week, table, s3)


def release(args: Any, table: Any, s3: Any) -> int:
    rec, version = _get_json(s3, hold_key(args.week))
    if not panelcast_hold.is_owner_hold(rec):
        raise SystemExit(f"week {args.week} carries no owner hold — nothing to release")
    if not (args.note or "").strip():
        raise SystemExit("--release needs --note: the release is an owner decision and is recorded with its reason")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    released = {**rec, "status": "released", "released_at": stamp, "released_by": args.decided_by, "release_note": args.note}
    restore = rec.get("superseded_hold")
    print(json.dumps({"would_release": hold_key(args.week), "restores_automated_hold": bool(restore)}, indent=1))
    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --backup-dir <dir> --apply (owner act).")
        return 0
    if not args.backup_dir:
        raise SystemExit("--apply needs --backup-dir")
    _backup(args.backup_dir, f"wk{args.week}.hold.before-release.json", rec, version)
    s3.put_object(
        Bucket=BUCKET,
        Key=f"{HOLD_PREFIX}/wk{args.week}.released-{stamp}.json",
        Body=json.dumps(released, indent=1).encode("utf-8"),
        ContentType="application/json",
    )
    if restore:
        s3.put_object(
            Bucket=BUCKET, Key=hold_key(args.week), Body=json.dumps(restore, indent=1).encode("utf-8"), ContentType="application/json"
        )
    else:
        s3.delete_object(Bucket=BUCKET, Key=hold_key(args.week))
    doc, _ = _get_json(s3, EPISODES_KEY)
    _write_public(s3, public_doc(s3, doc, args.week))
    print(f"RELEASED week {args.week}: audit copy wk{args.week}.released-{stamp}.json; held list re-derived; nothing published")
    return 0


def _live_episodes() -> Any:
    req = urllib.request.Request(f"{SITE}/panelcast/episodes.json", headers={"Cache-Control": "no-cache", "User-Agent": "panel-owner-hold"})
    with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310 — the platform's own public URL
        return json.loads(resp.read())


def verify(week: int, table: Any, s3: Any) -> int:
    """Read-back: the private record, the public line (S3 and HTTPS) and qa-smoke's own verdict. 0 = the week is held."""
    from boto3.dynamodb.conditions import Key
    from operational import story_season_qa as ssq

    rec, _ = _get_json(s3, hold_key(week))
    problems = ["no owner hold record"] if not panelcast_hold.is_owner_hold(rec) else panelcast_hold.record_problems(rec)
    print(f"VERIFY private record {hold_key(week)}: {'OK' if not problems else problems}")
    s3_doc, _ = _get_json(s3, EPISODES_KEY)
    live = _live_episodes()
    for label, doc in (("s3", s3_doc or {}), ("https", live)):
        line = [e for e in doc.get(panelcast_hold.PUBLIC_KEY) or [] if str(e.get("week")) == str(week)]
        bad = ["no held line"] if not line else panelcast_hold.public_problems(line[0])
        problems += [f"{label}: {b}" for b in bad]
        print(f"VERIFY public held line ({label}): {line[0] if line else None} {'OK' if not bad else bad}")
    rows, lek = [], None
    while True:
        kw: Dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(CHRONICLE_PK) & Key("sk").begins_with("DATE#")}
        if lek:
            kw["ExclusiveStartKey"] = lek
        resp = table.query(**kw)
        rows += resp.get("Items", [])
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
    verdicts = ssq.episode_verdicts(ssq.published_weeks(rows), live, datetime.now(timezone.utc))
    print("VERIFY qa-smoke verdict on the live season (https episodes.json):")
    for bucket, lines in verdicts.items():
        print(f"  {bucket}: {lines}")
    if not any(s.startswith(f"week {week} HELD") for s in verdicts["held"] + verdicts["aged"]):
        problems.append(f"qa-smoke would not read week {week} as held")
    print("VERIFY: PASS" if not problems else f"VERIFY: FAIL {problems}")
    return 0 if not problems else 1


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--row", default=None, help="the week's chronicle sk (DATE#...) — its blocking episode findings are preserved")
    ap.add_argument("--expect-findings", type=int, default=None, help="refuse unless the row carries exactly this many")
    ap.add_argument("--decided", default=datetime.now(timezone.utc).date().isoformat(), help="the owner's decision date (ISO)")
    ap.add_argument("--decided-by", default="owner")
    ap.add_argument("--ruling", default="", help='e.g. "owner ruling 2026-11-16"')
    ap.add_argument("--reason", default="")
    ap.add_argument("--public-reason", default="", help="the public held line's reason (default: derived, no private detail)")
    ap.add_argument("--refs", default="#6112")
    ap.add_argument("--re-record", action="store_true", help="replace an existing owner hold (a new decided date)")
    ap.add_argument("--verify", action="store_true", help="read-back only")
    ap.add_argument("--release", action="store_true", help="OWNER ACT: lift the hold (also the rollback of --apply)")
    ap.add_argument("--note", default="", help="why the hold is released")
    ap.add_argument("--backup-dir", default=None)
    ap.add_argument("--apply", action="store_true", help="OWNER ACT: write")
    args = ap.parse_args(argv)
    import boto3

    os.environ.setdefault("AWS_MAX_ATTEMPTS", "1")
    s3 = boto3.client("s3", region_name=REGION)
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
    if args.verify:
        return verify(args.week, table, s3)
    if args.release:
        return release(args, table, s3)
    if not args.reason.strip() or not args.ruling.strip():
        raise SystemExit("--reason and --ruling are required: a hold names why and on whose decision")
    return apply_hold(args, table, s3)


if __name__ == "__main__":
    raise SystemExit(main())
