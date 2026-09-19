"""tests/test_restart_verify_pre_genesis_census_3513.py — check 21's pure predicate (#3513 box 3).

`pre_genesis_unstamped(pages, genesis)` must: name an EXPERIMENT_SCOPED row dated before genesis
that is not `pilot` (unstamped OR wrongly `experiment`); pass a `pilot` one; ignore a CROSS_PHASE
row however it is stamped; ignore a scoped row dated on/after genesis. Loaded the way the sibling
restart_verify tests load the script (module from file, no main()).
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for p in (str(REPO_ROOT), str(REPO_ROOT / "deploy"), str(REPO_ROOT / "lambdas")):
    if p not in sys.path:
        sys.path.insert(0, p)


def _load():
    spec = importlib.util.spec_from_file_location("restart_verify_3513", REPO_ROOT / "deploy" / "restart_verify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


GENESIS = "2026-09-06"
SCOPED_PK = "USER#matthew#SOURCE#insights"
CROSS_PK = "COACH#sleep_coach"


def _pages(*rows):
    return [list(rows)]


def test_an_unstamped_pre_genesis_scoped_row_is_named():
    rv = _load()
    bad, n = rv.pre_genesis_unstamped(_pages({"pk": SCOPED_PK, "sk": "INSIGHT#2026-09-03#daily_brief#tldr"}), GENESIS)
    assert n == 1
    assert bad == [f"{SCOPED_PK}/INSIGHT#2026-09-03#daily_brief#tldr[phase=None]"]


def test_a_pre_genesis_scoped_row_stamped_experiment_is_named_too():
    rv = _load()
    bad, _ = rv.pre_genesis_unstamped(
        _pages({"pk": SCOPED_PK, "sk": "INSIGHT#2026-09-03#daily_brief#tldr", "phase": "experiment", "cycle": 17}), GENESIS
    )
    assert len(bad) == 1 and "[phase=experiment]" in bad[0]


def test_a_pilot_pre_genesis_row_and_a_post_genesis_row_pass():
    rv = _load()
    bad, n = rv.pre_genesis_unstamped(
        _pages(
            {"pk": SCOPED_PK, "sk": "INSIGHT#2026-09-03#daily_brief#tldr", "phase": "pilot", "cycle": 16},
            {"pk": SCOPED_PK, "sk": "INSIGHT#2026-09-10#daily_brief#tldr"},
        ),
        GENESIS,
    )
    assert n == 2 and bad == []


def test_a_cross_phase_row_is_never_a_member():
    rv = _load()
    bad, _ = rv.pre_genesis_unstamped(_pages({"pk": CROSS_PK, "sk": "CHAT#2026-09-01T10:00:00Z"}), GENESIS)
    assert bad == []


def test_an_empty_scan_is_zero_rows_not_a_pass():
    rv = _load()
    bad, n = rv.pre_genesis_unstamped(_pages(), GENESIS)
    assert (bad, n) == ([], 0)  # check 21 requires scanned > 0 to pass
