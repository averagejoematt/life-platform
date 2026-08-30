"""tests/test_cross_phase_framing_2957.py — #2957: cross-phase content says so.

The class, observed live across five reader-truth sweeps on cycle 14 (runs
32545820852, 32650063358, 32653124659, 32664670256, 32668047541): a counter or a
dated artefact that reaches back past the live genesis rendered with no label, so a
Day-5/Day-7 page asserted a history the cycle it sat in could not contain —

  * `/data/vitals/`         'No training logged — 57 days' on Day 5
  * `/method/calibration/`  'THIS SEASON · CYCLE 14' beside the CAREER forecast count
  * `/coaching/lab-notes/`  a 2026-07-26 diary reaction as the featured current coaching
  * `/method/cycles/`       'Days with data: 7' beside '—' for every other metric
  * `/data/sleep/`          'over the week' captioning a genesis-clamped 5 nights
  * `/story/`               the Day-2 chronicle installment, unframed, on Day 7

Every number was true. What was missing was the FRAME, and per ADR-104 and the phase
rubric (docs/PHASE_TAXONOMY.md) the frame belongs at the producer, not in a reader's
head. These tests pin the producer half — the labels the endpoints now emit. The
three front-end halves (the sleep caption, the calibration fig scope, the story
archival age) are pinned by the render sweep, not here.

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
    site_api_intelligence as intel,  # noqa: E402
    site_api_rollups,
    site_api_thirdwall,
)
from web.site_api_phase_frame import archival_frame, cross_cycle_suffix, label_with_span, spans_cycle  # noqa: E402

_HEVY_PK = "USER#matthew#SOURCE#hevy"
_NOTION_PK = "USER#matthew#SOURCE#notion"
_REACTIONS_PK = "USER#matthew#SOURCE#diary_reactions"


def _today_pt():
    return datetime.now(common.PT).date()


def _iso(d):
    return d.strftime("%Y-%m-%d")


# ── the vocabulary itself ────────────────────────────────────────────────────


class TestPhaseFrameVocabulary:
    def test_spans_cycle_is_the_day_one_boundary(self):
        # A 6-day gap on Day 7 points at Day 1 — in-cycle, no label.
        assert spans_cycle(6, 7) is False
        # A 7-day gap on Day 7 points at the day BEFORE Day 1 — cross-cycle.
        assert spans_cycle(7, 7) is True
        assert spans_cycle(57, 5) is True

    def test_spans_cycle_is_fail_soft_on_missing_or_junk_inputs(self):
        # A public read path: an unknown day number must degrade to "no frame",
        # never to an exception or a confidently wrong one.
        assert spans_cycle(None, 7) is False
        assert spans_cycle(57, None) is False
        assert spans_cycle("many", 5) is False

    def test_suffix_names_the_genesis_it_reaches_past(self):
        s = cross_cycle_suffix("2026-08-17")
        assert "lifetime" in s and "2026-08-17" in s
        assert "cycle 14" in cross_cycle_suffix("2026-08-17", 14)

    def test_suffix_without_a_genesis_still_says_lifetime(self):
        # We can always honestly say the counter spans cycles even when we cannot
        # name the boundary — what we must never do is invent a date.
        s = cross_cycle_suffix(None)
        assert "lifetime" in s
        assert "None" not in s

    def test_label_with_span_leaves_in_cycle_text_alone(self):
        assert label_with_span("No training logged — 2 days", 2, 7, "2026-08-17") == "No training logged — 2 days"

    def test_archival_frame_is_none_for_in_cycle_content(self):
        assert archival_frame("2026-08-20", "2026-08-17") is None
        assert archival_frame("2026-08-17", "2026-08-17") is None  # genesis day is in-cycle

    def test_archival_frame_measures_the_distance_back(self):
        f = archival_frame("2026-07-26", "2026-08-17", 14)
        assert f["pre_cycle"] is True
        assert f["days_before"] == 22
        assert "previous cycle" in f["label"] and "2026-08-17" in f["label"]

    def test_archival_frame_is_fail_soft_on_a_junk_date(self):
        assert archival_frame("", "2026-08-17") is None
        assert archival_frame("2026-07-26", None) is None


# ── /data/vitals/ + the cockpit: the lifetime gap counters ───────────────────


class _PulseTable:
    """Answers the handful of table.query() shapes /api/pulse issues, honouring the
    Key('sk').between(...) range so a day-scoped query doesn't leak neighbours."""

    def __init__(self, by_pk):
        self.by_pk = by_pk

    @staticmethod
    def _find_pk(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        for v in vals:
            got = _PulseTable._find_pk(v) if hasattr(v, "_values") else (v if isinstance(v, str) else None)
            if isinstance(got, str) and got.startswith("USER#"):
                return got
        return None

    @staticmethod
    def _find_sk_range(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        key = vals[0] if vals else None
        if getattr(key, "name", None) == "sk" and getattr(cond, "expression_operator", None) == "BETWEEN" and len(vals) == 3:
            return (vals[1], vals[2])
        for v in vals:
            if hasattr(v, "_values"):
                found = _PulseTable._find_sk_range(v)
                if found:
                    return found
        return None

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        pk = self._find_pk(cond) if cond is not None else None
        rng = self._find_sk_range(cond) if cond is not None else None
        items = list(self.by_pk.get(pk, []))
        if rng:
            lo, hi = rng
            items = [i for i in items if lo <= str(i.get("sk", "")) <= hi]
        if kwargs.get("ScanIndexForward") is False:
            items = sorted(items, key=lambda i: str(i.get("sk", "")), reverse=True)
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}


def _pulse(monkeypatch, *, day_n, last_lift_days_ago=None, last_journal_days_ago=None, whoop=False):
    """Run /api/pulse on Day `day_n` of a cycle, with the last hevy session and the
    last journal entry placed `*_days_ago` before today."""
    genesis = _iso(_today_pt() - timedelta(days=day_n - 1))
    monkeypatch.setattr(common, "EXPERIMENT_START", genesis)
    monkeypatch.setattr(intel, "EXPERIMENT_START", genesis)
    monkeypatch.setattr(intel, "_latest_item", lambda *a, **k: None)
    monkeypatch.setattr(intel, "_get_profile", lambda: {"journey_start_weight_lbs": 315.0})
    by_pk = {}
    # #3294: the lift label licenses a category-level "no training" claim only when
    # every workout-evidence source could speak. Give apple_health a live pipe (steps
    # today, no workout minutes) so the infrastructure leg of the denominator is
    # answered and these fixtures keep testing the FRAME, not the licensing gate.
    by_pk["USER#matthew#SOURCE#apple_health"] = [{"sk": f"DATE#{_iso(_today_pt())}", "steps": 5000}]
    if last_lift_days_ago is not None:
        d = _iso(_today_pt() - timedelta(days=last_lift_days_ago))
        by_pk[_HEVY_PK] = [{"sk": f"DATE#{d}", "routine_name": None}]
    if last_journal_days_ago is not None:
        d = _iso(_today_pt() - timedelta(days=last_journal_days_ago))
        by_pk[_NOTION_PK] = [{"sk": f"DATE#{d}"}]
    if whoop:
        # At least one signal must REPORT or the narrative is (correctly) replaced by
        # the honest "no data reported today" line and never reaches the journal clause.
        by_pk["USER#matthew#SOURCE#whoop"] = [
            {"sk": f"DATE#{_iso(_today_pt())}", "recovery_score": 60, "sleep_duration_hours": 7.2, "sleep_state": "finalized"}
        ]
    monkeypatch.setattr(intel, "table", _PulseTable(by_pk))
    return json.loads(intel.handle_pulse()["body"])["pulse"], genesis


class TestVitalsLifetimeGapCounters:
    def test_a_gap_older_than_the_cycle_is_labelled_lifetime(self, monkeypatch):
        """The live finding, reproduced: a 57-day training gap on Day 5."""
        p, genesis = _pulse(monkeypatch, day_n=5, last_lift_days_ago=57)
        lift = p["glyphs"]["lift"]
        assert lift["days_since_last"] == 57
        assert lift["spans_cycles"] is True
        assert "57 days" in lift["label"]
        assert "lifetime" in lift["label"], lift["label"]
        assert genesis in lift["label"], lift["label"]

    def test_an_in_cycle_gap_carries_no_lifetime_label(self, monkeypatch):
        """Control — the badge must not become wallpaper. Day 20, gap 6: the last
        session is inside this cycle, so the plain sentence is the honest one."""
        p, _ = _pulse(monkeypatch, day_n=20, last_lift_days_ago=6)
        lift = p["glyphs"]["lift"]
        assert lift["spans_cycles"] is False
        assert lift["label"] == "No training logged — 6 days"

    def test_journal_gap_takes_the_same_frame_in_glyph_and_narrative(self, monkeypatch):
        p, genesis = _pulse(monkeypatch, day_n=5, last_journal_days_ago=20, whoop=True)
        j = p["glyphs"]["journal"]
        assert j["spans_cycles"] is True
        assert "lifetime" in j["label"] and genesis in j["label"]
        # The prose narrative repeats the claim, so it repeats the frame.
        assert "lifetime" in p["narrative"], p["narrative"]


# ── /coaching/lab-notes/: an archived reaction says which cycle it is from ───


def _reaction_rows(dates):
    return [
        {
            "pk": _REACTIONS_PK,
            "sk": f"DATE#{d}#video_diary#u{i}",
            "entry_date": d,
            "entry_uid": f"u{i}",
            "channel": "video_diary",
            "kind": "diary",
            "coach_id": "mind_coach",
            "coach_name": "Dr. Nathan Reeves",
            "theme": "consistency",
            "reaction": "A steady week is the point.",
            "phase": "experiment",
        }
        for i, d in enumerate(dates)
    ]


def _diary_reactions(monkeypatch, dates, genesis):
    monkeypatch.setattr(common, "EXPERIMENT_START", genesis)
    monkeypatch.setattr(site_api_thirdwall, "EXPERIMENT_START", genesis)
    rows = _reaction_rows(dates)
    monkeypatch.setattr(coach_api, "table", FakeDdbTable(query_hook=lambda table, **kw: {"Items": list(rows)}))
    resp = coach_api.handle_diary_reactions({"queryStringParameters": None})
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])["reactions"]


