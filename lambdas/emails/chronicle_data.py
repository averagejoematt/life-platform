"""lambdas/emails/chronicle_data.py — the weekly data gather + narrative-ready
packet builder, split out of wednesday_chronicle_lambda.py (#1654). Reads the
facade's live (monkeypatchable) module state via the `_g` hand-off; does NOT
import the facade (no import cycle)."""

from datetime import datetime, timedelta, timezone

from ai_context import build_experiment_phase_context, format_experiment_phase_context
from constants import EXPERIMENT_BASELINE_WEIGHT_LBS
from digest_utils import d2f, safe_float
from phase_filter import singleton_visible


def gather_chronicle_data(*, _g):
    """Gather all data Elena needs for this week's installment."""
    query_range = _g["query_range"]
    query_range_list = _g["query_range_list"]
    fetch_profile = _g["fetch_profile"]
    table = _g["table"]
    USER_ID = _g["USER_ID"]
    EXPERIMENT_START_DATE = _g["EXPERIMENT_START_DATE"]
    logger = _g["logger"]
    today = datetime.now(timezone.utc).date()
    end = (today - timedelta(days=1)).isoformat()  # yesterday
    start = (today - timedelta(days=7)).isoformat()  # 7 days back
    weight_start = (today - timedelta(days=30)).isoformat()

    profile = fetch_profile()
    if not profile:
        logger.error("No profile found")
        return None

    logger.info(f"Gathering data: {start} -> {end}")

    # --- Core biometrics ---
    whoop = query_range("whoop", start, end)
    eightsleep = query_range("eightsleep", start, end)
    garmin = query_range("garmin", start, end)
    strava = query_range("strava", start, end)
    withings = query_range("withings", weight_start, end)
    macrofactor = query_range("macrofactor", start, end)
    apple_health = query_range("apple_health", start, end)

    # --- Journal entries (the soul of each installment) ---
    # Journal entries use SK pattern: DATE#YYYY-MM-DD#journal#template#uuid
    journal_entries = query_range_list("notion", start, end)
    # Filter to only journal entries (not other notion records)
    journal_entries = [e for e in journal_entries if "#journal#" in e.get("sk", "")]
    logger.info(f"Journal entries: {len(journal_entries)}")

    # --- Day grades + habit scores ---
    day_grades = query_range("day_grade", start, end)
    habit_scores = query_range("habit_scores", start, end)

    # --- Habits raw (for specific habit names) ---
    habitify = query_range("habitify", start, end)

    # --- State of Mind ---
    # SoM daily aggregates (som_avg_valence, som_top_labels/associations) live on
    # the apple_health partition; keep only days that carry a SoM aggregate.
    state_of_mind = {d: rec for d, rec in query_range("apple_health", start, end).items() if rec.get("som_avg_valence") is not None}

    # --- Supplements ---
    supplements = query_range("supplements", start, end)

    # --- Active experiments ---
    experiments = []
    try:
        # ADR-058: phase=pilot hidden by default.
        from phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                    "ExpressionAttributeValues": {
                        ":pk": f"USER#{USER_ID}#SOURCE#experiments",
                        ":prefix": "EXP#",
                    },
                }
            )
        )
        for item in resp.get("Items", []):
            exp = d2f(item)
            if exp.get("status") == "active":
                experiments.append(exp)
    except Exception as e:
        logger.warning(f"Experiments query: {e}")

    # --- Anomaly events ---
    anomalies = query_range("anomalies", start, end)

    # --- Weather (for setting/atmosphere) ---
    weather = query_range("weather", start, end)

    # --- Character Sheet (gamification layer — narrative hooks for Elena) ---
    character_sheet = query_range("character_sheet", start, end)
    logger.info(f"Character sheet records: {len(character_sheet)}")

    # --- Previous 4 installments (for continuity) ---
    prev_installments = []
    try:
        # ADR-058: phase=pilot hidden by default.
        from phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": "pk = :pk AND begins_with(sk, :prefix)",
                    "ExpressionAttributeValues": {
                        ":pk": f"USER#{USER_ID}#SOURCE#chronicle",
                        ":prefix": "DATE#",
                    },
                    "ScanIndexForward": False,
                    # Read past the phase=pilot dormant records (which with_phase_filter drops)
                    # to reach the low-SK re-dated origin lead-ins, so the genuine prior
                    # installments feed continuity instead of being missed (2026-06-21).
                    "Limit": 25,
                }
            )
        )
        prev_installments = [d2f(i) for i in resp.get("Items", [])]
        logger.info(f"Previous installments: {len(prev_installments)}")
    except Exception as e:
        logger.warning(f"Previous installments: {e}")

    # --- Field Notes (current week's AI analysis + Matthew response) ---
    field_notes = None
    try:
        iso_year, iso_week, _ = today.isocalendar()
        current_week = f"{iso_year}-W{iso_week:02d}"
        fn_resp = table.get_item(
            Key={
                "pk": f"USER#{USER_ID}#SOURCE#field_notes",
                "sk": f"WEEK#{current_week}",
            }
        )
        fn_item = d2f(fn_resp.get("Item"))
        if fn_item and fn_item.get("ai_present"):
            field_notes = {
                "week": current_week,
                "ai_tone": fn_item.get("ai_tone", "mixed"),
                "ai_present": fn_item.get("ai_present", "")[:500],
                "has_matthew_response": bool(fn_item.get("matthew_agreement")),
                "matthew_agreement": (fn_item.get("matthew_agreement") or "")[:300],
            }
            logger.info(
                f"Field notes for {current_week}: tone={field_notes['ai_tone']}, matthew_responded={field_notes['has_matthew_response']}"
            )
    except Exception as e:
        logger.warning(f"Field notes query: {e}")

    # --- Narrative arc + experiment arc (the cross-week throughline) — for the
    # "previously on" recap. Both are already-summarized prose artifacts (never raw
    # vitals), so they ground a recap without re-introducing the fabrication frontier.
    narrative_arc = None
    experiment_arc = None
    arc_pk = "NARRATIVE#arc"  # platform singleton partition (not a USER#…#SOURCE# source)
    ai_pk = f"USER#{USER_ID}#SOURCE#ai_analysis"
    try:
        # #946: get_item bypasses the phase filter — hide a tombstoned arc, and
        # (since NARRATIVE#arc reuses `phase` for its NARRATIVE phase, the generic
        # singleton_visible check can't apply) an arc entered before the current
        # genesis: it's the previous cycle's story, not this recap's throughline.
        _arc_raw = d2f(table.get_item(Key={"pk": arc_pk, "sk": "STATE#current"}).get("Item") or {})
        if _arc_raw and not _arc_raw.get("tombstone") and str(_arc_raw.get("entered_date") or "") >= EXPERIMENT_START_DATE:
            narrative_arc = _arc_raw
    except Exception as e:
        logger.warning(f"Narrative arc query: {e}")
    try:
        _exp_arc_raw = table.get_item(Key={"pk": ai_pk, "sk": "EXPERT#experiment_arc"}).get("Item")
        if singleton_visible(_exp_arc_raw):  # #946: honest-null while tombstoned from a reset
            experiment_arc = d2f(_exp_arc_raw) or None
    except Exception as e:
        logger.warning(f"Experiment arc query: {e}")

    return {
        "whoop": whoop,
        "eightsleep": eightsleep,
        "garmin": garmin,
        "strava": strava,
        "withings": withings,
        "macrofactor": macrofactor,
        "apple_health": apple_health,
        "journal_entries": journal_entries,
        "day_grades": day_grades,
        "habit_scores": habit_scores,
        "habitify": habitify,
        "state_of_mind": state_of_mind,
        "supplements": supplements,
        "experiments": experiments,
        "anomalies": anomalies,
        "weather": weather,
        "character_sheet": character_sheet,
        "prev_installments": prev_installments,
        "narrative_arc": narrative_arc,
        "experiment_arc": experiment_arc,
        "profile": profile,
        "field_notes": field_notes,
        "dates": {"start": start, "end": end},
    }


