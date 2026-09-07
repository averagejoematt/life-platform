"""mcp/tools_surfaces.py — the index and the waiter (#3668).

TWO TOOLS, NOT FIFTY-NINE
-------------------------
59 owner-relevant site-API endpoints had no MCP tool. The obvious fix — one tool each —
is the wrong one: the 2026-07-08 prune took the surface 143 → 60 *because* an oversized
tool list degrades selection (``docs/MCP_TOOL_AUDIT.md``), and rebuilding toward 135
re-creates exactly the problem that prune solved. So:

  ``describe_platform_surfaces()``  — the index. What can I ask, and what does each
                                      surface's answer MEAN?
  ``get_platform_surface(name, …)`` — the waiter. Fetch any indexed surface.

Named tools stay for the handful asked constantly (``mcp/tools_platform.py``): a named
tool is more discoverable than an index lookup, and those questions get asked daily. The
index carries the long tail.

THE PART THAT MATTERS MORE THAN COVERAGE
----------------------------------------
Every response from the waiter carries the surface's **governing rule** next to its data
— the phase filter applied, the date basis, and whether row provenance is distinguished
at all. That is not decoration. On 2026-09-06 a careful assistant read a technically
correct payload off five different surfaces and drew three wrong conclusions from it,
because in each case the rule that produced the payload was invisible. Coverage would
have prevented none of them. See ``mcp/surface_index.py`` for the specimen table.

An unanswerable request writes a miss record (``mcp/miss_log.py``) before it returns.

READ-ONLY BY CONSTRUCTION
-------------------------
The waiter dispatches through ``site_api_lambda._dispatch_route`` — the single exit point
#2876 established — with a synthetic GET event. It never constructs its own DynamoDB
query, so it cannot read anything the public site could not, and a POST-only route is
excluded by derivation before dispatch is ever reached.

Payloads pass through the SAME Tier-2 declaration ``mcp/tools_data.py`` reads
(``privacy.field_tiers.strip_map``) rather than a second copy of the ruling: a generic
pass-through is precisely the "dump the row" shape #2809 caught handing owner-only
withings fields into conversation context, and the fix is one declaration with many
readers, never a re-implementation.
"""

from __future__ import annotations

import difflib
import json
from typing import Any

from mcp import miss_log, surface_index
from mcp.config import logger

# The strip set is DERIVED from lambdas/privacy/field_tiers.py — the same call
# mcp/tools_data.py makes. Never a literal here (#2803/#2809).
try:
    from privacy.field_tiers import TIER_OWNER_ONLY, fields_at_tier

    _OWNER_ONLY_FIELDS = frozenset(fields_at_tier(TIER_OWNER_ONLY))
except Exception:  # noqa: BLE001 — a missing declaration must not open the gate
    _OWNER_ONLY_FIELDS = frozenset()
    logger.warning("[#3668] privacy.field_tiers unavailable — the waiter will refuse to serve rather than serve unstripped")

_PRIVACY_UNAVAILABLE = not _OWNER_ONLY_FIELDS


def _strip_owner_only(node: Any, removed: set) -> Any:
    """Recursively drop Tier-2 owner-only field names from a served payload.

    Only ever REMOVES keys already present — never invents, renames or adds one (the
    ``_strip_tier2`` contract). Keyed on the field NAME because a pass-through payload
    has no `source` column to key on; that is strictly more conservative than the
    per-source strip, so it fails closed.
    """
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            if k in _OWNER_ONLY_FIELDS:
                removed.add(k)
                continue
            out[k] = _strip_owner_only(v, removed)
        return out
    if isinstance(node, list):
        return [_strip_owner_only(v, removed) for v in node]
    return node


def _dispatch(path: str, params: dict, method: str = "GET"):
    """Fetch one surface through the site API's single dispatch exit point."""
    from web import site_api_lambda as _L  # lazy: heavy import, only the waiter pays

    event = {
        "rawPath": path,
        "path": path,
        "httpMethod": method,
        "requestContext": {"http": {"method": method, "sourceIp": "127.0.0.1"}},
        "queryStringParameters": {str(k): str(v) for k, v in (params or {}).items()},
        "headers": {},
    }
    return _L._dispatch_route(event, path, method)


