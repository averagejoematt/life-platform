"""lambdas/web/site_api_character.py — the character sheet (the game layer).

Split out of ``site_api_vitals.py`` (#1654 — god-module breakup). One seam: **the
RPG rendering of the day** — `/api/character` (pillar scores, level, per-pillar
day-grade replay), `/api/character_config` (the whitelisted "how the engine works"
contract served live so the mechanics panels can never drift from what the engine
runs), `/api/character_receipt` (the verifiable per-day computation receipt), and
`/api/character_stats` (the character_stats.json passthrough).

The routed handler entrypoints stay in the ``site_api_vitals`` facade as thin
delegators; the logic lives here. Handlers receive the facade's ``globals()`` as
``_g`` and read the monkeypatched/injectable state (``table``,
``EXPERIMENT_START``, ``pre_start_meta``, ``datetime``) via ``_g["<name>"]`` — the
surface ``test_character_not_instrumented`` / ``test_progression_receipts_1373`` /
``test_pre_start_contract_sweep`` patch on the facade.

This module does NOT import the facade; no import cycle. Every other shared helper
comes straight from ``site_api_common`` (identical binding semantics to the
pre-split module).
"""

import json
import os
import re as _re
from datetime import timedelta

from boto3.dynamodb.conditions import Key
from experiment.phase_filter import with_phase_filter  # ADR-058

from web.site_api_common import (
    PT,
    S3_REGION,
    USER_ID,
    USER_PREFIX,
    _decimal_to_float,
    _error,
    _ok,
    logger,
)


