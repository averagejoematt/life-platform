"""scripts/recompute_character_verify.py — the combined recompute's final-state, event and responsiveness checks (#6224).

The owner's conditions before he is asked to approve (2026-11-27). Every check below runs in the dry run and either FAILS
the combined run or is reported as evidence; per-event and per-date detail stays in the PRIVATE manifest, the summary
carries counts.

  final state   the last ladder step equals ``planned_states`` on EVERY field, composite and events included (the
                private tool's supported reader); the public composite of every planned v3 block equals what
                ``/api/character`` itself serves for that block (the route's own code, on a stub table).
  events        reconstructed == added + moved (every ADDED and MOVED event marked, no KEPT one); no duplicate
                (who, type, level) in the final public set and no event both KEPT and ADDED; every event served before
                the containment switch has a disposition (KEPT, MOVED from → to, REMOVED with its eligibility reason).
  responds      with XP debt at 0 a poor measured day still moves the public projection (live counts: day-over-day
                drops of public pillar levels, raw scores and the composite after the recompute).
"""

from __future__ import annotations

import json
from typing import Any, Callable, Optional

STATE_FIELDS = ("character_level", "character_xp", "composite", "pillars", "events")
PUBLIC_PILLARS = ("sleep", "movement", "nutrition", "metabolic", "consistency")
COMPOSITE_RULE = (
    "/api/character: round(mean of raw_score over the pillars not flagged not_instrumented, 1) — computed by the route "
    "itself (web.site_api_character.character) on a stub table holding only the planned record"
)


# ── final state ───────────────────────────────────────────────────────────────────────────────────────────────────


def final_state_check(last_step: dict, planned_states: Optional[dict]) -> dict:
    """Last ladder step vs ``planned_states`` on every field of every date. ``planned_states`` None = the reader has not
    landed (reported PENDING; the final run fails on it)."""
    if planned_states is None:
        return {"status": "pending", "dates": len(last_step), "mismatches": [], "composite_verified": None}
    dates = sorted(set(last_step) | set(planned_states))
    mism = []
    for d in dates:
        a, b = last_step.get(d) or {}, planned_states.get(d) or {}
        for f in STATE_FIELDS:
            if a.get(f) != b.get(f):
                mism.append(f"{d} {f}")
    comp_bad = {m.split()[0] for m in mism if m.endswith(" composite")}
    return {"status": "checked", "dates": len(dates), "mismatches": mism, "composite_verified": len(dates) - len(comp_bad)}


def route_composite_of(record: dict) -> Optional[float]:
    """The composite ``/api/character`` serves for ``record`` (a sheet carrying its planned ``public`` block), from the
    route's own code: a stub table that returns only this record; scores served live (the post-switch state)."""
    from health import character_privacy as CP
    from web import site_api_vitals as vitals

    class _Only:
        def query(self, **_kw):
            return {"Items": [record]}

        def get_item(self, **_kw):
            return {}

    saved = (vitals.table, CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE)
    vitals.table, CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = _Only(), False
    try:
        body = json.loads(vitals.handle_character()["body"])
    finally:
        vitals.table, CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = saved
    return (body.get("character") or {}).get("composite_score")


def public_composite_check(records: dict, reported: dict, route: Callable[[dict], Optional[float]] = route_composite_of) -> dict:
    """{date: record with its planned public block} vs {date: the composite the recompute reports}: equal on every date."""
    mism = []
    for d in sorted(records):
        got = route(records[d])
        if got != reported.get(d):
            mism.append({"date": d, "route": got, "reported": reported.get(d)})
    return {"dates": len(records), "verified": len(records) - len(mism), "mismatches": mism, "rule": COMPOSITE_RULE}


# ── events ────────────────────────────────────────────────────────────────────────────────────────────────────────


def _key(e: dict) -> tuple:
    return (str(e.get("who")), str(e.get("type")), str(e.get("new")))


