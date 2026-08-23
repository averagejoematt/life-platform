"""coach_derived_prose.py — the OUTPUT# record's DERIVED reader prose (#2418).

WHAT THIS OWNS
--------------
`coach_state_updater` asks Haiku to condense a coach's generated narrative into four
short fields (#2972 added `public_summary`, the one field with a PUBLIC audience
frame), and those fields — not the narrative — are what most readers actually
see:

  * `observatory_summary` — the coach-analysis text `/api/coach_analysis` prefers over
    `content` (site_api_coach_narrative), the observatory card's body, and the
    `position_summary` slot on `/api/coaching-dashboard`;
  * `key_recommendation` — preferred over BOTH of those on three serving paths
    (`site_api_coach_profile`, the Panel podcast's co-host material, the daily
    reflection's factual basis);
  * `elena_quote` — the observatory card's meta-observation line.

They are a SET, not one field. #2343 and #2390 each guarded `observatory_summary`
alone; the census for #2418 measured six serving paths and found `key_recommendation`
outranking it on half of them with no guard at all. Guarding the instance and not the
set is how this class keeps coming back, so this module names the set once and every
gate, hold and read site derives from that name.

WHY IT IS ITS OWN MODULE
------------------------
Two reasons. The blob/hold/read helpers are needed on BOTH sides of the platform —
the writer (`coach/coach_state_updater.py`) and three readers in three different
packages (`web/`, `emails/`, `compute/`) — and a shared contract restated at four call
sites is a contract that drifts. And `coach_state_updater.py` sits at the #1665 size
ratchet, so the gate's supporting machinery has to live beside it rather than in it
(the #2221 shape). The `grounding_findings()` chokepoint call itself deliberately
stays in `coach_state_updater` — the #2390 census resolves a module's invoke seam to a
surface registered in THAT module, and an exemption pointing somewhere else was not
what #2418 asked for.

Pure: no boto3, no clock, no network. The one model call (`recondense`) takes the
caller's own `call_model` so this module never picks a transport.
"""

from common.text_utils import truncate_at_word

from coach.reading_date_fidelity import SUMMARY_DAY_CORRESPONDENCE_RULE

# The set, named once. Order is the WRITE order (how the extraction prompt lists them),
# not the read preference — `served_summary` below owns that separately.
# #2972 added `public_summary` — the ONE public-audience-frame field (third person for
# the subject, `coach/audience_guard.py` enforces it at write and at every public read
# seam). It joins THIS set so the ADR-104 grounding gate, the HOLD and the recondense
# cover it like the other three; it deliberately does NOT join
# SERVED_SUMMARY_PREFERENCE below, whose consumers are owner/coach-register surfaces.
DERIVED_PROSE_FIELDS = ("observatory_summary", "key_recommendation", "elena_quote", "public_summary")

# The read preference every serving path already used, made explicit so the six sites
# cannot drift apart. `content` is the coach's full narrative — the artifact that
# passed the generation-time grounding gate — and is the honest fallback for all three.
SERVED_SUMMARY_PREFERENCE = ("key_recommendation", "observatory_summary")

RECONDENSE_SYSTEM_PROMPT = (
    "You rewrite the four short reader-facing condensations of an AI coach's output. "
    "The coach's full narrative is the ONLY source of truth: every number, every date "
    "and every claim you write must already be present in it. You may shorten, "
    "paraphrase and round; you may not introduce.\n\n"
    "Return ONLY valid JSON with exactly these keys — no markdown, no preamble:\n"
    '  - "observatory_summary": the coach\'s output condensed for a website card '
    "(2-3 short paragraphs, ~150-200 words), written AS the coach in first person, "
    "never referring to the coach in third person.\n"
    '  - "key_recommendation": the single most actionable recommendation, as a '
    "standalone 1-2 sentence string.\n"
    '  - "elena_quote": one sentence in Elena Voss\'s literary-journalist voice about '
    "what the coach is NOT seeing, third person — or null if the narrative implies no "
    "such meta-observation.\n"
    '  - "public_summary": the coach\'s read rewritten for visitors to the public '
    "website (2 short paragraphs, ~120-180 words): first person for the coach, "
    "strictly THIRD person for the subject (his first name or 'he'/'his') — never "
    "'you'/'your', never a name-as-salutation, never an imperative aimed at him.\n\n" + SUMMARY_DAY_CORRESPONDENCE_RULE + "\n"
    "A sleep, recovery, HRV or resting-HR figure that does not say which night it "
    "belongs to cannot be checked by a reader or by the grounding gate — name the "
    "night or drop the figure. Dropping a figure is always allowed; inventing one is "
    "never allowed."
)


