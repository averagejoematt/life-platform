"""tests/test_coach_room_words_cr2.py — /api/coach_room_words, the ONE route that opens the CR2 scope (owner ruling
2026-11-09, third, D). The allowlist's own gate tests are tests/test_narrative_allowlist_cr2.py.

What is pinned, end to end through the site API's ``lambda_handler`` and the real gated table (``PublicationTable``
over a fake raw table):

  * DARK: with ``CR2_PUBLIC`` off the route is a 404 for every coach; called outside the CR2 scope it is a 404 too;
  * ON: inside the route, an approved, unchanged, unrecorded row is served — even when an earlier out-of-scope request
    in the same container tainted its words at the wire;
  * NOT WIDENED: every other routed path runs with no scope, so a probe that reads the same approved rows through the
    gated table and echoes their words gets them withheld (emptied at the read, or scrubbed at the wire);
  * NEGATIVE CONTROLS through the route: a listed row whose words changed, a listed row that carries a provenance
    record of its own (private, unrecorded or malformed), a historical row not on the list, a lead read whose cited
    block names a private field, and a dossier filter that cannot load — each is left out (omitted, never marked);
  * THE WIRE: a listed row that the gate withheld (its own private record) is NOT exempt from the wire scrub inside
    the scope — the exemption covers only words the gate published in this request.

The sealed calls' words are already public in deploy/generated/genesis_preregistration.json, so these tests use the
real entries for them; lead reads use a synthetic entry (their words are private until CR2 ships).
"""

# premerge-gate: CR2 route (owner 2026-11-09 D): walks every routed path of the site API against the approved rows — a diff that adds a route, opens the CR2 scope elsewhere or changes the gate's wire exemption must red before merge.
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "lambdas"))
os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")

from common import narrative_allowlist as NA  # noqa: E402
from web import (
    narrative_publication as G,  # noqa: E402
    site_api_coach_room as R,  # noqa: E402
    site_api_common as C,  # noqa: E402
    site_api_lambda as L,  # noqa: E402
)

PREREG = json.loads((ROOT / "deploy" / "generated" / "genesis_preregistration.json").read_text())
SEALED = {p["claim_natural"] for c in PREREG["coaches"].values() for p in c["predictions"]}
COACH = "sleep_coach"
LEAD = "eli_marsh"
LEAD_SK = "LEAD_DAILY#2026-10-11"  # not a listed day: the synthetic entry below is the only one under it
LEAD_TEXT = "A synthetic dated lead read: weight down and recovery steady this morning."
PUBLIC_CITED = [
    {"metric": "hrv", "value": "50", "as_of": "2026-10-10", "source_field": "whoop.hrv"},
    {"metric": "weight", "value": "250.0", "as_of": "2026-10-10", "source_field": "withings.weight_lbs"},
]


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _calls(coach: str = COACH) -> list:
    return [e for e in NA.APPROVED if e.pk == f"COACH#{coach}" and e.sk.startswith("PREDICTION#")]


def _sealed_row(entry: NA.Entry) -> dict:
    claim = next(c for c in SEALED if _sha(c) == entry.text_sha256)
    return {
        "pk": entry.pk,
        "sk": entry.sk,
        "claim_natural": claim,
        "status": "refuted",
        "prediction_id": entry.sk[len("PREDICTION#") :],
        "coach_id": entry.pk[len("COACH#") :],
        "created_date": "2026-09-06",
        "pre_registered": True,
        "outcome_date": "2026-09-20",
        "evaluation": {"metric": "sleep_duration_hours", "type": "directional", "condition": "up", "evaluation_window_days": 14},
    }


def _lead_row(text: str = LEAD_TEXT, cited=None) -> dict:
    return {
        "pk": f"COACH#{LEAD}",
        "sk": LEAD_SK,
        "coach_id": LEAD,
        "text": text,
        "generated_at": "2026-10-11T17:07:05Z",
        "data_through": "2026-10-10",
        "cited": PUBLIC_CITED if cited is None else cited,
    }


