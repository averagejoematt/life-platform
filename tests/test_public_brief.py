"""tests/test_public_brief.py — the public-safe coaching brief (owner ruling 2026-11-09, third, E).

Pins, offline (no AWS; Bedrock replaced by a canned reply):

  1. THE INPUT WHITELIST is derived: a metric is an input only when every source it reads is classified public, and a
     source turned private drops its metrics (mutation control). No private family can reach a brief's provenance.
  2. THE CONTRACT: a brief whose input set includes a private family is WITHHELD by the public chokepoint
     (``web.narrative_publication``) and omitted by ``/api/coach_brief``; the same brief with public inputs is served
     (the negative control). And the producer refuses to make a call when its input set is not publishable.
  3. THE DARK SWITCH: off by default; the route 404s and the brief's ledger calls are private while it is off.
  4. NO BACKFILL: only the current cycle, never before FIRST_CYCLE — refused before any read or model call.
  5. THE SECTIONS: observations are computed (not written by the model); calls are rendered, filed GRADEABLE in the
     prediction ledger and their frozen test copied; items that fail a check are dropped; evidence and revisions are
     append-only rows linked to the brief they belong to; a brief is never rewritten.
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
os.environ.setdefault("CONTENT_FILTER_JSON", json.dumps({"blocked_vices": [], "blocked_vice_keywords": ["fixtureblockedword"]}))

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

import pytest  # noqa: E402
from coach import persona_registry, public_brief as PB  # noqa: E402
from common import (  # noqa: E402
    activity_publication as AP,
    narrative_provenance as NP,
    prediction_publication as PP,
    public_brief_policy as POL,
)
from experiment.measurable_metrics import METRIC_SOURCES  # noqa: E402
from web import narrative_publication as NPUB, site_api_coach_brief as API  # noqa: E402

CYCLE = "2026-11-16"
TODAY = "2026-11-16"
COACH = "nutrition_coach"


# ── a small in-memory table: begins_with queries, conditional puts ─────────────────────────
class Table:
    def __init__(self, rows=()):
        self.store = {(r["pk"], r["sk"]): dict(r) for r in rows}
        self.puts = []

    def query(self, **kw):
        eav = kw.get("ExpressionAttributeValues") or {}
        pk, prefix = eav.get(":pk"), eav.get(":p", "")
        items = [dict(v) for (p, s), v in sorted(self.store.items()) if p == pk and s.startswith(prefix)]
        if kw.get("ScanIndexForward") is False:
            items.reverse()
        return {"Items": items}

    def get_item(self, Key, **_kw):
        it = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(it)} if it else {}

    def put_item(self, Item, ConditionExpression=None, **_kw):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and key in self.store:
            raise RuntimeError("ConditionalCheckFailedException")
        self.puts.append(Item)
        self.store[key] = dict(Item)
        return {}


def _series(start, n, base, step=0.0):
    from datetime import datetime, timedelta

    d0 = datetime.strptime(start, "%Y-%m-%d")
    return [((d0 + timedelta(days=i)).strftime("%Y-%m-%d"), base + step * i) for i in range(n)]


SERIES = {
    "total_calories_kcal": _series("2026-10-19", 28, 2100.0, -5.0),
    "total_protein_g": _series("2026-10-19", 28, 150.0, 0.5),
    "weight_lbs": _series("2026-10-19", 28, 190.0, -0.1),
}


def readings(metric, start, end):
    return [(d, v) for d, v in SERIES.get(metric, []) if start <= d <= end]


def tolerance_for(_metric):
    return (1.5, "±1 SD of the trailing 30-day personal series (n=28 readings, SD=1.5)", 28)


def _reply(obj):
    def invoke(body, model_name=None):
        invoke.calls.append(body)
        return {"content": [{"type": "text", "text": json.dumps(obj)}], "usage": {"input_tokens": 900, "output_tokens": 300}}

    invoke.calls = []
    return invoke


def _obs_value(metric, key="last7"):
    obs = PB.observe([metric], CYCLE, readings)
    return obs[0][key]["mean"]


def good_draft():
    cal = _obs_value("total_calories_kcal")
    return {
        "interpretations": [{"text": f"Daily calories averaged {cal} kcal over the last 7 days, below the 28-day mean.", "cites": ["o1"]}],
        "predictions": [
            {
                "metric": "weight_lbs",
                "kind": "direction",
                "direction": "down",
                "window_days": 14,
                "confidence": 0.7,
                "rationale": "Intake is below the 28-day mean.",
                "cites": ["o1", "o3"],
            },
            {
                "metric": "total_protein_g",
                "kind": "level",
                "target": 160,
                "window_days": 7,
                "confidence": 0.6,
                "rationale": "Protein has been climbing.",
                "cites": ["o2"],
            },
        ],
        "recommendations": [
            {
                "text": "Keep protein at or above 150 g every day this week.",
                "rationale": "It is the steadiest lever.",
                "check": {"metric": "total_protein_g", "condition": "at_least", "threshold": 150},
            },
            {"text": "Weigh in each morning.", "rationale": "Daily readings make the trend clearer.", "check": None},
        ],
        "position_changes": [],
    }


def _run(table, draft=None, today=TODAY, **kw):
    invoke = _reply(draft if draft is not None else good_draft())
    out = PB.run(
        table, today=today, coach_ids=[COACH], invoke=invoke, allow=lambda f: True, readings=readings, tolerance_for=tolerance_for, **kw
    )
    return out, invoke


def _served(table, live=True, today=TODAY):
    resp = API.handle_coach_brief({"queryStringParameters": {"coach": COACH}}, table=NPUB.wrap(table), live=live, today=today)
    return resp, (json.loads(resp["body"]) if resp.get("body") else None)


# ── 1. the input whitelist ─────────────────────────────────────────────────────────────────
def test_eligible_metrics_are_exactly_the_ledger_metrics_whose_every_source_is_public():
    expected = sorted(m for m in METRIC_SOURCES if POL.metric_is_eligible(m))
    assert POL.eligible_metrics() == expected and expected
    for m in expected:
        srcs = PP.metric_sources(m)
        assert srcs and all(AP.source_class(s) == NP.PUBLIC for s in srcs), m
    assert all(NP.classify(f) == NP.PUBLIC for f in POL.families_for(expected))


def test_a_source_turned_private_drops_its_metrics_mutation_control(monkeypatch):
    real = AP.source_class
    monkeypatch.setattr(AP, "source_class", lambda s: NP.PRIVATE if s == "macrofactor" else real(s))
    metrics = POL.eligible_metrics()
    assert "total_protein_g" not in metrics and "total_calories_kcal" not in metrics
    assert "weight_lbs" in metrics
    assert PB.coach_metrics(COACH) == ["weight_lbs"]


def test_no_private_family_is_ever_an_input():
    private = {f for f, c in NP.SOURCE_FAMILIES.items() if c == NP.PRIVATE}
    assert {"journal", "journal_presence", "notion", "mood_read", "diary_claims"} <= private
    for m in POL.eligible_metrics():
        assert not set(PP.metric_sources(m)) & private, m


def test_registry_lists_only_known_metrics_and_every_input_has_words():
    personas = persona_registry.personas()
    listed = {m for p in personas.values() for m in (p.get("public_brief_metrics") or [])}
    assert listed and listed <= set(METRIC_SOURCES)
    assert set(POL.eligible_metrics()) <= set(PB.METRIC_WORDS)
    assert PB.brief_coaches() and set(PB.brief_coaches()) <= set(persona_registry.OPERATIONAL_COACH_IDS)


# ── 2. the contract: a private input set is withheld; the public control is served ───────────
def _brief_with(families):
    obs = PB.observe(PB.coach_metrics(COACH), CYCLE, readings)
    sections = {
        "interpretations": [{"id": "i1", "text": "Daily calories ran below the 28-day mean this week.", "cites": ["o1"]}],
        "recommendations": [],
        "position_changes": [],
    }
    prov = NP.stamp(families, producer=PB.PRODUCER)
    return PB.build_brief(COACH, CYCLE, TODAY, obs, sections, [], {}, {"calls": 1}, prov)


@pytest.mark.parametrize("private_family", ["journal", "journal_presence", "state_of_mind", "notion", "mood_read", "diary_claims"])
def test_a_brief_whose_inputs_include_a_private_family_is_withheld(private_family):
    if NP.classify(private_family) != NP.PRIVATE:
        pytest.skip(f"{private_family} is not a registered private family in this tree")
    row = PB._ddb(_brief_with(POL.families_for(PB.coach_metrics(COACH)) + ["persona", private_family]))
    gated = NPUB.gate_item(row)
    assert NPUB.is_withheld(gated)
    assert gated["interpretations"][0]["text"] == ""
    _resp, body = _served(Table([row]))
    assert body["briefs"] == []  # omitted, never marked
    assert "withheld" not in json.dumps(body)


def test_negative_control_the_same_brief_with_public_inputs_is_served():
    row = PB._ddb(_brief_with(POL.families_for(PB.coach_metrics(COACH)) + ["persona"]))
    assert not NPUB.is_withheld(NPUB.gate_item(row))
    _resp, body = _served(Table([row]))
    assert body["briefs"][0]["interpretations"][0]["text"].startswith("Daily calories")
    assert "provenance" not in json.dumps(body)


def test_an_unrecorded_or_unknown_family_is_withheld_too():
    row = PB._ddb(_brief_with(["persona", "a_family_nobody_classified"]))
    assert NPUB.is_withheld(NPUB.gate_item(row))
    row2 = PB._ddb(_brief_with(["persona"]))
    row2.pop("provenance")
    assert NPUB.is_withheld(NPUB.gate_item(row2))


def test_the_producer_refuses_when_its_input_set_is_not_publishable(monkeypatch):
    monkeypatch.setattr(POL, "families_for", lambda ms: ["macrofactor", "journal"])
    table = Table()
    out, invoke = _run(table)
    assert out["results"][COACH]["status"] == "refused"
    assert invoke.calls == [] and table.puts == []


def test_the_written_brief_and_its_calls_carry_a_public_provenance():
    table = Table()
    out, _ = _run(table)
    assert out["results"][COACH]["status"] == "written", out
    for row in table.puts:
        fams = NP.record_of(row)["families"]
        assert NP.is_publishable(row), (row["sk"], fams)
        assert set(fams) <= {"macrofactor", "withings", "persona", "prediction_ledger"}


# ── 3. the dark switch ─────────────────────────────────────────────────────────────────────
def test_the_switch_is_off_and_the_route_404s():
    assert POL.PUBLICATION_LIVE is False
    assert PP.PUBLIC_BRIEF_SOURCE == POL.BRIEF_CALL_SOURCE  # the call policy and the producer name the same source
    table = Table()
    _run(table)
    resp, _ = _served(table, live=None)
    assert resp["statusCode"] == 404


def test_brief_calls_are_private_while_dark_and_classified_by_structure_when_live(monkeypatch):
    table = Table()
    _run(table)
    calls = [r for r in table.puts if r["sk"].startswith("PREDICTION#")]
    assert calls
    for c in calls:
        assert PP.classify(c["pk"], c) == (PP.PRIVATE, PP.PUBLIC_BRIEF_DARK)
    monkeypatch.setattr(POL, "PUBLICATION_LIVE", True)
    for c in calls:
        assert PP.classify(c["pk"], c)[0] == PP.PUBLIC, PP.classify(c["pk"], c)


def test_unknown_coach_404s_even_when_live():
    resp = API.handle_coach_brief({"queryStringParameters": {"coach": "mind_coach"}}, table=NPUB.wrap(Table()), live=True, today=TODAY)
    assert resp["statusCode"] == 404


# ── 4. no backfill ─────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("today,reason", [("2026-11-09", "before_first_cycle"), ("2026-10-05", "before_first_cycle")])
def test_no_cycle_before_the_first(today, reason):
    table = Table()
    out, invoke = _run(table, today=today)
    assert out == {"status": "refused", "reason": reason, "cycle": POL.cycle_of(today)}
    assert invoke.calls == [] and table.puts == []


def test_only_the_cycle_containing_today():
    assert POL.cycle_allowed("2026-11-16", "2026-11-20") == (True, "ok")
    assert POL.cycle_allowed("2026-11-16", "2026-11-24")[1] == "not_the_current_cycle"
    assert POL.cycle_allowed("2026-11-17", "2026-11-17")[1] == "not_a_cycle_start"


def test_budget_pause_reads_and_calls_nothing():
    table = Table()
    invoke = _reply(good_draft())
    out = PB.run(
        table, today=TODAY, invoke=invoke, allow=lambda f: False, readings=lambda *a: pytest.fail("read"), tolerance_for=tolerance_for
    )
    assert out == {"status": "paused", "feature": "coach_narrative"} and invoke.calls == [] and table.puts == []


# ── 5. the sections ────────────────────────────────────────────────────────────────────────
def test_the_model_sees_only_the_computed_facts_and_the_persona():
    table = Table()
    _out, invoke = _run(table)
    body = invoke.calls[0]
    user = body["messages"][0]["content"]
    assert user.count("\n") == 3  # the header line + one line per observation, nothing else
    assert not re.search(r"journal|mood|diary|state of mind|check-in answers", user, re.I)
    assert body["model"] == PB.MODEL


def test_sections_are_served_apart_with_the_frozen_test_and_the_ledger_status(monkeypatch):
    table = Table()
    out, _ = _run(table)
    res = out["results"][COACH]
    assert (res["interpretations"], res["predictions"], res["recommendations"]) == (1, 2, 2)
    _resp, dark = _served(table)  # the route forced on, the switch still off: the calls are held back with their criteria
    assert dark["briefs"][0]["predictions"] == [] and dark["briefs"][0]["evaluation_criteria"] == []
    monkeypatch.setattr(POL, "PUBLICATION_LIVE", True)
    _resp, body = _served(table, live=None)
    b = body["briefs"][0]
    assert set(b) >= {
        "observations",
        "interpretations",
        "predictions",
        "evaluation_criteria",
        "recommendations",
        "owner_actions",
        "revisions",
    }
    assert [o["metric"] for o in b["observations"]] == ["total_calories_kcal", "total_protein_g", "weight_lbs"]
    assert [p["claim"] for p in b["predictions"]] == [
        "Weight will fall over the next 28 days.",
        "Daily protein will be about 160 g on 2026-11-23.",
    ]
    assert all(p["ledger"]["status"] == "pending" for p in b["predictions"])
    stored = {r["prediction_id"]: r for r in table.puts if r["sk"].startswith("PREDICTION#")}
    for c in b["evaluation_criteria"]:
        spec = stored[c["prediction_id"]]["evaluation"]
        assert c["window_end"] == spec["window_end"] and c["type"] == spec["type"]
    assert [a["state"] for a in b["owner_actions"]] == ["pending", "not_measured"]


def test_ledger_calls_are_gradeable_and_linked_to_the_brief():
    table = Table()
    _run(table)
    calls = [r for r in table.puts if r["sk"].startswith("PREDICTION#")]
    for c in calls:
        assert c["source"] == POL.BRIEF_CALL_SOURCE and c["status"] == "pending" and c["filing"]["verdict"] == "gradeable"
        assert c["brief_ref"]["brief_cycle"] == CYCLE and c["brief_ref"]["coach_id"] == COACH
        assert c["created_date"] == CYCLE


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["interpretations"][0].update(text="Daily calories averaged 1234 kcal."),  # a number not in the facts
        lambda d: d["interpretations"][0].update(text="He skipped his journal, so intake drifted."),  # private activity
        lambda d: d["interpretations"][0].update(text="Dinners with his partner pushed intake up."),  # a person
        lambda d: d["interpretations"][0].update(cites=[]),  # cites nothing
        lambda d: d["interpretations"][0].update(text="Daily calories dropped sharply on 2026-12-25."),  # a date nobody was shown
    ],
)
def test_a_failing_interpretation_is_dropped_never_published(mutate):
    draft = good_draft()
    mutate(draft)
    table = Table()
    out, _ = _run(table, draft)
    res = out["results"][COACH]
    assert res["interpretations"] == 0 and res["dropped"]["interpretations"] == 1
    assert res["predictions"] == 2  # the rest of the brief stands


def test_a_call_on_a_metric_outside_the_coach_inputs_is_dropped():
    draft = good_draft()
    draft["predictions"][0]["metric"] = "hrv"
    table = Table()
    out, _ = _run(table, draft)
    assert out["results"][COACH]["predictions"] == 1


def test_nothing_passing_holds_the_brief_and_writes_nothing():
    draft = {"interpretations": [{"text": "He felt tired all week.", "cites": ["o1"]}], "predictions": [], "recommendations": []}
    table = Table()
    out, _ = _run(table, draft)
    assert out["results"][COACH]["status"] == "held" and table.puts == []


def test_a_brief_is_never_rewritten():
    table = Table()
    _run(table)
    n = len(table.puts)
    out, invoke = _run(table)
    assert out["results"][COACH]["status"] == "exists" and len(table.puts) == n and invoke.calls == []


def test_evidence_after_the_window_closes_and_revisions_on_the_next_cycle():
    table = Table()
    _run(table)
    for d in ("2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-21", "2026-11-22"):
        SERIES.setdefault("_week", [])
    SERIES["total_protein_g"] += [
        (d, 152.0 if d != "2026-11-19" else 140.0) for d in ("2026-11-16", "2026-11-17", "2026-11-19", "2026-11-20")
    ]
    SERIES["total_calories_kcal"] += _series("2026-11-16", 7, 1950.0)
    SERIES["weight_lbs"] += _series("2026-11-16", 7, 187.0, -0.1)
    try:
        draft = good_draft()
        draft["position_changes"] = [
            {"target": "r2", "text": "A weekly weigh-in average is enough.", "reason": "Daily readings added little."}
        ]
        out, invoke = _run(table, draft, today="2026-11-23")
        assert out["results"][COACH]["status"] == "written" and out["results"][COACH]["evidence_written"] == 1
        assert "Your previous brief (cycle 2026-11-16)" in invoke.calls[0]["messages"][0]["content"]
        ev = [r for r in table.puts if POL.EVIDENCE_TAG in r["sk"]][0]
        assert ev["sk"] == "PUBLIC_BRIEF#2026-11-16#EVIDENCE#r1"
        assert (ev["days_in_window"], ev["days_with_data"], ev["days_meeting"]) == (7, 4, 3)
        assert ev["source_refs"] == [{"source": "macrofactor", "start": "2026-11-16", "end": "2026-11-22"}]
        rev = [r for r in table.puts if POL.REVISION_TAG in r["sk"]][0]
        assert rev["brief_cycle"] == "2026-11-16" and rev["revised_in_cycle"] == "2026-11-23" and rev["target"] == "r2"
        _resp, body = _served(table, today="2026-11-23")
        older = [b for b in body["briefs"] if b["cycle"] == "2026-11-16"][0]
        assert older["owner_actions"][0]["state"] == "recorded" and older["owner_actions"][0]["days_meeting"] == 3
        assert older["owner_actions"][1]["state"] == "not_measured"
        assert older["revisions"][0]["text"] == "A weekly weigh-in average is enough."
        assert [b["cycle"] for b in body["briefs"]] == ["2026-11-23", "2026-11-16"]
    finally:
        for k in list(SERIES):
            SERIES[k] = [(d, v) for d, v in SERIES[k] if d < "2026-11-16"]
        SERIES.pop("_week", None)


def test_a_private_evidence_or_revision_row_is_omitted():
    table = Table()
    _run(table)
    rev = PB.revision_row(
        COACH,
        CYCLE,
        "2026-11-23",
        {"target": "i1", "text": "Changed my mind on intake.", "reason": "New data."},
        NP.stamp(["journal"], producer="x"),
        0,
    )
    table.store[(rev["pk"], rev["sk"])] = rev
    _resp, body = _served(table)
    assert body["briefs"][0]["revisions"] == []
