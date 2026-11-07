"""lambdas/emails/chronicle_data.py — the weekly data gather + narrative-ready
packet builder, split out of wednesday_chronicle_lambda.py (#1654). Reads the
facade's live (monkeypatchable) module state via the `_g` hand-off; does NOT
import the facade (no import cycle).

THE PACKET IS A PUBLIC GENERATOR'S INPUT (owner rulings 2026-11-03 and 2026-11-05). Whatever enters
it can reach a published installment, its excerpt, the RSS feed, the share kit, the recap and the
Panel episode. So journal activity never enters it: the gather does not read the journal partition
or the State of Mind check-ins (both PRIVATE in ``common.narrative_provenance``), the habit block
names and counts only habits ``common.activity_publication`` classifies PUBLIC (the journal habits
are private activity), and the presence block is the engagement record's PUBLIC projection — the
one /api/presence serves. Private data stays stored for the owner's own tools; it is not read here.
``tests/test_chronicle_journal_invariance.py`` holds the packet byte-identical when only journal
inputs vary, with a mutation control that proves the check can fail."""

import re
from datetime import datetime, timedelta

from ai.ai_context import build_experiment_phase_context, format_experiment_phase_context
from common import activity_publication  # owner ruling 2026-11-05: only PUBLIC habits reach the public packet
from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS, PLAN_DAILY_PROTEIN_MIN_G
from common.digest_utils import d2f, safe_float
from common.pacific_time import pacific_now  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days
from experiment.phase_filter import singleton_visible
from health import character_privacy  # owner rulings 2026-11-03/04: the chronicle is public — private-source pillars held
from health.calorie_target import target_phrase  # #5095: the ONE calorie target
from privacy import diary_consent  # #1483 (ADR-142 tier 2): the conversation-allude projection + prompt block

# ── #2422: model-authored prose must not widen the grounding allow-list ───────
# The anomaly detector's "hypothesis" is Haiku-WRITTEN text persisted on the
# anomalies partition. The packet used to inline it bare, so the chronicle's
# number/date allow-list (derived from the whole packet by
# chronicle_prompt.installment_grounding_findings) treated it as SOURCE
# material — a figure the model invented upstream would GROUND the same figure
# in reader text (laundering: model text grounding other model text). These
# fence markers mark any model-authored span in the packet;
# installment_grounding_findings strips fenced spans before deriving the
# allow-list, so Elena still SEES the hypothesis as context but its numbers and
# dates cannot ground anything. The anomaly's MEASURED fields (value, baseline,
# z — the detector's deterministic statistics) are emitted as separate plain
# lines and remain groundable. The markers deliberately contain no digits.
MODEL_CONJECTURE_OPEN = "<<model-conjecture (AI-written, not measured data — never cite its numbers)>>"
MODEL_CONJECTURE_CLOSE = "<<end model-conjecture>>"
_MODEL_CONJECTURE_RE = re.compile(re.escape(MODEL_CONJECTURE_OPEN) + r".*?" + re.escape(MODEL_CONJECTURE_CLOSE), re.DOTALL)


def mark_model_conjecture(text):
    """Fence a model-authored string so allow-list derivation can strip it.

    Any marker text already present inside the span is removed first, so a
    (model-authored) payload can never close the fence early and leak its tail
    into the allow-list."""
    clean = (text or "").replace(MODEL_CONJECTURE_OPEN, "").replace(MODEL_CONJECTURE_CLOSE, "")
    return f"{MODEL_CONJECTURE_OPEN} {clean} {MODEL_CONJECTURE_CLOSE}"


def strip_model_conjecture(text):
    """Remove every fenced model-conjecture span (the allow-list derivation path)."""
    return _MODEL_CONJECTURE_RE.sub("", text or "")


