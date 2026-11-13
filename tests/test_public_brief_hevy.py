"""tests/test_public_brief_hevy.py — Eli Marsh's brief from Hevy's recorded sessions (owner approval 2026-11-12).

Pins, offline (no AWS; Bedrock replaced by a canned reply):

  1. THE FIELD IS ALREADY PUBLIC AND DERIVED. ``total_volume_kg`` reaches the brief through METRIC_SOURCES and the
     policy's own derivation (Hevy classified PUBLIC), and it is a field ``/api/workouts`` already serves per session.
     Every Hevy-sourced ledger metric must be such a field (guard the set). Excluded and why: ``set_count`` counts
     warm-up, treadmill and mobility "sets"; sessions/week, sets per muscle, top-set load and reps are not row fields the
     grader reads; titles, descriptions and notes are free text. Must-fail control: Hevy turned private drops it.
  2. PERFORMED, NEVER PLANNED. A reading is a performed ``DATE#<d>#WORKOUT#<id>`` row with load logged: a routine /
     pre-draft / plan row in the partition and a load-free (treadmill-only) session are not readings — in the grader's
     series, the brief's readings and the tolerance read alike. Must-fail control: without the rule both are counted.
  3. GRADEABLE. The brief's rendered calls on it (rise, fall, a level on a day) file GRADEABLE through validate_filing,
     and the existing evaluator grades a direction call from Hevy rows (confirmed on a rising series, refuted on a
     falling one). "Zone 2 volume" / "walking volume" never bind to it (bare "volume" names nothing).
  4. NO CLAIM HEVY CANNOT EVIDENCE. Effort, RPE, intensity, technique, pain, injury, soreness, fatigue and strength
     words drop the item; the prompt says so; a clean item passes (control).
  5. THE SWITCH. ``public_brief_enabled`` puts a non-operational coach in the brief and ``false`` takes it out (the rest
     of the brief untouched); Eli is held, not substituted, when Hevy has too few sessions.
"""

import json
import os
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
sys.path.insert(0, os.path.join(_REPO, "tests"))

import pytest  # noqa: E402
from coach import coach_prediction_evaluator as ev, metric_trailing_series as MTS, persona_registry, public_brief as PB  # noqa: E402
from coach.filing_rules import validate_filing  # noqa: E402
from coach.prediction_emission import build_prediction_eval_spec  # noqa: E402
from common import activity_publication as AP, narrative_provenance as NP, public_brief_policy as POL  # noqa: E402
from experiment import measurable_metrics as MM  # noqa: E402
from test_public_brief import Table, _reply  # noqa: E402

ELI = "eli_marsh"
CYCLE = "2026-11-16"
METRIC = "total_volume_kg"


def _workout(day, vol, uid=None, **extra):
    return {
        "pk": "USER#matthew#SOURCE#hevy",
        "sk": f"DATE#{day}#WORKOUT#{uid or day}",
        "date": day,
        "total_volume_kg": vol,
        "set_count": 20,
        "title": "Upper A — felt heavy",
        "description": "private words",
        **extra,
    }


