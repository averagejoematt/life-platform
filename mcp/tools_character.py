"""
Character Sheet tools: view character level, pillar detail, and level history.
Reads pre-computed data from DynamoDB SOURCE#character_sheet partition.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from mcp.config import table, USER_PREFIX, logger

# ── Constants ──
CS_PK = USER_PREFIX + "character_sheet"

_TIER_BARS = {
    "Foundation": "██░░░░░░░░",
    "Momentum":   "████░░░░░░",
    "Discipline": "██████░░░░",
    "Mastery":    "████████░░",
    "Elite":      "██████████",
}

_PILLAR_EMOJI = {
    "sleep": "😴", "movement": "🏋️", "nutrition": "🥗",
    "metabolic": "📊", "mind": "🧠", "relationships": "💬",
    "consistency": "🎯",
}

_PILLAR_ORDER = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]


def _fetch_one(date_str):
    try:
        resp = table.get_item(Key={"pk": CS_PK, "sk": "DATE#" + date_str})
        item = resp.get("Item")
        return _d2f(item) if item else None
    except Exception as e:
        logger.error(f"[character] fetch failed for {date_str}: {e}")
        return None


def _fetch_range(start, end):
    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
            ExpressionAttributeValues={
                ":pk": CS_PK, ":s": "DATE#" + start, ":e": "DATE#" + end,
            },
        )
        items = resp.get("Items", [])
        while resp.get("LastEvaluatedKey"):
            resp = table.query(
                KeyConditionExpression="pk = :pk AND sk BETWEEN :s AND :e",
                ExpressionAttributeValues={
                    ":pk": CS_PK, ":s": "DATE#" + start, ":e": "DATE#" + end,
                },
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))
        return [_d2f(i) for i in items]
    except Exception as e:
        logger.error(f"[character] range query failed: {e}")
        return []


def _d2f(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _d2f(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_d2f(i) for i in obj]
    return obj


def _format_pillar_line(name, pillar_data):
    emoji = _PILLAR_EMOJI.get(name, "📋")
    level = pillar_data.get("level", 1)
    tier = pillar_data.get("tier", "Foundation")
    tier_emoji = pillar_data.get("tier_emoji", "🔨")
    raw = pillar_data.get("raw_score")
    bars = _TIER_BARS.get(tier, "░░░░░░░░░░")
    raw_str = f" (raw: {raw})" if raw is not None else ""
    return f"{emoji} {name.capitalize():15s} {bars} {level:3d} {tier_emoji} {tier}{raw_str}"


# ── Tool: get_character_sheet ──

def tool_get_character_sheet(args):
    """Get the current character sheet — overall level, all 7 pillars, active effects, recent events."""
    date = args.get("date")
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    record = _fetch_one(date)
    if not record:
        yesterday = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        record = _fetch_one(yesterday)
        if not record:
            return {"error": f"No character sheet found for {date} or {yesterday}. "
                    "The character sheet may not have been computed yet. "
                    "Run the backfill or wait for the next Daily Brief."}
        date = yesterday

    # 14-day sparkline data
    start_14d = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=13)).strftime("%Y-%m-%d")
    history = _fetch_range(start_14d, date)

    sparklines = {}
    for pillar in _PILLAR_ORDER:
        levels = []
        for h in history:
            p = h.get(f"pillar_{pillar}", {})
            levels.append(p.get("level", 0))
        sparklines[pillar] = _make_sparkline(levels)

    lines = [
        f"🎮 CHARACTER SHEET — Level {record.get('character_level', 1)} "
        f"({record.get('character_tier_emoji', '🔨')} {record.get('character_tier', 'Foundation')})",
        f"📅 {date}  |  XP: {record.get('character_xp', 0)}  |  Engine: {record.get('engine_version', '?')}",
        "━" * 60,
    ]

    for pillar in _PILLAR_ORDER:
        pdata = record.get(f"pillar_{pillar}", {})
        line = _format_pillar_line(pillar, pdata)
        spark = sparklines.get(pillar, "")
        xp_delta = pdata.get("xp_delta", 0)
        xp_str = f"+{xp_delta}" if xp_delta >= 0 else str(xp_delta)
        lines.append(f"{line}  {spark}  XP:{xp_str}")

    effects = record.get("active_effects", [])
    if effects:
        lines.append("")
        lines.append("Active Effects: " + "  ".join(
            f"{e.get('emoji', '')} {e['name']}" for e in effects))

    events = record.get("level_events", [])
    if events:
        lines.append("")
        for ev in events:
            etype = ev.get("type", "")
            if "tier" in etype:
                lines.append(f"{'🏆' if 'up' in etype else '📋'} "
                           f"{ev.get('pillar', 'Overall').capitalize()} "
                           f"{ev.get('old_tier', '?')} → {ev.get('new_tier', '?')}")
            elif "character" in etype:
                lines.append(f"⭐ Character Level {ev.get('old_level')} → {ev.get('new_level')}")
            else:
                arrow = "↑" if "up" in etype else "↓"
                lines.append(f"{arrow} {ev.get('pillar', '?').capitalize()} "
                           f"Level {ev.get('old_level')} → {ev.get('new_level')}")

    return {
        "display": "\n".join(lines),
        "date": date,
        "character_level": record.get("character_level"),
        "character_tier": record.get("character_tier"),
        "character_xp": record.get("character_xp"),
        "pillars": {p: record.get(f"pillar_{p}", {}) for p in _PILLAR_ORDER},
        "active_effects": effects,
        "level_events": events,
        "sparklines": sparklines,
    }


# ── Tool: get_pillar_detail ──

def tool_get_pillar_detail(args):
    """Deep dive into a single pillar: component breakdown, daily scores, level history, XP curve."""
    pillar = args.get("pillar", "").lower()
    if pillar not in _PILLAR_ORDER:
        return {"error": f"Invalid pillar '{pillar}'. Valid: {_PILLAR_ORDER}"}

    days = min(args.get("days", 30), 180)
    end_date = args.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    records = _fetch_range(start_date, end_date)
    if not records:
        return {"error": f"No character sheet data found between {start_date} and {end_date}."}

    daily_data = []
    raw_scores = []
    levels = []
    events = []

    for rec in records:
        pdata = rec.get(f"pillar_{pillar}", {})
        date = rec.get("date", "?")
        raw = pdata.get("raw_score")
        lv = pdata.get("level", 0)

        daily_data.append({
            "date": date, "raw_score": raw, "level_score": pdata.get("level_score"),
            "level": lv, "tier": pdata.get("tier", "?"), "xp_delta": pdata.get("xp_delta", 0),
        })
        if raw is not None:
            raw_scores.append(raw)
        levels.append(lv)

        for ev in rec.get("level_events", []):
            if ev.get("pillar") == pillar or ev.get("type", "").startswith("character"):
                events.append({**ev, "date": date})

    latest = records[-1].get(f"pillar_{pillar}", {})
    components = latest.get("components", {})

    summary = {
        "current_level": latest.get("level", 0),
        "current_tier": latest.get("tier", "?"),
        "current_tier_emoji": latest.get("tier_emoji", "🔨"),
        "total_xp": latest.get("xp_total", 0),
        "raw_score_avg": round(sum(raw_scores) / len(raw_scores), 1) if raw_scores else None,
        "raw_score_min": min(raw_scores) if raw_scores else None,
        "raw_score_max": max(raw_scores) if raw_scores else None,
        "level_change_count": len(events),
        "days_analyzed": len(records),
    }

    comp_lines = []
    for comp_name, comp_data in sorted(components.items()):
        if isinstance(comp_data, dict):
            score = comp_data.get("score")
            weight = comp_data.get("weight", 0)
            score_str = f"{score:.0f}" if score is not None else "—"
            comp_lines.append(f"  {comp_name}: {score_str}/100 (weight: {weight:.0%})")

    emoji = _PILLAR_EMOJI.get(pillar, "📋")
    display = [
        f"{emoji} {pillar.upper()} — Detailed Analysis ({days}d)",
        "━" * 50,
        f"Level: {summary['current_level']} ({summary['current_tier_emoji']} {summary['current_tier']})",
        f"XP Total: {summary['total_xp']}",
        f"Raw Score: avg {summary['raw_score_avg']} | range [{summary['raw_score_min']}-{summary['raw_score_max']}]",
        f"Level Events: {summary['level_change_count']} in {days}d",
        "", "Component Breakdown (latest):",
    ] + comp_lines

    if events:
        display.append("")
        display.append("Level Events:")
        for ev in events[-10:]:
            display.append(f"  {ev.get('date')}: {ev.get('type')} "
                         f"(Level {ev.get('old_level', '?')} → {ev.get('new_level', '?')})")

    return {
        "display": "\n".join(display),
        "pillar": pillar, "summary": summary, "components": components,
        "daily_data": daily_data[-30:], "events": events,
        "sparkline": _make_sparkline(levels[-14:]),
    }


# ── Tool: get_level_history ──

def tool_get_level_history(args):
    """Timeline of all level/tier change events across all or one pillar."""
    days = min(args.get("days", 90), 365)
    pillar_filter = args.get("pillar", "").lower() if args.get("pillar") else None
    end_date = args.get("date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start_date = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    records = _fetch_range(start_date, end_date)
    if not records:
        return {"error": f"No character sheet data found between {start_date} and {end_date}."}

    all_events = []
    for rec in records:
        date = rec.get("date", "?")
        for ev in rec.get("level_events", []):
            if pillar_filter and ev.get("pillar") != pillar_filter and "character" not in ev.get("type", ""):
                continue
            all_events.append({**ev, "date": date})

    timeline = []
    for rec in records:
        entry = {"date": rec.get("date"), "character_level": rec.get("character_level")}
        for p in _PILLAR_ORDER:
            pdata = rec.get(f"pillar_{p}", {})
            entry[p] = {"level": pdata.get("level", 0), "tier": pdata.get("tier", "?")}
        timeline.append(entry)

    milestones = []
    for rec in records:
        if all((rec.get(f"pillar_{p}", {}).get("level", 0) >= 41) for p in _PILLAR_ORDER):
            milestones.append({"type": "all_discipline", "date": rec.get("date"),
                              "description": "🌟 All pillars at Discipline+ tier!"})
        if all((rec.get(f"pillar_{p}", {}).get("level", 0) >= 61) for p in _PILLAR_ORDER):
            milestones.append({"type": "all_mastery", "date": rec.get("date"),
                              "description": "👑 All pillars at Mastery+ — Project 40 Complete!"})

    display = [
        f"📜 Level History — {'All Pillars' if not pillar_filter else pillar_filter.capitalize()} ({days}d)",
        "━" * 50,
        f"Events: {len(all_events)} level changes in {len(records)} days",
    ]

    if all_events:
        display.append("")
        for ev in all_events:
            etype = ev.get("type", "")
            pillar = ev.get("pillar", "overall").capitalize()
            emoji = _PILLAR_EMOJI.get(ev.get("pillar", ""), "⭐")
            arrow = "⬆" if "up" in etype else "⬇"
            if "tier" in etype:
                display.append(f"  {ev['date']} {arrow} {emoji} {pillar}: "
                             f"{ev.get('old_tier')} → {ev.get('new_tier')}")
            elif "character" in etype:
                display.append(f"  {ev['date']} {arrow} ⭐ Overall: "
                             f"Level {ev.get('old_level')} → {ev.get('new_level')}")
            else:
                display.append(f"  {ev['date']} {arrow} {emoji} {pillar}: "
                             f"Level {ev.get('old_level')} → {ev.get('new_level')}")
    else:
        display.append("\nNo level change events in this period.")

    if milestones:
        display.append("")
        display.append("🏆 Milestones:")
        for ms in milestones[-5:]:
            display.append(f"  {ms['date']}: {ms['description']}")

    return {
        "display": "\n".join(display), "events": all_events,
        "milestones": milestones,
        "timeline_start": timeline[0] if timeline else None,
        "timeline_end": timeline[-1] if timeline else None,
        "days_covered": len(records),
    }


def _make_sparkline(values, width=14):
    if not values:
        return ""
    blocks = " ▁▂▃▄▅▆▇█"
    vals = [v for v in values if v is not None]
    if not vals:
        return ""
    mn, mx = min(vals), max(vals)
    rng = mx - mn if mx != mn else 1
    chars = []
    for v in values[-width:]:
        if v is None:
            chars.append("░")
        else:
            idx = min(8, int((v - mn) / rng * 8))
            chars.append(blocks[idx])
    return "".join(chars)


# ══════════════════════════════════════════════════════════════════════════════
# Phase 4 tools (v2.71.0): Rewards, Config Update, Protocol Recommendations
# ══════════════════════════════════════════════════════════════════════════════

import time
import boto3
import os as _os

REWARDS_PK   = USER_PREFIX + "rewards"
S3_BUCKET    = _os.environ.get("S3_BUCKET", "matthew-life-platform")  # PROD-2 Phase 2
_CS_USER_ID  = _os.environ.get("USER_ID", "matthew")                  # PROD-2 Phase 2
CS_CONFIG_KEY = f"config/{_CS_USER_ID}/character_sheet.json"          # PROD-2 Phase 2

_s3_client = None
def _get_s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client("s3", region_name="us-west-2")
    return _s3_client


# ── Tool: set_reward ──

def tool_set_reward(args):
    """Create or update a user-defined reward milestone."""
    title = args.get("title", "").strip()
    if not title:
        return {"error": "Reward title is required."}

    condition_type = args.get("condition_type", "").lower()
    valid_conditions = ["pillar_tier", "pillar_level", "character_level", "character_tier"]
    if condition_type not in valid_conditions:
        return {"error": f"condition_type must be one of: {valid_conditions}"}

    condition = {"type": condition_type}
    valid_pillars = ["sleep", "movement", "nutrition", "metabolic", "mind", "relationships", "consistency"]
    valid_tiers = ["Foundation", "Momentum", "Discipline", "Mastery", "Elite"]

    if condition_type in ("pillar_tier", "pillar_level"):
        pillar = args.get("pillar", "").lower()
        if pillar not in valid_pillars:
            return {"error": f"pillar must be one of: {valid_pillars}"}
        condition["pillar"] = pillar

    if condition_type in ("pillar_tier", "character_tier"):
        tier = args.get("tier", "").strip()
        if tier not in valid_tiers:
            return {"error": f"tier must be one of: {valid_tiers}"}
        condition["tier"] = tier

    if condition_type in ("pillar_level", "character_level"):
        level = args.get("level")
        if level is None or not (1 <= int(level) <= 100):
            return {"error": "level must be between 1 and 100."}
        condition["level"] = int(level)

    reward_id = args.get("reward_id") or f"reward_{int(time.time())}"
    now = datetime.now(timezone.utc).isoformat()
    description = args.get("description", "")

    item = {
        "pk": REWARDS_PK,
        "sk": f"REWARD#{reward_id}",
        "reward_id": reward_id,
        "title": title,
        "description": description,
        "condition": condition,
        "status": "active",
        "created_at": now,
        "triggered_at": None,
        "claimed_at": None,
    }

    try:
        table.put_item(Item=json.loads(json.dumps(item), parse_float=Decimal))
        return {
            "success": True,
            "reward_id": reward_id,
            "display": (
                f"\U0001f381 Reward created: {title}\n"
                f"   Condition: {_describe_condition(condition)}\n"
                f"   Status: active\n"
                f"   ID: {reward_id}"
            ),
        }
    except Exception as e:
        logger.error(f"[rewards] set_reward failed: {e}")
        return {"error": f"Failed to save reward: {e}"}


# ── Tool: get_rewards ──

def tool_get_rewards(args):
    """View all reward milestones with optional status filter."""
    status_filter = args.get("status", "").lower() or None
    valid_statuses = ["active", "triggered", "claimed"]

    try:
        resp = table.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={
                ":pk": REWARDS_PK,
                ":prefix": "REWARD#",
            },
        )
        items = resp.get("Items", [])
        while resp.get("LastEvaluatedKey"):
            resp = table.query(
                KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
                ExpressionAttributeValues={
                    ":pk": REWARDS_PK,
                    ":prefix": "REWARD#",
                },
                ExclusiveStartKey=resp["LastEvaluatedKey"],
            )
            items.extend(resp.get("Items", []))
    except Exception as e:
        logger.error(f"[rewards] get_rewards query failed: {e}")
        return {"error": f"Failed to fetch rewards: {e}"}

    rewards = [_d2f(i) for i in items]
    if status_filter:
        if status_filter not in valid_statuses:
            return {"error": f"status must be one of: {valid_statuses}"}
        rewards = [r for r in rewards if r.get("status") == status_filter]

    status_order = {"active": 0, "triggered": 1, "claimed": 2}
    rewards.sort(key=lambda r: (status_order.get(r.get("status", ""), 9), r.get("created_at", "")))

    if not rewards:
        return {
            "display": "\U0001f381 No rewards found" + (f" with status '{status_filter}'" if status_filter else "") + ".\n"
                       "Use set_reward to create reward milestones (e.g., 'when Sleep hits Mastery \u2192 buy new pillow').",
            "rewards": [],
            "count": 0,
        }

    lines = [f"\U0001f381 REWARD MILESTONES ({len(rewards)} total)", "\u2501" * 50]
    status_icons = {"active": "\u23f3", "triggered": "\U0001f389", "claimed": "\u2705"}
    for r in rewards:
        icon = status_icons.get(r.get("status", ""), "\u2753")
        lines.append(f"\n{icon} {r.get('title', '?')}")
        lines.append(f"   Condition: {_describe_condition(r.get('condition', {}))}")
        lines.append(f"   Status: {r.get('status', '?')}")
        if r.get("description"):
            lines.append(f"   Note: {r['description']}")
        if r.get("triggered_at"):
            lines.append(f"   Triggered: {r['triggered_at'][:10]}")
        if r.get("claimed_at"):
            lines.append(f"   Claimed: {r['claimed_at'][:10]}")

    return {"display": "\n".join(lines), "rewards": rewards, "count": len(rewards)}


def _describe_condition(condition):
    """Human-readable condition description."""
    ctype = condition.get("type", "")
    if ctype == "pillar_tier":
        return f"{condition.get('pillar', '?').capitalize()} reaches {condition.get('tier', '?')}"
    elif ctype == "pillar_level":
        return f"{condition.get('pillar', '?').capitalize()} reaches Level {condition.get('level', '?')}"
    elif ctype == "character_level":
        return f"Character Level reaches {condition.get('level', '?')}"
    elif ctype == "character_tier":
        return f"Character Tier reaches {condition.get('tier', '?')}"
    return str(condition)


# ── Tool: update_character_config ──

def tool_update_character_config(args):
    """View or update character sheet configuration in S3."""
    action = args.get("action", "view").lower()
    s3 = _get_s3()

    try:
        resp = s3.get_object(Bucket=S3_BUCKET, Key=CS_CONFIG_KEY)
        config = json.loads(resp["Body"].read())
    except Exception as e:
        return {"error": f"Failed to load config from S3: {e}"}

    if action == "view":
        pillars = config.get("pillars", {})
        leveling = config.get("leveling", {})
        effects = config.get("cross_pillar_effects", [])
        protocols = config.get("protocols", {})

        lines = ["\u2699\ufe0f CHARACTER SHEET CONFIG", "\u2501" * 50, ""]
        lines.append("PILLAR WEIGHTS:")
        for pname, pconf in sorted(pillars.items()):
            w = pconf.get("weight", 0)
            lines.append(f"  {pname.capitalize()}: {w:.0%}")

        lines.append(f"\nLEVELING: EMA \u03bb={leveling.get('ema_lambda')}, "
                     f"window={leveling.get('ema_window_days')}d, "
                     f"level up={leveling.get('level_up_streak_days')}d, "
                     f"down={leveling.get('level_down_streak_days')}d, "
                     f"tier up={leveling.get('tier_up_streak_days')}d, "
                     f"down={leveling.get('tier_down_streak_days')}d")

        lines.append(f"\nCROSS-PILLAR EFFECTS: {len(effects)}")
        for eff in effects:
            lines.append(f"  {eff.get('emoji', '')} {eff.get('name')}: {eff.get('condition')}")

        proto_pillars = [k for k in protocols if k != "_meta" and isinstance(protocols.get(k), dict)]
        proto_count = sum(len(recs) for k in proto_pillars for recs in protocols[k].values() if isinstance(recs, list))
        lines.append(f"\nPROTOCOL RECOMMENDATIONS: {proto_count} total across {len(proto_pillars)} pillars")

        return {"display": "\n".join(lines), "config": config}

    elif action == "update_weight":
        pillar = args.get("pillar", "").lower()
        weight = args.get("weight")
        if pillar not in config.get("pillars", {}):
            return {"error": f"Unknown pillar '{pillar}'. Valid: {list(config.get('pillars', {}).keys())}"}
        if weight is None or not (0 < float(weight) <= 1):
            return {"error": "weight must be between 0 and 1 (e.g., 0.20 for 20%)."}
        config["pillars"][pillar]["weight"] = float(weight)

    elif action == "update_target":
        pillar = args.get("pillar", "").lower()
        component = args.get("component", "")
        target_field = args.get("target_field", "")
        value = args.get("value")
        if pillar not in config.get("pillars", {}):
            return {"error": f"Unknown pillar '{pillar}'."}
        components = config["pillars"][pillar].get("components", {})
        if component not in components:
            return {"error": f"Unknown component '{component}' in {pillar}. Valid: {list(components.keys())}"}
        if not target_field:
            return {"error": "target_field is required (e.g., 'target_hours', 'target_pct', 'target_g')."}
        components[component][target_field] = float(value) if value is not None else None

    elif action == "update_leveling":
        field = args.get("field", "")
        value = args.get("value")
        valid_fields = ["ema_lambda", "ema_window_days", "level_up_streak_days",
                       "level_down_streak_days", "tier_up_streak_days", "tier_down_streak_days"]
        if field not in valid_fields:
            return {"error": f"Unknown leveling field '{field}'. Valid: {valid_fields}"}
        config["leveling"][field] = float(value) if "lambda" in field else int(value)

    else:
        return {"error": f"Unknown action '{action}'. Valid: view, update_weight, update_target, update_leveling"}

    config["_meta"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    try:
        s3.put_object(
            Bucket=S3_BUCKET, Key=CS_CONFIG_KEY,
            Body=json.dumps(config, indent=2, default=str),
            ContentType="application/json",
        )
        return {
            "success": True,
            "display": f"\u2705 Character config updated ({action}). Changes take effect on next character sheet compute.",
            "action": action,
        }
    except Exception as e:
        return {"error": f"Failed to write config to S3: {e}"}


# ── Reward evaluation (called by Daily Brief Lambda) ──

def evaluate_rewards(character_sheet, table_resource=None):
    """Check all active rewards against current character sheet. Returns newly triggered rewards."""
    tbl = table_resource or table
    try:
        resp = tbl.query(
            KeyConditionExpression="pk = :pk AND begins_with(sk, :prefix)",
            ExpressionAttributeValues={":pk": REWARDS_PK, ":prefix": "REWARD#"},
        )
        items = resp.get("Items", [])
    except Exception as e:
        logger.error(f"[rewards] evaluate_rewards query failed: {e}")
        return []

    triggered = []
    now = datetime.now(timezone.utc).isoformat()
    tier_order = ["Foundation", "Momentum", "Discipline", "Mastery", "Elite"]

    for item in items:
        if item.get("status") != "active":
            continue
        condition = _d2f(item.get("condition", {}))
        if isinstance(condition, str):
            try:
                condition = json.loads(condition)
            except Exception:
                continue

        met = False
        ctype = condition.get("type", "")
        if ctype == "character_level":
            met = character_sheet.get("character_level", 0) >= condition.get("level", 999)
        elif ctype == "character_tier":
            cur = character_sheet.get("character_tier", "Foundation")
            tgt = condition.get("tier", "Elite")
            met = (tier_order.index(cur) >= tier_order.index(tgt)
                   if cur in tier_order and tgt in tier_order else False)
        elif ctype == "pillar_level":
            p = condition.get("pillar", "")
            met = character_sheet.get(f"pillar_{p}", {}).get("level", 0) >= condition.get("level", 999)
        elif ctype == "pillar_tier":
            p = condition.get("pillar", "")
            cur = character_sheet.get(f"pillar_{p}", {}).get("tier", "Foundation")
            tgt = condition.get("tier", "Elite")
            met = (tier_order.index(cur) >= tier_order.index(tgt)
                   if cur in tier_order and tgt in tier_order else False)

        if met:
            try:
                tbl.update_item(
                    Key={"pk": item["pk"], "sk": item["sk"]},
                    UpdateExpression="SET #s = :s, triggered_at = :t",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": "triggered", ":t": now},
                )
                triggered.append({
                    "reward_id": item.get("reward_id", ""),
                    "title": _d2f(item.get("title", "")),
                    "description": _d2f(item.get("description", "")),
                    "condition": condition,
                })
            except Exception as e:
                logger.error(f"[rewards] failed to update reward {item.get('reward_id')}: {e}")

    return triggered


# ── Protocol recommendations helper ──

def get_protocol_recommendations(character_sheet, config):
    """Get protocol recs for pillars needing attention (below Discipline or dropped)."""
    protocols_config = config.get("protocols", {})
    if not protocols_config:
        return []

    events = character_sheet.get("level_events", [])
    dropped = {ev.get("pillar", "") for ev in events if "down" in ev.get("type", "")}

    recs = []
    for pillar in _PILLAR_ORDER:
        pdata = character_sheet.get(f"pillar_{pillar}", {})
        level = pdata.get("level", 1)
        tier = pdata.get("tier", "Foundation")

        if (pillar in dropped or level < 41) and pillar in protocols_config:
            pillar_protos = protocols_config[pillar]
            if isinstance(pillar_protos, dict) and tier in pillar_protos:
                tier_recs = pillar_protos[tier]
                if tier_recs:
                    recs.append({
                        "pillar": pillar,
                        "tier": tier,
                        "level": level,
                        "dropped": pillar in dropped,
                        "protocols": tier_recs[:2],
                    })
    return recs


def tool_get_character(args):
    """Unified character sheet dispatcher.
    Reads pre-computed data from SOURCE#character_sheet partition (written nightly
    by character-sheet-compute Lambda) — all views are fast DDB reads.
    """
    VALID_VIEWS = {
        "sheet":  tool_get_character_sheet,
        "pillar": tool_get_pillar_detail,
        "history": tool_get_level_history,
    }
    view = (args.get("view") or "sheet").lower().strip()
    if view not in VALID_VIEWS:
        return {"error": f"Unknown view '{view}'.", "valid_views": list(VALID_VIEWS.keys()),
                "hint": "'sheet' for overall Character Level + all 7 pillars, 'pillar' for deep dive into one pillar (requires pillar=), 'history' for level-up timeline."}
    return VALID_VIEWS[view](args)
