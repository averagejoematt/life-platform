"""web/vitals_resolver.py — the Truth Spine (#1369).

ONE latest-reading resolution for the public "current vitals" — recovery, HRV,
RHR, sleep, steps. Every public surface that serves the current numbers
(/api/pulse, /api/vitals → /api/snapshot, and both public_stats.json writers)
reads THIS module, so two pages can never disagree about the same morning.
tests/test_vitals_truth_spine.py is the cross-surface contract gate.

Canonical semantics:
- recovery/hrv/rhr come from the newest whoop record whose recovery_score is
  actually populated ("latest finalized" — the newest record can be unscored
  until the night's sleep syncs). The three move together from one morning's
  reading; a color is never served without a number behind it (ADR-104).
- sleep comes from the newest whoop record carrying sleep_duration_hours
  (sleep finalizes separately from recovery).
- steps prefer garmin (the watch of record), falling back to apple_health,
  within the last ~2 days only — older step counts aren't "current".
- No genesis clamp and no phase filter: the latest reading is the latest
  reading regardless of experiment cycle (same liveness reasoning as the
  freshness board, #1203). Provenance is the *_as_of date — consumers surface
  staleness, they don't zero it. Trailing-window TRENDS keep their ADR-077
  genesis clamp in their own handlers; the clamp is about windows, never about
  what the body's latest reading is.
- Honest absence (ADR-104): no reading in the lookback ⇒ value None AND status
  None. Never 0.0, never a color for a missing number.
- The selected record may not name a day the PACIFIC calendar has not reached
  (#3287). See `reached_in_pacific` — this is the one place the scan's widened
  bound is separated from what is allowed to WIN it.
"""

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key
from common.pacific_time import PACIFIC  # #1964: THE Pacific frame — never a local ZoneInfo
from ingestion.source_registry import day_key_frame_for  # #3257: which calendar a source's DATE# key names

# Recovery/sleep lookback: generous enough to survive a multi-day sync gap —
# the as_of date keeps staleness visible. Steps go stale in 2 days.
LOOKBACK_DAYS = 14
STEPS_LOOKBACK_DAYS = 2


def recovery_status(pct):
    """Status color for a recovery %, or None when there's no reading.

    The ONE home of the 67/34 thresholds. Never returns a color without a
    number behind it — "recovery_pct: null + recovery_status: red" was the
    honesty bug this module exists to make structurally impossible.
    """
    if pct is None:
        return None
    return "green" if pct >= 67 else ("yellow" if pct >= 34 else "red")


def _num(record, field):
    """float(record[field]) or None — 0/absent/unparseable are all None."""
    try:
        v = record.get(field)
        if v is None:
            return None
        f = float(str(v))
        return f if f != 0.0 else None
    except (TypeError, ValueError):
        return None


def _sk_date(record):
    sk = str(record.get("sk", ""))
    return sk.replace("DATE#", "")[:10] or None


def reached_in_pacific(date_str, pt_today):
    """Has the PACIFIC calendar reached the day this ``DATE#`` key names? (#3287)

    THE DEFECT THIS EXISTS FOR. The scan below deliberately runs to ``now + 1 day``
    so a boundary record is never *missed*; ``ScanIndexForward=False`` then hands the
    loop the newest key first and the loop takes it. Those two facts together meant
    the newest key always WON, and for ``apple_health`` — the one source whose
    ``DATE#`` names a **UTC** day (TD-19 Phase 2, registry facet ``day_key_frame``) —
    a fresh partial next-UTC-day record outranks the real Pacific-day total from
    ~17:00 PT every evening. Measured live at 21:01 PDT on 2026-08-27: ``/api/pulse``
    served ``movement.as_of = 2026-08-28`` on a page whose own date was 2026-08-27,
    a two-digit partial rendered red against an 8,000-step target while the Pacific
    day's real three-digit total sat one row down. Roughly 7 hours of every day.

    THE FIX IS THE SELECTION, NOT THE WINDOW. The widened bound stays (a record must
    still be *fetched* to be considered at all); what changed is that a key naming a
    day the Pacific calendar has not reached can no longer win. This is the same
    comparison ``site_api_freshness`` already makes to stamp ``last_update_ahead_of_pt``
    — one house convention applied to a second consumer, not a fourth one invented.

    AND IT IS NOT A CLAMP (#3232). The stored UTC key is correct and is never
    rewritten; the record is simply not "today, so far". Its own day will be reachable
    tomorrow and it wins then, with its own date on it.

    Per-source, not blanket: for every Pacific-keyed source (11 of 12 — the framework
    stamps ``pacific_today()``) this predicate is a no-op by construction, because a
    Pacific key can never name a day Pacific has not reached. It only ever bites the
    UTC-keyed source, which is why the frame is read from the registry rather than
    assumed. A blanket Pacific *anchor* would have made apple_health's age negative
    for the same 7 hours — see tests/test_freshness_age_frame_3257.py's hazard control.
    """
    return not (date_str and pt_today and date_str > pt_today)


