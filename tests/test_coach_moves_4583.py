"""tests/test_coach_moves_4583.py — the coaches' daily line is a move, not numbers restated (#4583).

Offline. The fixtures are the WIRE: the lead read's `cited` block and the per-pillar
absence records are copied from the live `/api/coaching-dashboard` and `/api/character`
bodies of 2026-10-03, and the three refused specimens are the coach texts those same
routes served that day (the journal "silent for eleven days" beside a served 24; "food
logging has been quiet for four days" beside a food log written that morning; a
four-figure recitation).
"""

import json
import os
import sys

import pytest

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

from coach import (
    coach_moves as M,  # noqa: E402
    coach_moves_sheet as S,  # noqa: E402
)
from fakes import FakeDdbTable  # noqa: E402

TODAY = "2026-10-03"

# /api/coaching-dashboard lead_daily, live 2026-10-03 (generated 17:07Z).
LEAD = {
    "text": "(the lead read)",
    "generated_at": "2026-10-03T17:07:06.262395+00:00",
    "data_through": "2026-10-02",
    "coach_id": "eli_marsh",
    "cited": [
        {
            "metric": "day of the experiment",
            "value": "28",
            "as_of": "2026-10-03",
            "source_field": "ai_context.build_experiment_phase_context.days_in",
        },
        {
            "metric": "experiment start date",
            "value": "Sunday, September 6",
            "as_of": "2026-09-06",
            "source_field": "profile.journey_start_date",
        },
        {"metric": "latest weigh-in (lb)", "value": "311.0", "as_of": "2026-10-02", "source_field": "withings.weight_lbs"},
        {"metric": "latest weigh-in date", "value": "Friday, October 2", "as_of": "2026-10-02", "source_field": "withings.sk"},
        {"metric": "starting weight (lb)", "value": "327.3", "as_of": "2026-09-06", "source_field": "profile.journey_start_weight_lbs"},
        {"metric": "lost since the start (lb)", "value": "16.3", "as_of": "2026-10-02", "source_field": "journey.lost_lbs"},
        {
            "metric": "weekly loss rate (lb per week)",
            "value": "3.6",
            "as_of": "2026-10-02",
            "source_field": "computed_metrics.weekly_rate_lbs",
        },
        {
            "metric": "weekly loss rate, likely range (lb per week)",
            "value": "2.5 to 3.9",
            "as_of": "2026-10-02",
            "source_field": "computed_metrics.weekly_rate_ci",
        },
        {"metric": "rate status", "value": "settled", "as_of": "2026-10-02", "source_field": "computed_metrics.rate_provisional"},
        {"metric": "morning recovery score (0-100, Whoop)", "value": "98", "as_of": "2026-10-03", "source_field": "whoop.recovery_score"},
        {"metric": "heart-rate variability (ms)", "value": "58", "as_of": "2026-10-03", "source_field": "whoop.hrv"},
        {
            "metric": "resting heart rate (beats per minute)",
            "value": "54",
            "as_of": "2026-10-03",
            "source_field": "whoop.resting_heart_rate",
        },
        {"metric": "sleep last night (hours)", "value": "8.8", "as_of": "2026-10-03", "source_field": "whoop.sleep_duration_hours"},
    ],
}

# /api/character pillars[].absence, live 2026-10-03.
PILLARS = [
    {
        "name": "movement",
        "absence": {"state": "logged", "last_log_date": "2026-10-03", "days_dark": None, "transition": "logged", "days_since_last_log": 0},
    },
    {
        "name": "nutrition",
        "absence": {"state": "logged", "last_log_date": "2026-10-03", "days_dark": None, "transition": "logged", "days_since_last_log": 0},
    },
    {
        "name": "mind",
        "absence": {"state": "dark", "last_log_date": "2026-09-09", "days_dark": 24, "transition": "paused", "days_since_last_log": 24},
    },
]

