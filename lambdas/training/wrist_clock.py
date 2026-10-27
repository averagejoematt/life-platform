"""wrist_clock.py — a cardio block as a clock rule he can follow by glancing at his watch (#5374, epic #5050).

WHY THIS EXISTS

The owner rides with an iPad over the console (shows, podcasts), so he cannot see or set up a workout on the
machine, and the Apple Watch gives no haptic or alert: the ONLY trigger is a glance at the watch's clock (owner,
2026-10-25, attended Session CG). A block that says "the hill program" assumes a machine he cannot use. His own
10-25 ride shows what works, in his words (his Hevy note, verbatim):

    8/12 for 2 mins for 20 mins / 8/14 for 2 mins for 20 mins / 8 level up every 2 mins from 40 to 60 to level 18

So the block is stated as ONE rule line: what to set at which minute of the session clock. Owner amendment
2026-10-26 (attended, Session CH): at most THREE numbers to remember per line (levels, incline steps, resistance)
— a ramp like "+1 level every 2 min from 40 to 60" is one rule, not eleven levels.

THE RULE GRAMMAR (`RULE_RE`; `cardio_note` line 1 carries it between the shape and the effort words)

    RULE    := CLAUSE ( " · then " CLAUSE )* [ " · check in every " N " min" ]
    CLAUSE  := HOLD | ALT | RAMP | SPRINT
    HOLD    := VALUE TIME                                   "level 11 for 30"        one level held
    ALT     := VALUE "/" VALUE " every " N " min " TIME     "8/12 every 2 min for 20" A, then B, every N min
    RAMP    := DELTA " every " N " min " TIME               "+1 level every 2 min from 40 to 60"
    SPRINT  := VALUE " for " W " min every " M " min " TIME "12 for 2 min every 4 min from 10 to 30"
    TIME    := "for " M          (from the previous clause's end, or minute 0)
             | "from " T1 " to " T2                          (session-clock minutes)
    VALUE   := ["level "] N | N "%" | "base" ["+" N]          a bike/rower/elliptical level, a treadmill incline,
                                                              or the level he rides when none is on record
    DELTA   := ("+" | "-") N (" level" | "%")

READING A CLAUSE ON THE CLOCK (the semantics every reader shares — `resolve`)

  * HOLD: the value from its start to its end.
  * ALT: A for N min, then B for N min, alternating, starting with A.
  * RAMP: the step lands at T1 and again every N min — block i (from 0) sits at start + step × (i + 1), so
    "+1 level every 2 min from 40 to 60" from level 8 rides 9, 10 … 18 and ends at 18 (his own "to level 18").
    The start is the level he was on (the previous clause), or the level his own note names ("8 level up …").
  * SPRINT: W min at the value at the start of every M-min period, the rest of the period at the level before.

THE GRID (owner, 2026-10-25): every change point is a whole minute on a 2-, 5- or 10-minute grid of the session
clock (:02, :04 … or :05, :10 …), so a glance can tell whether a change is due (`off_grid`).

THE OWNER'S NOTE GRAMMAR (`parse_note`) is a superset: "A/B for N mins for M mins", "+X level(s) every N mins from T1
to T2", "<L> level up every N mins from T1 to T2 to level <L2>", "sprint N every M" — separated by " / ", "then", ";",
"," or a new line. Every rendered rule parses under it too, so a prescribed shape and a performed one are the same
structure (`grade`). A segment it cannot read is kept, verbatim, under `unparsed`; nothing is guessed.

Pure: no I/O, no clock.
"""

from __future__ import annotations

import re
from typing import Any

WRIST_CLOCK_VERSION = "wrist-clock@1.0.0"

# OWNER-CHOSEN (2026-10-25 / amendment 2026-10-26), not platform constants: the grid and the memory limit.
GRID_MINUTES = (2, 5, 10)
MAX_NUMBERS = 3

CLAUSE_TYPES = ("hold", "alternate", "ramp", "sprint")
FAMILIES = ("steady", "hills", "intervals")

