"""exercise_library.py — the owner's exercise library: loader, schema check, gate rules, private join (#5769).

WHAT IT IS

`config/exercise_library.json` is the coaching team's menu, written BEFORE any drafting: every
movement Matthew has logged in Hevy (all years, all phases, tombstones excluded) plus expansion
candidates he has not done, each tagged with what it trains, how (length bias, resistance
profile, stability), what it costs (joint stress, skill) and what it needs (equipment ids from a
controlled vocabulary). Each per-target hypertrophy row carries a QUALITY tier S-D that the written rubric
(`training.quality_rubric`, #5857) derives from those attributes, and its evidence confidence as a separate field: evidence
above `none_reviewed` needs a citation verified to exist (DOI or PMID), and only a direct trial may move a row one band off
its rubric tier, recorded with its citation.

It ships `status: "proposed"`. Only the selection engine (#5773, `selection_engine` / `selection_critic`)
reads it, and it changes no live draft until the owner approves the library: while `proposed` the engine
runs in SHADOW (`tests/test_exercise_library_5769.py` asserts no other module imports this one). Gate
evaluation is #5772.

TWO HALVES — PUBLIC AND PRIVATE

The repo is public, so the library carries no bodyweight, body-composition or note text. The N=1
half — best set per bodyweight band, coded signals from his Hevy notes (pain, sentiment, swaps,
equipment), the detail behind a `not_for_you_now`, and every gate threshold that is a bodyweight
number — lives in an OWNER-PRIVATE overlay, written by `deploy/write_exercise_library_overlay.py`
to `s3://matthew-life-platform/config/coaching/exercise_library.private.json` (the #3043
owner-private prefix: no public-read statement in `deploy/bucket_policy.json` covers `config/`,
and `config/*` is delete-protected). `load_private_overlay()` reads it env -> gitignored local file
-> S3, the same order `training_charter.load_private()` uses, and FAILS CLOSED: any failure returns
None, and `n1_view()` then reports the N=1 fit as `unknown` — it never raises.

GATES

A gate is DEFINED here and EVALUATED in #5772. Shape (`LIBRARY_GATE_KINDS`): every gate names its
`measured_input`, its `unlock_condition`, its `chain_prerequisites` (movement ids) and what an
unknown input means — always `locked`. A bodyweight threshold is never a number in this file: it
is `threshold.ref`, a key into the private overlay's `gate_thresholds`. A `clinical_cue` gate is a
CUE only (`locks: false`): it never caps intensity. `requires_*` below are the rules that say which
movements must carry which gate kind; the builder assigns gates from them and the tests hold every
entry to them.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Optional

from common import repo_config

from training import quality_rubric

logger = logging.getLogger("exercise_library")

LIBRARY_BASENAME = "exercise_library.json"
PRIVATE_ENV_VAR = "EXERCISE_LIBRARY_PRIVATE_JSON"
PRIVATE_LOCAL_BASENAME = "exercise_library.private.local.json"  # gitignored
PRIVATE_S3_KEY = "config/coaching/exercise_library.private.json"  # #3043 owner-private prefix

# ── controlled vocabularies (the equipment vocabulary lives IN the library, so the gym audit edits one file) ──
SOURCES = ("history", "expansion")
FAMILIES = ("hypertrophy", "strength_anchor", "carry_conditioning", "core_anti_movement", "skill_athletic", "corrective")
LENGTH_BIAS = ("lengthened", "mid", "shortened", "not_applicable", "unknown")
RESISTANCE_PROFILES = (
    "free_weight",
    "cable",
    "machine_selectorized",
    "machine_plate_loaded",
    "bodyweight",
    "band",
    "sled",
    "cardio_machine",
    "not_applicable",
    "unknown",
)
STABILITY = ("high", "moderate", "low", "unknown")
STRESS_LEVELS = ("low", "moderate", "high", "unknown")
JOINT_STRESS_KEYS = ("spinal_load", "shear", "wrist", "elbow", "shoulder")
PAIN_MAP_JOINTS = ("knee", "hip")
"""#5861 FIX4: the knee and hip ratings the live pain rule reads (`deploy/exercise_library_input_review.KNEE_HIP`, a class rule);
optional per entry, never read by the rubric's joint cost (`quality_rubric.RUBRIC_JOINTS`)."""
SKILL = ("low", "moderate", "high")
TIERS = quality_rubric.QUALITY_TIERS  # the QUALITY tier S-D, derived by the rubric (#5857) — never an evidence grade
EVIDENCE_CONFIDENCE = quality_rubric.EVIDENCE_CONFIDENCE  # evidence strength, its own field beside the tier
LIBRARY_GATE_KINDS = (
    "bodyweight_threshold",  # measured: the 7-day mean Withings bodyweight; threshold value lives in the private overlay
    "chain_prerequisite",  # measured: logged sessions of the prerequisite movement(s) meeting the stated standard
    "performance_threshold",  # measured: a logged performance on THIS movement (a hold time, an assistance fraction)
    "pain_flag_exclusion",  # measured: pain flags on this movement in the private overlay's note signals
    "charter_gate",  # the training charter already owns this gate (`charter_ref`); the library only points at it
    "owner_confirmation",  # measured: the owner (or a coached session) marks the technique confirmed
    "equipment_available",  # measured: gym_inventory states at home_gym; unavailable/unknown => locked; contention never locks
    "clinical_cue",  # a CUE, never a lock: breathing / no breath-hold. Clinical guidance is reference only.
)
UNKNOWN_INPUT = "locked"
PAIN_SOURCE_ID = "training_notes_pain.pain_class (#5806)"  # the rule behind the overlay's `pain_flag` tag (#5773)

