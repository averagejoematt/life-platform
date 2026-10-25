"""#5029 — the public HR series endpoints carry ONE neutral `baseline_change` date, from hr_regime, and nothing clinical.

Owner ruling 2026-10-25: any public HR-derived chart breaks or footnotes at the marker date as a
"baseline change", with no reason given and no re-baselining label. The front-end never hard-codes the
date, so the API serves it: `/api/pulse_history` (resting HR, HRV, recovery, strain), `/api/zone2`
(weekly zone-2 minutes) and `/api/vitals_depth` (walking HR, VO2max). The value is read through
`web.baseline_change` -- the public layer never imports `hr_regime` (the guard in
test_hr_regime_surfaces_5029 stays green). No asserted value reads a clock.
"""

from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LAMBDAS = os.path.join(ROOT, "lambdas")
for _p in (LAMBDAS, ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)

os.environ.setdefault("TABLE_NAME", "life-platform")

from health import hr_regime  # noqa: E402
from web import (
    baseline_change as bc,  # noqa: E402
    site_api_autonomic as az,  # noqa: E402
    site_api_vitals_depth as vd,  # noqa: E402
)

CLINICAL = re.compile(r"atrial|fibrillation|afib|\bAF\b|metoprolol|medicat|diagnos|clinical|arrhythm|re-baselin|rebaselin|regime", re.I)


def test_the_date_is_the_marker_registry_date_and_only_a_date():
    assert bc.baseline_change_date() == hr_regime.HR_REGIME_MARKERS[-1]["date"] == "2026-10-10"
    out = bc.with_baseline_change({"x": 1})
    assert out == {"x": 1, "baseline_change": "2026-10-10"}
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", out["baseline_change"])


def test_zone2_payload_carries_it_additively(monkeypatch):
    monkeypatch.setattr(az, "_query_source", lambda *a, **k: [])
    resp = az.handle_zone2_breakdown()
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["baseline_change"] == "2026-10-10"
    assert not CLINICAL.search(json.dumps(body)), "a clinical word reached the public payload"


def test_vitals_depth_payload_carries_it(monkeypatch):
    monkeypatch.setattr(vd, "_vo2max_arc", lambda: {"available": False})
    monkeypatch.setattr(vd, "_walking_hr", lambda: {"available": False})
    body = json.loads(vd.handle_vitals_depth()["body"])
    assert body["baseline_change"] == "2026-10-10"
    assert not CLINICAL.search(json.dumps(body))


def test_pulse_history_wraps_its_payload():
    src = open(os.path.join(LAMBDAS, "web", "site_api_pulse.py"), encoding="utf-8").read()
    assert '_ok(with_baseline_change({"pulse_history": days}), cache_seconds=3600)' in src


def test_public_layer_names_nothing_clinical_and_never_imports_the_marker_module():
    web = os.path.join(LAMBDAS, "web")
    for name in ("baseline_change.py", "site_api_pulse.py", "site_api_autonomic.py", "site_api_vitals_depth.py"):
        src = open(os.path.join(web, name), encoding="utf-8").read()
        if name.startswith("site_api"):
            assert "hr_regime" not in src and "re-baselining" not in src, f"{name} names the marker module"
            assert "from web.baseline_change import with_baseline_change" in src
    # the one door's own docstring/code stays free of any diagnosis or drug
    door = open(os.path.join(web, "baseline_change.py"), encoding="utf-8").read()
    assert not re.search(r"atrial|fibrillation|afib|metoprolol|medicat|diagnos", door, re.I)
