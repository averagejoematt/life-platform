#!/usr/bin/env python3
"""tests/call_publication_route_walk.py — every public GET route, and the static pages built from them, served from a
table whose ONLY difference between variants is the owner's PRIVATE coach calls (owner ruling 2026-11-05). Run by
`tests/test_call_publication_privacy.py`, one fresh interpreter per variant, so no handler cache carries one variant
into another.

    python3 tests/call_publication_route_walk.py --variant none|some|many [--ungated]

THE INFERENCE TEST. A private journal-derived call must not show through "IDs, wording, metadata, counts, evaluation
results or related endpoints", and "differences between public and private totals cannot be used to infer private
journal counts". So vary ONLY the private calls and compare EVERYTHING public: every route's body (and the two
wire-guard headers, whose values are counts) must be byte-identical across the variants, and so must the whole set
taken together — a cross-endpoint inference (one route's total against another's) needs some route to move.

What varies, all SYNTHETIC (no real id, date, count or wording):
  * private CALLS of every class the policy decides: a legacy call the reviewed registry does not list (its subject is
    the journal, graded on a public metric), and calls filed after the registry — an observation (free-text subject),
    a gradeable call whose words name the journal, a gradeable call on a metric no registry resolves;
  * the rows that NAME a private call: its LEARNING# (one names a call filed after the registry, so the reference
    rule's read is exercised), a grade CORRECTION#, the calibration ledger's prediction_void;
  * a private ASK (COMMITMENT#), legacy and new, and the commitments TALLY — PRODUCED here by the real producer
    (``coach.commitment_grading.write_tally``) from the varied corpus, so the producer half is under test too;
  * a private BET: a resolved docket entry, its two sides' docket PREDICTION# rows and its docket LEARNING#.

What is held fixed: every public call, ask, bet, learning and correction (reviewed-public legacy rows and structured
public calls filed after the registry), and every other row of the journal walk's public table.

The clock is frozen at `--now` for all variants. boto3, S3, HTTP and Bedrock are dead (the #4972 walk's wiring).
"""

from __future__ import annotations

import argparse
import datetime as _dtmod
import json
import os
import sys
import time as _time
from decimal import Decimal

_REAL_DT = _dtmod.datetime
FROZEN: _REAL_DT = _REAL_DT(2026, 11, 7, 20, 0, 0, tzinfo=_dtmod.timezone.utc)


class _FrozenDateTime(_REAL_DT):
    @classmethod
    def now(cls, tz=None):  # noqa: D102
        base = cls.fromtimestamp(FROZEN.timestamp(), tz=_dtmod.timezone.utc)
        return base.astimezone(tz) if tz is not None else cls.fromtimestamp(FROZEN.timestamp())

    @classmethod
    def utcnow(cls):  # noqa: D102
        return cls.fromtimestamp(FROZEN.timestamp(), tz=_dtmod.timezone.utc).replace(tzinfo=None)

    @classmethod
    def today(cls):  # noqa: D102
        return cls.now()


def _freeze(now_iso: str) -> None:
    global FROZEN
    FROZEN = _REAL_DT.fromisoformat(now_iso)
    _dtmod.datetime = _FrozenDateTime  # type: ignore[misc]
    _time.time = lambda: FROZEN.timestamp()  # type: ignore[assignment]


if __name__ == "__main__":
    _ap = argparse.ArgumentParser()
    _ap.add_argument("--variant", choices=("none", "some", "many"), required=True)
    _ap.add_argument("--now", required=True)
    _ap.add_argument("--ungated", action="store_true", help="mutation control: the call policy publishes every call")
    ARGS = _ap.parse_args()
    _freeze(ARGS.now)

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "scripts"))
os.environ.setdefault("CONTENT_FILTER_JSON", json.dumps({"blocked_vices": ["No fizzlewick"], "blocked_vice_keywords": ["fizzlewick"]}))

import journal_activity_route_walk as ja  # noqa: E402 — the public base table, the fake table, the dead clients
import rhythm_route_walk as rw  # noqa: E402

ja.FROZEN = FROZEN

