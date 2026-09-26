"""tests/test_lead_daily_read_4188.py — #4188: the head coach's DAILY grounded lead read.

The coaching door opened on the integrator's WEEKLY call (a Monday read served on a
Friday, two figures stale) because no daily lead read existed: `/api/coach/eli_marsh.daily`
was null and `stance.headline_read` was "". `coach.lead_daily_read` writes one per daily
brief. This file pins, offline (no AWS, Bedrock mocked):

  1. prompt assembly — from a FIXED fact set, the model is shown exactly the cited block
     and nothing else numeric; a grounded draft is written with that block attached;
  2. the hard post-check — a draft with an uncited number (an invented weight, a figure
     the model computed) is refused, regenerated once, then HELD with nothing written;
     the mutation control flips one digit of a passing draft and watches it fail;
  3. budget first — a paused `coach_narrative` feature means no vitals read, no model
     call, no write; and the budget check is the first thing that runs;
  4. the quality gate — a gate hold writes nothing, and the gate is handed the cited
     numbers as its allow-list;
  5. the serializer pair — the producer's row, read back by /api/coaching-dashboard
     (`lead_daily`) and /api/coach/eli_marsh (`daily` + `lead_daily`).
"""

import json
import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from ai import budget_guard  # noqa: E402
from ai.grounded_generation import numbers_in_text  # noqa: E402
from coach import (
    lead_daily_read as LDR,  # noqa: E402
    persona_registry,  # noqa: E402
)
from fakes import FakeDdbTable  # noqa: E402

# Injected into every call as `today=` (the dependency-injection pattern): no code path under
# test derives this day from the wall clock, so no fixture here can rot at a midnight (#2376).
GENERATION_DAY = "2026-09-26"
DATA = {
    "date": "2026-09-25",
    "weight_recency": {"current_weight_lb": 313.1, "current_weight_as_of": "2026-09-25"},
    "latest_weight": 313.1,
    "weekly_rate_lbs": -4.58,
    "weekly_rate_ci_low": -4.9,
    "weekly_rate_ci_high": -2.7,
    "rate_provisional": True,
    "macrofactor": {"total_protein_g": 182.4},
}
PROFILE = {"journey_start_date": "2026-09-06", "journey_start_weight_lbs": 327.3, "protein_floor_g": 170}
VITALS = {
    "recovery_pct": 99.0,
    "hrv_ms": 56.8,
    "rhr_bpm": 52.0,
    "recovery_as_of": "2026-09-26",
    "sleep_hours": 9.9,
    "sleep_as_of": "2026-09-26",
}
GROUNDED = (
    "He is losing fast and eating to plan: 313.1 lb at the Friday, September 25 weigh-in, 14.2 lb down since "
    "September 6. The weekly loss rate is 4.6 lb, an early, provisional estimate. He ate 182 grams of protein, "
    "above his 170-gram floor, and slept 9.9 hours with a recovery score of 99."
)


