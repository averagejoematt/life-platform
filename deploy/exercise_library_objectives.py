"""exercise_library_objectives.py — the per-objective INPUTS for `config/exercise_library.json` (#5861).

WHY. Rubric v2 (#5857) rated every movement on hypertrophy alone, so carries, sleds, cardio, core control and cuff work landed
at C or D by construction, and the attributes it read were title-regex output. #5861 rates five objectives separately
(`training.quality_rubric`: hypertrophy, strength, functional, conditioning, mobility). Each rubric reads a small set of
categorical INPUTS this module derives per movement — by stated title/attribute rules first, then the reviewed layer in
`deploy/exercise_library_targets.py` (`INPUT_OVERRIDES`, `CATEGORY_OVERRIDES`, `SECONDARY_ROWS`, `CANONICAL_FAMILIES`), which
always wins and is recorded on the entry. Every rule is a heuristic, labelled as such; a reviewed override says why.

WHAT IT WRITES, per movement (`apply`, called by deploy/build_exercise_library.py before any tier is derived):
  * `category` — hypertrophy | strength | conditioning | athletic | mobility | rehab_control | carry;
  * `trunk_function` (trunk work only) and `functions` (hip flexion, grip, wrist, forearm rotation — when present);
  * `objective_inputs` — ceiling (overload ceiling), limiter, systemic_fatigue, resistance_class, strength_lift, ladder, functional,
    conditioning, mobility, reviewed (`quality_rubric.OBJECTIVE_INPUTS`);
  * the canonical layer — `canonical` on every movement, `variant` {axis: value} on a variant, and an exact duplicate
    (`alias`) takes its canonical's reviewed attributes so the same movement never scores twice. Every existing key and
    Hevy template id stays on its own entry: history joins are unchanged.

Pure over the movements dict. Titles and attributes only — never a load, a bodyweight or a word of his notes.
"""

from __future__ import annotations

import re
from typing import Any

import exercise_library_targets as targets

# ── category, trunk function, distinct functions ──────────────────────────────────────────────────────────────────
_MOBILITY_RE = re.compile(
    r"stretch\w*|mobility|90/90|\bcars\b|inchworms?|leg swings|t spine|thoracic|hurdle|angels and devils|squat reaches|"
    r"kickthrough|hip circles|couch|pry",
    re.I,
)
_ATHLETIC_CARDIO_RE = re.compile(r"sprints?|shuttle|5-10-5|s runs|box drill|shuffle|back pedals?|flying|broad jump|rachet|hops", re.I)
_LOADED_TRUNK_RE = re.compile(r"ab wheel|rollout|pallof|landmine 180|landmine rotation", re.I)
_TRUNK_RULES: list[tuple[str, str]] = [
    (r"side plank|suitcase|copenhagen", "anti_lateral_flexion"),
    (r"pallof|bird dog|anti[- ]rotation|renegade", "anti_rotation"),
    (r"carry|carries|farmers", "loaded_stabilisation"),
    (r"twist|rotation|woodchop|landmine 180|windshield", "rotation"),
    (r"plank|hover hold|ab wheel|rollout|dead bug|hollow|body saw|mountain climbers?|long leg marches|canoes", "anti_extension"),
    (r"crunch|sit ?up|v ?ups?|leg raise|knee raise|toes to bar|chinnies|heel taps|heels to the heavens|side bend", "loaded_flexion"),
]
_FUNCTION_RULES: list[tuple[str, str]] = [
    (r"knee raise|leg raise|knee drives?|march\w*|toes to bar|mountain climbers?|psoas|hip flexion", "hip_flexion"),
    (r"carry|carries|farmers|\bhang\b|dead hang|wiring out|wrist roller|pinch|towel|grip|gripper", "grip"),
    (r"palms up|wrist curl|forearm curl", "wrist_flexion"),
    (r"palms down|reverse wrist|overhand reverse", "wrist_extension"),
    (r"pronation|supination|zottman|around the world", "forearm_rotation"),
]


