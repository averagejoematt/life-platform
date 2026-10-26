"""training/session_count.py — THE count of training sessions and their minutes (#5387).

WHY THIS EXISTS

A family of readers counted Strava activities directly (`len(activities)`, the day row's
`activity_count`, a sum of `moving_time_seconds`), outside the cross-source resolver. On a gym
day the Strava partition holds Hevy's own push of the WHOLE session (device `Hevy`, typed
WeightTraining, spanning lift + cardio block + mobility block) AND the wearable's record of the
cardio block inside it (before 2026-10-26 WHOOP's Ride/Walk, from then the watch's own upload).
The read seam folds only same-sport copies, so both survive and every such reader counted one
visit as two sessions (three when WHOOP also posted the treadmill block) and its minutes as
lift-span + ride. Owner ruling 2026-10-26: Hevy is the one routine source for a gym visit; every
watch, pliability, HealthKit and Strava copy is an echo that counts once.

THE RULE

  * PARTS are `training.workout_identity`'s identities — the ONE cross-source rule (Hevy's own
    Strava push dropped as an echo of the Hevy session in hand, a wearable's ride joined to the
    Hevy cycling block, WHOOP's lift pieces folded by the read seam). A gym visit is its parts:
    the lift, the ride, the mobility block, each labelled by what it was.
  * A VISIT (what every reader here calls a session or a workout) is the parts that belong to one
    occasion: parts of one Hevy session, or parts whose intervals overlap. One gym visit is one
    visit, whichever device uploaded the ride and whether or not the reader holds the Hevy rows
    (without them, Hevy's push is the lift part and the ride inside it overlaps it).
  * MINUTES are claimed once. A Hevy-anchored part counts the time Hevy logged for it (Hevy's own
    partition of its session: the cardio and mobility blocks' set time, the lift the rest), and
    claims the session's span. Every other part, tightest interval first, counts only the share
    of its interval nothing earlier claimed (walking_volume's #4068 pro-rata primitive,
    `uncovered_seconds`, the order `training.zone2_minutes` claims time in). So Hevy's push
    without the Hevy rows keeps only the minutes outside the ride it spans. A timed part left
    with no unclaimed time is an echo in time and is not a part.
    An untimed record cannot be placed and is its own visit.
  * ZONE 2 is never computed here: `zone2_by_date` / `zone2_total` read THE Zone 2 computation
    (`training.zone2_minutes`, #4627) — devices' own zones, minutes in zone, each session once.

A visit is dated by the Pacific date of its start (the site's day frame); an untimed one by the
day row it was stored under. Pure — no boto3, no I/O, no clock reads.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from common.pacific_time import pacific_date_of, parse_iso_utc

from training import workout_identity, zone2_minutes
from training.walking_volume import uncovered_seconds

SESSION_COUNT_VERSION = "session-count@1.0.0"

HEVY = "hevy"
STRAVA = "strava"

Rows = Optional[Iterable[dict[str, Any]]]


def _row_date(row: dict[str, Any]) -> str:
    return str(row.get("date") or str(row.get("sk") or "").replace("DATE#", ""))[:10]


def _live_hevy(hevy: Rows) -> list[dict[str, Any]]:
    """Hevy workout rows minus tombstones (a superseded legacy daily aggregate is the same
    sessions again, #4030 — training_load and the monthly digest drop it the same way). A row
    with no workout id of its own (no `workout_id`/`id`, no `#WORKOUT#` key) gets its row-and-
    position id on a copy, so two such rows stay two sessions (the resolver keys on vendor ids)."""
    out = []
    for i, r in enumerate(hevy or ()):
        if isinstance(r, dict) and not r.get("tombstone"):
            out.append(r if _hevy_id(r) else {**r, "workout_id": f"{_row_date(r)}:{i}"})
    return out


def _activities(rows: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    """(row date, activity) for every Strava activity in the (normalised) day rows."""
    return [(_row_date(row), a) for row in rows for a in row.get("activities") or () if isinstance(a, dict)]


#: Keys only a Strava DAY row carries (the writer's day totals): a dict holding one is never a bare activity.
_DAY_TOTAL_KEYS = ("activity_count", "total_moving_time_seconds", "total_distance_miles", "total_zone2_seconds", "total_kilojoules")
#: A day row with no activities stands in as one activity when it carries one of these of its own.
_STAND_IN_KEYS = ("sport_type", "type", "moving_time_seconds", "duration_minutes", "moving_time_minutes")


def _stand_in(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if k not in ("activities", "pk", "sk")}


def _normalise_strava(rows: Rows) -> list[dict[str, Any]]:
    """Strava day rows in the resolver's shape, copied (never the caller's dicts): a bare activity
    is wrapped in a day row; a day row with no activities but a sport or a duration of its own stands
    in as one activity (the shape `/api/training_overview` always read); an activity with no vendor id gets
    its row-and-position id (so two such activities stay two); a minutes-only duration
    (`duration_minutes` / `moving_time_minutes`) is carried as `moving_time_seconds`."""
    out: list[dict[str, Any]] = []
    for row in rows or ():
        if not isinstance(row, dict):
            continue
        nested = row.get("activities")
        is_day = "activities" in row or str(row.get("sk") or "").startswith("DATE#") or any(k in row for k in _DAY_TOTAL_KEYS)
        if not is_day:
            day = str(row.get("start_date_local") or row.get("start_date") or row.get("date") or "")[:10]
            row, nested = {"date": day, "activities": [row]}, [row]
        elif not nested and any(row.get(k) for k in _STAND_IN_KEYS):
            nested = [_stand_in(row)]
        day = _row_date(row)
        acts = []
        for i, a in enumerate(nested if isinstance(nested, list) else ()):
            if not isinstance(a, dict):
                continue
            a = dict(a)
            if not (a.get("strava_id") or a.get("id")):
                a["strava_id"] = f"{day}#{i}"
            minutes = a.get("duration_minutes") or a.get("moving_time_minutes")
            if not a.get("moving_time_seconds") and minutes:
                a["moving_time_seconds"] = float(minutes) * 60.0
            acts.append(a)
        out.append({**row, "activities": acts})
    return out


def _hevy_id(w: dict[str, Any]) -> str:
    """The Hevy workout id the resolver keys a session's members on (`workout_identity.hevy_members`)."""
    wid = w.get("workout_id") or w.get("id")
    sk = str(w.get("sk") or "")
    return str(wid) if wid else (sk.split("#WORKOUT#", 1)[1] if "#WORKOUT#" in sk else "")


