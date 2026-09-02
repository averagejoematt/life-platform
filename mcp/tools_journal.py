"""
Journal tools: entries, search, mood, insights, correlations — plus the ONE write
tool of this module, mark_journal_quote (#1568/ADR-142): the consent-per-line
publishable marker for "from the journal, in his words".
"""

import re
from datetime import datetime, timedelta, timezone

from boto3.dynamodb.conditions import Key
from common.pacific_time import pacific_now, pacific_today  # #2817: THE Pacific frame — DATE#/day keys name Pacific calendar days

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
    today = pacific_today()
    start = args.get("start_date", (pacific_now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    end = args.get("end_date", today)
    metric = args.get("metric", "all")  # mood|energy|stress|all

    items = _query_journal(start, end)

    if not items:
        return {"trend": [], "error": "No journal entries found for this period."}

    from health.flourishing import entry_channel  # #1572 channel provenance

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
    from health.flourishing import SIGNALS, ema_series, provenance_line

    days = max(7, min(365, int(args.get("days") or 90)))
    # default span=14: chosen against the observed median inter-entry gap
    # (~9d) in real journal density, not a calendar-day target — the EMA
    # below is observation-indexed (see ema_span_semantics in the payload),
    # so a span a bit past the typical gap keeps at least one prior entry
    # meaningfully weighted without collapsing to the single latest row.
    span = max(3, min(60, int(args.get("ema_span") or 14)))
    start = (pacific_now() - timedelta(days=days)).strftime("%Y-%m-%d")
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
        "ema_span_semantics": (
            "observation-indexed, not calendar-indexed: the span counts contributing "
            "ROWS (see days_with_rows), and gaps between journal entries are carried "
            "across rather than decayed by elapsed time — a sparse history keeps old "
            "readings influential far longer than the span number implies."
        ),
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
    from content import journal_quotes as jq  # bundled shared module (#781) — the pure gate
    from privacy import privacy_guard  # #1804: guard_version staleness — is_stale_draft/GUARD_VERSION

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
        # ADR-104 re-verification (2026-07-26 review): marks made before the day's
        # Notion ingestion are grounding=pending_ingestion and WITHHELD from the
        # public serve path. Each list call re-checks pendings against the now-
        # ingested entry: verbatim match → upgraded to verified (starts serving);
        # entry present but line absent → flagged grounding_mismatch (stays
        # withheld — unmark it or re-mark his exact words); entry still absent →
        # stays pending. The journal-interview close runs a list, so yesterday's
        # marks verify on the next session without a separate job.
        for i in items:
            if i.get("grounding") != "pending_ingestion":
                continue
            q_date, q_sk = i.get("date"), i.get("sk")
            if not q_date or not q_sk:
                continue
            entry_resp = table.query(
                KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}notion") & Key("sk").begins_with(f"DATE#{q_date}#journal"),
            )
            entries = entry_resp.get("Items", [])
            if not entries:
                continue  # not ingested yet — honestly still pending
            if any(jq.grounds_in(i.get("quote"), e.get("raw_text")) for e in entries):
                table.update_item(
                    Key={"pk": _quotes_pk(), "sk": q_sk},
                    UpdateExpression="SET grounding = :v",
                    ConditionExpression="grounding = :p",
                    ExpressionAttributeValues={":v": "verified", ":p": "pending_ingestion"},
                )
                i["grounding"] = "verified"
            else:
                i["grounding"] = "grounding_mismatch"  # advisory in this response; the stored row stays pending (withheld)
        return {
            "count": len(items),
            "quotes": [
                {
                    "sk": i.get("sk"),
                    "date": i.get("date"),
                    "quote": i.get("quote"),
                    "marked_at": i.get("marked_at"),
                    "grounding": i.get("grounding"),
                    # #1804: guard_version is stamped at mark time but was never read
                    # anywhere — surface staleness here (Matthew's private review
                    # surface) so he can see which marks pre-date the current taboo
                    # vocabulary. Informational only: list never withholds on this;
                    # the actual fail-closed re-screen runs at the public serve path
                    # (handle_journal_quotes in site_api_coach.py).
                    "guard_stale": privacy_guard.is_stale_draft(i.get("guard_version")),
                }
                for i in items
            ],
        }

    date = (args.get("date") or "").strip()
    quote = " ".join(str(args.get("quote") or "").split())
    # #1802: sk IS the revoke handle — an unmark that supplies it needs neither
    # date nor quote (the sk embeds the date: QUOTE#YYYY-MM-DD#hash).
    _sk_arg = str(args.get("sk") or "")
    if action == "unmark" and _sk_arg.startswith(jq.SK_PREFIX):
        date = date if _DATE_RE.match(date) else _sk_arg.split("#")[1]
    if not _DATE_RE.match(date):
        return {"error": "date is required (YYYY-MM-DD — the journal entry's day)."}
    if not quote and not (action == "unmark" and _sk_arg):
        return {"error": "quote is required — the exact verbatim line."}

    if action == "unmark":
        # #1802: revocation must be VERIFIED, never asserted. A DDB delete on a
        # missing key is a successful no-op, and the sk is a content hash — one
        # smart quote or trailing period between the typed text and the frozen
        # bytes means "revoked" while the line keeps serving. ALL_OLD proves the
        # delete; a miss answers honestly with that date's actual marked lines.
        sk = args.get("sk") or jq.quote_sk(date, quote)
        resp = table.delete_item(Key={"pk": _quotes_pk(), "sk": sk}, ReturnValues="ALL_OLD")
        if resp.get("Attributes"):
            return {"status": "revoked", "sk": sk, "note": "The line is private again; the public surface drops it on next fetch."}
        candidates = table.query(
            KeyConditionExpression=Key("pk").eq(_quotes_pk()) & Key("sk").begins_with(f"{jq.SK_PREFIX}{date}#"),
        ).get("Items", [])
        return {
            "status": "not_found",
            "sk": sk,
            "error": "NOTHING was revoked — no marked line matches that exact text/date (the sk is a hash of the frozen bytes; "
            "a punctuation or date mismatch derives a different key).",
            "marked_lines_for_date": [{"sk": c.get("sk"), "quote": c.get("quote")} for c in candidates],
            "how_to_revoke": "call again with the exact sk from the list above (sk is THE revoke handle).",
        }

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

    # Featured-slot stability (2026-07-26 review): an idempotent re-mark must not
    # refresh marked_at — featured_for_week keys on first-marked, and an overwrite
    # would rotate the home slot mid-week. Preserve the original timestamp.
    _prior = next((e for e in existing if e.get("sk") == sk), None)
    marked_at = (_prior or {}).get("marked_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # #1806: allowlist, not just strip/default-on-falsy — ANY value outside the
    # 3-value enum (including a string carrying taboo content, or a caller typo)
    # silently collapses to "journal" before it's ever written to DDB. Coercion,
    # not refusal: channel is metadata, not the marked content itself, so a bad
    # channel must never torpedo an otherwise-good, taboo-clean quote mark.
    _channel = (args.get("channel") or "journal").strip().lower()
    channel = _channel if _channel in jq.CHANNELS else "journal"
    table.put_item(
        Item={
            "pk": "USER#matthew#SOURCE#journal_quotes",  # literal (orphan-gate greppable); == _quotes_pk()
            "sk": sk,
            "date": date,
            "quote": quote,
            "marked_at": marked_at,
            "channel": channel,
            "grounding": grounding,
            "guard_version": privacy_guard.GUARD_VERSION,
        }
    )
    return {
        "status": "marked",
        "sk": sk,
        "date": date,
        "quote": quote,
        "grounding": grounding,
        "surface": "story hub archive + at most one featured line per week on home (/api/journal_quotes)",
        # #1802: the sk is THE revoke handle — the date+quote form silently derives
        # a different key on any byte drift from the frozen text.
        "revoke": f"mark_journal_quote(action='unmark', date='{date}', sk='{sk}') any time — consent is revocable; keep this sk.",
    }


# ── The on-tape claims ledger (#1841) ────────────────────────────────────────────
#
# The diary was a pipe INTO enrichment and never a loop: entries were full of implicit
# forecasts and not one of them entered the prediction machinery. This tool is the loop's
# hinge. The /vlog interviewer PROPOSES 0-3 falsifiable claims at the route-the-takeaways
# close and takes consent per claim; `lambdas/diary_claims.admit_claim` — pure, deterministic,
# ADR-105 — is the only thing that can ADMIT one. Admitted claims are written in the
# canonical PREDICTION# record shape and graded by the same daily coach-prediction-evaluator
# as every coach prediction. Nothing here grades, and nothing here calls an LLM.


def _claims_pk():
    from privacy import diary_claims as dc  # bundled shared module (#781) — the pure gate

    return f"{USER_PREFIX}{dc.SOURCE_NAME}"


def _claims_phase_stamp():
    """ADR-058 phase/cycle stamp, fail-soft (the coach_diary_reaction._stamp pattern)."""
    try:
        from experiment import phase_taxonomy

        return phase_taxonomy.experiment_stamp()
    except Exception:
        try:
            from common.constants import EXPERIMENT_PHASE_CURRENT

            return {"phase": EXPERIMENT_PHASE_CURRENT}
        except Exception:
            return {"phase": "experiment"}


def _read_claims():
    """Every claim in the ledger, newest stated-date first."""
    from privacy import diary_claims as dc

    items = []
    kwargs = {
        "KeyConditionExpression": Key("pk").eq(_claims_pk()) & Key("sk").begins_with(dc.SK_PREFIX),
        "ScanIndexForward": False,
    }
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    return [decimal_to_float(i) for i in items]


def tool_manage_diary_claims(args):
    """The on-tape claims ledger: log consented claims, list what's due, close the loop."""
    from common.numeric import floats_to_decimal  # #1207/D5: the ONE float->Decimal walker
    from privacy import diary_claims as dc  # bundled shared module (#781) — the pure gate

    action = (args.get("action") or "due").strip().lower()
    today = (args.get("today") or pacific_today()).strip()
    if not _DATE_RE.match(today):
        return {"error": "today must be YYYY-MM-DD."}

    # ── due: the /vlog step-0 priming list (AC3) ─────────────────────────────────
    if action == "due":
        records = _read_claims()
        due = dc.due_for_grading(records, today)
        return {
            "count": len(due),
            "due": due,
            "track_record": dc.track_record(records),
            "how_to_use": (
                "Call these back ON TAPE, in his own words, before asking anything new — read the claim "
                "verbatim, then ask what he thinks happened BEFORE revealing the verdict. A claim whose "
                "machine_verdict is 'still pending' is worth raising anyway: the deadline he named has "
                "landed even if the evaluator's domain-minimum window has not."
            ),
            "then": "mark each one worked with action='called_back' so it stops resurfacing next session.",
        }

    # ── list: the whole ledger + track record (AC4) ──────────────────────────────
    if action == "list":
        records = _read_claims()
        status_filter = (args.get("status") or "").strip().lower() or None
        rows = [r for r in records if not status_filter or r.get("status") == status_filter]
        return {
            "count": len(rows),
            "track_record": dc.track_record(records),
            "store": "USER#matthew#SOURCE#diary_claims / PREDICTION# — graded by the same evaluator as coach predictions",
            "claims": [
                {
                    "claim_id": r.get("claim_id"),
                    "sk": r.get("sk"),
                    "stated_date": r.get("stated_date"),
                    "claim": r.get("claim_natural"),
                    "criterion": r.get("criterion"),
                    "grade_by": r.get("grade_by"),
                    "confidence": r.get("confidence"),
                    "status": r.get("status"),
                    "outcome": r.get("outcome"),
                    "outcome_date": r.get("outcome_date"),
                    "source_sk": r.get("source_sk"),
                    "called_back_at": r.get("called_back_at"),
                }
                for r in rows
            ],
        }

    # ── called_back: close the on-tape loop ──────────────────────────────────────
    if action == "called_back":
        sk = str(args.get("sk") or "")
        if not sk.startswith(dc.SK_PREFIX):
            return {"error": f"sk is required and must start with {dc.SK_PREFIX} — use the sk from action='due'."}
        resp = table.update_item(
            Key={"pk": _claims_pk(), "sk": sk},
            UpdateExpression="SET called_back_at = :t",
            ConditionExpression="attribute_exists(sk)",
            ExpressionAttributeValues={":t": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
            ReturnValues="ALL_NEW",
        )
        return {"status": "called_back", "sk": sk, "claim": (resp.get("Attributes") or {}).get("claim_natural")}

    if action != "log":
        return {"error": f"Unknown action '{action}'.", "valid_actions": ["due", "log", "list", "called_back"]}

    # ── log: LLM proposed, CODE admits (AC1/AC2) ─────────────────────────────────
    stated_date = str(args.get("date") or "").strip()
    source_sk = str(args.get("source_sk") or "").strip()
    candidates = args.get("claims")
    if not isinstance(candidates, list):
        return {"error": "claims must be a list of 0-3 candidate claim objects."}
    if len(candidates) > dc.MAX_CLAIMS_PER_SESSION:
        return {
            "error": f"refused: {len(candidates)} claims offered, the cap is {dc.MAX_CLAIMS_PER_SESSION} per session. "
            "A close that mines a diary for forecasts is content extraction, not an interview."
        }

    # The entry pointer must name a REAL video-diary entry. A claim pointing at nothing is
    # uncitable on tape, and #1568's lesson is that a write which cannot be grounded is a
    # write that should not happen. Absent ingestion is reported honestly, not guessed past.
    entry_resp = table.query(
        KeyConditionExpression=Key("pk").eq(f"{USER_PREFIX}notion") & Key("sk").eq(source_sk),
    )
    if not entry_resp.get("Items"):
        return {
            "error": f"refused: no journal entry at sk {source_sk!r} (ADR-104 grounding).",
            "why": "Notion ingestion is hourly — right after a session the entry may not be in DDB yet.",
            "fix": "Re-run the close once the entry has ingested; nothing is written in the meantime.",
        }

    stamp = _claims_phase_stamp()
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    admitted, refused = [], []
    for candidate in candidates:
        ok, reason, normalized = dc.admit_claim(candidate, stated_date, source_sk)
        if not ok:
            refused.append({"claim": (candidate or {}).get("claim") if isinstance(candidate, dict) else None, "reason": reason})
            continue
        record = dc.build_claim_record(normalized, stated_date, source_sk, now_iso)
        # boto3 rejects native float — the ONE canonical walker (#1207/D5), never a fork.
        table.put_item(
            Item=floats_to_decimal(
                # literal (orphan-gate greppable); == _claims_pk()
                {**stamp, **record, "pk": "USER#matthew#SOURCE#diary_claims"}
            )
        )
        admitted.append(
            {
                "claim_id": record["claim_id"],
                "sk": record["sk"],
                "claim": record["claim_natural"],
                "criterion": record["criterion"],
                "grade_by": record["grade_by"],
                "eval_type": record["evaluation"]["type"],
                "metric": record["metric"],
            }
        )

    return {
        "status": "logged" if admitted else "nothing_admitted",
        "admitted": admitted,
        "refused": refused,
        "contract": (
            "The interviewer proposes; this gate admits. A refusal is not a failure to hide — say it on tape "
            "('that one isn't gradable, and here's why') and move on (ADR-105)."
        ),
        "graded_by": "the daily coach-prediction-evaluator, on the same code and the same statuses as every coach prediction",
        "privacy": "private by default — no public surface reads this partition.",
    }
