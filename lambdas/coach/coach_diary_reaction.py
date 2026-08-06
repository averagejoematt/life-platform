"""
coach_diary_reaction.py — a coach reacts to something Matthew said, in his own words.

#1574 (epic #1564, absorbs #1388 AC2). When a Video Diary entry lands, the relevant
coach (routed by the entry's enriched themes — ``mind_coach`` default) writes ONE
short, grounded reaction that renders on the public lab-notes surface beside the
V3-consented context. Readers see the coaches responding to the human, not just the
sensors.

#1675 (epic #1668, The Social Membrane) extends the SAME mechanism to the social
channel — the story's first acceptance criterion is explicitly "no parallel reaction
machinery". One producer, one storage partition, one endpoint, one render surface; what
varies per channel is exactly three things, each dispatched on ``reaction_kind(entry)``:

  ============  ==============================  ==============================
  kind          the permission gate             the routing signal
  ============  ==============================  ==============================
  ``diary``     ``privacy.diary_consent`` —     the laundered public theme
                private by default, the owner   (``DIARY_THEME_COACH``)
                must opt an entry in
  ``social``    ``privacy.social_consent`` —    the enricher's own deterministic
                already public; the S2 origin   ``enriched_coach_route``
                membrane + the S5 sensitivity   (``social_signals``)
                gate must both clear it
  ============  ==============================  ==============================

Everything downstream of the context — the prompt frame, the single generation call, the
ADR-104 grounding gate, the ADR-108 quality gate, the phase/cycle stamp, the sk, the
serve query and the lab-notes render — is shared verbatim between the two channels.

The four guarantees this module upholds (the story's acceptance criteria):

  1. ADR-104 GROUNDED, LEAK-PROOF. The generator is handed ONLY the leak-proof public
     context from the channel's gate — the laundered public theme, the channel, the
     date, and (quote tier only) a single substring-grounded verbatim line: for a diary
     the line the owner explicitly cleared, for a social post a deterministically
     selected line of the post's OWN already-public text. The raw entry body never
     reaches the prompt. A blocked entry yields no context → no reaction (returns None).
     The draft then passes the number-grounding allow-list gate (detection-only, so it
     never spends a second call).

  2. BUDGET-TIERED, ONE CALL MAX. Gated on the reader-narrative feature for the channel
     (``budget_guard``: ``coach_diary_reaction`` / ``coach_social_reaction``) — both at
     cutoff 2, in lockstep with the other reader narratives (ADR-125 band 2: a reaction
     is reader-facing narrative, so it outlives every internal/dev AI feature and pauses
     before the two irreducible reader promises). Two feature names, one band, so the
     per-channel Bedrock cost is separately observable at the chokepoint. Generation is
     exactly ONE Haiku/Sonnet call; there is no generation retry loop
     (``max_regenerations=0`` on the quality gate). The ADR-108 gate's own Haiku scoring
     call is shared coach infra, not a second generation call.

  3. RENDERS ON LAB-NOTES / ABSENT RENDERS NOTHING. A produced reaction — diary or
     social — is stored under ``USER#matthew#SOURCE#diary_reactions`` and served by
     ``/api/diary_reactions``; when generation returns None (blocked, paused, held, or
     infra failure) nothing is stored and nothing renders.

  4. ADR-108 QUALITY GATE. The draft ships through ``ai_calls._enforce_quality_gate`` —
     the same regenerate-or-hold path every coach narrative uses. A sub-threshold draft
     is HELD (returns None), never published.

DynamoDB (ONE partition for both channels — so the phase-taxonomy registration, the
restart wipe, the serve query and the render surface are all shared, not duplicated):
  PK = USER#matthew#SOURCE#diary_reactions
  SK = DATE#{YYYY-MM-DD}#{channel}#{entry_uid}

  #1756: the entry_uid segment is the fix for a same-day sk collision — the original
  two-segment key meant a SECOND Video Diary on the same day overwrote the first
  entry's reaction. The uid is the SAME stable per-page suffix the journal sk uses
  (notion_lambda.build_sk / #476-E-6: the last 12 hex of the Notion page id), so the
  reaction key is per-ENTRY, idempotent, and re-derivable without a lookup. A legacy
  entry that carries neither a page id nor a stable sk suffix still writes the
  two-segment key (unchanged behaviour, and nothing else can claim it).

  #1675: a social post's uid is its ``post_id`` (the same id its own sk suffix carries,
  #1669), sanitised to the sk-safe alphabet — so two posts on the same channel on the
  same day keep separate rows, exactly as two same-day diaries do. The ``channel``
  segment is the platform name (``youtube`` …), which also keeps a social reaction from
  ever colliding with a diary reaction.

Trigger: ``maybe_react(entry)`` is called inline per enriched record, from that
channel's OWN enrichment pass — ``ingestion/journal_enrichment_lambda`` for the diary
(#1756) and ``ingestion/social_enrichment_lambda`` for social (#1675). Option A in both
cases: no second pipeline, no new Lambda, no schedule (the 4th-channel principle), and
the enrichment pass is the only place the enriched signals this routes on exist. It is
fail-open by contract: a reaction failure never fails enrichment. ``lambda_handler``
remains for a manual/backfill invoke of one entry or post.

Pure-importable; the AI/quality-gate/budget callables are dependency-injected (lazy real
defaults) so the unit suite runs with no live call.
"""

