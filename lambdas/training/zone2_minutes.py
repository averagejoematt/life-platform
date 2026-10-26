"""training/zone2_minutes.py — THE Zone 2 computation (#4627, built on #4644 Q1's recommended answer).

WHY THIS EXISTS

Three surfaces served three different Zone 2 numbers for the same week (#4627, measured
2026-10-04): `/api/training_overview` counted a whole activity as Zone 2 when its AVERAGE heart
rate fell inside 60–70% of a hardcoded maximum and then added every Hevy bike/elliptical block
on top; `/api/zone2` and the MCP `get_zone2_breakdown` tool did the average-HR method with the
profile maximum and a 10-minute floor; the hypothesis engine read stored time-in-zone. The week
of 2026-09-28 was served as 940 / 518 min against 38 (Whoop) – 83 (Strava) by the vendors' own
zones. This module is the one definition all three read.

THE DEFINITION (the recommended answer to #4644 Q1, held until the owner rules)

  "devices' own Zone 2 · minutes in zone · Hevy bike/elliptical/treadmill = cardio minutes,
  not Zone 2"

  * BAND — each recording's own Zone 2: Whoop's `zone_2_minutes` on a Whoop workout sub-row
    (real since #4629's writer fix, PR #4922), Strava's `zone2_seconds` on a Strava activity
    (Strava's per-athlete zones over the recording device's stream). No maximum heart rate is
    assumed here and no band is computed here.
  * METHOD — minutes actually spent in the zone, from the stored time-in-zone rows. A
    session's average heart rate is never read.
  * HEVY — a cardio block logged in Hevy (no heart-rate stream) is reported as
    `hevy_cardio_minutes` and is NEVER added to Zone 2. Its heart-rate minutes, when a wearable
    recorded them, already reach Zone 2 through that wearable's own row.

COUNTED ONCE

  * A Whoop workout stored under two date keys (a session crossing 00:00 UTC, #4629 defect 3)
    is one workout: one row per `workout_id`, the row carrying measured zones preferred, and the
    day is the Pacific date of its `start_time` (the frame of every other day key on the site).
  * A Whoop row whose zone fields are all zero is UNMEASURED, not a measured zero: the pre-#4922
    writer stored six zeros on every workout (the vendor key was misread), and a real workout
    always spends its minutes in some zone, zone 0 included.
  * Strava activities arrive through `strava_read_seam` (the caller's `_query_source` /
    `query_source` applies it), which already folds same-sport echoes inside the partition.
  * ACROSS SOURCES (#5369) — sessions are `training.workout_identity`'s identities, the ONE
    cross-source workout rule: Hevy, Strava, the watch's `apple_workouts` and Whoop's workout rows,
    same family (or a label naming none — Whoop's "activity" / "Cross Training") overlapping by
    half the shorter interval, Hevy's own Strava push dropped as an echo of the Hevy session in
    hand, a HealthKit workout Hevy or the pliability app wrote folded into that app's record. So a
    gym visit is its PARTS — the lift, the ride, the mobility block — each once and each labelled
    by what it was; before #5369 a zone2-local union-find (`_same_session` / `_groups`) chained the
    whole visit into one session called WeightTraining and lost the ride. A Hevy-only identity (no
    wearable recorded it) is not a Zone 2 session: its blocks are `hevy_cardio_minutes`, as before.
    Each session's zones come from ONE source: the first in `SOURCE_PRIORITY` (Whoop, the device
    worn throughout and the one whose own band Strava re-zones when Whoop pushes a workout) whose
    recordings measured at least `CONTAINMENT_SHARE` of the most any source measured of the session
    (total seconds in any zone) — so Strava's zones count only where no Whoop row measured the
    session, or a second device measured materially more of it. Every Apple origin shares the
    Apple slot (the HR is the watch's whichever app started the workout).
  * TIME CLAIMED ONCE (#5369) — two parts of one visit can carry the same minutes (on 2026-10-25
    Hevy's watch app and WHOOP labelled the last 23 minutes a lift while the pliability app
    recorded them as mobility). A recording's zone seconds are scaled by the share of its interval
    no earlier-claimed recording covers, tightest interval first (walking_volume's #4068 pro-rata
    rule, `uncovered_seconds`) — inside a source's candidate and across the whole read — and
    `overlap_minutes_removed` says how much a session gave up. A Hevy push that carries a seam
    graft holds the folded wearable copy's zones over an interval it does not know, so it is
    counted whole and claims nothing.

Pure — no boto3, no I/O, no clock reads: every date comes from the caller.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

from common.hr_zones import ZONE_KEYS, zone_seconds_from_bpm_bins
from common.max_hr import DEFAULT_MAX_HR
from common.pacific_time import pacific_date_of, parse_iso_utc
from common.strava_read_seam import STRAVA_SOURCE, strava_read_seam

from training import workout_identity
from training.walking_volume import apple_workout_source, uncovered_seconds

#: One sentence a surface can print — the recommended answer's words, unparaphrased.
DEFINITION = "devices' own Zone 2 · minutes in zone · Hevy bike/elliptical/treadmill = cardio minutes, not Zone 2"
#: The weekly reference the surfaces compare against (Attia / Huberman / WHO), unchanged.
WEEKLY_TARGET_MIN = 150
#: "Trailing 7 days" = the 7 dates [end − 6, end] (#4627: `end − 7` counted 8).
TRAILING_DAYS = 7
#: Tie-break between sources that measured the same number of seconds of a session.
WHOOP = "whoop"  # the partition the Whoop workout sub-rows live in
STRAVA = STRAVA_SOURCE  # the read seam's own name for its partition
APPLE = "apple_health"  # #4979: the Apple Watch's own workouts (the #4973 `apple_workouts` map)
APPLE_WORKOUTS_FIELD = "apple_workouts"  # owner-only (privacy.field_tiers); never served raw
# #4979 (per the #4627 ruling, "devices' own Zone 2 · minutes in zone"): the Apple Watch's own
# Zone 2 joins as the THIRD source — it counts only where no Whoop or Strava recording measured the
# session (or it measured materially more of it), so no number served before the watch moves.
SOURCE_PRIORITY = (WHOOP, STRAVA, APPLE)
#: The source-choice share (`_choose`): a higher-priority source wins unless another measured
#: materially more of the session. (START_WINDOW_MIN, the retired `_same_session`'s other
#: threshold, went with it in #5369.)
CONTAINMENT_SHARE = 0.8
#: A session's sport label when no Strava member names it (Strava's own vocabulary, so a
#: per-sport split reads one word per kind across sources).
FAMILY_SPORT = {"cycling": "Ride", "walking": "Walk", "running": "Run", "strength": "WeightTraining", "mobility": "Mobility"}
#: Zone keys every result carries; Whoop's zone 0 and anything below Strava's zone 1 is below_zone_1.
#: Hevy exercise-name tokens that mark a steady-cardio block (moved verbatim from the
#: training_overview handler's P0.4 fold, so the set of blocks reported is unchanged).
HEVY_CARDIO_TOKENS = ("cycling", "elliptical", "rowing", "treadmill", "stair", "ski erg", "ski-erg", "assault", "echo bike", "air bike")


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _row_date(row: Mapping[str, Any]) -> str:
    return str(row.get("date") or str(row.get("sk", "")).replace("DATE#", ""))[:10]


def trailing_window(end_date: str, days: int = TRAILING_DAYS) -> Tuple[str, str]:
    """(start, end) covering exactly `days` dates ending on `end_date`, inclusive."""
    end = datetime.strptime(end_date[:10], "%Y-%m-%d")
    return (end - timedelta(days=days - 1)).strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")


def window_dates(start_date: str, end_date: str) -> List[str]:
    """Every date in [start, end], inclusive."""
    d = datetime.strptime(start_date[:10], "%Y-%m-%d")
    end = datetime.strptime(end_date[:10], "%Y-%m-%d")
    out = []
    while d <= end:
        out.append(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return out


# ── the recordings ────────────────────────────────────────────────────────────


def _whoop_zones(row: Mapping[str, Any]) -> Optional[Dict[str, float]]:
    """Seconds per zone from a Whoop workout sub-row, or None when unmeasured (absent or all-zero)."""
    secs = {k: 0.0 for k in ZONE_KEYS}
    seen = False
    for i in range(6):
        m = _num(row.get(f"zone_{i}_minutes"))
        if m is None:
            continue
        seen = True
        secs["below_zone_1" if i == 0 else f"zone_{i}"] += m * 60.0
    if not seen or sum(secs.values()) <= 0:
        return None
    return secs


def _strava_zones(act: Mapping[str, Any]) -> Optional[Dict[str, float]]:
    """Seconds per zone from a Strava activity's `zone{n}_seconds`, or None when it carries none."""
    secs = {k: 0.0 for k in ZONE_KEYS}
    for i in range(1, 6):
        secs[f"zone_{i}"] = _num(act.get(f"zone{i}_seconds")) or 0.0
    return secs if sum(secs.values()) > 0 else None