# coach_input_facts.nutrition_record's shape, with /api/nutrition_overview's live values.
NUTRITION = {
    "window_start": "2026-09-06",
    "days_logged": 28,
    "latest_log_date": "2026-10-03",
    "lag_days": 0,
    "stalled": False,
    "today_pending": False,
    "protein_avg_g": 148.4,
    "protein_avg_ci95_g": [141.0, 155.8],
    "protein_avg_days": 28,
    "note": "",
}
SERIES = [(f"2026-09-{d:02d}", 140.0 + (d % 7) * 3) for d in range(6, 31)] + [
    ("2026-10-01", 166.0),
    ("2026-10-02", 150.0),
    ("2026-10-03", 153.0),
]

# health.instrument_presence.absent_coaches, live shape (glucose: "no sensor since 2026-08-27").
ABSENT = {
    "glucose_coach": {
        "source": "apple_health",
        "datatype": "cgm",
        "dark": True,
        "last_seen": "2026-08-27",
        "reason": "no sensor since 2026-08-27",
    }
}

NAMES = {
    "sleep_coach": "Lisa Park",
    "nutrition_coach": "Marcus Webb",
    "mind_coach": "Nathan Reeves",
    "physical_coach": "Max Reyes",
    "glucose_coach": "Amara Patel",
    "labs_coach": "James Okafor",
    "explorer_coach": "Henning Brandt",
}

GRADED = [
    {
        "coach_id": "sleep_coach",
        "prediction_id": "pred_sleep_0930",
        "status": "confirmed",
        "claim_natural": "Recovery stays above 60 on at least four of the next seven mornings.",
        "outcome_date": "2026-10-02",
    }
]

POSITIONS = {
    "mind_coach": {"text": "His journal has been silent for eleven days.", "as_of": "2026-10-03"},
    "nutrition_coach": {"text": "Logging resumed on October 1st with 166g protein.", "as_of": "2026-10-03"},
}


def _inputs(**over):
    base = {
        "names": NAMES,
        "lead": LEAD,
        "pillars": PILLARS,
        "nutrition": NUTRITION,
        "protein_series": SERIES,
        "absent": ABSENT,
        "graded": GRADED,
        "positions": POSITIONS,
        "yesterday": [],
    }
    base.update(over)
    return base


@pytest.fixture
def sheet():
    return S.build_sheet(_inputs(), TODAY)


# ── the sheet ────────────────────────────────────────────────────────────────


def test_the_sheet_carries_the_served_values_once(sheet):
    by = {f["key"]: f["value"] for f in sheet["facts"]}
    assert by["journal.days_since"] == "24", "the journal gap is the /api/character value, not a coach's"
    assert by["food_log.state"] == "logged" and by["food_log.days_since"] == "0"
    assert by["withings.weight_lbs"] == "311.0" and by["whoop.recovery_score"] == "98"
    assert by["nutrition.days_logged"] == "28" and by["nutrition.protein_avg_g"] == "148.4"
    assert sheet["absent"] == [{"coach_id": "glucose_coach", "name": "Amara Patel", "reason": "no sensor since 2026-08-27"}]
    assert sheet["served"]["weight"]["weekly_rate_lbs"] == -3.6
    assert sheet["served"]["weight"]["weekly_rate_ci_low"] == -3.9


def test_context_masks_every_figure(sheet):
    ctx = S.context_text(sheet, NAMES)
    assert "eleven" not in ctx and "166" not in ctx, ctx
    assert "[n] days" in ctx
    assert "Amara Patel" in ctx and "no sensor since" in ctx


def test_a_lead_read_older_than_a_day_is_not_on_the_sheet():
    old = dict(LEAD, generated_at="2026-09-30T17:00:00+00:00")
    sh = S.build_sheet(_inputs(lead=old), TODAY)
    assert not [f for f in sh["facts"] if f["source"] == "lead_daily.cited"]


# ── the specimens: the served 2026-10-03 texts are each refused ───────────────

SPECIMENS = {
    "mind_eleven_days": (
        "I think his recovery on the night of October 1st reached 98%—the highest yet—but his deep sleep is declining "
        "and his journal has been silent for eleven days.",
        "call",
    ),
    "physical_food_quiet": ("I expect more of the same: food logging has been quiet for four days and I doubt that changes.", "call"),
    "sleep_recitation": (
        "On the night of October 1st, his Whoop captured 98% recovery, 58.8 ms HRV, 54 bpm resting heart rate, and 24.9% deep sleep "
        "— objectively strong numbers.",
        "call",
    ),
}


