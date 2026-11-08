"""Owner rulings on PR #5656 (2026-11-06/07): the dependency, history and reader requirements before any write.

* an explicit readiness check of the day's habit scores (not the schedule alone), failing closed;
* recalculated history distinguished from what was available on the date — in data, API and pages;
* a recalculation never fires an event, a badge or a milestone ("a methodology correction, not an improvement");
* the PUBLIC correction ledger cannot identify private activity;
* evaluation / coach / calibration / baseline readers keep reading method-1 as-of values (a reader inventory);
* public Mind, XP, composite, level and Day grade stay invariant to private journal inputs.
"""

# premerge-gate: the reader inventory sweeps lambdas/ + mcp/ for every reader of the character_sheet / day_grade partitions

import copy
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "tests"))

import backfill_public_variant as B  # noqa: E402
import test_character_public_variant as T  # noqa: E402 — the two-history fixtures
from health import character_privacy, character_public, public_corrections  # noqa: E402

histories = T.histories
CONFIG = T.CONFIG
DAY = "2026-11-04"


def _hs(**over):
    base = {
        "date": DAY,
        "computed_at": "2026-11-05T17:40:10+00:00",
        "input_manifest": {"sources": {"habitify": {"latest_day": DAY}, "notion": {"status": "stale", "latest_day": "2026-09-09"}}},
    }
    return dict(base, **over)


# ── readiness ────────────────────────────────────────────────────────────────────────────


def test_readiness_is_an_explicit_check_of_day_closure_and_public_inputs():
    r = character_public.habit_scores_readiness
    assert r(_hs(), DAY) == "ready"
    assert r(None, DAY) == "missing"
    assert r(_hs(date="2026-11-03"), DAY) == "wrong_day"
    assert r(_hs(computed_at="2026-11-04T23:00:00+00:00"), DAY) == "before_day_closed"  # 15:00 PT on the day itself
    assert r(_hs(input_manifest={"sources": {"habitify": {"latest_day": "2026-11-03"}}}), DAY) == "habitify_behind"
    assert r(_hs(input_manifest={}), DAY) == "unverified"


def test_readiness_never_reads_a_private_input():
    """The journal's manifest row is always degraded; it must not gate a public score either way."""
    a = _hs()
    b = copy.deepcopy(a)
    b["input_manifest"]["sources"]["notion"] = {"status": "fresh", "latest_day": DAY}
    assert character_public.habit_scores_readiness(a, DAY) == character_public.habit_scores_readiness(b, DAY) == "ready"


def test_a_day_whose_habit_scores_are_not_ready_reads_them_as_missing_never_zero_never_carried(histories):
    _quiet, private, _q, p = histories
    days = T._days()
    d = days[15]
    prev = T._stored(B.previous_record(private, d), p[days[14]]["public"])
    hist = [T._stored(private[h], p[h]["public"]) for h in sorted(private) if B.shift(d, -21) <= h <= B.shift(d, -1)]
    pub = T._public_inputs(days.index(d), d)
    out = {}
    for status in ("ready", "missing"):
        rec = copy.deepcopy(private[d])
        data = {
            "engagement_state": pub["engagement_state"],
            "habit_scores": pub["habit_scores"],
            "vice_streaks": pub["vice_streaks"],
            "habit_scores_status": status,
        }
        assert character_public.attach_public_variant(rec, data, prev, hist, CONFIG) is None
        out[status] = rec[B.PUBLIC]["pillar_mind"]
    assert out["ready"]["components"]["t0_habit_compliance"]["score"] > 0
    assert out["missing"]["components"]["t0_habit_compliance"]["score"] is None  # missing data, not a 0
    assert "t0_habit_compliance" not in out["missing"]["absent_behaviors"]


# ── recalculated history is labelled, and fires nothing ─────────────────────────────────


def _rec(day, level, origin, m1_level=None, events=None):
    block = {
        "public_method_version": character_privacy.PUBLIC_METHOD_VERSION,
        "origin": origin,
        "computed_at": "2026-11-08T03:00:00+00:00",
        "character_level": level,
        "level_events": events or [],
    }
    return {"date": day, "sk": f"DATE#{day}", "character_level": m1_level if m1_level is not None else level, B.PUBLIC: block}


