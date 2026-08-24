"""
integrator_prompts.py — the board lead's narrative prompt builders, extracted
from ai_expert_analyzer_lambda (#1115, ADR-080 size gate).

WHO SIGNS THESE (#1986). The integrator voice used to be hardcoded as "Dr. Kai
Nakamura, Integrative Health Director" while the public roster billed Dr. Eli
Marsh as the lead — two characters in one role, and a reader could not tell who
ran the board. The name is now DERIVED from the persona registry's single
``lead: true`` persona (config/personas.json → coach.persona_registry), so the
prompt, the API byline and the static noscript cannot drift apart again.

Three cross-domain narrative prompts, one per timeframe altitude:

  build_synthesis_prompt     — the WEEKLY priority + cross-domain notes
                               (EXPERT#integrator, the Week lens's call)
  build_month_rollup_prompt  — the MONTH rollup: the trailing ~4 lab-note weeks
                               as one pattern (EXPERT#integrator_month, #1115)
  build_arc_prompt           — the JOURNEY rollup: the whole run's arc
                               (EXPERT#experiment_arc, the Experiment lens)

Each is a PURE builder (strings in → prompt out) so the #1086 phase-context
coverage suite can drive it offline, and each carries the mandatory
experiment-phase grounding block via _phase_context_block() — a narrative
prompt that doesn't know what day/phase it is cannot ship (ADR-104, #1138).

#3018: `build_synthesis_prompt` now also asks for `public_summary` — the
integrator's weekly call rewritten for site VISITORS (third person for
Matthew, never addressed) — mirroring `coach_extraction_prompt`'s task 12.
`weekly_priority` stays the owner-directed channel; `ai_expert_analyzer_lambda`
grounds and writes both, guarded at write by `coach.audience_guard.reader_safe`
and served at `site_api_coach_stance._integrator_digest`, the ONE public
chokepoint (#2972's shape, pointed at the producer #2972 didn't reach).
"""

import logging

logger = logging.getLogger(__name__)


def _lead():
    """(name, surname, title) of the registry's board lead (#1986).

    Fail-soft to the registry's own pinned fallback constants — a narrative prompt
    must never open with an empty byline or a persona id. The fallback is asserted
    equal to config/personas.json by tests/test_board_lead_single_character.py.
    """
    try:
        from coach import persona_registry

        name, title = persona_registry.lead_byline()
    except Exception as e:  # noqa: BLE001 — a byline lookup must never block generation
        logger.warning("lead byline unavailable, using pinned fallback (non-blocking): %s", e)
        name, title = "Dr. Eli Marsh", "Principal Investigator — Program Lead"
    return name, name.split()[-1], title


def _phase_context_block():
    """#1086/#1115: the ONE mandatory experiment-phase grounding block for every
    narrative prompt this module builds. No-arg build reads EXPERIMENT_START_DATE
    + today (PT). Fail-soft to "" only on an import/runtime error — the bundle
    always ships ai_context, and tests pin the block's presence in every prompt."""
    try:
        from ai.ai_context import build_experiment_phase_context, format_experiment_phase_context

        return format_experiment_phase_context(build_experiment_phase_context())
    except Exception as e:  # noqa: BLE001 — grounding must never hard-fail generation
        logger.warning("phase-context block unavailable (non-blocking): %s", e)
        return ""


