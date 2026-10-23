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
    "call": "I expect his protein to hold through the weekend, and I think that matters more than a recovery of 98 does.",
    "question": "My question for Matthew: what would make the Saturday long run feel worth doing again this week?",
    "reply": "I disagree with Nathan Reeves here: I think the lighter training says more about a busy week than about his mood.",
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
    assert M.latest_served(t) == {
        "date": "2026-10-03",
        "generated_at": "x",
        "lines": [],
        "absent": [],
        "silent": ["sleep_coach"],
        # a row written before box 5 carries no `sidelined`: it is derived from `silent`
        "sidelined": [{"coach": "sleep_coach", "state": "absent", "reason": M.SIDELINE_REASONS["quiet"]}],
    }


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


def test_a_calendar_day_is_a_date_not_a_figure_and_a_bare_small_count_is_not_a_figure(sheet):
    assert S.figures_in("I expect 309 by Saturday, October 10.") == [309.0]
    assert S.off_sheet_figures("I think two of us agree, and 7 lb is not on the sheet.", S.allowed_for(sheet)[0]) == [7.0]
    assert S.off_sheet_figures("I expect the loss of 3.6 lb a week to hold.", S.allowed_for(sheet)[0]) == []


def test_a_cast_that_names_coaches_by_name_is_recognised(sheet):
    """The first live run (2026-10-04) cast three speakers by NAME; every one was dropped as
    "not on the roster" and the front page served no line. This is that wire."""
    names = {"mind_coach": "Nathan Reeves", "labs_coach": "Dr. James Okafor", "nutrition_coach": "Marcus Webb", "sleep_coach": "Lisa Park"}
    raw = {
        "speakers": [
            {"coach_id": "Marcus Webb", "move": "question"},
            {"coach_id": "nathan reeves", "move": "call"},
            {"coach_id": "James Okafor", "move": "reply", "replies_to": "Marcus Webb"},
        ]
    }
    plan = M.admit_cast(raw, sheet, ELIGIBLE, TODAY, names)
    got = {s["coach_id"]: s for s in plan["speakers"]}
    assert not [d for d in plan["dropped"] if "not eligible" in d["reason"]], plan["dropped"]
    assert {"nutrition_coach", "mind_coach"} <= set(got), plan
    if "labs_coach" in got:
        assert got["labs_coach"]["replies_to"] == "nutrition_coach"
    # Control: without the names the same cast is refused, which is the live failure.
    refused = M.admit_cast(raw, sheet, ELIGIBLE, TODAY)
    assert not refused["speakers"] and len(refused["dropped"]) == 3
    # A name that is nobody's still finds nobody.
    assert M.admit_cast({"speakers": [{"coach_id": "Somebody Else", "move": "call"}]}, sheet, ELIGIBLE, TODAY, names)["speakers"] == []


# ── a coach never names herself (#4705) ──────────────────────────────────────

# /api/coach_moves?date=2026-10-07, live 2026-10-10 03:04Z (sleep_coach, reaction) — the wire.
SELF_NAMED = (
    "I was skeptical when Lisa called the recovery spike genuine architecture rather than noise, "
    "but today's recovery suggests she was right."
)


def test_a_line_naming_its_own_speaker_is_refused_4705(sheet):
    reasons = S.check_line(SELF_NAMED, "reaction", sheet, today=TODAY, speaker_name=NAMES["sleep_coach"])
    assert "names_self:Lisa" in reasons, reasons
    assert "names_self:Reyes" in S.check_line("Reyes would say it held.", "reaction", sheet, today=TODAY, speaker_name="Max Reyes")
    assert "names_self:Lisa Park" in S.check_line("lisa park here: it held.", "reaction", sheet, today=TODAY, speaker_name="Lisa Park")
    assert "names_self:Max Reyes" in S.check_line("Max Reyes thinks it held.", "reaction", sheet, today=TODAY, speaker_name="Max Reyes")
    # another coach's name is not the speaker's
    assert not [r for r in S.check_line(SELF_NAMED, "reaction", sheet, today=TODAY, speaker_name="Max Reyes") if r.startswith("names_self")]


def _self_named(text, name):
    return [r for r in S.self_name_findings(text, name) if r.startswith("names_self")]