PRIVATE_TOKEN = "SYNTHETIC-PRIVATE-CALL"
COACHES = ("sleep", "mind", "nutrition", "physical")
LEGACY_AT = "2026-10-20T12:00:00+00:00"  # before the reviewed registry's THROUGH
LEGACY_DAY = "2026-10-20"
NEW_AT = "2026-11-06T12:00:00+00:00"  # after it: decided by structure
NEW_DAY = "2026-11-06"


def _pk(cid: str) -> str:
    return f"COACH#{cid}_coach"


def _eval(metric, kind="directional", condition="up"):
    return {
        "type": kind,
        "metric": metric,
        "condition": condition,
        "threshold": None,
        "evaluation_window_days": Decimal("7"),
        "null_hypothesis": None,
        "beats_null_if": None,
    }


def _call(cid, pid, at, claim, status, metric, *, filing=None, outcome_date=None, extra=None):
    row = {
        "pk": _pk(cid),
        "sk": f"PREDICTION#{pid}",
        "prediction_id": pid,
        "coach_id": f"{cid}_coach",
        "claim_natural": claim,
        "status": status,
        "outcome": status if status in ("confirmed", "refuted") else None,
        "confidence": Decimal("0.6"),
        "created_at": at,
        "created_date": at[:10],
        "phase": "experiment",
        "cycle": Decimal("17"),
        "subdomain": "recovery",
        "decision_class": "observational",
        "evaluation": _eval(metric) if metric else {"type": "qualitative", "metric": None, "condition": None},
        "gradeable_by": "deterministic" if metric else "none",
        "outcome_date": outcome_date,
        "outcome_notes": json.dumps({"actual_value": 61.0, "reason": "synthetic grade"}) if outcome_date else None,
    }
    if filing is not None:
        row["filing"] = filing
    row.update(extra or {})
    return row


GRADEABLE = {"verdict": "gradeable", "filing_rules_version": "1", "reason": None}
OBSERVATION = {"verdict": "observation", "filing_rules_version": "1", "reason": "outcome_names_no_metric"}


def _learning(cid, pid, day, status, metric):
    return {
        "pk": _pk(cid),
        "sk": f"LEARNING#{day}#{pid.replace('_', '-')}",
        "prediction_id": pid,
        "coach_id": f"{cid}_coach",
        "status": status,
        "metric": metric,
        "condition": "up",
        "evaluation_type": "directional",
        "reason": "synthetic evaluator note",
        "date": day,
        "created_at": f"{day}T16:00:00+00:00",
        "phase": "experiment",
        "cycle": Decimal("17"),
        "channel": "data",
    }


def _correction(cid, pid, day):
    return {
        "pk": _pk(cid),
        "sk": f"CORRECTION#{pid}#{day}T18:00:00Z",
        "prediction_id": pid,
        "prediction_sk": f"PREDICTION#{pid}",
        "coach_id": f"{cid}_coach",
        "original_status": "confirmed",
        "corrected_status": "refuted",
        "reason": "synthetic correction",
        "corrected_at": f"{day}T18:00:00Z",
        "phase": "experiment",
        "cycle": Decimal("17"),
    }


def _ask(cid, sk_id, at, text, status, metric=None):
    return {
        "pk": _pk(cid),
        "sk": f"COMMITMENT#{sk_id}",
        "commitment_id": sk_id,
        "coach_id": f"{cid}_coach",
        "commitment_natural": text,
        "status": status,
        "created_at": at,
        "created_date": at[:10],
        "due_date": "2026-11-13",
        "window_days": Decimal("7"),
        "action_check": {"metric": metric, "direction": "up"} if metric else None,
        "phase": "experiment",
        "cycle": Decimal("17"),
        "surfaced_to_subject": True,
    }


