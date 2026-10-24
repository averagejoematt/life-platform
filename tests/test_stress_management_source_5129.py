"""tests/test_stress_management_source_5129.py — Mind's stress_management reads REPORTED stress (#5129).

Before: `compute_mind_raw` scored stress_management from Whoop `recovery_score` (else strain) — a
physiology proxy, not stress. Now it reads the evening check-in's `stress` (0-4, #5106), and with no
check-in it is unavailable — never a Whoop stand-in.

The input is owner-only ("no public projection of any kind", privacy.field_tiers +
docs/DATA_GOVERNANCE.md), and the character sheet is public. So the component is HELD OUT of the
pillar arithmetic (the published Mind score cannot move with it) and is never named on a driver list
or a level-up event — fail-closed in code, so a lambda deployed ahead of its config twin is safe too.
Also pinned: the weekly-correlation docstring lists exactly the pairs CORRELATION_PAIRS computes.
"""

import json
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from health import character_engine as ce  # noqa: E402

_CFG = json.load(open(os.path.join(_REPO, "config", "character_sheet.json"), encoding="utf-8"))
_WHOOP = {"recovery_score": 95.0, "day_strain": 11.0}


def _mind(data, cfg=_CFG):
    return ce.compute_mind_raw(data, cfg)


def test_stress_management_reads_the_evening_checkin_not_whoop():
    _raw, d = _mind({"whoop": _WHOOP, "evening_checkin": {"stress": 1}})
    assert d["stress_management"]["score"] == 75.0  # (4 - 1) / 4
    _raw, d = _mind({"whoop": _WHOOP, "evening_checkin": {"stress": 4}})
    assert d["stress_management"]["score"] == 0.0


def test_no_checkin_is_unavailable_never_a_whoop_stand_in():
    _raw, d = _mind({"whoop": _WHOOP})
    assert d["stress_management"]["score"] is None
    for bad in ({"stress": None}, {"stress": 7}, {"stress": -1}, {"hunger": 2}):
        assert ce.character_privacy.stress_management_score(bad) is None


def test_the_published_mind_score_cannot_move_with_reported_stress():
    base = {"whoop": _WHOOP, "habit_scores": {"tier0_pct": 0.8, "tier1_pct": 0.5}, "journal_14d_count": 7}
    calm, d_calm = _mind(dict(base, evening_checkin={"stress": 0}))
    tense, d_tense = _mind(dict(base, evening_checkin={"stress": 4}))
    absent, d_absent = _mind(base)
    assert calm == tense == absent
    assert d_calm["_data_coverage"] == d_tense["_data_coverage"] == d_absent["_data_coverage"]  # coverage says nothing either
    assert d_calm["stress_management"]["held_out"] is True and d_calm["stress_management"]["owner_only"] is True


def test_held_out_even_when_the_config_twin_lags_the_code():
    stale = json.loads(json.dumps(_CFG))
    stale["pillars"]["mind"]["components"]["stress_management"] = {"weight": 0.1}  # the pre-#5129 config
    base = {"habit_scores": {"tier0_pct": 0.8}}
    assert _mind(dict(base, evening_checkin={"stress": 0}), stale)[0] == _mind(dict(base, evening_checkin={"stress": 4}), stale)[0]


def test_only_an_explicit_opt_in_puts_it_in_the_pillar():
    ruled = json.loads(json.dumps(_CFG))
    ruled["pillars"]["mind"]["components"]["stress_management"]["in_pillar_score"] = True
    base = {"habit_scores": {"tier0_pct": 0.8}}
    calm, d = _mind(dict(base, evening_checkin={"stress": 0}), ruled)
    tense, _ = _mind(dict(base, evening_checkin={"stress": 4}), ruled)
    assert calm > tense
    assert d["stress_management"]["owner_only"] is True and d["stress_management"]["held_out"] is False
    assert "stress_management" not in sum(ce.pillar_drivers(d).values(), [])  # still never a named driver


def test_never_a_named_driver():
    _raw, d = _mind({"evening_checkin": {"stress": 0}})
    assert "stress_management" not in sum(ce.pillar_drivers(d).values(), [])


def test_repo_config_declares_the_owner_only_input():
    comp = _CFG["pillars"]["mind"]["components"]["stress_management"]
    assert comp["owner_only_input"] == ce.character_privacy.OWNER_ONLY_COMPONENTS["stress_management"] == "evening_checkin"
    assert comp["in_pillar_score"] is False

    from privacy.field_tiers import SOURCE_TIERS, TIER_OWNER_ONLY

    assert SOURCE_TIERS["evening_checkin"] == TIER_OWNER_ONLY


def test_the_lambda_fetches_the_checkin_and_keeps_it_off_the_public_receipt():
    src = open(os.path.join(_REPO, "lambdas", "compute", "character_sheet_lambda.py"), encoding="utf-8").read()
    assert 'data["evening_checkin"] = fetch_date("evening_checkin", yesterday_str)' in src
    body = src[src.index("def collect_input_rows") : src.index("def write_progression_receipt")]
    assert "evening_checkin" not in body.replace("#5129", "")


def test_the_pruning_protocol_line_no_longer_claims_a_rule():
    lines = sum(_CFG["protocols"]["mind"].values(), [])
    t0 = [ln for ln in lines if "T0 habit list" in ln]
    assert len(t0) == 1 and "only if" not in t0[0] and "nothing in the platform checks" in t0[0]


def test_weekly_correlation_docstring_lists_exactly_the_computed_pairs():
    sys.path.insert(0, _REPO)
    import importlib

    os.environ.setdefault("AWS_REGION", "us-west-2")
    wc = importlib.import_module("compute.weekly_correlation_compute_lambda")
    doc = wc.__doc__
    section = doc[doc.index("Correlation pairs computed") : doc.index("Schedule:")]
    named = set(re.findall(r"`([a-z0-9_]+)`", section))
    assert named == {label for _a, _b, label, _lag in wc.CORRELATION_PAIRS}
    assert "mood_score" not in doc