import os
import re
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

# The reader-narrative budget features (both registered in budget_guard._FEATURE_CUTOFF
# at cutoff 2 — they pause under tier 2, after all internal AI, before the irreducible
# reader promises). Two names, one ADR-125 band: the band is an AUDIENCE decision and
# both surfaces face the same audience, but separate names keep the per-channel Bedrock
# cost separately observable at the bedrock_client chokepoint.
BUDGET_FEATURE = "coach_diary_reaction"
SOCIAL_BUDGET_FEATURE = "coach_social_reaction"

_MAX_TOKENS = 220  # a SHORT reaction — a few sentences, not an essay

# #1756: the ONLY journal channels a reaction is produced for. A typed journal entry
# (channel="journal") is never a diary, so it never reaches the consent gate — the
# reaction surface is "the coaches responding to a RECORDING", by definition.
DIARY_CHANNELS = ("video_diary", "solo_recording")

# #1675: the two reaction kinds. `reaction_kind()` is the ONE dispatcher — the gate, the
# routing signal, the prompt frame and the budget feature all key off its answer.
KIND_DIARY = "diary"
KIND_SOCIAL = "social"

# social_signals' two deterministic routes → the coach that owns each. The enricher
# already computed and persisted this route per post (`enriched_coach_route`), so the
# reaction reuses the channel's OWN router rather than inventing a second one.
SOCIAL_ROUTE_COACH = {"training": "training_coach", "mind": "mind_coach"}

# The #476/E-6 stable per-page sk suffix: last 12 hex of the de-hyphenated Notion page id.
_STABLE_SUFFIX_RE = re.compile(r"^[0-9a-f]{12}$")
# Everything outside the DDB-sk-safe alphabet is dropped from a social post id.
_UID_UNSAFE_RE = re.compile(r"[^0-9A-Za-z_-]+")
_MAX_SOCIAL_UID = 48


def reaction_kind(entry):
    """Which reaction channel this record belongs to — ``diary``, ``social``, or None.

    Structural, never a hand-maintained channel allow-list on the social side: a social
    post record is exactly the thing #1669's ingestion transform stamps with a
    ``post_id``, so a new inbound source (#1676/#1677 — Bluesky, Mastodon, X …) is
    reactable the day it lands, with no edit here. ``None`` ⇒ not a reaction surface at
    all (an ordinary typed journal entry, a metrics row), and the trigger stops free.
    """
    entry = entry or {}
    if str(entry.get("channel") or "").strip().lower() in DIARY_CHANNELS:
        return KIND_DIARY
    if str(entry.get("post_id") or "").strip():
        return KIND_SOCIAL
    return None


