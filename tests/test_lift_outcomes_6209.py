"""tests/test_lift_outcomes_6209.py — training outcomes a pre-registered experiment can name (#6209, epic #6206).

``experiment_design.DESIGN_METRICS`` had no training outcome, so ``validate_design`` refused every training experiment.
#6209 adds three per-session series derived from the logged sets in the ``hevy`` partition
(``lambdas/experiment/lift_outcomes.py``): ``lift_session_rpe``, ``lift_e1rm_index`` and
``lift_effort_adjusted_e1rm_index``. These tests pin, on SYNTHETIC sessions only:

  * validate_design accepts each new metric, and refuses them as counterfactual inputs (decided, #6209 e);
  * the derivation — warm-ups ignored, unrated sets counted, a day with no session absent (never 0), deterministic;
  * the owner's merge conditions (2026-11-23): the baseline is a WRITE-ONCE, timestamped snapshot on the experiment row,
    captured at creation (or at the first analysis read after a future start, marked so); the close path reads it and
    never recomputes — a baseline row edited, backfilled or tombstoned after capture moves neither the reference nor the
    verdict; eligibility is ">= 2 baseline sessions", independent of the analysis window; exercise identity is the KEY
    (template id), never guessed from a title; every session keeps the keys and best sets behind its value;
  * the verdict through the real close path: supported, contradicted, inconclusive, thin arms, and no snapshot;
  * privacy: /api/experiments serves an ALLOWLIST of analysis keys — observations and any unknown key never ship, and a
    non-lift experiment's public analysis is byte-identical.

Every expectation is hand-derived in a comment. Fixture dates sit in 2050 and the clock is pinned (#4848).
"""

import copy
import json
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "lambdas"))

from experiment import (  # noqa: E402
    experiment_design as ed,
    lift_outcomes as lo,
)

import mcp.tools_lifestyle as tl  # noqa: E402
from mcp import experiment_close as ec  # noqa: E402

STOP = "run the full 14 days regardless of interim trend; abort only on an injury that stops a session"
START = "2050-01-15"
EXP_SK = "EXP#lift-test_2050-01-15"
# baseline_days 14, washout 0, end 2050-01-28:
#   baseline = 2050-01-01 → 2050-01-14 ; analysis = 2050-01-15 → 2050-01-28
WINDOWS = ed.design_windows(START, "2050-01-28", {"baseline_days": 14, "washout_days": 0})
A, B = "tid:a", "tid:b"
_NOW = datetime(2050, 1, 15, 8, 0, tzinfo=timezone.utc)


def _design(metric, direction="higher", min_effect=2, **extra):
    return {
        "baseline_days": 14,
        "washout_days": 0,
        "stopping_rule": STOP,
        "criterion": {"metric": metric, "direction": direction, "min_effect": min_effect},
        **extra,
    }


def _set(w, reps, rpe=None, kind="normal"):
    return {"weight_kg": w, "reps": reps, "rpe": rpe, "type": kind}


def _ex(name, tid, *sets):
    return {"name": name, "template_id": tid, "sets": list(sets)}


def _session(day, wid, *exercises, adherence=None):
    row = {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{day}#WORKOUT#{wid}",
        "date": day,
        "source_workout_id": wid,
        "start_time": f"{day}T17:00:00Z",
        "exercises": list(exercises),
    }
    if adherence is not None:
        row["adherence"] = adherence
    return row


def _snap(rows, today=START):
    return lo.capture_baseline(rows, "2050-01-01", "2050-01-14", start_date=START, captured_at="2050-01-15T08:00:00Z", today=today)


class _CondFail(Exception):
    response = {"Error": {"Code": "ConditionalCheckFailedException"}}


class _Table:
    """A one-partition fake that honours attribute_not_exists on update_item (the write-once contract)."""

    def __init__(self, rows=(), fail_writes=False):
        self.items = {r["sk"]: copy.deepcopy(r) for r in rows}
        self.updates = []
        self.fail_writes = fail_writes

    def get_item(self, Key):
        it = self.items.get(Key["sk"])
        return {"Item": copy.deepcopy(it)} if it else {}

    def put_item(self, Item):
        self.items[Item["sk"]] = copy.deepcopy(Item)

    def query(self, **kw):
        return {"Items": [copy.deepcopy(v) for v in self.items.values()]}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeValues, ConditionExpression=None, **kw):
        self.updates.append(UpdateExpression)
        if self.fail_writes:
            raise RuntimeError("throttled")
        row = self.items.setdefault(Key["sk"], dict(Key))
        if ConditionExpression == "attribute_not_exists(baseline_snapshot)" and "baseline_snapshot" in row:
            raise _CondFail()
        assert UpdateExpression == "SET baseline_snapshot = :b"
        row["baseline_snapshot"] = copy.deepcopy(ExpressionAttributeValues[":b"])


