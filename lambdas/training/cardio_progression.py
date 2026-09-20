"""cardio_progression.py — the cardio arm of the ADR-068 history cue (#3700).

WHY THIS EXISTS

ADR-068 pulls a factual "Last: …" cue into every generated Hevy routine, so the next
session opens with what the last one actually did. It works — for barbells.
`exercise_history.render_history_cue` reads a top-set weight and a reps list, and a
cardio set carries NEITHER:

    weight = _round_weight(facts.get("last_top_weight_kg", 0))
    reps = facts.get("last_reps_list") or []
    if not weight or not reps:
        return ""          # <- every cardio block lands here

The defect is one branch wider than that, and the outer half is the one that actually
hides the data: `load_recent_history` drops any set whose `reps` is not > 0 before the
renderer ever sees it, so a cycling block is not merely unrendered — it is absent from
the index. Notes and numbers go in and nothing comes back out.

Owner, on #3700: *"If I do cardio in the gym I will detail what I did on that equipment —
and then as I save the performed workout, I want you to pull those comments automatically
so next time you have baselines and know how to increase difficulty or mix it up."* The
outcome is the next prescription; the fields are only the means.

THE FOUR INPUTS, AND WHICH ONES PORT

The issue's own `## Set` enumerates the progression inputs by whether they survive a
change of equipment. This module's posture follows it exactly:

  * `distance_m`, `duration_sec` — portable, captured, and the basis of the trend
    (speed-at-level). Neither touches the note extractor.
  * level — NOT portable (one machine's dial) and prose-only on the wire. This module
    parses it DETERMINISTICALLY from the raw note (`LEVEL_RE`, the same pattern
    `training_notes` uses, held to it by a derivation test) so a level decision never
    depends on the LLM extractor tail. The raw note stays sovereign and is quoted
    verbatim into the cue.
  * HR at level — portable, and NOT joined to the set on the wire. `join_whoop_hr`
    below is that join, and it refuses far more often than it fires (see below).

WHAT THE LIVE DATA ACTUALLY SUPPORTS (verified against DynamoDB 2026-09-19)

Nineteen cycling blocks are on the record; TEN of them carry a note with a single
parseable level, and exactly TWO of those ten can be joined to a ride-scoped Whoop average
HR. That is not a bug in the join — a Hevy exercise block carries no timestamps of its
own, and Whoop's workout records are usually session-scoped ("Cross Training", 18:12–19:18,
spanning two hours of barbell work plus the bike). A session-scoped average HR is not
HR-at-level, so this module declines to substitute one: `join_whoop_hr` returns a NAMED
absence rather than the nearest available number.

The consequence travels into the verdict: HR coverage at the busiest level (10) is n=0, so
the rule runs on speed alone, and `level_verdict` says so in its own output, because speed
alone confounds fitness with effort (the issue's own caution, ADR-104/105).

THE RULE, AND WHY N IS DERIVED RATHER THAN PICKED (ADR-105)

Hold the level. Raise it only when the most recent block of `k` sessions at that level is
faster than the prior block by at least one **within-level standard deviation of his own
speed** — his measured noise, not a chosen percentage. `k` is not picked either: it is the
smallest block size whose mean is precise to half that effect (`sd/sqrt(k) <= effect/2`),
which at `effect = 1 sd` gives `k = 4` and therefore `n_required = 8` sessions at the
level. Below that the verdict is `insufficient_n` and `claims_improvement` is False — no
surface may render "your cardio is improving" off a handful of rides.

WHAT THIS MODULE NEVER DOES

No LLM. No invented number. No interpolated HR. No suggestion below `n_required`. Every
absence is returned as a named status, never as a zero or a silent omission.
"""

from __future__ import annotations

import math
import re
import statistics
from datetime import date
from typing import Any

# THE canonical ISO parser (#1964) — never a private fork. Hevy and Whoop both emit
# `Z`-suffixed UTC, and this states the tz-less semantic so a laptop run and the Lambda
# cannot disagree about what an unsuffixed stamp means.
from common.pacific_time import parse_day_key, parse_iso_utc

CARDIO_PROGRESSION_VERSION = "cardio-progression@1.0.0"

METERS_PER_MILE = 1609.344