def _vintage_of(payload: dict) -> dict:
    """What the envelope itself says about WHEN — never inferred, only reported.

    ``_meta.content_as_of`` present means the handler ASSERTED a stored vintage;
    absent means it declares none, which is "unknown", never "fresh" (#1971).
    """
    meta = payload.get("_meta") if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        return {"declared": False, "note": "This surface's envelope carries no _meta block — its vintage is UNKNOWN, not fresh."}
    out = {
        "declared": True,
        "served_at": meta.get("served_at"),
        "generated_at": meta.get("generated_at"),
        "content_as_of": meta.get("content_as_of"),
        "degraded": meta.get("degraded"),
    }
    if meta.get("content_as_of") is None:
        out["note"] = "No content_as_of declared: generated_at is the ASSEMBLY instant, not a claim that the content is current."
    return out


# ═══════════════════════════════════════════════════════════════════════════
# describe_platform_surfaces — the index
# ═══════════════════════════════════════════════════════════════════════════
def tool_describe_platform_surfaces(args=None):
    """Every surface the platform can answer from, with the rule each one applies."""
    args = args or {}
    keyword = (args.get("keyword") or "").lower().strip()
    include_excluded = bool(args.get("include_excluded"))
    detail = bool(args.get("detail"))
    limit = args.get("limit")
    if not isinstance(limit, int) or limit < 1:
        limit = 200
    limit = min(limit, 300)

    index = surface_index.cached_index()
    rows = []
    for name in sorted(index):
        entry = index[name]
        if not entry["owner_relevant"] and not include_excluded:
            continue
        if keyword and keyword not in (name + " " + entry["question"] + " " + entry.get("example_phrasing", "")).lower():
            continue
        row = {
            "name": name,
            "path": entry["path"],
            "question": entry["question"],
            "example_phrasing": entry["example_phrasing"],
            "params": entry["params"],
            "annotated": entry["annotated"],
            "owner_relevant": entry["owner_relevant"],
        }
        if not entry["owner_relevant"]:
            row["excluded_reason"] = entry["excluded_reason"]
        else:
            rule = entry["rule"]
            row["default_filter"] = rule["phase_filter"]
            row["default_filter_meaning"] = rule["phase_filter_meaning"]
            row["unfiltered_view"] = rule["unfiltered_view"]
            row["date_basis"] = rule["date_basis"]
            row["row_provenance"] = rule["row_provenance"]
            if detail:
                row["derived_from"] = rule["derived_from"]
                row["phase_read_counts"] = rule["phase_read_counts"]
        rows.append(row)

    reachable = surface_index.reachable(index)
    filters: dict[str, int] = {}
    for e in reachable.values():
        filters[e["rule"]["phase_filter"]] = filters.get(e["rule"]["phase_filter"], 0) + 1
    undeclared_provenance = sum(1 for e in reachable.values() if e["rule"]["row_provenance"].startswith("undeclared"))

    return {
        "how_to_use": (
            "Pick a `name` and call get_platform_surface(name=...). Read `default_filter` BEFORE reporting an "
            "empty result: 'experiment-only' means pre-genesis and prior-cycle rows are hidden ON PURPOSE, so "
            "an empty answer is 'excluded by a rule you asked for', never 'the platform does not hold it'."
        ),
        "index_is_derived": (
            "This list is AST-derived from site_api_lambda's route tables (deploy/endpoint_registry.py, the same "
            "walk the doc-sync and the schema-completeness gate use). A route shipped today appears here today, "
            "with `annotated: false` until someone writes its plain-English question."
        ),
        "counts": {
            "routes_discovered": len(index),
            "reachable": len(reachable),
            "excluded": len(index) - len(reachable),
            "annotated": sum(1 for e in reachable.values() if e["annotated"]),
            "by_default_filter": filters,
            "provenance_undeclared": undeclared_provenance,
        },
        "known_gap": (
            f"{undeclared_provenance} of {len(reachable)} reachable surfaces do not distinguish live capture from "
            "backfilled history. A 2026-05 bulk import and a live day look identical on those surfaces — say so "
            "rather than inferring data loss from a gap."
        ),
        "surfaces": rows[:limit],
        "truncated": len(rows) > limit,
        "total_matching": len(rows),
    }


