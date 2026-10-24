"""tests/test_relapse_early_warning_5121.py — M1: the relapse early-warning detector (#5121, epic #5120).

What this holds:
  * each of the six new cadence signals (weigh-in cadence, food-log gaps, step drop, check-in silence, the 7-day
    weight reversal, sessions below plan) fires on its charter threshold and stays quiet just inside it — every
    threshold READ from the charter's ``early_warning`` block, never typed here (the derivation guard's
    NOT_APPLICABLE row for ``early_warning`` points at this file);
  * a channel with nothing in the lookback is ABSENT (unevaluated), never silent (ADR-104);
  * two or more signals raise ONE flag; one alone never does; a charter with no block cannot raise it at all;
  * the read half (``gather``) over the stored row shapes measured from the live table (2026-10-24, read-only):
    Withings ``weight_lbs`` day rows, MacroFactor ``total_calories_kcal`` day rows, Hevy ``DATE#d#WORKOUT#id``
    sub-rows, Whoop day rows beside their ``#WORKOUT#`` sub-rows, Apple Health ``steps``;
  * the owner-only row, the episode rule, and the response owner's ONE text per episode (``coach_event_triggers``);
  * PRIVACY: the flag partition is read only by the owner channels — no web, email, content, site-generator or
    support-contact module reads it.

The fixtures are the owner's real series around 2026-10-23 (no clock read anywhere: ``as_of`` is fixed, #4848).
"""

# premerge-gate: #5121: os.walk sweep of lambdas/ mcp/ and the site generators — the owner-only early-warning flag partition has exactly the owner-channel readers

from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))

from health import early_warning as ew  # noqa: E402
from training import training_charter as tc  # noqa: E402


@pytest.fixture(autouse=True)
def _public_charter_only(monkeypatch):
    """The bundled PUBLIC charter only: no owner twin from the laptop env, no S3 probe."""
    monkeypatch.delenv(tc.PRIVATE_ENV_VAR, raising=False)
    monkeypatch.setattr(tc, "_from_s3", lambda key: None)
    tc.reset_cache()
    yield
    tc.reset_cache()


def C(path):
    return tc.charter_value("early_warning." + path)


AS_OF = "2026-10-23"
D = date(2026, 10, 23)


def _d(back: int) -> str:
    return (D - timedelta(days=back)).isoformat()


# ── the live series (read-only DynamoDB, 2026-10-24) ────────────────────────────────────
LIVE_WEIGHTS = {
    "2026-10-01": 311.73, "2026-10-02": 311.01, "2026-10-03": 310.97, "2026-10-04": 312.11, "2026-10-05": 311.09,
    "2026-10-06": 308.87, "2026-10-07": 308.31, "2026-10-08": 307.18, "2026-10-09": 306.13, "2026-10-10": 306.52,
    "2026-10-12": 308.29, "2026-10-13": 305.4, "2026-10-14": 305.56, "2026-10-15": 304.46, "2026-10-16": 304.03,
    "2026-10-17": 302.22, "2026-10-18": 302.2, "2026-10-19": 301.77, "2026-10-20": 301.45, "2026-10-21": 299.25,
    "2026-10-22": 299.44, "2026-10-23": 298.42,
}  # fmt: skip
LIVE_KCAL = {
    "2026-10-08": 1235.0,
    "2026-10-09": 1911.0,
    "2026-10-10": 1935.0,
    "2026-10-11": 1512.0,
    "2026-10-12": 1286.0,
    "2026-10-13": 1579.0,
    "2026-10-14": 1311.0,
    "2026-10-15": 873.0,
    "2026-10-16": 1460.0,
    "2026-10-17": 1561.0,
    "2026-10-18": 1198.0,
    "2026-10-19": 1361.0,
    "2026-10-20": 779.0,
    "2026-10-21": 1012.0,
    "2026-10-22": 1573.0,
    "2026-10-23": 1488.0,
}  # fmt: skip  (10-23 is not yet ingested live; one ordinary day stands in so the window is the evaluated day's)
LIVE_STEPS = {
    "2026-09-20": 3463, "2026-09-21": 8740, "2026-09-22": 8933, "2026-09-23": 8563, "2026-09-24": 8457, "2026-09-25": 9961,
    "2026-09-26": 13165, "2026-09-27": 17662, "2026-09-28": 3254, "2026-09-29": 3340, "2026-09-30": 11722, "2026-10-01": 3420,
    "2026-10-02": 3376, "2026-10-03": 24816, "2026-10-04": 10466, "2026-10-05": 9057, "2026-10-06": 3547, "2026-10-07": 8666,
    "2026-10-08": 9922, "2026-10-09": 2743, "2026-10-10": 8509, "2026-10-11": 3335, "2026-10-12": 12512, "2026-10-13": 4067,
    "2026-10-14": 17739, "2026-10-15": 5242, "2026-10-16": 2617, "2026-10-17": 17866, "2026-10-18": 6878, "2026-10-19": 8487,
    "2026-10-20": 18718, "2026-10-21": 4758, "2026-10-22": 11024, "2026-10-23": 2679,
}  # fmt: skip
LIVE_SESSIONS = [
    "2026-10-09",
    "2026-10-11",
    "2026-10-13",
    "2026-10-15",
    "2026-10-16",
    "2026-10-18",
    "2026-10-19",
    "2026-10-21",
    "2026-10-23",
]
LIVE_CHECKINS: list = []  # the evening check-in had no answered row when this landed (first row after #5106's deploy)


