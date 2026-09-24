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
number. "owner-history" means it was mined from his own logged record. "population-derived"
means it came from literature or a persona's practice, not from his own variance, and it
says so at the point of use — a threshold whose origin is unstated is the class of defect
the rigor bar exists to prevent. `derived_by` names the red-team seat where one argued it.

STATUS: ACTIVE since 2026-09-21 — the owner approved v0.3 on #3753 ("yes i approve it",
~20:05 PT, after reading the plan). v1 (2026-09-13) was drafted from his recorded
statements; v2 (2026-09-20) was the first red team at his 3 lb/wk ask and was never
approved; v3 (2026-09-22 UTC) is the second red team on his CHANGED objective —
reproduce the 2024–25 velocity, engineer the landing — and is the one he signed. While
ACTIVE was False `plan_engine` reported the redlines as PROPOSED, the same posture #3717
took and for the same reason: an unconfirmed redline must not steer a prescription.
Every later edit to a threshold is a dated commit.
"""

from __future__ import annotations

from typing import Any

ACTIVE = True
"""True since 2026-09-21: the owner reviewed and approved v0.3 (#3753, gate:owner satisfied)."""

REDLINES_VERSION = "3.2"
"""v3 (2026-09-22 UTC / approved 2026-09-21 PT): six independent personas — transformation coach,
obesity-medicine physician, performance nutritionist, S&C coach, lived experience, and a blueprint
historian arguing only from his own 2024–25 data — ran blind on one evidence packet compiled from
the platform's own partitions (238 weigh-ins, 329 Hevy rows, 272 Strava days, a year of Whoop and
Eight Sleep, both DEXAs, the trough labs, the current 28-day block, and an energy-balance model
calibrated on that record). The record is `RED_TEAM_RECORD`; the plan is `TRAINING_PROGRAM_v0.3.md`
in the same owner-private home. Approved by the owner 2026-09-21 (#3753): from that date the values
below are his instruction to the coach.

v3.1 (2026-09-23, #4111): the owner overruled the `self_added_volume` tripwire's action — it no
longer reads training above prescription as an anxiety tell, enforces subtract-only, or asks about
mood; it is now an end-of-week report only. Nothing else in v3 changed.

v3.2 (2026-09-24, #4147): the owner switched the program to v0.4 Upper/Lower, order-based
(`DECISION#2026-09-24T03:10:59`). Two values move with it — `lifting_sessions_per_wk.structure`
and `sets_per_muscle_wk` [6, 10] -> [8, 12] (~10), which moves the `volume_ceiling` tripwire's
top with it — and the rep scheme gains v0.4's volume exposure (8–12). Every other v3/v3.1
redline is kept unchanged: protein, energy floor, walking floor, rate schedule, tripwires,
subtract-only authoring, band-matched anchoring, novel-again, the 10 % detraining discount."""

RED_TEAM_RECORD = "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM_v0.3_redteam.md"
PLAN = "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM_v0.4.md"  # #4147; written by the driver, owner-private
PLAN_V0_3 = "s3://matthew-life-platform/config/coaching/TRAINING_PROGRAM_v0.3.md"  # superseded 2026-09-24, kept

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
"""History. v2 was never approved; it is kept so the v3 diff below reads against something."""

CHANGELOG_V2_TO_V3: list[str] = [
    "rate: 3.0 → 3.5 lb/wk above 275 lb (cap 4.0 above 295) — his own measured 2024–25 record (3.4 lb/wk over 32 weeks, "
    "W38 → W18; the 2026-09-20 packet's '2.7' divided by the wrong window) and clean trough labs; the taper now follows "
    "his fat fraction and the DXA gates (3.0 to 260 with 3.5 DXA-gated; 2.75 to 240), not a calendar",
    "floor: 1,700 → 1,800 on the 7-day mean (1,900 on a lifting day), no single day < 1,600 — 200 g protein + 65 g fat "
    "do not fit under 1,700; opening intake 2,100, titrated ±150 on the scale, never on an incomplete-log week",
    "lifting: six days on a wave, 10–16 sets/muscle, loads that MOVE → three or four full-body sessions, 6–10 sets/muscle, "
    "loads that HOLD, gains taken only when offered (retention was excellent last time; volume was the cost; the wave "
    "manufactures failures that raise calories for the wrong reason — Bickel 2011)",
    "walking: 12–15 h target → 13 h by week 6 with 16 h permitted in weeks 3–12; floor 8.5 h permanent, 10 h in maintenance "
    "(the engine that made the rate: 16–19 h/wk in the first nine weeks of 2024–25)",
    "landing: 12 weeks at 200 → deceleration from 240 lb in weight not weeks, rehearsal maintenance weeks at 260/240/220, "
    "land at 200–205 never 188, 26 weeks of maintenance in a 195–205 band with walking as the relapse vital sign",
    "medical: DXA 8–12 → 8 weeks fixed; ursodiol in every week the 14-day trend exceeds 3.0 lb/wk; baseline within two weeks "
    "including the week-0 DXA, RMR and gallbladder ultrasound; the stop/slow table",
    "new: fat floor 65 g and carb floor 120 g; the logging redline (7 of 7, 14 complete days before the first titration, "
    "a day < 600 kcal is dark); the adaptive-rate tripwires (loss_acceptable / excessive_clean / excessive_flagged / "
    "rate_ceiling / insufficient_adherent / insufficient_nonadherent), under_floor, walking_vs_fork, "
    "leverage_not_deterioration, lean_mass, sleep, weigh_in_dark, joy, post_goal_walking",
    "tripwire thresholds: readiness 40 on 3 days → recovery 7-day mean < 50 (5–7 days); strength → rolling 3-session e1RM "
    "median > 5 % below the 6-session baseline on 2 of 4 anchors (the engine still computes the simpler top-set drop and "
    "says so); rate_overshoot is cap-based with ursodiol on; volume_ceiling → 10 sets/muscle/wk; "
    "abstinence_violation_spiral folded into weigh_in_dark + logging_dark",
    "kept: protein 200/180 on ≥6 of 7 in 4 feedings, subtract-only authoring, the running gate (tightened), daily weighing, "
    "the Minimum Viable Week, the mood firewall, band-matched load anchoring with the detraining discount",
]

LAST_REVIEWED_BY_OWNER: str | None = "2026-09-23"
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
            "preserved… defensible rate window ~0.5-1.0% bodyweight/wk'. Kept as the historical ENVELOPE; the "
            "instruction is the scheduled absolute target in `rate_schedule_lb_wk`. v3 changes the invariant: not "
            "%BW/wk (a population figure from people carrying 20–40 lb of fat) but the LEAN COST of each week — the "
            "Forbes/Hall fat fraction of the loss, anchored on his two DEXAs, times the rate — held at ≤0.5–0.7 lb "
            "lean/wk. 3.5 lb/wk at 317 lb is 1.10 %BW/wk, ABOVE this envelope's top, and is his instruction anyway."
        ),
        "owner_to_resolve": None,
        "resolution": (
            "RESOLVED as a schedule (red team 2026-09-22, approved by the owner 2026-09-21): the v3 targets sit above "
            "the 09-07 envelope's 1.0 %BW/wk top while he is above 240 lb (1.06–1.19 %BW/wk) on his own 2024–25 record "
            "and the lean-cost invariant; they re-enter the envelope from 240 lb down where the landing steps the rate "
            "on schedule. The envelope is kept as what he said on 09-07, superseded by what he approved on 09-21 — the "
            "two owner statements are reconciled here, not left to coexist in two stores."
        ),
    },
    "rate_schedule_lb_wk": {
        "steps": [
            {
                "above_lb": 295,
                "target": 3.5,
                "cap": 4.0,
                "pct_bw_wk": "1.10–1.19",
                "note": "weeks 1–2 excluded (water); his measured 3.37 at 290s on 16 h walking",
            },
            {
                "above_lb": 275,
                "target": 3.25,
                "cap": 3.75,
                "pct_bw_wk": "1.18",
                "note": "3.5 → 3.25 across the band; his measured 3.66 at 280s (19 h), 2.76 at 270s",
            },
            {
                "above_lb": 260,
                "target": 3.0,
                "cap": 3.5,
                "pct_bw_wk": "1.09–1.15",
                "dxa_gate": "3.5 permitted ONLY if the week-8 DXA lean share of the loss is ≤ 12 % and the anchors are flat",
                "note": "his measured 1.99 at 260s — walking had fallen to 7 h. The energy floor binds here on any base under 13 h",
            },
            {
                "above_lb": 240,
                "target": 2.75,
                "cap": 3.25,
                "pct_bw_wk": "1.06–1.15",
                "dxa_gate": "3.0 permitted while the DXA lean share of the loss is ≤ 15 %",
                "note": "his measured 1.96 / 2.65; the fat fraction of the loss falls through 0.79–0.75 here",
            },
            {
                "above_lb": 220,
                "target": 2.25,
                "cap": 2.75,
                "pct_bw_wk": "0.94–1.02",
                "note": "LANDING BEGINS at 240 lb — the rate now steps DOWN on schedule, in weight not weeks",
            },
            {
                "above_lb": 210,
                "target": 1.75,
                "cap": 2.25,
                "pct_bw_wk": "0.80",
                "note": "rehearsal maintenance week at 220; his record fell 3.06 → 2.14 → 1.15 here with activity flat",
            },
            {
                "above_lb": 205,
                "target": 1.25,
                "cap": 1.75,
                "pct_bw_wk": "0.60",
                "note": "arrive at the band already eating maintenance; the scale stops being the goal at 210",
            },
            {
                "above_lb": 0,
                "target": 0.0,
                "cap": 0.0,
                "note": "26-week maintenance block: land at 200–205 (never 188), band 195–205 on the 7-day mean, walking floor 10 h as the vital sign (see `landing`)",
            },
        ],
        "overshoot_rule": (
            "trend >cap for 2 consecutive weeks after week 3 → +150–250 kcal/day and ursodiol on; overshoot is a failure, not a win "
            "(unless strength, DXA and recovery are ALL clean — then `loss_excessive_clean` holds the trajectory; above 4.0 lb/wk `rate_ceiling` applies regardless)"
        ),
        "invariant": "lean cost of the week ≤ 0.5–0.7 lb/wk = model fat fraction (Forbes/Hall on his two DEXAs) × rate; hold the rate while that holds, taper as it rises",
        "provenance": "population-derived",
        "derived_by": (
            "red-team consensus 2026-09-22 (six personas) on his own 2024–25 record — 3.4 lb/wk measured over 32 weeks, 3.6 over the first twelve — "
            "with the taper points from the calibrated energy-balance model (energy floor binds ~275 on <13 h walking; composition crosses "
            "3 % of fat mass/wk ~262; Weinsier's 1.5 kg/wk gallstone line ~260; his own physiology fell at ~210)"
        ),
        "stated": "2026-09-22",
        "note": (
            "All six personas independently put the point where a constant 3.5 stops being supportable at 275–260 lb. The 3.5 above 275 "
            "is not an entitlement: it is what the walking engine at 16 h produces at ~2,000–2,200 kcal, and the record shows he held "
            "that engine for nine weeks, not thirty. ~50 of the 100 lb come off in the first 16 weeks under this table; the aggression is "
            "spent where the fat fraction is ≥0.80 and the floor is not binding. The 14-day weigh-in average is the number; single days are noise. "
            "The final cut step ends at 205, not 200: §8 lands him at 200–205 and the band is 195–205, so 203 lb is IN the band, not a week short of it."
        ),
    },
    "energy_floor_kcal": {
        "floor_7d_mean": 1800,
        "floor_lifting_day": 1900,
        "floor_any_day": 1600,
        "planned_minimum_any_weight": 1700,
        "opening_kcal": 2100,
        "prescribed": [2000, 2100],
        "titration": {
            "read": "14-day trend of daily weigh-ins, read weekly",
            "not_before_day": 21,
            "never_on_a_week_with_fewer_complete_logs_than": 6,
            "act_on": "two consecutive out-of-band reads (band = target ± 0.5 lb/wk)",
            "step_kcal": 150,
            "min_days_between_steps": 14,
            "insufficient_loss_with_logging_intact": "walking hours FIRST (+2 h), then −150 — feet before fork",
            "expected_path": "2,100 to 275 → 2,000 to 240 → 1,950 to 220 → rising to 2,000–2,150 through the landing → ~2,700–2,800 at maintenance (model; measure RMR)",
        },
        "provenance": "population-derived",
        "derived_by": "red-team consensus 2026-09-22 (physician + nutritionist floors; the calibrated model's 'highest intake that reproduces the trajectory')",
        "stated": "2026-09-22",
        "note": (
            "At the 2024–25 activity base (16 h walking, 5 lifts) ~2,000 kcal reproduces the campaign — −100 lb at week 29, 3.45 lb/wk — "
            "exactly the measured record; at a 13 h base the same intake gives ~3.3. 1,500 kcal reproduces 3.5 only at today's 8.4 h "
            "and cannot hold it below 260; its cost is ~30 g of carbohydrate a day for training and an estimated 3–6 lb more lean lost "
            "(from practice, not a citation). There is no prize for eating 1,500: the same trajectory is available at ~2,000–2,100 with "
            "the feet. `prescribed` is the OPENING band; a titration step moves it by a dated edit here, never silently. `floor_any_day` "
            "and `floor_lifting_day` are what the nutrition critics grade single days against; the 7-day-mean floor is not yet computed by "
            "any module and is reported, not enforced."
        ),
    },
    "protein_floor_g": {
        "value": 180,
        "target_g": 200,
        "days_of_7": 6,
        "feedings": 4,
        "feeding_g": [45, 55],
        "g_per_kg_dxa_lean": {"target": 2.6, "floor": 2.3, "lean_kg": 77.4, "lean_source": "DXA 2026-03-30 (170.6 lb lean)"},
        "timing": "one feeding ≥ 40 g within 2 h of lifting; one pre-sleep",
        "provenance": "owner",
        "stated": "2026-09-07",
        "note": (
            "'Protein is the #1 preservation lever — 180 g/day target, currently under-hitting.' Unchanged from v2: 180 g is the FLOOR, "
            "200 g the target, on ≥6 of 7 days, in 4 feedings (Helms 2014, 2.3–3.1 g/kg FFM; Longland 2016, 2.4 g/kg in a 40 % deficit "
            "gained lean; Pasiakos 2013, no benefit past 2× RDA). Measured now: 107–146 g mean, floor met on 2 of 20 logged days."
        ),
    },
    "fat_floor_g": {
        "value": 65,
        "per_meal_g": 10,
        "meals_with_fat": 3,
        "epa_dha_g": 2,
        "provenance": "population-derived",
        "derived_by": "red-team consensus 2026-09-22 (nutritionist + physician: gallbladder emptying, Gebhard 1996; testosterone 361, Whittaker & Wu 2021)",
        "stated": "2026-09-22",
        "note": "≥ 10 g at each of ≥ 3 meals is the gallbladder-emptying rule that pairs with ursodiol above 3.0 lb/wk. NEW in v3; no module grades it yet.",
    },
    "carb_floor_g": {
        "value": 120,
        "typical_g": [150, 180],
        "bias": "toward lifting days; a high-carb refeed (300–350 g at maintenance) only below 240 and only when an anchor drops ≥ 5 % over two sessions with adherence intact",
        "fibre_g": [35, 40],
        "provenance": "population-derived",
        "derived_by": "red-team consensus 2026-09-22 (nutritionist + S&C coach)",
        "stated": "2026-09-22",
        "note": "Carbohydrate is the remainder after protein and fat; 1,500 kcal leaves ~30 g, which is why the floor moved to 1,800. NEW in v3; no module grades it yet.",
    },
    "walking_floor_hr_wk": {
        "value": 8.5,
        "target_hr_wk": 13,
        "target_by_week": 6,
        "ramp_hr_per_wk_max": 1.0,
        "front_load_permitted_hr_wk": 16,
        "front_load_weeks": [3, 12],
        "ceiling_hr_wk_outside_front_load": 15,
        "maintenance_floor_hr_wk": 10,
        "hr_ceiling_bpm": 105,  # drift-ok: a heart-rate ceiling in bpm, not a budget ceiling (ADR-133 scanner false-positive)
        "walks": "2–3 per day, none over 75 min; no walking in the 2 h before lifting; the lightest walking day follows the heavy session",
        "permanent": True,
        "provenance": "owner-history",
        "stated": "2026-06-19",
        "note": (
            "PROVEN_BLUEPRINT's by-band table: at 300-309 lb during the campaign that worked he was walking ~10x/wk, "
            "~8.5 hrs/wk, from day one. v3 (historian, 2026-09-22): the 2024–25 rate was BOUGHT with walking — 15 walks, 16–19 h/wk "
            "at 83–104 bpm for the first nine weeks — and halved to 2.0 at ~269 lb when walking fell from 18 to 7 h while lifting "
            "volume rose. Today: 8.4 h. Rebuild to 13 h by week 6; 16 h is permitted in weeks 3–12 and is what the historical rate "
            "actually requires at 2,000–2,200 kcal — the plan assumes he will not hold it longer and does not depend on it. The floor "
            "is PERMANENT and is a vital sign, not a schedule: a week under 8.5 h (10 h in maintenance) fires the relapse-prodrome "
            "tripwire in every phase (11.4 → 4.4 walks/wk inside 8 weeks of the 2025 trough preceded the regain). Owner correction "
            "2026-09-19: treadmill and cycling blocks logged inside Hevy count; Apple Health steps are NOT a walking proxy. "
            "The walking-hours choice for weeks 3–12 (13 or 16) is the owner's open item — it decides 38 vs 34 vs ~31 weeks."
        ),
    },
    "lifting_sessions_per_wk": {
        "low": 3,
        "high": 4,
        # #4147 (owner, 2026-09-23, DECISION#2026-09-24T03:10:59): v0.4 Upper/Lower replaced v0.3 full-body. The v0.3
        # structure string is kept below as history; the numbers it did not touch are unchanged.
        "structure": (
            "upper/lower in ORDER: upper-heavy -> lower-heavy -> upper-volume -> lower-volume, repeating; the next session is the one "
            "after the last performed lift, whatever the date (a walk audible postpones, never skips); each muscle 2x/wk"
        ),
        "structure_v0_3": "full-body: heavy / moderate / heavy-moderate on non-consecutive days; the optional 4th only after two green recovery days",
        "sets_per_muscle_wk": [8, 12],
        "sets_per_muscle_wk_provenance": "owner 2026-09-23 (#4147, v0.4): ~10 hard sets/muscle/wk; was [6, 10] under v0.3 (red team 2026-09-22)",
        "sets_per_muscle_wk_small": [4, 6],
        "total_hard_sets_wk": [50, 65],
        "session_minutes": [55, 70],
        "anchors_per_week": 2,
        "load_rule": "hold — gains taken only when offered",
        "load_entry": {
            "start_pct_of_band_e1rm": [60, 65],
            "after_detraining_discount": True,
            "ramp_pct_per_wk": 5,
            "ramp_to_week": 6,
            "max_pct_of_band_e1rm_until_week_8": 85,
            "then": "hold",
        },
        "gain_rule": {
            "size": "+2.5 % or +1 rep, one anchor at a time, no more than every 14 days",
            "offered_when": [
                "two consecutive prescribed top sets at ≤ RPE 7 with back-offs complete",
                "no pain flag in 14 days",
                "prior-day intake logged ≥ 1,800 kcal",
            ],
            "refused_when": [
                "recovery < 50",
                "sleep < 6.5 h",
                "the week after a rate-over-cap flag",
                "the first three exposures of a novel-again pattern",
            ],
        },
        "rep_scheme": "heavy exposure 4–6: one top set at RPE 7–8 plus two back-offs at −10 %; moderate 6–10; volume 8–12; accessories 8–15 at RIR 1–2",
        "accessory_rule": "2–3 per session, 2 sets, machines/cables, fixed for the block — none added after week 1; first thing dropped on a bad day",
        "deload": {"every_nth_week": 6, "sets_pct": -30, "loads": "held"},
        "minimum_viable_session": "anchors only, top set + one back-off, ~25 min",
        "success": "the same load, the same reps, week after week, while the bodyweight under it falls — relative strength up ~35 % over the campaign is the win",
        "provenance": "population-derived",
        "derived_by": "red-team consensus 2026-09-22 (S&C coach; Bickel 2011 — one-third of building volume maintains strength, one-ninth maintains size; supersedes v2's 5–6 sessions and the owner's 2026-09-07 '2-3x/wk')",
        "stated": "2026-09-22",
        "note": (
            "Retention was NOT the problem last time; volume was the cost. 100–196 sets a week on an unlogged deficit produced flat "
            "loads and a 'weaker than hoped' arrival while the DEXA says the muscle stayed (trough: 160.9 lb lean at 15.6 %). Under "
            "the owner's hierarchy (lean → absolute strength → gains as a bonus) v3 keeps the retention and cuts the cost: ~50–65 hard "
            "sets total vs 98 now. Deficit-adjusted MEV–MAV, never MRV. 'Loads that MOVE' was 2025's hope renamed."
        ),
    },
    "load_anchoring": {
        "value": "bodyweight-band-matched history, discounted for detraining",
        # #4107 owner ruling 2026-09-23: the discount is 10 % — the band collapses to its
        # shallow end, so the ramp (which reads the deep end) and the blueprint-historian
        # critic (which reports the band) read one number. The 2026-09-08 statement stays below.
        "detraining_discount_pct": [10, 10],
        "detraining_discount_provenance": "owner ruling 2026-09-23 (#4107): 10 %, not the lane's conservative 15 %",
        "detraining_discount_pct_stated_2026_09_08": [10, 15],
        "entry_pct_of_band_best": [85, 90],
        "trap_bar_until_lb": 275,
        "provenance": "owner",
        "stated": "2026-09-08",
        "note": (
            "'Prescribe strength loads against BODYWEIGHT-BAND-MATCHED history, not recent history… TWO axes: (1) "
            "matched bodyweight band tells you what his frame handled, (2) weeks since last consistent block tells you "
            "what his connective tissue is ready for NOW. Matching on weight alone will over-prescribe.' Observed "
            "discount that was correct in practice: ~10-15% under last performed after a ~10 week layoff. Unchanged in v3, "
            "plus: the hinge is the TRAP BAR until ≤ 275 lb — the 250–289 conventional pull in his record was set at 260-lb "
            "geometry, so the conventional bar is gated by bodyweight, not by preference. Connective tissue at 316 lb lags "
            "muscle by 8–12 weeks (Kubo 2010): weekly axial tonnage and walking hours each +≤ 10 %/wk."
        ),
    },
    "run_gate_lb": {
        "value": 240,
        "gate": (
            "≤ 240 lb AND four consecutive weeks ≥ 12 h walking without a pain flag AND a run/walk on-ramp; max 2 runs/wk, none within "
            "24 h of a heavy lower session; no intervals at any weight"
        ),
        "provenance": "owner-history",
        "stated": "2026-06-19",
        "note": (
            "ZERO runs logged above 240 lb across his whole history; running appears at 240 and scales down-weight. Joint-gated from "
            "his own data, not a generic caution. v3 tightens the gate: the 220–229 band (4.4 runs + 5.2 lifts + 138 sets) was his "
            "lowest recovery of the whole 2024–25 cut."
        ),
    },
    "medical_cover": {
        "baseline_within_weeks": 2,
        "baseline_status": "WAIVED by owner ruling 2026-09-22 — no fresh baseline is booked; the latest on record is week 0 (see week0_reference)",
        "week0_reference": {
            "ruling": "owner 2026-09-22: disregard the fresh baseline; arm v0.3 on the latest the platform holds",
            "dxa": {
                "date": "2026-03-30",
                "lean_lb": 170.6,
                "weight_lb_that_week": 307.2,
                "weight_lb_at_ruling": 315.0,
                "caveat": (
                    "he is ~8 lb heavier than at the reference scan, so the lean-share-of-loss arithmetic runs across weight he had "
                    "already lost once — a small bias in the strict direction, accepted by the ruling"
                ),
            },
            "labs": {
                "date": "2026-04-03",
                "where": "USER#matthew#SOURCE#labs / DATE#2026-04-03 — the stop lines' 'from baseline' reference",
            },
            "next_scan": {
                "week": 8,
                "approx_date": "2026-11-01",
                "earns": "the DXA-gated 3.5 (lean share ≤ 12 %) — nothing is earned before it",
            },
            "wired_to_engine": False,
        },
        "baseline": [
            "CMP with phosphate and Mg",
            "CBC",
            "ferritin",
            "lipids",
            "HbA1c",
            "fasting insulin",
            "TSH",
            "testosterone total+free, SHBG",
            "uric acid",
            "hs-CRP",
            "25-OH-D",
            "urinalysis",
            "12-lead ECG with QTc",
            "gallbladder ultrasound",
            "DXA (week 0 — by owner ruling 2026-09-22 the 2026-03-30 scan STANDS as week 0; the next scan is week 8, ~2026-11-01)",
            "BP + orthostatics",
            "PHQ-9",
            "RMR by indirect calorimetry",
        ],
        "dxa_every_weeks": 8,
        "labs_cadence": "week 4, then every 8 weeks with the DXA",
        "weekly": ["BP/orthostatics", "RHR/HRV", "sleep", "PHQ-2"],
        "phq9": "monthly, through December (7 of 16 cuts began in December; both reversals were grief)",
        "ecg_repeat_on": ["K < 3.5", "7-day mean < 1,500 kcal", "palpitations", "syncope"],
        "ursodiol": {"dose_mg_per_day": [500, 600], "when": "every week the 14-day trend exceeds 3.0 lb/wk", "trend_threshold_lb_wk": 3.0},
        "stop_lines": [
            "K < 3.5",
            "Mg < 1.7 or PO4 < 2.5",
            "Na < 133",
            "eGFR worse than −25 % from baseline",
            "ALT > 3× ULN",
            "uric acid > 9 or a flare",
            "QTc > 470",
            "orthostatic SBP drop > 20 or syncope",
            "RHR +12 over the 14-day baseline",
            "PHQ-9 ≥ 10 or any item 9 (stop AND firewall)",
        ],
        "slow_lines": ["K 3.5–3.7 (slow and replace)", "RHR +8 with HRV −20 %"],
        "stop_means": "deficit to zero for 72 h and review",
        "slow_means": "−0.5 lb/wk and +250 kcal",
        "lean_mass_rule": {
            "continue": "DXA lean share of the loss ≤ 15 % and ≤ 0.6 lb/wk",
            "slow_one_band": "≥ 20 % or ≥ 1.0 lb/wk",
            "maintenance_until_next_scan": "≥ 25 %, or appendicular lean −5 % from week 0",
            "testosterone": "expect a rise toward 2025's 577; < 250 with symptoms at week 16 = slow",
        },
        "bone": "T-score 3.9; calcium, vitamin D, one axial loaded pattern weekly, BMD read on every DXA; a further −0.5 across the cut → endocrine review, not a stop",
        "provenance": "population-derived",
        "derived_by": "red-team consensus 2026-09-22 (obesity-medicine physician; Sugerman 1995 and Stokes 2014 for ursodiol)",
        "stated": "2026-09-22",
        "note": (
            "What makes this aggressive rather than reckless. DXA every 8 weeks FIXED (not 8–12) because the DXA gates in the rate "
            "schedule cannot be earned on a scan that has not happened. The engine reports what it cannot yet read — the labs "
            "partition exists; the cadence and the thresholds are not wired to it (`medical_stop_lines`)."
        ),
    },
    "landing": {
        "deceleration_begins_lb": 240,
        "rehearsal_maintenance_weeks_at_lb": [260, 240, 220],
        "rehearsal_week": "seven days at the estimated maintenance, walking floor met, daily weigh-in, logged",
        "land_lb": [200, 205],
        "never_lb": 188,
        "goal_after_210": "four consecutive weeks of walking floor met, protein 6 of 7, weekly mean inside a 3-lb band — hitting 200 in week two of that changes nothing",
        "maintenance_weeks": 26,
        "band_lb": [195, 205],
        "band_read": "7-day mean",
        "overshoot_rules": {
            "plus_5_for_3_days": "7-day mean > 205 for 3 consecutive days → 14 days at the last cut prescription, no discussion",
            "over_208": "7-day mean > 208 → the plan is re-entered, not 'considered'",
        },
        "calories": "days 1–7 up in one step (+300–400; expect 4–6 lb of food and water on the scale, told in advance); then +100–150 kcal/week until the 14-day trend reads 0 ± 0.5 lb/wk",
        "walking_floor_hr_wk": 10,
        "relapse_signal": "walking, not weight — any maintenance week < 8.5 h (10 h in maintenance) is the prodrome; same-day human contact",
        "weekly_human_hour": "one fixed hour a week where the numbers are read by someone who is not him",
        "dxa_at_maintenance_weeks": [0, 12, 26],
        "labs_at_maintenance_weeks": [12, 26],
        "lifting": "continues at the maintenance dose in a genuine progression block — the first strength phase he has ever had",
        "provenance": "population-derived",
        "derived_by": (
            "red-team consensus 2026-09-22 — the lived-experience seat's 240 adopted (the last weight at which his own record shows the "
            "walking base kept; physician 230, historian 210 dissent recorded); Kerns 2017 (activity, not adaptation, distinguished "
            "maintainers); Rosenbaum & Leibel 2010 / Fothergill 2016 for the 200–400 kcal maintenance discount"
        ),
        "stated": "2026-09-22",
        "note": (
            "The primary improvement over 2024–25. That campaign proved the engine and not the brakes: 188.5 at W18 → 112 lb back in ten "
            "months, 102 of it fat, at 0.79× the loss rate, with walking gone within eight weeks. Rate did not cause that (Purcell 2014, "
            "Vink 2016); the cliff did. Deceleration from 240 costs ~5–9 weeks against the straight-line historical trajectory, spent "
            "entirely below 240 where the lean went last time. 26 weeks, not 12 — 12 covers one crater cycle and stops."
        ),
    },
    "logging_completeness": {
        "days_of_7": 7,
        "complete_days_before_first_titration": 14,
        "dark_day_kcal": 600,
        "audit_week_every_n_weeks": 4,
        "provenance": "population-derived",
        "derived_by": "red-team consensus 2026-09-22 (nutritionist + lived experience)",
        "stated": "2026-09-22",
        "note": (
            "Logging is the instrument and it is currently broken: 20 of 28 days logged, logged mean 1,097 kcal (1,533 on days ≥ 600) "
            "against a 2.42 lb/wk trend at 317 lb that implies a true intake near 2,400. The first four weeks of v0.3 fix the instrument "
            "before they grade the rate. A logged day under 600 kcal is a dark day, not a good one."
        ),
    },
    "standing_owner_rules": {
        "value": [
            "daily weighing",
            "never max out on session 1 of a novel-again pattern",
            "never two heavy axial patterns cold in one session",
            "loads anchored to band-matched history with the detraining discount",
            "subtract-only authoring: in session he may drop load 5–10 %, drop a set, or take the listed swap — never add",
        ],
        "provenance": "owner",
        "stated": "2026-09-08",
        "note": "§6 item 9 — unchanged from the owner's own rules across v1 → v3; restated here so the redlines file is the whole posture.",
    },
}


