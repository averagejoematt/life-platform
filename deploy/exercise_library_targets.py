"""exercise_library_targets.py — the reviewed TARGET-LABEL audit for `config/exercise_library.json` (#5857).

WHY. A movement's `target.primary` came through raw from Hevy's own muscle label (`config/movement_catalog.json`), and the
quality rubric (`training.quality_rubric`) grades every movement against that muscle. Hevy files many movements under the
wrong one — a straight-arm pulldown under shoulders, a high cable row under chest, every lunge under hamstrings, a
squat-to-row under triceps — so the tier table ranked movements against muscles they do not train first. Owner-approved
audit on PR #5858 (2026-11-12): every S/A/B row of every major muscle, and every movement whose title clearly names a
different primary target, reviewed here with a one-line reason each.

WHAT IT DOES. `deploy/build_exercise_library.py` applies each row AFTER the rule derivation and the curation, by library
key: `target.primary` (and `target.region`) take the audited muscle, every hypertrophy row whose target was the old primary
moves with it (a sub-target row such as `triceps_long_head` is left alone), and the entry records the move as
`target.audit` {from, reason}. The quality tier is then re-derived from the audited target. A key that is not in the
library is a hard stop, and `tests/test_target_audit_5857.py` holds the committed library to this table both ways.

THE VOCABULARY. Beyond Hevy's muscles: the shoulder is split into `side_delts`, `rear_delts` and `front_delts` (a rotator-
cuff or general shoulder drill stays `shoulders`); `traps` takes the shrugs and trap raises; `adductors` the adductor
work; `full_body` is a COMPOUND or conditioning movement (a squat-to-row, a lunge-curl, a thruster, a carry) — graded
against no single muscle, so it never sits in a single-muscle tier and never matches a muscle slot. The charter's volume
landmarks still group side and rear delts as one (`side_rear_delts`), so that split exists in the library only.

Never a load, a bodyweight or a word of his notes: titles and muscles only.
"""

from __future__ import annotations

SIDE, REAR, FRONT = "side_delts", "rear_delts", "front_delts"
FULL = "full_body"
_LUNGE = "a lunge / split squat: the quads lead (glutes second); Hevy filed it under hamstrings"
_SQUAT = "a squat pattern: the quads lead; Hevy filed it under another muscle"
_STEP = "a step-up: the quads lead; Hevy filed it under hamstrings"
_PRESS = "an overhead / shoulder press: the front delts lead"
_FRONT_RAISE = "a front raise: front delts"
_LATERAL = "a lateral raise: side delts"
_REAR = "a reverse fly / face pull / rear-delt row: rear delts"
_SHRUG = "a shrug / trap raise: traps, not the lats or the delts"
_COMPOUND = "a compound or conditioning movement: graded against no single muscle"

