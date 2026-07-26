"""Spiral circuit breaker (#1627) — the leading-indicator detector that gates celebratory output.

The Personal Board's binding guardrail (docs/BOARDS.md §5, issue #1627): during a suspected
downturn the platform's job is to check on Matthew, not to congratulate him. Every celebratory
emitter routes its "should I celebrate?" question through this module before firing.

Architecture (the personal_baselines.py split, ADR-105):

- **Pure core** — `is_suppressed(signals, config, now) -> (bool, reasons)` and the fuller
  `evaluate(...)`. Deterministic, no I/O, no LLM anywhere in the path, no wall-clock reads
  (`now` is a required parameter). Same inputs -> same output, always.
- **Fetch half** — `gather_signals(now=...)` owns the DynamoDB reads and returns the plain
  dict the core consumes. Any fetch failure simply omits that signal family, which the core
  treats as no-data -> suppress.

The five conditions (issue #1627; thresholds from personal variance per ADR-105 rule 4):

1. ``low_valence`` — recent State of Mind valence below the personal trailing p25.
2. ``training_gap`` — no logged training day (hevy | strava) for >= 7 days.
3. ``habit_collapse`` — trailing-14d tier-0 habit compliance below the personal baseline p25.
4. ``sleep_midpoint_variance`` — recent sleep-midpoint spread above the personal band
   (p75 of the trailing distribution of same-length rolling windows).
5. ``coverage_hold`` — the ADR-134 character coverage gate is holding any pillar for thin
   data (an uninstrumented pillar must never be read as a good one).

**Fails closed.** Missing, stale, or thin input data suppresses celebration rather than
permitting it (the genesis-week present-None precedent, #1540/#1536/#1535). Only five
explicit ``clear`` verdicts allow a celebratory output.

**Privacy (public repo).** Suppression is never surfaced publicly — the absence of a note is
the signal, and it is a private one. Reasons are structured for private audit surfaces
(logs, email internals) only; they must never flow into any public API response or page.
The clinical rationale for the condition set is held privately (docs/PLATFORM_CONTEXT.md,
PRIVATE) — this module cites issue/ADR numbers only, by design.

Wiring status: the emitter registry below (`CELEBRATORY_EMITTERS`) enumerates the
celebratory surfaces; enforcement that each one imports this gate lands with the wiring
follow-up (tracked on #1627 / epic #1619).
"""

from datetime import date, datetime, timedelta

from personal_baselines import percentile

try:  # structured JSON logging (logger-discipline gate: never print() in lambdas/)
    from platform_logger import get_logger

    logger = get_logger("spiral-breaker")
except ImportError:  # pragma: no cover — minimal bundles
    import logging

    logger = logging.getLogger("spiral-breaker")

try:  # thresholds live next to the facet they threshold — imported, never copied (#498)
    from source_registry import DEFAULT_STALE_HOURS, hae_datatype_thresholds

    _SOM_STALE_DAYS = next(
        (int(d.get("stale_days") or 14) for d in hae_datatype_thresholds() if d.get("key") == "state_of_mind"),
        14,
    )
    _WEARABLE_STALE_DAYS = int(DEFAULT_STALE_HOURS) // 24 + 1  # 48h infra threshold + a day of margin
except Exception:  # pragma: no cover — registry unavailable (minimal bundles); safe literals
    _SOM_STALE_DAYS = 14
    _WEARABLE_STALE_DAYS = 3

# ---------------------------------------------------------------------------
# Contract constants
# ---------------------------------------------------------------------------

# Condition names (stable identifiers — these appear in reasons and audit logs).
LOW_VALENCE = "low_valence"
TRAINING_GAP = "training_gap"
HABIT_COLLAPSE = "habit_collapse"
SLEEP_MIDPOINT_VARIANCE = "sleep_midpoint_variance"
COVERAGE_HOLD = "coverage_hold"

