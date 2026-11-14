"""live_balance.py — pain persistence, the library fallback, one effort per lift and the cardio host/machine (#5861). LIVE only:
every function is reached from a live hook that checks the live mark first; `why_effort` and `template_resolver` are reached in
shadow and return their input there (tests/test_no_live_change_5861_l6.py).

  * `spine_loading`: THE one spine-loading definition (a squat/hinge compound at moderate+ spinal load).
  * `pain_assess` (PAIN_ASSESS_LINE): while a pain flag stands, the flagged lift carries one neutral "get it assessed" line.
  * `library_fallbacks`: an accessory's last resort — same pattern, same muscle, best tier first.
  * `effort_targets` / `one_effort` / `why_effort`: one effort target per lift; a morning with no cardio block never promises
    "easy cardio" (ruling 4).
  * The cardio host and machine (`conditioning_host`, `easy_gap`, `min_block`, `cardio_machine`, `machine_label`).

Deleted in fix round 9: the allocation, the kettlebell slot placement and template setting (the resolver is an identity seam kept
for the cron and MCP call sites), the adherence dip's lighter week and the structured rate band."""

from __future__ import annotations

import re
from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"
HOST_ROLE = "shoulders_arms"
PAIN_ASSESS_LINE = "Still hurts 2 sessions? Get it assessed."
"""The one neutral line a standing pain flag puts on its flagged lift (no diagnosis, no number)."""
EASY_MIN_BLOCK = 20
"""Heuristic: the shortest easy aerobic block worth its warm-up (practitioner consensus: 20-30 min continuous)."""


def _entry(key: str | None, ctx: dict[str, Any]) -> dict[str, Any]:
    lid = ctx["idx"]["to_lib"].get(str(key)) if key else None
    return ((ctx["lib"].get("movements") or {}).get(lid) or {}) if lid else {}


# ── 1. one spine-loading definition ──────────────────────────────────────────
def spine_loading(entry: dict[str, Any] | None) -> bool:
    """THE spine-loading lift (one definition — the stacking rule, the gates and the sample-week generator read it): a
    squat- or hinge-pattern compound whose library spinal load is moderate or high. A carry is not one; a dumbbell lunge with
    the load at the sides is not one (its spinal load is low — `SPINE_AT_SIDES`)."""
    e = entry or {}
    spinal = str((e.get("joint_stress") or {}).get("spinal_load"))
    return e.get("pattern") in ("squat", "hinge") and e.get("job") == "compound" and spinal in ("moderate", "high")


# ── 2. the kettlebell slot's placement ───────────────────────────────────────


def _skip_set(skipped: Any) -> set[str]:
    """A role or roles this week does not draft (#5861 FIX5: a 2- or 3-day week skips more than one), as a set."""
    if not skipped:
        return set()
    return {str(skipped)} if isinstance(skipped, str) else {str(r) for r in skipped}


def template_resolver(resolve: Any, lib: dict[str, Any] | None = None) -> Any:
    """The compiler's movement -> Hevy template resolver, unchanged. Fix round 9 deleted the kettlebell-template setting (owner
    ruling #2: no KB Deadlift template unless he logs it regularly); the cron and MCP call sites outside this lane keep the seam."""
    return resolve


# ── 3. pain that persists ────────────────────────────────────────────────────
def pain_assess(rx: dict[str, Any], ctx: dict[str, Any], flags: list[dict[str, Any]], workouts: Any) -> list[str]:
    """IN PLACE: while a PAIN flag stands, the session's first joint-flagged lift (else its first lift) carries
    `pain_assess_line` (`live_assess`) and the rationale says how many sessions logged it. Off when the setting is ""."""
    from training.training_notes_pain import pain_class

    line = PAIN_ASSESS_LINE
    pains = [f for f in flags if f.get("source") == "pain"]
    if not line or not pains or not rx.get("exposures"):
        return []
    tids = {str(_entry_by_id(f["movement_id"], ctx).get("template_id") or "").upper() for f in pains}
    days = {
        str(w.get("date") or "")[:10]
        for w in workouts or []
        for x in w.get("exercises") or []
        if str(x.get("template_id") or "").upper() in tids and x.get("notes") and pain_class(str(x["notes"]))
    }
    from training import live_pain  # #5861 FIX7: the assess line only on the flagged lift (or what stands in for it)

    hit = live_pain.assess_target(rx, ctx, pains)
    if hit is None:
        return []
    hit["live_assess"] = line
    names = ", ".join(sorted(str(f.get("title")) for f in pains))
    return [f"pain (live): {names} — logged on {len(days)} session(s); the note says: {line} (pain_assess_line)"]


