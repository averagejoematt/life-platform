"""tests/test_character_steps_charter_5056.py — the character sheet's daily-steps target reads the charter (#5056).

The owner's 2026-10-18 ruling: a 12,000 floor and a 15,000 target EVERY day, held in
config/training_charter.json (`steps.floor` / `steps.target`). The coach line and the 19:00 PT
lifting-day nudge already read it (#5166, tests/test_steps_nudge_5056.py). The #5056 Set's
remaining hand copies were the character sheet's `daily_steps.target` 8000 and the engine's 8000
fallback, which scored a 12,000-step day as perfect and could let a p75 of his own lifting-day
steps (the #1412 personal band) set a target under the floor.

Pinned here:
  1. `protocol_targets` reads the charter's steps rule: target = floor, perfect_at = target,
     provenance `source: charter` with the two dotted paths;
  2. the charter outranks the personal band and the authored prior in `apply_character_targets`;
  3. an unreadable or malformed charter falls back to the #1412 path (never a fabricated value);
  4. the engine scores 100 at the charter target, floor/target x 100 at the floor, and keeps the
     authored 1.5 curve for a component with no `perfect_at` (legacy configs unchanged).

Expected values are derived from the charter, never re-typed, except the one literal pair the
owner ruled (asserted once, so a charter edit surfaces here by name).
"""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambdas"))

from health import (
    character_engine as ce,  # noqa: E402
    personal_baselines as pb,  # noqa: E402
)
from training import training_charter  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_CONFIG_PATH = os.path.join(_ROOT, "config", "character_sheet.json")


def _authored_config():
    with open(_CONFIG_PATH) as f:
        return json.load(f)


def _band(p75, n=60):
    return {"p25": p75 * 0.7, "p50": p75 * 0.85, "p75": p75, "n": n, "window_days": 365}


def _floor_target():
    return training_charter.charter_value("steps.floor"), training_charter.charter_value("steps.target")


def _steps_score(cfg, steps):
    _raw, details = ce.compute_movement_raw({"apple": {"steps": steps}}, cfg)
    return details["daily_steps"]


def test_the_charter_carries_the_owner_ruled_pair():
    assert _floor_target() == (12000, 15000)


def test_protocol_targets_read_the_charter_steps_rule():
    floor, target = _floor_target()
    overlay = pb.protocol_targets()["daily_steps"]
    assert overlay["target"] == floor
    assert overlay["perfect_at"] == target
    assert overlay["target_provenance"]["source"] == "charter"
    assert overlay["target_provenance"]["paths"] == {"target": "steps.floor", "perfect_at": "steps.target"}


def test_the_charter_outranks_the_personal_band_and_the_authored_prior():
    floor, target = _floor_target()
    cfg = _authored_config()
    for baselines in ({"daily_steps": _band(9000.0)}, {"daily_steps": _band(14000.0)}, {}):
        comp = pb.apply_character_targets(cfg, baselines)["pillars"]["movement"]["components"]["daily_steps"]
        assert (comp["target"], comp["perfect_at"]) == (floor, target), baselines
        assert comp["target_provenance"]["source"] == "charter"
    # the authored config is never mutated (the engine caches it in-process)
    assert "perfect_at" not in cfg["pillars"]["movement"]["components"]["daily_steps"]


def test_unreadable_or_malformed_charter_falls_back_to_the_1412_path(monkeypatch):
    views = (
        {},
        {"steps": {"floor": None, "target": 15000}},
        {"steps": {"floor": 15000, "target": 12000}},
        {"steps": {"floor": True, "target": 15000}},
    )
    offenders = []
    for view in views:
        monkeypatch.setattr(training_charter, "public_view", lambda v=view: v)
        comp = pb.apply_character_targets(_authored_config(), {"daily_steps": _band(11000.0)})["pillars"]["movement"]["components"]
        steps = comp["daily_steps"]
        ok = pb.protocol_targets() == {} and steps["target"] == 11000 and steps["target_provenance"]["source"] == "personal"
        if not ok or "perfect_at" in steps:
            offenders.append((view, steps))
    assert not offenders, offenders


def test_a_charter_read_that_raises_is_fail_soft(monkeypatch):
    def boom():
        raise RuntimeError("no charter")

    monkeypatch.setattr(training_charter, "public_view", boom)
    assert pb.protocol_targets() == {}


def test_engine_scores_against_the_charter_floor_and_target():
    floor, target = _floor_target()
    cfg = pb.apply_character_targets(_authored_config(), {})
    assert _steps_score(cfg, target)["score"] == 100.0
    assert _steps_score(cfg, target + 4000)["score"] == 100.0
    assert _steps_score(cfg, floor)["score"] == round(floor / target * 100, 1)
    assert _steps_score(cfg, floor // 2)["score"] == round((floor // 2) / target * 100, 1)
    # under the target is not perfect (100 steps under; one step under rounds to 100.0 at one decimal)
    assert _steps_score(cfg, target - 100)["score"] == round((target - 100) / target * 100, 1) < 100.0
    assert _steps_score(cfg, floor)["target_provenance"]["source"] == "charter"


def test_a_component_with_no_perfect_at_keeps_the_authored_curve():
    cfg = {"pillars": {"movement": {"components": {"daily_steps": {"weight": 1.0, "target": 8000}}}}}
    assert pb.perfect_ratio(cfg["pillars"]["movement"]["components"]["daily_steps"], 1.5) == 1.5
    assert _steps_score(cfg, 12000)["score"] == 100.0
    assert _steps_score(cfg, 6000)["score"] == 50.0


def test_perfect_ratio_ignores_a_perfect_at_under_the_target():
    assert pb.perfect_ratio({"target": 12000, "perfect_at": 15000}, 1.5) == 1.25
    assert pb.perfect_ratio({"target": 12000, "perfect_at": 9000}, 1.5) == 1.5
    assert pb.perfect_ratio(None, 1.5) == 1.5


# ── the plan-figure gate (#3518) grades a step claim against the charter rule, not the genesis range ──


def test_the_plan_gate_sanctions_the_charter_rule_and_still_catches_a_shelf_figure():
    from ai import plan_facts_gate as pg
    from experiment import plan_facts as pf

    floor, target = _floor_target()
    facts = pf.load_plan_facts()
    assert facts[pf.LIVE_STEPS_KEY] == [floor, target]
    assert facts["daily_steps_range"] == [6000, 7000]  # the sealed genesis figure is untouched
    assert pf.plan_figures(facts)["steps"] == {float(floor), float(target)}
    ok = f"he holds the {floor:,}-step floor and aims for the {target:,} steps target"
    assert pg.plan_figure_findings(ok, facts) == []
    bad = pg.plan_figure_findings("his 8,000+ steps/day protocol", facts)
    assert [f["claimed"] for f in bad] == [8000.0]
    assert bad[0]["plan"] == [float(floor), float(target)]
    assert "training_charter.json" in bad[0]["detail"]


def test_the_plan_gate_keeps_the_genesis_range_when_the_charter_is_unreadable(monkeypatch):
    from experiment import plan_facts as pf

    monkeypatch.setattr(training_charter, "charter_value", lambda path, default=None: None)
    facts = pf.load_plan_facts()
    assert pf.LIVE_STEPS_KEY not in facts
    assert pf.plan_figures(facts)["steps"] == {6000.0, 7000.0}
