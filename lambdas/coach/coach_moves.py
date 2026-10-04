"""coach_moves.py — the coaches' daily line: a move, not numbers restated (#4583, epic #4580).

Runs inside the EXISTING `coach-daily-reflection` job (19:00 UTC, after the daily brief has
written today's lead read and OUTPUT# rows). No new Lambda, no new schedule.

THE ORDER (cost first, then honesty)
  1. budget — `budget_guard.allow("coach_narrative")` (band 2, the feature every daily
     coach narrative runs under) before any read or call; a row already written today
     is not paid for twice (EventBridge's async retries, a manual re-run) unless forced;
  2. the fact sheet — `coach_moves_sheet.build_sheet`, ONE per day, in code, from served
     values (see that module): every line today is judged against the same sheet, so two
     coaches cannot cite two values for one metric;
  3. the cast — ONE Haiku call picks at most three speakers and each one's move (a call,
     a reaction to a graded result, a reply to another coach, a question to Matthew, a
     change of mind), and may propose a dated bet between two of them. Code admits the
     cast: a sidelined coach (`absent_coaches`) cannot speak, a reply must name a coach
     who has said something, a reaction must name a graded result on the sheet, a change
     of mind needs a prior position, and the bet must pass `dispute_docket.validate_criterion`
     (opposite sides of a gradable metric, a frozen date inside the docket's horizon);
  4. the lines — ONE Sonnet call per chosen coach (plus at most one regeneration), each
     refused by `coach_moves_sheet.check_line` / `cross_line_findings` unless it makes its
     move, carries an opinion, cites at most two figures and only sheet values. A refused
     line is HELD and that coach is silent today — never shipped;
  5. the bet — when both bettors' lines stand, the existing Dispute Docket opens it
     (`dispute_docket.open_from_disagreements`, ENSEMBLE#docket — no new store), which
     grades it on its date in code;
  6. one row, `COACH#eli_marsh / MOVES#{date}` (the head coach's partition hosts the
     board's day — a distinct sk prefix no OUTPUT# reader picks up, the LEAD_DAILY#
     precedent), with each line's move tag and date, the absent coaches and their reasons,
     the silent ones, the held ones with their reasons, the sheet itself, and the measured
     token usage and cost. Served by `latest_served` as `/api/coaching-dashboard` `moves`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Callable, Optional

from ai.model_defaults import NARRATIVE_MODEL

from coach import coach_moves_sheet as sheet_mod

logger = logging.getLogger(__name__)

LEAD_ID = "eli_marsh"  # persona_registry.LEAD_PERSONA_ID — the board's day lives on the lead's partition
PK = f"COACH#{LEAD_ID}"
SK_PREFIX = "MOVES#"
BUDGET_FEATURE = "coach_narrative"
CAST_MODEL = os.environ.get("AI_MODEL_HAIKU", "claude-haiku-4-5-20251001")  # structured choice
LINE_MODEL = os.environ.get("AI_MODEL", NARRATIVE_MODEL)  # the line itself (narrative tier)
MAX_SPEAKERS = 3
CAST_MAX_TOKENS = 500
LINE_MAX_TOKENS = 160
# A calorie figure never reaches a reader surface (standing rule), so a bet on calories is
# never offered and never admitted.
_BET_EXCLUDED_METRICS = ("total_calories_kcal",)
MOVE_LABELS = {
    "call": "A call",
    "reaction": "On a result",
    "reply": "A reply",
    "question": "A question for Matthew",
    "change_of_mind": "A change of mind",
}
_CONDITION_WORDS = {"gt": "above", "gte": "at or above", "lt": "below", "lte": "at or below", "eq": "exactly"}

CAST_PROMPT = (
    "You run the daily meeting of an AI coaching team for a public health-experiment site about Matthew. "
    "Pick who speaks today — AT MOST three coaches, fewer is better, none is allowed — and the one move each makes:\n"
    + "\n".join(f'- "{k}": {v}' for k, v in sheet_mod.MOVE_WORDS.items())
    + "\nA coach speaks only with something NEW to say: an opinion, a forecast, a disagreement, a question. "
    "Restating today's numbers is not a move — a coach with nothing to add stays silent. Never pick a sidelined coach. "
    "A reply names the coach it answers in replies_to. A reaction names the graded result in result (its prediction_id). "
    "A change of mind is only for a coach whose earlier position appears below.\n"
    "If two of your speakers would genuinely disagree about something a number will settle within 3 to 30 days, "
    "propose ONE bet: metric (one of {metrics}), condition (gt, gte, lt, lte), threshold, resolution_days, and sides "
    "(each coach's id mapped to true if they say the condition will hold, false if not — opposite sides). Otherwise bet is null.\n"
    "Answer with JSON only, no prose:\n"
    '{{"speakers": [{{"coach_id": "...", "move": "call", "about": "<what they will say, under 20 words>", '
    '"replies_to": null, "result": null}}], "bet": null}}'
)

LINE_PROMPT = (
    "You are an AI coach on a public health-experiment site, writing ONE short line for today's front page. "
    "Rules you must obey:\n"
    f"- {sheet_mod.MAX_WORDS - 10} words at most. One or two sentences. No preamble, no sign-off, no lists.\n"
    "- Speak as yourself in the first person ('I think', 'I expect', 'I was wrong'). Say what you THINK, not what the data says: "
    "a line that only reports numbers will be refused.\n"
    "- Refer to Matthew in the third person (Matthew / he / his). Never 'you'. Never quote him or write words in his voice.\n"
    "- At most two figures, each exactly as it appears on the fact sheet. No other number, no arithmetic, no rounding. "
    "Spell no counts that are not on the sheet.\n"
    "- Correlative only — never say one thing caused another. Hedge early data ('so far', 'early').\n"
    "- Never mention calories or a deficit, a reset, a restart, an attempt or a numbered cycle. No titles such as 'Dr.'.\n"
    "- No medical advice, no diagnosis, no supplement or drug suggestions."
)


# ── the cast ─────────────────────────────────────────────────────────────────


def _bet_metrics() -> list:
    from experiment.measurable_metrics import METRIC_SOURCES

    return sorted(m for m in METRIC_SOURCES if m not in _BET_EXCLUDED_METRICS)


def cast_user(sheet: dict, names: dict, eligible: list) -> str:
    roster = "\n".join(f"- {cid}: {names.get(cid, cid)}" for cid in eligible)
    return (
        sheet_mod.sheet_text(sheet)
        + "\n\n"
        + sheet_mod.context_text(sheet, names)
        + f"\n\nCOACHES WHO MAY SPEAK TODAY:\n{roster}\n\nChoose today's speakers."
    )


def _text_of(resp: Any) -> str:
    for block in (resp or {}).get("content") or []:
        if isinstance(block, dict) and isinstance(block.get("text"), str):
            return block["text"].strip()
    return ""


def parse_json(text: str) -> Optional[dict]:
    """The cast's JSON object — through the ONE model-JSON door (ai.structured_json, #4276)."""
    from ai.structured_json import parse_json_span

    out = parse_json_span(text, "{")
    return out if isinstance(out, dict) else None


