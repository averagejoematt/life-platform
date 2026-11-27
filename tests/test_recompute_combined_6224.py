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
import backfill_public_variant_backup as BK  # noqa: E402
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


class StubS3:
    """``BK.S3Backups``' surface with S3's conditional-put semantics (IfNoneMatch='*': an existing key is refused)."""

    def __init__(self, fail_put: bool = False):
        self.objects: dict = {}
        self.fail_put = fail_put
        self.calls: list = []

    def put_new(self, key, body):
        self.calls.append(("put", key))
        if self.fail_put:
            raise RuntimeError("AccessDenied (synthetic)")
        if key in self.objects:
            raise BK.BackupExists(key)
        self.objects[key] = bytes(body)

    def get(self, key):
        return self.objects[key]

    def list(self, prefix):
        return sorted(k for k in self.objects if k.startswith(prefix))

    def versioning(self):
        return "Enabled"


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


def _served_overall(store) -> dict:
    """{date: the overall numbers a public route serves} for every stored sheet, the global switch forced OFF: through
    ``public_sheet`` and through ``/api/character``'s own handler on a stub table holding that one record."""
    import recompute_character_verify as VF

    out = {}
    saved = CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE
    CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = False
    try:
        for (pk, sk), item in sorted(store.items.items()):
            if pk != B.SHEET_PK:
                continue
            rec = decimals_to_float(item)
            view = CP.public_sheet(rec, pending=False) or {}
            nums = {k: view.get(k) for k in ("character_level", "character_xp", "character_xp_debt") if view.get(k) is not None}
            if view:
                route = VF.route_character_of(rec)
                nums.update(
                    {f"route.{k}": route.get(k) for k in ("level", "xp_total", "xp_debt", "composite_score") if route.get(k) is not None}
                )
            if nums:
                out[sk] = nums
    finally:
        CP.PUBLIC_CHARACTER_SCORES_PENDING_RECOMPUTE = saved
    return out


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

    plan = A.load_plan(plan_path)
    with pytest.raises(T.PlanGuardError):
        A.apply_plan(store, plan, str(tmp_path / "wrong"), "all", TS, approved_plan_id="0" * 16)  # a wrong approval
    assert _canon(store) == start  # refused before any write
    priv = A.apply_plan(store, plan, str(tmp_path), "all", TS, approved_plan_id=plan["plan_id"])
    assert priv["aborted"] == []
    # rollback coverage == write set, both tools (owner: "rollback coverage")
    private_writes = {(r["pk"], r["sk"]) for r in A.load_plan(plan_path)["rows"] if r["action"] == "write"}
    priv_export = json.load(open(priv["export"], encoding="utf-8"))
    assert {(e["pk"], e["sk"]) for e in priv_export["entries"]} == private_writes == {(w["pk"], w["sk"]) for w in priv["written"]}
    assert PI.unplanned_rows(lambda k: table.get_item(Key=k).get("Item"), pub) == []  # now exactly the approved rows

    export = B.build_export(lambda k: table.get_item(Key=k).get("Item"), pub, TS)
    assert {(e["pk"], e["sk"]) for e in export["entries"]} == {(w["pk"], w["sk"]) for w in pub}
    B.record_ledger_preimage(table, export)
    s3 = StubS3()  # the public pre-image is backed up to S3 (conditional put, verified) BEFORE the first write
    applied = BK.apply_phase(table, s3, export, pub, pid, "pre-merge", str(tmp_path), {"ledger_version": "v2", "rows": []})
    assert applied["written"] == len(pub) and applied["backup"]["key"] == BK.backup_key(pid, "pre-merge")

    again, pid2 = public_plan(store, plan_path)
    assert again == [] and pid2 != pid  # public verify: 0 writes (the plan id covers the writes, so it moves to the empty plan)
    assert A.verify(store, str(tmp_path / "verify"), trees=P.TREES)["planned_writes"] == 0  # private verify: 0

    from_s3 = BK.load_export(f"s3://bucket/{applied['backup']['key']}", s3)  # PUBLIC first, from the S3 copy (sha256 verified)
    assert {(e["pk"], e["sk"]) for e in from_s3["entries"]} == {(w["pk"], w["sk"]) for w in pub}  # coverage == write set
    served_after_apply = _served_overall(store)
    assert served_after_apply, "control: after the public apply the v3 blocks serve their numbers with the switch off"
    assert B.rollback(table, from_s3, apply=True)["refused"] == []
    # #6224: a rollback of the public apply returns every date to "being recalculated", never to the old numbers —
    # the restored blocks are older-method, and the switch is forced OFF here
    assert _served_overall(store) == {}, _served_overall(store)
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
    assert out["control_differs"] == {"tree_switch_residual": []} and out["last_step_differs_from_plan"] == []
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
    plan = A.load_plan(plan_path)
    assert list(states) == [s["cause"] for s in plan["ladder"]]  # the order is the plan's, never hard-coded
    import recompute_character_attribution as ATT

    controls = ATT.controls_of(plan["causes_legend"])
    assert set(controls) >= {"tree_switch_residual", "final_switch_residual"}  # both controls, read from the legend
    out = ATT.method_layer(states, A.stored_states(plan_path), A.planned_sheets(plan_path), controls)
    assert out["last_step_differs_from_plan"] == [] and set(out["control_differs"]) == set(controls)
    assert not any(out["control_differs"].values())


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