def test_a_name_part_that_is_an_ordinary_word_never_refuses_4705():
    """Max Reyes (physical_coach) and Lisa Park (sleep_coach) carry name parts that are English words —
    "max", "park". A line using the word is not the coach naming herself (#4705 review)."""
    for text in (
        "I think he should push to max effort on Saturday.",
        "Max heart rate is not the point; I expect the steps to matter more.",
        "I think his VO2 Max will climb through October.",
        "I expect the max he lifts to hold, and a max-effort week to follow.",
        "I think a long walk in the park would do more than another lifting day.",
        "Park the scale for a week; I expect the trend to hold.",
    ):
        assert _self_named(text, "Max Reyes") == [], text
        assert _self_named(text, "Lisa Park") == [], text
    # the surname that is no word, and lowercase first names, behave as names only when capitalised
    assert _self_named("I think reyes is a word nobody uses.", "Max Reyes") == []
    assert _self_named("Reyes thinks it held.", "Max Reyes") == ["names_self:Reyes"]
    # every live word-part is on the list, so no roster coach trips on it
    for part in ("Max", "Park", "Marsh", "Vale", "Brooks"):
        assert part.lower() in S.COMMON_WORD_NAME_PARTS


def test_run_wires_the_speakers_name_into_the_gate_4705(monkeypatch):
    """The production wiring: run() passes the speaker's display name to check_line. A line in which
    physical_coach names himself twice is held; without the wiring it would ship."""
    named = "Reyes thinks the long nights will keep the weight falling, and I expect that to hold through the weekend."
    cast = {"speakers": [{"coach_id": "physical_coach", "move": "call"}], "bet": None}
    out, table, inv, opened = _run(monkeypatch, cast, {"physical_coach": [named, named]})
    row = table.puts[-1]
    assert row["lines"] == [], row["lines"]
    assert row["held"][0]["coach_id"] == "physical_coach"
    assert row["held"][0]["reasons"] == ["names_self:Reyes"], row["held"]
    # control: the same line from another coach is not self-naming and ships
    cast = {"speakers": [{"coach_id": "sleep_coach", "move": "call"}], "bet": None}
    out, table, inv, opened = _run(monkeypatch, cast, {"sleep_coach": [named, named]})
    assert [ln["coach_id"] for ln in table.puts[-1]["lines"]] == ["sleep_coach"], table.puts[-1]["held"]


def test_the_speakers_own_entries_read_you_4705(sheet):
    ctx = S.context_text(sheet, NAMES, speaker="sleep_coach")
    assert "you (your own call) predicted" in ctx and "Lisa Park predicted" not in ctx, ctx
    other = S.context_text(sheet, NAMES, speaker="mind_coach")
    assert "Lisa Park predicted" in other
    sh = S.build_sheet(_inputs(positions={"sleep_coach": {"text": "Sleep held.", "as_of": "2026-10-03"}}), TODAY)
    assert "you (your own last position" in S.context_text(sh, NAMES, speaker="sleep_coach")
    assert "Lisa Park (sleep_coach" not in S.context_text(sh, NAMES, speaker="sleep_coach")


def test_line_user_and_prompt_tell_the_speaker_who_she_is_4705(sheet):
    sp = {"coach_id": "sleep_coach", "move": "reaction", "result": "pred_sleep_0930"}
    user = M.line_user(sp, sheet, NAMES, {}, None, "")
    assert "YOU ARE Lisa Park" in user
    assert "your own call predicted" in user and "sleep_coach predicted" not in user, user
    assert 'Say "I", never your own name' in M.LINE_PROMPT


# ── round 8: repeats, tics, jargon (the live lines of 2026-10-05..09) ───────
#
# The fixtures are the WIRE: each text is what https://averagejoematt.com/api/coach_moves?date=...
# served on that date (read 2026-10-11), keyed by date and coach.