def category(e: dict[str, Any]) -> str:
    """The movement's primary TYPE (a label; the objective ratings carry the verdicts). Rule, in order: cardio target ->
    conditioning; a sprint/agility drill -> athletic; a carry or sled -> carry; skill/athletic family -> athletic; a mobility
    word -> mobility; a corrective -> rehab_control; anti-movement core -> strength when externally loadable, else
    rehab_control; a strength anchor or primary lift -> strength; else hypertrophy."""
    t, fam = str(e.get("title") or ""), e.get("family")
    if (e.get("target") or {}).get("primary") == "cardio" or e.get("pattern") == "cardio":
        return "athletic" if _ATHLETIC_CARDIO_RE.search(t) else "conditioning"
    if e.get("pattern") == "carry" or re.search(r"\bcarry|carries|farmers|sled\b", t, re.I):
        return "carry"
    if fam == "skill_athletic" or re.search(r"(?<!leg )\bswings?\b", t, re.I):
        return "athletic"
    if _MOBILITY_RE.search(t):
        return "mobility"
    if fam == "corrective":
        return "rehab_control"
    if fam == "core_anti_movement":
        return "strength" if _LOADED_TRUNK_RE.search(t) else "rehab_control"
    if fam == "strength_anchor":
        return "strength"
    return "hypertrophy"


def trunk_function(e: dict[str, Any]) -> str | None:
    """The trunk function for trunk work (target abs, an anti-movement drill or a carry); None otherwise."""
    t = str(e.get("title") or "")
    trunk = (e.get("target") or {}).get("primary") == "abs" or e.get("family") == "core_anti_movement" or e.get("pattern") == "carry"
    if not trunk or e.get("category") == "conditioning":
        return None
    return next((fn for pat, fn in _TRUNK_RULES if re.search(pat, t, re.I)), None)


def functions(e: dict[str, Any]) -> list[str]:
    t = str(e.get("title") or "")
    return [fn for pat, fn in _FUNCTION_RULES if re.search(pat, t, re.I)]


# ── the objective inputs (heuristic rules; the reviewed layer overrides) ────────────────────────────────────────────────
_HELD_LOWER = re.compile(r"squat|lunge|split|step|deadlift|rdl|hinge|swing|carry|farmers|goblet|landmine squat|front squat", re.I)
_LADDER_RE = re.compile(r"pull ?ups?|chin ?ups?|\bdips?\b|inverted row|push ?ups?|pushups?|pistol|nordic|ab wheel|rollout", re.I)
_BALANCE_RE = re.compile(
    r"walking|lateral|side lunge|alt side|curtsy|drop step|3 way|creeping|sprinter|offset lunge|overhead dumbbell lunge|"
    r"crossover step|single leg (?:rdl|romanian|cable rdl|static)|reach across|pistol|1 legged|skater|step ?ups?|stepup|"
    r"\blunges?\b(?!.*split)",
    re.I,
)
_UNILATERAL_RE = re.compile(
    r"single leg|one leg|1 leg|1 legged|pistol|split|bulgarian|lunge|step ?ups?|stepup|cossack|curtsy|suitcase|offset|"
    r"single arm|one arm|1 arm|sprinter|skater|step back",
    re.I,
)
_MULTIPLANAR_RE = re.compile(r"lateral|side lunge|alt side|cossack|curtsy|3 way|rotational|crossover|drop step|skater|twist", re.I)
_LOCOMOTION_RE = re.compile(r"walk\w*|carry|carries|farmers|sled|crawl\w*|bear|march", re.I)
_OFFSET_RE = re.compile(r"suitcase|offset|single arm|one arm|1 arm|overhead|renegade|landmine", re.I)
_POWER_RE = re.compile(
    r"clap|high pulls?|shouldering|jump\w*|hops?|bound\w*|pogos?|plyo\w*|clean|snatch|jerk|swing|slam\w*|throw\w*|toss|shot put|sprint\w*",
    re.I,
)


def _load_ceiling(e: dict[str, Any]) -> str:
    """Can the target be overloaded progressively? band -> low; bodyweight -> moderate with a ladder, else low; an assisted
    machine -> moderate; machine, cable, sled, barbell or weighted calisthenics -> high; a dumbbell or kettlebell HELD for a
    lower-body pattern -> moderate (the hands cap the load), any other dumbbell work -> high."""
    t, res, eq = str(e.get("title") or ""), e.get("resistance_profile"), set(e.get("equipment") or [])
    if res == "band":
        return "low"
    if re.search(r"assisted", t, re.I):
        return "moderate"
    if res == "bodyweight":
        return "moderate" if _LADDER_RE.search(t) and not re.search(r"push ?ups?|pushups?", t, re.I) else "low"
    if res in ("machine_selectorized", "machine_plate_loaded", "cable", "sled"):
        return "high"
    if res == "free_weight":
        if eq & {"barbell", "trap_bar", "ez_bar", "pullup_bar", "dip_station"} and not re.search(r"landmine squat", t, re.I):
            return "high"
        if _HELD_LOWER.search(t) or re.search(r"push ?ups?|pushups?", t, re.I):
            return "moderate"
        return "high"
    return "unknown"


