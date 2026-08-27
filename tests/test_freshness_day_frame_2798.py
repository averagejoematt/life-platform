"""tests/test_freshness_day_frame_2798.py — the SERVING half of the PT-day contract (#2798).

THE RULING THIS FILE PINS
─────────────────────────
`/api/source_freshness`'s ``last_update`` is a stored ``DATE#`` day key, and for the
near-real-time sources that key is a **UTC calendar day — deliberately, and by audit**.
TD-19 Phase 2 (2026-05-03, `docs/audits/TD-19_DATE_PARTITION_AUDIT.md`) changed
`health_auto_export_lambda.parse_date_str` to convert the device's source-tz timestamp
to UTC *before* extracting the day, so every source shares one partition frame and
cross-source aggregation stops undercounting. **The key is correct.** What was wrong is
presenting it unqualified on a Pacific-framed page.

So this file guards a LABEL, not a clamp. `test_the_future_dated_row_is_never_clamped`
is the load-bearing one: clamping a legitimately-UTC day to PT-today would hide a record
that genuinely exists, which is the worse failure of the two and the one this fix was
explicitly not allowed to commit.

WHAT WENT WRONG
───────────────
UTC rolls over at 17:00 PT. Between 17:00 PT and PT-midnight, a source that has just
delivered serves *tomorrow's* calendar date to a reader whose own page header says that
day has not happened yet. Captured live on 2026-08-26 at 22:38 PT (05:38Z on the 27th)::

    {"id": "apple_health", "last_update": "2026-08-27", "age_hours": 5.7, ...}

The armed reader-truth judge caught it on post-deploy run 33040437876 — "LAST UPDATE
2026-08-27 6h but today is 2026-08-26. This is a future date" — and gated CI on it. It
is the #3206/#3222 shape one layer out: real for 7 hours a day, invisible for the other
17, so nobody had seen it in the months it had been live.

WHY THE CLOCK IS FROZEN (the #3206 lesson, not re-learned)
──────────────────────────────────────────────────────────
#3206 shipped green because its CI ran ~13:00 PT, where UTC and Pacific agree — its own
suite could not see its own bug, and `main` went red 24 hours later on unrelated work.
A gate that only ever runs where it cannot fail is not a gate. Every assertion below
runs against a **constructed instant**, so the 17:00-PT-to-midnight case is exercised on
every run at every hour, on a laptop in Pacific and on a runner in UTC alike. The
pattern is copied from `tests/test_fixture_frame_pairing_3222.py::
test_the_pt_evening_window_is_exercised_without_waiting_for_it`.

Both calendars are derived from the frozen instant via `common.pacific_time.PACIFIC` —
the same zone object the handler binds as `PT` — so no expectation here is a hand-typed
date, and this file cannot drift from the handler's own answer.

THE CROSS-LAYER PAIRING
───────────────────────
The fix has two halves and either one alone is inert: the API must stamp the frame, and
`/method/pipeline/`'s renderer must show it. `test_the_pipeline_renderer_consumes_the_frame`
reads the shipped JS so that deleting either half reds this file. That is deliberate —
#2703's lesson is that a test on code the running path never reaches passes everything
and does nothing.

Not in scope, and deliberately untouched: `age_hours` / `status` are durations, they are
frame-independent, and `age_hours: 5.7` was correct all along. The `datatypes[]` array's
sub-datatype staleness is #3204's lane.
"""

import json
import os
import sys
from datetime import datetime, timezone

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))
sys.path.insert(0, os.path.join(_REPO, "lambdas", "web"))

from common.pacific_time import PACIFIC  # noqa: E402  — the handler's own zone object, never a hand-rolled offset
from web import (
    site_api_data as sad,  # noqa: E402
    site_api_freshness as sf,  # noqa: E402
)

_JS = os.path.join(_REPO, "site", "assets", "js", "evidence_meta.js")

# The captured instant from the epic comment, to the minute: 05:38Z on 2026-08-27 is
# 22:38 PT on 2026-08-26. This is the exact wire state the judge gated on.
_PT_EVENING = datetime(2026, 8, 27, 5, 38, tzinfo=timezone.utc)
# 16:00Z on 2026-08-26 is 09:00 PT the same day — the frames agree. This is the window
# the daily crons (and #3206's CI) run in, which is why the defect stayed invisible.
_PT_MORNING = datetime(2026, 8, 26, 16, 0, tzinfo=timezone.utc)