def admit_cast(raw: Optional[dict], sheet: dict, eligible: list, today: str) -> dict:
    """Code admits the model's cast. Returns {speakers, bet, dropped}; `bet` is
    {raw, normalized, coaches, description} or None."""
    raw = raw or {}
    graded_ids = {g["prediction_id"] for g in sheet.get("graded") or [] if g.get("prediction_id")}
    has_prior = set((sheet.get("positions") or {}).keys()) | {y.get("coach_id") for y in sheet.get("yesterday") or []}
    speakers: list = []
    dropped: list = []
    seen: set = set()
    for s in raw.get("speakers") or []:
        if not isinstance(s, dict):
            continue
        cid, move = str(s.get("coach_id") or ""), str(s.get("move") or "")
        why = None
        if cid not in eligible:
            why = "not eligible (sidelined or not on the roster)"
        elif cid in seen:
            why = "already speaking"
        elif move not in sheet_mod.MOVES:
            why = f"unknown move {move!r}"
        elif len(speakers) >= MAX_SPEAKERS:
            why = f"more than {MAX_SPEAKERS} speakers"
        elif move == "reply" and (
            s.get("replies_to") == cid or s.get("replies_to") not in (set(eligible) & (has_prior | {x["coach_id"] for x in speakers}))
        ):
            why = "a reply must answer another coach who has said something"
        elif move == "reaction" and str(s.get("result") or "") not in graded_ids:
            why = "a reaction must name a graded result on the sheet"
        elif move == "change_of_mind" and cid not in has_prior:
            why = "a change of mind needs an earlier position"
        if why:
            dropped.append({"coach_id": cid, "move": move, "reason": why})
            continue
        seen.add(cid)
        speakers.append(
            {
                "coach_id": cid,
                "move": move,
                "about": str(s.get("about") or "")[:200],
                "replies_to": s.get("replies_to") if move == "reply" else None,
                "result": str(s.get("result")) if move == "reaction" else None,
            }
        )
    # A reply to a coach speaking today goes after that coach, so it can read the line.
    order = {x["coach_id"]: i for i, x in enumerate(speakers)}
    speakers.sort(key=lambda x: order[x["replies_to"]] + 0.5 if x["move"] == "reply" and x["replies_to"] in order else order[x["coach_id"]])
    return {"speakers": speakers, "bet": admit_bet(raw.get("bet"), speakers, today), "dropped": dropped}