def _limiter(e: dict[str, Any]) -> str:
    t = str(e.get("title") or "")
    if e.get("category") == "conditioning":
        return "cardio"
    if e.get("pattern") == "carry" or re.search(r"carry|farmers", t, re.I):
        return "grip"
    if re.search(r"cossack", t, re.I):
        return "mobility"
    if re.search(r"renegade", t, re.I):
        return "trunk"
    if re.search(r"hanging (?:leg|knee)|knee raise|leg raise", t, re.I):
        return "other_muscle"
    if _BALANCE_RE.search(t) and e.get("stability") in ("low", "unknown"):
        return "balance"
    return "target"


def _systemic_fatigue(e: dict[str, Any]) -> str:
    js = e.get("joint_stress") or {}
    if js.get("spinal_load") == "high" or e.get("family") == "skill_athletic":
        return "high"
    if e.get("pattern") in ("squat", "hinge") or e.get("category") == "carry":
        return "moderate"
    if e.get("job") == "compound" and e.get("resistance_profile") in ("free_weight", "bodyweight", "sled"):
        return "moderate"
    return "low"


def _overload(e: dict[str, Any]) -> str:
    res, eq = e.get("resistance_profile"), set(e.get("equipment") or [])
    landmine = "landmine" in eq  # one end of the bar, held or pressed: a dumbbell-class load, not a barbell's
    if res in ("machine_plate_loaded", "sled") or (
        res == "free_weight" and eq & {"barbell", "trap_bar", "pullup_bar", "dip_station"} and not landmine
    ):
        return "maximal"
    if res in ("free_weight", "cable", "machine_selectorized"):
        return "submaximal"
    return "bodyweight" if res == "bodyweight" else "light"


def _functional(e: dict[str, Any]) -> list[str]:
    t, cat = str(e.get("title") or ""), e.get("category")
    lower = e.get("pattern") in ("squat", "hinge") or bool(re.search(r"lunge|step ?ups?|stepup|step back|split|pistol|single leg", t, re.I))
    q = set()
    offset_compound = bool(_OFFSET_RE.search(t)) and e.get("job") == "compound"  # a single-arm isolation is not functional
    if _UNILATERAL_RE.search(t) and (lower or offset_compound or cat == "carry"):
        q.add("unilateral")
    if lower and e.get("stability") == "low" and _UNILATERAL_RE.search(t) or re.search(r"balance", t, re.I):
        q.add("balance")
    if cat == "carry" and not re.search(r"sled", t, re.I):
        q.add("carry")
    if _LOCOMOTION_RE.search(t) and cat != "conditioning":
        q.add("locomotion")
    standing_axial = e.get("job") == "compound" and (e.get("joint_stress") or {}).get("spinal_load") == "high"
    resists = str(e.get("trunk_function") or "").startswith("anti_") or e.get("trunk_function") == "loaded_stabilisation"
    if resists or (offset_compound and e.get("stability") == "low") or standing_axial:  # flexion/rotation is not stability
        q.add("trunk_stability")
    if _MULTIPLANAR_RE.search(t) and (lower or cat in ("athletic", "carry")):
        q.add("multiplanar")
    if cat == "athletic" and _POWER_RE.search(t):
        q.add("power")
    return [x for x in ("unilateral", "balance", "carry", "locomotion", "trunk_stability", "multiplanar", "power") if x in q]


