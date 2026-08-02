"""window_registry.py — the canonical registry of published window-named fields (#1917/#1922).

Moved from tests/test_window_name_honesty_1917.py (which now imports it) so the
DETERMINISTIC phase-plausibility checker (lambdas/operational/phase_plausibility.py,
#1922) and the #1917 set-guard test share ONE registry. The registry is the single
place a `_Nd`-named published field states what it really covers:

  * EXTENSIVE (counts, sums, totals) — a short window understates, never
    overstates; safe by kind.
  * INTENSIVE (averages, means, deltas, rates) — a full-window-named value
    computed over a partly-elapsed window is a DIFFERENT CLAIM than its name
    makes; must gate on a genuinely full window (gap None) or carry an
    issue-linked gap declaring the debt (#1919).

The #1917 test still AST-scans lambdas/web/ so every published window-named key
must appear here; the #1922 checker reads the same entries to decide which
non-null fields are phase-impossible. One registry, two enforcers.
"""

import re

# A published JSON key naming a day-window: foo_30d, hrv_30d_avg, avg_7d_g, ...
WINDOW_KEY = re.compile(r"^(?:.*_)?(\d+)d(?:_.*)?$")

EXTENSIVE = "extensive"  # count/sum over the window — a short window understates, never overstates
INTENSIVE = "intensive"  # mean/delta/rate over the window — a short window MISSTATES

# ── the registry ────────────────────────────────────────────────────────────
# key -> (kind, gap). `gap` is None when the field is safe by kind (extensive) or
# genuinely gated (intensive); otherwise it is an issue reference explaining why an
# intensive field may still publish under a possibly-under-filled window name.
REGISTRY: dict[str, tuple[str, str | None]] = {
    # ── intensive + GATED by #1917 (the fix) ────────────────────────────────
    # These read None until the window they are named for is genuinely covered;
    # the real value ships alongside under a window-generic name.
    "weight_delta_30d": (INTENSIVE, None),
    "hrv_30d_avg": (INTENSIVE, None),
    "hrv_30d_n": (EXTENSIVE, None),  # an n, gated with its average so the pair never disagrees
    # `weight_delta_7d` is written by daily_brief over an exactly-7-day lookback
    # (week_ago_weight) and carries `weight_delta_window_days` — named for its real
    # window as of #1917, when it was corrected from `weight_delta_30d`.
    "weight_delta_7d": (INTENSIVE, None),
    # Found BY this scan, not by qa-smoke and not by reading: seven more means on
    # /api/glucose and /api/sleep, in the same file as the reported bug. They use
    # the PREFIX form (`30d_avg_mg_dl`), which every `_30d`-suffix grep — including
    # the one I ran first — misses. Gated identically.
    "30d_avg_mg_dl": (INTENSIVE, None),
    "30d_avg_tir": (INTENSIVE, None),
    "30d_avg_optimal": (INTENSIVE, None),
    "30d_avg_std": (INTENSIVE, None),
    "30d_avg_recovery": (INTENSIVE, None),
    "30d_avg_score": (INTENSIVE, None),
    "30d_avg_efficiency": (INTENSIVE, None),
    # ── intensive, NOT yet gated — declared debt, not silence ───────────────
    # Each publishes a mean/delta over a genesis-clamped window and so under-fills
    # its name on Day 1..N-1 of a cycle, exactly as /api/vitals did. None is as
    # reader-visible as the two qa-smoke caught: they are on lower-traffic
    # surfaces and several already ship an explicit n beside the claim (ADR-105),
    # which is a partial mitigation, not a fix.
    "mean_7d": (INTENSIVE, "#1919 — ships n_scored_7d beside it (ADR-105 partial mitigation)"),
    "mean_30d": (INTENSIVE, "#1919 — ships n_scored_30d beside it (ADR-105 partial mitigation)"),
    "trend_7d": (INTENSIVE, "#1919 — a per-day series, not a scalar claim; lower risk"),
    "trend_vs_prior_30d": (INTENSIVE, "#1919 — window-over-window comparison on a clamped window"),
    "cal_7d_avg": (INTENSIVE, "#1919 — nutrition 7d mean over a clamped window"),
    "pro_7d_avg": (INTENSIVE, "#1919 — nutrition 7d mean over a clamped window"),
    "avg_7d_g": (INTENSIVE, "#1919 — protein 7d mean surfaced to the AI layer"),
    "total_protein_30d_avg_g": (INTENSIVE, "#1919 — 30d mean over a clamped window"),
    "sleep_hours_30d_avg": (INTENSIVE, "#1919 — written by daily_brief, carried by site_stats_refresh"),
    "group_90d_avgs": (INTENSIVE, "#1919 — habit group means over a clamped 90d window"),
    "uptime_90d": (INTENSIVE, "#1919 — a percentage; platform uptime, not experiment-scoped data"),
    "composite_delta_1d": (INTENSIVE, None),  # a 1-day window is full from Day 2; nothing to under-fill
    # ── extensive: counts and sums. Safe by kind. ───────────────────────────
    "binge_days_30d": (EXTENSIVE, None),
    "count_30d": (EXTENSIVE, None),
    "daily_modality_minutes_30d": (EXTENSIVE, None),
    "distinct_exercises_30d": (EXTENSIVE, None),
    "journal_entries_30d": (EXTENSIVE, None),
    "n_scored_7d": (EXTENSIVE, None),
    "n_scored_30d": (EXTENSIVE, None),
    "orders_30d": (EXTENSIVE, None),
    "relapses_90d": (EXTENSIVE, None),
    "resisted_90d": (EXTENSIVE, None),
    "sessions_30d": (EXTENSIVE, None),
    "sessions_90d": (EXTENSIVE, None),
    "strength_sessions_30d": (EXTENSIVE, None),
    "total_interactions_30d": (EXTENSIVE, None),
    "total_miles_30d": (EXTENSIVE, None),
    "total_minutes_30d": (EXTENSIVE, None),
    "total_rucks_30d": (EXTENSIVE, None),
    "total_sets_30d": (EXTENSIVE, None),
    "total_spend_30d": (EXTENSIVE, None),
    "total_temptations_90d": (EXTENSIVE, None),
    "total_walks_30d": (EXTENSIVE, None),
    "workouts_30d": (EXTENSIVE, None),
    "workouts_90d": (EXTENSIVE, None),
    "z2_trailing_7d_min": (EXTENSIVE, None),
}


def window_days(key: str) -> int | None:
    """The N a window-named key claims (hrv_30d_avg -> 30), else None."""
    m = WINDOW_KEY.match(key)
    return int(m.group(1)) if m else None
