"""
tests/test_reader_truth_qa.py — the phase-aware reader-truth rubric (#1095/#1096).

Covers the ONE shared module (lambdas/reader_truth_qa.py) and both of its hooks:
  - prompt builder: phase context (Day N / pre-start) appears, all four rubric
    categories present, batching at 4-6 surfaces per call;
  - verdict parsing: tolerant of fences/garbage, coerces junk severities so an
    unrecognized severity can never gate;
  - the CI harness merge (tests/visual_ai_qa.assess_reader_truth): the #1095
    regression guard — a synthetic contradiction ("30-day trend" at day 0/2)
    with a high verdict must flip the page to FAIL;
  - the nightly qa_smoke check (#1096) with mocked Bedrock: flag → FAIL check,
    clean → ok, Bedrock error → soft warn (never reds the nightly), budget
    tier 3 → explicit ⏸ pause (ADR-125's operator-truth band since #1927 —
    tiers 1 and 2 must RUN the gate, which is what #1927 fixed).

No wall-clock time bombs: every fixture date is DERIVED from
constants.EXPERIMENT_START_DATE, which moves on each experiment reset.
"""

import json
import os
import sys
import types
from datetime import date, timedelta

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)  # for `import visual_ai_qa`

import boto3  # noqa: E402
import visual_ai_qa  # noqa: E402
from ai import budget_guard  # noqa: E402  (lambdas/ on sys.path via conftest)
from common.constants import EXPERIMENT_START_DATE  # noqa: E402
from operational import reader_truth_qa as rtq  # noqa: E402

_START = date.fromisoformat(EXPERIMENT_START_DATE)
_DAY_1 = _START.isoformat()
_DAY_2 = (_START + timedelta(days=1)).isoformat()
_PRE_3 = (_START - timedelta(days=3)).isoformat()

_PAGES = [
    {"name": "Cockpit", "path": "/now/", "prose": "Day marker here. Your 30-day trend shows steady improvement across every pillar."},
    {"name": "Home", "path": "/", "prose": "One man, every metric, in public."},
    {"name": "Coaching", "path": "/coaching/", "prose": "The board weighs in daily."},
]

_HIGH_VERDICT = {
    "findings": [
        {
            "page": "/now/",
            "category": "temporal_contradiction",
            "severity": "high",
            "note": "narrates a 30-day trend at the very start of the experiment",
        }
    ],
    "severity": "high",
    "summary": "temporal contradiction on the cockpit",
}
_CLEAN_VERDICT = {"findings": [], "severity": "ok", "summary": "all surfaces consistent with the phase"}


def _fake_invoke(payload, calls=None):
    """A bedrock_client.invoke stand-in returning `payload` as the model's JSON reply."""

    def invoke(body, model_name=None):
        if calls is not None:
            calls.append({"body": body, "model_name": model_name})
        return {"content": [{"type": "text", "text": json.dumps(payload)}]}

    return invoke


# ── #1440: QAPausedByBudget metric emission (ADR-104 applied to QA itself) ─────


class _CW:
    """Fake CloudWatch client — records put_metric_data calls (auth_breaker's pattern)."""

    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kw):
        self.calls.append(kw)


def _patch_cw(monkeypatch):
    cw = _CW()
    monkeypatch.setattr(boto3, "client", lambda *a, **k: cw)
    return cw


def test_emit_budget_pause_metric_puts_qa_paused_by_budget(monkeypatch):
    cw = _patch_cw(monkeypatch)
    rtq.emit_budget_pause_metric("qa_smoke", 1)
    assert cw.calls, "emit_budget_pause_metric must call put_metric_data"
    call = cw.calls[-1]
    assert call["Namespace"] == "LifePlatform/QA"
    assert call["MetricData"][0]["MetricName"] == "QAPausedByBudget"
    assert call["MetricData"][0]["Value"] == 1.0


def test_emit_budget_pause_metric_is_fail_soft(monkeypatch):
    """A CloudWatch outage must never raise — the QA pass is already degrading."""

    class _Boom:
        def put_metric_data(self, **kw):
            raise RuntimeError("cloudwatch down")

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _Boom())
    rtq.emit_budget_pause_metric("qa_smoke", 1)  # must not raise


# ── phase context (derived from EXPERIMENT_START_DATE — no wall-clock literals) ──


def test_phase_context_day_one():
    p = rtq.phase_context(_DAY_1)
    assert p["day_n"] == 1 and p["pre_start"] is False and p["days_until_start"] == 0
    assert p["start_date"] == EXPERIMENT_START_DATE


def test_phase_context_day_two():
    p = rtq.phase_context(_DAY_2)
    assert p["day_n"] == 2 and p["pre_start"] is False


def test_phase_context_pre_start():
    p = rtq.phase_context(_PRE_3)
    assert p["day_n"] == 0 and p["pre_start"] is True and p["days_until_start"] == 3


# ── prompt builder ────────────────────────────────────────────────────────────


def test_prompt_carries_day_number_and_start_date():
    prompt = rtq.build_prompt(_PAGES, rtq.phase_context(_DAY_2))
    assert "Day 2" in prompt
    assert EXPERIMENT_START_DATE in prompt
    for p in _PAGES:  # every surface's name, path, and prose are in the batch
        assert p["path"] in prompt and p["name"] in prompt and p["prose"][:40] in prompt


