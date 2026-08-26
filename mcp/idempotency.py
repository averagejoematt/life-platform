"""mcp/idempotency.py — replay semantics for the write-capable MCP tools (#3114, #3115).

DIL-025's census (`docs/IDEMPOTENCY.md` §5) found that most of the 26 write tools
(`mcp/audit.py::is_write_tool`) key their writes on something deterministic and are
replay-safe by overwrite. A minority keyed on `datetime.now()` or `uuid4()`, so a
retried tool call — Claude Desktop reconnecting mid-call, a user double-submitting,
a client-side timeout on a write that actually landed — appended a SECOND row that
no later read could distinguish from a genuine second event. Those partitions feed
graded track records and the character engine, so a duplicate inflates the
denominator of an honesty metric (ADR-104/105).

Two primitives live here:

1. **The claim ledger** (`claim` / `release`) — a conditional put on a deterministic
   `(scope, content-key)` row in its OWN partition, taken BEFORE the real write. It
   is the same shape as the vote/follow family's conditional-dedup-row-before-counter
   (`lambdas/web/site_api_social_experiments.py:228`), lifted out so the MCP tools
   share one implementation. Reach for it when the target row's key cannot be made
   deterministic without breaking readers (`log_decision`'s time-ordered sort key)
   or when the side effect is a third party's (`create_todoist_task`).

   **It fails OPEN, by contract.** A broken ledger degrades to a possible duplicate,
   never to a silently dropped write — the same rule `common/send_ledger.py` states
   for the sender fleet. Only a real `ConditionalCheckFailedException` suppresses a
   write; every other error proceeds and logs.

   `release()` does NOT delete: the MCP role has PutItem on the table but no
   DeleteItem, so a release is a put that marks the row re-claimable. A claim taken
   before a third-party call that then FAILED must be released, or a legitimate
   retry is blocked for the window — which is the fail-closed direction.

2. **The declaration registry** (`REPLAY_SEMANTICS`) — every write tool says, in
   source, what happens when it runs twice. `tests/test_mcp_write_idempotency_3114_3115.py`
   DERIVES the write set from `is_write_tool` over the live registry and asserts each
   member has a declaration, so a 27th write tool cannot land without answering the
   question. Presence is what the test can check; honesty is the reviewer's job.

Two things this module deliberately does NOT do:

  * It is not a generic dispatch-layer replay cache. A blanket "same tool + same args
    within N seconds = suppress" at `mcp/handler.py` would also suppress a genuinely
    distinct second event with identical arguments (two 30-minute reading sessions in
    one evening). Replay identity is a per-tool SEMANTIC question, so each tool names
    the fields that make its call the same event.
  * It does not touch the S3 write-audit trail (`mcp/audit.py`). That trail is
    append-only on purpose: a duplicate audit entry is the correct record of a
    duplicate CALL, and it is the only evidence that a replay was suppressed.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from common.numeric import decimals_to_float, floats_to_decimal  # bundled shared module (#1207)

logger = logging.getLogger()

#: Dedup rows live in their OWN partition, never beside the records they guard —
#: a ledger row in `USER#matthew#SOURCE#decisions` would be returned by
#: `get_decisions`' partition query and counted as a decision.
LEDGER_PK = f"USER#{os.environ.get('USER_ID', 'matthew')}#MCP_IDEMPOTENCY"

#: Ledger rows self-expire. Long enough that a replay days later is still caught,
#: short enough that the partition does not grow without bound.
DEFAULT_TTL_DAYS = 180

#: The stock note returned on a suppressed replay. Says what happened AND what to do
#: if the second call was genuinely a second event — never a silent no-op.
DUPLICATE_NOTE = (
    "Duplicate suppressed (#3114/#3115): an identical call already landed, so nothing was written a second time. "
    "The first record's id is returned. If this really is a distinct second event, vary the content."
)


def content_key(*parts: Any) -> str:
    """A stable 16-hex digest of the fields that make a call the SAME event.

    Whitespace-normalised and case-preserving; containers go through canonical JSON
    so `["a","b"]` and `["a", "b"]` collapse but `["b","a"]` does not (list order is
    meaning, not formatting). `None` and `""` are distinct from a missing part only
    in position — callers pass a fixed tuple of fields, so position is stable.
    """
    canon = []
    for part in parts:
        if isinstance(part, (dict, list, tuple)):
            canon.append(json.dumps(part, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False))
        else:
            canon.append(" ".join(str("" if part is None else part).split()))
    return hashlib.sha256("\x1f".join(canon).encode("utf-8")).hexdigest()[:16]


def _sk(scope: str, key: str) -> str:
    return f"{scope}#{key}"


def _is_conditional_failure(exc: Exception) -> bool:
    return "ConditionalCheckFailed" in type(exc).__name__ or "ConditionalCheckFailedException" in str(exc)


def claim(
    table,
    scope: str,
    key: str,
    *,
    payload: dict | None = None,
    window_seconds: int | None = None,
    ttl_days: int = DEFAULT_TTL_DAYS,
    now: datetime | None = None,
) -> dict:
    """Take the write claim for `(scope, key)`. Call this BEFORE the real write.

    Returns ``{"claimed": True, ...}`` when the caller owns the write and must
    proceed, or ``{"claimed": False, "first": <the first claim's row>}`` when an
    identical call already landed and the caller must NOT write again.

    ``window_seconds=None`` (the default) makes the claim permanent: the same content
    key is never written twice. Pass a window for a call whose content identity is not
    unique over all time — two genuinely distinct 30-minute reading sessions in one day
    have identical fields, so `log_session` claims for a few minutes (long enough to
    swallow a retry, short enough that the evening's second session still records).

    ``degraded: True`` marks a fail-open pass: the ledger errored (throttle, missing
    grant, no table) and the write proceeds unguarded rather than being lost.
    """
    now = now or datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    sk = _sk(scope, key)
    item = {
        "pk": LEDGER_PK,
        "sk": sk,
        "scope": scope,
        "claimed_at": epoch,
        "released": False,
        "ttl": epoch + int(ttl_days) * 86400,
        # boto3 rejects a bare Python float; the shared #1207 walker is the canonical
        # cast (never a private copy — the D5 guard in tests/test_ddb_patterns.py).
        "payload": floats_to_decimal(dict(payload or {})),
    }
    condition = "attribute_not_exists(sk) OR released = :yes"
    values: dict = {":yes": True}
    if window_seconds is not None:
        condition += " OR claimed_at < :cutoff"
        values[":cutoff"] = epoch - int(window_seconds)
    try:
        table.put_item(Item=item, ConditionExpression=condition, ExpressionAttributeValues=values)
        return {"claimed": True, "first": None, "degraded": False}
    except Exception as e:  # noqa: BLE001 — fail-open is the contract
        if not _is_conditional_failure(e):
            logger.warning(f"[#3114] idempotency claim failed open for {sk} (write proceeds unguarded): {e}")
            return {"claimed": True, "first": None, "degraded": True}
    try:
        first = (table.get_item(Key={"pk": LEDGER_PK, "sk": sk}) or {}).get("Item") or {}
    except Exception as e:  # noqa: BLE001 — the suppression stands; only the echo is lost
        logger.warning(f"[#3114] could not read the first claim for {sk}: {e}")
        first = {}
    return {"claimed": False, "first": first, "degraded": False}


def first_payload(result: dict) -> dict:
    """The payload the winning claim stored (ids to echo back), or ``{}`` — JSON-safe
    (Decimals back to float, so the tool's response serialises)."""
    return dict(decimals_to_float((result.get("first") or {}).get("payload") or {}))


def guard(
    table,
    scope: str,
    key: str,
    *,
    payload: dict | None = None,
    window_seconds: int | None = None,
) -> dict | None:
    """`claim` + the stock duplicate response, for the call sites that only need
    "proceed, or return this to the caller".

    Returns ``None`` when the caller owns the write, or the response dict to return
    verbatim when an identical call already landed. The dict is the winning claim's
    payload (so the first record's ids are echoed) plus `duplicate` and `note`.
    """
    result = claim(table, scope, key, payload=payload, window_seconds=window_seconds)
    if result["claimed"]:
        return None
    return {**first_payload(result), "duplicate": True, "note": DUPLICATE_NOTE}


def record(table, scope: str, key: str, payload: dict, *, ttl_days: int = DEFAULT_TTL_DAYS, now: datetime | None = None) -> None:
    """Attach the completed write's ids to a claim the caller already holds.

    An UNCONDITIONAL put — the caller won the claim, so it owns the row. Called after
    the guarded side effect lands (a Todoist task id is only knowable once the POST
    returns), so a later suppressed replay can echo the real id rather than the empty
    placeholder the claim was taken with. Never raises: losing the echo is cosmetic,
    losing the claim is not.
    """
    now = now or datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    try:
        table.put_item(
            Item={
                "pk": LEDGER_PK,
                "sk": _sk(scope, key),
                "scope": scope,
                "claimed_at": epoch,
                "released": False,
                "ttl": epoch + int(ttl_days) * 86400,
                "payload": floats_to_decimal(dict(payload or {})),
            }
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[#3115] idempotency payload record failed for {_sk(scope, key)}: {e}")


def release(table, scope: str, key: str, *, now: datetime | None = None) -> None:
    """Hand a claim back after the guarded write FAILED, so a retry can proceed.

    A put, not a delete — the MCP role has no `dynamodb:DeleteItem`. Never raises:
    a failed release costs a blocked retry inside the window, which the caller
    surfaces as an error anyway.
    """
    now = now or datetime.now(timezone.utc)
    epoch = int(now.timestamp())
    try:
        table.put_item(
            Item={
                "pk": LEDGER_PK,
                "sk": _sk(scope, key),
                "scope": scope,
                "claimed_at": 0,
                "released": True,
                "ttl": epoch + 86400,
                "payload": {},
            }
        )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[#3114] idempotency release failed for {_sk(scope, key)}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# The declaration registry — every write tool states its replay semantics
# ══════════════════════════════════════════════════════════════════════════════

#: Naturally safe: the write lands on a key derived entirely from the call's own
#: arguments, so a replay overwrites the identical row.
DETERMINISTIC_KEY = "deterministic-key"
#: The key is derived from a hash of the record's CONTENT (#3114 work, or an
#: existing precedent like `mark_journal_quote`'s `QUOTE#{date}#{sha256}`).
CONTENT_KEY = "content-key"
#: Guarded by the claim ledger above — a conditional dedup row taken before the write.
CLAIM_LEDGER = "claim-ledger"
#: Reads first and refuses (or short-circuits) on an existing record.
READ_BEFORE_WRITE = "read-before-write"
#: Duplicating is the correct behaviour (an append-only trail).
APPEND_BY_DESIGN = "append-by-design"
#: Honestly not guarded. The value is the reason — never left blank.
RESIDUAL = "residual"

VALID_MECHANISMS = frozenset({DETERMINISTIC_KEY, CONTENT_KEY, CLAIM_LEDGER, READ_BEFORE_WRITE, APPEND_BY_DESIGN, RESIDUAL})

#: tool name -> (mechanism, one-line evidence/reason).
#: A write tool missing from this map fails
#: `tests/test_mcp_write_idempotency_3114_3115.py::test_every_write_tool_declares_its_replay_semantics`.
REPLAY_SEMANTICS: dict[str, tuple[str, str]] = {
    # ── #3114: the timestamp/uuid-keyed writes this change fixed ──────────────
    "log_decision": (CLAIM_LEDGER, "DECISION#{ms-ts} kept for ordering; claim on (date, decision, source, followed, note)"),
    "save_insight": (CLAIM_LEDGER, "INSIGHT#{second-ts} kept for ordering; claim on (date, text, source, tags)"),
    "log_coach_correction": (CONTENT_KEY, "correction_id defaults to sha256(item_ref, text, error_class)[:8]; conditional put"),
    "audit_coach_dossier": (CONTENT_KEY, "retract/correct route through the same coach_corrections.write_correction"),
    "manage_reading": (
        CLAIM_LEDGER,
        "log_session windowed claim; add_note/debrief note ids content-derived; debrief probe read-before-write",
    ),
    "curate_horizon": (CONTENT_KEY, "PICK#{week} was already deterministic; the follow-up CHECKIN# uid is now content-derived"),
    "manage_hevy_routine": (DETERMINISTIC_KEY, "routine_id derived from (target_date, archetype, variant); commit find-or-creates in Hevy"),
    # ── #3115: the third-party creates ────────────────────────────────────────
    "create_todoist_task": (CLAIM_LEDGER, "no vendor idempotency header on the REST surface — windowed local find-or-create"),
    "close_todoist_task": (CLAIM_LEDGER, "close ADVANCES a recurring task; windowed claim on task_id refuses the replay"),
    "update_todoist_task": (DETERMINISTIC_KEY, "POST /tasks/{id} with the same fields is a converging update, not an append"),
    # ── Already replay-safe before this change (census §5) ────────────────────
    "archive_horizon": (DETERMINISTIC_KEY, "writes PICK#{week} and its retrospective in place — one row per ISO week"),
    "create_experiment": (READ_BEFORE_WRITE, "pre-reads and RAISES on a duplicate rather than upserting"),
    "delete_platform_memory": (DETERMINISTIC_KEY, "delete of a caller-named (category, key); a second delete removes nothing"),
    "end_experiment": (DETERMINISTIC_KEY, "sets terminal fields on the caller-named experiment row; converging, not appending"),
    "evaluate_prediction": (DETERMINISTIC_KEY, "grades the caller-named prediction row in place; the grade is a function of the row"),
    "log_coach_calibration": (
        READ_BEFORE_WRITE,
        "GUARDED, not natural: the Beta counter is only safe because a conditional put on a deterministic LEARNING# sk short-circuits first (coach_calibration.py:395-449) — do not remove that guard",
    ),
    "log_coach_checkin": (DETERMINISTIC_KEY, "answers the caller-supplied CHECKIN# sk — a replay rewrites the same answer"),
    "log_evening_intake": (DETERMINISTIC_KEY, "one row per DATE# — a replay overwrites the same evening (guarded since #1484)"),
    "log_field_note_response": (DETERMINISTIC_KEY, "answers the caller-named field-note row; the response replaces, never appends"),
    "log_habit_reflection": (DETERMINISTIC_KEY, "one row per (habit, date) — a replay overwrites that day's reflection"),
    "manage_diary_claims": (DETERMINISTIC_KEY, "each claim is keyed by its own caller-supplied id, so a replay converges"),
    "manage_sick_days": (DETERMINISTIC_KEY, "one row per DATE# — marking the same day sick twice is one sick day"),
    "mark_journal_quote": (CONTENT_KEY, "QUOTE#{date}#{sha256(norm(quote))[:10]} — the in-repo precedent this change copied"),
    "update_decision_outcome": (DETERMINISTIC_KEY, "updates the caller-supplied DECISION# sk in place; no new row is ever created"),
    "update_insight_outcome": (DETERMINISTIC_KEY, "updates the caller-supplied INSIGHT# sk in place; no new row is ever created"),
    "write_platform_memory": (DETERMINISTIC_KEY, "one row per (category, key) — a rewrite is the point, not a duplicate"),
}
