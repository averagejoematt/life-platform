"""tests/test_pt_evening_email_frame_2817.py — the PT-EVENING INSTANT proof for the email fleet (#2817, epic #2798).

WHAT THIS FILE IS FOR
─────────────────────
#2817's third acceptance box: *"a PT-evening-instant test covers freshness_checker's
staleness math and the chronicle sender's day selection."* Everything else in that issue
was a SHAPE sweep — PR #3196 converted 149 naive-UTC-day sites across `lambdas/emails/`
and `mcp/` to `pacific_now()`/`pacific_today()`, and
`tests/test_utc_day_fleet_ratchet_2811.py` holds the shape at zero. **A shape guard is
not a behaviour guard** (#2798 says this about pairs; it is just as true about frames).
This file drives the two named modules at ONE frozen PT-evening instant and asserts the
ANSWER, not the syntax.

THE INSTANT, AND WHY IT IS A CONSTANT
─────────────────────────────────────
``_EVENING_UTC = 2026-08-27T05:30Z`` is 22:30 **PDT on 2026-08-26** — inside the
17:00-24:00 PT window where the UTC and Pacific calendars name different days, which is
exactly the window every one of these crons never runs in (they fire 15:00-18:00 UTC,
i.e. 08:00-11:00 PT, where the calendars agree) and therefore the window CI has
historically never sampled. It is a hard-coded constant, never `now()`: #3222 (PR #3227)
is the incident where a fixture computed its expectation on a different clock than its
handler and failed 7 hours of every 24, and #3206 shipped green because its CI happened
to run at 13:00 PT and broke `main` 24 hours later on someone else's commit. A test about
a time bomb must not be one. `test_the_frozen_instant_is_actually_inside_the_failure_window`
below asserts the constant still straddles a day boundary, so editing it into a harmless
hour reds this file instead of silently retiring it.

EXPECTATIONS COME FROM THE HANDLER'S OWN CLOCK
──────────────────────────────────────────────
Every fixture day below is derived from the Pacific instant `freeze_pacific()` returns —
i.e. the value the handler's own patched `pacific_now()` yields — never from a
hand-written `"2026-08-26"` literal and never from a second Pacific derivation. That is
#3222's rule stated as code: the fixture and the handler read one clock.

THE DEFECT THIS FILE PINS (found by hand, invisible to BOTH matchers)
─────────────────────────────────────────────────────────────────────
`freshness_checker_lambda.py` anchored the day it read off a `DATE#` sort key at **UTC
midnight** while comparing it against a **Pacific** `now`:

    last_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    age_hours = (now - last_date).total_seconds() / 3600     # now = pacific_now()

`DATE#` keys name Pacific calendar days, so this placed the day's start 7h (PDT) / 8h
(PST) *before* the day began and inflated `age_hours` by exactly the Pacific offset —
firing the ADR-052 warning tier and the staleness alert that much early, with a silent
one-hour seasonal shift across a DST transition. Neither the #2414 matcher nor the #2811
fleet ratchet can see it: both bottom out in "is there a *clock* in this subtree?", and
`strptime` is not a clock. PR #3196's sweep moved `now` to Pacific and left the other
operand's anchor in UTC — the frame mismatch was *introduced by the fix* for the frame
mismatch, which is why a behavioural test and not a shape test is what catches it.

The two freshness tests below are MUTATION-PROVED against exactly that: they patch the
module's `PACIFIC` name back to `timezone.utc`, which reconstitutes the pre-fix
expression character-for-character, and assert the answer changes.

Run:  python3 -m pytest tests/test_pt_evening_email_frame_2817.py -v
"""

import os
import sys
from datetime import datetime, timedelta, timezone

os.environ.setdefault("AWS_REGION", "us-west-2")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-west-2")
os.environ.setdefault("TABLE_NAME", "life-platform-test")
os.environ.setdefault("USER_ID", "matthew")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from emails import (
    chronicle_email_sender_lambda as ces,  # noqa: E402
    freshness_checker_lambda as fc,  # noqa: E402
)
from pacific_clock import freeze_pacific, pacific_instant  # noqa: E402 — the sanctioned frozen-PT harness (#2811)

