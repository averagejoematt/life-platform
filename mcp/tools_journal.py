"""
Journal tools: entries, search, mood, insights, correlations — plus the ONE write
tool of this module, mark_journal_quote (#1568/ADR-142): the consent-per-line
publishable marker for "from the journal, in his words".
"""

import re
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key

from mcp.config import USER_PREFIX, table
from mcp.core import decimal_to_float

# R22-SCI-02 (#820): fit-quality floor for the sentiment-trajectory regressions below.
# r² < 0.09 is |r| < 0.3 — the same "below moderate" floor already used as the weak/moderate
# correlation boundary in tools_habits.py (habit-lever interpretation) and tools_training.py
# (correlation interpretation). ADR-105 rule 1: every statistical claim carries its fit quality.
_TRAJECTORY_LOW_FIT_R2 = 0.09

# ── Journal query helper ──


def _query_journal(start_date, end_date, template=None):
    """Query journal entries from DynamoDB. Returns list of items."""
    from mcp.core import _apply_phase_filter  # ADR-058

    pk = f"{USER_PREFIX}notion"
    # ADR-058: longitudinal/clinical archive — cross-phase by design (owner decision 2026-06-06)
    kwargs = _apply_phase_filter(
        {
            "KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start_date}#journal", f"DATE#{end_date}#journal#~"),
            "ScanIndexForward": True,
        },
        include_pilot=True,
    )
    items = []
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    # Filter to journal items only
    items = [i for i in items if "#journal#" in i.get("sk", "")]

    # Optional template filter
    if template:
        template_lower = template.lower().replace(" ", "_").replace("-", "_")
        alias_map = {
            "morning": "morning",
            "evening": "evening",
            "weekly": "weekly",
            "weekly_reflection": "weekly",
            "stressor": "stressor",
            "health_event": "health",
            "health": "health",
            "video_diary": "video_diary",  # #1572 Diary-Studio transcript channel
            "solo_recording": "solo_recording",  # #1573 local-Whisper solo transcript channel
        }
        sk_suffix = alias_map.get(template_lower, template_lower)
        items = [i for i in items if f"#journal#{sk_suffix}" in i.get("sk", "")]

    return [decimal_to_float(i) for i in items]


