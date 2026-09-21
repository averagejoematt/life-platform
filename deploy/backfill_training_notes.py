#!/usr/bin/env python3
"""
backfill_training_notes.py — one-time resumable backfill of the derived note-signal layer
over existing Hevy workouts that carry non-empty notes.

SCALE (measured 2026-09-19, #3918): **532 noted exercise-sessions across history have no
note record at all.** The docstring used to say "trivial at current scale (~1 session)",
which was true the day it was written and has been false for months; 532 sessions is real
Bedrock spend over historical data, which is why `--apply` is an owner decision and
`--value-census` exists to price the VALUE of that spend before it is made.

Reads raw Hevy workouts, runs the SAME extractor + projection writer the on-ingest hook
uses, and elevates pain. Dry-run by default.

#3816: `--apply` no longer overwrites a changed extraction in place. `write_workout_notes`
archives the prior to `ARCHIVE#DATE#…#WORKOUT#<id>[#<occ>]#<digest>` and stamps
`supersedes` on the new head; an UNCHANGED extraction writes nothing at all.
`--report-overwrites` is the read-only preview of exactly that: which stored records a
re-run would version, counted before anything is written.

#3918: the head key is `DATE#<d>#WORKOUT#<id>#<occurrence>` — one per exercise-SESSION,
so a workout logging the same template twice keeps both notes addressable. `--migrate`
re-keys the two known pre-#3918 collision workouts (2026-06-23, 2026-09-10 — both
Treadmill) from their stored heads and archived priors, and asserts each becomes two
distinct notes.

Usage:
  python3 deploy/backfill_training_notes.py                        # dry-run, all dates
  python3 deploy/backfill_training_notes.py --apply                # write (MODEL SPEND)
  python3 deploy/backfill_training_notes.py --since 2026-06-01 --apply
  python3 deploy/backfill_training_notes.py --report-overwrites    # READ-ONLY; writes nothing
  python3 deploy/backfill_training_notes.py --value-census         # READ-ONLY, $0; what is IN the un-extracted notes
  python3 deploy/backfill_training_notes.py --pain-burst-census --since 2026-09-19T21:00Z --until 2026-09-19T21:10Z
                                                                     # READ-ONLY (#3972); lists #pain thread rows + lexicon explanation
  python3 deploy/backfill_training_notes.py --migrate              # dry-run re-key of the collisions
  python3 deploy/backfill_training_notes.py --migrate --apply      # write the re-key (no model calls)
"""

import argparse
import os
import re
import statistics
import sys
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import boto3  # noqa: E402
from boto3.dynamodb.conditions import Key  # noqa: E402
from training import training_notes as tn  # noqa: E402
from training.training_notes_llm import make_llm_fn  # noqa: E402

REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE = os.environ.get("TABLE_NAME", "life-platform")

# The measured population `--apply` would extract (2026-09-19, #3918). Reported against,
# never assumed: `--value-census` re-counts it live on every run.
MEASURED_UNEXTRACTED = 532

# The two workouts that logged one template TWICE under the pre-#3918 key scheme.
COLLISION_DATES = ("2026-06-23", "2026-09-10")


def _query_all(table, **kwargs):
    """Every page of one query. A single page is a 1MB truncation reported as a corpus."""
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            return items
        kwargs["ExclusiveStartKey"] = lek


def _noted_workouts(table, since, until="9999"):
    """Every noted Hevy workout since `since` — PAGINATED.

    The original read one `table.query` page and called it the corpus. At ~5 years of
    workouts that is a 1MB truncation, and it silently returns the OLDEST slice: a
    "whole-history" backfill that never reaches this year. A count taken from it would
    be a floor reported as a total (#3816 box 4 needs the total)."""
    workouts = _query_all(
        table,
        KeyConditionExpression=Key("pk").eq("USER#matthew#SOURCE#hevy") & Key("sk").between(f"DATE#{since}", f"DATE#{until}~"),
    )
    workouts = [it for it in workouts if "#WORKOUT#" in it.get("sk", "")]
    return [w for w in workouts if any((e.get("notes") or "").strip() for e in (w.get("exercises") or []))]


