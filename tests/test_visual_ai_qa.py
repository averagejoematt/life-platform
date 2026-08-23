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
import struct
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)  # for `import visual_qa`, `import visual_ai_qa`, `import qa_manifest`

import boto3  # noqa: E402
import pytest  # noqa: E402
import qa_manifest  # noqa: E402
import visual_ai_qa  # noqa: E402
import visual_qa  # noqa: E402
from ai import budget_guard  # noqa: E402  (lambdas/ on sys.path via conftest)

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


def _png_bytes(w=100, h=100, pad=400):
    """Header-valid PNG bytes: real signature + IHDR carrying (w, h), padded past the
    256-byte zero-crop filter. Only the header is sniffed by _prepare_image for
    in-limit images, so the body can be padding — an OVERSIZED (w, h) exercises the
    dimension check without a multi-megapixel fixture."""
    ihdr = struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + ihdr + b"\x00" * pad


def _result_with_shot(tmp_path, name="Cockpit", path="/cockpit/", tier=1, png=None):
    shot = tmp_path / f"{name}.png"
    shot.write_bytes(png if png is not None else _png_bytes())
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
    assert status == {"status": "ok", "evaluated": 1, "unevaluated": 0, "no_shots": 0}
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
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)  # operator-truth band cutoff (#1927)
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _fake_bedrock(_HIGH_VERDICT, calls=calls))
    results = [_result_with_shot(tmp_path)]
    status = visual_ai_qa.assess_results(results)
    assert calls == [], "no Bedrock spend while the internal-QA band is paused"
    assert status == {"status": "skipped_by_budget", "tier": 3}
    assert results[0]["status"] == "PASS"  # never fabricated FAIL from a paused run
    assert "ai_verdict" not in results[0]  # never fabricated a verdict either


def test_assess_results_budget_paused_tags_results_skipped_by_budget(monkeypatch):
    results = [{"page": "x", "path": "/x/", "tier": 1, "status": "PASS", "issues": [], "warnings": [], "screenshots": []}]

    def _boom(*a, **k):
        raise AssertionError("must not call Bedrock while budget-paused")

    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: type("B", (), {"invoke": staticmethod(_boom)})())
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)
    visual_ai_qa.assess_results(results)
    assert any(w.startswith("SKIPPED-BY-BUDGET:") for w in results[0]["warnings"])


def test_assess_results_budget_paused_emits_qa_paused_metric(tmp_path, monkeypatch):
    cw = _patch_cw(monkeypatch)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 3)
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


# ── budget_guard ladder: visual_ai_qa is an OPERATOR-TRUTH gate (#1927) ──────
# It was cutoff 1 ("internal QA") and therefore did not run on 26 of 30 measured
# days, while the visual-qa job still reported green.


def test_visual_ai_qa_feature_is_operator_truth_cutoff():
    assert budget_guard._FEATURE_CUTOFF["visual_ai_qa"] == budget_guard._HARD_STOP_TIER
    assert "visual_ai_qa" in budget_guard.CI_GATE_FEATURES


def test_visual_ai_qa_runs_at_the_tiers_it_used_to_skip(tmp_path, monkeypatch):
    """#1927 negative test: at tiers 1 and 2 — where the platform actually lives —
    the vision gate must genuinely RUN (Bedrock called, verdict merged), not merely
    fail to report a pause."""
    for tier in (1, 2):
        calls = []
        monkeypatch.setattr(budget_guard, "current_tier", lambda t=tier: t)
        monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _fake_bedrock(_HIGH_VERDICT, calls=calls))
        results = [_result_with_shot(tmp_path, name=f"Cockpit{tier}")]
        status = visual_ai_qa.assess_results(results)
        assert status["status"] == "ok", f"tier {tier} must not skip the vision gate"
        assert status["evaluated"] == 1
        assert calls, f"Bedrock must be called at tier {tier} (#1927)"
        assert results[0]["status"] == "FAIL", "a real high verdict must still gate"


