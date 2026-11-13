"""kb_entry.py — the kettlebell slot's entry progression (#5774, owner ruling 2026-11-11).

THE RULING

"KETTLEBELL SLOT = KB SWING, entered via [two] exposures of KB DEADLIFT first (the library's progression: kb_deadlift ->
swing)." The charter's concession ledger promises dan_john "carries and kettlebell work weekly"; the slot that keeps it is
`lower_volume.kettlebell_swing` (`program_structure.SESSION_TEMPLATES`, beside the Romanian deadlift — hinge-adjacent,
displacing no anchor). It serves the kettlebell DEADLIFT until he has logged it twice, then the swing.

THE COUNT IS MEASURED. `exposures` counts the distinct Pacific days of the Hevy record (the rows the session sequence
already reads, since the program's block start) that log a set under the entry's template on or after `COUNT_FROM`.
Hevy has no Kettlebell Deadlift template, so the entry logs under the closest real template no catalog key holds, Sumo
Deadlift (`ENTRY_TEMPLATE_ID`, catalog `kettlebell_deadlift` — a floor-start hinge, bell between the feet; Deadlift
(Dumbbell) is catalogued already and one template id is catalogued once, #4169). He has never logged it; `COUNT_FROM`
(the ruling's day) still bounds the count, so no earlier session could ever be read as an entry exposure. An unread
record (None) serves the entry: the count is never assumed.

The novel-again caps (owner ruling OD1: RPE <= 7, reps <= 8 for exposures 1-3): the slot's reps are 6-8 (the lower_volume
template, `program_structure`) and the RPE cap is named on the slot's rationale line (`note`); the swing, last logged
more than 90 days ago, is also capped by the existing `layoff_tiers.exposure_caps`.

Pure: no I/O, no clock.
"""

from __future__ import annotations

from typing import Any

ISSUE = "#5774"
RULING = "owner ruling 2026-11-11 (#5774): the kettlebell slot is the KB swing, entered through the KB deadlift (logged twice first)"
SLOT_ID = "lower_volume.kettlebell_swing"
TARGET = "kettlebell_swing"
ENTRY = "kettlebell_deadlift"
ENTRY_EXPOSURES = 2
ENTRY_TEMPLATE_ID = "D20D7BBE"  # Hevy 'Sumo Deadlift' — Hevy holds no Kettlebell Deadlift template (index of 2026-11-11)
ENTRY_TITLE = "Sumo Deadlift"
COUNT_FROM = "2026-11-11"
CAP = "novel-again: RPE 7 max, 6-8 reps for exposures 1-3 (owner ruling OD1)"


def _logged(ex: dict[str, Any], template_ids: tuple[str, ...] = (ENTRY_TEMPLATE_ID,)) -> bool:
    tid = str(ex.get("template_id") or "").upper()
    if (tid and tid not in template_ids) or (not tid and str(ex.get("name") or ex.get("title") or "") != ENTRY_TITLE):
        return False  # the template id decides; the title only when the row carries none
    return any(int(s.get("reps") or 0) > 0 or float(s.get("weight_kg") or 0) > 0 for s in ex.get("sets") or [])


def exposures(
    block_workouts: list[dict[str, Any]] | None, before_day: str | None, template_ids: tuple[str, ...] = (ENTRY_TEMPLATE_ID,)
) -> int | None:
    """Distinct days on/after `COUNT_FROM` and before `before_day` that log a set under the entry's template; None when
    the record was not read. `template_ids` (#5861 FIX3, live only): also the owner's custom KB template when he sets one."""
    if block_workouts is None:
        return None
    days = {
        str(w.get("date") or "")[:10]
        for w in block_workouts
        if not w.get("tombstone")
        and COUNT_FROM <= str(w.get("date") or "")[:10] < str(before_day or "9999-12-31")
        and any(_logged(ex, template_ids) for ex in w.get("exercises") or [])
    }
    return len(days)


def served(n: int | None) -> str:
    """The slot's movement after `n` logged entry exposures: the deadlift until two are logged (or the count is unread)."""
    return TARGET if n is not None and n >= ENTRY_EXPOSURES else ENTRY


def note(n: int | None) -> str:
    """The rationale line for the slot."""
    if n is None:
        return f"kettlebell slot: the KB deadlift (the Hevy record was not read, so its {ENTRY_EXPOSURES} entry exposures are not assumed); {CAP}"
    if n >= ENTRY_EXPOSURES:
        return f"kettlebell slot: the KB swing — {n} KB deadlift exposure(s) logged since {COUNT_FROM} ({RULING}); {CAP}"
    return (
        f"kettlebell slot: the KB deadlift (one kettlebell, logged as Hevy's {ENTRY_TITLE}), exposure {n + 1} of {ENTRY_EXPOSURES} "
        f"before the swing ({RULING}); {CAP}"
    )
