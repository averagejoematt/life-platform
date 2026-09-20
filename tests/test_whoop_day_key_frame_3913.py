"""tests/test_whoop_day_key_frame_3913.py — #3913, the residual #3677 named and left open.

THE DEFECT
----------
`source_registry` carried no `day_key_frame` for `whoop`, so `day_key_frame_for("whoop")`
returned the platform default `"pacific"` — while whoop's `DATE#` keys are measurably UTC
days. The framework enumerates Pacific date LABELS, but `whoop_lambda.fetch_day` turns each
label into a UTC WINDOW (`{d}T00:00:00.000Z .. {d+1}T00:00:00.000Z`) and `transform` files
whatever that window returns under the same label, so a whoop `DATE#{d}` names the UTC day
`d`. Measured read-only on the live partition (#3677, re-measured for #3913):

    straddling rows (UTC day != Pacific day of start, i.e. 17:00 PT..midnight)
        2020-03-23..2026-09-19   2,249 rows   UTC-keyed 2,249   Pacific-keyed 0
        2026-07-01..2026-09-19      66 rows   UTC-keyed    66   Pacific-keyed 0

The facet feeds `common.pacific_time.anchor_day_key`, which is how BOTH consumers that age
a `DATE#` key compute that age (`emails/freshness_checker_lambda.py` for the ops alert,
`web/site_api_freshness.py` for the public board). Anchoring a UTC-named day at PACIFIC
midnight starts it 7h (PDT) / 8h (PST) AFTER it actually began, so whoop's reported age was
that much too SMALL — the freshness surfaces understated whoop's staleness by up to the full
offset, every day, in the opposite direction to the #3257 defect and invisible for the same
reason (a day is not an instant, and the mistake is always exactly the offset).

WHAT IS AND IS NOT CHANGED
--------------------------
Only the ARITHMETIC that ages the key. The WRITER stays exactly as it is: the store is
right, `MissingActivityCount{Source=whoop}` was 0 on 30 of 30 consecutive daily runs, and
re-framing the writer to Pacific would mint a phantom nightly gap —
`tests/test_whoop_reconciler_frame_3677.py` fails anyone who tries, and this file must
never be read as licence to.

THE FIXTURES ARE THE WIRE
-------------------------
The sleep record below is the stored upstream fixture `tests/fixtures/upstream/whoop/
sleep.json` (a Whoop API `/v1/activity/sleep` record shape), and the sort keys are the
stored partition snapshot `tests/fixtures/whoop_sk_zoo_2026w35.json` — including the
`DATE#<d>#WORKOUT#<uuid>` sub-record shape, which is what the live partition's NEWEST key
usually is, so the `[:10]` slice both consumers do is exercised on the real grammar rather
than on a hand-typed day row.

Run:  python3 -m pytest tests/test_whoop_day_key_frame_3913.py -v
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

for _k, _v in {
    "S3_BUCKET": "test-bucket",
    "TABLE_NAME": "life-platform",
    "USER_ID": "matthew",
    "AWS_DEFAULT_REGION": "us-west-2",
    "AWS_REGION": "us-west-2",
}.items():
    os.environ.setdefault(_k, _v)

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "lambdas"))
sys.path.insert(0, str(_REPO / "lambdas" / "web"))

from common.pacific_time import PACIFIC, anchor_day_key  # noqa: E402
from ingestion import whoop_lambda as whoop  # noqa: E402
from ingestion.source_registry import (  # noqa: E402
    DEFAULT_STALE_HOURS,
    SOURCE_REGISTRY,
    day_key_frame_consequence_for,
    day_key_frame_for,
    stale_hours_overrides,
    utc_day_key_source_ids,
)
from web import (  # noqa: E402
    site_api_data as sad,
    site_api_freshness as sf,
)

pytestmark = pytest.mark.premerge

# ── The wire record. Loaded, never retyped. ──────────────────────────────────────────
_SLEEP_FIXTURE = json.loads((_REPO / "tests" / "fixtures" / "upstream" / "whoop" / "sleep.json").read_text())
MAIN_SLEEP = next(r for r in _SLEEP_FIXTURE["records"] if not r.get("nap"))
SLEEP_START = MAIN_SLEEP["start"]  # 2026-06-08T05:00:00.000Z == 2026-06-07 22:00 PDT
UTC_DAY = "2026-06-08"
PACIFIC_DAY = "2026-06-07"

_SK_ZOO = json.loads((_REPO / "tests" / "fixtures" / "whoop_sk_zoo_2026w35.json").read_text())
WORKOUT_SK = next(r["sk"] for r in _SK_ZOO["records"] if "#WORKOUT#" in r["sk"])

# Instants, injected — never `now()`. #3206 shipped a gate that could only see the
# afternoon; the whole defect lives in the 17:00-PT..midnight window.
MIDDAY_PT = datetime(2026, 6, 8, 19, 0, tzinfo=timezone.utc)  # 12:00 PDT
EVENING_PT = datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc)  # 18:00 PDT — UTC-today is tomorrow in PT
LATE_PT = datetime(2026, 6, 9, 6, 59, tzinfo=timezone.utc)  # 23:59 PDT
WINTER_PT = datetime(2026, 12, 15, 2, 0, tzinfo=timezone.utc)  # 18:00 PST — the 8h offset
CHECKER_CRON = datetime(2026, 6, 8, 16, 45, tzinfo=timezone.utc)  # cron(45 16 * * ? *), 9:45 AM PT


# ─────────────────────────────────────────────────────────────────────────────
# The control: the fixture must actually straddle, or everything below agrees
# with both frames at once and proves nothing.
# ─────────────────────────────────────────────────────────────────────────────
def test_the_wire_fixture_really_straddles_the_boundary():
    t = datetime.fromisoformat(SLEEP_START.replace("Z", "+00:00"))
    assert t.astimezone(timezone.utc).strftime("%Y-%m-%d") == UTC_DAY
    assert t.astimezone(PACIFIC).strftime("%Y-%m-%d") == PACIFIC_DAY
    assert UTC_DAY != PACIFIC_DAY, "a non-straddling fixture would pass every assertion below for the wrong reason"
    assert t.astimezone(PACIFIC).hour >= 17, "the boundary only bites from 17:00 PT; this fixture must sit in that window"
    assert MAIN_SLEEP["timezone_offset"] == "-07:00", "the wire record carries the owner's own offset — the reason the two frames differ"


def test_the_stored_key_for_that_wire_record_is_its_utc_day():
    """The measurement, as a test. 2,249 of 2,249 straddling rows are keyed by the UTC day;
    the key for this record is `DATE#2026-06-08`, not `DATE#2026-06-07`."""
    assert whoop._utc_day(SLEEP_START) == UTC_DAY
    assert whoop._utc_day(SLEEP_START) != PACIFIC_DAY


# ─────────────────────────────────────────────────────────────────────────────
# The facet itself
# ─────────────────────────────────────────────────────────────────────────────
def test_whoop_declares_the_utc_frame_and_joins_the_derived_set():
    assert day_key_frame_for("whoop") == "utc"
    assert utc_day_key_source_ids() == {"apple_health", "whoop"}, (
        "the UTC-keyed set is derived from the facet. A third member needs the measurement that says its key "
        "is UTC (count the straddling rows in BOTH frames, the #3677/#3913 shape); a member leaving needs a "
        "backfill, not an edit."
    )


def test_the_consequence_note_states_the_price_and_cites_the_ruling():
    """#3677's requirement, met for the source that made it a SET. A frame label is a fact
    a reader nods at; what it costs has to travel with it, on the facet, behind the same
    accessor a consumer would call."""
    note = day_key_frame_consequence_for("whoop")
    assert len(note) >= 80
    assert "17:00" in note and "16:00" in note, "the note must name the PT hour the boundary bites, in both DST halves"
    assert "#3913" in note, "a non-default frame must cite the ruling that chose it"
    assert "fetch_day" in note, "the note must name the MECHANISM — the label/window split is the whole surprise"


def test_the_module_registry_and_the_facet_agree_with_no_exemption_left():
    """The residual, closed and derived. #3666's writer registry declared whoop `utc` while
    the facet silently said `pacific`, and its agreement test carried an explicit
    `if source == "whoop": continue` to tolerate that. Both records must now agree for EVERY
    entry, with nothing skipped — asserted over the live registry so this cannot pass by a
    comment being edited."""
    sys.path.insert(0, str(_REPO / "tests"))
    from test_ingestion_day_key_derivation_3666 import DAY_KEY_WRITERS

    checked = 0
    for name, entry in sorted(DAY_KEY_WRITERS.items()):
        source = entry.get("source")
        if not source:
            continue
        checked += 1
        assert (
            day_key_frame_for(source) == entry["frame"]
        ), f"{name}: module says {entry['frame']!r}, facet says {day_key_frame_for(source)!r}"
    assert checked >= 6, f"only {checked} writers carry a source — the cross-check thinned out"
    assert DAY_KEY_WRITERS["whoop_lambda.py"]["frame"] == "utc"


# ─────────────────────────────────────────────────────────────────────────────
# The arithmetic the facet actually drives
# ─────────────────────────────────────────────────────────────────────────────
def _ops_age(date_str, source, now):
    """The ops checker's age arithmetic (freshness_checker_lambda.py)."""
    return (now - anchor_day_key(date_str, source)).total_seconds() / 3600