def test_prompt_pre_start_variant():
    prompt = rtq.build_prompt(_PAGES, rtq.phase_context(_PRE_3))
    assert "NOT started" in prompt
    assert "3 day(s) away" in prompt


def test_prompt_rubric_categories_and_contract_present():
    prompt = rtq.build_prompt(_PAGES, rtq.phase_context(_DAY_2))
    for cat in rtq.CATEGORIES:
        assert cat in prompt, f"rubric category {cat} missing from prompt"
    assert "DO NOT flag" in prompt  # the false-positive guard rails
    assert '"findings"' in prompt and '"severity"' in prompt  # the JSON contract


def test_prompt_states_the_lower_bound_not_only_the_upper():
    """#1917: the rubric must say a SHORTER window is correct, not only that a longer one is impossible.

    Stating only the upper bound let the model infer that any window number differing
    from day_n was a contradiction: it flagged `weight_delta_window_days: 5` on Day 6
    as an "impossible number" on three consecutive runs, blocking the deploy pipeline
    on a payload that was telling the truth. After a cycle restart EVERY trailing
    window is clamped to the cycle start (ADR-077 "clamped, not hidden"), so short
    windows are the honest path — the rubric has to say so out loud.
    """
    prompt = rtq.build_prompt(_PAGES, rtq.phase_context(_DAY_2))
    lowered = prompt.lower()
    assert "smaller than" in lowered, "the prompt must explicitly permit windows smaller than day_n"
    assert "expected and correct" in lowered
    assert "only a span longer" in lowered, "the impossible direction must be named as the ONLY one"
    # the DO-NOT-flag list must carry the concrete case too, not just the phase line
    assert "under-filled window" in lowered or "under-filled" in lowered


def test_prompt_truncates_oversized_prose():
    pages = [{"name": "Big", "path": "/big/", "prose": "x" * (rtq.MAX_PROSE_CHARS + 500)}]
    prompt = rtq.build_prompt(pages, rtq.phase_context(_DAY_2))
    assert "…[truncated]" in prompt
    # Overhead allowance = rubric + footer, not prose. 4000 → 5000 on 2026-08-09:
    # the DO-NOT-flag ledger grew the two pre-start clauses ("··" honest-absence
    # glyph + habitual-present design copy, the cycle-13 false-positive class).
    # 5000 → 6000 on 2026-08-13 (#2613): the wake-date ruling widened from the
    # scalar `night_of` to the dated SERIES, the clause class that had been
    # re-failing nightly at Day 3. ~660 chars ≈ 165 Haiku tokens per batch, twice
    # a night — the ledger IS the rule in this module, so it is allowed to grow;
    # this bound exists to keep it from growing UNNOTICED, not to freeze it.
    # 6000 → 6800 on 2026-08-23 (#2959): the trailing-window/day-counter clause —
    # the old bullet's last line INSTRUCTED flagging any window longer than the
    # elapsed days, which manufactured the 7-day-HRV-average highs that held the
    # publish path twice in one hour (runs 32616299944 + 32618360726).
    assert len(prompt) < rtq.MAX_PROSE_CHARS + 6800


def test_batching_four_to_six_surfaces_per_call():
    calls = []
    seven = [{"name": f"P{i}", "path": f"/p{i}/", "prose": f"prose {i}"} for i in range(7)]
    findings, errors = rtq.assess_prose(seven, _fake_invoke(_CLEAN_VERDICT, calls), today_iso=_DAY_2, batch_size=5)
    assert errors == [] and findings == []
    assert len(calls) == 2  # 5 + 2
    first_prompt = calls[0]["body"]["messages"][0]["content"][0]["text"]
    second_prompt = calls[1]["body"]["messages"][0]["content"][0]["text"]
    assert "/p4/" in first_prompt and "/p4/" not in second_prompt
    assert "/p5/" in second_prompt and "/p5/" not in first_prompt


def test_default_model_is_haiku_tier():
    calls = []
    rtq.assess_prose(_PAGES, _fake_invoke(_CLEAN_VERDICT, calls), today_iso=_DAY_2)
    assert all("haiku" in c["model_name"] for c in calls)  # ADR-049/063 structured tier


# ── verdict parsing ───────────────────────────────────────────────────────────


def test_parse_verdict_tolerates_fences():
    text = "Sure, here it is:\n```json\n" + json.dumps(_HIGH_VERDICT) + "\n```"
    v = rtq.parse_verdict(text)
    assert v["findings"][0]["category"] == "temporal_contradiction"


def test_parse_verdict_garbage_degrades_to_no_findings():
    v = rtq.parse_verdict("no json anywhere")
    assert v["findings"] == [] and v["severity"] == "ok"
    assert rtq.parse_verdict(None)["findings"] == []


def test_junk_severity_and_category_are_coerced_not_gating():
    verdict = {"findings": [{"page": "/now/", "category": "made_up", "severity": "critical", "note": "x"}]}
    findings, _ = rtq.assess_prose(_PAGES[:1], _fake_invoke(verdict), today_iso=_DAY_2)
    assert findings == [{"page": "/now/", "category": "other", "severity": "low", "note": "x"}]


