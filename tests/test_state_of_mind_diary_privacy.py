"""tests/test_state_of_mind_diary_privacy.py — State of Mind and the video diary are private activity
(owner rulings 2026-11-05), classified by source identity + field through common.activity_publication.

The rulings: "Treat How We Feel / State of Mind as private. Remove its activity, last-sync date, status
and other revealing metadata from public surfaces, while preserving authorized internal access."
"Classify video-diary sessions as private journal activity by default."

Every value in this file is SYNTHETIC (relative dates, invented valences and counts).

THE INFERENCE TEST (`tests/journal_activity_route_walk.py --axis mind`). Three tables that differ ONLY in
the State-of-Mind check-ins (every som_* aggregate the ingest writes, a state_of_mind partition row, the
HAE per-datatype liveness row), the daily diary-session count, unconsented video-diary rows, a diary-day
hypothesis and its graded calibration row, and the weekly correlation record + what-changed snapshot the
REAL producer computes from a series whose private metrics vary — every public GET route walked against
each with the clock frozen. Every body must be byte-identical, and so must the set of them.

NEGATIVE CONTROLS. (1) `--ungated` (the policy publishes everything) must move the policy-governed routes
(asserted below). (2) The same `--axis mind` walk against origin/main fee6da359 (run for the PR, not
re-run here): 9 routes moved — /api/calibration, /api/correlations, /api/diary_shelf, /api/hypotheses,
/api/intelligence_summary, /api/mind_overview, /api/pulse, /api/source_freshness, /api/status.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common import (
    activity_publication as AP,  # noqa: E402
    narrative_provenance as NP,  # noqa: E402
)

NOW = "2026-11-03T20:00:00+00:00"
VARIANTS = ("none", "daily", "gaps")
# Strings that must never reach the wire from the varied private rows.
# (`mood_valence` is not here: it is also the evening ritual's own public 0-4 tap on /api/fulfillment_ritual.)
DIRECT_TOKENS = ("som_", "Synthetic Association", "Synthetic, Labels", "diary_sessions", "diary_day", "hyp_synthetic_diary", "values_lived")


def _walk(*args) -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tests" / "journal_activity_route_walk.py"), "--axis", "mind", "--now", NOW, *args],
        capture_output=True,
        text=True,
        timeout=300,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stderr[-3000:]
    return json.loads(proc.stdout.strip().splitlines()[-1])


@pytest.fixture(scope="module")
def walks() -> dict:
    return {v: _walk("--variant", v) for v in VARIANTS}


@pytest.fixture(scope="module")
def ungated() -> dict:
    return {v: _walk("--variant", v, "--ungated") for v in ("none", "daily")}


def _moved(runs: dict) -> list:
    base = runs["none"]["bodies"]
    return sorted(k for k in base if any(r["bodies"].get(k) != base[k] for r in runs.values()))


# ── the inference test ────────────────────────────────────────────────────────────────────


def test_no_public_route_moves_with_state_of_mind_or_diary_activity(walks):
    for v, out in walks.items():
        assert out["routes"] >= 140 and out["answered"] >= out["routes"] - 3, (v, out["routes"], out["answered"])
        assert out["raised"] == {} and out["unparsed_queries"] == 0, (v, out["raised"])
    assert _moved(walks) == [], "public routes whose body changes with State of Mind / diary activity alone"

    def digest(out):
        return hashlib.sha256(json.dumps(out["bodies"], sort_keys=True).encode()).hexdigest()

    assert len({digest(walks[v]) for v in VARIANTS}) == 1


def test_no_direct_state_of_mind_or_diary_token_reaches_any_route(walks):
    for v, out in walks.items():
        for key, body in out["bodies"].items():
            hits = [t for t in DIRECT_TOKENS if t in body]
            assert not hits, (v, key, hits)


def test_the_walk_is_not_vacuous(walks):
    b = {k: json.loads(v)["body"] for k, v in walks["daily"]["bodies"].items()}
    pairs = b["/api/correlations"]["correlations"]["pairs"]
    assert len(pairs) >= 15 and all(
        AP.correlation_metric_is_public(p["field_a"]) and AP.correlation_metric_is_public(p["field_b"]) for p in pairs
    )
    assert [h["hypothesis_id"] for h in b["/api/hypotheses"]["hypotheses"]] == ["hyp_synthetic_public"]
    ah = next(s for s in b["/api/source_freshness"]["sources"] if s["id"] == "apple_health")
    assert {d["key"] for d in ah["datatypes"]} == {"steps", "water"}
    status_names = {c["name"] for g in b["/api/status"]["groups"] for c in g["components"]}
    assert "Apple Health Import" in status_names and "State of Mind Data (Health Export)" not in status_names
    assert "mind" not in b["/api/pulse"]["pulse"]["glyphs"]
    assert not {"avg_valence", "mood_entries_count"} & set(b["/api/mind_overview"]["mind"]) and "mood_trend" not in b["/api/mind_overview"]
    assert "withheld" not in b["/api/diary_shelf"]["shelf"]


def test_mutation_control_ungated_policy_moves_the_routes(ungated):
    moved = _moved(ungated)
    for route in (
        "/api/status",
        "/api/source_freshness",
        "/api/correlations",
        "/api/hypotheses",
        "/api/calibration",
        "/api/intelligence_summary",
    ):
        assert route in moved, (route, moved)


# ── the classification ───────────────────────────────────────────────────────────────────


def test_every_state_of_mind_field_the_ingest_writes_is_private_and_apple_health_stays_public():
    from ingestion import health_auto_export_lambda as hae

    payload = {
        "data": {
            "stateOfMind": [
                {"date": "2026-10-01 08:00:00 -0700", "valence": 0.25, "kind": "dailyMood", "labels": ["Calm"], "associations": ["Work"]}
            ]
        }
    }
    _entries, agg = hae.process_state_of_mind(payload)
    written = set().union(*(set(v) for v in agg.values()))
    assert written == set(AP.STATE_OF_MIND_FIELDS), "classify the new State-of-Mind field in activity_publication"
    assert AP.source_is_public("apple_health") and AP.field_is_public("apple_health", "steps")
    for f in written:
        assert not AP.field_is_public("apple_health", f), f
        assert AP.field_family("apple_health", f) == "state_of_mind" and NP.classify("state_of_mind") == NP.PRIVATE
    assert not AP.field_is_public("computed_metrics", "diary_sessions") and AP.field_is_public("computed_metrics", "day_grade_score")


def test_every_hae_datatype_is_classified_by_its_fields():
    from ingestion.source_registry import SOURCE_REGISTRY

    keys = [d["key"] for d in SOURCE_REGISTRY["apple_health"]["hae_datatypes"]]
    private = [k for k in keys if not AP.hae_datatype_is_public({"key": k})]
    assert private == ["state_of_mind"], private
    assert not AP.hae_datatype_is_public({"key": "a_stream_added_tomorrow"})  # undeclared: fail closed
    assert AP.public_hae_datatypes(None) is None


def test_every_correlation_metric_and_hypothesis_metric_and_day_grade_component_is_classified():
    src = (ROOT / "lambdas/compute/weekly_correlation_compute_lambda.py").read_text()
    series_metrics = set(re.findall(r'metrics\["(\w+)"\]\s*=', src))
    assert {"hrv", "mood_valence", "diary_sessions"} <= series_metrics  # the parser reads the real assignments
    assert series_metrics == set(AP.CORRELATION_METRIC_FAMILIES), "classify the new correlation metric (unlisted = private)"
    from compute import hypothesis_engine_lambda as HE
    from health import scoring_engine as SE

    assert set(HE.SPEC_METRICS) == set(AP.HYPOTHESIS_METRIC_FAMILIES), "classify the new hypothesis metric (unlisted = private)"
    assert set(SE.COMPONENT_SCORERS) == set(AP.DAY_GRADE_COMPONENT_FAMILIES), "classify the new day-grade component"
    private_corr = sorted(m for m in AP.CORRELATION_METRIC_FAMILIES if not AP.correlation_metric_is_public(m))
    assert private_corr == ["diary_sessions", "mood_valence", "values_lived_count"]
    private_hyp = sorted(m for m in AP.HYPOTHESIS_METRIC_FAMILIES if not AP.hypothesis_metric_is_public(m))
    assert private_hyp == ["diary_day", "energy", "journal_stress", "mood"]
    assert [c for c in AP.DAY_GRADE_COMPONENT_FAMILIES if not AP.day_grade_component_is_public(c)] == ["journal"]
    assert not AP.correlation_metric_is_public("a_metric_added_tomorrow") and not AP.hypothesis_metric_is_public(None)


def _pair(a, b, p):
    return {"metric_a": a, "metric_b": b, "pearson_r": 0.5, "n_days": 30, "p_value": p, "fdr_significant": False}


def test_public_correlations_rerun_the_fdr_over_the_public_family_only():
    """Invariance: vary ONLY the private pairs' p-values (absent / tiny / large) and the public pairs'
    served significance is identical. Mutation control: the stored single-family flags DO differ, so
    without the re-run a private p-value moves a public flag."""
    public = {"hrv_vs_recovery": _pair("hrv", "recovery_score", 0.012), "steps_vs_hrv": _pair("steps", "hrv", 0.03)}
    outs, single_family = set(), set()
    for private_p in (None, 0.0001, 0.9):
        corrs = dict(public)
        if private_p is not None:
            corrs.update(
                {
                    f"priv{i}": _pair(m, "habit_pct", private_p)
                    for i, m in enumerate(("mood_valence", "diary_sessions", "values_lived_count"))
                }
            )
        served = AP.public_correlations(corrs)
        assert set(served) == set(public)
        outs.add(json.dumps(served, sort_keys=True))
        from common import stats_core

        labels = list(corrs)
        adj = stats_core.bh_fdr([corrs[k]["p_value"] for k in labels])
        single_family.add(tuple(a <= 0.05 for k, a in zip(labels, adj) if k in public))
    assert len(outs) == 1
    assert len(single_family) > 1, "the control could not move a public flag — the invariance above is vacuous"
    assert AP.public_correlations([_pair("hrv", "recovery_score", 0.01), _pair("mood_valence", "hrv", 0.01)])[0]["metric_a"] == "hrv"


def test_the_producer_corrects_public_and_private_pairs_as_two_families():
    """The weekly producer: the public pairs' stored p_value_fdr / fdr_significant are identical whatever
    the private metrics did (so the newly-unlocked ledger built from them is too)."""
    from compute import weekly_correlation_compute_lambda as WC

    def series(private_on: bool):
        out = {}
        for i in range(30):
            d = f"2026-09-{i + 1:02d}"
            out[d] = {
                "hrv": 40 + i + (i * 7) % 5,
                "recovery_score": 50 + 1.2 * i + (i * 3) % 7,
                "steps": 7000 + 50 * ((i * 5) % 9),
                "habit_pct": 0.5 + 0.01 * ((i * 4) % 11),
                "mood_valence": (0.02 * i - 0.3) if private_on else None,
                "diary_sessions": float(i % 2) if private_on else 0.0,
                "values_lived_count": float(i % 3) if private_on else None,
            }
        return out

    def public_flags(corrs):
        return {k: (v.get("p_value_fdr"), v.get("fdr_significant")) for k, v in corrs.items() if AP.correlation_pair_is_public(v)}

    a, b = WC.compute_correlations(series(False)), WC.compute_correlations(series(True))
    assert public_flags(a) == public_flags(b) and public_flags(a)
    assert any(v.get("p_value") is not None for k, v in b.items() if not AP.correlation_pair_is_public(v))  # the private pairs ran


def test_a_hypothesis_naming_a_private_metric_is_not_public():
    assert not AP.hypothesis_is_public({"test_spec": {"condition_metric": "diary_day", "outcome_metric": "habit_pct"}})
    assert not AP.hypothesis_is_public({"test_spec": {"condition_metric": "hrv", "outcome_metric": "mood"}})
    assert AP.hypothesis_is_public({"test_spec": {"condition_metric": "hrv", "outcome_metric": "recovery"}})
    assert AP.hypothesis_is_public({"hypothesis_id": "v1-era, no spec"})
    assert AP.public_component_scores({"journal": 100, "sleep_quality": 80, "a_component_added_tomorrow": 1}) == {"sleep_quality": 80}


# ── the HAE writer: a State-of-Mind merge never stamps the partition's public ingest instant ──────


class _FakeTable:
    def __init__(self):
        self.updates = []

    def get_item(self, **_kw):
        return {"Item": {}}

    def update_item(self, **kw):
        self.updates.append(kw)


def test_a_state_of_mind_merge_does_not_stamp_webhook_ingested_at(monkeypatch):
    """/api/last_sync publishes apple_health's newest `webhook_ingested_at`, and HAE fires one automation
    per data type — so a stamp on the State-of-Mind merge would publish when a check-in arrived.
    Mutation control: an ordinary merge (steps) still stamps it."""
    from ingestion import health_auto_export_lambda as hae

    t = _FakeTable()
    monkeypatch.setattr(hae, "table", t)
    hae.merge_day_to_dynamo("2026-10-01", {"som_avg_valence": 0.25, "som_check_in_count": 1}, stamp_ingest=False)
    hae.merge_day_to_dynamo("2026-10-01", {"steps": 1000.0})
    som, steps = (set(u["ExpressionAttributeNames"].values()) for u in t.updates)
    assert "webhook_ingested_at" not in som and "som_avg_valence" in som
    assert "webhook_ingested_at" in steps
    tree = ast.parse((ROOT / "lambdas/ingestion/health_auto_export_lambda.py").read_text())
    som_calls = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.For) and isinstance(n.iter, ast.Call) and "som_daily_agg" in ast.unparse(n.iter)
        for n in ast.walk(n)
        if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "merge_day_to_dynamo"
    ]
    assert som_calls and all(any(k.arg == "stamp_ingest" and ast.unparse(k.value) == "False" for k in c.keywords) for c in som_calls)


# ── the public catalogue ─────────────────────────────────────────────────────────────────


def test_state_of_mind_is_not_named_in_the_public_catalogue():
    """/data/data_sources.json, /data/stack.json, /gear/ and the v7 method page are generated from the
    registry's catalogue rows; none may name State of Mind (owner ruling 2026-11-05)."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import v4_build_data_sources as ds

    rows = ds.build()["sources"]
    assert "state_of_mind" not in {r["id"] for r in rows}
    assert not any(re.search(r"state.of.mind", json.dumps(r), re.I) for r in rows)
    for rel in ("site/data/data_sources.json", "site/data/stack.json", "site/gear/index.html", "site/next/method/index.html"):
        assert not re.search(r"state.of.mind", (ROOT / rel).read_text(), re.I), rel
