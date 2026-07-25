"""
coach_diary_reaction.py — a coach reacts to a Video Diary / Solo Recording entry.

#1574 (epic #1564, absorbs #1388 AC2). When a Video Diary entry lands, the relevant
coach (routed by the entry's enriched themes — ``mind_coach`` default) writes ONE
short, grounded reaction that renders on the public lab-notes surface beside the
V3-consented context. Readers see the coaches responding to the human, not just the
sensors.

The four guarantees this module upholds (the story's acceptance criteria):

  1. ADR-104 GROUNDED, LEAK-PROOF. The generator is handed ONLY the leak-proof public
     context from ``diary_consent.public_context`` — the laundered public theme, the
     channel, the date, and (quote tier only) a single owner-cleared, substring-
     grounded verbatim line. The raw entry body never reaches the prompt. A private /
     unmarked entry yields no context → no reaction (returns None). The draft then
     passes the number-grounding allow-list gate (detection-only, so it never spends a
     second call).

  2. BUDGET-TIERED, ONE CALL MAX. Gated on the ``coach_diary_reaction`` reader-narrative
     feature (``budget_guard``) — paused at tier 2, in lockstep with the other reader
     narratives. Generation is exactly ONE Haiku/Sonnet call; there is no generation
     retry loop (``max_regenerations=0`` on the quality gate). The ADR-108 gate's own
     Haiku scoring call is shared coach infra, not a second generation call.

  3. RENDERS ON LAB-NOTES / ABSENT RENDERS NOTHING. A produced reaction is stored under
     ``USER#matthew#SOURCE#diary_reactions`` and served by ``/api/diary_reactions``;
     when generation returns None (private, paused, held, or infra failure) nothing is
     stored and nothing renders.

  4. ADR-108 QUALITY GATE. The draft ships through ``ai_calls._enforce_quality_gate`` —
     the same regenerate-or-hold path every coach narrative uses. A sub-threshold draft
     is HELD (returns None), never published.

DynamoDB:
  PK = USER#matthew#SOURCE#diary_reactions
  SK = DATE#{YYYY-MM-DD}#{channel}

Trigger (ops — wired at deploy, see PR): invoked per enriched Video Diary /
Solo Recording journal entry. Pure-importable; the AI/quality-gate/budget callables are
dependency-injected (lazy real defaults) so the unit suite runs with no live call.
"""

import os
from datetime import datetime, timezone

# Deterministic public-theme → coach routing. mind_coach owns Matthew's inner state
# and is the default for a diary entry (which is almost always about inner state);
# a body/health-dominant entry routes to the physical coach. This mirrors the
# deterministic COACH_DOMAINS config routing in coach_narrative_orchestrator (not
# inference). Keys are diary_consent.public_theme()'s 8-way vocabulary.
DIARY_THEME_COACH = {
    "anxiety_stress": "mind_coach",
    "relationships": "mind_coach",
    "personal_growth": "mind_coach",
    "reflection": "mind_coach",
    "gratitude": "mind_coach",
    "work_ambition": "mind_coach",
    "health_body": "physical_coach",
    "other": "mind_coach",
}
DEFAULT_COACH = "mind_coach"

# Display names — the same roster the site renders (coaching.js BOARD_PERSONAS).
COACH_NAMES = {
    "mind_coach": "Dr. Nathan Reeves",
    "physical_coach": "Dr. Victor Reyes",
    "sleep_coach": "Dr. Lisa Park",
    "nutrition_coach": "Dr. Marcus Webb",
    "training_coach": "Dr. Sarah Chen",
    "glucose_coach": "Dr. Amara Patel",
    "labs_coach": "Dr. James Okafor",
    "explorer_coach": "Dr. Henning Brandt",
}

USER_ID = os.environ.get("USER_ID", "matthew")
DIARY_REACTIONS_PK = f"USER#{USER_ID}#SOURCE#diary_reactions"

