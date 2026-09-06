"""ai/plan_facts_gate.py — the plan-figure grounding class (#3518, ADR-104).

THE DEFECT CLASS
----------------
The ADR-104 number gate asks "does this figure appear in what the model was given?".
That is the right question for a DATA figure and the wrong one for a PLAN figure: the
live 2026-09-04 physical summary said "his 8,000+ steps/day protocol" while the frozen
pre-registration, `config/user_goals.json` and the cockpit all say a 6,000-7,000 step
floor. The 8,000 was in the input — an unactivated shelf experiment in
`config/experiment_library.json` rode into the prompt — so every allow-list passed it,
and the intelligence layer's only numeric cross-check (`_NUMERIC_CLAIM_RE`) matches
unit-bearing numbers only; a step count carries no unit token.

THE RULE
--------
A plan-FRAMED claim — a step / protein / calorie / fiber figure sitting next to
protocol framing ("protocol", "floor", "target", "goal", "minimum", "prescribed", …) —
must equal a figure the plan states for that quantity, or lie inside its stated range,
or appear in the caller's OBSERVED fact set for it. Nothing else licenses it: not the
prompt, not the narrative being condensed, not the shelf. The invariant is the one the
sealed pre-registration already lives under: *claims ⊆ plan facts*, never the reverse.

FRAMING-SCOPED, like `baseline_freshness`: an observed count ("you walked 4,312 steps
yesterday") carries no plan framing and is never graded here — the numbers class still
grades it against the data. This is what keeps the class safe to arm broadly: it says
nothing about a figure that is not presented as the plan.

This is the sibling `_NUMERIC_CLAIM_RE` the issue asks for: `plan_quantity_claims()`
matches a bare integer >= 100 (thousands separators handled, "8,000+" and "6,000-7,000"
ranges included) with a following quantity noun, so a step or count claim is visible.

Pure: no AWS, no clock. `derived_prose_plan_findings()` is the one convenience wrapper
that loads the plan (cached, fail-soft) for the coach-state condensation gate, whose
module sits at its #1665 line ceiling and cannot host the loader itself.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from experiment.plan_facts import load_plan_facts, plan_figures

logger = logging.getLogger()

FINDING_TYPE = "plan_figure_contradiction"

# A number token: thousands-separated or bare, optional decimal, optional trailing "+".
_NUM = r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
_RANGE = rf"{_NUM}\s*\+?(?:\s*(?:-|–|—|to)\s*{_NUM})?\s*\+?"

# quantity -> the claim regexes. Each pattern's numbered groups hold the figure(s); the
# quantity is the noun the figure is attached to, in either order for the gram nouns.
_QUANTITY_PATTERNS: Dict[str, Tuple[re.Pattern, ...]] = {
    "steps": (re.compile(rf"(?<![\d.]){_RANGE}\s*[- ]?steps?\b(?!\s*(?:per|/)\s*(?:minute|min)\b)", re.IGNORECASE),),
    "protein_g": (
        re.compile(rf"(?<![\d.]){_RANGE}\s*[- ]?(?:g|grams?)\b(?:\s+of)?\s+(?:daily\s+)?protein\b", re.IGNORECASE),
        re.compile(rf"\bprotein\b[^.;\n]{{0,30}}?(?<![\d.]){_RANGE}\s*[- ]?(?:g|grams?)\b", re.IGNORECASE),
    ),
    "calories": (re.compile(rf"(?<![\d.]){_RANGE}\s*[- ]?(?:kcal|calories?|cal)\b", re.IGNORECASE),),
    "fiber_g": (
        re.compile(rf"(?<![\d.]){_RANGE}\s*[- ]?(?:g|grams?)\b(?:\s+of)?\s+(?:daily\s+)?fib(?:er|re)\b", re.IGNORECASE),
        re.compile(rf"\bfib(?:er|re)\b[^.;\n]{{0,30}}?(?<![\d.]){_RANGE}\s*[- ]?(?:g|grams?)\b", re.IGNORECASE),
    ),
}

# Plan framing. Only a figure with one of these within `proximity` characters on either
# side — inside its own clause (a `.`/`;` boundary cuts the window) — is graded. "per
# day"/"/day" alone is NOT framing: "you averaged 4,300 steps/day" is an observation.
_PLAN_FRAMING_RE = re.compile(
    r"\b(?:protocol|floor|target(?:s|ed)?|goal|minimum|maximum|prescri(?:bed|ption)|"
    r"pre-?registered|plan(?:ned)?|aim(?:ing)?|threshold|budget|ceiling|cap|commit(?:ted|ment)|"
    r"should\s+(?:be\s+)?(?:hit|reach|clear|walk|eat|get)|need(?:s)?\s+to\s+(?:hit|reach|clear|walk|eat|get))\b",
    re.IGNORECASE,
)

_QUANTITY_LABEL = {"steps": "daily steps", "protein_g": "protein (g)", "calories": "calories (kcal)", "fiber_g": "fiber (g)"}
# The issue's bar for a UNITLESS noun: a bare integer >= 100 with a following noun. The
# unit-bearing quantities (g, kcal) are claims at any size — "25 g of fiber" is a plan
# figure exactly as much as "170 g protein".
_MIN_CLAIM = {"steps": 100.0, "protein_g": 1.0, "calories": 100.0, "fiber_g": 1.0}


def _to_float(token: str) -> Optional[float]:
    try:
        return float(token.replace(",", ""))
    except (TypeError, ValueError):
        return None


def plan_quantity_claims(text: str) -> List[Dict[str, Any]]:
    """Every plan-quantity figure in ``text``: ``{quantity, value, start, end, claim}``.

    A range yields one entry per endpoint. A unitless step figure below 100 is ignored —
    the small counts the number gate treats as benign are not plan figures either.
    """
    out: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, int, float]] = set()
    for quantity, patterns in _QUANTITY_PATTERNS.items():
        for rx in patterns:
            for m in rx.finditer(text or ""):
                for g in m.groups():
                    if not g:
                        continue
                    value = _to_float(g)
                    if value is None or value < _MIN_CLAIM[quantity]:
                        continue
                    key = (quantity, m.start(), value)
                    if key in seen:
                        continue
                    seen.add(key)
                    # `start`/`end` are the FIGURE's own span, not the whole match: the
                    # framing window is measured from the number, so "protein target of
                    # 190g" sees its framing and "he averages 17 g fiber" does not.
                    gi = m.groups().index(g) + 1
                    out.append({"quantity": quantity, "value": value, "start": m.start(gi), "end": m.end(gi), "claim": m.group(0).strip()})
    out.sort(key=lambda c: (c["start"], c["quantity"], c["value"]))
    return out


_CLAUSE_BOUNDARY_RE = re.compile(r"[.;!?\n]")


def _clause_bounds(text: str, start: int, end: int, proximity: int) -> Tuple[int, int]:
    """The window a framing token may occupy for the figure at [start, end): `proximity`
    characters either side, cut at the figure's own clause boundary."""
    lo = max(0, start - proximity)
    before = text[lo:start]
    cut = list(_CLAUSE_BOUNDARY_RE.finditer(before))
    if cut:
        lo += cut[-1].end()
    hi = min(len(text), end + proximity)
    m = _CLAUSE_BOUNDARY_RE.search(text[end:hi])
    if m:
        hi = end + m.start()
    return lo, hi


