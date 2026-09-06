"""experiment/plan_facts.py — the plan root's FIGURES, derived once from user_goals (#3518).

WHY THIS MODULE
---------------
The 2026-09-05 review (R4) met two step floors a page apart: the frozen pre-registration
says "daily step counts at or above the 3-mile minimum (~6,000-7,000 steps)", the cockpit
says "the 6,000-step pre-registered floor", and the physical coach's served position
summary said "his 8,000+ steps/day protocol". The 8,000 exists only in
`config/experiment_library.json` — an unactivated shelf experiment that rode into the
coach's prompt — so every DATA-grounding gate passed it: the number was in the input.

ADR-104's invariant for a plan figure is *claims ⊆ plan facts*, never the reverse
(`reference_frozen_prereg_is_stamped_fix_the_test`). That needs the plan's figures as
STRUCTURE, in one place, derived from the plan root rather than re-typed per surface:

  * `deploy/seed_genesis_preregistration.py` carries them into every FUTURE freeze as the
    `plan_facts` block (the sealed cycle-17 artifact already holds the first three keys —
    it is content-addressed and is never edited to add the rest);
  * `ai/plan_facts_gate.py` grades a plan-framed claim ("8,000+ steps/day protocol",
    "6,000-step floor", "1,500 kcal target") against the same figures at generation time.

Pure: no boto3 at import. `load_plan_facts()` is the one I/O helper and fails SOFT to
``None`` — a gate must never be the thing that takes a narrative surface down (#1691).
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, Set

PLAN_SOURCE = "config/user_goals.json"

# "roughly 6,000-7,000 steps" / "8,000+ steps" / "6,000 steps" inside the movement target
# prose — the plan root states the step floor as a RANGE in free text, so it is parsed
# here once rather than eyeballed per surface.
_STEP_FIGURE_RE = re.compile(
    r"(\d{1,3}(?:,\d{3})+|\d{3,6})(?:\s*(?:-|–|—|to)\s*(\d{1,3}(?:,\d{3})+|\d{3,6}))?\s*\+?\s*steps?\b", re.IGNORECASE
)
# "170g", "180 g", "160g" inside the protein note — the sanctioned protein figures the plan
# root names in prose beside the structural floor.
_GRAM_FIGURE_RE = re.compile(r"(?<![\d.])(\d{2,3})\s*g(?:rams?)?\b", re.IGNORECASE)


def _int(value: Any) -> Optional[int]:
    try:
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def plan_facts_from_goals(goals: Dict[str, Any]) -> Dict[str, Any]:
    """The structural plan block for one `user_goals.json` document.

    The first three keys are EXACTLY the block the cycle-17 freeze sealed (source,
    calorie target, protein floor, eating window — `test_plan_literal_reconciliation`
    reads two of them as fields); the rest are additive and ride only in freezes made
    after this landed. A missing target yields ``None`` for that key, never a guess.
    """
    targets = goals.get("targets") or {}
    nutrition = targets.get("nutrition") or {}
    # The movement target lives under targets.training in the plan root; the top-level
    # fallback keeps the derivation honest if the key is ever hoisted.
    movement = str((targets.get("training") or {}).get("daily_movement_target") or targets.get("daily_movement_target") or "")
    step_lo: Optional[int] = None
    step_hi: Optional[int] = None
    for m in _STEP_FIGURE_RE.finditer(movement):
        lo = _int(m.group(1))
        hi = _int(m.group(2)) if m.group(2) else lo
        if lo is None:
            continue
        step_lo = lo if step_lo is None else min(step_lo, lo)
        step_hi = hi if step_hi is None else max(step_hi, hi or lo)
    protein_prose = sorted({int(g) for g in _GRAM_FIGURE_RE.findall(str(nutrition.get("protein_note") or ""))})
    facts: Dict[str, Any] = {
        "source": PLAN_SOURCE,
        "daily_calories_target": _int(nutrition.get("daily_calories_target")),
        "daily_protein_min_g": _int(nutrition.get("daily_protein_min_g")),
        "eating_window": (nutrition.get("eating_window") or {}).get("window"),
        # ── additive since #3518 (future freezes only) ──
        "daily_steps_floor": step_lo,
        "daily_steps_range": [step_lo, step_hi] if step_lo is not None and step_hi is not None else None,
        "daily_fiber_min_g": _int(nutrition.get("daily_fiber_min_g")),
        "protein_figures_named_g": protein_prose,
    }
    return facts


def plan_figures(facts: Optional[Dict[str, Any]]) -> Dict[str, Set[float]]:
    """quantity -> the set of figures the plan sanctions for it.

    ``steps`` carries BOTH ends of the range (a claim inside the range is graded by
    ``plan_facts_gate`` as within-plan; the endpoints are what a summary may quote).
    Empty set for a quantity the plan does not state — the gate then has nothing to
    hold that quantity to, and says nothing (never a finding from an absent plan).
    """
    facts = facts or {}
    out: Dict[str, Set[float]] = {"steps": set(), "protein_g": set(), "calories": set(), "fiber_g": set()}
    rng = facts.get("daily_steps_range")
    if isinstance(rng, (list, tuple)) and len(rng) == 2 and all(isinstance(x, (int, float)) for x in rng):
        out["steps"] |= {float(rng[0]), float(rng[1])}
    elif isinstance(facts.get("daily_steps_floor"), (int, float)):
        out["steps"].add(float(facts["daily_steps_floor"]))
    if isinstance(facts.get("daily_protein_min_g"), (int, float)):
        out["protein_g"].add(float(facts["daily_protein_min_g"]))
    for g in facts.get("protein_figures_named_g") or ():
        if isinstance(g, (int, float)):
            out["protein_g"].add(float(g))
    if isinstance(facts.get("daily_calories_target"), (int, float)):
        out["calories"].add(float(facts["daily_calories_target"]))
    if isinstance(facts.get("daily_fiber_min_g"), (int, float)):
        out["fiber_g"].add(float(facts["daily_fiber_min_g"]))
    return out


def load_plan_facts(bucket: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The live plan block: the repo file when present (tests, scripts, local runs),
    else S3 `config/user_goals.json` (the Lambda runtime — config/ is not bundled).
    ``None`` on any failure; the caller disarms the plan class and logs, never raises.
    """
    try:
        from common.repo_config import config_path

        path = config_path("user_goals.json")
        with open(path, encoding="utf-8") as fh:
            return plan_facts_from_goals(json.load(fh))
    except Exception:  # noqa: BLE001 — no local file: fall through to S3
        pass
    try:
        import os

        import boto3

        s3 = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        resp = s3.get_object(Bucket=bucket or os.environ.get("S3_BUCKET", "matthew-life-platform"), Key=PLAN_SOURCE)
        return plan_facts_from_goals(json.loads(resp["Body"].read()))
    except Exception:  # noqa: BLE001 — fail-soft by contract (see module docstring)
        return None