def admit_bet(bet: Any, speakers: list, today: str) -> Optional[dict]:
    if not isinstance(bet, dict):
        return None
    sides: dict = bet["sides"] if isinstance(bet.get("sides"), dict) else {}
    pair = [c for c in sides if c in {s["coach_id"] for s in speakers}]
    if len(pair) != 2 or bet.get("metric") in _BET_EXCLUDED_METRICS:
        return None
    from coach import dispute_docket

    criterion = {k: bet.get(k) for k in ("metric", "condition", "threshold", "resolution_days", "sides")}
    ok, reason, normalized = dispute_docket.validate_criterion(criterion, pair[0], pair[1], today)
    if not ok:
        logger.info("[coach_moves] bet not admitted: %s", reason)
        return None
    return {"raw": criterion, "normalized": normalized, "coaches": pair, "description": bet_words(normalized)}


def bet_words(n: dict) -> str:
    metric = str(n["metric"]).replace("_7day_avg", " (7-day average)").replace("_lbs", "").replace("_", " ")
    return f"{metric} {_CONDITION_WORDS.get(n['condition'], n['condition'])} {n['threshold']:g} on {sheet_mod.date_in_words(n['resolution_date'])}"


# ── the lines ────────────────────────────────────────────────────────────────


def line_user(sp: dict, sheet: dict, names: dict, spoken: dict, bet: Optional[dict], extra: str) -> str:
    parts = [sheet_mod.sheet_text(sheet, extra), sheet_mod.context_text(sheet, names)]
    parts.append(f"YOUR MOVE TODAY: {sheet_mod.MOVE_WORDS[sp['move']]}.")
    if sp.get("about"):
        parts.append(f"What the meeting asked you to say: {sp['about']}")
    if sp["move"] == "reply":
        target = sp["replies_to"]
        said = spoken.get(target) or ((sheet.get("positions") or {}).get(target) or {}).get("text") or ""
        parts.append(f"You are answering {names.get(target, target)}, who said: {said}  Name {names.get(target, target)} in your line.")
    if sp["move"] == "reaction":
        g = next((g for g in sheet.get("graded") or [] if g["prediction_id"] == sp.get("result")), None)
        if g:
            parts.append(f"The result you are reacting to: {g['coach_id']} predicted '{g['claim']}' — it {g['verdict']}.")
    if bet and sp["coach_id"] in bet["coaches"]:
        side = bet["normalized"]["sides"][sp["coach_id"]]
        other = next(c for c in bet["coaches"] if c != sp["coach_id"])
        parts.append(
            f"You have a dated bet with {names.get(other, other)}: {bet['description']}. "
            f"You say it WILL {'' if side else 'NOT '}happen. Say so in your line."
        )
    parts.append("Write your line.")
    return "\n\n".join(p for p in parts if p)


def _bet_extra(bet: Optional[dict]) -> str:
    return f"OPEN BET: {bet['description']}." if bet else ""


