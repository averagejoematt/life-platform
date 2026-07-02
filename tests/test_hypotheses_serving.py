"""tests/test_hypotheses_serving.py — /api/hypotheses serves the machine's bets whole.

The "What the machine suspects" surface (2026-07-02) renders the engine's live
hypotheses with their verdict trail. Pins: the public:false privacy filter, the
verdict-trail passthrough (last_checked/last_evidence — added for the surface;
null until the first weekly check), and that archived bets still serve (the
front-end folds them into the honest "expired undecided" count).
"""

import json
import os
import sys

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from web import site_api_intelligence as sai  # noqa: E402


class _FakeTable:
    def __init__(self, items):
        self._items = items

    def query(self, **kwargs):
        return {"Items": self._items}


def _body(resp):
    return json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]


_ITEMS = [
    {
        "pk": "USER#matthew#SOURCE#hypotheses",
        "sk": "HYPOTHESIS#hyp_walking_speed_recovery_floor",
        "hypothesis_id": "hyp_walking_speed_recovery_floor",
        "hypothesis": "Walking speed below 2.80 mph on high-step days predicts recovery <=70.",
        "domains": ["activity", "recovery"],
        "status": "refuted",
        "confidence": "low",
        "created_at": "2026-06-28T19:00:42+00:00",
        "check_count": 2,
        "evidence": "On 2026-06-27 walking speed was 2.17 mph and recovery crashed to 30.",
        "last_checked": "2026-07-05T19:00:00+00:00",
        "last_evidence": "On 2026-07-04 speed was 2.31 mph with 9,200 steps and recovery held at 82 — the floor did not predict.",
    },
    {
        "pk": "USER#matthew#SOURCE#hypotheses",
        "sk": "HYPOTHESIS#hyp_private_thing",
        "hypothesis_id": "hyp_private_thing",
        "hypothesis": "A private observation that must never serve.",
        "status": "pending",
        "public": False,
    },
    {
        "pk": "USER#matthew#SOURCE#hypotheses",
        "sk": "HYPOTHESIS#hyp_expired",
        "hypothesis_id": "hyp_expired",
        "hypothesis": "An old bet the window closed on.",
        "status": "archived",
        "check_count": 1,
    },
]


def _hyps():
    sai.table = _FakeTable(_ITEMS)
    resp = sai.handle_hypotheses()
    assert resp["statusCode"] == 200
    return _body(resp)["hypotheses"]


def test_private_hypotheses_never_serve():
    ids = {h["hypothesis_id"] for h in _hyps()}
    assert "hyp_private_thing" not in ids


def test_verdict_trail_served():
    h = next(x for x in _hyps() if x["hypothesis_id"] == "hyp_walking_speed_recovery_floor")
    assert h["status"] == "refuted"
    assert h["last_checked"].startswith("2026-07-05")
    assert "did not predict" in h["last_evidence"]


def test_verdict_trail_null_before_first_check():
    sai.table = _FakeTable([{**_ITEMS[0], "last_checked": None, "last_evidence": None, "status": "pending", "check_count": 0}])
    h = _body(sai.handle_hypotheses())["hypotheses"][0]
    assert h["last_checked"] is None and h["last_evidence"] is None


def test_archived_still_served_for_the_expired_count():
    ids = {h["hypothesis_id"] for h in _hyps()}
    assert "hyp_expired" in ids
