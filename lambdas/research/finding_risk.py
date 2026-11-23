"""research/finding_risk.py — the risk vocabulary and risk rules of the research findings store (#6208).

Split out of `research.findings` (the store's registry, which re-exports every name here) under the module-size
ceiling. Pure: no I/O, no clock.

THE TRIPWIRE HAS KNOWN GAPS. `TOUCH_WORDS` refuses a finding whose question, summary or applicability names a drug,
supplement, electrolyte or intake term its declared `touches` do not cover. It is a tripwire, not a classifier: the
owner's declared `touches`, `risk_tier` and the required `risk_rationale` are the record, and a risk field can only be
TIGHTENED by a correction (a lower-risk reading is a new finding). It runs on the record and on every correction to the
question or summary, in every state.

THE OBSERVATION INVARIANT. A finding in an observation state (observation_planned / observation_recorded) touches
exactly ["observation"] at tier <= 2 — always. Nothing that takes on intervention risk can stay an observation.
"""

from __future__ import annotations

import re
from typing import Any


class FindingError(ValueError):
    """A finding or event the ruling forbids — refused at write, never stored (and skipped if found stored)."""


RISK_TIERS: dict[int, str] = {
    1: "observational",
    2: "reversible behavioural",
    3: "training or nutrition modification",
    4: "supplement or electrolyte",
    5: "medication or medical management",
}
#: What a finding touches, and the lowest risk tier that touch can carry. Declared, never inferred — but a
#: question or summary that names a supplement, an electrolyte, a medication or an intake term must declare that touch.
TOUCH_MIN_TIER: dict[str, int] = {
    "observation": 1,
    "behaviour": 2,
    "sleep": 2,
    "training": 3,
    "intake_target": 3,
    "electrolytes": 4,
    "supplements": 4,
    "medication": 5,
}
TOUCHES: tuple[str, ...] = tuple(TOUCH_MIN_TIER)
#: At tier >= 3 a finding touching one of these needs clinical review before anything is tried.
CLINICAL_TOUCHES: frozenset[str] = frozenset({"intake_target", "electrolytes", "supplements", "medication"})
CLINICAL_REVIEW_TIER = 3
CLINICIAN_ONLY_TIER = 5
OBSERVATION_ONLY = ["observation"]
OBSERVATION_MAX_TIER = 2
#: A TRIPWIRE with known gaps, not a classifier. "dose-response" (a training term) is deliberately not a medication word.
TOUCH_WORDS: dict[str, re.Pattern] = {
    "supplements": re.compile(
        r"\bsupplement(?:s|ation|ing|ed)?\b|\bcreatine\b|\bvitamins?\b|\bfish[- ]oil\b|\bomega[- ]?3s?\b|\bmelatonin\b|"
        r"\bashwagandha\b|\bzinc\b",
        re.IGNORECASE,
    ),
    "electrolytes": re.compile(r"\belectrolytes?\b|\bsodium\b|\bpotassium\b|\bmagnesium\b|\bsalt(?:s|y|ed)?\b", re.IGNORECASE),
    "medication": re.compile(
        r"\bmedications?\b|\bprescri(?:be|bed|ption)s?\b|\bmetoprolol\b|\bbeta[- ]?blockers?\b|\bstatins?\b|\bnsaids?\b|"
        r"\bibuprofen\b|\banticoagul\w*|\bdos(?:e|es|age|ages)\b(?!-response)|\bdrugs?\b|\bmedicines?\b",
        re.IGNORECASE,
    ),
    "intake_target": re.compile(
        r"\bkcal\b|\bcalori\w*|\bfasting\b|\bprotein (?:target|floor)s?\b|\bcaffeine\b|\balcohol\b",
        re.IGNORECASE,
    ),
}
LOWER_RISK = "a correction can only tighten risk — a lower-risk reading needs a new finding"
OBSERVATION_LEAK = "a finding in an observation state cannot take on intervention risk; close it and record a new finding"


def normalize_touches(value: Any) -> Any:
    """A sorted list with no repeats; a repeated touch is refused (it is a typo, not more risk). Non-lists pass through
    unchanged for `check_risk` to refuse with its own message."""
    if not isinstance(value, list):
        return value
    if len(set(map(str, value))) != len(value):
        raise FindingError(f"touches lists a touch twice: {value}")
    return sorted(value)


def check_risk(f: dict[str, Any]) -> None:
    """The risk tier, touches and clinical review agree, and the text names nothing the touches do not declare."""
    tier = f.get("risk_tier")
    if not isinstance(tier, int) or isinstance(tier, bool) or tier not in RISK_TIERS:
        raise FindingError("risk_tier must be an integer 1-5: " + "; ".join(f"{k} {v}" for k, v in RISK_TIERS.items()))
    touches = f.get("touches")
    if not isinstance(touches, list) or not touches or any(t not in TOUCH_MIN_TIER for t in touches):
        raise FindingError(f"touches must be a non-empty list drawn from {list(TOUCHES)}")
    normalize_touches(touches)
    text = (
        " ".join(str(f.get(k) or "") for k in ("question", "evidence_summary"))
        + " "
        + str((f.get("applicability") or {}).get("text") or "")
    )
    for touch, pattern in TOUCH_WORDS.items():
        m = pattern.search(text)
        if m and touch not in touches:
            raise FindingError(f"the finding names {m.group(0)!r} — declare '{touch}' in touches")
    floor = max(TOUCH_MIN_TIER[t] for t in touches)
    if tier < floor:
        raise FindingError(f"risk_tier {tier} is below what it touches: {sorted(touches)} needs tier >= {floor} ({RISK_TIERS[floor]})")
    clinical = f.get("clinical_review_required")
    if not isinstance(clinical, bool):
        raise FindingError("clinical_review_required must be true or false")
    if not clinical and (tier > CLINICAL_REVIEW_TIER or (tier == CLINICAL_REVIEW_TIER and set(touches) & CLINICAL_TOUCHES)):
        raise FindingError(
            "clinical_review_required must be true: a tier >= 3 finding touching an intake target, electrolytes, supplements "
            "or medication needs clinical review"
        )


def observation_only(touches: Any, tier: Any) -> bool:
    return list(touches or []) == OBSERVATION_ONLY and isinstance(tier, int) and not isinstance(tier, bool) and tier <= OBSERVATION_MAX_TIER


def tighten_only(field: str, value: Any, current: Any) -> None:
    if field == "risk_tier":
        if isinstance(value, int) and not isinstance(value, bool) and isinstance(current, int) and value < current:
            raise FindingError(f"risk_tier {current} -> {value}: {LOWER_RISK}")
    elif field == "touches":
        if isinstance(value, list) and not set(current or []) <= set(value):
            raise FindingError(f"removing {sorted(set(current or []) - set(value))} from touches: {LOWER_RISK}")
    elif field == "clinical_review_required":
        if current is True and value is not True:
            raise FindingError(f"clearing clinical_review_required: {LOWER_RISK}")