CONDITIONS = (LOW_VALENCE, TRAINING_GAP, HABIT_COLLAPSE, SLEEP_MIDPOINT_VARIANCE, COVERAGE_HOLD)

# Statuses. Anything other than CLEAR suppresses (fail closed).
CLEAR = "clear"
FIRED = "fired"
NO_DATA = "no_data"
STALE = "stale"
INSUFFICIENT_BASELINE = "insufficient_baseline"

SUPPRESSING_STATUSES = (FIRED, NO_DATA, STALE, INSUFFICIENT_BASELINE)

# Stable CloudWatch prefix for the suppression audit trail (grep target — do not change).
SUPPRESSION_LOG_PREFIX = "[spiral-breaker] suppression"

DEFAULT_CONFIG = {
    # (1) low_valence — personal trailing p25 (ADR-105 rule 4, never a population constant)
    "valence_baseline_days": 60,
    "valence_recent_obs": 3,  # mean of the most recent k observations vs the band
    "valence_percentile": 25,
    "valence_min_n": 14,  # floor-guard: thinner baseline -> fail closed
    "valence_stale_days": _SOM_STALE_DAYS,  # registry: state_of_mind is a manual capture
    # (2) training_gap — the >=7-day bound is set by issue #1627 itself (documented-why-not
    # per ADR-105: a gap length is a count, not a distribution percentile)
    "training_gap_days": 7,
    "training_lookback_days": 30,
    # (3) habit_collapse — trailing 14d (issue-fixed window) vs personal baseline p25
    "habit_recent_days": 14,
    "habit_recent_min_days": 7,
    "habit_baseline_days": 60,  # baseline window sits BEFORE the recent window (no self-drag)
    "habit_percentile": 25,
    "habit_min_n": 14,
    "habit_stale_days": _WEARABLE_STALE_DAYS,
    # (4) sleep_midpoint_variance — recent spread vs p75 of rolling same-length windows
    "sleep_recent_days": 14,
    "sleep_recent_min_nights": 7,  # matches the circadian-compliance >=7-night floor
    "sleep_baseline_days": 60,
    "sleep_variance_percentile": 75,
    "sleep_min_rolling_windows": 10,
    "sleep_stale_days": _WEARABLE_STALE_DAYS,
    # (5) coverage_hold — ADR-134 gate read from the latest character sheet
    "character_stale_days": 3,
}

# ---------------------------------------------------------------------------
# Celebratory-emitter registry (#1627 wiring AC — enforcement lands with the wiring)
# ---------------------------------------------------------------------------
# Every surface that can emit a celebratory line is enumerated here. ``wired`` flips to
# True as each consumer routes through is_suppressed(); tests/test_spiral_breaker.py
# asserts every wired emitter actually imports this module, so a wired claim can't drift.
# ``pending_issue`` marks emitters whose module has not merged yet.
CELEBRATORY_EMITTERS = {
    "daily_brief": {"path": "lambdas/emails/daily_brief_lambda.py", "wired": False},
    "daily_debrief": {"path": "lambdas/emails/daily_debrief_lambda.py", "wired": False},
    "wednesday_chronicle": {"path": "lambdas/emails/wednesday_chronicle_lambda.py", "wired": False},
    "chronicle_share_kit": {"path": "lambdas/chronicle_share_kit.py", "wired": False},
    "state_of_matthew": {"path": "lambdas/compute/state_of_matthew_lambda.py", "wired": False},
    "coach_commentary": {"path": "lambdas/web/site_api_coach.py", "wired": False},
    "og_share_cards": {"path": "lambdas/og_image_lambda.mjs", "wired": False},
    # #1628: milestone_ledger.sweep routes announcements through check_celebration_allowed
    # (fail-closed; suppressed rungs stay unconsumed and re-evaluate later).
    "milestone_announcements": {"path": "lambdas/milestone_ledger.py", "wired": True},
}

USER_PREFIX = "USER#matthew#SOURCE#"


