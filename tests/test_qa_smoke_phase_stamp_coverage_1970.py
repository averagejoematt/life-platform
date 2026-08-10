"""tests/test_qa_smoke_phase_stamp_coverage_1970.py — #1970 nightly guard.

check_coach_ensemble_phase_stamp_coverage() is the regression guard: the genesis
prereg seeder (deploy/seed_genesis_preregistration.py) used to write PREDICTION#
rows to the tagger-blind COACH# partition with no phase attribute — restart_phase_tag.py
(the reset-time tagger) only reaches USER#matthew#SOURCE#* pks, never COACH#*/
ENSEMBLE#*, and PHASE_FILTER_EXPRESSION (phase_filter.py) admits
attribute_not_exists(phase) forever — so an unstamped row on these partitions
survives every read filter and leaks into the next reset cycle.

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
    """pk -> list[Item]. query() honors the attribute_not_exists(#phase) filter
    the real check applies, and paginates via a fixed page size to prove the
    check's ExclusiveStartKey loop actually drains every page."""

    def __init__(self, items_by_pk=None, page_size=1, raise_exc=None):
        self.items_by_pk = items_by_pk or {}
        self.page_size = page_size
        self.raise_exc = raise_exc
        self.queried_pks = []

    def query(self, **kwargs):
        if self.raise_exc:
            raise self.raise_exc
        pk = kwargs["KeyConditionExpression"].get_expression()["values"][1]
        self.queried_pks.append(pk)
        unstamped = [it for it in self.items_by_pk.get(pk, []) if "phase" not in it]
        start = 0
        lek = kwargs.get("ExclusiveStartKey")
        if lek:
            start = lek["_offset"]
        page = unstamped[start : start + self.page_size]
        resp = {"Items": page}
        if start + self.page_size < len(unstamped):
            resp["LastEvaluatedKey"] = {"_offset": start + self.page_size}
        return resp


def _all_target_pks():
    return [f"COACH#{cid}" for cid in OPERATIONAL_COACH_IDS] + [
        "COACH#computation",
        "ENSEMBLE#digest",
        "ENSEMBLE#disagreements",
        "ENSEMBLE#dispute",
        "ENSEMBLE#docket",
    ]


def test_flags_a_real_unstamped_row(monkeypatch):
    pk = f"COACH#{OPERATIONAL_COACH_IDS[0]}"
    fake = _FakeTable({pk: [{"sk": "PREDICTION#pred_x"}]})
    monkeypatch.setattr(qa, "table", fake)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None  # WARN, never FAIL/throw
    assert "#1970" in c.message
    assert f"{pk}/PREDICTION#pred_x" in c.message
    assert "backfill_coach_ensemble_phase_stamps.py" in c.message


def test_passes_when_every_row_is_stamped(monkeypatch):
    pk = f"COACH#{OPERATIONAL_COACH_IDS[0]}"
    fake = _FakeTable({pk: [{"sk": "PREDICTION#pred_x", "phase": "experiment", "cycle": 12}]})
    monkeypatch.setattr(qa, "table", fake)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is True
    assert "carry a phase stamp" in c.message


def test_passes_when_no_rows_exist_at_all(monkeypatch):
    monkeypatch.setattr(qa, "table", _FakeTable({}))
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is True


def test_pagination_drains_every_page(monkeypatch):
    pk = f"COACH#{OPERATIONAL_COACH_IDS[0]}"
    items = [{"sk": f"PREDICTION#pred_{i}"} for i in range(5)]
    fake = _FakeTable({pk: items}, page_size=2)
    monkeypatch.setattr(qa, "table", fake)
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None
    for i in range(5):
        assert f"PREDICTION#pred_{i}" in c.message or "more" in c.message
    # exactly 5 unstamped rows found across the paginated queries
    assert "5 row(s)" in c.message


def test_ensemble_influence_graph_is_never_queried(monkeypatch):
    """SYSTEM_STATE static config — never phase-stamped by design, must not be
    part of the audited set (it would be a permanent false positive)."""
    fake = _FakeTable({})
    monkeypatch.setattr(qa, "table", fake)
    qa.check_coach_ensemble_phase_stamp_coverage()
    assert "ENSEMBLE#influence_graph" not in fake.queried_pks


def test_every_expected_pk_is_covered(monkeypatch):
    fake = _FakeTable({})
    monkeypatch.setattr(qa, "table", fake)
    qa.check_coach_ensemble_phase_stamp_coverage()
    assert set(fake.queried_pks) == set(_all_target_pks())


def test_fails_soft_never_throws_on_a_ddb_error(monkeypatch):
    monkeypatch.setattr(qa, "table", _FakeTable(raise_exc=RuntimeError("ddb unavailable")))
    (c,) = qa.check_coach_ensemble_phase_stamp_coverage()
    assert c.passed is None  # warn, not a crash
    assert "errored" in c.message


def test_check_is_partitioned_content_truth():
    """A data-honesty finding, not a deploy regression — must never gate ci-cd's
    fleet auto-rollback (only DEPLOY_HEALTH failures do)."""
    fake = _FakeTable({})
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
    pk = f"COACH#{OPERATIONAL_COACH_IDS[0]}"
    monkeypatch.setattr(qa, "table", _FakeTable({pk: [{"sk": s} for s in _ADR153_SKS]}))

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
    pk = f"COACH#{OPERATIONAL_COACH_IDS[0]}"
    rows = [{"sk": s} for s in _ADR153_SKS] + [{"sk": "PREDICTION#pred_x"}]
    monkeypatch.setattr(qa, "table", _FakeTable({pk: rows}))

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
    pk = f"COACH#{OPERATIONAL_COACH_IDS[0]}"
    chatty = [{"sk": f"CHAT#2026-08-10#m{i}"} for i in range(50)] + [{"sk": f"DEDUPE#{i}"} for i in range(50)]
    monkeypatch.setattr(qa, "table", _FakeTable({pk: chatty}, page_size=7))

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
