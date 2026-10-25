"""cardio_menu.py — the cardio menu with a dose, read from the training charter (#5076, epic #5050).

WHY THIS EXISTS

Before 2026-10-10, 95% of his gym cardio time sat at or below HR zone 1 and no block carried a
level: cardio had a modality but no dose. The owner's 2026-10-18 rulings make gym cardio
deliberate — "from a menu, with level, speed and RPE" (ruling 4), intervals and conditioning open
by RPE / talk test (ruling 7) — and the charter (`config/training_charter.json` `cardio_menu`)
carries the menu. This module is the engine's one reader of it. Every number below is read
through `training_charter.charter_value()`; nothing here restates a menu value.

WHAT IT DECIDES (pure: no I/O, no clock — every date is passed in)

  * the KIND of today's block — `choose_kind`, the weekly placement rule: conditioning
    `conditioning_sessions_per_wk` times a week in `placement.conditioning_order` (one
    tempo-or-hills, then one intervals), every other block easy; never the same hard shape on
    consecutive days; a hard day is followed by an easy one while the week still has room;
  * the MACHINE — the recumbent for a CONDITIONING block the day immediately after a heavy lower
    session (owner ruling 2026-10-25 on #5076, "a": `placement.recumbent_after_session`, read from the
    previous PERFORMED session — `previous_performed`), or on loaded legs (a heavy walking weekend,
    `recent_aerobic.legs_loaded`); an easy block stays on the menu's default, the incline treadmill walk,
    and a conditioning block on fresh legs takes the treadmill when its block allows it (hills), else the
    menu's own machines for it (tempo, intervals: never the treadmill, so the bike by the menu, not the rule);
  * the DOSE — bike: the level (the last ride's, one up on a `cardio_progression.level_verdict`
    raise: same RPE at a higher level) and the speed he rides at it; treadmill: incline % and mph
    from his treadmill history inside the charter's starting band, one step up when the last two
    walks held the dose. The reason for any step is returned as words (`dose["reason"]`);
  * `movement_minutes` — the gym cardio minutes a plan (or a performed day) adds to the daily
    steps/movement goal (`steps.gym_cardio_minutes_count_toward_movement`; #5056 reads it).

The note itself (line 1 grammar, line 2 why) is `training.cardio_note`'s.
"""

from __future__ import annotations

import re
from typing import Any

from training import training_charter

CARDIO_MENU_VERSION = "cardio-menu@1.0.0"

KINDS = ("incline_treadmill_walk", "easy", "tempo", "hills", "intervals")
HARD = ("tempo", "hills", "intervals")
EASY = ("incline_treadmill_walk", "easy")
RECUMBENT = "cycling"
TREADMILL = "treadmill"

# PLATFORM-CHOSEN (ADR-105), not a charter value: the tempo block starts one level above the easy
# level; the RPE band is the prescription, so the level is a starting point he corrects by feel.
TEMPO_LEVEL_STEP = 1
# PLATFORM-CHOSEN: how many consecutive walks at the same dose earn the next step.
HELD_WALKS_FOR_STEP = 2
# PLATFORM-CHOSEN: the treadmill hill shape climbs one incline step every this many minutes, then back.
HILL_STEP_MINUTES = 3
LABELS = {
    "tempo_level_step": "platform-chosen",
    "held_walks_for_step": "platform-chosen",
    "hill_step_minutes": "platform-chosen",
}

_INCLINE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%?\s*incline|incline\s*(?:of|at)?\s*(\d+(?:\.\d+)?)", re.IGNORECASE)
_EASY_WORD = re.compile(r"\bflat\b|\beasy\b|\bsteady\b", re.IGNORECASE)
_TEMPO_WORD = re.compile(r"\btempo\b|\bhard\b", re.IGNORECASE)
# his own word for an easy ride ("flat" is left out: the tempo block is flat too, so "flat" names no kind)
_EASY_ONLY_WORD = re.compile(r"\beasy\b|\bsteady\b|\brecovery\b", re.IGNORECASE)
_M_PER_MI = 1609.344


# ── the charter reads ─────────────────────────────────────────────────────────────────
def menu() -> dict[str, Any]:
    return training_charter.charter_value("cardio_menu", {}) or {}


def block(kind: str) -> dict[str, Any]:
    return (menu().get("blocks") or {}).get(kind) or {}