class TestLabNotesArchivalFraming:
    def test_a_pre_genesis_reaction_is_framed_as_a_previous_cycle(self, monkeypatch):
        """The live finding: the featured lab-notes reaction was 22 days older than
        the cycle it was being served inside."""
        genesis = _iso(_today_pt() - timedelta(days=6))  # Day 7
        old = _iso(_today_pt() - timedelta(days=28))
        (r,) = _diary_reactions(monkeypatch, [old], genesis)
        assert r["archival"]["pre_cycle"] is True
        assert r["archival"]["days_before"] == 22
        assert genesis in r["archival"]["label"]

    def test_an_in_cycle_reaction_carries_no_archival_key(self, monkeypatch):
        genesis = _iso(_today_pt() - timedelta(days=6))
        recent = _iso(_today_pt() - timedelta(days=2))
        (r,) = _diary_reactions(monkeypatch, [recent], genesis)
        assert "archival" not in r, r


# ── /method/cycles/: the live column is a partial read, a dash is per-metric ─


def _cycle_compare(geneses, rows_by_source):
    def _query_source(source, start, end, include_pilot=False):
        lo, hi = f"DATE#{start}", f"DATE#{end}"
        return [r for r in rows_by_source.get(source, ()) if lo <= r["sk"] <= hi + "￿"]

    resp = site_api_rollups.cycle_compare(_g={"CYCLE_GENESES": geneses, "_query_source": _query_source, "pre_start_meta": lambda: None})
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