# ── the advisory slop-lens (#1466): structurally incapable of gating ──────────


def test_gloss_flag_alone_never_fails_a_page():
    """A flagged template-gloss verdict with clean rendering = warning only."""
    v = visual_ai_qa._parse_verdict(
        '{"renders_ok": true, "charts_populated": "yes", "issues": [], '
        '"template_gloss": {"flagged": true, "note": "purple-blue gradient hero"}, '
        '"severity": "ok", "summary": "renders fine"}'
    )
    assert v["severity"] == "ok"
    assert v["template_gloss"]["flagged"] is True


def test_gloss_misfiled_inside_issues_is_stripped_before_severity():
    """Prompt rules can't guarantee structure (reference_prompt_structural_guarantees):
    if the model files the gloss finding INSIDE issues[] at high severity, the
    deterministic strip must keep it from flipping the page to FAIL."""
    v = visual_ai_qa._parse_verdict(
        '{"renders_ok": true, "issues": [{"type": "template_gloss", "severity": "high", '
        '"note": "glassmorphism"}], "severity": "high", "summary": "gloss drift"}'
    )
    assert v["issues"] == []
    assert v["severity"] == "ok", "a stated severity unsupported by surviving issues must be demoted"


def test_gloss_strip_never_touches_real_rendering_issues():
    v = visual_ai_qa._parse_verdict(
        '{"renders_ok": false, "issues": [{"type": "blank_chart", "severity": "high", "note": "empty frame"}, '
        '{"type": "ai-template-gloss", "severity": "med", "note": "SaaS grid"}], '
        '"severity": "high", "summary": "broken"}'
    )
    assert [i["type"] for i in v["issues"]] == ["blank_chart"]
    assert v["severity"] == "high"  # the REAL issue still gates


def test_gloss_flag_merges_as_warning_not_issue(tmp_path, monkeypatch):
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: object())
    monkeypatch.setattr(budget_guard, "allow", lambda f: True)
    monkeypatch.setattr(
        visual_ai_qa,
        "_assess_page",
        lambda bedrock, name, path, shots: {
            "renders_ok": True,
            "issues": [],
            "template_gloss": {"flagged": True, "note": "stock template geometry"},
            "severity": "ok",
            "summary": "fine",
        },
    )
    r = _result_with_shot(tmp_path)
    visual_ai_qa.assess_results([r])
    assert r["status"] != "FAIL"
    assert not r.get("issues")
    assert any("slop-lens" in w and "never gating" in w for w in r["warnings"])


def test_prompt_carries_the_lens_and_its_non_gating_contract():
    p = visual_ai_qa._PROMPT
    assert "template_gloss" in p and "#1466" in p
    assert "NEVER counts toward severity" in p


# ── #2973: a page the oracle cannot see is a page with NO coverage ────────────
# Run 32580634729: Bedrock rejected home.png (1440x11827) and protocols.png
# (1440x9200) with ValidationException on messages.0.content.0.image.source —
# both surfaced as ⚠ lines, neither reduced the pass count, and the sweep
# reported green coverage it did not have. These tests pin (a) the loud-fail
# contract, (b) the downscale that removes the cause, (c) the tally arithmetic.


def _rejecting_bedrock(calls=None):
    def invoke(body, model_name=None):
        if calls is not None:
            calls.append(body)
        raise Exception(
            "An error occurred (ValidationException) when calling the InvokeModel operation: "
            "messages.0.content.0.image.source: image dimensions exceed max allowed size"
        )

    return type("B", (), {"invoke": staticmethod(invoke)})()


def test_bedrock_validation_exception_reds_the_page_not_a_warning(tmp_path, monkeypatch):
    """Proof-of-fire: inject the exact production failure shape and assert the
    sweep goes RED — an unevaluated page fails, is never counted among passed."""
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", _rejecting_bedrock)
    results = [_result_with_shot(tmp_path)]
    status = visual_ai_qa.assess_results(results)
    assert status == {"status": "ok", "evaluated": 0, "unevaluated": 1, "no_shots": 0}
    assert results[0]["status"] == "FAIL", "an unevaluated page must FAIL the sweep, never pass silently"
    assert results[0]["ai_unevaluated"]
    assert any("AI-vision UNEVALUATED (#2973)" in i and "ValidationException" in i for i in results[0]["issues"])
    assert not any("AI-QA error" in w for w in results[0]["warnings"]), "the old ⚠-warning shape must be gone"


