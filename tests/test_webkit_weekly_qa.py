"""tests/test_webkit_weekly_qa.py — #1434: the weekly ADVISORY WebKit (iOS-Safari
engine) mobile-viewport run.

Two guards:

1. The pure tier filter (visual_qa.sweep_pages) the run selects pages with:
   None = unchanged full coverage (what every existing gating run passes),
   max_tier=2 = flagship doors + live-data topic pages, missing tier = always
   included (an untiered page must never vanish from coverage by accident —
   same semantics as ai_qa_targets, #1428).

2. The structural contract of .github/workflows/webkit-mobile-qa.yml —
   text-based on purpose (CI's `test` job installs no PyYAML; same style as
   test_site_deploy_workflow.py):
     - weekly `schedule:` cron (fixed UTC, repo convention) + workflow_dispatch
     - installs the WEBKIT engine (`playwright install --with-deps webkit`)
     - drives tests/visual_qa.py with --browser webkit --mobile --max-tier 2
     - ADVISORY: no rollback scripts, no deploy scripts, no cdk deploy —
       a red here must never be able to roll back or mutate anything
     - failure surfaces loudly: since #3277 a red run files a tracked issue
       through the #1447 advisory-failure-issue helper (own slug, issues:write,
       last step, if: always() so a green run closes it). The pre-#3277 `aws sns
       publish` is GONE, not fixed: it failed AuthorizationError on every run
       (the diagnosis role has no sns: grant) and six weekly reds — each carrying
       the 390px scrollable-region-focusable finding — reached nobody
     - upload-artifact carries continue-on-error: true (an account-wide
       artifact-quota exhaustion must not red the QA verdict —
       reference_ci_artifact_quota_rollback / #1331 class)
     - the playwright pin matches ci-cd.yml's enforced pin (CQ-01 class drift:
       a different engine version here would make a red mean something else)
"""

import os
import re
import sys
from types import SimpleNamespace

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_WORKFLOW = os.path.join(_REPO, ".github", "workflows", "webkit-mobile-qa.yml")
_CI_CD = os.path.join(_REPO, ".github", "workflows", "ci-cd.yml")

if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import visual_qa  # noqa: E402
from visual_qa import sweep_pages  # noqa: E402

# ── 1. the tier filter ────────────────────────────────────────────────────────


def test_sweep_pages_none_is_identity():
    pages = [{"path": "/", "tier": 1}, {"path": "/x/", "tier": 4}]
    assert sweep_pages(pages, None) is pages  # unchanged object: zero risk to existing gating callers


def test_sweep_pages_max_tier_2_keeps_tier_1_and_2_drops_3_and_4():
    pages = [
        {"path": "/a/", "tier": 1},
        {"path": "/b/", "tier": 2},
        {"path": "/c/", "tier": 3},
        {"path": "/d/", "tier": 4},
    ]
    assert [p["path"] for p in sweep_pages(pages, 2)] == ["/a/", "/b/"]


def test_sweep_pages_missing_tier_always_included():
    pages = [{"path": "/untiered/"}, {"path": "/none/", "tier": None}, {"path": "/late/", "tier": 3}]
    assert [p["path"] for p in sweep_pages(pages, 1)] == ["/untiered/", "/none/"]


def test_sweep_pages_over_manifest_tier_2_is_nonempty_and_excludes_editorial():
    """Non-vacuous against the real manifest: the weekly WebKit selection must
    cover the flagship doors + live-data topic pages and exclude tier-3/4."""
    from qa_manifest import visual_pages

    pages = visual_pages()
    selected = sweep_pages(pages, 2)
    assert len(selected) >= 20, "tier<=2 selection suspiciously small — manifest tiers moved?"
    assert len(selected) < len(pages), "tier filter selected everything — tier facet missing from visual_pages()?"
    assert all(p["tier"] <= 2 for p in selected)
    assert any(p["path"] == "/cockpit/" for p in selected), "flagship door missing from the weekly WebKit selection"


# ── 2. the workflow contract ──────────────────────────────────────────────────


def _workflow_text():
    assert os.path.exists(_WORKFLOW), "webkit-mobile-qa.yml missing — the weekly WebKit run (#1434) is gone"
    with open(_WORKFLOW, encoding="utf-8") as f:
        return f.read()


