#!/usr/bin/env python3
"""tests/contain_publication_route_walk.py — walk every site-API GET handler against a table
that holds the owner-register ai_analysis rows and the coaches' private confidence state
(#5607, owner ruling 2026-11-03, item 5), in a fresh interpreter.

Run by `tests/test_contain_publication_5607.py` as a subprocess, so the handlers'
module-level caches never carry the fixture into (or out of) the rest of the suite. The
wiring (boto3/S3/HTTP/Bedrock dead, every `web.*` table binding re-pointed) is the #4972
walk's (`tests/rhythm_route_walk.py`); only the table and the leak test differ.

The table holds, at their REAL keys:
  * one `USER#matthew#SOURCE#ai_analysis` / `EXPERT#<short>` row per operational coach,
    every prose field (analysis, key_recommendation, journaling_prompt, elena_quote)
    carrying the sentinel `AIPROSESENTINEL`;
  * per coach, `STANCE#latest` + one dated `STANCE#` snapshot whose `confidence_note`
    carries `POSTERIORSENTINEL` and the posterior-shaped number 0.123457, and a
    `CONFIDENCE#sleep` Beta row (alpha / beta / mean_confidence 0.123457);
  * one open `ENSEMBLE#docket` bet whose frozen stakes carry `confidence: 0.123457`.

A query answers the rows of the partition it asked for, narrowed by its sort-key
condition when that is `=` or `begins_with` (over-inclusive when it cannot be read); a
get_item answers only its exact key; a scan answers everything.

A response LEAKS when its body carries a sentinel, the posterior number, or a key named
`confidence_note` / `mean_confidence` / `alpha` / `beta` / `posterior`; and, for
/api/ai_analysis, any of the four prose keys at all. Prints one JSON document.

`--plant` is the mutation control: it re-adds the three removed fields (the prose on
/api/ai_analysis, `confidence_note` on the stance, the stake `confidence` on the docket)
and the test asserts the walk catches each one.
"""

from __future__ import annotations

import json
import os
import sys
from decimal import Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
# The content filter fails CLOSED without a vocabulary (the docket would serve nothing and
# the walk would be blind to it). Under pytest the conftest's neutral vocabulary is
# inherited; run by hand, the same neutral terms stand in (never the real, private ones).
os.environ.setdefault("CONTENT_FILTER_JSON", json.dumps({"blocked_vices": ["No fizzlewick"], "blocked_vice_keywords": ["fizzlewick"]}))

import rhythm_route_walk as rw  # noqa: E402 — sets the env + lambdas/ path, owns the wiring
from coach.persona_registry import OPERATIONAL_COACH_IDS, OPERATIONAL_SHORT_IDS  # noqa: E402

PROSE = "AIPROSESENTINEL"
POSTERIOR = "POSTERIORSENTINEL"
POSTERIOR_NUMBER = "0.123457"
STANCE_READ = "STANCEREADSENTINEL"  # non-vacuity: the stance WAS read and served
DOCKET_BRIER = "0.271828"  # non-vacuity: the docket stake WAS read and served
AI_META_DAY = "2026-10-31"  # non-vacuity: the EXPERT# row WAS read (its data_through)

AI_PROSE_KEYS = ("analysis", "key_recommendation", "journaling_prompt", "elena_quote")
PRIVATE_KEYS = ("confidence_note", "mean_confidence", "alpha", "beta", "posterior")
SENTINELS = (PROSE, POSTERIOR, POSTERIOR_NUMBER)


