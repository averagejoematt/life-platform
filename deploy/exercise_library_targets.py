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
    "lateral_raise_dumbbell": (
        {"stability": "moderate", "joint_stress": _js(_L, _L, _L, _L, _L)},
        "re-checked: a standing dumbbell lateral raise is light, the trunk is braced and the side delt is the limiter "
        "(moderate, not low); no joint is loaded hard",
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
