"""
training_notes_keys.py — the key scheme of the derived note-signal layer.

Split out of training_notes.py (#3918): the head key, the archive key's prefix, and the
helpers that read an occurrence back off a stored sk are one cohesive thing, and every
reader of the partition (the writer, the MCP tool, the health check, the backfill) needs
them without needing the extractor. No I/O, no model, no boto3 — pure string work over
keys, which is why it is unit-testable everywhere the extractor is.

The rationale for each choice is below; the archive key's own rationale stays next to
`prior_extraction_sk` in training_notes.py, which is where the content digest is built.
"""

from __future__ import annotations

# ── The archive key (#3816) ───────────────────────────────────────────────────
# `ARCHIVE#` is a PREFIX, not a suffix on the head key: every reader of this partition
# scopes by `DATE#`, and "ARCHIVE#" sorts BEFORE "DATE#", so archived rows fall outside
# every reader's range by key shape rather than by a filter each has to remember.
# Archived rows also carry `record_kind: prior_extraction` so a reader that DOES widen
# its range has a positive attribute to exclude on.
ARCHIVE_PREFIX = "ARCHIVE#"
RECORD_KIND_PRIOR = "prior_extraction"


def normalize_exercise_key(exercise: dict) -> tuple[str, str]:
    """(template_id, display_name) for an exercise block. Hevy template_id is stable
    across sessions (hex OR uuid for custom exercises — both kept verbatim)."""
    tid = exercise.get("template_id") or ""
    name = exercise.get("name") or exercise.get("title") or exercise.get("exercise_name") or ""
    return str(tid), str(name)


# ──────────────────────────────────────────────────────────────────────────────
# The head key: one per (workout, exercise template, OCCURRENCE)  (#3918)
#
# The key was `DATE#<d>#WORKOUT#<id>` inside the per-template partition — one key per
# (workout, template) — so a workout that logs the SAME template TWICE with two
# different notes had both notes land on ONE key. Measured live 2026-09-19: 2026-06-23
# and 2026-09-10, both Treadmill. #3816/#3899 stopped the second write DESTROYING the
# first (it versions instead), but the two notes were still not separately addressable
# and every pass re-versioned them against each other.
#
# The occurrence suffix is the 0-based ordinal of that exercise among the appearances of
# ITS TEMPLATE in the workout's exercise list — counted over ALL appearances, noted or
# not. Counting only the noted ones would be cheaper and wrong: adding a note to the
# first Treadmill block later would silently RE-KEY the second block's existing record.
#
# READ COMPAT, no rewrite: a row written under the old scheme (no suffix) READS as
# occurrence 0 (`occurrence_from_sk`), and the writer looks for it at its legacy key
# before deciding whether anything changed — so the dominant path (an unchanged
# re-extraction over history) still writes NOTHING and mints no duplicate.
# `deploy/backfill_training_notes.py --migrate` is the durable re-key.
# ──────────────────────────────────────────────────────────────────────────────
def workout_id_from_uid(workout_uid) -> str:
    """`hevy:e5c2f877` → `e5c2f877`. The id the head key carries."""
    return str(workout_uid).split(":")[-1] if workout_uid else ""


def head_sk(date, workout_id, occurrence: int = 0) -> str:
    """The current head key: `DATE#<d>#WORKOUT#<id>#<occurrence>`."""
    return f"DATE#{date}#WORKOUT#{workout_id}#{int(occurrence)}"


def legacy_head_sk(date, workout_id) -> str:
    """The pre-#3918 head key: `DATE#<d>#WORKOUT#<id>` (reads as occurrence 0)."""
    return f"DATE#{date}#WORKOUT#{workout_id}"


def _head_parts(sk) -> list:
    """Head-key tokens, a `#CORRECTION` overlay suffix stripped; [] when not a head key."""
    parts = str(sk or "").split("#")
    if parts and parts[-1] == "CORRECTION":
        parts = parts[:-1]
    if len(parts) >= 4 and parts[0] == "DATE" and parts[2] == "WORKOUT":
        return parts
    return []


def occurrence_from_sk(sk) -> int:
    """The occurrence a head key names. An old-scheme row (no suffix) IS occurrence 0.

    Position-keyed, not suffix-keyed: an `ARCHIVE#…` row (whose key ends in a content
    digest that can be all-digits) never poses as an occurrence, because its token 0 is
    not `DATE`. Archived rows are outside every reader's key range anyway (#3816) — this
    is the second lock, not the first.
    """
    parts = _head_parts(sk)
    if len(parts) >= 5 and parts[4].isdigit():
        return int(parts[4])
    return 0


def is_legacy_head_sk(sk) -> bool:
    """True for a head key written before #3918 (no occurrence suffix)."""
    parts = _head_parts(sk)
    return bool(parts) and (len(parts) == 4 or not parts[4].isdigit())


def head_sk_base(sk) -> str:
    """`DATE#<d>#WORKOUT#<id>` — the (workout, template) group a head row belongs to."""
    parts = _head_parts(sk)
    return "#".join(parts[:4]) if parts else str(sk or "")


def occurrence_indices(exercises) -> list:
    """Per exercise, its 0-based ordinal among ITS TEMPLATE's appearances in this workout."""
    seen: dict[str, int] = {}
    out = []
    for ex in exercises or []:
        tid, _ = normalize_exercise_key(ex)
        n = seen.get(tid, 0)
        out.append(n)
        seen[tid] = n + 1
    return out


def noted_occurrences_by_template(exercises) -> dict:
    """{template_id: [occurrence, …]} for the exercises in this workout that CARRY a note.

    The occurrence is counted over every appearance of the template, so an unnoted first
    block still consumes index 0 — the key of a noted second block never moves because a
    note was added to (or removed from) the first.
    """
    out: dict[str, list] = {}
    for ex, occ in zip(exercises or [], occurrence_indices(exercises)):
        if not (ex.get("notes") or "").strip():
            continue
        tid, _ = normalize_exercise_key(ex)
        out.setdefault(tid, []).append(occ)
    return out


def workout_id_of_raw_row(row) -> str:
    """The workout id a RAW Hevy row names, from its sk (authoritative) or its uid."""
    parts = str((row or {}).get("sk") or "").split("#")
    if len(parts) >= 4 and parts[0] == "DATE" and parts[2] == "WORKOUT":
        return parts[3]
    return workout_id_from_uid((row or {}).get("workout_uid") or (row or {}).get("source_workout_id") or "")


def dedupe_head_rows(rows) -> dict:
    """{occurrence: row} for the head rows of ONE (workout, template) group.

    A legacy row and a new-scheme row can coexist for occurrence 0 while the re-key is
    pending (the writer versions in place; `--migrate` is the separate, owner-run step).
    The new-scheme row wins; a correction overlay and an archived prior are not head rows
    at all and never enter the map.
    """
    best: dict[int, dict] = {}
    for r in rows or []:
        sk = str(r.get("sk") or "")
        if sk.endswith("#CORRECTION") or r.get("record_kind") == RECORD_KIND_PRIOR:
            continue
        occ = occurrence_from_sk(sk)
        cur = best.get(occ)
        if cur is None or (is_legacy_head_sk(cur.get("sk")) and not is_legacy_head_sk(sk)):
            best[occ] = r
    return best
