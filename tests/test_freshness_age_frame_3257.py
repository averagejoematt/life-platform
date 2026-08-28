"""#3257 — /api/source_freshness aged a Pacific DATE# key at UTC midnight.

THE DEFECT, VERIFIED LIVE 2026-08-27
------------------------------------
``site_api_freshness.py`` did::

    last_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    age_hours = round((now - last_dt).total_seconds() / 3600, 1)

for all twelve board sources. Eleven of them are PACIFIC-keyed —
``ingestion_framework.py:652`` stamps ``pacific_today()``, "DATE# keys are Pacific calendar
days (truth audit 2026-07-10)". Anchoring a Pacific day at UTC midnight starts it 7h (PDT)
/ 8h (PST) before it began, so the live response asserted both of these at once::

    pacific_today: 2026-08-27
    whoop  last=2026-08-27  age=21.7h  fresh

A record stamped with today's Pacific date, reported as 21.7 hours old. 21.7h is exactly
``2026-08-27T00:00Z → now``; the honest Pacific-anchored age was ~14.7h.

WHY THE GUARD IS AN AGREEMENT, NOT A NUMBER
-------------------------------------------
The ops-side sibling reading the SAME keys was fixed to Pacific two days earlier
(``452929f17``, #2817/#3233). That left two consumers of one key disagreeing about its
frame by 7 hours, with the reader-facing one wrong — a source between ``stale_hours`` and
``stale_hours + 7`` rendered STALE to the public while the ops checker called it fresh and
sent no alert. The disagreement IS the defect, so the guard is the agreement: both call
``common.pacific_time.anchor_day_key`` and are pinned to produce identical ages.

WHY apple_health IS ASSERTED SEPARATELY
---------------------------------------
Sweeping everything to Pacific would have been wrong in the other direction. apple_health's
``DATE#`` day is a UTC calendar day, deliberately, by TD-19 Phase 2 — ``parse_date_str``
converts the device's source-tz timestamp to UTC before taking the day so HAE's sub-streams
share one partition frame. A Pacific anchor there yields a NEGATIVE age for the 7 hours a
day that UTC-today runs ahead of PT-today. The frame is therefore per-source, read from the
registry's ``day_key_frame`` facet.

AND IT IS NOT A CLAMP. #3232 ruled the stored key correct and refused to clamp; that ruling
stands and is re-asserted below. What changed is the arithmetic's frame.

THE CLOCK THESE TESTS RUN ON
----------------------------
Every instant here is INJECTED. #3206 shipped green because its CI happened to run at 13:00
PT and the test failed 7 of every 24 hours; a gate for an evening-only defect that can only
see the afternoon is not a gate. The PT-evening window (17:00–24:00 PT, when UTC-today runs
ahead of PT-today) is exercised explicitly.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "lambdas" / "web"))

from common.pacific_time import PACIFIC, anchor_day_key  # noqa: E402
from ingestion.source_registry import day_key_frame_for, public_board_sources, utc_day_key_source_ids  # noqa: E402
from web import (
    site_api_data as sad,  # noqa: E402
    site_api_freshness as sf,  # noqa: E402
)

# The two PT-evening instants that matter, plus a benign midday one. Expressed in UTC and
# converted, so there is no ambiguity about which side of the 17:00 PT rollover they sit on.
MIDDAY_PT = datetime(2026, 8, 27, 19, 0, tzinfo=timezone.utc)  # 12:00 PDT — UTC-today == PT-today
EVENING_PT = datetime(2026, 8, 28, 1, 0, tzinfo=timezone.utc)  # 18:00 PDT — UTC-today is TOMORROW in PT
LATE_PT = datetime(2026, 8, 28, 6, 59, tzinfo=timezone.utc)  # 23:59 PDT — the last minute before PT rollover
WINTER_PT = datetime(2026, 12, 15, 2, 0, tzinfo=timezone.utc)  # 18:00 PST — the 8h offset, DST's other side


def _ops_age(date_str, source, now):
    """The ops checker's age arithmetic, as it stands in freshness_checker_lambda.py."""
    return (now - anchor_day_key(date_str, source)).total_seconds() / 3600


def _board_age(date_str, source, now):
    """The public board's age arithmetic, as it stands in site_api_freshness.py."""
    return round((now - anchor_day_key(date_str, source)).total_seconds() / 3600, 1)


