"""tests/test_supplement_weight_loss_figure_3526.py — #3526.

`config/supplement_registry.json` hand-typed "A 117-lb weight-loss journey" /
"A 117-lb loss" in the Collagen entry's `why`/`rationale` prose — a figure from
an earlier cycle's baseline that disagreed with the doors (home/data/protocols),
which all derive the same "climb" from `config/user_goals.json` (start minus
goal, `scripts/v4_proof.py`'s `climb = int(sw) - int(gw)` where `sw`/`gw` are
the whole-pound-rounded start/goal weights — the SAME derivation this module
uses as its root, so the two families can never independently drift).

Same class as #1898's protein-floor reconciliation (`test_plan_literal_
reconciliation.py`): hardcoding the corrected number here would just create
another copy to drift, so the test derives the canonical figure and scans for
disagreement rather than asserting a specific number.
"""

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
GOALS = ROOT / "config" / "user_goals.json"
SUPPLEMENTS = ROOT / "config" / "supplement_registry.json"


def _canonical_weight_loss_lbs() -> int:
    """The doors' own "lb climb" derivation (scripts/v4_proof.py's home banner):
    whole-pound-rounded start weight minus whole-pound-rounded goal weight."""
    goals = json.loads(GOALS.read_text(encoding="utf-8"))
    start = goals["timeline"]["start_weight_lbs"]
    goal = goals["targets"]["weight"]["goal_lbs"]
    return round(float(start)) - round(float(goal))


# A "<N>-lb weight-loss journey" / "A <N>-lb loss" claim — the CURRENT-cycle
# phrasing this module polices. Deliberately narrow (not every "<N> lb" in the
# file — dosing figures like "10-15g" or "3 lb" thresholds elsewhere are out of
# scope) so it can't false-positive on unrelated numbers.
_JOURNEY_FIGURE = re.compile(r"(\d+)-lb (?:weight-loss journey|loss)\b", re.IGNORECASE)


def _journey_figures(text: str) -> set:
    return {int(m) for m in _JOURNEY_FIGURE.findall(text)}


def test_the_canonical_figure_is_readable():
    """Guard the guard: if this can't resolve, every assertion below is vacuous."""
    lbs = _canonical_weight_loss_lbs()
    assert 50 < lbs < 300, f"implausible weight-loss journey figure {lbs} — the root moved or changed units"


def test_supplement_registry_carries_no_stale_weight_loss_figure():
    """#3526's exact defect: 'A 117-lb weight-loss journey' / 'A 117-lb loss'
    survived a reset that moved the baseline (and therefore the climb) on."""
    canonical = _canonical_weight_loss_lbs()
    found = _journey_figures(SUPPLEMENTS.read_text(encoding="utf-8"))
    stale = found - {canonical}
    assert not stale, f"config/supplement_registry.json carries weight-loss journey figure(s) {sorted(stale)}, current is {canonical}"
    # And the reverse isn't vacuously true — the phrase must actually still be there.
    assert canonical in found, "expected at least one 'N-lb weight-loss journey'/'N-lb loss' phrase to police"


def test_positive_control_a_stale_figure_is_detected():
    """The check must actually be able to fail — feed it the #3526 defect verbatim."""
    canonical = _canonical_weight_loss_lbs()
    stale_text = 'the "why": "A 117-lb weight-loss journey means significant skin adaptation."'
    # 117 is only "stale" if it happens to differ from the current canonical figure;
    # pick a number guaranteed to differ so this control can't accidentally pass.
    bogus = canonical + 37
    stale_text = f'"why": "A {bogus}-lb weight-loss journey means significant skin adaptation."'
    found = _journey_figures(stale_text)
    assert found - {canonical} == {bogus}, "the positive control itself is broken"
