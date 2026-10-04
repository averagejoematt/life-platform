"""site_api_edition.py — GET /api/edition: the front page's ONE document (#4582, epic #4580).

THE DEFECT
----------
The front page's blocks (the week's chapter and podcast, today's weight, the coach lines,
his own words, the coaches' record) were each fetched from a separate route, and every
route carries its own idea of "today". On 2026-10-03 one coach cited an eleven-day journal
silence where the site said 24. A page assembled from a dozen as-of dates can disagree
with itself, and a cold reader has no way to tell which line is current.

THE RULE
--------
One request, one top-level ``as_of`` (the Pacific date, the site's PT-today rule) and one
``day_n``. Every block is an object with the same five keys::

    {"state": "ok" | "absent" | "stale" | "unavailable",
     "as_of": "YYYY-MM-DD" | None,      # the day the block's data is ABOUT
     "source": "/api/..." | [...],      # the route (or public file) it was read from
     "absent_text": "<sentence>",       # what a page prints when state != "ok"
     "data": {...} | None}

  * ``unavailable`` — the upstream read failed (non-200, a ``_meta.degraded`` fallback, an
    exception). The block carries NO data and an "... is not served right now." sentence:
    never a blank, a zero, or a stale figure passed off as current.
  * ``absent`` — the upstream answered and there is nothing (no chapter yet, no note).
  * ``stale`` — the data is served, but it is older than the block's freshness bound; its
    own ``as_of`` says how old, and ``absent_text`` names the day.
  * ``absent_text`` is ALWAYS a sentence (first-person-free) — present in every state so
    the block contract never depends on the state.

COMPOSITION, NOT A SECOND IMPLEMENTATION
-----------------------------------------
``compose()`` is pure: it takes the upstream BODIES (exactly as the existing routes serve
them — ``None`` for a failed read), the Pacific date and the clock, and returns the
document. ``handle_edition()`` is the shell: it reads each upstream through the SAME
in-process dispatcher the routes use (``site_api_lambda._dispatch_route`` is handed in as
``read_route`` — never an HTTP call to itself) plus the two public manifests the chronicle
and the panelcast publish (``generated/journal/posts.json``, ``generated/panelcast/
episodes.json`` — the files ``/journal/posts.json`` and ``/panelcast/episodes.json``
serve). No new Lambda, no schedule, no DynamoDB write, no new IAM: the site-api role
already reads ``generated/*``.

Honest-number rules (ADR-104/105) bind every block: no cycle/reset/attempt counts, no
calorie-deficit figure, nothing spanning earlier starts (``/api/predictions``' ``overall``
and ``/api/calibration``'s ``platform`` are this experiment's; their ``lifetime`` siblings
are never read), and coach names carry no "Dr." honorific.
"""

from __future__ import annotations

import json
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from coach.persona_registry import plain_name as _registry_plain_name
from common import subscriber_cadence as sc
from common.pacific_time import day_in_words, pacific_date_of, pacific_day_n, parse_day_key, parse_iso_utc

#: The page order. The front page renders blocks in exactly this sequence.
ORDER = ("premise", "chapter", "next", "today", "week", "life", "coach_lines", "scorecard", "record", "his_words", "catch_up", "follow")

#: Upstream key -> the route (or public file) it is read from. The key is the ``bodies``
#: key ``compose()`` reads; the value is what every block's ``source`` names.
SOURCES = {
    "journal": "/journal/posts.json",
    "panelcast": "/panelcast/episodes.json",
    "cadence": "/api/content_cadence",
    "docket": "/api/coach_docket",
    "journey": "/api/journey",
    "dashboard": "/api/coaching-dashboard",
    "predictions": "/api/predictions",
    "calibration": "/api/calibration",
    "decisions": "/api/decisions",
    # #4584: his own words from his Claude chat or his email replies, verbatim — read before the decisions note.
    "owner_words": "/api/owner_words",
    # The whole-life rows (#4586): one served fact per area of his life, each a door.
    "sleep": "/api/sleep_detail",
    "session": "/api/session",
    "nutrition": "/api/nutrition_overview",
    "habits": "/api/habit_streaks",
    "supplements": "/api/supplements",
    "experiments": "/api/experiments",
    # The last seven days (#4586): one value per day per measure.
    "pulse": "/api/pulse_history",
    "training": "/api/training_overview",
}

#: The two public manifests are S3 objects under generated/ (CloudFront strips the prefix).
_S3_KEYS = {"journal": "generated/journal/posts.json", "panelcast": "generated/panelcast/episodes.json"}

#: Query strings for the routes that take one (the record needs ``overall`` only).
_ROUTE_QS = {"predictions": {"limit": "1"}}

# Freshness bounds, in days. Past the bound a block is ``stale`` — served, but dated.
CHAPTER_STALE_DAYS = 8  # a weekly installment; past 8 days it is not "this week's"
WEIGHIN_STALE_DAYS = 1  # today's or yesterday's weigh-in; older is not "this morning"
COACH_STALE_DAYS = 1  # the coach text is written daily before the 17:00 UTC brief
HIS_WORDS_STALE_DAYS = 7

MAX_COACH_LINES = 3
CACHE_SECONDS = 300  # the neighbours' cache (/api/coach_docket, /api/decisions, /api/calibration)

# The older coach text restates the day's numbers; a block built from it says so with
# ``voice: "restated"``. It stands in only when no current day of moves (#4583) is served.
COACH_VOICE = "restated"
COACH_VOICE_MOVE = "move"  # #4583: each line is a move a coach made today, checked in code against one fact sheet

# TODO(scorecard follow-up under epic #4580): the "More than weight" rows (body, training,
# sleep, food, mind, the AI) need rules no route serves today. The block ships ``absent``
# rather than inventing rules; the follow-up story owns them.
SCORECARD_TODO = "epic #4580 — the scorecard rows have no served rules yet"