class _Raw:
    """A raw DynamoDB table: get_item by key, query by partition."""

    def __init__(self, rows):
        self.rows = {(r["pk"], r["sk"]): dict(r) for r in rows}

    def get_item(self, **kw):
        k = kw.get("Key") or {}
        row = self.rows.get((k.get("pk"), k.get("sk")))
        return {"Item": dict(row)} if row else {}

    def query(self, **kw):
        pk = (kw.get("ExpressionAttributeValues") or {}).get(":pk")
        return {"Items": [dict(r) for (p, _s), r in self.rows.items() if pk is None or p == pk]}

    def scan(self, **kw):
        return {"Items": [dict(r) for r in self.rows.values()]}


@pytest.fixture
def lead_entry(monkeypatch):
    e = NA.Entry(f"COACH#{LEAD}", LEAD_SK, "text", _sha(LEAD_TEXT), NA.DERIVED_FROM_CITED)
    monkeypatch.setattr(NA, "APPROVED", NA.APPROVED + (e,))
    monkeypatch.setattr(NA, "INDEX", {**NA.INDEX, (e.pk, e.sk): e})
    return e


@pytest.fixture
def cr2_on(monkeypatch):
    monkeypatch.setattr(NA, "CR2_PUBLIC", True)


@pytest.fixture
def ldl_counterfactual(monkeypatch):
    """The route's positive control. Since the owner ruled the LDL target private (2026-11-11, items 2 and 6) every
    sealed call is withheld — each generation prompt read that field (tests/test_goals_field_privacy.py). To keep
    proving the ROUTE serves an approved, unchanged call, the mechanism tests restore the pre-ruling classification
    of that one field; ``test_the_ldl_ruling_leaves_the_route_no_sealed_call`` pins the live outcome."""
    from common import goals_field_privacy as GFP

    f = "targets.biomarkers.ldl_target_mg_dl"
    monkeypatch.setattr(GFP, "_PRIVATE", tuple(p for p in GFP._PRIVATE if p != f))
    monkeypatch.setattr(GFP, "_PUBLIC_SAFE", GFP._PUBLIC_SAFE + (f,))


@pytest.fixture
def dossier_ok(monkeypatch):
    from coach import coach_dossier

    monkeypatch.setattr(coach_dossier, "dossier_safe", lambda *t: True)


def _install(monkeypatch, rows) -> _Raw:
    """The site API's gated table over a fake raw table (the real PublicationTable, the real call policy)."""
    raw = _Raw(rows)
    monkeypatch.setattr(C, "table", G.wrap(raw))
    return raw


def _get(path: str, qs: dict | None = None) -> dict:
    event = {"rawPath": path, "requestContext": {"http": {"method": "GET"}}, "queryStringParameters": qs or {}, "headers": {}}
    return L.lambda_handler(event, None)


def _body(resp: dict) -> dict:
    return json.loads(resp["body"])


def _rows():
    return [_sealed_row(e) for e in _calls()] + [_lead_row()]


# ── the route is registered, dark, and the only scope opener ─────────────────────────────────


def test_the_route_is_routed_and_the_switch_is_off_on_main():
    assert R.ROUTE in L.ROUTES and L._SIMPLE_ROUTES[R.ROUTE][1] is R.handle_coach_room_words
    assert NA.CR2_PUBLIC is False


def test_the_scope_opens_for_the_cr2_route_only(cr2_on):
    paths = set(L.ROUTES) | set(L._SIMPLE_ROUTES) | {"/api/coach/eli_marsh", "/api/coach_room_words/", "/API/COACH_ROOM_WORDS", ""}
    for p in sorted(paths - {R.ROUTE}):
        with R.scope_for(p):
            assert not NA.active(), p
    with R.scope_for(R.ROUTE):
        assert NA.active()


@pytest.mark.parametrize("coach", [COACH, LEAD, "training_coach", "", "not_a_coach"])
def test_switch_off_the_route_is_a_404_for_every_coach(monkeypatch, lead_entry, dossier_ok, coach):
    _install(monkeypatch, _rows())
    resp = _get(R.ROUTE, {"coach": coach})
    assert resp["statusCode"] == 404
    blob = resp["body"]
    assert LEAD_TEXT not in blob and not any(c in blob for c in SEALED)


