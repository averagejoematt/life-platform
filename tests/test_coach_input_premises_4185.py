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
import re
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


# #4343: verbatim sentences from the 2026-09-27 17:00Z brief (EVALRET#coach_brief) that
# the served-fact check held although none of them states his daily intake or its average.
NUTRITION_0927_SERVINGS = (
    "Morning smoothie at 9am delivers 15 g, protein shake at noon adds 30 g, buffalo edamame in the afternoon contributes 11 g."
)
NUTRITION_0927_SHIFT = "One ask this week: redistribute 40g of protein away from dinner into morning and midday."
GLUCOSE_0927_CONDITIONAL = (
    "If protein reaches 190g next week and your fasting glucose still looks elevated, I need you to not read that as non-response."
)
PHYSICAL_0927_AVERAGE = "Protein averaging around 122.7 grams per day through the recent logged period is not sufficient substrate."


def test_a_serving_a_shift_or_a_conditional_target_is_not_an_intake_claim():
    """#4343: the 09-27 holds — per-item amounts, a redistribution and a conditional
    target were each judged against the 21-logged-day average and held their coach."""
    facts = _facts("2026-09-25", "2026-09-26")
    for text in (NUTRITION_0927_SERVINGS, NUTRITION_0927_SHIFT, GLUCOSE_0927_CONDITIONAL):
        assert ci.served_fact_findings(text, facts, today="2026-09-26") == [], text


def test_an_average_framed_figure_is_still_judged():
    """The frame requirement does not loosen the check: the physical coach's 122.7 g
    "averaging … per day" still fails against the served average (cause B of #4343)."""
    facts = _facts("2026-09-25", "2026-09-26")
    found = ci.served_fact_findings(PHYSICAL_0927_AVERAGE, facts, today="2026-09-26")
    assert [(f["metric"], f["cited"]) for f in found] == [("protein_g", 122.7)], found


def test_mutation_control_without_the_intake_frame_the_servings_are_held(monkeypatch):
    """Revert the frame to "every figure is an intake claim" (the pre-#4343 behaviour):
    the three 09-27 fragments fail again, so the test above cannot pass by accident."""
    monkeypatch.setattr(ci, "_INTAKE_FRAME", re.compile(r""))
    facts = _facts("2026-09-25", "2026-09-26")
    for text in (NUTRITION_0927_SERVINGS, NUTRITION_0927_SHIFT, GLUCOSE_0927_CONDITIONAL):
        assert [f["metric"] for f in ci.served_fact_findings(text, facts, today="2026-09-26")], text


# #4343 (09-28 brief, request 15d734b8): the labs coach was held on 190 g — a TARGET and the
# level an escalation moves to, both "per day"-framed, so #4344's intake frame let them through.
LABS_0928_TARGET = (
    "Now, on protein: your intake is averaging 153.5 grams a day over the last 21 logged days, "
    "against a target of 190 grams and a floor of 170 grams."
)
LABS_0928_ESCALATION = "The reset is: kidney function clears on the next panel, then protein escalation to 190 grams per day is authorized."
MIND_0928_TARGET = (
    "Your protein average over the last 21 logged days is 153.5 grams — still well short of the 190-gram target, but genuinely rising."
)


def test_a_target_floor_or_escalation_level_is_not_an_intake_claim():
    facts = _facts("2026-09-25", "2026-09-26")
    for text in (LABS_0928_TARGET, LABS_0928_ESCALATION, MIND_0928_TARGET):
        assert [f["cited"] for f in ci.served_fact_findings(text, facts, today="2026-09-26") if f["metric"] == "protein_g"] == [], text
    # the same figure stated as what he ATE is still judged
    ate = "You averaged 190 g of protein a day, above the 170 g floor."
    assert [f["cited"] for f in ci.served_fact_findings(ate, facts, today="2026-09-26")] == [190.0]