#: Reader words for a coach's domain, keyed by the persona registry's ``domain`` field.
#: GAP (named in the PR): config/personas.json carries no reader-facing domain word, and the
#: v7 pages hold two JS copies (v7_home.js COACH_WORDS, v7_coaches.js ROLE_WORDS). The words
#: here follow the owner-approved prototype ("food", not "nutrition"). Unknown domains print
#: their own words with the underscores opened — never hidden.
_DOMAIN_WORDS = {
    "sleep_science": "sleep",
    "nutrition_science": "food",
    "behavioral_psychology": "mind",
    "performance_science": "training",
    "exercise_physiology": "training",
    "metabolic_health": "blood sugar",
    "clinical_pathology": "blood tests",
    "biostatistics_n1_research": "statistics",
    "orchestration": "the whole plan",
    "longitudinal_patterns": "patterns",
}

_QUESTION_COND = {"gte": "or higher", "ge": "or higher", "lte": "or lower", "le": "or lower", "eq": "exactly"}

# Honest-number screens for served coach prose (ADR-104; the cycle-count ruling of
# 2026-09-26; no calorie-deficit figure on a reader surface).
_DEFICIT_FIGURE = re.compile(
    r"\d[\d,.]*\s*(?:kcal|calories?|cal)?\s*(?:a\s+day\s+|daily\s+)?deficit|deficit\s+(?:of\s+)?(?:about\s+|roughly\s+|~)?\d", re.I
)
_CYCLE_COUNT = re.compile(
    r"\b(?:cycle|attempt|reset|restart)s?\s*#?\d+|\b\d+(?:st|nd|rd|th)\s+(?:cycle|attempt|reset|restart|start)\b"
    r"|\b(?:earlier|previous|prior)\s+(?:starts|attempts|cycles|resets)\b",
    re.I,
)
_HONORIFIC = re.compile(r"\bDr\.?\s+(?=[A-Z])")
_UNDERSCORE_EMPHASIS = re.compile(r"(?<!\w)_([^_\n]+)_(?!\w)")
_SENTENCE_END = re.compile(r"[.!?][\"”’)]?(?=\s|$)")


# ── small pure helpers ──────────────────────────────────────────────────────────


def plain_name(name: Any) -> str:
    """A persona's name with no honorific — the registry's one spelling of the rule (#4578)."""
    return _registry_plain_name(name)


def _days_between(earlier: str | None, later: str) -> int | None:
    a, b = parse_day_key(earlier or ""), parse_day_key(later)
    return (b - a).days if a and b else None


def _block(state: str, as_of: str | None, source: Any, absent_text: str, data: Any = None, **extra) -> dict:
    """The one block shape. ``data`` is None unless the state carries served data."""
    return {"state": state, "as_of": as_of, "source": source, "absent_text": absent_text, "data": data, **extra}


def _unavailable(source: Any, what: str) -> dict:
    return _block("unavailable", None, source, f"{what} is not served right now.")


def _trim_to_sentence(text: str) -> tuple[str, bool]:
    """Drop a served ellipsis cut: keep through the last full sentence. ``(text, truncated)``."""
    t = text.strip()
    if not t.endswith(("…", "...")):
        return t, False
    body = t[:-1].rstrip() if t.endswith("…") else t[:-3].rstrip()
    ends = list(_SENTENCE_END.finditer(body))
    if ends:
        return body[: ends[-1].end()].strip(), False
    return t, True  # no full sentence survives the cut: serve it as cut, and say so


def strip_emphasis(text: str) -> str:
    """Markdown emphasis off: ``**``/``*`` markers dropped, ``_word_`` unwrapped."""
    return _UNDERSCORE_EMPHASIS.sub(r"\1", text.replace("**", "").replace("*", ""))


def dek_of(excerpt: Any) -> str | None:
    """The chapter's opening line: the first paragraph that is not an editor's note,
    markdown emphasis stripped, the excerpt's ellipsis cut trimmed to a full sentence."""
    for para in re.split(r"\n\s*\n", str(excerpt or "")):
        plain = strip_emphasis(para).strip()
        if not plain or plain.lower().startswith("editor's note") or plain.lower().startswith("editor’s note"):
            continue
        text, _cut = _trim_to_sentence(plain)
        return text or None
    return None


def honest_text(text: str) -> bool:
    """False when served prose carries a figure the honest-number rules keep off the page."""
    return not (_DEFICIT_FIGURE.search(text) or _CYCLE_COUNT.search(text))


def domain_words(persona: dict | None) -> str | None:
    domain = str((persona or {}).get("domain") or "")
    if not domain:
        return None
    return _DOMAIN_WORDS.get(domain) or domain.replace("_", " ")


def _fmt_num(value: Any) -> str | None:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return str(int(f)) if f == int(f) else f"{f:.1f}".rstrip("0").rstrip(".")


def bet_question(criterion: dict, settle_date: str, metric_words: Callable[[Any], str | None]) -> str | None:
    """'Will the morning recovery score (7-day average) be 81.6 or higher on Monday, October 5?'

    Built from the docket's CRITERION (engine fields), never from the served topic prose —
    the same rule v7_coaches.js docketQuestion() follows, with the metric's reader words
    from ``web.prediction_reason.metric_words`` (the server-side registry). None when the
    metric has no reader words or no threshold: a question is never guessed."""
    words = metric_words((criterion or {}).get("metric"))
    thr = _fmt_num((criterion or {}).get("threshold"))
    if not words or thr is None:
        return None
    cond = str(criterion.get("condition") or "").lower()
    when = day_in_words(settle_date) if parse_day_key(settle_date or "") else ""
    on = f" on {when}" if when else ""
    if cond in ("gt", "lt"):
        return f"Will the {words} be {'over' if cond == 'gt' else 'under'} {thr}{on}?"
    if cond not in _QUESTION_COND:
        return None
    return f"Will the {words} be {thr} {_QUESTION_COND[cond]}{on}?"


