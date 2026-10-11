"""tests/test_claim_sourcing_4673.py — a coach's words citing a sensor with no reading that day are not quoted (#4673).

The specimen, verified live 2026-10-05 04:09Z: `/api/coach/glucose_coach` served
`absent: true, reason: "no sensor since 2026-08-27"`, while `/api/coach_docket.resolved[]`
and `/api/calls` (`bet-20260930-994b3d89f6`) served Amara Patel's side of a bet opened
2026-09-23 verbatim — "Evening carb reduction is likely coming based on CGM data…".

Fixtures are the wire: `instrument_presence_fixture` (the live 2026-09-26 liveness sentinel,
cgm dark since 2026-08-27) and `fixtures/calls_wire_4586/` (the PREDICTION# partitions and
ENSEMBLE#docket rows read from DynamoDB 2026-10-04, which hold the specimen bet). Every
route test has a MUTATION CONTROL: the same rows with the checker's `dark` verdict flipped on
cgm alone must quote the words again.

The SET is guarded two ways:
  * every instrument `coach_instruments()` names has a phrase table entry (a new sensor
    cannot join with nothing to recognise it by), and
  * the specimen's words appear on NO route body that serves docket claims —
    /api/coach_docket, /api/calls and /api/calls?id=<the bet> — swept in one test.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "tests"))

from fakes import FakeDdbTable  # noqa: E402
from instrument_presence_fixture import (  # noqa: E402
    ABSENT_REASON,
    CGM_LAST_SEEN,
    GLUCOSE_DOCKET_CLAIM,
    GLUCOSE_POSITION_SUMMARY,
    NOW,
    NUTRITION_DOCKET_CLAIM,
    dispatching_query_hook,
    fresh_instrument_rows,
    glucose_docket_item,
    sentinel_item,
)
from web import claim_sourcing  # noqa: E402

BET = "bet-20260930-994b3d89f6"
HELD_SENTENCE = "Not quoted: this was said on September 23 and rests on his glucose sensor, which had sent no reading since August 27."
_WIRE = os.path.join(_REPO, "tests", "fixtures", "calls_wire_4586")
#: The interval form (#4702) of the live 2026-09-26 state: cgm dark since 2026-08-27, one OPEN gap.
CGM_DARK = [
    {
        "source": "apple_health",
        "datatype": "cgm",
        "label": "CGM (glucose)",
        "gaps": [{"start": CGM_LAST_SEEN, "end": None, "reason": ABSENT_REASON}],
    }
]


def _load(name):
    with open(os.path.join(_WIRE, name), encoding="utf-8") as fh:
        return json.load(fh)


# ── the rule ───────────────────────────────────────────────────────────────────────────


def test_every_registry_instrument_has_phrases_and_no_phrase_entry_is_orphaned():
    from ingestion.source_registry import coach_instruments

    registry = {(i["source"], i.get("datatype") or None) for i in coach_instruments().values()}
    missing = sorted(map(str, registry - set(claim_sourcing.CITES)))
    orphaned = sorted(map(str, set(claim_sourcing.CITES) - registry))
    assert not missing, f"an instrument with no phrases can never have a claim held for it: {missing}"
    assert not orphaned, f"phrase entries for instruments the registry no longer names: {orphaned}"


def test_the_specimen_is_held_and_says_why_in_words():
    note = claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], "2026-09-23", CGM_DARK)
    assert note == {
        "reason": ABSENT_REASON,
        "instrument": {"source": "apple_health", "datatype": "cgm"},
        "last_seen": CGM_LAST_SEEN,
        "gap": {"start": CGM_LAST_SEEN, "end": None},
        "said_on": "2026-09-23",
        "text": HELD_SENTENCE,
    }


def test_words_said_on_or_before_the_last_reading_are_quoted():
    assert claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], CGM_LAST_SEEN, CGM_DARK) is None
    assert claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], "2026-08-20", CGM_DARK) is None


def test_no_date_no_citation_or_no_dark_instrument_means_quoted():
    assert claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], None, CGM_DARK) is None, "never guess a date"
    assert claim_sourcing.unsourced([NUTRITION_DOCKET_CLAIM], "2026-09-23", CGM_DARK) is None
    assert claim_sourcing.unsourced(["Recovery score will be 66.2% tomorrow (80% interval 37–95%)."], "2026-09-09", CGM_DARK) is None
    assert claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], "2026-09-23", []) is None


def test_the_phrase_not_the_speaker_decides():
    """The nutrition coach's 2026-09-13 sentence cites the CGM too — it is held by the same rule."""
    said = "Evening carb reduction without caloric compensation will crater recovery within the CGM window."
    assert claim_sourcing.unsourced([said], "2026-09-13", CGM_DARK)