def test_mutation_control_without_the_target_frame_the_labs_coach_is_held(monkeypatch):
    monkeypatch.setattr(ci, "_target_framed", lambda _s, _v: False)
    facts = _facts("2026-09-25", "2026-09-26")
    for text in (LABS_0928_ESCALATION,):
        assert 190.0 in [f["cited"] for f in ci.served_fact_findings(text, facts, today="2026-09-26")], text


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
    """MUTATION CONTROL: the pre-#4185 gate (the judge's report alone) publishes it.

    #4214's reader checks (`coach.reader_checks.merge_into_report`, a sibling #4185 gate
    that landed on main in parallel) also hold this draft here — on the allow-list class,
    because this hermetic env serves no canonical facts. They are switched off too so the
    control isolates THIS PR's served-fact check; with both live the draft is held twice over."""
    from coach import reader_checks

    monkeypatch.setattr(ci, "served_fact_gate", lambda report, text, facts: report)
    monkeypatch.setattr(reader_checks, "merge_into_report", lambda payload, text, brief, cycle_boundary=None: [])
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


# ══════════════════════════════════════════════════════════════════════════════
# #4189 — the morning note reaches every coach's input as a served fact
# ══════════════════════════════════════════════════════════════════════════════

NOTE_ROW = {
    "pk": "USER#matthew#SOURCE#morning_note",
    "sk": "MORNING_NOTE#2026-09-26",
    "date": "2026-09-26",
    "sleep_word": "heavy",
    "body_word": "stiff",
    "mood_word": "steady",
    "felt_recovered": False,
    "written_at": "2026-09-26T12:12:00+00:00",
    "tier": 1,
    "source": "site_api_morning_note",
}


class _NoteTable:
    """Answers the note window query with the rows given; records the key condition."""

    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def query(self, **kw):
        self.calls.append(kw)
        return {"Items": [dict(r) for r in self.rows]}


def _fresh_note_run():
    ci._run.clear()


def test_every_coach_input_carries_the_morning_note_as_a_served_fact():
    """The sleep and mind coaches asked for the four words by name; every coach reads the
    same fact so no two narrate a morning he described differently. Mutation control: hand
    the raw row (or the raw UTC instant) through instead of coach_fact — the checks below fail."""
    _fresh_note_run()
    table = _NoteTable([NOTE_ROW])
    for coach in ("sleep_coach", "mind_coach", "nutrition_coach", "training_coach"):
        _fresh_note_run()
        out = ci.coach_inputs(coach, {"hrv": 50}, {"date": "2026-09-25"}, table=table)
        fact = out["morning_note"]
        assert fact["state"] == "measured"
        assert (fact["sleep_word"], fact["body_word"], fact["mood_word"], fact["felt_recovered"]) == ("heavy", "stiff", "steady", False)
        assert fact["date"] == fact["data_through"] == "2026-09-26" and fact["day"].startswith("Saturday, September 26")
        assert fact["written_at_pt"].endswith("PT") and "written_at" not in fact, "the UTC instant never reaches a coach"
        assert "verbatim" in fact["note"]
    assert out["hrv"] == 50, "the domain data is carried, not replaced"


def test_the_note_is_read_for_today_not_for_the_previous_data_day():
    """The brief runs after the morning it was written: the window ends on Pacific TODAY, and
    reaches back exactly COACH_LOOKBACK_DAYS — not to `data_through`'s day, not 14 days."""
    from boto3.dynamodb.conditions import ConditionExpressionBuilder
    from coach import morning_note as mn

    _fresh_note_run()
    table = _NoteTable([])
    ci.served_run_facts({"date": "2026-09-25"}, table=table, today="2026-09-26")
    rendered = [(ConditionExpressionBuilder().build_expression(c["KeyConditionExpression"], is_key_condition=True), c) for c in table.calls]
    note_calls = [(b, c) for b, c in rendered if mn.MORNING_NOTE_PK in b.attribute_value_placeholders.values()]
    assert len(note_calls) == 1, "exactly one note window read per run (the macrofactor window is the other query)"
    built, call = note_calls[0]
    bounds = set(built.attribute_value_placeholders.values()) - {mn.MORNING_NOTE_PK}
    assert bounds == {mn.sk_for("2026-09-25"), mn.sk_for("2026-09-26") + "~"}, bounds
    assert call["Limit"] == mn.COACH_LOOKBACK_DAYS == 2


