"""lambdas/web/site_api_habits.py — habit-domain handlers split out of site_api_data.py
(#1654): habits / habit_streaks / habit_registry / vice_streaks + the #422 causality
capture helpers and the P1.1 taxonomy. Handlers read facade state via `_g` (see freshness)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import habit_causality
from boto3.dynamodb.conditions import Key
from phase_filter import with_phase_filter

from web.site_api_common import (
    USER_ID,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _is_blocked_vice,
    _ok,
    _scrub_blocked_terms,
    logger,
)

_TAX_TIME = [
    ("morning", ("morning", "wake", "wakeup", "wake-up", "am ", "breakfast", "sunrise", "first thing", "dawn")),
    ("evening", ("evening", "night", "bed", "bedtime", "pm ", "dinner", "sunset", "wind down", "wind-down", "before sleep")),
    ("midday", ("lunch", "midday", "afternoon", "noon")),
]


_TAX_AVOID = ("no ", "avoid", "quit", "limit", "less ", "skip", "cut ", "abstain", "stop ", "zero ")


_TAX_MAINTAIN = ("track", "log ", "logging", "weigh", "measure", "record", "review", "check ", "plan ")


_TAX_GROUP_HINTS = [
    ("Nutrition", ("eat", "protein", "hydrate", "water", "meal", "calorie", "macro", "veg", "food", "supplement", "creatine", "fiber")),
    ("Training", ("walk", "run", "lift", "workout", "train", "gym", "steps", "stretch", "mobility", "cardio", "zone", "ruck")),
    ("Recovery", ("sleep", "bed", "meditat", "breath", "sauna", "cold", "plunge", "rest", "recovery", "nap", "sunlight")),
    ("Mind", ("read", "journal", "write", "learn", "study", "gratitude", "reflect", "focus", "deep work")),
]


def _causality_entry(store: dict, habit: str) -> dict:
    """Get/create the causality accumulator for one habit."""
    return store.setdefault(
        habit,
        {"trigger": None, "reward": None, "context": [], "why_missed": []},
    )


def _absorb_habitify_notes(store: dict, habit: str, date_key: str, st: dict) -> None:
    """Lift verbatim Habitify notes (primary channel) into the causality accumulator.

    A note on a completed day is driver context; on a skipped/failed day it's the reason
    the day slipped. Interpretation is the deterministic trigger:/reward: convention only
    (habit_causality.parse_note) — nothing is inferred (ADR-104).
    """
    notes = st.get("notes") or []
    if not notes:
        return
    status = st.get("status")
    missed = status in ("failed", "skipped")
    entry = _causality_entry(store, habit)
    for raw_note in notes:
        text = _scrub_blocked_terms((raw_note or "").strip())
        if not text:
            continue
        parsed = habit_causality.parse_note(text)
        if missed:
            entry["why_missed"].append({"date": date_key, "reason": parsed["raw"] or text, "channel": "habitify_note"})
        else:
            if parsed["trigger"] and not entry["trigger"]:
                entry["trigger"] = {"text": parsed["trigger"], "channel": "habitify_note"}
            if parsed["reward"] and not entry["reward"]:
                entry["reward"] = {"text": parsed["reward"], "channel": "habitify_note"}
            body = parsed["raw"] or text
            if body:
                entry["context"].append({"date": date_key, "text": body, "channel": "habitify_note"})


def _absorb_reflection(store: dict, rec: dict) -> None:
    """Merge a Claude-sourced reflection record (secondary channel) — never overwrites a
    Habitify-sourced trigger/reward already present; both channels coexist per habit."""
    habit = rec.get("habit")
    if not habit or _is_blocked_vice(habit):
        return
    date_key = rec.get("date") or ""
    entry = _causality_entry(store, habit)
    trig = _scrub_blocked_terms((rec.get("trigger") or "").strip())
    rew = _scrub_blocked_terms((rec.get("reward") or "").strip())
    why = _scrub_blocked_terms((rec.get("why_missed") or "").strip())
    ctx = _scrub_blocked_terms((rec.get("context") or "").strip())
    if trig and not entry["trigger"]:
        entry["trigger"] = {"text": trig, "channel": "claude_reflection"}
    if rew and not entry["reward"]:
        entry["reward"] = {"text": rew, "channel": "claude_reflection"}
    if why:
        entry["why_missed"].append({"date": date_key, "reason": why, "channel": "claude_reflection"})
    if ctx:
        entry["context"].append({"date": date_key, "text": ctx, "channel": "claude_reflection"})


def _query_reflection_records(start_date: str, end_date: str, *, _g) -> list:
    """Read the Claude-sourced causality store (habit_causality partition) for the window."""
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    table = _g["table"]
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}habit_causality")
                    & Key("sk").between(f"HABITDAY#{start_date}", f"HABITDAY#{end_date}~"),
                }
            )
        )
        return _decimal_to_float(resp.get("Items", []))
    except Exception as e:  # pragma: no cover — live DDB only
        logger.warning("[handle_habits] reflection read failed (non-fatal): %s", e)
        return []


def _causality_public(entry: dict) -> dict:
    """Shape one habit's accumulated causality for the API (bounded, verbatim)."""
    return {
        "trigger": entry.get("trigger"),
        "reward": entry.get("reward"),
        "why_missed": entry.get("why_missed", [])[:8],
        "context": entry.get("context", [])[:5],
    }