def gather_chronicle_data(*, _g):
    """Gather all data Elena needs for this week's installment."""
    query_range = _g["query_range"]
    fetch_profile = _g["fetch_profile"]
    table = _g["table"]
    USER_ID = _g["USER_ID"]
    EXPERIMENT_START_DATE = _g["EXPERIMENT_START_DATE"]
    logger = _g["logger"]
    today = pacific_now().date()
    end = (today - timedelta(days=1)).isoformat()  # yesterday
    start = (today - timedelta(days=7)).isoformat()  # 7 days back
    weight_start = (today - timedelta(days=30)).isoformat()

    profile = fetch_profile()
    if not profile:
        logger.error("No profile found")
        return None

    logger.info(f"Gathering data: {start} -> {end}")

    # --- Core biometrics ---
    # #3442: the injected query_range is digest_utils.query_range — day-rows-only,
    # so whoop's DATE#<d>#WORKOUT#<uuid> sub-records cannot clobber the day row here.
    whoop = query_range("whoop", start, end)
    eightsleep = query_range("eightsleep", start, end)
    garmin = query_range("garmin", start, end)
    strava = query_range("strava", start, end)
    withings = query_range("withings", weight_start, end)
    macrofactor = query_range("macrofactor", start, end)
    apple_health = query_range("apple_health", start, end)

    # --- Journal: NOT READ (owner rulings 2026-11-03/05) ---
    # The chronicle is public; whether, when and what he writes in the journal is private. Neither
    # the journal partition (notion) nor the State of Mind check-ins are read for this packet.

    # --- Day grades + habit scores ---
    day_grades = query_range("day_grade", start, end)
    habit_scores = query_range("habit_scores", start, end)

    # --- Habits raw (for specific habit names) ---
    habitify = query_range("habitify", start, end)

    # --- Supplements ---
    supplements = query_range("supplements", start, end)

    # --- Active experiments ---
    experiments = []
    try:
        # ADR-058: phase=pilot hidden by default.
        from experiment.phase_filter import with_phase_filter

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
        from experiment.phase_filter import with_phase_filter

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

    # --- Conversation references (#1483, ADR-142 theme-referenceable tier) ---
    # Coach check-in conversations from the covered week, projected to SANCTIONED
    # fields ONLY (diary_consent.conversation_reference) BEFORE they enter the
    # gather: the verbatim CHECKIN#/LEARNING# text (Matthew-private, ADR-141)
    # never reaches the packet builder, so Elena cannot quote what she never saw
    # — she "wasn't in the room", structurally.
    conversation_refs = []
    try:
        from boto3.dynamodb.conditions import Key
        from coach import persona_registry
        from experiment.phase_filter import with_phase_filter

        for pid in persona_registry.OPERATIONAL_COACH_IDS:
            resp = table.query(
                **with_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq(f"COACH#{pid}") & Key("sk").begins_with("LEARNING#"),
                        "ScanIndexForward": False,
                        "Limit": 15,
                    }
                )
            )
            for it in resp.get("Items", []):
                if (it.get("channel") or "data") != "conversation":
                    continue
                ref = diary_consent.conversation_reference(d2f(it))
                if ref and start <= ref["date"] <= end:
                    conversation_refs.append(ref)
        logger.info(f"Conversation references (allude tier): {len(conversation_refs)}")
    except Exception as e:
        logger.warning(f"Conversation references gather: {e}")

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
        "day_grades": day_grades,
        "habit_scores": habit_scores,
        "habitify": habitify,
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
        "conversation_refs": conversation_refs,
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


def _week_statuses(data):
    """{habit name: its latest stored status in the window} — the identity the publication policy reads."""
    out = {}
    for d in sorted((data.get("habitify") or {}).keys()):
        for name, st in ((data["habitify"][d] or {}).get("habit_statuses") or {}).items():
            out[name] = st
    return out


def _non_public_habits(data):
    """Habit names the publication policy does not classify PUBLIC: any habit in the window's statuses
    that is not public (by its Habitify id), plus every registry habit the policy names private
    outright (the journal habits; an owner-declared private one). Decided by identity, never by words."""
    registry = (data.get("profile") or {}).get("habit_registry") or {}
    statuses = _week_statuses(data)
    names = {n for n, st in statuses.items() if not activity_publication.habit_is_public(n, st, registry.get(n))}
    for n, meta in registry.items():
        fam = activity_publication.habit_family(n, statuses.get(n), meta)
        if fam in ("journal_presence", activity_publication.OWNER_DECLARED_PRIVATE):
            names.add(n)
    return names, statuses, registry


def _tier(meta):
    try:
        return int((meta or {}).get("tier"))
    except (TypeError, ValueError):
        return None