def test_recalculated_values_say_so_in_data_api_and_pages():
    rec = character_privacy.public_method_label(_rec("2026-10-01", 9, "recomputed"))
    live = character_privacy.public_method_label(_rec("2026-11-09", 22, "live"))
    assert rec["origin"] == "recomputed" and rec["basis"] == "records_available_at_recalculation" and rec["recalculated_on"] == "2026-11-08"
    assert live["origin"] == "live" and live["basis"] == "records_available_at_compute" and live["recalculated_on"] is None
    assert rec["notice"] == character_privacy.PUBLIC_CORRECTION_NOTICE and live["notice"] is None
    assert "not from what was available on this date" in rec["label"]
    import publish_snapshot_day as S

    payload = {"character": {"as_of_date": "2026-10-01", "level": 9, "method": rec}, "pillars": []}
    assert character_privacy.PUBLIC_CORRECTION_NOTICE in S.engine_of(payload, "2026-10-01")["method"]


def test_a_recalculated_record_carries_no_level_event_on_any_public_reader():
    ev = [{"type": "character_level_up", "old_level": 9, "new_level": 12}]
    view = character_privacy.public_sheet(_rec("2026-10-01", 12, "recomputed", events=ev))
    assert view["level_events"] == [] and view["recalculated_level_events"] == ev
    assert character_privacy.public_sheet(_rec("2026-11-09", 22, "live", events=ev))["level_events"] == ev


def test_the_correction_earns_no_badge_and_no_milestone():
    recs = [_rec("2026-10-01", 18, "recomputed", m1_level=13), _rec("2026-11-04", 21, "recomputed", m1_level=16)]
    assert character_privacy.event_level(recs) == 16  # the level actually reached then, never the recalculated 21
    recs.append(_rec("2026-11-09", 21, "live"))  # live, but only back at the recalculated level: no event
    assert character_privacy.event_level(recs) == 16 and character_privacy.public_event_sheets(recs) == []
    recs.append(_rec("2026-11-10", 22, "live"))  # a real rise above the corrected history
    assert character_privacy.event_level(recs) == 22 and [v["date"] for v in character_privacy.public_event_sheets(recs)] == ["2026-11-10"]


def test_the_timeline_draws_no_level_up_from_recalculated_history(monkeypatch):
    from web import site_api_journey, site_api_vitals as V

    recs = [_rec(f"2026-10-{d:02d}", lvl, "recomputed") for d, lvl in ((1, 5), (2, 9), (3, 12))] + [
        _rec("2026-11-09", 12, "live"),
        _rec("2026-11-10", 14, "live"),
    ]
    for r in recs:
        r["pk"] = B.SHEET_PK

    class _Asc(T._Table):  # the route queries ScanIndexForward=True: oldest first, as DynamoDB serves it
        def query(self, **kw):
            return {"Items": copy.deepcopy(sorted(self.items, key=lambda i: i["sk"]))}

    monkeypatch.setattr(T, "_Table", _Asc)
    body = json.loads(T._served(monkeypatch, recs, lambda: V.handle_timeline()))
    assert [(e["date"], e["level"]) for e in body["timeline"]["level_ups"]] == [("2026-11-10", 14)]  # 5→9→12 drew nothing
    assert site_api_journey  # the module the handler delegates to


# ── the public correction ledger ─────────────────────────────────────────────────────────


def _ledger(records):
    before = B.replay_character(records, T._engagement(records), T._habit_scores(records), CONFIG, "t", order_fix=False)
    after = B.replay_character(records, T._engagement(records), T._habit_scores(records), CONFIG, "t")
    return public_corrections.build_ledger(
        {d: r["public"] for d, r in before.items()}, {d: r["public"] for d, r in after.items()}, "2026-11-08"
    )


def test_the_public_correction_ledger_cannot_identify_private_activity(histories):
    quiet, private, _q, _p = histories
    a, b = _ledger(quiet), _ledger(private)
    assert T._canon(a) == T._canon(b)  # every row, every reason: the same whatever the journal did
    assert a["rows"] and a["reason_categories"] == list(public_corrections.REASON_CATEGORIES)
    served = public_corrections.served_ledger(a)
    assert set(served) == set(public_corrections.SERVED_KEYS)