# modality -> (aerobic, intensity control, impact, recovery demand); heuristics, first match wins
_CONDITIONING_RULES: list[tuple[str, tuple[str, str, str, str]]] = [
    (r"carry|carries|farmers", ("low", "moderate", "low", "moderate")),
    (r"rowing|air bike|stair|ski ?erg|swim\w*", ("high", "high", "low", "moderate")),
    (r"treadmill|cycling|bike|spinning|elliptical", ("high", "high", "low", "low")),
    (r"walking|walk|hiking", ("moderate", "moderate", "low", "low")),
    (r"running|jog", ("high", "moderate", "high", "moderate")),
    (r"jump rope|burpee|jumping jack|hops", ("moderate", "moderate", "high", "moderate")),
    (r"mountain climber|battle rope", ("moderate", "low", "low", "moderate")),
    (r"sled|prowler", ("moderate", "high", "low", "moderate")),
    (r"(?<!leg )swings?\b", ("moderate", "moderate", "low", "moderate")),
    (r"sprints?|shuttle|5-10-5|s runs|box drill|shuffle|back pedals?|flying|broad jump|rachet", ("low", "low", "high", "high")),
]


def _conditioning(e: dict[str, Any]) -> dict[str, str] | None:
    if e.get("category") not in ("conditioning", "carry", "athletic"):
        return None
    t = str(e.get("title") or "")
    hit = next((v for pat, v in _CONDITIONING_RULES if re.search(pat, t, re.I)), None)
    if hit is None:
        return None
    return dict(zip(("aerobic", "control", "impact", "recovery"), hit))


_MOBILITY_TYPE_RULES: list[tuple[str, str]] = [
    (r"bird dog|dead bug|balance|scap\w*|hip band|bridge and reach", "motor_control"),
    (
        r"external rotation|internal rotation|rotator cuff|ucv|w raise|y raise|face pulls?|pull ?aparts?|cossack|dead hang|scarecrow",
        "loaded",
    ),
    (r"stretch\w*|90/90|couch|pry", "passive"),
    (
        r"cars\b|mobility|wall slides|t spine|thoracic|leg swings|angels and devils|inchworms?|hurdle|squat reaches|kickthrough|hip circles",
        "active",
    ),
]


def _mobility(e: dict[str, Any]) -> str | None:
    t = str(e.get("title") or "")
    if e.get("category") not in ("mobility", "rehab_control") and not re.search(r"cossack|face pulls?|dead hang", t, re.I):
        return None
    return next((v for pat, v in _MOBILITY_TYPE_RULES if re.search(pat, t, re.I)), None)


def derive_inputs(e: dict[str, Any]) -> dict[str, Any]:
    """The rule-derived objective inputs for one movement (before the reviewed overrides)."""
    t = str(e.get("title") or "")
    return {
        "ceiling": _load_ceiling(e),
        "limiter": _limiter(e),
        "systemic_fatigue": _systemic_fatigue(e),
        "resistance_class": _overload(e),
        "strength_lift": False,
        "ladder": e.get("resistance_profile") == "bodyweight" and bool(_LADDER_RE.search(t)) and not re.search(r"assisted", t, re.I),
        "functional": _functional(e),
        "conditioning": _conditioning(e),
        "mobility": _mobility(e),
        "reviewed": False,
    }


# ── apply: the rules, then the reviewed layer, then the canonical layer ───────────────────────────────────────────────
ALIAS_FIELDS = (
    "target",
    "family",
    "job",
    "pattern",
    "length_bias",
    "resistance_profile",
    "stability",
    "joint_stress",
    "skill_complexity",
    "category",
    "trunk_function",
    "functions",
    "objective_inputs",
    "hypertrophy",
)


def _hard_stop(table: str, keys: Any, movements: dict[str, Any]) -> None:
    missing = sorted(k for k in keys if k not in movements)
    if missing:
        raise SystemExit(f"{table}: rows for movements not in the library: {missing}")