def _board_age(date_str, source, now):
    """The public board's age arithmetic (site_api_freshness.py)."""
    return round((now - anchor_day_key(date_str, source)).total_seconds() / 3600, 1)


def test_the_age_is_anchored_at_the_utc_midnight_the_key_names():
    """A `DATE#` day is a DAY. Ageing it means choosing a midnight, and the only defensible
    one is the midnight of the calendar that NAMED it."""
    anchor = anchor_day_key(UTC_DAY, "whoop")
    assert anchor == datetime(2026, 6, 8, 0, 0, tzinfo=timezone.utc)
    assert anchor.utcoffset() == timedelta(0), "a UTC-named day must not be anchored with a Pacific offset"
    assert _board_age(UTC_DAY, "whoop", MIDDAY_PT) == 19.0  # 19h since 2026-06-08T00:00Z


@pytest.mark.parametrize("now", [MIDDAY_PT, EVENING_PT, LATE_PT, WINTER_PT], ids=["midday", "evening", "late", "winter"])
def test_the_pre_flip_pacific_anchor_understated_staleness_by_exactly_the_offset(monkeypatch, now):
    """THE MUST-FAIL CONTROL, run through the real facet rather than a re-implementation:
    put `pacific` back on the registry entry and the age drops by exactly the offset —
    7h in PDT, 8h in PST. That gap is the defect #3913 closes, and it is a gap in the
    UNDER-reporting direction: a whoop partition that had gone quiet looked fresher than it
    was, so the staleness alarm fired up to the full offset late."""
    day = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    honest = _board_age(day, "whoop", now)

    monkeypatch.setitem(SOURCE_REGISTRY["whoop"], "day_key_frame", "pacific")
    assert day_key_frame_for("whoop") == "pacific", "the monkeypatch did not reach the facet — this control is inert"
    pre_flip = _board_age(day, "whoop", now)

    expected_offset = 8.0 if now.astimezone(PACIFIC).utcoffset() == timedelta(hours=-8) else 7.0
    assert round(honest - pre_flip, 1) == expected_offset, f"honest {honest}h vs pre-flip {pre_flip}h — expected a {expected_offset}h gap"
    assert pre_flip < honest, "the pre-flip anchor must be the OPTIMISTIC one; if it is not, the direction of the fix is wrong"


