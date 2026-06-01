"""
tools_hevy_routine.py — `manage_hevy_routine` fat MCP tool (ADR-066, ADR-069).

One tool, ten actions:

  draft         — generate IR via the deterministic programmer (no Hevy write)
  draft_custom  — author an IR from an explicit exercise/set/weight list (ADR-069)
  dry_run       — compile a draft IR into the Hevy wire body for preview
  commit        — push a draft IR to Hevy via the compiler (write tool)
  list          — list ROUTINE# items in a date range
  get           — return one IR by routine_id
  archive       — rename + folder-move (Hevy has no DELETE)
  floor         — generate floor variant explicitly
  re_entry      — force re-entry mode regardless of last-workout date
  adherence     — programmed-vs-performed report for a routine_id

`draft` is the opinionated, deterministic volume-landmark programmer — it
builds its own routine from your state and never takes an exercise list.
`draft_custom` (ADR-069) is the escape hatch: it accepts a fully specified
session (movements, sets, loads) and persists it as a normal draft IR, so the
dry_run → commit chain pushes it to Hevy unchanged. Loads in draft_custom are
user-supplied; the platform does NOT compute them (ADR-068's "LLM never
computes" applies only to the deterministic path).

Commit-gate principle: `commit` and `archive` require an explicit
routine_id. No write on inferred intent.

Reminder: the public site / chronicle must never describe this feature
as "autoregulated" while the readiness signal is unvalidated (per Lena's
dissent in REVIEW §4). Correct phrasing: "deterministic volume-landmark
programming with red-day deload guard."
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from mcp.utils import mcp_error

logger = logging.getLogger("tools_hevy_routine")

_VALID_ACTIONS = {
    "draft", "draft_custom", "dry_run", "commit", "list", "get",
    "archive", "floor", "re_entry", "adherence",
}

_LB_TO_KG = 0.45359237


def _ts_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_resolver():
    """movement_key -> Hevy template_id resolver with a reconcile-by-title fallback.

    The catalog ships a `hevy_template_id_hint` for most movements; when one is
    missing (e.g. a movement added for draft_custom), fall back to searching the
    live Hevy template list by title (`reconcile_custom`). This keeps the
    compiler I/O-free and means a new movement only needs its exact Hevy title in
    the catalog — never a hand-transcribed template id, which could silently
    mis-map. A title miss raises MovementUnmappable loudly rather than pushing the
    wrong exercise.
    """
    from hevy_template_cache import (MovementUnmappable, reconcile_custom,
                                     resolve_movement)
    import hevy_write_client as wc

    def _resolve(movement_key: str) -> str:
        # ADR-069 (template index): keys of the form "tmpl:<id>" are already
        # resolved (draft_custom matched a title against the full Hevy index or
        # a live lookup). Short-circuit straight to the id — no catalog needed.
        if movement_key.startswith("tmpl:"):
            return movement_key[len("tmpl:"):]
        try:
            return resolve_movement(movement_key)
        except MovementUnmappable:
            return reconcile_custom(movement_key, wc.list_templates)

    return _resolve


def _generator_inputs(args: dict[str, Any]):
    from routine_generator import GeneratorInputs
    return GeneratorInputs(
        target_date=args.get("target_date") or datetime.now(timezone.utc).date().isoformat(),
        recovery_tier=args.get("recovery_tier", "yellow"),
        acwr_flag=args.get("acwr_flag", "safe"),
        volume_7d=args.get("volume_7d") or {},
        z2_minutes_7d=float(args.get("z2_minutes_7d") or 0),
        days_since_last_workout=int(args.get("days_since_last_workout") or 2),
        add_load_enabled=False,  # never permitted from chat; SSM-gated only
    )


def _action_draft(args: dict[str, Any]) -> dict[str, Any]:
    from routine_generator import generate_routines
    from routine_repo import put_versioned
    inputs = _generator_inputs(args)
    routines = generate_routines(inputs)
    ideal = next((r for r in routines if r.variant == "ideal"), None)
    floor = next((r for r in routines if r.variant == "floor"), None)
    for ir in routines:
        put_versioned(ir)
    return {
        "status": "drafted",
        "target_date": inputs.target_date,
        "ideal_routine_id": getattr(ideal, "routine_id", None),
        "floor_routine_id": getattr(floor, "routine_id", None),
        "variants_persisted": [r.variant for r in routines],
        "rationale": (ideal.rationale if ideal else []),
        "note": "Use action=dry_run before action=commit. Commit requires explicit routine_id.",
    }


def _catalog_movements() -> dict[str, Any]:
    from routine_generator import _load_json
    return (_load_json("movement_catalog.json") or {}).get("movements", {})


def _normalize_title(t: str) -> str:
    """Normalize a title for index lookup: lowercase, collapse whitespace, strip."""
    import re
    return re.sub(r"\s+", " ", (t or "").strip().lower())


def _template_index() -> dict[str, Any]:
    """Full Hevy template index (ADR-069): normalized_title -> {id, title}.

    Covers every built-in Hevy exercise plus the account's custom ones, so
    draft_custom can author any exercise by name without a curated catalog
    entry. Distinct from movement_catalog.json (the generator's curated pool).
    Returns {} if the index is absent — resolution then falls back to a live
    Hevy lookup.
    """
    from routine_generator import _load_json
    try:
        return (_load_json("hevy_template_index.json") or {}).get("templates", {})
    except Exception:
        return {}


def _live_template_id_by_title(name: str) -> str | None:
    """Self-heal: search the live Hevy template list for an exact title match.

    Triggered only when the static index misses (e.g. a template created in
    Hevy after the index was last built). Exact normalized-title match only —
    never a fuzzy guess, to avoid silently pushing the wrong exercise.
    """
    import hevy_write_client as wc
    target = _normalize_title(name)
    page = 1
    while page <= 30:
        try:
            resp = wc.list_templates(page=page, page_size=100)
        except Exception:
            return None
        items = resp.get("exercise_templates") or resp.get("templates") or []
        if not items:
            return None
        for t in items:
            if _normalize_title(t.get("title")) == target and t.get("id"):
                return str(t["id"])
        if len(items) < 100:
            return None
        page += 1
    return None


def _resolve_movement_key(ex: dict[str, Any], catalog: dict[str, Any]) -> str | None:
    """Map a caller-supplied exercise onto a resolvable movement key.

    Resolution order (conservative — exact matches before fuzzy, curated before
    index, to avoid silent mis-maps):
      1. explicit `movement_key` that is a curated catalog key (keeps generator
         metadata + ADR-067/068 semantics)
      2. exact title match against the curated catalog
      3. exact normalized-title match against the full Hevy index -> "tmpl:<id>"
      4. exact title match against the live Hevy list (self-heal) -> "tmpl:<id>"
      5. loose contains match within the small curated catalog only

    Returns None when nothing maps — caller surfaces a loud, listy error.
    """
    mk = (ex.get("movement_key") or "").strip()
    if mk and mk in catalog:
        return mk
    name = (ex.get("title") or ex.get("name") or mk or "").strip()
    if not name:
        return None
    nlow = name.lower()

    # 2. curated catalog, exact title
    for k, v in catalog.items():
        if (v.get("title") or "").strip().lower() == nlow:
            return k

    # 3. full Hevy index, exact normalized title
    norm = _normalize_title(name)
    hit = _template_index().get(norm)
    if hit and hit.get("id"):
        return "tmpl:" + str(hit["id"])

    # 4. live Hevy lookup (self-heal for templates newer than the index)
    live_id = _live_template_id_by_title(name)
    if live_id:
        return "tmpl:" + live_id

    # 5. loose contains within the curated catalog only (small + trusted)
    for k, v in catalog.items():
        title = (v.get("title") or "").strip().lower()
        if title and (nlow in title or title in nlow):
            return k
    return None


def _index_suggestions(name: str, limit: int = 8) -> list[str]:
    """Closest index titles sharing a token with `name` — for loud-error help."""
    tokens = {w for w in _normalize_title(name).split() if len(w) > 2}
    if not tokens:
        return []
    out = []
    for v in _template_index().values():
        title = v.get("title") or ""
        if tokens & set(_normalize_title(title).split()):
            out.append(title)
            if len(out) >= limit:
                break
    return out


def _coerce_sets(raw_sets: list[dict[str, Any]] | None) -> list:
    """Build IR Set objects from a caller spec. lbs -> kg (Hevy stores kg);
    `count` repeats a set N times (ergonomic for '15 lb x 15 (x3)')."""
    from routine_ir import Set
    sets: list = []
    for s in raw_sets or []:
        if not isinstance(s, dict):
            continue
        weight_kg = s.get("weight_kg")
        if weight_kg is None and s.get("weight_lbs") is not None:
            weight_kg = round(float(s["weight_lbs"]) * _LB_TO_KG, 4)
        reps = int(s["reps"]) if s.get("reps") is not None else None
        n = max(1, int(s.get("count") or 1))
        for _ in range(n):
            sets.append(Set(
                type=s.get("type", "normal"),
                weight_kg=weight_kg,
                reps=reps,
                rep_range_start=s.get("rep_range_start"),
                rep_range_end=s.get("rep_range_end"),
                distance_meters=s.get("distance_meters"),
                duration_seconds=s.get("duration_seconds"),
                custom_metric=s.get("custom_metric"),
            ))
    return sets


def _action_draft_custom(args: dict[str, Any]) -> dict[str, Any]:
    """Author an IR from an explicit exercise/set/weight list (ADR-069).

    Bypasses the deterministic generator. Loads + sets are taken verbatim from
    the caller; the platform does not compute them. The resulting draft IR is
    identical in shape to a generator draft, so dry_run/commit work unchanged.
    """
    from routine_ir import ExerciseBlock, RoutineSpec
    from routine_generator import _new_routine_id, _now_iso
    from routine_repo import put_versioned

    raw_exercises = args.get("exercises")
    if not isinstance(raw_exercises, list) or not raw_exercises:
        return mcp_error(
            "draft_custom requires a non-empty 'exercises' list "
            "[{movement_key|title, sets:[{weight_lbs|weight_kg, reps|rep_range_start/end, "
            "count?}], rest_seconds?, superset_id?, notes?}]",
            error_code="MISSING_ARG",
        )

    catalog = _catalog_movements()
    blocks: list = []
    unknown: list[str] = []
    for ex in raw_exercises:
        if not isinstance(ex, dict):
            continue
        raw_label = str(ex.get("title") or ex.get("name") or ex.get("movement_key") or "?")
        mk = _resolve_movement_key(ex, catalog)
        if not mk:
            unknown.append(raw_label)
            continue
        mdef = catalog.get(mk, {})  # empty for index-resolved ("tmpl:") movements
        blocks.append(ExerciseBlock(
            movement_key=mk,
            sets=_coerce_sets(ex.get("sets")),
            superset_id=(int(ex["superset_id"]) if ex.get("superset_id") is not None else None),
            rest_seconds=(int(ex["rest_seconds"]) if ex.get("rest_seconds") is not None else None),
            notes=(ex.get("notes") or ""),
            joint_friendly_score=int(mdef.get("joint_friendly_score", 3)),
            skill_tier=int(mdef.get("skill_tier", 1)),
            # human label for traceability — curated movements keep "custom",
            # index-resolved ones record the title that mapped to the template id.
            rationale_tag=(mdef.get("title") or raw_label) if mk.startswith("tmpl:") else "custom",
        ))

    if unknown:
        msg = ("Unknown movement(s): " + ", ".join(unknown) + ". "
               "Pass a curated movement_key or an exact Hevy exercise title "
               "(any built-in or custom Hevy exercise resolves by title).")
        suggestions = []
        for u in unknown:
            suggestions += _index_suggestions(u, limit=6)
        if suggestions:
            msg += " Did you mean: " + ", ".join(sorted(set(suggestions))) + "?"
        return mcp_error(msg, error_code="MOVEMENT_UNMAPPABLE")
    if not blocks:
        return mcp_error("No valid exercises after parsing 'exercises'", error_code="MISSING_ARG")

    archetype = (args.get("archetype") or "custom").strip().lower()
    target_date = args.get("target_date") or datetime.now(timezone.utc).date().isoformat()
    total_sets = sum(len(b.sets) for b in blocks)

    warnings: list[str] = []
    try:
        from routine_generator import _load_json
        ceiling = (_load_json("training_week.json") or {}).get("session_set_ceiling")
        if ceiling and total_sets > int(ceiling):
            warnings.append(
                f"total_sets {total_sets} exceeds session_set_ceiling {ceiling}; "
                "allowed for a custom session, just flagging.")
    except Exception:
        pass

    ir = RoutineSpec(
        routine_id=_new_routine_id(),
        target_date=target_date,
        archetype=archetype,
        variant="ideal",
        title=(args.get("title") or f"{archetype.title()} — {target_date}")[:60],
        notes=(args.get("notes") or ""),
        version=1,
        created_at=_now_iso(),
        created_by="chat",
        source_action="draft_custom",
        status="draft",
        exercises=blocks,
        budget_used={},
        inputs_snapshot={"authored": "custom", "total_sets": total_sets,
                         "exercise_count": len(blocks)},
        rationale=[
            "custom-authored via chat (action=draft_custom)",
            "loads + sets are user-specified; the generator did NOT compute them",
            f"{len(blocks)} exercises, {total_sets} total sets",
        ],
        caps={},
    )
    put_versioned(ir)
    return {
        "status": "drafted_custom",
        "routine_id": ir.routine_id,
        "target_date": target_date,
        "archetype": archetype,
        "exercise_count": len(blocks),
        "total_sets": total_sets,
        "warnings": warnings,
        "note": "Run action=dry_run with this routine_id to preview the exact Hevy "
                "body, then action=commit to push. Commit requires explicit routine_id.",
    }


def _action_dry_run(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error("dry_run requires routine_id", error_code="MISSING_ARG")
    from hevy_compiler import to_create_body
    from routine_repo import get_current
    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    body = to_create_body(ir, _make_resolver())
    return {
        "status": "preview",
        "routine_id": routine_id,
        "wire_body": body,
        "rationale": ir.rationale,
    }


def _action_commit(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error(
            "commit requires explicit routine_id — no inferred intent",
            error_code="MISSING_ARG",
        )
    from hevy_compiler import from_hevy_response, to_create_body, to_update_body
    import hevy_write_client as wc
    from routine_repo import get_current, put_versioned, upsert_id_map
    from routine_title import build_title_context, format_why_note
    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    try:
        resolve = _make_resolver()
        title_ctx = build_title_context(ir)
        why = format_why_note(ir)
        if ir.hevy_routine_id:
            body = to_update_body(ir, resolve,
                                  title_context=title_ctx, why_note=why)
            resp = wc.update_routine_with_guard(
                ir.hevy_routine_id, body, expected_updated_at=ir.hevy_updated_at,
            )
        else:
            body = to_create_body(ir, resolve,
                                  title_context=title_ctx, why_note=why)
            resp = wc.create_routine(body)
        parsed = from_hevy_response(resp)
        ir.hevy_routine_id = parsed["hevy_routine_id"] or ir.hevy_routine_id
        ir.hevy_updated_at = parsed["updated_at"]
        ir.hevy_pushed_at = _ts_now()
        ir.status = "active"
        ir.parent_version = ir.version
        ir.version += 1
        put_versioned(ir)
        if ir.hevy_routine_id:
            try:
                upsert_id_map(ir.routine_id, ir.hevy_routine_id)
            except Exception:
                logger.info(f"id-map already present for routine {ir.routine_id}")
        return {
            "status": "committed",
            "routine_id": ir.routine_id,
            "hevy_routine_id": ir.hevy_routine_id,
            "version": ir.version,
        }
    except wc.HevyOrphanCreated as e:
        # Hevy returned 4xx but created the routine anyway. Link the id locally
        # so future updates target it (instead of POSTing a third copy).
        ir.hevy_routine_id = e.hevy_routine_id
        ir.hevy_updated_at = e.hevy_updated_at
        ir.hevy_pushed_at = _ts_now()
        ir.status = "active"
        ir.parent_version = ir.version
        ir.version += 1
        put_versioned(ir)
        try:
            upsert_id_map(ir.routine_id, ir.hevy_routine_id)
        except Exception:
            pass
        return mcp_error(
            f"Hevy returned {e.status} but created routine {e.hevy_routine_id}. "
            f"Local IR linked to it so future commits target the same routine. "
            f"Inspect in the Hevy app and delete or fix as needed. "
            f"Original Hevy body: {e.body[:200]}",
            error_code="HEVY_ORPHAN_CREATED",
        )
    except wc.HevyConflict as e:
        return mcp_error(
            f"Hevy in-app edit detected — refusing to clobber. {e}",
            error_code="HEVY_CONFLICT",
        )
    except wc.HevyAuthError as e:
        return mcp_error(f"Hevy auth failed (rotate life-platform/hevy-write?): {e}",
                         error_code="HEVY_AUTH")
    except wc.HevyRetryable as e:
        return mcp_error(f"Hevy transient error after retries: {e}",
                         error_code="HEVY_RETRYABLE")


def _action_list(args: dict[str, Any]) -> dict[str, Any]:
    from routine_repo import list_by_date_range
    start = args.get("start_date") or args.get("date") or "2026-05-31"
    end = args.get("end_date") or args.get("date") or start
    items = list_by_date_range(start, end, limit=int(args.get("limit") or 50))
    return {
        "status": "ok",
        "count": len(items),
        "routines": [
            {
                "routine_id": ir.routine_id,
                "target_date": ir.target_date,
                "archetype": ir.archetype,
                "variant": ir.variant,
                "status": ir.status,
                "hevy_routine_id": ir.hevy_routine_id,
                "version": ir.version,
            }
            for ir in items
        ],
    }


def _action_get(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error("get requires routine_id", error_code="MISSING_ARG")
    from routine_ir import serialize
    from routine_repo import get_current
    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    return {"status": "ok", "routine": serialize(ir)}


def _action_archive(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error(
            "archive requires explicit routine_id — no inferred intent",
            error_code="MISSING_ARG",
        )
    from hevy_compiler import to_update_body
    from hevy_template_cache import resolve_movement
    import hevy_write_client as wc
    from routine_repo import get_current, put_versioned
    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    if not ir.hevy_routine_id:
        ir.status = "archived"
        ir.parent_version = ir.version
        ir.version += 1
        put_versioned(ir)
        return {"status": "archived_local_only", "routine_id": ir.routine_id,
                "note": "Routine was never pushed to Hevy; nothing to rename."}
    # Ensure an Archive folder, then rename + folder-move in Hevy. Hevy has no DELETE.
    folders = wc.list_folders()
    archive_folder_id = None
    for f in folders.get("routine_folders") or folders.get("folders") or []:
        if (f.get("title") or "").lower() == "archive":
            archive_folder_id = f.get("id")
            break
    if not archive_folder_id:
        created = wc.create_folder("Archive")
        new_folder = created.get("routine_folder") or created
        archive_folder_id = new_folder.get("id")
    ir.title = f"[archived {datetime.now(timezone.utc).date().isoformat()}] {ir.title or ir.archetype}"
    ir.hevy_folder_id = archive_folder_id
    body = to_update_body(ir, resolve_movement)
    try:
        wc.update_routine_with_guard(ir.hevy_routine_id, body,
                                     expected_updated_at=ir.hevy_updated_at)
    except wc.HevyConflict as e:
        return mcp_error(f"Hevy in-app edit detected on archive — refusing to clobber. {e}",
                         error_code="HEVY_CONFLICT")
    ir.status = "archived"
    ir.parent_version = ir.version
    ir.version += 1
    put_versioned(ir)
    return {"status": "archived", "routine_id": ir.routine_id,
            "archive_folder_id": archive_folder_id}


def _action_floor(args: dict[str, Any]) -> dict[str, Any]:
    from routine_generator import generate_routines
    from routine_repo import put_versioned
    inputs = _generator_inputs(args)
    routines = generate_routines(inputs)
    floor = next((r for r in routines if r.variant == "floor"), None)
    if not floor:
        return mcp_error("Generator did not produce a floor variant", error_code="INTERNAL")
    put_versioned(floor)
    return {"status": "drafted_floor", "routine_id": floor.routine_id,
            "target_date": floor.target_date}


def _action_re_entry(args: dict[str, Any]) -> dict[str, Any]:
    from routine_generator import GeneratorInputs, generate_routines
    from routine_repo import put_versioned
    base = _generator_inputs(args)
    inputs = GeneratorInputs(
        target_date=base.target_date,
        recovery_tier=base.recovery_tier,
        acwr_flag=base.acwr_flag,
        volume_7d=base.volume_7d,
        z2_minutes_7d=base.z2_minutes_7d,
        days_since_last_workout=max(base.days_since_last_workout, 7),
        history_last_dates=base.history_last_dates,
        add_load_enabled=False,
    )
    routines = generate_routines(inputs)
    re_entry = next((r for r in routines if r.variant == "re_entry"), None)
    if not re_entry:
        return mcp_error("Generator did not produce a re_entry variant",
                         error_code="INTERNAL")
    put_versioned(re_entry)
    return {"status": "drafted_re_entry", "routine_id": re_entry.routine_id,
            "target_date": re_entry.target_date}


def _action_adherence(args: dict[str, Any]) -> dict[str, Any]:
    routine_id = args.get("routine_id")
    if not routine_id:
        return mcp_error("adherence requires routine_id", error_code="MISSING_ARG")
    from adherence_calc import calculate_adherence
    import hevy_write_client as wc
    from routine_repo import get_current
    ir = get_current(routine_id)
    if not ir:
        return mcp_error(f"routine_id={routine_id} not found", error_code="NOT_FOUND")
    workouts = wc.get_workouts(page=1, page_size=10).get("workouts") or []
    performed: dict[str, Any] = {}
    for w in workouts:
        if (w.get("start_time") or "")[:10] == ir.target_date:
            performed = w
            break
    if not performed:
        return {"status": "no_workout_for_date", "routine_id": routine_id,
                "target_date": ir.target_date}
    return {"status": "ok",
            "routine_id": routine_id,
            "adherence": calculate_adherence(ir, performed)}


_DISPATCH = {
    "draft": _action_draft,
    "draft_custom": _action_draft_custom,
    "dry_run": _action_dry_run,
    "commit": _action_commit,
    "list": _action_list,
    "get": _action_get,
    "archive": _action_archive,
    "floor": _action_floor,
    "re_entry": _action_re_entry,
    "adherence": _action_adherence,
}


def tool_manage_hevy_routine(args: dict[str, Any] | None = None) -> dict[str, Any]:
    """Single fat tool for the Hevy routine write-loop. See module docstring."""
    args = args or {}
    action = (args.get("action") or "").strip().lower()
    if action not in _VALID_ACTIONS:
        return mcp_error(
            f"action must be one of: {sorted(_VALID_ACTIONS)}",
            error_code="INVALID_ACTION",
        )
    return _DISPATCH[action](args)