def habit_streaks(*, _g) -> dict:
    """
    GET /api/habit_streaks
    Returns: Tier 0 habit streaks for public display (aggregate streak only, no habit names).
    Cache: 3600s (1 hr).
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    table = _g["table"]
    datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")

    # Read latest habit_scores record
    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": "pk = :pk",
                "ExpressionAttributeValues": {":pk": pk},
                "ScanIndexForward": False,
                "Limit": 3,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))
    record = items[0] if items else None

    if not record:
        # Genesis week — shaped-empty 200 (the Essential-Seven badge shows 0, not an error).
        return _ok(
            {"habit_streaks": {"as_of_date": yesterday, "tier0_pct": 0, "tier0_done": 0, "tier0_total": 1, "aggregate_streak": 0}},
            cache_seconds=300,
        )

    t0_done = int(record.get("tier0_done", 0))
    t0_total = int(record.get("tier0_total", 1))
    t0_pct = round(t0_done / t0_total * 100) if t0_total else 0

    # Compute aggregate T0 streak from habit_scores (t0_streak field if present)
    t0_streak = int(record.get("t0_perfect_streak") or record.get("t0_aggregate_streak") or 0)

    return _ok(
        {
            "habit_streaks": {
                "as_of_date": record.get("date", yesterday),
                "tier0_pct": t0_pct,
                "tier0_done": t0_done,
                "tier0_total": t0_total,
                "aggregate_streak": t0_streak,
            }
        },
        cache_seconds=3600,
    )


def vice_streaks(*, _g) -> dict:
    """
    GET /api/vice_streaks
    Returns content-filtered vice streak portfolio from habit_scores.vice_streaks.
    Computes current streak, 90-day best, and relapse count per vice.
    Blocked vices (per content_filter.json) are excluded from the response.
    Cache: 3600s (1 hr).
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _experiment_date = _g["_experiment_date"]
    table = _g["table"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ninety_days_ago = _experiment_date(90)

    # Stage0 Fix 1 (2026-05-30): _is_blocked_vice catches both blocked_vices
    # (exact full names) AND blocked_vice_keywords (substring match). Previously
    # only the former was filtered here, while the client shipped the keyword
    # list to do the substring check itself — leaking the keywords in JS.
    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{ninety_days_ago}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))

    if not items:
        return _ok({"vices": [], "total_held": 0, "total_tracked": 0, "as_of_date": today}, cache_seconds=3600)

    # Gather per-vice streak history (chronological)
    vice_history: dict = {}
    for item in items:
        vs = item.get("vice_streaks") or {}
        if not isinstance(vs, dict):
            continue
        for vice_name, streak_val in vs.items():
            if _is_blocked_vice(vice_name):
                continue
            if vice_name not in vice_history:
                vice_history[vice_name] = []
            vice_history[vice_name].append(int(streak_val or 0))

    if not vice_history:
        return _ok({"vices": [], "total_held": 0, "total_tracked": 0, "as_of_date": today}, cache_seconds=3600)

    # Current state from latest record
    latest = items[-1]
    latest_vs = {}
    raw_vs = latest.get("vice_streaks") or {}
    if isinstance(raw_vs, dict):
        latest_vs = {k: int(v or 0) for k, v in raw_vs.items() if not _is_blocked_vice(k)}

    vices = []
    for vice_name, history in vice_history.items():
        current_streak = latest_vs.get(vice_name, history[-1] if history else 0)
        best_streak = max(history) if history else 0
        # Relapse = streak dropped from >0 to 0
        relapses = sum(1 for i in range(1, len(history)) if history[i - 1] > 0 and history[i] == 0)
        vices.append(
            {
                "name": vice_name,
                "current_streak": current_streak,
                "best_streak": best_streak,
                "relapses_90d": relapses,
                "holding": current_streak > 0,
            }
        )

    # Sort: holding first, then by streak descending
    vices.sort(key=lambda v: (-int(v["holding"]), -v["current_streak"]))

    # Count actual holding vices, not the stored `vices_held` aggregate — that field read 7
    # against 6 tracked (more held than exist), a visible lie on the marquee stat. Derive it.
    total_held = sum(1 for v in vices if v["holding"])
    total_tracked = len(vices)

    return _ok(
        {
            "as_of_date": latest.get("date", today),
            "vices": vices,
            "total_held": total_held,
            "total_tracked": total_tracked,
        },
        cache_seconds=3600,
    )