# The reader-narrative budget feature (registered in budget_guard._FEATURE_CUTOFF at
# cutoff 2 — pauses under tier 2, after all internal AI, before the irreducible reader
# promises).
BUDGET_FEATURE = "coach_diary_reaction"

_MAX_TOKENS = 220  # a SHORT reaction — a few sentences, not an essay


def route_coach(entry):
    """The coach that reacts to this entry — deterministic, from the public theme.
    Never inference; mind_coach is the default. Returns a coach_id."""
    from diary_consent import public_theme

    return DIARY_THEME_COACH.get(public_theme(entry), DEFAULT_COACH)


def _tone(entry):
    """A coarse machine tone label (like field_notes' ai_tone) — NOT journal content.
    Derived from the already-computed enriched sentiment; defaults to reflective."""
    s = str(entry.get("enriched_sentiment") or "").strip().lower()
    if s == "positive":
        return "affirming"
    if s == "negative":
        return "cautionary"
    return "reflective"


def build_reaction_prompt(coach_id, ctx):
    """(system, user) for the reaction call, built ONLY from the leak-proof public
    context. No raw journal text ever enters here — the sole verbatim string that can
    appear is ctx['quote'], which is present only for a grounded quote-tier entry."""
    coach_name = COACH_NAMES.get(coach_id, "The coach")
    channel = {"video_diary": "video diary", "solo_recording": "solo audio recording"}.get(ctx.get("channel"), "diary entry")
    theme = str(ctx.get("theme") or "other").replace("_", " ")

    system = (
        f"You are {coach_name} ({coach_id.replace('_', ' ')}), one of Matthew's AI coaches. "
        "Matthew just recorded a private diary entry and consented to a short PUBLIC reaction from you. "
        "Write 2-3 warm, specific sentences responding to HIM as a person — the coaches responding to the human, "
        "not to sensor data. This is the reader-facing lab-notes surface.\n\n"
        "HARD RULES:\n"
        "- You have NOT read the entry. You know only its theme (and, if given, one line he cleared for quoting).\n"
        "- NEVER invent, guess at, or imply the entry's specific contents, events, names, or feelings beyond the theme.\n"
        "- If a cleared quote is given you MAY quote it verbatim, once; otherwise quote nothing.\n"
        "- No numbers, no metrics, no data claims — this is a human response, not an analysis.\n"
        "- Speak in your own coaching voice. No preamble, no sign-off, no 'Dear Matthew'."
    )

    lines = [
        f"Matthew recorded a {channel}.",
        f"Its theme (the only thing you know about its content): {theme}.",
    ]
    if ctx.get("quote"):
        lines.append(f'The one line he cleared for you to quote, verbatim: "{ctx["quote"]}"')
    else:
        lines.append("He did NOT clear any line for quoting — paraphrase/allude at the theme level only, quote nothing.")
    lines.append("Write your short reaction now.")
    return system, "\n".join(lines)


def _default_generate_fn(system, user):
    from ai_calls import call_anthropic

    return call_anthropic(user, max_tokens=_MAX_TOKENS, system=system)


def _default_ground_fn(label, draft, allow_sources):
    """ADR-104 number allow-list gate in DETECTION-ONLY mode — a no-op regen so it
    never spends a second generation call (the reaction carries no numeric facts to
    correct; the real leak boundary is diary_consent). Fail-soft."""
    from ai_calls import _ground_legacy_output

    return _ground_legacy_output(label, draft, lambda _note: draft, *allow_sources)


def _default_quality_gate_fn(lambda_client, coach_id, text, brief):
    """ADR-108 regenerate-or-hold with max_regenerations=0 (hold, don't re-generate —
    honours the one-call-max AC). Returns (text|None, report)."""
    from ai_calls import _enforce_quality_gate

    return _enforce_quality_gate(lambda_client, coach_id, text, brief, lambda _note: text, max_regenerations=0)


def _is_unavailable(text):
    return not text or not str(text).strip() or "[AI_UNAVAILABLE]" in str(text)