class TestCycleCompareInProgressFraming:
    def test_the_live_cycle_is_marked_in_progress_with_its_elapsed_day(self):
        today = _today_pt()
        g_old = (today - timedelta(days=400)).isoformat()
        g_now = (today - timedelta(days=6)).isoformat()  # Day 7
        d = _cycle_compare({13: g_old, 14: g_now}, {"whoop": [{"sk": f"DATE#{g_now}", "recovery_score": 50}], "withings": []})
        cur = [c for c in d["cycles"] if c["cycle"] == 14][0]
        old = [c for c in d["cycles"] if c["cycle"] == 13][0]
        assert cur["in_progress"] is True and cur["days_elapsed"] == 7
        assert old["in_progress"] is False

    def test_the_note_says_the_dash_is_per_metric_absence(self):
        """The judge's exact objection: 'Days with data: 7' beside '—' for start
        weight read as a contradiction. It is per-metric absence, and the note now
        says so on the surface rather than leaving the reader to infer it."""
        today = _today_pt()
        g_now = (today - timedelta(days=6)).isoformat()
        d = _cycle_compare({14: g_now}, {"whoop": [{"sk": f"DATE#{g_now}", "recovery_score": 50}], "withings": []})
        note = d["note"]
        assert "still running" in note, note
        assert "no reading inside the window" in note, note
        # And the cycle it names is the live one, not a hardcoded number.
        assert "Cycle 14" in note, note


# ── /method/calibration/: the season card can name its own window ────────────


class TestCalibrationSeasonWindow:
    def test_payload_carries_the_genesis_the_season_is_counted_from(self, monkeypatch):
        monkeypatch.setattr(coach_api, "table", FakeDdbTable(query_hook=lambda table, **kw: {"Items": []}))
        resp = coach_api.handle_calibration({"queryStringParameters": None})
        body = json.loads(resp["body"])
        assert body.get("cycle_start") == common.EXPERIMENT_START, body.get("cycle_start")
