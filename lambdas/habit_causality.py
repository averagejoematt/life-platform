"""habit_causality.py — habit causality capture + cross-page completion merge (#422, EVR-01/02/03).

Shared, bundled module (ONE bundle, no layer — #781). Pure functions only: no AWS
calls, no I/O at import. Both the ingestion path (Habitify notes → habit-day records),
the site-API read path, and the MCP backfill tools import from here so the deterministic
conventions live in exactly ONE place.

What this module owns
---------------------
1. ``parse_note`` — the ONLY interpretation applied to a raw habit note. It recognises an
   optional, case-insensitive ``trigger:`` / ``reward:`` line prefix and lifts it into a
   structured field. Everything else stays verbatim in ``raw``. There is NO inference
   beyond these literal prefixes (ADR-104 — a note with no prefix is context, not a
   guessed cause).

2. ``CROSS_PAGE_SIGNALS`` + ``merge_cross_page_group_scores`` — the EVR-03 wiring. Exactly
   ONE daily-completion signal per evidence page feeds the habit GROUP scores, and a
   day+group the habit tracker already scored is NEVER touched (explicit double-count
   prevention). Cross-page contributions only ever FILL a gap the tracker left empty, and
   they are returned tagged so no consumer can mistake a borrowed signal for a tracked one.
"""

from __future__ import annotations

import re

# ── Note conventions (EVR-01/02) ───────────────────────────────────────────────
# Literal, case-insensitive line prefixes. These are the ENTIRE parsing surface —
# anything else in the note is preserved raw. Kept tiny on purpose (ADR-104).
_TRIGGER_PREFIXES = ("trigger:", "cue:", "because:")
_REWARD_PREFIXES = ("reward:", "payoff:", "felt:")

_NOTE_MAX = 500  # cap stored/rendered note length (DDB item-size guard + sanity)


def clip_note(text: str | None) -> str:
    """Trim + collapse a raw note to a bounded, storable string. Verbatim otherwise."""
    s = (text or "").strip()
    if len(s) > _NOTE_MAX:
        s = s[:_NOTE_MAX].rstrip() + "…"
    return s


def parse_note(text: str | None) -> dict:
    """Deterministic, labeled light-convention parse of ONE habit note.

    Recognises an optional ``trigger:`` / ``reward:`` prefix at the start of any line
    (case-insensitive). Lines without a recognised prefix are left untouched and returned
    joined in ``raw``. Never infers a trigger or reward that wasn't explicitly written.

    Returns ``{"trigger": str|None, "reward": str|None, "raw": str}``.
    """
    raw = clip_note(text)
    if not raw:
        return {"trigger": None, "reward": None, "raw": ""}
    trigger = None
    reward = None
    leftover: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        low = stripped.lower()
        hit = False
        # Every prefix ends with ":" so the value is everything after the FIRST colon —
        # written as split(":", 1) rather than a computed slice (black/flake8 E203 truce).
        for p in _TRIGGER_PREFIXES:
            if low.startswith(p):
                val = stripped.split(":", 1)[1].strip()
                if val:
                    trigger = val
                hit = True
                break
        if hit:
            continue
        for p in _REWARD_PREFIXES:
            if low.startswith(p):
                val = stripped.split(":", 1)[1].strip()
                if val:
                    reward = val
                hit = True
                break
        if not hit:
            leftover.append(stripped)
    return {"trigger": trigger, "reward": reward, "raw": "\n".join(leftover).strip() or raw}


def slugify_habit(name: str | None) -> str:
    """Stable, key-safe slug for a habit name (for the MCP backfill side store)."""
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-")
    return s or "habit"


# ── Cross-page completion signals (EVR-03) ─────────────────────────────────────
# ONE daily-completion signal per evidence page, each mapped to the Habitify P40 habit
# GROUP it reinforces. The signal source is a component score already stored on the
# ``computed_metrics`` day record (written by daily_metrics_compute_lambda) — so every
# signal is a real, pre-computed daily fact, not a new derivation. An absent component =>
# absent signal (honest empty, never assumed present).
#
# Deliberately one-per-page: adding a second signal for the same page would be a second
# door to the same group and reintroduce the double-counting this design prevents.
CROSS_PAGE_SIGNALS: dict[str, dict] = {
    # evidence page   component on computed_metrics   habit group it feeds
    "movement": {"component": "movement", "group": "Performance"},
    "nutrition": {"component": "nutrition", "group": "Nutrition"},
    "recovery": {"component": "sleep_quality", "group": "Recovery"},
    "mind": {"component": "journal", "group": "Growth"},
}

# Minimum component score for a page to count as a daily completion for its group.
# A component present but near-zero is not a "completion" — it's an honest low day.
_CROSS_PAGE_MIN_SCORE = 50.0


def derive_cross_page_signals(component_scores: dict | None) -> dict:
    """Map ONE computed_metrics day's component scores → {group: score} cross-page signals.

    Only emits a group when its page's component is present AND clears the completion
    floor. Missing/low components emit nothing (no fabricated completion).
    """
    out: dict[str, float] = {}
    if not component_scores:
        return out
    for spec in CROSS_PAGE_SIGNALS.values():
        val = component_scores.get(spec["component"])
        if val is None:
            continue
        try:
            score = float(val)
        except (TypeError, ValueError):
            continue
        if score >= _CROSS_PAGE_MIN_SCORE:
            # If two pages ever mapped to one group (they don't, by construction),
            # keep the strongest signal — still one contribution per group per day.
            out[spec["group"]] = max(out.get(spec["group"], 0.0), round(score))
    return out


def merge_cross_page_group_scores(
    tracker_groups_by_date: dict[str, dict],
    cross_signals_by_date: dict[str, dict],
) -> dict[str, dict]:
    """Fill habit-group score gaps with cross-page signals — never double-count.

    Args:
      tracker_groups_by_date: ``{date: {group: pct}}`` the habit tracker itself recorded.
      cross_signals_by_date:  ``{date: {group: score}}`` derived from other pages.

    Returns ``{date: {"groups": {...}, "cross_page": {...}}}`` where:
      * ``groups`` = the tracker's groups for that date, with cross-page groups ADDED only
        for (date, group) pairs the tracker left empty (the explicit dedup — a group the
        tracker scored is never overwritten or added to).
      * ``cross_page`` = just the groups that were sourced cross-page that date, so the
        provenance is auditable and a borrowed signal is never rendered as a tracked one.
    """
    merged: dict[str, dict] = {}
    all_dates = set(tracker_groups_by_date) | set(cross_signals_by_date)
    for date in all_dates:
        tracked = dict(tracker_groups_by_date.get(date) or {})
        signals = cross_signals_by_date.get(date) or {}
        cross_added: dict[str, float] = {}
        for group, score in signals.items():
            if group in tracked:
                # DOUBLE-COUNT PREVENTION: the habit tracker already owns this group
                # for this day — the cross-page signal is dropped, not summed.
                continue
            tracked[group] = score
            cross_added[group] = score
        merged[date] = {"groups": tracked, "cross_page": cross_added}
    return merged
