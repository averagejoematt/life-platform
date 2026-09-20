"""owner_redlines.py — what Matthew is signing up for, and what makes the coach pull back (#3753).

WHY THIS EXISTS

On 2026-09-13, after a week of using cycle 17, the owner said the plans felt too
conservative: he is attempting an aggressive transformation, he has done one before, and
he wants the platform to back that with science rather than substitute its own risk
tolerance for his.

He was reading something real. The conservatism is not emergent — it is a written design
decision from June. `PROVEN_BLUEPRINT.md` §"Where the science improves" instructs the
coach to run a SLOWER rate than the prior cut ("3.5 lb/wk is above the platform's own
muscle-loss rate flag"), on the well-evidenced thesis that his failure mode is holding,
not losing: 16 loss episodes since 2012, zero that held, regain at 0.79x the speed of
loss. That thesis is good. But it was the PLATFORM's ruling, carried silently in prose
that every plan inherits, and the client never signed it.

So the posture becomes a file he edits. Two sections, and the distinction is the whole
point:

  REDLINES  — what the plan must PURSUE. His instruction to the coach.
  TRIPWIRES — what makes the coach pull back. The conditions HE accepts as reasons to
              ease off, chosen in advance, in the calm — not improvised mid-cut by a
              model weighing his health against his stated goal on its own authority.

An aggressive plan with named tripwires is safer than a conservative plan with none,
because the conservative one hides its own thresholds and nobody can audit them.

WHY THIS FILE AND NOT config/

`config/*.json` is not staged into the Lambda bundle, so a repo-side edit is inert at
runtime (#3675, #3671). The #3717 attestation module took the same route for the same
reason: a declaration that must reach the planner ships in code.

ADR-105: every threshold below carries its `provenance`. "owner" means he chose the
number. "population-derived" means it came from literature, not from his own variance,
and it says so at the point of use — a threshold whose origin is unstated is the class of
defect the rigor bar exists to prevent.

STATUS: NOT YET ACTIVE. `ACTIVE = False` until the owner has read and edited this file.
An unconfirmed redline must not steer a prescription — the same posture #3717 took, and
for the same reason. `plan_engine` reports the redlines as PROPOSED while this is False.
"""

from __future__ import annotations

from typing import Any

ACTIVE = False
"""Flip to True only when the owner has reviewed the values below. gate:owner (#3753)."""

REDLINES_VERSION = "2.0-proposed"
"""v1 (2026-09-13) was drafted from the owner's recorded statements. v2 (2026-09-20) is the
red-teamed proposal: five independent personas (transformation coach, obesity-medicine physician,
performance dietitian, strength & conditioning coach, lived experience) argued from one evidence
packet compiled from the platform's own record, at the owner's 3 lb/wk ask. The record is
`RED_TEAM_RECORD`; the plan is TRAINING_PROGRAM.md v0.2 in the same owner-private home. Still
PROPOSED: nothing below is his instruction until he approves v0.2 and flips ACTIVE."""

RED_TEAM_RECORD = "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM_v0.2_redteam.md"

CHANGELOG_V1_TO_V2: list[str] = [
    "rate: the 0.5–1.0 %BW band is kept as the envelope; a scheduled absolute target replaces the unresolved "
    "'top of band vs widen' question — 3.0 lb/wk (cap 3.5) above 295 lb, then 2.5 / 2.0 / 1.5 stepping at 260 / 230 "
    "/ 200 lb, and a mandatory 12-week maintenance block at 200 (all five personas; Forbes 2000; Alpert 2005)",
    "energy: a NEW floor — 1,700 kcal any day, 1,800 on a lifting day, prescribed 2,000–2,300; the measured 1,533 "
    "kcal/day was the biggest problem in the record, too LOW (four of five personas; Longland 2016; Lichtman 1992)",
    "protein: the 180 g floor stays; a 200 g target, ≥6 of 7 days, 4 feedings of ~50 g is added (Helms 2014; Areta 2013)",
    "lifting: 2–3 sessions/wk → 5–6 on a 5-week load wave with 10–16 sets/muscle (strength + transformation coach; "
    "Schoenfeld 2016/2017; Murphy & Koehler 2022) — the 2–3 rule guarded a burnout failure mode he has never had",
    "walking: the 8.5 h floor is now PERMANENT (survives the cut), target 12–15 h at ≤105 bpm; walking collapse is the " "relapse prodrome",
    "medical cover: a NEW redline — baseline labs/ECG/gallbladder ultrasound/DXA/RMR, DXA every 8–12 weeks (physician)",
    "tripwires: anchor-lift drop 10% → 7.5% and the action now changes the DIET (+200 kcal) as well as holding load; "
    "readiness floor 34 → 40 (34 is Whoop's boundary, too late to be early); protein-missed action moves to the "
    "kitchen; nine NEW tripwires added that the engine does not yet evaluate (each says so)",
]

