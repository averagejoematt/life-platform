#!/usr/bin/env python3
"""write_exercise_library_overlay.py — the OWNER-PRIVATE N=1 half of the exercise library (#5769).

DRY-RUN BY DEFAULT. It prints COUNTS ONLY (no loads, no bodyweight, no thresholds, no note text) and writes
nothing. `--out <file>` writes the overlay JSON to a local file (use the gitignored
`config/exercise_library.private.local.json`, or a scratch path); `--apply` PUTs it to
`s3://matthew-life-platform/config/coaching/exercise_library.private.json` — the #3043 owner-private prefix:
`deploy/bucket_policy.json` grants public GetObject only on `site/*` and named `generated/*` keys, so nothing
under `config/` is anonymously readable, and `config/*` is delete-protected. Never `generated/` or `site/`.

WHAT IT HOLDS (keyed by Hevy template id, joined to the public library at selection time by
`training.exercise_library.n1_view`):

  * `per_template[tid].best_set_by_band` — the best logged set (Epley e1RM ranking; warm-ups excluded; the
    #5373 per-hand / total-carried unit convention applied, as `exercise_history` does) per 10-lb bodyweight band
    (`training.band_reference.band_key`), the bodyweight being the nearest Withings weigh-in within
    `exercise_history.BODYWEIGHT_TOLERANCE_DAYS`. A set with no weigh-in near it is counted, never banded.
  * `per_template[tid].note_signals` — coded tag counts from his Hevy exercise notes
    (`training.exercise_library.note_signal_tags`): pain / joint discomfort + region, sentiment, swaps, form checks,
    equipment fit, availability. Never the note text. A note repeated verbatim in >= 3 workouts is a program
    template, not his voice, and is skipped.
  * `availability_learned` — per equipment id at `home_gym`: `unavailable` from a "gym doesn't have X" note
    (owner-confirmable), `contention` / `question` / `load_ceiling` counts. Contention never marks anything
    unavailable.
  * `gates` — one row per public gate id: measured input, comparator, value, chain prerequisites. Bodyweight
    thresholds the owner has not set stay `null` (=> the gate is locked, and
    `scripts/check_library_gates_private.py` fails until he sets them). A value already in the existing overlay
    is preserved — a re-run never wipes an owner-set threshold.
  * `not_for_you_now_detail` — the coded evidence behind each public `not_for_you_now`.
  * `technique_confirmations` — library movement id -> {confirmed_on, source}: the owner's technique confirmations, which
    the `owner_confirmation` gate reads as met (#5772). Seeded from `OWNER_TECHNIQUE_CONFIRMATIONS`; one already in the
    existing overlay is preserved, so a re-run never drops one. Harder skill steps still follow their chain gates.

Read-only inputs: the Hevy partition (the same Query the library builder uses), the Withings partition, the
existing overlay (S3 GetObject), `config/exercise_library.json`, `config/training_charter.json`.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(REPO_ROOT, "lambdas"), REPO_ROOT, os.path.dirname(os.path.abspath(__file__))]

from training import exercise_library as xl  # noqa: E402

OVERLAY_VERSION = "0.2.0"  # 0.2.0 (#5773): pain_flag tags from training_notes_pain.pain_class; `pain_source` stamped
_WORKOUT_SK = re.compile(r"^DATE#(\d{4}-\d{2}-\d{2})#WORKOUT#(.+)$")
_DELETE_SK = re.compile(r"^DELETE#WORKOUT#(.+)$")
LEGACY_TOMBSTONE = "legacy_daily_aggregate_superseded_by_per_workout"
PROGRAM_NOTE_REPEATS = 3

# Owner ruling 2026-11-11 (on PR #5824 / #5772): he CONFIRMS his clean technique — the clean he logs now (`clean`, the
# Hevy "Clean" template) and the hang power clean (`hang_power_clean`, logged under Hevy's "Hang Clean"). Only the
# owner_confirmation gate reads this; the clean's bodyweight and chain gates still apply.
OWNER_TECHNIQUE_CONFIRMATIONS: dict[str, dict[str, str]] = {
    "clean": {"confirmed_on": "2026-11-11", "source": "owner ruling 2026-11-11"},
    "hang_power_clean": {"confirmed_on": "2026-11-11", "source": "owner ruling 2026-11-11"},
}


def technique_confirmations(lib: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, dict[str, str]]:
    """Existing confirmations first (never dropped), then the seeded owner rulings; ids must be library movements."""
    known = xl.movements(lib)
    prior = (existing or {}).get("technique_confirmations") or {}
    out = {k: v for k, v in prior.items() if k in known and isinstance(v, dict)}
    for k, v in OWNER_TECHNIQUE_CONFIRMATIONS.items():
        if k in known:
            out.setdefault(k, dict(v))
    return dict(sorted(out.items()))


def _f(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def live_workouts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same exclusion the library builder applies: legacy aggregates, non-workout keys, unconsumed DELETE# markers."""
    deleted = {m.group(1) for r in rows if (m := _DELETE_SK.match(str(r.get("sk") or "")))}
    out = []
    for r in rows:
        m = _WORKOUT_SK.match(str(r.get("sk") or ""))
        if not m or r.get("tombstoned_reason") == LEGACY_TOMBSTONE:
            continue
        if m.group(2) in deleted or str(r.get("source_workout_id") or "") in deleted:
            continue
        out.append({**r, "_day": m.group(1)})
    return out


