"""mcp/ritual_triggers.py — checkpoint triggers: the platform proposes the ritual (#1578).

Real teams call a meeting when something happens. This module gives the platform the
same reflex: a catalog of DETERMINISTIC checkpoint conditions computed from existing
data that PROPOSE a diary/interview ritual (a `suggested_rituals` entry surfaced by
`get_capture_queues`). A proposal is never a push and never a nag — it is one line at
the top of a session that Matthew acts on or skips. Skipping records nothing.

Design rules (the acceptance criteria, load-bearing):

  1. DETERMINISTIC (ADR-105). Every trigger is pure code over already-stored data —
     no LLM judgment decides whether a condition fired. Where a threshold is not a
     natural round number it derives from Matthew's OWN distribution (percentile bands,
     ADR-105 rule 4), never a hand-set population cutoff. Round-number milestones
     (5-lb weight bands, cycle-day anniversaries) are legitimate goal anchors and are
     labeled as such — the ADR-105 "or document why not" carve-out.

  2. HONEST ABSENCE (ADR-104). A dark source proposes nothing. Every trigger reads
     inside its own try/except (via the orchestrator); a read failure or a too-thin
     series is a silent no-fire, never a fabricated or population-defaulted suggestion.

  3. ONCE PER CONDITION-EPISODE. This surface is READ-ONLY (it never writes a "shown"
     ledger — a skip must record nothing, AC #3). Once-per-episode is therefore a
     property of the trigger's shape, delivered two ways: EDGE triggers only evaluate
     true on the transition day (a cycle anniversary is one calendar day; a readiness
     cliff is the day recovery first drops below the personal floor), and WINDOW
     triggers carry a stable `episode_key` tied to the episode's start (the dark-since
     date, the first day of a mood slide, the crossed weight band) so a consumer
     dedups on the key across the days the condition persists. Same episode -> same
     key, every session.

Each suggestion is `{ritual, rule, episode_key, fired_by[, coach]}`:
  - ritual      : the slash-command the platform proposes (Diary Studio epic #1564).
  - rule        : the plain-language deterministic condition, so the proposal explains
                  itself without an LLM.
  - episode_key : the dedup identity for this condition-episode.
  - fired_by    : the exact data that fired it (ADR-105: the rule AND its evidence).
  - coach       : optional coach specialty the ritual should route to.

Pure orchestration lives in `build_suggested_rituals`; the section wiring is in
`tools_capture._suggested_rituals_section`. The DDB reads are isolated in the
`_*_series` / `_active_experiments` helpers so tests monkeypatch them at the module
level and stay hermetic.
"""

import math
from datetime import date, timedelta

from mcp.config import logger
from mcp.core import query_source

try:
    # Bundled shared modules (#781) — staged at the zip root in the Lambda.
    import constants as _const
    import personal_baselines as _pb
except ImportError:  # pragma: no cover — the MCP bundle always ships lambdas/ at root
    from lambdas import constants as _const, personal_baselines as _pb

# ── Trigger thresholds ───────────────────────────────────────────────────────
# Journaling sources whose darkness proposes a spoken/written interview. A source
# ABSENT from the freshness read (never connected) proposes nothing — ADR-104.
_JOURNAL_SOURCES = {"notion", "journal", "diary"}
_JOURNAL_DARK_DAYS = 7  # the story's stated cadence floor

# Weight: round 5-lb bands are goal anchors, not a variance threshold (ADR-105 carve-out).
_WEIGHT_STEP_LBS = 5
_WEIGHT_LOOKBACK_DAYS = 45

# Mood: the slide LENGTH is a fixed 3 days (the story), but "low enough to matter" is
# personal — the current valence must sit in Matthew's OWN bottom quartile (ADR-105).
# The valence scale itself is device-dependent (How We Feel exports vary -1..1 / -3..3 /
# 1..7), which is exactly why an absolute cutoff is unsafe and a personal percentile is
# the only honest threshold here.
_MOOD_WINDOW_DAYS = 90
_MOOD_SLIDE_DAYS = 3
_MOOD_SLIDE_PERSONAL_PCTL = 25

# Readiness: a "cliff" is a drop below Matthew's own p10 recovery (ADR-105 rule 4's
# worked example — "a 40-point floor means nothing if his p10 is 55"). Needs enough of
# his own history for the band to mean anything; below the floor it proposes nothing.
_RECOVERY_WINDOW_DAYS = 90
_RECOVERY_CLIFF_PCTL = 10
_RECOVERY_MIN_N = 14

# Cycle: genesis, each weekly anniversary, and the named day milestones.
_CYCLE_DAY_MILESTONES = (30, 60, 90, 180, 270, 365)


def _suggestion(ritual, rule, episode_key, fired_by, coach=None):
    s = {"ritual": ritual, "rule": rule, "episode_key": episode_key, "fired_by": fired_by}
    if coach:
        s["coach"] = coach
    return s