# ── the strict grammar (what `cardio_note` renders) ─────────────────────────────────────
_NUM = r"\d{1,3}(?:\.\d)?"
_VAL = rf"(?:{_NUM}%|(?:level )?{_NUM}|base(?:\+\d{{1,2}})?)"
_DELTA = rf"[+-]{_NUM}(?:%| level)"
_TIME = r"(?:for \d{1,3}|from \d{1,3} to \d{1,3})"
_CLAUSE = (
    rf"(?:{_VAL} for \d{{1,2}} min every \d{{1,2}} min {_TIME}"  # SPRINT
    rf"|{_VAL}/{_VAL} every \d{{1,2}} min {_TIME}"  # ALT
    rf"|{_DELTA} every \d{{1,2}} min {_TIME}"  # RAMP
    rf"|{_VAL} {_TIME})"  # HOLD
)
RULE_PATTERN = rf"{_CLAUSE}(?: · then {_CLAUSE})*(?: · check in every \d{{1,2}} min)?"
RULE_RE = re.compile(rf"^{RULE_PATTERN}$")

# ── the lenient grammar (his notes; every strict clause also matches) ───────────────────
_LV = r"(?:(?:level|lvl|l)\s*)?"
_M = r"(?:\s*min)?"


def _v(p: str) -> str:
    """A value: a number (a level, or an incline with %), or "base" / "base+N" — named groups prefixed `p`."""
    return rf"(?:{_LV}(?P<{p}n>\d{{1,3}}(?:\.\d)?)\s*(?P<{p}pct>%?)|(?P<{p}base>base)(?:\s*\+\s*(?P<{p}plus>\d{{1,2}}))?)"


_T = rf"(?:for\s+(?P<dur>\d{{1,3}}){_M}|from\s+(?P<t1>\d{{1,3}}){_M}\s+to\s+(?P<t2>\d{{1,3}}){_M})"
_P_ALT = re.compile(rf"^{_v('a')}\s*/\s*{_v('b')}\s+(?:every|for)\s+(?P<every>\d{{1,2}}){_M}\s+{_T}$")
_P_RAMP = re.compile(
    rf"^(?:{_v('s')}\s+)?(?:(?:level|lvl)\s*(?P<word>up|down)|(?P<bare>up|down)|(?P<sign>[+-])\s*(?P<mag>\d{{1,3}}(?:\.\d)?)\s*(?P<u>%|levels?)?)"
    rf"\s+every\s+(?P<every>\d{{1,2}}){_M}\s+{_T}(?:\s+to\s+(?:level\s*)?(?P<to>\d{{1,3}}(?:\.\d)?)\s*%?)?$"
)
_P_SPRINT_WORD = re.compile(
    rf"^sprint(?:\s+(?:at\s+)?{_v('w')})?\s+(?:for\s+)?(?P<work>\d{{1,2}}){_M}\s+every\s+(?P<every>\d{{1,2}}){_M}(?:\s+{_T})?$"
)
_P_SPRINT = re.compile(rf"^{_v('w')}\s+for\s+(?P<work>\d{{1,2}}){_M}\s+every\s+(?P<every>\d{{1,2}}){_M}(?:\s+{_T})?$")
_P_HOLD = re.compile(rf"^{_v('h')}\s+{_T}$")
# #5428 / #5374 box 3: his bare bike log, "Level 11 flat" / "L12" / "Level 11 ramp" (a level held the whole block, the
# block's own duration closes it). The LEVEL WORD is required, so a bare number is never read as a level; a trailing
# " - <words>" comment ("Level 10 flat - big toe throbbing …") is kept, never parsed.
_P_BARE_LEVEL = re.compile(
    r"^(?:level|lvl|l)\s*(?P<n>\d{1,3})(?:\s+(?P<terrain>flat|ramp|hills?|hilly|manual))?(?:\s+[-–—]\s+(?P<comment>\D.*))?$"
)
_P_CHECKIN = re.compile(r"^check\s+in\s+every\s+(\d{1,2})\s*min$")
_SPLIT = re.compile(r"\s*(?:·\s*then\b|·|\n|;|\s/\s|,\s*then\b|\band\s+then\b|\bthen\b|,)\s*", re.IGNORECASE)


def num(s: str | None) -> float | int | None:
    """A number string as an int when whole, else a float; None for an absent one."""
    if s is None or s == "":
        return None
    f = float(s)
    return int(f) if f.is_integer() else f


