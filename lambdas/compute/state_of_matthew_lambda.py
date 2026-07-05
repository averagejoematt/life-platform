"""
state_of_matthew_lambda.py — "State of Matthew" weekly model brief (#552, epic #528).

The weekly executive summary of the whole intelligence layer: the forecast engine's
current expectations (#541), the hypothesis engine's live pre-registered bets (#530/
ADR-105), the coaching panel's current consensus/disputes (the integrator digest),
and the calibration scoreboard's self-graded track record (#538) — combined into
ONE narrated brief instead of four things a reader has to piece together themselves.

ADR-104 (grounded generation) is the hard rule here: every number in the brief is
computed deterministically BEFORE the model ever sees it. The single Haiku call at
the end does exactly one thing — write the connecting prose from the pre-computed
structure. It never calculates, estimates, rounds, or invents a number; the output
is checked against the exact numeric vocabulary it was given
(grounded_generation.grounding_findings) plus a causal-language check, and either
failure falls back to a plain templated narrative rather than publishing an
unverified claim. No regeneration — this is the platform's ONE weekly Haiku call,
not two.

Degrades gracefully section-by-section (the issue's explicit design): a source that
has genuinely produced nothing yet (calibration n=0 post-reset, no coach-consensus
digest yet, no hypothesis the engine has ever produced) is OMITTED from the brief,
never zero-filled or errored around. `sections_available` on the stored record says
exactly which of the four inputs made it in this week.

Budget: +1 Haiku call/week (~$0.01), gated at budget tier 1 via budget_guard's
"state_of_matthew" feature cutoff — paused alongside daily coach narration + the
ensemble, matching the issue's "tier-1 paused" budget line. A tier-1+ pause (or any
Bedrock failure, or a failed grounding check) still produces a full record — just
with a deterministic, template-built narrative instead of Haiku's prose.

DDB record: pk USER#matthew#SOURCE#state_of_matthew (EXPERIMENT_SCOPED — derived
weekly intelligence; see phase_taxonomy.py), sk DATE#<issued_date>. Read by
GET /api/state_of_matthew (lambdas/web/site_api_data.py).

Runs weekly, Sunday 19:30 UTC (12:30 PM PT) — after hypothesis-engine (19:00 UTC)
so this week's fresh hypothesis checks/resolutions are in before the brief reads
them.
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import boto3
import calibration_core  # #538: shared Brier + reliability scorer (layer module)
from boto3.dynamodb.conditions import Key
from er03_gate import BANNED_CAUSAL  # reuse the platform's one causal-language list
from grounded_generation import allowed_numbers, grounding_findings  # ADR-104 gate
from numeric import decimals_to_float, floats_to_decimal  # shared layer float<->Decimal
from phase_filter import with_phase_filter  # ADR-058: default-deny pilot data

try:
    from platform_logger import get_logger

    logger = get_logger("state-of-matthew")
except ImportError:
    logger = logging.getLogger("state-of-matthew")
    logger.setLevel(logging.INFO)

_REGION = os.environ.get("AWS_REGION", "us-west-2")
TABLE_NAME = os.environ.get("TABLE_NAME", "life-platform")
USER_ID = os.environ.get("USER_ID", "matthew")
USER_PREFIX = f"USER#{USER_ID}#SOURCE#"

STATE_PK = f"{USER_PREFIX}state_of_matthew"
FORECAST_PK = f"{USER_PREFIX}forecast"
HYPOTHESES_PK = f"{USER_PREFIX}hypotheses"
CALIBRATION_PK = f"{USER_PREFIX}calibration"
AI_ANALYSIS_PK = f"{USER_PREFIX}ai_analysis"

BUDGET_FEATURE = "state_of_matthew"
MODEL = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")
MAX_TOKENS = 420

# Same 8-coach roster used by the coach-intelligence tools + the calibration
# scoreboard (mcp/tools_coach_intelligence.py, lambdas/web/site_api_coach.py).
COACH_NAMES = {
    "sleep": "Dr. Lisa Park",
    "nutrition": "Dr. Marcus Webb",
    "training": "Dr. Sarah Chen",
    "mind": "Dr. Nathan Reeves",
    "physical": "Dr. Victor Reyes",
    "glucose": "Dr. Amara Patel",
    "labs": "Dr. James Okafor",
    "explorer": "Dr. Henning Brandt",
}
COACH_IDS = tuple(COACH_NAMES)

RESOLVED_WINDOW_DAYS = 7  # "this week's" hypothesis resolutions considered for the highlight

dynamodb = boto3.resource("dynamodb", region_name=_REGION)
table = dynamodb.Table(TABLE_NAME)


# ─────────────────────────────────────────────────────────────────────────────
# Section builders — pure functions, no I/O. Each returns a section dict, or
# None when that input is genuinely unavailable (the graceful-degrade contract).
# ─────────────────────────────────────────────────────────────────────────────


def gather_forecast_section(summary_item: dict | None) -> dict | None:
    """Shape the forecast engine's latest DATE# summary (#541). None when the
    engine has never issued a forecast."""
    if not summary_item:
        return None
    forecasts = summary_item.get("forecasts") or []
    return {
        "issued_date": summary_item.get("date"),
        "model": summary_item.get("model"),
        "confidence": summary_item.get("confidence"),
        "expectations": [
            {
                "metric": f.get("metric"),
                "unit": f.get("unit"),
                "horizon_days": f.get("horizon_days"),
                "frame": f.get("frame"),
                "point": f.get("point"),
                "lo": f.get("lo"),
                "hi": f.get("hi"),
            }
            for f in forecasts
        ],
        "resolutions_this_run": summary_item.get("resolutions_today") or [],
        "coverage": summary_item.get("coverage"),
    }


def gather_hypotheses_section(items: list, cutoff_str: str) -> dict | None:
    """Shape the hypothesis engine's live bets (#530/ADR-105). None when the
    engine has never produced a single (public) hypothesis.

    `cutoff_str` (an ISO date) marks the window a resolution counts as "this
    week's" for the highlight — mirrors RESOLVED_WINDOW_DAYS.
    """
    public_items = [it for it in (items or []) if it.get("public") is not False]
    if not public_items:
        return None

    by_status: dict = {}
    for it in public_items:
        status = it.get("status", "pending")
        by_status[status] = by_status.get(status, 0) + 1

    active = [it for it in public_items if it.get("status") in ("pending", "confirming")]
    active.sort(key=lambda i: i.get("created_at") or "", reverse=True)

    recently_resolved = [
        it for it in public_items if it.get("status") in ("confirmed", "refuted") and (it.get("last_checked") or "") >= cutoff_str
    ]
    recently_resolved.sort(key=lambda i: i.get("last_checked") or "", reverse=True)

    return {
        "total": len(public_items),
        "by_status": by_status,
        "active_count": len(active),
        "active": [
            {
                "hypothesis_id": it.get("hypothesis_id") or it.get("sk", "").replace("HYPOTHESIS#", ""),
                "hypothesis": it.get("hypothesis", ""),
                "status": it.get("status"),
                "confidence": it.get("confidence"),
                "effect_size": it.get("effect_size"),
                "ci95_low": it.get("ci95_low"),
                "ci95_high": it.get("ci95_high"),
                "n_condition": it.get("n_condition"),
                "n_comparison": it.get("n_comparison"),
            }
            for it in active[:5]
        ],
        "recently_resolved": [
            {
                "hypothesis_id": it.get("hypothesis_id") or it.get("sk", "").replace("HYPOTHESIS#", ""),
                "hypothesis": it.get("hypothesis", ""),
                "status": it.get("status"),
                "last_checked": it.get("last_checked"),
                "last_evidence": it.get("last_evidence"),
            }
            for it in recently_resolved
        ],
    }


def gather_coach_consensus_section(integrator_item: dict | None) -> dict | None:
    """Shape the integrator digest's live disagreements (same source as the
    get_coach_disagreements MCP tool + the /api/coach_team tension map). None
    when the integrator has never written a digest."""
    if not integrator_item:
        return None
    raw = integrator_item.get("disagreements") or integrator_item.get("active_disagreements") or []
    disagreements = []
    for d in raw if isinstance(raw, list) else []:
        if not isinstance(d, dict):
            continue
        disagreements.append(
            {
                "topic": d.get("topic") or d.get("domain") or "",
                "coaches": d.get("coaches_involved") or d.get("coaches") or [],
                "resolution": (d.get("nakamura_call") or d.get("resolution_suggested") or d.get("tension") or d.get("summary") or ""),
            }
        )
    return {
        "generated_at": integrator_item.get("generated_at"),
        "disagreement_count": len(disagreements),
        "disagreements": disagreements[:3],
    }


def gather_calibration_section(platform_summary: dict | None) -> dict | None:
    """Shape the platform-wide calibration_core.score_pairs() summary. None when
    nothing has resolved yet (n=0) — the documented post-reset empty state."""
    if not platform_summary or not platform_summary.get("n"):
        return None
    return {
        "n": platform_summary["n"],
        "confirmed": platform_summary["confirmed"],
        "refuted": platform_summary["refuted"],
        "accuracy_pct": platform_summary["accuracy_pct"],
        "brier": platform_summary["brier"],
        "brier_skill": platform_summary["brier_skill"],
        "calibration": platform_summary["calibration"],
        "label": platform_summary["label"],
    }


def pick_highlight(forecast, hypotheses, coaches, calibration) -> dict | None:
    """The one thing that mattered this week — a fixed, deterministic priority
    order over whichever sections are available. No scoring/weighting math:
    just "did something resolve" before "is there a live number to report."
    """
    if hypotheses and hypotheses.get("recently_resolved"):
        return {"kind": "hypothesis_resolution", "detail": hypotheses["recently_resolved"][0]}
    if forecast and forecast.get("resolutions_this_run"):
        misses = [r for r in forecast["resolutions_this_run"] if r.get("covered") is False]
        return {"kind": "forecast_resolution", "detail": misses[0] if misses else forecast["resolutions_this_run"][0]}
    if calibration and (calibration.get("n") or 0) >= 5:
        return {
            "kind": "calibration",
            "detail": {"calibration": calibration["calibration"], "n": calibration["n"], "brier": calibration["brier"]},
        }
    if coaches and (coaches.get("disagreement_count") or 0) > 0:
        return {"kind": "coach_disagreement", "detail": coaches["disagreements"][0]}
    return None


def assemble_state(forecast, hypotheses, coaches, calibration, as_of: str) -> dict:
    """Combine the four (possibly-None) sections into one structure. This is
    the whole "deterministic assembly" step — no math happens past this point,
    only narration of what's already here."""
    return {
        "as_of": as_of,
        "sections_available": {
            "forecast": forecast is not None,
            "hypotheses": hypotheses is not None,
            "coaches": coaches is not None,
            "calibration": calibration is not None,
        },
        "forecast": forecast,
        "hypotheses": hypotheses,
        "coaches": coaches,
        "calibration": calibration,
        "highlight": pick_highlight(forecast, hypotheses, coaches, calibration),
    }