def best_sets_by_band(workouts: list[dict[str, Any]], weight_index: dict[str, float]) -> tuple[dict[str, Any], Counter]:
    """Pure. tid -> band -> best set {weight_kg, reps, date}; plus a counter of unbanded sets."""
    from training import logging_conventions
    from training.band_reference import band_key
    from training.exercise_history import nearest_bodyweight

    best: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    stats: Counter = Counter()
    for w in workouts:
        day = w["_day"]
        bw = nearest_bodyweight(day, weight_index)
        for ex in w.get("exercises") or []:
            tid = str(ex.get("template_id") or "").strip().upper()
            if not tid:
                continue
            sets_raw = ex.get("sets") or []
            scale = logging_conventions.current_unit_scale(ex.get("name"), tid, sets_raw, day=day)
            for s in sets_raw:
                if str(s.get("type") or s.get("set_type") or "normal").lower() == "warmup":
                    continue
                kg, reps = _f(s.get("weight_kg")) * scale, int(_f(s.get("reps")))
                if kg <= 0 or reps <= 0:
                    continue
                if bw is None:
                    stats["sets_without_weighin"] += 1
                    continue
                band = band_key(bw)
                e1rm = kg * (1 + reps / 30.0)
                cur = best[tid].get(band)
                if cur is None or e1rm > cur["_e1rm"] or (e1rm == cur["_e1rm"] and day < cur["date"]):
                    best[tid][band] = {"weight_kg": round(kg, 2), "reps": reps, "date": day, "_e1rm": e1rm}
                stats["sets_banded"] += 1
    out = {tid: {b: {k: v for k, v in row.items() if k != "_e1rm"} for b, row in sorted(bands.items())} for tid, bands in best.items()}
    return out, stats


