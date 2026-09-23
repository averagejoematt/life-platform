"""
adherence_calc.py — Phase 2 readback: programmed-vs-performed adherence.

Inputs:
  ir            — the RoutineSpec that was pushed to Hevy (system of record)
  performed     — the Hevy workout as we received it (dict with exercises[]
                  + sets[]). Same shape as /v1/workouts response items.

Output:
  {
    "overall_pct": float,           # 0..100 — SET COMPLETION ONLY (see below)
    "overall_pct_dimension": "sets_only",
    "per_muscle": {muscle: pct},
    "movements": [{movement_key, programmed_sets, performed_sets, pct, intensity}],
    "missing": [movement_keys],
    "extra":   [exercise_template_ids],
    "sets_adherence":      {...},   # #3714 — the set-count dimension, named
    "intensity_adherence": {...},   # #3714 — the RPE-ceiling dimension
    "as_prescribed":       {...},   # #3714 — the AND of the two, never their average
  }

TWO DIMENSIONS, NEVER ONE NUMBER (#3714). Adherence used to be set-count overlap
alone, so the 2026-09-07 push session read `overall_pct: 100.0` while its incline DB
press was logged at RPE 10 — trained to failure on a day whose own plan said "No
failure sets today". `intensity_adherence` is the missing half, graded against the
ceiling the routine ITSELF named (see `training.intensity_prescription` — nothing
there invents a cutoff). The two are reported SEPARATELY on purpose: averaging "he did
every set" with "he blew the ceiling on five of them" back into one percentage would
reproduce the same defect one level up, hiding which half failed. `as_prescribed` is
the composite the story asks for, and it is an AND of two verdicts with its reasons
named — not a blend of two percentages.

`overall_pct` deliberately KEEPS its set-completion meaning: it is already stored on
every pre-#3714 workout record, and silently redefining a number that is written down
is its own lie. It gains `overall_pct_dimension` so no reader can mistake it for the
whole story, and `sets_adherence.pct` is its named twin.

Movement matching: by Hevy exercise_template_id when present; falls back to
title prefix on the catalog title.

TEMPLATE-ID ALIASES (#3929). Hevy's own catalog carries the same movement under more
than one exercise_template_id (specimen: `21310F5F` "Triceps Extension (Cable)" vs
`B5EFBF9C` "Overhead Triceps Extension (Cable)" — one movement, two ids). Matched by
raw template_id alone, a performed set logged under the alias id scored as BOTH one
missing (the prescribed id never seen performed) and one extra (the alias id never
seen prescribed) — a single real movement double-penalized. `config/hevy_template_aliases.json`
(`aliases`: alias `template_id` -> canonical `movement_key`, read by `_load_template_aliases`)
is resolved to a canonical template_id via the SAME `_ir_movement_to_template` path
programmed exercises already use, and applied to the performed side BEFORE missing/extra
are computed. The registry is shrink-only-honest: it is the ONLY source of resolution —
nothing here infers or auto-merges a pairing at runtime. `find_alias_candidates()` is the
reporting tool for an unconfirmed pairing; it never feeds back into scoring.
`canonical_template_ids()` is the same resolution exposed for OTHER readers (#4069's
exercise-history / anchor-lift trend key in `mcp/strength_helpers.exercise_identity()`) —
one alias table, read once, never a second one grown beside it (#4073).

PROGRAM-DEFAULT INTENSITY CEILING (#4073). `intensity_prescription.resolve_ceiling`
correctly refuses to invent a ceiling — a movement whose OWN prescription names no RPE/RIR
returns `{"rpe": None}` on purpose (ADR-105: no invented thresholds). But a `None` ceiling
made `grade_sets` report `status: "unprescribed"` and drop the movement out of the
intensity denominator entirely — so an isolation accessory logged at RPE 9.5 (to-failure
territory) still read a clean `as_prescribed` verdict, because nothing was ever compared.
The program itself (v0.3 §3, `training.program_structure.EXPOSURES`, prose home
`owner_redlines.REDLINES["lifting_sessions_per_wk"]["rep_scheme"]`) already names a ceiling
for every movement CLASS even when a specific session's notes don't repeat it: accessories
are RIR 1-2 (RPE <= 9), and the anchor pattern families train at the heavy exposure's top_rpe
ceiling (<= 8) at the loosest. `_program_default_ceiling` applies that class-level default
ONLY when the routine's own prescription is silent (`resolve_ceiling` returned `rpe: None`)
— an explicit routine/exercise ceiling always wins, this is a fallback, never an override.
Classification is by the SAME `program_structure.classify_movement` the accessory-rotation
check already uses, read against the movement's Hevy catalog/alias title (never the raw
movement_key string, which has no spaces for the title hints to match). A movement that
classifies `cardio` — or that cannot be classified at all because no title is available —
gets no default: ADR-104 absence semantics still apply where the program truly has nothing
to say. `intensity["basis"]` names a defaulted ceiling `"program_default:accessory"` /
`"program_default:anchor:<family>"` so a reader can always tell an inherited program number
from the routine's own words.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any

from common.repo_config import config_dir
from training.intensity_prescription import RIR_RPE_ANCHOR, grade_sets, resolve_ceiling
from training.program_structure import EXPOSURES, classify_movement
from training.routine_ir import RoutineSpec

logger = logging.getLogger("adherence_calc")

# Depth-independent default — see common.repo_config (#1653). The literal
# `dirname(__file__)/../config` assumed this module sat directly under the repo root.
CONFIG_DIR = os.environ.get("TRAINING_CONFIG_DIR", config_dir())
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
S3_CONFIG_PREFIX = os.environ.get("TRAINING_CONFIG_S3_PREFIX", "config/")

_s3_loader_client = None


def _load_catalog() -> dict[str, Any]:
    local = os.path.join(CONFIG_DIR, "movement_catalog.json")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            return json.load(f)
    global _s3_loader_client
    if _s3_loader_client is None:
        import boto3

        _s3_loader_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
    obj = _s3_loader_client.get_object(Bucket=S3_BUCKET, Key=f"{S3_CONFIG_PREFIX}movement_catalog.json")
    return json.loads(obj["Body"].read())


def _load_template_cache() -> dict[str, Any]:
    """The resolved movement→Hevy-template map the compiler actually pushed
    (`config/hevy_template_cache.json`). Enrichment over the catalog hints, used only
    for ADR-069 title-resolved movements that deliberately carry NO hint — their real
    id lives here. Absent cache is non-fatal: we fall back to hints (empty → {})."""
    local = os.path.join(CONFIG_DIR, "hevy_template_cache.json")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            return json.load(f)
    global _s3_loader_client
    if _s3_loader_client is None:
        import boto3

        _s3_loader_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
    try:
        obj = _s3_loader_client.get_object(Bucket=S3_BUCKET, Key=f"{S3_CONFIG_PREFIX}hevy_template_cache.json")
        return json.loads(obj["Body"].read())
    except Exception as e:  # noqa: BLE001 — enrichment only; hints still resolve most movements
        logger.warning("template cache load failed (non-fatal, hints still apply): %s", e)
        return {}


def _load_template_aliases() -> dict[str, Any]:
    """The confirmed template-ID alias registry (`config/hevy_template_aliases.json`,
    #3929) — alias `exercise_template_id` -> canonical `movement_key`. Absent registry
    is non-fatal: no aliasing applied, matching pre-#3929 behavior exactly."""
    local = os.path.join(CONFIG_DIR, "hevy_template_aliases.json")
    if os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            return json.load(f)
    global _s3_loader_client
    if _s3_loader_client is None:
        import boto3

        _s3_loader_client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
    try:
        obj = _s3_loader_client.get_object(Bucket=S3_BUCKET, Key=f"{S3_CONFIG_PREFIX}hevy_template_aliases.json")
        return json.loads(obj["Body"].read())
    except Exception as e:  # noqa: BLE001 — resolution is best-effort; absence must not break scoring
        logger.warning("template alias registry load failed (non-fatal, no aliasing applied): %s", e)
        return {}


def _ir_movement_to_template(catalog: dict[str, Any], movement_key: str, cache: dict[str, Any] | None = None) -> str | None:
    """Resolve a programmed movement_key to the Hevy template id it was pushed as.
    Three tiers: (1) ADR-069 template-index keys of the form "tmpl:<id>" already carry
    the resolved id in the suffix (a movement added by raw template, not a catalog entry
    — mirrors tools_hevy_routine.py); resolve it directly or it would be counted "missing"
    even when performed, deflating adherence. (2) catalog hint (authoritative for hinted
    movements). (3) resolved template cache for title-resolved movements (no hint on purpose)."""
    if movement_key and movement_key.startswith("tmpl:"):
        return movement_key[len("tmpl:") :]
    hint = catalog.get("movements", {}).get(movement_key, {}).get("hevy_template_id_hint")
    if hint:
        return hint
    return ((cache or {}).get("movements", {}).get(movement_key) or {}).get("hevy_template_id")


def _resolve_alias_canonical_tids(catalog: dict[str, Any], cache: dict[str, Any], aliases: dict[str, str]) -> dict[str, str]:
    """Resolve the alias registry's `template_id -> movement_key` entries down to
    `template_id -> canonical template_id`, through the SAME movement_key namespace
    `_ir_movement_to_template` already reads (catalog hint / cache / the ADR-069
    `tmpl:<id>` escape hatch). An entry whose movement_key does not resolve to a
    template id is skipped (logged, non-fatal) rather than applied half-resolved —
    an unresolvable alias must fail open to pre-#3929 behavior, never raise."""
    resolved: dict[str, str] = {}
    for alias_tid, movement_key in (aliases or {}).items():
        canonical_tid = _ir_movement_to_template(catalog, movement_key, cache)
        if canonical_tid:
            resolved[alias_tid] = canonical_tid
        else:
            logger.warning(
                "template alias %s -> %s: movement_key did not resolve to a template id; alias skipped",
                alias_tid,
                movement_key,
            )
    return resolved


def canonical_template_ids() -> dict[str, str]:
    """alias template_id -> canonical template_id, both upper-cased — the registry above,
    resolved through the SAME `_resolve_alias_canonical_tids` path adherence scoring uses.

    Public for the exercise-history and anchor-lift reads (#4069), so identity has ONE alias
    table (#3929's) and not a second one grown beside it. Raises if the catalog cannot be
    read; the caller decides how an unreadable registry is reported (never as "no aliases")."""
    resolved = _resolve_alias_canonical_tids(_load_catalog(), _load_template_cache(), _load_template_aliases().get("aliases", {}))
    return {str(a).strip().upper(): str(c).strip().upper() for a, c in resolved.items() if a and c}


# ── program-default intensity ceiling (#4073) ─────────────────────────────────
# Derived from training.program_structure.EXPOSURES, never re-typed as a literal — a
# change to the program's own numbers must move this too, not silently drift from it.
# The one prose home for both is owner_redlines.REDLINES["lifting_sessions_per_wk"]["rep_scheme"]
# ("heavy exposure 4-6: one top set at RPE 7-8 plus two back-offs at -10%; moderate 6-10;
# accessories 8-15 at RIR 1-2").
_ACCESSORY_DEFAULT_RPE: float = RIR_RPE_ANCHOR - min(EXPOSURES["accessory"]["rir"])  # RIR 1-2 -> RPE <= 9
_ANCHOR_DEFAULT_RPE: float = float(max(EXPOSURES["heavy"]["top_rpe"]))  # the tightest numeric ceiling EXPOSURES names


def _catalog_entry_for(movement_key: str, catalog: dict[str, Any]) -> dict[str, Any]:
    """The catalog entry for one IR movement_key — by key, or for the ADR-069 `tmpl:<id>` form
    by the entry whose `hevy_template_id_hint` IS that id (#4073, live 2026-09-23).

    Chat-authored routines key their movements `tmpl:<id>`, and since #4108 the catalog holds
    the whole Hevy history keyed by name with the template id as a hint. A by-key lookup alone
    therefore missed 7 of 9 movements on the 09-22 legs session — no default ceiling, and
    `per_muscle: {unknown: 100}`. Case-insensitive: Hevy ids appear in both cases."""
    movements = catalog.get("movements", {}) or {}
    entry = movements.get(movement_key)
    if entry or not (movement_key or "").startswith("tmpl:"):
        return entry or {}
    tid = movement_key[len("tmpl:") :].upper()
    return next((e for e in movements.values() if str(e.get("hevy_template_id_hint") or "").upper() == tid), {})


def _movement_title_for_classification(movement_key: str, catalog: dict[str, Any], alias_titles: dict[str, str]) -> str:
    """The Hevy-catalog title for one movement_key, for `program_structure.classify_movement`
    — which matches against TITLE substrings ("bench press", "pulldown") and would silently
    miss every one of them if handed a raw movement_key (`db_bench_press_flat` has no space).

    Catalog entry title first; the ADR-069 `tmpl:<id>` escape hatch (a movement with no
    catalog entry of its own — the exact case the #3929 alias specimen is) falls back to the
    alias registry's OWN `titles` map, keyed by the plain template id — the same file already
    read for aliasing, not a second title source (#4073)."""
    entry = _catalog_entry_for(movement_key, catalog)
    if entry.get("title"):
        return str(entry["title"])
    if movement_key and movement_key.startswith("tmpl:"):
        return str(alias_titles.get(movement_key[len("tmpl:") :], "") or "")
    return ""


def _program_default_ceiling(movement_key: str, catalog: dict[str, Any], alias_titles: dict[str, str]) -> dict[str, Any]:
    """The program's own class-level RPE ceiling for a movement whose OWN prescription
    named none (#4073). Never consulted when `resolve_ceiling` already found one — this is
    the fallback, not an override.

    Classification is `program_structure.classify_movement` against the movement's title.
    A movement with no resolvable title, or one that classifies `cardio`, gets no default —
    ADR-104 absence semantics: "the plan never said" stays legible, it is not manufactured.
    Returns {"rpe": float|None, "basis": str|None}, the same shape `resolve_ceiling` returns.
    """
    title = _movement_title_for_classification(movement_key, catalog, alias_titles)
    if not title:
        return {"rpe": None, "basis": None}
    cls = classify_movement(title)
    if cls == "cardio":
        return {"rpe": None, "basis": None}
    if cls.startswith("anchor:"):
        return {"rpe": _ANCHOR_DEFAULT_RPE, "basis": f"program_default:{cls}"}
    return {"rpe": _ACCESSORY_DEFAULT_RPE, "basis": "program_default:accessory"}


# Conservative on purpose (#3929): only orientation/variant words known to describe the
# SAME movement pattern under a different Hevy catalog entry. Deliberately excludes
# words like "incline"/"decline" that name a genuinely different movement (see
# `incline_db_press` vs `db_bench_press_flat` in config/movement_catalog.json) — a wider
# list would surface false candidates faster than a human could review them.
_ALIAS_TITLE_MODIFIER_WORDS = {"overhead"}


def _normalize_alias_title(title: str) -> str:
    """The grouping key `find_alias_candidates` groups titles by: lowercase, collapse
    whitespace, drop `_ALIAS_TITLE_MODIFIER_WORDS` tokens. NOT used for scoring —
    candidate generation only."""
    t = re.sub(r"\s+", " ", (title or "").strip().lower())
    words = [w for w in t.split(" ") if w and w not in _ALIAS_TITLE_MODIFIER_WORDS]
    return " ".join(words)


def find_alias_candidates(titles: dict[str, str], known_aliases: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """Report UNCONFIRMED alias candidates — never applied to scoring (shrink-only-honest,
    #3929's acceptance: "an unrecognized template pairing is reported as a candidate,
    never silently merged"). `titles` is `{exercise_template_id: title}` (e.g. from
    `config/hevy_template_aliases.json`'s own `titles` map, or a Hevy template-index
    walk); `known_aliases` is the registry's confirmed `aliases` map, used only to
    exclude ids the registry already accounts for so the output is the unconfirmed
    residue a human still needs to review.

    A group of >=2 template ids that normalize (see `_normalize_alias_title`) to the
    same core title is a candidate. This function performs NO resolution — it is a
    reporting tool, called by a human/script curating the registry, never by
    `calculate_adherence`."""
    known_aliases = known_aliases or {}
    groups: dict[str, list[str]] = {}
    for tid, title in (titles or {}).items():
        key = _normalize_alias_title(title)
        if not key:
            continue
        groups.setdefault(key, []).append(tid)

    candidates: list[dict[str, Any]] = []
    for key, ids in groups.items():
        if len(ids) < 2:
            continue
        unconfirmed = sorted(tid for tid in ids if tid not in known_aliases)
        if len(unconfirmed) < 2:
            continue  # the registry already accounts for every id but one in this group
        candidates.append({"normalized_title": key, "template_ids": unconfirmed})
    return sorted(candidates, key=lambda c: c["normalized_title"])


def _intensity_rollup(movements: list[dict[str, Any]]) -> dict[str, Any]:
    """Roll the per-movement intensity grades into the session's intensity dimension.

    The denominator is GRADED working sets only — sets that carried both a prescribed
    ceiling and a logged RPE. Sets with no logged RPE are reported in `sets_rpe_absent`
    and never counted as within-ceiling (ADR-104: absence is absence, not compliance).

    `status`:
      graded       — at least one working set had a ceiling AND an RPE
      unreadable   — a ceiling was prescribed but no working set carried an RPE
      unprescribed — the routine named no intensity anywhere (pct is None, never 100)
    """
    grades = [m["intensity"] for m in movements if m.get("intensity")]
    # Only movements that were actually PRESCRIBED an intensity contribute to the
    # rollup. A movement with no ceiling has nothing to be compliant or non-compliant
    # with; counting its sets as "graded" would silently manufacture a denominator.
    prescribed = [g for g in grades if g["ceiling_rpe"] is not None]
    graded = sum(g["sets_graded"] for g in prescribed)
    over = sum(g["sets_over_ceiling"] for g in prescribed)
    absent = sum(g["sets_rpe_absent"] for g in prescribed)
    overages = [g["max_overage"] for g in prescribed if g.get("max_overage")]

    if graded:
        status = "graded"
        pct: float | None = round((graded - over) / graded * 100, 1)
    elif prescribed:
        status, pct = "unreadable", None
    else:
        status, pct = "unprescribed", None

    return {
        "status": status,
        "pct": pct,
        "sets_graded": graded,
        "sets_over_ceiling": over,
        "sets_rpe_absent": absent,
        "movements_with_ceiling": len(prescribed),
        "max_overage": max(overages) if overages else (0.0 if graded else None),
        "over_ceiling_movements": sorted(m["movement_key"] for m in movements if (m.get("intensity") or {}).get("sets_over_ceiling")),
    }


def _as_prescribed(sets_pct: float, intensity: dict[str, Any], movements: list[dict[str, Any]]) -> dict[str, Any]:
    """ "Did he train the session as prescribed?" — an AND of the two dimensions.

    Never an average. `no` names which dimension failed; `unknown` is returned rather
    than `yes` whenever the intensity half could not be read, because "we couldn't tell"
    has never been the same claim as "he complied" (ADR-104).
    """
    reasons: list[str] = []
    if sets_pct < 100.0:
        reasons.append(f"sets: {sets_pct}% of programmed sets completed")
    if intensity["sets_over_ceiling"]:
        names = ", ".join(intensity["over_ceiling_movements"])
        reasons.append(f"intensity: {intensity['sets_over_ceiling']} set(s) above the prescribed RPE ceiling ({names})")
    if reasons:
        return {"verdict": "no", "reasons": reasons}

    if intensity["status"] != "graded":
        return {"verdict": "unknown", "reasons": [f"intensity: {intensity['status']} — no RPE-vs-ceiling comparison was possible"]}
    blind = sorted(
        m["movement_key"]
        for m in movements
        if (m.get("intensity") or {}).get("sets_rpe_absent") and str((m["intensity"] or {}).get("basis") or "").startswith("exercise")
    )
    if blind:
        return {
            "verdict": "unknown",
            "reasons": [f"intensity: RPE not logged on movements that carried their own ceiling ({', '.join(blind)})"],
        }
    return {"verdict": "yes", "reasons": []}


def calculate_adherence(ir: RoutineSpec, performed: dict[str, Any]) -> dict[str, Any]:
    catalog = _load_catalog()
    cache = _load_template_cache()
    alias_registry = _load_template_aliases()  # #3929's one registry — aliases AND titles read from it
    alias_to_canonical_tid = _resolve_alias_canonical_tids(catalog, cache, alias_registry.get("aliases", {}))
    alias_titles = alias_registry.get("titles", {})
    routine_notes = getattr(ir, "notes", "") or ""
    recovery_branches = ((getattr(ir, "inputs_snapshot", None) or {}) or {}).get("recovery_branches")
    programmed: list[dict[str, Any]] = []
    template_to_key: dict[str, str] = {}
    for ex in ir.exercises:
        tid = _ir_movement_to_template(catalog, ex.movement_key, cache)
        sets = len(ex.sets)
        ceiling = resolve_ceiling(ex.movement_key, getattr(ex, "notes", "") or "", routine_notes, recovery_branches)
        if ceiling["rpe"] is None:
            # #4073 — the routine's own words named no ceiling; fall back to the program's
            # class-level default (accessory / anchor pattern) before calling it ungraded.
            ceiling = _program_default_ceiling(ex.movement_key, catalog, alias_titles)
        programmed.append({"movement_key": ex.movement_key, "template_id": tid, "sets": sets, "ceiling": ceiling})
        if tid:
            template_to_key[tid] = ex.movement_key

    performed_by_tid: dict[str, int] = {}
    performed_sets_by_tid: dict[str, list[dict[str, Any]]] = {}
    for ex in performed.get("exercises", []):
        tid = ex.get("exercise_template_id")
        if not tid:
            continue
        tid = alias_to_canonical_tid.get(tid, tid)  # #3929 — resolved BEFORE missing/extra
        ex_sets = ex.get("sets", []) or []
        performed_by_tid[tid] = performed_by_tid.get(tid, 0) + len(ex_sets)
        performed_sets_by_tid.setdefault(tid, []).extend(ex_sets)

    movements: list[dict[str, Any]] = []
    per_muscle_programmed: dict[str, int] = {}
    per_muscle_performed: dict[str, int] = {}
    for p in programmed:
        performed_sets = performed_by_tid.get(p["template_id"], 0)
        pct = round(min(1.0, performed_sets / p["sets"]) * 100, 1) if p["sets"] else 0.0
        intensity = grade_sets(p["ceiling"]["rpe"], performed_sets_by_tid.get(p["template_id"], []))
        intensity["basis"] = p["ceiling"]["basis"]
        movements.append(
            {
                "movement_key": p["movement_key"],
                "programmed_sets": p["sets"],
                "performed_sets": performed_sets,
                "pct": pct,
                "intensity": intensity,
            }
        )
        muscle = _catalog_entry_for(p["movement_key"], catalog).get("primary_muscle", "unknown")
        per_muscle_programmed[muscle] = per_muscle_programmed.get(muscle, 0) + p["sets"]
        per_muscle_performed[muscle] = per_muscle_performed.get(muscle, 0) + performed_sets

    missing = [m["movement_key"] for m in movements if m["performed_sets"] == 0]
    programmed_tids = {p["template_id"] for p in programmed if p["template_id"]}
    extra = [tid for tid in performed_by_tid if tid not in programmed_tids]

    per_muscle = {
        muscle: round(min(1.0, per_muscle_performed.get(muscle, 0) / max(1, sets)) * 100, 1)
        for muscle, sets in per_muscle_programmed.items()
    }
    total_programmed = sum(per_muscle_programmed.values())
    total_performed = sum(min(per_muscle_programmed[m], per_muscle_performed.get(m, 0)) for m in per_muscle_programmed)
    overall_pct = round((total_performed / total_programmed) * 100, 1) if total_programmed else 0.0

    intensity_adherence = _intensity_rollup(movements)

    return {
        "overall_pct": overall_pct,
        # #3714: name the dimension on the number so nothing can read set completion
        # as "trained as prescribed". The two dimensions below are never averaged.
        "overall_pct_dimension": "sets_only",
        "sets_adherence": {
            "pct": overall_pct,
            "programmed_sets": total_programmed,
            "performed_sets": total_performed,
        },
        "intensity_adherence": intensity_adherence,
        "as_prescribed": _as_prescribed(overall_pct, intensity_adherence, movements),
        "per_muscle": per_muscle,
        "movements": movements,
        "missing": missing,
        "extra": extra,
    }


def _best_by_overlap(candidates: list[RoutineSpec], performed: dict[str, Any]) -> tuple[RoutineSpec | None, str | None]:
    """When several routines were pushed for one day (ideal/floor/re-entry siblings),
    pick the one whose programmed template-ids best overlap what was actually performed.
    Returns (ir, "date_overlap") or (None, None) on a zero-overlap or a tie — we do not
    guess between equally-plausible plans (ADR-104)."""
    catalog = _load_catalog()
    cache = _load_template_cache()
    alias_to_canonical_tid = _resolve_alias_canonical_tids(catalog, cache, _load_template_aliases().get("aliases", {}))
    performed_tids = {
        alias_to_canonical_tid.get(t, t)  # #3929 — same alias resolution as calculate_adherence
        for t in (ex.get("exercise_template_id") for ex in performed.get("exercises", []))
        if t
    }
    scored: list[tuple[int, RoutineSpec]] = []
    for c in candidates:
        prog_tids = {t for t in (_ir_movement_to_template(catalog, ex.movement_key, cache) for ex in c.exercises) if t}
        scored.append((len(prog_tids & performed_tids), c))
    scored.sort(key=lambda s: s[0], reverse=True)
    if not scored or scored[0][0] == 0:
        return None, None
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None, None  # a genuine tie — don't fabricate a match
    return scored[0][1], "date_overlap"


def derive_adherence(raw_workout: dict[str, Any]) -> dict[str, Any] | None:
    """On-ingest deviation readback (#412): match a performed Hevy workout to the plan
    that was pushed for it, and compute programmed-vs-performed adherence.

    `raw_workout` is the RAW Hevy /v1/workouts item — it carries `routine_id`,
    `start_time`, and `exercises[].exercise_template_id` + `sets[]`. Do NOT pass the
    normalized record: normalization renames `exercise_template_id` → `template_id`,
    which would break the template match.

    Returns exactly one of (never raises — a projection must never break ingestion):
      • {"status": "matched",   "matched_routine_id", "match_method", "routine_target_date",
         "workout_pacific_date", "computed_at", **calculate_adherence(...)}
      • {"status": "ad_hoc",    "matched_routine_id": None, ...}      — no pushed plan
      • {"status": "ambiguous", "candidate_routine_ids": [...], ...}  — plans existed, none matched confidently
      • None                                                          — unexpected error (logged, non-fatal)

    ad_hoc / ambiguous deliberately omit every pct / movement field so nothing downstream
    can render a fabricated number (ADR-104)."""
    try:
        from common.pacific_time import pacific_date_of
        from training import routine_repo

        performed = raw_workout or {}
        pac_date = pacific_date_of(performed.get("start_time"))
        base = {
            "workout_pacific_date": pac_date,
            "computed_at": datetime.now(timezone.utc).isoformat(),
        }

        ir: RoutineSpec | None = None
        match_method: str | None = None
        candidates: list[RoutineSpec] = []

        # 1) Exact — the workout carries the Hevy routine id it was started from;
        #    reverse the id-map to our routine_id. Immune to the UTC-date keying bug.
        hevy_rid = str(performed.get("routine_id") or "").strip()
        if hevy_rid:
            rid = routine_repo.lookup_routine_id(hevy_rid)
            if rid:
                ir = routine_repo.get_current(rid)
                if ir:
                    match_method = "hevy_routine_id"

        # 2) Fallback — the routine(s) pushed for this Pacific calendar day.
        if ir is None and pac_date:
            candidates = routine_repo.list_by_date_range(pac_date, pac_date)
            if len(candidates) == 1:
                ir, match_method = candidates[0], "date_single"
            elif len(candidates) > 1:
                ir, match_method = _best_by_overlap(candidates, performed)

        if ir is None:
            if candidates:  # plans existed but none matched confidently → say so, don't guess
                return {
                    **base,
                    "status": "ambiguous",
                    "matched_routine_id": None,
                    "candidate_routine_ids": [getattr(c, "routine_id", None) for c in candidates],
                }
            return {**base, "status": "ad_hoc", "matched_routine_id": None}

        return {
            **base,
            "status": "matched",
            "matched_routine_id": getattr(ir, "routine_id", None),
            "match_method": match_method,
            "routine_target_date": getattr(ir, "target_date", None),
            **calculate_adherence(ir, performed),
        }
    except Exception as e:  # noqa: BLE001 — deviation is a projection; never break ingestion
        logger.warning("adherence derive failed (non-fatal): %s", e)
        return None
