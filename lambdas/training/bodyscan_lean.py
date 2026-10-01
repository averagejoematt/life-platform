"""training/bodyscan_lean.py — the between-DXA lean and regional read from Withings Body Scan 2 (#4503, OD6).

Owner ruling OD6 (A, AMENDED by the owner, 2026-09-30): the week-8 DXA is a baseline plus the gross-
failure and regional checks; `lean_mass`, `dxa_override` and the 260-band permission first evaluate
at week 16. Between DXA scans, the Body Scan 2 metrics already ingested (#2782, docs/SCHEMA.md
§Withings BodyScan 2) are the between-scan lean and regional TREND signal. They carry a bioimpedance
label (hydration-sensitive) and a noise band taken from his own repeat full scans (ADR-105), and they
are never a substitute for the DXA anchor.

The read is pure arithmetic over the stored rows:

  * a FULL SCAN is a row carrying all 15 segmental fields `{fat_free_mass,fat_mass,muscle_mass}_
    {torso,left_arm,right_arm,left_leg,right_leg}_kg`. Regions: torso; arms = left + right; legs =
    left + right. The scalar `fat_free_mass_kg` is the total (the five segments sum to it, #2994).
  * the BASELINE is the first full scan on or after the latest DXA's `scan_date` — or, with no DXA
    on or before the window, the earliest full scan, and the row says so. The LATEST is the last full
    scan on or before `as_of`.
  * the NOISE BAND comes from his own repeat scans. The differences between full scans at most
    `REPEAT_MAX_GAP_DAYS` apart are read as measurement noise, and their sample SD x 1.96 is the band
    a change must exceed (a difference already carries both scans' error). Below `MIN_NOISE_N` pairs
    the band is unknown and the delta is reported but not judged. The pair count `n` is on every row.
"""

from __future__ import annotations

import statistics
from typing import Any

LABEL = (
    "bioimpedance (Withings Body Scan 2) — hydration-sensitive; a between-DXA trend and regional signal, "
    "never a substitute for the DXA anchor (OD6, #4503)"
)
REGIONS: dict[str, tuple[str, ...]] = {"torso": ("torso",), "arms": ("left_arm", "right_arm"), "legs": ("left_leg", "right_leg")}
_SEGMENTS = ("torso", "left_arm", "right_arm", "left_leg", "right_leg")
_KINDS = ("fat_free_mass", "fat_mass", "muscle_mass")
REPEAT_MAX_GAP_DAYS = 2
MIN_NOISE_N = 3
Z_95 = 1.96


def _num(v: Any) -> float | None:
    try:
        return None if v in (None, "") or isinstance(v, bool) else float(v)
    except (TypeError, ValueError):
        return None


def _day(row: dict[str, Any]) -> str:
    return str(row.get("date") or str(row.get("sk") or "").replace("DATE#", ""))[:10]


def full_scans(rows: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The full Body Scan 2 scans, oldest first: {date, total_ffm_kg, ffm: {torso, arms, legs}, fat_mass, muscle_mass}."""
    out = []
    for r in rows or []:
        seg = {f"{k}_{s}": _num(r.get(f"{k}_{s}_kg")) for k in _KINDS for s in _SEGMENTS}
        if any(v is None for v in seg.values()) or not _day(r):
            continue
        point: dict[str, Any] = {"date": _day(r), "total_ffm_kg": _num(r.get("fat_free_mass_kg"))}
        for k in _KINDS:
            point[k] = {reg: round(sum(float(seg[f"{k}_{s}"] or 0) for s in segs), 2) for reg, segs in REGIONS.items()}
        out.append(point)
    return sorted(out, key=lambda p: p["date"])


def _metric(p: dict[str, Any], key: str) -> float | None:
    if key == "total_ffm_kg":
        return p.get("total_ffm_kg")
    kind, reg = key.rsplit(":", 1)
    return (p.get(kind) or {}).get(reg)


def noise_band(scans: list[dict[str, Any]], key: str) -> dict[str, Any]:
    """1.96 x SD of the repeat-scan differences for one metric (`total_ffm_kg` or `kind:region`)."""
    from common.pacific_time import parse_day_key

    diffs = []
    for a, b in zip(scans, scans[1:]):
        da, db, va, vb = parse_day_key(a["date"]), parse_day_key(b["date"]), _metric(a, key), _metric(b, key)
        if da and db and va is not None and vb is not None and (db - da).days <= REPEAT_MAX_GAP_DAYS:
            diffs.append(vb - va)
    if len(diffs) < MIN_NOISE_N:
        return {
            "band_kg": None,
            "n": len(diffs),
            "reason": f"{len(diffs)} repeat-scan pair(s) <= {REPEAT_MAX_GAP_DAYS} d apart; {MIN_NOISE_N} needed",
        }
    return {
        "band_kg": round(Z_95 * statistics.stdev(diffs), 2),
        "n": len(diffs),
        "basis": f"1.96 x SD of his own repeat-scan differences (<= {REPEAT_MAX_GAP_DAYS} d apart)",
    }


def between_dxa_read(withings_rows: list[dict[str, Any]] | None, dxa_scans: list[dict[str, Any]] | None, as_of: str) -> dict[str, Any]:
    """The between-DXA lean/regional read (module docstring). `withings_rows` None = the read failed."""
    if withings_rows is None:
        return {"state": "read_failed", "label": LABEL}
    scans = [s for s in full_scans(withings_rows) if s["date"] <= as_of]
    if len(scans) < 2:
        return {
            "state": "insufficient",
            "label": LABEL,
            "full_scans": len(scans),
            "reason": "fewer than two full Body Scan 2 scans on record",
        }
    dxa_dates = sorted(str(r.get("scan_date") or "")[:10] for r in (dxa_scans or []) if r.get("scan_date") and str(r["scan_date"]) <= as_of)
    anchor = dxa_dates[-1] if dxa_dates else None
    base = next((s for s in scans if anchor and s["date"] >= anchor), None)
    base_rule = f"the first full scan on/after the latest DXA ({anchor})"
    if base is None:
        base, base_rule = scans[0], (
            f"the earliest full scan — no full scan since the latest DXA ({anchor})"
            if anchor
            else "the earliest full scan — no DXA on record"
        )
    last = scans[-1]
    deltas: dict[str, Any] = {}
    for key in ["total_ffm_kg"] + [f"{k}:{reg}" for k in ("fat_free_mass", "muscle_mass") for reg in REGIONS]:
        b, l = _metric(base, key), _metric(last, key)
        if b is None or l is None:
            continue
        d = round(l - b, 2)
        band = noise_band(scans, key)
        beyond = None if band["band_kg"] is None else abs(d) > band["band_kg"]
        deltas[key] = {"from_kg": b, "to_kg": l, "delta_kg": d, "noise": band, "beyond_noise": beyond}
    return {
        "state": "measured",
        "label": LABEL,
        "dxa_anchor": anchor,
        "baseline": {"date": base["date"], "rule": base_rule},
        "latest": last["date"],
        "full_scans": len(scans),
        "deltas": deltas,
        "rule": "a delta inside its noise band is not a change; beyond it is a trend to watch, never a DXA verdict (ADR-105)",
    }
