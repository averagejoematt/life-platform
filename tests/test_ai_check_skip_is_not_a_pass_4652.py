"""tests/test_ai_check_skip_is_not_a_pass_4652.py — a skipped AI check says so, and is never a pass (#4652, ADR-116).

#4589 put a cost gate in front of the two AI judges CI runs (`scripts/reader_surface.py`):
no reader surface in the diff, no Bedrock call. What it left behind was the shape ADR-116
exists to refuse — on a SKIP the workflow dropped `--ai-qa`, printed a `::notice`, and the
job named "Visual + AI-vision QA" went green with `ai_vision_status: null` in report.json,
indistinguishable from a run that was never asked to judge anything.

What is pinned here:

  1. THE RECORD — a skip handed to the sweep is reported as SKIPPED-BY-READER-SURFACE, "not
     run, not a pass", on all four surfaces the sweep owns: stdout, the job summary, a
     `::warning` annotation and report.json. Driven through `run_sweep` itself with the
     browser stubbed, so it is the real reporting path and not a helper in isolation.
  2. THE WIRING — every place a workflow drops a judge on the gate's SKIP hands the reason
     to the sweep; no bare deterministic-only invocation is left behind a SKIP.
  3. THE REGISTRY CANNOT DRIFT — every workflow that runs a judge either consults the gate
     or is ruled ungated with a reason; site-deploy.yml's path filter still names the site
     tree and its judge is unconditional; and every Function-URL Lambda in the two edge
     stacks is a request-time entry or ruled as rendering no swept page.

No AWS, no Bedrock, no real browser.
"""

import json
import os
import re
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(ROOT, "tests"), os.path.join(ROOT, "scripts"), os.path.join(ROOT, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import reader_surface as rs  # noqa: E402
import visual_qa  # noqa: E402
import visual_qa_cli  # noqa: E402

WF_DIR = os.path.join(ROOT, ".github", "workflows")
REASON = "reader-surface gate (#4589): SKIP — 3 file(s) changed in abc123def456..HEAD and none is on the reader surface"


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


# ── 1. the record ──────────────────────────────────────────────────────────────


class _FakeBrowser:
    def new_context(self, **_kw):
        return object()

    def close(self):
        pass


class _FakePlaywright:
    chromium = types.SimpleNamespace(launch=lambda headless=True: _FakeBrowser())

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


@pytest.fixture()
def swept(monkeypatch, tmp_path, capsys):
    """Run the REAL run_sweep over zero pages with the browser stubbed; return what it reported."""
    fake = types.ModuleType("playwright.sync_api")
    fake.sync_playwright = lambda: _FakePlaywright()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake)
    monkeypatch.setattr(visual_qa, "sweep_pages", lambda pages, max_tier: [])
    monkeypatch.setattr(visual_qa, "await_convergence_or_die", lambda: None)
    # The sweep persists its a11y shrink sidecar on every run — point it out of the checkout.
    monkeypatch.setattr(visual_qa.a11y_audit, "SHRINK_LEDGER_PATH", str(tmp_path / "a11y_shrink_ledger.json"))
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")

    def _run(**kw):
        ok = visual_qa.run_sweep(screenshot_dir=str(tmp_path), a11y=False, leak_scan=False, **kw)
        report = json.loads((tmp_path / "report.json").read_text())
        return ok, report, capsys.readouterr().out, summary.read_text()

    return _run


def test_a_skipped_vision_judge_is_reported_on_every_surface_and_never_as_a_pass(swept):
    ok, report, out, summary = swept(ai_qa_skipped=REASON)

    # report.json — the machine record. Not None ("never asked"), not "ok" ("ran clean").
    st = report["ai_vision_status"]
    assert st == {"status": "skipped_by_reader_surface", "reason": REASON}
    assert st["status"] != "ok"

    # stdout — the line the task names.
    line = f"AI-vision QA: SKIPPED-BY-READER-SURFACE — not run, not a pass ({REASON})"
    assert line in out.splitlines()

    # the annotation — the one surface visible beside the green check without opening the log.
    ann = [ln for ln in out.splitlines() if ln.startswith("::warning title=AI-vision QA SKIPPED-BY-READER-SURFACE::")]
    assert len(ann) == 1, out
    assert "did NOT run" in ann[0] and "not evidence about this deploy" in ann[0] and REASON in ann[0]

    # the job summary.
    assert "**AI-vision QA: SKIPPED-BY-READER-SURFACE** — not run, not a pass." in summary and REASON in summary

    # The deterministic sweep's own verdict is untouched: zero pages, zero failures.
    assert ok is True


