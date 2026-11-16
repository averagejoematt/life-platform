"""#5656 release phases (owner review 2026-11-07): the history is written in two phases around the merge.

The pre-#5656 /api/character_receipt passes an unknown item attribute through, so a receipt's `public` written before
the merge would be served early by the old code. Measured on the old code (origin/main, every public GET route, the 184
real items with and without their planned variants): only /api/character_receipt moved, and only when the receipts
carried one. So the pre-merge phase writes the sheets, the day grades and the ledger; the post-merge phase writes the
receipts once the new code is live, and until then the new receipt route answers "not available", never method 1.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import backfill_public_variant as B  # noqa: E402
import backfill_public_variant_cli as CLI  # noqa: E402

PLAN = [
    {"pk": pk, "sk": f"DATE#2026-10-0{i}", "value": {}, "precision": 4} for pk in (B.SHEET_PK, B.GRADE_PK, B.RECEIPT_PK) for i in (1, 2)
]


def test_the_pre_merge_phase_never_writes_a_receipt():
    pre = B.plan_for_phase(PLAN, "pre-merge")
    assert pre and all(w["pk"] != B.RECEIPT_PK for w in pre)
    assert {w["pk"] for w in pre} == {B.SHEET_PK, B.GRADE_PK}


def test_the_post_merge_phase_writes_only_receipts_and_no_ledger():
    post = B.plan_for_phase(PLAN, "post-merge")
    assert post and {w["pk"] for w in post} == {B.RECEIPT_PK}
    assert B.PHASE_WRITES_LEDGER == {"pre-merge": True, "post-merge": False, "all": True}


def test_the_two_phases_partition_the_whole_plan():
    pre, post = B.plan_for_phase(PLAN, "pre-merge"), B.plan_for_phase(PLAN, "post-merge")
    keys = lambda ws: {(w["pk"], w["sk"]) for w in ws}  # noqa: E731
    assert keys(pre) & keys(post) == set() and keys(pre) | keys(post) == keys(PLAN) == keys(B.plan_for_phase(PLAN, "all"))


def test_an_apply_must_name_its_phase(monkeypatch):
    """Refused before any AWS client exists: no table, no write."""
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    with pytest.raises(SystemExit) as e:
        CLI.main(["--out", "/nonexistent", "--apply"])
    assert e.value.code == 2


def test_mutation_control_an_apply_with_a_phase_gets_past_the_phase_check(monkeypatch):
    """The check above is the phase rule, not a broken CLI: with a phase named, the run reaches AWS setup."""
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    with pytest.raises(KeyError):
        CLI.main(["--out", "/nonexistent", "--apply", "--phase", "pre-merge"])


def test_the_new_receipt_route_answers_not_available_before_the_post_merge_phase():
    from web import site_api_character as C

    assert C._public_receipt({"digest": "method-1", "transitions": {"pillars": {"mind": {}}}}) is None