def test_mutation_control_a_ledger_with_method1_befores_would_leak(histories):
    quiet, private, q, p = histories
    a = public_corrections.build_ledger(dict(quiet), {d: r["public"] for d, r in q.items()}, "x")
    b = public_corrections.build_ledger(dict(private), {d: r["public"] for d, r in p.items()}, "x")
    assert T._canon(a) != T._canon(b)


# ── the reader inventory: evaluation keeps method-1 as-of values ────────────────────────

# Every module that reads the character_sheet or day_grade partitions, by role.
PUBLIC_VARIANT_READERS = {
    "lambdas/compute/character_sheet_lambda.py",  # character_stats.json (+ the producer)
    "lambdas/compute/dashboard_refresh_lambda.py",  # buddy/data.json
    "lambdas/compute/weekly_correlation_compute_lambda.py",  # /api/correlations, /api/what_changed
    "lambdas/content/recap_data.py",  # the recap card
    "lambdas/content/story_dossier.py",  # the chronicle's weekly dossier
    "lambdas/emails/chronicle_data.py",  # the chronicle packet
    "lambdas/emails/daily_brief_lambda.py",  # writes buddy/data.json through the public sheet
    "lambdas/emails/daily_debrief_lambda.py",  # the public audio debrief's grade
    "lambdas/health/achievement_rules.py",  # level badges: event levels only
    "lambdas/health/milestone_ledger.py",  # level milestones: event levels only
    "lambdas/web/site_api_ai_context.py",
    "lambdas/web/site_api_character.py",
    "lambdas/web/site_api_discovery.py",
    "lambdas/web/site_api_fulfillment.py",
    "lambdas/web/site_api_habits.py",
    "lambdas/web/site_api_journey.py",
    "lambdas/web/site_api_mind.py",
    "lambdas/web/site_stats_refresh_lambda.py",
}
# Evaluation, coach context, calibration, baselines and owner surfaces: they read the STORED method-1 fields, as of the
# date — a recalculation (which only adds the `public` attribute) can never change what they saw or what they grade.
METHOD1_ASOF_READERS = {
    "lambdas/coach/spiral_breaker.py",  # coach context
    "lambdas/compute/adaptive_mode_lambda.py",  # engagement score (owner brief)
    "lambdas/compute/daily_insight_compute_lambda.py",  # momentum (owner brief; public grounding drops it)
    "lambdas/compute/daily_metrics_compute_lambda.py",  # the producer
    "lambdas/compute/failure_pattern_compute_lambda.py",  # failure patterns (coach context)
    "lambdas/compute/hypothesis_engine_lambda.py",  # cross-pillar effect refit (calibration of the effects)
    "lambdas/ai/ai_calls.py",  # the daily brief's AI context
    "lambdas/content/output_writers.py",  # the owner dashboard (buddy is written from a public sheet by the caller)
    "lambdas/emails/monday_compass_lambda.py",
    "lambdas/emails/monthly_digest_lambda.py",
    "lambdas/emails/monthly_digest_render.py",
    "lambdas/emails/partner_email_lambda.py",
    "lambdas/emails/weekly_digest_extractors.py",
    "lambdas/emails/weekly_digest_lambda.py",
    "lambdas/intelligence/challenge_generator_lambda.py",  # challenge candidates (AI input; publication-gated separately)
    "lambdas/intelligence/field_notes_lambda.py",  # reads non-existent keys (dead read)
    "lambdas/operational/coherence_sentinel_lambda.py",
    "lambdas/operational/data_reconciliation_lambda.py",
    "lambdas/operational/pipeline_health_check_lambda.py",
    "lambdas/operational/qa_check_outputs.py",
    "lambdas/web/site_api_rollups.py",  # reads a key no record carries (overall_score): serves nothing from the sheet
}
# Name the partitions without reading them (registries, schemas, policy and the method modules themselves).
NOT_READERS = {
    "lambdas/common/activity_publication.py",
    "lambdas/common/compute_metadata.py",
    "lambdas/common/input_manifest.py",
    "lambdas/common/narrative_provenance.py",
    "lambdas/common/request_validator.py",
    "lambdas/experiment/phase_taxonomy.py",
    "lambdas/health/character_engine.py",
    "lambdas/health/public_corrections.py",
    "lambdas/ingestion/ingestion_validator.py",
    "lambdas/ingestion/source_registry.py",
    "lambdas/web/site_api_ledger.py",
    "lambdas/web/site_api_status.py",
}
_PARTITION = re.compile(r"""["'](character_sheet|day_grade)["']|SOURCE#(character_sheet|day_grade)|\}(character_sheet|day_grade)\b""")
_PUBLIC_ACCESS = ("public_sheet", "public_sheets", "public_event_sheets", "event_level", "public_grade", "public_score", "public_letter")


