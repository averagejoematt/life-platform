"""tests/test_sealed_prereg_graders_5518.py — every sealed pre-registration row is visible to its grader (#5518).

Cycle 17 sealed 2 hypotheses and 16 predictions. Four were invisible to their graders for weeks: the two genesis
hypotheses carried a wall-clock ``phase=pilot`` stamp the engine's loader filtered out, and the retired training seat's
two sealed bets sat in a partition the evaluator never queried (fixed by #5533 (b)). This file is the contract:

1. **The visibility contract** — for a pre-registration document in the sealed file's shape, every ``hypothesis_id``
   it lists is loaded by ``hypothesis_engine_lambda.load_existing_hypotheses`` and every prediction it seals (ids
   derived by ``prereg_provenance_gate.frozen_prediction_ids``, the seeder's own derivation) is returned by
   ``coach_prediction_evaluator._fetch_predictions`` — whatever phase the write stamped, on operational AND retired
   seats — while the tombstoned copies of earlier cycles stay out. The rows are written by the seeder's own builders
   (``build_prediction_records``, the engine's ``store_hypothesis``); the table stand-in honours the ADR-058 phase
   FilterExpression exactly as DynamoDB would, so the pre-fix loader fails it (mutation-run on this branch).

   The document is SYNTHETIC (stand-in call text): the sealed 2026-09-06 file left the repo under the owner ruling of
   2026-11-11 (PR #5808) and is never re-added. When ``LIFE_PLATFORM_PRIVATE_PREREG_DIR`` holds the private original
   whose bytes hash to the published seal (``tests/sealed_prereg.py``), the SAME contract also runs over it.

2. **The window grade** (``compute/sealed_hypotheses``) — a sealed row whose window closed is graded once on its own
   window, never on today's trailing data; a day with nothing logged is missing; a window across the HR regime marker
   is voided with the marker named; an inconclusive window is voided with its arm counts as the reason.

3. **The dead-man** (``coach/prereg_overdue``) — the overdue count, its horizons and graces, the handler's emission,
   silence on a failed scan, and the alarm's literal name held to the emitting module's constant.

No assertion here reaches a clock: every function under test takes the day it reasons about, and the engine's clock
is pinned where ``store_hypothesis`` reads it.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "lambdas" / "compute", ROOT / "lambdas" / "coach", ROOT / "lambdas", ROOT / "deploy"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

import coach_prediction_evaluator as ev  # noqa: E402
import hypothesis_engine_lambda as eng  # noqa: E402
import prereg_provenance_gate  # noqa: E402
import sealed_prereg as private_prereg  # noqa: E402  (tests/sealed_prereg.py — the private original, seal-checked)
from coach import prereg_overdue  # noqa: E402
from coach.persona_registry import OPERATIONAL_COACH_IDS, RETIRED_COACH_IDS  # noqa: E402
from common import compute_metadata  # noqa: E402
from common.constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE  # noqa: E402
from compute import sealed_hypotheses  # noqa: E402
from experiment.phase_filter import PHASE_FILTER_EXPRESSION  # noqa: E402
from prereg_fixture_series import fixture_series  # noqa: E402

GENESIS = EXPERIMENT_START_DATE
EVE = (date.fromisoformat(GENESIS) - timedelta(days=1)).isoformat()
#: The freeze ran the evening before genesis, Pacific — already genesis day in UTC (the 2026-09-06T02:13Z shape).
FREEZE_INSTANT = datetime.fromisoformat(f"{GENESIS}T02:13:39+00:00")


def _load(module_name: str, rel_path: str):
    spec = importlib.util.spec_from_file_location(module_name, ROOT / rel_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


seeder = _load("seed_genesis_preregistration", "deploy/seed_genesis_preregistration.py")


# ── the table stand-in ────────────────────────────────────────────────────────────────────────────────────────────


def _key_terms(cond):
    expr = cond.get_expression()
    if expr["operator"] == "AND":
        return [t for sub in expr["values"] for t in _key_terms(sub)]
    vals = expr["values"]
    return [(vals[0].name, expr["operator"], vals[1] if len(vals) > 1 else None)]


class PhaseAwareTable:
    """Both KeyConditionExpression shapes the two graders issue, pagination, and — the point — the ADR-058 phase
    FilterExpression applied exactly as DynamoDB applies it, so a loader that leaves the filter on the query cannot
    see a pilot-stamped sealed row here either."""

    def __init__(self, page_size: int = 3):
        self.items: dict = {}
        self.page_size = page_size
        self.queries: list = []
        self.writes: list = []

    def put_item(self, Item=None, **_):
        self.items[(Item["pk"], Item["sk"])] = Item
        return {}

    def update_item(self, **kwargs):
        self.writes.append(kwargs)
        return {}

    def query(self, **kwargs):
        self.queries.append(kwargs)
        vals = kwargs.get("ExpressionAttributeValues", {})
        kce = kwargs["KeyConditionExpression"]
        if isinstance(kce, str):
            pk, prefix = vals[":pk"], vals.get(":prefix") or vals.get(":p")
        else:
            terms = {(a, op): v for a, op, v in _key_terms(kce)}
            pk, prefix = terms[("pk", "=")], terms.get(("sk", "begins_with"))
        rows = sorted((v for (p, _), v in self.items.items() if p == pk and str(v["sk"]).startswith(prefix or "")), key=lambda r: r["sk"])
        if kwargs.get("ScanIndexForward") is False:
            rows.reverse()
        if PHASE_FILTER_EXPRESSION in (kwargs.get("FilterExpression") or ""):
            rows_out = lambda page: [r for r in page if r.get("phase") in (None, vals[":phase_experiment"])]  # noqa: E731
        else:
            rows_out = lambda page: page  # noqa: E731
        start = int((kwargs.get("ExclusiveStartKey") or {}).get("i", 0))
        page = rows[start : start + self.page_size]
        resp = {"Items": rows_out(page)}
        if start + self.page_size < len(rows):
            resp["LastEvaluatedKey"] = {"i": start + self.page_size}
        return resp


@pytest.fixture
def table(monkeypatch):
    t = PhaseAwareTable()
    monkeypatch.setattr(eng, "table", t)
    monkeypatch.setattr(ev, "table", t)
    return t


# ── the pre-registration document and the seeder's rows ──────────────────────────────────────────────────────────


def synthetic_prereg() -> dict:
    """A document in the sealed file's shape, with stand-in call text. One operational seat and the retired seat."""
    seats = [OPERATIONAL_COACH_IDS[0], RETIRED_COACH_IDS[0]]
    coaches = {
        c: {
            "coach_name": c,
            "predictions": [
                {"claim_natural": f"Stand-in sealed call {c} {n}: hrv trends up", "metric": "hrv", "direction": "up", "window_days": 21},
                {
                    "claim_natural": f"Stand-in sealed call {c} {n + 1}: steps trend up",
                    "metric": "steps",
                    "direction": "up",
                    "window_days": 21,
                },
            ],
        }
        for n, c in enumerate(seats)
    }
    goals = json.loads((ROOT / "config" / "user_goals.json").read_text())
    return {
        "genesis": GENESIS,
        "generated_at": FREEZE_INSTANT.isoformat(),
        "coaches": coaches,
        "hypotheses": seeder.build_hypotheses(goals, series_reader=fixture_series),
    }


