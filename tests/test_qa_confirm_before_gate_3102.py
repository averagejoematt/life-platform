"""tests/test_qa_confirm_before_gate_3102.py — #3102: confirm-before-gate for
NEW reader-truth highs in tests/visual_ai_qa.py (the CI deploy-time gate).

WHY THIS EXISTS. Measured in the 2026-08-23/24 session: three site-deploys
rolled back on single-run AI-truth verdicts, and two of the three did NOT
reproduce in the adjacent sweep minutes later — a nondeterministic Haiku judge
call over borderline content was the whole basis for a deploy rollback. #2978
already solved the deterministic half of this class (confirm-before-fail,
tests/test_qa_confirm_before_fail_2978.py); the nightly post-deploy alarm
already solved the AI-verdict half for ITS surface (#2741,
lambdas/operational/qa_check_reader_truth.py::_confirm_high_findings —
measured 2/8 flake on byte-identical content). This is the same fix for the
sibling surface that had none: the pre-merge CI gate
(tests/visual_ai_qa.py::assess_reader_truth).

Offline throughout — no Playwright, no live Bedrock; every judge call is a
stub that never leaves the process.

Covers:
  1. `_confirm_new_truth_highs` in isolation: agree-twice gates; disagree does
     NOT gate and is visibly logged (never silently dropped); a re-judge that
     cannot run — ANY exception, explicitly including a BudgetExceeded stand-in
     — fails CLOSED (the original verdict stands); the re-judge reads the
     SAME already-captured surface object (never a re-render); cost is bounded
     to one call per DISTINCT PAGE, not per finding, and a page with no
     matching surface pays nothing.
  2. THE WIRE — visual_ai_qa.assess_reader_truth exercised through the real
     function (reader_truth_qa + budget_guard stubbed, mirrors
     test_truth_baseline_audit.TestWire's harness): only a would-gate NEW high
     ever triggers a second Bedrock call — baselined findings, med/low
     findings, and a clean sweep all cost exactly the one first-pass call.
  3. MUTATION PROOFS: (a) a synthetic agree-twice high still gates [proves the
     confirm path can't accidentally swallow a real, reproducing finding];
     (b) a synthetic disagree finding does NOT gate, is not dropped, and is
     named NON-REPRODUCED in the visible warnings — delete the confirm call
     and this test reds, because a bare `verdict == "new"` would gate on the
     first pass alone.
"""

import os
import sys
import types
import unittest
from unittest import mock

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)

import truth_baseline_audit as tba  # noqa: E402
import visual_ai_qa  # noqa: E402
from operational import reader_truth_qa  # noqa: E402  (lambdas/ on sys.path via conftest)


def _finding(page="/x/", category="temporal_contradiction", severity="high", note="n"):
    return {"page": page, "category": category, "severity": severity, "note": note}


def _surface(page="/x/", prose="hello world"):
    return {"name": page, "path": page, "prose": prose}


def _baseline(pages):
    return {"_meta": {}, "pages": pages}


# ── 1. _confirm_new_truth_highs in isolation ───────────────────────────────────


