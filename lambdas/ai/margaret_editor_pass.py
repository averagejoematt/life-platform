"""margaret_editor_pass.py — Margaret Calloway's red pen (#548).

Margaret Calloway has existed since Week 3 as a named persona
(`config/board_of_directors.json` -> members.margaret_calloway) with a
`features.chronicle` entry describing her as the chronicle's editor — but
until now nothing ever called her. Elena's installment shipped first-draft,
every week, with no second perspective. This module gives Margaret the same
kind of real functional role #537 gave Elena (a mind), following the same
"the LLM proposes, this code disposes" discipline as
`emails/elena_state_updater.py` and the ADR-104 harness in
`grounded_generation.py`:

  1. CRITIQUE (Haiku, structured findings) — Margaret reads the just-drafted
     installment once and returns what works, what's doing double duty
     (cut/tighten), the one missing addition, any due reader-callback she
     thinks the piece owes but doesn't pay off, a craft score (0-10), and
     — only when the deterministic monthly gate allows it — a publishable
     editor's note candidate.
  2. REVISION (Haiku, Elena's own voice) — triggered ONLY when the critique
     found something worth fixing (low score, or concrete cut/callback-debt
     findings). One rewrite. Never regresses: the revision replaces the
     original only if it survives the SAME deterministic gates every other
     narrative surface uses (ADR-104's number-fabrication check + the
     privacy_guard vice/real-name gate) and isn't degenerate length-wise.
  3. EDITOR'S NOTE (no extra call — reuses the critique response) — spliced
     into the installment as a signed blockquote, gated to at most once a
     month (a code-level cadence, not the model's judgement) and through the
     same grounding + privacy checks as everything else.

Budget (#548): AT MOST 2 Haiku calls per chronicle run — one critique, one
conditional revision. There is deliberately no second critique call to
re-score the revision; the "keep if improved" decision after a revision is
made entirely by the deterministic gate (grounding + privacy + word-count
sanity), not by asking the model to grade its own homework again. Callers
gate the whole pass behind `budget_guard.allow("chronicle_editor")`
(tier-1 pause, matching `coach_narrative`) before even requesting a critique.

Pure functions, no AWS, no HTTP — callers supply `critique_fn` / `revise_fn`
(`(system, user) -> str` and `(system, user) -> (str, stop_reason)` callables —
#4535: the revision reports its stop reason so a cut reply never ships — typically thin wrappers around
`retry_utils.call_anthropic_api(..., model=AI_MODEL_HAIKU)`), the current
allow-listed numbers (from `grounded_generation.allowed_numbers`), and the
due-callback promises (from the PERSONA#elena CALLBACK# ledger, #537).

v1.0.0 — 2026-07-05 (#548, epic #527)
"""

import logging
import re

try:
    from common.platform_logger import get_logger

    logger = get_logger("margaret-editor-pass")
except ImportError:  # pragma: no cover
    logger = logging.getLogger("margaret-editor-pass")
    logger.setLevel(logging.INFO)

# A revision is attempted only when the critique earns it.
CRAFT_SCORE_THRESHOLD = 7

# Bounded inputs/outputs — the #410 lesson applied to a new surface.
MAX_DUE_CALLBACKS_IN_PROMPT = 5
MAX_CUT_ITEMS = 6
MAX_WORKS_ITEMS = 4
EDITORS_NOTE_MAX_CHARS = 700

# A revision that loses or gains too much text is a Haiku editing failure
# (truncation, padding, duplication) — reject it, keep the original.
MIN_WORD_RATIO = 0.55
MAX_WORD_RATIO = 1.6

# The editor's note is narrative texture, not a weekly fixture.
NOTE_MIN_DAYS_BETWEEN = 28

