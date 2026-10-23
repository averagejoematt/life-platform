"""tests/served_templates_5162.py — the two upper-day templates as they were served before #5162.

Owner ruling 2026-10-23 (#5162, "trade inside 75") moved the overhead press off upper-heavy and upper-volume: their press
sets became a lateral raise / a face pull. Several tests replay a captured wire session that was served WITH the press —
the 2026-09-29 upper-heavy (`tests/fixtures/training_block1_wire_4408_4409`) and the 2026-10-18 upper-volume
(`tests/fixtures/draft_custom_slot_5005`). What those tests hold is a resolver (in-block variant #4409, one template
resolver #4431, the held load #4408, warm-ups #5049, the custom-slot stamp #5005), not the week's design, so they run
against the template as it was served that day. The current templates are held by `test_program_session_4064_4147.py`
and `test_volume_floors_5053.py`.

One copy, imported by every replay, so a later template change has one place to say what was served.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import patch


def _as_served() -> dict[str, dict[str, Any]]:
    from training import program_structure

    t = program_structure.SESSION_TEMPLATES
    return {
        "upper_heavy": {
            **t["upper_heavy"],
            "anchors": [["bench", "heavy"], ["row", "heavy"], ["overhead_press", "moderate"], ["vertical_pull", "moderate"]],
            "accessories": ["cable_tricep_pushdown", "db_curl", "reverse_pec_deck"],
            "accessory_sets": {},
        },
        "upper_volume": {
            **t["upper_volume"],
            "anchors": [["bench", "volume"], ["row", "volume"], ["overhead_press", "volume"], ["vertical_pull", "volume"]],
            "accessories": ["cable_chest_fly", "cable_tricep_pushdown", "db_curl"],
            "accessory_sets": {},
        },
    }


@contextmanager
def pre_5162_upper_days() -> Iterator[None]:
    """Both upper days as served before 2026-10-23 (the press on each), for the duration of the block."""
    from training import program_structure

    with patch.dict(program_structure.SESSION_TEMPLATES, _as_served()):
        yield
