"""tests/test_coach_input_premises_4185.py — #4185: coach inputs read the served facts.

The served coach corpus on 2026-09-25/26 stated premises the engine's own served numbers
contradicted. This file pins the INPUT side of the fix (acceptance boxes 1 and 3) plus the
protein / days-logged half of the generation-time gate (box 2):

  (a) READER: the daily nutrition coach was handed yesterday's single MacroFactor row and
      no logging record (`ai.ai_context._build_nutrition_data`), so its only notion of the
      last log was its own carried threads — "Six days without logs" beside a served
      record of 20/20 logged days. It now gets the record `/api/nutrition_overview` serves,
      from the SAME derivation (`health.nutrition_logging`). Fixture: the live 09-26 JSON.
  (b) READER: `sleep_start` reached coach prompts as a raw UTC instant (04:45Z, read as a
      "4:45 AM onset"; it is 9:45 PM PT). Every sleep instant is now a labelled PT time at
      the input boundary (`coach.coach_input_facts.coach_inputs`).
  (c) GATE: a cited protein / days-logged / logging-gap figure is judged against the served
      fact for the window the sentence names, tolerance = the fact's own 95% CI, and a miss
      regenerates-or-holds through `ai_calls._enforce_quality_gate` (ADR-108).
  (d) data_through: the OUTPUT# writer stamps it beside created_at, and both read sites
      (`/api/coaching-dashboard`, `/api/coach/{id}`) serve it — a plain producer→consumer
      contract test (see `test_data_through_*` for why not a pair_contract registry entry).

Each fix carries a mutation control: the old reader / old behaviour is re-run and the
assertion that defends the fix is shown to go red against it.

Offline: no AWS. boto3 and call_anthropic are fakes wherever the pipeline runs.
"""

import json
import os
import sys
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

from ai import ai_calls, ai_context  # noqa: E402
from coach import coach_input_facts as ci, coach_state_updater  # noqa: E402
from health import nutrition_logging as nl  # noqa: E402

_FIXTURE = os.path.join(_REPO, "tests", "fixtures", "coach_input_premises_4185", "api_nutrition_overview_2026-09-26.json")
with open(_FIXTURE, encoding="utf-8") as _fh:
    LIVE = json.load(_fh)

# The rows as the partition keys them, rebuilt from the served trend (one row per day).
ALL_ROWS = [
    {
        "pk": "USER#matthew#SOURCE#macrofactor",
        "sk": f"DATE#{r['date']}",
        "date": r["date"],
        "total_protein_g": r["protein_g"],
        "total_calories_kcal": r["calories"],
    }
    for r in LIVE["nutrition_trend"]
]


def _rows_through(day):
    return [r for r in ALL_ROWS if r["date"] <= day]


# The 09-25 daily brief ran at 17:00Z = 10:00 PT: its data day was 09-24 ("yesterday")
# and 09-25's intake had not been uploaded yet (the by-design end-of-day lag).
BRIEF_TODAY = "2026-09-25"
BRIEF_DATA_DAY = "2026-09-24"
ROWS_0925 = _rows_through(BRIEF_DATA_DAY)

# The live sentences (#4185 items 1 and 3), verbatim from the saved served JSON.
WEBB_0925 = (
    "The food log went dark after September 19th, and that silence tells me I can't verify what happened to his "
    "protein intake during the gap. His protein EWMA sits at 154g from 19 logged days, but the … Six days without "
    "logs tells us nothing about what actually happened to protein intake during that window."
)
ELI_0921 = (
    "The signal I'm watching most closely right now is protein: his average intake has dropped to 106.9 grams "
    "across 14 logged days, well short of the 170-gram floor that preserves lean mass during a deficit."
)
OKAFOR_0925 = "I'm watching his protein intake climb to 154 g/day, but the clinical gate I set in September remains in place."


@pytest.fixture(autouse=True)
def _fresh_run_facts():
    ci._run.clear()
    yield
    ci._run.clear()


