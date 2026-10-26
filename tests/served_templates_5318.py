"""tests/served_templates_5318.py — upper-volume and shoulders+arms as they were served before #5318.

Owner rulings 2026-10-24 (#5318): B2 "Swap upper_volume's flat bench for incline DB press — same set count" pinned the
upper-volume bench slot to `incline_db_press` (`SESSION_TEMPLATES['upper_volume']['anchor_keys']`); B3 "Replace the 2 DB shrug
sets on shoulders_arms with 2 sets of farmer's carry" swapped `shrug_dumbbell` for `farmers_walk`. A test that replays a
session served BEFORE that day holds a resolver, not the week's design, so it runs against the template as it was served.
The current templates are held by `test_rulings_5318_5317.py`, `test_program_session_4064_4147.py` and
`test_volume_floors_5053.py`. (Sessions served before 2026-10-23 also predate #5162: `served_templates_5162`.)
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import patch


def _as_served() -> dict[str, dict[str, Any]]:
    from training import program_structure

    t = program_structure.SESSION_TEMPLATES
    sa = {k: v for k, v in t["shoulders_arms"].items() if k != "accessory_shapes"}
    sa["accessories"] = ["shrug_dumbbell" if a == "farmers_walk" else a for a in t["shoulders_arms"]["accessories"]]
    return {
        "upper_volume": {k: v for k, v in t["upper_volume"].items() if k != "anchor_keys"},
        "shoulders_arms": sa,
    }


@contextmanager
def pre_5318_templates() -> Iterator[None]:
    """Upper-volume (the flat barbell bench) and shoulders+arms (the dumbbell shrug) as served before 2026-10-24."""
    from training import program_structure

    with patch.dict(program_structure.SESSION_TEMPLATES, _as_served()):
        yield
