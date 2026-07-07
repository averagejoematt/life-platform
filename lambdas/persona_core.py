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
import os
import time

logger = logging.getLogger(__name__)

_S3_PREFIX = "config/coaches/"
_TTL_S = 300  # 5 minutes — matches persona_registry / coach_stance warm caches
_cache: dict = {}  # coach_id -> {"spec": dict|None, "ts": float}

# Defensive caps — specs are curated, but a corrupt/bloated field must never
# balloon a cached system block.
_MAX_FIELD_CHARS = 400
_MAX_LIST_ITEMS = 6


def _local_path(coach_id: str) -> str:
    """Repo-relative fallback: lambdas/persona_core.py -> ../config/coaches/{id}.json."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "config", "coaches", f"{coach_id}.json")


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


def persona_block(coach_id: str, s3_client=None, bucket=None) -> str:
    """load_voice_spec + voice_block in one call. "" on any failure."""
    try:
        return voice_block(load_voice_spec(coach_id, s3_client=s3_client, bucket=bucket))
    except Exception as e:  # never let a persona render break a caller
        logger.warning("[persona_core] persona_block failed for %s: %s", coach_id, e)
        return ""