# ---------------------------------------------------------------------------
# Small pure helpers
# ---------------------------------------------------------------------------


def _coerce_now(now):
    """Normalize ``now`` to a datetime.date. Required — the pure core never reads the wall clock."""
    if now is None:
        raise ValueError("now is required — spiral_breaker's pure core never reads the wall clock (pass a Pacific date)")
    if isinstance(now, datetime):
        return now.date()
    if isinstance(now, date):
        return now
    return datetime.strptime(str(now)[:10], "%Y-%m-%d").date()


def _to_float(value):
    """Decimal/str tolerant float cast; None on failure."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_day(value):
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def _clean_series(mapping, start, end):
    """{date_str: value} -> sorted [(date, float)] within [start, end], Nones dropped."""
    out = []
    for k, v in (mapping or {}).items():
        d = _parse_day(k)
        f = _to_float(v)
        if d is None or f is None:
            continue
        if start <= d <= end:
            out.append((d, f))
    return sorted(out)


def _mean(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def _stdev(values):
    """Sample standard deviation; None below n=2."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    if n < 2:
        return None
    m = sum(vals) / n
    return (sum((v - m) ** 2 for v in vals) / (n - 1)) ** 0.5


def _normalize_midpoint_hour(hour):
    """Wrap-safe midpoint hour: values cluster around the small hours, so map (12, 24) -> (-12, 0)
    to keep e.g. 23.5 and 0.5 numerically adjacent (the circadian-compliance wrap convention)."""
    h = _to_float(hour)
    if h is None:
        return None
    h = h % 24.0
    return h - 24.0 if h > 12.0 else h


def _reason(condition, status, window_days, n, observed=None, threshold=None, detail=None):
    """One structured reason. Never prose — ADR-105 (structured, gradeable, no narrative)."""
    out = {
        "condition": condition,
        "status": status,
        "window_days": window_days,
        "n": n,
    }
    if observed is not None:
        out["observed"] = round(observed, 4)
    if threshold is not None:
        out["threshold"] = round(threshold, 4)
    if detail:
        out["detail"] = detail
    return out


# ---------------------------------------------------------------------------
# Condition evaluators (all pure)
# ---------------------------------------------------------------------------


def _eval_low_valence(signals, cfg, today):
    window = int(cfg["valence_baseline_days"])
    series = _clean_series(signals.get("som_daily_valence"), today - timedelta(days=window), today)
    if not series:
        return _reason(LOW_VALENCE, NO_DATA, window, 0)
    latest_day = series[-1][0]
    if (today - latest_day).days > int(cfg["valence_stale_days"]):
        return _reason(LOW_VALENCE, STALE, window, len(series), detail={"latest": latest_day.isoformat()})
    values = [v for _, v in series]
    if len(values) < int(cfg["valence_min_n"]):
        return _reason(LOW_VALENCE, INSUFFICIENT_BASELINE, window, len(values))
    band = percentile(values, int(cfg["valence_percentile"]))
    recent = _mean(values[-int(cfg["valence_recent_obs"]) :])
    if band is None or recent is None:
        return _reason(LOW_VALENCE, NO_DATA, window, len(values))
    status = FIRED if recent < band else CLEAR
    return _reason(
        LOW_VALENCE,
        status,
        window,
        len(values),
        observed=recent,
        threshold=band,
        detail={"percentile": int(cfg["valence_percentile"]), "recent_obs": int(cfg["valence_recent_obs"])},
    )


