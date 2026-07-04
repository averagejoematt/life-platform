"""grounded_generation.py — ADR-104: one grounded-generation harness for every
AI narrative surface.

The platform's rule is "the model never does the math" (ADR-062) — this module
is that rule's enforcement arm at generation time. It composes the three proven
pieces that previously lived apart:

  1. Fact injection    — authoritative_facts_block() renders canonical_facts as
                         the AUTHORITATIVE FACTS prompt block (the analyzer's
                         battle-tested wording, incl. the no-invent-trends rule).
  2. Deterministic     — grounding_findings() = hard canonical contradictions
     post-check          (grounding_guard, RHR/recovery/HRV) + the er03-style
                         allow-list number gate generalized for narratives:
                         every number in the output must appear in the input.
                         This is what kills "climbed from X to Y" fabrication —
                         the invented X isn't in anything the model was given.
  3. Regen-once        — regen_once() extracts the duplicated keep-if-strictly-
                         improved harness (ai_expert_analyzer / field_notes) so
                         every surface corrects the same way: one rewrite,
                         kept only if findings strictly decrease, never worse.

Pure functions, no AWS, no HTTP — the caller supplies the regeneration callable.
Fail modes are the caller's choice: keep-best (internal narratives) or
fail-closed (reader-facing surfaces drop/fallback, like the podcast gate).

Import paths: bundled at lambdas/ root AND shipped in the shared layer (with a
flat copy of grounding_guard) so both bundled lambdas and layer modules
(ai_calls' V2 coach render) can use it.
"""

import json
import re

# The tight canonical-contradiction detector (SS-10). Dual path: package-style
# (bundled lambdas/), flat (layer / flattened bundle). Fail-soft to None — the
# number gate still runs; only the vitals-contradiction check is skipped.
try:
    from intelligence.grounding_guard import hard_canonical_contradictions as _hard_contradictions
except ImportError:  # pragma: no cover — environment-dependent
    try:
        from grounding_guard import hard_canonical_contradictions as _hard_contradictions
    except ImportError:
        _hard_contradictions = None

_NUM_RE = re.compile(r"\d+(?:\.\d+)?")
_THOUSANDS_RE = re.compile(r"(?<=\d),(?=\d{3}\b)")

# Numbers narrative prose may always use without them appearing in the input:
# small counts ("three meals", "2 of the last 5 days"), the common prescriptive
# durations, round anchors, and years. Everything else must be earned from the
# input — a plausible-but-invented vital (58, 13.8, 172) is never benign.
_BENIGN_NUMBERS = (
    set(float(x) for x in range(0, 13)) | {15.0, 20.0, 30.0, 45.0, 60.0, 90.0, 100.0} | set(float(y) for y in range(2020, 2031))
)


def numbers_in_text(text: str) -> set:
    """Distinct numeric values in a string (floats), thousands-separators handled."""
    out = set()
    for m in _NUM_RE.findall(_THOUSANDS_RE.sub("", text or "")):
        try:
            out.add(round(float(m), 4))
        except ValueError:
            pass
    return out


def allowed_numbers(*sources) -> set:
    """The allow-list: every number present in what the model was given.

    Accepts strings and any JSON-serializable structure (dicts/lists are
    json.dumps'd, so nested values count). Pass the prompt, the data blob,
    and the canonical facts — the union is the model's numeric vocabulary.
    """
    allowed = set()
    for src in sources:
        if src is None:
            continue
        text = src if isinstance(src, str) else json.dumps(src, default=str)
        allowed |= numbers_in_text(text)
    return allowed


def fabricated_numbers(text: str, allowed: set) -> list:
    """Numbers in the output that appear nowhere in the input (minus benign)."""
    out = []
    for x in sorted(numbers_in_text(text)):
        if x in _BENIGN_NUMBERS:
            continue
        if any(abs(x - a) < 0.01 for a in allowed):
            continue
        # An integer restatement of an input float (64 for 64.2) is grounded.
        if any(abs(x - round(a)) < 0.01 for a in allowed):
            continue
        out.append(x)
    return out


