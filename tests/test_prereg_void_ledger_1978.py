"""tests/test_prereg_void_ledger_1978.py — the pre-registered-bet ledger invariant (#1978).

#1199 made the reset write a `voided_at_reset` row for every OPEN pre-registered bet
before the wipe tombstones it. That fix was forward-only and nothing ever ASSERTED it,
so two populations went hidden-and-unresolved: everything tombstoned before #1199
landed, and anything whose void row was clobbered by a same-genesis re-registration
reusing the same slug.

What is pinned here:
  1. The invariant FIRES on a synthetic open+tombstoned+unvoided row (the negative test
     that would have caught the live gap), and stays quiet on every healthy shape.
  2. Slug-only matching is NOT sufficient — a void row for the same slug from a
     different cycle must not count as proof (this is the exact live failure).
  3. The void-row sk is collision-proof across cycles that reuse a slug, while staying
     idempotent for the same bet.
  4. The reconcile script's classification is correct for a synthetic row of each class,
     and its planned rows are honest: voided, cycle-stamped from the row's OWN
     provenance, never back-graded, never Brier-scorable.

No AWS: a fake table serves fixture rows; everything else is pure.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from experiment import calibration_core, phase_taxonomy as taxonomy, prereg_voids  # noqa: E402


def _load_deploy(name: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "deploy" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


reconcile = _load_deploy("reconcile_prereg_voids")

_FIX = taxonomy.PREREG_VOID_FIX_LANDED  # "2026-07-17"


# ── fixture bets ─────────────────────────────────────────────────────────────


def _hyp(sk_ts, hid, status="pending", tombstone=False, tombstoned_reason=None, cycle=None):
    bet = {
        "sk": f"HYPOTHESIS#{sk_ts}",
        "hypothesis_id": hid,
        "hypothesis": f"claim {hid}",
        "status": status,
        "confidence": "low",
        "created_at": sk_ts,
        "pre_registered_at": sk_ts,
    }
    if tombstone:
        bet["tombstone"] = True
        bet["tombstoned_reason"] = tombstoned_reason or "experiment_restart_2026-07-13"
        bet["tombstoned_at"] = (tombstoned_reason or "experiment_restart_2026-07-13").split("_")[-1] + "T01:00:00+00:00"
    if cycle is not None:
        bet["cycle"] = cycle
    return bet


def _void_row(kind, bet, genesis, cycle=5):
    return prereg_voids.build_void_calib_item(kind, bet, genesis, cycle, "2026-07-13T02:00:00+00:00")


# ── 1. the invariant fires ───────────────────────────────────────────────────


def test_invariant_fires_on_open_tombstoned_unvoided_row():
    orphan = _hyp("2026-05-10T19:01:01.507348+00:00", "hyp_glucose_lag", tombstone=True)
    with pytest.raises(ValueError) as exc:
        taxonomy.assert_no_unvoided_open_bets([("hypothesis", orphan)], [])
    msg = str(exc.value)
    assert "invariant BREACHED" in msg
    assert "hypothesis=1" in msg
    assert "reconcile_prereg_voids.py --apply" in msg  # names the remedy, not just the fault


def test_invariant_quiet_on_every_healthy_shape():
    live_open = _hyp("2026-08-01T00:00:00+00:00", "hyp_live")  # open, not yet archived
    graded = _hyp("2026-05-10T00:00:00+00:00", "hyp_graded", status="refuted", tombstone=True)
    resolved = _hyp("2026-05-11T00:00:00+00:00", "hyp_resolved", tombstone=True)
    bets = [("hypothesis", live_open), ("hypothesis", graded), ("hypothesis", resolved)]
    voids = [_void_row("hypothesis", resolved, "2026-07-13")]
    assert taxonomy.find_unvoided_open_bets(bets, voids) == []
    assert taxonomy.assert_no_unvoided_open_bets(bets, voids) == 0


def test_invariant_counts_predictions_too():
    pred = {
        "sk": "PREDICTION#p_a",
        "prediction_id": "p_a",
        "coach_id": "sleep_coach",
        "status": "pending",
        "created_date": "2026-04-29",
        "tombstone": True,
        "tombstoned_reason": "experiment_restart_2026-07-13",
    }
    with pytest.raises(ValueError, match="prediction=1"):
        taxonomy.assert_no_unvoided_open_bets([("prediction", pred)], [])


# ── 2. slug-only matching is not proof (the live failure) ────────────────────


def test_same_slug_from_another_cycle_is_not_proof_of_resolution():
    # The genesis pre-registration reuses genesis_prereg_h1 EVERY cycle. Cycle A's bet
    # was voided; cycle B's identically-named bet was not — and must still be flagged.
    cycle_a = _hyp("2026-07-13T03:26:30.671332+00:00", "genesis_prereg_h1", tombstone=True)
    cycle_b = _hyp(
        "2026-07-18T22:02:16.808142+00:00",
        "genesis_prereg_h1",
        tombstone=True,
        tombstoned_reason="experiment_restart_2026-07-20",
    )
    voids = [_void_row("hypothesis", cycle_a, "2026-07-18")]
    orphans = taxonomy.find_unvoided_open_bets([("hypothesis", cycle_a), ("hypothesis", cycle_b)], voids)
    assert [b["sk"] for _, b in orphans] == [cycle_b["sk"]]


# ── 3. the void-row sk no longer collides ────────────────────────────────────


def test_void_row_sk_is_unique_per_bet_and_idempotent_per_bet():
    a = _hyp("2026-07-18T22:02:16.808142+00:00", "genesis_prereg_h1")
    b = _hyp("2026-07-20T02:55:03.029602+00:00", "genesis_prereg_h1")
    # Same genesis + same slug + DIFFERENT registration → different sk (no clobber).
    assert taxonomy.void_row_sk("2026-07-20", "hypothesis", a) != taxonomy.void_row_sk("2026-07-20", "hypothesis", b)
    # Same bet twice → same sk (a re-run overwrites its own row, not someone else's).
    assert taxonomy.void_row_sk("2026-07-20", "hypothesis", a) == taxonomy.void_row_sk("2026-07-20", "hypothesis", a)
    # Still inside the CALIB#<genesis>#void# namespace the ledger readers scan.
    assert taxonomy.void_row_sk("2026-07-20", "hypothesis", a).startswith("CALIB#2026-07-20#void#hyp#genesis_prereg_h1")


def test_void_row_and_bet_agree_by_construction():
    bet = _hyp("2026-07-05T19:00:48.727764+00:00", "hyp_sedentary", tombstone=True)
    row = _void_row("hypothesis", bet, "2026-07-13")
    assert taxonomy.void_row_ledger_key(row) == taxonomy.bet_ledger_key("hypothesis", bet)


# ── 4. reconcile classification + row honesty ────────────────────────────────


_CYCLE_GENESES = {1: "2026-04-01", 5: "2026-07-12", 6: "2026-07-13", 8: "2026-07-19", 9: "2026-07-20"}


def _classify(bet, voids=(), kind="hypothesis"):
    keys = {k for k in (taxonomy.void_row_ledger_key(r) for r in voids) if k is not None}
    return reconcile.classify_bet(kind, bet, keys)


def test_classification_of_one_synthetic_row_per_class():
    graded = _hyp("2026-05-10T00:00:00+00:00", "h_graded", status="refuted", tombstone=True)
    live = _hyp("2026-08-01T00:00:00+00:00", "h_live")
    resolved = _hyp("2026-05-11T00:00:00+00:00", "h_resolved", tombstone=True)
    pre_fix = _hyp("2026-05-12T00:00:00+00:00", "h_pre", tombstone=True, tombstoned_reason="experiment_restart_2026-07-13")
    post_fix = _hyp("2026-07-18T22:02:16+00:00", "h_post", tombstone=True, tombstoned_reason="experiment_restart_2026-07-20")

    assert _classify(graded) == reconcile.GRADED
    assert _classify(live) == reconcile.LIVE_OPEN
    assert _classify(resolved, [_void_row("hypothesis", resolved, "2026-07-13")]) == reconcile.ALREADY_VOIDED
    assert _classify(pre_fix) == reconcile.ORPHAN_PRE_FIX
    assert _classify(post_fix) == reconcile.ORPHAN_POST_FIX
    # The split is on the reset's genesis, not on when the reconcile happens to run.
    assert "2026-07-13" < _FIX <= "2026-07-20"


def test_closing_cycle_is_derived_from_the_rows_own_provenance():
    # The reset that OPENS cycle 6 (genesis 2026-07-13) CLOSES cycle 5 — the number the
    # wipe stamps on what it archives.
    bet = _hyp("2026-05-12T00:00:00+00:00", "h_pre", tombstone=True, tombstoned_reason="experiment_restart_2026-07-13", cycle=1)
    assert taxonomy.closing_genesis_of(bet) == "2026-07-13"
    assert taxonomy.closing_cycle_for_genesis("2026-07-13", _CYCLE_GENESES) == 5
    row = reconcile.build_reconcile_row("hypothesis", bet, reconcile.ORPHAN_PRE_FIX, _CYCLE_GENESES, "2026-08-02T00:00:00+00:00", 11)
    assert row["cycle"] == 5  # the cycle that actually closed it…
    assert row["reconciled_at_cycle"] == 11  # …not the cycle the backfill ran in
    assert row["bet_cycle_stamp"] == 1  # the row's own (create-time) stamp is preserved, not overwritten
    assert row["reset_genesis"] == "2026-07-13"


def test_unresolvable_closing_cycle_is_reported_not_invented():
    bet = _hyp("2026-05-12T00:00:00+00:00", "h_odd", tombstone=True, tombstoned_reason="experiment_restart_2029-01-01")
    row = reconcile.build_reconcile_row("hypothesis", bet, reconcile.ORPHAN_PRE_FIX, _CYCLE_GENESES, "2026-08-02T00:00:00+00:00", 11)
    assert "cycle" not in row  # None is dropped rather than defaulted to a number
    assert "unknown" in row["cycle_attribution"]


def test_reconciled_row_is_voided_never_back_graded():
    bet = _hyp("2026-05-12T00:00:00+00:00", "h_pre", tombstone=True, tombstoned_reason="experiment_restart_2026-07-13")
    row = reconcile.build_reconcile_row("hypothesis", bet, reconcile.ORPHAN_PRE_FIX, _CYCLE_GENESES, "2026-08-02T00:00:00+00:00", 11)
    assert row["outcome"] == "voided_at_reset"
    assert row["status_at_reset"] == "pending"  # what it actually was — no invented verdict
    assert "never graded" in row["void_reason"] and "#1199" in row["void_reason"]
    # ADR-104/105: a voided bet must never move the calibration curve in either direction.
    assert calibration_core.outcome_to_binary(row["outcome"]) is None
    assert calibration_core.pairs_from_calibration_rows([row]) == []
    # CROSS_PHASE — survives the next wipe, which is the whole point of the ledger.
    assert taxonomy.classify(row["pk"], row["sk"]) == taxonomy.CROSS_PHASE


def test_post_fix_orphan_reason_names_the_sk_clobber():
    bet = _hyp("2026-07-18T22:02:16+00:00", "genesis_prereg_h1", tombstone=True, tombstoned_reason="experiment_restart_2026-07-20")
    row = reconcile.build_reconcile_row("hypothesis", bet, reconcile.ORPHAN_POST_FIX, _CYCLE_GENESES, "2026-08-02T00:00:00+00:00", 11)
    assert "overwriting it" in row["void_reason"]
    assert row["cycle"] == 8  # genesis 2026-07-20 opens cycle 9 → closes cycle 8


# ── end-to-end over a fake table ─────────────────────────────────────────────


class _FakeTable:
    def __init__(self, by_pk):
        self._by_pk = by_pk
        self.puts = []

    def query(self, **kw):
        vals = kw["ExpressionAttributeValues"]
        items = [i for i in self._by_pk.get(vals[":pk"], []) if str(i.get("sk", "")).startswith(vals.get(":skp", ""))]
        return {"Items": items}

    def put_item(self, Item=None, **_kw):
        self.puts.append(Item)


def _mixed_table():
    resolved = _hyp("2026-05-11T00:00:00+00:00", "h_resolved", tombstone=True)
    return (
        _FakeTable(
            {
                prereg_voids.HYPOTHESES_PK: [
                    _hyp("2026-05-10T00:00:00+00:00", "h_graded", status="refuted", tombstone=True),
                    _hyp("2026-08-01T00:00:00+00:00", "h_live"),
                    resolved,
                    _hyp("2026-05-12T00:00:00+00:00", "h_pre", tombstone=True, tombstoned_reason="experiment_restart_2026-07-13"),
                    _hyp("2026-07-18T22:02:16+00:00", "h_post", tombstone=True, tombstoned_reason="experiment_restart_2026-07-20"),
                ],
                prereg_voids.CALIBRATION_PK: [_void_row("hypothesis", resolved, "2026-07-13")],
            }
        ),
        resolved,
    )


def test_plan_is_read_only_and_selects_exactly_the_orphans():
    table, _ = _mixed_table()
    census, rows, orphans = reconcile.plan(table, _CYCLE_GENESES, ("hypothesis",), "2026-08-02T00:00:00+00:00", 11)
    assert table.puts == []  # dry-run touches nothing
    assert census[("hypothesis", reconcile.GRADED)] == 1
    assert census[("hypothesis", reconcile.LIVE_OPEN)] == 1
    assert census[("hypothesis", reconcile.ALREADY_VOIDED)] == 1
    assert census[("hypothesis", reconcile.ORPHAN_PRE_FIX)] == 1
    assert census[("hypothesis", reconcile.ORPHAN_POST_FIX)] == 1
    assert sorted(b["hypothesis_id"] for _, b, _ in orphans) == ["h_post", "h_pre"]
    assert len(rows) == 2


def test_reconcile_rows_satisfy_the_invariant_that_flagged_them():
    # The closing loop: feed the planned rows back in as ledger rows and the invariant
    # that raised must now return 0 — the fix and the guard agree on one identity rule.
    table, _ = _mixed_table()
    _, rows, _ = reconcile.plan(table, _CYCLE_GENESES, ("hypothesis",), "2026-08-02T00:00:00+00:00", 11)
    before = prereg_voids.query_all(table, prereg_voids.CALIBRATION_PK, "CALIB#")
    with pytest.raises(ValueError):
        prereg_voids.assert_prereg_ledger_complete(table)
    bets = prereg_voids.collect_open_bets(table, include_tombstoned=True)
    assert taxonomy.assert_no_unvoided_open_bets(bets, before + rows) == 0


def test_planned_row_skeys_are_distinct():
    table, _ = _mixed_table()
    _, rows, _ = reconcile.plan(table, _CYCLE_GENESES, ("hypothesis",), "2026-08-02T00:00:00+00:00", 11)
    assert len({r["sk"] for r in rows}) == len(rows)


def test_cycle_geneses_registry_parses_from_the_live_file():
    geneses = reconcile.read_cycle_geneses()
    assert geneses[1] == "2026-04-01"
    assert max(geneses) >= 11
    # Every registered genesis resolves to a closing cycle except cycle 1 (no predecessor).
    assert taxonomy.closing_cycle_for_genesis(geneses[1], geneses) is None
    assert taxonomy.closing_cycle_for_genesis(geneses[max(geneses)], geneses) == max(geneses) - 1
