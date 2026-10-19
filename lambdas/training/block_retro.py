"""block_retro.py — the block retro's deterministic half and its panel re-grade (#5079, epic #5051). OWNER-ONLY.

WHY THIS EXISTS

The 2026-10-18 elite-panel review graded the training on thirteen rows with no earlier review to compare
against. The `/training-review` skill (`.claude/skills/training-review/SKILL.md`) re-grades the SAME rows
(`config/training_scorecard.json`) once per block and names what moved. This module makes that grading
reproducible: the same stored rows and the same supplied counts give the same evidence, the same code
scores, the same movers and the same prediction verdicts. The session reads and explains; it does not count.

THE SHAPE (ADR-105: deterministic computation before any model verdict)

  * `block_window`       the block is the charter's `rotation.anchors_fixed_weeks` weeks ending on a Sunday
                         (`block_model.block_weeks`), Monday-to-Sunday like the May tracker's weeks.
  * `assemble_evidence`  arranges what the platform already measured — the May tracker's WEEK# rows, the
                         panel rubric's weekly PANEL# grades, the owner's DELOAD# / disruption records and the
                         counts the skill reads through MCP tools (`supplied`) — into labelled cells
                         `{state: measured|absent, value, source}`. Absent is never zero (ADR-104).
  * `code_scores`        each row's `code_rules` over the evidence: `share` (numerator / denominator x 10) and
                         `panel_mean` (C5's rubric criteria, averaged over the block's weekly grades).
  * `panel_regrade`      the model half: ONE call per panel seat (the charter's concession-ledger schools, the
                         same seats as `config/panel_rubric.json`), back-to-back on route `charter.retro`
                         (feature `charter_retro`, band 1) with the owner-only charter block cached
                         (`charter_ai.system_blocks`). Budget-checked; a paused or failed seat is named, never
                         filled in. A laptop run is also held by the dev-session cap inside `bedrock_client`.
  * `grade`              code score and the panel median combine per `combine_rule`; letters from the
                         scorecard's scale; movers against the previous retro (or the 2026-10-18 baseline);
                         every grade below `grade_scale.fix_below` becomes a named fix.
  * `grade_predictions`  the four dated charter predictions (#5089, `diary_claims` PREDICTION# rows, status
                         `observation`) are graded MECHANICALLY by their own `measurement` block once their
                         `grade_by` has passed. `evaluate_prediction` (the MCP tool) only edits coach-thread
                         arrays and cannot reach that partition (`scripts/register_charter_predictions.py`), so
                         the verdicts are written by `scripts/training_block_retro.py --apply`.
  * `retro_item`         the owner-only row `USER#matthew#SOURCE#training_constraints / RETRO#<block_end>`.
  * `render_markdown`    the human-readable retro for the owner's PRIVATE review doc (never a public page).

PRIVACY. Every output here is owner-only: the grades, the evidence, the target-bearing May-tracker cells.
Nothing in this module is imported by `lambdas/web/` or `lambdas/emails/` (`tests/test_block_retro_5079.py`).
"""

from __future__ import annotations

import json
import logging
import re
import statistics
from typing import Any, Callable, Iterable, Mapping, Optional

from common import repo_config

logger = logging.getLogger(__name__)

RETRO_VERSION = "block-retro@1.0.0"
SCORECARD_BASENAME = "training_scorecard.json"
ROUTE = "charter.retro"
RETRO_SK_PREFIX = "RETRO#"
MAX_TOKENS = 2500
MEASURED, ABSENT = "measured", "absent"
GRADED_BY = "block_retro_5079"
PREDICTION_OPEN_STATUSES = ("observation",)

INSTRUCTIONS = (
    "BLOCK RETRO — ONE PANEL SEAT\n\n"
    "You are one seat of an expert training panel, re-grading a fixed thirteen-row scorecard at the end of a "
    "training block. The charter above names what each school concedes to the deadline and what it gets in return "
    "(concession_ledger). Grade from the evidence only: each row lists the platform reads it is graded from and, "
    "where code could score it, that code score. A row whose inputs are absent is graded on what IS there, and "
    "your reason says what was missing. Score each row 0-10 (10 = exemplary for this trainee under this charter, "
    "9 = meets the bar, 7 = a visible gap, 5 = half there, 0 = absent or contrary), with one short reason naming "
    "the evidence. Then say whether the block delivered what your seat was promised for its concession.\n\n"
    "Return JSON only, in the schema given. No preamble.\n\n"
)


# ── the scorecard ─────────────────────────────────────────────────────────────────────────
def load_scorecard(path: Optional[str] = None) -> Optional[dict[str, Any]]:
    """`config/training_scorecard.json`, or None when unreadable (the retro then refuses, saying so)."""
    p = path or repo_config.config_path(SCORECARD_BASENAME)
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        logger.warning("block_retro: %s unreadable (%s)", SCORECARD_BASENAME, type(e).__name__)
        return None
    return data if isinstance(data, dict) and isinstance(data.get("rows"), list) else None


