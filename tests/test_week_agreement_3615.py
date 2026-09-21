"""#3615 boxes 2+3 — the week-narration registry, the nightly agreement gate, and the absence half.

THE CLAUSE: "No page contradicts another page's account of the same week" had NO
instrument over its set. Every contradiction on the 2026-09-05 review (#3518, #3526,
#3520, #3521, #3515) was found by a human reading two pages side by side, and each fix
landed on its specimen. The absence half was the same: #3516/#3518 fixed two narrating
surfaces while agreement on a paused source's DURATION and CAUSE across the brief, the
coach summary, /api/status and the freshness board was unguarded.

WHAT THESE TESTS HOLD

  DERIVATION — `lambdas/{web,emails,compute,content,coach}` is swept for the fact-key
  literals. A module that restates a week fact must be a registered surface's producer or
  carry a reason in `UNREGISTERED_PRODUCERS`. A NEW narrating surface therefore cannot be
  born silent, which is the whole difference between this and a specimen fix.

  RATCHETS — `WEEK_SURFACES` may only grow; `UNREGISTERED_PRODUCERS` may only shrink.

  BEHAVIOUR — a contradiction is a FAIL naming both surfaces and both values; a dated
  fact from a different as-of is NOT a contradiction (an archive page is allowed to say
  "Week 2" forever); a rounded rendering inside tolerance is not a contradiction; a
  paused source narrated as a sync failure is a FAIL; a source PAST its declared cadence
  may still say it needs attention (this gate must never mute a real outage with a
  facet); and the copy the shipped producers now emit satisfies the gate.
"""

import json
from pathlib import Path

from ingestion.source_registry import availability_facet
from operational import week_agreement_qa as wq, week_narration_registry as reg
from operational.census_probe import ProbeBudget
from operational.qa_check import CONTENT_TRUTH, Check

REPO = Path(__file__).resolve().parent.parent

# Measured at landing (2026-09-21): 9 surfaces / 19 graded (surface, fact) pairs, read
# live in 10 HTTP fetches shared with the hook-liveness leg.
SURFACE_COUNT_FLOOR = 9
OBSERVATION_COUNT_FLOOR = 19
# SHRINK-ONLY: 12 producers restate a week fact with no nightly-fetchable artifact.
UNREGISTERED_PRODUCER_CEILING = 12


# ── the derivation sweep ─────────────────────────────────────────────────────
def week_fact_producers() -> dict:
    """{repo path: [fact key literals]} — every first-party module that renders a week fact."""
    found: dict = {}
    for directory in reg.PRODUCER_DIRS:
        for path in sorted((REPO / directory).glob("*.py")):
            text = path.read_text(encoding="utf-8", errors="replace")
            keys = sorted({k for k in reg.FACT_KEY_LITERALS if f'"{k}":' in text or f"'{k}':" in text})
            if keys:
                found[str(path.relative_to(REPO))] = keys
    return found


def registered_producers() -> set:
    """Every repo path claimed by a registered surface (the `::member` suffix stripped).

    Lives here, not in the registry: the derivation guard is its only caller and a public
    def under lambdas/ ships in every bundle (#781, tests/test_no_dead_shared_defs_3538.py).
    """
    out = set()
    for row in list(reg.WEEK_SURFACES) + list(reg.ABSENCE_SURFACES) + list(reg.RATE_CONSUMERS):
        out.add(row.producer.split("::")[0].split(" ")[0])
    return out


def test_the_producer_sweep_still_finds_producers():
    """A sweep that finds nothing passes forever — check it can still see."""
    producers = week_fact_producers()
    assert len(producers) >= 10, f"the producer sweep found only {len(producers)} modules — it has gone blind"
    assert "lambdas/web/site_api_journey.py" in producers


def test_every_week_fact_producer_is_registered_or_reasoned():
    registered = registered_producers()
    unexplained = {
        path: keys for path, keys in week_fact_producers().items() if path not in registered and path not in reg.UNREGISTERED_PRODUCERS
    }
    assert not unexplained, (
        "these modules restate a week fact and no instrument compares them to anything: "
        f"{unexplained} — register the served surface in WEEK_SURFACES, or record why it "
        "has no fetchable artifact in UNREGISTERED_PRODUCERS (lambdas/operational/week_narration_registry.py)"
    )


def test_the_exemption_set_only_shrinks_and_every_entry_is_real():
    assert len(reg.UNREGISTERED_PRODUCERS) <= UNREGISTERED_PRODUCER_CEILING, "an exemption was ADDED — give the surface an artifact instead"
    for path, reason in reg.UNREGISTERED_PRODUCERS.items():
        assert (REPO / path).exists(), f"{path} is exempted but does not exist — prune the entry"
        assert len(reason) > 30, f"{path} is exempted with no real reason"