def prose_blob(extraction) -> str:
    """The gate's view of the record: ONLY the derived reader-bound prose, as TEXT.

    Plain text joined by blank lines rather than a JSON dump (the shape the digest and
    compression gates use) because this surface arms the #1968 night class, which
    splits on sentences — JSON punctuation would fuse and split them wrongly.

    Deliberately excluded: `themes`, `structural_fingerprint`, `predictions_made`,
    `threads_*`, `decision_classes_used`, `anti_pattern_violations`, `commitments_made`.
    Those are structured extraction metadata — tags, counts, enum labels and machine-
    checkable claim records with their own downstream validators (the measurable-metric
    allow-list, the prediction evaluator). Grading them as prose would flag a
    `paragraph_count` of 4 as a fabricated number, which is how a gate gets switched
    off.
    """
    extraction = extraction or {}
    parts = []
    for field in DERIVED_PROSE_FIELDS:
        value = extraction.get(field)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip())
    return "\n\n".join(parts)


def hold(extraction) -> dict:
    """The HOLD: null every derived condensation, keep the rest of the extraction.

    A copy — the caller's dict is not mutated. The whole set goes, not just the field
    whose sentence tripped the gate: the four are produced by ONE model call over one
    source, `grounding_findings` grades the joined text and reports a finding against a
    sentence rather than a field, and attributing it back by string-matching would be a
    guess. Holding the set is the same choice the ensemble digest makes when its gate
    survives a regen, and it is the safe direction — every read site falls back to
    `content`, the narrative that passed its own gate at generation time.

    Note what is NOT held: `content`, `themes`, the threads and the predictions. The
    coach's real output still ships and still feeds the state machine. This holds a
    condensation, never the lane.
    """
    held = dict(extraction or {})
    for field in DERIVED_PROSE_FIELDS:
        held[field] = None
    held["derived_prose_held"] = True
    return held


def recondense_message(coach_id, source_text, extraction, correction) -> str:
    """The user message for the ONE corrective regeneration."""
    return "\n".join(
        [
            f"## Coach: {coach_id}",
            "",
            "## The coach's full narrative (the only source of truth)",
            "---",
            str(source_text or ""),
            "---",
            "",
            "## The condensations that failed the grounding check",
            "---",
            prose_blob(extraction) or "(empty)",
            "---",
            "",
            str(correction or ""),
            "",
            "Rewrite all four fields. Return ONLY the JSON object.",
        ]
    )


def recondense(coach_id, source_text, extraction, correction, call_model) -> dict:
    """One corrective regeneration of the four fields; the rest of the record is kept.

    `call_model(system=..., user_message=..., max_tokens=..., temperature=...)` is the
    caller's own transport (ADR-062 routes it to Bedrock) — this module picks no model
    and owns no retry. A non-dict reply returns the extraction unchanged, which
    `regen_once` reads as "no improvement" and turns into a HOLD.
    """
    reply = call_model(
        system=RECONDENSE_SYSTEM_PROMPT,
        user_message=recondense_message(coach_id, source_text, extraction, correction),
        max_tokens=1500,
        temperature=0.1,
    )
    if not isinstance(reply, dict):
        return dict(extraction or {})
    candidate = dict(extraction or {})
    for field in DERIVED_PROSE_FIELDS:
        value = reply.get(field)
        candidate[field] = value.strip() if isinstance(value, str) else None
    return candidate


def served_summary(output_item, limit=200) -> str:
    """The reader-bound summary for one OUTPUT# row, with the HOLD fallback built in.

    The three serving paths that used this shape — `site_api_coach_profile`'s recent-
    outputs list, the Panel podcast's co-host material and the daily reflection's
    factual basis — ended their chain at `or ""`, so a held condensation left them with
    nothing at all: a coach silently dropped from the roster's summary, from the show
    and from the day's reflection. Ending it at the coach's own `content` instead is
    what makes the hold a DEGRADATION rather than a disappearance, and `content` is the
    text the generation-time gate already cleared.

    Truncated at a word boundary (#1224) because these three slots are card- and
    prompt-sized; the two paths that render the full analysis (`site_api_coach_narrative`
    and `coach_observatory_renderer`) keep their own untruncated `or content` fallback.
    """
    item = output_item or {}
    for field in SERVED_SUMMARY_PREFERENCE:
        value = item.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return truncate_at_word(str(item.get("content") or "").strip(), limit)