def _facts(day, today):
    return ci.served_run_facts({"date": day, "macrofactor_window": _rows_through(day)}, today=today)


# ══════════════════════════════════════════════════════════════════════════════
# (a) the days-logged / last-log reader is the served derivation
# ══════════════════════════════════════════════════════════════════════════════


def test_the_shared_derivation_reproduces_the_served_record():
    """The live 09-26 read (16:46Z = 09:46 PT): served days_logged 20, latest 09-25,
    lag_days 1, stalled false, avg_protein_g 153.3 — `health.nutrition_logging` over the
    same rows gives the same record, and so does the coach's prompt-facing copy."""
    rec = nl.logging_record(ALL_ROWS, "2026-09-26", stale_hours=96)
    served = LIVE["nutrition"]
    assert rec["days_logged"] == served["days_logged"] == 20
    assert rec["latest_date"] == served["latest_date"] == "2026-09-25"
    assert rec["lag_days"] == served["lag_days"] == 1
    assert rec["stalled"] is served["stalled"] is False
    assert rec["today_pending"] is served["today_pending"] is True
    coach_rec = ci.nutrition_record(ALL_ROWS, "2026-09-26")
    assert coach_rec["days_logged"] == 20 and coach_rec["latest_log_date"] == "2026-09-25" and coach_rec["lag_days"] == 1
    assert coach_rec["protein_avg_g"] == served["avg_protein_g"] == 153.3


def test_nutrition_overview_serves_the_shared_derivation(monkeypatch):
    """The ENDPOINT itself, driven through its real handler with a frozen clock, serves
    exactly `nutrition_logging.logging_record` — one derivation, not two that agree."""
    from web import site_api_common as sac, site_api_nutrition as nut

    now = datetime(2026, 9, 26, 16, 46, 44, tzinfo=timezone.utc)

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz else now.replace(tzinfo=None)

    monkeypatch.setattr(nut, "datetime", _Frozen)
    monkeypatch.setattr(sac, "datetime", _Frozen)
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-09-06")
    monkeypatch.setattr(nut, "_get_profile", lambda: {"protein_target_g": 190, "protein_floor_g": 170, "height_inches": 72})

    def _qs(source, start, end, include_pilot=None):
        return [dict(r) for r in ALL_ROWS if start <= r["date"] <= end] if source == "macrofactor" else []

    resp = nut.nutrition_overview(_g={"_query_source": _qs, "_experiment_date": sac._experiment_date})
    served = json.loads(resp["body"])["nutrition"]
    rec = nl.logging_record(ALL_ROWS, "2026-09-26")
    for key in ("days_logged", "latest_date", "lag_days", "stalled", "today_pending"):
        assert served[key] == rec[key], key
    # The coach-side window rule is the endpoint's `_experiment_date(30)`, not a copy that drifts.
    assert nl.window_start("2026-09-26", "2026-09-06") == sac._experiment_date(30)


def _assert_the_gap_premise_is_contradicted_by_the_input(domain_data):
    """What the nutrition coach is GIVEN on 09-25 must itself say the log is current:
    the last log was 09-24 (yesterday) and the lag is the one-day upload lag."""
    rec = (domain_data or {}).get("logging_record") or {}
    assert rec.get("latest_log_date") == BRIEF_DATA_DAY, rec
    assert rec.get("lag_days") == 1 and rec.get("days_logged") == 19 and rec.get("stalled") is False, rec


def test_the_nutrition_coach_input_carries_the_served_logging_record(monkeypatch):
    monkeypatch.setattr(ci, "pacific_today", lambda: BRIEF_TODAY)
    data = {"date": BRIEF_DATA_DAY, "macrofactor": ROWS_0925[-1], "macrofactor_window": ROWS_0925}
    domain = ci.coach_inputs("nutrition_coach", ai_context._build_nutrition_data(data), data)
    _assert_the_gap_premise_is_contradicted_by_the_input(domain)
    assert "the gap is closed" in domain["logging_record"]["note"]


