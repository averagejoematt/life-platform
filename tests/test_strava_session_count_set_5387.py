"""tests/test_strava_session_count_set_5387.py — every Strava-activity counter counts one gym visit once (#5387).

The issue's Set is 15 readers that counted or summed Strava activities directly, outside the cross-source
resolver. On a gym day the Strava partition holds Hevy's own push of the WHOLE session (device `Hevy`,
WeightTraining) and the wearable's record of the ride inside it (before 2026-10-26 WHOOP's, from then the
watch's own upload); the read seam folds only same-sport copies, so each reader counted one 160-minute visit
as 2 sessions / 220 minutes. Each now reads `training.session_count` (THE count over the resolver's parts),
and the Zone 2 members read THE Zone 2 computation (`training.zone2_minutes`, #4627) instead of Strava's day
`total_zone2_seconds` / `zone2_seconds` sums or an average-HR band.

THE FIXTURE is #5369's shared one (`tests/test_gym_visit_one_source_5369.py`: the 2026-10-25 wire's structure,
synthetic numbers), run on both wires:
  * PRE  (to 2026-10-25): Hevy's push + WHOOP's two lift pieces + WHOOP's ride (the seam folds the pieces into
    the push — 2 activities, 220 minutes, as the day row's totals say);
  * POST (from 2026-10-26): Hevy's push + the watch's own ride.
The day rows carry the writer's own totals (`strava_read_seam.day_totals`), so a reader that read them would
see 2 / 220 here.

ONE assertion reports every offender (member × wire), so a regression names every reader it touches.
Mutation control: `test_the_old_readings_are_what_the_set_reported` reproduces the pre-#5387 readings on the
same rows (2 / 220, and the day totals' Zone 2), so the expectations below are not vacuous.
"""

from __future__ import annotations