def entry_uid(entry):
    """The stable per-entry id used to key this record's reaction (#1756/#1675), or "".

    Prefers the Notion page id (canonical — it is exactly what notion_lambda.build_sk
    derives the journal sk's stable suffix from), then a social post's own ``post_id``
    (#1675 — the same id its record's sk suffix carries), and falls back to the stable
    sk suffix when the sk is present but neither id is. Anything that doesn't look like
    the stable 12-hex suffix is rejected rather than guessed at, so a single-per-day
    template sk (…#journal#morning) can never be mistaken for an entry id.
    """
    page_id = str(entry.get("notion_page_id") or "").replace("-", "").strip().lower()
    if len(page_id) >= 12 and _STABLE_SUFFIX_RE.match(page_id[-12:]):
        return page_id[-12:]
    post_id = _UID_UNSAFE_RE.sub("", str(entry.get("post_id") or "").strip())[:_MAX_SOCIAL_UID]
    if post_id:
        return post_id
    tail = str(entry.get("sk") or "").rsplit("#", 1)[-1].strip().lower()
    return tail if _STABLE_SUFFIX_RE.match(tail) else ""


def reaction_sk(entry_date, channel=None, uid=""):
    """The reaction's sort key. Per-ENTRY when a uid is known (#1756 — two diaries on
    the same day+channel no longer overwrite each other); the legacy two-segment form
    only when no stable entry id exists at all."""
    base = f"DATE#{entry_date}#{channel or 'video_diary'}"
    return f"{base}#{uid}" if uid else base


def route_coach(entry, kind=None):
    """The coach that reacts to this record — deterministic, never inference.

    Each channel routes on the signal its own enrichment pass already produced:
      * diary  — the laundered public theme (``DIARY_THEME_COACH``);
      * social — the enricher's persisted ``enriched_coach_route`` (``social_signals``),
        falling through to that module's live classifier for a legacy/unstamped record.
    ``mind_coach`` is the default on both sides. Returns a coach_id.
    """
    if (kind or reaction_kind(entry)) == KIND_SOCIAL:
        from content.social_signals import coach_route_of

        return SOCIAL_ROUTE_COACH.get(coach_route_of(entry), DEFAULT_COACH)

    from privacy.diary_consent import public_theme

    return DIARY_THEME_COACH.get(public_theme(entry), DEFAULT_COACH)


def public_context_for(entry, kind=None):
    """The channel's leak-proof public context for this record, or ``None``.

    THE gate dispatch: a diary entry goes through ``diary_consent`` (private by default,
    the owner must opt in); a social post goes through ``social_consent`` (already
    public, but the S2 origin membrane + the S5 sensitivity gate must both clear it).
    Both return the same context shape, so everything downstream is channel-agnostic.
    """
    kind = kind or reaction_kind(entry)
    if kind == KIND_SOCIAL:
        from privacy.social_consent import public_context as social_public_context

        return social_public_context(entry)
    if kind == KIND_DIARY:
        from privacy.diary_consent import public_context

        ctx = public_context(entry)
        if ctx is not None:
            ctx.setdefault("kind", KIND_DIARY)
        return ctx
    return None


def budget_feature(kind):
    """The budget_guard feature name for a channel — both at ADR-125 cutoff 2."""
    return SOCIAL_BUDGET_FEATURE if kind == KIND_SOCIAL else BUDGET_FEATURE


def _tone(entry):
    """A coarse machine tone label (like field_notes' ai_tone) — NOT journal content.
    Derived from the already-computed enriched sentiment; defaults to reflective."""
    s = str(entry.get("enriched_sentiment") or "").strip().lower()
    if s == "positive":
        return "affirming"
    if s == "negative":
        return "cautionary"
    return "reflective"


