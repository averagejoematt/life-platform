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
    change in any part changes the digest.

    #2889 — PASS STRUCTURE, NOT RENDERED PROSE. `canonicalize()` strips bookkeeping
    by dict KEY, so a part handed in as an already-rendered string (a prompt with
    `json.dumps(brief)` baked into it) carries every volatile key straight into the
    digest and the whole `_VOLATILE_KEYS` mechanism becomes a no-op. That is exactly
    what the only production call site did from ADR-126 until 2026-08-22: the digest
    covered `json.dumps(brief)` text containing `generation_date`, so it changed
    every single day and `GenerationSkippedUnchanged` was never once emitted.
    """
    canon = [canonicalize(p) for p in parts]
    blob = json.dumps(canon, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def brief_parts(system_prompt, brief, domain_data, trends, data_inventory, corrections) -> dict:
    """The named semantic parts of a coach daily-brief generation (#2889).

    The NAMES live here, not at the call site, so a caller cannot quietly drop or
    rename one — dropping a part narrows the fingerprint, which is the direction
    that could serve stale output as fresh.
    """
    return {
        "system_prompt": system_prompt,
        "brief": brief,
        "domain_data": domain_data,
        "trends": trends,
        "data_inventory": data_inventory,
        "corrections": corrections,
    }


def check_reuse_or_explain(table, coach_id: str, output_type: str, parts: dict):
    """Fingerprint `parts`, try reuse, and on a MISS say which part changed.

    Returns `(fingerprint, reused_output_or_None, unchanged_since_or_None)`.

    THIS IS THE ENTRY POINT CALLERS SHOULD USE (#2889). It exists so the caller
    hands over STRUCTURE and never a rendered prompt — see `brief_fingerprint` for
    what that mistake cost — and so the miss reason lives with the cache rather than
    at each call site. `lambdas/ai/ai_calls.py` is baselined by the #1665 module-size
    guard, and the guard was right: this logic belongs here.

    The miss line is a `print`, deliberately not a dimensioned metric — #2837 is an
    open finding about 743 EMF series across 35 namespaces, and a per-coach
    miss-reason dimension would have added ~40 more for a diagnostic that a log
    search answers just as well.
    """
    fingerprint = brief_fingerprint(parts)
    entry = load_entry(table, coach_id, output_type)
    if entry and entry.get("brief_hash") == fingerprint and entry.get("output"):
        return fingerprint, entry["output"], entry.get("first_generated")
    diff = changed_parts((entry or {}).get("part_hashes") or {}, part_fingerprints(parts))
    print(f"[GEN-CACHE-MISS:{coach_id}] {output_type} regenerating — parts changed: {', '.join(diff) or 'none (first run)'}")
    return fingerprint, None, None


def part_fingerprints(parts: dict) -> dict:
    """Per-part digests, so a MISS can say WHICH part changed (#2889).

    The skip-rate was unmeasurable in the bad direction: the metric only fires on a
    hit, so "never emitted" could not distinguish "the inputs genuinely change every
    day" from "the fingerprint is computed wrong". Storing a digest per named part
    turns the next miss into a named diff, at zero CloudWatch cost — deliberately a
    log line rather than a dimensioned metric, because #2837 is an open finding about
    743 EMF series and this would have added another 40.
    """
    return {name: brief_fingerprint(value) for name, value in parts.items()}


def changed_parts(stored: dict, current: dict) -> list:
    """Names of parts whose digest differs, sorted. Parts absent from `stored` (an
    entry written before per-part digests existed) are reported as `?<name>` rather
    than silently counted as unchanged — an unknown must not read as a match."""
    if not stored:
        return ["<no part digests stored>"]
    out = []
    for name, digest in sorted(current.items()):
        if name not in stored:
            out.append(f"?{name}")
        elif stored[name] != digest:
            out.append(name)
    return out


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


def store_entry(table, coach_id: str, output_type: str, fingerprint: str, output: str, today: str, parts: dict | None = None) -> bool:
    """Persist a freshly generated, gate-passed output under its brief fingerprint.
    Reached only on a cache MISS, so `first_generated` resets the unchanged-since
    clock. Pass the same `parts` dict the fingerprint came from (#2889) and the
    per-part digests are stored alongside, so the NEXT miss names what changed
    instead of leaving the miss reason unmeasurable. Best-effort."""
    try:
        part_hashes = part_fingerprints(parts) if parts else None
        item = {
            "pk": CACHE_PK,
            "sk": cache_sk(coach_id, output_type),
            "brief_hash": fingerprint,
            "output": output,
            "first_generated": today,
            "last_generated": today,
            "reuse_count": 0,
        }
        if part_hashes:
            item["part_hashes"] = part_hashes
        table.put_item(Item=item)
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
