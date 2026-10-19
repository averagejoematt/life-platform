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
  * the MACHINE — the recumbent after a lower day (today's or the session before it in
    `split.sequence`) or on loaded legs (a heavy walking weekend, `recent_aerobic.legs_loaded`);
    otherwise the menu's default, the incline treadmill walk, for an easy block;
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


def block_minutes(kind: str) -> int:
    """The block's own minutes when the menu names them (tempo: 'hard flat 40'), else the split's cardio block cap."""
    own = block(kind).get("minutes")
    if own:
        return int(own)
    return int(training_charter.charter_value("split.session_minutes.cardio_block_max", 0) or 0)


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
    """The lower sessions' names, lower-cased: every `split.sequence` name that says 'lower', plus the
    generic archetypes the generator writes ('lower', 'legs')."""
    seq = training_charter.charter_value("split.sequence", []) or []
    return {str(s).strip().lower() for s in seq if "lower" in str(s).lower()} | {"lower", "legs"}


def is_lower(archetype: Any) -> bool:
    return str(archetype or "").strip().lower() in lower_names()


def session_before(archetype: Any) -> str | None:
    """The session before `archetype` in `split.sequence` (wrapping), or None when it is not a sequence name."""
    seq = [str(s) for s in training_charter.charter_value("split.sequence", []) or []]
    low = [s.lower() for s in seq]
    a = str(archetype or "").strip().lower()
    if a not in low:
        return None
    return seq[(low.index(a) - 1) % len(seq)]


# ── placement ─────────────────────────────────────────────────────────────────────────
def kind_of_performed(machine_key: str, note: str | None) -> str:
    """The menu kind a performed block was, read from its machine and its own note."""
    from training import cardio_note

    text = note or ""
    shape = cardio_note.shape_of(text)
    if shape == "intervals":
        return "intervals"
    if shape == "hill":
        return "hills"
    if machine_key == TREADMILL:
        return "incline_treadmill_walk"
    if _TEMPO_WORD.search(text):
        return "tempo"
    return "easy"


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
) -> dict[str, Any]:
    """{kind, machine, why} for today's block. `machines` restricts the choice to a block that is already
    on one machine (a chat-drafted bike); None lets the menu pick the machine too.

    `week_kinds` are this week's blocks before today (performed or placed), oldest first."""
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
    lower_today = is_lower(archetype)
    before = session_before(archetype)
    lower_before = is_lower(before) if before else False
    recumbent_why = (
        "a lower day"
        if lower_today
        else (f"the session before was {before}" if lower_before else ("the legs carry a heavy walking load" if legs_loaded else None))
    )
    if legs_loaded is None and not (lower_today or lower_before):
        recumbent_why = "the walking load was not read"

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
    on_recumbent = recumbent_why is not None
    if kind is None:
        kind = "easy" if on_recumbent else default_kind()
    machine = _machine_for(kind, on_recumbent)
    if machines:
        machine, kind = _fit_machine(kind, machines)
    if on_recumbent and machine == RECUMBENT:
        why += f"; the recumbent: {recumbent_why}"
    return {"kind": kind, "machine": machine, "why": why, "needed": needed}


def _machine_for(kind: str, on_recumbent: bool) -> str:
    machines = list(block(kind).get("machines") or [])
    if on_recumbent and RECUMBENT in machines:
        return RECUMBENT
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


def place_week(days: list[dict[str, Any]], last_tempo_or_hills: str | None = None) -> list[dict[str, Any] | None]:
    """The placement over a week of days, each `{date, archetype}` (None archetype = a rest day, no gym
    block) plus optional `legs_loaded`. Returns one `choose_kind` result per day (None on a rest day).
    The same rule `choose_kind` applies to a single draft, iterated so the week can be read whole."""
    out: list[dict[str, Any] | None] = []
    week: list[str] = []
    prior: str | None = None
    lifting = [d for d in days if d.get("archetype")]
    for d in days:
        if not d.get("archetype"):
            out.append(None)
            prior = None
            continue
        left = len(lifting) - sum(1 for x in out if x)
        pick = choose_kind(
            target_date=d["date"],
            archetype=d["archetype"],
            week_kinds=week,
            prior_day_kind=prior,
            legs_loaded=d.get("legs_loaded", False),
            last_tempo_or_hills=last_tempo_or_hills,
            days_left=left,
        )
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
