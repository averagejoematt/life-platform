"""compute/watch_hypotheses.py — the three hypotheses the Apple Watch makes testable, pre-registered (#4979).

WHY THIS EXISTS

The Apple Watch Ultra 4 (epic #4967) measures three things no instrument on the platform measured before:
time in daylight, cardio recovery (the heart-rate drop one minute after exercise) and a VO2 max estimate
going forward. Each makes a long-standing question testable. They are registered HERE, in code, before the
data that grades them is read — the #1843 diary seed's shape: fixed ids, idempotent across every status
(a resolved or archived one is never re-created), validated by the engine's own `validate_hypothesis`,
and written through the engine's `store_hypothesis` chokepoint, which freezes the spec and stamps
`pre_registered_at`. The engine's deterministic check reads ONLY data dated after that stamp
(`evaluate_test_spec(spec, daily_rows, since_date=created_at)`), so the decision rule below predates
every observation that decides it.

THE DESIGN (written 2026-10-24, before any check has run)

  1. daylight -> sleep onset: days in the upper half of the watch's time-in-daylight are followed by a
     faster sleep onset (Eight Sleep latency) that night. Lag 1: sleep rows are keyed by the WAKE date.
  2. Zone 2 volume -> cardio recovery: days whose trailing-7-day Zone 2 minutes (THE Zone 2 computation,
     `training.zone2_minutes`, the watch's own zones included as its third source) are in the upper half
     carry a higher cardio recovery. OWNER-CHANNEL ONLY: cardio recovery is TIER_INTERNAL (field_tiers,
     #4970 — "not published"), so this record is stored `public: False` (`/api/hypotheses` filters it)
     and the metric is kept out of the weekly LLM generator's vocabulary and prompt rows.
  3. training volume -> VO2 max: days whose trailing-7-day recorded cardio-session minutes are in the
     upper half carry a higher VO2 max estimate the next day (through the resolver, Apple Watch first).

Every test is the engine's: a median split on the condition, outcome compared at the stated lag, a
bootstrap 95% CI, at least MIN_DAYS_PER_ARM days per arm, the bar below re-derived at the write from the
outcome's own trailing variance when the series supports it (#3495) and labelled a design constant when
it does not. A hypothesis whose arms never fill expires undecided at the engine's 30-day hard limit —
that is an honest answer, not a failure (ADR-104/105). The window each one states is the engine's
monitoring window, 30 days from registration.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Mapping, Optional

from common import metric_truth as mt
from common.strava_read_seam import strava_read_seam
from experiment import experiment_gates
from training import zone2_minutes as z2

#: The day the design below was written — the decision rule is dated before any data is read.
DESIGN_REGISTERED_ON = "2026-10-24"

#: The narrative metrics this module adds (build_data_narrative's vocabulary, SPEC_METRICS).
DAYLIGHT = "daylight_min"
CARDIO_RECOVERY = "cardio_recovery"
VO2 = "vo2max"
ZONE2_7D = "zone2_7d_min"
CARDIO_7D = "cardio_7d_min"
WATCH_METRICS = frozenset({DAYLIGHT, CARDIO_RECOVERY, VO2, ZONE2_7D, CARDIO_7D})
#: Emitted only on a date whose whole trailing week lies inside the fetched data (never on a lone day).
TRAILING_METRICS = frozenset({ZONE2_7D, CARDIO_7D})

#: Metrics no public artifact may carry: kept out of the LLM generator's vocabulary and prompt rows.
OWNER_CHANNEL_METRICS = frozenset({CARDIO_RECOVERY})

logger = logging.getLogger(__name__)

_APPLE = "apple_health"
_TRAILING = 7

WATCH_DESIGN_CITATION = (
    f"#4979's design choice, written {DESIGN_REGISTERED_ON} before the watch data that grades it was read: the "
    "smallest difference that would change a habit — 3 minutes of sleep-onset latency, 2 bpm of cardio recovery, "
    "0.5 ml/kg/min of VO2 max. Replaced at the write by the outcome's own trailing variance when the series allows."
)


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def _day(items: Iterable[Mapping[str, Any]], date: str) -> Mapping[str, Any]:
    """The DAY row for `date` (a #WORKOUT# sub-row never answers for the day)."""
    for i in items or ():
        sk = str(i.get("sk") or "")
        if i.get("date") == date and not (sk.startswith("DATE#") and len(sk) > 15):
            return i
    return {}


def _trailing_volumes(data: Mapping[str, list], dates: list[str]) -> dict[str, dict[str, float]]:
    """{date: {zone2_7d_min, cardio_7d_min}} for every date whose FULL trailing week lies inside the
    fetched window (a partial week is not a 7-day volume, so it stays absent — ADR-104)."""
    if not dates:
        return {}
    # #5369: Hevy anchors a gym visit's parts when the caller fetched it (the hypothesis engine's
    # input manifest does not list hevy today, so the wearables resolve among themselves).
    sessions = z2.counted_sessions(
        strava_read_seam("strava", data.get("strava") or []), data.get("whoop") or [], data.get(_APPLE) or [], hevy_rows=data.get("hevy")
    )
    first = dates[0]
    out: dict[str, dict[str, float]] = {}
    for d in dates:
        start, end = z2.trailing_window(d, _TRAILING)
        if start < first:
            continue
        week = [s for s in sessions if start <= s["date"] <= end]
        out[d] = {
            ZONE2_7D: round(sum(s["zone_2_minutes"] or 0.0 for s in week if s["source"]), 1),
            CARDIO_7D: round(sum(s["duration_minutes"] for s in week), 1),
        }
    return out


def add_watch_metrics(rows: list[dict], data: Mapping[str, list]) -> list[dict]:
    """Add the watch-enabled metrics to `build_data_narrative`'s day rows, in place (absent stays absent)."""
    volumes = _trailing_volumes(data, [r["date"] for r in rows])
    for row in rows:
        d = row["date"]
        ah = _day(data.get(_APPLE) or [], d)
        vo2 = mt.resolve(mt.VO2_MAX, {_APPLE: ah or None, "garmin": _day(data.get("garmin") or [], d) or None})
        found = {
            DAYLIGHT: _num(ah.get("daylight_minutes_apple")),
            CARDIO_RECOVERY: _num(ah.get("cardio_recovery_bpm_apple")),
            VO2: vo2.value,
            **volumes.get(d, {}),
        }
        row.update({k: v for k, v in found.items() if v is not None})
    return rows


def generation_rows(rows: list[dict]) -> list[dict]:
    """The day rows the weekly LLM generator may see: owner-channel metrics removed (its hypotheses are public)."""
    return [{k: v for k, v in r.items() if k not in OWNER_CHANNEL_METRICS} for r in rows]


def _hyp(hid: str, text: str, domains: list[str], criteria: str, spec: dict, actionable: str, *, public: bool = True) -> dict:
    return {
        "hypothesis_id": hid,
        "hypothesis": text,
        "domains": domains,
        "evidence": (
            f"Pre-registered by design (#4979, written {DESIGN_REGISTERED_ON}), not mined from an observed pattern: the Apple "
            "Watch is the first instrument on the platform that measures this, so nothing has been seen yet. The test reads "
            "only data dated after this record's pre-registration stamp."
        ),
        "confirmation_criteria": criteria,
        "decision_rule": (
            "Confirmed when the deterministic test's 95% CI for the condition-minus-comparison difference excludes 0 in the "
            "stated direction and the difference reaches min_effect, with at least the per-arm floor of days in each arm; "
            "refuted when the CI excludes 0 the other way; otherwise undecided at the monitoring window's end."
        ),
        "design_registered_on": DESIGN_REGISTERED_ON,
        "test_spec": spec,
        "monitoring_window_days": 30,
        "confidence": "low",
        "confidence_reason": "Pre-registered, not data-mined — no observation backs a higher confidence, and nothing is randomised.",
        "actionable_if_confirmed": actionable,
        "correlative_only": True,
        "public": public,
        "source": "watch_prereg_4979",
    }


WATCH_HYPOTHESES: tuple[dict, ...] = (
    _hyp(
        "hyp_watch_daylight_sleep_onset",
        "Days with more time in daylight (Apple Watch) are followed by a faster sleep onset that night.",
        ["environment", "sleep"],
        "Sleep-onset latency is at least 3 minutes shorter on nights following upper-half daylight days than after "
        "lower-half days over the 30-day monitoring window, with the deterministic test's 95% CI excluding 0.",
        {
            "condition_metric": DAYLIGHT,
            "condition_op": "median_split",
            "outcome_metric": "sleep_onset_min",
            "direction": "lower",
            "min_effect": 3,
            "lag_days": 1,
        },
        "If confirmed, a daylight walk earlier in the day is a cheap lever on falling asleep.",
    ),
    _hyp(
        "hyp_watch_zone2_cardio_recovery",
        "Weeks with more Zone 2 minutes carry a higher cardio recovery (Apple Watch).",
        ["training", "recovery"],
        "Cardio recovery is at least 2 bpm higher on days whose trailing-7-day Zone 2 volume is in the upper half than on "
        "lower-half days over the 30-day monitoring window, with the deterministic test's 95% CI excluding 0.",
        {
            "condition_metric": ZONE2_7D,
            "condition_op": "median_split",
            "outcome_metric": CARDIO_RECOVERY,
            "direction": "higher",
            "min_effect": 2,
            "lag_days": 0,
        },
        "If confirmed, Zone 2 volume is moving the heart's recovery and the weekly Zone 2 target earns its place.",
        public=False,
    ),
    _hyp(
        "hyp_watch_training_vo2max",
        "Weeks with more recorded cardio-session minutes carry a higher VO2 max estimate.",
        ["training", "fitness"],
        "The VO2 max estimate is at least 0.5 ml/kg/min higher the day after an upper-half trailing-7-day cardio volume than "
        "after a lower-half week over the 30-day monitoring window, with the deterministic test's 95% CI excluding 0.",
        {
            "condition_metric": CARDIO_7D,
            "condition_op": "median_split",
            "outcome_metric": VO2,
            "direction": "higher",
            "min_effect": 0.5,
            "lag_days": 1,
        },
        "If confirmed, the cardio volume is registering in the watch's fitness estimate within weeks, not months.",
    ),
)


def seed_watch_hypotheses(
    all_hypotheses: Iterable[Mapping[str, Any]],
    daily_rows: list,
    validate: Callable[..., tuple],
    store: Callable[..., None],
    kind: str = experiment_gates.POPULATION_CONSTANT,
) -> dict[str, Any]:
    """Register each WATCH_HYPOTHESES id once (any existing status blocks it), through the engine's own
    validator and store. Never fatal: a failure is reported per id and the run continues."""
    seen = {h.get("hypothesis_id") for h in all_hypotheses}
    out: dict[str, Any] = {"registered": [], "skipped": {}}
    for hyp in WATCH_HYPOTHESES:
        hid = hyp["hypothesis_id"]
        if hid in seen:
            out["skipped"][hid] = "already_registered"
            continue
        try:
            ok, issues = validate(dict(hyp), existing_texts=None)
            if not ok:
                out["skipped"][hid] = f"validation_failed: {issues}"
                continue
            store(dict(hyp), daily_rows, kind=kind, citation=WATCH_DESIGN_CITATION)
            out["registered"].append(hid)
        except Exception as e:  # noqa: BLE001 — one seed never blocks the weekly run
            out["skipped"][hid] = f"error: {type(e).__name__}"
            logger.warning(f"[#4979] seeding {hid} failed (non-fatal): {e}")
    return out