def letter_for(score: float, scorecard: Mapping[str, Any]) -> str:
    letters = scorecard["grade_scale"]["letters"]
    for row in letters:
        if score >= float(row["min"]):
            return str(row["letter"])
    return str(letters[-1]["letter"])


def letter_rank(letter: Optional[str], scorecard: Mapping[str, Any]) -> Optional[int]:
    """Higher is better; None for a letter the scale does not carry."""
    order = [str(r["letter"]) for r in scorecard["grade_scale"]["letters"]]
    return len(order) - order.index(letter) if letter in order else None


def below_fix_line(letter: Optional[str], scorecard: Mapping[str, Any]) -> bool:
    rank, line = letter_rank(letter, scorecard), letter_rank(scorecard["grade_scale"]["fix_below"], scorecard)
    return rank is not None and line is not None and rank < line


# ── the window ────────────────────────────────────────────────────────────────────────────
def block_window(block_end: str) -> dict[str, Any]:
    """`{start, end, weeks}` for the block ending on `block_end` (a Sunday, Pacific day key)."""
    from common.pacific_time import parse_day_key, shift_day_key

    from training import block_model

    d = parse_day_key(str(block_end)[:10])
    if d is None:
        raise ValueError(f"block_retro: not a day key: {block_end!r}")
    if d.weekday() != 6:
        raise ValueError(f"block_retro: a block ends on a Sunday (the May tracker's week end); {block_end} is not one")
    weeks = block_model.block_weeks()
    return {"start": shift_day_key(d.isoformat(), -(weeks * 7 - 1)), "end": d.isoformat(), "weeks": weeks}


def _in(day: Any, window: Mapping[str, Any]) -> bool:
    d = str(day or "")[:10]
    return bool(d) and window["start"] <= d <= window["end"]


# ── evidence ──────────────────────────────────────────────────────────────────────────────
def cell(state: str, value: Any, source: str, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"state": state, "value": value if state == MEASURED else None, "source": source}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _measured(value: Any, source: str, **extra: Any) -> dict[str, Any]:
    return cell(MEASURED if value is not None else ABSENT, value, source, **extra)


def _cv(path: str, default: Any = None) -> Any:
    from training.training_charter import charter_value

    return charter_value(path, default)


