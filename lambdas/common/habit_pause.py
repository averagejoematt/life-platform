"""habit_pause.py — the `paused_since` facet on a habit_registry entry (#5007).

A habit paused on a date is NOT SCHEDULED from that date on, the way a `paused` source in
`ingestion/source_registry.py` is intentionally off and never counted stale. The facet is one
ISO date on the registry entry (`"paused_since": "2026-10-10"`); an entry without it is
scheduled as before. Nothing about WHY a habit is paused is ever recorded here (public repo).

What "not scheduled" means, everywhere it is read:
  * not a miss (`scoring_engine.habitify_reading` returns None — UNOBSERVED, the same ruling
    as a habit the day never names, ADR-104) — so no score, streak, completion rate, synergy
    miss or effort count sees it after `paused_since`;
  * not in the habit-reflection queue, not in the Saturday skipped-habits nag;
  * reported as `paused`, never `missed`, by the status readers.

Days BEFORE `paused_since` are history and read exactly as they always did.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional


def paused_since(meta: Optional[Mapping[str, Any]]) -> Optional[str]:
    """The entry's `paused_since` ISO date, or None when it is scheduled."""
    if not isinstance(meta, Mapping):
        return None
    raw = meta.get("paused_since")
    return raw.strip() if isinstance(raw, str) and raw.strip() else None


def is_paused_on(meta: Optional[Mapping[str, Any]], date_str: Optional[str]) -> bool:
    """True when `date_str` (YYYY-MM-DD) is on or after the entry's `paused_since`.

    ISO dates compare lexically. A missing/blank date is never paused: with no day to
    place it, the habit reads as scheduled (the pre-#5007 behaviour).
    """
    since = paused_since(meta)
    return bool(since and isinstance(date_str, str) and date_str[:10] >= since)


def registry_entry_for(registry: Optional[Mapping[str, Any]], name: str) -> Optional[Mapping[str, Any]]:
    """The registry entry a Habitify display `name` answers to (its key, or a `habitify_names` alias)."""
    reg = registry or {}
    if isinstance(reg.get(name), Mapping):
        return reg[name]
    for meta in reg.values():
        if isinstance(meta, Mapping) and name in (meta.get("habitify_names") or []):
            return meta
    return None


def is_name_paused_on(registry: Optional[Mapping[str, Any]], name: str, date_str: Optional[str]) -> bool:
    return is_paused_on(registry_entry_for(registry, name), date_str)