# #4535: the revision is the WHOLE installment again, so its output budget is measured
# from the draft it rewrites — never a flat cap. The old flat 1,500 tokens sat below a
# 1,200-1,800-word target (~1.3-1.4 tokens per English word ⇒ ~1,600-2,500 tokens), and
# two installments shipped cut off mid-sentence (wk3 published, wk4 draft). The budget
# covers the longest revision the word-ratio gate would still accept (MAX_WORD_RATIO ×
# the draft) at a conservative tokens-per-word, plus the title / stats / footer lines.
REVISION_TOKENS_PER_WORD = 1.5
REVISION_FORMAT_TOKENS = 256
REVISION_MIN_TOKENS = 4096
REVISION_MAX_TOKENS = 8192

# The closing signature every chronicle installment ends on (the same pattern the Story
# Desk's writer pins, content/story_writers.CHRONICLE_FOOTER).
CHRONICLE_FOOTER = r"\*Week \d+ of The Measured Life\*|\*Prologue — The Measured Life\*"


def revision_max_tokens(draft_text):
    """The revision call's output budget, measured from the draft (#4535)."""
    words = len((draft_text or "").split())
    need = int(words * MAX_WORD_RATIO * REVISION_TOKENS_PER_WORD) + REVISION_FORMAT_TOKENS
    return max(REVISION_MIN_TOKENS, min(REVISION_MAX_TOKENS, need))


def _split_reply(reply):
    """A revise_fn reply is ``(text, stop_reason)`` or a bare string (stop_reason unknown)."""
    if isinstance(reply, tuple) and len(reply) == 2:
        return reply[0], reply[1]
    return reply, None


def revision_completeness_findings(revised, stop_reason):
    """Why a revision is NOT a finished installment (#4535), or [] when it is.

    The model's own verdict first — anything but ``end_turn`` means the reply was cut,
    whatever the text looks like — then the text itself: it must end on the
    ``*Week N of The Measured Life*`` footer, and the prose before the footer must end
    on a terminal sentence. Shares ``content.story_checks.completeness`` with the Story
    Desk so the two writers hold one definition of "finished"."""
    from content.story_checks import completeness

    return completeness(revised, stop_reason=stop_reason, footer_pattern=CHRONICLE_FOOTER)


_FALLBACK_NARRATOR = {
    "name": "Margaret Calloway",
    "title": "Senior Editor — Longform & Narrative",
    "voice": {
        "tone": "Exacting, unsentimental, deeply respectful of the reader's time",
        "style": (
            "A fictional longform editor with no real-world masthead (#4363). Edits narrative nonfiction the way a "
            "surgeon operates — removes what doesn't belong, strengthens what does, never leaves "
            "fingerprints. She reads once slowly, then marks three things: what works, what's doing "
            "double duty, and what's missing."
        ),
    },
    "principles": [
        "Every piece needs a spine. Find it before you write a word.",
        "If a sentence is doing two jobs, it's doing neither well.",
        "The detail that almost didn't make the cut is usually the best one.",
        "Openings are promises. Closings are whether you kept them.",
        "Never cut a line because it's uncomfortable. Cut it because it's redundant.",
    ],
    "relationship": (
        "Margaret joined the project after Week 3, brought on to ensure 'The Measured Life' reaches its "
        "potential as serious longform journalism rather than a health blog. She edits Elena's installments "
        "before publication — tightening structure, cutting redundancy, occasionally adding the single "
        "sentence that unlocks a paragraph. She has high standards and low patience for sentimentality, "
        "but she believes in the series."
    ),
}


# Same absolute-privacy rules Elena's prompt carries — Margaret reads and can
# rewrite the piece, so she needs the same guardrails, not just a downstream check.
def _privacy_rules() -> str:
    """Built at runtime: the vice enumeration comes from the ER-06 non-committed
    channel (#2370 — the category names must not live in this public repo).
    Fail-closed via require=True — no vocabulary, no editor pass."""
    from privacy import content_filter_channel

    terms = ", ".join(content_filter_channel.blocked_keywords(require=True))
    return (
        "PRIVACY — ABSOLUTE, even while editing: never name a specific vice or substance Matthew is "
        f"moderating ({terms}, alcohol, nicotine, vaping, etc.) — refer to it "
        "only in non-specific terms if it's load-bearing to a note, never the substance itself. Never cite a "
        "specific gene name, rsID, or genotype string. Never name a real public figure as a coach or source."
    )


