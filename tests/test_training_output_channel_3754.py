"""tests/test_training_output_channel_3754.py — the deficit tracker's "Training output"
channel reads a measure that is non-zero when training happened (#3754, the 2026-10-04
data-source-sweep extension).

THE DEFECT, STATED AS A NEGATIVE CONTROL

Both deficit-sustainability readers scored channel 5 off the Strava day row's
`total_kilojoules`. Strava populates per-activity `kilojoules` only for power-equipped
activities, and the owner has none: the sweep measured the day-level rollup at > 0 on
**0 of 1,242 stored day rows all-time**. The channel's series was therefore always all-zero,
`first_avg == 0` short-circuited the trend to "stable", and the channel could never read
"degraded" — the composite verdict was calibrated against five channels while one of them
could not fire. Every existing channel test fixtured non-zero kJ, which is exactly why none
of them could see it: the fixture was the wire's SHAPE but not its VALUES.

So the first test here is the control the issue asks for: rows shaped the way the owner's
rows are actually stored (HR-bearing walks and lifts, `kilojoules` 0, Hevy set logs) must
produce a non-zero channel input across a window that contains sessions. It FAILS on the
old input — the same rows' `total_kilojoules` sum to 0 — and the test says so by computing
both, rather than asserting the new path alone.

The input is now `training.training_load.daily_training_load` — the SAME per-day model the
ACWR / TSB surfaces read (#4075) — resolved once in `health.training_output_channel` for
both readers (`mcp/tools_nutrition.tool_get_deficit_sustainability` and the public
`web/site_api_nutrition.deficit_sustainability`), each exercised end-to-end below.
"""

from __future__ import annotations

import inspect
import json
import os
from datetime import datetime, timedelta

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")  # mcp.config reads these at import
os.environ.setdefault("USER_ID", "matthew")

import pytest  # noqa: E402
from health import deficit_disclosures as dd, training_output_channel as toc  # noqa: E402
from pacific_clock import freeze_pacific  # noqa: E402 — #2817: the Pacific clock the MCP module reads
from test_mcp_tools_nutrition_behavior import (  # noqa: E402 — the sibling's bounded DynamoDB double + row builders
    _FROZEN,
    _PT,
    _SUST_DAYS,
    FLAT,
    NOW,
    PT_TODAY,
    SUST_ARGS,
    _FrozenDatetime,
    channel,
    install,
    mf,
    row,
    whoop,
)
from training import training_load as tl  # noqa: E402
from web import site_api_common as sac, site_api_nutrition as nut  # noqa: E402

from mcp import core as mcore, tools_nutrition as tn  # noqa: E402

# ── the owner's rows, as stored ───────────────────────────────────────────────────────
# A walk or a run with a chest strap: HR present, moving time present, NO power meter, so
# `kilojoules` is 0 — the shape the sweep found on every 2026 day row. `sport_type` is the
# writer's field; a non-lifting sport keeps the activity out of the Hevy-echo skip.
HR_ACTIVITY = {"kilojoules": 0, "moving_time_seconds": 3600, "sport_type": "Run", "has_heartrate": True}
#: A Zone-1 walk: HR under the 109.8 bpm ceiling scores 0 load — observed rest, not a gap (#4075).
Z1_WALK = {**HR_ACTIVITY, "sport_type": "Walk", "average_heartrate": 100}


def strava_day(date: str, *avg_hrs: float) -> dict:
    """ONE Strava day row holding one HR-bearing activity per `avg_hrs` entry, with the day
    totals the writer stores beside them (`common.strava_read_seam.day_totals` IS the writer's
    formula — `tests/test_shared_modules.py` pins it equal to `strava_lambda.transform`)."""
    from common.strava_read_seam import day_totals

    acts = [{**HR_ACTIVITY, "average_heartrate": hr} for hr in avg_hrs]
    return row("strava", date, activities=acts, **day_totals(acts))


