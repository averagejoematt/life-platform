"""#3399 — the judge labelled a self-withdrawn finding `basis: "impossibility"` and it gated.

THE OBSERVED FAILURE (run 33451827346, "Visual QA (standalone)", captured
2026-08-31 PT — the cycle-15 pre-start eve; genesis 2026-09-01).
/method/voicefidelity/ FAILed the live reader-truth sweep on a high
temporal_contradiction whose own note narrates a re-check and ends
"…This is correctly framed as historical. Withdrawing this finding." — with
`basis: "impossibility"`, exactly what the old footer forbade in prose. Across
all 35 findings in that run, `basis: "withdrawn"` was emitted ZERO times: the
structured channel #3337 built was populated and WRONG, which is worse than
absent (#3399's charge).

THE MECHANISM, and why the fix is field ORDER rather than a phrase or a clause:
the old response schema put `basis` BEFORE `note`. Generation is autoregressive,
so the judge had committed its basis tokens before writing one word of the note —
a retraction it reasons its way to MID-NOTE had no structured place left to land.
The old footer's closing instruction ("do not drop a retraction into the prose…")
was a prose clause, and prose clauses measure 3-of-3 / 25-of-60 ignored
(#2613/#2741). #3399 moves `basis` to the END of each finding, after the note,
so `basis: "withdrawn"` becomes the judge's own POST-NOTE structured withdrawal
marker. Nothing new reads the prose: `_WITHDRAWAL_RE` is untouched (still a
logged tiebreak that cannot decide alone — the #2959→#3379 family bar), and the
enforcement point for a first-pass mislabel is the #2741/#3102 confirm pass,
which re-judges every would-gate high under the same (now post-note) contract.

WHAT THIS FILE HOLDS.

  1. THE CONTRACT GUARD (negative control against reversion) — `basis` sits
     after `note` in the schema and "withdrawn" stays in the enum. This test
     FAILED against the pre-#3399 footer (run during development — the must-fail
     case demonstrably fails; a vacuous negative control equals a passing one).
  2. THE REACHABILITY CONTROL + ITS NON-VACUITY TWIN — the wire voicefidelity
     finding with the post-note marker filled is DROPPED by the real pipeline at
     any severity, clock or no clock; the byte-identical finding with the wire's
     own `basis: "impossibility"` survives at high. The ONLY difference is the
     marker, so the control cannot pass vacuously.
  3. THE WIRE REPLAY CENSUS — all 35 recorded findings replayed verbatim through
     the real `assess_prose` under the recorded frame reproduce the recorded run
     exactly (35 out, 19 highs, ruling-for-ruling parity). This pins the
     positive controls: the genuine impossibilities in that run still gate, and
     the first pass still does NOT read the withdrawal out of the prose (that
     would be the phrase list this issue refuses to extend).
  4. THE GATE REGRESSION, both surfaces — the CI gate that failed
     (`visual_ai_qa._confirm_new_truth_highs`) and its nightly sibling
     (`qa_check_reader_truth._confirm_high_findings`): a would-gate high whose
     confirm-pass re-judge records the withdrawal in the post-note marker is
     demoted (never gates, never silently dropped); the named positive control
     (/coaching/team/'s "launched on September 1st" high, from the same run)
     re-judged with `basis: "impossibility"` still gates.

FIXTURE PROVENANCE — the wire, not a paraphrase:
`tests/fixtures/reader_truth_run_33451827346_findings.json` is extracted verbatim
from the run's own artifact (`visual-qa-standalone-screenshots/report.json`,
`results[*].truth_findings`). The voicefidelity note is 922 chars and ends
"Withdrawing this finding." — both asserted below so the fixture cannot drift.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _TESTS_DIR not in sys.path:
    sys.path.insert(0, _TESTS_DIR)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lambdas"))

import visual_ai_qa  # noqa: E402
from operational import (
    qa_check_reader_truth,  # noqa: E402
    reader_truth_qa as rtq,  # noqa: E402
)

_FIXTURE = Path(__file__).parent / "fixtures" / "reader_truth_run_33451827346_findings.json"

# The RECORDED frame (see the fixture's _provenance): the sweep captured on the
# pre-start eve of cycle 15 — genesis 2026-09-01, capture_today_pt 2026-08-31.
# Replayed pinned, never from the live constant: the 2026-09-01 re-anchor proved
# a wire corpus breaks at every reset when it rides wall-clock constants
# (test_reader_truth_structural_rulings_3337.py learned this first).
_RECORDED_GENESIS = "2026-09-01"
_RECORDED_TODAY = "2026-08-31"

_WIRE = json.loads(_FIXTURE.read_text(encoding="utf-8"))
_VOICEFIDELITY = next(f for f in _WIRE["findings"] if f["page"] == "/method/voicefidelity/")
# The named positive control from the same run: a genuine pre-start impossibility
# ("The experiment launched on September 1st …" narrated on 2026-08-31).
_POSITIVE_CONTROL = next(f for f in _WIRE["findings"] if f["page"] == "/coaching/team/" and f["severity"] == "high")


def _reply(findings):
    """A bedrock_client.invoke-shaped stub returning `findings` as the judge's verdict."""
    text = json.dumps({"findings": findings, "severity": "high", "summary": "replay"})

    def invoke(body, model_name=None):
        return {"content": [{"type": "text", "text": text}]}

    return invoke