def _group_head_rows(table, pk, date, wid):
    """{occurrence: row} for one (workout, template) group — legacy rows included."""
    rows = _query_all(
        table,
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(f"DATE#{date}#WORKOUT#{wid}"),
    )
    return tn.dedupe_head_rows(rows)


def _stored_head(table, pk, date, wid, occurrence):
    """The stored head for one exercise-session: occurrence key first, legacy key second."""
    got = (table.get_item(Key={"pk": pk, "sk": tn.head_sk(date, wid, occurrence)}) or {}).get("Item")
    if got is None and int(occurrence) == 0:
        got = (table.get_item(Key={"pk": pk, "sk": tn.legacy_head_sk(date, wid)}) or {}).get("Item")
    return got


def _noted_sessions(w):
    """(exercise, template_id, name, occurrence, note) for every noted block in a workout."""
    exs = w.get("exercises") or []
    out = []
    for ex, occ in zip(exs, tn.occurrence_indices(exs)):
        note = (ex.get("notes") or "").strip()
        if not note:
            continue
        tid, name = tn.normalize_exercise_key(ex)
        out.append((ex, tid, name, occ, note))
    return out


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
        wid = tn.workout_id_of_raw_row(w)
        for _ex, tid, name, occ, note in _noted_sessions(w):
            pk, sk = tn.notes_pk(tid), tn.head_sk(date, wid, occ)
            row = {"date": date, "exercise": name, "template_id": tid, "sk": sk, "occurrence": occ}
            stored = _stored_head(table, pk, date, wid, occ)
            if not stored:
                buckets["absent"].append(row)
                continue
            row["stored_sk"] = stored.get("sk")
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


# ══════════════════════════════════════════════════════════════════════════════
# --migrate — re-key the pre-#3918 collisions onto the occurrence key (box 3)
# ══════════════════════════════════════════════════════════════════════════════
def _candidate_extractions(table, pk, date, wid):
    """Every stored extraction that ever stood for this (workout, template) group: the
    head rows (legacy + occurrence) AND the archived priors. No model, no writes."""
    heads = _query_all(
        table,
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(f"DATE#{date}#WORKOUT#{wid}"),
    )
    archived = _query_all(
        table,
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with(f"{tn.ARCHIVE_PREFIX}DATE#{date}#WORKOUT#{wid}"),
    )
    return [r for r in heads if not str(r.get("sk", "")).endswith("#CORRECTION")], archived


def plan_group_migration(table, date, wid, tid, occs, notes_by_occ):
    """The re-key plan for ONE (workout, template) group. Read-only; returns the plan.

    Each noted occurrence is matched to a stored extraction BY `note_hash` — the head row
    that currently holds it, else the archived prior that does (the displaced note of the
    collision lives there, which is why #3816's archive is what makes this migration
    possible at all). Nothing is re-extracted: an occurrence with no stored extraction is
    reported `unavailable`, because extracting it is model spend and that is box 4.
    """
    pk = tn.notes_pk(tid)
    heads, archived = _candidate_extractions(table, pk, date, wid)
    by_hash = {}
    for r in archived + heads:  # a live head outranks an archived copy of the same text
        h = str(r.get("note_hash") or "")
        if h:
            by_hash[h] = r
    plan = {
        "date": date,
        "workout_id": wid,
        "template_id": tid,
        "noted_occurrences": list(occs),
        "puts": [],
        "deletes": [],
        "already": [],
        "unavailable": [],
    }
    existing = {str(r.get("sk")): str(r.get("note_hash") or "") for r in heads}
    end_state = dict(existing)
    for occ in occs:
        target = tn.head_sk(date, wid, occ)
        want = tn.note_hash(notes_by_occ[occ])
        if existing.get(target) == want:
            plan["already"].append({"sk": target, "occurrence": occ})
            continue
        src = by_hash.get(want)
        if src is None:
            plan["unavailable"].append({"sk": target, "occurrence": occ, "why": "no stored extraction carries this note text"})
            continue
        item = dict(src)
        item["sk"] = target
        item["occurrence"] = int(occ)
        item["migrated_from_sk"] = src.get("sk")
        item["migrated_by"] = "backfill_training_notes --migrate (#3918)"
        item.pop("record_kind", None)  # a promoted archive copy becomes a head again
        item.pop("superseded_head_sk", None)
        plan["puts"].append(item)
        end_state[target] = want
    # The legacy row is retired only once its own content stands at an occurrence key.
    legacy = tn.legacy_head_sk(date, wid)
    if legacy in existing and existing[legacy] in {v for k, v in end_state.items() if k != legacy}:
        plan["deletes"].append(legacy)
        end_state.pop(legacy, None)
    plan["end_state"] = end_state
    plan["distinct_notes"] = len(set(end_state.values()))
    return plan


