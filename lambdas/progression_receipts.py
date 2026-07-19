"""
progression_receipts.py — audit-grade receipts for every XP/level change (#1373).

Every character-sheet compute day persists ONE receipt alongside the sheet:
the exact per-pillar transition inputs the engine judged (previous state, the
EMA level score, the raw-day gate values, coverage, presence, bonus XP), the
outputs those inputs produced (level/tier/streaks/XP/events), the keys of the
DynamoDB rows that fed the compute, the engine formula version, a hash of the
S3 config, and a deterministic replay digest over all of it.

The contract (issue #1373 acceptance criteria):
  1. the receipt stores contributing input-row KEYS + formula version +
     config hash + a replay digest — never copies of raw rows;
  2. deterministic replay of the stored inputs through the live engine
     (character_engine.evaluate_level_changes / pillar_xp_transition /
     _roll_xp_buffer — the SAME functions the nightly compute runs, never a
     reimplementation) reproduces the digest; a mismatch is drift:
       - config_drift  — the S3 config hash changed since the receipt
       - engine_drift  — character_engine.ENGINE_VERSION changed
       - a mismatch with NEITHER flag is real nondeterminism → alarm
     (the compute lambda self-verifies at write time and emits the
     ReceiptReplayMismatch EMF metric; qa_smoke replays the recent window
     nightly and reds the report on a true mismatch);
  3. /api/character_receipt serves the receipt (verify=1 replays server-side)
     for the /data/character/ drill-down;
  4. ADR-104: no receipt is ever fabricated — a record with no captured
     transitions (sick-day freeze, pre-#1373 history) yields None, and the
     endpoint answers available=false for dates with no stored receipt.

Storage: USER#matthew#SOURCE#character_receipt / DATE#{YYYY-MM-DD} —
classified EXPERIMENT_SCOPED in lambdas/phase_taxonomy.py (follows
character_sheet), documented in docs/SCHEMA.md.

Numbers are stored at FULL float precision (floats_to_decimal with no
rounding): Decimal(str(x)) round-trips a Python float exactly, so a replay
from the stored item feeds the engine bit-identical inputs and the digest is
reproducible — a precision-rounded copy would not be.

v1.0.0 — 2026-07-19 (#1373)
"""

from __future__ import annotations

import hashlib
import json
import logging
from decimal import Decimal
from typing import Any, Optional

logger = logging.getLogger(__name__)

RECEIPT_SCHEMA_VERSION = 1

# The digest covers exactly these receipt fields, in canonical JSON.
_DIGEST_FIELDS = ("date", "engine_version", "receipt_schema_version", "config_hash", "input_rows", "transitions")

_EMF_NAMESPACE = "LifePlatform/Character"


# ==============================================================================
# CANONICALIZATION + HASHING
# ==============================================================================


