#!/usr/bin/env python3
"""
scripts/sync_diary_publications.py — close the cut→entry→engagement loop (#1845).

Reads the studio's append-only ``PUBLISH_LOG.md`` and writes one
``DIARY_PUBLISH#{channel}`` / ``POST#{post_id}`` provenance row per published cut, so the
inbound social ingestion path (``lambdas/ingestion/youtube_lambda.py``) can stamp every
matching post with the session, cut and diary entry it came from. Record shape, parsing
and the Goodhart guardrail all live in ``lambdas/diary_publish.py`` — read that module
docstring first; this file is only the I/O around it.

WHY A SCRIPT, NOT A LAMBDA (same reasoning as ``scripts/backfill_vocal_metrics.py``):
the publish log lives in the private studio tree outside this repo, nothing in AWS can
see it, and publishing itself is a deliberate manual act ("you never post anything
anywhere" — the studio desk's standing rule). A human posts a cut, logs it, and runs
this. There is no schedule and no auto-invoke.

USAGE
    python3 scripts/sync_diary_publications.py ~/Documents/Claude/vlog/PUBLISH_LOG.md
    python3 scripts/sync_diary_publications.py <log> --apply
    python3 scripts/sync_diary_publications.py <log> --verify

The log path is ALWAYS an explicit argument — this script never hardcodes a path into the
private studio tree, and that tree is never committed to this repo.

  (default)   dry-run: parse, validate, print exactly what would be written, touch nothing
  --apply     write the publication rows (idempotent put_item on a stable key)
  --verify    read the stored rows back and report any disagreement with the log — AC1's
              "the studio log and the platform record agree", checkable on demand

WHAT THIS WRITES (and does not)
  - One row per published cut that has a resolvable ``(channel, post_id)``: session slug,
    cut id/file/kind, surface, URL, publish date, entry date, and the entry's sk when it
    can be resolved unambiguously. Provenance only.
  - NEVER any tape content: no transcript, no captions, no quote, no description. The
    words stay in Notion (consent-gated, ADR-142); this ledger is pointers.
  - Nothing at all for a row the deterministic gate refuses — refusals are printed with
    the cell to fix, never silently dropped ("report the skips", STUDIO.md §4.5).

ENTRY RESOLUTION
  1. The log's ``entry`` column (a Notion page URL) → the exact entry sk, derived with
     ``notion_lambda.build_sk``'s own rule (last 12 hex of the de-hyphenated page id).
  2. With AWS available, a query of that date's journal entries: used ONLY when exactly
     one entry exists for the date+channel. Two recordings in one day is a legal state
     (``MULTI_PER_DAY``), and guessing between them would attach engagement to the wrong
     entry — so an ambiguous date resolves to no sk, and says so.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from privacy import diary_publish  # noqa: E402

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")

# Fields compared by --verify. Deliberately the provenance chain and nothing derived —
# `recorded_at` is expected to differ, and comparing it would make every row look drifted.
_VERIFY_FIELDS = ("session_slug", "cut_id", "surface", "url", "published_date", "entry_date")


# ── I/O layer (boto3) ──────────────────────────────────────────────────────────────────


def _table():
    import boto3

    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


def resolve_entry_sk(table, entry_date: str, entry_channel: str):
    """The date's single diary entry sk, or None when absent OR ambiguous.

    Ambiguity is resolved to None on purpose (see the module docstring): attaching a cut's
    engagement to the wrong one of two same-day recordings is worse than attaching it to
    none, because the error is invisible downstream.
    """
    if table is None:
        return None
    from boto3.dynamodb.conditions import Key

    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER_ID}#SOURCE#notion")
            & Key("sk").begins_with(f"DATE#{entry_date}#journal#{entry_channel}"),
        )
    except Exception as e:  # noqa: BLE001 — resolution is best-effort; the row is still written
        print(f"      (entry lookup failed for {entry_date}: {e})")
        return None
    sks = [item["sk"] for item in resp.get("Items", [])]
    if len(sks) == 1:
        return sks[0]
    if len(sks) > 1:
        print(f"      (entry ambiguous for {entry_date}: {len(sks)} entries — no entry_sk written; add the Notion URL to the log)")
    return None


# ── The sweep ──────────────────────────────────────────────────────────────────────────


def load_rows(log_path: Path):
    """Parse the log; returns (rows, problems). Raises on an unreadable file."""
    return diary_publish.parse_publish_log(log_path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("log_path", help="Path to the studio's PUBLISH_LOG.md (explicit — never hardcoded)")
    parser.add_argument("--apply", action="store_true", help="Actually write the publication rows (default: dry-run)")
    parser.add_argument("--verify", action="store_true", help="Compare stored rows against the log and report disagreements")
    args = parser.parse_args(argv)

    log_path = Path(args.log_path).expanduser()
    if not log_path.is_file():
        print(f"No such publish log: {log_path}")
        return 2

    rows, problems = load_rows(log_path)
    for problem in problems:
        print(f"LOG   {problem}")
    if not rows:
        print(f"No publication rows in {log_path} (an empty log is a normal state — nothing has been posted yet)")
        return 0

    # `Any` deliberately: a boto3 Table resource is untyped, and dry-run holds None here.
    table: Any = _table() if (args.apply or args.verify) else None
    now_iso = datetime.now(timezone.utc).isoformat()
    written = refused = unjoinable = drifted = matched = missing = errors = 0

    for row in rows:
        ok, reason, normalized = diary_publish.admit_publication(row)
        if not ok:
            print(f"REFUSE line {row.get('_lineno')}  — {reason}")
            refused += 1
            continue

        if not normalized.get("entry_sk") and normalized.get("entry_date"):
            normalized["entry_sk"] = resolve_entry_sk(table, normalized["entry_date"], normalized["entry_channel"])

        record = diary_publish.build_publication_record(normalized, now_iso, user_id=USER_ID)
        label = f"{normalized['cut_id']} → {normalized['surface']}"
        if record is None:
            # Provenance without a joinable post id: real, and honestly reported.
            print(f"NOJOIN {label}  — no recognised post URL ({normalized['url'] or 'no link'}); engagement cannot be joined for this one")
            unjoinable += 1
            continue

        if args.verify:
            try:
                stored = (table.get_item(Key=diary_publish.publish_key(record["channel"], record["post_id"])) or {}).get("Item")
            except Exception as e:  # noqa: BLE001
                print(f"ERROR {label}  — {e}")
                errors += 1
                continue
            if not stored:
                print(f"MISSING {label}  — logged but not in the ledger (run with --apply)")
                missing += 1
                continue
            diffs = [f"{f}: log={record.get(f)!r} ledger={stored.get(f)!r}" for f in _VERIFY_FIELDS if record.get(f) != stored.get(f)]
            if diffs:
                print(f"DRIFT {label}  — " + "; ".join(diffs))
                drifted += 1
            else:
                matched += 1
            continue

        if not args.apply:
            entry = record.get("entry_sk") or f"(no entry sk — date {record['entry_date']})"
            print(f"DRY-RUN {label}  post={record['channel']}:{record['post_id']}  session={record['session_slug']}  entry={entry}")
            continue

        try:
            table.put_item(Item=record)  # idempotent: stable key, wholly owned by this script
            print(f"WROTE {label}  post={record['channel']}:{record['post_id']}  entry={record.get('entry_sk') or '(none)'}")
            written += 1
        except Exception as e:  # noqa: BLE001 — one bad row must not abort the sweep
            print(f"ERROR {label}  — {e}")
            errors += 1

    if args.verify:
        print(f"\nVerify. matched={matched} drifted={drifted} missing={missing} refused={refused} unjoinable={unjoinable} errors={errors}")
        return 1 if (drifted or missing or errors) else 0
    print(
        f"\nDone. written={written} refused={refused} unjoinable={unjoinable} errors={errors}"
        + ("" if args.apply else "  (dry-run — pass --apply to write)")
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
