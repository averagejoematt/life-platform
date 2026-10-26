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

#: #5388 (ADR-105 box 3) — THE DATED CUT-OVER. The VO2 max hypothesis (registered 2026-10-24) is graded on
#: `cardio_7d_min`, and the Zone 2 / cardio-recovery one on `zone2_7d_min`. Until this date both were resolved
#: WITHOUT the Hevy rows, so Hevy's own Strava push stood for a whole gym visit and the watch's ride and the
#: pliability mobility block inside it were counted again as their own parts (a 160-minute visit read 240).
#: From this Pacific day the trailing week is resolved WITH Hevy and counts the visit once. It is a CONSTANT, not
#: a clock read: a re-run recomputes every date under the definition that date belongs to, whenever the engine runs.
#: Deploy date of #5388 (set to the first full Pacific day after the merge; moving it later is a new amendment).
HEVY_CUTOVER_DATE = "2026-10-27"

#: Written onto each open watch hypothesis whose CONDITION metric is affected (`series_amendments`, beside the
#: frozen `test_spec`, which is never touched), so a grader reading the record sees the series changed definition.
SERIES_AMENDMENTS: tuple[dict[str, Any], ...] = (
    {
        "amendment_id": "hevy_input_5388",
        "effective_from": HEVY_CUTOVER_DATE,
        "metrics": [CARDIO_7D, ZONE2_7D],
        "issue": "#5388",
        "change": (
            "Trailing 7-day volumes are resolved WITH the Hevy routine rows from this date (a gym visit's lift, cycling block "
            "and mobility block count once); before it they were resolved without them, which double-counted the visit's "
            "parts. The series changed definition on this day: a grader must not read the days either side as one series. "
            "The registered test_spec is unchanged."
        ),
    },
)

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
    fetched window (a partial week is not a 7-day volume, so it stays absent — ADR-104).

    #5388 — the series changed definition on HEVY_CUTOVER_DATE. From that date the week is resolved WITH the
    Hevy rows (the routine source: a gym visit's lift, cycling block and mobility block count once); before it,
    as registered, without them. The choice is per output DATE and applies to that date's whole trailing week,
    so a single value is never a mixture of the two definitions."""
    if not dates:
        return {}
    strava = strava_read_seam("strava", data.get("strava") or [])
    whoop, apple, hevy = data.get("whoop") or [], data.get(_APPLE) or [], data.get("hevy")
    as_registered = z2.counted_sessions(strava, whoop, apple)
    # #5369: Hevy anchors a gym visit's parts (the engine's input manifest lists hevy since #5388).
    with_hevy = z2.counted_sessions(strava, whoop, apple, hevy_rows=hevy) if hevy else as_registered
    first = dates[0]
    out: dict[str, dict[str, float]] = {}
    for d in dates:
        start, end = z2.trailing_window(d, _TRAILING)
        if start < first:
            continue
        sessions = with_hevy if d >= HEVY_CUTOVER_DATE else as_registered
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
    table: Any = None,
) -> dict[str, Any]:
    """Register each WATCH_HYPOTHESES id once (any existing status blocks it), through the engine's own
    validator and store. Never fatal: a failure is reported per id and the run continues. With `table`
    (#5388) the open records are also stamped with SERIES_AMENDMENTS."""
    all_hypotheses = list(all_hypotheses)
    seen = {h.get("hypothesis_id") for h in all_hypotheses}
    out: dict[str, Any] = {"registered": [], "skipped": {}, "amended": []}
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
    if table is not None:
        out["amended"] = amend_open_watch_hypotheses(all_hypotheses, table)
    return out


#: Statuses in which a watch record is still being graded (a resolved one was graded under its own definition).
_OPEN = frozenset({"pending", "confirming"})


def amend_open_watch_hypotheses(all_hypotheses: Iterable[Mapping[str, Any]], table: Any) -> list[str]:
    """#5388: append each SERIES_AMENDMENT to every OPEN watch record whose condition metric it names and that
    does not carry it yet (idempotent by `amendment_id`). Only `series_amendments` is written; the frozen
    `test_spec` and `pre_registered_at` are never touched. Never fatal. Returns "hypothesis_id:amendment_id"."""
    done: list[str] = []
    for h in all_hypotheses:
        if h.get("source") != "watch_prereg_4979" or h.get("status") not in _OPEN or not (h.get("pk") and h.get("sk")):
            continue
        metric = (h.get("test_spec") or {}).get("condition_metric")
        have = {a.get("amendment_id") for a in h.get("series_amendments") or [] if isinstance(a, Mapping)}
        todo = [a for a in SERIES_AMENDMENTS if metric in a["metrics"] and a["amendment_id"] not in have]
        if not todo:
            continue
        try:
            table.update_item(
                Key={"pk": h["pk"], "sk": h["sk"]},
                UpdateExpression="SET series_amendments = list_append(if_not_exists(series_amendments, :empty), :new)",
                ExpressionAttributeValues={":empty": [], ":new": [dict(a) for a in todo]},
            )
            done.extend(f"{h.get('hypothesis_id')}:{a['amendment_id']}" for a in todo)
        except Exception as e:  # noqa: BLE001 — an amendment never blocks the weekly run
            logger.warning(f"[#5388] amending {h.get('hypothesis_id')} failed (non-fatal): {e}")
    return done