def _norm(obj: Any) -> Any:
    """Canonical value normalization so build-time and replay-from-DDB agree.

    DynamoDB returns every number as Decimal; build time sees int/float. Both
    sides normalize to: bool → bool, integral number → int, else float. Tuples
    become lists. This makes canonical_json() identical across the round trip.
    """
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, Decimal):
        f = float(obj)
        return int(f) if f.is_integer() else f
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return int(obj) if obj.is_integer() else obj
    if isinstance(obj, dict):
        return {str(k): _norm(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_norm(v) for v in obj]
    return obj


def canonical_json(obj: Any) -> str:
    """Deterministic JSON: normalized values, sorted keys, no whitespace."""
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def config_hash(config: dict) -> str:
    """Fingerprint of the FULL engine config (canonical JSON) — any knob change
    (weight, band, streak gate, target) changes the hash, which is exactly the
    drift the receipt exists to expose.

    #1411: the effect-fit annotations (fit_status / fit_n_eff / fit_ci_95 /
    fit_badge / …) are normalized OUT before hashing. They are runtime-merged
    evidence metadata about the config, not scoring knobs — they change no
    computed number (modifiers, XP, levels are all fit-blind), and the compute
    path merges the latest quarterly fit into the config it hands the engine,
    so hashing them would make every replay against the pristine S3 config a
    spurious config_drift and roll the hash each quarter with zero mechanical
    change."""
    cfg = config or {}
    effects = cfg.get("cross_pillar_effects")
    if isinstance(effects, list):
        cfg = dict(cfg)
        cfg["cross_pillar_effects"] = [
            (
                {k: v for k, v in e.items() if not (isinstance(k, str) and (k.startswith("fit_") or k == "fitted_at"))}
                if isinstance(e, dict)
                else e
            )
            for e in effects
        ]
    return sha256_hex(canonical_json(cfg))


def digest_of(receipt: dict) -> str:
    """The replay digest: sha256 over the canonical digest-covered fields."""
    return sha256_hex(canonical_json({k: receipt.get(k) for k in _DIGEST_FIELDS}))


# ==============================================================================
# BUILD
# ==============================================================================


def build_receipt(record: dict, config: dict, input_rows: Optional[list] = None) -> Optional[dict]:
    """Build the day's receipt from a computed character-sheet record.

    Returns None when the record carries no captured transitions (sick-day
    freeze, pre-#1373 engine) — a receipt is NEVER fabricated for a change
    with no recorded inputs (ADR-104).
    """
    transitions = record.get("progression_transitions")
    if not transitions or not transitions.get("pillars"):
        return None
    receipt = {
        "date": record.get("date"),
        "engine_version": record.get("engine_version"),
        "receipt_schema_version": RECEIPT_SCHEMA_VERSION,
        "config_hash": config_hash(config),
        "input_rows": _norm(input_rows or []),
        "transitions": _norm(transitions),
        "computed_at": record.get("computed_at"),
    }
    receipt["digest"] = digest_of(receipt)
    return receipt


# ==============================================================================
# REPLAY
# ==============================================================================


def _replay_pillar(pillar: str, transition: dict, config: dict, day_number, engine) -> dict:
    """Re-run ONE pillar's transition from its stored inputs through the SAME
    engine functions the nightly compute uses. Pure + deterministic."""
    ins = transition.get("inputs") or {}
    prev = ins.get("prev")
    level_state = engine.evaluate_level_changes(
        pillar,
        ins.get("level_score"),
        prev,
        config,
        data_coverage=ins.get("data_coverage"),
        raw_score=ins.get("raw_score"),
        unadjusted_level_score=ins.get("unadjusted_level_score"),
        raw_score_unblended=ins.get("raw_score_unblended"),
        presence_dark=bool(ins.get("presence_dark")),
    )
    prev_xp = (prev or {}).get("xp_total", 0) or 0
    prev_debt = (prev or {}).get("xp_debt", 0) or 0
    bonus_xp = ins.get("bonus_xp", 0) or 0
    xp_hold = bool(level_state.get("coverage_hold")) or bool(ins.get("not_instrumented"))
    xp_earned, xp_delta, new_xp, new_debt = engine.pillar_xp_transition(
        ins.get("raw_score"), prev_xp, prev_debt, bonus_xp, xp_hold, config, day_number=day_number
    )
    leveling = config.get("leveling", {}) or {}
    xp_buffer = engine._roll_xp_buffer(
        (prev or {}).get("xp_buffer"),
        prev_xp,
        new_xp,
        leveling.get("xp_per_level", engine.DEFAULT_XP_PER_LEVEL),
        buffer_cap=leveling.get("xp_buffer_cap"),
    )
    return {
        "level": level_state["level"],
        "tier": level_state["tier"],
        "streak_above": level_state["streak_above"],
        "streak_below": level_state["streak_below"],
        "coverage_hold": bool(level_state.get("coverage_hold", False)),
        "xp_earned": xp_earned,
        "xp_delta": xp_delta,
        "xp_total": new_xp,
        "xp_debt": new_debt,
        "xp_buffer": xp_buffer,
        "events": [
            {k: ev.get(k) for k in ("type", "pillar", "old_level", "new_level", "old_tier", "new_tier") if k in ev}
            for ev in level_state.get("events", [])
        ],
    }


def _replay_headline(transitions: dict, replayed_pillars: dict, config: dict) -> dict:
    """Recompute the headline character level from the REPLAYED pillar levels +
    the CURRENT config weights — mirrors compute_character_sheet Step 6 (#960
    renormalization included)."""
    import math

    pillar_cfgs = (config or {}).get("pillars", {})
    weighted = 0.0
    total_w = 0.0
    for name, outs in replayed_pillars.items():
        ins = (transitions.get("pillars", {}).get(name) or {}).get("inputs") or {}
        if bool(ins.get("not_instrumented")) and outs["level"] <= 1:
            continue
        weight = pillar_cfgs.get(name, {}).get("weight", 1.0 / 7)
        weighted += outs["level"] * weight
        total_w += weight
    character_level = max(1, min(100, int(math.floor(weighted / total_w)))) if total_w > 0 else 1
    prev_level = ((transitions.get("headline") or {}).get("inputs") or {}).get("prev_character_level", 1)
    events = []
    if character_level > prev_level:
        events.append({"type": "character_level_up", "old_level": prev_level, "new_level": character_level})
    elif character_level < prev_level:
        events.append({"type": "character_level_down", "old_level": prev_level, "new_level": character_level})
    return {"character_level": character_level, "events": events}


def _diff(pillar: str, stored: Any, replayed: Any, path: str, out: list) -> None:
    """Record leaf-level differences between stored and replayed outputs."""
    stored_n, replayed_n = _norm(stored), _norm(replayed)
    if isinstance(stored_n, dict) and isinstance(replayed_n, dict):
        for k in sorted(set(stored_n) | set(replayed_n)):
            _diff(pillar, stored_n.get(k), replayed_n.get(k), f"{path}.{k}" if path else str(k), out)
        return
    if stored_n != replayed_n:
        out.append({"pillar": pillar, "field": path, "stored": stored_n, "replayed": replayed_n})


def replay(receipt: dict, config: dict, engine=None) -> dict:
    """Deterministically replay a stored receipt against the CURRENT engine +
    config. Returns a provenance-labeled verdict:

      verified       — digest_match AND outputs_match (the AC2 bar; use THIS)
      digest_match   — replayed digest == stored digest. Detects tampered or
                       drifted INPUTS, input_rows, config, engine version —
                       but NOT tampered outputs (the replayed digest is built
                       over the honestly RE-COMPUTED outputs, so a forged
                       stored output leaves both digests agreeing)…
      outputs_match  — …which is why the stored outputs are ALSO compared
                       field-by-field against the recomputation
      config_drift   — the live config hash differs from the stored one
      engine_drift   — ENGINE_VERSION differs from the stored one
      mismatches     — leaf-level stored-vs-replayed output differences

    verified=False with NEITHER drift flag set is real nondeterminism or a
    tampered receipt — the alarm case.
    """
    if engine is None:
        import character_engine as engine  # bundled module (#781)

    receipt = _norm(receipt)
    transitions = receipt.get("transitions") or {}
    day_number = transitions.get("day_number")
    current_hash = config_hash(config)
    current_version = getattr(engine, "ENGINE_VERSION", None)

    replayed_pillars = {}
    mismatches: list = []
    for name, transition in (transitions.get("pillars") or {}).items():
        outs = _replay_pillar(name, transition, config, day_number, engine)
        replayed_pillars[name] = outs
        _diff(name, transition.get("outputs"), outs, "", mismatches)

    replayed_headline = _replay_headline(transitions, replayed_pillars, config)
    _diff("headline", (transitions.get("headline") or {}).get("outputs"), replayed_headline, "", mismatches)

    replayed_transitions = {
        "day_number": day_number,
        "pillars": {
            name: {"inputs": (t.get("inputs") or {}), "outputs": replayed_pillars[name]}
            for name, t in (transitions.get("pillars") or {}).items()
        },
        "headline": {
            "inputs": (transitions.get("headline") or {}).get("inputs") or {},
            "outputs": replayed_headline,
        },
    }
    replayed_digest = digest_of(
        {
            "date": receipt.get("date"),
            "engine_version": current_version,
            "receipt_schema_version": receipt.get("receipt_schema_version"),
            "config_hash": current_hash,
            "input_rows": receipt.get("input_rows"),
            "transitions": replayed_transitions,
        }
    )
    digest_match = replayed_digest == receipt.get("digest")
    return {
        "verified": digest_match and not mismatches,
        "digest_match": digest_match,
        "outputs_match": not mismatches,
        "config_drift": current_hash != receipt.get("config_hash"),
        "engine_drift": current_version != receipt.get("engine_version"),
        "stored_digest": receipt.get("digest"),
        "replayed_digest": replayed_digest,
        "current_config_hash": current_hash,
        "current_engine_version": current_version,
        "mismatches": mismatches,
    }


# ==============================================================================
# STORAGE + TELEMETRY
# ==============================================================================


def store_receipt(table_resource: Any, pk: str, receipt: dict) -> dict:
    """Write the receipt item. Caller passes the full pk (the compute lambda
    builds it as USER_PREFIX + "character_receipt" so the partition has a
    statically-resolvable writer for the orphan gate). Floats convert via the
    canonical helper at FULL precision — see module docstring."""
    from numeric import floats_to_decimal  # bundled shared module (#1207)

    item = {"pk": pk, "sk": "DATE#" + receipt["date"]}
    item.update(floats_to_decimal(_norm(receipt)))
    try:
        from compute_metadata import tag_record

        item = tag_record(item, source_id="character_receipt")
    except ImportError:
        pass
    table_resource.put_item(Item=item)
    return item


def emf_replay_metric_line(*, date: str, mismatch: bool, timestamp_ms: int) -> str:
    """Embedded-Metric-Format line for the write-time self-verify (#1373 AC2).

    Emits ReceiptReplayMismatch (0/1) in LifePlatform/Character on EVERY
    compute run — a structured log line CloudWatch extracts to a metric, no
    put_metric_data call or extra IAM. 1 = the freshly built receipt did not
    replay to its own digest under the same config (nondeterminism)."""
    doc = {
        "_aws": {
            "Timestamp": int(timestamp_ms),
            "CloudWatchMetrics": [
                {
                    "Namespace": _EMF_NAMESPACE,
                    "Dimensions": [[]],  # one empty DimensionSet = an undimensioned metric
                    "Metrics": [{"Name": "ReceiptReplayMismatch"}],
                }
            ],
        },
        "ReceiptDate": date,
        "ReceiptReplayMismatch": 1 if mismatch else 0,
    }
    return json.dumps(doc)
