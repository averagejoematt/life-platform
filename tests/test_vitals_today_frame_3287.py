"""#3287 — /data/vitals/ "TODAY, SO FAR" served a partial next-UTC-day step count.

THE DEFECT, VERIFIED LIVE 2026-08-27
------------------------------------
``/api/pulse`` returned ``movement: {as_of: "2026-08-28"}`` on a page whose own ``date``
was ``2026-08-27``. Measured at 04:01 UTC = 21:01 PDT — there is no Pacific 2026-08-28
yet. DynamoDB carried a three-digit step count on ``DATE#2026-08-27`` and a two-digit
partial on ``DATE#2026-08-28``; the partial won, and ``_movement_state()`` coloured it
**red** against an 8,000-step target.

Mechanism, in ``web/vitals_resolver.py``:

  * the scan ends at ``now_utc + 1 day`` — deliberate, so a boundary record is not MISSED
  * ``ScanIndexForward=False`` — newest key first
  * the loop takes the FIRST record carrying ``steps``

``apple_health`` is the one source whose ``DATE#`` key names a **UTC** day (TD-19 Phase 2;
registry facet ``day_key_frame``), so from ~17:00 PT a freshly-written partial UTC-day
record is the newest key and displaces the real Pacific-day total. Roughly **7 hours of
every day** — invisible for the other 17, which is why nothing caught it.

WHAT CHANGED, AND WHAT DELIBERATELY DID NOT
-------------------------------------------
The WINDOW is unchanged. #2414's widened bound is right and narrowing it would reintroduce
the miss it was written to prevent; ``test_the_scan_window_was_not_narrowed`` pins that.
What changed is the SELECTION: ``reached_in_pacific`` refuses a key naming a day the
Pacific calendar has not reached.

It is NOT a clamp. #3232 ruled the stored UTC key correct and refused to rewrite it; that
ruling stands and is re-asserted below — the skipped record keeps its own date and wins
tomorrow, on its own day.

THE CLOCK THESE TESTS RUN ON
----------------------------
Every instant is INJECTED. #3206 shipped green because its CI happened to run at 13:00 PT
while the test failed 7 of every 24 hours; a gate for an evening-only defect that can only
ever see the afternoon is not a gate. The whole 17:00–24:00 PT window is exercised, on both
sides of DST, in both frames.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import pytest

os.environ.setdefault("TABLE_NAME", "life-platform")
os.environ.setdefault("S3_BUCKET", "matthew-life-platform")
os.environ.setdefault("USER_ID", "matthew")
os.environ.setdefault("AWS_REGION", "us-west-2")

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "lambdas"))

from common.pacific_time import PACIFIC  # noqa: E402
from ingestion.source_registry import day_key_frame_for  # noqa: E402
from web import (  # noqa: E402
    site_api_common as common,
    site_api_intelligence as intel,
    site_api_pulse as pulse_mod,
    vitals_resolver,
)

# The instants that matter, expressed in UTC and converted, so there is no ambiguity about
# which side of the 17:00 PT rollover each one sits on.
MIDDAY_PT = datetime(2026, 8, 27, 19, 0, tzinfo=timezone.utc)  # 12:00 PDT — UTC-today == PT-today
ROLLOVER_PT = datetime(2026, 8, 28, 0, 1, tzinfo=timezone.utc)  # 17:01 PDT — the first minute of the window
EVENING_PT = datetime(2026, 8, 28, 4, 1, tzinfo=timezone.utc)  # 21:01 PDT — the instant #3287 was measured at
LATE_PT = datetime(2026, 8, 28, 6, 59, tzinfo=timezone.utc)  # 23:59 PDT — the last minute before PT rollover
WINTER_PT = datetime(2026, 12, 16, 2, 0, tzinfo=timezone.utc)  # 18:00 PST — the 8h offset, DST's other side

PT_EVENING_WINDOW = [ROLLOVER_PT, EVENING_PT, LATE_PT, WINTER_PT]
ALL_INSTANTS = [MIDDAY_PT] + PT_EVENING_WINDOW
_IDS = ["midday", "rollover", "evening", "late", "winter"]

# Synthetic counts, deliberately far apart so a wrong selection cannot look like a rounding
# difference: the Pacific day's real total vs the few-hours-old next-UTC-day partial.
PACIFIC_DAY_STEPS = 9310
NEXT_UTC_DAY_PARTIAL_STEPS = 41
PACIFIC_DAY_WATER_ML = 2400
NEXT_UTC_DAY_PARTIAL_WATER_ML = 150

_AH_PK = "USER#matthew#SOURCE#apple_health"
_GARMIN_PK = "USER#matthew#SOURCE#garmin"
_WHOOP_PK = "USER#matthew#SOURCE#whoop"


def _pt(now):
    return now.astimezone(PACIFIC).strftime("%Y-%m-%d")


def _utc(now):
    return now.strftime("%Y-%m-%d")


def _ah_record(day, steps, water_ml=2400):
    """The wire shape health_auto_export_lambda writes: a UTC-framed DATE# key, the
    canonical `steps` field, and the sibling daily fields that ride the same partition —
    `water_intake_ml` included, because the pulse's water glyph is fed by the SAME
    newest-row selection and inherited the same defect."""
    return {
        "pk": _AH_PK,
        "sk": f"DATE#{day}",
        "date": day,
        "steps": steps,
        "water_intake_ml": water_ml,
        "active_energy_kcal": 430,
        "updated_at": f"{day}T00:12:04+00:00",
    }


class FakeTable:
    """Answers table.query() from {pk: [items]}, honouring the Key("sk").between(...)
    range and ScanIndexForward/Limit — the DynamoDB behaviours the selection depends on."""

    def __init__(self, by_pk=None):
        self.by_pk = by_pk or {}
        self.queries = []

    @staticmethod
    def _find_pk(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        for v in vals:
            got = FakeTable._find_pk(v) if hasattr(v, "_values") else (v if isinstance(v, str) else None)
            if isinstance(got, str) and got.startswith("USER#"):
                return got
        return None

    @staticmethod
    def _find_sk_range(cond):
        vals = getattr(cond, "_values", None)
        if vals is None:
            return None
        key = vals[0] if vals else None
        if getattr(key, "name", None) == "sk" and getattr(cond, "expression_operator", None) == "BETWEEN" and len(vals) == 3:
            return (vals[1], vals[2])
        for v in vals:
            if hasattr(v, "_values"):
                found = FakeTable._find_sk_range(v)
                if found:
                    return found
        return None

    def query(self, **kwargs):
        cond = kwargs.get("KeyConditionExpression")
        pk = self._find_pk(cond) if cond is not None else None
        sk_range = self._find_sk_range(cond) if cond is not None else None
        self.queries.append((pk, sk_range))
        items = list(self.by_pk.get(pk, []))
        if sk_range:
            lo, hi = sk_range
            items = [i for i in items if lo <= str(i.get("sk", "")) <= hi]
        if kwargs.get("ScanIndexForward") is False:
            items = sorted(items, key=lambda i: str(i.get("sk", "")), reverse=True)
        limit = kwargs.get("Limit")
        return {"Items": items[:limit] if limit else items}

    def get_item(self, **kwargs):
        return {}


def _both_days_table(now, *, with_garmin=False):
    """THE fixture that creates the bug: the Pacific day's real total AND the next-UTC-day
    partial, both present, exactly as they sit in DynamoDB during the PT evening."""
    days = {_pt(now): (PACIFIC_DAY_STEPS, PACIFIC_DAY_WATER_ML)}
    if _utc(now) != _pt(now):
        days[_utc(now)] = (NEXT_UTC_DAY_PARTIAL_STEPS, NEXT_UTC_DAY_PARTIAL_WATER_ML)
    by_pk = {_AH_PK: [_ah_record(d, st, wa) for d, (st, wa) in days.items()]}
    if with_garmin:
        by_pk[_GARMIN_PK] = [{"sk": f"DATE#{_pt(now)}", "steps": 8123}]
    return FakeTable(by_pk)


# ─────────────────────────────────────────────────────────────────────────────
# The resolver — the selection itself
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("now", ALL_INSTANTS, ids=_IDS)
def test_the_pacific_day_record_wins_not_the_next_utc_day_partial(now):
    """THE must-fail case. With both records present at a pinned PT-evening instant, the
    resolver must serve the Pacific day's total. Before the fix the newest key won and this
    returned the two-digit partial dated tomorrow."""
    out = vitals_resolver.resolve_vitals(_both_days_table(now), "USER#matthew#SOURCE#", now=now)
    assert out["steps"] == PACIFIC_DAY_STEPS, (
        f"at {now.isoformat()} (PT {_pt(now)}) the resolver served {out['steps']} steps "
        f"as_of {out['steps_as_of']} — the next-UTC-day partial, not the Pacific day"
    )
    assert out["steps_as_of"] == _pt(now)
    assert out["steps_as_of"] <= _pt(now), "no record dated ahead of Pacific today may ever be selected"
    assert out["steps_source"] == "apple_health"


@pytest.mark.parametrize("now", PT_EVENING_WINDOW, ids=_IDS[1:])
def test_the_pre_fix_selection_reproduced_the_filed_symptom(now):
    """POSITIVE CONTROL. A test that only ever sees the fixed code cannot say whether it is
    exercising the defect (#3220's vacuous-control class). This runs the OLD rule — "take
    the first record carrying steps" — over the same fixture and asserts it produces the
    filed symptom: an as_of ahead of the page's Pacific date, with the partial count."""
    table = _both_days_table(now)
    end = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    start = (now - timedelta(days=vitals_resolver.STEPS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    rows = vitals_resolver._daily_records(table, "USER#matthew#SOURCE#", "apple_health", start, end, limit=5)
    pre_fix = next(r for r in rows if vitals_resolver._num(r, "steps") is not None)
    assert vitals_resolver._sk_date(pre_fix) == _utc(now) > _pt(now), "the control is not sitting in the defect's window"
    assert vitals_resolver._num(pre_fix, "steps") == NEXT_UTC_DAY_PARTIAL_STEPS


@pytest.mark.parametrize("now", ALL_INSTANTS, ids=_IDS)
def test_garmin_still_outranks_apple_health(now):
    """The pre-existing source policy is untouched: garmin is the watch of record. The
    selection guard must not have quietly become a source preference."""
    out = vitals_resolver.resolve_vitals(_both_days_table(now, with_garmin=True), "USER#matthew#SOURCE#", now=now)
    assert out["steps_source"] == "garmin"
    assert out["steps"] == 8123
    assert out["steps_as_of_frame"] == "pacific"


def test_the_scan_window_was_not_narrowed():
    """#2414's widened bound is DELIBERATE and stays. The fix is which record may win, not
    which records are fetched — narrowing the window would reintroduce the missed boundary
    record it was written to prevent. Read the range the resolver actually asked DDB for."""
    now = EVENING_PT
    table = _both_days_table(now)
    vitals_resolver.resolve_vitals(table, "USER#matthew#SOURCE#", now=now)
    ah_ranges = [rng for pk, rng in table.queries if pk == _AH_PK and rng]
    assert ah_ranges, "the resolver did not query apple_health at all"
    hi = ah_ranges[0][1]
    tomorrow_utc = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    assert hi.startswith(f"DATE#{tomorrow_utc}"), f"the scan's upper bound moved to {hi} — #2414's widened window must stay"


@pytest.mark.parametrize("now", PT_EVENING_WINDOW, ids=_IDS[1:])
def test_the_skipped_record_is_not_clamped_and_wins_on_its_own_day(now):
    """#3232's ruling, re-asserted. The UTC key is correct and is never rewritten — the
    record is simply not "today, so far". One day later the Pacific calendar has reached
    it, and it is served, under its OWN date."""
    table = _both_days_table(now)
    tomorrow = now + timedelta(days=1)
    out = vitals_resolver.resolve_vitals(table, "USER#matthew#SOURCE#", now=tomorrow)
    assert out["steps"] == NEXT_UTC_DAY_PARTIAL_STEPS
    assert out["steps_as_of"] == _utc(now), "the stored key was rewritten — that would be the clamp #3232 refused"


def test_a_lone_next_utc_day_record_does_not_fabricate_a_zero():
    """ADR-104. When the ONLY record in range names an unreached day, steps resolve to
    None — honest absence — never 0 and never a colour. `_movement_state` renders gray."""
    now = EVENING_PT
    table = FakeTable({_AH_PK: [_ah_record(_utc(now), NEXT_UTC_DAY_PARTIAL_STEPS)]})
    out = vitals_resolver.resolve_vitals(table, "USER#matthew#SOURCE#", now=now)
    assert out["steps"] is None and out["steps_source"] is None and out["steps_as_of"] is None
    assert out["steps_as_of_frame"] is None


def test_the_guard_covers_the_whole_spine_not_just_steps():
    """Guard the SET, not the instance. recovery and sleep run the same newest-first scan
    over the same widened window; a whoop row dated past Pacific today (a bad backfill —
    whoop is Pacific-keyed, so such a row can only be corrupt) must not become "today's"
    reading either."""
    now = EVENING_PT
    ahead = (now.astimezone(PACIFIC) + timedelta(days=2)).strftime("%Y-%m-%d")
    real = _pt(now)
    table = FakeTable(
        {
            _WHOOP_PK: [
                {"sk": f"DATE#{ahead}", "recovery_score": 12, "hrv": 20.0, "resting_heart_rate": 80, "sleep_duration_hours": 3.0},
                {"sk": f"DATE#{real}", "recovery_score": 71, "hrv": 62.0, "resting_heart_rate": 51, "sleep_duration_hours": 7.6},
            ]
        }
    )
    out = vitals_resolver.resolve_vitals(table, "USER#matthew#SOURCE#", now=now)
    assert out["recovery_pct"] == 71 and out["recovery_as_of"] == real
    assert out["sleep_hours"] == 7.6 and out["sleep_as_of"] == real


# ─────────────────────────────────────────────────────────────────────────────
# The frame facet — per-source, never a blanket sweep
# ─────────────────────────────────────────────────────────────────────────────
def test_the_frame_comes_from_the_registry_and_travels_with_the_date():
    """#3257's facet is the reason this is per-source. apple_health's DATE# names a UTC
    day, so `as_of == pacific_today` does NOT mean "the Pacific day so far" — it means the
    UTC day that closed at 17:00 PT. The consumer cannot say that unless the API says which
    calendar the date is in, so the frame ships beside it."""
    assert day_key_frame_for("apple_health") == "utc"
    assert day_key_frame_for("garmin") == "pacific"
    now = EVENING_PT
    out = vitals_resolver.resolve_vitals(_both_days_table(now), "USER#matthew#SOURCE#", now=now)
    assert out["steps_as_of_frame"] == "utc"


@pytest.mark.parametrize("now", PT_EVENING_WINDOW, ids=_IDS[1:])
def test_a_pacific_keyed_source_is_untouched_by_the_guard(now):
    """Per-source, not blanket (lane A's #3257 hazard control in the selection layer). For
    a Pacific-keyed source the predicate is a no-op by construction — a Pacific key can
    never name a day Pacific has not reached — so garmin's behaviour is bit-identical."""
    table = FakeTable({_GARMIN_PK: [{"sk": f"DATE#{_pt(now)}", "steps": 5001}]})
    out = vitals_resolver.resolve_vitals(table, "USER#matthew#SOURCE#", now=now)
    assert out["steps"] == 5001 and out["steps_as_of"] == _pt(now)
    assert vitals_resolver.reached_in_pacific(_pt(now), _pt(now)) is True


def test_the_predicate_is_the_house_comparison_not_a_new_one():
    """`site_api_freshness` already stamps `last_update_ahead_of_pt` with exactly this
    comparison. Same question, same answer — a second consumer of one convention, not a
    fourth convention (and not a second frame resolver: #3257's `day_key_frame_for` is
    where the frame is decided, here and there)."""
    assert vitals_resolver.reached_in_pacific("2026-08-28", "2026-08-27") is False
    assert vitals_resolver.reached_in_pacific("2026-08-27", "2026-08-27") is True
    assert vitals_resolver.reached_in_pacific("2026-08-26", "2026-08-27") is True
    assert vitals_resolver.reached_in_pacific(None, "2026-08-27") is True  # no date ⇒ nothing to refuse
    src = open(os.path.join(_REPO, "lambdas", "web", "site_api_freshness.py"), encoding="utf-8").read()
    assert "last_update > pt_today" in src, "the sibling comparison moved — re-derive which convention this follows"


# ─────────────────────────────────────────────────────────────────────────────
# ON THE WIRE — the real /api/pulse handler, not the helper
# ─────────────────────────────────────────────────────────────────────────────
# Everything above tests the resolver. Necessary, not sufficient: a fix whose helper is
# right and whose CALL SITE is not passes all of it (#2703). These drive the routed handler
# at a constructed instant and read the payload a reader gets.


def _frozen(at):
    return type(
        "_At",
        (datetime,),
        {"_at": at, "now": classmethod(lambda cls, tz=None: cls._at.astimezone(tz) if tz else cls._at.replace(tzinfo=None))},
    )


def _pulse(monkeypatch, now, table):
    monkeypatch.setattr(pulse_mod, "datetime", _frozen(now))
    monkeypatch.setattr(vitals_resolver, "datetime", _frozen(now))
    monkeypatch.setattr(intel, "table", table)
    monkeypatch.setattr(intel, "_latest_item", lambda *a, **k: None)
    monkeypatch.setattr(intel, "_get_profile", lambda: {"journey_start_weight_lbs": 315.0})
    monkeypatch.setattr(common, "EXPERIMENT_START", "2026-08-17")
    monkeypatch.setattr(intel, "EXPERIMENT_START", "2026-08-17")
    return json.loads(intel.handle_pulse()["body"])["pulse"]


@pytest.mark.parametrize("now", PT_EVENING_WINDOW, ids=_IDS[1:])
def test_the_served_pulse_never_dates_a_glyph_past_its_own_page(monkeypatch, now):
    """THE FILED SYMPTOM, on the wire: `pulse.date = 2026-08-27` and
    `glyphs.movement.as_of = 2026-08-28` in ONE payload. Read the two fields against each
    other, the way the page does."""
    if now is WINTER_PT:
        monkeypatch.setattr(common, "EXPERIMENT_START", "2026-12-01")
    p = _pulse(monkeypatch, now, _both_days_table(now))
    mv = p["glyphs"]["movement"]
    assert p["date"] == _pt(now)
    assert mv["as_of"] <= p["date"], f"the page is dated {p['date']} and the movement glyph claims {mv['as_of']} — the #3287 contradiction"
    assert mv["value"] == PACIFIC_DAY_STEPS
    assert mv["state"] == "green", "the Pacific day's real total is above the 8,000 target — the partial is what read red"
    assert mv["as_of_frame"] == "utc", "the frame must travel to the consumer or the date reads as Pacific"


@pytest.mark.parametrize("now", PT_EVENING_WINDOW, ids=_IDS[1:])
def test_the_water_glyph_stops_asserting_today_for_another_days_record(monkeypatch, now):
    """The same selection fed `water` and the weight fallback out of a `Limit=1` query over
    the same widened range, under a comment claiming it fetched "the PT-date record
    specifically". The water glyph then stamped an unconditional `as_of: today_pt`."""
    if now is WINTER_PT:
        monkeypatch.setattr(common, "EXPERIMENT_START", "2026-12-01")
    p = _pulse(monkeypatch, now, _both_days_table(now))
    water = p["glyphs"]["water"]
    assert water["liters"] == PACIFIC_DAY_WATER_ML / 1000, (
        f"the water glyph served {water['liters']}L — the next-UTC-day partial "
        f"({NEXT_UTC_DAY_PARTIAL_WATER_ML}ml), not the Pacific day's total"
    )
    assert water["as_of"] <= p["date"], "the water glyph published a next-UTC-day record as today's hydration"
    assert water["as_of"] == _pt(now)


def test_a_stale_hydration_record_wears_its_real_date(monkeypatch):
    """And the other direction: when apple_health is behind, the water glyph no longer claims
    today. The number is still served (provenance, not zeroing — the resolver's contract);
    the DATE is what becomes honest, which is what the page needs in order to disclose it.
    One day back, because the pulse's own apple_health range starts at yesterday-PT — a
    record older than that is not fetched at all and the glyph is simply gray."""
    now = MIDDAY_PT
    stale = (now.astimezone(PACIFIC) - timedelta(days=1)).strftime("%Y-%m-%d")
    p = _pulse(monkeypatch, now, FakeTable({_AH_PK: [_ah_record(stale, 4200)]}))
    assert p["glyphs"]["water"]["as_of"] == stale != p["date"]