def assert_distinct_notes(plan):
    """Box 3: after this plan the collision IS two separately addressable notes."""
    n_keys, n_notes = len(plan["end_state"]), plan["distinct_notes"]
    expected = len(plan["noted_occurrences"])
    assert n_keys >= expected and n_notes >= expected, (
        f"{plan['date']} {plan['template_id']}: the re-key does NOT yield {expected} distinct notes "
        f"({n_keys} head key(s), {n_notes} distinct note text(s)) — unavailable: {plan['unavailable']}"
    )


def migrate_collisions(table, dates=COLLISION_DATES, apply=False):
    """Re-key ONLY the known collision workouts onto the occurrence key (#3918 box 3).

    Dry-run by default; `--apply` writes DynamoDB and calls NO model — every record it
    writes already exists, this moves stored extractions onto their own keys.
    """
    plans = []
    for date in dates:
        for w in _noted_workouts(table, date, until=date):
            wid = tn.workout_id_of_raw_row(w)
            exs = w.get("exercises") or []
            notes_by_occ = {occ: note for _ex, _tid, _nm, occ, note in _noted_sessions(w)}
            for tid, occs in tn.noted_occurrences_by_template(exs).items():
                if len(occs) < 2:
                    continue  # not a collision — untouched
                plans.append(plan_group_migration(table, date, wid, tid, occs, notes_by_occ))

    print(f"MIGRATE{'' if apply else ' (dry-run — nothing written)'}: {len(plans)} colliding (workout, template) group(s)\n")
    for p in plans:
        print(f"  {p['date']}  workout {p['workout_id']}  template {p['template_id']}  noted occurrences {p['noted_occurrences']}")
        for it in p["puts"]:
            print(f"    put    {it['sk']}   (from {it['migrated_from_sk']})")
        for sk in p["deletes"]:
            print(f"    delete {sk}   (legacy key; its content now stands at an occurrence key)")
        for a in p["already"]:
            print(f"    ok     {a['sk']} already carries this occurrence")
        for u in p["unavailable"]:
            print(f"    MISS   {u['sk']} — {u['why']}")
        if apply:
            from common.numeric import floats_to_decimal

            pk = tn.notes_pk(p["template_id"])
            for it in p["puts"]:
                table.put_item(Item=floats_to_decimal(it))
            for sk in p["deletes"]:
                table.delete_item(Key={"pk": pk, "sk": sk})
            after = _group_head_rows(table, pk, p["date"], p["workout_id"])
            p["end_state"] = {str(r.get("sk")): str(r.get("note_hash") or "") for r in after.values()}
            p["distinct_notes"] = len(set(p["end_state"].values()))
            print(f"    APPLIED — {len(p['end_state'])} head row(s), {p['distinct_notes']} distinct note(s)")
        assert_distinct_notes(p)
        print()
    print(f"{'APPLIED' if apply else 'DRY-RUN'}: every collision resolves to one head key per noted occurrence.")
    return plans