def test_every_served_specimen_is_refused(sheet):
    held = {name: S.check_line(text, move, sheet, today=TODAY) for name, (text, move) in SPECIMENS.items()}
    assert all(held.values()), held
    assert any("journal" in r or "11" in r for r in held["mind_eleven_days"]), held["mind_eleven_days"]
    assert any(r.startswith("absence_state:food_log") for r in held["physical_food_quiet"]), held["physical_food_quiet"]
    assert any(r.startswith("restates_numbers") for r in held["sleep_recitation"]), held["sleep_recitation"]


GOOD = {
    "call": "I expect the journal to stay quiet through the weekend, and I think that matters more than a recovery of 98 does.",
    "question": "My question for Matthew: what would make the journal feel worth opening again this week?",
    "reply": "I disagree with Nathan Reeves here: I think the quiet journal says more about a busy week than about his mood.",
    "reaction": "I called it right on recovery holding up, and I think the long nights helped it hold so well.",
    "change_of_mind": "I used to think the scale would stall this month; I now think a loss of 3.6 lb a week can hold a while longer.",
}


@pytest.mark.parametrize("move", sorted(GOOD))
def test_a_genuine_move_passes(sheet, move):
    target = "Nathan Reeves" if move == "reply" else ""
    assert S.check_line(GOOD[move], move, sheet, today=TODAY, target_name=target) == []


# ── the numbers-restated refusal, and its mutation control ────────────────────

RESTATEMENT = "His recovery came in at 98 this morning, with heart-rate variability at 58 ms and a resting heart rate of 54 bpm."


def test_a_line_that_only_restates_numbers_is_refused(sheet):
    reasons = S.check_line(RESTATEMENT, "call", sheet, today=TODAY)
    assert "restates_numbers:3_figures" in reasons and "restates_numbers:no_opinion" in reasons, reasons


def test_mutation_control_the_restatement_refusal_is_what_holds_it(sheet, monkeypatch):
    """Disarm ONLY restatement_findings: the same line must then pass every other check.
    If it did not, the refusal above could be coming from somewhere else, and the
    numbers-only rule would be a gate wired to nothing."""
    monkeypatch.setattr(S, "restatement_findings", lambda *a, **kw: [])
    assert S.check_line(RESTATEMENT, "call", sheet, today=TODAY) == []


def test_mutation_control_each_restatement_arm_fires_alone(sheet, monkeypatch):
    one_figure = "His recovery came in at 98 this morning."
    assert S.restatement_findings(one_figure, "call") == ["restates_numbers:no_opinion", "move_not_made:call"]
    monkeypatch.setattr(S, "MAX_FIGURES", 99)
    assert "restates_numbers:3_figures" not in S.restatement_findings(RESTATEMENT, "call")


def test_a_value_not_on_the_sheet_is_refused(sheet):
    reasons = S.check_line("I think he will be under 309.2 pounds by Sunday.", "call", sheet, today=TODAY)
    assert any("309.2" in r for r in reasons), reasons
    spelled = S.check_line("I think the journal stays quiet; it has been nineteen days.", "call", sheet, today=TODAY)
    assert any("19" in r for r in spelled), spelled


@pytest.mark.parametrize(
    "text,reason",
    [
        ("I think you should open the journal again this week.", "second_person"),
        ("I expect Dr. Reeves will want the journal back by Sunday.", "honorific"),
        ("I think this third attempt will hold up through next week.", "cycle_or_reset_count"),
        ("I expect the reset will hold through next week.", "cycle_or_reset_count"),
        ("I think the calorie deficit will keep the loss going next week.", "calorie_figure"),
        ('I expect him to say "I am done with the journal" by Sunday.', "words_in_his_mouth"),
        ("I think the weight is falling because of the long nights, and I expect more next week.", "causal"),
    ],
)
def test_the_standing_reader_rules_refuse(sheet, text, reason):
    assert reason in S.check_line(text, "call", sheet, today=TODAY)