def test_mutation_control_the_old_reader_reinstates_the_false_gap(monkeypatch):
    """MUTATION CONTROL: the old reader (the bare `_build_nutrition_data`, no record) gives
    the coach nothing that contradicts a carried "dark since 09-19" thread — red."""
    monkeypatch.setattr(ci, "pacific_today", lambda: BRIEF_TODAY)
    data = {"date": BRIEF_DATA_DAY, "macrofactor": ROWS_0925[-1], "macrofactor_window": ROWS_0925}
    with pytest.raises(AssertionError):
        _assert_the_gap_premise_is_contradicted_by_the_input(ai_context._build_nutrition_data(data))


def test_only_the_nutrition_coach_gets_the_logging_record(monkeypatch):
    monkeypatch.setattr(ci, "pacific_today", lambda: BRIEF_TODAY)
    data = {"date": BRIEF_DATA_DAY, "macrofactor_window": ROWS_0925}
    assert "logging_record" not in ci.coach_inputs("sleep_coach", {"hrv": 50}, data)


def test_a_failed_read_is_absence_never_an_empty_log(monkeypatch):
    """No table / a failing read → the record is None (unknown), never days_logged 0."""
    monkeypatch.setattr(ci, "pacific_today", lambda: BRIEF_TODAY)
    table = MagicMock()
    table.query.side_effect = RuntimeError("no DDB")
    out = ci.coach_inputs("nutrition_coach", {}, {"date": BRIEF_DATA_DAY}, table=table)
    assert out["logging_record"] is None
    assert ci.coach_inputs("nutrition_coach", {}, {"date": "2026-09-23"}, table=None)["logging_record"] is None


def test_the_window_read_paginates_and_drops_tombstones(monkeypatch):
    pages = [
        {"Items": ROWS_0925[:10], "LastEvaluatedKey": {"sk": ROWS_0925[9]["sk"]}},
        {"Items": ROWS_0925[10:] + [{**ROWS_0925[0], "sk": "DATE#2026-09-06", "tombstone": True}]},
    ]
    table = MagicMock()
    table.query.side_effect = pages
    rows = ci.fetch_macrofactor_window(table, BRIEF_TODAY)
    assert len(rows) == 19 and table.query.call_count == 2
    assert table.query.call_args_list[1].kwargs["ExclusiveStartKey"] == {"sk": ROWS_0925[9]["sk"]}


# ══════════════════════════════════════════════════════════════════════════════
# (b) sleep instants reach every coach prompt in PT
# ══════════════════════════════════════════════════════════════════════════════

SLEEP_START_UTC = "2026-09-24T04:45:00Z"  # the issue's instant: 21:45 PT on 09-23


def test_a_sleep_instant_is_rendered_as_a_labelled_pt_time():
    out = ci.localize_sleep_instants({"sleep_start": SLEEP_START_UTC, "nested": {"sleep_onset_times": [SLEEP_START_UTC]}, "hrv": 50})
    assert out["sleep_start"] == "Sep 23, 9:45 PM PT"
    assert out["nested"]["sleep_onset_times"] == ["Sep 23, 9:45 PM PT"]
    assert out["hrv"] == 50
    assert "04:45" not in json.dumps(out)


def test_a_day_or_a_non_sleep_key_is_left_alone():
    src = {"sleep_start": "2026-09-24", "computed_at": "2026-09-24T04:45:00Z", "sleep_duration_hours": 7.5}
    assert ci.localize_sleep_instants(src) == src


