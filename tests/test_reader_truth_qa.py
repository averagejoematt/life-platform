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
    tier >= 1 → explicit ⏸ pause (ADR-125 internal-QA band).

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

import budget_guard  # noqa: E402  (lambdas/ on sys.path via conftest)
import reader_truth_qa as rtq  # noqa: E402
import visual_ai_qa  # noqa: E402
from constants import EXPERIMENT_START_DATE  # noqa: E402

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


def test_prompt_truncates_oversized_prose():
    pages = [{"name": "Big", "path": "/big/", "prose": "x" * (rtq.MAX_PROSE_CHARS + 500)}]
    prompt = rtq.build_prompt(pages, rtq.phase_context(_DAY_2))
    assert "…[truncated]" in prompt
    assert len(prompt) < rtq.MAX_PROSE_CHARS + 4000


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
    _patch_harness(monkeypatch, _HIGH_VERDICT, tier=1, calls=calls)  # internal QA pauses at tier >= 1 (ADR-125)
    visual_ai_qa.assess_reader_truth(results)
    assert calls == []  # no Bedrock spend while paused
    assert results[0]["status"] == "PASS"
    assert any("budget tier 1" in w for w in results[0]["warnings"])  # honest skip, never silent green


# ── nightly qa_smoke check (#1096) ────────────────────────────────────────────

import bedrock_client  # noqa: E402
import qa_smoke_lambda  # noqa: E402


def _patch_smoke(monkeypatch, payload=None, tier=0, surfaces=None, fetch_warnings=None, invoke=None):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)
    monkeypatch.setattr(
        qa_smoke_lambda, "_fetch_reader_truth_surfaces", lambda: (surfaces if surfaces is not None else _PAGES, fetch_warnings or [])
    )
    monkeypatch.setattr(bedrock_client, "invoke", invoke or _fake_invoke(payload if payload is not None else _CLEAN_VERDICT))


def test_qa_smoke_high_finding_fails_the_check(monkeypatch):
    _patch_smoke(monkeypatch, payload=_HIGH_VERDICT)
    checks = qa_smoke_lambda.check_reader_truth()
    fails = [c for c in checks if c.passed is False]
    assert len(fails) == 1
    assert fails[0].category == "Reader Truth"
    assert "temporal_contradiction" in fails[0].message and "/now/" in fails[0].message


def test_qa_smoke_clean_run_is_ok(monkeypatch):
    _patch_smoke(monkeypatch, payload=_CLEAN_VERDICT)
    checks = qa_smoke_lambda.check_reader_truth()
    assert [c.passed for c in checks] == [True]
    assert "no truth findings" in checks[0].message


def test_qa_smoke_low_med_findings_warn_not_fail(monkeypatch):
    low = {"findings": [{"page": "/", "category": "duplicated_narrative", "severity": "low", "note": "same paragraph twice"}]}
    _patch_smoke(monkeypatch, payload=low)
    checks = qa_smoke_lambda.check_reader_truth()
    assert not any(c.passed is False for c in checks)
    assert any(c.passed is None and "duplicated_narrative" in c.message for c in checks)


def test_qa_smoke_bedrock_error_never_reds_the_nightly(monkeypatch):
    def boom(body, model_name=None):
        raise RuntimeError("ServiceUnavailableException: Bedrock down")

    _patch_smoke(monkeypatch, invoke=boom)
    checks = qa_smoke_lambda.check_reader_truth()
    assert not any(c.passed is False for c in checks), "a Bedrock outage must NOT red the nightly"
    assert any(c.passed is None and "fail-soft" in c.message for c in checks)


def test_qa_smoke_budget_tier_pauses_explicitly(monkeypatch):
    def must_not_call(body, model_name=None):
        raise AssertionError("Bedrock must not be called while budget-paused")

    for tier in (1, 2, 3):
        _patch_smoke(monkeypatch, tier=tier, invoke=must_not_call)
        checks = qa_smoke_lambda.check_reader_truth()
        assert len(checks) == 1 and checks[0].paused is True
        assert f"budget tier {tier}" in checks[0].message  # explicit skip state, no silent green
        assert not any(c.passed is False for c in checks)


def test_qa_smoke_fetch_failures_warn_softly(monkeypatch):
    _patch_smoke(monkeypatch, payload=_CLEAN_VERDICT, fetch_warnings=["Home (/) — fetch failed: boom"])
    checks = qa_smoke_lambda.check_reader_truth()
    assert any(c.passed is None and "fetch failed" in c.message for c in checks)
    assert any(c.passed is True for c in checks)  # the surviving surfaces still got judged


def test_qa_smoke_no_surfaces_skips_softly(monkeypatch):
    def must_not_call(body, model_name=None):
        raise AssertionError("no surfaces — Bedrock must not be called")

    _patch_smoke(monkeypatch, surfaces=[], fetch_warnings=["all fetches failed"], invoke=must_not_call)
    checks = qa_smoke_lambda.check_reader_truth()
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
