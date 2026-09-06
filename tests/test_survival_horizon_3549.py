"""tests/test_survival_horizon_3549.py — #3549: the odds of day 30 are horizon-checked,
derived, and reproducible from the served log by the served method string.

THE LIVE DEFECT (2026-09-05, /review full DV-1/R3): `/api/survival` served
`p_reach_30_pct 47` over 15 prior cycles of which SEVEN "survivors" were cycles
re-anchored on days 1–7 while still engaged (censored) and ZERO had ever been
observed at day 30. `survivors = cd is None or cd > 30` had no `window >= horizon`
test; the served `method` said "n=2 is narrative" beside a computed 15; the
`confidence` string said "n=2 cycles" — a literal that outlived the two-prior era
it was written in by thirteen cycles.

Three contracts, each with a positive control so the test cannot pass vacuously:

  1. An all-censored short-cycle record NEVER produces odds: `p_reach_30_pct` is
     None, and the Laplace residue 1/(n+2) is served as a CEILING, named as such.
  2. Every served string's `n=<int>` equals a numeric field in the same payload
     (the #2003 idea applied to API prose) — and the strings move when n moves.
  3. Whenever odds ARE served, p <= (reached + 1)/(n + 2) with reached counting
     ONLY cycles known engaged through the horizon — a censored day-7 cycle never
     lifts it.

Dates derive from a live now(PT) — never wall-clock literals.
"""

import json
import os
import re
import sys
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

import pytest  # noqa: E402
from web import site_api_common as common, site_api_rollups as rollups  # noqa: E402

H = rollups._SURVIVAL_HORIZON

# The live payload's prior-cycle tuples on 2026-09-05 (collapse_day, window_days):
# 8 collapsed at days [13,2,14,2,2,2,3,1]; 7 censored with windows [6,1,1,1,2,7,4].
LIVE_PRIORS_2026_09_05 = [(13, 20), (2, 6), (14, 25), (2, 7), (2, 5), (2, 9), (3, 8), (1, 6)] + [
    (None, 6),
    (None, 1),
    (None, 1),
    (None, 1),
    (None, 2),
    (None, 7),
    (None, 4),
]


# ── 1. the pure helper on the exact live tuples ───────────────────────────────


