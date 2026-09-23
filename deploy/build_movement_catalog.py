#!/usr/bin/env python3
"""build_movement_catalog.py — build `config/movement_catalog.json` from the whole Hevy history (#4108).

WHY

The catalog is the routine generator's entire vocabulary, and until #4108 it held the 26
movements hand-written on 2026-05-31 (ADR-066). The owner has logged 538 distinct exercises in
Hevy since 2021-04-12 (136 of them in ≥ 5 workouts); Squat (Barbell) alone appears in 85
workouts and was not catalogued, so every generated plan chose from ~5 % of what he actually
trains. Owner, 2026-09-23: "update the catalog to pull every worked exercise in Hevy ever as a
starting point".

WHAT IT DOES

  1. Reads every per-workout Hevy row (`pk=USER#matthew#SOURCE#hevy`, `sk=DATE#…#WORKOUT#…`),
     BOTH phases (pilot + experiment — no phase filter), skipping the legacy daily aggregates
     (`tombstoned_reason=legacy_daily_aggregate_superseded_by_per_workout`). Read-only query.
  2. Keys each logged exercise by `mcp.strength_helpers.exercise_identity()` through the ONE
     alias table (`config/hevy_template_aliases.json`, resolved by
     `health.adherence_calc._resolve_alias_canonical_tids`) — a confirmed alias id folds into its
     canonical id and is never catalogued twice. Counts sessions (distinct workouts), first, last.
  3. Enriches every id from Hevy's own exercise-template metadata — READ-ONLY GETs through the
     existing client (`training.hevy_write_client.list_templates` walked by
     `training.hevy_template_index.walk_templates`, ~9 pages at the client's 1 req/s throttle;
     `get_template` only for an id the walk did not return). No Hevy write of any kind.
  4. Merges, by provenance (`training/movement_catalog.py` documents all three):
       * hand-curated entries (and any `hevy_history` entry a human has set `reviewed: true`)
         keep ALL their fields and gain `reviewed: true` + the measured `sessions` /
         `first_done` / `last_done`;
       * `coach_added` entries (never-trained exercises added on purpose) keep every written
         field, get each ABSENT field from Hevy metadata, the measured fields, and
         `reviewed: false` unless written;
       * every other logged id becomes a generated `provenance: hevy_history`,
         `reviewed: false` entry, rebuilt from scratch on each run.
     Every entry gets `anchor_family` from `training.movement_catalog.anchor_family`.

THE DERIVATION RULES (each stated with its reason)

  * `skill_tier` from Hevy's `equipment` — see `EQUIPMENT_SKILL_TIER`. 382 of 538 titles carry no
    equipment word, so the title cannot carry this; Hevy's own field can.
  * `primary_muscle` / `secondary_muscles` from Hevy's muscle groups through
    `training.muscle_volume.HEVY_MUSCLE_GROUP` — the one table (column 1 is the planner key the
    generator matches on, column 0 the `muscle_volume.MUSCLES` label written as `volume_muscle`).
  * `joint_friendly_score` = `UNREVIEWED_JOINT_FRIENDLY_SCORE` for every generated entry.
  * `default_rep_range` by tier (`TIER_REP_RANGE`) for rep-based types only.
  * Generator eligibility is NOT written into the file — it is a rule over these fields, owned
    by `training.movement_catalog.generator_eligible` (reviewed OR a prescribable rep range, and
    always under the skill ceiling — owner ruling C: no frequency gate), so the file and the
    rule cannot disagree.

DETERMINISTIC: no wall clock in the output; entries are ordered curated-first (in their
existing order) then by sessions desc, key asc. The same history + template metadata produce
byte-identical output. `--save-inputs` / `--inputs` capture and replay those inputs offline.

    python3 deploy/build_movement_catalog.py                 # dry-run: summary, writes nothing
    python3 deploy/build_movement_catalog.py --write         # overwrite config/movement_catalog.json
    python3 deploy/build_movement_catalog.py --save-inputs /path/in.json   # snapshot the live reads
    python3 deploy/build_movement_catalog.py --inputs /path/in.json --write # rebuild offline

The runtime reads the S3 twin (`s3://matthew-life-platform/config/movement_catalog.json` — the
file is NOT staged into the Lambda bundle); a merged change reaches S3 through site-deploy's
`config_twin_sync.py --apply` step (`config/**` is in its path filter). This script never
writes S3.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Any, Iterable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(REPO_ROOT, "lambdas"), REPO_ROOT]

from training.movement_catalog import (  # noqa: E402
    PROVENANCE_COACH,
    PROVENANCE_CURATED,
    PROVENANCE_HISTORY,
    REP_BASED_TYPES,
    anchor_family,
)
from training.muscle_volume import HEVY_MUSCLE_GROUP  # noqa: E402
from training.template_muscle_overrides import is_retired_template  # noqa: E402

CATALOG_PATH = os.path.join(REPO_ROOT, "config", "movement_catalog.json")
ALIASES_PATH = os.path.join(REPO_ROOT, "config", "hevy_template_aliases.json")
TABLE_NAME = "life-platform"
HEVY_PK = "USER#matthew#SOURCE#hevy"
LEGACY_TOMBSTONE = "legacy_daily_aggregate_superseded_by_per_workout"
GENERATED_BY = "deploy/build_movement_catalog.py"

#: Hevy `equipment` -> skill tier. The issue's mapping (#4108), and why:
#:   1 — machine, resistance band, bodyweight ("none"): the path of the load is fixed or the load
#:       is the body; the lowest technical demand and the lowest cost of a bad rep.
#:   2 — dumbbell, kettlebell, cable (a Hevy "machine" whose title names a cable — see
#:       `_skill_tier`), plate, suspension, "other": free or semi-free load the lifter must
#:       stabilise; "other" (box jump, farmers walk, bench dip in his history) is unknown kit and
#:       sits in the middle rather than claiming either end.
#:   3 — barbell (and the Smith machine, by title): the highest-skill loaded patterns.
#: An id whose metadata Hevy no longer serves has no equipment → tier 3 (never under-state an
#: unknown's demand); such an entry has no rep range, so it is catalogued but never auto-picked.
EQUIPMENT_SKILL_TIER: dict[str, int] = {
    "machine": 1,
    "resistance_band": 1,
    "none": 1,
    "dumbbell": 2,
    "kettlebell": 2,
    "plate": 2,
    "suspension": 2,
    "other": 2,
    "barbell": 3,
}
UNKNOWN_EQUIPMENT_TIER = 3

#: Every generated (unreviewed) entry's joint_friendly_score. 1 = below every curated entry
#: scored 2 or 3, so the muscle selector (which sorts by joint_friendly_score desc) keeps the
#: hand-reviewed pool first until a human reviews the new entry and scores it.
UNREVIEWED_JOINT_FRIENDLY_SCORE = 1

#: Default rep range for a generated rep-based entry, by tier — the curated catalog's own
#: pattern (machines 10–15, dumbbell/cable 8–12, the barbell bench 5–8).
TIER_REP_RANGE: dict[int, dict[str, int]] = {1: {"start": 10, "end": 15}, 2: {"start": 8, "end": 12}, 3: {"start": 5, "end": 8}}
_WORKOUT_SK = re.compile(r"^DATE#(\d{4}-\d{2}-\d{2})#WORKOUT#")

CATALOG_COMMENT = (
    "Internal movement vocabulary. Maps a stable internal key -> Hevy exercise_template_id. Tags every movement with primary "
    "muscle (the config/training_landmarks.json key the generator matches on), secondary muscles, skill_tier "
    "(1=machine/band/bodyweight, 2=dumbbell/cable/kettlebell, 3=barbell/smith) and joint_friendly_score (3=highest, 0=lowest). "
    "Consumed by routine_generator.py for selection + hevy_template_cache.py for resolution. Entries with `reviewed: true` "
    "are hand-curated and are preserved verbatim by the builder; `provenance: hevy_history` entries are GENERATED from the "
    "owner's whole Hevy history by deploy/build_movement_catalog.py (#4108) — review one by setting `reviewed: true` and "
    "editing its fields, never by hand-adding a generated-shaped entry. Which entries the generator may auto-program is "
    "training/movement_catalog.generator_eligible (reviewed OR a default_rep_range, under the skill ceiling — no frequency "
    "gate). `coach_added` entries are never-trained exercises added on purpose (see training/movement_catalog.py)."
)


# ── inputs ──────────────────────────────────────────────────────────────────────


def load_alias_map(catalog: dict[str, Any]) -> dict[str, str]:
    """alias id -> canonical id (upper), through adherence_calc's own resolver — the ONE alias table."""
    from health.adherence_calc import _resolve_alias_canonical_tids

    with open(ALIASES_PATH, encoding="utf-8") as f:
        aliases = json.load(f).get("aliases", {})
    resolved = _resolve_alias_canonical_tids(catalog, {}, aliases)
    return {str(a).strip().upper(): str(c).strip().upper() for a, c in resolved.items() if a and c}


