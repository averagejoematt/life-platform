"""Owner rulings 2026-11-06 on the public variant (PR #5656).

* the computation-order defect: the character compute read the day's habit_scores before daily-metrics wrote them;
* "Missing data must not be represented as a genuine zero score" — an unavailable / insufficient-data state;
* the evening check-in's PRESENCE as an explicitly classified public core habit;
* challenge XP public only when the challenge's origin and evidence sources are public-eligible;
* habit_pct over public-eligible habits only, versioned;
* the backfill's reconstruction of the habit scores the fixed order would have seen.
"""

import copy
import json
import os
import re
import sys
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import backfill_public_variant as B  # noqa: E402
import test_character_public_variant as T  # noqa: E402 — the two-history fixtures
from common import activity_publication as A  # noqa: E402
from health import character_engine, character_public, core_habits, habit_pct_public  # noqa: E402

histories = T.histories  # the module-scoped fixture
CONFIG = T.CONFIG


def _ready_hs(day, **fields):
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    base = {"scoring_method": "core_set_v1", "date": day, "computed_at": f"{nxt}T17:40:10+00:00"}
    return dict(base, input_manifest={"sources": {"habitify": {"latest_day": day}}}, **fields)


def test_the_character_compute_runs_after_daily_metrics_writes_the_habit_scores():
    """The order defect: character-sheet-compute ran at 09:30 PT and read the day's habit_scores, which daily-metrics
    writes at 09:40 PT. It now runs after daily-metrics and still before the brief, in the same zone."""
    rows = json.load(open(os.path.join(ROOT, "config", "schedules.json"), encoding="utf-8"))["schedules"]

    def hm(name):
        m = re.match(r"cron\((\d+) (\d+) ", rows[name]["expression"])
        return int(m.group(2)), int(m.group(1))

    assert hm("daily-metrics-compute") < hm("character-sheet-compute") < hm("daily-brief")
    assert rows["character-sheet-compute"].get("timezone") == rows["daily-metrics-compute"].get("timezone")


def test_mutation_control_the_old_order_fails_the_order_check():
    rows = {"daily-metrics-compute": (9, 40), "character-sheet-compute": (9, 30), "daily-brief": (10, 0)}
    assert not (rows["daily-metrics-compute"] < rows["character-sheet-compute"] < rows["daily-brief"])


def test_the_compute_waits_for_and_sees_the_days_habit_scores(monkeypatch):
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    from compute import character_sheet_lambda as L

    hs = _ready_hs("2026-11-04", core_pct=0.75)
    premature = dict(hs, computed_at="2026-11-04T20:00:00+00:00")  # written before the day closed: not the day
    reads, sleeps = iter([None, premature, hs]), []
    monkeypatch.setattr(L, "fetch_date", lambda source, d: next(reads) if source == "habit_scores" else None)
    got, status = L.await_habit_scores("2026-11-04", wait_s=30, poll_s=5, sleep=sleeps.append)
    assert got == hs and status == "ready" and sleeps == [5, 5]
    _raw, det = character_engine.compute_mind_raw({"habit_scores": got}, CONFIG)
    assert det["t0_habit_compliance"]["score"] == 75.0 and not det["t0_habit_compliance"].get("absent")
    monkeypatch.setattr(L, "fetch_date", lambda source, d: None)
    sleeps.clear()
    assert L.await_habit_scores("2026-11-04", wait_s=10, poll_s=5, sleep=sleeps.append) == (None, "missing") and sleeps == [5, 5]


def test_the_stored_sheet_records_the_habit_scores_readiness(monkeypatch):
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    from compute import character_sheet_lambda as L

    stored = []
    monkeypatch.setattr(L.character_engine, "store_character_sheet", lambda t, p, r: stored.append(dict(r)))
    monkeypatch.setattr(L.character_public, "attach_public_variant", lambda *a: "no chain")
    L.store_sheet({"date": "2026-11-04", "character_level": 3}, {"habit_scores_status": "ready"}, None, [], CONFIG)
    L.store_sheet({"date": "2026-11-05", "character_level": 3}, {"habit_scores_status": "missing"}, None, [], CONFIG)
    assert [s["habit_scores_status"] for s in stored] == ["ready", "missing"]


def _mind(details, method="core_set_v1"):
    return character_public.public_mind(details, method, character_public.public_config(CONFIG))


