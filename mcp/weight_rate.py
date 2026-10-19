"""weight_rate.py — the weight-loss rate in both units, and the one flag on it (#5060).

Split out of `mcp/tools_health.py` by the module-size guard (#1665: the 1,000 logical-line
ceiling) when #5060 landed the percent-of-bodyweight rate. `tool_get_weight_loss_progress`
is the only caller; the rate arithmetic lives here so the tool module stays a tool module.

Owner ruling 3 (2026-10-18): every rate is shown in lb/wk AND % of bodyweight.
"""

from __future__ import annotations

from datetime import datetime, timedelta

# Rate flag threshold, relative to bodyweight (#5060, owner ruling 3: every rate is shown in lb/wk AND % of bodyweight).
# Source: Helms et al. 2014 (J Int Soc Sports Nutr) recommends 0.5-1.0 %BW/wk to preserve lean mass in lean-mass-
# retaining cuts; the owner's 3.0-3.5 lb/wk band is ~1.0-1.2 %BW/wk at ~300 lb, so the flag is set at 1.25 %BW/wk,
# above the band's ceiling at his size, and tightens automatically as he gets lighter (a fixed lb/wk number does not).
# charter: governing_goal.rate_band (#5074 moves the band read to the charter in W1)
RATE_FLAG_PCT_BW_PER_WK = 1.25
RATE_SLOW_LB_PER_WK = 0.25  # below this the "very slow" nudge fires (absolute, unchanged)


def rate_pct_bw(rate_lb_per_wk, weight_lbs):
    """rate / current weight x 100, 2dp; None when either input is missing or the weight is not positive."""
    if rate_lb_per_wk is None or not weight_lbs or weight_lbs <= 0:
        return None
    return round(rate_lb_per_wk / weight_lbs * 100, 2)


def annotate_weekly_rates(weight_series):
    """Pair each weigh-in with the one ~7 days earlier (4-day tolerance); stamp rate + flag in place; return the rates."""
    weekly_rates = []
    for i in range(len(weight_series)):
        pt = weight_series[i]
        target_dt = datetime.strptime(pt["date"], "%Y-%m-%d") - timedelta(days=7)
        prior = None
        best_gap = 999
        for j in range(i):
            d = datetime.strptime(weight_series[j]["date"], "%Y-%m-%d")
            gap = abs((target_dt - d).days)
            if gap < best_gap:
                best_gap = gap
                prior = weight_series[j]
        if prior and best_gap <= 4:
            days_diff = (datetime.strptime(pt["date"], "%Y-%m-%d") - datetime.strptime(prior["date"], "%Y-%m-%d")).days
            if days_diff > 0:
                weekly_rate = round((prior["weight_lbs"] - pt["weight_lbs"]) / days_diff * 7, 2)
                pt["weekly_loss_rate_lbs"] = weekly_rate
                pt["rate_lb_per_wk"] = weekly_rate
                pt["rate_pct_bodyweight_per_wk"] = rate_pct_bw(weekly_rate, pt["weight_lbs"])
                weekly_rates.append(weekly_rate)
                pct = pt["rate_pct_bodyweight_per_wk"]
                if pct is not None and pct > RATE_FLAG_PCT_BW_PER_WK:
                    pt["rate_flag"] = (
                        f"⚠️ Losing too fast ({weekly_rate} lb/wk = {pct}% of bodyweight; flag above "
                        f"{RATE_FLAG_PCT_BW_PER_WK}%/wk) — risk of muscle loss. Check nutrition."
                    )
                elif weekly_rate < 0:
                    pt["rate_flag"] = "↑ Weight gain this week"
                elif weekly_rate < RATE_SLOW_LB_PER_WK and len(weight_series) > 14:
                    pt["rate_flag"] = "⏸ Very slow — review deficit"
    return weekly_rates
