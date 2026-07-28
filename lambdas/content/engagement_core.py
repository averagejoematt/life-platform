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

# ── Channels — DERIVED from source_registry (#914, the #498 drift cure) ─────
# Manual channels that STOP when Matthew disengages. The channel set, labels,
# staleness tolerances, and per-source presence predicates are the
# `engagement_channel` facet in lambdas/source_registry.py — this module only
# projects them (gotchas the registry documents: journal lives under `notion`;
# hevy is the interactive workout channel; habitify writes a record every day so
# it needs a completion predicate). source_registry is pure data — importing it
# keeps this core boto3/clock/I-O free.
# NB: the loud rung has no constant to import — dark itself begins at
# ENGAGEMENT_SEVERITY_LOUD_DARK_DAYS (=5, see _classify's `primary_gap >= 5`),
# so dark→loud is definitional; only the alarm escalations need thresholds here.
from source_registry import (
    ENGAGEMENT_SEVERITY_ALARM_CHANNEL_QUIET_DAYS,
    ENGAGEMENT_SEVERITY_ALARM_DARK_DAYS,
    ENGAGEMENT_SEVERITY_ALARM_QUIET_CHANNELS,
    engagement_channels,
    engagement_primary_channel,
)

_CHANNELS = engagement_channels()
PRIMARY_CHANNEL = engagement_primary_channel()
MANUAL_CHANNELS = {k: v["label"] for k, v in _CHANNELS.items()}
CHANNEL_STALE_DAYS = {k: v["stale_days"] for k, v in _CHANNELS.items()}

# ── Presence predicates (#914) ──────────────────────────────────────────────
# Does a DDB record for this source count as Matthew actually LOGGING that day?
# Default: any record. habitify's hourly pull writes a record EVERY day even at
# total_completed=0, so a 14-day zero-completion stall read as gap_days=0 — its
# predicate counts a day only when at least one habit was completed. Predicates
# are pure item→bool; the registry facet names them, this dict resolves them.
PRESENCE_PREDICATES = {
    "habitify_completed": lambda item: _as_float((item or {}).get("total_completed")) > 0,
}

# Extra DDB attributes a predicate needs (the caller's query projects sk only by
# default — it must widen the projection for these sources).
PRESENCE_PREDICATE_FIELDS = {
    "habitify_completed": ("total_completed",),
}


def _as_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def channel_presence_fields(source):
    """Extra DDB attributes the source's presence predicate reads ((),) if none."""
    name = (_CHANNELS.get(source) or {}).get("presence_predicate")
    return PRESENCE_PREDICATE_FIELDS.get(name, ())


def channel_counts_as_logged(source, item):
    """True if this DDB record counts as Matthew logging that day (per the
    source's registry-named predicate; sources without one count any record)."""
    name = (_CHANNELS.get(source) or {}).get("presence_predicate")
    pred = PRESENCE_PREDICATES.get(name)
    return True if pred is None else bool(pred(item))


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

# Severity ladder (#914) — how loudly the narrative surfaces must treat the gap.
# Thresholds live in source_registry next to the engagement_channel facet
# definitions (imported above). A planned pause always de-escalates to none.
SEVERITY_NONE = "none"
SEVERITY_SOFT = "soft"
SEVERITY_LOUD = "loud"
SEVERITY_ALARM = "alarm"

