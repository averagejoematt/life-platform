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


def planned_states(plan_path: str) -> dict:
    """{date: state} computed FROM THE PLANNED ITEMS, in exactly the ``ladder_states`` state shape (the dry run asserts
    the last ladder step equals it on every field). Integrity-checked first; a plan without the field is refused."""
    plan = load_plan(plan_path)
    states = plan.get("planned_states")
    if not isinstance(states, dict):
        raise PlanGuardError("this plan carries no planned_states — re-run the dry run with the current tool")
    return dict(states)


def check_approval(approved: Optional[str], plan: dict, live_plan_id: Optional[str] = None) -> Optional[str]:
    """None when the owner's explicit approval names this exact plan (the file's id and, once re-derived, the live id);
    otherwise the refusal. Called before any backup or write."""
    if not approved:
        return "--apply needs --approved-plan-id <the exact plan id the owner approved>"
    if approved != plan.get("plan_id"):
        return f"--approved-plan-id {approved} is not this plan file's id {plan.get('plan_id')}"
    if live_plan_id is not None and approved != live_plan_id:
        return f"the plan re-derived from the live rows is {live_plan_id}, not the approved {approved} — re-run and re-approve"
    return None


def preflight(store: Any, plan: dict) -> dict:
    """Read-only backup preconditions: no backup exists yet under this plan id (ListObjectsV2) and the bucket is versioned
    (GetBucketVersioning). Nothing is written; what a read cannot prove is named."""
    prefix = f"{BACKUP_PREFIX}/{plan['plan_id']}/"
    existing = store.list_backups(prefix)
    versioning = store.bucket_versioning()
    return {
        "ok": not existing and versioning == "Enabled",
        "verified_read_only": {
            "backup_prefix": prefix,
            "no_backup_under_prefix_yet": not existing,
            "existing_keys": existing[:10],
            "bucket_versioning": versioning,
        },
        "unverifiable_without_a_write": [
            "the conditional put (IfNoneMatch='*') itself, and the role's s3:PutObject / dynamodb:PutItem at request time "
            "(IAM simulation is evidence, not the request)"
        ],
    }


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


def backup_key(plan_id: str) -> str:
    """THE pre-image of a plan: one S3 object per plan id, written once (IfNoneMatch), never replaced."""
    return f"{BACKUP_PREFIX}/{plan_id}/export.json"


def _verified_export(body: bytes, plan: dict) -> dict:
    export = json.loads(body)
    if export.get("schema") != EXPORT_SCHEMA or export.get("plan_id") != plan["plan_id"]:
        raise PlanGuardError("the backup under this plan id is not this plan's export — nothing written")
    if any(digest(e["preimage"]) != e["preimage_digest"] for e in export["entries"]):
        raise PlanGuardError("an exported pre-image does not hash to its recorded digest — nothing written")
    return export


def existing_preimages(store: Any, plan: dict) -> dict:
    """{(pk, sk): entry} of this plan's existing backup (an interrupted or phased apply), or {} when none exists."""
    key = backup_key(plan["plan_id"])
    if key not in store.list_backups(f"{BACKUP_PREFIX}/{plan['plan_id']}/"):
        return {}
    return {(e["pk"], e["sk"]): e for e in _verified_export(store.get_backup(key), plan)["entries"]}


def ensure_preimage(store: Any, plan: dict, out_dir: str, now: str) -> dict:
    """The plan's ONE pre-image, covering every row of every phase the plan writes.

    First apply: every planned row is read; a row that still equals the plan's stored pre-image is exported (a row that
    changed since the plan is left out and reported, never written); the export is written to ``export_<plan_id>.json``
    (+ ``.sha256``) and to S3 ``backup_key`` with IfNoneMatch, and both copies are re-read and hashed before any write.
    Later apply (a further phase, or a resume after an interruption): the existing S3 export is re-read and verified and
    is the pre-image — no second pre-image is ever taken or written. A different local copy refuses."""
    key = backup_key(plan["plan_id"])
    prefix = f"{BACKUP_PREFIX}/{plan['plan_id']}/"
    path = os.path.join(out_dir, f"export_{plan['plan_id']}.json")
    keys = store.list_backups(prefix)
    if keys and key not in keys:
        raise PlanGuardError(f"unexpected objects under {prefix}: {keys[:3]} — nothing written; inspect before any apply")
    if key in keys:
        body = store.get_backup(key)
        export = _verified_export(body, plan)
        if os.path.exists(path) and open(path, "rb").read() != body:
            raise PlanGuardError(f"the local {path} differs from the S3 pre-image — nothing written; restore it from S3")
        if not os.path.exists(path):
            with open(path, "wb") as fh:
                fh.write(body)
            with open(path + ".sha256", "w", encoding="utf-8") as fh:
                fh.write(hashlib.sha256(body).hexdigest() + "\n")
        export.update(_local_path=path, _s3_key=key, _sha256=hashlib.sha256(body).hexdigest(), _aborted_before_export=[], _resumed=True)
        return export
    entries, aborted = [], []
    for r in rows_for(plan, "all"):
        cur = store.get(r["pk"], r["sk"])
        cur_t = to_typed(cur) if cur is not None else None
        if cur_t is not None and digest(cur_t) == r.get("planned_digest"):
            raise PlanGuardError(f"{r['pk']} {r['sk']} already holds this plan's value but no backup exists — nothing written")
        if cur_t is None or digest(cur_t) != r["stored_digest"]:
            aborted.append({"pk": r["pk"], "sk": r["sk"], "reason": "the row changed since the plan"})
            continue
        entries.append(
            {"pk": r["pk"], "sk": r["sk"], "preimage": cur_t, "preimage_digest": r["stored_digest"], "planned_digest": r["planned_digest"]}
        )
    export = {"schema": EXPORT_SCHEMA, "plan_id": plan["plan_id"], "taken_at": now, "entries": entries}
    body = json.dumps(export, sort_keys=True, indent=1).encode()
    sha = hashlib.sha256(body).hexdigest()
    with open(path, "wb") as fh:
        fh.write(body)
    with open(path + ".sha256", "w", encoding="utf-8") as fh:
        fh.write(sha + "\n")
    with open(path, "rb") as fh:
        if hashlib.sha256(fh.read()).hexdigest() != sha:
            raise PlanGuardError("the local export does not read back to its hash — no write made")
    _verified_export(open(path, "rb").read(), plan)
    store.put_backup(key, body)  # IfNoneMatch: never over an existing object
    if hashlib.sha256(store.get_backup(key)).hexdigest() != sha:
        raise PlanGuardError("the S3 backup does not read back to the export's hash — no write made")
    export.update(_local_path=path, _s3_key=key, _sha256=sha, _aborted_before_export=aborted, _resumed=False)
    return export


