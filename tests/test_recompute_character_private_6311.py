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
_STEP1 = {"tree": "new", "rebuild": ["movement", "nutrition"], "loader": "held_skip", "relationships": "engine"}
TEST_LADDER = (
    ("fidelity", "replay_residual", _STEP1),
    ("switch", "tree_switch_residual", dict(_STEP1)),  # a control: the same method again, so it must change nothing
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

    versioning = "Enabled"

    def list_backups(self, prefix):
        return sorted(k for k in self.objects if k.startswith(prefix))

    def bucket_versioning(self):
        return self.versioning

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


SICK_DAY = 7  # a sick-day freeze row: a verbatim copy of day 6, a stale-stress day (6 % 3 == 0)


def seed_store(n: int = N_DAYS, receipts: bool = True, challenge_day: int = 3) -> StubStore:
    cfg = _cfg()
    st = StubStore()
    prev_rec: dict = {}
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
        if i == SICK_DAY:  # the compute's freeze: the previous record copied, re-dated, flagged
            rec = dict(copy.deepcopy(prev_rec), sk=f"DATE#{d}", date=d, sick_day=True, sick_day_reason="synthetic", frozen_from=_d(i - 1))
        prev_rec = rec
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


RAW_NONE = {"effects": {}, "reads": {}}


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
    assert [c for c in causes if c in T.METHOD_CAUSES] == list(T.METHOD_CAUSES)
    assert causes == [
        "replay_residual",
        "stress_days",
        "journal_frequency",
        "model_values",
        "xp_debt",
        "rest_decay",
        "tree_switch_residual",
        "relationships_exclusion",
        "missing_data",
        "final_switch_residual",
        "planned_rest",
        "lab_ageing",
        "rest_day_completeness",
        "mood_label_presence",
    ]
    assert T.LADDER[-1][2] is T.PLAN_SPEC and set(T.CAUSES_LEGEND) >= set(causes) | set(T.STAMP_CAUSES)
    assert set(T.CONTROL_CAUSES) == {"tree_switch_residual", "final_switch_residual"}
    specs = {c: spec for _n, c, spec in T.LADDER}
    assert specs["missing_data"]["tree"] == "amended" and specs["final_switch_residual"].get("switches") == []
    assert specs["mood_label_presence"]["switches"] == list(T._SWITCHES) and specs["mood_label_presence"]["effects"] == list(T._EFFECTS)


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


def test_a_sick_day_freeze_copy_of_a_stale_stress_day_counts_and_is_rewritten(seeded):
    _store, plan = seeded
    sd = plan["stress_days"]
    stale = sorted({_d(i) for i in range(N_DAYS) if i % 3 == 0} | {_d(SICK_DAY)})
    assert sd["stored_with_stress"] == stale
    assert sd["sick_day_frozen_copies"] == [_d(SICK_DAY)]
    assert "sick-day freeze copy included" in sd["definition"]
    row = next(r for r in plan["rows"] if r["pk"] == T.SHEET_PK and r["date"] == _d(SICK_DAY))
    prev = next(r for r in plan["rows"] if r["pk"] == T.SHEET_PK and r["date"] == _d(SICK_DAY - 1))
    assert row["action"] == "write"
    planned, planned_prev = T.as_float(row["planned_item"]), T.as_float(prev["planned_item"])
    assert planned["sick_day"] is True and planned["frozen_from"] == _d(SICK_DAY - 1)  # the freeze fields kept as stored
    assert planned["pillar_mind"] == planned_prev["pillar_mind"]  # the copy follows the RECOMPUTED previous day
    assert planned["pillar_mind"]["components"]["stress_management"].get("held_out") is True


def test_planned_receipts_reader_uses_the_planned_sheets_convention(seeded, tmp_path):
    _store, plan = seeded
    (tmp_path / "out").mkdir(exist_ok=True)
    path = T.write_outputs(plan, str(tmp_path / "out"))["plan"]
    receipts = A.planned_receipts(path)
    assert sorted(receipts) == [_d(i) for i in range(N_DAYS) if i % 2 == 0 and i != SICK_DAY]
    one = receipts[_d(0)]
    assert one["pk"] == T.RECEIPT_PK and one["engine_version"] == "1.10.0" and isinstance(one["receipt_schema_version"], float)
    assert one["public"] == {"origin": "synthetic"} and one[T.PROVENANCE]["kind"] == T.PROVENANCE_KIND


def test_ladder_states_reconcile_to_the_plan_and_the_control_equals_its_predecessor(seeded, tmp_path):
    import recompute_character_private_report as R

    _store, plan = seeded
    (tmp_path / "out").mkdir(exist_ok=True)
    path = T.write_outputs(plan, str(tmp_path / "out"))["plan"]
    states = A.ladder_states(path)
    assert list(states) == [c for _n, c, _s in TEST_LADDER]
    sheets = A.planned_sheets(path)
    assert states["missing_data"] == {d: R.chain_state(sheets[d]) for d in sorted(sheets)}  # the last step IS the plan
    assert states["tree_switch_residual"] == states["replay_residual"]  # the control changes nothing
    one = states["missing_data"][_d(1)]
    assert set(one) == {"character_level", "character_xp", "composite", "pillars", "events"}
    assert one["pillars"]["relationships"] == {"raw_score": None, "level": None}
    assert set(one["pillars"]) == set(R.STATE_PILLARS)
    # the ablation question the public side asks: at which step did a value first change?
    changed = [
        c
        for prev, c in zip(list(states), list(states)[1:])
        if states[prev][_d(0)]["pillars"]["mind"] != states[c][_d(0)]["pillars"]["mind"]
    ]
    assert changed == ["missing_data"]  # day 0 is a stale-stress seed: Mind moves when it is re-weighted


def test_ladder_states_reader_refuses_a_plan_without_them(seeded, tmp_path):
    _store, plan = seeded
    (tmp_path / "out").mkdir(exist_ok=True)
    old = {k: v for k, v in plan.items() if k != "ladder_states"}
    path = T.write_outputs(old, str(tmp_path / "out"))["plan"]
    assert A.planned_sheets(path)  # an older plan still reads (the field is additive)
    with pytest.raises(T.PlanGuardError):
        A.ladder_states(path)


def test_stored_states_are_the_baseline_replay_residual_is_measured_from(seeded, tmp_path):
    import recompute_character_private_report as R

    store, plan = seeded
    (tmp_path / "out").mkdir(exist_ok=True)
    path = T.write_outputs(plan, str(tmp_path / "out"))["plan"]
    stored = A.stored_states(path)
    raw = {d: T.as_float(T.to_typed(store.get(T.SHEET_PK, f"DATE#{d}"))) for d in stored}
    assert stored == {d: R.chain_state(raw[d]) for d in sorted(raw)}
    first = A.ladder_states(path)["replay_residual"]
    by_step = {d: set(a["by_step"].get("replay_residual", [])) for d, a in plan["attribution"].items()}
    for d in stored:  # a state difference exists exactly where replay_residual changed the attribute behind it
        assert (stored[d]["character_level"] != first[d]["character_level"]) == ("character_level" in by_step[d]), d
        assert (stored[d]["character_xp"] != first[d]["character_xp"]) == ("character_xp" in by_step[d]), d
        for p in R.STATE_PILLARS:
            if stored[d]["pillars"][p] != first[d]["pillars"][p]:
                assert f"pillar_{p}" in by_step[d], (d, p)
    assert any(stored[d] != first[d] for d in stored)  # the seed's retired debt and missing chain fields do differ


def test_stored_states_reader_refuses_a_plan_without_them(seeded, tmp_path):
    _store, plan = seeded
    (tmp_path / "out").mkdir(exist_ok=True)
    path = T.write_outputs({k: v for k, v in plan.items() if k != "stored_states"}, str(tmp_path / "out"))["plan"]
    assert A.ladder_states(path)  # the other readers still work
    with pytest.raises(T.PlanGuardError):
        A.stored_states(path)


# ── final-state equality, stress accounting, exact-plan approval, preflight ────────────────────────────────────────


def _plan_path(plan, tmp_path):
    (tmp_path / "out").mkdir(parents=True, exist_ok=True)
    return T.write_outputs(plan, str(tmp_path / "out"))["plan"]


def test_planned_states_are_computed_from_the_planned_items_and_equal_the_last_step(seeded, tmp_path):
    import recompute_character_private_report as R

    _store, plan = seeded
    path = _plan_path(plan, tmp_path)
    planned = A.planned_states(path)
    sheets = A.planned_sheets(path)
    assert planned == {d: R.chain_state(sheets[d]) for d in sorted(sheets)}
    assert planned == A.ladder_states(path)["missing_data"]  # every field, composite included
    assert all(v["composite"] is not None for v in planned.values())
    with pytest.raises(T.PlanGuardError):
        A.planned_states(_plan_path({k: v for k, v in plan.items() if k != "planned_states"}, tmp_path))


def test_a_corrupted_composite_fails_the_final_state_check(seeded):
    import recompute_character_private_report as R

    _store, plan = seeded
    R.check_final_state(plan["ladder_states"], plan["planned_states"])  # the real plan passes
    bad = copy.deepcopy(plan["planned_states"])
    bad[_d(4)]["composite"] = (bad[_d(4)]["composite"] or 0) + 0.1
    with pytest.raises(T.PlanGuardError, match="composite"):
        R.check_final_state(plan["ladder_states"], bad)


def test_the_dry_run_itself_refuses_when_the_final_composite_disagrees(tmp_path, monkeypatch):
    import recompute_character_private_report as R

    real = R.ladder_states

    def corrupt(ladder_f):
        out = real(ladder_f)
        last = out[list(out)[-1]]
        last[_d(2)] = dict(last[_d(2)], composite=(last[_d(2)]["composite"] or 0) + 1.0)
        return out

    monkeypatch.setattr(R, "ladder_states", corrupt)
    with pytest.raises(T.PlanGuardError, match="composite"):
        plan_for(seed_store(), tmp_path, "corrupt")


def test_stress_days_are_distinct_add_up_and_are_all_planned_writes(seeded):
    import recompute_character_private_report as R

    _store, plan = seeded
    acc = plan["stress_days"]["accounting"]
    assert acc == {"dates": 5, "distinct": 5, "computed_days": 4, "sick_day_frozen_copies": 1, "planned_writes": 5}
    sd = copy.deepcopy(plan["stress_days"])
    sd["stored_with_stress"].append(sd["stored_with_stress"][0])  # a planted duplicate
    with pytest.raises(T.PlanGuardError, match="twice"):
        R.check_stress_days(sd, plan["rows"])
    sd = copy.deepcopy(plan["stress_days"])
    sd["computed_days"] = sd["computed_days"][1:]  # one day unaccounted
    with pytest.raises(T.PlanGuardError, match="make up"):
        R.check_stress_days(sd, plan["rows"])
    rows = [dict(r, action="unchanged") if r["date"] == _d(0) and r["pk"] == T.SHEET_PK else r for r in plan["rows"]]
    with pytest.raises(T.PlanGuardError, match="planned write"):
        R.check_stress_days(plan["stress_days"], rows)


def test_approval_requires_the_exact_plan_id():
    plan = {"plan_id": "abc123"}
    assert "needs --approved-plan-id" in A.check_approval(None, plan)
    assert "not this plan file" in A.check_approval("zzz", plan)
    assert "re-derived" in A.check_approval("abc123", plan, "def456")
    assert A.check_approval("abc123", plan) is None and A.check_approval("abc123", plan, "abc123") is None


@pytest.mark.parametrize(
    "approved, live_id, expect_apply", [(None, None, False), ("wrong", None, False), ("SAME", "other", False), ("SAME", "SAME", True)]
)
def test_apply_cli_refuses_without_the_exact_approval_before_any_backup_or_write(
    seeded, tmp_path, monkeypatch, approved, live_id, expect_apply
):
    store, plan = seeded
    path = _plan_path(plan, tmp_path)
    pid = plan["plan_id"]
    calls = {"dry_run": 0, "apply": 0}

    def fake_dry_run(*_a, **_k):
        calls["dry_run"] += 1
        return dict(plan, plan_id=pid if live_id == "SAME" else "f" * 16)

    def fake_apply(*_a, **_k):
        calls["apply"] += 1
        return {"written": [], "aborted": [], "export": "x"}

    monkeypatch.setattr(T, "live_store", lambda writable: store)
    monkeypatch.setattr(T, "dry_run", fake_dry_run)
    monkeypatch.setattr(A, "apply_plan", fake_apply)
    argv = ["--out", str(tmp_path / "cli"), "--apply", "--plan-in", path]
    if approved:
        argv += ["--approved-plan-id", pid if approved == "SAME" else approved]
    rc = T.main(argv)
    assert (calls["apply"] == 1) is expect_apply
    assert rc == (0 if expect_apply else 4)
    if approved in (None, "wrong"):
        assert calls["dry_run"] == 0  # refused before even the read-back
    assert store.writes == [] and store.s3_writes == []


def test_preflight_is_read_only_and_names_what_it_cannot_prove(seeded, tmp_path):
    store, plan = seeded
    ok = A.preflight(store, plan)
    assert ok["ok"] is True and ok["verified_read_only"]["bucket_versioning"] == "Enabled"
    assert ok["verified_read_only"]["no_backup_under_prefix_yet"] is True and ok["unverifiable_without_a_write"]
    store.objects[f"{T.BACKUP_PREFIX}/{plan['plan_id']}/all-x/export.json"] = b"{}"
    assert A.preflight(store, plan)["ok"] is False
    store.objects.clear()
    store.versioning = "Suspended"
    assert A.preflight(store, plan)["ok"] is False
    assert store.writes == [] and store.s3_writes == []


def test_apply_plan_rechecks_a_given_approval_before_the_export(seeded, tmp_path):
    store, plan = seeded
    plan = saved_plan(plan, tmp_path)
    with pytest.raises(T.PlanGuardError):
        A.apply_plan(store, plan, str(tmp_path / "out"), "all", "2026-11-26T01:00:00+00:00", approved_plan_id="0" * 16)
    assert store.writes == [] and store.s3_writes == []
    done = A.apply_plan(store, plan, str(tmp_path / "out"), "all", "2026-11-26T01:00:00+00:00", approved_plan_id=plan["plan_id"])
    assert done["written"] and done["aborted"] == []


# ── the four final causes: raw-input effects as on/off DIFFERENCES ───────────────────────────────────────────────


_FINAL_BASE = {"tree": "new", "rebuild": ["movement", "nutrition", "mind"], "loader": "held_skip", "relationships": "engine"}
FINAL_LADDER = (
    ("fidelity", "replay_residual", _STEP1),
    ("md", "missing_data", dict(_FINAL_BASE)),
    ("final0", "final_switch_residual", dict(_FINAL_BASE, switches=[])),
    ("prest", "planned_rest", dict(_FINAL_BASE, switches=list(T._SWITCHES[:1]), effects=["planned_rest"])),
    ("lab", "lab_ageing", dict(_FINAL_BASE, switches=list(T._SWITCHES[:2]), effects=["planned_rest", "lab_ageing"])),
    ("comp", "rest_day_completeness", dict(_FINAL_BASE, switches=list(T._SWITCHES[:3]), effects=list(T._EFFECTS))),
    ("plan", "mood_label_presence", T.PLAN_SPEC),
)
REST_DAY, COMP_DAY = 5, 8


def _same(score):
    return {c: score for c in ce.MOVEMENT_WINDOW_COMPONENTS}


def drift_only_effects(n=N_DAYS):
    """Raw recompute values that DIFFER from the stored ones (drift) but agree between the switch states: no effect."""
    eff = {}
    for i in range(n):
        if i == SICK_DAY:
            continue
        eff[_d(i)] = {
            "movement": {"days": 1 if i == REST_DAY else 0, "off": _same(11.0 + i), "on": _same(11.0 + i)},
            "metabolic": {"off": {"lab_score": 33.0, "evidence_weight": None}, "on": {"lab_score": 33.0, "evidence_weight": None}},
            "completeness": {"off": 20.0 + i, "on": 20.0 + i},
        }
    return {"effects": eff, "reads": {}}


def real_effects(n=N_DAYS):
    eff = drift_only_effects(n)
    eff["effects"][_d(REST_DAY)]["movement"]["on"] = _same(2 * (11.0 + REST_DAY))  # proration doubles the window scores
    eff["effects"][_d(COMP_DAY)]["completeness"]["on"] = 20.0 + COMP_DAY + 20.0  # a rest day leaves the denominator
    return eff


class EffectStore(StubStore):
    effects: dict = {"effects": {}, "reads": {}}

    def raw_effects_for(self, snap):
        return copy.deepcopy(self.effects)


def effect_store(effects) -> EffectStore:
    st = EffectStore()
    st.items = seed_store().items
    st.effects = effects
    return st


@pytest.fixture(scope="module")
def final_plans(tmp_path_factory):
    out = tmp_path_factory.mktemp("final")
    none = T.dry_run(
        effect_store({"effects": {}, "reads": {}}),
        str(out / "none"),
        ladder=FINAL_LADDER,
        trees=TREES,
        planned_at="2026-11-26T00:00:00+00:00",
    )
    drift = T.dry_run(
        effect_store(drift_only_effects()), str(out / "drift"), ladder=FINAL_LADDER, trees=TREES, planned_at="2026-11-26T00:00:00+00:00"
    )
    real = T.dry_run(
        effect_store(real_effects()), str(out / "real"), ladder=FINAL_LADDER, trees=TREES, planned_at="2026-11-26T00:00:00+00:00"
    )
    return none, drift, real


def test_a_raw_input_difference_with_the_switch_off_contributes_nothing(final_plans):
    none, drift, _real = final_plans
    assert [r.get("planned_compare_digest") for r in drift["rows"]] == [r.get("planned_compare_digest") for r in none["rows"]]
    assert drift["plan_id"] == none["plan_id"]
    assert all(not v for v in drift["raw_effects"]["applied_by_step"].values())
    assert drift["raw_effects"]["dates_with_on_off_difference"] == {"planned_rest": [], "lab_ageing": [], "rest_day_completeness": []}


def test_the_raw_dependent_steps_apply_only_their_on_off_difference(final_plans):
    none, _drift, real = final_plans
    assert real["raw_effects"]["dates_with_on_off_difference"] == {
        "planned_rest": [_d(REST_DAY)],
        "lab_ageing": [],
        "rest_day_completeness": [_d(COMP_DAY)],
    }
    assert real["raw_effects"]["applied_by_step"]["planned_rest"] == {_d(REST_DAY): ["planned_rest"]}
    tot = real["accounting"]["ladder_totals"]
    assert tot["final_switch_residual"]["attributes"] == 0 and tot["lab_ageing"]["attributes"] == 0
    assert tot["planned_rest"]["dates"] >= 1 and tot["rest_day_completeness"]["dates"] >= 1
    first = {c: s for c, s in real["ladder_states"].items()}
    assert first["planned_rest"][_d(REST_DAY)]["pillars"]["movement"] != first["final_switch_residual"][_d(REST_DAY)]["pillars"]["movement"]
    # the stored window scores are SCALED by on/off (x2 here, capped at 100), never replaced by the raw value
    by_none = {r["date"]: T.as_float(r["planned_item"]) for r in none["rows"] if r["pk"] == T.SHEET_PK}
    by_real = {r["date"]: T.as_float(r["planned_item"]) for r in real["rows"] if r["pk"] == T.SHEET_PK}
    mv0, mv1 = by_none[_d(REST_DAY)]["pillar_movement"]["components"], by_real[_d(REST_DAY)]["pillar_movement"]["components"]
    for c in ce.MOVEMENT_WINDOW_COMPONENTS:
        if (mv0.get(c) or {}).get("score") is not None and not mv0[c].get("absent"):
            assert mv1[c]["score"] == min(100.0, round(mv0[c]["score"] * 2, 1)), c
    c0 = by_none[_d(COMP_DAY)]["pillar_consistency"]["components"]["data_completeness"]["score"]
    c1 = by_real[_d(COMP_DAY)]["pillar_consistency"]["components"]["data_completeness"]["score"]
    assert c1 == min(100.0, c0 + 20.0)


def test_planned_sheets_let_the_public_side_restore_a_planned_rest_day_unprorated(final_plans, tmp_path):
    from health import character_public

    none, _drift, real = final_plans
    p_none, p_real = _plan_path(none, tmp_path / "a"), _plan_path(real, tmp_path / "b")
    mv_none, mv_real = A.planned_sheets(p_none)[_d(REST_DAY)]["pillar_movement"], A.planned_sheets(p_real)[_d(REST_DAY)]["pillar_movement"]
    rest = mv_real["components"]["_planned_rest"]
    assert rest["days"] == 1 and rest["pre_rest_raw"] == mv_none["raw_score"]
    raw, det = character_public.without_private_modifiers(mv_real["raw_score"], mv_real["components"])
    assert raw == mv_none["raw_score"] and "_planned_rest" not in det
    assert "_planned_rest" not in A.planned_sheets(p_real)[_d(REST_DAY + 1)]["pillar_movement"]["components"]


def test_the_final_switch_control_and_mood_report(final_plans):
    _none, _drift, real = final_plans
    assert real["accounting"]["ladder_totals"]["final_switch_residual"] == {"dates": 0, "attributes": 0, "leaves": 0}
    ml = real["mood_labels"]
    assert set(ml) >= {"stored_labels_rewritten", "stored_to_planned", "stored_dormant", "planned_labels", "moved_by_mood_step"}
    assert "dormant" not in ml["planned_labels"]


def test_effects_are_not_applied_twice_after_an_apply(final_plans, tmp_path):
    _none, _drift, real = final_plans
    st = effect_store(real_effects())
    A.apply_plan(
        st, saved_plan(real, tmp_path), str(tmp_path / "out"), "all", "2026-11-26T01:00:00+00:00", approved_plan_id=real["plan_id"]
    )
    done = A.verify(st, str(tmp_path / "out"), trees=TREES)
    assert done["planned_writes"] == 0, done["pending"]


# ── an interrupted (or phased) apply: ONE pre-image per plan; resume completes against it, or stops for rollback ──


def test_a_partial_apply_resumes_against_the_original_preimage_never_a_second(seeded, tmp_path):
    store, plan = seeded
    plan = saved_plan(plan, tmp_path)
    pre = copy.deepcopy(store.items)
    first = A.apply_plan(store, plan, str(tmp_path / "out"), "sheets", "2026-11-26T01:00:00+00:00", limit=3)
    assert len(first["written"]) == 3 and first["resumed"] is False and len(store.s3_writes) == 1
    body = store.objects[A.backup_key(plan["plan_id"])]
    second = A.apply_plan(store, plan, str(tmp_path / "out"), "all", "2026-11-26T02:00:00+00:00")
    assert second["resumed"] is True and second["aborted"] == []
    assert len(store.s3_writes) == 1 and store.objects[A.backup_key(plan["plan_id"])] == body  # never a second pre-image
    n_write = sum(1 for r in plan["rows"] if r["action"] == "write")
    assert len(first["written"]) + len(second["written"]) == n_write
    assert A.verify(store, str(tmp_path / "out"), trees=TREES)["planned_writes"] == 0
    done = A.rollback(store, second["export"], apply=True)  # the ONE export rolls back the whole plan
    assert done["refused"] == [] and done["verified"]["mismatches"] == []
    assert {k: T.canonical(T.to_typed(v)) for k, v in store.items.items()} == {k: T.canonical(T.to_typed(v)) for k, v in pre.items()}


def test_a_resume_after_an_outside_write_stops_and_directs_to_rollback(seeded, tmp_path):
    store, plan = seeded
    plan = saved_plan(plan, tmp_path)
    A.apply_plan(store, plan, str(tmp_path / "out"), "sheets", "2026-11-26T01:00:00+00:00", limit=2)
    key = (T.SHEET_PK, f"DATE#{_d(0)}")  # written by the first run, then touched by something else
    store.items[key]["run_id"] = "outside"
    writes = list(store.writes)
    with pytest.raises(T.PlanGuardError, match="--rollback"):
        A.apply_plan(store, plan, str(tmp_path / "out"), "all", "2026-11-26T02:00:00+00:00")
    assert store.writes == writes and len(store.s3_writes) == 1


def test_a_resume_refuses_a_local_export_that_differs_from_the_s3_preimage(seeded, tmp_path):
    store, plan = seeded
    plan = saved_plan(plan, tmp_path)
    first = A.apply_plan(store, plan, str(tmp_path / "out"), "sheets", "2026-11-26T01:00:00+00:00", limit=1)
    with open(first["export"], "ab") as fh:
        fh.write(b" ")
    with pytest.raises(T.PlanGuardError, match="differs from the S3 pre-image"):
        A.apply_plan(store, plan, str(tmp_path / "out"), "all", "2026-11-26T02:00:00+00:00")


def test_the_approval_rederives_the_original_plan_through_the_preimage_overlay(seeded, tmp_path):
    store, plan = seeded
    plan_file = saved_plan(plan, tmp_path)
    A.apply_plan(store, plan_file, str(tmp_path / "out"), "sheets", "2026-11-26T01:00:00+00:00")  # phase 1 of 2
    plain = plan_for(store, tmp_path, "plain")
    assert plain["plan_id"] != plan["plan_id"]  # the half-applied rows alone re-derive a different plan
    overlay = A.PreimageOverlay(store, A.existing_preimages(store, plan_file))
    out = tmp_path / "overlay"
    out.mkdir()
    again = T.dry_run(overlay, str(out), ladder=TEST_LADDER, trees=TREES, planned_at="2026-11-26T00:00:00+00:00", raw_effects=RAW_NONE)
    assert again["plan_id"] == plan["plan_id"]
    with pytest.raises(RuntimeError):
        overlay.put({}, [])
