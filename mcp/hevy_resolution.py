"""hevy_resolution.py — turning an exercise TITLE into a Hevy template id (#3763).

Extracted from `mcp/tools_hevy_routine.py`, which sits on a shrink-only size ratchet
(#1665). This is a real seam rather than a place to put the overflow: title resolution is
one job with its own cost model, its own cache and its own failure mode, and the module
that authors routines should not have to carry it.

THE COST MODEL, MEASURED 2026-09-13

  20 exact Hevy titles                     0.01 s
   7 titles, 1 non-exact                   8.35 s   (that ONE title: 8.34 s)
  20 titles, 3 non-exact                  27.46 s   = the 30 s MCP soft timeout

The live Hevy catalogue is 828 templates = 9 pages at the write client's 1 req/s throttle.
Walking it used to happen once PER unresolved exercise, from page 1, and — worse — ahead of
the free in-memory curated match that would often have answered. Exercise COUNT never
mattered; the number of imprecise TITLES did. That is the whole origin of the "draft_custom
times out above ~7 exercises" note the owner designed around for months (#3771).

So: everything free first, the walk last and at most once per draft.
"""

from __future__ import annotations

import os
import re
from typing import Any


# The index was re-read from S3 once PER EXERCISE. `_load_json` is deliberately
# uncached (routine_generator.py:46 says so), and a 20-exercise draft therefore paid 20
# GETs of the same 98 KB object. Memoized for the container's life with a TTL: the index
# is rebuilt daily (#3764), so a warm container holding it for 15 minutes cannot serve a
# meaningfully stale answer, and the live-walk fallback still self-heals a true miss.
# ── shared helpers ───────────────────────────────────────────────────────────
def _normalize_title(t: str) -> str:
    """Normalize a title for index lookup: lowercase, collapse whitespace, strip."""

    return re.sub(r"\s+", " ", (t or "").strip().lower())


# #3763: the index was re-read from S3 once PER EXERCISE. `_load_json` is deliberately
# uncached (routine_generator.py:46 says so), and a 20-exercise draft therefore paid 20
# GETs of the same 98 KB object. Memoized for the container's life with a TTL: the index
# is rebuilt daily (#3764), so a warm container holding it for 15 minutes cannot serve a
# meaningfully stale answer, and the live-walk fallback still self-heals a true miss.
_INDEX_TTL_SECONDS = int(os.environ.get("HEVY_TEMPLATE_INDEX_TTL", "900"))
_index_cache: dict[str, Any] = {"at": 0.0, "templates": None}


_INDEX_TTL_SECONDS = int(os.environ.get("HEVY_TEMPLATE_INDEX_TTL", "900"))
_index_cache: dict[str, Any] = {"at": 0.0, "templates": None}


def _template_index(force: bool = False) -> dict[str, Any]:
    """Full Hevy template index (ADR-069): normalized_title -> {id, title}.

    Covers every built-in Hevy exercise plus the account's custom ones, so
    draft_custom can author any exercise by name without a curated catalog
    entry. Distinct from movement_catalog.json (the generator's curated pool).
    Returns {} if the index is absent — resolution then falls back to a live
    Hevy lookup.
    """
    import time as _time

    from training.routine_generator import _load_json

    if not force and _index_cache["templates"] is not None and (_time.time() - _index_cache["at"]) < _INDEX_TTL_SECONDS:
        return _index_cache["templates"]
    try:
        templates = (_load_json("hevy_template_index.json") or {}).get("templates", {})
    except Exception:
        templates = {}
    _index_cache["templates"] = templates
    _index_cache["at"] = _time.time()
    return templates


def _reset_index_cache_for_tests() -> None:
    _index_cache["templates"] = None
    _index_cache["at"] = 0.0


def _title_tokens(name: str) -> set[str]:
    """Word tokens of a title, punctuation dropped.

    "Squat (Barbell)" and "Squat Barbell" must tokenize the same way; splitting on
    whitespace alone leaves "(barbell)" and the subset test silently never matches.
    """
    import re as _re

    return {w for w in _re.findall(r"[a-z0-9]+", _normalize_title(name)) if len(w) > 1}


def _index_fuzzy(name: str) -> str | None:
    """Exact-or-nothing token-set match against the index — never a near guess.

    'Leg Curl (Machine)' is not a Hevy title; 'Seated Leg Curl (Machine)' is. Before
    #3763 that one-word gap cost a full 9-page walk of the live catalogue, and then
    resolved anyway from the curated loose match that had been sitting one step further
    down all along. This closes the gap without ever guessing: a candidate qualifies only
    when the query's tokens are a SUBSET of the title's, and only when exactly one
    candidate qualifies. Two candidates is ambiguity, and ambiguity returns None so the
    caller fails loudly with suggestions rather than pushing the wrong exercise.
    """
    tokens = _title_tokens(name)
    if not tokens:
        return None
    hits = []
    for norm, v in _template_index().items():
        if not v.get("id"):
            continue
        if tokens <= _title_tokens(norm):
            hits.append(str(v["id"]))
            if len(hits) > 1:
                return None
    return hits[0] if len(hits) == 1 else None


class _LiveWalk:
    """One pass over the live Hevy template list, shared by every title in a draft.

    The walk is the expensive half of resolution: 828 templates = 9 pages at the client's
    1 req/s throttle, ~8.4s. It used to run once PER unresolved exercise, from page 1, so
    three imprecise titles cost ~27s — at the MCP handler's 30s soft timeout. The pages
    are identical across titles within one draft, so they are fetched at most once.
    """

    def __init__(self, list_templates_fn=None):
        self._list = list_templates_fn
        self._by_title: dict[str, str] = {}
        self._walked = False

    def _ensure(self) -> None:
        if self._walked:
            return
        self._walked = True  # a failed walk is not retried per-title either
        lister = self._list
        if lister is None:
            from training import hevy_write_client as wc

            lister = wc.list_templates
        page = 1
        while page <= 30:
            try:
                resp = lister(page=page, page_size=100)
            except Exception:
                return
            items = resp.get("exercise_templates") or resp.get("templates") or []
            if not items:
                return
            for t in items:
                if t.get("id"):
                    self._by_title.setdefault(_normalize_title(t.get("title")), str(t["id"]))
            if len(items) < 100:
                return
            page += 1

    def id_for(self, name: str) -> str | None:
        self._ensure()
        return self._by_title.get(_normalize_title(name))


def _live_template_id_by_title(name: str) -> str | None:
    """Self-heal: search the live Hevy template list for an exact title match.

    Triggered only when the static index misses (e.g. a template created in
    Hevy after the index was last built). Exact normalized-title match only —
    never a fuzzy guess, to avoid silently pushing the wrong exercise.
    """
    from training import hevy_write_client as wc

    target = _normalize_title(name)
    page = 1
    while page <= 30:
        try:
            resp = wc.list_templates(page=page, page_size=100)
        except Exception:
            return None
        items = resp.get("exercise_templates") or resp.get("templates") or []
        if not items:
            return None
        for t in items:
            if _normalize_title(t.get("title")) == target and t.get("id"):
                return str(t["id"])
        if len(items) < 100:
            return None
        page += 1
    return None