def hevy_workout(date: str, *, sets: int = 20, reps: int = 8) -> dict:
    """ONE Hevy per-workout row with a set log the way `training.hevy_common` stores it:
    rep sets carry `duration_sec: None` (every one of 327 rep sets 2026-09-03 → 09-23). Its
    workout id and its span are the wire's (#5387: the session count keys and places it by them)."""
    return row(
        "hevy",
        date,
        workout_id=f"hv-{date}",
        start_time=f"{date}T17:00:00+00:00",
        end_time=f"{date}T18:30:00+00:00",
        duration_sec=90 * 60,
        exercises=[{"name": "Squat", "sets": [{"type": "normal", "reps": reps, "weight_kg": 100, "duration_sec": None}] * sets}],
    )


def old_input_kilojoules(strava_rows: list[dict]) -> list[float]:
    """What the channel READ before #3754: the day row's `total_kilojoules`, summed per day."""
    by_day: dict[str, float] = {}
    for s in strava_rows:
        d = s["date"]
        by_day[d] = by_day.get(d, 0.0) + float(s.get("total_kilojoules") or 0)
    return [by_day[d] for d in sorted(by_day)]


def input_is_live(out: dict) -> bool:
    """The control's predicate: a window WITH sessions carries a NON-ZERO channel input."""
    return out["input"]["sessions"] > 0 and sum(out["values"]) > 0


# ── clocks ────────────────────────────────────────────────────────────────────────────
@pytest.fixture(autouse=True)
def _frozen(monkeypatch):
    """Both readers' clocks pinned to the sibling modules' 2026-05-10 17:40Z instant."""
    _FROZEN[0] = NOW
    _PT[0] = PT_TODAY
    monkeypatch.setattr(tn, "datetime", _FrozenDatetime)
    freeze_pacific(monkeypatch, tn, _FrozenDatetime)
    monkeypatch.setattr(tn, "pacific_today", lambda: _PT[0])
    monkeypatch.setattr(mcore, "_PROFILE_CACHE", None, raising=False)
    monkeypatch.setattr(nut, "datetime", _FrozenDatetime)
    monkeypatch.setattr(sac, "datetime", _FrozenDatetime)
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-01-01")
    monkeypatch.setattr(nut, "_get_profile", lambda: {"protein_target_g": 190, "protein_floor_g": 170, "height_inches": 72})
    yield
    mcore._PROFILE_CACHE = None


# ── 1. the negative control ───────────────────────────────────────────────────────────
def test_negative_control_the_owners_real_rows_carry_zero_kilojoules_but_a_nonzero_channel_input():
    """Six training days as the owner's partition holds them: a chest-strap activity a day
    (kJ 0) plus a Hevy set log on three of them. The OLD input sums to 0 across the window;
    the channel's input does not — the exact predicate the issue asks a test to fail on."""
    strava = [strava_day(d, 140) for d in _SUST_DAYS]
    hevy = [hevy_workout(d) for d in _SUST_DAYS[::2]]
    assert all(s["total_kilojoules"] == 0 for s in strava), "the fixture must carry the stored rows' real zero"
    assert sum(old_input_kilojoules(strava)) == 0, "the control's premise: the kJ rollup is 0 across a window with sessions"

    out = toc.series(strava, hevy)
    assert out["input"]["sessions"] == 6 + 3
    assert out["input"]["days_observed"] == 6
    assert out["input"]["days_with_load"] == 6, out
    assert input_is_live(out), f"channel input is ZERO across a window with {out['input']['sessions']} sessions: {out}"
    # The control fires on the old input: same rows, kJ as the measure → not live.
    assert not input_is_live({"values": old_input_kilojoules(strava), "input": out["input"]})


def test_the_channel_input_is_the_training_load_model_and_says_so():
    strava = [strava_day(d, 140) for d in _SUST_DAYS]
    out = toc.series(strava, [hevy_workout(_SUST_DAYS[0])])
    # Point-for-point the SAME per-day load the TSB/ACWR surfaces read (#4075) — not a second model.
    load_by_day, _basis = tl.daily_training_load(strava, [hevy_workout(_SUST_DAYS[0])])
    assert out["by_day"] == {d: round(v, 1) for d, v in load_by_day.items()}
    assert out["input"]["measure"] == "daily_training_load"
    assert out["input"]["model"] == tl.LOAD_MODEL
    assert out["input"]["unit"] == "tss_proxy"
    assert "total_kilojoules" in out["input"]["replaced"]


