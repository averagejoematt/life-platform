"""tests/test_calibration_void_1893.py — the void ledger stops being write-only.

#1893: every reset stamps one `voided_at_reset` CALIB# row per still-open
pre-registered bet (restart_pipeline.build_void_calib_item), and until this
change NOTHING ever read them — 273 of 323 lifetime bets were invisible on the
public calibration surface. These tests pin:

  - count_voided over representative rows (split by kind, keyed by reset);
  - the totality guard: every row class in the shared CALIB# ledger is
    accounted for (graded / awaiting / voided) — a NEW record_type that no
    reader counts fails loud instead of going write-only for five resets;
  - the reconcile invariant on realistic mixed fixtures: graded + awaiting +
    voided == total rows, so a silent denominator shrink cannot recur;
  - Brier purity: voided rows still contribute NOTHING to scoring pairs.
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_LAMBDAS = os.path.join(os.path.dirname(_HERE), "lambdas")
if _LAMBDAS not in sys.path:
    sys.path.insert(0, _LAMBDAS)

from experiment import calibration_core as cc  # noqa: E402


def _void(kind, genesis, i):
    return {
        "sk": f"CALIB#{genesis}#void#{kind}#{i}",
        "record_type": f"{'hypothesis' if kind == 'hyp' else 'prediction'}_void",
        "outcome": "voided_at_reset",
        "reset_genesis": genesis,
        "stated_confidence": "medium",
    }


def _graded(i, outcome="confirmed"):
    return {"sk": f"CALIB#h{i}", "record_type": "hypothesis_resolution", "outcome": outcome, "stated_confidence": "high"}


def _forecast(i, covered=True):
    return {"sk": f"CALIB#f{i}", "record_type": "forecast_resolution", "covered": covered, "confidence": 0.8}


_FIXTURE = (
    [_graded(i) for i in range(3)]
    + [_graded(i, "refuted") for i in range(3, 5)]
    + [_forecast(i) for i in range(4)]
    + [_forecast(9, covered=None)]
    + [_void("pred", "2026-07-20", i) for i in range(6)]
    + [_void("pred", "2026-07-27", i) for i in range(2)]
    + [_void("hyp", "2026-07-27", i) for i in range(2)]
)


def test_count_voided_splits_by_kind_and_reset():
    v = cc.count_voided(_FIXTURE)
    assert v["n"] == 10
    assert v["predictions"] == 8 and v["hypotheses"] == 2
    assert v["by_reset"] == {"2026-07-20": 6, "2026-07-27": 4}


def test_count_voided_empty_ledger():
    assert cc.count_voided([]) == {"n": 0, "hypotheses": 0, "predictions": 0, "by_reset": {}}


def test_totality_every_row_class_is_accounted_for():
    c = cc.classify_calibration_rows(_FIXTURE)
    assert c["unclassified"] == []
    assert c["graded"] + c["awaiting"] + c["voided"] == len(_FIXTURE)
    assert c["voided"] == 10 and c["graded"] == 9 and c["awaiting"] == 1


def test_totality_guard_fails_loud_on_a_new_unread_row_class():
    # The exact failure mode #1893 closes: a writer invents a row class no
    # reader counts. It must land in unclassified, not vanish.
    rogue = {"sk": "CALIB#2026-08-01#suspended#x", "record_type": "prediction_suspend", "outcome": "suspended_at_pause"}
    c = cc.classify_calibration_rows(_FIXTURE + [rogue])
    assert c["unclassified"] == ["CALIB#2026-08-01#suspended#x"]


def test_voided_rows_never_reach_the_brier_pairs():
    # Purity: voided_at_reset is not scorable and must not distort the curve.
    assert cc.pairs_from_calibration_rows([_void("pred", "2026-07-27", 1)]) == []
    assert cc.outcome_to_binary("voided_at_reset") is None


def test_handler_serves_the_void_count(monkeypatch):
    """handle_calibration reads the SAME fetched rows — the payload must carry
    voided and the disclosure must explain it."""
    import json

    os.environ.setdefault("S3_BUCKET", "test-bucket")
    from web import site_api_coach as sac

    def _fake_parallel_fetch(jobs):
        return {k: (_FIXTURE if k == "hypothesis-ledger" else []) for k in jobs}

    monkeypatch.setattr(sac, "_parallel_fetch", _fake_parallel_fetch)
    monkeypatch.setattr(sac, "_current_cycle", lambda: 11)
    resp = sac.handle_calibration({})
    body = json.loads(resp["body"])
    assert body["voided"]["n"] == 10
    assert body["voided"]["by_reset"] == {"2026-07-20": 6, "2026-07-27": 4}
    assert "voids" in body["disclosure"] and "never resolved" in body["disclosure"]
    # the graded platform numbers are untouched by the voids
    assert body["platform"]["lifetime"]["n"] == 9