def _value(m: re.Match[str], p: str) -> tuple[Any, str | None]:
    """(value, unit) for the value named `p`: a number (unit "level" or "%"), "base" / "base+N", or (None, None)."""
    n = m.group(f"{p}n")
    if n is not None:
        return num(n), ("%" if m.group(f"{p}pct") else "level")
    if m.group(f"{p}base"):
        plus = m.group(f"{p}plus")
        return (f"base+{int(plus)}" if plus else "base"), None
    return None, None


def _time(m: re.Match[str]) -> dict[str, int | None]:
    dur, t1, t2 = m.group("dur"), m.group("t1"), m.group("t2")
    if t1 is not None:
        return {"start": int(t1), "end": int(t2)}
    return {"duration": int(dur)} if dur is not None else {}


def _normalise(segment: str) -> str:
    s = segment.strip().lower().replace("−", "-").replace("–", "-")
    s = re.sub(r"\b(?:minutes|minute|mins)\b", "min", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" .")


def parse_clause(segment: str) -> dict[str, Any] | None:
    """One clause of either grammar as a dict (`type` + its numbers, times unresolved), or None when it is none."""
    s = _normalise(segment)
    if not s:
        return None
    m = _P_CHECKIN.match(s)
    if m:
        return {"type": "check_in", "every": int(m.group(1))}
    m = _P_SPRINT_WORD.match(s) or _P_SPRINT.match(s)
    if m:
        value, unit = _value(m, "w")
        return {"type": "sprint", "value": value, "unit": unit, "work": int(m.group("work")), "every": int(m.group("every")), **_time(m)}
    m = _P_ALT.match(s)
    if m:
        a, unit_a = _value(m, "a")
        b, unit_b = _value(m, "b")
        return {"type": "alternate", "values": [a, b], "unit": unit_a or unit_b, "every": int(m.group("every")), **_time(m)}
    m = _P_RAMP.match(s)
    if m:
        start, unit = _value(m, "s")
        word = m.group("word") or m.group("bare")
        if word:
            step: float | int = 1 if word == "up" else -1
            unit_word = None
        else:
            mag = num(m.group("mag")) or 0
            step = mag if m.group("sign") == "+" else -mag
            unit_word = "%" if m.group("u") == "%" else ("level" if m.group("u") else None)
        return {
            "type": "ramp",
            "from_value": start,
            "step": step,
            "unit": unit or unit_word,
            "every": int(m.group("every")),
            **_time(m),
            "to_stated": num(m.group("to")),
        }
    m = _P_HOLD.match(s)
    if m:
        value, unit = _value(m, "h")
        return {"type": "hold", "value": value, "unit": unit, **_time(m)}
    m = _P_BARE_LEVEL.match(s)
    if m:
        terrain = m.group("terrain")
        out: dict[str, Any] = {"type": "hold", "value": int(m.group("n")), "unit": "level"}
        if terrain:
            out["terrain"] = "hills" if terrain.startswith("hill") else terrain
        if m.group("comment"):
            out["comment"] = m.group("comment").strip()
        return out
    return None


# ── resolving clauses onto the session clock ────────────────────────────────────────────
def _blocks(clause: dict[str, Any], level: Any) -> tuple[list[tuple[int, int, Any]], Any]:
    """(the clause's blocks as (start, end, value), the value he is on at its end). Values may be "base" strings."""
    start, end, kind = clause["start"], clause["end"], clause["type"]
    out: list[tuple[int, int, Any]] = []
    if end is None or end <= start:
        return out, level
    if kind == "hold":
        value = clause["value"] if clause["value"] is not None else level
        return [(start, end, value)], value
    every = max(1, int(clause.get("every") or 1))
    if kind == "alternate":
        a, b = clause["values"]
        t, i, value = start, 0, a
        while t < end:
            value = a if i % 2 == 0 else b
            out.append((t, min(t + every, end), value))
            t, i = t + every, i + 1
        return out, value
    if kind == "ramp":
        base = clause.get("from_value")
        base = level if base is None else base
        clause["from_resolved"] = base
        t, i, value = start, 0, base
        while t < end:
            value = base + clause["step"] * (i + 1) if isinstance(base, (int, float)) else None
            value = num(f"{value:.1f}") if isinstance(value, float) else value
            out.append((t, min(t + every, end), value))
            t, i = t + every, i + 1
        clause["to_resolved"] = value
        return out, value
    # sprint: W min at the value at the head of every M-min period, the rest at the level he was on
    work = int(clause.get("work") or 0)
    rest = level
    clause["base_resolved"] = rest
    t = start
    while t < end:
        hi = min(t + work, end)
        out.append((t, hi, clause["value"]))
        if hi < min(t + every, end):
            out.append((hi, min(t + every, end), rest))
        t += every
    return out, rest