def build_narrator(config):
    """Margaret's persona dict via board_loader, or the hardcoded fallback.

    `config` is the S3 board_of_directors.json dict (or None). Mirrors the
    dual-path convention `wednesday_chronicle_lambda._build_elena_prompt_from_config`
    already uses for Elena.
    """
    if config:
        try:
            from coach import board_loader

            narrator = board_loader.build_narrator_prompt(config, narrator_id="margaret_calloway")
            if narrator:
                return narrator
        except ImportError:  # pragma: no cover — environment-dependent
            pass
    return dict(_FALLBACK_NARRATOR)


# ══════════════════════════════════════════════════════════════════════════════
# CRITIQUE
# ══════════════════════════════════════════════════════════════════════════════


def build_critique_system_prompt(narrator):
    """Margaret's critique-pass system prompt from her persona dict."""
    voice = narrator.get("voice", {}) or {}
    tone = voice.get("tone", _FALLBACK_NARRATOR["voice"]["tone"])
    style = voice.get("style", _FALLBACK_NARRATOR["voice"]["style"])
    principles = narrator.get("principles") or _FALLBACK_NARRATOR["principles"]
    relationship = narrator.get("relationship") or _FALLBACK_NARRATOR["relationship"]
    principles_text = "\n".join(f"- {p}" for p in principles[:6])

    return (
        f"You are {narrator.get('name', 'Margaret Calloway')}, {narrator.get('title', 'Senior Editor')} for "
        f"'The Measured Life,' the weekly chronicle Elena Voss writes about Matthew's health experiment.\n\n"
        f"YOUR VOICE: {tone}. {style}\n\n"
        f"YOUR RELATIONSHIP TO THE SERIES: {relationship}\n\n"
        f"YOUR PRINCIPLES:\n{principles_text}\n\n"
        "YOUR JOB THIS PASS: read the installment Elena just drafted, ONCE, slowly. Mark three things: what "
        "works (do not touch), what's doing double duty or padding the piece (cut or tighten), and the one "
        "single addition that would strengthen it — if there is one. You are also handed the promises Elena "
        "has made to readers that are due this week (her callback ledger); flag any the installment sets up "
        "but never pays off. You do not rewrite anything yet — that's a separate step, and only happens if "
        "your critique earns it.\n\n"
        f"{_privacy_rules()}\n\n"
        "Grade the installment's craft 0-10 (10 = nothing you'd change). A 7+ means solid, ship as-is. Below "
        "7 means it's worth one revision pass.\n\n"
        "OUTPUT — ONLY valid JSON, no markdown, no preamble:\n"
        "{\n"
        '  "works": ["what already works — do not touch (max 4)"],\n'
        '  "cut_or_tighten": [{"issue": "what\'s wrong", "detail": "specific line or passage, paraphrased"}],\n'
        '  "missing_addition": "one sentence describing the single addition that would help, or \\"\\"",\n'
        '  "callback_debt": ["a due promise from the ledger below that this installment sets up but never pays off"],\n'
        '  "craft_score": 7,\n'
        '  "editors_note": "IF (and only if) this week genuinely surfaces something about the craft of the '
        "series worth sharing with readers, one tight paragraph in your own voice, signed implicitly (no "
        "'--Margaret'). Otherwise the empty string. This is rare — most weeks it should be empty.\"\n"
        "}\n"
    )