WIRE = {
    ("2026-10-05", "nutrition_coach", "reaction"): (
        "Marcus Webb called it — non-compensated carb cuts correlating with recovery decline — and that result is graded "
        "true, yet Matthew's recovery score today is 98, his strongest so far; I think the structure held better than the "
        "prediction implied."
    ),
    ("2026-10-07", "sleep_coach", "reaction"): (
        "I was skeptical when Lisa called the recovery spike genuine architecture rather than noise, but today's 77 recovery "
        "score and HRV of 57 — so far — suggest she was right and Matthew's sleep structure is holding load, not just "
        "bouncing off a floor event."
    ),
    ("2026-10-07", "nutrition_coach", "reply"): (
        "James Okafor's protein hold deserves scrutiny — I was wrong about dinner disruption collapsing intake during the "
        "dark journal gap, and Matthew held his average intact, so I think the intake concern is weaker than James is "
        "framing it right now."
    ),
    ("2026-10-07", "mind_coach", "question"): (
        "Does Matthew see the 28-day journal silence as a deliberate choice, or has it quietly become the path of least "
        "resistance — and I wonder if even he knows which one it is yet?"
    ),
    ("2026-10-08", "labs_coach", "reply"): (
        "Marcus Webb is right that dinner underperforms, but so far Matthew's 27-day average has held at 146.9g — I think "
        "the intake concern is weaker than the lab draw absence, which is now the clearest blocker I see."
    ),
    ("2026-10-08", "mind_coach", "question"): (
        "Is the 29-day journal silence something Matthew chose, or something that simply accumulated while he was busy with "
        "everything the logged data shows he's been doing well?"
    ),
    ("2026-10-09", "explorer_coach", "reaction"): (
        "Henning's prediction just came true, and I think it reshapes what we thought we knew — so far, Matthew's recovery "
        "holding at 52ms HRV alongside 20.2 lbs lost suggests glucose dynamics, not protein primacy, are driving his "
        "recovery architecture."
    ),
    ("2026-10-09", "labs_coach", "call"): (
        "I think Matthew will keep deferring the lab draw as long as the symptom baseline stays uncollected — so far, 30 "
        "days of journal silence makes it nearly impossible to build that case, and I expect that gap, not protein, is what "
        "stalls clinical progress next."
    ),
}


def _wire(day, cid, move):
    return WIRE[(day, cid, move)]


def _yesterday_of(day):
    """Yesterday's lines exactly as the sheet carries them (build_sheet masks their figures)."""
    lines = [{"coach_id": cid, "move": mv, "text": t} for (d, cid, mv), t in WIRE.items() if d == day]
    return S.build_sheet(_inputs(yesterday=lines), TODAY)["yesterday"]


def test_the_wire_tics_are_the_prompts_own_words():
    """The count the round-8 read found: 'so far' and 'I think' each sit in five of the eight served lines."""
    texts = list(WIRE.values())
    assert sum(bool(S.TICS["so_far"].search(t)) for t in texts) == 5
    assert sum(bool(S.TICS["i_think"].search(t)) for t in texts) == 5


def test_the_same_coach_asking_the_same_question_twice_is_refused():
    y = _yesterday_of("2026-10-07")
    again = _wire("2026-10-08", "mind_coach", "question")
    assert S.repeat_findings(again, "question", "mind_coach", y) == ["repeats_yesterday:journal"]
    # the subject arm alone carries this one: the two questions share no five-word run
    assert S.shared_run(again, _wire("2026-10-07", "mind_coach", "question")) == ""
    # another coach asking about the journal is not this coach repeating itself
    assert S.repeat_findings(again, "question", "sleep_coach", y) == []
    # a question on a different subject passes
    assert S.repeat_findings("Does Matthew plan his dinners, or take them as they come?", "question", "mind_coach", y) == []


def test_a_sentence_said_again_the_next_day_is_refused():
    y = _yesterday_of("2026-10-07")
    found = S.repeat_findings(_wire("2026-10-08", "labs_coach", "reply"), "reply", "labs_coach", y)
    assert found == ['repeats_yesterday:"i think the intake concern is weaker than"']


def test_the_word_run_strips_figures_and_case():
    a = "On 28 days he Held The Line on protein, and that matters."
    b = "after 29 days he held the line on protein again"
    assert S.shared_run(a, b) == "days he held the line on protein"  # 28 / 29 stripped, so the runs meet at "days"
    assert S.shared_run("he held the line today", "he held the line yesterday") == ""  # four words is not a repeat


def test_a_new_point_the_next_day_passes():
    y = _yesterday_of("2026-10-08")
    for (day, cid, mv), text in WIRE.items():
        if day == "2026-10-09":
            assert S.repeat_findings(text, mv, cid, y) == [], (cid, text)