def _state(comp, mood="steady"):
    return {"character_level": 5.0, "character_xp": 10.0, "composite": comp, "character_mood": mood, "pillars": {}, "events": []}


def test_must_fail_a_mood_only_difference_in_the_private_final_state():
    import recompute_character_verify as VF

    last = {"2026-10-01": _state(61.2)}
    assert VF.final_state_check(last, {"2026-10-01": _state(61.2, mood="unavailable")})["mismatches"] == ["2026-10-01 character_mood"]


def test_must_fail_the_second_control_moving():
    import recompute_character_attribution as ATT

    s0 = {"2026-10-01": _st(5)}
    states = {"a": s0, "tree_switch_residual": s0, "b": s0, "final_switch_residual": {"2026-10-01": _st(6)}}
    out = ATT.method_layer(
        states, s0, {"2026-10-01": {"character_level": 6, "character_xp": 10.0}}, ("tree_switch_residual", "final_switch_residual")
    )
    assert out["control_differs"] == {"tree_switch_residual": [], "final_switch_residual": ["2026-10-01"]}
    assert ATT.failures({"method": out, "public": {}})


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


def test_the_private_apply_refuses_without_the_exact_approved_plan_id(private, tmp_path, monkeypatch):
    """Through the private tool's CLI: no --approved-plan-id, or a different one, exits 4 before any store is opened."""
    _base, plan_path = private
    for var in ("AWS_CONFIG_FILE", "AWS_SHARED_CREDENTIALS_FILE"):
        monkeypatch.setenv(var, os.devnull)

    def no_store(*_a, **_k):
        raise AssertionError("the refusal must come before any store is opened")

    monkeypatch.setattr(T, "live_store", no_store)
    out = str(tmp_path / "apply")
    assert T.main(["--out", out, "--apply", "--plan-in", plan_path]) == 4
    assert T.main(["--out", out, "--apply", "--plan-in", plan_path, "--approved-plan-id", "0" * 16]) == 4


# ── the public pre-image backup (owner: "backup before writes", "verified rollback") ──────────────────────────────────


class _Recording(PublicAdapter):
    def __init__(self, store, log):
        super().__init__(store)
        self.log = log

    def update_item(self, **kw):
        self.log.append(("ddb", kw["Key"]["sk"]))
        return super().update_item(**kw)

    def put_item(self, **kw):
        self.log.append(("ddb", kw["Item"]["sk"]))
        return super().put_item(**kw)


class _LoggedS3(StubS3):
    def __init__(self, log, **kw):
        super().__init__(**kw)
        self.log = log

    def put_new(self, key, body):
        self.log.append(("s3", key))
        return super().put_new(key, body)


def _applied_private(private, tmp_path):
    base, plan_path = private
    store = _fresh(base)
    plan = A.load_plan(plan_path)
    os.makedirs(str(tmp_path / "priv"), exist_ok=True)
    A.apply_plan(store, plan, str(tmp_path / "priv"), "all", TS, approved_plan_id=plan["plan_id"])
    pub, pid = public_plan(store, plan_path)
    return store, pub, pid


def test_the_backup_is_written_and_verified_before_the_first_write(private, tmp_path):
    store, pub, pid = _applied_private(private, tmp_path)
    log: list = []
    table, s3 = _Recording(store, log), _LoggedS3(log)
    export = B.build_export(lambda k: table.get_item(Key=k).get("Item"), pub, TS)
    BK.apply_phase(table, s3, export, pub, pid, "pre-merge", str(tmp_path), None)
    first_ddb = next(i for i, e in enumerate(log) if e[0] == "ddb")
    assert [e for e in log[:first_ddb]] == [("s3", BK.backup_key(pid, "pre-merge")), ("s3", BK.backup_key(pid, "pre-merge") + ".sha256")]
    assert BK.backup_key(pid, "pre-merge").startswith("backups/character-public-recompute/")
    assert os.path.exists(str(tmp_path / f"export_pre-merge_{pid}.json.sha256"))  # the local copy is kept too


def test_a_failing_backup_put_aborts_with_zero_writes(private, tmp_path):
    store, pub, pid = _applied_private(private, tmp_path)
    before = _canon(store)
    table = PublicAdapter(store)
    export = B.build_export(lambda k: table.get_item(Key=k).get("Item"), pub, TS)
    with pytest.raises(BK.BackupError, match="no write made"):
        BK.apply_phase(table, StubS3(fail_put=True), export, pub, pid, "pre-merge", str(tmp_path), {"rows": []})
    assert _canon(store) == before


