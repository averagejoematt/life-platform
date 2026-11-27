"""tests/test_development_profile_6294.py — #6294: the private personal-development profile.

`health.development_profile.assemble_profile` is pure; `mcp.tools_development_profile.get_development_profile` reads.
Covered here, over synthetic, impersonal fixtures (a fictional subject; the repo is public):
  * the domain registry equals the closed `life_domains` vocabulary, in the store and in the write schema;
  * every status rule: measured (a trend over a stated window with a minimum n, sick/travel days excluded), counted
    (counts only, improving only past the margin, a drop never read as decline), own report and owner-confirmed
    (at least N dated self-reports in each window, contradictory statements -> mixed with both shown);
  * missing data -> not_enough_to_say and NEVER harder; a failed read -> unread, never empty;
  * planted enriched_* fields, sentiment, journal frequency and conversation counts change nothing;
  * interpretations (ai_interpretation, competing_hypothesis, rejected_interpretation, observed_pattern) and unreviewed
    records are never evidence; an open hypothesis is listed as an open question, never counted;
  * no roll-up key or number above the evidence; last_owner_view and the how_to_disagree call shape;
  * life_domains / life_direction are validated and written only through the approval queue;
  * the tool is a read (mcp.audit), writes nothing against a write-refusing table, and no site, coach, AI, email or
    content module can import the profile; the demonstration script runs.
"""

# premerge-gate: sweeps lambdas/ and mcp/ (rglob + the import graph) for site routes naming the profile and import paths from coach/AI/web modules into it

import ast
import copy
import json
import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

