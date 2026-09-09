"""
tools_benchmark.py — BENCH-1 cut-benchmarking & regain firewall (PRIVATE).

One view-dispatched tool, get_benchmark (Anika; matches get_health / get_nutrition,
protects the ≤80-tool SIMP-1 budget). Reads the precomputed weight_episodes /
training_reference sources (written weekly by the episode-detect Lambda) via
query_source — exactly like computed_metrics — plus a live pace comparison from recent
withings/strava at call time (Viktor: the live comparison is NOT precomputed).

Hard guardrails (board acceptance criteria):
  - Descriptive + correlational only (Henning): every numeric block carries confidence
    + n; no causal language; small-n ⇒ confidence "low".
  - Forward framing (Nathan): output strings never tally failures or render a regain
    count — surface the forward signal (walking is X vs the ~Y/wk that worked).
  - PRIVATE: nothing here may surface to Elena Voss or any public surface.

BENCH-1.3 — dispatcher + pace view (this commit).
BENCH-1.4 — episodes + maintenance views (next commit).
"""

from datetime import datetime, timedelta

from common.pacific_time import pacific_today  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days

from mcp.core import get_profile, query_source

# Run gate from PROVEN_BLUEPRINT.md (owner-private: s3://matthew-life-platform/config/coaching/,
# #3043) — zero runs logged above ~240 lb in his own history.
#
# Numeric-anchor disclosure ACCEPTED, dated 2026-08-23 (#3045, DIL-012 residual): this
# threshold (and the ~0.79x regain-asymmetry ratio below) are functional code constants
# in a public repo. The quantity they anchor — the owner's weight ballpark — is itself
# TIER_OWNER_PUBLISHED (ADR-155: weight is deliberately published daily on /api/vitals),
# so the anchors disclose nothing beyond the consented surface. Revisit trigger: weight
# ever leaves the published set.
RUN_GATE_LB = 240.0

# The chronic training-load window (#3711). Rates computed over a shorter span
# are arithmetic, not measurements — see band_reference.VOLUME_FLOOR_DAYS for
# the provenance of the 21-28d range.
_CHRONIC_WINDOW_DAYS = 28

TRAINING_REFERENCE_SOURCE = "training_reference"
WEIGHT_EPISODES_SOURCE = "weight_episodes"

_BENCHMARK_DISCLAIMER = (
    "For personal health tracking only. Not medical advice. Descriptive of Matthew's own "
    "n=1 history (correlational, not causal). Consult a qualified healthcare provider before "
    "making health decisions based on this data."
)


# ── precomputed-source reads (newest-in-range, like computed_metrics) ───────────


def _today() -> str:
    return pacific_today()


def _read_reference() -> dict:
    """Newest training_reference singleton, or {} if episode-detect hasn't run yet."""
    recs = query_source(TRAINING_REFERENCE_SOURCE, "2000-01-01", _today())
    if not recs:
        return {}
    return max(recs, key=lambda r: r.get("date") or r.get("sk", ""))


def _read_episodes() -> list:
    """All weight_episodes, oldest→newest."""
    recs = query_source(WEIGHT_EPISODES_SOURCE, "2000-01-01", _today())
    return sorted(recs, key=lambda r: r.get("date") or r.get("sk", ""))


# ── live helpers (computed at call time) ───────────────────────────────────────


def _campaign_start() -> str:
    """The current experiment genesis — the campaign this delta is measuring.

    Read from the constant that ships in every bundle and that every reset
    regenerates (#3671's lesson: never a second hand-maintained copy).
    """
    try:
        from common.constants import EXPERIMENT_START_DATE

        return str(EXPERIMENT_START_DATE)
    except Exception:  # noqa: BLE001 - fail soft to a 28-day frame
        return (datetime.strptime(_today(), "%Y-%m-%d") - timedelta(days=_CHRONIC_WINDOW_DAYS)).strftime("%Y-%m-%d")