def note_signals(workouts: list[dict[str, Any]]) -> tuple[dict[str, dict[str, int]], dict[str, Any], dict[str, list[str]], Counter]:
    """Pure. -> (tid -> tag counts, availability_learned, tid -> pain/discomfort dates, stats)."""
    texts = Counter(" ".join(str(ex.get("notes") or "").split()) for w in workouts for ex in w.get("exercises") or [])
    per: dict[str, Counter] = defaultdict(Counter)
    flag_dates: dict[str, list[str]] = defaultdict(list)
    avail: dict[str, dict[str, Any]] = {}
    stats: Counter = Counter()
    for w in workouts:
        for ex in w.get("exercises") or []:
            note = " ".join(str(ex.get("notes") or "").split())
            if not note:
                continue
            if texts[note] >= PROGRAM_NOTE_REPEATS:
                stats["program_template_notes_skipped"] += 1
                continue
            stats["notes_read"] += 1
            tid = str(ex.get("template_id") or "").strip().upper()
            tags = xl.note_signal_tags(note)
            for t in tags:
                per[tid][t] += 1
                if t.startswith("availability:"):
                    _, sig, eid = t.split(":", 2)
                    row = avail.setdefault(eid, {xl.LOCATION_ID: {"state": None, "signals": Counter(), "last_signal": None}})[
                        xl.LOCATION_ID
                    ]
                    row["signals"][sig] += 1
                    row["last_signal"] = max(row["last_signal"] or "", w["_day"])
                    if sig == "unavailable":
                        row["state"] = "unavailable"
                        row["source"] = f"owner note {w['_day']}"
                        row["owner_confirmable"] = True
            if {"pain_flag", "joint_discomfort"} & set(tags) and tid:
                flag_dates[tid].append(w["_day"])
    learned = {}
    for eid, rows in sorted(avail.items()):
        r = rows[xl.LOCATION_ID]
        learned[eid] = {xl.LOCATION_ID: {**{k: v for k, v in r.items() if k != "signals"}, "signals": dict(sorted(r["signals"].items()))}}
    return {k: dict(sorted(v.items())) for k, v in per.items()}, learned, {k: sorted(v) for k, v in flag_dates.items()}, stats


