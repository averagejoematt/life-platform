"""tests/test_judge_verdict_retry_3688.py — #3688: a truncated or unparseable
judge verdict is RETRIED before the surface is recorded UNEVALUATED.

#3652 box 1 asked for: "A judge verdict that comes back truncated is retried (or
its budget raised) before the page is called UNEVALUATED, with the retry visible
in the log." PR #3656 delivered the budget raise (`max_tokens` 700 → 1200, sized
from n=752 verdicts, p99 = 637) and #3652 closed on boxes 2-4. The RETRY half did
not land, and the parenthetical "(or its budget raised)" is what let it not land.

A raised budget makes truncation less likely; it does not make a truncated verdict
recoverable — the money is already spent AND no coverage was bought. And because
`ai-unevaluated` is one of the three classes `tests/visual_qa_verdict.py` routes
to DECLINE, a truncated verdict does not revert the deploy: the gate goes red,
the site stays up, and the reason is a judge that ran out of tokens rather than a
page that is wrong. Silent by construction.

LIVE SPECIMEN (the issue was filed saying there was none — there is now).
`Visual QA (standalone)` run **34907061838**, 2026-09-14T23:03Z, and every
scheduled run of that workflow back to 2026-09-05 (34786433337, 34721963870,
34653985159, 34537384983, 34412212250) — nine consecutive days red:

    [WARN] bedrock response TRUNCATED at max_tokens=1500 (output_tokens=1500, ...)
    ❌ Reader-truth batch UNEVALUATED (#3540, gating): batch [/story/panel/, ...]: UNEVALUATED (unparseable)
    ❌ Reader-truth batch UNEVALUATED (#3540, gating): batch [/method/mirror/, ...]: UNEVALUATED (truncated)
    ❌ Reader-truth batch UNEVALUATED (#3540, gating): batch [/protocols/experiments/, ...]: UNEVALUATED (truncated)
    Reader-truth: 16/19 batch(es) judged over 93 surface(s); 3 UNEVALUATED → FAIL

2 truncated + 1 unparseable, 14 reader-facing surfaces unjudged, on a real run.
Note WHICH judge: the failing call site is `operational/reader_truth_qa.assess_prose`
— the BATCH prose judge — not `visual_ai_qa._assess_page`, the per-page vision
judge the issue's Set named as its one confirmed member. `assess_prose` is a
FOURTH call site the Set table does not list by name, and it is the one the
issue's row 3 ("qa_smoke_lambda check_reader_truth — unverified") actually
resolves to: `qa_check_reader_truth` has no judge of its own, it calls
`assess_prose`. So the same fix covers the nightly advisory AND the CI gate.

What this file holds:
  * behaviour — each covered judge re-asks ONCE at a doubled budget, prints the
    retry by attempt number and reason, and records UNEVALUATED only if the
    SECOND answer is still unreadable;
  * the no-free-lunch control — a readable first verdict costs exactly one call;
  * the chokepoint — both sites route through
    `lambdas/common/retry_utils.invoke_until_readable_verdict`, not a private loop;
  * THE SET — the judge call sites are enumerated FROM SOURCE (every place that
    decides `stop_reason == "max_tokens"`), and each one must be either covered
    here or registered as a residual naming the issue it is folded onto. Fixing
    the specimen is not fixing the class.
"""

import json
import os
import re
import struct
import sys

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_TESTS_DIR)
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import pytest  # noqa: E402
import visual_ai_qa  # noqa: E402
from ai import budget_guard  # noqa: E402  (lambdas/ on sys.path via conftest)
from common import retry_utils  # noqa: E402
from operational import reader_truth_qa as rtq  # noqa: E402

# ── fixtures: a judge that answers badly, then well ───────────────────────────

_TRUTH_CLEAN = {"findings": [], "severity": "ok", "summary": "clean"}
_TRUTH_HIGH = {
    "findings": [{"page": "/cockpit/", "category": "other", "severity": "high", "note": "a real finding, on the second attempt"}],
    "severity": "high",
    "summary": "one finding",
}
_VISION_OK = {"renders_ok": True, "issues": [], "severity": "ok", "summary": "fine"}

_PAGES = [{"name": "Cockpit", "path": "/cockpit/", "prose": "DAY 9 · the cockpit prose"}]

# The three unreadable shapes, as (response-kwargs, expected kind). These are the
# #3540 vocabulary both judges share.
_UNREADABLE = [
    pytest.param({"text": '{"findings": [{"page": "/cockpit/", "sev', "stop_reason": "max_tokens"}, "truncated", id="truncated"),
    pytest.param({"text": '{"findings": [,,]}', "stop_reason": "end_turn"}, "unparseable", id="unparseable"),
    pytest.param({"text": "Sure! Here is my assessment in prose.", "stop_reason": "end_turn"}, "no_verdict", id="no_verdict"),
]


