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
  read-only, the three raw-   through the compute Lambda's own ``assemble_data`` (``recompute_character_private_raw``):
  dependent final steps only  whoop, macrofactor, apple_health, notion (DATE#<d>#journal#*), habit_scores, flourishing,
                              evening_checkin, engagement_state (DATE#<d>, STATE#current), strava, hevy
                              (DATE#<d>#WORKOUT#*), todoist, withings, labs, habitify, sick_days, travel,
                              personal_baselines, and the ADR-097 GSI2 READING_SESSION index. Only each switch's ON and
                              OFF output per date is kept (no raw row); the live run records every partition read
                              (``partitions.raw_reads``)
  never written               every source partition. A day is replayed from the stored sheet's own component
                              measurements (``recompute_character_private_replay``); the three raw-dependent steps
                              (planned_rest, lab_ageing, rest_day_completeness) apply only the on/off DIFFERENCE of the
                              engine's own function on the SAME assembled inputs to that stored-derived chain, never a raw
                              value (a raw recompute does not reproduce the stored rows: late data, earlier rule changes)

No event, ledger, milestone, badge, notification, feed, email or ``character_stats.json`` write exists in this file:
level events are REPORTED (kept / moved / removed / added) for the #6283 reconciliation, which owns their writes.

RUN (every path but --apply/--rollback --apply is read-only behind a proxy that refuses each write verb):
  python3 scripts/recompute_character_private.py --out DIR                       # DRY RUN: the ladder + plan.json,
                                                                                 #   per_date.csv, SUMMARY.md
  python3 scripts/recompute_character_private.py --out DIR --verify              # 0 planned writes, or exit 1
  python3 scripts/recompute_character_private.py --out DIR --preflight --plan-in P         # read-only backup preconditions
  python3 scripts/recompute_character_private.py --out DIR --apply --plan-in P --approved-plan-id ID [--phase ...] [--limit N]
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

LADDER STATES (``ladder_states`` in the plan; additive, outside the plan id; read with
``recompute_character_private_apply.ladder_states(path)``) — the chain's values AFTER each step, cumulatively:

  {cause: {date: {"character_level": float|None, "character_xp": float|None, "composite": float|None,
                  "pillars": {pillar: {"raw_score": float|None, "level": float|None}},
                  "events": [{"who", "type", "old", "new"}]}}}

  keyed by every cause in ``ladder`` order (replay_residual … missing_data); the last cause's states are the plan's
  planned sheets. ``composite`` is the mean raw score over the pillars that carry one and are not not-instrumented
  (``/api/character``'s composite rule); a pillar with no number (Relationships under the amended method) is
  {"raw_score": None, "level": None}. The first step at which a value differs from the previous step's (or, for
  replay_residual, from the stored row) is the step that produced the change.

PLANNED STATES (``planned_states``; additive, outside the plan id; ``recompute_character_private_apply.planned_states``)
— {date: state} computed FROM THE PLANNED ITEMS in the same state shape. The dry run refuses unless the last ladder step's
states equal it on every field of every date, composite included (``check_final_state``).

APPROVAL. ``--apply`` refuses (exit 4, before any backup or write) unless ``--approved-plan-id`` equals the plan file's
id AND the id re-derived from the live rows. ``--preflight --plan-in P`` is read-only: ListObjectsV2 shows no backup
exists yet under this plan id's prefix, GetBucketVersioning shows the bucket versioned; the conditional put itself
cannot be verified without a write.

STORED STATES (``stored_states``; additive, outside the plan id; ``recompute_character_private_apply.stored_states``)
— {date: state} of the STORED rows in the same state shape: the baseline the first step (replay_residual) is compared
against.

CAUSES (ladder order): replay_residual (not a method change) · stress_days · journal_frequency · model_values ·
xp_debt · rest_decay · tree_switch_residual (control, must be 0) · relationships_exclusion · missing_data ·
final_switch_residual (control: the final tree with its four switches off vs the amended tree, must be 0) ·
planned_rest · lab_ageing · rest_day_completeness · mood_label_presence; stamps: method_version_stamp ·
recompute_provenance. Mind's two removals are attributed separately (journal_frequency, then model_values). A receipt
row inherits its sheet's causes (it replays the sheet's transitions). Both controls are asserted 0 on every run.

PLANNED REST AND THE PUBLIC RESTORE. A planned sheet whose Movement window was prorated carries
``pillar_movement.components._planned_rest`` = {days, pre_rest_raw, pre_rest_raw_unblended, pre_rest_details} exactly
as ``compute_movement_raw`` records it, the pre-rest values being the un-prorated stored-derived Movement. So
``character_public.without_private_modifiers`` restores the public day from ``planned_sheets()`` with no other input.

AN INTERRUPTED OR PHASED APPLY. A plan has ONE pre-image: ``backups/character-private-recompute/<plan_id>/export.json``
(and ``OUT/export_<plan_id>.json``), covering every row of every phase, written once with IfNoneMatch before the first
write. A later ``--apply`` of the same plan (the receipts phase after the sheets phase, or a re-run after an
interruption) never takes or writes a second pre-image: it re-reads and verifies that object, refuses a local copy that
differs, and re-derives the approval from the pre-image (``PreimageOverlay``: a row holding this plan's value reads as its
exported pre-image), so the approved plan id still reproduces. It then COMPLETES idempotently — a row holding its planned
value is skipped, a row holding its pre-image is written conditionally — when every exported row is exactly one of the
two. If any exported row is neither (something else wrote it since), it writes nothing and STOPS, directing to
``--rollback OUT/export_<plan_id>.json --apply``. Completing is safe because the state is proven to be the plan's own
partial state against the one verified pre-image; anything else is a state the plan was not approved for.
"""

from __future__ import annotations

import argparse
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
AMENDED_TREE_COMMIT = "dc199e9234f54097db158f971438f1600833f38e"  # #6299 as amended, before the four final switches
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
_BASE_AMENDED = {"tree": "new", "rebuild": ["movement", "nutrition", "mind"], "loader": "held_skip", "relationships": "engine"}
_SWITCHES = ("PLANNED_REST_PRORATES", "LAB_AGE_TAPERS_WEIGHT", "REST_DAY_COMPLETENESS", "MOOD_NOT_OBSERVED")
_EFFECTS = ("planned_rest", "lab_ageing", "rest_day_completeness")
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
            "tree": "amended",
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
            "tree": "amended",
            "rebuild": ["movement", "nutrition", "mind"],
            "loader": "legacy",
            "relationships": "engine",
            "patches": ["legacy_missing"],
        },
    ),
    ("md", "missing_data", dict(_BASE_AMENDED, tree="amended")),
    # the final tree (#6299 head) from here: a control with its four switches OFF (must equal the amended tree's last step),
    # then each switch ON in turn; the three raw-dependent ones apply their on/off difference (raw_effects)
    ("final0", "final_switch_residual", dict(_BASE_AMENDED, switches=[])),
    ("prest", "planned_rest", dict(_BASE_AMENDED, switches=_SWITCHES[:1], effects=["planned_rest"])),
    ("lab", "lab_ageing", dict(_BASE_AMENDED, switches=_SWITCHES[:2], effects=["planned_rest", "lab_ageing"])),
    ("comp", "rest_day_completeness", dict(_BASE_AMENDED, switches=_SWITCHES[:3], effects=list(_EFFECTS))),
    ("plan", "mood_label_presence", dict(_BASE_AMENDED, switches=list(_SWITCHES), effects=list(_EFFECTS))),
)
PLAN_SPEC = LADDER[-1][2]
METHOD_CAUSES = (
    "stress_days",
    "journal_frequency",
    "model_values",
    "xp_debt",
    "rest_decay",
    "relationships_exclusion",
    "missing_data",
    "planned_rest",
    "lab_ageing",
    "rest_day_completeness",
    "mood_label_presence",
)
CONTROL_CAUSES = ("tree_switch_residual", "final_switch_residual")
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
    "final_switch_residual": "control: the final tree with its four #6293 switches off vs the amended tree (must be 0)",
    "planned_rest": "a recorded planned pause (sick / travel) prorates Movement's 7-day window targets (PLANNED_REST_PRORATES)",
    "lab_ageing": "an ageing lab result loses evidence weight, never score (LAB_AGE_TAPERS_WEIGHT)",
    "rest_day_completeness": "a day with no activity anywhere does not expect a Strava row (REST_DAY_COMPLETENESS)",
    "mood_label_presence": "logging silence reads 'unavailable', never 'dormant' or a presence-driven 'fading' (MOOD_NOT_OBSERVED)",
    "method_version_stamp": "engine_version / config_hash of the amended method",
    "recompute_provenance": "the recompute's own provenance attribute",
}
STRESS_DAY_DEFINITION = (
    "a stored sheet whose Mind counts the evening-check-in stress score (stress_management carries a score and no "
    "held_out flag), which today's method holds out (#5129) — every such row, a sick-day freeze copy included"
)
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

    def list_backups(self, prefix: str) -> list:
        """Keys under ``prefix`` (ListObjectsV2, a read)."""
        resp = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=1000)
        return [o["Key"] for o in resp.get("Contents", [])]

    def bucket_versioning(self) -> Optional[str]:
        """The bucket's versioning status (GetBucketVersioning, a read): "Enabled", "Suspended" or None."""
        return self.s3.get_bucket_versioning(Bucket=self.bucket).get("Status")

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


def collect_raw_effects(store: Any, snap: dict) -> dict:
    """The three raw-dependent steps' on/off outputs per date (``recompute_character_private_raw``; LIVE, read-only)."""
    import recompute_character_private_raw as RAW

    return RAW.collect_raw_effects(store, snap)


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
        "raw_effects": (snap.get("raw_effects") or {}).get("effects") or {},
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
    full = dict(
        spec,
        tree=trees.get(spec["tree"], trees["new"]),
        new_tree=trees.get("amended", trees["new"]),  # the XP / Mind grafts come from the amended method's source
        old_tree=trees.get("old", trees["new"]),
    )
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
    order = ("replay_residual",) + METHOD_CAUSES[:5] + ("tree_switch_residual",) + METHOD_CAUSES[5:7]
    order += ("final_switch_residual",) + METHOD_CAUSES[7:] + STAMP_CAUSES
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


# ── the dry run ─────────────────────────────────────────────────────────────────────────────────────────────────────


def dry_run(
    store: Any,
    out_dir: str,
    start: str = EXPERIMENT_START_DATE,
    end: Optional[str] = None,
    ladder: tuple = LADDER,
    trees: Optional[dict] = None,
    planned_at: Optional[str] = None,
    raw_effects: Optional[dict] = None,
) -> dict:
    import recompute_character_private_report as R  # the reports (module-size split, #1665)

    planned_at = planned_at or datetime.now(timezone.utc).isoformat()
    snap = load_snapshot(store, start, end)
    os.makedirs(refuse_in_repo(out_dir), exist_ok=True)
    work = tempfile.mkdtemp(prefix="replay-", dir=out_dir)
    trees = trees or {"new": ROOT, "old": materialize_old_tree(work), "amended": materialize_old_tree(work, AMENDED_TREE_COMMIT)}
    uses_effects = any((spec.get("effects") for _n, _c, spec in ladder))
    if raw_effects is not None:  # supplied by the caller (tests)
        snap["raw_effects"] = dict(raw_effects, source=raw_effects.get("source", "caller-supplied"))
    else:
        snap["raw_effects"] = collect_raw_effects(store, snap) if uses_effects else {"effects": {}, "reads": {}}
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
    for control in CONTROL_CAUSES:  # each control must change nothing, on any date
        if accounting["ladder_totals"].get(control, {}).get("attributes", 0):
            raise PlanGuardError(f"control {control} is not 0: {accounting['ladder_totals'][control]}")
    stored_f = {d: as_float(to_typed(i)) for d, i in snap["sheets"].items()}
    planned_f = {r["date"]: as_float(r["planned_item"]) for r in rows if r["pk"] == SHEET_PK and r["planned_item"]}
    ladder_f = [(c, {d: as_float(v) for d, v in recs.items()}) for c, recs in ladder_records]
    sdays = R.stress_days(snap)
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
        "method": {
            **method,
            "config_hash": plan_result.get("config_hash"),
            "tree": tree_state(),
            "old_tree_commit": OLD_TREE_COMMIT,
            "amended_tree_commit": AMENDED_TREE_COMMIT,
        },
        "window": {"genesis": EXPERIMENT_START_DATE, "start": snap["start"], "end": snap["end"], "sheet_dates": len(snap["sheets"])},
        "partitions": {
            "written": list(WRITTEN_PARTITIONS),
            "read_only_inputs": READ_ONLY_INPUTS,
            "reads": dict(getattr(store, "reads", {})),
            "raw_read_only_inputs": list(R.RAW_READ_PARTITIONS),
            "raw_reads": dict(snap["raw_effects"].get("reads") or {}),
        },
        "causes_legend": CAUSES_LEGEND,
        "ladder": [{"step": n, "cause": c, "spec": s} for n, c, s in ladder],
        "rows": rows,
        "attribution": attribution,
        "ladder_states": R.ladder_states(ladder_f),
        "stored_states": {d: R.chain_state(r) for d, r in sorted(stored_f.items())},
        # the planned items' own state, computed from the planned items (not copied from the ladder) — cross-checked below
        "planned_states": {d: R.chain_state(r) for d, r in sorted(planned_f.items())},
        "accounting": accounting,
        "counts": R.counts(rows, snap),
        "stress_days": {
            "stored_with_stress": sdays,
            "mind_raw_changed_by_stress_step": stress_direct,
            "same_set": sdays == stress_direct,
            "changed_only_through_the_chain": sorted(set(stress_changed) - set(stress_direct)),
            # a sick-day freeze row copies the previous day's Mind verbatim: it carries the stale contribution too (and
            # is rewritten from the recomputed previous day), but it is not an independently computed day
            "sick_day_frozen_copies": sorted(d for d in sdays if snap["sheets"][d].get("sick_day")),
            "computed_days": sorted(d for d in sdays if not snap["sheets"][d].get("sick_day")),
            "definition": STRESS_DAY_DEFINITION,
        },
        "preserved_non_engine_attributes": R.preserved_attributes(rows),
        "receipts_self_replay_verified": sum(
            1 for r in rows if r["pk"] == RECEIPT_PK and r["planned_item"] and (r["planned_item"].get("replay_verified") is True)
        ),
        "served_baseline": R.served_baselines(rows),
        "events": R.event_report(stored_f, planned_f, ladder_f),
        "challenge_xp": R.challenge_report(snap, rows),
        "notes": {n: results[n].get("notes") for n, _c, _s in ladder[-1:]},
        "invisible_sheets_in_window": snap["invisible_sheets"],
        "raw_effects": {
            "effects": snap["raw_effects"].get("effects") or {},
            "dates_with_on_off_difference": R.changed_effects(snap["raw_effects"].get("effects") or {}),
            "applied_by_step": {c: results[n].get("effects_applied") or {} for n, c, _s in ladder},
            "source": snap["raw_effects"].get("source"),
        },
        "mood_labels": R.mood_report(stored_f, planned_f, ladder_f),
    }
    R.check_final_state(plan["ladder_states"], plan["planned_states"])  # every field, composite included; else refuse
    plan["stress_days"]["accounting"] = R.check_stress_days(plan["stress_days"], rows)  # distinct, 46 + 1, all written
    return plan


def write_outputs(plan: dict, out_dir: str, plan_out: Optional[str] = None, preliminary: bool = False) -> dict:
    """plan.json (``--plan-out``), per_date.csv and SUMMARY.md — ``recompute_character_private_report.write_outputs``."""
    import recompute_character_private_report as R

    return R.write_outputs(plan, out_dir, plan_out, preliminary=preliminary)


# ── CLI ─────────────────────────────────────────────────────────────────────────────────────────────────────────────


def live_store(writable: bool) -> LiveStore:
    import boto3

    region = os.environ["AWS_DEFAULT_REGION"]
    table = boto3.resource("dynamodb", region_name=region).Table(os.environ["TABLE_NAME"])
    return LiveStore(table, boto3.client("s3", region_name=region), os.environ["S3_BUCKET"], writable=writable)


def main(argv: list) -> int:
    import recompute_character_private_apply as A  # the write half (module-size split, #1665)

    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", required=True, help="output directory OUTSIDE the repo (outputs carry real values)")
    ap.add_argument("--plan-out", help="the plan file (default OUT/plan.json); read by the public dry run (--plan-in there)")
    ap.add_argument("--start", default=EXPERIMENT_START_DATE)
    ap.add_argument("--end", help="last date (default: the latest stored sheet)")
    ap.add_argument("--verify", action="store_true", help="zero-write post-verification: exit 1 unless 0 planned writes")
    ap.add_argument("--apply", action="store_true", help="WRITE (owner act): with --plan-in, or with --rollback")
    ap.add_argument("--plan-in", help="the approved plan file --apply writes")
    ap.add_argument("--phase", choices=sorted(A.PHASES), default="all")
    ap.add_argument("--from-date", help="resume cursor: plan rows on or after this date")
    ap.add_argument("--limit", type=int, help="write at most N rows this run (resumable)")
    ap.add_argument("--rollback", help="an export file: restore its pre-images (dry run unless --apply)")
    ap.add_argument("--preliminary", action="store_true", help="head the summary as preliminary (not the dry run for approval)")
    ap.add_argument("--approved-plan-id", help="--apply only: the plan id the owner approved (must equal the file's and the live one)")
    ap.add_argument("--preflight", action="store_true", help="read-only: with --plan-in, check the backup preconditions")
    args = ap.parse_args(argv)
    out_dir = refuse_in_repo(args.out)
    os.makedirs(out_dir, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()

    if args.rollback:
        result = A.rollback(live_store(writable=args.apply), args.rollback, apply=args.apply)
        with open(os.path.join(out_dir, f"rollback_{now.replace(':', '')}.json"), "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=1)
        ok = not result["refused"] and (not args.apply or not result["verified"]["mismatches"])
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in result.items()}, indent=1, default=str))
        return 0 if ok else 2
    if args.verify:
        result = A.verify(live_store(writable=False), out_dir, args.start, args.end)
        print(json.dumps({"rows": result["rows"], "planned_writes": result["planned_writes"]}))
        return 0 if result["planned_writes"] == 0 else 1
    if args.preflight:
        if not args.plan_in:
            ap.error("--preflight needs --plan-in")
        result = A.preflight(live_store(writable=False), A.load_plan(args.plan_in))
        print(json.dumps(result, indent=1))
        return 0 if result["ok"] else 1
    if args.apply:
        if not args.plan_in:
            ap.error("--apply needs --plan-in (the approved plan)")
        plan = A.load_plan(args.plan_in)
        refusal = A.check_approval(args.approved_plan_id, plan)  # before any read-back, backup or write
        if refusal:
            print(f"REFUSED: {refusal}", file=sys.stderr)
            return 4
        ro = live_store(writable=False)
        # a phased or interrupted apply: the approval is re-derived from the pre-image the apply started from
        overlay = A.PreimageOverlay(ro, A.existing_preimages(ro, plan))
        fresh = dry_run(overlay, out_dir, plan["window"]["start"], plan["window"]["end"], planned_at=plan["generated_at"])
        refusal = A.check_approval(args.approved_plan_id, plan, fresh["plan_id"])
        if refusal:
            print(f"REFUSED: {refusal}", file=sys.stderr)
            return 4
        if fresh["plan_id"] != plan["plan_id"] or any(
            a.get("planned_digest") != b.get("planned_digest") for a, b in zip(fresh["rows"], plan["rows"])
        ):
            print("REFUSED: the plan no longer reproduces from the stored rows — re-run the dry run and re-approve", file=sys.stderr)
            return 3
        later = [d for d in load_snapshot(live_store(writable=False), plan["window"]["end"], None)["sheets"] if d > plan["window"]["end"]]
        if later:
            print(f"REFUSED: stored sheets exist after the plan's window ({later[:3]}…) — re-plan to include them", file=sys.stderr)
            return 3
        result = A.apply_plan(
            live_store(writable=True), plan, out_dir, args.phase, now, args.from_date, args.limit, approved_plan_id=args.approved_plan_id
        )
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
