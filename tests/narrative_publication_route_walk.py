#!/usr/bin/env python3
"""tests/narrative_publication_route_walk.py — walk every site-API GET route against a table whose
AI-written narrative rows carry SYNTHETIC paraphrased disclosures, under one provenance variant
(owner ruling 2026-11-03). Run by `tests/test_narrative_publication_gate.py` in a fresh
interpreter so no handler cache carries the fixture into the rest of the suite.

    python3 tests/narrative_publication_route_walk.py --variant private|unrecorded|public [--ungated]

Every narrative row — each coach's OUTPUT# read, STANCE#latest, COMMITMENT#, PREDICTION#, the
lead's LEAD_DAILY#, the board's MOVES# day, the integrator's EXPERT# weekly call, the coach-thread
partition and an open docket bet — holds the same three synthetic sentences, none of which names
the journal (so the #5131 keyword scrub cannot see them):

    "writing stays dark" · "the notebook has gone quiet" · "no entries this week"

The variant sets every row's `provenance`:
  * private    — a known record naming a private family (`journal_presence`);
  * unrecorded — no record at all (every row written before the ruling);
  * public     — a known record naming only public families.

A response LEAKS when it carries any of the three phrases, or the provenance record itself. Prints
one JSON document: routes, answered, raised, leaks, seen (route -> phrases) and the dashboard's
withheld-state markers. `--ungated` unwraps the chokepoint — the negative control: the same walk
must leak (the code before the ruling had no such gate).

The wiring is the #4972 walk's (`tests/rhythm_route_walk.py`: boto3/S3/HTTP/Bedrock dead) with
one difference that matters: module table handles are NOT re-pointed past the chokepoint. boto3
is patched BEFORE any `web.*` import, so `web.site_api_common.table` is the production
`PublicationTable` around the fake, and any module that builds its OWN table reads the raw fake —
exactly as it would in production, where such a read would bypass the gate (and leak here).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from decimal import Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(ROOT, "lambdas"))
os.environ.setdefault("CONTENT_FILTER_JSON", json.dumps({"blocked_vices": ["No fizzlewick"], "blocked_vice_keywords": ["fizzlewick"]}))

import rhythm_route_walk as rw  # noqa: E402 — sets the env; we reuse its fake table + query parser

PHRASES = ("writing stays dark", "the notebook has gone quiet", "no entries this week")
DISCLOSURE = "In this synthetic fixture the subject's writing stays dark, the notebook has gone quiet, and there were no entries this week."
FAMILY_TOKENS = ("npg-fixture-producer",)  # the provenance record itself must never reach the wire
DAY = "2026-11-02"

PROVENANCE = {
    "private": {
        "v": 1,
        "families": ["journal_presence", "whoop"],
        "producer": "npg-fixture-producer",
        "stamped_at": "2026-11-02T12:00:00+00:00",
    },
    "unrecorded": None,
    "public": {
        "v": 1,
        "families": ["whoop", "withings", "persona"],
        "producer": "npg-fixture-producer",
        "stamped_at": "2026-11-02T12:00:00+00:00",
    },
}


def _rows(variant: str) -> list:
    from coach.persona_registry import OPERATIONAL_COACH_IDS

    prov = PROVENANCE[variant]
    rows: list = []
    for cid in OPERATIONAL_COACH_IDS:
        rows.append(
            {
                "pk": f"COACH#{cid}",
                "sk": f"OUTPUT#{DAY}#daily",
                "content": DISCLOSURE,
                "observatory_summary": DISCLOSURE,
                "public_summary": DISCLOSURE,
                "public_ask": DISCLOSURE,
                "key_recommendation": DISCLOSURE,
                "elena_quote": DISCLOSURE,
                "emotional_investment": "invested",
                "created_at": f"{DAY}T12:00:00+00:00",
                "data_through": DAY,
                "predictions": [{"text": DISCLOSURE, "confidence": "medium", "status": "pending"}],
                "themes": ["sleep"],
                "word_count": Decimal("20"),
            }
        )
        rows.append(
            {
                "pk": f"COACH#{cid}",
                "sk": "STANCE#latest",
                "headline_read": DISCLOSURE,
                "focused_on_now": [DISCLOSURE],
                "set_aside_for_now": ["body weight"],
                "stage": {"label": "Holding steady", "rationale": DISCLOSURE},
                "how_my_read_changed": DISCLOSURE,
                "evidence_basis": ["sleep"],
                "as_of": DAY,
            }
        )
        rows.append(
            {
                "pk": f"COACH#{cid}",
                "sk": f"COMMITMENT#{DAY}#c1",
                "status": "pending",
                "text": DISCLOSURE,
                "public_text": DISCLOSURE,
                "date": DAY,
                "due_date": "2026-11-09",
            }
        )
        rows.append(
            {
                "pk": f"COACH#{cid}",
                "sk": f"PREDICTION#{DAY}#p1",
                "prediction_id": f"{cid}-p1",
                "coach_id": cid,
                "claim_natural": DISCLOSURE,
                "claim": DISCLOSURE,
                "status": "pending",
                "confidence": Decimal("0.6"),
                "created_at": f"{DAY}T12:00:00+00:00",
                "date": DAY,
                "target_date": "2026-11-09",
                "metric": "hrv",
            }
        )
        rows.append(
            {
                "pk": f"COACH#{cid}",
                "sk": "PREDICTION#2026-10-20#p0",
                "prediction_id": f"{cid}-p0",
                "coach_id": cid,
                "claim_natural": DISCLOSURE,
                "claim": DISCLOSURE,
                "outcome_notes": DISCLOSURE,
                "status": "refuted",
                "confidence": Decimal("0.7"),
                "created_at": "2026-10-20T12:00:00+00:00",
                "date": "2026-10-20",
                "target_date": "2026-10-27",
                "outcome_date": "2026-10-28",
                "evaluated_at": "2026-10-28T12:00:00+00:00",
                "metric": "hrv",
            }
        )
    rows.append(
        {
            "pk": "COACH#eli_marsh",
            "sk": f"LEAD_DAILY#{DAY}",
            "coach_id": "eli_marsh",
            "text": DISCLOSURE,
            "generated_at": f"{DAY}T12:00:00+00:00",
            "data_through": DAY,
            "cited": [{"metric": "hrv", "value": "50", "as_of": DAY, "source_field": "whoop.hrv"}],
        }
    )
    rows.append(
        {
            "pk": "COACH#eli_marsh",
            "sk": f"MOVES#{DAY}",
            "record_type": "coach_moves",
            "date": DAY,
            "generated_at": f"{DAY}T12:00:00+00:00",
            "lines": [
                {"coach_id": cid, "name": cid, "move": "reply", "text": DISCLOSURE, "date": DAY, "replies_to": None}
                for cid in sorted(OPERATIONAL_COACH_IDS)[:3]
            ],
            "absent": [],
            "silent": [],
        }
    )
    rows.append(
        {
            "pk": "USER#matthew#SOURCE#ai_analysis",
            "sk": "EXPERT#integrator",
            "analysis": DISCLOSURE,
            "public_summary": DISCLOSURE,
            "weekly_priority": DISCLOSURE,
            "generated_at": f"{DAY}T10:00:00+00:00",
            "data_through": DAY,
        }
    )
    for cid in OPERATIONAL_COACH_IDS:
        short = cid.replace("_coach", "")
        rows.append(
            {
                "pk": "USER#matthew",
                "sk": f"SOURCE#coach_thread#{short}#{DAY}",
                "position_summary": DISCLOSURE,
                "open_questions": [DISCLOSURE],
                "date": DAY,
            }
        )
        rows.append(
            {
                "pk": f"COACH#{cid}",
                "sk": f"LEARNING#{DAY}#l1",
                "learning": DISCLOSURE,
                "what_i_learned": DISCLOSURE,
                "summary": DISCLOSURE,
                "date": DAY,
                "created_at": f"{DAY}T12:00:00+00:00",
            }
        )
        rows.append(
            {
                "pk": f"COACH#{cid}",
                "sk": f"THREAD#{DAY}#t1",
                "summary": DISCLOSURE,
                "topic": DISCLOSURE,
                "status": "open",
                "date": DAY,
            }
        )
    for sk in ("EXPERT#integrator_month", "EXPERT#experiment_arc"):
        rows.append(
            {
                "pk": "USER#matthew#SOURCE#ai_analysis",
                "sk": sk,
                "narrative": DISCLOSURE,
                "arc": DISCLOSURE,
                "analysis": DISCLOSURE,
                "generated_at": f"{DAY}T10:00:00+00:00",
            }
        )
    rows.append({"pk": "USER#matthew#SOURCE#state_of_matthew", "sk": f"DATE#{DAY}", "narrative": DISCLOSURE, "date": DAY})
    rows.append(
        {
            "pk": "USER#matthew#SOURCE#field_notes",
            "sk": "WEEK#2026-W45",
            "ai_present": DISCLOSURE,
            "ai_tone": DISCLOSURE,
            "ai_cautionary": DISCLOSURE,
            "ai_affirming": DISCLOSURE,
            "week": "2026-W45",
        }
    )
    rows.append(
        {
            "pk": "USER#matthew#SOURCE#challenges",
            "sk": "CHALLENGE#c1",
            "challenge_id": "c1",
            "name": DISCLOSURE,
            "description": DISCLOSURE,
            "source": "journal_mining",
            "source_detail": DISCLOSURE,
            "status": "active",
            "origin": "live",
        }
    )
    rows.append(
        {
            "pk": "ENSEMBLE#digest",
            "sk": f"CYCLE#{DAY}",
            "coach_summaries": {"sleep_coach": DISCLOSURE},
            "active_disagreements": [{"topic": DISCLOSURE, "positions": {"sleep_coach": DISCLOSURE}}],
            "date": DAY,
        }
    )
    a, b = "sleep_coach", "mind_coach"
    rows.append(
        {
            "pk": "ENSEMBLE#docket",
            "sk": f"OPEN#{a}#{b}#sleep",
            "record_type": "dispute_docket",
            "status": "open",
            "topic": DISCLOSURE,
            "topic_slug": "t1",
            "coach_a": a,
            "coach_b": b,
            "claims": {a: DISCLOSURE, b: DISCLOSURE},
            "criterion": {"metric": "hrv", "condition": "above", "threshold": Decimal("50"), "description": DISCLOSURE},
            "sides": {a: True, b: False},
            "resolution_date": "2026-11-20",
            "opened_date": DAY,
            "subdomain": "sleep",
        }
    )
    if prov is not None:
        for r in rows:
            r["provenance"] = json.loads(json.dumps(prov))
    return rows


class NarrativeTable(rw.RhythmTable):
    rows: list = []

    def _rows(self, pk=None, sk=None):
        out = [json.loads(json.dumps(r, default=str), parse_float=Decimal) for r in self.rows]
        if pk is not None:
            out = [r for r in out if r["pk"] == pk]
        if sk is not None:
            out = [r for r in out if r["sk"] == sk]
        return out

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ExpressionAttributeNames=None, IndexName=None, **kw):
        import contain_publication_route_walk as cw

        out = super().query(
            KeyConditionExpression=KeyConditionExpression,
            ExpressionAttributeValues=ExpressionAttributeValues,
            ExpressionAttributeNames=ExpressionAttributeNames,
            IndexName=IndexName,
            **kw,
        )
        cond = None if IndexName else cw._requested_sk(KeyConditionExpression, ExpressionAttributeValues)
        if cond and cond[1] is not None:
            kind, val = cond
            items = [r for r in out["Items"] if (r["sk"] == val if kind == "eq" else str(r["sk"]).startswith(str(val)))]
            out = {"Items": items, "Count": len(items)}
        return out


def _wire(variant: str, ungated: bool):
    import urllib.request

    import boto3

    NarrativeTable.rows = _rows(variant)
    try:  # owner ruling 2026-11-05: the synthetic calls here are ordinary, publishable calls (reviewed public)
        from call_publication_fixtures import register_reviewed_public

        register_reviewed_public(NarrativeTable.rows)
    except ImportError:  # a checkout from before the call policy (the negative control on origin/main)
        pass
    raw = NarrativeTable()
    boto3.client = lambda *a, **k: rw._DeadClient()  # type: ignore[assignment]

    class _Res:
        def Table(self, _name):  # noqa: N802 — boto3's spelling
            return raw

    boto3.resource = lambda *a, **k: _Res()  # type: ignore[assignment]
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(rw._Dead("http disabled"))  # type: ignore[assignment]

    from web import site_api_common, site_api_lambda as L

    try:
        from web import narrative_publication as NPub
    except ImportError:  # a checkout from before the ruling (the negative control run on origin/main)
        NPub = None
    if NPub is not None and not ungated:
        assert (
            isinstance(site_api_common.table, NPub.PublicationTable) and site_api_common.table.wrapped is raw
        ), "the chokepoint is not installed"
    _gate_type = NPub.PublicationTable if NPub is not None else ()
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or not mod_name.startswith(("web.", "common.", "intelligence.", "health.", "ai.", "coach.")):
            continue
        for attr in ("table", "_table", "TABLE", "ddb_table"):
            cur = getattr(mod, attr, None)
            if ungated and _gate_type and isinstance(cur, _gate_type):
                setattr(mod, attr, raw)  # the negative control: the code before the ruling had no gate
            elif (
                hasattr(cur, "query") and not (_gate_type and isinstance(cur, _gate_type)) and cur is not raw and not isinstance(cur, type)
            ):
                setattr(mod, attr, raw)  # a handle built before the patch — production would hold a raw table here too
        for attr in ("s3", "s3_client", "_s3", "S3", "bedrock", "_bedrock", "cloudwatch", "cw"):
            if attr in vars(mod) and not isinstance(vars(mod)[attr], type):
                setattr(mod, attr, rw._DeadClient())
    try:
        from ai import bedrock_client

        bedrock_client.invoke = lambda *a, **k: (_ for _ in ()).throw(rw._Dead("bedrock disabled"))
    except ImportError:
        pass
    # Every coach present (no dark instrument), so the dashboard reads each coach's OUTPUT#.
    from health import instrument_presence

    instrument_presence.absent_coaches = lambda *_a, **_k: {}
    return L


def _requests(L) -> list:
    from coach.persona_registry import OPERATIONAL_COACH_IDS, OPERATIONAL_SHORT_IDS

    reqs = [(p, {}) for p in rw.route_paths(L)]
    reqs += [(f"/api/coach/{cid}", {}) for cid in list(OPERATIONAL_COACH_IDS) + ["eli_marsh"]]
    reqs += [("/api/ai_analysis", {"expert": s}) for s in sorted(OPERATIONAL_SHORT_IDS)]
    reqs += [("/api/coach_analysis", {"domain": s}) for s in sorted(OPERATIONAL_SHORT_IDS)]
    reqs += [("/api/coach_timeline", {"coach_id": cid}) for cid in OPERATIONAL_COACH_IDS]
    reqs += [("/api/coach_moves", {"date": DAY})]
    return reqs


# The graded record's routes: every number they serve (counts, list lengths, rates, Brier scores)
# must be IDENTICAL with and without the gate — withholding words never changes a public number.
RECORD_ROUTES = (
    "/api/predictions",
    "/api/calibration",
    "/api/ledger_export",
    "/api/calls",
    "/api/wrong",
    "/api/coaches",
    "/api/coach_docket",
    "/api/coach/mind_coach",
    "/api/coach/sleep_coach",
)


def _numbers(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            if k != "_meta":
                yield from _numbers(v, f"{path}.{k}")
    elif isinstance(node, list):
        yield (f"{path}#len", len(node))
        for v in node:
            yield from _numbers(v, f"{path}[]")
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield (path, node)


def walk(variant: str, ungated: bool = False) -> dict:
    L = _wire(variant, ungated)
    result = {
        "variant": variant,
        "ungated": ungated,
        "routes": 0,
        "answered": 0,
        "raised": {},
        "leaks": {},
        "seen": {},
        "dashboard": {},
        "numbers": {},
    }
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
        gate = getattr(L, "narrative_publication", None)
        try:
            if gate is not None:
                gate.begin_request()
            resp = L._dispatch_route(event, path, "GET")
            if resp is None and callable(L.ROUTES.get(path)):
                resp = L.ROUTES[path]()
            if isinstance(resp, dict):  # the handler's own last step: annotate (if present), then the #5131 scrub
                resp = L.guard_api_response(gate.annotate(resp) if gate is not None else resp)
        except Exception as e:  # noqa: BLE001 — a handler that raises served nothing
            result["raised"][key] = type(e).__name__
            continue
        if not isinstance(resp, dict):
            continue
        result["answered"] += 1
        if key in RECORD_ROUTES:
            try:
                parsed = json.loads(resp.get("body") or "null")
            except ValueError:
                parsed = None
            result["numbers"][key] = sorted(_numbers(parsed))
        blob = json.dumps(resp, default=str).lower()
        phrases = sorted(p for p in PHRASES if p in blob)
        if phrases:
            result["seen"][key] = phrases
        tokens = sorted(t for t in FAMILY_TOKENS if t in blob)
        if (variant != "public" and phrases) or tokens:
            result["leaks"][key] = phrases + [f"token:{t}" for t in tokens]
        if path == "/api/coaching-dashboard":
            try:
                body = json.loads(resp.get("body") or "{}")
            except ValueError:
                body = {}
            result["dashboard"] = {
                "position_summaries": [c.get("position_summary") for c in body.get("coaches") or []],
                "withheld_slots": sum(1 for c in body.get("coaches") or [] if c.get("position_summary_withheld")),
                "moves_lines": len(((body.get("moves") or {}).get("lines")) or []),
                "moves_withheld": bool((body.get("moves") or {}).get("withheld")),
                "meta_withheld": (body.get("_meta") or {}).get("withheld"),
                "header": (resp.get("headers") or {}).get("x-narrative-withheld"),
            }
    return result


if __name__ == "__main__":
    import io
    import logging

    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", choices=sorted(PROVENANCE), required=True)
    ap.add_argument("--ungated", action="store_true")
    args = ap.parse_args()
    logging.disable(logging.CRITICAL)
    _real_stdout = sys.stdout
    sys.stdout = io.StringIO()  # handlers print; keep stdout for the one JSON line
    try:
        out = walk(args.variant, args.ungated)
        out["unparsed_queries"] = rw.STATS["unparsed_queries"]
    finally:
        sys.stdout = _real_stdout
    print(json.dumps(out))
