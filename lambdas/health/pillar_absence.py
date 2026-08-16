"""pillar_absence.py — the pillar → "is this pillar's own source dark?" derivation (#2388).

WHY THIS EXISTS
---------------
ADR-104's behavioral-absence semantics say an unlogged habit scores 0 at full weight, and
the character engine already publishes the honest signal alongside the score
(`absent_behaviors`, `coverage_hold`, `data_coverage`). That is NOT the defect #2388 is
about and this module deliberately does not touch it.

The defect was one layer up: the READER surfaces translated a 0-because-nothing-was-logged
into a trend verb. Over a cycle with zero food logs and MacroFactor quiet 45+ days, the
family panel on `/` said "EATING eased off a little" and the cockpit's pillar detail said
"Nutrition is at 1 and slipping" — a mild-decline claim about a behavior that produced no
data at all. A family reader was told "he's eating slightly less well" when the true
sentence is "nothing is logged".

A trend verb is only licensed when the pillar's own SOURCE was reporting. That is a fact
about the ingestion registry (`stale_hours` per source), not about the score — so it has to
be derived where the registry lives (server-side) and handed to the front end as a state,
never re-derived in JS off a hardcoded window that would drift from the registry.

WHAT IT ANSWERS, AND WHAT IT REFUSES TO
---------------------------------------
`pillar_absence()` returns one of three states:

  * ``dark``    — every source that feeds this pillar is past its OWN registry
                  `stale_hours` window. The reader surface must render the nothing-logged
                  state; a trend verb here is a fabricated claim.
  * ``logged``  — at least one feeding source is inside its window. Normal trend copy.
  * ``unknown`` — the caller could not observe some feeding source. Unknown is never
                  narrated as absence (the #2056 semantics `behavior_logs` established:
                  absence of evidence is not evidence of absence), so the surface keeps
                  its existing behavior rather than inventing a darkness it cannot see.

`dark` requires EVERY mapped source to be known-and-stale. One unobservable source demotes
the whole pillar to `unknown` rather than letting a partial read publish a confident
absence — the conservative direction, because "nothing logged" is itself a claim.

For the three pillars whose behavior maps onto a `behavior_logs.LOG_CATEGORIES` token, the
result also carries the #2382 transition kind, so a surface can tell "he logged and then
stopped 12 days ago" (``paused``) apart from "nothing was ever logged in this cycle"
(``never_logged``). A last log date that predates the experiment window is handed to the
derivation as ``None`` — that is exactly the never-logged-in-this-window answer, and it is
what structurally prevents the MacroFactor case from ever reading as "eased off".

Pure: zero I/O. The caller owns every lookup (see `web/site_api_character.py`).
"""

from typing import Any, Iterable, Mapping, Optional

from ai.behavior_logs import LogAvailability, absence_transition

# Pillar → the registry sources whose writes are the pillar's behavioral evidence.
#
# Only the MANUAL-LOG pillars are mapped, and that scope is the point. `sleep` and
# `metabolic` are wearable-backed: a Whoop night lands without Matthew doing anything, so
# a dark wearable is a broken pipe (already disclosed by /api/source_freshness), not a
# behavioral absence, and the trend on those pillars stays honest. `relationships` has no
# single feeding source. An unmapped pillar returns None here and every surface keeps its
# existing behavior — this module adds a state, it never removes one.
PILLAR_SOURCES: dict[str, tuple[str, ...]] = {
    "nutrition": ("macrofactor",),
    "movement": ("hevy", "strava"),
    "mind": ("notion",),
    "consistency": ("todoist", "habitify"),
}

# Pillar → the `behavior_logs.LOG_CATEGORIES` token, where one exists. `consistency` has
# no category (habit ticks are not one of the six the gate's claim patterns speak), so it
# gets the dark/logged state without a transition kind rather than a guessed one.
PILLAR_LOG_CATEGORY: dict[str, str] = {
    "nutrition": "nutrition",
    "movement": "workout",
    "mind": "journal",
}

STATE_DARK = "dark"
STATE_LOGGED = "logged"
STATE_UNKNOWN = "unknown"


def _iso_day(value: Any) -> Optional[str]:
    s = str(value or "")[:10]
    return s if len(s) == 10 and s[4] == "-" and s[7] == "-" else None


