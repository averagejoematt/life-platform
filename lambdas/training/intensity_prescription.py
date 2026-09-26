"""
intensity_prescription.py — read the RPE ceiling a routine actually prescribed (#3714).

Adherence used to mean "did the right number of sets". A session trained to failure
reported 100% because the calculator counted sets and never looked at the `rpe` Hevy
stores on every set. This module supplies the missing half: the ceiling the
prescription itself named, so a performed set can be compared against it.

THE THRESHOLD PROBLEM (ADR-105). There is no invented cutoff in this file. Nothing
here says "RPE > 8.5 is non-compliant". The ceiling is READ from the routine's own
prescription and the comparison is a plain `performed > prescribed` with ZERO
tolerance — the only number that is not read off the prescription is the RIR→RPE
anchor below, and that is a definition, not a threshold.

WHERE A CEILING CAN LIVE. Three forms, all of them the routine's own words:

  1. `inputs_snapshot["recovery_branches"]["exercises"][movement_key]` — the
     structured GREEN/YELLOW/RED branch dict written by the recovery-adaptive
     authoring path (`mcp/recovery_authoring.build_top_set_branches`). GREEN is the
     AUTHORED CEILING by that module's own subtract-only rule ("nothing lets him
     exceed the GREEN ceiling on the day"), so GREEN's `rpe_cap` is the ceiling.
  2. An explicit RPE in the exercise's own notes — "RPE 8 cap.", "top set RPE 9",
     "RPE 7-8". (Live: the 2026-09-08 pull routine's lat_pulldown note is literally
     "RPE 8 cap. 120 lb anchored on 3 Sept".)
  3. An RIR in the exercise's own notes — "Target 3 RIR", "4+ RIR", "2-3 RIR on the
     last set". This is how the chat-authored routines of cycle 17 actually express
     intensity, so a reader that only understood "RPE" would be blind to every one of
     them. RIR converts by DEFINITION on the RIR-based RPE scale (Zourdos et al.
     2016), the same scale Hevy logs against: **RPE = 10 − RIR**. 3 RIR IS RPE 7. That
     identity is a unit conversion, not a population cutoff — but it is named here
     rather than buried so the one imported number in this file is visible.

Falls back to the routine-level notes when an exercise names no intensity of its own
(the session block — "RECOVERY BRANCH … GREEN 67-100: … 1-2 RIR" — is a real
prescription for the day). Basis is always reported alongside the number, so a
consumer can tell an exercise-specific ceiling from a session-wide fallback.

A ROUTINE NOTE CAN NAME A MOVEMENT (#4160). "Squat novel-again: exposure 1 of 3, RPE 7
max." (live, 09-24, `b1b9960468f374e30dcdeca8630dd18f`) used to be read as a
SESSION-WIDE ceiling — every other movement in that session (RDL, leg press, leg curl,
calf press) was graded against RPE 7 too, because `resolve_ceiling` only ever handed
`routine_notes` to `read_ceiling` as one undifferentiated block.

THE RULING (#4160): a routine-note clause that NAMES a movement is scoped to the
movements it names. Only a clause that names none stays session-wide. Grammar, applied
clause-by-clause (`routine_notes` split on `.`/`;`/newline):

  * a clause is SCOPED when it opens with a short leading phrase (<=4 words) followed
    immediately by `:` or a dash (`-`/`–`/`—`) — "Squat novel-again: … RPE 7 max.",
    "OHP - RPE 8 max." The leading phrase is the named movement.
  * a clause with no such leading name-then-separator shape is UNSCOPED and reads
    session-wide, exactly as before this change — "Pull, RPE 8 hard cap." has a comma,
    not a name separator, so "Pull" is prose, not a scope.
  * a SCOPED clause's ceiling applies only to a movement whose catalog title (the
    caller's own resolved title — see `movement_title` below) shares a word with the
    named phrase (matched longest-phrase-first, so "Squat novel-again" matches "Squat
    (Barbell)" on "squat" once the descriptive suffix fails to match in full). A movement
    whose title does NOT share a word is excluded from that clause's ceiling — it is
    never treated as session-wide by a clause that named someone else.

`resolve_ceiling`'s new `movement_title` parameter carries the name to scope against.
It is the CALLER's job to resolve a movement_key to its catalog title (reusing the
catalog lookup the caller already has — `adherence_calc._movement_title_for_classification`,
built for #4073) and pass it in; this module stays pure/stdlib-only and never reads the
catalog itself, so there is no second movement-name matcher. Passing no `movement_title`
(the pre-#4160 call shape) reads `routine_notes` as one block exactly as before —
existing callers are unaffected.

MOST-PERMISSIVE WINS, deliberately. A block of prose can name several intensities
("Target 3 RIR. PERFORMANCE-GATED: if set 1 moves at 4+ RIR, climb…"). Taking the
HIGHEST implied RPE ceiling is the conservative read: it minimises false
"over ceiling" flags, so a flagged set is one no reading of the prescription allows.
The same rule picks the permissive end of a range ("2-3 RIR" → the 2-RIR end → RPE 8;
"RPE 7-8" → 8).

Pure + stdlib only: no boto3, no repo config, no I/O. Unit-testable without AWS.
"""

