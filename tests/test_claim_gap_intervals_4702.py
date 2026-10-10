"""tests/test_claim_gap_intervals_4702.py — a coach claim said during a sensor gap stays held after the sensor reports again (#4702).

#4673 (PR #4698) held a dated coach text that cites an instrument when the instrument was
dark NOW and the text was dated after its current `last_seen`. The sentinel keeps only the
last reading, so the moment the CGM reported again the gap from 2026-08-27 vanished and the
specimen — Amara Patel's side of `bet-20260930-994b3d89f6`, "…based on CGM data…", said on
2026-09-23 — would have been quoted again on every route.

The fix decides against GAP INTERVALS per instrument: the open one (`absent_coaches`) plus
every closed one `instrument_presence.gap_history` derives from the stored DATE# rows.

Fixtures are the wire: the DATATYPE_LIVENESS sentinel shape and the apple_health DATE# row
shape (`blood_glucose_avg`, the registry's cgm field) from `instrument_presence_fixture`,
the PREDICTION# partitions and ENSEMBLE#docket rows in `fixtures/calls_wire_4586/`. The CGM
reading days before the gap are the live ones (read 2026-10-09: 2026-08-18…08-24, 08-26,
08-27); the days after it are the "reports again" this issue is about. Every route
assertion has a MUTATION CONTROL: the same routes over a CGM with no gap quote the words.
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "tests"))

from fakes import FakeDdbTable  # noqa: E402
from instrument_presence_fixture import (  # noqa: E402
    APPLE_HEALTH_PK,
    CGM_LAST_SEEN,
    GLUCOSE_DOCKET_CLAIM,
    NUTRITION_DOCKET_CLAIM,
    dispatching_query_hook,
    fresh_instrument_rows,
    glucose_docket_item,
    sentinel_item,
)
from web import claim_sourcing  # noqa: E402

BET = "bet-20260930-994b3d89f6"
BACK_ON = "2026-10-05"  # the CGM's first reading after the gap
NOW = datetime(2026, 10, 9, 20, 0, tzinfo=timezone.utc)
TODAY = "2026-10-09"
_WIRE = _REPO / "tests" / "fixtures" / "calls_wire_4586"
HELD_SENTENCE = (
    "Not quoted: this was said on September 23 and rests on his glucose sensor, "
    "which had sent no reading since August 27 and did not report again until October 5."
)
CLOSED = [
    {
        "source": "apple_health",
        "datatype": "cgm",
        "label": "CGM (glucose)",
        "gaps": [{"start": CGM_LAST_SEEN, "end": BACK_ON, "reason": f"no sensor from {CGM_LAST_SEEN} to {BACK_ON}"}],
    }
]

#: The live CGM reading days before the gap (DynamoDB, 2026-10-09).
_BEFORE = ["2026-08-18", "2026-08-19", "2026-08-20", "2026-08-21", "2026-08-22", "2026-08-23", "2026-08-24", "2026-08-26", CGM_LAST_SEEN]
_AFTER = ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", TODAY]


def _days(lo: str, hi: str) -> list[str]:
    from datetime import date, timedelta

    a, b = date.fromisoformat(lo), date.fromisoformat(hi)
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def _cgm_row(day: str) -> dict:
    return {"pk": APPLE_HEALTH_PK, "sk": f"DATE#{day}", "blood_glucose_avg": 104, "blood_glucose_readings_count": 96, "steps": 9000}


def _steps_only(day: str) -> dict:
    """The partition stays alive on steps through the gap — that is NOT a CGM reading."""
    return {"pk": APPLE_HEALTH_PK, "sk": f"DATE#{day}", "steps": 8000}


def _live_again_sentinel() -> dict:
    """The checker's sentinel the day the CGM is live again: cgm not dark, last_seen today."""
    item = sentinel_item(cgm_dark=False)
    item["datatypes"][0] = {**item["datatypes"][0], "last_seen": TODAY, "age_days": 0, "dark": False}
    return item


def _store(gap: bool, extra=()) -> list:
    cgm_days = _BEFORE + _AFTER if gap else _days(_BEFORE[0], TODAY)
    filler = [_steps_only(d) for d in _days("2026-08-28", "2026-10-04")] if gap else []
    return [_live_again_sentinel(), *fresh_instrument_rows(TODAY), *[_cgm_row(d) for d in cgm_days], *filler, *extra]


