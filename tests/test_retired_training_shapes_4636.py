"""#4636 — readers on retired training record shapes.

Three readers kept reading the per-day training shape after Hevy became the per-workout
source: the monthly digest counted 0 of September 2026's 24 sessions, the MCP
periodization volume and muscle-group recency read `macrofactor_workouts` (no writer since
2026-03-07), and `get_workouts` returned the same session twice on 421 days.

This file holds the behaviour pins for each fix AND the guard over the set:

* `test_no_retired_shape_read_outside_the_bridge` sweeps every .py under lambdas/ and mcp/
  (AST) for (a) a string naming the `macrofactor_workouts` partition, (b) a `.get("workouts")`
  / `["workouts"]` read, and (c) an import of the bridge module. Each file that does any of
  these is pinned below with its exact count and the reason it is not a retired-shape
  reader. A new file — or one more occurrence in a pinned file — reds; so does a pin that
  no longer matches (a stale entry is how an allowlist rots into permission).

Fixtures are SYNTHETIC rows built on the stored key set of a live Hevy per-workout row and a
`macrofactor_workouts` per-day row (read-only DynamoDB, 2026-10-09). The stored values are
not committed: the rows carry free-text training notes, and this repo is public.
"""

from __future__ import annotations

import ast
import os
import sys
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("EMAIL_RECIPIENT", "test@example.com")
os.environ.setdefault("EMAIL_SENDER", "test@example.com")

KG_PER_LB = 0.45359237


# ──────────────────────────────────────────────────────────────────────────────
# Row builders — the STORED key set, synthetic values
# ──────────────────────────────────────────────────────────────────────────────


def hevy_row(date: str, wid: str, sets_lbs_reps: list[tuple[float, int]], *, title: str = "Foundation - Push - 1 - 1", phase="experiment"):
    """One live Hevy per-workout row: every top-level key a stored row carries (2026-09)."""
    sets = [
        {
            "weight_kg": lbs * KG_PER_LB,
            "rpe": None,
            "reps": reps,
            "set_index": i,
            "type": "normal",
            "distance_m": None,
            "duration_sec": None,
        }
        for i, (lbs, reps) in enumerate(sets_lbs_reps)
    ]
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{date}#WORKOUT#{wid}",
        "adherence": {"status": "ad_hoc", "matched_routine_id": None, "workout_pacific_date": date},
        "date": date,
        "description": "",
        "duration_sec": 3600,
        "start_time": f"{date}T14:00:00+00:00",
        "end_time": f"{date}T15:00:00+00:00",
        "exercise_count": 1,
        "exercises": [{"template_id": "79D0BB3A", "name": "Bench Press (Barbell)", "notes": "", "sets": sets}],
        "hevy_routine_id": "",
        "ingested_at": f"{date}T16:00:00+00:00",
        "original_unit": "kg",
        "phase": phase,
        "raw_ref": f"s3://bucket/raw/hevy/{wid}.json",
        "schema_version": 2,
        "set_count": len(sets),
        "source": "hevy",
        "source_workout_id": wid,
        "title": title,
        "total_volume_kg": round(sum(lbs * KG_PER_LB * reps for lbs, reps in sets_lbs_reps), 1),
        "workout_uid": f"hevy:{wid}",
    }


def legacy_day_row(date: str, workouts: list[dict]):
    """One `macrofactor_workouts` per-day row — the stored key set of the retired shape."""
    total_sets = sum(len(ex["sets"]) for w in workouts for ex in w["exercises"])
    return {
        "pk": "USER#matthew#SOURCE#macrofactor_workouts",
        "sk": f"DATE#{date}",
        "date": date,
        "source": "macrofactor_workouts",
        "original_source": "hevy",
        "phase": "pilot",
        "schema_version": "1",
        "ingested_at": "2026-02-22T15:46:25Z",
        "migrated_at": "2026-02-22T18:21:46Z",
        "workouts_count": len(workouts),
        "total_sets": total_sets,
        "total_volume_lbs": sum(float(s["weight_lbs"]) * float(s["reps"]) for w in workouts for ex in w["exercises"] for s in ex["sets"]),
        "unique_exercises": len({ex["exercise_name"] for w in workouts for ex in w["exercises"]}),
        "workouts": workouts,
    }


def legacy_workout(name: str, start: str, exercises: list[tuple[str, list[tuple[float, int]]]]):
    return {
        "workout_name": name,
        "start_time": start,
        "workout_duration_min": "40",
        "exercises": [
            {
                "exercise_name": ex,
                "sets": [
                    {"set_type": "normal", "set_index": str(i), "reps": str(r), "weight_lbs": str(w)} for i, (w, r) in enumerate(sets)
                ],
            }
            for ex, sets in exercises
        ],
    }


