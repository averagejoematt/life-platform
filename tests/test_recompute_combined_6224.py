"""tests/test_recompute_combined_6224.py — the combined recompute, end to end on fake storage (#6224, #6311).

Owner rulings 2026-11-26/27: ONE final recompute — the private tool's plan, then the public projection computed on the
PLANNED private rows (``backfill_public_variant.py --plan-in``) — with backup and tested rollback. Held here on the
private tool's own stub store (Decimal-only, conditional puts) and its synthetic seed (no real reading):

  * the public dry run reads the planned rows, and refuses a plan that is not the private schema, does not cover the
    public window, or misses a stored date;
  * the public plan id is deterministic over (private plan id, method version, planned public blocks) and moves when
    the private plan does;
  * the public apply is refused until the live rows are exactly the approved private plan's (must-fail before the
    private apply);
  * private apply → public apply → both verify at 0 writes → rollback public → rollback private → every item
    byte-identical to the start.
"""

from __future__ import annotations

import copy
import json
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import backfill_public_variant as B  # noqa: E402
import backfill_public_variant_cli as CLI  # noqa: E402
import backfill_public_variant_planin as PI  # noqa: E402
import recompute_character_private as T  # noqa: E402
import recompute_character_private_apply as A  # noqa: E402
import test_recompute_character_private_6311 as P  # noqa: E402 — the private tool's stub store and synthetic seed
from common.numeric import decimals_to_float, floats_to_decimal  # noqa: E402
from health import character_privacy as CP, character_public  # noqa: E402

CONFIG = json.load(open(os.path.join(ROOT, "config", "character_sheet.json"), encoding="utf-8"))
TS = "2026-11-27T01:00:00+00:00"


class PublicAdapter:
    """The boto3 Table surface the public tool uses, over the private tool's stub store (numbers stored as Decimal)."""

    def __init__(self, store):
        self.store = store

    def get_item(self, Key=None, **_kw):  # noqa: N803
        it = self.store.get(Key["pk"], Key["sk"])
        return {"Item": it} if it is not None else {}

    def update_item(
        self, Key=None, UpdateExpression="", ExpressionAttributeNames=None, ExpressionAttributeValues=None, **_kw
    ):  # noqa: N803
        key = (Key["pk"], Key["sk"])
        item = copy.deepcopy(self.store.items[key])
        attr = ExpressionAttributeNames["#p"]
        if UpdateExpression.startswith("SET"):
            item[attr] = ExpressionAttributeValues[":p"]
        else:
            item.pop(attr, None)
        self.store.items[key] = P._normalise(item)

    def put_item(self, Item=None, **_kw):  # noqa: N803
        self.store.items[(Item["pk"], Item["sk"])] = P._normalise(copy.deepcopy(Item))

    def delete_item(self, Key=None, **_kw):  # noqa: N803
        self.store.items.pop((Key["pk"], Key["sk"]), None)


@pytest.fixture(scope="module")
def private(tmp_path_factory):
    """The seeded store and its private plan file (the ladder runs once per module)."""
    out = tmp_path_factory.mktemp("combined")
    store = P.seed_store()
    plan = P.plan_for(store, out)
    path = T.write_outputs(plan, str(out / "out"))["plan"]
    return store, path


def _fresh(store):
    s = P.StubStore()
    s.items = copy.deepcopy(store.items)
    return s


def _snapshot(store) -> dict:
    """The public tool's snapshot, from the stub store (floats, as load_snapshot reads)."""
    sheets = {i["date"]: decimals_to_float(i) for (pk, _sk), i in store.items.items() if pk == B.SHEET_PK}
    receipts = {i["date"]: decimals_to_float(i) for (pk, _sk), i in store.items.items() if pk == B.RECEIPT_PK}
    return {"sheets": sheets, "receipts": receipts}


def public_plan(store, plan_path) -> tuple:
    """The public dry run's plan on the PLANNED private rows (the CLI's own steps: replay, receipts, narrow, expected)."""
    snap = _snapshot(store)
    expected = PI.apply_to_snapshot(snap, PI.load_private_plan(plan_path))
    char = B.replay_character(snap["sheets"], {}, {}, CONFIG, TS)
    receipts = {}
    for d, r in char.items():
        if r.get("transitions") and d in snap["receipts"]:
            rec_like = {"date": d, B.PUBLIC: r["public"], "public_progression_transitions": r["transitions"]}
            receipts[d] = character_public.public_receipt(rec_like, CONFIG, snap["receipts"][d].get("input_rows"))
    plan_all = B.plan_writes(char, {}, set(snap["receipts"]), receipts)
    stored = {(B.SHEET_PK, f"DATE#{d}"): i for d, i in snap["stored_sheets"].items()}
    stored.update({(B.RECEIPT_PK, f"DATE#{d}"): i for d, i in _snapshot(store)["receipts"].items()})
    plan, _skipped = CLI.narrow_plan(plan_all, stored)
    plan = PI.attach_expected(plan, expected)
    pid = PI.public_plan_id(A.load_plan(plan_path)["plan_id"], CP.PUBLIC_METHOD_VERSION, plan)
    return plan, pid


def _canon(store) -> dict:
    return {str(k): T.canonical(T.to_typed(v)) for k, v in sorted(store.items.items())}