def _scripted_invoke(replies, calls):
    """A bedrock-shaped invoke that returns `replies` in order, recording each call."""

    def invoke(body, model_name=None):
        calls.append({"max_tokens": body.get("max_tokens"), "model_name": model_name})
        spec = replies[min(len(calls) - 1, len(replies) - 1)]
        resp = {"content": [{"type": "text", "text": spec["text"]}]}
        if spec.get("stop_reason") is not None:
            resp["stop_reason"] = spec["stop_reason"]
        return resp

    return invoke


def _png_bytes(w=100, h=100, pad=400):
    ihdr = struct.pack(">II", w, h) + b"\x08\x06\x00\x00\x00"
    return b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + ihdr + b"\x00" * pad


def _result_with_shot(tmp_path, name="Cockpit", path="/cockpit/"):
    shot = tmp_path / f"{name}.png"
    shot.write_bytes(_png_bytes())
    return {
        "page": name,
        "path": path,
        "tier": 1,
        "status": "PASS",
        "issues": [],
        "warnings": [],
        "screenshots": [{"kind": "page", "path": str(shot)}],
    }


def _bedrock(invoke):
    return type("B", (), {"invoke": staticmethod(invoke)})()


# ── member 1: operational/reader_truth_qa.assess_prose (the LIVE specimen) ────


@pytest.mark.parametrize("bad,kind", _UNREADABLE)
def test_reader_truth_unreadable_batch_is_retried_and_the_second_answer_is_used(bad, kind, capsys):
    """Pre-fix this fails on the FIRST assert: one call, and the batch went
    straight into `errors` as UNEVALUATED. Run 34907061838's three batches are
    exactly this shape."""
    calls = []
    invoke = _scripted_invoke([bad, {"text": json.dumps(_TRUTH_HIGH), "stop_reason": "end_turn"}], calls)

    findings, errors = rtq.assess_prose(_PAGES, invoke)

    assert len(calls) == 2, f"the unreadable ({kind}) verdict was not re-asked — {len(calls)} call(s) made"
    assert not errors, f"the batch was recorded UNEVALUATED despite a readable second verdict: {[str(e) for e in errors]}"
    assert [f["note"] for f in findings] == ["a real finding, on the second attempt"]


@pytest.mark.parametrize("bad,kind", _UNREADABLE)
def test_reader_truth_retry_raises_the_budget_rather_than_re_asking_identically(bad, kind):
    """A re-ask at the identical cap is the #2893 re-bill with extra steps. The
    second attempt must be materially different from the one that just failed."""
    calls = []
    invoke = _scripted_invoke([bad, {"text": json.dumps(_TRUTH_CLEAN), "stop_reason": "end_turn"}], calls)
    rtq.assess_prose(_PAGES, invoke)
    assert len(calls) == 2
    assert calls[1]["max_tokens"] > calls[0]["max_tokens"], f"the retry re-asked at the SAME budget {calls[0]['max_tokens']}"
    assert calls[1]["max_tokens"] == calls[0]["max_tokens"] * retry_utils.VERDICT_RETRY_BUDGET_MULTIPLIER


@pytest.mark.parametrize("bad,kind", _UNREADABLE)
def test_reader_truth_retry_is_visible_in_the_log_by_attempt_and_reason(bad, kind, capsys):
    """#3652 box 1's actual wording: "with the retry visible in the log". A run
    that retried must be distinguishable from a run that did not."""
    calls = []
    invoke = _scripted_invoke([bad, {"text": json.dumps(_TRUTH_CLEAN), "stop_reason": "end_turn"}], calls)
    rtq.assess_prose(_PAGES, invoke)
    out = capsys.readouterr().out
    assert "verdict retry" in out, f"the retry left NO trace in the log:\n{out}"
    assert kind in out, f"the log does not name WHY it retried ({kind}):\n{out}"
    assert "attempt 1/2" in out, f"the log does not name the attempt number:\n{out}"
    assert "#3688" in out
    assert "/cockpit/" in out, "the log does not name WHAT was re-judged"


