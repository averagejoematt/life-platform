"""tests/test_coaching_dashboard_paused_1971.py — #1971: the coaching door's
FIRST screen gets the #802 paused disclosure.

THE GAP (fullreview cpo-2, confirmed 2026-07-28 and again 2026-08-02): #802
wired the budget-guard pause signal into /api/coach_analysis only — the
/api/coaching-dashboard payload (the roster the door renders first) carried no
`regeneration_paused` key at all, and coaching.js hardcoded `false` on the
roster render. Under a tier >= 2 pause a reader saw "as of <date>" presented
as merely dated, not paused-and-frozen — while the frozen text cited a stale
weight the cockpit had already moved past.

Pinned here (the pattern mirrors test_coaches_api.py's coach_analysis pair):

  - at budget tier 2 (SSM mocked via budget_guard.current_tier) the dashboard
    payload carries `regeneration_paused: True`;
  - at tier 0 it carries an explicit `False` — present, never absent, so the
    front-end's strict `=== true` reader distinguishes "not paused" from
    "field not deployed yet" (absent = unknown = render nothing new);
  - the shaped-empty CATASTROPHIC fallback deliberately omits the field
    (unknown, not false) — asserted against the source so a refactor can't
    quietly start fabricating a not-paused claim in the failure path.

Offline: no AWS, no SSM — the fake table serves nothing and every inner read
falls through its own try/except to the shaped-empty branches.
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from ai import budget_guard  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import site_api_lambda as L  # noqa: E402

_EVENT = {"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}


def _dashboard_body(monkeypatch, tier):
    monkeypatch.setattr(L, "table", FakeDdbTable())
    monkeypatch.setattr(L, "_integrator_digest", lambda: None)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)
    resp = L.lambda_handler(dict(_EVENT), None)
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def test_dashboard_flags_regeneration_paused_at_tier_2(monkeypatch):
    body = _dashboard_body(monkeypatch, tier=2)
    assert body["regeneration_paused"] is True


def test_dashboard_not_paused_at_tier_0_field_still_present(monkeypatch):
    body = _dashboard_body(monkeypatch, tier=0)
    # Explicit False, never absent: the front-end reads strictly (`=== true`)
    # and treats an ABSENT field as unknown (the deploy-race state) — so the
    # healthy payload must carry the field to say "checked, and not paused".
    assert body["regeneration_paused"] is False


def test_catastrophic_fallback_omits_the_field_rather_than_claiming_not_paused():
    """The outer-exception shaped-empty response must NOT carry
    regeneration_paused: an error state is UNKNOWN, and fabricating `false`
    there would render a frozen board as merely dated — the exact dishonesty
    #1971 removes. Asserted against the source (the fallback is a literal).

    #2876 moved the inline `/api/coaching-dashboard` branch (and every other
    early-return route) out of `lambda_handler` and into `_dispatch_route`,
    the single dispatch exit point — so the fallback literal now lives there.
    """
    import inspect

    src = inspect.getsource(L._dispatch_route)
    fallback = next(line for line in src.splitlines() if "coaching-dashboard failed" in line or ('"weekly_priority": {}' in line))
    assert "regeneration_paused" not in fallback