# ──────────────────────────────────────────────────────────────────────────────
# 1. The monthly digest's strength extractor
# ──────────────────────────────────────────────────────────────────────────────


def _september_rows():
    """24 per-workout rows across September 2026, the count the live partition holds."""
    days = [3, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29]
    return [hevy_row(f"2026-09-{d:02d}", f"wid-{d:02d}", [(135.0, 8), (135.0, 8), (95.0, 10)]) for d in days]


def test_monthly_extractor_counts_per_workout_hevy_rows():
    import emails.monthly_digest_lambda as m

    out = m.ex_hevy(_september_rows())
    assert out is not None
    assert out["workout_count"] == 24
    per = 135 * 8 * 2 + 95 * 10
    assert out["total_volume_lbs"] == 24 * per
    assert out["avg_volume_lbs"] == per


def test_monthly_extractor_ignores_a_tombstoned_per_day_aggregate():
    """A superseded per-day Hevy aggregate is the same sessions again; it must not count."""
    import emails.monthly_digest_lambda as m

    tomb = {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": "DATE#2026-09-03",
        "date": "2026-09-03",
        "tombstone": True,
        "workouts": [{"title": "x", "total_volume_lbs": 9999}],
    }
    out = m.ex_hevy([*_september_rows()[:2], tomb])
    assert out["workout_count"] == 2


def test_monthly_extractor_absence_is_none_not_zero():
    import emails.monthly_digest_lambda as m

    assert m.ex_hevy([]) is None


# ──────────────────────────────────────────────────────────────────────────────
# 2. MCP periodization strength block + muscle-group recency read Hevy
# ──────────────────────────────────────────────────────────────────────────────


class _Reader:
    def __init__(self, **by_source):
        self.data = by_source
        self.calls: list[str] = []

    def __call__(self, source, start_date, end_date, lean=False, include_pilot=None):
        self.calls.append(source)
        return [dict(r) for r in self.data.get(source, []) if start_date <= (r.get("date") or "") <= end_date]


def test_periodization_strength_volume_reads_hevy_after_march(monkeypatch):
    import mcp.tools_training as tt

    rows = [hevy_row("2026-09-21", "a", [(100.0, 10), (100.0, 10)]), hevy_row("2026-09-23", "b", [(200.0, 5)])]
    reader = _Reader(strava=[], hevy=rows)
    monkeypatch.setattr(tt, "query_source", reader)
    monkeypatch.setattr(tt, "get_profile", lambda: {"max_heart_rate": 190})

    out = tt._get_training_periodization({"start_date": "2026-09-14", "end_date": "2026-09-27"})
    assert "macrofactor_workouts" not in reader.calls
    vols = {w["week"]: w["volume_lbs"] for w in out["weekly_breakdown"]}
    assert vols.get("2026-W39") == pytest.approx(3000.0, abs=0.5), vols
    assert out["source"] == "strava + hevy"


def test_muscle_recency_reads_hevy_after_march(monkeypatch):
    import mcp.tools_training as tt

    # The recommendation view reads many partitions; only the strength rows matter here.
    rows = [hevy_row("2026-09-27", "c", [(135.0, 8)])]
    reader = _Reader(hevy=rows)
    monkeypatch.setattr(tt, "query_source", reader)
    monkeypatch.setattr(tt, "get_profile", lambda: {"max_heart_rate": 190})

    out = tt._get_training_recommendation({"date": "2026-09-28"})
    assert "macrofactor_workouts" not in reader.calls
    assert out["muscle_recovery"], out["muscle_recovery"]
    assert {v["last_trained"] for v in out["muscle_recovery"].values()} == {"2026-09-27"}


# ──────────────────────────────────────────────────────────────────────────────
# 3. get_workouts returns one row per session on an overlap day
# ──────────────────────────────────────────────────────────────────────────────


def _overlap_day():
    """2021-11-08, one of the 421 overlap days: the live Hevy row and the archive's per-day row
    carry the same three exercises and the same 10 sets (the stored set totals agree, 10 = 10)."""
    live = hevy_row(
        "2021-11-08", "37b3513c", [(25.0, 8)] * 3 + [(135.0, 10)] * 3 + [(45.0, 12)] * 4, title="Dynamic Effort Lower (Tues)", phase="pilot"
    )
    legacy = legacy_day_row(
        "2021-11-08",
        [
            legacy_workout(
                "Dynamic Effort Lower (Tues)",
                "8 Nov 2021, 22:48",
                [
                    ("Bulgarian Split Squat", [(25, 8)] * 3),
                    ("Deadlift (Barbell)", [(135, 10)] * 3),
                    ("Side Bend (Dumbbell)", [(45, 12)] * 4),
                ],
            )
        ],
    )
    assert live["set_count"] == legacy["total_sets"] == 10
    return live, legacy


