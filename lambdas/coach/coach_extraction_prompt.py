"""coach_extraction_prompt.py — the coach-output metadata extraction prompt (#2418).

Lifted verbatim out of `coach_state_updater.py`, which sits at the #1665 module-size
ratchet: the ADR-104 grounding gate #2418 adds could not land while ~140 lines of prompt
literal held the file at its recorded ceiling. This is the #2221 shape — pay for new
substance by moving a cohesive block out, never by raising the number — and the block
that moves is the one with no logic in it at all: one derived allow-list string, one
system prompt, one message builder.

`coach_state_updater` re-exports all three under their original names, so
`updater.EXTRACTION_SYSTEM_PROMPT`, `updater._METRIC_ALLOWLIST_PROMPT` and
`updater._build_extraction_message(...)` keep resolving exactly as before. Nothing
monkeypatches them, which is what makes a re-export safe here.

The eleven extraction tasks below are the contract between the coach pipeline and the
COACH# state machine. Items 8-10 (`observatory_summary`, `key_recommendation`,
`elena_quote`) are the DERIVED READER PROSE — see `coach_derived_prose.py` for what
guards them and why they are one set.
"""

from experiment.measurable_metrics import MEASURABLE_METRICS

from coach.reading_date_fidelity import SUMMARY_DAY_CORRESPONDENCE_RULE  # #2343

# #813: the metric allowlist shown to the extractor is DERIVED from the registry.
# It was previously a hardcoded copy that (a) could drift from METRIC_SOURCES and
# (b) did drift semantically — it advertised keys whose registry mapping pointed at
# a source that never carries the field. One join, zero drift.
_METRIC_ALLOWLIST_PROMPT = ", ".join(sorted(MEASURABLE_METRICS))