def _narration_payload(state: dict) -> dict:
    """The exact numeric vocabulary the model is allowed to use — every present
    (non-None) section, nothing else. Also what gets rendered into the prompt."""
    payload = {"as_of": state["as_of"]}
    for key in ("forecast", "hypotheses", "coaches", "calibration", "highlight"):
        if state.get(key) is not None:
            payload[key] = state[key]
    return payload


def build_narration_body(state: dict) -> dict:
    """The Anthropic Messages body for the one weekly Haiku call. No section of
    this prompt asks the model to compute anything — only to narrate numbers
    it is handed verbatim."""
    system = (
        'You are the narrator of "State of Matthew," a weekly one-paragraph brief that connects four '
        "independent measurement systems on a personal health-data platform: a statistical forecast "
        "engine, a pre-registered hypothesis tracker, a panel of AI health coaches, and a self-graded "
        "prediction scoreboard. You are given the exact, already-computed numbers below in JSON — you "
        "must NOT calculate, estimate, round, average, extrapolate, or invent any number, date, or trend "
        "that is not explicitly present in that JSON. Use ONLY the facts given. Write 2-4 sentences "
        "(roughly 80-130 words) in a plain, correlative, non-hyperbolic voice — never claim causation "
        "('causes', 'because', 'leads to', etc.), never dramatize. If a section is absent from the JSON, "
        "do not mention it or apologize for its absence — just work with what's given. Do not open with "
        "the word 'Matthew'."
    )
    data_blob = json.dumps(_narration_payload(state), indent=2, default=str)
    user = "This week's pre-computed platform state:\n\n" + data_blob + "\n\nWrite the connecting narrative."
    return {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    }


