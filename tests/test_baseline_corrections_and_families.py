"""tests/test_baseline_corrections_and_families.py — owner ruling 2026-11-09 (third), A and B.

A. A frozen "nothing changes" verdict re-scored under the current rule is an OVERLAY
   (``grade_corrections.apply_baseline_correction``): the frozen ``baseline`` map, the grade and ``corrections[]`` are
   untouched, ``baseline_corrections[]`` gains one entry (with ruleset version, reason, cause, instant, ruler), a
   ``CORRECTION#BASELINE#`` ledger row is written first, and every served comparison reads
   ``coach_baseline.effective``. The original verdict stays readable as the original.
B. A repeat family is stored on each member row (``coach.repeat_family``) with an audit row carrying the evidence;
   members must share the frozen kind, metric, target day, condition and window, and their predicted values must
   agree — distinct forecasts are refused. ``scripts/record_verification.py`` copies the stored family into the
   VERIFY# classification and refuses an entry that contradicts it.

Every id here is synthetic. Each property has a negative control.
"""

from __future__ import annotations

import copy
import io
import json
import os
import sys

os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

from datetime import datetime, timezone  # noqa: E402

import pytest  # noqa: E402
import record_verification as rv  # noqa: E402
from coach import (  # noqa: E402
    coach_baseline,
    grade_corrections,
    repeat_family,
    verification_record as vr,  # noqa: E402
)
from web import verification_fields as vf  # noqa: E402

AT = "2026-11-09T21:00:00Z"
FROZEN = {"rule": "nothing_changes", "version": 1, "right": False}
RESCORED = {"rule": "nothing_changes", "version": 1, "right": True}