@pytest.mark.parametrize("now", [MIDDAY_PT, EVENING_PT, LATE_PT, WINTER_PT], ids=["midday", "evening", "late", "winter"])
def test_the_ops_checker_and_the_public_board_still_report_the_same_whoop_age(now):
    """#3257's agreement, extended to the source that moved. The two consumers disagreeing
    about one key by 7h is the original defect; changing the frame for one of them only
    would have re-created it."""
    for offset_days in (0, 1, 3, 40):
        day = (now.astimezone(timezone.utc) - timedelta(days=offset_days)).strftime("%Y-%m-%d")
        assert _board_age(day, "whoop", now) == pytest.approx(_ops_age(day, "whoop", now), abs=0.05)


def test_a_pacific_keyed_source_is_untouched_by_this_change():
    """Per-source, never a sweep. The eleven framework-keyed sources must be bit-identical
    after the flip — this is the hazard #3257's blanket-Pacific fix created in the other
    direction, and the reason the frame lives on the registry."""
    for source in ("eightsleep", "withings", "habitify", "strava", "garmin"):
        assert day_key_frame_for(source) == "pacific"
        assert anchor_day_key(UTC_DAY, source).utcoffset() == timedelta(hours=-7)


# ─────────────────────────────────────────────────────────────────────────────
# ON THE WIRE — the real handler, on the real sort-key grammar
# ─────────────────────────────────────────────────────────────────────────────
class _WhoopLatestTable:
    """Serves one stored sort key for every source — the newest whoop key on the live
    partition is normally a `DATE#<d>#WORKOUT#<uuid>` sub-record, which is exactly the
    shape both consumers slice `[:10]` off."""

    def __init__(self, sk):
        self._sk = sk

    def query(self, **kwargs):
        limit = kwargs.get("Limit")
        items = [{"sk": self._sk}]
        return {"Items": items[:limit] if limit is not None else items}

    def get_item(self, Key=None):
        return {}