class _FreezeClock(datetime):
    """The freeze instant, advancing 80 ms per read (the live rows' sort keys are ~80 ms apart), so two writes in one
    run get distinct HYPOTHESIS# keys exactly as they did live."""

    ticks = 0

    @classmethod
    def now(cls, tz=None):
        cls.ticks += 1
        t = FREEZE_INSTANT + timedelta(milliseconds=80 * cls.ticks)
        return t if tz else t.replace(tzinfo=None)


def write_as_the_seeder_did(table, doc, monkeypatch) -> None:
    """The cycle-17 writes, reproduced: hypotheses through the engine's own ``store_hypothesis`` at the freeze instant
    with the wall-clock stamp (``pilot`` — the incident); predictions from ``build_prediction_records``, half stamped
    for the genesis cycle (#3874) and half with the wall-clock fallback (``pilot``). Plus an earlier cycle's sealed
    copies, tombstoned by its reset, which must stay invisible."""
    monkeypatch.setattr(eng, "datetime", _FreezeClock)
    monkeypatch.setattr(compute_metadata, "tag_record", lambda item, source_id="", **_: {**item, "phase": "pilot"})
    for hyp in doc["hypotheses"]:
        eng.store_hypothesis(dict(hyp))
    for n, rec in enumerate(seeder.build_prediction_records(doc)):
        phase = EXPERIMENT_PHASE_CURRENT if n % 2 else "pilot"
        table.put_item(Item={**rec, "phase": phase})
        old = {**rec, "sk": rec["sk"] + "_prior_cycle", "created_date": "2026-08-17", "phase": "pilot", "tombstone": True}
        table.put_item(Item=old)
    for hyp in doc["hypotheses"]:
        sk = "HYPOTHESIS#2026-08-17T16:01:44+00:00#" + hyp["hypothesis_id"]
        table.put_item(
            Item={
                **hyp,
                "pk": eng.HYPOTHESES_PK,
                "sk": sk,
                "status": "pending",
                "created_at": "2026-08-17T16:01:44+00:00",
                "phase": "pilot",
                "tombstone": True,
            }
        )