def test_surface_registry_only_grows():
    assert len(reg.WEEK_SURFACES) >= SURFACE_COUNT_FLOOR
    assert sum(len(s.facts) for s in reg.WEEK_SURFACES) >= OBSERVATION_COUNT_FLOOR


def test_every_registered_fact_is_in_the_vocabulary_and_dated_facts_can_be_dated():
    for surface in reg.WEEK_SURFACES:
        for fact_id, ref in surface.facts:
            assert fact_id in reg.FACTS, f"{surface.id} declares unknown fact {fact_id!r}"
            if reg.FACTS[fact_id].dated:
                assert ref.as_of_path or surface.default_as_of_path or ref.transform, (
                    f"{surface.id}/{fact_id} is a DATED fact with no as-of source — it would be compared "
                    "against surfaces stamped on other days"
                )
            if ref.transform:
                assert ref.transform in wq._TRANSFORMS, f"{surface.id}/{fact_id}: unknown transform {ref.transform!r}"
        if surface.select:
            assert surface.select in wq._SELECTORS


def test_every_absence_surface_has_an_extractor():
    for surface in reg.ABSENCE_SURFACES:
        assert surface.extractor in wq._ABSENCE_EXTRACTORS


# ── the agreement gate ───────────────────────────────────────────────────────
def _payloads(**overrides):
    base = {
        "/api/journey": {
            "_meta": {"generated_at": "2026-09-21T02:00:00+00:00"},
            "journey": {
                "started_date": "2026-09-06",
                "start_weight_lbs": 327.3,
                "goal_weight_lbs": 185.0,
                "current_weight_lbs": 316.9,
                "last_weighin_date": "2026-09-20",
                "day_n": 15,
                "week_n": 3,
                "weekly_rate_lbs": -5.63,
                "weighin_count": 7,
                "rate_provisional": True,
            },
        },
        "/api/timeline": {
            "_meta": {"generated_at": "2026-09-21T02:00:00+00:00"},
            "timeline": {
                "journey_start": "2026-09-06",
                "start_weight": 327.3,
                "goal_weight": 185.0,
                "weights": [{"date": "2026-09-06", "lbs": 327.3}, {"date": "2026-09-20", "lbs": 316.9}],
            },
        },
        "/api/pulse": {"_meta": {"generated_at": "2026-09-21T02:00:00+00:00"}, "pulse": {"day_number": 15, "date": "2026-09-20"}},
        "/api/fingerprint": {
            "_meta": {"generated_at": "2026-09-21T02:00:00+00:00"},
            "fingerprint": {"day_number": 15, "date": "2026-09-20"},
        },
        "/api/snapshot": {
            "vitals": {"_meta": {"generated_at": "2026-09-21T02:00:00+00:00"}, "vitals": {"weight_lbs": 317, "weight_as_of": "2026-09-20"}}
        },
        "/api/recap": {"_meta": {"generated_at": "2026-09-19T02:00:00+00:00"}, "recap": {"as_of": "2026-09-15", "as_of_week": 2.0}},
        "/journal/posts.json": {
            "posts": [
                {
                    "date": "2026-09-15",
                    "sequence": 5,
                    "label": "Week 2",
                    "url": "/journal/posts/week-05/",
                    "stats_line": "Weight: 318.9 lbs | Week Grade: avg 63",
                }
            ]
        },
        "/moments/share-kits/week-05/kit.json": {
            "label": "Week 2",
            "date": "2026-09-15",
            "stats_line": "Weight: 318.9 lbs | Week Grade: avg 63",
        },
        "/api/source_freshness": {
            "_meta": {"generated_at": "2026-09-21T02:00:00+00:00"},
            "experiment": {"genesis": "2026-09-06"},
            "sources": [],
        },
        "/api/status": {"groups": []},
    }
    for path, payload in overrides.items():
        base[path] = payload
    return base


def _budget(payloads):
    def opener(url, timeout):
        for path, payload in payloads.items():
            if url.endswith(path):
                return 200, json.dumps(payload)
        return 404, '{"error": "Not found"}'

    return ProbeBudget(opener=opener)


def _run(check_fn, payloads, **kwargs):
    return check_fn(Check, CONTENT_TRUTH, site_base_url="https://site", budget=_budget(payloads), **kwargs)[0]


def test_agreeing_surfaces_are_green():
    check = _run(wq.check_week_agreement, _payloads())
    assert check.passed is True, check.message
    assert "agree across" in check.message


def test_a_contradicting_day_n_is_a_FAIL_naming_both_surfaces():
    payloads = _payloads()
    payloads["/api/pulse"]["pulse"]["day_number"] = 14
    check = _run(wq.check_week_agreement, payloads)
    assert check.passed is False
    assert "api_journey" in check.message and "api_pulse" in check.message and "day" in check.message.lower()


