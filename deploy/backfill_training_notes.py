#!/usr/bin/env python3
"""
backfill_training_notes.py — one-time resumable backfill of the derived note-signal layer
over existing Hevy workouts that carry non-empty notes.

Trivial at current scale (~1 session) but written resumable for growth. Mirrors the
meal-layer backfill. Reads raw Hevy workouts, runs the SAME extractor + projection writer
the on-ingest hook uses, and elevates pain. Dry-run by default.

#3816: `--apply` no longer overwrites a changed extraction in place. `write_workout_notes`
archives the prior to `ARCHIVE#DATE#…#WORKOUT#<id>#<prior extracted_at>` and stamps
`supersedes` on the new head; an UNCHANGED extraction writes nothing at all.
`--report-overwrites` is the read-only preview of exactly that: which stored records a
re-run would version, counted before anything is written.

Usage:
  python3 deploy/backfill_training_notes.py                        # dry-run, all dates
  python3 deploy/backfill_training_notes.py --apply                # write
  python3 deploy/backfill_training_notes.py --since 2026-06-01 --apply
  python3 deploy/backfill_training_notes.py --report-overwrites    # READ-ONLY; writes nothing
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import boto3  # noqa: E402
from boto3.dynamodb.conditions import Key  # noqa: E402
from training import training_notes as tn  # noqa: E402
from training.training_notes_llm import make_llm_fn  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE = os.environ.get("TABLE_NAME", "life-platform")


def _noted_workouts(table, since):
    """Every noted Hevy workout since `since` — PAGINATED.

    The original read one `table.query` page and called it the corpus. At ~5 years of
    workouts that is a 1MB truncation, and it silently returns the OLDEST slice: a
    "whole-history" backfill that never reaches this year. A count taken from it would
    be a floor reported as a total (#3816 box 4 needs the total)."""
    workouts = []
    kwargs = {"KeyConditionExpression": Key("pk").eq("USER#matthew#SOURCE#hevy") & Key("sk").between(f"DATE#{since}", "DATE#9999~")}
    while True:
        resp = table.query(**kwargs)
        workouts.extend(it for it in resp.get("Items", []) if "#WORKOUT#" in it.get("sk", ""))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return [w for w in workouts if any((e.get("notes") or "").strip() for e in (w.get("exercises") or []))]


def _cached_llm_fn(table):
    """A READ-ONLY stand-in for the model tail: the hash cache the live extractor already
    populated (`training_notes#CACHE / HASH#<note_hash>`). A hit returns exactly what a
    live re-run would get, for $0 and zero writes. A miss raises, which is why the report
    buckets those rows as `undetermined` rather than guessing at them."""
    from training.training_notes_llm import cache_get

    def _fn(note_text, _taxonomy):
        cached = cache_get(table, tn.note_hash(note_text))
        if cached is None:
            raise LookupError("no cached extraction for this note")
        return cached

    return _fn


def report_overwrites(table, since):
    """Read-only: which stored note records would a re-run VERSION? (#3816 box 4)

    Writes nothing, calls no model. For each stored record the predicted re-extraction is
    built from the deterministic pass plus the CACHED model tail; a note with no cached
    tail cannot be predicted without spending, and is reported as `undetermined` instead
    of being counted either way.
    """
    llm_fn = _cached_llm_fn(table)
    buckets = {"would_version": [], "unchanged": [], "absent": [], "undetermined": []}
    for w in _noted_workouts(table, since):
        date = w.get("date")
        wid = str(w.get("workout_uid") or "").split(":")[-1]
        for ex in w.get("exercises") or []:
            note = (ex.get("notes") or "").strip()
            if not note:
                continue
            tid, name = tn.normalize_exercise_key(ex)
            pk, sk = tn.notes_pk(tid), f"DATE#{date}#WORKOUT#{wid}"
            row = {"date": date, "exercise": name, "template_id": tid, "sk": sk}
            stored = (table.get_item(Key={"pk": pk, "sk": sk}) or {}).get("Item")
            if not stored:
                buckets["absent"].append(row)
                continue
            row["stored_extracted_at"] = stored.get("extracted_at")
            row["stored_extracted_by"] = stored.get("extracted_by")
            # (a) forced by the extraction contract — no model needed, and it holds even
            #     where the cached tail is missing.
            forced = tn.certain_change_reason(stored, note)
            if forced:
                row["why"] = forced
                buckets["would_version"].append(row)
                continue
            # (b) otherwise predict the whole extraction from the CACHED tail.
            predicted = tn.extract_signals(note, llm_fn=llm_fn)
            if predicted.get("degraded"):
                # The only degrade path reachable here is the cache miss above: the
                # prediction would need a model call, so it is not made.
                buckets["undetermined"].append(row)
                continue
            if tn.extraction_changed(stored, predicted):
                row["why"] = "cached re-extraction differs from the stored record"
                buckets["would_version"].append(row)
            else:
                buckets["unchanged"].append(row)

    print("REPORT-OVERWRITES (read-only; nothing was written)\n")
    for label in ("would_version", "unchanged", "absent", "undetermined"):
        rows = buckets[label]
        print(f"{label}: {len(rows)}")
        for r in rows:
            extra = f"  [stored {r.get('stored_extracted_by')} @ {r.get('stored_extracted_at')}]" if r.get("stored_extracted_at") else ""
            why = f"  — {r['why']}" if r.get("why") else ""
            print(f"    {r['date']}  {r['exercise']}  {r['sk']}{extra}{why}")
        print()
    print(
        f"A re-run today would VERSION {len(buckets['would_version'])} stored record(s) "
        f"(prior archived + `supersedes` stamped), leave {len(buckets['unchanged'])} untouched, "
        f"and CREATE {len(buckets['absent'])}. {len(buckets['undetermined'])} cannot be predicted "
        "without a model call (no cached extraction for that note)."
    )
    return buckets


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2000-01-01")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--report-overwrites",
        action="store_true",
        help="READ-ONLY: list the stored records a re-run would version, and write nothing",
    )
    args = ap.parse_args()
    if args.report_overwrites and args.apply:
        ap.error("--report-overwrites is read-only; it cannot be combined with --apply")

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)

    if args.report_overwrites:
        report_overwrites(table, args.since)
        return

    llm_fn = make_llm_fn(table) if args.apply else None  # dry-run: deterministic-only, no model spend

    total_records = total_pain = total_workouts = 0
    total_wrote = total_skipped = total_versioned = 0
    for w in _noted_workouts(table, args.since):
        exs = w.get("exercises") or []
        total_workouts += 1
        res = tn.write_workout_notes(table, w["date"], w.get("workout_uid", ""), exs, dry_run=not args.apply, llm_fn=llm_fn)
        total_records += res["records"]
        total_wrote += res["wrote"]
        total_skipped += res["skipped"]
        total_versioned += res["versioned"]
        if args.apply:
            for it in res.get("items", []):
                if it.get("pain_flag"):
                    tn.elevate_pain(table, it)
                    total_pain += 1
        print(f"  {w['date']} {w.get('workout_uid', '')}: {res['records']} records" + (" [dry-run]" if not args.apply else ""))

    print(
        f"\n{'APPLIED' if args.apply else 'DRY-RUN'}: {total_workouts} noted workouts → {total_records} records, {total_pain} pain elevated"
    )
    if args.apply:
        # #3816: the stored past is an outcome of this run, so it is reported as one.
        print(f"         rows written {total_wrote} ({total_versioned} versioned, prior archived), {total_skipped} unchanged and skipped")


if __name__ == "__main__":
    main()