def test_the_domain_word_alone_is_not_a_citation():
    assert not claim_sourcing.cites("Nocturnal glucose dips will trigger cortisol counter-regulation.", "apple_health", "cgm")
    for cited in ("His CGM is generating traces", "glucose readings this week", "the Dexcom shows", "continuous glucose monitoring"):
        assert claim_sourcing.cites(cited, "apple_health", "cgm"), cited


def test_an_instrument_with_no_reading_on_record_holds_any_dated_citation():
    dark = [{**CGM_DARK[0], "gaps": [{"start": None, "end": None, "reason": "no sensor recorded"}]}]
    note = claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], "2026-09-23", dark)
    assert note and note["text"].endswith("which had no reading on record.")


def test_gap_instruments_reads_the_absent_map_once_per_instrument():
    absent = {
        "glucose_coach": {"source": "apple_health", "datatype": "cgm", "label": "CGM (glucose)", "last_seen": "2026-08-27", "reason": "x"},
        "other": {"source": "apple_health", "datatype": "cgm", "label": "CGM (glucose)", "last_seen": "2026-08-27", "reason": "x"},
    }
    rows = claim_sourcing.gap_instruments(absent)
    assert [d["datatype"] for d in rows] == ["cgm"]
    assert rows[0]["gaps"] == [{"start": "2026-08-27", "end": None, "reason": "x"}], "one OPEN gap per dark instrument"
    assert claim_sourcing.gap_instruments(None) == []


def test_dated_rows_lose_their_words_not_their_place():
    rows = [
        {"date": "2026-09-26", "summary": GLUCOSE_POSITION_SUMMARY, "themes": ["CGM data quality", "meal logging"]},
        {"date": "2026-09-19", "summary": "I'm testing whether nocturnal glucose dips are fragmenting his slow-wave sleep.", "themes": []},
        {"date": "2026-08-20", "summary": "His CGM trace shows a flat overnight line.", "themes": []},
    ]
    out = claim_sourcing.scrub_rows(rows, CGM_DARK, day_key="date", text_keys=("summary",), list_keys=("themes",))
    assert out[0]["summary"] == "" and out[0]["themes"] == [] and out[0]["date"] == "2026-09-26"
    assert out[0]["unsourced"]["said_on"] == "2026-09-26"
    assert out[1] == rows[1], "no citation: untouched"
    assert out[2] == rows[2], "said while the sensor still read: untouched"
    assert rows[0]["summary"] == GLUCOSE_POSITION_SUMMARY, "the stored row is never edited"
    assert claim_sourcing.scrub_rows(rows, [], day_key="date", text_keys=("summary",)) is rows
    assert claim_sourcing.scrub_one(None, CGM_DARK, day_key="created_date", text_keys=("claim",)) is None


def test_the_dossier_drops_a_held_open_position_and_counts_it():
    from web.site_api_coach_profile import _held_positions

    dossier = {
        "docket_positions": [
            {"date": "2026-09-23", "my_claim": GLUCOSE_DOCKET_CLAIM},
            {"date": "2026-09-23", "my_claim": NUTRITION_DOCKET_CLAIM},
        ],
        "withheld": 0,
    }
    out = _held_positions(dossier, CGM_DARK)
    assert [p["my_claim"] for p in out["docket_positions"]] == [NUTRITION_DOCKET_CLAIM]
    assert out["unsourced"] == 1 and out["withheld"] == 0, "not a privacy hit — its own count"
    assert _held_positions(dossier, []) is dossier


# ── the routes ─────────────────────────────────────────────────────────────────────────


def _presence_table(cgm_dark, extra=()):
    items = [sentinel_item(cgm_dark=cgm_dark), *fresh_instrument_rows(), *extra]
    return FakeDdbTable(store_items=items, query_hook=dispatching_query_hook)


def _resolved_specimen():
    item = glucose_docket_item()
    item.update(
        {
            "sk": "RESOLVED#2026-09-30#glucose_coach__nutrition_coach#recovery",
            "status": "resolved",
            "resolved_date": "2026-09-30",
            "winner": "nutrition_coach",
            "loser": "glucose_coach",
            "verdict": {"outcome": "graded", "winner": "nutrition_coach", "loser": "glucose_coach", "actual_value": 59},
            "concession": f'CONCESSION (2026-09-30) — I lost. My recorded claim: "{GLUCOSE_DOCKET_CLAIM}".',
        }
    )
    return item