# library key -> (audited primary target, one-line reason)
TARGET_OVERRIDES: dict[str, tuple[str, str]] = {
    # ── shoulders split: side ──
    "lateral_raise_dumbbell": (SIDE, _LATERAL),
    "lateral_raise_machine": (SIDE, _LATERAL),
    "lateral_raise_cable_single_arm": (SIDE, _LATERAL),
    "bent_arm_lateral_raises": (SIDE, _LATERAL),
    "db_cheat_laterals": (SIDE, _LATERAL),
    "side_lateral_raises": (SIDE, "a lateral raise (Hevy filed it under back): side delts"),
    "upright_row_barbell": (SIDE, "an upright row: side delts lead"),
    "db_abduction_rows": (SIDE, "an abduction row (elbows out and up): side delts"),
    "l_raise": (SIDE, "an L raise: side delts with the front delt"),
    # ── shoulders split: rear ──
    "face_pull": (REAR, _REAR),
    "chest_supported_reverse_fly_dumbbell": (REAR, _REAR),
    "rear_delt_reverse_fly_cable": (REAR, _REAR),
    "rear_delt_reverse_fly_machine": (REAR, _REAR),
    "rear_delt_fly": (REAR, _REAR),
    "bent_over_lateral_raise": (REAR, "a bent-over lateral raise is a reverse fly: rear delts"),
    "db_rear_delt_rows": (REAR, _REAR),
    "band_pullaparts": (REAR, "a band pull-apart: rear delts"),
    "doorway_face_pulls": (REAR, "a face pull (Hevy filed it under chest): rear delts"),
    "prone_w_raise": (REAR, "a prone W raise (Hevy filed it under chest): rear delts and the cuff"),
    "db_ucv_raise": (REAR, "a prone UCV raise (Hevy filed it under chest): rear delts and lower traps"),
    # ── shoulders split: front ──
    "landmine_press": (FRONT, _PRESS),
    "landmine_press_single_arm": (FRONT, _PRESS),
    "landmine_shoulder_press": (FRONT, _PRESS),
    "landmine_pushaway_presses": (FRONT, _PRESS),
    "alternating_rotation_shoulder_press": (FRONT, _PRESS),
    "db_single_arm_overhead_press": (FRONT, _PRESS),
    "db_wide_arc_shoulder_press": (FRONT, _PRESS),
    "military_press": (FRONT, _PRESS),
    "overhead_press_dumbbell": (FRONT, _PRESS),
    "seated_overhead_press_dumbbell": (FRONT, _PRESS),
    "shoulder_press_dumbbell": (FRONT, _PRESS),
    "shoulder_press": (FRONT, _PRESS),
    "seated_shoulder_press_machine": (FRONT, _PRESS),
    "arnold_press_dumbbell": (FRONT, _PRESS),
    "db_scoop_press": (FRONT, _PRESS),
    "db_speed_press": (FRONT, _PRESS),
    "kettlebell_press": (FRONT, _PRESS),
    "overhead_press": (FRONT, _PRESS),
    "overhead_press_barbell": (FRONT, _PRESS),
    "z_press": (FRONT, _PRESS),
    "push_press": (FRONT, _PRESS),
    "db_push_press": (FRONT, "a push press (Hevy filed it under other): front delts lead"),
    "pike_pushup": (FRONT, "a pike push-up is an overhead press pattern: front delts"),
    "handstand_push_up": (FRONT, "a handstand push-up is an overhead press pattern: front delts"),
    "rotational_single_arm_press": (FRONT, _PRESS),
    "modified_db_bradford_press": (FRONT, _PRESS),
    "front_raise_dumbbell": (FRONT, _FRONT_RAISE),
    "incline_db_front_raises": (FRONT, _FRONT_RAISE),
    "cable_stretch_front_raises": (FRONT, _FRONT_RAISE),
    # ── back / lats ──
    "kneeling_straight_arm_pulldown": ("back", "a straight-arm pulldown (Hevy filed it under shoulders): the lats"),
    "high_cable_row": ("back", "a row (Hevy filed it under chest): the back"),
    "ring_inverted_rows": ("back", "an inverted row (Hevy filed it under chest): the back"),
    "db_tripod_rows": ("back", "a row (Hevy filed it under triceps): the back"),
    "shoulder_pushdown": ("back", "a straight-arm pushdown (Hevy filed it under triceps): the lats"),
    "thoracic_extension": ("back", "a thoracic-extension drill: the upper back, not the delts"),
    "angels_and_devils": ("back", "a scapular mobility drill (Hevy filed it under biceps): the upper back"),
    # ── traps ──
    "shrug_barbell": ("traps", _SHRUG),
    "shrug_dumbbell": ("traps", _SHRUG),
    "shrug_machine": ("traps", _SHRUG),
    "seated_shrugs": ("traps", _SHRUG),
    "db_haney_shrugs": ("traps", _SHRUG),
    "eccentric_trap_raises": ("traps", _SHRUG),
    "banded_trap_raises_retreats": ("traps", _SHRUG),
    # ── chest ──
    "cable_low_to_high_crossovers": ("chest", "a low-to-high cable crossover is a fly (Hevy filed it under back): the chest"),
    "depth_ploymetric_push_up": ("chest", "a push-up (Hevy filed it under other): the chest"),
    # ── biceps / forearms ──
    "cross_body_hammer_curls": ("biceps", "a hammer curl (Hevy filed it under forearms): the elbow flexors"),
    "no_money_zottman_curls": ("biceps", "a Zottman curl (Hevy filed it under forearms): the elbow flexors"),
    "dead_arm_switch_grip_hang": ("forearms", "a hang: grip, not the back"),
    "dead_arm_hang": ("forearms", "a hang: grip, not the delts"),
    # ── quads (lunges, split squats, squats, step-ups Hevy filed elsewhere) ──
    "3_way_lunge": ("quadriceps", _LUNGE),
    "bulgarian_split_squat_with_twist": ("quadriceps", _LUNGE),
    "db_reverse_lunge": ("quadriceps", _LUNGE),
    "leaning_bulgarian_split_squats": ("quadriceps", _LUNGE),
    "side_lunge": ("quadriceps", "a side lunge: quads and adductors lead (Hevy filed it under hamstrings)"),
    "single_db_split_squats": ("quadriceps", _LUNGE),
    "tke_split_squat_drops": ("quadriceps", _LUNGE),
    "banded_db_alternate_reverse_lunge": ("quadriceps", _LUNGE),
    "reverse_lunge_front_rack": ("quadriceps", _LUNGE),
    "split_squat_switches": ("quadriceps", _LUNGE),
    "db_alt_reverse_sprinter_lunges": ("quadriceps", _LUNGE),
    "db_alt_side_lunges": ("quadriceps", "a side lunge: quads and adductors lead (Hevy filed it under hamstrings)"),
    "drop_step_lunges": ("quadriceps", _LUNGE),
    "offset_lunges": ("quadriceps", _LUNGE),
    "static_creeping_lunges": ("quadriceps", _LUNGE),
    "sprinter_switches": ("quadriceps", _LUNGE),
    "db_sumo_drop_squat": ("quadriceps", _SQUAT),
    "drop_squat": ("quadriceps", _SQUAT),
    "db_crush_grip_squats": ("quadriceps", _SQUAT),
    "db_heel_touch_squats": ("quadriceps", _SQUAT),
    "db_rocket_squats": ("quadriceps", _SQUAT),
    "prisoner_squats": ("quadriceps", _SQUAT),
    "banded_er_pause_squats": ("quadriceps", _SQUAT),
    "banded_overhead_squats": ("quadriceps", _SQUAT),
    "single_leg_wall_sit_time": ("quadriceps", "a wall sit: the quads (Hevy filed it under hamstrings)"),
    "db_bench_front_squats": ("quadriceps", "a front squat (Hevy filed it under glutes): the quads lead"),
    "db_cossack_squats": ("quadriceps", "a lateral squat (Hevy filed it under glutes): quads and adductors lead"),
    "db_step_up": ("quadriceps", _STEP),
    "leaning_step_ups": ("quadriceps", _STEP),
    "leaning_speed_step_ups": ("quadriceps", _STEP),
    "step_up_thrusts": ("quadriceps", _STEP),
    # ── glutes ──
    "alternating_db_curtsy_lunges": ("glutes", "a curtsy lunge: the glutes (medius) lead (Hevy filed it under hamstrings)"),
    "banded_clam_shells": ("glutes", "a clamshell: glute medius (Hevy filed it under hamstrings)"),
    "jane_fondas": ("glutes", "a side-lying leg raise: glute medius (Hevy filed it under hamstrings)"),
    "walking_hip_circles": ("glutes", "a hip-circle walk: the glutes (Hevy filed it under hamstrings)"),
    # ── hamstrings ──
    "slick_floor_bridge_hammer_curls": ("hamstrings", "a bridge leg curl (Hevy filed it under abs): the hamstrings"),
    "banded_bridge_curls": ("hamstrings", "a bridge leg curl (Hevy filed it under abs): the hamstrings"),
    "banded_static_bridge_curls": ("hamstrings", "a bridge leg curl (Hevy filed it under abs): the hamstrings"),
    # ── adductors ──
    "db_adductor_slides": ("adductors", "an adductor slide: the adductors (Hevy filed it under hamstrings)"),
    # ── abs ──
    "hover_hold_time": ("abs", "a plank hold (Hevy filed it under glutes): the abs"),
    "bird_dog": ("abs", "a bird dog is an anti-rotation core drill (Hevy filed it under glutes)"),
    "landmine_power_twists": ("abs", "a rotational core movement (Hevy filed it under back)"),
    "chinnies": ("abs", "a crunch variation (Hevy filed it under other)"),
    "finger_tip_mountain_climbers": ("abs", "a mountain climber: the core (Hevy filed it under hamstrings)"),
    "cable_pallof_press": ("abs", "#5861: a Pallof press is anti-rotation trunk work (Hevy filed it under shoulders); its aliases follow"),
    # ── compound / conditioning: graded against no single muscle ──
    "cable_squat_to_standing_row": (FULL, "squat + row (Hevy filed it under triceps): " + _COMPOUND),
    "reverse_lunge_curls": (FULL, "lunge + curl (Hevy filed it under biceps): " + _COMPOUND),
    "kettlebell_step_back_curl": (FULL, "lunge + curl (Hevy filed it under hamstrings): " + _COMPOUND),
    "curl_and_press": (FULL, "curl + press (Hevy filed it under biceps): " + _COMPOUND),
    "row_and_kickback": (FULL, "row + kickback: " + _COMPOUND),
    "db_single_leg_rdl_calf_raises": (FULL, "single-leg RDL + calf raise (Hevy filed it under calves): " + _COMPOUND),
    "landmine_thrusters": (FULL, "squat + press: " + _COMPOUND),
    "landmine_squat_and_press": (FULL, "squat + press: " + _COMPOUND),
    "kettlebell_thrusters": (FULL, "squat + press: " + _COMPOUND),
    "thruster_barbell": (FULL, "squat + press: " + _COMPOUND),
    "landmine_pivot_press": (FULL, "a rotational landmine press: " + _COMPOUND),
    "lunge_and_reach_bodyweight": (FULL, "lunge + reach (Hevy filed it under shoulders): " + _COMPOUND),
    "bottomed_out_squat_reaches": (FULL, "a deep-squat mobility reach (Hevy filed it under abs): " + _COMPOUND),
    "inchworms": (FULL, "an inchworm is a mobility flow (Hevy filed it under triceps): " + _COMPOUND),
    "spiderman_crawls": (FULL, "a crawl (Hevy filed it under chest): " + _COMPOUND),
    "alternating_side_kickthrough": (FULL, "an animal-flow kickthrough (Hevy filed it under forearms): " + _COMPOUND),
    "hurdle_over_unders": (FULL, "a hip-mobility hurdle drill: " + _COMPOUND),
    "single_leg_static_balance_with_eyes_closed": (FULL, "a balance drill: " + _COMPOUND),
    "walking_reverse_lunge_and_twist": (FULL, "lunge + trunk rotation: " + _COMPOUND),
    "sledgehammer_swings": (FULL, "a sledgehammer swing: " + _COMPOUND),
    "sandbag_shouldering": (FULL, "a sandbag shouldering: " + _COMPOUND),
    "db_shot_put": (FULL, "a shot-put throw: " + _COMPOUND),
    "farmers_walk": (FULL, "a farmer's carry trains grip, traps and trunk (Hevy filed it under abs): " + _COMPOUND),
    "farmers_walk_8d414b80": (FULL, "a farmer's carry trains grip, traps and trunk (Hevy filed it under abs): " + _COMPOUND),
    "sandbag_carry": (FULL, "a sandbag carry (Hevy filed it under abs): " + _COMPOUND),
    "db_gun_carries": (FULL, "a carry (Hevy filed it under biceps): " + _COMPOUND),
    "db_overhead_farmers_carry": (FULL, "an overhead carry (Hevy filed it under shoulders): " + _COMPOUND),
}
"""One reviewed row per move. Removing a row is a reviewed change too: `tests/test_target_audit_5857.py` pins the count."""

