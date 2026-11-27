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
    expected = PI.apply_to_snapshot(snap, PI.load_private_plan(plan_path), plan_path)
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
    # rollback coverage == write set, both tools (owner: "rollback coverage")
    private_writes = {(r["pk"], r["sk"]) for r in A.load_plan(plan_path)["rows"] if r["action"] == "write"}
    priv_export = json.load(open(priv["export"], encoding="utf-8"))
    assert {(e["pk"], e["sk"]) for e in priv_export["entries"]} == private_writes == {(w["pk"], w["sk"]) for w in priv["written"]}
    assert PI.unplanned_rows(lambda k: table.get_item(Key=k).get("Item"), pub) == []  # now exactly the approved rows

    export = B.build_export(lambda k: table.get_item(Key=k).get("Item"), pub, TS)
    assert {(e["pk"], e["sk"]) for e in export["entries"]} == {(w["pk"], w["sk"]) for w in pub}
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
        PI.apply_to_snapshot(snap, plan, plan_path)
    ok = _snapshot(_fresh(base))
    assert PI.apply_to_snapshot(ok, plan, plan_path)  # control: the covered window is accepted


def test_an_edited_private_plan_is_refused(private, tmp_path):
    _base, plan_path = private
    edited = json.load(open(plan_path, encoding="utf-8"))
    edited["rows"][0]["stored_digest"] = "0" * 64
    path = tmp_path / "edited.json"
    path.write_text(json.dumps(edited))
    with pytest.raises(PI.PlanInError, match="integrity"):
        PI.load_private_plan(str(path))


def _st(level, xp=10.0, comp=50.0, events=()):
    return {"character_level": level, "character_xp": xp, "composite": comp, "pillars": {}, "events": list(events)}


def test_layer1_credits_the_first_changing_step_and_fails_a_moving_control():
    import recompute_character_attribution as ATT

    stored = {"2026-10-01": _st(5), "2026-10-02": _st(5)}
    states = {
        "replay_residual": {"2026-10-01": _st(5), "2026-10-02": _st(5)},
        "journal_frequency": {"2026-10-01": _st(4), "2026-10-02": _st(5)},
        "tree_switch_residual": {"2026-10-01": _st(4), "2026-10-02": _st(5)},
        "missing_data": {"2026-10-01": _st(3), "2026-10-02": _st(6)},
    }
    plan = {"2026-10-01": {"character_level": 3, "character_xp": 10.0}, "2026-10-02": {"character_level": 6, "character_xp": 10.0}}
    out = ATT.method_layer(states, stored, plan)
    assert out["first_cause"]["character_level"] == {"journal_frequency": 1, "missing_data": 1}  # first step only
    assert out["control_differs"] == [] and out["last_step_differs_from_plan"] == []
    assert out["stored_vs_replay_residual"] == {"character_level": [], "character_xp": [], "composite": []}
    states["replay_residual"]["2026-10-02"] = _st(5, xp=11.0)  # a presentation residual is reported, never a failure
    assert ATT.method_layer(states, stored, plan)["stored_vs_replay_residual"]["character_xp"] == ["2026-10-02"]
    assert not ATT.failures({"method": ATT.method_layer(states, stored, plan), "public": {}})
    states["replay_residual"]["2026-10-02"] = _st(5)
    states["tree_switch_residual"]["2026-10-02"] = _st(9)  # must-fail: the control step moves
    assert ATT.failures({"method": ATT.method_layer(states, stored, plan), "public": {}})
    states["tree_switch_residual"]["2026-10-02"] = _st(5)
    assert ATT.failures({"method": ATT.method_layer(states, stored, {"2026-10-01": {"character_level": 1}}), "public": {}})  # last != plan


def test_layer2_fails_on_a_public_change_no_ladder_step_produces():
    import recompute_character_attribution as ATT

    q = lambda lv: {"character_level": lv, "character_xp": 1.0, "character_xp_debt": 0.0, "composite": 40.0}  # noqa: E731
    before = {"2026-10-01": q(5), "2026-10-02": q(5)}
    parts = [("privacy", {"2026-10-01": q(4), "2026-10-02": q(5)}), ("habit_timing", {"2026-10-01": q(4), "2026-10-02": q(5)})]
    final = {"2026-10-01": q(4), "2026-10-02": q(7)}  # planted: the method part moves 10-02
    planted = ATT.public_layer(before, parts + [("method", final)], final, {})
    assert planted["unattributed"] == ["2026-10-02 character_level"] and ATT.failures({"method": {}, "public": planted})
    ok = ATT.public_layer(before, parts + [("method", final)], final, {"2026-10-02": ["missing_data"]})  # control
    assert ok["unattributed"] == [] and ok["by_part"]["privacy"]["character_level"]["dates"] == 1
    assert ok["by_part"]["method"]["character_level"] == {"dates": 1, "range": [2, 2, 2]} and ok["residual"] == {}


def test_method_events_name_the_first_step_and_the_served_state():
    import recompute_character_attribution as ATT

    ev = {"who": "nutrition", "type": "level_up", "old": 1, "new": 2}
    stored = {"2026-10-02": _st(5, events=[ev])}
    states = {"stress_days": {"2026-10-02": _st(5, events=[ev])}, "missing_data": {"2026-10-02": _st(5)}}
    rows = ATT.method_events(states, stored, {("2026-10-02", "nutrition", "2")})
    assert rows == [
        {
            "date": "2026-10-02",
            "who": "nutrition",
            "event": "level_up",
            "level": "2",
            "change": "REMOVED",
            "first_cause": "missing_data",
            "served_before": True,
            "protected_pillar": False,
        }
    ]


