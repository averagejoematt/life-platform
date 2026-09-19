"""tests/test_qa_smoke_phase_stamp_coverage_1970.py — #1970 nightly guard.

check_coach_ensemble_phase_stamp_coverage() is the regression guard: the genesis
prereg seeder (deploy/seed_genesis_preregistration.py) used to write PREDICTION#
rows to the tagger-blind COACH# partition with no phase attribute — restart_phase_tag.py
(the reset-time tagger) only reaches USER#matthew#SOURCE#* pks, never COACH#*/
ENSEMBLE#*, and PHASE_FILTER_EXPRESSION (phase_filter.py) admits
attribute_not_exists(phase) forever — so an unstamped row on these partitions
survives every read filter and leaks into the next reset cycle.

#3599 box 2: the check no longer walks a hand list of COACH#/ENSEMBLE# pks — it
enumerates ROWS through one provenance scan (`experiment.pk_census.scoped_stamp_audit`)
and asks the taxonomy per row, so every EXPERIMENT_SCOPED family is audited and
`USER#matthew#SOURCE#insights` (#3513) is inside the Set. The fakes here answer scan().

Proves the guard actually FIRES on an unstamped row and stays clean when every
row carries its stamp — a check that could never turn red would not satisfy
either half of this file. Also proves it is wired into the nightly run and that
it WARNs (never FAILs/throws) so a currently-known gap can't red the pipeline
before the operator backfill (deploy/backfill_coach_ensemble_phase_stamps.py) lands.
"""

import os
import sys

# qa_smoke_lambda reads these at import time (conftest supplies fake AWS creds).
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
os.environ.setdefault("EMAIL_SENDER", "qa@example.com")

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

import qa_smoke_lambda as qa  # noqa: E402
from coach.persona_registry import OPERATIONAL_COACH_IDS  # noqa: E402


class _FakeTable:
    """A list of items. scan() honours the check's ProjectionExpression only in the sense
    that it returns what the fixture holds, and paginates via a fixed page size to prove
    the check's ExclusiveStartKey loop actually drains every page.

    #3599: this used to be a pk -> items map answering query(). The check now enumerates
    ROWS through one provenance scan (`experiment.pk_census.scan_provenance_pages`), so
    every fixture row carries its own pk and the fake answers scan()."""

    def __init__(self, items=None, page_size=1, raise_exc=None):
        self.items = list(items or [])
        self.page_size = page_size
        self.raise_exc = raise_exc
        self.scans = 0

    def scan(self, **kwargs):
        if self.raise_exc:
            raise self.raise_exc
        self.scans += 1
        start = (kwargs.get("ExclusiveStartKey") or {}).get("_offset", 0)
        page = self.items[start : start + self.page_size]
        resp = {"Items": page}
        if start + self.page_size < len(self.items):
            resp["LastEvaluatedKey"] = {"_offset": start + self.page_size}
        return resp


def _rows(pk, sks, **attrs):
    return [{"pk": pk, "sk": sk, **attrs} for sk in sks]


_COACH_PK = f"COACH#{OPERATIONAL_COACH_IDS[0]}"


def test_flags_a_real_unstamped_row(monkeypatch):
    fake = _FakeTable(_rows(_COACH_PK, ["PREDICTION#pred_x"]))
    monkeypatch.setattr(qa, "table", fake)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None  # WARN, never FAIL/throw
    assert "#1970" in c.message
    assert f"{_COACH_PK}/PREDICTION#pred_x" in c.message
    assert "backfill_coach_ensemble_phase_stamps.py" in c.message


def test_passes_when_every_row_is_stamped(monkeypatch):
    fake = _FakeTable(_rows(_COACH_PK, ["PREDICTION#pred_x"], phase="experiment", cycle=12))
    monkeypatch.setattr(qa, "table", fake)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is True
    assert "carry a phase stamp" in c.message


def test_an_empty_scan_is_an_errored_warn_never_a_pass(monkeypatch):
    """The vacuous-scan trap (#3860): a scan that returns nothing cannot certify that every
    row is stamped. This used to pass; it now lands in the ALARMED errored branch."""
    monkeypatch.setattr(qa, "table", _FakeTable([]))
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None
    assert c.chronic is False
    assert "errored" in c.message and "ZERO rows" in c.message


