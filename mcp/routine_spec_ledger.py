"""
mcp/routine_spec_ledger.py — durable home for a committed routine's spec (#4079).

Problem: a routine committed from a chat coaching session only ever lived as a
markdown file the skill hand-authored into docs/coaching/routines/<type>/ and
asked Matthew to `git commit` — a step chat cannot perform (no repo, no git
tool). The result: docs/coaching/routines/README.md's index has been stale
since 2026-09-19 while routines kept committing to Hevy underneath it.

This module gives the `commit` action of `manage_hevy_routine`
(mcp/tools_hevy_routine.py::_action_commit) a durable, chat-reachable home
that needs no git step at all — written by the same call that pushes to Hevy.

Storage ruling (#4079): a private S3 object, not a new DDB record.
  - `USER#matthew#ROUTINE#<id>` in DynamoDB (lambdas/training/routine_repo.py)
    already carries the full versioned IR on every commit, and is already
    classified SYSTEM_STATE in lambdas/experiment/phase_taxonomy.py ("Versioned
    routine IR audit trail + ops state"). That's the machine's working store —
    the thing `draft`/`dry_run`/`commit` themselves read and write — not a
    place a coaching session goes looking for "the spec". No NEW phase-taxonomy
    classification is needed here: this ledger is an S3 object, and the
    taxonomy's domain is DynamoDB pk/sk only.
  - `config/coaching/` is the established OWNER-PRIVATE prefix the skill
    already reads from for TRAINING_CONTEXT.md / TRAINING_CALIBRATION.md /
    TRAINING_PROGRAM.md / PROVEN_BLUEPRINT.md (docs/coaching/COACH_SESSION.md,
    .claude/skills/daily-debrief/SKILL.md) — never public, unlike
    `generated/*` / `site/*` / `blog/*`. The MCP server role already carries
    `s3:PutObject` on `config/*` (cdk/stacks/role_policies_serve.py::
    mcp_server, sid S3Write) — no CDK/IAM change needed to land this.

Key shape: `config/coaching/routine_specs/<archetype>/<routine_id>.json` — one
object per routine_id, overwritten on a re-commit (a re-commit is a new
version of the SAME spec, matching the docs/coaching/routines/ convention of
"bump the file when the routine materially changes", not a new file per
commit). `deploy/backfill_routine_specs.py` writes into this exact shape for
every routine committed since 2026-09-21 that predates this module.

Fail-soft by contract, mirroring mcp/audit.py's #753 write-audit trail:
`save_routine_spec` never raises. A ledger-write failure must never block or
unwind an already-successful Hevy commit.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("routine_spec_ledger")

SPEC_PREFIX = "config/coaching/routine_specs"

_S3_CLIENT = None


def _spec_s3():
    """Lazy S3 client, tight timeouts + a single attempt — same fail-open contract
    as mcp/audit.py's `_audit_s3()`: a wedged S3 endpoint must never stall a
    commit response that has already succeeded against Hevy."""
    global _S3_CLIENT
    if _S3_CLIENT is None:
        import os

        import boto3
        from botocore.config import Config

        _S3_CLIENT = boto3.client(
            "s3",
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
            config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}),
        )
    return _S3_CLIENT


def spec_key(archetype: str | None, routine_id: str) -> str:
    return f"{SPEC_PREFIX}/{archetype or 'unclassified'}/{routine_id}.json"


def content_hash(ir: Any) -> str:
    """SHA-256 of the committed IR's own content — the spec's own material, not
    the Hevy wire body (the compiler derives that, and its shape can change
    independent of what was actually specified). Canonical `json.dumps(...,
    sort_keys=True)` over the dataclass, float-coerced exactly like
    `training.routine_ir.serialize` does for its own DDB write, so the hash is
    stable across a DDB round-trip (Decimal <-> float) and independent of dict
    key order."""
    from common.numeric import decimals_to_float

    payload = decimals_to_float(asdict(ir))
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_spec(ir: Any, *, committed_at: str | None = None) -> dict[str, Any]:
    """The #4079 fixture: routine_id, content hash, date, session role — plus
    enough identity (archetype/variant/title/hevy id/version/status) that a
    reader, or the backfill sweep, doesn't need a second lookup to know what
    it's looking at.

    `committed_at` defaults to now (the live commit path calls this right after
    the Hevy push); `deploy/backfill_routine_specs.py` passes the routine's own
    `hevy_pushed_at` instead so a backfilled spec's timestamp is the ORIGINAL
    commit instant, not the moment the sweep happened to run."""
    return {
        "routine_id": ir.routine_id,
        "hevy_routine_id": ir.hevy_routine_id,
        "archetype": ir.archetype,
        "variant": ir.variant,
        "title": ir.title,
        "target_date": ir.target_date,
        "status": ir.status,
        "version": ir.version,
        "content_hash": content_hash(ir),
        "committed_at": committed_at or datetime.now(timezone.utc).isoformat(),
        # `created_by` is "chat" | "cron" on RoutineSpec (training/routine_ir.py) —
        # the closest existing field to "which session authored this"; reused
        # rather than inventing a second provenance concept.
        "session_role": ir.created_by,
        "schema_version": 1,
    }


def save_routine_spec(ir: Any, *, committed_at: str | None = None) -> dict[str, Any]:
    """Write the committed routine's spec to its durable S3 home.

    Called once, at the end of a successful `commit`
    (mcp/tools_hevy_routine.py::_action_commit), AFTER `put_versioned(ir)` — so
    the spec written is for exactly the state that made it into Hevy, never a
    draft that never shipped. `deploy/backfill_routine_specs.py` also calls this
    directly (with `committed_at` pinned to the routine's own `hevy_pushed_at`)
    for everything committed before this module existed.

    Never raises. Returns a small report the commit result folds in under
    `routine_spec`, so the caller — chat, reading the tool result — can see the
    spec landed with no git step: an "instant recorded" (#4079 acceptance),
    not an assumption.
    """
    spec = build_spec(ir, committed_at=committed_at)
    key = spec_key(ir.archetype, ir.routine_id)
    try:
        from mcp.config import S3_BUCKET

        _spec_s3().put_object(
            Bucket=S3_BUCKET,
            # Spelled as a literal f-string (== spec_key; pinned by a test) so
            # deploy/config_twin_registry.py resolves this write to the runtime family
            # `config/coaching/routine_specs/*/*.json` — no repo twin may shadow it.
            Key=f"config/coaching/routine_specs/{ir.archetype or 'unclassified'}/{ir.routine_id}.json",
            Body=json.dumps(spec, sort_keys=True),
            ContentType="application/json",
        )
        return {"saved": True, "key": key, "committed_at": spec["committed_at"], "content_hash": spec["content_hash"]}
    except Exception as e:  # noqa: BLE001 — fail-soft: a ledger write must never break a successful commit
        logger.warning(f"[#4079] routine-spec ledger write failed for {ir.routine_id} (commit unaffected): {e}")
        return {"saved": False, "key": key, "error": str(e)}