def generate_diary_reaction(
    entry,
    *,
    lambda_client=None,
    budget_allow=None,
    generate_fn=None,
    ground_fn=None,
    quality_gate_fn=None,
    now_fn=None,
):
    """Produce the coach reaction dict for a journal entry, or None.

    None (⇒ nothing stored, nothing rendered) when: budget-paused, the entry is
    private/unmarked (no public context), the generation call fails, or the ADR-108
    quality gate HELD the draft. Exactly one generation call is made on the happy path.
    """
    allow = budget_allow or _default_budget_allow
    if not allow(BUDGET_FEATURE):
        return None

    from diary_consent import public_context

    ctx = public_context(entry)
    if ctx is None:
        return None  # private / unmarked — nothing crosses to the public reaction

    coach_id = route_coach(entry)
    system, user = build_reaction_prompt(coach_id, ctx)

    gen = generate_fn or _default_generate_fn
    draft = gen(system, user)
    if _is_unavailable(draft):
        return None
    draft = str(draft).strip()

    ground = ground_fn or _default_ground_fn
    try:
        draft = str(ground(f"diary_reaction:{coach_id}", draft, (system, user))).strip()
    except Exception:  # noqa: BLE001 — grounding is fail-soft, never blocks
        pass
    if not draft:
        return None

    # ADR-108: the same quality gate every coach narrative passes through. A
    # generation brief carrying the decision-class ceiling (observational — a human
    # reaction never prescribes) so the gate can enforce it.
    brief = {"decision_class_ceiling": "observational", "guardrails": {"surface": "diary_reaction", "theme": ctx["theme"]}}
    gate = quality_gate_fn or _default_quality_gate_fn
    final, _report = gate(lambda_client, coach_id, draft, brief)
    if final is None or not str(final).strip():
        return None  # held by the quality gate — do not publish

    now = (now_fn or (lambda: datetime.now(timezone.utc).isoformat()))()
    reaction = {
        "coach_id": coach_id,
        "coach_name": COACH_NAMES.get(coach_id, "The coach"),
        "reaction": str(final).strip(),
        "tone": _tone(entry),
        "theme": ctx["theme"],
        "channel": ctx["channel"],
        "tier": ctx["tier"],
        "entry_date": ctx.get("date"),
        "generated_at": now,
    }
    if ctx.get("quote"):
        reaction["quote"] = ctx["quote"]
    return reaction


def _default_budget_allow(feature):
    import budget_guard

    return budget_guard.allow(feature)


def store_reaction(reaction, table_=None):
    """Persist a produced reaction. Phase-tagged (ADR-058) so a wiped cycle's
    reactions are hidden by the serve query. Returns the SK written."""
    if not reaction or not reaction.get("entry_date"):
        return None
    if table_ is None:
        import boto3

        table_ = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
            os.environ.get("TABLE_NAME", "life-platform")
        )
    try:
        from constants import EXPERIMENT_PHASE_CURRENT

        phase = EXPERIMENT_PHASE_CURRENT
    except Exception:  # noqa: BLE001
        phase = "current"

    sk = f"DATE#{reaction['entry_date']}#{reaction.get('channel', 'video_diary')}"
    item = {"pk": DIARY_REACTIONS_PK, "sk": sk, "phase": phase, **reaction}
    table_.put_item(Item=item)
    return sk


def lambda_handler(event, context=None):
    """Generate + store the reaction for one journal entry.

    Event: ``{"entry": {...}}`` — the enriched journal item (must carry raw_text,
    enriched_themes/dominant_theme, the public_reaction_consent marker, date, channel).
    Returns ``{"stored": bool, "coach_id": ..., "sk": ...}``.
    """
    import boto3

    entry = (event or {}).get("entry") or {}
    reaction = generate_diary_reaction(entry, lambda_client=boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-west-2")))
    if not reaction:
        return {"stored": False, "reason": "no_reaction"}
    sk = store_reaction(reaction)
    return {"stored": bool(sk), "coach_id": reaction["coach_id"], "sk": sk}