def _bet(slug, opened_at, claim_a, claim_b, metric):
    a, b = "sleep_coach", "physical_coach"
    day = opened_at[:10]
    sk = f"RESOLVED#2026-10-27#{a}__{b}#{slug}"
    docket = {
        "pk": "ENSEMBLE#docket",
        "sk": sk,
        "topic": f"Synthetic bet {slug}",
        "topic_slug": slug,
        "coach_a": a,
        "coach_b": b,
        "claims": {a: claim_a, b: claim_b},
        "criterion": {"metric": metric, "condition": "gte", "threshold": Decimal("60"), "description": f"{metric} >= 60 on 2026-10-27"},
        "sides": {a: "yes", b: "no"},
        "stakes": {a: {"brier": Decimal("0.2"), "brier_n": Decimal("5")}, b: {"brier": Decimal("0.3"), "brier_n": Decimal("5")}},
        "opened_date": day,
        "opened_at": opened_at,
        "resolution_date": "2026-10-27",
        "resolved_date": "2026-10-27",
        "winner": a,
        "loser": b,
        "verdict": {"winner": a, "loser": b, "actual_value": Decimal("62")},
        "actual_value": Decimal("62"),
        "concession": f"CONCESSION — I lost the docket dispute on 'Synthetic bet {slug}'.",
        "status": "resolved",
        "record_type": "docket",
        "phase": "experiment",
        "cycle": Decimal("17"),
    }
    sides = []
    for cid, claim, won in ((a, claim_a, True), (b, claim_b, False)):
        pid = f"docket-{a}__{b}-recovery-{slug}-{day}"
        sides.append(
            {
                "pk": f"COACH#{cid}",
                "sk": f"PREDICTION#{pid}",
                "prediction_id": pid,
                "coach_id": cid,
                "claim_natural": claim,
                "status": "confirmed" if won else "refuted",
                "outcome": "confirmed" if won else "refuted",
                "confidence": Decimal("0.6"),
                "created_at": opened_at,
                "outcome_date": "2026-10-27",
                "resolved_at": "2026-10-27T16:00:00+00:00",
                "source": "dispute_docket",
                "docket_ref": f"OPEN#{a}__{b}#recovery",
                "metric": metric,
                "subdomain": "recovery",
                "phase": "experiment",
                "cycle": Decimal("17"),
                "actual_value": Decimal("62"),
            }
        )
        sides.append(
            {
                "pk": f"COACH#{cid}",
                "sk": f"LEARNING#2026-10-27#docket-{a}__{b}-recovery-{slug}",
                "coach_id": cid,
                "claim": claim,
                "docket_ref": f"OPEN#{a}__{b}#recovery",
                "metric": metric,
                "condition": "gte",
                "evaluation_type": "docket",
                "outcome": "confirmed" if won else "refuted",
                "date": "2026-10-27",
                "created_at": "2026-10-27T16:00:00+00:00",
                "channel": "data",
                "phase": "experiment",
                "cycle": Decimal("17"),
            }
        )
    return [docket] + sides


def _void(cid, pid):
    return {
        "pk": "USER#matthew#SOURCE#calibration",
        "sk": f"CALIB#2026-09-06#void#pred#{cid}_coach#{pid}",
        "record_type": "prediction_void",
        "coach_id": f"{cid}_coach",
        "prediction_id": pid,
        "claim": "a voided synthetic call",
        "outcome": "voided_at_reset",
        "voided_at_reset": True,
        "stated_confidence": Decimal("0.5"),
        "status_at_reset": "pending",
    }