def _install_range(monkeypatch, by_source):
    import mcp.tools_hevy as th

    def _q(source, start, end, include_pilot=None):
        return [dict(r) for r in by_source.get(source, []) if start <= r["date"] <= end]

    monkeypatch.setattr(th, "query_source_range", _q)
    return th


def test_get_workouts_returns_one_row_on_an_overlap_day(monkeypatch):
    live, legacy = _overlap_day()
    th = _install_range(monkeypatch, {"hevy": [live], "macrofactor_workouts": [legacy]})
    out = th.tool_get_workouts({"start_date": "2021-11-01", "end_date": "2021-11-30"})
    assert out["total"] == 1, out["workouts"]
    assert out["workouts"][0]["workout_uid"] == "hevy:37b3513c"
    assert out["legacy_days_superseded"] == 1


def test_get_workouts_keeps_an_archive_only_day(monkeypatch):
    """The archive still fills a day the live source does not hold (2026-02-24..03-07)."""
    live, _ = _overlap_day()
    only = legacy_day_row("2026-02-24", [legacy_workout("Upper", "24 Feb 2026, 07:00", [("Row", [(100, 10)])])])
    th = _install_range(monkeypatch, {"hevy": [live], "macrofactor_workouts": [only]})
    out = th.tool_get_workouts({"start_date": "2021-01-01", "end_date": "2026-03-31"})
    assert sorted(w["source"] for w in out["workouts"]) == ["hevy", "macrofactor_export"]
    assert out["legacy_days_superseded"] == 0


def test_get_workouts_archive_filter_still_returns_the_archive(monkeypatch):
    """Asking for the archive explicitly does not read the live source, so nothing supersedes it."""
    live, legacy = _overlap_day()
    th = _install_range(monkeypatch, {"hevy": [live], "macrofactor_workouts": [legacy]})
    out = th.tool_get_workouts({"start_date": "2021-11-01", "end_date": "2021-11-30", "source": "macrofactor_export"})
    assert [w["source"] for w in out["workouts"]] == ["macrofactor_export"]


# ──────────────────────────────────────────────────────────────────────────────
# 4. The guard over the set
# ──────────────────────────────────────────────────────────────────────────────

BRIDGE = "lambdas/training/legacy_workouts.py"
BRIDGE_MODULE = "training.legacy_workouts"

# Files that NAME the retired partition as a string. Reads of the partition go through the
# bridge's LEGACY_WORKOUTS_PARTITION; everything here writes, classifies or registers it.
PARTITION_NAMED: dict[str, tuple[int, str]] = {
    BRIDGE: (1, "the bridge: LEGACY_WORKOUTS_PARTITION, the one place the name lives for readers"),
    "lambdas/ingestion/macrofactor_lambda.py": (2, "the WRITER (Dropbox workout CSV) — its PK and the row's `source`"),
    "lambdas/ingestion/ingestion_validator.py": (1, "the writer's validation schema"),
    "lambdas/experiment/phase_taxonomy.py": (1, "SOURCE_CLASS classification (ADR-077)"),
    "lambdas/ingestion/source_registry.py": (1, "the unregistered-partition ledger entry (a frozen archive)"),
    "lambdas/web/site_api_status.py": (1, "the status board's freshness row — reads the newest key, never the row shape"),
}

# Files that read a nested `workouts` key. Only the bridge reads it off a STORED retired row;
# every other entry reads a different dict that happens to use the same key.
WORKOUTS_KEY_READ: dict[str, tuple[int, str]] = {
    BRIDGE: (2, "the bridge: `data.workouts` (pre-2026-05-26 Hevy aggregates) and `workouts` (macrofactor_workouts)"),
    "lambdas/ai/ai_summaries.py": (1, "the digests' `mf_workouts` summary — built from Hevy per-workout rows (#485)"),
    "lambdas/content/html_builder.py": (1, "the daily brief's `mf_workouts` — fetch_hevy_workouts' Hevy-built aggregate (#485)"),
    "lambdas/emails/weekly_digest_lambda.py": (1, "ex_hevy_workouts' output dict, not a stored row"),
    "lambdas/ingestion/health_auto_export_lambda.py": (1, "the Health Auto Export webhook payload"),
    "lambdas/ingestion/whoop_lambda.py": (1, "the Whoop API fetch bundle"),
    "lambdas/intelligence/ai_expert_analyzer_lambda.py": (1, "a computed briefing-packet count"),
    "lambdas/web/site_api_training.py": (1, "a per-week bucket dict built in the same function"),
    "mcp/hevy_readback_report.py": (2, "the Hevy API's /workouts response"),
    "mcp/plan_draft_evidence.py": (1, "tool_get_workouts' response (live rows + the bridge)"),
}