def build_critique_user_message(installment_text, week_number, due_callbacks, note_eligible):
    """The critique-pass user message: the draft + her ledger input + the note gate state."""
    parts = [f"=== WEEK {week_number} INSTALLMENT (Elena's draft) ===\n{installment_text}"]

    due = [str(c).strip() for c in (due_callbacks or []) if str(c).strip()][:MAX_DUE_CALLBACKS_IN_PROMPT]
    if due:
        parts.append(
            "=== ELENA'S CALLBACK LEDGER — promises due to readers THIS WEEK ===\n"
            + "\n".join(f"- {c}" for c in due)
            + "\n\nDoes this installment pay any of these off? Flag the ones it doesn't."
        )
    else:
        parts.append("=== ELENA'S CALLBACK LEDGER ===\nNo promises are due this week.")

    if note_eligible:
        parts.append(
            "An editor's note IS eligible to publish this week (it's been long enough since the last one). "
            "Only propose one if something genuinely worth surfacing about the craft happened — do not force it."
        )
    else:
        parts.append('An editor\'s note is NOT eligible this week (one published too recently) — return "" for editors_note.')

    return "\n\n".join(parts)


def _extract_json(text):
    """The critique reply parsed in the one door (#4276): a dict, else None.

    Schema-less on purpose: `critique_fn` is a text seam (`_margaret_haiku_call` →
    `retry_utils.call_anthropic_api`), shared with Elena's PROSE revision call, so it
    carries no `output_config`. The fence-tolerant parse is `structured_json.parse_json_text`.
    """
    from ai.structured_json import parse_json_text

    parsed = parse_json_text(text)
    return parsed if isinstance(parsed, dict) else None


def _sanitize_critique(data):
    """Clamp/truncate an LLM critique payload into a safe, bounded shape."""
    if not isinstance(data, dict):
        return None
    try:
        score = int(data.get("craft_score", 10))
    except (TypeError, ValueError):
        score = 10
    score = max(0, min(10, score))
    return {
        "works": [str(w).strip()[:200] for w in (data.get("works") or [])[:MAX_WORKS_ITEMS] if str(w).strip()],
        "cut_or_tighten": [
            {"issue": str(c.get("issue", "")).strip()[:120], "detail": str(c.get("detail", "")).strip()[:300]}
            for c in (data.get("cut_or_tighten") or [])[:MAX_CUT_ITEMS]
            if isinstance(c, dict) and str(c.get("issue", "")).strip()
        ],
        "missing_addition": str(data.get("missing_addition") or "").strip()[:300],
        "callback_debt": [str(c).strip()[:200] for c in (data.get("callback_debt") or [])[:MAX_DUE_CALLBACKS_IN_PROMPT] if str(c).strip()],
        "craft_score": score,
        "editors_note": str(data.get("editors_note") or "").strip()[:EDITORS_NOTE_MAX_CHARS],
    }


def request_critique(installment_text, week_number, due_callbacks, note_eligible, narrator, critique_fn):
    """One Haiku call. Returns a sanitized critique dict, or None (fail-soft: no critique available)."""
    system = build_critique_system_prompt(narrator)
    user = build_critique_user_message(installment_text, week_number, due_callbacks, note_eligible)
    try:
        raw = critique_fn(system, user)
    except Exception as e:
        logger.warning("[margaret] critique call failed (fail-soft): %s", e)
        return None
    critique = _sanitize_critique(_extract_json(raw))
    if critique is None:
        logger.warning("[margaret] critique returned non-JSON — skipping edit pass")
    return critique


def needs_revision(critique):
    """Whether the critique earns a revision attempt."""
    if not critique:
        return False
    return bool(critique["craft_score"] < CRAFT_SCORE_THRESHOLD or critique["cut_or_tighten"] or critique["callback_debt"])


# ══════════════════════════════════════════════════════════════════════════════
# REVISION — one Elena rewrite, incorporating Margaret's notes
# ══════════════════════════════════════════════════════════════════════════════