def resolve(clauses: list[dict[str, Any]], total_min: int | None = None) -> dict[str, Any]:
    """The clauses laid on the session clock: per-clause start/end, the blocks, the levels ridden and the minutes at
    each, the change points. `total_min` (the block's own duration) closes a clause with no end ("sprint 2 every 10")."""
    rules = [dict(c) for c in clauses if c.get("type") in CLAUSE_TYPES]
    check_in = next((c["every"] for c in clauses if c.get("type") == "check_in"), None)
    cursor, level = 0, None
    blocks: list[tuple[int, int, Any]] = []
    for c in rules:
        start = c.get("start")
        start = cursor if start is None else start
        end = c.get("end")
        if end is None and c.get("duration") is not None:
            end = start + int(c["duration"])
        if end is None and total_min is not None and int(total_min) > start:
            end = int(total_min)
        c["start"], c["end"] = start, end
        c.pop("duration", None)
        b, level = _blocks(c, level)
        blocks.extend(b)
        cursor = end if end is not None else cursor
    minutes: dict[str, int] = {}
    numeric = [(s, e, v) for s, e, v in blocks if isinstance(v, (int, float))]
    for s, e, v in numeric:
        minutes[_key(v)] = minutes.get(_key(v), 0) + (e - s)
    levels = sorted({v for _, _, v in numeric})
    weighted = sum(v * (e - s) for s, e, v in numeric)
    timed = sum(e - s for s, e, _ in numeric)
    points = sorted({s for s, _, _ in blocks if s > 0} | {e for _, e, _ in blocks if e and e < (cursor or 0)})
    changes = [p for p in points if _value_at(blocks, p - 1) != _value_at(blocks, p)]
    unit = next((c.get("unit") for c in rules if c.get("unit")), None)
    return {
        "clauses": rules,
        "check_in_every": check_in,
        "unit": unit or "level",
        "total_min": cursor if rules else None,
        "blocks": [[s, e, v] for s, e, v in blocks],
        "change_points": changes,
        "level_minutes": minutes,
        "levels": levels,
        "base_level": levels[0] if levels else None,
        "top_level": levels[-1] if levels else None,
        "mean_level": round(weighted / timed, 1) if timed else None,
        "family": family(rules),
    }


def _key(v: float | int) -> str:
    return f"{v:g}"


def _value_at(blocks: list[tuple[int, int, Any]], minute: int) -> Any:
    for s, e, v in blocks:
        if s <= minute < e:
            return v
    return None


def family(clauses: list[dict[str, Any]]) -> str:
    """steady | hills | intervals, by where the minutes go: alternations and sprints are intervals, ramps are hills,
    holds are steady. A mixed ride takes the family with more minutes (intervals on a tie)."""
    mins = {"steady": 0, "hills": 0, "intervals": 0}
    for c in clauses:
        span = (c.get("end") or 0) - (c.get("start") or 0)
        span = span if span > 0 else 1
        mins[{"hold": "steady", "ramp": "hills"}.get(c["type"], "intervals")] += span
    if mins["intervals"] and mins["intervals"] >= mins["hills"]:
        return "intervals"
    if mins["hills"]:
        return "hills"
    return "steady"