def test_a_skipped_prose_judge_is_reported_the_same_way(swept):
    _ok, report, out, summary = swept(reader_truth_skipped=REASON)
    assert report["reader_truth_status"] == {"status": "skipped_by_reader_surface", "reason": REASON}
    assert report["ai_vision_status"] is None, "a judge nobody asked for and nobody skipped stays None"
    assert f"Reader-truth QA: SKIPPED-BY-READER-SURFACE — not run, not a pass ({REASON})" in out.splitlines()
    assert any(ln.startswith("::warning title=Reader-truth QA SKIPPED-BY-READER-SURFACE::") for ln in out.splitlines())
    assert "**Reader-truth QA: SKIPPED-BY-READER-SURFACE** — not run, not a pass." in summary


def test_the_negative_control_a_run_with_no_skip_says_nothing_about_one(swept):
    """The mutation the positive tests are measured against: no skip passed → no skip claimed."""
    _ok, report, out, summary = swept()
    assert report["ai_vision_status"] is None and report["reader_truth_status"] is None
    assert "SKIPPED-BY-READER-SURFACE" not in out and "SKIPPED-BY-READER-SURFACE" not in summary


def test_the_old_silent_shape_is_distinguishable_from_the_recorded_skip():
    """Before #4652 a SKIP left `ai_vision_status: null` — the same value as 'never requested'."""
    assert visual_qa.reader_surface_skip_status(None) is None
    recorded = visual_qa.reader_surface_skip_status(REASON)
    assert recorded is not None and recorded["status"] == visual_qa.SKIPPED_BY_READER_SURFACE
    # An empty reason still records the skip — it can never collapse back into None.
    assert visual_qa.reader_surface_skip_status("")["status"] == visual_qa.SKIPPED_BY_READER_SURFACE
    # Outside CI the annotation is quiet (no noise on a laptop); the stdout line is not.
    assert visual_qa.gha_paused_gate_annotation("AI-vision QA", recorded, env={}) == ""
    assert visual_qa.reader_surface_skip_line("AI-vision QA", recorded)
    assert visual_qa.reader_surface_skip_line("AI-vision QA", {"status": "ok"}) == ""


def test_the_cli_carries_the_skip_to_the_sweep_and_refuses_run_plus_skipped():
    seen = {}

    class _Vqa:
        PAGES = []
        SITE_URL = "https://example.invalid"

        @staticmethod
        def run_sweep(**kw):
            seen.update(kw)
            return True

    assert visual_qa_cli.main(vqa=_Vqa, argv=["--screenshot", "--ai-qa-skipped", REASON]) == 0
    assert seen["ai_qa"] is False and seen["ai_qa_skipped"] == REASON and seen["reader_truth_skipped"] is None

    # A judge cannot be both run and recorded as skipped — that would be a pass with a skip's label.
    for argv in (["--ai-qa", "--ai-qa-skipped", REASON], ["--reader-truth", "--reader-truth-skipped", REASON]):
        with pytest.raises(SystemExit) as exc:
            visual_qa_cli.main(vqa=_Vqa, argv=argv)
        assert exc.value.code == 2


def test_a_requested_judge_is_never_overwritten_by_a_skip_record(swept, monkeypatch):
    """If the judge RAN, its own status stands — the skip argument cannot paint over a verdict."""
    fake_ai = types.ModuleType("visual_ai_qa")
    fake_ai.assess_results = lambda targets: {"status": "ok"}
    monkeypatch.setitem(sys.modules, "visual_ai_qa", fake_ai)
    _ok, report, out, _summary = swept(ai_qa=True, ai_qa_skipped=REASON)
    assert report["ai_vision_status"] == {"status": "ok"}
    assert "SKIPPED-BY-READER-SURFACE" not in out


# ── 2. the wiring ──────────────────────────────────────────────────────────────


