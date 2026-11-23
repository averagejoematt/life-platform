"""brief_trends.py — daily variation is not the whole story: the compact brief's multi-week context (#6240, ruling 2026-11-23 #6241 §3).

On 23 November the compact lead said nothing moved beyond day-to-day variation while the 4-week weight trend ran
at about 3.9 lb a week. The daily thresholds (`content.brief_compact`) were right about the day and silent about the
weeks. This module adds the weeks, from verdicts the platform ALREADY computes — no new threshold, no medical one:

  STATE              SOURCE (existing)                                                         KIND
  ordinary           nothing below is open                                                      —
  trend              the 4-week regression rate (`health.weight_trend`: 28-day OLS + 80 % block-     trend
                     bootstrap CI, `weekly_rate_*`) against the owner's plan band
                     (`training.rate_band.band_view`: `governing_goal.rate_band_lb_per_wk`, lowered
                     by the clinical guidance cap — the VALUE is never printed here, #5074)
  concern            the anomaly detector's own SUSTAINED-streak verdict (`anomalies.sustained_metrics`)  concern
                     on a physiological metric (`brief_compact.ANOMALY_PHYSIOLOGICAL_FIELDS`) — open
                     until the detector stops reporting it
  unknown            the rate is `rate_provisional`, the band cannot be read, or the guidance cap     unknown
                     could not be read while the rate sits inside the band — no confident judgment

WORDING. A trend is a pattern, not today's number, and nothing here changes a target or proposes one: the owner's
targets are his ("do not automatically change my targets"). No line says safe, fine or healthy. The CI decides how
firm the words are: the whole likely range outside the band -> "has run faster/slower"; only the estimate outside ->
"may be running faster/slower".

CADENCE (no daily nagging). Each open item has a key and a signature. The full sentence is shown when the item OPENS
(the previous send did not carry it), when its signature CHANGES, and at least every `REMIND_DAYS` while it stays
open; every other day it is a few-word standing pointer. Read from the existing SEND# rows (`trend_notes`), no new store.

Pure module: no AWS, no clock, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from common.pacific_time import day_in_words, parse_day_key, shift_day_key

REMIND_DAYS = 7  # the low cadence while an item stays unresolved (owner ruling #6241 §3: "e.g. weekly")
TREND_WINDOW_WORDS = "over the past four weeks"  # health.weight_trend.weight_trajectory(window_days=28)


@dataclass
class TrendItem:
    key: str  # e.g. "weight_rate", "sustained:hrv"
    kind: str  # trend | concern | unknown
    sig: str  # what must change for a full re-statement
    full: str
    pointer: str
    lead: str  # the one qualified clause the lead carries
    mode: str = "full"  # full | pointer


def _f(v) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x else None


def weight_rate_item(status: dict, band: Optional[dict], band_error: bool) -> Optional[TrendItem]:
    """The 4-week loss rate against the plan band. None = ordinary (inside the band, confidently)."""
    rate = _f(status.get("weekly_rate_lbs"))
    if rate is None:
        return None
    if status.get("rate_provisional"):
        return TrendItem(
            "weight_rate",
            "unknown",
            "provisional",
            "The weight trend is still provisional, so whether it sits inside your plan's weekly band is not known yet.",
            "weight trend still provisional",
            "the weight trend is still provisional",
        )
    if not band:
        return TrendItem(
            "weight_rate",
            "unknown",
            "band_unread",
            "Your plan's weekly band could not be read, so the weight trend is shown without a comparison.",
            "weight trend not compared with your plan",
            "the weight trend could not be compared with your plan",
        )
    loss = -rate
    lo_raw, hi_raw = _f(status.get("rate_ci_low")), _f(status.get("rate_ci_high"))
    # in loss terms (positive = losing): the CI's slow and fast ends
    ci = sorted([-lo_raw, -hi_raw]) if lo_raw is not None and hi_raw is not None else None
    floor, ceiling = float(band["floor_lb_wk"]), float(band["ceiling_lb_wk"])
    if floor <= loss <= ceiling:
        if band_error:
            return TrendItem(
                "weight_rate",
                "unknown",
                "cap_unread",
                "The weight trend sits inside your plan's band, but one input to that band could not be read today.",
                "weight trend's band partly unread",
                "the weight trend's band was partly unreadable",
            )
        return None
    side = "faster" if loss > ceiling else "slower"
    firm = ci is not None and ((ci[0] > ceiling) if side == "faster" else (ci[1] < floor))
    verb = "has run " + side + " than" if firm else "may be running " + side + " than"
    full = (
        "Your weight trend " + verb + " your plan's weekly band " + TREND_WINDOW_WORDS + ": a pattern, not today's number. "
        "Nothing here changes your targets; adjusting is your call."
    )
    return TrendItem(
        "weight_rate",
        "trend",
        side + (":firm" if firm else ":possible"),
        full,
        "weight trend " + ("" if firm else "possibly ") + side + " than your plan's band",
        "the 4-week weight trend " + verb + " your plan's band",
    )


def sustained_items(anomaly: dict, physiological: frozenset) -> list:
    """The anomaly detector's sustained streaks on body signals — open concerns while it keeps reporting them."""
    out = []
    for m in (anomaly or {}).get("sustained_metrics") or []:
        if not isinstance(m, dict) or str(m.get("metric") or m.get("field") or "") not in physiological:
            continue
        label = str(m.get("label") or m.get("metric"))
        n = int(_f(m.get("streak_days")) or 0)
        direction = str(m.get("direction") or "")
        out.append(
            TrendItem(
                "sustained:" + str(m.get("metric") or m.get("field")),
                "concern",
                direction,
                label + " has been outside its usual range for " + str(n) + " days in a row (the anomaly detector's "
                "sustained flag). It is unresolved; it is a reading, not a diagnosis.",
                label + " still outside its usual range",
                label.lower() + " has been outside its usual range for " + str(n) + " days",
            )
        )
    return out


