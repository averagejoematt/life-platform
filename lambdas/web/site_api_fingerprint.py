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
    "warming_up": (
        "fewer than 3 measured metrics were fed to this mark ⇒ a dashed, staged core. For the living "
        "attempt this is genuine low-n (honest, never a faked field); for a sealed attempt on the Wall "
        "it's display policy (ADR-058) hiding that day's real metrics, not their absence — see /api/wall's note."
    ),
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
    """1-indexed Day-N relative to genesis — 0 for any pre-genesis date (#1824).

    Mirrors `lambdas/constants.day_n()`'s documented contract exactly ("Returns 0
    for pre-genesis dates"); this used to clamp to 1 instead, so a countdown day
    (today < genesis) reported the SAME day_number: 1 as the real Day 1 tomorrow —
    a public-API surface disagreeing with the platform's own canonical counter."""
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        g = datetime.strptime(genesis, "%Y-%m-%d")
        delta = (d - g).days
        return delta + 1 if delta >= 0 else 0
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
    """Ordered (cycle, genesis, end_date, is_current, staged) — each attempt's true
    lifespan. An attempt ends the day before the next cycle's genesis; the last cycle
    runs to today, UNLESS its genesis is still in the future — a reset can stage a
    cycle a day or more ahead of its start (the standard #931/#939 pre-start pattern).
    That staged cycle hasn't begun: it is neither alive (no day has happened yet) nor
    dead (#1822 — a future genesis is not an "ended" date); `staged=True` marks it so
    callers can render a third, upcoming state instead of forcing alive/dead."""
    # Imported here (not at module load) so tests can patch site_api_data.CYCLE_GENESES.
    from web.site_api_data import CYCLE_GENESES

    today = _today()
    items = sorted(CYCLE_GENESES.items())  # [(cycle, genesis), ...]
    spans = []
    for i, (cycle, genesis) in enumerate(items):
        is_last = i == len(items) - 1
        staged = is_last and genesis > today  # #1822: staged, not dead — hasn't begun
        if is_last:
            end = today if genesis <= today else genesis
        else:
            nxt = datetime.strptime(items[i + 1][1], "%Y-%m-%d")
            end = (nxt - timedelta(days=1)).strftime("%Y-%m-%d")
            if end < genesis:  # cycles a day apart ⇒ a one-day attempt
                end = genesis
        alive = is_last and genesis <= today
        spans.append((cycle, genesis, end, alive, staged))
    return spans


def handle_wall():
    """GET /api/wall — the all-attempts field. Real per-day marks for the living cycle;
    honest date-only 'warming up' marks for sealed past cycles; a staged, dayless entry
    for a cycle whose genesis hasn't arrived yet (#1822)."""
    today = _today()
    spans = _cycle_spans()
    current_genesis = spans[-1][1] if spans else EXPERIMENT_START
    live_index = _metrics_index(current_genesis, today) if current_genesis <= today else {}

    attempts = []
    for cycle, genesis, end, alive, staged in spans:
        if staged:
            # The day hasn't happened — no day cell to draw, no "ended" date (it
            # hasn't started, let alone finished). #1822.
            attempts.append(
                {
                    "cycle": cycle,
                    "genesis": genesis,
                    "ended": None,
                    "day_count": 0,
                    "alive": False,
                    "staged": True,
                    "days_until_start": (datetime.strptime(genesis, "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days,
                    "days": [],
                }
            )
            continue
        days = []
        cur = datetime.strptime(genesis, "%Y-%m-%d")
        last = datetime.strptime(end, "%Y-%m-%d")
        dn = 1
        while cur <= last:
            ds = cur.strftime("%Y-%m-%d")
            # #1818: sealed-cycle metrics are POLICY-hidden (ADR-058 phase filter),
            # not absent — DDB retains them (raw_timeseries). {} here means "not
            # displayed for this sealed attempt", never "no data exists"; the note
            # below and the front-end legend must say exactly that, not "honest
            # low-data" (which implies the metrics themselves don't exist).
            metrics = live_index.get(ds, {}) if alive else {}
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
                "staged": False,
                "days": days,
            }
        )

    # #1822: living_cycle must agree with the attempt flags — only report a cycle as
    # "living" when some attempt actually carries alive=True. Pre-start, nothing is
    # alive yet (the staged cycle hasn't begun), so this is None, not the staged
    # cycle's number.
    living_cycle = next((a["cycle"] for a in attempts if a["alive"]), None)

    return _ok(
        {
            "wall": {
                "attempts": attempts,
                "attempt_count": len(attempts),
                "living_cycle": living_cycle,
                # #1818: sealed marks are a function of the DATE ALONE (display
                # policy hides that day's real metrics) — the archive still holds
                # them. Never claim the underlying data is absent.
                "note": (
                    "Each mark for the living attempt is a pure function of that day's real metrics. "
                    "Sealed attempts render date-only marks: their archive metrics are retained in the "
                    "database but not displayed here, so the low-data appearance is a display choice, "
                    "not missing data. A staged attempt (genesis not yet reached) has no marks at all — "
                    "no day has happened."
                ),
            }
        },
        cache_seconds=3600,
    )