def public_rows() -> list:
    """The fixed public record: reviewed-public legacy rows and structured public calls filed after the registry."""
    rows: list = []
    for i, cid in enumerate(COACHES):
        for j, (status, metric) in enumerate((("confirmed", "recovery_score"), ("refuted", "hrv"), ("pending", "steps"))):
            pid = f"pred_20261020_synthetic_public_{cid}_{j}"
            od = "2026-10-27" if status != "pending" else None
            rows.append(
                _call(cid, pid, LEGACY_AT, f"Synthetic public call {i}-{j}: {metric} will rise this week.", status, metric, outcome_date=od)
            )
            if od:
                rows.append(_learning(cid, pid, "2026-10-27", status, metric))
        rows.append(_call(cid, f"pred_20261020_synthetic_obs_{cid}", LEGACY_AT, f"Synthetic public observation {i}.", "observation", None))
        new_pid = f"pred_20261106_synthetic_public_new_{cid}"
        rows.append(
            _call(
                cid, new_pid, NEW_AT, f"Synthetic structured call {i}: recovery will rise.", "pending", "recovery_score", filing=GRADEABLE
            )
        )
        rows.append(
            _ask(
                cid, f"commit_20261020_synthetic_public_{cid}", LEGACY_AT, f"Synthetic public ask {i}: walk after dinner.", "kept", "steps"
            )
        )
        rows.append(
            _ask(cid, f"commit_20261106_synthetic_public_new_{cid}", NEW_AT, "Synthetic structured ask: steps up.", "pending", "steps")
        )
    rows.append(_correction("sleep", "pred_20261020_synthetic_public_sleep_0", "2026-10-28"))
    rows.append(_void("sleep", "pred_20261020_synthetic_public_sleep_2"))
    rows += _bet(
        "public-bet",
        "2026-09-28T12:00:00+00:00",
        "Synthetic side A: recovery holds.",
        "Synthetic side B: recovery slips.",
        "recovery_score",
    )
    rows.append(
        {
            "pk": "USER#matthew#SOURCE#calibration",
            "sk": "CALIB#2026-10-25#forecast#hrv",
            "record_type": "forecast_resolution",
            "model": "ewma-v1",
            "covered": True,
            "resolved_at": "2026-10-25T12:00:00+00:00",
            "metric": "hrv",
        }
    )
    return rows


def private_rows(n: int) -> list:
    """``n`` sets of private calls and every row that names them (all synthetic)."""
    rows: list = []
    for k in range(n):
        for cid in COACHES:
            legacy = f"pred_20261020_synthetic_private_{cid}_{k}"
            rows.append(
                _call(
                    cid,
                    legacy,
                    LEGACY_AT,
                    f"{PRIVATE_TOKEN} {k}: a synthetic journal call graded on a public metric.",
                    "refuted",
                    "total_protein_g",
                    outcome_date="2026-10-27",
                )
            )
            rows.append(_learning(cid, legacy, "2026-10-27", "refuted", "total_protein_g"))
            rows.append(_correction(cid, legacy, "2026-10-28"))
            rows.append(_void(cid, legacy))
            obs = f"pred_20261106_synthetic_private_obs_{cid}_{k}"
            rows.append(
                _call(cid, obs, NEW_AT, f"{PRIVATE_TOKEN} {k}: a synthetic free-text observation.", "observation", None, filing=OBSERVATION)
            )
            words = f"pred_20261106_synthetic_private_words_{cid}_{k}"
            rows.append(
                _call(
                    cid,
                    words,
                    NEW_AT,
                    f"{PRIVATE_TOKEN} {k}: if he journals, recovery will rise.",
                    "confirmed",
                    "recovery_score",
                    filing=GRADEABLE,
                    outcome_date=NEW_DAY,
                )
            )
            rows.append(_learning(cid, words, NEW_DAY, "confirmed", "recovery_score"))  # names a call filed after the registry
            unres = f"pred_20261106_synthetic_private_metric_{cid}_{k}"
            rows.append(
                _call(cid, unres, NEW_AT, f"{PRIVATE_TOKEN} {k}: valence will settle.", "pending", "mood_valence", filing=GRADEABLE)
            )
            rows.append(
                _ask(cid, f"commit_20261020_synthetic_private_{cid}_{k}", LEGACY_AT, f"{PRIVATE_TOKEN} {k}: write one line.", "unresolved")
            )
            rows.append(
                _ask(cid, f"commit_20261106_synthetic_private_{cid}_{k}", NEW_AT, f"{PRIVATE_TOKEN} {k}: name the quiet.", "pending")
            )
        rows += _bet(
            f"private-bet-{k}",
            "2026-09-29T12:00:00+00:00",
            f"{PRIVATE_TOKEN} {k}: the journal returns.",
            f"{PRIVATE_TOKEN} {k}: the journal stays shut.",
            "recovery_score",
        )
    return rows