def _build_social_prompt(coach_id, ctx):
    """(system, user) for a reaction to a PUBLIC social post (#1675).

    The frame is the inverse of the diary's: nothing here is private, so the coach may
    be handed the post's own cleared line — but it is still handed NOTHING ELSE. No
    engagement numbers, no metrics, no other posts, no enrichment internals. A coach
    that was never given a number cannot cite one (ADR-104, structurally).
    """
    coach_name = COACH_NAMES.get(coach_id, "The coach")
    channel = str(ctx.get("channel") or "social").replace("_", " ")
    theme = str(ctx.get("theme") or "other").replace("_", " ")

    system = (
        f"You are {coach_name} ({coach_id.replace('_', ' ')}), one of Matthew's AI coaches. "
        f"Matthew just posted publicly on {channel} — his own public voice, in his own words. "
        "Write 2-3 warm, specific sentences responding to HIM as a person — the coaches responding to the human, "
        "not to sensor data. This renders publicly beside his post.\n\n"
        "HARD RULES:\n"
        "- You know ONLY what is given below: the post's theme, and (if given) one line of the post itself.\n"
        "- NEVER invent, guess at, or imply anything else about the post, the day, or what he did.\n"
        "- Do NOT congratulate him on reach, views, likes, or engagement — you have not seen any, and they are not the point.\n"
        "- If a line of the post is given you MAY quote it verbatim, once; otherwise quote nothing.\n"
        "- No numbers, no metrics, no data claims — this is a human response, not an analysis.\n"
        "- Speak in your own coaching voice. No preamble, no sign-off, no 'Dear Matthew'."
    )

    lines = [
        f"Matthew posted publicly on {channel}.",
        f"Its theme (the only thing you know about its subject): {theme}.",
    ]
    if ctx.get("quote"):
        lines.append(f'One line from the post, verbatim — you may quote it: "{ctx["quote"]}"')
    else:
        lines.append("No line of the post is available to you — respond at the theme level only, quote nothing.")
    lines.append("Write your short reaction now.")
    return system, "\n".join(lines)


def build_reaction_prompt(coach_id, ctx):
    """(system, user) for the reaction call, built ONLY from the leak-proof public
    context. No raw journal text ever enters here — the sole verbatim string that can
    appear is ctx['quote'], which is present only for a grounded quote-tier entry (for
    a diary, the line the owner cleared; for a social post, a line of his own already-
    public words). Dispatches on the context's kind (#1675)."""
    if ctx.get("kind") == KIND_SOCIAL:
        return _build_social_prompt(coach_id, ctx)

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
    from ai.ai_calls import call_anthropic

    return call_anthropic(user, max_tokens=_MAX_TOKENS, system=system)


def _default_ground_fn(label, draft, allow_sources):
    """ADR-104 number allow-list gate in DETECTION-ONLY mode — a no-op regen so it
    never spends a second generation call (the reaction carries no numeric facts to
    correct; the real leak boundary is diary_consent). Fail-soft."""
    from ai.ai_calls import _ground_legacy_output

    return _ground_legacy_output(label, draft, lambda _note: draft, *allow_sources)


