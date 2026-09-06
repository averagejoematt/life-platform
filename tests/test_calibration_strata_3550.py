"""tests/test_calibration_strata_3550.py — #3550: the platform-wide calibration card can
never claim a property no stratum has.

THE LIVE DEFECT (2026-09-05, /review full QS-3): `/api/calibration`'s
`platform.lifetime` read `skilled=true (Brier skill 0.17) / well-calibrated /
reliable` while BOTH strata were unskilled — the coaches' 37 calls (0.5 stated,
22% observed, skill ≈ -0.47 against their own base rate) and the 137 interval
forecasts (0.8 stated, 79% observed, skill ≈ -0.001). Pooling them and scoring the
pool against ONE pooled base rate (116/174) manufactured the skill: the pooled
reference Brier (0.222) is worse than either stratum's own, so "knowing which
stratum a call came from" was credited to the forecasters. The n-weighted gap did
the same the other way — 137 forecasts at a 0.01 gap diluted the coaches' 0.28
gap to 0.069, under the 0.15 over-confidence trip.

The scorer-level invariant lives in tests/test_calibration_core_parity.py (three
copies). This file pins the HANDLERS: /api/calibration's platform + lifetime cards
and the State of Matthew section are scored by score_strata, the strata ride on
the payload, and the exact live shape reads honestly end to end.
"""

import ast
import inspect
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

from experiment import calibration_core as cc  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_coach as api, site_api_coach_ledger as ledger  # noqa: E402

COACHES = [(0.5, 1)] * 8 + [(0.5, 0)] * 29
FORECASTS = [(0.8, 1)] * 108 + [(0.8, 0)] * 29


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _pk_of(kw):
    cond = kw["KeyConditionExpression"]
    return cond._values[0]._values[1]


def _live_shape_hook(table, **kw):
    """The 2026-09-05 card's shape: every coach call archived (career-only) at 0.5
    with 8/37 confirmed; 137 interval-forecast resolutions at 0.8 with 108 covered."""
    pk = _pk_of(kw)
    if pk == "COACH#sleep_coach":
        items = []
        for i, (conf, y) in enumerate(COACHES):
            items.append(
                {
                    "pk": pk,
                    "sk": f"PREDICTION#c{i}",
                    "status": "confirmed" if y else "refuted",
                    "confidence": conf,
                    "phase": "pilot",
                    "tombstone": True,
                    "cycle": 12,
                }
            )
        return {"Items": items}
    if pk.endswith("calibration"):
        items = []
        for i, (conf, y) in enumerate(FORECASTS):
            items.append(
                {
                    "pk": pk,
                    "sk": f"CALIB#2026-07-{(i % 28) + 1:02d}#f{i}",
                    "record_type": "forecast_resolution",
                    "confidence": conf,
                    "covered": bool(y),
                    "resolved_at": f"2026-07-{(i % 28) + 1:02d}",
                }
            )
        return {"Items": items}
    return {"Items": []}


class TestCalibrationHandlerIsStratified:
    def test_the_handler_scores_the_platform_cards_with_score_strata(self):
        """The extract-the-right-real-source guard: the pooled cards must be built
        by score_strata, and NO call to score_pairs may take a concatenated list."""
        src = inspect.getsource(ledger.handle_calibration)
        tree = ast.parse(src.replace("\n    ", "\n") if src.startswith(" ") else src)
        strata_calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "score_strata"]
        assert len(strata_calls) == 2, "platform + platform.lifetime"
        for n in ast.walk(tree):
            if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "score_pairs":
                assert not any(isinstance(a, ast.BinOp) for a in n.args), "score_pairs over a concatenated pair list is the #3550 defect"

    def test_the_live_shape_reads_honestly_end_to_end(self, monkeypatch):
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_live_shape_hook))
        data = _body(api.handle_calibration({}))
        life = data["platform"]["lifetime"]
        assert life["n"] == 174 and life["confirmed"] == 116
        # Positive control: the pooled scorer on the same pairs DOES manufacture it.
        pooled = cc.score_pairs(COACHES + FORECASTS)
        assert pooled["skilled"] is True and pooled["calibration"] == "well-calibrated"
        # The served card cannot.
        assert life["skill_reference"] == "stratified"
        assert life["skilled"] is False and life["brier_skill"] < 0
        assert life["calibration"] == "over-confident" and life["label"] == "not_yet_skillful"
        assert life["worst_stratum_gap"]["stratum"] == "coaches" and life["worst_stratum_gap"]["gap"] > 0.15
        strata = life["strata"]
        assert set(strata) == {"coaches", "hypotheses", "interval_forecasts"}
        assert strata["coaches"]["n"] == 37 and strata["coaches"]["skilled"] is False
        assert strata["interval_forecasts"]["n"] == 137 and strata["interval_forecasts"]["skilled"] is False
        assert strata["hypotheses"]["n"] == 0 and strata["hypotheses"]["skilled"] is None
        # The disclosure names the rule the card is scored by.
        assert "STRATIFIED base rate" in data["disclosure"]

    def test_the_season_card_carries_strata_too_and_the_shape_is_a_superset(self, monkeypatch):
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_live_shape_hook))
        data = _body(api.handle_calibration({}))
        season = data["platform"]
        for key in ("n", "brier", "brier_skill", "skilled", "calibration", "label", "score", "accuracy_ci95", "reliability_bins"):
            assert key in season and key in season["lifetime"]
        assert "strata" in season and season["skill_reference"] == "stratified"

    def test_skilled_still_follows_brier_skill_sign(self, monkeypatch):
        """The #1370 / diligence-d5 invariant survives the reference change."""
        monkeypatch.setattr(api, "table", FakeDdbTable(query_hook=_live_shape_hook))
        life = _body(api.handle_calibration({}))["platform"]["lifetime"]
        assert life["skilled"] == (life["brier_skill"] > 0)


class TestStateOfMatthewIsStratified:
    def test_fetch_calibration_summary_scores_strata_not_a_pooled_list(self):
        from compute import state_of_matthew_lambda as som

        src = inspect.getsource(som.fetch_calibration_summary)
        assert "score_strata(" in src and "score_pairs(" not in src

    def test_the_section_shape_is_unchanged(self):
        from compute import state_of_matthew_lambda as som

        card = cc.score_strata({"coaches": COACHES, "hypotheses": []})
        section = som.gather_calibration_section(card)
        assert set(section) == {"n", "confirmed", "refuted", "accuracy_pct", "brier", "brier_skill", "calibration", "label"}
        assert section["label"] == "not_yet_skillful"


class TestPooledCardInvariantAcrossShapes:
    """Property over random two-stratum ledgers: pooled skilled=True implies some
    stratum is skilled; pooled 'well-calibrated' implies no stratum trips the
    over/under-confidence band at n>=5."""

    def test_random_strata_never_manufacture_skill(self):
        import random

        rng = random.Random(3550)
        for _ in range(300):
            strata = {}
            for name in ("a", "b", "c"):
                n = rng.randint(0, 40)
                conf = rng.choice([0.2, 0.5, 0.7, 0.8, 0.9])
                rate = rng.random()
                strata[name] = [(conf, 1 if rng.random() < rate else 0) for _ in range(n)]
            card = cc.score_strata(strata)
            if card["skilled"] is True:
                assert any(s["skilled"] is True for s in card["strata"].values()), strata
            if card["calibration"] == "well-calibrated":
                for s in card["strata"].values():
                    if s["n"] >= 5 and s["reliability_gap"] is not None:
                        assert -0.15 <= s["reliability_gap"] <= 0.15 or abs(s["reliability_gap"]) <= 0.1505, (s, card)
