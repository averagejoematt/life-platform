"""brief_domain_inputs.py — the daily brief's inputs for two coach domain blocks (#4358/#4359).

Both defects were one shape: an ``ai_context._build_*_data`` builder read keys the brief's
``data`` dict never carried, so the builder returned a structurally empty block every day
and the coach wrote his public daily read without saying so.

* **#4358 — the Performance coach (``physical_coach``)** read ``withings``/``dexa``/
  ``measurements`` only. The brief fetched Hevy for YESTERDAY into ``mf_workouts`` (the
  html report's shape) and Strava into ``strava_7d``, and neither reached his builder —
  while the Telegram chat pack (``coach.coach_domain_facts._physical_pack``) read Hevy over
  14 days. The seat has owned training since the 2026-08-10 merge; it was judging sessions
  it could not see.
* **#4359 — the explorer coach** read ``weekly_correlations``, ``active_experiments`` and
  ``experiment_names``; the brief set none of them, so he was told "0 correlations, 0
  experiments" daily — a false ZERO, not an absence.

The brief side is :func:`gather` (one spread line in ``gather_daily_data``); the builder
side is :func:`training_block` / :func:`explorer_block`. They live together because they
are the two ends of one seam: the keys :func:`gather` sets are exactly the keys the two
block builders read, and ``tests/test_daily_brief_behavior.py`` drives the pair from the
real ``gather_daily_data`` against a FakeTable seeded with live-copied row shapes.

ABSENCE (ADR-104) is structural here, never narrative-only: a partition that could not be
read, or holds no visible record, is ``None`` — rendered as "not computed" — and never
``0``/``[]``. A zero is emitted only when the partition WAS read and genuinely holds none.
"""

from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from boto3.dynamodb.conditions import Key
from common import constants as _constants
from experiment.phase_filter import singleton_visible, with_phase_filter

#: The Hevy window. Mirrors ``coach_domain_facts._physical_pack`` (14 days), so the seat's
#: chat and its daily read see the same sessions — the window ends at the brief's subject day.
HEVY_WINDOW_DAYS = 14
MAX_SESSIONS = 5
MAX_ACTIVITIES = 6
MAX_PAIRS = 5
MAX_EXPERIMENT_NAMES = 3
_KG_PER_LB = 0.45359237
_M_PER_MILE = 1609.34

#: A Strava activity whose device is Hevy is the SAME session Hevy already logged (Hevy
#: pushes every workout to Strava as WeightTraining — live rows 2026-09-25/26). Listing it
#: twice would double the strength count the coach narrates.
_HEVY_MIRROR_DEVICE = "hevy"


def gather(
    table: Any,
    fetch_range: Callable[[str, str, str], list],
    today: date,
    yesterday: str,
    user_prefix: str,
    withings_rows: Optional[list] = None,
) -> Dict[str, Any]:
    """The keys the physical and explorer blocks read, for ``gather_daily_data`` to spread.

    ``withings_rows`` is the brief's own 30-day Withings window (#4373) — the subject day's
    row is picked from it, not re-read.

    ``fetch_range`` is the brief's own phase-aware DATE# window reader (reused, not a third
    Hevy reader — #4358's acceptance). The correlation and experiment partitions are keyed
    ``WEEK#``/``EXP#``, which that reader cannot address, so they are queried here with the
    same ADR-058 phase filter.
    """
    start = (today - timedelta(days=HEVY_WINDOW_DAYS)).isoformat()
    experiments = _active_experiments(table, user_prefix)
    hevy = fetch_range("hevy", start, yesterday)
    corr = _latest_correlations(table, user_prefix)
    withings = subject_day_row(withings_rows, yesterday)
    out = {
        "hevy_recent": hevy,
        "withings": withings,
        "weekly_correlations": corr,
        "active_experiments": None if experiments is None else len(experiments),
        "experiment_names": None if experiments is None else experiments[:MAX_EXPERIMENT_NAMES],
    }
    # The live proof line (#4358/#4359): what the two blocks were handed, greppable in the
    # daily-brief log group — the coach pipeline does not log its domain_data.
    dates = sorted({_row_date(r) for r in hevy if isinstance(r, dict)}, reverse=True)
    print(
        f"[brief_domain_inputs] hevy_recent={len(hevy)} (dates {dates[:3]}) "
        f"weekly_correlations={(corr or {}).get('week', 'NOT COMPUTED')} significant={(corr or {}).get('significant_correlations')} "
        f"active_experiments={out['active_experiments']} names={out['experiment_names']} "
        f"withings={(withings or {}).get('date', 'NO ROW')} weight_lbs={(withings or {}).get('weight_lbs')}"
    )
    return out