def _model_finding(f, **overrides):
    """The judge's raw JSON for a recorded finding — the model emits page/category/
    severity/note/basis only; `rulings` is written by the assessment loop and is
    stripped here so the replay enters the pipeline exactly where the wire did."""
    raw = {k: f[k] for k in ("page", "category", "severity", "note", "basis") if k in f}
    raw.update(overrides)
    return raw


class _RecordedFrame(unittest.TestCase):
    """Pin the phase anchors and the SSM cycle probe to the recorded run's frame."""

    def setUp(self):
        patches = [
            mock.patch("common.constants.EXPERIMENT_START_DATE", _RECORDED_GENESIS),
            mock.patch.dict(rtq._cycle_probe, {"done": True, "value": None}),
            # The nightly confirm pass (#2741) computes its phase at wall-clock
            # pacific_today(); pin it so the whole class replays in the recorded frame.
            mock.patch("common.pacific_time.pacific_today", lambda: _RECORDED_TODAY),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def _assess(self, raw_findings, pages=None):
        pages = pages or sorted({f["page"] for f in raw_findings})
        surfaces = [{"name": p, "path": p, "prose": "wire replay"} for p in pages]
        out, errs = rtq.assess_prose(surfaces, _reply(raw_findings), today_iso=_RECORDED_TODAY, batch_size=max(1, len(surfaces)))
        assert errs == [], errs
        return out


# ── 1. the contract guard: basis is a POST-NOTE field and "withdrawn" survives ─


class TestResponseContract(unittest.TestCase):
    def test_basis_is_emitted_after_the_note(self):
        """The structural fix itself. Autoregressive generation commits fields in
        schema order, so a pre-note `basis` cannot record a retraction the note
        reasons its way to — run 33451827346's measured result (0/35 withdrawn,
        the one genuine withdrawal labelled impossibility at high). Reverting the
        order re-opens exactly that hole, so the order IS the regression test.
        (This test FAILED against the pre-#3399 footer — verified in development.)
        """
        schema = rtq._PROMPT_FOOTER.split("Set top-level")[0]
        self.assertIn('"note"', schema)
        self.assertIn('"basis"', schema)
        self.assertLess(
            schema.index('"note"'),
            schema.index('"basis"'),
            "`basis` must come AFTER `note` in the finding schema — a pre-note basis is "
            "committed before the note's own re-check can reach it (#3399)",
        )

    def test_withdrawn_stays_in_the_enum_and_the_footer(self):
        """`withdrawn` unreachable == the #3399 failure re-armed. Guard the SET:
        every enum value the code honours must be offered to the judge, so the
        contract and `_normalize_finding` cannot drift apart."""
        self.assertIn("withdrawn", rtq.JUDGE_BASIS_VALUES)
        for value in rtq.JUDGE_BASIS_VALUES:
            self.assertIn(f'"{value}"', rtq._PROMPT_FOOTER, f"enum value {value!r} missing from the response contract")

    def test_the_prompt_carries_the_contract(self):
        """build_prompt must actually ship the footer (the contract is not a comment)."""
        prompt = rtq.build_prompt(
            [{"name": "Home", "path": "/", "prose": "hello"}],
            rtq.phase_context(_RECORDED_TODAY),
        )
        schema = prompt.split("Set top-level")[0]
        self.assertLess(schema.rindex('"note"'), schema.rindex('"basis"'))


# ── 2. reachability + the non-vacuity twin ─────────────────────────────────────


class TestWithdrawnMarkerReachability(_RecordedFrame):
    def test_the_wire_note_with_the_marker_filled_is_dropped(self):
        """The regression, at the pipeline level: the REAL voicefidelity note with
        the post-note marker recording what its own last sentence says is dropped
        by `is_self_refuted` channel 1 — a field decision, no phrase anywhere.
        Channel 1 is deliberately clock-free, so this holds even in the recorded
        pre-start frame where every clock-gated ruling was dead."""
        out = self._assess([_model_finding(_VOICEFIDELITY, basis="withdrawn")])
        self.assertEqual(out, [], "a basis:withdrawn finding must be dropped at any severity")

    def test_the_twin_without_the_marker_still_survives_at_high(self):
        """NON-VACUITY: the byte-identical finding carrying the wire's own
        mislabel (`basis: "impossibility"`) survives the first pass at high. The
        ONLY difference from the test above is the marker — so if the drop ever
        keys on anything else (severity, the note's prose, the page), one of the
        pair reds. This also pins the design decision NOT to read the withdrawal
        out of the prose: that would be the fifth phrase-matched member of the
        #2959/#3003/#3199/#3379 family, and this issue refuses it."""
        out = self._assess([_model_finding(_VOICEFIDELITY)])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["severity"], "high")
        self.assertEqual(out[0]["page"], "/method/voicefidelity/")

    def test_fixture_is_the_wire(self):
        """The fixture cannot drift: the note is the 922-char record whose final
        sentence is the withdrawal, and the recorded run emitted basis:withdrawn
        exactly zero times (the issue's own census, re-derived not remembered)."""
        self.assertEqual(len(_VOICEFIDELITY["note"]), 922)
        self.assertTrue(_VOICEFIDELITY["note"].rstrip().endswith("Withdrawing this finding."))
        self.assertEqual(_VOICEFIDELITY["basis"], "impossibility")
        self.assertEqual(_VOICEFIDELITY["severity"], "high")
        self.assertEqual(len(_WIRE["findings"]), 35)
        self.assertEqual(sum(1 for f in _WIRE["findings"] if f.get("basis") == "withdrawn"), 0)


