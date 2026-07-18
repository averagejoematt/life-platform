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
"""

from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

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
    sleep_hours, sleep_as_of, steps, steps_source, steps_as_of.

    Every field is honest-null when there is no reading — callers render
    absence, they never substitute a zero.
    """
    now = now or datetime.now(timezone.utc)
    end = (now + timedelta(days=1)).strftime("%Y-%m-%d")  # TZ boundary: a PT record can be dated "tomorrow" in UTC
    start = (now - timedelta(days=LOOKBACK_DAYS)).strftime("%Y-%m-%d")

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
    }

    try:
        whoop = _daily_records(table, user_prefix, "whoop", start, end, limit=LOOKBACK_DAYS + 10)
    except Exception:
        whoop = []

    # Latest FINALIZED recovery record — recovery/hrv/rhr move together from it.
    for rec in whoop:
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
        s = _num(rec, "sleep_duration_hours")
        if s is not None:
            out["sleep_hours"] = s
            out["sleep_as_of"] = _sk_date(rec)
            break

    # Steps: garmin (watch of record) then apple_health, recent days only.
    steps_start = (now - timedelta(days=STEPS_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    for source in ("garmin", "apple_health"):
        try:
            for rec in _daily_records(table, user_prefix, source, steps_start, end, limit=STEPS_LOOKBACK_DAYS + 3):
                s = _num(rec, "steps")
                if s is not None:
                    out["steps"] = s
                    out["steps_source"] = source
                    out["steps_as_of"] = _sk_date(rec)
                    break
        except Exception:
            continue
        if out["steps"] is not None:
            break

    return out
