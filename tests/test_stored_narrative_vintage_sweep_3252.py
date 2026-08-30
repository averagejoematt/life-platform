"""tests/test_stored_narrative_vintage_sweep_3252.py — the #3252 sibling sweep:
every stored-narrative endpoint declares its content vintage (ADR-104).

#3268/#3252 fixed /api/coaching-dashboard + /api/weekly_priority and the verdict
was "reported, not swept": the same defect class — an endpoint that serves a
STORED narrative/compute record while its envelope wears the request instant —
was still live on six sibling handlers. Three of them (`/api/forecast`,
`/api/scenarios`, `/api/state_of_matthew`) actively STRIP the record's
`computed_at` via `_INTERNAL`, so the generation instant never reached a reader
at all; `/api/state_of_matthew` is the worst instance — a weekly-recomputed,
budget-pausable (ADR-125 tier >= 2) narrative with no vintage anywhere.

The fix pattern is the existing one, not a new convention:
`_ok(..., content_as_of=content_vintage(*stamps))` — the canonical call is
site_api_coach_narrative.handle_weekly_priority. Where a handler assembles
MULTIPLE stored records, every constituent stamp is passed and content_vintage
reports the OLDEST: an envelope may not claim more freshness than its stalest
member (the whole rule, pinned by test_paused_envelope_vintage_3252.py).

Fixture discipline (the wire, not a guess): every timestamp field name below is
copied from the WRITER that stamps it —

  * `computed_at`   — common.compute_metadata.tag_record (forecast_engine_lambda,
                      scenario_explorer_lambda, state_of_matthew_lambda all tag);
  * `generated_at`  — emails/chronicle_recap.py:236 (RECAP#latest) and
                      intelligence/ai_expert_analyzer_lambda (EXPERT#integrator,
                      EXPERT#integrator_month);
  * `created_at`    — coach/coach_state_updater (OUTPUT# rows) and
                      coach/coach_ensemble_digest (ENSEMBLE digest).

All are `datetime.now(timezone.utc).isoformat()` — microseconds + a literal
`+00:00`, the shape a hand-written fixture reliably gets wrong.

`_INTERNAL` semantics are NOT relaxed: pk/sk/run_id/phase/cycle/record_type and
`computed_at` itself stay out of the payload body — the vintage surfaces only in
`_meta.content_as_of` (and `_meta.generated_at`, whose name always promised it).
"""

import json
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from fakes import FakeDdbTable  # noqa: E402
from web import (  # noqa: E402
    site_api_coach as coach,
    site_api_common as common,
    site_api_intelligence as intel,
)

# ── the wire shapes ───────────────────────────────────────────────────────────

FORESIGHT_COMPUTED_AT = "2026-08-26T13:05:11.482913+00:00"  # tag_record's stamp
RECAP_GENERATED_AT = "2026-08-25T18:40:02.118274+00:00"  # chronicle_recap commit
ROLLUP_GENERATED_AT = "2026-08-24T17:12:44.902100+00:00"  # ai_expert_analyzer month cache

# handle_coach_analysis assembles three stored records; the ensemble digest is
# deliberately the OLDEST so the multi-record rule is what the assertion proves.
OUTPUT_CREATED_AT = "2026-08-26T17:02:28.557831+00:00"  # coach_state_updater OUTPUT#
INTEGRATOR_GENERATED_AT = "2026-08-27T14:02:46.793290+00:00"  # EXPERT#integrator
ENSEMBLE_CREATED_AT = "2026-08-23T19:30:09.331245+00:00"  # coach_ensemble_digest


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _past_genesis(monkeypatch, days=30):
    start = (datetime.now(common.PT).date() - timedelta(days=days)).isoformat()
    for mod in (common, intel, coach):
        monkeypatch.setattr(mod, "EXPERIMENT_START", start, raising=False)
    return start


# ── /api/forecast, /api/scenarios, /api/state_of_matthew ─────────────────────
# The three foresight singletons. Each row carries tag_record's real stamps
# (run_id + computed_at + phase); the handler strips them from the BODY and must
# now declare computed_at as the envelope's vintage.


def _foresight_row(source, record_type, **over):
    row = {
        "pk": f"USER#matthew#SOURCE#{source}",
        "sk": "DATE#2026-08-26",
        "record_type": record_type,
        "date": "2026-08-26",
        "run_id": "b2b0c5f4-run",
        "computed_at": FORESIGHT_COMPUTED_AT,
        "phase": "experiment",
    }
    row.update(over)
    return row


def test_forecast_declares_the_records_computed_at(monkeypatch):
    _past_genesis(monkeypatch)
    row = _foresight_row("forecast", "forecast_summary", forecasts=[], resolutions_today=[], coverage={})
    monkeypatch.setattr(intel, "table", FakeDdbTable(rows=[row]))
    body = _body(intel.handle_forecast())
    assert body["available"] is True
    assert body["_meta"]["content_as_of"] == FORESIGHT_COMPUTED_AT
    assert body["_meta"]["generated_at"] == FORESIGHT_COMPUTED_AT
    # _INTERNAL semantics untouched — the stamp surfaces in _meta, never the body.
    for k in ("pk", "sk", "run_id", "computed_at", "phase", "record_type"):
        assert k not in body