def test_assess_prose_bedrock_error_is_soft():
    def boom(body, model_name=None):
        raise RuntimeError("ThrottlingException")

    findings, errors = rtq.assess_prose(_PAGES, boom, today_iso=_DAY_2)
    assert findings == []
    assert len(errors) == 1 and "ThrottlingException" in errors[0] and "/now/" in errors[0]


def test_html_to_text_strips_script_and_tags():
    html = (
        "<html><head><style>.x{color:red}</style></head><body><script>var a=1;</script><h1>Day 2</h1><p>of the experiment</p></body></html>"
    )
    text = rtq.html_to_text(html)
    assert "Day 2" in text and "of the experiment" in text
    assert "var a=1" not in text and "color:red" not in text


# ── CI harness merge (#1095 regression guard) ─────────────────────────────────


def _harness_results(tmp_path, prose):
    pf = tmp_path / "now.txt"
    pf.write_text(prose)
    return [
        {
            "page": "Cockpit",
            "path": "/now/",
            "status": "PASS",
            "issues": [],
            "warnings": [],
            "screenshots": [{"kind": "prose", "path": str(pf)}],
        }
    ]


def _patch_harness(monkeypatch, payload, tier=0, calls=None):
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: types.SimpleNamespace(invoke=_fake_invoke(payload, calls)))
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)


def test_synthetic_contradiction_fixture_fails_the_page(tmp_path, monkeypatch):
    """#1095 acceptance: a mocked page asserting a week-long trend at day 0/2,
    judged high, must FAIL the harness page exactly like an AI-vision high."""
    results = _harness_results(tmp_path, "Day 0. Your 30-day trend shows steady improvement.")
    _patch_harness(monkeypatch, _HIGH_VERDICT)
    visual_ai_qa.assess_reader_truth(results)
    assert results[0]["status"] == "FAIL"
    assert any("Reader-truth (high)" in i and "temporal_contradiction" in i for i in results[0]["issues"])
    assert results[0]["truth_findings"][0]["page"] == "/now/"


def test_harness_med_finding_warns_but_does_not_fail(tmp_path, monkeypatch):
    med = {"findings": [{"page": "/now/", "category": "audience_violation", "severity": "med", "note": "insider jargon"}]}
    results = _harness_results(tmp_path, "As discussed in our session, the plan holds.")
    _patch_harness(monkeypatch, med)
    visual_ai_qa.assess_reader_truth(results)
    assert results[0]["status"] == "PASS"
    assert any("Reader-truth (med)" in w for w in results[0]["warnings"])


def test_harness_budget_skip_is_explicit_and_makes_no_ai_call(tmp_path, monkeypatch):
    calls = []
    results = _harness_results(tmp_path, "anything")
    _patch_harness(monkeypatch, _HIGH_VERDICT, tier=3, calls=calls)  # operator-truth band pauses at tier 3 (ADR-125/#1927)
    visual_ai_qa.assess_reader_truth(results)
    assert calls == []  # no Bedrock spend while paused
    assert results[0]["status"] == "PASS"
    assert any("budget tier 3" in w for w in results[0]["warnings"])  # honest skip, never silent green


def test_harness_budget_skip_returns_explicit_status_and_emits_metric(tmp_path, monkeypatch):
    """#1440 acceptance: the CI/local harness's budget pause (1) emits the
    QAPausedByBudget CloudWatch metric and (2) returns a status the caller can
    render as SKIPPED-BY-BUDGET instead of silently blending into "passed"."""
    cw = _patch_cw(monkeypatch)
    results = _harness_results(tmp_path, "anything")
    _patch_harness(monkeypatch, _HIGH_VERDICT, tier=3)
    status = visual_ai_qa.assess_reader_truth(results)

    assert status == {"status": "skipped_by_budget", "tier": 3}

    assert cw.calls, "a budget-tier pause must emit a CloudWatch metric (#1440)"
    call = cw.calls[-1]
    assert call["Namespace"] == "LifePlatform/QA"
    assert call["MetricData"][0]["MetricName"] == "QAPausedByBudget"

    # AC2: the warning text is explicitly tagged, not just "skipped".
    assert any(w.startswith("SKIPPED-BY-BUDGET:") for w in results[0]["warnings"])
    # AC2: a paused pass must never render as PASS *by way of a fake success verdict*
    # — no ai_verdict/truth_findings were fabricated for the paused run.
    assert "truth_findings" not in results[0]


# ── nightly qa_smoke check (#1096) ────────────────────────────────────────────

import qa_smoke_lambda  # noqa: F401,E402  (imported for its module-level env/AWS setup)
from ai import bedrock_client  # noqa: E402
from operational import qa_check_reader_truth  # noqa: E402  (#1665: check_reader_truth's real home)


def _patch_smoke(monkeypatch, payload=None, tier=0, surfaces=None, fetch_warnings=None, invoke=None):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)
    monkeypatch.setattr(
        qa_check_reader_truth, "_fetch_reader_truth_surfaces", lambda: (surfaces if surfaces is not None else _PAGES, fetch_warnings or [])
    )
    monkeypatch.setattr(bedrock_client, "invoke", invoke or _fake_invoke(payload if payload is not None else _CLEAN_VERDICT))


