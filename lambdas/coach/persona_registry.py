"""Canonical persona registry loader (CC-00).

Single source of truth that reconciles the three historically-divergent coach
name-spaces — config/coaches/*.json keys, the engine COACH_IDS, and the
board_of_directors.json personas — so a coach's public byline is provably the
coach that authored the data.

Data lives in ``config/personas.json`` (synced to S3 at the same key). This
module is the read API consumed by both the compute engine and the site-api.
Consistency between this file, the JSON, and every coach id-space is enforced by
``tests/test_persona_registry.py`` (no orphans either direction).
"""

import json
import logging
import time

from common.repo_config import config_path

logger = logging.getLogger(__name__)

# Canonical operational coach ids, in display order. MUST stay equal to the
# ``operational: true`` personas in config/personas.json (enforced by
# tests/test_persona_registry.py). Hardcoded so compute lambdas can import the
# id list without an S3 round-trip at module load.
OPERATIONAL_COACH_IDS = [
    "sleep_coach",
    "nutrition_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
]
OPERATIONAL_SHORT_IDS = [c.replace("_coach", "") for c in OPERATIONAL_COACH_IDS]

# Coaching-team v2 (2026-08-10): the roster grew TIERS. training_coach retired at
# the cycle-13 genesis (Dr. Sarah Chen — the Performance seat absorbs training);
# chat-tier coaches carry a voice spec + a Telegram bot but no daily engine
# outputs; consulting specialists keep pipelines + site but no bots. MUST stay
# equal to the corresponding flags in config/personas.json
# (tests/test_persona_registry.py).
CHAT_COACH_IDS = ["pattern_coach", "career_coach", "eli_marsh"]
CONSULTING_COACH_IDS = ["glucose_coach", "labs_coach"]
RETIRED_COACH_IDS = ["training_coach"]

# Every coach with a voice spec a texting surface may load (worker persona path).
TEXTING_PERSONA_IDS = [c for c in OPERATIONAL_COACH_IDS if c not in CONSULTING_COACH_IDS] + CHAT_COACH_IDS

# The head coach (Principal Investigator) — the lead tier ABOVE the 8 operational
# coaches (#1112). Non-operational (writes no domain OUTPUT#/STANCE#) but a
# first-class cast member on the public staff surfaces. MUST stay equal to the
# single ``lead: true`` persona in config/personas.json (enforced by
# tests/test_persona_registry.py).
LEAD_PERSONA_ID = "eli_marsh"

# Last-resort byline when the registry cannot be read at all (S3 down AND the
# bundled config missing). A byline must never render empty or as a persona id —
# #1986: the board-lead byline is the one field a reader uses to decide who runs
# the board, so the fallback is pinned to the lead persona and asserted equal to
# config/personas.json by tests/test_board_lead_single_character.py.
LEAD_FALLBACK_NAME = "Dr. Eli Marsh"
LEAD_FALLBACK_TITLE = "Principal Investigator — Program Lead"

_S3_KEY = "config/personas.json"
_cache = {"data": None, "ts": 0}
_TTL_S = 300  # 5 minutes — matches board_loader


def _local_path():
    """Path to config/personas.json.

    Was `dirname(dirname(__file__))/config/personas.json`, which hard-coded "this
    module sits exactly one level under the repo root". #1653 moved it to
    lambdas/coach/, which silently resolved to lambdas/config/personas.json — the
    file loads fine from S3 in Lambda, so the break only showed up offline (tests
    and scripts), where it degraded to the empty-registry fallback rather than
    raising. See common.repo_config for why this searches upward.
    """
    return config_path("personas.json")