from __future__ import annotations

import re
from typing import Any

# The RIR-based RPE scale's defining identity (Zourdos et al. 2016), the scale Hevy
# logs against. NOT a threshold — a unit conversion. A prescription of N reps in
# reserve is a prescription of RPE (10 - N).
RIR_RPE_ANCHOR = 10.0

# RPE is bounded 1..10 on that scale; a parse outside it is clamped rather than
# trusted (a stray "RPE 155" from a load number adjacent to the word would otherwise
# mint an unreachable ceiling that silently excuses everything).
RPE_MIN = 1.0
RPE_MAX = 10.0

_NUM = r"\d+(?:\.\d+)?"
# A ceiling word may sit BETWEEN "RPE" and the number as well as after it. Both word
# orders are live: "RPE 8 cap." (2026-09-08 lat_pulldown) and "RPE cap 9." (2026-09-13
# legs, session-level). The first sweep of live routines read only the first form and
# silently reported six 09-13 movements `unprescribed` against a session that had in
# fact capped them — which is why this list exists at all.
_CEILING_WORD = r"(?:cap(?:ped)?(?:\s+at)?|ceiling|max(?:imum)?|target|of)"
# "RPE 8", "RPE 7-8", "rpe@8", "top set RPE 9", "RPE 8 cap", "RPE cap 9"
_RPE_RE = re.compile(rf"\brpe\s*(?:{_CEILING_WORD}\s+)?@?\s*({_NUM})(?:\s*(?:[-–—]|\s+to\s+)\s*({_NUM}))?", re.IGNORECASE)
# "3 RIR", "4+ RIR", "2-3 RIR", "1-2 RIR"
_RIR_RE = re.compile(rf"\b({_NUM})\s*(?:\+\s*)?(?:(?:[-–—]|\s+to\s+)\s*({_NUM})\s*\+?\s*)?rir\b", re.IGNORECASE)

# #4160 — a routine note is read clause-by-clause so a movement-naming clause can be
# scoped rather than session-wide. Split on sentence/clause boundaries.
_CLAUSE_SPLIT_RE = re.compile(r"[.\n;]+")
# A clause opens with a short leading phrase (<=4 words) immediately followed by a
# colon or dash: "Squat novel-again: …", "OHP - …". A comma does not count ("Pull, RPE
# 8 hard cap." is prose, not a name) — that distinction is deliberate, it is what keeps
# every pre-#4160 session-wide note reading session-wide.
_SCOPE_NAME_RE = re.compile(r"^\s*([A-Za-z][\w/&()'+]*(?:\s+[\w/&()'+-]+){0,3}?)\s*[:\-–—]\s*\S")


def _clamp(v: float) -> float:
    return max(RPE_MIN, min(RPE_MAX, v))


