"""coach_corrections.py — the durable ledger for Matthew's corrections to weekly
AI-review-pack items (#1689, foundation story for epic #1687 "The Coach Correction Loop").

The weekly AI-review-pack email (#1594) numbers + stack-ranks each generation and
tags it with a checkable claim (S1, #1688). When Matthew corrects an item, the
correction needs a durable home — tagged by **error-class** — so it can later feed
three downstream mechanisms (none of them built by this story):
  - prompt-memory: a per-coach "past corrections for you" few-shot block (S5, #1691+)
  - deterministic gates: recurring classes graduate to hard checks (ADR-104/105)
  - pattern-extraction: periodic clustering that proposes memory→gate promotions (S6)

This module is JUST the ledger: storage + a pure item-builder + a mockable
writer/reader. The feedback CHANNELS that call `write_correction()` — an MCP tool
(`log_coach_correction`) and an email-reply parser — are #1690, out of scope here.

Design (mirrors `lambdas/eval_retention.py`'s build/write/read split and
`lambdas/emails/ai_review_pack_lambda.py::record_email_send`'s mockable-table idiom):
- Records live at pk `USER#matthew#SOURCE#coach_corrections`,
  sk `CORRECTION#<YYYY-MM-DD>#<id8>` (id8 = the CONTENT digest of what was
  corrected + what was said + the class, per #3114 — it was `uuid4().hex[:8]`,
  which appended a fresh row on every replay of the same correction) — single-table
  convention, no new GSI (adding one requires an ADR; this module reads via a
  plain partition Query + client-side filter).
- Classified **CROSS_PHASE** in `lambdas/phase_taxonomy.py`: a correction Matthew
  makes about a coach's error stays true across experiment resets — it is not a
  property of the current run (same rationale as the CROSS_PHASE "calibration"
  and "EVALRET#" ledgers), so it is NEVER tagged, wiped, or phase-filtered.
- `build_correction_item()` is PURE (no AWS) — unit-testable in isolation.
- `write_correction()` / `list_corrections()` / `get_correction()` /
  `update_status()` all take a boto3 Table resource as their first argument
  (mockable with `tests/fakes.py::FakeDdbTable`), mirroring
  `ai_review_pack_lambda.record_email_send(table, ...)`.
- Decimal-before-write (ADR/CLAUDE.md convention): any float inside `item_ref`
  (e.g. a pack number) is cast to `Decimal` before the put via the shared
  `lambdas/numeric.py::floats_to_decimal` walker (#1207) — boto3 rejects a bare
  Python `float`, and this module deliberately does NOT fork its own copy (the
  D5 regression guard in `tests/test_ddb_patterns.py` enforces that).

v1.0.0 — 2026-07-22 (#1689)
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from common.numeric import floats_to_decimal

# `normalize_coach_id` is THE shared coach-id normalizer (#1786): the ledger's writers
# spell a coach id differently — the review-pack resolver stores the S3 archive `variant`
# (suffixed: "mind_coach"), the dossier channel stores f"{bare}_coach", and older rows
# carry the bare form ("mind") or no `coach` key at all — while
# `ai_calls._run_coach_v2_pipeline` READS with the suffixed id. Comparing the raw strings
# made the S5 injection a live no-op; both sides now normalize at the join
# (`_item_ref_matches`). Flat sibling imports, per #781 (every root module ships together).
from coach.coach_checkin import normalize_coach_id, read_cycle

PK = "USER#matthew#SOURCE#coach_corrections"
SK_PREFIX = "CORRECTION#"

# The error-class vocabulary locked by epic #1687 / story #1688 — the checkable-claim
# tags the review pack applies to each ranked item. Kept as a tuple so #1688 (the
# ranker/tagger) and #1690 (the feedback channels) import ONE source of truth rather
# than each hand-rolling the list. "other" is the deliberate free-form fallback: an
# unrecognized tag is never silently dropped (see `build_correction_item` below) — it
# is normalized to "other" with the original label preserved in `error_class_raw`.
ERROR_CLASSES = (
    "stale-baseline",  # reset-window contamination — frozen pre-genesis baselines cited as current
    "ungrounded-behavioral",  # a behavioral claim with no supporting log ("you maintained your window")
    "cross-coach-inconsistency",  # two coaches asserting conflicting numbers for the same target
    "framing",  # technically-true but misleadingly framed
    "checkable-metric",  # a specific numeric claim that is simply wrong
    "hedged-safe",  # correctly hedged / appropriately uncertain (a "no correction needed" tag)
    "defense-held",  # Matthew reviewed a flagged item and the generation's claim held up
    "other",  # free-form fallback — never silently drops an unrecognized class
)

# The lifecycle a correction moves through once #1690's channels + #1691's gate
# start consuming the ledger. "open" is the only state this story ever writes;
# the other two are downstream transitions via `update_status()`.
STATUSES = ("open", "applied-to-prompt", "applied-to-gate")

_ID_LEN = 8


def derive_correction_id(item_ref: Optional[dict], correction_text: str, error_class: str) -> str:
    """The correction's SEMANTIC identity, as 8 hex — replacing `uuid4().hex[:8]` (#3114).

    A uuid4 suffix meant a replayed `log_coach_correction` / `audit_coach_dossier
    retract` minted a SECOND ledger row for the same correction: same subject, same
    words, same class, indistinguishable from Matthew having said it twice. Since the
    correction ledger is read by the prompt-memory injection (S5) and the promotion
    clustering (S6), a duplicate double-weights one piece of feedback.

    Derived from what makes a correction the same correction — WHAT was corrected
    (`item_ref`, canonicalised so key order cannot change the digest), WHAT was said
    (whitespace-normalised), and the class. Deliberately NOT the date: `write_correction`
    puts on `CORRECTION#{date}#{id}`, so the date is already in the key and including it
    twice would only re-open the duplicate on the stroke of UTC midnight.
    """
    canonical = json.dumps(item_ref or {}, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)
    text = " ".join((correction_text or "").split())
    return hashlib.sha256(f"{canonical}\x1f{text}\x1f{error_class or ''}".encode("utf-8")).hexdigest()[:_ID_LEN]


def build_correction_item(
    item_ref: Optional[dict],
    correction_text: str,
    error_class: str,
    *,
    now: Optional[datetime] = None,
    correction_id: Optional[str] = None,
    cycle: Optional[int] = None,
) -> dict:
    """Pure: build the DDB item for one correction. No AWS calls — unit-testable
    without a table (mirrors `eval_retention.build_record` / `ai_review_pack_lambda.build_html`).

    `item_ref` identifies what was corrected — the caller's convention (per #1687/#1688)
    is a dict with keys like `surface`, `coach`, `date`, `pack_number`/`pack_item_ref`,
    but this function does not require or validate a specific shape beyond making it
    Decimal-safe: it is stored as given (deep-copied + float-cast), so #1690's channels
    are free to pass whatever fields the S1 ranked pack exposes.

    An `error_class` outside `ERROR_CLASSES` is never dropped: it is normalized to
    "other" and the original value is preserved verbatim in `error_class_raw`.

    Float->Decimal conversion inside `item_ref` uses the shared `numeric.floats_to_decimal`
    walker (#1207) rather than a private copy — see the D5 regression guard in
    `tests/test_ddb_patterns.py`.

    `cycle` (#1791): the experiment cycle (SSM `/life-platform/experiment-cycle`) active
    when this correction was logged, same CHECKIN#-row convention as `coach_checkin.py`.
    Stored ONLY when the caller supplies one (this function stays pure/no-AWS — the
    caller reads it, typically via `coach_checkin.read_cycle()`, and passes it through
    `write_correction`). Absence is honest: a pre-#1791 row, or a write that couldn't
    reach SSM, is never guessed at.
    """
    now = now or datetime.now(timezone.utc)
    # #3114: was `uuid.uuid4().hex[:_ID_LEN]` — a fresh partition row per replay.
    correction_id = correction_id or derive_correction_id(item_ref, correction_text, error_class)
    date_str = now.strftime("%Y-%m-%d")
    sk = f"{SK_PREFIX}{date_str}#{correction_id}"

    normalized_class = error_class if error_class in ERROR_CLASSES else "other"

    item: dict = {
        "pk": PK,
        "sk": sk,
        "correction_id": correction_id,
        "item_ref": floats_to_decimal(dict(item_ref or {})),
        "correction_text": correction_text,
        "error_class": normalized_class,
        "status": "open",
        "created_at": now.isoformat(),
    }
    if normalized_class != error_class:
        item["error_class_raw"] = error_class
    if cycle is not None:
        item["cycle"] = int(cycle)
    return item


def write_correction(
    table,
    item_ref: Optional[dict],
    correction_text: str,
    error_class: str,
    *,
    now: Optional[datetime] = None,
    correction_id: Optional[str] = None,
    cycle: Optional[int] = None,
) -> str:
    """Put one correction. Returns the `sk` (the record's id) so a caller (#1690's
    MCP tool / email parser) can echo or reference it. Raises on a DDB error — unlike
    `eval_retention.retain()`, a correction write is user-initiated feedback, not a
    best-effort side channel, so a silent failure would mean Matthew's correction is
    lost without him knowing.

    `cycle` (#1791): pass-through to `build_correction_item` — the caller's job to
    resolve (typically `coach_checkin.read_cycle()`, fail-soft None). This function
    does NOT default it itself: a DDB write already raises on failure per the
    docstring above, and a bonus SSM round-trip inside the one function every
    corrections-writing caller shares would make that raise attributable to the
    wrong dependency.
    """
    item = build_correction_item(item_ref, correction_text, error_class, now=now, correction_id=correction_id, cycle=cycle)
    # #3114: the sk is now deterministic, so an unconditional put would still be
    # replay-safe for the CONTENT — but it would also reset `status` from
    # `applied-to-prompt`/`applied-to-gate` back to `open`, silently undoing a
    # downstream consumption. Write once; a replay is a no-op that returns the same sk.
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(sk)")
    except Exception as e:  # noqa: BLE001 — only a conditional failure is a duplicate
        if "ConditionalCheckFailed" not in type(e).__name__ and "ConditionalCheckFailedException" not in str(e):
            raise
    return item["sk"]


def get_correction(table, sk: str) -> Optional[dict]:
    """Fetch one correction by its `sk`. Returns None if not found."""
    resp = table.get_item(Key={"pk": PK, "sk": sk})
    return resp.get("Item")


def list_corrections(
    table,
    *,
    status: Optional[str] = None,
    error_class: Optional[str] = None,
    limit: int = 100,
) -> list:
    """Query the corrections partition (newest first), optionally filtered by
    `status` and/or `error_class`. No GSI (adding one requires an ADR) — this is a
    single-partition Query with client-side filtering, which is the right tradeoff
    for a durable feedback ledger that is written at human speed, not high volume.

    Paginates via `LastEvaluatedKey` (#1796): a single Query response silently
    caps at DynamoDB's ~1MB-per-page limit, which used to mean that once the
    partition outgrew one page, the OLDEST corrections (queried newest-first)
    were simply never seen — including retractions, whose subjects would then
    reappear on the public dossier with no error and no signal. Pages are
    fetched newest-first until either the (post-filter) result reaches `limit`
    or the partition is exhausted, so the common small-ledger case still costs
    exactly one page.
    """
    from boto3.dynamodb.conditions import Key

    items: list = []
    kwargs = {"KeyConditionExpression": Key("pk").eq(PK), "ScanIndexForward": False}
    # Hard page bound: at ~1MB/page this is ~100MB of corrections — far beyond a
    # human-speed ledger. Guarantees termination even against a pathological table
    # (a blanket MagicMock's truthy LastEvaluatedKey looped this forever and OOM-killed
    # CI runners — #1847/#1849).
    for _ in range(100):
        resp = table.query(**kwargs)
        for i in resp.get("Items", []):
            if status is not None and i.get("status") != status:
                continue
            if error_class is not None and i.get("error_class") != error_class:
                continue
            items.append(i)
        last_key = resp.get("LastEvaluatedKey")
        if not last_key or len(items) >= limit:
            break
        kwargs["ExclusiveStartKey"] = last_key
    return items[:limit]


def update_status(table, sk: str, new_status: str) -> bool:
    """Transition one correction's status (open -> applied-to-prompt|applied-to-gate).

    Raises ValueError on an unknown status rather than writing a typo'd state.
    """
    if new_status not in STATUSES:
        raise ValueError(f"unknown correction status {new_status!r} (expected one of {STATUSES})")
    table.update_item(
        Key={"pk": PK, "sk": sk},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": new_status},
    )
    return True


# ==============================================================================
# S5 (#1697, epic #1687) — prompt-memory injection
# ------------------------------------------------------------------------------
# The first live CONSUMER of the ledger: each coach's generation prompt gains a
# compact "prior corrections — do not repeat" block, scoped to that coach/surface,
# so a correction stops its *class* of error from recurring (not just the one line
# it fixed). Wired into `lambdas/ai_calls._run_coach_v2_pipeline` (the per-coach
# coach_brief generator).
#
# TWO decisions baked in here (see the #1697 PR body for the full rationale):
#
#   1. Prompt-cache boundary (COST-OPT-2 / ADR-049). This block is DYNAMIC — it
#      changes as corrections are logged/resolved — so the caller injects it into
#      the coach's DYNAMIC user portion, OUTSIDE the cached system prefix. Putting
#      it inside the cached prefix would bust the 90% cache discount on every log.
#      This module only RENDERS text; the caller owns where it lands.
#
#   2. Status lifecycle = ROLLING BOUNDED WINDOW, not auto-transition. A correction
#      stays `status="open"` and keeps suppressing its error-class on EVERY
#      generation until it is genuinely resolved (by the S6 pattern-extraction /
#      S7 gate path, or a manual `update_status`) — NOT after a single injection.
#      The #1697 acceptance's "no unbounded re-injection" is satisfied by the BOUND
#      (`PROMPT_MEMORY_MAX_PER_COACH`, newest-first), deliberately NOT by an
#      `open -> applied-to-prompt` transition on read. A single-generation
#      transition would let a still-unfixed class recur the very next cycle.
# ==============================================================================

# The rolling-window bound: at most this many OPEN corrections are injected per
# coach/surface, newest-first. Keeps the per-coach prompt cost bounded (ADR-063)
# and satisfies "no unbounded re-injection" without a status transition.
PROMPT_MEMORY_MAX_PER_COACH = 5


def _item_ref_matches(item: dict, *, surface: Optional[str], coach: Optional[str]) -> bool:
    """True if `item`'s `item_ref` matches the requested coach/surface scope.

    A `None` filter is a wildcard for that axis. Scoping is what makes each coach
    see ONLY its own corrections (never the global list) — the core #1697 acceptance.

    TWO id-form rules, both from #1786 (the S5 injection was a live no-op because
    neither held — every open correction reached zero coaches):

      1. **Normalized comparison.** The ledger's writers spell the coach id
         differently (`coach_correction_resolver.build_item_ref` stores the archive
         `variant` — "mind_coach"; `tools_coach_intelligence` stores f"{bare}_coach";
         legacy rows carry the bare "mind") and the reader passes the suffixed
         pipeline id. Both sides go through `normalize_coach_id`, so "mind" and
         "mind_coach" are the SAME coach. Normalization is one-way (suffix stripped,
         never re-added), so a non-coach `variant` on another surface still compares
         as itself.
      2. **A row with no coach applies to EVERY coach on its surface.** A correction
         logged without a coach is a correction about that surface's output in
         general ("stop citing the pre-genesis baseline"); silently addressing it to
         nobody is the failure mode, not the safe default. Scoping is still real —
         a row that NAMES a coach reaches only that coach.
    """
    ref = item.get("item_ref") or {}
    if surface is not None and ref.get("surface") != surface:
        return False
    if coach is not None:
        row_coach = ref.get("coach")
        if row_coach in (None, ""):
            return True  # surface-wide correction — applies to every coach on this surface
        if normalize_coach_id(str(row_coach)) != normalize_coach_id(str(coach)):
            return False
    return True


def open_corrections_for(
    table,
    *,
    surface: Optional[str] = None,
    coach: Optional[str] = None,
    limit: int = PROMPT_MEMORY_MAX_PER_COACH,
) -> list:
    """The S5 read: OPEN corrections scoped to one coach/surface, newest-first,
    bounded to `limit` (the rolling window).

    Status is NOT mutated here — a read never transitions a correction (see the
    module note: rolling window, not auto-transition). Newest-first is enforced by
    sorting on `sk` (`CORRECTION#<YYYY-MM-DD>#<id8>`) descending, so the bound is
    deterministic regardless of the table's native scan order (real DDB already
    returns newest-first via ScanIndexForward=False; the sort also makes the bound
    stable under the in-memory test fake).
    """
    opened = list_corrections(table, status="open", limit=10000)
    scoped = [i for i in opened if _item_ref_matches(i, surface=surface, coach=coach)]
    scoped.sort(key=lambda i: i.get("sk", ""), reverse=True)
    return scoped[: max(0, int(limit))]


def _provenance_stamp(item: dict, *, current_cycle: Optional[int]) -> str:
    """#1791: the "(logged YYYY-MM-DD, cycle N)" (or subset) rendered before a
    correction's text. Never fabricates a piece it doesn't have — a row with no
    `created_at` (a hand-built test/legacy shape) or no `cycle` (pre-#1791, or a
    write that couldn't reach SSM) just omits that piece, rather than guessing.

    When BOTH this row's `cycle` and `current_cycle` are known and they differ,
    appends an explicit PRIOR CYCLE flag: a reset has happened since this
    correction was logged, so any cycle-specific number it cites (a baseline
    weight, a genesis date) needs re-verifying rather than re-asserting forever
    as a standing fact (the core #1791 defect).
    """
    created_at = item.get("created_at")
    date_str = created_at[:10] if isinstance(created_at, str) and len(created_at) >= 10 else None
    cycle = item.get("cycle")

    parts = []
    if date_str:
        parts.append(f"logged {date_str}")
    if cycle is not None:
        parts.append(f"cycle {cycle}")
    if not parts:
        return ""

    stamp = "(" + ", ".join(parts) + ")"
    if cycle is not None and current_cycle is not None and int(cycle) != int(current_cycle):
        stamp += " [PRIOR CYCLE — a reset has happened since; re-verify any cited number before treating it as current]"
    return stamp


def render_corrections_block(corrections: list, *, current_cycle: Optional[int] = None) -> str:
    """Pure: render scoped, bounded, newest-first corrections into a compact
    "PRIOR CORRECTIONS — DO NOT REPEAT" prompt block.

    Empty input -> "" (no block, no padded placeholder — honest-when-empty, the
    same convention as the journal-signals / presence blocks). Each line carries
    the error-CLASS tag so the model suppresses the class, not just the one line,
    plus (#1791) a provenance stamp — WHEN it was logged and, if known, which
    experiment cycle — so a correction can no longer read as a fact that has
    always been true and always will be. `current_cycle` (typically
    `coach_checkin.read_cycle()`) lets a row from a superseded cycle carry an
    explicit re-verify flag instead of silently re-asserting forever.
    """
    if not corrections:
        return ""
    lines = [
        "PRIOR CORRECTIONS — DO NOT REPEAT (Matthew corrected these exact error classes in past reviews of YOUR"
        " output; do not reproduce any of them in this generation. Treat each as a standing constraint on the "
        "error PATTERN — but a line flagged PRIOR CYCLE was logged before a subsequent experiment reset, so "
        "verify any specific number it cites is still current before repeating it):",
    ]
    for c in corrections:
        cls = c.get("error_class", "other")
        txt = (c.get("correction_text") or "").strip()
        stamp = _provenance_stamp(c, current_cycle=current_cycle)
        prefix = f"- [{cls}] {stamp}".rstrip() if stamp else f"- [{cls}]"
        lines.append(f"{prefix} {txt}" if txt else prefix)
    return "\n".join(lines)


def corrections_prompt_block(
    table,
    *,
    surface: Optional[str] = None,
    coach: Optional[str] = None,
    limit: int = PROMPT_MEMORY_MAX_PER_COACH,
    current_cycle: Optional[int] = None,
) -> str:
    """Convenience: fetch (open, scoped, newest-first, bounded) + render in one
    call. Returns "" when there is nothing to inject for this coach/surface.

    `current_cycle` (#1791) defaults to `coach_checkin.read_cycle()` (cached per
    warm container, fail-soft None) so the rendered block can flag any open
    correction logged before the most recent experiment reset. Pass it explicitly
    to avoid the SSM read (e.g. from a caller that already resolved it).
    """
    if current_cycle is None:
        current_cycle = read_cycle()
    opened = open_corrections_for(table, surface=surface, coach=coach, limit=limit)
    return render_corrections_block(opened, current_cycle=current_cycle)


# ── #1791 — the review-on-reset primitive ─────────────────────────────────────
# The rendered PRIOR-CYCLE flag (above) keeps a stale number from silently
# re-asserting itself INSIDE a coach's prompt. This is the companion read for a
# human- or ops-facing surface (a future review-pack section, or an ad-hoc MCP
# query) to actually clear the backlog: which still-open corrections were logged
# before the current cycle and may need a manual `update_status` / re-date. Not
# wired into any scheduled job by this story — `correction_promotion.py` stays
# strictly read-only per its own docstring, and a write-side "supersede on
# reset" step is a bigger, separate change; this is the reusable building block.
def stale_cycle_corrections(corrections: list, *, current_cycle: Optional[int]) -> list:
    """Pure: the subset of (typically open, `list_corrections`-shaped) `corrections`
    stamped with a `cycle` strictly OLDER than `current_cycle` — i.e. logged before
    the most recent experiment reset.

    A correction with no `cycle` (pre-#1791, or a write that couldn't reach SSM) is
    NEVER flagged — absence of provenance is not evidence of staleness, it's just
    missing data. `current_cycle=None` -> [] (nothing can be judged stale without a
    reference point to compare against).
    """
    if current_cycle is None:
        return []
    out = []
    for c in corrections:
        cyc = c.get("cycle")
        if cyc is not None and int(cyc) < int(current_cycle):
            out.append(c)
    return out
