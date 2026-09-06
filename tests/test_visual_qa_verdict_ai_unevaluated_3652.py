"""tests/test_visual_qa_verdict_ai_unevaluated_3652.py — #3652: "the judge never
answered" is its own surface, and it DECLINES the rollback.

THE INCIDENT
------------
#3540 (2026-09-05) stopped a truncated AI-vision reply from being scored as a clean
``{"severity": "ok", "renders_ok": true}`` pass — the page becomes an explicit
UNEVALUATED FAIL instead. Correct, and it had a second-order effect nobody looked for:
the string it appends (``AI-vision UNEVALUATED (#3540): …``) matched no marker in
`visual_qa_verdict.py`, so it fell through the negative control to ``site-shell`` →
REACHABLE → `rollback-site-on-failure` ran. Result on 2026-09-06: **every** `site/**`
merge deployed and was immediately reverted (runs 34056404335 and 34057051481). The
reader-facing pages survived only because the rollback target happened to already carry
the cycle-17 supersede.

Two things this file has to hold at once, and they pull in opposite directions:

  * an UNEVALUATED page must DECLINE (nobody looked at it, so no one can say a revert
    would help — and the gate still FAILS either way, which is #3540's half and is not
    this module's to weaken); and
  * a page the oracle DID judge and found broken must still ROLL BACK. That positive
    control is the one that matters most: the cheap way to "fix" this issue is to stop
    rolling back on AI verdicts at all, which would quietly retire the gate.

The mixed-report fixture below is transcribed verbatim from run 34056404335's own
`report.json` artifact (downloaded 2026-09-06) — one truncated `/coaching/` verdict plus
two real axe color-contrast regressions — because a fixture that is not the wire is the
class of guard this repo keeps paying for.
"""

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "tests"))

import visual_qa_verdict as V  # noqa: E402

# ── the wire strings, copied from visual_ai_qa.py's own `issues.append` calls ────

UNEVAL_3540 = "AI-vision UNEVALUATED (#3540): the judge returned no readable verdict (truncated) — this page was NOT assessed"
UNEVAL_2973 = "AI-vision UNEVALUATED (#2973): no usable screenshots — every capture for this page is empty/near-empty"
UNEVAL_READER_TRUTH = (
    "Reader-truth UNEVALUATED (#3540): the judge returned no readable verdict for this batch — these pages were NOT assessed"
)
A11Y_RED = (
    "NEW serious a11y violation (axe: color-contrast): Elements must meet minimum color contrast ratio "
    "thresholds — 5 node(s) e.g. article:nth-child(1) > .rd-meta.la"
)
AI_HIGH = "AI-vision (high): the vitals chart frame is drawn but completely empty and the hero headline overlaps the kicker"


def _result(path, issues, *, status="FAIL"):
    return {
        "page": path.strip("/") or "Home",
        "path": path,
        "status": status,
        "issues": list(issues),
        "warnings": [],
        "screenshots": {},
        "perf": {"lcp_ms": 900, "cls": 0.01, "js_bytes": 180_000},
        "shell_content_type": "text/html",
    }


# ── the decline path ────────────────────────────────────────────────────────────


def test_a_truncated_ai_verdict_is_ai_unevaluated_and_declines_the_rollback():
    """The exact 2026-09-06 shape. Before #3652 this classified `site-shell` and the
    rollback ran on every merge."""
    verdict = V.classify_report({"results": [_result("/coaching/", [UNEVAL_3540])]})
    assert verdict["reachable"] is False, "an unjudged page must not authorise an automatic revert"
    assert verdict["surfaces"] == {V.AI_UNEVALUATED: 1}
    assert verdict["pages"][0]["surface"] == V.AI_UNEVALUATED
    assert "no judgement" in verdict["pages"][0]["reason"]
    # the note must name THIS reason, not the two older incidents (#3652 made it per-surface)
    assert "never judged" in verdict["note"]
    assert "the gate still FAILS" in verdict["note"], "the decline must not read as 'this page was fine'"


def test_the_2973_cannot_look_at_it_spelling_declines_too():
    """`AI-vision UNEVALUATED (#2973)` is the older sibling — the oracle could not make
    the call at all (empty captures, a Bedrock ValidationException). Same ruling: nobody
    looked. Matching on the issue NUMBER rather than the class is how one of these two
    would have been left behind."""
    verdict = V.classify_report({"results": [_result("/story/", [UNEVAL_2973])]})
    assert verdict["reachable"] is False
    assert verdict["surfaces"] == {V.AI_UNEVALUATED: 1}


def test_the_reader_truth_judge_going_quiet_is_the_same_class():
    """Vocabulary parity (no live effect on the deploy path — #3251 removed
    `--reader-truth` from the per-deploy copies — but the ruling must not depend on
    WHICH judge went silent)."""
    verdict = V.classify_report({"results": [_result("/data/", [UNEVAL_READER_TRUTH])]})
    assert verdict["reachable"] is False
    assert verdict["surfaces"] == {V.AI_UNEVALUATED: 1}