class CallTable(ja.JournalTable):
    """The journal walk's table, plus ``ExclusiveStartKey`` / ``LastEvaluatedKey`` paging (so a Limit-filled read is
    exercised the way DynamoDB answers it) and ``get_item``."""

    def query(self, KeyConditionExpression=None, ExpressionAttributeValues=None, ExpressionAttributeNames=None, IndexName=None, **kw):
        start = kw.pop("ExclusiveStartKey", None)
        limit = kw.pop("Limit", None)
        resp = super().query(KeyConditionExpression, ExpressionAttributeValues, ExpressionAttributeNames, IndexName, **kw)
        if "Items" not in resp:
            return resp
        items = resp["Items"]
        if start:
            keys = [str(i.get("sk")) for i in items]
            sk = str(start.get("sk"))
            items = items[keys.index(sk) + 1 :] if sk in keys else items
        out = {"Items": items, "Count": len(items)}
        if limit and len(items) > int(limit):
            out["Items"] = items[: int(limit)]
            out["Count"] = int(limit)
            last = out["Items"][-1]
            out["LastEvaluatedKey"] = {"pk": last["pk"], "sk": last["sk"]}
        return out

    def get_item(self, Key=None, **_kw):
        rows = self._rows(Key.get("pk"), Key.get("sk"))
        return {"Item": rows[0]} if rows else {}


def _ungate() -> None:
    from common import prediction_publication as PP

    PP.row_is_public = lambda *_a, **_k: True  # type: ignore[assignment]


def _wire(variant: str, ungated: bool):
    import urllib.request

    import boto3
    from call_publication_fixtures import register_reviewed_public

    if ungated:
        _ungate()
    pub = public_rows()
    register_reviewed_public([r for r in pub if not str(r.get("created_at") or r.get("opened_at") or "").startswith("2026-11-06")])
    n = {"none": 0, "some": 1, "many": 3}[variant]
    CallTable.rows = ja._rows("none") + pub + private_rows(n)
    raw = CallTable()
    boto3.client = lambda *a, **k: rw._DeadClient()  # type: ignore[assignment]

    class _Res:
        def Table(self, _name):  # noqa: N802
            return raw

    boto3.resource = lambda *a, **k: _Res()  # type: ignore[assignment]
    urllib.request.urlopen = lambda *a, **k: (_ for _ in ()).throw(rw._Dead("http disabled"))  # type: ignore[assignment]

    # The commitments tally, PRODUCED by the real producer from the varied corpus (the grader's own call).
    import logging

    from coach import commitment_grading as CG

    corpus = [r for r in CallTable.rows if str(r.get("sk", "")).startswith("COMMITMENT#")]
    CG.write_tally(raw, corpus, {}, FROZEN.date().isoformat(), logging.getLogger("walk"))

    from web import narrative_publication, site_api_common, site_api_lambda as L

    assert isinstance(site_api_common.table, narrative_publication.PublicationTable), "the chokepoint is not installed"
    for mod_name, mod in list(sys.modules.items()):
        if mod is None or not mod_name.startswith(("web.", "common.", "intelligence.", "health.", "ai.", "coach.", "content.")):
            continue
        for attr in ("table", "_table", "TABLE", "ddb_table"):
            cur = getattr(mod, attr, None)
            if hasattr(cur, "query") and not isinstance(cur, type) and type(cur).__name__ != "PublicationTable" and cur is not raw:
                setattr(mod, attr, raw)
        for attr in ("s3", "s3_client", "_s3", "S3", "bedrock", "_bedrock", "cloudwatch", "cw"):
            if attr in vars(mod) and not isinstance(vars(mod)[attr], type):
                setattr(mod, attr, rw._DeadClient())
    try:
        from ai import bedrock_client

        bedrock_client.invoke = lambda *a, **k: (_ for _ in ()).throw(rw._Dead("bedrock disabled"))
    except ImportError:
        pass
    return L


