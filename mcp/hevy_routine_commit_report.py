"""
hevy_routine_commit_report.py — what a Hevy routine commit must tell its caller.

Extracted from `tools_hevy_routine.py` by #3670, which is also the reason the
module exists at all. Both defects that issue fixed had the same shape: the
commit path did something the caller could not see, and returned
`{"status": "committed"}` anyway. This module owns the two facts that used to be
swallowed —

  * **where the routine was filed.** `ensure_folder` (plus the archetype →
    folder-title map it routes with) returns `(folder_id, miss_reason)`: exactly
    one of the two is set. Folder I/O is deliberately fail-soft, because a folder
    outage must not stop a routine reaching Hevy — but fail-soft is not the same
    as silent, and that is exactly where the distinction was lost. The old form
    logged a CloudWatch warning nobody read, returned a bare `None`, and every
    routine was created in the Hevy account root for months. Callers MUST put
    `miss_reason` in their own result — see `_action_commit`'s `"folder"` key,
    which reads `"unfoldered: <reason>"`.
  * **which of the caller's arguments it could not honour.**
    `discarded_commit_title_warnings` names a `title` / `force_title` passed to
    `commit`, which is read only at draft time and was previously dropped without
    a word while the call still reported success.

Nothing here raises. Everything here is designed to be *reported*.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Per-type Hevy folder routing (ADR-067 sibling). Mirrors the repo's
# docs/coaching/routines/<type>/ layout: the Hevy folder is the session TYPE,
# the phase lives in the title (Foundation - Push - 1 - 1). Hevy folders are a
# FLAT list (no nesting) and folder_id is CREATE-ONLY (PUT omits it), so this is
# applied once, on the create branch of commit. Edit the map to re-name folders.
FOLDER_BY_ARCHETYPE = {
    "push": "Push",
    "pull": "Pull",
    "legs": "Legs",
    "lower": "Legs",
    "upper": "Upper",
    "engine": "Engine",
    "full_body": "Full Body",
    "conditioning": "Engine",
}

# What commit reports for the "folder" key on the UPDATE branch. Hevy's folder_id is
# create-only (to_update_body omits it — hevy_compiler.py), so an existing routine's
# folder cannot be changed by the API at all. Saying so beats an absent key.
UPDATE_FOLDER_NOTE = "unchanged — folder_id is create-only in Hevy; move it in the app"


# Arguments that are honoured at DRAFT time only and are inert on commit (#3670).
DRAFT_ONLY_COMMIT_ARGS = ("title", "force_title")


def folder_title_for(ir: Any) -> str:
    arch = (getattr(ir, "archetype", "") or "custom").strip().lower()
    return FOLDER_BY_ARCHETYPE.get(arch, arch.title() or "Custom")


def ensure_folder(title: str) -> tuple[str | None, str | None]:
    """Find-or-create a Hevy routine folder by title.

    Returns ``(folder_id, miss_reason)``: exactly one of the two is set. Never
    raises — but never lies either: every failure path names itself in
    `miss_reason` so the caller can put it in its own result (#3670).

    Hevy folders are a flat list; folder_id is set-on-create only.
    """
    from training import hevy_write_client as wc

    try:
        folders = wc.list_folders()
    except Exception as e:  # noqa: BLE001 — never block a commit on folder I/O
        reason = f"list_folders failed ({type(e).__name__}: {e})"
        logger.warning(f"{reason}; committing without folder")
        return None, reason
    for f in folders.get("routine_folders") or folders.get("folders") or []:
        if (f.get("title") or "").strip().lower() == title.strip().lower():
            return f.get("id"), None
    try:
        created = wc.create_folder(title)
        new_folder = created.get("routine_folder") or created
    except Exception as e:  # noqa: BLE001
        reason = f"create_folder({title!r}) failed ({type(e).__name__}: {e})"
        logger.warning(f"{reason}; committing without folder")
        return None, reason
    folder_id = new_folder.get("id")
    if not folder_id:
        reason = f"create_folder({title!r}) returned no id (payload keys: {sorted(created)})"
        logger.warning(f"{reason}; committing without folder")
        return None, reason
    return folder_id, None


def discarded_commit_title_warnings(args: dict[str, Any], ir: Any) -> list[str]:
    """Name any draft-time-only argument passed to commit, instead of dropping it.

    `force_title` and `title` are read at draft_custom time and persisted onto
    `ir.inputs_snapshot`; `_resolve_title_inputs` reads the snapshot and never the
    commit args. Passing either on commit was therefore a silent no-op that still
    returned `{"status": "committed"}` — the caller believed a rename landed that
    never did (#3670). Returning a warning is deliberately non-fatal: the commit
    itself is valid, only the caller's expectation about the title is wrong.
    """
    supplied = [k for k in DRAFT_ONLY_COMMIT_ARGS if args.get(k) not in (None, "")]
    if not supplied:
        return []
    forced = bool((getattr(ir, "inputs_snapshot", None) or {}).get("force_title"))
    return [
        f"Ignored {'/'.join(supplied)} on commit: both are DRAFT-time arguments, read only from "
        f"the routine's draft snapshot (force_title={forced} there). The title was rendered from "
        f"that snapshot, not from this call. To force a title, re-draft with "
        f"draft_custom(force_title=true, title=...) then dry_run, then commit."
    ]