def reconcile_events(comparison: dict, marked: list, final_events: list, before_events: list) -> dict:
    """``comparison``: the event comparison (rows: KEPT / MOVED / REMOVED / ADDED); ``marked``: [(date, key, redated_from)]
    of every event the recomputed blocks carry as reconstructed; ``final_events`` / ``before_events``: the served event
    sets after / before. Returns the reconciliation and its failures."""
    rows = comparison.get("rows") or []
    added = {(r["date"], tuple(r["key"])) for r in rows if r["status"] == "ADDED"}
    moved = {(r["new_date"], tuple(r["key"])): r["date"] for r in rows if r["status"] == "MOVED"}
    kept = {(r["date"], tuple(r["key"])) for r in rows if r["status"] == "KEPT"}
    marks = {(d, tuple(k)): src for d, k, src in marked}
    fails = []
    if len(marks) != len(added) + len(moved):
        fails.append(f"reconstructed {len(marks)} != added {len(added)} + moved {len(moved)}")
    unmarked = sorted(added - set(marks)) + sorted(set(moved) - set(marks))
    if unmarked:
        fails.append(f"{len(unmarked)} ADDED/MOVED event(s) without the reconstructed marker")
    marked_kept = sorted(set(marks) & kept)
    if marked_kept:
        fails.append(f"{len(marked_kept)} KEPT event(s) carry the reconstructed marker")
    stray = sorted(set(marks) - added - set(moved))
    if stray:
        fails.append(f"{len(stray)} reconstructed event(s) neither ADDED nor MOVED")
    bad_src = sorted(k for k, src in moved.items() if marks.get(k) != src)
    if bad_src:
        fails.append(f"{len(bad_src)} MOVED event(s) whose redated_from is not their served date")
    seen: dict = {}
    for e in final_events:
        seen.setdefault(_key(e), []).append(e["date"])
    dups = {"|".join(k): v for k, v in seen.items() if len(v) > 1}
    both = sorted({k for _d, k in kept} & {k for _d, k in added})
    if dups:
        fails.append(f"{len(dups)} duplicate event(s) in the final public set")
    if both:
        fails.append(f"{len(both)} event(s) both KEPT and ADDED")
    disposition = {(r["date"], tuple(r["key"])): r for r in rows if r["status"] in ("KEPT", "MOVED", "REMOVED")}
    served = []
    for e in before_events:
        r = disposition.get((e["date"], _key(e)))
        if r is None or (r["status"] == "MOVED" and not r.get("new_date")) or (r["status"] == "REMOVED" and not r.get("reason")):
            served.append({"date": e["date"], "key": list(_key(e)), "disposition": None})
            continue
        served.append(
            {"date": e["date"], "key": list(_key(e)), "disposition": r["status"], "to": r.get("new_date"), "reason": r.get("reason")}
        )
    undisposed = [s for s in served if s["disposition"] is None]
    if undisposed:
        fails.append(f"{len(undisposed)} event(s) served before have no disposition")
    tally: dict = {}
    for s in served:
        label = s["disposition"] if s["disposition"] != "REMOVED" else f"REMOVED ({s['reason']})"
        tally[label] = tally.get(label, 0) + 1
    return {
        "equation": {"reconstructed": len(marks), "added": len(added), "moved": len(moved), "holds": len(marks) == len(added) + len(moved)},
        "marked_not_added": [{"date": d, "key": list(k), "redated_from": moved[(d, k)]} for d, k in sorted(set(marks) & set(moved))],
        "duplicates": dups,
        "kept_and_added": [list(k) for k in both],
        "served_before": {"count": len(served), "by_disposition": tally, "rows": served},
        "failures": fails,
    }


def marked_events(blocks: dict) -> list:
    """[(date, key, redated_from)] of every event a recomputed public block carries as reconstructed."""
    from health import character_privacy as CP

    out = []
    for d, block in sorted(blocks.items()):
        for ev in (block or {}).get("level_events") or []:
            if isinstance(ev, dict) and CP.is_reconstructed(ev):
                who = str(ev.get("pillar") or "character").lower()
                new = ev.get("new_tier") if "tier" in str(ev.get("type")) else ev.get("new_level")
                out.append((d, [who, ev.get("type"), _num_str(new)], ev.get("redated_from")))
    return out