def _eval_training_gap(signals, cfg, today):
    window = int(cfg["training_lookback_days"])
    if "training_dates" not in (signals or {}):
        # Family never fetched (fetch failure / empty fixture) — that's absence of
        # EVIDENCE, not evidence of a gap: fail closed as no-data.
        return _reason(TRAINING_GAP, NO_DATA, window, 0)
    start = today - timedelta(days=window)
    days = sorted({d for d in (_parse_day(x) for x in (signals.get("training_dates") or ())) if d and start <= d <= today})
    if not days:
        # No training day anywhere in the lookback: the gap is at least the whole window.
        return _reason(TRAINING_GAP, FIRED, window, 0, observed=float(window), threshold=float(cfg["training_gap_days"]))
    gap = (today - days[-1]).days
    status = FIRED if gap >= int(cfg["training_gap_days"]) else CLEAR
    return _reason(
        TRAINING_GAP,
        status,
        window,
        len(days),
        observed=float(gap),
        threshold=float(cfg["training_gap_days"]),
        detail={"last_training_day": days[-1].isoformat()},
    )


def _normalize_pct(value):
    """tier0_pct is a 0..1 fraction by contract, but be tolerant of 0..100 legacy values
    (the character_engine convention)."""
    f = _to_float(value)
    if f is None:
        return None
    return f * 100.0 if f <= 1.0 else min(f, 100.0)


def _eval_habit_collapse(signals, cfg, today):
    recent_days = int(cfg["habit_recent_days"])
    baseline_days = int(cfg["habit_baseline_days"])
    window = recent_days + baseline_days
    raw = {k: _normalize_pct(v) for k, v in (signals.get("habit_daily_tier0_pct") or {}).items()}
    recent_start = today - timedelta(days=recent_days - 1)
    recent = _clean_series(raw, recent_start, today)
    baseline = _clean_series(raw, recent_start - timedelta(days=baseline_days), recent_start - timedelta(days=1))
    if not recent and not baseline:
        return _reason(HABIT_COLLAPSE, NO_DATA, window, 0)
    latest_day = max(d for d, _ in recent + baseline)
    if (today - latest_day).days > int(cfg["habit_stale_days"]):
        return _reason(HABIT_COLLAPSE, STALE, window, len(recent) + len(baseline), detail={"latest": latest_day.isoformat()})
    if len(recent) < int(cfg["habit_recent_min_days"]) or len(baseline) < int(cfg["habit_min_n"]):
        return _reason(
            HABIT_COLLAPSE,
            INSUFFICIENT_BASELINE,
            window,
            len(recent) + len(baseline),
            detail={"recent_n": len(recent), "baseline_n": len(baseline)},
        )
    band = percentile([v for _, v in baseline], int(cfg["habit_percentile"]))
    recent_mean = _mean([v for _, v in recent])
    if band is None or recent_mean is None:
        return _reason(HABIT_COLLAPSE, NO_DATA, window, len(recent) + len(baseline))
    status = FIRED if recent_mean < band else CLEAR
    return _reason(
        HABIT_COLLAPSE,
        status,
        recent_days,
        len(recent),
        observed=recent_mean,
        threshold=band,
        detail={"percentile": int(cfg["habit_percentile"]), "baseline_n": len(baseline), "baseline_window_days": baseline_days},
    )


def _eval_sleep_midpoint_variance(signals, cfg, today):
    recent_days = int(cfg["sleep_recent_days"])
    baseline_days = int(cfg["sleep_baseline_days"])
    window = recent_days + baseline_days
    raw = {}
    for k, v in (signals.get("sleep_midpoints") or {}).items():
        h = _normalize_midpoint_hour(v)
        if h is not None:
            raw[k] = h
    series = _clean_series(raw, today - timedelta(days=window), today)
    if not series:
        return _reason(SLEEP_MIDPOINT_VARIANCE, NO_DATA, window, 0)
    latest_day = series[-1][0]
    if (today - latest_day).days > int(cfg["sleep_stale_days"]):
        return _reason(SLEEP_MIDPOINT_VARIANCE, STALE, window, len(series), detail={"latest": latest_day.isoformat()})
    by_day = dict(series)
    min_nights = int(cfg["sleep_recent_min_nights"])

    def window_sd(end_day):
        vals = []
        for off in range(recent_days):
            v = by_day.get(end_day - timedelta(days=off))
            if v is not None:
                vals.append(v)
        return _stdev(vals) if len(vals) >= min_nights else None

    recent_sd = window_sd(today)
    rolling = []
    for back in range(recent_days, recent_days + baseline_days):
        sd = window_sd(today - timedelta(days=back))
        if sd is not None:
            rolling.append(sd)
    if recent_sd is None or len(rolling) < int(cfg["sleep_min_rolling_windows"]):
        return _reason(
            SLEEP_MIDPOINT_VARIANCE,
            INSUFFICIENT_BASELINE,
            window,
            len(series),
            detail={"recent_sd_available": recent_sd is not None, "rolling_windows": len(rolling)},
        )
    band = percentile(rolling, int(cfg["sleep_variance_percentile"]))
    if band is None:
        return _reason(SLEEP_MIDPOINT_VARIANCE, NO_DATA, window, len(series))
    status = FIRED if recent_sd > band else CLEAR
    return _reason(
        SLEEP_MIDPOINT_VARIANCE,
        status,
        recent_days,
        len(series),
        observed=recent_sd,
        threshold=band,
        detail={"percentile": int(cfg["sleep_variance_percentile"]), "rolling_windows": len(rolling), "unit": "hours_sd"},
    )