def _resolved_specimen(opened: str = "2026-09-23") -> dict:
    item = glucose_docket_item()
    item.update(
        {
            "sk": "RESOLVED#2026-09-30#glucose_coach__nutrition_coach#recovery",
            "status": "resolved",
            "opened_date": opened,
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
        return datetime(2026, 10, 9, 12, 0, tzinfo=tz)


@pytest.fixture()
def sac(monkeypatch):
    """The site-api facade with presence pinned to NOW — the REAL `absent_coaches` and the
    REAL `gap_history`, so the routes run the production derivation over the fake table."""
    from health import instrument_presence
    from web import site_api_coach

    real_absent, real_history = instrument_presence.absent_coaches, instrument_presence.gap_history
    monkeypatch.setattr(
        instrument_presence, "absent_coaches", lambda table, now=None, instruments=None: real_absent(table, NOW, instruments)
    )
    monkeypatch.setattr(instrument_presence, "gap_history", lambda table, now=None, instruments=None: real_history(table, NOW, instruments))
    rows = json.loads((_WIRE / "prediction_rows.json").read_text(encoding="utf-8"))
    docket = json.loads((_WIRE / "docket_rows.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(
        site_api_coach, "_fetch_prediction_partition", lambda pk: rows.get(pk.removeprefix("COACH#").removesuffix("_coach"), [])
    )
    monkeypatch.setattr(
        site_api_coach, "_docket_rows", lambda prefix, limit, newest_first: docket["resolved" if prefix == "RESOLVED#" else "open"]
    )
    monkeypatch.setattr(site_api_coach, "EXPERIMENT_START", "2026-09-06")
    monkeypatch.setattr(site_api_coach, "datetime", _Clock)

    def wire(gap: bool, extra=()):
        monkeypatch.setattr(site_api_coach, "table", FakeDdbTable(store_items=_store(gap, extra), query_hook=dispatching_query_hook))
        return site_api_coach

    return wire


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


# ── the derivation: gap intervals per instrument, from stored rows ─────────────────────


def test_every_coach_instrument_gets_a_gap_list_and_the_cgm_gap_is_derived_from_its_rows():
    from health import instrument_presence
    from ingestion.source_registry import coach_instruments

    table = FakeDdbTable(store_items=_store(gap=True), query_hook=dispatching_query_hook)
    history = instrument_presence.gap_history(table, NOW)
    keys = {(i["source"], i.get("datatype") or None) for i in coach_instruments().values()}
    assert {(h["source"], h["datatype"]) for h in history} == keys, "every coach instrument has a gap list"
    by = {(h["source"], h["datatype"]): h["gaps"] for h in history}
    assert by[("apple_health", "cgm")] == CLOSED[0]["gaps"], "a steps-only day is not a CGM reading"
    assert by[("whoop", None)] == [], "a source with one reading day has no closed gap"
    for behavioral in ("macrofactor", "hevy", "labs"):
        assert by[(behavioral, None)] == [], f"{behavioral} can never be dark, so it has no gaps"


def test_closed_gaps_only_past_the_instruments_own_dark_threshold():
    from health import instrument_presence

    days = ["2026-08-24", "2026-08-26", "2026-08-27", "2026-10-05"]
    assert instrument_presence.closed_gaps(days, 3.0) == [
        {"start": "2026-08-27", "end": "2026-10-05", "reason": "no sensor from 2026-08-27 to 2026-10-05"}
    ]
    assert instrument_presence.closed_gaps(days, None) == []
    assert instrument_presence.gap_threshold_days({"source": "apple_health", "datatype": "cgm"}) == 3.0
    assert instrument_presence.gap_threshold_days({"source": "hevy", "datatype": None, "behavioral": True}) is None


def test_a_failed_history_read_fails_open_and_never_raises():
    from health import instrument_presence

    class Boom:
        def query(self, **_):
            raise RuntimeError("throttled")

    history = instrument_presence.gap_history(Boom(), NOW)
    assert history and all(h["gaps"] == [] for h in history)


# ── the rule: a closed gap holds, whatever the instrument's state is now ───────────────


def test_the_specimen_said_inside_a_closed_gap_is_held_and_the_sentence_names_both_ends():
    note = claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], "2026-09-23", CLOSED)
    assert note == {
        "reason": f"no sensor from {CGM_LAST_SEEN} to {BACK_ON}",
        "instrument": {"source": "apple_health", "datatype": "cgm"},
        "last_seen": CGM_LAST_SEEN,
        "gap": {"start": CGM_LAST_SEEN, "end": BACK_ON},
        "said_on": "2026-09-23",
        "text": HELD_SENTENCE,
    }


def test_a_text_dated_outside_the_gap_or_on_a_reading_day_is_quoted():
    for day in ("2026-08-20", CGM_LAST_SEEN, BACK_ON, "2026-10-07"):
        assert claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], day, CLOSED) is None, day