def _pipeline_env(monkeypatch, generation_text, rows=None):
    """`_run_coach_v2_pipeline` over fakes (the #952 harness shape): lambda invokes,
    S3 voice spec, a table that serves macrofactor rows and fails every other read."""
    monkeypatch.setattr(ai_calls, "_comp_results_cache", {"trends": {}})
    monkeypatch.setattr(ci, "pacific_today", lambda: BRIEF_TODAY)
    fake_lambda = MagicMock()
    events = []

    def _invoke(**kwargs):
        fn = kwargs["FunctionName"]
        events.append((fn, json.loads(kwargs["Payload"])))
        payload = MagicMock()
        if fn == "coach-narrative-orchestrator":
            brief = {"generation_brief": {"voice_guidance": {}, "decision_class_ceiling": "observational"}}
            payload.read.return_value = json.dumps({"body": json.dumps(brief)}).encode()
        elif fn == "coach-quality-gate":
            payload.read.return_value = json.dumps({"statusCode": 200, "passed": True, "score": 90}).encode()
        else:
            payload.read.return_value = b"{}"
        return {"Payload": payload}

    fake_lambda.invoke.side_effect = _invoke
    fake_s3 = MagicMock()
    body = MagicMock()
    body.read.return_value = json.dumps(
        {"display_name": "Dr. Test", "domain": "test", "structural_voice_rules": {}, "decision_style": {}, "anti_pattern_detection": {}}
    ).encode()
    fake_s3.get_object.return_value = {"Body": body}

    def _query(**kw):
        cond = kw["KeyConditionExpression"].get_expression()
        pk_cond = cond["values"][0] if cond.get("operator") == "AND" else kw["KeyConditionExpression"]
        pk = pk_cond.get_expression()["values"][1]
        if pk == "USER#matthew#SOURCE#macrofactor" and rows is not None:
            return {"Items": [dict(r) for r in rows]}
        raise RuntimeError("no DDB in tests")

    table = MagicMock()
    table.query.side_effect = _query
    table.get_item.side_effect = RuntimeError("no DDB in tests")
    table.put_item.side_effect = RuntimeError("no DDB in tests")
    resource = MagicMock()
    resource.Table.return_value = table
    fake_boto3 = MagicMock()
    fake_boto3.client.side_effect = lambda service, **kw: fake_lambda if service == "lambda" else fake_s3
    fake_boto3.resource.return_value = resource
    monkeypatch.setattr(ai_calls, "boto3", fake_boto3)
    prompts = []

    def _call(user_message, *a, **kw):
        prompts.append(user_message)
        return generation_text

    monkeypatch.setattr(ai_calls, "call_anthropic", _call)
    return events, prompts


def test_the_sleep_coach_prompt_carries_pt_never_the_utc_instant(monkeypatch):
    events, prompts = _pipeline_env(monkeypatch, "Sleep held steady this week; keep the wind-down where it is.")
    data = {"date": BRIEF_DATA_DAY, "sleep": {"sleep_start": SLEEP_START_UTC, "sleep_score": 80}}
    out = ai_calls._run_coach_v2_pipeline("sleep_coach", ai_context._build_sleep_data(data), "sleep", data, "")
    assert isinstance(out, str)
    assert "9:45 PM PT" in prompts[0] and "04:45" not in prompts[0]


def test_mutation_control_the_raw_builder_output_carries_the_utc_instant():
    """MUTATION CONTROL: without the boundary (the pre-#4185 input), the same fixture puts
    the bare UTC instant in the prompt payload — the "4:45 AM onset" the integrator read."""
    raw = json.dumps(ai_context._build_sleep_data({"sleep": {"sleep_start": SLEEP_START_UTC}}))
    assert "04:45" in raw and "9:45 PM PT" not in raw


def test_the_weekly_sleep_pack_hands_its_onset_times_over_in_pt(monkeypatch):
    """The weekly expert/integrator path (where "median ~4:45 AM" was written) reads the
    same boundary: its `sleep_onset_times` are PT labels, never UTC instants."""
    from intelligence import ai_expert_analyzer_lambda as az

    whoop = [{"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-09-24", "sleep_start": SLEEP_START_UTC, "sleep_duration_hours": 7.5}]
    monkeypatch.setattr(az, "_query_source", lambda source, s, e: [dict(r) for r in whoop] if source == "whoop" else [])
    pack = az.gather_data_for_expert("sleep")
    assert pack["sleep_onset_times"] == ["Sep 23, 9:45 PM PT"]
    assert "04:45" not in json.dumps(pack)


# ══════════════════════════════════════════════════════════════════════════════
# (c) cited figures vs the served facts — the generation-time gate
# ══════════════════════════════════════════════════════════════════════════════