def test_unevaluated_page_reds_the_sweep_exit_contract(tmp_path, monkeypatch):
    """The full-accounting invariant: passed + failed + unevaluated == P, an
    unevaluated page never lands in `passed`, and the sweep cannot conclude
    success while unevaluated > 0 (run_sweep's exit term)."""
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", _rejecting_bedrock)
    results = [
        _result_with_shot(tmp_path, name="Home", path="/"),
        {"page": "Leak sweep", "path": "(synthetic)", "status": "PASS", "issues": [], "warnings": [], "screenshots": []},
    ]
    visual_ai_qa.assess_results(results)
    passed, failed, unevaluated = visual_qa.sweep_tally(results)
    assert (passed, failed, unevaluated) == (1, 0, 1)
    assert passed + failed + unevaluated == len(results)
    assert not (failed == 0 and unevaluated == 0), "run_sweep's success condition must be False here"


def test_sweep_tally_never_counts_an_unevaluated_page_as_passed():
    """Belt-and-braces: even if a future refactor stops flipping unevaluated pages
    to FAIL, the tally still pulls them out of `passed` and the buckets still sum."""
    results = [
        {"page": "a", "path": "/a/", "status": "PASS", "issues": [], "warnings": []},
        {"page": "b", "path": "/b/", "status": "PASS", "issues": [], "warnings": [], "ai_unevaluated": "boom"},
        {"page": "c", "path": "/c/", "status": "FAIL", "issues": ["x"], "warnings": []},
        {"page": "d", "path": "/d/", "status": "FAIL", "issues": ["y"], "warnings": [], "ai_unevaluated": "boom"},
    ]
    passed, failed, unevaluated = visual_qa.sweep_tally(results)
    assert (passed, failed, unevaluated) == (1, 1, 2)
    assert passed + failed + unevaluated == len(results)


def test_oversized_capture_is_downscaled_and_actually_evaluated(tmp_path, monkeypatch):
    """The cause fix: a capture over Bedrock's 8000px dimension cap is downscaled
    to a valid payload and the page IS evaluated (Bedrock called, verdict merged) —
    not failed, not skipped. Requires Pillow (pinned in requirements-dev.txt; the
    wiring test below keeps it in the CI lanes)."""
    pytest.importorskip("PIL")
    from PIL import Image

    shot = tmp_path / "tall.png"
    Image.new("RGB", (60, 9000), "white").save(shot)
    assert visual_ai_qa._png_dims(shot.read_bytes()) == (60, 9000)

    calls = []
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _fake_bedrock(_OK_VERDICT, calls=calls))
    results = [_result_with_shot(tmp_path, name="Home", path="/", png=shot.read_bytes())]
    status = visual_ai_qa.assess_results(results)

    assert status == {"status": "ok", "evaluated": 1, "unevaluated": 0, "no_shots": 0}
    assert results[0]["status"] == "PASS" and "ai_verdict" in results[0]
    import base64

    sent = base64.b64decode(calls[0]["body"]["messages"][0]["content"][0]["source"]["data"])
    w, h = visual_ai_qa._png_dims(sent)
    assert h <= visual_ai_qa._BEDROCK_MAX_DIM and w >= 1, f"payload still oversized: {w}x{h}"


def test_prepare_image_passes_small_pngs_through_untouched(tmp_path):
    shot = tmp_path / "small.png"
    shot.write_bytes(_png_bytes(w=800, h=600))
    assert visual_ai_qa._prepare_image(str(shot)) == shot.read_bytes()