# ── validation ───────────────────────────────────────────────────────────────


def test_validate_design_accepts_every_training_metric():
    for metric in (lo.LIFT_SESSION_RPE, lo.LIFT_E1RM_INDEX, lo.LIFT_EFFORT_E1RM_INDEX):
        ok, issues = ed.validate_design(_design(metric))
        assert ok, (metric, issues)
        assert ed.DESIGN_METRICS[metric] == ("hevy", metric, lo.LIFT_METRICS[metric]["label"])


def test_lift_slugs_are_not_counterfactual_inputs_and_old_designs_still_validate():
    """#6209 (e), decided: the ghost is a daily model; a session-only series is neither a control nor a ghost criterion."""
    ok, issues = ed.validate_design(_design("recovery_score", counterfactual={"controls": [lo.LIFT_E1RM_INDEX]}))
    assert not ok and any("session-only lift series, not a control" in i for i in issues)
    ok, issues = ed.validate_design(_design(lo.LIFT_E1RM_INDEX, counterfactual={"controls": ["resting_heart_rate"]}))
    assert not ok and any("not available for the session-only lift criterion" in i for i in issues)
    ok, issues = ed.validate_design(_design("recovery_score", counterfactual={"controls": ["resting_heart_rate"]}))
    assert ok, issues


def test_registry_entries_state_the_confounds_and_the_mix():
    assert "confounds programmed load with performance" in lo.LIFT_METRICS[lo.LIFT_E1RM_INDEX]["caveat"]
    assert "self-reported effort" in lo.LIFT_METRICS[lo.LIFT_EFFORT_E1RM_INDEX]["caveat"]
    assert "self-report" in lo.LIFT_METRICS[lo.LIFT_SESSION_RPE]["caveat"]
    for m in lo.INDEX_METRICS:
        assert "arms can differ in exercise mix" in lo.LIFT_METRICS[m]["definition"]
    assert lo.MIN_BASELINE_VALUED == ed.MIN_POINTS_PER_ARM


def test_the_mcp_metric_description_enumerates_exactly_the_design_metrics():
    """The tool's criterion.metric prose is a literal (the catalog generator reads it with ast.literal_eval), so this pins
    it to the registry: every slug validate_design accepts, in registry order, and nothing else; plus both confounds."""
    from mcp.tools_descriptions import DESIGN_METRIC_DESCRIPTION

    listed = DESIGN_METRIC_DESCRIPTION.split("One of: ", 1)[1].split(". ", 1)[0].split(", ")
    assert listed == list(ed.DESIGN_METRICS)
    assert "confounds programmed load with performance" in DESIGN_METRIC_DESCRIPTION
    assert "self-reported effort" in DESIGN_METRIC_DESCRIPTION


# ── lift_session_rpe ─────────────────────────────────────────────────────────


def test_session_rpe_ignores_warmups_and_counts_unrated_sets():
    rows = [
        # warm-up rated 10 is ignored; rated working sets 7, 8, 9 → mean 8.0; one unrated; one bodyweight set unloaded
        _session(
            "2050-01-02",
            "w1",
            _ex("Bench Press", "a", _set(40, 10, 10, "warmup"), _set(60, 8, 7), _set(60, 8, 8), _set(60, 8)),
            _ex("Squat", "b", _set(90, 5, 9), _set(0, 10, 6)),
        ),
        # only two rated sets → no value (needs 3)
        _session("2050-01-04", "w2", _ex("Bench Press", "a", _set(60, 8, 8), _set(60, 8, 9), _set(60, 8))),
    ]
    snap = _snap(rows)
    assert snap["baseline_values"][lo.LIFT_SESSION_RPE] == {"2050-01-02": 8.0}  # 01-04 ABSENT, never 0
    arm = snap["arms"][lo.LIFT_SESSION_RPE]
    assert arm["n_sessions"] == 2 and arm["n_sessions_valued"] == 1
    assert arm["sets_warmup"] == 1 and arm["sets_unloaded"] == 1
    assert arm["sets_unrated"] == 2  # one per session
    assert arm["sets_rated"] == 5  # 3 (7, 8, 9) + 2
    assert arm["sessions"][1]["no_value_reason"] == "2 rated sets (needs 3)"


# ── the snapshot and the index ───────────────────────────────────────────────


