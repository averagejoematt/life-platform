"""tests/test_truth_baseline_audit.py — the reader-truth debt ledger's contract.

Offline (no Playwright, no Bedrock). Three guarantees:

  1. GATE SEMANTICS — a NEW high (page, category) finding still FAILs; a
     baselined one downgrades to a visible warning naming its issue; med/low
     never gate (unchanged); an unobserved baselined entry is a shrink
     candidate, and an unswept page is never reported as fixed.
  2. THE COMMITTED FILE IS TRIAGED — every entry in tests/truth_baseline.json
     carries a real issue ref (UNTRIAGED or blank reds this suite), so the
     --update-truth-baseline path cannot be committed without triage.
  3. THE WIRE — visual_ai_qa.assess_reader_truth consults this module: a
     baselined high finding must NOT set the page's status to FAIL, and a new
     high finding must. Tested through the real assess_reader_truth with a
     stubbed Bedrock invoke, not a re-implementation.
"""

import json
import os
import sys
import types
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))

import truth_baseline_audit as tba  # noqa: E402


def _finding(page="/x/", category="temporal_contradiction", severity="high", note="n"):
    return {"page": page, "category": category, "severity": severity, "note": note}


def _baseline(pages):
    return {"_meta": {}, "pages": pages}


class TestGateSemantics(unittest.TestCase):
    def test_new_high_gates(self):
        self.assertEqual(tba.gate_finding(_finding(), _baseline({})), "new")

    def test_baselined_high_does_not_gate(self):
        base = _baseline({"/x/": [{"category": "temporal_contradiction", "issue": "#2956"}]})
        self.assertEqual(tba.gate_finding(_finding(), base), "baselined")
        self.assertEqual(tba.baselined_issue(_finding(), base), "#2956")

    def test_same_page_different_category_still_gates(self):
        base = _baseline({"/x/": [{"category": "audience_violation", "issue": "#2956"}]})
        self.assertEqual(tba.gate_finding(_finding(category="temporal_contradiction"), base), "new")

    def test_different_page_same_category_still_gates(self):
        base = _baseline({"/y/": [{"category": "temporal_contradiction", "issue": "#2956"}]})
        self.assertEqual(tba.gate_finding(_finding(page="/x/"), base), "new")

    def test_med_low_are_advisory_regardless(self):
        for sev in ("med", "low"):
            self.assertEqual(tba.gate_finding(_finding(severity=sev), _baseline({})), "advisory")

    def test_shrink_candidates_only_for_unobserved(self):
        base = _baseline(
            {
                "/x/": [{"category": "temporal_contradiction", "issue": "#1"}],
                "/y/": [{"category": "temporal_contradiction", "issue": "#2"}],
            }
        )
        observed = [_finding(page="/x/")]
        self.assertEqual(tba.shrink_candidates(observed, base), {"/y/": ["temporal_contradiction"]})

    def test_untriaged_entries_detected(self):
        base = _baseline(
            {
                "/x/": [{"category": "a", "issue": "UNTRIAGED"}, {"category": "b", "issue": "#5"}],
                "/y/": [{"category": "c", "issue": ""}],
            }
        )
        self.assertEqual(tba.untriaged_entries(base), [("/x/", "a"), ("/y/", "c")])


class TestUpdatePath(unittest.TestCase):
    def _tmp(self):
        import tempfile

        d = tempfile.mkdtemp()
        return os.path.join(d, "truth_baseline.json")

    def test_update_preserves_unswept_and_prior_issue_refs(self):
        p = self._tmp()
        tba.update_baseline({"/x/": [_finding(page="/x/")]}, path=p)
        base = tba.load_baseline(p)
        # fresh entry lands UNTRIAGED — commit-blocked until triaged
        self.assertEqual(base["pages"]["/x/"][0]["issue"], tba.UNTRIAGED)
        base["pages"]["/x/"][0]["issue"] = "#2956"
        with open(p, "w") as f:
            json.dump(base, f)
        # a later --page sweep of /y/ must not touch /x/ or its ref
        tba.update_baseline({"/y/": [_finding(page="/y/")]}, path=p)
        base = tba.load_baseline(p)
        self.assertEqual(base["pages"]["/x/"][0]["issue"], "#2956")
        self.assertIn("/y/", base["pages"])

    def test_clean_page_is_removed(self):
        p = self._tmp()
        tba.update_baseline({"/x/": [_finding(page="/x/")]}, path=p)
        report = tba.update_baseline({"/x/": []}, path=p)
        self.assertNotIn("/x/", tba.load_baseline(p)["pages"])
        # A drop is never self-evidently a fix — the fail-soft oracle (#2973)
        # makes an errored page look exactly like a clean one, so say it.
        self.assertEqual(report["dropped"], ["/x/ [temporal_contradiction]"])
        self.assertIn("dropped 1 entry", " ".join(tba.update_summary(report)))


