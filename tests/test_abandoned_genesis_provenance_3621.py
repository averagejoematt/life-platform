"""tests/test_abandoned_genesis_provenance_3621.py — #3621 box 1: the abandoned-genesis
alias map, the resolver that consults it, and the census check 22 runs on it.

THE DEFECT. The cycle-16 re-anchor was mis-dated to Friday 2026-09-04, caught about an hour
in, and re-anchored to Saturday 2026-09-05 by CORRECTING `CYCLE_GENESES[16]` IN PLACE. But
the Friday run had already executed `restart_intelligence_wipe`, which writes
`tombstoned_reason` / `cycle` / `tombstoned_at` with `if_not_exists` PRECISELY so a later
reset can never overwrite the generation a record was first archived in (#1202, ADR-077) —
so the in-place correction could not reach the rows it had already stamped. Measured on the
live table 2026-09-20: 328 rows carry `tombstoned_reason = experiment_restart_2026-09-04`,
all stamped `cycle=15`, and `closing_cycle_for_genesis('2026-09-04', CYCLE_GENESES)`
returned None for every one of them.

Re-putting those 328 reason strings is rejected by the issue and by this test's framing: it
would destroy the record that the Friday genesis was written at all. The alias is how the
record stays true in both directions.

THE MUTATION CONTROL is the same fixture row with an EMPTY alias map — the pre-#3621
behaviour — which must come back unresolved. Without it these tests would pass on a
resolver that resolved everything.
"""

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
for _p in (str(REPO_ROOT), str(REPO_ROOT / "deploy"), str(REPO_ROOT / "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from experiment import phase_taxonomy as taxonomy  # noqa: E402
from web.site_api_data import ABANDONED_GENESES, CYCLE_GENESES  # noqa: E402


def _load_rv():
    """Load deploy/restart_verify.py the way its sibling tests do (no main())."""
    spec = importlib.util.spec_from_file_location("restart_verify_3621", REPO_ROOT / "deploy" / "restart_verify.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# A pinned registry, so these tests do not drift as restart_pipeline appends real cycles.
_GENESES = {1: "2026-04-01", 15: "2026-09-01", 16: "2026-09-05", 17: "2026-09-06"}
_ALIASES = {"2026-09-04": 16}

# The live shape of the 328 rows, measured 2026-09-20 (pk/sk from the census's own sample).
FRIDAY_ROW = {
    "pk": "USER#matthew#SOURCE#habit_scores",
    "sk": "DATE#2026-08-31",
    "tombstone": True,
    "tombstoned_reason": "experiment_restart_2026-09-04",
    "cycle": 15,
    "phase": "pilot",
}


def _pages(*rows):
    return [list(rows)]


# ── the registry itself ───────────────────────────────────────────────────────


def test_the_abandoned_genesis_is_registered_with_the_cycle_it_was_opening():
    assert ABANDONED_GENESES["2026-09-04"] == 16


def test_an_abandoned_genesis_is_never_also_a_live_genesis():
    """A date in BOTH registries is a contradiction: it would claim the anchor was moved
    and not moved. Guards the SET (every alias), not just the 2026-09-04 instance."""
    live = {str(v)[:10] for v in CYCLE_GENESES.values()}
    collisions = sorted(set(ABANDONED_GENESES) & live)
    assert not collisions, f"{collisions} appear in both CYCLE_GENESES and ABANDONED_GENESES"


def test_every_alias_points_at_a_cycle_that_exists():
    unknown = sorted(d for d, c in ABANDONED_GENESES.items() if int(c) not in {int(k) for k in CYCLE_GENESES})
    assert not unknown, f"{unknown} alias a cycle number that is not in CYCLE_GENESES"


# ── the resolver ──────────────────────────────────────────────────────────────


def test_the_abandoned_genesis_resolves_to_the_cycle_it_opened():
    assert taxonomy.opening_cycle_for_genesis("2026-09-04", _GENESES, _ALIASES) == 16
    assert taxonomy.closing_cycle_for_genesis("2026-09-04", _GENESES, _ALIASES) == 15


def test_the_mutation_control_an_empty_alias_map_leaves_it_unresolved():
    """The pre-#3621 behaviour, pinned. If this ever starts resolving, the tests above
    are proving nothing."""
    assert taxonomy.opening_cycle_for_genesis("2026-09-04", _GENESES, {}) is None
    assert taxonomy.closing_cycle_for_genesis("2026-09-04", _GENESES, {}) is None


def test_a_live_genesis_still_resolves_without_any_alias():
    assert taxonomy.closing_cycle_for_genesis("2026-09-05", _GENESES, {}) == 15
    assert taxonomy.closing_cycle_for_genesis("2026-09-06", _GENESES, {}) == 16


def test_cycle_one_is_distinguishable_from_an_unregistered_genesis():
    """`closing_cycle_for_genesis` returns None for both "cycle 1, no predecessor" and
    "never heard of this date" — which is why the census reads the OPENING cycle instead.
    Collapsing the two would make the census red on every cycle-1 row forever."""
    assert taxonomy.opening_cycle_for_genesis("2026-04-01", _GENESES, {}) == 1
    assert taxonomy.closing_cycle_for_genesis("2026-04-01", _GENESES, {}) is None
    assert taxonomy.opening_cycle_for_genesis("2019-01-01", _GENESES, {}) is None


def test_an_empty_or_missing_genesis_resolves_to_nothing():
    assert taxonomy.opening_cycle_for_genesis(None, _GENESES, _ALIASES) is None
    assert taxonomy.opening_cycle_for_genesis("", _GENESES, _ALIASES) is None


def test_the_resolver_consults_the_live_alias_map_when_none_is_passed():
    """The signature defaults to None = "consult site_api_data.ABANDONED_GENESES", so a
    caller that knows nothing about aliases (deploy/reconcile_prereg_voids.py) gets the
    fix for free."""
    taxonomy._ABANDONED_CACHE["value"] = None  # never trust a cache another test warmed
    assert taxonomy.closing_cycle_for_genesis("2026-09-04", CYCLE_GENESES) == 15


# ── the census predicate (check 22) ───────────────────────────────────────────


def test_the_fixture_row_resolves_to_its_own_cycle_stamp():
    rv = _load_rv()
    counts, _ex, scanned = rv.tombstone_provenance_census(_pages(FRIDAY_ROW), _GENESES, _ALIASES)
    assert scanned == 1
    assert counts == {rv.TOMB_MATCHED: 1}


def test_the_mutation_control_the_census_reds_with_an_empty_alias_map():
    """RED before the alias, GREEN after — the free positive control the issue names. On
    the live table this is exactly 328 -> 0 (measured 2026-09-20)."""
    rv = _load_rv()
    counts, examples, _ = rv.tombstone_provenance_census(_pages(FRIDAY_ROW), _GENESES, {})
    assert counts == {rv.TOMB_UNRESOLVED: 1}
    assert "experiment_restart_2026-09-04" in examples[rv.TOMB_UNRESOLVED][0]


def test_a_row_with_no_tombstoned_reason_is_not_in_scope():
    rv = _load_rv()
    counts, _ex, scanned = rv.tombstone_provenance_census(
        _pages({"pk": "USER#matthew#SOURCE#whoop", "sk": "DATE#2026-09-10"}, {**FRIDAY_ROW, "tombstoned_reason": ""}),
        _GENESES,
        _ALIASES,
    )
    assert scanned == 2 and counts == {}


def test_a_reason_naming_no_genesis_is_counted_out_of_scope_not_guessed_at():
    """`legacy_daily_aggregate_superseded_by_per_workout` (421 live rows) names no genesis.
    Guessing one from `tombstoned_at` would attribute a bulk data migration to a reset."""
    rv = _load_rv()
    row = {"pk": "USER#matthew#SOURCE#hevy", "sk": "DATE#2021-04-12"}
    row["tombstoned_reason"] = "legacy_daily_aggregate_superseded_by_per_workout"
    row["tombstoned_at"] = "2026-09-05T12:00:00Z"
    counts, _ex, _ = rv.tombstone_provenance_census(_pages(row), _GENESES, _ALIASES)
    assert counts == {rv.TOMB_UNDATED: 1}


def test_the_census_reads_dated_reasons_beyond_experiment_restart():
    """Wider than phase_taxonomy.closing_genesis_of on purpose — 438 live rows carry the
    `countdown_gap_reconcile_<genesis>` family, and their genesis must resolve too."""
    rv = _load_rv()
    assert rv.genesis_in_reason("countdown_gap_reconcile_2026-09-05") == "2026-09-05"
    assert rv.genesis_in_reason("experiment_restart_2026-09-04") == "2026-09-04"
    assert rv.genesis_in_reason("fabricated_verdict_reconcile_1896") is None
    assert rv.genesis_in_reason(None) is None


def test_stamp_disagreement_classes_are_reported_and_do_not_block():
    """Two of the three disagreement shapes are the INTENDED archive, so the census
    separates them by name instead of failing on all three. `stamp_is_an_earlier_cycle`
    is #1202 working (the row kept the cycle it was born in); `stamp_is_a_later_cycle`
    is a real second finding (411 live rows) that no code change can repair — it is
    printed on every run so it cannot go quiet."""
    rv = _load_rv()
    earlier = {**FRIDAY_ROW, "sk": "DATE#2026-06-02", "tombstoned_reason": "experiment_restart_2026-09-05", "cycle": 4}
    later = {**FRIDAY_ROW, "sk": "DATE#2026-09-02", "tombstoned_reason": "experiment_restart_2026-09-05", "cycle": 16}
    unstamped = {**FRIDAY_ROW, "sk": "DATE#2026-09-03", "tombstoned_reason": "experiment_restart_2026-09-06", "cycle": None}
    counts, _ex, scanned = rv.tombstone_provenance_census(_pages(earlier, later, unstamped), _GENESES, _ALIASES)
    assert scanned == 3
    assert counts == {rv.TOMB_EARLIER: 1, rv.TOMB_LATER: 1, rv.TOMB_NO_STAMP: 1}
    assert counts.get(rv.TOMB_UNRESOLVED, 0) == 0  # none of the three blocks check 22


def test_a_cycle_one_genesis_reason_is_its_own_class_not_unresolved():
    rv = _load_rv()
    row = {**FRIDAY_ROW, "tombstoned_reason": "experiment_restart_2026-04-01", "cycle": 1}
    counts, _ex, _ = rv.tombstone_provenance_census(_pages(row), _GENESES, _ALIASES)
    assert counts == {rv.TOMB_CYCLE_ONE: 1}
