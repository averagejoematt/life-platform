"""live_safety.py — the fourth red team's SAFETY and NOTE fixes (#5861 FIX4). LIVE only: every entry point is reached from a
live hook (`live_program.joint_flags` / `apply_joint_rule` / `annotate` / `cardio_note`, `live_session._blocked` /
`_replacement` / `for_live_draft`, `selection_live.build_policy`, `live_balance.why_effort`), each of which returns before reading
anything unless the draft ran the live session fit (`live_session.MARK`, which exists only when the exercise library is
`approved`) or the live selection policy exists. tests/test_no_live_change_5861_l6.py pins the served proposed-mode drafts byte
for byte.

WHY IT EXISTS. A fourth independent red team (2026-11-12) graded the engine B- (safety C) on the GENERATED weeks:

  1. THE PAIN SITE (`note_site`, `flag_joints`). A pain flag's joint was the flagged movement's worst joint, never the note's
     words, and the joint model had no knee or hip: "knee pain 5/10 on the squat" was routed as a SPINAL-LOAD flag (a row and a
     calf raise cut, three lunge patterns kept at RPE 8-9). The joint is now read from the note (knee, hip, low back, shoulder,
     elbow, wrist) and the movement's worst joint is the fallback only when no site is named; a knee flag's pattern group is
     the knee-dominant group (squat, lunge, split squat, step-up, leg extension) whatever lift the note was on.
  2. MILD PAIN KEEPS THE LIFT (`mild`, `mild_pain_tids`). PAIN_RULE says a stated score at or under 3/10, not sharp, keeps the
     movement lighter; the session fit and the selection swapped it anyway (any pain-class note). Both layers now keep it, and
     every lift the pain rule touched carries an in-set stop line (`stop_line`).
  3. ONE LOAD RULE IN THE NOTES (`no_step`, fix round 10; `r3_lines`, fix round 11). Double progression (`live_load`) is the
     one progression system under live: the engine's in-session load-step lines are dropped from every note, and the ONE bounded
     in-session step (`live_load` rule 8, the owner's R3: set 1 at RPE 7 or easier → one load step on later sets, never down) is
     written back only on a lift the session-to-session rule does not hold, step down or cap.
  4. ONE EFFORT ACROSS THE SESSION (`coherent_effort`, `big_lift_conflicts`). "Lower heavy · RPE 7 on big lifts" sat two lines
     above a deadlift's own "RPE 8–9": the guard read one lift at a time.
  5. THE STOP LINE (`symptom_text`, `lifting_day_symptom`). A second wording preset (`symptom_line: "extended"`) adds "heart
     racing or irregular" and "doesn't settle → get medical help", and a switch (`symptom_line_on_lifting_days`) prints it on
     exercise 1 of every lifting morning too. The default wording is unchanged (owner decision).

Every number here is a labelled PLATFORM HEURISTIC (practitioner consensus at best), owner-adjustable; none is validated.
"""

from __future__ import annotations

import re
from typing import Any

ISSUE = "#5861"
HEURISTIC = "heuristic"

SITE_WORDS: tuple[tuple[str, str], ...] = (
    (r"\bknees?\b|patell\w*|kneecap|\bmenisc\w*|\b(?:acl|mcl)\b", "knee"),
    (r"\bhips?\b|\bgroin\b|hip flexor|\bpiriformis\b", "hip"),
    (r"\blow(?:er)? back\b|\blumbar\b|\bspine\b|\bsciatic\w*|(?<!upper )\bback\b", "spinal_load"),
    (r"\bshoulders?\b|rotator|\bcuff\b|\bac joint\b", "shoulder"),
    (r"\belbows?\b", "elbow"),
    (r"\bwrists?\b", "wrist"),
)
"""HEURISTIC: the body-site words a pain note names, -> the library joint they map to. The EARLIEST site named in the note wins
(\"knee pain on the squat\" -> knee); none named -> the flagged movement's worst joint (the old inference, kept as the fallback)."""
JOINT_GROUP = {"knee": "squat"}
"""A site-named flag's pattern group (the movements it AVOIDS above the mild line): a knee flag avoids the knee-dominant group
(squat, lunge, split squat, step-up — the `squat` pattern — and leg extension) whatever lift the note was on. Other joints keep
the flagged movement's own group (a shoulder flag on a press avoids presses)."""
STOP_LINE: dict[str, Any] = {
    "value": "Pain past {n}/10 or sharp → stop this lift.",
    "label": HEURISTIC,
    "basis": "fourth red team (physio): a pain-flagged lift needs an in-set rule. The pain-monitoring line is PAIN_RULE mild_max "
    "(3/10) or the stated score when lower: pain above it, or turning sharp, ends that lift for the day (practitioner consensus)",
}


