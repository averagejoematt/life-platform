"""horizons_retrospective.py — the Horizons weekly retrospective (#1707, epic #1686 S3).

The week AFTER a pick, the **Mind coach** writes a grounded, public retrospective:
*why I recommended it* and *what I hoped it would do for Matthew*. This is the reader
hook for the public ``/data/horizons/`` feed. It is coach voice ABOUT A MEDIA PICK —
never Matthew's private reactions to it (those are S4 scope and stay private).

Four load-bearing constraints, all enforced here and all unit-testable offline:

  1. **GROUNDED (ADR-104), on BOTH sides.**
     *Input side:* the prompt is built ONLY from the stored pick's own fields (title /
     source / format / pitch / rationale_tag / url / week). No outside facts, no
     fabricated claims, no invented outcomes — the coach reflects on the pick it
     *actually made*, not on what Matthew did with it (which the coach does not know
     and must not pretend to). ``build_body`` never reads anything but the pick dict.
     *Output side (#1830):* input-side grounding plus a prompt instruction is exactly
     the posture ADR-104 rejected platform-wide — "prompt rules are hopes, code gates
     are guarantees". So the generated text also crosses
     ``grounded_generation.grounding_findings`` (the allow-list number gate + the
     #1242 date gate) against the numbers/dates the model was actually given, with
     one ``regen_once`` corrective rewrite. Anything still ungrounded is HELD —
     the same deterministic bar the chronicle, the coach briefs, ask/board_ask and
     State of Matthew already meet. Honest residual, recorded: a NON-numeric
     fabrication ("a landmark essay") is not deterministically detectable and stays
     covered by the prompt rule alone — ADR-104's stated residual on every surface.

  2. **BUDGET-GATED (ADR-062/125).** A retrospective is a reader-NARRATIVE surface →
     ``budget_guard`` band 2 (feature ``"horizons_retrospective"``, pauses at tier 2,
     one full tier after all internal AI, one before the irreducible reader promises).
     A paused call returns a ``paused`` verdict (no text), never a fabricated one, and
     ``bedrock_client.invoke``'s own tier-3 backstop is the hard floor underneath.

  3. **SENSITIVITY-GATED (#1673, fail-closed).** The generated text is stamped by
     ``broadcast_sensitivity_gate`` before it is publishable — exactly like the
     Broadcast feed. The deterministic spine (privacy_guard vices / real-names + PII)
     is the load-bearing check for AI-authored text: if the model ever emitted PII, a
     banned real name, or vice content it HOLDS (never auto-publishes). Only a
     ``cleared`` verdict yields a published retrospective.

Pure-ish: the Bedrock call (``invoker``) and the off-topic classifier are injected, so
the whole path is exercised offline with no network. Production wiring lives in
``lambdas/reading`` (bundled into MCP per #781 / the reading-rail bundle rule).
"""

from __future__ import annotations

from datetime import datetime, timezone

from privacy import broadcast_sensitivity_gate as gate

# The ADR-104 grounded-generation harness (#1830). FAIL-CLOSED, unlike the fail-soft
# import shims elsewhere in the codebase: this is a public reader surface, so if the
# gate module is missing from the bundle we withhold the retrospective rather than
# publish an ungated one. `generate()` reads `_gg is None` and HOLDS.
try:
    from ai import grounded_generation as _gg
except ImportError:  # pragma: no cover — environment-dependent; withhold, never pass through
    _gg = None

# ── Retrospective status seam (what the public feed keys on) ──────────────────────
STATUS_PUBLISHED = "published"  # cleared the gate → visible on /data/horizons/
STATUS_HELD = "held"  # a gate did not clear → withheld, fail-closed
STATUS_PAUSED = "paused"  # budget band 2 paused → no retrospective this run (transient)

# The `categories` marker a grounding hold carries, so the review surface can tell a
# fabrication hold from a privacy/sensitivity hold at a glance.
CATEGORY_UNGROUNDED = "ungrounded"

# Budget feature name — reader-NARRATIVE band (tier 2), registered in
# budget_guard._FEATURE_CUTOFF next to coach_narrative / state_of_matthew.
BUDGET_FEATURE = "horizons_retrospective"

CURATOR = "mind"  # the Mind coach owns Horizons (owner decision 2026-07-25)

_MAX_TOKENS = 320  # a short reflection (2-3 sentences), not an essay