LAST_REVIEWED_BY_OWNER: str | None = None
"""ISO date the owner last read this file. None means never."""


# ── What the plan must pursue ────────────────────────────────────────────────
REDLINES: dict[str, dict[str, Any]] = {
    "rate_band_pct_bw_per_wk": {
        "low": 0.5,
        "high": 1.0,
        "provenance": "owner",
        "stated": "2026-09-07",
        "note": (
            "From his own platform-memory record of 2026-09-07: 'maximum sustainable fat loss with lean mass "
            "preserved… defensible rate window ~0.5-1.0% bodyweight/wk'. v2 keeps this as the ENVELOPE; the "
            "instruction is the scheduled absolute target in `rate_schedule_lb_wk` below — 3 lb/wk is 0.95 %BW/wk "
            "at 317 lb (inside the band) and would be 1.3 %BW/wk at 230 lb (outside it), which is why it steps."
        ),
        "owner_to_resolve": None,
        "resolution": (
            "RESOLVED as a schedule (red team 2026-09-20): hold the window's top while above 295 lb, then step "
            "the absolute target down so the %BW never rises as the fat reserve shrinks. Not 'widen the window'. "
            "Pending the owner's approval of v0.2."
        ),
    },
    "rate_schedule_lb_wk": {
        "steps": [
            {"above_lb": 295, "target": 3.0, "cap": 3.5},
            {"above_lb": 260, "target": 2.5, "cap": 3.0},
            {"above_lb": 230, "target": 2.0, "cap": 2.5},
            {"above_lb": 200, "target": 1.5, "cap": 2.0},
            {"above_lb": 0, "target": 0.0, "cap": 0.0, "note": "12-week maintenance block at 200 lb; decide about 185 from there"},
        ],
        "overshoot_rule": "trend >cap for 2 consecutive weeks after week 4 → +250 kcal/day; overshoot is a failure, not a win",
        "provenance": "population-derived",
        "derived_by": "red-team consensus 2026-09-20 (owner target 3 lb/wk; Forbes 2000; Alpert 2005 working assumption)",
        "stated": "2026-09-20",
        "note": (
            "All five personas put the first step between 295 and 260 lb and end below 1.0 %BW/wk by 220 lb; two "
            "land him at 200 for a mandatory maintenance block (Dulloo 1997: overshoot scales with the fat deficit). "
            "The 14-day weigh-in average is the number; single days are noise."
        ),
    },
    "energy_floor_kcal": {
        "floor_any_day": 1700,
        "floor_lifting_day": 1800,
        "prescribed": [2000, 2300],
        "provenance": "population-derived",
        "derived_by": "red-team consensus 2026-09-20 (three independent TDEE derivations; Longland 2016; Lichtman 1992)",
        "stated": "2026-09-20",
        "note": (
            "Three independent TDEE derivations landed at 3,300–4,000 kcal (Mifflin RMR ~2,350 + measured 12.4 h/wk "
            "walking/cycling + 7 lifts; the platform's 5,241 is inflated and may not be cited). A 3 lb/wk deficit is "
            "~1,500 kcal/day, so intake near 2,000–2,300 — the measured 1,533 (very likely under-reported, Lichtman "
            "1992) was ~500 below what the rate itself needs, and is where lean mass goes. Hold intake roughly flat as "
            "he lightens; the rate then tapers by arithmetic. Re-derive from the 14-day trend every 4 weeks."
        ),
    },
    "protein_floor_g": {
        "value": 180,
        "target_g": 200,
        "days_of_7": 6,
        "feedings": 4,
        "provenance": "owner",
        "stated": "2026-09-07",
        "note": (
            "'Protein is the #1 preservation lever — 180 g/day target, currently under-hitting.' v2: 180 g is the FLOOR, "
            "200 g the target, on ≥6 of 7 days, in 4 feedings of ~50 g ≥3 h apart with one inside 2 h of the morning "
            "block (Helms 2014, g/kg FFM; Longland 2016; Areta 2013). Measured 146 g mean with ≥180 g on 3 of 14 days "
            "was an arithmetic impossibility at 1,533 kcal (47% of intake); at 2,200 kcal, 200 g is 36% — ordinary."
        ),
    },
    "walking_floor_hr_wk": {
        "value": 8.5,
        "target_hr_wk": [12, 15],
        "hr_ceiling_bpm": 105,  # drift-ok: a heart-rate ceiling in bpm, not a budget ceiling (ADR-133 scanner false-positive)
        "permanent": True,
        "provenance": "owner-history",
        "stated": "2026-06-19",
        "note": (
            "PROVEN_BLUEPRINT's by-band table: at 300-309 lb during the campaign that worked he was walking ~10x/wk, "
            "~8.5 hrs/wk, from day one. The blueprint calls walking 'the single most replicable, highest-confidence "
            "driver in the dataset'. Owner correction 2026-09-19: the planner's Strava-only read (5.09 hr/wk) undercounts — "
            "treadmill and cycling blocks logged inside Hevy count too; 13–19 Sep measured >=8.79 hr, at or above the floor. "
            "Apple Health steps are NOT a walking proxy. v2: the floor is PERMANENT and survives the cut ending — walking "
            "is the energy-flux engine and his documented relapse tell (11.4 → 4.4 walks/wk within 8 weeks of the 2025 "
            "trough), not the lean-mass-retention engine; ~90% of it at his own 97 bpm average."
        ),
    },
    "lifting_sessions_per_wk": {
        "low": 5,
        "high": 6,
        "sets_per_muscle_wk": [10, 16],
        "load_wave": "5-week blocks: wk1-3 3-4x6 @ 75-80% e1RM, wk4 top double @ RIR 2 re-mints e1RM, wk5 deload half the sets",
        "accessory_rule": "6-8 accessories fixed for the whole 5-week block; rotate only at block boundaries",
        "provenance": "population-derived",
        "derived_by": "red-team consensus 2026-09-20 (supersedes the owner's 2026-09-07 '2-3x/wk' pending his approval)",
        "stated": "2026-09-20",
        "note": (
            "The 2–3 sessions rule was a bandwidth-preservation rule for people whose failure mode is training burnout; "
            "his documented failure mode is not that (both reversals were grief, not training). He runs 7 sessions at "
            "GREEN with safe ACWR. Cutting to 2–3 removes the retention stimulus at exactly the rate he is losing. Six "
            "days on a 5-week wave, 10–16 hard sets/muscle (MEV–MAV in a deficit, never MRV — Murphy & Koehler 2022), "
            "legs and standing core fed (28-day: quads 8.5, hams 8.5, glutes 6.8, core 2 vs chest 17, triceps 21). Loads "
            "held flat from 260 to 190 lb last time was not maintenance — it was the leak nobody could see."
        ),
    },
    "load_anchoring": {
        "value": "bodyweight-band-matched history, discounted for detraining",
        "detraining_discount_pct": [10, 15],
        "entry_pct_of_band_best": [85, 90],
        "provenance": "owner",
        "stated": "2026-09-08",
        "note": (
            "'Prescribe strength loads against BODYWEIGHT-BAND-MATCHED history, not recent history… TWO axes: (1) "
            "matched bodyweight band tells you what his frame handled, (2) weeks since last consistent block tells you "
            "what his connective tissue is ready for NOW. Matching on weight alone will over-prescribe.' Observed "
            "discount that was correct in practice: ~10-15% under last performed after a ~10 week layoff. v2 adds the "
            "entry rule (85–90% of the band best) and keeps the carry-forward floor and subtract-only authoring (§7.1–7.2)."
        ),
    },
    "run_gate_lb": {
        "value": 240,
        "provenance": "owner-history",
        "stated": "2026-06-19",
        "note": "ZERO runs logged above 240 lb across his whole history; running appears at 240 and scales down-weight. Joint-gated from his own data, not a generic caution.",
    },
    "medical_cover": {
        "baseline": [
            "CMP (K, Mg, phosphate, creatinine, LFTs)",
            "CBC",
            "lipids",
            "HbA1c",
            "fasting insulin",
            "TSH",
            "testosterone total+free, SHBG",
            "ferritin, B12, folate, 25-OH-D",
            "uric acid",
            "CK",
            "hs-CRP",
            "12-lead ECG with QTc",
            "gallbladder ultrasound",
            "DXA",
            "RMR by indirect calorimetry",
            "PHQ-9",
        ],
        "dxa_every_weeks": [8, 12],
        "electrolytes_weeks": [2, 4, 6, "then monthly"],
        "provenance": "population-derived",
        "stated": "2026-09-20",
        "note": (
            "From the physician persona: the v1 draft had no lab, electrolyte, ECG, gallbladder or mood instrument in it — "
            "at BMI 46.8 with a ~1,500 kcal deficit that is the omission that matters. DXA is the one instrument that "
            "answers his actual question (did I keep the muscle). Gallstone prophylaxis at >1.5 %BW/wk is a conversation "
            "for his physician (Broomfield 1988; Shiffman 1995). Whether any supervision exists is not on the record."
        ),
    },
}


