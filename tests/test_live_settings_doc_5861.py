"""#5861 fix round 9 (consolidation): ONE settings table, the docs and the library generated from it.

`training.live_settings` is the one table of the live engine's settings (owner rulings) and labelled heuristics. The eighth red
team found the architecture doc contradicting the code's defaults in six places and the library carrying five rounds of dead
settings; here the doc's tables and the library's `programming_settings` are both generated from the table and held to it.

Must-fail controls (run on the lane, recorded on the PR): a default changed in `live_settings.SETTINGS` without regenerating ->
the doc test and the library test are both red.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "lambdas", REPO / "scripts"):
    sys.path.insert(0, str(_p))

import gen_live_settings_doc_5861 as gen  # noqa: E402
from training import live_settings  # noqa: E402

LIB = json.loads((REPO / "config" / "exercise_library.json").read_text())


def test_the_docs_generated_tables_equal_the_code():
    for path in gen.DOCS:
        text = path.read_text()
        assert gen.BEGIN in text and gen.END in text, path
        block = text.split(gen.BEGIN, 1)[1].split(gen.END, 1)[0].strip()
        assert block == live_settings.settings_table_markdown(), f"{path.name}: run scripts/gen_live_settings_doc_5861.py"


def test_the_librarys_programming_settings_are_the_one_table():
    got = LIB["programming_settings"]
    assert set(got) == set(live_settings.SETTINGS)
    assert got == live_settings.defaults()
    assert live_settings.settings(LIB) == live_settings.defaults()


def test_no_rating_basis_carries_points_arithmetic():
    hits = sorted(set(re.findall(r"points \d+/\d+", json.dumps(LIB["movements"]))))
    assert hits == [], hits[:5]


def test_the_library_stays_proposed():
    assert LIB["status"] == "proposed"


def test_every_heuristic_and_setting_states_its_provenance():
    for k, row in live_settings.SETTINGS.items():
        assert row.get("ruling") and row.get("what"), k
    for k, row in live_settings.HEURISTICS.items():
        assert row.get("basis") and row.get("retune") and row.get("group"), k