def test_a_move_not_made_is_refused(sheet):
    assert "move_not_made:question" in S.check_line("I think the journal matters this week.", "question", sheet, today=TODAY)
    assert "move_not_made:reply" in S.check_line(GOOD["reply"], "reply", sheet, today=TODAY, target_name="Max Reyes")


def test_two_lines_may_not_tie_two_values_to_one_metric(sheet):
    sh = dict(sheet, facts=sheet["facts"])
    first = "I think the journal has been quiet 24 days and it will stay quiet."
    second = "I expect the journal, quiet 12 days, to open again soon."
    assert S.cross_line_findings(second, [first], sh) == ["cross_line:journal.days_since"]
    assert S.cross_line_findings(first, [first], sh) == []


# ── the cast, admitted in code ───────────────────────────────────────────────

ELIGIBLE = [c for c in NAMES if c not in ABSENT]


def test_admit_cast_drops_what_code_does_not_admit(sheet):
    raw = {
        "speakers": [
            {"coach_id": "glucose_coach", "move": "call"},
            {"coach_id": "mind_coach", "move": "question"},
            {"coach_id": "sleep_coach", "move": "reaction", "result": "pred_unknown"},
            {"coach_id": "physical_coach", "move": "reply", "replies_to": "mind_coach"},
            {"coach_id": "labs_coach", "move": "change_of_mind"},
            {"coach_id": "nutrition_coach", "move": "call"},
            {"coach_id": "explorer_coach", "move": "call"},
        ]
    }
    plan = M.admit_cast(raw, sheet, ELIGIBLE, TODAY)
    assert [(s["coach_id"], s["move"]) for s in plan["speakers"]] == [
        ("mind_coach", "question"),
        ("physical_coach", "reply"),
        ("nutrition_coach", "call"),
    ]
    why = {d["coach_id"]: d["reason"] for d in plan["dropped"]}
    assert "sidelined" in why["glucose_coach"]
    assert "graded result" in why["sleep_coach"]
    assert "earlier position" in why["labs_coach"]
    assert "more than 3" in why["explorer_coach"]


def test_a_reply_is_ordered_after_the_line_it_answers(sheet):
    raw = {
        "speakers": [
            {"coach_id": "physical_coach", "move": "reply", "replies_to": "sleep_coach"},
            {"coach_id": "sleep_coach", "move": "call"},
        ]
    }
    sh = dict(sheet, positions={**sheet["positions"], "sleep_coach": {"text": "x", "as_of": ""}})
    plan = M.admit_cast(raw, sh, ELIGIBLE, TODAY)
    assert [s["coach_id"] for s in plan["speakers"]] == ["sleep_coach", "physical_coach"]


def _bet(**over):
    b = {
        "metric": "weight_lbs",
        "condition": "lt",
        "threshold": 309,
        "resolution_days": 7,
        "sides": {"sleep_coach": True, "physical_coach": False},
    }
    b.update(over)
    return b


def test_a_bet_is_admitted_only_on_opposite_sides_of_a_gradable_metric(sheet):
    speakers = [{"coach_id": "sleep_coach"}, {"coach_id": "physical_coach"}]
    ok = M.admit_bet(_bet(), speakers, TODAY)
    assert ok and ok["normalized"]["resolution_date"] == "2026-10-10"
    assert ok["description"] == "weight below 309 on Saturday, October 10"
    assert M.admit_bet(_bet(sides={"sleep_coach": True, "physical_coach": True}), speakers, TODAY) is None
    assert M.admit_bet(_bet(metric="total_calories_kcal"), speakers, TODAY) is None, "no calorie bet reaches a reader"
    assert M.admit_bet(_bet(metric="mood_vibes"), speakers, TODAY) is None
    assert M.admit_bet(_bet(), [{"coach_id": "sleep_coach"}], TODAY) is None, "both bettors must be speaking"


# ── the whole run, offline ───────────────────────────────────────────────────


class _Invoke:
    def __init__(self, cast, lines):
        self.cast, self.lines, self.calls = cast, dict(lines), []

    def __call__(self, body, model_name=None):
        self.calls.append(model_name)
        if model_name == M.CAST_MODEL:
            text = json.dumps(self.cast)
        else:
            who = _CURRENT["speaker"]
            text = self.lines[who].pop(0) if isinstance(self.lines[who], list) else self.lines[who]
        return {"content": [{"type": "text", "text": text}], "usage": {"input_tokens": 1500, "output_tokens": 80}}


