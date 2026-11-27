"""scripts/backfill_public_variant_events.py — the recompute's EVENT COMPARISON (#6224, owner decision 2026-11-26).

"Preserve unrelated valid activity and achievement events. Recalculate level-dependent unlocks according to the
corrected historical scores. Move milestones to their correct dates where necessary. Do not erase legitimate history
merely because a day's character sheet was recomputed. Do not retain achievements that no longer satisfy their actual
eligibility rules. Do not invent replacement events."

Pure functions over two record lists (each a stored ``character_sheet`` item, oldest first):

  * ``before`` — the records as stored, served by the rule the public routes applied before the containment switch
    (``character_privacy.public_event_sheets`` with the 2026-11-06 rule for every variant — the pre-#6224-events code);
  * ``after``  — the same items with the recomputed ``public`` block, served by the corrected-chain rule.

Every event served BEFORE is classified KEPT (same event, same date) / MOVED (same event, another date) / REMOVED (with
its reason: a Mind event, or the corrected chain does not reach it). Every event served AFTER and not matched is ADDED,
with the per-date values that prove the corrected chain crosses it there. Level badges and the level milestone ladder
are compared by first-crossing date. ``verbatim_losses`` lists every public-input pillar event (sleep, movement,
nutrition, metabolic) served before and not KEPT — it must be empty.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator, Optional

from health import character_privacy as CP

VERBATIM = ("sleep", "movement", "nutrition", "metabolic")


@contextmanager
def _serving(old_rule: bool, keep_mind: bool) -> Iterator[None]:
    """The scores live (the state the comparison describes); ``old_rule``: the 2026-11-06 event rule for every variant
    (the code before this change); ``keep_mind``: Mind's stored events not scrubbed (so a removed one is named)."""
    saved = (CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE, CP.is_corrected_chain, CP.scrub_unscored, CP.older_method)
    CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = False
    if old_rule:
        CP.is_corrected_chain = lambda _v: False  # type: ignore[assignment]
        CP.older_method = lambda _v: False  # type: ignore[assignment]  # the code before #6224's per-block rule
    if keep_mind:
        CP.scrub_unscored = lambda view: view  # type: ignore[assignment]
    try:
        yield
    finally:
        CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE, CP.is_corrected_chain, CP.scrub_unscored, CP.older_method = saved