# ── reading a note / a rule ─────────────────────────────────────────────────────────────
def parse_note(note: str | None, total_min: int | None = None) -> dict[str, Any]:
    """His note (or a rendered rule) as a structured shape.

    `status`: ``shaped`` — at least one alternation, ramp or sprint was read (a ride with more than one level on the
    clock); ``steady`` — only held levels were read; ``none`` — nothing in the note is a clock clause. Segments that are
    not clauses are kept verbatim in `unparsed`; they never block the clauses that did read."""
    text = (note or "").strip()
    out: dict[str, Any] = {"version": WRIST_CLOCK_VERSION, "status": "none", "raw": text, "unparsed": []}
    if not text:
        return out
    clauses: list[dict[str, Any]] = []
    for seg in _SPLIT.split(text):
        if not seg or not seg.strip():
            continue
        c = parse_clause(seg)
        if c is None:
            out["unparsed"].append(seg.strip())
        else:
            clauses.append(c)
    if not any(c["type"] in CLAUSE_TYPES for c in clauses):
        return out
    out.update(resolve(clauses, total_min))
    out["status"] = "shaped" if any(c["type"] != "hold" for c in out["clauses"]) else "steady"
    return out


# ── his treadmill grammar (#5374 box 3, owner 2026-10-27: "a note on what i do on the machine … to feedback loop") ──
# "<speed> / <incline>[ incline|%]" is a steady block at that speed (mph) and incline (%); a change is the same pair with
# "from <min>" or "at <min>" ("3.3 / 1.5, 4.0 / 3 from 20"). His older forms read too: "3.3 mph 1.5 incline",
# "1.5 incline at 3mph", "3.1 mph and 1.0 incline", "0.5 incline 3mph". Segments split on "," ";" "then" or a new line —
# never on " / ", which is his speed/incline separator here (on the bike it separates clauses, `parse_note`).
_WALK_SPLIT = re.compile(r"\s*(?:,|;|\n|\bthen\b)\s*", re.IGNORECASE)
_W_NUM = r"\d{1,2}(?:\.\d{1,2})?"
_W_TIME = re.compile(
    r"\s+(?:(?:from|at)\s+(?:min\s*)?(?P<t1>\d{1,3})(?:\s*min)?(?:\s+to\s+(?:min\s*)?(?P<t2>\d{1,3})(?:\s*min)?)?"
    r"|for\s+(?P<dur>\d{1,3})(?:\s*min)?)$"
)
_W_SPEED = re.compile(rf"(?P<v>{_W_NUM})\s*mph\b")
_W_INCLINE = re.compile(rf"(?P<v>{_W_NUM})\s*(?:%|incline\b)(?:\s*incline\b)?|incline\s+(?:of\s+|at\s+)?(?P<w>{_W_NUM})\s*%?")
_W_SLASH = re.compile(rf"^(?P<s>{_W_NUM})\s*/\s*(?P<i>{_W_NUM})$")
_W_FILLER = re.compile(r"^(?:[/,@&]|and|at|with|mph|incline|%|\s)*$")
WALK_SPEED_MPH = (0.5, 12.0)  # a treadmill belt's plausible walking-to-running range; outside it the pair is not a speed
WALK_INCLINE_PCT = (-3.0, 30.0)


def _walk_segment(segment: str, treadmill: bool) -> dict[str, Any] | None:
    """One "<speed> / <incline>" segment as {speed_mph, incline_pct, start?, end?, duration?}, or None when it is not one.
    A bare "3 / 1" needs the machine to be a treadmill (or a decimal) — on a bike "8/12" is his level alternation."""
    s = _normalise(segment)
    time: dict[str, int] = {}
    tm = _W_TIME.search(s)
    if tm:
        if tm.group("t1") is not None:
            time["start"] = int(tm.group("t1"))
            if tm.group("t2") is not None:
                time["end"] = int(tm.group("t2"))
        else:
            time["duration"] = int(tm.group("dur"))
        s = s[: tm.start()].strip()
    speed = incline = None
    rest = s
    sm = _W_SPEED.search(rest)
    if sm:
        speed = float(sm.group("v"))
        rest = rest[: sm.start()] + " " + rest[sm.end() :]  # noqa: E203
    im = _W_INCLINE.search(rest)
    if im:
        incline = float(im.group("v") or im.group("w"))
        rest = rest[: im.start()] + " " + rest[im.end() :]  # noqa: E203
    rest = rest.strip()
    if speed is None and incline is None:
        m = _W_SLASH.match(rest)
        if not m or not (treadmill or "." in rest):
            return None
        speed, incline, rest = float(m.group("s")), float(m.group("i")), ""
    elif speed is None or incline is None:
        # one side named its unit; the other is the bare number left over ("3.3 / 1.5 incline" -> 3.3 is the speed)
        m = re.fullmatch(rf"(?:[/,@&]|and|at|with|\s)*(?P<v>{_W_NUM})(?:[/,@&]|and|at|with|\s)*", rest)
        if not m:
            return None
        if speed is None:
            speed = float(m.group("v"))
        else:
            incline = float(m.group("v"))
        rest = ""
    if not _W_FILLER.match(rest):
        return None
    if not (WALK_SPEED_MPH[0] <= speed <= WALK_SPEED_MPH[1]) or not (WALK_INCLINE_PCT[0] <= incline <= WALK_INCLINE_PCT[1]):
        return None
    return {"speed_mph": num(f"{speed:g}"), "incline_pct": num(f"{incline:g}"), **time}