def run(
    table: Any,
    *,
    names: dict,
    voices: Callable[[str], tuple],
    today: Optional[str] = None,
    coach_ids: Optional[list] = None,
    invoke: Optional[Callable] = None,
    allow: Optional[Callable] = None,
    inputs: Optional[dict] = None,
    open_bet: Optional[Callable] = None,
    persist: bool = True,
    force: bool = False,
) -> dict:
    """The whole pipeline. Never raises; returns {status, ...} for the handler's log line."""
    try:
        if allow is None:
            from ai import budget_guard

            allow = budget_guard.allow
        if not allow(BUDGET_FEATURE):
            return {"status": "paused", "feature": BUDGET_FEATURE}
        if today is None:
            from common.pacific_time import pacific_today

            today = pacific_today()
        if coach_ids is None:
            from coach import persona_registry

            coach_ids = list(persona_registry.OPERATIONAL_COACH_IDS)
        if persist and not force and _row(table, today):
            return {"status": "already_written", "date": today}
        if inputs is None:
            inputs = sheet_mod.read_inputs(table, today, coach_ids, names)
            inputs["yesterday"] = (_row(table, (date.fromisoformat(today) - timedelta(days=1)).isoformat()) or {}).get("lines") or []
        sheet = sheet_mod.build_sheet(inputs, today)
        absent_ids = {a["coach_id"] for a in sheet["absent"]}
        eligible = [c for c in coach_ids if c not in absent_ids]
        if invoke is None:
            from ai import bedrock_client

            invoke = bedrock_client.invoke
        usages: list = []

        cast_resp = invoke(
            {
                "model": CAST_MODEL,
                "max_tokens": CAST_MAX_TOKENS,
                "system": CAST_PROMPT.format(metrics=", ".join(_bet_metrics())),
                "messages": [{"role": "user", "content": cast_user(sheet, names, eligible)}],
            },
            model_name=CAST_MODEL,
        )
        usages.append((CAST_MODEL, dict((cast_resp or {}).get("usage") or {})))
        plan = admit_cast(parse_json(_text_of(cast_resp)), sheet, eligible, today)
        bet = plan["bet"]

        lines: list = []
        held: list = []
        spoken: dict = {}
        accepted_texts: list = []
        for sp in plan["speakers"]:
            cid = sp["coach_id"]
            extra = _bet_extra(bet) if bet and cid in bet["coaches"] else ""
            target_name = names.get(sp.get("replies_to") or "", "")
            rules, example = voices(cid)
            system = (
                LINE_PROMPT
                + (f"\n\nYour voice rules: {rules}" if rules else "")
                + (f"\n\nA sample of your voice:\n{example}" if example else "")
            )
            user = line_user(sp, sheet, names, spoken, bet, extra)
            text, reasons = "", ["not_generated"]
            for attempt in range(2):
                msg = user if attempt == 0 else user + "\n\nYour previous line was refused: " + "; ".join(reasons) + ". Fix exactly that."
                resp = invoke(
                    {"model": LINE_MODEL, "max_tokens": LINE_MAX_TOKENS, "system": system, "messages": [{"role": "user", "content": msg}]},
                    model_name=LINE_MODEL,
                )
                usages.append((LINE_MODEL, dict((resp or {}).get("usage") or {})))
                text = _text_of(resp)
                reasons = sheet_mod.check_line(text, sp["move"], sheet, today=today, target_name=target_name, extra=extra)
                reasons += sheet_mod.cross_line_findings(text, accepted_texts, sheet)
                if not reasons:
                    break
            if reasons:
                logger.info("[coach_moves] %s %s HELD — %s", cid, sp["move"], reasons)
                held.append({"coach_id": cid, "move": sp["move"], "reasons": reasons})
                continue
            spoken[cid] = text
            accepted_texts.append(text)
            lines.append(
                {
                    "coach_id": cid,
                    "name": names.get(cid, cid),
                    "move": sp["move"],
                    "text": text,
                    "date": today,
                    "replies_to": sp.get("replies_to"),
                    "replies_to_name": target_name or None,
                    "result_id": sp.get("result"),
                }
            )

        bet_out = None
        if bet and all(c in spoken for c in bet["coaches"]):
            if open_bet is None:
                from coach import dispute_docket

                open_bet = dispute_docket.open_from_disagreements
            a, b = bet["coaches"]
            res = open_bet(
                [
                    {
                        "topic": bet["description"],
                        "coaches": [a, b],
                        "positions": {a: spoken[a], b: spoken[b]},
                        "resolution_criterion": bet["raw"],
                        "sk": f"{SK_PREFIX}{today}",
                    }
                ],
                today,
            )
            opened = (res or {}).get("opened") or []
            if opened:
                bet_out = {
                    "docket_sk": opened[0].get("sk"),
                    "resolution_date": opened[0].get("resolution_date"),
                    "description": bet["description"],
                    "coaches": [a, b],
                    "sides": bet["normalized"]["sides"],
                }
                for ln in lines:
                    if ln["coach_id"] in (a, b):
                        ln["bet"] = {k: bet_out[k] for k in ("docket_sk", "resolution_date", "description")}
            else:
                logger.info("[coach_moves] bet not opened: %s", (res or {}).get("skipped"))

        cost = _cost(usages)
        row = build_row(today, lines, sheet, eligible, held, plan["dropped"], bet_out, cost)
        if persist:
            table.put_item(Item=row)
        logger.info(
            "[coach_moves] %s: %d line(s), held %s, bet %s, %s", today, len(lines), [h["coach_id"] for h in held], bool(bet_out), cost
        )
        return {"status": "written" if persist else "dry_run", "lines": len(lines), "held": len(held), "bet": bool(bet_out), **cost}
    except Exception as e:  # noqa: BLE001 — the moves never break the reflection batch
        logger.warning("[coach_moves] failed (non-fatal): %s", e)
        return {"status": "error", "error": str(e)}