def _norm(v: Any) -> Any:
    """A level as one value whatever its stored type (Decimal, float or int): 40, 40.0 and Decimal("40") are one level."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return int(f) if f == int(f) else round(f, 4)


def _day(view: dict) -> str:
    return str(view.get("date") or str(view.get("sk", "")).replace("DATE#", ""))[:10]


def served_events(records: list, *, old_rule: bool) -> list[dict]:
    """Every level event the public routes serve from ``records``, flattened: {date, who, type, old, new, key}."""
    with _serving(old_rule=old_rule, keep_mind=old_rule):
        views = CP.public_event_sheets(records, internal=True)  # the historical record, provenance included
    out = []
    for v in views:
        for ev in v.get("level_events") or []:
            if not isinstance(ev, dict):
                continue
            who = str(ev.get("pillar") or "character").lower()
            new = ev.get("new_tier") if "tier" in str(ev.get("type")) else ev.get("new_level")
            old = ev.get("old_tier") if "tier" in str(ev.get("type")) else ev.get("old_level")
            old, new = _norm(old), _norm(new)
            row = {"date": _day(v), "who": who, "type": ev.get("type"), "old": old, "new": new, "key": [who, ev.get("type"), str(new)]}
            row.update({k: ev[k] for k in CP.PROVENANCE_KEYS if k in ev})
            out.append(row)
    return out


def per_date_values(records: list) -> dict[str, dict[str, Any]]:
    """{date: {who: level}} from the corrected public views (the manifest's per-date values the events must follow)."""
    with _serving(old_rule=False, keep_mind=False):
        views = CP.public_sheets(records, pending=False)
    out: dict[str, dict[str, Any]] = {}
    for v in views:
        row: dict[str, Any] = {"character": _norm(v.get("character_level")), "character_tier": v.get("character_tier")}
        for k, p in v.items():
            if str(k).startswith("pillar_") and isinstance(p, dict) and p.get("level") is not None:
                row[str(k)[len("pillar_") :]] = _norm(p.get("level"))
                row[str(k)[len("pillar_") :] + "_tier"] = p.get("tier")
        out[_day(v)] = row
    return out


def _proof(values: dict, date: str, who: str) -> dict:
    days = sorted(values)
    i = days.index(date) if date in days else -1
    prev = values[days[i - 1]] if i > 0 else {}
    return {
        "previous_day": days[i - 1] if i > 0 else None,
        "level_before": prev.get(who),
        "level_on_date": (values.get(date) or {}).get(who),
    }


def compare(before: list[dict], after: list[dict], values: dict) -> dict:
    """The classification (module docstring). Totals by kind: "character" or the pillar name."""
    pool = [dict(e) for e in after]
    used: set = set()
    rows = []

    def take(pred) -> Optional[int]:
        for i, e in enumerate(pool):
            if i not in used and pred(e):
                used.add(i)
                return i
        return None

    for e in before:
        i = take(lambda a: a["key"] == e["key"] and a["date"] == e["date"])
        if i is not None:
            rows.append(dict(e, status="KEPT"))
            continue
        i = take(lambda a: a["key"] == e["key"])
        if i is not None:
            rows.append(dict(e, status="MOVED", new_date=pool[i]["date"]))
            continue
        reason = "a Mind event (Mind is not scored in public)" if e["who"] == "mind" else "the corrected chain does not reach it"
        rows.append(dict(e, status="REMOVED", reason=reason, corrected_values=_proof(values, e["date"], e["who"])))
    for i, a in enumerate(pool):
        if i not in used:
            rows.append(dict(a, status="ADDED", corrected_values=_proof(values, a["date"], a["who"])))
    totals: dict[str, dict[str, int]] = {}
    for r in rows:
        totals.setdefault(r["who"], {"KEPT": 0, "MOVED": 0, "REMOVED": 0, "ADDED": 0})[r["status"]] += 1
    return {"rows": rows, "totals": totals}


def verbatim_losses(comparison: dict) -> list[dict]:
    """Every public-input pillar event served before and not KEPT on its date — must be empty."""
    return [r for r in comparison["rows"] if r["who"] in VERBATIM and r["status"] in ("MOVED", "REMOVED")]


def stored_verbatim_mismatches(before_records: list, after_records: list) -> list[dict]:
    """Per date, the public-input pillars' STORED events (served or not) in the old block vs the recomputed one: the
    pillars' values are verbatim, so their events must be identical on every date."""
    out = []
    for b, a in zip(before_records, after_records):
        bb, ab = (b.get(CP.PUBLIC_KEY) or {}), (a.get(CP.PUBLIC_KEY) or {})

        def evs(block: dict) -> list:
            return sorted(
                [str(ev.get("pillar")), str(ev.get("type")), str(_norm(ev.get("new_level"))), str(ev.get("new_tier"))]
                for ev in (block.get("level_events") or []) + (block.get("recalculated_level_events") or [])
                if isinstance(ev, dict) and str(ev.get("pillar")) in VERBATIM
            )

        if evs(bb) != evs(ab):
            out.append({"date": _day(b), "before": evs(bb), "after": evs(ab)})
    return out


def level_crossings(before_records: list, after_records: list, rungs: list[int]) -> dict:
    """First date each level rung is credited (badges, the level milestone ladder), before (the old rule) → after."""
    with _serving(old_rule=True, keep_mind=False):
        sb = CP.event_level_series(before_records)
    with _serving(old_rule=False, keep_mind=False):
        sa = CP.event_level_series(after_records)

    def first(s: list, n: int) -> Optional[str]:
        return next((d for d, lv in s if lv >= n), None)

    out = {}
    for n in sorted(set(rungs)):
        pair = [first(sb, n), first(sa, n)]
        status = "KEPT" if pair[0] == pair[1] else "MOVED" if pair[0] and pair[1] else "REMOVED" if pair[0] else "ADDED"
        out[str(n)] = {"before": pair[0], "after": pair[1], "status": status}
    return out


def event_comparison(before_records: list, after_records: list, badge_rungs: dict, milestone_rungs: list[int]) -> dict:
    """The whole EVENT COMPARISON section of the manifest."""
    before = served_events(before_records, old_rule=True)
    after = served_events(after_records, old_rule=False)
    comp = compare(before, after, per_date_values(after_records))
    crossings = level_crossings(before_records, after_records, list(badge_rungs.values()) + list(milestone_rungs))
    return {
        "events": comp,
        "verbatim_losses": verbatim_losses(comp),
        "stored_verbatim_mismatches": stored_verbatim_mismatches(before_records, after_records),
        "level_badges": {bid: crossings[str(n)] for bid, n in badge_rungs.items()},
        "level_milestones": {f"level_{n}": crossings[str(n)] for n in milestone_rungs},
    }


def annotate_provenance(after_blocks: dict, stored: dict, comparison: dict, reconstructed_at: str, method_version: str) -> int:
    """Write the INTERNAL provenance onto the recomputed public blocks (``after_blocks``: {date: block}, in place) — owner
    ruling 2026-11-26 23:50Z: every ADDED and MOVED event is ``event_provenance: "reconstructed"`` with
    ``reconstructed_at`` and ``reconstructed_method`` (and ``redated_from`` when moved); a KEPT event carries none.

    Idempotent: when the STORED block (``stored``: {date: stored item}) is already a corrected-chain variant holding the
    same event, its provenance is copied exactly (present or absent) — so a dry run after an apply plans no write and a
    second run never re-stamps an event. Returns the number of events marked reconstructed."""
    status: dict = {}
    for r in comparison["rows"]:
        if r["status"] == "ADDED":
            status[(r["date"], tuple(r["key"]))] = None
        elif r["status"] == "MOVED":
            status[(r["new_date"], tuple(r["key"]))] = r["date"]
    marked = 0
    for d, block in after_blocks.items():
        old = (stored.get(d) or {}).get(CP.PUBLIC_KEY) or {}
        old_list = list(old.get("level_events") or []) + list(old.get("recalculated_level_events") or [])
        old_events = {_event_key(e): e for e in old_list if isinstance(e, dict)}
        for ev in (block or {}).get("level_events") or []:
            if not isinstance(ev, dict):
                continue
            key = _event_key(ev)
            for k in CP.PROVENANCE_KEYS:
                ev.pop(k, None)
            if CP.is_corrected_chain(old) and key in old_events:
                ev.update({k: old_events[key][k] for k in CP.PROVENANCE_KEYS if k in old_events[key]})
            elif (d, key) in status:
                ev.update(
                    {"event_provenance": CP.RECONSTRUCTED, "reconstructed_at": reconstructed_at, "reconstructed_method": method_version}
                )
                if status[(d, key)]:
                    ev["redated_from"] = status[(d, key)]
            marked += 1 if CP.is_reconstructed(ev) else 0
    return marked


def _event_key(ev: dict) -> tuple:
    who = str(ev.get("pillar") or "character").lower()
    new = ev.get("new_tier") if "tier" in str(ev.get("type")) else ev.get("new_level")
    return (who, ev.get("type"), str(_norm(new)))
