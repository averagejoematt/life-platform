"""tests/test_cross_phase_framing_2957_remaining.py — #2957/#2958: the members
PR #3074 deliberately left baselined.

#3074 built the shared `lambdas/web/site_api_phase_frame.py` vocabulary and drained
six producers with it. It named five surfaces still carrying the class, plus a sixth
(`/method/verify/`) landed on the baseline the next day (comment thread on #2957):

  * `/method/postmortems/` + `/method/survival/` + `/story/attempts/` — the
    live-cycle-as-closed sibling (folded #2958): a page whose whole subject is
    "what each DEAD cycle taught" gives the reader no signal that the excluded
    live cycle is ALIVE, not simply unwritten yet.
  * `/method/voicefidelity/` — `N=16` judgments, a cross-phase accumulator
    (`VOICEFIDELITY#` never resets at a restart — PHASE_TAXONOMY.md) rendered with
    no scope word, so it reads as this cycle's own count.
  * `/method/wrong/` — the validator-catch table's 120-day window reaches well past
    the live genesis; two rows from cycle 14 sit beside two from a cycle that ended
    months earlier with no cycle label distinguishing them.
  * `/method/verify/` — the Whoop-vs-Garmin table's dates (2026-04-29 to
    2026-06-15, frozen since the Garmin pause) render with a pause explanation but
    no cycle/phase framing of the window itself.

These tests pin the producer half for the remaining members — the labels the
endpoints now emit, reusing `site_api_phase_frame`'s existing `archival_frame`
(wrong, verify) and its new `lifetime_scope()` (voicefidelity), plus one new
producer-computed sentence (`survival()`'s `in_progress_note`, which
`/method/postmortems/` reads off the same payload). The front-end halves (the
postmortems footer note, the wrong-page date badge, the verify table caption, the
voicefidelity figure) are pinned by the render sweep, not here — same split
`test_cross_phase_framing_2957.py` already established.

`/method/survival/` and `/story/attempts/` needed no code change — a live
reader-truth sweep run while diagnosing this found both already render the live
cycle correctly ("day N · live" / "live — day N."); their baseline entries retire
as a hand-shrink backed by that observation, not a producer diff.

Dates are always derived from a live now(PT) — never wall-clock literals
(reference_golden_tests_wallclock).
"""

import json
import os
import sys
from datetime import datetime, timedelta

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import (  # noqa: E402
    site_api_coach as coach_api,  # noqa: E402
    site_api_common as common,  # noqa: E402
    site_api_freshness as freshness,  # noqa: E402
    site_api_intelligence as intel,  # noqa: E402
    site_api_phase_frame as phase_frame,  # noqa: E402
    site_api_rollups,  # noqa: E402
)


def _today_pt():
    return datetime.now(common.PT).date()


def _iso(d):
    return d.strftime("%Y-%m-%d")


# ── the vocabulary's one new word ─────────────────────────────────────────────


class TestLifetimeScopeVocabulary:
    def test_lifetime_scope_is_all_cycles(self):
        assert phase_frame.lifetime_scope() == "all cycles"


# ── /method/postmortems/ (+ /method/survival/): the live cycle is IN PROGRESS ─


def _survival(geneses):
    def _query_source(source, start, end, include_pilot=False):
        return []

    return site_api_rollups.survival(_g={"CYCLE_GENESES": geneses, "_query_source": _query_source})


class TestSurvivalInProgressNote:
    def test_the_live_cycle_gets_an_in_progress_sentence(self):
        """The live finding: postmortems reads the same payload's `in_progress_note`
        so the two pages can't disagree about whether cycle 14 is alive."""
        today = _today_pt()
        g_old = (today - timedelta(days=400)).isoformat()
        g_now = (today - timedelta(days=7)).isoformat()  # Day 8
        resp = _survival({13: g_old, 14: g_now})
        assert resp["statusCode"] == 200, resp
        body = json.loads(resp["body"])
        assert body["in_progress_note"] is not None
        assert "Cycle 14 is still running (day 8)" in body["in_progress_note"], body["in_progress_note"]
        assert "post-mortem" in body["in_progress_note"]

    def test_the_note_names_whichever_cycle_is_actually_live(self):
        """Not a hardcoded '14' — the note derives from the max genesis, same as
        every other current-cycle computation on this endpoint."""
        today = _today_pt()
        g_now = (today - timedelta(days=2)).isoformat()  # Day 3
        resp = _survival({1: g_now})
        body = json.loads(resp["body"])
        assert "Cycle 1 is still running (day 3)" in body["in_progress_note"], body["in_progress_note"]


# ── /method/wrong/: a validator catch says which cycle it's from ─────────────


def _cond_values(cond):
    """Recursively walk a boto3 ConditionBase's private `_values` — the same
    introspection `test_cross_phase_framing_2957.py::_PulseTable` uses to tell
    apart the different table.query() shapes a facade issues on one fake table."""
    vals = getattr(cond, "_values", None)
    if vals is None:
        return
    for v in vals:
        if hasattr(v, "_values"):
            yield from _cond_values(v)
        else:
            yield v


class _WrongTable:
    """wrong() issues two query shapes against the same table: the
    `intelligence_quality` validator-catch scan (which this fake actually answers)
    and a per-coach `LEARNING#` ledger scan (answered empty — irrelevant to the
    catches this test pins). get_item is deliberately unimplemented: the
    `effect_fitter.load_latest_fit` call it would back is wrapped in its own
    non-fatal try/except in `wrong()`."""

    def __init__(self, intelligence_rows):
        self.intelligence_rows = intelligence_rows

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        vals = list(_cond_values(cond)) if cond is not None else []
        if any(isinstance(v, str) and "intelligence_quality" in v for v in vals):
            return {"Items": list(self.intelligence_rows)}
        return {"Items": []}


