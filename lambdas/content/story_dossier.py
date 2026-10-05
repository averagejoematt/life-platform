"""content/story_dossier.py — the week dossier: the only numbers a story writer may use (#4532).

Deterministic and window-bounded: ``week_dossier(table, week)`` reads each partition for
exactly that week's dates and computes the figures in code (ADR-105 — deterministic
computation before any model verdict). The desk ranks stories from it; the writers write
from it; ``story_checks.ungrounded_numbers`` holds them to it.

Three rules the 2026-10-01 continuity review earned:

  * **Plan figures come from the plan root** (``experiment.plan_facts``), never from
    ``PROFILE#v1`` — the profile's 1,800 kcal / 190 g turned every protein verdict upside
    down for four weeks (#4540).
  * **An export lag is not an absence.** Each batch-exported source carries a watermark —
    the last date it covers and when that batch landed — and window dates past it are
    ``not_yet_exported``. MacroFactor lands 3–7 days late; four installments read that as
    a man who stopped logging.
  * **Programmed volume is the programme.** Every session carries whether it was a matched
    routine and how it scored against the prescription, so the volume is attributed to the
    team that wrote it.

Privacy at the source: habit names from the Vice group never enter the dossier (only held
counts), journal entries are counted, never read, and nothing here is a cycle count.
"""

from __future__ import annotations

import datetime as _dt
import statistics
from typing import Any, Dict, List, Optional, Tuple

from common.constants import EXPERIMENT_START_DATE as GENESIS  # noqa: E402 — one genesis (ADR-058)

USER = "matthew"


def _operational() -> tuple:
    from coach.persona_registry import OPERATIONAL_COACH_IDS  # the registry owns the roster (charter rule 1)

    return tuple(OPERATIONAL_COACH_IDS)


RATE_FLAG_LB_WK = 2.5  # the platform's own "losing too fast" flag (get_weight_loss_progress)


# ── the season calendar ──────────────────────────────────────────────────────


def _d(s: str) -> _dt.date:
    return _dt.datetime.strptime(s[:10], "%Y-%m-%d").date()


def season_weeks(genesis: str = GENESIS, through: Optional[str] = None) -> List[Dict[str, Any]]:
    """The chronicle's weeks: Week 1 runs from genesis to the first Tuesday (the Wednesday
    edition's cadence), then Wednesday→Tuesday. ``date`` is the week's last day — the key the
    chronicle has always stored a week under."""
    g = _d(genesis)
    first_end = g + _dt.timedelta(days=(1 - g.weekday()) % 7)  # Tuesday on/after genesis
    stop = _d(through) if through else first_end + _dt.timedelta(days=7 * 52)
    weeks = [{"week": 1, "start": g.isoformat(), "end": first_end.isoformat()}]
    end = first_end
    while end + _dt.timedelta(days=7) <= stop:
        start, end = end + _dt.timedelta(days=1), end + _dt.timedelta(days=7)
        weeks.append({"week": len(weeks) + 1, "start": start.isoformat(), "end": end.isoformat()})
    for w in weeks:
        w["date"] = w["end"]
        w["day_first"] = (_d(w["start"]) - g).days + 1
        w["day_last"] = (_d(w["end"]) - g).days + 1
    return weeks


def week_containing(day: str) -> Optional[Dict[str, Any]]:
    """The season week a calendar day falls in, or None before genesis. ONE definition: the Monday questions
    sender and its dead-man (`operational.story_season_qa`, #4539) must name the same week or the dead-man
    looks for a marker the sender never writes."""
    through = (_d(day) + _dt.timedelta(days=7)).isoformat()
    return next((w for w in season_weeks(through=through) if w["start"] <= day <= w["end"]), None)


