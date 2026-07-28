#!/usr/bin/env python3
"""gen_calibration_vectors.py — build the shared calibration test-vector suite (#1396).

The vector file (`oss/calibration-core/vectors/calibration_vectors.json`) is the
contract that makes the OSS extraction of the calibration grader *enforced* rather
than asserted. Three implementations must reproduce it exactly (ADR-105 — identical
numbers, not "close enough"):

  1. `lambdas/calibration_core.py`      — the deployed platform grader (the AUTHORITY
                                          for everything under `core_cases`)
  2. `oss/calibration-core/src/calibration_core.py` — the extracted standalone package
  3. `oss/calibration-core/js/calibration-core.js`  — the browser port that powers
                                          /method/grade-your-coach/ (vendored to
                                          site/assets/js/calibration-core.js)

`core_cases` expectations are generated from (1) — so the open package can never
silently drift away from what the site actually publishes. `adapter_cases` cover the
paste-a-ledger input layer that only (2) and (3) have (the platform reads structured
records out of DynamoDB and never parses free text), so those expectations come from
(2) and are two-way Python <-> JS.

Regenerate:  python3 scripts/gen_calibration_vectors.py
Drift gate:  tests/test_calibration_core_parity.py::test_vectors_file_is_regenerable
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

from experiment import calibration_core as platform_core  # noqa: E402  (the deployed grader)

OSS_MODULE_PATH = os.path.join(ROOT, "oss", "calibration-core", "src", "calibration_core.py")
VECTORS_PATH = os.path.join(ROOT, "oss", "calibration-core", "vectors", "calibration_vectors.json")


def load_oss_module():
    """Load the extracted package by path, under its own name.

    Both modules are called `calibration_core`; loading the OSS one by file path
    keeps them side by side in one process without either shadowing the other.
    """
    spec = importlib.util.spec_from_file_location("oss_calibration_core", OSS_MODULE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ──────────────────────────────────────────────────────────────────────────
# The cases
# ──────────────────────────────────────────────────────────────────────────

# (id, description, n_bins, pairs)
SCORE_CASES = [
    ("empty", "nothing resolved — every number is None, never a fabricated zero", 10, []),
    ("single_hit", "one confirmed call: n<3 so the label stays nascent", 10, [[0.8, 1]]),
    ("two_calls_degenerate_base_rate", "both outcomes identical — skill is undefined, not zero", 10, [[0.8, 1], [0.9, 1]]),
    (
        "perfect_forecaster",
        "stated 1.0/0.0 and always right — Brier 0, skill 1",
        10,
        [[1.0, 1], [1.0, 1], [0.0, 0], [0.0, 0], [1.0, 1], [0.0, 0]],
    ),
    (
        "confidently_wrong",
        "the worst case — maximal confidence, always wrong",
        10,
        [[1.0, 0], [1.0, 0], [0.0, 1], [0.0, 1], [1.0, 0], [0.0, 1]],
    ),
    (
        "always_fifty",
        "the always-say-50% baseline — Brier 0.25 exactly",
        10,
        [[0.5, 1], [0.5, 0], [0.5, 1], [0.5, 0], [0.5, 1], [0.5, 0]],
    ),
    (
        "over_confident",
        "high stated confidence, mediocre reality — the classic LLM-coach failure",
        10,
        [[0.9, 1], [0.9, 0], [0.9, 0], [0.85, 1], [0.85, 0], [0.8, 0], [0.95, 0], [0.9, 1]],
    ),
    (
        "under_confident",
        "hedged low and kept being right — under-confident, still skilled",
        10,
        [[0.2, 1], [0.2, 1], [0.3, 1], [0.2, 0], [0.25, 1], [0.3, 1], [0.2, 1], [0.15, 1]],
    ),
    (
        "reliable_but_unskilled",
        "reliability without skill — must read not_yet_skillful, never well-calibrated",
        10,
        [[0.5, 1], [0.5, 1], [0.5, 1], [0.5, 0], [0.5, 0], [0.5, 1], [0.5, 1], [0.5, 0]],
    ),
    (
        "authoritative",
        "n>=12 and Brier<=0.15 — the only path to the top label",
        10,
        [
            [0.95, 1],
            [0.9, 1],
            [0.92, 1],
            [0.88, 1],
            [0.05, 0],
            [0.1, 0],
            [0.08, 0],
            [0.12, 0],
            [0.9, 1],
            [0.07, 0],
            [0.93, 1],
            [0.06, 0],
            [0.91, 1],
            [0.09, 0],
        ],
    ),
    (
        "boundary_probabilities",
        "p==0.0 and p==1.0 must land in the first/last bin, not off the end",
        10,
        [[0.0, 0], [1.0, 1], [0.1, 0], [0.9, 1], [0.5, 1], [0.0, 1], [1.0, 0]],
    ),
    (
        "malformed_dropped",
        "out-of-range / non-binary / unparseable entries are dropped, never coerced",
        10,
        [[0.8, 1], [1.5, 1], [-0.2, 0], [0.4, 2], ["x", 1], [0.6, 0], [0.7, 1], [0.3, 0], [0.55, 1]],
    ),
    (
        "five_bins",
        "n_bins is a parameter — the same pairs must re-bin identically everywhere",
        5,
        [[0.05, 0], [0.25, 0], [0.45, 1], [0.65, 1], [0.85, 1], [0.95, 1], [0.35, 0], [0.75, 1]],
    ),
    (
        "rounding_sensitive",
        "means that land on a rounding tie — the half-to-even trap the JS port has to reproduce",
        10,
        [[0.125, 1], [0.125, 0], [0.375, 1], [0.375, 0], [0.6875, 1], [0.6875, 0], [0.8125, 1], [0.8125, 0]],
    ),
]

CONFIDENCE_CASES = [
    None,
    0.4,
    0,
    1,
    2.5,
    -1.0,
    True,
    False,
    "0.4",
    "40%",
    " 0.7 ",
    "85%",
    "HIGH",
    "very low",
    "Medium",
    "moderate",
    "not a number",
    "",
    "1e-1",
    "  ",
    "nan",
    "inf",
    "-inf",
    "0.5%",
    "100%",
]

OUTCOME_CASES = [
    "confirmed",
    "CONFIRMED",
    " confirming ",
    "refuted",
    "Refuted",
    "pending",
    "inconclusive",
    "expired",
    "",
    None,
    0,
    False,
    "hit",
]

PREDICTION_RECORD_CASES = [
    (
        "mixed_statuses",
        [
            {"confidence": 0.8, "status": "confirmed"},
            {"confidence": 0.6, "status": "refuted"},
            {"confidence": 0.7, "status": "pending"},
            {"confidence": "high", "outcome": "confirmed"},
            {"status": "refuted"},
            {"confidence": 0.9, "status": "inconclusive"},
        ],
    ),
    ("empty", []),
]

CALIBRATION_ROW_CASES = [
    (
        "word_confidence_and_forecast_rows_skipped",
        [
            {"stated_confidence": "high", "outcome": "confirmed"},
            {"stated_confidence": "low", "outcome": "refuted"},
            {"stated_confidence": "medium", "outcome": "pending"},
            {"record_type": "forecast_resolution", "confidence": 0.8, "covered": True},
            {"stated_confidence": 0.42, "outcome": "confirming"},
        ],
    ),
]

FORECAST_ROW_CASES = [
    (
        "interval_coverage",
        [
            {"record_type": "forecast_resolution", "confidence": 0.8, "covered": True},
            {"record_type": "forecast_resolution", "confidence": 0.8, "covered": False},
            {"record_type": "forecast_resolution", "confidence": 0.5},
            {"stated_confidence": "high", "outcome": "confirmed"},
            {"record_type": "forecast_resolution", "confidence": "95%", "covered": True},
        ],
    ),
]

# Adapter-only (package + JS port): the paste box.
LEDGER_TEXT_CASES = [
    ("bare_csv", "0.8,confirmed\n0.6,refuted\n0.9,hit\n0.2,miss"),
    ("headered_csv", "date,confidence,outcome\n2026-01-01,0.8,confirmed\n2026-01-02,60%,refuted"),
    ("tsv", "confidence\toutcome\n0.75\tyes\n0.25\tno"),
    ("percent_and_words", "high,confirmed\nlow,refuted\n80,confirmed\n0.5,pending"),
    ("comments_and_blanks", "# my coach's calls\n\n0.7,yes\n\n  \n0.3,no\n"),
    ("rejects", "0.8,maybe\nbanana,confirmed\n1.5,confirmed\nonlyonefield\n,confirmed\n0.9,confirmed"),
    ("all_unresolved", "0.8,pending\n0.6,tbd\n0.4,n/a"),
    ("quoted_fields", '"0.8","confirmed"\n"0.4","refuted"'),
    ("empty", ""),
]

# Python's round() is half-to-EVEN on the exact binary value. These are the cases
# where a naive JS Math.round / toFixed port silently disagrees.
ROUND_CASES = [
    (0.125, 2),
    (0.135, 2),
    (2.675, 2),
    (1.005, 2),
    (0.15, 1),
    (0.25, 1),
    (0.35, 1),
    (2.5, 1),
    (0.0005, 3),
    (0.00005, 4),
    (1.0 / 3.0, 4),
    (2.0 / 3.0, 4),
    (0.1 + 0.2, 4),
    (-0.125, 2),
    (-2.675, 2),
    (100.0 / 7.0, 1),
    (0.0, 4),
    (1.0, 2),
    (0.9995, 3),
    (0.20585, 4),
]


def build():
    oss = load_oss_module()

    core_cases = [
        {
            "id": cid,
            "description": desc,
            "n_bins": n_bins,
            "pairs": pairs,
            "expected": platform_core.score_pairs([tuple(p) for p in pairs], n_bins=n_bins),
        }
        for (cid, desc, n_bins, pairs) in SCORE_CASES
    ]

    confidence_cases = [{"input": v, "expected": platform_core.normalize_confidence(v)} for v in CONFIDENCE_CASES]
    outcome_cases = [{"input": v, "expected": platform_core.outcome_to_binary(v)} for v in OUTCOME_CASES]

    record_cases = []
    for cid, records in PREDICTION_RECORD_CASES:
        record_cases.append(
            {
                "id": f"prediction_records/{cid}",
                "kind": "prediction_records",
                "records": records,
                "expected_pairs": [list(p) for p in platform_core.pairs_from_prediction_records(records)],
            }
        )
    for cid, rows in CALIBRATION_ROW_CASES:
        record_cases.append(
            {
                "id": f"calibration_rows/{cid}",
                "kind": "calibration_rows",
                "records": rows,
                "expected_pairs": [list(p) for p in platform_core.pairs_from_calibration_rows(rows)],
            }
        )
    for cid, rows in FORECAST_ROW_CASES:
        record_cases.append(
            {
                "id": f"forecast_resolution_rows/{cid}",
                "kind": "forecast_resolution_rows",
                "records": rows,
                "expected_pairs": [list(p) for p in platform_core.pairs_from_forecast_resolution_rows(rows)],
            }
        )

    ledger_cases = [{"id": cid, "text": text, "expected": oss.parse_ledger_text(text)} for (cid, text) in LEDGER_TEXT_CASES]
    round_cases = [{"x": x, "nd": nd, "expected": round(x, nd)} for (x, nd) in ROUND_CASES]

    return {
        "schema": "calibration-core/test-vectors@1",
        "issue": "https://github.com/averagejoematt/life-platform/issues/1396",
        "note": (
            "Shared parity fixture. `core_cases`, `confidence_cases`, `outcome_cases` and "
            "`record_cases` are generated from the deployed platform grader "
            "(lambdas/calibration_core.py) and must be reproduced EXACTLY — not within a "
            "tolerance — by the extracted Python package and the JS port. `adapter_cases` "
            "cover the paste-a-ledger input layer that only the package and the JS port "
            "have; those are generated from the package and are two-way Python <-> JS. "
            "Regenerate with scripts/gen_calibration_vectors.py."
        ),
        "core_cases": core_cases,
        "confidence_cases": confidence_cases,
        "outcome_cases": outcome_cases,
        "record_cases": record_cases,
        "adapter_cases": {
            "ledger_text_cases": ledger_cases,
            "round_cases": round_cases,
        },
    }


def main() -> int:
    payload = build()
    os.makedirs(os.path.dirname(VECTORS_PATH), exist_ok=True)
    with open(VECTORS_PATH, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")
    n = len(payload["core_cases"])
    print(f"wrote {VECTORS_PATH}: {n} core cases, {len(payload['confidence_cases'])} confidence, {len(payload['outcome_cases'])} outcome")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