def test_webb_0925_fails_on_the_gap_and_the_date_but_not_on_the_honest_figures():
    found = ci.served_fact_findings(WEBB_0925, _facts(BRIEF_DATA_DAY, BRIEF_TODAY), today=BRIEF_TODAY)
    metrics = sorted(f["metric"] for f in found)
    assert metrics == ["last_log_date", "log_gap_days"], found
    assert any("claims 6 days without a food log" in f["detail"] for f in found)


def test_webb_with_the_engines_figures_passes():
    honest = (
        "The food log is current through September 24th, and his protein EWMA sits at 154g from 19 logged days. "
        "1 day without a log is the ordinary end-of-day upload lag."
    )
    assert ci.served_fact_findings(honest, _facts(BRIEF_DATA_DAY, BRIEF_TODAY), today=BRIEF_TODAY) == []


def test_eli_0921_protein_fails_against_its_named_14_day_window():
    """At the 09-21 weekly run the rows ran 09-06..09-19 (14 logged days); their mean is
    150.6 g, 95% CI 127.1-174.0 — 106.9 g sits far outside it."""
    facts = _facts("2026-09-19", "2026-09-21")
    found = ci.served_fact_findings(ELI_0921, facts, today="2026-09-21")
    assert [f["metric"] for f in found] == ["protein_g"], found
    assert found[0]["cited"] == 106.9 and found[0]["canonical"] == 150.6
    honest = ELI_0921.replace("106.9", "150.6")
    assert ci.served_fact_findings(honest, facts, today="2026-09-21") == []


def test_a_protein_figure_inside_the_served_ci_passes():
    facts = _facts("2026-09-25", "2026-09-26")  # served avg 153.3 g, CI 136.4-170.3
    assert ci.served_fact_findings(OKAFOR_0925, facts, today="2026-09-26") == []
    assert [f["metric"] for f in ci.served_fact_findings(OKAFOR_0925.replace("154", "106.9"), facts, today="2026-09-26")] == ["protein_g"]


def test_a_single_logged_day_is_not_judged_as_an_average():
    facts = _facts("2026-09-25", "2026-09-26")
    assert ci.served_fact_findings("Yesterday you logged 245 g of protein.", facts, today="2026-09-26") == []


def test_more_logged_days_than_the_record_holds_fails():
    facts = _facts(BRIEF_DATA_DAY, BRIEF_TODAY)
    found = ci.served_fact_findings("That is 24 logged days of protein data.", facts, today=BRIEF_TODAY)
    assert [f["metric"] for f in found] == ["days_logged"]


def test_no_served_record_is_a_skip_never_a_verdict():
    assert ci.served_fact_findings(WEBB_0925, {"nutrition": None, "protein_series": []}) == []
    assert ci.served_fact_findings(WEBB_0925, None) == []


def test_the_webb_draft_is_regenerated_then_held_by_the_quality_gate(monkeypatch):
    """End to end through `_run_coach_v2_pipeline`: the judge PASSES the 09-25 draft (its
    live verdict), the served-fact check fails it, the one corrective regeneration
    repeats the false premise, and ADR-108 holds the section — nothing is published."""
    events, prompts = _pipeline_env(monkeypatch, WEBB_0925, rows=ROWS_0925)
    data = {"date": BRIEF_DATA_DAY, "macrofactor": ROWS_0925[-1]}
    out = ai_calls._run_coach_v2_pipeline("nutrition_coach", ai_context._build_nutrition_data(data), "nutrition", data, "")
    assert isinstance(out, ai_calls.CoachHold), out
    assert "coach-state-updater" not in [fn for fn, _p in events]
    # The generation prompt itself carried the served record the draft contradicts.
    assert '"latest_log_date": "2026-09-24"' in prompts[0] and '"days_logged": 19' in prompts[0]
    # The regeneration was TOLD the served figure.
    assert any("the served record's lag is 1 day(s)" in p for p in prompts[1:])