def test_no_note_is_absent_and_no_table_is_read_failed_never_an_empty_morning():
    """ADR-104 at birth: `[]` is "no note" (stated); an unreadable partition is unknown.
    Mutation control: collapse None into `absent` — the second assertion fails."""
    _fresh_note_run()
    fact = ci.coach_inputs("sleep_coach", {}, {"date": "2026-09-25"}, table=_NoteTable([]))["morning_note"]
    assert fact["state"] == "absent" and "never infer" in fact["note"] and "sleep_word" not in fact
    _fresh_note_run()
    fact = ci.coach_inputs("sleep_coach", {}, {"date": "2026-09-25"}, table=None)["morning_note"]
    assert fact["state"] == "read_failed" and "sleep_word" not in fact


def test_the_quality_gate_sees_the_same_note_the_coach_was_given():
    """`served_run_facts()` with no data returns THIS run's facts — the gate reads the note
    the coach read, not a fresh query that might have moved."""
    _fresh_note_run()
    ci.coach_inputs("mind_coach", {}, {"date": "2026-09-25"}, table=_NoteTable([NOTE_ROW]))
    assert ci.served_run_facts()["morning_note"]["mood_word"] == "steady"


def test_a_presence_only_tier_withholds_the_words_from_the_coach_too():
    """The stored tier is honoured on EVERY read path, not only the public one."""
    _fresh_note_run()
    row = {**NOTE_ROW, "tier": 2}
    fact = ci.coach_inputs("sleep_coach", {}, {"date": "2026-09-25"}, table=_NoteTable([row]))["morning_note"]
    assert fact["state"] == "measured" and "sleep_word" not in fact and fact["words"].startswith("withheld")


def test_the_reader_checks_do_not_misfire_on_a_coach_quoting_the_note():
    """#4214's deterministic checks over the sentence a coach would write from the fact: the
    words are not numbers, the day is in words, the instant is a PT clock label — no finding.
    Mutation control: quote the ISO `date` or the UTC `written_at` — raw_instant fires."""
    from coach import morning_note as mn, reader_checks as rc

    fact = mn.coach_fact(NOTE_ROW)
    sentence = (
        f"Before he opened the app on {fact['day']}, his four words were {fact['sleep_word']}, {fact['body_word']}, "
        f"{fact['mood_word']} — and he did not feel recovered ({fact['written_at_pt']})."
    )
    assert rc.raw_instant(sentence, facts={}) == []
    assert rc.unit_number_not_served(sentence) == []
    assert rc.unlabeled_window_figure(sentence) == []
    assert rc.raw_instant(f"His note on {fact['date']}: heavy.", facts={}), "control: the ISO date IS a finding"
    assert rc.raw_instant(f"Written at {NOTE_ROW['written_at']}.", facts={}), "control: the UTC instant IS a finding"


# ══════════════════════════════════════════════════════════════════════════════
# #4185 item 4 — weight / loss-rate figures vs the served trajectory; and the
# #4343 grounding misfire on an age-decade idiom
# ══════════════════════════════════════════════════════════════════════════════