# ── 3. the 35-finding replay census: positive controls preserved ───────────────


class TestWireRunReplay(_RecordedFrame):
    def test_replay_reproduces_the_recorded_run(self):
        """Acceptance measurement, run against the recorded 35: nothing about
        #3399 touches the first-pass disposition of ANY recorded finding — the
        19 genuine highs (the positive controls) still emerge as highs, and every
        recorded ruling fires identically. The voicefidelity finding also still
        emerges high from the FIRST pass (no prose is read); its de-gating is the
        confirm pass honouring the post-note marker, tested below."""
        raw = [_model_finding(f) for f in _WIRE["findings"]]
        out = self._assess(raw)
        self.assertEqual(len(out), 35)
        highs = [f for f in out if f["severity"] == "high"]
        self.assertEqual(len(highs), 19)
        self.assertIn("/method/voicefidelity/", [f["page"] for f in highs])
        self.assertIn("/coaching/team/", [f["page"] for f in highs])
        recorded = {(f["page"], f["category"], f["note"]): tuple(f.get("rulings") or ()) for f in _WIRE["findings"]}
        replayed = {(f["page"], f["category"], f["note"]): tuple(f.get("rulings") or ()) for f in out}
        self.assertEqual(recorded, replayed, "ruling-for-ruling parity with the recorded run")