def test_switch_on_outside_the_scope_the_handler_is_a_404(monkeypatch, cr2_on, dossier_ok):
    _install(monkeypatch, _rows())
    assert R.handle_coach_room_words({"queryStringParameters": {"coach": COACH}})["statusCode"] == 404


def test_an_ungated_table_is_refused(monkeypatch, cr2_on, dossier_ok):
    with NA.serving(NA.SCOPE_CR2):
        resp = R.handle_coach_room_words({"queryStringParameters": {"coach": COACH}}, table=_Raw(_rows()))
    assert resp["statusCode"] == 404


# ── switch on, inside the route: the approved rows are served ───────────────────────────────


def test_switch_on_the_route_serves_the_approved_sealed_calls(monkeypatch, cr2_on, dossier_ok, ldl_counterfactual):
    _install(monkeypatch, _rows())
    resp = _get(R.ROUTE, {"coach": COACH})
    assert resp["statusCode"] == 200
    b = _body(resp)
    assert b["coach_id"] == COACH and b["approved_at"] == NA.APPROVED_AT and b["lead_reads"] == []
    want = {_sealed_row(e)["claim_natural"] for e in _calls()}
    assert {c["claim"] for c in b["sealed_calls"]} == want and len(want) == 2
    for c in b["sealed_calls"]:
        assert set(c) == {"prediction_id", "claim", "logged_date", "due_date", "settled_date", "metric", "kind", "status", "sealed"}
        assert c["logged_date"] == "2026-09-06" and c["status"] == "refuted" and c["sealed"] is True


def test_the_ldl_ruling_leaves_the_route_no_sealed_call(monkeypatch, cr2_on, dossier_ok):
    """Owner ruling 2026-11-11: with the LDL target private, the route serves NONE of the approved sealed calls (all
    14 read it); only the 21 approved lead reads remain servable. The owner accepted this consequence."""
    _install(monkeypatch, _rows())
    resp = _get(R.ROUTE, {"coach": COACH})
    assert resp["statusCode"] == 200
    b = _body(resp)
    assert b["sealed_calls"] == []
    assert not ({_sealed_row(e)["claim_natural"] for e in _calls()} & set(json.dumps(b).split('"')))
    sealed = [e for e in NA.APPROVED if e.sk.startswith("PREDICTION#")]
    assert len(sealed) == 14 and len(NA.APPROVED) - len(sealed) == 21


def test_switch_on_the_route_serves_an_approved_lead_read_with_public_figures_only(monkeypatch, cr2_on, lead_entry, dossier_ok):
    _install(monkeypatch, _rows())
    b = _body(_get(R.ROUTE, {"coach": LEAD}))
    assert b["sealed_calls"] == [] and len(b["lead_reads"]) == 1
    r = b["lead_reads"][0]
    assert r["text"] == LEAD_TEXT and r["date"] == "2026-10-11" and r["data_through"] == "2026-10-10"
    assert r["cited"] == [{"metric": c["metric"], "value": c["value"], "as_of": c["as_of"]} for c in PUBLIC_CITED]
    assert "source_field" not in json.dumps(b), "the cited block's source names never cross the wire"
    # the denominator rides with the lead's reads (a count, no words) — and only with the lead's
    assert b["lead_window"] == NA.LEAD_WINDOW and b["lead_window"]["written"] >= len(b["lead_reads"])


def test_the_lead_window_counts_at_least_every_listed_lead_read_and_rides_with_the_lead_only(monkeypatch, cr2_on, dossier_ok):
    listed = [e for e in NA.APPROVED if e.pk == NA.LEAD_PK and e.sk.startswith(R.LEAD_PREFIX)]
    days = sorted(e.sk[len(R.LEAD_PREFIX) :] for e in listed)
    assert NA.LEAD_WINDOW["written"] >= len(listed)
    assert NA.LEAD_WINDOW["from"] <= days[0] and days[-1] <= NA.LEAD_WINDOW["to"]
    _install(monkeypatch, _rows())
    assert "lead_window" not in _body(_get(R.ROUTE, {"coach": COACH}))