def habits(*, _g) -> dict:
    """
    GET /api/habits
    Returns 90-day daily habit completion history (aggregate only — no habit names).
    Used by /habits/ page for the heatmap and group adherence bars.
    Cache: 3600s (1 hr).
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _experiment_date = _g["_experiment_date"]
    table = _g["table"]
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ninety_days_ago = _experiment_date(90)

    pk = f"{USER_PREFIX}habit_scores"
    resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habit scores
                "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{ninety_days_ago}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    items = _decimal_to_float(resp.get("Items", []))

    # ── Also pull by_group from habitify partition (group data lives there, not in habit_scores)
    hab_pk = f"{USER_PREFIX}habitify"
    hab_resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot habitify records
                "KeyConditionExpression": Key("pk").eq(hab_pk) & Key("sk").between(f"DATE#{ninety_days_ago}", f"DATE#{today}"),
                "ScanIndexForward": True,
            }
        )
    )
    habitify_by_date = {}
    _habit_agg: dict = {}  # P0.5: per-habit window adherence for the state taxonomy
    _causality: dict = {}  # #422: per-habit captured drivers + why-missed (both channels)
    _habit_days: dict = {}  # #1107: per-habit per-date status for the 30-day dot strip
    for hi in _decimal_to_float(hab_resp.get("Items", [])):
        date_key = hi.get("date") or hi.get("sk", "").replace("DATE#", "")
        by_group = hi.get("by_group", {})
        if by_group and isinstance(by_group, dict):
            # by_group[Group] = {completed, possible, pct, habits_done}
            # pct is 0.0–1.0, convert to 0–100
            habitify_by_date[date_key] = {g: round(float(v.get("pct", 0) or 0) * 100) for g, v in by_group.items() if isinstance(v, dict)}
        # Aggregate per-habit completed/scheduled across the window (state taxonomy).
        for hname, st in (hi.get("habit_statuses") or {}).items():
            if _is_blocked_vice(hname):
                continue
            st = st if isinstance(st, dict) else {}
            a = _habit_agg.setdefault(hname, {"scheduled": 0, "completed": 0, "group": st.get("group") or "Other", "last_completed": None})
            # #1107: per-date status for the dot strip — done / missed / off (not scheduled).
            # A date with no habitify entry at all stays "absent" (honest absence, ADR-104).
            if date_key:
                if st.get("scheduled_today", True):
                    _day_status = "done" if st.get("status") == "completed" else "missed"
                else:
                    _day_status = "off"
                _habit_days.setdefault(hname, {})[date_key] = _day_status
            if st.get("scheduled_today", True):
                a["scheduled"] += 1
                if st.get("status") == "completed":
                    a["completed"] += 1
                    # Staleness honesty: the date a habit LAST fired — so the front-end
                    # can stop calling a 2-week-silent habit "automatic".
                    if not a["last_completed"] or date_key > a["last_completed"]:
                        a["last_completed"] = date_key
            # #422 EVR-01/02: lift in-app Habitify notes into captured causality. A note on a
            # completed day is driver context (trigger/reward); on a missed day it's the why.
            _absorb_habitify_notes(_causality, hname, date_key, st)

    # #422: fold in the Claude-sourced reflection layer (secondary channel). Never
    # overwrites Habitify-sourced triggers/rewards — both channels coexist per habit.
    for _rec in _query_reflection_records(ninety_days_ago, today, _g=_g):
        _absorb_reflection(_causality, _rec)

    history = []
    for item in items:
        date_str = item.get("date") or item.get("sk", "").replace("DATE#", "")
        t0_done = int(item.get("tier0_done", 0) or 0)
        t0_total = int(item.get("tier0_total", 1) or 1)
        t01_done = int(item.get("tier01_done", t0_done) or t0_done)
        t01_total = int(item.get("tier01_total", t0_total) or t0_total)
        t0_pct = round(t0_done / t0_total * 100) if t0_total else 0
        t01_pct = round(t01_done / t01_total * 100) if t01_total else 0
        int(item.get("t0_perfect_streak") or item.get("t0_aggregate_streak") or 0)

        # Per-group breakdown: prefer flat group_* fields on habit_scores;
        # fall back to habitify by_group data if present
        group_data = {}
        for key, val in item.items():
            if key.startswith("group_") and isinstance(val, (int, float)):
                group_data[key.replace("group_", "")] = val
        if not group_data and date_str in habitify_by_date:
            group_data = habitify_by_date[date_str]

        day = {
            "date": date_str,
            "tier0_pct": t0_pct,
            "tier01_pct": t01_pct,
            "t0_done": t0_done,
            "t0_total": t0_total,
            "perfect": t0_pct == 100,
        }
        if group_data:
            day["groups"] = group_data
        history.append(day)

    # ── #422 EVR-03: cross-page daily-completion signals feed habit GROUP scores ──────
    # ONE signal per evidence page (habit_causality.CROSS_PAGE_SIGNALS), sourced from the
    # pre-computed component scores on computed_metrics. A cross-page signal only FILLS a
    # (date, group) the habit tracker left empty — a group the tracker already scored is
    # never touched (double-count prevention), and borrowed groups are tagged so a
    # cross-page fill is never rendered as a tracked score.
    cross_page_days = 0
    try:
        cp_resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(f"{USER_PREFIX}computed_metrics")
                    & Key("sk").between(f"DATE#{ninety_days_ago}", f"DATE#{today}"),
                    "ScanIndexForward": True,
                }
            )
        )
        cross_signals_by_date = {}
        for cm in _decimal_to_float(cp_resp.get("Items", [])):
            cm_date = cm.get("date") or cm.get("sk", "").replace("DATE#", "")
            sig = habit_causality.derive_cross_page_signals(cm.get("component_scores") or {})
            if sig:
                cross_signals_by_date[cm_date] = sig
        if cross_signals_by_date:
            tracker_by_date = {d["date"]: dict(d.get("groups") or {}) for d in history}
            merged = habit_causality.merge_cross_page_group_scores(tracker_by_date, cross_signals_by_date)
            for day in history:
                m = merged.get(day["date"])
                if not m:
                    continue
                if m["groups"]:
                    day["groups"] = m["groups"]
                if m["cross_page"]:
                    day["groups_cross_page"] = m["cross_page"]  # provenance: which groups were borrowed
                    cross_page_days += 1
    except Exception as _cp_e:
        logger.warning("[handle_habits] cross-page merge failed (non-fatal): %s", _cp_e)

    # Latest record for current streak
    history[-1] if history else {}
    latest_streak = 0
    if items:
        last_item = _decimal_to_float(items[-1])
        latest_streak = int(last_item.get("t0_perfect_streak") or last_item.get("t0_aggregate_streak") or 0)

    # ── Day-of-week analysis (0=Mon ... 6=Sun)
    dow_sums = [0.0] * 7
    dow_counts = [0] * 7
    for day in history:
        try:
            d = datetime.strptime(day["date"], "%Y-%m-%d")
            dow = d.weekday()  # 0=Mon ... 6=Sun
            dow_sums[dow] += day.get("tier0_pct", 0) or 0
            dow_counts[dow] += 1
        except Exception:
            pass
    dow_avgs = [round(dow_sums[i] / dow_counts[i]) if dow_counts[i] else None for i in range(7)]
    valid_dow = [(i, v) for i, v in enumerate(dow_avgs) if v is not None]
    best_dow = max(valid_dow, key=lambda x: x[1])[0] if valid_dow else None
    worst_dow = min(valid_dow, key=lambda x: x[1])[0] if valid_dow else None

    # ── 90-day per-group averages + keystone identification
    group_90d_sums: dict = {}
    group_90d_counts: dict = {}
    for day in history:
        for gname, gpct in (day.get("groups") or {}).items():
            if isinstance(gpct, (int, float)):
                group_90d_sums[gname] = group_90d_sums.get(gname, 0) + gpct
                group_90d_counts[gname] = group_90d_counts.get(gname, 0) + 1
    group_90d_avgs = {g: round(group_90d_sums[g] / group_90d_counts[g]) for g in group_90d_sums if group_90d_counts.get(g, 0) > 0}
    keystone_group = max(group_90d_avgs, key=group_90d_avgs.get) if group_90d_avgs else None
    keystone_group_pct = group_90d_avgs.get(keystone_group) if keystone_group else None

    # ── HAB-3: Pearson correlation per habit group vs character score ──────────
    keystone_correlations = []
    try:
        import math as _math

        # Fetch character_sheet records for same window
        cs_pk = f"{USER_PREFIX}character_sheet"
        cs_resp = table.query(
            **with_phase_filter(
                {  # ADR-058: hide pilot character sheets
                    "KeyConditionExpression": Key("pk").eq(cs_pk) & Key("sk").between(f"DATE#{ninety_days_ago}", f"DATE#{today}"),
                    "ScanIndexForward": True,
                }
            )
        )
        cs_items = _decimal_to_float(cs_resp.get("Items", []))

        # Build date → pillar sum (character health proxy)
        PILLARS_CS = [
            "pillar_sleep",
            "pillar_movement",
            "pillar_nutrition",
            "pillar_metabolic",
            "pillar_mind",
            "pillar_relationships",
            "pillar_consistency",
        ]
        char_by_date = {}
        for ci in cs_items:
            cs_date = ci.get("date") or ci.get("sk", "").replace("DATE#", "")
            psum = 0.0
            for pkey in PILLARS_CS:
                pdata = ci.get(pkey) or {}
                if isinstance(pdata, dict):
                    ls = pdata.get("level_score")
                    if ls is not None:
                        psum += float(ls)
            if psum > 0:
                char_by_date[cs_date] = psum

        # For each group, collect matched (char_score, group_pct) pairs
        group_series: dict = {}
        for day in history:
            d = day.get("date")
            if d not in char_by_date:
                continue
            # Staleness honesty (truth audit 2026-07-10): a day where NOTHING was
            # logged (every group pct 0 and zero tier-0 completions) is an absence,
            # not an observation — including those days inflated n (26 vs ~12) past
            # the n>=14 gate on a correlation that had no behavioral variance in it.
            _day_groups = day.get("groups") or {}
            _all_zero = _day_groups and all((not isinstance(v, (int, float))) or v == 0 for v in _day_groups.values())
            if _all_zero and not day.get("t0_done"):
                continue
            cs_score = char_by_date[d]
            for gname, gpct in (day.get("groups") or {}).items():
                if isinstance(gpct, (int, float)):
                    if gname not in group_series:
                        group_series[gname] = []
                    group_series[gname].append((float(gpct), cs_score))

        # Pearson r helper
        def _pearson(pairs):
            n = len(pairs)
            if n < 5:
                return None
            xs = [p[0] for p in pairs]
            ys = [p[1] for p in pairs]
            mx = sum(xs) / n
            my = sum(ys) / n
            num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
            dx = _math.sqrt(sum((x - mx) ** 2 for x in xs))
            dy = _math.sqrt(sum((y - my) ** 2 for y in ys))
            if dx == 0 or dy == 0:
                return None
            return round(num / (dx * dy), 3)

        corr_list = []
        for gname, pairs in group_series.items():
            r = _pearson(pairs)
            if r is not None:
                corr_list.append(
                    {
                        "group": gname,
                        "correlation_r": r,
                        "avg_pct": group_90d_avgs.get(gname),
                        "n_days": len(pairs),
                    }
                )
        corr_list.sort(key=lambda x: abs(x["correlation_r"]), reverse=True)
        keystone_correlations = corr_list[:5]
    except Exception as _hc_e:
        logger.warning("[handle_habits] keystone_correlations failed (non-fatal): %s", _hc_e)

    # #1107 — the 30-day dot-strip window, GENESIS-CLAMPED (ADR-077 / #1133 doctrine):
    # _experiment_date floors the start at EXPERIMENT_START, so on genesis day the strip
    # is honestly 1 day long — pre-cycle days are clamped out entirely, never rendered
    # as unlabeled prior-cycle history.
    strip_start = _experiment_date(29)  # 29 back + today = a 30-day window, max
    strip_dates = []
    try:
        _sd = datetime.strptime(strip_start, "%Y-%m-%d")
        _ed = datetime.strptime(today, "%Y-%m-%d")
        while _sd <= _ed:
            strip_dates.append(_sd.strftime("%Y-%m-%d"))
            _sd += timedelta(days=1)
    except ValueError:
        logger.warning("[handle_habits] dot-strip window parse failed (non-fatal): %s..%s", strip_start, today)

    # P0.5 — per-habit state taxonomy inputs: window adherence + a state label.
    per_habit = []
    for hname, a in sorted(_habit_agg.items(), key=lambda kv: -(kv[1]["completed"] / kv[1]["scheduled"] if kv[1]["scheduled"] else -1)):
        sched, comp = a["scheduled"], a["completed"]
        pct = round(comp / sched * 100) if sched else None
        if comp == 0:
            state = "backlog"
        elif pct >= 85:
            state = "automatic"
        elif pct >= 60:
            state = "holding"
        else:
            state = "needs_attention"
        ph = {
            "name": hname,
            "group": a["group"],
            "scheduled_days": sched,
            "completed_days": comp,
            "adherence_pct": pct,
            "state": state,
            "last_completed": a.get("last_completed"),
            # #1107: the 30-day (genesis-clamped) day-by-day strip. Status per date:
            # done / missed / off (not scheduled) / absent (no data captured that day).
            "days": [{"date": _ds, "status": _habit_days.get(hname, {}).get(_ds, "absent")} for _ds in strip_dates],
        }
        # #422: attach captured causality (drivers + why-missed, both channels). Only
        # present when a real note/reflection exists — the cell stays honestly empty
        # otherwise (no inferred causes, ADR-104).
        cz = _causality.get(hname)
        if cz and (cz.get("trigger") or cz.get("reward") or cz.get("why_missed") or cz.get("context")):
            ph["causality"] = _causality_public(cz)
        per_habit.append(ph)

    causality_captured = sum(
        1 for v in _causality.values() if v.get("trigger") or v.get("reward") or v.get("why_missed") or v.get("context")
    )

    return _ok(
        {
            "as_of_date": today,
            "days_tracked": len(history),
            "current_streak": latest_streak,
            "per_habit": per_habit,
            # #1107: the dot-strip window served explicitly so the front-end can say
            # WHY a strip is short (genesis-clamped) instead of padding it.
            "days_window": {"start": strip_start, "end": today, "n_days": len(strip_dates)},
            "history": history,
            "day_of_week_avgs": dow_avgs,
            "best_day": best_dow,
            "worst_day": worst_dow,
            "group_90d_avgs": group_90d_avgs,
            "keystone_group": keystone_group,
            "keystone_group_pct": keystone_group_pct,
            # HAB-3: top 5 habit groups by |Pearson r| vs character score
            "keystone_correlations": keystone_correlations,
            # #422 EVR-01/02/03: causality capture surface + cross-page provenance.
            "causality_captured": causality_captured,
            "cross_page_days": cross_page_days,
            "cross_page_signals": {p: s["group"] for p, s in habit_causality.CROSS_PAGE_SIGNALS.items()},
        },
        cache_seconds=3600,
    )


def habit_registry(*, _g) -> dict:
    """GET /api/habit_registry — the habits being tracked, grouped.

    Source of truth is Habitify (USER#…#SOURCE#habitify, latest DATE# record):
    its ``habit_statuses`` map carries every scheduled habit with its area/group
    and periodicity. We surface that list grouped by area so the public habits
    page shows "everything I'm trying to do" even right after an experiment reset
    (when the PROFILE#v1 registry and the phase-scoped habit_scores are empty).

    Blocked vice/habit names (porn, marijuana, …) are stripped server-side via
    ``_is_blocked_vice`` — content_filter.json's ``habit_data`` rule — so they
    never reach the client even though Habitify tracks them.
    """
    # Facade state injected via `_g` (the delegator's globals()) — same module the test patched.
    _habits_from_habitify = _g["_habits_from_habitify"]
    table = _g["table"]
    try:
        habits = _habits_from_habitify()
        source = "habitify"
        if not habits:
            # Fallback: legacy PROFILE#v1 registry (pre-Habitify-sourcing).
            resp = table.get_item(Key={"pk": f"USER#{USER_ID}", "sk": "PROFILE#v1"})
            registry = resp.get("Item", {}).get("habit_registry", {})
            for name, meta in registry.items():
                if _is_blocked_vice(name):
                    continue
                h = {"name": name, "group": meta.get("group") if isinstance(meta, dict) else None}
                if isinstance(meta, dict):
                    for k, v in meta.items():
                        h[k] = float(v) if isinstance(v, Decimal) else v
                habits.append(h)
            source = "profile"

        # Stable group ordering: known P40-ish groups first, then alpha, "Other" last.
        seen, groups = set(), []
        for h in habits:
            g = h.get("group") or "Other"
            if g not in seen:
                seen.add(g)
                groups.append(g)
        groups.sort(key=lambda g: (g == "Other", g.lower()))
        habits.sort(key=lambda x: ((x.get("group") or "Other") == "Other", (x.get("group") or "Other").lower(), x.get("name", "").lower()))
        # P1.1 — auto-derived taxonomy (time-of-day / type / logical group), labeled derived.
        for h in habits:
            h["taxonomy"] = _derive_habit_taxonomy(h.get("name", ""))
        return _ok(
            {"habits": habits, "groups": groups, "count": len(habits), "source": source, "taxonomy_derived": True},
            cache_seconds=3600,
        )
    except Exception as e:
        logger.error(f"[habit_registry] Error: {e}")
        return _error(500, "Failed to load habit registry")


def _derive_habit_taxonomy(name: str) -> dict:
    """P1.1 — deterministic, name-only inference of a habit's context.

    Re-derives time-of-day, type (do/avoid/maintain) and a logical group from the
    habit *name* (Habitify's stored area is storage, not logic). Heuristic + n=1:
    always returned under ``derived: True`` and labeled "auto-derived" on the surface,
    never presented as fact. No causal claims — this only classifies, it does not score.
    """
    n = f" {(name or '').lower().strip()} "
    time_of_day = "anytime"
    for label, keys in _TAX_TIME:
        if any(k in n for k in keys):
            time_of_day = label
            break
    if any(k in n for k in _TAX_AVOID):
        htype = "avoid"
    elif any(k in n for k in _TAX_MAINTAIN):
        htype = "maintain"
    else:
        htype = "do"
    group = None
    for g, keys in _TAX_GROUP_HINTS:
        if any(k in n for k in keys):
            group = g
            break
    return {"time_of_day": time_of_day, "type": htype, "group": group, "derived": True}