def test_a_contradicting_baseline_weight_is_a_FAIL():
    payloads = _payloads()
    payloads["/api/timeline"]["timeline"]["start_weight"] = 314.0
    check = _run(wq.check_week_agreement, payloads)
    assert check.passed is False and "baseline" in check.message


def test_an_archive_page_on_an_older_week_is_not_a_contradiction():
    """journal_manifest says Week 2 as-of 09-15 while /api/journey says Week 3 today —
    both true. A gate that reds here is a gate somebody mutes."""
    check = _run(wq.check_week_agreement, _payloads())
    assert check.passed is True


def test_two_surfaces_disagreeing_about_the_SAME_week_is_a_FAIL():
    payloads = _payloads()
    payloads["/moments/share-kits/week-05/kit.json"]["label"] = "Week 3"
    check = _run(wq.check_week_agreement, payloads)
    assert check.passed is False and "share_kit" in check.message and "journal_manifest" in check.message


def test_a_rounded_weight_inside_tolerance_agrees():
    """/api/snapshot renders 317 for the same 316.9 /api/journey serves."""
    observations, _, _ = wq.observe(_budget(_payloads()), "https://site")
    weights = [o for o in observations if o.fact == reg.FACT_CURRENT_WEIGHT and o.as_of == "2026-09-20"]
    assert {o.surface for o in weights} >= {"api_journey", "api_snapshot", "api_timeline"}
    assert not wq.disagreements(observations)


def test_a_half_pound_past_tolerance_is_a_FAIL():
    payloads = _payloads()
    payloads["/api/snapshot"]["vitals"]["vitals"]["weight_lbs"] = 318.0
    check = _run(wq.check_week_agreement, payloads)
    assert check.passed is False and "api_snapshot" in check.message


def test_an_unreachable_surface_is_a_WARN_never_a_silent_pass():
    payloads = _payloads()
    del payloads["/api/pulse"]
    check = _run(wq.check_week_agreement, payloads)
    assert check.passed is None and "NOT OBSERVED" in check.message and "api_pulse" in check.message


def test_a_withheld_fact_is_reported_by_name_as_a_warn():
    payloads = _payloads()
    payloads["/api/journey"]["journey"]["current_weight_lbs"] = None
    check = _run(wq.check_week_agreement, payloads)
    assert check.passed is None and "not rendered" in check.message


# ── box 3: the absence half ──────────────────────────────────────────────────
def _absence_payloads(status_comment, freshness_row=None, source="garmin", rel="97d ago", comp_status="yellow"):
    payloads = _payloads()
    payloads["/api/status"] = {
        "groups": [
            {"components": [{"id": source, "status": comp_status, "last_sync_relative": rel, "comment": status_comment, "description": ""}]}
        ]
    }
    payloads["/api/source_freshness"]["sources"] = [freshness_row] if freshness_row else []
    return payloads


def _run_absence(payloads):
    return wq.check_absence_agreement(Check, CONTENT_TRUTH, None, site_base_url="https://site", budget=_budget(payloads))[0]


def test_a_paused_source_narrated_as_a_sync_failure_is_a_FAIL():
    """The live 2026-09-21 copy, verbatim — garmin is paused by ADR-074 and cannot report."""
    check = _run_absence(_absence_payloads("Pipeline may need attention — was flowing regularly but stopped 97d ago. Check auth/webhook."))
    assert check.passed is False
    assert "garmin" in check.message and "broken pipe" in check.message


def test_a_paused_source_with_no_duration_is_a_FAIL():
    row = {"id": "garmin", "status": "paused", "desc": "Biometrics — paused (vendor anti-automation, ADR-074)"}
    check = _run_absence(_absence_payloads("PAUSED in the source registry — paused. Last record: 97d ago.", freshness_row=row))
    assert check.passed is False and "renders NO duration" in check.message


def test_the_shipped_status_comment_satisfies_the_gate():
    """The producer fix in this PR, graded by the gate in this PR — the whole point of
    deriving both from `availability_facet()`. It fails against the pre-PR copy, which
    said "Pipeline may need attention … Check auth/webhook." about a source paused by
    ADR-074 (measured live 2026-09-21)."""
    from web.site_api_status import _absence_comment

    facet = availability_facet("garmin")
    comment = _absence_comment(facet, "97d ago")
    assert wq._cause_verdict(facet, comment, 97.0) is None, comment
    assert "paus" in comment.lower()
    assert "97d" in comment, "the cause without a duration is half the story"


def test_a_lagging_source_PAST_its_cadence_may_still_say_it_needs_attention():
    """This gate must never become the thing that hides an outage behind a facet."""
    facet = {"status": "lagging", "reason": "manual end-of-day upload", "lag_hours": 96}
    assert wq._cause_verdict(facet, "Pipeline may need attention — stopped 20d ago. Check auth/webhook.", 20.0) is None