def _get_mood_trend(args):
    """Mood/energy/stress scores over time with enriched signals."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    start = args.get("start_date", (datetime.now(timezone.utc) - timedelta(days=30)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)
    metric = args.get("metric", "all")  # mood|energy|stress|all

    items = _query_journal(start, end)

    if not items:
        return {"trend": [], "error": "No journal entries found for this period."}

    from flourishing import entry_channel  # #1572 channel provenance

    # Build daily scores (prefer enriched, fall back to structured)
    daily = {}  # date -> {mood, energy, stress, themes, sentiment, channels}
    for item in items:
        date = item.get("date")
        if not date:
            continue
        if date not in daily:
            daily[date] = {"date": date, "entries": 0}

        daily[date]["entries"] += 1
        template = item.get("template", "")

        # #1572: record which capture channel(s) contributed to the day so the
        # trend can be read by channel (video_diary transcript vs typed journal).
        ch = entry_channel(item)
        chans = daily[date].setdefault("channels", [])
        if ch not in chans:
            chans.append(ch)

        # Mood: enriched > morning_mood > day_rating
        mood = item.get("enriched_mood") or item.get("morning_mood") or item.get("day_rating")
        if mood and ("mood" not in daily[date] or template == "Evening"):
            daily[date]["mood"] = float(mood) if mood else None

        # Energy: enriched > morning_energy > energy_eod
        energy = item.get("enriched_energy") or item.get("morning_energy") or item.get("energy_eod")
        if energy and ("energy" not in daily[date] or template == "Evening"):
            daily[date]["energy"] = float(energy) if energy else None

        # Stress: enriched > stress_level
        stress = item.get("enriched_stress") or item.get("stress_level")
        if stress and ("stress" not in daily[date] or template == "Evening"):
            daily[date]["stress"] = float(stress) if stress else None

        # Themes and sentiment from enrichment
        themes = item.get("enriched_themes", [])
        if themes:
            daily[date].setdefault("themes", []).extend(themes)

        sentiment = item.get("enriched_sentiment")
        if sentiment:
            daily[date]["sentiment"] = sentiment

        quote = item.get("enriched_notable_quote")
        if quote:
            daily[date]["notable_quote"] = quote

    trend = sorted(daily.values(), key=lambda x: x["date"])

    # Compute rolling 7-day averages
    for metric_name in ["mood", "energy", "stress"]:
        values = [(i, d.get(metric_name)) for i, d in enumerate(trend) if d.get(metric_name) is not None]
        for idx, val in values:
            window = [v for j, v in values if idx - 6 <= j <= idx]
            if window:
                trend[idx][f"{metric_name}_7d_avg"] = round(sum(window) / len(window), 2)

    # Summary stats
    summary = {}
    for metric_name in ["mood", "energy", "stress"]:
        vals = [d.get(metric_name) for d in trend if d.get(metric_name) is not None]
        if vals:
            summary[metric_name] = {
                "avg": round(sum(vals) / len(vals), 2),
                "min": min(vals),
                "max": max(vals),
                "latest": vals[-1],
                "days_tracked": len(vals),
            }
            # Trend direction (first half vs second half)
            if len(vals) >= 4:
                mid = len(vals) // 2
                first_avg = sum(vals[:mid]) / mid
                second_avg = sum(vals[mid:]) / (len(vals) - mid)
                delta = second_avg - first_avg
                if metric_name == "stress":
                    # For stress, down is good
                    direction = "improving" if delta < -0.3 else "worsening" if delta > 0.3 else "stable"
                else:
                    direction = "improving" if delta > 0.3 else "declining" if delta < -0.3 else "stable"
                summary[metric_name]["trend_direction"] = direction
                summary[metric_name]["half_delta"] = round(delta, 2)

    # Top recurring themes
    all_themes = []
    for d in trend:
        all_themes.extend(d.get("themes", []))
    theme_counts = {}
    for t in all_themes:
        theme_counts[t] = theme_counts.get(t, 0) + 1
    top_themes = sorted(theme_counts.items(), key=lambda x: -x[1])[:5]

    # #1572/#1573: which capture channels appear across the window + a note when
    # transcript channels (video_diary / solo_recording) are mixed in (the same
    # enrichment pass codes all of them).
    channels_present = sorted({c for d in trend for c in d.get("channels", [])})

    result = {
        "trend": trend,
        "summary": summary,
        "top_themes": [{"theme": t, "count": c} for t, c in top_themes],
        "days_with_entries": len(trend),
        "date_range": f"{start} to {end}",
        "channels_present": channels_present,
    }
    _TRANSCRIPT_CHANNEL_LABELS = {"video_diary": "video-diary", "solo_recording": "solo-recording"}
    transcript_channels = [c for c in channels_present if c in _TRANSCRIPT_CHANNEL_LABELS]
    if transcript_channels:
        labels = ", ".join(_TRANSCRIPT_CHANNEL_LABELS[c] for c in transcript_channels)
        result["channel_note"] = (
            f"Includes transcript entries ({labels}), coded by the "
            "same enrichment pass as typed journal. Per-day 'channels' lists what contributed."
        )

    # Filter to requested metric if not "all"
    if metric != "all" and metric in summary:
        result["summary"] = {metric: summary[metric]}

    return result


def tool_get_mood(args):
    """Unified mood/state-of-mind dispatcher.
    mood_trend = subjective journal-derived mood; state_of_mind = Apple Health HWF valence.
    """
    from mcp.tools_lifestyle import _get_state_of_mind_trend

    VALID_VIEWS = {
        "trend": _get_mood_trend,
        "state_of_mind": _get_state_of_mind_trend,
    }
    view = (args.get("view") or "trend").lower().strip()
    if view not in VALID_VIEWS:
        return {
            "error": f"Unknown view '{view}'.",
            "valid_views": list(VALID_VIEWS.keys()),
            "hint": "'trend' for journal-derived mood/energy/stress scores, 'state_of_mind' for Apple Health How We Feel valence data.",
        }
    return VALID_VIEWS[view](args)


# ── BS-MP2: Journal Sentiment Trajectory ─────────────────────────────────


def tool_get_flourishing_trend(args):
    """#1403: EMA trends per PERMA signal from SOURCE#flourishing — the daily
    LLM-coded projection of journal enrichment (values/gratitude/flow/growth/
    ownership/social). Every number is a language model's reading of prose, and
    the payload says so (provenance per ADR-104)."""
    from flourishing import SIGNALS, ema_series, provenance_line

    days = max(7, min(365, int(args.get("days") or 90)))
    span = max(3, min(60, int(args.get("ema_span") or 14)))
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}flourishing") & Key("sk").gte(f"DATE#{start}"),
        ScanIndexForward=True,
    )
    rows = [decimal_to_float(r) for r in resp.get("Items", [])]
    trends = {}
    for sig in SIGNALS:
        series = [(r.get("date") or str(r.get("sk", "")).replace("DATE#", "")[:10], r.get(sig)) for r in rows if r.get(sig) is not None]
        if not series:
            trends[sig] = {"n": 0, "ema": None, "latest": None}
            continue
        trends[sig] = {
            "n": len(series),
            "ema": ema_series([v for _, v in series], span=span),
            "latest": {"date": series[-1][0], "value": series[-1][1]},
        }
    model = rows[-1].get("enrichment_model") if rows else None
    # #1572: capture channels that fed the window's rows, so the PERMA trend can
    # be read by channel (video_diary transcript vs typed journal).
    channels_present = sorted({c for r in rows for c in (r.get("channels") or [])})
    return {
        "window_days": days,
        "ema_span": span,
        "days_with_rows": len(rows),
        "signals": trends,
        "channels_present": channels_present,
        "provenance": provenance_line(model),
        "_framing": (
            "These are inputs you influence, not a verdict on you. A low stretch is "
            "information about conditions (sleep, load, season), never identity — and "
            "if reviewing them feels heavy, a tracking break is a sanctioned move."
        ),
    }


# ── #1568 (ADR-142): mark_journal_quote — the consent-per-line publish marker ──
#
# The ONLY write path of the verbatim-public quote channel. Nothing is ever
# quotable without an explicit per-line mark made through here (approved=true is
# a hard argument, never inferred), and the ELENA_PREQUEL_BRIEF taboo gate
# (lambdas/journal_quotes.find_mark_violations — substances / family-specifics /
# age / private events / real names) runs fail-closed BEFORE any write. The
# chronicle's never-quote rule is untouched: this channel is a separate,
# owner-consented lane, not a loosening of deep-background.

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _quotes_pk():
    return f"{USER_PREFIX}journal_quotes"


def tool_mark_journal_quote(args):
    """Mark / unmark / list explicitly-publishable verbatim journal lines."""
    import journal_quotes as jq  # bundled shared module (#781) — the pure gate

    action = (args.get("action") or "mark").strip().lower()
    if action == "list":
        items = []
        kwargs = {
            "KeyConditionExpression": Key("pk").eq(_quotes_pk()) & Key("sk").begins_with(jq.SK_PREFIX),
            "ScanIndexForward": False,
        }
        while True:
            resp = table.query(**kwargs)
            items.extend(resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        items = [decimal_to_float(i) for i in items]
        return {
            "count": len(items),
            "quotes": [{"sk": i.get("sk"), "date": i.get("date"), "quote": i.get("quote"), "marked_at": i.get("marked_at")} for i in items],
        }

    date = (args.get("date") or "").strip()
    quote = " ".join(str(args.get("quote") or "").split())
    if not _DATE_RE.match(date):
        return {"error": "date is required (YYYY-MM-DD — the journal entry's day)."}
    if not quote:
        return {"error": "quote is required — the exact verbatim line."}

    if action == "unmark":
        sk = args.get("sk") or jq.quote_sk(date, quote)
        table.delete_item(Key={"pk": _quotes_pk(), "sk": sk})
        return {"status": "revoked", "sk": sk, "note": "The line is private again; the public surface drops it on next fetch."}

    if action != "mark":
        return {"error": f"Unknown action '{action}'.", "valid_actions": ["mark", "unmark", "list"]}

    # 1) Consent is explicit, per line, never inferred (AC1).
    if args.get("approved") is not True:
        return {
            "error": "refused: approved must be exactly true — Matthew must explicitly mark THIS line publishable.",
            "consent_contract": "Nothing is ever quotable without an explicit per-line mark (ADR-142).",
        }
    if len(quote) > jq.MAX_QUOTE_CHARS:
        return {"error": f"refused: quote exceeds {jq.MAX_QUOTE_CHARS} chars — a pull-quote is a line, not a passage."}

    # 2) The mark-time taboo gate (AC3) — fail-closed, deterministic.
    violations = jq.find_mark_violations(quote)
    if violations:
        return {
            "error": "refused: this line touches the mark-time taboo list and can never be nominated or published.",
            "violations": [{"category": c, "term": t} for c, t in violations],
            "policy": "ELENA_PREQUEL_BRIEF abstract/omit list, enforced in code (lambdas/journal_quotes.py).",
        }

    # 3) ADR-104 grounding: the line must be his actual words from that day's entry.
    #    Entries land via the hourly Notion ingestion; right after an interview the
    #    entry may not be in DDB yet — that's recorded honestly, never faked.
    entry_resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}notion") & Key("sk").begins_with(f"DATE#{date}#journal"),
    )
    entries = entry_resp.get("Items", [])
    if entries:
        if not any(jq.grounds_in(quote, e.get("raw_text")) for e in entries):
            return {
                "error": "refused: the line does not appear verbatim in that day's journal entry (ADR-104 grounding). "
                "Quote his exact words or don't quote at all.",
            }
        grounding = "verified"
    else:
        grounding = "pending_ingestion"

    # 4) The per-day nomination cap (0–2 lines per close).
    existing = table.query(
        KeyConditionExpression=Key("pk").eq(_quotes_pk()) & Key("sk").begins_with(f"{jq.SK_PREFIX}{date}#"),
    ).get("Items", [])
    sk = jq.quote_sk(date, quote)
    if len([e for e in existing if e.get("sk") != sk]) >= jq.MAX_QUOTES_PER_DAY:
        return {"error": f"refused: {jq.MAX_QUOTES_PER_DAY} lines are already marked for {date} — the cap is 0–2 per entry."}

    marked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    table.put_item(
        Item={
            "pk": "USER#matthew#SOURCE#journal_quotes",  # literal (orphan-gate greppable); == _quotes_pk()
            "sk": sk,
            "date": date,
            "quote": quote,
            "marked_at": marked_at,
            "channel": (args.get("channel") or "journal").strip() or "journal",
            "grounding": grounding,
            "guard_version": __import__("privacy_guard").GUARD_VERSION,
        }
    )
    return {
        "status": "marked",
        "sk": sk,
        "date": date,
        "quote": quote,
        "grounding": grounding,
        "surface": "story hub archive + at most one featured line per week on home (/api/journal_quotes)",
        "revoke": "mark_journal_quote(action='unmark', date=…, quote=…) any time — consent is revocable.",
    }