class TestSeverityFreeWritePath(unittest.TestCase):
    """#2981 — the write path records a pair at ANY severity; only READ gates."""

    def _tmp(self):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), "truth_baseline.json")

    def test_sub_gating_severity_is_recorded(self):
        p = self._tmp()
        report = tba.update_baseline({"/x/": [_finding(page="/x/", severity="med")]}, path=p)
        base = tba.load_baseline(p)
        self.assertIn("/x/", base["pages"], "a med finding on an unbaselined page must still be recorded (#2981)")
        self.assertEqual(base["pages"]["/x/"][0]["severity_observed"], "med")
        self.assertEqual(report["added"], ["/x/ [temporal_contradiction]"])
        self.assertTrue(report["changed"])

    def test_recording_at_med_pre_authorizes_the_high_grade(self):
        """The whole point: the same pair graded high on a later run must NOT gate.

        This is the #2981 loop with no exit — baseline it while the oracle says
        med, and the next high grade still failed the deploy.
        """
        p = self._tmp()
        tba.update_baseline({"/x/": [_finding(page="/x/", severity="med")]}, path=p)
        base = tba.load_baseline(p)
        base["pages"]["/x/"][0]["issue"] = "#2972"
        with open(p, "w") as f:
            json.dump(base, f)
        self.assertEqual(tba.gate_finding(_finding(page="/x/", severity="high"), tba.load_baseline(p)), "baselined")

    def test_highest_observed_severity_wins_per_pair(self):
        p = self._tmp()
        tba.update_baseline(
            {"/x/": [_finding(page="/x/", severity="low", note="a"), _finding(page="/x/", severity="high", note="b")]},
            path=p,
        )
        row = tba.load_baseline(p)["pages"]["/x/"][0]
        self.assertEqual(row["severity_observed"], "high")
        self.assertEqual(row["note_sample"], "b")

    def test_gating_is_unchanged_at_read_time(self):
        """A recorded sub-gating pair must not make med/low findings gate."""
        base = _baseline({"/x/": [{"category": "temporal_contradiction", "issue": "#1", "severity_observed": "med"}]})
        self.assertEqual(tba.gate_finding(_finding(page="/x/", severity="med"), base), "advisory")
        self.assertEqual(tba.gate_finding(_finding(page="/x/", severity="high"), base), "baselined")


class TestUpdateIsNeverABareSuccessLine(unittest.TestCase):
    """#2981 — 'truth baseline rewritten' printed over a no-op cost a deploy plane."""

    def _tmp(self):
        import tempfile

        return os.path.join(tempfile.mkdtemp(), "truth_baseline.json")

    def test_a_no_op_run_says_nothing_was_recorded(self):
        p = self._tmp()
        tba.update_baseline({"/x/": [_finding(page="/x/")]}, path=p)
        report = tba.update_baseline({"/x/": [_finding(page="/x/")]}, path=p)  # identical re-sweep
        self.assertFalse(report["changed"])
        text = " ".join(tba.update_summary(report))
        self.assertIn("NOTHING was recorded", text)
        self.assertNotIn("rewritten", text)

    def test_an_empty_sweep_is_reported_and_writes_nothing(self):
        p = self._tmp()
        tba.update_baseline({"/x/": [_finding(page="/x/")]}, path=p)
        stamp = tba.load_baseline(p)["_meta"]["captured_at"]
        report = tba.update_baseline({}, path=p)
        self.assertIn("NOT updated", " ".join(tba.update_summary(report)))
        self.assertEqual(tba.load_baseline(p)["_meta"]["captured_at"], stamp, "a 0-page sweep must not restamp captured_at")

    def test_untriaged_entries_are_named_in_the_summary(self):
        p = self._tmp()
        report = tba.update_baseline({"/x/": [_finding(page="/x/")]}, path=p)
        self.assertIn("UNTRIAGED", " ".join(tba.update_summary(report)))

    def test_the_caller_renders_the_report_rather_than_its_own_success_line(self):
        """visual_qa.py must print update_summary's lines, not a literal of its own."""
        src = open(os.path.join(os.path.dirname(__file__), "visual_qa.py"), encoding="utf-8").read()
        self.assertIn("truth_baseline_audit.update_summary(report)", src)
        self.assertNotIn("truth baseline rewritten", src)


class TestCommittedFileIsTriaged(unittest.TestCase):
    def test_committed_baseline_has_no_untriaged_entries(self):
        base = tba.load_baseline()  # missing file → empty → passes
        self.assertEqual(
            tba.untriaged_entries(base),
            [],
            "tests/truth_baseline.json has UNTRIAGED entries — file/name the tracking issue "
            "for each before committing (the ledger is triaged debt, not an excuse file)",
        )

    def test_committed_entries_reference_real_issue_shapes(self):
        base = tba.load_baseline()
        for page, rows in base.get("pages", {}).items():
            for r in rows:
                self.assertRegex(
                    r.get("issue", ""),
                    r"^#\d{3,5}$",
                    f"{page}/{r.get('category')}: issue ref {r.get('issue')!r} is not '#NNNN'",
                )


class TestWire(unittest.TestCase):
    """assess_reader_truth consults the ledger — through the real function."""

    def _run(self, finding, baseline_pages):
        # Stub the bedrock + budget imports assess_reader_truth performs, and
        # the rubric module, so the only real logic under test is the
        # gate-vs-baseline branch on the returned finding.
        import visual_ai_qa

        results = [
            {
                "page": "X",
                "path": finding["page"],
                "status": "PASS",
                "screenshots": [{"kind": "prose", "path": __file__}],  # any readable file
            }
        ]
        rubric = types.SimpleNamespace(
            BUDGET_FEATURE="reader_truth_qa",
            emit_budget_pause_metric=lambda *a, **k: None,
            assess_prose=lambda surfaces, invoke: ([finding], []),
            phase_context=lambda: {"pre_start": False, "day_n": 5},
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
            mock.patch.object(tba, "load_baseline", return_value=_baseline(baseline_pages)),
        ):
            visual_ai_qa.assess_reader_truth(results)
        return results[0]

    def test_new_high_fails_page(self):
        r = self._run(_finding(page="/x/"), {})
        self.assertEqual(r["status"], "FAIL")

    def test_baselined_high_warns_with_issue_ref(self):
        r = self._run(_finding(page="/x/"), {"/x/": [{"category": "temporal_contradiction", "issue": "#2956"}]})
        self.assertEqual(r["status"], "PASS")
        joined = " ".join(r.get("warnings", []))
        self.assertIn("#2956", joined)
        self.assertIn("BASELINED", joined)


if __name__ == "__main__":
    unittest.main()