class _Clock(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 10, 4, 12, 0, tzinfo=tz)


@pytest.fixture()
def api(monkeypatch):
    from health import instrument_presence
    from web import site_api_coach as sac

    real = instrument_presence.absent_coaches  # the SAME derivation the board runs, pinned to the corpus's instant
    monkeypatch.setattr(instrument_presence, "absent_coaches", lambda table, now=None, instruments=None: real(table, NOW, instruments))

    def wire(cgm_dark, docket_items=None):
        table = _presence_table(cgm_dark, docket_items if docket_items is not None else [_resolved_specimen()])
        monkeypatch.setattr(sac, "table", table)
        return sac

    return wire


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def test_the_docket_holds_the_resolved_specimen_and_names_why(api):
    sac = api(cgm_dark=True)
    entry = _body(sac.handle_coach_docket({}))["resolved"][0]
    assert entry["claims"] == {"nutrition_coach": NUTRITION_DOCKET_CLAIM}
    assert entry["unsourced"]["glucose_coach"]["text"] == HELD_SENTENCE
    assert entry["unsourced"]["glucose_coach"]["reason"] == ABSENT_REASON
    assert entry["sides"] == {"glucose_coach": False, "nutrition_coach": True}, "the bet itself stands"
    assert entry["concession"] is None and entry["concession_unsourced"]["said_on"] == "2026-09-23"


def test_mutation_control_the_docket_quotes_the_specimen_when_the_cgm_reads(api):
    sac = api(cgm_dark=False)
    entry = _body(sac.handle_coach_docket({}))["resolved"][0]
    assert entry["claims"]["glucose_coach"] == GLUCOSE_DOCKET_CLAIM
    assert "unsourced" not in entry and entry["concession"]


def test_a_bet_opened_before_the_last_reading_keeps_its_words(api):
    item = _resolved_specimen()
    item.update({"opened_date": "2026-08-20"})
    sac = api(cgm_dark=True, docket_items=[item])
    entry = _body(sac.handle_coach_docket({}))["resolved"][0]
    assert entry["claims"]["glucose_coach"] == GLUCOSE_DOCKET_CLAIM and "unsourced" not in entry


def test_an_open_item_keeps_the_4217_absence_and_gains_the_reason(api):
    sac = api(cgm_dark=True, docket_items=[glucose_docket_item()])
    entry = _body(sac.handle_coach_docket({}))["open"][0]
    assert entry["claims"] == {"nutrition_coach": NUTRITION_DOCKET_CLAIM}
    assert entry["absent"]["glucose_coach"]["reason"] == ABSENT_REASON
    assert entry["unsourced"]["glucose_coach"]["text"] == HELD_SENTENCE


def _wire_calls(monkeypatch, sac):
    rows, docket = _load("prediction_rows.json"), _load("docket_rows.json")
    monkeypatch.setattr(sac, "_fetch_prediction_partition", lambda pk: rows.get(pk.removeprefix("COACH#").removesuffix("_coach"), []))
    monkeypatch.setattr(sac, "_docket_rows", lambda prefix, limit, newest_first: docket["resolved" if prefix == "RESOLVED#" else "open"])
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-09-06")
    monkeypatch.setattr(sac, "datetime", _Clock)
    return sac


def test_the_bet_page_holds_the_side_and_prints_why(api, monkeypatch):
    sac = _wire_calls(monkeypatch, api(cgm_dark=True))
    call = _body(sac.handle_calls({"queryStringParameters": {"id": BET}}))["call"]
    sides = {s["coach_id"]: s for s in call["sides"]}
    assert sides["glucose"]["claim"] == "" and sides["glucose"]["unsourced"]["text"] == HELD_SENTENCE
    assert sides["glucose"]["said"] == "no" and sides["glucose"]["right"] is False, "the bet itself stands"
    assert sides["nutrition"]["claim"] == NUTRITION_DOCKET_CLAIM and "unsourced" not in sides["nutrition"]
    assert call["claim"] == NUTRITION_DOCKET_CLAIM


def test_mutation_control_the_bet_page_quotes_both_sides_when_the_cgm_reads(api, monkeypatch):
    sac = _wire_calls(monkeypatch, api(cgm_dark=False))
    call = _body(sac.handle_calls({"queryStringParameters": {"id": BET}}))["call"]
    assert {s["coach_id"]: s["claim"] for s in call["sides"]}["glucose"] == GLUCOSE_DOCKET_CLAIM
    assert not any("unsourced" in s for s in call["sides"])