def test_qa_smoke_high_finding_fails_the_check(monkeypatch):
    _patch_smoke(monkeypatch, payload=_HIGH_VERDICT)
    checks = qa_check_reader_truth.check_reader_truth()
    fails = [c for c in checks if c.passed is False]
    assert len(fails) == 1
    assert fails[0].category == "Reader Truth"
    assert "temporal_contradiction" in fails[0].message and "/now/" in fails[0].message


def test_qa_smoke_clean_run_is_ok(monkeypatch):
    _patch_smoke(monkeypatch, payload=_CLEAN_VERDICT)
    checks = qa_check_reader_truth.check_reader_truth()
    # #1922: the deterministic plausibility pass reports first (a warn here —
    # this fixture has no /api/ surfaces for it to check); the LLM verdict follows.
    assert not any(c.passed is False for c in checks)
    verdicts = [c for c in checks if c.name == "reader_truth:verdict"]
    assert len(verdicts) == 1 and verdicts[0].passed is True
    assert "no truth findings" in verdicts[0].message


def test_qa_smoke_low_med_findings_warn_not_fail(monkeypatch):
    low = {"findings": [{"page": "/", "category": "duplicated_narrative", "severity": "low", "note": "same paragraph twice"}]}
    _patch_smoke(monkeypatch, payload=low)
    checks = qa_check_reader_truth.check_reader_truth()
    assert not any(c.passed is False for c in checks)
    assert any(c.passed is None and "duplicated_narrative" in c.message for c in checks)


def test_qa_smoke_bedrock_error_never_reds_the_nightly(monkeypatch):
    def boom(body, model_name=None):
        raise RuntimeError("ServiceUnavailableException: Bedrock down")

    _patch_smoke(monkeypatch, invoke=boom)
    checks = qa_check_reader_truth.check_reader_truth()
    assert not any(c.passed is False for c in checks), "a Bedrock outage must NOT red the nightly"
    assert any(c.passed is None and "fail-soft" in c.message for c in checks)


def test_qa_smoke_budget_tier_pauses_explicitly(monkeypatch):
    def must_not_call(body, model_name=None):
        raise AssertionError("Bedrock must not be called while budget-paused")

    for tier in (3,):  # #1927: only the hard stop pauses this gate now
        _patch_smoke(monkeypatch, tier=tier, invoke=must_not_call)
        checks = qa_check_reader_truth.check_reader_truth()
        # #1922: the deterministic pass STILL runs under a pause — only the LLM half skips.
        paused = [c for c in checks if c.paused]
        assert len(paused) == 1
        assert f"budget tier {tier}" in paused[0].message  # explicit skip state, no silent green
        assert any(c.name == "reader_truth:plausibility" for c in checks)
        assert not any(c.passed is False for c in checks)


def test_qa_smoke_reader_truth_runs_at_the_tiers_it_used_to_skip(monkeypatch):
    """#1927 negative test: tier 1 and 2 are where this platform actually lives
    (tier >= 1 for 26 of 30 measured days), and the nightly gate was paused
    through all of them while reporting no findings. The gate must now RUN there
    — proven by Bedrock actually being called, not by the absence of a pause."""
    for tier in (0, 1, 2):
        calls = []

        def _invoke(body, model_name=None, _calls=calls):
            _calls.append(body)
            return {"content": [{"type": "text", "text": json.dumps({"findings": []})}]}

        _patch_smoke(monkeypatch, tier=tier, invoke=_invoke)
        checks = qa_check_reader_truth.check_reader_truth()
        assert calls, f"the reader-truth gate must call Bedrock at tier {tier} (#1927)"
        assert not any(c.paused for c in checks), f"no check may be paused at tier {tier}"


def test_qa_smoke_budget_tier_pause_emits_qa_paused_metric(monkeypatch):
    """#1440 acceptance: the nightly hook's budget pause emits QAPausedByBudget.

    This is the ONLY guaranteed signal for a pause-only night — qa_smoke's own
    lambda_handler emails nothing when there are zero real FAILUREs (a lone ⏸
    pause never trips the "not fails" branch), so without the metric (feeding
    the qa-paused-by-budget CloudWatch alarm, routed to_digest=True in
    monitoring_stack.py) a budget pause would leave no trace outside raw logs.
    """

    def must_not_call(body, model_name=None):
        raise AssertionError("Bedrock must not be called while budget-paused")

    cw = _patch_cw(monkeypatch)
    _patch_smoke(monkeypatch, tier=3, invoke=must_not_call)
    checks = qa_check_reader_truth.check_reader_truth()

    assert any(c.paused for c in checks)  # #1922: deterministic check accompanies the pause
    assert cw.calls, "a budget-tier pause must emit a CloudWatch metric (#1440)"
    call = cw.calls[-1]
    assert call["Namespace"] == "LifePlatform/QA"
    assert call["MetricData"][0]["MetricName"] == "QAPausedByBudget"
    assert call["MetricData"][0]["Value"] == 1.0


def test_qa_smoke_fetch_failures_warn_softly(monkeypatch):
    _patch_smoke(monkeypatch, payload=_CLEAN_VERDICT, fetch_warnings=["Home (/) — fetch failed: boom"])
    checks = qa_check_reader_truth.check_reader_truth()
    assert any(c.passed is None and "fetch failed" in c.message for c in checks)
    assert any(c.passed is True for c in checks)  # the surviving surfaces still got judged


