"""The PUBLIC variant of the character sheet and the day grade (owner ruling 2026-11-05).

"Public Mind, composite, XP, Day grades and overall levels must depend only on public-eligible inputs ... Apply the
same private-input invariance tests to historical results, rolling calculations and downstream aggregates."

Every test here builds TWO histories that differ ONLY in private inputs — journal entries and their 14-day count, the
journal-enrichment (flourishing) row, How We Feel / State of Mind, the check-in's stress, the journal habits — runs the
REAL engine for method 1, then the public method over it, and asserts the public outputs are byte-identical while the
method-1 outputs differ (the control that the private inputs were really there). Each invariance test has a mutation
control: undo one piece of the public method and the outputs move.
"""

import copy
import json
import os
import sys
from datetime import date, timedelta

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import backfill_public_variant as B  # noqa: E402
from health import character_engine, character_privacy, character_public, day_grade_public, scoring_engine  # noqa: E402

GENESIS = "2026-09-06"
N_DAYS = 30
CONFIG = json.load(open(os.path.join(ROOT, "config", "character_sheet.json"), encoding="utf-8"))
PRIVATE_DAYS = {3, 4, 9, 10, 11, 17, 24}  # day indexes carrying private inputs in the "private" history


def _days(n=N_DAYS):
    return [(date.fromisoformat(GENESIS) + timedelta(days=i)).isoformat() for i in range(n)]


def _public_inputs(i, d):
    """Public inputs that vary by day, identical in both histories."""
    return {
        "date": d,
        "sleep": {"sleep_duration_hours": 6.0 + (i % 5) * 0.5, "sleep_efficiency_percentage": 80 + (i % 7) * 2},
        "habit_scores": {"scoring_method": "core_set_v1", "core_pct": round(0.4 + (i % 6) * 0.1, 3)},
        "vice_streaks": {"No alcohol": float(i + 1)},
        "reading_session_days_7d": [d] * (i % 4),
        "data_completeness_pct": 60.0 + (i % 3) * 20,
        "todoist": {"overdue_count": float(i % 5)},
        "engagement_state": {
            "presence_class": "present",
            "gap_days": 0,
            "planned_pause": False,
            "public": {"presence_class": "present", "gap_days": 0, "planned_pause": False},
        },
    }


def _private_inputs(i, d):
    """The private inputs a journal day carries: entries, the 14-day count, the enrichment row, SoM, stress."""
    entries = [
        {"sk": f"DATE#{d}#journal#evening", "template": "Evening", "enriched_mood": 4, "enriched_themes": ["family time", "friends"]}
    ]
    return {
        "journal_entries": entries,
        "journal": {"themes": ["family time", "friends"], "mood_avg": 7.5},
        "journal_14d_count": 1 + (i % 3),
        "flourishing": {"values_lived_count": 3, "social_quality_score": 8.0, "enrichment_model": "test-model"},
        "state_of_mind": {"som_avg_valence": 0.6},
        "evening_checkin": {"stress": 1},
    }


def _method1_history(with_private: bool, days=None):
    """The stored method-1 records the live compute would have written (the engine's own chain, stored precision)."""
    days = days or _days()
    records = {}
    for i, d in enumerate(days):
        data = _public_inputs(i, d)
        if with_private and i in PRIVATE_DAYS:
            data.update(_private_inputs(i, d))
        hist = B.window_records(records, d)
        data.update(character_engine.derive_consistency_inputs(hist, d))
        rec = character_engine.compute_character_sheet(data, B.previous_record(records, d), B.raw_histories(hist), CONFIG)
        rec.pop("progression_transitions", None)
        rec["sk"] = f"DATE#{d}"
        records[d] = B.as_stored(rec)
    return records


def _engagement(records):
    return {d: _public_inputs(0, d)["engagement_state"] for d in records}


def _habit_scores(records):
    """The habit_scores records the method-1 compute read (the same public inputs), as stored."""
    out = {}
    for i, d in enumerate(_days()):
        if d in records:
            pub = _public_inputs(i, d)
            out[d] = dict(pub["habit_scores"], vice_streaks=pub["vice_streaks"])
    return out


