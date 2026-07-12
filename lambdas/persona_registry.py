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
import os
import time

logger = logging.getLogger(__name__)

# Canonical operational coach ids, in display order. MUST stay equal to the
# ``operational: true`` personas in config/personas.json (enforced by
# tests/test_persona_registry.py). Hardcoded so compute lambdas can import the
# id list without an S3 round-trip at module load.
OPERATIONAL_COACH_IDS = [
    "sleep_coach",
    "training_coach",
    "nutrition_coach",
    "mind_coach",
    "physical_coach",
    "glucose_coach",
    "labs_coach",
    "explorer_coach",
]
OPERATIONAL_SHORT_IDS = [c.replace("_coach", "") for c in OPERATIONAL_COACH_IDS]

# The head coach (Principal Investigator) — the lead tier ABOVE the 8 operational
# coaches (#1112). Non-operational (writes no domain OUTPUT#/STANCE#) but a
# first-class cast member on the public staff surfaces. MUST stay equal to the
# single ``lead: true`` persona in config/personas.json (enforced by
# tests/test_persona_registry.py).
LEAD_PERSONA_ID = "eli_marsh"

_S3_KEY = "config/personas.json"
_cache = {"data": None, "ts": 0}
_TTL_S = 300  # 5 minutes — matches board_loader


def _local_path():
    """Repo-relative path: lambdas/persona_registry.py -> ../config/personas.json."""
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(here), "config", "personas.json")


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


def tts_voice(persona_id, s3_client=None, bucket=None):
    """The persistent Google Chirp 3: HD voice assigned to a persona (podcasts), or None."""
    p = resolve(persona_id, s3_client, bucket)
    return p.get("tts_voice") if p else None
