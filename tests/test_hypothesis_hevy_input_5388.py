"""tests/test_hypothesis_hevy_input_5388.py — the hypothesis engine counts a gym visit once (#5388).

`compute.watch_hypotheses._trailing_volumes` resolves the trailing week through
`training.zone2_minutes.counted_sessions`. The engine's input manifest did not list `hevy`, so the
resolver ran WITHOUT the routine source and one 160-minute visit read 240 `cardio_7d_min` (Hevy's own
Strava push stood for the whole visit, and the watch's ride and the mobility block inside it were
counted again). This file pins, on the #5369 shared fixture (synthetic numbers):

  * the manifest declares `hevy` and the engine's `gather_data` therefore fetches it;
  * from the dated cut-over the same week reads 160, with a mutation control that drops the Hevy rows
    (240) and one that moves the cut-over out of reach (240);
  * BEFORE the cut-over the series is the one the hypothesis was registered on (240 — the as-registered
    definition), so the record's grader sees the definition change on a stated day;
  * the open watch records are stamped with the amendment, idempotently, never touching the frozen spec;
  * the engine's role already reads the Hevy partition (one table, no LeadingKeys condition).

No clock is read: every date is a literal handed in.
"""

from __future__ import annotations

import copy
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


def _days(end: str, n: int = 7):
    from datetime import date, timedelta

    e = date.fromisoformat(end)
    return [(e - timedelta(days=i)).isoformat() for i in range(n - 1, -1, -1)]


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


def test_a_gym_visit_reads_once_from_the_cut_over():
    dates = _days(CUT)
    vols = wh._trailing_volumes(_data(), dates)
    assert vols[CUT]["cardio_7d_min"] == VISIT


def test_mutation_control_dropping_the_hevy_rows_reads_the_visit_twice():
    """The pre-#5388 wire: no `hevy` in the data. Same fixture, same date: 240 for a 160-minute visit."""
    vols = wh._trailing_volumes(_data(with_hevy=False), _days(CUT))
    assert vols[CUT]["cardio_7d_min"] == 240.0


def test_mutation_control_a_cut_over_out_of_reach_keeps_the_as_registered_series(monkeypatch):
    monkeypatch.setattr(wh, "HEVY_CUTOVER_DATE", "2099-01-01")
    assert wh._trailing_volumes(_data(), _days(CUT))[CUT]["cardio_7d_min"] == 240.0


def test_before_the_cut_over_the_series_is_the_one_the_hypothesis_was_registered_on():
    day_before = _days(CUT)[-2]
    assert day_before < CUT
    vols = wh._trailing_volumes(_data(), _days(day_before))
    assert vols[day_before]["cardio_7d_min"] == 240.0, "as registered: no Hevy rows, the visit's parts counted again"


def test_the_series_steps_on_the_cut_over_day_and_a_value_is_never_a_mixture():
    dates = _days(CUT, 8)
    vols = wh._trailing_volumes(_data(), dates)
    assert vols[dates[-2]]["cardio_7d_min"] == 240.0 and vols[CUT]["cardio_7d_min"] == VISIT


def test_the_zone2_volume_moves_with_the_same_cut_over():
    """Both trailing volumes come from ONE resolution of the week; the zone-2 record is amended too."""
    with_h = wh._trailing_volumes(_data(), _days(CUT))[CUT]["zone2_7d_min"]
    without = wh._trailing_volumes(_data(with_hevy=False), _days(CUT))[CUT]["zone2_7d_min"]
    assert with_h != without  # the push's own zones are dropped as the echo once Hevy is read
    assert {wh.CARDIO_7D, wh.ZONE2_7D} <= set(wh.SERIES_AMENDMENTS[0]["metrics"])


def test_add_watch_metrics_carries_the_corrected_volume_onto_the_day_row():
    rows = [{"date": d} for d in _days(CUT)]
    out = wh.add_watch_metrics(rows, _data())
    assert out[-1]["cardio_7d_min"] == VISIT and "cardio_7d_min" not in out[0]


# ── the record names the cut-over ─────────────────────────────────────────────────────────


class _Table:
    def __init__(self, fail=False):
        self.calls, self.fail = [], fail

    def update_item(self, **kw):
        if self.fail:
            raise RuntimeError("boom")
        self.calls.append(kw)


def _stored(hid, status="pending", **extra):
    hyp = next(h for h in wh.WATCH_HYPOTHESES if h["hypothesis_id"] == hid)
    return {"pk": "USER#matthew#SOURCE#hypotheses", "sk": f"HYPOTHESIS#{hid}", "status": status, "source": hyp["source"], **hyp, **extra}


def test_the_open_records_on_an_affected_condition_are_amended_and_the_rest_are_not():
    recs = [
        _stored("hyp_watch_training_vo2max"),
        _stored("hyp_watch_zone2_cardio_recovery", status="confirming"),
        _stored("hyp_watch_daylight_sleep_onset"),
    ]
    t = _Table()
    done = wh.amend_open_watch_hypotheses(recs, t)
    assert sorted(done) == ["hyp_watch_training_vo2max:hevy_input_5388", "hyp_watch_zone2_cardio_recovery:hevy_input_5388"]
    (vo2,) = [c for c in t.calls if c["Key"]["sk"].endswith("vo2max")]
    (amend,) = vo2["ExpressionAttributeValues"][":new"]
    assert amend["effective_from"] == CUT and amend["issue"] == "#5388" and "changed definition" in amend["change"]
    assert vo2["UpdateExpression"].startswith("SET series_amendments = list_append(") and "test_spec" not in vo2["UpdateExpression"]


def test_amending_is_idempotent_and_leaves_a_resolved_record_alone():
    t = _Table()
    done = _stored("hyp_watch_training_vo2max", series_amendments=[dict(wh.SERIES_AMENDMENTS[0])])
    resolved = _stored("hyp_watch_zone2_cardio_recovery", status="confirmed")
    assert wh.amend_open_watch_hypotheses([done, resolved], t) == [] and t.calls == []


def test_a_failed_amendment_is_not_fatal():
    assert wh.amend_open_watch_hypotheses([_stored("hyp_watch_training_vo2max")], _Table(fail=True)) == []


def test_the_seed_amends_through_the_table_it_is_given_and_not_without_one():
    recs = [_stored(h["hypothesis_id"]) for h in wh.WATCH_HYPOTHESES]
    t = _Table()
    out = wh.seed_watch_hypotheses(recs, [], lambda *a, **k: (True, []), lambda *a, **k: None, table=t)
    assert out["registered"] == [] and len(out["amended"]) == 2 and len(t.calls) == 2
    assert wh.seed_watch_hypotheses(recs, [], lambda *a, **k: (True, []), lambda *a, **k: None)["amended"] == []


def test_the_engine_hands_the_seed_its_table():
    import hypothesis_engine_lambda as eng

    assert "table=table" in inspect.getsource(eng.lambda_handler).split("seed_watch_hypotheses(")[1].split("\n")[0]


# ── the grant: one table, no partition condition ──────────────────────────────────────────


def test_the_engine_role_already_reads_the_hevy_partition():
    sys.path.insert(0, os.path.join(_REPO, "cdk"))
    from stacks import role_policies_compute as rpc

    stmts = rpc.compute_hypothesis_engine()
    ddb = [s for s in stmts if "dynamodb:Query" in s.actions]
    assert ddb and "dynamodb:UpdateItem" in ddb[0].actions
    assert "LeadingKeys" not in inspect.getsource(rpc._compute_base), "a partition-scoped grant would need a Hevy entry"
