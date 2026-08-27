"""tests/test_paused_narrative_dateline.py — a HELD narrative must be datelined
in the frame its own prose uses (measured live 2026-08-27).

THE DEFECT, as it actually happened. At 07:12 PT on 2026-08-27 the gating
visual-QA judge failed /coaching/by-coach/#physical_coach:

    Dr. Max Reyes states "I'm ten days into this restart with you — Day 10 as of
    today" but the experiment is on Day 11.

Ground truth from production /api/coach_analysis at the time:
`regeneration_paused: True`, `generated_at: 2026-08-26T17:02:28Z`, budget tier 2.
Genesis is 2026-08-17, so the text was written on Day 10 and served on Day 11.

The mechanism is a compounding one, and none of its three parts is a bug on its
own: (a) budget_guard pauses coach_narrative regeneration at tier >= 2 (ADR-125 —
correct, and it stays); (b) the frozen prose bakes an ABSOLUTE day number into
cacheable text, because "Day N" is the frame the coach is written in; (c) the
serving layer datelined that text in CALENDAR days only ("as of Aug 26"). A
reader cannot convert Aug 26 into Day 10, so the frozen "Day 10 as of today"
arrived unanchored — and gained one full day of error for every day the pause
lasted. An ADR-104 honest-numbers violation that worsens by itself.

THE FIX PINNED HERE: the payload carries the READ'S OWN day number, derived from
its timestamp, so the dateline can state both frames and the frozen sentence
reads as history instead of as a claim about today. Nothing here regenerates
anything, and nothing here relaxes the pause.

The properties, and the mutation each one kills:

  1. the 2026-08-27 replay — the measured shape yields as_of_day_n == 10;
  2. it is the CONTENT'S day, not TODAY'S — a `_current_day_n()` implementation
     (the obvious wrong wiring) fails 1 on every day except the day of writing;
  3. PACIFIC, not UTC — an instant at 05:00Z on the 27th is 22:00 PT on the 26th
     and is Day 10. A UTC-dated implementation says Day 11, which would make the
     dateline endorse the very error it exists to frame (the #2506/#2675 class,
     and the strptime/UTC-midnight class of #3196);
  4. unknown renders NOTHING — an unparseable or pre-genesis timestamp yields no
     day number at all, never Day 0, never a negative, never a guess (#1971's
     absent-is-unknown rule: a WRONG day number is strictly worse than none);
  5. the SET, not the instance — /api/coaches (the coaching door's first screen,
     the second coachAsOf call site) carries the same field;
  6. the front-end actually consumes it — a served field no renderer reads is
     the #2703 class (a fix that passes everything and does nothing).
"""

import json
import os
import re
import sys

os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("S3_BUCKET", "test-bucket")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "FAKE")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "FAKE")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from ai import budget_guard  # noqa: E402
from fakes import FakeDdbTable  # noqa: E402
from web import (
    site_api_coach as api,  # noqa: E402
    site_api_lambda as L,  # noqa: E402
)
from web.site_api_common import as_of_day_n  # noqa: E402

# The live cycle-14 genesis the 2026-08-27 incident ran under.
GENESIS = "2026-08-17"

# The exact production record shape, from the incident.
INCIDENT_GENERATED_AT = "2026-08-26T17:02:28Z"
INCIDENT_DAY = 10


def _body(resp):
    assert resp["statusCode"] == 200, resp
    return json.loads(resp["body"])


def _fake_query_first_call_only(item):
    """table.query stub: the OUTPUT# lookup returns `item`; every later read
    (threads/ensemble/computation/learning — each individually try/except'd)
    raises, exercising handle_coach_analysis's fail-soft secondary paths."""
    calls = {"n": 0}

    def _query(**kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"Items": [item]}
        raise RuntimeError("offline test — no secondary reads")

    return _query