# Severities at which the acknowledgment gate arms (generated narratives MUST
# reference the gap or be regenerated/held — the ADR-108 pattern).
ACK_SEVERITIES = (SEVERITY_LOUD, SEVERITY_ALARM)


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
    experiment_start=None,
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
        experiment_start: 'YYYY-MM-DD' or None — the genesis clamp (#955,
            decision option (a)): presence is measured WITHIN the current
            experiment window. Manual logs before this date are out-of-window
            (the prior cycle's story lives in /data/cycles/, per the #943
            presentation rule), and a channel with no post-genesis log has been
            quiet since Day 1 at most — never since the previous cycle's stall.
            Day 1 therefore reads "present" (the same 24h lag grace a
            genesis-day log gets) and any gap accrues from genesis, so the
            semantics self-maintain across every future reset. A first log
            after genesis is a fresh start, never a cross-cycle "return".
            None ⇒ unclamped (legacy behaviour).

    Returns a plain dict (the engagement_signal / presence record body). Always
    returns a well-formed record; honest defaults, never raises.
    """
    channel_dates = channel_dates or {}
    sick_days = set(sick_days or ())
    travel_days = set(travel_days or ())

    # #955 genesis clamp — the window never starts before the experiment does.
    # With a genesis, a channel with nothing logged since it gets its gap
    # ANCHORED at genesis (as if the cycle opened present), not None ("dark
    # forever"): pre-genesis silence is the archive's story, not this cycle's.
    genesis = _to_date(experiment_start)
    genesis_gap_cap = _effective_gap(genesis, today) if genesis else None

    # Per-channel gap picture.
    channels = {}
    for src, label in MANUAL_CHANNELS.items():
        dates = sorted(
            {d for d in (channel_dates.get(src) or []) if _to_date(d) and (genesis is None or _to_date(d) >= genesis)},
            reverse=True,
        )
        latest = dates[0] if dates else None
        gap = _effective_gap(latest, today)
        if latest is None and genesis_gap_cap is not None:
            gap = genesis_gap_cap  # quiet since genesis at most — never since the prior cycle
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
    severity = _severity(presence_class, primary_gap, channels, planned=bool(planned_reason))

    # Return detection: a fresh primary log immediately after a real lull.
    # _dates are already genesis-filtered (#955), so a first log after genesis
    # whose previous log is pre-genesis reads as a fresh start, not a "return
    # after N days" — the cross-cycle return beat can never fire.
    returned, resumed_after = _detect_return(primary.get("_dates"), today)

    passive_flowing = _passive_flowing(wearable_latest, today)

    signal = {
        "date": today,
        "presence_class": presence_class,
        "severity": severity,  # #914 ladder: none | soft | loud | alarm
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
        # #955: the genesis clamp in force — makes the stored record
        # self-explaining when gap_days is genesis-anchored while
        # last_food_log_date is still None (nothing logged this cycle yet).
        "experiment_window_start": genesis.isoformat() if genesis else None,
        "channel_detail": {
            src: {
                "label": c["label"],
                "last_log_date": c["last_log_date"],
                "gap_days": c["gap_days"],
                # #914: how long this specific channel has been dropped (same
                # lag-adjusted semantic as gap_days; None = nothing in window).
                "dropout_streak_days": c["gap_days"],
            }
            for src, c in channels.items()
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


def _severity(presence_class, primary_gap, channels, *, planned):
    """The #914 severity ladder — none | soft | loud | alarm. Registry-owned
    thresholds (they live next to the engagement_channel facet definitions):

      quiet                      → soft
      dark (gap ≥ 5)             → loud
      dark ≥ 10d                 → alarm
      ≥ 3 channels quiet ≥ 7d    → alarm (even when food alone looks fresher —
                                   a multi-channel dropout is a stall, not noise)

    A planned pause (sick/travel) de-escalates to none — the classifier already
    holds the class at 'light' for those, and a deliberate break must never trip
    the acknowledgment gate. A channel with nothing in the window (gap None) has
    certainly been quiet ≥ the alarm threshold."""
    if planned:
        return SEVERITY_NONE
    quiet_long = sum(1 for c in channels.values() if c["gap_days"] is None or c["gap_days"] >= ENGAGEMENT_SEVERITY_ALARM_CHANNEL_QUIET_DAYS)
    if presence_class in (QUIET, DARK) and quiet_long >= ENGAGEMENT_SEVERITY_ALARM_QUIET_CHANNELS:
        return SEVERITY_ALARM
    if presence_class == DARK:
        if primary_gap is None or primary_gap >= ENGAGEMENT_SEVERITY_ALARM_DARK_DAYS:
            return SEVERITY_ALARM
        return SEVERITY_LOUD
    if presence_class == QUIET:
        return SEVERITY_SOFT
    return SEVERITY_NONE


def severity_of(signal):
    """The signal's severity, deriving it for records written before the #914
    ladder existed (presence_class/gap_days only). Honest defaults, never raises."""
    signal = signal or {}
    sev = signal.get("severity")
    if sev in (SEVERITY_NONE, SEVERITY_SOFT, SEVERITY_LOUD, SEVERITY_ALARM):
        return sev
    cls = signal.get("presence_class")
    if signal.get("planned_pause"):
        return SEVERITY_NONE
    gap = signal.get("gap_days")
    try:
        gap = int(gap) if gap is not None else None
    except (TypeError, ValueError):
        gap = None
    if cls == DARK:
        return SEVERITY_ALARM if (gap is None or gap >= ENGAGEMENT_SEVERITY_ALARM_DARK_DAYS) else SEVERITY_LOUD
    if cls == QUIET:
        return SEVERITY_SOFT
    return SEVERITY_NONE


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


# ── #914: the ONE shared presence prompt block ───────────────────────────────
# Extracted verbatim from ai_expert_analyzer_lambda._presence_block so every
# narrative surface (expert coaches, integrator, chronicle, podcasts, daily
# brief, State of Matthew) injects the SAME steering text. Pure function — the
# caller passes the engagement_state STATE#current read.


def _num_or_none(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def presence_prompt_block(sig):
    """A steering block for when Matthew's OWN logging has gone quiet (or he just
    returned). Empty string when he's present. This is what stops a narrative
    surface from claiming perfect adherence / an unbroken streak / 'zero missed
    targets' over a window that actually contains a logging gap — the exact
    incoherence the presence feature exists to kill. The REASON for the gap is
    never included (the coach names the silence and invites the story).

    Pure, no I/O: `sig` is the engagement_state STATE#current record the caller
    read (fail-soft {} → ""). At severity=alarm the block ends with the mandate
    that the gap be addressed in the opening paragraph."""
    sig = sig or {}
    if not sig:
        return ""
    cls = sig.get("presence_class")
    returned = bool(sig.get("returned"))
    severity = severity_of(sig)
    if cls not in (LIGHT, QUIET, DARK) and not returned and severity not in ACK_SEVERITIES:
        return ""  # present → nothing to say

    lines = []
    if returned:
        rn = _num_or_none(sig.get("resumed_after_days"))
        lines.append(f"Matthew has JUST RETURNED to logging after ~{rn if rn is not None else 'a few'} days quiet.")
        wd = sig.get("weight_delta_over_gap")
        if wd is not None:
            try:
                lines.append(f"Weight change over the gap: {float(wd):+g} lb (data, not a verdict).")
            except (TypeError, ValueError):
                pass
        lines.append("Acknowledge the return SUPPORTIVELY — never punitive; the goal is to help him restart.")
    else:
        gap = _num_or_none(sig.get("gap_days"))
        last = sig.get("last_food_log_date")
        gap_txt = f"~{gap} days" if gap is not None else "several days"
        lines.append(
            f"Matthew's OWN logging has gone quiet — it has been {gap_txt} since his last food log"
            + (f" (last logged {last})" if last else "")
            + "."
        )
        quiet = sig.get("channels_quiet") or []
        if quiet:
            lines.append(f"Channels gone silent: {', '.join(str(q) for q in quiet)}.")
        if sig.get("passive_still_flowing"):
            lines.append(
                "His WEARABLES are still reporting — the passive data (sleep/recovery/RHR) keeps flowing even though he stopped logging, so you can see the consequences but not the cause."
            )
        if sig.get("planned_pause"):
            lines.append(
                f"This looks like a PLANNED pause ({sig.get('planned_pause_reason') or 'sick/travel'}) — frame it as a break, not falling off."
            )

    guard = (
        "CRITICAL: because of this gap, DO NOT claim perfect adherence, an unbroken streak, "
        "'zero missed targets', or summarize the period as flawless — any window that includes "
        "these days is INCOMPLETE, and celebrating it would be dishonest. Acknowledge the silence "
        "honestly in your own voice, ground the day-count in the number above, do NOT invent WHY he "
        "went quiet (you cannot see it — name the gap and invite the story), and cite only the "
        "authoritative wearable values you were given for any consequences. "
    )
    if severity == SEVERITY_ALARM and not returned:
        guard += (
            "SEVERITY: ALARM. This is the single most important fact about this period. "
            "Address it in the opening paragraph. Do not narrate a normal week."
        )
    else:
        guard += (
            "PLACEMENT: the gap must NOT be your OPENING line unless the quiet channel is your "
            "own domain's primary signal — one coach opening on it is honest; all eight opening on it "
            "reads as one templated voice. Open with your own domain's read, then name the gap where "
            "it genuinely bears on your analysis."
        )
    return "PRESENCE / QUIET STRETCH (Matthew's own logging):\n" + "\n".join(f"- {ln}" for ln in lines) + "\n" + guard


# ── #914: the acknowledgment gate (ADR-108 pattern) ──────────────────────────
# When the gap is loud/alarm, a generated narrative that reads like a normal
# week is dishonest — the deterministic check below verifies the output actually
# references the gap (anchor phrases / the injected day-count; no LLM judge),
# and the enforcement helper regenerates once then HOLDS, exactly like
# ai_calls._enforce_quality_gate. Pure functions — the caller supplies the
# regeneration callable and the STATE#current read.

# Small, deterministic anchor-phrase set: any one of these counts as the output
# acknowledging the gap. Deliberately generic-but-specific — phrases a narrative
# would only use when talking about the logging silence itself.
_ACK_PHRASES = (
    "quiet",
    "silence",
    "silent",
    "gap",
    "went dark",
    "gone dark",
    "stopped logging",
    "hasn't logged",
    "has not logged",
    "no logs",
    "not logging",
    "without a log",
    "logging break",
    "logging lapse",
    "logging stall",
    "stall",
    "off the log",
    "absence",
    "dropped off",
    "fallen off",
    "fell off",
)


def presence_ack_required(sig):
    """True when generated narratives MUST acknowledge the gap (loud/alarm and
    not a planned pause / a fresh return)."""
    sig = sig or {}
    if bool(sig.get("returned")) or bool(sig.get("planned_pause")):
        return False
    return severity_of(sig) in ACK_SEVERITIES


def presence_ack_anchors(sig):
    """The anchor strings whose presence in an output counts as acknowledging
    the gap: the injected gap-day count (both '~N days' and bare 'N-day' forms),
    the last-log date, plus the small fixed phrase set."""
    anchors = []
    gap = _num_or_none((sig or {}).get("gap_days"))
    if gap is not None:
        anchors.extend([f"{gap} days", f"{gap}-day", f"{gap} day"])
    last = (sig or {}).get("last_food_log_date")
    if last:
        anchors.append(str(last))
    anchors.extend(_ACK_PHRASES)
    return anchors


def presence_ack_finding(text, sig):
    """Deterministic post-generation check. None when the output acknowledges the
    gap (or no acknowledgment is required); else a finding dict in the
    grounded_generation shape ({type, detail, ...})."""
    if not presence_ack_required(sig):
        return None
    low = (text or "").lower()
    for anchor in presence_ack_anchors(sig):
        if anchor.lower() in low:
            return None
    gap = _num_or_none((sig or {}).get("gap_days"))
    return {
        "type": "presence_unacknowledged",
        "severity": severity_of(sig),
        "gap_days": gap,
        "detail": (
            f"the narrative never references Matthew's logging gap "
            f"({'~' + str(gap) + ' days' if gap is not None else 'several days'} quiet, severity={severity_of(sig)}) "
            "— it reads as a normal week over an incomplete window"
        ),
    }


def presence_ack_correction(sig):
    """The corrective-rewrite note for a draft that failed the acknowledgment
    check (mirrors grounded_generation.correction_prompt's directness)."""
    gap = _num_or_none((sig or {}).get("gap_days"))
    gap_txt = f"~{gap} days" if gap is not None else "several days"
    note = (
        "ACKNOWLEDGMENT REQUIRED — your draft narrates this period as a normal week, but Matthew's own "
        f"logging has been quiet for {gap_txt}. Rewrite so the narrative honestly references this gap "
        f"(use the real day-count: {gap_txt}). Do NOT invent why he went quiet — name the silence and "
        "invite the story. Keep your voice and length; do not mention that a correction was made."
    )
    if severity_of(sig) == SEVERITY_ALARM:
        note += " SEVERITY: ALARM — this is the single most important fact about this period; " "address it in the opening paragraph."
    return note


def enforce_presence_acknowledgment(text, sig, regenerate_fn, max_regenerations=1):
    """Regenerate-or-hold, exactly the ADR-108 gate shape (see
    ai_calls._enforce_quality_gate): a draft that never acknowledges a loud/alarm
    gap is retried through `regenerate_fn(correction_note)` up to
    `max_regenerations` times; if no attempt acknowledges it, returns
    (None, finding) — the caller's "None = hold, don't publish" contract.

    Fail-open on regeneration INFRA errors is deliberately NOT the behavior for
    the verdict itself: a responding pipeline that keeps producing an
    unacknowledging draft is held. A regenerate_fn exception keeps the prior
    draft's verdict (held), never publishes the failing text.

    Returns (text_or_None, finding_or_None). finding is the ORIGINAL draft's
    finding when the gate fired (even if a regeneration then passed)."""
    finding = presence_ack_finding(text, sig)
    if finding is None:
        return text, None
    attempts = 0
    current = text
    while attempts < max_regenerations:
        attempts += 1
        try:
            regenerated = regenerate_fn(presence_ack_correction(sig))
        except Exception:
            break
        if not (regenerated or "").strip():
            break
        current = regenerated
        if presence_ack_finding(current, sig) is None:
            return current, finding
    return None, finding