def test_pagination_drains_every_page(monkeypatch):
    fake = _FakeTable(_rows(_COACH_PK, [f"PREDICTION#pred_{i}" for i in range(5)]), page_size=2)
    monkeypatch.setattr(qa, "table", fake)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None
    assert fake.scans == 3  # 2 + 2 + 1
    assert "5 row(s)" in c.message  # exactly 5 unstamped rows found across the paginated scan


def test_ensemble_influence_graph_is_never_a_finding(monkeypatch):
    """SYSTEM_STATE static config — never phase-stamped by design. It used to be kept out
    of the audited pk list by hand; now the row is scanned like every other and the
    TAXONOMY excludes it (it would otherwise be a permanent false positive)."""
    fake = _FakeTable(_rows("ENSEMBLE#influence_graph", ["GRAPH#current"]))
    monkeypatch.setattr(qa, "table", fake)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is True
    assert "influence_graph" not in c.message


def test_every_experiment_scoped_source_family_is_audited(monkeypatch):
    """Guard the SET (#3599 box 2): the audited families are DERIVED from the taxonomy's
    own registry, so an unstamped row on ANY EXPERIMENT_SCOPED source — insights (#3513)
    included — is a finding, and the member count in the message is the registry's size."""
    from experiment.phase_taxonomy import EXPERIMENT_SCOPED, SOURCE_CLASS

    scoped_sources = sorted(s for s, cls in SOURCE_CLASS.items() if cls == EXPERIMENT_SCOPED)
    assert "insights" in scoped_sources
    rows = [{"pk": f"USER#matthew#SOURCE#{src}", "sk": "X#1"} for src in scoped_sources]
    monkeypatch.setattr(qa, "table", _FakeTable(rows, page_size=7))
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None
    assert f"{len(rows)} row(s) across {len(rows)} of {len(rows)} EXPERIMENT_SCOPED pk families" in c.message
    assert "SOURCE#insights" in c.message


def test_a_cross_phase_source_family_is_not_a_finding(monkeypatch):
    """The inverse of the test above, so the derivation is shown to DISCRIMINATE rather
    than to flag every unstamped row it meets: an unstamped row on a CROSS_PHASE or
    SYSTEM_STATE source is the correct state."""
    from experiment.phase_taxonomy import CROSS_PHASE_SOURCES, SYSTEM_STATE_SOURCES

    rows = [{"pk": f"USER#matthew#SOURCE#{src}", "sk": "X#1"} for src in (CROSS_PHASE_SOURCES[0], SYSTEM_STATE_SOURCES[0])]
    monkeypatch.setattr(qa, "table", _FakeTable(rows))
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is True


def test_fails_soft_never_throws_on_a_ddb_error(monkeypatch):
    monkeypatch.setattr(qa, "table", _FakeTable(raise_exc=RuntimeError("ddb unavailable")))
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None  # warn, not a crash
    assert "errored" in c.message


def test_check_is_partitioned_content_truth():
    """A data-honesty finding, not a deploy regression — must never gate ci-cd's
    fleet auto-rollback (only DEPLOY_HEALTH failures do)."""
    fake = _FakeTable(_rows(_COACH_PK, ["PREDICTION#p"], phase="experiment"))
    import qa_smoke_lambda as qa2

    orig_table = qa2.table
    qa2.table = fake
    try:
        (c,) = qa2.check_coach_ensemble_phase_stamp_coverage()
    finally:
        qa2.table = orig_table
    assert c.partition == qa.CONTENT_TRUTH


def test_wired_into_lambda_handler():
    """The check must actually run nightly (#2307: via qa.check_steps(), the one
    wiring point the handler loops over)."""
    assert ("phase_stamp_coverage", qa.check_coach_ensemble_phase_stamp_coverage) in qa.check_steps()