def _analysis(monkeypatch, *, generated_at, tier=2, genesis=GENESIS):
    out_item = {
        "pk": "COACH#physical_coach",
        "sk": "OUTPUT#2026-08-26",
        "content": "I'm ten days into this restart with you — Day 10 as of today.",
        "created_at": generated_at,
    }
    monkeypatch.setattr(api, "EXPERIMENT_START", genesis)
    monkeypatch.setattr(api.table, "query", _fake_query_first_call_only(out_item))
    monkeypatch.setattr(api.table, "get_item", lambda Key: {})
    monkeypatch.setattr(budget_guard, "current_tier", lambda: tier)
    return _body(api.handle_coach_analysis({"queryStringParameters": {"domain": "physical"}}))


# ── 1/2. the replay: the content's own day, never today's ────────────────────


def test_replays_the_08_27_incident_the_held_read_carries_its_own_day(monkeypatch):
    data = _analysis(monkeypatch, generated_at=INCIDENT_GENERATED_AT)
    assert data["regeneration_paused"] is True, "the tier-2 pause is correct and must stay — this fix does not touch it"
    # A hard-coded 10 is the mutation guard for property 2: any implementation
    # that reads a clock (`_current_day_n()`, `datetime.now()`) instead of the
    # record's timestamp fails this on every day but 2026-08-26.
    assert data["as_of_day_n"] == INCIDENT_DAY, (
        f"the held read is from Day {INCIDENT_DAY} (generated {INCIDENT_GENERATED_AT}, genesis {GENESIS}) — "
        f"got {data.get('as_of_day_n')!r}"
    )
    assert data["generated_at"] == INCIDENT_GENERATED_AT


def test_the_day_number_tracks_the_record_not_the_wall_clock(monkeypatch):
    """Two records, one genesis, one process: the served day number must differ.
    A clock-derived implementation returns the same value for both."""
    a = _analysis(monkeypatch, generated_at="2026-08-18T14:00:00Z")["as_of_day_n"]
    b = _analysis(monkeypatch, generated_at="2026-08-26T14:00:00Z")["as_of_day_n"]
    assert (a, b) == (2, 10), f"expected (Day 2, Day 10) from the two timestamps, got ({a}, {b})"


# ── 3. PACIFIC, not UTC — the must-fail case ─────────────────────────────────


def test_the_evening_pt_instant_is_yesterdays_day_not_todays():
    """05:00Z on 2026-08-27 is 22:00 PT on 2026-08-26 — Day 10.

    This is the negative control that actually fails: a UTC-dated implementation
    returns 11 here, which would print "Day 11" over prose that says "Day 10" and
    make the dateline endorse the error it exists to frame. The site's day frame
    is Pacific (#2506/#2675) and so is this."""
    assert as_of_day_n("2026-08-27T05:00:00Z", GENESIS) == 10
    # ... and the control's control: the same wall-clock hour on the NEXT PT day
    # really is Day 11, so the rule is a conversion, not a blanket decrement.
    assert as_of_day_n("2026-08-28T05:00:00Z", GENESIS) == 11


def test_a_naive_timestamp_is_read_as_utc_then_converted():
    # Writers emit UTC; a value that lost its suffix must not silently become PT.
    assert as_of_day_n("2026-08-27T05:00:00", GENESIS) == 10


def test_a_bare_calendar_date_is_already_a_pt_day():
    # The OUTPUT# sk fallback (`OUTPUT#{YYYY-MM-DD}`) the dashboard uses.
    assert as_of_day_n("2026-08-26", GENESIS) == 10


# ── 4. unknown renders nothing — never Day 0, never a guess ──────────────────


