"""persona_core.py — one voice per coach, on every surface (#531).

A coach's voice lives in ONE place — config/coaches/{coach_id}.json (the voice
spec the V2 daily brief already writes from). Before this module, the public
board (site_api_ai_lambda COACH_ROSTER) carried a one-line "lens" self and the
observatory experts (ai_expert_analyzer_lambda EXPERT_PERSONAS) a third
hand-written self — three disconnected minds per character. This module renders
the SAME voice-spec fields into a compact persona block those surfaces share,
so Dr. Lisa Park sounds like Dr. Lisa Park everywhere.

Design constraints:
- Byte-stable per coach: the block derives only from the voice-spec JSON
  (which changes rarely), never from live data — so a caller can put it in an
  ephemeral-cached system block and keep the 90% prompt-cache discount.
  Volatile state (stance, compressed memory, facts) stays in the user turn.
- Compact by intent: structural voice rules + decision style + anti-patterns,
  NO few-shot examples — the board answers in 3-5 sentences and the experts in
  2-3 paragraphs; the full-length calibration corpus stays a brief-only tool.
- Fail-soft: every loader returns None/"" on any failure and the caller keeps
  its previous (roster/persona-dict) framing — a missing spec never breaks a
  public endpoint.

Import paths: bundled at lambdas/ root (Code.from_asset ships the whole tree)
(ships inside every function bundle — deploy/build_bundle.py, #781).
"""

import json
import logging
import time

from common.repo_config import config_path

logger = logging.getLogger(__name__)

_S3_PREFIX = "config/coaches/"
_TTL_S = 300  # 5 minutes — matches persona_registry / coach_stance warm caches
_cache: dict = {}  # coach_id -> {"spec": dict|None, "ts": float}

# Defensive caps — specs are curated, but a corrupt/bloated field must never
# balloon a cached system block.
_MAX_FIELD_CHARS = 400
_MAX_LIST_ITEMS = 6


_SHARED_STANDARD_ID = "_shared_standard"


def _local_path(coach_id: str) -> str:
    """Offline fallback: config/coaches/{id}.json. Depth-independent — see
    common.repo_config (#1653)."""
    return config_path("coaches", f"{coach_id}.json")


def load_voice_spec(coach_id: str, s3_client=None, bucket=None, force_refresh=False):
    """The coach's voice spec dict, or None. S3 first (when client+bucket are
    given), local repo file as the offline/tests fallback. Warm-cached ~5 min."""
    now = time.time()
    hit = _cache.get(coach_id)
    if not force_refresh and hit and (now - hit["ts"]) < _TTL_S:
        return hit["spec"]

    spec = None
    if s3_client and bucket:
        try:
            resp = s3_client.get_object(Bucket=bucket, Key=f"{_S3_PREFIX}{coach_id}.json")
            spec = json.loads(resp["Body"].read().decode("utf-8"))
        except Exception as e:
            logger.warning("[persona_core] S3 voice spec read failed for %s (%s) — trying local file", coach_id, e)

    if spec is None:
        try:
            with open(_local_path(coach_id), encoding="utf-8") as fh:
                spec = json.load(fh)
        except Exception as e:
            logger.warning("[persona_core] local voice spec read failed for %s: %s", coach_id, e)
            spec = None

    _cache[coach_id] = {"spec": spec, "ts": now}
    return spec


def _clip(text) -> str:
    return str(text or "").strip()[:_MAX_FIELD_CHARS]


def _items(seq) -> list:
    return [str(x).strip() for x in (seq or [])[:_MAX_LIST_ITEMS] if str(x).strip()]