# regions for the audited vocabulary (the builder's `_REGION` covers Hevy's own muscles)
AUDIT_REGIONS: dict[str, str] = {
    SIDE: "upper",
    REAR: "upper",
    FRONT: "upper",
    "traps": "upper",
    "adductors": "lower",
    FULL: "full_body",
}


# ── the attribute audit (owner ruling 2026-11-12 on #5857, board recommendation 5 — blocking before approval) ────────────
# Rubric v2 counts an unknown joint as moderate, so every S/A row must carry rated joints, and two recorded attributes the
# board found wrong are fixed. Two layers, both applied by `deploy/build_exercise_library.py::apply_attribute_audit`:
#   * ATTRIBUTE_OVERRIDES — per movement, the named attributes replaced (a joint_stress map merges), one reason each;
#   * JOINT_RATINGS_BY_PATTERN — per movement pattern (and a title refinement), the rating that fills a joint still
#     `unknown`; a joint the curation or the rules already rated is never overwritten. One reason per row.
_L, _M, _H = "low", "moderate", "high"


def _js(spinal: str, shear: str, wrist: str, elbow: str, shoulder: str) -> dict[str, str]:
    return {"spinal_load": spinal, "shear": shear, "wrist": wrist, "elbow": elbow, "shoulder": shoulder}


ATTRIBUTE_OVERRIDES: dict[str, tuple[dict, str]] = {
    "chest_dip_weighted": (
        {
            "resistance_profile": "free_weight",
            "stability": "moderate",
            "equipment": ["dip_station", "weight_plate"],
            "joint_stress": _js(_L, _L, _L, _M, _H),
        },
        "a weighted dip is bodyweight plus a hung plate on the dip bars, not a selectorized machine; the shoulder is loaded "
        "deep in extension at the bottom (high), the elbow moderately",
    ),
    # ── #5861 reviewed-attribute pass: the misclassifications the engine audit (2026-11-12) found ──
    "crossover_stepup": (
        {"resistance_profile": "bodyweight", "equipment": ["plyo_box"], "stability": "low", "length_bias": "mid"}
        | {"joint_stress": _js(_L, _L, _L, _L, _L)},
        "a crossover step-up is a lateral step-up over a box, not a cable crossover fly (the 'crossover' word made it cable)",
    ),
    "push_up_weighted": (
        {"resistance_profile": "free_weight", "equipment": ["weight_plate"]},
        "a weighted push-up is the push-up plus an external load (a plate or vest): free weight, like the weighted dip",
    ),
    "pull_up_weighted": (
        {"resistance_profile": "free_weight", "equipment": ["pullup_bar", "weight_plate"]},
        "a weighted pull-up is bodyweight plus a hung plate: free weight, like the weighted dip",
    ),
    "chin_up_weighted": (
        {"resistance_profile": "free_weight", "equipment": ["pullup_bar", "weight_plate"]},
        "a weighted chin-up is bodyweight plus a hung plate: free weight, like the weighted dip",
    ),
    "rotator_cuff_external_rotation": (
        {"resistance_profile": "cable", "equipment": ["cable_stack"], "stability": "moderate", "joint_stress": _js(_L, _L, _L, _L, _L)},
        "a cuff external rotation is a light cable rotation at the side; the rule could not read its equipment",
    ),
    "db_external_rotation": (
        {"stability": "moderate", "joint_stress": _js(_L, _L, _L, _L, _L)},
        "a side-lying or supported dumbbell external rotation: light, the shoulder is not loaded hard",
    ),
    "rear_delt_reverse_fly_cable": (
        {"length_bias": "mid"},
        "a cable reverse fly keeps tension from the crossed (lengthened) start to the end, unlike a dumbbell whose torque "
        "peaks at the top: mid, like the machine reverse fly",
    ),
    "rear_delt_fly": (
        {"resistance_profile": "free_weight", "equipment": ["dumbbell"]},
        "a rear-delt fly is a dumbbell movement, not bodyweight",
    ),
    "bent_over_lateral_raise": (
        {"resistance_profile": "free_weight", "equipment": ["dumbbell"]},
        "a bent-over lateral raise is a dumbbell reverse fly, not bodyweight",
    ),
    "ab_wheel": (
        {"length_bias": "lengthened", "joint_stress": _js(_M, _L, _L, _L, _M)},
        "an ab-wheel rollout loads the abs at long length (anti-extension); the lumbar spine and the shoulder are loaded",
    ),
    "linear_leg_press": (
        {"resistance_profile": "machine_plate_loaded", "equipment": ["leg_press_machine"], "stability": "high"},
        "a linear leg press is a plate-loaded leg press, not bodyweight",
    ),
    "glute_ham_raise_pushup": (
        {"resistance_profile": "bodyweight"},
        "a glute-ham raise with a push-off is bodyweight knee flexion, not a band press",
    ),
    "walking_hip_circles": ({"family": "corrective"}, "a hip-circle walk is a mobility drill, not cardio"),
    "inverted_row": (
        {"resistance_profile": "bodyweight", "equipment": ["smith_machine"], "stability": "moderate"},
        "an inverted row is a bodyweight row under a fixed bar, not a selectorized machine",
    ),
    "lateral_raise_dumbbell": (
        {"stability": "moderate", "joint_stress": _js(_L, _L, _L, _L, _L)},
        "re-checked: a standing dumbbell lateral raise is light, the trunk is braced and the side delt is the limiter "
        "(moderate, not low); no joint is loaded hard",
    ),
    # ── #5861 FIX-DATA: the red-team data errors (2026-11-12) and the same classes found by the systematic pass ──
    "spider_curl": (
        {"stability": "high"},
        "a spider curl is chest-supported on an incline bench: the trunk is fixed, so stability is high, not low (red team)",
    ),
    "shrug_barbell": (
        {"stability": "moderate"},
        "a standing, bilateral shrug on a fixed bar path: the trunk is braced, stability is moderate, not low (red team)",
    ),
    "shrug_dumbbell": (
        {"stability": "moderate"},
        "a standing, bilateral shrug with the load at the sides: the trunk is braced, stability is moderate, not low (red team)",
    ),
    "incline_chest_fly_dumbbell": (
        {"stability": "moderate"},
        "a bench-supported dumbbell fly: the back is supported, stability is moderate, not low (same class as the spider curl)",
    ),
    "chest_fly_dumbbell": (
        {"stability": "moderate"},
        "a bench-supported dumbbell fly: the back is supported, stability is moderate, not low (same class as the spider curl)",
    ),
    "incline_db_skull_crushers": (
        {"stability": "moderate"},
        "a bench-supported extension: the back is supported, stability is moderate, not low (same class as the spider curl)",
    ),
    "prone_leg_curl": (
        {"resistance_profile": "machine_selectorized", "equipment": ["leg_curl_lying"], "stability": "high"},
        "a prone leg curl IS the lying leg-curl machine (a curl needs a loaded lever; Hevy's custom template carries no equipment, which read as bodyweight): one machine, one rating",
    ),
    "overhead_tricep_extension": (
        {"resistance_profile": "unknown", "equipment": ["other_unspecified"]},
        "a custom template with no equipment recorded (Hevy 'none') is not bodyweight: an overhead extension needs a load; equipment unknown until the owner names it",
    ),
    "tricep_extension": (
        {"resistance_profile": "unknown", "equipment": ["other_unspecified"]},
        "a custom template with no equipment recorded (Hevy 'none') is not bodyweight: a triceps extension needs a load; equipment unknown until the owner names it",
    ),
    "shoulder_press": (
        {"resistance_profile": "unknown", "equipment": ["other_unspecified"]},
        "a custom template with no equipment recorded (Hevy 'none') is not bodyweight: a shoulder press needs a load; equipment unknown until the owner names it",
    ),
    "seated_bicep_curls": (
        {"resistance_profile": "unknown", "equipment": ["other_unspecified"]},
        "a custom template with no equipment recorded (Hevy 'none') is not bodyweight: a curl needs a load; equipment unknown until the owner names it",
    ),
    "21s": (
        {"resistance_profile": "unknown", "equipment": ["other_unspecified"]},
        "a custom template with no equipment recorded (Hevy 'none') is not bodyweight: 21s (a loaded curl) needs a load; equipment unknown until the owner names it",
    ),
    "one_arm_bench_press": (
        {"resistance_profile": "unknown", "equipment": ["other_unspecified"]},
        "a custom template with no equipment recorded (Hevy 'none') is not bodyweight: a bench press needs a load; equipment unknown until the owner names it",
    ),
    "gorilla_row_kettlebell": (
        {"skill_complexity": "low"},
        "a gorilla row with kettlebells is the dumbbell gorilla row with another handle: the same skill demand, one rating",
    ),
}

