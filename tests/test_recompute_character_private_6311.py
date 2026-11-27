"""#6311 — the private character recompute tool (scripts/recompute_character_private.py), on STUB storage only.

Synthetic data throughout (no real reading). The stub behaves like DynamoDB where the tool depends on it: Decimal-only
items (a float is refused), numbers normalised on write, conditional puts. No AWS client is ever built: every store in
this file is ``StubStore``; the replay child runs with every AWS config path at /dev/null (``child_env``).
"""

from __future__ import annotations

import copy
import json
import os
import sys
from datetime import date, timedelta
from decimal import Decimal

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))

import recompute_character_private as T  # noqa: E402
import recompute_character_private_apply as A  # noqa: E402
from common.numeric import floats_to_decimal  # noqa: E402
from health import character_engine as ce  # noqa: E402

GENESIS = T.EXPERIMENT_START_DATE
N_DAYS = 10
TREES = {"new": ROOT}
# A hermetic two-step ladder on the amended tree (the real ladder's first steps need the pre-amendment tree from git):
# step 1 takes Mind verbatim from the stored row, step 2 is the plan (Mind re-weighted from its stored components).
TEST_LADDER = (
    (
        "fidelity",
        "replay_residual",
        {"tree": "new", "rebuild": ["movement", "nutrition"], "loader": "held_skip", "relationships": "engine"},
    ),
    ("plan", "missing_data", T.PLAN_SPEC),
)


def _d(i: int) -> str:
    return (date.fromisoformat(GENESIS) + timedelta(days=i)).isoformat()


# ── the stub ────────────────────────────────────────────────────────────────────────────────────────────────────────


