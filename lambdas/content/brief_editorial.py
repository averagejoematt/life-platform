"""brief_editorial.py — what the Morning Brief may claim about a day it has not fully seen (#6163).

Four render-time rules, each a label or a collapse — nothing here computes, stores or changes a
number any other consumer reads:

  1. NOT ARRIVED vs NOT LOGGED. MacroFactor reaches the platform by a manual export
     (`source_registry` "Manual CSV export via Dropbox poller, ~24h behind by design"). A data day
     with no food row is "not logged" only when an export has ARRIVED after that day ended and
     still lacks it. Otherwise the export has not arrived: say so, with the date of the last one,
     and ask nothing of him.
  2. PROVISIONAL GRADE. A day grade computed without that day's food log is labelled provisional,
     naming what is missing. The grade itself (score, letter, colour, the stored row, the subject
     line) is untouched.
  3. THE MORNING OF EACH READINESS FIGURE. The READINESS SIGNAL's recovery/strain/RHR row reads the
     data day's Whoop row — the morning BEFORE the one the brief is read on. It is labelled with
     that morning, and with whether this morning's recovery had been scored when the brief was built.
  4. UNCHANGED SINCE. A guidance item or protocol bullet identical to the previous brief's collapses
     into one "unchanged since <date>" line. The previous brief is what the platform already stored
     for the day before (`computed_insights.guidance_given`; the protocol block is a pure function of
     that day's stored `character_sheet` row) — read by `emails.brief_editorial_inputs`, no new store.

Inputs arrive as `data["brief_editorial"]` (set by `html_builder.build_html` from its `editorial`
argument). Absent inputs -> every function returns the pre-#6163 output, byte for byte.

Pure module: no AWS, no clock, no I/O.
"""

from __future__ import annotations

from common.digest_utils import safe_float
from common.pacific_time import day_in_words, shift_day_key

from content.brief_format import esc

_NOTE_STYLE = "color:#94a3b8;font-size:11px;margin:6px 0 0;"
NOT_LOGGED_HTML = '<p style="color:#64748b;font-size:12px;margin:0;">No nutrition data logged yesterday.</p>'


def _editorial(data) -> dict:
    return (data or {}).get("brief_editorial") or {}


def _has_intake(data) -> bool:
    return safe_float((data or {}).get("macrofactor") or {}, "total_calories_kcal") is not None


def nutrition_arrival(data) -> str | None:
    """'arrived' (an export landed after the data day ended), 'not_arrived', or None (unknown).

    `editorial["nutrition"]` = {"last_arrival_day": PT day the newest export landed,
    "last_intake_day": newest day carrying intake} — the source's own freshness, read from its
    newest DATE# rows the way `get_freshness_status` reads it."""
    nut = _editorial(data).get("nutrition") or {}
    arrival = nut.get("last_arrival_day")
    day = (data or {}).get("date")
    if not arrival or not day:
        return None
    return "arrived" if arrival > day else "not_arrived"


def nutrition_absent_html(data) -> str:
    """The NUTRITION REPORT line for a day with no food row. 'Not logged' only when an export has
    arrived since the day ended; before that, the export has not arrived and nothing is asked."""
    if nutrition_arrival(data) != "not_arrived":
        return NOT_LOGGED_HTML
    nut = _editorial(data)["nutrition"]
    last = "the last export arrived " + day_in_words(nut["last_arrival_day"])
    if nut.get("last_intake_day") == nut["last_arrival_day"]:
        last += " and runs through that day"
    elif nut.get("last_intake_day"):
        last += " and runs through " + day_in_words(nut["last_intake_day"])
    return (
        '<p style="color:#64748b;font-size:12px;margin:0;">MacroFactor export not arrived for '
        + day_in_words(data["date"])
        + " — "
        + last
        + ". The food log reaches the platform by manual export, so this is not a missed log.</p>"
    )


def grade_provisional_html(data, day_grade_score) -> str:
    """A 'PROVISIONAL' line under the DAY GRADE when the grade was computed without the day's food log."""
    if day_grade_score is None or _has_intake(data) or not (data or {}).get("date"):
        return ""
    why = "food log not arrived" if nutrition_arrival(data) == "not_arrived" else "no food log"
    return (
        '<p style="color:#f59e0b;font-size:10px;margin:4px 0 0;font-weight:700;">PROVISIONAL</p>'
        '<p style="color:#94a3b8;font-size:10px;margin:0;">' + esc(why + " for " + day_in_words(data["date"], weekday=False)) + "</p>"
    )