# (pattern, title regex or None, joint ratings, reason) — the first matching row wins
JOINT_RATINGS_BY_PATTERN: list[tuple[str, str | None, dict[str, str], str]] = [
    ("chest_fly", None, _js(_L, _L, _L, _L, _M), "a fly loads the shoulder at stretch; trunk supported"),
    ("horizontal_press", r"push ?ups?|pushups?", _js(_L, _L, _M, _L, _M), "a push-up loads the wrist in extension and the shoulder"),
    ("horizontal_press", None, _js(_L, _L, _L, _L, _M), "a press loads the shoulder; the trunk is supported on a bench or pad"),
    ("vertical_press", r"seated|machine", _js(_L, _L, _L, _L, _M), "a seated overhead press loads the shoulder; the trunk is supported"),
    ("vertical_press", None, _js(_M, _L, _L, _L, _M), "a standing overhead press loads the shoulder and the spine"),
    ("press", None, _js(_L, _L, _L, _L, _M), "a press loads the shoulder"),
    ("vertical_pull", None, _js(_L, _L, _L, _L, _M), "a pull from overhead loads the shoulder in flexion"),
    (
        "horizontal_pull",
        r"bent over|dead row|gorilla|renegade|meadows|landmine|barbell",
        _js(_M, _M, _L, _L, _L),
        "an unsupported bent-over row loads the spine isometrically",
    ),
    ("horizontal_pull", None, _js(_L, _L, _L, _L, _L), "a supported, seated or cable row: the trunk is braced on a pad or seat"),
    ("squat", r"leg press|hack|pendulum|belt|smith|machine", _js(_L, _L, _L, _L, _L), "a machine squat: the spine is unloaded"),
    ("squat", r"barbell|front rack|zercher", _js(_M, _L, _L, _L, _L), "a barbell squat or lunge loads the spine"),
    ("squat", r"goblet|front squat", _js(_M, _L, _L, _L, _L), "a front-loaded squat loads the spine moderately"),
    ("squat", None, _js(_L, _L, _L, _L, _L), "a dumbbell, kettlebell or bodyweight squat, lunge or step-up: load hangs at the sides"),
    ("hinge", r"single leg|banded|good morning", _js(_L, _L, _L, _L, _L), "a light or single-leg hinge"),
    ("hinge", None, _js(_M, _M, _L, _L, _L), "a loaded hinge shears and loads the lumbar spine"),
    ("leg_curl", None, _js(_L, _L, _L, _L, _L), "a leg curl: machine-supported, no upper-body or spinal load"),
    ("leg_extension", None, _js(_L, _L, _L, _L, _L), "a leg extension: seated, no upper-body or spinal load"),
    ("calf", r"standing|donkey", _js(_M, _L, _L, _L, _L), "a standing calf raise loads the spine through the shoulders or the bar"),
    ("calf", None, _js(_L, _L, _L, _L, _L), "a seated or press calf raise: the spine is unloaded"),
    ("hip_extension", r"back extension|hyperextension|reverse hyper", _js(_M, _L, _L, _L, _L), "a back extension loads the lumbar spine"),
    ("hip_extension", None, _js(_L, _L, _L, _L, _L), "a hip thrust, bridge or kickback: the spine is supported"),
    ("curl", r"preacher|scott", _js(_L, _L, _L, _M, _L), "a preacher curl loads the elbow at full extension"),
    ("curl", r"cheat", _js(_M, _L, _L, _L, _L), "a cheat curl loads the spine through the swing"),
    ("curl", None, _js(_L, _L, _L, _L, _L), "a curl: no joint loaded hard"),
    ("triceps_extension", r"dip", _js(_L, _L, _L, _M, _M), "a dip loads the shoulder in extension and the elbow"),
    (
        "triceps_extension",
        r"overhead|skull|lying|french|jm",
        _js(_L, _L, _L, _M, _L),
        "an overhead or lying extension loads the elbow at stretch",
    ),
    ("triceps_extension", None, _js(_L, _L, _L, _L, _L), "a pushdown, pushaway or kickback: no joint loaded hard"),
    ("lateral_raise", r"upright", _js(_L, _L, _L, _L, _M), "an upright row loads the shoulder in internal rotation"),
    ("lateral_raise", None, _js(_L, _L, _L, _L, _L), "a lateral raise: light, no joint loaded hard"),
    ("rear_delt", None, _js(_L, _L, _L, _L, _L), "a reverse fly or face pull: light, no joint loaded hard"),
    ("shrug", None, _js(_M, _L, _L, _L, _L), "a shrug loads the spine through the arms"),
]


def joint_rating(e: dict, pattern: str) -> tuple[dict[str, str], str] | None:
    """The reviewed joint rating for a movement's pattern (and title), or None when no row covers it."""
    import re

    title = str(e.get("title") or "")
    if pattern == "other" and re.search(r"\bpress(es)?\b", title, re.I) and not re.search(r"press ?outs?|leg press|calf", title, re.I):
        pattern = "press"
    for pat, rx, ratings, reason in JOINT_RATINGS_BY_PATTERN:
        if pat == pattern and (rx is None or re.search(rx, title, re.I)):
            return ratings, reason
    return None