# ── availability (owner ruling 2026-11-11) ──
# One location id, never a name: `home_gym`. A movement logged in the last AVAILABLE_LOOKBACK_YEARS of his
# Hevy history is AVAILABLE there by default; equipment seen only in older history, or only in expansion
# candidates, is UNKNOWN. A swap note saying the gym does not have X marks X UNAVAILABLE (owner-confirmable);
# "X was taken" / "no bench free" is CONTENTION, which never makes anything unavailable.
LOCATION_ID = "home_gym"
AVAILABILITY_STATES = ("available", "unavailable", "unknown")
AVAILABLE_LOOKBACK_YEARS = 5
FALLBACK_REASONS = ("same_stimulus", "same_target", "same_family")
MIN_FALLBACKS = 1

# A template id is 8-char uppercase hex (Hevy standard; a few legacy ids carry other characters) or a custom UUID.
_TID_RE = re.compile(r"^(?:[0-9A-Z]{8}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ── which movements must carry a gate (the builder assigns, the tests hold every entry to these) ──
# Bodyweight-loaded: he moves (most of) his own mass, so the load IS the bodyweight. Incline / wall / knee push-ups,
# inverted rows and assisted variants are the on-ramps, not the gated lift.
_BODYWEIGHT_LOADED_RE = re.compile(
    r"\b(pull[\s-]?ups?|chin[\s-]?ups?|muscle[\s-]?ups?|dips?|nordic|hanging (?:leg|knee) raises?|toes to bar|"
    r"push[\s-]?ups?|pushups?|pistol|handstand|dragon flag|l[\s-]?sit|front lever|back lever)\b",
    re.IGNORECASE,
)
_BODYWEIGHT_ONRAMP_RE = re.compile(r"\b(assisted|incline push|knee push|wall push|bench dip|band(?:ed)?|negative|machine)\b", re.IGNORECASE)
_PLYO_RE = re.compile(
    r"\b(jumps?|jumping|hops?|hopping|bounds?|bounding|pogos?|plyo\w*|sprints?|sprinting|skips?|burpees?|tuck|box jump|broad jump|"
    r"depth jump|run|running|jog|jogging|shuttle|back pedals?)\b",
    re.IGNORECASE,
)


def requires_bodyweight_gate(entry: dict[str, Any]) -> bool:
    """True when the movement loads (most of) his bodyweight and is not itself an on-ramp variant."""
    title = str(entry.get("title") or "")
    return bool(_BODYWEIGHT_LOADED_RE.search(title)) and not _BODYWEIGHT_ONRAMP_RE.search(title)


def requires_impact_gate(entry: dict[str, Any]) -> bool:
    """True for jumps, hops, sprints and runs — the charter's plyometric exclusion / running gate owns these."""
    if entry.get("family") == "carry_conditioning" and re.search(
        r"\b(walk|walking|treadmill|cycling|bike|row|stair)\b", str(entry.get("title") or ""), re.I
    ):
        return False
    return bool(_PLYO_RE.search(str(entry.get("title") or "")))


def requires_skill_gate(entry: dict[str, Any]) -> bool:
    """True for skill/athletic movements and any high-skill lift: a chain prerequisite or an owner confirmation."""
    return entry.get("family") == "skill_athletic" or entry.get("skill_complexity") == "high"


# ── loading ───────────────────────────────────────────────────────────────────────────────────────────────────────


def library_path() -> str:
    return repo_config.config_path(LIBRARY_BASENAME)


def load_library(path: Optional[str] = None) -> dict[str, Any]:
    """The public library (local/bundle copy). Raises on a missing or unreadable file — the caller is offline tooling."""
    with open(path or library_path(), encoding="utf-8") as f:
        return json.load(f)


def movements(lib: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return lib.get("movements") or {}


# ── schema check (hand-written: no jsonschema dependency in the Lambda bundle) ─────────────────────────────────────


def _err(errors: list[str], where: str, msg: str) -> None:
    errors.append(f"{where}: {msg}")


def _equivalence_errors(lib: dict[str, Any]) -> list[str]:
    """An equivalence adjustment (#5857 rubric v2, board rec 6) names a comparator whose tier for the same target sits
    ABOVE this row's rubric tier — parity with a higher-tier movement is what earns the +1."""
    out: list[str] = []
    mv = lib["movements"]
    for mid, e in mv.items():
        for row in e.get("hypertrophy") or []:
            adj = row.get("evidence_adjustment") or {}
            if adj.get("basis") != "equivalence":
                continue
            comp = next(
                (r for r in (mv.get(adj.get("comparator")) or {}).get("hypertrophy") or [] if r.get("target") == row.get("target")), None
            )
            order = quality_rubric.QUALITY_TIERS
            if (
                comp is None
                or comp.get("tier") not in order
                or row.get("rubric_tier") not in order
                or order.index(str(comp.get("tier"))) >= order.index(str(row.get("rubric_tier")))
            ):
                out.append(
                    f"movements.{mid}: equivalence with {adj.get('comparator')!r} needs a higher-tier comparator for {row.get('target')}"
                )
    return out


def _hypertrophy_row_errors(errors: list[str], w: str, e: dict[str, Any], row: dict[str, Any], citations: Any) -> None:
    """One per-target row (#5857): a quality tier S-D the rubric derives (plus at most one recorded evidence band), and
    its evidence confidence beside it. Evidence above `none_reviewed` cites a registered reference and carries a date."""
    if row.get("tier") not in TIERS and not (row.get("tier") is None and row.get("applicable") is False):
        _err(errors, w, f"tier {row.get('tier')!r} (S-D, or None only on a not-applicable row, #5861)")
    for why in quality_rubric.derivation_problems(e, row):
        _err(errors, w, f"{row.get('target')}: {why}")
    if row.get("evidence_confidence") not in EVIDENCE_CONFIDENCE:
        _err(errors, w, f"evidence_confidence {row.get('evidence_confidence')!r}")
    if row.get("evidence_confidence") not in (None, "none_reviewed"):
        cites = row.get("citations") or []
        if not cites or any(c not in citations for c in cites):
            _err(errors, w, f"evidence {row.get('evidence_confidence')} for {row.get('target')} needs >=1 registered citation")
        if not _DATE_RE.match(str(row.get("last_reviewed"))):
            _err(errors, w, "a reviewed row carries a dated last_reviewed")
    elif row.get("evidence_adjustment"):
        _err(errors, w, "an unreviewed row never moves off its rubric tier")


def validate(lib: dict[str, Any]) -> list[str]:
    """Every schema violation in the library, as readable strings. Empty list = valid."""
    errors: list[str] = []
    for key in (
        "version",
        "status",
        "change_log",
        "equipment_vocabulary",
        "citations",
        "gate_schema",
        "gates",
        "gym_inventory",
        "movements",
    ):
        if key not in lib:
            _err(errors, "library", f"missing top-level `{key}`")
    if errors:
        return errors
    if lib["status"] not in ("proposed", "approved", "retired"):
        _err(errors, "library", f"status {lib['status']!r} not in proposed|approved|retired")
    if not re.match(r"^\d+\.\d+\.\d+$", str(lib["version"])):
        _err(errors, "library", "version must be semver")
    if not lib["change_log"] or not all({"version", "date", "by", "what"} <= set(c) for c in lib["change_log"]):
        _err(errors, "change_log", "every line needs version, date, by, what")
    vocab = set(lib["equipment_vocabulary"])
    if lib["gym_inventory"].get("location_id") != LOCATION_ID:
        _err(errors, "gym_inventory", f"location_id must be {LOCATION_ID!r} (a gym is never named)")
    for eid, row in (lib["gym_inventory"].get("items") or {}).items():
        if eid not in vocab:
            _err(errors, f"gym_inventory.{eid}", "not in equipment_vocabulary")
        st = (row or {}).get(LOCATION_ID) or {}
        if st.get("state") not in AVAILABILITY_STATES or not st.get("source"):
            _err(errors, f"gym_inventory.{eid}", f"needs {LOCATION_ID}.state in {AVAILABILITY_STATES} + a source")
    citations = lib["citations"]
    for cid, c in citations.items():
        if not (c.get("doi") or c.get("pmid")):
            _err(errors, f"citations.{cid}", "needs a doi or pmid")
        for k in ("title", "authors", "year", "journal", "verified_on"):
            if not c.get(k):
                _err(errors, f"citations.{cid}", f"missing {k}")
    gates = lib["gates"]
    for gid, g in gates.items():
        if g.get("kind") not in LIBRARY_GATE_KINDS:
            _err(errors, f"gates.{gid}", f"kind {g.get('kind')!r} not in LIBRARY_GATE_KINDS")
        for k in ("measured_input", "unlock_condition"):
            if not g.get(k):
                _err(errors, f"gates.{gid}", f"missing {k}")
        if g.get("unknown_input") != UNKNOWN_INPUT:
            _err(errors, f"gates.{gid}", "unknown_input must be 'locked'")
        if g.get("kind") == "clinical_cue" and g.get("locks") is not False:
            _err(errors, f"gates.{gid}", "a clinical_cue never locks (locks: false)")
        if g.get("kind") != "clinical_cue" and g.get("locks") is not True:
            _err(errors, f"gates.{gid}", "every non-cue gate locks (locks: true)")
        if g.get("kind") == "bodyweight_threshold":
            thr = g.get("threshold") or {}
            if not str(thr.get("ref") or "").startswith("overlay:gate_thresholds.") and not thr.get("charter_ref"):
                _err(errors, f"gates.{gid}", "a bodyweight threshold is an overlay ref or a charter ref, never a value")
            if "value" in thr:
                _err(errors, f"gates.{gid}", "a bodyweight threshold value never sits in the public library")
        if g.get("kind") == "charter_gate" and not g.get("charter_ref"):
            _err(errors, f"gates.{gid}", "a charter_gate names its charter_ref")
        for pre in g.get("chain_prerequisites") or []:
            if pre not in lib["movements"]:
                _err(errors, f"gates.{gid}", f"chain prerequisite {pre!r} is not a library movement")
    seen_tids: dict[str, str] = {}
    for mid, e in lib["movements"].items():
        w = f"movements.{mid}"
        if e.get("source") not in SOURCES:
            _err(errors, w, f"source {e.get('source')!r}")
        tid = e.get("template_id")
        if tid is not None:
            if not _TID_RE.match(str(tid)):
                _err(errors, w, f"template_id {tid!r} malformed")
            if str(tid).upper() in seen_tids:
                _err(errors, w, f"template_id {tid} also on {seen_tids[str(tid).upper()]}")
            seen_tids[str(tid).upper()] = mid
        elif not e.get("template_note"):
            _err(errors, w, "template_id null needs a template_note")
        if e.get("source") == "history":
            h = e.get("history") or {}
            if not (_DATE_RE.match(str(h.get("first_done"))) and _DATE_RE.match(str(h.get("last_done")))):
                _err(errors, w, "history needs first_done/last_done dates")
            if not isinstance(h.get("exposures"), int) or h["exposures"] < 1:
                _err(errors, w, "history.exposures must be an int >= 1")
            if not tid:
                _err(errors, w, "a history entry carries its logged template_id")
        if e.get("family") not in FAMILIES:
            _err(errors, w, f"family {e.get('family')!r}")
        if e.get("job") not in quality_rubric.JOBS:
            _err(errors, w, f"job {e.get('job')!r} (compound | isolation, #5857 rubric v2)")
        if e.get("length_bias") not in LENGTH_BIAS:
            _err(errors, w, f"length_bias {e.get('length_bias')!r}")
        if e.get("resistance_profile") not in RESISTANCE_PROFILES:
            _err(errors, w, f"resistance_profile {e.get('resistance_profile')!r}")
        if e.get("stability") not in STABILITY:
            _err(errors, w, f"stability {e.get('stability')!r}")
        if e.get("skill_complexity") not in SKILL:
            _err(errors, w, f"skill_complexity {e.get('skill_complexity')!r}")
        js = e.get("joint_stress") or {}
        if set(js) - set(PAIN_MAP_JOINTS) != set(JOINT_STRESS_KEYS) or any(v not in STRESS_LEVELS for v in js.values()):
            _err(errors, w, "joint_stress needs exactly spinal_load/shear/wrist/elbow/shoulder (+ knee/hip) in low|moderate|high|unknown")
        tgt = e.get("target") or {}
        if not tgt.get("primary") or not tgt.get("region"):
            _err(errors, w, "target needs primary + region")
        eq = e.get("equipment")
        if not isinstance(eq, list) or not eq or any(x not in vocab for x in eq):
            _err(errors, w, f"equipment {eq!r} must be a non-empty list of equipment_vocabulary ids")
        hyp = e.get("hypertrophy")
        if not isinstance(hyp, list) or not hyp:
            _err(errors, w, "hypertrophy needs at least one per-target row")
        for row in hyp or []:
            _hypertrophy_row_errors(errors, w, e, row, citations)
        fbs = e.get("fallbacks")
        if not isinstance(fbs, list) or len(fbs) < MIN_FALLBACKS:
            _err(errors, w, "needs >= 1 ranked fallback")
        for fb in fbs or []:
            if fb.get("movement_id") not in lib["movements"] or fb.get("movement_id") == mid:
                _err(errors, w, f"fallback {fb.get('movement_id')!r} is not another library movement")
            if fb.get("reason") not in FALLBACK_REASONS:
                _err(errors, w, f"fallback reason {fb.get('reason')!r}")
        av = (e.get("availability") or {}).get(LOCATION_ID) or {}
        if av.get("state") not in AVAILABILITY_STATES:
            _err(errors, w, f"availability.{LOCATION_ID}.state must be one of {AVAILABILITY_STATES}")
        for g in e.get("gates") or []:
            if g not in gates:
                _err(errors, w, f"gate {g!r} not defined")
        nfy = e.get("not_for_you_now")
        if nfy is not None and not (nfy.get("reason_code") and nfy.get("unlock_condition")):
            _err(errors, w, "not_for_you_now needs reason_code + unlock_condition")
        kinds = {gates[g]["kind"] for g in e.get("gates") or [] if g in gates}
        if requires_bodyweight_gate(e) and "bodyweight_threshold" not in kinds:
            _err(errors, w, "bodyweight-loaded movement without a bodyweight_threshold gate")
        if requires_impact_gate(e) and "charter_gate" not in kinds:
            _err(errors, w, "impact movement without its charter gate")
        if requires_skill_gate(e) and not kinds & {"chain_prerequisite", "owner_confirmation", "charter_gate"}:
            _err(errors, w, "skill movement without a chain / owner-confirmation / charter gate")
    errors += _equivalence_errors(lib)
    errors += _evaluation_errors(lib)
    return errors


def canonical_of(lib: dict[str, Any], ref: str) -> Optional[str]:
    """The canonical movement key for a library key OR a Hevy template id (#5861 alias layer); None when unknown. Every
    pre-existing key and template id resolves: aliases and variants keep their own entries and name their canonical."""
    mv = movements(lib)
    e = mv.get(ref) or next((x for x in mv.values() if str(x.get("template_id") or "").upper() == str(ref).upper()), None)
    return None if e is None else str(e.get("canonical") or next(k for k, x in mv.items() if x is e))


def _input_ok(k: str, v: Any) -> bool:
    """One objective input against its vocabulary: `functional` a list of qualities, `conditioning` None or a
    {aerobic, control, impact, recovery} map of levels, every other input a single allowed value."""
    allowed = quality_rubric.OBJECTIVE_INPUTS[k]
    if k == "functional":
        return isinstance(v, list) and all(x in allowed for x in v)
    if k == "conditioning":
        return v is None or (isinstance(v, dict) and set(v) == set(allowed) and all(x in quality_rubric.LEVELS for x in v.values()))
    return v in allowed


_ALIAS_SAME = ("family", "job", "pattern", "length_bias", "resistance_profile", "stability", "joint_stress", "skill_complexity")


def _evaluation_errors(lib: dict[str, Any]) -> list[str]:
    """#5861: category / trunk_function / functions in vocabulary, objective inputs well-formed, every rating what the
    objective rubrics derive, and the canonical layer coherent (each canonical resolves; an alias carries its canonical's
    attributes; the index and the entries agree)."""
    errors: list[str] = []
    qr = quality_rubric
    mv = movements(lib)
    for mid, e in mv.items():
        w = f"movements.{mid}"
        if e.get("category") not in qr.CATEGORIES:
            _err(errors, w, f"category {e.get('category')!r}")
        if "trunk_function" in e and e["trunk_function"] not in qr.TRUNK_FUNCTIONS:
            _err(errors, w, f"trunk_function {e.get('trunk_function')!r}")
        if any(f not in qr.FUNCTIONS for f in e.get("functions") or []):
            _err(errors, w, f"functions {e.get('functions')!r}")
        inp = e.get("objective_inputs") or {}
        for k in qr.OBJECTIVE_INPUTS:
            if k not in inp or not _input_ok(k, inp.get(k)):
                _err(errors, w, f"objective_inputs.{k} {inp.get(k)!r}")
        errors += [f"{w}: {why}" for why in qr.rating_problems(e)]
        head = canonical_of(lib, mid)
        if head not in mv:
            _err(errors, w, f"canonical {e.get('canonical')!r} is not a library movement")
        elif (e.get("variant") or {}).get("duplicate_of") and any(e.get(f) != mv[head].get(f) for f in _ALIAS_SAME):
            _err(errors, w, f"an alias of {head} carries different attributes")
    for head, fam in (lib.get("canonical_families") or {}).items():
        for k in list(fam.get("aliases") or []) + list(fam.get("variants") or {}):
            if (mv.get(k) or {}).get("canonical") != head:
                _err(errors, f"canonical_families.{head}", f"{k} does not name {head} as its canonical")
    return errors


# ── the owner-private overlay (N=1 fit) — fail closed ────────────────────────────────────────────────────────────


def _overlay_from_env() -> Optional[dict[str, Any]]:
    raw = os.environ.get(PRIVATE_ENV_VAR)
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except ValueError:
        logger.warning("%s is set but not valid JSON; ignoring", PRIVATE_ENV_VAR)
        return None


def _overlay_from_local() -> Optional[dict[str, Any]]:
    path = repo_config.config_path(PRIVATE_LOCAL_BASENAME)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        logger.warning("private overlay local file unreadable; ignoring")
        return None


def _overlay_from_s3() -> Optional[dict[str, Any]]:
    try:
        import boto3

        bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
        region = os.environ.get("S3_REGION") or os.environ.get("AWS_REGION") or "us-west-2"
        body = boto3.client("s3", region_name=region).get_object(Bucket=bucket, Key=PRIVATE_S3_KEY)["Body"].read()
        data = json.loads(body)
        return data if isinstance(data, dict) else None
    except Exception as e:  # noqa: BLE001 — fail closed: any failure means "N=1 fit unknown"
        logger.warning("private exercise-library overlay unavailable (%s); N=1 fit is unknown", type(e).__name__)
        return None


def load_private_overlay(allow_s3: bool = True) -> Optional[dict[str, Any]]:
    """env -> gitignored local file -> owner-private S3. None on any failure (never raises)."""
    try:
        return _overlay_from_env() or _overlay_from_local() or (_overlay_from_s3() if allow_s3 else None)
    except Exception:  # noqa: BLE001
        logger.warning("private overlay load failed; N=1 fit is unknown")
        return None


def n1_view(entry: dict[str, Any], overlay: Optional[dict[str, Any]]) -> dict[str, Any]:
    """The selection-time join of one library entry with the private overlay.

    Overlay missing, malformed or silent on this template => `n1_fit: "unknown"` (never an error, never a pass).
    """
    unknown = {"n1_fit": "unknown", "best_set_by_band": None, "note_signals": None, "pain_flagged": None}
    if not isinstance(overlay, dict):
        return unknown
    per = overlay.get("per_template")
    tid = str(entry.get("template_id") or "").upper()
    if not isinstance(per, dict) or not tid or not isinstance(per.get(tid), dict):
        return unknown
    row = per[tid]
    signals = row.get("note_signals") if isinstance(row.get("note_signals"), dict) else {}
    return {
        "n1_fit": "known",
        "best_set_by_band": row.get("best_set_by_band"),
        "note_signals": signals,
        "pain_flagged": bool(signals.get("pain_flag")),
    }


# ── availability learned from swap notes (pure; the overlay writer runs it over his notes) ──────────────────────
# Phrase -> equipment id. Longest phrase first, so "preacher curl machine" never resolves as a bare "machine".
EQUIPMENT_PHRASES: tuple[tuple[str, str], ...] = (
    ("preacher curl machine", "preacher_machine"),
    ("preacher machine", "preacher_machine"),
    ("standing calf machine", "calf_raise_standing_machine"),
    ("standing calf raise machine", "calf_raise_standing_machine"),
    ("seated calf machine", "calf_raise_seated_machine"),
    ("calf machine", "calf_raise_standing_machine"),
    ("machine for calf", "calf_raise_standing_machine"),
    ("pec deck machine", "pec_deck"),
    ("pec deck", "pec_deck"),
    ("hip thrust machine", "hip_thrust_machine"),
    ("leg press", "leg_press_machine"),
    ("hack squat", "hack_squat_machine"),
    ("squat rack", "squat_rack"),
    ("rack", "squat_rack"),
    ("incline bench", "bench_adjustable"),
    ("bench", "bench_flat"),
    ("kettlebells", "kettlebell"),
    ("kettlebell", "kettlebell"),
    ("dumbbells", "dumbbell"),
    ("dumbbell", "dumbbell"),
    ("ez bar", "ez_bar"),
    ("trap bar", "trap_bar"),
    ("barbell", "barbell"),
    ("cable", "cable_stack"),
    ("treadmills", "treadmill"),
    ("treadmill", "treadmill"),
    ("bike", "stationary_bike"),
    ("sled", "sled"),
    ("landmine", "landmine"),
    ("smith machine", "smith_machine"),
)
_EQ_ALT = "|".join(re.escape(p) for p, _ in EQUIPMENT_PHRASES)
_ART = r"(?:an?\s+|the\s+|any\s+)?"
_UNAVAILABLE_RES = (
    re.compile(r"(?:my|this|the)\s+gym\s+(?:does\s*n[o']?t|doesnt|does not|don'?t)\s+(?:have|has)\s+" + _ART + r"(" + _EQ_ALT + r")"),
    re.compile(r"(?:do\s*n[o']?t|dont)\s+think\s+(?:my|this|the)\s+gym\s+(?:has|have)\s+" + _ART + r"(" + _EQ_ALT + r")"),
    re.compile(r"(?:gym|they)\s+(?:has|have)\s+no\s+(" + _EQ_ALT + r")"),
    re.compile(r"no\s+(" + _EQ_ALT + r")\s+(?:at|in)\s+(?:my|this|the)\s+gym"),
)
_CONTENTION_RES = (
    re.compile(r"(" + _EQ_ALT + r")\s+(?:was|were|is|are)\s+(?:all\s+)?(?:taken|busy|occupied|in use|full)"),
    re.compile(r"(?:all|every)\s+(?:the\s+)?(" + _EQ_ALT + r")\s+(?:was|were)\s+(?:taken|busy|occupied|in use)"),
    re.compile(r"no\s+(" + _EQ_ALT + r")\s+(?:free|available|open)"),
    re.compile(r"(?:waiting|wait)\s+(?:for|on)\s+" + _ART + r"(" + _EQ_ALT + r")"),
    re.compile(r"(" + _EQ_ALT + r")\s+had\s+a\s+long\s+(?:wait|weight)"),
)
_QUESTION_RES = (
    re.compile(
        r"(?:see|check|find out)\s+if\s+(?:my|this|the)\s+(?:other\s+rooms?\s+in\s+my\s+)?gym\s+(?:has|have)\s+"
        + _ART
        + r"("
        + _EQ_ALT
        + r")"
    ),
)
_CEILING_RES = (re.compile(r"no\s+heavier\s+(" + _EQ_ALT + r")"),)


def _eq_id(phrase: str) -> Optional[str]:
    p = phrase.strip().lower()
    for k, v in EQUIPMENT_PHRASES:
        if p == k:
            return v
    return None


def classify_availability_note(text: str) -> list[dict[str, str]]:
    """Pure. One swap/equipment note -> coded availability signals, never the note text.

    `unavailable`  the gym does not have X ("I don't think my gym has a preacher curl machine") — owner-confirmable;
    `contention`   X exists but was busy ("kettlebell was taken", "no bench available") — NEVER unavailability;
    `question`     he is checking whether the gym has X — changes nothing;
    `load_ceiling` the gym's X does not go heavy enough ("no heavier kettlebells").
    One signal per (kind, equipment); an equipment named as unavailable is not also reported as contention.
    """
    t = " ".join((text or "").lower().replace("\u2019", "'").split())
    if not t:
        return []
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, regs in (
        ("unavailable", _UNAVAILABLE_RES),
        ("question", _QUESTION_RES),
        ("load_ceiling", _CEILING_RES),
        ("contention", _CONTENTION_RES),
    ):
        for rx in regs:
            for m in rx.finditer(t):
                eid = _eq_id(m.group(1))
                if not eid or (kind, eid) in seen:
                    continue
                if kind in ("contention", "question") and ("unavailable", eid) in seen:
                    continue
                if kind == "contention" and ("question", eid) in seen:
                    continue
                seen.add((kind, eid))
                out.append({"signal": kind, "equipment": eid})
    return out


# ── fallbacks ────────────────────────────────────────────────────────────────────────────────────────────────────
_PATTERNS: tuple[tuple[str, str], ...] = (
    ("calf", r"calf"),
    # #5861 L6: a reverse Nordic is a knee EXTENSION (it was read as a leg curl); internal/external rotation is the cuff (it
    # was read as trunk rotation); a curl-up is trunk flexion (it was read as a biceps curl); a band walk is hip abduction
    # (any "walk" was read as cardio)
    ("leg_extension", r"leg extension|sissy|reverse nordic|spanish squat"),
    ("leg_curl", r"leg curl|nordic|hamstring curl"),
    ("shoulder_rotation", r"(?:external|internal) rotation|rotator cuff"),
    ("hip_abduction", r"hip abduction|band walks?|monster walk|lateral (?:band )?steps?|clam ?shell"),
    ("hip_adduction", r"hip adduction|copenhagen"),
    ("hip_extension", r"hip thrust|glute bridge|back extension|hyperextension|pull through|kickback|rear kick|reverse hyper"),
    ("hinge", r"deadlift|\brdl\b|good morning|swing"),
    ("squat", r"squat|leg press|lunge|step up|split"),
    ("vertical_pull", r"pull ?up|chin ?up|pulldown|pullover"),
    ("horizontal_pull", r"\brows?\b|rowing|t bar"),
    ("triceps_extension", r"tricep|triceps|skull|pushdown|push ?away|kickback|jm press|dip"),
    ("core_flexion_curl_up", r"curl[- ]ups?\b"),
    ("curl", r"curl|21s"),
    ("vertical_press", r"overhead press|shoulder press|military press|arnold|landmine press|pike|handstand"),
    ("lateral_raise", r"lateral raise|upright row|y raise"),
    ("rear_delt", r"rear delt|reverse fly|face pull|scarecrow|pull ?apart"),
    ("chest_fly", r"\bfly\b|flyes?|crossover|pec deck"),
    ("horizontal_press", r"bench press|chest press|push ?ups?|pushups?|floor press|dip"),
    ("carry", r"carry|carries|farmers|suitcase|sled|prowler"),
    ("core_anti", r"plank|pallof|dead bug|bird dog|ab wheel|rollout"),
    ("core_flexion", r"crunch|sit up|v up|leg raise|knee raise|rotation|twist|side bend|oblique"),
    ("cardio", r"treadmill|cycling|bike|elliptical|rowing machine|stair|\bwalk(?:ing|s)?\b"),
    ("olympic", r"clean|snatch|jerk|high pull"),
    ("shrug", r"shrug"),
)


def movement_pattern(title: str) -> str:
    t = (title or "").lower()
    for name, pat in _PATTERNS:
        if re.search(pat, t):
            return "core_flexion" if name == "core_flexion_curl_up" else name
    return "other"


def _locking_gate_kinds(lib: dict[str, Any], e: dict[str, Any]) -> set[str]:
    gates = lib.get("gates") or {}
    return {gates[g]["kind"] for g in e.get("gates") or [] if g in gates and gates[g].get("locks")}


def fallback_index(lib: dict[str, Any]) -> dict[str, tuple[str, set[str]]]:
    """key -> (movement pattern, locking gate kinds) — computed once when ranking every movement's fallbacks."""
    return {k: (movement_pattern(e.get("title", "")), _locking_gate_kinds(lib, e)) for k, e in movements(lib).items()}


def fallback_candidates(lib: dict[str, Any], key: str, index: Optional[dict[str, tuple[str, set[str]]]] = None) -> list[tuple[str, str]]:
    """Ranked (movement_id, reason) same-stimulus substitutes for `key` — pure over the library.

    Eligible: another movement, not `not_for_you_now`, not unavailable at home_gym, with no bodyweight / chain /
    owner-confirmation / charter gate (a fallback must be usable the day the primary is not) — unless the primary is
    itself gated, when gated candidates are allowed but ranked after ungated ones. Reason:
    `same_stimulus` = same primary target AND same movement pattern; `same_target` = same primary target;
    `same_family` = same family and (same region + pattern, or any, for a pattern-less movement) — the last resort. Ranked by reason, then NO shared equipment with the
    primary (a missing item must be a swap, not the same hole), then same length bias, then available, then
    history exposures.
    """
    mv = movements(lib)
    idx = index if index is not None else fallback_index(lib)
    me = mv[key]
    tgt = (me.get("target") or {}).get("primary")
    region = (me.get("target") or {}).get("region")
    pat = idx[key][0]
    my_eq = set(me.get("equipment") or [])
    blocking = {"bodyweight_threshold", "chain_prerequisite", "owner_confirmation", "charter_gate"}
    # A movement that is itself behind a skill / bodyweight / charter gate may fall back to another gated one (an
    # Olympic lift's substitute is another pull, not a curl), ranked AFTER every ungated candidate.
    primary_gated = bool(idx[key][1] & blocking)
    ranked = []
    for k, e in mv.items():
        if k == key or e.get("not_for_you_now"):
            continue
        if ((e.get("availability") or {}).get(LOCATION_ID) or {}).get("state") == "unavailable":
            continue
        gated = bool(idx[k][1] & blocking)
        if gated and not primary_gated:
            continue
        et = (e.get("target") or {}).get("primary")
        same_pat = idx[k][0] == pat and pat != "other"
        if et == tgt and tgt not in (None, "unknown", "other") and same_pat:
            reason, r = "same_stimulus", 0
        elif et == tgt and tgt not in (None, "unknown", "other"):
            reason, r = "same_target", 1
        elif e.get("family") == me.get("family") and (((e.get("target") or {}).get("region") == region and same_pat) or pat == "other"):
            reason, r = "same_family", 2
        else:
            continue
        shares = bool(set(e.get("equipment") or []) & my_eq)
        avail = ((e.get("availability") or {}).get(LOCATION_ID) or {}).get("state") == "available"
        exp = (e.get("history") or {}).get("exposures", 0)
        ranked.append(((r, gated, shares, e.get("length_bias") != me.get("length_bias"), not avail, -exp, k), k, reason))
    ranked.sort()
    return [(k, reason) for _, k, reason in ranked]


# ── coded note signals (pure; feeds the PRIVATE overlay only — never the public library) ────────────────────────
_NEGATION_RE = re.compile(r"(?:\bno|\bnot|\bwasn'?t|\bisn'?t|\bwithout|\bnever|\bzero)\s+(?:\w+\s+){0,2}$")
_DISCOMFORT_RE = re.compile(r"\b(?:did\s*n[o']?t|didnt)\s+feel\s+(?:great|good|right)|\buncomfortable\b|\bdiscomfort\b|\bfelt off\b")
_SWAP_RE = re.compile(r"\bswap(?:ped)?\b|\binstead\b|\bsubstitut\w*|\bin place of\b")
_FORM_CHECK_RE = re.compile(r"\b(?:check|help with|double check|need)\b.{0,25}\bform\b")
_EFFICACY_RE = re.compile(r"\befficacy\b|\btop tier\b|\beffective(?:ness)?\b")
_FIT_RE = re.compile(r"\bmachine\s+(?:does\s*n[o']?t|doesnt)\s+let\b|\bgetting used to\b|\bnew machine\b|\bdifferent machine\b")
_NEG_SENT_EXTRA = re.compile(r"\bfrustrat\w*")


def _word_hit(words: list[str], text: str, negatable: bool = False) -> bool:
    for w in words:
        for m in re.finditer(r"\b" + re.escape(w) + r"\b", text):
            if negatable and _NEGATION_RE.search(text[max(0, m.start() - 40) : m.start()]):
                continue
            return True
    return False


def note_signal_tags(text: str) -> list[str]:
    """Pure. One Hevy exercise note -> sorted coded tags. NEVER returns note text.

    Reuses the training_notes lexicons (joint regions, sentiment), matched as WHOLE WORDS. `pain_flag` is set only when
    #5806's `training_notes_pain.pain_class` says `pain` (`PAIN_SOURCE_ID`, stamped on the overlay): a negated pain word,
    a discomfort note or a form/equipment note is never a pain flag.
    """
    from training.training_notes import _JOINT_REGIONS, _SENTIMENT_NEG, _SENTIMENT_POS, _strip_grip_modality
    from training.training_notes_pain import DISCOMFORT, PAIN, pain_class

    t = " ".join(_strip_grip_modality((text or "").lower().replace("’", "'")).split())
    if not t:
        return []
    tags: set[str] = set()
    regions = [r for r in _JOINT_REGIONS if re.search(r"\b" + re.escape(r) + r"s?\b", t)]
    # #5773: the pain class is #5806's deterministic rule (`training_notes_pain.pain_class`) — only `pain` is a pain flag;
    # `discomfort` is coded as joint discomfort (an N=1 demotion, never an exclusion); `form_or_equipment` is neither.
    cls = pain_class(text or "")
    pain = cls == PAIN
    if pain:
        tags.add("pain_flag")
    if (regions and _DISCOMFORT_RE.search(t)) or cls == DISCOMFORT:
        tags.add("joint_discomfort")
    if pain or "joint_discomfort" in tags:
        tags.update(f"region:{r.replace(' ', '_')}" for r in regions)
    if _word_hit(_SENTIMENT_POS, t):
        tags.add("sentiment_positive")
    if _word_hit(_SENTIMENT_NEG, t) or _NEG_SENT_EXTRA.search(t):
        tags.add("sentiment_negative")
    if _SWAP_RE.search(t):
        tags.add("swap")
    if _FORM_CHECK_RE.search(t):
        tags.add("form_check_requested")
    if _EFFICACY_RE.search(t):
        tags.add("efficacy_question")
    if _FIT_RE.search(t):
        tags.add("equipment_fit")
    for sig in classify_availability_note(t):
        tags.add(f"availability:{sig['signal']}:{sig['equipment']}")
    return sorted(tags)


# ── private-side gate completeness (owner requirement 2026-11-11) ───────────────────────────────────────────────
PRIVATE_GATE_FIELDS = ("measured_input", "comparator", "value")


def private_gate_gaps(lib: dict[str, Any], overlay: Optional[dict[str, Any]]) -> list[dict[str, Any]]:
    """Pure. Every public gate must resolve in the private overlay to a complete row.

    Returns one finding per incomplete gate: {gate_id, movement_ids, missing: [field names]}. Field names and ids
    only — NEVER a threshold value, because this output may land in logs. Empty list = complete.
    A missing / unreadable overlay fails every gate (`missing: ["overlay"]`) — fail closed.
    """
    mv = movements(lib)
    carriers: dict[str, list[str]] = {}
    for k, e in mv.items():
        for g in e.get("gates") or []:
            carriers.setdefault(g, []).append(k)
    rows = (overlay or {}).get("gates") if isinstance(overlay, dict) else None
    findings: list[dict[str, Any]] = []
    for gid, g in sorted((lib.get("gates") or {}).items()):
        who = ["all"] if g.get("applies_to") == "all" else sorted(carriers.get(gid, []))
        missing: list[str] = []
        if not isinstance(rows, dict):
            missing.append("overlay")
        elif not isinstance(rows.get(gid), dict):
            missing.append("gate_row")
        else:
            row = rows[gid]
            for f in PRIVATE_GATE_FIELDS:
                v = row.get(f)
                if v is None or v == "" or v == {} or v == []:
                    missing.append(f)
            if g.get("kind") == "bodyweight_threshold" and "value" not in missing:
                if not isinstance(row.get("value"), (int, float)) or isinstance(row.get("value"), bool):
                    missing.append("value_numeric")
            for p in list(g.get("chain_prerequisites") or []) + list(row.get("chain_prerequisites") or []):
                if p not in mv:
                    missing.append(f"chain_prerequisite:{p}")
        if not g.get("unlock_condition"):
            missing.append("unlock_condition")
        if missing:
            findings.append({"gate_id": gid, "movement_ids": who, "missing": sorted(set(missing))})
    return findings