def test_unknown_and_pregenesis_timestamps_yield_no_day_number():
    for bad in ("", None, "not-a-date", "   ", 20260826, {"t": 1}):
        assert as_of_day_n(bad, GENESIS) is None, f"{bad!r} must be UNKNOWN, not a day number"
    # Pre-genesis: a prior-cycle record must not print "Day 0" or "Day -3".
    assert as_of_day_n("2026-08-16T23:00:00Z", GENESIS) is None
    assert as_of_day_n("2026-08-17T12:00:00Z", GENESIS) == 1, "genesis day itself is Day 1, not Day 0"
    # An unusable genesis is unknown too, never an exception out of a read path.
    assert as_of_day_n(INCIDENT_GENERATED_AT, "") is None


def test_the_endpoint_omits_the_key_entirely_when_the_day_is_unknown(monkeypatch):
    """`resp` strips None, so an unknown day is an ABSENT key — the front-end's
    absent-is-unknown reader then renders nothing at all (#1971), rather than a
    fabricated Day 0."""
    data = _analysis(monkeypatch, generated_at="not-a-date")
    assert "as_of_day_n" not in data


# ── 5. the SET: the coaching door's first screen carries it too ──────────────


def test_the_dashboard_card_carries_the_same_day_field(monkeypatch):
    """/api/coaches feeds the second coachAsOf call site. #1971's own lesson was
    that #802 wired ONE surface and left the door's first screen lying; this
    field must not repeat that."""
    monkeypatch.setattr(L, "table", FakeDdbTable())
    monkeypatch.setattr(L, "_integrator_digest", lambda: None)
    monkeypatch.setattr(budget_guard, "current_tier", lambda: 2)
    resp = L.lambda_handler({"rawPath": "/api/coaching-dashboard", "requestContext": {"http": {"method": "GET"}}}, None)
    body = json.loads(resp["body"])
    coaches = body.get("coaches") or []
    assert coaches, "the dashboard payload must carry coach entries to stamp"
    for c in coaches:
        assert "analysis_as_of_day_n" in c, f"{c.get('coach_id')} card has no day-number stamp"


# ── 6. the renderer actually reads it (the #2703 class) ──────────────────────

_JS = os.path.join(_REPO, "site", "assets", "js")


def _read(name):
    with open(os.path.join(_JS, name), encoding="utf-8") as fh:
        return fh.read()


def test_every_coachasof_call_site_passes_a_day_number():
    """A served field no renderer reads is a fix that passes its tests and does
    nothing. Every coachAsOf(...) call in site/assets/js must pass a THIRD
    argument — and never a literal, the #1971 set-guard idiom."""
    offenders = []
    for fn in sorted(os.listdir(_JS)):
        if not fn.endswith(".js") or fn == "coach_asof.js":
            continue
        for m in re.finditer(r"coachAsOf\(([^)]*)\)", _read(fn)):
            args = [a.strip() for a in m.group(1).split(",")]
            if len(args) < 3:
                offenders.append(f"{fn}: coachAsOf({m.group(1)}) — no day-number argument")
            elif re.fullmatch(r"\d+|true|false|null|undefined", args[2]):
                offenders.append(f"{fn}: coachAsOf({m.group(1)}) — day number hardcoded as a literal")
    assert not offenders, "\n".join(offenders)


def test_the_by_coach_dateline_leads_the_prose_and_the_kicker_stops_saying_this_week():
    """Position is part of the fix: a dateline a reader meets AFTER the claim it
    frames is a footnote, not a frame. And "· this week" over a held read is the
    present-tense half of the same untruth."""
    src = _read("coaching.js")
    assert "bc-asof" in src and "bc-analysis" in src, "the by-coach read lost its as-of stamp or its prose block"
    assert src.index("bc-asof") < src.index("bc-analysis"), "the as-of dateline must render ABOVE the coach's prose, not below it"
    assert "bc-dateline" in src, "the dateline needs its own class — .bc-asof's trailing margin is wrong above the prose"
    assert (
        "· this week" not in src.split("bc-read")[1].split("</section>")[0] or 'regenPaused ? "" : " · this week"' in src
    ), 'the by-coach kicker must drop "· this week" while regeneration is paused'