def _replay(records):
    return B.replay_character(records, _engagement(records), _habit_scores(records), CONFIG, "2026-11-05T00:00:00+00:00")


def _public_blocks(replayed):
    return {d: r["public"] for d, r in replayed.items()}


def _canon(obj):
    return json.dumps(obj, sort_keys=True, default=str)


@pytest.fixture(scope="module")
def histories():
    quiet, private = _method1_history(False), _method1_history(True)
    return quiet, private, _replay(quiet), _replay(private)


# ── single day + the historical chain ──────────────────────────────────────────────────────


def test_method1_really_differs_between_the_two_histories(histories):
    """The control: the private inputs reach method 1 (Mind, Relationships XP, the composite, consistency)."""
    quiet, private, _q, _p = histories
    d = _days()[PRIVATE_DAYS.__iter__().__next__()]
    assert _canon(quiet) != _canon(private)
    assert any(quiet[d]["pillar_mind"]["raw_score"] != private[d]["pillar_mind"]["raw_score"] for d in quiet)
    assert any(quiet[d]["character_xp"] != private[d]["character_xp"] for d in quiet)
    assert d in quiet


def test_public_variant_is_byte_identical_across_the_whole_replayed_history(histories):
    """Every date's public block — Mind, composite inputs, XP, levels, streaks, buffers, effects, mood, events — is
    the same whether or not private inputs existed, across the multi-day state chain."""
    _quiet, _private, q, p = histories
    assert _canon(_public_blocks(q)) == _canon(_public_blocks(p))


def test_public_receipts_are_byte_identical(histories):
    _quiet, _private, q, p = histories
    for d in q:
        a = {"date": d, B.PUBLIC: q[d]["public"], "public_progression_transitions": q[d]["transitions"]}
        b = {"date": d, B.PUBLIC: p[d]["public"], "public_progression_transitions": p[d]["transitions"]}
        ra, rb = character_public.public_receipt(a, CONFIG, []), character_public.public_receipt(b, CONFIG, [])
        assert _canon(ra) == _canon(rb)
        assert ra["replay_verified"] is True


def test_mutation_control_a_public_method_that_kept_the_private_components_would_move(histories, monkeypatch):
    quiet, private, _q, _p = histories
    monkeypatch.setattr(character_public, "mind_component_is_public", lambda name: name in character_public.MIND_COMPONENT_SOURCES)
    assert _canon(_public_blocks(_replay(quiet))) != _canon(_public_blocks(_replay(private)))


def test_mutation_control_chaining_from_method1_state_would_move(histories):
    """The public chain must start from the previous PUBLIC state: chaining from method 1's leaks private inputs."""
    quiet, private, _q, _p = histories
    d = _days()[max(PRIVATE_DAYS) + 1]
    pa = B.previous_record(quiet, d)
    pb = B.previous_record(private, d)
    a, _ = character_public.compute_public_variant(quiet[d], pa, [], CONFIG, computed_at="t")
    b, _ = character_public.compute_public_variant(private[d], pb, [], CONFIG, computed_at="t")
    assert _canon(a) != _canon(b)


def test_non_private_pillars_are_unchanged_by_the_public_method(histories):
    """Sleep, Movement, Nutrition and Metabolic read no private input: their raw score, details, level, XP and
    streaks in the public variant are exactly method 1's, on every date."""
    _quiet, private, _q, p = histories
    for d, rec in private.items():
        for pillar in character_public.VERBATIM_PILLARS:
            m1, pub = rec[f"pillar_{pillar}"], p[d]["public"][f"pillar_{pillar}"]
            for f in (
                "raw_score",
                "level",
                "level_score",
                "xp_total",
                "xp_debt",
                "xp_buffer",
                "streak_above",
                "streak_below",
                "tier",
                "components",
            ):
                assert m1.get(f) == pub.get(f), (d, pillar, f)


def test_the_method1_replay_reproduces_the_stored_chain(histories):
    """The fidelity control the backfill reports: the same machinery over method-1 inputs reproduces method 1."""
    _quiet, private, _q, p = histories
    assert all(r["fidelity"] == [] for r in p.values())


