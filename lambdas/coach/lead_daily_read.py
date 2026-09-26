"""lead_daily_read.py — the head coach's DAILY grounded lead read (#4188, epic #4182).

THE DEFECT
  The coaching door's top slot had no daily read to show. `/api/coach/eli_marsh.daily`
  was `null` (the CC-08 reflection batch covers the seven operational coaches only) and
  `stance.headline_read` was `""`, so the door opened on the integrator's WEEKLY call —
  on a Friday that meant a Monday read, 4.6 days old and wrong in two figures by then.

THE SHAPE
  Once per daily brief, after the domain coaches, the lead writes <= 90 words ABOUT
  Matthew (third person) from facts this module computes deterministically out of the
  SAME gathered `data` the brief already holds (ADR-062: the model never does the math).
  Every figure the text may use is listed in a `cited` block — `{metric, value, as_of,
  source_field}` — and the text is refused unless every number token in it appears in
  that block (ADR-104/105). The row is written to `COACH#eli_marsh / LEAD_DAILY#{date}`
  and served as `lead_daily` by /api/coaching-dashboard and /api/coach/eli_marsh.

WHY NOT `OUTPUT#{date}#daily`
  The brief for this work assumed the coach-profile serializer reads such a row as
  `daily`. Verified false: `daily` comes from generated/coach_daily.json. And an OUTPUT#
  row under the lead would be picked up by every OUTPUT# reader (recent outputs, recap
  cards, the podcast, the observatory) as if it were a domain coach's narrative. A
  distinct sk prefix keeps this record to the two readers that ask for it.

THE ORDER (cost first, then honesty)
  1. budget — `budget_guard.allow("coach_narrative")` BEFORE any read or call (band 2,
     the same feature the domain coaches' daily commentary runs under);
  2. facts — deterministic; too few facts -> no call at all;
  3. one Haiku call (plus at most one regeneration);
  4. the cited-number post-check + the deterministic grounding classes (numbers,
     dates, freshness) — fail-closed;
  5. the N-06 quality gate (`ai_calls._enforce_quality_gate`, regenerate-or-hold) — its
     regenerations must re-pass step 4;
  6. write, with the measured token usage and estimated cost ON the row, because inside
     the daily-brief Lambda the platform's `LambdaFunction` cost dimension cannot tell
     this call from the rest of the brief.
  A hold writes nothing: the door falls back to its existing chain, and says so.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

LEAD_ID = "eli_marsh"  # persona_registry.LEAD_PERSONA_ID — pinned equal in the tests
PK = f"COACH#{LEAD_ID}"
SK_PREFIX = "LEAD_DAILY#"
BUDGET_FEATURE = "coach_narrative"
MODEL = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")
MAX_WORDS = 90
MAX_TOKENS = 260
MIN_FACTS = 3  # fewer than this and there is nothing worth a call

# The prompt, verbatim in the PR body. Third person, reader-facing, no arithmetic.
LEAD_PROMPT = (
    "You write the one short daily read that opens the coaching page of a public health-experiment "
    "site. You are Dr. Eli Marsh, the head coach. You write ABOUT Matthew, in the third person "
    '("he"), for his friends and family.\n'
    "Rules you must obey:\n"
    f"- {MAX_WORDS} words at most. One plain paragraph. No preamble, no sign-off, no headings, no lists.\n"
    "- Your first sentence is the finding or the ask: the single most important thing about where he stands today.\n"
    "- Use ONLY the facts you are given. Every number you write must appear exactly as it is written in the facts. "
    "Do no arithmetic: never add, subtract, average, convert or re-round a number.\n"
    '- Write dates in words exactly as the facts give them (for example "Friday, September 25"), never as digits like 2026-09-25.\n'
    "- Plain words, no jargon or abbreviations: say heart-rate variability and resting heart rate, never HRV, RHR, TDEE, "
    "EWMA or CI.\n"
    "- A rate marked provisional is an early estimate; say so if you use it.\n"
    "- Correlative only: never claim one thing caused another.\n"
    "- No medical advice, no diagnosis, no supplement or drug suggestions.\n"
    "- If a metric is not in the facts, do not mention it."
)


# ── dates in words ───────────────────────────────────────────────────────────


def date_in_words(iso: Optional[str]) -> str:
    """'2026-09-25' -> 'Friday, September 25'. '' for anything unparseable."""
    from common.pacific_time import parse_day_key  # #3609: the one calendar-day parser

    d = parse_day_key(str(iso or "")[:10])
    if d is None:
        return ""
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}"


def _fmt(v: Any, places: int = 1) -> Optional[str]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f"{abs(f):.{places}f}" if places else str(int(round(abs(f))))


def _cite(out: list, metric: str, value: Optional[str], as_of: Optional[str], source_field: str) -> None:
    if value is None or value == "":
        return
    out.append({"metric": metric, "value": value, "as_of": as_of or "", "source_field": source_field})


# ── the facts: deterministic, from the brief's own gathered data ────────────


def build_cited(data: dict, profile: dict, vitals: dict, today: str) -> list:
    """The `cited` block — every figure the lead read may use, pre-computed here.

    Absence is absence (ADR-104): a metric with no reading is left out, never zeroed.
    Values are the exact display strings the prompt shows, so the post-check can match
    the text against them token for token.
    """
    from ai.ai_context import build_experiment_phase_context  # #1086: the ONE phase claim, never re-derived here
    from common.constants import EXPERIMENT_BASELINE_WEIGHT_LBS

    data = data or {}
    profile = profile or {}
    vitals = vitals or {}
    cited: list = []
    pctx = build_experiment_phase_context(profile, today)
    started = str(pctx.get("start_date") or "")
    if not pctx.get("pre_start") and int(pctx.get("days_in") or 0) > 0:
        _cite(cited, "day of the experiment", str(int(pctx["days_in"])), today, "ai_context.build_experiment_phase_context.days_in")
        _cite(cited, "experiment start date", date_in_words(started), started, "profile.journey_start_date")

    wr = data.get("weight_recency") or {}
    current = wr.get("current_weight_lb") if wr.get("current_weight_lb") is not None else data.get("latest_weight")
    current_as_of = wr.get("current_weight_as_of") or ""
    start_wt = pctx.get("start_weight") or EXPERIMENT_BASELINE_WEIGHT_LBS
    if current is not None:
        _cite(cited, "latest weigh-in (lb)", _fmt(current), current_as_of, "withings.weight_lbs")
        if current_as_of:
            _cite(cited, "latest weigh-in date", date_in_words(current_as_of), current_as_of, "withings.sk")
        _cite(cited, "starting weight (lb)", _fmt(start_wt), started, "profile.journey_start_weight_lbs")
        change = round(float(start_wt) - float(current), 1)
        label = "lost since the start (lb)" if change >= 0 else "gained since the start (lb)"
        _cite(cited, label, _fmt(change), current_as_of, "journey.lost_lbs")

    rate = data.get("weekly_rate_lbs")
    if rate is not None:
        direction = "loss" if float(rate) <= 0 else "gain"
        _cite(cited, f"weekly {direction} rate (lb per week)", _fmt(rate), data.get("date"), "computed_metrics.weekly_rate_lbs")
        lo, hi = data.get("weekly_rate_ci_low"), data.get("weekly_rate_ci_high")
        if lo is not None and hi is not None:
            a, b = sorted([abs(float(lo)), abs(float(hi))])
            _cite(
                cited,
                f"weekly {direction} rate, likely range (lb per week)",
                f"{a:.1f} to {b:.1f}",
                data.get("date"),
                "computed_metrics.weekly_rate_ci",
            )
        _cite(
            cited,
            "rate status",
            "provisional" if data.get("rate_provisional") else "settled",
            data.get("date"),
            "computed_metrics.rate_provisional",
        )

    _cite(
        cited,
        "morning recovery score (0-100, Whoop)",
        _fmt(vitals.get("recovery_pct"), 0),
        vitals.get("recovery_as_of"),
        "whoop.recovery_score",
    )
    _cite(cited, "heart-rate variability (ms)", _fmt(vitals.get("hrv_ms"), 0), vitals.get("recovery_as_of"), "whoop.hrv")
    _cite(
        cited,
        "resting heart rate (beats per minute)",
        _fmt(vitals.get("rhr_bpm"), 0),
        vitals.get("recovery_as_of"),
        "whoop.resting_heart_rate",
    )
    _cite(cited, "sleep last night (hours)", _fmt(vitals.get("sleep_hours")), vitals.get("sleep_as_of"), "whoop.sleep_duration_hours")

    mf = data.get("macrofactor") or {}
    protein = mf.get("total_protein_g")
    if protein is not None:
        _cite(cited, "protein eaten (grams)", _fmt(protein, 0), data.get("date"), "macrofactor.total_protein_g")
        floor = profile.get("protein_floor_g")
        if floor is not None:
            _cite(cited, "protein floor (grams a day)", _fmt(floor, 0), data.get("date"), "profile.protein_floor_g")
            met = float(protein) >= float(floor)
            _cite(
                cited,
                "protein floor met",
                "yes" if met else "no",
                data.get("date"),
                "macrofactor.total_protein_g vs profile.protein_floor_g",
            )
    return cited


def facts_text(cited: list, data_through: str) -> str:
    """The user turn: one line per cited fact, dates in words."""
    lines = [f"Facts (data through {date_in_words(data_through) or data_through}):"]
    for c in cited:
        when = date_in_words(c.get("as_of"))
        lines.append(f"- {c['metric']}: {c['value']}" + (f" (as of {when})" if when else ""))
    return "\n".join(lines)


# ── the hard post-check ─────────────────────────────────────────────────────


def _cited_numbers(cited: list, data_through: str) -> set:
    from ai.grounded_generation import numbers_in_text

    return numbers_in_text(facts_text(cited, data_through))


def uncited_numbers(text: str, cited: list, data_through: str = "") -> list:
    """Every number token in `text` that the cited block (as the model was shown it)
    does not carry — sorted. Exact match: a rounding or a computed figure is uncited."""
    from ai.grounded_generation import numbers_in_text

    allowed = _cited_numbers(cited, data_through)
    return sorted(n for n in numbers_in_text(text or "") if n not in allowed)


def _grounding_findings(text: str, cited: list, data_through: str, today: str) -> list:
    """The registered grounding surface (tests/grounding_wiring.py): numbers, dates,
    freshness — against an allow-list built from exactly what the model was shown."""
    from ai import grounded_generation as gg
    from common.constants import EXPERIMENT_START_DATE

    shown = facts_text(cited, data_through)
    return gg.grounding_findings(
        text,
        allowed=gg.allowed_numbers(shown),
        allowed_dates=gg.allowed_dates(shown),
        generation_date_iso=today,
        start_date_iso=EXPERIMENT_START_DATE,
        number_tolerance=gg.NUMBER_TOLERANCE_EXACT,
    )


def check(text: Optional[str], cited: list, data_through: str, today: str) -> list:
    """Reasons to refuse `text` — [] means it may ship. Fail-closed."""
    t = (text or "").strip()
    if not t:
        return ["empty"]
    reasons = [f"uncited_number:{n:g}" for n in uncited_numbers(t, cited, data_through)]
    if len(t.split()) > MAX_WORDS:
        reasons.append(f"over_{MAX_WORDS}_words")
    reasons += [f"grounding:{f.get('type', 'finding')}" for f in _grounding_findings(t, cited, data_through, today)]
    return reasons


# ── generation ──────────────────────────────────────────────────────────────


def generate(cited: list, data_through: str, invoke: Callable, correction: str = "") -> tuple:
    """(text, usage) from ONE model call. `invoke` is bedrock_client.invoke in production."""
    user = facts_text(cited, data_through) + "\n\nWrite the lead read."
    if correction:
        user += "\n\nYour previous draft was refused: " + correction
    resp = invoke(
        {"model": MODEL, "max_tokens": MAX_TOKENS, "system": LEAD_PROMPT, "messages": [{"role": "user", "content": user}]}, model_name=MODEL
    )
    text = ""
    for block in (resp or {}).get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            text = block["text"].strip()
            break
    return text, dict((resp or {}).get("usage") or {})


def _cost(usages: list) -> dict:
    from ai import bedrock_client

    model_id = bedrock_client.resolve_model_id(MODEL)
    tin = sum(int(u.get("input_tokens", 0) or 0) for u in usages)
    tout = sum(int(u.get("output_tokens", 0) or 0) for u in usages)
    usd = sum(bedrock_client.estimate_cost_usd(u, model_id) for u in usages)
    return {"calls": len(usages), "input_tokens": tin, "output_tokens": tout, "cost_usd": round(usd, 6)}


def build_row(text: str, cited: list, data_through: str, today: str, cost: dict, gate_score: Any = None) -> dict:
    """The stored record — the serializer below reads exactly these fields."""
    from experiment.phase_taxonomy import experiment_stamp_for

    sk = f"{SK_PREFIX}{today}"
    row = {
        "pk": PK,
        "sk": sk,
        "coach_id": LEAD_ID,
        "text": text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "data_through": data_through,
        "cited": [dict(c) for c in cited],
        "model": MODEL,
        "calls": int(cost.get("calls", 0)),
        "input_tokens": int(cost.get("input_tokens", 0)),
        "output_tokens": int(cost.get("output_tokens", 0)),
        "cost_usd": Decimal(str(cost.get("cost_usd", 0))),
    }
    if gate_score is not None:
        try:
            row["gate_score"] = Decimal(str(gate_score))
        except Exception:  # noqa: BLE001 — a score is metadata, never a reason to drop the row
            pass
    row.update(experiment_stamp_for(PK, sk))
    return row


def run(
    data: dict,
    profile: dict,
    *,
    table: Any,
    lambda_client: Any = None,
    today: Optional[str] = None,
    persist: bool = True,
    invoke: Optional[Callable] = None,
    resolve_vitals: Optional[Callable] = None,
    enforce_gate: Optional[Callable] = None,
    allow: Optional[Callable] = None,
) -> dict:
    """The whole pipeline. Never raises; returns {status, ...} for the caller's log line."""
    try:
        if allow is None:
            from ai import budget_guard

            allow = budget_guard.allow
        if not allow(BUDGET_FEATURE):  # 1. budget FIRST — before any read or call
            return {"status": "paused", "feature": BUDGET_FEATURE}
        if today is None:
            from common.pacific_time import pacific_today

            today = pacific_today()
        data_through = str((data or {}).get("date") or "")
        if resolve_vitals is None:
            from web import vitals_resolver

            resolve_vitals = vitals_resolver.resolve_vitals
        vitals = resolve_vitals(table, "USER#matthew#SOURCE#") or {}
        cited = build_cited(data, profile, vitals, today)  # 2. facts
        if len(cited) < MIN_FACTS:
            return {"status": "insufficient_facts", "facts": len(cited)}
        if invoke is None:
            from ai import bedrock_client

            invoke = bedrock_client.invoke
        usages: list = []

        def _draft(correction: str = "") -> str:
            text, usage = generate(cited, data_through, invoke, correction)  # 3. the model
            usages.append(usage)
            return text

        text = _draft()
        reasons = check(text, cited, data_through, today)  # 4. cited-number + grounding
        if reasons:
            logger.info("[lead_daily] draft refused %s — regenerating once", reasons)
            text = _draft("; ".join(reasons) + ". Use only the numbers in the facts, exactly as written.")
            reasons = check(text, cited, data_through, today)
        if reasons:
            logger.warning("[lead_daily] HELD — %s (no row written)", reasons)
            return {"status": "held", "reasons": reasons, **_cost(usages)}

        # 5. N-06 quality gate, regenerate-or-hold; a regeneration must re-pass step 4.
        from ai.quality_gate_contract import brief_with_grounding

        def _regen(note: str) -> str:
            t = _draft(note)
            return t if not check(t, cited, data_through, today) else ""

        if enforce_gate is None:
            from ai import ai_calls

            enforce_gate = ai_calls._enforce_quality_gate
        if lambda_client is None:  # a None client would make the gate fail OPEN on the transport error
            import boto3

            lambda_client = boto3.client("lambda", region_name="us-west-2")
        brief = brief_with_grounding({"surface": "lead_daily", "cited": cited}, {}, _cited_numbers(cited, data_through))
        gated, report = enforce_gate(lambda_client, LEAD_ID, text, brief, _regen)
        if not gated or check(gated, cited, data_through, today):
            logger.warning("[lead_daily] HELD by the quality gate (score=%s) — no row written", (report or {}).get("score"))
            return {"status": "held", "reasons": ["quality_gate"], **_cost(usages)}
        cost = _cost(usages)
        row = build_row(gated, cited, data_through, today, cost, (report or {}).get("score"))
        if persist:
            table.put_item(Item=row)  # 6.
        logger.info("[lead_daily] wrote %s (%d facts, %s)", row["sk"], len(cited), cost)
        return {"status": "written" if persist else "dry_run", "sk": row["sk"], **cost}
    except Exception as e:  # noqa: BLE001 — the lead read never breaks the brief
        logger.warning("[lead_daily] failed (non-fatal): %s", e)
        return {"status": "error", "error": str(e)}