def _weight_evidence(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    src = "may_tracker WEEK# rows: weight.band_position_week (the charter band via training.rate_band)"
    positions = {r.get("week_end"): (r.get("weight") or {}).get("band_position_week") for r in rows}
    counted = [p for p in positions.values() if p is not None]
    last_r4 = None
    for r in rows:
        r4 = ((r.get("weight") or {}).get("rate_4wk") or {}).get("value")
        last_r4 = r4 if r4 is not None else last_r4
    return {
        "weeks_counted": _measured(len(counted) if counted else None, src),
        "weeks_in_band": _measured(sum(1 for p in counted if p == "in") if counted else None, src),
        "positions": _measured(positions or None, src),
        "rate_4wk_last": _measured(last_r4, "may_tracker weight.rate_4wk (lb/wk)"),
    }


def _waist_evidence(rows: list[Mapping[str, Any]], window: Mapping[str, Any]) -> dict[str, Any]:
    src = "may_tracker waist (the latest tape row per week)"
    dates = sorted({str((r.get("waist") or {}).get("date")) for r in rows if (r.get("waist") or {}).get("state") == MEASURED})
    in_block = [d for d in dates if _in(d, window)]
    latest = next((dict(r["waist"]) for r in reversed(rows) if (r.get("waist") or {}).get("state") == MEASURED), None)
    return {"tape_rows": _measured(len(in_block) if rows else None, src, dates=in_block or None), "latest": _measured(latest, src)}


def _anchor_evidence(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    src = "may_tracker anchors (plan_engine.anchor_e1rm_trend per core anchor)"
    tripped = sorted({f for r in rows for f, a in (((r.get("anchors") or {}).get("anchors")) or {}).items() if a.get("tripped")})
    last = (((rows[-1].get("anchors") or {}).get("anchors")) or {}) if rows else {}
    measured = sorted(f for f, a in last.items() if a.get("state") == MEASURED)
    if not measured:
        return {k: cell(ABSENT, None, src) for k in ("measured", "held", "down_at_end", "tripped_any_week")}
    down = sorted(f for f in measured if last[f].get("down"))
    held = [f for f in measured if f not in down and f not in tripped]
    return {
        "measured": cell(MEASURED, len(measured), src, families=measured),
        "held": cell(MEASURED, len(held), src, families=held),
        "down_at_end": cell(MEASURED, len(down), src, families=down or None),
        "tripped_any_week": cell(MEASURED, len(tripped), src, families=tripped or None),
    }


def _tracker_steps(row: Mapping[str, Any]) -> Mapping[str, Any]:
    return row.get("steps") or {}  # steps-truth: the May tracker's steps SECTION (built from steps_resolver), not a source row


def _steps_evidence(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    src = "may_tracker steps (training.steps_resolver days vs the charter floor and target)"
    weeks = [w for w in map(_tracker_steps, rows) if w.get("state") == MEASURED]
    if not weeks:
        return {k: cell(ABSENT, None, src) for k in ("days_measured", "days_at_floor", "days_at_target")}
    total = {k: sum(int(w.get(k) or 0) for w in weeks) for k in ("days_measured", "days_at_floor", "days_at_target")}
    return {k: cell(MEASURED, v, src, weeks=len(weeks)) for k, v in total.items()}


def _panel_evidence(panel_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    src = "PANEL# weekly grades (config/panel_rubric.json via training.panel_judge)"
    if not panel_rows:
        return {k: cell(ABSENT, None, src) for k in ("weeks_graded", "overall_mean", "criteria_means", "degraded_weeks")}
    sums: dict[str, list[float]] = {}
    for r in panel_rows:
        for seat, s in (r.get("seats") or {}).items():
            for crit, c in ((s or {}).get("criteria") or {}).items():
                if isinstance((c or {}).get("score"), (int, float)):
                    sums.setdefault(f"{seat}.{crit}", []).append(float(c["score"]))
    overall = [float(r["overall_score"]) for r in panel_rows if isinstance(r.get("overall_score"), (int, float))]
    return {
        "weeks_graded": cell(MEASURED, len(panel_rows), src, week_ends=sorted(str(r.get("week_end")) for r in panel_rows)),
        "overall_mean": _measured(round(statistics.mean(overall), 2) if overall else None, src),
        "criteria_means": _measured({k: round(statistics.mean(v), 2) for k, v in sorted(sums.items())} or None, src),
        "degraded_weeks": cell(MEASURED, sum(1 for r in panel_rows if r.get("degraded")), src),
    }


def _calibration_evidence(window: Mapping[str, Any], waist: Mapping[str, Any], fitness_in_block: bool) -> dict[str, Any]:
    """Due vs done for the charter's calibration cadence over the block: tape + photos, the fitness battery."""
    src = "charter calibration.* cadence; tape from the May tracker, the battery from the fitness record"
    weeks = int(window["weeks"])
    tape_every = _cv("calibration.tape_and_photos.every_weeks")
    fit_every = _cv("calibration.fitness_tests.every_weeks")
    detail: dict[str, Any] = {}
    due = done = 0
    if isinstance(tape_every, int) and tape_every > 0:
        tape_due, tape_done = weeks // tape_every, int((waist.get("tape_rows") or {}).get("value") or 0)
        detail["tape_and_photos"] = {"due": tape_due, "done": tape_done, "every_weeks": tape_every}
        due, done = due + tape_due, done + min(tape_done, tape_due)
    if isinstance(fit_every, int) and fit_every > 0:
        fit_due = weeks // fit_every
        detail["fitness_tests"] = {"due": fit_due, "done": int(fitness_in_block), "every_weeks": fit_every}
        due, done = due + fit_due, done + min(int(fitness_in_block), fit_due)
    if not due:
        return {k: cell(ABSENT, None, src) for k in ("due", "done", "detail")}
    return {"due": cell(MEASURED, due, src), "done": cell(MEASURED, done, src), "detail": cell(MEASURED, detail, src)}


def _supplied(supplied: Mapping[str, Any], section: str, key: str, source: str) -> dict[str, Any]:
    v = (supplied.get(section) or {}).get(key)
    return _measured(v, source)


def _loop_evidence(window: Mapping[str, Any], may_rows: list[Mapping[str, Any]], panel_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """A week's planning loop CLOSED when its May-tracker row exists and its panel grade is not degraded."""
    src = "may_tracker WEEK# + PANEL# rows per block week"
    tracked = {str(r.get("week_end")) for r in may_rows}
    clean = {str(r.get("week_end")) for r in panel_rows if not r.get("degraded")}
    return {"weeks": cell(MEASURED, int(window["weeks"]), src), "weeks_closed": cell(MEASURED, len(tracked & clean), src)}


def assemble_evidence(
    window: Mapping[str, Any],
    *,
    may_rows: Iterable[Mapping[str, Any]] = (),
    panel_rows: Iterable[Mapping[str, Any]] = (),
    deload_records: Iterable[Mapping[str, Any]] = (),
    disruption_records: Iterable[Mapping[str, Any]] = (),
    supplied: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Every row input, as labelled cells. The stored rows are filtered to the block; `supplied` carries the counts
    the skill reads through MCP tools (sessions, sleep, progression, cardio, planning, fitness) — see the skill."""
    sup = dict(supplied or {})
    may = sorted((dict(r) for r in may_rows if _in(r.get("week_end"), window)), key=lambda r: str(r.get("week_end")))
    panel = sorted((dict(r) for r in panel_rows if _in(r.get("week_end"), window)), key=lambda r: str(r.get("week_end")))
    waist = _waist_evidence(may, window)
    fit_rows = [r["fitness_tests"] for r in may if (r.get("fitness_tests") or {}).get("state") == MEASURED]
    battery = sup.get("fitness", {}).get("battery") if isinstance(sup.get("fitness"), dict) else None
    battery = battery if battery is not None else (fit_rows[-1].get("value") if fit_rows else None)
    weeks = int(window["weeks"])
    days, cond = _cv("split.lifting_days_per_wk"), _cv("cardio_menu.conditioning_sessions_per_wk")
    prog = sup.get("progression") or {}
    opportunities = None
    if prog.get("steps_taken") is not None and prog.get("step_due") is not None:
        opportunities = int(prog["steps_taken"]) + int(prog["step_due"])
    deloads = [dict(r) for r in deload_records if _in(r.get("start_date"), window)]
    modes = [dict(r) for r in disruption_records if _overlaps(r, window)]
    return {
        "window": dict(window),
        "weight": _weight_evidence(may),
        "waist": waist,
        "anchors": _anchor_evidence(may),
        "steps": _steps_evidence(may),
        "panel": _panel_evidence(panel),
        "fitness": {"battery": _measured(battery, "fitness-test battery (#5078) or the May tracker's fitness cell")},
        "calibration": _calibration_evidence(window, waist, battery is not None),
        "sessions": {
            "logged": _supplied(sup, "sessions", "logged", "Hevy lifting workouts in the block (get_training_load / Hevy)"),
            "planned": _measured(int(days) * weeks if isinstance(days, int) else None, "charter split.lifting_days_per_wk x block weeks"),
            "distinct_movements": _supplied(sup, "sessions", "distinct_movements", "distinct Hevy movements logged in the block"),
        },
        "sleep": {
            k: _supplied(sup, "sleep", k, "the sleep tools over the block (get_sleep_analysis)")
            for k in ("nights", "mean_hours", "consistency")
        },
        "progression": {
            "steps_taken": _supplied(sup, "progression", "steps_taken", "load steps logged (get_exercise_history, double progression)"),
            "step_due": _supplied(sup, "progression", "step_due", "stall_detector step_due verdicts in the block"),
            "stalls": _supplied(sup, "progression", "stalls", "stall_detector stall verdicts in the block"),
            "step_opportunities": _measured(opportunities, "steps_taken + step_due"),
        },
        "cardio": {
            "conditioning_sessions": _supplied(sup, "cardio", "conditioning_sessions", "conditioning blocks logged in the block"),
            "conditioning_target": _measured(int(cond) * weeks if isinstance(cond, int) else None, "charter cardio_menu x block weeks"),
        },
        "planning": {
            "custom_departures": _supplied(sup, "planning", "custom_departures", "draft_custom commits with a departure_reason"),
            "committed_plans": _supplied(sup, "planning", "committed_plans", "committed routines in the block"),
        },
        "loop": _loop_evidence(window, may, panel),
        "deload": {
            "records": cell(MEASURED, deloads, "training_constraints DELOAD# (the owner's recorded word)"),
            "recommendations": _supplied(sup, "deload", "recommendations", "deload_recommendation active days"),
        },
        "disruption": {"records": cell(MEASURED, modes, "training_constraints MODE#disruption")},
    }


def _overlaps(rec: Mapping[str, Any], window: Mapping[str, Any]) -> bool:
    start = str(rec.get("start_date") or "")[:10]
    end = str(rec.get("ended_on") or rec.get("until") or start)[:10]
    return bool(start) and start <= window["end"] and end >= window["start"]


def ev(evidence: Mapping[str, Any], dotted: str) -> dict[str, Any]:
    section, _, key = dotted.partition(".")
    c = (evidence.get(section) or {}).get(key)
    return dict(c) if isinstance(c, dict) else cell(ABSENT, None, f"no evidence key {dotted}")


# ── code scores ───────────────────────────────────────────────────────────────────────────
def _rule_share(rule: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[Optional[float], str]:
    num, den = ev(evidence, rule["numerator"]), ev(evidence, rule["denominator"])
    if num["state"] != MEASURED or den["state"] != MEASURED or not den["value"]:
        return None, f"{rule['numerator']} / {rule['denominator']}: not measured"
    share = min(1.0, float(num["value"]) / float(den["value"]))
    return round(10 * share, 2), f"{rule['numerator']} / {rule['denominator']} = {num['value']}/{den['value']}"


def _rule_panel_mean(rule: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[Optional[float], str]:
    means = ev(evidence, "panel.criteria_means")
    have = {c: means["value"][c] for c in rule["criteria"] if means["state"] == MEASURED and c in means["value"]}
    if not have:
        return None, "no weekly panel grade carries these criteria"
    missing = [c for c in rule["criteria"] if c not in have]
    note = f"; not graded: {', '.join(missing)}" if missing else ""
    return round(statistics.mean(have.values()), 2), f"panel mean over {len(have)} criteria{note}"


RULES: dict[str, Callable[[Mapping[str, Any], Mapping[str, Any]], tuple[Optional[float], str]]] = {
    "share": _rule_share,
    "panel_mean": _rule_panel_mean,
}


def code_scores(scorecard: Mapping[str, Any], evidence: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Row -> {score (the mean of its measured rules, or None), rules [{kind, score, evidence}], inputs}."""
    out: dict[str, dict[str, Any]] = {}
    for row in scorecard["rows"]:
        rules = [
            {"kind": r["kind"], **dict(zip(("score", "evidence"), RULES[r["kind"]](r, evidence)))} for r in row.get("code_rules") or []
        ]
        scored = [r["score"] for r in rules if r["score"] is not None]
        out[row["id"]] = {
            "score": round(statistics.mean(scored), 2) if scored else None,
            "rules": rules,
            "inputs": {k: ev(evidence, k) for k in row.get("inputs") or []},
        }
    return out


# ── the panel re-grade (the model half) ───────────────────────────────────────────────────
def seats() -> list[str]:
    """The panel: the charter's concession-ledger schools (one call each — the cache register's calls_within_ttl)."""
    return sorted((_cv("concession_ledger", {}) or {}).keys())


def response_schema(scorecard: Mapping[str, Any]) -> dict[str, Any]:
    ids = [r["id"] for r in scorecard["rows"]]
    row = {
        "type": "object",
        "properties": {"score": {"type": "integer"}, "why": {"type": "string"}},
        "required": ["score", "why"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "rows": {"type": "object", "properties": {i: row for i in ids}, "required": ids, "additionalProperties": False},
            "concession_held": {"type": "boolean"},
        },
        "required": ["rows", "concession_held"],
        "additionalProperties": False,
    }


def evidence_text(scorecard: Mapping[str, Any], codes: Mapping[str, Any]) -> str:
    """The per-row packet one seat reads: label, inputs (state + value) and the code score."""
    lines = []
    for row in scorecard["rows"]:
        c = codes[row["id"]]
        inputs = {k: (v.get("value") if v.get("state") == MEASURED else v.get("state")) for k, v in c["inputs"].items()}
        lines.append(
            f"- {row['id']} ({row['label']}): code score {c['score'] if c['score'] is not None else 'none'}; "
            f"inputs {json.dumps(inputs, sort_keys=True, default=str)}" + (f"; note: {row['note']}" if row.get("note") else "")
        )
    return "\n".join(lines)


def build_body(seat: str, scorecard: Mapping[str, Any], codes: Mapping[str, Any], window: Mapping[str, Any]) -> dict[str, Any]:
    from training import charter_ai

    volatile = INSTRUCTIONS + f"YOUR SEAT: {seat}\n"
    return {
        "max_tokens": MAX_TOKENS,
        "temperature": 0,
        "system": charter_ai.system_blocks(ROUTE, volatile),
        "messages": [
            {
                "role": "user",
                "content": f"BLOCK {window['start']}..{window['end']} ({window['weeks']} weeks)\n\nROWS\n"
                + evidence_text(scorecard, codes),
            }
        ],
    }


def parse_seat(parsed: Any, scorecard: Mapping[str, Any]) -> dict[str, Any]:
    """{rows: {id: {score 0-10, why}}, concession_held}. A row the reply lacks is left out, never filled in."""
    rows: dict[str, Any] = {}
    raw = parsed.get("rows") if isinstance(parsed, dict) else None
    raw = raw if isinstance(raw, dict) else {}
    for r in scorecard["rows"]:
        v = raw.get(r["id"])
        if not isinstance(v, dict):
            continue
        s = v.get("score")
        if isinstance(s, (int, float)) and not isinstance(s, bool):
            rows[r["id"]] = {"score": max(0.0, min(10.0, float(s))), "why": str(v.get("why") or "")[:300]}
    held = parsed.get("concession_held") if isinstance(parsed, dict) else None
    return {"rows": rows, "concession_held": held if isinstance(held, bool) else None}


def _metered(transport: Callable[[dict[str, Any]], dict[str, Any]], usage: dict[str, Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def call(body: dict[str, Any]) -> dict[str, Any]:
        resp = transport(body)
        usage.update((resp or {}).get("usage") or {})
        return resp

    return call


def panel_regrade(
    scorecard: Mapping[str, Any],
    codes: Mapping[str, Any],
    window: Mapping[str, Any],
    *,
    call: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
) -> dict[str, Any]:
    """One call per seat, back-to-back. `call` is the transport (tests pass a replay; None = Bedrock on the route's
    model after the budget check). Never raises: a paused, failed or unparsed seat is recorded by name."""
    from ai import structured_json

    from training import panel_judge

    if call is None:
        ok, why = panel_judge._allowed(ROUTE)
        if not ok:
            return {"status": "paused", "reason": why, "seats": {}, "usage": {}}
    usage: dict[str, int] = {}
    out: dict[str, Any] = {}
    transport = call
    for seat in seats():
        try:
            transport = transport or panel_judge._bedrock_call(ROUTE)
            seat_usage: dict[str, Any] = {}
            parsed = structured_json.call_json(
                _metered(transport, seat_usage), build_body(seat, scorecard, codes, window), response_schema(scorecard), label="block_retro"
            )
            for k, v in seat_usage.items():
                if isinstance(v, int):
                    usage[k] = usage.get(k, 0) + v
            got = parse_seat(parsed, scorecard)
            out[seat] = {"status": "ok" if got["rows"] else "unparsed", **got}
        except Exception as e:  # noqa: BLE001 — a failed seat is named on the retro, never a fabricated score
            logger.warning("block_retro: seat %s failed (%s)", seat, type(e).__name__)
            out[seat] = {"status": "error", "reason": f"{type(e).__name__}: {str(e)[:200]}", "rows": {}, "concession_held": None}
    ok = [s for s, v in out.items() if v["status"] == "ok"]
    status = "ok" if len(ok) == len(out) else ("partial" if ok else "failed")
    return {"status": status, "route": ROUTE, "seats": out, "usage": usage}


# ── combining, movers, fixes ──────────────────────────────────────────────────────────────
def _prior_letters(scorecard: Mapping[str, Any], prior: Optional[Mapping[str, Any]]) -> tuple[dict[str, Optional[str]], str]:
    if prior and isinstance(prior.get("rows"), dict):
        return {rid: (r or {}).get("letter") for rid, r in prior["rows"].items()}, f"retro {prior.get('block_end')}"
    return {r["id"]: r.get("baseline_grade") for r in scorecard["rows"]}, f"baseline {scorecard['baseline']['date']}"


def grade(
    scorecard: Mapping[str, Any],
    evidence: Mapping[str, Any],
    codes: Mapping[str, Any],
    panel: Optional[Mapping[str, Any]],
    *,
    prior: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Every row's score + letter, the comparison with the last retro (or the baseline), the movers and the fixes."""
    prior_letters, compared_with = _prior_letters(scorecard, prior)
    seat_rows = {s: v.get("rows") or {} for s, v in ((panel or {}).get("seats") or {}).items()}
    interrupted = bool(ev(evidence, "disruption.records").get("value")) or bool(ev(evidence, "deload.records").get("value"))
    rows: dict[str, Any] = {}
    for spec in scorecard["rows"]:
        rid = spec["id"]
        votes = {s: r[rid]["score"] for s, r in seat_rows.items() if rid in r}
        median = round(statistics.median(votes.values()), 2) if votes else None
        parts = [x for x in (codes[rid]["score"], median) if x is not None]
        score = round(statistics.mean(parts), 2) if parts else None
        letter = letter_for(score, scorecard) if score is not None else None
        before = prior_letters.get(rid)
        carried = letter is None or (spec.get("reference_only") and not interrupted)
        shown = before if carried else letter
        r_now, r_then = letter_rank(shown, scorecard), letter_rank(before, scorecard)
        rows[rid] = {
            "label": spec["label"],
            "score": score,
            "letter": shown,
            "state": ("carried" if letter is None else "reference_carried") if carried else "graded",
            "code_score": codes[rid]["score"],
            "code_rules": codes[rid]["rules"],
            "panel_median": median,
            "seat_scores": votes,
            "seat_reasons": {s: r[rid]["why"] for s, r in seat_rows.items() if rid in r},
            "prior_letter": before,
            "change": (r_now - r_then) if r_now is not None and r_then is not None else None,
            "fix_route": spec.get("fix_route"),
        }
    movers = sorted((rid for rid, r in rows.items() if r["change"]), key=lambda rid: (-abs(rows[rid]["change"]), rid))
    fixes = [
        {"row": rid, "label": r["label"], "letter": r["letter"], "route": r["fix_route"]}
        for rid, r in rows.items()
        if r["state"] == "graded" and below_fix_line(r["letter"], scorecard)
    ]
    return {
        "rows": rows,
        "compared_with": compared_with,
        "movers": [
            {"row": rid, "from": rows[rid]["prior_letter"], "to": rows[rid]["letter"], "change": rows[rid]["change"]} for rid in movers
        ],
        "fixes": fixes,
        "ungraded": sorted(rid for rid, r in rows.items() if r["state"] == "carried"),
    }


def apply_overrides(graded: dict[str, Any], overrides: Mapping[str, Mapping[str, Any]], scorecard: Mapping[str, Any]) -> dict[str, Any]:
    """The session's recorded departures from the computed letter: each needs a known letter AND a reason."""
    for rid, o in (overrides or {}).items():
        row = graded["rows"].get(rid)
        letter, reason = o.get("letter"), str(o.get("reason") or "").strip()
        if row is None or letter_rank(letter, scorecard) is None or not reason:
            raise ValueError(f"block_retro: override of {rid!r} needs a scorecard row, a scale letter and a reason")
        row["override"] = {"computed": row["letter"], "letter": letter, "reason": reason}
        row["letter"] = letter
        before = letter_rank(row["prior_letter"], scorecard)
        row["change"] = (letter_rank(letter, scorecard) or 0) - before if before is not None else None
    graded["fixes"] = [
        {"row": rid, "label": r["label"], "letter": r["letter"], "route": r["fix_route"]}
        for rid, r in graded["rows"].items()
        if r["state"] == "graded" and below_fix_line(r["letter"], scorecard)
    ]
    graded["movers"] = [
        {"row": rid, "from": r["prior_letter"], "to": r["letter"], "change": r["change"]}
        for rid, r in sorted(graded["rows"].items(), key=lambda kv: (-abs(kv[1]["change"] or 0), kv[0]))
        if r["change"]
    ]
    return graded


# ── the dated charter predictions (#5089) ─────────────────────────────────────────────────
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


def _window_of(measurement: Mapping[str, Any]) -> tuple[str, str]:
    """The first and last day key the measurement's `window` names (`2026-10-19..2026-12-06`, or prose around two days)."""
    days = _DAY.findall(str(measurement.get("window") or ""))
    return (days[0], days[-1]) if days else ("", "")


def _grade_steps_share(m: Mapping[str, Any], may_rows: list[Mapping[str, Any]], _sup: Mapping[str, Any]) -> tuple[str, Any]:
    start, end = _window_of(m)
    in_window = [r for r in may_rows if start <= str(r.get("week_start")) and str(r.get("week_end")) <= end]
    weeks = [w for w in map(_tracker_steps, in_window) if w.get("state") == MEASURED]
    measured = sum(int(w.get("days_measured") or 0) for w in weeks)
    at = sum(int(w.get("days_at_floor") or 0) for w in weeks)
    if not measured:
        return "inconclusive", {"weeks": 0, "reason": "no measured step day in the window"}
    share = round(at / measured, 3)
    return ("confirmed" if share >= float(m["threshold"]) else "refuted"), {"days_measured": measured, "days_at_floor": at, "share": share}


def _grade_rate_weeks(m: Mapping[str, Any], may_rows: list[Mapping[str, Any]], _sup: Mapping[str, Any]) -> tuple[str, Any]:
    """Weekly reads whose week_end falls in the window: a counted rate inside the prediction's OWN frozen band is a hit,
    a counted rate outside it a miss, no counted rate a missing week (never a miss)."""
    from common.pacific_time import shift_day_key

    lo, hi = (float(x) for x in m["band_lb_wk"])
    first, last = _window_of(m)
    ends, d = [], first
    while d and d <= last:
        ends.append(d)
        d = shift_day_key(d, 7)
    by_end = {str(r.get("week_end")): r for r in may_rows}
    rates: dict[str, Any] = {}
    for e in ends:
        rw = ((by_end.get(e) or {}).get("weight") or {}).get("rate_week") or {}
        rates[e] = rw.get("value") if rw.get("counted") and rw.get("value") is not None else None
    hits = sum(1 for v in rates.values() if v is not None and lo <= float(v) <= hi)
    misses = sum(1 for v in rates.values() if v is not None and not lo <= float(v) <= hi)
    need = int(m["threshold"])
    verdict = "confirmed" if hits >= need else ("refuted" if len(ends) - misses < need else "inconclusive")
    return verdict, {"in_band": hits, "out_of_band": misses, "missing": len(ends) - hits - misses, "rates": rates}


def _grade_anchor_up(_m: Mapping[str, Any], _rows: list[Mapping[str, Any]], sup: Mapping[str, Any]) -> tuple[str, Any]:
    lifts = sup.get("anchor_e1rm") or {}
    if not lifts:
        return "inconclusive", {"reason": "no anchor e1RM baseline/current was supplied"}
    worse = sorted(k for k, v in lifts.items() if v.get("current") is not None and float(v["current"]) <= float(v["baseline"]))
    missing = sorted(k for k, v in lifts.items() if v.get("current") is None)
    verdict = "refuted" if worse else ("inconclusive" if missing else "confirmed")
    return verdict, {"lifts": lifts, "not_above_baseline": worse, "no_post_baseline_session": missing}


def _grade_no_stalls(_m: Mapping[str, Any], _rows: list[Mapping[str, Any]], sup: Mapping[str, Any]) -> tuple[str, Any]:
    moves = {k: v for k, v in (sup.get("accessory_stalls") or {}).items() if v.get("scored")}
    if not moves:
        return "inconclusive", {"reason": "no accessory movement had 3 sessions in the window"}
    stalled = sorted(k for k, v in moves.items() if int(v.get("stall_runs") or 0) > 0)
    return ("refuted" if stalled else "confirmed"), {"scored": sorted(moves), "stalled": stalled}


PREDICTION_GRADERS: dict[str, Callable[..., tuple[str, Any]]] = {
    "steps_floor_90pct": _grade_steps_share,
    "rate_in_band_4_of_6": _grade_rate_weeks,
    "anchor_e1rm_up": _grade_anchor_up,
    "zero_accessory_stalls": _grade_no_stalls,
}


def grade_predictions(
    predictions: Iterable[Mapping[str, Any]],
    as_of: str,
    may_rows: Iterable[Mapping[str, Any]],
    supplied: Optional[Mapping[str, Any]] = None,
) -> list[dict[str, Any]]:
    """Every OPEN charter prediction whose `grade_by` has passed by `as_of`, graded by its own measurement block.
    A metric with no grader is reported `unsupported` and left open."""
    rows = sorted((dict(r) for r in may_rows), key=lambda r: str(r.get("week_end")))
    out = []
    for p in predictions:
        if p.get("evaluation", {}).get("graded_by") != GRADED_BY or p.get("status") not in PREDICTION_OPEN_STATUSES:
            continue
        if not p.get("grade_by") or str(p["grade_by"]) > as_of:
            continue
        g = PREDICTION_GRADERS.get(str(p.get("metric")))
        verdict, detail = g(p.get("measurement") or {}, rows, supplied or {}) if g else ("unsupported", {"reason": "no grader"})
        out.append(
            {
                "pk": p.get("pk"),
                "sk": p.get("sk"),
                "metric": p.get("metric"),
                "claim": p.get("claim_natural"),
                "verdict": verdict,
                "evidence": detail,
            }
        )
    return out


# ── the stored row and the private doc tab ────────────────────────────────────────────────
def retro_item(retro: Mapping[str, Any], user_pk: str = "USER#matthew") -> dict[str, Any]:
    """The owner-only row `<user_pk>#SOURCE#training_constraints / RETRO#<block_end>` (docs/SCHEMA.md)."""
    from training.training_charter import charter_version

    w = retro["window"]
    return {
        "pk": f"{user_pk}#SOURCE#training_constraints",
        "sk": f"{RETRO_SK_PREFIX}{w['end']}",
        "block_start": w["start"],
        "block_end": w["end"],
        "block_weeks": w["weeks"],
        "rows": retro["graded"]["rows"],
        "compared_with": retro["graded"]["compared_with"],
        "movers": retro["graded"]["movers"],
        "fixes": retro["graded"]["fixes"],
        "ungraded": retro["graded"]["ungraded"],
        "predictions": [{k: p[k] for k in ("sk", "metric", "verdict", "evidence")} for p in retro.get("predictions") or []],
        "panel": {k: (retro.get("panel") or {}).get(k) for k in ("status", "route", "usage", "reason")},
        "scorecard_version": retro.get("scorecard_version"),
        "charter_version": retro.get("charter_version") or charter_version(),
        "version": RETRO_VERSION,
        "tier": "owner_only",
    }


def render_markdown(retro: Mapping[str, Any]) -> str:
    """The retro as the owner reads it — the new tab in his PRIVATE review doc. Never a published surface."""
    w, g = retro["window"], retro["graded"]
    out = [f"## Block retro {w['start']} to {w['end']} ({w['weeks']} weeks)", "", f"Compared with: {g['compared_with']}.", ""]
    out += ["| Row | Before | Now | Code | Panel | State |", "|---|---|---|---|---|---|"]
    for r in g["rows"].values():
        out.append(
            f"| {r['label']} | {r['prior_letter'] or '-'} | {r['letter'] or '-'} | {r['code_score']} | {r['panel_median']} | {r['state']} |"
        )
    out += ["", "**Movers:** " + ("; ".join(f"{m['row']} {m['from']} -> {m['to']}" for m in g["movers"]) or "none")]
    out += [
        "",
        "**Fixes (below the fix line):** " + ("; ".join(f"{f['label']} ({f['letter']}, via {f['route']})" for f in g["fixes"]) or "none"),
    ]
    if g["ungraded"]:
        out += ["", "**Ungraded (no evidence, grade carried):** " + ", ".join(g["ungraded"])]
    preds = retro.get("predictions") or []
    if preds:
        out += ["", "**Charter predictions graded:**"] + [f"- {p['metric']}: {p['verdict']}" for p in preds]
    out += ["", f"Panel re-grade: {(retro.get('panel') or {}).get('status')}. Charter {retro.get('charter_version')}."]
    return "\n".join(out) + "\n"


def run(
    block_end: str,
    *,
    scorecard: Optional[Mapping[str, Any]] = None,
    may_rows: Iterable[Mapping[str, Any]] = (),
    panel_rows: Iterable[Mapping[str, Any]] = (),
    deload_records: Iterable[Mapping[str, Any]] = (),
    disruption_records: Iterable[Mapping[str, Any]] = (),
    predictions: Iterable[Mapping[str, Any]] = (),
    prior: Optional[Mapping[str, Any]] = None,
    supplied: Optional[Mapping[str, Any]] = None,
    call: Optional[Callable[[dict[str, Any]], dict[str, Any]]] = None,
    with_panel: bool = True,
) -> dict[str, Any]:
    """The whole retro, pure but for the (injectable) panel transport. Readers live in scripts/training_block_retro.py."""
    from training.training_charter import charter_version

    sc = scorecard or load_scorecard()
    if sc is None:
        return {"status": "no_scorecard", "reason": f"config/{SCORECARD_BASENAME} unreadable"}
    window = block_window(block_end)
    may = list(may_rows)
    evidence = assemble_evidence(
        window, may_rows=may, panel_rows=panel_rows, deload_records=deload_records, disruption_records=disruption_records, supplied=supplied
    )
    codes = code_scores(sc, evidence)
    panel = panel_regrade(sc, codes, window, call=call) if with_panel else {"status": "skipped", "seats": {}, "usage": {}}
    return {
        "status": "graded",
        "window": window,
        "evidence": evidence,
        "graded": grade(sc, evidence, codes, panel, prior=prior),
        "panel": panel,
        "predictions": grade_predictions(predictions, window["end"], may, supplied),
        "scorecard_version": sc.get("version"),
        "charter_version": charter_version(),
    }