class TestSurvivalOddsPure:
    def test_the_live_record_serves_no_odds_not_47(self):
        odds = rollups.survival_odds(LIVE_PRIORS_2026_09_05, H)
        assert odds["n_prior_cycles"] == 15
        assert odds["reached_horizon_n"] == 0
        assert odds["collapsed_before_horizon_n"] == 8
        assert odds["censored_before_horizon_n"] == 7
        assert odds["longest_run_days"] == 13
        assert odds["p_reach_pct"] is None, "a horizon no cycle reached must not carry a percentage"
        assert odds["p_reach_ci95_pct"] is None
        # The Laplace residue at reached=0 — served as a ceiling, named as one.
        assert odds["p_reach_ceiling_pct"] == round(100 / 17) == 6
        assert "0 of 15 prior cycles has been observed at day 30" in odds["method"]
        assert "ceiling" in odds["method"] and "not evidence" in odds["method"]
        assert "n=15 prior cycles" in odds["confidence"]

    def test_all_censored_short_cycles_never_raise_the_odds_above_the_prior(self):
        """AC1: a fixture of all-censored 1–7-day cycles must NOT raise p30 above
        the Laplace prior 1/(n+2) — here it produces no odds at all, and the
        ceiling IS the prior."""
        priors = [(None, w) for w in (6, 1, 1, 1, 2, 7, 4)]
        odds = rollups.survival_odds(priors, H)
        assert odds["p_reach_pct"] is None
        assert odds["reached_horizon_n"] == 0
        assert odds["censored_before_horizon_n"] == 7
        assert odds["p_reach_ceiling_pct"] == round(100 / (7 + 2))

    def test_a_censored_cycle_counts_only_when_its_window_reaches_the_horizon(self):
        """Positive control for the horizon check: the SAME censored cycle lifts
        `reached` only once its window covers the horizon."""
        short = rollups.survival_odds([(None, H - 1), (5, 10)], H)
        long = rollups.survival_odds([(None, H), (5, 10)], H)
        assert short["reached_horizon_n"] == 0 and short["p_reach_pct"] is None
        assert long["reached_horizon_n"] == 1
        assert long["p_reach_pct"] == round((1 + 1) / (2 + 2) * 100) == 50

    def test_a_collapse_after_the_horizon_reached_it_and_one_on_the_horizon_did_not(self):
        # collapse_day is the FIRST silent day: collapse on day H+1 => engaged through day H.
        assert rollups.survival_odds([(H + 1, H + 5)], H)["reached_horizon_n"] == 1
        assert rollups.survival_odds([(H, H + 5)], H)["reached_horizon_n"] == 0

    def test_served_odds_never_exceed_the_laplace_bound(self):
        """AC3: p_reach <= (count of cycles known engaged through the horizon + 1)/(n+2)."""
        priors = [(None, 40), (None, 3), (12, 20), (None, 45), (2, 8), (None, 1)]
        odds = rollups.survival_odds(priors, H)
        reached = sum(1 for cd, w in priors if cd is None and w >= H)
        assert odds["reached_horizon_n"] == reached == 2
        bound = round((reached + 1) / (len(priors) + 2) * 100)
        assert odds["p_reach_pct"] is not None and odds["p_reach_pct"] <= bound
        assert odds["p_reach_pct"] == bound  # the estimator IS the bound — censored cycles never lift it
        lo, hi = odds["p_reach_ci95_pct"]
        assert 0 <= lo <= hi <= 100
        assert f"({reached}+1)/({len(priors)}+2) = {bound}%" in odds["method"]

    def test_strings_are_derived_from_n_positive_control(self):
        """AC2 positive control: mutate the prior count and the strings must follow
        — no literal 'n=2' can survive a record of 3."""
        three = rollups.survival_odds([(None, 2), (None, 3), (5, 9)], H)
        assert "n=3 prior cycles" in three["confidence"]
        assert "0 of 3 prior cycles" in three["method"]
        assert "n=2" not in three["confidence"] and "n=2" not in three["method"]
        two = rollups.survival_odds([(None, 2), (5, 9)], H)
        assert "n=2 prior cycles" in two["confidence"]

    def test_no_priors_is_nothing_to_handicap(self):
        odds = rollups.survival_odds([], H)
        assert odds["p_reach_pct"] is None and odds["p_reach_ceiling_pct"] is None
        assert odds["n_prior_cycles"] == 0
        assert "nothing to handicap" in odds["method"]


# ── 2. the endpoint: served strings agree with served numbers ─────────────────


def _today_pt():
    return datetime.now(common.PT).date()