def test_the_check_reaches_its_verdict_through_the_shared_row_audit():
    """#3860's shape (tests/test_pk_census_one_home_3860.py): the check must DELEGATE to
    `experiment.pk_census.scoped_stamp_audit` over the docstring-stripped body, not
    re-derive a classify loop beside it. A caller that imports the helper and then loops
    itself is the same drift with an import in front."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(qa.check_coach_ensemble_phase_stamp_coverage))
    fn = tree.body[0]
    fn.body = fn.body[1:] if isinstance(fn.body[0], ast.Expr) else fn.body  # strip the docstring
    called = {
        n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, "id", None) for n in ast.walk(fn) if isinstance(n, ast.Call)
    }
    assert "scoped_stamp_audit" in called and "scan_provenance_pages" in called
    assert "classify" not in called and "should_phase_stamp" not in called, "the check re-derives the class loop beside the shared audit"


# ─────────────────────────────────────────────────────────────────────────────
# #2520: the audit must agree with the taxonomy.
#
# The tests above were written when every unstamped row on these partitions really
# was a gap. ADR-153 put the texting relationship (CROSS_PHASE CHAT#/CHAT#summary#/
# RELATIONSHIP#) and Telegram DEDUPE# rows (SYSTEM_STATE) on the same COACH#<id>
# partitions, where unstamped is the CORRECT state. Counting those made the finding
# grow with every text Matthew sent a coach — it could never reach zero (#2379
# saturation) — and had the check tell the operator to run a backfill that would have
# marked his whole conversation history for deletion at the next reset.
# ─────────────────────────────────────────────────────────────────────────────

_ADR153_SKS = ["CHAT#2026-08-10#m1", "CHAT#summary#2026-08-10", "RELATIONSHIP#state", "DEDUPE#4711"]


def test_unstamped_cross_phase_and_system_state_rows_are_not_a_finding(monkeypatch):
    """MUTATION PROOF direction 1: a seeded cross-phase row leaves the check silent."""
    monkeypatch.setattr(qa, "table", _FakeTable(_rows(_COACH_PK, _ADR153_SKS)))

    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()

    assert c.passed is True  # not a finding
    assert "--apply" not in c.message  # AC3: no remediation when nothing is safe to repair
    assert "backfill_coach_ensemble_phase_stamps" not in c.message
    for s in _ADR153_SKS:
        assert s not in c.message
    # Excluded, but visibly excluded — not silently dropped.
    assert "4 cross-phase/system-state row(s) are correctly unstamped" in c.message


def test_a_genuine_scoped_gap_is_still_counted_next_to_protected_rows(monkeypatch):
    """MUTATION PROOF direction 2: an unstamped experiment-scoped row must STILL be
    a finding, and still carry the remediation — a fix that merely silenced the check
    would pass direction 1 on its own."""
    pk = _COACH_PK
    monkeypatch.setattr(qa, "table", _FakeTable(_rows(pk, _ADR153_SKS + ["PREDICTION#pred_x"])))

    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()

    assert c.passed is None  # WARN
    assert "1 row(s)" in c.message  # the PREDICTION# row only — the 4 protected rows are not counted
    assert f"{pk}/PREDICTION#pred_x" in c.message
    assert "deploy/backfill_coach_ensemble_phase_stamps.py --apply" in c.message
    for s in _ADR153_SKS:
        assert s not in c.message  # never named as a gap the operator should stamp


def test_the_finding_no_longer_grows_every_time_matthew_texts_a_coach(monkeypatch):
    """The #2379 saturation property: chat volume must not move this check at all.
    50 more conversation turns, still zero findings."""
    chatty = _rows(_COACH_PK, [f"CHAT#2026-08-10#m{i}" for i in range(50)] + [f"DEDUPE#{i}" for i in range(50)])
    monkeypatch.setattr(qa, "table", _FakeTable(chatty, page_size=7))

    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()

    assert c.passed is True
    assert "100 cross-phase/system-state row(s) are correctly unstamped" in c.message


def test_the_audit_and_the_backfill_ask_the_taxonomy_the_same_question():
    """The audit's job is to predict what the backfill would do. Both now route
    through phase_taxonomy.should_phase_stamp(), so they cannot disagree — the
    #1970 pair drifted apart precisely because each restated the rule itself."""
    import importlib.util
    from pathlib import Path

    from experiment.phase_taxonomy import should_phase_stamp

    repo_root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("_bf2520", repo_root / "deploy/backfill_coach_ensemble_phase_stamps.py")
    bf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bf)

    pk = f"COACH#{OPERATIONAL_COACH_IDS[0]}"
    for sk in _ADR153_SKS + ["PREDICTION#pred_x", "BRIEF#2026-08-01", "STANCE#latest"]:
        stampable, _ = bf.split_by_class(pk, [{"sk": sk}])
        assert bool(stampable) is should_phase_stamp(pk, sk), sk