def _dates(start: str, end: str) -> List[str]:
    a, b = _d(start), _d(end)
    return [(a + _dt.timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


# ── small numeric helpers ────────────────────────────────────────────────────


def _f(v: Any) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def _r(v: Optional[float], n: int = 1) -> Optional[float]:
    return None if v is None else round(v, n)


def _mean(xs: List[Optional[float]]) -> Optional[float]:
    ys = [x for x in xs if x is not None]
    return round(statistics.fmean(ys), 1) if ys else None


def _sd(xs: List[Optional[float]]) -> Optional[float]:
    ys = [x for x in xs if x is not None]
    return round(statistics.stdev(ys), 1) if len(ys) >= 3 else None


# ── readers (thin; the shared range readers do the phase filtering) ─────────


def _days(table, source, start, end) -> Dict[str, dict]:
    from common.digest_utils import query_range

    return query_range(table, source, start, end, user_id=USER)


def _rows(table, source, start, end) -> List[dict]:
    from common.digest_utils import query_range_list

    return query_range_list(table, source, start, end, user_id=USER)


# ── sections ─────────────────────────────────────────────────────────────────


def _weight(table, wk: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    series = _days(table, "withings", GENESIS, wk["end"])
    pts = sorted((d, _f(r.get("weight_lbs"))) for d, r in series.items() if _f(r.get("weight_lbs")))
    if not pts:
        return {"available": False}
    first_d, first_w = pts[0]
    in_win = [(d, w) for d, w in pts if wk["start"] <= d <= wk["end"]]
    before = [(d, w) for d, w in pts if d < wk["start"]]
    start_ref = before[-1] if before else pts[0]
    end_d, end_w = (in_win or pts)[-1]
    days_elapsed = max(1, (_d(end_d) - _d(first_d)).days)
    rate = (first_w - end_w) / days_elapsed * 7
    week_days = max(1, (_d(end_d) - _d(start_ref[0])).days)
    week_rate = (start_ref[1] - end_w) / week_days * 7
    marks = [m for m in range(325, 180, -5) if end_w <= m < start_ref[1]]
    waypoints = plan.get("weight_waypoints") or []
    nxt = next((w for w in waypoints if w["lbs"] < end_w), None)
    return {
        "available": True,
        "first_weigh_in": {"date": first_d, "lbs": _r(first_w)},
        "pre_registered_start_lbs": plan.get("prereg_start_lbs"),
        "week_start": {"date": start_ref[0], "lbs": _r(start_ref[1])},
        "week_end": {"date": end_d, "lbs": _r(end_w)},
        "week_change_lbs": _r(end_w - start_ref[1]),
        "total_change_lbs": _r(end_w - first_w),
        "avg_rate_lb_per_wk_since_start": _r(rate, 2),
        "rate_this_window_lb_per_wk": _r(week_rate, 2),
        "platform_rate_flag": rate > RATE_FLAG_LB_WK,
        "platform_rate_flag_rule": f"the platform flags losses above {RATE_FLAG_LB_WK} lb/wk as a lean-mass risk",
        "round_numbers_crossed_this_week": marks,
        "weigh_ins_in_window": [{"date": d, "lbs": _r(w)} for d, w in in_win],
        "next_plan_waypoint": nxt,
        "lbs_to_next_waypoint": _r(end_w - nxt["lbs"]) if nxt else None,
        "goal_lbs": plan.get("goal_lbs"),
    }


def _family(title: str) -> str:
    t = (title or "").lower()
    for fam in ("push", "pull", "legs", "engine", "upper", "lower", "flex"):
        if f" {fam} " in f" {t.replace('-', ' ')} ":
            return fam
    return "ad hoc"


def _training(table, wk: Dict[str, Any]) -> Dict[str, Any]:
    from training import training_streaks  # THE one definition of a loaded session (#4105)

    rows = sorted(_rows(table, "hevy", wk["start"], wk["end"]), key=lambda r: str(r.get("start_time") or r.get("sk") or ""))
    sessions = []
    for r in rows:
        ad = r.get("adherence") or {}
        asp = ad.get("as_prescribed") or {}
        sessions.append(
            {
                "date": r.get("date") or r["sk"][5:15],
                "title": r.get("title"),
                "block": _family(r.get("title") or ""),
                "loaded": training_streaks.is_loaded_session(r),  # a working set with weight on a non-cardio exercise
                "programmed": bool(r.get("hevy_routine_id")) and ad.get("status") == "matched",
                "minutes": round((_f(r.get("duration_sec")) or 0) / 60),
                "sets": int(_f(r.get("set_count")) or 0),
                "volume_lb": round((_f(r.get("total_volume_kg")) or 0) * 2.20462),
                "sets_adherence_pct": _r(_f(ad.get("overall_pct")), 0),
                "as_prescribed": asp.get("verdict"),
                "off_prescription_reasons": (asp.get("reasons") or [])[:2],
            }
        )
    whoop = [r for r in _rows(table, "whoop", wk["start"], wk["end"]) if "#WORKOUT#" in r.get("sk", "")]
    cardio = []
    seen = set()
    for w in whoop:
        wid = w.get("workout_id") or w["sk"].split("#WORKOUT#")[-1]
        if wid in seen:
            continue
        seen.add(wid)
        mins = None
        try:
            from common.pacific_time import parse_iso_utc

            a, b = parse_iso_utc(w["start_time"]), parse_iso_utc(w["end_time"])
            mins = round((b - a).total_seconds() / 60) if a and b else None
        except (KeyError, ValueError):
            pass
        sport = str(w.get("sport_name") or "")
        if (
            sport.lower() in ("weightlifting", "functional fitness", "powerlifting")
            or sport.startswith("Sport_")
            or w.get("average_heart_rate") is None
        ):
            continue
        cardio.append(
            {
                "date": w.get("date"),
                "sport": w.get("sport_name"),
                "minutes": mins,
                "avg_hr": _f(w.get("average_heart_rate")),
                "max_hr": _f(w.get("max_heart_rate")),
                "strain": _r(_f(w.get("strain"))),
            }
        )
    strava = _days(table, "strava", wk["start"], wk["end"])
    walks = []
    for d, r in sorted(strava.items()):
        for a in r.get("activities") or []:
            if str(a.get("sport_type", "")).lower() in ("walk", "hike"):
                walks.append(
                    {"date": d, "miles": _r(_f(a.get("distance_miles"))), "minutes": round((_f(a.get("moving_time_seconds")) or 0) / 60)}
                )
    # The streak is the LOADED-lifting streak ending at the window's end, looking back across weeks (#4678): the
    # same predicate and day-walk the routine notes and the coach packet read (`training.training_streaks`,
    # #4067/#4411). It used to count every date with ANY Hevy row — treadmill, bike and walking blocks included —
    # so a programme that logs cardio in Hevy on the off days could only ever grow it.
    lifting_days = {
        (r.get("date") or r["sk"][5:15])
        for r in _rows(table, "hevy", GENESIS, wk["end"])
        if not r.get("tombstone") and training_streaks.is_loaded_session(r)
    }
    day_after_end = (_d(wk["end"]) + _dt.timedelta(days=1)).isoformat()
    streak = training_streaks.streak_before(lifting_days, day_after_end)
    day_before = (_d(wk["start"]) - _dt.timedelta(days=1)).isoformat()
    blocks_before = {_family(r.get("title") or "") for r in _rows(table, "hevy", GENESIS, day_before)} if day_before >= GENESIS else set()
    blocks_now = [s["block"] for s in sessions]
    new_blocks = sorted({b for b in blocks_now if b not in blocks_before and b != "ad hoc"}) if blocks_before else []
    return {
        "sessions": sessions,
        "session_count": len(sessions),
        "programmed_count": sum(1 for s in sessions if s["programmed"]),
        "rest_days_in_window": [d for d in _dates(wk["start"], wk["end"]) if d not in {s["date"] for s in sessions}],
        "consecutive_loaded_lifting_days_through_week_end": streak,
        "lifting_streak_definition": (
            "consecutive days, ending on the window's last day, with a session that carried load (a working set with weight "
            "on a non-cardio exercise). Walk, treadmill, bike and other cardio-only days are not counted, so it is shorter "
            "than the run of days he was active. It is a count of lifting days and not a fatigue measure: never present it "
            "as a reason he needs rest."
        ),
        "minutes_total": sum(s["minutes"] for s in sessions),
        "longest_session_min": max((s["minutes"] for s in sessions), default=None),
        "new_programme_blocks_this_week": new_blocks,
        "who_writes_the_sessions": (
            "each programmed session is a routine the coaching workflow writes for that day and matches on completion; the volume is "
            "the programme as executed — whether he pushed past what was recommended is HIS call to report (owner_voice), and the "
            "over-ceiling sets in off_prescription_reasons are the data's evidence. Never attribute motive without his words."
        ),
        "cardio_and_walks_whoop": cardio,
        "strava_walks": walks,
    }


def _recovery(table, wk: Dict[str, Any]) -> Dict[str, Any]:
    days = _days(table, "whoop", wk["start"], wk["end"])
    base = _days(
        table, "whoop", (_d(wk["start"]) - _dt.timedelta(days=30)).isoformat(), (_d(wk["start"]) - _dt.timedelta(days=1)).isoformat()
    )
    per: List[Dict[str, Any]] = [
        {
            "date": d,
            "recovery": _f(r.get("recovery_score")),
            "hrv_ms": _r(_f(r.get("hrv"))),
            "rhr": _f(r.get("resting_heart_rate")),
            "sleep_h": _r(_f(r.get("sleep_duration_hours")), 2),
        }
        for d, r in sorted(days.items())
    ]

    def ext(key: str, fn) -> Optional[Dict[str, Any]]:
        vals = [p for p in per if p[key] is not None]
        if not vals:
            return None
        p = fn(vals, key=lambda x: x[key])
        return {"date": p["date"], "value": p[key]}

    return {
        "note": "each row is a MORNING: its recovery, HRV, resting HR and sleep_h all describe the night in sleep_night_of — pair them exactly as given",
        "per_day": per,
        "recovery_mean": _mean([p["recovery"] for p in per]),
        "hrv_mean_ms": _mean([p["hrv_ms"] for p in per]),
        "rhr_mean": _mean([p["rhr"] for p in per]),
        "sleep_mean_h": _mean([p["sleep_h"] for p in per]),
        "recovery_low": ext("recovery", min),
        "recovery_high": ext("recovery", max),
        "hrv_high": ext("hrv_ms", max),
        "rhr_low": ext("rhr", min),
        "previous_30d_recovery_mean": _mean([_f(r.get("recovery_score")) for r in base.values()]),
        "previous_30d_recovery_sd": _sd([_f(r.get("recovery_score")) for r in base.values()]),
        "previous_30d_hrv_mean_ms": _mean([_f(r.get("hrv")) for r in base.values()]),
        "previous_30d_rhr_mean": _mean([_f(r.get("resting_heart_rate")) for r in base.values()]),
        "nights_at_or_over_7_5h": sum(1 for p in per if (p["sleep_h"] or 0) >= 7.5),
    }


def _watermark(table, source: str, end: str) -> Dict[str, Any]:
    rows = _days(table, source, (_d(end) - _dt.timedelta(days=21)).isoformat(), (_d(end) + _dt.timedelta(days=21)).isoformat())
    if not rows:
        return {"last_covered_date": None, "last_batch_landed": None}
    last = max(rows)
    return {"last_covered_date": last, "last_batch_landed": str(rows[last].get("ingested_at") or "")[:16] or None}


def _nutrition(table, wk: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    days = _days(table, "macrofactor", wk["start"], wk["end"])
    kcal_t, prot_t, fib_t = plan.get("daily_calories_target"), plan.get("daily_protein_min_g"), plan.get("daily_fiber_min_g")
    per: List[Dict[str, Any]] = []
    for d in _dates(wk["start"], wk["end"]):
        r = days.get(d)
        if not r:
            continue
        per.append(
            {
                "date": d,
                "kcal": _r(_f(r.get("total_calories_kcal")), 0),
                "protein_g": _r(_f(r.get("total_protein_g")), 0),
                "fiber_g": _r(_f(r.get("total_fiber_g")), 0),
            }
        )
    wm = _watermark(table, "macrofactor", wk["end"])
    missing = [d for d in _dates(wk["start"], wk["end"]) if d not in days]
    nye = [d for d in missing if wm["last_covered_date"] is None or d > wm["last_covered_date"]]
    return {
        "targets_from_plan": {
            "calories_kcal": kcal_t,
            "protein_floor_g": prot_t,
            "fiber_min_g": fib_t,
            "source": "config/user_goals.json (the sealed plan)",
        },
        "per_day": per,
        "days_logged": len(per),
        "days_protein_at_or_over_floor": sum(1 for p in per if prot_t and (p["protein_g"] or 0) >= prot_t),
        "days_calories_at_or_under_target": sum(1 for p in per if kcal_t and (p["kcal"] or 1e9) <= kcal_t),
        "protein_mean_g": _mean([p["protein_g"] for p in per]),
        "calories_mean_kcal": _mean([p["kcal"] for p in per]),
        "export_watermark": wm,
        "not_yet_exported_dates": nye,
        "missing_but_exported_dates": [d for d in missing if d not in nye],
        "how_this_source_arrives": "MacroFactor is exported in batches that land days after the meals; a date past the watermark is NOT YET EXPORTED, not unlogged",
    }


def _habits(table, wk: Dict[str, Any]) -> Dict[str, Any]:
    scores = _days(table, "habit_scores", wk["start"], wk["end"])
    raw = _days(table, "habitify", wk["start"], wk["end"])
    # (vice names are collected only to be excluded)
    vice_names = {n for r in raw.values() for n, st in (r.get("habit_statuses") or {}).items() if (st or {}).get("group") == "Vice"}
    missed: Dict[str, int] = {}
    for r in scores.values():
        for h in r.get("missed_tier0") or []:
            if h in vice_names:  # a vice is reported only as a held count, never by name
                continue
            missed[h] = missed.get(h, 0) + 1
    done: Dict[str, int] = {}
    sched: Dict[str, int] = {}
    for r in raw.values():
        for name, st in (r.get("habit_statuses") or {}).items():
            if (st or {}).get("group") == "Vice":  # vice names never enter the dossier
                continue
            if (st or {}).get("scheduled_today") is False:
                continue
            sched[name] = sched.get(name, 0) + 1
            if (st or {}).get("status") in ("completed", "done"):
                done[name] = done.get(name, 0) + 1
    n = max(1, len(raw))
    held = sorted(((h, done.get(h, 0)) for h in sched if done.get(h, 0) == sched[h] and sched[h] >= n - 1), key=lambda x: x[0])
    rarely = sorted(((h, done.get(h, 0)) for h in sched if done.get(h, 0) <= 1 and sched[h] >= n - 1), key=lambda x: x[0])
    return {
        "days": len(scores),
        "non_negotiables_pct_mean": _r(_mean([(_f(r.get("tier0_pct")) or 0) * 100 for r in scores.values()]), 0),
        "non_negotiables_total": int(max([_f(r.get("tier0_total")) or 0 for r in scores.values()] or [0])),
        "non_negotiables_most_missed": sorted(missed.items(), key=lambda x: -x[1])[:3],
        "vices_held_mean_pct": _r(
            _mean([100 * (_f(r.get("vices_held")) or 0) / max(1.0, _f(r.get("vices_total")) or 1) for r in scores.values()]), 0
        ),
        "held_every_day": [h for h, _ in held][:12],
        "rarely_or_never_done": [h for h, _ in rarely][:12],
        "note": "an all-seven-every-day streak is not a story; the per-habit picture is",
    }


def _journal(table, wk: Dict[str, Any]) -> Dict[str, Any]:
    from boto3.dynamodb.conditions import Key

    n = 0
    for d in _dates(wk["start"], wk["end"]):
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#{USER}#SOURCE#notion") & Key("sk").begins_with(f"DATE#{d}#journal#"),
            ProjectionExpression="sk",
        )
        n += len(resp.get("Items", []))
    return {"entries_in_window": n, "privacy": "journal content is off the record; only its presence is a fact here"}


def _predictions(table, wk: Dict[str, Any], roster: Dict[str, str]) -> Dict[str, Any]:
    from boto3.dynamodb.conditions import Key

    graded: List[Dict[str, Any]] = []
    made: Dict[str, int] = {}
    record: Dict[str, Dict[str, int]] = {}
    prereg: List[Dict[str, Any]] = []
    prereg_status: Dict[str, str] = {}
    for cid in _operational():
        kw: Dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(f"COACH#{cid}") & Key("sk").begins_with("PREDICTION#")}
        items: List[dict] = []
        while True:
            resp = table.query(**kw)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kw["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        for it in items:
            if str(it.get("cycle") or "") not in ("17", "") or it.get("tombstone"):
                continue
            created = str(it.get("created_date") or "")
            if not created or created < GENESIS or created > wk["end"]:
                continue
            claim = str(it.get("claim_natural") or "")[:220]
            status = str(it.get("status") or "")
            od = str(it.get("outcome_date") or "")
            rec = record.setdefault(cid, {"right": 0, "wrong": 0})
            if status in ("confirmed", "refuted") and od and od <= wk["end"]:
                rec["right" if status == "confirmed" else "wrong"] += 1
                if od >= wk["start"]:
                    graded.append(
                        {
                            "coach": roster.get(cid, cid),
                            "coach_id": cid,
                            "made": created,
                            "graded": od,
                            "claim": claim,
                            "result": "right" if status == "confirmed" else "wrong",
                            "evidence": _outcome_line(it),
                        }
                    )
            if wk["start"] <= created <= wk["end"]:
                made[cid] = made.get(cid, 0) + 1
            if created == GENESIS:
                res = status if (status in ("confirmed", "refuted") and od and od <= wk["end"]) else "pending"
                prereg_status[_norm(it.get("claim_natural"))] = {"confirmed": "right", "refuted": "wrong"}.get(res, "not yet graded")
    sealed = load_prereg()
    for cid, block in (sealed.get("coaches") or {}).items():
        for p in block.get("predictions", []):
            prereg.append(
                {
                    "filed_by": display_name(block.get("coach_name")),
                    "coach_id": cid,
                    "claim": str(p.get("claim_natural"))[:240],
                    "window_days": p.get("window_days"),
                    "status_at_week_end": prereg_status.get(_norm(p.get("claim_natural")), "not in the graded ledger"),
                }
            )
    return {
        "graded_this_week": graded[:14],
        "graded_this_week_count": len(graded),
        "made_this_week_by_coach": {roster.get(k, k): v for k, v in made.items()},
        "record_to_date_by_coach": {roster.get(k, k): v for k, v in record.items()},
        "records_through": wk["end"],
        "pre_registered": prereg,
        # counts are facts, not something a model should count from a list (a fact read miscounted 16 as 15)
        "pre_registered_count": len(prereg),
        "pre_registered_filer_names": sorted({p["filed_by"] for p in prereg}),
        "pre_registered_filer_count": len({p["filed_by"] for p in prereg}),
        "pre_registered_status_counts": {
            k: sum(1 for p in prereg if p["status_at_week_end"] == k) for k in sorted({p["status_at_week_end"] for p in prereg})
        },
        "grading_caveat": "the evaluator grades directional calls by trend slope; a count claim ('5 of 7 nights') graded by slope is not a count (#4541); "
        "steps-based calls are graded on phone-only step counts that undercount, so a steps miss may be the instrument; state a record as 'through <records_through>'",
    }


PREREG_URL = "https://averagejoematt.com/experiments/prereg/genesis-2026-09-06.json"
PREREG_SHA256 = "bd225d24f67381c253a34671107ba1bc1a8a3c9cc35dadbca1a5edd061b9782d"  # printed in the sealed prologue
_PREREG_CACHE: Dict[str, Any] = {}


def load_prereg() -> Dict[str, Any]:
    """The sealed pre-registration, verified against the fingerprint the prologue printed.
    A mismatch returns {} — a sealed record that does not verify is not quoted."""
    if "doc" not in _PREREG_CACHE:
        import hashlib
        import json
        import urllib.request

        try:
            with urllib.request.urlopen(PREREG_URL, timeout=20) as resp:  # noqa: S310 — fixed https URL
                raw = resp.read()
            _PREREG_CACHE["doc"] = json.loads(raw) if hashlib.sha256(raw).hexdigest() == PREREG_SHA256 else {}
        except Exception:  # noqa: BLE001 — absence is reported as an empty section, never a guess
            _PREREG_CACHE["doc"] = {}
    return _PREREG_CACHE["doc"]


def _norm(s: Any) -> str:
    return " ".join(str(s or "").lower().split())[:160]


def _outcome_line(it: dict) -> str:
    import json

    try:
        n = json.loads(it.get("outcome_notes") or "{}")
        return str(n.get("reason") or "")[:200]
    except (TypeError, ValueError):
        return ""


def _coaches(table, wk: Dict[str, Any], roster: Dict[str, str]) -> List[Dict[str, Any]]:
    from boto3.dynamodb.conditions import Key
    from experiment.phase_filter import with_phase_filter

    out = []
    for cid in _operational():
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"COACH#{cid}")
                    & Key("sk").between(f"OUTPUT#{wk['start']}", f"OUTPUT#{wk['end']}~"),
                    "ScanIndexForward": False,
                }
            )
        )
        items = resp.get("Items", [])
        if not items:
            continue
        latest = items[0]
        out.append(
            {
                "coach_id": cid,
                "name": roster.get(cid, cid),
                "outputs_this_week": len(items),
                "latest_date": latest["sk"].split("#")[1],
                "latest_public_summary": str(latest.get("public_summary") or "")[:1400],
                "summary_caveat": "a coach summary may cite the profile's stale 190 g / 1,800 kcal targets (#4540); the plan's targets are in nutrition.targets_from_plan — never quote a target figure from a summary",
                "latest_key_recommendation": str(latest.get("key_recommendation") or "")[:400],
                "themes": [str(t) for t in (latest.get("themes") or [])][:5],
            }
        )
    return out