def _modules():
    files = sorted(glob.glob(os.path.join(ROOT, "lambdas", "**", "*.py"), recursive=True) + glob.glob(os.path.join(ROOT, "mcp", "*.py")))
    return {os.path.relpath(f, ROOT): open(f, encoding="utf-8").read() for f in files}


def test_every_reader_of_the_character_and_day_grade_partitions_is_classified():
    readers = {rel for rel, src in _modules().items() if _PARTITION.search(src)}
    known = PUBLIC_VARIANT_READERS | METHOD1_ASOF_READERS | NOT_READERS
    assert readers <= known, f"unclassified readers (public variant or method-1 as-of?): {sorted(readers - known)}"
    assert not (PUBLIC_VARIANT_READERS & METHOD1_ASOF_READERS)


def test_public_readers_read_the_public_variant_and_evaluation_readers_never_do():
    mods = _modules()
    for rel in PUBLIC_VARIANT_READERS:
        assert any(f in mods[rel] for f in _PUBLIC_ACCESS), f"{rel} must read the public variant"
    for rel in METHOD1_ASOF_READERS:
        assert not any(f"{f}(" in mods[rel] for f in _PUBLIC_ACCESS), f"{rel} is an as-of reader and must keep method 1"


def test_as_of_readers_see_the_method1_values_when_a_public_variant_sits_beside_them():
    """The recalculation only adds `public`: an evaluation reader reading the stored record sees method 1, unchanged."""
    from compute import daily_insight_compute_lambda as di
    from experiment import effect_fitter

    sheet = {"date": DAY, "pillar_mind": {"raw_score": 8.3}, B.PUBLIC: {"pillar_mind": {"raw_score": 60.3}}}
    assert effect_fitter._raw_score(sheet, "mind") == 8.3
    grades = [{"date": DAY, "total_score": 61, B.PUBLIC: {"total_score": 79}}]
    _sig, this_week, _prev, _t = di.compute_momentum(grades, DAY)
    assert this_week == 61.0


# ── invariance of every public value ────────────────────────────────────────────────────


def test_public_values_are_invariant_to_private_inputs_across_the_replayed_history(histories):
    quiet, private, q, p = histories
    for d in q:
        a, b = q[d]["public"], p[d]["public"]
        for k in ("character_level", "character_xp", "character_mood"):
            assert a.get(k) == b.get(k), (d, k)
        for pillar in ("mind", "consistency", "sleep", "movement", "nutrition", "metabolic", "relationships"):
            assert a[f"pillar_{pillar}"] == b[f"pillar_{pillar}"], (d, pillar)


def test_the_live_page_explains_the_jump_while_the_correction_is_recent():
    from web import site_api_character as C

    class _T:
        def __init__(self, item):
            self.item = item

        def get_item(self, Key):
            return {"Item": self.item} if self.item else {}

    live = _rec("2026-11-09", 21, "live")
    ledger = {"pk": "x", "sk": public_corrections.correction_sk(), "recalculated_on": "2026-11-08"}
    notice = character_privacy.PUBLIC_CORRECTION_NOTICE
    assert C._method_label(_T(ledger), live, "2026-11-09")["notice"] == notice
    assert C._method_label(_T(ledger), live, "2027-02-01")["notice"] is None  # past the window: no lingering notice
    assert C._method_label(_T(None), live, "2026-11-09")["notice"] is None  # no correction recorded: none claimed
    assert C._method_label(_T(None), _rec("2026-10-01", 9, "recomputed"), "2027-02-01")["notice"] == notice