def _default_quality_gate_fn(lambda_client, coach_id, text, brief):
    """ADR-108 regenerate-or-hold with max_regenerations=0 (hold, don't re-generate —
    honours the one-call-max AC). Returns (text|None, report)."""
    from ai.ai_calls import _enforce_quality_gate

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
    """Produce the coach reaction dict for a diary entry OR a social post, or None.

    None (⇒ nothing stored, nothing rendered) when: budget-paused, the record's channel
    gate blocks it (a private/unmarked diary entry; a platform-origin or un-cleared
    social post), the generation call fails, or the ADR-108 quality gate HELD the draft.
    Exactly one generation call is made on the happy path, on either channel.
    """
    kind = reaction_kind(entry)
    allow = budget_allow or _default_budget_allow
    if not allow(budget_feature(kind)):
        return None

    ctx = public_context_for(entry, kind)
    if ctx is None:
        return None  # gated — nothing crosses to the public reaction

    coach_id = route_coach(entry, kind)
    system, user = build_reaction_prompt(coach_id, ctx)

    gen = generate_fn or _default_generate_fn
    draft = gen(system, user)
    if _is_unavailable(draft):
        return None
    draft = str(draft).strip()

    ground = ground_fn or _default_ground_fn
    try:
        draft = str(ground(f"{kind or 'diary'}_reaction:{coach_id}", draft, (system, user))).strip()
    except Exception:  # noqa: BLE001 — grounding is fail-soft, never blocks
        pass
    if not draft:
        return None

    # ADR-108: the same quality gate every coach narrative passes through. A
    # generation brief carrying the decision-class ceiling (observational — a human
    # reaction never prescribes) so the gate can enforce it.
    brief = {
        "decision_class_ceiling": "observational",
        "guardrails": {"surface": f"{kind or KIND_DIARY}_reaction", "theme": ctx["theme"]},
    }
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
        # #1675: which channel Matthew's half of the exchange came from. The render
        # surface needs it to frame the human voice (a private recording he cleared vs.
        # a post he published); it is NOT the platform name — that stays `channel`.
        "kind": ctx.get("kind", KIND_DIARY),
        "entry_date": ctx.get("date"),
        "generated_at": now,
    }
    uid = entry_uid(entry)
    if uid:
        reaction["entry_uid"] = uid  # #1756: per-entry sk segment (same-day collision fix)
    if ctx.get("quote"):
        reaction["quote"] = ctx["quote"]
    if ctx.get("url"):
        # Social only: the public post's own URL — the "he posted" half of the loop is a
        # real link, not a claim. Already https-validated by the channel's gate.
        reaction["post_url"] = ctx["url"]
    return reaction


def _default_budget_allow(feature):
    from ai import budget_guard

    return budget_guard.allow(feature)


def _table():
    import boto3

    return boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-west-2")).Table(
        os.environ.get("TABLE_NAME", "life-platform")
    )


def _stamp():
    """The ADR-058/#1233 write-time provenance stamp (phase + cycle), fail-soft.
    A missing stamp must never block the write, so this degrades to phase-only."""
    try:
        from experiment.phase_taxonomy import experiment_stamp

        stamp = experiment_stamp()
        if stamp.get("phase"):
            return stamp
    except Exception:  # noqa: BLE001 — provenance never breaks a write
        pass
    try:
        from common.constants import EXPERIMENT_PHASE_CURRENT

        return {"phase": EXPERIMENT_PHASE_CURRENT}
    except Exception:  # noqa: BLE001
        return {"phase": "current"}


def store_reaction(reaction, table_=None):
    """Persist a produced reaction. Phase-tagged + cycle-stamped (ADR-058/#1233) so a
    wiped cycle's reactions are hidden by the serve query and each row names its own
    reset generation. Returns the SK written."""
    if not reaction or not reaction.get("entry_date"):
        return None
    if table_ is None:
        table_ = _table()

    sk = reaction_sk(reaction["entry_date"], reaction.get("channel"), reaction.get("entry_uid", ""))
    item = {"pk": DIARY_REACTIONS_PK, "sk": sk, **_stamp(), **reaction}
    table_.put_item(Item=item)
    return sk


def reaction_exists(entry, table_=None):
    """True when this entry already has a stored reaction (#1756 idempotency).

    Keyed on the SAME per-entry sk the writer builds, so a re-enrichment pass (the
    Sunday 30-day sweep, a schema bump, a Notion edit) never spends a second Bedrock
    call on an entry that has already been reacted to. Fail-soft to False — an
    unreadable table must not silently suppress a legitimate first reaction; the
    put_item that follows is idempotent on the same key anyway.
    """
    date = entry.get("date") or entry.get("entry_date")
    if not date:
        return False
    if table_ is None:
        table_ = _table()
    sk = reaction_sk(date, entry.get("channel"), entry_uid(entry))
    try:
        return bool(table_.get_item(Key={"pk": DIARY_REACTIONS_PK, "sk": sk}).get("Item"))
    except Exception:  # noqa: BLE001
        return False