def fetch_workout_rows() -> list[dict[str, Any]]:
    """Every row under the Hevy partition (read-only Query, paged)."""
    import boto3
    from boto3.dynamodb.conditions import Key

    table = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(TABLE_NAME)
    kw: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(HEVY_PK)}
    items: list[dict[str, Any]] = []
    while True:
        resp = table.query(**kw)
        items.extend(resp.get("Items") or [])
        if "LastEvaluatedKey" not in resp:
            return items
        kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def summarize_history(rows: Iterable[dict[str, Any]], alias_map: dict[str, str]) -> dict[str, Any]:
    """Pure. Per-workout rows -> {workouts, first, last, templates: {identity: {sessions, first_done, last_done, names}}}.

    A session is a distinct workout that logged the exercise at least once. Legacy daily
    aggregates and any non-workout sk are skipped; a phase is never filtered.
    """
    from mcp.strength_helpers import exercise_identity

    templates: dict[str, dict[str, Any]] = {}
    dates: list[str] = []
    untagged = 0
    for row in rows:
        m = _WORKOUT_SK.match(str(row.get("sk") or ""))
        if not m or row.get("tombstoned_reason") == LEGACY_TOMBSTONE:
            continue
        day = m.group(1)
        dates.append(day)
        seen: set[str] = set()
        for ex in row.get("exercises") or []:
            ident = exercise_identity(ex.get("template_id"), ex.get("name"), alias_map)
            if ident.startswith("untagged:"):
                untagged += 1
                continue
            rec = templates.setdefault(ident, {"sessions": 0, "first_done": day, "last_done": day, "names": Counter()})
            rec["names"][str(ex.get("name") or "").strip()] += 1
            if ident in seen:
                continue
            seen.add(ident)
            rec["sessions"] += 1
            rec["first_done"] = min(rec["first_done"], day)
            rec["last_done"] = max(rec["last_done"], day)
    return {
        "workouts": len(dates),
        "first": min(dates) if dates else None,
        "last": max(dates) if dates else None,
        "untagged_exercises": untagged,
        "templates": {
            k: {"sessions": v["sessions"], "first_done": v["first_done"], "last_done": v["last_done"], "names": dict(v["names"])}
            for k, v in sorted(templates.items())
        },
    }