def test_the_decision_reads_gaps_never_a_bare_last_seen():
    """A row in the old now-only shape (a `last_seen`, no `gaps`) holds nothing: the
    interval form is the only input the rule reads."""
    legacy = [{"source": "apple_health", "datatype": "cgm", "label": "CGM (glucose)", "last_seen": CGM_LAST_SEEN, "reason": "x"}]
    assert claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], "2026-09-23", legacy) is None


def test_open_and_closed_gaps_merge_per_instrument():
    absent = {
        "glucose_coach": {"source": "apple_health", "datatype": "cgm", "label": "CGM (glucose)", "last_seen": "2026-10-20", "reason": "r"}
    }
    rows = claim_sourcing.gap_instruments(absent, CLOSED)
    assert len(rows) == 1 and [g["end"] for g in rows[0]["gaps"]] == [BACK_ON, None]
    assert claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], "2026-09-23", rows)["gap"]["end"] == BACK_ON
    assert claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], "2026-10-25", rows)["gap"]["end"] is None
    assert claim_sourcing.unsourced([GLUCOSE_DOCKET_CLAIM], "2026-10-10", rows) is None


# ── the routes: every #4698 route plus /api/predictions, the CGM live again ────────────


def _routes(sac_mod) -> dict:
    return {
        "/api/coach_docket": sac_mod.handle_coach_docket({}),
        "/api/calls": sac_mod.handle_calls({"queryStringParameters": None}),
        f"/api/calls?id={BET}": sac_mod.handle_calls({"queryStringParameters": {"id": BET}}),
        "/api/predictions": sac_mod.handle_predictions({"queryStringParameters": {"limit": "200"}}),
    }


def test_the_specimen_stays_held_on_every_route_with_the_cgm_live_again(sac):
    from health import instrument_presence

    s = sac(gap=True)  # the docket rows are the wire's, which hold the specimen bet
    assert instrument_presence.absent_coaches(s.table) == {}, "the CGM is live again: nothing is dark now"
    bodies = {route: _body(resp) for route, resp in _routes(s).items()}
    offenders = [route for route, body in bodies.items() if "based on CGM data" in json.dumps(body, ensure_ascii=False)]
    assert not offenders, f"words said during the closed CGM gap were quoted on: {offenders}"

    entry = bodies["/api/coach_docket"]["resolved"][0]
    assert entry["claims"] == {"nutrition_coach": NUTRITION_DOCKET_CLAIM}
    assert entry["unsourced"]["glucose_coach"]["text"] == HELD_SENTENCE
    sides = {x["coach_id"]: x for x in bodies[f"/api/calls?id={BET}"]["call"]["sides"]}
    assert sides["glucose"]["claim"] == "" and sides["glucose"]["unsourced"]["text"] == HELD_SENTENCE
    held = [p for p in bodies["/api/predictions"]["predictions"] if p.get("unsourced")]
    assert any(p["coach_id"] == "glucose" and p["unsourced"]["gap"] == {"start": CGM_LAST_SEEN, "end": BACK_ON} for p in held)