def next_send_date(cron: str, now: datetime) -> str | None:
    """The Pacific date of a weekly sender's next fire at or after ``now`` (UTC-aware)."""
    weekday = sc.cron_weekday(cron)
    if weekday is None:
        return None
    now_utc = now.astimezone(timezone.utc)
    fire = now_utc.replace(hour=sc.cron_hour(cron), minute=sc.cron_minute(cron), second=0, microsecond=0)
    fire += timedelta(days=(weekday - now_utc.weekday()) % 7)
    if fire < now_utc:
        fire += timedelta(days=7)
    return pacific_date_of(fire.isoformat())


# ── the blocks ──────────────────────────────────────────────────────────────────


def _premise(today: str) -> dict:
    # Static: the words live in the page. The block carries only the copy key.
    return _block("ok", today, "static", "The introduction is not served right now.", {"copy_key": "premise"})


def _published_posts(journal: dict, today: str) -> list:
    posts = [p for p in (journal or {}).get("posts") or [] if isinstance(p, dict) and p.get("title") and p.get("url")]
    return [p for p in posts if parse_day_key(str(p.get("date") or "")) and str(p["date"]) <= today]


def _podcast_part(panelcast: dict | None, week: Any, persona_of: Callable[[str], dict | None]) -> dict:
    src = SOURCES["panelcast"]
    if panelcast is None:
        return _unavailable(src, "The podcast list")
    eps = [e for e in panelcast.get("episodes") or [] if isinstance(e, dict) and e.get("week") == week and e.get("url")]
    if not eps:
        return _block("absent", None, src, "No podcast episode for this chapter yet.")
    ep = max(eps, key=lambda e: str(e.get("date") or ""))
    secs = ep.get("duration_sec")
    data = {
        "title": ep.get("title"),
        "guest": plain_name(ep.get("guest_name")) or None,
        "guest_domain": domain_words(persona_of(str(ep.get("guest_id") or ""))),
        "duration_sec": secs,
        "duration_minutes": max(1, round(secs / 60)) if isinstance(secs, (int, float)) and secs > 0 else None,
        "mp3_url": ep.get("url"),
        "date": ep.get("date"),
    }
    return _block("ok", ep.get("date"), src, "No podcast episode for this chapter yet.", data)


def _chapter(journal: dict | None, panelcast: dict | None, today: str, persona_of) -> dict:
    src = [SOURCES["journal"], SOURCES["panelcast"]]
    if journal is None:
        return _unavailable(src, "The latest chapter")
    posts = _published_posts(journal, today)
    if not posts:
        return _block("absent", None, src, "No chapter has been published yet.")
    post = max(posts, key=lambda p: (str(p["date"]), p.get("sequence") or 0))
    words = post.get("word_count")
    data = {
        "title": post["title"],
        "date": post["date"],
        "week_label": post.get("label"),
        "dek": dek_of(post.get("excerpt")),
        "url": post["url"],
        "word_count": words,
        "read_minutes": max(1, math.ceil(words / 230)) if isinstance(words, int) and words > 0 else None,
        "podcast": _podcast_part(panelcast, post.get("week"), persona_of),
    }
    age = _days_between(post["date"], today)
    if age is not None and age > CHAPTER_STALE_DAYS:
        return _block("stale", post["date"], src, f"No new chapter since {day_in_words(post['date'])}.", data)
    return _block("ok", post["date"], src, "No chapter has been published yet.", data)


def _next(cadence: dict | None, docket: dict | None, today: str, persona_of, metric_words) -> dict:
    if cadence is None:
        chapter = _unavailable(SOURCES["cadence"], "The chapter schedule")
    else:
        ch = cadence.get("chronicle") or {}
        if ch.get("paused") or not ch.get("next_date"):
            chapter = _block("absent", None, SOURCES["cadence"], "The next chapter is paused.")
        else:
            # Drafted that day; it publishes once he has read it (content_cadence's own caveat).
            chapter = _block(
                "ok",
                ch["next_date"],
                SOURCES["cadence"],
                "The next chapter is paused.",
                {"date": ch["next_date"], "drafted_not_promised": True},
            )
    if docket is None:
        bet = _unavailable(SOURCES["docket"], "The coaches' open bets")
    else:
        due = sorted(
            (d for d in docket.get("open") or [] if isinstance(d, dict) and str(d.get("resolution_date") or "") >= today),
            key=lambda d: str(d["resolution_date"]),
        )
        if not due:
            bet = _block("absent", None, SOURCES["docket"], "No coach bet is waiting to settle.")
        else:
            d = due[0]
            sides = d.get("sides") or {}
            data = {
                "question": bet_question(d.get("criterion") or {}, d["resolution_date"], metric_words),
                "topic": d.get("topic"),
                "settle_date": d["resolution_date"],
                "sides": [
                    {"coach": plain_name((persona_of(pid) or {}).get("name") or pid), "says": "yes" if sides.get(pid) else "no"}
                    for pid in (d.get("coach_a"), d.get("coach_b"))
                    if pid in sides
                ],
            }
            bet = _block("ok", d["resolution_date"], SOURCES["docket"], "No coach bet is waiting to settle.", data)
    parts = {"chapter": chapter, "bet": bet}
    states = {p["state"] for p in parts.values()}
    state = "ok" if "ok" in states else ("unavailable" if "unavailable" in states else "absent")
    src = [SOURCES["cadence"], SOURCES["docket"]]
    if state == "unavailable":
        return _unavailable(src, "What comes next")
    return _block(state, today, src, "Nothing is scheduled yet.", parts)