def _causal_language(text: str) -> list:
    """Reuses the platform's one banned-causal-connective list (er03_gate) so a
    narration surface doesn't grow its own divergent copy."""
    low = (text or "").lower()
    return [w for w in BANNED_CAUSAL if re.search(r"\b" + re.escape(w) + r"\b", low)]


def deterministic_fallback_narrative(state: dict) -> str:
    """A template narrative built directly from already-computed fields — used
    when Haiku is paused/unavailable/ungrounded. Cannot fabricate a number
    because it only ever restates fields already in `state`."""
    parts = []
    f = state.get("forecast")
    if f and f.get("expectations"):
        e = f["expectations"][0]
        frame = f" ({e['frame']})" if e.get("frame") else ""
        parts.append(f"The forecast engine currently expects {e.get('metric')} near {e.get('point')} {e.get('unit')}{frame}.")
    h = state.get("hypotheses")
    if h:
        parts.append(f"{h.get('active_count', 0)} of {h.get('total', 0)} tracked hypotheses are currently active.")
    c = state.get("coaches")
    if c:
        n = c.get("disagreement_count", 0)
        parts.append(f"The coaching panel currently has {n} open disagreement{'s' if n != 1 else ''}.")
    cal = state.get("calibration")
    if cal:
        verdict = (cal.get("calibration") or "ungraded").replace("_", " ")
        parts.append(f"Across {cal.get('n')} graded predictions the platform is {verdict} (Brier {cal.get('brier')}).")
    if not parts:
        return "Not enough resolved data yet this week to summarize the platform's model state."
    return " ".join(parts)