def test_a_second_line_with_the_same_tic_is_refused():
    first = _wire("2026-10-09", "explorer_coach", "reaction")
    second = _wire("2026-10-09", "labs_coach", "call")
    assert S.tic_findings(first, []) == []
    assert S.tic_findings(second, [first]) == ["tic:so_far", "tic:i_think"]
    assert S.tic_findings("Early days, but I expect the scale to hold through Sunday.", [first]) == []


def test_jargon_in_a_served_line_is_refused(sheet):
    expected = {
        ("2026-10-05", "nutrition_coach", "reaction"): ["jargon:compensated"],
        ("2026-10-07", "sleep_coach", "reaction"): ["jargon:architecture"],
        ("2026-10-09", "explorer_coach", "reaction"): ["jargon:architecture", "jargon:dynamics", "jargon:primacy"],
        ("2026-10-09", "labs_coach", "call"): ["jargon:baseline"],
    }
    for key, text in WIRE.items():
        assert S.jargon_findings(text) == expected.get(key, []), key
    # and check_line carries it
    reasons = S.check_line(_wire("2026-10-09", "explorer_coach", "reaction"), "reaction", sheet, today=TODAY)
    assert {"jargon:architecture", "jargon:dynamics", "jargon:primacy"} <= set(reasons)


def test_mutation_control_check_line_refuses_jargon_only_through_the_plain_words_check(sheet, monkeypatch):
    text = "I expect the journal to stay quiet through the weekend, and the recovery architecture matters more than a score of 98."
    assert "jargon:architecture" in S.check_line(text, "call", sheet, today=TODAY)
    monkeypatch.setattr(S, "jargon_findings", lambda t: [])
    assert "jargon:architecture" not in S.check_line(text, "call", sheet, today=TODAY)


def test_the_retry_names_what_was_wrong():
    note = S.retry_note(['repeats_yesterday:"i think the intake concern is weaker than"', "repeats_yesterday:food_log"])
    assert '"i think the intake concern is weaker than"' in note and "food log" in note
    note = S.retry_note(["tic:so_far", "tic:i_think", "jargon:primacy"])
    assert "different hedge" in note and "early days" in note
    assert "do not write 'I think'" in note
    assert "'primacy'" in note and "plain word" in note


class _RecordingInvoke(_Invoke):
    def __init__(self, cast, lines):
        super().__init__(cast, lines)
        self.messages = []

    def __call__(self, body, model_name=None):
        if model_name == M.LINE_MODEL:
            self.messages.append((_CURRENT["speaker"], body["messages"][0]["content"]))
        return super().__call__(body, model_name)


def _run_round8(monkeypatch, cast, lines, yesterday):
    table = FakeDdbTable()
    real_line_user = M.line_user

    def _line_user(sp, *a, **k):
        _CURRENT["speaker"] = sp["coach_id"]
        return real_line_user(sp, *a, **k)

    monkeypatch.setattr(M, "line_user", _line_user)
    inv = _RecordingInvoke(cast, lines)
    out = M.run(
        table,
        names=NAMES,
        voices=lambda cid: ("", ""),
        today=TODAY,
        coach_ids=list(NAMES),
        invoke=inv,
        allow=lambda f: True,
        inputs=_inputs(yesterday=yesterday),
        open_bet=lambda dis, day: {"opened": [], "skipped": []},
    )
    return out, table.puts[-1], inv


# The 10-08 wire question's shape on the test sheet (2026-10-03: journal quiet 24 days). The wire text itself also
# trips today's absence binding on this sheet ("logged"), so the run tests use this form, which only the repeat refuses.
_AGAIN = "Is the journal something Matthew set aside on purpose, or something that simply slipped away from him this month?"
_NEW_QUESTION = "Does Matthew plan his dinners ahead, or take them as they come each night?"


def test_run_refuses_a_repeated_question_and_tells_the_model_what_it_repeated(monkeypatch):
    yesterday = [{"coach_id": "mind_coach", "move": "question", "text": _wire("2026-10-07", "mind_coach", "question")}]
    cast = {"speakers": [{"coach_id": "mind_coach", "move": "question"}], "bet": None}
    again = _AGAIN
    out, row, inv = _run_round8(monkeypatch, cast, {"mind_coach": [again, _NEW_QUESTION]}, yesterday)
    assert [ln["text"] for ln in row["lines"]] == [_NEW_QUESTION], row["held"]
    retry = inv.messages[1][1]
    assert "it repeats yesterday (journal)" in retry
    # held, never shipped, when the model repeats twice
    out, row, inv = _run_round8(monkeypatch, cast, {"mind_coach": [again, again]}, yesterday)
    assert row["lines"] == [] and row["held"][0]["reasons"] == ["repeats_yesterday:journal"]