def test_workflow_is_weekly_scheduled_and_dispatchable():
    text = _workflow_text()
    m = re.search(r"cron:\s*'([^']+)'", text)
    assert m, "no schedule cron in webkit-mobile-qa.yml"
    fields = m.group(1).split()
    assert len(fields) == 5
    # weekly = a specific day-of-week (not '*'), at a fixed UTC minute/hour
    assert fields[4] != "*", f"cron '{m.group(1)}' is not weekly (day-of-week is *)"
    assert fields[0].isdigit() and fields[1].isdigit(), "cron minute/hour must be fixed (UTC, repo convention)"
    assert "workflow_dispatch:" in text, "must be manually triggerable for on-demand iOS-engine checks"


def test_workflow_installs_webkit_and_drives_the_mobile_tier2_sweep():
    text = _workflow_text()
    assert re.search(r"playwright install --with-deps webkit", text), "webkit engine not installed"
    run = re.search(r"python3 tests/visual_qa\.py([^\n]*)", text)
    assert run, "workflow never invokes python3 tests/visual_qa.py"
    args = run.group(1)
    for flag in ("--browser webkit", "--mobile", "--max-tier 2"):
        assert flag in args, f"visual_qa.py invocation missing {flag}: {args.strip()}"


def test_workflow_is_advisory_no_rollback_no_deploy():
    text = _workflow_text()
    for forbidden in ("rollback_site.sh", "rollback_lambda.sh", "cdk deploy", "deploy_lambda.sh", "deploy_site_api.sh", "sync_site_to_s3"):
        assert forbidden not in text, f"advisory workflow must never contain '{forbidden}' — it gates and mutates NOTHING"


def test_workflow_failure_surfaces_loudly():
    """#1434 AC3, re-satisfied by #3277: a red run must reach someone, not just sit
    in the Actions history nobody reads. The original surface was an `aws sns
    publish` and it never delivered once — this workflow's OIDC role
    (github-actions-diagnosis-role) has no sns:Publish, so the call failed
    AuthorizationError and `|| echo ::warning::` swallowed that too, across six
    consecutive reds. The surface is now the #1447 filer; the assertion moved with
    it rather than being deleted."""
    text = _workflow_text()
    assert "uses: ./.github/actions/advisory-failure-issue" in text, "a red run would surface nowhere (#1447 filer missing)"
    # comments narrate the deletion; the assertion is about what the runner EXECUTES.
    executable = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "aws sns publish" not in executable, (
        "the SNS publish is deliberately DELETED (#3277) — the diagnosis role cannot execute it, "
        "and a notify path that has never delivered makes a failure LOOK surfaced"
    )


def test_workflow_red_files_a_tracked_issue_not_just_a_swallowed_publish():
    """#3277: the run had been red every week with the exact mobile a11y finding and
    surfaced nowhere. The fix is the #1447 filer, not an IAM grant: wired as the
    LAST step, `if: always()` (so a green run auto-closes the tracker), under its
    own dedup slug, with the issues:write the composite action documents as its
    precondition."""
    text = _workflow_text()
    assert "uses: ./.github/actions/advisory-failure-issue" in text, "webkit-mobile-qa.yml does not use the #1447 filer"
    step = text[text.index("uses: ./.github/actions/advisory-failure-issue") - 400 :]
    assert "if: always()" in step.split("uses: ./.github/actions/advisory-failure-issue")[0], "filer step must run always() (recover path)"
    assert "workflow-slug: webkit-mobile-qa" in text, "filer needs its own stable dedup slug"
    assert re.search(r"^permissions:(?:\n  .+)*\n  issues: write", text, re.M), "permissions block must grant issues: write for the filer"
    executable = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    assert "sns" not in executable.lower(), "no SNS notify path and no IAM grant belong here — the tracked issue is the surface"
    # the filer must be the last step, so nothing after it can be skipped on failure
    assert text.rstrip().endswith("investigate and fix forward."), "the advisory-failure-issue step must be the workflow's last step"


def test_workflow_artifact_upload_cannot_flip_the_verdict():
    text = _workflow_text()
    uploads = [chunk for chunk in re.split(r"\n(?=      - )", text) if "actions/upload-artifact@" in chunk]
    assert uploads, "no artifact upload — screenshots/report are the debugging evidence for a WebKit-only failure"
    for chunk in uploads:
        assert "continue-on-error: true" in chunk, "artifact upload can red the run on quota noise (#1331 class)"