def test_qa_smoke_no_surfaces_skips_softly(monkeypatch):
    def must_not_call(body, model_name=None):
        raise AssertionError("no surfaces — Bedrock must not be called")

    _patch_smoke(monkeypatch, surfaces=[], fetch_warnings=["all fetches failed"], invoke=must_not_call)
    checks = qa_check_reader_truth.check_reader_truth()
    assert not any(c.passed is False for c in checks)
    assert any("skipped this run" in c.message for c in checks)


# ── deterministic vitals-freshness rule (#1226 regression guard) ──────────────
#
# Fixtures mirror the real "EACH COACH'S READ" digest card prose from the issue.
# The NON-VACUOUS proof lives in the pair below: the exact dateless card the bug
# reproduces on MUST flag, and the same card once the fix adds the as-of kicker
# MUST NOT — so the guard would have failed before the fix and passes after it.

# Reyes' card, verbatim shape from the issue evidence.
_DATELESS_CARD = "Day 1 baselines: recovery score 44%, HRV 34 ms, resting heart rate 62 bpm... 315.6 lbs"
# Chen's card, the "dip" phrasing.
_DATELESS_DIP = "The recovery dip (60% → 44%) is the story of the week."
# Same card once /api/coaching-dashboard supplies analysis_generated_at and
# coaching.js stamps the coachAsOf() kicker into the rendered prose.
_DATED_CARD = _DATELESS_CARD + " as of Jul 13"


def test_vitals_quote_extraction_reads_the_windowed_values():
    q = rtq.quoted_vitals(_DATELESS_CARD)
    assert q["recovery"] == [44] and q["hrv"] == [34] and q["rhr"] == [62]  # not the 315 lbs
    assert rtq.quoted_vitals(_DATELESS_DIP)["recovery"] == [60, 44]  # both dip endpoints


def test_dateless_coach_vitals_quote_is_flagged():
    """The bug: the digest card quotes vitals with no as-of date."""
    findings = rtq.check_vitals_freshness([{"path": "/coaching/", "prose": _DATELESS_CARD}])
    assert len(findings) == 1
    assert findings[0]["category"] == "temporal_contradiction" and findings[0]["severity"] == "high"
    assert "no as-of date" in findings[0]["note"]


def test_dated_coach_vitals_quote_is_clean():
    """The fix: the same card with the as-of kicker no longer flags."""
    assert rtq.check_vitals_freshness([{"path": "/coaching/", "prose": _DATED_CARD}]) == []


def test_guard_is_non_vacuous_dateless_fails_dated_passes():
    """One assertion proving the guard discriminates: flip the ONLY difference
    (the as-of stamp) and the verdict flips — a vacuous rule could not do this."""
    dateless = rtq.check_vitals_freshness([{"path": "/coaching/", "prose": _DATELESS_CARD}])
    dated = rtq.check_vitals_freshness([{"path": "/coaching/", "prose": _DATED_CARD}])
    assert len(dateless) == 1 and dated == []


def test_all_coachasof_kicker_forms_satisfy_the_rule():
    # Every string coachAsOf() can emit must count as an as-of stamp.
    for kicker in ("as of Jul 13", "as of Jul 13 — next refresh pending", "refresh paused (budget guard)"):
        assert rtq.check_vitals_freshness([{"path": "/coaching/", "prose": _DATELESS_CARD + " " + kicker}]) == []


def test_divergence_subcheck_flags_stale_dated_value():
    # A dated read whose quoted recovery is far from that date's true vitals.
    findings = rtq.check_vitals_freshness(
        [{"path": "/coaching/", "prose": _DATELESS_CARD, "as_of": "2026-07-13"}],
        vitals_by_date={"2026-07-13": {"recovery": 96.0, "hrv": 62.0, "rhr": 57.0}},
    )
    assert findings, "44% recovery vs a true 96% on the as-of date must flag"
    assert all(f["severity"] == "med" for f in findings)
    assert any("recovery" in f["note"] for f in findings)


def test_divergence_subcheck_clean_when_values_match():
    findings = rtq.check_vitals_freshness(
        [{"path": "/coaching/", "prose": "recovery score 95%, resting heart rate 58 bpm as of Jul 13", "as_of": "2026-07-13"}],
        vitals_by_date={"2026-07-13": {"recovery": 96.0, "rhr": 57.0}},
    )
    assert findings == []


def test_no_vitals_quote_is_not_flagged():
    assert rtq.check_vitals_freshness([{"path": "/coaching/", "prose": "Sleep looks steady this week. as of Jul 13"}]) == []
    assert rtq.check_vitals_freshness([{"path": "/coaching/", "prose": "Sleep looks steady this week."}]) == []


# ── #1224: word-boundary truncation helper + the mid-word reader-truth guard ───

from common import text_utils  # noqa: E402  (lambdas/ on sys.path via conftest)