def _today(journey_body: dict | None, today: str) -> dict:
    src = SOURCES["journey"]
    if journey_body is None:
        return _unavailable(src, "Today's weight")
    j = journey_body.get("journey") or {}
    current, start, last = j.get("current_weight_lbs"), j.get("start_weight_lbs"), j.get("last_weighin_date")
    if j.get("pre_start") or not isinstance(current, (int, float)) or not parse_day_key(str(last or "")):
        return _block("absent", None, src, "No weigh-in yet.")
    data = {
        "weight_lbs": current,
        "date": last,
        "start_weight_lbs": start,
        "start_date": j.get("started_date"),
        "goal_weight_lbs": j.get("goal_weight_lbs"),
        "change_lbs": round(current - start, 1) if isinstance(start, (int, float)) else None,
    }
    age = _days_between(last, today)
    if age is not None and age > WEIGHIN_STALE_DAYS:
        return _block("stale", last, src, f"No weigh-in since {day_in_words(last)}.", data)
    return _block("ok", last, src, "No weigh-in yet.", data)


# ── the last seven days (#4586) ─────────────────────────────────────────────────
# Seven Pacific days ending today, one value per day per measure, plus one plain sentence
# per measure. A day with no reading is None — never a zero, never carried forward. `met`
# marks a day against a stated bar (trained at all; 7 hours; the plan's protein floor): a
# fact about that day, not a verdict on the week.
WEEK_DAYS = 7
SLEEP_BAR_HOURS = 7.0


def _week_days(today: str) -> list:
    end = parse_day_key(today)
    return [(end - timedelta(days=i)).isoformat() for i in range(WEEK_DAYS - 1, -1, -1)] if end else []


def _by_date(rows: Any, field: str) -> dict:
    return {str(r.get("date")): _num(r.get(field)) for r in rows or [] if isinstance(r, dict) and r.get("date")}


def _training_minutes(rows: Any, today: str) -> dict:
    """Training minutes by day. Today's zero is NOT a reading: the day is not over, so a
    session not yet logged must not count as a day without training."""
    minutes = _by_date(rows, "total_min")
    if not minutes.get(today):
        minutes.pop(today, None)
    return minutes


def _measure(
    src: Any, what: str, body: dict | None, days: list, values: dict | None, sentence: Callable[[list], str | None], bar=None
) -> dict:
    if body is None:
        return _unavailable(src, what)
    series = [values.get(d) if values else None for d in days]
    seen = [d for d, v in zip(days, series) if v is not None]
    if not seen:
        return _block("absent", None, src, f"{what} has no reading in these seven days.")
    data = {"values": series, "text": sentence(series)}
    if bar is not None:
        data["met"] = [None if v is None else bool(bar(v)) for v in series]
    return _block("ok", seen[-1], src, f"{what} has no reading in these seven days.", data)


_MODALITY_WORDS = (
    ("strength_min", "strength"),
    ("walking_min", "walking"),
    ("cycling_min", "cycling"),
    ("hiking_min", "hiking"),
    ("soccer_min", "soccer"),
    ("stretching_min", "stretching"),
    ("breathwork_min", "breathwork"),
    ("other_min", "other training"),
)


def _rows_by_date(rows: Any) -> dict:
    return {str(r.get("date")): r for r in rows or [] if isinstance(r, dict) and r.get("date")}


def _day_detail(day: str, pulse_row: dict | None, training_row: dict | None, food_row: dict | None, is_today: bool = False) -> dict:
    """One day, opened: every fact a route served for that day, in plain words. A measure
    with no reading that day is left out — the day says what was recorded, nothing else."""
    facts, summary = [], []
    p, t, f = pulse_row or {}, training_row or {}, food_row or {}
    weight, hours, recovery, steps = (
        _num(p.get("weight_lbs")),
        _num(p.get("sleep_hours")),
        _num(p.get("recovery_pct")),
        _num(p.get("steps")),
    )
    if weight is not None:
        facts.append({"label": "Weight", "text": f"{weight:.1f} lb"})
        summary.append(f"{weight:.1f} lb")
    total = _num(t.get("total_min"))
    if total:
        kinds = [f"{_fmt_num(t[k])} minutes of {word}" for k, word in _MODALITY_WORDS if _num(t.get(k))]
        facts.append({"label": "Training", "text": "; ".join(kinds) or f"{_fmt_num(total)} minutes"})
        summary.append("trained")
    elif training_row is not None and not is_today:
        facts.append({"label": "Training", "text": "No training recorded."})
        summary.append("no training recorded")
    if hours is not None:
        rec = f"; recovery {_fmt_num(recovery)} out of 100" if recovery is not None else ""
        facts.append({"label": "Sleep", "text": f"{_fmt_num(hours)} hours{rec}"})
        summary.append(f"slept {_fmt_num(hours)} h")
    protein, calories = _num(f.get("protein_g")), _num(f.get("calories"))
    if protein is not None:
        kcal = f", {int(calories):,} kcal" if calories is not None else ""
        facts.append({"label": "Food", "text": f"{_fmt_num(protein)} g protein{kcal}"})
    if steps is not None:
        facts.append({"label": "Steps", "text": f"{int(steps):,}"})
    return {"date": day, "summary": " · ".join(summary) or "Nothing recorded yet.", "facts": facts}