def _blocked_reason(entry, kind):
    """The channel gate's verdict as a trigger reason, or None if it may react.

    Cheap and I/O-free on BOTH channels — this is what keeps an ordinary ingestion day
    at exactly zero cost. Diary: the fail-closed ``public_reaction_consent`` marker.
    Social: the S2 origin membrane then the S5 sensitivity gate (#1670/#1673), both
    read straight off the already-stamped record.
    """
    if kind == KIND_SOCIAL:
        from privacy.social_consent import blocked_reason

        return blocked_reason(entry)

    from privacy.diary_consent import TIER_PRIVATE, resolve_consent

    return "private" if resolve_consent(entry) == TIER_PRIVATE else None


def maybe_react(entry, *, table_=None, lambda_client=None, force=False, **generate_kwargs):
    """THE TRIGGER (#1756 diary / #1675 social). Produce + store the reaction for one
    enriched record, or explain why it didn't. Never raises — the caller is a hot
    ingestion path and a reaction is never allowed to fail it.

    The gates, in cost order — every one of them is BEFORE any Bedrock call:
      1. ``not_diary``        — not a reaction surface at all: neither a Video Diary /
                                Solo Recording entry nor a social post (free, no I/O).
                                The reason string is kept from #1756 rather than
                                renamed, so the existing consumers/tests are unchanged.
      2. the channel's gate   — ``private`` (diary: no ``public_reaction_consent``
                                opt-in, the fail-closed default for 99.9% of entries) /
                                ``platform_origin`` (social: an S2 platform echo, never
                                his voice) / ``held`` (social: the S5 sensitivity gate
                                did not clear it). All free, no I/O.
      3. ``exists``           — this record already has a reaction (one cheap GetItem)
    Only then does ``generate_diary_reaction`` run, which itself checks the budget tier
    before spending anything (a tier-≥2 run returns ``no_reaction``).

    Returns ``{"reacted": bool, "reason": str, ...}``.
    """
    try:
        entry = entry or {}
        kind = reaction_kind(entry)
        if kind is None:
            return {"reacted": False, "reason": "not_diary"}

        blocked = _blocked_reason(entry, kind)
        if blocked:
            return {"reacted": False, "reason": blocked}

        if table_ is None:
            table_ = _table()
        if not force and reaction_exists(entry, table_):
            return {"reacted": False, "reason": "exists"}

        if lambda_client is None:
            import boto3

            lambda_client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-west-2"))
        reaction = generate_diary_reaction(entry, lambda_client=lambda_client, **generate_kwargs)
        if not reaction:
            # budget-paused, quality-gate HOLD, or an AI failure — nothing renders (AC3)
            return {"reacted": False, "reason": "no_reaction"}

        sk = store_reaction(reaction, table_=table_)
        return {"reacted": bool(sk), "reason": "stored" if sk else "store_failed", "sk": sk, "coach_id": reaction["coach_id"]}
    except Exception as e:  # noqa: BLE001 — fail-OPEN: a reaction never fails enrichment
        return {"reacted": False, "reason": "error", "error": str(e)}


def lambda_handler(event: dict, context=None) -> dict:
    """Generate + store the reaction for one record (manual / backfill invoke — the
    production trigger is the inline ``maybe_react`` call from that channel's own
    enrichment pass).

    Event: ``{"entry": {...}, "force": bool}`` — either an enriched journal item (carrying
    raw_text, enriched_themes/dominant_theme, the public_reaction_consent marker, date,
    channel) or an enriched social post (carrying post_id, title/description, origin, the
    sensitivity stamp, enriched_themes/enriched_coach_route, date, channel).
    Returns ``{"stored": bool, "reason": ..., "coach_id": ..., "sk": ...}``.
    """
    event = event or {}
    out = maybe_react(event.get("entry") or {}, force=bool(event.get("force")))
    return {"stored": out.get("reacted", False), **out}