def _cadence(**over):
    base = {
        "weights": dict(LIVE_WEIGHTS),
        "food_kcal": dict(LIVE_KCAL),
        "steps": dict(LIVE_STEPS),
        "checkin_days": list(LIVE_CHECKINS),
        "session_days": list(LIVE_SESSIONS),
        "plan_sessions": tc.charter_value("split.lifting_days_per_wk"),
    }
    base.update(over)
    return base


def _s():
    return ew.settings()


def _fired(cadence):
    return ew.cadence_markers(cadence, D, _s())[0]


# ── the charter block ────────────────────────────────────────────────────────────────────


def test_the_thresholds_are_the_charter_block_and_name_their_provenance():
    s = _s()
    assert s["min_signals"] == C("min_signals") and s["lookback_days"] == C("lookback_days")
    assert set(s["signals"]) == set(ew.CADENCE_SIGNALS) and all(s["signals"].values())
    assert "platform default" in C("provenance") and "failure_mode" in C("provenance")
    assert s["complete_log_kcal"] is not None, "the food-log line is the titration rule's complete-log line, read"
    assert s["charter_version"] == tc.charter_version()


def test_a_charter_without_the_block_evaluates_nothing_and_never_raises():
    s = ew.settings(charter_reader=lambda p: None, complete_log_kcal=600)
    assert s["min_signals"] is None
    r = ew.detect([], [], [{"metric": "recovery"}], _cadence(weights={}), AS_OF, s)
    assert r["active"] is False and set(r["unevaluated"]) == set(ew.CADENCE_SIGNALS)


def test_on_the_live_series_no_cadence_signal_fires():
    fired, evidence, unevaluated = ew.cadence_markers(_cadence(), D, _s())
    assert fired == []
    assert unevaluated == ["checkin_silence"], "no answered check-in in the lookback is absent, never silent"
    assert "down" in evidence["weight_reversal"] and "4, 4" in evidence["sessions_below_plan"]


# ── 1. weigh-in cadence ──────────────────────────────────────────────────────────────────


def test_weigh_ins_stopping_for_the_silent_days_fires():
    n = int(C("signals.weigh_in_cadence.silent_days"))
    stopped = {d: w for d, w in LIVE_WEIGHTS.items() if d <= _d(n)}
    assert "weigh_in_cadence" in _fired(_cadence(weights=stopped))
    one_less = {d: w for d, w in LIVE_WEIGHTS.items() if d <= _d(n - 1)}
    assert "weigh_in_cadence" not in _fired(_cadence(weights=one_less))


def test_no_weigh_in_in_the_lookback_is_absent_not_silent():
    _, _, unevaluated = ew.cadence_markers(_cadence(weights={}), D, _s())
    assert "weigh_in_cadence" in unevaluated and "weight_reversal" in unevaluated