# The level pattern. Held byte-identical to `training_notes._LEVEL_SPAN_RE` by
# tests/test_cardio_progression_3700.py::test_level_regex_is_derived_from_the_notes_taxonomy —
# two copies of a parser that disagree is how "level 9" becomes two different facts.
# Deliberately a COPY rather than an import of a private name: this module must keep
# working if the extractor module is unavailable, because the whole point of the
# structured level is that it does not depend on the extractor.
LEVEL_RE = re.compile(r"\b(?:level|lvl|l)\s*(\d{1,3})(?:\s*(?:-|–|/|to)\s*(\d{1,3}))?\b", re.IGNORECASE)

# ── the rule's constants, each one derived and each one stated ────────────────────────
# The smallest speed shift that is distinguishable from his own within-level noise is one
# within-level SD. It is a MULTIPLIER on a measured quantity, not a hand-picked mph.
EFFECT_IN_SD = 1.0
# k = ceil(4 * (sd/effect)^2): the block size whose mean is precise to half the effect.
# At EFFECT_IN_SD = 1.0 this is 4, and the rule needs two such blocks.
BLOCK_K = math.ceil(4.0 * (1.0 / EFFECT_IN_SD) ** 2)
N_REQUIRED_AT_LEVEL = 2 * BLOCK_K

# Whoop workout duration must land within this fraction of the Hevy block duration for the
# join to fire. 10% is wide enough for the start/stop slop of thumbing a watch and narrow
# enough that a 2-hour session record can never match a 30-minute ride (the live failure
# mode: 3,959 s of "Cross Training" against an 1,800 s bike block).
HR_DURATION_TOLERANCE = 0.10
# Slack on the Hevy session window, since the watch is started before the phone app.
HR_WINDOW_SLACK_SEC = 600

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _num(v: Any) -> float | None:
    """float(v) or None. Never 0.0 for an absent value — absence is not zero (ADR-104)."""
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _short_date(iso: str) -> str:
    try:
        y, m, d = str(iso)[:10].split("-")
        return f"{int(d)} {_MONTHS[int(m) - 1]}"
    except (ValueError, IndexError):
        return ""


# ── the structured level ──────────────────────────────────────────────────────────────


def _is_decimal_head(text: str, end: int) -> bool:
    """True when the integer just consumed is followed by `.<digit>` — i.e. it was the
    head of a decimal ("5" of "5.6"), not a level bound."""
    if end < 0 or end + 1 >= len(text):
        return False
    return text[end] == "." and text[end + 1].isdigit()


def structured_level(notes: str | None) -> dict[str, Any]:
    """The level as a STRUCTURED field, parsed deterministically from the raw note.

    Always returns a dict carrying `status`, so "no level" is legible as WHICH absence it
    is and never as a default number:

      ``ok``                  exactly one level reference, a single value -> `level` set
      ``level_range``         one reference but a span ("L9-10") — not a session level
      ``multi_level_session`` two or more distinct references ("level 9 for 20 and then
                              level 6 for 10"): a single number would misreport the ride
      ``no_level_in_note``    nothing matched
      ``no_note``             the exercise carried no note at all

    The `multi_level_session` refusal is not hypothetical — 2026-06-22 and 2026-06-25 are
    both live examples, and both would have been silently mislabelled "level 9".
    """
    text = (notes or "").strip()
    if not text:
        return {"level": None, "status": "no_note", "raw": "", "source": "note_regex_deterministic"}
    spans: list[tuple[int, int]] = []
    for m in LEVEL_RE.finditer(text):
        low = int(m.group(1))
        high = int(m.group(2)) if m.group(2) else low
        # THE RANGE PLAUSIBILITY CHECK, and it is not academic. The live 2026-09-07 note
        # this issue was filed against reads "Level 9 - 5.6 miles": the shared pattern
        # happily matches "9 - 5" as a span and the ride loses its level entirely. A span
        # is only a span when it ASCENDS and its upper bound is not the integer part of a
        # decimal. `training_notes` needs no such check — a calibration anchor reads the
        # span, while this module has to emit a single structured NUMBER.
        if high != low and (high < low or _is_decimal_head(text, m.end(2) if m.group(2) else -1)):
            high = low
        spans.append((low, high))
    out: dict[str, Any] = {"level": None, "raw": text, "source": "note_regex_deterministic", "references": spans}
    if not spans:
        out["status"] = "no_level_in_note"
        return out
    distinct = {s for s in spans}
    if len(distinct) > 1:
        out["status"] = "multi_level_session"
        return out
    low, high = spans[0]
    if low != high:
        out["status"] = "level_range"
        out["level_low"], out["level_high"] = low, high
        return out
    out["level"] = low
    out["status"] = "ok"
    return out