def _week(b: dict, today: str) -> dict:
    days = _week_days(today)
    pulse, training, nutrition = b["pulse"], b["training"], b["nutrition"]
    history = (pulse or {}).get("pulse_history")
    floor = _num(((nutrition or {}).get("nutrition") or {}).get("protein_floor_g"))

    def weight_text(v: list) -> str | None:
        seen = [x for x in v if x is not None]
        if len(seen) < 2:
            return f"{_fmt_num(seen[-1])} lb at the one weigh-in in these seven days."
        change = round(seen[-1] - seen[0], 1)
        way = "down" if change < 0 else "up" if change > 0 else "level"
        moved = f"{way} {_fmt_num(abs(change))}" if change else "level"
        return f"{_fmt_num(seen[-1])} lb, {moved} across {len(seen)} weigh-ins."

    def count_text(label: str, bar) -> Callable[[list], str | None]:
        def text(v: list) -> str | None:
            seen = [x for x in v if x is not None]
            return f"{label} on {sum(1 for x in seen if bar(x))} of {len(seen)} days recorded."

        return text

    def trained(x: float) -> bool:
        return x > 0

    def slept(x: float) -> bool:
        return x >= SLEEP_BAR_HOURS

    def fed(x: float) -> bool:
        return floor is not None and x >= floor

    parts = {
        "weight": _measure(SOURCES["pulse"], "The weight", pulse, days, _by_date(history, "weight_lbs"), weight_text),
        "training": _measure(
            SOURCES["training"],
            "Training",
            training,
            days,
            _training_minutes((training or {}).get("daily_modality_minutes_30d"), today),
            count_text("Trained", trained),
            trained,
        ),
        "sleep": _measure(
            SOURCES["pulse"],
            "Sleep",
            pulse,
            days,
            _by_date(history, "sleep_hours"),
            count_text(f"Slept {_fmt_num(SLEEP_BAR_HOURS)} hours or more", slept),
            slept,
        ),
        "food": _measure(
            SOURCES["nutrition"],
            "The food log",
            nutrition if floor is not None else None,
            days,
            _by_date((nutrition or {}).get("nutrition_trend"), "protein_g"),
            count_text(f"At or above {_fmt_num(floor)} g protein", fed),
            fed,
        ),
    }
    src = [SOURCES["pulse"], SOURCES["training"], SOURCES["nutrition"]]
    if all(p["state"] == "unavailable" for p in parts.values()):
        return _unavailable(src, "The last seven days")
    series = [
        {"date": str(r["date"]), "lbs": r["weight_lbs"]}
        for r in history or []
        if isinstance(r, dict) and r.get("date") and _num(r.get("weight_lbs")) is not None and str(r["date"]) <= today
    ]
    by_pulse, by_training = _rows_by_date(history), _rows_by_date((training or {}).get("daily_modality_minutes_30d"))
    by_food = _rows_by_date((nutrition or {}).get("nutrition_trend"))
    # Newest first: the day a returning reader came for is the first one they can open.
    detail = [_day_detail(d, by_pulse.get(d), by_training.get(d), by_food.get(d), d == today) for d in reversed(days)]
    data = {"days": days, "order": list(parts), "measures": parts, "detail": detail, "weight_series": series}
    return _block("ok", today, src, "Nothing is recorded in these seven days.", data)


# ── the whole-life rows (#4586) ─────────────────────────────────────────────────
# One served FACT per area, each a door to its own page. No verdict on any row: whether an
# area is "going well" is decided by written rules that are not built yet (the scorecard,
# #4595). A row whose source failed is `unavailable`; one with nothing to say is `absent`;
# one whose fact is older than LIFE_STALE_DAYS says which day it is from.
LIFE_ORDER = ("body", "training", "sleep", "food", "habits", "supplements", "experiments", "mind")
LIFE_STALE_DAYS = 2
_RUNNING = {"active", "running", "in_progress"}


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _row(src: Any, what: str, body: dict | None, build: Callable[[dict], tuple | None], nothing: str, today: str) -> dict:
    """One whole-life row. ``build(body)`` returns ``(text, as_of)`` or None for nothing to say."""
    if body is None:
        return _unavailable(src, what)
    made = build(body)
    if not made:
        return _block("absent", None, src, nothing)
    text, as_of = made
    age = _days_between(as_of, today) if as_of else None
    if age is not None and age > LIFE_STALE_DAYS:
        return _block("stale", as_of, src, f"Nothing newer than {day_in_words(as_of)}.", {"text": text})
    return _block("ok", as_of or today, src, nothing, {"text": text})


def _life_body(body: dict) -> tuple | None:
    j = body.get("journey") or {}
    lost, left, goal = _num(j.get("lost_lbs")), _num(j.get("remaining_lbs")), _num(j.get("goal_weight_lbs"))
    if j.get("pre_start") or lost is None or left is None or goal is None:
        return None
    way = "down" if lost >= 0 else "up"
    return f"{_fmt_num(abs(lost))} lb {way} so far; {_fmt_num(left)} lb to go to reach {_fmt_num(goal)}.", j.get("last_weighin_date")


def _life_training(today: str) -> Callable[[dict], tuple | None]:
    def build(body: dict) -> tuple | None:
        names = [str(e.get("name")) for e in body.get("exercises") or [] if isinstance(e, dict) and e.get("name")]
        if body.get("state") != "served" or str(body.get("date") or "") != today or not names:
            return None
        rest = len(names) - 2
        more = f" and {rest} more" if rest > 0 else ""
        return f"Planned for today: {', '.join(names[:2])}{more}.", today

    return build


def _life_sleep(body: dict) -> tuple | None:
    d = body.get("sleep_detail") or {}
    hours, recovery, night = _num(d.get("total_sleep_hours")), _num(d.get("recovery_score")), d.get("night_of")
    if hours is None or not parse_day_key(str(night or "")):
        return None
    rec = f"; recovery {_fmt_num(recovery)} out of 100" if recovery is not None else ""
    # The night of the 3rd is the sleep he woke from on the 4th: the row is about that morning.
    return f"Slept {_fmt_num(hours)} hours on the night of {day_in_words(night)}{rec}.", d.get("as_of_date") or night


def _life_food(body: dict) -> tuple | None:
    n = body.get("nutrition") or {}
    hit, logged, floor = _num(n.get("protein_floor_hit_days")), _num(n.get("days_logged")), _num(n.get("protein_floor_g"))
    if hit is None or not logged or floor is None:
        return None
    return f"At or above the {_fmt_num(floor)} g protein floor on {int(hit)} of {int(logged)} logged days.", n.get("latest_date")