def _num_str(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    return str(int(f)) if f == int(f) else str(round(f, 4))


# ── responds: what still moves on a poor measured day ────────────────────────────────────────────────────────────


def live_responsiveness(rows: list) -> dict:
    """From the public manifest's per-date rows (``[before, after]`` pairs): after the recompute, how many dates show a
    public pillar level, a public pillar raw score or the composite going DOWN day-over-day; and that XP never falls and
    XP debt is 0 (the ONLY thing the amendment removes is the debt carry-over)."""
    after = [
        (r["date"], {k: (v[1] if isinstance(v, list) and len(v) == 2 else None) for k, v in r.items()})
        for r in sorted(rows, key=lambda r: r["date"])
    ]
    out = {
        "dates": len(after),
        "level_down_dates": 0,
        "raw_down_dates": 0,
        "composite_down_dates": 0,
        "by_pillar": {},
        "xp_falls": 0,
        "xp_debt_nonzero": 0,
    }
    for p in PUBLIC_PILLARS:
        out["by_pillar"][p] = {"level_down": 0, "raw_down": 0}
    for (_d0, a), (_d1, b) in zip(after, after[1:]):
        lv = rw = False
        for p in PUBLIC_PILLARS:
            if _down(a.get(f"{p}_level"), b.get(f"{p}_level")):
                out["by_pillar"][p]["level_down"] += 1
                lv = True
            if _down(a.get(f"{p}_score"), b.get(f"{p}_score")):
                out["by_pillar"][p]["raw_down"] += 1
                rw = True
        out["level_down_dates"] += lv
        out["raw_down_dates"] += rw
        out["composite_down_dates"] += _down(a.get("composite"), b.get("composite"))
        out["xp_falls"] += _down(a.get("character_xp"), b.get("character_xp"))
    out["xp_debt_nonzero"] = sum(1 for _d, a in after if a.get("character_xp_debt") not in (None, 0, 0.0))
    return out


def _down(a: Any, b: Any) -> bool:
    return isinstance(a, (int, float)) and isinstance(b, (int, float)) and b < a - 1e-9


def responds(series: list) -> list:
    """What does NOT respond in a public chain ``series`` ([public block per day], a run of good days then sustained poor
    measured days): [] when everything the amendment keeps still moves. The detector the must-fail test exercises."""
    missing = []
    first_poor = next((i for i, b in enumerate(series) if b.get("_poor")), None)
    if first_poor is None or first_poor == 0:
        return ["no poor day in the series"]
    good, poor = series[first_poor - 1], series[first_poor:]
    if not ((poor[0].get("pillar_sleep") or {}).get("raw_score", 0) < (good.get("pillar_sleep") or {}).get("raw_score", 0)):
        missing.append("raw score")
    if not any((b.get("pillar_sleep") or {}).get("level", 0) < (good.get("pillar_sleep") or {}).get("level", 0) for b in poor):
        missing.append("pillar level")
    comp = [b.get("_composite") for b in series]
    if not any(isinstance(x, (int, float)) and x < comp[first_poor - 1] for x in comp[first_poor:]):
        missing.append("composite")
    cs = [(b.get("pillar_consistency") or {}).get("raw_score") for b in series]
    if len({c for c in cs[first_poor - 1 :] if c is not None}) < 2:
        missing.append("consistency")
    if any((b.get("character_xp_debt") or 0) != 0 for b in series):
        missing.append("debt is not retired")
    if any((b.get("character_xp") or 0) < (a.get("character_xp") or 0) for a, b in zip(series, series[1:])):
        missing.append("XP fell (debt carry-over not removed)")
    return missing


def manifest_checks(snap: dict, char: dict, c_rows: list, level_credit: dict) -> dict:
    """The public dry run's verification block (private manifest): reconciliation, public composite, responsiveness."""
    import backfill_public_variant as B
    import backfill_public_variant_events as EV

    dates = sorted(snap["sheets"])
    before_recs = [snap["sheets"][d] for d in dates]
    after_recs = [
        dict(snap["sheets"][d], **{B.PUBLIC: char[d]["public"]}) if (char.get(d) or {}).get("public") else snap["sheets"][d] for d in dates
    ]
    blocks = {d: char[d]["public"] for d in dates if (char.get(d) or {}).get("public")}
    rec = reconcile_events(
        level_credit["events"],
        marked_events(blocks),
        EV.served_events(after_recs, old_rule=False),
        EV.served_events(before_recs, old_rule=True),
    )
    rec["level_badges"], rec["level_milestones"] = level_credit.get("level_badges"), level_credit.get("level_milestones")
    records = {d: dict(snap["sheets"][d], **{B.PUBLIC: blocks[d]}) for d in blocks}
    reported = {r["date"]: (r.get("composite") or [None, None])[1] for r in c_rows}
    return {
        "reconciliation": rec,
        "public_composite": public_composite_check(records, {d: reported.get(d) for d in records}),
        "responsiveness": live_responsiveness(c_rows),
    }
