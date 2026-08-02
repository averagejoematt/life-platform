#!/usr/bin/env python3
"""gen_mirror_vectors.py — pin the Mirror's browser scoring to the deployed engine (#1392).

/method/mirror/ scores a reader's Whoop export IN THE BROWSER on the same deterministic
instruments that score Matthew every night. That claim — "the same instruments" — is
only true if the JS port cannot drift from the deployed Python. So, exactly like
calibration-core (#1396), the port is pinned by a shared test-vector suite generated
FROM the deployed modules, never hand-written:

    lambdas/health/scoring_engine.py            score_sleep / score_recovery
    lambdas/health/personal_baselines.py        percentile / readiness_hrv_score / bands
    lambdas/compute/daily_metrics_compute_lambda.py
                                                normalize_whoop_sleep / compute_readiness / avg

Consumed by BOTH sides of the parity gate:
    tests/test_mirror_parity.py      — re-runs the Python against the committed vectors
                                       (catches a stale vectors file after an engine change)
    tests/js/mirror_core.test.mjs    — runs site/assets/js/mirror-core.js against the
                                       same vectors under node --test (exact equality)

ADR-105: exact equality, never a tolerance — every value is rounded at the source.

Run from repo root:  python3 scripts/gen_mirror_vectors.py
Writes tests/vectors/mirror_vectors.json. Deterministic: no clock, no randomness, no I/O
besides the output file — regenerating without an engine change is a no-op diff.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from compute.daily_metrics_compute_lambda import compute_readiness, normalize_whoop_sleep  # noqa: E402
from health import personal_baselines, scoring_engine  # noqa: E402

OUT_PATH = os.path.join(ROOT, "tests", "vectors", "mirror_vectors.json")


# ── deterministic fixture inputs (varied but fixed — NOT random) ─────────────

PERCENTILE_LISTS = [
    [],
    [42.0],
    [1, 2, 3, 4, 5],
    [5, 1, 4, 2, 3],  # unsorted — the function sorts
    [55.2, None, 61.0, "bad", 48.7, 70.1, 66.6],  # dirty entries dropped
    [0.82, 0.91, 1.04, 0.97, 1.13, 0.88, 1.01, 0.95, 1.08, 0.79],
]
PERCENTILE_PS = [0, 5, 10, 25, 50, 62, 75, 90, 95, 100]

# A ≥30-value HRV-ratio history (band engages) and a 29-value one (floor-guard holds).
RATIOS_THICK = [round(0.78 + 0.017 * i, 4) for i in range(34)]
RATIOS_THIN = RATIOS_THICK[:29]

PERSONAL_BAND = {"readiness_hrv_ratio": {"p10": 0.85, "p50": 0.99, "p90": 1.18, "n": 120}}
THIN_BAND = {"readiness_hrv_ratio": {"p10": 0.85, "p50": 0.99, "p90": 1.18, "n": 12}}  # below MIN_N → fallback
DEGENERATE_BAND = {"readiness_hrv_ratio": {"p10": 1.0, "p50": 1.0, "p90": 1.0, "n": 40}}

HRV_RATIO_CASES = [0.6, 0.75, 0.85, 0.92, 0.99, 1.0, 1.08, 1.18, 1.25, 1.4]

SLEEP_RECORDS = [
    # full record straight off the ingestion shape (values as floats, post-Decimal)
    {
        "sleep_duration_hours": 7.42,
        "slow_wave_sleep_hours": 1.51,
        "rem_sleep_hours": 1.83,
        "light_sleep_hours": 4.08,
        "time_awake_hours": 0.62,
        "disturbance_count": 11,
        "sleep_efficiency_percentage": 91.34,
        "sleep_quality_score": 84.0,
    },
    # no stages, quality only
    {"sleep_duration_hours": 6.1, "sleep_quality_score": 71.0},
    # zero duration — pct fields must NOT be produced
    {"sleep_duration_hours": 0, "slow_wave_sleep_hours": 1.2, "sleep_quality_score": 60.0},
    # aliases already present — normalize must not overwrite them
    {
        "sleep_duration_hours": 8.0,
        "rem_sleep_hours": 2.0,
        "rem_pct": 33.3,
        "sleep_score": 90.0,
        "sleep_quality_score": 80.0,
        "sleep_efficiency_percentage": 88.0,
        "sleep_efficiency_pct": 87.0,
    },
    # unparseable duration — pct computation skipped, record otherwise preserved
    {"sleep_duration_hours": "seven", "rem_sleep_hours": 2.0, "sleep_quality_score": 75.0},
]

PROFILE_DEFAULT = {}  # score_sleep falls back to sleep_target_hours_ideal 7.5
PROFILE_CUSTOM = {"sleep_target_hours_ideal": 8.0}

SCORE_SLEEP_CASES = [
    # (data, profile) — data is the {"sleep": ...} wrapper score_sleep reads
    ({"sleep": None}, PROFILE_DEFAULT),
    (
        {
            "sleep": {
                "sleep_score": 84.0,
                "sleep_efficiency_pct": 91.34,
                "sleep_duration_hours": 7.42,
                "deep_pct": 20.4,
                "rem_pct": 24.7,
                "light_pct": 55.0,
            }
        },
        PROFILE_DEFAULT,
    ),
    ({"sleep": {"sleep_score": 84.0}}, PROFILE_DEFAULT),
    ({"sleep": {"sleep_efficiency_pct": 78.0, "sleep_duration_hours": 5.9}}, PROFILE_CUSTOM),
    ({"sleep": {"sleep_duration_hours": 10.2}}, PROFILE_DEFAULT),
    ({"sleep": {"toss_and_turns": 9}}, PROFILE_DEFAULT),  # no scoreable field → None + details
]

SCORE_RECOVERY_CASES = [
    {"whoop": None},
    {"whoop": {"recovery_score": 67.0}},
    {"whoop": {"recovery_score": 101.0}},  # clamped
    {"whoop": {"hrv": 55.0}},  # no recovery_score → None
]

READINESS_CASES = [
    # every case carries the full key surface compute_readiness touches
    {
        "label": "all components (no tsb — the Mirror's shape)",
        "data": {
            "whoop_today": {"recovery_score": 62.0},
            "whoop": {"recovery_score": 58.0},
            "sleep": {"sleep_score": 84.0},
            "hrv": {"hrv_7d": 52.3, "hrv_30d": 48.9},
            "tsb": None,
        },
        "baselines": {},
    },
    {
        "label": "recovery falls back to yesterday",
        "data": {
            "whoop_today": None,
            "whoop": {"recovery_score": 71.0},
            "sleep": {"sleep_score": 66.0},
            "hrv": {"hrv_7d": 44.0, "hrv_30d": 51.0},
            "tsb": None,
        },
        "baselines": {},
    },
    {
        "label": "personal band engaged",
        "data": {
            "whoop_today": {"recovery_score": 80.0},
            "whoop": None,
            "sleep": {"sleep_score": 75.0},
            "hrv": {"hrv_7d": 50.0, "hrv_30d": 47.0},
            "tsb": None,
        },
        "baselines": PERSONAL_BAND,
    },
    {
        "label": "recovery only",
        "data": {"whoop_today": {"recovery_score": 55.0}, "whoop": None, "sleep": None, "hrv": {}, "tsb": None},
        "baselines": {},
    },
    {
        "label": "sleep + hrv, no recovery",
        "data": {"whoop_today": None, "whoop": None, "sleep": {"sleep_score": 90.0}, "hrv": {"hrv_7d": 60.0, "hrv_30d": 52.0}, "tsb": None},
        "baselines": {},
    },
    {
        "label": "with tsb (platform shape — the Mirror never has this, pinned anyway)",
        "data": {
            "whoop_today": {"recovery_score": 62.0},
            "whoop": None,
            "sleep": {"sleep_score": 84.0},
            "hrv": {"hrv_7d": 52.3, "hrv_30d": 48.9},
            "tsb": -12.0,
        },
        "baselines": {},
    },
    {
        "label": "nothing scoreable",
        "data": {"whoop_today": None, "whoop": None, "sleep": None, "hrv": {}, "tsb": None},
        "baselines": {},
    },
    {
        "label": "hrv_30d zero is skipped, not divided by",
        "data": {"whoop_today": {"recovery_score": 62.0}, "whoop": None, "sleep": None, "hrv": {"hrv_7d": 52.3, "hrv_30d": 0}, "tsb": None},
        "baselines": {},
    },
]

AVG_LISTS = [
    [],
    [None, None],
    [52.3, 48.1, None, 55.0],
    [47.85, 47.85, 47.86],
]


def build() -> dict:
    vectors: dict = {
        "_note": (
            "Generated by scripts/gen_mirror_vectors.py FROM the deployed scoring modules. "
            "Do not hand-edit — regenerate after any engine change and commit the diff. "
            "Consumed by tests/test_mirror_parity.py (Python) and tests/js/mirror_core.test.mjs (JS)."
        ),
        "source_modules": [
            "lambdas/health/scoring_engine.py",
            "lambdas/health/personal_baselines.py",
            "lambdas/compute/daily_metrics_compute_lambda.py",
        ],
    }

    vectors["percentile"] = [
        {"values": vals, "p": p, "expected": personal_baselines.percentile(vals, p)} for vals in PERCENTILE_LISTS for p in PERCENTILE_PS
    ]

    vectors["avg"] = [{"values": vals, "expected": scoring_engine.avg(vals)} for vals in AVG_LISTS]

    vectors["hrv_band"] = [
        {"ratios": ratios, "expected": personal_baselines.compute_bands(ratios, [])["readiness_hrv_ratio"]}
        for ratios in (RATIOS_THICK, RATIOS_THIN, [])
    ]

    rhs_cases = []
    for baselines, blabel in [
        ({}, "fallback"),
        (PERSONAL_BAND, "personal"),
        (THIN_BAND, "thin->fallback"),
        (DEGENERATE_BAND, "degenerate"),
    ]:
        for ratio in HRV_RATIO_CASES:
            score, src = personal_baselines.readiness_hrv_score(ratio, baselines)
            rhs_cases.append({"ratio": ratio, "baselines": baselines, "label": blabel, "expected": [score, src]})
    vectors["readiness_hrv_score"] = rhs_cases

    vectors["normalize_whoop_sleep"] = [{"item": item, "expected": normalize_whoop_sleep(dict(item))} for item in SLEEP_RECORDS] + [
        {"item": None, "expected": None}
    ]

    ss_cases = []
    for data, profile in SCORE_SLEEP_CASES:
        score, details = scoring_engine.score_sleep(data, profile)
        ss_cases.append({"data": data, "profile": profile, "expected": [score, details]})
    vectors["score_sleep"] = ss_cases

    vectors["score_recovery"] = [{"data": data, "expected": list(scoring_engine.score_recovery(data, {}))} for data in SCORE_RECOVERY_CASES]

    cr_cases = []
    for case in READINESS_CASES:
        score, colour, breakdown = compute_readiness(case["data"], case["baselines"])
        cr_cases.append({**case, "expected": [score, colour, breakdown]})
    vectors["compute_readiness"] = cr_cases

    return vectors


def main() -> int:
    vectors = build()
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(vectors, fh, indent=2, ensure_ascii=False, sort_keys=False)
        fh.write("\n")
    counts = {k: len(v) for k, v in vectors.items() if isinstance(v, list) and k != "source_modules"}
    print(f"wrote {os.path.relpath(OUT_PATH, ROOT)}: " + ", ".join(f"{k}={n}" for k, n in counts.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
