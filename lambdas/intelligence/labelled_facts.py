"""labelled_facts — labelled-fact checks for the weekly analyzer's grounding gate (#4580 B-01).

The allow-list half of the gate (`grounded_generation.fabricated_numbers`) asks only "is this number anywhere
in the input?". The lead read of 2026-10-18 shows what that misses: "his starting weight of 302.2 pounds"
(302.2 was the CURRENT weight, in the input; the start is 327.3), "54 logged training sessions in thirty days"
(the page serves 39), "his food logs stopped four days ago", "his journal entries have been silent for forty
days" — each a real number attached to the wrong LABEL. The starting-weight class already exists
(`grounded_generation.baseline_freshness_findings`, armed by `baseline_lbs`) and the current-weight class is
`coach_input_facts.weight_findings`; this module adds the three label-to-number checks they do not cover,
against the facts the caller passes:

    sessions_30d      the served 30-day workout count (what /api/training_overview prints as workouts_30d)
    food_lag_days     the served nutrition record's lag (days since the last food log)
    journal_gap_days  the journal channel's gap_days from the engagement signal (the prompt's own count)

A fact the caller does not have (None) is never checked — nothing to judge against is a skip, not a pass on
a made-up number. Findings use the gate's "contradiction" shape, so `correction_prompt` tells the one rewrite
"Use <canonical>" and a residual finding HOLDS the read (the caller keeps its prior record, #4703).

`reader_surface_findings` is the public-register half: the ONE cycle/attempt/reset pattern
(`content.story_checks.cycle_reference_findings`, owner ruling 2026-09-26) as gate findings, for a reader-bound
field only — the owner-read `analysis`/`weekly_priority` is not a reader surface.

The findings are pure (no boto3, no clock); `labelled_facts` reads through the caller's own query/engagement seams.
"""

import logging
import re
from typing import Optional

from content.story_checks import cycle_reference_findings

logger = logging.getLogger(__name__)

GAP_TOLERANCE_DAYS = 1  # the same one-day tolerance `coach_input_facts` gives a logging gap (a lag-day boundary)

_UNITS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}
_TEENS = {
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
    "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19,
}  # fmt: skip
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_NUM = r"\d{1,3}|(?:" + "|".join(_TENS) + r")(?:[- ](?:" + "|".join(_UNITS) + r"))?|" + "|".join(list(_TEENS) + list(_UNITS))


def number_value(token: str) -> Optional[int]:
    """'54' -> 54, 'forty' -> 40, 'forty-two' -> 42, 'four' -> 4; None for anything else."""
    t = (token or "").strip().lower()
    if t.isdigit():
        return int(t)
    if t in _UNITS:
        return _UNITS[t]
    if t in _TEENS:
        return _TEENS[t]
    parts = re.split(r"[- ]", t)
    if parts and parts[0] in _TENS:
        if len(parts) == 1:
            return _TENS[parts[0]]
        if len(parts) == 2 and parts[1] in _UNITS:
            return _TENS[parts[0]] + _UNITS[parts[1]]
    return None


_THIRTY_DAYS = r"(?:the\s+)?(?:last\s+|past\s+)?(?:thirty|30)\s+days"
_SESSIONS = re.compile(
    rf"\b(?P<n>{_NUM})\s+(?:logged\s+)?(?:training\s+)?(?:sessions|workouts)\s+(?:logged\s+)?(?:in|over|across|during)\s+{_THIRTY_DAYS}\b",
    re.IGNORECASE,
)
_FOOD_GAP = [
    re.compile(
        rf"\bfood[- ]?log(?:s|ging)?\s+(?:stopped|ended|went\s+(?:quiet|dark|silent)|paused)\s+(?P<n>{_NUM})\s+days?\s+ago\b", re.IGNORECASE
    ),
    re.compile(rf"\bno\s+food[- ]?logs?\s+(?:in|for)\s+(?:the\s+)?(?:last\s+|past\s+)?(?P<n>{_NUM})\s+days\b", re.IGNORECASE),
]
_JOURNAL_GAP = [
    re.compile(
        rf"\bjournal(?:\s+entries)?\s+(?:has|have)\s+(?:been\s+)?(?:silent|quiet|dark|empty)\s+(?:for\s+)?(?P<n>{_NUM})\s+days\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\b(?P<n>{_NUM})\s+days\s+(?:without|since)\s+(?:a\s+|his\s+(?:last\s+)?|the\s+last\s+)?journal(?:\s+entry)?\b", re.IGNORECASE
    ),
    re.compile(
        rf"\bhas(?:n['’]t|\s+not)\s+(?:journal(?:l)?ed|written\s+in\s+his\s+journal)\s+(?:in|for)\s+(?P<n>{_NUM})\s+days\b", re.IGNORECASE
    ),
]


def _finding(metric, cited, canonical, detail, excerpt):
    return {"type": "contradiction", "metric": metric, "cited": cited, "canonical": canonical, "detail": detail, "excerpt": excerpt[:200]}