# ── 1. the pain site ─────────────────────────────────────────────────────────
def note_site(note: str | None) -> str | None:
    """The joint the note's words name (SITE_WORDS, earliest in the text), or None."""
    text = str(note or "").lower()
    hits = [(m.start(), joint) for rx, joint in SITE_WORDS for m in [re.search(rx, text)] if m]
    return min(hits)[1] if hits else None


def latest_notes(workouts: Any) -> dict[str, str]:
    """{template id: its latest non-empty note} from the Hevy record (oldest first, so the latest wins)."""
    out: dict[str, str] = {}
    for w in sorted(workouts or [], key=lambda w: str(w.get("date") or w.get("sk") or "")):
        for ex in w.get("exercises") or []:
            if ex.get("notes"):
                out[str(ex.get("template_id") or "").upper()] = str(ex["notes"])
    return out


def mild(note: str | None) -> bool:
    """PAIN_RULE's mild line: a stated score at or under mild_max and not 'sharp' (no number is never mild)."""
    from training.live_program import PAIN_RULE
    from training.training_notes_pain import stated_severity

    sev = stated_severity(str(note or "")) if note else None
    return sev is not None and sev <= float(PAIN_RULE["mild_max"]["value"]) and "sharp" not in str(note).lower()


def mild_pain_tids(workouts: Any) -> set[str]:
    """Template ids whose LATEST note is a pain-class note at the mild line: kept lighter, never swapped (module doc 2)."""
    from training.training_notes_pain import pain_class

    return {tid for tid, note in latest_notes(workouts).items() if pain_class(note) == "pain" and mild(note)}


def flag_joints(note: str, inferred: list[str], pattern_group: str | None) -> tuple[list[str], str | None, str]:
    """(joints, group, source) for one flag: the note's site when it names one (`note`), else the inferred worst joints."""
    site = note_site(note)
    if site:
        return [site], JOINT_GROUP.get(site, pattern_group), "note"
    return inferred, pattern_group, "inferred"


def stop_line(severity: float | None) -> str:
    """STOP_LINE at PAIN_RULE mild_max, or the stated score when it is lower."""
    from training.live_program import PAIN_RULE

    n = float(PAIN_RULE["mild_max"]["value"])
    if severity is not None and float(severity) < n:
        n = float(severity)
    return str(STOP_LINE["value"]).format(n=f"{n:g}")


def blocked_pain_is_mild(entry: dict[str, Any], ctx: dict[str, Any]) -> bool:
    """A pain-class flag on `entry` whose latest note is mild: the session fit keeps the movement (the joint rule reduces it)."""
    return str(entry.get("template_id") or "").upper() in (ctx.get("mild_pain") or set())


def pain_limit(entry: dict[str, Any] | None, ctx: dict[str, Any]) -> tuple[str, int] | None:
    """For a pain swap in the session fit: (the note's site joint, the entry's stress there) when the note names a site the
    library rates; else None (the caller keeps its worst-joint inference)."""
    from training.live_session import STRESS_ORDER

    note = (ctx.get("pain_notes") or {}).get(str((entry or {}).get("template_id") or "").upper())
    site = note_site(note)
    level = STRESS_ORDER.get(str(((entry or {}).get("joint_stress") or {}).get(site))) if site else None
    return (str(site), int(level)) if site and level is not None else None


# ── 3. one load rule in the notes ────────────────────────────────────────────
_LATER_SETS = re.compile(r"on later sets|: \+\d+(?:\.\d+)? lb per hand")  # a carry's in-session step too