def unreachable(doc) -> list[str]:
    """Every sealed member of ``doc`` its grader cannot load, as readable identities."""
    hyp_rows = eng.load_existing_hypotheses()
    loaded = {h.get("hypothesis_id") for h in hyp_rows if not h.get("tombstone")}
    evaluable, ungradeable = ev._fetch_predictions()
    fetched = {p.get("prediction_id") for p in evaluable + ungradeable if not p.get("tombstone")}
    missing = [f"hypothesis {h['hypothesis_id']}" for h in doc["hypotheses"] if h["hypothesis_id"] not in loaded]
    missing += [f"prediction {pid}" for pid in sorted(prereg_provenance_gate.frozen_prediction_ids(doc) - fetched)]
    leaked = [f"tombstoned row loaded: {r['sk']}" for r in hyp_rows + evaluable + ungradeable if r.get("tombstone")]
    return missing + leaked


def test_every_sealed_member_of_a_preregistration_is_visible_to_its_grader(table, monkeypatch):
    """THE contract (#5518 box 3). One test over every document available — the synthetic one always, the private
    original when its bytes are the seal — reporting every unreachable member at once."""
    docs = [("synthetic", synthetic_prereg())]
    sealed = private_prereg.load_sealed()
    if sealed is not None:
        docs.append(("sealed 2026-09-06 (private original)", sealed))
    failures = []
    for label, doc in docs:
        table.items.clear()
        write_as_the_seeder_did(table, doc, monkeypatch)
        failures += [f"{label}: {m}" for m in unreachable(doc)]
    assert failures == [], "sealed rows a grader cannot see:\n" + "\n".join(failures)


def test_the_contract_document_covers_both_seams_that_hid_cycle_17(table, monkeypatch):
    """The synthetic document must exercise what went wrong: a pilot-stamped hypothesis, a pilot-stamped prediction
    and a retired seat. A fixture that stopped doing so would pass the contract vacuously."""
    doc = synthetic_prereg()
    write_as_the_seeder_did(table, doc, monkeypatch)
    rows = list(table.items.values())
    live = [r for r in rows if not r.get("tombstone")]
    assert {r.get("phase") for r in live if r["pk"] == eng.HYPOTHESES_PK} == {"pilot"}
    preds = [r for r in live if r["pk"].startswith("COACH#")]
    assert {"pilot", EXPERIMENT_PHASE_CURRENT} <= {r["phase"] for r in preds}
    assert any(r["pk"] == f"COACH#{RETIRED_COACH_IDS[0]}" for r in preds)
    assert len(doc["hypotheses"]) == 2 and len(prereg_provenance_gate.frozen_prediction_ids(doc)) == 4