@pytest.mark.parametrize("bad,kind", _UNREADABLE)
def test_reader_truth_persistently_unreadable_batch_still_lands_as_unevaluated(bad, kind, capsys):
    """The retry must not become a way to LOSE the UNEVALUATED signal. Two bad
    answers is still no coverage, recorded exactly as #3540 records it."""
    calls = []
    invoke = _scripted_invoke([bad], calls)  # every attempt is bad
    findings, errors = rtq.assess_prose(_PAGES, invoke)
    assert len(calls) == retry_utils.VERDICT_RETRY_MAX_ATTEMPTS
    assert len(errors) == 1 and rtq.is_unevaluated(errors[0])
    assert errors[0].kind == kind and errors[0].paths == ("/cockpit/",)
    assert f"UNEVALUATED ({kind})" in str(errors[0])
    assert "still unreadable" in capsys.readouterr().out


def test_reader_truth_readable_first_verdict_costs_exactly_one_call():
    """The no-free-lunch control: the retry may not double the bill on the p50
    call. A guard that fires on a good verdict is a cost regression, not a fix."""
    calls = []
    invoke = _scripted_invoke([{"text": json.dumps(_TRUTH_CLEAN), "stop_reason": "end_turn"}], calls)
    findings, errors = rtq.assess_prose(_PAGES, invoke)
    assert len(calls) == 1 and not errors and not findings


def test_reader_truth_transport_failure_is_not_this_loops_class():
    """A raised exception keeps its existing fail-soft ⚠ (#1440) and is NOT
    re-asked by the verdict loop — the transport ladder above it owns that."""
    calls = []

    def boom(body, model_name=None):
        calls.append(body)
        raise RuntimeError("bedrock throttled")

    findings, errors = rtq.assess_prose(_PAGES, boom)
    assert len(calls) == 1, "a transport error was re-asked by the VERDICT retry (wrong layer)"
    assert len(errors) == 1 and not rtq.is_unevaluated(errors[0])


# ── member 2: tests/visual_ai_qa._assess_page (the issue's confirmed member) ──


@pytest.mark.parametrize("bad,kind", _UNREADABLE)
def test_vision_unreadable_verdict_is_retried_and_the_page_is_not_unevaluated(bad, kind, monkeypatch, tmp_path):
    """Pre-fix: `_assess_page` returned `_unevaluated_verdict(...)` on the first
    bad answer, the page went FAIL/ai_unevaluated, and `visual_qa_verdict` then
    DECLINED the rollback — red gate, live site, no second look."""
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    calls = []
    invoke = _scripted_invoke([bad, {"text": json.dumps(_VISION_OK), "stop_reason": "end_turn"}], calls)
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _bedrock(invoke))

    results = [_result_with_shot(tmp_path)]
    status = visual_ai_qa.assess_results(results)

    assert len(calls) == 2, f"the unreadable ({kind}) verdict was not re-asked — {len(calls)} call(s) made"
    assert status == {"status": "ok", "evaluated": 1, "unevaluated": 0, "no_shots": 0}
    assert results[0]["status"] == "PASS" and "ai_unevaluated" not in results[0]
    assert calls[1]["max_tokens"] == calls[0]["max_tokens"] * retry_utils.VERDICT_RETRY_BUDGET_MULTIPLIER


@pytest.mark.parametrize("bad,kind", _UNREADABLE)
def test_vision_retry_is_visible_in_the_log_and_names_the_page(bad, kind, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    invoke = _scripted_invoke([bad, {"text": json.dumps(_VISION_OK), "stop_reason": "end_turn"}], [])
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _bedrock(invoke))
    visual_ai_qa.assess_results([_result_with_shot(tmp_path)])
    out = capsys.readouterr().out
    assert "verdict retry" in out and kind in out and "#3688" in out, out
    assert "/cockpit/" in out, "the log does not name WHICH page was re-judged"


@pytest.mark.parametrize("bad,kind", _UNREADABLE)
def test_vision_persistently_unreadable_page_still_fails_as_unevaluated(bad, kind, monkeypatch, tmp_path):
    """#3540/#2973's ruling for this caller is unchanged — it is now taken on the
    LAST attempt rather than the first."""
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    calls = []
    monkeypatch.setattr(visual_ai_qa, "_import_bedrock", lambda: _bedrock(_scripted_invoke([bad], calls)))
    results = [_result_with_shot(tmp_path)]
    status = visual_ai_qa.assess_results(results)
    assert len(calls) == retry_utils.VERDICT_RETRY_MAX_ATTEMPTS
    assert status["unevaluated"] == 1 and status["evaluated"] == 0
    assert results[0]["status"] == "FAIL" and results[0]["ai_unevaluated"]
    assert results[0]["ai_verdict"][visual_ai_qa._UNEVALUATED_FIELD] == kind