def test_public_mind_holds_the_private_components_out_of_sum_and_coverage():
    det = {
        "t0_habit_compliance": {"score": 60.0, "weight": 0.3},
        "t1_habit_compliance": {"score": 60.0, "weight": 0.1},
        "journal_consistency": {"score": 0.0, "weight": 0.1, "absent": True},
        "state_of_mind_valence": {"score": 80.0, "weight": 0.1},
        "stress_management": {"score": 75.0, "weight": 0.1, "owner_only": True, "held_out": True},
        "values_alignment": {"score": 100.0, "weight": 0.1},
        "vice_control": {"score": 50.0, "weight": 0.1},
        "reading_practice": {"score": 0.0, "weight": 0.1, "absent": True},
    }
    cfg = character_public.public_config(CONFIG)
    raw, details = character_public.public_mind(det, "core_set_v1", cfg)
    assert set(k for k in details if not k.startswith("_")) == {
        "t0_habit_compliance",
        "t1_habit_compliance",
        "vice_control",
        "reading_practice",
    }
    assert details["_data_coverage"] == 1.0  # none of the private weights in the denominator
    assert raw == round((60 * 0.3 + 60 * 0.1 + 50 * 0.1 + 0 * 0.1) / 0.6, 1)
    _raw2, details2 = character_public.public_mind(det, "tier_weighted_v1", cfg)
    assert "t1_habit_compliance" not in details2  # the tier-1 share counted the journal habits


def test_a_sick_day_freezes_the_public_chain_as_the_live_compute_freezes_method1(histories):
    """The live sick-day path stores a verbatim copy of the previous record (its public variant included); the replay
    mirrors it, and the chain after the frozen day stays invariant to private inputs."""

    def frozen(records, d):
        prev = B.previous_record(records, d)
        out = dict(records)
        out[d] = dict(copy.deepcopy(prev), date=d, sk=f"DATE#{d}", sick_day=True)
        return out

    quiet, private, _q, _p = histories
    d = _days()[12]
    rq, rp = _replay(frozen(quiet, d)), _replay(frozen(private, d))
    assert rp[d]["public"] == rp[_days()[11]]["public"] and rp[d]["sick_day_frozen_from"] == _days()[11]
    assert _canon(_public_blocks(rq)) == _canon(_public_blocks(rp))


def test_relationships_has_no_public_reading_and_no_xp(histories):
    _quiet, _private, _q, p = histories
    for r in p.values():
        rel = r["public"]["pillar_relationships"]
        assert rel["not_instrumented"] is True and rel["xp_total"] == 0 and rel["level"] == 1
        assert "relationships" in r["public"]["headline_excluded_pillars"]


# ── the stored shape, the readers, fail closed ─────────────────────────────────────────────


def _stored(m1, block):
    return dict(m1, **{B.PUBLIC: block})


def test_public_sheet_serves_the_variant_and_never_method1(histories):
    _quiet, private, _q, p = histories
    d = _days()[10]
    view = character_privacy.public_sheet(_stored(private[d], p[d]["public"]))
    assert view["pillar_mind"]["raw_score"] == p[d]["public"]["pillar_mind"]["raw_score"]
    assert view["character_xp"] == p[d]["public"]["character_xp"]
    assert view["date"] == d and view["public_method_version"] == character_privacy.PUBLIC_METHOD_VERSION
    assert character_privacy.public_sheet(private[d]) is None  # no variant: nothing (fail closed)
    unknown = dict(p[d]["public"], public_method_version="character-public-v0")
    assert character_privacy.public_sheet(_stored(private[d], unknown)) is None
    assert character_privacy.public_sheets([private[d], _stored(private[d], p[d]["public"])]) == [view]


def test_the_method_label_does_not_depend_on_private_inputs(histories):
    _quiet, private, q, p = histories
    labels = {_canon(character_privacy.public_method_label(_stored(private[d], p[d]["public"]))) for d in private}
    assert len(labels) == 1
    live = dict(q[_days()[0]]["public"], origin="live")
    assert character_privacy.public_method_label(_stored(private[_days()[0]], live))["origin"] == "live"


