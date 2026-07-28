"""tests/test_process_milestones_1628.py — window-validated process milestones (#1628).

The acceptance criteria, mapped to tests:

  * pure window functions, window/threshold/n explicit  → test_definitions_registry_is_explicit,
    (no day-triggered variants)                            test_return_after_gap_is_a_window_function_not_a_day_trigger
  * return_after_gap fires within 7 days, not after     → test_return_after_gap_fires_within_seven_days_not_after
  * sustained_sessions = non-decline, peak must not fire → test_sustained_sessions_peak_then_decline_does_not_fire
  * strength_in_deficit needs BOTH signals (ADR-104)    → test_strength_in_deficit_requires_both_signals_present
  * weight structurally never emits alone               → test_weight_only_fixture_produces_no_emission,
                                                          test_weight_emits_only_as_companion_of_process_milestone,
                                                          test_weight_is_not_companion_to_streak
  * writes through MILESTONE# + spiral circuit breaker  → test_process_milestones_write_through_ledger_write_once,
                                                          test_spiral_breaker_suppression_defers_not_consumes
  * uncertainty + n on every emission (ADR-105)         → test_every_emission_carries_window_n_and_uncertainty
"""

import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from health import (
    milestone_ledger as ml,  # noqa: E402
    process_milestones as pm,  # noqa: E402
)

USER_PREFIX = "USER#matthew#SOURCE#"
LEDGER_PK = USER_PREFIX + "milestones"


# ── Fixture helpers ───────────────────────────────────────────────────────────


class FakeTable:
    """Minimal DDB Table double (same shape as the #1626 test double)."""

    def __init__(self):
        self.items: dict[tuple[str, str], dict] = {}

    def put_item(self, Item, ConditionExpression=None):  # noqa: N803 — boto3 kwarg casing
        key = (Item["pk"], Item["sk"])
        if ConditionExpression and "attribute_not_exists(sk)" in ConditionExpression and key in self.items:
            raise RuntimeError("ConditionalCheckFailedException")
        self.items[key] = dict(Item)

    def query(self, **kw):
        vals = kw.get("ExpressionAttributeValues", {})
        pk = vals[":pk"]
        cond = kw["KeyConditionExpression"]
        out = [dict(v) for (k_pk, k_sk), v in self.items.items() if k_pk == pk and _sk_matches(cond, k_sk, vals)]
        out.sort(key=lambda i: i["sk"])
        return {"Items": out}


def _sk_matches(cond: str, sk: str, vals: dict) -> bool:
    if "begins_with" in cond:
        return sk.startswith(vals[":sk"])
    if "BETWEEN" in cond:
        return vals[":s"] <= sk <= vals[":e"]
    return True


def _weight_day(d: str, lbs: float) -> dict:
    return {"pk": USER_PREFIX + "withings", "sk": f"DATE#{d}", "weight_lbs": lbs}


def _strava_day(d: str) -> dict:
    return {"pk": USER_PREFIX + "strava", "sk": f"DATE#{d}"}


def _habit_day(d: str, streak: int) -> dict:
    return {"pk": USER_PREFIX + "habit_scores", "sk": f"DATE#{d}", "t0_perfect_streak": streak}


def _sweep(table, today, **kw):
    kw.setdefault("suppressed", False)
    return ml.sweep(table, USER_PREFIX, None, today, **kw)


def _ledger_items(table) -> dict[str, dict]:
    return {sk: dict(v) for (pk, sk), v in table.items.items() if pk == LEDGER_PK}


def _iso(d: date) -> str:
    return d.isoformat()


def _span(start: str, n: int, step: int = 1) -> list[str]:
    d0 = date.fromisoformat(start)
    return [_iso(d0 + timedelta(days=i * step)) for i in range(n)]


def _training_from_weekly(counts: list[int], today: str) -> list[str]:
    """Training dates realizing weekly session counts (index 0 = oldest week) in
    fixed 7-day buckets counting back from `today`."""
    t = date.fromisoformat(today)
    weeks = len(counts)
    out = []
    for idx, c in enumerate(counts):
        bucket_end = t - timedelta(days=7 * (weeks - 1 - idx))
        out.extend(_iso(bucket_end - timedelta(days=j)) for j in range(c))
    return out


# ── AC: return_after_gap fires within 7 days of a missed week, not after ─────