def test_a_zone1_walk_is_an_observed_rest_day_at_zero_not_a_gap():
    """#4075: a walk under the Zone-1 ceiling is MEASURED rest. It stays in the series at 0
    (so the trend sees it) and counts as observed, not as loaded."""
    strava = [row("strava", _SUST_DAYS[0], activities=[dict(Z1_WALK)]), strava_day(_SUST_DAYS[1], 140)]
    out = toc.series(strava, [])
    assert out["values"][0] == 0 and out["values"][1] > 0
    assert out["input"]["days_observed"] == 2 and out["input"]["days_with_load"] == 1


def test_a_tombstoned_hevy_aggregate_is_not_a_session():
    """#4030: a tombstoned Hevy row is a superseded daily aggregate whose sessions are also
    present as per-workout rows — counting it would double them."""
    live = hevy_workout(_SUST_DAYS[0])
    dead = {**hevy_workout(_SUST_DAYS[0]), "tombstone": True}
    assert toc.series([], [live, dead])["input"]["sessions"] == 1
    assert toc.series([], [live, dead])["values"] == toc.series([], [live])["values"]


def test_sessions_counts_what_the_load_model_scored_not_the_raw_strava_activities():
    """ADR-104: `input.sessions` is the live-proof predicate, so it must be the number the
    model scored, not the raw record count. One Strava day holding Hevy's own echo of a lift
    (`WeightTraining`, skipped because Hevy carries the session) plus the SAME Zone-1 walk
    twice (two devices, one start — `strava_read_seam.dedup_activities` keeps one), and one
    Hevy workout row: four raw records, TWO sessions (the lift once, the walk once). #5387: `total`
    is THE session count (one visit per occasion), the echo Hevy's own push (device `Hevy`) over
    the Hevy session's span."""
    day = _SUST_DAYS[0]
    walk = {**Z1_WALK, "start_date": f"{day}T15:00:00Z", "elapsed_time_seconds": 3600, "device_name": "WHOOP"}
    walk_again = {**walk, "device_name": "Garmin"}  # the second device's copy of the same minutes
    echo = {
        **HR_ACTIVITY,
        "sport_type": "WeightTraining",
        "average_heartrate": 120,
        "start_date": f"{day}T17:00:00Z",
        "elapsed_time_seconds": 5400,
        "device_name": "Hevy",
    }
    strava = [row("strava", day, activities=[echo, walk, walk_again])]
    hevy = [hevy_workout(day)]
    assert sum(len(r["activities"]) for r in strava) + len(hevy) == 4, "the raw count the old field reported"

    out = toc.series(strava, hevy)
    assert out["input"]["sessions"] == 2, out["input"]
    # The model's own ledger of what it scored and what it set aside, carried on its basis.
    _, basis = tl.daily_training_load(strava, hevy)
    assert basis["sessions"] == {"total": 2, "parts": 2, "strava": 1, "hevy": 1, "strava_echoes_skipped": 1, "strava_duplicates_dropped": 1}
    assert out["input"]["sessions"] == basis["sessions"]["total"]
    # And the load itself is the lift's worked-set points alone: the walk is Zone-1 rest at 0,
    # the echo contributes nothing (Hevy carries it), the duplicate walk nothing twice.
    assert out["values"] == [round(tl.hevy_session_load(hevy[0])["points"], 1)]
    # Without a Hevy row that day the lift is NOT an echo — the Strava record is the session.
    _, alone = tl.daily_training_load(strava, [])
    assert alone["sessions"] == {"total": 2, "parts": 2, "strava": 2, "hevy": 0, "strava_echoes_skipped": 0, "strava_duplicates_dropped": 1}


