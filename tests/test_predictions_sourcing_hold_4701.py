"""tests/test_predictions_sourcing_hold_4701.py — the predictions ledger applies the #4673 sourcing hold (#4701).

PR #4698 (#4673) held a dated coach claim that cites an instrument with no reading by the
claim's date on /api/coach_docket, /api/calls, /api/coach/<id> and /api/coaches — and not on
/api/predictions, which served every PREDICTION# row's `claim_natural` verbatim. So the call
page withheld a claim the ledger still quoted.

Fixtures are the wire: `instrument_presence_fixture` (the live 2026-09-26 liveness sentinel,
cgm dark since 2026-08-27) and `fixtures/calls_wire_4586/prediction_rows.json` (the PREDICTION#
partitions read from DynamoDB 2026-10-04). Two specimens from that read:

  * physical, 2026-09-13 — "Nocturnal CGM dips may be driving a cortisol counter-regulation
    pattern…", a dated in-cycle call;
  * glucose, the docket side of `bet-20260930-994b3d89f6` — "…based on CGM data…". A
    dispute-docket row carries NO `created_date`; its words were said on the docket's
    `opened_date`, the `prediction_id` suffix (2026-09-23).

Every route assertion has a MUTATION CONTROL: the same rows with the checker's `dark` verdict
flipped on cgm alone quote the words again.
"""

from __future__ import annotations

import json
import os
import re
import sys
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
    ABSENT_REASON,
    CGM_LAST_SEEN,
    NOW,
    dispatching_query_hook,
    fresh_instrument_rows,
    sentinel_item,
)
from web import claim_sourcing  # noqa: E402

_WIRE = _REPO / "tests" / "fixtures" / "calls_wire_4586"
PHYSICAL_CGM = "Nocturnal CGM dips may be driving a cortisol counter-regulation pattern"
DOCKET_CGM = "Evening carb reduction is likely coming based on CGM data"
DOCKET_PID = "docket-glucose_coach__nutrition_coach-recovery-carb-reduction-recommendation-will-it-degrade-recovery-or-im-2026-09-23"


def _rows():
    return json.loads((_WIRE / "prediction_rows.json").read_text(encoding="utf-8"))


@pytest.fixture()
def ledger(monkeypatch):
    """/api/predictions over the wire partitions, presence read from a fake table whose cgm
    `dark` verdict the caller chooses — through the REAL `absent_coaches`, pinned to the
    corpus's instant."""
    from health import instrument_presence
    from web import site_api_coach as sac

    real = instrument_presence.absent_coaches
    monkeypatch.setattr(instrument_presence, "absent_coaches", lambda table, now=None, instruments=None: real(table, NOW, instruments))
    rows = _rows()
    monkeypatch.setattr(sac, "_fetch_prediction_partition", lambda pk: rows.get(pk.removeprefix("COACH#").removesuffix("_coach"), []))
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-09-06")

    def serve(cgm_dark, qs=None):
        table = FakeDdbTable(store_items=[sentinel_item(cgm_dark=cgm_dark), *fresh_instrument_rows()], query_hook=dispatching_query_hook)
        monkeypatch.setattr(sac, "table", table)
        resp = sac.handle_predictions({"queryStringParameters": {"limit": "200", **(qs or {})}})
        assert resp["statusCode"] == 200, resp
        return json.loads(resp["body"])

    return serve


def _by_said(body, coach_id, date):
    return [p for p in body["predictions"] if p["coach_id"] == coach_id and p["date"] == date]


# ── the rule's date: a docket row is dated by the docket's opened_date ─────────────────


def test_claim_day_reads_created_date_then_the_docket_suffix_and_never_guesses():
    assert claim_sourcing.claim_day({"created_date": "2026-09-13", "prediction_id": "pred_x"}) == "2026-09-13"
    assert claim_sourcing.claim_day({"source": "dispute_docket", "prediction_id": DOCKET_PID}) == "2026-09-23"
    assert claim_sourcing.claim_day({"prediction_id": DOCKET_PID}) is None, "only a docket-sourced row is dated by its id"
    assert claim_sourcing.claim_day({"source": "dispute_docket", "prediction_id": "docket-ref-notadate"}) is None
    assert claim_sourcing.claim_day({}) is None and claim_sourcing.claim_day(None) is None