def build_synthesis_prompt(coach_sections, goals_json, facts_block, presence_block):
    """The integrator (weekly-priority) prompt — extracted pure so the #1086
    phase-context coverage suite can drive it offline (#1115)."""
    phase_block = _phase_context_block()
    lead_name, lead_surname, lead_title = _lead()
    return f"""You are {lead_name}, {lead_title}. You've just read assessments from all domain coaches. Your job: synthesize, resolve contradictions, and make ONE call.

Matthew's goals: {goals_json}
{phase_block}
{facts_block}{presence_block}
Coach assessments:
{coach_sections}

Write in first person. You are {lead_surname} — direct, decisive, and on Matthew's side.

HOW TO JUDGE THE WEEK (read this before you write):
- Judge progress against where Matthew STARTED, not only against the end goal. He is early in a long experiment; "not at the goal yet" is NOT failure. Distance-to-goal is context, never the verdict.
- Start from what actually happened. Before you name a problem, account for what he DID this week — the workouts, the walks, the logged meals, the habits checked off. Credit the real wins first. A coach who only sees what's missing isn't reading the data, he's projecting onto it.
- Be honest about genuine problems, but calibrate the tone: direct and warm, never catastrophizing. NO clinical doom labels ("behavioral arrest", "he's avoiding himself"), no diagnosing his character from one thin week. Describe behavior and numbers, not pathology.
- Effort and consistency are the wins worth reinforcing at this stage, even when the scale or a lab hasn't moved yet. Lagging outcomes are expected to lag — don't read a slow-moving number as a behavioral failure.

Produce EXACTLY this JSON structure (no markdown, no explanation):
{{
  "weekly_priority": "One paragraph. Open by crediting what Matthew actually did well this week (be specific, drawn from the data). Then name the ONE thing that matters most NEXT — framed as the next step forward from where he is, not a scolding about the gap to the goal. One concrete action. If coaches disagree, make the call and say why. Decisive but encouraging — the voice of a coach who saw the real effort this week.",
  "public_summary": "The same weekly call, rewritten for VISITORS to the public website — an audience reading ABOUT Matthew's experiment, not Matthew himself (2 short paragraphs, ~120-180 words). Speak AS {lead_surname} in first person ('I'm watching…'), but refer to Matthew strictly in the THIRD person — by his first name or 'he'/'his'. NEVER address him: no 'you'/'your', no name-as-salutation ('Matthew — …'), no imperatives aimed at him. Open with what he did well this week, then the one thing that matters most next — reported ('I've asked him to…'), never commanded. Keep the most important data point. This is the ONLY field served to site visitors; weekly_priority speaks to Matthew directly and is never shown to them.",
  "cross_domain_notes": {{
    "sleep": "1-2 sentences connecting sleep to the other domains this week",
    "nutrition": "1-2 sentences connecting nutrition to the other domains",
    "training": "1-2 sentences connecting training to the other domains",
    "glucose": "1-2 sentences connecting glucose to the other domains",
    "physical": "1-2 sentences connecting physical/body comp to the other domains",
    "mind": "1-2 sentences connecting mind/behavioral to the other domains"
  }},
  "disagreements": [
    {{
      "topic": "what the disagreement is about",
      "coaches": ["coach_a", "coach_b"],
      "position_a": "what coach A recommends",
      "position_b": "what coach B recommends",
      "lead_call": "your resolution — who is right and why"
    }}
  ]
}}

For disagreements: only flag GENUINE conflicts where two coaches would give Matthew contradictory advice. Do not invent disagreements. Empty list is fine if all coaches are aligned."""


def build_month_rollup_prompt(weeks_text, goals_json, facts_block, n_weeks, window_label):
    """#1115: the integrator's MONTH-altitude rollup prompt — the trailing ~4 weeks
    as one pattern, sitting between the weekly priority (week lens) and the
    experiment arc (journey lens)."""
    phase_block = _phase_context_block()
    lead_name, lead_surname, lead_title = _lead()
    return f"""You are {lead_name}, {lead_title}. You've read the board's weekly lab notes for the past month{f" ({window_label})" if window_label else ""}. Your job: name the MONTH'S pattern — not this week's call (that exists separately), not the whole experiment's arc (that exists separately) — the shape of the last ~{n_weeks} weeks taken together.

Matthew's goals: {goals_json}
{phase_block}
{facts_block}
The board's read, week by week (oldest first, most recent last):
{weeks_text}

Write in first person as {lead_surname} — direct, warm, on Matthew's side.

HOW TO READ THE MONTH (read before writing):
- Speak at MONTH altitude: recurring patterns, trends across the weeks, what compounded and what stalled. Do NOT restate any single week's priority sentence — a reader sees the weekly call elsewhere; give them what only a month of distance shows.
- Judge against where Matthew STARTED, not the end goal. Lagging outcomes are expected to lag; a slow-moving number is not a behavioral failure.
- Only {n_weeks} weeks of notes exist in this window; do not pretend to more history than the notes contain.
- BEHAVIORAL PRESENCE lines are deterministic counts from the raw logs — AUTHORITATIVE, and they override any rosier read in a week's notes. Absence weeks are narrated AS absence, never as progress; rest-inflated recovery during an absence week is never credited.

Produce EXACTLY this JSON (no markdown, no preamble):
{{
  "narrative": "1-2 short paragraphs. The month's pattern — what the weeks add up to, what recurred, what changed across them, where the month leaves things. Specific, drawn from the weekly notes, month-altitude only.",
  "headline": "4-10 words naming what this month was"
}}"""