# ── 2. the MCP tool, end to end ───────────────────────────────────────────────────────
def _hr_series_rows(hrs: list[float]) -> list[dict]:
    """Seven MacroFactor days (the tool's floor), six Whoop days, one HR activity a day."""
    rows = [
        mf((datetime.strptime("2026-05-03", "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d"), total_calories_kcal=1800)
        for i in range(7)
    ]
    rows += [whoop(d, hrv=FLAT[i]) for i, d in enumerate(_SUST_DAYS)]
    rows += [strava_day(d, hrs[i]) for i, d in enumerate(_SUST_DAYS)]
    return rows


def test_the_mcp_tool_sees_an_intensity_drop_the_kilojoule_input_could_never_show(monkeypatch):
    """Three days at 150 bpm then three at 120 bpm, every row's kJ 0. Under the old input
    this channel read stable/0 by construction; it now reads declining and degraded."""
    rows = _hr_series_rows([150, 150, 150, 120, 120, 120])
    assert all(r.get("total_kilojoules") == 0 for r in rows if r["pk"].endswith("strava"))
    install(monkeypatch, rows)
    out = tn.tool_get_deficit_sustainability(SUST_ARGS)
    train = channel(out, "Training Output")
    # Hand-derived from the load model's own HR function (one hour at each HR): first third
    # vs last third of a 6-point series = mean(3 x load@150) vs mean(3 x load@120).
    first, last = round(tl.hr_load(1.0, 150), 1), round(tl.hr_load(1.0, 120), 1)
    assert first > last > 0
    assert train["direction"] == "declining"
    assert train["delta_pct"] == round((last - first) / first * 100, 1)
    assert train["delta_pct"] < -dd.CHANNEL_CUTOFFS["training_output"]["decline_pct"]
    assert train["status"] == "degraded"
    assert train["input"]["measure"] == "daily_training_load" and train["input"]["sessions"] == 6
    assert train["avg"] == round((3 * first + 3 * last) / 6, 2)


def test_the_mcp_tool_reads_hevy_for_the_channel_so_a_lifting_only_week_is_not_a_dark_one(monkeypatch):
    """A week of Hevy sessions with no Strava record at all used to be `insufficient_data`
    (the channel read Strava only). The set log is training output."""
    rows = [
        mf((datetime.strptime("2026-05-03", "%Y-%m-%d") + timedelta(days=i)).strftime("%Y-%m-%d"), total_calories_kcal=1800)
        for i in range(7)
    ]
    rows += [whoop(d, hrv=FLAT[i]) for i, d in enumerate(_SUST_DAYS)]
    rows += [hevy_workout(d, sets=20 if i < 3 else 8) for i, d in enumerate(_SUST_DAYS)]  # 160 reps/day, then 64
    install(monkeypatch, rows)
    train = channel(tn.tool_get_deficit_sustainability(SUST_ARGS), "Training Output")
    # 20 x 8 reps x 3 s = 480 s worked -> 480/3600 x 50 = 6.7 pts; 8 x 8 x 3 = 192 s -> 2.7 pts -> -59.7%
    assert train["input"]["sessions"] == 6 and train["input"]["days_with_load"] == 6
    assert train["direction"] == "declining" and train["status"] == "degraded"
    assert train["delta_pct"] == round((2.7 - 6.7) / 6.7 * 100, 1)


# ── 3. the public API, end to end ─────────────────────────────────────────────────────
class _Sources:
    """A bounded stand-in for `site_api_common._query_source` (same contract as the
    sibling site test's `FakeSources`: inclusive window filter, [] for an unknown source)."""

    def __init__(self, **by_source):
        self.data = {k: list(v) for k, v in by_source.items()}
        self.read: set[str] = set()

    def __call__(self, source, start, end, include_pilot=False):
        self.read.add(source)
        return [dict(r) for r in self.data.get(source, []) if start <= r["sk"].replace("DATE#", "") <= end]


def _site_channel(src: _Sources) -> dict:
    resp = nut.deficit_sustainability(_g={"_query_source": src, "_experiment_date": sac._experiment_date})
    assert resp["statusCode"] == 200
    ds = json.loads(resp["body"])["deficit_sustainability"]
    assert ds["available"] is True, ds
    return next(c for c in ds["channels"] if c["name"] == "Training output")


def test_the_public_channel_scores_the_same_training_load_and_reads_hevy():
    """The reader-facing channel: kJ 0 on every row, HR dropping 150 -> 120, a Hevy log on
    the first three days. Must read degraded, with the input named on the wire."""
    wdays = [(datetime(2026, 5, 9) - timedelta(days=5 - i)).strftime("%Y-%m-%d") for i in range(6)]
    days = [(datetime(2026, 5, 9) - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    strava = [strava_day(d, [150, 150, 150, 120, 120, 120][i]) for i, d in enumerate(wdays)]
    src = _Sources(
        macrofactor=[
            {"pk": "USER#matthew#SOURCE#macrofactor", "sk": f"DATE#{d}", "total_calories_kcal": 2000, "expenditure_kcal": 3000}
            for d in days
        ],
        strava=strava,
        hevy=[hevy_workout(d) for d in wdays[:3]],
    )
    train = _site_channel(src)
    assert "hevy" in src.read, "the public reader must read the Hevy partition for this channel"
    assert train["status"] == "degraded" and train["direction"] == "declining"
    assert train["input"]["measure"] == "daily_training_load"
    assert train["input"]["sessions"] == 9 and train["input"]["days_with_load"] == 6
    # First third = three HR-150 days each carrying a Hevy log; last third = three HR-120 days.
    hevy_pts = round(tl.hevy_session_load(hevy_workout(wdays[0]))["points"], 1)
    first = round(tl.hr_load(1.0, 150) + hevy_pts, 1)
    last = round(tl.hr_load(1.0, 120), 1)
    assert train["delta_pct"] == round((last - first) / first * 100, 1)


def test_the_public_channel_input_is_zero_only_when_there_were_no_sessions():
    """The control on the public wire: a window of real rows is never all-zero WITH
    sessions, and `insufficient_data` is what a window WITHOUT any reads as."""
    days = [(datetime(2026, 5, 9) - timedelta(days=6 - i)).strftime("%Y-%m-%d") for i in range(7)]
    macro = [
        {"pk": "USER#matthew#SOURCE#macrofactor", "sk": f"DATE#{d}", "total_calories_kcal": 2000, "expenditure_kcal": 3000} for d in days
    ]
    with_sessions = _site_channel(_Sources(macrofactor=macro, strava=[strava_day(d, 140) for d in days[1:]]))
    assert with_sessions["input"]["sessions"] == 6 and with_sessions["input"]["days_with_load"] == 6
    assert with_sessions["direction"] != "insufficient_data"
    without = _site_channel(_Sources(macrofactor=macro))
    assert without["input"]["sessions"] == 0 and without["direction"] == "insufficient_data"


# ── 4. one input, both readers; the disclosure names it ───────────────────────────────
def test_both_readers_resolve_the_channel_through_the_one_input_and_never_the_kilojoule_rollup():
    for fn in (tn.tool_get_deficit_sustainability, nut.deficit_sustainability):
        src = inspect.getsource(fn)
        assert "training_output_channel.series(" in src, f"{fn.__qualname__} does not read the shared training-output input"
        body = "\n".join(line for line in src.splitlines() if not line.strip().startswith("#"))
        assert "total_kilojoules" not in body, f"{fn.__qualname__} still reads the kJ rollup that is 0 on every stored day row"


def test_the_disclosure_names_the_input_and_what_it_replaced():
    entry = dd.CHANNEL_CUTOFFS["training_output"]
    assert "daily_training_load" in entry["input"] and "total_kilojoules" in entry["input"]
    assert "kilojoule" not in entry["note"].lower(), "the cutoff note still describes the dead kJ measure"
    assert entry["provenance"] == "population-derived"  # the 15% cutoff itself is unchanged, and still labelled