ROOT = Path(__file__).resolve().parent.parent
for _p in (str(ROOT), str(ROOT / "lambdas"), str(ROOT / "tests")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from ai import platform_memory as pm  # noqa: E402
from health import development_profile as dp  # noqa: E402

TODAY = "2026-11-20"  # a fixed Pacific day — nothing below reads the live clock
T = date.fromisoformat(TODAY)


def _d(days_ago: int) -> str:
    return (T - timedelta(days=days_ago)).isoformat()


RECENT = range(0, 28)  # days ago inside the recent measured window
PRIOR = range(28, 56)


def _status(profile, key):
    return next(d for d in profile["domains"] if d["domain"] == key)


def _profile(inputs):
    return dp.assemble_profile(inputs, today=TODAY)


# ── synthetic inputs ────────────────────────────────────────────────────────────────────────────


def _measured(recent_z2_days=5, prior_z2_days=3, recent_lift=110.0, prior_lift=100.0):
    """Every day observed; zone 2 sessions of 30 min on the first N days of each week; three lifts."""
    zone2, training = [], []
    for ago in list(RECENT) + list(PRIOR):
        per_week = recent_z2_days if ago < 28 else prior_z2_days
        if ago % 7 < per_week:
            zone2.append({"date": _d(ago), "minutes": 30})
            training.append(_d(ago))
    lifts = []
    for name in ("Fictional Press", "Fictional Row", "Fictional Squat"):
        lifts.append({"date": _d(40), "identity": name.upper(), "name": name, "best_e1rm_lb": prior_lift})
        lifts.append({"date": _d(5), "identity": name.upper(), "name": name, "best_e1rm_lb": recent_lift})
    habits = [{"date": _d(a), "completion_pct": 0.8 if a < 28 else 0.6} for a in list(RECENT) + list(PRIOR)]
    return {
        "observed_days": [_d(a) for a in range(56)],
        "excluded_days": {"sick": [], "travel": []},
        "zone2_sessions": zone2,
        "training_days": training,
        "lift_sessions": lifts,
        "weight": [{"date": _d(a), "weight_lbs": 200 - a * 0.0} for a in (1, 10, 30, 50)],
        "habit_days": habits,
    }


def _record(ago, kind="owner_statement", domains=("social_connection",), direction="better", reviewed=True, text="A synthetic note."):
    r = {
        "pk": "USER#matthew#SOURCE#platform_memory",
        "sk": f"MEMORY#personal_record#{_d(ago)}#{abs(hash((ago, kind, direction, text))) % 10**10:010d}",
        "category": "personal_record",
        "summary": text,
        "evidence_kind": kind,
        "event_date": _d(ago),
        "event_date_precision": "day",
        "life_domains": list(domains),
        "life_direction": direction,
    }
    if reviewed:
        r["owner_reviewed_at"] = f"{_d(ago)}T12:00:00+00:00"
    return r


def _ratings(recent_mood=4, prior_mood=3, days=10):
    rows = []
    for ago in list(range(days)) + list(range(28, 28 + days)):
        rows.append({"date": _d(ago), "morning_mood": recent_mood if ago < 28 else prior_mood, "stress_level": 2})
    return rows


# ── the registry ────────────────────────────────────────────────────────────────────────────────


def test_the_domain_registry_is_the_closed_life_domain_vocabulary_everywhere():
    import mcp.tools_memory as tm

    assert tuple(dp.DOMAINS) == pm.LIFE_DOMAINS
    props = tm.WRITE_PLATFORM_MEMORY_INPUT["properties"]
    assert props["life_domains"]["items"]["enum"] == list(pm.LIFE_DOMAINS)
    assert props["life_direction"]["enum"] == list(pm.LIFE_DIRECTIONS)
    assert len(dp.DOMAINS) == 9
    for key, spec in dp.DOMAINS.items():
        assert spec["basis"] in dp.BASES and spec["definition"] and spec["sources"], key
    assert dp.OWNER_SELF_REPORT_MEASURES == {}, "the questionnaire seam stays empty until its own reviewed change"


# ── missing data ────────────────────────────────────────────────────────────────────────────────


def test_no_data_reads_not_enough_to_say_in_every_domain():
    p = _profile({})
    assert {d["status"] for d in p["domains"]} == {dp.NOT_ENOUGH}
    for d in p["domains"]:
        assert d["not_observed"], d["domain"]
        assert d["how_to_disagree"]["tool"] == "log_coach_correction"


def test_absence_never_produces_harder():
    """Strip every recent-window observation from a dataset that reads improving: each domain falls to not enough, never harder."""
    inputs = _measured()
    inputs["personal_records"] = [_record(a, direction="better") for a in (5, 10, 20, 100, 110, 120)]
    inputs["journal_entries"] = _ratings()
    stripped = copy.deepcopy(inputs)
    recent_days = {_d(a) for a in RECENT}
    stripped["observed_days"] = [d for d in stripped["observed_days"] if d not in recent_days]
    stripped["zone2_sessions"] = [s for s in stripped["zone2_sessions"] if s["date"] not in recent_days]
    stripped["training_days"] = [d for d in stripped["training_days"] if d not in recent_days]
    stripped["lift_sessions"] = [s for s in stripped["lift_sessions"] if s["date"] not in recent_days]
    stripped["habit_days"] = [h for h in stripped["habit_days"] if h["date"] not in recent_days]
    stripped["journal_entries"] = [r for r in stripped["journal_entries"] if r["date"] not in recent_days]
    stripped["personal_records"] = [r for r in stripped["personal_records"] if r["event_date"] < _d(89)]
    p = _profile(stripped)
    assert dp.HARDER not in {d["status"] for d in p["domains"]}
    for key in ("physical_capacity", "behavioural_consistency", "emotional_wellbeing", "social_connection"):
        assert _status(p, key)["status"] == dp.NOT_ENOUGH, key


def test_a_failed_read_is_unread_never_a_zero():
    inputs = _measured(recent_z2_days=0)  # observed days with no zone 2 at all: a real measured drop
    assert _status(_profile(inputs), "physical_capacity")["status"] in (dp.MIXED, dp.HARDER)
    inputs["read_failed"] = {"zone2_sessions": "ClientError", "lift_sessions": "ClientError"}
    d = _status(_profile(inputs), "physical_capacity")
    assert d["status"] == dp.NOT_ENOUGH
    assert any("read failed" in n for n in d["not_observed"])


# ── measured rules ──────────────────────────────────────────────────────────────────────────────


def test_measured_improving_steady_and_harder_follow_the_stated_margins():
    assert _status(_profile(_measured()), "physical_capacity")["status"] == dp.IMPROVING
    assert _status(_profile(_measured(recent_z2_days=3, recent_lift=100.0)), "physical_capacity")["status"] == dp.STEADY
    assert _status(_profile(_measured(recent_z2_days=1, recent_lift=90.0)), "physical_capacity")["status"] == dp.HARDER
    assert _status(_profile(_measured(recent_z2_days=5, recent_lift=90.0)), "physical_capacity")["status"] == dp.MIXED
    beh = _status(_profile(_measured()), "behavioural_consistency")
    assert beh["status"] == dp.IMPROVING and beh["basis"] == dp.MEASURED


def test_measured_evidence_shows_window_n_and_the_underlying_figures():
    d = _status(_profile(_measured()), "physical_capacity")
    z2 = next(e for e in d["evidence"] if e.get("indicator") == "zone2_minutes_per_week")
    assert z2["evidence_kind"] == "measured" and z2["n"] == {"recent": 28, "prior": 28}
    assert z2["window"]["recent"] == {"start": _d(27), "end": TODAY}
    assert z2["figure"]["recent"] == pytest.approx(150.0) and z2["figure"]["prior"] == pytest.approx(90.0)
    weight = next(e for e in d["evidence"] if e["source"].startswith("withings"))
    assert weight["counts_toward_status"] is False, "weight is shown, never scored"


def test_sick_and_travel_days_are_excluded_from_the_denominator():
    inputs = _measured(recent_z2_days=5, prior_z2_days=5, recent_lift=100.0)
    base = _status(_profile(inputs), "physical_capacity")
    sick = [_d(a) for a in RECENT if a % 7 >= 5]  # the recent no-session days, all marked sick
    inputs["excluded_days"] = {"sick": sick, "travel": []}
    d = _status(_profile(inputs), "physical_capacity")
    z2 = next(e for e in d["evidence"] if e.get("indicator") == "zone2_minutes_per_week")
    assert z2["n"]["recent"] == 28 - len(sick) and z2["excluded"]["recent"]["sick"] == len(sick)
    assert base["status"] == dp.STEADY
    # the whole recent window on travel -> below the minimum -> not enough to say (never harder)
    inputs["excluded_days"] = {"sick": [], "travel": [_d(a) for a in RECENT]}
    beh = _status(_profile(inputs), "behavioural_consistency")
    assert beh["status"] in (dp.NOT_ENOUGH, dp.IMPROVING, dp.STEADY)
    td = next(i for i in beh["evidence"] if i.get("indicator") == "training_days_per_week")
    assert td["direction"] == dp.INSUFFICIENT and td["n"]["recent"] == 0


def test_below_the_minimum_n_is_not_enough_to_say():
    inputs = _measured()
    keep = {_d(a) for a in range(0, 10)} | {_d(a) for a in PRIOR}
    inputs["observed_days"] = sorted(keep)
    inputs["zone2_sessions"] = [s for s in inputs["zone2_sessions"] if s["date"] in keep]
    inputs["lift_sessions"] = []
    assert _status(_profile(inputs), "physical_capacity")["status"] == dp.NOT_ENOUGH


# ── counted rules ───────────────────────────────────────────────────────────────────────────────


def _experiments(recent, prior):
    out = []
    for i in range(recent):
        out.append({"experiment_id": f"r{i}", "start_date": _d(5 + i), "end_date": None, "status": "active"})
    for i in range(prior):
        out.append({"experiment_id": f"p{i}", "start_date": _d(60 + i), "end_date": None, "status": "active"})
    return out


def test_counted_domain_improves_only_past_the_margin_and_never_declines():
    assert _status(_profile({"experiments": _experiments(6, 2)}), "learning_and_experimentation")["status"] == dp.IMPROVING
    inside = _status(_profile({"experiments": _experiments(4, 3)}), "learning_and_experimentation")
    assert inside["status"] == dp.NOT_ENOUGH
    fewer = _status(_profile({"experiments": _experiments(0, 8)}), "learning_and_experimentation")
    assert fewer["status"] == dp.NOT_ENOUGH, "fewer records is never read as decline"
    assert any("not read as decline" in n for n in fewer["not_observed"])
    assert fewer["basis"] == dp.COUNTED


def test_learning_counts_answers_outcomes_and_decisions():
    recs = [
        {"response": "accepted", "response_recorded_at": f"{_d(3 + i)}T09:00:00Z", "outcome": {"recorded_at": f"{_d(2)}T10:00:00Z"}}
        for i in range(3)
    ]
    recs.append({"response": "not_recorded", "response_recorded_at": None, "outcome": None})
    decisions = [{"sk": "DECISION#x", "date": _d(10), "outcome_date": _d(4)}, {"sk": "DECISION#y", "date": _d(10), "outcome_date": None}]
    d = _status(_profile({"recommendations": recs, "decisions": decisions}), "learning_and_experimentation")
    by_kind = d["evidence"][0]["figure"]["by_kind"]
    assert by_kind["recommendations_answered"]["recent"] == 3
    assert by_kind["recommendation_outcomes_recorded"]["recent"] == 3
    assert by_kind["decisions_with_outcome"]["recent"] == 1
    assert d["status"] == dp.IMPROVING


def _hypothesis(hid, views, open_=True):
    return {
        "hypothesis_id": hid,
        "question": "Why does the fictional subject skip Thursday piano practice?",
        "status": "exploratory",
        "open": open_,
        "history": [{"kind": "owner_view", "view": v, "recorded_at": f"{_d(a)}T08:00:00Z"} for v, a in views],
    }


def test_self_understanding_counts_his_views_and_lists_open_hypotheses_as_questions():
    hyps = [_hypothesis("ph_aaaaaaaaaaaa", [("confirm", 3), ("correct", 4)]), _hypothesis("ph_bbbbbbbbbbbb", [("reject", 6)], open_=False)]
    recs = [_record(5, kind="confirmed_insight", domains=()), _record(7, kind="rejected_interpretation", domains=())]
    for r in recs:
        r.pop("life_domains")
        r.pop("life_direction")
    d = _status(_profile({"hypotheses": hyps, "personal_records": recs}), "self_understanding")
    by_kind = next(e for e in d["evidence"] if e.get("indicator") == "interpretations_reviewed")["figure"]["by_kind"]
    assert by_kind["hypotheses_confirmed"]["recent"] == 1 and by_kind["hypotheses_rejected"]["recent"] == 1
    assert by_kind["insights_confirmed"]["recent"] == 1 and by_kind["interpretations_rejected"]["recent"] == 1
    assert d["status"] == dp.IMPROVING  # 5 in the recent window against 0 before
    assert [q["hypothesis_id"] for q in d["open_questions"]] == ["ph_aaaaaaaaaaaa"]
    assert d["open_questions"][0]["counts_toward_status"] is False and "not evidence" in d["open_questions"][0]["label"]


# ── own report / owner-confirmed rules ──────────────────────────────────────────────────────────


def test_self_report_domain_needs_n_dated_statements_in_each_window():
    three_each = [_record(a) for a in (5, 10, 20, 100, 110, 120)]
    assert _status(_profile({"personal_records": three_each}), "social_connection")["status"] == dp.IMPROVING
    two_recent = [_record(a) for a in (5, 10, 100, 110, 120)]
    assert _status(_profile({"personal_records": two_recent}), "social_connection")["status"] == dp.NOT_ENOUGH
    undated = [dict(r, event_date="2026-10", event_date_precision="month") for r in three_each]
    d = _status(_profile({"personal_records": undated}), "social_connection")
    assert d["status"] == dp.NOT_ENOUGH and len(d["evidence"]) == 6, "a coarse-dated record is shown, not windowed"
    assert all(e["counts_toward_status"] is False for e in d["evidence"])


def test_his_statements_pointing_both_ways_read_mixed_and_both_are_shown():
    recs = [_record(5, direction="better", text="Calmer after the weekly call."), _record(10, direction="harder", text="Lonely week.")]
    recs += [_record(20, direction="same")] + [_record(a, direction="same") for a in (100, 110, 120)]
    d = _status(_profile({"personal_records": recs}), "social_connection")
    assert d["status"] == dp.MIXED
    shown = {e["statement"] for e in d["evidence"]}
    assert {"Calmer after the weekly call.", "Lonely week."} <= shown
    assert d["basis"] == dp.OWNER_CONFIRMED


def test_his_own_harder_statements_can_read_harder():
    recs = [_record(a, direction="harder") for a in (5, 10, 20)] + [_record(a, direction="same") for a in (100, 110, 120)]
    assert _status(_profile({"personal_records": recs}), "coping_and_flexibility")["status"] == dp.NOT_ENOUGH  # tagged elsewhere
    recs = [dict(r, life_domains=["coping_and_flexibility"]) for r in recs]
    assert _status(_profile({"personal_records": recs}), "coping_and_flexibility")["status"] == dp.HARDER


def test_interpretations_and_unreviewed_records_are_never_evidence():
    base = [_record(a) for a in (5, 10, 20, 100, 110, 120)]
    offenders = []
    for kind in ("ai_interpretation", "competing_hypothesis", "rejected_interpretation", "observed_pattern"):
        planted = base + [_record(a, kind=kind, direction="harder", text="An interpretation.") for a in (3, 4, 6, 7)]
        planted += [_record(a, direction="harder", reviewed=False, text="Unreviewed.") for a in (2, 8, 9)]
        d = _status(_profile({"personal_records": planted}), "social_connection")
        if d["status"] != dp.IMPROVING or {e["statement"] for e in d["evidence"]} != {"A synthetic note."}:
            offenders.append(kind)
    assert offenders == [], offenders


def test_emotional_wellbeing_reads_his_ratings_only():
    d = _status(_profile({"journal_entries": _ratings()}), "emotional_wellbeing")
    assert d["status"] == dp.IMPROVING and d["basis"] == dp.OWN_REPORT
    mood = next(e for e in d["evidence"] if e.get("indicator") == "journal_mood")
    assert mood["evidence_kind"] == "self_report" and mood["n"] == {"recent": 10, "prior": 10}
    # a model score where he gave no rating is never read: model-only entries are invisible
    model_only = [{"date": _d(a), "enriched_mood": 1, "enriched_stress": 5} for a in range(40)]
    assert _status(_profile({"journal_entries": model_only}), "emotional_wellbeing")["status"] == dp.NOT_ENOUGH
    few = _ratings(days=dp.RATING_MIN_DAYS - 1)
    assert _status(_profile({"journal_entries": few}), "emotional_wellbeing")["status"] == dp.NOT_ENOUGH


def test_evening_checkin_stress_rising_reads_harder():
    rows = [{"date": _d(a), "mood": 2, "stress": 3 if a < 28 else 1} for a in list(range(10)) + list(range(28, 38))]
    d = _status(_profile({"evening_checkins": rows}), "emotional_wellbeing")
    assert d["status"] == dp.HARDER  # mood steady, stress up 2 points on his own 0-4 scale


# ── never inputs ────────────────────────────────────────────────────────────────────────────────

_PLANT = {
    "enriched_mood": 1,
    "enriched_energy": 1,
    "enriched_stress": 5,
    "enriched_sentiment": "negative",
    "enriched_themes": ["isolation"],
    "enriched_avoidance_flags": ["planted"],
    "enriched_defense_patterns": ["planted"],
    "enriched_cognitive_patterns": ["planted"],
    "enriched_social_quality": 1,
    "sentiment": -0.9,
    "journal_entry_count": 0,
    "conversation_count": 0,
    "word_count": 3,
}


def _full_inputs():
    inputs = _measured()
    inputs["personal_records"] = [_record(a) for a in (5, 10, 20, 100, 110, 120)]
    inputs["journal_entries"] = _ratings()
    inputs["evening_checkins"] = [{"date": _d(a), "mood": 3, "stress": 1} for a in range(10)]
    inputs["experiments"] = _experiments(5, 1)
    inputs["hypotheses"] = [_hypothesis("ph_aaaaaaaaaaaa", [("confirm", 3)])]
    return inputs


def _strip_volatile(p):
    return json.loads(json.dumps(p, default=str))


def test_planted_enrichment_sentiment_and_frequency_change_nothing():
    clean = _profile(_full_inputs())
    planted = _full_inputs()
    for key, rows in planted.items():
        if isinstance(rows, list):
            planted[key] = [dict(r, **_PLANT) if isinstance(r, dict) else r for r in rows]
    for k, v in _PLANT.items():
        planted[k] = v
    # journal frequency: every rated day written three times over, with the same rating
    planted["journal_entries"] = planted["journal_entries"] * 3
    # and a flood of unrated entries (more journaling, no rating) plus enrichment-only rows
    planted["journal_entries"] += [{"date": _d(a), **_PLANT} for a in range(56)]
    assert _strip_volatile(_profile(planted)) == _strip_volatile(clean)


def test_the_module_names_no_enrichment_or_inferred_label_field():
    from common.inferred_fields import INFERRED_PSYCH_LABEL_FIELDS, INFERRED_PSYCH_LABEL_KEYS, MODEL_SCORE_FIELDS

    banned = INFERRED_PSYCH_LABEL_FIELDS | INFERRED_PSYCH_LABEL_KEYS | set(MODEL_SCORE_FIELDS.values())
    for rel in ("lambdas/health/development_profile.py", "mcp/tools_development_profile.py"):
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        names = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not names & banned, (rel, names & banned)
        assert not [s for s in names if s.startswith("enriched_")], rel
        assert "resolve_rating" not in names and "resolved_value" not in names, "the model fallback is never even reached"


# ── no roll-up ──────────────────────────────────────────────────────────────────────────────────

_ROLLUP = frozenset(
    {"score", "overall", "composite", "level", "rank", "ranking", "percent", "percentage", "pct", "xp", "total", "index", "grade"}
)


def _walk_keys(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield f"{path}.{k}", k
            yield from _walk_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk_keys(v, path)


def test_no_roll_up_key_or_number_above_the_evidence():
    p = _profile(_full_inputs())
    bad = [path for path, k in _walk_keys(p) if set(str(k).lower().split("_")) & _ROLLUP]
    assert bad == [], bad
    for k, v in p.items():
        if k not in ("rules", "rules_version"):
            assert not isinstance(v, (int, float)) or isinstance(v, bool), k
    for d in p["domains"]:
        for k, v in d.items():
            if k in ("evidence", "open_questions"):
                continue
            assert not isinstance(v, (int, float)) or isinstance(v, bool), (d["domain"], k)
    assert set(dp.STATUSES) >= {d["status"] for d in p["domains"]}


# ── his view and the disagreement door ──────────────────────────────────────────────────────────


def test_last_owner_view_and_how_to_disagree():
    from coach import coach_corrections

    from mcp.tools_descriptions import LOG_COACH_CORRECTION_INPUT

    rows = [
        {
            "sk": "CORRECTION#2026-11-10#aaaa1111",
            "created_at": "2026-11-10T18:00:00+00:00",
            "item_ref": {"surface": dp.PROFILE_SURFACE, "signal": dp.signal_for("social_connection")},
            "correction_text": "This reads too rosy.",
            "error_class": "framing",
        },
        {
            "sk": "CORRECTION#2026-11-12#bbbb2222",
            "created_at": "2026-11-12T18:00:00+00:00",
            "item_ref": {"surface": dp.PROFILE_SURFACE, "signal": dp.signal_for("social_connection")},
            "correction_text": "Fair, that is right.",
            "error_class": dp.AGREE_ERROR_CLASS,
        },
        {
            "sk": "CORRECTION#2026-11-13#cccc3333",
            "created_at": "2026-11-13T18:00:00+00:00",
            "item_ref": {"surface": "chat_coaching", "signal": dp.signal_for("social_connection")},
            "correction_text": "Another surface.",
            "error_class": "framing",
        },
    ]
    p = _profile({"profile_corrections": rows})
    view = _status(p, "social_connection")["last_owner_view"]
    assert view == {
        "date": "2026-11-12",
        "view": "agree",
        "his_words": "Fair, that is right.",
        "correction_sk": "CORRECTION#2026-11-12#bbbb2222",
    }
    assert _status(p, "coping_and_flexibility")["last_owner_view"] is None
    call = _status(p, "social_connection")["how_to_disagree"]
    assert call["tool"] == "log_coach_correction"
    assert set(call["arguments"]) <= set(LOG_COACH_CORRECTION_INPUT["properties"])
    assert call["arguments"]["surface"] not in coach_corrections.OWNER_FACING_SURFACES, "no coach prompt reads a profile correction"


# ── the life-domain tags: validated, queue-only ─────────────────────────────────────────────────


def test_life_tags_are_validated():
    ok, out = pm.validate_provenance(
        {"evidence_kind": "owner_statement", "life_domains": ["social_connection"], "life_direction": "better"}
    )
    assert ok is None and out["life_domains"] == ["social_connection"] and out["life_direction"] == "better"
    assert pm.validate_provenance({"evidence_kind": "owner_statement", "life_domains": ["happiness"]})[0]
    assert pm.validate_provenance({"evidence_kind": "owner_statement", "life_direction": "better"})[0]
    assert pm.validate_provenance({"evidence_kind": "owner_statement", "life_domains": ["social_connection"], "life_direction": "up"})[0]
    for kind in ("ai_interpretation", "competing_hypothesis", "rejected_interpretation", "observed_pattern"):
        err = pm.validate_provenance({"evidence_kind": kind, "life_domains": ["social_connection"]})[0]
        assert err and "cannot be tagged" in err, kind
    assert pm.validate_provenance({"evidence_kind": "ai_interpretation"})[0] is None, "untagged rows are unchanged"


class _MemTable:
    def __init__(self):
        self.store: dict = {}

    def put_item(self, Item, ConditionExpression=None, ExpressionAttributeNames=None, ExpressionAttributeValues=None):
        key = (Item["pk"], Item["sk"])
        if ConditionExpression == "attribute_not_exists(sk)" and key in self.store:
            raise type("ConditionalCheckFailedException", (Exception,), {})("exists")
        if ConditionExpression == "#st = :expected" and (self.store.get(key) or {}).get("status") != ExpressionAttributeValues[":expected"]:
            raise type("ConditionalCheckFailedException", (Exception,), {})("status")
        self.store[key] = json.loads(json.dumps(Item, default=str))
        return {}

    def get_item(self, Key):
        item = self.store.get((Key["pk"], Key["sk"]))
        return {"Item": dict(item)} if item else {}

    def query(self, **kwargs):
        if isinstance(kwargs["KeyConditionExpression"], str):
            pk, prefix = kwargs["ExpressionAttributeValues"][":pk"], kwargs["ExpressionAttributeValues"][":pfx"]
        else:
            exp = kwargs["KeyConditionExpression"].get_expression()
            pk = exp["values"][0].get_expression()["values"][1]
            prefix = exp["values"][1].get_expression()["values"][1]
        return {"Items": [dict(v) for (p, s), v in sorted(self.store.items()) if p == pk and s.startswith(prefix)]}


def test_life_tags_are_written_only_through_the_approval_queue(monkeypatch):
    import mcp.audit as mcp_audit
    import mcp.tools_memory as tm
    import mcp.tools_pending_writes as tpw

    t = _MemTable()
    monkeypatch.setattr(tm, "_table_ref", t)
    monkeypatch.setattr(tpw, "_table_ref", t)
    monkeypatch.setattr(mcp_audit, "record_mutation", lambda *a, **k: None)
    args = {
        "category": "personal_record",
        "content": {"summary": "A synthetic statement about a weekly call with a friend."},
        "evidence_kind": "owner_statement",
        "event_date": "2026-11-01",
        "life_domains": ["social_connection"],
        "life_direction": "better",
    }
    direct = tm.tool_write_platform_memory(dict(args))
    assert "QUEUE-ONLY" in direct["error"] and not t.store
    bad = tpw.tool_manage_pending_writes(
        {"action": "enqueue", "target_tool": "write_platform_memory", "target_args": dict(args, life_domains=["x"]), "summary": "s"}
    )
    assert "error" in bad
    q = tpw.tool_manage_pending_writes({"action": "enqueue", "target_tool": "write_platform_memory", "target_args": args, "summary": "s"})
    assert q.get("queued"), q
    res = tpw.tool_manage_pending_writes({"action": "approve", "pending_id": q["pending_id"]})
    assert res.get("approved") is True, res
    rows = [v for (p, s), v in t.store.items() if s.startswith("MEMORY#personal_record#")]
    assert len(rows) == 1 and rows[0]["life_domains"] == ["social_connection"] and rows[0]["owner_reviewed_at"]
    assert pm._META_FIELDS >= {"life_domains", "life_direction"}, "the tags are never rendered as a memory's text"


# ── read-only, owner-only ───────────────────────────────────────────────────────────────────────


class _ReadOnlyTable:
    def __init__(self):
        self.calls: list = []

    def query(self, **kwargs):
        self.calls.append("query")
        return {"Items": []}

    def get_item(self, **kwargs):
        self.calls.append("get_item")
        return {}

    def __getattr__(self, name):
        raise AssertionError(f"the profile tried table.{name} — it is read-only")


def test_the_tool_is_a_read_and_writes_nothing(monkeypatch):
    from mcp_registry_ast import registered_tool_names

    import mcp.tools_development_profile as tdp
    from mcp import audit

    assert "get_development_profile" in registered_tool_names((ROOT / "mcp" / "registry.py").read_text(encoding="utf-8"))
    assert audit.is_write_tool("get_development_profile") is False
    t = _ReadOnlyTable()
    monkeypatch.setattr(tdp, "_table_ref", t)
    monkeypatch.setattr(tdp, "_user_id_ref", "matthew")
    monkeypatch.setattr(tdp, "query_source", lambda *a, **k: [])
    import mcp.tools_correlation as tcorr
    import mcp.tools_strength as tstr

    monkeypatch.setattr(tcorr, "tool_get_zone2_breakdown", lambda args: {"error": "No recorded sessions for range."})
    monkeypatch.setattr(tstr, "_read_hevy_all_phases", lambda *a, **k: ([], []))
    import mcp.tools_journal as tj

    monkeypatch.setattr(tj, "_query_journal", lambda *a, **k: [])
    out = tdp.tool_get_development_profile({"today": TODAY})
    assert {d["status"] for d in out["domains"]} == {dp.NOT_ENOUGH}
    assert set(t.calls) <= {"query", "get_item"} and t.calls
    assert out["reads"]["failed"] == {}, out["reads"]

    def boom(*a, **k):
        raise RuntimeError("synthetic read failure")

    monkeypatch.setattr(tdp, "query_source", boom)
    out = tdp.tool_get_development_profile({"today": TODAY})
    assert "habit_days" in out["reads"]["failed"] and dp.HARDER not in {d["status"] for d in out["domains"]}
    src = (ROOT / "mcp" / "tools_development_profile.py").read_text(encoding="utf-8")
    for verb in ("put_item", "update_item", "delete_item", "batch_write", "ddb_cache_set", "enqueue"):
        assert verb not in src, verb


def test_no_public_coach_or_prompt_module_can_reach_the_profile():
    from test_research_findings_6208 import NO_READ_PACKAGES, _closure, _import_graph

    graph = _import_graph()
    roots = [m for m in graph if m.startswith(NO_READ_PACKAGES)]
    assert len(roots) > 50, "the roots were not found — vacuous guard"
    profile_modules = {"health.development_profile", "mcp.tools_development_profile"}
    reached = _closure(graph, roots)
    assert not reached & profile_modules, sorted(reached & profile_modules)
    importers = sorted(m for m, deps in graph.items() if deps & profile_modules and m not in profile_modules)
    assert importers == ["mcp.registry"], importers
    graph["coach.fake_prompt"] = {"health.development_profile"}
    assert _closure(graph, ["coach.fake_prompt"]) & profile_modules, "the boundary sweep can fail"


def test_no_site_route_names_the_profile():
    hits = []
    for p in (ROOT / "lambdas" / "web").rglob("*.py"):
        src = p.read_text(encoding="utf-8", errors="replace")
        if any(s in src for s in ("development_profile", "life_domains", "get_development_profile")):
            hits.append(str(p.relative_to(ROOT)))
    assert hits == [], hits


# ── the demonstration ───────────────────────────────────────────────────────────────────────────


def test_the_demo_script_prints_a_full_profile():
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_")}
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "demo_development_profile.py")],
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(ROOT),
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    for key in dp.DOMAINS:
        assert key in proc.stdout, key
    assert "no overall score" in proc.stdout and "RESULT: PASS" in proc.stdout