def build_calendar_facts(start, end, genesis=None):
    """Deterministic date→weekday map for the covered window + genesis (#1220).

    Every weekday is computed from `datetime`, so it is always correct — never a
    hardcoded map. Returns a CALENDAR grounding block (empty string on bad dates).
    """
    try:
        d0 = datetime.strptime(start, "%Y-%m-%d")
        d1 = datetime.strptime(end, "%Y-%m-%d")
    except (ValueError, TypeError):
        return ""
    days = {}
    cur = d0
    while cur <= d1:
        days[cur.strftime("%Y-%m-%d")] = cur
        cur += timedelta(days=1)
    if genesis:
        try:
            days.setdefault(genesis, datetime.strptime(genesis, "%Y-%m-%d"))
        except (ValueError, TypeError):
            genesis = None
    lines = ["=== CALENDAR (deterministic weekdays — cite these EXACT day-of-week labels; never guess a day of week) ==="]
    for ds in sorted(days):
        tag = " (experiment genesis)" if genesis and ds == genesis else ""
        lines.append(f"- {ds} was a {days[ds].strftime('%A')}{tag}")
    return "\n".join(lines)


def build_data_packet(data):
    """Transform raw data into a narrative-ready packet for Elena."""
    profile = data["profile"]
    dates = data["dates"]
    packet = []

    packet.append("=== THE MEASURED LIFE — WEEKLY DATA PACKET ===")
    packet.append(f"Week ending: {dates['end']}")

    # --- Week number + phase context (#1086) ---
    # The ONE shared experiment-phase block replaces this surface's own week
    # math: same genesis anchor, identical week arithmetic (d days after
    # genesis → d//7 + 1 for both), plus the pre-start state, the audience
    # descriptor, and the cannot-exist-yet guardrail every narrative surface
    # now carries. Anchored to the week-ENDING date, not "today".
    pctx = build_experiment_phase_context(profile, dates["end"])
    journey_start = pctx["start_date"]
    # A pre-genesis lead-in still labels/publishes as week 1 — week_num feeds
    # filenames and DDB keys downstream, never the narrative clock (the phase
    # block + the TIMELINE guard below own that).
    week_num = pctx["week_num"] or 1
    packet.append(format_experiment_phase_context(pctx))

    # Week number is anchored to the experiment GENESIS (journey_start) — never the count of
    # installments. Pre-genesis "prologue" lead-ins (dated before genesis) are backstory and must
    # NOT inflate the experiment week or imply the weight loss / training spans more weeks than the
    # experiment has actually run (this caused the "9 lbs in three weeks" error on 2026-06-21, when
    # the experiment was one week old). Continuity (don't re-open cold) is handled by feeding Elena
    # the prior installments as context — not by bumping the week number.
    def _inst_date(p):
        return str(p.get("date") or p.get("sk", "")).replace("DATE#", "")

    prologue = [p for p in data.get("prev_installments", []) if _inst_date(p) and _inst_date(p) < journey_start]
    packet.append(f"Week number: {week_num}")
    packet.append(f"Journey start (experiment genesis): {journey_start}")

    # --- Deterministic weekday calendar (#1220) ---
    # A weekday paired with a date is a mechanically checkable fact; the grounding
    # gate never verified it, so the cycle-6 draft called 2026-07-13 a "Sunday"
    # (it was a Monday — stale cycle-5 genesis leak). Feed Elena the CORRECT
    # day-of-week for every date in the covered window + the genesis, computed
    # from datetime so it is always right, not a hardcoded map.
    cal_facts = build_calendar_facts(dates.get("start"), dates.get("end"), genesis=journey_start)
    if cal_facts:
        packet.append(cal_facts)
    if prologue:
        packet.append(
            f"TIMELINE — CRITICAL: {len(prologue)} earlier installment(s) are PRE-GENESIS PROLOGUE "
            f"(backstory dated before the {journey_start} genesis). They are NOT experiment weeks. "
            f"This is experiment WEEK {week_num}; the measured experiment is {week_num} week(s) old. "
            f"NEVER describe the experiment, the weight loss, the training load, or any streak as "
            f"spanning more weeks than that. Draw on the prologue for continuity and backstory, but "
            f"the measured clock — and any 'in N weeks' framing — starts at genesis."
        )
    # Matthew-specific fallback defaults; only used if profile fetch fails
    packet.append(f"Journey start weight: {profile.get('journey_start_weight_lbs', EXPERIMENT_BASELINE_WEIGHT_LBS)} lbs")
    packet.append(f"Goal weight: {profile.get('goal_weight_lbs', 185)} lbs")
    packet.append(f"Age: {profile.get('age', 37)}")
    packet.append("")

    # --- Weight story ---
    packet.append("=== WEIGHT ===")
    weights = []
    for d in sorted(data["withings"].keys()):
        w = safe_float(data["withings"][d], "weight_lbs")
        if w:
            weights.append((d, w))
    if weights:
        latest = weights[-1]
        packet.append(f"Current: {latest[1]:.1f} lbs ({latest[0]})")
        if len(weights) >= 2:
            earliest_7d = [w for w in weights if w[0] >= dates["start"]]
            if earliest_7d:
                delta = latest[1] - earliest_7d[0][1]
                packet.append(f"Week change: {delta:+.1f} lbs")
        journey_start_w = profile.get("journey_start_weight_lbs", EXPERIMENT_BASELINE_WEIGHT_LBS)  # Matthew-specific fallback
        total_lost = journey_start_w - latest[1]
        packet.append(f"Total journey loss: {total_lost:.1f} lbs")
    packet.append("")

    # --- Recovery & physiology ---
    packet.append("=== RECOVERY & PHYSIOLOGY ===")
    # Temporal frame for the narrator: each dated line is the reading FOR that
    # morning, produced by the night before — recovery/HRV set that day UP; they
    # are not something Matthew "did" on it. Reference them as "the night of"/"the
    # morning of", never as same-day activity.
    packet.append("(Frame: each line is that morning's reading, reflecting the prior night — it sets the day up.)")
    for d in sorted(data["whoop"].keys()):
        rec = data["whoop"][d]
        hrv = safe_float(rec, "hrv")
        recovery = safe_float(rec, "recovery_score")
        rhr = safe_float(rec, "resting_heart_rate")
        strain = safe_float(rec, "strain")
        parts = [f"{d}:"]
        if recovery is not None:
            parts.append(f"Recovery {recovery:.0f}%")
        if hrv is not None:
            parts.append(f"HRV {hrv:.0f}ms")
        if rhr is not None:
            parts.append(f"RHR {rhr:.0f}")
        if strain is not None:
            parts.append(f"Strain {strain:.1f}")
        packet.append(" | ".join(parts))
    packet.append("")

    # --- Sleep (Whoop — SOT for duration, stages, score — captures all sleep) ---
    packet.append("=== SLEEP (Whoop — source of truth) ===")
    # Wake-date keyed: a line dated D is the sleep of the night of D-1 → morning D.
    packet.append("(Frame: a line dated D is the night of D-1 into the morning of D — last night's sleep.)")
    for d in sorted(data["whoop"].keys()):
        rec = data["whoop"][d]
        score = safe_float(rec, "sleep_quality_score")
        dur = safe_float(rec, "sleep_duration_hours")
        eff = safe_float(rec, "sleep_efficiency_percentage")
        rem_h = safe_float(rec, "rem_sleep_hours")
        deep_h = safe_float(rec, "slow_wave_sleep_hours")
        deep_pct = round(deep_h / dur * 100, 0) if deep_h and dur and dur > 0 else None
        rem_pct = round(rem_h / dur * 100, 0) if rem_h and dur and dur > 0 else None
        parts = [f"{d}:"]
        if score is not None:
            parts.append(f"Score {score:.0f}")
        if dur is not None:
            parts.append(f"{dur:.1f}h")
        if eff is not None:
            parts.append(f"Eff {eff:.0f}%")
        if deep_pct is not None:
            parts.append(f"Deep {deep_pct:.0f}%")
        if rem_pct is not None:
            parts.append(f"REM {rem_pct:.0f}%")
        packet.append(" | ".join(parts))
    packet.append("")

    # --- Sleep Restlessness (Eight Sleep tosses/turns) ---
    # Bed/room temperature retired (ADR-118, #489): the Eight Sleep temperature
    # pipeline is dead (dead /v2/intervals endpoint, no temp field 4+ months).
    # Tosses/turns is still a live field, so keep it.
    packet.append("=== SLEEP RESTLESSNESS (Eight Sleep) ===")
    for d in sorted(data["eightsleep"].keys()):
        rec = data["eightsleep"][d]
        toss = safe_float(rec, "toss_and_turns") or safe_float(rec, "toss_turn_count")
        if toss is not None:
            packet.append(f"{d}: Tosses {toss:.0f}")
    packet.append("")

    # --- Training / Strava activities ---
    packet.append("=== TRAINING ===")
    for d in sorted(data["strava"].keys()):
        rec = data["strava"][d]
        activities = rec.get("activities", [])
        for a in activities:
            name = a.get("name", "Activity")
            sport = a.get("sport_type", "?")
            dur_min = round(safe_float(a, "moving_time_seconds", 0) / 60)
            dist_m = safe_float(a, "distance_meters", 0)
            dist_mi = round(dist_m / 1609.34, 2) if dist_m else 0
            avg_hr = safe_float(a, "average_heartrate")
            elev = safe_float(a, "total_elevation_gain_feet")
            start = a.get("start_date_local", "")
            time_part = start.split("T")[1][:5] if "T" in str(start) else ""
            line = f"{d} {time_part}: {name} ({sport}, {dur_min}min"
            if dist_mi > 0:
                line += f", {dist_mi}mi"
            if avg_hr:
                line += f", HR {avg_hr:.0f}"
            if elev and elev > 100:
                line += f", {elev:.0f}ft gain"
            line += ")"
            packet.append(line)
    if not any(data["strava"].values()):
        packet.append("No activities recorded this week.")
    packet.append("")

    # --- Day grades ---
    packet.append("=== DAY GRADES ===")
    for d in sorted(data["day_grades"].keys()):
        rec = data["day_grades"][d]
        score = safe_float(rec, "total_score")
        grade = rec.get("letter_grade", "?")
        packet.append(f"{d}: {score:.0f}/100 ({grade})")
    packet.append("")

    # --- Habit scores (tier performance) ---
    packet.append("=== HABIT PERFORMANCE ===")
    for d in sorted(data["habit_scores"].keys()):
        rec = data["habit_scores"][d]
        t0_done = rec.get("tier0_done", 0)
        t0_total = rec.get("tier0_total", 0)
        t1_done = rec.get("tier1_done", 0)
        t1_total = rec.get("tier1_total", 0)
        vices_held = rec.get("vices_held", 0)
        vices_total = rec.get("vices_total", 0)
        missed = rec.get("missed_tier0", [])
        line = f"{d}: T0 {t0_done}/{t0_total}, T1 {t1_done}/{t1_total}, Vices {vices_held}/{vices_total}"
        if missed:
            line += f" | MISSED T0: {', '.join(missed[:3])}"
        packet.append(line)
    packet.append("")

    # --- Nutrition overview ---
    packet.append("=== NUTRITION ===")
    for d in sorted(data["macrofactor"].keys()):
        rec = data["macrofactor"][d]
        cal = safe_float(rec, "total_calories_kcal")
        prot = safe_float(rec, "total_protein_g")
        if cal:
            packet.append(f"{d}: {cal:.0f} cal, {prot:.0f}g protein")
    packet.append(f"Targets: {profile.get('calorie_target', 1800)} cal, {profile.get('protein_target_g', 190)}g protein")
    packet.append("")

    # --- Journal entries (DEEP BACKGROUND — never quote directly) ---
    packet.append("=== JOURNAL (OFF THE RECORD — never quote directly) ===")
    for entry in sorted(data["journal_entries"], key=lambda e: e.get("sk", "")):
        template = entry.get("template", "?")
        date = entry.get("date", entry.get("sk", "").split("#")[1] if "#" in entry.get("sk", "") else "?")
        raw = entry.get("raw_text", "")
        mood = entry.get("enriched_mood")
        energy = entry.get("enriched_energy")
        stress = entry.get("enriched_stress")
        themes = entry.get("enriched_themes", [])
        emotions = entry.get("enriched_emotions", [])
        cognitive = entry.get("enriched_cognitive_patterns", [])
        avoidance = entry.get("enriched_avoidance_flags")  # J-3 (#503): plural list, not singular
        social = entry.get("enriched_social_quality")
        ownership = entry.get("enriched_ownership")  # J-3 (#503): _level variant never written

        packet.append(f"--- {date} ({template}) ---")
        if raw:
            # Include full text — Elena needs the emotional texture
            packet.append(f"Text: {raw[:1500]}")
        signals = []
        if mood is not None:
            signals.append(f"Mood:{mood}/5")
        if energy is not None:
            signals.append(f"Energy:{energy}/5")
        if stress is not None:
            signals.append(f"Stress:{stress}/5")
        if themes:
            signals.append(f"Themes: {', '.join(themes[:4])}")
        if emotions:
            signals.append(f"Emotions: {', '.join(emotions[:5])}")
        if cognitive:
            signals.append(f"Cognitive: {', '.join(cognitive[:3])}")
        if avoidance:
            signals.append(f"AVOIDANCE FLAGS: {', '.join(str(a) for a in avoidance)}")
        if social:
            signals.append(f"Social: {social}")
        if ownership:
            signals.append(f"Ownership: {ownership}")
        if signals:
            packet.append("Signals: " + " | ".join(signals))
        packet.append("")
    if not data["journal_entries"]:
        packet.append("No journal entries this week.")
    packet.append("")

    # --- State of Mind ---
    # Aggregate fields are prefixed som_* on the apple_health record; top labels /
    # associations are already comma-joined strings, not lists.
    packet.append("=== STATE OF MIND (How We Feel) ===")
    _som_days = sorted(data["state_of_mind"].keys())
    if not _som_days:
        packet.append("No State of Mind check-ins this week.")
    for d in _som_days:
        rec = data["state_of_mind"][d]
        valence = safe_float(rec, "som_avg_valence")
        if valence is None:
            continue
        labels = rec.get("som_top_labels") or ""
        areas = rec.get("som_top_associations") or ""
        parts = [f"{d}: valence {valence:.2f}"]
        if labels:
            parts.append(f"emotions: {labels}")
        if areas:
            parts.append(f"areas: {areas}")
        packet.append(" | ".join(parts))
    packet.append("")

    # --- Active experiments ---
    if data["experiments"]:
        packet.append("=== ACTIVE EXPERIMENTS ===")
        for exp in data["experiments"]:
            name = exp.get("name", "?")
            hypothesis = exp.get("hypothesis", "")
            start_d = exp.get("start_date", "?")
            days = exp.get("days_active", "?")
            packet.append(f"- {name} (started {start_d}, {days} days active)")
            if hypothesis:
                packet.append(f"  Hypothesis: {hypothesis}")
        packet.append("")

    # --- Anomalies ---
    anomaly_events = [a for a in data["anomalies"].values() if a.get("severity") in ("moderate", "high")]
    if anomaly_events:
        packet.append("=== ANOMALY EVENTS ===")
        for a in anomaly_events:
            d = a.get("date", "?")
            sev = a.get("severity", "?")
            metrics = a.get("anomalous_metrics", [])
            hyp = a.get("hypothesis", "")
            labels = [m.get("label", "?") for m in metrics]
            packet.append(f"{d}: {sev} — {', '.join(labels)}")
            if hyp:
                packet.append(f"  Hypothesis: {hyp}")
        packet.append("")

    # --- Weather (for setting/atmosphere) ---
    packet.append("=== WEATHER (Seattle) ===")
    for d in sorted(data["weather"].keys()):
        rec = data["weather"][d]
        temp = safe_float(rec, "temp_avg_f")
        precip = safe_float(rec, "precipitation_mm")
        daylight = safe_float(rec, "daylight_hours")
        parts = [d]
        if temp is not None:
            parts.append(f"{temp:.0f}°F")
        if precip is not None:
            parts.append(f"{'Rain' if precip > 0.5 else 'Dry'}")
        if daylight is not None:
            parts.append(f"{daylight:.1f}h daylight")
        packet.append(" | ".join(parts))
    packet.append("")

    # --- Supplements taken ---
    supp_names = set()
    for d, rec in data["supplements"].items():
        for s in rec.get("supplements", []):
            supp_names.add(s.get("name", "?"))
    if supp_names:
        packet.append(f"=== SUPPLEMENT STACK: {', '.join(sorted(supp_names))} ===")
        packet.append("")

    # --- Character Sheet (gamification arc — narrative gold for Elena) ---
    cs_data = data.get("character_sheet", {})
    if cs_data:
        packet.append("=== CHARACTER SHEET (RPG gamification layer) ===")
        packet.append("The Character Sheet is Matthew's persistent gamified life score — an RPG-style")
        packet.append("Character Level (1-100) built from 7 weighted pillars. Tier transitions and")
        packet.append("level changes are RARE (2-4 per month) and narratively significant.")
        packet.append("")
        # Show progression across the week (first day vs last day)
        sorted_dates = sorted(cs_data.keys())
        if sorted_dates:
            latest_cs = cs_data[sorted_dates[-1]]
            earliest_cs = cs_data[sorted_dates[0]] if len(sorted_dates) > 1 else latest_cs
            lvl = latest_cs.get("character_level", 1)
            tier = latest_cs.get("character_tier", "Foundation")
            tier_emoji = latest_cs.get("character_tier_emoji", "\U0001f528")
            xp = latest_cs.get("character_xp", 0)
            prev_lvl = earliest_cs.get("character_level", 1)
            delta = lvl - prev_lvl
            delta_str = f" ({'+' if delta > 0 else ''}{delta} this week)" if delta != 0 else " (stable)"
            packet.append(f"Overall: Level {lvl} {tier_emoji} {tier}{delta_str} | XP: {xp}")
            packet.append("")

            # Pillar breakdown (latest day)
            pillar_names = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
            pillar_labels = {
                "sleep": "\U0001f634 Sleep",
                "movement": "\U0001f3cb\ufe0f Movement",
                "nutrition": "\U0001f957 Nutrition",
                "metabolic": "\U0001f4ca Metabolic",
                "mind": "\U0001f9e0 Mind",
                "relationships": "\U0001f4ac Relationships",
                "consistency": "\U0001f3af Consistency",
            }
            for pn in pillar_names:
                pd = latest_cs.get(f"pillar_{pn}") or {}
                ep = earliest_cs.get(f"pillar_{pn}") or {}
                p_lvl = pd.get("level", 1)
                p_tier = pd.get("tier", "Foundation")
                p_raw = pd.get("raw_score")
                prev_p_lvl = ep.get("level", 1)
                p_delta = p_lvl - prev_p_lvl
                p_delta_str = f" ({'+' if p_delta > 0 else ''}{p_delta})" if p_delta != 0 else ""
                raw_str = f" (raw: {p_raw:.0f})" if p_raw is not None else ""
                packet.append(f"  {pillar_labels.get(pn, pn)}: Level {p_lvl} ({p_tier}){p_delta_str}{raw_str}")
            packet.append("")

            # Level events (THE NARRATIVE HOOKS)
            all_events = []
            for d in sorted_dates:
                events = cs_data[d].get("level_events", [])
                for ev in events:
                    all_events.append((d, ev))
            if all_events:
                packet.append("LEVEL EVENTS THIS WEEK (these are story moments):")
                for d, ev in all_events:
                    pillar = ev.get("pillar", "?")
                    etype = ev.get("event_type", "?")
                    old_lvl = ev.get("old_level", "?")
                    new_lvl = ev.get("new_level", "?")
                    old_tier = ev.get("old_tier")
                    new_tier = ev.get("new_tier")
                    if old_tier and new_tier and old_tier != new_tier:
                        packet.append(f"  {d}: {pillar} TIER CHANGE: {old_tier} \u2192 {new_tier} (Level {old_lvl} \u2192 {new_lvl})")
                    else:
                        packet.append(f"  {d}: {pillar} {etype}: Level {old_lvl} \u2192 {new_lvl}")
            else:
                packet.append("No level events this week. Stable is fine — it means no flip-flopping.")
            packet.append("")

            # Active effects (cross-pillar interactions)
            effects = latest_cs.get("active_effects", [])
            if effects:
                packet.append("ACTIVE EFFECTS (cross-pillar buffs/debuffs):")
                for eff in effects:
                    packet.append(f"  {eff.get('emoji', '')} {eff.get('name', '?')}: {eff.get('description', '')}")
                packet.append("")

        packet.append("NOTE FOR ELENA: Tier transitions are Chronicle-worthy moments. A pillar")
        packet.append("crossing from Momentum to Discipline means sustained behavioral change.")
        packet.append("Level events are rare by design — each one represents 5+ days of consistent")
        packet.append("improvement. Use these as narrative anchors when they occur.")
        packet.append("")

    # --- Field Notes cross-reference ---
    fn = data.get("field_notes")
    if fn and fn.get("ai_present"):
        packet.append("=== FIELD NOTES THIS WEEK ===")
        packet.append(f"AI tone: {fn.get('ai_tone', 'mixed')}")
        packet.append(f"AI preview: {fn.get('ai_present', '')[:300]}")
        if fn.get("has_matthew_response") and fn.get("matthew_agreement"):
            packet.append(f"Matthew's agreement: {fn['matthew_agreement'][:200]}")
        packet.append("NOTE FOR ELENA: If the Field Notes raise a theme worth weaving into")
        packet.append("this week's narrative, include a brief reference. This connects the")
        packet.append("AI advisor's weekly analysis with your storytelling.")
        packet.append("")

    return "\n".join(packet), week_num


def _load_engagement_signal(*, _g):
    """#914: the presence / quiet-stretch state (engagement_state STATE#current,
    written by adaptive_mode via engagement_core). Fail-soft → {}. The pure
    rendering + acknowledgment logic lives in engagement_core; only this read is
    local (the callers-pass-the-read contract)."""
    table = _g["table"]
    USER_PREFIX = _g["USER_PREFIX"]
    logger = _g["logger"]
    try:
        resp = table.get_item(Key={"pk": USER_PREFIX + "engagement_state", "sk": "STATE#current"})
        return resp.get("Item") or {}
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"engagement signal read failed: {e}")
        return {}