def test_an_existing_matching_backup_resumes_and_a_different_one_stops(private, tmp_path):
    store, pub, pid = _applied_private(private, tmp_path)
    table = PublicAdapter(store)
    s3 = StubS3()
    export = B.build_export(lambda k: table.get_item(Key=k).get("Item"), pub, TS)
    BK.backup_export(s3, export, pid, "pre-merge", str(tmp_path / "a.json"))  # an earlier run's backup, same pre-images
    later = B.build_export(lambda k: table.get_item(Key=k).get("Item"), pub, "2026-11-27T02:00:00+00:00")
    assert BK.apply_phase(table, s3, later, pub, pid, "pre-merge", str(tmp_path), None)["backup"]["resumed"] is True
    # a different pre-image under the same key stops the apply, with zero writes
    store2, pub2, pid2 = _applied_private(private, tmp_path / "b")
    t2 = PublicAdapter(store2)
    other = B.build_export(lambda k: t2.get_item(Key=k).get("Item"), pub2, TS)
    other["entries"][0]["previous_public"] = {"synthetic": "a different pre-image"}
    s3b = StubS3()
    BK.backup_export(s3b, other, pid2, "pre-merge", str(tmp_path / "c.json"))
    before = _canon(store2)
    honest = B.build_export(lambda k: t2.get_item(Key=k).get("Item"), pub2, TS)
    os.makedirs(str(tmp_path / "d"))
    with pytest.raises(BK.BackupError, match="DIFFERENT backup"):
        BK.apply_phase(t2, s3b, honest, pub2, pid2, "pre-merge", str(tmp_path / "d"), None)
    assert _canon(store2) == before


def test_rollback_refuses_an_export_whose_sha256_does_not_match(tmp_path):
    s3 = StubS3()
    s3.objects["backups/character-public-recompute/x/export_pre-merge.json"] = b"{}"
    s3.objects["backups/character-public-recompute/x/export_pre-merge.json.sha256"] = b"0" * 64
    with pytest.raises(BK.BackupError, match="does not match"):
        BK.load_export("s3://bucket/backups/character-public-recompute/x/export_pre-merge.json", s3)
    local = tmp_path / "e.json"
    local.write_text("{}")
    with pytest.raises(BK.BackupError, match="no recorded sha256"):
        BK.load_export(str(local), None)


def test_the_public_preflight_is_read_only_and_names_its_limit():
    s3 = StubS3()
    out = BK.preflight(s3, "abcd")
    assert out["ok"] and out["verified_read_only"]["no_backup_under_prefix_yet"] and s3.calls == []
    assert "IfNoneMatch" in out["unverifiable_without_a_write"][0]
    s3.objects["backups/character-public-recompute/abcd/export_pre-merge.json"] = b"{}"
    assert not BK.preflight(s3, "abcd")["ok"]  # control: an existing backup under the plan id


def test_the_conditional_put_maps_a_412_to_backup_exists():
    class _Err(Exception):
        response = {"Error": {"Code": "PreconditionFailed"}}

    class _Client:
        def put_object(self, **kw):
            assert kw["IfNoneMatch"] == "*"
            raise _Err()

    with pytest.raises(BK.BackupExists):
        BK.S3Backups(_Client(), "b").put_new("backups/character-public-recompute/k", b"{}")


def test_backups_are_not_anonymously_readable():
    """deploy/bucket_policy.json: public GetObject covers site/* and named generated/* paths only; none names backups/."""
    policy = json.load(open(os.path.join(ROOT, "deploy", "bucket_policy.json"), encoding="utf-8"))
    for st in policy["Statement"]:
        if st.get("Effect") == "Allow" and st.get("Principal") in ("*", {"AWS": "*"}):
            res = st["Resource"] if isinstance(st["Resource"], list) else [st["Resource"]]
            assert not any("/backups/" in r or r.endswith(":::matthew-life-platform/*") for r in res), st.get("Sid")


def test_the_probe_evidence_is_printed_per_tool_and_an_absent_one_says_not_run(tmp_path):
    import recompute_character_combined_sections as S

    ev = {
        "key": "backups/character-public-recompute/probe-synthetic/export_probe.json",
        "started": "2026-11-27T17:26:48+00:00",
        "1_created": {"readback_matches": True},
        "2b_s3_response": {"code": "PreconditionFailed", "http": 412},
        "4_tool_same": {"resumed": True},
        "5_object_unchanged": True,
        "anonymous_read": {"site": 404, "bucket": 403},
        "boto3": "x",
        "botocore": "x",
    }
    f = tmp_path / "probe.json"
    f.write_text(json.dumps(ev))
    lines = S.probe_lines({"probe_evidence": S.load_probe_evidence([str(f)])})
    text = "\n".join(lines)
    assert "PUBLIC tool, exercised once for real" in text and "PreconditionFailed, HTTP 412" in text
    assert "PRIVATE tool: its own live conditional-put probe has NOT run" in text
    assert "PROVEN on this bucket and role for the public path" in text
    none = "\n".join(S.probe_lines({"probe_evidence": {}}))
    assert "no path yet" in none and "PUBLIC tool: its own live conditional-put probe has NOT run" in none
