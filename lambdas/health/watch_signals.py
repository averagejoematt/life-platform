"""health/watch_signals.py — the Apple Watch's signals for coaches and tools, labelled by source (#4979).

WHY THIS EXISTS

Playbook step 7 (docs/NEW_SIGNAL_PLAYBOOK.md) for the Apple Watch Ultra 4 (epic #4967): the watch's
daily fields (#4970) and its own night (#4971) land in the `apple_health` partition, but no coach and no
MCP tool read them. This module is the ONE assembly every consumer calls, so the coach fact pack, the
analyzer, the public ask and the owner's MCP tools describe the same watch the same way.

WHAT IT GUARANTEES

  * Every value carries its SOURCE label ("Apple Watch", "Whoop") and the date of the row that supplied
    it (`as_of`, the #2667 contract) — never a bare number implied to be today's.
  * Where Whoop and the watch measure the same metric (resting HR, HRV, sleep duration) both readings are
    reported, labelled, through the ONE read-side resolver (`common.metric_truth.dual_wear`). The blend
    rule lives there, not here: owner ruling 2026-10-23 "track both, then blend" (no blend until the #4974
    agreement study rules one per metric) and "HRV is never blended" (Whoop RMSSD vs the watch's SDNN).
  * Privacy by AUDIENCE, decided from `privacy.field_tiers` at runtime — this module restates no tier:
      PUBLIC    a surface whose output can reach a reader (the expert analyzer, /api/ask): publishable
                tiers only (`is_publishable`) — so the watch's INTERNAL cardio recovery / HRV / resting HR
                never reach it (#4980 owns any publication ruling);
      OWNER_AI  an AI narrative context on an owner channel (the owner's Telegram coach thread): adds the
                INTERNAL fields, never an OWNER_ONLY one (field_tiers: "NEVER quoted into an AI narrative
                context") — so the watch's sleep, SpO2, wrist temperature and breathing disturbances are
                absent from every fact pack;
      OWNER_TOOL the owner's own MCP surface: every field, returned field-selectively (the #2809
                distinction) — the owner-only fields are derived from FIELD_TIERS, never listed here.
  * Heart-RHYTHM data (ECG, notifications, AFib burden, medications — the #4972 owner-only channel in the
    clinical partition) is never read by this module at all.

Pure — no boto3, no clock: the caller hands in the rows it read and the Pacific `today`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable, Mapping, Optional

from common import metric_truth as mt
from privacy.field_tiers import TIER_OWNER_ONLY, fields_at_tier, is_publishable, tier_of

APPLE = "apple_health"
WHOOP = "whoop"
WATCH_LABEL = "Apple Watch"

PUBLIC = "public"
OWNER_AI = "owner_ai"
OWNER_TOOL = "owner_tool"
AUDIENCES = (PUBLIC, OWNER_AI, OWNER_TOOL)

#: The trailing window a fact line summarises (dates [today − 6, today]).
WINDOW_DAYS = 7
#: The window the VO2 max arc is drawn over (a slow estimate; a week shows nothing).
ARC_DAYS = 30


@dataclass(frozen=True)
class Signal:
    """One watch field a coach or tool reads: the stored field, its words and the domains it serves."""

    key: str
    field: str
    label: str
    unit: str
    domains: tuple[str, ...]
    agg: str = "mean"  # "mean" over the window, or "latest" (an estimate that moves slowly)


# The watch's signals (#4970 field names; docs/SCHEMA.md "Apple Watch daily metrics (#4970)").
# "Running form": HAE's running dynamics are not mapped yet (#4969 owns the raw diff), so the form
# signals the platform HAS are the watch's gait readings, labelled as walking gait — not running.
SIGNALS: tuple[Signal, ...] = (
    Signal("cardio_recovery", "cardio_recovery_bpm_apple", "cardio recovery (HR drop one minute after exercise)", "bpm", ("training",)),
    Signal("daylight", "daylight_minutes_apple", "time in daylight", "min/day", ("sleep", "training")),
    Signal("audio", "environmental_audio_db_apple", "environmental audio exposure", "dB", ("sleep",)),
    Signal("exercise_minutes", "exercise_minutes_apple", "exercise minutes", "min/day", ("training",)),
    Signal("walking_speed", "walking_speed_mph", "walking gait: speed", "mph", ("training",)),
    Signal("step_length", "walking_step_length_in", "walking gait: step length", "in", ("training",)),
    Signal("asymmetry", "walking_asymmetry_pct", "walking gait: asymmetry", "%", ("training",)),
    Signal("double_support", "walking_double_support_pct", "walking gait: double support", "%", ("training",)),
    Signal("steadiness", "walking_steadiness_pct", "walking steadiness", "%", ("training",), agg="latest"),
)

#: The metrics both wrists measure, through the resolver's dual-wear read (registry facet keys).
DUAL_WEAR_METRICS: tuple[str, ...] = (mt.RHR_BPM, mt.HRV_MS, mt.SLEEP_HOURS)
_DUAL_WEAR_WORDS = {mt.RHR_BPM: "resting heart rate", mt.HRV_MS: "HRV", mt.SLEEP_HOURS: "sleep duration"}
_DUAL_WEAR_DOMAINS = {mt.RHR_BPM: ("sleep", "training"), mt.HRV_MS: ("sleep", "training"), mt.SLEEP_HOURS: ("sleep",)}


def allowed(source: str, field: str, audience: str) -> bool:
    """May `source`.`field` reach `audience`? The ONE privacy predicate here, read from field_tiers."""
    if audience not in AUDIENCES:
        raise ValueError(f"unknown audience {audience!r}")
    tier = tier_of(source, field)
    if audience == PUBLIC:
        return is_publishable(tier)
    if audience == OWNER_AI:
        return tier != TIER_OWNER_ONLY
    return True


def owner_only_watch_fields() -> tuple[str, ...]:
    """The apple_health owner-only fields an owner TOOL may return field-selectively — derived from
    FIELD_TIERS (the `_rd_` reading maps are internal bookkeeping, never a value)."""
    return tuple(sorted(f for f in fields_at_tier(TIER_OWNER_ONLY, APPLE) if not f.startswith("_")))


# ── row helpers ───────────────────────────────────────────────────────────────


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _date(row: Mapping[str, Any]) -> Optional[str]:
    sk = str(row.get("sk") or "")
    if sk.startswith("DATE#") and len(sk) > 15:
        return None  # a #WORKOUT# (or other) sub-row never answers for the day
    d = row.get("date") or (sk[5:15] if sk.startswith("DATE#") else None)
    return str(d)[:10] if d else None


def day_rows(rows: Optional[Iterable[Mapping[str, Any]]]) -> dict[str, Mapping[str, Any]]:
    """`{date: day row}` (sub-rows dropped; the last day row per date wins)."""
    out: dict[str, Mapping[str, Any]] = {}
    for r in rows or ():
        d = _date(r)
        if d:
            out[d] = r
    return out


def _window_start(today: str, days: int) -> str:
    return (datetime.strptime(today[:10], "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")


def _series(by_date: Mapping[str, Mapping[str, Any]], field: str, start: str, today: str) -> list[tuple[str, float]]:
    """(date, value) for every day in [start, today] whose row carries a numeric `field`."""
    return [(d, v) for d, r in sorted(by_date.items()) if start <= d <= today and (v := _num(r.get(field))) is not None]


# ── the watch's own signals ────────────────────────────────────────────────────


def summarize(sig: Signal, by_date: Mapping[str, Mapping[str, Any]], today: str, days: int = WINDOW_DAYS) -> Optional[dict[str, Any]]:
    """One signal over the trailing window: latest value + its date, the window mean and its n.
    None when no day in the window carries a reading (absence stays absent, ADR-104)."""
    pts = _series(by_date, sig.field, _window_start(today, days), today)
    if not pts:
        return None
    as_of, latest = pts[-1]
    vals = [v for _, v in pts]
    return {
        "key": sig.key,
        "label": sig.label,
        "source": WATCH_LABEL,
        "field": sig.field,
        "unit": sig.unit,
        "latest": round(latest, 1),
        "as_of": as_of,
        "mean": round(sum(vals) / len(vals), 1),
        "n_days": len(vals),
        "window_days": days,
        "agg": sig.agg,
    }


def signal_summaries(apple_rows, today: str, *, audience: str, domain: Optional[str] = None) -> list[dict[str, Any]]:
    """Every watch signal `audience` may see (optionally one `domain`'s), summarised, absent ones omitted."""
    by_date = day_rows(apple_rows)
    out = []
    for sig in SIGNALS:
        if (domain and domain not in sig.domains) or not allowed(APPLE, sig.field, audience):
            continue
        s = summarize(sig, by_date, today)
        if s:
            out.append(s)
    return out


def _label(source: Optional[str]) -> str:
    """The instrument label a reader sees: the watch's Tier-2 fields are Apple-DEVICE readings."""
    if source == APPLE:
        return WATCH_LABEL
    from ingestion.source_registry import source_label

    return source_label(source or "") or str(source)


def vo2_arc(rows_by_source: Mapping[str, Iterable[Mapping[str, Any]]], today: str, days: int = ARC_DAYS) -> Optional[dict[str, Any]]:
    """The VO2 max estimate over `days` through the resolver (Apple Watch, else Garmin's history), each
    point carrying its source; says when the arc spans more than one device (two vendors' estimators)."""
    start = _window_start(today, days)
    pts = [(d, r) for d, r in sorted(mt.resolve_by_date(mt.VO2_MAX, rows_by_source).items()) if start <= d <= today and r.value is not None]
    if not pts:
        return None
    sources = sorted({_label(r.source) for _, r in pts if r.source})
    first_d, first = pts[0]
    last_d, last = pts[-1]
    return {
        "key": "vo2_max",
        "label": "VO2 max (device estimate)",
        "unit": "ml/kg/min",
        "latest": round(float(last.value or 0.0), 1),
        "as_of": last_d,
        "latest_source": _label(last.source),
        "first": round(float(first.value or 0.0), 1),
        "first_date": first_d,
        "change": round(float(last.value or 0.0) - float(first.value or 0.0), 1),
        "n_points": len(pts),
        "sources": sources,
        "mixed_devices": len(sources) > 1,
        "window_days": days,
    }


# ── both wrists ───────────────────────────────────────────────────────────────


def dual_wear_night(metric: str, rows_by_source: Mapping[str, Iterable[Mapping[str, Any]]], today: str, *, audience: str):
    """The newest date in the window on which ANY instrument has a reading for `metric`, with every
    reading `audience` may see (labelled) and the resolver's blend verdict. None when nothing reads."""
    start = _window_start(today, WINDOW_DAYS)
    by_date = mt.dual_wear_by_date(metric, rows_by_source)
    for d in sorted(by_date, reverse=True):
        if not (start <= d <= today):
            continue
        dw = by_date[d]
        readings = [r.as_dict() for r in dw.readings if r.value is not None and allowed(r.source, r.field, audience)]
        if readings:
            return {
                "metric": metric,
                "label": _DUAL_WEAR_WORDS.get(metric, metric),
                "as_of": d,
                "readings": readings,
                "blend": {"state": dw.blend, "value": dw.blend_value, "reason": dw.blend_reason},
            }
    return None


def dual_wear_nights(rows_by_source, today: str, *, audience: str, domain: Optional[str] = None) -> list[dict[str, Any]]:
    """`dual_wear_night` for every dual-wear metric (optionally one domain's)."""
    out = []
    for metric in DUAL_WEAR_METRICS:
        if domain and domain not in _DUAL_WEAR_DOMAINS[metric]:
            continue
        night = dual_wear_night(metric, rows_by_source, today, audience=audience)
        if night:
            out.append(night)
    return out


# ── renderers ─────────────────────────────────────────────────────────────────


def _fmt(v: Any) -> str:
    f = float(v)
    return f"{f:.0f}" if abs(f) >= 100 else f"{f:.1f}"


def signal_line(s: Mapping[str, Any]) -> str:
    if s["agg"] == "latest" or s["n_days"] == 1:
        return f"{s['source']} {s['label']}: {_fmt(s['latest'])} {s['unit']} (as of {s['as_of']})."
    return (
        f"{s['source']} {s['label']}: {_fmt(s['mean'])} {s['unit']} mean over {s['n_days']} of the last "
        f"{s['window_days']} days; latest {_fmt(s['latest'])} (as of {s['as_of']})."
    )


def vo2_line(arc: Mapping[str, Any]) -> str:
    line = f"VO2 max estimate: {_fmt(arc['latest'])} {arc['unit']} ({arc['latest_source']}, as of {arc['as_of']})"
    if arc["n_points"] > 1:
        line += f"; {arc['change']:+.1f} since {arc['first_date']} over {arc['n_points']} estimates"
    if arc["mixed_devices"]:
        line += f" — the arc spans {', '.join(arc['sources'])}, two vendors' estimators, so the change is not one instrument's"
    return line + "."


def dual_wear_line(night: Mapping[str, Any]) -> str:
    parts = [f"{r['label']} {_fmt(r['value'])} {r['unit']}" for r in night["readings"]]
    line = f"{night['label'][:1].upper()}{night['label'][1:]} (night of {night['as_of']}): " + " · ".join(parts)
    blend = night["blend"]
    if blend["state"] == "active" and blend["value"] is not None:
        return line + f" · blended {_fmt(blend['value'])} (labelled blend, owner-ruled)."
    if blend["state"] == "never" and len(night["readings"]) > 1:
        return line + " — never blended: different statistics."
    if len(night["readings"]) > 1:
        return line + " — both kept, not blended (awaiting the 30-night agreement study)."
    return line + "."


def fact_lines(apple_rows, whoop_rows, today: str, *, audience: str, domain: str, garmin_rows=None) -> list[str]:
    """The watch lines for one coach domain's fact pack, every line dated and source-labelled.
    `audience` decides which fields may appear (OWNER_AI never carries an owner-only field)."""
    if audience == OWNER_TOOL:
        raise ValueError("fact_lines builds AI narrative context — OWNER_TOOL is not an AI audience")
    lines: list[str] = []
    rows_by_source = {WHOOP: list(whoop_rows or ()), APPLE: list(apple_rows or ())}
    lines += [dual_wear_line(n) for n in dual_wear_nights(rows_by_source, today, audience=audience, domain=domain)]
    if domain == "training":
        arc = vo2_arc({APPLE: rows_by_source[APPLE], "garmin": list(garmin_rows or ())}, today)
        if arc:
            lines.append(vo2_line(arc))
    lines += [signal_line(s) for s in signal_summaries(apple_rows, today, audience=audience, domain=domain)]
    return lines


def analyzer_block(apple_rows, today: str, domain: str, garmin_rows=None) -> dict[str, Any]:
    """The PUBLIC watch block for the expert analyzer's JSON data (its output is published):
    publishable fields only, each with its `as_of`; an empty `signals` list says the watch is silent."""
    block: dict[str, Any] = {
        "source": WATCH_LABEL,
        "signals": signal_summaries(apple_rows, today, audience=PUBLIC, domain=domain),
        "note": "Apple Watch readings, each dated by as_of; absent signals had no reading in the window.",
    }
    if domain == "training":
        block["vo2_max"] = vo2_arc({APPLE: list(apple_rows or ()), "garmin": list(garmin_rows or ())}, today)
    return block


#: The analyzer experts that receive a watch block, and the signal domain each reads.
ANALYZER_DOMAINS = {"training": "training", "sleep": "sleep"}


def with_analyzer_block(data: dict, read, today: str, start: Optional[str] = None) -> dict:
    """The expert analyzer's seam: `data` (one expert's gathered dict) with its PUBLIC `apple_watch`
    block attached when that expert reads the watch. `read(source, start, end)` is the analyzer's own
    day-row reader. Fail-soft: a read failure leaves `data` exactly as it was."""
    domain = ANALYZER_DOMAINS.get(str((data or {}).get("expert_key") or ""))
    if not domain:
        return data
    start = start or _window_start(today, ARC_DAYS)
    try:
        garmin = read("garmin", start, today) if domain == "training" else []
        data["apple_watch"] = analyzer_block(read(APPLE, start, today), today, domain, garmin_rows=garmin)
    except Exception:  # noqa: BLE001 — the analysis runs without the watch block, as before #4979
        pass
    return data


# ── the owner's MCP view (field-selective, owner-only fields included) ─────────


def owner_day(apple: Mapping[str, Any], whoop: Mapping[str, Any]) -> dict[str, Any]:
    """One day for the owner's tool: every watch signal + the owner-only watch fields (named from
    FIELD_TIERS), and each dual-wear metric with both instruments labelled and the blend verdict."""
    rows = {WHOOP: whoop or None, APPLE: apple or None}
    signals = {s.key: _num(apple.get(s.field)) for s in SIGNALS}
    owner_only = {f: apple.get(f) for f in owner_only_watch_fields() if apple.get(f) is not None}
    dual = {m: mt.dual_wear(m, rows).as_dict() for m in DUAL_WEAR_METRICS}
    vo2 = mt.resolve(mt.VO2_MAX, {APPLE: apple or None})
    return {
        "watch_signals": {k: v for k, v in signals.items() if v is not None},
        "vo2_max": {"value": vo2.value, "source": vo2.source} if vo2.value is not None else None,
        "owner_only": owner_only,
        "dual_wear": dual,
    }


def owner_view(apple_rows, whoop_rows, start: str, end: str) -> dict[str, Any]:
    """The owner's watch read over [start, end]: per-day labelled values and the trailing summaries."""
    a_by, w_by = day_rows(apple_rows), day_rows(whoop_rows)
    dates = sorted(d for d in set(a_by) | set(w_by) if start <= d <= end)
    days = [{"date": d, **owner_day(a_by.get(d) or {}, w_by.get(d) or {})} for d in dates]
    rows_by_source = {WHOOP: list(w_by.values()), APPLE: list(a_by.values())}
    return {
        "start_date": start,
        "end_date": end,
        "summaries": signal_summaries(apple_rows, end, audience=OWNER_TOOL),
        "dual_wear_latest": dual_wear_nights(rows_by_source, end, audience=OWNER_TOOL),
        "days": days,
        "days_with_watch_data": sum(1 for d in dates if d in a_by),
        "labels": {WHOOP: "Whoop", APPLE: WATCH_LABEL},
        "blend_rule": (
            "Both instruments are kept and labelled; a blended value appears only where the owner has ruled one per metric "
            "after the 30-night agreement study (#4974). HRV is never blended (Whoop RMSSD vs Apple Watch SDNN)."
        ),
        "privacy": "Owner channel: owner-only watch fields are included here and are never quoted into any AI narrative or public surface.",
    }