def parse_walk(note: str | None, total_min: int | None = None, *, treadmill: bool = False) -> dict[str, Any]:
    """His treadmill note as a structured shape on the session clock (#5374 box 3).

    The same keys as `parse_note` (unit ``%``: the levels are inclines, so `grade` compares a performed walk with a
    prescribed one), plus `segments` — each `{start, end, speed_mph, incline_pct}` — and `speed_mph` (the time-weighted
    mean when every segment's minutes are known, else the first segment's). A segment that is not a speed/incline pair
    is kept verbatim in `unparsed`; a note with none reads `status: none`. Deterministic, no model."""
    text = (note or "").strip()
    out: dict[str, Any] = {"version": WRIST_CLOCK_VERSION, "status": "none", "raw": text, "unparsed": [], "grammar": "walk"}
    if not text:
        return out
    segs: list[dict[str, Any]] = []
    for seg in _WALK_SPLIT.split(text):
        if not seg or not seg.strip():
            continue
        parsed = _walk_segment(seg, treadmill)
        if parsed is None:
            out["unparsed"].append(seg.strip())
        else:
            segs.append(parsed)
    if not segs:
        return out
    # lay the segments on the clock: a segment with no start begins where the last one ended (minute 0 for the first);
    # a segment with no end runs to the next one's start, or to the block's own minutes
    cursor = 0
    for i, sg in enumerate(segs):
        sg["start"] = sg.get("start", cursor)
        if "end" not in sg:
            if "duration" in sg:
                sg["end"] = sg["start"] + int(sg.pop("duration"))
            else:
                nxt = next((x.get("start") for x in segs[i + 1 :] if x.get("start") is not None), None)
                sg["end"] = nxt if nxt is not None else (int(total_min) if total_min else None)
        sg.pop("duration", None)
        cursor = sg["end"] if sg["end"] is not None else sg["start"]
    clauses = [{"type": "hold", "value": sg["incline_pct"], "unit": "%", "start": sg["start"], "end": sg["end"]} for sg in segs]
    out.update(resolve(clauses, total_min))
    timed = [sg for sg in segs if sg["end"] is not None and sg["end"] > sg["start"]]
    if len(timed) == len(segs) and timed:
        mins = sum(sg["end"] - sg["start"] for sg in timed)
        out["speed_mph"] = round(sum(sg["speed_mph"] * (sg["end"] - sg["start"]) for sg in timed) / mins, 1)
    else:
        out["speed_mph"] = segs[0]["speed_mph"]
    inclines = sorted({sg["incline_pct"] for sg in segs})
    out["levels"] = out.get("levels") or inclines
    out["base_level"], out["top_level"] = out["levels"][0], out["levels"][-1]
    if out.get("mean_level") is None:
        out["mean_level"] = round(sum(inclines) / len(inclines), 1)
    out["segments"] = [{k: sg[k] for k in ("start", "end", "speed_mph", "incline_pct")} for sg in segs]
    out["speeds"] = sorted({sg["speed_mph"] for sg in segs})
    out["unit"] = "%"
    pairs = {(sg["speed_mph"], sg["incline_pct"]) for sg in segs}
    out["status"] = "shaped" if len(pairs) > 1 else "steady"
    return out