def build_revision_user_message(installment_text, critique):
    """The revision-pass user message: original text + Margaret's structured notes."""
    lines = [
        "Your editor, Margaret Calloway, read this week's installment and left notes. Revise the installment "
        "to address them. Keep your own voice, length, and structure — this is a tightening pass, not a "
        "rewrite from scratch. Return the FULL installment in the exact same format you always use (title "
        "line in quotes, blank line, the [Weight: ... | Week Grade: ... | T0 Streak: ...] stats line, blank "
        "line, then the body, ending with the --- and *Week N of The Measured Life* signature).",
        f"=== YOUR DRAFT ===\n{installment_text}",
    ]
    if critique.get("works"):
        lines.append(
            "=== WHAT MARGARET SAYS IS ALREADY WORKING — do not touch these ===\n" + "\n".join(f"- {w}" for w in critique["works"])
        )
    if critique.get("cut_or_tighten"):
        lines.append(
            "=== WHAT MARGARET WANTS CUT OR TIGHTENED ===\n"
            + "\n".join(f"- {c['issue']}: {c['detail']}" for c in critique["cut_or_tighten"])
        )
    if critique.get("missing_addition"):
        lines.append(f"=== THE ONE ADDITION MARGARET SUGGESTS ===\n{critique['missing_addition']}")
    if critique.get("callback_debt"):
        lines.append(
            "=== PROMISES MARGARET SAYS YOU'RE NOT PAYING OFF ===\n"
            + "\n".join(f"- {c}" for c in critique["callback_debt"])
            + "\nPay these off in the revision, or explicitly extend them in-text — don't just drop them silently."
        )
    lines.append(_privacy_rules())
    lines.append(
        "Do not mention Margaret, an edit, or a revision anywhere in the text — you are Elena, and this is simply this week's installment."
    )
    return "\n\n".join(lines)


def _word_count_sane(original, revised):
    o = len((original or "").split())
    r = len((revised or "").split())
    if o == 0:
        return r > 0
    ratio = r / o
    return MIN_WORD_RATIO <= ratio <= MAX_WORD_RATIO


def _deterministic_ok(text, allowed_numbers):
    """The same deterministic gates every narrative surface uses. Returns (ok, reason)."""
    if allowed_numbers is not None:
        try:
            from ai.grounded_generation import fabricated_numbers

            fab = fabricated_numbers(text, allowed_numbers)
            if fab:
                return False, f"fabricated_numbers:{fab}"
        except ImportError:  # pragma: no cover
            pass
    try:
        from privacy import privacy_guard

        if not privacy_guard.is_clean(text):
            return False, "privacy_violation"
    except ImportError:  # pragma: no cover
        pass
    # #4363: Margaret revises AFTER Elena's grounding gate and signs the editor's note, so
    # an invented credit at a real publication she writes would reach the page ungated.
    try:
        from content.chronicle_schema import real_publication_credit_findings

        credits = real_publication_credit_findings(text)
        if credits:
            return False, f"real_publication_credit:{[c['publication'] for c in credits]}"
    except ImportError:  # pragma: no cover
        pass
    return True, "ok"


def apply_revision(installment_text, critique, allowed_numbers, revise_fn):
    """One conditional Haiku revision. Returns (final_text, applied: bool, reason: str).

    Never regresses: keeps the original unless the revision (a) exists, (b) is a
    FINISHED installment — the model stopped on ``end_turn``, the prose ends on a
    terminal sentence and the ``*Week N*`` footer is there (#4535), (c) is not
    degenerate in length, and (d) passes the same deterministic gates as every other
    narrative surface (ADR-104 number-fabrication + privacy_guard).

    ``revise_fn`` returns ``(text, stop_reason)``; a bare string is accepted (stop
    reason unknown — the text checks still run).
    """
    if not needs_revision(critique):
        return installment_text, False, "no_revision_needed"
    try:
        revised, stop_reason = _split_reply(revise_fn(None, build_revision_user_message(installment_text, critique)))
    except Exception as e:
        logger.warning("[margaret] revision call failed (fail-soft, keeping original): %s", e)
        return installment_text, False, f"revise_call_failed:{e}"
    revised = (revised or "").strip()
    if not revised:
        return installment_text, False, "empty_revision"
    # #4535: a truncated revision never ships — the draft does, and the fallback is named.
    # The model's own stop verdict is read first (a cut reply is "truncated" even when it
    # is also short); the text checks run after the length sanity check.
    incomplete = revision_completeness_findings(revised, stop_reason)
    model_cut = stop_reason is not None and stop_reason != "end_turn"
    if not model_cut and not _word_count_sane(installment_text, revised):
        return installment_text, False, "word_count_degenerate"
    if incomplete:
        logger.warning(
            "[margaret] revision_truncated — keeping Elena's draft (stop_reason=%s): %s",
            stop_reason,
            "; ".join(incomplete),
        )
        return installment_text, False, f"revision_truncated:{stop_reason}"
    ok, reason = _deterministic_ok(revised, allowed_numbers)
    if not ok:
        logger.warning("[margaret] revision rejected by deterministic gate: %s", reason)
        return installment_text, False, reason
    return revised, True, "revised"