def test_words_tainted_by_an_earlier_request_are_still_served_inside_the_route(
    monkeypatch, cr2_on, lead_entry, dossier_ok, ldl_counterfactual
):
    """The container's taint set persists across requests: the gate's own publication of an approved row is what
    exempts its words at the wire — for that request only."""
    _install(monkeypatch, _rows())
    G.begin_request()
    for r in _rows():  # an out-of-scope read (any other route) withholds them; a graded row's words are tainted
        G.gate_item(dict(r))
    calls = [r["claim_natural"] for r in _rows() if "claim_natural" in r]
    assert calls and all(G.is_tainted(c) for c in calls)
    b = _body(_get(R.ROUTE, {"coach": COACH}))
    assert len(b["sealed_calls"]) == 2 and all(c["claim"] for c in b["sealed_calls"])
    assert _body(_get(R.ROUTE, {"coach": LEAD}))["lead_reads"][0]["text"] == LEAD_TEXT
    assert all(G.is_tainted(c) for c in calls), "outside the route they stay withheld at the wire"


# ── not widened: every other path reads the same rows withheld ─────────────────────────────


def _probe_paths() -> list:
    return sorted((set(L.ROUTES) | set(L._SIMPLE_ROUTES) | {"/api/coach/eli_marsh", "/api/coach/sleep_coach"}) - {R.ROUTE})


def test_every_other_route_reads_the_approved_rows_withheld(monkeypatch, cr2_on, lead_entry, dossier_ok, ldl_counterfactual):
    """A probe dispatcher stands in for every routed handler: it reads the approved rows through the gated table and
    echoes every word it got. Under every path but the CR2 route, nothing approved reaches the wire."""
    _install(monkeypatch, _rows())
    keys = [(e.pk, e.sk) for e in _calls()] + [(f"COACH#{LEAD}", LEAD_SK)]

    def probe(event, path, method):
        got = [C.table.get_item(Key={"pk": pk, "sk": sk}).get("Item") or {} for pk, sk in keys]
        q = C.table.query(KeyConditionExpression="pk = :pk", ExpressionAttributeValues={":pk": f"COACH#{COACH}"})
        words = [i.get("claim_natural") or i.get("text") or "" for i in got + q["Items"]]
        return C._ok({"words": words}, cache_seconds=0)

    monkeypatch.setattr(L, "_dispatch_route", probe)
    approved = {r.get("claim_natural") or r.get("text") for r in _rows()}
    for path in _probe_paths():
        resp = _get(path)
        served = set(_body(resp).get("words") or []) if resp["statusCode"] == 200 else set()
        assert resp["statusCode"] == 200 and not (served & approved), path
    on = set(_body(_get(R.ROUTE))["words"])  # the control: the same probe under the CR2 route gets every approved word
    assert approved <= on


# ── negative controls through the route ────────────────────────────────────────────────────


def test_a_listed_row_whose_words_changed_is_left_out(monkeypatch, cr2_on, lead_entry, dossier_ok, ldl_counterfactual):
    rows = _rows()
    rows[0] = {**rows[0], "claim_natural": rows[0]["claim_natural"] + " "}
    rows[-1] = _lead_row(LEAD_TEXT.replace("steady", "steadier"))
    _install(monkeypatch, rows)
    b = _body(_get(R.ROUTE, {"coach": COACH}))
    assert [c["claim"] for c in b["sealed_calls"]] == [rows[1]["claim_natural"]]
    assert _body(_get(R.ROUTE, {"coach": LEAD}))["lead_reads"] == []