# ── What makes the coach pull back ───────────────────────────────────────────
# Every entry: the signal, the threshold, where the threshold came from, and what the
# coach DOES. "Pull back" is never "stop" unless it says so — a tripwire that can only
# halt everything is one he will learn to ignore. `evaluated_by_engine: False` marks a
# tripwire that plan_engine does not compute — it is REPORTED so the owner can see the
# whole posture, and it says so wherever it appears (ADR-105: silence is not clearance).
# The nutrition critics (`health.nutrition_critics`, #3754) read the intake floor and the
# logging counts, but that is a different module: `evaluated_by_engine` is a plan_engine
# claim and stays False there.
TRIPWIRES: list[dict[str, Any]] = [
    # ── the v1 five — computed by plan_engine today (self_added_volume joined them in #4081) ──
    {
        "id": "anchor_lift_strength_drop",
        "signal": "rolling 3-session e1RM median vs the 6-session baseline on the four core anchors (bench, row, squat, hinge)",
        "threshold_pct": 5,
        "consecutive_sessions": 2,
        "definition_v3": (
            "rolling 3-session e1RM median > 5 % below the 6-session baseline on 2 of 4 core anchors inside 14 days, or > 10 % on one "
            "anchor for 3 sessions; not before week 6 (the ramp is still under 85 % of band e1RM)"
        ),
        "not_before_week": 6,
        "provenance": "population-derived",
        "derived_by": "S&C coach (red team 2026-09-22); the action order is the owner's rule",
        "action": (
            "audit protein / sleep / logging FIRST → sets −30 % for 2 weeks and walking −20 % → only if a brought-forward DXA shows lean "
            "loss > 15 % of the loss since the last scan: +200–300 kcal as carbohydrate. NEVER automatically 'eat more'; never lower the load automatically"
        ),
        "note": (
            "Strength held flat through a 118 lb loss last time and the DEXA called retention excellent; a sustained drop is the earliest "
            "honest signal that the rate is outrunning recovery. v3: 5 % (was 7.5 %) on a rolling e1RM MEDIAN, and the action no longer "
            "adds calories by reflex — the wave-and-eat-more loop 'manufactures failures that raise calories for the wrong reason'. "
            "`leverage_not_deterioration` is the companion: an absolute drop ≤ 5 % per 20 lb with allometric strength flat is leverage, "
            "logged and not acted on. Since #4098 the engine computes the rolling 3-session e1RM median against the 6-session baseline "
            "per template identity (`plan_engine.anchor_e1rm_trend`), trips on `threshold_pct` with `consecutive_sessions` of the last 3 "
            "below it, on the WORST core anchor, and holds the whole tripwire `not_yet_active` before `not_before_week` on the block "
            "calendar; the '2 of 4 anchors inside 14 days' and '> 10 % on one anchor for 3 sessions' clauses are not yet computed. "
            "Day-to-day e1RM noise in a trained lifter is ~4–5 % (from practice, not a citation) — NOT computed from his own variance; the engine must say so wherever it fires (ADR-105)."
        ),
    },
    {
        "id": "protein_floor_missed",
        "signal": "days below the protein floor (180 g) in the trailing 7",
        "threshold_days": 3,
        "provenance": "owner",
        "action": (
            "the next 7 days are a kitchen intervention (pre-portioned protein); training does not grow that week and "
            "the rate is not 'earned' — the consequence lands in the kitchen, not only on the gym"
        ),
        "note": (
            "His own stated #1 preservation lever. Missing it is the mechanism by which an aggressive rate costs muscle "
            "rather than fat. Unchanged v2 → v3."
        ),
    },
    {
        "id": "readiness_floor",
        "signal": "Whoop recovery 7-day mean (or HRV 7-day mean < 32 — a −20 % read — or RHR +8 over the 14-day baseline)",
        "threshold": 50,
        "consecutive_days": 5,
        "window_days": [5, 7],
        "provenance": "population-derived",
        "derived_by": "transformation coach + physician (red team 2026-09-22), the §7 `recovery` row",
        "action": "deload −40 % sets, walking KEPT, +200 kcal; re-read on day 14",
        "note": (
            "v1 used 34 (Whoop's own boundary), v2 40 on 3 days; v3 moves to a 7-day MEAN under 50 read over 5–7 days — the multi-day form "
            "is the one that means something, and 50 is still population-derived (recovery improved through his 2024–25 cut; the 220–229 "
            "band's 53 was its low). The engine computes the simpler consecutive-days-below-50 streak until the 7-day mean is wired, and says "
            "so. Re-derive from his own recovery distribution once cycle 17 has it."
        ),
    },
    {
        "id": "pain_flag_named_site",
        "signal": "a pain flag ≥ 3/10 persisting 24 h on a named joint/tendon in the derived note layer",
        "threshold": "any",
        "provenance": "owner",
        "action": (
            "−10 % on that pattern for 2 weeks (the muscle's volume kept via a pain-free variant); two flags on one joint in 14 days → the "
            "listed swap; two swaps on the same site in 8 weeks → a human, not a program tweak"
        ),
        "note": (
            "The pain lexicon is over-inclusive by design and the flag is a question, not a verdict. NOTE (#3768): this "
            "tripwire reads a layer that was dark from the day it shipped until 2026-09-13 — so it could not have "
            "fired. The engine reports this tripwire's own layer_status rather than its silence."
        ),
    },
    {
        "id": "weight_stall_with_adherence",
        "signal": "trailing 14d weight trend flat or up WHILE intake, protein and walking adherence are on plan",
        "threshold_days": 14,
        "provenance": "owner-history",
        "action": "this is a diet-break / refeed decision, surfaced to him as a decision — never taken silently, never 'push harder'",
        "note": (
            "The prior campaign ran flat-out with no planned landing and reversed. A stall that is NOT explained by "
            "adherence is the moment the blueprint says to schedule a break rather than push harder. An unaudited stall is "
            "a logging problem first (every 4th week is a gram-scale audit week). Above 260 no refeed or break unless a tripwire "
            "fires; below 260 the rehearsal maintenance weeks at 260 / 240 / 220 are the planned breaks."
        ),
    },
    # ── the adaptive-rate rules (§7) — reported, not yet evaluated by plan_engine ──
    {
        "id": "loss_acceptable",
        "signal": "14-day trend vs the band's target",
        "threshold": "within ±15 % (±0.5 lb/wk)",
        "window_days": "rolling",
        "provenance": "owner",
        "derived_by": "owner (the 2026-09-21 ask: the rate is adaptive, not ideological)",
        "action": "nothing — do not slow on a calendar",
        "evaluated_by_engine": False,
        "note": "The base case the other rate rules are exceptions to. Named so 'on schedule' is a computed state, not the absence of a flag.",
    },
    {
        "id": "loss_excessive_clean",
        "signal": "trend > the band's cap WHILE strength, DXA and recovery are all clean",
        "threshold": "after week 3",
        "threshold_days": 14,
        "provenance": "owner",
        "derived_by": "owner + physician (red team 2026-09-22)",
        "action": "HOLD — the aggressive trajectory continues; ursodiol on",
        "evaluated_by_engine": False,
        "note": "Overshoot with every retention signal clean is the historical record repeating, not a failure; the gallstone cover is the price.",
    },
    {
        "id": "loss_excessive_flagged",
        "signal": "trend > the band's cap AND any strength / lean / recovery flag",
        "threshold_days": 14,
        "provenance": "population-derived",
        "derived_by": "population (Garthe 2011) via the nutritionist and S&C seats",
        "action": "+150–250 kcal/day; target −0.5 lb/wk",
        "evaluated_by_engine": False,
        "note": "The flagged arm of the overshoot rule; `rate_overshoot` below is its cap-based v2 ancestor kept for the nutrition critics' read.",
    },
    {
        "id": "rate_ceiling",
        "signal": "14-day trend > 4.0 lb/wk after week 3, at any weight",
        "threshold_lb_wk": 4.0,
        "threshold_days": 14,
        "provenance": "population-derived",
        "derived_by": "physician / nutritionist (red team 2026-09-22)",
        "action": "+150 kcal/day regardless of every other signal",
        "evaluated_by_engine": False,
        "note": "An absolute ceiling above the schedule's caps; the only rate rule with no 'unless'.",
    },
    {
        "id": "rate_overshoot",
        "signal": "14-day weight trend rate above the schedule's cap for 2 consecutive weeks, after week 3",
        "threshold_weeks": 2,
        "after_week": 3,
        "provenance": "population-derived",
        "derived_by": "transformation coach + physician (v2), re-based on the v3 caps",
        "action": "+150–250 kcal/day and ursodiol on — unless strength, DXA and recovery are ALL clean (`loss_excessive_clean`: hold); overshoot is a failure, not a win",
        "evaluated_by_engine": False,
        "note": (
            "Cap-based: the cap is the schedule step's `cap` at his current weight (4.0 above 295, 3.75 above 275, …). "
            "`health.nutrition_critics` reads `threshold_weeks` and the overshoot rule's words and offers the +250 as a change; "
            "its week gate is 'after week 4' from v2 and one week looser than v3's 'after week 3' — noted, not silently corrected."
        ),
    },
    {
        "id": "loss_insufficient_adherent",
        "signal": "trend < 70 % of target WITH logging ≥ 6/7 and the protein floor met",
        "threshold_pct_of_target": 70,
        "threshold_days": 21,
        "provenance": "owner",
        "derived_by": "owner's rule: feet before fork",
        "action": "walking +2 h FIRST; then −150 kcal (floor 1,800); never both inside 14 days",
        "evaluated_by_engine": False,
        "note": "The only rule that lowers intake, and it lowers the feet first.",
    },
    {
        "id": "loss_insufficient_nonadherent",
        "signal": "trend < 70 % of target WITH logging < 6/7 or walking under the floor",
        "threshold_pct_of_target": 70,
        "threshold_days": 14,
        "provenance": "population-derived",
        "derived_by": "nutritionist (red team 2026-09-22)",
        "action": "adherence audit only; NO calorie change",
        "evaluated_by_engine": False,
        "note": "A rate that cannot be read is not a rate that is too slow.",
    },
    {
        "id": "intake_floor_breached",
        "signal": "days below the hard energy floor (1,600 kcal any day; 1,900 on a lifting day) in the trailing 7",
        "threshold_days": 2,
        "provenance": "population-derived",
        "derived_by": "physician + nutritionist (v2), floors re-based to v3",
        "action": "+250 kcal/day as protein + fruit for 7 days; the aggressive phase pauses until corrected",
        "evaluated_by_engine": False,
        "note": "Read by `health.nutrition_critics` against `energy_floor_kcal.floor_any_day` / `floor_lifting_day`; the 1,078 kcal day in the record is a violation, not a good day.",
    },
    {
        "id": "under_floor",
        "signal": "logged days < 1,700 kcal in the trailing 7",
        "threshold_kcal": 1700,
        "threshold_days": 3,
        "provenance": "owner-history",
        "derived_by": "lived experience (red team 2026-09-22); firing today on his own record — 15 of 20 logged days",
        "action": "+250 kcal for 7 days, protein to 200 g",
        "evaluated_by_engine": False,
        "note": "The planned-minimum arm (1,700 at any weight) as distinct from the hard floor above; the current block trips it.",
    },
    {
        "id": "logging_dark",
        "signal": "a logged day < 600 kcal, or no log at all",
        "threshold_days": 2,
        "dark_day_kcal": 600,
        "threshold_days_of_7": 2,
        "threshold_days_of_14": 4,
        "provenance": "owner-history",
        "derived_by": "lived experience (red team 2026-09-20 / 2026-09-22)",
        "action": "2 of 7 → a check-in, not a scolding (a message, read as an early mood signal); 4 of 14 → intake assumed at the floor and prescribed by default, walking audited",
        "evaluated_by_engine": False,
        "note": "Logging goes dark before the walks do. `health.nutrition_critics` reads `threshold_days` as the trailing no-log run; the <600 kcal dark-day rule is v3 and not yet read by it.",
    },
    {
        "id": "walking_vs_fork",
        "signal": "two weeks under the 8.5 h walking floor WHILE the trend is at or above target",
        "threshold_days": 14,
        "provenance": "population-derived",
        "derived_by": "lived experience (red team 2026-09-22; from practice, not a citation)",
        "action": "the deficit shrinks by 250 kcal — speed may not come from the fork when the feet are down",
        "evaluated_by_engine": False,
        "note": "The rule that stops 1,500 kcal from quietly substituting for 16 hours of walking, which is exactly how the current block is producing its rate.",
    },
    {
        "id": "leverage_not_deterioration",
        "signal": "absolute anchor load down ≤ 5 % per 20 lb of bodyweight WITH allometric strength (e1RM / BW^0.67) flat",
        "threshold": "≤ 5 % per 20 lb, allometric flat",
        "provenance": "population-derived",
        "derived_by": "S&C coach (red team 2026-09-22; from practice)",
        "action": "log it; no action",
        "evaluated_by_engine": False,
        "note": "The companion to `anchor_lift_strength_drop`: a lighter man moving slightly less is leverage, and treating it as deterioration is how 2025's loads got held flat out of fear.",
    },
    {
        "id": "lean_mass",
        "signal": "DXA-interval lean share of the loss > 20 %, or > 1.0 lb lean/wk",
        "threshold": {
            "lean_share_pct": 20,
            "lean_lb_wk": 1.0,
            "maintenance_at_lean_share_pct": 25,
            "maintenance_at_appendicular_lean_pct": -5,
        },
        "threshold_days": 56,
        "provenance": "population-derived",
        "derived_by": "obesity-medicine physician (red team 2026-09-22)",
        "action": "slow one band; > 25 % of the loss, or appendicular lean −5 % from week 0 → maintenance until the next scan",
        "evaluated_by_engine": False,
        "note": "The instrument that answers his actual question (did I keep the muscle) and the one that earns the DXA-gated 3.5 / 3.0 steps. Week 0 = the 2026-03-30 scan by owner ruling 2026-09-22 (medical_cover.week0_reference); it earns nothing until the week-8 scan.",
    },
    {
        "id": "sleep",
        "signal": "sleep 7-day mean < 6.5 h",
        "threshold_hours": 6.5,
        "consecutive_days": 5,
        "provenance": "population-derived",
        "derived_by": "transformation coach (red team 2026-09-22)",
        "action": "the Minimum Viable Week",
        "evaluated_by_engine": False,
        "note": "Sleep is his one degraded channel now (7.25 h vs 8.4 in the 290s of 2024) and is why the walking ceiling is 15 h outside the front-loaded window.",
    },
    {
        "id": "walking_collapse",
        "signal": "walking+cycling hours down >30% week-over-week, or two skipped evening walks in one week",
        "threshold_pct": 30,
        "provenance": "owner-history",
        "action": "mandatory human contact the same day and a mode review — this is the relapse prodrome, not a rest day",
        "evaluated_by_engine": False,
        "note": (
            "11.4 → 4.4 walks/wk inside 8 weeks of the 2025 trough preceded the regain, and the 2024–25 rate halved at ~269 lb the week "
            "walking fell from 18 to 7 h. The engine computes weekly walking hours (walking-volume@1.0.0) and `health.nutrition_critics` "
            "reads the week-over-week comparison; plan_engine does not."
        ),
    },
    {
        "id": "weigh_in_dark",
        "signal": "no weigh-in for 3 days, in any phase",
        "threshold_days": 3,
        "provenance": "population-derived",
        "derived_by": "lived experience (red team 2026-09-22; from practice)",
        "action": "a call: logs go dark first, the scale second, the walk third",
        "evaluated_by_engine": False,
        "note": "Absorbs v2's `abstinence_violation_spiral` — the next morning's weigh-in is still the rule that breaks the spiral; the signal is now the missing weigh-in itself.",
    },
    {
        "id": "medical_stop_lines",
        "signal": "any stop line in `medical_cover.stop_lines` · RUQ pain · syncope · palpitations",
        "threshold": "any",
        "provenance": "population-derived",
        "derived_by": "obesity-medicine physician (red team 2026-09-22)",
        "action": "deficit to zero for 72 h; labs / ECG / ultrasound; resume on clearance. A slow line → −0.5 lb/wk and +250 kcal",
        "evaluated_by_engine": False,
        "note": "The platform has a labs partition; the cadence and the thresholds are not wired to it. Postprandial RUQ pain → ultrasound within 48 h.",
    },
    {
        "id": "mood_declared",
        "signal": "PHQ-9 ≥ 10, item 9 > 0, a grief event, or he declares it himself",
        "threshold": "any",
        "provenance": "owner-history",
        "action": (
            "the Minimum Viable Week fires AUTOMATICALLY, not chosen — calories to the band's maintenance (not down), the walking floor "
            "halves (never zero), logging becomes ate / walked / weighed, daily weighing continues with no judgement for 14 days; one named "
            "human is contacted within 48 h BY THE PLAN, not by him; day 14 the plan asks whether the week extends; day 28 someone other than him decides"
        ),
        "evaluated_by_engine": False,
        "note": (
            "Both major reversals were bereavement/depression, not training. Two in fourteen years is the base rate, not the exception. "
            "v3 lowers the PHQ-9 line from 15 to 10 (physician). Written now because it cannot be written on the day; the named human is an owner act (§13)."
        ),
    },
    {
        "id": "joy",
        "signal": "weekly yes/no: did you want to do any of it",
        "threshold": "three 'no' answers before 230 lb",
        "threshold_days": 21,
        "provenance": "population-derived",
        "derived_by": "lived experience (red team 2026-09-22)",
        "action": "one week at maintenance — numbers-only tripwires miss this",
        "evaluated_by_engine": False,
        "note": "The one tripwire with no number behind it, on purpose.",
    },
    {
        "id": "self_added_volume",
        "signal": "training above the prescription two weeks running",
        "threshold_weeks": 2,
        "definition_engine": (
            "a Mon–Sun Pacific week is above the prescription when, across its sessions matched to a committed routine, the sets "
            "performed on prescribed movements exceed the sets prescribed for them (net) — the per-movement counts are "
            "`health.adherence_calc`'s, stored on each Hevy row at ingest; fires when the two most recent COMPLETE weeks are both above"
        ),
        "provenance": "owner-history",
        "tripwire_class": "report_only",
        "action": (
            "an end-of-week report: the week's total sets added beyond the prescription, by movement, day and RPE, and the net — "
            "no veto, no subtract-only flag, no mood question"
        ),
        "evaluated_by_engine": True,
        "note": (
            "Amended 2026-09-23 by owner ruling (#4111): 'Just give me an end of week report or update — I don't think this is "
            "anxiety, it's me wanting to do more.' The original wording (red team 2026-09-22) read the same signal as an anxiety "
            "tell and enforced subtract-only with a mood question by name — the owner overruled that reading of his own behaviour. "
            "Evaluated by plan_engine since #4081 (`training.self_added_volume`) from adherence's per-movement programmed-vs-performed "
            "set counts — every logged set on both sides, warm-ups included, as adherence counts them; an exercise the routine did not "
            "name (`adherence.extra`) is evidence, not counted volume, because a swap and a treadmill block look the same by template "
            "id. `health.nutrition_critics` reads the same run length and reports it as information, never as a change or a veto."
        ),
    },
    {
        "id": "volume_ceiling",
        "signal": "hard sets per muscle per week, or working sets in one session",
        # #4147: moves with v0.4's band (owner, 2026-09-23: ~10 sets/muscle/wk, [8, 12]) — 12; it was 10, the top of v0.3's 6–10.
        # derived from the band, never re-typed: the ceiling IS the band's top
        "threshold": {"sets_per_muscle_wk": REDLINES["lifting_sessions_per_wk"]["sets_per_muscle_wk"][1], "sets_per_session": 18},
        "provenance": "population-derived",
        "derived_by": "S&C coach (red team 2026-09-22); the redline band is `lifting_sessions_per_wk.sets_per_muscle_wk` (v0.4: 8–12), this is its top",
        "action": "the plan does not grow next week — MRV is lower in a deficit and he can overshoot it without feeling it; above the band the next week's sets come down, never up",
        "evaluated_by_engine": False,
        "note": "The 28-day per-muscle sets are already computed; the per-session count is the generator's own `session_set_ceiling` (18).",
    },
    {
        "id": "post_goal_walking",
        "signal": "any maintenance week < 70 % of the cut-phase walking mean",
        "threshold_pct_of_cut_mean": 70,
        "threshold_days": 7,
        "provenance": "owner-history",
        "derived_by": "lived experience (red team 2026-09-22) on his own 2025 regain — walking gone within eight weeks of the trough",
        "action": "relapse declared; the band protocol begins regardless of weight",
        "evaluated_by_engine": False,
        "note": "Relapse detection is walking, not weight. This is the tripwire the 2024–25 campaign did not have.",
    },
]


