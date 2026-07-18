"""tests/test_intake_response.py — #1405 private intake ledger: write routing,
pairing math, ADR-105 statistics floors, and the brief line.

Red on the pre-#1405 tree: no intake_response module, no intake_count metric,
no private routing in the ritual write path.
"""

import os
import sys
from datetime import datetime

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))
sys.path.insert(0, _REPO)

import intake_response as ir  # noqa: E402
from ritual_link import PRIVATE_INTAKE_SOURCE, PRIVATE_RITUAL_METRICS, RITUAL_METRICS, sign_ritual_token  # noqa: E402
from web import site_api_social as social  # noqa: E402

SECRET = "test-ritual-secret-0123456789"


# ── the one-tap write path routes private metrics to the private partition ────


class _FakeTable:
    def __init__(self):
        self.update_args = None

    def update_item(self, **kw):
        self.update_args = kw
        return {}


def _setup(monkeypatch):
    monkeypatch.setattr(social, "_get_ritual_token_secret", lambda: SECRET)
    monkeypatch.setattr(social, "_RATE_LIMITER_READY", True)
    monkeypatch.setattr(social, "_ddb_rate_check", lambda *a, **k: (True, 0, 0))
    ft = _FakeTable()
    monkeypatch.setattr(social, "table", ft)
    return ft


def _ev(qs):
    return {
        "queryStringParameters": qs,
        "headers": {"x-forwarded-for": "5.5.5.5"},
        "requestContext": {"http": {"sourceIp": "5.5.5.5"}},
    }


def test_intake_count_is_a_ritual_metric():
    assert "intake_count" in RITUAL_METRICS
    assert "intake_count" in PRIVATE_RITUAL_METRICS


def test_intake_tap_writes_private_partition_not_evening_ritual(monkeypatch):
    ft = _setup(monkeypatch)
    d = datetime.now(social.PT).strftime("%Y-%m-%d")
    qs = {"date": d, "metric": "intake_count", "value": "2", "token": sign_ritual_token(SECRET, d, "intake_count", 2)}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 200
    pk = ft.update_args["Key"]["pk"]
    assert pk == f"USER#matthew#SOURCE#{PRIVATE_INTAKE_SOURCE}"
    assert "evening_ritual" not in pk


def test_public_metric_still_writes_evening_ritual(monkeypatch):
    ft = _setup(monkeypatch)
    d = datetime.now(social.PT).strftime("%Y-%m-%d")
    qs = {"date": d, "metric": "connection", "value": "3", "token": sign_ritual_token(SECRET, d, "connection", 3)}
    r = social._handle_ritual_log(_ev(qs))
    assert r["statusCode"] == 200
    assert ft.update_args["Key"]["pk"] == "USER#matthew#SOURCE#evening_ritual"


# ── pairing + statistics (pure core) ──────────────────────────────────────────


def _mk_series(counts, hrv):
    """counts/hrv aligned by day index → (intake_by_date, metrics_by_date)."""
    intake, mets = {}, {}
    for i, (c, h) in enumerate(zip(counts, hrv)):
        d = f"2026-06-{i + 1:02d}"
        intake[d] = c
        mets[d] = {"hrv": h, "recovery_score": None, "rem_sleep_hours": None}
    return intake, mets


def test_pair_series_orders_chronologically_and_drops_missing():
    intake = {"2026-06-03": 2, "2026-06-01": 0, "2026-06-02": 1}
    mets = {"2026-06-01": {"hrv": 50}, "2026-06-03": {"hrv": 30}, "2026-06-02": {"hrv": None}}
    xs, ys = ir.pair_series(intake, mets, "hrv")
    assert xs == [0, 2] and ys == [50, 30]


def test_metric_block_below_floor_is_none():
    xs, ys = [0, 1, 2, 0], [50, 40, 30, 52]
    assert ir._metric_block(xs, ys) is None  # n=4 < MIN_PAIRS=5


def test_metric_block_carries_n_neff_p_and_ci():
    # 20 alternating evenings: zero → high HRV, nonzero → suppressed HRV.
    counts = [0, 2, 0, 1, 0, 2, 0, 1, 0, 2, 0, 1, 0, 2, 0, 1, 0, 2, 0, 1]
    hrv = [55, 38, 54, 44, 56, 37, 53, 43, 55, 39, 54, 45, 57, 38, 52, 44, 56, 36, 55, 43]
    block = ir._metric_block(counts, hrv)
    assert block["n"] == 20
    assert 2 <= block["n_eff"] <= 20  # Pyper-Peterman clamps into [2, n]
    assert block["r"] < 0  # intake suppresses next-day HRV in this fixture
    assert block["p"] is not None
    assert block["n_zero"] == 10 and block["n_nonzero"] == 10
    lo, hi = block["diff_ci95"]
    assert lo <= block["diff"] <= hi
    assert block["diff"] < 0
    assert block["ci_excludes_zero"] is True


def test_dose_response_gates_on_min_nonzero():
    counts = [0, 1] * 5  # 5 nonzero evenings — far below the 15 floor
    hrv = [55, 40] * 5
    intake, mets = _mk_series(counts, hrv)

    class _T:
        def query(self, **kw):
            return {"Items": [{"sk": f"DATE#{d}", "intake_count": c} for d, c in intake.items()]}

        def get_item(self, **kw):
            return {}

    payload = ir.compute_intake_response(_T())
    assert payload["nonzero_evenings"] == 5
    assert payload["dose_response"] is None
    assert payload["arming"]["dose_response_min_nonzero"] == ir.DOSE_RESPONSE_MIN_NONZERO


def test_dose_bins_shape():
    counts = [0, 1, 2, 3, 0, 1]
    hrv = [55, 44, 38, 30, 53, 45]
    intake, mets = _mk_series(counts, hrv)
    bins = ir._dose_bins(intake, mets)
    assert [b["dose"] for b in bins] == ["0", "1", "2+"]
    assert bins[0]["n"] == 2 and bins[1]["n"] == 2 and bins[2]["n"] == 2
    assert bins[2]["hrv_mean"] < bins[0]["hrv_mean"]


# ── the brief line (ADR-105: n + CI on every claim) ───────────────────────────


def test_brief_line_none_when_nothing_logged():
    assert ir.brief_line({"logged_evenings": 0}) is None
    assert ir.brief_line(None) is None


def test_brief_line_arming_before_floor():
    payload = {
        "logged_evenings": 3,
        "nonzero_evenings": 1,
        "arming": {"min_pairs": 5, "dose_response_min_nonzero": 15, "current_nonzero": 1},
        "metrics": {},
        "dose_response": None,
    }
    line = ir.brief_line(payload)
    assert "arming" in line and "3 evening" in line


def test_brief_line_carries_n_and_ci():
    payload = {
        "logged_evenings": 20,
        "nonzero_evenings": 10,
        "arming": {"min_pairs": 5, "dose_response_min_nonzero": 15, "current_nonzero": 10},
        "metrics": {
            "hrv": {
                "n": 20,
                "n_eff": 14.2,
                "r": -0.8,
                "p": 0.001,
                "n_zero": 10,
                "n_nonzero": 10,
                "zero_mean": 54.7,
                "nonzero_mean": 40.7,
                "diff": -14.0,
                "diff_ci95": [-18.2, -9.6],
                "ci_excludes_zero": True,
            }
        },
        "dose_response": None,
    }
    line = ir.brief_line(payload)
    assert "95% CI" in line and "n=10+10" in line and "n_eff=14.2" in line
    assert "15 nonzero evenings" in line and "10/15" in line