def test_mutation_control_without_the_served_check_the_webb_draft_publishes(monkeypatch):
    """MUTATION CONTROL: the pre-#4185 gate (the judge's report alone) publishes it."""
    monkeypatch.setattr(ci, "served_fact_gate", lambda report, text, facts: report)
    events, _prompts = _pipeline_env(monkeypatch, WEBB_0925, rows=ROWS_0925)
    data = {"date": BRIEF_DATA_DAY, "macrofactor": ROWS_0925[-1]}
    out = ai_calls._run_coach_v2_pipeline("nutrition_coach", ai_context._build_nutrition_data(data), "nutrition", data, "")
    assert out == WEBB_0925


def test_the_served_findings_reach_eval_retention():
    from ai.quality_gate_contract import report_findings

    report = ci.served_fact_gate({"passed": True}, WEBB_0925, _facts(BRIEF_DATA_DAY, BRIEF_TODAY))
    assert report["passed"] is False
    assert {f["type"] for f in report_findings(report)} == {"served_fact"}


# ══════════════════════════════════════════════════════════════════════════════
# (d) data_through: producer writes → both read sites serve
#
# A plain contract test rather than a `tests/pair_contract_registry.py` entry: enrolling
# a pair there regenerates the committed system model (`model/platform_model.json` +
# docs/DEPENDENCY_GRAPH.md §4b) and ratchets ENROLLED_FLOOR — derived artifacts a lane
# should not carry through the merge train — and the harness's `partition` field models
# USER#…#SOURCE# partitions, which COACH#…/OUTPUT# is not. The shape is the same:
# the REAL producer's captured item is fed to the REAL consumers, and a mutation
# (the key dropped) must change what they serve.
# ══════════════════════════════════════════════════════════════════════════════


def _produced_output_item(monkeypatch, data_through="2026-09-24"):
    written = []
    monkeypatch.setattr(coach_state_updater, "_put_item", lambda item: written.append(item) or True)
    monkeypatch.setattr(coach_state_updater, "_gate_derived_prose", lambda cid, d, text, ex: (ex, []))
    monkeypatch.setattr(coach_state_updater.published_vitals, "stamp_published_vitals", lambda *a, **k: None)
    coach_state_updater._write_output_record(
        "nutrition_coach", "2026-09-25", "daily_brief_nutrition", "Protein is steady.", {"public_summary": None}, data_through=data_through
    )
    assert written, "the OUTPUT# writer refused the write"
    return written[0]


def _served_by_coach_profile(item):
    from boto3.dynamodb.conditions import Key  # noqa: F401 — the reader builds a Key condition
    from web import site_api_coach_profile as prof

    table = MagicMock()
    table.query.return_value = {"Items": [dict(item)]}
    return prof._recent_outputs("nutrition_coach", _g={"table": table})[0]