def test_every_gate_skip_in_a_workflow_hands_its_reason_to_the_sweep():
    ci = _read(".github/workflows/ci-cd.yml")
    assert 'python3 tests/visual_qa.py --screenshot --ai-qa-skipped "${SKIP_REASON}"' in ci
    assert "SKIP_REASON: ${{ steps.reader_surface.outputs.reason }}" in ci
    # No deterministic-only invocation is left that says nothing about the judge it dropped.
    assert not re.search(r"^\s*python3 tests/visual_qa\.py --screenshot\s*$", ci, re.M), "a bare SKIP invocation is back in ci-cd.yml"

    vq = _read(".github/workflows/visual-qa.yml")
    # Each SKIP arm clears the flag AND records why, in the same arm.
    assert 'case "$V" in *"(#4589): SKIP"*) RT=""; RT_SKIP="$V" ;; esac' in vq
    assert 'case "$V" in *"(#4589): SKIP"*) AI=""; AI_SKIP="$V" ;; esac' in vq
    assert vq.count('*"(#4589): SKIP"*)') == 2, "a third SKIP arm appeared without a skip record"
    assert 'SKIPPED+=(--ai-qa-skipped "${AI_QA_SKIP}")' in vq and 'SKIPPED+=(--reader-truth-skipped "${READER_TRUTH_SKIP}")' in vq
    assert '"${SKIPPED[@]}"' in vq, "the skip records are built but never passed to the sweep"
    # The verdict line is free text: it travels as env, never interpolated into the script body.
    assert "AI_QA_SKIP: ${{ steps.cadence.outputs.ai_qa_skip }}" in vq
    assert "READER_TRUTH_SKIP: ${{ steps.cadence.outputs.reader_truth_skip }}" in vq


def test_the_gates_skip_verdict_is_the_string_the_workflows_match_on(monkeypatch):
    """The `case` arms key on '(#4589): SKIP' — hold the producer to it, and a RUN can never match."""
    monkeypatch.setattr(rs, "decide", lambda base, head="HEAD": (False, "SKIP — nothing on the reader surface"))
    out = []
    monkeypatch.setattr("builtins.print", lambda *a, **k: out.append(" ".join(str(x) for x in a)))
    assert rs.main(["--base", "abc123"]) == 0
    assert "(#4589): SKIP" in out[-1]
    monkeypatch.setattr(rs, "decide", lambda base, head="HEAD": (True, "RUN — 1 reader-surface file(s) changed"))
    assert rs.main(["--base", "abc123"]) == 0
    assert "(#4589): SKIP" not in out[-1]


def test_a_skip_cannot_trigger_a_rollback_and_a_site_change_cannot_be_skipped():
    """The two halves of 'a skip must neither revert nor count as green evidence for a site change'."""
    ci = _read(".github/workflows/ci-cd.yml")
    # ci-cd.yml: no job lists visual-qa in its `needs`, so its result — green on a skip or
    # red on a finding — is in no rollback's inputs.
    assert not re.search(r"^\s*needs:.*\bvisual-qa\b", ci, re.M), "a ci-cd.yml job now depends on visual-qa — re-rule the skip"
    # site-deploy.yml: the workflow whose visual-qa result DOES feed a rollback and the
    # deploy-record job never consults the gate, so a skip cannot occur there at all.
    sd = _read(".github/workflows/site-deploy.yml")
    assert "needs.visual-qa.result" in sd
    assert "reader_surface" not in sd and "--ai-qa-skipped" not in sd
    assert re.search(r"^\s*python3 tests/visual_qa\.py --screenshot --ai-qa --ai-qa-max-tier 1\s*$", sd, re.M)


# ── 3. the registry cannot drift ───────────────────────────────────────────────

_JUDGE_FLAG = re.compile(r"--ai-qa\b(?!-skipped)|--reader-truth\b(?!-skipped)")


def _code_lines(text):
    return [ln for ln in text.splitlines() if not ln.lstrip().startswith("#")]