# Modules allowed to import the bridge.
BRIDGE_IMPORTERS: dict[str, str] = {
    "lambdas/training/muscle_volume.py": "normalize_hevy_items parses tombstoned Hevy per-day aggregates via day_workouts",
    "mcp/tools_hevy.py": "get_workouts' legacy bridge over the archive (live rows win their day, #4636)",
    "lambdas/content/vacation_fund.py": "the opt-in archive mileage source (macrofactor_export)",
    "lambdas/training/routine_title.py": "the honest performed-workout counters union the archive, deduped by workout_uid",
}


def _names_partition(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (node.value == "macrofactor_workouts" or "SOURCE#macrofactor_workouts" in node.value)
    )


def _reads_workouts_key(node: ast.AST) -> bool:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
        a = node.args[0]
        return isinstance(a, ast.Constant) and a.value == "workouts"
    if isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load):
        s = node.slice
        return isinstance(s, ast.Constant) and s.value == "workouts"
    return False


def _imports_bridge(node: ast.AST) -> bool:
    if isinstance(node, ast.ImportFrom):
        return node.module == BRIDGE_MODULE or (node.module == "training" and any(a.name == "legacy_workouts" for a in node.names))
    if isinstance(node, ast.Import):
        return any(a.name == BRIDGE_MODULE for a in node.names)
    return False


def sweep(root: Path = REPO) -> tuple[Counter, Counter, Counter]:
    named, keyed, importers = Counter(), Counter(), Counter()
    for top in ("lambdas", "mcp"):
        for path in sorted((root / top).rglob("*.py")):
            rel = path.relative_to(root).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if _names_partition(node):
                    named[rel] += 1
                if _reads_workouts_key(node):
                    keyed[rel] += 1
                if _imports_bridge(node):
                    importers[rel] += 1
    return named, keyed, importers


def _diff(found: Counter, pinned: dict[str, tuple[int, str]]) -> list[str]:
    bad = []
    for rel, n in sorted(found.items()):
        if rel not in pinned:
            bad.append(f"{rel}: {n} (unpinned)")
        elif pinned[rel][0] != n:
            bad.append(f"{rel}: {n} (pinned {pinned[rel][0]})")
    for rel in sorted(set(pinned) - set(found)):
        bad.append(f"{rel}: 0 (stale pin {pinned[rel][0]})")
    return bad


def test_no_retired_shape_read_outside_the_bridge():
    named, keyed, importers = sweep()
    problems = []
    for b in _diff(named, PARTITION_NAMED):
        problems.append(f"names the macrofactor_workouts partition — {b}")
    for b in _diff(keyed, WORKOUTS_KEY_READ):
        problems.append(f"reads a nested 'workouts' key — {b}")
    for rel in sorted(set(importers) ^ set(BRIDGE_IMPORTERS)):
        problems.append(f"bridge importer set differs at {rel} (found={rel in importers}, pinned={rel in BRIDGE_IMPORTERS})")
    assert not problems, (
        "#4636: the retired per-day training shape is read only through "
        f"{BRIDGE}. A new reader belongs on the live Hevy per-workout rows "
        "(emails.weekly_digest_extractors.ex_hevy_workouts / training.muscle_volume.normalize_hevy_items); "
        "a genuinely different dict needs a pinned entry with its reason.\n  " + "\n  ".join(problems)
    )


def test_the_sweep_sees_each_form(tmp_path):
    """The detectors are not vacuous: each form is seen in a synthetic tree."""
    (tmp_path / "lambdas").mkdir()
    (tmp_path / "mcp").mkdir()
    (tmp_path / "lambdas" / "a.py").write_text('X = query("macrofactor_workouts")\nY = r.get("workouts")\nZ = r["workouts"]\n')
    (tmp_path / "mcp" / "b.py").write_text(
        'from training.legacy_workouts import day_workouts\nPK = f"USER#{u}#SOURCE#macrofactor_workouts"\n'
    )
    named, keyed, importers = sweep(tmp_path)
    assert named == Counter({"lambdas/a.py": 1, "mcp/b.py": 1})
    assert keyed == Counter({"lambdas/a.py": 2})
    assert importers == Counter({"mcp/b.py": 1})
