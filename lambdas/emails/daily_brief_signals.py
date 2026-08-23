"""daily_brief_signals.py — the brief's pure signal computations (#1665 extraction).

Split from daily_brief_lambda.py 2026-08-23: the #2944 absence-handling fix put
the module 25 lines over its recorded FULL ceiling (2737), and the size guard's
remedy is extraction, not a raised number. These are the brief's pure functions
— numeric helpers, journal signal extraction, cross-device activity dedup, TSB
and readiness computation — no AWS, no I/O, no module globals. The lambda
re-imports every name, so callers and tests keep one import surface.
"""

from common.digest_utils import safe_float
from common.pacific_time import parse_iso_utc
from common.platform_logger import get_logger
from training import training_load  # shared TSS-like load model (#490)

logger = get_logger("daily-brief")


def avg(vals):
    v = [x for x in vals if x is not None]
    return round(sum(v) / len(v), 1) if v else None


def clamp(val, lo=0, hi=100):
    return max(lo, min(hi, val))


def fmt_num(val):
    if val is None:
        return "—"
    return "{:,}".format(round(val))


def extract_journal_signals(entries):
    if not entries:
        return None
    mood_scores, energy_scores, stress_scores = [], [], []
    all_themes, all_emotions = [], []
    notable_quote = None
    templates_found = []
    for entry in entries:
        template = entry.get("template", "")
        templates_found.append(template)
        m = entry.get("enriched_mood")
        e = entry.get("enriched_energy")
        s = entry.get("enriched_stress")
        if m is not None:
            mood_scores.append(float(m))
        if e is not None:
            energy_scores.append(float(e))
        if s is not None:
            stress_scores.append(float(s))
        for t in entry.get("enriched_themes") or []:
            all_themes.append(t)
        for em in entry.get("enriched_emotions") or []:
            all_emotions.append(em)
        q = entry.get("enriched_notable_quote")
        if q and (template.lower() == "evening" or notable_quote is None):
            notable_quote = str(q)
        if m is None:
            for field in ("morning_mood", "day_rating"):
                val = entry.get(field)
                if val is not None:
                    mood_scores.append(float(val))
                    break
        if e is None:
            for field in ("morning_energy", "energy_eod"):
                val = entry.get(field)
                if val is not None:
                    energy_scores.append(float(val))
                    break
        if s is None:
            val = entry.get("stress_level")
            if val is not None:
                stress_scores.append(float(val))
    # Phase 2A: Extract enrichment fields for deeper coaching
    all_cognitive_patterns, all_defense_patterns = [], []
    all_avoidance_flags, all_growth_signals = [], []
    social_quality_readings, ownership_readings = [], []
    stress_sources = []
    for entry in entries:
        for cp in entry.get("enriched_cognitive_patterns") or []:
            all_cognitive_patterns.append(cp)
        for dp in entry.get("enriched_defense_patterns") or []:
            all_defense_patterns.append(dp)
        primary_defense = entry.get("enriched_primary_defense")
        if primary_defense and primary_defense not in all_defense_patterns:
            all_defense_patterns.insert(0, primary_defense)
        for af in entry.get("enriched_avoidance_flags") or []:
            all_avoidance_flags.append(af)
        for gs in entry.get("enriched_growth_signals") or []:
            all_growth_signals.append(gs)
        sq = entry.get("enriched_social_quality")
        if sq:
            social_quality_readings.append(sq)
        ow = entry.get("enriched_ownership")
        if ow is not None:
            ownership_readings.append(float(ow))
        ss = entry.get("stress_source")
        if ss:
            stress_sources.append(ss)

    return {
        "mood_avg": round(sum(mood_scores) / len(mood_scores), 1) if mood_scores else None,
        "energy_avg": round(sum(energy_scores) / len(energy_scores), 1) if energy_scores else None,
        "stress_avg": round(sum(stress_scores) / len(stress_scores), 1) if stress_scores else None,
        "themes": list(dict.fromkeys(all_themes))[:4],
        "emotions": list(dict.fromkeys(all_emotions))[:5],
        "notable_quote": notable_quote,
        "templates": templates_found,
        # Phase 2A enrichment
        "cognitive_patterns": list(dict.fromkeys(all_cognitive_patterns))[:3],
        "defense_patterns": list(dict.fromkeys(all_defense_patterns))[:3],
        "avoidance_flags": list(dict.fromkeys(all_avoidance_flags))[:3],
        "growth_signals": list(dict.fromkeys(all_growth_signals))[:3],
        "social_quality": social_quality_readings[-1] if social_quality_readings else None,
        "ownership_avg": round(sum(ownership_readings) / len(ownership_readings), 1) if ownership_readings else None,
        "stress_sources": list(dict.fromkeys(stress_sources))[:3],
    }


