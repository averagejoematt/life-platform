"""exercise_library_changelog.py — the change-log lines `deploy/build_exercise_library.py` OWNS (`BUILDER_CHANGE_LOG`).

Extracted from the builder (#5861 FIX4) on the module-size seam (docs/ENGINEERING_STANDARDS.md §2: the builder sat at its 1000-line
ceiling): data only — `build_exercise_library.with_builder_changes` adds each line once and moves `version` to the highest. The
file's own lines are never rewritten.
"""

from __future__ import annotations

# Change-log lines the BUILDER owns: a rule change in this file (not an owner ruling on the file) records itself here, and
# `with_builder_changes` adds each line once and moves `version` to the highest. The file's own lines are never rewritten.
BUILDER_CHANGE_LOG = [
    {
        "version": "0.2.0",
        "date": "2026-11-12",
        "by": "#5857 (owner note 2026-11-12, PROPOSAL for the owner's review with the library)",
        "what": "Tiers grade QUALITY, not evidence: every per-target row's `tier` is S/A/B/C/D, derived by the written rubric "
        "(`quality_rubric`, docs/coaching/EXERCISE_LIBRARY.md) from length_bias, stability, resistance_profile, "
        "skill_complexity and joint_stress; `evidence_confidence` (rct_direct | rct_characteristic | consensus | "
        "none_reviewed) is its own field, and a direct trial moves a row at most one band, recorded with its citation "
        "(`evidence_adjustment`). The A/B/C evidence grade and `evidence_quality` are retired. Attribute rules: a named "
        "machine reads `machine_selectorized` (was `unknown`); the pec deck reads `lengthened` (was `unknown`). Target-label audit (owner-approved on PR #5858): "
        "Hevy's raw muscle label is replaced by the reviewed target for every row in deploy/exercise_library_targets.py, each "
        "with its reason and recorded on the entry as `target.audit`; the shoulder splits into side_delts / rear_delts / "
        "front_delts, shrugs move to traps, and compound or conditioning movements to full_body (no single-muscle tier).",
        "rule": "rubric weights are PROPOSED — owner to confirm; status stays proposed",
    },
    {
        "version": "0.3.0",
        "date": "2026-11-12",
        "by": "#5861 (owner brief 2026-11-12, PROPOSAL for the owner's review with the library)",
        "what": "Five objectives rated separately (`ratings`: hypertrophy per target, strength, functional, conditioning, "
        "mobility; null = not applicable, never forced), each by its own small categorical rubric (`quality_rubric`, rubric "
        "3.0.0) over reviewed `objective_inputs`. Hypertrophy keeps the v2 points as its stimulus profile, capped by load "
        "ceiling, limiter muscle and S criteria (stimulus-to-fatigue, stability, joints); body mass loads a bodyweight "
        "compound, a calisthenics ladder earns the load-step point, and any known glute length scores mid. Every movement "
        "gets a `category` (and `trunk_function` / `functions` where they apply), and a canonical layer (`canonical`, "
        "`variant`, `canonical_families`) consolidates the duplicate pairs and near-identical variants while every key and "
        "template id stays. Reviewed fixes: walking lunge no longer cardio, crossover step-up no longer a fly, cuff rotations "
        "no longer trunk flexion, weighted push-up / pull-up / chin-up free weight like the weighted dip, step-up and push-up "
        "length rules, Pallof press target, rear-delt fly attributes.",
        "rule": "rubric 3.0.0 terms and objective inputs are PROPOSED — owner to confirm; status stays proposed",
    },
    {
        "version": "0.3.1",
        "date": "2026-11-12",
        "by": "#5861 FIX2-DATA (second red team 2026-11-12, PROPOSAL for the owner's review with the library)",
        "what": "Unreviewed is not poor (rubric 3.2.0): an unknown input scores its term's NEUTRAL value (a fully unknown movement "
        "lands at B), never helps reach S (`inputs_known`), and every rating on unreviewed or unknown inputs carries "
        "`provisional: true` (+ `provisional_why`). A reviewed-input pass (deploy/exercise_library_input_review.py) covers every "
        "movement logged on 3+ days in the window, every S/A movement and the red team's named rows (Glute Ham Raise, Shrug "
        "(Machine)); a one-field input override no longer implies a full review. Evidence ordering: an untested form of a "
        "trial-backed movement ties it at best (the machine hip thrust no longer outranks the barbell hip thrust). Cuff, face-pull "
        "and pull-apart work leave loaded mobility (joint capacity, on functional). `programming_settings` carries the "
        "programming lane's owner-pending defaults.",
        "rule": "rubric 3.2.0 and the review pass are PROPOSED — owner to confirm; status stays proposed",
    },
    {
        "version": "0.3.2",
        "date": "2026-11-13",
        "by": "#5861 FIX4 (fourth red team, PROPOSAL for the owner's review with the library)",
        "what": "joint_stress gains knee + hip, a PAIN-MAP class rating (exercise_library_input_review.KNEE_HIP; never the rubric's joint "
        "cost, quality_rubric.RUBRIC_JOINTS); Hevy's built-in band pull-up (56808FD2) added; inputs corrected: landmine presses + trap "
        "pulldown moderate ceiling (S -> A), sleds submaximal (strength A -> B), Pallof rehab_control, ab wheel hypertrophy",
        "rule": "the knee/hip class rule and the input corrections are PROPOSED — owner to confirm; status stays proposed",
    },
    {
        "version": "0.3.3",
        "date": "2026-11-13",
        "by": "#5861 FIX6 (the owner's rulings of 2026-11-13 on the decision register — configuration, not activation)",
        "what": "`programming_settings` carries the owner's ruled values (build_exercise_library.OWNER_RULED_SETTINGS): the shared "
        "75-min cap, the 4-session short week, purposeful cardio only, top set + one back-off with a weekly lead lift, overhead "
        "press 3 sets, no KB hinge under strain, chest + quadriceps priority by stimulus and performance, the advisory loss-rate "
        "ceiling, no symptom warning line. Rubric 3.4.0: the glute stretch term at its top for any known length (ruling 17: the "
        "same S standard as other muscles, no exercise-specific trial required); a provisional rating never reaches S on any "
        "objective (ruling 16).",
        "rule": "rulings are configuration only — status stays proposed until the owner approves the library",
    },
]