def _step_line(line: str) -> bool:
    """An in-session load-step line: the session block's rule (its if/then and its limits) or a lift's own "on later sets"."""
    from training import hevy_note_grammar as g

    s = line.strip()
    return bool(_LATER_SETS.search(s)) or s.startswith((g.LOAD_RULE_HEAD, g.OTHER_LIFTS_HEAD)) or s == g.LOAD_RULE_LIMITS


def block_rule(block: str) -> str:
    """The session block (exercise 1's, or the compiler's WHY line) without the in-session load rule (module doc 3)."""
    return "\n".join(ln for ln in (block or "").split("\n") if not _step_line(ln))


def no_step(blocks: list[Any], rx: dict[str, Any]) -> list[str]:
    """IN PLACE, live only (module doc 3): no in-session load step on any lift — the session block's rule and every lift's own
    "on later sets" line go. Returns the rationale line."""
    from training import session_block as sb

    dropped = 0
    for b in blocks:
        block, own = sb.split(b.notes or "")
        lines = [ln for ln in own.split("\n") if ln.strip()]
        kept = [ln for ln in lines if not _step_line(ln)]
        new = block_rule(block) if block else block
        dropped += len(lines) - len(kept) + (block or "").count("\n") - (new or "").count("\n")
        b.notes = new + ("\n\n" + "\n".join(kept) if kept else "") if new else "\n".join(kept)
    return [f"one load rule (live): {dropped} in-session load-step line(s) dropped — double progression only"] if dropped else []


R3_LINE = "Set 1 at RPE 7 or easier → {step} on later sets."
"""Rule 8 of `live_load` (fix round 11: the owner's 2026-10-27 R3 in-session rule, ONE bounded form): never down in-session."""


def r3_text(step: Any) -> str:
    """The bounded in-session step's line for one lift (`R3_LINE`); `step` [lb or None, per hand]."""
    from training import hevy_note_grammar as g

    lb, per_hand = (list(step or []) + [None, False])[:2]
    return R3_LINE.format(step=g._step_text(lb, bool(per_hand)) if lb else "the next pin")


def r3_lines(blocks: list[Any], rx: dict[str, Any]) -> list[str]:
    """IN PLACE, live only, after `no_step`: the ONE in-session step (`live_load` rule 8) on every eligible lift's own note — a
    loaded lift whose session-to-session decision is a step up or a reps-first hold, never one held for a reason, stepped down,
    new, first back, pain-touched or capped at RPE 7, never on a hold day (`live_load.r3_eligible`). Returns the line."""
    from training import live_load, live_session as ls, session_block as sb

    mark = rx.get(ls.MARK) or {}
    guard = {d["key"]: d for d in mark.get("load_guard") or []}
    by_key = {e.get("movement_key"): e for e in rx.get("exposures") or []}
    held_day = bool(mark.get("hold_all")) or (rx.get("fatigue") or {}).get("state") in ("strained", "overreached")
    steps = mark.get("r3_step") or {}
    n = 0
    for b in blocks:
        e = by_key.get(b.movement_key)
        if e is None or str(b.movement_key) not in steps or not live_load.r3_eligible(e, guard.get(b.movement_key), held_day):
            continue
        b.notes = sb.add_reason(b.notes, r3_text(steps[str(b.movement_key)]))
        n += 1
    return (
        [f"in-session step (live): {n} lift(s) step up one load step on later sets when set 1 lands at RPE 7 or easier (R3)"] if n else []
    )


# ── 4. one effort across the session ─────────────────────────────────────────
def _own_effort(note: str | None) -> str | None:
    """The lift's own effort target (`RPE a–b`): its own first effort line, else None (it inherits the session band)."""
    from training import hevy_note_grammar as g, session_block as sb

    _block, own = sb.split(note)
    first = next((ln.strip() for ln in own.split("\n") if ln.strip()), "")
    m = g.EFFORT_RE.match(first)
    return f"RPE {m.group('rpe')}" if m else None


def _is_big(b: Any) -> bool:
    return str(getattr(b, "rationale_tag", "") or "").startswith("anchor:")