def _character(table, wk: Dict[str, Any]) -> Dict[str, Any]:
    days = _days(table, "character_sheet", wk["start"], wk["end"])
    if not days:
        return {}
    last = days[max(days)]
    events = []
    for r in days.values():
        for e in r.get("level_events") or []:
            if str(e.get("pillar")) != "relationships":
                events.append(
                    {"pillar": e.get("pillar"), "type": e.get("type"), "from": _f(e.get("old_level")), "to": _f(e.get("new_level"))}
                )
    return {
        "character_level_end": _f(last.get("character_level")),
        "pillar_levels_end": {
            p: _f((last.get(f"pillar_{p}") or {}).get("level"))
            for p in ("sleep", "movement", "nutrition", "metabolic", "mind", "consistency")
        },
        "level_events": events[:8],
        "note": "texture only — a reader does not know this vocabulary; use sparingly",
    }


def _grades(table, wk: Dict[str, Any]) -> Dict[str, Any]:
    days = _days(table, "day_grade", wk["start"], wk["end"])
    scores = [_f(r.get("total_score")) for r in days.values()]
    return {
        "day_grade_mean": _mean(scores),
        "explain": "the platform scores each day 0-100 across sleep, training, food, recovery and habits",
    }


def _steps(table, wk: Dict[str, Any]) -> Dict[str, Any]:
    days = _days(table, "apple_health", wk["start"], wk["end"])
    return {
        "per_day": [{"date": d, "steps": _f(r.get("steps"))} for d, r in sorted(days.items())],
        "caveat": "steps come from the phone only this experiment (the watch feed is paused), so they undercount — gym treadmill walks and walks without the phone are invisible; do not build a story on step counts",
    }