def pillar_absence(
    pillar: str,
    *,
    source_state: Mapping[str, Mapping[str, Any]],
    absent_behaviors: Iterable[Any] = (),
    reference_date: Any = None,
    window_start: Any = None,
) -> Optional[dict]:
    """Derive the absence state for one pillar. Pure, total, never raises.

    ``source_state`` maps a registry source id to what the caller observed:
    ``{"last_date": "YYYY-MM-DD"|None, "age_hours": float|None, "stale_hours": int}``.
    A source missing from the map, or carrying ``age_hours: None``, is UNOBSERVED.

    Returns None for a pillar with no source mapping (the caller omits the key).
    """
    name = str(pillar or "").strip().lower()
    sources = PILLAR_SOURCES.get(name)
    if not sources:
        return None

    dark_ages: list[float] = []
    stale_windows: list[int] = []
    dark_sources: list[str] = []
    any_fresh = False
    any_unobserved = False
    last_seen: Optional[str] = None

    for sid in sources:
        obs = source_state.get(sid) if isinstance(source_state, Mapping) else None
        obs = obs if isinstance(obs, Mapping) else {}
        age = obs.get("age_hours")
        window = obs.get("stale_hours")
        d = _iso_day(obs.get("last_date"))
        if d and (last_seen is None or d > last_seen):
            last_seen = d
        try:
            age_f = float(age) if age is not None else None
            window_f = float(window) if window is not None else None
        except (TypeError, ValueError):
            age_f, window_f = None, None
        if age_f is None or window_f is None:
            # `no_records` is the caller saying "I looked and this source has written
            # nothing at all". That is dark — and it carries NO day-count, because there
            # is no last log to count from (the #2382 rule: a never-logged channel never
            # gets a number attached to its absence).
            if obs.get("no_records") is True and d is None:
                dark_sources.append(sid)
                if window_f is not None:
                    stale_windows.append(int(window_f))
            else:
                any_unobserved = True
            continue
        if age_f > window_f:
            dark_ages.append(age_f)
            stale_windows.append(int(window_f))
            dark_sources.append(sid)
        else:
            any_fresh = True

    if any_fresh:
        state = STATE_LOGGED
    elif any_unobserved or not dark_sources:
        state = STATE_UNKNOWN
    else:
        state = STATE_DARK

    # The transition kind, for the pillars whose behavior has a log category. A last log
    # that predates the experiment window is None to the derivation — "nothing anywhere in
    # this window" — which is the never_logged answer, not a 45-day pause event.
    transition_kind: Optional[str] = None
    days_since_last_log: Optional[int] = None
    category = PILLAR_LOG_CATEGORY.get(name)
    ref = _iso_day(reference_date)
    win = _iso_day(window_start)
    if category and (last_seen is not None or state == STATE_DARK):
        in_window = last_seen if (last_seen and (win is None or last_seen >= win)) else None
        avail = LogAvailability(frozenset(), frozenset(), frozenset({(category, in_window)}))
        tr = absence_transition(avail, category, ref, win)
        transition_kind = tr.kind
        days_since_last_log = tr.days_since_last_log

    out: dict[str, Any] = {
        "state": state,
        "sources": list(sources),
        "dark_sources": dark_sources,
        "last_log_date": last_seen,
        "days_dark": int(min(dark_ages) // 24) if dark_ages else None,
        "stale_hours": min(stale_windows) if stale_windows else None,
        "transition": transition_kind,
        "days_since_last_log": days_since_last_log,
        "absent_behaviors": [str(b) for b in (absent_behaviors or [])],
    }
    return out


def nutrition_absence_facts(latest_row, days_in_experiment: int, experiment_start: str, today=None) -> dict:
    """#2756: the TRUE absence facts for an empty nutrition window.

    An empty 30-day fact-pack window used to hand the model `None` and the model
    filled the vacuum ("blank for four days" while the platform's own derivation
    said 52). This builder turns the partition's newest row — regardless of
    window — into explicit absence facts the prompt can carry and the
    `absence_span` grounding class (grounded_generation, #2756) can police.

    `latest_row` is the newest macrofactor item anywhere in the record (or None);
    pure, zero I/O — the caller owns the lookup, same contract as pillar_absence().
    """
    from datetime import date, datetime

    today = today or date.today()
    sk = str((latest_row or {}).get("sk", ""))
    last_date = sk[len("DATE#") :][:10] if sk.startswith("DATE#") else None
    days_dark = None
    if last_date:
        try:
            days_dark = (today - datetime.strptime(last_date, "%Y-%m-%d").date()).days
        except ValueError:
            last_date = None
    if last_date and last_date < experiment_start:
        absence = (
            f"NO food log has landed in THIS cycle (Day {days_in_experiment}). The last food log anywhere "
            f"in the record is {last_date} — {days_dark} days dark. State the span honestly or not at all; "
            f"never guess a smaller number."
        )
        transition = "never_logged_this_cycle"
    elif last_date:
        absence = f"Last food log {last_date} — {days_dark} days dark. State the span honestly or not at all."
        transition = "paused"
    else:
        absence = "No food log exists anywhere in the record."
        transition = "never_logged"
    return {
        "note_absence": absence,
        "absence_days_dark": days_dark,
        "absence_last_log_date": last_date,
        "absence_transition": transition,
    }


def absence_gate_map(data) -> dict | None:
    """#2756: the measured dark-span map for the absence_span grounding class —
    None when the window had data (the gate arms only when absence is the story)."""
    d = (data or {}).get("absence_days_dark")
    return {"food": int(d)} if d is not None else None