# The doubles are IMPORTED, not forked: `tests/test_freshness_checker_handler_wiring.py`
# already models every query shape this handler issues, and a second copy of a fixture is
# a second thing to drift (the #3212 lesson, and this epic's own "guard the SET, not the
# instance"). If that module's doubles stop matching the handler, both files fail together
# — which is the correct coupling.
from test_freshness_checker_handler_wiring import FakeTable, _install  # noqa: E402

UID = fc.USER_ID

# 22:30 PDT on 2026-08-26. See the module docstring: a constant, deliberately, and
# deliberately inside the window where the UTC day is already 2026-08-27.
_EVENING_UTC = datetime(2026, 8, 27, 5, 30, tzinfo=timezone.utc)
# The same wall-clock shape in PST (21:30 on 2026-01-14), so the DST half of the claim
# — that the inflation is the *offset*, 8h not 7h — is exercised rather than asserted.
_WINTER_EVENING_UTC = datetime(2026, 1, 15, 5, 30, tzinfo=timezone.utc)


# ══════════════════════════════════════════════════════════════════════════════
# The instant itself
# ══════════════════════════════════════════════════════════════════════════════


def test_the_frozen_instant_is_actually_inside_the_failure_window():
    """The premise of every test below, asserted rather than assumed.

    If someone "tidies" `_EVENING_UTC` to an hour where the UTC and Pacific calendars
    agree, every mutation proof in this file silently becomes a tautology that passes
    against the broken code too. That is precisely how a frame test rots into
    decoration, so the straddle is a test.
    """
    for label, instant in (("PDT", _EVENING_UTC), ("PST", _WINTER_EVENING_UTC)):
        pt = pacific_instant(instant)
        assert pt.date() != instant.date(), f"{label}: the frozen instant no longer straddles a day boundary"
        assert pt.hour >= 17, f"{label}: the frozen instant is not a PT evening (hour={pt.hour})"
    # And the two instants must be in *different* DST regimes, or the winter case proves nothing.
    assert pacific_instant(_EVENING_UTC).utcoffset() != pacific_instant(_WINTER_EVENING_UTC).utcoffset()


def test_the_thresholds_this_file_straddles_are_still_the_shipped_ones():
    """Both freshness proofs work by placing a row between the PT-anchored and
    UTC-anchored side of a threshold. If the thresholds move, the straddle moves with
    them and the tests would keep passing while testing nothing."""
    assert fc.WARNING_HOURS == 24, f"WARNING_HOURS moved to {fc.WARNING_HOURS} — re-derive the straddle below"
    assert fc.STALE_HOURS == 48, f"STALE_HOURS moved to {fc.STALE_HOURS} — re-derive the straddle below"


# ══════════════════════════════════════════════════════════════════════════════
# freshness_checker — the staleness math
# ══════════════════════════════════════════════════════════════════════════════


def _whoop_row(day):
    return {"pk": f"USER#{UID}#SOURCE#whoop", "sk": f"DATE#{day.isoformat()}", "recovery_score": 60}


def _run_freshness(monkeypatch, *, row_days_back, instant, utc_anchor=False):
    """Drive the REAL `lambda_handler` at `instant` with one whoop row `row_days_back`
    Pacific days old. Returns (body, sns_double).

    `utc_anchor=True` is the MUTATION: it rebinds the module's `PACIFIC` name to
    `timezone.utc`, which turns the shipped
    `strptime(...).replace(tzinfo=PACIFIC)` back into the pre-#2817
    `strptime(...).replace(tzinfo=timezone.utc)` exactly — no re-implementation of the
    old code in the test, just the one name the fix introduced.
    """
    pt = freeze_pacific(monkeypatch, fc, instant)
    row_day = pt.date() - timedelta(days=row_days_back)  # derived from the HANDLER's clock
    table = FakeTable(rows=[_whoop_row(row_day)])
    sns, _cw = _install(monkeypatch, table)
    if utc_anchor:
        monkeypatch.setattr(fc, "PACIFIC", timezone.utc)
    return fc.lambda_handler({}, None), sns


