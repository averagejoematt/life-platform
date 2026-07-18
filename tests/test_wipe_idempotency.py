"""tests/test_wipe_idempotency.py — #1202: a later reset must not re-stamp prior archives.

Root cause (deploy/restart_intelligence_wipe.py): ``is_already_tombstoned`` only
recognised a tombstone written by the CURRENT genesis, so every reset re-tombstoned
records archived by earlier resets and ``build_update`` unconditionally SET ``cycle`` to
the latest closing run. The whole archive converged onto the newest cycle (a Feb
cycle-1 insight claimed cycle=5), defeating ADR-077's "archive navigable by reset
generation" guarantee (docs/PHASE_TAXONOMY.md: cycle=N answers "which run did this
belong to?").

These tests pin both halves of the fix:
  * ``is_already_tombstoned`` skips any already-tombstoned row (the live-flow guard), and
  * ``build_update`` writes the generation-identity attrs with ``if_not_exists`` so a
    second pass can never overwrite the first stamp (defence-in-depth).

The second test applies the real UpdateExpression twice — once per reset generation —
against a fixture item, honouring DynamoDB ``if_not_exists`` semantics, and asserts the
first cycle stamp survives.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# The wipe script self-manages sys.path (repo root + lambdas/) at import time.
_spec = importlib.util.spec_from_file_location("restart_intelligence_wipe", REPO_ROOT / "deploy" / "restart_intelligence_wipe.py")
wipe = importlib.util.module_from_spec(_spec)
sys.modules["restart_intelligence_wipe"] = wipe
_spec.loader.exec_module(wipe)


def _apply_update(item: dict, update_expr: str, names: dict, values: dict) -> dict:
    """Minimal DynamoDB SET-expression interpreter honouring ``if_not_exists``.

    Supports the two RHS forms build_update emits: ``:val`` (unconditional set) and
    ``if_not_exists(<attr>, :val)`` (set only when <attr> is absent from the item).
    Attribute-name placeholders (``#p``) are resolved via ``names``. Mutates + returns
    ``item``.
    """
    assert update_expr.startswith("SET "), update_expr
    body = update_expr.removeprefix("SET ")
    # Each assignment: TARGET = (if_not_exists(SRC, :val) | :val). The comma inside
    # if_not_exists is consumed by its own group, so scanning the whole body is safe.
    pattern = re.compile(r"([#\w]+)\s*=\s*(?:if_not_exists\(\s*([#\w]+)\s*,\s*(:\w+)\s*\)|(:\w+))")
    for m in pattern.finditer(body):
        target_tok, ine_attr_tok, ine_val_tok, plain_val_tok = m.groups()
        target = names.get(target_tok, target_tok)
        if plain_val_tok is not None:
            item[target] = values[plain_val_tok]
        else:
            src_attr = names.get(ine_attr_tok, ine_attr_tok)
            if src_attr not in item:
                item[target] = values[ine_val_tok]
    return item


def test_apply_update_helper_honours_if_not_exists():
    """Guard the test's own simulator so a bug here can't make the real test vacuous."""
    item = _apply_update({}, "SET a = if_not_exists(a, :v), #p = :p", {"#p": "phase"}, {":v": 1, ":p": "pilot"})
    assert item == {"a": 1, "phase": "pilot"}
    # Second pass: if_not_exists leaves the existing value; plain SET overwrites.
    _apply_update(item, "SET a = if_not_exists(a, :v), #p = :p", {"#p": "phase"}, {":v": 99, ":p": "recovery"})
    assert item == {"a": 1, "phase": "recovery"}


def test_build_update_uses_if_not_exists_for_generation_identity():
    """The generation-identity attrs are preserve-first; the hide flags are set-always."""
    expr, _names, _values = wipe.build_update({}, "2026-07-13T00:00:00+00:00", 5)
    assert "#cyc = if_not_exists(#cyc, :cycle)" in expr
    assert "tombstoned_at = if_not_exists(tombstoned_at, :ts)" in expr
    assert "tombstoned_reason = if_not_exists(tombstoned_reason, :reason)" in expr
    # tombstone + phase stay unconditional (inert when re-set on an already-hidden row).
    assert "tombstone = :tomb" in expr
    assert "#p = :phase" in expr


def test_first_cycle_stamp_survives_a_later_reset(monkeypatch):
    """The regression guard: run build_update twice with two different TOMBSTONE_REASONs
    against one fixture item; the first cycle stamp (and tombstoned_at/reason) survive."""
    # Reset generation 1 — cycle 4, April genesis — tombstones a fresh cycle-1 insight.
    monkeypatch.setattr(wipe, "TOMBSTONE_REASON", "experiment_restart_2026-04-01")
    expr1, names1, vals1 = wipe.build_update({}, "2026-04-01T00:00:00+00:00", 4)
    item = _apply_update(
        {"pk": "USER#matthew#SOURCE#insights", "sk": "INSIGHT#2026-02-23T02:13:57"},
        expr1,
        names1,
        vals1,
    )
    assert item["cycle"] == 4
    assert item["tombstoned_at"] == "2026-04-01T00:00:00+00:00"
    assert item["tombstoned_reason"] == "experiment_restart_2026-04-01"

    # Reset generation 2 — cycle 5, a LATER genesis, different reason — sweeps the same row.
    monkeypatch.setattr(wipe, "TOMBSTONE_REASON", "experiment_restart_2026-07-13")
    expr2, names2, vals2 = wipe.build_update({}, "2026-07-13T00:00:00+00:00", 5)
    _apply_update(item, expr2, names2, vals2)

    # The archive keeps the reset generation it was FIRST stamped with (ADR-077).
    assert item["cycle"] == 4, "cycle stamp was overwritten by a later reset (#1202 regressed)"
    assert item["tombstoned_at"] == "2026-04-01T00:00:00+00:00"
    assert item["tombstoned_reason"] == "experiment_restart_2026-04-01"
    # Still hidden from the current run — the phase flag is (correctly) unconditional.
    assert item["phase"] == "pilot"
    assert item["tombstone"] is True


def test_is_already_tombstoned_skips_any_prior_generation(monkeypatch):
    """Live-flow guard: main()'s loop skips a row tombstoned by ANY reset, so the
    per-item build_update/update_item write never fires on a prior archive at all."""
    monkeypatch.setattr(wipe, "TOMBSTONE_REASON", "experiment_restart_2026-07-13")
    prior = {"tombstone": True, "tombstoned_reason": "experiment_restart_2026-04-01", "cycle": 4}
    current = {"tombstone": True, "tombstoned_reason": "experiment_restart_2026-07-13", "cycle": 5}
    assert wipe.is_already_tombstoned(prior) is True  # the bug: this used to be False
    assert wipe.is_already_tombstoned(current) is True
    # A never-tombstoned (newly in-scope) record is still fair game.
    assert wipe.is_already_tombstoned({"pk": "x", "sk": "y"}) is False
    assert wipe.is_already_tombstoned({"tombstone": False}) is False