def test_workflow_playwright_pin_matches_ci_gate():
    """CQ-01 class: the WebKit run must drive the SAME pinned Playwright as the
    enforced ci-cd.yml gate, or a red here can mean 'different engine version',
    not 'iOS Safari breakage'.

    #2609 made that structural rather than comparative: neither file carries a version
    any more — both resolve playwright from requirements-dev.txt via scripts/ci_pins.py.
    Equality between two literals is replaced by identity of one source, which is
    strictly stronger, so the assertions below are about the resolver call plus the
    absence of a second copy.
    """

    def resolves_playwright(path):
        with open(path, encoding="utf-8") as f:
            return [args for args in re.findall(r"ci_pins\.py([^)\n]*)", f.read()) if "playwright" in args.split()]

    def literals(path):
        with open(path, encoding="utf-8") as f:
            return sorted(set(re.findall(r"\bplaywright==([0-9][0-9A-Za-z.\-]*)", f.read())))

    assert resolves_playwright(_WORKFLOW), "webkit-mobile-qa.yml no longer resolves playwright from requirements-dev.txt (#2609)"
    assert resolves_playwright(_CI_CD), "ci-cd.yml no longer resolves playwright from requirements-dev.txt (#2609)"
    for path, name in ((_WORKFLOW, "webkit-mobile-qa.yml"), (_CI_CD, "ci-cd.yml")):
        assert not literals(
            path
        ), f"{name} hardcodes a playwright version again ({literals(path)}) — resolve it instead, or the two can drift (#2609)"


# ── 3. the WebKit 32767px screenshot-cap fix (#3353) ──────────────────────────
#
# Every historical webkit-mobile-qa run failed with "Page.screenshot: Cannot
# take screenshot larger than 32767 pixels on any dimension" on the taller
# pages — the mobile-Safari profile is 390x844 at device_scale_factor 3, so a
# page whose CSS scrollHeight exceeds ~10,900px hits the device-pixel cap (the
# tallest live page measured 2026-08-30: /protocols/challenges/ at 25,243px
# CSS height / 390x844 dpr3 mobile viewport — 3x that in device pixels, ~2.3x
# over the 32767 cap; see the PR body for the full measurement). The fix is
# `visual_qa._capture_full_page`: try the normal full-page screenshot, and on
# ANY failure fall back to scrolling in viewport-height tiles and stitching
# with Pillow — never raising, so a capture failure becomes a WARNING, not an
# aborted page audit.
#
# Section (a) exercises `_capture_full_page` directly (success / WebKit-cap
# fallback / total-failure) with a hand-built fake page — no browser needed.
# Section (b) is the acceptance-criteria proof: drive the REAL `capture_page`
# audit function with a fake `page` whose `.screenshot(full_page=True)`
# succeeds on one instance and raises the exact production WebKit error on
# the other, across three sample pages, and assert the two runs produce
# IDENTICAL a11y/gate verdicts (issues + status) — the screenshot mechanism
# must be provably decoupled from the rest of the audit. A positive control
# (a planted, non-baselined serious a11y violation) proves the parity check
# is non-vacuous: both runs must still show the SAME real defect as an issue,
# not just an empty issues list on each side.


class _FakeScreenshotPage:
    """Minimal `.screenshot()`-only fake for `_capture_full_page` unit tests."""

    def __init__(self, mode="ok", scroll_height=800, viewport=None):
        self.mode = mode  # "ok" | "webkit_cap" | "always_fail"
        self.scroll_height = scroll_height
        self.viewport_size = viewport or {"width": 390, "height": 844}
        self.full_page_calls = 0
        self.tile_calls = 0

    def screenshot(self, path=None, full_page=False):
        if full_page:
            self.full_page_calls += 1
            if self.mode in ("webkit_cap", "always_fail"):
                raise Exception("Page.screenshot: Cannot take screenshot larger than 32767 pixels on any dimension")
            from PIL import Image

            Image.new("RGB", (self.viewport_size["width"], min(self.scroll_height, 4000)), "white").save(path)
            return
        # tile capture (full_page falsy)
        self.tile_calls += 1
        if self.mode == "always_fail":
            raise Exception("simulated engine screenshot failure on tile capture too")
        from PIL import Image

        Image.new("RGB", (self.viewport_size["width"], self.viewport_size["height"]), "white").save(path)

    def evaluate(self, script, *a, **k):
        if "scrollHeight" in script:
            return self.scroll_height
        return None

    def wait_for_timeout(self, ms):
        pass


def test_capture_full_page_direct_success_never_tiles(tmp_path):
    pytest.importorskip("PIL")
    page = _FakeScreenshotPage(mode="ok", scroll_height=1200)
    warnings = []
    out = str(tmp_path / "page.png")
    assert visual_qa._capture_full_page(page, out, warnings) is True
    assert os.path.exists(out)
    assert page.full_page_calls == 1
    assert page.tile_calls == 0
    assert warnings == []