# The served trajectory beside Eli's read (/api/journey, fetched 2026-09-26 19:32Z — the
# reader_checks corpus specimen `2026-09-21-eli-weekly-106.9g-316.9lb.json`).
JOURNEY_0926 = {"latest_weight": 313.8, "weekly_rate_lbs": -4.36, "weekly_rate_ci_low": -4.74, "weekly_rate_ci_high": -2.75}
# Verbatim from the same served text (weekly_priority, 09-21, the door's top read on 09-26).
ELI_0921_WEIGHT = (
    "At 316.9 pounds after 16 experiment days, he's losing 3.7 pounds per week, which is aggressive and on-target "
    "for the Foundation phase."
)
# The physical coach's retained FINAL from the 2026-09-27 17:00Z brief (EVALRET#coach_brief,
# read-only query): it was held on `fabricated_number 40` ("after your mid-40s") among others.
with open(os.path.join(os.path.dirname(_FIXTURE), "evalret_coach_brief_physical_2026-09-27.json"), encoding="utf-8") as _fh:
    PHYSICAL_0927 = json.load(_fh)


def _weight_facts(traj=JOURNEY_0926):
    return {"weight": ci.weight_fact(traj)}


def test_eli_0921_weight_fails_against_the_served_weigh_in_and_passes_with_it():
    """316.9 lb beside a served 313.8 lb is 3.1 lb off (tolerance: the nightly QA's 1.5 lb).
    The 3.7 lb/week sits INSIDE the served 80% CI (2.75-4.74 lb/week), so the rate is not
    a contradiction by the engine's own interval — only the weight fails."""
    found = ci.served_fact_findings(ELI_0921_WEIGHT, _weight_facts(), today="2026-09-26")
    assert [(f["metric"], f["cited"], f["canonical"]) for f in found] == [("weight_lb", 316.9, 313.8)], found
    assert "the latest served weigh-in is 313.8 lb" in found[0]["detail"]
    assert ci.served_fact_findings(ELI_0921_WEIGHT.replace("316.9", "313.8"), _weight_facts(), today="2026-09-26") == []


def test_a_rate_outside_the_served_ci_fails_and_one_inside_passes():
    facts = _weight_facts()
    found = ci.served_fact_findings("He is losing 7.3 lb/week right now.", facts)
    assert [(f["metric"], f["cited"]) for f in found] == [("weekly_rate_lb", 7.3)], found
    assert "80% CI -4.74 to -2.75" in found[0]["detail"]
    assert ci.served_fact_findings("He is losing 1.9 pounds per week.", facts)  # below the band
    for honest in ("He is losing 4.4 pounds per week.", "That is 2.8 lb/week.", "A rate of −4.7 lb/week."):
        assert ci.served_fact_findings(honest, facts) == [], honest


def test_no_ci_served_falls_back_to_the_nightly_qa_tolerance():
    facts = _weight_facts({"weekly_rate_lbs": -4.36})
    assert ci.served_fact_findings("He is losing 5.2 lb/week.", facts) == []  # within 1.0
    assert [f["metric"] for f in ci.served_fact_findings("He is losing 5.5 lb/week.", facts)] == ["weekly_rate_lb"]


def test_a_goal_an_origin_a_forecast_or_a_dated_weigh_in_is_not_a_claim_about_today():
    """Here a misfire HOLDS a coach (#4343), so the figures a coach states correctly but
    not as today's weight are each left alone — and an undated present weight still fails."""
    facts = _weight_facts()
    for text in (
        "Down 13.5 lbs from 327.3 lbs; the goal is 185 lbs.",
        "He started at 327 pounds.",
        "The goal of 185 lbs is a long way off.",
        "On the way to 300 pounds, the first milestone matters.",
        "Your weight on September 26 is 313.8 lbs, down 13.5 lbs.",
        "321.1 lbs at Day 1 is the anchor.",
        "Add 10 lbs to the bar.",
    ):
        assert ci.served_fact_findings(text, facts, today="2026-09-27") == [], text
    assert [f["cited"] for f in ci.served_fact_findings("You weigh 316 lbs and the goal is 185 lbs.", facts)] == [316.0]