@pytest.mark.parametrize(
    "record",
    [
        {"v": 1, "families": ["experiments", "journal_presence"], "producer": "t"},
        {"v": 1, "families": ["persona", "state_of_mind"], "producer": "t"},
        {"v": 1, "families": ["experiments", "unrecorded"], "producer": "t"},
        {"v": 2, "families": ["experiments"], "producer": "t"},
        None,
    ],
)
def test_a_listed_row_carrying_its_own_record_is_left_out(monkeypatch, cr2_on, lead_entry, dossier_ok, record):
    """The allowlist never overrides a provenance marker: the row's own record decides (private here, or broken)."""
    rows = [{**r, "provenance": record} for r in _rows()]
    _install(monkeypatch, rows)
    assert _body(_get(R.ROUTE, {"coach": COACH}))["sealed_calls"] == []
    assert _body(_get(R.ROUTE, {"coach": LEAD}))["lead_reads"] == []


def test_inside_the_scope_a_withheld_listed_row_is_still_scrubbed_at_the_wire(monkeypatch, cr2_on, dossier_ok):
    """The wire exemption covers the words the gate PUBLISHED, never the list: a listed call carrying a private
    record is withheld at the read (a graded row reaches the handler unchanged) and must be scrubbed at the wire even
    when a handler inside the CR2 scope echoes it."""
    row = {**_sealed_row(_calls()[0]), "provenance": {"v": 1, "families": ["journal_presence"], "producer": "t"}}
    _install(monkeypatch, [row])

    def echo(event, path, method):
        item = C.table.get_item(Key={"pk": row["pk"], "sk": row["sk"]}).get("Item") or {}
        return C._ok({"claim": item.get("claim_natural")}, cache_seconds=0)

    monkeypatch.setattr(L, "_dispatch_route", echo)
    assert _body(_get(R.ROUTE))["claim"] == ""


def test_a_historical_row_not_on_the_list_is_never_served(monkeypatch, cr2_on, dossier_ok, ldl_counterfactual):
    """Negative control: the same partition holds an unlisted day-one call and an unlisted lead day — neither is read
    as approved (the route reads by listed key only, and the gate withholds them anyway)."""
    extra = [
        {**_sealed_row(_calls()[0]), "sk": "PREDICTION#pred_20260906_not_on_the_list", "prediction_id": "pred_20260906_not_on_the_list"},
        _lead_row("A synthetic lead read for a day the record-level check excluded.") | {"sk": "LEAD_DAILY#2026-10-29"},
    ]
    _install(monkeypatch, _rows() + extra)
    b = _body(_get(R.ROUTE, {"coach": COACH}))
    assert len(b["sealed_calls"]) == 2 and all(c["prediction_id"] != "pred_20260906_not_on_the_list" for c in b["sealed_calls"])
    assert extra[1]["text"] not in json.dumps(_body(_get(R.ROUTE, {"coach": LEAD})))


@pytest.mark.parametrize("field", ["journal.days_since_last_entry", "state_of_mind.valence", "a_source_nobody_classified.x"])
def test_a_lead_read_whose_cited_block_names_a_private_field_is_left_out(monkeypatch, cr2_on, lead_entry, dossier_ok, field):
    cited = PUBLIC_CITED + [{"metric": "m", "value": "3", "as_of": "2026-10-10", "source_field": field}]
    _install(monkeypatch, [_lead_row(cited=cited)])
    assert _body(_get(R.ROUTE, {"coach": LEAD}))["lead_reads"] == []


def test_a_dossier_filter_that_cannot_load_withholds_everything(monkeypatch, cr2_on, lead_entry):
    from coach import coach_dossier

    def boom(*_t):
        raise RuntimeError("vocabulary unavailable")

    monkeypatch.setattr(coach_dossier, "dossier_safe", boom)
    _install(monkeypatch, _rows())
    assert _body(_get(R.ROUTE, {"coach": COACH}))["sealed_calls"] == []
    assert _body(_get(R.ROUTE, {"coach": LEAD}))["lead_reads"] == []


def test_the_route_answers_only_for_coaches_with_approved_rows(monkeypatch, cr2_on, dossier_ok):
    assert set(R.coaches()) == {e.pk[len("COACH#") :] for e in NA.APPROVED}
    assert "training_coach" in R.coaches() and "career_coach" not in R.coaches()
    _install(monkeypatch, _rows())
    assert _get(R.ROUTE, {"coach": "career_coach"})["statusCode"] == 404
    assert _get(R.ROUTE)["statusCode"] == 404
