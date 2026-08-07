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
# genuinely gated (intensive); otherwise it is an issue-referenced string
# explaining either (a) the field is still-open debt — it may publish under a
# possibly-under-filled window name — or (b) it is EXEMPT: an intensive field
# that is provably never genesis-clamped (e.g. a deliberately cross-phase read,
# #2109), so there is nothing to gate. Case (b) still needs a non-None gap
# because `phase_plausibility.py` (#1922) treats `kind == INTENSIVE and gap is
# None` as "gate this" — an exempt field left at gap=None would make the live
# deterministic QA check flag its correct, permanently-full values as
# impossible on a young cycle. Gap strings say which case with an
# "EXEMPT (not debt)" prefix; read the per-entry comment for the reasoning.
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
    # ── #1919 resolution (measured against the live code, 2026-08-06) ───────
    # Of the 11 fields #1919 declared, measuring found the debt was real for 6,
    # already resolved by unrelated work for 2, one was never a genesis-clamp
    # defect at all (a permanent size mislabel instead), one is a raw per-day
    # series (self-documenting, not a scalar claim), and one is a deliberate
    # UX trade-off left open — see each entry below.
    #
    # GATED (the #1917 pattern: real value ships unconditionally under a
    # window-generic key; the `_Nd`-named key nulls until the window is real):
    "mean_7d": (INTENSIVE, None),  # gated on pacific_day_n>=7; real value ships as recent_week_mean
    "mean_30d": (INTENSIVE, None),  # gated on pacific_day_n>=30; real value ships as recent_month_mean
    "trend_vs_prior_30d": (INTENSIVE, None),  # gated on _window_span(d60, d30, 30)["full"]
    "cal_7d_avg": (INTENSIVE, None),  # gated on _window_span(d7, today, 7)["full"]; real value ships as cal_avg_recent
    "pro_7d_avg": (INTENSIVE, None),  # gated on _window_span(d7, today, 7)["full"]; real value ships as pro_avg_recent_g
    "total_protein_30d_avg_g": (INTENSIVE, None),  # gated on _window_span(d30, today, 30)["full"]; real value ships as total_protein_avg_g
    # RECLASSIFIED EXTENSIVE — a raw per-day array, not a computed scalar. Its
    # length already IS the honest window (never padded to 7 — see #1919's
    # fulfillment_index.py fix, which also stopped the array from being
    # extended with pre-genesis dates in the first place); a short array
    # understates by being short, it never misstates a number as if it covered
    # more days than it does. Same logic EXTENSIVE already applies to counts.
    "trend_7d": (EXTENSIVE, None),
    # EXEMPT — not experiment-scoped at all, so the genesis-clamp premise this
    # whole registry is about does not apply. `_uptime_90d` (site_api_intelligence.py)
    # windows off the PLATFORM epoch (2026-03-28), not EXPERIMENT_START, and is
    # unaffected by any cycle reset; it is also a per-day status array (0/1/2),
    # not an averaged rate, so it is EXTENSIVE by the same reasoning as trend_7d
    # above — the registry's original "a percentage" description was wrong.
    "uptime_90d": (EXTENSIVE, None),
    # EXEMPT — measured NOT to be genesis-clamped. `avg_7d_g` (site_api_ai_lambda.py,
    # sourced from daily_metrics_compute_lambda's `protein_g_avg`) reads via
    # `fetch_range`, which is deliberately CROSS-PHASE for RAW_TIMESERIES sources
    # (#2109) — the query window is a real, un-clamped 30 calendar days regardless
    # of cycle age. The actual #1919-class defect here was different: the key (and
    # its AI-prompt prose) claimed "7d" for a computation that has always run over
    # 30 days. Fixed by renaming to `avg_30d_g` (site_api_ai_lambda.py, ai_context.py)
    # so the name matches the real, permanently-full window.
    #
    # `gap` is intentionally NOT None even though this is not open debt: the
    # phase_plausibility deterministic checker (#1922) reads `kind == INTENSIVE and
    # gap is None` to mean "gate this — flag a non-null value before day N as
    # impossible". avg_30d_g genuinely publishes non-null on Day 4 (it is real,
    # cross-phase data), so gap=None here would make the live QA gate flag a
    # CORRECT payload as a false positive — the opposite of what #1919 is for.
    # The gap string marks "exempt", not "still under-filling".
    "avg_30d_g": (INTENSIVE, "#1919 — EXEMPT (not debt): cross-phase RAW_TIMESERIES read (#2109), never genesis-clamped"),
    # EXEMPT — measured NOT to be genesis-clamped, for the same reason as avg_30d_g:
    # daily_brief_lambda's `fetch_range` reads whoop cross-phase (RAW_TIMESERIES,
    # #2089/#2109) over a hard-coded `today - 30d` window with NO EXPERIMENT_START
    # clamp at all. Unlike avg_7d_g, the name here was always accurate (a genuine
    # 30-day rolling average) — this field predates #1919 and #2109 fixed the
    # underlying read pattern before this issue was even measured. Same non-None
    # gap reasoning as avg_30d_g above: this is a real, permanently-full value
    # that must NOT trip the phase_plausibility day_n gate on a young cycle.
    "sleep_hours_30d_avg": (INTENSIVE, "#1919 — EXEMPT (not debt): cross-phase RAW_TIMESERIES read (#2089/#2109), never genesis-clamped"),
    # STILL OPEN — real debt, left open deliberately (not mechanically converted).
    # group_90d_avgs (site_api_habits.py) IS a genesis-clamped mean (same shape as
    # weight_delta_30d) and IS under-filled through Day 90 of every cycle — but
    # unlike the other 10 fields, it is the PRIMARY signal /habits/ renders
    # (evidence_habits.js: effort map, group trends, goal linkage all read this
    # key directly, no fallback). Gating it null would blank that page for up to
    # ~90 days after every cycle restart — a worse reader outcome than a
    # correctly-disclosed partial mean, and the front-end has no consumer for a
    # window-generic replacement key yet. #1919 adds the disclosure half
    # (`group_avgs_window_days`, the real span) without the frontend migration;
    # closing this one for real is a follow-up that touches evidence_habits.js.
    "group_90d_avgs": (
        INTENSIVE,
        "#1919 — ships group_avgs_window_days beside it; full gate needs a frontend migration, deliberately deferred",
    ),
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
