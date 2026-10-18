"""#5029 — the HR-derived surfaces outside readiness read the 2026-10-10 HR regime marker.

#4999 (PR #5030) built THE registry (`lambdas/health/hr_regime.py`) and wired the readiness
models to it. These are the surfaces it did not reach; inside the marker's re-baselining window
(2026-10-10..2026-10-24) each one draws no green / yellow / red label from a heart-rate number,
and every protective flag (ACWR > 1.3 / > 1.5) is still carried:

- the daily brief: the readiness card ("RE-BASELINING", never "NO DATA"), the scorecard's
  Recovery tile, the HRV line and the ACWR line (`content.html_builder`)
- the dashboard JSON readiness label (`content.output_writers.write_dashboard_json`)
- acwr-compute's `acwr_zone` / `acwr_alert` (`compute.acwr_compute_lambda._regime_classify`)
- the Zone 2 site surfaces (`/api/training_overview`, `/api/zone2`, `evidence_body.js`,
  `evidence_autonomic.js`) and the MCP `get_zone2_breakdown`
- `/api/sleep_detail`'s Whoop recovery / HRV / RHR trio

Every date is a literal (2026-10-10..2026-10-18 inside, 2026-10-09 / 2026-10-25 outside). The one
handler that reads the wall clock (`sleep_detail`) has its clock frozen (#4848).
"""

from __future__ import annotations