def test_scenarios_declares_the_records_computed_at(monkeypatch):
    _past_genesis(monkeypatch)
    row = _foresight_row("scenarios", "scenario_summary", levers=[], window_days=60)
    monkeypatch.setattr(intel, "table", FakeDdbTable(rows=[row]))
    body = _body(intel.handle_scenarios())
    assert body["available"] is True
    assert body["_meta"]["content_as_of"] == FORESIGHT_COMPUTED_AT
    assert body["_meta"]["generated_at"] == FORESIGHT_COMPUTED_AT
    assert "computed_at" not in body


def test_state_of_matthew_declares_the_records_computed_at(monkeypatch):
    """The worst instance of the class: a weekly-recomputed, budget-pausable
    narrative that surfaced NO generation instant at all — while regeneration is
    paused the brief freezes and the envelope's stamp did not."""
    _past_genesis(monkeypatch)
    row = _foresight_row(
        "state_of_matthew",
        "state_of_matthew_brief",
        narrative="The model held its calibration through a quiet week.",
        narrated=True,
        sections_available={"forecast": True},
    )
    monkeypatch.setattr(intel, "table", FakeDdbTable(rows=[row]))
    body = _body(intel.handle_state_of_matthew())
    assert body["available"] is True
    assert body["narrative"].startswith("The model held")
    assert body["_meta"]["content_as_of"] == FORESIGHT_COMPUTED_AT
    assert body["_meta"]["generated_at"] == FORESIGHT_COMPUTED_AT
    assert "computed_at" not in body


def test_foresight_empty_states_declare_no_vintage(monkeypatch):
    """`available: False` has no stored content to date — absent means UNKNOWN,
    never a fabricated stamp (#1971)."""
    _past_genesis(monkeypatch)
    monkeypatch.setattr(intel, "table", FakeDdbTable(rows=[]))
    for handler in (intel.handle_forecast, intel.handle_scenarios, intel.handle_state_of_matthew):
        body = _body(handler())
        assert body["available"] is False
        assert "content_as_of" not in body["_meta"]
        assert body["_meta"]["generated_at"] == body["_meta"]["served_at"]


# ── /api/recap ────────────────────────────────────────────────────────────────


def _recap_row(**over):
    row = {
        "pk": f"{coach.USER_PREFIX}chronicle",
        "sk": "RECAP#latest",
        "story_so_far": "Fourteen days of holding the line.",
        "recent_beats": ["The reset landed."],
        "where_we_are_now": "Week two.",
        "threads_to_watch": [],
        "as_of": "2026-08-25",
        "as_of_week": 2,
        "author": "Elena Voss",
        "experiment_day": 9,
        "generated_at": RECAP_GENERATED_AT,
    }
    row.update(over)
    return row


def test_recap_declares_the_stored_records_generated_at(monkeypatch):
    _past_genesis(monkeypatch)
    monkeypatch.setattr(coach, "table", FakeDdbTable(store_items=[_recap_row()]))
    monkeypatch.setattr(coach, "_current_day_n", lambda: 12)
    monkeypatch.setattr(coach, "_regeneration_paused", lambda feature: False)
    body = _body(coach.handle_recap())
    assert body["recap"]["story_so_far"].startswith("Fourteen")
    assert body["_meta"]["content_as_of"] == RECAP_GENERATED_AT
    assert body["_meta"]["generated_at"] == RECAP_GENERATED_AT


def test_recap_honest_null_declares_no_vintage(monkeypatch):
    _past_genesis(monkeypatch)
    monkeypatch.setattr(coach, "table", FakeDdbTable(store_items=[]))
    monkeypatch.setattr(coach, "_current_day_n", lambda: 12)
    body = _body(coach.handle_recap())
    assert body["recap"] is None
    assert "content_as_of" not in body["_meta"]


# ── /api/coach_analysis ───────────────────────────────────────────────────────


def _output_row(**over):
    row = {
        "pk": "COACH#sleep_coach",
        "sk": "OUTPUT#2026-08-26#daily_brief_sleep",
        "created_at": OUTPUT_CREATED_AT,
        "content": "The sleep read, written on 2026-08-26.",
        "public_summary": "Matthew's sleep signal held steady through the window.",
        "confidence": 0.8,
    }
    row.update(over)
    return row


def _integrator_item():
    return {
        "expert_key": "integrator",
        "generated_at": INTEGRATOR_GENERATED_AT,
        "analysis": "Hold the sleep window; everything else follows.",
        "cross_domain_notes": {"sleep": "Sleep architecture continues to favor early wake."},
    }