EXTRA_REQUESTS = tuple(("/api/coach/" + f"{c}_coach", {}) for c in COACHES) + (
    ("/api/predictions", {"limit": "200"}),
    ("/api/predictions", {"status": "pending", "coach_id": "sleep"}),
    ("/api/ledger_export", {"page": "1", "size": "5"}),
    ("/api/ledger_export", {"page": "2", "size": "5"}),
    ("/api/coach_moves", {"date": "2026-11-06"}),
)
HEADERS = ("x-narrative-withheld", "x-journal-silence-withheld")


def _serve(L, path: str, qs: dict):
    """One request the way ``lambda_handler`` serves it: begin, dispatch, the two wire halves."""
    from common.journal_silence import guard_api_response
    from web import narrative_publication

    event = {
        "rawPath": path,
        "path": path,
        "httpMethod": "GET",
        "requestContext": {"http": {"method": "GET"}},
        "headers": {},
        "queryStringParameters": dict(qs),
    }
    narrative_publication.begin_request()
    resp = L._dispatch_route(event, path, "GET")
    if resp is None and callable(L.ROUTES.get(path)):
        resp = L.ROUTES[path]()
    return guard_api_response(narrative_publication.annotate(resp)) if isinstance(resp, dict) else resp


def _parsed(resp):
    body = resp.get("body")
    try:
        return json.loads(body) if isinstance(body, str) else body
    except ValueError:
        return body


def _pages(L) -> dict:
    """The static pages' data, built by the real snapshot builder from the in-process routes (Day pages, the
    ledger's per-call pages, the coaches) — the objects `www/` renders and the sitemap lists."""
    import publish_snapshot as PS

    def _get(_base, path, _timeout):
        p, _, q = path.partition("?")
        if not p.startswith("/api/"):
            return {}
        qs = dict(kv.split("=", 1) for kv in q.split("&") if "=" in kv)
        resp = _serve(L, p, qs)
        if not isinstance(resp, dict) or int(resp.get("statusCode") or 0) != 200:
            raise PS.urllib.error.URLError(f"{p}: {resp.get('statusCode') if isinstance(resp, dict) else None}")
        return _parsed(resp)

    PS._get = _get
    PS._get_text = lambda *_a, **_k: ""
    PS.log = lambda *_a, **_k: None
    try:
        objs, _data = PS.build_live_with_data("http://walk.invalid", 5.0)
    except Exception as e:  # noqa: BLE001 — reported, and the test fails on it
        return {"error": f"{type(e).__name__}: {e}"}
    keep = ("prediction", "day", "coach", "disagreement")
    return {t: ja._normalise(objs.get(t) or []) for t in keep}


def walk(variant: str, ungated: bool = False) -> dict:
    L = _wire(variant, ungated)
    out = {"variant": variant, "routes": 0, "answered": 0, "raised": {}, "bodies": {}, "headers": {}}
    reqs = [(p, {}) for p in rw.route_paths(L)] + list(EXTRA_REQUESTS)
    for path, qs in reqs:
        out["routes"] += 1
        key = path + ("?" + "&".join(f"{k}={v}" for k, v in qs.items()) if qs else "")
        try:
            resp = _serve(L, path, qs)
        except Exception as e:  # noqa: BLE001 — a handler that raises served nothing
            out["raised"][key] = type(e).__name__
            continue
        if not isinstance(resp, dict):
            continue
        out["answered"] += 1
        out["bodies"][key] = json.dumps(
            {"status": resp.get("statusCode"), "body": ja._normalise(_parsed(resp))}, sort_keys=True, default=str
        )
        hdrs = {k.lower(): v for k, v in (resp.get("headers") or {}).items()}
        out["headers"][key] = {h: hdrs.get(h) for h in HEADERS}
    out["pages"] = json.dumps(_pages(L), sort_keys=True, default=str)
    out["unparsed_queries"] = rw.STATS["unparsed_queries"]
    return out


if __name__ == "__main__":
    import io
    import logging

    logging.disable(logging.CRITICAL)
    _real_stdout = sys.stdout
    sys.stdout = io.StringIO()
    try:
        result = walk(ARGS.variant, ARGS.ungated)
    finally:
        sys.stdout = _real_stdout
    print(json.dumps(result))
