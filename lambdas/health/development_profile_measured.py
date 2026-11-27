"""development_profile_measured.py — the MEASURED indicators of the development profile (#6294, amended 2026-11-26).

Owner rulings on #6317 (2026-11-26) these indicators encode:
  * "Preserve the evidence that estimated strength improved … Distinguish increased Zone 2 training volume from
    demonstrated aerobic fitness improvement. More minutes trained aren't automatically increased physical capacity."
    So zone 2 minutes are TRAINING VOLUME — shown, never counted toward physical capacity. Aerobic fitness counts only
    from RESULT measures: the fitness test battery's aerobic tests (#5078/#5798 — the 6-minute walk, the fixed-workload
    treadmill heart rate, the 20-minute bike at RPE 6; latest against previous in each test's own series) and the
    stored VO2 max device estimate (`get_training(view="cardio_fitness")`'s arc, resolved per date by
    `common.metric_truth`), from ONE device across both windows. No proxy is invented.
  * "Do not label consistency as improving merely because training frequency increased … Use adherence to intended
    routines where reliable records exist … Use the established core habit set." So training days are CONTEXT (seven
    a week is the ceiling, and Hevy walk blocks count); consistency counts program ADHERENCE — sessions credited by
    `training.session_sequence`'s credit rule against the sessions the program intends per program week — and the
    core-habit set's own done/known counts (`health.core_habits`, stored on the `habit_scores` rows).

THE RULES (stated, deterministic)

  strength       best Epley e1RM per lift over two 28-day windows; lifts performed in both; at least 3 lifts; a lift
                 moved at ±2.5%; better/worse at a net of 2 lifts (up and down inside that margin -> mixed).
  aerobic tests  the battery's aerobic tests: a test counts when its latest result (at most 84 days old) has a previous
                 result in the same series; better/worse from the battery's own direction; both ways -> mixed.
  aerobic VO2    the VO2 max device estimate, at least 3 estimates in EACH 28-day window, all from ONE device (two
                 vendors' estimators are not one instrument); better/worse at a change of window means >= 1.0 ml/kg/min.
  zone 2 volume  minutes per observed week (28-day windows, >= 14 eligible days each) — CONTEXT, never counted.
  training days  days with a Hevy workout or a zone 2 session per eligible week — CONTEXT, never counted.
  adherence      the four complete Mon–Sun weeks ending on the last Sunday on or before today, and the four before. A
                 week counts only when the program's intent for it is on record (a program week inside the session
                 sequence), it holds no sick or travel day, and at least 5 of its 7 days were observed (a habit record
                 or a session — an unobserved week is never a week of misses); a planned rest day is never a miss (the program intends
                 N sessions a week, not seven). Per window: sum(min(credited, intended)) / sum(intended). At least 3
                 counted weeks in EACH window; better/worse at a change >= 0.10; both windows >= 0.95 -> same (at the ceiling).
  core habits    days whose core set has at least one known habit (core_known > 0), sick and travel days excluded;
                 per window sum(core_done) / sum(core_known); at least 14 such days in EACH 28-day window; margin 0.05.
                 Counts only — no habit name is read or shown.
  body weight    shown, never scored.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Mapping, Optional

from health.development_profile_base import (
    BETTER,
    INSUFFICIENT,
    MEASURED_MIN_DAYS,
    MEASURED_WINDOW_DAYS,
    MIXED_DIR,
    SAME,
    WORSE,
    _compare,
    _day,
    _eligible_days,
    _excluded,
    _failed_indicator,
    _indicator,
    _measured_evidence,
    _num,
    _read_failed,
    _require_day,
    _which,
    _window_block,
    windows,
)

STRENGTH_MIN_LIFTS = 3
STRENGTH_MOVE_FRACTION = 0.025
STRENGTH_NET_LIFTS = 2
ZONE2_MARGIN_MIN = 10.0
ZONE2_MARGIN_FRACTION = 0.15
TRAINING_DAYS_MARGIN = 0.5
#: The battery's AEROBIC tests (charter `calibration.fitness_tests.tests`; the strength-side tests — dead hang,
#: assisted pull-up — are not aerobic and are not read here). A result counts when it has a previous result in the
#: same series (the battery's own `trend`, which keeps a regime-bound test inside one heart-rate regime and setting)
#: and the latest is at most AEROBIC_TEST_MAX_AGE_DAYS old.
AEROBIC_TESTS = ("six_minute_walk", "treadmill_20min_fixed", "bike_20min_rpe6")
AEROBIC_TEST_MAX_AGE_DAYS = 84
AEROBIC_MIN_ESTIMATES = 3
AEROBIC_MARGIN = 1.0
ADHERENCE_WEEKS = 4
ADHERENCE_MIN_WEEKS = 3
ADHERENCE_MARGIN = 0.10
ADHERENCE_CEILING = 0.95
ADHERENCE_MIN_OBSERVED_DAYS = 5  # of 7: a week the platform barely observed is not a week of misses
CORE_MIN_DAYS = 14
CORE_MARGIN = 0.05

AEROBIC_LABEL = "Demonstrated aerobic fitness (VO2 max device estimate)"
AEROBIC_TEST_LABEL = "Demonstrated aerobic fitness (fitness test battery: walk, fixed-workload treadmill, bike)"
ZONE2_LABEL = "Zone 2 minutes per observed week — training volume: minutes trained, not a fitness result"
TRAINING_DAYS_LABEL = "Training days per eligible week — frequency, shown as context"


def strength(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    key, label = "strength_best_e1rm", "Estimated strength: best e1RM per lift, lifts performed in both windows"
    failed = _read_failed(inputs, "lift_sessions")
    if failed:
        return _failed_indicator(key, label, failed)
    wins = windows(today, MEASURED_WINDOW_DAYS)
    best: dict[str, dict[str, float]] = {}
    per_lift_n: dict[str, dict[str, int]] = {}
    names: dict[str, str] = {}
    sessions = {name: 0 for name in wins}
    for s in inputs.get("lift_sessions") or []:
        w = _which(_day(s.get("date")), wins)
        v = _num(s.get("best_e1rm_lb"))
        ident = str(s.get("identity") or "")
        if w is None or v is None or v <= 0 or not ident:
            continue
        sessions[w] += 1
        names.setdefault(ident, str(s.get("name") or ident))
        slot = best.setdefault(ident, {})
        slot[w] = max(slot.get(w, 0.0), v)
        cnt = per_lift_n.setdefault(ident, {"recent": 0, "prior": 0})
        cnt[w] += 1
    compared = []
    for ident, slot in sorted(best.items()):
        if "recent" in slot and "prior" in slot:
            change = (slot["recent"] - slot["prior"]) / slot["prior"]
            moved = "up" if change >= STRENGTH_MOVE_FRACTION else "down" if change <= -STRENGTH_MOVE_FRACTION else "flat"
            compared.append(
                {
                    "lift": names[ident],
                    "prior_lb": round(slot["prior"], 1),
                    "recent_lb": round(slot["recent"], 1),
                    "moved": moved,
                    "n": per_lift_n[ident],
                    "window": _window_block(wins),
                }
            )
    ups = sum(1 for c in compared if c["moved"] == "up")
    downs = sum(1 for c in compared if c["moved"] == "down")
    ev = {
        "date": today,
        "source": "hevy (Epley e1RM, mcp.strength_helpers.extract_hevy_sessions)",
        "evidence_kind": "measured",
        "statement": (
            f"Estimated strength improved on {ups} of {len(compared)} repeated lifts ({downs} down, "
            f"{len(compared) - ups - downs} within ±{STRENGTH_MOVE_FRACTION:.1%}), best e1RM per lift, recent 28 days against the 28 before"
        ),
        "window": _window_block(wins),
        "n": {"lift_sessions": sessions, "lifts_compared": len(compared)},
        "figure": {"lifts": compared, "unit": "lb"},
        "counts_toward_status": True,
    }
    if len(compared) < STRENGTH_MIN_LIFTS:
        return _indicator(
            key, label, INSUFFICIENT, f"fewer than {STRENGTH_MIN_LIFTS} lifts performed in both windows ({len(compared)})", ev
        )
    if ups - downs >= STRENGTH_NET_LIFTS:
        direction = BETTER
    elif downs - ups >= STRENGTH_NET_LIFTS:
        direction = WORSE
    elif ups and downs:
        direction = MIXED_DIR
    else:
        direction = SAME
    return _indicator(key, label, direction, f"net lifts moved against a margin of {STRENGTH_NET_LIFTS}", ev)


def aerobic(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    """Demonstrated aerobic fitness from a RESULT measure only: the stored VO2 max device estimate."""
    key, label = "aerobic_vo2max_estimate", AEROBIC_LABEL
    failed = _read_failed(inputs, "vo2_estimates")
    if failed:
        return _failed_indicator(key, label, failed)
    wins = windows(today, MEASURED_WINDOW_DAYS)
    vals: dict[str, list[float]] = {name: [] for name in wins}
    devices: set[str] = set()
    for e in inputs.get("vo2_estimates") or []:
        w = _which(_day(e.get("date")), wins)
        v = _num(e.get("value"))
        if w is None or v is None or v <= 0:
            continue
        vals[w].append(v)
        devices.add(str(e.get("source") or "unknown"))
    n = {k: len(v) for k, v in vals.items()}
    fig = {k: (round(sum(v) / len(v), 1) if v else None) for k, v in vals.items()}
    ev = {
        "date": today,
        "source": "VO2 max device estimate (get_training view=cardio_fitness; common.metric_truth per date)",
        "evidence_kind": "measured",
        "statement": f"{label}: recent mean {fig['recent']} over {n['recent']} estimates, prior {fig['prior']} over {n['prior']}",
        "window": _window_block(wins),
        "n": n,
        "figure": {**fig, "unit": "ml/kg/min", "devices": sorted(devices)},
        "counts_toward_status": True,
    }
    if min(n.values()) < AEROBIC_MIN_ESTIMATES:
        return _indicator(
            key, label, INSUFFICIENT, f"not established — fewer than {AEROBIC_MIN_ESTIMATES} VO2 max estimates in a window ({n})", ev
        )
    if len(devices) > 1:
        return _indicator(key, label, INSUFFICIENT, f"not established — the estimates come from {len(devices)} devices' estimators", ev)
    direction = _compare(float(fig["recent"] or 0.0), float(fig["prior"] or 0.0), AEROBIC_MARGIN)
    return _indicator(key, label, direction, f"change of window means against a margin of {AEROBIC_MARGIN} ml/kg/min", ev)


def _why_not(cell: Mapping[str, Any]) -> str:
    if cell.get("state") != "measured":
        return str(cell.get("detail") or "never logged")
    if cell.get("direction") not in (BETTER, SAME, WORSE):
        return str(cell.get("detail") or "the first result in its series — nothing to compare it with yet")
    return f"the latest result is more than {AEROBIC_TEST_MAX_AGE_DAYS} days old"


def aerobic_tests(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    """Demonstrated aerobic fitness from the fitness test battery's own trend (latest against the previous result in
    the same series). A test logged once, or not for AEROBIC_TEST_MAX_AGE_DAYS, establishes nothing."""
    key, label = "aerobic_fitness_tests", AEROBIC_TEST_LABEL
    failed = _read_failed(inputs, "fitness_trend")
    if failed:
        return _failed_indicator(key, label, failed)
    trend = inputs.get("fitness_trend") or {}
    t = _require_day(today)
    rows, dirs = [], []
    for tid in AEROBIC_TESTS:
        cell = trend.get(tid) or {}
        latest, previous = cell.get("latest") or {}, cell.get("previous") or {}
        d = _day(latest.get("date"))
        fresh = d is not None and (t - d).days <= AEROBIC_TEST_MAX_AGE_DAYS
        comparable = cell.get("state") == "measured" and cell.get("direction") in (BETTER, SAME, WORSE) and fresh
        rows.append(
            {
                "test": tid,
                "label": cell.get("label") or tid,
                "latest": {"date": latest.get("date"), "value": latest.get("value")} if latest else None,
                "previous": {"date": previous.get("date"), "value": previous.get("value")} if previous else None,
                "unit": cell.get("unit"),
                "direction": cell.get("direction") if comparable else None,
                "why_not_counted": None if comparable else _why_not(cell),
            }
        )
        if comparable:
            dirs.append(str(cell["direction"]))
    ev = {
        "date": today,
        "source": "fitness test battery (training.fitness_tests.trend via mcp.tools_fitness_tests.read_view)",
        "evidence_kind": "measured",
        "statement": f"{label}: {len(dirs)} of {len(AEROBIC_TESTS)} aerobic tests have a comparable latest and previous result",
        "n": {"comparable_tests": len(dirs)},
        "figure": {"tests": rows},
        "counts_toward_status": True,
    }
    if not dirs:
        return _indicator(
            key, label, INSUFFICIENT, "not established — no aerobic battery test has a recent result to compare with a previous one", ev
        )
    if BETTER in dirs and WORSE in dirs:
        return _indicator(key, label, MIXED_DIR, "the aerobic tests point both ways", ev)
    direction = BETTER if BETTER in dirs else WORSE if WORSE in dirs else SAME
    return _indicator(key, label, direction, "latest against previous result in each test's own series", ev)


def zone2_volume(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    key = "zone2_minutes_per_week"
    failed = _read_failed(inputs, "zone2_sessions", "observed_days")
    if failed:
        return _failed_indicator(key, ZONE2_LABEL, failed, counts=False)
    wins = windows(today, MEASURED_WINDOW_DAYS)
    sessions = [(str(s.get("date"))[:10], _num(s.get("minutes")) or 0.0) for s in inputs.get("zone2_sessions") or []]
    elig = _eligible_days(inputs, wins, (d for d, _m in sessions))
    fig, n = {}, {}
    for name in wins:
        days = set(elig[name]["days"])
        n[name] = len(days)
        fig[name] = round(sum(m for d, m in sessions if d in days) / len(days) * 7, 1) if days else None
    ev = _measured_evidence(today, wins, n, fig, "min/week", "training.zone2_minutes counted sessions", elig, ZONE2_LABEL, counts=False)
    if min(n.values()) < MEASURED_MIN_DAYS:
        return _indicator(
            key, ZONE2_LABEL, INSUFFICIENT, f"fewer than {MEASURED_MIN_DAYS} eligible observed days in a window ({n})", ev, counts=False
        )
    margin = max(ZONE2_MARGIN_MIN, ZONE2_MARGIN_FRACTION * float(fig["prior"] or 0.0))
    direction = _compare(float(fig["recent"] or 0.0), float(fig["prior"] or 0.0), margin)
    reason = f"training volume {'up' if direction == BETTER else 'down' if direction == WORSE else 'about the same'}; shown, never counted as capacity"
    return _indicator(key, ZONE2_LABEL, direction, reason, ev, counts=False)


def training_days(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    key = "training_days_per_week"
    failed = _read_failed(inputs, "training_days", "observed_days")
    if failed:
        return _failed_indicator(key, TRAINING_DAYS_LABEL, failed, counts=False)
    wins = windows(today, MEASURED_WINDOW_DAYS)
    trained = {str(d)[:10] for d in inputs.get("training_days") or []}
    elig = _eligible_days(inputs, wins, trained)
    fig, n = {}, {}
    for name in wins:
        days = set(elig[name]["days"])
        n[name] = len(days)
        fig[name] = round(len(days & trained) / len(days) * 7, 2) if days else None
    src = "recorded training sessions (hevy + zone 2 sessions; Hevy walk blocks count)"
    ev = _measured_evidence(today, wins, n, fig, "days/week", src, elig, TRAINING_DAYS_LABEL, counts=False)
    ev["ceiling_note"] = (
        "seven days a week is the ceiling and Hevy walk blocks count as training, so frequency leaves no meaningful headroom"
    )
    if min(n.values()) < MEASURED_MIN_DAYS:
        return _indicator(
            key, TRAINING_DAYS_LABEL, INSUFFICIENT, f"fewer than {MEASURED_MIN_DAYS} eligible observed days ({n})", ev, counts=False
        )
    direction = _compare(float(fig["recent"] or 0.0), float(fig["prior"] or 0.0), TRAINING_DAYS_MARGIN)
    return _indicator(key, TRAINING_DAYS_LABEL, direction, "frequency; shown as context, never counted as consistency", ev, counts=False)


def adherence_windows(today: str) -> dict[str, list[str]]:
    """The Monday keys of the recent four complete Mon–Sun weeks (ending on the last Sunday on or before `today`) and the four before."""
    t = _require_day(today)
    last_sunday = t - timedelta(days=(t.weekday() + 1) % 7)
    mondays = [(last_sunday - timedelta(days=6 + 7 * k)).isoformat() for k in range(2 * ADHERENCE_WEEKS)]
    return {"recent": sorted(mondays[:ADHERENCE_WEEKS]), "prior": sorted(mondays[ADHERENCE_WEEKS:])}


def adherence(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    key, label = "program_adherence", "Program adherence: sessions credited against the sessions the program intended"
    failed = _read_failed(inputs, "adherence_weeks")
    if failed:
        return _failed_indicator(key, label, failed)
    weeks = {str(w.get("week_start")): w for w in inputs.get("adherence_weeks") or []}
    ex = _excluded(inputs)
    paused = ex["sick"] | ex["travel"]
    observed = {str(d)[:10] for d in (inputs.get("observed_days") or [])} | {str(d)[:10] for d in (inputs.get("training_days") or [])}
    out: dict[str, dict[str, Any]] = {}
    for name, mondays in adherence_windows(today).items():
        counted, skipped = [], []
        for m in mondays:
            w = weeks.get(m)
            intended = int(_num((w or {}).get("intended")) or 0)
            days = {(_require_day(m) + timedelta(days=i)).isoformat() for i in range(7)}
            if not w or intended <= 0:
                skipped.append({"week_start": m, "why": "no record of what the program intended that week"})
            elif days & paused:
                skipped.append({"week_start": m, "why": "a sick or travel day that week — never a miss"})
            elif len(days & observed) < ADHERENCE_MIN_OBSERVED_DAYS:
                skipped.append({"week_start": m, "why": f"fewer than {ADHERENCE_MIN_OBSERVED_DAYS} observed days — not read as misses"})
            else:
                credited = int(_num(w.get("credited")) or 0)
                counted.append({"week_start": m, "intended": intended, "credited": credited, "program_version": w.get("program_version")})
        den = sum(c["intended"] for c in counted)
        num = sum(min(c["credited"], c["intended"]) for c in counted)
        out[name] = {"weeks": counted, "skipped": skipped, "fraction": round(num / den, 3) if den else None, "intended": den, "done": num}
    n = {k: len(v["weeks"]) for k, v in out.items()}
    ev = {
        "date": today,
        "source": "training.session_sequence credited sessions (routine archetype + anchor content) against the program's sessions per program week",
        "evidence_kind": "measured",
        "statement": (
            f"{label}: recent {out['recent']['done']} of {out['recent']['intended']} intended over {n['recent']} weeks, "
            f"prior {out['prior']['done']} of {out['prior']['intended']} over {n['prior']} weeks"
        ),
        "intent_established_by": inputs.get("adherence_intent") or "not stated",
        "denominator": "sessions the program intended in each counted week (planned rest is never a miss; sick or travel weeks are left out)",
        "window": {k: {"weeks": v["weeks"], "skipped": v["skipped"]} for k, v in out.items()},
        "n": n,
        "figure": {"recent": out["recent"]["fraction"], "prior": out["prior"]["fraction"], "unit": "fraction of intended sessions"},
        "counts_toward_status": True,
    }
    if min(n.values()) < ADHERENCE_MIN_WEEKS:
        return _indicator(
            key,
            label,
            INSUFFICIENT,
            f"not enough to say — intent records cover fewer than {ADHERENCE_MIN_WEEKS} weeks in a window ({n})",
            ev,
        )
    recent, prior = float(out["recent"]["fraction"] or 0.0), float(out["prior"]["fraction"] or 0.0)
    if recent >= ADHERENCE_CEILING and prior >= ADHERENCE_CEILING:
        return _indicator(key, label, SAME, f"both windows at or above {ADHERENCE_CEILING:.0%} — at the ceiling", ev)
    return _indicator(key, label, _compare(recent, prior, ADHERENCE_MARGIN), f"change against a margin of {ADHERENCE_MARGIN}", ev)


def core_habits(inputs: Mapping[str, Any], today: str) -> dict[str, Any]:
    key, label = "core_habit_adherence", "Core habit set: core habits done over core habits known"
    failed = _read_failed(inputs, "core_habit_days")
    if failed:
        return _failed_indicator(key, label, failed)
    wins = windows(today, MEASURED_WINDOW_DAYS)
    ex = _excluded(inputs)
    paused = ex["sick"] | ex["travel"]
    per_day: dict[str, tuple[float, float]] = {}
    for row in inputs.get("core_habit_days") or []:
        d = _day(row.get("date"))
        done, known = _num(row.get("core_done")), _num(row.get("core_known"))
        if d is None or done is None or not known or _which(d, wins) is None or d.isoformat() in paused:
            continue
        per_day[d.isoformat()] = (done, known)  # one row per day: the day's own core verdict
    sums = {name: [0.0, 0.0, 0] for name in wins}
    for day, (done, known) in per_day.items():
        s = sums[str(_which(_day(day), wins))]
        s[0], s[1], s[2] = s[0] + done, s[1] + known, int(s[2]) + 1
    n = {k: int(v[2]) for k, v in sums.items()}
    fig = {k: (round(v[0] / v[1], 3) if v[1] else None) for k, v in sums.items()}
    ev = {
        "date": today,
        "source": "habit_scores core_done / core_known (health.core_habits, the charter's core set); counts only, no habit named",
        "evidence_kind": "measured",
        "statement": f"{label}: recent {fig['recent']} over {n['recent']} days, prior {fig['prior']} over {n['prior']} days",
        "window": _window_block(wins),
        "n": n,
        "figure": {**fig, "unit": "fraction of known core habits done"},
        "counts_toward_status": True,
    }
    if min(n.values()) < CORE_MIN_DAYS:
        return _indicator(key, label, INSUFFICIENT, f"fewer than {CORE_MIN_DAYS} days with a known core habit in a window ({n})", ev)
    direction = _compare(float(fig["recent"] or 0.0), float(fig["prior"] or 0.0), CORE_MARGIN)
    return _indicator(key, label, direction, f"change against a margin of {CORE_MARGIN}", ev)


def weight_figure(inputs: Mapping[str, Any], today: str) -> Optional[dict[str, Any]]:
    """Body weight, shown beside the capacity figures and never scored (whether a change is progress is his goal's call)."""
    if _read_failed(inputs, "weight"):
        return None
    wins = windows(today, MEASURED_WINDOW_DAYS)
    vals: dict[str, list[float]] = {name: [] for name in wins}
    for row in inputs.get("weight") or []:
        w = _which(_day(row.get("date")), wins)
        v = _num(row.get("weight_lbs"))
        if w is not None and v is not None:
            vals[w].append(v)
    n = {k: len(v) for k, v in vals.items()}
    if not any(n.values()):
        return None
    fig = {k: (round(sum(v) / len(v), 1) if v else None) for k, v in vals.items()}
    return {
        "date": today,
        "source": "withings weight_lbs",
        "evidence_kind": "measured",
        "statement": f"Mean weigh-in: recent {fig['recent']} lb ({n['recent']} weigh-ins), prior {fig['prior']} lb ({n['prior']}) — shown, not scored",
        "window": _window_block(wins),
        "n": n,
        "figure": {**fig, "unit": "lb"},
        "counts_toward_status": False,
    }