def _index_fixture():
    """Baseline A ref = (80 + 90) / 2 = 85, B ref = (105 + 120) / 2 = 112.5 (Epley w * (1 + reps/30)):
    2050-01-02: A best 60x10 = 80 (the 100x10 warm-up = 133.3 is ignored; 60x5 = 70 loses), B 90x5 = 105,
                D 20x10 (one baseline session), E 50x5 (one baseline session)
    2050-01-09: A 75x6 = 90, B 90x10 = 120
    2050-01-16: A 75x6 = 90, B 90x10 = 120, C 50x10 (never in the baseline), E 55x5
    2050-01-18: A only → 1 referenced exercise → no value
    """
    return [
        _session(
            "2050-01-02",
            "w1",
            _ex("Bench Press", "a", _set(100, 10, None, "warmup"), _set(60, 10, 8), _set(60, 5)),
            _ex("Squat", "b", _set(90, 5, 9)),
            _ex("Curl", "d", _set(20, 10, 8)),
            _ex("Lunge", "e", _set(50, 5, 8)),
        ),
        _session("2050-01-09", "w2", _ex("Bench Press", "a", _set(75, 6, 9)), _ex("Squat", "b", _set(90, 10, 10))),
        _session(
            "2050-01-16",
            "w3",
            _ex("Bench Press", "a", _set(75, 6, 8)),
            _ex("Squat", "b", _set(90, 10, 9)),
            _ex("Row", "c", _set(50, 10, 8)),
            _ex("Lunge", "e", _set(55, 5, 8)),
            adherence={"status": "matched", "as_prescribed": {"verdict": "progressed"}},
        ),
        _session("2050-01-18", "w4", _ex("Bench Press", "a", _set(80, 5, 9))),
    ]


def test_the_snapshot_carries_identity_references_and_source_rows():
    snap = _snap(_index_fixture())
    assert snap["engine"] == lo.ENGINE and snap["captured_at"] == "2050-01-15T08:00:00Z"
    assert snap["window"] == {"start": "2050-01-01", "end": "2050-01-14"}
    assert snap["captured_after_start"] is False and snap["capture_lag_days"] == 0
    a = snap["exercises"][A]
    assert a["display_name"] == "Bench Press" and a["template_id"] == "a"
    assert a["references"] == {lo.LIFT_E1RM_INDEX: 85.0, lo.LIFT_EFFORT_E1RM_INDEX: 88.25}
    assert a["n_sessions"] == {lo.LIFT_E1RM_INDEX: 2, lo.LIFT_EFFORT_E1RM_INDEX: 2}
    assert a["source_rows"][lo.LIFT_E1RM_INDEX][0] == {
        "date": "2050-01-02",
        "sk": "DATE#2050-01-02#WORKOUT#w1",
        "workout_id": "w1",
        "best_set": {"weight_kg": 60, "reps": 10, "rpe": 8.0},
        "e1rm": 80.0,
    }
    assert snap["exercises"]["tid:d"]["references"][lo.LIFT_E1RM_INDEX] is None  # one baseline session
    # rows from outside the window never enter a snapshot
    assert "tid:c" not in snap["exercises"]


def test_e1rm_index_reads_the_snapshot_and_reports_exclusions_by_key():
    rows = _index_fixture()
    out = lo.derive(lo.LIFT_E1RM_INDEX, rows, WINDOWS, _snap(rows))
    obs = out["observations"]
    assert obs["state"] == "ok"
    assert obs["reference_e1rm_kg"] == {
        A: {"display_name": "Bench Press", "template_id": "a", "reference": 85.0, "n_sessions": 2},
        B: {"display_name": "Squat", "template_id": "b", "reference": 112.5, "n_sessions": 2},
    }
    assert obs["exercises_used"] == [A, B]
    assert obs["exercises_excluded"] == {
        "tid:c": {"display_name": "Row", "template_id": "c", "reason": "not in the baseline window"},
        "tid:d": {"display_name": "Curl", "template_id": "d", "reason": "1 baseline sessions (needs 2)"},
        "tid:e": {"display_name": "Lunge", "template_id": "e", "reason": "1 baseline sessions (needs 2)"},
    }
    # 01-02: (80/85 + 105/112.5)/2 * 100 = (94.1176 + 93.3333)/2 = 93.73
    # 01-09 and 01-16: (90/85 + 120/112.5)/2 * 100 = (105.8824 + 106.6667)/2 = 106.27
    assert out["values"] == {"2050-01-02": 93.73, "2050-01-09": 106.27, "2050-01-16": 106.27}  # 01-18: one referenced exercise
    analysis = obs["arms"]["analysis"]
    s16, s18 = analysis["sessions"]
    assert s18["no_value_reason"] == "1 referenced exercises (needs 2)"
    # the audit trail behind a value: the keys used and the best set behind each
    assert s16["keys_used"] == [A, B]
    assert s16["exercises"][A]["best_set"] == {"weight_kg": 75, "reps": 6, "rpe": 8.0}
    assert s16["exercises"][A]["pct_of_reference"] == 105.8824 and s16["exercises"]["tid:c"]["used"] is False
    assert s16["as_prescribed"] == "progressed" and analysis["as_prescribed_counts"] == {"None": 1, "progressed": 1}
    # the exercise mix of each arm (key → sessions valued with it)
    assert obs["arms"]["baseline"]["exercise_mix"] == {A: 2, B: 2}
    assert analysis["exercise_mix"] == {A: 1, B: 1}
    # the baseline arm averages 100 by construction: (93.73 + 106.27) / 2
    base = [v for d, v in out["values"].items() if d <= WINDOWS["baseline_end"]]
    assert sum(base) / len(base) == 100.0


