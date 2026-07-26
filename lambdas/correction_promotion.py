"""correction_promotion.py — S6 pattern-extraction → gate-promotion PROPOSALS
(#1698, epic #1687 "The Coach Correction Loop", Path 3).

Prompt-memory (S5, #1697) SOFTENS a recurring error class; a deterministic gate
(like the S4 baseline-freshness gate, #1691) ELIMINATES it. This module is the
periodic analysis that watches the corrections ledger (#1689,
`lambdas/coach_corrections.py`), clusters recurring error classes, and PROPOSES
which classes have recurred enough to graduate from prompt-memory → a hard
deterministic gate.

Governance is HUMAN and stays human (ADR-104/105):
  * This module is STRICTLY READ-ONLY over the ledger. It contains NO write
    path of any kind — no put_item / update_item / delete_item / update_status
    call exists anywhere in this file, and a regression test
    (tests/test_correction_promotion.py) source-scans the module to keep it
    that way. A proposal NEVER flips a gate on.
  * Promotion itself is a human-authored gate PR (exactly like S4/#1691 was).
    This module only identifies and proposes; Matthew signs off (or doesn't)
    from the weekly AI review pack, where the proposals surface
    (`lambdas/emails/ai_review_pack_lambda.py`, #1594).

The clustering is deliberately SIMPLE and DETERMINISTIC — computed-before-any-
LLM per ADR-105; no Bedrock call is made (or needed) anywhere in this module:
  * Cluster key = exact `error_class` match. The free-form "other" class is
    sub-clustered by its preserved raw label (`error_class_raw`, see #1689's
    normalization) so a recurring UNRECOGNIZED class still surfaces, while
    unrelated free-form corrections don't lump into one false cluster.
  * Recurrence = number of DISTINCT corrected items in the cluster, where
    distinctness is the normalized `item_ref` (lower-cased, whitespace-stripped
    key/value pairs; empty ref falls back to the correction's own sk). Logging
    the same correction twice therefore counts ONCE — recurrence measures how
    often the ERROR recurred, not how often Matthew typed.
  * Threshold (named constants below, the #1698-locked defaults): a class
    proposes when it recurred ≥ PROMOTION_MIN_RECURRENCE (3) times across
    ≥ PROMOTION_MIN_COACHES (2) distinct coaches. The cross-coach requirement
    is what separates "one coach has a quirk" (prompt-memory's job) from "the
    class is systemic" (a gate's job).
  * Statuses counted: "open" and "applied-to-prompt" — graduation is FROM
    prompt-memory TO a gate, so prompt-applied corrections still count.
    "applied-to-gate" corrections are excluded: their class already graduated.
  * The no-correction-needed tags ("hedged-safe", "defense-held") never
    propose — they record that a generation HELD UP, not an error.

Runs weekly alongside (inside) the review-pack Lambda — no new schedule, no new
Lambda, no CDK change. Bundled at lambdas/ root (#781 — one bundle, no layer).

v1.0.0 — 2026-07-25 (#1698)
"""

from __future__ import annotations

from typing import Optional

from coach_corrections import list_corrections

# ── The #1698-locked promotion thresholds (documented in the module docstring) ──
# A class proposes for gate-promotion when it recurred at least this many times…
PROMOTION_MIN_RECURRENCE = 3
# …across at least this many DISTINCT coaches (systemic, not one coach's quirk).
PROMOTION_MIN_COACHES = 2
# At most this many example refs ride each proposal (newest-first).
MAX_EXAMPLE_REFS = 3

# The "no correction needed" tags — they record a generation that held up, never
# an error, so they can never be promotion candidates.
NON_PROMOTABLE_CLASSES = ("hedged-safe", "defense-held")

# Statuses that count toward recurrence. "applied-to-gate" is deliberately
# absent: those corrections' class already graduated to a gate.
COUNTED_STATUSES = ("open", "applied-to-prompt")

# The coach label used when a correction's item_ref carries no coach.
UNSPECIFIED_COACH = "(unspecified)"


def _class_key(item: dict) -> str:
    """The deterministic cluster key for one correction: its exact `error_class`,
    except the free-form "other" class is sub-clustered by the preserved raw
    label so unrelated free-form corrections never lump into one false cluster
    (and a recurring unrecognized class still surfaces under its own name)."""
    cls = str(item.get("error_class") or "other")
    if cls == "other":
        raw = str(item.get("error_class_raw") or "").strip().lower()
        if raw:
            return f"other:{raw}"
    return cls


def normalize_item_ref(ref: Optional[dict]) -> tuple:
    """Normalize an `item_ref` for similarity: a sorted tuple of lower-cased,
    whitespace-stripped (key, value) string pairs, dropping empty values. Two
    refs that differ only in case/whitespace/key order normalize equal. An
    empty/missing ref normalizes to () — callers fall back to the correction's
    own sk so distinct ref-less corrections still count separately."""
    if not ref:
        return ()
    pairs = []
    for k, v in ref.items():
        if v is None:
            continue
        v_str = str(v).strip().lower()
        if not v_str:
            continue
        pairs.append((str(k).strip().lower(), v_str))
    return tuple(sorted(pairs))