def _pt_day(instant):
    """The Pacific calendar day of an instant — via the handler's own zone object."""
    return instant.astimezone(PACIFIC).strftime("%Y-%m-%d")


def _utc_day(instant):
    return instant.astimezone(timezone.utc).strftime("%Y-%m-%d")


class _UniformBoardTable:
    """Every registry source's newest DATE# record is the same day. Uniform on purpose:
    the frame stamp is a property of the *date against the clock*, not of any one
    source, so a uniform board exercises every row at once and the assertions below
    hold for whichever sources the registry happens to carry today."""

    def __init__(self, date_str):
        self._date = date_str

    def query(self, **kwargs):
        items = [{"sk": f"DATE#{self._date}"}]
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit is not None else items}

    def get_item(self, Key=None):
        return {}  # no HAE DATATYPE_LIVENESS sentinel — #3204's lane, left alone


class _FrozenClock(datetime):
    """`datetime` with `now()` pinned. Subclassed so `strptime` and everything else the
    handler reaches for still behave exactly as the real class does."""

    _at = _PT_EVENING

    @classmethod
    def now(cls, tz=None):
        return cls._at.astimezone(tz) if tz is not None else cls._at.replace(tzinfo=None)


def _board(monkeypatch, *, at, stored_date):
    """Run the real handler at a constructed instant over a uniform board."""
    frozen = type("_At", (_FrozenClock,), {"_at": at})
    monkeypatch.setattr(sf, "datetime", frozen)
    monkeypatch.setattr(sad, "table", _UniformBoardTable(stored_date))
    resp = sad.handle_source_freshness()
    body = json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]
    return body, {s["id"]: s for s in body["sources"]}


# ── the anchor: the fixture instant is a real disagreement, or everything below is theatre ──


def test_the_constructed_instants_are_a_real_frame_disagreement():
    """Non-vacuous anchor, in the #3222 shape. If these two instants ever stop
    disagreeing/agreeing the way the mechanism requires, every proof below is vacuous
    and must be read again rather than trusted."""
    assert _utc_day(_PT_EVENING) != _pt_day(_PT_EVENING), "22:38 PT must sit on the NEXT UTC day — that is the whole mechanism"
    assert _utc_day(_PT_EVENING) > _pt_day(_PT_EVENING)
    assert _utc_day(_PT_MORNING) == _pt_day(_PT_MORNING), "09:00 PT must agree with UTC — the window #3206's CI ran in"


# ── the defect, reproduced and then ruled ──


def test_the_pt_evening_row_is_stamped_with_its_frame(monkeypatch):
    """THE REGRESSION GUARD. At 22:38 PT the board's newest stored day is UTC-tomorrow.
    Pre-fix the payload said only `last_update: 2026-08-27` with nothing to distinguish
    that from a future date. It must now carry both halves of the frame: the row is
    ahead of the reader's Pacific day, and the frame it is ahead *in* is UTC."""
    stored = _utc_day(_PT_EVENING)
    body, by = _board(monkeypatch, at=_PT_EVENING, stored_date=stored)

    ah = by["apple_health"]  # the ground-truthed row from the epic comment
    assert ah["last_update"] == stored
    assert ah["last_update_ahead_of_pt"] is True, "a stored day past PT-today must say so — this is the judge's finding"
    assert ah["last_update_frame"] == "utc", "the frame must be PROVEN and stated, not left for the reader to infer"

    assert body["pacific_today"] == _pt_day(_PT_EVENING), "the page's own Pacific day must be served, not derived client-side"
    assert body["pacific_today"] < ah["last_update"], "the payload must itself expose the disagreement the reader can see"


def test_the_future_dated_row_is_never_clamped(monkeypatch):
    """THE LOAD-BEARING ONE. The stored key is a genuine UTC day (TD-19 Phase 2), so
    clamping it to PT-today would hide a record that really exists — a worse failure than
    the bug, and the one this fix was explicitly forbidden to commit. `last_update` and
    `last_update_ts` must survive the PT-evening window byte-for-byte."""
    stored = _utc_day(_PT_EVENING)
    _, by = _board(monkeypatch, at=_PT_EVENING, stored_date=stored)
    ah = by["apple_health"]
    assert ah["last_update"] == stored, "the real record must never be clamped away"
    assert ah["last_update_ts"] == f"{stored}T00:00:00+00:00"