def test_the_specimen_is_on_no_route_that_serves_a_docket_claim(api, monkeypatch):
    """The SET: every route body that carries docket claims, swept in one pass."""
    sac = _wire_calls(monkeypatch, api(cgm_dark=True))
    bodies = {
        "/api/coach_docket": sac.handle_coach_docket({}),
        "/api/calls": sac.handle_calls({"queryStringParameters": None}),
        f"/api/calls?id={BET}": sac.handle_calls({"queryStringParameters": {"id": BET}}),
    }
    offenders = [route for route, resp in bodies.items() if "based on CGM data" in json.dumps(_body(resp), ensure_ascii=False)]
    assert not offenders, f"a claim citing a sensor with no reading that day was served on: {offenders}"
    listed = _body(bodies["/api/calls"])
    assert BET in [c["id"] for c in listed["calls"]], "the bet keeps its page"


def test_a_failed_presence_read_fails_open_on_the_calls_route(monkeypatch):
    from health import instrument_presence
    from web import site_api_coach as sac

    def boom(table, now=None, instruments=None):
        raise RuntimeError("sentinel unreadable")

    monkeypatch.setattr(instrument_presence, "absent_coaches", boom)
    _wire_calls(monkeypatch, sac)
    body = _body(sac.handle_calls({"queryStringParameters": {"id": BET}}))
    assert body["state"] == "ok", "a broken presence read must not take the settled calls down"


# ── the coach page and roster: the same rule over their dated records ──────────────────


def test_the_coach_page_and_roster_hold_dated_words_citing_the_dark_sensor(monkeypatch):
    """Wiring, not the rule: /api/coach/<id> passes its recent outputs, stance history, latest
    checked call and dossier docket positions through the rule, and /api/coaches its latest
    checked call. Seeded with the live 2026-09-26 output specimen and the 2026-09-09 graded call."""
    from coach import latest_checked
    from web import site_api_coach as sac, site_api_coach_profile as prof

    state = {"source": "apple_health", "datatype": "cgm", "label": "CGM (glucose)", "dark": True}
    state.update({"last_seen": CGM_LAST_SEEN, "reason": ABSENT_REASON})
    checked = {"claim": "Nocturnal glucose dips will create a loop between CGM and sleep architecture.", "created_date": "2026-09-09"}
    monkeypatch.setattr(prof, "_absent_coaches", lambda _g: {"glucose_coach": dict(state)})
    monkeypatch.setattr(prof.instrument_presence, "gap_history", lambda table, now=None, instruments=None: [])  # the open gap decides
    monkeypatch.setattr(latest_checked, "for_coach", lambda table, pid: dict(checked))
    monkeypatch.setattr(
        sac, "_recent_outputs", lambda pid, limit=25: [{"date": "2026-09-26", "summary": GLUCOSE_POSITION_SUMMARY, "themes": ["CGM"]}]
    )
    monkeypatch.setattr(
        sac, "_stance_history", lambda pid, limit=8: [{"as_of": "2026-09-23", "headline_read": "The CGM is warming up.", "stage": {}}]
    )
    monkeypatch.setattr(sac, "_dossier_block", lambda pid: {"docket_positions": [{"date": "2026-09-23", "my_claim": GLUCOSE_DOCKET_CLAIM}]})

    page = _body(sac.handle_coach({"rawPath": "/api/coach/glucose_coach"}))
    assert page["absent"] is True and page["reason"] == ABSENT_REASON
    assert page["recent_outputs"][0]["summary"] == "" and page["recent_outputs"][0]["unsourced"]["said_on"] == "2026-09-26"
    assert page["stance_history"][0]["headline_read"] == "" and page["stance_history"][0]["unsourced"]
    assert page["latest_checked"]["claim"] == "" and page["latest_checked"]["unsourced"]["said_on"] == "2026-09-09"
    assert page["dossier"]["docket_positions"] == [] and page["dossier"]["unsourced"] == 1
    assert "CGM" not in json.dumps(page["recent_outputs"] + page["stance_history"]) + page["latest_checked"]["claim"]

    roster = _body(sac.handle_coaches({}))
    lines = [c["latest_checked"] for c in roster["coaches"] if c.get("tier") == "staff"]
    assert lines and all(lc["claim"] == "" and lc["unsourced"] for lc in lines), "the 2026-09-09 CGM sentence is on no roster card"