# ══════════════════════════════════════════════════════════════════════════════
# EDITOR'S NOTE — narrative texture, gated to <=1/month
# ══════════════════════════════════════════════════════════════════════════════


def editors_note_eligible(last_note_date, current_date, min_days_between=NOTE_MIN_DAYS_BETWEEN):
    """Deterministic <=1/month gate — the code decides eligibility, not the model.

    Dates are "YYYY-MM-DD" strings. No prior note (or an unparseable date) => eligible.
    """
    if not last_note_date:
        return True
    from datetime import date

    try:
        last = date.fromisoformat(str(last_note_date))
        cur = date.fromisoformat(str(current_date))
    except ValueError:
        return True
    return (cur - last).days >= min_days_between


def extract_editors_note(critique, note_eligible, allowed_numbers):
    """The note text to publish this week, or None. Applies the same grounding +
    privacy gate as the revision — a note is new user-facing text like any other."""
    if not note_eligible or not critique:
        return None
    note = (critique.get("editors_note") or "").strip()
    if not note:
        return None
    ok, reason = _deterministic_ok(note, allowed_numbers)
    if not ok:
        logger.warning("[margaret] editor's note rejected by deterministic gate: %s", reason)
        return None
    return note


_SIGNATURE_RE = re.compile(r"\n-{3,}\s*\n\*Week", re.IGNORECASE)


def splice_editors_note(text, note):
    """Insert the note as a signed blockquote before the closing signature line
    (or append at the end if the expected signature isn't found)."""
    if not note:
        return text
    block = f"\n\n> **Editor's note — Margaret Calloway:** {note}\n"
    m = _SIGNATURE_RE.search(text)
    if m:
        idx = m.start()
        return text[:idx] + block + text[idx:]
    return text.rstrip() + block


# ══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════


def run_pass(
    installment_text,
    week_number,
    due_callbacks,
    allowed_numbers,
    note_eligible,
    narrator,
    critique_fn,
    revise_fn,
):
    """Margaret's full pass: critique -> (maybe) revise -> (maybe) splice a note.

    At most 2 model calls total (critique_fn, revise_fn) — the #548 budget.
    Fail-soft throughout: any failure returns the original text untouched.

    Returns a dict:
      final_text     — the (possibly revised, possibly note-spliced) installment
      critique       — the sanitized critique dict, or None
      revised        — bool
      revision_reason
      editors_note   — the published note text, or None
    """
    critique = request_critique(installment_text, week_number, due_callbacks, note_eligible, narrator, critique_fn)
    if critique is None:
        return {
            "final_text": installment_text,
            "critique": None,
            "revised": False,
            "revision_reason": "no_critique",
            "editors_note": None,
        }

    final_text, revised, reason = apply_revision(installment_text, critique, allowed_numbers, revise_fn)
    note = extract_editors_note(critique, note_eligible, allowed_numbers)
    if note:
        final_text = splice_editors_note(final_text, note)

    return {
        "final_text": final_text,
        "critique": critique,
        "revised": revised,
        "revision_reason": reason,
        "editors_note": note,
    }
