"""tests/test_survival_derived_horizon_3495.py — #3495 (carried from #3621 qs ROW7):
/api/survival reports a horizon DERIVED from the prior cycles, never a hand-typed 30.

THE RESIDUE: #3549 made the odds honest (no censored cycle shorter than the horizon
counts as a survivor), but the route still passed a fixed `_SURVIVAL_HORIZON = 30`,
so the page led with "odds of day 30" over a record in which no cycle had been
observed at day 30 since 2026-06-14 — an n=0 headline that could not acquire an
observation at the cadence the record runs at.

THE RULE: the served `horizon_days` is the largest day H <= 30 (the target) that at
least `_SURVIVAL_MIN_REACHED` prior cycles were observed engaged through — the SAME
floor the odds are served against — so the payload speaks at a day the record can
answer, with n and the reached count stated AT that day.

The mutation control (`test_a_hand_typed_30_fails_the_contract`) re-runs the route
with the derivation replaced by the old constant and proves the contract check reds.
Dates derive from a live now(PT) — never wall-clock literals.
"""

import ast
import inspect
import json
import os
import sys
import textwrap
from datetime import datetime, timedelta

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from web import site_api_common as common, site_api_rollups as rollups  # noqa: E402

TARGET = rollups._SURVIVAL_TARGET
FLOOR = rollups._SURVIVAL_MIN_REACHED

# The prior-cycle tuples (collapse_day | None, window_days) of the 2026-09-05 record
# (#3549's fixture): longest alive run 13 days (collapse on day 14 of a 25-day window).
LIVE_PRIORS_2026_09_05 = [(13, 20), (2, 6), (14, 25), (2, 7), (2, 5), (2, 9), (3, 8), (1, 6)] + [
    (None, 6),
    (None, 1),
    (None, 1),
    (None, 1),
    (None, 2),
    (None, 7),
    (None, 4),
]


# ── 1. the pure derivation ────────────────────────────────────────────────────


class TestSurvivalHorizonPure:
    def test_the_live_record_speaks_at_its_longest_observed_run(self):
        assert rollups.survival_horizon(LIVE_PRIORS_2026_09_05) == 13
        odds = rollups.survival_odds(LIVE_PRIORS_2026_09_05)
        assert odds["horizon_days"] == 13
        assert odds["reached_horizon_n"] == 1  # the 25-day cycle that collapsed on day 14
        assert odds["n_prior_cycles"] == 15
        assert odds["p_reach_pct"] == round((1 + 1) / (15 + 2) * 100) == 12
        assert odds["p_reach_ci95_pct"] is not None
        assert odds["p_reach_ceiling_pct"] is None
        # n and the reached count are stated AT the derived horizon.
        assert "n=15 prior cycles · 1 reached day 13" in odds["confidence"]
        assert "The horizon is day 13, not day 30" in odds["method"]

    def test_the_horizon_is_capped_at_the_target(self):
        priors = [(None, 45), (40, 60), (3, 9)]
        assert rollups.survival_horizon(priors) == TARGET
        odds = rollups.survival_odds(priors)
        assert odds["horizon_days"] == TARGET and odds["reached_horizon_n"] == 2
        assert "not day" not in odds["method"], "at the target there is nothing to explain"

    def test_the_horizon_moves_with_the_record(self):
        """Positive control: a longer prior run lifts the horizon one-for-one —
        the value is read from the record, not from a constant."""
        for run in (1, 5, 13, 29):
            assert rollups.survival_horizon([(None, run), (2, 8)]) == max(run, 1)
            assert rollups.survival_horizon([(run + 1, run + 6), (2, 8)]) == max(run, 1)

    def test_a_censored_cycle_shorter_than_the_derived_horizon_never_counts(self):
        """Epic box 1 holds at the derived horizon: the censored 6-day cycle stays in
        n and does not reach day 13."""
        odds = rollups.survival_odds([(14, 25), (None, 6), (None, 2)])
        assert odds["horizon_days"] == 13
        assert odds["reached_horizon_n"] == 1
        assert odds["censored_before_horizon_n"] == 2

    def test_no_answerable_day_falls_back_to_the_target_and_serves_no_odds(self):
        assert rollups.survival_horizon([]) == TARGET
        dead_on_day_one = [(1, 6), (1, 3)]  # collapse on day 1 => alive 0 days
        assert rollups.survival_horizon(dead_on_day_one) == TARGET
        odds = rollups.survival_odds(dead_on_day_one)
        assert odds["p_reach_pct"] is None and odds["p_reach_ceiling_pct"] == round(100 / 4)

    def test_the_floor_is_the_one_the_odds_use(self):
        """The derived horizon always clears the odds floor, so a derived horizon
        never serves a ceiling while a run >= 1 day exists. The method sentence
        says 'any prior cycle' — that wording is exact only at a floor of 1."""
        assert FLOOR == 1
        for priors in (LIVE_PRIORS_2026_09_05, [(None, 3)], [(None, 40), (2, 5)]):
            odds = rollups.survival_odds(priors)
            assert odds["reached_horizon_n"] >= FLOOR and odds["p_reach_pct"] is not None
        # a floor of 2 takes the 2nd-longest run
        assert rollups.survival_horizon([(None, 20), (None, 9), (3, 8)], floor=2) == 9