def test_effort_adjusted_index_uses_rated_sets_with_reps_in_reserve():
    rows = _index_fixture()
    out = lo.derive(lo.LIFT_EFFORT_E1RM_INDEX, rows, WINDOWS, _snap(rows))
    # w * (1 + (reps + 10 - rpe)/30), rated sets only (the unrated 60x5 cannot count):
    #   A: 60x10@8 = 60*1.4 = 84 ; 75x6@9 = 75*(1 + 7/30) = 92.5 → ref 88.25
    #   B: 90x5@9 = 90*1.2 = 108 ; 90x10@10 = 90*(4/3) = 120 → ref 114
    refs = out["observations"]["reference_e1rm_kg"]
    assert (refs[A]["reference"], refs[B]["reference"]) == (88.25, 114.0)
    # 01-16: A 75x6@8 = 95 → 95/88.25 = 107.6487 ; B 90x10@9 = 123 → 123/114 = 107.8947 → mean 107.7717
    assert out["values"]["2050-01-16"] == 107.77


def test_an_unrated_session_has_no_effort_adjusted_value():
    rows = _index_fixture() + [_session("2050-01-20", "w5", _ex("Bench Press", "a", _set(75, 6)), _ex("Squat", "b", _set(90, 10)))]
    snap = _snap(rows)
    assert "2050-01-20" in lo.derive(lo.LIFT_E1RM_INDEX, rows, WINDOWS, snap)["values"]
    assert "2050-01-20" not in lo.derive(lo.LIFT_EFFORT_E1RM_INDEX, rows, WINDOWS, snap)["values"]


def test_without_a_snapshot_nothing_is_computed():
    out = lo.derive(lo.LIFT_E1RM_INDEX, _index_fixture(), WINDOWS, None)
    assert out["values"] == {} and out["observations"]["state"] == lo.NO_BASELINE_SNAPSHOT
    assert out["observations"]["reference_e1rm_kg"] == {}
    assert all(
        s["value"] is None and s["no_value_reason"] == lo.NO_BASELINE_SNAPSHOT for s in out["observations"]["arms"]["baseline"]["sessions"]
    )


def test_derivation_is_deterministic_whatever_the_row_order():
    rows = _index_fixture()
    for metric in lo.LIFT_METRICS:
        a = lo.derive(metric, rows, WINDOWS, _snap(rows))
        b = lo.derive(metric, list(reversed(rows)), WINDOWS, _snap(list(reversed(rows))))
        assert a == b, metric


def test_tombstones_and_day_aggregates_are_not_sessions():
    extra = [
        {**_session("2050-01-20", "w9", _ex("Bench Press", "a", _set(200, 5, 8)), _ex("Squat", "b", _set(200, 5, 8))), "tombstone": True},
        {"pk": "USER#matthew#SOURCE#hevy", "sk": "DATE#2050-01-21", "exercises": []},
    ]
    snap = _snap(_index_fixture())
    assert (
        lo.derive(lo.LIFT_E1RM_INDEX, _index_fixture() + extra, WINDOWS, snap)["values"]
        == lo.derive(lo.LIFT_E1RM_INDEX, _index_fixture(), WINDOWS, snap)["values"]
    )