# ═══════════════════════════════════════════════════════════════════════════
# get_platform_surface — the waiter
# ═══════════════════════════════════════════════════════════════════════════
def tool_get_platform_surface(args=None):
    """Fetch one indexed surface, with the rule it applied attached to the answer."""
    args = args or {}
    raw_name = (args.get("name") or "").strip()
    name = surface_index.surface_name(raw_name) if raw_name.startswith("/api/") else raw_name.strip("/")
    params = args.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    question = args.get("question") or ""

    index = surface_index.cached_index()

    if not name:
        rec = miss_log.record_miss(
            reason=miss_log.REASON_UNANSWERED_QUESTION, question=question, params=params, detail="no surface name supplied"
        )
        return {"error": "name is required — call describe_platform_surfaces() for the list.", "miss_recorded": rec}

    entry = index.get(name)
    if entry is None:
        near = difflib.get_close_matches(name, list(index), n=5, cutoff=0.5)
        rec = miss_log.record_miss(
            reason=miss_log.REASON_NO_SUCH_SURFACE, asked_for=name, question=question, params=params, near_misses=near
        )
        return {
            "error": f"No surface named {name!r}.",
            "honest_framing": "No surface exposes this. That is a statement about the TOOL SURFACE, not about whether the platform holds the fact.",
            "did_you_mean": near,
            "miss_recorded": rec,
        }

    if not entry["owner_relevant"]:
        rec = miss_log.record_miss(
            reason=miss_log.REASON_READER_ONLY, asked_for=name, question=question, params=params, detail=entry["excluded_reason"]
        )
        return {
            "error": f"{name!r} is indexed but deliberately not served through this tool.",
            "excluded_reason": entry["excluded_reason"],
            "honest_framing": "This surface EXISTS and is excluded on purpose — a different answer from 'no such surface'.",
            "miss_recorded": rec,
        }

    if _PRIVACY_UNAVAILABLE:
        return {"error": "privacy.field_tiers is unavailable; refusing to serve an unstripped payload (fail closed)."}

    path = entry["path"]
    if entry["is_prefix"]:
        suffix = str(params.pop("path_suffix", "") or "").strip("/")
        if not suffix:
            return {"error": f"{name!r} is a prefix route — supply params.path_suffix (e.g. 'sleep_coach')."}
        path = path.rstrip("/") + "/" + suffix

    try:
        resp = _dispatch(path, params)
    except Exception as e:  # noqa: BLE001 — a handler blowing up is a MISS, and misses are recorded
        rec = miss_log.record_miss(
            reason=miss_log.REASON_SURFACE_ERROR, asked_for=name, question=question, params=params, detail=str(e)[:400]
        )
        return {"error": f"{name!r} raised: {str(e)[:300]}", "rule": entry["rule"], "miss_recorded": rec}

    if not isinstance(resp, dict):
        rec = miss_log.record_miss(
            reason=miss_log.REASON_UNROUTED,
            asked_for=name,
            question=question,
            params=params,
            detail=f"router returned {type(resp).__name__}",
        )
        return {"error": f"{name!r} is indexed but the router did not answer {path!r}.", "rule": entry["rule"], "miss_recorded": rec}

    status = int(resp.get("statusCode", 0) or 0)
    try:
        payload = json.loads(resp.get("body") or "{}")
    except Exception:  # noqa: BLE001
        payload = {"_unparseable_body": str(resp.get("body"))[:500]}

    if status >= 400:
        rec = miss_log.record_miss(
            reason=miss_log.REASON_SURFACE_ERROR, asked_for=name, question=question, params=params, detail=f"HTTP {status}"
        )
        return {"surface": name, "path": path, "status": status, "rule": entry["rule"], "data": payload, "miss_recorded": rec}

    removed: set = set()
    payload = _strip_owner_only(payload, removed)

    out = {
        "surface": name,
        "path": path,
        "status": status,
        "question_this_answers": entry["question"],
        # THE POINT OF #3668: the rule travels with the data, always, on every response.
        "rule": entry["rule"],
        "vintage": _vintage_of(payload),
        "privacy": {
            "rule": "Tier-2 owner-only fields are stripped from this generic pass-through (the #2809 'dump the row' rule).",
            "declaration": "lambdas/privacy/field_tiers.py",
            "fields_removed": sorted(removed),
        },
        "data": payload,
    }
    if params:
        out["params_applied"] = params

    against = args.get("explain_against")
    if against:
        other = surface_index.surface_name(against) if str(against).startswith("/api/") else str(against).strip("/")
        out["reconciliation"] = surface_index.explain_discrepancy(name, other, index)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# The caller-declared miss — a question with no candidate surface at all
# ═══════════════════════════════════════════════════════════════════════════
def record_unanswered(question: str, detail: str = "") -> dict | None:
    """Record a question no surface could answer. Used by the named tools and available
    to any caller that has exhausted the index — the cycle-number question vanished
    because nothing had this shape to call."""
    index = surface_index.cached_index()
    near = difflib.get_close_matches((question or "").lower(), list(index), n=5, cutoff=0.4)
    return miss_log.record_miss(reason=miss_log.REASON_UNANSWERED_QUESTION, question=question, near_misses=near, detail=detail)
