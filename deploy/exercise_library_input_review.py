"""exercise_library_input_review.py — the reviewed-input pass for `config/exercise_library.json` (#5861 FIX2-DATA).

WHY. The second red team (2026-11-12) cross-tabbed hypertrophy tier against `objective_inputs.reviewed`: every S/A/B row was
reviewed, and nearly every C/D row was not. "C/D means nobody filled in the inputs, not poor exercise" — a Glute Ham Raise at
D, a machine shrug at D, because their attributes were `unknown` and the rubric scored unknown as nothing. Two fixes, both by
class: the rubric now scores an unknown input NEUTRAL and marks the row `provisional` (`training.quality_rubric` 3.2.0), and
this module is the hand review that removes the placeholder where it matters — every movement the owner has logged on at
least `LOGGED_MIN_SESSIONS` distinct days inside the library's own 5-year window, every movement named in the red team, and
every reviewed movement that still carried an unknown input.

WHAT IT HOLDS.
  * `REVIEW` — library key -> {attrs, inputs, why}: the attributes (`length_bias`, `stability`, `resistance_profile`,
    `skill_complexity`, `joint_stress`, `equipment`) and objective inputs (`quality_rubric.OBJECTIVE_INPUTS`) set by the
    review, and one reason. An entry with no attrs/inputs CONFIRMS the derived values (the reason says why they are right).
    Every key here reads `objective_inputs.reviewed: true`. A key not in the library is a hard stop.
  * `EVIDENCE_FORMS` — a trial-backed movement -> its untested forms for the trial's target: the evidence-ordering rule
    (`quality_rubric.evidence_ceiling`): an untested form ties the tested one at best, never outranks it.

Practitioner judgement on what each movement IS (its equipment, how stable it is, what ends the set) — no trial is claimed
by any row here, and none moves an evidence confidence. Titles and attributes only: never a load, a bodyweight or a note.
Applied by deploy/build_exercise_library.py (`apply_attributes`, after the attribute audit) and
deploy/exercise_library_objectives.py (`inputs_for`, after the input overrides) — the review always wins, and is recorded on
the entry as `attribute_audit.review`.
"""

from __future__ import annotations

from typing import Any

LOGGED_MIN_SESSIONS = 3  # "a movement he actually uses": logged on at least this many distinct days in the 5-year window
_L, _M, _H = "low", "moderate", "high"


def js(spinal: str, shear: str, wrist: str, elbow: str, shoulder: str) -> dict[str, str]:
    return {"spinal_load": spinal, "shear": shear, "wrist": wrist, "elbow": elbow, "shoulder": shoulder}


_LOW = js(_L, _L, _L, _L, _L)


def _r(why: str, attrs: dict[str, Any] | None = None, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"attrs": dict(attrs or {}), "inputs": dict(inputs or {}), "why": why}


_MID, _LEN, _SHORT = {"length_bias": "mid"}, {"length_bias": "lengthened"}, {"length_bias": "shortened"}
_NO_RANGE = "no range trained: loaded control of the cuff and scapula (joint capacity, rated on functional)"
_UNNAMED = (
    "custom template whose title does not identify the movement — left unknown (scored neutral, provisional) until the owner describes it"
)
_OWNER_EQ = "custom template with no equipment recorded: the load is unknown until the owner names it (scored neutral, provisional)"
# category values used below
_REHAB, _MOB, _ATH, _COND = "rehab_control", "mobility", "athletic", "conditioning"