def _served_by_dashboard(monkeypatch, item):
    from ai import budget_guard
    from web import site_api_lambda as L

    def _query(**kw):
        cond = kw["KeyConditionExpression"].get_expression()
        pk = cond["values"][0].get_expression()["values"][1] if cond.get("operator") == "AND" else cond["values"][1]
        return {"Items": [dict(item)]} if pk == "COACH#nutrition_coach" else {"Items": []}

    table = MagicMock()
    table.query.side_effect = _query
    table.get_item.return_value = {}
    monkeypatch.setattr(L, "table", table)
    monkeypatch.setattr(
        L, "_integrator_digest", lambda: {"analysis": "weekly", "generated_at": "2026-09-21T14:02:56+00:00", "data_through": "2026-09-21"}
    )
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    resp = L.lambda_handler({"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}, None)
    body = json.loads(resp["body"])
    card = next(c for c in body["coaches"] if c["coach_id"] == "nutrition")
    return card, body["weekly_priority"]


def test_data_through_is_written_beside_created_at_and_served_by_both_read_sites(monkeypatch):
    item = _produced_output_item(monkeypatch)
    assert item["data_through"] == "2026-09-24" and item["created_at"]
    served = _served_by_coach_profile(item)
    assert served["data_through"] == item["data_through"] and served["generated_at"] == item["created_at"]
    card, weekly = _served_by_dashboard(monkeypatch, item)
    assert card["analysis_data_through"] == item["data_through"]
    assert weekly["data_through"] == "2026-09-21"


def test_data_through_mutation_a_dropped_key_is_served_as_unknown(monkeypatch):
    """MUTATION: the producer drops the key → both consumers serve null (unknown), never
    a stale or invented day — the consumers really read the field."""
    item = _produced_output_item(monkeypatch)
    item.pop("data_through")
    assert _served_by_coach_profile(item)["data_through"] is None
    card, _weekly = _served_by_dashboard(monkeypatch, item)
    assert card["analysis_data_through"] is None


def test_the_pipeline_sends_data_through_to_the_state_updater(monkeypatch):
    events, _prompts = _pipeline_env(monkeypatch, "Sleep held steady this week.")
    data = {"date": BRIEF_DATA_DAY, "sleep": {"sleep_score": 80}}
    ai_calls._run_coach_v2_pipeline("sleep_coach", ai_context._build_sleep_data(data), "sleep", data, "")
    payloads = [p for fn, p in events if fn == "coach-state-updater"]
    assert payloads and payloads[0]["data_through"] == BRIEF_DATA_DAY


def test_the_state_updater_handler_forwards_data_through(monkeypatch):
    seen = {}
    monkeypatch.setattr(coach_state_updater, "_write_output_record", lambda *a, **k: seen.update(k))
    monkeypatch.setattr(coach_state_updater, "_call_haiku", lambda **k: {})
    for name in (
        "_update_voice_state",
        "_create_thread_records",
        "_update_referenced_threads",
        "_update_relationship_state",
    ):
        monkeypatch.setattr(coach_state_updater, name, lambda *a, **k: None, raising=False)
    try:
        coach_state_updater.lambda_handler(
            {"coach_id": "sleep_coach", "output_text": "x", "generation_date": "2026-09-25", "data_through": "2026-09-24"}, None
        )
    except Exception:  # noqa: BLE001 — later steps may need DDB; the OUTPUT# write is step 1
        pass
    assert seen.get("data_through") == "2026-09-24"


def _weekly_gate(monkeypatch, text, rows, today):
    """`ai_expert_analyzer_lambda._gate_prose` — the weekly experts' and the integrator's
    ONE grounding chokepoint — over a table that serves `rows` for macrofactor."""
    from common import retry_utils
    from intelligence import ai_expert_analyzer_lambda as az

    table = MagicMock()
    table.query.return_value = {"Items": [dict(r) for r in rows]}
    monkeypatch.setattr(az, "table", table)
    monkeypatch.setattr(az, "pacific_today", lambda: today)
    monkeypatch.setattr(ci, "pacific_today", lambda: today)
    monkeypatch.setattr(az, "_load_canonical_facts", dict)
    monkeypatch.setattr(retry_utils, "call_anthropic_raw", lambda req, timeout=None: {"content": [{"type": "text", "text": text}]})
    return az._gate_prose("weekly_priority", text, text, "sk-test", available_logs=frozenset())


def test_the_weekly_integrator_gate_holds_the_106_9_protein_read(monkeypatch):
    """#4185 item 3 was written by the WEEKLY integrator (EXPERT#integrator, 09-21), which
    never passes through `_enforce_quality_gate` — the same check rides its own
    regenerate-or-hold chokepoint. A rewrite that repeats the figure is held ("")."""
    assert _weekly_gate(monkeypatch, ELI_0921, _rows_through("2026-09-19"), "2026-09-21") == ""


def test_mutation_control_the_weekly_gate_without_the_served_check_publishes_it(monkeypatch):
    monkeypatch.setattr(ci, "served_fact_findings", lambda text, facts, today=None: [])
    assert _weekly_gate(monkeypatch, ELI_0921, _rows_through("2026-09-19"), "2026-09-21") == ELI_0921