def _season_to_date(table, wk: Dict[str, Any]) -> Dict[str, Any]:
    """Experiment-to-date extremes and firsts, computed over every day since genesis — the ONLY source a writer may
    use for "first / lowest / highest / only / never / since the start" (the red team found six false superlatives
    derived from a single week's window)."""
    days = _days(table, "whoop", GENESIS, wk["end"])

    def ext(field: str, fn) -> Optional[Dict[str, Any]]:
        vals = [(d, _f(r.get(field))) for d, r in days.items() if _f(r.get(field)) is not None]
        if not vals:
            return None
        d, v = fn(vals, key=lambda x: x[1])
        return {"morning": d, "value": _r(v, 1)}

    sessions = sorted(_rows(table, "hevy", GENESIS, wk["end"]), key=lambda r: str(r.get("start_time") or r.get("sk") or ""))
    incomplete = []
    for r in sessions:
        ad = r.get("adherence") or {}
        pct = _f(ad.get("overall_pct"))
        if r.get("hevy_routine_id") and pct is not None and pct < 100:
            incomplete.append({"date": r.get("date") or r["sk"][5:15], "title": r.get("title"), "sets_pct": _r(pct, 0)})
    trained = sorted({(r.get("date") or r["sk"][5:15]) for r in sessions})
    return {
        "through": wk["end"],
        "recovery_low": ext("recovery_score", min),
        "recovery_high": ext("recovery_score", max),
        "hrv_low_ms": ext("hrv", min),
        "hrv_high_ms": ext("hrv", max),
        "rhr_low": ext("resting_heart_rate", min),
        "sleep_shortest_h": ext("sleep_duration_hours", min),
        "sleep_longest_h": ext("sleep_duration_hours", max),
        "programmed_sessions_below_100pct_sets": incomplete,
        "first_training_day": trained[0] if trained else None,
        "days_without_a_session_since_genesis": [d for d in _dates(GENESIS, wk["end"]) if d not in set(trained)],
        "rule": "a superlative or a 'first' must come from this block; this week's window alone cannot support one",
    }