def _query_visible(table: Any, pk: str, sk_prefix: str) -> Optional[List[dict]]:
    """Every visible row of one partition, newest first; None when the read failed.

    No ``Limit``: DynamoDB applies it BEFORE the filter, so a limited read of a partition
    whose newest rows were wiped returns nothing (the #1203/#2080 class). Both partitions
    are small (one row a week; a handful of experiments).
    """
    try:
        kwargs = with_phase_filter(
            {
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix),
                "ScanIndexForward": False,
            }
        )
        items: List[dict] = []
        for _page in range(10):
            resp = table.query(**kwargs)
            items.extend(i for i in resp.get("Items") or [] if singleton_visible(i))
            if "LastEvaluatedKey" not in resp:
                return items
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return items
    except Exception as e:  # noqa: BLE001 — a failed read is ABSENCE, reported as such
        print(f"[brief_domain_inputs] {pk} read failed (absence, not zero): {e}")
        return None


def _num(v: Any) -> Optional[float]:
    try:
        return float(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _latest_correlations(table: Any, user_prefix: str) -> Optional[Dict[str, Any]]:
    """The newest visible ``weekly_correlations`` record, summarised; None when there is none.

    The writer (``weekly_correlation_compute_lambda.store_correlations``) stores a
    ``correlations`` MAP keyed by pair label — there is no ``pairs``/``significant_pairs``
    key on any record. Significance is the writer's own Benjamini-Hochberg verdict
    (``fdr_significant``), never re-judged here.
    """
    items = _query_visible(table, user_prefix + "weekly_correlations", "WEEK#")
    if not items:
        return None
    rec = items[0]
    corrs = rec.get("correlations")
    if not isinstance(corrs, dict):
        return None
    sig = []
    for label, c in corrs.items():
        r = _num(c.get("pearson_r")) if isinstance(c, dict) else None
        if r is None or c.get("fdr_significant") is not True:
            continue
        sig.append(
            {
                "pair": label,
                "metric_a": c.get("metric_a"),
                "metric_b": c.get("metric_b"),
                "r": round(r, 2),
                "n_days": int(_num(c.get("n_days")) or 0),
                "ci95": [_num(c.get("ci95_low")), _num(c.get("ci95_high"))],
                "counterintuitive": bool(c.get("counterintuitive")),
            }
        )
    sig.sort(key=lambda p: -abs(p["r"]))
    return {
        "week": rec.get("week"),
        "window": f"{rec.get('start_date')}..{rec.get('end_date')}",
        "pairs_tested": len(corrs),
        "significant_correlations": len(sig),
        "top_pairs": sig[:MAX_PAIRS],
    }


def _active_experiments(table: Any, user_prefix: str) -> Optional[List[str]]:
    """Names of the visible ``status == "active"`` experiments; None when the read failed."""
    items = _query_visible(table, user_prefix + "experiments", "EXP#")
    if items is None:
        return None
    return [str(e.get("name") or e.get("experiment_id") or "unnamed") for e in items if e.get("status") == "active"]


# ── the builder side: read by ai_context._build_physical_data / _build_explorer_data ──


def _row_date(row: dict) -> str:
    return str(row.get("date") or str(row.get("sk", ""))[len("DATE#") :])[:10]


def subject_day_row(rows: Optional[list], day: str) -> Optional[Dict[str, Any]]:
    """#4373: the ``day`` row of a DATE#-keyed window, or None — the brief's
    ``fetch_date`` convention (whoop/strava/apple are the subject day's row), applied to a
    window already in hand."""
    return next((r for r in rows or [] if isinstance(r, dict) and _row_date(r) == day), None)


def withings_block(data: Dict[str, Any]) -> Dict[str, Any]:
    """#4373: the subject day's own Withings weigh-in, DATED.

    ``_build_physical_data`` read ``data["withings"]`` for years and the brief never set it,
    so ``weight_lbs`` was None every day. It now carries the reading's own date (#1924: a
    bare weight gets narrated as current), and a pre-genesis row is withheld (#2104: the
    brief's subject day is YESTERDAY, so on genesis day this row is the previous cycle's).

    Body fat is deliberately NOT read from this row: the live field is ``fat_ratio_pct``
    (never ``body_fat_pct``), and it is TIER_OWNER_ONLY in ``privacy.field_tiers`` — the
    physical coach's text is a reader surface. DEXA's owner-published ``body_fat_pct`` is
    the builder's only body-fat source.
    """
    row = data.get("withings") or {}
    row_date = _row_date(row) if row else None
    weight = _num(row.get("weight_lbs"))
    # ONE boundary with the dated weight facts beside it (weight_recency's `cycle_genesis`),
    # else the constants MODULE read at call time — never an import-time-frozen value.
    genesis = str((data.get("weight_recency") or {}).get("cycle_genesis") or _constants.EXPERIMENT_START_DATE)
    if weight is None or not row_date or row_date < genesis:
        return {"weight_lbs": None, "weight_lbs_date": None}
    return {"weight_lbs": round(weight, 1), "weight_lbs_date": row_date}


def _strava_activities(day_rows: list) -> List[Dict[str, Any]]:
    """Flatten Strava DAY rows (one row a day, an ``activities`` list inside) to dated
    activities, newest first, Hevy mirrors dropped."""
    out = []
    for day in day_rows:
        if not isinstance(day, dict):
            continue
        for a in day.get("activities") or []:
            if not isinstance(a, dict) or str(a.get("device_name") or "").strip().lower() == _HEVY_MIRROR_DEVICE:
                continue
            secs = _num(a.get("moving_time_seconds")) or _num(a.get("elapsed_time_seconds"))
            metres = _num(a.get("distance_meters"))
            out.append(
                {
                    "date": str(a.get("start_date_local") or "")[:10] or _row_date(day),
                    "type": a.get("sport_type") or a.get("type") or "unknown",
                    "duration_min": round(secs / 60, 1) if secs else None,
                    "distance_miles": round(metres / _M_PER_MILE, 2) if metres else None,
                    "avg_hr": _num(a.get("average_heartrate")),
                }
            )
    out.sort(key=lambda a: str(a["date"]), reverse=True)
    return out


def training_block(data: Dict[str, Any]) -> Dict[str, Any]:
    """#4358: the dated training block — Hevy sessions and Strava activities, each with its
    own date, and a day with no logged session stated as ABSENCE (ADR-104), not zero."""
    as_of = str(data.get("date") or "")[:10]
    hevy = sorted((r for r in data.get("hevy_recent") or [] if isinstance(r, dict)), key=lambda r: str(r.get("sk", "")), reverse=True)
    sessions = []
    for r in hevy[:MAX_SESSIONS]:
        vol_kg = _num(r.get("total_volume_kg"))
        secs = _num(r.get("duration_sec"))
        sessions.append(
            {
                "date": _row_date(r),
                "title": r.get("title") or "Strength session",
                "duration_min": round(secs / 60) if secs else None,
                "exercise_count": int(_num(r.get("exercise_count")) or 0),
                "set_count": int(_num(r.get("set_count")) or 0),
                "volume_lb": round(vol_kg / _KG_PER_LB) if vol_kg else None,
            }
        )
    activities = _strava_activities(data.get("strava_7d") or [])
    last = sessions[0]["date"] if sessions else None
    if not sessions:
        note = f"No Hevy strength session logged in the {HEVY_WINDOW_DAYS} days through {as_of} — absence of logs, not proof of rest days."
    elif last != as_of:
        note = f"No strength session logged on {as_of}; the most recent logged session is {last}. A day without a log is absence, not zero training."
    else:
        note = f"Strength session logged on {as_of}."
    if not activities:
        note += " No Strava activity outside the logged lifts in the last 7 days — absence of data, not zero activity."
    return {
        "strength_sessions_14d": sessions,
        "strength_session_count_14d": len(hevy),
        "last_strength_session_date": last,
        "cardio_activities_7d": activities[:MAX_ACTIVITIES],
        "training_note": note,
    }


def explorer_block(data: Dict[str, Any]) -> Dict[str, Any]:
    """#4359: the explorer's cross-domain block. A partition that is absent renders as
    "not computed" (None + a status line) — never the false ``0``/``[]`` it used to be."""
    corr = data.get("weekly_correlations")
    n_active = data.get("active_experiments")
    out: Dict[str, Any] = {}
    if isinstance(corr, dict):
        out.update(
            {
                "significant_correlations": corr.get("significant_correlations"),
                "pairs_tested": corr.get("pairs_tested"),
                "top_pairs": (corr.get("top_pairs") or [])[:MAX_PAIRS],
                "correlation_week": corr.get("week"),
                "correlation_window": corr.get("window"),
            }
        )
    else:
        out.update(
            {
                "significant_correlations": None,
                "top_pairs": None,
                "correlations_status": "not computed — no weekly correlation record is readable this cycle; do not report zero correlations",
            }
        )
    if isinstance(n_active, int):
        out.update({"active_experiments": n_active, "experiment_names": list(data.get("experiment_names") or [])})
    else:
        out.update(
            {
                "active_experiments": None,
                "experiment_names": None,
                "experiments_status": "not computed — the experiments partition was not readable; do not report zero experiments",
            }
        )
    return out