def test_mutation_control_the_run_refuses_a_repeat_only_through_repeat_findings(monkeypatch):
    yesterday = [{"coach_id": "mind_coach", "move": "question", "text": _wire("2026-10-07", "mind_coach", "question")}]
    cast = {"speakers": [{"coach_id": "mind_coach", "move": "question"}], "bet": None}
    again = _AGAIN
    monkeypatch.setattr(S, "repeat_findings", lambda *a, **k: [])
    out, row, inv = _run_round8(monkeypatch, cast, {"mind_coach": [again, again]}, yesterday)
    assert [ln["text"] for ln in row["lines"]] == [again]


_FIRST = "I expect his recovery to hold up through Sunday, so far the long nights are carrying it."
_SECOND_TIC = "I disagree with Lisa Park: so far the scale says more than recovery does about this week."
_SECOND_OK = "I disagree with Lisa Park: early days, but the scale says more than recovery does about this week."


def test_run_refuses_a_second_so_far_and_asks_for_a_different_hedge(monkeypatch):
    cast = {
        "speakers": [
            {"coach_id": "sleep_coach", "move": "call"},
            {"coach_id": "physical_coach", "move": "reply", "replies_to": "sleep_coach"},
        ],
        "bet": None,
    }
    out, row, inv = _run_round8(monkeypatch, cast, {"sleep_coach": _FIRST, "physical_coach": [_SECOND_TIC, _SECOND_OK]}, [])
    assert [ln["text"] for ln in row["lines"]] == [_FIRST, _SECOND_OK], row["held"]
    assert "use a different hedge" in inv.messages[2][1]


def test_mutation_control_the_run_refuses_a_tic_only_through_tic_findings(monkeypatch):
    cast = {
        "speakers": [
            {"coach_id": "sleep_coach", "move": "call"},
            {"coach_id": "physical_coach", "move": "reply", "replies_to": "sleep_coach"},
        ],
        "bet": None,
    }
    monkeypatch.setattr(S, "tic_findings", lambda *a, **k: [])
    out, row, inv = _run_round8(monkeypatch, cast, {"sleep_coach": _FIRST, "physical_coach": [_SECOND_TIC, _SECOND_OK]}, [])
    assert [ln["text"] for ln in row["lines"]] == [_FIRST, _SECOND_TIC]


def test_run_retry_names_the_jargon_term(monkeypatch):
    cast = {"speakers": [{"coach_id": "sleep_coach", "move": "call"}], "bet": None}
    jargon = "I expect his recovery architecture to hold up through Sunday; the long nights are carrying it."
    plain = "I expect his recovery to hold up through Sunday; the long nights are carrying it."
    out, row, inv = _run_round8(monkeypatch, cast, {"sleep_coach": [jargon, plain]}, [])
    assert [ln["text"] for ln in row["lines"]] == [plain], row["held"]
    assert "'architecture' is a specialist word" in inv.messages[1][1]


def test_the_prompts_carry_the_round8_rules():
    assert "not cast again for it unless the fact changed or Matthew answered" in M.CAST_PROMPT
    for hedge in ("'early days'", "'on a few days of data'", "'for now'", "'so far'"):
        assert hedge in M.LINE_PROMPT
    assert "vary your opening; do not start with 'I think'" in M.LINE_PROMPT
    assert "('I think'" not in M.LINE_PROMPT, "the prompt no longer hands every coach the same opener"
    assert "{metrics}" in M.CAST_PROMPT and M.CAST_PROMPT.format(metrics="x")