# ── the route ──────────────────────────────────────────────────────────────────────────


def test_the_ledger_holds_a_dated_call_citing_the_dark_cgm_and_keeps_its_record(ledger):
    body = ledger(cgm_dark=True)
    (held,) = [p for p in _by_said(body, "physical", "2026-09-13") if p.get("unsourced")]
    assert held["text"] == "", "held words are removed, never quoted"
    assert held["status"] == "refuted" and held["date"] == "2026-09-13", "the row keeps its date and its verdict"
    assert held["unsourced"] == {
        "reason": ABSENT_REASON,
        "instrument": {"source": "apple_health", "datatype": "cgm"},
        "last_seen": CGM_LAST_SEEN,
        "gap": {"start": CGM_LAST_SEEN, "end": None},  # #4702: the gap it fell in (open)
        "said_on": "2026-09-13",
        "text": "Not quoted: this was said on September 13 and rests on his glucose sensor, which had sent no reading since August 27.",
    }
    assert body["by_coach"]["physical"]["record"] == ledger(cgm_dark=False)["by_coach"]["physical"]["record"], "the record is unchanged"


def test_the_docket_specimen_is_held_by_its_opened_date(ledger):
    body = ledger(cgm_dark=True)
    held = [p for p in body["predictions"] if p["coach_id"] == "glucose" and (p.get("unsourced") or {}).get("said_on") == "2026-09-23"]
    assert len(held) == 1 and held[0]["text"] == "" and held[0]["status"] == "refuted"


def test_no_text_citing_the_dark_cgm_after_its_last_reading_is_quoted(ledger):
    """The SET over the whole served ledger, not the two specimens: every quoted row that cites
    the CGM is dated on or before its last reading."""
    body = ledger(cgm_dark=True)
    offenders = [
        (p["coach_id"], p["date"], p["text"][:60])
        for p in body["predictions"]
        if claim_sourcing.cites(p["text"], "apple_health", "cgm") and not (p["date"] and p["date"] <= CGM_LAST_SEEN)
    ]
    assert not offenders, f"/api/predictions quoted a claim citing the dark CGM: {offenders}"
    assert DOCKET_CGM not in json.dumps(body, ensure_ascii=False)
    assert PHYSICAL_CGM not in json.dumps(body, ensure_ascii=False)


def test_mutation_control_the_ledger_quotes_them_when_the_cgm_reads(ledger):
    body = ledger(cgm_dark=False)
    assert not any("unsourced" in p for p in body["predictions"])
    served = json.dumps(body, ensure_ascii=False)
    assert PHYSICAL_CGM in served and DOCKET_CGM in served


def test_a_call_citing_no_dark_instrument_is_quoted_unchanged(ledger):
    body = ledger(cgm_dark=True)
    recovery = [p for p in body["predictions"] if p["text"].startswith("Recovery score will be 66.2% tomorrow")]
    assert recovery and all("unsourced" not in p for p in recovery)


def test_the_coach_filter_holds_too(ledger):
    body = ledger(cgm_dark=True, qs={"coach_id": "physical"})
    assert [p for p in body["predictions"] if p.get("unsourced")], "the per-coach read (ck_coach.js) applies the hold"
    assert PHYSICAL_CGM not in json.dumps(body, ensure_ascii=False)


