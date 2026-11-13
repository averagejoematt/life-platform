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
  3. NO LOAD STEP ON A HELD LIFT (`no_step`). The session block's "Top reps at RPE 7 or less → +10 lb on later sets" headed
     every exercise 1 — on deload-recommended days, stall resets, pain cuts and load holds — and undid the cut it sat under.
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
NO_STEP_LINE = "No load step today."
HOLD_DAY_LINE = "Loads stay as written today."
SYMPTOM_PRESETS: dict[str, str] = {
    "extended": "Chest, breathing, dizzy, heart racing or irregular? Stop.\nDoesn't settle → get medical help.",
}
"""`programming_settings.symptom_line` may name a preset instead of literal text (OWNER DECISION; the default literal is
unchanged). `extended` adds a racing or irregular heartbeat and a seek-care step (fourth red team, the clinician panel voice).
No condition named, no heart-rate number (owner rulings)."""
SETTINGS_DEFAULTS: dict[str, Any] = {"symptom_line_on_lifting_days": False}
"""OWNER DECISION, off by default: True prints the symptom line as the last line of exercise 1 on every live lifting morning
(today it prints on conditioning notes only)."""


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


# ── 3. no load step on a held lift ───────────────────────────────────────────
def _hold_day(rx: dict[str, Any]) -> bool:
    from training.live_program import LOAD_POLICY

    fat = rx.get("fatigue") or {}
    return fat.get("state") in LOAD_POLICY["hold_states"]["value"] or fat.get("action") == "deload_recommended"


def no_step_keys(rx: dict[str, Any]) -> set[str]:
    """Movements whose load must not step inside the session: a guard decision (cut or hold), a joint flag, a stall reset, the
    deload shape, a lift already cut this week, a pain swap."""
    from training import live_session as ls

    out = {str(d["key"]) for d in (rx.get(ls.MARK) or {}).get("load_guard") or []}
    for e in rx.get("exposures") or []:
        swap = (e.get("live_swap") or {}).get("code")
        if e.get("live_load") or e.get("live_retreated") or e.get("live_stop") or swap in ("joint", "pain"):
            out.add(str(e.get("movement_key")))
    return out


_LATER_SETS = re.compile(r"on later sets")


def _drop_step_lines(lines: list[str]) -> list[str]:
    return [ln for ln in lines if not _LATER_SETS.search(ln)]


def block_rule(block: str, rx: dict[str, Any], blocks: list[Any]) -> str:
    """The session block (exercise 1's, or the compiler's WHY line) with its load rule fitted to the held lifts (module doc 3):
    a hold day drops it; a held exercise 1 turns it to "Other lifts: …", or drops it when no other lift may step."""
    from training import hevy_note_grammar as g, session_block as sb

    lines = (block or "").split("\n")
    if len(lines) < 3 or not blocks:
        return block
    keys, ex1 = no_step_keys(rx), blocks[0]
    others = any(x is not ex1 and x.movement_key not in keys for x in blocks if sb.steppable(x))
    if _hold_day(rx) or (ex1.movement_key in keys and not others):
        return "\n".join(lines[:2])
    if ex1.movement_key in keys and not lines[2].startswith(g.OTHER_LIFTS_HEAD):
        return "\n".join(lines[:2] + sb.load_rule_line(sb.step_lb(), other_lifts=True).split("\n"))
    return block


def no_step(blocks: list[Any], rx: dict[str, Any]) -> list[str]:
    """IN PLACE, live only (module doc 3): no "+N on later sets" line on a held lift or on a hold day. A held lift's own
    "Set 1: … on later sets" line goes; the session block's rule is fitted by `block_rule` (here when exercise 1 carries the
    block, else on the compiler's WHY line, `live_balance.why_effort`); a hold day says HOLD_DAY_LINE on exercise 1; any other
    held lift (exercise 1 aside — the rule addresses the OTHER lifts then) says NO_STEP_LINE. Returns the rationale lines."""
    from training import session_block as sb
    from training.live_balance import assess_note

    if not blocks:
        return []
    keys, hold = no_step_keys(rx), _hold_day(rx)
    for i, b in enumerate(blocks):
        if not (hold or b.movement_key in keys):
            continue
        block, own = sb.split(b.notes or "")
        lines = _drop_step_lines([ln for ln in own.split("\n") if ln.strip()])
        block = block_rule(block, rx, blocks) if i == 0 and block else block
        b.notes = block + ("\n\n" + "\n".join(lines) if lines else "") if block else "\n".join(lines)
        if i == 0 and hold:
            b.notes = assess_note(b.notes, HOLD_DAY_LINE)
        elif i > 0 and not hold and sb.steppable(b):
            b.notes = assess_note(b.notes, NO_STEP_LINE)
    here = keys & {b.movement_key for b in blocks}
    if hold:
        return [f"no step (live): a hold day ({(rx.get('fatigue') or {}).get('state')}) — no in-session load step on any lift"]
    return [f"no step (live): {len(here)} held / cut / flagged lift(s) keep their load all session"] if here else []


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
        if _is_big(b) and own and own != band:
            out.append(f"{b.movement_key}: {own} under '{band} on big lifts'")
    return out


def coherent_head(head: str, blocks: list[Any]) -> str:
    """The session line restated so it never contradicts a big lift: the band every big lift shares, or the day alone when
    they differ (each big lift then states its own target)."""
    from training import session_block as sb

    m = sb.SESSION_LINE_RE.match(head or "")
    if not m:
        return head
    band = f"RPE {m.group('band')}"
    targets = {_own_effort(b.notes) or band for b in blocks if _is_big(b)}
    if len(targets) == 1:
        (t,) = targets
        return head if t == band else f"{m.group('day')} · {t} on big lifts"
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
    out = block_rule(block, rx, blocks)
    head = out.split("\n", 1)[0]
    new = coherent_head(head, blocks)
    return new + out[len(head) :] if new != head else out


# ── 5. the stop line ─────────────────────────────────────────────────────────
def symptom_text(settings: dict[str, Any] | None) -> str:
    """The configured symptom line: a SYMPTOM_PRESETS name resolves to its text; anything else is the owner's literal."""
    raw = str((settings or {}).get("symptom_line") or "").strip()
    return SYMPTOM_PRESETS.get(raw, raw)


def lifting_day_symptom(blocks: list[Any], settings: dict[str, Any] | None) -> None:
    """IN PLACE: with `symptom_line_on_lifting_days`, the symptom line as exercise 1's last lines (idempotent)."""
    text = symptom_text(settings)
    if not blocks or not text or not (settings or {}).get("symptom_line_on_lifting_days"):
        return
    note = blocks[0].notes or ""
    if text not in note:
        blocks[0].notes = f"{note}\n{text}".strip()