class TestConfirmNewTruthHighsUnit(unittest.TestCase):
    def test_agree_twice_gates(self):
        f = _finding()
        with mock.patch.object(reader_truth_qa, "assess_prose", return_value=([f], [])) as m:
            confirmed, unconfirmed, note = visual_ai_qa._confirm_new_truth_highs(
                [f], {"/x/": _surface()}, invoke=lambda *a, **k: None, today_iso="2026-08-24"
            )
        self.assertEqual(confirmed, [f])
        self.assertEqual(unconfirmed, [])
        self.assertIsNone(note)
        m.assert_called_once()

    def test_disagree_does_not_gate_and_is_logged_by_name(self):
        f = _finding()
        with mock.patch.object(reader_truth_qa, "assess_prose", return_value=([], [])):
            confirmed, unconfirmed, note = visual_ai_qa._confirm_new_truth_highs(
                [f], {"/x/": _surface()}, invoke=lambda *a, **k: None, today_iso="2026-08-24"
            )
        self.assertEqual(confirmed, [])
        self.assertEqual(unconfirmed, [f])
        self.assertIsNotNone(note, "a non-reproduced finding must be visibly logged, never silent")
        self.assertIn("did NOT reproduce", note)
        self.assertIn("/x/", note)
        self.assertIn("#3102", note)

    def test_reprobe_reads_the_same_captured_surface_never_a_rerender(self):
        f = _finding(page="/y/")
        surface = _surface(page="/y/", prose="EXACT CAPTURED TEXT — do not re-render")
        seen = {}

        def _fake_assess(surfaces, invoke, today_iso=None):
            seen["surfaces"] = surfaces
            return [f], []

        with mock.patch.object(reader_truth_qa, "assess_prose", side_effect=_fake_assess):
            visual_ai_qa._confirm_new_truth_highs([f], {"/y/": surface}, invoke=lambda *a, **k: None, today_iso=None)
        self.assertEqual(seen["surfaces"], [surface], "the re-judge must read the identical surface object")

    def test_fail_closed_on_any_exception(self):
        f = _finding()
        with mock.patch.object(reader_truth_qa, "assess_prose", side_effect=RuntimeError("bedrock throttled")):
            confirmed, unconfirmed, note = visual_ai_qa._confirm_new_truth_highs(
                [f], {"/x/": _surface()}, invoke=lambda *a, **k: None, today_iso=None
            )
        self.assertEqual(confirmed, [f], "an errored re-judge must never downgrade a would-gate high")
        self.assertEqual(unconfirmed, [])
        self.assertIn("fail-closed", note)
        self.assertIn("#3102", note)

    def test_fail_closed_on_budget_exceeded(self):
        class _BudgetExceeded(Exception):
            """Stand-in for ai.budget_guard.BudgetExceeded — the confirm path
            catches broad Exception, so any subclass fails closed identically."""

        f = _finding()
        with mock.patch.object(reader_truth_qa, "assess_prose", side_effect=_BudgetExceeded("tier 3")):
            confirmed, unconfirmed, note = visual_ai_qa._confirm_new_truth_highs(
                [f], {"/x/": _surface()}, invoke=lambda *a, **k: None, today_iso=None
            )
        self.assertEqual(confirmed, [f])
        self.assertEqual(unconfirmed, [])
        self.assertIn("fail-closed", note)

    def test_missing_surface_fails_closed_without_spending_a_call(self):
        f = _finding(page="/gone/")
        with mock.patch.object(reader_truth_qa, "assess_prose") as m:
            confirmed, unconfirmed, note = visual_ai_qa._confirm_new_truth_highs([f], {}, invoke=lambda *a, **k: None, today_iso=None)
        self.assertEqual(confirmed, [f])
        self.assertEqual(unconfirmed, [])
        m.assert_not_called()

    def test_one_call_per_page_not_per_finding(self):
        f1 = _finding(page="/x/", category="temporal_contradiction")
        f2 = _finding(page="/x/", category="fabricated_number")
        with mock.patch.object(reader_truth_qa, "assess_prose", return_value=([f1, f2], [])) as m:
            confirmed, unconfirmed, note = visual_ai_qa._confirm_new_truth_highs(
                [f1, f2], {"/x/": _surface()}, invoke=lambda *a, **k: None, today_iso=None
            )
        m.assert_called_once()  # bounded cost — two would-gate findings, ONE page, ONE call
        self.assertEqual(len(confirmed), 2)

    def test_two_distinct_pages_cost_two_calls(self):
        f1 = _finding(page="/x/")
        f2 = _finding(page="/y/")
        surfaces_by_path = {"/x/": _surface("/x/"), "/y/": _surface("/y/")}
        with mock.patch.object(reader_truth_qa, "assess_prose", return_value=([f1, f2], [])) as m:
            visual_ai_qa._confirm_new_truth_highs([f1, f2], surfaces_by_path, invoke=lambda *a, **k: None, today_iso=None)
        self.assertEqual(m.call_count, 2)


# ── 2 + 3. THE WIRE — assess_reader_truth end-to-end, mutation-proved ──────────


