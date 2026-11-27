#!/usr/bin/env python3
"""scripts/recompute_character_private.py — the ONE private recompute of the stored character history under the
amended method (engine v1.10.0, config v1.7.0; #6293), #6311.

THE RULING (owner, 2026-11-26). "Build the narrowly scoped private recompute tool first ... Accurate stored and served
baselines. Complete per-date before/after dry runs. Explicit separation of methodological changes. Backup before writes.
Verified rollback. Idempotence and zero-write post-verification. Preservation of legitimate historical achievements.
Reconciliation of the 46 older stress-contribution days. Exact accounting of affected records. Keep private source
records unchanged. Coordinate with the public projection and historical event reconciliation. No historical database
writes until I receive and approve the final exact dry run."

WHAT IT TOUCHES. Reads (never writes) the inputs; writes, only under ``--apply``, the engine-owned attributes of existing
items in exactly two partitions — never a new item, never another partition (``assert_character_keys`` fails closed):

  written (``--apply`` only)  USER#<u>#SOURCE#character_sheet    DATE#<d>  the private sheet (its ``public`` attribute and
                                                                          every other non-engine attribute kept as stored)
                              USER#<u>#SOURCE#character_receipt  DATE#<d>  the private receipt (its ``public`` kept)
  read-only inputs            USER#<u>#SOURCE#engagement_state   DATE#<d>  presence (mood; the retired dark rules)
                              USER#<u>#SOURCE#habit_scores       DATE#<d>  vice streaks (cross-pillar effects)
                              USER#<u>#SOURCE#personal_baselines SNAPSHOT#LATEST  the personal targets overlay
                              USER#<u>#SOURCE#effect_fits        FIT#<d>   the latest effect fit (badges)
                              USER#<u>#SOURCE#challenges         CHALLENGE#*  the consumed-challenge XP cross-check
  never read or written       every wearable / nutrition / habit-log / journal / raw partition: a day is replayed from
                              the stored sheet's own component measurements (``recompute_character_private_replay``)

No event, ledger, milestone, badge, notification, feed, email or ``character_stats.json`` write exists in this file:
level events are REPORTED (kept / moved / removed / added) for the #6283 reconciliation, which owns their writes.

RUN (every path but --apply/--rollback --apply is read-only behind a proxy that refuses each write verb):
  python3 scripts/recompute_character_private.py --out DIR                       # DRY RUN: the ladder + plan.json,
                                                                                 #   per_date.csv, SUMMARY.md
  python3 scripts/recompute_character_private.py --out DIR --verify              # 0 planned writes, or exit 1
  python3 scripts/recompute_character_private.py --out DIR --apply --plan-in P [--phase sheets|receipts|all] [--limit N]
  python3 scripts/recompute_character_private.py --out DIR --rollback EXPORT [--apply]

``--apply`` re-derives the plan and refuses unless it reproduces ``--plan-in`` exactly, exports and verifies the
pre-image (local file + S3 ``backups/``) before the first write, and writes each row conditionally on its pre-image.
DIR must be outside the repository: every output carries real values.

THE PLAN FILE (``--plan-out``; schema ``character-private-recompute-plan-v1``) — what the public dry run reads instead of
the stored rows (``planned_sheets(path)`` returns them in the shape ``backfill_public_variant_cli.load_snapshot`` builds):

  plan_id            str, 16 hex — sha256 over [pk, sk, stored_digest, planned_compare_digest] of every row
  generated_at       ISO-8601 UTC; also the ``planned_at`` of every row's provenance
  method             {engine_version, config_version, config_hash, uninstrumented_pillars, tree{head, dirty}, old_tree_commit}
  window             {genesis, start, end, sheet_dates}
  partitions         {written: [pk, pk], read_only_inputs: {pk: sk pattern}, reads: {pk: n}}
  causes_legend      {cause: meaning}; ladder: [{step, cause, spec}] in order
  rows               one per stored item in the window, sheets (date order) then receipts (date order):
    pk, sk, date, partition       "character_sheet" | "character_receipt"
    action                        "write" | "unchanged" | "not_planned"
    stored_digest                 sha256 of the stored item's canonical typed JSON (the conditional write's fingerprint)
    stored_compare_digest         the same with ``recompute_provenance`` left out
    planned_compare_digest        the planned item's, ``recompute_provenance`` left out (equal to stored_compare_digest
                                  exactly when action is "unchanged")
    planned_digest                (action "write") sha256 of the full planned item, provenance included
    planned_item                  the FULL planned item, typed JSON: a number is {"$N": "<canonical decimal string>"},
                                  everything else is plain JSON. Every non-engine attribute (``public``, ``run_id``,
                                  ``phase``, ``computed_at``, ``habit_scores_status``, ``input_manifest``, sick-day
                                  fields) is the stored value; ``public`` is never changed by this tool
    changed_attributes            top-level attributes whose value differs from the stored item
    removed_attributes            engine-owned attributes the stored item has and the plan drops
    leaf_changes                  number of differing leaf paths
    attribute_causes              {attribute: [cause, ...]} — every changed attribute names >= 1 cause
    causes                        the row's causes (the union, plus ``recompute_provenance`` on a write)
  attribution        {date: {by_step: {cause: [attributes]}, attr_causes: {...}, leaf_counts: {cause: n}}}
  accounting         ladder_totals, net_attribute_causes, changed_then_restored, sheet_rows_to_write (reconciled)
  counts / stress_days / served_baseline / events / challenge_xp / preserved_non_engine_attributes / notes

CAUSES (ladder order): replay_residual (not a method change) · stress_days · journal_frequency · model_values ·
xp_debt · rest_decay · tree_switch_residual (control, must be 0) · relationships_exclusion · missing_data; stamps:
method_version_stamp · recompute_provenance. Mind's two removals are attributed separately (journal_frequency, then
model_values). A receipt row inherits its sheet's causes (it replays the sheet's transitions).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")

from common.constants import EXPERIMENT_PHASE_CURRENT, EXPERIMENT_START_DATE  # noqa: E402

REPLAY = os.path.join(ROOT, "scripts", "recompute_character_private_replay.py")
USER = os.environ["USER_ID"]
PFX = f"USER#{USER}#SOURCE#"
SHEET_PK, RECEIPT_PK = PFX + "character_sheet", PFX + "character_receipt"
WRITTEN_PARTITIONS = (SHEET_PK, RECEIPT_PK)
READ_ONLY_INPUTS = {
    PFX + "engagement_state": "DATE#<d>",
    PFX + "habit_scores": "DATE#<d>",
    PFX + "personal_baselines": "SNAPSHOT#LATEST",
    PFX + "effect_fits": "FIT#<latest>",
    PFX + "challenges": "CHALLENGE#*",
}
PLAN_SCHEMA = "character-private-recompute-plan-v1"
EXPORT_SCHEMA = "character-private-recompute-export-v1"
PROVENANCE = "recompute_provenance"
PROVENANCE_KIND = "historical_recompute"  # a nightly compute never writes this attribute
TOOL = "scripts/recompute_character_private.py"
OLD_TREE_COMMIT = "648d36d74d04f0a9554b6df6279c7fe2353ed9f9"  # engine 1.8.0 / config 1.6.0: #6299's base (#6283's tip)
BACKUP_PREFIX = "backups/character-private-recompute"
WRITE_VERBS = ("put_item", "update_item", "delete_item", "batch_writer", "batch_write_item", "transact_write_items")
S3_WRITE_VERBS = ("put_object", "delete_object", "delete_objects", "copy_object", "upload_file", "upload_fileobj")
SK_DATE = re.compile(r"^DATE#(\d{4}-\d{2}-\d{2})$")

# ── the method ladder: each step adds ONE methodological change to the one before it ─────────────────────────────────
# The cause a transition names is what the public side's combined summary attributes every change to (plan.json
# ``causes``). ``replay_residual`` and ``tree_switch_residual`` are not method changes: the first is what a replay of the
# STORED method does not reproduce (it must be explained, never attributed to a method step), the second is the control
# that the pre-amendment tree with the amended XP/dark rules equals the amended tree with the pre-amendment missing-data
# rules and Relationships still in the chain (it must be empty — see ``SUMMARY.md``).
_BASE_OLD = {"tree": "old", "rebuild": ["movement", "nutrition"], "loader": "legacy", "relationships": "verbatim"}
LADDER = (
    ("fidelity", "replay_residual", dict(_BASE_OLD)),
    ("stress", "stress_days", dict(_BASE_OLD, rebuild=["movement", "nutrition", "mind"])),
    ("jf", "journal_frequency", dict(_BASE_OLD, rebuild=["movement", "nutrition", "mind"], mind_drop=["journal_consistency"])),
    ("mv", "model_values", dict(_BASE_OLD, rebuild=["movement", "nutrition", "mind"], mind_config="new")),
    ("xp", "xp_debt", dict(_BASE_OLD, rebuild=["movement", "nutrition", "mind"], mind_config="new", patches=["xp_net"])),
    ("rest", "rest_decay", dict(_BASE_OLD, rebuild=["movement", "nutrition", "mind"], mind_config="new", patches=["xp_net", "no_neglect"])),
    (
        "switch",
        "tree_switch_residual",
        {
            "tree": "new",
            "rebuild": ["movement", "nutrition", "mind"],
            "loader": "legacy",
            "relationships": "verbatim",
            "patches": ["legacy_missing", "rel_in_chain"],
        },
    ),
    (
        "rel",
        "relationships_exclusion",
        {
            "tree": "new",
            "rebuild": ["movement", "nutrition", "mind"],
            "loader": "legacy",
            "relationships": "engine",
            "patches": ["legacy_missing"],
        },
    ),
    (
        "plan",
        "missing_data",
        {"tree": "new", "rebuild": ["movement", "nutrition", "mind"], "loader": "held_skip", "relationships": "engine"},
    ),
)
PLAN_SPEC = LADDER[-1][2]
METHOD_CAUSES = ("stress_days", "journal_frequency", "model_values", "xp_debt", "rest_decay", "relationships_exclusion", "missing_data")
STAMP_CAUSES = ("method_version_stamp", "recompute_provenance")
CAUSES_LEGEND = {
    "replay_residual": "stored value the stored method's own replay does not reproduce (not a method change)",
    "stress_days": "the stale evening-check-in stress contribution in Mind, removed by #5129 and never recomputed",
    "journal_frequency": "Mind's journal_consistency component removed (#6293)",
    "model_values": "Mind's model-counted values_alignment component removed (#6293)",
    "xp_debt": "no daily XP decay, no XP debt; the shield rolls with the measured verdict (#6293)",
    "rest_decay": "the #913 neglect atrophy and #959 dark down-streak persistence removed (#6293)",
    "tree_switch_residual": "control: pre-amendment tree + amended XP/dark rules vs amended tree + legacy missing data (must be 0)",
    "relationships_exclusion": "uninstrumented Relationships out of every aggregate, stored as its reason (#6293)",
    "missing_data": "only habits two-state; a no-evidence pillar-day held out of every aggregate; 0% completeness unknown (#6293)",
    "method_version_stamp": "engine_version / config_hash of the amended method",
    "recompute_provenance": "the recompute's own provenance attribute",
}
_IGNORE_STEP = ("computed_at", "engine_version")


class PlanGuardError(RuntimeError):
    """A key outside the character partitions, or a plan that does not reconcile: refuse, never write."""


class ConditionFailed(RuntimeError):
    """A conditional write's pre-image condition did not hold."""