def _normalise(obj):
    if isinstance(obj, float):
        raise TypeError("Float types are not supported. Use Decimal types instead.")
    if isinstance(obj, Decimal):
        return Decimal(T.canon_number(obj))
    if isinstance(obj, dict):
        return {k: _normalise(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_normalise(v) for v in obj]
    return obj


class StubStore:
    def __init__(self):
        self.items: dict = {}
        self.objects: dict = {}
        self.writes: list = []
        self.s3_writes: list = []
        self.reads: dict = {}

    def seed(self, item: dict) -> None:
        self.items[(item["pk"], item["sk"])] = _normalise(copy.deepcopy(item))

    def query(self, pk, lo, hi):
        self.reads[pk] = self.reads.get(pk, 0) + 1
        return [copy.deepcopy(v) for (p, s), v in sorted(self.items.items()) if p == pk and lo <= s <= hi]

    def get(self, pk, sk):
        v = self.items.get((pk, sk))
        return copy.deepcopy(v) if v is not None else None

    def _holds(self, cur, clause):
        kind, path = clause[0], clause[1]
        segs = [path] if isinstance(path, str) else list(path)
        node, present = cur, cur is not None
        for s in segs:
            if not isinstance(node, dict) or s not in node:
                present, node = False, None
                break
            node = node[s]
        if kind == "exists":
            return present
        if kind == "not_exists":
            return not present
        return present and _normalise(node) == _normalise(clause[2])

    def put(self, item, cond):
        cur = self.items.get((item["pk"], item["sk"]))
        if not all(self._holds(cur, c) for c in cond):
            raise T.ConditionFailed(f"{item['pk']} {item['sk']}")
        self.items[(item["pk"], item["sk"])] = _normalise(copy.deepcopy(item))
        self.writes.append((item["pk"], item["sk"]))

    def put_backup(self, key, body):
        assert key.startswith("backups/") and key not in self.objects
        self.objects[key] = bytes(body)
        self.s3_writes.append(key)

    def get_backup(self, key):
        return self.objects[key]


# ── synthetic seed rows ─────────────────────────────────────────────────────────────────────────────────────────────


def _cfg():
    with open(os.path.join(ROOT, "config", "character_sheet.json"), encoding="utf-8") as fh:
        return json.load(fh)


def _pillar(name: str, i: int, cfg: dict, stale_stress: bool = False) -> dict:
    comps = cfg["pillars"][name]["components"]
    scores = {}
    for j, comp in enumerate(comps):
        if (i + j) % 5 == 0:
            scores[comp] = None  # a gap
        else:
            scores[comp] = float((17 * i + 29 * j) % 90 + 5)
    raw, det = ce._weighted_pillar_score(scores, comps)
    if stale_stress and "stress_management" in det:  # a pre-#5129 row: the stress score counted, no hold-out flags
        det["stress_management"] = {"score": 12.0, "weight": comps["stress_management"]["weight"]}
        raw = round(raw - 3.0, 1)
    return {"raw_score": raw, "components": det, "level": 1, "xp_total": 0, "xp_debt": 4 if i else 0}


def seed_store(n: int = N_DAYS, receipts: bool = True, challenge_day: int = 3) -> StubStore:
    cfg = _cfg()
    st = StubStore()
    for i in range(n):
        d = _d(i)
        rec = {
            "pk": T.SHEET_PK,
            "sk": f"DATE#{d}",
            "date": d,
            "character_level": 1,
            "character_xp": 0,
            "character_xp_debt": 4,
            "engine_version": "1.8.0",
            "computed_at": f"{d}T17:50:00+00:00",
            "run_id": f"seed-{i}",
            "phase": "experiment",
            "habit_scores_status": "ready",
            "public": {"character_level": 1, "origin": "synthetic"},
        }
        for p in ("sleep", "movement", "nutrition", "metabolic"):
            rec[f"pillar_{p}"] = _pillar(p, i, cfg)
        rec["pillar_mind"] = _pillar("mind", i, cfg, stale_stress=(i % 3 == 0))
        rec["pillar_relationships"] = {"raw_score": 50.0, "components": {}, "level": 1}
        rec["pillar_consistency"] = {"components": {"data_completeness": {"score": 80.0, "weight": 0.2}}, "level": 1}
        if i == challenge_day:
            rec["challenge_bonus_xp"] = {"movement": 5}
        st.seed(floats_to_decimal(rec, precision=4))
        if receipts and i % 2 == 0:
            st.seed(
                {
                    "pk": T.RECEIPT_PK,
                    "sk": f"DATE#{d}",
                    "date": d,
                    "input_rows": [],
                    "computed_at": f"{d}T17:50:01+00:00",
                    "run_id": f"seed-{i}",
                    "public": {"origin": "synthetic"},
                }
            )
    st.seed(
        {
            "pk": T.PFX + "challenges",
            "sk": "CHALLENGE#synthetic-1",
            "status": "completed",
            "completed_at": f"{_d(challenge_day)}T20:00:00+00:00",
            "xp_consumed_at": f"{_d(challenge_day + 1)}T17:51:00+00:00",
            "character_xp_awarded": Decimal(5),
            "domain": "movement",
        }
    )
    return st


def plan_for(store: StubStore, tmp_path, name: str = "out", ladder=TEST_LADDER) -> dict:
    out = tmp_path / name
    out.mkdir(exist_ok=True)
    return T.dry_run(store, str(out), ladder=ladder, trees=TREES, planned_at="2026-11-26T00:00:00+00:00")


def saved_plan(plan: dict, tmp_path) -> dict:
    """The plan as --apply reads it: written, then loaded and integrity-checked."""
    (tmp_path / "out").mkdir(exist_ok=True)
    paths = T.write_outputs(plan, str(tmp_path / "out"))
    return A.load_plan(paths["plan"])


@pytest.fixture(scope="module")
def _seeded_once(tmp_path_factory):
    store = seed_store()
    plan = plan_for(store, tmp_path_factory.mktemp("seeded"))
    return store, plan


@pytest.fixture
def seeded(_seeded_once):
    """A fresh copy per test: the seeded store and its dry-run plan (the ladder runs once per module)."""
    store, plan = _seeded_once
    fresh = StubStore()
    fresh.items = copy.deepcopy(store.items)
    return fresh, copy.deepcopy(plan)


# ── the tests ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_plan_is_deterministic(seeded, tmp_path):
    store, plan = seeded
    again = plan_for(store, tmp_path, "again")
    assert plan["plan_id"] == again["plan_id"]
    assert [r.get("planned_digest") for r in plan["rows"]] == [r.get("planned_digest") for r in again["rows"]]
    assert plan["counts"]["character_sheet"]["rows_read"] == N_DAYS
    assert plan["counts"]["character_sheet"]["rows_to_write"] == N_DAYS  # every seed row carries the retired debt


def test_step_attribution_reconciles_exactly(seeded):
    _store, plan = seeded
    acc = plan["accounting"]
    assert acc["sheet_rows_to_write"] == acc["sheet_rows_with_a_cause"] == plan["counts"]["character_sheet"]["rows_to_write"]
    for r in plan["rows"]:
        if r["pk"] == T.SHEET_PK and r["action"] == "write":
            assert set(r["attribute_causes"]) == set(r["changed_attributes"])
            assert all(r["attribute_causes"][a] for a in r["changed_attributes"]), r["date"]
    # the stale-stress seed dates change Mind at the plan step (Mind re-weighted), the others do not
    stale = {_d(i) for i in range(N_DAYS) if i % 3 == 0}
    mind_changed = {d for d, a in plan["attribution"].items() if "pillar_mind" in a["by_step"].get("missing_data", [])}
    assert stale <= mind_changed
    # per-step totals are the per-date sums
    for cause, t in acc["ladder_totals"].items():
        assert t["attributes"] == sum(len(a["by_step"].get(cause, [])) for a in plan["attribution"].values())


def test_reconcile_refuses_a_change_with_no_cause():
    rows = [
        {
            "pk": T.SHEET_PK,
            "sk": f"DATE#{GENESIS}",
            "date": GENESIS,
            "action": "write",
            "attribute_causes": {"character_level": []},
            "changed_attributes": ["character_level"],
            "causes": [],
        }
    ]
    with pytest.raises(T.PlanGuardError):
        T.reconcile(rows, {}, [("missing_data", {})], {})


def test_reconcile_refuses_a_ladder_that_does_not_end_at_the_plan():
    with pytest.raises(T.PlanGuardError):
        T.reconcile([], {}, [("missing_data", {GENESIS: {"character_level": {"$N": "2"}}})], {GENESIS: {"character_level": {"$N": "3"}}})


def test_source_partitions_guard_is_red_on_a_planted_key(seeded):
    _store, plan = seeded
    T.assert_character_keys(plan["rows"], plan["window"]["start"], plan["window"]["end"])
    planted = copy.deepcopy(plan["rows"][:1])
    planted[0]["pk"] = planted[0]["planned_item"]["pk"] = T.PFX + "whoop"  # a source partition, consistently planted
    with pytest.raises(T.PlanGuardError):
        T.assert_character_keys(planted, plan["window"]["start"], plan["window"]["end"])
    planted = copy.deepcopy(plan["rows"][:1])
    planted[0]["sk"] = planted[0]["planned_item"]["sk"] = "DATE#2020-01-01"  # outside the window
    with pytest.raises(T.PlanGuardError):
        T.assert_character_keys(planted, plan["window"]["start"], plan["window"]["end"])
    planted = copy.deepcopy(plan["rows"][:1])
    planted[0]["planned_item"]["pk"] = T.PFX + "habitify"  # the item itself pointing elsewhere
    with pytest.raises(T.PlanGuardError):
        T.assert_character_keys(planted, plan["window"]["start"], plan["window"]["end"])


def test_dry_run_writes_nothing_and_reads_only_declared_partitions(tmp_path):
    store = seed_store()
    before = copy.deepcopy(store.items)
    plan_for(store, tmp_path)
    assert store.writes == [] and store.s3_writes == [] and store.items == before
    assert set(store.reads) <= set(T.WRITTEN_PARTITIONS) | set(T.READ_ONLY_INPUTS)


def test_apply_writes_only_character_rows_and_backs_up_first(seeded, tmp_path):
    store, plan = seeded
    plan = saved_plan(plan, tmp_path)
    order = []
    real_put, real_backup = store.put, store.put_backup
    store.put = lambda item, cond: (order.append("put"), real_put(item, cond))[1]
    store.put_backup = lambda key, body: (order.append("backup"), real_backup(key, body))[1]
    result = A.apply_plan(store, plan, str(tmp_path / "out"), "all", "2026-11-26T01:00:00+00:00")
    assert order[0] == "backup" and order.count("backup") == 1
    assert {pk for pk, _sk in store.writes} <= set(T.WRITTEN_PARTITIONS)
    assert all(k.startswith(T.BACKUP_PREFIX + "/") for k in store.s3_writes)
    assert result["aborted"] == [] and all(w["verified"] for w in result["written"])
    item = store.get(T.SHEET_PK, f"DATE#{_d(1)}")
    assert item[T.PROVENANCE]["kind"] == T.PROVENANCE_KIND and item[T.PROVENANCE]["plan_id"] == plan["plan_id"]
    assert item["engine_version"] == "1.10.0" and item["computed_at"] == f"{_d(1)}T17:50:00+00:00"  # original timestamp
    assert item["public"] == {"character_level": 1, "origin": "synthetic"}  # the public side's attribute untouched
    assert item["character_xp_debt"] == 0


def test_backup_is_verified_before_the_first_write(seeded, tmp_path):
    store, plan = seeded
    plan = saved_plan(plan, tmp_path)
    store.get_backup = lambda key: b"{}"  # the S3 copy does not read back
    with pytest.raises(T.PlanGuardError):
        A.apply_plan(store, plan, str(tmp_path / "out"), "all", "2026-11-26T01:00:00+00:00")
    assert store.writes == []


def test_a_row_changed_since_the_plan_is_aborted_and_reported(seeded, tmp_path):
    store, plan = seeded
    plan = saved_plan(plan, tmp_path)
    key = (T.SHEET_PK, f"DATE#{_d(2)}")
    store.items[key]["run_id"] = "a-nightly-rewrite"
    result = A.apply_plan(store, plan, str(tmp_path / "out"), "all", "2026-11-26T01:00:00+00:00")
    assert [(a["pk"], a["sk"]) for a in result["aborted"]] == [key]
    assert key not in store.writes and store.items[key]["run_id"] == "a-nightly-rewrite"
    assert (
        len(result["written"])
        == plan["counts"]["character_sheet"]["rows_to_write"] + plan["counts"]["character_receipt"]["rows_to_write"] - 1
    )


def test_the_conditional_write_refuses_a_change_between_read_and_write(seeded, tmp_path):
    store, plan = seeded
    plan = saved_plan(plan, tmp_path)
    real_get = store.get
    calls = {"n": 0}
    target = (T.SHEET_PK, f"DATE#{_d(4)}")

    def racing_get(pk, sk):  # the nightly rewrites the row right after the tool's pre-write read
        item = real_get(pk, sk)
        if (pk, sk) == target:
            calls["n"] += 1
            if calls["n"] == 2:
                store.items[target]["computed_at"] = "raced"
        return item

    store.get = racing_get
    result = A.apply_plan(store, plan, str(tmp_path / "out"), "sheets", "2026-11-26T01:00:00+00:00")
    assert any((a["pk"], a["sk"]) == target and "conditional" in a["reason"] for a in result["aborted"])
    assert target not in store.writes


def test_reapplying_the_same_plan_writes_nothing(seeded, tmp_path):
    store, plan = seeded
    plan = saved_plan(plan, tmp_path)
    A.apply_plan(store, plan, str(tmp_path / "out"), "all", "2026-11-26T01:00:00+00:00")
    n = len(store.writes)
    again = A.apply_plan(store, plan, str(tmp_path / "out"), "all", "2026-11-26T02:00:00+00:00")
    assert len(store.writes) == n and again["written"] == [] and again["aborted"] == []


def test_resume_by_limit_then_rest(seeded, tmp_path):
    store, plan = seeded
    plan = saved_plan(plan, tmp_path)
    first = A.apply_plan(store, plan, str(tmp_path / "out"), "sheets", "2026-11-26T01:00:00+00:00", limit=3)
    assert len(first["written"]) == 3
    rest = A.apply_plan(store, plan, str(tmp_path / "out"), "sheets", "2026-11-26T02:00:00+00:00")
    assert len(rest["written"]) == plan["counts"]["character_sheet"]["rows_to_write"] - 3 and rest["aborted"] == []


def test_verify_is_zero_write_after_apply(seeded, tmp_path):
    store, plan = seeded
    pending = A.verify(store, str(tmp_path / "out"), trees=TREES)
    assert pending["planned_writes"] > 0
    A.apply_plan(store, saved_plan(plan, tmp_path), str(tmp_path / "out"), "all", "2026-11-26T01:00:00+00:00")
    writes = list(store.writes)
    done = A.verify(store, str(tmp_path / "out"), trees=TREES)
    assert done["planned_writes"] == 0, done["pending"]
    assert store.writes == writes  # verify wrote nothing


def test_verify_cli_exits_non_zero_with_pending_writes(seeded, tmp_path, monkeypatch):
    store, _plan = seeded
    monkeypatch.setattr(T, "live_store", lambda writable: store)
    monkeypatch.setattr(A, "verify", lambda st, out, start, end: {"rows": 1, "planned_writes": 2, "pending": ["x", "y"]})
    assert T.main(["--out", str(tmp_path / "cli"), "--verify"]) == 1
    monkeypatch.setattr(A, "verify", lambda st, out, start, end: {"rows": 1, "planned_writes": 0, "pending": []})
    assert T.main(["--out", str(tmp_path / "cli"), "--verify"]) == 0


@pytest.mark.parametrize("limit", [None, 4])
def test_rollback_restores_every_preimage_byte_for_byte(seeded, tmp_path, limit):
    store, plan = seeded
    pre = copy.deepcopy(store.items)
    result = A.apply_plan(store, saved_plan(plan, tmp_path), str(tmp_path / "out"), "all", "2026-11-26T01:00:00+00:00", limit=limit)
    assert store.items != pre
    dry = A.rollback(store, result["export"], apply=False)
    assert dry["refused"] == [] and store.items != pre
    done = A.rollback(store, result["export"], apply=True)
    assert done["refused"] == [] and done["verified"]["mismatches"] == []
    assert {k: T.canonical(T.to_typed(v)) for k, v in store.items.items()} == {k: T.canonical(T.to_typed(v)) for k, v in pre.items()}


def test_rollback_refuses_a_row_changed_after_the_apply(seeded, tmp_path):
    store, plan = seeded
    result = A.apply_plan(store, saved_plan(plan, tmp_path), str(tmp_path / "out"), "sheets", "2026-11-26T01:00:00+00:00")
    key = (T.SHEET_PK, f"DATE#{_d(5)}")
    store.items[key]["public"] = {"origin": "the public apply ran after"}
    done = A.rollback(store, result["export"], apply=True)
    assert [(r["pk"], r["sk"]) for r in done["refused"]] == [key]
    assert store.items[key]["public"] == {"origin": "the public apply ran after"}
    assert f"{key[0]} {key[1]}" in done["verified"]["mismatches"]


def test_rollback_refuses_an_edited_export(seeded, tmp_path):
    store, plan = seeded
    result = A.apply_plan(store, saved_plan(plan, tmp_path), str(tmp_path / "out"), "sheets", "2026-11-26T01:00:00+00:00")
    with open(result["export"], "a", encoding="utf-8") as fh:
        fh.write(" ")
    with pytest.raises(T.PlanGuardError):
        A.rollback(store, result["export"], apply=True)


def test_consumed_challenge_xp_is_carried_forward(seeded):
    _store, plan = seeded
    d = _d(3)
    row = next(r for r in plan["rows"] if r["pk"] == T.SHEET_PK and r["date"] == d)
    planned = T.as_float(row["planned_item"])
    assert planned["challenge_bonus_xp"] == {"movement": 5}
    assert planned["pillar_movement"]["challenge_bonus_xp"] == 5
    prev = T.as_float(next(r for r in plan["rows"] if r["pk"] == T.SHEET_PK and r["date"] == _d(2))["planned_item"])
    assert planned["pillar_movement"]["xp_total"] >= prev["pillar_movement"]["xp_total"] + 5
    ch = plan["challenge_xp"]
    assert ch["planned_carries_stored"] is True and ch["stored_matches_consumed"] == 1 and ch["stored_differs"] == []


def test_no_event_or_notification_write_exists():
    src = "".join(
        open(os.path.join(ROOT, "scripts", f), encoding="utf-8").read()
        for f in (
            "recompute_character_private.py",
            "recompute_character_private_apply.py",
            "recompute_character_private_report.py",
            "recompute_character_private_replay.py",
        )
    )
    for forbidden in ("read_announced_events", "record_event", "send_email", "ses", "sns", "publish_site_stats", "write_character_stats"):
        assert f"{forbidden}(" not in src and f".{forbidden}" not in src, forbidden
    assert "activity_publication" not in src  # the tool reads no publication set (#6283 may move it)


def test_events_are_reported_never_written(seeded, tmp_path):
    store, plan = seeded
    assert plan["events"]["writes_events"] is False
    assert set(plan["events"]["events"]["totals"]) <= {"character", "sleep", "movement", "nutrition", "metabolic", "mind", "consistency"}
    A.apply_plan(store, saved_plan(plan, tmp_path), str(tmp_path / "out"), "all", "2026-11-26T01:00:00+00:00")
    assert {pk for pk, _ in store.writes} <= set(T.WRITTEN_PARTITIONS)


def test_the_private_apply_changes_nothing_a_reader_is_served(seeded):
    _store, plan = seeded
    assert plan["served_baseline"] and all(v["unchanged_by_private_apply"] for v in plan["served_baseline"].values())


def test_an_output_path_inside_the_repo_is_refused(tmp_path):
    with pytest.raises(T.PlanGuardError):
        T.refuse_in_repo(os.path.join(ROOT, "tmp-out"))
    with pytest.raises(T.PlanGuardError):
        T.refuse_in_repo(ROOT)
    with pytest.raises(T.PlanGuardError):
        T.main(["--out", os.path.join(ROOT, "tmp-out")])
    assert T.refuse_in_repo(str(tmp_path)) == os.path.realpath(str(tmp_path))
    assert not os.path.exists(os.path.join(ROOT, "tmp-out"))


def test_a_float_never_reaches_a_write_and_the_typed_codec_round_trips():
    with pytest.raises(TypeError):
        T.to_typed({"x": 1.5})
    item = {"pk": "p", "sk": "s", "n": Decimal("80.0"), "m": {"a": [Decimal("0.1250"), True, None, "t"]}}
    typed = T.to_typed(item)
    assert typed["n"] == {"$N": "80"} and T.from_typed(typed) == {
        "pk": "p",
        "sk": "s",
        "n": Decimal("80"),
        "m": {"a": [Decimal("0.125"), True, None, "t"]},
    }
    with pytest.raises(T.PlanGuardError):
        T.to_typed({"m": {"$N": "1"}})


def test_the_plan_file_is_integrity_checked(seeded, tmp_path):
    _store, plan = seeded
    (tmp_path / "out").mkdir(exist_ok=True)
    paths = T.write_outputs(plan, str(tmp_path / "out"))
    data = json.load(open(paths["plan"], encoding="utf-8"))
    assert "_stored" not in data["rows"][0] and "_owned" not in data["rows"][0]
    w = next(r for r in data["rows"] if r["action"] == "write")
    w["planned_item"]["character_level"] = {"$N": "99"}
    with open(paths["plan"], "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    with pytest.raises(T.PlanGuardError):
        A.load_plan(paths["plan"])


def test_condition_spec_renders_as_dynamodb_expression():
    out = T.ddb_condition(
        [("exists", "pk"), ("eq", "computed_at", "c"), ("not_exists", T.PROVENANCE), ("eq", [T.PROVENANCE, "plan_id"], "p")]
    )
    assert out["ConditionExpression"] == "attribute_exists(#n0) AND #n1 = :v0 AND attribute_not_exists(#n2) AND #n3.#n4 = :v1"
    assert out["ExpressionAttributeNames"] == {
        "#n0": "pk",
        "#n1": "computed_at",
        "#n2": T.PROVENANCE,
        "#n3": T.PROVENANCE,
        "#n4": "plan_id",
    }
    assert out["ExpressionAttributeValues"] == {":v0": "c", ":v1": "p"}


def test_read_only_proxy_refuses_every_write_verb():
    class Inner:
        def get_item(self, **kw):
            return {}

    proxy = T.ReadOnlyProxy(Inner(), T.WRITE_VERBS)
    assert proxy.get_item(Key={}) == {}
    for verb in T.WRITE_VERBS:
        with pytest.raises(RuntimeError):
            getattr(proxy, verb)


def test_the_real_ladder_names_every_method_cause_in_order():
    causes = [c for _n, c, _s in T.LADDER]
    assert [c for c in causes if c in T.METHOD_CAUSES] == list(T.METHOD_CAUSES[:5]) + ["relationships_exclusion", "missing_data"]
    assert causes[0] == "replay_residual" and "tree_switch_residual" in causes
    assert T.LADDER[-1][2] is T.PLAN_SPEC and set(T.CAUSES_LEGEND) >= set(causes) | set(T.STAMP_CAUSES)


def test_planned_sheets_reader_gives_the_public_side_the_stored_shape(seeded, tmp_path):
    _store, plan = seeded
    (tmp_path / "out").mkdir(exist_ok=True)
    path = T.write_outputs(plan, str(tmp_path / "out"))["plan"]
    sheets = A.planned_sheets(path)
    assert sorted(sheets) == [_d(i) for i in range(N_DAYS)]
    one = sheets[_d(1)]
    assert isinstance(one["character_level"], float) and one["engine_version"] == "1.10.0"
    assert one["public"] == {"character_level": 1.0, "origin": "synthetic"}
    assert one["pillar_relationships"].get("not_instrumented") is True and "raw_score" not in one["pillar_relationships"]
    assert one[T.PROVENANCE]["kind"] == T.PROVENANCE_KIND