# ── #5861: the evaluation layer's reviewed inputs (deploy/exercise_library_objectives.py applies every table) ────────────
_SH = "shoulder_rotation"
# library key -> (pattern, job, reason): the title-regex pattern was wrong
PATTERN_OVERRIDES: dict[str, tuple[str, str, str]] = {
    "crossover_stepup": ("squat", "compound", "a step-up, not a chest fly"),
    "rotator_cuff_external_rotation": (_SH, "isolation", "a cuff external rotation, not trunk flexion"),
    "external_rotation": (_SH, "isolation", "a cuff external rotation, not trunk flexion"),
    "db_external_rotation": (_SH, "isolation", "a cuff external rotation, not trunk flexion"),
    "torso_rotation": ("core_rotation", "isolation", "a trunk rotation, not trunk flexion"),
    "bent_over_lateral_raise": ("rear_delt", "isolation", "a bent-over raise is a reverse fly"),
    "glute_ham_raise_pushup": ("leg_curl", "isolation", "a glute-ham raise is knee flexion, not a press"),
    "incline_db_kickbacks": ("triceps_extension", "isolation", "a triceps kickback, not a hip extension"),
    "inverted_db_tricep_kickbacks": ("triceps_extension", "isolation", "a triceps kickback, not a hip extension"),
    "triceps_kickback_dumbbell": ("triceps_extension", "isolation", "a triceps kickback, not a hip extension"),
    "db_straight_bar_curls": ("curl", "isolation", "a curl, not a row"),
    "shoulder_pushdown": ("vertical_pull", "isolation", "a straight-arm pushdown is a lat movement, not a triceps extension"),
    "rowing_machine": ("cardio", "isolation", "a rowing machine is conditioning, not a cable row"),
    "upright_row_barbell": ("lateral_raise", "compound", "an upright row is a side-delt raise pattern, not a horizontal pull"),
    # ── #5861 FIX-DATA: the title regex read "other" (a hyphen, a missing word) or the wrong pattern ──
    "side_bend_dumbbell": ("core_lateral_flexion", "isolation", "a side bend is lateral spinal flexion, not a crunch (red team)"),
    "saxon_side_bends": ("core_lateral_flexion", "isolation", "a side bend is lateral spinal flexion, not a crunch"),
    "side_crunch_slow_cadence": ("core_lateral_flexion", "isolation", "a side crunch is lateral spinal flexion"),
    "knee_push_up": ("horizontal_press", "compound", "a knee push-up is a push-up regression: a horizontal press (the hyphen hid it)"),
    "elbows_tucked_db_bench": ("horizontal_press", "compound", "a dumbbell bench press with the elbows tucked: a horizontal press"),
    "glute_ham_raise": ("leg_curl", "isolation", "a glute-ham raise is knee flexion against the body (a bodyweight leg curl)"),
    "physio_ball_glute_ham_raise": ("leg_curl", "isolation", "a physio-ball glute-ham raise is knee flexion (a bodyweight leg curl)"),
    "db_cheat_laterals": ("lateral_raise", "isolation", "a cheat lateral is a lateral raise (a family variant)"),
    "front_raise_dumbbell": ("lateral_raise", "isolation", "a front raise is a shoulder-raise pattern: single-joint, front delts"),
}

# P0/P1 ADDITIONS (#5861 L2) the title regex could not name — `other` can never match a slot's patterns, so each publishes its own
# pattern. Soft table: a build WITHOUT the additions simply has no such key (`exercise_library_objectives.evaluate_entry`); a
# test holds every key present in the committed library.
ADDITION_PATTERNS: dict[str, tuple[str, str, str]] = {
    "tibialis_raise": ("ankle_dorsiflexion", "isolation", "a tibialis raise is loaded ankle dorsiflexion (P0)"),
    "cable_serratus_punch": ("scapular_protraction", "isolation", "a serratus punch is loaded scapular protraction (P1)"),
    "controlled_forward_step_down": ("step_down", "compound", "a controlled step-down is an eccentric single-leg knee pattern (P1)"),
}

# library key -> reason: the primary strength lifts (squat, hinge, bench, overhead press, row, weighted pull) — the only
# movements that can reach S on strength. Practitioner consensus: the lifts strength is tested and built on.
STRENGTH_LIFTS: dict[str, str] = {
    "squat_barbell": "the back squat: the primary squat",
    "front_squat": "the front squat: a primary squat",
    "deadlift_barbell": "the conventional deadlift: the primary hinge",
    "deadlift_trap_bar": "the trap-bar deadlift: a primary hinge",
    "bench_press_barbell": "the barbell bench press: the primary horizontal press",
    "overhead_press_barbell": "the barbell overhead press: the primary vertical press",
    "bent_over_row_barbell": "the barbell row: the primary horizontal pull",
    "pull_up_weighted": "the weighted pull-up: the primary vertical pull",
    "chin_up_weighted": "the weighted chin-up: a primary vertical pull",
}

# library key -> (category, reason): where the title rule mislabels the movement's TYPE
CATEGORY_OVERRIDES: dict[str, tuple[str, str]] = {
    "face_pull": ("hypertrophy", "a face pull trains the rear delts (rated there) and the cuff (rated on mobility / joint function)"),
    "doorway_face_pulls": ("hypertrophy", "a face pull trains the rear delts (rated there) and the cuff (mobility / joint function)"),
    "cable_stretch_curls": ("hypertrophy", "a stretch-position cable curl, not a stretch"),
    "cable_stretch_front_raises": ("hypertrophy", "a stretch-position cable front raise, not a stretch"),
    "hover_hold": ("rehab_control", "a hover hold is a plank: low-load trunk control"),
    "hover_hold_time": ("rehab_control", "a hover hold is a plank: low-load trunk control"),
    "walking_hip_circles": ("mobility", "a hip-circle walk is a hip mobility drill"),
    "clap_push_ups": ("athletic", "a clap push-up is a plyometric (power) press"),
    "db_shot_put": ("athletic", "a shot-put throw is a power movement"),
    "sandbag_shouldering": ("athletic", "sandbag shouldering is a strongman power lift from the floor"),
    "sled_push": ("carry", "a sled push is loaded locomotion (the carry family), rated on functional, strength and conditioning"),
    "sled_drag": ("carry", "a sled pull is loaded locomotion (the carry family), rated on functional, strength and conditioning"),
    "dead_arm_hang": ("rehab_control", "a hang is the dead hang's variant: shoulder and grip control, not a growth movement"),
    "dead_arm_switch_grip_hang": ("rehab_control", "a hang is the dead hang's variant: shoulder and grip control, not a growth movement"),
}