def _stale_pages(sns):
    """Only the STALE-SOURCE alerts (`freshness_checker_lambda.py:710`).

    The handler legitimately raises other alerts on this fixture — the Apple Health
    and Notion partitions are empty, so their dark-channel guards fire, which is them
    working. Asserting `sns.published == []` would therefore be asserting something
    this test is not about, and would break the moment an unrelated guard is added.
    """
    return [p for p in sns.published if "stale source" in str(p.get("Subject", ""))]


def test_todays_data_reads_fresh_at_2230_pt_and_the_utc_anchor_calls_it_degraded(monkeypatch):
    """A row for TODAY (Pacific) is 22.5h old at 22:30 PT — inside the 24h warning
    threshold, i.e. a healthy source.

    Anchored at UTC midnight it measures 29.5h and trips the ADR-052 warning tier, so
    the operator's dashboard reports a degrading source every evening on data that
    arrived today. Nothing is wrong with the source; the arithmetic is reading a
    Pacific day on a UTC ruler.
    """
    body, sns = _run_freshness(monkeypatch, row_days_back=0, instant=_EVENING_UTC)
    assert body["warning_count"] == 0, f"today's data should not be a warning at 22:30 PT: {body['warning_sources']}"
    assert body["stale_count"] == 0
    assert _stale_pages(sns) == []

    mutated, _ = _run_freshness(monkeypatch, row_days_back=0, instant=_EVENING_UTC, utc_anchor=True)
    assert mutated["warning_count"] == 1, "MUTATION PROOF FAILED: the UTC anchor no longer inflates today's age past 24h"
    assert mutated["warning_sources"] == ["Whoop"]


def test_yesterdays_data_does_not_page_at_2230_pt_but_the_utc_anchor_pages(monkeypatch):
    """THE OPERATOR-VISIBLE FAILURE. A row for YESTERDAY (Pacific) is 46.5h old at
    22:30 PT — under the 48h staleness threshold, so it is a warning, not an alarm.

    Anchored at UTC midnight it measures 53.5h, crosses STALE_HOURS, and publishes an
    SNS staleness alert: a false page, at 10:30 at night, for a source that is fine.
    This is the concrete cost of the frame mismatch and the reason it is worth a fix
    rather than a note.
    """
    body, sns = _run_freshness(monkeypatch, row_days_back=1, instant=_EVENING_UTC)
    assert body["stale_count"] == 0, f"yesterday's data is 46.5h old — not stale at 48h: {body['stale_sources']}"
    assert body["warning_count"] == 1, "it IS a warning (>=24h), which is the honest tier"
    assert _stale_pages(sns) == [], "no staleness page should be raised for a 46.5h-old source"

    mutated, mutated_sns = _run_freshness(monkeypatch, row_days_back=1, instant=_EVENING_UTC, utc_anchor=True)
    assert mutated["stale_count"] == 1, "MUTATION PROOF FAILED: the UTC anchor no longer pushes 46.5h past the 48h threshold"
    assert _stale_pages(mutated_sns), "the pre-#2817 anchor raised a real SNS staleness page here — that is the defect"