def test_return_after_gap_fires_within_seven_days_not_after():
    """Synthetic history: regular training, then a missed week, then a return on
    day d (1..10) after the missed week completes. Fires for d <= 7, never after."""
    prev = date.fromisoformat("2026-04-01")
    history = [_iso(prev - timedelta(days=k)) for k in (0, 3, 6, 9)]  # regular training up to `prev`
    for d in range(1, 11):
        ret = prev + timedelta(days=pm.RETURN_MISSED_WEEK_DAYS + d)
        result = pm.return_after_gap(history + [_iso(ret)], _iso(ret))
        if d <= 7:
            assert result is not None, f"return on day {d} after the missed week must fire"
            milestone, meas = result
            assert milestone.id == f"return_after_gap_{_iso(ret)}"
            assert meas["returned_on_day"] == d
            assert meas["missed_days"] == pm.RETURN_MISSED_WEEK_DAYS + d - 1
        else:
            assert result is None, f"return on day {d} fired — the milestone must NOT fire after day 7"


def test_return_after_gap_needs_a_real_missed_week():
    """A 6-day break is not a missed week — no milestone."""
    days = ["2026-04-01", "2026-04-08"]  # 6 full missed days between sessions
    assert pm.return_after_gap(days, "2026-04-08") is None


def test_return_after_gap_is_a_window_function_not_a_day_trigger():
    """The verdict is a property of the (series, evaluation-date) window: the same
    qualifying return is visible for days afterwards (same identity), and ages out
    of the emit window instead of depending on 'did it happen today'."""
    days = ["2026-02-01", "2026-02-10"]  # 8 missed days -> returned on day 2
    on_the_day = pm.return_after_gap(days, "2026-02-10")
    three_later = pm.return_after_gap(days, "2026-02-13")
    assert on_the_day is not None and three_later is not None
    assert on_the_day[0].id == three_later[0].id == "return_after_gap_2026-02-10"
    # …and beyond the 45-day emit window it is archaeology, not news. (Window
    # widened 14→45 by the 2026-07-26 review: breaker suppression after a spiral
    # regularly outlasts 14 days and was silently losing the restart fact; the
    # entry stays identity-anchored to the true return date, so a late write is
    # still the honest dated record.)
    assert pm.return_after_gap(days, "2026-03-27") is not None  # day 45 — still emittable
    assert pm.return_after_gap(days, "2026-03-28") is None  # day 46 — aged out


# ── AC: sustained_sessions is a non-decline, never a peak ─────────────────────


def test_sustained_sessions_fires_on_non_decline():
    today = "2026-06-01"
    result = pm.sustained_sessions(_training_from_weekly([3] * 8, today), today)
    ids = [m.id for m, _ in result]
    assert "sustained_sessions_8w" in ids
    meas = dict(result)[[m for m, _ in result if m.id == "sustained_sessions_8w"][0]]
    assert meas["weekly_counts"] == [3] * 8
    assert meas["n"] == 24


def test_sustained_sessions_peak_then_decline_does_not_fire():
    """The documented failure mode: five, to three, to one. A peak-then-decline
    series must NOT fire — the milestone is 'has not declined', not 'peaked'."""
    today = "2026-06-01"
    result = pm.sustained_sessions(_training_from_weekly([3, 4, 5, 5, 4, 3, 2, 2], today), today)
    assert result == [], "a peak-then-decline series fired sustained_sessions — the AC forbids exactly this"


def test_sustained_sessions_floor_a_skipped_week_does_not_fire():
    today = "2026-06-01"
    counts = [3, 3, 3, 1, 3, 3, 3, 3]  # one week under the floor
    assert pm.sustained_sessions(_training_from_weekly(counts, today), today) == []


# ── AC: strength_in_deficit requires BOTH signals (never a partial claim) ─────


def _strength_fixture(today="2026-05-01"):
    t = date.fromisoformat(today)
    start = t - timedelta(days=pm.STRENGTH_WINDOW_DAYS - 1)
    volume = {_iso(start + timedelta(days=i)): 5000.0 for i in range(0, pm.STRENGTH_WINDOW_DAYS, 2)}
    calories = {_iso(start + timedelta(days=i)): 2200.0 for i in range(pm.STRENGTH_WINDOW_DAYS)}
    expenditure = {_iso(start + timedelta(days=i)): 2700.0 for i in range(pm.STRENGTH_WINDOW_DAYS)}
    return volume, calories, expenditure


def test_strength_in_deficit_requires_both_signals_present():
    volume, calories, expenditure = _strength_fixture()
    fired = pm.strength_in_deficit(volume, calories, expenditure, "2026-05-01")
    assert fired is not None
    milestone, meas = fired
    assert milestone.category == "composition"
    assert meas["mean_deficit_kcal"] == 500.0 and meas["n_deficit_days"] >= pm.DEFICIT_MIN_DAYS

    # Missing either signal yields NO milestone — never a partial claim (ADR-104).
    assert pm.strength_in_deficit(volume, None, None, "2026-05-01") is None, "strength alone claimed strength-in-deficit"
    assert pm.strength_in_deficit(None, calories, expenditure, "2026-05-01") is None, "deficit alone claimed strength-in-deficit"
    assert pm.strength_in_deficit({}, calories, expenditure, "2026-05-01") is None