# ── compute/sealed_hypotheses: who is sealed, and the window grade ───────────────────────────────────────────────────


def _hyp(**extra):
    row = {
        "pk": eng.HYPOTHESES_PK,
        "sk": f"HYPOTHESIS#{FREEZE_INSTANT.isoformat()}",
        "hypothesis_id": "genesis_prereg_h1",
        "hypothesis": "stand-in sealed hypothesis",
        "status": "pending",
        "phase": "pilot",
        "created_at": FREEZE_INSTANT.isoformat(),
        "monitoring_window_days": 30,
        "test_spec": {
            "condition_metric": "calories",
            "condition_op": "<=",
            "condition_threshold": 1500,
            "outcome_metric": "weight_lbs",
            "direction": "lower",
            "min_effect": 0.1,
            "lag_days": 1,
        },
    }
    return {**row, **extra}


def test_sealed_means_this_cycles_genesis_row_and_nothing_else():
    assert sealed_hypotheses.is_sealed(_hyp()) and sealed_hypotheses.grader_visible(_hyp())
    assert sealed_hypotheses.is_sealed(_hyp(created_at=f"{EVE}T19:13:00+00:00"))  # the freeze runs the evening before
    assert not sealed_hypotheses.is_sealed(_hyp(tombstone=True))  # an earlier cycle's copy, voided by its reset
    assert not sealed_hypotheses.is_sealed(_hyp(created_at="2026-08-17T16:01:44+00:00"))
    assert not sealed_hypotheses.is_sealed(_hyp(hypothesis_id="hyp_generated_weekly"))
    assert not sealed_hypotheses.grader_visible(_hyp(hypothesis_id="hyp_generated_weekly"))  # other pilot rows stay hidden
    assert sealed_hypotheses.grader_visible(_hyp(hypothesis_id="hyp_generated_weekly", phase=EXPERIMENT_PHASE_CURRENT))


def test_the_window_is_the_sealed_one_and_closes_after_its_last_outcome_day():
    since, last, lag = sealed_hypotheses.window_bounds(_hyp())
    assert (since, lag) == (GENESIS, 1)
    assert (date.fromisoformat(last) - date.fromisoformat(since)).days == 29  # 30 condition days, inclusive
    outcome_last = (date.fromisoformat(last) + timedelta(days=1)).isoformat()
    assert not sealed_hypotheses.window_closed(_hyp(), outcome_last)
    assert sealed_hypotheses.window_closed(_hyp(), (date.fromisoformat(outcome_last) + timedelta(days=1)).isoformat())
    assert not sealed_hypotheses.due_for_window_grade(_hyp(status="refuted"), "2026-12-31")


def _days(start: str, n: int):
    d0 = date.fromisoformat(start)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _window_data(under_target_weight: float, over_target_weight: float, *, after_window: float | None = None, zero_entry=()):
    """Alternating under/over-target calorie days across the sealed window; next-day weight follows the arm.
    ``after_window`` writes contrary data AFTER the window, which a correct grade never reads."""
    food, weight = [], []
    for i, d in enumerate(_days(GENESIS, 45)):
        in_window = i < 30
        under = i % 2 == 0
        kcal = 1400 if under else 1900
        row = {"date": d, "total_calories_kcal": kcal, "entries_count": 5}
        if d in zero_entry:
            row = {"date": d, "total_calories_kcal": 80, "entries_count": 0}
        food.append(row)
        nxt = (date.fromisoformat(d) + timedelta(days=1)).isoformat()
        w = under_target_weight if under else over_target_weight
        if not in_window and after_window is not None:
            w = after_window if under else under_target_weight - 5
        weight.append({"date": nxt, "weight_lbs": w + (i % 3) * 0.01})
    return {"macrofactor": food, "withings": weight}