def read_ceiling(text: str | None) -> tuple[float | None, str | None]:
    """The most permissive RPE ceiling named anywhere in one block of prescription prose.

    Returns (ceiling, form) where form is "rpe", "rir" or "rpe+rir" — or (None, None)
    when the text names no intensity at all. Absence is absence: this never returns a
    default ceiling, because a default would be exactly the invented threshold this
    module exists to avoid.
    """
    if not text:
        return None, None
    found: list[float] = []
    forms: set[str] = set()

    for m in _RPE_RE.finditer(text):
        vals = [float(g) for g in m.groups() if g is not None]
        if vals:
            found.append(_clamp(max(vals)))  # the permissive end of an RPE range
            forms.add("rpe")

    for m in _RIR_RE.finditer(text):
        vals = [float(g) for g in m.groups() if g is not None]
        if vals:
            # Fewest reps in reserve = hardest allowed = the permissive end.
            found.append(_clamp(RIR_RPE_ANCHOR - min(vals)))
            forms.add("rir")

    if not found:
        return None, None
    form = "rpe+rir" if len(forms) > 1 else next(iter(forms))
    return max(found), form


def _normalize_words(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def _strip_parenthetical(s: str | None) -> str:
    return re.sub(r"\([^)]*\)", " ", s or "")


def _extract_scope_name(clause: str) -> str | None:
    """The leading movement-name phrase of one clause, or None when the clause has no
    name-then-separator shape (#4160 grammar, see module docstring)."""
    m = _SCOPE_NAME_RE.match(clause)
    if not m:
        return None
    name = m.group(1).strip()
    # A colon after the ceiling word itself ("RPE: 7") must not be read as a name.
    if not name or _RPE_RE.search(name) or _RIR_RE.search(name):
        return None
    return name


def _name_matches_title(name: str, title: str | None) -> bool:
    """Does the routine note's named phrase name this movement's catalog title?

    Longest-phrase-first: try the whole normalized name, then progressively drop the
    trailing word. "Squat novel-again" fails whole ("squat novel again" is not in
    "squat barbell") and then matches on "squat" alone — the trailing words are the
    note's own exposure/set prose, not part of the movement's name, and this is how a
    single-word name still resolves without requiring the note to spell the title out
    in full. A multi-word catalog title ("Leg Press") matches whole when the note names
    it in full, so two different movements sharing one generic word ("leg") are never
    both claimed by a name that only ever offers the word "leg" alone.
    """
    title_n = _normalize_words(_strip_parenthetical(title))
    words = _normalize_words(name).split()
    if not words or not title_n:
        return False
    for n in range(len(words), 0, -1):
        candidate = " ".join(words[:n])
        if re.search(rf"\b{re.escape(candidate)}\b", title_n):
            return True
    return False


def _routine_notes_ceiling(routine_notes: str | None, movement_title: str | None) -> tuple[float | None, str | None]:
    """The routine-note ceiling for ONE movement (#4160).

    `movement_title` is None for callers that predate the scoping feature (or that
    could not resolve a title): the whole block reads exactly as `read_ceiling` always
    has, unscoped. When a title IS given, each clause is read on its own — a clause
    that names a movement contributes its ceiling only when the name matches this
    movement's title (`_name_matches_title`); a clause that names no movement (or that
    names a DIFFERENT one) is excluded rather than defaulting to session-wide, because a
    routine note that explicitly names another movement is not silent about this one —
    it is silent BY EXCLUSION, and #4073's program-default fallback is what should apply.
    Most-permissive-wins still holds across whatever remains, same as `read_ceiling`.
    """
    if not routine_notes:
        return None, None
    if movement_title is None:
        return read_ceiling(routine_notes)

    caps: list[float] = []
    forms: set[str] = set()
    for clause in _CLAUSE_SPLIT_RE.split(routine_notes):
        cap, form = read_ceiling(clause)
        if cap is None:
            continue
        name = _extract_scope_name(clause)
        if name is not None and not _name_matches_title(name, movement_title):
            continue  # named a DIFFERENT movement — excluded, not session-wide
        caps.append(cap)
        forms.add(form)

    if not caps:
        return None, None
    form = "rpe+rir" if len(forms) > 1 else next(iter(forms))
    return max(caps), form


def _branch_ceiling(branches: Any, movement_key: str) -> float | None:
    """GREEN's `rpe_cap` for one movement out of a stashed recovery_branches dict.

    GREEN is the authored ceiling (recovery_authoring's subtract-only invariant), so
    it — not YELLOW, not the recommended branch — is what "over the prescription"
    must be measured against.
    """
    try:
        per_ex = ((branches or {}).get("exercises") or {}).get(movement_key) or {}
        cap = (per_ex.get("green") or {}).get("rpe_cap")
        return _clamp(float(cap)) if cap is not None else None
    except (TypeError, ValueError, AttributeError):
        return None


def resolve_ceiling(
    movement_key: str,
    exercise_notes: str | None,
    routine_notes: str | None = None,
    recovery_branches: Any = None,
    movement_title: str | None = None,
) -> dict[str, Any]:
    """Resolve ONE movement's prescribed RPE ceiling. Precedence: structured branch →
    the exercise's own notes → the session-level routine notes.

    Returns {"rpe": float|None, "basis": str|None}. `basis` names where the number came
    from ("recovery_branches:green", "exercise_notes:rir", "routine_notes:rpe", …) so a
    reader can tell a movement-specific ceiling from a session-wide fallback — and so a
    `None` ceiling is legible as "the plan never said", not as "compliant".

    `movement_title` (#4160) is this movement's catalog title, supplied by the caller so
    a routine-note clause that NAMES a movement ("Squat novel-again: … RPE 7 max.")
    scopes to that movement instead of every movement in the session — see the module
    docstring for the ruling and grammar. Omit it (the pre-#4160 call shape) to read
    `routine_notes` as one undifferentiated block, unchanged.
    """
    cap = _branch_ceiling(recovery_branches, movement_key)
    if cap is not None:
        return {"rpe": cap, "basis": "recovery_branches:green"}

    cap, form = read_ceiling(exercise_notes)
    if cap is not None:
        return {"rpe": cap, "basis": f"exercise_notes:{form}"}

    cap, form = _routine_notes_ceiling(routine_notes, movement_title)
    if cap is not None:
        return {"rpe": cap, "basis": f"routine_notes:{form}"}

    return {"rpe": None, "basis": None}


def is_working_set(s: dict[str, Any]) -> bool:
    """Warm-up sets are not graded against the top-set ceiling.

    Hevy stamps `type` on every set; the 2026-09-07 bench opened with three `warmup`
    sets carrying no RPE at all. Counting those as "RPE absent" would report a hole
    that isn't one. Anything that is not explicitly a warmup is a working set —
    unknown types grade, they do not silently drop out.
    """
    return str(s.get("type") or "normal").lower() != "warmup"


def grade_sets(ceiling: float | None, sets: list[dict[str, Any]]) -> dict[str, Any]:
    """Grade one movement's PERFORMED sets against its prescribed ceiling.

    ADR-104 absence semantics, three ways:
      • ceiling is None  → status "unprescribed". Not graded, not counted compliant.
      • rpe is None      → counted in `sets_rpe_absent`, kept OUT of the denominator.
                           An unlogged RPE is never evidence of compliance.
      • no working set carried an rpe → status "unreadable", pct None (never 100).

    Comparison is strict `performed > ceiling` with no tolerance band — inventing a
    "close enough" margin would be inventing the threshold.
    """
    working = [s for s in (sets or []) if is_working_set(s)]
    graded: list[float] = []
    absent = 0
    for s in working:
        rpe = s.get("rpe")
        try:
            val = float(rpe) if rpe not in (None, "") else None
        except (TypeError, ValueError):
            val = None
        if val is None:
            absent += 1
        else:
            graded.append(val)

    out: dict[str, Any] = {
        "ceiling_rpe": ceiling,
        "working_sets": len(working),
        "sets_graded": len(graded),
        "sets_rpe_absent": absent,
        "max_rpe": max(graded) if graded else None,
        "sets_over_ceiling": 0,
        "max_overage": None,
        "pct_within_ceiling": None,
    }
    if ceiling is None:
        out["status"] = "unprescribed"
        return out
    if not graded:
        out["status"] = "unreadable"
        return out

    over = [v for v in graded if v > ceiling]
    out["status"] = "graded"
    out["sets_over_ceiling"] = len(over)
    out["max_overage"] = round(max(over) - ceiling, 1) if over else 0.0
    out["pct_within_ceiling"] = round((len(graded) - len(over)) / len(graded) * 100, 1)
    return out
