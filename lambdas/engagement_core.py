"""engagement_core.py — presence / quiet-stretch detection (pure core).

Gives a HUMAN logging-gap a voice. The platform's freshness plumbing already
detects that a manual channel has gone quiet (``freshness_checker``,
``source_state``), but it deliberately stays silent about it —
``BEHAVIORAL_SOURCES`` are excluded from paging and ``adaptive_mode`` returns a
neutral 50 for missing data ("don't penalise for missing data"). Nothing ever
NARRATES the gap. This core computes a *presence state* — is Matthew actively
logging, or has he fallen off routine? — that the coaches and the public site
can then voice.

Pure + deterministic: no boto3, no clock, no I/O. The caller passes ``today``
and, per manual channel, the recent list of logged ``DATE#`` days (the
high-water-mark primitive ``freshness_checker`` uses, widened to a trailing
window so a just-ended lull is detectable). Everything here is a plain data
transform — trivially unit-testable.

THE KEY DISTINCTION this exploits: manual channels (nutrition / workouts /
habits / journal) STOP when Matthew disengages; wearables (whoop / apple_health
/ eightsleep) keep syncing passively. So a lull = manual channels quiet WHILE
the wearables keep talking — which is exactly what lets a coach name the silence
and its measurable consequences (rough sleep, elevated RHR) without knowing, or
fabricating, the reason. The reason for the gap is NEVER in this payload.

24h-lag honesty: manual logs (esp. nutrition) arrive end-of-day, so an absent
same-day log is by-design lag, not disengagement (see ``ai_calls.py``). The gap
used for classification is therefore lag-adjusted — a channel logged today OR
yesterday counts as fully present.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

# ── Channels ────────────────────────────────────────────────────────────────
# Manual channels that STOP when Matthew disengages. Label = the reader-facing
# noun. macrofactor (food) is the PRIMARY anchor: it's the daily-expected manual
# channel and the first, most reliable thing to stop when routine breaks. Source
# keys per the DDB PK (gotchas: journal lives under `notion`, workouts split
# hevy + macrofactor_workouts — hevy is the interactive one).
PRIMARY_CHANNEL = "macrofactor"
MANUAL_CHANNELS = {
    "macrofactor": "food",
    "hevy": "training",
    "habitify": "habits",
    "notion": "journal",
}

# Per-channel staleness tolerance in days (lag-adjusted). Daily-expected channels
# (food, habits) go stale fast; sparse ones (training has legit rest days,
# journaling is inherently intermittent) are lenient so a rest day never reads as
# falling off.
CHANNEL_STALE_DAYS = {
    "macrofactor": 2,
    "habitify": 2,
    "hevy": 4,
    "notion": 4,
}

# Passive wearables — kept flowing by the device, not by Matthew. Their presence
# is what makes "went quiet but the wearables kept talking" true.
WEARABLES = ("whoop", "apple_health", "eightsleep")

# A gap must reach this many (lag-adjusted) days before it's a "lull" worth
# naming or a return worth marking. Below it, a day or two off is just noise.
LULL_MIN_DAYS = 3

# Presence classes, quietest → loudest.
PRESENT = "present"
LIGHT = "light"
QUIET = "quiet"
DARK = "dark"


# ── date helpers ────────────────────────────────────────────────────────────


def _to_date(s):
    if isinstance(s, date):
        return s
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _days_between(a, b):
    """Whole days from a → b (b - a). None if either is unparseable."""
    da, db = _to_date(a), _to_date(b)
    if da is None or db is None:
        return None
    return (db - da).days


def _effective_gap(latest, today):
    """Lag-adjusted days since the latest log. Logged today OR yesterday ⇒ 0
    (the 24h manual-logging grace). None latest ⇒ None (never logged in window)."""
    raw = _days_between(latest, today)
    if raw is None:
        return None
    return max(0, raw - 1)


# ── the computation ─────────────────────────────────────────────────────────


def compute_presence(
    today,
    channel_dates,
    *,
    wearable_latest=None,
    weight_series=None,
    passive_metrics=None,
    sick_days=None,
    travel_days=None,
):
    """Compute the presence / quiet-stretch state.

    Args:
        today: 'YYYY-MM-DD' — the compute reference day.
        channel_dates: {source: [ 'YYYY-MM-DD', ... ]} for the manual channels,
            each a trailing window (~35d) of days that channel logged. Order
            doesn't matter; deduped + sorted internally.
        wearable_latest: {source: latest 'YYYY-MM-DD' or None} for the passive
            wearables — used only to assert "still flowing."
        weight_series: [('YYYY-MM-DD', lbs), ...] — semi-passive weigh-ins, for
            the weight-delta-over-gap "the weight came back" beat on return.
        passive_metrics: optional dict of REAL recent passive reads to carry
            verbatim to the coaches (e.g. {"recovery_trend": "...", "rhr": 64}).
            Never synthesised here — grounding is the caller's job.
        sick_days / travel_days: sets of 'YYYY-MM-DD' — a lull mostly covered by
            these is a PLANNED pause, not falling off.

    Returns a plain dict (the engagement_signal / presence record body). Always
    returns a well-formed record; honest defaults, never raises.
    """
    channel_dates = channel_dates or {}
    sick_days = set(sick_days or ())
    travel_days = set(travel_days or ())

    # Per-channel gap picture.
    channels = {}
    for src, label in MANUAL_CHANNELS.items():
        dates = sorted({d for d in (channel_dates.get(src) or []) if _to_date(d)}, reverse=True)
        latest = dates[0] if dates else None
        gap = _effective_gap(latest, today)
        tol = CHANNEL_STALE_DAYS.get(src, LULL_MIN_DAYS)
        channels[src] = {
            "label": label,
            "last_log_date": latest,
            "gap_days": gap,  # lag-adjusted; None = nothing in window
            "quiet": gap is None or gap > tol,
            "_dates": dates,  # internal, stripped before return
        }

    # Headline anchor = the primary (food) channel.
    primary = channels.get(PRIMARY_CHANNEL, {})
    primary_gap = primary.get("gap_days")
    last_manual_log = _latest_across(channels)
    quiet_channels = [c["label"] for c in channels.values() if c["quiet"]]

    # Planned-pause suppression: how much of the gap window is excused by sick /
    # travel days. If the UNEXCUSED remainder is below a lull, it's a break, not a
    # fall-off.
    gap_days_unexcused, planned_reason = _unexcused_gap(last_manual_log, today, sick_days, travel_days)

    presence_class = _classify(primary_gap, quiet_channels, gap_days_unexcused, planned=bool(planned_reason))

    # Return detection: a fresh primary log immediately after a real lull.
    returned, resumed_after = _detect_return(primary.get("_dates"), today)

    passive_flowing = _passive_flowing(wearable_latest, today)

    signal = {
        "date": today,
        "presence_class": presence_class,
        "gap_days": primary_gap,  # canonical lag-adjusted days since a food log
        "last_manual_log_date": last_manual_log,
        "last_food_log_date": primary.get("last_log_date"),
        "channels_quiet": quiet_channels,
        "channels_quiet_count": len(quiet_channels),
        "passive_still_flowing": passive_flowing,
        "planned_pause": bool(planned_reason),
        "planned_pause_reason": planned_reason,
        "returned": returned,
        "resumed_after_days": resumed_after,
        "channel_detail": {
            src: {"label": c["label"], "last_log_date": c["last_log_date"], "gap_days": c["gap_days"]} for src, c in channels.items()
        },
    }

    if returned and weight_series:
        signal["weight_delta_over_gap"] = _weight_delta_over_gap(weight_series, primary.get("_dates"), resumed_after)

    if passive_metrics:
        # Carried verbatim — the caller has already grounded these in real reads.
        signal["passive_read"] = passive_metrics

    return signal


# ── sub-computations ─────────────────────────────────────────────────────────


def _latest_across(channels):
    """The most recent day ANY manual channel logged."""
    latest = None
    for c in channels.values():
        d = c.get("last_log_date")
        if d and (latest is None or _to_date(d) > _to_date(latest)):
            latest = d
    return latest


def _unexcused_gap(last_manual_log, today, sick_days, travel_days):
    """(unexcused_gap_days, reason) for the window (last_log, yesterday]. A day
    covered by a sick/travel log is excused. Reason names the dominant cause when
    the gap is mostly excused, else ''."""
    if not last_manual_log:
        return None, ""
    start = _to_date(last_manual_log)
    end = _to_date(today)
    if start is None or end is None:
        return None, ""
    # Window is the days AFTER the last log up to (but excluding) today — the
    # by-design-lag grace means today itself is never counted.
    window = [start + timedelta(days=i) for i in range(1, (end - start).days)]
    if not window:
        return 0, ""
    sick_hits = sum(1 for d in window if d.isoformat() in sick_days)
    travel_hits = sum(1 for d in window if d.isoformat() in travel_days)
    excused = sum(1 for d in window if d.isoformat() in sick_days or d.isoformat() in travel_days)
    unexcused = len(window) - excused
    reason = ""
    if excused and unexcused < LULL_MIN_DAYS:
        reason = "travel" if travel_hits >= sick_hits else "sick"
    return unexcused, reason


def _classify(primary_gap, quiet_channels, gap_days_unexcused, *, planned):
    """Presence class from the food-gap length. Corroborating quiet channels only
    nudge the borderline 2-day case (everything stopping at once is more telling
    than food alone). A planned pause never escalates past 'light'. Because a real
    fall-off silences every channel together, gap LENGTH — not channel count —
    drives the quiet→dark escalation."""
    if primary_gap is None:
        # No food log anywhere in the trailing window — dark unless excused (then a
        # long planned break, held at light).
        return LIGHT if planned else DARK
    if primary_gap <= 1:
        return PRESENT
    if planned:
        return LIGHT
    if primary_gap >= 5:
        return DARK
    if primary_gap >= 3:
        return QUIET
    # primary_gap == 2 — a day off; only 'quiet' if every channel went silent too.
    return QUIET if len(quiet_channels) >= 3 else LIGHT


def _detect_return(primary_dates, today):
    """(returned, resumed_after_days). True when the primary channel logged
    fresh (today/yesterday) DIRECTLY after a real lull. resumed_after_days = the
    number of missed days in that lull."""
    if not primary_dates or len(primary_dates) < 2:
        return False, None
    latest, prev = primary_dates[0], primary_dates[1]
    if _effective_gap(latest, today) != 0:
        return False, None  # not fresh — an ongoing gap, not a return
    missed = _days_between(prev, latest)
    if missed is None:
        return False, None
    missed_days = missed - 1  # exclusive of both endpoints
    if missed_days >= LULL_MIN_DAYS:
        return True, missed_days
    return False, None


def _passive_flowing(wearable_latest, today):
    """True if at least one wearable has a reading within the last 2 days."""
    if not wearable_latest:
        return None
    for src in WEARABLES:
        latest = wearable_latest.get(src)
        gap = _days_between(latest, today)
        if gap is not None and gap <= 2:
            return True
    return False


def _weight_delta_over_gap(weight_series, primary_dates, resumed_after):
    """lbs regained over the gap: latest weigh-in minus the weigh-in nearest the
    lull's start. Positive = regain. None if the readings don't bracket it."""
    if not weight_series or not primary_dates or len(primary_dates) < 2:
        return None
    parsed = sorted(
        ((_to_date(d), float(w)) for d, w in weight_series if _to_date(d) is not None and w is not None),
        key=lambda x: x[0],
    )
    if len(parsed) < 2:
        return None
    gap_start = _to_date(primary_dates[1])  # last engaged day before the lull
    if gap_start is None:
        return None
    # Baseline = last weigh-in on/before the gap start; current = latest weigh-in.
    baseline = None
    for d, w in parsed:
        if d <= gap_start:
            baseline = w
        else:
            break
    if baseline is None:
        return None
    current = parsed[-1][1]
    return round(current - baseline, 1)