def test_the_physical_0927_final_raises_no_weight_or_rate_finding():
    """The live 09-27 physical final cites the weigh-in (dated), the rate (4.4, inside the
    CI) and the #541 forecast interval (314.5, 310.8-318.1) — all honest. Only its
    protein figure — cause B of #4343, fixed upstream by #4345 — remains a served-fact finding."""
    facts = {**_facts("2026-09-25", "2026-09-26"), **_weight_facts(PHYSICAL_0927["facts"])}
    found = ci.served_fact_findings(PHYSICAL_0927["final"], facts, today="2026-09-27")
    assert [(f["metric"], f["cited"]) for f in found] == [("protein_g", 122.7)], found


# The live forecast sentence writes units only on the point ("314.5 lbs", 0.7 lb off); the
# same sentence with a unit on each bound is what the forecast frame exists for.
FORECAST_0927_UNITS = "The model expects weight of 314.5 lbs tomorrow morning, with the interval running from 310.8 lbs to 318.1 lbs."


def test_a_forecast_interval_with_units_is_not_a_claim_about_today():
    assert ci.served_fact_findings(FORECAST_0927_UNITS, _weight_facts(PHYSICAL_0927["facts"]), today="2026-09-27") == []


def test_mutation_control_without_the_forecast_frame_the_interval_misfires(monkeypatch):
    monkeypatch.setattr(ci, "_WEIGHT_FORECAST_SENTENCE", re.compile(r"(?!)"))
    found = ci.served_fact_findings(FORECAST_0927_UNITS, _weight_facts(PHYSICAL_0927["facts"]), today="2026-09-27")
    assert [f["cited"] for f in found] == [318.1], found


def test_mutation_control_without_the_weight_check_eli_publishes(monkeypatch):
    monkeypatch.setattr(ci, "weight_findings", lambda sentence, weight: [])
    assert ci.served_fact_findings(ELI_0921_WEIGHT, _weight_facts(), today="2026-09-26") == []


def test_the_daily_run_facts_carry_the_trajectory_the_brief_gathered():
    """The daily brief's `data` carries computed_metrics' trajectory under the canonical
    names; the run facts the quality gate reads (`served_run_facts()`) carry it too, and a
    later caller without it (the weekly nutrition pack's `{"date": …}`) never erases it."""
    data = {"date": "2026-09-25", "macrofactor_window": _rows_through("2026-09-25"), **JOURNEY_0926}
    ci.served_run_facts(data, today="2026-09-26")
    assert ci.served_run_facts()["weight"] == JOURNEY_0926
    ci._run.pop("at")  # force a re-derive keyed the same
    ci._run["at"] = __import__("time").monotonic()
    ci.served_run_facts({"date": "2026-09-25"}, today="2026-09-26")
    assert ci.served_run_facts()["weight"] == JOURNEY_0926
    assert ci.weight_fact({"latest_weight": None, "weekly_rate_lbs": None}) is None  # pre-genesis: withheld


def test_the_gate_holds_a_daily_draft_on_the_served_weight(monkeypatch):
    """`served_fact_gate` folds the weight finding into the report ADR-108 regenerates or
    holds on, with the figure logged and the correction naming the served weigh-in."""
    ci.served_run_facts({"date": "2026-09-25", "macrofactor_window": _rows_through("2026-09-25"), **JOURNEY_0926}, today="2026-09-26")
    report = ci.gated(lambda *_a: {"passed": True, "suggestions": []}, None, "physical_coach", ELI_0921_WEIGHT, {})
    assert report["passed"] is False
    assert [f["metric"] for f in report[ci.SERVED_FACT_REPORT_KEY]] == ["weight_lb"]
    assert any("313.8 lb" in s for s in report["suggestions"])