# ─────────────────────────────────────────────────────────────────────────────
# The defect itself
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("now", [MIDDAY_PT, EVENING_PT, LATE_PT, WINTER_PT], ids=["midday", "evening", "late", "winter"])
def test_a_record_stamped_today_never_reads_a_day_old(now):
    """The reported symptom: `last=<pacific today>` served as `age=21.7h`. Whatever the
    hour, a Pacific-keyed record stamped with the CURRENT Pacific day is younger than 24h
    — and specifically younger than the wall-clock hour count, never older."""
    pt_today = now.astimezone(PACIFIC).strftime("%Y-%m-%d")
    hours_into_the_pacific_day = now.astimezone(PACIFIC).hour + now.astimezone(PACIFIC).minute / 60
    for source in ("whoop", "eightsleep", "habitify"):
        age = _board_age(pt_today, source, now)
        # `<= 24` not `< 24`: the LATE_PT case is 23:59 PDT, which is 23.98h and rounds to
        # 24.0 in the payload. The exact-value assertion below is the real pin.
        assert 0 <= age <= 24, f"{source}: a record stamped today ({pt_today}) reads {age}h old at {now.isoformat()}"
        assert age == pytest.approx(hours_into_the_pacific_day, abs=0.1), (
            f"{source}: age {age}h should be the hours elapsed since Pacific midnight "
            f"({hours_into_the_pacific_day:.1f}h) — anything else is an anchor in the wrong frame"
        )


def test_the_pre_fix_utc_anchor_reproduced_the_filed_number():
    """The evidence, reproduced from the OLD arithmetic — so this file can be read as a
    proof rather than a claim. 2026-08-27 was PDT (UTC-7); the filing recorded 21.7h."""
    now = datetime(2026, 8, 27, 21, 42, tzinfo=timezone.utc)  # 14:42 PDT
    old_way = datetime.strptime("2026-08-27", "%Y-%m-%d").replace(tzinfo=timezone.utc)
    assert round((now - old_way).total_seconds() / 3600, 1) == 21.7
    assert _board_age("2026-08-27", "whoop", now) == 14.7  # the honest Pacific-anchored age
    assert round(21.7 - 14.7, 1) == 7.0  # exactly the PDT offset, as the filing predicted


# ─────────────────────────────────────────────────────────────────────────────
# The guard: the two consumers must AGREE
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("now", [MIDDAY_PT, EVENING_PT, LATE_PT, WINTER_PT], ids=["midday", "evening", "late", "winter"])
def test_public_board_and_ops_checker_report_the_same_age(now):
    """THE agreement. Between 452929f17 and #3257 these differed by exactly 7h for every
    framework source, so the board could render a source STALE while the ops checker called
    it fresh and stayed silent. Every board source, every instant, all offsets."""
    for source in sorted(public_board_sources()):
        for offset_days in (0, 1, 3, 40):
            day = (now.astimezone(PACIFIC) - timedelta(days=offset_days)).strftime("%Y-%m-%d")
            board = _board_age(day, source, now)
            ops = _ops_age(day, source, now)
            assert board == pytest.approx(ops, abs=0.05), f"{source} @ {day} @ {now.isoformat()}: board {board}h vs ops {ops}h"


def test_the_agreement_would_have_caught_the_pre_fix_split():
    """POSITIVE CONTROL for the test above. If both consumers used one helper but that helper
    were wrong, the agreement test would still pass — so prove the assertion can FAIL by
    running the two PRE-fix implementations against each other (board UTC, ops Pacific)."""
    now = EVENING_PT
    pre_fix_board = (now - datetime.strptime("2026-08-27", "%Y-%m-%d").replace(tzinfo=timezone.utc)).total_seconds() / 3600
    pre_fix_ops = (now - datetime.strptime("2026-08-27", "%Y-%m-%d").replace(tzinfo=PACIFIC)).total_seconds() / 3600
    assert round(pre_fix_board - pre_fix_ops, 1) == 7.0, "the pre-fix split was not 7h — this control is not exercising the defect"
    assert pre_fix_board != pytest.approx(pre_fix_ops, abs=0.05)