def _owner_voice(table, wk: Dict[str, Any]) -> Dict[str, Any]:
    from content import story_questions

    return story_questions.owner_voice(table, f"USER#{USER}#SOURCE#insights", int(wk["week"]))


def _body_composition(table, wk: Dict[str, Any]) -> Dict[str, Any]:
    """Fat-free mass only: it is owner-published (field_tiers TIER_OWNER_PUBLISHED). Fat mass is Tier-2 owner-only
    and never enters the dossier (#4531 privacy fix — tests/test_privacy_tier_wiring_2803.py)."""
    days = _days(table, "withings", GENESIS, wk["end"])
    scans = [(d, _f(r.get("fat_free_mass_lbs"))) for d, r in sorted(days.items()) if _f(r.get("fat_free_mass_lbs")) is not None]
    if len(scans) < 2:
        return {"available": False}
    (d0, ff0), (d1, ff1) = scans[0], scans[-1]
    return {
        "available": True,
        "first_scan": {"date": d0, "fat_free_mass_lbs": _r(ff0)},
        "latest_scan": {"date": d1, "fat_free_mass_lbs": _r(ff1)},
        "fat_free_mass_change_lbs": _r(ff1 - ff0),
        "scans": len(scans),
        "caveat": "scale bio-impedance on full-scan days only — noisy and not a DEXA; fat-free mass includes water. The platform's "
        "lean-mass flag is a RATE heuristic (lb/week), not a composition measurement — never call it a measured lean-mass loss. "
        "Fat mass is private: never state it or derive it.",
    }