def test_two_sessions_on_one_day_average_into_that_day():
    rows = _index_fixture() + [
        # 01-16 second session: A 60x10 = 80 → 94.1176 ; B 90x5 = 105 → 93.3333 → 93.7255
        _session("2050-01-16", "w6", _ex("Bench Press", "a", _set(60, 10, 8)), _ex("Squat", "b", _set(90, 5, 9))),
    ]
    out = lo.derive(lo.LIFT_E1RM_INDEX, rows, WINDOWS, _snap(rows))
    assert out["values"]["2050-01-16"] == 100.0  # (106.2745 + 93.7255) / 2
    assert out["observations"]["arms"]["analysis"]["n_sessions"] == 3


def test_eligibility_does_not_depend_on_the_analysis_window():
    """Owner condition (b): a baseline-only exercise keeps its reference, and a LATER session — even one that is the
    first window appearance of that exercise — never changes a baseline day value."""
    base = [
        _session("2050-01-02", "a", _ex("Squat", "s", _set(100, 5, 8)), _ex("Bench", "b", _set(80, 5, 8)), _ex("Row", "r", _set(50, 5, 8))),
        _session("2050-01-05", "b", _ex("Squat", "s", _set(100, 5, 8)), _ex("Bench", "b", _set(80, 5, 8)), _ex("Row", "r", _set(70, 5, 8))),
    ]
    snap = _snap(base)
    assert snap["exercises"]["tid:r"]["references"][lo.LIFT_E1RM_INDEX] == 70.0  # (58.333 + 81.667) / 2, no window needed
    later = [_session("2050-01-20", "f", _ex("Row", "r", _set(60, 5, 8)))]
    before = lo.derive(lo.LIFT_E1RM_INDEX, base, WINDOWS, snap)["values"]
    after = lo.derive(lo.LIFT_E1RM_INDEX, base + later, WINDOWS, snap)["values"]
    assert {d: v for d, v in after.items() if d <= "2050-01-14"} == before
    assert snap["baseline_values"][lo.LIFT_E1RM_INDEX] == before


def test_identity_is_the_key_never_the_title():
    """Owner condition 2: two template ids sharing a title stay two exercises; a renamed movement keeps its key; a title
    logged without a template id is never matched to the same title with one — it is reported, not merged."""
    two = [
        _session(d, w, _ex("Squat", "t1", _set(100, 5, 8)), _ex("Squat", "t9", _set(50, 5, 8)), _ex("Bench", "t2", _set(80, 5, 8)))
        for d, w in (("2050-01-02", "a"), ("2050-01-05", "b"), ("2050-01-16", "d"))
    ]
    refs = lo.derive(lo.LIFT_E1RM_INDEX, two, WINDOWS, _snap(two))["observations"]["reference_e1rm_kg"]
    assert refs["tid:t1"]["reference"] != refs["tid:t9"]["reference"] and refs["tid:t9"]["display_name"] == "Squat"

    ren = [
        _session("2050-01-02", "a", _ex("Squat", "t1", _set(100, 5, 8)), _ex("Bench", "t2", _set(80, 5, 8))),
        _session("2050-01-05", "b", _ex("Squat", "t1", _set(100, 5, 8)), _ex("Bench", "t2", _set(80, 5, 8))),
        _session("2050-01-16", "d", _ex("Back Squat", "t1", _set(100, 5, 8)), _ex("Bench", "t2", _set(80, 5, 8))),
    ]
    assert lo.derive(lo.LIFT_E1RM_INDEX, ren, WINDOWS, _snap(ren))["values"]["2050-01-16"] == 100.0

    notid = [
        _session("2050-01-02", "a", _ex("Squat", "", _set(100, 5, 8)), _ex("Bench", "t2", _set(80, 5, 8))),
        _session("2050-01-05", "b", _ex("Squat", "", _set(100, 5, 8)), _ex("Bench", "t2", _set(80, 5, 8))),
        _session("2050-01-16", "d", _ex("Squat", "t1", _set(100, 5, 8)), _ex("Bench", "t2", _set(80, 5, 8))),
    ]
    obs = lo.derive(lo.LIFT_E1RM_INDEX, notid, WINDOWS, _snap(notid))["observations"]
    assert "name:squat" in obs["exercises_used"]
    reason = obs["exercises_excluded"]["tid:t1"]["reason"]
    assert "name:squat" in reason and "never matched by name" in reason
    assert obs["arms"]["analysis"]["sessions"][0]["no_value_reason"] == "1 referenced exercises (needs 2)"


# ── the close path: write-once snapshot, verdicts, mutations ─────────────────