def _life_habits(body: dict) -> tuple | None:
    h = body.get("habit_streaks") or {}
    done, total, day = _num(h.get("tier0_done")), _num(h.get("tier0_total")), h.get("as_of_date")
    if done is None or not total or not parse_day_key(str(day or "")):
        return None
    return f"{int(done)} of {int(total)} daily habits kept on {day_in_words(day)}.", day


def _life_supplements(body: dict) -> tuple | None:
    count = sum(len((g or {}).get("items") or []) for g in (body.get("groups") or {}).values() if isinstance(g, dict))
    if not count:
        return None
    return f"{count} in the daily stack.", body.get("as_of_date")


def _life_experiments(today: str) -> Callable[[dict], tuple | None]:
    def build(body: dict) -> tuple | None:
        rows = [e for e in body.get("experiments") or [] if isinstance(e, dict)]
        if not rows:
            return None
        running = [str(e.get("name")) for e in rows if e.get("status") in _RUNNING and e.get("name")]
        ready = sum(1 for e in rows if e.get("status") == "available")
        if running:
            more = f" and {len(running) - 1} more" if len(running) > 1 else ""
            return f"Running now: {running[0]}{more}.", today
        return f"None running right now; {ready} ready to start.", today

    return build


def _life_mind(his_words: dict) -> dict:
    src = his_words.get("source")
    if his_words.get("state") == "unavailable":
        return _unavailable(src, "His own words")
    day = his_words.get("as_of")
    if his_words.get("state") == "ok" and day:
        return _block("ok", day, src, "Nothing in his own words yet.", {"text": f"His latest words are from {day_in_words(day)}."})
    return _block(his_words.get("state") or "absent", day, src, his_words.get("absent_text") or "Nothing in his own words yet.")


def _life(b: dict, his_words: dict, today: str) -> dict:
    parts = {
        "body": _row(SOURCES["journey"], "The weight so far", b["journey"], _life_body, "No weigh-in yet.", today),
        "training": _row(
            SOURCES["session"], "Today's session", b["session"], _life_training(today), "No session is planned for today.", today
        ),
        "sleep": _row(SOURCES["sleep"], "Last night's sleep", b["sleep"], _life_sleep, "No sleep has been recorded yet.", today),
        "food": _row(SOURCES["nutrition"], "The food log", b["nutrition"], _life_food, "No food has been logged yet.", today),
        "habits": _row(SOURCES["habits"], "The daily habits", b["habits"], _life_habits, "No habits have been recorded yet.", today),
        "supplements": _row(
            SOURCES["supplements"], "The supplement stack", b["supplements"], _life_supplements, "No supplements are listed.", today
        ),
        "experiments": _row(
            SOURCES["experiments"], "The experiments", b["experiments"], _life_experiments(today), "No experiments are listed.", today
        ),
        "mind": _life_mind(his_words),
    }
    src = sorted({str(x) for p in parts.values() for x in (p["source"] if isinstance(p["source"], list) else [p["source"]]) if x})
    if all(p["state"] == "unavailable" for p in parts.values()):
        return _unavailable(src, "How the whole thing is going")
    return _block("ok", today, src, "Nothing is recorded yet.", {"order": list(LIFE_ORDER), "rows": parts})


def _coach_moves(moves: Any, today: str, persona_of) -> dict | None:
    """The day's coach moves (#4583) as the block, or None when there is no current day of
    them and the older restated text should stand in.

    A day the coaches were cast and none had anything to say is a day of moves: the block
    is ``absent`` with that sentence, never yesterday's restated numbers."""
    if not isinstance(moves, dict) or not parse_day_key(str(moves.get("date") or "")):
        return None
    day = str(moves["date"])
    age = _days_between(day, today)
    if age is None or age < 0 or age > COACH_STALE_DAYS:
        return None
    src = SOURCES["dashboard"]
    lines = []
    for ln in moves.get("lines") or []:
        text = str((ln or {}).get("text") or "").strip() if isinstance(ln, dict) else ""
        if not text or not ln.get("move") or not honest_text(text):
            continue
        bet = ln.get("bet") if isinstance(ln.get("bet"), dict) else None
        lines.append(
            {
                "coach": plain_name(ln.get("name")),
                "domain": domain_words(persona_of(str(ln.get("coach_id") or ""))),
                "text": _HONORIFIC.sub("", text),
                "as_of": day,
                "move": ln["move"],
                "move_label": ln.get("move_label"),
                "replies_to": plain_name(ln.get("replies_to_name")) or None,
                "bet_settles": (bet or {}).get("resolution_date") or None,
                "truncated": False,
                "when_text": None,
            }
        )
    lines = lines[:MAX_COACH_LINES]
    if not lines:
        return _block("absent", day, src, f"No coach had anything to say on {day_in_words(day)}.", voice=COACH_VOICE_MOVE)
    return _block("ok", day, src, "The coaches have written nothing yet.", {"lines": lines, "mixed_days": False}, voice=COACH_VOICE_MOVE)