def test_no_public_mind_measurement_is_unavailable_never_zero():
    absent = {"t0_habit_compliance": {"score": 0.0, "absent": True}, "t1_habit_compliance": {"score": 0.0, "absent": True}}
    raw, det = _mind(dict(absent, reading_practice={"score": 0.0}, vice_control={"score": None}))
    assert det["_not_instrumented"] is True and det["_insufficient_data"] is True and raw == 50.0  # the no-signal shape
    raw2, det2 = _mind(dict(absent, reading_practice={"score": 50.0}))
    assert det2["_not_instrumented"] is False and raw2 > 0
    assert det2["t0_habit_compliance"]["score"] is None  # a missing habit record is missing data, not a 0
    assert "t0_habit_compliance" not in det2["_absent_behaviors"]


def test_mutation_control_scoring_a_missing_record_as_zero_would_report_zero():
    absent = {"t0_habit_compliance": {"score": 0.0, "absent": True}, "reading_practice": {"score": 0.0}}
    comps = character_public.public_config(CONFIG)["pillars"]["mind"]["components"]
    raw, det = character_engine._weighted_pillar_score({"t0_habit_compliance": None, "reading_practice": 0.0}, comps)
    assert raw == 0.0 and det["_not_instrumented"] is False  # the method-1 arithmetic: a misleading 0.0
    assert _mind(absent)[1]["_not_instrumented"] is True


def test_public_habit_data_moves_mind_as_expected():
    base = {"vice_control": {"score": 60.0}, "reading_practice": {"score": 50.0}}
    lo = _mind(dict(base, t0_habit_compliance={"score": 40.0}, t1_habit_compliance={"score": 40.0}))[0]
    hi = _mind(dict(base, t0_habit_compliance={"score": 90.0}, t1_habit_compliance={"score": 90.0}))[0]
    assert hi > lo
    assert hi == round((90 * 0.3 + 90 * 0.1 + 60 * 0.1 + 50 * 0.1) / 0.6, 1)


def test_the_unavailable_mind_leaves_the_composite_and_routes_serve_no_score(histories, monkeypatch):
    from web import site_api_vitals as V

    quiet, _private, q, _p = histories
    d = T._days()[-1]
    block = copy.deepcopy(q[d]["public"])
    block["pillar_mind"] = dict(block["pillar_mind"], not_instrumented=True, not_instrumented_note=character_public.UNAVAILABLE_NOTE)
    items = [dict(quiet[d], pk=B.SHEET_PK, **{B.PUBLIC: block})]
    body = json.loads(T._served(monkeypatch, items, lambda: V.handle_character(None)))
    mind = next(p for p in body["pillars"] if p["name"] == "mind")
    assert mind["not_instrumented"] is True and mind["not_instrumented_note"] == character_public.UNAVAILABLE_NOTE
    measured = [p for p in body["pillars"] if not p["not_instrumented"]]
    assert "mind" not in {p["name"] for p in measured} and body["character"]["composite_pillar_count"] == len(measured)
    assert body["character"]["composite_score"] == round(sum(p["raw_score"] for p in measured) / len(measured), 1)


def test_the_evening_checkin_presence_is_classified_public_and_its_answers_private():
    assert A.source_is_public("evening_checkin_presence") and not A.source_is_public("evening_checkin")
    assert set(A.CORE_BASIS_FAMILIES) == set(core_habits.BASES)
    assert all(A.core_basis_is_public(b) for b in core_habits.BASES)
    # the presence is derived from the check-in row (and its prompt ledger) alone — no journal partition is read
    src = open(os.path.join(ROOT, "lambdas", "health", "core_habits.py"), encoding="utf-8").read()
    assert "notion" not in src and "journal_entries" not in src and "flourishing" not in src


def test_mutation_control_a_private_core_basis_holds_the_habit_share_out(monkeypatch):
    det = {"t0_habit_compliance": {"score": 80.0}, "t1_habit_compliance": {"score": 80.0}, "reading_practice": {"score": 50.0}}
    with_core = _mind(det)[1]
    monkeypatch.setitem(A.ACTIVITY_ONLY_SOURCES, "evening_checkin_presence", A.PRIVATE)
    without = _mind(det)[1]
    assert "t0_habit_compliance" in with_core
    assert "t0_habit_compliance" not in without and "t1_habit_compliance" not in without