_ANY_NUMBER_RE = re.compile(r"(?<![\d.])\d{1,3}(?:,\d{3})+(?:\.\d+)?|(?<![\d.,])\d+(?:\.\d+)?")


def plan_framed_claims(text: str, claims: List[Dict[str, Any]], proximity: int) -> List[Dict[str, Any]]:
    """The subset of ``claims`` a framing token licenses as a PLAN claim.

    Each framing token binds to the NEAREST number inside its clause window — any
    number, not only a recognised claim — so in "protein averaged 132 g against the
    170 g floor" the word `floor` binds to 170 and the observed 132 stays an
    observation for the numbers class. A claim is framed only when it IS the number a
    framing token bound to.
    """
    text = text or ""
    numbers = [(m.start(), m.end()) for m in _ANY_NUMBER_RE.finditer(text)]
    bound: Set[int] = set()
    for fm in _PLAN_FRAMING_RE.finditer(text):
        best, best_dist = None, None
        for ns, ne in numbers:
            lo, hi = _clause_bounds(text, ns, ne, proximity)
            if fm.start() < lo or fm.end() > hi:
                continue
            dist = ns - fm.end() if fm.end() <= ns else fm.start() - ne
            if best_dist is None or dist < best_dist:
                best, best_dist = ns, dist
        if best is not None:
            bound.add(best)
    return [c for c in claims if c["start"] in bound]


def _within_plan(value: float, sanctioned: Set[float], observed: Set[float]) -> bool:
    if value in sanctioned or value in observed:
        return True
    if len(sanctioned) >= 2 and min(sanctioned) <= value <= max(sanctioned):
        return True  # inside the plan's stated range ("~6,500 steps" against 6,000-7,000)
    return False