def fetch_template_metadata(ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """Hevy template metadata keyed by UPPER id — the account's full list, plus a GET per straggler.

    Read-only: `list_templates` / `get_template` are both GETs. An id Hevy no longer serves
    (a deleted custom exercise) is simply absent from the result.
    """
    import urllib.error

    from training import hevy_write_client as hevy
    from training.hevy_template_index import walk_templates

    out = {str(t["id"]).upper(): t for t in walk_templates(hevy.list_templates) if t.get("id")}
    for tid in sorted(set(ids) - set(out)):
        try:
            t = hevy.get_template(tid)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            raise
        t = t.get("exercise_template") or t
        if t.get("id"):
            out[str(t["id"]).upper()] = t
    return out


# ── derivation ─────────────────────────────────────────────────────────────────


def _skill_tier(equipment: str | None, title: str) -> tuple[int, str]:
    """(tier, source) from Hevy equipment, refined by the two kits Hevy files under another value."""
    tl = title.lower()
    if re.search(r"\bsmith\b", tl):
        return 3, "title:smith"
    if equipment == "machine" and re.search(r"\bcable\b", tl):
        return 2, "title:cable"  # Hevy files cable exercises under "machine"; the issue's mapping puts cable at 2
    if equipment in EQUIPMENT_SKILL_TIER:
        return EQUIPMENT_SKILL_TIER[equipment], f"hevy_equipment:{equipment}"
    return UNKNOWN_EQUIPMENT_TIER, "hevy_equipment:unknown"


def _planner_muscle(group: str | None) -> str:
    return HEVY_MUSCLE_GROUP.get(str(group or "other"), (None, "other"))[1]


def _slug(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_") or "exercise"


def enrichment(tid: str, meta: dict[str, Any] | None, fallback_title: str) -> dict[str, Any]:
    """Pure. The fields Hevy's template metadata determines for one id (history AND coach_added entries)."""
    title = str((meta or {}).get("title") or fallback_title).strip()
    entry: dict[str, Any] = {"title": title, "hevy_template_id_hint": str((meta or {}).get("id") or tid)}
    if meta is None:
        tier, source = UNKNOWN_EQUIPMENT_TIER, "hevy_metadata:unavailable"
        entry |= {"primary_muscle": "other", "secondary_muscles": [], "volume_muscle": None, "hevy_metadata": "unavailable"}
    else:
        tier, source = _skill_tier(meta.get("equipment"), title)
        group = meta.get("primary_muscle_group")
        primary = _planner_muscle(group)
        secondary: list[str] = []
        for g in meta.get("secondary_muscle_groups") or []:
            s = _planner_muscle(g)
            if s not in ("other", "cardio", primary) and s not in secondary:
                secondary.append(s)
        entry |= {
            "primary_muscle": primary,
            "secondary_muscles": secondary,
            "volume_muscle": HEVY_MUSCLE_GROUP.get(str(group or "other"), (None, "other"))[0],
            "hevy_primary_muscle_group": group,
            "hevy_type": meta.get("type"),
            "is_custom": bool(meta.get("is_custom")),
        }
    entry["skill_tier"] = tier
    entry["skill_tier_source"] = source
    entry["joint_friendly_score"] = UNREVIEWED_JOINT_FRIENDLY_SCORE
    if entry.get("hevy_type") in REP_BASED_TYPES:
        entry["default_rep_range"] = dict(TIER_REP_RANGE[tier])
    equipment = (meta or {}).get("equipment")
    if source == "title:cable":
        equipment = "cable"
    elif source == "title:smith":
        equipment = "smith"
    entry["equipment"] = equipment
    return entry


def _measured(h: dict[str, Any] | None) -> dict[str, Any]:
    return {
        "sessions": int(h["sessions"]) if h else 0,
        "first_done": h["first_done"] if h else None,
        "last_done": h["last_done"] if h else None,
    }


def generated_entry(tid: str, hist: dict[str, Any], meta: dict[str, Any] | None) -> dict[str, Any]:
    """Pure. One history identity + its Hevy template metadata -> a generated catalog entry."""
    names = hist.get("names") or {}
    fallback_title = sorted(names.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] if names else tid
    entry = enrichment(tid, meta, fallback_title)
    entry |= {"provenance": PROVENANCE_HISTORY, "reviewed": False} | _measured(hist)
    entry["anchor_family"] = anchor_family(entry)
    return entry


def _kind(entry: dict[str, Any]) -> str:
    """How the builder treats an existing entry: regenerated, enriched-if-absent, or preserved."""
    prov = entry.get("provenance")
    if prov == PROVENANCE_HISTORY and not entry.get("reviewed"):
        return "regenerate"
    if prov == PROVENANCE_COACH:
        return "coach"
    return "preserve"


def build_catalog(current: dict[str, Any], history: dict[str, Any], metadata: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Pure + deterministic. The current catalog + history summary + template metadata -> the new catalog."""
    title_to_tid: dict[str, str] = {}
    for tid, m in sorted(metadata.items()):
        t = str(m.get("title") or "").strip().lower()
        if t and not is_retired_template(tid):
            title_to_tid.setdefault(t, tid)
    hist = history["templates"]

    kept: dict[str, dict[str, Any]] = {}
    claimed: dict[str, str] = {}  # template id -> kept key
    coach_added = 0
    for key, entry in (current.get("movements") or {}).items():
        kind = _kind(entry)
        if kind == "regenerate":
            continue
        tid = str(entry.get("hevy_template_id_hint") or "").upper() or title_to_tid.get(str(entry.get("title") or "").strip().lower(), "")
        out = dict(entry)
        if kind == "coach":
            coach_added += 1
            meta = metadata.get(tid) if tid else None
            if meta is not None:
                for field, value in enrichment(tid, meta, str(entry.get("title") or tid)).items():
                    out.setdefault(field, value)
            out.setdefault("reviewed", False)
        else:
            out.setdefault("provenance", PROVENANCE_CURATED)
            out["reviewed"] = True
        out |= _measured(hist.get(tid) if tid else None)
        out["anchor_family"] = anchor_family(out)
        kept[key] = out
        if tid:
            claimed.setdefault(tid, key)

    retired: list[str] = []
    unavailable: list[str] = []
    generated: dict[str, dict[str, Any]] = {}
    for tid in sorted(hist):
        if tid in claimed:
            continue
        if is_retired_template(tid):
            retired.append(tid)
            continue
        meta = metadata.get(tid)
        if meta is None:
            unavailable.append(tid)
        entry = generated_entry(tid, hist[tid], meta)
        key = _slug(entry["title"])
        if key in kept or key in generated:
            key = f"{key}_{_slug(tid)[:8]}"
        generated[key] = entry

    ordered = dict(sorted(generated.items(), key=lambda kv: (-kv[1]["sessions"], kv[0])))
    movements = kept | ordered
    tiers = Counter(int(v.get("skill_tier", 0)) for v in movements.values())
    families = Counter(v["anchor_family"] for v in movements.values() if v.get("anchor_family"))
    return {
        "_comment": CATALOG_COMMENT,
        "_version": 2,
        "_id_format": "8-char uppercase hex for a Hevy standard template; a custom template's id is a UUID. The hint is the id "
        "Hevy serves (GET /v1/exercise_templates).",
        "_provenance": {
            "generated_by": GENERATED_BY,
            "source": f"DynamoDB {TABLE_NAME} pk={HEVY_PK} per-workout rows, every phase (read-only query) + Hevy "
            "GET /v1/exercise_templates (read-only)",
            "history_first": history.get("first"),
            "history_through": history.get("last"),
            "workouts": history.get("workouts"),
            "distinct_templates": len(hist),
            "entries": len(movements),
            "reviewed": sum(1 for v in movements.values() if v.get("reviewed")),
            "coach_added": coach_added,
            "generated": len(ordered),
            "entries_by_skill_tier": {str(t): n for t, n in sorted(tiers.items())},
            "entries_by_anchor_family": dict(sorted(families.items())),
            "excluded_retired_template_ids": retired,
            "metadata_unavailable_template_ids": unavailable,
        },
        "_rules": {
            "skill_tier": "Hevy equipment: machine/resistance_band/none -> 1; dumbbell/kettlebell/plate/suspension/other and "
            "cable (by title) -> 2; barbell and smith (by title) -> 3; metadata unavailable -> 3. See "
            "deploy/build_movement_catalog.py EQUIPMENT_SKILL_TIER.",
            "joint_friendly_score_unreviewed": UNREVIEWED_JOINT_FRIENDLY_SCORE,
            "primary_muscle": "Hevy primary_muscle_group through training/muscle_volume.HEVY_MUSCLE_GROUP (column 1); "
            "volume_muscle is column 0 (muscle_volume.MUSCLES).",
            "generator_eligibility": "training/movement_catalog.generator_eligible: skill_tier <= ceiling AND (reviewed OR a "
            "default_rep_range). No frequency gate (owner ruling C, #4108).",
            "anchor_family": "training/movement_catalog.anchor_family: program_structure.classify_movement(title) AND primary "
            "muscle in the anchor's primary_muscles AND loaded (Hevy weight_reps; any rep-based type for vertical_pull).",
            "coach_added": "A never-trained exercise may be added as {title, hevy_template_id_hint, provenance: coach_added}; "
            "the builder fills absent fields from Hevy metadata and keeps every written field. See "
            "training/movement_catalog.py.",
        },
        "movements": movements,
    }


# ── cli ────────────────────────────────────────────────────────────────────────


def _summary(new: dict[str, Any]) -> str:
    from training.movement_catalog import generator_eligible

    mv = new["movements"]
    lines = [json.dumps(new["_provenance"], indent=2)]
    for ceiling in (1, 2, 3):
        lines.append(f"eligible at skill_ceiling {ceiling}: {sum(1 for v in mv.values() if generator_eligible(v, ceiling))}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true", help=f"overwrite {os.path.relpath(CATALOG_PATH, REPO_ROOT)} (default: dry-run)")
    ap.add_argument("--inputs", help="replay a --save-inputs snapshot instead of reading DynamoDB + Hevy")
    ap.add_argument("--save-inputs", help="write the history summary + template metadata read live to this path")
    args = ap.parse_args(argv)

    with open(CATALOG_PATH, encoding="utf-8") as f:
        current = json.load(f)

    if args.inputs:
        with open(args.inputs, encoding="utf-8") as f:
            snap = json.load(f)
        history, metadata = snap["history"], snap["metadata"]
    else:
        history = summarize_history(fetch_workout_rows(), load_alias_map(current))
        coach_ids = [
            str(v.get("hevy_template_id_hint")).upper()
            for v in (current.get("movements") or {}).values()
            if v.get("hevy_template_id_hint") and v.get("provenance") == PROVENANCE_COACH
        ]
        metadata = fetch_template_metadata(list(history["templates"]) + coach_ids)
    if args.save_inputs:
        with open(args.save_inputs, "w", encoding="utf-8") as f:
            json.dump({"history": history, "metadata": metadata}, f, indent=2, sort_keys=True)
            f.write("\n")

    new = build_catalog(current, history, metadata)
    print(_summary(new))
    if not args.write:
        print("\ndry-run — nothing written (pass --write)")
        return 0
    with open(CATALOG_PATH, "w", encoding="utf-8") as f:
        json.dump(new, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"\nwrote {os.path.relpath(CATALOG_PATH, REPO_ROOT)} ({len(new['movements'])} movements)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
