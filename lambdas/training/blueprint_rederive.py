"""training/blueprint_rederive.py — the activity basis of the 2024–25 blueprint band table (#4427, TB-7).

WHY THIS EXISTS. The `training_reference` singleton (episode-detect, #930/#951/#3709) sums
Strava activities into weekly rates per 10-lb weight band. Through 2024–25 two devices (a
Garmin watch and WHOOP) both pushed each walk and run to Strava, so the band table counted
every session about twice and its hours and heart rates were wrong by a large factor. The
read seam (#4419, `common.strava_read_seam`) removes twins with a PAIR rule tuned for every
consumer (keep the richer copy). The blueprint derivation needs something narrower and
stated: one session counted once, at a stated duration, with a stated heart-rate rule. That
is this module, and it is what the 2026-09-29 v0.5 red team's round 2 re-derived by hand.

THE RULE (stamped on the record as `method`, so a reader can see what the numbers rest on):
  * Cluster records of the same kind (walk incl. hike, run, cycle, lift) when they overlap by
    at least half of the SHORTER one's elapsed interval, or start within 5 minutes of each
    other. Clustering is transitive: a long Garmin walk that WHOOP split into two chunks is
    one session of three records.
  * A cluster counts ONCE. Its hours are its LONGEST member's moving time; its miles are the
    largest distance any member measured (WHOOP measures none).
  * Its heart rate is the HIGHEST member average inside the plausible band. A device average
    outside the band is rejected, never averaged in: the 2024 Garmin walk copies read 44–57
    bpm (below his resting rate) for minutes WHOOP read 100+. With no plausible member the
    session has no heart rate — absence, never 0 (ADR-104).
  * The clustering needs the RAW partition (every device's record), so the caller reads
    strava with the seam's `keep_duplicates` opt-out and clusters here. Clustering the seam's
    output instead would inherit the richer-copy duration, not the longest one.

Pure — no boto3, no I/O, no clock reads.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from common.pacific_time import parse_iso_utc  # #1964: THE ISO parser (naive == UTC)

#: Bumped whenever the rule below changes; consumers compare it, never the prose.
METHOD_ID = "session_cluster_v1"
#: Share of the shorter record's elapsed interval that must overlap the other's.
OVERLAP_SHARE_OF_SHORTER = 0.5
#: Two records of one kind starting this close are one session whatever their durations.
START_WINDOW_MIN = 5
#: A device average heart rate outside [low, high] is an artefact, not a reading.
PLAUSIBLE_AVG_HR_BPM = (70.0, 220.0)
#: The 2024–25 cut the red team re-derived. The record states its session counts over it.
CUT_WINDOW = ("2024-09-04", "2025-05-10")


def method() -> Dict[str, Any]:
    """The rule as data, for the record's `method` field."""
    lo, hi = PLAUSIBLE_AVG_HR_BPM
    return {
        "id": METHOD_ID,
        "source": "strava, every device's record (read-seam opt-out), clustered here",
        "cluster": (
            f"same kind; overlap >= {OVERLAP_SHARE_OF_SHORTER:g} of the shorter record's elapsed time, "
            f"or starts within {START_WINDOW_MIN} min; transitive"
        ),
        "hours": "the cluster's longest member moving time",
        "miles": "the largest distance any member measured",
        "heart_rate": f"highest member average in [{lo:g}, {hi:g}] bpm; outside it rejected; none plausible -> absent",
        "band_heart_rate": "time-weighted by session hours",
        "issue": "#4427",
    }


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN -> None


def plausible_hr(v: Any) -> Optional[float]:
    """The average heart rate if it is physiologically possible, else None."""
    hr = _num(v)
    lo, hi = PLAUSIBLE_AVG_HR_BPM
    return hr if hr is not None and lo <= hr <= hi else None


def _start(r: Dict[str, Any]) -> Optional[datetime]:
    return parse_iso_utc(r.get("start") or "") if r.get("start") else None


def _span_s(r: Dict[str, Any]) -> float:
    return _num(r.get("elapsed_s")) or _num(r.get("moving_s")) or 0.0


def _same_session(a: Dict[str, Any], ta: datetime, b: Dict[str, Any], tb: datetime) -> bool:
    if abs((tb - ta).total_seconds()) <= START_WINDOW_MIN * 60:
        return True
    da, db = _span_s(a), _span_s(b)
    if da <= 0 or db <= 0:
        return False
    overlap = (min(ta + timedelta(seconds=da), tb + timedelta(seconds=db)) - max(ta, tb)).total_seconds()
    return overlap >= OVERLAP_SHARE_OF_SHORTER * min(da, db)