def test_vision_readable_first_verdict_costs_exactly_one_call(monkeypatch, tmp_path):
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    calls = []
    monkeypatch.setattr(
        visual_ai_qa,
        "_import_bedrock",
        lambda: _bedrock(_scripted_invoke([{"text": json.dumps(_VISION_OK), "stop_reason": "end_turn"}], calls)),
    )
    results = [_result_with_shot(tmp_path)]
    assert visual_ai_qa.assess_results(results) == {"status": "ok", "evaluated": 1, "unevaluated": 0, "no_shots": 0}
    assert len(calls) == 1


# ── the chokepoint: one loop, not three ───────────────────────────────────────

_COVERED_SOURCES = {
    "lambdas/operational/reader_truth_qa.py": "the reader-truth BATCH judge (assess_prose) — CI gate + nightly + restart-verify",
    "tests/visual_ai_qa.py": "the per-page AI-vision judge (_assess_page)",
}


def _read(rel):
    with open(os.path.join(_REPO, rel)) as f:
        return f.read()


@pytest.mark.parametrize("rel", sorted(_COVERED_SOURCES))
def test_each_covered_judge_routes_through_the_common_retry_chokepoint(rel):
    """The issue's own wording: "routed through the existing retry chokepoint
    rather than a new one". A second private copy of this loop is how the two
    judges' truncation handling drifted apart in the first place."""
    src = _read(rel)
    assert "from common.retry_utils import invoke_until_readable_verdict" in src, f"{rel} does not import the chokepoint"
    assert "invoke_until_readable_verdict" in src


def test_the_chokepoint_never_retries_a_readable_verdict_or_swallows_a_transport_error():
    """Unit-level, so the property is pinned independently of either caller."""
    calls = []
    resp, reason, n = retry_utils.invoke_until_readable_verdict(
        _scripted_invoke([{"text": "ok", "stop_reason": "end_turn"}], calls), {"max_tokens": 100}, unreadable=lambda r: None
    )
    assert (reason, n, len(calls)) == (None, 1, 1)

    def boom(body, model_name=None):
        raise RuntimeError("transport")

    with pytest.raises(RuntimeError):
        retry_utils.invoke_until_readable_verdict(boom, {"max_tokens": 100}, unreadable=lambda r: "truncated")


def test_the_batch_judges_budget_is_a_named_constant_the_control_can_force():
    """`assess_prose` sent a bare `"max_tokens": 1500`, so the issue's own
    reproduction ("lower the budget below p50") had no knob and the positive
    control could only be faked. Same rule the sibling gate already enforces for
    `visual_ai_qa._VERDICT_MAX_TOKENS` (#3652): every budget is a NAMED constant.
    The value is unchanged — #3688 is the retry, not another raise."""
    src = _read("lambdas/operational/reader_truth_qa.py")
    assert rtq.BATCH_VERDICT_MAX_TOKENS == 1500
    body = src.split("def assess_prose")[1]
    assert '"max_tokens": BATCH_VERDICT_MAX_TOKENS' in body
    assert not re.search(r'"max_tokens":\s*\d+', body), "assess_prose hardcodes a max_tokens literal again"


def test_the_chokepoint_does_not_mutate_the_callers_body():
    """Callers build one body per batch and reuse it; a retry that edits it in
    place would leak the doubled budget into the next batch's first attempt."""
    body = {"max_tokens": 1500, "messages": []}
    retry_utils.invoke_until_readable_verdict(
        _scripted_invoke([{"text": "x", "stop_reason": "end_turn"}], []), body, unreadable=lambda r: "truncated"
    )
    assert body["max_tokens"] == 1500


# ── THE SET, enumerated from source ───────────────────────────────────────────
#
# The enumeration property: a JUDGE call site is a place in first-party source
# that DECIDES on `stop_reason == "max_tokens"` — i.e. turns a model reply into a
# terminal verdict about coverage. That is a structural query over the tree, not a
# hand-kept list, so a fourth judge added tomorrow reds this test instead of
# quietly inheriting the no-retry default. (The issue's own `grep max_tokens`
# query returns ~90 hits dominated by output-budget literals; this narrows to the
# decision itself, which is the property that matters.)
#
# THE PATTERN WAS WIDENED BY ITS OWN MUTATION RUN, which is worth recording. The first
# draft matched only `get("stop_reason") … == "max_tokens"`. Mutation M4 rewrote the
# COVERED site in tests/visual_ai_qa.py to `resp.get("stop_reason") in ("max_tokens",)`
# — semantically identical, and the draft pattern went blind to it. So the rule now
# requires the two names on one line with a COMPARISON between them (`==`, `!=`, or
# membership), which catches the subscript, membership and negated forms alike, and
# trailing `# …` is stripped first so a decision is never confused with a note about one.
# Measured across the whole scan surface: the widened rule returns the SAME three sites,
# no new false positives.
# STILL INVISIBLE, stated rather than papered over: a two-line form
# (`sr = resp.get("stop_reason")` … `if sr == "max_tokens":`), a helper that returns the
# stop reason, and a parse failure reached without reading stop_reason at all. Those are
# gaps, not passes — which is why the two covered sites ALSO carry behavioural tests
# above rather than resting on this census.
_DECIDES_ON_TRUNCATION = re.compile(
    r"""stop_reason[^\n]*?(?:==|!=|\bin\b)[^\n]*?max_tokens|max_tokens[^\n]*?(?:==|!=|\bin\b)[^\n]*?stop_reason"""
)
_TRAILING_COMMENT = re.compile(r"\s#.*$")
_SCAN_DIRS = ("lambdas", "mcp", "scripts", "deploy", "cdk")
_SCAN_FILES = ("tests/visual_ai_qa.py", "tests/visual_qa.py", "tests/visual_qa_verdict.py")

