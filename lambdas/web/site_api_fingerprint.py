"""site_api_fingerprint.py — #1379: the Daily Fingerprint + the Wall.

Two read-only GET endpoints that serve the CANONICAL mark rendered by the pure
`fingerprint` module (one source of truth — the cockpit masthead and the /data/wall/
field both inject the SVG this Python function produces, so what a reader sees is the
same byte-identical artifact AC1 pins):

  • GET /api/fingerprint[?date=YYYY-MM-DD]  — today's (or a past day's) mark + the
    metric→visual mapping the /method/ page documents.
  • GET /api/wall                            — the all-attempts field: every experiment
    cycle (CYCLE_GENESES) as a row of daily marks. The LIVING cycle carries real
    per-day metrics (earned glow); sealed past cycles carry date-only "warming up"
    marks — honest, never fabricated density (ADR-104), so you literally watch each
    attempt begin and die along the timeline.
"""

from datetime import datetime, timedelta

from web.fingerprint import build_mark, mark_to_svg
from web.site_api_common import EXPERIMENT_START, PT, _ok, _query_source

# The metric→visual contract, served on /api/fingerprint and mirrored on /method/fingerprint/.
MAPPING = {
    "recovery": "core size + node light (Whoop recovery %)",
    "sleep_hours": "node light (sleep duration, 8h = full)",
    "steps": "node light (daily steps)",
    "streak": "node light (tier-0 streak)",
    "hrv": "node light (HRV ms)",
    "strain": "node light (Whoop strain)",
    "glow": "earned only — the ember halo grows with the day's mean score; a thin or low day withholds it",
    "warming_up": "fewer than 3 measured metrics ⇒ a dashed, staged core (honest low-n, never a faked field)",
}

_WALL_CELL = 40  # per-day mark size on the wall (px; CSS may override — geometry is size-independent)
_MASTHEAD = 200  # the cockpit masthead / single-day mark size


def _metrics_index(start_date, end_date):
    """One batched read of the daily instruments over [start,end] → {date: metrics}.
    Mirrors handle_pulse_history's source selection (Whoop for recovery/sleep/HRV/
    strain; Apple Health then plausible-Garmin for steps) so the mark is seeded by the
    same real numbers the vitals page shows."""
    if start_date > end_date:
        return {}
    whoop = _query_source("whoop", start_date, end_date)
    ah = _query_source("apple_health", start_date, end_date)
    garmin = _query_source("garmin", start_date, end_date)

    steps = {}
    for h in ah:
        d = h.get("sk", "").replace("DATE#", "")[:10]
        if d and h.get("steps") and float(h["steps"]) > 0:
            steps[d] = max(steps.get(d, 0), int(float(h["steps"])))
    for g in garmin:
        d = g.get("sk", "").replace("DATE#", "")[:10]
        if d and g.get("steps") and float(g["steps"]) >= 1000 and d not in steps:
            steps[d] = int(float(g["steps"]))

    out = {}
    for w in whoop:
        d = w.get("sk", "").replace("DATE#", "")[:10]
        if not d:
            continue
        out.setdefault(d, {})
        if w.get("recovery_score") is not None:
            out[d]["recovery"] = float(w["recovery_score"])
        if w.get("sleep_duration_hours"):
            out[d]["sleep_hours"] = float(w["sleep_duration_hours"])
        if w.get("hrv"):
            out[d]["hrv"] = float(w["hrv"])
        if w.get("strain") is not None:
            out[d]["strain"] = float(w["strain"])
    for d, s in steps.items():
        out.setdefault(d, {})["steps"] = s
    return out


def _today():
    return datetime.now(PT).strftime("%Y-%m-%d")


def _day_number(date_str, genesis):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        g = datetime.strptime(genesis, "%Y-%m-%d")
        return max(1, (d - g).days + 1)
    except (ValueError, TypeError):
        return None


def handle_fingerprint(date=None):
    """GET /api/fingerprint[?date=YYYY-MM-DD]. Dateless ⇒ today (PT). Returns the
    day's canonical mark SVG + the metrics that seeded it + the mapping."""
    today = _today()
    date_str = (date or today)[:10]
    if date_str > today:
        date_str = today
    if date_str < EXPERIMENT_START:
        date_str = EXPERIMENT_START if EXPERIMENT_START <= today else today

    metrics = _metrics_index(date_str, date_str).get(date_str, {})
    mark = build_mark(date_str, metrics)
    return _ok(
        {
            "fingerprint": {
                "date": date_str,
                "day_number": _day_number(date_str, EXPERIMENT_START),
                "svg": mark_to_svg(mark, size=_MASTHEAD),
                "warming_up": mark["warming_up"],
                "earned_score": mark["earned_score"],
                "n": mark["n"],
                "metrics": {k: round(v, 2) if isinstance(v, float) else v for k, v in metrics.items()},
                "mapping": MAPPING,
            }
        },
        cache_seconds=900,
    )


def _cycle_spans():
    """Ordered (cycle, genesis, end_date, is_current) — each attempt's true lifespan.
    An attempt ends the day before the next cycle's genesis; the last cycle runs to
    today (or is pre-start if its genesis is in the future)."""
    # Imported here (not at module load) so tests can patch site_api_data.CYCLE_GENESES.
    from web.site_api_data import CYCLE_GENESES

    today = _today()
    items = sorted(CYCLE_GENESES.items())  # [(cycle, genesis), ...]
    spans = []
    for i, (cycle, genesis) in enumerate(items):
        is_last = i == len(items) - 1
        if is_last:
            end = today if genesis <= today else genesis  # pre-start: a single staged day
        else:
            nxt = datetime.strptime(items[i + 1][1], "%Y-%m-%d")
            end = (nxt - timedelta(days=1)).strftime("%Y-%m-%d")
            if end < genesis:  # cycles a day apart ⇒ a one-day attempt
                end = genesis
        spans.append((cycle, genesis, end, is_last and genesis <= today))
    return spans


def handle_wall():
    """GET /api/wall — the all-attempts field. Real per-day marks for the living cycle;
    honest date-only 'warming up' marks for sealed past cycles."""
    today = _today()
    spans = _cycle_spans()
    current_genesis = spans[-1][1] if spans else EXPERIMENT_START
    live_index = _metrics_index(current_genesis, today) if current_genesis <= today else {}

    attempts = []
    for cycle, genesis, end, alive in spans:
        days = []
        cur = datetime.strptime(genesis, "%Y-%m-%d")
        last = datetime.strptime(end, "%Y-%m-%d")
        dn = 1
        while cur <= last:
            ds = cur.strftime("%Y-%m-%d")
            metrics = live_index.get(ds, {}) if alive else {}  # sealed cycles: no retained vitality
            mark = build_mark(ds, metrics)
            days.append(
                {
                    "date": ds,
                    "day_number": dn,
                    "svg": mark_to_svg(mark, size=_WALL_CELL),
                    "warming_up": mark["warming_up"],
                    "earned": mark["earned_score"],
                }
            )
            cur += timedelta(days=1)
            dn += 1
        attempts.append(
            {
                "cycle": cycle,
                "genesis": genesis,
                "ended": None if alive else end,
                "day_count": len(days),
                "alive": alive,
                "days": days,
            }
        )

    return _ok(
        {
            "wall": {
                "attempts": attempts,
                "attempt_count": len(attempts),
                "living_cycle": spans[-1][0] if spans else None,
                "note": "Each mark is a pure function of that day's real metrics. Sealed attempts show honest low-data marks — the vitality of a wiped cycle is not fabricated.",
            }
        },
        cache_seconds=3600,
    )
