#!/usr/bin/env python3
"""
scripts/backfill_vocal_metrics.py — write deterministic vocal biomarkers (#1842) to
existing journal entries, computed from local Whisper SRT files.

WHY A SCRIPT, NOT A LAMBDA (see lambdas/vocal_metrics.py's module docstring for the full
spec/definitions this script writes): the SRT files this feature needs live outside this
repo, in the private studio tree the vlog session desk uses. The vlog upload path to
Notion does NOT carry the SRT — Notion only ever sees the transcript's plain TEXT baked
into the entry body, never the timecoded file — so there is no ingest-time Lambda hook
that could ever see an SRT. The honest architecture is this: a small script, run locally
right after a diary session (or as a one-off backfill sweep over the whole studio
archive), that a human points at a directory and that writes ONLY the resulting numbers
back to DynamoDB.

USAGE
    python3 scripts/backfill_vocal_metrics.py <srt-dir> --channel video_diary
    python3 scripts/backfill_vocal_metrics.py <srt-dir> --channel solo_recording --apply

<srt-dir> is ALWAYS an explicit argument — this script never hardcodes a path to the
private studio tree (e.g. ~/Documents/Claude/vlog/sessions), and that tree is never
committed to this repo. Every *.srt file found recursively under <srt-dir> is a
candidate.

Dry-run by default (prints what would be written, touches nothing); --apply commits.
Matches the platform's standing "manual publish stays manual" convention (see
scripts/v4_build_journal.py) — there is no schedule and no auto-invoke.

WHAT THIS WRITES (and does not)
  - Six numeric/derived fields per matched entry: vocal_wpm, vocal_mean_pause_s,
    vocal_pauses_per_min, vocal_fillers_per_min, vocal_duration_s, vocal_word_count,
    plus vocal_metrics_computed_at (an ISO timestamp — the only string field). See
    lambdas/vocal_metrics.py for exact definitions and docs/SCHEMA.md's "Vocal metrics
    fields" table.
  - NEVER the transcript text or any fragment of the raw SRT — this script reads the SRT
    locally, computes six numbers, and that's all that ever reaches DynamoDB.
  - update_item with an UpdateExpression that SETs ONLY those seven attributes, gated on
    attribute_exists(pk) so it can only ever touch a journal record that already exists
    (never put_item — see #1814: put_item on an existing journal record clobbers
    concurrent enrichment/claims fields other pipelines write to the same item).
  - Nothing at all for an SRT the parser can't get a usable reading from, and nothing at
    all for a date/channel with no matching journal entry — ADR-104's "absent, not
    zeroed": a day with no computable vocal metrics simply has no vocal_* fields, ever.

HOW A SESSION MAPS TO A DATE
  1. A sibling SESSION.md next to the transcript directory, if present, with a
     ``date: YYYY-MM-DD`` line in its YAML front matter (the studio's own convention —
     see any `sessions/<date>_<slug>/SESSION.md`). Preferred: it's the studio's own
     record of the session date, immune to filesystem quirks.
  2. Otherwise, a ``YYYY-MM-DD`` prefix on the SRT's own directory ancestry (the studio
     lays sessions out as `sessions/<date>_<slug>/transcript/*.srt`) — the first
     ancestor directory name (closest to furthest) that starts with a bare
     ``YYYY-MM-DD`` is used.
  3. If neither yields a date, the file is skipped and reported unresolved.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from health import vocal_metrics  # noqa: E402

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
USER_ID = os.environ.get("USER_ID", "matthew")
VALID_CHANNELS = ("video_diary", "solo_recording")

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})")
_FRONT_MATTER_DATE_RE = re.compile(r"^date:\s*(\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


# ── Pure helpers (no boto3, no network — unit-testable in isolation) ──────────────────


def iter_srt_files(root: Path) -> list[Path]:
    """All *.srt files under root, recursively, sorted for deterministic output."""
    if not root.is_dir():
        return []
    return sorted(root.rglob("*.srt"))


def find_session_date(srt_path: Path) -> str | None:
    """Resolve the YYYY-MM-DD date for one SRT file (see module docstring §HOW A
    SESSION MAPS TO A DATE). Pure with respect to boto3; does read local files
    (SESSION.md, if present) since that's the whole point of local backfill."""
    for ancestor in srt_path.parents:
        session_md = ancestor / "SESSION.md"
        if session_md.is_file():
            try:
                text = session_md.read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
            m = _FRONT_MATTER_DATE_RE.search(text)
            if m:
                return m.group(1)
        # Only walk up as far as the immediate parent-of-parent (transcript/ -> session
        # dir); beyond that we're into the shared sessions/ root and should stop.
        m = _DATE_RE.match(ancestor.name)
        if m:
            return m.group(1)
        if ancestor.name.lower() == "sessions":
            break
    return None