def test_challenge_xp_is_public_only_when_origin_domain_and_evidence_are():
    ok = {"source": "data_signal", "domain": "movement", "metric_targets": {"daily_steps": 8000, "streak_days": 7}}
    assert A.source_is_public("challenges") and A.challenge_is_public(ok)
    assert not A.challenge_is_public(dict(ok, source="journal_mining"))
    assert not A.challenge_is_public(dict(ok, domain="social"))
    assert not A.challenge_is_public(dict(ok, metric_targets={"mood_stability": 1}))
    assert not A.challenge_is_public(dict(ok, metric_targets={"a_new_target": 1}))  # unclassified fails closed
    assert not A.challenge_is_public(dict(ok, source=None))
    assert character_public.public_challenge_bonus({"movement": 5}) == {"movement": 5}
    assert character_public.public_challenge_bonus(None) == {}


def test_the_compute_credits_only_public_challenges_to_the_public_variant(monkeypatch):
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    from compute import character_sheet_lambda as L

    chs = [
        {
            "sk": "CHALLENGE#a",
            "status": "completed",
            "completed_at": "2026-11-04T20:00",
            "character_xp_awarded": 5,
            "domain": "movement",
            "source": "data_signal",
            "metric_targets": {"daily_steps": 1},
        },
        {
            "sk": "CHALLENGE#b",
            "status": "completed",
            "completed_at": "2026-11-04T21:00",
            "character_xp_awarded": 7,
            "domain": "mental",
            "source": "journal_mining",
        },
    ]

    class Tbl:
        def query(self, **kw):
            return {"Items": copy.deepcopy(chs)}

    monkeypatch.setattr(L, "table", Tbl())
    bonus, items = L.collect_challenge_bonus("2026-11-04")
    assert bonus == {"movement": 5, "mind": 7} and len(items) == 2
    assert L.PUBLIC_CHALLENGE_BONUS["2026-11-04"] == {"movement": 5}


def _habitify(journal_done):
    return {
        "habits": {"Walk": 1, "Floss": 0, "Morning Journal": journal_done, "Evening Journal": journal_done, "New thing": 1},
        "habit_statuses": {
            "Walk": {"habit_id": "1427C438-3012-47B6-846D-3CAEF84F4F9A"},
            "Floss": {"habit_id": "16D6E3B6-7345-4AB2-8DD1-F4BBEEADB750"},
            "Morning Journal": {"habit_id": "99A94E6D-3D82-4BE9-85EF-8858CB4BA340"},
            "Evening Journal": {"habit_id": "A862488C-8219-48EB-AD1F-90CBFDC37788"},
            "New thing": {"habit_id": "UNCLASSIFIED-ID"},
        },
    }


def test_habit_pct_counts_public_habits_only():
    H = habit_pct_public
    assert H.method1_habit_pct(_habitify(1)) != H.method1_habit_pct(_habitify(0))  # control: method 1 moves
    assert H.public_habit_pct(_habitify(1)) == H.public_habit_pct(_habitify(0)) == 0.5  # Walk + Floss only
    assert H.public_habit_pct({"habits": {"Morning Journal": 1}}) is None  # no public habit: no value, never 0


def test_the_published_habit_pct_readers_use_the_public_method(monkeypatch):
    from compute import weekly_correlation_compute_lambda as wc

    for journal in (0, 1):
        stub = {"habitify": [dict(_habitify(journal), date="2026-10-01")]}
        monkeypatch.setattr(wc, "fetch_range", lambda source, s, e, stub=stub: stub.get(source, []))
        assert wc.assemble_daily_series("2026-10-01", "2026-10-01")["2026-10-01"]["habit_pct"] == 0.5
    src = open(os.path.join(ROOT, "lambdas", "compute", "hypothesis_engine_lambda.py"), encoding="utf-8").read()
    assert "habit_pct_public.public_habit_pct(hab)" in src


def test_the_backfill_reconstructs_the_fixed_order_from_the_stored_habit_scores():
    m1 = {"date": "2026-10-30", "pillar_mind": {"components": {"t0_habit_compliance": {"score": 0.0, "absent": True}}}}
    hs = {"2026-10-30": _ready_hs("2026-10-30", core_pct=0.6, vice_streaks={"No alcohol": 10.0})}
    fixed, method, vice, info = B.order_fixed_inputs(m1, hs, CONFIG)
    assert method == "core_set_v1" and vice == {"No alcohol": 10.0} and info["habit_scores_present"]
    assert fixed["pillar_mind"]["components"]["t0_habit_compliance"]["score"] == 60.0
    assert m1["pillar_mind"]["components"]["t0_habit_compliance"]["absent"] is True  # method 1 untouched
    same, method2, _v, info2 = B.order_fixed_inputs(m1, {}, CONFIG)
    assert method2 is None and not info2["habit_scores_present"] and info2["readiness"] == "missing"
    assert same["pillar_mind"]["components"]["t0_habit_compliance"]["absent"] is True