def _block(day0, n, step, factor, wid_prefix, rpe=8):
    """n sessions every `step` days from day0 (2050-01-DD), A and B at a factor of a fixed per-session pattern."""
    pattern = [60, 62, 58, 61, 59, 60, 62]
    rows = []
    for i in range(n):
        day = f"2050-01-{day0 + i * step:02d}" if day0 + i * step <= 31 else f"2050-02-{day0 + i * step - 31:02d}"
        w = pattern[i % len(pattern)] * factor
        rows.append(
            _session(
                day,
                f"{wid_prefix}{i}",
                _ex("Bench Press", "a", _set(w, 5, rpe), _set(w, 5, rpe), _set(w, 5, rpe)),
                _ex("Squat", "b", _set(w * 1.5, 5, rpe), _set(w * 1.5, 5, rpe)),
            )
        )
    return rows


def _wire(monkeypatch, rows, table, today="2050-03-01"):
    """Point tools_lifestyle's reads at `rows` and `table`, and pin its clock."""

    def fake_query_source(source, start, stop, **kw):
        assert source == "hevy"
        return [copy.deepcopy(r) for r in rows if start <= r["sk"][5:15] <= stop]

    monkeypatch.setattr(tl, "query_source", fake_query_source)
    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "pacific_today", lambda: today)


def _row(metric, direction="higher", min_effect=2, snapshot=None):
    r = {"pk": "USER#matthew#SOURCE#experiments", "sk": EXP_SK, "start_date": START, "design": _design(metric, direction, min_effect)}
    if snapshot is not None:
        r["baseline_snapshot"] = snapshot
    return r


def _close(monkeypatch, rows, metric, end="2050-01-28", direction="higher", min_effect=2, table=None, today="2050-03-01"):
    existing = (table.get_item(Key={"sk": EXP_SK}).get("Item") if table else None) or _row(metric, direction, min_effect)
    table = table or _Table([existing])
    _wire(monkeypatch, rows, table, today)
    return tl._run_design_analysis(existing, existing["design"], end)


def test_verdict_supported_when_the_window_lifts_more(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 1.1, "w")  # 10% heavier, same reps → index ≈ 110
    out = _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX)
    assert out["verdict"] == "supported"
    assert abs(out["mean_baseline"] - 100) < 0.5 and abs(out["mean_window"] - 110) < 0.5
    obs = out["observations"]
    assert obs["arms"]["baseline"]["n_sessions"] == 7 and obs["arms"]["analysis"]["n_sessions"] == 7
    assert obs["exercises_used"] == [A, B]
    assert obs["snapshot"]["captured_after_start"] is True and obs["snapshot"]["capture_lag_days"] == 45  # captured at close


def test_verdict_contradicted_when_the_window_lifts_less(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 0.9, "w")
    assert _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX)["verdict"] == "contradicted"


def test_verdict_inconclusive_when_nothing_moves(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 1.0, "w")
    assert _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX)["verdict"] == "inconclusive"


def test_thin_arms_are_inconclusive_with_honest_ns(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 3, 2, 1.3, "w")  # only 3 analysis sessions (needs 5)
    out = _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX)
    assert out["verdict"] == "inconclusive" and out["effect_size"] is None
    assert out["n_window"] == 3 and out["observations"]["arms"]["analysis"]["n_sessions_valued"] == 3


def test_session_rpe_verdict_through_the_close_path(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b", rpe=8) + _block(15, 7, 2, 1.0, "w", rpe=7)
    out = _close(monkeypatch, rows, lo.LIFT_SESSION_RPE, direction="lower", min_effect=0.5)
    assert out["mean_baseline"] == 8.0 and out["mean_window"] == 7.0
    assert out["verdict"] == "supported"


def test_baseline_mutations_after_capture_move_neither_reference_nor_verdict(monkeypatch):
    """Owner condition 1: capture, then EDIT a baseline row, BACKFILL a heavier one, TOMBSTONE another — the stored
    reference, the baseline arm and the verdict are exactly those of the clean close."""
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 1.1, "w")
    table = _Table([_row(lo.LIFT_E1RM_INDEX)])
    _wire(monkeypatch, rows, table, today=START)
    ec.ensure_baseline_snapshot(table.items[EXP_SK], query_source=tl.query_source, table=table, now=_NOW, today=START)
    clean = _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX, table=table)

    edited = copy.deepcopy(rows)
    edited[0]["exercises"][0]["sets"] = [_set(140, 5, 8)]
    backfilled = rows + [_session("2050-01-04", "z", _ex("Bench Press", "a", _set(30, 5, 8)), _ex("Squat", "b", _set(45, 5, 8)))]
    tombstoned = copy.deepcopy(rows)
    tombstoned[1]["tombstone"] = True
    for mutated in (edited, backfilled, tombstoned):
        out = _close(monkeypatch, mutated, lo.LIFT_E1RM_INDEX, table=table)
        assert out["observations"]["reference_e1rm_kg"] == clean["observations"]["reference_e1rm_kg"]
        assert out["observations"]["arms"]["baseline"] == clean["observations"]["arms"]["baseline"]
        assert (out["mean_baseline"], out["n_baseline"], out["verdict"]) == (clean["mean_baseline"], clean["n_baseline"], clean["verdict"])
    assert table.updates == ["SET baseline_snapshot = :b"]  # captured once; every close read it