def test_a_lagging_source_INSIDE_its_cadence_is_a_WARN_not_a_FAIL():
    """The panel's "an API poller writes daily" heuristic and the registry's per-source
    cadence are both defensible; the census names the source nightly and leaves the
    ruling to the owner (#3615 residual) instead of reddening on a product question."""
    facet = {"status": "lagging", "reason": "manual end-of-day upload", "lag_hours": 96}
    severity, message = wq._cause_verdict(facet, "Pipeline may need attention — stopped 2d ago. Check auth/webhook.", 2.0)
    assert severity == "warn" and "broken pipe" in message


def test_a_paused_source_contradiction_is_FAIL_severity():
    facet = availability_facet("garmin")
    severity, _message = wq._cause_verdict(facet, "Pipeline may need attention — stopped 97d ago. Check auth/webhook.", 97.0)
    assert severity == "fail", "a source that CANNOT report has no auth to check — this one is not a judgement call"


def test_surfaces_disagreeing_on_how_long_a_source_has_been_silent_is_a_FAIL():
    row = {"id": "garmin", "status": "paused", "desc": "paused (ADR-074)", "days_dark": 30, "last_update": "2026-08-21"}
    payloads = _absence_payloads("PAUSED in the source registry — paused (ADR-074). Last record: 97d ago.", freshness_row=row)
    check = _run_absence(payloads)
    assert check.passed is False and "how long" in check.message


def test_month_granularity_is_not_a_disagreement():
    """176 days rendered as '5mo ago' on one surface is the same silence, not a second one."""
    row = {"id": "garmin", "status": "paused", "desc": "paused (ADR-074)", "days_dark": 176, "last_update": "2026-03-28"}
    payloads = _absence_payloads(
        "PAUSED in the source registry — paused (ADR-074). Last record: 5mo ago.", freshness_row=row, rel="5mo ago"
    )
    check = _run_absence(payloads)
    assert check.passed is True, check.message


def test_a_never_rendering_is_an_honest_duration():
    rows = wq._extract_status_components(
        {"groups": [{"components": [{"id": "x", "status": "blue", "last_sync_relative": "never", "comment": "c"}]}]}
    )
    assert rows["x"]["duration_rendered"] is True and rows["x"]["duration_days"] is None


def test_relative_durations_parse_the_way_the_panel_renders_them():
    assert wq._relative_to_days("97d ago") == 97.0
    assert wq._relative_to_days("5mo ago") == 150.0
    assert wq._relative_to_days("yesterday") == 1.0
    assert wq._relative_to_days("today") == 0.0
    assert wq._relative_to_days("") is None


# ── box 3, second clause: a rate carries its n ───────────────────────────────
def test_a_rate_with_n_and_provisional_is_green():
    check = _run(wq.check_rate_disclosure, _payloads())
    assert check.passed is True


def test_a_rate_without_n_is_a_FAIL():
    payloads = _payloads()
    payloads["/api/journey"]["journey"]["weighin_count"] = None
    check = _run(wq.check_rate_disclosure, payloads)
    assert check.passed is False and "NO n" in check.message


def test_a_rate_without_a_provisional_flag_is_a_FAIL():
    payloads = _payloads()
    payloads["/api/journey"]["journey"]["rate_provisional"] = None
    check = _run(wq.check_rate_disclosure, payloads)
    assert check.passed is False and "provisional" in check.message


def test_no_rate_rendered_is_not_a_finding():
    payloads = _payloads()
    payloads["/api/journey"]["journey"]["weekly_rate_lbs"] = None
    payloads["/api/journey"]["journey"]["weighin_count"] = None
    check = _run(wq.check_rate_disclosure, payloads)
    assert check.passed is True


def test_the_three_verdicts_share_one_read_budget():
    payloads = _payloads()
    budget = _budget(payloads)
    checks = wq.checks(Check, CONTENT_TRUTH, None, site_base_url="https://site", budget=budget)
    assert [c.name for c in checks] == ["weeks:fact_agreement", "weeks:absence_agreement", "weeks:rate_disclosure"]
    assert budget.requests <= 12, f"{budget.requests} reads — the census must stay key-bounded (#3615)"


def test_the_gate_is_wired_into_the_nightly_sweep():
    import os

    os.environ.setdefault("S3_BUCKET", "test-bucket")
    os.environ.setdefault("EMAIL_RECIPIENT", "qa@example.com")
    os.environ.setdefault("EMAIL_SENDER", "qa@example.com")
    import qa_smoke_lambda

    labels = [label for label, _fn in qa_smoke_lambda.check_steps()]
    assert "week_narration_agreement" in labels