class _Table:
    def __init__(self, items):
        self.items = sorted(items, key=lambda i: i["sk"], reverse=True)

    def query(self, **kw):
        return {"Items": copy.deepcopy(self.items)}

    def get_item(self, Key):
        for i in self.items:
            if i["sk"] == Key["sk"]:
                return {"Item": copy.deepcopy(i)}
        return {}


def _items(records, replayed):
    return [dict(records[d], pk=B.SHEET_PK, **{B.PUBLIC: replayed[d]["public"]}) for d in records]


def _served(monkeypatch, items, route):
    from web import site_api_character as C, site_api_vitals as V

    monkeypatch.setattr(V, "table", _Table(items))
    monkeypatch.setattr(V, "EXPERIMENT_START", GENESIS)
    monkeypatch.setattr(V, "_query_source", lambda *a, **k: [])  # the other sources: identical (empty) on both sides
    monkeypatch.setattr(V, "_get_profile", lambda *a, **k: {})
    monkeypatch.setattr(C, "_attach_pillar_absence", lambda *a, **k: None)
    body = json.loads(route()["body"])
    body.pop("_meta", None)
    return _canon(body)


def test_api_character_latest_and_dated_are_byte_identical(histories, monkeypatch):
    quiet, private, q, p = histories
    from web import site_api_vitals as V

    for when in (None, _days()[11], _days()[25]):
        a = _served(monkeypatch, _items(quiet, q), lambda w=when: V.handle_character(w))
        b = _served(monkeypatch, _items(private, p), lambda w=when: V.handle_character(w))
        assert a == b
    assert '"method"' in a


def test_api_character_fails_closed_without_a_public_variant(histories, monkeypatch):
    quiet, _private, q, _p = histories
    from web import site_api_vitals as V

    days = sorted(quiet)
    items = _items(quiet, q)
    items[-1].pop(B.PUBLIC)  # the latest record has no public variant
    body = json.loads(_served(monkeypatch, items, lambda: V.handle_character(None)))
    assert body["character"]["as_of_date"] == days[-2]  # an earlier public record, never the method-1 one
    bare = [{k: v for k, v in i.items() if k != B.PUBLIC} for i in items]
    body = json.loads(_served(monkeypatch, bare, lambda: V.handle_character(None)))
    assert body["character"].get("pre_experiment") is True and body["character"]["level"] == 1


def test_downstream_routes_are_byte_identical(histories, monkeypatch):
    """/api/timeline, /api/pillar_coupling, /api/character_stats over the two histories."""
    quiet, private, q, p = histories
    from web import site_api_discovery, site_api_vitals as V

    for route in (V.handle_timeline, lambda: site_api_discovery.pillar_coupling(_g={"table": V.table})):
        a = _served(monkeypatch, _items(quiet, q), route)
        b = _served(monkeypatch, _items(private, p), route)
        assert a == b


def test_character_stats_json_is_written_from_the_public_variant_only(histories, monkeypatch):
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    from compute import character_sheet_lambda as L
    from content import site_writer

    quiet, private, q, p = histories
    d = _days()[-1]
    calls = []
    monkeypatch.setattr(site_writer, "write_character_stats", lambda s3_client=None, **kw: calls.append(_canon(kw)))
    for recs, rep in ((quiet, q), (private, p)):
        monkeypatch.setattr(L, "fetch_range", lambda *a, recs=recs, rep=rep: _items(recs, rep))
        L.publish_site_stats(_stored(recs[d], rep[d]["public"]), d, 21)
    assert len(calls) == 2 and calls[0] == calls[1]
    L.publish_site_stats(private[d], d, 21)  # no public variant: not written at all
    assert len(calls) == 2


def test_the_receipt_route_serves_only_the_public_receipt(histories):
    from web import site_api_character as C

    _quiet, private, _q, p = histories
    d = _days()[12]
    pub = character_public.public_receipt(
        {"date": d, B.PUBLIC: p[d]["public"], "public_progression_transitions": p[d]["transitions"]}, CONFIG, []
    )
    served = C._public_receipt({"digest": "method-1", "transitions": {"pillars": {"mind": {}}}, B.PUBLIC: pub})
    assert served["digest"] == pub["digest"] and "relationships" not in served["transitions"]["pillars"]
    assert C._public_receipt({"digest": "method-1", "transitions": {"pillars": {}}}) is None


