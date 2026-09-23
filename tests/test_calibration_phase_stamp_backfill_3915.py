"""tests/test_calibration_phase_stamp_backfill_3915.py — #3915 box 2, the row half:
`deploy/backfill_calibration_phase_stamp.py` strips the provenance the calibration
ledger's CROSS_PHASE class forbids, dry-run by default.

THE FIXTURES ARE THE WIRE
  The row shapes below are the live ones from the script's own first dry run
  (read-only Query of `USER#matthew#SOURCE#calibration`, 2026-09-22, 2,509 rows):
    prediction_void + cycle + tombstoned_at (reconciled)   1,404
    prediction_void + cycle                                  750
    forecast_resolution, no provenance                       229
    prediction_void + tombstoned_at, closing cycle unknown    69
    hypothesis_void + cycle + tombstoned_at (reconciled)      33
    hypothesis_void + cycle                                   24
  -> would change 2,280: [cycle+tombstoned_at] 1,437 · [cycle] 774 · [tombstoned_at] 69.
  No values are copied beyond the keys and the provenance attrs themselves.

WHAT IS PROVED
  1. The plan covers exactly the rows carrying forbidden provenance, by shape.
  2. `tombstoned_at` is MOVED to `bet_tombstoned_at` (content), `cycle` is removed — and
     an existing destination is never clobbered.
  3. Dry run writes nothing; `--apply` writes one update per planned row.
  4. MUTATION CONTROL: deleting the calibration ruling (or reverting it to a label) makes
     the plan EMPTY — the script defers to the registry, it does not re-derive it.
  5. Scope: it reads one partition with a Query and never Scans.
"""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "lambdas"))

from experiment import (
    phase_taxonomy as taxonomy,  # noqa: E402
    pk_census,  # noqa: E402
)


def _load_backfill():
    name = "backfill_calibration_phase_stamp"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / "deploy" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bf = _load_backfill()
PK = bf.CALIBRATION_PK

LIVE_ROWS = [
    # reconciled prediction void: cycle + tombstoned_at
    {
        "pk": PK,
        "sk": "CALIB#2026-07-13#void#pred#explorer_coach#pred_20260503_body_weight_will_mature_to_preliminary_d#eafdb6d4",
        "record_type": "prediction_void",
        "reset_genesis": "2026-07-13",
        "reconciled_by": "reconcile_prereg_voids.py (#1978)",
        "cycle": 5,
        "tombstoned_at": "2026-07-13T01:00:00+00:00",
    },
    # reset-written prediction void: cycle only
    {
        "pk": PK,
        "sk": "CALIB#2026-07-18#void#pred#explorer_coach#pred_20260713_over_the_first_7_days_the_daily_protein",
        "record_type": "prediction_void",
        "reset_genesis": "2026-07-18",
        "cycle": 7,
    },
    # forecast resolution: clean, never planned
    {"pk": PK, "sk": "CALIB#2026-07-06#forecast-recovery_pct-h1.0-2026-07-05", "record_type": "forecast_resolution"},
    # reconciled, closing cycle unknown: tombstoned_at only
    {
        "pk": PK,
        "sk": "CALIB#2026-08-03#void#pred#explorer_coach#pred_20260726_best_scored_recovery_mornings_will_show#915dfa5e",
        "record_type": "prediction_void",
        "reset_genesis": "2026-08-03",
        "reconciled_by": "reconcile_prereg_voids.py (#1978)",
        "cycle_attribution": "unknown (closing genesis 2026-08-03 not in CYCLE_GENESES)",
        "tombstoned_at": "2026-08-03T02:00:00+00:00",
    },
    # reconciled hypothesis void
    {
        "pk": PK,
        "sk": "CALIB#2026-07-13#void#hyp#genesis_prereg_h1#ca0ed3ee",
        "record_type": "hypothesis_void",
        "reset_genesis": "2026-07-13",
        "reconciled_by": "reconcile_prereg_voids.py (#1978)",
        "cycle": 5,
        "tombstoned_at": "2026-07-13T01:00:00+00:00",
    },
]


class FakeTable:
    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)
        self.queries: list = []
        self.updates: list = []

    def query(self, **kwargs):
        self.queries.append(kwargs)
        return {"Items": copy.deepcopy(self.rows)}

    def scan(self, **kwargs):  # pragma: no cover — the assertion IS the test
        raise AssertionError("the backfill must Query the single calibration partition, never Scan")

    def update_item(self, **kwargs):
        self.updates.append(kwargs)
        return {}


