"""tests/test_hypothesis_hevy_input_5388.py — the hypothesis engine counts a gym visit once (#5388).

`compute.watch_hypotheses._trailing_volumes` resolves the trailing week through
`training.zone2_minutes.counted_sessions`. The engine's input manifest did not list `hevy`, so the
resolver ran WITHOUT the routine source and one 160-minute visit read 240 `cardio_7d_min` (Hevy's own
Strava push stood for the whole visit, and the watch's ride and the mobility block inside it were
counted again). This file pins, on the #5369 shared fixture (synthetic numbers):

  * the manifest declares `hevy` and the engine's `gather_data` therefore fetches it;
  * `cardio_7d_min` is ALWAYS resolved with the Hevy rows (160, on every date, no per-date switch), with a
    mutation control that drops the Hevy rows (240);
  * the VO2 max hypothesis registered 2026-10-24 is RE-REGISTERED (owner ruling 2026-10-27, option b): the old
    record is closed as superseded with the reason and the successor's id written on it, once however many runs
    see it; the twin is registered as of 2026-10-27, its check reads only dates on or after it, and its test
    spec is the old record's, field for field;
  * `zone2_7d_min` (a different hypothesis, not part of that ruling) keeps its dated cut-over and its
    `series_amendments` stamp, idempotently, never touching the frozen spec;
  * the engine's role already reads the Hevy partition (one table, no LeadingKeys condition).

Clocks are frozen: every date is a literal handed in, `now=` / `pacific_now` are pinned.
"""

from __future__ import annotations

import copy
import datetime as dt
import inspect
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))
for _k, _v in (("TABLE_NAME", "life-platform"), ("S3_BUCKET", "matthew-life-platform"), ("USER_ID", "matthew")):
    os.environ.setdefault(_k, _v)
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import test_gym_visit_one_source_5369 as fx  # noqa: E402 — the #5369 shared fixture
from common import input_manifest as im  # noqa: E402
from compute import watch_hypotheses as wh  # noqa: E402

CUT = wh.HEVY_CUTOVER_DATE
VISIT = 160.0  # the fixture's visit: lift 82 + ride 60 + mobility 18 minutes, each once
NOW = dt.datetime(2026, 11, 1, 19, 0, 20, tzinfo=dt.timezone.utc)  # the engine's next scheduled run, frozen
# The superseded record's test_spec as it is stored live (read-only DDB read, 2026-10-26): the twin must equal it.
V1_SPEC = {
    "condition_metric": "cardio_7d_min",
    "condition_op": "median_split",
    "direction": "higher",
    "lag_days": 1,
    "min_days_per_arm": 5,
    "min_effect": 0.5,
    "outcome_metric": "vo2max",
}