def speed_mph(distance_m: Any, duration_sec: Any) -> float | None:
    """Speed in mph, or None when either input is absent or non-positive.

    None rather than 0.0 on purpose: a ride whose machine shut off mid-session (live,
    2026-09-10) has an unknown distance, and a 0.0 mph entry in a speed series is a
    measurement claim nobody made.
    """
    d, t = _num(distance_m), _num(duration_sec)
    if not d or not t or d <= 0 or t <= 0:
        return None
    return round((d / METERS_PER_MILE) / (t / 3600.0), 2)


def _fmt_duration(duration_sec: Any) -> str:
    t = _num(duration_sec)
    if not t or t <= 0:
        return ""
    total = int(round(t))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


# ── the Whoop join ────────────────────────────────────────────────────────────────────


def join_whoop_hr(
    session_start: Any,
    session_end: Any,
    block_seconds: Any,
    whoop_workouts: list[dict[str, Any]] | None,
    tolerance: float = HR_DURATION_TOLERANCE,
    sibling_block_seconds: list[Any] | None = None,
) -> dict[str, Any]:
    """Average HR for THIS cardio block, or a named refusal. Never a substitute number.

    A Hevy exercise block carries no timestamps, so the only honest join is by duration
    inside the session window: a Whoop workout that (a) starts and ends within the Hevy
    session (plus `HR_WINDOW_SLACK_SEC`), (b) lasts within `tolerance` of the block, and
    (c) actually carries an average HR. Exactly one candidate must survive — two is
    ambiguity, and picking the closer one would be a guess wearing a number's clothes.

    AMBIGUITY RUNS BOTH WAYS, and the second direction is the one that bites. On the live
    2026-09-12 session a 1,739 s Whoop "Hiking" workout matched the 1,800 s CYCLING block
    — and equally matched the 1,800 s WALKING block sitting beside it in the same session.
    A per-block join that only looks at its own block sees one candidate and reports a
    heart rate for the bike that was almost certainly the treadmill. `sibling_block_seconds`
    is the other blocks' durations, and any candidate that also matches one of them is
    refused as `ambiguous_sibling_block`.

    `status` values: ``ok`` · ``no_block_duration`` · ``no_session_window`` ·
    ``no_whoop_workouts`` · ``no_ride_scoped_match`` · ``ambiguous_match`` ·
    ``ambiguous_sibling_block``.

    On every non-``ok`` status `average_heart_rate` is None. The session-level average is
    deliberately NOT used as a fallback: over a two-hour session that is a number about
    barbells, and calling it HR-at-level would be the exact ADR-104 violation this issue
    was filed against.
    """
    block = _num(block_seconds)
    out: dict[str, Any] = {
        "average_heart_rate": None,
        "scope": None,
        "status": "",
        "method": "whoop workout inside the Hevy session window, duration-matched to the block",
        "tolerance": tolerance,
        "candidates_considered": 0,
    }
    if not block or block <= 0:
        out["status"] = "no_block_duration"
        return out
    start, end = parse_iso_utc(session_start), parse_iso_utc(session_end)
    if not start or not end:
        out["status"] = "no_session_window"
        out["reason"] = "the Hevy workout record carried no usable start/end time"
        return out
    if not whoop_workouts:
        out["status"] = "no_whoop_workouts"
        return out

    siblings = [s for s in (_num(x) or 0.0 for x in (sibling_block_seconds or [])) if s > 0]
    lo = start.timestamp() - HR_WINDOW_SLACK_SEC
    hi = end.timestamp() + HR_WINDOW_SLACK_SEC
    matches: list[dict[str, Any]] = []
    sibling_collisions = 0
    for w in whoop_workouts:
        hr = _num(w.get("average_heart_rate"))
        ws, we = parse_iso_utc(w.get("start_time")), parse_iso_utc(w.get("end_time"))
        if not ws or not we:
            continue
        out["candidates_considered"] += 1
        if hr is None or hr <= 0:
            continue
        if ws.timestamp() < lo or we.timestamp() > hi:
            continue
        dur = we.timestamp() - ws.timestamp()
        if dur <= 0 or abs(dur - block) > tolerance * block:
            continue
        if any(abs(dur - s) <= tolerance * s for s in siblings):
            sibling_collisions += 1
            continue
        matches.append(
            {
                "average_heart_rate": int(round(hr)),
                "workout_id": w.get("workout_id"),
                "sport_name": w.get("sport_name"),
                "whoop_seconds": int(round(dur)),
                "block_seconds": int(round(block)),
            }
        )
    if not matches:
        if sibling_collisions:
            out["status"] = "ambiguous_sibling_block"
            out["reason"] = (
                f"{sibling_collisions} Whoop workout(s) match this block's duration AND another cardio block "
                "in the same session; the watch cannot say which one it was"
            )
            return out
        out["status"] = "no_ride_scoped_match"
        out["reason"] = (
            "no Whoop workout inside the session window lasts within "
            f"{int(tolerance * 100)}% of this block; the session-scoped average is NOT substituted"
        )
        return out
    if len(matches) > 1:
        out["status"] = "ambiguous_match"
        out["reason"] = f"{len(matches)} Whoop workouts match this block's duration; choosing one would be a guess"
        out["matches"] = matches
        return out
    out.update(matches[0])
    out["scope"] = "ride"
    out["status"] = "ok"
    return out