def _rc(why: str, category: str, attrs: dict[str, Any] | None = None, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    return _r(why, attrs, inputs) | {"category": category}


REVIEW: dict[str, dict[str, Any]] = {
    # ── the red team's named rows ───────────────────────────────────────────────────────────────────────────────────
    "glute_ham_raise": _r(
        "a glute-ham raise is bodyweight knee flexion from full extension on a GHD (thighs pinned: stable), the hamstrings loaded "
        "long at the knee like the Nordic; it ladders (assisted -> bodyweight -> a held plate). Unreviewed inputs read it D (red team)",
        {"resistance_profile": "bodyweight", "stability": "high", "skill_complexity": "moderate", "joint_stress": _LOW} | _LEN,
        {"ceiling": "moderate", "ladder": True, "resistance_class": "bodyweight"},
    ),
    "shrug_machine": _r(
        "a machine shrug: a guided lever or pin stack (stable, small steps); like every shrug it ends on grip before the traps tire. "
        "Unreviewed inputs read it D (red team)",
        {"resistance_profile": "machine_selectorized", "stability": "high"},
        {"ceiling": "high", "limiter": "grip", "resistance_class": "submaximal"},
    ),
    "physio_ball_glute_ham_raise": _r(
        "a stability-ball hamstring curl: bodyweight, the ball rolls (low stability), progressed two-leg -> one-leg, not by load",
        {"resistance_profile": "bodyweight", "stability": "low", "joint_stress": _LOW} | _MID,
        {"ceiling": "low", "resistance_class": "bodyweight"},
    ),
    # ── a one-field override used to imply a full review; these were reviewed in full here ────────────────────────────
    "shrug_barbell": _r("confirmed: a barbell shrug, short by nature, grip-limited (the input override), moderate spinal load"),
    "shrug_dumbbell": _r("confirmed: a dumbbell shrug, grip-limited (the input override)"),
    "dead_arm_hang": _r("confirmed: the dead hang's variant, loaded overhead shoulder range and grip"),
    "dead_arm_switch_grip_hang": _r("confirmed: the dead hang's variant, loaded overhead shoulder range and grip"),
    # ── the logged hypertrophy rows (>= 3 sessions in the window) ─────────────────────────────────────────────────────
    "21s": _r("21s are a partial-then-full curl: mid length. " + _OWNER_EQ, _MID),
    "arnold_press_dumbbell": _r("an Arnold press is a dumbbell overhead press with a rotation: mid length like every press", _MID),
    "bench_dip": _r(
        "a bench dip is bodyweight on a flat bench (moderately stable); its progression ends at a plate on the lap — a regression "
        "of the bar dip, not its ladder (ceiling low); the shoulder is loaded deep in extension (high), as on the dip bars",
        {"resistance_profile": "bodyweight", "stability": "moderate", "joint_stress": {"shoulder": _H}},
        {"ceiling": "low", "ladder": False, "resistance_class": "bodyweight"},
    ),
    "cable_pull_through": _r(
        "a cable pull-through is a standing cable hinge: the glutes loaded from hip flexion (scored mid, the glute cap), the "
        "cable pulls the lifter back so heavy loads are hard to hold (ceiling moderate), and the lumbar spine is loaded by the hinge",
        {"joint_stress": {"spinal_load": _M}} | _LEN,
        {"ceiling": "moderate"},
    ),
    "cable_twist_up_to_down": _r(
        "a high-to-low cable woodchop: trunk rotation under a cable (mid length, standing), the spine loaded in rotation",
        {"joint_stress": js(_M, _L, _L, _L, _L)} | _MID,
    ),
    "chest_fly_band": _r(
        "a band fly's tension rises as the arms close, so it loads the chest SHORT, not at the stretch; standing (moderate)",
        {"stability": "moderate"} | _SHORT,
    ),
    "chinnies": _r("a seated crunch-and-tuck: loaded trunk flexion, short, bodyweight", {"joint_stress": _LOW} | _SHORT),
    "concentration_curl": _r(
        "a concentration curl is seated with the elbow braced on the thigh: stable (high), the biceps loaded short",
        {"stability": "high"},
    ),
    "cross_body_hammer_curls": _r("a cross-body hammer curl: a standing dumbbell curl, mid length", _MID),
    "db_drag_curls": _r("a drag curl keeps the bar path against the body: a standing dumbbell curl, mid length", _MID),
    "db_jm_press": _r(
        "a JM press is a lying close press-extension hybrid: on a bench (moderate), the triceps at mid length, the elbow loaded",
        {"stability": "moderate"} | _MID,
    ),
    "db_no_money_curls": _r("a curl with the elbows pinned and the forearms rotated out: mid length", _MID),
    "db_push_press": _r(
        "a dumbbell push press drives the press with the legs: mid length, a timing skill (moderate)",
        {"skill_complexity": "moderate"} | _MID,
    ),
    "db_speed_press": _r("a dumbbell press done for speed: the movement is a press (mid length); speed is the protocol", _MID),
    "db_straight_bar_curls": _r("a standing dumbbell curl: mid length", _MID),
    "db_waiter_curls": _r("a waiter curl holds one dumbbell by its head: a standing curl, mid length", _MID),
    "double_db_frog_press": _r(_UNNAMED),
    "elbows_tucked_db_bench": _r(
        "a dumbbell bench press with the elbows tucked: on a bench (moderate), mid length, the shoulder loaded",
        {"stability": "moderate", "joint_stress": js(_L, _L, _L, _L, _M)} | _MID,
    ),
    "floor_press_dumbbell": _r(
        "a floor press stops where the elbows touch the floor, cutting off the stretch: short; lying (moderate)",
        {"stability": "moderate"} | _SHORT,
    ),
    "db_cheat_laterals": _r(
        "a cheat lateral is the dumbbell lateral raise (its family head) with a deliberate swing: the head's short length and "
        "stance, less control (low stability), the swing loading the spine",
        {"stability": "low", "joint_stress": js(_M, _L, _L, _L, _L)} | _SHORT,
    ),
    "front_raise_dumbbell": _r("confirmed: a front raise, short, light; no joint loaded hard", {"joint_stress": _LOW}),
    "hip_buck": _r(_UNNAMED),
    "incline_db_squeeze_press": _r(
        "an incline dumbbell press with the bells squeezed together: on a bench (moderate), mid length",
        {"stability": "moderate"} | _MID,
    ),
    "kneeling_banded_hip_thrusts": _r(
        "a kneeling band hip thrust: bodyweight-supported kneeling (moderate), band resistance peaks at lockout",
        {"stability": "moderate"},
    ),
    "modified_db_bradford_press": _r(
        "a Bradford press moves the bells front-to-back over the head: a standing press, mid length",
        _MID,
    ),
    "nsfw": _r(_UNNAMED),
    "prowler_pushup": _r("a push-up on the prowler's handles: a push-up (mid length), bodyweight", _MID),
    "reverse_hyperextension": _r(
        "a reverse hyper swings loaded legs from a pad (moderate stability), plate-loaded on its machine; the swing loads and "
        "shears the lumbar spine (moderate)",
        {"resistance_profile": "machine_plate_loaded", "joint_stress": {"spinal_load": _M, "shear": _M}},
        {"ceiling": "moderate", "resistance_class": "submaximal"},
    ),
    "russian_twist_bodyweight": _r(
        "a Russian twist: seated trunk rotation, mid length, bodyweight; the spine is loaded in rotation",
        {"joint_stress": js(_M, _L, _L, _L, _L)} | _MID,
    ),
    "side_bend_dumbbell": _r(
        "a dumbbell side bend: lateral flexion with the load hanging (mid length), the spine loaded sideways",
        {"joint_stress": js(_M, _L, _L, _L, _L)} | _MID,
    ),
    "triceps_kickback_dumbbell": _r("confirmed: a kickback's torque peaks at lockout (short); standing, free (low stability)"),
    "upright_row_barbell": _r("confirmed: an upright row, short for the side delts, the shoulder loaded in internal rotation"),
    "v_up": _r("a V-up: trunk flexion, short, bodyweight; no joint loaded hard", {"joint_stress": _LOW}),
    "wall_sit": _r(
        "a wall sit: an isometric quad hold, back on the wall (stable), bodyweight; a plate on the lap is the only load step",
        {"resistance_profile": "bodyweight", "stability": "high", "joint_stress": _LOW, "equipment": ["bodyweight"]} | _MID,
        {"ceiling": "low", "resistance_class": "bodyweight"},
    ),
    # ── logged movements that are not growth movements: typed by what they are ─────────────────────────────────────────
    "banded_overhead_squats": _rc(
        "a band held overhead through a bodyweight squat: an overhead-squat mobility drill, not a loaded squat",
        _MOB,
        {"stability": "moderate", "length_bias": "not_applicable"},
        {"mobility": "active"},
    ),
    "banded_prone_press": _rc(
        "a prone band press overhead: lower-trap and scapular control. " + _NO_RANGE, _REHAB, {}, {"functional": ["joint_capacity"]}
    ),
    "banded_trap_raises_retreats": _rc(
        "band trap raises and retractions: scapular control. " + _NO_RANGE,
        _REHAB,
        {"stability": "moderate", "length_bias": "not_applicable", "joint_stress": _LOW},
        {"functional": ["joint_capacity"]},
    ),
    "db_urlachers": _rc(
        "the Urlacher (a dumbbell row, rotate, press complex): upper-back and cuff control, not a growth movement. " + _NO_RANGE,
        _REHAB,
        {"length_bias": "not_applicable", "joint_stress": js(_L, _L, _L, _L, _M)},
        {"functional": ["joint_capacity"]},
    ),
    "sword_raise": _rc(
        "a sword draw: a diagonal cross-body raise for the rear delt, lower trap and cuff. " + _NO_RANGE,
        _REHAB,
        {"stability": "moderate", "resistance_profile": "cable", "length_bias": "not_applicable", "joint_stress": _LOW},
        {"ceiling": "moderate", "functional": ["joint_capacity"]},
    ),
    "jane_fondas": _rc(
        "a side-lying leg raise: low-load glute-medius control (hip abduction), not a growth movement",
        _REHAB,
        {"stability": "high", "length_bias": "not_applicable", "joint_stress": _LOW},
        {"mobility": "motor_control"},
    ),
    "standing_banded_fondas": _rc(
        "a standing band hip abduction: glute-medius activation and single-leg balance, not a growth movement",
        _REHAB,
        {"length_bias": "not_applicable", "joint_stress": _LOW},
        {"functional": ["balance"], "mobility": "motor_control"},
    ),
    "superman": _rc(
        "a prone superman hold: low-load back-extensor endurance, not a growth movement",
        _REHAB,
        {"length_bias": "not_applicable", "joint_stress": js(_M, _L, _L, _L, _L)},
        {"functional": ["trunk_stability"], "mobility": "motor_control"},
    ),
    "superman_press_outs": _rc(
        "a prone superman with the arms pressing out: back-extensor and lower-trap endurance, not a growth movement",
        _REHAB,
        {"length_bias": "not_applicable", "joint_stress": js(_M, _L, _L, _L, _L)},
        {"functional": ["trunk_stability"], "mobility": "motor_control"},
    ),
    "long_leg_marches": _rc(
        "supine long-lever marches: low-load anti-extension trunk control with hip flexion, not a growth movement",
        _REHAB,
        {"length_bias": "not_applicable", "joint_stress": _LOW},
        {"functional": ["trunk_stability"], "mobility": "motor_control"},
    ),
    "single_db_press_outs": _rc(
        "a dumbbell held at the chest and pressed out: an anti-extension trunk hold, not a growth movement",
        _REHAB,
        {"length_bias": "not_applicable", "joint_stress": js(_L, _L, _L, _L, _M)},
        {"functional": ["trunk_stability"]},
    ),
    "reverse_iron_cross": _rc(
        "the reverse iron cross (prone scorpion): a dynamic hip and thoracic mobility drill",
        _MOB,
        {"length_bias": "not_applicable", "joint_stress": _LOW},
        {"mobility": "active"},
    ),
    "sprinter_switches": _rc(
        "sprinter switches: fast alternating split-stance switches, a plyometric drill",
        _ATH,
        {"length_bias": "not_applicable", "joint_stress": _LOW},
        {"functional": ["unilateral", "power"]},
    ),
    "rope_pulling": _rc(
        "a hand-over-hand rope pull (a sled on a rope): grip, upper back and conditioning, not a growth movement",
        _COND,
        {"resistance_profile": "sled", "stability": "moderate", "length_bias": "not_applicable", "joint_stress": js(_M, _L, _L, _L, _L)},
        {
            "ceiling": "high",
            "functional": ["trunk_stability"],
            "conditioning": {"aerobic": "moderate", "control": "moderate", "impact": "low", "recovery": "moderate"},
        },
    ),
    "flag": _rc(
        "the flag (human or dragon flag): an advanced calisthenics trunk hold, high skill",
        _ATH,
        {"length_bias": "not_applicable", "joint_stress": js(_M, _L, _L, _L, _M)},
        {"functional": ["trunk_stability"]},
    ),
    "hang_high_pull": _rc(
        "the template now reads '180 Squat Jumps' (the key is its older name): a bodyweight jump with a half turn — power, "
        "multiplanar landing",
        _ATH,
        {"resistance_profile": "bodyweight", "equipment": ["bodyweight"], "stability": "moderate", "joint_stress": _LOW},
        {"ceiling": "low", "resistance_class": "bodyweight", "functional": ["power", "multiplanar"], "systemic_fatigue": "moderate"},
    ),
    "double_swings": _r(
        "a double kettlebell swing: the swing with a bell in each hand (the title omits the implement)",
        {"resistance_profile": "free_weight", "equipment": ["kettlebell"], "stability": "low", "length_bias": "not_applicable"},
        {"ceiling": "moderate", "resistance_class": "submaximal"},
    ),
    "sandbag_clean": _r(
        "a sandbag clean: a strongman floor-to-chest power lift; the bag is awkward (low stability), the spine loaded",
        {"joint_stress": js(_M, _M, _L, _L, _L)},
    ),
    "90_degree_max_jump_turns": _r(
        "a jump with a quarter turn: power and multiplanar landing", {"joint_stress": _LOW}, {"functional": ["power", "multiplanar"]}
    ),
    "box_jump": _r("confirmed: a box jump, power with a soft landing (the box limits the impact)", {"joint_stress": _LOW}),
    "high_pogos": _r("confirmed: pogo hops, ankle stiffness and power", {"joint_stress": _LOW}),
    "low_pogos": _r("confirmed: low pogo hops, ankle stiffness", {"joint_stress": _LOW}),
    "side_to_side_hops": _r(
        "confirmed: lateral hops, power and multiplanar landing", {"joint_stress": _LOW}, {"functional": ["power", "multiplanar"]}
    ),
    "lying_on_back_to_10_yard_sprint": _r("confirmed: a get-up-and-sprint drill", {"joint_stress": _LOW}),
    "db_high_pulls": _r("confirmed: a dumbbell high pull, a power pull", {"joint_stress": js(_M, _L, _L, _L, _M)}),
    "kettlebell_high_pull": _r("confirmed: a kettlebell high pull, a power pull"),
    "kettlebell_swing": _r("confirmed: the kettlebell swing, a ballistic hinge (athletic, rated on functional and conditioning)"),
    "plyo_inverted_rows": _r("confirmed: an explosive inverted row, a bodyweight power pull"),
    "angels_and_devils": _r("confirmed: an active shoulder mobility drill", {"joint_stress": _LOW}),
    "bottomed_out_squat_reaches": _r("confirmed: a deep-squat hold with reaches, active hip and thoracic mobility"),
    "bridge_and_reach_over": _r("confirmed: a bridge with a reach, hip and thoracic motor control", {"joint_stress": _LOW}),
    "hurdle_over_unders": _r("confirmed: hip mobility over and under a hurdle", {"length_bias": "not_applicable", "joint_stress": _LOW}),
    "inchworms": _r("confirmed: an active hamstring and shoulder mobility drill", {"joint_stress": _LOW}),
    "leg_swings": _r("confirmed: dynamic hip mobility", {"length_bias": "not_applicable"}),
    "stretching": _r("confirmed: passive stretching", {"joint_stress": _LOW}),
    "t_spine_rotations": _r("confirmed: active thoracic rotation", {"joint_stress": _LOW}),
    "er_wall_slides": _r(
        "external-rotation wall slides: active shoulder range with cuff control",
        {"joint_stress": _LOW},
        {"functional": ["joint_capacity"]},
    ),
    "hip_band_ladder": _r("a banded lateral-walk ladder: glute-medius control", {"stability": "moderate", "joint_stress": _LOW}),
    "dead_arm_scap_rows": _r("confirmed: a scapular row, joint capacity"),
    "dead_bug": _r("confirmed: a dead bug, anti-extension trunk control"),
    "plank": _r("confirmed: a plank, anti-extension trunk control", {"joint_stress": _LOW}),
    "leaning_scapular_push_up": _r("confirmed: a scapular push-up, serratus control"),
    "lunge_and_reach_bodyweight": _r("confirmed: a bodyweight lunge with a reach, rated whole-body (balance-limited)"),
    # ── reviewed movements in the S/A band that still carried an unknown input ─────────────────────────────────────────
    "3d_curls": _r(
        "a machine curl series through three arm positions: its length bias changes by position, so it stays unknown (scored neutral)"
    ),
    "db_crush_grip_squats": _r("a dumbbell squat (the plural 'squats' slipped the length rule): lengthened, like the goblet squat", _LEN),
    "db_heel_touch_squats": _r("a dumbbell squat (the plural 'squats' slipped the length rule): lengthened, like the goblet squat", _LEN),
    "db_rocket_squats": _r("a dumbbell squat (the plural 'squats' slipped the length rule): lengthened, like the goblet squat", _LEN),
    "push_press": _r("a barbell push press: a press driven by the legs, mid length", _MID),
    "z_press": _r("a Z press: a seated-on-the-floor barbell overhead press, mid length", _MID),
    "rotational_single_arm_press": _r(
        "a rotational single-arm (landmine) press: mid length, the spine loaded in rotation",
        {"joint_stress": js(_M, _L, _L, _L, _M)} | _MID,
    ),
    "thruster_barbell": _r("a thruster (squat + press): rated whole-body", {"joint_stress": js(_M, _L, _L, _L, _M)} | _MID),
    "rear_kick_machine": _r("a kneeling glute kickback machine: the glutes at mid length (the glute cap)", _MID),
    "torso_rotation": _r(
        "a seated torso-rotation machine: obliques at mid length, the spine loaded in rotation",
        {"joint_stress": js(_M, _L, _L, _L, _L)} | _MID,
    ),
    "triceps_extension_machine": _r(
        "a machine triceps extension: whether its arm position is overhead (long head lengthened) or in front is model-specific, "
        "so its length stays unknown (scored neutral) until the owner names the machine"
    ),
    "overhead_tricep_extension": _r("an overhead extension: the long head lengthened. " + _OWNER_EQ),
    "shoulder_press": _r("a shoulder press: mid length. " + _OWNER_EQ),
    # ── the cuff / scapular class (no range trained): joints rated so the row reads whole ────────────────────────────
    "prone_w_raise": _r("a prone W raise: cuff external rotation with lower-trap control. " + _NO_RANGE, {"joint_stress": _LOW}),
    "db_ucv_raise": _r("a UCV raise: lower-trap and serratus upward rotation. " + _NO_RANGE, {"joint_stress": _LOW}),
    # ── #5861 FIX4 (fourth red team) ──
    "pull_up_band": _r(
        "Hevy's built-in band-assisted pull-up: the lats at long length on a bar, the band taking a share of bodyweight (the band's "
        "thickness is the load step); a regression rung of the pull-up ladder, so its ceiling is the unassisted pull-up (moderate)",
        inputs={"ladder": True},
    ),
}

EVIDENCE_FORMS: dict[str, dict[str, Any]] = {
    "hip_thrust_barbell": {
        "target": "glutes",
        "forms": ("hip_thrust_machine", "db_hip_thrust"),
        "why": "the hip-thrust trial (Plotkin 2023) used a barbell; the machine and dumbbell forms are the same movement, untested",
    },
}


def apply_attributes(movements: dict[str, dict[str, Any]]) -> None:
    """The review's attribute half, in place (a joint_stress map merges joint by joint). A key not in the library is a
    hard stop — a review never vanishes silently."""
    missing = sorted(k for k in list(REVIEW) + list(EVIDENCE_FORMS) if k not in movements)
    missing += sorted(f for spec in EVIDENCE_FORMS.values() for f in spec["forms"] if f not in movements)
    if missing:
        raise SystemExit(f"input review: rows for movements not in the library: {missing}")
    for key, row in REVIEW.items():
        e = movements[key]
        for field, value in row["attrs"].items():
            e[field] = {**(e.get(field) or {}), **value} if field == "joint_stress" else value


def inputs_for(key: str) -> dict[str, Any]:
    """The review's objective-input half for one movement ({} when the review sets none)."""
    return dict((REVIEW.get(key) or {}).get("inputs") or {})


def audit_record(key: str) -> dict[str, Any]:
    row = REVIEW[key]
    return {"attrs": sorted(row["attrs"]), "inputs": sorted(row["inputs"]), "why": row["why"], "pass": "#5861 FIX2-DATA"}


# ── #5861 FIX3 (third red team): two CLASS rules over the reviewed attributes ─────────────────────────────────────────
SHOULDER_PROVOKING = {
    "patterns": ("lateral_raise", "rear_delt", "shoulder_rotation"),
    "title": r"face ?pulls?|upright row|reverse fly|rear delt|external rotation|internal rotation|scaption|\by[- ]raise",
    "floor": _M,
    "why": "third red team (2026-11-13): abduction toward 90 degrees, horizontal abduction and loaded rotation are the classic "
    "painful-arc provocations a physio protects first under a shoulder flag; 'light, no joint loaded hard' rated them low, so a "
    "6/10 sharp shoulder note left lateral raises and face pulls at RPE 9-10. The shoulder is rated at least moderate: the pain "
    "rule (live_program.PAIN_RULE) then caps or avoids them. Practitioner consensus, not a trial.",
}
"""Shoulder-provoking work: the shoulder joint stress is raised to at least `floor` (never lowered from high)."""
ELBOW_PROVOKING = {
    "patterns": ("triceps_extension", "curl"),
    "not_title": r"wrist|forearm|bridge|step back",
    "floor": _M,
    "why": "fifth red team (2026-11-13): a pushdown, pushaway, kickback or curl rated the elbow LOW ('no joint loaded hard'), so "
    "an elbow-pain flag swapped one loaded elbow extension for another and served it to failure. A loaded elbow extension or "
    "flexion loads the elbow: the working joint is rated at least moderate as a PAIN-MAP floor (like the shoulder's), so the "
    "pain rule caps or avoids it; the rubric's joint cost keeps the healthy-joint rating (`provocation_floor`). Wrist and "
    "forearm curls (the wrist works) and the bridge / step-back 'curls' (a leg or a lunge) are not elbow work. Practitioner "
    "consensus, not a trial.",
}
"""Elbow-dominant isolation (triceps extension, curl): the elbow joint stress is raised to at least `floor` (pain map only)."""
SPINE_AT_SIDES = {
    "pattern": "squat",
    "equipment": ("dumbbell", "kettlebell"),
    "not_title": r"goblet|front|zercher|overhead|rack|barbell|landmine|jump|hop|plyo",
    "level": _L,
    "why": "third red team (2026-11-13): one spine-loading definition — a split squat, lunge or step-up with the load hanging at "
    "the sides loads the legs, not the spine; two such rows read moderate and the rest low, so the stacking rule 'swapped' a "
    "Bulgarian split squat for a reverse lunge that loads the spine the same (a label moved, not the fatigue). Every row of the "
    "class reads low, the pattern table's own rating for it (exercise_library_targets.JOINT_RATINGS_BY_PATTERN).",
}
"""Squat-pattern work with dumbbells/kettlebells at the sides: spinal load `level` for the whole class."""


# ── #5861 FIX4 (fourth red team): the knee and hip PAIN MAP ───────────────────────────────────────────────────────────
KNEE_HIP: dict[str, Any] = {
    "knee": (
        # (rule name, level, pattern set or None, title regex or None) — first match wins, in order
        ("knee_regression", _M, None, r"box squat|wall squat|wall sit|spanish squat"),
        ("knee_dominant", _H, ("squat", "leg_extension", "step_down"), None),
        (
            "knee_lower_other",
            _H,
            ("other", "olympic", "cardio"),
            r"lunge|split squat|step ?ups?|stepup|squat|pistol|skater|jump|hop|bound|pogo|thruster|burpee|tuck",
        ),
        ("knee_hinge_soft", _L, ("hinge",), r"romanian|\brdl\b|stiff|good ?morning|single leg deadlift"),
        ("knee_off_floor", _M, ("hinge", "olympic"), r"deadlift|trap bar|hex bar|sumo|clean|snatch"),
        ("knee_flexion", _M, ("leg_curl",), None),
        ("knee_locomotion", _M, None, r"\bsled\b|\brun|jog|sprint|stair|step ?mill|jump rope|\brow(?:er|ing)\b|hik(?:e|ing)"),
        (
            "knee_quiet",
            _L,
            ("hinge", "hip_extension", "calf", "hip_abduction", "hip_adduction", "carry", "cardio", "ankle_dorsiflexion"),
            None,
        ),
    ),
    "hip": (
        ("hip_hinge", _H, ("hinge", "olympic"), None),
        ("hip_flexion_loaded", _M, ("squat", "hip_extension", "hip_abduction", "hip_adduction"), None),
        ("hip_flexor", _M, ("core_flexion", "core_anti"), r"leg raise|knee raise|v[- ]?up|toes to bar|hanging|l[- ]?sit"),
        ("hip_locomotion", _M, None, r"\bsled\b|\brun|jog|sprint|stair|step ?mill|lunge|split squat|step ?ups?"),
        ("hip_quiet", _L, ("calf", "leg_curl", "leg_extension", "step_down", "carry", "cardio", "ankle_dorsiflexion"), None),
    ),
    "lower_regions": ("lower", "full_body", "cardio"),
    "why": "fourth red team (2026-11-12): a knee-pain note on the squat was routed as a SPINAL-LOAD flag (the joint model had no "
    "knee), which cut a row and a calf raise and left three lunge patterns at RPE 8-9 in a week the knee hurt. Knee and hip join "
    "the joint-stress map as a PAIN-MAP rating, by class: knee-dominant squat, lunge, split-squat, step-up and knee-extension "
    "work high (the box / wall / Spanish squat regressions a physio uses moderate); a pull off the floor, a leg curl and "
    "loaded locomotion moderate; hinges high for the hip, loaded hip flexion and hip-dominant isolation moderate; upper-body "
    "work low; a lower-body row no rule recognises stays unknown (never read as safe). Practitioner consensus, not a trial; "
    "never read by the rubric's joint cost (quality_rubric.RUBRIC_JOINTS).",
}
"""Knee and hip pain-map ratings by class (`apply_class_rules`): first matching (pattern, title) rule; else low for an upper-
body / core row, unknown for a lower-body row no rule recognises."""


def knee_hip(e: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """{joint: (level, rule)} for one movement by KNEE_HIP."""
    import re

    title, pattern = str(e.get("title") or ""), e.get("pattern")
    region = str((e.get("target") or {}).get("region") or "")
    out: dict[str, tuple[str, str]] = {}
    for joint in ("knee", "hip"):
        for name, level, patterns, rx in KNEE_HIP[joint]:
            if (patterns is None or pattern in patterns) and (rx is None or re.search(rx, title, re.I)):
                out[joint] = (level, name)
                break
        else:
            out[joint] = ("unknown", "unrecognised_lower") if region in KNEE_HIP["lower_regions"] else (_L, "upper_or_core")
    return out


def _rank(level: str) -> int:
    return {"low": 0, "moderate": 1, "high": 2}.get(str(level), -1)


def apply_class_rules(movements: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """The class rules (#5861 FIX3 two, FIX4 the knee/hip map), in place, AFTER the canonical layer (each row's pattern and attributes are final) and before any
    tier is derived; each change is recorded on the row (`attribute_audit.class_rule`). Returns {rule: [keys changed]}."""
    import re

    out: dict[str, list[str]] = {"shoulder_provoking": [], "elbow_provoking": [], "spine_at_sides": [], "knee_hip": []}
    for key, e in sorted(movements.items()):
        js_ = dict(e.get("joint_stress") or {})
        dup = (e.get("variant") or {}).get("duplicate_of") if isinstance(e.get("variant"), dict) else None
        for joint, (level, _rule) in knee_hip(movements.get(str(dup)) or e).items():  # #5861 FIX4: the pain map; an alias = its head
            js_[joint] = level
        out["knee_hip"].append(key)
        title = str(e.get("title") or "")
        hit = e.get("pattern") in SHOULDER_PROVOKING["patterns"] or re.search(SHOULDER_PROVOKING["title"], title, re.I)
        if hit and _rank(js_.get("shoulder", "unknown")) < _rank(SHOULDER_PROVOKING["floor"]):
            # the healthy-joint rating stays the rubric's joint-cost input (quality_rubric.joint_penalty): a pain-map floor
            e["provocation_floor"] = {"shoulder": {"from": str(js_.get("shoulder", "unknown")), "rule": "shoulder_provoking"}}
            js_["shoulder"] = SHOULDER_PROVOKING["floor"]
            out["shoulder_provoking"].append(key)
            _record(e, "shoulder_provoking", "shoulder", SHOULDER_PROVOKING["floor"])
        elbow = e.get("pattern") in ELBOW_PROVOKING["patterns"] and not re.search(ELBOW_PROVOKING["not_title"], title, re.I)
        if elbow and _rank(js_.get("elbow", "unknown")) < _rank(ELBOW_PROVOKING["floor"]):  # #5861 FIX5: the elbow pain map
            floor = e.get("provocation_floor") or {}
            e["provocation_floor"] = {**floor, "elbow": {"from": str(js_.get("elbow", "unknown")), "rule": "elbow_provoking"}}
            js_["elbow"] = ELBOW_PROVOKING["floor"]
            out["elbow_provoking"].append(key)
            _record(e, "elbow_provoking", "elbow", ELBOW_PROVOKING["floor"])
        eq = set(e.get("equipment") or [])
        at_sides = (
            e.get("pattern") == SPINE_AT_SIDES["pattern"]
            and e.get("job") == "compound"
            and eq & set(SPINE_AT_SIDES["equipment"])
            and "barbell" not in eq
            and not re.search(SPINE_AT_SIDES["not_title"], title, re.I)
        )
        if at_sides and js_.get("spinal_load") not in (SPINE_AT_SIDES["level"], "unknown"):
            js_["spinal_load"] = SPINE_AT_SIDES["level"]
            out["spine_at_sides"].append(key)
            _record(e, "spine_at_sides", "spinal_load", SPINE_AT_SIDES["level"])
        e["joint_stress"] = js_
    return out


def _record(e: dict[str, Any], rule: str, joint: str, level: str) -> None:
    audit = e.setdefault("attribute_audit", {"fields": [], "reason": ""})
    audit.setdefault("class_rule", []).append({"rule": rule, "joint": joint, "level": level, "pass": "#5861 FIX3"})
