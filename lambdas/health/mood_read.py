"""mood_read.py — one mood / stress / connection read, journal first, the evening check-in behind it (#5123).

WHY. The mind coach's mood read was journal-only: ``coach_narrative_orchestrator`` built ``journal_mood`` from the
enriched Notion entries and dropped it below 5 scored entries in 21 days. The journal is ``monitored: False`` and
mostly dark, so the read starved, while the 20-second evening check-in (#5106: hunger, stress, cravings 0-4 and
one word) lands most evenings. This module makes the choice once, states it, and never invents a number:

  * ``journal``        — enough scored journal entries in the window: the #549 aggregate, as before.
  * ``evening_checkin`` — the journal is below the floor and enough check-ins carry ``stress``: the stress
    trajectory on the check-in's own 0-4 scale. The check-in asks nothing about mood, connection or
    flourishing, so those are ``None`` with the reason in words, never borrowed from somewhere else.
  * ``unavailable``    — both are below the floor: no trend and no number, only the two counts.

PRIVACY (``privacy.field_tiers``: ``evening_checkin`` is TIER_OWNER_ONLY; DATA_GOVERNANCE: "no public projection
of any kind"). The orchestrator's brief feeds coach generation whose output is served on the site
(``site_api_coach_narrative``), so that path is the PUBLISHED one and the check-in never enters it:

  * ``published_signal`` takes journal entries only — it has no check-in parameter, so a published caller cannot
    pass one — and ``for_published`` lets through only a ``PUBLISHED_SOURCES`` read (fail-closed: an
    ``evening_checkin``, ``unavailable`` or unknown source is dropped whole).
  * The check-in fallback is read only by ``owner_read`` / ``owner_lines``, which feed the owner's own Telegram
    mind-coach thread (``coach.coach_domain_facts``, the same owner channel as the clinical record and the
    coach-vision block). Those lines carry trend words, counts and means — never the check-in's ``word`` and
    never journal text (the notable quote stays on the journal path, behind its own privacy gate).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

WINDOW_DAYS = 21
MIN_ENTRIES = 5  # below this many readings a trajectory is too thin to be honest (#549's floor, now shared)
TREND_MIN_N = 4  # a first-half / second-half split needs at least two on each side
TREND_DELTA = 0.3  # the #549 threshold for "rising" / "falling"

SOURCE_JOURNAL = "journal"
SOURCE_CHECKIN = "evening_checkin"
SOURCE_UNAVAILABLE = "unavailable"

# The only sources a published caller may carry. Everything else is held back whole (fail-closed).
PUBLISHED_SOURCES = frozenset({SOURCE_JOURNAL})
OWNER_ONLY_SOURCES = frozenset({SOURCE_CHECKIN})

CHECKIN_SCALE = "0-4"  # coach/evening_checkin.py SCALE_MIN..SCALE_MAX, 4 = the most
CHECKIN_FIELDS = ("stress", "hunger", "cravings")
NOT_ASKED = "the evening check-in asks hunger, stress and cravings (0-4) and one word; nothing about this"

JOURNAL_PK = "USER#matthew#SOURCE#notion"
CHECKIN_PK = "USER#matthew#SOURCE#evening_checkin"


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN is an absence


def trend(vals: list) -> dict[str, Any]:
    """First-half vs second-half average — the lightweight technique mcp.tools_journal's mood trend uses."""
    if len(vals) < TREND_MIN_N:
        return {"direction": "insufficient_data", "avg": round(sum(vals) / len(vals), 2) if vals else None, "n": len(vals)}
    mid = len(vals) // 2
    delta = round(sum(vals[mid:]) / (len(vals) - mid) - sum(vals[:mid]) / mid, 2)
    direction = "rising" if delta > TREND_DELTA else "falling" if delta < -TREND_DELTA else "stable"
    return {"direction": direction, "avg": round(sum(vals) / len(vals), 2), "delta": delta, "n": len(vals)}


def _top(values: Iterable[Any], n: int = 4) -> list:
    counts: dict = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return [k for k, _ in sorted(counts.items(), key=lambda x: -x[1])[:n]]


def _entry_date(e: Mapping[str, Any]) -> str:
    d = e.get("date")
    if d:
        return str(d)
    sk = str(e.get("sk", ""))
    return sk.split("DATE#")[1][:10] if "DATE#" in sk else ""


def scored_journal_count(entries: list) -> int:
    """The floor's count: the larger of the mood-scored and the stress-scored entries."""
    moods = sum(1 for e in entries if _num(e.get("enriched_mood")) is not None)
    stresses = sum(1 for e in entries if _num(e.get("enriched_stress")) is not None)
    return max(moods, stresses)