# library key -> (objective_inputs fields, reason): where the input rule is wrong for the movement
INPUT_OVERRIDES: dict[str, tuple[dict, str]] = {
    "ab_wheel": ({"ceiling": "moderate", "ladder": True}, "progresses kneeling -> standing and by range: a ladder, not a fixed load"),
    "side_plank": ({"ceiling": "moderate"}, "progresses by lever, a top-leg raise and added load"),
    "sled_push": ({"functional": ["locomotion", "trunk_stability"]}, "pushing a loaded sled braces the trunk against the load"),
    "sled_drag": ({"functional": ["locomotion", "trunk_stability"]}, "dragging a loaded sled braces the trunk against the load"),
    "db_cossack_squats": ({"mobility": "loaded"}, "a cossack squat is loaded end-range hip abduction: strength through range"),
    "hip_thrust_machine": ({"limiter": "target"}, "the glutes end a hip-thrust set; the trunk is supported"),
    "kettlebell_turkish_get_up": (
        {"functional": ["unilateral", "trunk_stability", "multiplanar"]},
        "a get-up holds a single-arm overhead load through a multi-plane floor-to-stand transition",
    ),
    "landmine_squat": ({"ceiling": "moderate"}, "the bar end is held at the chest: the hands and upper back cap the load, like a goblet"),
    "pull_up_assisted": ({"ceiling": "moderate"}, "an assisted pull-up is a regression: its ceiling is the unassisted pull-up"),
    "chin_up_assisted": ({"ceiling": "moderate"}, "an assisted chin-up is a regression: its ceiling is the unassisted chin-up"),
    "triceps_dip_assisted": ({"ceiling": "moderate"}, "an assisted dip is a regression: its ceiling is the unassisted dip"),
    # ── #5861 FIX-DATA ──
    "rotator_cuff_external_rotation": (
        {"mobility": None},
        "cuff external rotation is loaded JOINT CAPACITY (rated on functional), not a mobility movement: it trains no range (red team)",
    ),
    "db_external_rotation": (
        {"mobility": None},
        "cuff external rotation is loaded JOINT CAPACITY (rated on functional), not a mobility movement: it trains no range (red team)",
    ),
    "dead_arm_hang": ({"mobility": "loaded"}, "the dead hang's variant: loaded shoulder and grip control (the head is rated loaded)"),
    "dead_arm_switch_grip_hang": (
        {"mobility": "loaded"},
        "the dead hang's variant: loaded shoulder and grip control (the head is rated loaded)",
    ),
    "glute_kickback_machine": (
        {"ceiling": "moderate"},
        "a single-leg lever stack caps the absolute load far below the glutes' capacity — the hip thrust carries the heavy glute "
        "loading — so the target cannot be overloaded to a high ceiling: A, not S (red team)",
    ),
    "cable_kickback": ({"ceiling": "moderate"}, "a single-leg cable kickback caps the absolute load far below the glutes' capacity"),
    "rear_kick_machine": ({"ceiling": "moderate"}, "a single-leg lever stack caps the absolute load far below the glutes' capacity"),
    "shrug_barbell": (
        {"limiter": "grip"},
        "a heavy shrug ends on grip before the traps tire (practitioner consensus; straps are the usual fix)",
    ),
    "seated_shrugs": (
        {"limiter": "grip"},
        "a heavy shrug ends on grip before the traps tire (practitioner consensus; straps are the usual fix)",
    ),
    "shrug_dumbbell": (
        {"limiter": "grip"},
        "a heavy shrug ends on grip before the traps tire (practitioner consensus; straps are the usual fix)",
    ),
}

# library key -> [(second target, limiter for that target, reason)]: the reviewed attribution beyond the primary
SECONDARY_ROWS: dict[str, list[tuple[str, str, str]]] = {
    "db_cossack_squats": [("adductors", "target", "the lateral squat loads the straight leg's adductors at long length")],
    "db_alt_side_lunges": [("adductors", "balance", "a side lunge loads the adductors of the trailing leg; balance ends the set")],
    "side_lunge": [("adductors", "balance", "a side lunge loads the adductors of the trailing leg; balance ends the set")],
    "sumo_squat_dumbbell": [("adductors", "target", "a wide-stance squat loads the adductors (magnus) through hip extension")],
    "db_sumo_drop_squat": [("adductors", "target", "a wide-stance squat loads the adductors (magnus) through hip extension")],
    "bulgarian_split_squat_dumbbell": [("glutes", "target", "a rear-foot-elevated split squat loads the front glute in deep hip flexion")],
}

# canonical head -> (exact-duplicate alias keys, {variant key: {axis: value}}). Every key keeps its own entry, template id and
# history; an alias takes the head's reviewed attributes (the same movement never scores twice). Axes: grip, stance, range,
# tempo, equipment, load, laterality.
CANONICAL_FAMILIES: dict[str, tuple[tuple[str, ...], dict[str, dict[str, str]]]] = {
    "triceps_pushdown": (
        ("tricep_pushdown",),
        {
            "triceps_rope_pushdown": {"grip": "rope"},
            "rocking_tricep_pushdown": {"tempo": "rocking"},
            "jackhammer_pushdowns": {"tempo": "rapid"},
            "tricep_pushdowns_for_time": {"tempo": "timed"},
            "tricep_pushdown_and_twist": {"grip": "rotating"},
        },
    ),
    "tricep_pushaway": (("tricep_pushaways",), {"kneeling_tricep_pushaway": {"stance": "kneeling"}}),
    "glute_kickback_machine": (("glute_machine_kickback",), {}),
    # #5861 FIX-DATA: one machine, one rating
    "lying_leg_curl_machine": (("prone_leg_curl",), {}),
    "seated_incline_curl_dumbbell": (("db_incline_curls",), {}),
    "gorilla_rows": ((), {"gorilla_row_kettlebell": {"equipment": "kettlebell"}}),
    "db_step_up": ((), {"step_up": {"resistance": "bodyweight"}}),
    "goblet_squat": ((), {"kettlebell_goblet_squat": {"equipment": "kettlebell"}}),
    "farmers_walk": (("farmers_walk_8d414b80",), {}),
    "overhead_press_barbell": (("military_press",), {}),
    "db_reverse_lunge": (
        ("reverse_lunge_dumbbell",),
        {
            "reverse_lunge": {"resistance": "bodyweight"},
            "reverse_lunge_barbell": {"equipment": "barbell"},
            "reverse_lunge_front_rack": {"equipment": "barbell_front_rack"},
            "banded_db_alternate_reverse_lunge": {"equipment": "band_and_dumbbell"},
        },
    ),
    "db_power_incline_bombs": (("db_incline_power_bombs",), {}),
    "high_knee_flying_20s": (("high_knee_flying_20s_2476151f",), {}),
    "cable_pallof_press": (("pallof_press", "pallof_press_cc55119b"), {}),
    "lateral_raise_machine": (("side_lateral_raises",), {}),
    "hover_hold": (("hover_hold_time",), {}),
    "chest_fly_machine": (("butterfly_pec_deck",), {}),
    "lat_pulldown_cable": (
        ("front_lat_pulldown",),
        {
            "lat_pulldown_close_grip_cable": {"grip": "close"},
            "lat_pulldown_wide_grip_cable": {"grip": "wide"},
            "lat_pulldown_machine": {"equipment": "machine"},
            "prone_grip_dual_handle_pulldowns": {"grip": "dual_handle_pronated"},
            "dual_handle_underhand_pulldowns": {"grip": "dual_handle_supinated"},
            "reverse_grip_lat_pulldown_cable": {"grip": "supinated"},
            "underhand_lat_pulldowns": {"grip": "supinated"},
            "rocking_pulldown": {"tempo": "rocking"},
        },
    ),
    "cable_fly_crossovers": (
        (),
        {
            "x_crossovers": {"range": "crossed_finish"},
            "cable_3d_crossovers": {"range": "multi_plane"},
            "cavaliere_crossover": {"range": "low_to_high_crossed"},
            "cable_low_to_high_crossovers": {"range": "low_to_high"},
            "low_cable_fly": {"range": "low_to_high"},
        },
    ),
    "seated_cable_row_bar_grip": (("seated_cable_row",), {"seated_cable_row_v_grip_cable": {"grip": "v_handle"}}),
    "high_cable_row": ((), {"1_arm_high_cable_row": {"laterality": "single_arm"}}),
    "straight_arm_pulldown": (("straight_arm_lat_pulldown_cable",), {"kneeling_straight_arm_pulldown": {"stance": "kneeling"}}),
    "pull_up": (
        (),
        {
            "pull_up_weighted": {"resistance": "weighted"},
            "pull_up_assisted": {"resistance": "assisted"},
            "pull_up_negative": {"tempo": "eccentric_only"},
        },
    ),
    "chin_up": ((), {"chin_up_weighted": {"resistance": "weighted"}, "chin_up_assisted": {"resistance": "assisted"}}),
    "push_up": (
        (),
        {
            "push_up_weighted": {"resistance": "weighted"},
            "incline_push_up": {"range": "incline_regression"},
            "knee_push_up": {"stance": "kneeling_regression"},
            "half_push_up": {"range": "partial"},
            "push_up_close_grip": {"grip": "close"},
            "finger_tip_pushups": {"grip": "finger_tip"},
        },
    ),
    "one_arm_push_up": (("1_arm_push_up",), {}),
    "leg_press_machine": (
        (),
        {
            "leg_press_horizontal_machine": {"equipment": "horizontal_leg_press"},
            "linear_leg_press": {"equipment": "linear_leg_press"},
            "single_leg_press": {"laterality": "single_leg"},
        },
    ),
    "leg_extension_machine": ((), {"single_leg_extension": {"laterality": "single_leg"}}),
    "rotator_cuff_external_rotation": (("external_rotation",), {"db_external_rotation": {"equipment": "dumbbell"}}),
    "plank": ((), {"rkc_plank": {"tempo": "max_tension"}}),
    "shrug_barbell": (
        (),
        {"shrug_dumbbell": {"equipment": "dumbbell"}, "shrug_machine": {"equipment": "machine"}, "seated_shrugs": {"stance": "seated"}},
    ),
    "standing_calf_raise_machine": ((), {"single_leg_standing_calf_raise_machine": {"laterality": "single_leg"}}),
    "standing_calf_raise_dumbbell": ((), {"single_leg_standing_calf_raise_dumbbell": {"laterality": "single_leg"}}),
    "hanging_knee_raise": ((), {"captains_chair_knee_raise": {"equipment": "captains_chair"}}),
    "hanging_leg_raise": ((), {"leg_raise_parallel_bars": {"equipment": "parallel_bars"}}),
    "jump_rope": (("jump_rope_drill",), {}),
    "ninja_tuck_jumps": (("ninja_tuck_jumps_quantity",), {}),
    "build_up_sprints_40": ((), {"build_up_sprints_60": {"range": "60_yards"}}),
    "dead_hang": ((), {"dead_arm_hang": {"grip": "dead_arm"}, "dead_arm_switch_grip_hang": {"grip": "switch"}}),
    "lateral_raise_dumbbell": ((), {"db_cheat_laterals": {"tempo": "cheat"}, "bent_arm_lateral_raises": {"grip": "bent_arm"}}),
    "rear_delt_fly": (("bent_over_lateral_raise",), {}),
    "rear_delt_reverse_fly_machine": (
        (),
        {"rear_delt_reverse_fly_cable": {"equipment": "cable"}, "chest_supported_reverse_fly_dumbbell": {"equipment": "dumbbell"}},
    ),
    "face_pull": ((), {"doorway_face_pulls": {"equipment": "doorway_anchor"}}),
    "straight_leg_deadlift": (("stiff_legged_deadlift",), {"db_stiff_legged_deadlift": {"equipment": "dumbbell"}}),
    "bicep_curl_dumbbell": ((), {"bicep_curl_for_time": {"tempo": "timed"}}),
    "suitcase_carry": ((), {"kettlebell_suitcase_carry": {"equipment": "kettlebell"}}),
    "split_squat_dumbbell": ((), {"single_db_split_squats": {"equipment": "single_dumbbell"}}),
    "bulgarian_split_squat_dumbbell": ((), {"leaning_bulgarian_split_squats": {"stance": "forward_lean"}}),
    "triceps_dip": ((), {"triceps_dip_assisted": {"resistance": "assisted"}}),
}