def _eval_coverage_hold(signals, cfg, today):
    character = signals.get("character") or {}
    sheet_day = _parse_day(character.get("sheet_date"))
    if sheet_day is None:
        return _reason(COVERAGE_HOLD, NO_DATA, int(cfg["character_stale_days"]), 0)
    if (today - sheet_day).days > int(cfg["character_stale_days"]):
        return _reason(COVERAGE_HOLD, STALE, int(cfg["character_stale_days"]), 1, detail={"latest": sheet_day.isoformat()})
    held = sorted(str(p) for p in (character.get("coverage_hold_pillars") or ()))
    # Deliberate (ADR-134 #960): pillars that are not_instrumented AND headline-excluded do
    # not fire on their own — a permanently-uninstrumented pillar would jam the breaker on.
    # coverage_hold is the engine's own "thin data today" verdict, which is the gate here.
    status = FIRED if held else CLEAR
    return _reason(
        COVERAGE_HOLD,
        status,
        int(cfg["character_stale_days"]),
        1,
        detail={
            "held_pillars": held,
            "not_instrumented_pillars": sorted(str(p) for p in (character.get("not_instrumented_pillars") or ())),
            "sheet_date": sheet_day.isoformat(),
        },
    )


_EVALUATORS = {
    LOW_VALENCE: _eval_low_valence,
    TRAINING_GAP: _eval_training_gap,
    HABIT_COLLAPSE: _eval_habit_collapse,
    SLEEP_MIDPOINT_VARIANCE: _eval_sleep_midpoint_variance,
    COVERAGE_HOLD: _eval_coverage_hold,
}


# ---------------------------------------------------------------------------
# Pure core — public surface
# ---------------------------------------------------------------------------


def evaluate(signals, config=None, now=None):
    """Full per-condition report. Pure and deterministic — no I/O, no LLM, no wall clock.

    Returns ``{"suppressed": bool, "as_of": iso_date, "reasons": [...], "conditions": [...]}``
    where ``conditions`` carries all five reports (including CLEAR ones, for audit/grading)
    and ``reasons`` only the suppressing ones. Every report records its window and n.
    """
    today = _coerce_now(now)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(config or {})
    signals = signals or {}
    conditions = [_EVALUATORS[name](signals, cfg, today) for name in CONDITIONS]
    reasons = [c for c in conditions if c["status"] != CLEAR]
    return {
        "suppressed": bool(reasons),
        "as_of": today.isoformat(),
        "reasons": reasons,
        "conditions": conditions,
    }


