"""#6156 — the platform's forecast rule: public-input forecasts readers can call beside (owner requirements 2026-11-21).

The owner's ten requirements, each proved here on the producer's real code (``coach.public_forecast``):

  1. public-only input lineage — the input is the served ``/api/series`` wire shape; the row stores URL, window, values
     and a reproducible SHA-256; a metric the route's catalogue does not serve, or one not classified public, is refused;
  2. identified model and prompt version — ``model.id``/``version``; ``prompt_version`` null with its reason;
  3. immutable timestamp — the write is ``attribute_not_exists(sk)``; a re-run finds it and changes nothing;
  4. a clear prediction and target — a number call (``point`` spec) on a stated day;
  5. a frozen evaluation method — the spec, the head-to-head scoring rule (owner ruling 2026-11-22 §5), the guess's
     value and the evaluation sentence are on the row at filing;
  6. publication through the existing rules — ``prediction_publication`` classifies the rows PRIVATE while the stream's
     committed switch is off, by structure once on;
  7. a meaningful submission window — the REAL reader-call rule (``open_until``) leaves the door open >= 2 days, for
     every filing weekday and every rule;
  8. an outcome unknown at registration — the data ends the day before filing; a reading on or after it is never read;
  9. a verifiable final result — graded by the one grader (tests/test_coach_prediction_evaluator_behavior.py
     ``TestPublicForecastIsGradedByThisGrader``);
 10. a comparison with the baseline — the "nothing changes" value is frozen at filing (the same function the grader
     stamps with).
Plus: both switches default off and fail closed; the owner's record reads (ledger export, /api/predictions,
/api/calibration, the calibration headline) are byte-identical with and without forecast rows; the dry-run CLI writes
nothing and creates no AWS client; the dead-man.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))
sys.path.insert(0, os.path.join(_REPO, "scripts"))

from coach import coach_baseline, prediction_windows, public_forecast as F  # noqa: E402
from common import prediction_publication as PP, public_brief_policy as BPOL, public_forecast_policy as FP  # noqa: E402
from web import reader_call_rules as R  # noqa: E402

TODAY = "2026-11-23"  # a Monday: the scheduled filing day
CYCLE = "2026-11-23"


def _payload(metric, values, end, *, unit="lb", source="withings", extra=None):
    """The ``/api/series`` wire shape (web.site_api_series.handle_series), one row per day ending on ``end``."""
    e = datetime.strptime(end, "%Y-%m-%d")
    days = []
    for i, v in enumerate(values):
        d = (e - timedelta(days=len(values) - 1 - i)).strftime("%Y-%m-%d")
        days.append({"date": d, "value": v, "present": v is not None, "gap": False})
    days += extra or []
    return {"metric": metric, "unit": unit, "source_id": source, "method_ids": [], "as_of": end, "window": {}, "days": days}


WEIGHT = [300.0 - 0.3 * i + (0.5 if i % 2 else -0.5) for i in range(30)]
RECOVERY = [60.0 + (i % 7) * 3 for i in range(30)]
SLEEP = [7.0 + (i % 5) * 0.2 for i in range(30)]
SERIES = {"weight_lbs": WEIGHT, "recovery_score": RECOVERY, "sleep_duration_hours": SLEEP}


def _fetch(today=TODAY, *, served=None, fail=()):
    """A fake HTTPS GET over the real wire shapes: the catalogue, and each series through the day before ``today``."""
    calls = []

    def fetch(url):
        calls.append(url)
        if url.endswith(F.ROUTE):
            keys = served if served is not None else list(SERIES)
            return {"metrics": [{"metric": k} for k in keys]}
        metric = url.split("metric=")[1].split("&")[0]
        if metric in fail:
            raise OSError("unreachable")
        through = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        return _payload(metric, SERIES[metric], through)

    fetch.calls = calls
    return fetch


class Table:
    """Append-only aware: honours ``attribute_not_exists(sk)`` the way DynamoDB does."""

    def __init__(self):
        self.store, self.writes = {}, []

    def put_item(self, Item, ConditionExpression=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.store:
            raise RuntimeError("ConditionalCheckFailedException")
        self.writes.append(key)
        self.store[key] = Item

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": item} if item else {}


def _rows(today=TODAY, **kw):
    out = F.run(None, today=today, persist=False, fetch_json=_fetch(today, **kw))
    assert out["status"] == "ok", out
    return out, out["forecasts"]


# ── the switches ──────────────────────────────────────────────────────────────────────────────────


def test_the_committed_switch_is_on_for_the_pilot_and_an_off_run_reads_and_writes_nothing(monkeypatch):
    # The owner switched the one-a-week pilot on (2026-11-22, #6156). Rollback = STREAM_LIVE = False + redeploy
    # (or the runtime kill switch /life-platform/public-forecast). OFF behaviour is proven below with it set False.
    assert FP.STREAM_LIVE is True, "the pilot is committed ON; rollback is this line -> False"
    monkeypatch.setattr(FP, "STREAM_LIVE", False)
    table, fetch = Table(), _fetch()
    assert F.run(table, today=TODAY, fetch_json=fetch, switch=lambda: True) == {"status": "off", "reason": "committed_switch_off"}
    monkeypatch.setattr(FP, "STREAM_LIVE", True)
    assert F.run(table, today=TODAY, fetch_json=fetch, switch=lambda: False)["reason"] == "runtime_switch_off"
    assert fetch.calls == [] and table.writes == []


@pytest.mark.parametrize("value,on", [("on", True), (" on ", True), ("On", False), ("yes", False), ("", False), (None, False)])
def test_the_runtime_switch_opens_only_on_the_literal_on(value, on):
    param = {} if value is None else {"Parameter": {"Value": value}}
    assert F.runtime_switch_on(lambda **_: param) is on


def test_an_unreadable_or_absent_runtime_switch_is_off():
    def boom(**_):
        raise RuntimeError("ParameterNotFound")

    assert F.runtime_switch_on(boom) is False


def test_a_live_run_files_append_only_and_a_rerun_changes_nothing(monkeypatch):
    monkeypatch.setattr(FP, "STREAM_LIVE", True)
    table = Table()
    first = F.run(table, today=TODAY, fetch_json=_fetch(), switch=lambda: True)
    assert {v["status"] for v in first["results"].values()} == {"written"}
    assert len(table.writes) == len(F.picks(CYCLE)) == FP.FORECASTS_PER_CYCLE == 1, "the pilot: one forecast a week"
    before = {k: dict(v) for k, v in table.store.items()}
    again = F.run(table, today=TODAY, fetch_json=_fetch(), switch=lambda: True)
    assert {v["status"] for v in again["results"].values()} == {"exists"}
    assert {k: dict(v) for k, v in table.store.items()} == before, "created_at and every field are immutable"
    later = F.run(table, today="2026-11-25", fetch_json=_fetch("2026-11-25"), switch=lambda: True)
    assert {v["status"] for v in later["results"].values()} == {"exists"}, "one forecast per rule per cycle"
    assert all(k[0] == FP.FORECAST_PK for k in table.store), "never a COACH#, never a USER# health partition"


# ── the record ────────────────────────────────────────────────────────────────────────────────────


def test_the_record_carries_every_field_the_owner_asked_for():
    _out, rows = _rows()
    assert [r["rule_id"] for r in rows] == F.picks(CYCLE)
    for row in rows:
        rule = F.RULES[row["rule_id"]]
        spec = row["evaluation"]
        assert row["pk"] == FP.FORECAST_PK and row["sk"] == FP.SK_PREFIX + row["prediction_id"]
        assert row["coach_id"] == "" and row["author"] == FP.AUTHOR_ID and "coach" not in row["author_words"].lower()
        assert row["author_words"] == "Rules-based platform forecast" and row["label"] == "rules-based platform forecast"
        assert row["record"] == FP.RECORD == "platform_forecast"
        assert row["source"] == FP.FORECAST_SOURCE and row["status"] == "pending" and row["gradeable_by"] == "deterministic"
        assert row["filing"]["verdict"] == "gradeable" and row["created_date"] == TODAY and row["created_at"]
        # model + prompt version
        m = row["model"]
        assert m["id"] == f"forecast_rule.{row['rule_id']}" and m["version"] == F.RULESET_VERSION and m["kind"] == "deterministic_rule"
        assert m["prompt_version"] is None and "no language model" in m["prompt_version_note"]
        # a clear prediction and target, frozen evaluation
        assert spec["type"] == "point" and spec["metric"] == rule["metric"]
        assert spec["target_date"] == "2026-11-30" and spec["evaluation_window_days"] == F.HORIZON_DAYS
        # the frozen head-to-head rule replaces the ±1 SD band (owner ruling 2026-11-22 §5), recorded with its version
        assert "tolerance" not in spec and "tolerance_rule" not in spec, "nothing may grade a forecast by the SD band"
        assert spec["scoring"] == FP.SCORING_RULE and spec["scoring_version"] == FP.SCORING_VERSION == 1
        assert row["scoring"] == {"rule": FP.SCORING_RULE, "version": 1, "words": FP.SCORING_WORDS, "frozen_at": "filing"}
        assert (
            spec["baseline_value"] == row["baseline_at_filing"]["filed_value"]
            and spec["baseline_on"] == row["baseline_at_filing"]["filed_on"]
        )
        assert row["claim_natural"].endswith("on 2026-11-30.") and "closer to" in row["evaluation_rule"]
        # lineage: public only, reproducible
        lin = row["lineage"]
        assert lin["public_only"] is True and lin["route"] == "/api/series" and f"metric={rule['metric']}" in lin["url"]
        canon = json.dumps(lin["readings"], separators=(",", ":")).encode()
        assert lin["sha256"] == hashlib.sha256(canon).hexdigest() and lin["n"] == len(lin["readings"])
        assert lin["window"]["to"] == "2026-11-22" and all(d < TODAY for d, _v in lin["readings"])
        # the baseline, frozen now by the grader's own function
        series = [tuple(x) for x in lin["readings"]]
        assert (row["baseline_at_filing"]["filed_value"], row["baseline_at_filing"]["filed_on"], None) == coach_baseline.filed_reading(
            series, rule["metric"], TODAY
        )
        assert row["baseline_at_filing"]["rule"] == coach_baseline.RULE_ID


def test_the_weight_rule_is_the_least_squares_line_read_on_the_target_day():
    rows = [(f"2026-11-{d:02d}", 200.0 - 0.5 * (d - 1)) for d in range(1, 15)]
    assert F.fit("linear_trend", rows, "2026-11-21") == pytest.approx(200.0 - 0.5 * 20)
    assert F.fit("trailing_mean", [("a", 1.0), ("b", 3.0)], "x") == 2.0
    assert F.fit("linear_trend", rows[:1], "2026-11-21") is None and F.fit("unknown", rows, "2026-11-21") is None


def test_an_outcome_already_on_record_is_never_an_input():
    """The payload carries readings on and after the filing day (and the target day itself): none is read."""
    late = [{"date": d, "value": 999.0, "present": True, "gap": False} for d in (TODAY, "2026-11-27", "2026-11-30")]
    row, why = F.build("weight_trend", TODAY, _payload("weight_lbs", WEIGHT, "2026-11-22", extra=late), "u", CYCLE, phase_stamp=False)
    assert why is None and 999.0 not in [v for _d, v in row["lineage"]["readings"]]
    assert row["evaluation"]["target_date"] > TODAY


@pytest.mark.parametrize(
    "case,payload,reason",
    [
        ("stale", _payload("weight_lbs", WEIGHT, "2026-11-18"), "inputs_stale"),
        ("thin", _payload("weight_lbs", [None] * 24 + WEIGHT[-6:], "2026-11-22"), "too_few_readings"),
        ("empty", {"days": []}, "inputs_stale"),
    ],
)
def test_thin_or_stale_inputs_hold_the_rule(case, payload, reason):
    assert F.build("weight_trend", TODAY, payload, "u", CYCLE, phase_stamp=False) == (None, reason), case


def test_a_metric_the_public_route_does_not_serve_or_cannot_be_read_is_held(monkeypatch):
    out = F.run(None, today=TODAY, persist=False, fetch_json=_fetch(served=["recovery_score"]))
    assert out["results"]["weight_trend"] == {"status": "held", "reason": "not_served_publicly"}
    monkeypatch.setattr(FP, "FORECASTS_PER_CYCLE", 2)  # the second rule is still available, only off in the pilot
    second = F.picks(CYCLE)[1]
    out = F.run(None, today=TODAY, persist=False, fetch_json=_fetch(fail=(F.RULES[second]["metric"],)))
    assert out["results"][second]["status"] == "held" and out["results"]["weight_trend"]["status"] == "dry_run"


# ── registry + derivation ─────────────────────────────────────────────────────────────────────────


def test_every_rule_reads_a_key_the_public_series_route_offers_and_the_policy_calls_public():
    from coach import public_brief as PB
    from web import site_api_series as S

    for rule_id, rule in F.RULES.items():
        assert rule["metric"] in S.SERIES and S.publishable(S.SERIES[rule["metric"]]), rule_id
        assert BPOL.metric_is_eligible(rule["metric"]) and rule["metric"] in PB.METRIC_WORDS, rule_id
    assert set(F.ALWAYS) | set(F.ALTERNATE) == set(F.RULES)


def test_the_pilot_files_weight_only_and_the_second_rule_stays_available_but_off():
    cycles = [(datetime(2026, 11, 23) + timedelta(days=7 * i)).strftime("%Y-%m-%d") for i in range(8)]
    assert FP.FORECASTS_PER_CYCLE == 1, "owner ruling 2026-11-22 §5: a limited one-forecast-per-week pilot"
    assert all(F.picks(c) == ["weight_trend"] for c in cycles)
    seen = [F.picks(c, per_cycle=2) for c in cycles]  # the rotation, were the policy constant raised
    assert all(len(p) == 2 and p[0] == "weight_trend" for p in seen)
    assert {p[1] for p in seen} == set(F.ALTERNATE)
    assert F.picks(cycles[0], per_cycle=9) == seen[0], "never more than MAX_PER_CYCLE"


# ── the reader window, by the REAL reader-call rule ───────────────────────────────────────────────


def test_every_filing_day_leaves_the_reader_door_open_at_least_two_days():
    assert F.HORIZON_DAYS >= R.SHORT_WINDOW_DAYS, "a window of at least four days, so the midpoint rule applies"
    for offset in range(7):  # whichever day of the cycle the run lands on
        today = (datetime(2026, 11, 23) + timedelta(days=offset)).strftime("%Y-%m-%d")
        out = F.run(None, today=today, persist=False, fetch_json=_fetch(today))
        assert len(out["forecasts"]) == FP.FORECASTS_PER_CYCLE, out["results"]
        for row in out["forecasts"]:
            spec, sub = row["evaluation"], row["subdomain"]
            eff = prediction_windows.effective_window_days(spec, sub)
            due = prediction_windows.due_date(today, spec, sub)
            last = R.open_until(spec, today, eff, due)
            assert R.call_kind(spec) == R.CLOSER and last == row["submission_window"]["closes"]
            assert (datetime.strptime(last, "%Y-%m-%d") - datetime.strptime(today, "%Y-%m-%d")).days + 1 >= F.MIN_OPEN_DAYS
            assert R.is_open(row, row["status"], last, today) and not R.is_open(row, row["status"], last, due)
            assert due == row["submission_window"]["result_due"] == spec["target_date"]


# ── publication through the existing gate ─────────────────────────────────────────────────────────


def test_the_publication_gate_keeps_forecasts_private_until_the_stream_is_on(monkeypatch):
    _out, rows = _rows()
    row = rows[0]
    assert PP.governs_partition(FP.FORECAST_PK) and PP.kind_of(FP.FORECAST_PK, row["sk"]) == PP.CALL
    assert PP.kind_of(FP.FORECAST_PK, FP.run_sk(CYCLE)) is None
    monkeypatch.setattr(FP, "STREAM_LIVE", False)
    assert PP.classify(row["pk"], row) == (PP.PRIVATE, FP.DARK_REASON)
    monkeypatch.setattr(FP, "STREAM_LIVE", True)
    assert PP.classify(row["pk"], row) == (PP.PUBLIC, "structured_public")


# ── the calibration sample and the owner's record do not move ─────────────────────────────────────


@pytest.mark.parametrize("live", [False, True])
def test_owner_record_reads_are_identical_with_and_without_forecast_rows(monkeypatch, live):
    from reader_call_support import GENESIS, _table
    from test_reader_call_6088 import _owner_reads
    from web import site_api_common

    monkeypatch.setattr(site_api_common, "EXPERIMENT_START", GENESIS)
    monkeypatch.setattr(FP, "STREAM_LIVE", live)
    _raw0, bare = _table()
    raw1, with_forecasts = _table()
    _out, rows = _rows()
    for row in rows:
        raw1.store[(row["pk"], row["sk"])] = json.loads(json.dumps(row, default=float))
    assert any(k[0] == FP.FORECAST_PK for k in raw1.store), "the comparison must actually carry forecast rows"
    assert _owner_reads(monkeypatch, bare) == _owner_reads(monkeypatch, with_forecasts)


# ── the dry-run CLI ───────────────────────────────────────────────────────────────────────────────


def test_the_dry_run_cli_prints_lineage_writes_nothing_and_creates_no_aws_client(monkeypatch, capsys):
    import boto3
    import public_forecast_dry_run as cli

    def no_aws(*a, **k):
        raise AssertionError("the dry run must not create an AWS client")

    monkeypatch.setattr(boto3, "client", no_aws)
    monkeypatch.setattr(boto3, "resource", no_aws)
    real_run = F.run
    monkeypatch.setattr(F, "run", lambda table, **kw: real_run(table, **{**kw, "fetch_json": _fetch(kw["today"])}))
    assert cli.main(["--today", TODAY]) == 0
    out = capsys.readouterr().out
    assert "Rules-based platform forecast" in out and "sha256" in out and "prompt_version: None" in out
    assert "closer_than_nothing_changes v1" in out
    assert "open_until=2026-11-26 (4 days open)" in out and "On 30 November, will the weight" in out


# ── the dead-man ──────────────────────────────────────────────────────────────────────────────────


class _Check:
    def __init__(self, name, cat, tier):
        self.state, self.msg = None, ""

    def ok(self, m=""):
        self.state, self.msg = "ok", m

    def warn(self, m=""):
        self.state, self.msg = "warn", m

    def fail(self, m=""):
        self.state, self.msg = "fail", m


def _judge(table, live=True, day="2026-11-23", hh=11):
    from common.pacific_time import PACIFIC
    from operational import public_brief_qa as QA

    now = lambda: datetime.strptime(f"{day} {hh:02d}:30", "%Y-%m-%d %H:%M").replace(tzinfo=PACIFIC)  # noqa: E731
    return QA.check_public_forecast_liveness(table, _Check, "content", now, live=live)[0]


def test_the_dead_man_is_quiet_while_off_and_loud_when_a_live_week_is_missing(monkeypatch):
    assert _judge(Table(), live=False).state == "ok"
    assert _judge(Table()).state == "fail", "live and no stamp after the Monday deadline"
    monkeypatch.setattr(FP, "STREAM_LIVE", True)
    table = Table()
    F.stamp(table, TODAY, F.run(table, today=TODAY, fetch_json=_fetch(), switch=lambda: True))
    assert _judge(table).state == "ok"
    table.store = {k: v for k, v in table.store.items() if not k[1].startswith(FP.SK_PREFIX)}
    assert _judge(table).state == "fail", "a stamp that says written with no row behind it"
    off = Table()
    F.stamp(off, TODAY, F.run(off, today=TODAY, fetch_json=_fetch(), switch=lambda: False))
    assert _judge(off).state == "warn"
    held = Table()
    F.stamp(held, TODAY, F.run(held, today=TODAY, fetch_json=_fetch(served=[]), switch=lambda: True))
    assert _judge(held).state == "warn"
    broken = Table()
    F.stamp(broken, TODAY, {"status": "error", "error": "boom", "cycle": CYCLE})
    assert _judge(broken).state == "fail"


def test_the_monday_door_runs_the_stream_after_the_brief_and_stamps_only_when_committed_on(monkeypatch):
    """public_brief.handle_event's scheduled path: committed off -> no forecast read or write at all."""
    import common.pacific_time as pt
    from coach import public_brief as PB

    monkeypatch.setattr(pt, "pacific_today", lambda: TODAY)
    monkeypatch.setattr(PB, "run", lambda table, **kw: {"status": "ok", "cycle": CYCLE, "results": {}})
    monkeypatch.setattr(PB, "stamp_run", lambda *a, **k: True)
    monkeypatch.setattr(FP, "STREAM_LIVE", False)
    table = Table()
    out = PB.handle_event(table, {"mode": "public_brief"})
    assert out["forecast"] == {"status": "off", "reason": "committed_switch_off"} and table.writes == []
    monkeypatch.setattr(FP, "STREAM_LIVE", True)
    monkeypatch.setattr(F, "runtime_switch_on", lambda get_parameter=None: False)
    real_run = F.run
    monkeypatch.setattr(F, "run", lambda t, **kw: real_run(t, **kw, switch=F.runtime_switch_on))
    out = PB.handle_event(table, {"mode": "public_brief"})
    assert out["forecast"]["reason"] == "runtime_switch_off" and table.writes == [(FP.FORECAST_PK, FP.run_sk(CYCLE))]