# ── DDB read helpers (monkeypatched in tests; each returns a chronological series) ──
def _series(source, field, today, days):
    """[(date, float(field)), ...] chronological, dropping None/unparseable/undated rows."""
    start = (today - timedelta(days=days)).isoformat()
    out = []
    for r in query_source(source, start, today.isoformat()):
        v, d = r.get(field), r.get("date")
        if v is None or not d:
            continue
        try:
            out.append((d, float(v)))
        except (TypeError, ValueError):
            continue
    out.sort()
    return out


def _weight_series(today):
    return _series("withings", "weight_lbs", today, _WEIGHT_LOOKBACK_DAYS)


def _valence_series(today):
    return _series("apple_health", "som_avg_valence", today, _MOOD_WINDOW_DAYS)


def _recovery_series(today):
    return _series("whoop", "recovery_score", today, _RECOVERY_WINDOW_DAYS)


def _active_experiments():
    from mcp.tools_lifestyle import tool_list_experiments

    return tool_list_experiments({"status": "active"}).get("experiments") or []


# ── Triggers (each returns a list of suggestions; [] = nothing fired) ─────────
def _cycle_milestone(today, _freshness):
    """Cycle anniversary → /interview. Edge trigger: true on exactly one calendar day."""
    start = date.fromisoformat(_const.EXPERIMENT_START_DATE)
    day_n = (today - start).days + 1
    if day_n < 1:  # pre-genesis countdown — nothing to reflect on yet (ADR-104)
        return []

    kind = None
    if day_n == 1:
        kind = "genesis"
    elif day_n in _CYCLE_DAY_MILESTONES:
        kind = f"day-{day_n}"
    elif (day_n - 1) % 7 == 0:
        kind = f"week-{(day_n - 1) // 7 + 1}"
    if not kind:
        return []

    return [
        _suggestion(
            ritual="/interview",
            rule=f"cycle checkpoint: today is a milestone day of the current cycle ({kind})",
            episode_key=f"cycle:{_const.EXPERIMENT_START_DATE}:day{day_n}",
            fired_by={"cycle_start": _const.EXPERIMENT_START_DATE, "day_n": day_n, "milestone": kind},
        )
    ]


def _journal_dark(today, freshness):
    """Journaling source dark >= 7d → /journal-interview. Window trigger keyed by the
    dark-since date so it fires once per dark episode. A journaling source that is not
    in the freshness read (never connected) proposes nothing — ADR-104."""
    if not isinstance(freshness, dict):
        return []
    out = []
    for flag in freshness.get("flags", []) or []:
        src = flag.get("source")
        days_dark = flag.get("days_dark")
        if src not in _JOURNAL_SOURCES or days_dark is None or days_dark < _JOURNAL_DARK_DAYS:
            continue
        dark_since = (today - timedelta(days=int(days_dark))).isoformat()
        out.append(
            _suggestion(
                ritual="/journal-interview",
                rule=f"journal dark >= {_JOURNAL_DARK_DAYS}d: '{src}' has no entry in {days_dark} days",
                episode_key=f"journal_dark:{src}:{dark_since}",
                fired_by={"source": src, "label": flag.get("label"), "days_dark": days_dark, "dark_since": dark_since},
            )
        )
    return out


def _weight_milestone(today, _freshness):
    """Latest weigh-in crossed a 5-lb band (downward) the prior weigh-in had not →
    /interview. Keyed by the deepest band crossed so it fires once per band."""
    series = _weight_series(today)
    if len(series) < 2:
        return []
    (prev_date, prev), (last_date, last) = series[-2], series[-1]
    if not last < prev:  # only celebrate a downward crossing
        return []
    lowest_mult = int(math.ceil((last + 1e-9) / _WEIGHT_STEP_LBS)) * _WEIGHT_STEP_LBS
    crossed = [m for m in range(lowest_mult, int(math.floor(prev)) + 1, _WEIGHT_STEP_LBS) if last < m <= prev]
    if not crossed:
        return []
    band = min(crossed)  # the deepest milestone reached
    return [
        _suggestion(
            ritual="/interview",
            rule=f"weight milestone: dropped below {band} lb ({prev} -> {last})",
            episode_key=f"weight_milestone:{band}",
            fired_by={
                "band_lbs": band,
                "all_bands_crossed": crossed,
                "latest_lbs": last,
                "latest_date": last_date,
                "previous_lbs": prev,
                "previous_date": prev_date,
            },
        )
    ]