class TestWireConfirmBeforeGate(unittest.TestCase):
    """Mirrors test_truth_baseline_audit.TestWire's harness: reader_truth_qa +
    budget_guard fully stubbed via sys.modules, assess_reader_truth runs for real."""

    def _run(self, results, first_pass_findings, second_pass_by_page=None, baseline_pages=None):
        calls = []

        def _assess_prose(surfaces, invoke, today_iso=None):
            pages = [s["path"] for s in surfaces]
            calls.append(pages)
            if len(calls) == 1:
                return list(first_pass_findings), []
            # every subsequent call is a #3102 confirm re-judge — always one page
            return list((second_pass_by_page or {}).get(pages[0], [])), []

        rubric = types.SimpleNamespace(
            BUDGET_FEATURE="reader_truth_qa",
            emit_budget_pause_metric=lambda *a, **k: None,
            assess_prose=_assess_prose,
            phase_context=lambda *a, **k: {"pre_start": False, "day_n": 5},
        )
        budget = types.SimpleNamespace(allow=lambda *a: True, current_tier=lambda: 0)
        with (
            mock.patch.object(visual_ai_qa, "_import_bedrock", return_value=types.SimpleNamespace(invoke=None)),
            mock.patch.dict(
                sys.modules,
                {
                    "operational.reader_truth_qa": rubric,
                    "operational": types.SimpleNamespace(reader_truth_qa=rubric),
                    "ai": types.SimpleNamespace(budget_guard=budget),
                    "ai.budget_guard": budget,
                },
            ),
            mock.patch.object(tba, "load_baseline", return_value=_baseline(baseline_pages or {})),
        ):
            visual_ai_qa.assess_reader_truth(results)
        return results, calls

    @staticmethod
    def _result(path):
        return {"page": path, "path": path, "status": "PASS", "screenshots": [{"kind": "prose", "path": __file__}]}

    # -- mutation proof (b): agree-twice still gates -----------------------------

    def test_agree_twice_still_gates(self):
        f = _finding(page="/x/")
        results, calls = self._run([self._result("/x/")], [f], {"/x/": [f]})
        self.assertEqual(results[0]["status"], "FAIL")
        self.assertEqual(len(calls), 2, "one first pass + one confirm re-judge")
        self.assertTrue(any("Reader-truth" in i for i in results[0]["issues"]))

    # -- mutation proof (a)+(c): disagree does NOT gate, and is visible ----------

    def test_disagree_does_not_gate_and_is_logged_non_reproduced(self):
        f = _finding(page="/x/")
        results, calls = self._run([self._result("/x/")], [f], {"/x/": []})  # confirm sees nothing
        r = results[0]
        self.assertEqual(r["status"], "PASS", "a non-reproduced high must not gate the deploy")
        self.assertEqual(len(calls), 2)
        self.assertEqual(r.get("issues", []), [], "a non-reproduced high is not a gating issue")
        joined = " ".join(r.get("warnings", []))
        self.assertIn("NON-REPRODUCED", joined)
        self.assertIn("#3102", joined)
        self.assertEqual(len(r.get("truth_findings", [])), 1, "the finding is demoted, never dropped")

    # -- only would-gate NEW highs re-judge; everything else is untouched --------

    def test_baselined_high_never_spends_a_confirm_call(self):
        f = _finding(page="/x/")
        baseline = {"/x/": [{"category": "temporal_contradiction", "issue": "#2956"}]}
        results, calls = self._run([self._result("/x/")], [f], baseline_pages=baseline)
        r = results[0]
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(len(calls), 1, "a baselined finding must never pay for a re-judge")
        self.assertTrue(any("BASELINED" in w for w in r.get("warnings", [])))

    def test_med_severity_finding_never_spends_a_confirm_call(self):
        f = _finding(page="/x/", severity="med")
        results, calls = self._run([self._result("/x/")], [f])
        r = results[0]
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(len(calls), 1, "advisory (med/low) findings never gate and never re-judge")

    def test_clean_sweep_never_spends_a_confirm_call(self):
        results, calls = self._run([self._result("/x/")], [])  # first pass returns no findings
        r = results[0]
        self.assertEqual(r["status"], "PASS")
        self.assertEqual(len(calls), 1)

    def test_mixed_sweep_only_re_judges_the_would_gate_page(self):
        # /x/ is a NEW high (would gate); /y/ is already baselined debt.
        fx = _finding(page="/x/", category="temporal_contradiction")
        fy = _finding(page="/y/", category="audience_violation")
        baseline = {"/y/": [{"category": "audience_violation", "issue": "#2956"}]}
        results, calls = self._run(
            [self._result("/x/"), self._result("/y/")],
            [fx, fy],
            second_pass_by_page={"/x/": [fx]},
            baseline_pages=baseline,
        )
        self.assertEqual(len(calls), 2, "first pass + exactly ONE confirm call, for /x/ only")
        self.assertEqual(calls[1], ["/x/"])
        rx = next(r for r in results if r["path"] == "/x/")
        ry = next(r for r in results if r["path"] == "/y/")
        self.assertEqual(rx["status"], "FAIL")
        self.assertEqual(ry["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
