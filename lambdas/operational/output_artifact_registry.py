#!/usr/bin/env python3
"""The output-artifact registry — dead-man switches on jobs that run OFF-platform.

WHY THIS EXISTS (2026-08-31)
  The freshness checker watches INPUT sources: it asks "has data arrived?" and it can
  only ask that of things that write to DynamoDB. Some jobs are not like that. The
  laptop's daily memory backup runs under launchd on one machine, writes to S3, and is
  invisible to every gate the platform has:

    * CI cannot see it — the LaunchAgent binding is local-machine state, and
      `tests/test_backup_agent_path_contract.py`'s two live assertions skip on a runner.
    * The path contract only fires if a human runs the suite locally.
    * And the failure that matters produces NO log line and NO test failure, because
      **nothing runs**. A stale launchd path, a revoked credential, an unloaded agent —
      each one is silent by construction. The last log entry just stops, and a log that
      stops looks exactly like a log nobody has read yet.

  The only control that catches "the job never fired" is an age check on its OUTPUT,
  performed from somewhere else. That is what this registry holds. It does not care WHY
  the job stopped, which is the point: it closes the class, not the instance.

WHY A HEARTBEAT AND NOT THE PAYLOAD
  The obvious check is the age of the backed-up file itself — `MEMORY.md`. It does not
  work, and the way it fails is instructive. `aws s3 sync` uploads only CHANGED files, so
  `MEMORY.md`'s LastModified is the age of the last *content change*, not of the last
  *run*. Measured on 2026-08-31: the job ran four times between 14:40Z and 15:12Z and
  S3 still reported 14:40:33Z, because only the first run had anything to upload.

  A quiet weekend would therefore age the payload past any threshold while the job ran
  perfectly every morning — a false positive on a daily schedule. An alarm that cries
  wolf gets muted, and a muted alarm is worse than none because it still looks like
  coverage. So the producer writes a small heartbeat object on every SUCCESSFUL run, and
  that object's age is the signal. It measures the thing we actually care about — "the
  job completed" — instead of a proxy that drifts away from it.

  The heartbeat also carries what the run saw (file count, source path), so
  "backed up successfully" can be distinguished from "backed up nothing successfully".

READ FAILURES ARE NOT FRESHNESS
  An artifact we could not read is reported `unknown`, never `fresh`. The platform has
  paid for this rule elsewhere (#2662: an unrecognised source name was dropped from the
  freshness tool, which then answered green over what was left). `unknown` is a NOT-OK
  answer and surfaces alongside stale ones — but it is labelled distinctly, so an
  operator is never told "your backup is stale" when the truth is "this check cannot see".
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

BUCKET = "matthew-life-platform"

# Status values. `unknown` is deliberately not `stale`: different cause, different fix.
STATUS_FRESH = "fresh"
STATUS_STALE = "stale"
STATUS_UNKNOWN = "unknown"

# ── The registry ──────────────────────────────────────────────────────────────
# One row per off-platform job whose silence would otherwise be invisible. Adding a
# job here is the whole integration: the freshness checker and the MCP tool both derive
# from this dict, so neither can drift from it (the #392 mirror class).
OUTPUT_ARTIFACTS: dict[str, dict[str, Any]] = {
    "claude_memory_backup": {
        "label": "Claude memory backup",
        "bucket": BUCKET,
        # Written unconditionally on every successful memory sync by
        # setup/claude_memory_backup.sh. Lives INSIDE claude-memory-backup/ on purpose:
        # that prefix already carries a lifecycle rule (noncurrent 90d) and delete
        # protection in deploy/bucket_policy.json, so the heartbeat inherits both rather
        # than needing a new uncovered prefix. Every memory gate globs *.md, so a .json
        # here is inert on restore.
        "key": "claude-memory-backup/_backup_heartbeat.json",
        # Daily at 09:15 local. 36h tolerates one missed window (a closed laptop, a late
        # wake) and trips on the second — short enough to catch a dead job the next
        # morning, long enough not to fire on an ordinary overnight.
        "max_age_hours": 36,
        "produced_by": "com.matthewwalker.claude-memory-backup (laptop launchd, daily 09:15 PT)",
        "why": (
            "The Claude memory dir exists on ONE laptop and is not in git. If this backup "
            "stops, the only copy of the incident narratives and preference memory is a "
            "machine that can be lost. docs/CONTINUITY.md §4."
        ),
        "runbook": (
            "Check the laptop: `launchctl print gui/$(id -u)/com.matthewwalker.claude-memory-backup` "
            "and the tail of ~/Library/Logs/claude-backup/backup-<date>.log. Then run "
            "`pytest tests/test_backup_agent_path_contract.py` locally — it asserts the "
            "LaunchAgent still points at setup/claude_memory_backup.sh in the repo. A moved "
            "or renamed checkout is the most likely cause."
        ),
    },
}


def artifact_keys() -> list[str]:
    """Registry keys, sorted — the derivation point for every consumer."""
    return sorted(OUTPUT_ARTIFACTS)


def _age_hours(last_modified: datetime, now: datetime) -> float:
    if last_modified.tzinfo is None:
        last_modified = last_modified.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return (now - last_modified).total_seconds() / 3600.0


def check_artifact(key: str, s3_client, now: Optional[datetime] = None) -> dict:
    """Evaluate ONE registry entry. Never raises: a read failure becomes `unknown`.

    Returns a dict with: key, label, status, age_hours (None if unreadable), threshold,
    detail (a sentence fit for an alert body), and — when the heartbeat parsed — the
    payload fields the producer recorded.
    """
    spec = OUTPUT_ARTIFACTS[key]
    now = now or datetime.now(timezone.utc)
    out = {
        "key": key,
        "label": spec["label"],
        "status": STATUS_UNKNOWN,
        "age_hours": None,
        "threshold_hours": spec["max_age_hours"],
        "s3_uri": f"s3://{spec['bucket']}/{spec['key']}",
        "produced_by": spec["produced_by"],
        "runbook": spec["runbook"],
        "detail": "",
        "payload": None,
    }

    try:
        head = s3_client.head_object(Bucket=spec["bucket"], Key=spec["key"])
    except Exception as e:  # noqa: BLE001 — every failure mode is 'we cannot see', by design
        name = type(e).__name__
        code = ""
        try:
            code = e.response["Error"]["Code"]  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
        if code in ("404", "NoSuchKey", "NotFound"):
            out["detail"] = (
                f"No heartbeat object at {out['s3_uri']} — the job has never completed a run "
                f"since the heartbeat was introduced, or the object was removed. NOT read as fresh."
            )
        elif code in ("AccessDenied", "403"):
            out["detail"] = (
                f"Access denied reading {out['s3_uri']} — this CHECK is broken, which is not the "
                f"same as the backup being broken. Grant s3:GetObject on the prefix "
                f"(cdk/stacks/role_policies_operational.py) and redeploy."
            )
        else:
            out["detail"] = f"Could not read {out['s3_uri']} ({name} {code}) — reporting unknown rather than fresh."
        return out

    age = _age_hours(head["LastModified"], now)
    out["age_hours"] = round(age, 1)

    body = None
    try:
        body = json.loads(s3_client.get_object(Bucket=spec["bucket"], Key=spec["key"])["Body"].read())
        out["payload"] = body
    except Exception:  # noqa: BLE001 — the timestamp is the signal; the payload is context
        pass

    extra = ""
    if isinstance(body, dict) and body.get("memory_files") is not None:
        extra = f", last run backed up {body['memory_files']} memory file(s)"
        # A run that succeeded over an empty source is a successful backup of nothing.
        # The producer refuses to write a heartbeat in that case, so this is belt-and-
        # braces — but if it ever appears, it must not read as healthy.
        try:
            if int(body["memory_files"]) <= 0:
                out["status"] = STATUS_STALE
                out["detail"] = (
                    f"Heartbeat is {age:.0f}h old but records ZERO memory files — the job ran and "
                    f"backed up nothing. Treat as failed, not fresh. {spec['runbook']}"
                )
                return out
        except (TypeError, ValueError):
            pass

    if age > spec["max_age_hours"]:
        out["status"] = STATUS_STALE
        out["detail"] = (
            f"Last successful run {age:.0f}h ago (threshold {spec['max_age_hours']}h){extra}. "
            f"Produced by {spec['produced_by']}. {spec['runbook']}"
        )
    else:
        out["status"] = STATUS_FRESH
        out["detail"] = f"Last successful run {age:.0f}h ago (threshold {spec['max_age_hours']}h){extra}."
    return out


def check_all(s3_client, now: Optional[datetime] = None) -> list[dict]:
    """Evaluate every registry entry, in stable key order."""
    return [check_artifact(k, s3_client, now) for k in artifact_keys()]


def not_ok(results: list[dict]) -> list[dict]:
    """The rows an operator must act on — stale AND unknown.

    `unknown` is included deliberately. A check that cannot see its target is not
    evidence of health, and excluding it here would recreate exactly the silent-green
    the registry exists to prevent.
    """
    return [r for r in results if r["status"] != STATUS_FRESH]