_SYSTEM = (
    "You are the Mind coach on a public self-quantification platform, writing a short, "
    "honest retrospective about a media pick you recommended to Matthew a week ago. Say, "
    "in the coach's own voice, WHY you recommended it and WHAT you hoped it would do for "
    "him. Ground every sentence in the pick's own details, which are given to you below. "
    "You do NOT know what Matthew actually did with it or how he reacted — never claim he "
    "read it, liked it, changed anything, or felt any particular way. No fabricated facts "
    "about the piece beyond what the details state; no invented quotes, statistics, names, "
    "or outcomes. 2-3 sentences, plain and warm. Output only the retrospective prose."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _grounding_facts(pick: dict) -> str:
    """The ONLY facts the model may use — assembled from the stored pick's fields.

    Nothing here is invented; every line is a stored attribute of the verified pick.
    Absent optional fields are simply omitted (never guessed).
    """
    p = pick or {}
    lines = [
        f"Title: {p.get('title', '')}",
        f"Format: {p.get('format', '')}",
    ]
    if p.get("source"):
        lines.append(f"Source: {p['source']}")
    if p.get("rationale_tag"):
        lines.append(f"Why this pick, this week (rationale tag): {p['rationale_tag']}")
    if p.get("pitch"):
        lines.append(f"The one-line pitch you sent with it: {p['pitch']}")
    if p.get("week"):
        lines.append(f"ISO week recommended: {p['week']}")
    return "\n".join(lines)


def build_body(pick: dict) -> dict:
    """The grounded Bedrock Messages body for a pick's retrospective.

    Grounding is structural: the system prompt forbids outside facts and the user
    message carries ONLY ``_grounding_facts(pick)`` — so a test can assert the prompt
    contains the real pick fields and nothing fabricated.
    """
    return {
        "max_tokens": _MAX_TOKENS,
        "system": _SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": (
                    "Write your retrospective, grounded only in these details of the pick " "you recommended:\n\n" + _grounding_facts(pick)
                ),
            }
        ],
    }


def _extract_text(resp: dict) -> str:
    """Concatenate the text blocks of a Bedrock/Anthropic Messages response."""
    out = ""
    for block in (resp or {}).get("content") or []:
        if block.get("type") == "text":
            out += block.get("text", "")
    return out.strip()


def _default_invoker(body: dict) -> dict:
    """Production invoker: the single Bedrock chokepoint (ADR-062), narrative tier."""
    from ai import bedrock_client

    return bedrock_client.invoke(body, model_name="sonnet")


def _default_offtopic_classifier(text: str):
    """The off-topic layer for a COACH-authored retrospective.

    A Horizons retrospective is first-party editorial about a pick the coach itself
    curated FOR this platform — on-topic by construction, like the chronicle (which is
    editorial and does not pass the social feed's off-topic screen at all). So this
    layer vouches on-topic; the load-bearing fail-closed protection for AI-authored
    text is the gate's DETERMINISTIC spine (privacy_guard vices/real-names + PII),
    which still HOLDS a retrospective that ever emitted PII or vice content. Injected /
    overridable so a stricter semantic screen can be wired later without touching
    callers.
    """
    return gate.OfftopicResult(True, 1.0)


def _grounding_gate(pick: dict, text: str, invoke) -> tuple:
    """ADR-104 deterministic grounding + one corrective rewrite (#1830).

    Returns ``(best_text, findings)`` — a non-empty ``findings`` means the caller must
    HOLD. Fail-closed: if the harness is unavailable or itself raises, the retrospective
    is held with a synthetic finding, never published ungated.

    The allow-list is built from ``_grounding_facts(pick)`` ALONE — literally what the
    model was given — not from the whole pick record. A number living only in the pick's
    ``verification`` blob or an unrendered field was never shown to the model, so
    counting it as "grounded" would quietly widen the gate.
    """
    if _gg is None:  # pragma: no cover — environment-dependent
        return text, [{"type": "gate_unavailable", "detail": "grounded_generation is not available in this bundle"}]
    try:
        from ai.grounding_gate_params import cycle_gate_params  # #1967

        facts_block = _grounding_facts(pick)
        allowed = _gg.allowed_numbers(facts_block)
        # An EMPTY date allow-list is meaningful, not a no-op: it means "no calendar
        # date is legitimate here", which is true of a pick whose facts carry none.
        allowed_date_set = _gg.allowed_dates(facts_block)

        def _findings_fn(candidate):
            # #1967: cycle anchors arm stale_phase/stale_baseline/experiment_span
            # (#1691/#1897); framing-scoped, so a retrospective that never frames a
            # "Day N" claim sees no change in behavior.
            return _gg.grounding_findings(candidate, facts=None, allowed=allowed, allowed_dates=allowed_date_set, **cycle_gate_params())

        def _regen_fn(correction):
            body = build_body(pick)
            body["messages"] = list(body["messages"]) + [
                {"role": "assistant", "content": text},
                {"role": "user", "content": correction},
            ]
            return _extract_text(invoke(body))

        best, findings, _corrected = _gg.regen_once(text, _findings_fn, _regen_fn, surface="horizons_retrospective")
        return best, findings
    except Exception as e:  # noqa: BLE001 — a broken gate withholds; it never waves text through
        return text, [{"type": "gate_error", "detail": f"grounding gate failed ({type(e).__name__})"}]