def test_mutation_control_with_no_gap_on_record_every_route_quotes_the_specimen(sac):
    s = sac(gap=False)
    bodies = {route: _body(resp) for route, resp in _routes(s).items()}
    assert bodies["/api/coach_docket"]["resolved"][0]["claims"]["glucose_coach"] == GLUCOSE_DOCKET_CLAIM
    sides = {x["coach_id"]: x for x in bodies[f"/api/calls?id={BET}"]["call"]["sides"]}
    assert sides["glucose"]["claim"] == GLUCOSE_DOCKET_CLAIM
    assert not [p for p in bodies["/api/predictions"]["predictions"] if p.get("unsourced")]


def test_a_bet_opened_before_the_gap_keeps_its_words_with_the_gap_on_record(sac, monkeypatch):
    s = sac(gap=True)
    early = _resolved_specimen(opened="2026-08-20")
    monkeypatch.setattr(s, "_docket_rows", lambda prefix, limit, newest_first: [early] if prefix == "RESOLVED#" else [])
    entry = _body(s.handle_coach_docket({}))["resolved"][0]
    assert entry["claims"]["glucose_coach"] == GLUCOSE_DOCKET_CLAIM and "unsourced" not in entry


def test_the_coach_page_and_roster_hold_a_closed_gap_too(sac, monkeypatch):
    from coach import latest_checked
    from web import site_api_coach_profile as prof

    s = sac(gap=True)
    monkeypatch.setattr(
        latest_checked, "for_coach", lambda table, pid: {"claim": "His CGM trace shows a flat line.", "created_date": "2026-09-09"}
    )
    monkeypatch.setattr(
        s, "_recent_outputs", lambda pid, limit=25: [{"date": "2026-09-26", "summary": "His CGM is generating traces.", "themes": []}]
    )
    monkeypatch.setattr(
        s, "_stance_history", lambda pid, limit=8: [{"as_of": "2026-10-06", "headline_read": "The CGM is back.", "stage": {}}]
    )
    monkeypatch.setattr(s, "_dossier_block", lambda pid: {"docket_positions": [{"date": "2026-09-23", "my_claim": GLUCOSE_DOCKET_CLAIM}]})
    assert prof._absent_coaches({"table": s.table}) == {}, "the CGM is live again"
    page = _body(s.handle_coach({"rawPath": "/api/coach/glucose_coach"}))
    assert page["absent"] is False
    assert page["recent_outputs"][0]["summary"] == "" and page["recent_outputs"][0]["unsourced"]["gap"]["end"] == BACK_ON
    assert page["latest_checked"]["claim"] == "" and page["latest_checked"]["unsourced"]["said_on"] == "2026-09-09"
    assert page["stance_history"][0]["headline_read"] == "The CGM is back.", "said after the sensor reported again: quoted"
    assert page["dossier"]["docket_positions"] == [] and page["dossier"]["unsourced"] == 1
    roster = _body(s.handle_coaches({}))
    assert all(c["latest_checked"]["claim"] == "" for c in roster["coaches"] if c.get("tier") == "staff")


#: The route modules #4698 and #4701 put the hold on. Each must build the interval form.
_ROUTE_MODULES = ("site_api_calls.py", "site_api_coach_ledger.py", "site_api_coach_profile.py")


def test_every_hold_route_reads_the_interval_form_and_none_reads_last_seen_for_the_decision():
    web = _REPO / "lambdas" / "web"
    offenders = {}
    for name in _ROUTE_MODULES:
        src = (web / name).read_text(encoding="utf-8")
        problems = []
        if not re.search(r"claim_sourcing\.gap_instruments\(", src):
            problems.append("never builds claim_sourcing.gap_instruments(...)")
        if not re.search(r"gap_history\(", src):
            problems.append("never reads instrument_presence.gap_history (closed gaps)")
        if "dark_instruments" in src:
            problems.append("still reads the now-only dark_instruments form")
        if "last_seen" in src:
            problems.append("reads last_seen directly")
        if problems:
            offenders[name] = problems
    assert not offenders, offenders
    rule = (web / "claim_sourcing.py").read_text(encoding="utf-8")
    body = rule.split("def unsourced(", 1)[1].split("\ndef ", 1)[0]
    assert 'inst.get("last_seen")' not in body, "unsourced decides on gaps, never on an instrument's last_seen"