# ─────────────────────────────────────────────────────────────────────────────
# The HAE exception, asserted separately (never folded into the Pacific path)
# ─────────────────────────────────────────────────────────────────────────────
def test_apple_health_keeps_the_utc_anchor():
    """TD-19 Phase 2: apple_health's DATE# day IS a UTC calendar day. It must not be swept
    into the Pacific fix."""
    assert day_key_frame_for("apple_health") == "utc"
    assert utc_day_key_source_ids() == {"apple_health"}, (
        "the UTC-keyed set changed. It is derived from the day_key_frame facet — if a second "
        "HAE-fed partition joined the board, declare it in the registry and update this pin "
        "with the audit that says its key is UTC."
    )
    now = MIDDAY_PT
    assert _board_age("2026-08-27", "apple_health", now) == 19.0  # 19h since 2026-08-27T00:00Z
    assert _board_age("2026-08-27", "whoop", now) == 12.0  # 12h since 2026-08-27T00:00 PDT


def test_a_blanket_pacific_sweep_would_have_made_apple_health_negative():
    """WHY the frame is per-source and not one sweep. In the PT evening, UTC-today is
    tomorrow in PT; anchoring that day at PACIFIC midnight puts it in the future."""
    now = EVENING_PT  # 18:00 PDT on 08-27 == 01:00 UTC on 08-28
    utc_today = now.strftime("%Y-%m-%d")
    assert utc_today == "2026-08-28"
    wrong = (now - datetime.strptime(utc_today, "%Y-%m-%d").replace(tzinfo=PACIFIC)).total_seconds() / 3600
    assert wrong < 0, "the negative-age hazard did not reproduce — this control is not exercising it"
    assert _board_age(utc_today, "apple_health", now) >= 0, "apple_health's UTC anchor must keep its age non-negative"


def test_every_board_source_resolves_a_frame_and_the_default_is_pacific():
    """Guard the SET. A new board source that nobody classified must land on the platform
    default (Pacific, the framework's pacific_today() stamp), not on undefined behaviour."""
    board = set(public_board_sources())
    assert len(board) >= 12, f"the board shrank to {len(board)} sources — re-derive before trusting this test"
    for source in board:
        assert day_key_frame_for(source) in ("pacific", "utc")
    assert board - utc_day_key_source_ids(), "every board source became UTC-keyed — that contradicts ingestion_framework"
    assert day_key_frame_for("a_source_that_does_not_exist_yet") == "pacific"


# ─────────────────────────────────────────────────────────────────────────────
# The ruling this fix must NOT overturn
# ─────────────────────────────────────────────────────────────────────────────
def test_the_fix_does_not_clamp():
    """#3232 refused to clamp an ahead-of-PT day and pinned that clamping is the wrong fix.
    A UTC-keyed day that is ahead of PT-today still ages to a real, un-clamped number."""
    now = EVENING_PT
    pt_today = now.astimezone(PACIFIC).strftime("%Y-%m-%d")
    utc_today = now.strftime("%Y-%m-%d")
    assert utc_today > pt_today  # the #3232 window
    age = _board_age(utc_today, "apple_health", now)
    assert age == 1.0, "the ahead-of-PT row must age honestly from its own UTC midnight, not be clamped to 0"


def test_both_consumers_call_the_one_helper():
    """The structural half: an agreement produced by two copies of the same arithmetic drifts
    the moment one is edited (that is literally what 452929f17 → #3257 was). Both modules
    must resolve the frame through common.pacific_time.anchor_day_key."""
    for rel in ("lambdas/web/site_api_freshness.py", "lambdas/emails/freshness_checker_lambda.py"):
        src = (_REPO / rel).read_text(encoding="utf-8")
        assert "anchor_day_key" in src, f"{rel} no longer resolves its DATE# anchor through the shared helper (#3257)"
        assert 'strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)' not in src, f"{rel} re-grew a bare UTC day anchor (#3257)"