# ── 2. food-log gaps ─────────────────────────────────────────────────────────────────────


def test_food_log_gaps_on_enough_of_the_window_fire():
    line = _s()["complete_log_kcal"]
    window, gaps = int(C("signals.food_log_gap.window_days")), int(C("signals.food_log_gap.min_gap_days"))
    assert window >= gaps
    kcal = dict(LIVE_KCAL)
    kcal.pop(_d(0))  # the newest day: no food log at all
    kcal.update({_d(i): line - 1 for i in range(1, gaps)})  # the rest: logged under the complete-log line (dark)
    assert "food_log_gap" in _fired(_cadence(food_kcal=kcal))
    kcal.update({_d(i): line for i in range(1, gaps)})  # at the line is a complete day
    kcal[_d(0)] = line
    assert "food_log_gap" not in _fired(_cadence(food_kcal=kcal))


# ── 3. step drop ─────────────────────────────────────────────────────────────────────────


def test_a_step_drop_against_his_own_baseline_fires_and_thin_data_is_absent():
    recent = int(C("signals.step_drop.recent_days"))
    drop = C("signals.step_drop.min_drop_pct") / 100
    base = [LIVE_STEPS[d] for d in ew._span(D, int(C("signals.step_drop.baseline_days")), end_offset=recent) if d in LIVE_STEPS]
    low = int(sum(base) / len(base) * (1 - drop)) - 1
    steps = dict(LIVE_STEPS)
    steps.update({_d(i): low for i in range(recent)})
    assert "step_drop" in _fired(_cadence(steps=steps))
    thin = {d: v for d, v in steps.items() if d < _d(recent - int(C("signals.step_drop.min_recent_n")) + 1)}
    assert "step_drop" in ew.cadence_markers(_cadence(steps=thin), D, _s())[2]


# ── 4. check-in silence ──────────────────────────────────────────────────────────────────


def test_checkin_silence_fires_only_after_he_had_been_answering():
    n = int(C("signals.checkin_silence.silent_days"))
    assert "checkin_silence" in _fired(_cadence(checkin_days=[_d(n + 2), _d(n + 1), _d(n)]))
    assert "checkin_silence" not in _fired(_cadence(checkin_days=[_d(n), _d(n - 1)]))


# ── 5. the 7-day weight reversal ─────────────────────────────────────────────────────────


def test_a_seven_day_weight_reversal_fires():
    w, rise = int(C("signals.weight_reversal.window_days")), C("signals.weight_reversal.min_rise_lb")
    weights = dict(LIVE_WEIGHTS)
    prior = [weights[d] for d in ew._span(D, w, end_offset=w) if d in weights]
    up = sum(prior) / len(prior) + rise + 0.2
    weights.update({_d(i): up for i in range(w)})
    assert "weight_reversal" in _fired(_cadence(weights=weights))
    weights.update({_d(i): sum(prior) / len(prior) + rise - 0.2 for i in range(w)})
    assert "weight_reversal" not in _fired(_cadence(weights=weights))


# ── 6. sessions below plan ───────────────────────────────────────────────────────────────


def test_sessions_below_plan_need_every_week_under_the_line():
    k, weeks = int(C("signals.sessions_below_plan.min_sessions_per_wk")), int(C("signals.sessions_below_plan.consecutive_weeks"))
    thin = [_d(7 * wk + i) for wk in range(weeks) for i in range(k - 1)]
    assert "sessions_below_plan" in _fired(_cadence(session_days=thin))
    one_good_week = thin + [_d(7 * (weeks - 1) + 6 - i) for i in range(k)]
    assert "sessions_below_plan" not in _fired(_cadence(session_days=one_good_week))


# ── the two-signal rule ──────────────────────────────────────────────────────────────────


def _stopped_weigh_ins():
    return {d: w for d, w in LIVE_WEIGHTS.items() if d <= _d(int(C("signals.weigh_in_cadence.silent_days")))}


