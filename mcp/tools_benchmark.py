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

from datetime import datetime, timedelta, timezone

from mcp.core import get_profile, query_source

# Run gate from PROVEN_BLUEPRINT.md — zero runs logged above ~240 lb in his own history.
RUN_GATE_LB = 240.0

TRAINING_REFERENCE_SOURCE = "training_reference"
WEIGHT_EPISODES_SOURCE = "weight_episodes"

_BENCHMARK_DISCLAIMER = (
    "For personal health tracking only. Not medical advice. Descriptive of Matthew's own "
    "n=1 history (correlational, not causal). Consult a qualified healthcare provider before "
    "making health decisions based on this data."
)


# ── precomputed-source reads (newest-in-range, like computed_metrics) ───────────


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


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


def _band_for(weight: float) -> str:
    base = int(weight // 10) * 10
    return f"{base}-{base + 9}"


def _current_weight_and_rate(end_date: str, days: int = 21) -> tuple:
    """(current_weight, rate_lb_wk [positive=losing], n_weighins) from recent withings."""
    start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = [r for r in query_source("withings", start, end_date) if r.get("weight_lbs") is not None]
    pts = sorted(((r.get("date") or r.get("sk", "").replace("DATE#", ""))[:10], float(r["weight_lbs"])) for r in rows)
    if not pts:
        return None, None, 0
    current = pts[-1][1]
    rate = None
    if len(pts) >= 2:
        d0 = datetime.strptime(pts[0][0], "%Y-%m-%d")
        d1 = datetime.strptime(pts[-1][0], "%Y-%m-%d")
        span_days = max(1, (d1 - d0).days)
        rate = (pts[0][1] - pts[-1][1]) / (span_days / 7.0)  # positive when losing
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
    """Local proven loss rate (lb/wk) at the matched weight, from the proven_curve."""
    pts = sorted(curve, key=lambda p: p.get("days_from_start", 0))
    for a, b in zip(pts, pts[1:]):
        lo, hi = sorted([a.get("weight", 0), b.get("weight", 0)])
        dd = b.get("days_from_start", 0) - a.get("days_from_start", 0)
        if lo <= weight <= hi and dd > 0:
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
        from mcp.tools_nutrition import tool_get_deficit_sustainability, tool_get_metabolic_adaptation

        ds = tool_get_deficit_sustainability({})
        out["deficit_sustainability"] = {"available": "error" not in ds, "note": ds.get("error")} if isinstance(ds, dict) else {}
        ma = tool_get_metabolic_adaptation({})
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


# ── dispatcher ──────────────────────────────────────────────────────────────────


def tool_get_benchmark(args):
    """View-dispatched cut-benchmarking tool (PRIVATE). Default view: pace."""
    VALID_VIEWS = {
        "pace": _benchmark_pace,
        "episodes": _benchmark_episodes,
        "maintenance": _benchmark_maintenance,
    }
    view = (args.get("view") or "pace").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "Default is 'pace' (live pace vs your proven trajectory). Also: 'episodes' (ledger), 'maintenance' (regain firewall).",
        }
    return VALID_VIEWS[view](args)
