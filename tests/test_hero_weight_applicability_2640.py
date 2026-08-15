"""#2640 — the hero-weight check was armed; what it could not do was say when it checked nothing.

The issue asked which of two things was true, **by measurement**: (1) the mutation attempt
used a payload the check could not read, or (2) a pre-start branch swallows the check.

MEASURED 2026-08-15 against the live `/api/journey`, five days into cycle 13:

    pre_start False · current_weight_lbs 317.2 · start_weight_lbs 321.6 · lost_lbs 4.4
    weighin_count 2 · weighin_span_days 1

    assess_hero_weight(live)                    -> (True,  "stat row reconciles …")
    assess_hero_weight(live with lost_lbs +40)  -> (False, "stat row fails arithmetic: …
                                                    residual 40.0 … can't reconcile it")

**It is (1).** The check is armed today, and an impossible number reds it with a specific
message. The census attempt used `{start 200, current 190, lost 10}`; the assessor reads
`start_weight_lbs` / `current_weight_lbs` / `lost_lbs`, so `current_weight_lbs` was absent,
which is `None`, which takes the early return. Same verdict both ways — not because a
pre-start branch was suppressing a live cycle, but because the payload never reached the
arithmetic. The census entry said it could not distinguish the two inside its time-box; this
is the distinguishing measurement.

WHICH LEAVES THE THING THE MEASUREMENT ACTUALLY FOUND. The early return is
`return True, "no weight claim to reconcile"`, and the caller rendered that as a **green
check**. A green from a check that examined nothing is indistinguishable from a green from a
check that examined something and liked it — the exact ADR-104 class this whole QA surface
exists to police, sitting inside the police.

The window is real, not theoretical: it opens at every genesis (#931/#939 stage the
countdown with weight fields nulled by design) and re-opens for as long as Matthew does not
weigh in. So the issue's third box applies — it *can* suppress during a live cycle — and the
ruling is that a suppressed check must not report green.

`chronic=True` is the sanctioned verdict for precisely this, per `Check.warn`'s own
docstring: "a known-recurring TIMING condition … the source is event-driven/sync-lagged and
the null recurs on a healthy platform". Fully visible in the email, the logs and
`ChronicWarnCount`; it does not increment the alarmed `WarnCount`, so a novel warn class
stays unmissable. And it un-chronics itself the moment a weigh-in lands, because the branch
is chosen by `hero_weight_applicable(journey)` rather than by a flag anyone has to remember
to clear.

SCOPE, recorded because #2578's verdict layer now requires it: `assess_hero_weight` proves
the ARITHMETIC and the trend-honesty rule over a payload it is given. It does not prove the
payload matches what the browser renders — `story.js` reads the same fields, but nothing here
executes it. That is a separate check and a separate proof.
"""

from __future__ import annotations

import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

for _k, _v in {
    "S3_BUCKET": "matthew-life-platform",
    "TABLE_NAME": "life-platform",
    "DDB_TABLE": "life-platform",
    "USER_ID": "matthew",
    "AWS_REGION": "us-west-2",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_ACCESS_KEY_ID": "FAKE",
    "AWS_SECRET_ACCESS_KEY": "FAKE",
    "EMAIL_RECIPIENT": "qa@example.com",
    "EMAIL_SENDER": "qa@example.com",
    "SITE_BASE_URL": "https://averagejoematt.com",
}.items():
    os.environ.setdefault(_k, _v)

import pytest  # noqa: E402
from operational.weight_truth_qa import assess_hero_weight, hero_weight_applicable  # noqa: E402

# The live payload, 2026-08-15 — real shape, real key names. The census attempt's payload is
# kept beside it because the difference between them IS the finding.
LIVE = {
    "pre_start": False,
    "current_weight_lbs": 317.2,
    "start_weight_lbs": 321.6,
    "lost_lbs": 4.4,
    "weighin_count": 2,
    "weighin_span_days": 1,
}
CENSUS_ATTEMPT = {"start": 200, "current": 190, "lost": 10}