def habit_performance_lines(data):
    """The HABIT PERFORMANCE lines over PUBLIC habits only (owner ruling 2026-11-05).

    A tier's done/total is printed only when no non-public habit sits in that tier (the stored counts
    include every habit, so a tier holding a journal habit would move with journal activity — its
    count is left out rather than recomputed). A missed habit is named only when the policy classifies
    it PUBLIC; an unclassified name is not printed (fail closed)."""
    private, statuses, registry = _non_public_habits(data)
    private_tiers = {_tier(registry.get(n)) for n in private}
    private_vice = any((statuses.get(n) or {}).get("group") == "Vice" for n in private)
    lines = []
    for d in sorted((data.get("habit_scores") or {}).keys()):
        rec = data["habit_scores"][d]
        parts = []
        if 0 not in private_tiers:
            parts.append(f"T0 {rec.get('tier0_done', 0)}/{rec.get('tier0_total', 0)}")
        if 1 not in private_tiers:
            parts.append(f"T1 {rec.get('tier1_done', 0)}/{rec.get('tier1_total', 0)}")
        if not private_vice:
            parts.append(f"Vices {rec.get('vices_held', 0)}/{rec.get('vices_total', 0)}")
        line = f"{d}: " + (", ".join(parts) or "habit counts not published")
        missed = [
            h
            for h in rec.get("missed_tier0", []) or []
            if h not in private and activity_publication.habit_is_public(h, statuses.get(h), registry.get(h))
        ]
        if missed:
            line += f" | MISSED T0: {', '.join(missed[:3])}"
        lines.append(line)
    return lines


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
        # #2177: a missing total_score is ADR-104 absence, not zero — a partial
        # day-grade record must degrade this one line, not crash the whole
        # weekly packet (and with it the Wednesday chronicle + Friday Panel
        # podcast, which reads this packet as its only input).
        if score is None:
            packet.append(f"{d}: no grade recorded")
            continue
        grade = rec.get("letter_grade", "?")
        packet.append(f"{d}: {score:.0f}/100 ({grade})")
    packet.append("")

    # --- Habit scores (tier performance) — PUBLIC habits only (owner ruling 2026-11-05) ---
    packet.append("=== HABIT PERFORMANCE ===")
    packet.extend(habit_performance_lines(data))
    packet.append("")

    # --- Nutrition overview ---
    packet.append("=== NUTRITION ===")
    for d in sorted(data["macrofactor"].keys()):
        rec = data["macrofactor"][d]
        cal = safe_float(rec, "total_calories_kcal")
        prot = safe_float(rec, "total_protein_g")
        if cal:
            # #2177: protein absent (ADR-104: absence, not zero) must not crash
            # a day that DID log calories — degrade that one clause honestly.
            prot_str = f"{prot:.0f}g protein" if prot is not None else "protein not logged"
            packet.append(f"{d}: {cal:.0f} cal, {prot_str}")
    packet.append(f"Targets: {target_phrase()}, {PLAN_DAILY_PROTEIN_MIN_G}g protein")
    packet.append("")

    # --- Journal: no block at all (owner rulings 2026-11-03/05) ---
    # Not its text, not its signals, not its presence or absence. A journal_entries key handed in by
    # an older caller is ignored; there is no "no entries" line, because a constant absence would
    # still be a statement about whether he writes.

    # --- Private conversations (#1483, ADR-142 tier 2 — allude only) ---
    # The block re-projects every item through diary_consent.conversation_reference,
    # so even a raw LEARNING# row handed in here renders as sanctioned fields only
    # (date, coarse theme, read delta). Empty week → no block at all.
    conv_block = diary_consent.conversation_prompt_block(data.get("conversation_refs") or [])
    if conv_block:
        packet.append(conv_block)
        packet.append("")

    # --- State of Mind: no block (owner rulings 2026-11-03/05) ---
    # The mood check-ins are a private self-report (``state_of_mind`` is PRIVATE in
    # common.narrative_provenance); neither their values nor their absence enter the public packet.

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
            # #2422: the MEASURED fields — the detector's deterministic statistics.
            # These are the groundable facts about the anomaly; before this, the only
            # numbers the packet carried for an anomaly lived inside the AI-written
            # hypothesis, which is exactly the text that must not ground anything.
            for m in metrics:
                val = safe_float(m, "yesterday_val")
                if val is None:
                    continue
                line = f"    {m.get('label', '?')}: {val:g}"
                mean = safe_float(m, "baseline_mean")
                if mean is not None:
                    line += f" (baseline {mean:g}"
                    z = safe_float(m, "z_score")
                    if z is not None:
                        line += f", z {z:g}"
                    line += ")"
                if m.get("direction"):
                    line += f" — {m['direction']}"
                packet.append(line)
            if hyp:
                # #2422: Haiku-authored — fenced so it cannot widen the allow-list.
                packet.append(f"  Hypothesis: {mark_model_conjecture(hyp)}")
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
    cs_data = {d: v for d, r in (data.get("character_sheet", {}) or {}).items() if (v := character_privacy.public_sheet(r))}
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
    local (the callers-pass-the-read contract).

    Owner ruling 2026-11-05: the chronicle is public, so it reads the record's PUBLIC projection
    (``engagement_core.PUBLIC_PROJECTION_KEY`` — the journal channel excluded, the same sub-record
    /api/presence serves), never the full record. A record without one steers nothing."""
    from content.engagement_core import PUBLIC_PROJECTION_KEY

    table = _g["table"]
    USER_PREFIX = _g["USER_PREFIX"]
    logger = _g["logger"]
    try:
        resp = table.get_item(Key={"pk": USER_PREFIX + "engagement_state", "sk": "STATE#current"})
        pub = (resp.get("Item") or {}).get(PUBLIC_PROJECTION_KEY)
        return pub if isinstance(pub, dict) else {}
    except Exception as e:  # pragma: no cover — defensive
        logger.warning(f"engagement signal read failed: {e}")
        return {}
