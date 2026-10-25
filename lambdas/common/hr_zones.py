"""hr_zones.py — THE heart-rate zone band, and the reader that applies it to stored 5-bpm bins (#4627, #5353).

The platform's 5-zone INTENSITY model by fraction of max HR lived in `mcp/helpers.py` (#2221); it moved
here so the pure `training.zone2_minutes` reader can apply the SAME table without importing the MCP
package. `mcp/helpers.HR_ZONE_BOUNDS` re-exports it. Nothing else may restate it.

  Zone 1: 50-60%   Zone 2: 60-70%   Zone 3: 70-80%   Zone 4: 80-90%   Zone 5: 90-100% (and above)
  Below 50% is `below_zone_1`.

READ-TIME ONLY. The Apple workouts writer stores seconds per 5-bpm bin (`derived.hr_seconds_by_bpm5`)
and assumes no band; the band is applied here, at read, from a max HR the caller supplies
(`common.max_hr`).

THE SPLIT RULE for a bin that straddles a zone edge: a bin labelled `b` covers bpm [b, b+5). Its
seconds are taken as uniform across that interval and divided between zones by the width of overlap
with each zone's [lo*max, hi*max) interval. A bin wholly inside a zone is that zone's; zone edges are
fractional bpm (0.60 * 183 = 109.8), so at max 183 the bin 105 gives 4.8/5 of its seconds to Zone 1 and 0.2/5 to
Zone 2. Zone 5 is open above.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

HR_ZONE_BOUNDS = (
    ("zone_1", "Zone 1 (Recovery)", 0.50, 0.60),
    ("zone_2", "Zone 2 (Aerobic)", 0.60, 0.70),
    ("zone_3", "Zone 3 (Tempo)", 0.70, 0.80),
    ("zone_4", "Zone 4 (Threshold)", 0.80, 0.90),
    ("zone_5", "Zone 5 (VO2 Max)", 0.90, 1.00),
)
#: The zone keys a result carries, in order (zone 0 is `below_zone_1`).
ZONE_KEYS = ("below_zone_1", "zone_1", "zone_2", "zone_3", "zone_4", "zone_5")
BIN_BPM = 5  # the writer's bin width (`health_auto_export_workouts._HR_BIN_BPM`)


def zone_seconds_from_bpm_bins(bins: Mapping[str, Any], max_hr: float, bin_bpm: int = BIN_BPM) -> Dict[str, float]:
    """Seconds per zone from `{lower_bpm_edge: seconds}` bins at `max_hr`, splitting straddling bins by overlap."""
    out = {k: 0.0 for k in ZONE_KEYS}
    edges = [("below_zone_1", float("-inf"), HR_ZONE_BOUNDS[0][2] * max_hr)]
    for i, (key, _label, lo, hi) in enumerate(HR_ZONE_BOUNDS):
        edges.append((key, lo * max_hr, float("inf") if i == len(HR_ZONE_BOUNDS) - 1 else hi * max_hr))
    for raw_lo, raw_secs in (bins or {}).items():
        try:
            b_lo, secs = float(raw_lo), float(raw_secs)
        except (TypeError, ValueError):
            continue
        if secs <= 0 or secs != secs:
            continue
        b_hi = b_lo + bin_bpm
        for key, z_lo, z_hi in edges:
            width = min(b_hi, z_hi) - max(b_lo, z_lo)
            if width > 0:
                out[key] += secs * width / bin_bpm
    return out