def _rows() -> list:
    rows = []
    for short in sorted(OPERATIONAL_SHORT_IDS):
        rows.append(
            {
                "pk": "USER#matthew#SOURCE#ai_analysis",
                "sk": f"EXPERT#{short}",
                "expert_key": short,
                "analysis": f"Your week, {short}: {PROSE} you should hold protein high.",
                "key_recommendation": f"{PROSE} keep your bedtime fixed",
                "journaling_prompt": f"{PROSE} what did you notice?",
                "elena_quote": f"{PROSE} he held the line",
                "generated_at": "2026-11-02T10:00:00+00:00",
                "data_through": AI_META_DAY,
                "week_number": Decimal("1"),
                "days_in_experiment": Decimal("1"),
            }
        )
    stance = {
        "headline_read": f"Matthew is {STANCE_READ} holding a steady week.",
        "focused_on_now": ["sleep timing"],
        "set_aside_for_now": ["body weight"],
        "stage": {"label": "Holding steady", "rationale": "The week held."},
        "how_my_read_changed": "The read held from last week.",
        "confidence_note": f"{POSTERIOR} protein confidence remains low ({POSTERIOR_NUMBER}).",
        "evidence_basis": ["sleep"],
        "as_of": "2026-11-01",
    }
    for cid in OPERATIONAL_COACH_IDS:
        rows.append({"pk": f"COACH#{cid}", "sk": "STANCE#latest", **stance})
        rows.append({"pk": f"COACH#{cid}", "sk": "STANCE#2026-11-01", **stance})
        rows.append(
            {
                "pk": f"COACH#{cid}",
                "sk": "CONFIDENCE#sleep",
                "subdomain": "sleep",
                "alpha": Decimal("3"),
                "beta": Decimal("4"),
                "mean_confidence": Decimal(POSTERIOR_NUMBER),
                "sample_size": Decimal("5"),
            }
        )
    a, b = "sleep_coach", "physical_coach"
    stake = {"brier": Decimal(DOCKET_BRIER), "brier_n": Decimal("14"), "confidence": Decimal(POSTERIOR_NUMBER), "subdomain": "sleep"}
    rows.append(
        {
            "pk": "ENSEMBLE#docket",
            "sk": f"OPEN#{a}#{b}#sleep",
            "record_type": "dispute_docket",
            "status": "open",
            "topic": "Whether deep sleep rises",
            "topic_slug": "deep-sleep",
            "coach_a": a,
            "coach_b": b,
            "claims": {a: "Deep sleep rises by the 20th.", b: "Deep sleep stays flat."},
            "criterion": {
                "metric": "deep_sleep_hours",
                "condition": "above",
                "threshold": Decimal("1.5"),
                "description": "deep sleep above 1.5 h",
            },
            "sides": {a: True, b: False},
            "resolution_date": "2026-11-20",
            "opened_date": "2026-11-01",
            "stakes": {a: dict(stake), b: dict(stake)},
            "subdomain": "sleep",
        }
    )
    return rows


FIXTURE_ROWS = _rows()


def _requested_sk(kce, eav):
    """('eq'|'prefix', value) for a readable sort-key condition, else None (over-inclusive)."""
    if isinstance(kce, str):
        import re

        m = re.search(r"begins_with\(\s*([#\w]+)\s*,\s*(:\w+)\s*\)", kce)
        if m and m.group(1) in ("sk", "#sk"):
            return ("prefix", (eav or {}).get(m.group(2)))
        m = re.search(r"\b(sk|#sk)\s*=\s*(:\w+)", kce)
        if m:
            return ("eq", (eav or {}).get(m.group(2)))
        return None
    get_expr = getattr(kce, "get_expression", None)
    if get_expr is None:
        return None
    expr = get_expr()
    op, values = expr.get("operator"), expr.get("values") or ()
    if op == "AND":
        for v in values:
            got = _requested_sk(v, eav)
            if got is not None:
                return got
        return None
    if len(values) == 2 and getattr(values[0], "name", None) == "sk":
        if op == "begins_with":
            return ("prefix", values[1])
        if op == "=":
            return ("eq", values[1])
    return None


class ContainTable(rw.RhythmTable):
    """The #4972 fake table over this fixture, with the sort-key condition honoured."""

    def _rows(self, pk=None, sk=None):
        rows = [dict(r) for r in FIXTURE_ROWS]
        if pk is not None:
            rows = [r for r in rows if r["pk"] == pk]
        if sk is not None:
            rows = [r for r in rows if r["sk"] == sk]
        return rows

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ExpressionAttributeNames=None, IndexName=None, **kw):
        out = super().query(
            KeyConditionExpression=KeyConditionExpression,
            ExpressionAttributeValues=ExpressionAttributeValues,
            ExpressionAttributeNames=ExpressionAttributeNames,
            IndexName=IndexName,
            **kw,
        )
        cond = None if IndexName else _requested_sk(KeyConditionExpression, ExpressionAttributeValues)
        if cond and cond[1] is not None:
            kind, val = cond
            items = [r for r in out["Items"] if (r["sk"] == val if kind == "eq" else str(r["sk"]).startswith(str(val)))]
            out = {"Items": items, "Count": len(items)}
        return out


