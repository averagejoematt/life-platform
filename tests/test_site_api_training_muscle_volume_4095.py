"""tests/test_site_api_training_muscle_volume_4095.py — the public `/api/training_overview`
per-muscle counter agrees with the MCP tool over the same window (#4095, the #4071 bug on the
public path).

THE BUG
  `lambdas/web/site_api_training._compute_muscle_volume` carried its own name-keyword table
  (`_MUSCLE_MAP`) that credited EVERY muscle named in a matched row at 1.0 — the same defect
  #4071 fixed in the MCP path. #4095 deletes that duplicate and makes `_compute_muscle_volume`
  delegate to `training.muscle_volume.working_sets_by_muscle`, the ONE per-muscle computation
  the #4071 derivation guard (`tests/test_muscle_volume_working_sets_4071.py`) now also
  scopes over `lambdas/web/`.

THIS FILE
  1. A bench-press-only week reads Chest direct, Triceps 0.5 secondary, Biceps absent (0) —
     the acceptance fixture named in #4095.
  2. The site path (`_compute_muscle_volume`) and the MCP tool
     (`mcp.tools_strength.tool_get_muscle_volume`) agree, set for set, over the identical raw
     Hevy rows and the identical window — proving there is really one computation under both
     doors, not two that happen to match today.
"""

from __future__ import annotations

import os
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "lambdas"))

os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "test-table")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from web.site_api_training import _compute_muscle_volume  # noqa: E402

import mcp.tools_strength as ts  # noqa: E402

PK = "USER#matthew#SOURCE#hevy"
BENCH_TID = "79D0BD87"  # Bench Press (Barbell) -> Chest (primary) + Triceps 0.5 (#4071)


def _set(kind: str = "normal", kg: float = 60.0, reps: int = 8, i: int = 0) -> dict:
    return {"type": kind, "weight_kg": kg, "reps": reps, "rpe": None, "set_index": i}


def _bench_week(start="2026-09-15", uid="bw1", n_sets=4) -> list[dict]:
    return [
        {
            "pk": PK,
            "sk": f"DATE#{start}#WORKOUT#{uid}",
            "date": start,
            "phase": "experiment",
            "exercises": [
                {
                    "name": "Bench Press (Barbell)",
                    "template_id": BENCH_TID,
                    "notes": "",
                    "sets": [_set("normal", 60.0, 8, i) for i in range(n_sets)],
                }
            ],
        }
    ]


# ── acceptance fixture: bench-only week ──────────────────────────────────────
def test_bench_only_week_reads_chest_direct_triceps_half_biceps_absent():
    hevy_items = _bench_week(n_sets=4)
    out = _compute_muscle_volume(hevy_items, num_weeks=1, start_date="2026-09-15", end_date="2026-09-21")
    muscles = {row["muscle"]: row for row in out}

    assert muscles["Chest"]["total_sets"] == 4
    assert muscles["Chest"]["sets_per_week"] == 4.0

    assert muscles["Triceps"]["total_sets"] == 2.0  # 4 sets x 0.5 secondary, no direct triceps work
    assert muscles["Triceps"]["sets_per_week"] == 2.0

    assert "Biceps" not in muscles  # absence is the honest 0 (ADR-104) — bench touches no biceps


# ── site and MCP agree on the same window ────────────────────────────────────
def test_site_and_mcp_agree_on_the_same_window(monkeypatch):
    hevy_items = _bench_week(n_sets=4) + [
        {
            "pk": PK,
            "sk": "DATE#2026-09-17#WORKOUT#bw2",
            "date": "2026-09-17",
            "phase": "experiment",
            "exercises": [
                {
                    "name": "Romanian Deadlift (Barbell)",
                    "template_id": "2B4B7310",
                    "notes": "",
                    "sets": [_set("normal", 100.0, 6, i) for i in range(3)] + [_set("warmup", 40.0, 10, 3)],
                }
            ],
        }
    ]
    start_date, end_date = "2026-09-15", "2026-09-21"

    site_out = {row["muscle"]: row for row in _compute_muscle_volume(hevy_items, num_weeks=1, start_date=start_date, end_date=end_date)}

    monkeypatch.setattr(ts, "_read_hevy_all_phases", lambda s, e: (hevy_items, ["experiment"]))
    mcp_out = ts.tool_get_muscle_volume({"start_date": start_date, "end_date": end_date})
    mcp_muscles = mcp_out["muscle_volume"]

    # every muscle the site reports has a non-zero total, and it matches the MCP figure exactly
    checked = 0
    for muscle, row in site_out.items():
        assert mcp_muscles[muscle]["total_sets"] == row["total_sets"], f"{muscle}: site {row['total_sets']} vs mcp {mcp_muscles[muscle]}"
        checked += 1
    assert checked >= 3, "the fixture must exercise more than one muscle for this to mean anything"

    # RDL's primary is Hamstrings, secondary Glutes at 0.5 (#4071 taxonomy) — 3 working sets,
    # 1 warmup excluded.
    assert site_out["Hamstrings"]["total_sets"] == mcp_muscles["Hamstrings"]["total_sets"] == 3.0
    assert site_out["Glutes"]["total_sets"] == mcp_muscles["Glutes"]["total_sets"] == 1.5
    assert site_out["Chest"]["total_sets"] == mcp_muscles["Chest"]["total_sets"] == 4.0