# ── the measurement that answers the issue's first box ───────────────────────


def test_the_check_is_armed_on_the_real_payload():
    ok, msg = assess_hero_weight(LIVE)
    assert ok is True and "reconciles" in msg


def test_an_impossible_delta_reds_it():
    """The mutation the census could not land, landed."""
    bad = dict(LIVE, lost_lbs=44.4)
    ok, msg = assess_hero_weight(bad)
    assert ok is False
    assert "fails arithmetic" in msg and "residual 40.0" in msg


def test_the_census_payload_could_not_reach_the_arithmetic():
    """It is (1), not (2) — and this is why both its payloads returned the same verdict."""
    assert hero_weight_applicable(CENSUS_ATTEMPT) is False, "the wrong key names read as 'no weigh-in'"
    consistent = assess_hero_weight(dict(CENSUS_ATTEMPT))
    inconsistent = assess_hero_weight(dict(CENSUS_ATTEMPT, lost=42))
    assert consistent == inconsistent, "the census saw identical verdicts; reproduce that here so the diagnosis is checkable"
    assert "no weight claim to reconcile" in consistent[1]


# ── the applicability predicate ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "journey,applicable",
    [
        (LIVE, True),
        (dict(LIVE, pre_start=True), False),
        (dict(LIVE, current_weight_lbs=None), False),
        ({}, False),
        (CENSUS_ATTEMPT, False),
    ],
)
def test_applicability_is_decided_by_the_payload_not_a_flag(journey, applicable):
    assert hero_weight_applicable(journey) is applicable


def test_a_zero_weight_is_applicable_not_absent():
    """`0` is falsy; a payload genuinely reporting zero must not read as 'no weigh-in'."""
    assert hero_weight_applicable(dict(LIVE, current_weight_lbs=0)) is True


# ── the verdict the caller now renders ───────────────────────────────────────


def _run_check(journey, monkeypatch):
    import operational.qa_smoke_lambda as qa

    class _Resp:
        def __init__(self, payload):
            self._p = payload

        def read(self):
            import json

            return json.dumps({"journey": self._p}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(qa.urllib.request, "urlopen", lambda *a, **k: _Resp(journey))
    return qa.check_hero_weight_arithmetic()[0]


def test_a_reconciling_payload_is_still_a_plain_green(monkeypatch):
    c = _run_check(LIVE, monkeypatch)
    assert c.passed is True and c.chronic is False


def test_an_impossible_payload_is_still_red(monkeypatch):
    """The fix must not have softened a real failure into a warning."""
    c = _run_check(dict(LIVE, lost_lbs=44.4), monkeypatch)
    assert c.passed is False


@pytest.mark.parametrize("journey", [dict(LIVE, pre_start=True), dict(LIVE, current_weight_lbs=None)])
def test_nothing_to_reconcile_is_a_visible_non_alarming_warn_not_a_green(journey, monkeypatch):
    """THE FINDING. A check that examined nothing may not report the same colour as a check
    that examined something and liked it."""
    c = _run_check(journey, monkeypatch)
    assert c.passed is None, "a suppressed check must not read as green"
    assert c.chronic is True, "…and must not alarm either — it recurs on a healthy platform"
    assert "no weight claim to reconcile" in c.message


def test_the_warn_unchronics_itself_when_a_weigh_in_lands(monkeypatch):
    """No flag to remember to clear: the branch is chosen by the payload."""
    assert _run_check(dict(LIVE, current_weight_lbs=None), monkeypatch).passed is None
    assert _run_check(LIVE, monkeypatch).passed is True


def test_a_fetch_failure_is_still_fail_soft(monkeypatch):
    """Unchanged: a network blip must never red the nightly."""
    import operational.qa_smoke_lambda as qa

    def _boom(*a, **k):
        raise OSError("connection reset")

    monkeypatch.setattr(qa.urllib.request, "urlopen", _boom)
    c = qa.check_hero_weight_arithmetic()[0]
    assert c.passed is None and c.chronic is False, "a novel failure must stay on the alarmed side"