def walk_signal(text: str | None) -> dict[str, Any]:
    """The treadmill shorthand in one bout as the notes layer's `progression` value fields (`training_notes`): {speed_mph,
    incline_pct} of the first segment, plus `segments` when he changed the setting; {} when the bout is not one."""
    walk = parse_walk(text)
    if walk["status"] == "none":
        return {}
    first = walk["segments"][0]
    out: dict[str, Any] = {"speed_mph": first["speed_mph"], "incline_pct": first["incline_pct"]}
    if len(walk["segments"]) > 1:
        out["segments"] = walk["segments"]
    return out


def parse_rule(rule: str | None) -> dict[str, Any] | None:
    """A rendered rule line, held to the STRICT grammar (`RULE_RE`): its shape, or None when it is off the grammar."""
    if not rule or not RULE_RE.match(rule):
        return None
    shape = parse_note(rule)
    return shape if not shape["unparsed"] else None


def off_grid(shape: dict[str, Any] | None) -> list[int]:
    """Change points that are not on the owner's 2/5/10-minute grid (whole minutes only)."""
    return [p for p in (shape or {}).get("change_points") or [] if not any(p % g == 0 for g in GRID_MINUTES)]


def numbers_to_remember(shape: dict[str, Any] | None) -> list[str]:
    """The distinct machine numbers a rule asks him to hold in his head (levels, inclines, step sizes; never the
    clock minutes): "8/12 every 2 min for 20 · then +1 level every 2 min from 20 to 40" -> 8, 12, 1."""
    seen: list[str] = []

    def add(v: Any) -> None:
        if isinstance(v, str) and v.startswith("base+"):
            v = v[5:]
        if v is None or v == "base":
            return
        k = _key(abs(float(v)))
        if k not in seen:
            seen.append(k)

    for c in (shape or {}).get("clauses") or []:
        if c["type"] == "hold":
            add(c.get("value"))
        elif c["type"] == "alternate":
            for v in c["values"]:
                add(v)
        elif c["type"] == "ramp":
            add(c.get("from_value"))
            add(c.get("step"))
        elif c["type"] == "sprint":
            add(c.get("value"))
    return seen


# ── rendering ───────────────────────────────────────────────────────────────────────────
def _fmt_value(v: Any, unit: str, first: bool) -> str:
    if isinstance(v, str):
        return v
    text = _key(v)
    if unit == "%":
        return text + "%"
    return f"level {text}" if first else text


def _fmt_time(start: int, end: int, first: bool) -> str:
    return f"for {end}" if first and start == 0 else f"from {start} to {end}"


def render(clauses: list[dict[str, Any]], unit: str, check_in_every: int | None = None) -> str:
    """Clauses (each with resolved `start`/`end`) as ONE rule line under `RULE_RE`."""
    parts: list[str] = []
    for i, c in enumerate(clauses):
        first = i == 0
        when = _fmt_time(int(c["start"]), int(c["end"]), first)
        if c["type"] == "hold":
            parts.append(f"{_fmt_value(c['value'], unit, first)} {when}")
        elif c["type"] == "alternate":
            a, b = c["values"]
            parts.append(f"{_fmt_value(a, unit, first)}/{_fmt_value(b, unit, False)} every {c['every']} min {when}")
        elif c["type"] == "ramp":
            sign = "+" if c["step"] > 0 else "-"
            tail = "%" if unit == "%" else " level"
            parts.append(f"{sign}{_key(abs(c['step']))}{tail} every {c['every']} min {when}")
        elif c["type"] == "sprint":
            parts.append(f"{_fmt_value(c['value'], unit, first)} for {c['work']} min every {c['every']} min {when}")
    line = " · then ".join(parts)
    return line + (f" · check in every {check_in_every} min" if check_in_every else "")