def test_the_baseline_is_frozen_at_capture_not_recomputed_at_close(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 1.1, "w") + _block(29, 7, 2, 1.5, "x")
    table = _Table([_row(lo.LIFT_E1RM_INDEX)])
    early = _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX, end="2050-01-28", table=table)
    late = _close(monkeypatch, rows, lo.LIFT_E1RM_INDEX, end="2050-02-11", table=table)
    assert early["observations"]["reference_e1rm_kg"] == late["observations"]["reference_e1rm_kg"]
    assert early["observations"]["snapshot"] == late["observations"]["snapshot"]
    assert early["mean_baseline"] == late["mean_baseline"] and abs(late["mean_baseline"] - 100) < 0.5
    # the reference is the mean baseline session-best: Bench mean 60.286 kg x5 → e1RM x (7/6) = 70.33
    assert early["observations"]["reference_e1rm_kg"][A]["reference"] == round(sum([60, 62, 58, 61, 59, 60, 62]) / 7 * 7 / 6, 4)


def test_a_second_capture_is_a_no_op_that_returns_the_stored_snapshot(monkeypatch):
    rows = _block(1, 7, 2, 1.0, "b")
    table = _Table([_row(lo.LIFT_E1RM_INDEX)])
    _wire(monkeypatch, rows, table, today=START)
    first = ec.ensure_baseline_snapshot(
        copy.deepcopy(table.items[EXP_SK]), query_source=tl.query_source, table=table, now=_NOW, today=START
    )
    # a racing writer that read the row before the first capture: its conditional write fails and it returns the stored one
    stale = _row(lo.LIFT_E1RM_INDEX)
    _wire(monkeypatch, rows + [_session("2050-01-03", "late", _ex("Bench Press", "a", _set(200, 5, 8)))], table, today=START)
    second = ec.ensure_baseline_snapshot(stale, query_source=tl.query_source, table=table, now=_NOW, today=START)
    assert second == first
    assert json.loads(json.dumps(table.items[EXP_SK]["baseline_snapshot"], default=float)) == first


def test_no_snapshot_and_none_capturable_closes_inconclusive(monkeypatch):
    table = _Table([_row(lo.LIFT_E1RM_INDEX)], fail_writes=True)
    out = _close(monkeypatch, _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 1.5, "w"), lo.LIFT_E1RM_INDEX, table=table)
    assert out["verdict"] == "inconclusive" and out["reason"] == lo.NO_BASELINE_SNAPSHOT
    assert "effect_size" not in out


def test_a_non_lift_close_is_unchanged_and_writes_nothing(monkeypatch):
    """(f) backward compatibility: a whoop criterion closes through the same code path with the pre-#6209 key set."""
    table = _Table([{"pk": "x", "sk": EXP_SK, "start_date": START, "design": _design("recovery_score")}])
    monkeypatch.setattr(tl, "table", table)
    monkeypatch.setattr(tl, "pacific_today", lambda: "2050-03-01")
    whoop = [{"sk": f"DATE#2050-01-{d:02d}", "recovery_score": 50 + (d % 3)} for d in range(1, 29)]
    monkeypatch.setattr(tl, "query_source", lambda s, a, b, **k: [r for r in whoop if a <= r["sk"][5:15] <= b] if s == "whoop" else [])
    out = tl._run_design_analysis(table.items[EXP_SK], table.items[EXP_SK]["design"], "2050-01-28")
    assert list(out) == [
        "windows",
        "metric",
        "n_baseline",
        "n_window",
        "mean_baseline",
        "mean_window",
        "effect_size",
        "ci95_low",
        "ci95_high",
        "cohens_d",
        "verdict",
        "summary",
        "analyzed_at",
        "engine",
    ]
    assert table.updates == []


# ── creation: capture when due, the advisory note ────────────────────────────


class _S3:
    def put_object(self, **kw):
        pass


def _create(monkeypatch, rows, today, design, start_date=START):
    table = _Table()
    monkeypatch.setattr(tl, "s3_client", _S3())
    _wire(monkeypatch, rows, table, today=today)
    out = tl.tool_create_experiment({"name": "Lift test", "hypothesis": "x", "start_date": start_date, "design": design})
    return out, table