# ── box 5: a sidelined coach shows absent with a reason ──────────────────────
#
# The live MOVES#2026-10-12 row, read-only from DynamoDB on 2026-10-13 (fact_sheet, cost and
# model fields left out; the line's words as served). It was written before box 5, so it carries no `sidelined`: the
# glucose coach is dark, two lines were held, and four eligible coaches did not speak. The
# 2026-10-12 `/api/coach_moves` wire had no `absent` key at all.
ROW_1012 = {
    "pk": "COACH#eli_marsh",
    "sk": "MOVES#2026-10-12",
    "date": "2026-10-12",
    "generated_at": "2026-10-12T19:00:41+00:00",
    "lines": [
        {
            "coach_id": "labs_coach",
            "name": "James Okafor",
            "move": "question",
            "date": "2026-10-12",
            "text": "My read is that 20.8 lb gone in 37 days is real progress, yet two items I flagged weeks ago remain unresolved — "
            "has Matthew taken any step this week to schedule either the blood draw or the symptom check-in?",
            "replies_to": None,
            "replies_to_name": None,
            "result_id": None,
        }
    ],
    "absent": [{"coach_id": "glucose_coach", "name": "Amara Patel", "reason": "no sensor since 2026-08-27"}],
    "silent": ["sleep_coach", "nutrition_coach", "mind_coach", "physical_coach", "explorer_coach"],
    "held": [
        {
            "coach_id": "nutrition_coach",
            "move": "reaction",
            "reasons": ["reader:unlabeled_window_figure", 'repeats_yesterday:"my read is that the"'],
        },
        {"coach_id": "mind_coach", "move": "reply", "reasons": ["restates_numbers:no_opinion"]},
    ],
    "dropped": [],
}
EXPECTED_1012 = [
    {"coach": "glucose_coach", "state": "absent", "reason": M.SIDELINE_REASONS["no_data"]},
    {"coach": "sleep_coach", "state": "absent", "reason": M.SIDELINE_REASONS["quiet"]},
    {"coach": "nutrition_coach", "state": "absent", "reason": M.SIDELINE_REASONS["held"]},
    {"coach": "mind_coach", "state": "absent", "reason": M.SIDELINE_REASONS["held"]},
    {"coach": "physical_coach", "state": "absent", "reason": M.SIDELINE_REASONS["quiet"]},
    {"coach": "explorer_coach", "state": "absent", "reason": M.SIDELINE_REASONS["quiet"]},
]


def test_the_sideline_vocabulary_is_plain_sentences_with_no_number():
    assert set(M.SIDELINE_REASONS) == {"no_data", "held", "quiet"}
    for code, text in M.SIDELINE_REASONS.items():
        assert text.endswith(".") and text[0].isupper(), code
        assert not any(ch.isdigit() for ch in text), f"{code}: a reason never carries a number"
        assert S.jargon_findings(text) == [], f"{code}: plain words only"


def test_the_live_1012_row_serves_every_coach_who_sat_out_with_a_reason():
    served = M.served(ROW_1012)
    assert served["sidelined"] == EXPECTED_1012
    assert "labs_coach" not in {e["coach"] for e in served["sidelined"]}, "a coach who spoke is not absent"
    flat = json.dumps(served["sidelined"])
    for internal in ("no sensor since", "2026-08-27", "restates_numbers", "repeats_yesterday", "reader:"):
        assert internal not in flat, f"the engine's own reason {internal!r} reached the served list"
    assert M.sideline_findings(served["sidelined"]) == []


def test_run_writes_sidelined_beside_the_lines(monkeypatch):
    cast = {
        "speakers": [{"coach_id": "mind_coach", "move": "question"}, {"coach_id": "sleep_coach", "move": "call"}],
        "bet": None,
    }
    _out, table, _inv, _opened = _run(monkeypatch, cast, {"mind_coach": GOOD["question"], "sleep_coach": [RESTATEMENT, RESTATEMENT]})
    row = table.puts[-1]
    assert [ln["coach_id"] for ln in row["lines"]] == ["mind_coach"]
    by = {e["coach"]: e["reason"] for e in row["sidelined"]}
    assert by["glucose_coach"] == M.SIDELINE_REASONS["no_data"]
    assert by["sleep_coach"] == M.SIDELINE_REASONS["held"]
    assert by["labs_coach"] == M.SIDELINE_REASONS["quiet"]
    assert "mind_coach" not in by
    assert set(by) | {"mind_coach"} == set(NAMES), "every coach on the roster either spoke or is absent"
    assert all(e["state"] == "absent" for e in row["sidelined"])
    assert M.sideline_findings(row["sidelined"]) == []
    assert M.served(row)["sidelined"] == row["sidelined"], "a stored list is served as stored"