def _mood_slide(today, _freshness):
    """>= 3 consecutive declining valence days AND current valence in Matthew's own
    bottom quartile → /speak-to-coaches (mind). Keyed by the slide's start date."""
    series = _valence_series(today)
    if len(series) < _MOOD_SLIDE_DAYS:
        return []
    # Maximal strictly-declining run ending at the latest reading.
    run = [series[-1]]
    i = len(series) - 2
    while i >= 0 and series[i][1] > series[i + 1][1]:
        run.insert(0, series[i])
        i -= 1
    if len(run) < _MOOD_SLIDE_DAYS:
        return []
    p25 = _pb.percentile([v for _, v in series], _MOOD_SLIDE_PERSONAL_PCTL)
    current = run[-1][1]
    if p25 is None or current >= p25:
        return []
    return [
        _suggestion(
            ritual="/speak-to-coaches",
            rule=(
                f"mood slide: {len(run)} consecutive declining check-in days and current valence "
                f"below personal p{_MOOD_SLIDE_PERSONAL_PCTL}"
            ),
            episode_key=f"mood_slide:{run[0][0]}",
            fired_by={
                "run_days": len(run),
                "dates": [d for d, _ in run],
                "valences": [v for _, v in run],
                "current_valence": current,
                "personal_p25": round(p25, 4),
                "n": len(series),
            },
            coach="mind",
        )
    ]


def _readiness_cliff(today, _freshness):
    """Recovery drops below Matthew's own p10 (from at-or-above) → /speak-to-coaches
    (mind). Edge trigger: fires only on the transition day. Needs enough personal
    history for the band to mean anything; below the floor it proposes nothing."""
    series = _recovery_series(today)
    if len(series) < _RECOVERY_MIN_N:
        return []
    p10 = _pb.percentile([v for _, v in series], _RECOVERY_CLIFF_PCTL)
    if p10 is None:
        return []
    last_date, last = series[-1]
    prev = series[-2][1] if len(series) >= 2 else None
    if not (last < p10 and (prev is None or prev >= p10)):
        return []
    return [
        _suggestion(
            ritual="/speak-to-coaches",
            rule=f"readiness cliff: recovery {last} dropped below personal p{_RECOVERY_CLIFF_PCTL}",
            episode_key=f"readiness_cliff:{last_date}",
            fired_by={"current_recovery": last, "personal_p10": round(p10, 2), "n": len(series), "date": last_date},
            coach="mind",
        )
    ]


def _experiment_midpoint(today, _freshness):
    """An active experiment reaches its planned midpoint → /vlog debrief. Edge trigger:
    the exact midpoint calendar day. Experiments with no planned end propose nothing."""
    out = []
    for exp in _active_experiments():
        start_s, end_s = exp.get("start_date"), exp.get("end_date")
        if not start_s or not end_s:
            continue
        try:
            start_d, end_d = date.fromisoformat(start_s), date.fromisoformat(end_s)
        except (TypeError, ValueError):
            continue
        span = (end_d - start_d).days
        if span < 2:
            continue
        midpoint = start_d + timedelta(days=span // 2)
        if today != midpoint:
            continue
        out.append(
            _suggestion(
                ritual="/vlog",
                rule=f"experiment midpoint: '{exp.get('name')}' reached day {span // 2} of {span}",
                episode_key=f"experiment_midpoint:{exp.get('experiment_id')}",
                fired_by={
                    "experiment_id": exp.get("experiment_id"),
                    "name": exp.get("name"),
                    "start_date": start_s,
                    "end_date": end_s,
                    "midpoint": midpoint.isoformat(),
                },
            )
        )
    return out


_TRIGGERS = (
    ("cycle_milestone", _cycle_milestone),
    ("journal_dark", _journal_dark),
    ("weight_milestone", _weight_milestone),
    ("mood_slide", _mood_slide),
    ("readiness_cliff", _readiness_cliff),
    ("experiment_midpoint", _experiment_midpoint),
)


def build_suggested_rituals(today, freshness):
    """Evaluate every deterministic checkpoint trigger and return the proposed rituals.

    `today` is a `datetime.date` (the Pacific calendar day). `freshness` is the
    `freshness_flags` section result (reused, so the freshness read happens once) or
    None when it was unavailable. Each trigger runs in isolation — one broken or
    thin-data trigger is a silent no-fire (ADR-104), never a failed section.
    """
    suggestions = []
    for name, fn in _TRIGGERS:
        try:
            suggestions.extend(fn(today, freshness) or [])
        except Exception as e:  # noqa: BLE001 — honest-absence: a broken trigger proposes nothing
            logger.warning(f"[#1578] ritual trigger '{name}' failed: {e}")
    return {
        "count": len(suggestions),
        "suggestions": suggestions,
        "how_to_use": (
            "Deterministic checkpoint proposals — the platform noticing a moment worth a diary/interview "
            "ritual (a cycle milestone, a weight band crossed, a journal gone dark, a mood slide, a readiness "
            "cliff, an experiment midpoint). Every one is optional and skip-without-penalty: acting is a ritual, "
            "skipping records nothing. Dedup on episode_key — the same condition-episode carries the same key "
            "across sessions, so a proposal is shown once per episode, never nagged."
        ),
    }