def _days(end: str, n: int = 7):
    e = dt.date.fromisoformat(end)
    return [(e - dt.timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


def _data(with_hevy=True):
    data = {
        "strava": [fx._strava_row(*fx.ALL_STRAVA)],
        "apple_health": [fx._apple_row(fx.APPLE_CYCLING, fx.APPLE_LIFT, fx.APPLE_FLEX)],
    }
    if with_hevy:
        data["hevy"] = [copy.deepcopy(fx.HEVY)]
    return data


def test_the_cut_over_is_a_pacific_day_on_or_after_the_fixture_visit():
    assert len(CUT) == 10 and CUT > fx.DAY, "the corrected input starts after the 2026-10-25 visit's first read"


def test_the_manifest_declares_hevy_and_the_engine_therefore_reads_it(monkeypatch):
    assert "hevy" in im.COMPUTE_INPUTS["hypothesis-engine"]
    import hypothesis_engine_lambda as eng

    requested = []
    monkeypatch.setattr(eng, "query_range", lambda source, s, e: requested.append(source) or [])
    eng.gather_data()
    assert "hevy" in requested


# ── cardio_7d_min: always WITH Hevy, no per-date switch ──────────────────────────────────


def test_a_gym_visit_reads_once_on_every_date_with_no_as_registered_branch():
    dates = _days(CUT, 9)
    vols = wh._trailing_volumes(_data(), dates)
    visit_week = [d for d in dates if "2026-10-25" <= d <= "2026-10-31"]
    assert visit_week and all(vols[d]["cardio_7d_min"] == VISIT for d in visit_week), "the day before the old cut-over too"
    assert vols[dates[-2]]["cardio_7d_min"] == VISIT and vols[CUT]["cardio_7d_min"] == VISIT


def test_mutation_control_dropping_the_hevy_rows_reads_the_visit_twice():
    """The pre-#5388 wire: no `hevy` in the data. Same fixture, same date: 240 for a 160-minute visit."""
    vols = wh._trailing_volumes(_data(with_hevy=False), _days(CUT))
    assert vols[CUT]["cardio_7d_min"] == 240.0


def test_mutation_control_the_cut_over_constant_no_longer_reaches_cardio(monkeypatch):
    """Moving the Zone 2 cut-over out of reach must not bring the as-registered cardio series back."""
    monkeypatch.setattr(wh, "HEVY_CUTOVER_DATE", "2099-01-01")
    assert wh._trailing_volumes(_data(), _days(CUT))[CUT]["cardio_7d_min"] == VISIT


def test_the_zone2_volume_keeps_its_own_dated_cut_over():
    """`zone2_7d_min` is a different hypothesis' condition and is not part of the VO2 ruling: before the date it is the
    as-registered series, from it WITH Hevy. #5390: a Hevy push carrying its own heart rate over a session that holds a
    lift is the lift's heart-rate member with or without the Hevy rows. Over a session holding NO lift (the ride and the
    mobility block only) the push is dropped as the echo once Hevy is read, and there the volume moves at the date."""
    with_h = wh._trailing_volumes(_data(), _days(CUT))[CUT]["zone2_7d_min"]
    without = wh._trailing_volumes(_data(with_hevy=False), _days(CUT))[CUT]["zone2_7d_min"]
    assert with_h == without, "the lift's own heart rate is kept either way (#5390)"
    no_lift = {**copy.deepcopy(fx.HEVY), "exercises": copy.deepcopy(fx.HEVY["exercises"][2:])}
    data = _data()
    data["hevy"] = [no_lift]
    dates = _days(CUT, 9)
    before = wh._trailing_volumes(data, dates)
    day_before = dates[-2]
    assert before[day_before]["zone2_7d_min"] == wh._trailing_volumes(_data(with_hevy=False), dates)[day_before]["zone2_7d_min"]
    assert before[CUT]["zone2_7d_min"] != before[day_before]["zone2_7d_min"]  # the push's zones dropped as the echo from the date
    assert before[day_before]["cardio_7d_min"] == before[CUT]["cardio_7d_min"], "cardio has no step at the date"


def test_add_watch_metrics_carries_the_corrected_volume_onto_the_day_row():
    rows = [{"date": d} for d in _days(CUT)]
    out = wh.add_watch_metrics(rows, _data())
    assert out[-1]["cardio_7d_min"] == VISIT and "cardio_7d_min" not in out[0]


# ── the zone-2 record names its cut-over ──────────────────────────────────────────────────


class _Table:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def update_item(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append(kw)


def _stored(hid, status="pending", **extra):
    hyp = next(h for h in wh.WATCH_HYPOTHESES if h["hypothesis_id"] == hid)
    return {"pk": "USER#matthew#SOURCE#hypotheses", "sk": f"HYPOTHESIS#{hid}", "status": status, **hyp, **extra}


def _v1(status="pending", **extra):
    """The 2026-10-24 VO2 max record as it is stored live (the code no longer seeds it)."""
    return {
        "pk": "USER#matthew#SOURCE#hypotheses",
        "sk": "HYPOTHESIS#2026-10-25T19:00:20.825616+00:00",
        "hypothesis_id": wh.VO2_V1_ID,
        "source": "watch_prereg_4979",
        "status": status,
        "created_at": "2026-10-25T19:00:20.825616+00:00",
        "test_spec": dict(V1_SPEC),
        **extra,
    }


def test_only_the_zone2_record_is_amended_and_the_vo2_record_is_not():
    recs = [
        _v1(),
        _stored("hyp_watch_zone2_cardio_recovery", status="confirming"),
        _stored("hyp_watch_daylight_sleep_onset"),
    ]
    t = _Table()
    done = wh.amend_open_watch_hypotheses(recs, t)
    assert done == ["hyp_watch_zone2_cardio_recovery:hevy_input_5388"]
    (z2,) = t.calls
    (amend,) = z2["ExpressionAttributeValues"][":new"]
    assert amend["effective_from"] == CUT and amend["issue"] == "#5388" and "changed definition" in amend["change"]
    assert amend["metrics"] == ["zone2_7d_min"]
    assert z2["UpdateExpression"].startswith("SET series_amendments = list_append(") and "test_spec" not in z2["UpdateExpression"]


def test_amending_is_idempotent_and_leaves_a_resolved_record_alone():
    t = _Table()
    done = _stored("hyp_watch_zone2_cardio_recovery", series_amendments=[dict(wh.SERIES_AMENDMENTS[0])])
    resolved = _stored("hyp_watch_daylight_sleep_onset", status="confirmed")
    assert wh.amend_open_watch_hypotheses([done, resolved], t) == [] and t.calls == []


def test_a_failed_amendment_is_not_fatal():
    assert wh.amend_open_watch_hypotheses([_stored("hyp_watch_zone2_cardio_recovery")], _Table(fail=True)) == []


def test_the_seed_amends_through_the_table_it_is_given_and_not_without_one():
    recs = [_stored(h["hypothesis_id"]) for h in wh.WATCH_HYPOTHESES]
    t = _Table()
    out = wh.seed_watch_hypotheses(recs, [], lambda *a, **k: (True, []), lambda *a, **k: None, table=t)
    assert out["registered"] == [] and len(out["amended"]) == 1 and len(t.calls) == 1
    assert wh.seed_watch_hypotheses(recs, [], lambda *a, **k: (True, []), lambda *a, **k: None)["amended"] == []


def test_the_engine_hands_the_seed_its_table():
    import hypothesis_engine_lambda as eng

    assert "table=table" in inspect.getsource(eng.lambda_handler).split("seed_watch_hypotheses(")[1].split("\n")[0]


# ── the VO2 max re-registration ───────────────────────────────────────────────────────────


class _Ddb:
    """An in-memory hypotheses partition. `update_item` honours the supersede's ConditionExpression."""

    def __init__(self, items):
        self.items = {i["sk"]: dict(i) for i in items}
        self.updates = []

    def update_item(self, **kw):
        item = self.items[kw["Key"]["sk"]]
        v = kw["ExpressionAttributeValues"]
        if ":new" in v:  # the zone-2 series_amendments stamp
            item["series_amendments"] = [*item.get("series_amendments", []), *v[":new"]]
            self.updates.append(kw)
            return
        if "ConditionExpression" in kw and item["status"] not in (v[":p"], v[":c"]):
            raise _Conditional()
        item.update(
            status=v[":s"], resolution=v[":res"], superseded_by=v[":by"], superseded_effective_from=v[":eff"],
            superseded_reason=v[":why"], superseded_at=v[":at"], last_evidence=v[":why"],
        )  # fmt: skip
        self.updates.append(kw)

    def load(self):
        return [dict(i) for i in self.items.values()]


class _Conditional(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


def _engine_store(ddb, monkeypatch):
    """The REAL store_hypothesis, writing into the in-memory partition."""
    from compute import hypothesis_engine_lambda as eng

    class _T:
        def put_item(self, Item):
            ddb.items[Item["sk"]] = dict(Item)

    monkeypatch.setattr(eng, "table", _T())
    return eng


def _run(ddb, eng):
    """One scheduled run's two watch steps over the partition as it stands: supersede, then seed."""
    all_h, closed = wh.supersede(ddb.load(), ddb, eng.validate_hypothesis, eng.store_hypothesis, now=NOW)
    seed = wh.seed_watch_hypotheses(all_h, [], eng.validate_hypothesis, eng.store_hypothesis, table=ddb)
    return all_h, closed, seed


def _live_partition():
    return _Ddb([_v1(), _stored("hyp_watch_zone2_cardio_recovery"), _stored("hyp_watch_daylight_sleep_onset")])


def _twin(ddb):
    (t,) = [i for i in ddb.items.values() if i.get("hypothesis_id") == wh.VO2_V2_ID]
    return t


def test_the_old_record_closes_once_with_the_reason_and_the_successors_id_on_it(monkeypatch):
    ddb = _live_partition()
    eng = _engine_store(ddb, monkeypatch)
    _, closed, seed = _run(ddb, eng)
    assert closed == [f"{wh.VO2_V1_ID}->{wh.VO2_V2_ID}"] and wh.VO2_V2_ID in {_twin(ddb)["hypothesis_id"]}
    old = ddb.items[_v1()["sk"]]
    assert old["status"] == "archived" and old["resolution"] == "superseded"
    assert old["superseded_by"] == wh.VO2_V2_ID and wh.VO2_V2_ID in old["superseded_reason"]
    assert old["superseded_effective_from"] == "2026-10-27" and old["superseded_at"] == NOW.isoformat()
    assert old["last_evidence"] == old["superseded_reason"] and "re-register" in old["superseded_reason"]
    assert old["test_spec"] == V1_SPEC, "the frozen spec of the closed record is never touched"
    assert seed["skipped"][wh.VO2_V2_ID] == "already_registered" and wh.VO2_V2_ID not in seed["registered"]


def test_the_supersede_is_written_once_across_two_runs(monkeypatch):
    ddb = _live_partition()
    eng = _engine_store(ddb, monkeypatch)
    _run(ddb, eng)
    after_first = copy.deepcopy(ddb.items)
    _, closed, seed = _run(ddb, eng)
    assert closed == [] and seed["registered"] == []
    assert len(ddb.updates) == 1 + 1, "one supersede + one zone-2 amendment, in total, over two runs"
    assert ddb.items.keys() == after_first.keys() and len([i for i in ddb.items.values() if i["hypothesis_id"] == wh.VO2_V2_ID]) == 1
    assert ddb.items[_v1()["sk"]] == after_first[_v1()["sk"]]


def test_a_lost_race_is_benign_and_a_closed_record_is_not_reopened(monkeypatch):
    ddb = _live_partition()
    eng = _engine_store(ddb, monkeypatch)
    ddb.items[_v1()["sk"]]["status"] = "archived"  # another run closed it between our load and our write
    stale = _live_partition().load()
    all_h, closed = wh.supersede(stale, ddb, eng.validate_hypothesis, eng.store_hypothesis, now=NOW)
    assert closed == [] and ddb.updates == [], "the conditional write refused; nothing was overwritten"


def test_the_twin_is_registered_as_of_the_ruling_day_through_the_engines_own_store(monkeypatch):
    ddb = _live_partition()
    eng = _engine_store(ddb, monkeypatch)
    _run(ddb, eng)
    twin = _twin(ddb)
    assert twin["pre_registered_at"] == twin["created_at"] == "2026-10-27T00:00:00-07:00"
    assert twin["pre_registered_at"][:10] == "2026-10-27"
    assert dt.datetime.fromisoformat(twin["written_at"]) and twin["written_at"] != twin["pre_registered_at"], "the write time is kept"
    assert twin["supersedes"] == wh.VO2_V1_ID and twin["re_registered_on"] == "2026-10-27" and twin["status"] == "pending"
    assert twin["sk"].startswith("HYPOTHESIS#") and twin["sk"] != _v1()["sk"]
    assert "registered_at" not in twin, "the override is consumed by the store, never persisted as a model field"


def test_mutation_control_without_the_override_the_store_stamps_the_write_time(monkeypatch):
    ddb = _Ddb([])
    eng = _engine_store(ddb, monkeypatch)
    hyp = {k: v for k, v in next(h for h in wh.WATCH_HYPOTHESES if h["hypothesis_id"] == wh.VO2_V2_ID).items() if k != "registered_at"}
    eng.store_hypothesis(hyp, None, kind="population_constant", citation=wh.WATCH_DESIGN_CITATION)
    (rec,) = ddb.items.values()
    assert rec["created_at"] == rec["pre_registered_at"] != wh.RE_REGISTERED_AT and "written_at" not in rec


def test_the_twins_test_spec_is_the_old_records_field_for_field(monkeypatch):
    ddb = _live_partition()
    eng = _engine_store(ddb, monkeypatch)
    _run(ddb, eng)
    spec = _twin(ddb)["test_spec"]
    assert {k: spec[k] for k in V1_SPEC} == V1_SPEC
    assert spec["min_effect_provenance"]["kind"] == "population_constant", "the bar is carried over, not re-priced on data since"
    assert _twin(ddb)["monitoring_window_days"] == 30 and _twin(ddb)["public"] is True


def test_the_twins_check_reads_only_dates_on_or_after_the_registration_day(monkeypatch):
    """End to end through the engine's own check: rows from 2026-10-20 on, the twin graded on 2026-11-06."""
    ddb = _live_partition()
    eng = _engine_store(ddb, monkeypatch)
    _run(ddb, eng)
    twin = {**_twin(ddb), "status": "pending"}
    rows = [{"date": d, "cardio_7d_min": 100.0 + i, "vo2max": 40.0} for i, d in enumerate(_days("2026-11-05", 17))]
    assert rows[0]["date"] == "2026-10-20"
    monkeypatch.setattr(eng, "pacific_now", lambda: dt.datetime(2026, 11, 6, 12, 0, tzinfo=dt.timezone.utc))
    ((hyp, _status, _note, stats, _res),) = eng.check_pending_hypotheses([twin], rows)
    on_or_after = [r for r in rows if r["date"] >= "2026-10-27"]
    assert stats["days_observed"] == len(on_or_after) - 1, "lag 1: the last day has no next-day outcome; nothing before 10-27 counts"
    assert eng.evaluate_test_spec(twin["test_spec"], rows, "2026-10-20")["days_observed"] > stats["days_observed"]  # the control


def test_the_open_old_record_is_never_graded_in_the_run_that_supersedes_it(monkeypatch):
    ddb = _live_partition()
    eng = _engine_store(ddb, monkeypatch)
    all_h, _ = wh.supersede(ddb.load(), ddb, eng.validate_hypothesis, eng.store_hypothesis, now=NOW)
    pending = [h for h in all_h if h.get("status") in ("pending", "confirming")]
    assert wh.VO2_V1_ID not in {h["hypothesis_id"] for h in pending} and wh.VO2_V2_ID in {h["hypothesis_id"] for h in pending}


def test_a_failed_successor_leaves_the_old_record_open_and_pointer_never_dangles(monkeypatch):
    ddb = _live_partition()
    eng = _engine_store(ddb, monkeypatch)
    all_h, closed = wh.supersede(ddb.load(), ddb, lambda *a, **k: (False, ["nope"]), eng.store_hypothesis, now=NOW)
    assert closed == [] and ddb.updates == [] and ddb.items[_v1()["sk"]]["status"] == "pending"


def test_mutation_control_with_no_supersession_declared_the_old_record_stays_open(monkeypatch):
    monkeypatch.setattr(wh, "SUPERSESSIONS", ())
    ddb = _live_partition()
    eng = _engine_store(ddb, monkeypatch)
    _, closed = wh.supersede(ddb.load(), ddb, eng.validate_hypothesis, eng.store_hypothesis, now=NOW)
    assert closed == [] and ddb.items[_v1()["sk"]]["status"] == "pending"


def test_a_fresh_environment_registers_the_twin_and_never_the_superseded_id():
    ids = [h["hypothesis_id"] for h in wh.WATCH_HYPOTHESES]
    assert wh.VO2_V2_ID in ids and wh.VO2_V1_ID not in ids and len(ids) == len(set(ids)) == 3


def test_no_other_open_hypothesis_reads_the_cardio_condition():
    """The set check: of the watch records only the successor reads `cardio_7d_min`; the amended zone-2 one reads
    `zone2_7d_min`. (A live read of the partition on 2026-10-26 found no other record on either metric.)"""
    readers = {
        h["hypothesis_id"]
        for h in wh.WATCH_HYPOTHESES
        if wh.CARDIO_7D in (h["test_spec"]["condition_metric"], h["test_spec"]["outcome_metric"])
    }
    assert readers == {wh.VO2_V2_ID}
    assert {a for s in wh.SERIES_AMENDMENTS for a in s["metrics"]} == {wh.ZONE2_7D}


def test_the_engine_closes_superseded_records_before_it_checks_anything():
    import hypothesis_engine_lambda as eng

    src = inspect.getsource(eng.lambda_handler)
    assert src.index("watch_hypotheses.supersede(") < src.index("enforce_hard_expiry(") < src.index("check_pending_hypotheses(")


# ── the grant: one table, no partition condition ──────────────────────────────────────────


def test_the_engine_role_already_reads_the_hevy_partition():
    sys.path.insert(0, os.path.join(_REPO, "cdk"))
    from stacks import role_policies_compute as rpc

    stmts = rpc.compute_hypothesis_engine()
    ddb = [s for s in stmts if "dynamodb:Query" in s.actions]
    assert ddb and "dynamodb:UpdateItem" in ddb[0].actions
    assert "LeadingKeys" not in inspect.getsource(rpc._compute_base), "a partition-scoped grant would need a Hevy entry"