def _pacific_today(now):
    """The Pacific calendar day of an aware instant — the day the page is showing."""
    return now.astimezone(PACIFIC).strftime("%Y-%m-%d")


def _daily_records(table, user_prefix, source, start, end, limit):
    """Newest-first DATE# daily records for source, workout sub-records skipped.

    No phase filter (see module docstring) — raw recency truth.
    """
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{user_prefix}{source}") & Key("sk").between(f"DATE#{start}", f"DATE#{end}~"),
        ScanIndexForward=False,
        Limit=limit,
    )
    return [i for i in resp.get("Items", []) if "#WORKOUT#" not in str(i.get("sk", ""))]


def resolve_vitals(table, user_prefix, now=None):
    """The canonical current-vitals read. Returns a dict of plain floats/None:

    recovery_pct, recovery_status, hrv_ms, rhr_bpm, recovery_as_of,
    sleep_hours, sleep_as_of, steps, steps_source, steps_as_of,
    steps_as_of_frame.

    Every field is honest-null when there is no reading — callers render
    absence, they never substitute a zero.
    """
    now = now or datetime.now(timezone.utc)
    # #3287 re-worded this exemption's boundary rather than deleting it. The window is
    # genuinely frame-tolerant and stays; what was FALSE in the old wording is "the newest
    # record wins" — true only for a Pacific-keyed source. The SELECTION is not exempt, and
    # `reached_in_pacific` below is where that line is now drawn.
    # utc-exempt(#2414, bounded by #3287): WIDENED scan bounds, never a reader "today".
    end = (now + timedelta(days=1)).strftime("%Y-%m-%d")  # TZ boundary: a PT record can be dated "tomorrow" in UTC
    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    pt_today = _pacific_today(now)

    out = {
        "recovery_pct": None,
        "recovery_status": None,
        "hrv_ms": None,
        "rhr_bpm": None,
        "recovery_as_of": None,
        "sleep_hours": None,
        "sleep_as_of": None,
        "steps": None,
        "steps_source": None,
        "steps_as_of": None,
        # #3287: WHICH CALENDAR `steps_as_of` names. Absent/None until a reading
        # resolves (ADR-104 — an empty spine is all-None and stays that way). "utc"
        # is the honest disclosure a consumer needs to say "the day that closed at
        # 17:00 PT", not "today so far", when the winning key is UTC-framed.
        "steps_as_of_frame": None,
    }

    try:
        whoop = _daily_records(table, user_prefix, "whoop", start, end, limit=LOOKBACK_DAYS + 10)
    except Exception:
        whoop = []

    # Latest FINALIZED recovery record — recovery/hrv/rhr move together from it.
    for rec in whoop:
        if not reached_in_pacific(_sk_date(rec), pt_today):
            continue
        r = _num(rec, "recovery_score")
        if r is not None:
            out["recovery_pct"] = r
            out["recovery_status"] = recovery_status(r)
            out["hrv_ms"] = _num(rec, "hrv")
            out["rhr_bpm"] = _num(rec, "resting_heart_rate")
            out["recovery_as_of"] = _sk_date(rec)
            break

    # Sleep finalizes separately — newest record that carries it.
    for rec in whoop:
        if not reached_in_pacific(_sk_date(rec), pt_today):
            continue
        s = _num(rec, "sleep_duration_hours")
        if s is not None:
            out["sleep_hours"] = s
            out["sleep_as_of"] = _sk_date(rec)
            break

    # Steps: garmin (watch of record) then apple_health, recent days only. apple_health's
    # DATE# names a UTC day, so the newest key in this range is a partial next-UTC-day
    # record for ~7h every evening; the scan still fetches it, `reached_in_pacific` refuses
    # to let it win, and the Pacific day's record is served instead (#3287).
    # utc-exempt(#2414, bounded by #3287): the same widened-bounds SCAN as above.
    steps_start = (now - timedelta(days=STEPS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    for source in ("garmin", "apple_health"):
        try:
            for rec in _daily_records(table, user_prefix, source, steps_start, end, limit=STEPS_LOOKBACK_DAYS + 3):
                day = _sk_date(rec)
                if not reached_in_pacific(day, pt_today):
                    continue
                s = _num(rec, "steps")
                if s is not None:
                    out["steps"] = s
                    out["steps_source"] = source
                    out["steps_as_of"] = day
                    out["steps_as_of_frame"] = day_key_frame_for(source)
                    break
        except Exception:
            continue
        if out["steps"] is not None:
            break

    return out