def _keys(obj, acc):
    if isinstance(obj, dict):
        for k, v in obj.items():
            acc.add(k)
            _keys(v, acc)
    elif isinstance(obj, list):
        for v in obj:
            _keys(v, acc)
    return acc


def _plant():
    """Re-add each removed field — the three regressions the guard exists to catch."""
    from web import site_api_coach, site_api_coach_ledger, site_api_coach_narrative, site_api_coach_stance

    real_withheld = site_api_coach_narrative._ai_analysis_withheld

    def withheld_with_prose(expert_key, item=None, **extra):
        body = real_withheld(expert_key, item, **extra)
        body["analysis"] = (item or {}).get("analysis")
        return body

    site_api_coach_narrative._ai_analysis_withheld = withheld_with_prose

    real_stance = site_api_coach_stance._stance_from_latest

    def stance_with_note(latest):
        out = real_stance(latest)
        out["confidence_note"] = latest.get("confidence_note")
        return out

    site_api_coach_stance._stance_from_latest = stance_with_note
    site_api_coach._stance_from_latest = stance_with_note  # the facade's _g is what handlers read
    site_api_coach_ledger.STAKE_PRIVATE_FIELDS = ()


# Every routed path, plus the per-coach and per-expert variants the bare walk cannot name.
def _requests(L):
    reqs = [(p, {}) for p in rw.route_paths(L)]
    reqs += [(f"/api/coach/{cid}", {}) for cid in OPERATIONAL_COACH_IDS]
    reqs += [("/api/ai_analysis", {"expert": s}) for s in sorted(OPERATIONAL_SHORT_IDS)]
    reqs += [("/api/coach_analysis", {"domain": s}) for s in sorted(OPERATIONAL_SHORT_IDS)]
    reqs += [("/api/coach_timeline", {"coach_id": cid}) for cid in OPERATIONAL_COACH_IDS]
    return reqs


def walk(plant: bool = False) -> dict:
    rw.RhythmTable = ContainTable  # rw._wire builds its table by this name
    L, _table = rw._wire()
    if plant:
        _plant()
    result = {"routes": 0, "answered": 0, "raised": {}, "leaks": {}, "seen": {}}
    for path, qs in _requests(L):
        result["routes"] += 1
        event = {
            "rawPath": path,
            "path": path,
            "httpMethod": "GET",
            "requestContext": {"http": {"method": "GET"}},
            "headers": {},
            "queryStringParameters": dict(qs),
        }
        key = path + ("?" + "&".join(f"{k}={v}" for k, v in qs.items()) if qs else "")
        try:
            resp = L._dispatch_route(event, path, "GET")
            if resp is None and callable(L.ROUTES.get(path)):
                resp = L.ROUTES[path]()
        except Exception as e:  # noqa: BLE001 — a handler that raises served nothing
            result["raised"][key] = type(e).__name__
            continue
        if not isinstance(resp, dict):
            continue
        result["answered"] += 1
        raw = resp.get("body")
        try:
            body = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except ValueError:
            body = {}
        blob = raw if isinstance(raw, str) else json.dumps(body, default=str)
        keys = _keys(body, set())
        hits = sorted({t for t in SENTINELS if t in blob} | {f"key:{k}" for k in PRIVATE_KEYS if k in keys})
        if path == "/api/ai_analysis":
            hits += sorted(f"key:{k}" for k in AI_PROSE_KEYS if k in keys)
            result["seen"][key] = {"state": body.get("state"), "data_through": body.get("data_through")}
        if hits:
            result["leaks"][key] = hits
        for marker in (STANCE_READ, DOCKET_BRIER):
            if marker in blob:
                result["seen"].setdefault(marker, []).append(key)
    return result


if __name__ == "__main__":
    import io
    import logging

    logging.disable(logging.CRITICAL)
    _real_stdout = sys.stdout
    sys.stdout = io.StringIO()  # handlers print; keep stdout for the one JSON line
    try:
        out = walk(plant="--plant" in sys.argv)
        out["queries"] = rw.STATS["queries"]
        out["unparsed_queries"] = rw.STATS["unparsed_queries"]
    finally:
        sys.stdout = _real_stdout
    print(json.dumps(out))