# ── the dossier ──────────────────────────────────────────────────────────────


def _goals() -> Dict[str, Any]:
    """The plan root: the repo file when present (scripts, tests), else S3 config/ (the Lambda runtime — config/ is
    not bundled), the same order experiment.plan_facts.load_plan_facts uses."""
    import json
    import os

    try:
        from common.repo_config import config_path

        with open(config_path("user_goals.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # noqa: BLE001 — fall through to S3
        import boto3

        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        return json.loads(
            s3.get_object(Bucket=os.environ.get("S3_BUCKET", "matthew-life-platform"), Key="config/user_goals.json")["Body"].read()
        )


def load_plan() -> Dict[str, Any]:
    from experiment.plan_facts import load_plan_facts

    facts = load_plan_facts() or {}
    goals = _goals()
    t = goals.get("targets") or {}
    return {
        **facts,
        "goal_lbs": (t.get("weight") or {}).get("goal_lbs"),
        "weight_waypoints": [{"lbs": m["lbs"], "label": m["label"]} for m in (t.get("weight") or {}).get("interim_milestones", [])],
        "plan_start_lbs": (goals.get("timeline") or {}).get("start_weight_lbs"),
        "prereg_start_lbs": 326.2,  # quoted in the sealed pre-registration essay; the first weigh-in was 327.3
        "lean_mass_floor_lbs": (t.get("body_composition") or {}).get("lean_mass_floor_lbs"),
        "plan_note": (goals.get("timeline") or {}).get("note"),
    }


def display_name(name: Optional[str]) -> str:
    """Reader-facing coach name: the AI personas carry no honorific (owner ruling 2026-10-02)."""
    from coach.persona_registry import plain_name

    return plain_name(name)


def roster() -> List[Dict[str, Any]]:
    from coach import persona_registry

    out = []
    import os

    s3 = None
    if not os.path.exists(
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "personas.json")
    ):
        import boto3

        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))  # Lambda: config/ lives in S3
    for pid, p in persona_registry.operational_personas(s3, os.environ.get("S3_BUCKET", "matthew-life-platform") if s3 else None).items():
        cid = p.get("engine_id") or p.get("coach_config_key")
        out.append(
            {
                "coach_id": cid,
                "persona_id": pid,
                "name": display_name(p.get("name")),
                "title": p.get("title"),
                "lens": p.get("lens"),
                "bio": p.get("short_bio"),
                "pronouns": p.get("pronouns"),
            }
        )
    return [r for r in out if r["coach_id"] in _operational()]


