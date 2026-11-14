"""week_floors.py — the week-level exercise-selection floors: a single-leg movement and a carry every program week, and the
kettlebell-weekly report (#5759, block-1 retro #5496).

WHY THIS EXISTS

The block-1 retro graded exercise selection below the fix line: single-leg work and carries were rarely drafted, and the
charter's concession ledger promises the Dan John seat "carries and kettlebell work weekly". This module is the WEEK-LEVEL
check, standalone on purpose: it reads only what a week serves (movement keys, with the slot that serves each) and the
recorded refusals, so the rotation path (`variant_rotation.plan`) calls it today and a later selection engine (the exercise
library epic, which supersedes the #5075 vetted pools) can call it unchanged.

THE RULES

  * `WEEKLY_FAMILY_FLOORS` — every program week serves at least ONE member of each named charter `rotation.pool` family
    (`single_leg_progression`, `carries`), unless a recorded gate excludes every member; then the gate is NAMED (the
    refusal reasons), never silently passed. The count of one is the issue's acceptance; the cadence is the charter's.
  * `kettlebell_weekly` — the week serves a kettlebell movement, or the miss is a stage-1 verdict on the draft: WARN now,
    BLOCK from the earlier of the exercise library's approval or program week 13 (owner ruling 2026-11-11). The verdict
    never edits the draft's movements: the current pools have no kettlebell movement to fill it.

Pure: no I/O, no clock.
"""

from __future__ import annotations

from typing import Any

ISSUE = "#5759"

WEEKLY_FAMILY_FLOORS: dict[str, str] = {
    "single_leg_progression": "#5759 (block-1 retro, #5496): every program week serves at least one single-leg movement",
    "carries": "#5759 (block-1 retro, #5496): every program week serves at least one loaded carry",
}
"""Charter `rotation.pool` families every program WEEK must serve at least one member of (floor = 1)."""

CHARTER_FAMILY_KEYS: dict[str, dict[str, str | None]] = {
    "single_leg_progression": {
        # no logged loaded template by that name files under quadriceps (Single DB Split Squats reads hamstrings)
        "supported split squat": None,
        "reverse lunge": "reverse_lunge_dumbbell",
        "Bulgarian split squat": "bulgarian_split_squat_dumbbell",
    },
    "carries": {"farmer carry": "farmers_walk", "suitcase carry": "suitcase_carry"},
}
"""Each floored family's charter names -> the catalog key that counts as it (None = no catalog template can; the reason is
on the line). A test holds these names equal to the charter's own, so a name the charter adds is never silently ignored."""

KETTLEBELL_PROVENANCE = "charter concession_ledger.dan_john.in_return: 'carries and kettlebell work weekly'"
KETTLEBELL_RULING = "owner ruling 2026-11-11: WARN now; BLOCK from the earlier of exercise-library approval or program week 13"
LIBRARY_BASENAME = "exercise_library.json"
LIBRARY_APPROVED = "approved"

# The earliest day program week 13 can open (block 3, week 1). Derived from the code, not guessed: a program week advances
# only when its session cycle is complete AND >= `session_sequence.WEEK_RULE['floor_days']` (7) Pacific days have passed
# since the previous advance (`session_sequence.ledger`). The live ledger (Hevy record read 2026-11-11) opened week 7 —
# block 2, week 1 — on 2026-11-08 (block 1 = weeks 1-6, block_start 2026-09-24 -> last session 2026-11-06). Six more weeks
# at the 7-day floor: 2026-11-08 + 6 x 7 days = 2026-12-20, and `ledger(completed + one session every day from 2026-11-11)`
# opens week 13 on exactly 2026-12-20 (held by tests/test_rotation_family_floors_5759.py). Missed sessions can only push the
# real week 13 later, so the literal is the EARLIEST date the ruling's "program week 13" leg can mean.
KETTLEBELL_BLOCK_FROM = "2026-12-20"


def family_members(family: str) -> list[str]:
    """The catalog keys that count as `family` (`CHARTER_FAMILY_KEYS`), in the charter's order."""
    return [k for k in (CHARTER_FAMILY_KEYS.get(family) or {}).values() if k]


