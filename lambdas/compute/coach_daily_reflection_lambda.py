"""coach_daily_reflection_lambda.py — the board's daily MOVES job (#4583).

RETIRED 2026-10-23 (owner ruling on #4583): the per-coach ≤120-word daily REFLECTION
(CC-08) that this job used to write to generated/coach_daily.json after the moves. The
move is now each coach's single daily voice: the coach profile's `daily` slot reads the
coach's line from the newest MOVES# row (`site_api_coach_profile._coach_daily`), and a
coach who did not speak on the current run serves nothing rather than a stale reflection.
The removal record is the "Retired" table in docs/PROPORTIONALITY.md: the reflection
prompt, its ER-03 + #2430 grounding gate and the #2889 hash-and-reuse slot stay in git
history at the commit before the retirement, and the last artifact written stays in S3
at generated/coach_daily.json as the reference copy — kept, no longer written or read.
Saving: up to seven Haiku calls a day (one per operational coach, plus a stricter
retry on a gate miss), less the #2889 reuse hits.

What this job still does, once a day on the batch (never on page view):
  * Self-skips at budget tier >= 2 (PG-10) — never pushes the monthly ceiling.
  * The board's daily moves: one fact sheet for the day built from served values, one
    Haiku call choosing at most three speakers and each one's move, one Sonnet call per
    chosen coach, every line refused in code unless it is a move grounded on the sheet,
    and two opposed lines opening a dated Dispute Docket bet. The whole stage is
    `coach.coach_moves`; `{"force_moves": true}` in the event re-runs it on a day whose
    row already exists. The function keeps its name (CDK, ci/lambda_map.json, the
    budget ledger's attribution key) — renaming a deployed function is not this change.
"""

import json
import logging
import os

import boto3
from coach import coach_moves, persona_registry
from common.pacific_time import pacific_today  # #2811: THE Pacific day helper — DATE# keys are Pacific days

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
S3_BUCKET = os.environ.get("S3_BUCKET", "matthew-life-platform")
REGION = os.environ.get("AWS_REGION", "us-west-2")
SKIP_TIER = 2  # PG-10: at budget tier >= 2 the daily moves do not run


def _voice(s3, coach_config_key):
    """A coach's structural voice rules + one few-shot sample — the move line's voice."""
    try:
        obj = s3.get_object(Bucket=S3_BUCKET, Key=f"config/coaches/{coach_config_key}.json")
        cfg = json.loads(obj["Body"].read())
        rules = cfg.get("structural_voice_rules") or {}
        ex = (cfg.get("few_shot_examples") or [None])[0]
        if isinstance(ex, dict):
            ex = ex.get("output") or ex.get("text") or next(iter(ex.values()), None)
        return json.dumps(rules)[:1200], (ex if isinstance(ex, str) else "")
    except Exception:
        return "", ""


def lambda_handler(event, context):
    # PG-10: budget self-skip — never run when spend is elevated.
    try:
        from ai.budget_guard import current_tier

        tier = current_tier()
        if tier >= SKIP_TIER:
            logger.info("[coach_daily] budget tier %s >= %s — skipping (PG-10)", tier, SKIP_TIER)
            return {"skipped": True, "tier": tier}
    except Exception:
        pass  # fail-open: a budget blip must not break the batch

    s3 = boto3.client("s3", region_name=REGION)
    table = boto3.resource("dynamodb", region_name=REGION).Table(TABLE_NAME)
    reg = persona_registry.load_registry(s3, S3_BUCKET).get("personas", {})
    today = pacific_today()
    _voices: dict = {}

    def voices(coach_id):
        if coach_id not in _voices:
            _voices[coach_id] = _voice(s3, (reg.get(coach_id) or {}).get("coach_config_key", coach_id))
        return _voices[coach_id]

    # #4583: the board's daily moves — one fact sheet, one cast call, at most three lines,
    # each refused in code unless it is a move grounded on the sheet. Written to
    # COACH#eli_marsh / MOVES#{date}. Never raises.
    names = {cid: (reg.get(cid) or {}).get("name") or cid for cid in persona_registry.OPERATIONAL_COACH_IDS}
    moves = coach_moves.run(table, names=names, voices=voices, today=today, force=bool((event or {}).get("force_moves")))
    logger.info("[coach_daily] moves: %s", moves)

    # #4583 (2026-10-23): the per-coach reflection loop that ran here is retired — see the
    # module docstring. Nothing is written to generated/coach_daily.json any more.
    return {"moves": moves}