def test_durations_are_frame_independent_and_untouched(monkeypatch):
    """`age_hours` and `status` are durations, not calendar days. `age_hours: 5.7` was
    correct on the wire the whole time and this fix must not have moved it: the value
    must still be exactly the hours from the stored day's UTC midnight to now."""
    stored = _utc_day(_PT_EVENING)
    _, by = _board(monkeypatch, at=_PT_EVENING, stored_date=stored)
    ah = by["apple_health"]
    expected = round((_PT_EVENING - datetime.strptime(stored, "%Y-%m-%d").replace(tzinfo=timezone.utc)).total_seconds() / 3600, 1)
    assert ah["age_hours"] == expected
    assert ah["status"] == "fresh"


def test_the_agreeing_window_carries_no_frame_noise(monkeypatch):
    """The complement, and the reason the stamp is conditional: 17 hours of every 24 the
    two calendars agree, and on those the board must carry no extra copy at all. A guard
    that fires all day would be muted; a label that shows all day is gloss."""
    stored = _pt_day(_PT_MORNING)
    body, by = _board(monkeypatch, at=_PT_MORNING, stored_date=stored)
    assert body["pacific_today"] == stored
    for sid, s in by.items():
        if s.get("last_update") is None:
            continue  # paused sources carry no date
        assert "last_update_ahead_of_pt" not in s, f"{sid}: a same-day row must not be stamped ahead"
        assert "last_update_frame" not in s, f"{sid}: a same-day row needs no frame label"


def test_a_genuinely_anomalous_future_date_gets_no_utc_alibi(monkeypatch):
    """The direction that keeps the label honest. A stored day beyond UTC-today is not a
    timezone artifact — it is a bad payload or a bad backfill. It must be flagged as
    ahead of today and must NOT earn the `utc` frame label, or the fix would become a
    machine for explaining real corruption away as a rollover."""
    stored = "2026-09-05"  # far past both calendars at the frozen instant
    assert stored > _utc_day(_PT_EVENING)
    _, by = _board(monkeypatch, at=_PT_EVENING, stored_date=stored)
    ah = by["apple_health"]
    assert ah["last_update_ahead_of_pt"] is True
    assert "last_update_frame" not in ah, "an unexplainable future date must never be labelled a UTC rollover"


# ── the cross-layer pairing: the renderer must actually consume what the API stamps ──


def test_the_pipeline_renderer_consumes_the_frame():
    """Either half of this fix alone is inert. `/method/pipeline/` is where the judge
    caught it, and its renderer is `renderPipeline` in the shipped ES module — so the
    contract is pinned against the file the browser actually loads, not against a copy.
    #2703: a test on real-looking code the running path never reaches passes everything
    and does nothing."""
    src = open(_JS, encoding="utf-8").read()
    start = src.index("export function renderPipeline")
    nxt = src.find("\nexport function ", start + 1)  # renderPipeline is currently last; tolerate either
    body = src[start:] if nxt == -1 else src[start:nxt]
    for field in ("last_update_frame", "last_update_ahead_of_pt", "pacific_today"):
        assert field in body, f"renderPipeline must consume {field} or the API stamp is dead weight"
    assert "Math.round(s.age_hours)" in body, "the duration display must survive — age_hours was never the defect"


def test_no_other_endpoint_renders_a_bare_last_update_date():
    """The consumer sweep, kept honest by the guard rather than by a one-time grep.

    `/api/last_sync` is the sibling that carries the same day keys, and its consumer
    (`cockpit.js::_syncAgo`) renders only DURATIONS — "today" / "3d ago" — so it is
    frame-independent and correctly needs no label. `scripts/v4_proof.py` reads the same
    payload for the data door but takes only labels and status counts. If either ever
    starts printing a bare calendar date, this guard is where that shows up."""
    cockpit = open(os.path.join(_REPO, "site", "assets", "js", "cockpit.js"), encoding="utf-8").read()
    start = cockpit.index("function _syncAgo")
    seg = cockpit[start : start + 400]
    assert "_dayAgoText" in seg and "_agoText" in seg, "last_sync must stay a duration display, not a date display"

    proof = open(os.path.join(_REPO, "scripts", "v4_proof.py"), encoding="utf-8").read()
    start = proof.index("def load_data_sources")
    seg = proof[start : proof.index("\ndef ", start + 1)]
    assert "last_update" not in seg, "the data door must not start rendering a raw source day key without a frame"