def _survival_with_engagement(geneses, engaged_by_cycle, monkeypatch):
    """Drive survival() through the real per-cycle loop with a stubbed engagement
    read: `engaged_by_cycle[n]` is the set of engaged day-offsets (0-based) for
    cycle n."""
    by_genesis = {g: n for n, g in geneses.items()}

    def _engaged_dates(start, end, *, _g):
        n = by_genesis[start]
        g = datetime.strptime(start, "%Y-%m-%d").date()
        return {(g + timedelta(days=i)).isoformat() for i in engaged_by_cycle.get(n, set())}

    monkeypatch.setattr(rollups, "_engaged_dates", _engaged_dates)
    resp = rollups.survival(_g={"CYCLE_GENESES": geneses, "_query_source": lambda *a, **k: []})
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _walk_strings(node):
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for v in node.values():
            yield from _walk_strings(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk_strings(v)


def _numeric_fields(payload):
    return {v for v in payload.values() if isinstance(v, int) and not isinstance(v, bool)}


def _all_censored_short_record():
    """Seven prior cycles re-anchored after 1–7 engaged days each, then the live one."""
    today = _today_pt()
    windows = [6, 1, 1, 1, 2, 7, 4]
    geneses, engaged = {}, {}
    day = today - timedelta(days=sum(windows) + 2)
    for i, w in enumerate(windows, start=1):
        geneses[i] = day.isoformat()
        engaged[i] = set(range(w))  # engaged every day of its short window
        day += timedelta(days=w)
    geneses[len(windows) + 1] = (today - timedelta(days=2)).isoformat()
    engaged[len(windows) + 1] = {0, 1, 2}
    return geneses, engaged


class TestSurvivalEndpoint:
    def test_all_censored_record_serves_null_odds_and_the_counts_that_explain_it(self, monkeypatch):
        geneses, engaged = _all_censored_short_record()
        body = _survival_with_engagement(geneses, engaged, monkeypatch)
        priors = [c for c in body["cycles"] if not c["is_current"]]
        assert len(priors) == 7 and all(c["censored"] for c in priors)
        assert body["p_reach_30_pct"] is None
        assert body["reached_horizon_n"] == 0
        assert body["censored_before_horizon_n"] == 7
        assert body["n_prior_cycles"] == 7
        assert body["p_reach_30_ceiling_pct"] == round(100 / 9)
        assert body["horizon_days"] == H

    def test_every_n_literal_in_a_served_string_is_a_numeric_field_of_the_payload(self, monkeypatch):
        """AC2/#2003-for-prose: any 'n=<int>' inside a served string must equal a
        numeric field in the same payload. Positive control: the string DOES
        carry an n= literal (the check is not vacuous)."""
        geneses, engaged = _all_censored_short_record()
        body = _survival_with_engagement(geneses, engaged, monkeypatch)
        literals = [int(m) for s in _walk_strings(body) for m in re.findall(r"\bn=(\d+)", s)]
        assert literals, "the confidence string must state n"
        fields = _numeric_fields(body)
        for lit in literals:
            assert lit in fields, f"served string says n={lit} but no numeric field in the payload equals it"
        assert "n=2" not in body["confidence"] and "n=2" not in body["method"]

    def test_the_hero_can_be_recomputed_from_the_served_log_by_the_served_method(self, monkeypatch):
        """AC4 (offline half): from `cycles` alone, apply the served rule and land on
        the served numbers — one cycle engaged through day 30, the rest short."""
        today = _today_pt()
        geneses = {
            1: (today - timedelta(days=80)).isoformat(),
            2: (today - timedelta(days=40)).isoformat(),
            3: (today - timedelta(days=30)).isoformat(),
            4: (today - timedelta(days=3)).isoformat(),
        }
        engaged = {1: set(range(40)), 2: set(range(10)), 3: set(range(5)), 4: {0, 1, 2}}
        body = _survival_with_engagement(geneses, engaged, monkeypatch)
        priors = [c for c in body["cycles"] if not c["is_current"]]
        alive = [(c["collapse_day"] - 1) if c["collapse_day"] else c["window_days"] for c in priors]
        reached = sum(1 for a in alive if a >= body["horizon_days"])
        assert reached == 1 == body["reached_horizon_n"]
        assert body["n_prior_cycles"] == 3
        assert body["p_reach_30_pct"] == round((reached + 1) / (3 + 2) * 100) == 40
        assert f"({reached}+1)/(3+2) = 40%" in body["method"]
        assert body["p_reach_30_ci95_pct"] is not None

    def test_the_old_optimistic_rule_would_have_served_a_number_here(self, monkeypatch):
        """The prove-red half: on the all-censored record, the removed rule
        (`cd is None or cd > 30` => survivor) yields (7+1)/(7+2) = 89% — the
        payload must not carry that or any percentage."""
        geneses, engaged = _all_censored_short_record()
        body = _survival_with_engagement(geneses, engaged, monkeypatch)
        priors = [c for c in body["cycles"] if not c["is_current"]]
        old_rule = round((sum(1 for c in priors if c["collapse_day"] is None or c["collapse_day"] > H) + 1) / (len(priors) + 2) * 100)
        assert old_rule == 89
        assert body["p_reach_30_pct"] != old_rule and body["p_reach_30_pct"] is None


# ── 3. the source: no hand-typed n survives in the served strings ─────────────


def test_no_hardcoded_n_literal_in_the_survival_source():
    """Every string literal (f-string constant parts included) in the two functions
    is free of a hand-typed 'n=<digit>' — the #3549 defect class. Comments may
    tell the story; served prose may not carry the number."""
    import ast
    import inspect
    import textwrap

    literals = []
    for fn in (rollups.survival, rollups.survival_odds):
        tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
        literals += [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)]
    assert literals, "positive control: the functions do carry string literals"
    offenders = [lit for lit in literals if re.search(r"n=\d", lit)]
    assert not offenders, f"hand-typed n-literal in served prose: {offenders}"


@pytest.mark.parametrize(
    "field", ["p_reach_30_pct", "p_reach_30_ceiling_pct", "n_prior_cycles", "reached_horizon_n", "method", "confidence"]
)
def test_the_served_contract_carries_the_reproducibility_fields(field, monkeypatch):
    geneses, engaged = _all_censored_short_record()
    body = _survival_with_engagement(geneses, engaged, monkeypatch)
    assert field in body