def _cost(usages: list) -> dict:
    from ai import bedrock_client

    tin = sum(int(u.get("input_tokens", 0) or 0) for _m, u in usages)
    tout = sum(int(u.get("output_tokens", 0) or 0) for _m, u in usages)
    usd = sum(bedrock_client.estimate_cost_usd(u, bedrock_client.resolve_model_id(m)) for m, u in usages)
    return {"calls": len(usages), "input_tokens": tin, "output_tokens": tout, "cost_usd": round(usd, 6)}


# ── the row ──────────────────────────────────────────────────────────────────


def build_row(today: str, lines: list, sheet: dict, eligible: list, held: list, dropped: list, bet: Optional[dict], cost: dict) -> dict:
    from common.numeric import floats_to_decimal
    from experiment.phase_taxonomy import experiment_stamp_for

    sk = f"{SK_PREFIX}{today}"
    speaking = {ln["coach_id"] for ln in lines}
    row = {
        "pk": PK,
        "sk": sk,
        "record_type": "coach_moves",
        "date": today,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "lines": lines,
        "absent": sheet.get("absent") or [],
        "silent": [c for c in eligible if c not in speaking],
        "held": held,
        "dropped": dropped,
        "bet": bet,
        "fact_sheet": sheet_mod.stored_sheet(sheet),
        "models": {"cast": CAST_MODEL, "line": LINE_MODEL},
        "calls": int(cost.get("calls", 0)),
        "input_tokens": int(cost.get("input_tokens", 0)),
        "output_tokens": int(cost.get("output_tokens", 0)),
    }
    row = floats_to_decimal(json.loads(json.dumps(row, default=str)))
    row["cost_usd"] = Decimal(str(cost.get("cost_usd", 0)))
    row.update(experiment_stamp_for(PK, sk))
    return row


def _row(table: Any, day: str) -> Optional[dict]:
    """One day's row, phase-visible only (a wiped prior-cycle row is not today's)."""
    from experiment.phase_filter import singleton_visible

    try:
        item = table.get_item(Key={"pk": PK, "sk": f"{SK_PREFIX}{day}"}).get("Item")
    except Exception as e:  # noqa: BLE001
        logger.warning("[coach_moves] read %s failed: %s", day, e)
        return None
    return item if item and singleton_visible(item) else None


# ── the serve side ───────────────────────────────────────────────────────────


def served(item: Optional[dict]) -> Optional[dict]:
    """A stored row -> the served `moves` object (the /api/coaching-dashboard key), or None."""
    if not isinstance(item, dict) or not item.get("date"):
        return None
    lines = []
    for ln in item.get("lines") or []:
        if not isinstance(ln, dict) or not str(ln.get("text") or "").strip() or ln.get("move") not in MOVE_LABELS:
            continue
        out = {
            "coach_id": str(ln.get("coach_id") or ""),
            "name": str(ln.get("name") or ""),
            "move": ln["move"],
            "move_label": MOVE_LABELS[ln["move"]],
            "text": str(ln["text"]),
            "date": str(ln.get("date") or item["date"]),
            "replies_to": ln.get("replies_to"),
            "replies_to_name": ln.get("replies_to_name"),
        }
        if isinstance(ln.get("bet"), dict):
            out["bet"] = {k: str(ln["bet"].get(k) or "") for k in ("description", "resolution_date")}
        lines.append(out)
    return {
        "date": str(item["date"]),
        "generated_at": str(item.get("generated_at") or ""),
        "lines": lines,
        "absent": [
            {"coach_id": str(a.get("coach_id") or ""), "name": str(a.get("name") or ""), "reason": str(a.get("reason") or "")}
            for a in item.get("absent") or []
            if isinstance(a, dict)
        ],
        "silent": [str(c) for c in item.get("silent") or []],
    }


_LATEST_MAX_PAGES = 8


def latest_served(table: Any) -> Optional[dict]:
    """The newest current-cycle day of moves, served; None on absence or any read error."""
    try:
        from boto3.dynamodb.conditions import Key
        from experiment.phase_filter import with_phase_filter

        kwargs = with_phase_filter(
            {"KeyConditionExpression": Key("pk").eq(PK) & Key("sk").begins_with(SK_PREFIX), "ScanIndexForward": False, "Limit": 25}
        )
        for _page in range(_LATEST_MAX_PAGES):
            resp = table.query(**kwargs)
            items = resp.get("Items") or []
            if items:
                return served(items[0])
            if not resp.get("LastEvaluatedKey"):
                return None
            kwargs = dict(kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        return None
    except Exception as e:  # noqa: BLE001 — absence is the honest fallback
        logger.warning("[coach_moves] latest read failed: %s", e)
        return None