def labelled_fact_findings(text: str, facts: Optional[dict], reader=None) -> list:
    """Every session-count / food-log-gap / journal-gap figure in `text` that disagrees with the labelled `facts`,
    plus `reader(text)`'s findings when the caller grades a reader-bound field (the analyzer's `_gate_prose`)."""
    out = list(reader(text)) if reader is not None and text else []
    if not text or not facts:
        return out
    sessions = facts.get("sessions_30d")
    if sessions is not None:
        for m in _SESSIONS.finditer(text):
            v = number_value(m.group("n"))
            if v is not None and v != int(sessions):
                out.append(
                    _finding(
                        "sessions_30d",
                        v,
                        float(sessions),
                        f"claims {v} training sessions in thirty days; the served 30-day count is {int(sessions)}",
                        m.group(0),
                    )
                )
    for metric, pats, key, what in (
        ("food_log_gap_days", _FOOD_GAP, "food_lag_days", "days since the last food log"),
        ("journal_gap_days", _JOURNAL_GAP, "journal_gap_days", "days since the last journal entry"),
    ):
        canon = facts.get(key)
        if canon is None:
            continue
        for pat in pats:
            for m in pat.finditer(text):
                v = number_value(m.group("n"))
                if v is not None and abs(v - float(canon)) > GAP_TOLERANCE_DAYS:
                    out.append(_finding(metric, v, float(canon), f"claims {v} {what}; the served record says {int(canon)}", m.group(0)))
    return out


def reader_surface_findings(text: str) -> list:
    """The cycle/attempt/reset count-or-reference class as gate findings, for a READER-bound field only."""
    return [
        {"type": "reader_surface", "metric": "cycle_reference", "detail": d.replace("story-door: ", ""), "excerpt": d[-200:]}
        for d in cycle_reference_findings(text or "")
    ]


# ── the labelled facts themselves (moved out of ai_expert_analyzer_lambda, which sits at its size ceiling) ──
def served_sessions_30d(query_source, today_str: str, floor: str) -> int:
    """The 30-day workout count the site serves (/api/training_overview `workouts_30d`) over the 30-date window
    ending today: THE session count (`training.session_count`, #5387) over the Strava and Hevy rows — one gym visit
    is one workout, never Hevy's push plus the ride inside it — the served definition itself, never re-derived
    (the prompt's old "Hevy + Strava ROWS" count said 54 where the page said 39)."""
    from datetime import datetime, timedelta

    from training import session_count

    start = max((datetime.strptime(today_str, "%Y-%m-%d") - timedelta(days=29)).strftime("%Y-%m-%d"), floor)
    strava, hevy = query_source("strava", start, today_str), query_source("hevy", start, today_str)
    return session_count.count(strava=strava, hevy=hevy, start_date=start, end_date=today_str)["sessions"]


def _journal_gap(signal: Optional[dict]) -> Optional[int]:
    for det in ((signal or {}).get("channel_detail") or {}).values():
        if isinstance(det, dict) and det.get("label") == "journal" and det.get("gap_days") is not None:
            return int(det["gap_days"])
    return None


def labelled_facts(gen_date_iso: str, served: Optional[dict], query_source, engagement, floor: str) -> dict:
    """The facts `labelled_fact_findings` checks against; None = unknown (a skip). Read per gate call — a few cheap
    reads per run, and no warm-container cache that could hand one run's facts to the next."""
    out = {"sessions_30d": None, "food_lag_days": ((served or {}).get("nutrition") or {}).get("lag_days"), "journal_gap_days": None}
    try:
        out["sessions_30d"] = served_sessions_30d(query_source, gen_date_iso, floor)
    except Exception as e:  # noqa: BLE001 — an unknown count is a skipped check, never a made-up one
        logger.warning("labelled facts: served session count unavailable (check skipped): %s", e)
    try:
        out["journal_gap_days"] = _journal_gap(engagement())
    except Exception as e:  # noqa: BLE001
        logger.warning("labelled facts: journal gap unavailable (check skipped): %s", e)
    return out


def count_bits(day_n: int, sessions_30d: Optional[int], nutrition: Optional[dict], signal: Optional[dict]) -> list:
    """#914-C: the synthesis prompt's DETERMINISTIC COUNTS — the same labelled facts the gate checks the prose against.
    The live integrator conflated numbers ("ten training sessions" vs the payload's 9), so it is given labelled counts
    with a no-arithmetic rule and cites them, never re-derives them."""
    bits = [f"experiment day_n = {day_n}"]
    if sessions_30d is not None:
        bits.append(f"workouts in the last 30 days (the count the site prints) = {sessions_30d}")
    if nutrition:
        bits.append(
            f"food-log days since {nutrition.get('window_start')} = {nutrition.get('days_logged')}; "
            f"last food log = {nutrition.get('latest_log_date')}"
        )
    for src, det in sorted(((signal or {}).get("channel_detail") or {}).items()):
        if not isinstance(det, dict):
            continue
        label, gap = det.get("label") or src, det.get("gap_days")
        bits.append(f"{label} gap_days = {int(gap)}" if gap is not None else f"{label} gap_days = unknown (nothing logged in window)")
    return bits