def test_strength_in_deficit_thin_or_failed_signals_do_not_fire():
    volume, calories, expenditure = _strength_fixture()
    # Deficit days below the n floor -> no claim.
    thin_cal = dict(list(calories.items())[: pm.DEFICIT_MIN_DAYS - 1])
    assert pm.strength_in_deficit(volume, thin_cal, expenditure, "2026-05-01") is None
    # Not actually in a deficit.
    surplus = {k: 2650.0 for k in calories}
    assert pm.strength_in_deficit(volume, surplus, expenditure, "2026-05-01") is None
    # Strength NOT maintained (second half collapses).
    mid = date.fromisoformat("2026-05-01") - timedelta(days=pm.STRENGTH_WINDOW_DAYS // 2 - 1)
    declined = {k: (v if date.fromisoformat(k) < mid else v * 0.5) for k, v in volume.items()}
    assert pm.strength_in_deficit(declined, calories, expenditure, "2026-05-01") is None


# ── zone2_accumulation / rhr_hrv_trend / waist_change ─────────────────────────


def test_zone2_accumulation_rungs():
    today = "2026-05-01"
    t = date.fromisoformat(today)
    by_day = {_iso(t - timedelta(days=i)): 30.0 for i in range(21)}  # 630 minutes in-window
    ids = [m.id for m, _ in pm.zone2_accumulation(by_day, today)]
    assert ids == ["zone2_4w_300", "zone2_4w_600"]
    assert pm.zone2_accumulation({_iso(t): 100.0}, today) == []


def test_rhr_hrv_trend_requires_both_metrics_beyond_noise():
    today = "2026-05-01"
    t = date.fromisoformat(today)
    rhr, hrv = {}, {}
    for i in range(pm.TREND_WINDOW_DAYS):  # recent block
        d = _iso(t - timedelta(days=i))
        rhr[d] = 55.0 + (i % 2)  # mean ~55.5
        hrv[d] = 47.0 + (i % 2) * 2  # mean ~48
    for i in range(pm.TREND_WINDOW_DAYS, 2 * pm.TREND_WINDOW_DAYS):  # previous block
        d = _iso(t - timedelta(days=i))
        rhr[d] = 60.0 + (i % 2)
        hrv[d] = 39.0 + (i % 2) * 2
    fired = pm.rhr_hrv_trend(rhr, hrv, today)
    assert fired is not None
    _, meas = fired
    assert meas["rhr"]["delta"] < 0 and meas["hrv"]["delta"] > 0
    assert meas["n"] >= pm.TREND_MIN_N

    # Only one metric improving is NOT the milestone.
    flat_hrv = {k: 40.0 + (i % 2) for i, k in enumerate(sorted(hrv))}
    assert pm.rhr_hrv_trend(rhr, flat_hrv, today) is None
    # Thin blocks make no claim (ADR-105).
    thin = {k: v for k, v in list(sorted(rhr.items()))[:15]}
    assert pm.rhr_hrv_trend(thin, hrv, today) is None


def test_waist_change_needs_a_real_window_not_one_tape_reading():
    today = "2026-05-01"
    t = date.fromisoformat(today)
    one = {_iso(t): 39.0}
    assert pm.waist_change(one, today) == [], "a single tape reading fired a waist rung"
    three = {_iso(t - timedelta(days=k)): v for k, v in zip((0, 3, 6), (40.5, 41.0, 41.5))}
    fired = pm.waist_change(three, today)
    ids = [m.id for m, _ in fired]
    assert "waist_sub_42" in ids and "waist_sub_44" in ids
    deepest = max(fired, key=lambda mm: mm[0].depth)
    assert deepest[0].id == "waist_sub_42"
    assert dict(fired)[deepest[0]]["n"] == 3


# ── AC: every emission carries window, n, and uncertainty (ADR-105) ──────────


def test_every_emission_carries_window_n_and_uncertainty():
    today = "2026-05-01"
    t = date.fromisoformat(today)
    volume, calories, expenditure = _strength_fixture(today)
    rhr = {_iso(t - timedelta(days=i)): (55.0 if i < 30 else 61.0) + (i % 2) for i in range(60)}
    hrv = {_iso(t - timedelta(days=i)): (48.0 if i < 30 else 40.0) + (i % 2) for i in range(60)}
    signals = {
        "training_dates": _training_from_weekly([3] * 8, today) + ["2026-01-01"],
        "strength_volume_by_day": volume,
        "calories_by_day": calories,
        "expenditure_by_day": expenditure,
        "zone2_minutes_by_day": {_iso(t - timedelta(days=i)): 30.0 for i in range(21)},
        "rhr_by_day": rhr,
        "hrv_by_day": hrv,
        "waist_by_day": {_iso(t - timedelta(days=k)): v for k, v in zip((0, 3, 6), (40.5, 41.0, 41.5))},
    }
    cands = pm.candidates(signals, today)
    ladders = {m.ladder for m, _ in cands}
    assert {"sustained_sessions", "strength_in_deficit", "zone2", "rhr_hrv_trend", "waist"} <= ladders
    for milestone, meas in cands:
        assert "window_days" in meas, f"{milestone.id} emission missing its window"
        assert "n" in meas, f"{milestone.id} emission missing its n (ADR-105)"
        assert "uncertainty" in meas, f"{milestone.id} emission missing its uncertainty (ADR-105)"


def test_definitions_registry_is_explicit():
    """Each milestone is defined with window length, threshold, and n explicit —
    the AC's 'no day-triggered variants' introspection surface."""
    assert set(pm.DEFINITIONS) == {"return_after_gap", "sustained_sessions", "strength_in_deficit", "zone2", "rhr_hrv_trend", "waist"}
    for ladder, defn in pm.DEFINITIONS.items():
        assert defn.get("window_days"), f"{ladder} definition missing an explicit window length"
        assert defn.get("threshold") is not None, f"{ladder} definition missing an explicit threshold"
        assert defn.get("min_n") is not None, f"{ladder} definition missing an explicit n"
        assert defn.get("category") in ("process", "composition")
    # Every ladder is ranked, and weight ranks last (demoted, #1628).
    for ladder in pm.DEFINITIONS:
        assert ladder in ml.LADDER_PRIORITY
    assert ml.LADDER_PRIORITY[0] == "return_after_gap", "the restart is THE highest-value milestone"
    assert ml.LADDER_PRIORITY[-1] == "weight"


# ── AC: weight structurally never emits alone ─────────────────────────────────


def test_weight_only_fixture_produces_no_emission():
    """The AC verbatim: a weight-only fixture produces NO emission — the rung is
    deferred (unconsumed), and no MILESTONE# weight item reaches the ledger."""
    table = FakeTable()
    _sweep(table, "2026-05-01")  # genesis: empty
    for d in ("2026-05-02", "2026-05-03", "2026-05-04"):
        table.put_item(Item=_weight_day(d, 245.0))
        r = _sweep(table, d)
        assert r["announced"] == [] and r["written"] == [], "a weight milestone emitted with no companion"
    assert "weight_sub_250" in r["deferred"], "the satisfied weight rung must stay deferred, not vanish"
    assert not any(sk.startswith("MILESTONE#weight_") for sk in _ledger_items(table)), "a weight item reached the ledger alone"


def test_weight_emits_only_as_companion_of_process_milestone():
    table = FakeTable()
    table.put_item(Item=_strava_day("2026-04-22"))
    table.put_item(Item=_strava_day("2026-04-25"))
    _sweep(table, "2026-05-01")  # genesis
    for d in ("2026-05-02", "2026-05-03", "2026-05-04"):
        table.put_item(Item=_weight_day(d, 245.0))
        _sweep(table, d)
    # The return: 9 missed days after 04-25, back on 05-05 (day 3 of the window).
    table.put_item(Item=_strava_day("2026-05-05"))
    r = _sweep(table, "2026-05-05")
    ids = [e["milestone_id"] for e in r["announced"]]
    assert ids == ["return_after_gap_2026-05-05", "weight_sub_250"]
    items = _ledger_items(table)
    weight = items["MILESTONE#weight_sub_250"]
    assert weight["companion_to"] == "return_after_gap_2026-05-05"
    assert weight["announce"] is True
    # The rest of the crossed weight ladder is consumed by the companion, silently.
    assert items["MILESTONE#weight_sub_260"]["subsumed_by"] == "weight_sub_250"
    # The process event carries its window, n, and uncertainty (ADR-105).
    meas = items["MILESTONE#return_after_gap_2026-05-05"]["measurement"]
    assert meas["window_days"] == pm.RETURN_LOOKBACK_DAYS and "n" in meas and "uncertainty" in meas


def test_weight_is_not_companion_to_streak():
    """Streak/days/level milestones do not give a weight number meaning — only
    process/composition companions qualify (the issue's ranking rule)."""
    table = FakeTable()
    for i, d in enumerate(_span("2026-04-26", 5)):
        table.put_item(Item=_habit_day(d, i + 1))
    _sweep(table, "2026-04-30")  # genesis: streak 5, nothing consumed above streak floor
    for d, streak in zip(_span("2026-05-01", 3), (6, 7, 8)):
        table.put_item(Item=_habit_day(d, streak))
        table.put_item(Item=_weight_day(d, 245.0))
        r = _sweep(table, d)
    # streak_7 announced alone; weight stays deferred with no ledger item.
    announced = [sk for sk, v in _ledger_items(table).items() if v.get("announce")]
    assert announced == ["MILESTONE#streak_7"]
    assert not any(sk.startswith("MILESTONE#weight_") for sk in _ledger_items(table))
    assert "weight_sub_250" in r["deferred"]


# ── AC: writes through MILESTONE#, subject to the spiral circuit breaker ──────


def test_spiral_breaker_suppression_defers_not_consumes():
    table = FakeTable()
    table.put_item(Item=_strava_day("2026-04-25"))
    _sweep(table, "2026-05-01")  # genesis
    table.put_item(Item=_strava_day("2026-05-05"))

    r = _sweep(table, "2026-05-05", suppressed=True)
    assert r["suppressed"] is True and r["written"] == [] and r["announced"] == []
    assert r["deferred"] == ["return_after_gap_2026-05-05"], "suppression must defer, not consume"

    # Breaker clear on a later evaluation, condition still true -> it announces.
    r = _sweep(table, "2026-05-06", suppressed=False)
    assert [e["milestone_id"] for e in r["announced"]] == ["return_after_gap_2026-05-05"]


def test_default_sweep_consults_the_breaker_and_fails_closed():
    """With no injected verdict, sweep asks the spiral breaker; on a bare fixture
    (no signal families) the breaker is not explicitly clear -> defer."""
    table = FakeTable()
    table.put_item(Item=_strava_day("2026-04-25"))
    _sweep(table, "2026-05-01")
    table.put_item(Item=_strava_day("2026-05-05"))
    r = ml.sweep(table, USER_PREFIX, None, "2026-05-05")  # suppressed=None -> live gate
    assert r["suppressed"] is True and r["announced"] == []


def test_breaker_registry_marks_milestones_wired():
    from coach import spiral_breaker

    spec = spiral_breaker.CELEBRATORY_EMITTERS["milestone_announcements"]
    assert spec["wired"] is True and spec["path"] == "lambdas/health/milestone_ledger.py"


def test_process_milestones_write_through_ledger_write_once():
    """Process milestones are MILESTONE# ledger events: write-once, idempotent,
    visible on the announced-events consumer surface."""
    table = FakeTable()
    table.put_item(Item=_strava_day("2026-04-25"))
    _sweep(table, "2026-05-01")
    table.put_item(Item=_strava_day("2026-05-05"))
    r = _sweep(table, "2026-05-05")
    assert [e["milestone_id"] for e in r["announced"]] == ["return_after_gap_2026-05-05"]
    assert "MILESTONE#return_after_gap_2026-05-05" in _ledger_items(table)

    before = {k: dict(v) for k, v in table.items.items()}
    for _ in range(5):
        r = _sweep(table, "2026-05-05")
        assert r["written"] == [] and r["announced"] == []
    assert table.items == before, "re-evaluation mutated the ledger"
    assert [e["milestone_id"] for e in ml.read_announced_events(table, USER_PREFIX)] == ["return_after_gap_2026-05-05"]


def test_return_beats_every_other_ladder_on_the_same_run():
    """LADDER_PRIORITY: the restart is the champion when several ladders trip at once."""
    table = FakeTable()
    t = date.fromisoformat("2026-05-05")
    table.put_item(Item=_strava_day("2026-04-25"))
    _sweep(table, "2026-05-01")
    table.put_item(Item=_strava_day("2026-05-05"))
    for i in range(21):  # 630 Zone 2 minutes in the 4-week window
        table.put_item(Item={"pk": USER_PREFIX + "garmin", "sk": f"DATE#{_iso(t - timedelta(days=i))}", "zone2_minutes": 30})
    r = _sweep(table, "2026-05-05")
    assert [e["milestone_id"] for e in r["announced"]] == ["return_after_gap_2026-05-05"]
    assert set(r["deferred"]) == {"zone2_4w_300", "zone2_4w_600"}, "the other satisfied ladder must defer, not vanish"


def test_genesis_consumes_already_true_window_milestones_without_announcing():
    """A qualifying return already in the window at ledger genesis is baseline —
    consumed silently (announce=False, event_date=None), never announced as news
    (ADR-104: no manufactured history)."""
    table = FakeTable()
    table.put_item(Item=_strava_day("2026-04-20"))
    table.put_item(Item=_strava_day("2026-04-30"))  # 9 missed days -> returned on day 3
    r = _sweep(table, "2026-05-01")
    assert r["genesis"] is True and r["announced"] == []
    rec = _ledger_items(table)["MILESTONE#return_after_gap_2026-04-30"]
    assert rec["announce"] is False and rec["origin"] == "baseline" and rec["event_date"] is None
    # …and it never announces later.
    r = _sweep(table, "2026-05-02")
    assert r["announced"] == []


# ── 2026-07-26 review-fix regressions ─────────────────────────────────────────


def test_windows_genesis_guard_baselines_without_announcing():
    """Review P2 (the deploy-sequencing trap): a ledger whose rung genesis was
    written by #1626-era code has never baselined the window family — the first
    sweep with window rules must CONSUME already-true window candidates as
    origin=baseline (announce=False), never announce them as fresh crossings."""
    table = FakeTable()
    # A #1626-era genesis exists, but no window marker and no window events.
    table.put_item(Item={"pk": LEDGER_PK, "sk": ml.GENESIS_SK, "genesis_date": "2026-07-25", "recorded_at": "2026-07-25"})

    # Signals with a currently-satisfied return_after_gap: train through 06-07,
    # miss exactly a week (06-08..06-14), return 06-15, today 06-17.
    training = [f"2026-06-0{d}" for d in range(1, 8)] + ["2026-06-15"]
    signals = {
        "weight_series": [],
        "tier0_streak": 0,
        "days_tracked": 0,
        "character_level": None,
        "training_dates": training,
        "strength_volume_by_day": {},
        "zone2_minutes_by_day": {},
        "rhr_by_day": {},
        "hrv_by_day": {},
        "calories_by_day": {},
        "expenditure_by_day": {},
        "waist_by_day": {},
    }
    out = ml.sweep(table, USER_PREFIX, None, "2026-06-17", signals=signals, suppressed=False)

    assert out["announced"] == []  # nothing manufactured as news
    baselined = [e for e in out["written"] if e.get("origin") == ml.ORIGIN_BASELINE]
    assert any("return_after_gap" in str(e.get("milestone_id", "")) for e in baselined)
    # The marker is stamped so the guard never re-runs.
    assert (LEDGER_PK, ml.WINDOWS_GENESIS_SK) in table.items

    # A LATER real crossing announces normally: new gap + return well after.
    training2 = training + ["2026-07-01", "2026-07-02", "2026-07-03", "2026-07-04", "2026-07-05", "2026-07-06", "2026-07-07", "2026-07-15"]
    signals2 = dict(signals, training_dates=training2)
    out2 = ml.sweep(table, USER_PREFIX, None, "2026-07-16", signals=signals2, suppressed=False)
    assert any("return_after_gap" in str(e.get("milestone_id", "")) for e in out2["announced"])


def test_zone2_takes_per_day_max_of_garmin_and_strava_not_sum():
    """Review P2: garmin activities auto-sync to Strava — summing the two sources
    double-counts the same workout. Per-day max keeps the better-covered source."""
    table = FakeTable()
    # Same day, both sources report the same 40-minute ride.
    table.put_item(Item={"pk": "USER#matthew#SOURCE#garmin", "sk": "DATE#2026-07-20", "zone2_minutes": 40})
    table.put_item(Item={"pk": "USER#matthew#SOURCE#strava", "sk": "DATE#2026-07-20", "total_zone2_seconds": 2400})
    # A garmin-only day and a strava-only day survive untouched.
    table.put_item(Item={"pk": "USER#matthew#SOURCE#garmin", "sk": "DATE#2026-07-21", "zone2_minutes": 25})
    table.put_item(Item={"pk": "USER#matthew#SOURCE#strava", "sk": "DATE#2026-07-22", "total_zone2_seconds": 1800})

    signals = ml.collect_signals(table, "USER#matthew#SOURCE#", None, "2026-07-23")
    z2 = signals["zone2_minutes_by_day"]
    assert z2["2026-07-20"] == 40.0  # max, not 80
    assert z2["2026-07-21"] == 25.0
    assert z2["2026-07-22"] == 30.0


# ── #1808: strength_in_deficit's Mifflin fallback (2026-07-26 deep-quality review) ──


def test_mifflin_tdee_estimate_is_a_positive_reasonable_number():
    """Sanity: the fallback formula returns something in a plausible daily-kcal
    range for an adult body weight, and refuses non-positive/unparsable weight."""
    est = pm.mifflin_tdee_estimate(200.0)
    assert est is not None and 1500 < est < 4000
    assert pm.mifflin_tdee_estimate(0) is None
    assert pm.mifflin_tdee_estimate(None) is None
    assert pm.mifflin_tdee_estimate("not-a-number") is None


def test_strength_in_deficit_discloses_measured_vs_estimated_expenditure_days():
    """#1808: expenditure_source_by_day lets the emission disclose how many
    deficit days were MacroFactor's measured figure vs. the Mifflin-St Jeor
    fallback — never silently blended (ADR-104/105)."""
    volume, calories, expenditure = _strength_fixture()
    today = "2026-05-01"
    t = date.fromisoformat(today)
    start = t - timedelta(days=pm.STRENGTH_WINDOW_DAYS - 1)
    days = [_iso(start + timedelta(days=i)) for i in range(pm.STRENGTH_WINDOW_DAYS)]
    # First half measured, second half estimated (arbitrary split covering both).
    source = {d: ("macrofactor_adaptive" if i < pm.STRENGTH_WINDOW_DAYS // 2 else "estimate_mifflin") for i, d in enumerate(days)}

    fired = pm.strength_in_deficit(volume, calories, expenditure, today, source)
    assert fired is not None
    _, meas = fired
    assert meas["expenditure_measured_days"] + meas["expenditure_estimated_days"] == meas["n_deficit_days"]
    assert meas["expenditure_estimated_days"] > 0 and meas["expenditure_measured_days"] > 0

    # No source map at all -> every day defaults to measured (pre-#1808 assumption,
    # preserved for callers that don't track provenance).
    fired_no_src = pm.strength_in_deficit(volume, calories, expenditure, today)
    _, meas_no_src = fired_no_src
    assert meas_no_src["expenditure_estimated_days"] == 0
    assert meas_no_src["expenditure_measured_days"] == meas_no_src["n_deficit_days"]


def test_strength_in_deficit_fires_using_only_mifflin_estimated_expenditure():
    """#1808's actual reachability claim: with NO measured MacroFactor expenditure
    at all — only intake + a Mifflin estimate — the milestone still fires,
    entirely disclosed as estimated. Before this fix the milestone required
    expenditure_kcal/tdee_kcal directly, which the routine per-meal upload path
    never writes (present on 4 of 124 live MacroFactor days, 2026-07-26 review)."""
    volume, calories, _ = _strength_fixture()
    today = "2026-05-01"
    t = date.fromisoformat(today)
    start = t - timedelta(days=pm.STRENGTH_WINDOW_DAYS - 1)
    days = [_iso(start + timedelta(days=i)) for i in range(pm.STRENGTH_WINDOW_DAYS)]
    # A body weight light enough that the Mifflin estimate clears DEFICIT_MIN_KCAL
    # over MacroFactor's flat 2200 kcal/day intake in the fixture.
    expenditure = {d: pm.mifflin_tdee_estimate(150.0) for d in days}
    source = {d: "estimate_mifflin" for d in days}

    fired = pm.strength_in_deficit(volume, calories, expenditure, today, source)
    assert fired is not None, "the Mifflin fallback should make strength_in_deficit reachable with zero measured expenditure"
    _, meas = fired
    assert meas["expenditure_measured_days"] == 0
    assert meas["expenditure_estimated_days"] == meas["n_deficit_days"] == pm.STRENGTH_WINDOW_DAYS


def test_collect_signals_falls_back_to_mifflin_estimate_when_macrofactor_expenditure_absent():
    """#1808 end-to-end: MacroFactor records carry calories but never
    expenditure_kcal/tdee_kcal (the routine per-meal upload path) — same-day
    Withings weigh-ins let collect_signals fill expenditure_by_day with a
    labeled Mifflin estimate instead of leaving strength_in_deficit unreachable."""
    table = FakeTable()
    today = "2026-05-01"
    t = date.fromisoformat(today)
    start = t - timedelta(days=pm.STRENGTH_WINDOW_DAYS - 1)
    for i in range(pm.STRENGTH_WINDOW_DAYS):
        d = _iso(start + timedelta(days=i))
        table.put_item(Item={"pk": USER_PREFIX + "macrofactor", "sk": f"DATE#{d}", "total_calories_kcal": 2200.0})
        table.put_item(Item=_weight_day(d, 200.0))

    signals = ml.collect_signals(table, USER_PREFIX, None, today)
    assert signals["expenditure_by_day"], "no expenditure signal reached collect_signals output"
    assert len(signals["expenditure_by_day"]) == pm.STRENGTH_WINDOW_DAYS
    assert all(v == "estimate_mifflin" for v in signals["expenditure_source_by_day"].values())

    # A day with a MEASURED figure is never overwritten by the estimate.
    measured_day = _iso(start)
    table.put_item(
        Item={
            "pk": USER_PREFIX + "macrofactor",
            "sk": f"DATE#{measured_day}",
            "total_calories_kcal": 2200.0,
            "expenditure_kcal": 2900.0,
        }
    )
    signals2 = ml.collect_signals(table, USER_PREFIX, None, today)
    assert signals2["expenditure_by_day"][measured_day] == 2900.0
    assert signals2["expenditure_source_by_day"][measured_day] == "macrofactor_adaptive"


# ── #1809: zone2's source_coverage disclosure (2026-07-26 deep-quality review) ──


def test_zone2_accumulation_discloses_source_coverage():
    today = "2026-05-01"
    t = date.fromisoformat(today)
    by_day = {_iso(t - timedelta(days=i)): 30.0 for i in range(21)}  # 630 minutes, all strava
    source = {_iso(t - timedelta(days=i)): "strava" for i in range(21)}
    fired = pm.zone2_accumulation(by_day, today, source)
    assert fired  # rungs 300/600 satisfied, same fixture as test_zone2_accumulation_rungs
    for _, meas in fired:
        assert meas["source_coverage"] == {"garmin_days": 0, "strava_days": 21}

    # No source map -> honest zeros, never a fabricated split.
    fired_no_src = pm.zone2_accumulation(by_day, today)
    for _, meas in fired_no_src:
        assert meas["source_coverage"] == {"garmin_days": 0, "strava_days": 0}


def test_collect_signals_discloses_zone2_source_by_day():
    """#1809: extends test_zone2_takes_per_day_max_of_garmin_and_strava_not_sum —
    collect_signals must also expose WHICH source won the per-day max(), not just
    the merged minutes, so the milestone measurement can disclose real coverage
    instead of implying (currently falsely) that garmin ever contributes."""
    table = FakeTable()
    table.put_item(Item={"pk": "USER#matthew#SOURCE#garmin", "sk": "DATE#2026-07-20", "zone2_minutes": 40})
    table.put_item(Item={"pk": "USER#matthew#SOURCE#strava", "sk": "DATE#2026-07-20", "total_zone2_seconds": 2400})
    table.put_item(Item={"pk": "USER#matthew#SOURCE#garmin", "sk": "DATE#2026-07-21", "zone2_minutes": 25})
    table.put_item(Item={"pk": "USER#matthew#SOURCE#strava", "sk": "DATE#2026-07-22", "total_zone2_seconds": 1800})

    signals = ml.collect_signals(table, "USER#matthew#SOURCE#", None, "2026-07-23")
    src = signals["zone2_source_by_day"]
    assert src["2026-07-20"] == "garmin"  # tied minutes -> garmin wins the >= comparison
    assert src["2026-07-21"] == "garmin"
    assert src["2026-07-22"] == "strava"


# ── #1810: return_after_gap's event_date is the true return date ─────────────


def test_return_after_gap_event_date_is_the_true_return_date_not_the_confirmation_date():
    """#1810: reproduces the finding's exact repro — a return on 2026-08-12
    confirmed on 2026-09-20 (39 days later, inside the 45-day emit window via
    breaker/cooldown suppression) must stamp event_date from the true return
    date, not the write/confirmation date read_announced_events sorts and
    filters by. recorded_at (the write date) is untouched."""
    signals = {"training_dates": ["2026-08-01", "2026-08-12"]}
    result = ml.evaluate(signals, set(), None, "2026-09-20")
    assert len(result["to_write"]) == 1
    entry = result["to_write"][0]
    assert entry["milestone_id"] == "return_after_gap_2026-08-12"
    assert entry["measurement"]["return_date"] == "2026-08-12"
    assert entry["event_date"] == "2026-08-12", "event_date drifted to the confirmation date, not the true return date"
    assert entry["recorded_at"] == "2026-09-20"


def test_return_after_gap_written_through_the_ledger_carries_the_true_event_date():
    """Same claim, through the real write path (ml.sweep -> _entry -> put_item) so
    a regression in the _entry plumbing — not just the pure evaluate() decision —
    would be caught. read_announced_events sorts on this field."""
    table = FakeTable()
    # Genesis first, on a pattern that does NOT satisfy return_after_gap (a single
    # training day — no gap to return from), so the later crossing announces as
    # news rather than being silently consumed as baseline.
    ml.sweep(table, USER_PREFIX, None, "2026-01-02", signals={"training_dates": ["2026-01-01"]}, suppressed=False)

    signals = {"training_dates": ["2026-08-01", "2026-08-12"]}
    r = ml.sweep(table, USER_PREFIX, None, "2026-09-20", signals=signals, suppressed=False)
    assert [e["milestone_id"] for e in r["announced"]] == ["return_after_gap_2026-08-12"]
    rec = _ledger_items(table)["MILESTONE#return_after_gap_2026-08-12"]
    assert rec["event_date"] == "2026-08-12"
    assert rec["recorded_at"] == "2026-09-20"
    announced = ml.read_announced_events(table, USER_PREFIX)
    assert announced[0]["event_date"] == "2026-08-12"