# A source longer than the 300-char excerpt budget, ending on real prose. The
# generator's `content_markdown[:300]` cut lands inside "data" → "…before any dat",
# the exact defect the issue reproduces on /journal/posts.json.
_STORY_SOURCE = (
    "The honest part of this week is that the plan was never really tested. I spent it "
    "writing the whole plan down, in public, before any data had a chance to argue back, "
    "which is a different kind of discipline than sticking to a hard cut across four days "
    "in a row while the deficit quietly did its slow, unglamorous, entirely predictable work."
)
# The /coaching/ position_summary defect: `content[:200]` cut lands inside "allocated".
_COACH_SOURCE = (
    "The real pressure point is the deficit: he is holding roughly 1,500 calories allocated "
    "to protein while training hard across four days, and that is a tension worth naming out loud."
)


def _midword_slice(source, word):
    """A fixed-length-style slice of `source` that stops partway through `word`."""
    cut = source.index(word) + len(word) - 1  # drop the last letter of the word
    return source[:cut]


def test_truncate_at_word_no_ellipsis_when_shorter_than_limit():
    # Nothing was cut → no ellipsis appended (preserve intent).
    assert text_utils.truncate_at_word("short and sweet", 200) == "short and sweet"
    assert text_utils.truncate_at_word("  padded  ", 200) == "padded"


def test_truncate_at_word_empty_and_none():
    assert text_utils.truncate_at_word("", 200) == ""
    assert text_utils.truncate_at_word(None, 200) == ""


def test_truncate_at_word_cuts_on_word_boundary_with_ellipsis():
    assert len(_STORY_SOURCE) > 300  # guard the fixture stays longer than the budget
    out = text_utils.truncate_at_word(_STORY_SOURCE, 300)
    assert out.endswith("…"), "a truncated excerpt must be signalled with an ellipsis"
    assert len(out) <= 301, "cut budget (300) + one ellipsis char"
    body = out[:-1].rstrip()  # the kept text, sans ellipsis
    assert _STORY_SOURCE.startswith(body), "truncation is a whole-word prefix of the source"
    assert body.split()[-1] in _STORY_SOURCE.split(), "last kept token is a complete source word"
    assert not body.endswith("dat"), "must not stop mid-word inside 'data'"


def test_truncate_at_word_idempotent_on_already_truncated():
    once = text_utils.truncate_at_word(_STORY_SOURCE, 300)
    assert text_utils.truncate_at_word(once, 300) == once


def test_truncate_at_word_single_long_token_hard_cut_still_ellipsised():
    out = text_utils.truncate_at_word("a" * 500, 200)
    assert out.endswith("…") and len(out) == 201


def test_midword_guard_is_non_vacuous_flags_current_defect_and_clears_after_fix():
    """The regression guard MUST fire on the shipped-today mid-word cut and go
    silent once the word-boundary helper is applied — proving it is not vacuous."""
    # BEFORE: the current generator behaviour — a slice ending '…before any dat'.
    pre_fix = _midword_slice(_STORY_SOURCE, "data")
    assert pre_fix.endswith("dat") and _STORY_SOURCE.startswith(pre_fix + "a")
    before = rtq.check_midword_truncation([{"path": "/story/", "field": "excerpt", "value": pre_fix, "source": _STORY_SOURCE}])
    assert before, "guard must flag the current mid-word excerpt (non-vacuous)"
    assert before[0]["category"] == "audience_violation"

    # AFTER: the same source through the fix helper — guard is clean.
    post_fix = text_utils.truncate_at_word(_STORY_SOURCE, len(pre_fix))
    after = rtq.check_midword_truncation([{"path": "/story/", "field": "excerpt", "value": post_fix, "source": _STORY_SOURCE}])
    assert after == [], "guard must clear once the excerpt is cut on a word boundary"


def test_midword_guard_flags_coaching_card_fragment():
    pre_fix = _midword_slice(_COACH_SOURCE, "allocated")  # stops inside "allocated"
    assert pre_fix[-1].islower() and _COACH_SOURCE.startswith(pre_fix + "d")
    findings = rtq.check_midword_truncation(
        [{"path": "/coaching/", "field": "position_summary", "value": pre_fix, "source": _COACH_SOURCE}]
    )
    assert findings and findings[0]["severity"] == "med"


def test_midword_guard_ignores_full_and_sentence_terminated_values():
    # value == whole source (not truncated) → clean.
    whole = "A complete, untruncated coach read."
    assert rtq.check_midword_truncation([{"value": whole, "source": whole}]) == []
    # truncated but ends on sentence punctuation → clean.
    src = "First sentence ends here. And then a much longer continuation that got dropped."
    assert rtq.check_midword_truncation([{"value": "First sentence ends here.", "source": src}]) == []


# ── #3003: the stored evidence is FULL — truncation is a print-time concern ────
# The 2026-08-22 publish-path hold was triaged from report.json, and every stored
# note ended mid-word ("vague abou", "habit data wit") because _normalize_finding
# capped it at 300 chars — the [never diagnose from a truncated log line] trap
# built into the instrument's own record. A human must be able to adjudicate a
# finding from the artifact without re-running the sweep.

# The observed /story/timeline/ note's shape at real evidence length (>300 chars,
# so this test has teeth against the old cap being reintroduced).
_NOTE_3003 = (
    "The milestone states 'The logs have gone quiet — 4 days without an entry' on Day 6. "
    "If 4 days have passed without an entry, the last entry would have been on Day 2 or earlier. "
    "However, Day 1 is listed as 2026-08-17, making Day 6 equal to 2026-08-22. "
    "The phrase '4 days without an entry' is vague about whether it counts calendar days or elapsed 24-hour periods."
)