def test_capture_full_page_webkit_cap_falls_back_to_tiled_stitch(tmp_path):
    """The exact production error string — falls back to tiling, stitches a
    correctly-sized image, records ONE warning, never raises."""
    pytest.importorskip("PIL")
    from PIL import Image

    page = _FakeScreenshotPage(mode="webkit_cap", scroll_height=2500, viewport={"width": 390, "height": 844})
    warnings = []
    out = str(tmp_path / "tall.png")
    assert visual_qa._capture_full_page(page, out, warnings) is True
    assert page.full_page_calls == 1
    assert page.tile_calls == 3  # ceil(2500 / 844)
    assert os.path.exists(out)
    stitched = Image.open(out)
    assert stitched.size == (390, 2500)
    assert len(warnings) == 1
    assert "falling back to tiled capture" in warnings[0]
    # no leftover tile artifacts
    assert not any(f.endswith(".png") and f != "tall.png" for f in os.listdir(tmp_path))


def test_capture_full_page_total_failure_returns_false_never_raises(tmp_path):
    """Even the tiled fallback failing must not raise — it becomes a warning,
    and the caller (capture_page) must be able to keep going."""
    pytest.importorskip("PIL")
    page = _FakeScreenshotPage(mode="always_fail", scroll_height=2500)
    warnings = []
    out = str(tmp_path / "broken.png")
    assert visual_qa._capture_full_page(page, out, warnings) is False
    assert not os.path.exists(out)
    assert len(warnings) == 2  # the direct-attempt warning + the tiled-capture-failed warning


# ── (b) capture_page parity: screenshot mechanism must not move the verdict ──


class _FakeAuditPage:
    """A capture_page-compatible fake. Every DOM-dependent visual_qa helper
    (`_scroll_and_reveal`, `_check_sections_for_blank`, etc.) is monkeypatched
    to a fixed value by the `_isolate_dom_helpers` fixture below — the ONLY
    thing this class need vary between test instances is `.screenshot()`
    itself, which is the whole point: capture_page's non-screenshot verdict
    must be identical regardless of how the screenshot capture behaves.
    """

    def __init__(self, screenshot_mode="ok", scroll_height=1200):
        self.screenshot_mode = screenshot_mode  # "ok" | "webkit_cap"
        self.scroll_height = scroll_height
        self.viewport_size = {"width": 390, "height": 844}

    def add_init_script(self, *a, **k):
        pass

    def on(self, *a, **k):
        pass

    def goto(self, url, wait_until=None, timeout=None):
        return None

    def wait_for_timeout(self, ms):
        pass

    def set_viewport_size(self, size):
        self.viewport_size = size

    def close(self):
        pass

    def query_selector_all(self, sel):
        return []

    def query_selector(self, sel):
        return None

    def evaluate(self, script, *a, **k):
        if "__perf" in script:
            return {}
        if "scrollHeight" in script:
            return self.scroll_height
        return None

    def screenshot(self, path=None, full_page=False):
        from PIL import Image  # caller (the test) already importorskip'd this

        if full_page and self.screenshot_mode == "webkit_cap":
            raise Exception("Page.screenshot: Cannot take screenshot larger than 32767 pixels on any dimension")
        Image.new("RGB", (self.viewport_size["width"], 50), "white").save(path)


@pytest.fixture
def _isolate_dom_helpers(monkeypatch):
    """Neutralize every capture_page helper that would otherwise need a real
    rendered DOM, so the fake page above only has to answer the handful of
    calls capture_page itself makes directly. This isolates the ONE variable
    under test: whether `.screenshot(full_page=True)` succeeds or raises."""
    for name, value in (
        ("_scroll_and_reveal", lambda page: None),
        ("_check_sections_for_blank", lambda page: []),
        ("_check_stale_text", lambda page: []),
        ("_mobile_overflow", lambda page: 0),
        ("_stuck_reveals", lambda page, sel: []),
        ("_app_bar_overflow", lambda page: 0),
        ("_viewport_meta_ok", lambda page: True),
        ("_tap_target_audit", lambda page, sel: []),
        ("_svg_text_floor_findings", lambda page, w: []),
        ("_html_text_floor_findings", lambda page, w: []),
    ):
        monkeypatch.setattr(visual_qa, name, value)


