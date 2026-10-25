"""workout_identity.py — ONE workout identity across Apple Health, Strava and Hevy (#4973).

WHY THIS EXISTS

One session can reach the platform up to three times: Hevy logs the lift or the treadmill block,
the wrist (WHOOP, Garmin, and once the watch is configured the Apple Watch) posts the same minutes
to Strava, and HealthKit records the watch's own workout ("Traditional Strength Training",
"Walking") which Health Auto Export forwards. Summed per source, the session is three sessions.
This module is the read-side resolver that says which records are ONE workout, so totals count
each identity once (the "capture all, interpret later" rule: every writer keeps its own record,
the combining lives here).

THE RULE

Two records from DIFFERENT sources are one workout when they are the same activity FAMILY and
their intervals overlap by at least half of the SHORTER interval (`OVERLAP_SHARE`). Identity is by
vendor id, never display name: a record seen twice from one source (the same `strava_id`, Apple
`id` or Hevy workout id) is one member, and two records from one source are never folded into one
identity — a source's own two records are two sessions, or that source's de-dup problem
(`common.strava_read_seam` owns Strava's multi-device one).

Families reuse the walking-volume layer's vocabulary (`training.walking_volume` STRAVA_COUNTED_TYPES
and HEVY_COUNTED_NAMES), so "walking" here is the walking that layer counts. A Hevy session yields
one member per counted cardio block (timed by the session, since a block carries a duration but no
clock) plus one `strength` member when it carries any other exercise.

COUNTED ONCE

An identity's duration is ONE member's, by source precedence — the logged Hevy block, else
Strava's moving time, else Apple's duration (the order `resolve_workout_identities` builds members in) — the same order the walking-volume layer's #4068 de-dup
claims time in. `identity_totals` sums identities, never members.

WHAT STAYS OWNER-ONLY

Apple's `route`, Strava's polyline and `location_*`, any lat/lon/GPS field and every free-text label
(an activity name can carry a place) ride in the identity's `owner_only` block. `public_projection`
drops that block and strips any `OWNER_ONLY_KEYS` key at any depth; tests/test_workout_identity_4973.py
pins it.

THE STORED APPLE RECORD

Since #4973's capture lane every Apple workout of every type is stored on the apple_health day row
as `apple_workouts` (one summary per HAE workout id — `ingestion.health_auto_export_workouts`);
`apple_members` takes those day rows directly. The rows are keyed by the UTC day of the workout's
start, so a reader resolving a Pacific day passes the neighbouring row too — a vendor id seen on
both is one member. A workout another app wrote into HealthKit (WHOOP, Hevy) is the source
`apple_health/<origin>`, distinct from the watch's own `apple_health`, so it can fold into the
watch's identity instead of standing beside it.

Pure functions only — no AWS. Wired into no live reader yet: walking_volume's #4068 de-dup is a
different, ruled rule (a partly-overlapping Strava walk keeps its UNcovered seconds), so it is
cross-checked against this resolver in tests rather than routed through it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any, Iterable, Optional

from common.pacific_time import parse_iso_utc

from training.walking_volume import HEVY_COUNTED_NAMES, STRAVA_COUNTED_TYPES

WORKOUT_IDENTITY_VERSION = "workout-identity@1.0.0"

OVERLAP_SHARE = 0.5

# Strava `sport_type`/`type` (lower-cased) → family, beyond walking_volume's counted set.
_STRAVA_EXTRA: dict[str, str] = {
    "run": "running",
    "trailrun": "running",
    "virtualrun": "running",
    "weighttraining": "strength",
    "workout": "strength",  # a Hevy session mirrored into Strava arrives as Workout/WeightTraining (#3930)
    "crossfit": "strength",
}
STRAVA_FAMILY: dict[str, str] = {**STRAVA_COUNTED_TYPES, **_STRAVA_EXTRA}

# HealthKit workout names as Health Auto Export sends them (lower-cased) → family.
APPLE_FAMILY: dict[str, str] = {
    "walking": "walking",
    "outdoor walk": "walking",
    "indoor walk": "walking",
    "hiking": "walking",
    "running": "running",
    "outdoor run": "running",
    "indoor run": "running",
    "cycling": "cycling",
    "outdoor cycle": "cycling",
    "indoor cycle": "cycling",
    "outdoor cycling": "cycling",  # the name HAE sends for a watch ride (live raw archive, 2026-10-21)
    "indoor cycling": "cycling",
    "traditional strength training": "strength",
    "functional strength training": "strength",
    "strength training": "strength",
}

# Never on a public projection, at any depth.
OWNER_ONLY_KEYS = frozenset(
    {
        "route",
        "routes",
        "map",
        "polyline",
        "summary_polyline",
        "start_latlng",
        "end_latlng",
        "latlng",
        "lat",
        "lon",
        "lng",
        "latitude",
        "longitude",
        "gps",
        "location",
        "location_city",
        "location_state",
        "location_country",
        "timezone",
        "label",
        "labels",
        "name",
    }
)


def _parse(v: Any) -> Optional[datetime]:
    """A UTC instant from Strava `start_date`, Hevy `start_time` or HAE's 'YYYY-MM-DD HH:MM:SS -0700'."""
    if not isinstance(v, str) or not v.strip():
        return None
    got = parse_iso_utc(v)
    if got is not None:
        return got
    try:
        return datetime.strptime(v.strip(), "%Y-%m-%d %H:%M:%S %z")
    except ValueError:
        return None