def _charter_value(charter: dict[str, Any], path: str) -> Any:
    cur: Any = charter
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def gate_rows(lib: dict[str, Any], charter: dict[str, Any], existing: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """One private row per public gate. An owner-set value in the existing overlay always wins."""
    prior = (existing or {}).get("gates") or {}
    out: dict[str, dict[str, Any]] = {}
    for gid, g in (lib.get("gates") or {}).items():
        kind = g["kind"]
        row: dict[str, Any] = {
            "kind": kind,
            "measured_input": g.get("measured_input"),
            "chain_prerequisites": list(g.get("chain_prerequisites") or []),
        }
        if kind == "bodyweight_threshold":
            thr = g.get("threshold") or {}
            row.update({"comparator": "<=", "unit": "lb"})
            if thr.get("charter_ref"):
                row.update({"value": _charter_value(charter, thr["charter_ref"]), "source": f"charter:{thr['charter_ref']}"})
            else:
                row.update({"value": None, "source": "owner_to_set"})
        elif kind in ("chain_prerequisite", "performance_threshold"):
            row.update({"comparator": "meets_all", "value": g.get("standard"), "source": "public gate standard (#5769, platform-proposed)"})
        elif kind == "pain_flag_exclusion":
            row.update({"comparator": "<=", "value": {"pain_flags_max": 0, "window_days": 28}, "source": "public gate (#5769)"})
        elif kind == "equipment_available":
            row.update({"comparator": "all_equal", "value": "available", "source": "owner ruling 2026-11-11"})
        elif kind == "clinical_cue":
            row.update({"comparator": "cue_only", "value": g.get("cue"), "source": "owner direction 2026-11-11"})
        elif kind == "owner_confirmation":
            row.update({"comparator": "==", "value": True, "source": "public gate (#5769)"})
        elif kind == "charter_gate":
            row.update({"comparator": "charter", "value": g.get("charter_ref"), "source": "training charter"})
        old = prior.get(gid) or {}
        if (
            old.get("value") is not None
            and old.get("source") not in (None, "owner_to_set")
            and kind == "bodyweight_threshold"
            and not (g.get("threshold") or {}).get("charter_ref")
        ):
            row["value"], row["source"] = old["value"], old["source"]
        out[gid] = row
    return out


def build_overlay(lib, charter, workouts, weight_index, existing) -> tuple[dict[str, Any], dict[str, Any]]:
    best, bstats = best_sets_by_band(workouts, weight_index)
    signals, learned, flags, nstats = note_signals(workouts)
    per: dict[str, dict[str, Any]] = {}
    for tid in sorted(set(best) | set(signals)):
        per[tid] = {"best_set_by_band": best.get(tid) or {}, "note_signals": signals.get(tid) or {}}
        if flags.get(tid):
            per[tid]["pain_or_discomfort_dates"] = flags[tid]
    nfy = {}
    for key, e in xl.movements(lib).items():
        if e.get("not_for_you_now"):
            tid = str(e.get("template_id") or "").upper()
            nfy[key] = {"template_id": tid, "evidence_dates": flags.get(tid, []), "evidence_tags": sorted(signals.get(tid, {}))}
    gates = gate_rows(lib, charter, existing)
    overlay = {
        "_comment": "OWNER-PRIVATE. Never commit, never publish. The N=1 half of config/exercise_library.json (#5769).",
        "version": OVERLAY_VERSION,
        "pain_source": xl.PAIN_SOURCE_ID,
        "library_version": lib.get("version"),
        "location_id": xl.LOCATION_ID,
        "per_template": per,
        "availability_learned": learned,
        "gates": gates,
        "gate_thresholds": {gid: row for gid, row in gates.items() if row["kind"] == "bodyweight_threshold"},
        "not_for_you_now_detail": nfy,
        "technique_confirmations": technique_confirmations(lib, existing),
    }
    summary = {
        "workouts_read": len(workouts),
        "weighins_read": len(weight_index),
        "templates_with_banded_best_sets": sum(1 for v in best.values() if v),
        "band_cells": sum(len(v) for v in best.values()),
        **dict(bstats),
        **dict(nstats),
        "templates_with_note_signals": len(signals),
        "tag_counts": dict(sorted(Counter(t for v in signals.values() for t in v for _ in range(v[t])).items())),
        "equipment_learned_unavailable": sorted(k for k, v in learned.items() if v[xl.LOCATION_ID].get("state") == "unavailable"),
        "equipment_with_contention": sorted(k for k, v in learned.items() if v[xl.LOCATION_ID]["signals"].get("contention")),
        "gates": len(gates),
        "gates_with_null_value": sorted(g for g, r in gates.items() if r.get("value") is None),
        "not_for_you_now_detail": len(nfy),
        "technique_confirmations": sorted(overlay["technique_confirmations"]),
    }
    return overlay, summary


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help=f"PUT to s3://<bucket>/{xl.PRIVATE_S3_KEY} (owner/driver only)")
    ap.add_argument("--out", help="write the overlay JSON to this local path (never inside the repo except the gitignored local file)")
    args = ap.parse_args(argv)

    from build_movement_catalog import fetch_workout_rows
    from training.exercise_history import load_bodyweight_index

    lib = xl.load_library()
    with open(os.path.join(REPO_ROOT, "config", "training_charter.json"), encoding="utf-8") as f:
        charter = json.load(f)
    existing = xl.load_private_overlay()
    workouts = live_workouts(fetch_workout_rows())
    overlay, summary = build_overlay(lib, charter, workouts, load_bodyweight_index(), existing)
    print(json.dumps(summary, indent=2))  # counts and ids only — never a value
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(overlay, f, indent=1, sort_keys=True)
        print(f"wrote overlay to {args.out}")
    if not args.apply:
        print("dry-run — nothing written to S3 (pass --apply)")
        return 0
    import boto3

    boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2")).put_object(
        Bucket=os.environ.get("S3_BUCKET", "matthew-life-platform"),
        Key=xl.PRIVATE_S3_KEY,
        Body=json.dumps(overlay, sort_keys=True).encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="AES256",
    )
    print(f"applied: s3://…/{xl.PRIVATE_S3_KEY}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