def _weight_on_or_after(day: str):
    """First weigh-in on/after `day`, or None. The campaign's starting weight."""
    rows = [r for r in query_source("withings", day, _today(), include_pilot=True) if r.get("weight_lbs") is not None]
    pts = sorted(((r.get("date") or r.get("sk", "").replace("DATE#", ""))[:10], float(r["weight_lbs"])) for r in rows)
    return pts[0][1] if pts else None


def _band_for(weight: float) -> str:
    base = int(weight // 10) * 10
    return f"{base}-{base + 9}"


def _current_weight_and_rate(end_date: str, days: int = 28) -> tuple:
    """(current_weight, rate_lb_wk [positive=losing], n_weighins) from recent withings.

    Rate is a least-squares slope over the window — robust to a single noisy weigh-in,
    unlike the old endpoint difference (two close-but-divergent readings used to
    manufacture an absurd rate, e.g. 12.75 lb/wk). Requires ≥3 weigh-ins spanning ≥7
    days; otherwise returns None (honest "unknown" beats a fabricated number).

    include_pilot=True (cross-phase): weight-change rate is physiological, not
    experiment-scoped. The default ADR-058 filter hides pre-genesis weigh-ins, which
    right after a reset leaves only a few post-genesis days of water-weight normalization
    (a steep transient, not a real rate). Like episode-detect, this reads the true recent
    trajectory across the phase boundary — the rate compares to LIFETIME proven history."""
    start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [r for r in query_source("withings", start, end_date, include_pilot=True) if r.get("weight_lbs") is not None]
    pts = sorted(((r.get("date") or r.get("sk", "").replace("DATE#", ""))[:10], float(r["weight_lbs"])) for r in rows)
    if not pts:
        return None, None, 0
    current = pts[-1][1]
    rate = None
    if len(pts) >= 3:
        d0 = datetime.strptime(pts[0][0], "%Y-%m-%d")
        xs = [(datetime.strptime(p[0], "%Y-%m-%d") - d0).days for p in pts]
        ys = [p[1] for p in pts]
        if (xs[-1] - xs[0]) >= 7:
            n = len(xs)
            xbar, ybar = sum(xs) / n, sum(ys) / n
            denom = sum((x - xbar) ** 2 for x in xs)
            if denom > 0:
                slope = sum((x - xbar) * (y - ybar) for x, y in zip(xs, ys)) / denom  # lb/day
                rate = round(-slope * 7.0, 2)  # positive when losing
    return current, rate, len(pts)


def _recent_walks_wk(end_date: str, days: int = 14) -> tuple:
    """(walks_per_week, n_strava_records) over the trailing window."""
    start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = query_source("strava", start, end_date)
    walks = 0
    for it in rows:
        acts = it.get("activities") if isinstance(it.get("activities"), list) else [it]
        for a in acts:
            st = (a.get("sport_type") or a.get("type") or "").lower().replace(" ", "").replace("_", "")
            if st in ("walk", "hike", "walking", "hiking"):
                walks += 1
    return round(walks / (days / 7.0), 2), len(rows)


def _proven_rate_at(curve: list, weight: float):
    """Local proven loss rate (lb/wk) at the matched weight, from the proven_curve.

    Clamps the lookup into the curve's weight range so a current weight just ABOVE the
    curve's heaviest sample (the common case at re-entry — the curve is rounded to 1dp,
    so 305.44 fell just past a 305.4 max and returned None → 'unknown') still resolves
    to the nearest segment instead of failing."""
    pts = sorted(curve, key=lambda p: p.get("days_from_start", 0))
    if len(pts) < 2:
        return None
    weights = [p.get("weight", 0) for p in pts]
    w = min(max(weight, min(weights)), max(weights))  # clamp into [curve min, curve max]
    for a, b in zip(pts, pts[1:]):
        lo, hi = sorted([a.get("weight", 0), b.get("weight", 0)])
        dd = b.get("days_from_start", 0) - a.get("days_from_start", 0)
        if lo <= w <= hi and dd > 0:
            return round((b.get("cum_lost", 0) - a.get("cum_lost", 0)) / dd * 7.0, 2)
    return None


def _pace_label(rate, proven_rate) -> str:
    if rate is None or proven_rate is None or proven_rate == 0:
        return "unknown"
    if rate >= proven_rate * 1.1:
        return "ahead"
    if rate <= proven_rate * 0.9:
        return "behind"
    return "on"


# ── views ──────────────────────────────────────────────────────────────────────


def _benchmark_pace(args: dict) -> dict:
    """BENCH-1.3 — live pace vs the proven trajectory at the current weight. Forward-framed."""
    end_date = args.get("date") or _today()
    ref = _read_reference()
    if not ref:
        return {"view": "pace", "status": "no training reference yet — episode-detect has not run", "_disclaimer": _BENCHMARK_DISCLAIMER}

    current_weight, rate, n_w = _current_weight_and_rate(end_date)
    if current_weight is None:
        return {"view": "pace", "status": "no recent weight data", "_disclaimer": _BENCHMARK_DISCLAIMER}

    band = _band_for(current_weight)
    band_data = (ref.get("bands") or {}).get(band, {})
    walks_proven = band_data.get("walks_wk")
    proven_rate = _proven_rate_at(ref.get("proven_curve") or [], current_weight)
    walks_current, n_walk = _recent_walks_wk(end_date)
    walk_gap = round(walks_proven - walks_current, 2) if (walks_proven is not None and walks_current is not None) else None
    run_gate_ok = current_weight <= RUN_GATE_LB
    n_ref = ref.get("n_episodes_with_covariates")

    # Forward-framed signal (Nathan): no failure tally — only what works next.
    bits = []
    if walks_proven is not None:
        bits.append(f"Walking is {walks_current}/wk vs the ~{walks_proven}/wk that worked at this weight last time.")
    if not run_gate_ok:
        bits.append(f"Running stays parked until ~240 lb (currently ~{round(current_weight)}); walking is the highest-leverage lever now.")
    else:
        bits.append("You're under the ~240 lb run gate — easy running can enter as joints allow.")

    return {
        "view": "pace",
        "date": end_date,
        "current": {
            "current_weight": round(current_weight, 1),
            "current_rate_lb_wk": round(rate, 2) if rate is not None else None,
            "walks_wk_current": walks_current,
            "confidence": "low",
            "n": n_w,
        },
        "proven": {
            "band": band,
            "proven_rate_at_weight": proven_rate,
            "walks_wk_proven": walks_proven,
            "confidence": "low",
            "n": n_ref,
        },
        "pace_vs_proven": _pace_label(rate, proven_rate),
        "walks_wk_current": walks_current,
        "walks_wk_proven": walks_proven,
        "walk_gap": walk_gap,
        "run_gate_ok": run_gate_ok,
        "signal": " ".join(bits),
        "_disclaimer": _BENCHMARK_DISCLAIMER,
    }


def _benchmark_episodes(args: dict) -> dict:
    """BENCH-1.4 — the weight_episodes ledger + loss/regain rate asymmetry. Read-only
    from the precomputed source; descriptive + correlational, confidence/n surfaced."""
    episodes = _read_episodes()
    if not episodes:
        return {"view": "episodes", "status": "no episodes yet — episode-detect has not run", "_disclaimer": _BENCHMARK_DISCLAIMER}

    losses = [e for e in episodes if e.get("type") == "loss"]
    regains = [e for e in episodes if e.get("type") == "regain"]

    def _mean_rate(eps):
        rates = [e["rate_lb_wk"] for e in eps if e.get("rate_lb_wk") is not None]
        return round(sum(rates) / len(rates), 2) if rates else None

    mean_loss = _mean_rate(losses)
    mean_regain = _mean_rate(regains)
    ratio = round(mean_regain / mean_loss, 2) if (mean_loss and mean_regain) else None

    return {
        "view": "episodes",
        "episodes": episodes,
        "summary": {
            "n_loss": len(losses),
            "n_regain": len(regains),
            "mean_loss_rate_lb_wk": mean_loss,
            "mean_regain_rate_lb_wk": mean_regain,
            # asymmetry: weight returns ~0.79x as fast as it left — the slow post-cut
            # drift never happens. Surfaced as a number, not a render string.
            "regain_to_loss_ratio": ratio,
            "confidence": "low",
            "n": len(episodes),
        },
        "_disclaimer": _BENCHMARK_DISCLAIMER,
    }


def _gate_signals() -> dict:
    """Victor's entry gates — consult get_metabolic_adaptation + get_deficit_sustainability.
    Defensive: thin data returns {'error': ...}; we surface availability, never block hard."""
    out = {}
    try:
        from mcp.tools_nutrition import _get_metabolic_adaptation, tool_get_deficit_sustainability

        ds = tool_get_deficit_sustainability({})
        out["deficit_sustainability"] = {"available": "error" not in ds, "note": ds.get("error")} if isinstance(ds, dict) else {}
        ma = _get_metabolic_adaptation({})
        out["metabolic_adaptation"] = {"available": "error" not in ma, "note": ma.get("error")} if isinstance(ma, dict) else {}
    except Exception as e:  # noqa: BLE001 — gates are advisory; never break the firewall view
        out["gate_error"] = str(e)
    return out


def _benchmark_maintenance(args: dict) -> dict:
    """BENCH-1.4 — the regain firewall. Only meaningful post-trough / near goal. Compares
    current rolling walk volume to the proven floor + the post-trough decay signature that
    preceded past dips. Support, never indictment (Nathan): forward signal, no failure tally."""
    end_date = args.get("date") or _today()
    ref = _read_reference()
    if not ref:
        return {
            "view": "maintenance",
            "status": "no training reference yet — episode-detect has not run",
            "_disclaimer": _BENCHMARK_DISCLAIMER,
        }

    current_weight, _rate, _n = _current_weight_and_rate(end_date)
    profile = get_profile()
    goal = profile.get("goal_weight_lbs")

    # Gate: the firewall activates near goal / post-trough. In the loss phase it just
    # points back to the walking engine (forward, supportive).
    near_goal = goal is not None and current_weight is not None and (current_weight - float(goal)) <= 25.0
    if not near_goal:
        return {
            "view": "maintenance",
            "applicable": False,
            "current_weight": round(current_weight, 1) if current_weight is not None else None,
            "goal_weight": float(goal) if goal is not None else None,
            "signal": "The maintenance firewall activates near goal weight — right now you're in the proven-loss phase. Keep the easy walking engine on (see view=pace).",
            "_disclaimer": _BENCHMARK_DISCLAIMER,
        }

    # Near goal: compare 4-week rolling walk volume to the proven floor + the post-trough
    # decay signature (the easy-volume level that easy-volume historically dropped toward).
    walks_current, _ = _recent_walks_wk(end_date, days=28)
    band = _band_for(current_weight)
    proven_floor = ((ref.get("bands") or {}).get(band, {}) or {}).get("walks_wk")
    eps = _read_episodes()
    pt = [
        e.get("post_trough_8wk", {}).get("walks_wk")
        for e in eps
        if e.get("type") == "loss" and isinstance(e.get("post_trough_8wk"), dict) and e["post_trough_8wk"].get("walks_wk") is not None
    ]
    post_trough_signature = round(sum(pt) / len(pt), 2) if pt else None
    firewall_ok = walks_current is not None and proven_floor is not None and walks_current >= proven_floor * 0.8

    bits = []
    if proven_floor is not None:
        bits.append(f"Easy walking is {walks_current}/wk; the proven floor at this weight is ~{proven_floor}/wk.")
    if post_trough_signature is not None:
        bits.append(
            f"The easy-volume dip toward ~{post_trough_signature}/wk is the pattern to stay ahead of — keep the walking on as the scale settles."
        )

    return {
        "view": "maintenance",
        "applicable": True,
        "date": end_date,
        "current_weight": round(current_weight, 1) if current_weight is not None else None,
        "walks_wk_current": walks_current,
        "proven_floor_walks_wk": proven_floor,
        "post_trough_signature_walks_wk": post_trough_signature,
        "firewall_ok": firewall_ok,
        "gates": _gate_signals(),
        "signal": " ".join(bits),
        "confidence": "low",
        "n": len(eps),
        "_disclaimer": _BENCHMARK_DISCLAIMER,
    }


def _recent_volume(end_date: str, days: int = 28) -> dict:
    """Trailing walking + lifting volume, in the same units the bands carry (#3710).

    28 days matches the chronic window the volume floor is derived from, so
    "now" and "then" are measured with the same denominator rather than one
    being a 14-day slice compared against a month.
    """
    start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    weeks = days / 7.0
    miles = hours = 0.0
    bpm: list = []
    for it in query_source("strava", start, end_date):
        acts = it.get("activities") if isinstance(it.get("activities"), list) else [it]
        for a in acts:
            st = (a.get("sport_type") or a.get("type") or "").lower().replace(" ", "").replace("_", "")
            if st not in ("walk", "hike", "walking", "hiking"):
                continue
            miles += float(a.get("distance_miles") or 0.0)
            hours += float(a.get("moving_time_seconds") or 0.0) / 3600.0
            if a.get("average_heartrate"):
                bpm.append(float(a["average_heartrate"]))
    return {
        "window_days": days,
        "walk_mi_wk": round(miles / weeks, 2),
        "walk_hr_wk": round(hours / weeks, 2),
        "walk_bpm": round(sum(bpm) / len(bpm)) if bpm else None,
        "n_walk_bpm": len(bpm),
    }


def _ratio(now, then):
    """`now` as a fraction of `then`, or None when the comparison is undefined."""
    try:
        if then in (None, 0) or now is None:
            return None
        return round(float(now) / float(then), 2)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _benchmark_prescription(args: dict) -> dict:
    """What was he doing at a comparable bodyweight, and is it citable? (#3710)

    The join the night-before authoring path was missing. `get_benchmark` has
    been registered since BENCH-1 and NOTHING in the training path ever called
    it; the daily-debrief skill pulls 14 tools and not one carries a heart rate,
    which is why the coach hedged about target HR on 2026-09-07.

    Two tables, deliberately, and they are not interchangeable:
      proven_target  — from days inside a detected LOSS episode. The target.
      current_typical — from all history in the band he is in now. At his
                        current weight that IS the period he is trying to
                        escape, so it is the baseline, never the prescription.

    The gap between them is the useful number, and #3711 ranks it.
    """
    from training.band_reference import resolve_band

    end_date = args.get("date") or _today()
    ref = _read_reference()
    if not ref:
        return {
            "applicable": False,
            "reason": "episode-detect has not written a training_reference yet",
            "_disclaimer": _BENCHMARK_DISCLAIMER,
        }

    if int(ref.get("reference_schema") or 1) < 2:
        return {
            "applicable": False,
            "reason": (
                "training_reference is v1 (no proven_bands, no per-band n). This is a STALE "
                "REFERENCE, not a finding about his history — episode-detect needs redeploying "
                "and re-running before this view can answer."
            ),
            "reference_schema": int(ref.get("reference_schema") or 1),
            "derived_at": ref.get("derived_at"),
            "_disclaimer": _BENCHMARK_DISCLAIMER,
        }

    weight, rate, n_wi = _current_weight_and_rate(end_date)
    if weight is None:
        return {
            "applicable": False,
            "reason": "no recent weigh-in — cannot resolve a comparable period",
            "_disclaimer": _BENCHMARK_DISCLAIMER,
        }

    proven = resolve_band(weight, ref.get("proven_bands"))
    typical = resolve_band(weight, ref.get("bands"))
    now = _recent_volume(end_date)

    out: dict = {
        "applicable": True,
        "date": end_date,
        "current_weight": round(weight, 1),
        "current_rate_lb_wk": rate,
        "n_weighins_28d": n_wi,
        "current_typical": None,
        "proven_target": None,
        "now": now,
        "gap": {},
        # ADR-104 — stated on every output, not inferred from its absence.
        "intake_comparable": False,
        "intake_note": (
            "Training and activity only. There is NO nutrition data for the prior cut — "
            "MacroFactor begins 2025-11-24, seven months after it ended — so intake, the "
            "dominant lever in weight change, cannot be compared to what worked."
        ),
        "confidence": "low",
        "_disclaimer": _BENCHMARK_DISCLAIMER,
    }

    if typical:
        out["current_typical"] = {
            "band": typical["band"],
            "walk_mi_wk": typical.get("walk_mi_wk"),
            "walk_hr_wk": typical.get("walk_hr_wk"),
            "walk_bpm": typical.get("walk_bpm"),
            "sets_wk": typical.get("sets_wk"),
            "n_days": typical.get("n_days"),
            "window": typical.get("window"),
            "_role": "baseline — what he has typically done at this weight, NOT a target",
        }

    if not proven:
        out["proven_target"] = None
        out["signal"] = (
            f"No comparable period from a losing phase within reach of {round(weight, 1)} lb. "
            "Nothing to prescribe from — say so rather than substituting the current band."
        )
        return out

    ev = proven.get("evidence") or {}
    citable = bool(ev.get("volume_ok"))
    out["proven_target"] = {
        "band": proven["band"],
        "band_distance_lb": proven["band_distance_lb"],
        "exact": proven["exact"],
        "walk_mi_wk": proven.get("walk_mi_wk"),
        "walk_hr_wk": proven.get("walk_hr_wk"),
        "target_walk_bpm": proven.get("walk_bpm"),
        "sets_wk": proven.get("sets_wk"),
        "tonnage_lb_wk": proven.get("tonnage_lb_wk"),
        "top_kg_by_movement": proven.get("top_kg_by_movement"),
        "window": proven.get("window"),
        "cardio_hr_wk": proven.get("cardio_hr_wk"),
        "cycle_hr_wk": proven.get("cycle_hr_wk"),
        # #3717 — present only when the owner has attested to training that was
        # never captured. It is NEVER added to the measured figures above; a
        # renderer must show it as a separate, labelled line or not at all.
        "attested": proven.get("attested"),
        "measurement_is_a_floor": bool(proven.get("attested")),
        "n_days": proven.get("n_days"),
        "n_effective": ev.get("n_effective"),
        "n_weighins": proven.get("n_weighins"),
        "evidence_tier": ev.get("tier"),
        "volume_citable": citable,
        "rate_assertable": bool(ev.get("rate_ok")),
        "floor_provenance": ev.get("floor_provenance"),
        "_role": ("target" if citable else "descriptive only — below the volume evidence floor"),
    }
    out["confidence"] = ev.get("tier") or "low"
    out["gap"] = {
        "walk_mi_wk_ratio": _ratio(now["walk_mi_wk"], proven.get("walk_mi_wk")),
        "walk_hr_wk_ratio": _ratio(now["walk_hr_wk"], proven.get("walk_hr_wk")),
        "walk_mi_wk_delta": (
            round((proven.get("walk_mi_wk") or 0) - now["walk_mi_wk"], 2) if proven.get("walk_mi_wk") is not None else None
        ),
    }

    dist = proven["band_distance_lb"]
    where = "at this weight" if proven["exact"] else f"{dist} lb lighter"
    if citable:
        out["signal"] = (
            f"Walking {where} ran {proven.get('walk_mi_wk')} mi/wk "
            f"({proven.get('walk_hr_wk')} hr/wk @ {proven.get('target_walk_bpm') or proven.get('walk_bpm')} bpm) "
            f"during a losing phase; the trailing 28d is {now['walk_mi_wk']} mi/wk."
        )
    else:
        out["signal"] = (
            f"The nearest losing-phase period is {proven['band']} ({where}), and it does not clear the "
            f"volume evidence floor — {ev.get('n_effective')} effective days against "
            f"{ev.get('volume_floor_days')}. Citable as description ({proven.get('walk_mi_wk')} mi/wk), "
            "not as a target."
        )
    return out


def _campaign_day_n(curve: list, day_n: int):
    """The proven curve's cumulative loss at day N (linear between samples)."""
    pts = sorted(((int(float(p.get("days_from_start") or 0)), float(p.get("cum_lost") or 0.0)) for p in curve or []))
    if not pts:
        return None
    if day_n <= pts[0][0]:
        return pts[0][1]
    if day_n >= pts[-1][0]:
        return pts[-1][1]
    for (d0, c0), (d1, c1) in zip(pts, pts[1:]):
        if d0 <= day_n <= d1:
            if d1 == d0:
                return c1
            return round(c0 + (c1 - c0) * (day_n - d0) / (d1 - d0), 1)
    return None


def _benchmark_campaign(args: dict) -> dict:
    """Is this campaign tracking the one that worked — and WHICH lever explains it? (#3711)

    Reporting that weight is behind is not actionable. Ranking the levers by how
    far each sits below its proven value is: it turns "you are behind" into
    "walking is at 10% of the volume that worked, and it is the furthest-below
    lever." That ranking is the whole output.

    Windows shorter than the chronic window are labelled as artifacts rather
    than printed as rates — three days over 0.43 weeks reads as 4.67 lift
    days/wk, which is arithmetic, not a measurement.
    """
    from training.band_reference import resolve_band

    end_date = args.get("date") or _today()
    ref = _read_reference()
    if not ref:
        return {"applicable": False, "reason": "no training_reference yet", "_disclaimer": _BENCHMARK_DISCLAIMER}
    if int(ref.get("reference_schema") or 1) < 2:
        return {
            "applicable": False,
            "reason": "training_reference is v1 — a STALE REFERENCE, not a finding. Redeploy episode-detect.",
            "reference_schema": int(ref.get("reference_schema") or 1),
            "_disclaimer": _BENCHMARK_DISCLAIMER,
        }

    weight, rate, _ = _current_weight_and_rate(end_date)
    if weight is None:
        return {"applicable": False, "reason": "no recent weigh-in", "_disclaimer": _BENCHMARK_DISCLAIMER}

    genesis = args.get("since") or _campaign_start()
    day_n = (datetime.strptime(end_date, "%Y-%m-%d") - datetime.strptime(genesis, "%Y-%m-%d")).days
    window_days = max(1, day_n + 1)
    artifact = window_days < _CHRONIC_WINDOW_DAYS

    start_w = _weight_on_or_after(genesis)
    actual_lost = round(start_w - weight, 1) if start_w is not None else None
    proven_lost = _campaign_day_n(ref.get("proven_curve") or [], day_n)

    now = _recent_volume(end_date, days=min(window_days, _CHRONIC_WINDOW_DAYS))
    proven = resolve_band(weight, ref.get("proven_bands"))

    levers = []
    if proven:
        for key, label in (("walk_mi_wk", "walking distance"), ("walk_hr_wk", "walking time"), ("sets_wk", "lifting sets")):
            then = proven.get(key)
            mine = now.get(key)
            if mine is None or then in (None, 0):
                continue
            levers.append(
                {
                    "lever": label,
                    "field": key,
                    "now": mine,
                    "proven": then,
                    "ratio": _ratio(mine, then),
                    "shortfall": round(float(then) - float(mine), 2),
                }
            )
        levers.sort(key=lambda x: (x["ratio"] if x["ratio"] is not None else 99))

    ev = (proven or {}).get("evidence") or {}
    out = {
        "applicable": True,
        "date": end_date,
        "campaign_start": genesis,
        "day_n": day_n,
        "window_days": window_days,
        "rates_are_artifacts": artifact,
        "artifact_note": (
            f"The campaign is {window_days} day(s) old, shorter than the {_CHRONIC_WINDOW_DAYS}-day "
            "chronic window. Per-week figures here are arithmetic on a short window, not measurements."
            if artifact
            else None
        ),
        "current_weight": round(weight, 1),
        "lost_to_date_lb": actual_lost,
        "proven_lost_at_same_day_lb": proven_lost,
        "vs_proven_lb": (round(actual_lost - proven_lost, 1) if (actual_lost is not None and proven_lost is not None) else None),
        "reference_band": (proven or {}).get("band"),
        "reference_distance_lb": (proven or {}).get("band_distance_lb"),
        "reference_tier": ev.get("tier"),
        "levers_ranked": levers,
        "worst_lever": levers[0] if levers else None,
        "intake_comparable": False,
        "intake_note": (
            "Training and activity only — no nutrition data exists before 2025-11-24, so intake "
            "cannot be compared to the cut that worked."
        ),
        "confidence": ev.get("tier") or "low",
        "_disclaimer": _BENCHMARK_DISCLAIMER,
    }
    if artifact:
        # The ranking is arithmetic on a window shorter than the chronic one.
        # Printing a percentage here would state as a measurement the very thing
        # `rates_are_artifacts` exists to deny — the flag must govern the
        # headline, not sit beside a sentence that ignores it.
        out["worst_lever"] = None
        out["signal"] = (
            f"Day {day_n}. Too early to rank levers: the campaign is {window_days} day(s) old against a "
            f"{_CHRONIC_WINDOW_DAYS}-day chronic window, so per-week figures are arithmetic, not "
            "measurements. Volumes are listed for context only."
        )
    elif levers:
        w = levers[0]
        out["signal"] = (
            f"Day {day_n}. Furthest-below lever: {w['lever']} at {w['now']} vs {w['proven']} "
            f"({int((w['ratio'] or 0) * 100)}% of the comparable losing period, {out['reference_distance_lb']} lb away)."
        )
    else:
        out["signal"] = f"Day {day_n}. No comparable losing-phase period within reach of {round(weight, 1)} lb to rank against."
    return out


# ── the tool's own description (#3710) ─────────────────────────────────────────
# Extracted from mcp/registry.py, which is FULL against the #1665 module-size
# ceiling. A tool describing itself beside its own implementation is where this
# belonged anyway: the two views added here needed ~15 lines of registry prose,
# and the size guard's rule is to pay for new lines out of an extraction rather
# than raise the baseline.
GET_BENCHMARK_DESCRIPTION = (
    "PRIVATE cut-benchmarking vs Matthew's own proven weight-loss history (descriptive, "
    "correlational, n=1 — never causal). Use 'view' to select: "
    "'pace' (default) = live pace vs the proven trajectory at the current weight — current "
    "weight/rate + recent walking volume vs the by-band proven volumes, walk gap, and the "
    "~240 lb run gate. "
    "'episodes' = the detected loss/regain ledger + loss-vs-regain rate asymmetry. "
    "'maintenance' = the regain firewall (near goal): rolling walk volume vs the proven floor "
    "and the post-trough decay signature. "
    "'prescription' = what he was ACTUALLY doing at a comparable bodyweight — walk miles/hours, "
    "target walk heart rate, sets and per-movement loads — from the periods he was LOSING, with "
    "the weight distance to that period and its evidence tier stated. Returns two tables that are "
    "not interchangeable: proven_target (from losing phases; the target) and current_typical (all "
    "history at his current weight; the BASELINE, never a target — at his current weight that is "
    "the period he is trying to escape). Training/activity only: intake is not comparable, no "
    "nutrition data exists before 2025-11-24. "
    "'campaign' = is THIS transformation tracking the one that worked, and which lever "
    "explains the gap — day-N cumulative loss vs the proven curve at the same day, plus the "
    "levers RANKED by how far each sits below its comparable losing-phase value. Windows "
    "shorter than the 28-day chronic window are flagged as artifacts, not printed as rates. "
    "All views forward-framed (what works next), never a failure tally. "
    "Use for: 'how does my pace compare to last time?', 'am I walking enough?', 'can I run yet?', "
    "'show my cut history', 'am I holding the loss?', 'what was I doing last time I weighed this?', "
    "'what heart rate should I target?', 'how many miles this week?'."
)


# ── dispatcher ──────────────────────────────────────────────────────────────────


def tool_get_benchmark(args):
    """View-dispatched cut-benchmarking tool (PRIVATE). Default view: pace."""
    VALID_VIEWS = {
        "pace": _benchmark_pace,
        "episodes": _benchmark_episodes,
        "maintenance": _benchmark_maintenance,
        "prescription": _benchmark_prescription,
        "campaign": _benchmark_campaign,
    }
    view = (args.get("view") or "pace").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": (
                "Default is 'pace' (live pace vs your proven trajectory). Also: 'episodes' (ledger), "
                "'maintenance' (regain firewall), 'prescription' (what he was doing at a comparable "
                "bodyweight, with the weight distance and evidence tier stated)."
            ),
        }
    return VALID_VIEWS[view](args)