def plan_figure_findings(
    text: str,
    plan_facts: Optional[Dict[str, Any]],
    *,
    observed: Optional[Dict[str, Iterable[float]]] = None,
    quantities: Optional[Iterable[str]] = None,
    proximity: int = 36,
) -> List[Dict[str, Any]]:
    """Deterministic plan-figure check. Returns ``[{type, quantity, claimed, plan, detail}]``.

    ``plan_facts`` is the block `experiment.plan_facts.plan_facts_from_goals` builds (the
    same block a freeze seals). ``None`` returns ``[]`` — the caller has no plan, so the
    class is disarmed rather than guessing one. ``observed`` maps a quantity to the
    figures the day's fact set holds for it (e.g. ``{"protein_g": [132.4, 190, 170]}``);
    a plan-framed claim equal to an observed figure is licensed by the data.
    ``quantities`` restricts the graded set (default: every quantity the plan states).
    """
    if not plan_facts or not text:
        return []
    sanctioned = plan_figures(plan_facts)
    graded = set(quantities) if quantities is not None else set(sanctioned)
    obs = {q: {float(v) for v in vals} for q, vals in (observed or {}).items()}
    findings: List[Dict[str, Any]] = []
    reported: Set[Tuple[str, float]] = set()
    claims = [c for c in plan_quantity_claims(text) if c["quantity"] in graded and sanctioned.get(c["quantity"])]
    for claim in plan_framed_claims(text, claims, proximity):
        q, value = claim["quantity"], claim["value"]
        if _within_plan(value, sanctioned[q], obs.get(q, set())):
            continue
        if (q, value) in reported:
            continue
        reported.add((q, value))
        plan_list = sorted(sanctioned[q])
        findings.append(
            {
                "type": FINDING_TYPE,
                "quantity": q,
                "claimed": value,
                "plan": plan_list,
                "claim": claim["claim"],
                "detail": (
                    f'the narrative presents "{claim["claim"]}" as the plan, but the plan root '
                    f"({plan_facts.get('source', 'config/user_goals.json')}) states {_QUANTITY_LABEL[q]} as "
                    + (f"{plan_list[0]:g}-{plan_list[-1]:g}" if len(plan_list) > 1 else f"{plan_list[0]:g}")
                    + " — a figure from a shelf experiment or the model's memory is not the protocol"
                ),
            }
        )
    return findings


def correction_line(finding: Dict[str, Any]) -> str:
    """The rewrite instruction for one finding (the shape `correction_prompt` appends)."""
    plan = finding.get("plan") or []
    stated = f"{plan[0]:g}-{plan[-1]:g}" if len(plan) > 1 else (f"{plan[0]:g}" if plan else "the plan's figure")
    return f"{finding.get('detail')}. Use {stated} for the {_QUANTITY_LABEL.get(finding.get('quantity', ''), 'plan')} figure, or drop the figure — never a protocol the plan does not state."


# ── the derived-prose convenience seam (coach_state_updater is at its line ceiling) ──
# The quantities graded on the served coach summary. Steps and calories are stated ONCE
# in the plan root and nowhere else; protein and fiber have a second configured source
# (`daily_metrics_compute`'s profile target/floor, which the AUTHORITATIVE FACTS block
# hands every coach as "target 190 g") that this seam does not hold, so grading them
# here would flag a figure the platform itself supplied. A caller that passes the day's
# `observed` facts may grade all four; this seam grades what it can grade honestly.
DERIVED_PROSE_QUANTITIES = ("steps", "calories")
_PLAN_CACHE: Dict[str, Any] = {}


def cached_plan_facts() -> Optional[Dict[str, Any]]:
    """The plan block, loaded once per container. ``None`` (disarmed, logged once) on failure."""
    if "facts" not in _PLAN_CACHE:
        facts = load_plan_facts()
        _PLAN_CACHE["facts"] = facts
        if facts is None:
            logger.warning("[#3518] plan facts unavailable — the plan-figure class is DISARMED for this container")
    return _PLAN_CACHE["facts"]


def derived_prose_plan_findings(text: str, coach_id: str = "") -> List[Dict[str, Any]]:
    """`plan_figure_findings` over the live plan for a coach's derived reader prose.

    Observed figures are deliberately NOT drawn from the narrative being condensed —
    that narrative is where the 8,000 came from. The log line is the live proof the
    class ran (#3518's first-live-output evidence): one line per gated condensation.
    """
    findings = plan_figure_findings(text, cached_plan_facts(), quantities=DERIVED_PROSE_QUANTITIES)
    logger.info("[#3518] plan-figure gate ran for %s: %d finding(s)", coach_id or "?", len(findings))
    return findings
