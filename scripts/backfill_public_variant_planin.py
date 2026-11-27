"""scripts/backfill_public_variant_planin.py — the public dry run on the PLANNED private rows (#6224, #6311).

Owner rulings 2026-11-26/27: ONE final recompute, shown as ONE combined dry run before any write. The private tool
(``scripts/recompute_character_private.py``, #6314) writes a plan file (schema ``character-private-recompute-plan-v1``);
``backfill_public_variant.py --plan-in <plan.json>`` computes the public projection and the event reconciliation on
those planned rows instead of the stored ones, so the owner sees the public result of the private plan before either
tool writes.

What this module guarantees:

  * the plan is the private tool's own, integrity-checked by its own loader (``load_plan``: schema, plan_id, every
    planned digest) — a clear error otherwise;
  * the plan covers the public window: every stored sheet date has a planned row, and the plan's window reaches the
    newest stored sheet — else refused (approval and apply fall inside one nightly cycle);
  * each public write carries the method-1 fingerprint of the PLANNED row (``expected_method1_digest``), and the
    apply refuses unless the live row has exactly that fingerprint — the public apply is valid only on top of exactly
    the approved private plan, applied;
  * the public plan has its own deterministic ``public_plan_id`` over (the private plan_id, the public method version,
    the planned public blocks without their run stamps) — a re-run on the deployed tree must reproduce it.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from typing import Any, Callable, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import backfill_public_variant as B  # noqa: E402

PRIVATE_PLAN_SCHEMA = "character-private-recompute-plan-v1"
# run stamps that differ between two runs of the same method on the same rows (never a method difference)
VOLATILE = frozenset({"computed_at", "reconstructed_at", "digest", "generated_at", "planned_at"})


class PlanInError(RuntimeError):
    """The private plan cannot be used for the public dry run (the message says why)."""


def load_private_plan(path: str) -> dict:
    """The private plan file, checked: its schema first (a clear error), then the private tool's own integrity check."""
    try:
        with open(path, encoding="utf-8") as fh:
            head = json.load(fh)
    except (OSError, ValueError) as exc:
        raise PlanInError(f"--plan-in {path}: not a readable JSON plan ({exc})") from exc
    if head.get("schema") != PRIVATE_PLAN_SCHEMA:
        raise PlanInError(f"--plan-in {path}: schema {head.get('schema')!r}, expected {PRIVATE_PLAN_SCHEMA!r}")
    import recompute_character_private_apply as A

    try:
        return A.load_plan(path)
    except Exception as exc:  # noqa: BLE001 — the private tool's own guard: edited, truncated, digest mismatch
        raise PlanInError(f"--plan-in {path}: the private plan fails its integrity check ({exc})") from exc


def planned_items(plan: dict, pk: str) -> dict:
    """{date: planned item, every number a float} for one partition — the private tool's own codec (``as_float``)."""
    import recompute_character_private_apply as A

    return {r["date"]: A.as_float(r["planned_item"]) for r in plan["rows"] if r["pk"] == pk and r.get("planned_item") is not None}


def check_coverage(plan: dict, stored_sheet_dates: list) -> None:
    """Refuse unless the plan covers the public window: every stored sheet date has a planned row, and the plan's window
    reaches the newest stored sheet."""
    planned = set(planned_items(plan, B.SHEET_PK))
    missing = sorted(d for d in stored_sheet_dates if d not in planned)
    if missing:
        raise PlanInError(
            f"a stored character_sheet exists for {len(missing)} date(s) the private plan does not cover (first {missing[0]}); "
            "re-run the private dry run — approval and apply must fall in one nightly cycle"
        )
    window = plan.get("window") or {}
    if stored_sheet_dates and str(window.get("end") or "") < max(stored_sheet_dates):
        raise PlanInError(f"the private plan's window ends {window.get('end')}, before the newest stored sheet {max(stored_sheet_dates)}")
    if stored_sheet_dates and str(window.get("start") or "9999") > min(stored_sheet_dates):
        raise PlanInError(f"the private plan's window starts {window.get('start')}, after the first stored sheet {min(stored_sheet_dates)}")


def apply_to_snapshot(snap: dict, plan: dict) -> dict:
    """Replace the snapshot's method-1 sheets (and receipts) with the PLANNED private rows, in place, after the coverage
    check. Returns {(pk, sk): expected method-1 fingerprint} — the planned row's, which the public apply requires."""
    check_coverage(plan, sorted(snap["sheets"]))
    sheets = planned_items(plan, B.SHEET_PK)
    receipts = planned_items(plan, B.RECEIPT_PK)
    snap["stored_sheets"] = snap["sheets"]
    snap["sheets"] = {d: item for d, item in sheets.items() if d in snap["stored_sheets"] and B.visible(item)}
    snap["receipts"] = {d: receipts.get(d, item) for d, item in snap["receipts"].items()}
    expected = {(B.SHEET_PK, f"DATE#{d}"): B.item_digest(item) for d, item in snap["sheets"].items()}
    expected.update({(B.RECEIPT_PK, f"DATE#{d}"): B.item_digest(item) for d, item in snap["receipts"].items()})
    return expected


def _stable(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _stable(v) for k, v in sorted(obj.items()) if k not in VOLATILE}
    if isinstance(obj, list):
        return [_stable(v) for v in obj]
    if isinstance(obj, float):
        return round(obj, 4)
    return obj


def public_plan_id(private_plan_id: Optional[str], method_version: str, plan: list) -> str:
    """16 hex over (the private plan_id, the public method version, every planned public write without its run stamps)."""
    body = [private_plan_id, method_version, [[w["pk"], w["sk"], _stable(B.decimals_to_float(w["value"]))] for w in plan]]
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()[:16]


def attach_expected(plan: list, expected: dict) -> list:
    """Each planned public write with the planned row's method-1 fingerprint it requires (``expected_method1_digest``)."""
    return [dict(w, expected_method1_digest=expected[(w["pk"], w["sk"])]) if (w["pk"], w["sk"]) in expected else w for w in plan]


def unplanned_rows(get_item: Callable[[dict], Optional[dict]], plan: list) -> list:
    """The planned public writes whose live row is NOT the approved planned private row (the private apply has not run,
    ran a different plan, or the row changed since) — the public apply refuses while this is non-empty."""
    out = []
    for w in plan:
        want = w.get("expected_method1_digest")
        if want is None:
            continue
        item = get_item({"pk": w["pk"], "sk": w["sk"]})
        if item is None or B.item_digest(item) != want:
            out.append(f"{w['pk'].split('#SOURCE#')[-1]} {w['sk']}")
    return out