def default_kind() -> str:
    """The charter's `cardio_menu.default`, read with no fallback: a missing key is a loud error."""
    kind = training_charter.charter_value("cardio_menu.default")
    if not kind:
        raise KeyError("training charter has no cardio_menu.default")
    return str(kind)


def conditioning_per_wk() -> int:
    return int(menu().get("conditioning_sessions_per_wk") or 0)


def placement() -> dict[str, Any]:
    return menu().get("placement") or {}


def own_minutes(kind: str) -> int | None:
    """The minutes the menu itself names for a block (tempo: 'hard flat 40'), before the split's cardio cap."""
    own = block(kind).get("minutes")
    return int(own) if own else None


def cardio_cap_minutes() -> int:
    """The charter's one-cardio-block ceiling (`split.session_minutes.cardio_block_max`)."""
    return int(training_charter.charter_value("split.session_minutes.cardio_block_max", 0) or 0)


def block_minutes(kind: str) -> int:
    """The block's minutes: the menu's own when it names them, else the cap — and NEVER above the cap (#5201).

    The charter's tempo block names 40 min against a 30-min cardio cap; the draft path used to emit the 40 because
    only the routine generator ran `enforce_session_shape`. The clamp lives here, at the one source, so every
    reader of the minutes (the block, its note, the shape) agrees with the cap."""
    cap, own = cardio_cap_minutes(), own_minutes(kind)
    return min(own, cap) if own and cap else (own or cap)


MODALITY_LABEL = {RECUMBENT: "cycling (recumbent)", TREADMILL: TREADMILL}


def prescription(kind: str, machine: str) -> dict[str, Any]:
    """THE cardio prescription for a placed block (#5201): modality, intensity cue and minutes, all from the menu.
    The pick, the block's note and the session shape are each derived from (or checked against) this."""
    return {
        "movement_key": machine,
        "modality": MODALITY_LABEL.get(machine, machine.replace("_", " ")),
        "intensity": effort_words(kind),
        "minutes": block_minutes(kind),
        "kind": kind,
    }


def align_pick(pick: dict[str, Any], kind: str, machine: str) -> dict[str, Any]:
    """`recent_aerobic.cardio_pick` re-stated to the menu's placed block: same modality and intensity cue as the
    prescription. The stage-1 pick is kept whole under `stage1_pick` (nothing silently lost); a pick that already
    agrees is returned unchanged."""
    rx = prescription(kind, machine)
    if pick.get("movement_key") == rx["movement_key"] and pick.get("intensity") == rx["intensity"]:
        return pick
    out = {**pick, "movement_key": rx["movement_key"], "modality": rx["modality"], "intensity": rx["intensity"]}
    out["reason"] = f"{pick.get('reason', '')} -> the menu placed {kind} on the {rx['modality']}".strip()
    out["stage1_pick"] = {k: pick.get(k) for k in ("movement_key", "modality", "intensity", "reason")}
    return out


MACHINE_WORD = {RECUMBENT: "bike", TREADMILL: "treadmill", "elliptical": "elliptical", "rowing_machine": "rower", "air_bike": "air bike"}