def test_normalize_finding_stores_the_full_note():
    assert len(_NOTE_3003) > 300, "the fixture no longer overflows the old cap — this test would prove nothing"
    out = rtq._normalize_finding(
        {"page": "/story/timeline/", "category": "temporal_contradiction", "severity": "high", "note": _NOTE_3003},
        {"/story/timeline/"},
    )
    assert out["note"] == _NOTE_3003, "the stored note must be the model's note IN FULL (#3003)"


def test_truth_line_carries_the_full_note():
    """The report.json issues/warnings line is stored evidence, not console output."""
    f = {"page": "/story/timeline/", "category": "temporal_contradiction", "severity": "high", "note": _NOTE_3003}
    assert _NOTE_3003 in visual_ai_qa._truth_line(f)


# ── #3003: "vague" is not a temporal_contradiction ─────────────────────────────
# /story/timeline/ was render-verified (Day 6, /api/presence gap_days=4.0): the
# copy was TRUE, the oracle's own arithmetic placed the last entry in-cycle, and
# its stated objection resolved to the phrase being "vague" — graded high, which
# held the site publish path. An objection resting on vagueness is editorial,
# never an impossibility, and never gates.


def test_vagueness_objection_fires_on_the_observed_timeline_note():
    f = {"page": "/story/timeline/", "category": "temporal_contradiction", "severity": "high", "note": _NOTE_3003}
    assert rtq.is_vagueness_objection(f) is True


def test_vagueness_objection_spares_a_real_impossibility_claim():
    note = (
        "Prose states 'No training logged — 57 days' on Day 5 of a 5-day experiment "
        "(Day 1 = 2026-08-17). A 57-day history is impossible; the experiment has only existed for 5 days."
    )
    f = {"page": "/data/vitals/", "category": "temporal_contradiction", "severity": "high", "note": note}
    assert rtq.is_vagueness_objection(f) is False


def test_vagueness_objection_never_touches_other_categories():
    for cat in ("duplicated_narrative", "audience_violation", "other"):
        f = {"page": "/", "category": cat, "severity": "high", "note": _NOTE_3003}
        assert rtq.is_vagueness_objection(f) is False, cat


def test_assess_prose_demotes_a_vagueness_high_to_low(capsys):
    """The predicate is wired: a high that resolves to vagueness reaches the gate as low."""
    verdict = {
        "findings": [
            {"page": "/story/timeline/", "category": "temporal_contradiction", "severity": "high", "note": _NOTE_3003},
        ],
        "severity": "high",
        "summary": "x",
    }
    pages = [{"name": "Timeline", "path": "/story/timeline/", "prose": "The logs have gone quiet — 4 days without an entry."}]
    findings, errors = rtq.assess_prose(pages, _fake_invoke(verdict), today_iso=_DAY_2)
    assert errors == []
    assert len(findings) == 1, "demoted, not dropped — it must stay visible as an advisory"
    assert findings[0]["severity"] == "low"
    assert findings[0]["note"] == _NOTE_3003, "demotion must not lose the evidence"
    assert "demoted a vagueness-objection finding" in capsys.readouterr().out


def test_prompt_states_the_vagueness_principle():
    """The clause the model reads and the predicate code enforces state one rule."""
    prompt = rtq.build_prompt([{"name": "Home", "path": "/", "prose": "hello"}], rtq.phase_context(_DAY_2))
    assert "vague" in prompt and "NOT a contradiction" in prompt


# ── #2959: the day counter is not a data bound ─────────────────────────────────
# Five instances in 24h held the publish path twice (runs 32616299944 +
# 32618360726): the model turned the prompt's own phase ground truth into a
# bound ("only 6 days of current-experiment data can exist") and flagged
# legitimately cross-phase content — a trailing 7-day HRV average, the build
# log's history. Notes below are the WIRE — verbatim from the runs' report.json.

_NOTE_2959_HOME = (
    "Home page states 'HRV spiked to 49ms (+27% above your 7-day average)' but only 6 days of "
    "current-experiment data can exist. A 7-day average is impossible on Day 6 of the experiment "
    "(Day 1 = 2026-08-17, today = 2026-08-22). This contradicts the phase constraint that at most "
    "6 days of current-experiment data exist."
)
_NOTE_2959_COCKPIT = (
    "Cockpit states 'HRV spiked to 49ms (+27% above your 7-day average)' in the daily line. This is "
    "impossible on Day 6 when only 6 days of data exist—a 7-day average cannot be computed from 6 "
    "days of current-cycle data."
)
_NOTE_2959_BOARD = (
    "States 'THIS SEASON · CYCLE 14' with '26 GRADED FORECASTS' on Day 5, but only 5 days of data "
    "can exist in the current cycle (started 2026-08-17). On Day 5, a maximum of 5 days of in-cycle "
    "data is possible."
)


def test_day_counter_bound_fires_on_all_three_observed_notes():
    for page, note in (("/", _NOTE_2959_HOME), ("/cockpit/", _NOTE_2959_COCKPIT), ("/method/board/", _NOTE_2959_BOARD)):
        f = {"page": page, "category": "temporal_contradiction", "severity": "high", "note": note}
        assert rtq.is_day_counter_bound_inference(f) is True, page