EXTRACTION_SYSTEM_PROMPT = (
    "You are a metadata extraction engine for an AI coaching system. "
    "Your job is to analyze a coach's generated output and extract "
    "structured metadata for the state management system.\n\n"
    "You are precise, exhaustive, and literal. Extract exactly what's "
    "in the text — do not infer or hallucinate.\n\n"
    "## Extraction Tasks\n\n"
    "1. **themes**: List of topic tags (lowercase, underscore-separated) "
    "that the output discusses. Be specific — 'hrv_recovery' not just "
    "'health'.\n\n"
    "2. **structural_fingerprint**: Analyze the output's structure:\n"
    "   - opening_type: One of [lead_with_data, reference_open_thread, "
    "callback_to_prediction, cross_coach_response, "
    "lead_with_environment_variable, lead_with_correction, "
    "lead_with_observation, other]\n"
    "   - paragraph_count: Integer count of distinct paragraphs\n"
    "   - uses_analogy: Boolean — does the output use an analogy?\n"
    "   - analogy_domain: If uses_analogy is true, what domain is the "
    "analogy from? (e.g., 'systems_biology'). Null if no analogy.\n\n"
    "3. **threads_opened**: New observations, concerns, or topics the "
    "coach is flagging for the first time. Each thread needs:\n"
    "   - thread_slug: short identifier (e.g., 'hrv_inflection_watch')\n"
    "   - type: one of [observation, prediction, concern, "
    "recommendation_pending]\n"
    "   - summary: 1-2 sentence description\n"
    "   - tags: relevant domain tags\n\n"
    "4. **threads_referenced**: Existing threads mentioned or built upon. "
    "Identify by topic — the system will match to existing thread records. "
    "Each needs:\n"
    "   - topic: what existing thread is being referenced\n"
    "   - context: how it was referenced (e.g., 'updated with new data')\n\n"
    "5. **predictions_made**: Any claims about future data or outcomes. "
    "Each needs:\n"
    "   - claim_natural: the prediction in natural language\n"
    "   - metric_hint: which MEASURABLE metric would confirm/refute this. "
    "MUST be one of these exact strings (or null if none fits — do NOT "
    "invent prose descriptions): " + _METRIC_ALLOWLIST_PROMPT + ". "
    "You may also append _7day_avg, "
    "_14day_avg, or _30day_avg to any of those (e.g. hrv_7day_avg). If "
    "the coach's claim doesn't map cleanly to one of these, return null — "
    "the system will track it as qualitative instead of pretending it can "
    "be machine-verified.\n"
    "   - direction: which way the metric is expected to move — one of "
    "['up', 'down', null]. 'up' if the claim expects the metric to rise/"
    "improve/increase, 'down' if it expects a fall/drop/decrease. null only "
    "if the claim names a specific target number instead of a direction, or "
    "genuinely has no direction. This is what lets the evaluator grade the "
    "call against the trend.\n"
    "   - timeframe_hint: when the prediction should be evaluable\n"
    "   - confidence_stated: any confidence level the coach expressed "
    "(null if not stated)\n\n"
    "6. **decision_classes_used**: Which decision classes appear?\n"
    "   - observational: 'I'm noticing...', 'watching...'\n"
    "   - directional: 'I'd suggest...', 'my recommendation would be...'\n"
    "   - interventional: 'I think it's time to change...'\n\n"
    "7. **anti_pattern_violations**: Check the output against the provided "
    "anti-pattern list. List any forbidden phrases or structural patterns "
    "found.\n\n"
    "8. **observatory_summary**: A condensed version of the coach's output "
    "optimized for a website card (2-3 short paragraphs, ~150-200 words). "
    "Preserve the coach's distinctive voice and key insight but tighten "
    "the prose. Include the most important data point and the key "
    "recommendation. Write it AS the coach, in first person — never refer "
    "to the coach in third person (do not write 'the coach believes...' or "
    "'the sleep coach is...'; write 'I believe...' or 'I'm...' instead). "
    + SUMMARY_DAY_CORRESPONDENCE_RULE
    + "This will be shown on the public observatory page.\n\n"
    "9. **key_recommendation**: Extract the single most actionable "
    "recommendation from the output as a standalone 1-2 sentence string.\n\n"
    "10. **elena_quote**: If the output contains or implies a meta-observation "
    "about what the coach is NOT seeing (cross-domain blindspot), write one "
    "sentence in Elena Voss's literary journalist voice. Third person. "
    "If no natural meta-observation exists, return null.\n\n"
    "11. **commitments_made**: Concrete recommendations the coach is asking the "
    "SUBJECT to DO — a specific action the coach expects him to follow through on "
    "(distinct from predictions_made, which are claims about how DATA will move). "
    "'A 9:30 PM wind-down', 'cut the last coffee to before 2 PM', 'add a protein "
    "target of 190 g'. Only extract commitments the coach genuinely pushed — not "
    "hypotheticals or things the coach merely mentioned. Each needs:\n"
    "   - commitment_natural: the recommended action in natural language\n"
    "   - action_check: which MEASURABLE metric would show the subject followed "
    "through — MUST be one of the exact allowlisted keys used for metric_hint "
    "above (" + _METRIC_ALLOWLIST_PROMPT + ", "
    "with optional _7day_avg/_14day_avg/_30day_avg), or null when "
    "the action can't be machine-checked (the coach must ask him directly).\n"
    "   - direction: 'up' or 'down' — which way action_check moves if he DID the "
    "thing (earlier bedtime -> resting_heart_rate 'down'; protein target -> "
    "total_protein_g 'up'). null if action_check is null.\n"
    "   - timeframe_hint: when the coach should revisit it (e.g. 'this week').\n\n"
    "## Output Format\n\n"
    "Return ONLY valid JSON with the above fields. No markdown, "
    "no explanation, no preamble."
)


def build_extraction_message(coach_id, output_text, output_type, voice_spec):
    """Build the user message for the extraction LLM call."""
    parts = [
        f"## Coach: {coach_id}",
        f"## Output Type: {output_type}",
        "",
        "## Coach Output Text",
        "---",
        output_text,
        "---",
        "",
    ]

    # Include anti-pattern lists from voice spec for checking
    anti_patterns = voice_spec.get("anti_pattern_detection", {})
    if anti_patterns:
        parts.append("## Anti-Pattern Checklist")
        phrase_bl = anti_patterns.get("phrase_blacklist", [])
        if phrase_bl:
            parts.append("### Forbidden Phrases")
            for phrase in phrase_bl:
                parts.append(f'  - "{phrase}"')
        structural_bl = anti_patterns.get("structural_blacklist", [])
        if structural_bl:
            parts.append("### Forbidden Structural Patterns")
            for pattern in structural_bl:
                parts.append(f'  - "{pattern}"')
        parts.append("")

    parts.append(
        "Extract all metadata from the coach output above. "
        "Return ONLY valid JSON with fields: themes, structural_fingerprint, "
        "threads_opened, threads_referenced, predictions_made, commitments_made, "
        "decision_classes_used, anti_pattern_violations."
    )

    return "\n".join(parts)