def test_the_weekly_gate_holds_the_316_9_weight_read(monkeypatch):
    """The weekly integrator (09-21) never reaches `_enforce_quality_gate`; its chokepoint
    `_gate_prose` now hands the canonical trajectory to the same check. A rewrite that
    repeats 316.9 is held (""); the engine's weight publishes."""
    from intelligence import ai_expert_analyzer_lambda as az

    rows = _rows_through("2026-09-19")
    monkeypatch.setattr(az, "_load_canonical_facts", lambda: dict(JOURNEY_0926))
    monkeypatch.setattr(az._gg, "grounding_findings", lambda *_a, **_k: [])  # isolate the served-fact half
    assert _weekly_gate_with(monkeypatch, az, ELI_0921_WEIGHT, rows, "2026-09-21") == ""
    ci._run.clear()
    honest = ELI_0921_WEIGHT.replace("316.9", "313.8")
    assert _weekly_gate_with(monkeypatch, az, honest, rows, "2026-09-21") == honest


def _weekly_gate_with(monkeypatch, az, text, rows, today):
    from common import retry_utils

    table = MagicMock()
    table.query.return_value = {"Items": [dict(r) for r in rows]}
    monkeypatch.setattr(az, "table", table)
    monkeypatch.setattr(az, "pacific_today", lambda: today)
    monkeypatch.setattr(ci, "pacific_today", lambda: today)
    monkeypatch.setattr(retry_utils, "call_anthropic_raw", lambda req, timeout=None: {"content": [{"type": "text", "text": text}]})
    return az._gate_prose("weekly_priority", text, text, "sk-test", available_logs=frozenset())


def test_an_age_decade_idiom_is_not_a_figure_to_ground():
    """#4343 (physical, 09-27): "…degrades roughly 1% per year after your mid-40s" was held
    as `fabricated_number 40`. Against the retained allow-list the final now grounds clean;
    a decade that is NOT a person's age — a measurement band or a rest interval — still
    must be earned."""
    from ai import grounded_generation as gg

    allowed = set(PHYSICAL_0927["allowed"])
    assert any(f["detail"].startswith("the number 40 ") for f in PHYSICAL_0927["retained_findings"])  # the live hold
    assert gg.fabricated_numbers(PHYSICAL_0927["final"], allowed) == []
    for idiom in ("after your mid-40s", "a man in his 40s", "in their late-50s", "your early 30s", "your 40’s"):
        assert gg.fabricated_numbers(idiom, set()) == [], idiom
    for measure in ("HRV has sat in the mid-40s", "rest 40s between sets", "40 g of protein"):
        assert gg.fabricated_numbers(measure, set()) == [40.0], measure
    # The idiom does not launder the same number written as a measurement elsewhere.
    assert gg.fabricated_numbers("After your mid-40s, eat 40 g at breakfast.", set()) == [40.0]


def test_mutation_control_without_the_idiom_rule_the_physical_final_is_held_on_40(monkeypatch):
    from ai import grounded_generation as gg

    monkeypatch.setattr(gg, "_AGE_DECADE_RE", re.compile(r"(?!)"))
    assert gg.fabricated_numbers(PHYSICAL_0927["final"], set(PHYSICAL_0927["allowed"])) == [40.0]


# ── #4343 / #4185 box 4: the SERVED corpus against the served facts (scripts/check_served_coach_facts.py) ──
# The generation-time gate sees drafts only; this probe re-reads what is already served. The
# fixture text is the live /api/coaching-dashboard lead read of 2026-09-29 (4.4 lb/week beside
# a served rate of -3.8, 80% CI -4.32..-2.12).
_SERVED_LEAD_4343 = (
    "Matthew has dropped 13.5 pounds in three weeks, running at a provisional early pace of 4.4 pounds per "
    "week—the kind of momentum that suggests his daily choices are clicking into place."
)


def _probe():
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
    import check_served_coach_facts as probe

    return probe