# ── 2. the endpoint + the mutation control ────────────────────────────────────


def _today_pt():
    return datetime.now(common.PT).date()


def _short_record():
    """Four closed cycles whose longest observed run is 13 days, then the live one."""
    today = _today_pt()
    spans = [(25, 13), (6, 6), (8, 2), (4, 4)]  # (window, engaged-from-day-0)
    geneses, engaged = {}, {}
    day = today - timedelta(days=sum(w for w, _ in spans) + 3)
    for i, (w, e) in enumerate(spans, start=1):
        geneses[i] = day.isoformat()
        engaged[i] = set(range(e))
        day += timedelta(days=w)
    geneses[len(spans) + 1] = (today - timedelta(days=2)).isoformat()
    engaged[len(spans) + 1] = {0, 1, 2}
    return geneses, engaged


def _serve(geneses, engaged, monkeypatch):
    by_genesis = {g: n for n, g in geneses.items()}

    def _engaged_dates(start, end, *, _g):
        g = datetime.strptime(start, "%Y-%m-%d").date()
        return {(g + timedelta(days=i)).isoformat() for i in engaged.get(by_genesis[start], set())}

    monkeypatch.setattr(rollups, "_engaged_dates", _engaged_dates)
    resp = rollups.survival(_g={"CYCLE_GENESES": geneses, "_query_source": lambda *a, **k: []})
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _horizon_contract_offenders(body):
    """Recompute the horizon from the served `cycles` log alone and report every way
    the payload disagrees with it."""
    priors = [c for c in body["cycles"] if not c["is_current"]]
    alive = sorted(((c["collapse_day"] - 1) if c["collapse_day"] else c["window_days"] for c in priors), reverse=True)
    expected = min(TARGET, alive[FLOOR - 1]) if len(alive) >= FLOOR and alive[FLOOR - 1] >= 1 else TARGET
    offenders = []
    if body["horizon_days"] != expected:
        offenders.append(f"horizon_days {body['horizon_days']} != derived {expected}")
    reached = sum(1 for a in alive if a >= body["horizon_days"])
    if body["reached_horizon_n"] != reached:
        offenders.append(f"reached_horizon_n {body['reached_horizon_n']} != {reached} recomputed at the served horizon")
    if f"reached day {body['horizon_days']}" not in body["confidence"]:
        offenders.append("confidence does not state the reached count at the served horizon")
    return offenders


class TestSurvivalEndpointHorizon:
    def test_the_route_serves_the_derived_horizon(self, monkeypatch):
        geneses, engaged = _short_record()
        body = _serve(geneses, engaged, monkeypatch)
        assert _horizon_contract_offenders(body) == []
        assert body["horizon_days"] == 13
        assert body["reached_horizon_n"] == 1 and body["n_prior_cycles"] == 4
        assert body["p_reach_30_pct"] == round(2 / 6 * 100) == 33
        assert "The horizon is day 13, not day 30" in body["method"]

    def test_a_hand_typed_30_fails_the_contract(self, monkeypatch):
        """MUTATION CONTROL: restore the pre-#3495 behaviour (the route speaks at the
        fixed target) and the contract check must red — so the test above cannot
        pass on a constant that happens to agree with the fixture."""
        monkeypatch.setattr(rollups, "survival_horizon", lambda priors, *a, **k: 30)
        geneses, engaged = _short_record()
        body = _serve(geneses, engaged, monkeypatch)
        assert body["horizon_days"] == 30
        offenders = _horizon_contract_offenders(body)
        assert any("horizon_days 30 != derived 13" in o for o in offenders), offenders

    def test_the_route_passes_no_horizon_literal(self):
        """Source half: survival() calls survival_odds without a horizon argument and
        builds `horizon_days` from the odds block, never from a constant."""
        tree = ast.parse(textwrap.dedent(inspect.getsource(rollups.survival)))
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "survival_odds"]
        assert len(calls) == 1, "positive control: the route calls survival_odds exactly once"
        assert not calls[0].keywords and len(calls[0].args) == 1, "the route must let survival_odds derive the horizon"
        int_literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and type(n.value) is int}
        assert TARGET not in int_literals, f"a literal {TARGET} in survival() is the #3495 defect class"
        assert "_SURVIVAL_TARGET" not in inspect.getsource(rollups.survival)