def test_a_failed_presence_read_fails_open_and_is_not_a_failed_partition(monkeypatch):
    from health import instrument_presence
    from web import site_api_coach as sac

    def boom(table, now=None, instruments=None):
        raise RuntimeError("sentinel unreadable")

    rows = _rows()
    monkeypatch.setattr(instrument_presence, "absent_coaches", boom)
    monkeypatch.setattr(sac, "_fetch_prediction_partition", lambda pk: rows.get(pk.removeprefix("COACH#").removesuffix("_coach"), []))
    monkeypatch.setattr(sac, "EXPERIMENT_START", "2026-09-06")
    monkeypatch.setattr(sac, "table", FakeDdbTable(query_hook=lambda table, **kw: {"Items": []}))
    resp = sac.handle_predictions({"queryStringParameters": {"limit": "200", "coach_id": "physical"}})
    assert resp["statusCode"] == 200, "a broken presence read must not take the ledger down"
    assert PHYSICAL_CGM in resp["body"], "fail-open: nothing is held when presence is unknown"


# ── #1527: the presence read adds no serial round trip ─────────────────────────────────


def test_the_presence_read_rides_the_one_concurrent_round(monkeypatch):
    """The handler issues ONE `_parallel_fetch` round, and the presence read is a job IN it
    beside every coach partition — never a read before or after the round."""
    from web import site_api_coach as sac, site_api_coach_ledger as led

    rounds = []
    real = sac._parallel_fetch

    def spy(jobs, *, failures=None):
        rounds.append(sorted(jobs))
        return real(jobs, failures=failures)

    presence_calls = []
    monkeypatch.setattr(sac, "_parallel_fetch", spy)
    monkeypatch.setattr(led, "_instrument_presence_safe", lambda *, _g: presence_calls.append(1) or {})
    monkeypatch.setattr(sac, "table", FakeDdbTable(query_hook=lambda table, **kw: {"Items": []}))
    resp = sac.handle_predictions({})
    assert resp["statusCode"] == 200
    assert len(rounds) == 1, f"expected one concurrent round, saw {len(rounds)}"
    assert led.PRESENCE_JOB in rounds[0] and len(rounds[0]) == len(led._CALIB_COACH_NAMES) + 1, rounds[0]
    assert len(rounds[0]) <= 9, "the round must fit the pool's 9 workers in one wave"
    assert presence_calls == [1], "presence is read once, inside the round"


# ── the SET: every claim_natural reader on a web route ─────────────────────────────────

#: Every lambdas/web module that reads `claim_natural`, and why it is covered.
#: "hold" means it routes the words through web.claim_sourcing; anything else is the reason
#: it is exempt. A new reader fails the sweep below until it is classified here.
CLAIM_NATURAL_READERS = {
    "site_api_coach_ledger.py": "hold",  # /api/predictions (#4701); the docket (#4673)
    "site_api_calls.py": "hold",  # /api/calls build_call (#4673)
    "site_api_diary.py": (
        "exempt: diary_claims (`USER#…#diary_claims`) are Matthew's OWN on-tape forecasts, not a coach "
        "speaking from an instrument; the hold is about a coach claim resting on a dark sensor, and his "
        "words are already gated by consent (visibility == public) and the #2206 dossier screen"
    ),
}


def test_every_claim_natural_reader_applies_the_hold_or_names_why_not():
    # A READ is the field named as a string literal (`row.get("claim_natural")`, a projection
    # tuple, an allowlist) — prose that merely mentions the field in backticks is not one.
    literal = re.compile(r"""["']claim_natural["']""")
    readers = sorted(p.name for p in (_REPO / "lambdas" / "web").glob("*.py") if literal.search(p.read_text(encoding="utf-8")))
    unclassified = sorted(set(readers) - set(CLAIM_NATURAL_READERS))
    assert not unclassified, f"a new claim_natural reader must apply web.claim_sourcing or name its exemption here: {unclassified}"
    stale = sorted(set(CLAIM_NATURAL_READERS) - set(readers))
    assert not stale, f"classified readers that no longer read claim_natural: {stale}"
    for name, verdict in CLAIM_NATURAL_READERS.items():
        src = (_REPO / "lambdas" / "web" / name).read_text(encoding="utf-8")
        if verdict == "hold":
            assert re.search(r"claim_sourcing\.unsourced\(", src), f"{name} is classified 'hold' but never calls claim_sourcing.unsourced"
        else:
            assert verdict.startswith("exempt: ") and len(verdict) > 40, f"{name}: an exemption needs a reason"