import inspect
import json
import os
import re
import sys
from datetime import datetime as _real_datetime
from decimal import Decimal

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
for _p in (LAMBDAS, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from compute import acwr_compute_lambda as acwr  # noqa: E402
from content import (
    brief_hr_regime as bhr,  # noqa: E402
    html_builder as hb,  # noqa: E402
)
from health import hr_regime  # noqa: E402
from web import (
    site_api_autonomic as az,  # noqa: E402
    site_api_common as sac,  # noqa: E402
)

INSIDE = ("2026-10-10", "2026-10-14", "2026-10-18", "2026-10-24")
OUTSIDE = ("2026-10-09", "2026-10-25")
REBASE = hr_regime.REBASELINING


# ── the brief (html_builder) ────────────────────────────────────────────────────


def _scorecards(date, readiness_colour="gray", recovery=88, computed=None):
    data = {
        "date": date,
        "hrv": {"hrv_7d": 61.1, "hrv_30d": 53.5},
        "whoop": {"hrv": 52.0, "recovery_score": 62, "resting_heart_rate": 64, "strain": 9.1},
        "computed_metrics": computed or {},
    }
    return hb._brief_scorecards({}, {"recovery": recovery, "sleep_quality": 85}, data, 0, {"habit_registry": {}}, readiness_colour, {})


def test_brief_readiness_card_says_rebaselining_not_no_data_inside_the_window():
    for date in INSIDE:
        out = _scorecards(date)
        assert "RE-BASELINING" in out
        assert "NO DATA" not in out
        # the Recovery tile (Whoop recovery = HRV + RHR) wears no colour and no number-as-verdict
        tile = re.search(r'color:([#0-9a-f]+);font-size:18px;font-weight:700;margin:2px 0;">re-baselining<', out)
        assert tile and tile.group(1) == bhr.REBASELINING_GREY
        assert "re-baselining after the HR regime marker" in out  # the HRV line


def test_brief_readiness_card_reads_the_stored_readiness_state_too():
    # a computed_metrics row that already says re-baselining wins even off-registry
    out = _scorecards("2026-11-30", computed={"readiness_state": REBASE})
    assert "RE-BASELINING" in out and "NO DATA" not in out


def test_brief_outside_the_window_is_unchanged():
    for date in OUTSIDE:
        out = _scorecards(date)
        assert "RE-BASELINING" not in out
        assert "NO DATA" in out  # gray outside the window still means no data
        assert '#22c55e;font-size:18px;font-weight:700;margin:2px 0;">88<' in out  # recovery 88 >= 80 is green


def test_brief_green_readiness_inside_the_window_is_withheld():
    # a pre-#4999 stored colour ("green") must not render GO inside the window
    out = _scorecards("2026-10-18", readiness_colour="green")
    assert "RE-BASELINING" in out and ">GO<" not in out


def _acwr_line(date, acwr_val, zone, alert):
    data = {"date": date, "computed_metrics": {"acwr": acwr_val, "acwr_zone": zone, "acwr_alert": alert, "acwr_alert_reason": "r"}}
    out = hb._brief_training_body(data, 0, 0, {"habit_registry": {}}, None)
    m = re.search(r'ACWR: <span style="color:([#0-9a-f]+);', out)
    return m.group(1) if m else None


def test_brief_acwr_line_has_no_safe_green_inside_the_window_but_keeps_the_alert_red():
    assert _acwr_line("2026-10-18", 1.05, "safe", False) == bhr.REBASELINING_GREY
    assert _acwr_line("2026-10-18", 0.7, REBASE, False) == bhr.REBASELINING_GREY
    assert _acwr_line("2026-10-18", 1.62, "danger", True) == "#ef4444"  # protective flag carried
    assert _acwr_line("2026-10-25", 1.05, "safe", False) == "#22c55e"  # outside: unchanged


# ── acwr-compute ────────────────────────────────────────────────────────────────


def test_acwr_zone_rebaselines_safe_and_detraining_inside_the_window():
    for date in INSIDE:
        assert acwr._regime_classify(1.05, date)[:2] == (REBASE, False)
        assert acwr._regime_classify(0.6, date)[:2] == (REBASE, False)


def test_acwr_protective_high_side_is_never_withheld():
    for date in INSIDE + OUTSIDE:
        zone, alert, reason = acwr._regime_classify(1.62, date)
        assert (zone, alert) == ("danger", True)
        assert acwr._regime_classify(1.4, date)[:2] == ("caution", True)
        assert "above 1.5" in reason


def test_acwr_outside_the_window_is_the_population_classifier():
    for date in OUTSIDE:
        for v in (None, 0.6, 1.05, 1.4, 1.62):
            assert acwr._regime_classify(v, date) == acwr._classify_acwr(v)


def test_acwr_handler_writes_the_regime_classification():
    src = inspect.getsource(acwr._lambda_handler_impl)
    assert "_regime_classify(acwr, target_date)" in src and "_classify_acwr(acwr)" not in src


# ── dashboard JSON label ────────────────────────────────────────────────────────


def test_dashboard_readiness_label_reads_the_marker():
    for date in INSIDE:
        assert bhr.dashboard_readiness(None, "gray", date) == {"score": None, "color": "gray", "label": "Re-baselining", "training_rec": ""}
        assert bhr.dashboard_readiness(70.9, "green", date)["label"] == "Re-baselining"  # a stale green never says Go
    for date in OUTSIDE:
        assert bhr.dashboard_readiness(None, "gray", date)["label"] == "No Data"
        assert bhr.dashboard_readiness(80, "green", date) == {
            "score": 80,
            "color": "green",
            "label": "Go",
            "training_rec": "Hard workout OK · Follow today's plan",
        }
    from content import output_writers as ow

    assert "brief_hr_regime.dashboard_readiness(readiness_score, readiness_colour, yesterday)" in inspect.getsource(ow.write_dashboard_json)


# ── site: the public reduction ──────────────────────────────────────────────────


def test_site_block_inside_the_window_publishes_only_the_reduction():
    for date in INSIDE:
        b = sac.hr_regime_public(date)
        assert b["state"] == REBASE and b["through"] == "2026-10-24"
        assert "zone2_pct" in b["components"] and "eightsleep_hrv_avg" in b["components"]
        # never the marker kind, its memory reference, or the owner-only note
        blob = json.dumps(b)
        assert "MEMORY#" not in blob and "hr_regime_change" not in blob and "constraint" not in blob


def test_site_block_outside_the_window_is_absent():
    for date in OUTSIDE:
        assert sac.hr_regime_public(date) is None


def _strava(dates):
    return [
        {
            "sk": f"DATE#{d}",
            "date": d,
            "activities": [
                {"name": "Z2", "sport_type": "Run", "moving_time_seconds": 2700, "average_heartrate": 124.0, "zone2_seconds": 2700}
            ],
        }
        for d in dates
    ]


def test_api_zone2_carries_the_block_inside_and_not_outside():
    days = ("2026-10-05", "2026-10-12", "2026-10-16")
    inside = az._compute_zone2_breakdown(_strava(days), today="2026-10-18", start_date="2026-09-20")
    assert inside["hr_regime"]["state"] == REBASE
    outside = az._compute_zone2_breakdown(_strava(days), today="2026-10-25", start_date="2026-09-20")
    assert outside["hr_regime"] is None


def test_training_overview_and_sleep_detail_attach_the_block():
    from web import site_api_sleep, site_api_training

    assert '"hr_regime": hr_regime_public(today)' in inspect.getsource(site_api_training.training_overview)
    assert '"hr_regime": hr_regime_public(today)' in inspect.getsource(site_api_sleep.sleep_detail)


class _FrozenDatetime(_real_datetime):
    @classmethod
    def now(cls, tz=None):
        return _real_datetime(2026, 10, 18, 12, 0, tzinfo=tz)


def test_sleep_detail_live_handler_inside_the_window(monkeypatch):
    from web import site_api_vitals as vit

    monkeypatch.setattr(vit, "EXPERIMENT_START", "2026-09-06")
    monkeypatch.setattr(vit, "datetime", _FrozenDatetime)
    eight = [{"sk": "DATE#2026-10-17", "sleep_score": Decimal("82"), "sleep_efficiency_pct": Decimal("90"), "hrv_avg": Decimal("55.9")}]
    whoop = [{"sk": "DATE#2026-10-17", "recovery_score": Decimal("62"), "hrv": Decimal("52"), "resting_heart_rate": Decimal("64")}]
    monkeypatch.setattr(vit, "_query_source", lambda source, *_a, **_k: {"eightsleep": eight, "whoop": whoop}.get(source, []))
    body = json.loads(vit.handle_sleep_detail()["body"])
    assert body["sleep_detail"]["hr_regime"]["state"] == REBASE


# ── front-end + MCP ─────────────────────────────────────────────────────────────


def test_front_end_labels_zone2_rebaselining_from_the_block():
    body = open(os.path.join(ROOT, "site", "assets", "js", "evidence_body.js"), encoding="utf-8").read()
    assert 't.hr_regime ? "zone-2 target · re-baselining" : "zone-2 target"' in body
    auto = open(os.path.join(ROOT, "site", "assets", "js", "evidence_autonomic.js"), encoding="utf-8").read()
    assert "if (d.hr_regime) parts.push(" in auto


def test_mcp_zone2_breakdown_reads_the_marker():
    src = open(os.path.join(ROOT, "mcp", "tools_correlation.py"), encoding="utf-8").read()
    assert '"hr_regime": hr_regime.regime_status(end_date)' in src
