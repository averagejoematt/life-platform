"""lambdas/flourishing.py — the PERMA fact layer over journal enrichment (#1403).

The Haiku enrichment pass (journal_enrichment_lambda, ADR-104-grounded) computes
values_lived / gratitude / flow / growth_signals / ownership / social_quality
daily — but until #1403 the output lived only as prompt context on the notion
entry records: no partition, no trend, no pillar input. This module is the ONE
projection of those signals into a first-class daily row:

    pk USER#matthew#SOURCE#flourishing · sk DATE#YYYY-MM-DD

Like macrofactor_meals / training_notes (#951) it is a derived FACT layer over
its parent partition — idempotent, never mutates the raw entries, re-derivable
at any time from the stored enrichment. RAW_TIMESERIES class (ADR-077): follows
the notion parent, kept forever, genesis-anchored on read.

Provenance (ADR-104 / #1403 AC): every row stores the enrichment model + schema
version that coded it, and every consumer surfaces "LLM-coded from journal text
(model …)" — these numbers are a language model's reading of prose, and they
must never masquerade as sensor data.
"""

from datetime import datetime, timezone
from decimal import Decimal

FLOURISHING_SOURCE = "flourishing"

# Ordered rungs of the categorical social_quality — mirrors
# character_engine._SOCIAL_QUALITY_RANK (#910) on the same 0-10 scale.
_SOCIAL_RANK = {"alone": 0, "surface": 1, "meaningful": 2, "deep": 3}

# The daily signals a row carries (numeric attrs on the row, EMA-trended by the
# MCP tool). Kept in one tuple so writer/reader/tool can never drift.
SIGNALS = (
    "values_lived_count",
    "gratitude_count",
    "flow",
    "growth_signals_count",
    "ownership_score",
    "social_quality_score",
)


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def social_quality_to_10(raw):
    """alone→0, surface→3.33, meaningful→6.67, deep→10; None on anything else."""
    if not isinstance(raw, str):
        return None
    rank = _SOCIAL_RANK.get(raw.strip().lower())
    if rank is None:
        return None
    return rank / 3 * 10


def aggregate_entries(entries):
    """One day's enriched journal entries → the flourishing row body (pure).

    Returns None when NO entry carries any enrichment (a day without an enriched
    journal is uninstrumented — measured absence, never a zero row). Signals a
    given day's entries don't carry are simply absent from the row (behavioral
    absence stays visible as a missing attribute, per ADR-104).
    """
    enriched = [e for e in entries if e.get("enriched_at")]
    if not enriched:
        return None
    values = []
    gratitude = 0
    flow_any = False
    flow_seen = False
    growth = 0
    ownership = []
    social = []
    for e in enriched:
        for v in e.get("enriched_values_lived") or []:
            if isinstance(v, str) and v.strip() and v.strip().lower() not in [x.lower() for x in values]:
                values.append(v.strip())
        gratitude += len(e.get("enriched_gratitude") or [])
        if "enriched_flow" in e:
            flow_seen = True
            flow_any = flow_any or bool(e.get("enriched_flow"))
        growth += len(e.get("enriched_growth_signals") or [])
        o = _f(e.get("enriched_ownership"))
        if o is not None:
            ownership.append(o)
        s = social_quality_to_10(e.get("enriched_social_quality"))
        if s is not None:
            social.append(s)
    row = {
        "n_entries": len(enriched),
        "values_lived": values,
        "values_lived_count": len(values),
        "gratitude_count": gratitude,
        "growth_signals_count": growth,
    }
    if flow_seen:
        row["flow"] = 1 if flow_any else 0
    if ownership:
        row["ownership_score"] = round(sum(ownership) / len(ownership), 2)
    if social:
        row["social_quality_score"] = round(sum(social) / len(social), 2)
    return row


def write_flourishing_row(table, user_id, date_str, entries, model, schema_version):
    """Aggregate + upsert one day's row. Returns True when a row was written."""
    body = aggregate_entries(entries)
    if body is None:
        return False
    item = {
        "pk": f"USER#{user_id}#SOURCE#{FLOURISHING_SOURCE}",
        "sk": f"DATE#{date_str}",
        "date": date_str,
        "source": "journal_enrichment",
        "enrichment_model": str(model),
        "enrichment_schema_version": Decimal(int(schema_version)),
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    for k, v in body.items():
        if isinstance(v, bool):
            item[k] = v
        elif isinstance(v, (int, float)):
            item[k] = Decimal(str(v))
        else:
            item[k] = v
    table.put_item(Item=item)
    return True


def values_alignment_score(values_count, has_row):
    """The Mind pillar's values_alignment component (#1403).

    A journaled+enriched day with zero values-in-action is a REAL low signal
    (the LLM read the prose and found none) — scored 20, not None and not 0.
    No flourishing row at all → None (uninstrumented day, ADR-104).
    1 value = 60, 2 = 80, 3+ = 100.
    """
    if not has_row or values_count is None:
        return None
    c = int(values_count)
    if c <= 0:
        return 20.0
    return {1: 60.0, 2: 80.0}.get(c, 100.0)


def ema_series(values, span=14):
    """Plain EMA over a chronological list (None-safe: gaps are skipped, the
    smoothing simply carries across them). Returns None on an empty series."""
    alpha = 2.0 / (span + 1.0)
    ema = None
    for v in values:
        f = _f(v)
        if f is None:
            continue
        ema = f if ema is None else alpha * f + (1 - alpha) * ema
    return round(ema, 2) if ema is not None else None


def provenance_line(model):
    """The mandatory consumer-facing provenance string (#1403 AC)."""
    return f"LLM-coded from journal text (model {model})" if model else "LLM-coded from journal text"