def _narrate(data):
    rows = {}
    for r in data.get("macrofactor", []):
        rows.setdefault(r["date"], {"date": r["date"]})["calories"] = r["total_calories_kcal"]
    for r in data.get("withings", []):
        rows.setdefault(r["date"], {"date": r["date"]})["weight_lbs"] = r["weight_lbs"]
    return [rows[d] for d in sorted(rows)]


def _grade(data, hyp=None):
    calls = []

    def gather(start_date=None, end_date=None):
        calls.append((start_date, end_date))
        return {k: [r for r in v if start_date <= r["date"] <= end_date] for k, v in data.items()}

    out = sealed_hypotheses.grade_closed_window(hyp or _hyp(), gather, _narrate, eng.evaluate_test_spec, eng.deterministic_evidence)
    return out, calls


def test_a_closed_sealed_window_is_graded_on_its_own_days_only():
    """Data after the window says the opposite; the grade must not read it (ADR-105: the window the row sealed)."""
    (hyp, status, evidence, stats, resolution), calls = _grade(_window_data(200.0, 202.0, after_window=210.0))
    assert (status, resolution) == ("confirmed", "confirmed")
    since, last, lag = sealed_hypotheses.window_bounds(_hyp())
    assert calls == [(since, (date.fromisoformat(last) + timedelta(days=lag)).isoformat())]
    assert stats["n_condition"] + stats["n_comparison"] == 30
    assert evidence.startswith(sealed_hypotheses.LATE_GRADE_TAG) and f"window {since}..{last}" in evidence


def test_a_contradicted_sealed_window_is_refuted():
    (_h, status, _e, _s, resolution), _ = _grade(_window_data(202.0, 200.0))
    assert (status, resolution) == ("refuted", "refuted")


def test_an_inconclusive_sealed_window_is_voided_with_its_arm_counts_as_the_reason():
    data = _window_data(200.0, 202.0)
    data["withings"] = data["withings"][:6]  # almost no weigh-ins in the window
    (_h, status, evidence, stats, resolution), _ = _grade(data)
    assert (status, resolution) == ("archived", "expired_undecided")
    assert f"{stats['n_condition']} " in evidence and "per arm" in evidence


def test_a_day_with_nothing_logged_is_missing_not_an_under_target_day():
    gaps = tuple(_days(GENESIS, 30)[1::6])  # five over-target days whose food row says nothing was logged
    (_h, _status, evidence, stats, _r), _ = _grade(_window_data(200.0, 202.0, zero_entry=gaps))
    assert stats["n_condition"] + stats["n_comparison"] == 30 - len(gaps)
    assert all(g in evidence for g in gaps) and "nothing logged" in evidence


def test_a_heart_rate_outcome_across_the_regime_marker_is_voided_with_the_marker_named(monkeypatch):
    from coach import grading_quality

    monkeypatch.setattr(grading_quality, "regime_split", lambda start, end: {"marker_date": "2026-09-20"})
    hyp = _hyp(
        test_spec={
            "condition_metric": "steps",
            "condition_op": ">=",
            "condition_threshold": 6000,
            "outcome_metric": "recovery",
            "direction": "higher",
            "lag_days": 1,
        }
    )
    (_h, status, evidence, _s, resolution), calls = _grade(_window_data(1, 2), hyp)
    assert (status, resolution, calls) == ("archived", "expired_undecided", [])
    assert "2026-09-20" in evidence