class ConditionFailed(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class FakeTable:
    """Honours exactly the conditions the two writers under test send."""

    def __init__(self, *rows):
        self.items = {(r["pk"], r["sk"]): copy.deepcopy(r) for r in rows}
        self.writes: list = []

    def get_item(self, Key, **_kw):
        item = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": copy.deepcopy(item)} if item else {}

    def put_item(self, Item, ConditionExpression=None, **_kw):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.items:
            raise ConditionFailed(key)
        self.writes.append(("put", key))
        self.items[key] = copy.deepcopy(Item)

    def update_item(self, Key, UpdateExpression, ConditionExpression="", ExpressionAttributeValues=None, **_kw):
        key = (Key["pk"], Key["sk"])
        row = self.items.get(key)
        v = ExpressionAttributeValues or {}
        if row is None:
            raise ConditionFailed(key)
        if ":st" in v and row.get("status") != v[":st"]:
            raise ConditionFailed(key)
        if ":frozen" in v and row.get("baseline") != v[":frozen"]:
            raise ConditionFailed(key)
        if f"attribute_not_exists({coach_baseline.CORRECTIONS_ATTR})" in ConditionExpression and row.get(coach_baseline.CORRECTIONS_ATTR):
            raise ConditionFailed(key)
        if ":n" in v and len(row.get(coach_baseline.CORRECTIONS_ATTR) or []) != v[":n"]:
            raise ConditionFailed(key)
        if f"attribute_not_exists({repeat_family.ATTR})" in ConditionExpression and row.get(repeat_family.ATTR):
            raise ConditionFailed(key)
        self.writes.append(("update", key))
        if "list_append" in UpdateExpression:
            row[coach_baseline.CORRECTIONS_ATTR] = list(row.get(coach_baseline.CORRECTIONS_ATTR) or []) + copy.deepcopy(v[":entry"])
        elif UpdateExpression == f"SET {repeat_family.ATTR} = :m":
            row[repeat_family.ATTR] = copy.deepcopy(v[":m"])
        else:  # pragma: no cover — a writer sent something this fake does not model
            raise AssertionError(UpdateExpression)


def _row(i=0, status="refuted", coach="sleep", **extra):
    pid = f"pred_20260912_synthetic_{coach}_{i:03d}"
    row = {
        "pk": f"COACH#{coach}_coach",
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "coach_id": f"{coach}_coach",
        "claim_natural": f"Synthetic call {i}.",
        "created_at": f"2026-09-12T17:00:{i:02d}Z",
        "created_date": "2026-09-12",
        "status": status,
        "outcome": status,
        "outcome_date": "2026-09-26",
        "outcome_notes": json.dumps({"reason": "synthetic", "algo_version": "1.0"}),
        "evaluation": {"type": "directional", "metric": "deep_pct", "condition": "up", "evaluation_window_days": 14},
        "baseline": dict(FROZEN),
        "phase": "experiment",
    }
    row.update(extra)
    return row


def _correct(table, row, corrected=RESCORED, **kw):
    args = dict(
        reason="re-scored under the current rule",
        ruleset_version="1.1",
        ruled_by="owner",
        ruling_ref="A",
        cause="direction_window_rule_4617",
    )
    args.update(kw)
    return grade_corrections.apply_baseline_correction(table, row, corrected, **args)


# ── A: the overlay ─────────────────────────────────────────────────────────────────────────────


def test_a_baseline_correction_is_an_overlay_and_the_original_stays_readable():
    row = _row(corrections=[{"original_status": "confirmed", "corrected_status": "refuted"}], original_grade={"status": "confirmed"})
    table = FakeTable(row)
    e = _correct(table, row)
    after = table.items[(row["pk"], row["sk"])]
    # the frozen verdict, the grade and the grade-correction trail are exactly as they were
    for k in ("baseline", "status", "outcome", "outcome_date", "outcome_notes", "corrections", "original_grade"):
        assert after[k] == row[k], k
    assert after[coach_baseline.CORRECTIONS_ATTR] == [e]
    assert e["original_baseline"] == FROZEN and e["corrected_baseline"] == RESCORED
    assert e["original_right"] is False and e["corrected_right"] is True and e["verdict_changed"] is True
    for k in ("reason", "ruleset_version", "corrected_at", "cause", "ruled_by", "ruling_ref"):
        assert e[k], k
    # the ledger row is written FIRST, on the call's own partition, under the baseline prefix
    assert [w[0] for w in table.writes] == ["put", "update"]
    ledger_sk = table.writes[0][1][1]
    assert ledger_sk.startswith(grade_corrections.BASELINE_PREFIX + row["prediction_id"] + "#")
    assert table.items[(row["pk"], ledger_sk)]["kind"] == "baseline"
    # readers: the effective verdict is the correction; the frozen one is still the frozen one
    assert coach_baseline.effective(after) == RESCORED and after["baseline"] == FROZEN
    # control: a row with no correction reads its frozen stamp
    assert coach_baseline.effective(row) == FROZEN


def test_a_stale_plan_or_a_second_run_writes_nothing_to_the_row():
    row = _row()
    table = FakeTable(row)
    _correct(table, row)
    with pytest.raises(ConditionFailed):  # the plan read no earlier correction; the row now carries one
        _correct(
            table,
            row,
            corrected={"rule": "nothing_changes", "version": 1, "right": True},
            now=datetime(2026, 11, 9, 23, tzinfo=timezone.utc),
        )
    assert len(table.items[(row["pk"], row["sk"])][coach_baseline.CORRECTIONS_ATTR]) == 1
    # a correction that would not change the effective verdict is refused before any write
    fresh = table.get_item(Key={"pk": row["pk"], "sk": row["sk"]})["Item"]
    n = len(table.writes)
    with pytest.raises(ValueError):
        _correct(table, fresh)
    assert len(table.writes) == n
    # control: the re-read row CAN take a further (changed) correction — the condition is on the count it read
    _correct(table, fresh, corrected=dict(FROZEN), reason="reverted by ruling", now=datetime(2026, 11, 10, tzinfo=timezone.utc))
    assert coach_baseline.effective(table.items[(row["pk"], row["sk"])]) == FROZEN


def test_a_baseline_correction_refuses_an_ungraded_row_or_a_missing_reason():
    with pytest.raises(ValueError):
        _correct(FakeTable(_row(status="expired")), _row(status="expired"))
    with pytest.raises(ValueError):
        _correct(FakeTable(_row()), _row(), reason="")
    with pytest.raises(ValueError):
        _correct(FakeTable(_row()), _row(), corrected={"rule": "something_else", "right": True})
    # control: the same call with everything named writes
    _correct(FakeTable(_row()), _row())


def test_a_row_whose_grade_moved_since_the_plan_is_not_corrected():
    row = _row()
    table = FakeTable(row)
    table.items[(row["pk"], row["sk"])]["status"] = "confirmed"  # changed between the read and the write
    with pytest.raises(ConditionFailed):
        _correct(table, row)


def test_every_served_comparison_reads_the_correction():
    rows = [_row(i) for i in range(3)]
    before = coach_baseline.comparison_block(rows)["records"]["direction"]["rule_right"]
    corrected = copy.deepcopy(rows)
    corrected[0][coach_baseline.CORRECTIONS_ATTR] = [{"corrected_baseline": dict(RESCORED), "corrected_at": AT}]
    after = coach_baseline.comparison_block(corrected)["records"]["direction"]["rule_right"]
    assert (before, after) == (0, 1)
    from web import site_api_calibration_v2

    pairs = site_api_calibration_v2.baseline_paired(corrected)["direction"]["pairs"]
    assert sorted(p[1] for p in pairs) == [False, False, True]


def _verified_set(n_corrected):
    rows, recs = [], []
    for i in range(25):
        r = _row(i, status="confirmed" if i % 2 else "refuted")
        sk = f"VERIFY#{r['prediction_id']}#{AT}"
        r["latest_verification"] = {"sk": sk, "outcome": "reproduced", "verified_at": AT}
        if i < n_corrected:
            r[coach_baseline.CORRECTIONS_ATTR] = [{"corrected_baseline": dict(RESCORED), "corrected_at": AT}]
        rows.append(r)
        recs.append({"sk": sk, "outcome": "reproduced", "classification": {"value": "keep", "approved": True, "ruling_ref": "R"}})
    return vf.headline({"sleep": rows}, {"sleep": recs}, genesis="2026-09-06")["verified"]["baseline"]


def test_the_verified_headline_reads_the_correction_and_says_so():
    b = _verified_set(4)
    assert b["right"] == 4 and b["basis"] == "stored_with_corrections" and b["corrected"] == 4
    assert "except 4 calls" in b["text"] and "re-scored under the current rule on 2026-11-09" in b["text"]
    assert "original verdicts are kept" in b["text"]
    # control: no correction → the stored basis and its words, unchanged
    c = _verified_set(0)
    assert c["right"] == 0 and c["basis"] == "stored" and c["corrected"] == 0
    assert "earlier verdicts have not been restated" in c["text"]


# ── B: repeat families ─────────────────────────────────────────────────────────────────────────


def _point(i, coach, *, target="2026-09-09", threshold=61.0, tolerance=17.6, created=None, **extra):
    spec = {
        "type": "point",
        "metric": "recovery_score",
        "target_date": target,
        "condition": "within",
        "evaluation_window_days": 1,
        "threshold": threshold,
        "tolerance": tolerance,
    }
    return _row(i, status="confirmed", coach=coach, evaluation=spec, created_at=created or f"2026-09-08T17:0{i}:00Z", **extra)


def _plan(rows, **kw):
    args = dict(why_same="one model output", ruling_ref="B", marked_by="owner", marked_at=AT)
    args.update(kw)
    return repeat_family.plan_family(rows, **args)


def test_one_forecast_filed_twice_is_one_family_with_the_earliest_standing():
    a, b = _point(1, "sleep"), _point(2, "physical", threshold=61.2)
    plans = _plan([b, a])
    assert [p["marker"]["role"] for p in plans] == ["first", "repeat"]
    assert plans[0]["row"] is a and len({p["marker"]["family_id"] for p in plans}) == 1
    assert plans[0]["audit"]["evidence"]["criteria"][0]["claim_sha256"] == repeat_family.claim_sha256(a)
    # deterministic: the same members give the same id whatever the order
    assert _plan([a, b])[0]["marker"]["family_id"] == plans[0]["marker"]["family_id"]


@pytest.mark.parametrize(
    "change",
    [
        {"target": "2026-09-10"},  # a different day is a different forecast
        {"threshold": 75.8},  # a different value is a different forecast
    ],
)
def test_distinct_forecasts_stay_distinct(change):
    with pytest.raises(repeat_family.FamilyError):
        _plan([_point(1, "sleep"), _point(2, "physical", **change)])


def test_a_different_metric_or_window_is_refused():
    other = _point(2, "physical")
    other["evaluation"]["metric"] = "hrv"
    with pytest.raises(repeat_family.FamilyError):
        _plan([_point(1, "sleep"), other])
    other2 = _point(2, "physical")
    other2["evaluation"]["evaluation_window_days"] = 14
    with pytest.raises(repeat_family.FamilyError):
        _plan([_point(1, "sleep"), other2])


def test_the_marker_is_written_once_and_never_overwritten():
    a, b = _point(1, "sleep"), _point(2, "physical")
    table = FakeTable(a, b)
    for p in _plan([a, b]):
        repeat_family.write_marker(table, p["row"], p["marker"], p["audit"])
    stored = table.items[(b["pk"], b["sk"])]
    assert stored[repeat_family.ATTR]["role"] == "repeat" and stored["claim_natural"] == b["claim_natural"]
    assert {k: v for k, v in stored.items() if k != repeat_family.ATTR} == b, "nothing but the marker moved"
    # a second marking is refused at plan time (row read with its marker) …
    with pytest.raises(repeat_family.FamilyError):
        _plan([table.get_item(Key={"pk": a["pk"], "sk": a["sk"]})["Item"], b])
    # … and at write time (a stale plan): the condition holds
    p = _plan([a, b], marked_at="2026-11-10T00:00:00Z")[1]
    with pytest.raises(ConditionFailed):
        repeat_family.write_marker(table, p["row"], p["marker"], p["audit"])


def test_the_verification_record_carries_the_stored_family_and_refuses_a_contradiction():
    row = _point(1, "sleep", repeat_family={"family_id": "F1", "role": "repeat"})
    entry = {"approved_classification": "keep", "classification_ruling_ref": "R"}
    assert vr.classification_of(entry, row)["family"] == "F1"
    assert vr.classification_of({**entry, "family": "F1"}, row)["family"] == "F1"
    with pytest.raises(ValueError):
        vr.classification_of({**entry, "family": "F2"}, row)
    with pytest.raises(ValueError):  # a family the row does not carry is the manifest's say-so: refused
        vr.classification_of({**entry, "family": "F1"}, _point(1, "sleep"))
    # control: no family anywhere → none recorded
    assert "family" not in vr.classification_of(entry, _point(1, "sleep"))


class FakeEvaluator:
    ALGO_VERSION = "1.1"

    def __init__(self, status):
        self.status = status

    def _evaluate_all(self, rows, today, write=False):
        assert write is False
        return [{"prediction_id": r["prediction_id"], "status": self.status, "reason": "synthetic"} for r in rows], {}

    def _fetch_range(self, source, lo, hi):
        return []

    def _extract_metric_series(self, records, base):
        return []


def test_a_ruled_observation_is_recorded_and_a_plain_one_is_not():
    ruled = _row(1, status="observation", corrections=[{"original_status": "refuted", "corrected_status": "observation"}])
    plain = _row(2, status="observation")
    table = FakeTable(ruled, plain)
    entries = [
        {
            "coach_pk": ruled["pk"],
            "prediction_id": ruled["prediction_id"],
            "approved_classification": "not_a_forecast",
            "classification_ruling_ref": "R",
        },
        {
            "coach_pk": plain["pk"],
            "prediction_id": plain["prediction_id"],
            "approved_classification": "not_a_forecast",
            "classification_ruling_ref": "R",
        },
    ]
    counts = rv.run(entries, table, ev=FakeEvaluator("refuted"), today="2026-11-09", apply=False, out=io.StringIO())
    assert counts["could_not_verify"] == 1 and counts["skipped"] == 1
    rec = counts["records"][0]
    assert rec["classification"]["value"] == "not_a_forecast" and rec["outcome"] == "could_not_verify"
    assert rec["classification_validated"] is False