# Sites that decide on truncation but are NOT judges, with the issue each is
# folded onto BY NAME. A residual may not be silent — that is the #3652 box-1
# failure mode this file exists to close.
_RESIDUAL = {
    "lambdas/ai/bedrock_client.py": (
        "#2893",
        "the fleet-wide truncation METER (_meter_truncation) — it WARNs and returns the response "
        "unchanged for every caller including the daily-brief narrative. Recovering a truncated "
        "NARRATIVE is a different decision from recovering a truncated VERDICT (prose survives "
        "truncation, a verdict does not), and it is #2893's, not this issue's.",
    ),
}


def _enumerate_truncation_decision_sites():
    hits = {}
    paths = [os.path.join(_REPO, f) for f in _SCAN_FILES]
    for d in _SCAN_DIRS:
        for root, dirs, files in os.walk(os.path.join(_REPO, d)):
            dirs[:] = [x for x in dirs if x not in ("node_modules", "cdk.out", "__pycache__", ".venv")]
            paths.extend(os.path.join(root, f) for f in files if f.endswith(".py"))
    for p in paths:
        if not os.path.isfile(p):
            continue
        rel = os.path.relpath(p, _REPO)
        with open(p, encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if line.lstrip().startswith("#"):
                    continue  # a comment ABOUT the decision is not the decision
                if _DECIDES_ON_TRUNCATION.search(_TRAILING_COMMENT.sub("", line)):
                    hits.setdefault(rel, []).append(i)
    return hits


def test_the_judge_call_site_set_is_enumerated_from_source_and_every_member_is_covered():
    """3/3, or the residual folded onto #2893 BY NAME — the issue's acceptance box 4.

    Covered:  operational/reader_truth_qa.py  (the batch prose judge — the live
              specimen; also the code behind the Set's row 3, `qa_smoke_lambda`'s
              check_reader_truth, which owns no judge of its own)
              tests/visual_ai_qa.py           (the per-page vision judge — row 1)
    Residual: lambdas/ai/bedrock_client.py    (the truncation meter → #2893, row 2)
    """
    hits = _enumerate_truncation_decision_sites()
    known = set(_COVERED_SOURCES) | set(_RESIDUAL)
    unregistered = {rel: lines for rel, lines in hits.items() if rel not in known}
    assert not unregistered, (
        "a NEW site decides on a truncated model reply and is neither covered by the #3688 retry "
        "nor registered as a residual naming its issue:\n" + "\n".join(f"  {rel}:{lines}" for rel, lines in sorted(unregistered.items()))
    )
    for rel in _COVERED_SOURCES:
        assert rel in hits, f"{rel} no longer decides on truncation — the Set membership moved; re-derive it"


def test_the_sets_third_row_resolves_to_the_covered_batch_judge_not_a_fourth_judge():
    """The issue lists `qa_smoke_lambda check_reader_truth` as an unverified third
    member. Verified here, from source: it delegates to `assess_prose` and owns no
    truncation decision, so covering `assess_prose` covers it — the nightly
    advisory AND the CI gate, one fix."""
    src = _read("lambdas/operational/qa_check_reader_truth.py")
    assert "reader_truth_qa.assess_prose(" in src
    assert not _DECIDES_ON_TRUNCATION.search(src), "qa_check_reader_truth grew its OWN truncation decision — enumerate it into the Set"


def test_every_residual_names_the_issue_it_is_folded_onto_in_its_own_source():
    """A residual recorded only in this test file is a residual nobody reading the
    code will find. The named issue must appear in the module itself."""
    for rel, (issue, _why) in _RESIDUAL.items():
        assert issue in _read(rel), f"{rel} is folded onto {issue} but its source never names it"