def _sid(a: dict[str, Any]) -> str:
    return str(a.get("strava_id") or a.get("id") or "")


def _interval(part: dict[str, Any]) -> Optional[tuple[datetime, datetime]]:
    start, end = parse_iso_utc(part.get("start")), parse_iso_utc(part.get("end"))
    return (start, end) if start is not None and end is not None and end > start else None


def _hevy_sessions(ident: dict[str, Any]) -> set[str]:
    return {str(i).split("#", 1)[0] for i in (ident.get("members") or {}).get(HEVY, ())}


def _claim(idents: list[dict[str, Any]]) -> list[float]:
    """The seconds each identity counts once (see THE RULE: MINUTES), in `idents` order."""
    counted = [0.0] * len(idents)
    claimed: list[tuple[datetime, datetime]] = []
    hevy_first = [i for i, x in enumerate(idents) if x["seconds_source"] == HEVY]
    rest = sorted(
        (i for i, x in enumerate(idents) if x["seconds_source"] != HEVY),
        key=lambda i: (_interval(idents[i]) is None, _span(idents[i]), idents[i]["workout_identity"]),
    )
    for i in hevy_first:
        counted[i] = float(idents[i]["seconds"] or 0.0)
    claimed.extend(iv for i in hevy_first if (iv := _interval(idents[i])) is not None)
    for i in rest:
        iv = _interval(idents[i])
        secs = float(idents[i]["seconds"] or 0.0)
        if iv is None:
            counted[i] = secs
            continue
        counted[i] = secs * uncovered_seconds(iv[0], iv[1], claimed) / (iv[1] - iv[0]).total_seconds()
        claimed.append(iv)
    return counted


def _span(ident: dict[str, Any]) -> float:
    iv = _interval(ident)
    return (iv[1] - iv[0]).total_seconds() if iv else 0.0