def _days(start, n):
    from datetime import datetime, timedelta

    d0 = datetime.strptime(start, "%Y-%m-%d")
    return [(d0 + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


# 28 days of sessions before the cycle, six a week, rising; a treadmill-only visit and a planned routine row among them
HEVY_ROWS = [_workout(d, 8000.0 + 50 * i) for i, d in enumerate(_days("2026-10-19", 28)) if i % 7 != 6]
HEVY_ROWS += [
    _workout("2026-11-14", 0.0, uid="walk"),  # treadmill-only: no load
    {"pk": "USER#matthew#SOURCE#hevy", "sk": "DATE#2026-11-15#ROUTINE#plan1", "date": "2026-11-15", "total_volume_kg": 99999.0},
]


# ── 1. public and derived ───────────────────────────────────────────────────────────────────
def test_the_metric_is_derived_eligible_through_the_policy():
    assert MM.METRIC_SOURCES[METRIC] == "hevy" and MM.METRIC_SUBDOMAIN[METRIC] == "training"
    assert POL.metric_is_eligible(METRIC) and METRIC in POL.eligible_metrics()
    assert AP.source_class("hevy") == NP.PUBLIC


def test_must_fail_control_hevy_private_drops_it(monkeypatch):
    real = AP.source_class
    monkeypatch.setattr(AP, "source_class", lambda s: NP.PRIVATE if s == "hevy" else real(s))
    assert METRIC not in POL.eligible_metrics() and PB.coach_metrics(ELI) == []
    assert ELI not in PB.brief_coaches()


def _served_workout_fields():
    from web import site_api_training as T

    class _T:
        def query(self, **kw):
            return {"Items": [_workout("2026-11-10", 9000.0)]}

    body = json.loads(T.workouts(_g={"table": _T()})["body"])
    return set(body["workouts"][0])


def test_every_hevy_ledger_metric_is_a_field_api_workouts_already_serves():
    hevy = {m for m, s in MM.METRIC_SOURCES.items() if s == "hevy"}
    assert hevy == {METRIC}  # guard the set: a new Hevy metric must be argued in here
    assert hevy <= _served_workout_fields()


def test_excluded_hevy_fields_are_not_ledger_metrics():
    for f in ("set_count", "exercise_count", "duration_sec", "title", "description", "owner_session_note", "exercises"):
        assert f not in MM.METRIC_SOURCES, f


# ── 2. performed, never planned ─────────────────────────────────────────────────────────────
def test_the_reading_rule():
    assert MM.row_is_reading(_workout("2026-11-10", 9000.0), METRIC)
    assert not MM.row_is_reading(_workout("2026-11-10", 0.0), METRIC)  # load-free session
    assert not MM.row_is_reading({"sk": "DATE#2026-11-10#ROUTINE#x", METRIC: 9000.0}, METRIC)  # a plan
    assert not MM.row_is_reading({"sk": "DATE#2026-11-10", METRIC: 9000.0}, METRIC)  # a legacy day aggregate
    assert MM.row_is_reading({"sk": "DATE#2026-11-10", "weight_lbs": 0.0}, "weight_lbs")  # other metrics untouched


def test_the_grader_series_reads_performed_loaded_sessions_only():
    series = ev._extract_metric_series(HEVY_ROWS, METRIC)
    assert 99999.0 not in [v for _d, v in series] and 0.0 not in [v for _d, v in series]
    assert len(series) == len([r for r in HEVY_ROWS if "#WORKOUT#" in r["sk"] and r["total_volume_kg"]])


def test_must_fail_control_without_the_rule_the_plan_and_the_walk_are_counted(monkeypatch):
    monkeypatch.setattr(ev, "row_is_reading", lambda rec, m: True)
    values = [v for _d, v in ev._extract_metric_series(HEVY_ROWS, METRIC)]
    assert 99999.0 in values and 0.0 in values


class _HevyTable:
    def __init__(self, rows):
        self.rows = rows

    def query(self, **kw):
        eav = kw["ExpressionAttributeValues"]
        items = [r for r in self.rows if r["pk"] == eav[":pk"] and eav[":s"] <= r["sk"] <= eav[":e"]]
        return {"Items": items}


def test_the_brief_readings_and_the_tolerance_read_the_same_rule():
    t = _HevyTable(HEVY_ROWS)
    got = MTS.window_readings(t, "matthew", METRIC, "2026-10-19", "2026-11-15")
    assert got and all(v not in (0.0, 99999.0) for _d, v in got)
    assert ("2026-11-15", 99999.0) not in got


# ── 3. gradeable ────────────────────────────────────────────────────────────────────────────
def _tol(_m):
    return (1500.0, "±1 SD of the trailing 30-day personal series (n=20 readings, SD=1500)", 20)


@pytest.mark.parametrize(
    "pred",
    [
        {"metric": METRIC, "kind": "direction", "direction": "up", "window_days": 14, "confidence": 0.6},
        {"metric": METRIC, "kind": "direction", "direction": "down", "window_days": 28, "confidence": 0.6},
        {"metric": METRIC, "kind": "level", "target": 9000.0, "window_days": 14, "confidence": 0.6},
    ],
)
def test_rendered_calls_file_gradeable(pred):
    row = PB.file_call(ELI, CYCLE, "p1", pred, _tol, {})
    assert row is not None and row["filing"]["verdict"] == "gradeable" and row["status"] == "pending"
    assert "lifting volume" in row["claim_natural"].lower() and row["evaluation"]["metric"] == METRIC


@pytest.mark.parametrize("claim", ["Zone 2 volume will rise over the next 21 days.", "Walking volume will rise over the next 21 days."])
def test_bare_volume_never_binds_to_hevy_lifting_volume(claim):
    v = validate_filing(claim, build_prediction_eval_spec(METRIC, "up", 21), CYCLE, stated_days=21)
    assert v["gradeable"] is False


def _call(direction):
    return {
        "coach_id": ELI,
        "created_date": CYCLE,
        "phase": "experiment",
        "claim_natural": f"Per-session lifting volume will {'rise' if direction == 'up' else 'fall'} over the next 21 days.",
        "evaluation": {"type": "directional", "metric": METRIC, "condition": direction, "evaluation_window_days": 21},
    }


@pytest.mark.parametrize("step,status", [(80.0, "confirmed"), (-80.0, "refuted")])
def test_the_existing_evaluator_grades_a_direction_call_from_hevy_rows(monkeypatch, step, status):
    rows = [_workout(d, 9000.0 + step * i) for i, d in enumerate(_days(CYCLE, 22)) if i % 7 != 6]
    rows.append(_workout("2026-12-06", 0.0, uid="walk"))  # a load-free last visit never decides the grade
    monkeypatch.setattr(ev, "_get_source_data", lambda *a, **k: rows)
    result = ev._evaluate_directional(_call("up"), _call("up")["evaluation"], {}, "2026-12-08")
    assert result["status"] == status, result
    assert result["window"]["last_value"] != 0.0


# ── 4. no claim Hevy cannot evidence ────────────────────────────────────────────────────────
@pytest.mark.parametrize(
    "text",
    [
        "His RPE stayed moderate across the sessions.",
        "Effort looked high this week.",
        "Volume rose while his technique held up.",
        "No sign of injury in the log.",
        "He is getting stronger week on week.",
        "Soreness may explain the lighter session.",
        "Intensity climbed on the lower days.",
    ],
)
def test_unevidenced_training_words_drop_the_item(text):
    assert "unevidenced_training_claim" in PB.text_problems(text, set())


def test_control_a_recorded_volume_sentence_passes():
    assert PB.text_problems("Per-session lifting volume rose over the last 7 days.", {7.0}) == []


def test_the_prompt_forbids_unevidenced_training_claims_and_plans_as_done():
    sp = PB.system_prompt({"name": "Eli Marsh", "title": "Head Coach"}, [METRIC], [METRIC])
    assert "Hevy recorded" in sp and "RPE" in sp and "planned or recommended session" in sp


# ── 5. the switch and the run ───────────────────────────────────────────────────────────────
def _personas(enabled=True):
    p = dict(persona_registry.personas()[ELI])
    p[PB.ENABLED_KEY] = enabled
    return {ELI: p, "nutrition_coach": persona_registry.personas()["nutrition_coach"]}


def test_eli_is_enabled_by_config_and_disabled_by_config_alone():
    assert ELI in PB.brief_coaches() and persona_registry.personas()[ELI].get("operational") is False
    assert ELI in PB.brief_coaches(_personas(True))
    off = PB.brief_coaches(_personas(False))
    assert ELI not in off and "nutrition_coach" in off  # the rest of the brief is untouched


def test_an_explicit_false_takes_an_operational_coach_out_and_a_non_bool_fails_closed():
    p = dict(persona_registry.personas()["nutrition_coach"])
    assert PB.brief_enabled(p) is True
    assert PB.brief_enabled({**p, PB.ENABLED_KEY: False}) is False
    assert PB.brief_enabled({**p, PB.ENABLED_KEY: "yes"}) is False


def _readings_from(rows):
    t = _HevyTable(rows)
    return lambda m, s, e: MTS.window_readings(t, "matthew", m, s, e) if m == METRIC else []


def _eli_draft(mean):
    return {
        "interpretations": [{"text": f"Per-session lifting volume averaged {mean} kg over the last 7 days.", "cites": ["o1"]}],
        "predictions": [
            {
                "metric": METRIC,
                "kind": "direction",
                "direction": "up",
                "window_days": 21,
                "confidence": 0.6,
                "rationale": "The 7-day mean sits above the 28-day mean.",
                "cites": ["o1"],
            }
        ],
        "recommendations": [
            {
                "text": "Log every lifting session in Hevy this week.",
                "rationale": "Each logged session is a reading.",
                "check": {"metric": METRIC, "condition": "at_least", "threshold": 8000},
            }
        ],
        "position_changes": [],
    }


def _eli_run(rows, persist=False):
    readings = _readings_from(rows)
    obs = PB.observe([METRIC], CYCLE, readings)
    mean = obs[0]["last7"]["mean"] if obs else 0
    invoke = _reply(_eli_draft(mean))
    out = PB.run(
        Table(),
        today=CYCLE,
        coach_ids=[ELI],
        persist=persist,
        invoke=invoke,
        allow=lambda f: True,
        readings=readings,
        tolerance_for=_tol,
        personas={ELI: persona_registry.personas()[ELI]},
    )
    return out["results"].get(ELI), invoke


def test_eli_dry_run_files_gradeable_dark_calls_from_hevy():
    res, invoke = _eli_run(HEVY_ROWS)
    assert res["status"] == "dry_run" and len(invoke.calls) == 1
    assert (res["interpretations"], res["predictions"], res["recommendations"]) == (1, 1, 1)
    chk = res["checks"]
    assert chk["brief_provenance_publishable"] and chk["calls_gradeable"] == [True]
    assert chk["call_class_now"] == [["private", "public_brief_dark"]]
    facts = invoke.calls[0]["messages"][0]["content"]
    assert "per-session lifting volume (kg)" in facts and "99999" not in facts and "Upper A" not in facts
    assert "private words" not in json.dumps(invoke.calls)


def test_eli_is_held_not_substituted_when_hevy_has_too_few_sessions():
    rows = [r for r in HEVY_ROWS if r["date"] < "2026-11-11"]  # 2 loaded sessions in the last 7 days (3 needed)
    res, invoke = _eli_run(rows)
    assert res == {"status": "held", "reason": PB.HELD_FOR_INPUTS, "missing": [METRIC], "evidence_written": 0}
    assert invoke.calls == []