def build_arc_prompt(weeks_text, goals_json, facts_block, n_weeks):
    """The journey-rollup (experiment-arc) prompt — extracted pure so the #1086
    phase-context coverage suite can drive it offline (#1115)."""
    phase_block = _phase_context_block()
    lead_name, lead_surname, lead_title = _lead()
    return f"""You are {lead_name}, {lead_title}. You've read the board's weekly lab notes across Matthew's entire experiment so far. Your job: step back and tell the ARC — not this week, but the whole trajectory.

Matthew's goals: {goals_json}
{phase_block}
{facts_block}
The board's read, week by week (oldest first):
{weeks_text}

Write in first person as {lead_surname} — direct, warm, on Matthew's side.

HOW TO JUDGE THE ARC (read before writing):
- Judge the trajectory against where Matthew STARTED, not the end goal. He is early in a long experiment; a slow-moving outcome is expected to lag and is NOT failure.
- Tell the real story: where this began, what shifted, what held steady, where it stands now. Name the turning points honestly but never catastrophize and never diagnose his character from thin data.
- Credit the throughline of effort and consistency. If the weeks rhymed (the same pattern recurring), say so plainly — that's the signal.
- Only {n_weeks} weeks exist; do not pretend to more history than the notes contain.
- BEHAVIORAL PRESENCE lines are deterministic counts from the raw logs — they are AUTHORITATIVE and override any rosier read in that week's notes. A week whose counts are zero (or near-zero) is an ABSENCE week: narrate it AS absence — the logging stopped, and that is the week's story — never as progress or triumph. Recovery/HRV that looks good during an absence week is REST-INFLATED (no training, no logged deficit behind it) and must NOT be credited as progress or "the best of the arc". Never call a fully-dark week's missing data "a minor logging problem".

Produce EXACTLY this JSON (no markdown, no preamble):
{{
  "arc": "2-3 short paragraphs. The trajectory of the experiment to date — the start, the turns, the throughline, where it stands now. Specific, drawn from the weekly notes. The voice of a coach who has watched the whole run.",
  "throughline": "One sentence — the single sentence that names what this experiment has actually been about so far.",
  "chapters": [
    {{ "week_label": "the week's label exactly as given", "headline": "4-8 words naming what that week was, in the arc" }}
  ]
}}

For chapters: one entry per week given, in order. The headline is the chapter title that week earns in the larger story."""


def gate_json_record(label, parsed, key, partial, prompt, api_key, *, gate_prose, lenient_json):
    """#2421: gate the reader-bound field(s) of a JSON-shaped generator (the weekly-
    priority synthesis, the experiment arc, the month rollup). A rewrite comes back as
    raw JSON, so the extractor re-parses it and keeps the WHOLE rewritten record —
    publishing a corrected headline beside the uncorrected chapters/notes it was
    generated with would be the post-gate-mutation bug in another costume. Returns the
    grounded record, or None to hold (the caller's prior cached record keeps serving).

    Extracted out of `ai_expert_analyzer_lambda.py` (#3018, the #1665 size ratchet —
    the module sat at its baselined ceiling) — the same #2604/#2610 earned-headroom
    shape as every other split in this tree. `gate_prose`/`lenient_json` are the
    caller's own grounding transport (that module's `_gate_prose`/`_lenient_json`);
    this module picks no model and owns no retry, the `coach_derived_prose.recondense`
    posture pointed at a different caller's `call_model`.

    `key` is normally one field name. #3018 lets it be a tuple — the weekly-priority
    synthesis's `public_summary` is produced by the SAME model call as `weekly_priority`,
    so the two are graded as one joined text: the `coach_derived_prose.DERIVED_PROSE_FIELDS`
    "guard the SET, not the instance" idiom, mirrored at this producer. Only the FIRST key
    is required for a regen to count as usable — the others are graded when present but
    never block an otherwise-clean primary field, so a rewrite that drops a secondary key
    still publishes (that key just comes back empty, the honest degradation)."""
    keys = key if isinstance(key, tuple) else (key,)
    fresh: dict = {}

    def _extract(_raw):
        _p = lenient_json(_raw, keys[0], partial)
        if _p and _p.get(keys[0]):
            fresh["parsed"] = _p
            return "\n\n".join(str(_p.get(k) or "") for k in keys)
        return ""

    joined = "\n\n".join(str(parsed.get(k) or "") for k in keys)
    text = gate_prose(label, joined, prompt, api_key, extract=_extract)
    if not text:
        logger.warning("%s HELD by the grounding gate (#2421/#2391) — prior cached record keeps serving", label)
        return None
    out = fresh.get("parsed", parsed)
    if len(keys) == 1:
        # #2421's original shape: for the single-key callers (experiment arc, month
        # rollup) the grounded text IS the field — set directly (a no-op when `out`
        # already carries it from `fresh["parsed"]`, load-bearing when it doesn't).
        out[keys[0]] = text
    return out