def _coach_lines(dashboard: dict | None, today: str, persona_of_short, persona_of=None) -> dict:
    src = SOURCES["dashboard"]
    if dashboard is None:
        return _unavailable(src, "What the coaches said today")
    moves = _coach_moves(dashboard.get("moves"), today, persona_of) if persona_of else None
    if moves is not None:
        return moves
    lines = []
    for c in dashboard.get("coaches") or []:
        if not isinstance(c, dict) or c.get("absent"):
            continue
        text, truncated = _trim_to_sentence(str(c.get("position_summary") or ""))
        written = pacific_date_of(str(c.get("analysis_generated_at") or "")) if c.get("analysis_generated_at") else None
        if not text or not written or not honest_text(text):
            continue
        lines.append(
            {
                "coach": plain_name(c.get("name")),
                "domain": domain_words(persona_of_short(str(c.get("coach_id") or ""))),
                "text": _HONORIFIC.sub("", text),
                "as_of": written,
                "data_through": c.get("analysis_data_through"),
                "truncated": truncated,
            }
        )
    if not lines:
        return _block("absent", None, src, "The coaches have written nothing yet.", voice=COACH_VOICE)
    # Newest first; a stable sort keeps the served roster order within a day.
    lines = sorted(lines, key=lambda x: str(x["as_of"]), reverse=True)[:MAX_COACH_LINES]
    days = {x["as_of"] for x in lines}
    mixed = len(days) > 1
    for x in lines:
        # Two texts from different days: each one says which day it is from.
        x["when_text"] = f"Written {day_in_words(x['as_of'])}." if mixed else None
    newest = lines[0]["as_of"]
    data = {"lines": lines, "mixed_days": mixed}
    age = _days_between(newest, today)
    if age is not None and age > COACH_STALE_DAYS:
        return _block("stale", newest, src, f"Nothing new from the coaches since {day_in_words(newest)}.", data, voice=COACH_VOICE)
    return _block("ok", newest, src, "The coaches have written nothing yet.", data, voice=COACH_VOICE)


def _scorecard() -> dict:
    return _block("absent", None, None, "The scorecard is not built yet.", todo=SCORECARD_TODO)


def _record(predictions: dict | None, calibration: dict | None, today: str) -> dict:
    """The coaches' checked calls — NEVER the count alone (epic #4580 rule 3, #4585).

    Both upstreams or nothing: without the calibration reading there is no comparison to
    print beside the count, so the whole block is ``unavailable`` rather than a bare K of N.
    """
    src = [SOURCES["predictions"], SOURCES["calibration"]]
    if predictions is None or calibration is None:
        return _unavailable(src, "The coaches' record")
    overall = predictions.get("overall") or {}
    coaches_stratum = ((calibration.get("platform") or {}).get("strata") or {}).get("coaches")
    if not isinstance(coaches_stratum, dict):
        return _unavailable(src, "The coaches' record")
    right, decided = overall.get("confirmed"), overall.get("decided")
    as_of = (overall.get("due") or {}).get("as_of") or calibration.get("as_of") or today
    if not isinstance(decided, int) or not isinstance(right, int) or decided <= 0:
        return _block("absent", as_of, src, "No coach call has been checked yet.")
    skill = coaches_stratum.get("brier_skill")
    known = isinstance(skill, (int, float))
    beats = bool(known and skill > 0)
    if not known:
        comparison = "Too few checked calls yet to compare them with a simple guess."
    elif beats:
        comparison = "So far they beat a simple guess."
    else:
        comparison = "So far they do not beat a simple guess."
    data = {
        "right": right,
        "decided": decided,
        "count_text": f"{right} of {decided} checked calls right.",
        "beats_simple_guess": beats,
        "comparison_text": comparison,
        "brier_skill": skill if known else None,
        "skill_n": coaches_stratum.get("n"),
    }
    return _block("ok", as_of, src, "No coach call has been checked yet.", data)


def _decision_note(decisions: dict, today: str) -> dict:
    """The older source: the newest logged decision carrying his verbatim note (#1569)."""
    src = SOURCES["decisions"]
    notes = [
        d
        for d in decisions.get("decisions") or []
        if isinstance(d, dict) and str(d.get("note") or "").strip() and parse_iso_utc(d.get("note_at")) is not None
    ]
    if not notes:
        return _block("absent", None, src, "Nothing in his own words yet.")
    latest = max(notes, key=lambda d: parse_iso_utc(d["note_at"]) or datetime.min.replace(tzinfo=timezone.utc))
    day = pacific_date_of(str(latest["note_at"]))
    data = {"text": str(latest["note"]).strip(), "date": day, "date_text": day_in_words(day) if day else None}
    age = _days_between(day, today)
    if age is not None and age > HIS_WORDS_STALE_DAYS:
        return _block("stale", day, src, f"Nothing new in his own words since {day_in_words(day)}.", data)
    return _block("ok", day, src, "Nothing in his own words yet.", data)


def _owner_entry(owner_words: dict, today: str) -> dict | None:
    """The newest served owner-words entry (#4584) as a block, EXACTLY as typed, with its date and prompt — or None
    when there is none. A held entry is never served upstream, so it cannot reach here."""
    src = SOURCES["owner_words"]
    entries = [
        e
        for e in owner_words.get("entries") or []
        if isinstance(e, dict) and isinstance(e.get("text"), str) and e["text"].strip() and parse_day_key(str(e.get("date") or ""))
    ]
    if not entries:
        return None
    latest = max(entries, key=lambda e: str(e["date"]))
    day = str(latest["date"])
    age = _days_between(day, today)
    if age is None or age < 0:
        return None
    data = {
        "text": latest["text"],
        "date": day,
        "date_text": day_in_words(day),
        "prompt": latest.get("prompt") or None,
        "channel": latest.get("channel"),
    }
    if age > HIS_WORDS_STALE_DAYS:
        return _block("stale", day, src, f"Nothing new in his own words since {day_in_words(day)}.", data)
    return _block("ok", day, src, "Nothing in his own words yet.", data)


def _his_words(decisions: dict | None, owner_words: dict | None, today: str) -> dict:
    """His words lead with the newest owner-words entry inside the freshness bound; else the decisions note; else,
    when neither is fresh, whichever is newer (dated stale). A failed read of EITHER source is ``unavailable``: a
    missing entry must never read as silence, nor be covered by an older note."""
    if decisions is None or owner_words is None:
        return _unavailable([SOURCES["owner_words"], SOURCES["decisions"]], "His own words")
    entry = _owner_entry(owner_words, today)
    if entry is not None and entry["state"] == "ok":
        return entry
    note = _decision_note(decisions, today)
    if entry is None or note["state"] == "ok":
        return note
    if note["state"] == "absent" or str(entry["as_of"]) >= str(note["as_of"] or ""):
        return entry
    return note


