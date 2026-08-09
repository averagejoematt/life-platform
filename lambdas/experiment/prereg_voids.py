"""prereg_voids.py — the pre-registered-bet void ledger (#1199 / #1978).

Every open bet the platform makes (weekly HYPOTHESIS# rows, coach PREDICTION# rows)
is EXPERIMENT_SCOPED: a reset tombstones it, which hides it from every phase-filtered
read forever. ADR-077 only sanctions that because the outcome is supposed to survive
in the CROSS_PHASE calibration ledger — so at reset, an open bet must be written out
as `voided_at_reset` before it is hidden (#1199), and NOTHING may end up hidden and
unresolved (#1978, the invariant in phase_taxonomy.find_unvoided_open_bets).

This module owns the DynamoDB side of that contract — the bet/void-row shapes, the
raw (no-phase-filter) reads, and the write — for both consumers:

  * deploy/restart_pipeline.py       — voids the CLOSING cycle's live bets at reset
  * deploy/reconcile_prereg_voids.py — one-time backfill of the historical orphans

The key algebra (what identifies a bet in the ledger, what an sk looks like, when the
invariant is breached) deliberately lives in phase_taxonomy, next to the rest of the
ADR-077 reset semantics, so all three callers assert the identical rule.

Extracted from restart_pipeline.py by #1978 (byte-identical logic apart from the sk
fix); the pipeline was at the module-size ceiling and this block is a cohesive whole.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from experiment import phase_taxonomy as taxonomy

REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"

# The CROSS_PHASE calibration ledger (phase_taxonomy: "calibration" = cross_phase)
# and the two open-bet partitions the reset would otherwise vanish ungraded.
CALIBRATION_PK = f"USER#{USER}#SOURCE#calibration"
HYPOTHESES_PK = f"USER#{USER}#SOURCE#hypotheses"

# Coaches that can carry open PREDICTION# bets. Derived from the canonical persona
# registry (#2334; guard: tests/test_coach_roster_set_guard_2334.py) — NOT from
# coach_prediction_evaluator, to keep the reset tools free of the evaluator's heavy
# lambda-bundle imports (same posture as restart_pipeline.bust_lambda_warm_cache;
# persona_registry itself is stdlib + common.repo_config, no boto3 at import).
from coach.persona_registry import OPERATIONAL_COACH_IDS

VOID_COACH_IDS = tuple(OPERATIONAL_COACH_IDS)


def open_table(table=None):
    """The life-platform table handle (lazy boto3 import: the pure helpers above are
    importable, and unit-testable, with no AWS in the room)."""
    if table is not None:
        return table
    import boto3

    return boto3.resource("dynamodb", region_name=REGION).Table(TABLE)


def to_ddb_decimal(obj: Any) -> Any:
    """floats → Decimal for DynamoDB (boto3 rejects float). Leaves ints/Decimals as-is."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    if isinstance(obj, dict):
        return {k: to_ddb_decimal(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_ddb_decimal(v) for v in obj]
    return obj


def query_all(table, pk: str, sk_prefix: str) -> list:
    """Paginate a begins_with(sk) query into a flat list. String KeyConditionExpression
    (like restart_intelligence_wipe / coach_prediction_evaluator) so the read is trivial
    to fake in a unit test."""
    items: list = []
    kwargs = {
        "KeyConditionExpression": "pk = :pk AND begins_with(sk, :skp)",
        "ExpressionAttributeValues": {":pk": pk, ":skp": sk_prefix},
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        lek = resp.get("LastEvaluatedKey")
        if not lek:
            break
        kwargs["ExclusiveStartKey"] = lek
    return items


def _is_open_untombstoned(item: dict) -> bool:
    """An OPEN bet the wipe has not already archived — the set THIS reset must void.

    Already-tombstoned rows are out of scope here by design: they belong to a PRIOR
    cycle and must not be re-voided under this closing cycle's stamp. #1978 removed
    the *assumption* that they therefore already carry a void row (they did not —
    a whole pre-#1199 backlog plus a same-genesis sk clobber escaped); that claim is
    now PROVED after the void step by assert_prereg_ledger_complete()."""
    return not item.get("tombstone") and taxonomy.is_open_bet(item)


def collect_open_bets(table, include_tombstoned: bool = False) -> list:
    """Every still-open pre-registered bet: hypotheses (USER#…#SOURCE#hypotheses /
    HYPOTHESIS#) + coach predictions (COACH#<id> / PREDICTION#). Raw reads (NO phase
    filter) so we see the closing cycle's live bets before the tagger/wipe hides them.
    Returns [(kind, item), …] where kind is 'hypothesis' | 'prediction'.

    `include_tombstoned=True` returns the archived ones too — the population the
    #1978 ledger invariant is asserted over (and the reconcile script's input)."""
    keep = taxonomy.is_open_bet if include_tombstoned else _is_open_untombstoned
    bets: list = []
    for h in query_all(table, HYPOTHESES_PK, "HYPOTHESIS#"):
        if keep(h):
            bets.append(("hypothesis", h))
    for coach_id in VOID_COACH_IDS:
        for p in query_all(table, f"COACH#{coach_id}", "PREDICTION#"):
            if keep(p):
                bets.append(("prediction", p))
    return bets


def collect_all_bets(table) -> list:
    """Every pre-registered bet regardless of status or tombstone — the population the
    reconcile script censuses (it must SEE the graded/live ones to report them, not just
    the orphans). Raw reads, no phase filter."""
    bets: list = [("hypothesis", h) for h in query_all(table, HYPOTHESES_PK, "HYPOTHESIS#")]
    for coach_id in VOID_COACH_IDS:
        bets.extend(("prediction", p) for p in query_all(table, f"COACH#{coach_id}", "PREDICTION#"))
    return bets


def count_unvoided_open_bets(table) -> int:
    """Read-only orphan count: open + tombstoned + no calibration void row."""
    voids = query_all(table, CALIBRATION_PK, "CALIB#")
    return len(taxonomy.find_unvoided_open_bets(collect_open_bets(table, include_tombstoned=True), voids))


def assert_prereg_ledger_complete(table) -> int:
    """#1978 post-void regression guard: after void_open_bets_at_reset, NOTHING may be
    open+tombstoned+unvoided. Read-only; returns the orphan count (0 = healthy) and
    raises ValueError naming the breach via the taxonomy registry."""
    voids = query_all(table, CALIBRATION_PK, "CALIB#")
    return taxonomy.assert_no_unvoided_open_bets(collect_open_bets(table, include_tombstoned=True), voids)


def build_void_calib_item(kind: str, bet: dict, genesis: str, closing_cycle, now_iso: str) -> dict:
    """One CROSS_PHASE calibration-ledger row recording that an open pre-registered bet
    was VOIDED (never graded) by the reset.

    outcome='voided_at_reset' is deliberately NOT Brier-scorable
    (calibration_core.outcome_to_binary → None), so it never distorts the calibration
    curve — it keeps the accountability record without pretending the bet resolved. The
    sk comes from taxonomy.void_row_sk: keyed on genesis + kind + id + a digest of the
    bet's own registration stamp, because slugs repeat across cycles (#1978)."""
    common = {
        "outcome": "voided_at_reset",
        "status_at_reset": bet.get("status"),
        "voided_at_reset": True,
        "voided_at": now_iso,
        "reset_genesis": genesis,
        "cycle": closing_cycle,
    }
    bet_id = taxonomy.bet_id_of(kind, bet)
    sk = taxonomy.void_row_sk(genesis, kind, bet)
    if kind == "hypothesis":
        item = {
            "pk": CALIBRATION_PK,
            "sk": sk,
            "record_type": "hypothesis_void",
            "hypothesis_id": bet_id,
            "hypothesis": bet.get("hypothesis", ""),
            "stated_confidence": bet.get("confidence", "low"),
            "predicted_direction": (bet.get("test_spec") or {}).get("direction"),
            "pre_registered_at": taxonomy.bet_registered_at(kind, bet),
            **common,
        }
    else:  # prediction
        item = {
            "pk": CALIBRATION_PK,
            "sk": sk,
            "record_type": "prediction_void",
            "prediction_id": bet_id,
            "coach_id": bet.get("coach_id") or "",
            "claim": bet.get("claim_natural") or bet.get("claim") or "",
            "stated_confidence": bet.get("confidence"),
            "subdomain": bet.get("subdomain"),
            "pre_registered_at": taxonomy.bet_registered_at(kind, bet),
            **common,
        }
    return {k: v for k, v in item.items() if v is not None}


def void_open_bets_at_reset(target_date: str, closing_cycle, apply: bool, table=None) -> int:
    """#1199: BEFORE the tagger/wipe (the first sub-scripts) hide the closing cycle's
    derived intelligence, stamp one 'voided_at_reset' row per OPEN pre-registered bet
    (hypotheses + coach predictions) into the CROSS_PHASE calibration ledger.

    ADR-077 justifies tombstoning hypotheses/predictions by promising 'graded outcomes
    live in the CROSS_PHASE calibration ledger' — but the wipe only adds a tombstone, it
    never changes status, so an open bet goes phase-hidden while still 'pending' and the
    weekly engine (which reads with_phase_filter, ADR-058) can NEVER re-see it to grade
    it. Every reset therefore silently dropped accountability for every open bet
    (violating ADR-105 rule 2: no prediction surface may be write-only). This closes it.

    Idempotent (sk keyed on genesis; already-tombstoned bets skipped). Returns the count
    of void rows — planned in dry-run, written under --apply. Reads are raw/no-phase-
    filter and read-only; the WRITE is --apply-gated like every other pipeline step."""
    table = open_table(table)
    now_iso = datetime.now(timezone.utc).isoformat()
    bets = collect_open_bets(table)
    if apply:
        for kind, bet in bets:
            item = build_void_calib_item(kind, bet, target_date, closing_cycle, now_iso)
            table.put_item(Item=to_ddb_decimal(item))
    return len(bets)