def narrate(state: dict) -> dict:
    """One Haiku call to write the connecting narrative — budget-gated (tier 1,
    matching the issue's budget line), fail-soft to the deterministic template
    on a tier pause, a Bedrock error, or a failed ADR-104 grounding check. Never
    regenerates: this is the platform's ONE weekly call, not two."""
    try:
        from budget_guard import allow

        if not allow(BUDGET_FEATURE):
            return {"narrative": deterministic_fallback_narrative(state), "narrated": False, "model": None, "reason": "budget_tier"}
    except ImportError:
        pass  # fail-open: never break narration on a missing layer module

    body = build_narration_body(state)
    try:
        import bedrock_client

        resp = bedrock_client.invoke(body, model_name=MODEL)
        content = resp.get("content") or []
        text = "".join(p.get("text", "") for p in content if isinstance(p, dict)).strip()
    except Exception as e:
        logger.warning(f"[state-of-matthew] narration call failed: {e}")
        return {"narrative": deterministic_fallback_narrative(state), "narrated": False, "model": None, "reason": "bedrock_error"}

    if not text:
        return {"narrative": deterministic_fallback_narrative(state), "narrated": False, "model": None, "reason": "empty_response"}

    allowed = allowed_numbers(_narration_payload(state))
    findings = grounding_findings(text, facts=None, allowed=allowed)
    causal_hits = _causal_language(text)
    if findings or causal_hits:
        logger.warning(f"[state-of-matthew] ADR-104 grounding gate failed (findings={findings}, causal={causal_hits}) — falling back")
        return {"narrative": deterministic_fallback_narrative(state), "narrated": False, "model": MODEL, "reason": "grounding_gate"}

    return {"narrative": text, "narrated": True, "model": MODEL, "reason": None}


def build_summary_item(state: dict, narration: dict, today_str: str) -> dict:
    """The DDB record written weekly — sk DATE#<today>, one row per run."""
    item = {
        "pk": STATE_PK,
        "sk": f"DATE#{today_str}",
        "record_type": "state_of_matthew_brief",
        "date": today_str,
        "sections_available": state["sections_available"],
        "forecast": state.get("forecast"),
        "hypotheses": state.get("hypotheses"),
        "coaches": state.get("coaches"),
        "calibration": state.get("calibration"),
        "highlight": state.get("highlight"),
        "narrative": narration["narrative"],
        "narrated": narration["narrated"],
        "model": narration.get("model"),
        "disclosure": (
            "Every number above comes from a deterministic computation over the platform's own recorded "
            "history (forecast intervals, pre-registered hypothesis tests, self-graded predictions) — the "
            "narrative paragraph only connects them; it never computes a figure itself."
        ),
    }
    try:
        from compute_metadata import tag_record

        item = tag_record(item, source_id="state_of_matthew")
    except ImportError:
        pass
    return item


