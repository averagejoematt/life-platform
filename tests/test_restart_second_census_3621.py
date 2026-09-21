"""tests/test_restart_second_census_3621.py — #3621 box 2, second half: the pre-seal
gate takes a SECOND census after the wipe.

THE WINDOW THIS CLOSES (DA-7)
─────────────────────────────
On the 2026-09-03 reset the phase tagger ran at 16:37Z and six `INSIGHT#` rows were
written at 17:09Z — thirty-two minutes after the last instrument that could have archived
them. Nothing looked twice, so nothing could tell, and the cycle's seal went on to make a
permanent public claim about a record that was still moving. A census is a snapshot; one
snapshot cannot see a writer that arrives after it.

So `deploy/prereg_truth_gate.py` (#3599's pre-seal truth contract) gains a fifth clause,
`CENSUS_FAMILY_APPEARED`: a pk family present in a census taken AFTER the wipe and absent
from the one taken before it is a blocking finding, and the reset aborts before the seal.

WHY THE CLAUSE IS OVER FAMILIES AND NOT ROWS
────────────────────────────────────────────
`deploy/restart_verify.py` already reads row-level counts and provenance. This clause is
the coarse, cheap one that the census scan can answer for free (a Scan is billed on bytes
SCANNED, not projected), and its specimen is a FAMILY appearing — the shape a writer that
nothing registered produces. Two implementations of one rule is how a comparison gate
goes blind; this file asserts the delegation rather than re-deriving.

THE MUTATION CONTROLS
─────────────────────
Three, each the plausible softening of the clause:
  * the delta computed in the wrong direction (before − after), which reports nothing for
    an appearing family and is silently green forever;
  * the empty-census refusals removed, which turns "the scan failed" into "nothing
    appeared" — the vacuous pass this whole box exists to end;
  * the findings marked non-blocking, which keeps the report and drops the abort.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "lambdas"), str(REPO_ROOT / "deploy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

_spec = importlib.util.spec_from_file_location("prereg_truth_gate", REPO_ROOT / "deploy" / "prereg_truth_gate.py")
gate = importlib.util.module_from_spec(_spec)
sys.modules["prereg_truth_gate"] = gate
_spec.loader.exec_module(gate)

from experiment import pk_census  # noqa: E402

#: A census in the shape `pk_census.family_census` returns. Families and representatives
#: are REAL ones from the committed live census artifact (see the test below that pins
#: them against it) — a synthetic family name would let the clause pass over a shape the
#: live table never produces.
BEFORE = {
    "SOURCE#insights": ("USER#matthew#SOURCE#insights", "INSIGHT#2026-02-23T02:13:57"),
    "SOURCE#chronicle": ("USER#matthew#SOURCE#chronicle", "DATE#2026-05-18"),
    "COACH": ("COACH#physical_coach", "BRIEF#2026-09-14"),
    "NARRATIVE": ("NARRATIVE#arc", "STATE#current"),
}


def _after_with_new_family():
    after = dict(BEFORE)
    after["SOURCE#recap_cards"] = ("USER#matthew#SOURCE#recap_cards", "DATE#2026-09-20")
    return after


# ─────────────────────────────────────────────────────────────────────────────
# the clause
# ─────────────────────────────────────────────────────────────────────────────


def test_an_appearing_family_is_a_blocking_finding():
    findings = gate.audit_census_delta(BEFORE, _after_with_new_family())
    assert len(findings) == 1
    (f,) = findings
    assert f.kind == gate.CENSUS_FAMILY_APPEARED
    assert f.blocking is True
    assert "SOURCE#recap_cards" in f.where
    assert "DATE#2026-09-20" in f.detail, "the finding must name the representative row, or nobody can go look at it"


def test_an_unchanged_census_produces_nothing():
    assert gate.audit_census_delta(BEFORE, dict(BEFORE)) == []


def test_several_appearing_families_are_each_reported_by_name():
    after = _after_with_new_family()
    after["LEDGER"] = ("LEDGER#weekly", "WEEK#2026-W38")
    findings = gate.audit_census_delta(BEFORE, after)
    assert sorted(f.where for f in findings) == ["census.LEDGER", "census.SOURCE#recap_cards"]


def test_a_family_that_vanished_is_deliberately_not_a_finding_here():
    """The wipe tombstones, it never deletes (Interpretation B), so a family present
    before and absent after is a different instrument's question — restart_verify's
    row-level census. Asserted so the omission is a decision on the record, not a gap."""
    shrunk = {k: v for k, v in BEFORE.items() if k != "NARRATIVE"}
    assert gate.audit_census_delta(BEFORE, shrunk) == []


def test_the_new_kind_is_declared_separately_from_the_artifact_kinds():
    """`FINDING_KINDS` is the set an ARTIFACT can reach, and #3599's own guard-the-set
    control asserts the live seal reaches every one of them. A clause that grades the
    TABLE cannot be reached by any artifact, so folding it in would have broken that
    control silently — the census kind gets its own declared set instead."""
    assert gate.CENSUS_FAMILY_APPEARED in gate.CENSUS_FINDING_KINDS
    assert gate.CENSUS_FAMILY_APPEARED not in gate.FINDING_KINDS
    assert set(gate.ALL_FINDING_KINDS) == set(gate.FINDING_KINDS) | set(gate.CENSUS_FINDING_KINDS)
    assert len(set(gate.ALL_FINDING_KINDS)) == len(gate.ALL_FINDING_KINDS)


def test_the_report_states_both_counts_and_every_offender():
    findings = gate.audit_census_delta(BEFORE, _after_with_new_family())
    text = gate.render_census_delta(findings, BEFORE, _after_with_new_family())
    assert "families before : 4" in text
    assert "families after  : 5" in text
    assert "SOURCE#recap_cards" in text


# ─────────────────────────────────────────────────────────────────────────────
# the vacuity refusals
# ─────────────────────────────────────────────────────────────────────────────


def test_an_empty_first_census_raises_rather_than_reporting_everything_new():
    with pytest.raises(ValueError, match="FIRST census is empty"):
        gate.audit_census_delta({}, BEFORE)


def test_an_empty_second_census_raises_rather_than_reading_as_clean():
    with pytest.raises(ValueError, match="SECOND census is empty"):
        gate.audit_census_delta(BEFORE, {})


def test_the_credentialed_wrapper_refuses_an_empty_scan_from_the_scanner_itself():
    """Belt and braces: `family_census` raises on an empty scan too, so the refusal does
    not depend on which of the two layers a future caller reaches first."""

    class EmptyTable:
        def scan(self, **_kw):
            return {"Items": []}

    with pytest.raises(pk_census.CensusPreflightError):
        pk_census.family_census(EmptyTable())


# ─────────────────────────────────────────────────────────────────────────────
# the wrapper, and the one derivation
# ─────────────────────────────────────────────────────────────────────────────


class _FakeTable:
    def __init__(self, items, page=3):
        self.items, self.page, self.scans = items, page, 0

    def scan(self, **kwargs):
        self.scans += 1
        start = kwargs.get("ExclusiveStartKey")
        i = 0 if start is None else next(n for n, it in enumerate(self.items) if it["pk"] == start["pk"] and it["sk"] == start["sk"]) + 1
        page = self.items[i : i + self.page]
        resp = {"Items": page}
        if i + self.page < len(self.items):
            resp["LastEvaluatedKey"] = {"pk": page[-1]["pk"], "sk": page[-1]["sk"]}
        return resp


def _rows(census):
    return [{"pk": pk, "sk": sk} for pk, sk in census.values()]


def test_the_wrapper_takes_the_second_census_and_returns_the_blocking_findings():
    table = _FakeTable(_rows(_after_with_new_family()))
    out = []
    findings = gate.run_second_census_gate(BEFORE, table=table, printer=out.append)
    assert [f.kind for f in findings] == [gate.CENSUS_FAMILY_APPEARED]
    assert table.scans >= 2, "the fake pages at 3 — a single scan call means pagination was not exercised"
    assert "appeared        : 1" in out[0]


def test_the_wrapper_is_clean_when_nothing_appeared():
    table = _FakeTable(_rows(BEFORE))
    assert gate.run_second_census_gate(BEFORE, table=table, printer=lambda _s: None) == []


def test_the_wrapper_delegates_the_enumeration_rather_than_re_deriving_it():
    """One derivation, two verdicts. A second scanner written beside `family_census` is
    how the before and after halves come to disagree about what a family is."""
    src = (REPO_ROOT / "deploy" / "prereg_truth_gate.py").read_text(encoding="utf-8")
    assert "from experiment.pk_census import family_census" in src
    assert "def scan_" not in src and "ProjectionExpression" not in src, "the gate must not grow a scanner of its own"


def test_the_baseline_is_captured_only_after_the_totality_preflight_passes():
    """Order is the decision: a BEFORE census built from a table the totality gate is
    about to reject is a baseline nobody can interpret. The preflight runs first and the
    baseline is captured after it, which costs one extra pk+sk Scan (~$0.001) on purpose."""
    src = (REPO_ROOT / "deploy" / "restart_pipeline.py").read_text(encoding="utf-8")
    assert "first_census = family_census()" in src
    assert src.index("fam_count = run_census_preflight()") < src.index("first_census = family_census()")


def test_the_pipeline_hard_fails_the_reset_on_an_appeared_family():
    """Source-level, like the sibling seal-path assertions in #3511/#3599: the wrapper is
    called after the wipe and its non-empty verdict exits non-zero."""
    src = (REPO_ROOT / "deploy" / "restart_pipeline.py").read_text(encoding="utf-8")
    assert "run_second_census_gate(first_census" in src
    after_call = src.split("run_second_census_gate(first_census", 1)[1][:600]
    assert "sys.exit(6)" in after_call, "an appeared family must ABORT, not print"
    assert 'name == "restart_intelligence_wipe"' in src


def test_a_skipped_first_census_says_so_instead_of_passing_silently():
    src = (REPO_ROOT / "deploy" / "restart_pipeline.py").read_text(encoding="utf-8")
    assert "the #3621 second census after the wipe is skipped too" in src


def test_the_families_used_here_are_real_ones_from_the_committed_live_census():
    """Fixture-must-be-the-wire: every family name above is one the live table actually
    produces (the committed census artifact is the measured list), so the clause is not
    proved over a shape that cannot occur."""
    import json

    artifact = REPO_ROOT / "deploy" / "generated" / "pk_family_census.json"
    if not artifact.exists():  # pragma: no cover - the artifact is committed
        pytest.skip("pk_family_census.json not committed")
    live = set(json.loads(artifact.read_text(encoding="utf-8"))["families"])
    assert set(BEFORE) <= live, f"synthetic families not in the live census: {sorted(set(BEFORE) - live)}"
    assert "SOURCE#recap_cards" in live, "the appearing-family specimen should be a real family too (#3860's own)"


# ─────────────────────────────────────────────────────────────────────────────
# mutation controls — soften the clause, these must RED
# ─────────────────────────────────────────────────────────────────────────────


def test_mutation_control_the_delta_computed_backwards_goes_silent():
    before, after = BEFORE, _after_with_new_family()
    backwards = sorted(set(before) - set(after))
    assert not backwards, "MUTATION CONTROL FAILED: the reversed delta also reports the appearing family"
    assert sorted(set(after) - set(before)) == ["SOURCE#recap_cards"]


def test_mutation_control_dropping_the_empty_census_refusal_turns_a_failed_scan_into_a_pass():
    """Without the refusal, `set(after) - set(before)` over an empty `after` is the empty
    set — a scan that returned nothing reads as 'no family appeared'."""
    assert sorted(set({}) - set(BEFORE)) == [], "the softened predicate must be shown to be silent"
    with pytest.raises(ValueError):
        gate.audit_census_delta(BEFORE, {})


def test_mutation_control_non_blocking_findings_would_be_dropped_by_the_wrapper():
    """`run_second_census_gate` returns `blocking(...)`. A finding minted with
    `blocking=False` disappears from the verdict while still printing — the report stays,
    the abort goes. Watched here so `blocking=True` in the clause is load-bearing."""
    soft = gate.Finding(gate.CENSUS_FAMILY_APPEARED, "census.X", "…", blocking=False)
    assert gate.blocking([soft]) == []
    assert all(f.blocking for f in gate.audit_census_delta(BEFORE, _after_with_new_family()))
