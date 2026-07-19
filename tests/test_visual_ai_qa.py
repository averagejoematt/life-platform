"""
tests/test_visual_ai_qa.py — tiered AI-vision QA (#1428).

Covers:
  - visual_qa.ai_qa_targets(): the pure tier-filter the deploy-time gate uses to
    restrict Claude-vision assessment to tier-1 pages, without touching which
    pages the deterministic Playwright sweep covers.
  - qa_manifest.visual_pages() carries `tier` through to every entry (deploy-time
    and weekly runs both read it off the harness's captured results).
  - visual_ai_qa.assess_results()'s budget-gate (mirrors the #1440 pattern already
    proven for assess_reader_truth): a tier>=1 pause makes NO Bedrock call, tags
    every result SKIPPED-BY-BUDGET, emits the QAPausedByBudget metric, and returns
    an explicit status dict — never a per-page "AI-QA error" swallowing the pause.
  - the normal (tier 0) path still merges high/med/low verdicts exactly as before.
"""

import json
import os
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)  # for `import visual_qa`, `import visual_ai_qa`, `import qa_manifest`

import boto3  # noqa: E402
import budget_guard  # noqa: E402  (lambdas/ on sys.path via conftest)
import qa_manifest  # noqa: E402
import visual_ai_qa  # noqa: E402
import visual_qa  # noqa: E402

# ── ai_qa_targets: the pure tier filter ────────────────────────────────────────


def _r(path, tier):
    return {"page": path, "path": path, "tier": tier, "status": "PASS", "issues": [], "warnings": [], "screenshots": []}


def test_ai_qa_targets_none_returns_everything_unfiltered():
    results = [_r("/", 1), _r("/data/vitals/", 2), _r("/gear/", 3)]
    assert visual_qa.ai_qa_targets(results, None) is results  # identity — no filtering work at all


def test_ai_qa_targets_restricts_to_max_tier():
    results = [_r("/", 1), _r("/cockpit/", 1), _r("/data/vitals/", 2), _r("/gear/", 3)]
    tier1 = visual_qa.ai_qa_targets(results, 1)
    assert {r["path"] for r in tier1} == {"/", "/cockpit/"}


def test_ai_qa_targets_max_tier_2_includes_tiers_1_and_2():
    results = [_r("/", 1), _r("/data/vitals/", 2), _r("/gear/", 3), _r("/404.html", 4)]
    tier2 = visual_qa.ai_qa_targets(results, 2)
    assert {r["path"] for r in tier2} == {"/", "/data/vitals/"}


def test_ai_qa_targets_missing_tier_defaults_to_included_not_dropped():
    """An untiered result (tier=None/absent) must never silently vanish from AI
    coverage — treat it as tier 0 (always in scope), not excluded by accident."""
    results = [{"page": "x", "path": "/x/", "tier": None, "status": "PASS", "issues": [], "warnings": [], "screenshots": []}]
    assert visual_qa.ai_qa_targets(results, 1) == results


def test_ai_qa_targets_deploy_time_restricts_to_exactly_the_six_doors():
    """The concrete #1428 acceptance case: --ai-qa-max-tier 1 over the real
    manifest-derived PAGES restricts to exactly the tier-1 flagship doors."""
    results = [_r(p["path"], p["tier"]) for p in visual_qa.PAGES]
    tier1 = visual_qa.ai_qa_targets(results, 1)
    assert {r["path"] for r in tier1} == {"/", "/cockpit/", "/data/", "/story/", "/coaching/", "/protocols/"}


# ── qa_manifest.visual_pages() carries tier ────────────────────────────────────


def test_visual_pages_carry_tier():
    for p in qa_manifest.visual_pages():
        assert "tier" in p and p["tier"] in (1, 2, 3, 4), p


def test_visual_qa_pages_match_manifest_tiers():
    by_path = {m["path"]: m["tier"] for m in qa_manifest.MANIFEST}
    for p in visual_qa.PAGES:
        base = p["path"].split("#")[0]
        assert p["tier"] == by_path[base], f"{p['path']}: visual_qa tier {p['tier']} != manifest tier {by_path[base]}"


# ── assess_results: the #1440-style budget gate (#1428) ────────────────────────


class _CW:
    """Fake CloudWatch client — records put_metric_data calls."""

    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


def _patch_cw(monkeypatch):
    cw = _CW()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: cw)
    return cw