def shared_block(s3_client=None, bucket=None) -> str:
    """The MOS shared character standard, rendered as the byte-stable substrate
    every coach inherits (config/coaches/_shared_standard.json).

    Same loader + cache as the voice specs (S3-first, bundled file offline), and
    deliberately FIRST in persona_block: it is identical across coaches and stable
    across days, which is exactly what the COST-OPT-2 cached prefix wants. "" on
    any failure — a coach without the substrate still has its own voice.
    """
    std = load_voice_spec(_SHARED_STANDARD_ID, s3_client=s3_client, bucket=bucket)
    if not isinstance(std, dict):
        return ""
    lines = []
    if std.get("mission"):
        lines.append(f"YOUR SHARED STANDARD (every coach on Matthew's staff inherits this):\nMISSION: {_clip(std['mission'])}")
    rules = [str(r).strip() for r in (std.get("constitutional_rules") or [])[:12] if str(r).strip()]
    if rules:
        lines.append("RULES: " + "; ".join(rules) + ".")
    model = [str(m).strip() for m in (std.get("matt_model") or [])[:9] if str(m).strip()]
    if model:
        lines.append("WORKING MODEL OF MATTHEW (living context, never permanent labels): " + "; ".join(model) + ".")
    stages = std.get("relationship_stages") or {}
    stage_bits = [f"{k}: {_clip(v)}" for k, v in stages.items() if v]
    if stage_bits:
        lines.append("RELATIONSHIP STAGES: " + " | ".join(stage_bits))
    if std.get("disengagement_rule"):
        lines.append(f"DISENGAGEMENT: {_clip(std['disengagement_rule'])}")
    avoid = [str(a).strip() for a in (std.get("communication_avoid") or [])[:9] if str(a).strip()]
    if avoid:
        lines.append("EVERY COACH AVOIDS: " + "; ".join(avoid) + ".")
    loop = [str(q).strip() for q in (std.get("reasoning_loop") or [])[:9] if str(q).strip()]
    if loop:
        lines.append("BEFORE REPLYING, SILENTLY ASK: " + " ".join(loop))
    evidence = [str(e).strip() for e in (std.get("evidence_rules") or [])[:6] if str(e).strip()]
    if evidence:
        lines.append("EVIDENCE: " + "; ".join(evidence) + ".")
    safety = [str(s).strip() for s in (std.get("safety_boundaries") or [])[:6] if str(s).strip()]
    if safety:
        lines.append("HARD BOUNDARIES: " + "; ".join(safety) + ".")
    return "\n".join(lines)


def voice_block(spec: dict) -> str:
    """Render a voice spec as the compact shared persona block.

    Deterministic — same spec, same bytes — so callers may embed it in a
    prompt-cached system block. Returns "" when the spec is unusable.
    """
    if not isinstance(spec, dict):
        return ""
    rules = spec.get("structural_voice_rules") or {}
    decision = spec.get("decision_style") or {}
    anti = spec.get("anti_pattern_detection") or {}
    lines = []

    # Character layer (the MOS bible transplant, #2402): who this coach IS —
    # rendered ahead of the mechanics so the voice rules read as expressions of a
    # person rather than a style guide. Every field optional; absent fields cost
    # zero bytes so pre-transplant specs render exactly as before.
    identity_bits = []
    if spec.get("bio"):
        identity_bits.append(f"WHO YOU ARE: {_clip(spec['bio'])}")
    if spec.get("defining_tension"):
        identity_bits.append(f"YOUR DEFINING TENSION: {_clip(spec['defining_tension'])}")
    philosophy = _items(spec.get("philosophy"))
    if philosophy:
        identity_bits.append("WHAT YOU BELIEVE: " + "; ".join(philosophy) + ".")
    if spec.get("relationship_style"):
        identity_bits.append(f"YOUR RELATIONSHIP WITH MATTHEW: {_clip(spec['relationship_style'])}")
    phrases = _items(spec.get("signature_phrases"))
    if phrases:
        identity_bits.append("SIGNATURE LANGUAGE (use naturally, never mechanically): " + "; ".join(f'"{p}"' for p in phrases))
    blind = _items(spec.get("blind_spots"))
    if blind:
        identity_bits.append("YOUR BLIND SPOTS (own them when they show): " + "; ".join(blind))
    bounds = spec.get("boundaries") or {}
    owns = _items(bounds.get("owns"))
    not_owns = _items(bounds.get("does_not_own"))
    if owns or not_owns:
        b = []
        if owns:
            b.append("you own " + ", ".join(owns))
        if not_owns:
            b.append("you do NOT own " + ", ".join(not_owns) + " — hand those off by name")
        identity_bits.append("SCOPE: " + "; ".join(b) + ".")
    lines.extend(identity_bits)

    voice_bits = []
    if rules.get("sentence_rhythm"):
        voice_bits.append(f"- Sentence rhythm: {_clip(rules['sentence_rhythm'])}")
    if rules.get("uncertainty_style"):
        voice_bits.append(f"- Uncertainty: {_clip(rules['uncertainty_style'])}")
    if rules.get("analogy_domain"):
        voice_bits.append(f"- Analogy domain: {_clip(rules['analogy_domain'])}")
    if rules.get("humor_style"):
        voice_bits.append(f"- Humor: {_clip(rules['humor_style'])}")
    if rules.get("relationship_to_others"):
        voice_bits.append(f"- Relationship to the other coaches: {_clip(rules['relationship_to_others'])}")
    moves = _items(rules.get("signature_moves"))
    if moves:
        voice_bits.append("- Signature moves: " + "; ".join(moves))
    if voice_bits:
        lines.append("YOUR VOICE (the same persistent voice spec your daily-brief self writes from):")
        lines.extend(voice_bits)

    decision_bits = []
    if decision.get("default_evidence_threshold"):
        decision_bits.append(f"evidence threshold: {_clip(decision['default_evidence_threshold'])}")
    if decision.get("comfort_with_bold_claims"):
        decision_bits.append(f"bold claims: {_clip(decision['comfort_with_bold_claims'])}")
    if decision.get("revision_style"):
        decision_bits.append(f"revision style: {_clip(decision['revision_style'])}")
    if decision_bits:
        lines.append("DECISION STYLE: " + " | ".join(decision_bits))

    phrases = _items(anti.get("phrase_blacklist"))
    if phrases:
        lines.append("NEVER USE (your own anti-pattern list): " + "; ".join(f'"{p}"' for p in phrases))
    structures = _items(anti.get("structural_blacklist"))
    if structures:
        lines.append("FORBIDDEN STRUCTURES: " + "; ".join(structures))

    return "\n".join(lines)