def journal_signal(entries: list, window_days: int = WINDOW_DAYS) -> Optional[dict[str, Any]]:
    """#549's journal aggregate (moved here unchanged, plus ``source``), or None below the floor."""
    entries = sorted(entries or [], key=_entry_date)
    if not entries or scored_journal_count(entries) < MIN_ENTRIES:
        return None
    moods: list[float] = []
    stresses: list[float] = []
    emotions: list[Any] = []
    themes: list[Any] = []
    social: list[Any] = []
    quote, quote_date = None, None
    for entry in entries:
        if (m := _num(entry.get("enriched_mood"))) is not None:
            moods.append(m)
        if (s := _num(entry.get("enriched_stress"))) is not None:
            stresses.append(s)
        emotions.extend(entry.get("enriched_emotions") or [])
        themes.extend(entry.get("enriched_themes") or [])
        if entry.get("enriched_social_quality"):
            social.append(entry["enriched_social_quality"])
        if entry.get("enriched_notable_quote"):  # the latest wins — the most recent texture
            quote, quote_date = entry["enriched_notable_quote"], _entry_date(entry)
    social_dist: dict = {}
    for sq in social:
        social_dist[sq] = social_dist.get(sq, 0) + 1
    return {
        "source": SOURCE_JOURNAL,
        "window_days": window_days,
        "entries_analyzed": len(entries),
        "mood_trend": trend(moods),
        "stress_trend": trend(stresses),
        "dominant_emotions": _top(emotions),
        "dominant_themes": _top(themes),
        "social_quality_distribution": social_dist,
        "alone_ratio": round(social_dist.get("alone", 0) / len(social), 2) if social else None,
        "notable_quote": quote,
        "notable_quote_date": quote_date,
    }


def checkin_signal(rows: list, window_days: int = WINDOW_DAYS) -> Optional[dict[str, Any]]:
    """The check-in fallback, or None when fewer than MIN_ENTRIES evenings carry a ``stress`` rating.

    Numbers only: the ``word`` is never read into the result. Mood, connection and flourishing are None with
    the reason — the check-in does not ask about them, and borrowing them from another source would be a guess."""
    rows = sorted((r for r in rows or [] if not r.get("tombstone")), key=_entry_date)
    series: dict[str, list] = {f: [] for f in CHECKIN_FIELDS}
    answered = 0
    for r in rows:
        vals = {f: _num(r.get(f)) for f in CHECKIN_FIELDS}
        if any(v is not None for v in vals.values()):
            answered += 1
        for f, v in vals.items():
            if v is not None:
                series[f].append(v)
    if len(series["stress"]) < MIN_ENTRIES:
        return None
    return {
        "source": SOURCE_CHECKIN,
        "window_days": window_days,
        "evenings_answered": answered,
        "scale": CHECKIN_SCALE,
        "stress_trend": trend(series["stress"]),
        "hunger_trend": trend(series["hunger"]),
        "cravings_trend": trend(series["cravings"]),
        "mood_trend": None,
        "social_quality": None,
        "flourishing": None,
        "not_measured": NOT_ASKED,
    }


def resolve(journal_entries: list, checkin_rows: list, window_days: int = WINDOW_DAYS) -> dict[str, Any]:
    """journal > evening_checkin > unavailable, always with ``source`` named. Never a default number."""
    j = journal_signal(journal_entries, window_days)
    if j is not None:
        return j
    c = checkin_signal(checkin_rows, window_days)
    if c is not None:
        c["journal_scored_entries"] = scored_journal_count(journal_entries or [])
        return c
    return {
        "source": SOURCE_UNAVAILABLE,
        "window_days": window_days,
        "journal_scored_entries": scored_journal_count(journal_entries or []),
        "checkin_stress_evenings": sum(1 for r in checkin_rows or [] if _num(r.get("stress")) is not None),
        "min_entries": MIN_ENTRIES,
    }


def published_signal(journal_entries: list, window_days: int = WINDOW_DAYS) -> Optional[dict[str, Any]]:
    """The read a PUBLISHED caller may build: journal only. There is deliberately no check-in parameter."""
    return journal_signal(journal_entries, window_days)


def for_published(signal: Any) -> Optional[dict[str, Any]]:
    """The signal if a published surface may carry it, else None (fail-closed on the source).

    A dict with no ``source`` predates #5123; its only producer was the journal aggregate, so it reads as journal."""
    if not isinstance(signal, dict):
        return None
    source = signal.get("source", SOURCE_JOURNAL)
    if source not in PUBLISHED_SOURCES:
        logger.info("mood read: %s source held back from a published brief", source)
        return None
    return signal


