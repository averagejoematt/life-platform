"""tests/test_rate_policy_5861.py — the adaptive loss-rate band proposal (#5861 L5, owner brief §10).

`health.rate_policy` is an interface only: pure, deterministic, read by no live path. Every profile here is synthetic.
The rules under test: a SLOW signal only ever moves the band down; nothing moves it above the start rung or the
heuristic max; the strength and protein thresholds are `owner_redlines`'s own; same inputs, same output.
"""

from __future__ import annotations

import itertools
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "lambdas"))
sys.path.insert(0, str(REPO))

from health import rate_policy as rp  # noqa: E402
from training import owner_redlines  # noqa: E402

STRENGTH_DOWN = {"bench": -6.0, "squat": -7.0, "row": 0.0, "hinge": 1.0}
STRENGTH_FLAT = {"bench": 0.5, "squat": -1.0, "row": 0.0, "hinge": 1.0}


def _lo_hi(p):
    return tuple(p["band_pct_bw_per_wk"])


def test_strength_decline_slows_the_band():
    """Must-fail control: 2 of 4 anchors past the tripwire threshold moves the band down a rung, driven by strength."""
    flat = rp.propose_band(body_fat_tier="report_only", anchor_e1rm_change_pct=STRENGTH_FLAT)
    down = rp.propose_band(body_fat_tier="report_only", anchor_e1rm_change_pct=STRENGTH_DOWN)
    assert _lo_hi(down) < _lo_hi(flat)
    assert down["driver"] == "strength" and down["rungs_down"] == 1
    one_severe = rp.propose_band(body_fat_tier="report_only", anchor_e1rm_change_pct={"bench": -12.0, "squat": 0.0})
    assert one_severe["driver"] == "strength", "one anchor past twice the threshold is a slow signal on its own"
    one_mild = rp.propose_band(body_fat_tier="report_only", anchor_e1rm_change_pct={"bench": -6.0, "squat": 0.0})
    assert _lo_hi(one_mild) == _lo_hi(flat) and one_mild["signals"][0]["state"] == "watch"


def test_adherence_break_slows_the_band():
    """Must-fail control: a protein-floor miss at the tripwire's day count, or intake in band on too few days, slows it."""
    base = rp.propose_band(body_fat_tier="brake")
    need = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "protein_floor_missed")["threshold_days"]
    protein = rp.propose_band(body_fat_tier="brake", protein_floor_days_missed_7d=need)
    intake = rp.propose_band(body_fat_tier="brake", intake_adherence_pct=rp.INTAKE_ADHERENCE_MIN_PCT - 1)
    for p in (protein, intake):
        assert _lo_hi(p) < _lo_hi(base) and p["driver"] == "adherence"
    held = rp.propose_band(body_fat_tier="brake", protein_floor_days_missed_7d=need - 1, intake_adherence_pct=90.0)
    assert _lo_hi(held) == _lo_hi(base)


def test_a_rate_below_the_band_never_speeds_it_up():
    """Must-fail control: an observed rate far below the band is reported as 'below' and changes nothing."""
    for tier in ("report_only", "brake", "full", "unknown", None):
        ref = rp.propose_band(body_fat_tier=tier)
        slow_loss = rp.propose_band(body_fat_tier=tier, observed_pct_bw_per_wk=0.0)
        assert _lo_hi(slow_loss) == _lo_hi(ref)
        assert slow_loss["observed_vs_band"] == "below"
        assert slow_loss["band_pct_bw_per_wk"][1] <= rp.HEURISTIC_MAX_PCT_BW_WK


def test_no_input_combination_exceeds_the_start_rung_or_the_heuristic_max():
    """Over a grid of every signal state, the band is never above its tier's start rung, nor above the heuristic max,
    nor below the slowest rung (this module never proposes zero)."""
    names = [r[0] for r in rp.RUNGS]
    grid = itertools.product(
        [None, "report_only", "brake", "full", "unknown"],
        [None, 0.0, 0.6, 2.0],
        [None, STRENGTH_FLAT, STRENGTH_DOWN],
        [None, "low", "elevated", "high"],
        [None, False, True],
        [None, 0, 5],
        [None, 30.0, 95.0],
        [None, 0, 6],
    )
    n = 0
    for tier, obs, st, fat, rec, prot, intake, hunger in grid:
        p = rp.propose_band(
            body_fat_tier=tier,
            observed_pct_bw_per_wk=obs,
            anchor_e1rm_change_pct=st,
            fatigue_level=fat,
            recovery_low=rec,
            protein_floor_days_missed_7d=prot,
            intake_adherence_pct=intake,
            hunger_high_days_7d=hunger,
        )
        start = rp.START_RUNG_BY_TIER.get(tier or "unknown")
        assert names.index(p["band_name"]) <= names.index(start)
        assert rp.RUNGS[0][1] <= p["band_pct_bw_per_wk"][0] < p["band_pct_bw_per_wk"][1] <= rp.HEURISTIC_MAX_PCT_BW_WK
        assert p["applied"] is False and p["status"] == "proposal"
        n += 1
    assert n == 5 * 4 * 3 * 4 * 3 * 3 * 3 * 3