# ── typed JSON, canonical form, digests ─────────────────────────────────────────────────────────────────────────────


def canon_number(d: Decimal) -> str:
    s = format(d.normalize(), "f")
    return "0" if s in ("-0", "0") else s


def to_typed(obj: Any) -> Any:
    """A DynamoDB item (Decimals) as JSON: a Decimal is {"$N": "<canonical number>"}; refuses a float or a "$N" map."""
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, Decimal):
        return {"$N": canon_number(obj)}
    if isinstance(obj, float):
        raise TypeError("a float in a DynamoDB item (Decimal only)")
    if isinstance(obj, int):
        return {"$N": str(obj)}
    if isinstance(obj, dict):
        if "$N" in obj:
            raise PlanGuardError("a stored map carries a '$N' key — the typed encoding would be ambiguous")
        return {k: to_typed(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_typed(v) for v in obj]
    if isinstance(obj, (set, frozenset, bytes, bytearray)):
        raise PlanGuardError(f"unsupported DynamoDB type {type(obj).__name__} in a character item")
    raise TypeError(f"unsupported type {type(obj).__name__}")


def from_typed(obj: Any) -> Any:
    if isinstance(obj, dict):
        if set(obj) == {"$N"}:
            return Decimal(obj["$N"])
        return {k: from_typed(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [from_typed(v) for v in obj]
    return obj


def canonical(typed: Any) -> str:
    return json.dumps(typed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(typed: Any, exclude: tuple = ()) -> str:
    body = {k: v for k, v in (typed or {}).items() if k not in exclude} if isinstance(typed, dict) else typed
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def as_float(typed: Any) -> Any:
    """Typed JSON as the compute reads a row (``d2f``: every number a float) — the shape the public backfill reads."""
    if isinstance(typed, dict):
        if set(typed) == {"$N"}:
            return float(typed["$N"])
        return {k: as_float(v) for k, v in typed.items()}
    if isinstance(typed, list):
        return [as_float(v) for v in typed]
    return typed


def typed_from_floats(record: dict, precision: Optional[int] = 4) -> Any:
    from common.numeric import floats_to_decimal

    return to_typed(floats_to_decimal(record, precision=precision))


def leaves(typed: Any, path: tuple = ()) -> dict:
    if isinstance(typed, dict) and set(typed) != {"$N"}:
        out: dict = {}
        if not typed and path:
            out[path] = "{}"
        for k, v in typed.items():
            out.update(leaves(v, path + (k,)))
        return out
    if isinstance(typed, list):
        out = {}
        if not typed and path:
            out[path] = "[]"
        for i, v in enumerate(typed):
            out.update(leaves(v, path + (f"[{i}]",)))
        return out
    return {path: canonical(typed)}


def changed_paths(a: Any, b: Any, ignore: tuple = ()) -> set:
    la, lb = leaves(a or {}), leaves(b or {})
    return {p for p in set(la) | set(lb) if p and p[0] not in ignore and la.get(p) != lb.get(p)}


# ── guards ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def refuse_in_repo(path: str) -> str:
    """The absolute output path, refused when it lies inside the repository (outputs carry real values)."""
    real = os.path.realpath(os.path.abspath(path))
    root = os.path.realpath(ROOT)
    if os.path.normcase(real).lower() == os.path.normcase(root).lower() or os.path.normcase(real).lower().startswith(
        os.path.normcase(root).lower() + os.sep
    ):
        raise PlanGuardError(f"refusing an output path inside the repository: {path}")
    return real


def assert_character_keys(rows: list, start: str, end: str) -> None:
    """Fail closed on any planned key outside the two character partitions or the window (the source-records guard)."""
    for r in rows:
        m = SK_DATE.match(str(r.get("sk", "")))
        if r.get("pk") not in WRITTEN_PARTITIONS or not m or not (start <= m.group(1) <= end):
            raise PlanGuardError(f"planned key outside the character partitions/window: {r.get('pk')} {r.get('sk')}")
        item = r.get("planned_item")
        if item is not None and (item.get("pk") != r["pk"] or item.get("sk") != r["sk"]):
            raise PlanGuardError(f"planned item key does not match its row: {r['pk']} {r['sk']}")


# ── storage adapters ────────────────────────────────────────────────────────────────────────────────────────────────


class ReadOnlyProxy:
    """Wraps a boto3 Table or S3 client; every write verb raises (the replay_6293 proxy, extended to S3)."""

    def __init__(self, inner: Any, verbs: tuple):
        self._inner, self._verbs = inner, verbs

    def __getattr__(self, name: str) -> Any:
        if name in self._verbs:
            raise RuntimeError(f"read-only: {name} refused")
        return getattr(self._inner, name)


def ddb_condition(cond: list) -> dict:
    """A condition spec as boto3 keywords. Clauses: ("exists", name) / ("not_exists", path) / ("eq", path, value)."""
    names: dict = {}
    values: dict = {}
    parts = []

    def ref(path: Any) -> str:
        segs = [path] if isinstance(path, str) else list(path)
        out = []
        for s in segs:
            key = f"#n{len(names)}"
            names[key] = s
            out.append(key)
        return ".".join(out)

    for clause in cond:
        kind = clause[0]
        if kind == "exists":
            parts.append(f"attribute_exists({ref(clause[1])})")
        elif kind == "not_exists":
            parts.append(f"attribute_not_exists({ref(clause[1])})")
        elif kind == "eq":
            key = f":v{len(values)}"
            values[key] = clause[2]
            parts.append(f"{ref(clause[1])} = {key}")
        else:
            raise ValueError(kind)
    out = {"ConditionExpression": " AND ".join(parts), "ExpressionAttributeNames": names}
    if values:
        out["ExpressionAttributeValues"] = values
    return out


class LiveStore:
    """DynamoDB + S3 through the minimal interface the tool uses. Read-only unless ``writable`` (``--apply`` paths)."""

    def __init__(self, table: Any, s3: Any, bucket: str, writable: bool = False):
        self.table = table if writable else ReadOnlyProxy(table, WRITE_VERBS)
        self.s3 = s3 if writable else ReadOnlyProxy(s3, S3_WRITE_VERBS)
        self.bucket = bucket
        self.reads: dict = {}

    def _note(self, pk: str) -> None:
        self.reads[pk] = self.reads.get(pk, 0) + 1

    def query(self, pk: str, lo: str, hi: str) -> list:
        from boto3.dynamodb.conditions import Key

        self._note(pk)
        out, kw = [], {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(lo, hi), "ConsistentRead": True}
        while True:
            resp = self.table.query(**kw)
            out += resp.get("Items", [])
            if "LastEvaluatedKey" not in resp:
                return out
            kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    def get(self, pk: str, sk: str) -> Optional[dict]:
        self._note(pk)
        return self.table.get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")

    def put(self, item: dict, cond: list) -> None:
        from botocore.exceptions import ClientError

        try:
            self.table.put_item(Item=item, **ddb_condition(cond))
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") == "ConditionalCheckFailedException":
                raise ConditionFailed(f"{item.get('pk')} {item.get('sk')}") from e
            raise

    def put_backup(self, key: str, body: bytes) -> None:
        self.s3.put_object(Bucket=self.bucket, Key=key, Body=body, IfNoneMatch="*", ContentType="application/json")

    def get_backup(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()


# ── reads ───────────────────────────────────────────────────────────────────────────────────────────────────────────


def shift(d: str, days: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=days)).isoformat()


def day_of(item: dict) -> str:
    return str(item.get("date") or str(item.get("sk", "")).replace("DATE#", ""))[:10]


def visible(item: Any) -> bool:
    """The compute's read semantics: no tombstone, the current phase or none (ADR-058)."""
    return isinstance(item, dict) and not item.get("tombstone") and item.get("phase", EXPERIMENT_PHASE_CURRENT) == EXPERIMENT_PHASE_CURRENT


def _dated(items: list, keep: Callable = lambda i: True) -> dict:
    return {day_of(i): i for i in items if keep(i) and SK_DATE.match(str(i.get("sk", "")))}


def load_snapshot(store: Any, start: str, end: Optional[str]) -> dict:
    """Every stored row the plan reads (raw Decimal items), read-only."""
    hi = f"DATE#{end or '9999-12-31'}~"
    lo = f"DATE#{shift(start, -28)}"
    sheets_all = _dated(store.query(SHEET_PK, lo, hi))
    sheets = {d: i for d, i in sheets_all.items() if visible(i) and d >= start}
    if end is None:
        end = max(sheets) if sheets else start
    sheets = {d: i for d, i in sheets.items() if d <= end}
    snap = {
        "start": start,
        "end": end,
        "sheets": sheets,
        "invisible_sheets": sorted(d for d, i in sheets_all.items() if not visible(i) and start <= d <= end),
        "receipts": {d: i for d, i in _dated(store.query(RECEIPT_PK, lo, hi), visible).items() if start <= d <= end},
        "engagement": _dated(store.query(PFX + "engagement_state", lo, hi), visible),
        "habit_scores": _dated(store.query(PFX + "habit_scores", lo, hi)),
        "baselines": store.get(PFX + "personal_baselines", "SNAPSHOT#LATEST"),
        "fits": [i for i in store.query(PFX + "effect_fits", "FIT#", "FIT#~")],
        "challenges": store.query(PFX + "challenges", "CHALLENGE#", "CHALLENGE#~"),
    }
    return snap


def child_inputs(snap: dict) -> dict:
    """The replay child's inputs file: the stored rows as the compute reads them (every number a float)."""
    cfg_items = {}
    if snap.get("baselines"):
        cfg_items[f"{PFX}personal_baselines|SNAPSHOT#LATEST"] = as_float(to_typed(snap["baselines"]))
    return {
        "user_id": USER,
        "user_prefix": PFX,
        "start": snap["start"],
        "end": snap["end"],
        "sheets": {d: as_float(to_typed(i)) for d, i in snap["sheets"].items()},
        "receipts": {d: as_float(to_typed(i)) for d, i in snap["receipts"].items()},
        "engagement": {d: as_float(to_typed(i)) for d, i in snap["engagement"].items()},
        "habit_scores": {d: as_float(to_typed(i)) for d, i in snap["habit_scores"].items()},
        "config_items": cfg_items,
        "fit_items": [as_float(to_typed(i)) for i in snap["fits"]],
    }


# ── the engine trees and the step runs ──────────────────────────────────────────────────────────────────────────────


def materialize_old_tree(workdir: str, commit: str = OLD_TREE_COMMIT) -> str:
    """The pre-amendment tree (lambdas/ + config/) from git, under ``workdir`` (outside the repo)."""
    dest = os.path.join(workdir, f"tree-{commit[:12]}")
    if os.path.isdir(os.path.join(dest, "lambdas")):
        return dest
    os.makedirs(dest, exist_ok=True)
    archive = subprocess.run(["git", "-C", ROOT, "archive", commit, "lambdas", "config"], check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", dest], input=archive, check=True)
    return dest


def tree_state() -> dict:
    head = subprocess.run(["git", "-C", ROOT, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(
        ["git", "-C", ROOT, "status", "--porcelain", "--", "lambdas", "config", "scripts"], capture_output=True, text=True
    )
    return {"head": head, "dirty": bool(dirty.stdout.strip())}


def child_env() -> dict:
    """The replay child cannot reach AWS: no credentials, no config, no metadata endpoint."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("AWS_") and k not in ("PYTHONPATH",)}
    env.update(
        {
            "AWS_CONFIG_FILE": os.devnull,
            "AWS_SHARED_CREDENTIALS_FILE": os.devnull,
            "AWS_EC2_METADATA_DISABLED": "true",
            "AWS_DEFAULT_REGION": "us-west-2",
            "S3_BUCKET": "unused-by-the-replay",
        }
    )
    return env


def run_step(spec: dict, inputs_path: str, workdir: str, trees: dict, name: str) -> dict:
    full = dict(spec, tree=trees[spec["tree"]], new_tree=trees["new"], old_tree=trees.get("old", trees["new"]))
    spec_path = os.path.join(workdir, f"spec_{name}.json")
    out_path = os.path.join(workdir, f"result_{name}.json")
    with open(spec_path, "w", encoding="utf-8") as fh:
        json.dump(full, fh)
    proc = subprocess.run(
        [sys.executable, REPLAY, "--spec", spec_path, "--inputs", inputs_path, "--result", out_path],
        env=child_env(),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"replay step {name} failed:\n{proc.stderr[-4000:]}")
    with open(out_path, encoding="utf-8") as fh:
        return json.load(fh)


def run_ladder(inputs: dict, workdir: str, trees: dict, ladder: tuple = LADDER, plan_spec: Optional[dict] = None) -> dict:
    """{step name: result} for every ladder step (the last one emits the planned items) + an independent plan run."""
    inputs_path = os.path.join(workdir, "inputs.json")
    with open(inputs_path, "w", encoding="utf-8") as fh:
        json.dump(inputs, fh)
    results = {}
    for i, (name, _cause, spec) in enumerate(ladder):
        s = dict(spec)
        if i == len(ladder) - 1:
            s["emit"] = "items"
        results[name] = run_step(s, inputs_path, workdir, trees, name)
    if plan_spec is not None:
        results["_plan_again"] = run_step(dict(plan_spec, emit="items"), inputs_path, workdir, trees, "plan_again")
    return results


def step_records(result: dict) -> dict:
    """{date: typed record as stored} for a step (records → precision-4 typed; an items step is typed already)."""
    if "sheet_attrs" in result:
        return result["sheet_attrs"]
    return {d: typed_from_floats(r) for d, r in result["records"].items()}


# ── attribution ─────────────────────────────────────────────────────────────────────────────────────────────────────


def _norm_step(rec: Optional[dict]) -> dict:
    r = dict(rec or {})
    if r.get("uninstrumented_pillars") == []:
        r.pop("uninstrumented_pillars")  # an empty list is the control's absence of the amended key
    return r


def attribute(stored_engine: dict, ladder_records: list) -> dict:
    """Per date and top-level attribute, the causes whose step changed it, from the cumulative ladder.

    ``stored_engine``: {date: typed engine-owned attributes as stored}; ``ladder_records``: [(cause, {date: typed})] in
    ladder order. Returns {date: {"by_step": {cause: [attrs]}, "attr_causes": {attr: [causes]}, "leaf_counts": {...}}}."""
    out: dict = {}
    dates = sorted(set(stored_engine) | {d for _c, recs in ladder_records for d in recs})
    for d in dates:
        prev = stored_engine.get(d)
        by_step: dict = {}
        attr_causes: dict = {}
        leaf_counts: dict = {}
        for cause, recs in ladder_records:
            cur = recs.get(d)
            paths = changed_paths(_norm_step(prev), _norm_step(cur), ignore=_IGNORE_STEP)
            if paths:
                attrs = sorted({p[0] for p in paths})
                by_step[cause] = attrs
                leaf_counts[cause] = len(paths)
                for a in attrs:
                    attr_causes.setdefault(a, []).append(cause)
            prev = cur
        out[d] = {"by_step": by_step, "attr_causes": attr_causes, "leaf_counts": leaf_counts}
    return out


# ── the plan ────────────────────────────────────────────────────────────────────────────────────────────────────────


def provenance(plan_id: str, method: dict, planned_at: str) -> dict:
    return {
        "kind": PROVENANCE_KIND,
        "tool": TOOL,
        "issue": 6311,
        "method": f"character-engine-{method['engine_version']}/config-{method['config_version']}",
        "plan_id": plan_id,
        "planned_at": planned_at,
    }


def build_rows(snap: dict, plan_result: dict, engine_keys: dict) -> list:
    """Every sheet and receipt row of the window: stored (typed), planned (typed), and the action.

    Engine-owned attributes are replaced by the plan's; every other stored attribute (``public``, ``run_id``,
    ``phase``, ``habit_scores_status``, the sick-day fields, the input manifest, pk/sk) is kept exactly as stored. An
    engine-owned attribute the stored row carries and the plan does not is removed. ``computed_at`` stays the stored
    one (the original timestamp)."""
    rows = []
    for d in sorted(snap["sheets"]):
        stored = to_typed(snap["sheets"][d])
        attrs = plan_result["sheet_attrs"].get(d)
        rows.append(_row(SHEET_PK, d, stored, attrs, engine_keys.get(d, set()) | set(attrs or {})))
    for d in sorted(snap["receipts"]):
        stored = to_typed(snap["receipts"][d])
        attrs = plan_result["receipt_attrs"].get(d)
        rows.append(_row(RECEIPT_PK, d, stored, attrs, set(attrs or {})))
    return rows


def _row(pk: str, d: str, stored: dict, attrs: Optional[dict], owned: set) -> dict:
    row: dict = {"pk": pk, "sk": f"DATE#{d}", "date": d, "partition": pk.split("#SOURCE#")[-1], "_stored": stored}
    row["stored_digest"] = digest(stored)
    row["stored_compare_digest"] = digest(stored, exclude=(PROVENANCE,))
    if attrs is None:
        row.update({"action": "not_planned", "planned_item": None, "changed_attributes": [], "removed_attributes": []})
        return row
    owned = set(owned) - {"pk", "sk", "computed_at", PROVENANCE}
    row["_owned"] = owned
    planned = {k: v for k, v in stored.items() if k not in owned and k != PROVENANCE}
    planned.update({k: v for k, v in attrs.items() if k not in ("computed_at",)})
    if "computed_at" in stored:
        planned["computed_at"] = stored["computed_at"]
    elif "computed_at" in attrs:
        planned["computed_at"] = attrs["computed_at"]
    planned["pk"], planned["sk"] = pk, f"DATE#{d}"
    row["planned_compare_digest"] = digest(planned, exclude=(PROVENANCE,))
    row["removed_attributes"] = sorted(k for k in owned if k in stored and k not in planned)
    row["changed_attributes"] = sorted({p[0] for p in changed_paths(stored, planned, ignore=(PROVENANCE,))})
    row["leaf_changes"] = len(changed_paths(stored, planned, ignore=(PROVENANCE,)))
    row["action"] = "write" if row["planned_compare_digest"] != row["stored_compare_digest"] else "unchanged"
    row["planned_item"] = planned
    return row


def finish_rows(rows: list, attribution: dict, method: dict, planned_at: str) -> str:
    """Name each row's causes, stamp the provenance on every row to write, and return the plan id."""
    for r in rows:
        a = attribution.get(r["date"], {})
        causes: dict = {}
        if r["pk"] == SHEET_PK:
            for attr in r["changed_attributes"]:
                cs = list(a.get("attr_causes", {}).get(attr, []))
                if attr == "engine_version":
                    cs.append("method_version_stamp")
                causes[attr] = sorted(set(cs), key=_cause_order)
        else:  # a receipt replays its sheet's transitions: its causes are the sheet's, plus the method stamp
            sheet_causes = sorted({c for cs in a.get("attr_causes", {}).values() for c in cs}, key=_cause_order)
            for attr in r["changed_attributes"]:
                causes[attr] = sorted(
                    set(sheet_causes + (["method_version_stamp"] if attr in ("engine_version", "config_hash") else [])), key=_cause_order
                )
        r["attribute_causes"] = causes
        r["causes"] = sorted({c for cs in causes.values() for c in cs}, key=_cause_order)
    plan_id = hashlib.sha256(
        canonical([[r["pk"], r["sk"], r["stored_digest"], r.get("planned_compare_digest")] for r in rows]).encode()
    ).hexdigest()[:16]
    prov = to_typed(provenance(plan_id, method, planned_at))
    for r in rows:
        if r["action"] == "write":
            r["planned_item"][PROVENANCE] = prov
            r["causes"] = sorted(set(r["causes"]) | {"recompute_provenance"}, key=_cause_order)
            r["planned_digest"] = digest(r["planned_item"])
    return plan_id


def _cause_order(c: str) -> int:
    order = ("replay_residual",) + METHOD_CAUSES[:5] + ("tree_switch_residual",) + METHOD_CAUSES[5:] + STAMP_CAUSES
    return order.index(c) if c in order else len(order)


def reconcile(rows: list, attribution: dict, ladder_records: list, plan_items: dict) -> dict:
    """The exact accounting. Raises PlanGuardError unless (1) the last ladder step IS the plan, row for row, (2) every
    changed sheet attribute names at least one cause, (3) the step totals add up to the per-row causes."""
    last_cause, last = ladder_records[-1]
    if any(canonical(_norm_step(last.get(d))) != canonical(_norm_step(plan_items.get(d))) for d in set(last) | set(plan_items)):
        raise PlanGuardError("the ladder's last step does not reproduce the plan")
    unexplained = [
        (r["date"], a) for r in rows if r["pk"] == SHEET_PK and r["action"] == "write" for a, cs in r["attribute_causes"].items() if not cs
    ]
    if unexplained:
        raise PlanGuardError(f"changed attributes with no cause: {unexplained[:10]}")
    totals = {c: {"dates": 0, "attributes": 0, "leaves": 0} for c, _r in ladder_records}
    for d, a in attribution.items():
        for c, attrs in a["by_step"].items():
            totals[c]["dates"] += 1
            totals[c]["attributes"] += len(attrs)
            totals[c]["leaves"] += a["leaf_counts"][c]
    sheet_rows = [r for r in rows if r["pk"] == SHEET_PK]
    net = {c: 0 for c in list(totals) + list(STAMP_CAUSES)}
    for r in sheet_rows:
        for cs in r["attribute_causes"].values():
            for c in cs:
                net[c] = net.get(c, 0) + 1
    gross_check = {c: sum(len(a["by_step"].get(c, [])) for a in attribution.values()) for c in totals}
    if any(gross_check[c] != totals[c]["attributes"] for c in totals):
        raise PlanGuardError("step totals do not add up")
    return {
        "ladder_totals": totals,
        "net_attribute_causes": net,
        "sheet_rows_to_write": sum(1 for r in sheet_rows if r["action"] == "write"),
        "sheet_rows_with_a_cause": sum(1 for r in sheet_rows if r["action"] == "write" and r["causes"]),
        "changed_then_restored": {
            c: sum(
                1
                for r in sheet_rows
                for attr in attribution.get(r["date"], {}).get("by_step", {}).get(c, [])
                if attr not in r["changed_attributes"]
            )
            for c in totals
        },
    }


# ── reports: served baseline, events, challenge XP, stress days ─────────────────────────────────────────────────────


def served_baselines(rows: list) -> dict:
    """Per date: what the public routes serve from the STORED row (its ``public`` block), and the proof that the
    planned private row serves the same (the private apply changes nothing a reader sees)."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    from backfill_public_variant_cli import served_today

    out = {}
    for r in rows:
        if r["pk"] != SHEET_PK or r["planned_item"] is None:
            continue
        before = served_today(as_float(r_stored(r)))
        after = served_today(as_float(r["planned_item"]))
        out[r["date"]] = {
            "served": (
                None
                if before is None
                else {"character_level": before.get("character_level"), "digest": digest(json.loads(json.dumps(before, default=str)))}
            ),
            "unchanged_by_private_apply": canonical(json.loads(json.dumps(before, default=str)))
            == canonical(json.loads(json.dumps(after, default=str))),
        }
    return out


def r_stored(r: dict) -> dict:
    """The row's stored pre-image (typed); kept in memory only — ``public_rows`` strips it (and ``_owned``) from the file."""
    return r["_stored"]


def public_rows(rows: list) -> list:
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in rows]


def _flat_events(by_date: dict) -> list:
    out = []
    for d in sorted(by_date):
        for ev in (by_date[d] or {}).get("level_events") or []:
            if not isinstance(ev, dict):
                continue
            who = str(ev.get("pillar") or "character").lower()
            tier = "tier" in str(ev.get("type"))
            new = ev.get("new_tier") if tier else _lv(ev.get("new_level"))
            old = ev.get("old_tier") if tier else _lv(ev.get("old_level"))
            out.append({"date": d, "who": who, "type": ev.get("type"), "old": old, "new": new, "key": [who, ev.get("type"), str(new)]})
    return out


def _lv(v: Any) -> Any:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return v
    return int(f) if f == int(f) else round(f, 4)


def event_report(stored_f: dict, planned_f: dict, ladder_f: list) -> dict:
    """KEPT / MOVED / REMOVED / ADDED for every private level event, the level badges' and level milestones' first
    crossing dates (the #6283 rules' rungs), and the events each ladder step emits. Reported only, never written."""
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import backfill_public_variant_events as EV
    from health import achievement_rules, milestone_ledger

    values = {d: {"character": _lv((r or {}).get("character_level"))} for d, r in planned_f.items()}
    for d, r in planned_f.items():
        for k, p in (r or {}).items():
            if k.startswith("pillar_") and isinstance(p, dict) and p.get("level") is not None:
                values[d][k[7:]] = _lv(p["level"])
    comp = EV.compare(_flat_events(stored_f), _flat_events(planned_f), values)
    badges = {r.id: r.threshold for r in achievement_rules.BADGE_RULES if r.signal == "current_level"}
    ladder_rungs = sorted(r.threshold for r in milestone_ledger.MILESTONE_RULES if r.signal == "character_level")

    def first(series: dict, n: Any) -> Optional[str]:
        return next(
            (
                d
                for d in sorted(series)
                if _lv((series[d] or {}).get("character_level")) is not None and float((series[d] or {}).get("character_level")) >= float(n)
            ),
            None,
        )

    crossings = {}
    for label, n in [*((f"badge:{k}", v) for k, v in badges.items()), *((f"milestone:level_{n}", n) for n in ladder_rungs)]:
        pair = [first(stored_f, n), first(planned_f, n)]
        status = "KEPT" if pair[0] == pair[1] else "MOVED" if pair[0] and pair[1] else "REMOVED" if pair[0] else "ADDED"
        crossings[label] = {"before": pair[0], "after": pair[1], "status": status}
    per_step = {}
    for cause, recs in ladder_f:
        evs = _flat_events(recs)
        per_step[cause] = {
            "level_up": sum(1 for e in evs if str(e["type"]).endswith("level_up")),
            "level_down": sum(1 for e in evs if str(e["type"]).endswith("level_down")),
        }
    return {"events": comp, "rung_crossings": crossings, "events_by_step": per_step, "writes_events": False}


def challenge_report(snap: dict, rows: list) -> dict:
    """Consumed challenge XP: the stored sheets' ``challenge_bonus_xp`` against the consumed challenges, and the proof
    that every planned sheet carries it unchanged (never recomputed away — the compute skips consumed challenges)."""
    domain_to_pillar = lambda_constant("CHALLENGE_DOMAIN_TO_PILLAR")
    expected: dict = {}
    for ch in snap.get("challenges") or []:
        if not ch.get("xp_consumed_at") or ch.get("status") not in ("completed", "failed"):
            continue
        xp = int(float(ch.get("character_xp_awarded", 0) or 0))
        if xp <= 0:
            continue
        d = str(ch.get("completed_at", ""))[:10]
        pillar = domain_to_pillar.get(ch.get("domain", "general"), "consistency")
        expected.setdefault(d, {})
        expected[d][pillar] = expected[d].get(pillar, 0) + xp
    out = {
        "dates_with_consumed_xp": 0,
        "stored_matches_consumed": 0,
        "stored_differs": [],
        "planned_carries_stored": True,
        "missing_rows": [],
    }
    by_date = {r["date"]: r for r in rows if r["pk"] == SHEET_PK}
    for d in sorted(set(expected) | {d for d, r in by_date.items() if as_float(r_stored(r)).get("challenge_bonus_xp")}):
        if not (snap["start"] <= d <= snap["end"]):
            continue
        out["dates_with_consumed_xp"] += 1
        r = by_date.get(d)
        if r is None:
            out["missing_rows"].append(d)
            continue
        s = {k: int(v) for k, v in (as_float(r_stored(r)).get("challenge_bonus_xp") or {}).items()}
        p = {k: int(v) for k, v in (as_float(r["planned_item"] or {}).get("challenge_bonus_xp") or {}).items()}
        if s == expected.get(d, {}):
            out["stored_matches_consumed"] += 1
        else:
            out["stored_differs"].append(d)
        if p != s:
            out["planned_carries_stored"] = False
    return out


def lambda_constant(name: str) -> Any:
    """A literal constant of the compute Lambda, read from its source (importing it would build boto3 resources)."""
    import ast

    path = os.path.join(ROOT, "lambdas", "compute", "character_sheet_lambda.py")
    for node in ast.parse(open(path, encoding="utf-8").read()).body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return ast.literal_eval(node.value)
    raise RuntimeError(f"{name} not found in the compute Lambda")


def stress_days(snap: dict) -> list:
    """Dates whose stored Mind carried a stress contribution (a stress score not held out) — the #5129 stale set."""
    out = []
    for d, s in sorted(snap["sheets"].items()):
        comp = (((s.get("pillar_mind") or {}).get("components") or {}).get("stress_management")) or {}
        if comp.get("score") is not None and not comp.get("held_out"):
            out.append(d)
    return out


# ── the dry run ─────────────────────────────────────────────────────────────────────────────────────────────────────


def dry_run(
    store: Any,
    out_dir: str,
    start: str = EXPERIMENT_START_DATE,
    end: Optional[str] = None,
    ladder: tuple = LADDER,
    trees: Optional[dict] = None,
    planned_at: Optional[str] = None,
) -> dict:
    planned_at = planned_at or datetime.now(timezone.utc).isoformat()
    snap = load_snapshot(store, start, end)
    os.makedirs(refuse_in_repo(out_dir), exist_ok=True)
    work = tempfile.mkdtemp(prefix="replay-", dir=out_dir)
    trees = trees or {"new": ROOT, "old": materialize_old_tree(work)}
    inputs = child_inputs(snap)
    results = run_ladder(inputs, work, trees, ladder, plan_spec=ladder[-1][2])
    plan_result = results[ladder[-1][0]]
    if canonical(plan_result["sheet_attrs"]) != canonical(results["_plan_again"]["sheet_attrs"]) or canonical(
        plan_result["receipt_attrs"]
    ) != canonical(results["_plan_again"]["receipt_attrs"]):
        raise PlanGuardError("the plan is not deterministic: two runs over the same inputs differ")
    ladder_records = [(cause, step_records(results[name])) for name, cause, _s in ladder]
    engine_keys = {d: {k for _c, recs in ladder_records for k in (recs.get(d) or {})} for d in snap["sheets"]}
    stored_engine = {d: {k: v for k, v in to_typed(i).items() if k in engine_keys.get(d, set())} for d, i in snap["sheets"].items()}
    attribution = attribute(stored_engine, ladder_records)
    rows = build_rows(snap, plan_result, engine_keys)
    method = dict(results[ladder[-1][0]]["meta"])
    plan_id = finish_rows(rows, attribution, method, planned_at)
    assert_character_keys(rows, snap["start"], snap["end"])
    accounting = reconcile(rows, attribution, ladder_records, plan_result["sheet_attrs"])
    stored_f = {d: as_float(to_typed(i)) for d, i in snap["sheets"].items()}
    planned_f = {r["date"]: as_float(r["planned_item"]) for r in rows if r["pk"] == SHEET_PK and r["planned_item"]}
    ladder_f = [(c, {d: as_float(v) for d, v in recs.items()}) for c, recs in ladder_records]
    sdays = stress_days(snap)
    stress_changed = sorted(d for d, a in attribution.items() if "stress_days" in a["by_step"])
    prev_recs = dict(ladder_records)[ladder[0][1]] if ladder[0][1] == "replay_residual" else {}
    stress_recs = dict(ladder_records).get("stress_days", {})
    stress_direct = sorted(
        d
        for d in stress_recs
        if canonical(((prev_recs.get(d) or {}).get("pillar_mind") or {}).get("raw_score"))
        != canonical(((stress_recs.get(d) or {}).get("pillar_mind") or {}).get("raw_score"))
    )
    plan = {
        "schema": PLAN_SCHEMA,
        "plan_id": plan_id,
        "generated_at": planned_at,
        "mode": "dry-run",
        "method": {**method, "config_hash": plan_result.get("config_hash"), "tree": tree_state(), "old_tree_commit": OLD_TREE_COMMIT},
        "window": {"genesis": EXPERIMENT_START_DATE, "start": snap["start"], "end": snap["end"], "sheet_dates": len(snap["sheets"])},
        "partitions": {
            "written": list(WRITTEN_PARTITIONS),
            "read_only_inputs": READ_ONLY_INPUTS,
            "reads": dict(getattr(store, "reads", {})),
        },
        "causes_legend": CAUSES_LEGEND,
        "ladder": [{"step": n, "cause": c, "spec": s} for n, c, s in ladder],
        "rows": rows,
        "attribution": attribution,
        "accounting": accounting,
        "counts": counts(rows, snap),
        "stress_days": {
            "stored_with_stress": sdays,
            "mind_raw_changed_by_stress_step": stress_direct,
            "same_set": sdays == stress_direct,
            "changed_only_through_the_chain": sorted(set(stress_changed) - set(stress_direct)),
        },
        "preserved_non_engine_attributes": preserved_attributes(rows),
        "receipts_self_replay_verified": sum(
            1 for r in rows if r["pk"] == RECEIPT_PK and r["planned_item"] and (r["planned_item"].get("replay_verified") is True)
        ),
        "served_baseline": served_baselines(rows),
        "events": event_report(stored_f, planned_f, ladder_f),
        "challenge_xp": challenge_report(snap, rows),
        "notes": {n: results[n].get("notes") for n, _c, _s in ladder[-1:]},
        "invisible_sheets_in_window": snap["invisible_sheets"],
    }
    return plan


def preserved_attributes(rows: list) -> dict:
    """{partition: {attribute: rows}} — the stored attributes the plan keeps exactly as stored (not engine-owned)."""
    out: dict = {}
    for r in rows:
        if r["planned_item"] is None:
            continue
        for k in sorted(set(r["_stored"]) - set(r["_owned"]) - {"pk", "sk"}):
            out.setdefault(r["partition"], {}).setdefault(k, 0)
            out[r["partition"]][k] += 1
    return out


def counts(rows: list, snap: dict) -> dict:
    out: dict = {}
    for pk in WRITTEN_PARTITIONS:
        rs = [r for r in rows if r["pk"] == pk]
        name = pk.split("#SOURCE#")[-1]
        out[name] = {
            "rows_read": len(rs),
            "rows_to_write": sum(1 for r in rs if r["action"] == "write"),
            "rows_unchanged": sum(1 for r in rs if r["action"] == "unchanged"),
            "rows_not_planned": sum(1 for r in rs if r["action"] == "not_planned"),
            "attributes_changed": sum(len(r["changed_attributes"]) for r in rs if r["action"] == "write"),
            "attributes_removed": sum(len(r["removed_attributes"]) for r in rs if r["action"] == "write"),
        }
    out["dates_affected"] = len({r["date"] for r in rows if r["action"] == "write"})
    return out


# ── outputs ─────────────────────────────────────────────────────────────────────────────────────────────────────────


def write_outputs(plan: dict, out_dir: str, plan_out: Optional[str] = None, preliminary: bool = False) -> dict:
    plan_path = refuse_in_repo(plan_out or os.path.join(out_dir, "plan.json"))
    with open(plan_path, "w", encoding="utf-8") as fh:
        json.dump(dict(plan, rows=public_rows(plan["rows"])), fh, indent=1, sort_keys=True)
    csv_path = os.path.join(out_dir, "per_date.csv")
    write_csv(csv_path, per_date_rows(plan))
    md_path = os.path.join(out_dir, "SUMMARY.md")
    with open(md_path, "w", encoding="utf-8") as fh:
        fh.write(summary_md(plan, preliminary=preliminary))
    return {"plan": plan_path, "csv": csv_path, "summary": md_path}


def per_date_rows(plan: dict) -> list:
    out = []
    by = {}
    for r in plan["rows"]:
        by.setdefault(r["date"], {})[r["partition"]] = r
    for d in sorted(by):
        s, rc = by[d].get("character_sheet"), by[d].get("character_receipt")
        row: dict = {"date": d}
        if s:
            st, pl = as_float(r_stored(s)), as_float(s["planned_item"] or {})
            row.update(
                {
                    "sheet_action": s["action"],
                    "sheet_attributes_changed": len(s["changed_attributes"]),
                    "sheet_leaves_changed": s.get("leaf_changes"),
                    "sheet_causes": "|".join(s["causes"]),
                    "character_level": f"{st.get('character_level')}->{pl.get('character_level')}",
                    "character_xp": f"{st.get('character_xp')}->{pl.get('character_xp')}",
                    "character_xp_debt": f"{st.get('character_xp_debt')}->{pl.get('character_xp_debt')}",
                }
            )
            for p in ("sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"):
                a, b = st.get(f"pillar_{p}") or {}, pl.get(f"pillar_{p}") or {}
                row[f"{p}_level"] = f"{a.get('level')}->{b.get('level')}"
                row[f"{p}_raw"] = f"{a.get('raw_score')}->{b.get('raw_score')}"
            for c in plan["ladder"]:
                row[f"step_{c['cause']}"] = "|".join(plan["attribution"].get(d, {}).get("by_step", {}).get(c["cause"], []))
        if rc:
            row.update({"receipt_action": rc["action"], "receipt_attributes_changed": len(rc["changed_attributes"])})
        out.append(row)
    return out


def write_csv(path: str, rows: list) -> None:
    keys = []
    for r in rows:
        keys += [k for k in r if k not in keys]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for r in rows:
            w.writerow(r)


PRELIMINARY_BANNER = (
    "**PRELIMINARY — not the dry run for approval.** The final dry run is the COMBINED one: the public projection's dry "
    "run (#6283) over this file's planned private rows, presented together. Nothing was written: every DynamoDB and S3 "
    "call went through a proxy that refuses each write verb."
)
OWNER_GATE = (
    "1. the public dry run over this plan (its --plan-in) · 2. the owner approves the exact combined plan ids · 3. the "
    "method PR (#6299) merges and deploys · 4. a re-run of this dry run on the deployed tree reproduces the approved plan "
    "id (--apply refuses otherwise) · 5. --apply --plan-in plan.json --phase sheets, then --phase receipts · 6. the public "
    "apply · 7. both --verify runs report 0 planned writes"
)


def summary_md(plan: dict, preliminary: bool = False) -> str:
    c, a, ev = plan["counts"], plan["accounting"], plan["events"]
    lines = [
        f"# Private character recompute — dry run ({plan['plan_id']})",
        "",
        *([PRELIMINARY_BANNER, ""] if preliminary else []),
        f"Generated {plan['generated_at']} · engine {plan['method']['engine_version']} · config {plan['method']['config_version']} · "
        f"tree {plan['method']['tree']['head'][:12]}{' (dirty)' if plan['method']['tree']['dirty'] else ''} · window "
        f"{plan['window']['start']}..{plan['window']['end']} ({plan['window']['sheet_dates']} stored sheets)",
        "",
        "## Rows",
    ]
    for name in ("character_sheet", "character_receipt"):
        x = c[name]
        lines.append(
            f"- {name}: read {x['rows_read']} · to write {x['rows_to_write']} · unchanged {x['rows_unchanged']} · not planned "
            f"{x['rows_not_planned']} · attributes changed {x['attributes_changed']} · removed {x['attributes_removed']}"
        )
    lines += [f"- dates affected: {c['dates_affected']}", "", "## Ladder (cumulative; dates / attributes / leaves changed by each step)"]
    for step in plan["ladder"]:
        t = a["ladder_totals"][step["cause"]]
        lines.append(
            f"- {step['cause']}: {t['dates']} / {t['attributes']} / {t['leaves']} (changed then restored later: {a['changed_then_restored'][step['cause']]})"
        )
    sd = plan["stress_days"]
    lines += [
        "",
        f"## Stress days: stored with a counted stress score {len(sd['stored_with_stress'])}; Mind raw changed by the stress "
        f"step {len(sd['mind_raw_changed_by_stress_step'])} (same set: {sd['same_set']}); later dates moved only through the "
        f"chain {len(sd['changed_only_through_the_chain'])}",
        f"## Receipts whose planned self-replay verifies: {plan['receipts_self_replay_verified']} of {c['character_receipt']['rows_read']}",
        "",
        "## Events (reported only; the #6283 reconciliation writes them)",
    ]
    for who, t in sorted(ev["events"]["totals"].items()):
        lines.append(f"- {who}: KEPT {t['KEPT']} · MOVED {t['MOVED']} · REMOVED {t['REMOVED']} · ADDED {t['ADDED']}")
    lines.append(
        "- events by step: " + "; ".join(f"{k} up {v['level_up']} down {v['level_down']}" for k, v in ev["events_by_step"].items())
    )
    ch = plan["challenge_xp"]
    served = plan["served_baseline"]
    lines += [
        "",
        f"## Consumed challenge XP: {ch['dates_with_consumed_xp']} dates; stored matches consumed on {ch['stored_matches_consumed']}; "
        f"planned carries stored: {ch['planned_carries_stored']}",
        f"## Served baseline unchanged by the private apply on {sum(1 for v in served.values() if v['unchanged_by_private_apply'])} of {len(served)} dates",
        "",
        "## Controls",
        f"- tree_switch_residual (must be 0): {a['ladder_totals'].get('tree_switch_residual', {}).get('attributes', 'n/a')} attributes",
        "- replay_residual: what the stored method's own replay does not reproduce — never a method change; read its "
        "attributes in plan.json `attribution` before approving",
        f"- method tree {'DIRTY: re-run from the committed, deployed tree' if plan['method']['tree']['dirty'] else 'clean'}",
        "",
        "## Before any write (owner gate)",
        OWNER_GATE,
        "",
    ]
    return "\n".join(lines)


def planned_sheets(plan_path: str) -> dict:
    """{date: planned sheet item, every number a float} from a plan file — the stored-sheets shape the public backfill
    reads (``backfill_public_variant_cli.load_snapshot``'s ``sheets``). An unchanged row's planned item is the stored
    item; a "not_planned" row is omitted. The file is integrity-checked first (``load_plan``)."""
    plan = load_plan(plan_path)
    return {r["date"]: as_float(r["planned_item"]) for r in plan["rows"] if r["pk"] == SHEET_PK and r["planned_item"] is not None}


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


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def live_store(writable: bool) -> LiveStore:
    import boto3

    region = os.environ["AWS_DEFAULT_REGION"]
    table = boto3.resource("dynamodb", region_name=region).Table(os.environ["TABLE_NAME"])
    return LiveStore(table, boto3.client("s3", region_name=region), os.environ["S3_BUCKET"], writable=writable)


def main(argv: list) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="output directory OUTSIDE the repo (outputs carry real values)")
    ap.add_argument("--plan-out", help="the plan file (default OUT/plan.json); read by the public dry run (--plan-in there)")
    ap.add_argument("--start", default=EXPERIMENT_START_DATE)
    ap.add_argument("--end", help="last date (default: the latest stored sheet)")
    ap.add_argument("--verify", action="store_true", help="zero-write post-verification: exit 1 unless 0 planned writes")
    ap.add_argument("--apply", action="store_true", help="WRITE (owner act): with --plan-in, or with --rollback")
    ap.add_argument("--plan-in", help="the approved plan file --apply writes")
    ap.add_argument("--phase", choices=sorted(PHASES), default="all")
    ap.add_argument("--from-date", help="resume cursor: plan rows on or after this date")
    ap.add_argument("--limit", type=int, help="write at most N rows this run (resumable)")
    ap.add_argument("--rollback", help="an export file: restore its pre-images (dry run unless --apply)")
    ap.add_argument("--preliminary", action="store_true", help="head the summary as preliminary (not the dry run for approval)")
    args = ap.parse_args(argv)
    out_dir = refuse_in_repo(args.out)
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    if args.rollback:
        result = rollback(live_store(writable=args.apply), args.rollback, apply=args.apply)
        with open(os.path.join(out_dir, f"rollback_{now.replace(':', '')}.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
        ok = not result["refused"] and (not args.apply or not result["verified"]["mismatches"])
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}, indent=1, default=str))
        return 0 if ok else 2
    if args.verify:
        result = verify(live_store(writable=False), out_dir, args.start, args.end)
        print(json.dumps({"rows": result["rows"], "planned_writes": result["planned_writes"]}))
        return 0 if result["planned_writes"] == 0 else 1
    if args.apply:
        if not args.plan_in:
            ap.error("--apply needs --plan-in (the approved plan)")
        plan = load_plan(args.plan_in)
        fresh = dry_run(
            live_store(writable=False), out_dir, plan["window"]["start"], plan["window"]["end"], planned_at=plan["generated_at"]
        )
        if fresh["plan_id"] != plan["plan_id"] or any(
            a.get("planned_digest") != b.get("planned_digest") for a, b in zip(fresh["rows"], plan["rows"])
        ):
            print("REFUSED: the plan no longer reproduces from the stored rows — re-run the dry run and re-approve", file=sys.stderr)
            return 3
        later = [d for d in load_snapshot(live_store(writable=False), plan["window"]["end"], None)["sheets"] if d > plan["window"]["end"]]
        if later:
            print(f"REFUSED: stored sheets exist after the plan's window ({later[:3]}…) — re-plan to include them", file=sys.stderr)
            return 3
        result = apply_plan(live_store(writable=True), plan, out_dir, args.phase, now, args.from_date, args.limit)
        print(json.dumps({"written": len(result["written"]), "aborted": len(result["aborted"]), "export": result["export"]}, indent=1))
        return 0 if not result["aborted"] and all(w["verified"] for w in result["written"]) else 2
    plan = dry_run(live_store(writable=False), out_dir, args.start, args.end, planned_at=now)
    paths = write_outputs(plan, out_dir, args.plan_out, preliminary=args.preliminary)
    print(json.dumps({"plan_id": plan["plan_id"], "counts": plan["counts"], **paths}, indent=1, default=str))
    print("DRY RUN — nothing written.")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, os.path.join(ROOT, "deploy", "lib"))
    from prod_write_guard import install_prod_write_guard

    install_prod_write_guard()
    sys.exit(main(sys.argv[1:]))