# ── 1. the plan ────────────────────────────────────────────────────────────────
def test_the_plan_matches_the_live_shapes():
    actions, shapes = bf.plan(FakeTable(LIVE_ROWS))
    assert len(actions) == 4  # the forecast_resolution row carries nothing
    assert dict(shapes) == {"cycle+tombstoned_at": 2, "cycle": 1, "tombstoned_at": 1}
    assert all(pk == PK for pk, _sk, _attrs, _item in actions)


def test_every_planned_row_is_clean_after_its_update():
    """Apply each planned update to a copy of its row and re-ask the SAME predicate the
    nightly uses: nothing forbidden may survive."""
    for _pk, _sk, attrs, item in bf.plan(FakeTable(LIVE_ROWS))[0]:
        after = dict(item)
        for a in attrs:
            dest = bf.PRESERVE_AS.get(a)
            if dest and after.get(dest) is None:
                after[dest] = after[a]
            after.pop(a)
        assert taxonomy.forbidden_provenance(PK, item["sk"], after) == []


# ── 2. move, don't delete ─────────────────────────────────────────────────────
def test_tombstoned_at_is_moved_not_deleted():
    row = LIVE_ROWS[0]
    kw = bf.build_strip_update(["cycle", "tombstoned_at"], row)
    names = kw["ExpressionAttributeNames"]
    assert kw["UpdateExpression"].startswith("SET ")
    assert "REMOVE " in kw["UpdateExpression"]
    assert "bet_tombstoned_at" in names.values()
    assert set(names.values()) == {"cycle", "tombstoned_at", "bet_tombstoned_at"}
    assert list(kw["ExpressionAttributeValues"].values()) == [row["tombstoned_at"]]
    # stale-read guard: the source value is pinned at plan time
    assert "ConditionExpression" in kw


def test_cycle_only_is_a_plain_remove():
    kw = bf.build_strip_update(["cycle"], LIVE_ROWS[1])
    assert kw["UpdateExpression"] == "REMOVE #a0"
    assert kw["ExpressionAttributeNames"] == {"#a0": "cycle"}
    assert "ExpressionAttributeValues" not in kw and "ConditionExpression" not in kw


def test_an_existing_destination_is_never_clobbered():
    row = dict(LIVE_ROWS[0], bet_tombstoned_at="2026-07-12T23:59:00+00:00")
    kw = bf.build_strip_update(["cycle", "tombstoned_at"], row)
    assert "bet_tombstoned_at" not in kw["ExpressionAttributeNames"].values()
    assert not kw["UpdateExpression"].startswith("SET ")


# ── 3. dry run vs apply ───────────────────────────────────────────────────────
def test_dry_run_writes_nothing(monkeypatch, capsys):
    table = FakeTable(LIVE_ROWS)
    monkeypatch.setattr(bf, "open_table", lambda: table)
    monkeypatch.setattr(sys, "argv", ["backfill_calibration_phase_stamp.py"])
    assert bf.main() == 0
    assert table.updates == []
    out = capsys.readouterr().out
    assert "would change 4 row(s)" in out and "DRY-RUN" in out


def test_apply_writes_one_update_per_planned_row(monkeypatch):
    table = FakeTable(LIVE_ROWS)
    monkeypatch.setattr(bf, "open_table", lambda: table)
    monkeypatch.setattr(sys, "argv", ["backfill_calibration_phase_stamp.py", "--apply"])
    assert bf.main() == 0
    assert len(table.updates) == 4
    assert {u["Key"]["sk"] for u in table.updates} == {r["sk"] for r in LIVE_ROWS if r["record_type"] != "forecast_resolution"}


# ── 4. mutation control: the script defers to the registry ────────────────────
@pytest.mark.parametrize("mutation", ["delete", "label"])
def test_without_the_in_scope_ruling_the_plan_is_empty(monkeypatch, mutation):
    rulings = dict(pk_census.CROSS_PHASE_PROVENANCE_RULINGS)
    if mutation == "delete":
        rulings.pop("SOURCE#calibration")
    else:
        rulings["SOURCE#calibration"] = dict(rulings["SOURCE#calibration"], disposition=pk_census.RULED_LABEL, allowed=("cycle",))
    monkeypatch.setattr(pk_census, "CROSS_PHASE_PROVENANCE_RULINGS", rulings)
    actions, shapes = bf.plan(FakeTable(LIVE_ROWS))
    assert actions == [] and not shapes


# ── 5. scope ──────────────────────────────────────────────────────────────────
def test_it_queries_one_partition_and_never_scans():
    table = FakeTable(LIVE_ROWS)
    bf.plan(table)
    assert len(table.queries) >= 1