def test_the_inflation_is_the_dst_offset_not_a_fixed_seven_hours(monkeypatch):
    """`.replace(tzinfo=PACIFIC)` must be DST-CORRECT.

    A fixed `timedelta(hours=-7)` would be wrong for roughly four months of the year —
    which is why #1964 bans hand-rolled offsets and why the fix imports `PACIFIC`
    rather than subtracting a literal. In January the same row/instant geometry is 8h
    off, not 7h, and the tier flip must still happen. If a future edit swaps `PACIFIC`
    for a constant offset, this is the test that notices.
    """
    body, _ = _run_freshness(monkeypatch, row_days_back=0, instant=_WINTER_EVENING_UTC)
    assert body["warning_count"] == 0, "a PST evening must behave like a PDT evening"

    mutated, _ = _run_freshness(monkeypatch, row_days_back=0, instant=_WINTER_EVENING_UTC, utc_anchor=True)
    assert mutated["warning_count"] == 1

    winter = pacific_instant(_WINTER_EVENING_UTC).utcoffset()
    summer = pacific_instant(_EVENING_UTC).utcoffset()
    assert winter == timedelta(hours=-8) and summer == timedelta(hours=-7), (
        f"the Pacific offsets this file's arithmetic assumes have changed: " f"winter={winter}, summer={summer}"
    )


def test_the_sibling_day_vs_day_checks_were_already_honest_and_stay_that_way(monkeypatch):
    """A judgment test, so the fix is not mistaken for "anchor everything in PACIFIC".

    `compute_datatype_liveness` reduces BOTH operands to `.date()` before subtracting
    (`today - strptime(last).date()`), which is frame-immune: the tzinfo never survives
    to the arithmetic. It was correct before #2817 and must not be "fixed". Driving it
    under the mutation proves it: flipping the anchor changes nothing here, which is
    exactly why line 612 was the only site in this module that needed to move.
    """
    pt = freeze_pacific(monkeypatch, fc, _EVENING_UTC)
    records = [{"sk": f"DATE#{(pt.date() - timedelta(days=3)).isoformat()}", "steps": 8000}]
    datatypes = [{"key": "steps", "label": "Steps", "fields": ["steps"], "stale_days": 2}]

    before = fc.compute_datatype_liveness(records, pt, datatypes)
    monkeypatch.setattr(fc, "PACIFIC", timezone.utc)
    after = fc.compute_datatype_liveness(records, pt, datatypes)

    assert before == after, "day-vs-day arithmetic must be frame-immune"
    assert before[0]["age_days"] == 3, f"a 3-day-old row must read as 3 days, got {before[0]['age_days']}"


# ══════════════════════════════════════════════════════════════════════════════
# chronicle_email_sender — the day selection
# ══════════════════════════════════════════════════════════════════════════════


class _ChronicleTable:
    """A DDB double for the ONE query `_get_this_weeks_installment` issues: pk equality
    + `sk BETWEEN`, with the phase filter modelled honestly (a row with no `phase`
    attribute passes `attribute_not_exists(#phase)`, which is the shape a real
    chronicle installment has). The BETWEEN bounds are recorded because they ARE the
    day selection under test."""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.bounds = []

    def query(self, **kwargs):
        vals = kwargs["ExpressionAttributeValues"]
        lo, hi = vals[":s"], vals[":e"]
        self.bounds.append((lo, hi))
        items = [r for r in self.rows if r.get("pk") == vals[":pk"] and lo <= str(r.get("sk", "")) <= hi]
        if "phase" in str(kwargs.get("FilterExpression", "")):
            current = vals.get(":phase_experiment")
            items = [r for r in items if "phase" not in r or r["phase"] == current]
        items.sort(key=lambda r: str(r.get("sk", "")), reverse=kwargs.get("ScanIndexForward") is False)
        return {"Items": items[: kwargs.get("Limit", len(items))]}


def _installment(day, week_number=41):
    return {
        "pk": ces.CHRONICLE_PK,
        "sk": f"DATE#{day.isoformat()}",
        "date": day.isoformat(),
        "status": "published",
        "week_number": week_number,
        "title": "The Seventh Week",
        "content_html": "<p>An installment.</p>",
    }