# ── What makes the coach pull back ───────────────────────────────────────────
# Every entry: the signal, the threshold, where the threshold came from, and what the
# coach DOES. "Pull back" is never "stop" unless it says so — a tripwire that can only
# halt everything is one he will learn to ignore. `evaluated_by_engine: False` marks a v2
# tripwire that plan_engine does not yet compute — it is REPORTED so the owner can see the
# whole posture, and it says so wherever it appears (ADR-105: silence is not clearance).
TRIPWIRES: list[dict[str, Any]] = [
    {
        "id": "anchor_lift_strength_drop",
        "signal": "top-set load on an anchor movement, vs the trailing best at this bodyweight band",
        "threshold_pct": 7.5,
        "consecutive_sessions": 2,
        "provenance": "population-derived",
        "action": (
            "hold all anchor loads flat for one block; protein compliance to 6 of 7; +200 kcal/day; surface a diet-break "
            "decision — never lower the load automatically"
        ),
        "note": (
            "Strength held flat through a 118 lb loss last time and the blueprint calls that 'decent muscle defense'. "
            "A sustained drop is the earliest honest signal that the rate is outrunning recovery. v2: 7.5% (was 10%) "
            "and the action changes the DIET, not just the load — holding load treats the symptom. The strength coach's "
            "target derivation is a 3-session rolling-median e1RM ≥7.5% below the trailing 4-week median on ≥2 of 3 "
            "anchors; the engine still computes the simpler top-set drop until that is wired. Day-to-day e1RM noise in a "
            "trained lifter is ~4–5% (from practice, not a citation) — NOT computed from his own variance; the engine must "
            "say so wherever it fires (ADR-105) and re-derive it once cycle 17 has enough anchor-lift data."
        ),
    },
    {
        "id": "protein_floor_missed",
        "signal": "days below the protein floor in the trailing 7",
        "threshold_days": 3,
        "provenance": "owner",
        "action": (
            "the next 7 days are a kitchen intervention (pre-portioned protein); training does not grow that week and "
            "the rate is not 'earned' — the consequence lands in the kitchen, not only on the gym"
        ),
        "note": (
            "His own stated #1 preservation lever. Missing it is the mechanism by which an aggressive rate costs muscle "
            "rather than fat. v2 (dietitian): 'plan does not grow' alone punished the gym for a kitchen failure."
        ),
    },
    {
        "id": "readiness_floor",
        "signal": "Whoop recovery",
        "threshold": 40,
        "consecutive_days": 3,
        "provenance": "population-derived",
        "action": (
            "cardio −25%, lifting volume held; the deficit is halved for 7 days if two of the five sustainability "
            "channels are also degraded; intervals come off; the easy session stays easy"
        ),
        "note": (
            "v1 used 34 — Whoop's own red/yellow boundary, a vendor threshold, not his — and the transformation coach "
            "called it too late to be an early warning. 40 on 3 of 7 days is still population-derived; the multi-day "
            "form is the one that means something. Re-derive from his own recovery distribution once cycle 17 has it."
        ),
    },
    {
        "id": "pain_flag_named_site",
        "signal": "a pain flag on a named joint/tendon in the derived note layer",
        "threshold": "any",
        "provenance": "owner",
        "action": (
            "that movement pattern is substituted for 2 weeks (the muscle's volume kept via a pain-free variant), not "
            "loaded, until he says otherwise; two substitutions on the same site in 8 weeks → a human, not a program tweak"
        ),
        "note": (
            "The pain lexicon is over-inclusive by design and the flag is a question, not a verdict. NOTE (#3768): this "
            "tripwire reads a layer that was dark from the day it shipped until 2026-09-13 — so it could not have "
            "fired. The engine reports this tripwire's own layer_status rather than its silence."
        ),
    },
    {
        "id": "weight_stall_with_adherence",
        "signal": "trailing 14d weight trend flat or up WHILE intake and training adherence are on plan",
        "threshold_days": 14,
        "provenance": "owner-history",
        "action": "this is a diet-break / refeed decision, surfaced to him as a decision — never taken silently, never 'push harder'",
        "note": (
            "The prior campaign ran flat-out with no planned landing and reversed. A stall that is NOT explained by "
            "adherence is the moment the blueprint says to schedule a break rather than push harder. v2: an unaudited "
            "stall is a logging problem first (every 4th week is a gram-scale audit week)."
        ),
    },
    # ── v2 additions — reported, not yet evaluated by plan_engine ──────────────
    {
        "id": "intake_floor_breached",
        "signal": "days below the energy floor (1,700 kcal; 1,800 on a lifting day) in the trailing 7",
        "threshold_days": 2,
        "provenance": "population-derived",
        "action": "+250 kcal/day as protein + fruit for 7 days; the aggressive phase pauses until corrected",
        "evaluated_by_engine": False,
        "note": "Physician + dietitian: the 1,078 kcal day in the record is a violation, not a good day.",
    },
    {
        "id": "rate_overshoot",
        "signal": "14-day weight trend rate above the schedule's cap for 2 consecutive weeks, after week 4",
        "threshold_weeks": 2,
        "provenance": "population-derived",
        "action": "+250 kcal/day; overshoot is a failure, not a win",
        "evaluated_by_engine": False,
        "note": "Transformation coach + physician, independently.",
    },
    {
        "id": "walking_collapse",
        "signal": "walking+cycling hours down >30% week-over-week, or two skipped evening walks in one week",
        "threshold_pct": 30,
        "provenance": "owner-history",
        "action": "mandatory human contact and a mode review — this is the relapse prodrome, not a rest day",
        "evaluated_by_engine": False,
        "note": (
            "11.4 → 4.4 walks/wk inside 8 weeks of the 2025 trough preceded the regain. Three personas wrote this "
            "tripwire without seeing each other; the lived-experience persona called it the single highest-value "
            "tripwire in the plan. The engine already computes weekly walking hours (walking-volume@1.0.0); the "
            "week-over-week comparison is the wiring to add."
        ),
    },
    {
        "id": "logging_dark",
        "signal": "consecutive days with no food log",
        "threshold_days": 2,
        "provenance": "owner-history",
        "action": "a check-in, not a scolding — read as an early mood signal",
        "evaluated_by_engine": False,
        "note": "Lived experience: logging goes dark before the walks do.",
    },
    {
        "id": "abstinence_violation_spiral",
        "signal": "a day over target followed by a skipped next-morning weigh-in, or a bad day not followed by a normal day within 24 h",
        "threshold": "any",
        "provenance": "owner-history",
        "action": "escalate; the recovery window is one day, always — the next morning's weigh-in is the rule that breaks the spiral",
        "evaluated_by_engine": False,
        "note": "'One 4,000 kcal night never made anyone fat. Eleven days of I'll-restart-Monday did. Sixteen times.'",
    },
    {
        "id": "volume_ceiling",
        "signal": "hard sets per muscle per week, or working sets in one 50-minute lift slot",
        "threshold": {"sets_per_muscle_wk": 18, "sets_per_slot": 20},
        "provenance": "population-derived",
        "action": "the plan does not grow next week — MRV is lower in a deficit and he can overshoot it without feeling it",
        "evaluated_by_engine": False,
        "note": "Strength coach; the 28-day per-muscle sets are already computed, the per-slot count is not.",
    },
    {
        "id": "medical_stop_lines",
        "signal": "K <3.5 · Mg <1.7 · phosphate <2.5 · QTc >470 ms · uric acid >9 or gout · ALT >3x ULN · creatinine +0.3 · FFM >25% of loss on a DXA interval · RMR >15% below FFM-predicted · RUQ pain, palpitations, syncope",
        "threshold": "any",
        "provenance": "population-derived",
        "action": "same-day medical contact; deficit to zero until cleared; FFM >25% of loss → deficit −500 kcal/day immediately",
        "evaluated_by_engine": False,
        "note": "Physician persona. The platform has a labs partition; the cadence and the thresholds are not wired to it.",
    },
    {
        "id": "mood_declared",
        "signal": "PHQ-9 ≥15, any positive item 9, or he declares it himself",
        "threshold": "any",
        "provenance": "owner-history",
        "action": (
            "the Minimum Viable Week fires — maintenance, not abandonment: protein floor, one 20-minute walk and a weigh-in "
            "make a GREEN day; the coach may not push rate during a declared event and may not let him disappear"
        ),
        "evaluated_by_engine": False,
        "note": (
            "Both major reversals were bereavement/depression, not training. Two in fourteen years is the base rate, not "
            "the exception. Written now because it cannot be written on the day."
        ),
    },
    {
        "id": "self_added_volume",
        "signal": "training above the prescription two weeks running",
        "threshold_weeks": 2,
        "provenance": "owner-history",
        "action": "read as an anxiety tell, not enthusiasm; subtract-only enforced and mood asked about by name",
        "evaluated_by_engine": False,
        "note": "Lived experience: 'the 21-hour week is not his strength, it is his hiding place.'",
    },
]


