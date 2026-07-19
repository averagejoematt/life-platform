"""tests/test_calibration_career_season_1376.py — #1376 career vs season.

CONFIRMED leak this pins the fix for: after an experiment reset, the calibration
scoreboard's platform block folded the CROSS_PHASE hypothesis/forecast ledger
(never wiped — cumulative across every cycle) together with the EXPERIMENT_SCOPED
coach PREDICTION# records (wiped + phase-tagged at every reset, ADR-077) into
ONE blended number — so /api/calibration read platform n=23 while every coach
read n=0 "nascent": career and season smashed together, with no lifetime view
to fall back on. Sports solved this decades ago: career stats beside season
stats, never one number pretending to be both.

This guard:
  1. pins that `_score_coach_calibration` splits ONE fetch of a coach's
     PREDICTION# partition into season (phase-visible) + career (every cycle)
     WITHOUT double-counting — season is a record-for-record subset of career,
     never a second independently-truncated query that could drift;
  2. pins that /api/calibration's `platform` block carries season numbers at
     the top level (unchanged shape) plus a nested `lifetime` career view, and
     that every per-coach entry does the same;
  3. pins the same split for /api/predictions' `overall` + `by_coach` blocks
     (the coach scorecard's data source);
  4. exercises the literal "confirmed leak" shape: a coach with ONLY archived
     (pre-reset) predictions reads season n=0 while its `lifetime` carries the
     real career count — the shape the front-end's "fresh slate — career: n=N"
     copy (AC-3) reads off of.
"""

import json
import os
import sys

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as api  # noqa: E402
from web.site_api_common import EXPERIMENT_START  # noqa: E402


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _pk_of(kw):
    """Extract the pk string a boto3 Key(pk).eq(v) & Key(sk).begins_with(...)
    KeyConditionExpression was built with (same trick #726's test uses)."""
    cond = kw["KeyConditionExpression"]
    return cond._values[0]._values[1]


def _season_pred(pred_id, status, confidence=0.8, coach="sleep_coach"):
    return {"pk": f"COACH#{coach}", "sk": f"PREDICTION#{pred_id}", "status": status, "confidence": confidence, "phase": "experiment"}


def _archived_pred(pred_id, status, confidence=0.8, coach="sleep_coach", cycle=7):
    # The reset wipe's stamp (phase_taxonomy.py): phase=pilot + tombstone=true + cycle=<closing>.
    return {
        "pk": f"COACH#{coach}",
        "sk": f"PREDICTION#{pred_id}",
        "status": status,
        "confidence": confidence,
        "phase": "pilot",
        "tombstone": True,
        "cycle": cycle,
    }


# sleep_coach: 2 season predictions (1 confirmed, 1 refuted) + 3 archived from a
# prior cycle (2 confirmed, 1 refuted) — season is a real number, not zero.
SLEEP_SEASON = [_season_pred("s1", "confirmed"), _season_pred("s2", "refuted")]
SLEEP_ARCHIVED = [
    _archived_pred("a1", "confirmed"),
    _archived_pred("a2", "confirmed"),
    _archived_pred("a3", "refuted"),
]
SLEEP_ALL = SLEEP_SEASON + SLEEP_ARCHIVED

# nutrition_coach: ONLY archived predictions — the literal "confirmed leak" shape,
# season n=0 while career carries the real record (AC-3's "fresh slate").
NUTRITION_ARCHIVED = [
    _archived_pred("n1", "confirmed", coach="nutrition_coach"),
    _archived_pred("n2", "confirmed", coach="nutrition_coach"),
    _archived_pred("n3", "confirmed", coach="nutrition_coach"),
]


def _coach_query_hook(table, **kw):
    pk = _pk_of(kw)
    if pk == "COACH#sleep_coach":
        return {"Items": list(SLEEP_ALL)}
    if pk == "COACH#nutrition_coach":
        return {"Items": list(NUTRITION_ARCHIVED)}
    return {"Items": []}