# ── 4. the gate regression: both confirm passes honour the post-note marker ────


class TestConfirmPassHonoursTheMarker(_RecordedFrame):
    """The enforcement point for a first-pass mislabel. Both gates already
    re-judge every would-gate high (#3102 CI, #2741 nightly) through the REAL
    `assess_prose` — so a re-judge that records its withdrawal in the post-note
    marker is dropped inside the second pass, the high does not reproduce, and
    the gate demotes it visibly. No confirm-side code changed for #3399; these
    tests hold the chain (marker → drop → unconfirmed) end-to-end so no link can
    be removed silently."""

    def test_ci_gate_demotes_the_wire_high_when_the_rejudge_withdraws(self):
        wire_high = dict(_VOICEFIDELITY)
        surfaces = {"/method/voicefidelity/": {"name": "x", "path": "/method/voicefidelity/", "prose": "wire replay"}}
        confirmed, unconfirmed, note = visual_ai_qa._confirm_new_truth_highs(
            [wire_high],
            surfaces,
            _reply([_model_finding(_VOICEFIDELITY, basis="withdrawn")]),
            today_iso=_RECORDED_TODAY,
        )
        self.assertEqual(confirmed, [])
        self.assertEqual(unconfirmed, [wire_high])
        self.assertIsNotNone(note)
        self.assertIn("NOT reproduce", note)

    def test_ci_gate_positive_control_still_gates(self):
        """The named positive control (#3399 acceptance): /coaching/team/'s
        "launched on September 1st" high from the same run, re-judged with
        `basis: "impossibility"` again, is confirmed and gates. Identical
        plumbing to the test above — only the marker differs."""
        wire_high = dict(_POSITIVE_CONTROL)
        surfaces = {"/coaching/team/": {"name": "x", "path": "/coaching/team/", "prose": "wire replay"}}
        confirmed, unconfirmed, note = visual_ai_qa._confirm_new_truth_highs(
            [wire_high],
            surfaces,
            _reply([_model_finding(_POSITIVE_CONTROL)]),
            today_iso=_RECORDED_TODAY,
        )
        self.assertEqual(confirmed, [wire_high])
        self.assertEqual(unconfirmed, [])

    def test_nightly_gate_demotes_when_the_rejudge_withdraws(self):
        """The #2741 sibling (qa_check_reader_truth) — same chain, the nightly's
        own confirm entry point, with only the LLM transport stubbed."""
        from ai import bedrock_client

        wire_high = dict(_VOICEFIDELITY)
        surfaces = [{"name": "x", "path": "/method/voicefidelity/", "prose": "wire replay"}]
        with mock.patch.object(bedrock_client, "invoke", _reply([_model_finding(_VOICEFIDELITY, basis="withdrawn")])):
            confirmed, unconfirmed, note = qa_check_reader_truth._confirm_high_findings([wire_high], surfaces)
        self.assertEqual(confirmed, [])
        self.assertEqual(unconfirmed, [wire_high])
        self.assertIn("did not reproduce", note)

    def test_nightly_gate_positive_control_still_gates(self):
        from ai import bedrock_client

        wire_high = dict(_POSITIVE_CONTROL)
        surfaces = [{"name": "x", "path": "/coaching/team/", "prose": "wire replay"}]
        with mock.patch.object(bedrock_client, "invoke", _reply([_model_finding(_POSITIVE_CONTROL)])):
            confirmed, unconfirmed, note = qa_check_reader_truth._confirm_high_findings([wire_high], surfaces)
        self.assertEqual(confirmed, [wire_high])
        self.assertEqual(unconfirmed, [])


if __name__ == "__main__":
    unittest.main()
