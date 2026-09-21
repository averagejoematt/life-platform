"""lambdas/health/deficit_disclosures.py — provenance + honesty text for the nutrition
deficit surfaces (#3754).

WHY THIS EXISTS

The 2026-09-20 red-team on `tool_get_deficit_sustainability` (`mcp/tools_nutrition.py`)
found every population-derived cutoff the tool uses — the first-third-vs-last-third trend
window, the five per-channel "degraded" deltas, the "3+ concurrent degradations =
unsustainable" composite rule, and the `deficit_label` bands ("aggressive" etc.) — carried
NO provenance on output (ADR-105 rule 4), while the tool read SUSTAINABLE on 1,533 kcal at
317 lb without ever touching intake, protein, electrolytes or DXA. This module is the ONE
place those cutoffs and their provenance live, so the values graded and the values
disclosed cannot drift apart, and so the ADR-104 "not comparable to the prior cut" sentence
is defined exactly once and reused verbatim everywhere a nutrition surface would otherwise
be tempted to paraphrase it (`tests/test_prior_cut_disclosure_3754.py` sweeps for exactly
one definition).

Every cutoff below is population-derived (Attia/Huberman-style heuristics baked into the
BS-12 tracker at build time, #390-era) — none has ever been checked against Matthew's own
day-to-day variance. This module does not change any verdict logic; it names what was
already being applied.
"""

from __future__ import annotations

from typing import Any

# ── ADR-104: intake has no continuous history ────────────────────────────────
# MacroFactor is the only intake source and it did not exist for the prior cut. Any
# surface that reads current intake/deficit figures as comparable to "how it was last
# time" is comparing measured data to nothing. This is the ONE sentence that says so —
# reused verbatim, never paraphrased, everywhere such a comparison could be read into a
# nutrition surface's output.
MACROFACTOR_START_DATE = "2025-11-24"

INTAKE_NOT_COMPARABLE_TO_PRIOR_CUT = "intake is NOT comparable to the prior cut — MacroFactor begins 2025-11-24 (ADR-104)"


# ── BS-12 deficit-sustainability cutoffs (ADR-105 rule 4: provenance at the point of use) ──
TREND_WINDOW_METHOD: dict[str, Any] = {
    "method": "first_third_vs_last_third_of_window",
    "stable_band_pct": 5,
    "provenance": "population-derived",
    "note": (
        "A channel is only called 'declining'/'improving' outside a flat +/-5% band between "
        "the first third and last third of the requested window — an arbitrary noise "
        "margin, not a figure derived from his own day-to-day variance."
    ),
}

# Keyed by the internal channel id used in tool_get_deficit_sustainability's `channels` list.
CHANNEL_CUTOFFS: dict[str, dict[str, Any]] = {
    "hrv": {
        "label": "HRV",
        "decline_pct": 8,
        "provenance": "population-derived",
        "note": "8% HRV decline (first-vs-last third) — a generic ANS-stress heuristic, not fitted to his own HRV variance.",
    },
    "sleep_efficiency": {
        "label": "Sleep Quality — efficiency",
        "decline_pct": 3,
        "provenance": "population-derived",
        "note": "3% sleep-efficiency decline — a generic cutoff, not his own baseline noise band.",
    },
    "sleep_deep_pct": {
        "label": "Sleep Quality — deep sleep share",
        "decline_pct": 8,
        "provenance": "population-derived",
        "note": "8% deep-sleep-share decline — a generic cutoff, not his own baseline noise band.",
    },
    "recovery": {
        "label": "Recovery",
        "decline_pct": 10,
        "provenance": "population-derived",
        "note": "10% Whoop recovery-score decline — a generic cutoff, not his own baseline noise band.",
    },
    "habit_completion": {
        "label": "Habit Completion",
        "decline_pct": 10,
        "provenance": "population-derived",
        "note": "10% Habitify completion-rate decline — a generic cutoff, not his own baseline noise band.",
    },
    "training_output": {
        "label": "Training Output",
        "decline_pct": 15,
        "provenance": "population-derived",
        "note": "15% Strava kilojoule-output decline — a generic cutoff, not his own baseline noise band.",
    },
}

# min_channels: how many of the 5 channels above must read "degraded" to reach the band.
CONCURRENT_DEGRADATION_BANDS: dict[str, dict[str, Any]] = {
    "watch": {
        "min_channels": 2,
        "provenance": "population-derived",
        "note": "2+ of 5 channels degrading concurrently — an arbitrary composite floor, not fitted to his history.",
    },
    "warning": {
        "min_channels": 3,
        "provenance": "population-derived",
        "note": (
            "3+ of 5 channels degrading concurrently is the BS-12 'unsustainable' call — an "
            "Attia/Huberman-style heuristic threshold, never validated against his own outcomes."
        ),
    },
    "critical": {
        "min_channels": 4,
        "provenance": "population-derived",
        "note": "4+ of 5 channels degrading concurrently — same composite rule, escalated.",
    },
}

DEFICIT_LABEL_BANDS: dict[str, Any] = {
    "aggressive_above_pct": 25,
    "moderate_above_pct": 15,
    "mild_above_pct": 5,
    "provenance": "population-derived",
    "note": "deficit_pct bands (>25 / >15 / >5 of estimated TDEE) are round-number labels, not derived from his own adherence/outcome history.",
}

IN_DEFICIT_FLOOR_KCAL: dict[str, Any] = {
    "value": 200,
    "provenance": "population-derived",
    "note": "A gap under 200 kcal/day vs TDEE is read as noise rather than an active cut — an arbitrary floor.",
}


def thresholds_block() -> dict[str, Any]:
    """The `thresholds` block `tool_get_deficit_sustainability` ships on every call.

    One function so the values the tool GRADES against and the values it DISCLOSES can
    never drift apart — the caller reads these same dicts to compute the verdict.
    """
    return {
        "trend_window": TREND_WINDOW_METHOD,
        "channel_cutoffs": CHANNEL_CUTOFFS,
        "concurrent_degradation_bands": CONCURRENT_DEGRADATION_BANDS,
        "deficit_label_bands": DEFICIT_LABEL_BANDS,
        "in_deficit_floor_kcal": IN_DEFICIT_FLOOR_KCAL,
    }


# ── Honesty line (2026-09-20 red-team, #3754) ────────────────────────────────
DEFICIT_SUSTAINABILITY_HONESTY = (
    "This tool reads HRV, sleep, recovery, habit-completion and training-output only — it "
    "has NO intake floor, NO protein channel, and NO electrolyte or DXA input. A "
    "SUSTAINABLE verdict is a statement about those five channels holding steady, not a "
    "clearance of the deficit itself — the deficit can be nutritionally unsound (too low, "
    "too little protein, no electrolyte tracking) while every channel here still reads clean."
)