def test_days_dark_receives_a_pacific_now():
    """The second site with the same root cause: `_days_dark` does `now.date() - last.date()`,
    so a UTC `now` reads one day too high for the 7h a day UTC-today runs ahead."""
    src = (_REPO / "lambdas" / "web" / "site_api_freshness.py").read_text(encoding="utf-8")
    assert "_days_dark(last_update, pt_now)" in src, "days_dark must be computed against the Pacific instant (#3257)"

    sys.path.insert(0, str(_REPO / "lambdas"))
    from web.site_api_data import _days_dark

    now = EVENING_PT
    assert _days_dark("2026-08-27", now.astimezone(PACIFIC)) == 0, "a record stamped today is 0 days dark at 18:00 PT"
    assert _days_dark("2026-08-27", now) == 1, "the UTC instant is what produced the off-by-one — control"


# ─────────────────────────────────────────────────────────────────────────────
# ON THE WIRE — the real handler, not the helper
# ─────────────────────────────────────────────────────────────────────────────
# Everything above tests `anchor_day_key`. That is necessary and not sufficient: a fix
# whose helper is right and whose CALL SITE is not passes every one of those assertions
# (#2703 — a test on real shipped code the running path never reaches). These drive the
# actual `/api/source_freshness` handler at a constructed instant and read `age_hours` off
# the payload the reader gets. Harness shape borrowed from
# tests/test_freshness_day_frame_2798.py so the two files agree about what "the wire" is.


class _UniformBoardTable:
    """Every source's newest DATE# record is the same day — the frame question is a
    property of the date against the clock, so a uniform board exercises every row."""

    def __init__(self, date_str):
        self._date = date_str

    def query(self, **kwargs):
        items = [{"sk": f"DATE#{self._date}"}]
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit is not None else items}

    def get_item(self, Key=None):
        return {}


class _FrozenClock(datetime):
    _at = EVENING_PT

    @classmethod
    def now(cls, tz=None):
        return cls._at.astimezone(tz) if tz is not None else cls._at.replace(tzinfo=None)


def _board(monkeypatch, *, at, stored_date):
    monkeypatch.setattr(sf, "datetime", type("_At", (_FrozenClock,), {"_at": at}))
    monkeypatch.setattr(sad, "table", _UniformBoardTable(stored_date))
    resp = sad.handle_source_freshness()
    body = json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]
    return body, {s["id"]: s for s in body["sources"]}


@pytest.mark.parametrize("now", [MIDDAY_PT, EVENING_PT, WINTER_PT], ids=["midday", "evening", "winter"])
def test_the_served_payload_never_ages_todays_record_by_a_day(monkeypatch, now):
    """THE FILED SYMPTOM, on the wire. `pacific_today` and a same-day `last_update` in one
    payload, with `age_hours` claiming 21.7. Read the real response and check the two
    fields against each other — the way a reader does."""
    pt_today = now.astimezone(PACIFIC).strftime("%Y-%m-%d")
    body, by = _board(monkeypatch, at=now, stored_date=pt_today)
    assert body["pacific_today"] == pt_today
    hours_in = now.astimezone(PACIFIC).hour + now.astimezone(PACIFIC).minute / 60
    for sid in ("whoop", "eightsleep", "habitify"):
        row = by[sid]
        assert row["last_update"] == pt_today
        assert row["age_hours"] == pytest.approx(hours_in, abs=0.1), (
            f"{sid}: the payload says last_update={pt_today} and pacific_today={pt_today} "
            f"while reporting age_hours={row['age_hours']} — the #3257 contradiction"
        )
        assert row["last_update_ts"].endswith(("-07:00", "-08:00")), "a Pacific-keyed row's anchor must carry the Pacific offset"


def test_apple_health_on_the_wire_keeps_its_utc_anchor(monkeypatch):
    """The exception, on the wire. #2798's `test_durations_are_frame_independent_and_untouched`
    pins apple_health's age against a UTC anchor; that must still hold after this change."""
    now = EVENING_PT
    stored = now.strftime("%Y-%m-%d")  # UTC-today, which is tomorrow in PT
    _, by = _board(monkeypatch, at=now, stored_date=stored)
    ah = by["apple_health"]
    expected = round((now - datetime.strptime(stored, "%Y-%m-%d").replace(tzinfo=timezone.utc)).total_seconds() / 3600, 1)
    assert ah["age_hours"] == expected == 1.0
    assert ah["last_update_ts"] == f"{stored}T00:00:00+00:00"
    assert ah["last_update"] == stored, "still not clamped (#3232)"
    assert ah["last_update_ahead_of_pt"] is True and ah["last_update_frame"] == "utc"
