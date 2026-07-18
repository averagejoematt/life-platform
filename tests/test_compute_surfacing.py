"""tests/test_compute_surfacing.py — elite review (2026-06-15) surfacing PR.

Compute outputs stored daily but exposed read-only via the site API:
  * circadian-compliance score  (SOURCE#circadian | DATE#)

These tests exercise the read-only handlers against a faked DynamoDB, covering
the populated shape, the empty/no-data path, and internal-key stripping.
ER-02 contract spirit — the endpoints' public shape is pinned.

#487/ADR-113 — the unified-sleep reconciliation surface (SOURCE#sleep_unified,
/api/sleep_reconciliation) was RETIRED: its per-field merge read record fields
that never existed and its date ran 1–2 nights stale, mislabelling the public
/data/sleep "night of" header. The header date is now sourced from the LIVE
/api/sleep_detail as_of_date (the latest Eight Sleep night in the window). The
tests at the bottom lock in both the retirement and the honest date source.
"""

import os
import sys
from decimal import Decimal

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas"))

from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_api_common as common,  # noqa: E402
    site_api_data as data,  # noqa: E402  # retired-handler absence check (test_sleep_reconciliation_handler_is_retired)
    site_api_intelligence as intel,  # noqa: E402  # #1240: handle_forecast moved here
    site_api_vitals as vit,  # noqa: E402  # #1240: handle_circadian/handle_sleep_detail moved here
)

# ── circadian ────────────────────────────────────────────────────────────────


def test_circadian_populated_shape(monkeypatch):
    item = {
        "pk": "USER#matthew#SOURCE#circadian",
        "sk": "DATE#2026-06-15",
        "date": "2026-06-15",
        "score": Decimal("78"),
        "category": "good",
        "prescription": "Get morning light before 9am.",
        "weakest_component": "screen_wind_down",
        "components": {
            "wake_light": {"score": Decimal("25"), "max": Decimal("25"), "note": "Logged AM sun"},
            "screen_wind_down": {"score": Decimal("3"), "max": Decimal("25"), "note": "Late screens"},
        },
        "run_id": "abc123",
    }
    monkeypatch.setattr(common, "table", FakeDdbTable(rows=[item]))

    resp = vit.handle_circadian()
    assert resp["statusCode"] == 200
    body = __import__("json").loads(resp["body"])
    assert body["available"] is True
    assert body["date"] == "2026-06-15"
    # temporal frame: circadian is a forward-looking forecast for tonight
    assert body["frame"] == "tonight"
    assert body["score"] == 78
    assert body["category"] == "good"
    assert body["weakest_component"] == "screen_wind_down"
    assert body["components"]["wake_light"]["score"] == 25
    assert body["components"]["screen_wind_down"]["note"] == "Late screens"
    # internal keys must not leak
    assert "pk" not in body and "sk" not in body and "run_id" not in body


def test_circadian_no_data(monkeypatch):
    monkeypatch.setattr(common, "table", FakeDdbTable(rows=[]))
    resp = vit.handle_circadian()
    assert resp["statusCode"] == 200
    body = __import__("json").loads(resp["body"])
    assert body["available"] is False
    assert "score" not in body


# ── unified sleep reconciliation — RETIRED (#487/ADR-113) ─────────────────────


def test_sleep_reconciliation_handler_is_retired():
    """The dead unified-sleep surface is gone: no handler, no route. (#487/ADR-113)"""
    assert not hasattr(data, "handle_sleep_reconciliation"), "handle_sleep_reconciliation should be removed"

    from web import site_api_lambda

    assert "/api/sleep_reconciliation" not in site_api_lambda.ROUTES, "the /api/sleep_reconciliation route must be removed"


def test_sleep_detail_night_of_date_sourced_live_not_from_unified(monkeypatch):
    """#487/ADR-113 date-sourcing lock: the /data/sleep "night of" header derives from
    handle_sleep_detail's as_of_date — the LATEST live Eight Sleep night in the window —
    NOT from the retired, chronically-stale sleep_unified record. as_of_date must track
    the freshest available night."""
    monkeypatch.setattr(vit, "EXPERIMENT_START", "2026-06-01")

    eight = [
        {"sk": "DATE#2026-07-01", "sleep_score": Decimal("80"), "sleep_efficiency_pct": Decimal("88")},
        {"sk": "DATE#2026-07-03", "sleep_score": Decimal("82"), "sleep_efficiency_pct": Decimal("90")},  # freshest
    ]
    whoop = [
        {"sk": "DATE#2026-07-03", "recovery_score": Decimal("66"), "hrv": Decimal("55"), "resting_heart_rate": Decimal("50")},
    ]

    def _fake_query_source(source, *_a, **_k):
        return {"eightsleep": eight, "whoop": whoop}.get(source, [])

    monkeypatch.setattr(vit, "_query_source", _fake_query_source)

    resp = vit.handle_sleep_detail()
    assert resp["statusCode"] == 200
    body = __import__("json").loads(resp["body"])
    # as_of_date is the freshest live Eight Sleep night — the honest source for "night of".
    assert body["sleep_detail"]["as_of_date"] == "2026-07-03"


# ── forecast (#541) ──────────────────────────────────────────────────────────


def test_forecast_populated_shape(monkeypatch):
    item = {
        "pk": "USER#matthew#SOURCE#forecast",
        "sk": "DATE#2026-07-04",
        "record_type": "forecast_summary",
        "date": "2026-07-04",
        "model": "ewma-v1",
        "confidence": Decimal("0.8"),
        "forecasts": [
            {
                "metric": "recovery_pct",
                "unit": "%",
                "horizon_days": Decimal("1"),
                "target_date": "2026-07-05",
                "point": Decimal("64.2"),
                "lo": Decimal("55"),
                "hi": Decimal("73.4"),
                "frame": "tomorrow",
            }
        ],
        "resolutions_today": [
            {
                "metric": "recovery_pct",
                "horizon_days": Decimal("1"),
                "target_date": "2026-07-04",
                "point": Decimal("62"),
                "lo": Decimal("53"),
                "hi": Decimal("71"),
                "actual": Decimal("66"),
                "covered": True,
            }
        ],
        "coverage": {"n_resolved": Decimal("5"), "n_covered": Decimal("4"), "coverage_pct": Decimal("80")},
        "run_id": "r1",
        "phase": "experiment",
    }
    monkeypatch.setattr(intel, "table", FakeDdbTable(rows=[item]))

    resp = intel.handle_forecast()
    assert resp["statusCode"] == 200
    body = __import__("json").loads(resp["body"])
    assert body["available"] is True
    assert body["model"] == "ewma-v1"
    assert body["forecasts"][0]["point"] == 64.2
    assert body["resolutions_today"][0]["covered"] is True
    assert body["coverage"]["coverage_pct"] == 80
    # anti-causal framing ships in the payload
    assert "not causal" in body["framing"]
    # internal keys stripped
    for k in ("pk", "sk", "run_id", "phase", "record_type"):
        assert k not in body


def test_forecast_empty(monkeypatch):
    monkeypatch.setattr(intel, "table", FakeDdbTable(rows=[]))
    resp = intel.handle_forecast()
    body = __import__("json").loads(resp["body"])
    assert body["available"] is False