def _or_list(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " or " + words[-1]


def off_default(
    kind: str, movement_key: str, legs_loaded: bool | None = None, previous: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Why today's block is not the menu's default (the incline treadmill walk), with the charter key that makes it so;
    None when it is the default. #5076: the live drafts served the bike day after day and said nothing about the walk.

    A conditioning kind the menu never runs on the treadmill (tempo, intervals: `cardio_menu.blocks.<kind>.machines`)
    is on the bike/elliptical/rower BY CHARTER; a hills block on the recumbent the day after a heavy lower session, or
    any block on loaded legs, is the recumbent rule (`cardio_menu.placement.recumbent_after`, ruling 2026-10-25: an easy
    block after a heavy lower session is NOT — easy days stay on the walk); otherwise the block's machine was fixed by
    its author (a chat draft), which no charter line decides. `previous` is `previous_performed`'s answer."""
    if movement_key == TREADMILL and kind in ("incline_treadmill_walk", "run_walk"):
        return None
    machines = list(block(kind).get("machines") or [])
    if kind in HARD and TREADMILL not in machines:
        words = _or_list([MACHINE_WORD.get(m, m.replace("_", " ")) for m in machines])
        return {
            "reason": f"{kind.capitalize()} is conditioning, which the menu runs on the {words}; the incline walk is the easy-day default.",
            "charter": f"cardio_menu.blocks.{kind}.machines",
        }
    if movement_key == TREADMILL:  # hills on the treadmill: the week's conditioning slot
        return {"reason": f"{kind.capitalize()} is the week's conditioning slot.", "charter": "cardio_menu.placement.conditioning_order"}
    if kind in recumbent_after_kinds() and movement_key == RECUMBENT and after_heavy_lower(previous):
        return {
            "reason": f"The recumbent: conditioning the day after {recumbent_after_session()}, in place of the incline walk.",
            "charter": "cardio_menu.placement.recumbent_after",
        }
    if legs_loaded:
        return {
            "reason": "The recumbent after loaded legs, in place of the incline walk.",
            "charter": "cardio_menu.placement.recumbent_after",
        }
    if legs_loaded is None:
        return {"reason": "The recumbent: the walking load was not read.", "charter": None}
    return {"reason": f"The block was drafted on the {MACHINE_WORD.get(movement_key, movement_key)}.", "charter": None}


def rpe_band(kind: str) -> tuple[int, int] | None:
    b = block(kind)
    if b.get("rpe"):
        lo, hi = b["rpe"]
        return int(lo), int(hi)
    if b.get("rpe_hard_minutes") is not None:
        n = int(b["rpe_hard_minutes"])
        return n, n
    return None


def effort_words(kind: str) -> str:
    """'RPE lo–hi, <talk test>' from the menu. Intervals: 'RPE n on the hard minutes'."""
    b = block(kind)
    band = rpe_band(kind)
    talk = b.get("talk_test")
    if kind == "intervals" and band:
        rpe = f"RPE {band[0]} on the hard minutes"
    elif band:
        rpe = f"RPE {band[0]}–{band[1]}"
    else:
        rpe = "by RPE / talk test"
    return f"{rpe}, {talk}" if talk else rpe


def interval_set() -> tuple[int, int, int]:
    """(efforts, work minutes, easy minutes) from the menu's intervals block."""
    b = block("intervals")
    work, easy = b.get("work_easy_minutes") or (0, 0)
    return int(b.get("efforts") or 0), int(work), int(easy)


def lower_names() -> set[str]:
    """The lower sessions' names, lower-cased: every `split.sequence` name that opens with 'lower' (#5069),
    plus the generic archetypes the generator writes ('lower', 'legs')."""
    seq = training_charter.charter_value("split.sequence", []) or []
    return {str(s).strip().lower() for s in seq if str(s).strip().lower().startswith("lower")} | {"lower", "legs"}


def is_lower(archetype: Any) -> bool:
    return str(archetype or "").strip().lower() in lower_names()


def recumbent_after_session() -> str:
    """The `split.sequence` name whose next day puts conditioning on the recumbent (`placement.recumbent_after_session`,
    owner ruling 2026-10-25 on #5076), read with no fallback: a missing key is a loud error."""
    name = placement().get("recumbent_after_session")
    if not name:
        raise KeyError("training charter has no cardio_menu.placement.recumbent_after_session")
    return str(name)


def recumbent_after_kinds() -> tuple[str, ...]:
    """The conditioning kinds the recumbent rule covers (`placement.recumbent_after_kinds`)."""
    return tuple(str(k) for k in placement().get("recumbent_after_kinds") or ())


def previous_performed(advanced_by: dict[str, Any] | None, target_date: str) -> dict[str, Any] | None:
    """{role, date, day_before} of the previous PERFORMED lifting session, or None when it was not read.

    `advanced_by` is `session_sequence.next_session(...)["advanced_by"]` — the last credited Hevy session and the role the
    sequence credited it as (the draft's `inputs_snapshot["calendar"]`, so no second read). `day_before` is True when it
    was performed on the Pacific day before `target_date`: the ruling's "the day immediately after"."""
    from common.pacific_time import shift_day_key

    if not isinstance(advanced_by, dict) or not advanced_by.get("session_role") or not advanced_by.get("date"):
        return None
    day = str(advanced_by["date"])[:10]
    try:
        yesterday = shift_day_key(str(target_date)[:10], -1)
    except (TypeError, ValueError):
        yesterday = None
    return {"role": str(advanced_by["session_role"]), "date": day, "day_before": day == yesterday}


def after_heavy_lower(previous: dict[str, Any] | None) -> bool:
    """True when the previous performed session was the heavy lower session AND it was yesterday (ruling 2026-10-25)."""
    from training.program_structure import role_id

    return bool(previous and previous.get("day_before") and previous.get("role") == role_id(recumbent_after_session()))


def _previous_words(previous: dict[str, Any] | None) -> str:
    if not previous:
        return "the session before was not read"
    return f"the session before was {previous['role']} on {previous['date']}"


# ── placement ─────────────────────────────────────────────────────────────────────────
def kind_of_performed(machine_key: str, note: str | None, served_kind: str | None = None) -> str:
    """The menu kind a performed block was, read from its machine, its own note and the routine it was served.

    His own note wins when it names a kind (intervals / hill / tempo / hard, or easy / steady). Otherwise the
    kind the served routine prescribed for that machine (`served_kind`, `annotate_served`) — #5076: he logs the
    menu's rides with an EMPTY note, so a performed tempo read from the note alone counted as easy, the week's
    conditioning never registered, and every draft re-placed "conditioning 1 of 2" tempo on the bike (the live
    2026-10-21/22/23/24 drafts). With neither, the machine's easy kind."""
    from training import cardio_note

    text = cardio_note.strip_negated(note)  # #5312: "No intervals" never names intervals
    shape = cardio_note.shape_of(text)
    if shape == "intervals":
        return "intervals"
    if shape == "hill":
        return "hills"
    if machine_key != TREADMILL and _TEMPO_WORD.search(text):
        return "tempo"
    if served_kind in KINDS and not _EASY_ONLY_WORD.search(text) and fits_machine(served_kind, machine_key):
        return str(served_kind)
    if machine_key == TREADMILL:
        return "incline_treadmill_walk"
    return "easy"


def fits_machine(kind: str, machine_key: str) -> bool:
    """True when the menu runs `kind` on `machine_key` (a served kind on a machine he swapped to does not carry)."""
    return machine_key in (block(kind).get("machines") or [])


def served_kinds(routines: list[Any] | None) -> dict[str, dict[str, str]]:
    """Hevy routine id -> {machine key: the cardio kind that routine prescribed}. Pure over the routines it is handed.

    The kind is the menu's placement tag (`cardio:<key>:menu:<kind>`) when the block carries one, else the kind its
    composed note names (`cardio_note.composed_kind`); a block with neither is left out (read from his note)."""
    from training import cardio_note

    out: dict[str, dict[str, str]] = {}
    for ir in routines or []:
        hid = str(getattr(ir, "hevy_routine_id", None) or "")
        if not hid:
            continue
        for ex in getattr(ir, "exercises", None) or []:
            key = str(getattr(ex, "movement_key", "") or "")
            if key not in cardio_note.MACHINES:
                continue
            tag = str(getattr(ex, "rationale_tag", "") or "").split(":")
            kind = (
                tag[3] if len(tag) >= 4 and tag[0] == "cardio" and tag[2] == "menu" else cardio_note.composed_kind(getattr(ex, "notes", ""))
            )
            if kind in KINDS:
                out.setdefault(hid, {})[key] = kind
    return out


def annotate_served(
    cardio_index: dict[str, list[dict[str, Any]]] | None, served: dict[str, dict[str, str]], catalog: dict[str, Any] | None
) -> dict[str, list[dict[str, Any]]] | None:
    """A copy of `cardio_index` whose sessions carry `served_kind` — the kind the routine he performed prescribed for
    that machine (`served_kinds`), matched on the session's `hevy_routine_id`. Sessions with no match are unchanged."""
    if not cardio_index or not served:
        return cardio_index
    by_tid = machine_template_ids(catalog)
    out: dict[str, list[dict[str, Any]]] = {}
    for tid, sessions in cardio_index.items():
        key = by_tid.get(tid)
        rows = []
        for s in sessions or []:
            kind = (served.get(str(s.get("hevy_routine_id") or "")) or {}).get(key or "")
            rows.append({**s, "served_kind": kind} if kind else s)
        out[tid] = rows
    return out


def authored_kind(machine_key: str, note: str | None) -> str | None:
    """The kind an author's own note names (intervals / hill / tempo, or flat / easy / steady), or None
    when it names none — an explicit choice in a chat draft stands; an unnamed one is placed by the menu."""
    kind = kind_of_performed(machine_key, note)
    if kind in HARD:
        return kind
    if _EASY_WORD.search(note or ""):
        return "incline_treadmill_walk" if machine_key == TREADMILL else "easy"
    return None


def lifting_days_left(target_date: str) -> int:
    """Lifting days left in the Mon-start week, today included (`split.lifting_days_per_wk`, Mon onward)."""
    from common.pacific_time import parse_day_key

    per_wk = int(training_charter.charter_value("split.lifting_days_per_wk", 0) or 0)
    day = parse_day_key(str(target_date or "")[:10])
    if day is None:
        return per_wk
    return max(1, per_wk - day.weekday())


def choose_kind(
    *,
    target_date: str,
    archetype: Any = "",
    week_kinds: list[str] | None = None,
    prior_day_kind: str | None = None,
    legs_loaded: bool | None = None,
    recovery_band: str | None = None,
    last_tempo_or_hills: str | None = None,
    machines: tuple[str, ...] | None = None,
    days_left: int | None = None,
    run_walk: dict[str, Any] | None = None,
    previous: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """{kind, machine, why} for today's block. `machines` restricts the choice to a block that is already
    on one machine (a chat-drafted bike); None lets the menu pick the machine too.

    `week_kinds` are this week's blocks before today (performed or placed), oldest first.

    `run_walk` (#5090) is `run_onramp.run_day_verdict` for today: once the run gate is open, an eligible day's
    EASY slot becomes the run/walk block (kind `run_walk`, on the treadmill, with its block) — never a conditioning
    slot, and never under a yellow/red recovery band.

    `previous` (`previous_performed`) decides the recumbent (owner ruling 2026-10-25 on #5076, "a"): a conditioning
    block goes on the recumbent only the day immediately after the heavy lower session; an easy block stays on the
    incline walk; on fresh legs a conditioning block takes the treadmill when its block allows it (hills), else the
    menu's first machine for it. The tempo/hills alternation is unchanged. Loaded or unread walking legs keep
    the recumbent for every block (`placement.recumbent_after`'s second clause, unchanged). Today's own role is never
    the trigger."""
    week = list(week_kinds or [])
    order = list(placement().get("conditioning_order") or [])[: conditioning_per_wk()]
    done = [k for k in week if k in HARD]
    needed: list[str] = []
    pool = list(done)
    for slot in order:
        hit = next((k for k in pool if (k in ("tempo", "hills") if slot == "tempo_or_hills" else k == slot)), None)
        if hit:
            pool.remove(hit)
        else:
            needed.append(slot)
    left = lifting_days_left(target_date) if days_left is None else int(days_left)
    heavy = after_heavy_lower(previous)
    walk_why = "the legs carry a heavy walking load" if legs_loaded else ("the walking load was not read" if legs_loaded is None else None)
    bike_conditioning = heavy or walk_why is not None

    kind, why = None, ""
    if recovery_band in ("yellow", "red"):
        why = f"{recovery_band} recovery: easy"
    elif not needed:
        why = "the week's conditioning is done: easy"
    elif prior_day_kind in HARD and left > len(needed):
        why = f"yesterday was {prior_day_kind}: easy today, conditioning later in the week"
    else:
        for slot in needed:
            cand = slot
            if slot == "tempo_or_hills":
                cand = "hills" if last_tempo_or_hills == "tempo" else "tempo"
            if cand == prior_day_kind:  # never the same hard shape on consecutive days
                continue
            kind, why = cand, f"conditioning {len(done) + 1} of {len(order)} this week"
            break
        if kind is None:
            why = f"yesterday was {prior_day_kind}: never the same hard shape twice running"
    if kind is None:
        kind = "easy" if walk_why else default_kind()
    on_recumbent = (kind in HARD and bike_conditioning) or (kind not in HARD and walk_why is not None)
    machine = _machine_for(kind, on_recumbent)
    if machines:
        machine, kind = _fit_machine(kind, machines)
    why += "; " + _machine_why(kind, machine, heavy, walk_why, previous)
    if run_walk and run_walk.get("eligible") and kind not in HARD and recovery_band not in ("yellow", "red") and not machines:
        return {
            "kind": "run_walk",
            "machine": TREADMILL,
            "why": f"{why}; run/walk: {run_walk.get('why')}",
            "needed": needed,
            "block": run_walk.get("block"),
        }
    return {"kind": kind, "machine": machine, "why": why, "needed": needed}


def _machine_why(kind: str, machine: str, heavy: bool, walk_why: str | None, previous: dict[str, Any] | None) -> str:
    """Why the bike or the walk (#5076): the rule that put the block on its machine, in words, with the session before."""
    word = MACHINE_WORD.get(machine, machine.replace("_", " "))
    if machine == RECUMBENT and kind in HARD and heavy:
        return f"the recumbent: conditioning the day after {recumbent_after_session()} ({_previous_words(previous)})"
    if machine == RECUMBENT and walk_why:
        return f"the recumbent: {walk_why}"
    if machine == TREADMILL and kind == "hills":
        return f"hills on the treadmill: fresh legs ({_previous_words(previous)}; the recumbent is for conditioning the day after {recumbent_after_session()})"
    if machine == TREADMILL:
        tail = f", also the day after {recumbent_after_session()}" if heavy else ""
        return f"the incline walk: an easy day stays on the walk{tail} ({_previous_words(previous)})"
    if kind in HARD:
        return f"{kind} on the {word}: the menu's machines for {kind} (cardio_menu.blocks.{kind}.machines), not the recumbent rule"
    return f"the {word}: the block's machine was fixed by its author"


def _machine_for(kind: str, on_recumbent: bool) -> str:
    machines = list(block(kind).get("machines") or [])
    if on_recumbent and RECUMBENT in machines:
        return RECUMBENT
    if not on_recumbent and TREADMILL in machines:
        return TREADMILL
    if machines:
        return machines[0]
    return RECUMBENT


def _fit_machine(kind: str, machines: tuple[str, ...]) -> tuple[str, str]:
    """(machine, kind) when the block's machine is fixed: the kind if the machine carries it, else that machine's easy kind."""
    for m in machines:
        if m in (block(kind).get("machines") or []):
            return m, kind
    m = machines[0]
    return m, ("incline_treadmill_walk" if m == TREADMILL else "easy")


def place_week(
    days: list[dict[str, Any]],
    last_tempo_or_hills: str | None = None,
    run_gate: dict[str, Any] | None = None,
    run_level: int | None = None,
    runs_done: int = 0,
) -> list[dict[str, Any] | None]:
    """The placement over a week of days, each `{date, archetype}` (None archetype = a rest day, no gym
    block) plus optional `legs_loaded`. Returns one `choose_kind` result per day (None on a rest day).
    The same rule `choose_kind` applies to a single draft, iterated so the week can be read whole.

    `run_gate` (#5090, `run_onramp.gate_state`): once open, each day is offered a run/walk at `run_level` through
    `run_onramp.run_day_verdict` — the weekly cap counts `runs_done` plus the runs placed so far.

    #5076: each day's `previous` is the lifting day placed before it in this week (its archetype as the role), or the
    day's own `previous` when it carries one (the first day reads the performed session before the week)."""
    from training import run_onramp
    from training.program_structure import role_id

    out: list[dict[str, Any] | None] = []
    week: list[str] = []
    prior: str | None = None
    runs = int(runs_done)
    lifting = [d for d in days if d.get("archetype")]
    before: dict[str, Any] | None = None
    for d in days:
        if not d.get("archetype"):
            out.append(None)
            prior = None
            continue
        previous = d.get("previous") or (
            previous_performed({"session_role": before["role"], "date": before["date"]}, d["date"]) if before else None
        )
        before = {"role": role_id(d["archetype"]), "date": d["date"]}
        left = len(lifting) - sum(1 for x in out if x)
        pick = choose_kind(
            target_date=d["date"],
            archetype=d["archetype"],
            week_kinds=week,
            prior_day_kind=prior,
            legs_loaded=d.get("legs_loaded", False),
            last_tempo_or_hills=last_tempo_or_hills,
            days_left=left,
            run_walk=run_onramp.run_day_verdict(d["archetype"], gate=run_gate, runs_this_week=runs, level=run_level) if run_gate else None,
            previous=previous,
        )
        runs += pick["kind"] == "run_walk"
        out.append(pick)
        week.append(pick["kind"])
        prior = pick["kind"]
        if pick["kind"] in ("tempo", "hills"):
            last_tempo_or_hills = pick["kind"]
    return out


def history_context(
    cardio_index: dict[str, list[dict[str, Any]]] | None, catalog: dict[str, Any] | None, target_date: str
) -> dict[str, Any]:
    """What the placement reads from his performed cardio (`exercise_history.load_history_indexes()[1]`):
    every cardio machine's sessions, this week's kinds before today, yesterday's last kind and the last
    tempo-or-hills. Pure over the index it is handed."""
    from common.pacific_time import parse_day_key

    from training import cardio_note

    day = parse_day_key(str(target_date or "")[:10])
    week_start = day.fromordinal(day.toordinal() - day.weekday()).isoformat() if day else str(target_date)
    yesterday = day.fromordinal(day.toordinal() - 1).isoformat() if day else str(target_date)
    by_tid = machine_template_ids(catalog)
    by_machine: dict[str, list[dict[str, Any]]] = {k: [] for k in cardio_note.MACHINES}
    for tid, key in by_tid.items():
        by_machine[key] = list((cardio_index or {}).get(tid) or [])
    before = cardio_note.week_kinds(by_machine, "0000-00-00", target_date)
    yday = cardio_note.week_kinds(by_machine, yesterday, target_date)
    return {
        "by_machine": by_machine,
        "week_kinds": cardio_note.week_kinds(by_machine, week_start, target_date),
        "prior_day_kind": yday[-1] if yday else None,
        "last_tempo_or_hills": next((k for k in reversed(before) if k in ("tempo", "hills")), None),
    }


# ── the dose ──────────────────────────────────────────────────────────────────────────
def walk_dose_of(session: dict[str, Any]) -> dict[str, Any] | None:
    """(incline %, mph) of one performed treadmill walk: incline from his note, speed from distance/time
    (falls back to none when either is missing)."""
    m = _INCLINE_RE.search(session.get("note") or "")
    try:
        mph = round(float(session["distance_m"]) / _M_PER_MI / (float(session["duration_sec"]) / 3600.0), 1)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        mph = None
    if not m or mph is None:
        return None
    return {"date": str(session.get("date") or "")[:10], "incline_pct": float(m.group(1) or m.group(2)), "mph": mph}


def _clip(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _fmt_num(v: float) -> str:
    return f"{v:g}"


def treadmill_dose(sessions: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The incline walk's dose from his treadmill history (`cardio_index` entry, most recent first).

    In the band (a walk at or above the band's floor incline is on record): the last such walk's dose,
    one step up (incline first, then speed) when the last `HELD_WALKS_FOR_STEP` walks held it. Below the
    band: the band's floor incline at the speed he walked his steepest walk, clipped into the band."""
    walk = block("incline_treadmill_walk")
    band = walk.get("starting_dose") or {}
    (i_lo, i_hi), (s_lo, s_hi) = band.get("incline_pct") or (0, 0), band.get("mph") or (0, 0)
    step = walk.get("step") or {}
    walks = [w for w in (walk_dose_of(s) for s in sessions or []) if w]
    in_band = [w for w in walks if w["incline_pct"] >= i_lo]
    if in_band:
        last = in_band[0]
        inc, mph = _clip(last["incline_pct"], i_lo, i_hi), _clip(last["mph"], s_lo, s_hi)
        held = in_band[:HELD_WALKS_FOR_STEP]
        if len(held) == HELD_WALKS_FOR_STEP and all(w["incline_pct"] >= inc and w["mph"] >= mph for w in held):
            if inc + float(step.get("incline_pct") or 0) <= i_hi:
                new = inc + float(step.get("incline_pct") or 0)
                reason = (
                    f"+{_fmt_num(new - inc)}%: your last {len(held)} walks held {_fmt_num(inc)}% at {mph} mph — same RPE, one step steeper"
                )
                inc = new
            elif mph + float(step.get("mph") or 0) <= s_hi + 1e-9:
                new = round(mph + float(step.get("mph") or 0), 1)
                reason = (
                    f"+{_fmt_num(round(new - mph, 1))} mph: {_fmt_num(inc)}% is the top of the band and your last {len(held)} walks held it"
                )
                mph = new
            else:
                reason = f"the top of the band ({_fmt_num(i_hi)}% at {s_hi} mph): hold it"
        else:
            reason = f"hold {_fmt_num(inc)}% at {mph} mph until {HELD_WALKS_FOR_STEP} walks in a row hold it"
        return {"incline_pct": inc, "mph": mph, "basis": "last walk in the band", "reason": reason, "stepped": "+" in reason}
    if walks:
        steep = max(walks, key=lambda w: (w["incline_pct"], w["date"]))
        mph = _clip(steep["mph"], s_lo, s_hi)
        reason = (
            f"start: {_fmt_num(i_lo)}% (the menu's floor; your steepest walk on record is "
            f"{_fmt_num(steep['incline_pct'])}% at {steep['mph']} mph) at {mph} mph"
        )
        return {"incline_pct": float(i_lo), "mph": mph, "basis": "his steepest walk", "reason": reason, "stepped": False}
    return {
        "incline_pct": float(i_lo),
        "mph": float(s_lo),
        "basis": "the menu's floor",
        "reason": f"start: {_fmt_num(i_lo)}% at {s_lo} mph, the floor of the menu's band (no treadmill walk on record)",
        "stepped": False,
    }


def speed_at_level(facts: dict[str, Any] | None, level: int | None) -> float | None:
    """His mean speed over his last rides at `level` (up to `cardio_progression.BLOCK_K`), or None."""
    from training.cardio_progression import BLOCK_K

    if level is None:
        return None
    at = [r for r in (facts or {}).get("series") or [] if r.get("level") == level and r.get("speed_mph") is not None]
    at.sort(key=lambda r: str(r.get("date")))
    recent = at[-BLOCK_K:]
    if not recent:
        return None
    return round(sum(float(r["speed_mph"]) for r in recent) / len(recent), 1)


def bike_dose(kind: str, facts: dict[str, Any] | None, verdict: dict[str, Any] | None, *, constrained: bool = False) -> dict[str, Any]:
    """{level, hold_level, mph, reason} for a bike-type block. Progression is the verdict's: same RPE at a
    higher level only on a `raise` (his speed at the level cleared his own within-level spread).

    One step per block, never two. A `raise` verdict moves the EASY block only (baseline + 1). A tempo
    block's step IS its dose: tempo = baseline + `TEMPO_LEVEL_STEP`, where the baseline is the held
    level (the last ride's), so a tempo day after a raise is still one level above the last ride
    (last_level 11 + raise -> easy 12, tempo 12, never 13). Intervals and hills ride the baseline."""
    from training import cardio_note

    level, hold = cardio_note.prescribed_level(facts, verdict, constrained=constrained)
    if level is None:
        return {
            "level": None,
            "hold_level": None,
            "mph": None,
            "reason": "no level on the record: pick the level that gives the RPE, and log it",
        }
    mph = speed_at_level(facts, hold)
    if level != hold:
        reason = f"+1 level: {(verdict or {}).get('basis')} — same RPE, one level up"
    else:
        reason = ""
    if kind == "tempo":
        level = hold + TEMPO_LEVEL_STEP  # the tempo step is the dose; a raise never stacks on it
        reason = f"tempo rides {TEMPO_LEVEL_STEP} level above your last ride (platform-chosen)"
    elif kind in ("intervals", "hills"):
        level = hold  # a harder shape never rides a raised level: the raise and the shape are one step each
        reason = ""
    return {"level": level, "hold_level": hold, "mph": mph, "reason": reason}


# ── movement minutes ──────────────────────────────────────────────────────────────────
def movement_minutes(exercises: list[Any] | None) -> int:
    """The gym cardio minutes a routine adds to the day's movement goal: the summed duration of every
    timed cardio-machine block (`cardio_note.MACHINES`)."""
    from training import cardio_note

    secs = 0
    for ex in exercises or []:
        if cardio_note.machine_for(str(getattr(ex, "movement_key", "") or "")):
            secs += sum(int(getattr(s, "duration_seconds", 0) or 0) for s in getattr(ex, "sets", None) or [])
    return round(secs / 60)


def machine_template_ids(catalog: dict[str, Any] | None) -> dict[str, str]:
    """Hevy template id -> movement key, for every cardio machine `cardio_note.MACHINES` names."""
    from training import cardio_note

    movements = (catalog or {}).get("movements") or {}
    return {
        str(movements[k]["hevy_template_id_hint"]): k
        for k in cardio_note.MACHINES
        if isinstance(movements.get(k), dict) and movements[k].get("hevy_template_id_hint")
    }


def performed_movement_minutes(
    cardio_index: dict[str, list[dict[str, Any]]] | None, day: str, template_ids: dict[str, str] | set[str]
) -> int:
    """The gym cardio minutes performed on `day` — the cardio-machine templates' blocks on that date
    (`template_ids`, e.g. `machine_template_ids(catalog)`; stretching, planks and carries are timed too
    and are not cardio) — the performed side of the same field, for the steps/movement goal."""
    secs = 0.0
    for tid, sessions in (cardio_index or {}).items():
        if tid not in template_ids:
            continue
        for s in sessions or []:
            if str(s.get("date") or "")[:10] == str(day)[:10]:
                try:
                    secs += float(s.get("duration_sec") or 0)
                except (TypeError, ValueError):
                    continue
    return round(secs / 60)