def _days_between(a: str, b: str) -> Optional[int]:
    da, db = parse_day_key(a), parse_day_key(b)
    return (db - da).days if da and db else None


def apply_cadence(items: list, prior_sends: list, data_day: str) -> list:
    """Set each item's mode from the previous sends' `trend_notes` ([{key, sig, full}]), oldest send first."""
    sends = sorted((r for r in prior_sends or [] if isinstance(r, dict)), key=lambda r: str(r.get("sk", "")))
    last = sends[-1] if sends else None
    for it in items:
        prev = next((n for n in (last or {}).get("trend_notes") or [] if isinstance(n, dict) and n.get("key") == it.key), None)
        if prev is None or str(prev.get("sig")) != it.sig:
            it.mode = "full"  # opens, or materially changed
            continue
        full_days = [
            str(r.get("sk", ""))[5:15] for r in sends for n in r.get("trend_notes") or [] if n.get("key") == it.key and n.get("full")
        ]
        gap = _days_between(max(full_days), data_day) if full_days else None
        it.mode = "full" if gap is None or gap >= REMIND_DAYS else "pointer"
        if it.mode == "pointer" and full_days:  # the brief that said it in full is read the morning after its data day
            it.pointer += ", said in full " + day_in_words(shift_day_key(max(full_days), 1), weekday=False)
    return items


def notes(items: list) -> list:
    """What the SEND# row records for tomorrow's cadence."""
    return [{"key": it.key, "sig": it.sig, "kind": it.kind, "full": it.mode == "full"} for it in items]


def state(items: list) -> str:
    """The day's context state: concern > trend > unknown > ordinary."""
    kinds = {it.kind for it in items}
    return next((k for k in ("concern", "trend", "unknown") if k in kinds), "ordinary")


def lead_clause(items: list) -> str:
    """One qualified clause naming the most important open item (the lead never sits silent over an open trend). On a
    day every open item is a pointer, the lead carries the pointers themselves — a few words, never the full warning."""
    ranked = sorted(items, key=lambda it: ("concern", "trend", "unknown").index(it.kind))
    if ranked and all(it.mode == "pointer" for it in ranked):
        return "; ".join(it.pointer for it in ranked)
    return ranked[0].lead if ranked else ""


def all_pointers(items: list) -> bool:
    return bool(items) and all(it.mode == "pointer" for it in items)