import copy
import os
import sys
from datetime import date, datetime, timedelta

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "emails"), os.path.join(_REPO, "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

for _k, _v in {
    "AWS_REGION": "us-west-2",
    "AWS_DEFAULT_REGION": "us-west-2",
    "S3_BUCKET": "matthew-life-platform",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "EMAIL_RECIPIENT": "test@example.com",
    "EMAIL_SENDER": "noreply@example.com",
}.items():
    os.environ.setdefault(_k, _v)

import test_gym_visit_one_source_5369 as gym  # noqa: E402 — THE shared fixture
from common.strava_read_seam import day_totals  # noqa: E402 — the writer's own day-total formula
from fakes import FakeDdbTable  # noqa: E402
from training import session_count, zone2_minutes as z2m  # noqa: E402

DAY = gym.DAY  # 2026-10-25
TODAY = "2026-10-26"
GENESIS = "2026-09-06"
VISIT_MIN = 160.0  # the visit's own span (16:40–19:20 UTC); its parts: lift 82, ride 60, mobility 18

WATCH_RIDE = gym._act("90000010", "Ride", "Apple Watch Ultra", "18:00:00", 3600, (1800, 1800, 0, 0, 0), avg_hr=115.0)
WIRES = {
    "pre": (gym.STRAVA_HEVY_PUSH, gym.STRAVA_WHOOP_LIFT_A, gym.STRAVA_WHOOP_RIDE, gym.STRAVA_WHOOP_LIFT_B),
    "post": (gym.STRAVA_HEVY_PUSH, WATCH_RIDE),
}


def strava_row(wire: str) -> dict:
    """The day row as the writer stores it: the activities plus the writer's totals over them."""
    acts = [dict(a) for a in WIRES[wire]]
    return {"pk": "USER#matthew#SOURCE#strava", "sk": f"DATE#{DAY}", "date": DAY, "activities": acts, **day_totals(acts)}


def hevy_row() -> dict:
    """The Hevy session, live (the monthly digest counts only rows carrying their source id)."""
    return {**copy.deepcopy(gym.HEVY), "source_workout_id": "hv-synth-5369", "workout_id": "hv-synth-5369"}


def the_zone2(wire: str, *, with_hevy: bool) -> float:
    """THE Zone 2 computation over the same rows — the number every Zone 2 member must serve."""
    sessions = z2m.counted_sessions([strava_row(wire)], [], None, hevy_rows=[hevy_row()] if with_hevy else None)
    return round(sum(s["zone_2_minutes"] or 0.0 for s in sessions if s["source"]), 1)


# ── one probe per Set member: what it serves for the day, read from its own output ──────────────────


class _Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        base = datetime(2026, 10, 26, 19, 0, 0)
        return base.replace(tzinfo=tz) if tz else base


def _experiment_date(days_back: int) -> str:
    return max(GENESIS, (date.fromisoformat(TODAY) - timedelta(days=days_back)).isoformat())


def _sources(wire: str):
    rows = {"strava": [strava_row(wire)], "hevy": [hevy_row()]}

    def query_source(source, start, end, *a, **k):
        return [copy.deepcopy(r) for r in rows.get(source, []) if start <= r["date"] <= end]

    return query_source


def probe_site_api_training(wire, monkeypatch):
    import json

    from web import site_api_training as sat

    monkeypatch.setattr(sat, "datetime", _Frozen)
    g = {
        "table": FakeDdbTable(query_hook=lambda table, **kw: {"Items": []}),
        "_query_source": _sources(wire),
        "_experiment_date": _experiment_date,
        "EXPERIMENT_START": GENESIS,
    }
    body = json.loads(sat.training_overview(_g=g)["body"])
    day = next(r for r in body["daily_modality_minutes_30d"] if r["date"] == DAY)
    edition = next(r for r in sat.edition_training(_g=g)["training"]["daily_modality_minutes_30d"] if r["date"] == DAY)
    t = body["training"]
    return {
        "sessions": t["workouts_30d"],
        "minutes": t["total_minutes_30d"],
        "day_minutes": day["total_min"],
        "edition_day_minutes": edition["total_min"],
        "weekly_trend_workouts": sum(w["workouts"] for w in body["weekly_trend"]),
        "modality_minutes": sum(m["total_minutes_30d"] for m in body["modality_breakdown"]),
    }


def probe_labelled_facts(wire, monkeypatch):
    from intelligence import labelled_facts

    return {"sessions": labelled_facts.served_sessions_30d(_sources(wire), TODAY, GENESIS)}


def probe_character_engine(wire, monkeypatch):
    from health import character_engine as ce

    comps = {"training_frequency": {"weight": 0.5, "target_sessions_week": 5}, "movement_diversity": {"weight": 0.5, "target_types": 4}}
    _, details = ce.compute_movement_raw(
        {"strava_7d": [strava_row(wire)], "hevy_7d": [hevy_row()]}, {"pillars": {"movement": {"components": comps}}}
    )
    score = details["training_frequency"]["score"]
    sessions = next(n for n in range(10) if ce._pct_of_target(n, 5, 1.4) == score)
    return {"sessions": sessions}


def probe_weekly_digest(wire, monkeypatch):
    from emails import weekly_digest_extractors as wde

    out = wde.ex_strava({DAY: strava_row(wire)}, {}, [hevy_row()])
    return {"sessions": out["activity_count"], "minutes": out["total_minutes"], "zone2": out["zone2_minutes"]}


def probe_monthly_digest(wire, monkeypatch):
    import monthly_digest_lambda as mdl

    out = mdl.ex_strava([strava_row(wire)], None, [hevy_row()])
    return {"sessions": out["activity_count"], "minutes": out["total_minutes"], "zone2": out["zone2_minutes"]}


def probe_partner_email(wire, monkeypatch):
    import partner_email_lambda as pel

    workouts, zone2 = pel.training_week({DAY: strava_row(wire)})
    return {"sessions": workouts, "zone2": zone2}


def probe_daily_brief(wire, monkeypatch):
    import daily_brief_lambda as dbl

    rows = [strava_row(wire)]
    zone2, _miles, sessions = dbl.training_facts({"strava_7d": rows, "strava_30d": rows, "hevy_30d": [hevy_row()]})
    return {"sessions": sessions, "zone2": zone2}


def probe_milestone_ledger(wire, monkeypatch):
    from health import milestone_ledger as ml
    from test_process_milestones_1628 import FakeTable

    table = FakeTable()
    table.put_item(Item=strava_row(wire))
    table.put_item(Item=hevy_row())
    return {"zone2": ml.collect_signals(table, "USER#matthew#SOURCE#", None, TODAY)["zone2_minutes_by_day"][DAY]}


def probe_hypothesis_engine(wire, monkeypatch):
    from compute import hypothesis_engine_lambda as hel

    row = next(r for r in hel.build_data_narrative({"strava": [strava_row(wire)]}) if r["date"] == DAY)
    return {"zone2": row["zone2_min"], "workout": row["workout"]}


def probe_daily_insight(wire, monkeypatch):
    from compute import daily_insight_compute_lambda as dic

    monkeypatch.setattr(dic, "fetch_date", lambda source, d: strava_row(wire) if source == "strava" else None)
    monkeypatch.setattr(dic, "fetch_range", lambda source, s, e: [hevy_row()] if source == "hevy" else [])
    monkeypatch.setattr(dic, "target_kcal", lambda *a, **k: 1800)
    return {"sessions": dic._fetch_execution_metrics(DAY, {})["exercise_sessions"]}


def probe_scoring_engine(wire, monkeypatch):
    from health import scoring_engine as se

    _, details = se.score_movement({"date": DAY, "strava": strava_row(wire), "hevy": [hevy_row()]}, {})
    return {"sessions": details["exercise_sessions"], "minutes": details["exercise_minutes"]}


def probe_ai_summaries(wire, monkeypatch):
    from ai import ai_summaries

    out = ai_summaries.build_data_summary({"date": DAY, "strava": strava_row(wire), "hevy": [hevy_row()]}, {})
    return {"sessions": out["exercise_count"], "minutes": out["exercise_minutes"]}


def probe_field_notes(wire, monkeypatch):
    from intelligence import field_notes_lambda as fnl

    monkeypatch.setattr(fnl, "_query_source", _sources(wire))
    monkeypatch.setattr(fnl, "table", FakeDdbTable(query_hook=lambda t, **kw: {"Items": []}, get_item_hook=lambda t, key, **kw: {}))
    out = fnl.gather_week_data("2026-10-19", "2026-10-25")["training"]
    return {"sessions": out["sessions"], "minutes": out["total_minutes"]}


def probe_mcp_helpers(wire, monkeypatch):
    """The day-intensity fallback reads the day's minutes: hard above 90, moderate above 45. The full
    visit is hard either way, so this probe also halves the visit (an 80-minute session holding a
    30-minute ride): THE count reads 80 (moderate); the summed rows read 110 (hard)."""
    from mcp import helpers

    half = {
        **strava_row(wire),
        "activities": [
            {**gym.STRAVA_HEVY_PUSH, "elapsed_time_seconds": 4800, "moving_time_seconds": 4800},
            {
                **WIRES[wire][-1 if wire == "post" else 2],
                "start_date": f"{DAY}T17:20:00Z",
                "elapsed_time_seconds": 1800,
                "moving_time_seconds": 1800,
            },
        ],
    }
    half.update(day_totals(half["activities"]))
    return {"label": helpers.classify_day_type(strava_activities=[half])}


def probe_training_load(wire, monkeypatch):
    from training import training_load

    _, basis = training_load.daily_training_load([strava_row(wire)], [hevy_row()])
    return {"sessions": basis["sessions"]["total"], "parts": basis["sessions"]["parts"]}


#: member -> (probe, the expected reading on a wire). `zone2:hevy` / `zone2:strava` = THE Zone 2 computation over
#: the rows the member holds (with / without the Hevy session).
SET: dict[str, tuple] = {
    "lambdas/web/site_api_training.py": (
        probe_site_api_training,
        lambda w: {
            "sessions": 1,
            "minutes": VISIT_MIN,
            "day_minutes": VISIT_MIN,
            "edition_day_minutes": VISIT_MIN,
            "weekly_trend_workouts": 1,
            "modality_minutes": VISIT_MIN,
        },
    ),
    "lambdas/intelligence/labelled_facts.py": (probe_labelled_facts, lambda w: {"sessions": 1}),
    "lambdas/health/character_engine.py": (probe_character_engine, lambda w: {"sessions": 1}),
    "lambdas/emails/weekly_digest_extractors.py": (
        probe_weekly_digest,
        lambda w: {"sessions": 1, "minutes": VISIT_MIN, "zone2": round(the_zone2(w, with_hevy=True))},
    ),
    "lambdas/emails/monthly_digest_lambda.py": (
        probe_monthly_digest,
        lambda w: {"sessions": 1, "minutes": VISIT_MIN, "zone2": round(the_zone2(w, with_hevy=True))},
    ),
    "lambdas/emails/partner_email_lambda.py": (probe_partner_email, lambda w: {"sessions": 1, "zone2": the_zone2(w, with_hevy=False)}),
    "lambdas/emails/daily_brief_lambda.py": (probe_daily_brief, lambda w: {"sessions": 1, "zone2": the_zone2(w, with_hevy=True)}),
    "lambdas/health/milestone_ledger.py": (probe_milestone_ledger, lambda w: {"zone2": the_zone2(w, with_hevy=True)}),
    "lambdas/compute/hypothesis_engine_lambda.py": (
        probe_hypothesis_engine,
        lambda w: {"zone2": the_zone2(w, with_hevy=False), "workout": True},
    ),
    "lambdas/compute/daily_insight_compute_lambda.py": (probe_daily_insight, lambda w: {"sessions": 1}),
    "lambdas/health/scoring_engine.py": (probe_scoring_engine, lambda w: {"sessions": 1, "minutes": VISIT_MIN}),
    "lambdas/ai/ai_summaries.py": (probe_ai_summaries, lambda w: {"sessions": 1, "minutes": VISIT_MIN}),
    "lambdas/intelligence/field_notes_lambda.py": (probe_field_notes, lambda w: {"sessions": 1, "minutes": VISIT_MIN}),
    "mcp/helpers.py": (probe_mcp_helpers, lambda w: {"label": "moderate"}),
    "lambdas/training/training_load.py": (probe_training_load, lambda w: {"sessions": 1, "parts": 3}),
}


def test_the_set_is_the_issues_fifteen():
    assert len(SET) == 15


def _no_aws(*_a, **_k):
    raise AssertionError("a Set probe reached AWS — every read here is a fixture")


def test_every_set_member_counts_one_gym_visit_once_on_both_wires(monkeypatch):
    """One visit, 160 minutes, THE Zone 2 — never 2 visits / 220 minutes / the day totals' Zone 2. Every
    offender (member × wire) in one report. No probe may reach AWS (botocore is stubbed to raise)."""
    import botocore.client

    offenders = []
    for member, (probe, expected) in SET.items():
        for wire in WIRES:
            want = expected(wire)
            monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", _no_aws)
            try:
                got = probe(wire, monkeypatch)
            except Exception as e:  # noqa: BLE001 — a member that cannot read the wire is an offender too
                got = {"error": f"{type(e).__name__}: {e}"}
            if got != want:
                offenders.append(f"{member} [{wire}]: served {got}, expected {want}")
            monkeypatch.undo()
    assert not offenders, "a Strava-activity counter counts one gym visit wrong (#5387):\n  " + "\n  ".join(offenders)


def test_the_zone2_members_never_serve_the_day_totals_sum():
    """THE Zone 2 is not Strava's day total on this fixture (the push and the ride both carry the ride's
    minutes), so the Zone 2 expectations above can tell the two apart."""
    for wire in WIRES:
        totals = strava_row(wire)["total_zone2_seconds"] / 60.0
        assert the_zone2(wire, with_hevy=True) < totals and the_zone2(wire, with_hevy=False) < totals, wire


def test_the_old_readings_are_what_the_set_reported():
    """Mutation control: the retired readings, re-run on the same rows — 2 sessions, 220 minutes, the day
    totals' Zone 2 — so the set test above would red on any member that went back to one."""
    from web.site_api_common import strava_read_seam

    for wire in WIRES:
        row = strava_read_seam("strava", [strava_row(wire)])[0]
        assert len(row["activities"]) == row["activity_count"] == 2  # len(activities) / the day's activity_count
        assert row["total_moving_time_seconds"] / 60.0 == 220.0  # the day's moving time
        assert sum(a["moving_time_seconds"] for a in row["activities"]) / 60.0 == 220.0
        assert session_count.count(strava=[row], hevy=[hevy_row()])["sessions"] == 1


# ── the helper itself ─────────────────────────────────────────────────────────────────────────────────


def test_the_count_is_one_visit_of_three_parts_with_or_without_hevy():
    for wire in WIRES:
        with_hevy = session_count.count(strava=[strava_row(wire)], hevy=[hevy_row()])
        assert (with_hevy["sessions"], with_hevy["parts"], with_hevy["minutes"]) == (1, 3, VISIT_MIN), wire
        assert with_hevy["by_family"] == {
            "cycling": {"parts": 1, "minutes": 60.0},
            "mobility": {"parts": 1, "minutes": 18.0},
            "strength": {"parts": 1, "minutes": 82.0},
        }, wire
        # Without the Hevy rows, Hevy's push is the lift part and the ride inside it keeps its own minutes.
        alone = session_count.count(strava=[strava_row(wire)])
        assert (alone["sessions"], alone["parts"], alone["minutes"]) == (1, 2, VISIT_MIN), wire
        assert alone["by_family"]["strength"]["minutes"] == VISIT_MIN - 60.0, wire


def test_separate_occasions_stay_separate_and_an_untimed_record_is_its_own_visit():
    walk = gym._act("90000300", "Walk", "Apple Watch Ultra", "22:00:00", 1800)
    untimed = {"strava_id": "90000301", "sport_type": "Run", "moving_time_seconds": 600}
    row = {**strava_row("post"), "activities": [*strava_row("post")["activities"], walk, untimed]}
    out = session_count.count(strava=[row], hevy=[hevy_row()])
    assert out["sessions"] == 3 and out["minutes"] == VISIT_MIN + 30.0 + 10.0


def test_two_hevy_rows_without_ids_stay_two_sessions_and_a_tombstone_is_none():
    a = {k: v for k, v in hevy_row().items() if k not in ("workout_id", "source_workout_id", "workout_uid")}
    a["sk"] = f"DATE#{DAY}"
    b = {**a, "start_time": f"{DAY}T22:00:00+00:00", "end_time": f"{DAY}T23:00:00+00:00"}
    assert session_count.count(hevy=[a, b])["sessions"] == 2
    assert session_count.count(hevy=[a, {**b, "tombstone": True}])["sessions"] == 1


def test_the_visit_rule_can_fail(monkeypatch):
    """Mutation control for the grouping: with the overlap rule off, the Strava-only read counts Hevy's
    push and the ride inside it as two visits again."""
    assert session_count.count(strava=[strava_row("post")])["sessions"] == 1
    monkeypatch.setattr(session_count, "_groups", lambda parts: [[p] for p in parts])
    assert session_count.count(strava=[strava_row("post")])["sessions"] == 2


def test_the_claim_rule_can_fail(monkeypatch):
    """Mutation control for minutes claimed once: with every part counted whole, the Strava-only read
    sums the push's span and the ride inside it — 220 minutes again."""
    assert session_count.count(strava=[strava_row("pre")])["minutes"] == VISIT_MIN
    monkeypatch.setattr(session_count, "uncovered_seconds", lambda start, end, claimed: (end - start).total_seconds())
    assert session_count.count(strava=[strava_row("pre")])["minutes"] == 220.0


def test_zone2_reads_the_one_computation():
    for wire in WIRES:
        assert session_count.zone2_total([strava_row(wire)], hevy=[hevy_row()]) == the_zone2(wire, with_hevy=True)
        assert session_count.zone2_by_date([strava_row(wire)]) == {DAY: the_zone2(wire, with_hevy=False)}
    assert (
        session_count.zone2_by_date([{"date": DAY, "activities": [{"strava_id": "x", "moving_time_seconds": 60}]}]) == {}
    ), "an unzoned day is absent, never a measured 0"