def engine_evaluated_tripwires() -> list[dict[str, Any]]:
    """The tripwires plan_engine computes today (the v1 five)."""
    return [t for t in TRIPWIRES if t.get("evaluated_by_engine", True)]


def unevaluated_tripwires() -> list[str]:
    """v2 tripwires that are reported but not yet computed — named, never silent (ADR-105)."""
    return [t["id"] for t in TRIPWIRES if not t.get("evaluated_by_engine", True)]


def summary() -> dict[str, Any]:
    """The block the planner embeds — never a bare number without its provenance."""
    return {
        "active": ACTIVE,
        "version": REDLINES_VERSION,
        "last_reviewed_by_owner": LAST_REVIEWED_BY_OWNER,
        "status_note": (
            "PROPOSED — v2, red-teamed 2026-09-20 from the owner's own record at his 3 lb/wk ask, not yet approved by "
            "him. Reported so the plan is auditable; not treated as his instruction until ACTIVE is True (#3753, gate:owner)."
            if not ACTIVE
            else f"ACTIVE — owner-reviewed {LAST_REVIEWED_BY_OWNER} (v{REDLINES_VERSION})."
        ),
        "red_team_record": RED_TEAM_RECORD,
        "redlines": REDLINES,
        "tripwires": TRIPWIRES,
        "unresolved": [k for k, v in REDLINES.items() if v.get("owner_to_resolve")],
        "population_derived_thresholds": [t["id"] for t in TRIPWIRES if t.get("provenance") == "population-derived"],
        "unevaluated_tripwires": unevaluated_tripwires(),
        "changelog_v1_to_v2": CHANGELOG_V1_TO_V2,
    }


