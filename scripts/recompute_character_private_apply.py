#!/usr/bin/env python3
"""scripts/recompute_character_private_apply.py — the WRITE half of ``recompute_character_private.py`` (#6311).

Loading and integrity-checking an approved plan, the pre-image export and its verification, the conditional apply, the
zero-write ``verify`` and the verified ``rollback``. Split from the dry-run half by the module-size ceiling (#1665); the
CLI (``recompute_character_private.main``) is the only entry point, and ``--apply`` / ``--rollback --apply`` are its only
writing paths.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
from typing import Any, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from recompute_character_private import (  # noqa: E402
    BACKUP_PREFIX,
    EXPERIMENT_START_DATE,
    EXPORT_SCHEMA,
    PLAN_SCHEMA,
    PLAN_SPEC,
    PROVENANCE,
    RECEIPT_PK,
    ROOT,
    SHEET_PK,
    WRITTEN_PARTITIONS,
    ConditionFailed,
    PlanGuardError,
    as_float,
    assert_character_keys,
    build_rows,
    canonical,
    child_inputs,
    digest,
    from_typed,
    load_snapshot,
    refuse_in_repo,
    run_ladder,
    to_typed,
)


def planned_sheets(plan_path: str) -> dict:
    """{date: planned sheet item, every number a float} from a plan file — the stored-sheets shape the public backfill
    reads (``backfill_public_variant_cli.load_snapshot``'s ``sheets``). An unchanged row's planned item is the stored
    item; a "not_planned" row is omitted. The file is integrity-checked first (``load_plan``)."""
    plan = load_plan(plan_path)
    return {r["date"]: as_float(r["planned_item"]) for r in plan["rows"] if r["pk"] == SHEET_PK and r["planned_item"] is not None}


def planned_receipts(plan_path: str) -> dict:
    """{date: planned receipt item, every number a float} from a plan file — the convention of ``planned_sheets`` (an
    unchanged row's planned item is the stored item; a "not_planned" row is omitted). Integrity-checked first."""
    plan = load_plan(plan_path)
    return {r["date"]: as_float(r["planned_item"]) for r in plan["rows"] if r["pk"] == RECEIPT_PK and r["planned_item"] is not None}


def ladder_states(plan_path: str) -> dict:
    """The chain's per-date values after each ladder step, cumulatively: {cause: {date: {character_level, character_xp,
    composite, pillars: {pillar: {raw_score, level}}, events: [{who, type, old, new}]}}}, causes in ladder order (the
    shape is documented in ``recompute_character_private``'s docstring). Integrity-checked first; a plan written before
    the field existed is refused (re-run the dry run), never guessed."""
    plan = load_plan(plan_path)
    states = plan.get("ladder_states")
    if not isinstance(states, dict):
        raise PlanGuardError("this plan carries no ladder_states — re-run the dry run with the current tool")
    order = [step["cause"] for step in plan.get("ladder") or []]
    return {c: states[c] for c in order if c in states}


def stored_states(plan_path: str) -> dict:
    """{date: state} of the STORED rows, in exactly the ``ladder_states`` state shape — the baseline ``replay_residual``
    is compared against. Integrity-checked first; a plan written before the field existed is refused."""
    plan = load_plan(plan_path)
    states = plan.get("stored_states")
    if not isinstance(states, dict):
        raise PlanGuardError("this plan carries no stored_states — re-run the dry run with the current tool")
    return dict(states)


# ── apply, verify, rollback ─────────────────────────────────────────────────────────────────────────────────────────


PHASES = {"sheets": (SHEET_PK,), "receipts": (RECEIPT_PK,), "all": (SHEET_PK, RECEIPT_PK)}


def load_plan(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        plan = json.load(fh)
    if plan.get("schema") != PLAN_SCHEMA:
        raise PlanGuardError("not a private recompute plan")
    pid = hashlib.sha256(
        canonical([[r["pk"], r["sk"], r["stored_digest"], r.get("planned_compare_digest")] for r in plan["rows"]]).encode()
    ).hexdigest()[:16]
    if pid != plan["plan_id"]:
        raise PlanGuardError("the plan file's rows do not hash to its plan_id (edited or truncated)")
    for r in plan["rows"]:
        if r["action"] == "write" and digest(r["planned_item"]) != r["planned_digest"]:
            raise PlanGuardError(f"planned item digest mismatch: {r['pk']} {r['sk']}")
    assert_character_keys(plan["rows"], plan["window"]["start"], plan["window"]["end"])
    return plan


def rows_for(plan: dict, phase: str, from_date: Optional[str] = None, limit: Optional[int] = None) -> list:
    keep = PHASES[phase]
    rows = [r for r in plan["rows"] if r["action"] == "write" and r["pk"] in keep and (not from_date or r["date"] >= from_date)]
    rows.sort(key=lambda r: (WRITTEN_PARTITIONS.index(r["pk"]), r["date"]))
    return rows[:limit] if limit else rows


def write_condition(pre: dict) -> list:
    """The write is conditional on the pre-image: the row exists, its nightly stamps are the exported ones, and it
    carries no recompute provenance other than the exported one."""
    cond: list = [("exists", "pk")]
    for k in ("computed_at", "run_id"):
        cond.append(("eq", k, from_typed(pre[k])) if k in pre else ("not_exists", k))
    if PROVENANCE in pre:
        cond.append(("eq", [PROVENANCE, "plan_id"], pre[PROVENANCE]["plan_id"]))
    else:
        cond.append(("not_exists", PROVENANCE))
    return cond


def export_and_verify(store: Any, plan: dict, rows: list, out_dir: str, phase: str, now: str) -> tuple:
    """The pre-image of every row about to be written, to a local file AND S3 ``backups/``, each re-read and hashed.
    Returns (export, path). Raises (no write happens) on any mismatch."""
    entries, aborted = [], []
    for r in rows:
        cur = store.get(r["pk"], r["sk"])
        cur_t = to_typed(cur) if cur is not None else None
        if cur_t is not None and digest(cur_t, exclude=(PROVENANCE,)) == r["planned_compare_digest"]:
            continue  # already applied (resume): not exported again, not written again
        if cur_t is None or digest(cur_t) != r["stored_digest"]:
            aborted.append({"pk": r["pk"], "sk": r["sk"], "reason": "the row changed since the plan"})
            continue
        entries.append(
            {"pk": r["pk"], "sk": r["sk"], "preimage": cur_t, "preimage_digest": r["stored_digest"], "planned_digest": r["planned_digest"]}
        )
    export = {"schema": EXPORT_SCHEMA, "plan_id": plan["plan_id"], "phase": phase, "taken_at": now, "entries": entries}
    body = json.dumps(export, sort_keys=True, indent=1).encode()
    sha = hashlib.sha256(body).hexdigest()
    path = os.path.join(out_dir, f"export_{plan['plan_id']}_{phase}_{now.replace(':', '')}.json")
    with open(path, "wb") as fh:
        fh.write(body)
    with open(path + ".sha256", "w", encoding="utf-8") as fh:
        fh.write(sha + "\n")
    with open(path, "rb") as fh:
        if hashlib.sha256(fh.read()).hexdigest() != sha:
            raise PlanGuardError("the local export does not read back to its hash — no write made")
    reread = json.loads(open(path, encoding="utf-8").read())
    if any(digest(e["preimage"]) != e["preimage_digest"] for e in reread["entries"]):
        raise PlanGuardError("an exported pre-image does not hash to its recorded digest — no write made")
    key = f"{BACKUP_PREFIX}/{plan['plan_id']}/{phase}-{now.replace(':', '')}/export.json"
    store.put_backup(key, body)
    if hashlib.sha256(store.get_backup(key)).hexdigest() != sha:
        raise PlanGuardError("the S3 backup does not read back to the export's hash — no write made")
    export["_local_path"], export["_s3_key"], export["_sha256"], export["_aborted_before_export"] = path, key, sha, aborted
    return export, path


def apply_plan(
    store: Any, plan: dict, out_dir: str, phase: str, now: str, from_date: Optional[str] = None, limit: Optional[int] = None
) -> dict:
    rows = rows_for(plan, phase, from_date, limit)
    export, path = export_and_verify(store, plan, rows, out_dir, phase, now)
    by_key = {(e["pk"], e["sk"]): e for e in export["entries"]}
    written, aborted = [], list(export["_aborted_before_export"])
    for r in rows:
        e = by_key.get((r["pk"], r["sk"]))
        if e is None:
            continue
        cur = store.get(r["pk"], r["sk"])
        if cur is None or digest(to_typed(cur)) != e["preimage_digest"]:
            aborted.append({"pk": r["pk"], "sk": r["sk"], "reason": "the row changed after the export"})
            continue
        try:
            store.put(from_typed(r["planned_item"]), write_condition(e["preimage"]))
        except ConditionFailed:
            aborted.append({"pk": r["pk"], "sk": r["sk"], "reason": "conditional write refused (pre-image changed)"})
            continue
        after = store.get(r["pk"], r["sk"])
        ok = after is not None and digest(to_typed(after)) == r["planned_digest"]
        written.append({"pk": r["pk"], "sk": r["sk"], "verified": ok})
    result = {
        "plan_id": plan["plan_id"],
        "phase": phase,
        "export": path,
        "s3_key": export["_s3_key"],
        "written": written,
        "aborted": aborted,
    }
    with open(os.path.join(out_dir, f"apply_{plan['plan_id']}_{phase}_{now.replace(':', '')}.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=1, sort_keys=True)
    return result


def rollback(store: Any, export_path: str, *, apply: bool) -> dict:
    """Restore every exported pre-image where the row still holds what the apply wrote, then verify byte for byte."""
    body = open(export_path, "rb").read()
    side = export_path + ".sha256"
    if os.path.exists(side) and open(side, encoding="utf-8").read().strip() != hashlib.sha256(body).hexdigest():
        raise PlanGuardError("the export does not match its recorded sha256")
    export = json.loads(body)
    if export.get("schema") != EXPORT_SCHEMA:
        raise PlanGuardError("not a private recompute export")
    ops, refused = [], []
    for e in export["entries"]:
        cur = store.get(e["pk"], e["sk"])
        cur_t = to_typed(cur) if cur is not None else None
        if cur_t is not None and digest(cur_t) == e["preimage_digest"]:
            ops.append({"pk": e["pk"], "sk": e["sk"], "op": "already_preimage"})
            continue
        if cur_t is None or digest(cur_t) != e["planned_digest"]:
            refused.append({"pk": e["pk"], "sk": e["sk"], "reason": "the row is neither the pre-image nor what the apply wrote"})
            continue
        ops.append({"pk": e["pk"], "sk": e["sk"], "op": "restore"})
        if apply:
            try:
                store.put(from_typed(e["preimage"]), [("exists", "pk"), ("eq", [PROVENANCE, "plan_id"], export["plan_id"])])
            except ConditionFailed:
                refused.append({"pk": e["pk"], "sk": e["sk"], "reason": "conditional restore refused"})
    verified = None
    if apply:
        mism = []
        for e in export["entries"]:
            cur = store.get(e["pk"], e["sk"])
            if cur is None or canonical(to_typed(cur)) != canonical(e["preimage"]):
                mism.append(f"{e['pk']} {e['sk']}")
        verified = {"entries": len(export["entries"]), "byte_equal": len(export["entries"]) - len(mism), "mismatches": mism}
    return {"applied": apply, "operations": ops, "refused": refused, "verified": verified}


def verify(store: Any, out_dir: str, start: str = EXPERIMENT_START_DATE, end: Optional[str] = None, trees: Optional[dict] = None) -> dict:
    """Zero-write post-verification: a fresh plan (the amended method only) over the stored rows must write nothing."""
    snap = load_snapshot(store, start, end)
    os.makedirs(refuse_in_repo(out_dir), exist_ok=True)
    work = tempfile.mkdtemp(prefix="verify-", dir=out_dir)
    trees = trees or {"new": ROOT}
    res = run_ladder(child_inputs(snap), work, trees, (("plan", "missing_data", PLAN_SPEC),))["plan"]
    engine_keys = {d: set(res["sheet_attrs"].get(d) or {}) for d in snap["sheets"]}
    rows = build_rows(snap, res, engine_keys)
    pending = [f"{r['partition']} {r['sk']}" for r in rows if r["action"] == "write"]
    return {"rows": len(rows), "planned_writes": len(pending), "pending": pending}