def _catch_up(journal: dict | None, today: str) -> dict:
    src = SOURCES["journal"]
    if journal is None:
        return _unavailable(src, "The list of chapters")
    posts = sorted(_published_posts(journal, today), key=lambda p: (p.get("sequence") or 0, str(p["date"])))
    if not posts:
        return _block("absent", None, src, "No chapters yet.")
    items = [{"label": p.get("label"), "title": p["title"], "url": p["url"], "date": p["date"]} for p in posts]
    return _block("ok", posts[-1]["date"], src, "No chapters yet.", {"items": items})


def _follow(cadence: dict | None, now: datetime, today: str) -> dict:
    src = ["common.subscriber_cadence", SOURCES["cadence"]]
    sends = [
        {"sender": s.function_name, "next_date": next_send_date(s.cron, now), "conditional": s.conditional} for s in sc.SUBSCRIBER_SENDERS
    ]
    ch = (cadence or {}).get("chronicle") or {}
    data = {
        "promise": sc.promise_sentence(),
        "sends": sends,
        "next_chapter_date": None if cadence is None or ch.get("paused") else ch.get("next_date"),
        "next_chapter_state": "unavailable" if cadence is None else ("absent" if ch.get("paused") or not ch.get("next_date") else "ok"),
    }
    return _block("ok", today, src, "The email schedule is not served right now.", data)


# ── the document ────────────────────────────────────────────────────────────────


def compose(
    bodies: dict,
    *,
    today: str,
    now: datetime,
    start_date: str,
    persona_of: Callable[[str], dict | None],
    persona_of_short: Callable[[str], dict | None],
    metric_words: Callable[[Any], str | None],
) -> dict:
    """The edition from the upstream bodies. Pure — no I/O, no clock of its own.

    ``bodies[key]`` is the parsed body an existing route served for ``SOURCES[key]``, or
    None when that read failed. ``persona_of(persona_id)`` / ``persona_of_short(short_id)``
    return a persona dict from the registry; ``metric_words`` is the server-side metric
    vocabulary. Everything a block says is derived from these arguments.
    """
    b = {k: bodies.get(k) for k in SOURCES}
    day_n = pacific_day_n(start_date, today) or None
    his_words = _his_words(b["decisions"], b["owner_words"], today)
    blocks = {
        "premise": _premise(today),
        "chapter": _chapter(b["journal"], b["panelcast"], today, persona_of),
        "next": _next(b["cadence"], b["docket"], today, persona_of, metric_words),
        "today": _today(b["journey"], today),
        "week": _week(b, today),
        "life": _life(b, his_words, today),
        "coach_lines": _coach_lines(b["dashboard"], today, persona_of_short, persona_of),
        "scorecard": _scorecard(),
        "record": _record(b["predictions"], b["calibration"], today),
        "his_words": his_words,
        "catch_up": _catch_up(b["journal"], today),
        "follow": _follow(b["cadence"], now, today),
    }
    return {"as_of": today, "day_n": day_n, "order": list(ORDER), "blocks": {k: blocks[k] for k in ORDER}}


# ── the shell ───────────────────────────────────────────────────────────────────


def body_of(response: Any) -> dict | None:
    """A route response -> its parsed body, or None when it is not a clean 200.

    A 200 carrying ``_meta.degraded`` is a fallback payload from inside an ``except``
    (#2686) — it reads like an empty measurement, so it is a failed read here."""
    if not isinstance(response, dict) or response.get("statusCode") != 200:
        return None
    try:
        body = json.loads(response.get("body") or "")
    except (TypeError, ValueError):
        return None
    if not isinstance(body, dict) or (body.get("_meta") or {}).get("degraded"):
        return None
    return body


def _read_s3_json(key: str) -> dict | None:
    """One public manifest from S3; None on any failure (never an empty dict)."""
    import os

    import boto3

    from web.site_api_common import S3_REGION

    try:
        obj = boto3.client("s3", region_name=S3_REGION).get_object(Bucket=os.environ.get("S3_BUCKET", "matthew-life-platform"), Key=key)
        data = json.loads(obj["Body"].read())
        return data if isinstance(data, dict) else None
    except Exception as e:  # noqa: BLE001 — a failed read is a block state, not a 500
        from web.site_api_common import logger

        logger.warning(f"[edition] manifest read failed ({type(e).__name__})")
        return None


def read_bodies(read_route: Callable[[str, dict], Any], read_s3: Callable[[str], dict | None] = _read_s3_json) -> dict:
    """Every upstream body, each read independently: one failure never blanks another."""
    out: dict = {}
    for key, path in SOURCES.items():
        try:
            out[key] = read_s3(_S3_KEYS[key]) if key in _S3_KEYS else body_of(read_route(path, dict(_ROUTE_QS.get(key, {}))))
        except Exception as e:  # noqa: BLE001
            from web.site_api_common import logger

            logger.warning(f"[edition] {path} read failed ({type(e).__name__})")
            out[key] = None
    return out


def handle_edition(read_route: Callable[[str, dict], Any]) -> dict:
    """GET /api/edition. ``read_route(path, qs)`` is the site API's own in-process dispatcher."""
    from coach import persona_registry
    from common.pacific_time import pacific_today

    from web.prediction_reason import metric_words
    from web.site_api_common import EXPERIMENT_START, _error, _ok, logger

    try:
        now = datetime.now(timezone.utc)
        doc = compose(
            read_bodies(read_route),
            today=pacific_today(),
            now=now,
            start_date=EXPERIMENT_START,
            persona_of=persona_registry.resolve,
            persona_of_short=lambda sid: persona_registry.by_short_id(sid)[1],
            metric_words=metric_words,
        )
        return _ok(doc, cache_seconds=CACHE_SECONDS)
    except Exception as e:  # noqa: BLE001
        logger.error(f"[site_api] /api/edition failed: {type(e).__name__}")
        return _error(500, "edition unavailable")
