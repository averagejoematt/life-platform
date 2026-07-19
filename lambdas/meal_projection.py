"""Idempotent projection writer for the derived meal layer (`macrofactor_meals`).

Writes ONLY to `SOURCE#macrofactor_meals` — it NEVER mutates the raw
`SOURCE#macrofactor` partition (Invariant 1; guarded by tests/test_meal_projection.py
and a runtime pk assertion). Upsert is keyed on a stable ordinal so re-running a day
(backfill or `regroup_day`) never duplicates, and stale higher-ordinal rows from a
prior grouping are pruned.

Bundled module (#781): used by both `deploy/backfill_meals.py` (local) and the
`manage_meals` MCP tool's `regroup_day` action (Lambda). `table` is injected so the
module needs no AWS client of its own and stays unit-testable.
"""

from datetime import datetime, timezone
from decimal import Decimal

from boto3.dynamodb.conditions import Key
from meal_grouper import group_day
from meal_templates_seed import ALGO_VERSION

MEALS_SOURCE = "macrofactor_meals"
RAW_SOURCE = "macrofactor"  # never written — provenance guard target

try:
    from numeric import floats_to_decimal
except ImportError:  # pragma: no cover - layer always provides numeric

    def floats_to_decimal(obj):
        if isinstance(obj, bool):
            return obj
        if isinstance(obj, float):
            return Decimal(str(obj))
        if isinstance(obj, dict):
            return {k: floats_to_decimal(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [floats_to_decimal(i) for i in obj]
        return obj


def meals_pk(user="matthew"):
    return f"USER#{user}#SOURCE#{MEALS_SOURCE}"


def raw_pk(user="matthew"):
    return f"USER#{user}#SOURCE#{RAW_SOURCE}"


def _ordinal_key(g):
    tw = g.get("time_window") or {}
    return (tw.get("start") or "99:99", g.get("signature") or "")


def build_meal_items(date, groups, user="matthew", now_iso=None):
    """Build the DDB items for a day. Ordinal = time order (stable, 1-based).
    sk = DATE#YYYY-MM-DD#MEAL#<NN>. Stamps algo_version + signature + cached rollup."""
    pk = meals_pk(user)
    now_iso = now_iso or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = []
    for i, g in enumerate(sorted(groups, key=_ordinal_key), 1):
        items.append(
            {
                "pk": pk,
                "sk": f"DATE#{date}#MEAL#{i:02d}",
                "date": date,
                "source": MEALS_SOURCE,
                "ordinal": i,
                "meal_name": g["meal_name"],
                "template_id": g.get("template_id"),
                "kind": g["kind"],  # meal | snack | uncategorized
                "method": g["method"],
                "inferred": True,
                "confidence": g["confidence"],
                "signature": g["signature"],
                "time_window": g.get("time_window") or {},
                "member_refs": g.get("member_refs") or [],
                "sides": g.get("sides") or [],
                "rollup": g.get("rollup") or {},
                "algo_version": g.get("algo_version", ALGO_VERSION),
                "ingested_at": now_iso,
            }
        )
    return items


def _existing_meal_sks(table, date, user="matthew"):
    pk = meals_pk(user)
    sks, kwargs = [], {
        "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(f"DATE#{date}#MEAL#"),
        "ProjectionExpression": "sk",
    }
    while True:
        r = table.query(**kwargs)
        sks += [it["sk"] for it in r.get("Items", [])]
        if "LastEvaluatedKey" not in r:
            break
        kwargs["ExclusiveStartKey"] = r["LastEvaluatedKey"]
    return sks


def write_day_projection(table, date, groups, user="matthew", dry_run=False, now_iso=None):
    """Idempotent upsert of one day's meal projection. Prunes stale ordinals from a
    prior, larger grouping. Returns a summary dict. Writes nothing when dry_run=True."""
    items = build_meal_items(date, groups, user=user, now_iso=now_iso)
    new_sks = {it["sk"] for it in items}
    existing = set(_existing_meal_sks(table, date, user=user))
    stale = sorted(existing - new_sks)
    result = {
        "date": date,
        "meals": len(items),
        "stale_pruned": len(stale),
        "wrote": 0,
        "deleted": 0,
        "dry_run": dry_run,
        "items": items,
        "stale_sks": stale,
    }
    if dry_run:
        return result

    pk = meals_pk(user)
    for it in items:
        # Provenance guard (Invariant 1): only ever write the meals partition.
        assert it["pk"] == pk, f"meal_projection refused to write non-meals pk: {it['pk']!r}"
        table.put_item(Item=floats_to_decimal(it))
        result["wrote"] += 1
    for sk in stale:
        table.delete_item(Key={"pk": pk, "sk": sk})
        result["deleted"] += 1
    return result


def project_day(table, date, entries, user="matthew", dry_run=False, now_iso=None, vocab=None, templates=None):
    """Convenience: group a day's raw food_log and upsert its projection.
    group_day asserts conservation internally (raises on any reconcile failure)."""
    groups = group_day(entries, vocab=vocab, templates=templates)
    res = write_day_projection(table, date, groups, user=user, dry_run=dry_run, now_iso=now_iso)
    res["groups"] = groups
    return res
