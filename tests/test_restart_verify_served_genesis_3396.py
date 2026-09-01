"""#3396 — the reset must verify the genesis a READER receives, not just the one it staged.

WHAT HAPPENED. On launch eve (2026-08-31) `restart_pipeline.py` staged genesis 2026-09-01
and `cdk deploy --all` updated every function — CloudFormation records
`SiteApiLambdaA5C2FE08 UPDATE_COMPLETE` at 20:13:43Z inside the reset's own deploy window —
yet the public API was still answering with the previous cycle's anchor hours later. The
nightly QA sweep read cycle-14 residue off 14 pages, the #2878 weight-arbitration smoke
check tripped on the disagreement, and the scope-blind rollback reverted wanted prose.

WHY NO EXISTING CHECK CAUGHT IT. Every one of `restart_verify.py`'s other checks reads the
CONTROL plane — constants.py, DynamoDB, config/, CloudWatch. None reads what a reader
actually receives. A fleet correct everywhere except at the edge passed the whole battery.
So the new check is deliberately cause-agnostic: it asserts the one fact the reset exists
to establish, on the plane the public reads it from.

This file tests the predicate that check rests on. The load-bearing case is the LAST one:
an unreadable answer must fail, not pass — "could not tell" is not "fine" for a check whose
whole reason for existing is that a reset can silently leave the serving path a cycle behind.
"""

import importlib.util
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
spec = importlib.util.spec_from_file_location("restart_verify_3396", os.path.join(_REPO, "deploy", "restart_verify.py"))
rv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rv)


def test_reads_the_genesis_the_api_answers_with():
    assert rv.served_genesis({"experiment": {"genesis": "2026-09-01", "cycle": 15}}) == "2026-09-01"


def test_a_stale_serving_path_does_not_compare_equal_to_the_staged_genesis():
    """The live failure shape: the fleet is on 2026-09-01, the edge is still on 2026-08-17."""
    stale = rv.served_genesis({"experiment": {"genesis": "2026-08-17", "cycle": 15}})
    assert stale == "2026-08-17"
    assert stale != "2026-09-01"


def test_an_unreadable_answer_is_none_so_the_check_fails_rather_than_passes():
    """Fail-toward-red. None never equals a genesis string, so each of these reds the check.

    A predicate that returned the staged value (or "" compared loosely) on a malformed
    payload would turn an outage into a pass — the exact shape of the class this check was
    added to end.
    """
    for payload in (
        None,
        {},
        [],
        "not-a-dict",
        {"experiment": None},
        {"experiment": []},
        {"experiment": {}},
        {"experiment": {"genesis": None}},
        {"experiment": {"genesis": ""}},
        {"experiment": {"genesis": 20260901}},
        {"genesis": "2026-09-01"},  # right value, wrong place — still not an answer
    ):
        assert rv.served_genesis(payload) is None, payload
        assert rv.served_genesis(payload) != "2026-09-01"


def test_the_check_is_wired_into_the_verifier_not_just_defined():
    """A helper nothing calls is not a check (#2578). Assert the call site exists."""
    source = open(os.path.join(_REPO, "deploy", "restart_verify.py")).read()
    assert "served /api/source_freshness genesis == staged genesis (#3396)" in source
    assert "live = served_genesis(served)" in source
    assert "api/source_freshness?cb=verify" in source, "the served read must bust the CDN cache"