def _title(key: str, catalog: dict[str, Any]) -> str:
    return str((catalog.get(key) or {}).get("title") or key)


def is_kettlebell(key: str, catalog: dict[str, Any]) -> bool:
    entry = catalog.get(key) or {}
    return entry.get("equipment") == "kettlebell" or "kettlebell" in str(entry.get("title") or key).lower()


def family_floors(served: list[dict[str, Any]], refusals: list[dict[str, str]], catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Per `WEEKLY_FAMILY_FLOORS` family: the week's served members, whether the floor is `met`, and when it is not the
    recorded `gate` (every member's refusal reason, or that nothing in the week hosts the family).

    `served`: what the week serves, one `{"key", "slot_id"?, "role"?}` per movement (only movements actually usable — a
    caller drops one a gate refuses and puts its reason in `refusals`). `refusals`: `{"key", "reason"}` per refused member."""
    out = []
    for family, provenance in WEEKLY_FAMILY_FLOORS.items():
        keys = family_members(family)
        hits = [
            {"slot_id": s.get("slot_id"), "role": s.get("role"), "variant": s["key"], "title": _title(s["key"], catalog)}
            for s in served
            if s["key"] in keys
        ]
        why = list(dict.fromkeys(f"{r['key']}: {r['reason']}" for r in refusals if r["key"] in keys))
        gate = None if hits else ("; ".join(why) or f"nothing in the week hosts a {family} member")
        out.append({"family": family, "floor": 1, "provenance": provenance, "served": hits, "met": bool(hits), "gate": gate})
    return out


def library(path: str | None = None) -> dict[str, Any] | None:
    """The exercise library (`config/exercise_library.json`, the library lane), or None when absent or unreadable."""
    import json

    from common import repo_config

    try:
        with open(path or repo_config.config_path(LIBRARY_BASENAME), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def library_status(path: str | None = None, data: Any = ...) -> str | None:
    """The exercise library's `status`, or None when the file is absent or unreadable — which reads as NOT approved (owner
    ruling 2026-11-11). `data`: an already-read `library()` (#5774 reads the file once for both its rows)."""
    data = library(path) if data is ... else data
    return str(data.get("status")) if isinstance(data, dict) and data.get("status") is not None else None


def kettlebell_enforced(on: str | None, status: str | None) -> str | None:
    """Why a kettlebell miss BLOCKS on day `on`, or None while it only warns: the library is approved, or `on` is on/after
    `KETTLEBELL_BLOCK_FROM` (program week 13). An unknown day never blocks on the date leg."""
    if status == LIBRARY_APPROVED:
        return f"the exercise library is {LIBRARY_APPROVED} (config/{LIBRARY_BASENAME} status)"
    if on and str(on)[:10] >= KETTLEBELL_BLOCK_FROM:
        return f"on/after {KETTLEBELL_BLOCK_FROM}, the earliest start of program week 13"
    return None


def kettlebell_weekly(
    served: list[dict[str, Any]], catalog: dict[str, Any], *, on: str | None = None, status: str | None = None
) -> dict[str, Any]:
    """The week's kettlebell movements, or the miss: `verdict` met | warn | block (owner ruling 2026-11-11 — WARN now,
    BLOCK (stage 1 fails) from the earlier of library approval or program week 13; `kettlebell_enforced`)."""
    hits = [
        {"slot_id": s.get("slot_id"), "variant": s["key"], "title": _title(s["key"], catalog)}
        for s in served
        if is_kettlebell(s["key"], catalog)
    ]
    enforced = None if hits else kettlebell_enforced(on, status)
    verdict = "met" if hits else ("block" if enforced else "warn")
    return {
        "check": "kettlebell_weekly",
        "provenance": KETTLEBELL_PROVENANCE,
        "ruling": KETTLEBELL_RULING,
        "stage": 1,
        "verdict": verdict,
        "blocking": verdict == "block",
        "block_from": KETTLEBELL_BLOCK_FROM,
        "library_status": status,
        "served": hits,
        "met": bool(hits),
        "note": (
            None
            if hits
            else (
                f"no kettlebell movement in this week's drafts — stage 1 FAILS: {enforced}"
                if enforced
                else f"no kettlebell movement in this week's drafts — a warning until {KETTLEBELL_BLOCK_FROM} or library approval"
            )
        ),
    }


def check_week(
    served: list[dict[str, Any]], refusals: list[dict[str, str]], catalog: dict[str, Any], *, on: str | None = None, status: Any = ...
) -> dict[str, Any]:
    """The week-level selection check, for any selection engine: the family floors and the kettlebell verdict on day `on`
    (`status`: the library's, read from config when not given)."""
    lib = library_status() if status is ... else status
    return {
        "issue": ISSUE,
        "family_floors": family_floors(served, refusals, catalog),
        "kettlebell": kettlebell_weekly(served, catalog, on=on, status=lib),
    }


def lines(check: dict[str, Any]) -> list[str]:
    """The draft rationale lines for one `check_week` result."""
    out = [
        (
            f"weekly floor met: {f['family']} — " + ", ".join(f"{s['title']} [{s['slot_id']}]" for s in f["served"])
            if f["met"]
            else f"weekly floor NOT met: {f['family']} — excluded by a recorded gate: {f['gate']}"
        )
        for f in check["family_floors"]
    ]
    kb = check["kettlebell"]
    out.append(
        "kettlebell weekly: " + ", ".join(s["title"] for s in kb["served"])
        if kb["met"]
        else f"kettlebell weekly {'BLOCKED' if kb['blocking'] else 'NOT met (warning)'}: {kb['note']}"
    )
    return out


# ── free-weight compound floor (owner ruling 2026-11-12 on #5857, board recommendation 4) ─────────────────────────────
# Every program week serves at least one FREE-WEIGHT COMPOUND for each of press, pull, squat and hinge; anchors count. It
# reads the exercise library's own `job` / `pattern` / `resistance_profile` (rubric v2), never a second classifier.
# group -> the audited primary targets a member must train (a rear-delt row is a pull pattern but not the back's pull)
FREE_WEIGHT_TARGETS: dict[str, tuple[str, ...]] = {
    "press": ("chest", "front_delts", "triceps"),
    "pull": ("back",),
    "squat": ("quadriceps", "glutes", "adductors"),
    "hinge": ("hamstrings", "glutes"),
}
FREE_WEIGHT_GROUPS: dict[str, tuple[str, ...]] = {
    "press": ("horizontal_press", "vertical_press", "press"),
    "pull": ("horizontal_pull", "vertical_pull"),
    "squat": ("squat",),
    "hinge": ("hinge",),
}


def _library_entry(key: str, lib: dict[str, Any], catalog: dict[str, Any]) -> dict[str, Any] | None:
    mv = (lib or {}).get("movements") or {}
    if key in mv:
        return mv[key]
    tid = str((catalog.get(key) or {}).get("hevy_template_id_hint") or "").upper()
    return next((e for e in mv.values() if tid and str(e.get("template_id") or "").upper() == tid), None)


def free_weight_compounds(served: list[dict[str, Any]], lib: dict[str, Any] | None, catalog: dict[str, Any]) -> dict[str, list[str]]:
    """Group -> the week's served free-weight compounds in it (library titles). Pure."""
    out: dict[str, list[str]] = {g: [] for g in FREE_WEIGHT_GROUPS}
    for s in served:
        e = _library_entry(str(s.get("key") or ""), lib or {}, catalog)
        if not e or e.get("job") != "compound" or e.get("resistance_profile") != "free_weight":
            continue
        for group, patterns in FREE_WEIGHT_GROUPS.items():
            target = str((e.get("target") or {}).get("primary") or "")
            if e.get("pattern") in patterns and target in FREE_WEIGHT_TARGETS[group] and str(e.get("title")) not in out[group]:
                out[group].append(str(e.get("title")))
    return out