# ══════════════════════════════════════════════════════════════════════════════
# --value-census — what is IN the un-extracted notes? ($0, read-only)
# ══════════════════════════════════════════════════════════════════════════════
# The question `--apply` cannot answer for itself: is extracting 532 historical notes
# worth real Bedrock spend? This counts and characterises the population WITHOUT a single
# model call, so the decision is made against the corpus rather than a hunch.
CENSUS_KEYWORDS = {
    "pain": ["pain", "hurt", "ache", "twinge", "knee", "shoulder", "back", "elbow"],
    "form": ["form", "cue", "tempo"],
    "progression": ["pr", "best", "heavy"],
    "equipment": ["machine", "bar", "band"],
}
LENGTH_BUCKETS = ((0, 40), (41, 80), (81, 160), (161, 320), (321, 10**9))


def _bucket_label(lo, hi):
    return f"{lo}-{hi}" if hi < 10**9 else f"{lo}+"


def keyword_hits(notes):
    """{class: {"sessions": n, "keywords": {kw: hits}}} over a list of note texts.

    Word-boundary, case-insensitive — "bar" does not score "barbell", and `PR` is counted
    as the word it is. `sessions` counts NOTES with at least one hit in the class, which
    is the number that matters (a note saying "knee" four times is one signal).
    """
    out = {}
    for cls, words in CENSUS_KEYWORDS.items():
        pats = {w: re.compile(rf"\b{re.escape(w)}\b", re.IGNORECASE) for w in words}
        per_kw: Counter = Counter()
        sessions = 0
        for note in notes:
            hit = False
            for w, pat in pats.items():
                n = len(pat.findall(note or ""))
                if n:
                    per_kw[w] += n
                    hit = True
            sessions += 1 if hit else 0
        out[cls] = {"sessions": sessions, "keywords": dict(per_kw.most_common())}
    return out


def length_distribution(notes):
    """min/median/mean/max + the bucket histogram of note lengths, in characters."""
    lens = sorted(len(n or "") for n in notes)
    buckets = {_bucket_label(lo, hi): 0 for lo, hi in LENGTH_BUCKETS}
    for ln in lens:
        for lo, hi in LENGTH_BUCKETS:
            if lo <= ln <= hi:
                buckets[_bucket_label(lo, hi)] += 1
                break
    return {
        "min": lens[0] if lens else 0,
        "median": int(statistics.median(lens)) if lens else 0,
        "mean": round(sum(lens) / len(lens), 1) if lens else 0.0,
        "max": lens[-1] if lens else 0,
        "buckets": buckets,
    }