# ── the serve side ──────────────────────────────────────────────────────────


def served(item: Optional[dict]) -> Optional[dict]:
    """A stored row -> the served `lead_daily` object, or None when it cannot be served."""
    if not isinstance(item, dict) or not str(item.get("text") or "").strip() or not item.get("generated_at"):
        return None
    cited = []
    for c in item.get("cited") or []:
        if isinstance(c, dict):
            cited.append({k: str(c.get(k) or "") for k in ("metric", "value", "as_of", "source_field")})
    return {
        "text": str(item["text"]),
        "generated_at": str(item["generated_at"]),
        "data_through": str(item.get("data_through") or ""),
        "cited": cited,
        "coach_id": str(item.get("coach_id") or LEAD_ID),
    }


def latest_served(table: Any) -> Optional[dict]:
    """The newest current-cycle lead read, served; None on absence or any read error."""
    try:
        from boto3.dynamodb.conditions import Key
        from experiment.phase_filter import with_phase_filter

        resp = table.query(
            **with_phase_filter(
                {"KeyConditionExpression": Key("pk").eq(PK) & Key("sk").begins_with(SK_PREFIX), "ScanIndexForward": False, "Limit": 1}
            )
        )
        items = resp.get("Items") or []
        return served(items[0]) if items else None
    except Exception as e:  # noqa: BLE001 — absence is the honest fallback
        logger.warning("[lead_daily] read failed: %s", e)
        return None
