"""#5089 — the charter predictions: wire-shape parity with diary_claims, idempotency, dry-run == apply."""

import contextlib
import io
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))
sys.path.insert(0, os.path.join(_ROOT, "scripts"))

import register_charter_predictions as rcp  # noqa: E402
from coach.prediction_windows import is_gradeable  # noqa: E402
from privacy import diary_claims as dc  # noqa: E402


class _Cond(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _Table:
    def __init__(self):
        self.items = {}

    def put_item(self, Item, ConditionExpression=None):
        k = (Item["pk"], Item["sk"])
        if k in self.items:
            raise _Cond()
        self.items[k] = Item


def _wire():
    """A real diary_claims record, built by the module that writes the store."""
    ok, why, n = dc.admit_claim(
        {"consent": True, "claim": "weight falls", "metric": "weight_lbs", "horizon_days": 30, "direction": "down"},
        "2026-07-26",
        "DATE#2026-07-26#journal#video_diary#a1b2c3d4e5f6",
    )
    assert ok, why
    return dc.build_claim_record(n, "2026-07-26", "DATE#2026-07-26#journal#video_diary#a1b2c3d4e5f6", "2026-07-26T00:00:00+00:00")


def test_four_predictions_dated_2026_12_06():
    recs = rcp.build_records()
    assert len(recs) == 4 and len({r["sk"] for r in recs}) == 4
    assert {r["grade_by"] for r in recs} == {"2026-12-06"}
    assert all(r["measurement"]["function"] and r["measurement"]["pass_rule"] for r in recs)


def test_record_shape_is_the_wire_shape():
    wire = _wire()
    # Every field the store's readers/evaluator key on is present with the same type; the only wire fields
    # we omit are the diary-entry pointers and consent stamps (not a diary claim) and the clock stamps.
    omitted = {"source_pk", "source_sk", "consent", "consent_at", "created_at"}
    for rec in rcp.build_records():
        assert set(wire) - omitted <= set(rec)
        for f in set(wire) - omitted - {"evaluation", "quote"}:
            assert type(rec[f]) is type(wire[f]), f
        assert rec["pk"] == dc.claims_pk() and rec["sk"].startswith("PREDICTION#2026-10-18#")
        assert rec["coach_id"] == "" and rec["visibility"] == "private"
        assert rec["sk"] == dc.claim_sk(rec["stated_date"], rec["claim_natural"])


def test_evaluator_skips_but_never_retires():
    for rec in rcp.build_records():
        assert not is_gradeable(rec["evaluation"])  # structurally skipped by the daily grader
        assert rec["status"] == "observation"  # not in EVALUABLE_STATUSES => never retired as ungradeable-pending


def test_apply_is_idempotent():
    t = _Table()
    first = rcp.apply_records(t, rcp.build_records(), "2026-10-18T12:00:00+00:00")
    again = rcp.apply_records(t, rcp.build_records(), "2026-10-19T12:00:00+00:00")
    assert [r["result"] for r in first] == ["registered"] * 4
    assert [r["result"] for r in again] == ["already_registered"] * 4
    assert len(t.items) == 4


def test_dry_run_prints_exactly_what_apply_writes():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert rcp.main([]) == 0
    text = buf.getvalue()
    body = text.split("\n", 1)[1]
    dec, printed, i = json.JSONDecoder(), [], 0
    while i < len(body):
        while i < len(body) and body[i].isspace():
            i += 1
        if i >= len(body):
            break
        obj, i = dec.raw_decode(body, i)
        printed.append(obj)
    t = _Table()
    rcp.apply_records(t, rcp.build_records(), "NOW")
    written = [{k: (json.loads(json.dumps(v, default=float))) for k, v in item.items()} for item in t.items.values()]
    for w in written:
        assert w.pop("registered_at") == "NOW"
    for p in printed:
        assert p.pop("registered_at") == "<stamped at apply>"
    assert sorted(printed, key=lambda r: r["sk"]) == sorted(written, key=lambda r: r["sk"])