def generate(pick: dict, *, invoker=None, offtopic_classifier=None) -> dict:
    """Generate + gate the retrospective for one stored pick. NEVER raises.

    Returns a verdict dict:
      * ``{"status": "published", "text", "curator", "generatedAt", "sensitivity_status"}``
      * ``{"status": "held", "reason", "categories", "generatedAt", ...}``   (fail-closed)
      * ``{"status": "paused", "reason", "generatedAt"}``                     (budget band 2)

    Order (ADR-105 — cheapest gate first, deterministic before publish):
      1. budget band 2 — if paused, stop before spending a token.
      2. Bedrock (grounded body) → text; an empty/failed generation HOLDS.
      3. broadcast_sensitivity_gate on the DRAFT — privacy/PII outranks grounding, so a
         leaking draft is held AS a privacy hold and never spends a corrective rewrite
         trying to make a leak better-grounded.
      4. grounding gate (#1830) — allow-list numbers/dates + one regen; still
         ungrounded ⇒ HOLD.
      5. broadcast_sensitivity_gate AGAIN, iff step 4 rewrote the text — the stamp must
         describe the bytes that actually publish, never a discarded draft.
    """
    now = _now_iso()

    # 1. Budget gate (reader-narrative band 2). Fail-open if budget_guard absent.
    try:
        from ai import budget_guard

        if not budget_guard.allow(BUDGET_FEATURE):
            return {"status": STATUS_PAUSED, "reason": "reader-narrative AI paused (budget tier 2)", "generatedAt": now}
    except ImportError:  # pragma: no cover — budget_guard is always bundled in prod
        pass

    # 2. Grounded generation through the single Bedrock chokepoint.
    invoke = invoker or _default_invoker
    try:
        resp = invoke(build_body(pick))
        text = _extract_text(resp)
    except Exception as e:  # noqa: BLE001 — a generation failure never publishes
        return {"status": STATUS_HELD, "reason": f"generation failed ({type(e).__name__})", "generatedAt": now}

    if not text:
        return {"status": STATUS_HELD, "reason": "empty generation", "generatedAt": now}

    # 3. Fail-closed sensitivity gate (#1673) on the draft — a privacy hold is reported
    #    as a privacy hold, never masked by the grounding verdict underneath it.
    classifier = offtopic_classifier or _default_offtopic_classifier

    def _sensitivity_hold(v):
        return {"status": STATUS_HELD, "reason": v.reason, "categories": list(v.categories), "generatedAt": now}

    verdict = gate.classify_sensitivity(text, offtopic_classifier=classifier)
    if not verdict.cleared:
        return _sensitivity_hold(verdict)

    # 4. Fail-closed grounding gate (#1830, ADR-104) — one corrective rewrite, then hold.
    draft = text
    text, findings = _grounding_gate(pick, text, invoke)
    if findings:
        details = [str(f.get("detail") or f.get("type")) for f in findings]
        return {
            "status": STATUS_HELD,
            "reason": "ungrounded: " + "; ".join(details[:3]),
            "categories": [CATEGORY_UNGROUNDED],
            "grounding_findings": details,
            "generatedAt": now,
        }

    # 5. Re-stamp iff the corrective rewrite changed the bytes — the published text, and
    #    only the published text, is what the sensitivity verdict may vouch for.
    if text != draft:
        verdict = gate.classify_sensitivity(text, offtopic_classifier=classifier)
        if not verdict.cleared:
            return _sensitivity_hold(verdict)

    return {
        "status": STATUS_PUBLISHED,
        "text": text,
        "curator": CURATOR,
        "sensitivity_status": gate.SENSITIVITY_CLEARED,
        "grounded": True,  # cleared the deterministic allow-list gate (#1830), not just the prompt rule
        "generatedAt": now,
    }