def _ensemble_digest(coaches=("sleep_coach", "nutrition_coach")):
    return {
        "created_at": ENSEMBLE_CREATED_AT,
        "active_disagreements": [{"topic": "zone-2 volume vs recovery debt", "coaches": list(coaches)}],
    }


def _run_coach_analysis(monkeypatch, digest_coaches=("sleep_coach", "nutrition_coach")):
    _past_genesis(monkeypatch)
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=[_output_row()]))
    monkeypatch.setattr(coach, "_integrator_digest", lambda: _integrator_item())
    monkeypatch.setattr(coach, "_latest_cycle_digest", lambda: _ensemble_digest(digest_coaches))
    monkeypatch.setattr(coach, "_regeneration_paused", lambda feature: True)
    return _body(coach.handle_coach_analysis({"queryStringParameters": {"domain": "sleep"}}))


def test_coach_analysis_vintage_is_the_oldest_constituent(monkeypatch):
    """Three stored records land in this response — the coach's OUTPUT# row, the
    integrator's cross-domain note, the ensemble digest's disagreement topic. The
    envelope reports the OLDEST (here the ensemble digest), never the newest and
    never the request instant: the freshest member must not launder the rest."""
    body = _run_coach_analysis(monkeypatch)
    assert body["cross_coach_reference"] == "zone-2 volume vs recovery debt"
    assert body["cross_domain_note"].startswith("Sleep architecture")
    assert body["weekly_priority"].startswith("Hold the sleep window")
    stamps = [OUTPUT_CREATED_AT, INTEGRATOR_GENERATED_AT, ENSEMBLE_CREATED_AT]
    assert body["_meta"]["content_as_of"] == ENSEMBLE_CREATED_AT == common.content_vintage(*stamps)
    assert body["_meta"]["generated_at"] == ENSEMBLE_CREATED_AT


def test_coach_analysis_ignores_a_digest_whose_content_did_not_land(monkeypatch):
    """The same digest with no disagreement involving this coach contributes NO
    prose to the payload, so its (older) stamp may not backdate the envelope —
    the vintage set is what the reader actually reads, not what the handler
    happened to fetch."""
    body = _run_coach_analysis(monkeypatch, digest_coaches=("nutrition_coach", "mind_coach"))
    assert "cross_coach_reference" not in body
    assert body["_meta"]["content_as_of"] == OUTPUT_CREATED_AT, "oldest of the records that DID land (output < integrator)"


# ── /api/month_rollup ─────────────────────────────────────────────────────────


def _rollup_row(**over):
    row = {
        "pk": f"{coach.USER_PREFIX}ai_analysis",
        "sk": "EXPERT#integrator_month",
        "expert_key": "integrator_month",
        "narrative": "Four weeks of the same honest pattern: training held, logging wobbled.",
        "headline": "A month of holding the line",
        "week_count": 4,
        "window_label": "2026-07-27 to 2026-08-23",
        "days_in_experiment": 8,
        "generated_at": ROLLUP_GENERATED_AT,
    }
    row.update(over)
    return row


def test_month_rollup_declares_the_stored_records_generated_at(monkeypatch):
    _past_genesis(monkeypatch)
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=[_rollup_row()]))
    monkeypatch.setattr(coach, "_current_day_n", lambda: 30)
    body = _body(coach.handle_month_rollup())
    assert body["narrative"].startswith("Four weeks")
    assert body["generated_at"] == ROLLUP_GENERATED_AT
    assert body["_meta"]["content_as_of"] == ROLLUP_GENERATED_AT
    assert body["_meta"]["generated_at"] == ROLLUP_GENERATED_AT


def test_month_rollup_honest_null_declares_no_vintage(monkeypatch):
    _past_genesis(monkeypatch)
    monkeypatch.setattr(coach, "table", FakeDdbTable(rows=[]))
    monkeypatch.setattr(coach, "_current_day_n", lambda: 30)
    body = _body(coach.handle_month_rollup())
    assert body["narrative"] is None
    assert "content_as_of" not in body["_meta"]


# ── served_at survives on every swept endpoint ────────────────────────────────


def test_served_at_still_carries_the_request_instant_on_a_swept_endpoint(monkeypatch):
    """The one honest use of request time ('is the API answering?') is named, not
    deleted — a sweep that renamed the field would lose it (property 4 of the
    canonical #3252 suite)."""
    _past_genesis(monkeypatch)
    row = _foresight_row("forecast", "forecast_summary", forecasts=[])
    monkeypatch.setattr(intel, "table", FakeDdbTable(rows=[row]))
    meta = _body(intel.handle_forecast())["_meta"]
    assert meta["served_at"] > meta["generated_at"], "served_at is now; generated_at is the frozen content"
    now = datetime.now(common.timezone.utc)
    served = datetime.fromisoformat(meta["served_at"])
    assert abs((now - served).total_seconds()) < 120