def load_registry(s3_client=None, bucket=None, force_refresh=False):
    """Load the registry dict. Prefers S3 when a client+bucket are given, falls
    back to the local repo file (tests / offline). Warm-container cached ~5 min."""
    now = time.time()
    if not force_refresh and _cache["data"] and (now - _cache["ts"]) < _TTL_S:
        return _cache["data"]

    data = None
    if s3_client and bucket:
        try:
            resp = s3_client.get_object(Bucket=bucket, Key=_S3_KEY)
            data = json.loads(resp["Body"].read().decode("utf-8"))
        except Exception as e:
            logger.warning("[persona_registry] S3 read failed (%s) — trying local file", e)

    if data is None:
        try:
            with open(_local_path(), encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception as e:
            logger.warning("[persona_registry] local read failed: %s", e)
            if _cache["data"]:
                return _cache["data"]
            return {"version": "0", "personas": {}}

    _cache["data"] = data
    _cache["ts"] = now
    return data


def personas(s3_client=None, bucket=None):
    """All personas keyed by persona_id."""
    return load_registry(s3_client, bucket).get("personas", {})


def resolve(persona_id, s3_client=None, bucket=None):
    """The persona dict for a persona_id, or None."""
    return personas(s3_client, bucket).get(persona_id)


def operational_personas(s3_client=None, bucket=None):
    """The 8 personas with a live coach_config_key + daily outputs (the public roster)."""
    return {k: v for k, v in personas(s3_client, bucket).items() if v.get("operational")}


def board_personas(s3_client=None, bucket=None):
    """Non-operational personas (the broader Board — lives on /method/board/)."""
    return {k: v for k, v in personas(s3_client, bucket).items() if not v.get("operational")}


def lead_persona(s3_client=None, bucket=None):
    """The single ``lead: true`` persona — the head coach who runs the board.

    #1986: two characters used to occupy this role (the integrator byline said
    Dr. Kai Nakamura, the roster said Dr. Eli Marsh). There is now ONE, and it is
    resolved here — every byline, prompt and noscript derives from this function
    rather than restating a name, so the cast can never fork again.
    """
    return resolve(LEAD_PERSONA_ID, s3_client, bucket) or {}


def lead_name(s3_client=None, bucket=None):
    """Display name of the board lead (never empty — see LEAD_FALLBACK_NAME)."""
    return lead_persona(s3_client, bucket).get("name") or LEAD_FALLBACK_NAME


def lead_title(s3_client=None, bucket=None):
    """Role title of the board lead, as it appears under the byline."""
    return lead_persona(s3_client, bucket).get("board_role") or LEAD_FALLBACK_TITLE


def lead_byline(s3_client=None, bucket=None):
    """``(name, title)`` for the board lead — the one byline pair the API serves."""
    return lead_name(s3_client, bucket), lead_title(s3_client, bucket)


def _find(field, value, s3_client=None, bucket=None):
    for pid, p in personas(s3_client, bucket).items():
        if p.get(field) == value:
            return pid, p
    return None, None


def by_coach_config_key(key, s3_client=None, bucket=None):
    """(persona_id, persona) for a config/coaches/<key>.json coach, or (None, None)."""
    return _find("coach_config_key", key, s3_client, bucket)


def by_engine_id(engine_id, s3_client=None, bucket=None):
    """(persona_id, persona) for an engine COACH_ID, or (None, None)."""
    return _find("engine_id", engine_id, s3_client, bucket)


def by_short_id(short_id, s3_client=None, bucket=None):
    """(persona_id, persona) for an intelligence_common short id, or (None, None)."""
    return _find("short_id", short_id, s3_client, bucket)


def display_name(persona_id, s3_client=None, bucket=None):
    """Human-facing name for a persona_id; falls back to the id itself."""
    p = resolve(persona_id, s3_client, bucket)
    return p.get("name") if p else persona_id


def _initials(name: str) -> str:
    parts = [w for w in str(name or "").replace("Dr.", "").split() if w and w[0].isalpha()]
    return "".join(w[0].upper() for w in parts[:2])


def short_id_names(s3_client=None, bucket=None, include_retired=False) -> dict:
    """{short_id: display name} for the operational roster — the map a dozen
    surfaces used to hand-copy (and let drift, which is how a renamed or retired
    coach kept ghost-writing). Retired personas are included only on request,
    for surfaces that render historical records under their real byline."""
    out = {}
    for pid, p in personas(s3_client, bucket).items():
        if not p.get("short_id") or not p.get("name"):
            continue
        if p.get("operational") or (include_retired and p.get("retired")):
            out[p["short_id"]] = p["name"]
    return out


def display_map(s3_client=None, bucket=None, include=("operational",)) -> dict:
    """{persona_id: {name, initials, title, color, emoji, lens}} for chip/roster
    surfaces. ``include`` selects tiers: "operational", "chat", "consulting",
    "retired". Fields fall back sensibly so a sparse persona never renders
    empty."""
    out = {}
    for pid, p in personas(s3_client, bucket).items():
        tier_ok = (
            ("operational" in include and p.get("operational"))
            or ("chat" in include and p.get("chat"))
            or ("consulting" in include and p.get("consulting"))
            or ("retired" in include and p.get("retired"))
        )
        if not tier_ok or not p.get("name"):
            continue
        out[pid] = {
            "name": p["name"],
            "initials": _initials(p["name"]),
            "title": p.get("title") or p.get("board_role") or "",
            "color": p.get("color") or "#94a3b8",
            "emoji": p.get("emoji") or "",
            "lens": p.get("lens") or p.get("short_bio") or "",
        }
    return out


def persona_for_telegram_route(route, s3_client=None, bucket=None):
    """(persona_id, persona) for a Telegram route key, or (None, None).

    Chat-tier coaches broke the old ``f"{route}_coach"`` derivation (eli_marsh
    has no ``_coach`` suffix), so the route → persona mapping is registry data
    (``telegram_route``), never string surgery."""
    return _find("telegram_route", route, s3_client, bucket)


def tts_voice(persona_id, s3_client=None, bucket=None):
    """The persistent Google Chirp 3: HD voice assigned to a persona (podcasts), or None."""
    p = resolve(persona_id, s3_client, bucket)
    return p.get("tts_voice") if p else None