def test_one_signal_alone_never_raises_the_flag():
    r = ew.detect([], [], [], _cadence(weights=_stopped_weigh_ins()), AS_OF)
    assert r["markers"] == ["weigh_in_cadence"] and r["active"] is False and ew.summary_block(r) == ""


def test_two_signals_together_raise_one_flag():
    k = int(C("signals.sessions_below_plan.min_sessions_per_wk"))
    r = ew.detect([], [], [], _cadence(weights=_stopped_weigh_ins(), session_days=[_d(1), _d(9)][: k - 1]), AS_OF)
    assert set(r["markers"]) == {"weigh_in_cadence", "sessions_below_plan"} and r["active"] is True
    assert len(r["markers"]) >= C("min_signals")
    assert "No weigh-in for" in ew.summary_block(r)


def test_a_pre_5121_marker_and_a_cadence_signal_count_together():
    r = ew.detect([], [], [{"metric": "recovery"}], _cadence(weights=_stopped_weigh_ins()), AS_OF)
    assert r["markers"] == ["recovery_sliding", "weigh_in_cadence"] and r["active"] is True


# ── the read half over the live row shapes ───────────────────────────────────────────────


def _rows_by_source():
    w = [{"pk": "USER#matthew#SOURCE#withings", "sk": f"DATE#{d}", "date": d, "weight_lbs": v} for d, v in LIVE_WEIGHTS.items()]
    mf = [{"sk": f"DATE#{d}", "date": d, "total_calories_kcal": v, "entries_count": 5} for d, v in LIVE_KCAL.items()]
    hevy = [
        {"sk": f"DATE#{d}#WORKOUT#w{i}", "date": d, "source_workout_id": f"w{i}", "title": "Foundation"}
        for i, d in enumerate(LIVE_SESSIONS)
    ]
    hevy.append({"sk": "DATE#2026-10-22#WORKOUT#gone", "date": "2026-10-22", "source_workout_id": "gone", "tombstone": True})
    whoop = [{"sk": f"DATE#{d}", "date": d, "step_count": v, "recovery_score": 60} for d, v in LIVE_STEPS.items()]
    whoop += [{"sk": f"DATE#{d}#WORKOUT#x", "date": d, "sport_name": "walking"} for d in list(LIVE_STEPS)[-3:]]
    return {"withings": w, "macrofactor": mf, "hevy": hevy, "whoop": whoop, "apple_health": [], "garmin": [], "evening_checkin": []}


def test_gather_reads_the_stored_shapes_and_drops_tombstones_and_workout_subrows():
    rows = _rows_by_source()
    calls = []

    def fetch(source, start, end):
        calls.append((source, start, end))
        return rows.get(source, [])

    cad = ew.gather(fetch, AS_OF, _s())
    assert cad["weights"]["2026-10-23"] == 298.42 and cad["food_kcal"]["2026-10-15"] == 873.0
    assert sorted(cad["session_days"]) == sorted(LIVE_SESSIONS), "a tombstoned workout is not a session"
    assert cad["steps"]["2026-10-23"] == 2679, "a #WORKOUT# sub-row never answers for the day"
    assert cad["checkin_days"] == [] and set(cad["_read"]) == set(ew.CADENCE_SIGNALS)
    assert {c[2] for c in calls} == {AS_OF} and all(c[1] <= _d(int(C("lookback_days")) - 1) for c in calls)


def test_a_failed_family_is_unevaluated_never_zero():
    def fetch(source, start, end):
        if source == "withings":
            raise RuntimeError("throttled")
        return _rows_by_source().get(source, [])

    cad = ew.gather(fetch, AS_OF, _s())
    _, _, unevaluated = ew.cadence_markers(cad, D, _s())
    assert {"weigh_in_cadence", "weight_reversal"} <= set(unevaluated)


# ── the owner-only row + the episode ─────────────────────────────────────────────────────


class _Table:
    def __init__(self, items=None):
        self.items = items or []
        self.puts = []
        self.queries = []

    def put_item(self, Item):
        self.puts.append(Item)

    def query(self, **kw):
        self.queries.append(kw)
        pk = kw["ExpressionAttributeValues"][":pk"]
        return {"Items": [i for i in self.items if i.get("pk") == pk]}