def test_unknown_tier_never_starts_on_the_fast_rung():
    assert rp.propose_band()["band_name"] == "typical"
    assert rp.propose_band(body_fat_tier="not-a-tier")["band_name"] == "typical"
    assert rp.propose_band(body_fat_tier="report_only")["band_name"] == "high_mass"


def test_every_configured_body_fat_tier_has_a_start_rung():
    """The start rung reads the platform's existing tiers; a renamed or added tier must be mapped here, not fall to the default."""
    cfg = owner_redlines.REDLINES["rate_protein_gate"]["body_fat_tiers"]["tiers"]
    assert {t["tier"] for t in cfg} | {"unknown"} == set(rp.START_RUNG_BY_TIER)


def test_driver_precedence_is_strength_first_and_three_signals_ask_the_owner():
    p = rp.propose_band(
        body_fat_tier="report_only",
        anchor_e1rm_change_pct=STRENGTH_DOWN,
        hunger_high_days_7d=7,
        recovery_low=True,
    )
    assert p["driver"] == "strength"
    assert p["band_name"] == "slow"  # three rungs down from high_mass, floored at slow
    assert p["owner_decision"]
    assert rp.propose_band(body_fat_tier="report_only", recovery_low=True)["owner_decision"] is None


def test_strength_threshold_is_the_tripwires_own(monkeypatch):
    """The threshold is READ from owner_redlines: raising it there turns a slow signal into a watch."""
    trip = next(t for t in owner_redlines.TRIPWIRES if t["id"] == "anchor_lift_strength_drop")
    assert rp.propose_band(anchor_e1rm_change_pct=STRENGTH_DOWN)["driver"] == "strength"
    monkeypatch.setitem(trip, "threshold_pct", 8)
    assert rp.propose_band(anchor_e1rm_change_pct=STRENGTH_DOWN)["driver"] == "body_fat_tier"


def test_deterministic():
    kw = dict(
        body_fat_tier="brake",
        observed_pct_bw_per_wk=1.1,
        anchor_e1rm_change_pct={"squat": -7.0, "bench": -5.5, "hinge": -1.0},
        fatigue_level="high",
        hunger_high_days_7d=4,
    )
    a = json.dumps(rp.propose_band(**kw), sort_keys=True)
    b = json.dumps(rp.propose_band(**dict(reversed(list(kw.items())))), sort_keys=True)
    assert a == b
    assert rp.dry_run({"x": kw, "a": {}}) == rp.dry_run({"a": {}, "x": kw})


def test_dry_run_script_runs_on_synthetic_profiles():
    out = subprocess.run([sys.executable, str(REPO / "scripts" / "rate_policy_dry_run.py"), "--json"], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    got = json.loads(out.stdout)
    assert got["b_top_tier_strength_down"]["driver"] == "strength"
    assert all(p["applied"] is False for p in got.values())


ADVISORY_READERS = {"lambdas/training/live_program.py"}
"""The ONE module allowed to read the proposal (#5861 red team, fix 7): `live_program.rate_line` renders the band as ADVISORY
text in a LIVE draft's rationale. It never feeds the rate band, titration or a kcal target — wiring the band into nutrition
stays the owner's decision (WEEKLY_STRUCTURE.md, `health.titration.band_for`)."""


def _readers() -> list[str]:
    out = []
    for root in ("lambdas", "mcp"):
        for path in sorted((REPO / root).rglob("*.py")):
            if path.name == "rate_policy.py":
                continue
            if "rate_policy" in path.read_text(encoding="utf-8", errors="ignore"):
                out.append(str(path.relative_to(REPO)))
    return out


# premerge-gate: sweeps lambdas/ and mcp/ for any import of the proposal — the "no live change" proof (#5861 L5)
def test_no_live_path_reads_the_proposal():
    """No Lambda or MCP module imports `rate_policy` but the one advisory reader: the live rate band, titration and kcal
    targets are untouched. The advisory reader only renders a rationale line (asserted on its source)."""
    offenders = [p for p in _readers() if p not in ADVISORY_READERS]
    assert offenders == [], f"a live module reads the rate proposal (owner decision first): {offenders}"
    src = (REPO / "lambdas/training/live_program.py").read_text()
    use = [ln.strip() for ln in src.splitlines() if "rate_policy." in ln]
    assert use and all("propose_band" in ln for ln in use), use  # the band proposal only
    imports = [ln for ln in src.splitlines() if ln.strip().startswith(("import ", "from "))]
    assert not [ln for ln in imports if "calorie_target" in ln or "titration" in ln], imports  # no kcal, no titration
    # control: a second reader planted in the set the sweep sees -> red
    assert [p for p in _readers() + ["lambdas/health/calorie_target.py"] if p not in ADVISORY_READERS]