class TestWrongValidatorArchival:
    def test_a_pre_genesis_catch_is_framed_as_previous_cycle(self, monkeypatch):
        """The live finding, reproduced: catches dated 2026-06-18/2026-05-19 sat
        unlabeled beside a Day-8 header."""
        genesis = _iso(_today_pt() - timedelta(days=7))  # Day 8
        old_date = _iso(_today_pt() - timedelta(days=60))
        rows = [
            {
                "pk": "USER#matthew",
                "sk": f"SOURCE#intelligence_quality#{old_date}",
                "date": old_date,
                "coach_id": "labs_coach",
                "checks_run": 3,
                "errors": [{"detail": "stale lab data"}],
            }
        ]
        monkeypatch.setattr(intel, "table", _WrongTable(rows))
        monkeypatch.setattr(intel, "EXPERIMENT_START", genesis)
        resp = intel.handle_wrong()
        assert resp["statusCode"] == 200, resp
        body = json.loads(resp["body"])
        (catch,) = body["validator"]["recent"]
        assert catch["archival"]["pre_cycle"] is True
        assert genesis in catch["archival"]["label"], catch["archival"]["label"]

    def test_an_in_cycle_catch_carries_no_archival_key(self, monkeypatch):
        genesis = _iso(_today_pt() - timedelta(days=7))
        recent_date = _iso(_today_pt() - timedelta(days=1))
        rows = [
            {
                "pk": "USER#matthew",
                "sk": f"SOURCE#intelligence_quality#{recent_date}",
                "date": recent_date,
                "coach_id": "nutrition_coach",
                "checks_run": 2,
                "flags": [{"detail": "duplicate suggestion"}],
            }
        ]
        monkeypatch.setattr(intel, "table", _WrongTable(rows))
        monkeypatch.setattr(intel, "EXPERIMENT_START", genesis)
        resp = intel.handle_wrong()
        body = json.loads(resp["body"])
        (catch,) = body["validator"]["recent"]
        assert "archival" not in catch or catch["archival"] is None, catch


# ── /method/verify/: the comparison window says which cycle it's from ────────


class TestDeviceAgreementArchivalFraming:
    def test_a_window_that_ends_before_genesis_is_framed_as_previous_cycle(self):
        """The live finding: Garmin's paused since 2026-06, so the whole 'night by
        night' window predates a cycle-14 genesis of 2026-08-17 — reproduced here
        with a relative genesis so the test never goes wall-clock stale."""
        genesis = _iso(_today_pt() - timedelta(days=7))
        last_night = _iso(_today_pt() - timedelta(days=70))

        def _query_source(source, start, end, include_pilot=False):
            return [{"date": last_night, "resting_heart_rate": 60.0 if source == "whoop" else 58.0}]

        resp = freshness.device_agreement(_g={"_query_source": _query_source, "EXPERIMENT_START": genesis})
        assert resp["statusCode"] == 200, resp
        body = json.loads(resp["body"])
        assert body["archival"]["pre_cycle"] is True
        assert genesis in body["archival"]["label"], body["archival"]["label"]

    def test_a_window_reaching_into_the_live_cycle_carries_no_archival_frame(self):
        genesis = _iso(_today_pt() - timedelta(days=7))
        recent_night = _iso(_today_pt() - timedelta(days=1))

        def _query_source(source, start, end, include_pilot=False):
            return [{"date": recent_night, "resting_heart_rate": 60.0 if source == "whoop" else 58.0}]

        resp = freshness.device_agreement(_g={"_query_source": _query_source, "EXPERIMENT_START": genesis})
        body = json.loads(resp["body"])
        assert body["archival"] is None, body["archival"]


# ── /method/voicefidelity/: the scoreboard says its own scope ────────────────


class TestVoiceFidelityLifetimeScope:
    def test_a_scored_board_carries_the_all_cycles_scope(self, monkeypatch):
        item = {
            "pk": "VOICEFIDELITY#scoreboard",
            "sk": "latest",
            "n": 16,
            "correct": 11,
            "accuracy_pct": 68.8,
            "chance_accuracy_pct": 12.5,
            "candidate_pool_size": 8,
            "per_coach": [{"coach_id": "labs_coach", "n": 2, "correct": 2, "accuracy_pct": 100.0, "distinguishability": "distinguishable"}],
            "confusion": {},
            "worst_confused_pair": None,
            "verdict": "distinguishable",
            "run_month": "2026-08",
            "updated_at": "2026-08-01T00:00:00+00:00",
        }
        monkeypatch.setattr(coach_api, "table", FakeDdbTable(store_items=[item]))
        resp = coach_api.handle_voice_fidelity({"queryStringParameters": None})
        assert resp["statusCode"] == 200, resp
        body = json.loads(resp["body"])
        assert body["scope"] == "all cycles"
        assert body["n"] == 16

    def test_an_unscored_board_still_carries_the_scope_word(self, monkeypatch):
        """n=0 is a count, not a class — the metric is cross-phase whether or not
        a panel has run yet, so the scope ships even on the empty state."""
        monkeypatch.setattr(coach_api, "table", FakeDdbTable(store_items=[]))
        resp = coach_api.handle_voice_fidelity({"queryStringParameters": None})
        body = json.loads(resp["body"])
        assert body["n"] == 0
        assert body["scope"] == "all cycles"