def engine_evaluated_tripwires() -> list[dict[str, Any]]:
    """The tripwires plan_engine computes today (the v1 five + self_added_volume, #4081)."""
    return [t for t in TRIPWIRES if t.get("evaluated_by_engine", True)]


def unevaluated_tripwires() -> list[str]:
    """Tripwires that are reported but not computed by plan_engine — named, never silent (ADR-105)."""
    return [t["id"] for t in TRIPWIRES if not t.get("evaluated_by_engine", True)]


def landing() -> dict[str, Any]:
    """The landing block (§8) — the primary improvement over 2024–25, as data the coach reads."""
    return REDLINES["landing"]


def summary() -> dict[str, Any]:
    """The block the planner embeds — never a bare number without its provenance."""
    return {
        "active": ACTIVE,
        "version": REDLINES_VERSION,
        "last_reviewed_by_owner": LAST_REVIEWED_BY_OWNER,
        "status_note": (
            "PROPOSED — v3, red-teamed 2026-09-22 from the owner's own record at his changed objective, not yet approved by "
            "him. Reported so the plan is auditable; not treated as his instruction until ACTIVE is True (#3753, gate:owner)."
            if not ACTIVE
            else f"ACTIVE — owner-reviewed {LAST_REVIEWED_BY_OWNER} (v{REDLINES_VERSION})."
        ),
        "red_team_record": RED_TEAM_RECORD,
        "plan": PLAN,
        "redlines": REDLINES,
        "tripwires": TRIPWIRES,
        "landing": landing(),
        "unresolved": [k for k, v in REDLINES.items() if v.get("owner_to_resolve")],
        "population_derived_thresholds": [t["id"] for t in TRIPWIRES if t.get("provenance") == "population-derived"],
        "unevaluated_tripwires": unevaluated_tripwires(),
        "changelog_v1_to_v2": CHANGELOG_V1_TO_V2,
        "changelog_v2_to_v3": CHANGELOG_V2_TO_V3,
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
        "dxa_gate": step.get("dxa_gate"),
        "target_pct_bw_wk": round(step["target"] / weight_lb * 100, 2) if weight_lb else None,
        "schedule_step_above_lb": step["above_lb"],
        "landing_phase": weight_lb <= REDLINES["landing"]["deceleration_begins_lb"],
        "provenance": band["provenance"],
        "schedule_provenance": REDLINES["rate_schedule_lb_wk"]["provenance"],
        "stated": band["stated"],
        "owner_to_resolve": band.get("owner_to_resolve"),
        "resolution": band.get("resolution"),
    }