def test_end_to_end_apply_verify_and_rollback_restore_every_item_byte_identically(private, tmp_path):
    base, plan_path = private
    store = _fresh(base)
    start = _canon(store)
    table = PublicAdapter(store)
    pub, pid = public_plan(store, plan_path)
    assert pub and all("expected_method1_digest" in w for w in pub)
    # must-fail: before the private apply the live rows are not the planned ones — the public apply is refused
    assert PI.unplanned_rows(lambda k: table.get_item(Key=k).get("Item"), pub)

    priv = A.apply_plan(store, A.load_plan(plan_path), str(tmp_path), "all", TS)
    assert priv["aborted"] == []
    assert PI.unplanned_rows(lambda k: table.get_item(Key=k).get("Item"), pub) == []  # now exactly the approved rows

    export = B.build_export(lambda k: table.get_item(Key=k).get("Item"), pub, TS)
    B.record_ledger_preimage(table, export)
    assert B.apply_plan(table, pub, export)["written"] == len(pub)
    B.put_public_ledger(table, {"ledger_version": "v2", "rows": []})

    again, pid2 = public_plan(store, plan_path)
    assert again == [] and pid2 != pid  # public verify: 0 writes (the plan id covers the writes, so it moves to the empty plan)
    assert A.verify(store, str(tmp_path / "verify"), trees=P.TREES)["planned_writes"] == 0  # private verify: 0

    assert B.rollback(table, export, apply=True)["refused"] == []  # PUBLIC first
    done = A.rollback(store, priv["export"], apply=True)  # then PRIVATE
    assert done["refused"] == [] and done["verified"]["mismatches"] == []
    assert _canon(store) == start


def test_the_public_plan_id_is_deterministic_and_follows_the_private_plan(private):
    base, plan_path = private
    p1, id1 = public_plan(_fresh(base), plan_path)
    p2, id2 = public_plan(_fresh(base), plan_path)
    assert id1 == id2 and len(id1) == 16
    assert PI.public_plan_id("another-private-plan", CP.PUBLIC_METHOD_VERSION, p1) != id1  # control
    assert PI.public_plan_id(A.load_plan(plan_path)["plan_id"], CP.PUBLIC_METHOD_V2, p1) != id1


def test_plan_in_refuses_the_wrong_schema_and_a_window_gap(private, tmp_path):
    base, plan_path = private
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema": "something-else", "rows": []}))
    with pytest.raises(PI.PlanInError, match="schema"):
        PI.load_private_plan(str(bad))
    plan = PI.load_private_plan(plan_path)
    snap = _snapshot(_fresh(base))
    later = dict(next(iter(snap["sheets"].values())), date="2099-01-01", sk="DATE#2099-01-01")
    snap["sheets"]["2099-01-01"] = later  # a stored sheet the plan does not cover
    with pytest.raises(PI.PlanInError, match="does not cover"):
        PI.apply_to_snapshot(snap, plan)
    ok = _snapshot(_fresh(base))
    assert PI.apply_to_snapshot(ok, plan)  # control: the covered window is accepted


def test_an_edited_private_plan_is_refused(private, tmp_path):
    _base, plan_path = private
    edited = json.load(open(plan_path, encoding="utf-8"))
    edited["rows"][0]["stored_digest"] = "0" * 64
    path = tmp_path / "edited.json"
    path.write_text(json.dumps(edited))
    with pytest.raises(PI.PlanInError, match="integrity"):
        PI.load_private_plan(str(path))


def test_the_combined_summary_fails_on_an_unattributed_public_change():
    import recompute_character_combined as C

    plan = {"rows": [{"pk": B.SHEET_PK, "date": "2026-10-01", "causes": ["method_version_stamp"], "planned_item": None}]}
    man = {"character": [{"date": "2026-10-01", "character_level": [5, 4], "level_changed": True}]}
    assert C.attribute(plan, man)["unattributed"] == ["2026-10-01"]
    plan["rows"][0]["causes"] = ["missing_data", "recompute_provenance"]
    out = C.attribute(plan, man)  # control: a named method cause attributes it
    assert out["unattributed"] == [] and out["by_cause"] == {"missing_data": 1}


def test_floats_to_decimal_round_trip_keeps_the_fingerprint(private):
    """The expected fingerprint is taken on the planned float item; the live row holds Decimals after the apply."""
    _base, plan_path = private
    item = next(iter(PI.planned_items(PI.load_private_plan(plan_path), B.SHEET_PK).values()))
    assert B.item_digest(item) == B.item_digest(P._normalise(floats_to_decimal(item, precision=None)))


def test_the_public_apply_refusal_names_the_approval_and_the_live_rows(private, tmp_path):
    base, plan_path = private
    store = _fresh(base)
    table = PublicAdapter(store)
    pub, pid = public_plan(store, plan_path)
    plan = PI.load_private_plan(plan_path)
    assert PI.apply_refusal(None, None, pid, table, pub) is None  # without --plan-in: unchanged behaviour
    assert "not the approved" in PI.apply_refusal(plan, "0" * 16, pid, table, pub)
    assert "run the private apply first" in PI.apply_refusal(plan, pid, pid, table, pub)
    A.apply_plan(store, A.load_plan(plan_path), str(tmp_path), "all", TS)
    assert PI.apply_refusal(plan, pid, pid, table, pub) is None  # control: approved id + planned rows live