def evaluate_entry(key: str, e: dict[str, Any], hyp_row: Any) -> None:
    """One movement, in place: the reviewed pattern fix, category / trunk function / functions, the objective inputs, the
    reviewed secondary rows. Rule first, then the reviewed tables (each recorded on the entry). An authored
    `objective_inputs` (an L2 addition) is kept as authored and counts as reviewed. The canonical layer is library-wide
    (`apply_canonical`); a movement outside every family is its own canonical."""
    if key in targets.PATTERN_OVERRIDES:
        pattern, job, reason = targets.PATTERN_OVERRIDES[key]
        e["pattern"], e["job"] = pattern, job
        e.setdefault("attribute_audit", {"fields": [], "reason": ""})
        e["attribute_audit"]["pattern"] = {"pattern": pattern, "job": job, "reason": reason}
    e.pop("trunk_function", None)
    e["category"] = "strength" if key in targets.STRENGTH_LIFTS else category(e)
    if key in targets.CATEGORY_OVERRIDES:
        e["category"] = targets.CATEGORY_OVERRIDES[key][0]
    tf = trunk_function(e)
    if tf:
        e["trunk_function"] = tf
    fns = functions(e)
    e.pop("functions", None)
    if fns:
        e["functions"] = fns
    authored = e.get("objective_inputs") if isinstance(e.get("objective_inputs"), dict) and e.get("source") == "expansion" else None
    inp = derive_inputs(e) | {"strength_lift": key in targets.STRENGTH_LIFTS} | (authored or {})
    if key in targets.INPUT_OVERRIDES:
        vals, reason = targets.INPUT_OVERRIDES[key]
        inp |= vals
        e.setdefault("attribute_audit", {"fields": [], "reason": ""})
        e["attribute_audit"]["inputs"] = {"fields": sorted(vals), "reason": reason}
    inp["reviewed"] = bool(authored) or key in targets.REVIEWED_KEYS or key in targets.INPUT_OVERRIDES
    e["objective_inputs"] = inp
    have = {r.get("target") for r in e.get("hypertrophy") or []}
    for target, limiter, reason in targets.SECONDARY_ROWS.get(key, []):
        if target not in have:
            e["hypertrophy"].append(hyp_row(target) | {"limiter": limiter, "attribution": reason})
    e["canonical"] = key


REVIEWED_TABLES = ("PATTERN_OVERRIDES", "CATEGORY_OVERRIDES", "STRENGTH_LIFTS", "INPUT_OVERRIDES", "SECONDARY_ROWS", "REVIEWED_KEYS")


def apply(movements: dict[str, dict[str, Any]], hyp_row: Any) -> dict[str, dict[str, Any]]:
    """The whole evaluation layer over the library, in place: a reviewed row for a movement that is not in the library is
    a hard stop (an override never vanishes silently); every movement through `evaluate_entry`; then the canonical layer.
    Returns the canonical-family index."""
    for table in REVIEWED_TABLES:
        _hard_stop(table, getattr(targets, table), movements)
    for key, e in movements.items():
        evaluate_entry(key, e, hyp_row)
    return apply_canonical(movements)


def apply_canonical(movements: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """The canonical layer (`CANONICAL_FAMILIES`): every movement names its `canonical`; a variant records its `variant`
    axes; an exact duplicate (alias) takes the canonical's reviewed attributes. Returns the index written at the top level."""
    index: dict[str, dict[str, Any]] = {}
    seen: dict[str, str] = {}
    for head, (aliases, variants) in targets.CANONICAL_FAMILIES.items():
        _hard_stop(f"CANONICAL_FAMILIES[{head}]", [head, *aliases, *variants], movements)
        for k in [head, *aliases, *variants]:
            if k in seen:
                raise SystemExit(f"CANONICAL_FAMILIES: {k} is in both {seen[k]} and {head}")
            seen[k] = head
        index[head] = {"aliases": list(aliases), "variants": {k: dict(v) for k, v in variants.items()}}
    for key, e in movements.items():
        head = seen.get(key, key)
        e["canonical"] = head
        e.pop("variant", None)
        if key in (index.get(head) or {}).get("variants", {}):
            e["variant"] = dict(index[head]["variants"][key])
    for head, fam in index.items():
        for a in fam["aliases"]:
            own_audit = (movements[a].get("target") or {}).get("audit")
            for f in ALIAS_FIELDS:
                if f in movements[head]:
                    movements[a][f] = _copy(movements[head][f])
                else:
                    movements[a].pop(f, None)
            # the target-label audit record stays the alias's own (it names the alias's own reviewed move, if any)
            movements[a]["target"] = {k: v for k, v in movements[a]["target"].items() if k != "audit"}
            if own_audit:
                movements[a]["target"]["audit"] = own_audit
            movements[a]["variant"] = {"duplicate_of": head}
    return index


def _copy(v: Any) -> Any:
    import copy

    return copy.deepcopy(v)