class _FrozenClock(datetime):
    _at = EVENING_PT

    @classmethod
    def now(cls, tz=None):
        return cls._at.astimezone(tz) if tz is not None else cls._at.replace(tzinfo=None)


def _board(monkeypatch, *, at, stored_sk):
    monkeypatch.setattr(sf, "datetime", type("_At", (_FrozenClock,), {"_at": at}))
    monkeypatch.setattr(sad, "table", _WhoopLatestTable(stored_sk))
    resp = sad.handle_source_freshness()
    body = json.loads(resp["body"]) if isinstance(resp.get("body"), str) else resp["body"]
    return body, {s["id"]: s for s in body["sources"]}


def test_the_served_board_payload_ages_whoop_from_utc_midnight(monkeypatch):
    """The call site, not the helper (#2703: a right helper behind a wrong call site passes
    every unit assertion). Drives `/api/source_freshness` and reads `age_hours` off the
    payload a reader actually gets — on the WORKOUT sub-record grammar."""
    now = MIDDAY_PT
    _, by = _board(monkeypatch, at=now, stored_sk=WORKOUT_SK)
    day = WORKOUT_SK.replace("DATE#", "")[:10]
    row = by["whoop"]
    assert row["last_update"] == day, "the sub-record suffix leaked into the day slice"
    assert row["last_update_ts"] == f"{day}T00:00:00+00:00", "the served anchor must carry the UTC offset, not -07:00"
    expected = round((now - datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc)).total_seconds() / 3600, 1)
    assert row["age_hours"] == expected


def test_the_served_payload_does_not_clamp_an_ahead_of_pt_whoop_day(monkeypatch):
    """#3232 stands. A UTC-named day that PT has not reached yet ages honestly from its own
    UTC midnight and keeps its own date; the board labels the frame instead of hiding the
    row. The label is derived at request time, so whoop inherits it without a code change."""
    now = EVENING_PT
    stored = now.strftime("%Y-%m-%d")  # UTC-today, which is tomorrow in PT
    _, by = _board(monkeypatch, at=now, stored_sk=f"DATE#{stored}")
    row = by["whoop"]
    assert row["last_update"] == stored, "still not clamped (#3232)"
    assert row["age_hours"] == 1.0, "an ahead-of-PT UTC day must age from its own midnight, never to 0 and never negative"
    assert row["last_update_ahead_of_pt"] is True and row["last_update_frame"] == "utc"


# ─────────────────────────────────────────────────────────────────────────────
# The consumer sweep's load-bearing claim: this moves a NUMBER, not an alarm
# ─────────────────────────────────────────────────────────────────────────────
def _ops_tier(age_hours, stale_hours, warning_hours=24):
    """The ops checker's ladder, as freshness_checker_lambda.py runs it."""
    if age_hours > stale_hours:
        return "stale"
    if age_hours >= warning_hours:
        return "warning"
    return "fresh"


@pytest.mark.parametrize("gap_days", [0, 1, 2, 3])
def test_the_ops_alert_tier_is_unchanged_at_the_checkers_own_schedule(gap_days):
    """The sweep result that mattered: at the ONE instant the ops checker actually runs —
    `cron(45 16 * * ? *)`, 9:45 AM PT — the 7h the anchor moves does not cross whoop's
    48h stale threshold or the 24h warning threshold for any gap size. So the flip corrects
    a reported number without minting alarm noise. (The public board is live 24/7 and CAN
    mark whoop stale up to 7h earlier after a >=2-day gap; that is the intended effect, not
    a regression — the data was that old the whole time.)"""
    stale_hours = stale_hours_overrides(["whoop"]).get("whoop", DEFAULT_STALE_HOURS)
    now = CHECKER_CRON
    day = (now.astimezone(timezone.utc) - timedelta(days=gap_days)).strftime("%Y-%m-%d")
    after = _ops_tier(_ops_age(day, "whoop", now), stale_hours)
    before = _ops_tier(_ops_age(day, "eightsleep", now), stale_hours)  # the pre-flip Pacific anchor, same arithmetic
    assert after == before, f"gap {gap_days}d: the flip changed the ops tier from {before} to {after} at the checker's own cron instant"


def test_the_flip_still_makes_a_visible_difference_somewhere():
    """POSITIVE CONTROL for the test above. "No tier change" is only meaningful if the
    numbers genuinely moved — otherwise the sweep is reporting that nothing happened."""
    now = CHECKER_CRON
    day = now.astimezone(timezone.utc).strftime("%Y-%m-%d")
    assert round(_ops_age(day, "whoop", now) - _ops_age(day, "eightsleep", now), 1) == 7.0