_CURRENT = {"speaker": None}


def _run(monkeypatch, cast, lines, **kw):
    table = FakeDdbTable()
    real_line_user = M.line_user

    def _line_user(sp, *a, **k):
        _CURRENT["speaker"] = sp["coach_id"]
        return real_line_user(sp, *a, **k)

    monkeypatch.setattr(M, "line_user", _line_user)
    inv = _Invoke(cast, lines)
    opened = []

    def _open(dis, day):
        opened.append((dis, day))
        return {"opened": [{"sk": "OPEN#physical_coach__sleep_coach#weight", "resolution_date": "2026-10-10"}], "skipped": []}

    out = M.run(
        table,
        names=NAMES,
        voices=lambda cid: ("", ""),
        today=TODAY,
        coach_ids=list(NAMES),
        invoke=inv,
        allow=lambda f: True,
        inputs=_inputs(),
        open_bet=_open,
        **kw,
    )
    return out, table, inv, opened


def test_run_writes_tagged_lines_and_opens_a_bet_on_opposed_lines(monkeypatch):
    cast = {
        "speakers": [
            {"coach_id": "sleep_coach", "move": "call", "about": "the scale"},
            {"coach_id": "physical_coach", "move": "reply", "replies_to": "sleep_coach", "about": "disagree"},
        ],
        "bet": _bet(),
    }
    lines = {
        "sleep_coach": "I expect him to be below 309 by Saturday, October 10; the long nights are helping and I'll say so now.",
        "physical_coach": "I disagree with Lisa Park: I think he will not be below 309 by Saturday, October 10, with his steps down.",
    }
    out, table, inv, opened = _run(monkeypatch, cast, lines)
    assert out["status"] == "written" and out["lines"] == 2 and out["bet"] is True, out
    assert inv.calls.count(M.CAST_MODEL) == 1 and inv.calls.count(M.LINE_MODEL) == 2
    row = table.puts[-1]
    assert row["pk"] == "COACH#eli_marsh" and row["sk"] == f"MOVES#{TODAY}"
    assert [(ln["coach_id"], ln["move"], ln["date"]) for ln in row["lines"]] == [
        ("sleep_coach", "call", TODAY),
        ("physical_coach", "reply", TODAY),
    ]
    assert row["absent"] == [{"coach_id": "glucose_coach", "name": "Amara Patel", "reason": "no sensor since 2026-08-27"}]
    assert set(row["silent"]) == {"nutrition_coach", "mind_coach", "labs_coach", "explorer_coach"}
    assert row["lines"][0]["bet"]["resolution_date"] == "2026-10-10"
    dis, day = opened[0][0][0], opened[0][1]
    assert day == TODAY and dis["positions"]["sleep_coach"] == lines["sleep_coach"]
    assert dis["resolution_criterion"]["sides"] == {"sleep_coach": True, "physical_coach": False}

    served = M.served(row)
    assert served["lines"][1]["move_label"] == "A reply" and served["lines"][1]["replies_to_name"] == "Lisa Park"
    assert served["absent"][0]["reason"] == "no sensor since 2026-08-27"


def test_a_line_refused_twice_is_held_and_the_coach_is_silent(monkeypatch):
    cast = {"speakers": [{"coach_id": "sleep_coach", "move": "call"}], "bet": None}
    out, table, inv, opened = _run(monkeypatch, cast, {"sleep_coach": [RESTATEMENT, RESTATEMENT]})
    row = table.puts[-1]
    assert row["lines"] == [] and row["held"][0]["coach_id"] == "sleep_coach"
    assert inv.calls.count(M.LINE_MODEL) == 2, "one regeneration, then held"
    assert "sleep_coach" in row["silent"] and not opened


def test_no_bet_opens_unless_both_opposed_lines_stand(monkeypatch):
    cast = {"speakers": [{"coach_id": "sleep_coach", "move": "call"}, {"coach_id": "physical_coach", "move": "call"}], "bet": _bet()}
    lines = {
        "sleep_coach": "I expect him below 309 by Saturday, October 10, and I'll stand by it.",
        "physical_coach": [RESTATEMENT, RESTATEMENT],
    }
    out, table, inv, opened = _run(monkeypatch, cast, lines)
    assert out["bet"] is False and not opened


