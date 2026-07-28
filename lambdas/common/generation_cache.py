"""
generation_cache.py — hash a coach generation brief and reuse the last gated
output when nothing semantic changed (#738, ADR-126).

During quiet stretches the daily coach narratives regenerate from near-identical
canonical facts + thread-state — paying full Sonnet generation (plus the grounding
and quality gates) to re-say the same silence. This module lets the coach-v2
pipeline skip that whole path when the exact semantic inputs are unchanged from
the last successful generation, reusing the stored gate-passed text instead. It's
likely the single biggest recurring AI saving on a low-signal day.

THE HONESTY INVARIANT (load-bearing — do not weaken):
  The fingerprint covers EVERY semantic input, so any change — a new vitals number,
  a stance update, even a staleness day-count ticking up — busts the cache and
  forces a fresh generation. Reuse can only ever return text that was generated
  from byte-identical semantic inputs; there is no stale-but-claiming-fresh path.

We strip ONLY pure bookkeeping before hashing: keys starting with "_" (the
orchestrator's documented internal-bookkeeping convention — grounding_flag,
_generated_at, _fallback, …) and an explicit set of timestamp keys. The strip
list is deliberately CONSERVATIVE because the failure modes are asymmetric:
  - a MISSED strip (a volatile key left in) merely busts a match that could have
    reused → we regenerate → no savings, but no harm;
  - an OVER-EAGER strip (a semantic key removed) could serve stale output as if
    fresh → the one failure this feature must never introduce.
So when unsure, we keep the field in the hash.

Bundled into every function's deploy package (#781 retired the shared layer).
"""

import hashlib
import json
from decimal import Decimal

# One row per (coach, output_type); overwritten on each real generation, so the
# partition never grows. A dedicated SOURCE keeps it clear of coach history.
CACHE_PK = "USER#matthew#SOURCE#coach_gen_cache"

# Pure bookkeeping keys that change run-to-run without changing meaning. Kept tiny
# and explicit (see the asymmetry note above). `_`-prefixed keys are stripped by
# convention regardless of this set.
_VOLATILE_KEYS = frozenset(
    {
        "as_of",
        "generated_at",
        "created_at",
        "last_checked",
        "computed_at",
        "run_id",
        "timestamp",
        "generation_date",
        "first_generated",
        "last_generated",
        "last_reused",
        "reuse_count",
    }
)


def cache_sk(coach_id: str, output_type: str) -> str:
    return f"COACH#{coach_id}#{output_type}"


def _is_bookkeeping(key) -> bool:
    return isinstance(key, str) and (key.startswith("_") or key in _VOLATILE_KEYS)


def canonicalize(obj):
    """Recursively drop bookkeeping keys so the fingerprint tracks only semantic
    content. List order is preserved (order can be semantic). Decimals are folded
    to float so a value read back from DDB (Decimal) fingerprints the same as the
    freshly-computed float — otherwise the cache would never match in practice."""
    if isinstance(obj, dict):
        return {k: canonicalize(v) for k, v in obj.items() if not _is_bookkeeping(k)}
    if isinstance(obj, (list, tuple)):
        return [canonicalize(v) for v in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


def brief_fingerprint(*parts) -> str:
    """SHA-256 hex over the canonicalized semantic inputs. Deterministic across
    runs: dict keys are sorted, Decimals/dates are stringified. Any semantic
    change in any part changes the digest."""
    canon = [canonicalize(p) for p in parts]
    blob = json.dumps(canon, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ── DDB helpers — all fail-soft: any error degrades to "regenerate", never raises.


def load_entry(table, coach_id: str, output_type: str):
    """Return the cached entry dict, or None on miss / any error."""
    try:
        resp = table.get_item(Key={"pk": CACHE_PK, "sk": cache_sk(coach_id, output_type)})
        return resp.get("Item")
    except Exception as e:  # noqa: BLE001
        print(f"[GEN-CACHE] load failed for {coach_id}/{output_type}: {e}")
        return None


def check_reuse(table, coach_id: str, output_type: str, fingerprint: str):
    """If the last successful generation used a byte-identical semantic brief,
    return (stored_output, unchanged_since_date). Else (None, None)."""
    entry = load_entry(table, coach_id, output_type)
    if entry and entry.get("brief_hash") == fingerprint and entry.get("output"):
        return entry["output"], entry.get("first_generated")
    return None, None


def store_entry(table, coach_id: str, output_type: str, fingerprint: str, output: str, today: str) -> bool:
    """Persist a freshly generated, gate-passed output under its brief fingerprint.
    Reached only on a cache MISS, so `first_generated` resets the unchanged-since
    clock. Best-effort."""
    try:
        table.put_item(
            Item={
                "pk": CACHE_PK,
                "sk": cache_sk(coach_id, output_type),
                "brief_hash": fingerprint,
                "output": output,
                "first_generated": today,
                "last_generated": today,
                "reuse_count": 0,
            }
        )
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[GEN-CACHE] store failed for {coach_id}/{output_type}: {e}")
        return False


def record_reuse(table, coach_id: str, output_type: str, today: str) -> None:
    """Bump reuse bookkeeping on a cache hit (last_reused + reuse_count). Best-effort;
    a failure here never blocks serving the reused output."""
    try:
        table.update_item(
            Key={"pk": CACHE_PK, "sk": cache_sk(coach_id, output_type)},
            UpdateExpression="SET last_reused = :d ADD reuse_count :one",
            ExpressionAttributeValues={":d": today, ":one": 1},
        )
    except Exception as e:  # noqa: BLE001
        print(f"[GEN-CACHE] reuse bookkeeping failed for {coach_id}/{output_type}: {e}")


def emit_skip_metric(cw, namespace: str, coach_id: str) -> None:
    """Emit LifePlatform/AI::GenerationSkippedUnchanged{Coach} = 1 so the
    regenerations-skipped/day rate is visible in the spend attribution. Non-fatal."""
    try:
        cw.put_metric_data(
            Namespace=namespace,
            MetricData=[
                {
                    "MetricName": "GenerationSkippedUnchanged",
                    "Dimensions": [{"Name": "Coach", "Value": coach_id}],
                    "Value": 1,
                    "Unit": "Count",
                }
            ],
        )
    except Exception as e:  # noqa: BLE001
        print(f"[GEN-CACHE] skip-metric emit failed (non-fatal): {e}")