def readiness_morning_html(data) -> str:
    """Names the morning the READINESS SIGNAL's figures describe (the data day's Whoop row), and
    labels it as an earlier morning than the one the brief is read on."""
    data = data or {}
    day = data.get("date")
    whoop = data.get("whoop") or {}
    if not day or not any(safe_float(whoop, k) for k in ("recovery_score", "strain", "resting_heart_rate")):
        return ""
    today = shift_day_key(day, 1)
    today_rec = safe_float(data.get("whoop_today") or {}, "recovery_score")
    if today_rec is None:
        tail = "this morning's recovery (" + day_in_words(today) + ") was not scored when this brief was built."
    else:
        tail = "this morning's recovery (" + day_in_words(today) + ") is " + str(round(today_rec)) + "%."
    return '<p style="' + _NOTE_STYLE + '">From the morning of ' + day_in_words(day) + " — an earlier morning; " + tail + "</p>"


def _norm(text) -> str:
    return " ".join(str(text or "").split())


def _since(data) -> str:
    """The previous brief was sent on the morning of the current data day."""
    return day_in_words((data or {}).get("date") or "")


def _unchanged_line(n, noun, data) -> str:
    return str(n) + " " + noun + ("" if n == 1 else "s") + " unchanged since the " + _since(data) + " brief."


def collapse_guidance(tldr_guidance, data):
    """TODAY'S GUIDANCE with every item identical to one of the previous brief's collapsed into one
    trailing "unchanged since" line. Returns a NEW dict (the caller's is untouched); unchanged when
    the previous brief's guidance was not read."""
    prev = _editorial(data).get("previous_guidance")
    items = (tldr_guidance or {}).get("guidance") or []
    if not prev or not items:
        return tldr_guidance
    seen = {_norm(p) for p in prev}
    fresh = [g for g in items if _norm(g) not in seen]
    if len(fresh) == len(items):
        return tldr_guidance
    return {**tldr_guidance, "guidance": fresh + [_unchanged_line(len(items) - len(fresh), "guidance item", data)]}


def _proto_name(proto) -> str:
    return str(proto.get("name", proto)) if isinstance(proto, dict) else str(proto)


def _proto_keys(recs) -> set:
    return {((r.get("pillar") or ""), _norm(_proto_name(p))) for r in recs or [] for p in r.get("protocols", [])}


def protocols_html(protocol_recs, data) -> str:
    """The PROTOCOLS TO TRY block (moved from `html_builder._brief_character`, #6163). A bullet whose
    pillar + text was also in the previous brief's block is folded into one "unchanged since" line."""
    if not protocol_recs:
        return ""
    prev = _editorial(data).get("previous_protocol_recs")
    seen = _proto_keys(prev) if prev else set()
    out = '<div style="padding:8px 24px 12px;background:rgba(0,0,0,0.15);border-top:1px solid #2d2d5e;">'
    out += (
        '<p style="color:#94a3b8;font-size:10px;margin:0 0 4px;font-weight:700;">PROTOCOLS TO TRY</p>'
        '<p style="color:#64748b;font-size:10px;margin:0 0 4px;">A protocol is a rule followed on purpose, to see if a number moves.</p>'
    )
    unchanged = 0
    for rec in protocol_recs:
        pillar = rec.get("pillar") or ""
        protos = [p for p in rec.get("protocols", []) if (pillar, _norm(_proto_name(p))) not in seen]
        unchanged += len(rec.get("protocols", [])) - len(protos)
        if not protos and rec.get("protocols"):
            continue
        arrow = "↓" if rec.get("dropped", False) else "⚠"
        out += '<p style="color:#f87171;font-size:11px;margin:2px 0;">' + arrow + " " + pillar.capitalize() + ":</p>"
        for proto in protos:
            out += '<p style="color:#9ca3af;font-size:10px;margin:0 0 2px 12px;">• ' + _proto_name(proto) + "</p>"
    if unchanged:
        out += '<p style="color:#9ca3af;font-size:10px;margin:2px 0 0;">' + esc(_unchanged_line(unchanged, "protocol", data)) + "</p>"
    return out + "</div>"