_OK_VERDICT = {"renders_ok": True, "charts_populated": "yes", "issues": [], "severity": "ok", "summary": "looks fine"}
_HIGH_VERDICT = {
    "renders_ok": False,
    "charts_populated": "no",
    "issues": [{"type": "chart", "severity": "high", "note": "blank chart frame"}],
    "severity": "high",
    "summary": "chart frame drawn but empty",
}
_MED_VERDICT = {
    "renders_ok": True,
    "charts_populated": "yes",
    "issues": [{"type": "text", "severity": "med", "note": "slightly clipped label"}],
    "severity": "med",
    "summary": "minor clipping",
}


def _fake_bedrock(payload, calls=None):
    def invoke(body, model_name=None):
        if calls is not None:
            calls.append({"body": body, "model_name": model_name})
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    return type("B", (), {"invoke": staticmethod(invoke)})()


def _result_with_shot(tmp_path, name="Cockpit", path="/cockpit/", tier=1):
    shot = tmp_path / f"{name}.png"
    shot.write_bytes(b"\x89PNG" + b"0" * 300)  # > 256 bytes so it isn't filtered as a zero-crop
    return {
        "page": name,
        "path": path,
        "tier": tier,
        "status": "PASS",
        "issues": [],
        "warnings": [],
        "screenshots": [{"kind": "page", "path": str(shot)}],
    }


def test_assess_results_ok_path_still_merges_high_verdict(tmp_path, monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _fake_bedrock(_HIGH_VERDICT))
    results = [_result_with_shot(tmp_path)]
    status = visual_ai_qa.assess_results(results)
    assert status == {"status": "ok"}
    assert results[0]["status"] == "FAIL"
    assert any("AI-vision (high)" in i for i in results[0]["issues"])


def test_assess_results_med_verdict_warns_but_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _fake_bedrock(_MED_VERDICT))
    results = [_result_with_shot(tmp_path)]
    visual_ai_qa.assess_results(results)
    assert results[0]["status"] == "PASS"
    assert any("AI-vision (med)" in w for w in results[0]["warnings"])


def test_assess_results_budget_paused_makes_no_bedrock_call(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)  # internal QA band cutoff
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _fake_bedrock(_HIGH_VERDICT, calls=calls))
    results = [_result_with_shot(tmp_path)]
    status = visual_ai_qa.assess_results(results)
    assert calls == [], "no Bedrock spend while the internal-QA band is paused"
    assert status == {"status": "skipped_by_budget", "tier": 1}
    assert results[0]["status"] == "PASS"  # never fabricated FAIL from a paused run
    assert "ai_verdict" not in results[0]  # never fabricated a verdict either


def test_assess_results_budget_paused_tags_results_skipped_by_budget(monkeypatch):
    results = [{"page": "x", "path": "/x/", "tier": 1, "status": "PASS", "issues": [], "warnings": [], "screenshots": []}]

    def _boom(*a, **k):
        raise AssertionError("must not call Bedrock while budget-paused")

    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: type("B", (), {"invoke": staticmethod(_boom)})())
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)
    visual_ai_qa.assess_results(results)
    assert any(w.startswith("SKIPPED-BY-BUDGET:") for w in results[0]["warnings"])


def test_assess_results_budget_paused_emits_qa_paused_metric(tmp_path, monkeypatch):
    cw = _patch_cw(monkeypatch)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 1)
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _fake_bedrock(_HIGH_VERDICT))
    results = [_result_with_shot(tmp_path)]
    visual_ai_qa.assess_results(results)
    assert cw.calls, "a budget-tier pause must emit the QAPausedByBudget metric (#1428, mirrors #1440)"
    call = cw.calls[-1]
    assert call["Namespace"] == "LifePlatform/QA"
    assert call["MetricData"][0]["MetricName"] == "QAPausedByBudget"


def test_assess_results_no_bedrock_client_returns_unavailable_status(tmp_path, monkeypatch):
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: None)
    results = [_result_with_shot(tmp_path)]
    status = visual_ai_qa.assess_results(results)
    assert status == {"status": "unavailable", "detail": "bedrock_client unavailable"}
    assert any("bedrock_client unavailable" in w for w in results[0]["warnings"])


# ── budget_guard ladder: visual_ai_qa classified in the internal (band-1) tier ──


def test_visual_ai_qa_feature_is_band1_internal_cutoff():
    assert budget_guard._FEATURE_CUTOFF["visual_ai_qa"] == 1