def compute_metrics_for_file(path: Path) -> dict | None:
    """Read one SRT file and compute its vocal metrics. Returns None (absent, per
    ADR-104) for a missing/unreadable file OR an SRT the parser can't get a usable
    reading from — the two "no signal" cases collapse to the same contract for the
    caller: don't write anything."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    return vocal_metrics.parse_srt(text)


def build_update_kwargs(pk: str, sk: str, metrics: dict, computed_at: str) -> dict:
    """The exact update_item() kwargs for one entry — SET-only, gated to an existing
    item, numeric fields cast to Decimal (DynamoDB rejects float). Split out from
    write_vocal_metrics() so the shape is unit-testable without a live table."""
    field_map = {
        "wpm": "vocal_wpm",
        "mean_pause_s": "vocal_mean_pause_s",
        "pauses_per_min": "vocal_pauses_per_min",
        "fillers_per_min": "vocal_fillers_per_min",
        "duration_s": "vocal_duration_s",
        "word_count": "vocal_word_count",
    }
    names: dict[str, str] = {"#pk": "pk"}
    values: dict[str, object] = {}
    set_parts = []
    for metric_key, attr in field_map.items():
        val = metrics.get(metric_key)
        if val is None:
            continue  # e.g. mean_pause_s absent when there were no qualifying pauses
        alias = f"#{attr}"
        placeholder = f":{attr}"
        names[alias] = attr
        values[placeholder] = Decimal(str(val))
        set_parts.append(f"{alias} = {placeholder}")
    names["#vmc"] = "vocal_metrics_computed_at"
    values[":vmc"] = computed_at
    set_parts.append("#vmc = :vmc")

    return {
        "Key": {"pk": pk, "sk": sk},
        "UpdateExpression": "SET " + ", ".join(set_parts),
        "ConditionExpression": "attribute_exists(#pk)",
        "ExpressionAttributeNames": names,
        "ExpressionAttributeValues": values,
    }


# ── I/O layer (boto3) ──────────────────────────────────────────────────────────────────


def _table():
    import boto3

    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)


def matching_journal_sks(table, date: str, channel: str) -> list[str]:
    """Every notion journal sk for this date+channel (the numbered-suffix convention
    means there can be more than one)."""
    from boto3.dynamodb.conditions import Key

    pk = f"USER#{USER_ID}#SOURCE#notion"
    prefix = f"DATE#{date}#journal#{channel}"
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(prefix),
    )
    return [item["sk"] for item in resp.get("Items", [])]


def write_vocal_metrics(table, pk: str, sk: str, metrics: dict, computed_at: str) -> None:
    table.update_item(**build_update_kwargs(pk, sk, metrics, computed_at))


# ── CLI ───────────────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("srt_dir", help="Directory to search recursively for *.srt files (e.g. the studio's sessions/ tree)")
    parser.add_argument("--channel", required=True, choices=VALID_CHANNELS, help="Journal channel these SRTs belong to")
    parser.add_argument("--apply", action="store_true", help="Actually write to DynamoDB (default: dry-run, prints only)")
    args = parser.parse_args(argv)

    root = Path(args.srt_dir).expanduser()
    srt_files = iter_srt_files(root)
    if not srt_files:
        print(f"No *.srt files found under {root}")
        return 0

    table = _table() if args.apply else None
    pk = f"USER#{USER_ID}#SOURCE#notion"
    computed_at = datetime.now(timezone.utc).isoformat()

    written = skipped_no_date = skipped_no_metrics = skipped_no_entry = errors = 0

    for srt_path in srt_files:
        date = find_session_date(srt_path)
        if not date:
            print(f"SKIP  {srt_path}  — could not resolve a session date")
            skipped_no_date += 1
            continue

        metrics = compute_metrics_for_file(srt_path)
        if metrics is None:
            print(f"SKIP  {srt_path}  ({date})  — no usable metrics (empty/degenerate SRT)")
            skipped_no_metrics += 1
            continue

        if not args.apply:
            print(
                f"DRY-RUN  {srt_path}  ({date}, channel={args.channel})  "
                f"wpm={metrics['wpm']} pauses/min={metrics['pauses_per_min']} "
                f"fillers/min={metrics['fillers_per_min']} words={metrics['word_count']} "
                f"duration_s={metrics['duration_s']}"
            )
            continue

        sks = matching_journal_sks(table, date, args.channel)
        if not sks:
            print(f"SKIP  {srt_path}  ({date}, channel={args.channel})  — no matching journal entry")
            skipped_no_entry += 1
            continue

        for sk in sks:
            try:
                write_vocal_metrics(table, pk, sk, metrics, computed_at)
                print(f"WROTE {sk}  wpm={metrics['wpm']} pauses/min={metrics['pauses_per_min']} fillers/min={metrics['fillers_per_min']}")
                written += 1
            except Exception as e:  # noqa: BLE001 — one bad entry must not abort the sweep
                print(f"ERROR {sk}  — {e}")
                errors += 1

    print(
        f"\nDone. written={written} skipped_no_date={skipped_no_date} "
        f"skipped_no_metrics={skipped_no_metrics} skipped_no_entry={skipped_no_entry} errors={errors}"
        + ("" if args.apply else "  (dry-run — pass --apply to write)")
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