def _groups(parts: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Parts of one occasion: one Hevy session, or overlapping intervals (union-find)."""
    parent = list(range(len(parts)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(parts):
        for j in range(i + 1, len(parts)):
            b = parts[j]
            same_hevy = bool(a["hevy_sessions"] & b["hevy_sessions"])
            ia, ib = a["_iv"], b["_iv"]
            overlap = ia is not None and ib is not None and min(ia[1], ib[1]) > max(ia[0], ib[0])
            if same_hevy or overlap:
                parent[find(i)] = find(j)
    by_root: dict[int, list[dict[str, Any]]] = {}
    for i, p in enumerate(parts):
        by_root.setdefault(find(i), []).append(p)
    return list(by_root.values())


def _sport(ident: dict[str, Any], acts: list[dict[str, Any]]) -> str:
    """Strava's word for the part when a Strava activity is in it (the longest); otherwise its
    family in Strava's vocabulary (`zone2_minutes.FAMILY_SPORT`, "Ride" / "Mobility")."""
    if acts:
        rep = max(acts, key=lambda a: float(a.get("moving_time_seconds") or a.get("elapsed_time_seconds") or 0))
        return str(rep.get("sport_type") or rep.get("type") or "Other")
    fam = str(ident.get("family") or "")
    return zone2_minutes.FAMILY_SPORT.get(fam) or (fam.removeprefix(workout_identity.OTHER_PREFIX).title() or "Other")


def visits(*, strava: Rows = None, hevy: Rows = None, whoop: Rows = None, apple: Rows = None) -> list[dict[str, Any]]:
    """Every visit once, oldest first: `{date, start, end, minutes, parts: [...], hevy_sessions}`.

    `strava` = Strava day rows (or bare activities), `hevy` = Hevy workout rows (the routine
    source; pass them wherever the reader holds them), `whoop` / `apple` = the resolver's other
    two sources, for a reader that already counts them. Each part carries its `family`, `sport`,
    counted `minutes`, the Strava `activities` it holds (seam-folded, echoes dropped) and its row
    `date`."""
    hevy_rows = _live_hevy(hevy)
    strava_rows = workout_identity.strava_without_echoes(_normalise_strava(strava), hevy_rows) if strava else []
    dated = _activities(strava_rows)
    by_sid = {_sid(a): (d, a) for d, a in dated if _sid(a)}
    hevy_date = {_hevy_id(r): _row_date(r) for r in hevy_rows}
    idents = workout_identity.resolve_workout_identities(strava=strava_rows, hevy=hevy_rows, whoop=whoop, apple=apple)
    counted = _claim(idents)
    parts: list[dict[str, Any]] = []
    for ident, secs in zip(idents, counted):
        iv = _interval(ident)
        if iv is not None and secs <= 0 and ident["seconds"]:
            continue  # every minute of it already claimed: an echo in time, not a part
        members = ident.get("members") or {}
        acts = [by_sid[s][1] for s in members.get(STRAVA, ()) if s in by_sid]
        row_dates = [by_sid[s][0] for s in members.get(STRAVA, ()) if s in by_sid]
        row_dates += [hevy_date[h] for h in _hevy_sessions(ident) if hevy_date.get(h)]
        parts.append(
            {
                "workout_identity": ident["workout_identity"],
                "family": ident["family"],
                "sport": _sport(ident, acts),
                "start": ident["start"],
                "end": ident["end"],
                "seconds": secs,
                "minutes": round(secs / 60.0, 1),
                "seconds_source": ident["seconds_source"],
                "sources": list(ident["sources"]),
                "strava_ids": [s for s in members.get(STRAVA, ())],
                "activities": acts,
                "hevy_sessions": _hevy_sessions(ident),
                "date": (pacific_date_of(ident["start"]) if ident["start"] else None) or (min(row_dates) if row_dates else None),
                "_iv": iv,
            }
        )
    out = []
    for group in _groups(parts):
        timed = [p["_iv"] for p in group if p["_iv"] is not None]
        first = min(group, key=lambda p: (p["_iv"] is None, p["_iv"][0] if p["_iv"] else datetime.max, p["workout_identity"]))
        seconds = sum(p["seconds"] for p in group)
        for p in group:
            p.pop("_iv", None)
        out.append(
            {
                "date": first["date"],
                "start": min(t[0] for t in timed).isoformat() if timed else None,
                "end": max(t[1] for t in timed).isoformat() if timed else None,
                "seconds": seconds,
                "minutes": round(seconds / 60.0, 1),
                "parts": sorted(group, key=lambda p: (p["start"] or "~", p["workout_identity"])),
                "hevy_sessions": sorted(set().union(*(p["hevy_sessions"] for p in group))),
            }
        )
    out.sort(key=lambda v: (v["date"] or "~", v["start"] or "~"))
    return out


def in_window(
    visit_list: Iterable[dict[str, Any]], start_date: Optional[str] = None, end_date: Optional[str] = None
) -> list[dict[str, Any]]:
    """The visits dated inside [start_date, end_date] (either bound optional); an undated visit is kept
    only when no bound is given."""
    out = []
    for v in visit_list:
        d = v.get("date")
        if (start_date or end_date) and not d:
            continue
        if start_date and d < start_date[:10]:
            continue
        if end_date and d > end_date[:10]:
            continue
        out.append(v)
    return out


def totals(visit_list: Iterable[dict[str, Any]], start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict[str, Any]:
    """`{sessions, parts, minutes, by_family, by_sport, by_date}` over the visits in the window — a
    visit counted once, its parts each once, its minutes once."""
    vs = in_window(visit_list, start_date, end_date)
    by_family: dict[str, dict[str, float]] = {}
    by_sport: dict[str, dict[str, float]] = {}
    by_date: dict[str, dict[str, float]] = {}
    for v in vs:
        day = by_date.setdefault(str(v.get("date") or ""), {"sessions": 0, "parts": 0, "minutes": 0.0})
        day["sessions"] += 1
        for p in v["parts"]:
            day["parts"] += 1
            day["minutes"] += p["seconds"] / 60.0
            for key, bucket in ((p["family"], by_family), (p["sport"], by_sport)):
                b = bucket.setdefault(str(key), {"parts": 0, "minutes": 0.0})
                b["parts"] += 1
                b["minutes"] += p["seconds"] / 60.0

    def _rounded(d: dict[str, dict[str, float]]) -> dict[str, dict[str, Any]]:
        return {k: {f: (round(x, 1) if isinstance(x, float) else int(x)) for f, x in v.items()} for k, v in sorted(d.items())}

    return {
        "sessions": len(vs),
        "parts": sum(len(v["parts"]) for v in vs),
        "minutes": round(sum(v["seconds"] for v in vs) / 60.0, 1),
        "by_family": _rounded(by_family),
        "by_sport": _rounded(by_sport),
        "by_date": _rounded(by_date),
        "version": SESSION_COUNT_VERSION,
    }


def count(
    *,
    strava: Rows = None,
    hevy: Rows = None,
    whoop: Rows = None,
    apple: Rows = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> dict[str, Any]:
    """`totals(visits(...), start_date, end_date)` — the one call a counting reader makes."""
    return totals(visits(strava=strava, hevy=hevy, whoop=whoop, apple=apple), start_date, end_date)


def activities(visit_list: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """The Strava activities the visits hold (seam-folded, Hevy's echoes dropped), each once —
    for a reader that lists activities (distance, a sport's walks) rather than counting them."""
    return [a for v in visit_list for p in v["parts"] for a in p["activities"]]


# ── Zone 2: THE computation (#4627), read through ──────────────────────────────────────


def zone2_by_date(strava: Rows = None, *, hevy: Rows = None, whoop: Rows = None, apple: Rows = None) -> dict[str, float]:
    """`{date: Zone 2 minutes}` from `training.zone2_minutes.counted_sessions` — each session once,
    the zones of the source that measured the most of it; a date appears only when a session on it
    was measured (an unzoned day is absent, never a measured 0)."""
    out: dict[str, float] = {}
    rows = list(strava or ())
    for s in zone2_minutes.counted_sessions(rows, list(whoop or ()), list(apple or ()) or None, hevy_rows=_live_hevy(hevy) or None):
        if s.get("source"):
            out[s["date"]] = out.get(s["date"], 0.0) + float(s["zone_2_minutes"] or 0.0)
    return {d: round(v, 1) for d, v in sorted(out.items())}


def zone2_total(
    strava: Rows = None,
    *,
    hevy: Rows = None,
    whoop: Rows = None,
    apple: Rows = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> float:
    """Zone 2 minutes over [start_date, end_date] (either bound optional) — `zone2_by_date` summed."""
    by = zone2_by_date(strava, hevy=hevy, whoop=whoop, apple=apple)
    return round(sum(v for d, v in by.items() if (not start_date or d >= start_date[:10]) and (not end_date or d <= end_date[:10])), 1)


def day_table(*, strava: Rows = None, hevy: Rows = None, whoop: Rows = None, apple: Rows = None) -> dict[str, dict[str, Any]]:
    """`{date: {sessions, parts, minutes, zone2_minutes}}` for a per-day reader: THE count's `by_date`
    beside THE Zone 2 (`zone2_by_date`; `None` on a day no session measured). Empty without Strava rows
    and Hevy rows."""
    if not strava and not hevy:
        return {}
    by = count(strava=strava, hevy=hevy, whoop=whoop, apple=apple)["by_date"]
    z2 = zone2_by_date(strava, hevy=hevy, whoop=whoop, apple=apple) if strava else {}
    return {d: {**by.get(d, {"sessions": 0, "parts": 0, "minutes": 0.0}), "zone2_minutes": z2.get(d)} for d in sorted(set(by) | set(z2))}