def test_create_captures_a_due_snapshot_and_notes_a_thin_baseline(monkeypatch):
    out, table = _create(monkeypatch, _block(1, 3, 3, 1.0, "b"), START, _design(lo.LIFT_E1RM_INDEX))
    stored = table.items[EXP_SK]["baseline_snapshot"]
    assert stored["window"] == {"start": "2050-01-01", "end": "2050-01-14"} and stored["captured_after_start"] is False
    assert out["baseline_snapshot_captured_at"] == stored["captured_at"]
    assert "Only 3 baseline days" in out["baseline_note"] and "inconclusive by construction" in out["baseline_note"]
    assert "baseline_snapshot" not in out  # the response names the capture; the snapshot itself stays on the row


def test_create_with_a_full_baseline_has_no_note(monkeypatch):
    out, _table = _create(monkeypatch, _block(1, 7, 2, 1.0, "b"), START, _design(lo.LIFT_E1RM_INDEX))
    assert "baseline_note" not in out and out["baseline_snapshot_captured_at"]


def test_a_future_start_defers_the_capture_and_the_first_read_after_it_marks_the_lag(monkeypatch):
    out, table = _create(monkeypatch, _block(1, 7, 2, 1.0, "b"), "2050-01-10", _design(lo.LIFT_E1RM_INDEX))
    assert "baseline_snapshot" not in table.items[EXP_SK] and out["baseline_snapshot_captured_at"] is None
    assert "in the future" in out["baseline_note"]
    rows = _block(1, 7, 2, 1.0, "b") + _block(15, 7, 2, 1.1, "w")
    _wire(monkeypatch, rows, table, today="2050-01-18")
    snap = ec.ensure_baseline_snapshot(table.items[EXP_SK], query_source=tl.query_source, table=table, now=_NOW, today="2050-01-18")
    assert snap["captured_after_start"] is True and snap["capture_lag_days"] == 3


def test_a_non_lift_create_gets_no_snapshot(monkeypatch):
    out, table = _create(monkeypatch, [], START, _design("recovery_score"))
    assert "baseline_snapshot" not in table.items[EXP_SK] and "baseline_note" not in out
    assert "baseline_snapshot_captured_at" not in out


# ── privacy: the public projection ───────────────────────────────────────────


def _public(monkeypatch, analysis):
    from fakes import FakeDdbTable
    from web import site_api_protocols as protocols_mod

    row = {"pk": "USER#matthew#SOURCE#experiments", "sk": "EXP#done", "name": "Morning sunlight", "status": "completed"}
    row.update(
        {"start_date": "2050-01-15", "end_date": "2050-01-28", "analysis": analysis, "baseline_snapshot": {"exercises": {"tid:a": {}}}}
    )
    body = json.loads(protocols_mod.experiments(_g={"table": FakeDdbTable(rows=[row]), "_experiment_catalog": lambda i, n: []})["body"])
    return body["experiments"][0]


def test_an_unknown_or_private_analysis_key_never_reaches_the_public_payload(monkeypatch):
    analysis = {"verdict": "supported", "observations": {"arms": {"baseline": {"sessions": [{"workout_id": "w1"}]}}}}
    analysis.update({"reason": "x", "some_future_key": {"kg": 1}})
    served = _public(monkeypatch, analysis)
    assert served["analysis"] == {"verdict": "supported"}
    assert "baseline_snapshot" not in served and "workout_id" not in json.dumps(served) and "tid:a" not in json.dumps(served)


def test_a_non_lift_public_analysis_is_byte_identical(monkeypatch):
    analysis = {
        "windows": {
            "baseline_start": "2050-01-01",
            "baseline_end": "2050-01-14",
            "analysis_start": "2050-01-15",
            "analysis_end": "2050-01-28",
        },
        "metric": "recovery_score",
        "n_baseline": 14,
        "n_window": 14,
        "mean_baseline": 51.0,
        "mean_window": 55.0,
        "effect_size": 4.0,
        "ci95_low": 2.0,
        "ci95_high": 6.0,
        "cohens_d": 1.2,
        "verdict": "supported",
        "randomization": {"p_value": 0.1429, "n_used": 7},
        "counterfactual": {"state": "no_counterfactual", "reason": "insufficient pre-period"},
        "summary": "Pre-registered criterion: Whoop Recovery higher by >= 2.",
        "analyzed_at": "2050-01-29T00:00:00",
        "engine": "n1-design-v1",
    }
    assert json.dumps(_public(monkeypatch, analysis)["analysis"]) == json.dumps(analysis)