# Canonical families whose members include an L2 ADDITION (soft: a build WITHOUT the additions has no such member, so the
# family is skipped rather than a hard stop). `tests/test_data_fixes_5861.py` holds each present.
ADDITION_FAMILIES: dict[str, tuple[tuple[str, ...], dict[str, dict[str, str]]]] = {
    # the machine he rides IS Hevy's "Cycling": one family, one rating
    "cycling": (("recumbent_bike",), {}),
}

# The movements whose objective inputs were checked by hand in the #5861 pass (every movement in a hypertrophy S/A/B band
# or S/A on another objective after the pass, and every movement in the owner's anomaly list). Their non-hypertrophy ratings
# read `consensus`; the rest stay `none_reviewed`. `tests/test_objective_ratings_5861.py` holds that no S/A/B row is unreviewed.
REVIEWED_KEYS: frozenset[str] = frozenset(
    {
        "1_arm_high_cable_row",
        "1_arm_push_up",
        "1_legged_squat",
        "3_way_lunge",
        "3_way_rdl",
        "3d_curls",
        "ab_wheel",
        "abdominal_oblique_crunch",
        "air_bike",
        "alternating_db_curtsy_lunges",
        "alternating_rotation_shoulder_press",
        "back_extension_45",
        "back_extension_weighted",
        "band_pullaparts",
        "banded_db_alternate_reverse_lunge",
        "banded_good_mornings",
        "barbell_dead_rows",
        "behind_the_back_curl_cable",
        "belt_squat",
        "bench_press_barbell",
        "bench_press_close_grip_barbell",
        "bench_press_dumbbell",
        "bench_press_neutral_grip",
        "bent_over_lateral_raise",
        "bent_over_row_barbell",
        "bicep_curl_barbell",
        "bicep_curl_cable",
        "bicep_curl_dumbbell",
        "bicep_curl_for_time",
        "bicep_curl_machine",
        "bird_dog",
        "box_squat_barbell",
        "bulgarian_split_squat_dumbbell",
        "bulgarian_split_squat_jump",
        "bulgarian_split_squat_with_twist",
        "butterfly_pec_deck",
        "cable_3d_crossovers",
        "cable_crunch",
        "cable_fly_crossovers",
        "cable_kickback",
        "cable_low_to_high_crossovers",
        "cable_pallof_press",
        "cable_stretch_curls",
        "calf_press_machine",
        "captains_chair_knee_raise",
        "cavaliere_crossover",
        "chest_dip_weighted",
        "chest_fly_dumbbell",
        "chest_fly_machine",
        "chest_press_machine",
        "chest_supported_reverse_fly_dumbbell",
        "chest_supported_t_bar_row",
        "chin_up",
        "chin_up_assisted",
        "chin_up_weighted",
        "clean",
        "clean_and_jerk",
        "cobra_pushups",
        "crossover_stepup",
        "cycling",
        "db_abduction_rows",
        "db_adductor_slides",
        "db_alt_reverse_sprinter_lunges",
        "db_alt_side_lunges",
        "db_bench_front_squats",
        "db_chest_supported_rows",
        "db_cossack_squats",
        "db_crush_grip_squats",
        "db_external_rotation",
        "db_floor_flyes",
        "db_gun_carries",
        "db_heel_touch_squats",
        "db_haney_shrugs",
        "db_hip_thrust",
        "db_incline_curls",
        "db_lat_pullovers",
        "db_overhead_farmers_carry",
        "db_reach_across_single_leg_rdl",
        "db_rear_delt_rows",
        "db_reverse_lunge",
        "db_rocket_squats",
        "db_single_arm_overhead_press",
        "db_single_leg_rdl_calf_raises",
        "db_split_snatch_front_variation",
        "db_split_snatch_side_variation",
        "db_step_up",
        "db_stiff_legged_deadlift",
        "db_sumo_drop_squat",
        "db_t_bar_rows",
        "db_tripod_rows",
        "db_ucv_raise",
        "db_underhand_dip",
        "db_wide_arc_shoulder_press",
        "db_wrist_curl",
        "dead_hang",
        "deadlift_barbell",
        "deadlift_dumbbell",
        "deadlift_trap_bar",
        "deadlift_twist",
        "decline_bench_press_barbell",
        "decline_bench_press_dumbbell",
        "decline_chest_press_machine",
        "diamond_cutter_pushups",
        "dive_bomber_pushups",
        "doorway_face_pulls",
        "drop_squat",
        "drop_step_lunges",
        "dual_handle_underhand_pulldowns",
        "dumbbell_row",
        "elliptical_trainer",
        "external_rotation",
        "ez_bar_biceps_curl",
        "face_pull",
        "farmers_walk",
        "farmers_walk_8d414b80",
        "finger_tip_pushups",
        "forearm_curl",
        "front_lat_pulldown",
        "front_squat",
        "glute_bridge",
        "glute_kickback_machine",
        "glute_machine_kickback",
        "goblet_squat",
        "gorilla_row_kettlebell",
        "gorilla_rows",
        "hack_squat_machine",
        "half_push_up",
        "hammer_curl_dumbbell",
        "hang_clean_and_lunge_complex",
        "hang_clean_and_press",
        "high_cable_row",
        "hip_thrust_barbell",
        "hip_thrust_machine",
        "incline_bench_press_barbell",
        "incline_bench_press_dumbbell",
        "incline_chest_fly_dumbbell",
        "incline_chest_press_machine",
        "incline_db_skull_crushers",
        "incline_push_up",
        "inverted_row",
        "jackhammer_pushdowns",
        "jump_rope",
        "kettlebell_deadlift",
        "kettlebell_goblet_squat",
        "kettlebell_press",
        "kettlebell_step_back_curl",
        "kettlebell_suitcase_carry",
        "kettlebell_turkish_get_up",
        "knee_cobra_push_up",
        "kneeling_straight_arm_pulldown",
        "kneeling_tricep_pushaway",
        "landmine_1_arm_dead_row",
        "landmine_clean",
        "landmine_jump_squats",
        "landmine_offset_underhand_row",
        "landmine_parallel_rows",
        "landmine_press",
        "landmine_press_single_arm",
        "landmine_pushaway_presses",
        "landmine_row",
        "landmine_shoulder_press",
        "landmine_split_squat_hops",
        "landmine_squat",
        "lat_pulldown_cable",
        "lat_pulldown_close_grip_cable",
        "lat_pulldown_machine",
        "lat_pulldown_wide_grip_cable",
        "lateral_raise_cable_single_arm",
        "lateral_raise_dumbbell",
        "lateral_raise_machine",
        "leaning_bulgarian_split_squats",
        "leaning_speed_step_ups",
        "leaning_step_ups",
        "leg_extension_machine",
        "leg_press_horizontal_machine",
        "leg_press_machine",
        "linear_leg_press",
        "low_cable_fly",
        "low_cable_rotational_row",
        "lunge_barbell",
        "lunge_dumbbell",
        "lunge_jumps",
        "lying_db_tricep_extension",
        "lying_leg_curl_machine",
        "machine_crunch",
        "meadows_row",
        "medicine_ball_twist_throws",
        "military_press",
        "nordic_hamstring_curl",
        "offset_lunges",
        "one_arm_bench_press",
        "one_arm_push_up",
        "overhead_curl_cable",
        "overhead_dumbbell_lunge",
        "overhead_press_barbell",
        "overhead_press_dumbbell",
        "overhead_tricep_extension",
        "overhead_triceps_extension_cable",
        "pallof_press",
        "pallof_press_cc55119b",
        "pendulum_squat",
        "pike_pushup",
        "pistol_squat",
        "plyo_step_ups",
        "power_clean",
        "power_clean_complex",
        "preacher_curl_barbell",
        "preacher_curl_dumbbell",
        "preacher_curl_machine",
        "prone_grip_dual_handle_pulldowns",
        "prone_leg_curl",
        "prone_w_raise",
        "pull_up",
        "pull_up_assisted",
        "pull_up_negative",
        "pull_up_weighted",
        "pullover_dumbbell",
        "pullover_machine",
        "push_press",
        "push_up",
        "push_up_close_grip",
        "push_up_weighted",
        "rear_delt_fly",
        "rear_delt_reverse_fly_cable",
        "rear_delt_reverse_fly_machine",
        "rear_kick_machine",
        "renegade_row_dumbbell",
        "reverse_curl_dumbbell",
        "reverse_grip_lat_pulldown_cable",
        "reverse_lunge",
        "reverse_lunge_barbell",
        "reverse_lunge_curls",
        "reverse_lunge_dumbbell",
        "reverse_lunge_front_rack",
        "rocking_pulldown",
        "rocking_tricep_pushdown",
        "romanian_deadlift_barbell",
        "romanian_deadlift_dumbbell",
        "rotational_high_row",
        "rotational_landmine_split_snatch",
        "rotational_single_arm_press",
        "rotator_cuff_external_rotation",
        "rowing_machine",
        "running",
        "sandbag_carry",
        "scarecrow",
        "seated_cable_row",
        "seated_cable_row_bar_grip",
        "seated_cable_row_v_grip_cable",
        "seated_calf_raise",
        "seated_incline_curl_dumbbell",
        "seated_leg_curl",
        "seated_overhead_press_dumbbell",
        "seated_row_machine",
        "seated_shoulder_press_machine",
        "seated_shrugs",
        "shoulder_press",
        "shoulder_press_dumbbell",
        "shoulder_pushdown",
        "side_lateral_raises",
        "side_lunge",
        "side_plank",
        "single_db_split_squats",
        "single_leg_cable_rdl",
        "single_leg_extension",
        "single_leg_press",
        "single_leg_rdl_dumbbell",
        "single_leg_squat_with_jump",
        "single_leg_standing_calf_raise_dumbbell",
        "single_leg_standing_calf_raise_machine",
        "skullcrusher_barbell",
        "skullcrusher_dumbbell",
        "sled_drag",
        "sled_push",
        "snatch",
        "spider_curl",
        "split_squat_dumbbell",
        "split_squat_jumps",
        "split_squat_switches",
        "sprints",
        "squat_barbell",
        "squat_bodyweight",
        "squat_dumbbell",
        "standing_calf_raise_barbell",
        "standing_calf_raise_dumbbell",
        "standing_calf_raise_machine",
        "static_creeping_lunges",
        "step_up",
        "step_up_thrusts",
        "stiff_legged_deadlift",
        "straight_arm_lat_pulldown_cable",
        "straight_arm_pulldown",
        "straight_leg_deadlift",
        "suitcase_carry",
        "sumo_squat_dumbbell",
        "t_bar_row",
        "thruster_barbell",
        "tke_split_squat_drops",
        "torso_rotation",
        "trap_pulldown",
        "treadmill",
        "tricep_pushaway",
        "tricep_pushaways",
        "tricep_pushdown",
        "tricep_pushdown_and_twist",
        "tricep_pushdowns_for_time",
        "triceps_dip",
        "triceps_dip_assisted",
        "triceps_extension_cable",
        "triceps_extension_machine",
        "triceps_pushdown",
        "triceps_rope_pushdown",
        "underhand_barbell_dead_rows",
        "underhand_bench_press",
        "underhand_lat_pulldowns",
        "walking",
        "walking_lunge_dumbbell",
        "walking_reverse_lunge_and_twist",
        "wall_squat",
        "wrap_around_row",
        "x_crossovers",
        "z_press",
        "zercher_squat",
    }
)