# ── the owner channel ────────────────────────────────────────────────────────────────────────────────


def _query_all(table: Any, pk: str, lo: str, hi: str) -> list:
    kwargs: dict[str, Any] = {
        "KeyConditionExpression": "pk = :pk AND sk BETWEEN :lo AND :hi",
        "ExpressionAttributeValues": {":pk": pk, ":lo": lo, ":hi": hi},
    }
    items: list = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return items
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def owner_read(table: Any, today: str, window_days: int = WINDOW_DAYS) -> Optional[dict[str, Any]]:
    """The resolved read for the owner's own channel (journal + check-in over the trailing window), or None
    when the store cannot be read (an honest absence, never a stand-in)."""
    try:
        start = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=window_days)).strftime("%Y-%m-%d")
        journal = [
            i
            for i in _query_all(table, JOURNAL_PK, f"DATE#{start}#journal", f"DATE#{today}#journal#~")
            if "#journal#" in str(i.get("sk", "")) and not i.get("tombstone")
        ]
        checkins = [i for i in _query_all(table, CHECKIN_PK, f"DATE#{start}", f"DATE#{today}~") if str(i.get("sk", "")).count("#") == 1]
    except Exception as e:  # noqa: BLE001 — the owner's chat runs without the read
        logger.warning("mood read: owner read failed: %s", type(e).__name__)
        return None
    read = resolve(journal, checkins, window_days)
    if read["source"] == SOURCE_JOURNAL:
        read["flourishing"] = _journal_flourishing(journal)
    return read


_FLOURISHING_KEYS = ("values_lived_count", "gratitude_count", "growth_signals_count", "ownership_score", "social_quality_score")


def _journal_flourishing(entries: list) -> Optional[dict[str, Any]]:
    """The window's PERMA signals through THE flourishing aggregate (``health.flourishing``), never a second one."""
    from health.flourishing import aggregate_entries

    body = aggregate_entries(entries)
    return {k: body[k] for k in _FLOURISHING_KEYS if k in body} if body else None


def _trend_words(t: Optional[Mapping[str, Any]], scale: str) -> str:
    if not t or not t.get("n"):
        return "no readings"
    if t.get("direction") == "insufficient_data":
        return f"too few readings for a direction (n={t['n']}, mean {t.get('avg')} on {scale})"
    return f"{t['direction']} (mean {t.get('avg')} on {scale}, half-to-half change {t.get('delta'):+}, n={t['n']})"


def owner_lines(read: Optional[Mapping[str, Any]]) -> list:
    """Plain lines for the owner's Telegram mind thread. Never the check-in word, never journal text."""
    if not read:
        return ["Mood read: could not be read today — say so rather than guessing how he feels."]
    src, w = read.get("source"), read.get("window_days")
    if src == SOURCE_JOURNAL:
        lines = [
            f"Mood read source: his journal ({read.get('entries_analyzed')} entries in the last {w} days).",
            f"Journal mood: {_trend_words(read.get('mood_trend'), 'the journal scale')}.",
            f"Journal stress: {_trend_words(read.get('stress_trend'), 'the journal scale')}.",
        ]
        if read.get("social_quality_distribution"):
            dist = ", ".join(f"{k} {v}" for k, v in sorted(read["social_quality_distribution"].items()))
            lines.append(f"Connection in the journal: {dist} (alone ratio {read.get('alone_ratio')}).")
        if read.get("flourishing"):
            parts = ", ".join(f"{k} {v}" for k, v in read["flourishing"].items())
            lines.append(f"Flourishing in the journal (LLM-coded from his entries): {parts}.")
        return lines
    if src == SOURCE_CHECKIN:
        return [
            f"Mood read source: the evening check-in — the journal had {read.get('journal_scored_entries')} scored entries in "
            f"the last {w} days, under the {MIN_ENTRIES}-entry floor. {read.get('evenings_answered')} evenings answered.",
            f"Reported stress: {_trend_words(read.get('stress_trend'), CHECKIN_SCALE)}.",
            f"Reported hunger: {_trend_words(read.get('hunger_trend'), CHECKIN_SCALE)}.",
            f"Reported cravings: {_trend_words(read.get('cravings_trend'), CHECKIN_SCALE)}.",
            f"Mood, connection and flourishing: not measured this window — {NOT_ASKED}. Ask him; do not infer them.",
        ]
    return [
        f"Mood read: unavailable — the journal had {read.get('journal_scored_entries')} scored entries and the evening "
        f"check-in {read.get('checkin_stress_evenings')} stress ratings in the last {w} days (each needs {MIN_ENTRIES}). "
        "No mood, stress, connection or flourishing number exists for this window; do not supply one."
    ]
