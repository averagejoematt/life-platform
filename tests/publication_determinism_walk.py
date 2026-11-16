#!/usr/bin/env python3
"""tests/publication_determinism_walk.py — one Site API request sequence in a FRESH interpreter, through the production
publication steps (``publication_begin`` → dispatch → ``publication_wire``), against a synthetic table (#6111).

    python3 tests/publication_determinism_walk.py --sequence '["/api/coaches", "/api/coach/mind_coach"]' [--mutate NAME]

A sequence step ``"*"`` expands to every GET request of the narrative route walk; ``"!drop-withheld"`` deletes the
withheld call from the table between two requests and lets the snapshot's refresh period pass (a handler cache that
kept its row would then serve its words).

Prints one JSON document: ``{"bodies": [[request, body], ...]}`` in request order. A fresh interpreter is the honest cold
container; running other requests first in the same interpreter is the warm one. ``tests/test_publication_determinism_6111.py``
compares them byte for byte.

THE FIXTURE (synthetic words only — no real call wording, no journal text). Every operational coach has a graded call and
a pending call (reviewed public, public provenance), a learning whose evidence names the graded call, and a daily read;
the lead has a daily read whose citation names a field path. The mind coach also holds ONE withheld call (a private
provenance record) whose sentence is ``WITHHELD``; its metric label is the words of the lead's field path. Two public rows
echo the withheld sentence: one in the mind coach's own partition (read by every request that reads the withheld call)
and one in the sleep coach's daily read (a partition no sleep-page request reads the withheld call from — only the
complete record can blank it).

``--mutate container_taint`` restores the defect this lane removes (the taint and the call-id map living for the
container, filled by whatever earlier requests read): the negative control the determinism test must catch.
``--mutate per_request_only`` withdraws the complete record from the taint (the design #6111's review overruled);
``--mutate no_wire`` skips the wire half, to show the words it removes are really on the page; ``--mutate handler_cache``
keeps one handler's graded rows across requests (the cache the per-request taint relies on never existing).
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
from decimal import Decimal

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "lambdas"))

import narrative_publication_route_walk as nw  # noqa: E402 — sets the env; we reuse its fake table and wiring

DAY = "2026-11-02"
#: The withheld call's sentence (synthetic) and the public rows that echo it.
WITHHELD = "The fixture subject will log seven quiet evenings of reading before the next weekly review."
WITHHELD_RUN = "will log seven quiet evenings of reading"
ECHO_SAME_PARTITION = f"Mind coach recap: the subject {WITHHELD_RUN} — a synthetic echo."
ECHO_MARK = "Mind coach recap"  # the same-partition echo's own words (not the withheld sentence's)
ECHO_OTHER_MARK = "Sleep coach aside"  # the other-partition echo's own words
ECHO_OTHER_PARTITION = f"Sleep coach aside: we expect the subject {WITHHELD_RUN} this cycle."
DROP = "!drop-withheld"  # a sequence step, not a request
FIELD_PATH = "whoop.recovery_score"
FIELD_LABEL = "WHOOP recovery score"

PUBLIC = {"v": 1, "families": ["whoop", "withings", "persona"], "producer": "pdw-fixture", "stamped_at": f"{DAY}T12:00:00+00:00"}
PRIVATE = {"v": 1, "families": ["journal_presence", "whoop"], "producer": "pdw-fixture", "stamped_at": f"{DAY}T12:00:00+00:00"}


def _call(cid: str, n: int, *, graded: bool, claim: str, prov: dict, minute: int) -> dict:
    row = {
        "pk": f"COACH#{cid}",
        "sk": f"PREDICTION#pred_202610{20 + n:02d}_{cid}_fixture_call_{n}",
        "prediction_id": f"pred_202610{20 + n:02d}_{cid}_fixture_call_{n}",
        "coach_id": cid,
        "claim_natural": claim,
        "claim": claim,
        "status": "confirmed" if graded else "pending",
        "confidence": Decimal("0.6"),
        "created_at": f"2026-10-{20 + n:02d}T12:{minute:02d}:00.{100000 + n:06d}+00:00",
        "created_date": f"2026-10-{20 + n:02d}",
        "date": f"2026-10-{20 + n:02d}",
        "target_date": "2026-10-28",
        "metric": "hrv",
        "evaluation": {"metric": "hrv", "type": "threshold", "condition": "above", "threshold": Decimal("50")},
        "provenance": prov,
    }
    if graded:
        row.update(outcome_date="2026-10-29", outcome_notes="hrv=55 vs threshold 50", evaluated_at="2026-10-29T12:00:00+00:00")
    return row


def rows() -> list:
    from coach.persona_registry import OPERATIONAL_COACH_IDS

    out: list = []
    for i, cid in enumerate(sorted(OPERATIONAL_COACH_IDS)):
        graded = _call(
            cid, 1, graded=True, claim=f"Synthetic graded call {i}: heart-rate variability stays above fifty.", prov=PUBLIC, minute=i
        )
        out.append(graded)
        out.append(
            _call(cid, 2, graded=False, claim=f"Synthetic pending call {i}: resting heart rate eases by Friday.", prov=PUBLIC, minute=i)
        )
        out.append(
            {
                "pk": f"COACH#{cid}",
                "sk": f"LEARNING#{DAY}#l1",
                "prediction_id": graded["prediction_id"],
                "status": "confirmed",
                "metric": "hrv",
                "reason": "hrv=55 vs threshold 50",
                "learning": f"Synthetic learning {i}: the variability call held.",
                "summary": f"Synthetic learning {i}: the variability call held.",
                "actual_value": Decimal("55"),
                "threshold": Decimal("50"),
                "condition": "above",
                "date": DAY,
                "created_at": f"{DAY}T12:00:00+00:00",
                "provenance": PUBLIC,
            }
        )
        daily = {"sleep_coach": ECHO_OTHER_PARTITION, "mind_coach": ECHO_SAME_PARTITION}.get(cid, f"Synthetic daily read {i}.")
        out.append(
            {
                "pk": f"COACH#{cid}",
                "sk": f"OUTPUT#{DAY}#daily",
                "content": daily,
                "public_summary": daily,
                "observatory_summary": f"Synthetic observatory line {i}.",
                "created_at": f"{DAY}T12:00:00+00:00",
                "data_through": DAY,
                "provenance": PUBLIC,
            }
        )
    withheld = _call("mind_coach", 3, graded=True, claim=WITHHELD, prov=PRIVATE, minute=59)
    withheld["metric_label"] = FIELD_LABEL
    out.append(withheld)
    out.append(
        {
            "pk": "COACH#eli_marsh",
            "sk": f"LEAD_DAILY#{DAY}",
            "coach_id": "eli_marsh",
            "text": "Synthetic lead read: recovery sat at sixty-six this morning.",
            "generated_at": f"{DAY}T12:00:00+00:00",
            "data_through": DAY,
            "cited": [{"metric": "morning recovery score", "value": "66", "as_of": DAY, "source_field": FIELD_PATH}],
            "provenance": PUBLIC,
        }
    )
    return out


def _mutate(name: str) -> None:
    """The defect, restored: taint and call ids that live for the container (the code before #6111)."""
    from web import narrative_publication as G, public_call_id as P, publication_snapshot as S, site_api_coach_ledger as LED

    if name == "no_wire":  # the wire half skipped: shows what the scrub is there to remove (a non-vacuity control)
        G.annotate = lambda response: response
        return
    if name == "handler_cache":  # a handler that keeps the graded rows it read for later requests (what must not exist)
        from coach import latest_checked

        real, kept = latest_checked._query_rows, {}
        latest_checked._query_rows = lambda table, coach_id: kept.setdefault(coach_id, real(table, coach_id))
        return
    if name == "per_request_only":  # the complete record withdrawn from the taint (ids still read): the design #6111 overruled
        S.complete = lambda: (frozenset(), frozenset())
        return
    if name != "container_taint":
        raise SystemExit(f"unknown mutation {name}")
    state = G._STATE

    def begin_request() -> None:
        G.NA.reset_served()
        state.update(withheld=0, served=0, scrubbed=0)

    G.begin_request = begin_request
    S.begin_request = lambda table=None: S._REQ.update(table=None, checked=False, refreshed=set(), sets=None)
    assert LED and P  # the partition reader still registers what it reads, as before


def _wire():
    nw._rows = lambda variant: rows()  # noqa: E731 — the walk's fixture, replaced
    L = nw._wire("public", False)
    from call_publication_fixtures import register_reviewed_public

    register_reviewed_public(nw.NarrativeTable.rows)
    return L


def request(L, target: str) -> str:
    path, _, q = target.partition("?")
    qs = dict(p.split("=", 1) for p in q.split("&")) if q else {}
    event = {
        "rawPath": path,
        "path": path,
        "httpMethod": "GET",
        "requestContext": {"http": {"method": "GET"}},
        "headers": {},
        "queryStringParameters": qs,
    }
    # The production steps; on a checkout from before #6111 (the reproduction run against origin/main) the same
    # three steps as that handler's tail.
    begin = getattr(L, "publication_begin", None) or L.narrative_publication.begin_request
    wire = getattr(L, "publication_wire", None) or (
        lambda p, r: L.guard_api_response(
            L._in_cr2_scope(p, lambda: L.narrative_publication.annotate(L.public_call_id.publicize_response(r))), L.logger
        )
    )
    begin()
    resp = L._in_cr2_scope(path, lambda: L._dispatch_route(event, path, "GET"))
    if resp is None and callable(L.ROUTES.get(path)):
        resp = L.ROUTES[path]()
    resp = wire(path, resp)
    return _clockless(resp.get("body") if isinstance(resp, dict) else "")


# The only bytes two runs of one request may differ in: the response's own clock reads (``_meta``'s instants).
_META_CLOCK = re.compile(r'"(generated_at|served_at)": "\d{4}-\d\d-\d\dT[0-9:.]+\+00:00"')


def _clockless(body: str) -> str:
    return _META_CLOCK.sub(lambda m: f'"{m.group(1)}": "<clock>"', body or "")


def _expand(L, sequence: list) -> list:
    """``"*"`` stands for every GET request of the narrative route walk (every route, every coach page, every variant)."""
    out: list = []
    for t in sequence:
        if t == "*":
            out += [p + ("?" + "&".join(f"{k}={v}" for k, v in qs.items()) if qs else "") for p, qs in nw._requests(L)]
        else:
            out.append(t)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sequence", required=True)
    ap.add_argument("--mutate")
    args = ap.parse_args()
    logging.disable(logging.CRITICAL)
    real = sys.stdout
    sys.stdout = io.StringIO()  # handlers print; stdout carries the one JSON line
    try:
        L = _wire()
        if args.mutate:
            _mutate(args.mutate)
        bodies = []
        for t in _expand(L, json.loads(args.sequence)):
            if t == DROP:  # the withheld call is deleted from the table, and the snapshot's refresh period passes
                from web import publication_snapshot as S

                nw.NarrativeTable.rows = [r for r in nw.NarrativeTable.rows if r.get("claim_natural") != WITHHELD]
                S._PARTS.clear()
                continue
            bodies.append([t, request(L, t)])
    finally:
        sys.stdout = real
    print(json.dumps({"bodies": bodies}))


if __name__ == "__main__":
    main()