def authoritative_facts_block(facts: dict) -> str:
    """Render canonical facts as the AUTHORITATIVE FACTS system-prompt block.

    The analyzer's proven wording (truth audit Phase 3 + the no-invent-trends
    hard rule) — one source so every surface injects facts identically.
    Returns "" when no facts are available (caller simply omits the block).
    """
    facts = facts or {}
    lines = []
    if facts.get("protein_g_avg") is not None:
        lines.append(
            f"  - Protein INTAKE averages {facts['protein_g_avg']:g} g/day "
            f"(target {int(facts.get('protein_g_target') or 190)} g, floor {int(facts.get('protein_g_floor') or 170)} g). "
            f"His actual intake is ~{facts['protein_g_avg']:g} g — never state intake as the target or floor."
        )
    if facts.get("recovery_pct") is not None:
        lines.append(f"  - Latest Whoop recovery: {facts['recovery_pct']:g}%")
    if facts.get("hrv_ms") is not None:
        lines.append(f"  - Latest HRV: {facts['hrv_ms']:g} ms (HRV is in MILLISECONDS, never bpm)")
    if facts.get("rhr_bpm") is not None:
        lines.append(f"  - Latest resting HR: {facts['rhr_bpm']:g} bpm")
    if facts.get("latest_weight") is not None:
        lines.append(f"  - Latest weight: {facts['latest_weight']:g} lb")
    if facts.get("weekly_rate_lbs") is not None:
        lines.append(f"  - Weekly weight rate: {facts['weekly_rate_lbs']:g} lb/week (signed; negative = losing)")
    if not lines:
        return ""
    return (
        "AUTHORITATIVE FACTS (cite these EXACT numbers; do not invent, round away, or "
        "substitute a target/floor for an actual value):\n" + "\n".join(lines) + "\n"
        "HARD RULE for resting HR, HRV, and recovery: state ONLY the exact value above. "
        "Do NOT invent a trend, a range, a multi-day figure, or a 'climbed/dropped from X to Y' "
        "for these — you do not have that history. If you have no specific number for a claim, "
        "describe the pattern qualitatively instead of inventing a figure."
    )


def grounding_findings(text: str, facts: dict = None, allowed: set = None) -> list:
    """Deterministic grounding check. Returns [{type, detail, ...}] — empty = grounded.

    - "contradiction": a stated RHR/recovery/HRV hard-contradicts canonical facts
      (grounding_guard's per-metric tolerances + grounded-anywhere logic).
    - "fabricated_number": a number appears in the output but nowhere in the
      input allow-list (and isn't benign) — the trend/range fabrication class.
    """
    findings = []
    if facts and _hard_contradictions is not None:
        for c in _hard_contradictions(text, facts):
            findings.append({"type": "contradiction", **c})
    if allowed is not None:
        for x in fabricated_numbers(text, allowed):
            findings.append(
                {
                    "type": "fabricated_number",
                    "claimed": x,
                    "detail": f"the number {x:g} appears in the narrative but nowhere in the data provided",
                }
            )
    return findings


def correction_prompt(findings: list) -> str:
    """The correction addendum for the single rewrite (analyzer's proven shape)."""
    lines = ["CORRECTION REQUIRED — your draft states numbers that are not grounded in the data:\n"]
    for i, f in enumerate(findings, 1):
        if f.get("type") == "contradiction" and f.get("canonical") is not None:
            lines.append(f"{i}. {f['detail']}. Use {f['canonical']:g}, or omit the metric — never invent one.")
        else:
            lines.append(f"{i}. {f['detail']}. Remove it or describe the pattern qualitatively — never invent a figure.")
    lines.append("\nRewrite with these corrected. Keep your voice and length; do not mention that a correction was made.")
    return "\n".join(lines)


def regen_once(text: str, findings_fn, regen_fn):
    """One corrective rewrite, kept only if strictly better. Never regresses.

    findings_fn(text) -> list of findings (e.g. a grounding_findings closure).
    regen_fn(correction: str) -> str — the caller's single regeneration call
    (model, tokens, prompt assembly all stay the caller's business).

    Returns (best_text, findings_for_best_text, corrected: bool).
    """
    findings = findings_fn(text)
    if not findings:
        return text, [], False
    try:
        fixed = regen_fn(correction_prompt(findings))
    except Exception:
        return text, findings, False
    if not (fixed or "").strip():
        return text, findings, False
    fixed_findings = findings_fn(fixed)
    if len(fixed_findings) < len(findings):
        return fixed, fixed_findings, True
    return text, findings, False