def character(date: str | None = None, *, _g) -> dict:
    """
    GET /api/character[?date=YYYY-MM-DD]
    Returns: character level, pillar scores, recent events.
    Cache: 900s (15 min) — computed nightly but visitors expect freshness.
    With ?date= (the time scrubber, 2026-06-13): the sheet as of that morning —
    latest record at-or-before the date, pilot/prior-cycle records included
    (history is explicitly cross-cycle), cached a day since the past is immutable.
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    datetime = _g["datetime"]
    pre_start_meta = _g["pre_start_meta"]
    table = _g["table"]

    import re as _re

    if date and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return _error(400, "date must be YYYY-MM-DD")
    # Character-sheet compute writes YESTERDAY's sheet daily ~16:30 UTC, so the freshest
    # record is routinely 1-2 days old. Take the latest available DATE# record (plus the
    # one before it, for day-over-day deltas) rather than a fixed today/yesterday window —
    # that window returned 503 for ~16h every day (00:00 UTC until the daily run landed),
    # degrading the Cockpit. `as_of_date` tells the reader how fresh it is.
    PILLAR_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    PILLAR_EMOJI = {
        "sleep": "😴",
        "movement": "🏋️",
        "nutrition": "🥗",
        "metabolic": "📊",
        "mind": "🧠",
        "relationships": "💬",
        "consistency": "🎯",
    }

    def _zeroed_pre_experiment(as_of: str) -> dict:
        # The zeroed "experiment hasn't started" state. Used both when the experiment
        # hasn't begun AND — critically — when the phase filter (ADR-058) hides every
        # pilot/pre-genesis sheet right after a reset: the first experiment-phase sheet
        # isn't computed until the morning after genesis, and a 503 in that window
        # degraded the Cockpit. Show zeroed, never a 503.
        # #948: never stamp a FUTURE as_of — a staged genesis put "as of <tomorrow>"
        # in the cockpit footer and character hero, a freshness claim about a date
        # that hasn't happened. Clamp to today (PT); the countdown fields ride along
        # pre-start. Inert (no clamp, pre_start=False) once genesis <= today.
        _pre = pre_start_meta()
        return _ok(
            {
                "character": {
                    "level": 1,
                    "tier": "Foundation",
                    "tier_emoji": "🔨",
                    "xp_total": 0,
                    "as_of_date": min(as_of, datetime.now(PT).date().isoformat()),
                    "pre_experiment": True,
                },
                "pillars": [
                    {"name": p, "emoji": PILLAR_EMOJI.get(p, ""), "level": 1, "raw_score": 0, "tier": "Foundation", "xp_delta": 0}
                    for p in PILLAR_ORDER
                ],
                **(_pre or {"pre_start": False}),
            },
            cache_seconds=900,
        )

    pk = f"{USER_PREFIX}character_sheet"
    _key_cond = Key("pk").eq(pk) & (Key("sk").between("DATE#0000-00-00", f"DATE#{date}") if date else Key("sk").begins_with("DATE#"))
    _resp = table.query(
        **with_phase_filter(
            {  # ADR-058: hide pilot character sheets (unless time-travelling)
                "KeyConditionExpression": _key_cond,
                "ScanIndexForward": False,
                "Limit": 2,
            },
            include_pilot=bool(date),
        )
    )
    _recs = _decimal_to_float(_resp.get("Items", []))
    record = _recs[0] if _recs else None
    prior_record = _recs[1] if len(_recs) > 1 else None

    # No experiment-phase sheet yet (incl. the post-reset window where all sheets are
    # pilot and filtered out) → zeroed state, not a 503.
    if not record:
        return _zeroed_pre_experiment(EXPERIMENT_START)
    date_str = str(record["sk"]).replace("DATE#", "")[:10]

    pillars = []
    for p in PILLAR_ORDER:
        pd = record.get(f"pillar_{p}", {})
        _drivers = pd.get("drivers") or {}
        pillars.append(
            {
                "name": p,
                "emoji": PILLAR_EMOJI.get(p, ""),
                "level": float(pd.get("level", 1)),
                "raw_score": float(pd.get("raw_score", 0)),
                "tier": pd.get("tier", "Foundation"),
                "xp_delta": float(pd.get("xp_delta", 0)),
                "xp_earned": float(pd.get("xp_earned", 0)),
                "score_delta": None,  # day-over-day move; filled below when a prior day exists
                # ADR-104 provenance — computed by the engine, never narrated:
                # how much real data backs the score, which behaviors didn't
                # happen, what's lifting/dragging, and whether levels are frozen
                # because the day carried no signal.
                "data_coverage": (float(pd["data_coverage"]) if pd.get("data_coverage") is not None else None),
                "coverage_hold": bool(pd.get("coverage_hold", False)),
                # #747: engine-computed, deterministic (ADR-105) — True only when
                # every weighted component had zero data today. Distinct from
                # coverage_hold (a real pillar having a thin day): this means the
                # pillar has no data source feeding it at all. Front end renders
                # a labeled "not yet instrumented" state instead of the bare
                # neutral raw_score; clears itself the day a component gets a
                # real value, no front-end change required.
                "not_instrumented": bool(pd.get("not_instrumented", False)),
                "not_instrumented_note": pd.get("not_instrumented_note"),
                "absent_behaviors": [str(b) for b in (pd.get("absent_behaviors") or [])],
                # #913 neglect honesty — the visible XP bleed (owed below the
                # 0-floor) and today's presence-driven atrophy on this pillar
                # (None when engaged / planned pause / not behavioral-heavy).
                # Absent on pre-v1.3.0 records → honest 0/None defaults.
                "xp_debt": float(pd.get("xp_debt", 0) or 0),
                "neglect_decay": (
                    {
                        "applied": True,
                        "multiplier": float(pd["neglect_decay"].get("multiplier", 1)),
                        "gap_days": float(pd["neglect_decay"].get("gap_days", 0)),
                    }
                    if isinstance(pd.get("neglect_decay"), dict)
                    else None
                ),
                "drivers": {
                    "top": [str(x) for x in (_drivers.get("top") or [])],
                    "dragging": [str(x) for x in (_drivers.get("dragging") or [])],
                    "absent": [str(x) for x in (_drivers.get("absent") or [])],
                    "no_data": [str(x) for x in (_drivers.get("no_data") or [])],
                },
            }
        )

    # Pre-experiment: show zeroed character (experiment hasn't started)
    if date_str < EXPERIMENT_START:
        return _zeroed_pre_experiment(date_str)

    # DPR-1.16 + Day-Grade Replay: deltas vs the PRIOR computed day (record-over-record,
    # robust to compute lag/gaps), not calendar yesterday.
    # #747: a not-yet-instrumented pillar's placeholder neutral score must not quietly
    # drag the whole-life composite toward 50 — exclude it, same as an absent reading.
    _composite_scores = [p["raw_score"] for p in pillars if not p.get("not_instrumented")]
    composite = (
        sum(_composite_scores) / len(_composite_scores)
        if _composite_scores
        else sum(p["raw_score"] for p in pillars) / max(len(pillars), 1)
    )
    composite_delta_1d = None
    if prior_record:
        _yd_scores = [float(prior_record.get(f"pillar_{p}", {}).get("raw_score", 0)) for p in PILLAR_ORDER]
        _yd_composite_scores = [
            float(prior_record.get(f"pillar_{p}", {}).get("raw_score", 0))
            for p in PILLAR_ORDER
            if not prior_record.get(f"pillar_{p}", {}).get("not_instrumented")
        ]
        _yd_composite = (
            sum(_yd_composite_scores) / len(_yd_composite_scores) if _yd_composite_scores else sum(_yd_scores) / max(len(_yd_scores), 1)
        )
        composite_delta_1d = round(composite - _yd_composite, 1)
        # per-pillar day-over-day score move (aligned by PILLAR_ORDER)
        for _pp, _yd_s in zip(pillars, _yd_scores):
            _pp["score_delta"] = round(_pp["raw_score"] - _yd_s, 1)

    return _ok(
        {
            "character": {
                "level": float(record.get("character_level", 1)),
                "tier": record.get("character_tier", "Foundation"),
                "tier_emoji": record.get("character_tier_emoji", "🔨"),
                "xp_total": float(record.get("character_xp", 0)),
                # #913: the visible bleed + the deterministic mood (engine-
                # computed, ADR-105). Absent on pre-v1.3.0 records → 0 / None.
                "xp_debt": float(record.get("character_xp_debt", 0) or 0),
                "character_mood": record.get("character_mood"),
                "character_mood_inputs": (
                    record.get("character_mood_inputs") if isinstance(record.get("character_mood_inputs"), dict) else None
                ),
                "as_of_date": date_str,
                "composite_score": round(composite, 1),
                "composite_delta_1d": composite_delta_1d,
                "time_travel": bool(date),
                # #590: the engine's designed cross-pillar couplings that are ACTIVE
                # right now (rare gameplay thresholds — e.g. Sleep Drag). The home
                # constellation lights these as directional overlay edges. Additive.
                # #1411 (ADR-105): the fit badge rides along — fitted (n_eff + CI)
                # or "authored prior — not yet confirmed". Pre-#1411 records carry
                # no fit fields; the honest default is the authored prior.
                "active_effects": [
                    {
                        "name": e.get("name"),
                        "emoji": e.get("emoji", ""),
                        "condition": e.get("condition", ""),
                        "targets": e.get("targets", {}),
                        "fit_status": e.get("fit_status", "authored-prior"),
                        "fit_n_eff": e.get("fit_n_eff"),
                        "fit_ci_95": e.get("fit_ci_95"),
                        "fit_badge": e.get("fit_badge") or "authored prior — not yet confirmed (n_eff=0)",
                    }
                    for e in (record.get("active_effects") or [])
                    if isinstance(e, dict)
                ],
            },
            "pillars": pillars,
        },
        cache_seconds=86400 if date else 900,  # the past is immutable
    )


# /api/character_config — the public "how the engine works" contract (character
# sheet P1.2). A WHITELISTED subset of config/{user}/character_sheet.json (the
# MCP-editable engine config), served live so the sheet's mechanics panels can
# never drift from what the engine actually runs. Never spread the config.
# Excluded BY DESIGN:
#   * pillar `owner`   — the config names a real public figure; the public site
#     fictionalizes real names (fail-closed until owners migrate to registered
#     personas)
#   * `baseline`       — /api/journey serves the public weight numbers
#   * `avatar`, `protocols`, `_meta` internals — private/prescriptive
_CHAR_CONFIG_LEVELING_KEYS = (
    "ema_lambda",
    "ema_window_days",
    "level_up_streak_days",
    "level_down_streak_days",
    "tier_up_streak_days",
    "tier_down_streak_days",
    "level_step_threshold",
    "level_step_bands",  # ADR-104: graduated step sizes by target gap
    "level_change_min_coverage",  # ADR-104: no-signal days can't move levels
    "xp_per_level",
    "daily_xp_decay",
    "xp_buffer_threshold",
    "xp_debt_cap",  # #913: the visible-bleed cap
    "neglect_decay",  # #913: atrophy knobs (n_grace_days/rate/floor/min_behavioral_share)
    "tier_streak_overrides",
)


def character_config(*, _g) -> dict:
    """
    GET /api/character_config
    Returns: pillar weights + component weights/targets, leveling mechanics
    (streak gates incl. per-tier overrides, XP economy), xp_bands, tier bands,
    and cross-pillar effects (emoji stripped — §8, renderers draw icons).
    Cache: 3600s — the config changes rarely (MCP edits take effect next compute).
    """
    table = _g["table"]

    import boto3 as _boto3

    bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
    try:
        s3 = _boto3.client("s3", region_name=S3_REGION)
        raw = s3.get_object(Bucket=bucket, Key=f"config/{USER_ID}/character_sheet.json")["Body"].read()
        cfg = json.loads(raw)
    except Exception as e:
        logger.warning("character_config: config load failed: %s", e)
        return _ok({"config": None, "available": False}, cache_seconds=300)

    # #1412 (ADR-105 rule 4): serve the EFFECTIVE targets — personal-variance
    # derived where the floor cleared, authored + "population prior, n<30"
    # labeled where not — with per-target provenance {method, window, n}.
    try:
        from health import personal_baselines as _pb

        cfg = _pb.effective_character_config(cfg, table, USER_PREFIX)
    except Exception as e:
        logger.warning("character_config: baselines overlay failed (authored config served): %s", e)

    def _scalars(o: dict) -> dict:
        return {k: v for k, v in (o or {}).items() if isinstance(v, (int, float, str, bool))}

    def _component_out(cv: dict) -> dict:
        out = _scalars(cv)
        if isinstance((cv or {}).get("target_provenance"), dict):
            out["target_provenance"] = cv["target_provenance"]
        return out

    pillars_out = {}
    for name, p in (cfg.get("pillars") or {}).items():
        pillars_out[name] = {
            "weight": p.get("weight"),
            "ema_lambda": p.get("ema_lambda"),
            "components": {cn: _component_out(cv) for cn, cv in (p.get("components") or {}).items()},
        }
    leveling = {k: v for k, v in (cfg.get("leveling") or {}).items() if k in _CHAR_CONFIG_LEVELING_KEYS}
    tiers = [{"name": t.get("name"), "min_level": t.get("min_level"), "max_level": t.get("max_level")} for t in cfg.get("tiers") or []]
    # #1411 (ADR-105): merge the latest quarterly effect fit so the sheet's
    # mechanics panel wears the earned badge — fitted (n_eff + CI) or "authored
    # prior — not yet confirmed". Fail-open to the declared authored default
    # (the merge itself can never invent "fitted": that only comes from a
    # stored fit record). Keys stay explicitly whitelisted.
    try:
        from experiment import effect_fitter

        effect_fitter.merge_fit_into_config(cfg, effect_fitter.load_latest_fit(table, USER_ID))
    except Exception as e:
        logger.warning("character_config: effect fit merge failed: %s", e)
    effects = [
        {
            "name": e.get("name"),
            "condition": e.get("condition"),
            "targets": e.get("targets"),
            "fit_status": e.get("fit_status", "authored-prior"),
            "fit_n_eff": e.get("fit_n_eff"),
            "fit_ci_95": e.get("fit_ci_95"),
            "fit_r": e.get("fit_r"),
            "fit_badge": e.get("fit_badge") or "authored prior — not yet confirmed (n_eff=0)",
            "fitted_at": e.get("fitted_at"),
        }
        for e in cfg.get("cross_pillar_effects") or []
    ]
    return _ok(
        {
            "available": True,
            "pillars": pillars_out,
            "leveling": leveling,
            "xp_bands": cfg.get("xp_bands") or [],
            "tiers": tiers,
            "cross_pillar_effects": effects,
            "updated_at": (cfg.get("_meta") or {}).get("last_updated"),
        },
        cache_seconds=3600,
    )


def character_receipt(date: str | None = None, verify: bool = False, *, _g) -> dict:
    """
    GET /api/character_receipt[?date=YYYY-MM-DD][&verify=1]
    The audit-grade progression receipt for a compute day (#1373): contributing
    input-row KEYS, engine formula version, config hash, per-pillar transition
    inputs/outputs, and the deterministic replay digest. Read-only.

    verify=1 replays the stored inputs server-side through the LIVE engine +
    config (the same bundled character_engine the nightly compute runs) and
    returns the provenance-labeled verdict — digest_match / config_drift /
    engine_drift / field-level mismatches.

    ADR-104: a date with no stored receipt answers available=false — receipts
    are never fabricated for changes that predate the receipt system. Dated
    reads include archived (prior-cycle) receipts deliberately, like
    /api/character?date= — history is cross-cycle and the receipt's own
    phase/cycle stamps ride along as provenance.
    Cache: 900s latest / 86400s dated (the past is immutable).
    """
    table = _g["table"]

    if date and not _re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return _error(400, "date must be YYYY-MM-DD")
    pk = f"{USER_PREFIX}character_receipt"
    if date:
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{date}"})
        item = resp.get("Item")
    else:
        resp = table.query(
            **with_phase_filter(
                {  # latest CURRENT-cycle receipt (ADR-058 — archived ones need ?date=)
                    "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").begins_with("DATE#"),
                    "ScanIndexForward": False,
                    "Limit": 1,
                }
            )
        )
        items = resp.get("Items", [])
        item = items[0] if items else None
    cache_s = 86400 if date else 900
    if not item:
        return _ok(
            {
                "available": False,
                "date": date,
                "reason": "no progression receipt recorded for this date — receipts began with #1373; earlier changes have no recorded inputs and are never back-fabricated (ADR-104)",
            },
            cache_seconds=cache_s,
        )

    receipt = _decimal_to_float({k: v for k, v in item.items() if k not in ("pk", "sk")})
    body = {"available": True, "receipt": receipt, "replay": None}
    if verify:
        try:
            import boto3 as _boto3
            from health import character_engine as _ce, progression_receipts as _pr

            bucket = os.environ.get("S3_BUCKET", "matthew-life-platform")
            s3 = _boto3.client("s3", region_name=S3_REGION)
            cfg = json.loads(s3.get_object(Bucket=bucket, Key=f"config/{USER_ID}/character_sheet.json")["Body"].read())
            # #1412: verify against the SAME effective config the compute hashed
            # into the receipt (personal-variance targets overlaid).
            from health import personal_baselines as _pb

            cfg = _pb.effective_character_config(cfg, table, USER_PREFIX)
            body["replay"] = _pr.replay(item, cfg, engine=_ce)
        except Exception as e:  # verify is best-effort; the receipt itself still serves
            logger.warning("character_receipt: replay failed: %s", e)
            body["replay"] = {"available": False, "reason": "replay unavailable (config load or engine error)"}
        cache_s = 900  # a verify verdict is against the LIVE config — never cache it a day
    return _ok(body, cache_seconds=cache_s)


def character_stats(*, _g) -> dict:
    """
    GET /api/character_stats
    Returns: current character level, tier, and all 7 pillar scores.
    Cache: 3600s (1 hr) — computed nightly.
    """
    EXPERIMENT_START = _g["EXPERIMENT_START"]
    datetime = _g["datetime"]
    pre_start_meta = _g["pre_start_meta"]
    table = _g["table"]

    today = datetime.now(PT).strftime("%Y-%m-%d")
    yesterday = (datetime.now(PT) - timedelta(days=1)).strftime("%Y-%m-%d")
    pk = f"{USER_PREFIX}character_sheet"
    record = None
    for date_str in [today, yesterday]:
        resp = table.get_item(Key={"pk": pk, "sk": f"DATE#{date_str}"})
        record = _decimal_to_float(resp.get("Item"))
        if record:
            break
    if not record:
        # Pre-compute / data-not-yet-available is NOT a 5xx situation.
        # Return 200 with computed=false so:
        #   - WAF/CloudFront alarms don't fire on a normal "no data yet" state
        #   - Homepage gauge fallback chain works (cs.level falsy → vitals API)
        #   - Clients can branch on the flag without parsing magic strings
        # 5-min cache: short enough that the first compute lands quickly,
        # long enough that 50k visitors don't hammer DDB.
        return _ok(
            {
                "character_stats": None,
                "pillars": None,
                "computed": False,
                "reason": "Character sheet not yet computed for today or yesterday",
            },
            cache_seconds=300,
        )

    PILLARS = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    pillars = {}
    for p in PILLARS:
        pd = record.get(f"pillar_{p}", {})
        pillars[p] = {
            "level": float(pd.get("level", 1)),
            "raw_score": float(pd.get("raw_score", 0)),
            "tier": pd.get("tier", "Foundation"),
        }

    # Pre-experiment: zeroed character
    if date_str < EXPERIMENT_START:
        PILLARS_ZERO = {p: {"level": 1, "raw_score": 0, "tier": "Foundation"} for p in PILLARS}
        # #948: align the stamp with /api/character's zeroed state \u2014 the honest
        # "as of" for a not-yet-started sheet is today (clamped so a staged future
        # genesis never stamps tomorrow), not the stale prior-cycle record's date;
        # the two character endpoints disagreed (2026-07-10 vs 2026-07-12).
        _pre = pre_start_meta()
        return _ok(
            {
                "character_stats": {
                    "level": 1,
                    "tier": "Foundation",
                    "tier_emoji": "\ud83d\udd28",
                    "xp_total": 0,
                    "as_of_date": min(EXPERIMENT_START, datetime.now(PT).date().isoformat()),
                    "pre_experiment": True,
                },
                "pillars": PILLARS_ZERO,
                **(_pre or {"pre_start": False}),
            },
            cache_seconds=3600,
        )

    return _ok(
        {
            "character_stats": {
                "level": float(record.get("character_level", 1)),
                "tier": record.get("character_tier", "Foundation"),
                "tier_emoji": record.get("character_tier_emoji", "🔨"),
                "xp_total": float(record.get("character_xp", 0)),
                "as_of_date": date_str,
            },
            "pillars": pillars,
        },
        cache_seconds=3600,
    )
