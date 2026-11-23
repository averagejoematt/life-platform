"""brief_rec_screen.py — no unsupported medical assertion reaches the compact Morning Brief (#6240, owner ruling 2026-11-23 #6241 §2).

A model-written recommendation (the TL;DR + guidance call's `guidance` items) is HELD — not rewritten, not shown —
when it falls in a HIGH-STAKES CLAIM CLASS and is not grounded in a source the platform verified. The original text is
kept on the private SEND# row (`held_recs`, with the classes) for investigation; logs carry counts only.

THE CLAIM CLASSES (deterministic patterns, precision over recall, like `ai.safety_contract`):
  clearance       a score or ratio read as permission ("cleared for hard training", "safe to push")
  disease         a named disease or condition, or a risk claim about one ("apnea risk", "thyroid", "diabetes")
  diagnosis       a diagnosis or deficiency claim ("you may have…", "a sign of…", "deficient")
  medication      a medicine, a prescription, a dose ("200 mg", "stop taking", a named drug class)
  genomic         genes, variants, "your genome" — Tier-2 owner-only (#1943): NEVER shown, grounded or not
  threshold       a physiological cut-off ("below 285 lb, the point where … drops")
  lab             lab interpretation or a test order ("CMP, CBC, TSH", "your renal markers")
  physiology      a stated body mechanism ("your body will pull from lean tissue", "metabolic adaptation")

THE GROUNDING RULE. A high-stakes class passes only for a recommendation whose `source` the platform computed from
stored rows by a fixed rule (`GROUNDED_SOURCES`). The model's guidance items carry no provenance — the guidance call
stores plain text with no citation, and the brief's grounding gate (`ai.grounded_generation`) checks NUMBERS against a
fact set, not medical claims — so a model-written high-stakes recommendation is never grounded today and is always
held. That is the honest state, stated rather than papered over: grounding a medical claim needs a citation the
generator does not produce, and building one is the model-judge project the owner ruled out.

Clean recommendations (a walk after dinner, protein at breakfast, an earlier bedtime with his own sleep numbers, the
food-export housekeeping line) match no class and pass. Pure module: no AWS, no clock, no I/O.
"""

from __future__ import annotations

import re

GROUNDED_SOURCES = frozenset({"readiness", "food_export"})  # rule-computed from stored rows (brief_hybrid)
NEVER_SHOWN = frozenset({"genomic"})

CLAIM_CLASSES: tuple[tuple[str, re.Pattern], ...] = (
    (
        "clearance",
        re.compile(
            r"\b(cleared|medical clearance|(?:have|got|given) clearance|safe to|safe zone|green light|all clear|good to go|fine to train|nothing to worry"
            r"|ready (?:for|to) (?:train|push|go hard)|hard training (?:or [a-z -]+ )?is fine)\b",
            re.I,
        ),
    ),
    (
        "genomic",
        # words any case; acronyms case-sensitive ("variant" alone is an exercise word, so it needs "genetic")
        re.compile(
            r"\b((?i:genom\w*|genetic\w*|genes?|alleles?|homozyg\w*|heterozyg\w*|polygenic|your dna)|DNA|SNPs?|rs\d{3,}|APOE\d?|MTHFR|FTO)\b"
        ),
    ),
    (
        "disease",
        re.compile(
            r"\b(apn(?:o)?ea|diabet\w*|prediabet\w*|hypertension|heart (?:disease|attack|failure)|cardiac|cardiovascular|stroke"
            r"|cancer|thyroid|hypothyroid\w*|hyperthyroid\w*|kidney|renal|liver disease|fatty liver|atrial fibrillation|afib"
            r"|arrhythmi\w*|dementia|sarcopenia|osteopor\w*|metabolic syndrome|gout|anaemi\w*|anemi\w*)\b",
            re.I,
        ),
    ),
    (
        "diagnosis",
        re.compile(
            r"\b(diagnos\w*|you (?:may |might |likely |probably )?have (?:a |an )?\w+ (?:disorder|condition|syndrome|deficiency)"
            r"|symptoms? of|signs? of (?:a |an )?(?:disorder|condition|deficiency|disease)|deficien\w+|disorder|syndrome)\b",
            re.I,
        ),
    ),
    (
        "medication",
        re.compile(
            r"\b(medication\w*|medicine\w*|prescri\w*|dosage|doses?|\d+\s?mg|metoprolol|beta[- ]?blockers?|statins?|metformin"
            r"|semaglutide|tirzepatide|GLP-1|stop taking|start taking)\b",
            re.I,
        ),
    ),
    (
        "lab",
        re.compile(
            r"\b(CMP|CBC|HbA1c|A1c|hs-?CRP|CRP|TSH|free T[34]|T3|T4|ferritin|LDL|HDL|triglycerides?|lipid panel|blood panel"
            r"|blood ?work|lab (?:results?|panel|work)|labs|biomarkers?|eGFR|creatinine|renal markers|fasting insulin|fasting glucose)\b",
            re.I,
        ),
    ),
    (
        "physiology",
        re.compile(
            r"\b(lean (?:tissue|mass)|muscle (?:loss|breakdown|wasting)|catabol\w*|metabolic (?:adaptation|damage|slowdown)"
            r"|hormon\w*|cortisol|testosterone|insulin (?:resistance|sensitivity)|inflammation|inflammatory)\b",
            re.I,
        ),
    ),
)
_THRESHOLD_NUMBER = re.compile(
    r"\b(?:below|under|above|over|past|beneath|cross(?:es|ed|ing)?|hit(?:ting)?)\s+\d{2,4}(?:\.\d+)?\s*(?:lbs?|pounds|kg|bpm|ms|mg/dl|mmol)?\b",
    re.I,
)
_THRESHOLD_WORD = re.compile(r"\b(risk|threshold|the point where|cut-?off|tipping point|drops? (?:substantially|sharply))\b", re.I)


def claim_classes(text: str) -> list:
    """Every high-stakes class the sentence makes a claim in (empty = a clean recommendation)."""
    s = str(text or "")
    out = [name for name, rx in CLAIM_CLASSES if rx.search(s)]
    if _THRESHOLD_NUMBER.search(s) and _THRESHOLD_WORD.search(s):
        out.append("threshold")
    return out


def screen(text: str, source: str) -> tuple[bool, list]:
    """(shown, classes). A grounded source passes its high-stakes classes, except a class never shown at all."""
    classes = claim_classes(text)
    if not classes:
        return True, []
    if any(c in NEVER_SHOWN for c in classes):
        return False, classes
    return (source in GROUNDED_SOURCES), classes