def _float(v: Any) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _owner_only(rec: dict[str, Any]) -> dict[str, Any]:
    return {k: rec[k] for k in rec if k in OWNER_ONLY_KEYS and rec[k] not in (None, "", [], {})}


def _hevy_family(name: str) -> Optional[str]:
    nl = (name or "").strip().lower()
    for key, family in HEVY_COUNTED_NAMES:
        if key in nl:
            return family
    return None


# ── members: one normalised record per (source, vendor id, family) ───────────────────


_APPLE_DEVICE_TOKENS = ("apple watch", "iphone", "ipad")


def _apple_source(w: dict[str, Any]) -> str:
    """`apple_health` for a workout the watch/phone recorded (or one with no origin on record);
    `apple_health/<origin>` for one another app wrote INTO HealthKit (a WHOOP or Hevy workout
    HAE re-exports) — so the two are distinct sources the resolver may fold into one identity,
    never two records of one source that it must keep apart."""
    src = w.get("source")
    name = str((src.get("name") if isinstance(src, dict) else src) or "").replace("\xa0", " ").strip().lower()
    if not name or any(tok in name for tok in _APPLE_DEVICE_TOKENS):
        return "apple_health"
    return "apple_health/" + "".join(ch if ch.isalnum() else "_" for ch in name).strip("_")