def _coach_label(item: dict) -> str:
    """The correction's coach, normalized (lower-cased/stripped). Missing coach →
    UNSPECIFIED_COACH — one shared bucket, so ref-less corrections can never
    fabricate the cross-coach spread on their own."""
    ref = item.get("item_ref") or {}
    coach = str(ref.get("coach") or "").strip().lower()
    return coach or UNSPECIFIED_COACH


def cluster_corrections(corrections: list) -> dict:
    """PURE: cluster ledger corrections by error class. Returns
    {class_key: {"error_class", "recurrence", "coaches", "example_refs"}}.

    Recurrence counts DISTINCT normalized item_refs (fallback: the correction's
    sk), so re-logging the same correction never inflates recurrence. Only
    COUNTED_STATUSES rows participate; NON_PROMOTABLE_CLASSES are skipped.
    Deterministic: no LLM, no randomness, no wall-clock (ADR-105).
    """
    clusters: dict = {}
    # Newest-first by sk (CORRECTION#<date>#<id8>) so example refs are the most
    # recent evidence — deterministic regardless of input order.
    for item in sorted(corrections, key=lambda i: str(i.get("sk", "")), reverse=True):
        if item.get("status") not in COUNTED_STATUSES:
            continue
        cls = str(item.get("error_class") or "other")
        if cls in NON_PROMOTABLE_CLASSES:
            continue
        key = _class_key(item)
        dedupe = normalize_item_ref(item.get("item_ref")) or ("sk", str(item.get("sk", "")))
        c = clusters.setdefault(
            key,
            {"error_class": key, "recurrence": 0, "coaches": set(), "example_refs": [], "_seen": set()},
        )
        if dedupe in c["_seen"]:
            continue  # same corrected item logged again — the ERROR did not recur
        c["_seen"].add(dedupe)
        c["recurrence"] += 1
        c["coaches"].add(_coach_label(item))
        if len(c["example_refs"]) < MAX_EXAMPLE_REFS:
            c["example_refs"].append(str(item.get("sk", "")))
    for c in clusters.values():
        c.pop("_seen")
        c["coaches"] = sorted(c["coaches"])
    return clusters


def promotion_proposals(
    corrections: list,
    *,
    min_recurrence: int = PROMOTION_MIN_RECURRENCE,
    min_coaches: int = PROMOTION_MIN_COACHES,
) -> list:
    """PURE: the S6 analysis. Cluster the ledger and return gate-promotion
    PROPOSALS — one dict per class whose recurrence crossed the threshold:

        {"error_class": str,          # the cluster key
         "recurrence": int,           # distinct corrected items
         "coaches": [str, ...],       # sorted distinct coach labels
         "coach_count": int,
         "example_refs": [sk, ...],   # newest-first, ≤ MAX_EXAMPLE_REFS
         "statement": str}            # the human-readable proposal line

    Sorted most-recurrent first (ties: class name). A one-off correction never
    proposes; a single-coach class never proposes (min_coaches). This function
    PROPOSES ONLY — it has no side effects and nothing downstream of it
    auto-promotes (ADR-104/105; promotion is a human-authored gate PR).
    """
    out = []
    for c in cluster_corrections(corrections).values():
        if c["recurrence"] < min_recurrence:
            continue
        # UNSPECIFIED_COACH is one shared bucket; it counts as (at most) one
        # "coach" toward the spread — documented, deterministic.
        if len(c["coaches"]) < min_coaches:
            continue
        proposal = dict(c)
        proposal["coach_count"] = len(c["coaches"])
        proposal["statement"] = (
            f"class `{c['error_class']}` recurred {c['recurrence']} times across "
            f"{len(c['coaches'])} coaches → candidate for a hard deterministic gate"
        )
        out.append(proposal)
    out.sort(key=lambda p: (-p["recurrence"], p["error_class"]))
    return out


def gate_promotion_proposals(
    table,
    *,
    min_recurrence: int = PROMOTION_MIN_RECURRENCE,
    min_coaches: int = PROMOTION_MIN_COACHES,
    limit: int = 10000,
) -> list:
    """The weekly entrypoint (called from the review-pack Lambda): read the
    ledger via `coach_corrections.list_corrections` and run the pure analysis.

    STRICTLY READ-ONLY — the only table method this path ever invokes is
    `query` (inside list_corrections). It never writes, never transitions a
    correction's status, never flips a gate (ADR-104/105).
    """
    corrections = list_corrections(table, limit=limit)
    return promotion_proposals(corrections, min_recurrence=min_recurrence, min_coaches=min_coaches)