def week_dossier(table, wk: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
    """(dossier, not_yet_exported_sources) for one season week."""
    plan = load_plan()
    team = roster()
    names = {c["coach_id"]: c["name"] for c in team}
    nutrition = _nutrition(table, wk, plan)
    dossier = {
        "week": wk["week"],
        "window": {
            "start": wk["start"],
            "end": wk["end"],
            "experiment_days": f"Day {wk['day_first']} to Day {wk['day_last']}",
            # weekday names are facts too — a writer guessing them put "Sunday" on a Tuesday
            "calendar": {d: f"{_d(d).strftime('%A')}, Day {(_d(d) - _d(GENESIS)).days + 1}" for d in _dates(wk["start"], wk["end"])},
        },
        "plan": plan,
        "roster": team,
        "weight": _weight(table, wk, plan),
        "training": _training(table, wk),
        "recovery_and_sleep": _recovery(table, wk),
        "nutrition": nutrition,
        "habits": _habits(table, wk),
        "journal": _journal(table, wk),
        "predictions": _predictions(table, wk, names),
        "coaches_this_week": _coaches(table, wk, names),
        "character_sheet": _character(table, wk),
        "day_grades": _grades(table, wk),
        "steps": _steps(table, wk),
        "season_to_date": _season_to_date(table, wk),
        # his own words, when he answered the week's questions by email (#4546); empty is a normal week
        "owner_voice": _owner_voice(table, wk),
        "body_composition": _body_composition(table, wk),
    }
    nye = ["macrofactor"] if nutrition["not_yet_exported_dates"] else []
    dossier["roster_note"] = {
        "weekly_team": [c["name"] for c in team],
        "weekly_team_count": len(team),
        "pre_registration_filers": "sixteen calls under eight names; six of those names sit on the weekly team",
        "not_on_the_weekly_team": "Sarah Chen (the two training calls)",
        "same_seat_two_names": "the physical seat's two calls were filed as 'Victor Reyes'; that seat is Max Reyes on the weekly team",
    }
    dossier["data_caveats"] = [
        *(["nutrition for " + ", ".join(nutrition["not_yet_exported_dates"]) + " is not yet exported"] if nye else []),
        "steps undercount (phone only)",
        "journal ingestion has been degraded since mid-September: an absent entry may simply be unlanded. Journal presence is NOT a story this experiment — at most one passing line in a season, never a lead or a coach's theme",
    ]
    return dossier, nye