def _served_4343(rate, lo, hi):
    trend = [{"date": f"2026-09-{d:02d}", "protein_g": 150.0 + (d % 5) * 4} for d in range(6, 27)]
    return {"nutrition_trend": trend}, {
        "journey": {"current_weight_lbs": 312.3, "weekly_rate_lbs": rate, "weekly_rate_ci_low": lo, "weekly_rate_ci_high": hi}
    }


def _payloads_4343():
    return {
        "/api/coaches": {"coaches": [{"persona_id": "eli_marsh", "headline_stat": "no checked call yet"}]},
        "/api/coaching-dashboard": {"lead_daily": {"text": _SERVED_LEAD_4343}},
        "/api/coach_team": {},
        "/api/coach/eli_marsh": {"daily": _SERVED_LEAD_4343},
    }


def test_4343_served_probe_names_the_path_figure_and_served_value():
    probe = _probe()
    facts = probe.facts_from_served(*_served_4343(-3.8, -4.32, -2.12), today="2026-09-29")
    hits = probe.findings(probe.served_texts(_payloads_4343()), facts, today="2026-09-29")
    paths = sorted(p for p, _f in hits)
    assert paths == ["/api/coach/eli_marsh $.daily", "/api/coaching-dashboard $.lead_daily.text"], paths
    assert all(f["cited"] == 4.4 for _p, f in hits), hits


def test_4343_mutation_control_facts_from_the_texts_own_figures_go_green():
    """The control: serve the rate the text cites and the same corpus is clean — the probe
    reds on the DISAGREEMENT, not on the presence of a figure."""
    probe = _probe()
    facts = probe.facts_from_served(*_served_4343(-4.4, -4.9, -3.9), today="2026-09-29")
    assert probe.findings(probe.served_texts(_payloads_4343()), facts, today="2026-09-29") == []


def test_4343_served_probe_exit_codes(monkeypatch, capsys):
    probe = _probe()
    nut, jr = _served_4343(-3.8, -4.32, -2.12)
    routes = {**_payloads_4343(), "/api/nutrition_overview": nut, "/api/journey": jr}
    monkeypatch.setattr(probe, "_fetch", lambda base, path: routes[path])
    assert probe.main([]) == 1
    out = capsys.readouterr().out
    assert "/api/coaching-dashboard $.lead_daily.text" in out and "cites 4.4" in out and "findings=2" in out

    def _down(base, path):
        raise OSError("connection refused")

    monkeypatch.setattr(probe, "_fetch", _down)
    assert probe.main([]) == 2, "a probe that could not look is UNEVALUABLE, never a clean corpus"
    monkeypatch.setattr(probe, "_fetch", lambda base, path: {"coaches": []} if path == "/api/coaches" else {})
    assert probe.main([]) == 2


def test_4343_served_probe_workflow_step_keeps_the_scripts_exit_code(tmp_path):
    """The nightly step is the REAL `run:` text from served-coach-facts.yml, executed as GitHub
    runs it (`bash -eo pipefail`) with the script swapped for a stand-in: findings (1) and
    UNEVALUABLE (2) are reds, a clean corpus (0) is green."""
    import subprocess

    import yaml

    wf = os.path.join(os.path.dirname(__file__), "..", ".github", "workflows", "served-coach-facts.yml")
    with open(wf, encoding="utf-8") as fh:
        steps = yaml.safe_load(fh)["jobs"]["probe"]["steps"]
    run = next(s["run"] for s in steps if "check_served_coach_facts.py" in (s.get("run") or ""))
    (tmp_path / "scripts").mkdir()
    for code in (0, 1, 2):
        (tmp_path / "scripts" / "check_served_coach_facts.py").write_text(f"raise SystemExit({code})\n", encoding="utf-8")
        env = {**os.environ, "GITHUB_STEP_SUMMARY": str(tmp_path / "summary.md")}
        got = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", "-c", run], cwd=tmp_path, env=env, capture_output=True)
        assert got.returncode == code, f"script exit {code} -> step exit {got.returncode}"