def _clusters(records: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
    """Group one kind's records into sessions (union-find over the start-ordered list)."""
    timed = sorted(((r, t) for r, t in ((r, _start(r)) for r in records) if t is not None), key=lambda x: x[1])
    parent = list(range(len(timed)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, (a, ta) in enumerate(timed):
        reach = ta + max(timedelta(seconds=_span_s(a)), timedelta(minutes=START_WINDOW_MIN))
        for j in range(i + 1, len(timed)):
            b, tb = timed[j]
            if tb > reach:
                break  # start-ordered: nothing later can overlap `a` or start near it
            if _same_session(a, ta, b, tb):
                parent[find(j)] = find(i)
    groups: Dict[int, List[Dict[str, Any]]] = {}
    for i, (r, _t) in enumerate(timed):
        groups.setdefault(find(i), []).append(r)
    untimed = [[r] for r in records if _start(r) is None]  # no start: cannot be matched, counts alone
    return list(groups.values()) + untimed


def _session(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    longest = max(members, key=lambda r: _num(r.get("moving_s")) or 0.0)
    hrs = [h for h in (plausible_hr(r.get("hr")) for r in members) if h is not None]
    return {
        "date": min(str(r.get("date") or "")[:10] for r in members),
        "kind": longest.get("kind"),
        "hours": (_num(longest.get("moving_s")) or 0.0) / 3600.0,
        "miles": max((_num(r.get("miles")) or 0.0) for r in members),
        "hr": max(hrs) if hrs else None,
        "n_records": len(members),
    }


def distinct_sessions(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Raw device records -> one row per real session, in the band builder's activity shape.

    `records`: [{date, kind, start (ISO), elapsed_s, moving_s, miles, hr}]. Returns
    [{date, kind, hours, miles, hr, n_records}], clustered per kind by the module rule.
    """
    by_kind: Dict[Any, List[Dict[str, Any]]] = {}
    for r in records:
        by_kind.setdefault(r.get("kind"), []).append(r)
    out = [_session(c) for kind in sorted(by_kind, key=str) for c in _clusters(by_kind[kind])]
    return sorted(out, key=lambda s: (s["date"], str(s["kind"])))


def session_basis(records: List[Dict[str, Any]], sessions: List[Dict[str, Any]], window: Tuple[str, str] = CUT_WINDOW) -> Dict[str, Any]:
    """Per-kind n over `window`: raw records, distinct sessions, hours both ways, HR rejections.

    This is the `n` a reader checks the table against — the live proof of #4427 is that the
    distinct walk count and hours here reproduce the red team's round-2 re-derivation.
    """
    d0, d1 = window

    def inside(r: Dict[str, Any]) -> bool:
        return d0 <= str(r.get("date") or "")[:10] <= d1

    out: Dict[str, Any] = {"window": f"{d0}..{d1}"}
    for kind in ("walk", "run"):
        recs = [r for r in records if r.get("kind") == kind and inside(r)]
        sess = [s for s in sessions if s.get("kind") == kind and inside(s)]
        out[kind] = {
            "records": len(recs),
            "sessions": len(sess),
            "hours_records_summed": round(sum((_num(r.get("moving_s")) or 0.0) for r in recs) / 3600.0, 1),
            "hours_sessions": round(sum(s["hours"] for s in sess), 1),
            "hr_rejected_records": sum(1 for r in recs if _num(r.get("hr")) is not None and plausible_hr(r.get("hr")) is None),
            "sessions_with_hr": sum(1 for s in sess if s["hr"] is not None),
        }
    return out


def supersedes_label(prior: Optional[Dict[str, Any]], new_ref: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What a new reference replaces. Every weekly record stays in the partition as history
    (SK = DATE#derived_date); this names the newest one before it and, when that one was
    built by another method, labels it superseded with the reason — the old table is kept,
    and readers take the newest, so the label is how a reader of the history tells them apart."""
    if not prior or not prior.get("sk"):
        return None
    prior_schema = int(_num(prior.get("reference_schema")) or 1)
    prior_method = prior["method"].get("id") if isinstance(prior.get("method"), dict) else None
    out: Dict[str, Any] = {
        "sk": str(prior["sk"]),
        "reference_schema": prior_schema,
        "method": prior_method or "twin-counted (before #4427)",
    }
    new_method = new_ref["method"].get("id") if isinstance(new_ref.get("method"), dict) else None
    if prior_method != new_method:
        out["status"] = "superseded"
        out["reason"] = (
            "built before #4427: device twins counted separately and implausible device heart rates averaged in"
            if prior_method is None
            else f"built by {prior_method}, replaced by {new_method}"
        )
    return out