def test_day_counter_bound_spares_a_bound_unrelated_to_the_day_number():
    note = "Chart claims a 90-day trend but only 30 days of data exist in the retention window; " "today is Day 6 of the cycle."
    f = {"page": "/data/vitals/", "category": "temporal_contradiction", "severity": "high", "note": note}
    assert rtq.is_day_counter_bound_inference(f) is False, "N=30 vs Day 6 — not derived from the day counter"


def test_day_counter_bound_spares_a_genuine_intra_page_contradiction():
    # The #2921 sleep-interleave class: internally contradictory numbers, no bound phrase.
    note = (
        "Field 'total_sleep_hours' is 1.4, but 'deep_sleep_hours' 1.98 + 'rem_sleep_hours' 1.64 "
        "printed beside it sum to 3.62 — sleep cannot total less than its own stages."
    )
    f = {"page": "/api/sleep_detail", "category": "temporal_contradiction", "severity": "high", "note": note}
    assert rtq.is_day_counter_bound_inference(f) is False


def test_day_counter_bound_never_touches_other_categories():
    f = {"page": "/", "category": "audience_violation", "severity": "high", "note": _NOTE_2959_HOME}
    assert rtq.is_day_counter_bound_inference(f) is False


# ── #2959: a finding whose own note withdraws the claim ────────────────────────
# Run 32618360726 emitted BOTH of these at gating severity; each note's final
# sentence retracts the contradiction it reports. Verbatim wire notes.

_NOTE_2959_WALL = (
    "Lists 'ATTEMPT 14 FROM 2026-08-17 alive · day 6', which is correct for the phase. However, "
    "the cycle started 2026-08-17 and today is 2026-08-22, making this Day 6 elapsed — the label "
    "is accurate. No contradiction here on rechecking arithmetic."
)
_NOTE_2959_SURVIVAL = (
    "The survival curve page shows '6 SILENT DAYS RIGHT NOW' and the engagement table shows cycle "
    "14 with strip '······' (6 dots) and '0/6' engagement. The header says 'DAY 6 · WEEK 1, SINCE "
    "AUGUST 17 2026'. This is self-consistent and correct: 6 days have elapsed, all silent. "
    "No contradiction."
)


def test_self_refuted_fires_on_both_observed_notes():
    for page, note in (("/data/wall/", _NOTE_2959_WALL), ("/method/survival/", _NOTE_2959_SURVIVAL)):
        f = {"page": page, "category": "temporal_contradiction", "severity": "high", "note": note}
        assert rtq.is_self_refuted(f) is True, page


def test_self_refuted_spares_a_midnote_consistency_with_live_objection():
    # The /method/postmortems/ shape, same run: consistency stated mid-note, the
    # objection continues after it — a live claim, never dropped.
    note = (
        "The strip shows '······' (6 dots = 6 silent days), which matches Day 1 through Day 6. "
        "However, the postmortem then says 'Showed up 0/6 days. day 6 · live' — this is internally "
        "consistent. But the header dates the restart 2026-08-16, one day before genesis."
    )
    f = {"page": "/method/postmortems/", "category": "temporal_contradiction", "severity": "high", "note": note}
    assert rtq.is_self_refuted(f) is False


def test_self_refuted_spares_an_ordinary_finding():
    f = {"page": "/", "category": "temporal_contradiction", "severity": "high", "note": _NOTE_2959_HOME}
    assert rtq.is_self_refuted(f) is False


def test_assess_prose_demotes_a_day_counter_bound_high_to_low(capsys):
    """The predicate is wired: the / HRV-average high reaches the gate as low."""
    verdict = {
        "findings": [
            {"page": "/", "category": "temporal_contradiction", "severity": "high", "note": _NOTE_2959_HOME},
        ],
        "severity": "high",
        "summary": "x",
    }
    pages = [{"name": "Home", "path": "/", "prose": "HRV spiked to 49ms (+27% above your 7-day average)"}]
    findings, errors = rtq.assess_prose(pages, _fake_invoke(verdict), today_iso=_DAY_2)
    assert errors == []
    assert len(findings) == 1, "demoted, not dropped — stays visible as advisory"
    assert findings[0]["severity"] == "low"
    assert "demoted a day-counter-bound finding" in capsys.readouterr().out


def test_assess_prose_drops_a_self_refuted_finding(capsys):
    """The predicate is wired: a finding whose note withdraws itself never gates."""
    verdict = {
        "findings": [
            {"page": "/data/wall/", "category": "temporal_contradiction", "severity": "high", "note": _NOTE_2959_WALL},
        ],
        "severity": "high",
        "summary": "x",
    }
    pages = [{"name": "Wall", "path": "/data/wall/", "prose": "ATTEMPT 14 FROM 2026-08-17 alive · day 6"}]
    findings, errors = rtq.assess_prose(pages, _fake_invoke(verdict), today_iso=_DAY_2)
    assert errors == []
    assert findings == [], "a withdrawn claim must not reach the gate at any severity"
    assert "dropped a self-refuted finding" in capsys.readouterr().out