def resume_state(store: Any, export: dict) -> list:
    """Every exported row must be exactly its pre-image or exactly its planned value; the rows that are neither."""
    bad = []
    for e in export["entries"]:
        cur = store.get(e["pk"], e["sk"])
        if cur is None or digest(to_typed(cur)) not in (e["preimage_digest"], e["planned_digest"]):
            bad.append(f"{e['pk']} {e['sk']}")
    return bad


class PreimageOverlay:
    """A read-only view of the store in which a row that holds this plan's planned value reads as its exported pre-image
    — so the approval check re-derives the plan an interrupted or phased apply started from, never the half state."""

    def __init__(self, store: Any, preimages: dict):
        self._store, self._pre = store, preimages

    def _swap(self, item: Optional[dict]) -> Optional[dict]:
        if not isinstance(item, dict):
            return item
        e = self._pre.get((item.get("pk"), item.get("sk")))
        if e is not None and digest(to_typed(item)) == e["planned_digest"]:
            return from_typed(e["preimage"])
        return item

    def query(self, pk: str, lo: str, hi: str) -> list:
        return [self._swap(i) for i in self._store.query(pk, lo, hi)]

    def get(self, pk: str, sk: str) -> Optional[dict]:
        return self._swap(self._store.get(pk, sk))

    def __getattr__(self, name: str) -> Any:
        if name in ("put", "put_backup"):
            raise RuntimeError(f"PreimageOverlay is read-only ({name} refused)")
        return getattr(self._store, name)


def apply_plan(
    store: Any,
    plan: dict,
    out_dir: str,
    phase: str,
    now: str,
    from_date: Optional[str] = None,
    limit: Optional[int] = None,
    approved_plan_id: Optional[str] = None,
) -> dict:
    """The conditional apply. The CLI always passes ``approved_plan_id`` (checked there against the file and the live id
    first); when given here it is checked again, before the export."""
    if approved_plan_id is not None and approved_plan_id != plan.get("plan_id"):
        raise PlanGuardError(f"approved plan id {approved_plan_id} is not this plan's {plan.get('plan_id')} — nothing written")
    rows = rows_for(plan, phase, from_date, limit)
    export = ensure_preimage(store, plan, out_dir, now)
    path = export["_local_path"]
    if export["_resumed"]:
        bad = resume_state(store, export)
        if bad:
            raise PlanGuardError(
                f"{len(bad)} exported row(s) are neither their pre-image nor this plan's value (e.g. {bad[0]}): a write outside "
                f"this tool since the interrupted apply — nothing written. Roll back: --rollback {path} --apply"
            )
    by_key = {(e["pk"], e["sk"]): e for e in export["entries"]}
    written, aborted = [], list(export["_aborted_before_export"])
    for r in rows:
        e = by_key.get((r["pk"], r["sk"]))
        if e is None:
            continue
        cur = store.get(r["pk"], r["sk"])
        if cur is not None and digest(to_typed(cur)) == e["planned_digest"]:
            continue  # already applied (an earlier, interrupted or phased run of this same plan): written once only
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
        "resumed": export["_resumed"],
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
    import recompute_character_private as T

    snap["raw_effects"] = T.collect_raw_effects(store, snap) if PLAN_SPEC.get("effects") else {"effects": {}, "reads": {}}
    res = run_ladder(child_inputs(snap), work, trees, (("plan", "plan", PLAN_SPEC),))["plan"]
    engine_keys = {d: set(res["sheet_attrs"].get(d) or {}) for d in snap["sheets"]}
    rows = build_rows(snap, res, engine_keys)
    pending = [f"{r['partition']} {r['sk']}" for r in rows if r["action"] == "write"]
    return {"rows": len(rows), "planned_writes": len(pending), "pending": pending}
