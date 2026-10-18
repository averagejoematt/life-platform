"""#4935 (fcd7d5) — a trend row's top-level figures never mix Eight Sleep's non-detect with Whoop.

Fixture = the two stored rows for 2026-09-19 as read from DynamoDB (shapes verbatim): Eight Sleep
slept 1.7 h of a 10.04 h session (efficiency 16.9, score 38); Whoop 8.61 h, 84.8 %, quality 83,
recovery 98. Rule: when the score gate discounts the Eight Sleep night, `efficiency` comes from
Whoop beside Whoop's `hours` and `sleep_score`; the nested eightsleep block keeps the raw figures.
"""

from __future__ import annotations

import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
for _p in (os.path.join(ROOT, "lambdas"), ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from web import site_api_vitals as vitals  # noqa: E402

_EIGHT = {
    "pk": "USER#matthew#SOURCE#eightsleep",
    "sk": "DATE#2026-09-19",
    "sleep_start": "2026-09-19T06:46:30Z",
    "sleep_end": "2026-09-19T14:58:30Z",
    "time_in_bed_hours": 10.04,
    "sleep_duration_hours": 1.7,
    "deep_hours": 0.05,
    "rem_hours": 0.47,
    "light_hours": 1.18,
    "awake_hours": 8.34,
    "waso_hours": 8.31,
    "sleep_efficiency_pct": 16.9,
    "sleep_score": 38,
    "vendor_incomplete": False,
}
_WHOOP = {
    "pk": "USER#matthew#SOURCE#whoop",
    "sk": "DATE#2026-09-19",
    "sleep_duration_hours": 8.61,
    "sleep_efficiency_percentage": 84.8,
    "sleep_quality_score": 83,
    "recovery_score": 98,
}


def _row(monkeypatch, eight, whoop):
    def fake(source, start, end, include_pilot=False):
        return [dict(eight)] if source == "eightsleep" else [dict(whoop)]

    monkeypatch.setattr(vitals, "EXPERIMENT_START", "2026-09-01")
    monkeypatch.setattr(vitals, "_query_source", fake)
    resp = vitals.handle_sleep_detail()
    assert resp["statusCode"] == 200
    return json.loads(resp["body"])["sleep_trend"][0]


def test_non_detect_night_serves_whoop_efficiency_beside_whoop_hours_and_score(monkeypatch):
    row = _row(monkeypatch, _EIGHT, _WHOOP)
    assert (row["hours"], row["sleep_score"], row["efficiency"]) == (8.6, 83.0, 84.8)
    # the raw vendor figures stay, labelled, in the nested per-device block
    assert row["eightsleep"]["sleep_efficiency_pct"] == 16.9
    assert row["eightsleep"]["total_sleep_hours"] == 1.7


def test_non_detect_night_without_whoop_efficiency_is_honestly_absent(monkeypatch):
    whoop = {k: v for k, v in _WHOOP.items() if k != "sleep_efficiency_percentage"}
    assert _row(monkeypatch, _EIGHT, whoop)["efficiency"] is None


def test_a_real_night_keeps_eight_sleep_efficiency(monkeypatch):
    eight = dict(_EIGHT, sleep_score=78, sleep_efficiency_pct=91.0, sleep_duration_hours=7.9)
    assert _row(monkeypatch, eight, _WHOOP)["efficiency"] == 91.0