def _apple_records(items: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Bare workout records, or apple_health DATE# day rows whose `apple_workouts` map
    (health_auto_export_workouts.py, #4973) holds one summary per HAE workout id."""
    out: list[dict[str, Any]] = []
    for item in items or ():
        nested = item.get("apple_workouts")
        if isinstance(nested, dict):
            out.extend(v for v in nested.values() if isinstance(v, dict))
        else:
            out.append(item)
    return out


def apple_members(workouts: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Apple workouts: HAE's `process_workouts` records ({id, name, start, end, duration_min, route?…}),
    the stored `apple_workouts` summaries (vendor `duration` in seconds), or day rows carrying them."""
    out = []
    for w in _apple_records(workouts):
        name = str(w.get("name") or "")
        start, end = _parse(w.get("start")), _parse(w.get("end"))
        seconds = _float(w.get("duration_min")) * 60.0 or _float(w.get("duration"))
        if start is not None and end is None and seconds > 0:
            end = start + timedelta(seconds=seconds)
        if not seconds and start is not None and end is not None:
            seconds = (end - start).total_seconds()
        out.append(
            {
                "source": _apple_source(w),
                "id": str(w.get("id") or ""),
                "family": APPLE_FAMILY.get(name.strip().lower(), "other:" + name.strip().lower()),
                "start": start,
                "end": end,
                "seconds": seconds,
                "owner_only": _owner_only(w),
            }
        )
    return out


def strava_members(items: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Strava activities — a DATE# day item carrying `activities`, or bare stored activities."""
    out = []
    for item in items or ():
        nested = item.get("activities")
        acts: list[dict[str, Any]] = nested if isinstance(nested, list) else [item]
        for a in acts:
            t = str(a.get("sport_type") or a.get("type") or "").strip().lower()
            start = _parse(a.get("start_date"))
            elapsed = _float(a.get("elapsed_time_seconds") or a.get("elapsed_time"))
            out.append(
                {
                    "source": "strava",
                    "id": str(a.get("strava_id") or a.get("id") or ""),
                    "family": STRAVA_FAMILY.get(t, "other:" + t),
                    "start": start,
                    "end": start + timedelta(seconds=elapsed) if start is not None and elapsed > 0 else None,
                    "seconds": _float(a.get("moving_time_seconds") or a.get("moving_time")) or elapsed,
                    "owner_only": _owner_only(a),
                }
            )
    return out


def _hevy_id(w: dict[str, Any]) -> str:
    wid = w.get("workout_id") or w.get("id")
    if wid:
        return str(wid)
    sk = str(w.get("sk") or "")
    return sk.split("#WORKOUT#", 1)[1] if "#WORKOUT#" in sk else ""


def hevy_members(workouts: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Hevy sessions (`DATE#d#WORKOUT#<id>` sub-items): one member per counted cardio family, timed
    by the session, plus one `strength` member for the session's other exercises."""
    out = []
    for w in workouts or ():
        wid = _hevy_id(w)
        start, end = _parse(w.get("start_time")), _parse(w.get("end_time"))
        elapsed = (end - start).total_seconds() if start is not None and end is not None and end > start else 0.0
        cardio: dict[str, float] = {}
        has_other = False
        for ex in w.get("exercises") or ():
            name = str(ex.get("name") or ex.get("exercise_name") or "")
            fam = _hevy_family(name)
            secs = sum(_float(s.get("duration_sec") or s.get("duration_seconds")) for s in ex.get("sets") or ())
            if fam and secs:
                cardio[fam] = cardio.get(fam, 0.0) + secs
            elif ex.get("sets"):
                has_other = True
        owner = _owner_only(w)
        for fam, secs in cardio.items():
            out.append(
                {"source": "hevy", "id": f"{wid}#{fam}", "family": fam, "start": start, "end": end, "seconds": secs, "owner_only": owner}
            )
        if has_other:
            secs = max(0.0, elapsed - sum(cardio.values()))
            out.append(
                {
                    "source": "hevy",
                    "id": f"{wid}#strength",
                    "family": "strength",
                    "start": start,
                    "end": end,
                    "seconds": secs,
                    "owner_only": owner,
                }
            )
    return out


# ── clustering ───────────────────────────────────────────────────────────────────────


def _overlap_share(a: dict[str, Any], b: dict[str, Any]) -> float:
    """Overlap of two timed members as a share of the SHORTER interval (0 when either is untimed)."""
    if None in (a["start"], a["end"], b["start"], b["end"]):
        return 0.0
    inter = (min(a["end"], b["end"]) - max(a["start"], b["start"])).total_seconds()
    shorter = min((a["end"] - a["start"]).total_seconds(), (b["end"] - b["start"]).total_seconds())
    return inter / shorter if inter > 0 and shorter > 0 else 0.0


def _identity_id(members: list[dict[str, Any]]) -> str:
    key = "|".join(sorted(f"{m['source']}:{m['id']}" for m in members))
    return "wid_" + hashlib.sha256(key.encode()).hexdigest()[:12]


def _identity(members: list[dict[str, Any]]) -> dict[str, Any]:
    by_rank = sorted(members, key=lambda m: m["rank"])
    counted = by_rank[0]
    timed = [m for m in members if m["start"] is not None and m["end"] is not None]
    ids: dict[str, list[str]] = {}
    for m in by_rank:
        ids.setdefault(m["source"], []).append(m["id"])
    return {
        "workout_identity": _identity_id(members),
        "family": counted["family"],
        "start": min(m["start"] for m in timed).isoformat() if timed else None,
        "end": max(m["end"] for m in timed).isoformat() if timed else None,
        "seconds": counted["seconds"],
        "seconds_source": counted["source"],
        "sources": list(ids),
        "members": ids,
        "untimed": not timed,
        "owner_only": {f"{m['source']}:{m['id']}": m["owner_only"] for m in members if m["owner_only"]},
    }


def resolve_workout_identities(
    *,
    apple: Iterable[dict[str, Any]] | None = None,
    strava: Iterable[dict[str, Any]] | None = None,
    hevy: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Cluster the three sources' workout records into identities, oldest first.

    Members are placed in precedence order (Hevy, then Strava, then Apple — so a logged block
    anchors its identity and supplies its duration), each joining the identity of its family it
    overlaps most — at least OVERLAP_SHARE of the shorter interval against some member — that does
    not already hold a record from its source. An untimed record cannot be placed in time and is
    its own identity (`untimed: true`)."""
    seen: set[tuple[str, str]] = set()
    members: list[dict[str, Any]] = []
    for rank, (build, records) in enumerate(((hevy_members, hevy), (strava_members, strava), (apple_members, apple))):
        for m in build(records):
            key = (m["source"], m["id"])
            if m["id"] and key in seen:
                continue  # the same vendor record seen twice is one member
            seen.add(key)
            members.append({**m, "rank": rank})

    clusters: list[list[dict[str, Any]]] = []
    for m in members:
        best, best_share = None, 0.0
        for c in clusters:
            if c[0]["family"] != m["family"] or any(x["source"] == m["source"] for x in c):
                continue
            share = max(_overlap_share(m, x) for x in c)
            if share >= OVERLAP_SHARE and share > best_share:
                best, best_share = c, share
        if best is None:
            clusters.append([m])
        else:
            best.append(m)
    out = [_identity(c) for c in clusters]
    return sorted(out, key=lambda i: (i["start"] or "~", i["workout_identity"]))


def identity_totals(identities: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Sessions and minutes with every identity counted ONCE, overall and per family."""
    total_s, n, untimed = 0.0, 0, 0
    by_family: dict[str, dict[str, float]] = {}
    for i in identities:
        n += 1
        total_s += i["seconds"]
        untimed += 1 if i["untimed"] else 0
        fam = by_family.setdefault(i["family"], {"sessions": 0, "minutes": 0.0})
        fam["sessions"] += 1
        fam["minutes"] += i["seconds"] / 60.0
    return {
        "sessions": n,
        "minutes": round(total_s / 60.0, 1),
        "by_family": {f: {"sessions": int(v["sessions"]), "minutes": round(v["minutes"], 1)} for f, v in sorted(by_family.items())},
        "untimed": untimed,
        "version": WORKOUT_IDENTITY_VERSION,
    }


def _strip(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _strip(v) for k, v in value.items() if k not in OWNER_ONLY_KEYS and k != "owner_only"}
    if isinstance(value, list):
        return [_strip(v) for v in value]
    return value


def public_projection(identity: dict[str, Any]) -> dict[str, Any]:
    """The identity with its `owner_only` block and every OWNER_ONLY_KEYS key removed, at any depth."""
    return _strip(identity)