def test_budget_pause_and_an_existing_row_cost_nothing(monkeypatch):
    inv = _Invoke({}, {})
    out = M.run(FakeDdbTable(), names=NAMES, voices=lambda c: ("", ""), today=TODAY, invoke=inv, allow=lambda f: False)
    assert out["status"] == "paused" and inv.calls == []
    t = FakeDdbTable(rows=[{"pk": M.PK, "sk": f"MOVES#{TODAY}", "date": TODAY, "lines": []}])
    out = M.run(t, names=NAMES, voices=lambda c: ("", ""), today=TODAY, invoke=inv, allow=lambda f: True)
    assert out["status"] == "already_written" and inv.calls == []


def test_latest_served_reads_the_newest_visible_row():
    row = {
        "pk": M.PK,
        "sk": "MOVES#2026-10-03",
        "date": "2026-10-03",
        "generated_at": "x",
        "lines": [],
        "absent": [],
        "silent": ["sleep_coach"],
    }
    t = FakeDdbTable(rows=[row])
    assert M.latest_served(t) == {"date": "2026-10-03", "generated_at": "x", "lines": [], "absent": [], "silent": ["sleep_coach"]}


def _moves_query_hook(row):
    def hook(table, **kw):
        expr = kw["KeyConditionExpression"].get_expression()
        if expr.get("operator") == "AND":
            pk = expr["values"][0].get_expression()["values"][1]
            sk = expr["values"][1].get_expression()["values"][1]
            if pk == "COACH#eli_marsh" and sk == "MOVES#":
                return {"Items": [dict(row)]}
        return {"Items": []}

    return hook


def test_coaching_dashboard_serves_moves_from_the_producer_row(monkeypatch):
    """The wire the edition reads: /api/coaching-dashboard `moves` (None until a row lands)."""
    from ai import budget_guard
    from web import site_api_coach as coach_api, site_api_lambda as L

    cast = {"speakers": [{"coach_id": "mind_coach", "move": "question"}], "bet": None}
    _out, table, _inv, _opened = _run(monkeypatch, cast, {"mind_coach": GOOD["question"]})
    row = table.puts[-1]
    monkeypatch.setattr(coach_api, "table", FakeDdbTable())
    monkeypatch.setattr(L, "table", FakeDdbTable(query_hook=_moves_query_hook(row)))
    monkeypatch.setattr(L, "_integrator_digest", lambda: None)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 0)
    resp = L.lambda_handler({"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}, None)
    assert resp["statusCode"] == 200, resp
    moves = json.loads(resp["body"])["moves"]
    assert moves["date"] == TODAY
    assert moves["lines"] == [
        {
            "coach_id": "mind_coach",
            "name": "Nathan Reeves",
            "move": "question",
            "move_label": "A question for Matthew",
            "text": GOOD["question"],
            "date": TODAY,
            "replies_to": None,
            "replies_to_name": None,
        }
    ]
    assert moves["absent"] == [{"coach_id": "glucose_coach", "name": "Amara Patel", "reason": "no sensor since 2026-08-27"}]
    monkeypatch.setattr(L, "table", FakeDdbTable())
    body = json.loads(L.lambda_handler({"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}, None)["body"])
    assert body["moves"] is None


def test_graded_claims_are_context_and_their_figures_never_join_the_allow_list():
    graded = GRADED + [
        {
            "coach_id": "nutrition_coach",
            "prediction_id": "p2",
            "status": "refuted",
            "claim_natural": "Protein reaches 190g daily.",
            "outcome_date": "2026-10-03",
        }
    ]
    sh = S.build_sheet(_inputs(graded=graded), TODAY)
    assert "190" not in S.sheet_text(sh) and "190" not in S.context_text(sh, NAMES)
    assert [g["prediction_id"] for g in sh["graded"]] == ["p2", "pred_sleep_0930"], "newest first"
    allowed, _dates = S.allowed_for(sh)
    assert 190.0 not in allowed