def rate_schedule_step(weight_lb: float) -> dict[str, Any]:
    """The scheduled step for a bodyweight — the first step whose `above_lb` the weight exceeds."""
    for step in REDLINES["rate_schedule_lb_wk"]["steps"]:
        if weight_lb > step["above_lb"]:
            return step
    return REDLINES["rate_schedule_lb_wk"]["steps"][-1]


def rate_target_lb_per_wk(weight_lb: float | None) -> dict[str, Any] | None:
    """The rate at a given bodyweight: the %BW envelope in pounds AND the scheduled absolute target."""
    if not weight_lb:
        return None
    band = REDLINES["rate_band_pct_bw_per_wk"]
    step = rate_schedule_step(weight_lb)
    return {
        "low_lb_wk": round(weight_lb * band["low"] / 100, 1),
        "high_lb_wk": round(weight_lb * band["high"] / 100, 1),
        "target_lb_wk": step["target"],
        "cap_lb_wk": step["cap"],
        "target_pct_bw_wk": round(step["target"] / weight_lb * 100, 2) if weight_lb else None,
        "schedule_step_above_lb": step["above_lb"],
        "provenance": band["provenance"],
        "schedule_provenance": REDLINES["rate_schedule_lb_wk"]["provenance"],
        "stated": band["stated"],
        "owner_to_resolve": band.get("owner_to_resolve"),
        "resolution": band.get("resolution"),
    }
