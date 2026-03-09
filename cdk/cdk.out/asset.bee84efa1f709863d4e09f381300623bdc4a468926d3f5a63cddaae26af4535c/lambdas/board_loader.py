"""
board_loader.py — Shared Board of Directors config loader for all Lambdas.

Reads centralized persona definitions from S3 and builds AI prompts dynamically.
Bundled alongside each Lambda handler in its zip package.

Config location: s3://{bucket}/config/board_of_directors.json
Fallback: If S3 read fails, returns None so callers can use hardcoded fallback prompts.

Usage:
    from board_loader import load_board, get_feature_members, build_prompt_sections

v1.0.0 — 2026-03-02
"""
import json
import logging
import time

logger = logging.getLogger(__name__)

# ── In-memory cache (survives Lambda warm starts, ~5 min TTL) ──
_board_cache = {"data": None, "ts": 0}
_CACHE_TTL_S = 300  # 5 minutes


def load_board(s3_client, bucket, force_refresh=False, user_id="matthew"):
    """Load board config from S3 with warm-container caching.

    Returns the full config dict, or None if S3 read fails.
    Callers should check for None and fall back to hardcoded prompts.
    """
    now = time.time()
    if not force_refresh and _board_cache["data"] and (now - _board_cache["ts"]) < _CACHE_TTL_S:
        return _board_cache["data"]

    try:
        resp = s3_client.get_object(Bucket=bucket, Key=f"config/{user_id}/board_of_directors.json")
        config = json.loads(resp["Body"].read().decode("utf-8"))
        _board_cache["data"] = config
        _board_cache["ts"] = now
        logger.info("[board_loader] Loaded %d members from S3", len(config.get("members", {})))
        return config
    except Exception as e:
        logger.warning("[board_loader] Failed to load board config from S3: %s — callers should use fallback", e)
        # Return stale cache if available
        if _board_cache["data"]:
            logger.info("[board_loader] Returning stale cached config")
            return _board_cache["data"]
        return None


def get_feature_members(config, feature_name, active_only=True):
    """Get members configured for a specific feature, preserving config order.

    Returns list of (member_id, member_dict, feature_config) tuples.
    """
    if not config:
        return []

    results = []
    for mid, member in config.get("members", {}).items():
        if active_only and not member.get("active", True):
            continue
        feat_cfg = member.get("features", {}).get(feature_name)
        if feat_cfg:
            results.append((mid, member, feat_cfg))
    return results


def build_member_voice(member):
    """Build a voice/personality description string from a member's config."""
    voice = member.get("voice", {})
    parts = []
    if voice.get("tone"):
        parts.append(f"Tone: {voice['tone']}")
    if voice.get("style"):
        parts.append(f"Style: {voice['style']}")
    if voice.get("catchphrase"):
        parts.append(f'Principle: "{voice["catchphrase"]}"')
    elif member.get("principles"):
        # Use first principle as the guiding quote
        parts.append(f'Principle: "{member["principles"][0]}"')
    return "\n".join(parts)


def build_section_prompt(member, feat_cfg):
    """Build a single advisor section prompt from member + feature config.

    Returns (header, prompt_body) tuple.
    """
    header = feat_cfg.get("section_header", f"{member.get('emoji', '📋')} {member['name'].upper()}")
    focus = feat_cfg.get("prompt_focus", "Provide your expert analysis.")
    voice_desc = build_member_voice(member)

    body = f"{header}\n{focus}"
    if voice_desc:
        body += f"\n{voice_desc}"
    return header, body


def build_panel_prompt(config, feature_name, context_block="", rules_block="", suffix_block=""):
    """Build a complete multi-advisor panel prompt for a feature.

    Assembles the prompt from:
      1. Context block (caller provides — data, goals, etc.)
      2. Rules block (caller provides — shared rules for all advisors)
      3. Per-member sections (from config)
      4. Suffix block (caller provides — additional instructions)

    Returns the full prompt string ready for the AI call.
    """
    members = get_feature_members(config, feature_name)
    if not members:
        return None

    sections = []
    for mid, member, feat_cfg in members:
        header, body = build_section_prompt(member, feat_cfg)
        sections.append(body)

    prompt_parts = []
    if context_block:
        prompt_parts.append(context_block)
    if rules_block:
        prompt_parts.append(rules_block)

    prompt_parts.append("Write exactly these sections with these exact headers:\n")
    prompt_parts.append("\n\n".join(sections))

    if suffix_block:
        prompt_parts.append(suffix_block)

    return "\n\n".join(prompt_parts)


def build_narrator_prompt(config, narrator_id="elena_voss"):
    """Build narrator persona description from config (for Chronicle).

    Returns a dict with keys: name, bio, voice, principles, or None if not found.
    """
    if not config:
        return None
    member = config.get("members", {}).get(narrator_id)
    if not member or not member.get("active", True):
        return None

    return {
        "name": member["name"],
        "title": member.get("title", ""),
        "voice": member.get("voice", {}),
        "principles": member.get("principles", []),
        "relationship": member.get("relationship_to_matthew", ""),
        "focus_areas": member.get("focus_areas", []),
        "features": member.get("features", {}),
    }


def build_interviewee_descriptions(config, feature_name="chronicle"):
    """Build Board interview personality descriptions for the Chronicle.

    Returns a string describing each interviewee's personality for Elena's prompt.
    """
    members = get_feature_members(config, feature_name)
    if not members:
        return ""

    descriptions = []
    for mid, member, feat_cfg in members:
        if feat_cfg.get("role") != "interviewee":
            continue
        name = member["name"]
        personality = feat_cfg.get("personality", member.get("voice", {}).get("tone", ""))
        if personality:
            descriptions.append(f"{name} is {personality}")

    if not descriptions:
        return ""

    return "These feel like real interviews — " + ". ".join(descriptions) + "."


def get_member_color(config, member_id):
    """Get a member's color for HTML styling."""
    if not config:
        return "#6366f1"  # default indigo
    member = config.get("members", {}).get(member_id)
    return member.get("color", "#6366f1") if member else "#6366f1"


def get_matthew_context(config):
    """Extract Matthew's context from the first member's relationship field.

    Returns a standardized context string for prompts. Callers can override
    with their own context if they prefer.
    """
    if not config:
        return None
    # Pull from the Chair's relationship — it's the most general
    chair = config.get("members", {}).get("the_chair", {})
    return chair.get("relationship_to_matthew")