def test_run_34056404335_the_real_mixed_report_declines_as_a_whole_and_still_names_the_site_shell_half():
    """#3352's AND rule, on the run that filed this issue: one unevaluated page + two
    genuine a11y regressions. The whole rollback declines (a partial revert of a mixed
    failure is the worst of both), and the two site-shell pages are still NAMED so the
    #1447 advisory issue hands a human the half they own."""
    verdict = V.classify_report(
        {
            "results": [
                _result("/coaching/", [UNEVAL_3540]),
                _result("/protocols/discoveries/", [A11Y_RED, "(reproduced on #2978 confirm re-probe — not a transient)"]),
                _result("/method/intelligence/", [A11Y_RED, "(reproduced on #2978 confirm re-probe — not a transient)"]),
            ]
        }
    )
    assert verdict["reachable"] is False
    assert verdict["surfaces"] == {V.AI_UNEVALUATED: 1, V.SITE_SHELL: 2}
    named = {p["path"] for p in verdict["pages"]}
    assert named == {"/coaching/", "/protocols/discoveries/", "/method/intelligence/"}
    assert "1 of 3 failed page(s) are NOT site/**-reachable" in verdict["summary"]


def test_a_page_that_is_both_unevaluated_and_visibly_broken_still_declines():
    """Precedence: `ai-unevaluated` outranks `site-shell`. The page was not judged AS A
    WHOLE, so "revert and hope" is not available for it — but the site-shell match is
    still recorded, and the reason string a human reads names it."""
    page = V.classify_report({"results": [_result("/cockpit/", [UNEVAL_3540, A11Y_RED])]})["pages"][0]
    assert page["surface"] == V.AI_UNEVALUATED
    assert page["surfaces"] == [V.AI_UNEVALUATED, V.SITE_SHELL]


# ── the positive controls: what must STILL roll back ────────────────────────────


def test_a_high_severity_ai_verdict_the_oracle_DID_return_still_rolls_back():
    """THE control that matters. The cheap way to stop the revert loop is to stop
    trusting AI verdicts entirely; that would retire the gate while reporting green.
    A judged, broken page is `site-shell` and REACHABLE, exactly as before #3652."""
    verdict = V.classify_report({"results": [_result("/", [AI_HIGH])]})
    assert verdict["reachable"] is True
    assert verdict["surfaces"] == {V.SITE_SHELL: 1}


def test_the_negative_control_is_untouched_an_unrecognised_string_still_rolls_back():
    """#3352's standing direction: this module may only ever REMOVE a rollback it can
    prove is futile. A shape nobody has thought about still rolls back."""
    verdict = V.classify_report({"results": [_result("/protocols/", ["some brand new failure mode nobody has classified yet"])]})
    assert verdict["reachable"] is True
    assert verdict["surfaces"] == {V.SITE_SHELL: 1}


def test_the_word_unevaluated_alone_does_not_trigger_the_decline():
    """The markers are the full `<judge> UNEVALUATED (` prefix, not the bare word — a
    marker loose enough to match any prose containing "unevaluated" would widen the
    decline set silently, which is the failure mode the negative control exists for."""
    verdict = V.classify_report({"results": [_result("/data/labs/", ["the unevaluated-sample banner overlaps the chart legend"])]})
    assert verdict["reachable"] is True
    assert verdict["surfaces"] == {V.SITE_SHELL: 1}


# ── the live-proof lever ────────────────────────────────────────────────────────


def test_the_injection_lever_can_fire_this_surface_through_the_production_rules():
    """#3352 box 3 / the #3200 lesson: a fail-closed path with green unit tests can be
    entirely non-functional, so the decline must be watchable on a real dispatched run.
    The synthetic result carries the REAL issue string (prefixed `[INJECTED]`) and is
    classified by the SAME marker rules — no short-circuit."""
    assert V.AI_UNEVALUATED in V.injection_choices()
    synthetic = V.injected_result("ai-unevaluated")
    assert synthetic is not None and synthetic["status"] == "FAIL"
    assert "[INJECTED" in synthetic["issues"][0], "the synthetic failure must be labelled everywhere it appears"
    verdict = V.classify_report({"results": [synthetic]})
    assert verdict["reachable"] is False
    assert verdict["pages"][0]["injected"] is True
    assert verdict["pages"][0]["surface"] == V.AI_UNEVALUATED


def test_rule_version_moved_with_the_rule():
    """The module's own contract: bump RULE_VERSION when a classification RULE changes,
    so a verdict.json pulled from an old run artifact is readable against the rules that
    produced it. #3652 added a surface — that is a rule change."""
    assert V.RULE_VERSION == "3652.1"
    assert V.AI_UNEVALUATED not in V.REACHABLE_SURFACES
    assert V.SURFACE_PRECEDENCE.index(V.AI_UNEVALUATED) < V.SURFACE_PRECEDENCE.index(V.SITE_SHELL)