def texting_block(spec: dict) -> str:
    """The coach's texting register (#2402) — rendered ONLY on the chat surface.

    The board answers in 3-5 sentences and the observatory experts in paragraphs;
    telling them how to text would be noise. The Telegram worker appends this to
    persona_block. "" when the spec carries no texting_style.
    """
    if not isinstance(spec, dict):
        return ""
    style = spec.get("texting_style") or {}
    if not isinstance(style, dict) or not style:
        return ""
    labels = (
        ("burst_shape", "Bursts"),
        ("message_length", "Length"),
        ("punctuation", "Punctuation"),
        ("opening_register", "Openings"),
        ("double_text", "Double-texting"),
        ("emoji_posture", "Emoji"),
        # #2533 — chat-only by design. The shared standard says every coach is a
        # fictional composite and must never claim otherwise; this is the same
        # concession rendered in ONE coach's voice, so eight personas stop
        # answering "are you a real person?" with the same sentence (measured
        # 2026-08-10: `"No — I'm a"` opened 6 of 8 verbatim, and the panel called
        # 100% of those conversations AI). The board and the observatory never
        # face the question, which is why it rides here and not in voice_block.
        ("identity_stance", "Identity"),
        # #2534 — when this coach stops. Measured: the two least-flagged coaches are
        # the two whose specs already instruct stopping ("then quiet", "silence is a
        # valid output"); the most-flagged instruct warmth and questions. Restraint
        # is the dimension the roster was missing, and it is per-persona because a
        # single shared sentence would fix the tone and leave the collapse untouched
        # (the #2533 lesson).
        ("restraint", "Restraint"),
        # #2536 — the two situations where the roster measurably converged on ONE
        # template. Given the identical opener "honestly I'm just tired of all of
        # this", 7 of 8 coaches opened by naming his state back at him and the
        # three-word stem "that kind of" opened replies from 5 of them; on honest
        # absence, "don't have that" opened the admission for 6 of 8. The shared
        # prompt can only forbid those constructions — it cannot supply eight
        # different replacements without becoming the ninth template — so what each
        # coach does INSTEAD is per-persona, and rides here for the same reason
        # restraint does: the board answers in paragraphs and never faces either
        # moment, so this is chat-surface calibration, not identity.
        ("vulnerable_shape", "When he brings you something heavy, or just a bad day"),
        ("absence_shape", "When you don't have it"),
    )
    bits = [f"- {label}: {_clip(style[key])}" for key, label in labels if style.get(key)]
    if not bits:
        return ""
    block = "HOW YOU TEXT (this surface only — a phone, not a report):\n" + "\n".join(bits)
    # Bubble-shaped few-shots (#2402): the bibles' dialogue examples re-cut for a
    # phone. Two at most, generously clipped — register calibration, not a corpus.
    shots = [str(s).strip()[:600] for s in (spec.get("texting_few_shots") or [])[:2] if str(s).strip()]
    if shots:
        block += "\n\nHOW A REAL EXCHANGE READS (register calibration, never scripts to reuse):\n" + "\n\n".join(shots)
    return block


def persona_block(coach_id: str, s3_client=None, bucket=None) -> str:
    """shared substrate + load_voice_spec + voice_block in one call. "" on any failure.

    The substrate joins ONLY when the coach's own voice resolves: a substrate-only
    persona would make every degraded coach sound like the same generic person,
    which is the nameless-coach defect in a nicer shirt.
    """
    try:
        voice = voice_block(load_voice_spec(coach_id, s3_client=s3_client, bucket=bucket))
        if not voice:
            return ""
        shared = shared_block(s3_client=s3_client, bucket=bucket)
        return f"{shared}\n\n{voice}" if shared else voice
    except Exception as e:  # never let a persona render break a caller
        logger.warning("[persona_core] persona_block failed for %s: %s", coach_id, e)
        return ""