def test_oversized_capture_without_pillow_is_a_named_loud_failure(tmp_path, monkeypatch):
    """The 'dependency missing makes a gate dark' class (#1927/#2938): if Pillow
    vanishes from a lane, an oversized capture must become a NAMED per-page FAIL
    — never a payload sent for Bedrock to reject, never a silent skip."""
    monkeypatch.setitem(sys.modules, "PIL", None)  # forces `from PIL import Image` to raise
    calls = []
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _fake_bedrock(_OK_VERDICT, calls=calls))
    results = [_result_with_shot(tmp_path, name="Home", path="/", png=_png_bytes(w=1440, h=11827))]
    status = visual_ai_qa.assess_results(results)
    assert calls == [], "must not send a payload Bedrock is guaranteed to reject"
    assert status["unevaluated"] == 1 and status["evaluated"] == 0
    assert results[0]["status"] == "FAIL"
    assert any("Pillow is not installed" in i and "11827" in i for i in results[0]["issues"])


def test_all_empty_captures_is_unevaluated_not_a_fabricated_pass(tmp_path, monkeypatch):
    """Every capture ≤256 bytes used to return a fabricated 'ok' verdict — a page
    the oracle never saw counted as fine. Now: loud, named, FAIL."""
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _fake_bedrock(_OK_VERDICT))
    results = [_result_with_shot(tmp_path, png=b"\x89PNG\r\n\x1a\n")]  # 8 bytes — under the zero-crop filter
    status = visual_ai_qa.assess_results(results)
    assert status["unevaluated"] == 1
    assert results[0]["status"] == "FAIL"
    assert any("no usable screenshots" in i for i in results[0]["issues"])


def test_mid_run_budget_exceeded_is_the_sanctioned_pause_not_page_failures(tmp_path, monkeypatch):
    """A tier-3 flip DURING the sweep is the same deliberate ADR-125 pause the
    upfront check reports — it must never red the deploy path as fabricated
    per-page failures (#1440's contract, extended to the mid-run window)."""
    from ai.budget_guard import BudgetExceeded

    def _budget_stop(body, model_name=None):
        raise BudgetExceeded("AI paused — monthly budget ceiling reached (tier 3).")

    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)  # upfront check passes…
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: type("B", (), {"invoke": staticmethod(_budget_stop)})())
    results = [_result_with_shot(tmp_path, name="Home", path="/"), _result_with_shot(tmp_path, name="Cockpit", path="/cockpit/")]
    status = visual_ai_qa.assess_results(results)
    assert status["status"] == "skipped_by_budget"
    for r in results:
        assert r["status"] == "PASS", "a budget pause must never fabricate page failures"
        assert not r.get("ai_unevaluated")
        assert any("SKIPPED-BY-BUDGET" in w for w in r["warnings"])


def test_pillow_is_wired_into_every_ai_qa_lane():
    """The dep is the trigger; the dark gate is the defect (#2938). Pin the WIRING:
    pillow must be pinned in requirements-dev.txt and installed (via ci_pins.py) in
    each workflow lane that runs --ai-qa, so the downscale path cannot silently
    lose its dependency and start failing pages for a self-inflicted reason."""
    repo = os.path.dirname(_TESTS_DIR)
    with open(os.path.join(repo, "requirements-dev.txt")) as f:
        assert any(line.split("==")[0].strip() == "pillow" for line in f if "==" in line), "pillow not pinned in requirements-dev.txt"
    ai_qa_workflows = [".github/workflows/visual-qa.yml", ".github/workflows/ci-cd.yml", ".github/workflows/site-deploy.yml"]
    for wf in ai_qa_workflows:
        with open(os.path.join(repo, wf)) as f:
            text = f.read()
        assert "--ai-qa" in text, f"{wf} no longer runs --ai-qa — update this test's lane list"
        install_lines = [ln for ln in text.splitlines() if "ci_pins.py" in ln and "playwright" in ln]
        assert install_lines and all(
            "pillow" in ln for ln in install_lines
        ), f"{wf}: the --ai-qa lane's ci_pins install must include pillow"