def test_the_plan_carries_ladder_states_the_attribution_reads(private):
    _base, plan_path = private
    states = A.ladder_states(plan_path)
    assert list(states)[-1] == "missing_data" and "tree_switch_residual" in states
    import recompute_character_attribution as ATT

    out = ATT.method_layer(states, A.stored_states(plan_path), A.planned_sheets(plan_path))
    assert out["last_step_differs_from_plan"] == [] and out["control_differs"] == []


def test_floats_to_decimal_round_trip_keeps_the_fingerprint(private):
    """The expected fingerprint is taken on the planned float item; the live row holds Decimals after the apply."""
    _base, plan_path = private
    item = next(iter(PI.planned_rows(plan_path)[0].values()))
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


# ── owner conditions A and the final state (recompute_character_verify) ──────────────────────────────────────────────


def _row(date, who, level, status, new_date=None, reason=None):
    r = {"date": date, "who": who, "type": "level_up", "key": [who, "level_up", str(level)], "new": level, "status": status}
    if new_date:
        r["new_date"] = new_date
    if reason:
        r["reason"] = reason
    return r


def _ev(date, who, level):
    return {"date": date, "who": who, "type": "level_up", "new": level}


def _reconcile_fixture():
    rows = [
        _row("2026-10-01", "sleep", 4, "KEPT"),
        _row("2026-10-02", "movement", 7, "MOVED", new_date="2026-10-04"),
        _row("2026-10-03", "character", 9, "REMOVED", reason="the corrected chain does not reach it"),
        _row("2026-10-05", "nutrition", 3, "ADDED"),
    ]
    marked = [("2026-10-04", ["movement", "level_up", "7"], "2026-10-02"), ("2026-10-05", ["nutrition", "level_up", "3"], None)]
    final = [_ev("2026-10-01", "sleep", 4), _ev("2026-10-04", "movement", 7), _ev("2026-10-05", "nutrition", 3)]
    before = [_ev("2026-10-01", "sleep", 4), _ev("2026-10-02", "movement", 7), _ev("2026-10-03", "character", 9)]
    return {"rows": rows}, marked, final, before


def test_the_reconciliation_equation_holds_and_names_the_moved_event():
    import recompute_character_verify as VF

    out = VF.reconcile_events(*_reconcile_fixture())
    assert out["failures"] == [] and out["equation"] == {"reconstructed": 2, "added": 1, "moved": 1, "holds": True}
    assert out["marked_not_added"] == [{"date": "2026-10-04", "key": ["movement", "level_up", "7"], "redated_from": "2026-10-02"}]
    assert out["served_before"]["by_disposition"] == {"KEPT": 1, "MOVED": 1, "REMOVED (the corrected chain does not reach it)": 1}


def test_must_fail_a_planted_duplicate_fails_the_reconciliation():
    import recompute_character_verify as VF

    comp, marked, final, before = _reconcile_fixture()
    final.append(_ev("2026-10-09", "sleep", 4))  # the same (who, type, level) on a second date
    assert any("duplicate" in f for f in VF.reconcile_events(comp, marked, final, before)["failures"])


def test_must_fail_an_unmarked_added_event_and_a_marked_kept_one():
    import recompute_character_verify as VF

    comp, marked, final, before = _reconcile_fixture()
    fails = VF.reconcile_events(comp, marked[:1] + [("2026-10-01", ["sleep", "level_up", "4"], None)], final, before)["failures"]
    assert any("without the reconstructed marker" in f for f in fails) and any("KEPT event(s) carry" in f for f in fails)


def test_must_fail_a_served_event_with_no_disposition():
    import recompute_character_verify as VF

    comp, marked, final, before = _reconcile_fixture()
    before.append(_ev("2026-10-06", "sleep", 5))  # served, but the comparison never accounts for it
    assert any("no disposition" in f for f in VF.reconcile_events(comp, marked, final, before)["failures"])


def _state(comp):
    return {"character_level": 5.0, "character_xp": 10.0, "composite": comp, "pillars": {}, "events": []}


def test_must_fail_a_composite_only_difference_in_the_private_final_state():
    import recompute_character_verify as VF

    last = {"2026-10-01": _state(61.2), "2026-10-02": _state(60.0)}
    assert VF.final_state_check(last, {"2026-10-01": _state(61.2), "2026-10-02": _state(60.0)})["mismatches"] == []
    bad = VF.final_state_check(last, {"2026-10-01": _state(61.2), "2026-10-02": _state(60.1)})
    assert bad["mismatches"] == ["2026-10-02 composite"] and bad["composite_verified"] == 1
    assert VF.final_state_check(last, None)["status"] == "pending"


def test_must_fail_a_composite_only_difference_on_the_public_side():
    import recompute_character_verify as VF

    recs = {"2026-10-01": {}, "2026-10-02": {}}
    ok = VF.public_composite_check(recs, {"2026-10-01": 50.0, "2026-10-02": 51.0}, route=lambda r: None)
    assert ok["verified"] == 0  # the route serves nothing: never a silent pass
    served = {"2026-10-01": 50.0, "2026-10-02": 51.0}
    route = lambda r: served[r["d"]]  # noqa: E731
    recs = {d: {"d": d} for d in served}
    assert VF.public_composite_check(recs, dict(served), route=route)["verified"] == 2
    assert VF.public_composite_check(recs, {"2026-10-01": 50.0, "2026-10-02": 51.1}, route=route)["mismatches"][0]["date"] == "2026-10-02"