def test_every_workflow_that_runs_a_judge_consults_the_gate_or_is_ruled_ungated():
    offenders = []
    running = set()
    for name in sorted(os.listdir(WF_DIR)):
        rel = f".github/workflows/{name}"
        if any(_JUDGE_FLAG.search(ln) for ln in _code_lines(_read(rel))):
            running.add(rel)
            gated = rel in rs.WIRING_PATHS and "scripts/reader_surface.py" in _read(rel)
            if not gated and rel not in rs.UNGATED_JUDGE_WORKFLOWS:
                offenders.append(rel)
    assert not offenders, (
        f"{offenders}: passes --ai-qa / --reader-truth without consulting scripts/reader_surface.py — add it to "
        "reader_surface.WIRING_PATHS and gate it, or rule it in UNGATED_JUDGE_WORKFLOWS with the reason"
    )
    assert len(running) >= 3, f"the scan found only {sorted(running)} — the judge-flag pattern stopped matching"
    stale = [w for w in rs.UNGATED_JUDGE_WORKFLOWS if w not in running]
    assert not stale, f"{stale}: ruled ungated but no longer runs a judge — remove the ruling"
    both = set(rs.UNGATED_JUDGE_WORKFLOWS) & set(rs.WIRING_PATHS)
    assert not both, f"{sorted(both)}: a workflow is either gated or ruled ungated, not both"


def test_the_site_deploy_path_filter_and_the_gates_site_set_are_the_same_tree():
    """The gate's first set is documented as 'site-deploy.yml's own path filter' — hold it to that."""
    sd = _read(".github/workflows/site-deploy.yml")
    block = sd[sd.index("    paths:") : sd.index("  workflow_dispatch:")]
    paths = re.findall(r"^\s*-\s*'([^']+)'", block, re.M)
    assert paths, "site-deploy.yml's push path filter could not be read"
    assert f"{rs.SITE_PREFIX}**" in paths, f"site-deploy.yml no longer triggers on {rs.SITE_PREFIX}** — the gate's site set drifted"
    assert rs.classify([f"{rs.SITE_PREFIX}index.html"]) == [(f"{rs.SITE_PREFIX}index.html", "site")]


_FN_DEF = re.compile(r"^\s*(\w+_fn) = (?:create_platform_lambda|_lambda\.Function)\(", re.M)


def _function_url_lambdas():
    """{construct variable: source_file or None} for every Lambda given a Function URL in the edge stacks."""
    found = {}
    for rel in rs.EDGE_PATHS:
        text = _read(rel)
        defs = [(m.start(), m.group(1)) for m in _FN_DEF.finditer(text)]
        for i, (pos, var) in enumerate(defs):
            if f"{var}.add_function_url(" not in text:
                continue
            body = text[pos : defs[i + 1][0] if i + 1 < len(defs) else len(text)]
            src = re.search(r'source_file="([^"]+)"', body.split(f"{var}.add_function_url(")[0])
            found[var] = src.group(1) if src else None
        assert text.count(".add_function_url(") == sum(
            1 for _, v in defs if f"{v}.add_function_url(" in text
        ), f"{rel}: a Function URL is attached to a construct this guard cannot name — extend _FN_DEF"
    return found


def test_every_function_url_in_the_edge_stacks_is_a_request_time_entry_or_ruled():
    found = _function_url_lambdas()
    assert len(found) >= 5, f"only {sorted(found)} found — the stack scan stopped matching"
    unruled = sorted(var for var, src in found.items() if src not in rs.REQUEST_TIME_ENTRIES and var not in rs.FUNCTION_URLS_NO_SWEPT_PAGE)
    assert not unruled, (
        f"{unruled}: a Lambda with a public Function URL is neither in reader_surface.REQUEST_TIME_ENTRIES nor ruled in "
        "FUNCTION_URLS_NO_SWEPT_PAGE — a diff to it would SKIP the AI judges by default"
    )
    stale = sorted(v for v in rs.FUNCTION_URLS_NO_SWEPT_PAGE if v not in found)
    assert not stale, f"{stale}: ruled as rendering no swept page but no such Function URL exists any more"
    double = sorted(v for v, src in found.items() if src in rs.REQUEST_TIME_ENTRIES and v in rs.FUNCTION_URLS_NO_SWEPT_PAGE)
    assert not double, f"{double}: both a request-time entry and ruled out"
    missing = sorted(e for e in rs.REQUEST_TIME_ENTRIES if e not in found.values())
    assert not missing, f"{missing}: a request-time entry with no Function URL in the edge stacks — stale entry point"


def test_the_subscriber_lambda_the_guard_found_now_runs_the_judges():
    """The member the Function-URL guard caught on its first run: /subscribe/confirm/ renders its answer."""
    hits = rs.classify(["lambdas/web/email_subscriber_lambda.py"])
    assert hits == [("lambdas/web/email_subscriber_lambda.py", "request-time API")]