def _resp(text):
    return {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": 700, "output_tokens": 90}}


class _Harness:
    """Records every seam `run` touches, in order."""

    def __init__(self, drafts, *, allowed=True, gate=None):
        self.calls = []
        self.bodies = []
        self.drafts = list(drafts)
        self.allowed = allowed
        self.gate = gate
        self.gate_briefs = []
        self.table = FakeDdbTable()

    def allow(self, feature):
        self.calls.append(("allow", feature))
        return self.allowed

    def vitals(self, table, prefix):
        self.calls.append(("vitals", prefix))
        return dict(VITALS)

    def invoke(self, body, model_name=None):
        self.calls.append(("invoke", model_name))
        self.bodies.append(body)
        return _resp(self.drafts.pop(0) if len(self.drafts) > 1 else self.drafts[0])

    def enforce(self, lambda_client, coach_id, text, brief, regen):
        self.calls.append(("gate", coach_id))
        self.gate_briefs.append(brief)
        if self.gate:
            return self.gate(text, regen)
        return text, {"passed": True, "score": 8.5}

    def run(self, persist=True):
        return LDR.run(
            DATA,
            PROFILE,
            table=self.table,
            lambda_client=object(),
            today=GENERATION_DAY,
            persist=persist,
            invoke=self.invoke,
            resolve_vitals=self.vitals,
            enforce_gate=self.enforce,
            allow=self.allow,
        )


def _cited():
    return LDR.build_cited(DATA, PROFILE, VITALS, GENERATION_DAY)


# ── 1. the facts and the prompt ─────────────────────────────────────────────


def test_the_lead_id_is_the_registry_lead():
    assert LDR.LEAD_ID == persona_registry.LEAD_PERSONA_ID
    assert LDR.BUDGET_FEATURE in budget_guard._FEATURE_CUTOFF  # a registered band, not the hard-stop default


def test_cited_block_is_computed_from_the_brief_facts_with_dates_in_words():
    by_metric = {c["metric"]: c for c in _cited()}
    assert by_metric["day of the experiment"]["value"] == "21"
    assert by_metric["experiment start date"]["value"] == "Sunday, September 6"
    assert by_metric["latest weigh-in (lb)"] == {
        "metric": "latest weigh-in (lb)",
        "value": "313.1",
        "as_of": "2026-09-25",
        "source_field": "withings.weight_lbs",
    }
    assert by_metric["latest weigh-in date"]["value"] == "Friday, September 25"
    assert by_metric["lost since the start (lb)"]["value"] == "14.2"  # computed HERE, not by the model
    assert by_metric["weekly loss rate (lb per week)"]["value"] == "4.6"
    assert by_metric["weekly loss rate, likely range (lb per week)"]["value"] == "2.7 to 4.9"
    assert by_metric["rate status"]["value"] == "provisional"
    assert by_metric["morning recovery score (0-100, Whoop)"]["value"] == "99"
    assert by_metric["heart-rate variability (ms)"]["value"] == "57"
    assert by_metric["protein eaten (grams)"]["value"] == "182"
    assert by_metric["protein floor met"]["value"] == "yes"
    for c in _cited():
        assert set(c) == {"metric", "value", "as_of", "source_field"}


def test_absent_metrics_are_left_out_never_zeroed():
    cited = LDR.build_cited({"date": "2026-09-25"}, {"journey_start_date": "2026-09-06"}, {}, GENERATION_DAY)
    metrics = {c["metric"] for c in cited}
    assert metrics == {"day of the experiment", "experiment start date"}
    h = _Harness([GROUNDED])
    h_data = {"date": "2026-09-25"}
    out = LDR.run(
        h_data,
        {},
        table=h.table,
        today=GENERATION_DAY,
        invoke=h.invoke,
        resolve_vitals=lambda t, p: {},
        enforce_gate=h.enforce,
        allow=h.allow,
    )
    assert out["status"] == "insufficient_facts"
    assert not [c for c in h.calls if c[0] == "invoke"]  # too few facts -> no model call at all


def test_prompt_is_assembled_only_from_the_cited_block_and_a_grounded_draft_is_written():
    h = _Harness([GROUNDED])
    out = h.run()
    assert out["status"] == "written", out
    body = h.bodies[0]
    assert body["system"] == LDR.LEAD_PROMPT
    user = body["messages"][0]["content"]
    assert user == LDR.facts_text(_cited(), DATA["date"]) + "\n\nWrite the lead read."
    # every number the model is shown lives in the cited block (a metric's own scale, its
    # value, or its as-of date in words) or in the data-through date — nothing else
    cited_nums = numbers_in_text(json.dumps([[c["metric"], c["value"], LDR.date_in_words(c["as_of"])] for c in _cited()]))
    assert numbers_in_text(user) <= cited_nums | numbers_in_text(LDR.date_in_words(DATA["date"]))
    assert {313.1, 14.2, 4.6, 99.0, 182.0, 170.0} <= numbers_in_text(user)
    # the prompt forbids the model's arithmetic and names the reader rules
    for rule in ("Do no arithmetic", "third person", "90 words", "No medical advice", "dates in words"):
        assert rule.lower() in LDR.LEAD_PROMPT.lower(), rule

    (row,) = h.table.puts
    assert row["pk"] == "COACH#eli_marsh" and row["sk"] == f"LEAD_DAILY#{GENERATION_DAY}"
    assert row["text"] == GROUNDED
    assert row["data_through"] == DATA["date"]
    assert row["cited"] == _cited()
    assert LDR.uncited_numbers(row["text"], row["cited"], row["data_through"]) == []
    assert row["calls"] == 1 and row["input_tokens"] == 700 and row["output_tokens"] == 90
    assert float(row["cost_usd"]) > 0  # measured from the call's own usage, not asserted
    assert row.get("phase")  # EXPERIMENT_SCOPED: stamped at write time


# ── 2. the hard post-check ──────────────────────────────────────────────────


def test_a_draft_with_an_uncited_number_is_refused_regenerated_once_then_held():
    invented = GROUNDED.replace("313.1 lb", "315.0 lb")
    h = _Harness([invented, invented])
    out = h.run()
    assert out["status"] == "held"
    assert any(r.startswith("uncited_number:315") for r in out["reasons"]), out
    assert [c[0] for c in h.calls].count("invoke") == 2  # the draft + ONE regeneration
    assert "refused" in h.bodies[1]["messages"][0]["content"]
    assert h.table.puts == []  # a held read writes nothing
    assert not [c for c in h.calls if c[0] == "gate"]  # never reaches the gate


def test_a_refused_draft_that_regenerates_clean_is_written():
    h = _Harness(["He weighs 315.0 lb.", GROUNDED])
    assert h.run()["status"] == "written"
    assert h.table.puts[0]["text"] == GROUNDED
    assert h.table.puts[0]["calls"] == 2


def test_post_check_mutation_control():
    cited = _cited()
    assert LDR.check(GROUNDED, cited, DATA["date"], GENERATION_DAY) == []
    mutated = GROUNDED.replace("14.2 lb", "14.3 lb")
    assert "uncited_number:14.3" in LDR.check(mutated, cited, DATA["date"], GENERATION_DAY)  # (the #2573 number class also fires)
    assert LDR.uncited_numbers(mutated, cited, DATA["date"]) == [14.3]
    # a figure the MODEL computed (182 - 170 = 12) is uncited by construction
    assert "uncited_number:12" in LDR.check(GROUNDED + " That is 12 grams over.", cited, DATA["date"], GENERATION_DAY)
    # a re-rounding is uncited too (the exact rule: 313.1 shown, 313 written)
    assert "uncited_number:313" in LDR.check(GROUNDED.replace("313.1", "313"), cited, DATA["date"], GENERATION_DAY)
    assert LDR.check("", cited, DATA["date"], GENERATION_DAY) == ["empty"]
    assert any(r.startswith("over_") for r in LDR.check(" ".join(["word"] * 91), cited, DATA["date"], GENERATION_DAY))


# ── 3. budget first ─────────────────────────────────────────────────────────


def test_budget_is_checked_first_and_a_pause_spends_nothing():
    h = _Harness([GROUNDED], allowed=False)
    assert h.run()["status"] == "paused"
    assert h.calls == [("allow", "coach_narrative")]
    assert h.table.puts == []

    h2 = _Harness([GROUNDED])
    h2.run()
    assert h2.calls[0] == ("allow", "coach_narrative")
    order = [c[0] for c in h2.calls]
    assert order.index("allow") < order.index("vitals") < order.index("invoke") < order.index("gate")


# ── 4. the quality gate ─────────────────────────────────────────────────────


def test_a_quality_gate_hold_writes_nothing_and_the_gate_gets_the_cited_allowlist():
    h = _Harness([GROUNDED], gate=lambda text, regen: (None, {"passed": False, "score": 3}))
    out = h.run()
    assert out["status"] == "held" and out["reasons"] == ["quality_gate"]
    assert h.table.puts == []
    brief = h.gate_briefs[0]
    assert brief["surface"] == "lead_daily"
    assert set(brief["grounding_allowlist"]) >= {313.1, 14.2, 4.6, 182.0, 170.0}


def test_a_gate_regeneration_must_repass_the_cited_check():
    seen = {}

    def gate(text, regen):
        seen["regen"] = regen("be warmer")  # the regenerated draft carries an invented number
        return (seen["regen"] or text), {"passed": True, "score": 7}

    h = _Harness([GROUNDED, "He weighs 300.0 lb now."], gate=gate)
    out = h.run()
    assert seen["regen"] == ""  # refused inside the regen fn -> the gate keeps the prior draft
    assert out["status"] == "written"
    assert h.table.puts[0]["text"] == GROUNDED


def test_the_run_never_raises():
    def boom(*a, **k):
        raise RuntimeError("bedrock down")

    h = _Harness([GROUNDED])
    out = LDR.run(
        DATA, PROFILE, table=h.table, today=GENERATION_DAY, invoke=boom, resolve_vitals=h.vitals, enforce_gate=h.enforce, allow=h.allow
    )
    assert out["status"] == "error"
    assert h.table.puts == []


# ── 5. the serializer pair ──────────────────────────────────────────────────


def _written_row():
    h = _Harness([GROUNDED])
    h.run()
    return h.table.puts[0]


def _lead_query_hook(row):
    def hook(table, **kw):
        expr = kw["KeyConditionExpression"].get_expression()
        if expr.get("operator") == "AND":
            pk = expr["values"][0].get_expression()["values"][1]
            sk = expr["values"][1].get_expression()["values"][1]
            if pk == "COACH#eli_marsh" and sk == "LEAD_DAILY#":
                return {"Items": [dict(row)]}
        return {"Items": []}

    return hook


def test_served_shape_round_trips_the_row():
    row = _written_row()
    got = LDR.latest_served(FakeDdbTable(query_hook=_lead_query_hook(row)))
    assert got == {
        "text": GROUNDED,
        "generated_at": row["generated_at"],
        "data_through": DATA["date"],
        "cited": _cited(),
        "coach_id": "eli_marsh",
    }
    assert LDR.latest_served(FakeDdbTable()) is None  # absence is None, never a placeholder
    assert LDR.served({"text": "", "generated_at": "x"}) is None


def test_coaching_dashboard_serves_lead_daily_from_the_producer_row(monkeypatch):
    from web import site_api_coach as coach_api, site_api_lambda as L

    row = _written_row()
    monkeypatch.setattr(coach_api, "table", FakeDdbTable())
    monkeypatch.setattr(L, "table", FakeDdbTable(query_hook=_lead_query_hook(row)))
    monkeypatch.setattr(L, "_integrator_digest", lambda: None)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    resp = L.lambda_handler({"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}, None)
    assert resp["statusCode"] == 200, resp
    lead = json.loads(resp["body"])["lead_daily"]
    assert lead["text"] == GROUNDED
    assert lead["generated_at"] == row["generated_at"]
    assert lead["data_through"] == DATA["date"]
    assert lead["cited"] == _cited()
    assert lead["coach_id"] == "eli_marsh"
    assert lead["coach_name"]  # the registry lead's byline, for the door

    # no row -> null, and the door's old chain decides
    monkeypatch.setattr(L, "table", FakeDdbTable())
    body = json.loads(L.lambda_handler({"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}, None)["body"])
    assert body["lead_daily"] is None


def test_coach_profile_serves_the_lead_daily_as_daily(monkeypatch):
    from web import site_api_coach as coach_api

    row = _written_row()
    monkeypatch.setattr(coach_api, "table", FakeDdbTable(query_hook=_lead_query_hook(row)))
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    resp = coach_api.handle_coach({"rawPath": "/api/coach/eli_marsh"})
    assert resp["statusCode"] == 200, resp
    body = json.loads(resp["body"])
    assert body["daily"] == GROUNDED  # the string contract every consumer of `daily` reads
    assert body["lead_daily"]["cited"] == _cited()


def test_the_daily_brief_calls_the_lead_read_once_with_its_persist_flag():
    src = open(os.path.join(_REPO, "lambdas", "emails", "daily_brief_lambda.py")).read()
    calls = re.findall(r"lead_daily_read\.run\(([^)]*)\)", src)
    assert calls == ["data, profile, table=table, persist=persist"]