def value_census(table, since="2000-01-01", samples=10):
    """READ-ONLY, $0: the un-extracted noted exercise-sessions, characterised.

    "Un-extracted" is decided the way `training_notes_health` decides `missing`: per
    (workout, template) group the stored occurrence rows are compared against the noted
    occurrences, and a single legacy row is allowed to stand for a single noted block.
    """
    unextracted = []
    noted_total = 0
    for w in _noted_workouts(table, since):
        date = w.get("date")
        wid = tn.workout_id_of_raw_row(w)
        exs = w.get("exercises") or []
        notes_by_occ, names_by_occ = {}, {}
        for _ex, tid, name, occ, note in _noted_sessions(w):
            notes_by_occ[(tid, occ)] = note
            names_by_occ[(tid, occ)] = name
        for tid, occs in tn.noted_occurrences_by_template(exs).items():
            noted_total += len(occs)
            found = _group_head_rows(table, tn.notes_pk(tid), date, wid)
            if len(occs) == 1 and len(found) == 1:
                continue  # the legacy scheme matching itself — extracted
            for occ in occs:
                if occ in found:
                    continue
                unextracted.append(
                    {
                        "date": date,
                        "workout_id": wid,
                        "template_id": tid,
                        "exercise": names_by_occ.get((tid, occ), ""),
                        "occurrence": occ,
                        "note": notes_by_occ.get((tid, occ), ""),
                    }
                )

    notes = [r["note"] for r in unextracted]
    ordered = sorted(unextracted, key=lambda r: str(r["date"]))
    stride = max(1, len(ordered) // samples) if ordered else 1
    return {
        "noted_exercise_sessions_total": noted_total,
        "unextracted": len(unextracted),
        "measured_reference": MEASURED_UNEXTRACTED,
        "by_year": dict(sorted(Counter(str(r["date"])[:4] for r in unextracted).items())),
        "top_exercises": Counter(r["exercise"] or r["template_id"] for r in unextracted).most_common(15),
        "note_length": length_distribution(notes),
        "keyword_classes": keyword_hits(notes),
        "samples": [
            {"date": r["date"], "exercise": r["exercise"], "note_head": (r["note"] or "")[:100]} for r in ordered[::stride][:samples]
        ],
    }


def print_value_census(c):
    print("VALUE CENSUS — un-extracted noted exercise-sessions (READ-ONLY, $0: no model call)\n")
    print(f"n = {c['unextracted']} un-extracted of {c['noted_exercise_sessions_total']} noted exercise-sessions")
    print(f"    (the measured reference on 2026-09-19 was {c['measured_reference']})\n")
    print("BY YEAR")
    for year, n in c["by_year"].items():
        print(f"    {year}: {n}")
    print("\nTOP 15 EXERCISES")
    for name, n in c["top_exercises"]:
        print(f"    {n:4d}  {name}")
    ln = c["note_length"]
    print(f"\nNOTE LENGTH (chars)  min {ln['min']} · median {ln['median']} · mean {ln['mean']} · max {ln['max']}")
    for bucket, n in ln["buckets"].items():
        print(f"    {bucket:>10}: {n}")
    print("\nKEYWORD CLASSES (word-boundary, case-insensitive; `sessions` = notes with >=1 hit)")
    for cls, d in c["keyword_classes"].items():
        kws = ", ".join(f"{k} x{v}" for k, v in d["keywords"].items()) or "-"
        print(f"    {cls:<12} sessions {d['sessions']:4d}   {kws}")
    print(f"\nSAMPLES ({len(c['samples'])})")
    for s in c["samples"]:
        print(f"    {s['date']}  {s['exercise']}: {s['note_head']}")
    print(
        "\nNothing was written and no model was called. Extracting this population is "
        "`--apply` (real Bedrock spend over historical data) and is an owner decision."
    )


def _extract_note_from_thread_text(text):
    """The verbatim (<=160-char) note `elevate_pain` embedded in its own thread text —
    the SAME truncation the write applied, never re-truncated here."""
    m = re.search(r'note on .*?: "(.*)"\. Surface', text or "", re.S)
    return m.group(1) if m else ""


def _pain_hit_pre_3972(note_text):
    """Re-derive the ORIGINAL (pre-#3972) lexicon verdict — no grip-work strip — so the
    census can show exactly why a row over-fired, against what `tn.pain_lexicon_hit`
    (post-fix) says today."""
    t = (note_text or "").lower()
    if any(w in t for w in tn._PAIN_WORDS):
        return True
    return any(r in t for r in tn._JOINT_REGIONS) and any(s in t for s in tn._JOINT_SENSATION)


def pain_burst_census(table, since, until):
    """READ-ONLY (#3972): every `#pain` coach_thread row written in [since, until) — the
    2026-09-19T21:08-09Z burst that mis-fired 14 rows off 2022 Hevy notes. No write, no
    delete: a Query plus a re-run of the pure lexicon function against each row's own
    stored note text, so a human can post keep/dismiss counts on the issue."""
    rows = _query_all(
        table,
        KeyConditionExpression=Key("pk").eq("USER#matthew")
        & Key("sk").between(f"SOURCE#coach_thread#training_coach#{since}", f"SOURCE#coach_thread#training_coach#{until}~"),
    )
    rows = [r for r in rows if str(r.get("sk", "")).endswith("#pain")]
    out = []
    for r in sorted(rows, key=lambda row: row.get("sk", "")):
        note = _extract_note_from_thread_text(r.get("text", ""))
        post_fix_hit = tn.pain_lexicon_hit(note)
        out.append(
            {
                "sk": r.get("sk"),
                "created_at": r.get("created_at"),
                "note_date": r.get("date"),
                "exercise": r.get("exercise"),
                "note_text": note,
                "pain_lexicon_hit_pre_3972": _pain_hit_pre_3972(note),
                "pain_lexicon_hit_post_3972": post_fix_hit,
                "disposition": "keep (genuine pain)" if post_fix_hit else "dismiss (lexicon false positive — #3972 grip-work control)",
            }
        )
    return out


def print_pain_burst_census(rows):
    print(f"PAIN-BURST CENSUS — {len(rows)} `#pain` coach_thread row(s) (READ-ONLY: no write, no delete)\n")
    keep = [r for r in rows if r["pain_lexicon_hit_post_3972"]]
    dismiss = [r for r in rows if not r["pain_lexicon_hit_post_3972"]]
    for r in rows:
        print(f"  {r['sk']}")
        print(f"      note date: {r['note_date']}   exercise: {r['exercise']}   created_at: {r['created_at']}")
        print(f'      note: "{r["note_text"]}"')
        print(f"      lexicon hit pre-#3972: {r['pain_lexicon_hit_pre_3972']}   post-#3972: {r['pain_lexicon_hit_post_3972']}")
        print(f"      disposition: {r['disposition']}\n")
    print(f"KEEP (genuine pain, post-fix): {len(keep)}")
    print(f"DISMISS (lexicon false positive, post-fix): {len(dismiss)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2000-01-01")
    ap.add_argument("--until", default="9999", help="upper bound for --pain-burst-census (exclusive-ish, sk-prefix compare)")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--report-overwrites",
        action="store_true",
        help="READ-ONLY: list the stored records a re-run would version, and write nothing",
    )
    ap.add_argument(
        "--value-census",
        action="store_true",
        help="READ-ONLY, $0: count and characterise the un-extracted noted exercise-sessions",
    )
    ap.add_argument(
        "--pain-burst-census",
        action="store_true",
        help="READ-ONLY (#3972): list #pain coach_thread rows in [--since, --until) with source note + lexicon-hit explanation",
    )
    ap.add_argument(
        "--migrate",
        action="store_true",
        help="re-key the pre-#3918 collision workouts onto DATE#...#WORKOUT#<id>#<occurrence> (dry-run unless --apply)",
    )
    args = ap.parse_args()
    if args.report_overwrites and args.apply:
        ap.error("--report-overwrites is read-only; it cannot be combined with --apply")
    if args.value_census and args.apply:
        ap.error("--value-census is read-only; it cannot be combined with --apply")
    if args.pain_burst_census and args.apply:
        ap.error("--pain-burst-census is read-only; it cannot be combined with --apply")
    if args.migrate and (args.report_overwrites or args.value_census or args.pain_burst_census):
        ap.error("--migrate is its own mode; run it on its own")

    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)

    if args.report_overwrites:
        report_overwrites(table, args.since)
        return
    if args.value_census:
        print_value_census(value_census(table, args.since))
        return
    if args.pain_burst_census:
        print_pain_burst_census(pain_burst_census(table, args.since, args.until))
        return
    if args.migrate:
        migrate_collisions(table, apply=args.apply)
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
