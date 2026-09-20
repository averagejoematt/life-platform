#!/usr/bin/env python3
"""
deploy/hevy_recreate_template.py — retire-and-recreate the corrupted Hevy
"Calf Press on Leg Press Machine" custom exercise template (#3770).

WHY

Live `GET /v1/exercise_templates/70b39605-52c0-4b79-855c-e26ea10440da` (checked
2026-09-13 and again on 2026-09-20) still reads `primary_muscle_group=shoulders`
— the owner's in-app correction never reached the Hevy API. `hevy_write_client.py`
exposes create/list/get for exercise templates but no template PUT, so the
muscle group on an EXISTING template can never be fixed in place. Owner ruling
2026-09-20: RETIRE-AND-RECREATE.

WHAT THIS SCRIPT DOES (--apply)

  1. POSTs a brand-new custom exercise template via the existing write client
     (`training.hevy_write_client.create_template` — the same call
     `mcp/tools_hevy_routine.py::_create_template_for` uses for every OTHER
     `create_missing` template), title EXACTLY "Calf Press on Leg Press
     Machine", `muscle_group="calves"` explicit (never guessed — #3770/#3718's
     `_explicit_muscle_group` would refuse an implicit one anyway).
  2. Resolves the NEW template's id by walking the live catalogue for an exact
     title match, SKIPPING the retired old id
     (`lambdas/training/template_muscle_overrides.RETIRED_TEMPLATE_IDS`) — the
     new and old templates deliberately share a title, so an id-blind title
     walk could otherwise resolve straight back to the corrupted template.
  3. Reads the new template back by id (`GET /v1/exercise_templates/<id>`) and
     asserts `primary_muscle_group == "calves"` — loud failure if not.
  4. Rebuilds `config/hevy_template_index.json` (#3764) from the live
     catalogue so name resolution (`mcp/hevy_resolution.py`) picks up the new
     id immediately rather than waiting for the daily rebuild cron.
  5. Prints the new id. The OLD id's alias to Calves for every set already
     logged against it lives in `lambdas/training/template_muscle_overrides.py`
     (committed code, not runtime state) — this script does not touch it.

Dry-run (default): prints the planned POST body and makes NO network call.
`--apply` performs the live create + resolve + verify + index rebuild.

  python3 deploy/hevy_recreate_template.py              # dry-run
  python3 deploy/hevy_recreate_template.py --apply       # live write

Per lane policy this script is never invoked from the authoring worktree — the
driver runs `--apply`, attended, after merge (Hevy writes are out of scope for
a lane).
"""

from __future__ import annotations

import argparse
import json
import sys
import time

sys.path.insert(0, "lambdas")

#: The corrupted template this replaces (#3770). Never referenced as a create target —
#: only as the id every resolver below must refuse to resolve TO.
OLD_TEMPLATE_ID = "70b39605-52c0-4b79-855c-e26ea10440da"

#: Deliberately identical to the corrupted template's title — Hevy's create-side API
#: has no uniqueness constraint on custom-exercise titles (verified: the account already
#: holds duplicate-titled built-ins), so this is safe, and an identical title is what
#: keeps every existing routine reference and reader-facing surface unchanged.
NEW_TITLE = "Calf Press on Leg Press Machine"
MUSCLE_GROUP = "calves"
# GET-side `type` on the corrupted template reads "weight_reps" (live-confirmed
# 2026-09-13); the create-side field name for the same enum is `exercise_type`.
EXERCISE_TYPE = "weight_reps"
# Inferred from the title ("... Leg Press Machine") — the corrupted template's GET
# response wasn't captured with its `equipment` field, so this is the create-side
# equivalent of the equipment _infer_equipment() would have picked for this title.
EQUIPMENT_CATEGORY = "machine"


def planned_body() -> dict:
    """The exact POST body `--apply` sends to `create_template`."""
    return {
        "exercise": {
            "title": NEW_TITLE,
            "muscle_group": MUSCLE_GROUP,
            "exercise_type": EXERCISE_TYPE,
            "equipment_category": EQUIPMENT_CATEGORY,
        }
    }


def find_new_id(list_templates_fn, title: str, retired_ids, normalize_title_fn, max_pages: int = 30) -> str | None:
    """Exact normalized-title match against the live catalogue, skipping retired ids.

    Same walk shape as `mcp/hevy_resolution.py::_live_template_id_by_title`, with one
    addition: an id in `retired_ids` is never a candidate, so a duplicate title (old +
    new deliberately share NEW_TITLE) cannot resolve back to the corrupted template.
    """
    target = normalize_title_fn(title)
    page = 1
    while page <= max_pages:
        resp = list_templates_fn(page=page, page_size=100)
        items = resp.get("exercise_templates") or resp.get("templates") or []
        if not items:
            return None
        for t in items:
            tid = t.get("id")
            if not tid or str(tid) in retired_ids:
                continue
            if normalize_title_fn(t.get("title")) == target:
                return str(tid)
        if len(items) < 100:
            return None
        page += 1
    return None


def run(apply: bool) -> dict:
    from training.template_muscle_overrides import RETIRED_TEMPLATE_IDS

    body = planned_body()
    if not apply:
        return {
            "dry_run": True,
            "old_template_id": OLD_TEMPLATE_ID,
            "planned_create_body": body,
            "note": "no network call made — pass --apply to create the replacement template",
        }

    from training import hevy_template_cache as cache, hevy_template_index as idx, hevy_write_client as wc

    create_error = None
    try:
        wc.create_template(body)
    except Exception as e:  # noqa: BLE001 — Hevy's create response may be a bare id string, not JSON
        create_error = f"{type(e).__name__}: {e}"

    new_id = None
    for attempt in range(4):
        new_id = find_new_id(wc.list_templates, NEW_TITLE, RETIRED_TEMPLATE_IDS, idx.normalize_title)
        if new_id:
            break
        time.sleep(min(0.5 * (attempt + 1), 1.5))
    if not new_id:
        raise RuntimeError(
            "could not resolve the new template id by title after create" + (f" (create error: {create_error})" if create_error else "")
        )

    fetched = wc.get_template(new_id)
    template_obj = fetched if "primary_muscle_group" in fetched else (fetched.get("exercise_template") or fetched.get("exercise") or {})
    actual_group = (template_obj.get("primary_muscle_group") or "").strip().lower()
    if actual_group != MUSCLE_GROUP:
        raise RuntimeError(f"new template {new_id} came back with primary_muscle_group={actual_group!r}, expected {MUSCLE_GROUP!r}")

    index_result = idx.rebuild(wc.list_templates, cache._write_s3_json, cache._read_s3_json)

    return {
        "dry_run": False,
        "old_template_id": OLD_TEMPLATE_ID,
        "new_template_id": new_id,
        "primary_muscle_group": actual_group,
        "index_rebuild": index_result,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="perform the live Hevy create + verify + index rebuild (default: dry-run)")
    args = parser.parse_args()
    result = run(args.apply)
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