def _entry_by_id(mid: str, ctx: dict[str, Any]) -> dict[str, Any]:
    return (ctx["lib"].get("movements") or {}).get(mid) or {}


def assess_note(note: str, line: str) -> str:
    """The persistence line as the lift's last own line (never displacing the effort or a reason). Idempotent."""
    if not line or line in note.split("\n"):
        return note
    from training import session_block as sb

    block, own = sb.split(note or "")
    return sb._join(block, sb._own_lines(block, own) + [line])  # fix round 9: the phone budget's fit (the fallback line yields)


# ── 4. volume by priority ────────────────────────────────────────────────────


# ── 5. the adherence dip ─────────────────────────────────────────────────────


# ── 6. the library fallback ──────────────────────────────────────────────────
def library_fallbacks(e: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    """An accessory's last resort after its slot's ranked fallbacks: the library's members of the same movement pattern
    whose landmark muscle is the slot's, best hypertrophy tier for that muscle first, then familiar first. Catalog-writable
    only (the generator can write it). Equipment, pain, gates and the joint limits are judged by the caller."""
    from training import live_volume, selection_live

    if e.get("kind") != "accessory":
        return []
    cur = _entry(e.get("movement_key"), ctx) or _entry(e.get("slot"), ctx)
    pattern, muscle = cur.get("pattern"), live_volume.landmark_muscle(e.get("movement_key"), ctx["catalog"], ctx["lib"])
    if not pattern or pattern in ("carry", "cardio", "other"):
        return []
    to_cat = {lid: k for k, lid in ctx["idx"]["to_lib"].items()}
    rank = {t: i for i, t in enumerate("SABCD")}
    out = []
    for lid, entry in sorted((ctx["lib"].get("movements") or {}).items()):
        key = to_cat.get(lid)
        if not key or entry.get("pattern") != pattern:
            continue
        if live_volume.landmark_muscle(key, ctx["catalog"], ctx["lib"]) != muscle:
            continue
        tier = selection_live.objective_tier(entry, "hypertrophy", muscle)
        if tier is None:
            continue
        out.append((rank.get(str(tier), 9), -int((ctx["catalog"].get(key) or {}).get("sessions") or 0), key))
    return [k for *_r, k in sorted(out)]


# ── 7. one effort target per lift ────────────────────────────────────────────
_RULE_LINE = re.compile(r"^(?:Set 1|Top reps|One set|Other lifts|Dumbbells|Low energy)")


def effort_targets(note: str | None) -> list[str]:
    """The distinct effort TARGETS a lift's note states: the session line's band (exercise 1's day line) and each own line
    that is an effort line (`RPE a–b`, its last-set clause aside). A load rule's threshold ("Set 1: … at RPE 7 or less") is
    not a target. More than one = the note contradicts itself."""
    from training import hevy_note_grammar as g, session_block as sb

    block, own = sb.split(note)
    out = []
    eff = sb.session_effort(block) if block else None
    if eff:
        out.append(eff[len("RPE ") :])
    for line in own.split("\n"):
        m = g.EFFORT_RE.match(line.strip())
        if m and not _RULE_LINE.match(line.strip()):
            out.append(m.group("rpe"))
    for line in own.split("\n"):  # a carry's line 1: `RPE a–b · pick the load per hand`
        m = g.CARRY_LINE1_RE.match(line.strip())
        if m:
            out.append(m.group("rpe"))
    from training.live_safety import _within  # #5861 FIX7: a session SPAN its own band sits inside is refined, not contradicted

    if eff and len(out) > 1 and all(_within(f"RPE {t}", eff) for t in out[1:]):
        out = out[1:]
    return list(dict.fromkeys(out))


def _day_line(head: str, own_effort: str) -> str:
    """The session line restated at exercise 1's own effort: `‹Day› · RPE ‹its band› on big lifts` (the note standard's
    grammar, `hevy_note_grammar.SESSION_LINE_RE`, kept) — the day's actual cap where exercise 1 is capped."""
    from training import hevy_note_grammar as g, session_block as sb

    m, e = sb.SESSION_LINE_RE.match(head), g.EFFORT_RE.match(own_effort.strip())
    if not m or not e:
        return head
    return f"{m.group('day')} · RPE {e.group('rpe')} on big lifts"


def one_effort(note: str | None) -> str:
    """Exercise 1's note with its session line restated at the lift's own effort when that effort says something else (a
    joint flag, the deload shape, a stall reset, the KB cap) — and the own line then printed once: one effort target per
    lift (third red team: "RPE 8–9 on big lifts" then "RPE 6–7" on the same lift). Any other note: unchanged."""
    from training import hevy_note_grammar as g, session_block as sb

    text = note or ""
    block, own = sb.split(text)
    eff = sb.session_effort(block) if block else None
    lines = [ln for ln in own.split("\n") if ln.strip()]
    if not eff or not lines or not g.EFFORT_RE.match(lines[0].strip()) or lines[0].strip() == eff:
        return text
    head, sep, rest = block.partition("\n")
    return sb._join(_day_line(head, lines[0]) + sep + rest, lines)


def why_effort(why: str, ir: Any) -> str:
    """The compiler's WHY block (`session_block.why_note_for`) with its session line restated at exercise 1's own effort when
    that says something else — LIVE drafts only (the prescription carries `live_session.MARK`); else `why`, unchanged. The
    compiler then prints exercise 1's effort once (`hevy_compiler._place_routine_note` dedupes the equal line)."""
    from training import hevy_note_grammar as g, live_session as ls, session_block as sb

    rx = (getattr(ir, "inputs_snapshot", None) or {}).get("session_prescription") or {}
    exercises = getattr(ir, "exercises", None) or []
    if ls.MARK not in rx or not exercises or not why:
        return why
    first = next((ln for ln in str(getattr(exercises[0], "notes", "") or "").split("\n") if ln.strip()), "")
    eff = sb.session_effort(why)
    if eff and g.EFFORT_RE.match(first.strip()) and first.strip() != eff:
        head, sep, rest = why.partition("\n")
        why = _day_line(head, first) + sep + rest
    from training.live_safety import fix_block  # #5861 FIX4: no step on a held exercise 1 / hold day; one effort across the session

    if not sb.cardio_kinds_of(exercises):  # fix round 9 (ruling 4): a morning with no cardio block never promises easy cardio
        why = "\n".join(g.LOW_ENERGY_LIFTS_LINE if ln == g.LOW_ENERGY_LINE else ln for ln in why.split("\n"))
    return fix_block(why, rx, exercises)


# ── 8. cardio: the host, the machine, its name ───────────────────────────────
def conditioning_host(skipped: Any) -> str:
    """The session the shared cap puts hard conditioning on: shoulders+arms; in a week that skips it (the short week, the dip
    week), the session the menu places conditioning on instead — the one after the heavy lower day (owner ruling 2026-10-25
    on #5076). The third red team's short week had no conditioning at all under the shared cap."""
    from training import program_structure as ps

    gone = _skip_set(skipped)
    if HOST_ROLE not in gone:
        return HOST_ROLE
    roles = [r for r in ps.SPLIT_ROLES if r not in (gone | {HOST_ROLE})] or [r for r in ps.SPLIT_ROLES if r not in gone]
    return roles[(roles.index("lower_heavy") + 1) % len(roles)] if "lower_heavy" in roles else roles[-1]


def easy_gap(kind: str, live: dict[str, Any]) -> tuple[bool, list[str]]:
    """(keep, lines) for an EASY block when the week's steps do not cover the aerobic floor: the block stays only while the
    gap — the guideline floor less the walking credit less every block performed this week (since its Monday) — is at least
    CARDIO_ROOM's minimum block. Steps first, then only the structured minutes that close the gap (third red team: the
    conservative credit must not turn into an easy block every morning). A hard kind, or unread steps: (True, [])."""
    from training import cardio_model, live_program, live_sequence

    aer = live.get("aerobic") or {}
    if kind in live_program.HARD_KINDS or not aer or aer.get("volume_covered"):
        return True, []
    from training import live_shape  # #5861 FIX8 (ruling 12): high steps of unknown intensity — reported, no easy block

    if live_shape.intensity_unknown(aer):
        return False, [
            f"cardio (live): no easy block — steps ~{aer.get('steps_per_day')}/day, intensity unknown: reported, not a deficit "
            "(ruling 12; WALK_PROMPT active_steps, heuristic)"
        ]
    since, day = live_sequence.week_start(str(live.get("target_date") or "")), str(live.get("target_date") or "")
    done = sum(
        int(r.get("duration_sec") or 0) // 60
        for rows in (live.get("by_machine") or {}).values()
        for r in rows or []
        if since <= str(r.get("date") or "")[:10] < day
    )
    walk = int(aer.get("walking_min_per_wk") or 0)
    gap = int(cardio_model.WEEKLY_MODERATE_MIN[0]) - walk - done
    floor = EASY_MIN_BLOCK
    if gap < floor:
        return False, [
            f"cardio (live): no easy block — recorded walking (~{walk} moderate min/wk credited) and {done} min of blocks this "
            f"week leave {max(gap, 0)} min of the weekly {cardio_model.WEEKLY_MODERATE_MIN[0]}: under a {floor}-min block (recorded walking first)"
        ]
    return True, [
        f"cardio (live): easy block kept — the week is ~{gap} min short of {cardio_model.WEEKLY_MODERATE_MIN[0]} after ~{walk} min of recorded walking and {done} min of blocks"
    ]


def min_block(kind: str, hard_min: int) -> int:
    """The shortest block worth serving under the shared cap: CARDIO_ROOM's minimum for an easy block (a stub is worthless),
    `hard_min` for a conditioning block (its intervals or tempo still fit)."""
    from training import live_program

    return hard_min if kind in live_program.HARD_KINDS else EASY_MIN_BLOCK


def _unavailable(key: str, lib: dict[str, Any] | None) -> bool:
    from training import selection_engine as se

    entry = ((lib or {}).get("movements") or {}).get(key)
    return bool(entry) and bool(se.availability(entry, lib or {}, None))


def cardio_machine(menu: dict[str, Any], lib: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """The menu's machine when the gym has it; else the first machine the menu runs this kind on that it has (treadmill,
    rower, bike, elliptical — `cardio_menu.fits_machine`); else unchanged (named). Live only (`live_program.cardio_fit`)."""
    from training import cardio_menu, cardio_note

    key = str(menu.get("machine") or "")
    if not key or not _unavailable(key, lib):
        return menu, []
    for alt in cardio_note.MACHINES:
        if alt != key and cardio_menu.fits_machine(str(menu["kind"]), alt) and not _unavailable(alt, lib):
            return {**menu, "machine": alt}, [f"cardio (live): {key} -> {alt} — the gym has no {key} (equipment, live)"]
    return menu, [f"cardio (live): {key} kept — no other machine the gym has runs {menu['kind']}"]


def recumbent_missing(lib: dict[str, Any] | None) -> bool:
    """The gym inventory marks a recumbent bike unavailable (an upright stationary bike may still be there)."""
    items = ((lib or {}).get("gym_inventory") or {}).get("items") or {}
    return str(((items.get("recumbent_bike") or {}).get("home_gym") or {}).get("state")) == "unavailable"


def machine_label(notes: str, lib: dict[str, Any] | None) -> str:
    """A `cycling` note names "Recumbent" (the owner's knee-sparing bike); where the gym has no recumbent it names "Bike"."""
    if not recumbent_missing(lib):
        return notes
    return "\n".join(("Bike" + ln[len("Recumbent") :]) if ln.startswith("Recumbent") else ln for ln in notes.split("\n"))


# ── 9. the rate band, by setting ─────────────────────────────────────────────