def big_lift_conflicts(blocks: list[Any], head: str | None = None) -> list[str]:
    """The session line's band against every BIG lift's (anchor's) own effort target: one entry per lift whose target differs
    (a lift with no own effort line inherits the band). `head` defaults to exercise 1's session line. Empty = coherent."""
    from training import session_block as sb

    if not blocks:
        return []
    line = head if head is not None else sb.split(blocks[0].notes or "")[0].split("\n", 1)[0]
    band = sb.session_effort(line or "")
    if not band:
        return []
    out = []
    for b in blocks:
        own = _own_effort(b.notes)
        if _is_big(b) and own and own != band and not _within(own, band):
            out.append(f"{b.movement_key}: {own} under '{band} on big lifts'")
    return out


def _span(effort: str) -> tuple[float, float] | None:
    """`RPE a–b` / `RPE a` -> (a, b)."""
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", str(effort or ""))]
    return (min(nums), max(nums)) if nums else None


def _within(own: str, band: str) -> bool:
    """#5861 FIX7: a big lift's own band INSIDE the session band refines it, never contradicts it (`RPE 7–8` under `RPE 7–9`)."""
    a, b = _span(own), _span(band)
    return bool(a and b and b[0] <= a[0] and a[1] <= b[1])


def coherent_head(head: str, blocks: list[Any]) -> str:
    """The session line restated so it never contradicts a big lift: the band every big lift shares, or the day alone when
    they differ (each big lift then states its own target)."""
    from training import session_block as sb

    m = sb.SESSION_LINE_RE.match(head or "")
    if not m:
        return head
    band = f"RPE {m.group('band')}"
    targets = {_own_effort(b.notes) or band for b in blocks if _is_big(b)}
    if not targets:  # #5861 FIX7: no big lift today (a flagged anchor skipped): nothing to contradict — the line keeps its band
        return head
    if len(targets) == 1:
        (t,) = targets
        return head if t == band else f"{m.group('day')} · {t} on big lifts"
    spans = [_span(t) for t in targets]
    if spans and all(
        spans
    ):  # #5861 FIX7: the span of the big lifts' bands (each states its own) — line 1 keeps its effort (lint L3/L6/L12)
        lo, hi = min(x[0] for x in spans if x), max(x[1] for x in spans if x)
        return f"{m.group('day')} · RPE {lo:g}–{hi:g} on big lifts"
    return m.group("day")


def coherent_effort(blocks: list[Any], rx: dict[str, Any]) -> None:
    """IN PLACE: the session line made coherent with every big lift (`coherent_head`) — on exercise 1's block, or, when the
    compiler will write the block as the WHY line (`live_balance.why_effort` restates it there), the line it will write; a big
    lift that inherited the old band and now sits under a day-only line states the band itself."""
    from training import session_block as sb

    if not blocks:
        return
    block, own = sb.split(blocks[0].notes or "")
    head = block.split("\n", 1)[0] if block else sb.session_line(sb.day_label(rx.get("session_role")), sb.compounds_band())
    new = coherent_head(head, blocks)
    band = sb.session_effort(head)
    if new == head or not band or sb.session_effort(new):
        if band and new != head and sb.session_effort(new) != band:  # FIX7: a big lift that inherited the old band states it
            for b in blocks[1:]:
                if _is_big(b) and not _own_effort(b.notes):
                    bl, ow = sb.split(b.notes or "")
                    ow = f"{band}\n{ow}".strip()
                    b.notes = (bl + "\n\n" + ow) if bl else ow
        if block and new != head:
            blocks[0].notes = new + block[len(head) :] + ("\n\n" + own if own.strip() else "")
        return
    for b in blocks:  # the line names the day only: every big lift (exercise 1 too) states its own target
        if _is_big(b) and not _own_effort(b.notes):
            bl, ow = sb.split(b.notes or "")
            ow = f"{band}\n{ow}".strip()
            b.notes = (bl + "\n\n" + ow) if bl else ow
    if block:
        block2, own2 = sb.split(blocks[0].notes or "")
        blocks[0].notes = new + block2[len(head) :] + ("\n\n" + own2 if own2.strip() else "")


def fix_block(block: str, rx: dict[str, Any], blocks: list[Any]) -> str:
    """The compiler's WHY block (live): `block_rule` then the coherent session line."""
    out = block_rule(block)
    head = out.split("\n", 1)[0]
    new = coherent_head(head, blocks)
    return new + out[len(head) :] if new != head else out


# ── 5. the stop line ─────────────────────────────────────────────────────────