# ─────────────────────────────────────────────────────────────────────────────
# I/O — DynamoDB reads. Each fetch fails soft (empty/None) so one source being
# down never takes out the other three.
# ─────────────────────────────────────────────────────────────────────────────


def fetch_forecast_summary() -> dict | None:
    try:
        resp = table.query(
            KeyConditionExpression=Key("pk").eq(FORECAST_PK) & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
            Limit=1,
        )
    except Exception as e:
        logger.warning(f"[state-of-matthew] forecast fetch failed: {e}")
        return None
    items = decimals_to_float(resp.get("Items", []))
    return items[0] if items else None


def fetch_hypotheses() -> list:
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(HYPOTHESES_PK) & Key("sk").begins_with("HYPOTHESIS#"),
                    "ScanIndexForward": False,
                    "Limit": 50,
                }
            )
        )
    except Exception as e:
        logger.warning(f"[state-of-matthew] hypotheses fetch failed: {e}")
        return []
    return decimals_to_float(resp.get("Items", []))


def fetch_coach_consensus() -> dict | None:
    try:
        resp = table.get_item(Key={"pk": AI_ANALYSIS_PK, "sk": "EXPERT#integrator"})
    except Exception as e:
        logger.warning(f"[state-of-matthew] coach consensus fetch failed: {e}")
        return None
    item = resp.get("Item")
    return decimals_to_float(item) if item else None


def _fetch_coach_prediction_pairs(coach_id: str) -> list:
    coach_pk = f"COACH#{coach_id}_coach"
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(coach_pk) & Key("sk").begins_with("PREDICTION#"),
                    "ScanIndexForward": False,
                    "Limit": 500,
                }
            )
        )
    except Exception as e:
        logger.warning(f"[state-of-matthew] calibration fetch ({coach_id}) failed: {e}")
        return []
    records = decimals_to_float(resp.get("Items", []))
    return calibration_core.pairs_from_prediction_records(records)


def _fetch_hypothesis_calibration_pairs() -> list:
    try:
        resp = table.query(
            **with_phase_filter(
                {
                    "KeyConditionExpression": Key("pk").eq(CALIBRATION_PK) & Key("sk").begins_with("CALIB#"),
                    "ScanIndexForward": False,
                    "Limit": 500,
                }
            )
        )
    except Exception as e:
        logger.warning(f"[state-of-matthew] hypothesis calibration ledger fetch failed: {e}")
        return []
    rows = decimals_to_float(resp.get("Items", []))
    return calibration_core.pairs_from_calibration_rows(rows)


def fetch_calibration_summary() -> dict:
    """Platform-wide (all coaches + the hypothesis ledger) — same shared scorer
    the public /api/calibration scoreboard uses (#538)."""
    pairs = []
    for cid in COACH_IDS:
        pairs.extend(_fetch_coach_prediction_pairs(cid))
    pairs.extend(_fetch_hypothesis_calibration_pairs())
    return calibration_core.score_pairs(pairs)


def lambda_handler(event: dict, context) -> dict:
    today = datetime.now(timezone.utc).date()
    today_str = today.isoformat()
    cutoff_str = (today - timedelta(days=RESOLVED_WINDOW_DAYS)).isoformat()

    forecast_summary = fetch_forecast_summary()
    hyp_items = fetch_hypotheses()
    integrator_item = fetch_coach_consensus()
    calibration_summary = fetch_calibration_summary()

    forecast = gather_forecast_section(forecast_summary)
    hypotheses = gather_hypotheses_section(hyp_items, cutoff_str)
    coaches = gather_coach_consensus_section(integrator_item)
    calibration = gather_calibration_section(calibration_summary)

    state = assemble_state(forecast, hypotheses, coaches, calibration, today_str)
    narration = narrate(state)
    item = build_summary_item(state, narration, today_str)

    try:
        table.put_item(Item=floats_to_decimal({k: v for k, v in item.items() if v is not None}))
    except Exception as e:
        logger.error(f"[state-of-matthew] write failed: {e}")
        raise

    result = {
        "date": today_str,
        "sections_available": state["sections_available"],
        "narrated": narration["narrated"],
        "narration_reason": narration.get("reason"),
    }
    logger.info(json.dumps(result))
    return result