def test_the_row_is_owner_only_and_carries_nothing_dynamodb_rejects():
    r = ew.detect([], [], [{"metric": "recovery"}], _cadence(weights=_stopped_weigh_ins()), AS_OF)
    t = _Table()
    assert ew.store(t, AS_OF, r)
    row = t.puts[0]
    assert row["pk"] == "USER#matthew#SOURCE#early_warning_flag" and row["sk"] == f"DATE#{AS_OF}"
    assert row["tier"] == "owner_only" and row["active"] is True and row["charter_version"] == tc.charter_version()

    def no_float(v):
        if isinstance(v, dict):
            return all(no_float(x) for x in v.values())
        if isinstance(v, list):
            return all(no_float(x) for x in v)
        return not isinstance(v, float)

    assert no_float(row)


def _flag(d, active, markers=("weigh_in_cadence", "step_drop")):
    return {"pk": "USER#matthew#SOURCE#early_warning_flag", "sk": f"DATE#{d}", "date": d, "active": active,
            "markers": list(markers) if active else [], "evidence": {m: f"{m} line" for m in markers}}  # fmt: skip


def test_an_episode_starts_at_its_first_active_day_and_a_missing_day_does_not_end_it():
    rows = [_flag("2026-10-18", False), _flag("2026-10-19", True), _flag("2026-10-21", True), _flag("2026-10-22", True)]
    assert ew.episode(rows) == {"start": "2026-10-19", "latest": "2026-10-22", "row": rows[-1]}
    assert ew.episode(rows + [_flag("2026-10-23", False)]) is None


def test_the_mind_thread_lines_state_the_flag_a_clear_read_or_an_absence():
    active = ew.owner_lines([_flag("2026-10-21", True), _flag("2026-10-22", True)], "2026-10-24")
    assert active[0].startswith("Early-warning flag (owner-only): ACTIVE since 2026-10-21") and "- step_drop line" in active
    assert "clear as of 2026-10-22" in ew.owner_lines([_flag("2026-10-22", False)], "2026-10-24")[0]
    assert "absent" in ew.owner_lines([_flag("2026-10-10", True)], "2026-10-24")[0]


def test_run_never_raises_and_stores_the_day(monkeypatch):
    t = _Table()
    assert ew.run(t, lambda *a: (_ for _ in ()).throw(RuntimeError("down")), AS_OF, [], [], []) == (False, [])
    assert t.puts and t.puts[0]["active"] is False and set(t.puts[0]["unevaluated"]) == set(ew.CADENCE_SIGNALS)


# ── the response owner's one text per episode (coach_event_triggers) ─────────────────────


def test_the_response_owner_texts_once_per_episode_on_concern_provenance():
    from coach import coach_event_triggers as cet, coach_outbound

    rows = [_flag("2026-10-21", True), _flag("2026-10-22", True)]
    ev = cet.detect_early_warning({"rows": rows, "owner": "mind_coach"}, "2026-10-24")
    assert ev["persona_id"] == "mind_coach" and ev["event_id"] == "early_warning#2026-10-21"
    assert ev["provenance"] == coach_outbound.PROVENANCE_CONCERN and "weigh_in_cadence line" in ev["evidence"]
    later = cet.detect_early_warning({"rows": rows + [_flag("2026-10-23", True)], "owner": "mind_coach"}, "2026-10-24")
    assert later["event_id"] == ev["event_id"], "a flag that stays up re-derives the id it already spent"


def test_no_owner_a_stale_flag_or_a_clear_day_sends_nothing():
    from coach import coach_event_triggers as cet

    rows = [_flag("2026-10-21", True), _flag("2026-10-22", True)]
    assert cet.detect_early_warning({"rows": rows, "owner": None}, "2026-10-24") is None
    assert cet.detect_early_warning({"rows": rows, "owner": "mind_coach"}, "2026-10-30") is None
    assert cet.detect_early_warning({"rows": rows + [_flag("2026-10-23", False)], "owner": "mind_coach"}, "2026-10-24") is None


