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
    """The check must actually run nightly."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(qa.lambda_handler))
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "check_coach_ensemble_phase_stamp_coverage" in calls