def test_the_sender_selects_the_pacific_seven_day_window_at_2230_pt(monkeypatch):
    """The day-selection contract, asserted on the query bounds themselves.

    `_get_this_weeks_installment` asks for `DATE#{today-7d}` .. `DATE#{today}`. At
    22:30 PT the Pacific window ends on 2026-08-26; a UTC `now` would end it on
    2026-08-27 and start it a day late, sliding the whole seven-day window forward.
    """
    pt = freeze_pacific(monkeypatch, ces, _EVENING_UTC)
    table = _ChronicleTable([])
    monkeypatch.setattr(ces, "table", table)

    ces._get_this_weeks_installment()

    lo, hi = table.bounds[0]
    assert hi == f"DATE#{pt.date().isoformat()}", f"window must END on the PACIFIC day, got {hi}"
    assert lo == f"DATE#{(pt.date() - timedelta(days=7)).isoformat()}", f"window must START 7 Pacific days back, got {lo}"


def test_a_seven_day_old_installment_is_found_in_pt_and_lost_in_utc(monkeypatch):
    """THE SUBSCRIBER-VISIBLE FAILURE, and the reason the sender was a priority target.

    An installment published exactly 7 Pacific days ago sits on the window's lower
    bound. In the Pacific frame the sender finds it and the week's letter goes out. On
    a UTC `now` the window has slid forward one day, the row falls off the bottom, and
    `_get_this_weeks_installment` returns None — which the handler treats as the
    legitimate "no installment this week" no-op. The week is silently skipped: no
    error, no alarm, no letter.

    The mutation here is the clock itself (`pacific_now` -> the UTC instant), because
    for this module the frame IS the day selection.
    """
    pt = freeze_pacific(monkeypatch, ces, _EVENING_UTC)
    edge_day = pt.date() - timedelta(days=7)
    table = _ChronicleTable([_installment(edge_day)])
    monkeypatch.setattr(ces, "table", table)

    found = ces._get_this_weeks_installment()
    assert found is not None, "the Pacific window must include an installment exactly 7 Pacific days old"
    assert found["date"] == edge_day.isoformat()

    # MUTATION: put the module back on a UTC "today" — the pre-#3196 shape.
    monkeypatch.setattr(ces, "pacific_now", lambda: _EVENING_UTC)
    table.rows = [_installment(edge_day)]
    assert ces._get_this_weeks_installment() is None, (
        "MUTATION PROOF FAILED: a UTC 'today' should slide the 7-day window forward and "
        "lose this installment — if it still finds it, this test is no longer proving the frame"
    )


def test_an_already_delivered_installment_still_no_ops_in_the_pacific_frame(monkeypatch):
    """The #2112 double-send guard has to keep working in the frame #2817 moved it to.

    Moving a day selection is exactly the kind of change that quietly widens a window
    past a de-dup marker, and this sender writes to real subscribers — a regression
    here is a duplicate letter, not a wrong number.
    """
    pt = freeze_pacific(monkeypatch, ces, _EVENING_UTC)
    row = _installment(pt.date())
    row["delivered_at"] = "2026-08-26T14:00:00+00:00"
    monkeypatch.setattr(ces, "table", _ChronicleTable([row]))

    assert ces._get_this_weeks_installment() is None, "a delivered installment must stay a no-op"


def test_the_send_completion_row_is_keyed_on_the_pacific_day(monkeypatch):
    """`_record_email_send` writes the `email_log#` completion row the status page reads.

    `lambdas/web/site_api_status.py` builds its 90-day uptime bars off
    `datetime.now(PT).date()`, so a UTC-keyed row put every letter sent after 17:00 PT
    on TOMORROW's bar — a send that happened showing as a miss. One partition, one
    frame: this asserts the writer's half at the instant where the two frames differ.
    """
    pt = freeze_pacific(monkeypatch, ces, _EVENING_UTC)
    puts = []

    class _T:
        def put_item(self, Item):
            puts.append(Item)

    monkeypatch.setattr(ces, "table", _T())
    ces._record_email_send(7)

    assert puts, "_record_email_send wrote nothing"
    assert puts[0]["sk"] == f"DATE#{pt.date().isoformat()}", f"completion row must be keyed on the PACIFIC day, got {puts[0]['sk']}"
    assert puts[0]["sk"] != f"DATE#{_EVENING_UTC.date().isoformat()}", "that is the UTC day — tomorrow's bar"