def test_mutation_control_dropping_the_reason_is_red(monkeypatch):
    """The planted defect — the writer drops the reason — is caught by the check the
    served list passes through, and an entry without a vocabulary reason is never served."""
    real = M.sidelined

    def _no_reason(*a, **kw):
        return [{k: v for k, v in e.items() if k != "reason"} for e in real(*a, **kw)]

    monkeypatch.setattr(M, "sidelined", _no_reason)
    cast = {"speakers": [{"coach_id": "mind_coach", "move": "question"}], "bet": None}
    _out, table, _inv, _opened = _run(monkeypatch, cast, {"mind_coach": GOOD["question"]})
    row = table.puts[-1]
    assert row["sidelined"], "the mutation still wrote the list"
    findings = M.sideline_findings(row["sidelined"])
    assert findings and all(f.endswith(":no_reason") for f in findings), findings
    assert M.served(row)["sidelined"] == [], "an entry with no reason is not served"
    # an off-vocabulary reason (the engine's own words, a raw date) is red too
    leaked = [{"coach": "glucose_coach", "state": "absent", "reason": "no sensor since 2026-08-27"}]
    assert M.sideline_findings(leaked) == ["0:reason_off_vocabulary"]
    assert M.served({**ROW_1012, "sidelined": leaked})["sidelined"] == []
    assert M.sideline_findings([{"coach": "x", "state": "quiet", "reason": M.SIDELINE_REASONS["quiet"]}]) == ["0:state_not_absent"]


def test_both_public_surfaces_carry_absent_beside_the_lines():
    from coach import persona_registry
    from web import site_api_coach_moves as day_route, site_api_edition as ed

    body = day_route.compose("2026-10-12", ROW_1012)
    assert body["state"] == "ok" and [ln["coach_id"] for ln in body["lines"]] == ["labs_coach"]
    assert body["absent"] == EXPECTED_1012
    assert set(body) == {"state", "date", "source", "absent_text", "lines", "absent"}
    assert day_route.compose("2026-10-11", None)["absent"] == [], "no row: nobody is named absent"

    block = ed._coach_moves(M.served(ROW_1012), "2026-10-12", persona_registry.resolve)
    assert {"state", "as_of", "source", "absent_text", "data"} <= set(block), "the block contract stands"
    assert block["state"] == "ok" and block["as_of"] == "2026-10-12"
    assert [ln["coach"] for ln in block["data"]["lines"]] == ["James Okafor"]
    assert block["data"]["absent"] == EXPECTED_1012


# ── journal silence is not reader copy (#4583, #4580) ─────────────────────────

# served on the public front page 2026-10-18 (/api/edition blocks.coach_lines, Nathan Reeves)
SERVED_JOURNAL_SILENCE = "Intake held steady, yet 39 days of journal silence. My read is the block was never nutritional."


@pytest.mark.parametrize(
    "text",
    [
        SERVED_JOURNAL_SILENCE,
        "The journal has been blank for a month and that worries me.",
        "He hasn't written in weeks, so I would ask why.",
        "A blank page where the diary used to be.",
        "No journal entries since the reset says something.",
    ],
)
def test_journal_silence_is_refused(sheet, text):
    assert "journal_silence" in S.check_line(text, "call", sheet, today=TODAY), text


@pytest.mark.parametrize("text", ["I expect his protein to hold through the weekend.", "The long run on Saturday was the right call."])
def test_protein_and_training_lines_do_not_trip_it(text):
    assert S.journal_silence_findings(text) == []


def test_the_retry_names_the_journal_refusal():
    assert "off the record" in S.retry_note(["journal_silence"])


def test_mutation_control_the_desk_and_the_daily_gate_share_one_pattern(sheet, monkeypatch):
    import re

    from common import journal_silence
    from content import story_desk

    budget = {
        "lead": {"thread_id": "t", "angle": "he hasn't written in weeks", "evidence": []}
    }  # no "journal" word: only the shared pattern sees it
    assert S.journal_silence_findings(SERVED_JOURNAL_SILENCE) == ["journal_silence"]
    assert story_desk.absence_lead_findings(budget, {})
    monkeypatch.setattr(journal_silence, "JOURNAL_SILENCE", re.compile(r"(?!x)x"))
    assert S.journal_silence_findings(SERVED_JOURNAL_SILENCE) == []
    assert story_desk.absence_lead_findings(budget, {}) == []