def test_the_engine_grades_a_closed_sealed_row_on_its_window_without_narration(monkeypatch):
    """Wired: check_pending_hypotheses routes the sealed row through the window grade (never the trailing rows it was
    handed, never an LLM), and hard expiry leaves it to that grade."""
    data = _window_data(200.0, 202.0)
    monkeypatch.setattr(
        eng,
        "gather_data",
        lambda days=30, start_date=None, end_date=None: {k: [r for r in v if start_date <= r["date"] <= end_date] for k, v in data.items()},
    )
    monkeypatch.setattr(eng, "build_data_narrative", _narrate)
    monkeypatch.setattr(eng, "narrate_resolution", lambda *a, **k: pytest.fail("a sealed window grade is never narrated"))
    today = datetime(2026, 11, 13, 19, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(eng, "pacific_now", lambda: today)
    trailing = [{"date": d, "calories": 1400, "weight_lbs": 250.0} for d in _days("2026-10-15", 30)]
    ((hyp, status, evidence, _stats, resolution),) = eng.check_pending_hypotheses([_hyp()], trailing)
    assert (status, resolution) == ("confirmed", "confirmed") and evidence.startswith(sealed_hypotheses.LATE_GRADE_TAG)
    assert eng.enforce_hard_expiry([_hyp()]) == []
    assert eng.enforce_hard_expiry([_hyp(hypothesis_id="hyp_generated_weekly")]) != []


# ── coach/prereg_overdue: the dead-man ───────────────────────────────────────────────────────────────────────────


def _pred(**extra):
    row = {
        "pk": f"COACH#{RETIRED_COACH_IDS[0]}",
        "sk": "PREDICTION#pred_x",
        "prediction_id": "pred_x",
        "created_date": GENESIS,
        "subdomain": "steps",
        "status": "pending",
        "pre_registered": True,
        "phase": EXPERIMENT_PHASE_CURRENT,
        "evaluation": {"type": "directional", "metric": "steps", "evaluation_window_days": 21},
    }
    return {**row, **extra}


def _after(day: str, n: int) -> str:
    return (date.fromisoformat(day) + timedelta(days=n)).isoformat()


def test_a_sealed_prediction_is_overdue_only_past_its_due_date_plus_the_grace():
    due = prereg_overdue.prediction_horizon(_pred())
    edge = _after(due, prereg_overdue.PREDICTION_GRACE_DAYS)
    assert prereg_overdue.overdue(_pred(), "prediction", edge) is None
    member = prereg_overdue.overdue(_pred(), "prediction", _after(edge, 1))
    assert member == {
        "kind": "prediction",
        "pk": _pred()["pk"],
        "sk": _pred()["sk"],
        "status": "pending",
        "phase": EXPERIMENT_PHASE_CURRENT,
        "due": due,
    }


def test_rows_a_working_grader_may_leave_open_are_never_counted():
    late = "2027-06-01"
    assert prereg_overdue.overdue(_pred(status="confirmed"), "prediction", late) is None
    assert prereg_overdue.overdue(_pred(tombstone=True), "prediction", late) is None  # voided by a reset
    assert prereg_overdue.overdue(_pred(pre_registered=False), "prediction", late) is None
    assert prereg_overdue.overdue(_pred(evaluation_hold={"reason": "owner hold"}), "prediction", late) is None
    cond = _pred(evaluation={"type": "conditional", "metric": "steps", "evaluation_window_days": 21})
    due = prereg_overdue.prediction_horizon(_pred())
    assert (
        prereg_overdue.overdue(cond, "prediction", _after(due, prereg_overdue.PREDICTION_GRACE_DAYS + 1)) is None
    )  # waits for its antecedent
    assert prereg_overdue.overdue(cond, "prediction", late) is not None


def test_a_hypothesis_is_overdue_past_its_window_plus_the_weekly_grace():
    due = prereg_overdue.hypothesis_horizon(_hyp())
    assert due == _after(GENESIS, 30)
    assert prereg_overdue.overdue(_hyp(), "hypothesis", _after(due, prereg_overdue.HYPOTHESIS_GRACE_DAYS)) is None
    assert prereg_overdue.overdue(_hyp(), "hypothesis", _after(due, prereg_overdue.HYPOTHESIS_GRACE_DAYS + 1))["due"] == due
    assert prereg_overdue.overdue(_hyp(test_spec=None), "hypothesis", "2027-01-01") is None  # v1: no frozen spec


def test_the_scan_is_phase_blind_and_counts_retired_seats_and_hypotheses(table):
    """The incident's exact rows: a pilot-stamped sealed hypothesis and a sealed bet on the retired seat."""
    table.put_item(Item=_pred())
    table.put_item(Item=_pred(sk="PREDICTION#done", status="refuted"))
    table.put_item(Item=_hyp())
    out = prereg_overdue.scan(table, ev.GRADING_COACH_IDS, ev.HYPOTHESES_PK, "2026-11-13")
    assert out["count"] == 2 and {m["kind"] for m in out["members"]} == {"prediction", "hypothesis"}
    assert not any("FilterExpression" in q for q in table.queries)


class _CW:
    def __init__(self):
        self.calls = []

    def put_metric_data(self, **kwargs):
        self.calls.append(kwargs)


class _Log:
    def __init__(self):
        self.lines = []

    def warning(self, msg, *args):
        self.lines.append(msg % args)


def test_every_completed_scan_emits_the_count_and_names_each_member():
    cw, log = _CW(), _Log()
    member = prereg_overdue.overdue(_pred(), "prediction", "2026-11-13")
    out = prereg_overdue.emit(cw, {"count": 1, "members": [member], "as_of": "2026-11-13"}, log)
    assert out == {"count": 1, "as_of": "2026-11-13"}
    assert cw.calls == [
        {"Namespace": "LifePlatform/Predictions", "MetricData": [{"MetricName": "PreRegisteredOverdue", "Value": 1.0, "Unit": "Count"}]}
    ]
    assert _pred()["sk"] in log.lines[0]
    prereg_overdue.emit(cw, {"count": 0, "members": [], "as_of": "2026-11-13"}, log)
    assert cw.calls[-1]["MetricData"][0]["Value"] == 0.0  # a zero is a datapoint, not silence


def test_a_failed_read_raises_so_no_comforting_zero_is_emitted():
    class Broken:
        def query(self, **_):
            raise RuntimeError("throttled")

    with pytest.raises(RuntimeError):
        prereg_overdue.scan(Broken(), ["sleep_coach"], ev.HYPOTHESES_PK, "2026-11-13")


def test_the_alarm_is_named_and_windowed_by_the_emitting_module():
    src = (ROOT / "cdk" / "stacks" / "monitoring_prediction_alarms.py").read_text()
    calls = [n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and any(k.arg == "alarm_name" for k in n.keywords)]
    names = {k.value.value for c in calls for k in c.keywords if k.arg == "alarm_name" and isinstance(k.value, ast.Constant)}
    assert prereg_overdue.ALARM_NAME in names
    assert "prereg_overdue.METRIC" in src and "prereg_overdue.NAMESPACE" in src and "prereg_overdue.ALARM_PERIODS" in src
    assert prereg_overdue.NAMESPACE == ev.LIVENESS_NAMESPACE
    assert prereg_overdue.ALARM_PERIODS * prereg_overdue.PERIOD_SECONDS <= 604800  # CloudWatch's ceiling (#3685)


def test_decimal_rows_from_dynamodb_are_read_the_same():
    row = _pred(evaluation={"type": "directional", "metric": "steps", "evaluation_window_days": Decimal("21")})
    assert prereg_overdue.prediction_horizon(row) == prereg_overdue.prediction_horizon(_pred())
    assert prereg_overdue.hypothesis_horizon(_hyp(monitoring_window_days=Decimal("30"))) == _after(GENESIS, 30)