def floor_to_grid(minutes: float, step: int = 2) -> int:
    """The largest multiple of `step` at or below `minutes` (never below 0)."""
    return max(0, int(minutes // step) * step)


def steady(value: Any, total: int, check_in_every: int | None = None) -> tuple[list[dict[str, Any]], int | None]:
    """One level the whole block (easy / tempo / the incline walk)."""
    every = check_in_every if check_in_every and total > check_in_every else None
    return [{"type": "hold", "value": value, "start": 0, "end": int(total)}], every


def hill(base: Any, step: float | int, steps: int, every: int, total: int) -> list[dict[str, Any]]:
    """Climb `steps` × `step` every `every` min and come back down, centred after a grid-aligned warm-up at the base;
    the base again to the end. The climb shrinks to fit the block; a block too short to climb holds the base."""
    total = int(total)
    steps = max(0, min(int(steps), (total - every) // (2 * every)))
    if steps <= 0:
        return steady(base, total)[0]
    span = 2 * steps * every
    warm = max(every, floor_to_grid((total - span) / 2, every))
    top = warm + steps * every
    down = top + steps * every
    out = [
        {"type": "hold", "value": base, "start": 0, "end": warm},
        {"type": "ramp", "step": step, "every": every, "start": warm, "end": top},
        {"type": "ramp", "step": -step, "every": every, "start": top, "end": down},
    ]
    if down < total:
        out.append({"type": "hold", "value": base, "start": down, "end": total})
    return out


def intervals(base: Any, hard: Any, efforts: int, work: int, easy: int, total: int) -> list[dict[str, Any]]:
    """`efforts` × (`work` min at `hard`, `easy` min at `base`) after a grid-aligned warm-up at the base; fewer efforts
    when the block is too short to hold them all with a 2-min warm-up; the base again to the end."""
    total, period = int(total), int(work) + int(easy)
    if period <= 0 or efforts <= 0:
        return steady(base, total)[0]
    n = max(0, min(int(efforts), (total - 2) // period))
    if n <= 0:
        return steady(base, total)[0]
    warm = max(2, floor_to_grid(total - n * period))
    end = warm + n * period
    out = [
        {"type": "hold", "value": base, "start": 0, "end": warm},
        {"type": "sprint", "value": hard, "work": int(work), "every": period, "start": warm, "end": end},
    ]
    if end < total:
        out.append({"type": "hold", "value": base, "start": end, "end": total})
    return out


# ── grading a performed shape against the prescribed one ────────────────────────────────
def grade(prescribed: dict[str, Any] | None, performed: dict[str, Any] | None) -> dict[str, Any]:
    """The performed shape against the prescribed one, as named facts — never a percentage, never a threshold.

    `status`: ``prescribed_unread`` (the routine's note carries no clock rule) · ``performed_unread`` (his note names
    no clock clause) · ``same_shape`` (the same family: steady / hills / intervals) · ``different_shape``. Beside it
    the minutes, the levels and the time-weighted mean level of each side, so a reader can say how far apart they are
    without this function deciding what counts as close."""
    pre = prescribed if prescribed and prescribed.get("status") in ("shaped", "steady") else None
    perf = performed if performed and performed.get("status") in ("shaped", "steady") else None

    def side(s: dict[str, Any] | None) -> dict[str, Any] | None:
        if not s:
            return None
        return {k: s.get(k) for k in ("family", "total_min", "levels", "base_level", "top_level", "mean_level", "unit")}

    out: dict[str, Any] = {"version": WRIST_CLOCK_VERSION, "prescribed": side(pre), "performed": side(perf)}
    if pre is None:
        out["status"] = "prescribed_unread"
        return out
    if perf is None:
        out["status"] = "performed_unread"
        out["unparsed"] = (performed or {}).get("unparsed") or []
        return out
    out["status"] = "same_shape" if pre["family"] == perf["family"] else "different_shape"
    if pre.get("mean_level") is not None and perf.get("mean_level") is not None:
        out["mean_level_delta"] = round(float(perf["mean_level"]) - float(pre["mean_level"]), 1)
    if pre.get("top_level") is not None and perf.get("top_level") is not None:
        out["top_level_delta"] = round(float(perf["top_level"]) - float(pre["top_level"]), 1)
    if pre.get("total_min") is not None and perf.get("total_min") is not None:
        out["minutes_delta"] = int(perf["total_min"]) - int(pre["total_min"])
    return out