class TestScoreCoachCalibrationSplit:
    """_score_coach_calibration: ONE fetch, season a true subset of career."""

    def test_season_and_career_partition_without_double_counting(self, monkeypatch):
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_coach_query_hook))
        season_summary, season_pairs, career_summary, career_pairs = api._score_coach_calibration("sleep")
        assert len(season_pairs) == 2
        assert len(career_pairs) == 5
        assert season_summary["n"] == 2
        assert career_summary["n"] == 5
        assert season_summary["confirmed"] == 1 and season_summary["refuted"] == 1
        assert career_summary["confirmed"] == 3 and career_summary["refuted"] == 2
        # Every season pair is also present in career (season ⊆ career) — the
        # invariant that makes "no double counting" true: career is never a
        # second independently-fetched count that could diverge from season.
        for pair in season_pairs:
            assert career_pairs.count(pair) >= season_pairs.count(pair)
        # Career == season plus archived-only, never season counted twice.
        archived_only = [r for r in SLEEP_ALL if not api.singleton_visible(r)]
        assert len(archived_only) == len(SLEEP_ALL) - len(SLEEP_SEASON)
        assert len(career_pairs) == len(season_pairs) + len(archived_only)

    def test_fresh_slate_shape_season_zero_career_real(self, monkeypatch):
        # nutrition_coach: only archived predictions — season reads n=0/"nascent"
        # while career carries the real count (the literal leak from the issue).
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_coach_query_hook))
        season_summary, season_pairs, career_summary, career_pairs = api._score_coach_calibration("nutrition")
        assert season_summary["n"] == 0
        assert season_summary["label"] == "nascent"
        assert career_summary["n"] == 3
        assert career_summary["confirmed"] == 3


class TestHandleCalibrationCareerVsSeason:
    def _hook(self, table, **kw):
        pk = _pk_of(kw)
        if pk == "COACH#sleep_coach":
            return {"Items": list(SLEEP_ALL)}
        if pk == "COACH#nutrition_coach":
            return {"Items": list(NUTRITION_ARCHIVED)}
        if pk == api.USER_PREFIX + "calibration":
            before = str(_shift_date(EXPERIMENT_START, -30))
            hyp_before = [
                {
                    "pk": pk,
                    "sk": f"CALIB#{before}#h1",
                    "record_type": "hypothesis_resolution",
                    "outcome": "confirmed",
                    "stated_confidence": "high",
                    "resolved_at": before,
                },
                {
                    "pk": pk,
                    "sk": f"CALIB#{before}#h2",
                    "record_type": "hypothesis_resolution",
                    "outcome": "refuted",
                    "stated_confidence": "low",
                    "resolved_at": before,
                },
            ]
            hyp_after = [
                {
                    "pk": pk,
                    "sk": f"CALIB#{EXPERIMENT_START}#h3",
                    "record_type": "hypothesis_resolution",
                    "outcome": "confirmed",
                    "stated_confidence": "high",
                    "resolved_at": EXPERIMENT_START,
                },
            ]
            fc_before = [
                {
                    "pk": pk,
                    "sk": f"CALIB#{before}#f1",
                    "record_type": "forecast_resolution",
                    "confidence": 0.8,
                    "covered": True,
                    "resolved_at": before,
                },
                {
                    "pk": pk,
                    "sk": f"CALIB#{before}#f2",
                    "record_type": "forecast_resolution",
                    "confidence": 0.8,
                    "covered": False,
                    "resolved_at": before,
                },
            ]
            fc_after = [
                {
                    "pk": pk,
                    "sk": f"CALIB#{EXPERIMENT_START}#f3",
                    "record_type": "forecast_resolution",
                    "confidence": 0.8,
                    "covered": True,
                    "resolved_at": EXPERIMENT_START,
                },
            ]
            return {"Items": hyp_before + hyp_after + fc_before + fc_after}
        return {"Items": []}

    def test_platform_carries_season_top_level_and_career_nested(self, monkeypatch):
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=self._hook))
        data = _body(api.handle_calibration({}))
        p = data["platform"]
        # Season: sleep(2) + hyp-after(1) + forecast-after(1) = 4 (nutrition
        # contributes 0 this season — all its predictions are archived).
        assert p["n"] == 4
        # Career: sleep(5) + nutrition(3) + hyp-all(3) + forecast-all(3) = 14 —
        # never equal to season and never the season number silently doubled.
        assert p["lifetime"]["n"] == 14
        assert p["lifetime"]["n"] != p["n"] * 2  # not a double-count artifact
        assert p["n"] < p["lifetime"]["n"]  # season is a real subset, not the whole record

    def test_every_coach_block_carries_lifetime_too(self, monkeypatch):
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=self._hook))
        data = _body(api.handle_calibration({}))
        by_id = {c["coach_id"]: c for c in data["coaches"]}
        assert by_id["sleep"]["n"] == 2
        assert by_id["sleep"]["lifetime"]["n"] == 5
        # The exact leak from the issue: nutrition reads season n=0 ("nascent")
        # while its lifetime carries the real, non-zero career record.
        assert by_id["nutrition"]["n"] == 0
        assert by_id["nutrition"]["label"] == "nascent"
        assert by_id["nutrition"]["lifetime"]["n"] == 3
        assert by_id["nutrition"]["lifetime"]["confirmed"] == 3

    def test_hypotheses_and_interval_forecasts_carry_lifetime(self, monkeypatch):
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=self._hook))
        data = _body(api.handle_calibration({}))
        assert data["hypotheses"]["n"] == 1  # season only (h3)
        assert data["hypotheses"]["lifetime"]["n"] == 3  # all 3 hypothesis rows
        assert data["interval_forecasts"]["n"] == 1  # season only (f3)
        assert data["interval_forecasts"]["lifetime"]["n"] == 3  # all 3 forecast rows