def compute_tsb(strava_60d, today):
    # #490: shared TSS-like scale (walks count via the moving-time fallback) so this
    # fallback bands the same way as the computed_metrics value it stands in for.
    # ADR-104 (#2221): an EMPTY window is not "balanced form" — banister() returns 0.0
    # for no load, which compute_readiness turned into clamp(60+0×2)=60.
    if not strava_60d:
        return None
    _ctl, _atl, tsb = training_load.compute_ctl_atl_tsb(strava_60d, today)
    return tsb


def dedup_activities(activities):
    """Remove duplicate activities from multi-device Strava sync.

    When multiple devices (WHOOP, Garmin, Apple Watch) record the same workout,
    Strava stores each as a separate activity. This detects overlaps and keeps
    the richer record.

    Overlap = same sport_type AND start times within 15 minutes.
    Keep = prefer has-distance over no-distance, then longer duration.
    """
    if len(activities) <= 1:
        return activities

    def parse_start(a):
        s = a.get("start_date_local") or a.get("start_date") or ""
        try:
            # #1964: the canonical parser — handles Z/z and offsets, states the
            # naive-timestamp semantic (tz-less == UTC), never a local fork.
            return parse_iso_utc(str(s))
        except (ValueError, TypeError):
            return None

    def richness(a):
        score = 0
        dist = float(a.get("distance_meters") or 0)
        if dist > 0:
            score += 1000
        score += float(a.get("moving_time_seconds") or 0)
        if a.get("summary_polyline"):
            score += 500
        if a.get("average_cadence") is not None:
            score += 100
        return score

    indexed = [(i, a, parse_start(a)) for i, a in enumerate(activities)]
    indexed = [(i, a, t) for i, a, t in indexed if t is not None]
    indexed.sort(key=lambda x: x[2])

    remove = set()
    for j in range(len(indexed)):
        if j in remove:
            continue
        i_j, a_j, t_j = indexed[j]
        sport_j = (a_j.get("sport_type") or a_j.get("type") or "").lower()
        for k in range(j + 1, len(indexed)):
            if k in remove:
                continue
            i_k, a_k, t_k = indexed[k]
            sport_k = (a_k.get("sport_type") or a_k.get("type") or "").lower()
            if sport_j != sport_k:
                continue
            gap_min = abs((t_k - t_j).total_seconds()) / 60
            if gap_min > 15:
                break
            if richness(a_j) >= richness(a_k):
                remove.add(k)
                dev_drop = a_k.get("device_name", "?")
                dev_keep = a_j.get("device_name", "?")
            else:
                remove.add(j)
                dev_drop = a_j.get("device_name", "?")
                dev_keep = a_k.get("device_name", "?")
            logger.info("Dedup: " + sport_j + " overlap — kept " + dev_keep + ", dropped " + dev_drop)

    kept = [a for i, (_, a, _) in enumerate(indexed) if i not in remove]
    no_time = [a for a in activities if parse_start(a) is None]
    return kept + no_time


def compute_readiness(data):
    # Sleep 25% (not 30%) to stay aligned with daily_metrics_compute.compute_readiness
    # and the live MCP get_readiness_score model — keep all three in sync.
    components = []
    # Phase-3: the ONE chosen whoop (today-if-finalized else yesterday), so readiness
    # uses the same recovery the vitals block and narrative show (no 30-vs-86 split).
    primary_whoop = data.get("primary_whoop") or data.get("whoop_today") or data.get("whoop")
    recovery = safe_float(primary_whoop, "recovery_score")
    if recovery is not None:
        components.append(("recovery", float(recovery), 0.40))
    sleep_score = safe_float(data.get("sleep"), "sleep_score")
    if sleep_score is not None:
        components.append(("sleep", float(sleep_score), 0.25))
    hrv_7d = data["hrv"].get("hrv_7d")
    hrv_30d = data["hrv"].get("hrv_30d")
    if hrv_7d and hrv_30d and hrv_30d > 0:
        hrv_score = clamp(round((hrv_7d / hrv_30d - 0.75) * 200))
        components.append(("hrv_trend", hrv_score, 0.20))
    tsb = data.get("tsb")
    if tsb is not None:
        components.append(("tsb", clamp(round(60 + tsb * 2)), 0.10))
    if not components:
        return None, "gray"
    tw = sum(w for _, _, w in components)
    score = round(sum(v * w for _, v, w in components) / tw)
    if score >= 80:
        return score, "green"
    if score >= 60:
        return score, "yellow"
    return score, "red"