# ── the live compute ──────────────────────────────────────────────────────────────────────


def test_live_attach_matches_the_backfill_and_fails_closed_without_a_chain(histories):
    _quiet, private, _q, p = histories
    days = _days()
    d = days[15]
    rec = copy.deepcopy(private[d])
    prev = _stored(B.previous_record(private, d), p[days[14]]["public"])
    hist = [_stored(private[h], p[h]["public"]) for h in sorted(private) if B.shift(d, -21) <= h <= B.shift(d, -1)]
    pub = _public_inputs(days.index(d), d)
    data = {"engagement_state": pub["engagement_state"], "habit_scores": pub["habit_scores"], "vice_streaks": pub["vice_streaks"]}
    assert character_public.attach_public_variant(rec, data, prev, hist, CONFIG) is None
    live, back = dict(rec[B.PUBLIC]), dict(p[d]["public"])
    for k in ("computed_at", "origin"):
        live.pop(k), back.pop(k)
    assert _canon(B.as_stored(live)) == _canon(back)
    rec2 = copy.deepcopy(private[d])
    reason = character_public.attach_public_variant(rec2, data, private[days[14]], hist, CONFIG)
    assert reason and B.PUBLIC not in rec2  # the previous record has no public variant: none attached


def test_store_sheet_keeps_method1_when_the_public_variant_fails(monkeypatch):
    os.environ.setdefault("S3_BUCKET", "test-bucket")
    from compute import character_sheet_lambda as L

    stored = []
    monkeypatch.setattr(L.character_engine, "store_character_sheet", lambda t, p, r: stored.append(dict(r)))
    monkeypatch.setattr(L.character_public, "attach_public_variant", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    L.store_sheet({"date": "2026-09-10", "character_level": 3, B.PUBLIC: {"x": 1}}, {}, None, [], CONFIG)
    assert stored and stored[0]["character_level"] == 3 and B.PUBLIC not in stored[0]


def test_the_sheet_item_never_stores_the_public_transitions():
    class T:
        def put_item(self, Item):
            self.item = Item

    t = T()
    character_engine.store_character_sheet(
        t, "P#", {"date": "2026-09-10", "progression_transitions": {"a": 1}, "public_progression_transitions": {"b": 2}, B.PUBLIC: {"c": 3}}
    )
    assert "progression_transitions" not in t.item and "public_progression_transitions" not in t.item and B.PUBLIC in t.item


# ── the day grade ─────────────────────────────────────────────────────────────────────────

_PROFILE = {
    "day_grade_weights": {
        "sleep_quality": 0.2,
        "recovery": 0.15,
        "nutrition": 0.2,
        "movement": 0.15,
        "habits_mvp": 0.15,
        "hydration": 0.05,
        "journal": 0.05,
        "glucose": 0.05,
    },
    "habit_registry": {
        "Morning Journal": {"status": "active", "tier": 1},
        "Evening Journal": {"status": "active", "tier": 1},
        "Walk": {"status": "active", "tier": 0, "habitify_id": "1427C438-3012-47B6-846D-3CAEF84F4F9A"},
        "Floss": {"status": "active", "tier": 1, "habitify_id": "16D6E3B6-7345-4AB2-8DD1-F4BBEEADB750"},
    },
}


def _grade_data(journal: bool):
    habits = {"Walk": 1, "Floss": 0, "Morning Journal": 1 if journal else 0, "Evening Journal": 1 if journal else 0}
    statuses = {
        "Walk": {"status": "completed", "habit_id": "1427C438-3012-47B6-846D-3CAEF84F4F9A"},
        "Floss": {"status": "not_done", "habit_id": "16D6E3B6-7345-4AB2-8DD1-F4BBEEADB750"},
        "Morning Journal": {"status": "completed" if journal else "not_done", "habit_id": "99A94E6D-3D82-4BE9-85EF-8858CB4BA340"},
        "Evening Journal": {"status": "completed" if journal else "not_done", "habit_id": "A862488C-8219-48EB-AD1F-90CBFDC37788"},
    }
    data = {
        "date": "2026-09-10",
        "sleep": {"sleep_score": 80, "sleep_efficiency_pct": 90, "sleep_duration_hours": 7.5},
        "whoop": {"recovery_score": 70},
        "habitify": {"habits": habits, "habit_statuses": statuses},
        "habitify_7d": [],
    }
    if journal:
        data["journal_entries"] = [{"template": "Morning"}, {"template": "Evening"}]
    return data


def test_day_grade_public_variant_is_invariant_to_the_journal_and_its_habits(monkeypatch):
    monkeypatch.setattr(day_grade_public, "TIER_WEIGHTED_HABITS", "replay")  # the re-score itself must be invariant
    m1a = scoring_engine.compute_day_grade(_grade_data(False), _PROFILE)
    m1b = scoring_engine.compute_day_grade(_grade_data(True), _PROFILE)
    assert m1a[0] != m1b[0]  # control: method 1 moves with the journal and its habits
    a, b = day_grade_public.compute_live(_grade_data(False), _PROFILE), day_grade_public.compute_live(_grade_data(True), _PROFILE)
    for x in (a, b):
        x.pop("computed_at")
    assert a == b and "journal" not in a["component_scores"] and "journal" not in a["weights"]


def test_day_grade_mutation_control_keeping_the_journal_component_would_move(monkeypatch):
    monkeypatch.setattr(day_grade_public, "PRIVATE_COMPONENTS", {})
    monkeypatch.setattr(day_grade_public, "PRIVATE_DATA_KEYS", ())
    a, b = day_grade_public.compute_live(_grade_data(False), _PROFILE), day_grade_public.compute_live(_grade_data(True), _PROFILE)
    assert a["total_score"] != b["total_score"]


def test_day_grade_tier_weighted_habits_are_held_out_by_default():
    out = day_grade_public.compute_live(_grade_data(True), _PROFILE)
    assert "habits_mvp" not in out["component_scores"]


def test_day_grade_from_stored_components_renormalises_without_the_journal():
    item = {
        "component_sleep_quality": 90,
        "component_recovery": 60,
        "component_journal": 100,
        "weights_snapshot": _PROFILE["day_grade_weights"],
    }
    r = B.replay_day_grade(item, "core_set", None, _PROFILE, "t")
    assert r["public"]["total_score"] == round((90 * 0.2 + 60 * 0.15) / 0.35)
    item2 = dict(item, component_journal=0)
    assert B.replay_day_grade(item2, "core_set", None, _PROFILE, "t")["public"] == r["public"]


def test_day_grade_readers_serve_the_public_variant_or_nothing():
    rec = {
        "total_score": 63,
        "letter_grade": "C",
        day_grade_public.PUBLIC_KEY: {"total_score": 70, "letter_grade": "B-", "public_method_version": day_grade_public.METHOD_VERSION},
    }
    assert day_grade_public.public_score(rec) == 70.0 and day_grade_public.public_letter(rec) == "B-"
    assert day_grade_public.public_score({"total_score": 63}) is None and day_grade_public.public_letter({"letter_grade": "C"}) is None


def test_day_grade_aggregates_are_invariant_over_a_month_of_journal_variation(monkeypatch):
    """The weekly correlations, /api/what_changed's monthly delta and the recap card's grade, computed from day_grade
    records the live writer would store — 70 days where only the journal and its habits vary."""
    from compute import weekly_correlation_compute_lambda as wc
    from content import recap_data

    days = [(date(2026, 9, 1) + timedelta(days=i)).isoformat() for i in range(70)]

    def records(journal_days):
        out = []
        for i, d in enumerate(days):
            data = dict(_grade_data(i in journal_days), date=d)
            data["sleep"] = {"sleep_score": 60 + i % 30, "sleep_efficiency_pct": 85, "sleep_duration_hours": 7}
            score, letter, comps, _ = scoring_engine.compute_day_grade(data, _PROFILE)
            pub = day_grade_public.stored_fields((data, _PROFILE))[day_grade_public.PUBLIC_KEY]
            pub = dict(B.decimals_to_float(pub), computed_at="t")
            out.append({"date": d, "total_score": score, "letter_grade": letter, day_grade_public.PUBLIC_KEY: pub})
        return out

    def aggregates(rows):
        mf = [{"date": d, "total_calories_kcal": 1800 + 7 * i} for i, d in enumerate(days)]
        stub = {"day_grade": rows, "macrofactor": mf}
        monkeypatch.setattr(wc, "fetch_range", lambda source, s, e: [r for r in stub.get(source, []) if s <= r["date"] <= e])
        series = wc.assemble_daily_series(days[0], days[-1])
        corr = wc.compute_correlations(series, pairs=[("calories", "day_grade", "calories_vs_day_grade", 0)])
        month = wc.compute_month_deltas(series, days[-1], metrics=[("day_grade", "Day grade", "", True)])
        by_day = {r["date"]: r for r in rows}
        monkeypatch.setattr(recap_data, "_get_day", lambda t, source, d: by_day.get(d) if source == "day_grade" else None)
        letters = [day_grade_public.public_letter(by_day[d]) for d in days]
        return _canon([corr, month, letters, [r[day_grade_public.PUBLIC_KEY]["total_score"] for r in rows]])

    quiet, journaled = records(set()), records(set(range(0, 70, 3)))
    assert [r["total_score"] for r in quiet] != [r["total_score"] for r in journaled]  # control: method 1 moves
    assert aggregates(quiet) == aggregates(journaled)


def test_weekly_correlation_and_story_dossier_read_the_public_grade():
    """The two day-grade aggregates read only the public variant (a method-1-only record contributes nothing)."""
    src = open(os.path.join(ROOT, "lambdas", "compute", "weekly_correlation_compute_lambda.py"), encoding="utf-8").read()
    assert 'metrics["day_grade"] = day_grade_public.public_score(' in src and 'safe_float(cm, "day_grade_score")' not in src
    from content import story_dossier

    class T:
        pass

    rows = {
        "2026-09-10": {
            "total_score": 50,
            day_grade_public.PUBLIC_KEY: {"total_score": 70, "public_method_version": day_grade_public.METHOD_VERSION},
        },
        "2026-09-11": {"total_score": 90},
    }
    orig = story_dossier._days
    try:
        story_dossier._days = lambda table, source, s, e: rows
        assert story_dossier._grades(T(), {"start": "2026-09-10", "end": "2026-09-11"})["day_grade_mean"] == 70.0
    finally:
        story_dossier._days = orig


# ── the backfill's export / apply / rollback ──────────────────────────────────────────────


class _WTable:
    """An in-memory table: get_item + update_item (SET / REMOVE of one attribute)."""

    def __init__(self, items):
        self.items = {(i["pk"], i["sk"]): copy.deepcopy(i) for i in items}
        self.updates = []

    def get_item(self, Key):
        i = self.items.get((Key["pk"], Key["sk"]))
        return {"Item": copy.deepcopy(i)} if i else {}

    def update_item(self, Key, UpdateExpression, ExpressionAttributeNames, ExpressionAttributeValues=None, ConditionExpression=None):
        self.updates.append(UpdateExpression)
        item = self.items[(Key["pk"], Key["sk"])]
        attr = ExpressionAttributeNames["#p"]
        if UpdateExpression.startswith("SET"):
            item[attr] = ExpressionAttributeValues[":p"]
        else:
            item.pop(attr, None)


def test_apply_writes_only_the_public_attribute_and_rollback_restores_the_pre_image(histories):
    _quiet, private, _q, p = histories
    days = _days()[:5]
    originals = [B.floats_to_decimal(dict(private[d], pk=B.SHEET_PK), precision=4) for d in days]
    originals[1][B.PUBLIC] = {"public_method_version": "character-public-v1", "character_level": 9}  # one had a prior value
    t = _WTable(originals)
    before = {k: _canon(B.decimals_to_float(v)) for k, v in t.items.items()}
    plan = [{"pk": B.SHEET_PK, "sk": f"DATE#{d}", "value": p[d]["public"], "precision": 4} for d in days]
    export = B.build_export(lambda key: t.get_item(Key=key).get("Item"), plan, "t")
    assert [e["had_public"] for e in export["entries"]] == [False, True, False, False, False]
    res = B.apply_plan(t, plan, export)
    assert res["written"] == 5 and not res["skipped"] and all(u == "SET #p = :p" for u in t.updates)
    for d in days:  # every method-1 field untouched
        after = B.decimals_to_float(t.items[(B.SHEET_PK, f"DATE#{d}")])
        assert {k: v for k, v in after.items() if k != B.PUBLIC} == {
            k: v for k, v in json.loads(before[(B.SHEET_PK, f"DATE#{d}")]).items() if k != B.PUBLIC
        }
    dry = B.rollback(t, json.loads(json.dumps(export)), apply=False)
    assert [o["op"] for o in dry["operations"]] == ["REMOVE", "SET", "REMOVE", "REMOVE", "REMOVE"] and not dry["refused"]
    assert len(t.updates) == 5  # the dry run wrote nothing
    B.rollback(t, json.loads(json.dumps(export)), apply=True)
    assert {k: _canon(B.decimals_to_float(v)) for k, v in t.items.items()} == before


def test_a_rerun_after_apply_plans_no_change(histories):
    """Idempotency: once applied, the same plan differs from nothing stored; a moved value is named."""
    _quiet, private, _q, p = histories
    days = _days()[:4]
    t = _WTable([B.floats_to_decimal(dict(private[d], pk=B.SHEET_PK), precision=4) for d in days])
    plan = [{"pk": B.SHEET_PK, "sk": f"DATE#{d}", "value": p[d]["public"], "precision": 4} for d in days]
    B.apply_plan(t, plan, B.build_export(lambda key: t.get_item(Key=key).get("Item"), plan, "t"))
    stored = {k: B.decimals_to_float(v) for k, v in t.items.items()}
    rerun = [dict(w, value=dict(w["value"], computed_at="later")) for w in plan]
    assert B.differs_from_stored(rerun, stored) == {"items_with_public": 4, "differing": []}
    moved = [dict(rerun[0], value=dict(rerun[0]["value"], character_level=99))] + rerun[1:]
    assert B.differs_from_stored(moved, stored)["differing"] == [f"character_sheet DATE#{days[0]}"]


def test_apply_and_rollback_refuse_an_item_whose_method1_fields_changed(histories):
    _quiet, private, _q, p = histories
    d = _days()[0]
    t = _WTable([B.floats_to_decimal(dict(private[d], pk=B.SHEET_PK), precision=4)])
    plan = [{"pk": B.SHEET_PK, "sk": f"DATE#{d}", "value": p[d]["public"], "precision": 4}]
    export = B.build_export(lambda key: t.get_item(Key=key).get("Item"), plan, "t")
    t.items[(B.SHEET_PK, f"DATE#{d}")]["character_level"] = 99  # a method-1 field moved after the export
    assert B.apply_plan(t, plan, export)["skipped"] and not t.updates
    assert B.rollback(t, export, apply=True)["refused"] and not t.updates


def test_the_export_refuses_to_plan_a_missing_item():
    t = _WTable([])
    with pytest.raises(RuntimeError):
        B.build_export(
            lambda key: t.get_item(Key=key).get("Item"), [{"pk": B.SHEET_PK, "sk": "DATE#2026-09-10", "value": {}, "precision": 4}], "t"
        )


# ── presence ──────────────────────────────────────────────────────────────────────────────


def test_public_presence_prefers_the_stored_projection_and_derives_without_the_journal():
    pub = {"presence_class": "present", "gap_days": 0, "planned_pause": False}
    assert character_public.public_presence({"public": pub})[0] == pub
    rec = {
        "presence_class": "light",
        "gap_days": 2,
        "planned_pause": False,
        "channels_quiet": ["journal"],
        "last_manual_log_date": "2026-09-22",
        "channel_detail": {"macrofactor": {"last_log_date": "2026-09-22"}},
    }
    presence, exact, _why = character_public.public_presence(rec)
    assert presence["presence_class"] == "light" and "channels_quiet" not in presence and exact
    flip = dict(rec, channels_quiet=[])  # the same day had the journal been logged: the derivation does not move
    assert character_public.public_presence(flip)[0]["presence_class"] == presence["presence_class"]