def test_the_owner_is_the_failure_mode_response_owner_in_config():
    import json

    from coach import persona_registry

    goals = json.load(open(ROOT / "config" / "user_goals.json", encoding="utf-8"))
    owner = goals["failure_mode"]["response_owner"]
    assert owner in persona_registry.OPERATIONAL_COACH_IDS


def test_the_sweep_sends_the_flag_to_the_owners_seat(monkeypatch):
    from datetime import datetime

    from coach import coach_event_triggers as cet, coach_outbound

    monkeypatch.setattr(coach_outbound, "claim_event", lambda table, eid, **k: True)
    monkeypatch.setattr(coach_outbound, "claim_outbound", lambda *a, **k: True)
    sent = []
    out = cet.run_sweep(
        now_pt=datetime(2026, 10, 24, 10, 0),
        table=_Table(),
        seat=lambda pid: ("tok", 42) if pid == "mind_coach" else (None, None),
        speak=lambda ev, tok, chat: sent.append((ev["persona_id"], chat, ev["event_id"])) or {"ok": True},
        chat_rows=lambda pid: [],
        tier=0,
        signals={"early_warning": {"rows": [_flag("2026-10-22", True)], "owner": "mind_coach"}},
    )
    assert sent == [("mind_coach", 42, "early_warning#2026-10-22")] and out["candidates"] == 1


# ── PRIVACY: the partition has exactly the owner-channel readers ─────────────────────────

# The modules that may name the partition or import the detector: the detector itself, its one writer, the two
# owner channels (the response owner's Telegram ping and the mind coach's own thread) and the registries.
ALLOWED = {
    "lambdas/health/early_warning.py",
    "lambdas/compute/daily_insight_compute_lambda.py",
    "lambdas/coach/coach_event_triggers.py",
    "lambdas/coach/coach_domain_facts.py",
    "lambdas/privacy/field_tiers.py",
    "lambdas/experiment/phase_taxonomy.py",
}
_TOKENS = ("early_warning_flag", "from health import early_warning", "health.early_warning", "from health.early_warning")


def _sweep():
    hits = set()
    roots = [ROOT / "lambdas", ROOT / "mcp", ROOT / "site", ROOT / "scripts"]
    for root in roots:
        for dirpath, _dirs, files in os.walk(root):
            if "__pycache__" in dirpath or "node_modules" in dirpath:
                continue
            for f in files:
                if not f.endswith((".py", ".js", ".html", ".mjs")):
                    continue
                p = Path(dirpath) / f
                rel = str(p.relative_to(ROOT))
                if rel.startswith("scripts/") and not f.startswith("v4_build_"):
                    continue  # the site generators are the scripts that publish
                try:
                    text = p.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                if any(tok in text for tok in _TOKENS):
                    hits.add(rel)
    return hits


def test_only_the_owner_channels_read_the_flag():
    hits = _sweep()
    assert hits == ALLOWED, f"unexpected readers: {sorted(hits - ALLOWED)}; missing: {sorted(ALLOWED - hits)}"
    for rel in hits:
        assert not rel.startswith(("lambdas/web/", "lambdas/emails/", "lambdas/content/", "site/", "scripts/"))
    assert "lambdas/coach/named_human_contact.py" not in hits, "the support contact is never told (R2 pending, owner-only)"


def test_the_sweep_sees_a_planted_public_reader(tmp_path, monkeypatch):
    """The guard can fail: a web module that imports the detector is a hit."""
    fake = tmp_path / "lambdas" / "web"
    fake.mkdir(parents=True)
    (fake / "site_api_relapse.py").write_text("from health import early_warning\n", encoding="utf-8")
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    assert _sweep() == {"lambdas/web/site_api_relapse.py"}


def test_the_partition_is_registered_owner_only_and_experiment_scoped():
    from experiment.phase_taxonomy import SOURCE_CLASS
    from privacy.field_tiers import SOURCE_TIERS, TIER_OWNER_ONLY

    assert SOURCE_TIERS[ew.SOURCE] == TIER_OWNER_ONLY and SOURCE_CLASS[ew.SOURCE] == "experiment_scoped"