def _run_capture_page_pair(monkeypatch, path, tmp_path, plant_defect):
    """Drive the real capture_page() twice — once with a screenshot that
    succeeds directly (the chromium-shaped path), once with one that raises
    the exact production WebKit 32767px error (the webkit-shaped path) — and
    return their result dicts. `plant_defect` controls a1ly_audit.run_axe's
    stub: when True, every call returns one NEW serious violation (not in the
    empty baseline) so BOTH desktop and mobile a11y passes must gate — the
    positive control that proves this test can fail."""
    from visual_qa import a11y_audit as vqa11y

    call_count = {"n": 0}

    def fake_run_axe(page):
        call_count["n"] += 1
        if not plant_defect:
            return []
        return [
            {
                "id": "scrollable-region-focusable",
                "impact": "serious",
                "help": "Scrollable region must have keyboard access",
                "nodes": 1,
                "targets": ["table"],
            }
        ]

    monkeypatch.setattr(vqa11y, "run_axe", fake_run_axe)

    empty_baseline = {"_meta": {}, "pages": {}, "pages_light": {}, "pages_mobile": {}, "pages_light_mobile": {}}
    page_def = {"path": path, "name": f"Sample {path}", "tier": 2}

    results = {}
    for mode in ("ok", "webkit_cap"):
        fake_page = _FakeAuditPage(screenshot_mode=mode, scroll_height=25243)
        context = SimpleNamespace(new_page=lambda fp=fake_page: fp)
        screenshot_dir = str(tmp_path / mode / path.strip("/").replace("/", "-"))
        os.makedirs(screenshot_dir, exist_ok=True)
        results[mode] = visual_qa.capture_page(
            context,
            page_def,
            screenshot_dir,
            save_screenshots=True,
            a11y_baseline=empty_baseline,
            context_mobile=False,
        )
    # both desktop + mobile axe passes ran on both sides (2 calls x 2 modes)
    assert call_count["n"] == 4, f"expected 4 run_axe calls (desktop+mobile x 2 screenshot modes), got {call_count['n']}"
    return results


_SAMPLE_PAGES = ["/protocols/challenges/", "/data/labs/", "/method/predictions/"]


@pytest.mark.parametrize("path", _SAMPLE_PAGES)
def test_screenshot_path_does_not_change_clean_verdict(monkeypatch, tmp_path, _isolate_dom_helpers, path):
    """Negative case: no planted defect — both screenshot paths must agree
    the page is clean (status PASS, no issues)."""
    pytest.importorskip("PIL")
    results = _run_capture_page_pair(monkeypatch, path, tmp_path, plant_defect=False)
    assert results["ok"]["status"] == "PASS"
    assert results["webkit_cap"]["status"] == "PASS"
    assert results["ok"]["issues"] == results["webkit_cap"]["issues"] == []


@pytest.mark.parametrize("path", _SAMPLE_PAGES)
def test_screenshot_path_produces_identical_a11y_verdict_positive_control(monkeypatch, tmp_path, _isolate_dom_helpers, path):
    """Positive control (the acceptance-criteria proof): a REAL a11y defect
    (planted via a11y_audit.run_axe) must gate identically whether the
    screenshot capture takes the direct path or the WebKit-cap tiled fallback
    — proving the two screenshot mechanisms are not coupled to the gate.

    Before #3353's fix, the WebKit-cap screenshot exception happened BEFORE
    the mobile viewport pass (capture_page resizes to 390px and runs the
    mobile a11y gate only AFTER the desktop screenshot call) and was caught by
    the function's outer `except Exception`, which replaced the rest of that
    page's issues with a single generic "Page load failed" — silently
    dropping the mobile a11y finding. This test fails exactly that way if the
    fix is reverted (see the mutation in the PR body: reinstate a bare
    `page.screenshot(path=full, full_page=True)` in place of the
    `_capture_full_page` call at the desktop site)."""
    pytest.importorskip("PIL")
    results = _run_capture_page_pair(monkeypatch, path, tmp_path, plant_defect=True)
    ok_result = results["ok"]
    cap_result = results["webkit_cap"]

    assert ok_result["status"] == "FAIL"
    assert cap_result["status"] == "FAIL"
    assert ok_result["issues"] == cap_result["issues"]
    # Real defect present on BOTH sides — the desktop AND mobile a11y passes.
    new_violation_issues = [i for i in ok_result["issues"] if "NEW serious a11y violation" in i]
    assert len(new_violation_issues) == 2, f"expected desktop+mobile a11y issues, got: {ok_result['issues']}"
    # The screenshot itself must still have been attempted on both sides —
    # this is not a case where the webkit_cap path silently skipped it.
    assert any("falling back to tiled capture" in w for w in cap_result["warnings"])
    assert not any("falling back to tiled capture" in w for w in ok_result["warnings"])