def is_suppressed(signals, config=None, now=None):
    """The gate every celebratory emitter calls (issue #1627).

    ``(True, reasons)`` -> do NOT celebrate; check in instead. ``(False, [])`` -> clear.
    Fails closed: empty/missing/stale/thin signals suppress. ``now`` is required
    (a Pacific-local date, ``datetime.date``/aware ``datetime``/"YYYY-MM-DD").

    Reasons are structured dicts for PRIVATE audit surfaces only — never expose them
    (or the fact of suppression) on any public endpoint or page.
    """
    verdict = evaluate(signals, config=config, now=now)
    return verdict["suppressed"], verdict["reasons"]


# ---------------------------------------------------------------------------
# Audit trail (no new DDB partition — CloudWatch structured log, greppable)
# ---------------------------------------------------------------------------


def record_suppression(verdict, emitter, now=None):
    """Record a suppression decision for auditability/false-positive grading (#1627 AC).

    Emits ONE structured JSON log line whose message is SUPPRESSION_LOG_PREFIX (the
    stable CloudWatch Logs Insights filter target), with emitter/suppressed/as_of/reasons
    as structured fields via platform_logger. Deliberately not a DynamoDB write: the
    detector stays read-only (no new partition, no orphan-gate surface); if grading later
    needs queryable history, a ledger partition ships with the wiring follow-up.
    Never raises.
    """
    try:
        logger.info(
            SUPPRESSION_LOG_PREFIX,
            emitter=str(emitter),
            suppressed=bool(verdict.get("suppressed")),
            as_of=verdict.get("as_of") or (_coerce_now(now).isoformat() if now else None),
            reasons=verdict.get("reasons", []),
        )
    except Exception as exc:  # pragma: no cover — audit trail must never break the caller
        logger.error(f"[spiral-breaker] record_suppression failed: {exc}")


# ---------------------------------------------------------------------------
# Fetch half — owns all I/O; the core never touches AWS
# ---------------------------------------------------------------------------


def _query_window(table, source, start_day, end_day):
    """All DATE#-keyed items for one source partition in [start, end], paginated."""
    from boto3.dynamodb.conditions import Key

    items = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(USER_PREFIX + source)
        & Key("sk").between(f"DATE#{start_day.isoformat()}", f"DATE#{end_day.isoformat()}~")
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        last = resp.get("LastEvaluatedKey")
        if not last:
            break
        kwargs["ExclusiveStartKey"] = last
    return items


def _midpoint_pacific_hour(sleep_start, sleep_end):
    """Fractional Pacific-local hour of the sleep midpoint from two ISO-8601 UTC stamps."""
    from zoneinfo import ZoneInfo

    try:
        start = datetime.fromisoformat(str(sleep_start).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(sleep_end).replace("Z", "+00:00"))
    except ValueError:
        return None
    if end <= start:
        return None
    mid = (start + (end - start) / 2).astimezone(ZoneInfo("America/Los_Angeles"))
    return mid.hour + mid.minute / 60.0 + mid.second / 3600.0