def whoop_recordings(whoop_rows: Optional[Iterable[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """Whoop WORKOUT sub-rows -> one recording per `workout_id` (day rows ignored)."""
    by_id: Dict[str, Dict[str, Any]] = {}
    for row in whoop_rows or []:
        sk = str(row.get("sk", ""))
        if "#WORKOUT#" not in sk:
            continue
        wid = str(row.get("workout_id") or sk.split("#WORKOUT#", 1)[1])
        start, end = parse_iso_utc(row.get("start_time")), parse_iso_utc(row.get("end_time"))
        zones = _whoop_zones(row)
        rec = {
            "source": WHOOP,
            "identity_source": WHOOP,
            "id": wid,
            "device": WHOOP,
            "date": pacific_date_of(row.get("start_time") or "") or _row_date(row),
            "sport": row.get("vendor_sport_name") or row.get("sport_name") or "Activity",
            "start": start,
            "end": end,
            "duration_s": (end - start).total_seconds() if (start and end and end > start) else 0.0,
            "zones": zones,
        }
        prior = by_id.get(wid)
        if prior is None or (prior["zones"] is None and zones is not None):
            by_id[wid] = rec
    return list(by_id.values())


def strava_recordings(strava_rows: Optional[Iterable[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """Seam-deduped Strava day rows -> one recording per activity (`strava_id`)."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for row in strava_rows or []:
        date = _row_date(row)
        for i, act in enumerate(row.get("activities") or []):
            sid = str(act.get("strava_id") or act.get("id") or f"{date}#{i}")
            if sid in seen:
                continue
            seen.add(sid)
            start = parse_iso_utc(act.get("start_date"))
            dur = _num(act.get("elapsed_time_seconds")) or _num(act.get("moving_time_seconds")) or 0.0
            out.append(
                {
                    "source": STRAVA,
                    "identity_source": STRAVA,
                    "graft": bool(act.get("hr_from_strava_id")),
                    "id": sid,
                    "device": str(act.get("device_name") or "").lower(),
                    "date": date,
                    "sport": act.get("sport_type") or act.get("type") or "Unknown",
                    "start": start,
                    "end": (start + timedelta(seconds=dur)) if start else None,
                    "duration_s": dur,
                    "zones": _strava_zones(act),
                }
            )
    return out


def apple_recordings(apple_rows: Optional[Iterable[Mapping[str, Any]]], max_hr: Optional[float] = None) -> List[Dict[str, Any]]:
    """#5353: Apple Watch workouts from the apple_health DAY rows' owner-only `apple_workouts` map
    (`{vendor workout id: summary}`, the #4973 writer) -> one recording per id.

    The watch's zone seconds are derived HERE, at read time, from `derived.hr_seconds_by_bpm5` (seconds
    per 5-bpm bin) through `common.hr_zones` — the one zone-band table — at `max_hr` (default
    `common.max_hr.DEFAULT_MAX_HR`; callers holding the profile pass its value). The writer assumes no band
    (#4627); a workout with no bins is unmeasured (it still groups with the same session from another
    device, it just measures nothing). A bin straddling a zone edge is split by overlap width."""
    mx = float(max_hr) if max_hr else float(DEFAULT_MAX_HR)
    by_id: Dict[str, Dict[str, Any]] = {}
    for row in apple_rows or []:
        workouts = row.get(APPLE_WORKOUTS_FIELD)
        if not isinstance(workouts, Mapping):
            continue
        for wid, w in workouts.items():
            if not isinstance(w, Mapping):
                continue
            wid = str(wid)
            start, end = parse_iso_utc(w.get("start")), parse_iso_utc(w.get("end"))
            bins = (w.get("derived") or {}).get("hr_seconds_by_bpm5") if isinstance(w.get("derived"), Mapping) else None
            zones = zone_seconds_from_bpm_bins(bins, mx) if bins else None
            if zones is not None and sum(zones.values()) <= 0:
                zones = None
            rec = {
                "source": APPLE,  # every origin shares the Apple slot in SOURCE_PRIORITY
                "identity_source": apple_workout_source(dict(w)),  # the resolver's key: `apple_health/<origin>` for Hevy / pliability
                "id": wid,
                "device": APPLE,
                "date": pacific_date_of(str(w.get("start") or "")) or _row_date(row),
                "sport": w.get("name") or "Activity",
                "start": start,
                "end": end,
                "duration_s": (end - start).total_seconds() if (start and end and end > start) else 0.0,
                "zones": zones,
            }
            if wid not in by_id or (by_id[wid]["zones"] is None and zones is not None):
                by_id[wid] = rec
    return list(by_id.values())


def hevy_cardio_blocks(hevy_rows: Optional[Iterable[Mapping[str, Any]]]) -> List[Dict[str, Any]]:
    """Hevy steady-cardio blocks (bike / elliptical / treadmill …): one per exercise per workout."""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for row in hevy_rows or []:
        wid = str(row.get("workout_uid") or row.get("source_workout_id") or row.get("sk") or "")
        if wid in seen:
            continue
        seen.add(wid)
        for ex in row.get("exercises") or []:
            name = str(ex.get("name") or ex.get("exercise_name") or "").strip()
            if not any(t in name.lower() for t in HEVY_CARDIO_TOKENS):
                continue
            secs = sum(_num(s.get("duration_sec")) or 0.0 for s in ex.get("sets") or [])
            if secs > 0:
                out.append({"source": "hevy", "workout_id": wid, "date": _row_date(row), "name": name, "minutes": secs / 60.0})
    return out


# ── counted once ──────────────────────────────────────────────────────────────


def _interval(m: Mapping[str, Any]) -> Optional[Tuple[datetime, datetime]]:
    if m.get("graft") or not (m["start"] and m["end"]) or m["end"] <= m["start"]:
        return None  # a grafted Hevy push holds another record's zones over an interval it does not know
    return m["start"], m["end"]


def _claim(recs: List[Dict[str, Any]], claimed: List[Tuple[datetime, datetime]]) -> Dict[int, float]:
    """{id(rec): share of its zone seconds still unclaimed} — tightest interval first; each timed
    recording then claims its interval (`claimed` is mutated). Untimed / grafted ones count whole."""
    shares: Dict[int, float] = {}
    for m in sorted(recs, key=lambda m: (_interval(m) is None, m["duration_s"], m["identity_source"], m["id"])):
        iv = _interval(m)
        if iv is None:
            shares[id(m)] = 1.0
            continue
        span = (iv[1] - iv[0]).total_seconds()
        shares[id(m)] = uncovered_seconds(iv[0], iv[1], claimed) / span
        claimed.append(iv)
    return shares


def _source_candidate(members: List[Dict[str, Any]]) -> Optional[Tuple[float, Dict[str, float], List[Dict[str, Any]]]]:
    """(measured seconds, zone seconds, recordings used) for one source's members of a session —
    its recordings' zones summed, overlapping ones counted once (`_claim`, inside the source)."""
    measured = [m for m in members if m["zones"] is not None]
    if not measured:
        return None
    share = _claim(measured, [])
    zones = {k: sum(m["zones"][k] * share[id(m)] for m in measured) for k in ZONE_KEYS}
    return sum(zones.values()), zones, [m for m in measured if share[id(m)] > 0]


def _choose(cands: Mapping[str, Tuple[float, Dict[str, float], List[Dict[str, Any]]]]) -> Optional[str]:
    """The first source in SOURCE_PRIORITY that measured at least CONTAINMENT_SHARE of the most any
    source measured of this session. Whoop's own zones win unless another recording measured
    materially more of the session — the same HR stream re-zoned by Strava (Whoop's push, or a
    Hevy copy carrying a grafted Whoop stream) measures the same seconds and never outranks it."""
    if not cands:
        return None
    best = max(c[0] for c in cands.values())
    return next(s for s in SOURCE_PRIORITY if s in cands and cands[s][0] >= CONTAINMENT_SHARE * best)


def _sessions_by_identity(
    strava_rows, whoop_rows, apple_rows, max_hr, hevy_rows
) -> List[Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]]:
    """[(identity or None, its wearable recordings)] — one entry per identity holding at least one
    recording (a Hevy-only identity is not a Zone 2 session). A recording the resolver could not key
    (no vendor id) stands alone."""
    strava_rows = workout_identity.strava_without_echoes(strava_read_seam(STRAVA, list(strava_rows or [])), hevy_rows)
    recs = strava_recordings(strava_rows) + whoop_recordings(whoop_rows) + apple_recordings(apple_rows, max_hr)
    identities = workout_identity.resolve_workout_identities(apple=apple_rows, strava=strava_rows, hevy=hevy_rows, whoop=whoop_rows)
    by_key = {(r["identity_source"], r["id"]): r for r in recs}
    out: List[Tuple[Optional[Dict[str, Any]], List[Dict[str, Any]]]] = []
    placed: set = set()
    for ident in identities:
        members = [by_key[(src, i)] for src, ids in ident["members"].items() for i in ids if (src, i) in by_key]
        members = [m for m in members if id(m) not in placed]
        if members:
            placed.update(id(m) for m in members)
            out.append((ident, members))
    out.extend((None, [r]) for r in recs if id(r) not in placed)
    return out


def _sport(ident: Optional[Mapping[str, Any]], rep: Optional[Mapping[str, Any]], first: Mapping[str, Any]) -> Any:
    """Strava's word for the session when a Strava recording is in it; for a Hevy-anchored part with
    none, its family in Strava's vocabulary (`FAMILY_SPORT` — "Ride", "Mobility"); otherwise the
    earliest recording's own name, as before #5369."""
    if rep:
        return rep["sport"]
    if ident and "hevy" in ident["sources"] and ident["family"] in FAMILY_SPORT:
        return FAMILY_SPORT[ident["family"]]
    return first["sport"]


def counted_sessions(strava_rows, whoop_rows, apple_rows=None, max_hr: Optional[float] = None, hevy_rows=None) -> List[Dict[str, Any]]:
    """Every session once, with the zone minutes of the source that measured the most of it.

    Sessions are `training.workout_identity`'s identities (#5369). `apple_rows` (#4979/#5353): the
    apple_health day rows whose `apple_workouts` map carries the watch's heart-rate bins, zoned at read
    time at `max_hr`. `hevy_rows` (#5369): the Hevy workout rows over the same read — the routine
    source that anchors a gym visit's parts and lets Hevy's own Strava push drop as its echo; without
    them the wearables resolve among themselves."""
    groups = _sessions_by_identity(strava_rows, whoop_rows, apple_rows, max_hr, hevy_rows)
    chosen_by_group: List[Tuple[Optional[str], Dict[str, Any]]] = []
    for _ident, group in groups:
        cands = {}
        for src in SOURCE_PRIORITY:
            c = _source_candidate([m for m in group if m["source"] == src])
            if c:
                cands[src] = c
        chosen = _choose(cands)
        chosen_by_group.append((chosen, cands))
    # TIME CLAIMED ONCE: every chosen recording across the read, tightest first.
    used_all = [m for chosen, cands in chosen_by_group if chosen for m in cands[chosen][2]]
    share = _claim(used_all, [])

    sessions: List[Dict[str, Any]] = []
    for (ident, group), (chosen, cands) in zip(groups, chosen_by_group):
        first = min(group, key=lambda m: (m["start"] is None, m["start"].timestamp() if m["start"] else 0.0, m["date"]))
        strava_members = [m for m in group if m["source"] == STRAVA]
        rep = max(strava_members, key=lambda m: m["duration_s"]) if strava_members else None
        family = ident["family"] if ident else None
        used = cands[chosen][2] if chosen else []
        zones = {k: sum(m["zones"][k] * share[id(m)] for m in used) for k in ZONE_KEYS} if chosen else None
        whole = sum(sum(m["zones"].values()) for m in used)
        measured = sum(zones.values()) if zones else 0.0
        zones_min = {k: round(zones[k] / 60.0, 2) for k in ZONE_KEYS} if zones else None
        hevy_ids = [f"hevy:{i}" for i in (ident or {}).get("members", {}).get("hevy", [])]
        sessions.append(
            {
                "date": first["date"],
                "source": chosen,
                "family": family,
                "workout_identity": ident["workout_identity"] if ident else None,
                "ids": sorted([f"{m['identity_source']}:{m['id']}" for m in group] + hevy_ids),
                "used_ids": sorted(f"{m['identity_source']}:{m['id']}" for m in used),
                "sport": _sport(ident, rep, first),
                "strava_id": rep["id"] if rep else None,
                "duration_minutes": round(
                    (ident["seconds"] if ident and ident["seconds"] else max(m["duration_s"] for m in group)) / 60.0,
                    1,
                ),
                "zones_minutes": zones_min,
                "zone_2_minutes": zones_min["zone_2"] if zones_min else None,
                "measured_minutes": round(measured / 60.0, 2) if chosen else 0.0,
                "overlap_minutes_removed": round(max(0.0, whole - measured) / 60.0, 2) if chosen else 0.0,
            }
        )
    return sorted(sessions, key=lambda s: (s["date"], s["ids"]))


def zone2_window(strava_rows, whoop_rows, hevy_rows, start_date: str, end_date: str, sessions=None) -> Dict[str, Any]:
    """Zone 2 minutes over [start_date, end_date] — the ONE number every surface serves.

    `sessions` lets a caller that already ran `counted_sessions` over a wider read reuse it;
    the result is identical either way (the window filter is on the session's date)."""
    dates = window_dates(start_date, end_date)
    in_win = set(dates)
    sess = [s for s in (sessions if sessions is not None else counted_sessions(strava_rows, whoop_rows)) if s["date"] in in_win]
    hevy = [b for b in hevy_cardio_blocks(hevy_rows) if b["date"] in in_win]
    by_day = {
        d: {"date": d, **{src: 0.0 for src in SOURCE_PRIORITY}, "zone_2_minutes": 0.0, "hevy_cardio_minutes": 0.0, "unmeasured_sessions": 0}
        for d in dates
    }
    zones = {k: 0.0 for k in ZONE_KEYS}
    by_source = {s: 0.0 for s in SOURCE_PRIORITY}
    unmeasured_min = 0.0
    for s in sess:
        day = by_day[s["date"]]
        if s["source"] is None:
            day["unmeasured_sessions"] += 1
            unmeasured_min += s["duration_minutes"]
            continue
        day[s["source"]] += s["zone_2_minutes"]
        day["zone_2_minutes"] += s["zone_2_minutes"]
        by_source[s["source"]] += s["zone_2_minutes"]
        for k in ZONE_KEYS:
            zones[k] += s["zones_minutes"][k]
    for b in hevy:
        by_day[b["date"]]["hevy_cardio_minutes"] += b["minutes"]
    rows = [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in by_day[d].items()} for d in dates]
    return {
        "start_date": dates[0] if dates else start_date,
        "end_date": dates[-1] if dates else end_date,
        "dates": len(dates),
        "zone_2_minutes": round(sum(by_source.values()), 1),
        "by_source": {k: round(v, 1) for k, v in by_source.items()},
        "zones_minutes": {k: round(v, 1) for k, v in zones.items()},
        "measured_minutes": round(sum(zones.values()), 1),
        "sessions_counted": sum(1 for s in sess if s["source"]),
        "unmeasured_sessions": sum(1 for s in sess if s["source"] is None),
        "unmeasured_minutes": round(unmeasured_min, 1),
        "hevy_cardio_minutes": round(sum(b["minutes"] for b in hevy), 1),
        "hevy_cardio_blocks": len(hevy),
        "by_day": rows,
        "sessions": sess,
        "definition": DEFINITION,
    }


def zone2_by_strava_id(sessions: Iterable[Mapping[str, Any]]) -> Dict[str, float]:
    """Each counted session's Zone 2 minutes attributed to its longest Strava member (for the
    per-sport / per-walk splits of a Strava-keyed list); Whoop-only sessions have no key."""
    return {str(s["strava_id"]): float(s["zone_2_minutes"] or 0.0) for s in sessions if s.get("strava_id") and s.get("source")}


def _monday(d: str) -> str:
    dt = datetime.strptime(d[:10], "%Y-%m-%d")
    return (dt - timedelta(days=dt.weekday())).strftime("%Y-%m-%d")


def weekly(sessions: Iterable[Mapping[str, Any]], hevy_rows=None, weekly_target_min: int = WEEKLY_TARGET_MIN) -> List[Dict[str, Any]]:
    """Monday-anchored weeks that hold at least one session (measured or not) or Hevy cardio block,
    oldest first. Each week's `zone_2_minutes` is the sum of its counted sessions — the same
    numbers `zone2_window` sums, so a week read through either path agrees."""
    weeks: Dict[str, Dict[str, Any]] = {}

    def wk(d: str) -> Dict[str, Any]:
        k = _monday(d)
        return weeks.setdefault(
            k,
            {
                "week_start": k,
                "zone_2_minutes": 0.0,
                "measured_minutes": 0.0,
                "session_minutes": 0.0,
                "activity_count": 0,
                "hevy_cardio_minutes": 0.0,
            },
        )

    for s in sessions:
        w = wk(s["date"])
        w["activity_count"] += 1
        w["session_minutes"] += s["duration_minutes"]
        if s.get("source"):
            w["zone_2_minutes"] += s["zone_2_minutes"]
            w["measured_minutes"] += s["measured_minutes"]
    for b in hevy_cardio_blocks(hevy_rows):
        wk(b["date"])["hevy_cardio_minutes"] += b["minutes"]
    out = []
    for k in sorted(weeks):
        w = weeks[k]
        z2 = round(w["zone_2_minutes"], 1)
        out.append(
            {
                **{f: (round(v, 1) if isinstance(v, float) else v) for f, v in w.items()},
                "zone_2_minutes": z2,
                "week_end": (datetime.strptime(k, "%Y-%m-%d") + timedelta(days=6)).strftime("%Y-%m-%d"),
                "target_pct": round(100 * z2 / weekly_target_min) if weekly_target_min > 0 else None,
                "target_met": (z2 >= weekly_target_min) if weekly_target_min > 0 else None,
            }
        )
    return out


def zone_distribution(sessions: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Minutes in each zone across the counted sessions, each zone as its device defines it."""
    measured = [s for s in sessions if s.get("source")]
    totals = {k: sum(s["zones_minutes"][k] for s in measured) for k in ZONE_KEYS}
    grand = sum(totals.values())
    return [
        {
            "zone": k,
            "total_minutes": round(totals[k], 1),
            "activity_count": sum(1 for s in measured if s["zones_minutes"][k] > 0),
            "pct_of_training": round(100 * totals[k] / grand, 1) if grand > 0 else 0,
        }
        for k in ZONE_KEYS
    ]


def sport_breakdown(sessions: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Zone 2 minutes per session sport, largest first (sessions with no Zone 2 time omitted)."""
    by: Dict[str, Dict[str, float]] = {}
    for s in sessions:
        if s.get("source") and (s["zone_2_minutes"] or 0) > 0:
            b = by.setdefault(str(s["sport"]), {"minutes": 0.0, "count": 0})
            b["minutes"] += s["zone_2_minutes"]
            b["count"] += 1
    return [
        {"sport_type": k, "zone_2_minutes": round(v["minutes"], 1), "activity_count": int(v["count"])}
        for k, v in sorted(by.items(), key=lambda x: -x[1]["minutes"])
    ]