# ── facts ─────────────────────────────────────────────────────────────────────────────


def cardio_facts(
    template_id: str | None,
    cardio_index: dict[str, list[dict[str, Any]]] | None,
    whoop_index: dict[str, list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Facts a renderer may quote for one cardio movement. `{"sessions_count": 0}` if none.

    `cardio_index` is `exercise_history.load_history_indexes()`'s second return: template_id
    -> sessions, most-recent first, each `{date, name, note, duration_sec, distance_m,
    session_start, session_end}`.

    The returned `series` is chronological and carries ONLY rides with a single parseable
    level and a real distance — the rest are counted by name in `excluded` so a thin
    series is legible as which rides were dropped and why, never as a short history.
    """
    sessions = list((cardio_index or {}).get(template_id or "") or [])
    if not template_id or not sessions:
        return {"sessions_count": 0, "modality": "cardio", "series": [], "excluded": {}, "calibration": []}

    excluded: dict[str, int] = {}
    series: list[dict[str, Any]] = []
    calibration: list[dict[str, Any]] = []
    for s in sessions:
        note = s.get("note") or ""
        lvl = structured_level(note)
        spd = speed_mph(s.get("distance_m"), s.get("duration_sec"))
        anchors = _calibration_anchors(note)
        if anchors:
            calibration.append({"date": s.get("date"), "anchors": anchors, "raw": note})
        if lvl["status"] != "ok":
            excluded[lvl["status"]] = excluded.get(lvl["status"], 0) + 1
            continue
        if spd is None:
            excluded["no_distance"] = excluded.get("no_distance", 0) + 1
            continue
        hr = join_whoop_hr(
            s.get("session_start"),
            s.get("session_end"),
            s.get("duration_sec"),
            (whoop_index or {}).get(str(s.get("date") or "")) or [],
            sibling_block_seconds=s.get("sibling_block_seconds"),
        )
        series.append(
            {
                "date": s.get("date"),
                "level": lvl["level"],
                "speed_mph": spd,
                "duration_sec": _num(s.get("duration_sec")),
                "distance_m": _num(s.get("distance_m")),
                "average_heart_rate": hr["average_heart_rate"],
                "hr_status": hr["status"],
            }
        )
    series.sort(key=lambda r: str(r["date"]))

    last = sessions[0]
    last_level = structured_level(last.get("note") or "")
    last_hr = join_whoop_hr(
        last.get("session_start"),
        last.get("session_end"),
        last.get("duration_sec"),
        (whoop_index or {}).get(str(last.get("date") or "")) or [],
        sibling_block_seconds=last.get("sibling_block_seconds"),
    )
    return {
        "sessions_count": len(sessions),
        "modality": "cardio",
        "template_id": template_id,
        "name": last.get("name"),
        "last_date": last.get("date"),
        "last_duration_sec": _num(last.get("duration_sec")),
        "last_distance_m": _num(last.get("distance_m")),
        "last_speed_mph": speed_mph(last.get("distance_m"), last.get("duration_sec")),
        "last_level": last_level["level"],
        "last_level_status": last_level["status"],
        "last_note": (last.get("note") or "").strip(),
        "last_hr": last_hr,
        "series": series,
        "excluded": excluded,
        "calibration": calibration,
        "version": CARDIO_PROGRESSION_VERSION,
    }


def _calibration_anchors(note: str) -> list[dict[str, Any]]:
    """`training_notes.calibration_anchors` when importable, [] when it is not.

    #3817's deterministic detector — no LLM in the path. Wrapped because a cardio cue
    must still render if the extractor module cannot be imported: box 1 of this issue is
    that a level decision never depends on the extractor layer.
    """
    try:
        from training.training_notes import calibration_anchors
    except Exception:  # pragma: no cover - exercised by the import-failure test
        return []
    try:
        return list(calibration_anchors(note or ""))
    except Exception:  # pragma: no cover
        return []


# ── the rule ──────────────────────────────────────────────────────────────────────────


def level_verdict(series: list[dict[str, Any]] | None, level: int | None) -> dict[str, Any]:
    """Hold, raise, or say why neither can be claimed. Never asserts improvement.

    `claims_improvement` is the load-bearing key: it is True ONLY for a `raise` verdict,
    which needs `N_REQUIRED_AT_LEVEL` sessions at that level AND a between-block gain of
    at least one within-level SD of his own speed. Any surface rendering a progress claim
    must read that flag rather than inspecting `delta_mph` itself.
    """
    out: dict[str, Any] = {
        "level": level,
        "verdict": "insufficient_n",
        "claims_improvement": False,
        "n_at_level": 0,
        "n_required": N_REQUIRED_AT_LEVEL,
        "block_k": BLOCK_K,
        "effect_in_sd": EFFECT_IN_SD,
        "within_level_sd_mph": None,
        "effect_mph": None,
        "recent_mean_mph": None,
        "prior_mean_mph": None,
        "delta_mph": None,
        "hr_arm": {"status": "not_evaluated", "n_with_ride_scoped_hr": 0},
        "basis": "",
    }
    at = [r for r in (series or []) if r.get("level") == level and r.get("speed_mph") is not None]
    at.sort(key=lambda r: str(r["date"]))
    out["n_at_level"] = len(at)

    hr_n = sum(1 for r in at if r.get("average_heart_rate"))
    out["hr_arm"] = {
        "status": "ok" if hr_n >= N_REQUIRED_AT_LEVEL else "insufficient_hr_n",
        "n_with_ride_scoped_hr": hr_n,
        "n_required": N_REQUIRED_AT_LEVEL,
        "note": (
            "HR-at-level is not yet decidable, so this verdict rests on speed alone — which "
            "confounds fitness with effort. A Hevy cardio block carries no timestamps, so HR "
            "joins only when a Whoop workout matches the block's duration inside the session."
            if hr_n < N_REQUIRED_AT_LEVEL
            else "HR-at-level available for every session in the comparison."
        ),
    }

    if level is None:
        out["verdict"] = "no_level"
        out["basis"] = "the last ride's note carried no single parseable level, so there is no level to hold or raise"
        return out
    if len(at) < 2:
        out["basis"] = f"n={len(at)} at level {level}: no within-level variance estimate yet, so no effect size can be honest"
        return out

    speeds = [float(r["speed_mph"]) for r in at]
    sd = round(statistics.stdev(speeds), 2)
    out["within_level_sd_mph"] = sd
    out["effect_mph"] = round(sd * EFFECT_IN_SD, 2)
    if len(at) < N_REQUIRED_AT_LEVEL:
        out["basis"] = (
            f"n={len(at)} at level {level}, need {N_REQUIRED_AT_LEVEL} "
            f"(two blocks of {BLOCK_K}); his own within-level spread is {sd} mph"
        )
        return out

    recent = speeds[-BLOCK_K:]
    prior = speeds[:-BLOCK_K]
    r_mean, p_mean = round(statistics.fmean(recent), 2), round(statistics.fmean(prior), 2)
    delta = round(r_mean - p_mean, 2)
    out["recent_mean_mph"], out["prior_mean_mph"], out["delta_mph"] = r_mean, p_mean, delta
    if delta >= out["effect_mph"]:
        out["verdict"] = "raise"
        out["claims_improvement"] = True
        out["basis"] = (
            f"last {BLOCK_K} at level {level} averaged {r_mean} mph vs {p_mean} mph before "
            f"(+{delta}), clearing his own {sd} mph within-level spread"
        )
    else:
        out["verdict"] = "hold"
        out["basis"] = (
            f"last {BLOCK_K} at level {level} averaged {r_mean} mph vs {p_mean} mph before "
            f"({delta:+}), inside his own {sd} mph within-level spread"
        )
    return out


# ── the cue ───────────────────────────────────────────────────────────────────────────

_NOTE_QUOTE_MAX = 120
CUE_MAX_CHARS = 260


def render_cardio_cue(facts: dict[str, Any], verdict: dict[str, Any] | None = None) -> str:
    """One-line factual cue for a cardio block. '' when there is no usable history.

    Positive control (acceptance box 1): the live 2026-09-07 cycling record —
    `notes="Level 9 - 5.6 miles"`, `duration_sec=1800`, `distance_m=9012` — renders

        Last: level 9, 5.60 mi in 30:00 (11.2 mph) ["Level 9 - 5.6 miles"]

    where `render_history_cue` returns ''.

    A `hold`/`raise` verdict is appended WITH its basis. An `insufficient_n` verdict
    appends nothing: at low n the cue states the baseline and suggests nothing.
    """
    if not facts or facts.get("sessions_count", 0) == 0:
        return ""
    dur = _fmt_duration(facts.get("last_duration_sec"))
    if not dur:
        return ""
    dist_m = _num(facts.get("last_distance_m"))
    spd = facts.get("last_speed_mph")
    # A duration alone is not a baseline. The live proof is the `Stretching` block, which
    # is duration-bearing on exactly the same wire as a ride and would otherwise render
    # "Last: 15:00 - 19 Sep" onto every routine: true, useless, and indistinguishable at a
    # glance from a cue that carries something. A cue needs a level, a distance, or the
    # athlete's own words.
    if facts.get("last_level") is None and not (dist_m and dist_m > 0) and not (facts.get("last_note") or "").strip():
        return ""

    head = "Last: "
    if facts.get("last_level") is not None:
        head += f"level {facts['last_level']}, "
    if dist_m and dist_m > 0:
        head += f"{dist_m / METERS_PER_MILE:.2f} mi in {dur}"
        if spd:
            head += f" ({spd:.1f} mph)"
    else:
        head += dur
    when = _short_date(str(facts.get("last_date") or ""))
    if when:
        head += f" — {when}"

    parts = [head]
    note = (facts.get("last_note") or "").strip()
    if note:
        quoted = note if len(note) <= _NOTE_QUOTE_MAX else note[: _NOTE_QUOTE_MAX - 1].rstrip() + "…"
        parts.append(f'["{quoted}"]')

    cal = facts.get("calibration") or []
    if cal:
        a = cal[0]
        anchor = (a.get("anchors") or [{}])[0]
        low, high = anchor.get("level_low"), anchor.get("level_high")
        span = f"L{low}" if low == high else f"L{low}-{high}"
        cal_when = _short_date(str(a.get("date") or ""))
        parts.append(f"· his calibration: {span} is {anchor.get('verdict')}" + (f" ({cal_when})" if cal_when else ""))

    if verdict and verdict.get("verdict") in ("hold", "raise"):
        parts.append(f"· {verdict['verdict']} level {verdict.get('level')}: {verdict.get('basis')}")

    cue = " ".join(p for p in parts if p)
    if len(cue) > CUE_MAX_CHARS:
        # Trim the trailing clauses, never the measured head — the facts outrank the prose.
        cue = ""
        for p in parts:
            candidate = f"{cue} {p}".strip() if cue else p
            if len(candidate) > CUE_MAX_CHARS:
                break
            cue = candidate
    return cue


def cardio_cue(
    template_id: str | None,
    cardio_index: dict[str, list[dict[str, Any]]] | None,
    whoop_index: dict[str, list[dict[str, Any]]] | None = None,
) -> str:
    """facts -> verdict -> cue, in one call. The routine generator's entry point."""
    facts = cardio_facts(template_id, cardio_index, whoop_index)
    if facts.get("sessions_count", 0) == 0:
        return ""
    verdict = level_verdict(facts.get("series"), facts.get("last_level"))
    return render_cardio_cue(facts, verdict)


def _today() -> date:  # pragma: no cover - trivial seam kept for symmetry with exercise_history
    from common.pacific_time import pacific_today

    return parse_day_key(pacific_today())  # #3609: the platform's one day-key parser, never a hand-rolled fromisoformat