class TestHandlePredictionsCareerVsSeason:
    def test_overall_and_by_coach_carry_lifetime(self, monkeypatch):
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_coach_query_hook))
        data = _body(api.handle_predictions({}))
        o = data["overall"]
        # Season overall: only sleep's 2 season predictions across all 8 coaches.
        assert o["total"] == 2
        assert o["confirmed"] == 1 and o["refuted"] == 1
        # Career overall: sleep's 5 (3 confirmed, 2 refuted) + nutrition's 3
        # (3 confirmed) = 8 total / 6 confirmed, never double-counted.
        assert o["lifetime"]["total"] == 8
        assert o["lifetime"]["confirmed"] == 6
        assert o["lifetime"]["refuted"] == 2
        assert o["lifetime"]["accuracy_pct"] == 75.0
        by_coach = data["by_coach"]
        assert by_coach["sleep"]["total"] == 2
        assert by_coach["sleep"]["lifetime"]["total"] == 5
        # The leak shape: nutrition reads 0 predictions this season...
        assert by_coach["nutrition"]["total"] == 0
        assert by_coach["nutrition"]["hit_rate_pct"] is None
        # ...but its career record is real and non-zero.
        assert by_coach["nutrition"]["lifetime"]["total"] == 3
        assert by_coach["nutrition"]["lifetime"]["confirmed"] == 3
        assert by_coach["nutrition"]["lifetime"]["hit_rate_pct"] == 100.0

    def test_season_predictions_list_excludes_archived_records(self, monkeypatch):
        # The scored calls list stays season-only (unchanged AC — the ledger
        # "restarts with each genesis" copy on the front-end still holds for
        # the CALL LIST; only the tallies gain the lifetime view, #1376).
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_coach_query_hook))
        data = _body(api.handle_predictions({}))
        ids = {p["coach_id"] for p in data["predictions"]}
        assert ids == {"sleep"}  # nutrition's predictions are all archived → none listed
        assert len(data["predictions"]) == 2


def _shift_date(iso, days):
    from datetime import date, timedelta

    d = date.fromisoformat(iso) + timedelta(days=days)
    return d.isoformat()