def gather_signals(now=None, table=None):
    """Read the five signal families from DynamoDB into the plain dict `evaluate` consumes.

    Resilient by construction: any family that fails to fetch is omitted, and the pure
    core fails closed on its absence. Decimal-safe (everything is cast via float on read).
    """
    if now is None:
        from pacific_time import pacific_today

        now = pacific_today()
    today = _coerce_now(now)

    if table is None:
        import boto3

        table = boto3.resource("dynamodb").Table("life-platform")

    cfg = DEFAULT_CONFIG
    signals = {"as_of": today.isoformat()}

    # (1) State of Mind daily valence — som_avg_valence on the apple_health partition
    # (there is no separate state_of_mind partition; see character_sheet_lambda).
    try:
        start = today - timedelta(days=int(cfg["valence_baseline_days"]))
        out = {}
        for item in _query_window(table, "apple_health", start, today):
            sk = str(item.get("sk", ""))
            v = _to_float(item.get("som_avg_valence"))
            if sk.startswith("DATE#") and len(sk) == 15 and v is not None:
                out[sk[5:15]] = v
        signals["som_daily_valence"] = out
    except Exception as exc:
        logger.warning(f"[spiral-breaker] som fetch failed (fails closed): {exc}")

    # (2) Training days — hevy workout sub-records (DATE#d#WORKOUT#id) union strava activity days.
    try:
        start = today - timedelta(days=int(cfg["training_lookback_days"]))
        days = set()
        for item in _query_window(table, "hevy", start, today):
            sk = str(item.get("sk", ""))
            if sk.startswith("DATE#") and "#WORKOUT#" in sk:
                days.add(sk[5:15])
        for item in _query_window(table, "strava", start, today):
            sk = str(item.get("sk", ""))
            if sk.startswith("DATE#"):
                days.add(sk[5:15])
        signals["training_dates"] = sorted(days)
    except Exception as exc:
        logger.warning(f"[spiral-breaker] training fetch failed (fails closed): {exc}")

    # (3) Habit compliance — tier0_pct (0..1 fraction) on the derived habit_scores partition.
    try:
        start = today - timedelta(days=int(cfg["habit_recent_days"]) + int(cfg["habit_baseline_days"]))
        out = {}
        for item in _query_window(table, "habit_scores", start, today):
            sk = str(item.get("sk", ""))
            v = _to_float(item.get("tier0_pct"))
            if sk.startswith("DATE#") and len(sk) == 15 and v is not None:
                out[sk[5:15]] = v
        signals["habit_daily_tier0_pct"] = out
    except Exception as exc:
        logger.warning(f"[spiral-breaker] habit fetch failed (fails closed): {exc}")

    # (4) Sleep midpoints — whoop sleep_start/sleep_end (skip interleaved #WORKOUT# sub-records).
    try:
        start = today - timedelta(days=int(cfg["sleep_recent_days"]) + int(cfg["sleep_baseline_days"]))
        out = {}
        for item in _query_window(table, "whoop", start, today):
            sk = str(item.get("sk", ""))
            if not sk.startswith("DATE#") or "#WORKOUT#" in sk:
                continue
            mid = _midpoint_pacific_hour(item.get("sleep_start"), item.get("sleep_end"))
            if mid is not None:
                out[sk[5:15]] = mid
        signals["sleep_midpoints"] = out
    except Exception as exc:
        logger.warning(f"[spiral-breaker] sleep fetch failed (fails closed): {exc}")

    # (5) ADR-134 coverage gate — latest character sheet, per-pillar coverage_hold flags.
    try:
        from boto3.dynamodb.conditions import Key

        resp = table.query(
            KeyConditionExpression=Key("pk").eq(USER_PREFIX + "character_sheet") & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
            Limit=1,
        )
        items = resp.get("Items", [])
        if items:
            record = items[0]
            held, not_instr = [], []
            for key, value in record.items():
                if not str(key).startswith("pillar_") or not isinstance(value, dict):
                    continue
                name = str(key)[len("pillar_") :]
                if value.get("coverage_hold"):
                    held.append(name)
                if value.get("not_instrumented"):
                    not_instr.append(name)
            signals["character"] = {
                "sheet_date": str(record.get("sk", ""))[5:15],
                "coverage_hold_pillars": sorted(held),
                "not_instrumented_pillars": sorted(not_instr),
            }
    except Exception as exc:
        logger.warning(f"[spiral-breaker] character fetch failed (fails closed): {exc}")

    return signals


def check_celebration_allowed(emitter, config=None, now=None, table=None):
    """One-call convenience for emitters: gather -> evaluate -> record -> (allowed, verdict).

    ``allowed`` is True only when every condition is CLEAR. Suppressions are recorded to
    the CloudWatch audit trail automatically. Emitters that already hold a signals dict
    should call is_suppressed() directly instead.
    """
    signals = gather_signals(now=now, table=table)
    verdict = evaluate(signals, config=config, now=now or signals.get("as_of"))
    if verdict["suppressed"]:
        record_suppression(verdict, emitter)
    return (not verdict["suppressed"]), verdict
