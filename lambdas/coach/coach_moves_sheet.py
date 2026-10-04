"""coach_moves_sheet.py — the day's ONE fact sheet and the code that refuses a line (#4583).

THE DEFECT (served 2026-10-03)
  The coaches' daily text was numbers restated, and the coaches disagreed with the site
  and with each other: the mind coach said the journal "has been silent for eleven days"
  where `/api/character` served 24; the nutrition coach said "logging resumed on October
  1st" while the physical coach said "food logging has been quiet for four days". Each
  coach was grounded on its OWN inputs, so nothing made two coaches cite one value.

THE SHAPE
  One fact sheet per day, built ONCE in code from values the site already serves, and
  every line any coach writes that day is judged against it:

    * the head coach's daily lead read `cited` block — served as `lead_daily.cited` on
      `/api/coaching-dashboard` (weight, rate, recovery, heart-rate variability, resting
      heart rate, sleep, protein, the day of the experiment);
    * the per-pillar absence record — `web.site_api_character._attach_pillar_absence`,
      the function `/api/character` serves `pillars[].absence` from (journal, food log,
      training log: last entry and days since);
    * the food-logging record — `coach.coach_input_facts.nutrition_record`, the
      derivation `/api/nutrition_overview` serves (days logged, protein average);
    * the sidelined coaches — `health.instrument_presence.absent_coaches`, the call
      `/api/coaching-dashboard` marks `absent` + `reason` from;
    * the graded results of the last few days (PREDICTION# confirmed/refuted rows — the
      ledger `/api/predictions` serves).

  Each coach's last public position and yesterday's lines ride along as CONTEXT, with
  every figure masked to "[n]": a value only ever reaches a line from the sheet.

WHAT `check_line` REFUSES (code, never the model — ADR-105)
  * a line that only restates numbers: more than MAX_FIGURES figures, or no opinion in
    the first person, or the move it was cast for not made (a "question" with no
    question, a "reply" that names nobody, a "change of mind" that changes nothing);
  * a value that is not on the sheet (digits AND spelled-out counts with a unit —
    "eleven days" is a figure), a date not on the sheet, a stale "Day N";
  * a served-fact contradiction (`coach_input_facts.served_fact_findings`) and the
    reader check classes (`coach.reader_checks.reader_findings` — absence premise,
    unit figure not served, unlabeled average, raw instant, banned jargon);
  * the standing reader rules: second person, a causal connective (ER-03's list), a "Dr." honorific, a reset/restart/attempt
    or numbered cycle, a calorie or deficit figure, words put in Matthew's mouth (a quote
    in the first person), and the privacy vocabulary (`privacy.privacy_guard`).
  `cross_line_findings` then refuses a later line that binds a different value to a
  metric an earlier line already cited.

Pure apart from `read_inputs` (DynamoDB reads only, every one fail-soft).
"""

from __future__ import annotations

import logging
import re
from datetime import timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)

MAX_WORDS = 55
MAX_FIGURES = 2  # a move may lean on two figures; three is a recitation
GRADED_LOOKBACK_DAYS = 2
MAX_GRADED = 8  # the newest distinct graded claims; measured 2026-10-03: 40 in three days
MOVES = ("call", "reaction", "reply", "question", "change_of_mind")
MOVE_WORDS = {
    "call": "a call — what he expects to happen next, said plainly enough to be wrong",
    "reaction": "a reaction to a graded result — what a result that just came in tells him",
    "reply": "a reply to another coach — agreeing or disagreeing with what they said, by name",
    "question": "a question to Matthew — one he could answer, asked about him in the third person",
    "change_of_mind": "a change of mind — what he used to think, and what he thinks now",
}

# The /api/character pillars whose absence record is a fact on the sheet, and the words
# the sheet (and the binding check below) uses for each.
ABSENCE_PILLARS = {
    "mind": ("journal", "his last journal entry", r"\bjournal\w*|\bnotion\b"),
    "nutrition": ("food_log", "his last food log", r"\bfood[-\s]?log\w*|\blogging\b|\blogged\b|\bmacrofactor\b|\bfood\b"),
    "movement": ("training_log", "his last logged workout", r"\bworkouts?\b|\blift\w*|\btraining log\w*|\bhevy\b|\bgym\b"),
}

_NUM_WORDS = {
    w: i
    for i, w in enumerate(
        "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
        "seventeen eighteen nineteen".split()
    )
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_WORD_NUM_RE = re.compile(
    r"\b(?:(" + "|".join(_TENS) + r")(?:[-\s](" + "|".join(list(_NUM_WORDS)[1:10]) + r"))?|(" + "|".join(_NUM_WORDS) + r"))\b",
    re.IGNORECASE,
)
_UNIT_AFTER_RE = re.compile(
    r"^\s*(?:more\s+|straight\s+|consecutive\s+|full\s+|logged\s+)?(?:%|percent|g\b|grams?|kcal|calories|lbs?\b|pounds?|ms\b|bpm|days?|nights?|hours?|weeks?)",
    re.IGNORECASE,
)
_DIGIT_FIGURE_RE = re.compile(r"(?<![\w.])\d[\d,]*(?:\.\d+)?")
_DAY_COUNT_RE = re.compile(r"(?<![\w.])(\d{1,3})\s+(?:straight\s+|consecutive\s+|full\s+)?days?\b", re.IGNORECASE)

# ── the standing reader rules, in code ───────────────────────────────────────
_HONORIFIC_RE = re.compile(r"\bDr\.?\s+[A-Z]")
_RESET_RE = re.compile(
    r"\b(?:re-?sets?|re-?start\w*|attempts?|tries)\b|\b(?:\d+|\w+(?:st|nd|rd|th))\s+(?:cycle|start|run)\b", re.IGNORECASE
)
_CYCLE_RE = re.compile(r"\bcycles?\b", re.IGNORECASE)
_SLEEP_CYCLE_RE = re.compile(r"\bsleep\s+cycles?\b", re.IGNORECASE)
_CALORIE_RE = re.compile(r"\bdeficit\b|\d[\d,]*(?:\.\d+)?\s*(?:kcal|calories|cals?)\b|\bcalories?\b[^.]{0,20}\d", re.IGNORECASE)
_QUOTE_RE = re.compile(r"[\"“”]([^\"“”]{3,})[\"“”]")
_FIRST_PERSON_RE = re.compile(r"\b(?:I|I'm|I've|I'd|I'll|me|my|mine|myself)\b")

# ── an opinion, and each move, in code ───────────────────────────────────────
_STANCE_RE = re.compile(
    r"\bI(?:'m|'ve|'d|'ll| am| have| would| will)?\s+(?:\w+\s+){0,3}?"
    r"(?:think|expect|bet|doubt|suspect|believe|disagree|agree|worry|worried|wrong|right|changed|convinced|calling|"
    r"predict|wager|want|wonder|read|guess|stand|hold|side|back|buy|take|say|see|call|would|was)\b"
    r"|\bmy\s+(?:call|bet|read|question|guess|money|view|worry|concern|position)\b",
    re.IGNORECASE,
)
_CALL_RE = re.compile(
    r"\b(?:expect|bet|predict|calling|wager|will|won't|going to|by (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"next week|the weekend|the end of)|this week|next week|tomorrow)\b",
    re.IGNORECASE,
)
_REACTION_RE = re.compile(
    r"\b(?:right|wrong|missed|landed|called it|came true|did not happen|didn't happen|held up|fell short|graded|"
    r"confirmed|refuted|came in|was off|got it)\b",
    re.IGNORECASE,
)
_CHANGE_RE = re.compile(
    r"\b(?:changed my mind|I was wrong|I no longer|I've changed|I now think|I used to think|I'm revising|I take (?:it )?back|"
    r"I'm reversing|changing my (?:call|view|read|mind)|I've come round|I've come around|I was too)\b",
    re.IGNORECASE,
)
_ABOUT_HIM_RE = re.compile(r"\b(?:Matthew|he|his|him)\b", re.IGNORECASE)
_QUIET_RE = re.compile(
    r"\b(?:quiet|silent|silence|dark|stopped|gap|lapsed|missing|absent|hasn't|has not|no (?:entries|entry|logs?))\b", re.I
)
# A claim that a log CAME BACK (past tense) — "will open again" is a forecast, not a claim.
_RESUMED_RE = re.compile(r"\b(?:resumed|is back|came back|has returned|returned to|picked (?:it )?back up|back on track)\b", re.IGNORECASE)


# ══════════════════════════════════════════════════════════════════════════════
# the sheet
# ══════════════════════════════════════════════════════════════════════════════


def date_in_words(iso: Optional[str]) -> str:
    from coach.lead_daily_read import date_in_words as _diw  # ONE date wording for the sheet and the lead read

    return _diw(iso)


def _fact(out: list, key: str, label: str, value: Any, as_of: Optional[str], source: str) -> None:
    if value is None or str(value) == "":
        return
    out.append({"key": key, "label": label, "value": str(value), "as_of": str(as_of or ""), "source": source})


def _days_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    from common.pacific_time import parse_day_key  # #3609: the one calendar-day parser

    da, db = parse_day_key(str(a or "")[:10]), parse_day_key(str(b or "")[:10])
    return (db - da).days if da and db else None


def mask_figures(text: Any) -> str:
    """Context text with every figure replaced by "[n]" — a value reaches a line only from the sheet."""
    t = _DIGIT_FIGURE_RE.sub("[n]", str(text or ""))
    out, last = [], 0
    for m in _WORD_NUM_RE.finditer(t):
        if _UNIT_AFTER_RE.match(t[m.end() :]):
            out.append(t[last : m.start()] + "[n]")
            last = m.end()
    return "".join(out) + t[last:]


def _lead_facts(lead: Optional[dict], today: str) -> list:
    """The lead read's cited block, when it is today's (or yesterday's) — never an older one."""
    if not isinstance(lead, dict):
        return []
    age = _days_between((lead.get("generated_at") or "")[:10], today)
    if age is None or age > 1:
        return []
    out: list = []
    for c in lead.get("cited") or []:
        if isinstance(c, dict) and c.get("value") not in (None, ""):
            _fact(
                out,
                str(c.get("source_field") or c.get("metric")),
                str(c.get("metric") or ""),
                c["value"],
                c.get("as_of"),
                "lead_daily.cited",
            )
    return out


def _absence_facts(pillars: Optional[list]) -> tuple:
    """(facts, gap) from /api/character's per-pillar absence records."""
    out: list = []
    gap: dict = {}
    for p in pillars or []:
        if not isinstance(p, dict) or p.get("name") not in ABSENCE_PILLARS:
            continue
        key, words, _alias = ABSENCE_PILLARS[p["name"]]
        a = p.get("absence") or {}
        days, last = a.get("days_since_last_log"), a.get("last_log_date")
        src = f"/api/character pillars[{p['name']}].absence"
        _fact(out, f"{key}.state", f"{words.replace('his last ', '')} — logging state", a.get("state"), None, src)
        if last:
            _fact(out, f"{key}.last_date", f"date of {words}", date_in_words(last), last, src)
        if days is not None:
            _fact(out, f"{key}.days_since", f"days since {words}", int(days), None, src)
        if key == "journal" and days is not None:
            gap["journal_gap_days"] = int(days)
    return out, gap


def _nutrition_facts(rec: Optional[dict]) -> tuple:
    out: list = []
    gap: dict = {}
    if not isinstance(rec, dict):
        return out, gap
    src = "/api/nutrition_overview (coach_input_facts.nutrition_record)"
    since = date_in_words(rec.get("window_start"))
    _fact(out, "nutrition.days_logged", f"days with a food log since {since}", rec.get("days_logged"), None, src)
    if rec.get("protein_avg_g") is not None and rec.get("protein_avg_days"):
        _fact(
            out,
            "nutrition.protein_avg_g",
            f"average protein across {int(rec['protein_avg_days'])} logged days (grams a day)",
            f"{float(rec['protein_avg_g']):.1f}",
            None,
            src,
        )
        _fact(out, "nutrition.protein_avg_days", "logged days in that protein average", int(rec["protein_avg_days"]), None, src)
    for k in ("lag_days",):
        if rec.get(k) is not None:
            gap[k] = int(rec[k])
    if rec.get("latest_log_date"):
        gap["last_food_log_date"] = rec["latest_log_date"]
    return out, gap


def _weight_fact(facts: list) -> Optional[dict]:
    """The served weight trajectory, in `coach_input_facts.weight_fact`'s shape, from the lead's cited block."""
    by = {f["key"]: f for f in facts}
    out = {"latest_weight": None, "weekly_rate_lbs": None, "weekly_rate_ci_low": None, "weekly_rate_ci_high": None}
    try:
        if "withings.weight_lbs" in by:
            out["latest_weight"] = float(by["withings.weight_lbs"]["value"])
        rate = by.get("computed_metrics.weekly_rate_lbs")
        if rate:
            sign = -1.0 if "loss" in rate["label"] else 1.0
            out["weekly_rate_lbs"] = sign * float(rate["value"])
            rng = by.get("computed_metrics.weekly_rate_ci")
            if rng:
                a, b = (float(x) for x in rng["value"].split(" to "))
                lo, hi = sorted((sign * a, sign * b))
                out["weekly_rate_ci_low"], out["weekly_rate_ci_high"] = lo, hi
    except (TypeError, ValueError, KeyError):
        pass
    return out if out["latest_weight"] is not None or out["weekly_rate_lbs"] is not None else None


def build_sheet(inputs: dict, today: str) -> dict:
    """The day's fact sheet from the served inputs (`read_inputs`). Pure."""
    inputs = inputs or {}
    facts = _lead_facts(inputs.get("lead"), today)
    a_facts, gap = _absence_facts(inputs.get("pillars"))
    n_facts, n_gap = _nutrition_facts(inputs.get("nutrition"))
    facts += a_facts + n_facts
    gap.update(n_gap)
    names = inputs.get("names") or {}
    absent = [
        {"coach_id": cid, "name": names.get(cid, cid), "reason": str((st or {}).get("reason") or "its instrument is dark")}
        for cid, st in sorted((inputs.get("absent") or {}).items())
    ]
    # Graded results are CONTEXT, figures masked like the positions: a claim's own numbers
    # (an old average, a target) are not today's served values and never join the allow-list.
    graded: list = []
    seen: set = set()
    rows = [
        g for g in inputs.get("graded") or [] if isinstance(g, dict) and g.get("coach_id") and g.get("status") in ("confirmed", "refuted")
    ]
    for g in sorted(rows, key=lambda g: str(g.get("outcome_date") or ""), reverse=True):
        claim = mask_figures(str(g.get("claim_natural") or "").strip())[:240]
        if not claim or (g["coach_id"], claim) in seen or g["coach_id"] in (inputs.get("absent") or {}):
            continue
        seen.add((g["coach_id"], claim))
        graded.append(
            {
                "coach_id": g["coach_id"],
                "prediction_id": str(g.get("prediction_id") or ""),
                "claim": claim,
                "verdict": "came true" if g["status"] == "confirmed" else "did not come true",
                "graded_on": date_in_words(g.get("outcome_date")),
            }
        )
        if len(graded) >= MAX_GRADED:
            break
    positions = {
        cid: {"text": mask_figures(p.get("text")), "as_of": date_in_words(p.get("as_of"))}
        for cid, p in (inputs.get("positions") or {}).items()
        if isinstance(p, dict) and p.get("text") and cid not in (inputs.get("absent") or {})
    }
    yesterday = [
        {"coach_id": ln.get("coach_id"), "move": ln.get("move"), "text": mask_figures(ln.get("text"))}
        for ln in (inputs.get("yesterday") or [])
        if isinstance(ln, dict) and ln.get("text")
    ]
    nut = inputs.get("nutrition") if isinstance(inputs.get("nutrition"), dict) else None
    return {
        "date": today,
        "facts": facts,
        "absent": absent,
        "graded": graded,
        "positions": positions,
        "yesterday": yesterday,
        "gap": gap,
        "served": {"nutrition": nut, "protein_series": inputs.get("protein_series") or [], "weight": _weight_fact(facts)},
    }


def sheet_text(sheet: dict, extra: str = "") -> str:
    """The sheet as the model is shown it — and, exactly, the text the number gate allows from."""
    lines = [f"FACT SHEET for {date_in_words(sheet.get('date'))} (the only values anyone may cite, exactly as written):"]
    for f in sheet.get("facts") or []:
        when = date_in_words(f.get("as_of")) if f.get("as_of") and not f["key"].endswith(".last_date") else ""
        lines.append(f"- {f['label']}: {f['value']}" + (f" (as of {when})" if when else ""))
    if extra:
        lines.append(extra)
    return "\n".join(lines)


def context_text(sheet: dict, names: dict) -> str:
    """Positions, yesterday's lines and the sidelined coaches — context only, figures masked."""
    lines = []
    if sheet.get("graded"):
        lines.append("GRADED RESULTS (recent; figures removed):")
        for g in sheet["graded"]:
            who = names.get(g["coach_id"], g["coach_id"])
            lines.append(f"- [{g['prediction_id']}] {who} predicted: {g['claim']} — {g['verdict']} (graded {g['graded_on']})")
    if sheet.get("absent"):
        lines.append("SIDELINED (cannot speak today):")
        lines += [f"- {a['name']} ({a['coach_id']}): {a['reason']}" for a in sheet["absent"]]
    if sheet.get("positions"):
        lines.append("EACH COACH'S LAST PUBLIC POSITION (figures removed — use the fact sheet):")
        for cid, p in sheet["positions"].items():
            lines.append(f"- {names.get(cid, cid)} ({cid}, {p['as_of']}): {p['text']}")
    if sheet.get("yesterday"):
        lines.append("YESTERDAY'S LINES:")
        lines += [f"- {names.get(y['coach_id'], y['coach_id'])} [{y['move']}]: {y['text']}" for y in sheet["yesterday"]]
    return "\n".join(lines)


def stored_sheet(sheet: dict) -> dict:
    """What the day's row keeps: the sheet itself, so any line can be checked against it later."""
    return {k: sheet.get(k) for k in ("date", "facts", "absent", "graded")}


# ══════════════════════════════════════════════════════════════════════════════
# the line gate
# ══════════════════════════════════════════════════════════════════════════════


def _word_figures(text: str) -> list:
    """Spelled-out counts written WITH a unit — "eleven days", "twenty-four days"."""
    out = []
    for m in _WORD_NUM_RE.finditer(text or ""):
        if not _UNIT_AFTER_RE.match(text[m.end() :]):
            continue
        if m.group(3):
            out.append(float(_NUM_WORDS[m.group(3).lower()]))
        else:
            out.append(float(_TENS[m.group(1).lower()] + (_NUM_WORDS[m.group(2).lower()] if m.group(2) else 0)))
    return out


# A calendar day ("October 10", "September 9th") is a date, policed by the date class —
# not a figure, and not one of the two a move may lean on.
_MONTH_DAY_RE = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def _without_dates(text: str) -> str:
    return _MONTH_DAY_RE.sub("<date>", text or "")


def figures_in(text: str) -> list:
    """Every figure in a line: digit tokens (years and calendar days excluded) plus spelled-out counts with a unit."""
    digits = []
    for m in _DIGIT_FIGURE_RE.finditer(_without_dates(text)):
        try:
            v = float(m.group(0).replace(",", ""))
        except ValueError:
            continue
        if not (2020 <= v <= 2035 and "." not in m.group(0)):
            digits.append(v)
    return digits + _word_figures(text or "")


def off_sheet_figures(text: str, allowed: set) -> list:
    """The EXACT number rule (the lead read's `uncited_numbers` discipline): every figure must be
    a sheet value or a rounding of one. A unitless count up to twelve ("two coaches") is not a
    figure; a count WITH a unit ("eleven days", "4 lb") always is."""
    from ai.grounded_generation import _is_restatement, unit_bearing_numbers

    clean = _without_dates(text)
    with_unit = unit_bearing_numbers(clean) | set(_word_figures(clean))
    out = []
    for v in sorted(set(figures_in(text))):
        if v.is_integer() and 0 <= v <= 12 and v not in with_unit:
            continue
        if not any(_is_restatement(v, a) for a in allowed):
            out.append(v)
    return out


def allowed_for(sheet: dict, extra: str = "") -> tuple:
    from ai import grounded_generation as gg

    shown = sheet_text(sheet, extra)
    graded_days = " ".join(g.get("graded_on") or "" for g in sheet.get("graded") or [])  # a reaction may name the day it was graded
    return gg.allowed_numbers(shown), gg.allowed_dates(shown + " " + graded_days)


def _rules_findings(text: str) -> list:
    out = []
    from coach.audience_guard import is_owner_directed

    if is_owner_directed(text):
        out.append("second_person")
    if _HONORIFIC_RE.search(text):
        out.append("honorific")
    if _RESET_RE.search(text) or (_CYCLE_RE.search(text) and not _SLEEP_CYCLE_RE.search(text)):
        out.append("cycle_or_reset_count")
    if _CALORIE_RE.search(text):
        out.append("calorie_figure")
    from experiment.er03_gate import BANNED_CAUSAL  # ONE causal list for every coach reader string (CC-08)

    low = text.lower()
    if any(re.search(r"\b" + re.escape(p) + r"\b", low) for p in BANNED_CAUSAL):
        out.append("causal")
    for m in _QUOTE_RE.finditer(text):
        if _FIRST_PERSON_RE.search(m.group(1)):
            out.append("words_in_his_mouth")
            break
    try:
        from privacy import privacy_guard

        if privacy_guard.find_violations(text):
            out.append("privacy")
    except Exception as e:  # noqa: BLE001 — the vocabulary is fail-closed: unknown is a refusal
        logger.warning("[coach_moves] privacy vocabulary unavailable — refusing the line: %s", e)
        out.append("privacy_unchecked")
    return out


def restatement_findings(text: str, move: str, *, target_name: str = "") -> list:
    """The numbers-restated refusal (#4583 acceptance 2): a line must carry an opinion and make its move."""
    out = []
    figs = figures_in(text)
    if len(figs) > MAX_FIGURES:
        out.append(f"restates_numbers:{len(figs)}_figures")
    if not _STANCE_RE.search(text) and not (move == "question" and "?" in text):
        out.append("restates_numbers:no_opinion")
    if move == "call" and not _CALL_RE.search(text):
        out.append("move_not_made:call")
    elif move == "reaction" and not _REACTION_RE.search(text):
        out.append("move_not_made:reaction")
    elif move == "question" and not ("?" in text and _ABOUT_HIM_RE.search(text)):
        out.append("move_not_made:question")
    elif move == "change_of_mind" and not _CHANGE_RE.search(text):
        out.append("move_not_made:change_of_mind")
    elif move == "reply":
        parts = [p for p in re.split(r"\s+", target_name or "") if len(p) > 1]
        if not parts or not any(re.search(r"\b" + re.escape(p) + r"\b", text) for p in parts):
            out.append("move_not_made:reply")
    return out


def bindings(text: str, sheet: dict) -> dict:
    """{fact_key: value} for every day-count a sentence ties to ONE absence fact."""
    from operational.weight_truth_qa import _sentences

    by = {f["key"]: f for f in sheet.get("facts") or []}
    out: dict = {}
    for s in _sentences(text or ""):
        hit = [key for _p, (key, _w, alias) in ABSENCE_PILLARS.items() if re.search(alias, s, re.IGNORECASE)]
        if len(hit) != 1 or f"{hit[0]}.days_since" not in by:
            continue
        vals = [float(v) for v in _DAY_COUNT_RE.findall(s)] + [v for v in _word_figures(s) if re.search(r"day", s, re.I)]
        if "logged days" in s.lower() or "days logged" in s.lower() or "days with a food log" in s.lower():
            continue  # a days-logged count, not a days-since one
        for v in vals:
            out.setdefault(f"{hit[0]}.days_since", set()).add(v)
    return out


def binding_findings(text: str, sheet: dict) -> list:
    """A day-count tied to the journal / food log / training log that is not that fact's served value,
    and an absence word against a log the sheet says is current (or "resumed" against a dark one)."""
    from operational.weight_truth_qa import _sentences

    by = {f["key"]: f for f in sheet.get("facts") or []}
    out = []
    for key, vals in bindings(text, sheet).items():
        served = float(by[key]["value"])
        for v in sorted(vals):
            if abs(v - served) > 0:
                out.append(f"metric_value:{key}={v:g}(served {served:g})")
    for s in _sentences(text or ""):
        for _p, (key, _w, alias) in ABSENCE_PILLARS.items():
            if not re.search(alias, s, re.IGNORECASE) or f"{key}.state" not in by:
                continue
            state = by[f"{key}.state"]["value"]
            days = by.get(f"{key}.days_since", {}).get("value")
            current = state == "logged" and days is not None and float(days) <= 1
            if current and _QUIET_RE.search(s):
                out.append(f"absence_state:{key} is logged, the line says it is quiet")
            if state == "dark" and _RESUMED_RE.search(s) and not _QUIET_RE.search(s):
                out.append(f"absence_state:{key} is dark, the line says it resumed")
    return out


def check_line(text: Optional[str], move: str, sheet: dict, *, today: str, target_name: str = "", extra: str = "") -> list:
    """Reasons to refuse one coach line — [] means it may ship. Fail-closed."""
    t = (text or "").strip()
    if not t:
        return ["empty"]
    if move not in MOVES:
        return [f"unknown_move:{move}"]
    reasons = []
    if len(t.split()) > MAX_WORDS:
        reasons.append(f"over_{MAX_WORDS}_words")
    reasons += _rules_findings(t)
    reasons += restatement_findings(t, move, target_name=target_name)
    allowed, allowed_dates = allowed_for(sheet, extra)
    from ai import grounded_generation as gg
    from common.constants import EXPERIMENT_START_DATE

    reasons += [f"not_on_sheet:{v:g}" for v in off_sheet_figures(t, allowed)]
    reasons += [
        f"grounding:{f.get('type')}:{f.get('claimed', '')}"
        for f in gg.grounding_findings(
            t,
            allowed=allowed,
            allowed_dates=allowed_dates,
            generation_date_iso=today,
            start_date_iso=EXPERIMENT_START_DATE,
        )  # the default window: the exact rule is `off_sheet_figures` above (#2290 keeps EXACT to /api/explain)
    ]
    try:
        from coach import coach_input_facts, reader_checks

        reasons += [f"served_fact:{f['metric']}" for f in coach_input_facts.served_fact_findings(t, sheet.get("served"), today)]
        reasons += [f"reader:{f.get('check')}" for f in reader_checks.reader_findings(t, facts=sheet.get("gap") or {}, allowed=allowed)]
    except Exception as e:  # noqa: BLE001 — a check that cannot run is a refusal, never a pass
        logger.warning("[coach_moves] served-fact/reader checks unavailable — refusing: %s", e)
        reasons.append("checks_unavailable")
    reasons += binding_findings(t, sheet)
    return list(dict.fromkeys(reasons))


def cross_line_findings(text: str, accepted: list, sheet: dict) -> list:
    """A later line that ties a different value to a metric an earlier accepted line cited."""
    mine = bindings(text, sheet)
    out = []
    for prev in accepted:
        for key, vals in bindings(prev, sheet).items():
            if key in mine and mine[key] != vals:
                out.append(f"cross_line:{key}")
    return out


# ══════════════════════════════════════════════════════════════════════════════
# the reads (DynamoDB only, each fail-soft)
# ══════════════════════════════════════════════════════════════════════════════


def _graded(table: Any, coach_ids: list, today: str) -> list:
    from boto3.dynamodb.conditions import Key
    from common.pacific_time import parse_day_key  # #3609: the one calendar-day parser
    from experiment.phase_filter import with_phase_filter

    day = parse_day_key(today)
    if day is None:
        return []
    since = (day - timedelta(days=GRADED_LOOKBACK_DAYS)).isoformat()
    out = []
    for cid in coach_ids:
        try:
            kwargs = with_phase_filter({"KeyConditionExpression": Key("pk").eq(f"COACH#{cid}") & Key("sk").begins_with("PREDICTION#")})
            for _page in range(5):
                resp = table.query(**kwargs)
                for it in resp.get("Items") or []:
                    if it.get("status") in ("confirmed", "refuted") and str(it.get("outcome_date") or "")[:10] >= since:
                        out.append({**it, "coach_id": cid})
                if not resp.get("LastEvaluatedKey"):
                    break
                kwargs = dict(kwargs, ExclusiveStartKey=resp["LastEvaluatedKey"])
        except Exception as e:  # noqa: BLE001
            logger.warning("[coach_moves] graded read %s failed (omitted): %s", cid, e)
    return out


def _positions(table: Any, coach_ids: list) -> dict:
    from boto3.dynamodb.conditions import Key
    from experiment.phase_filter import with_phase_filter

    from coach import audience_guard

    out = {}
    for cid in coach_ids:
        try:
            resp = table.query(
                **with_phase_filter(
                    {
                        "KeyConditionExpression": Key("pk").eq(f"COACH#{cid}") & Key("sk").begins_with("OUTPUT#"),
                        "ScanIndexForward": False,
                        "Limit": 1,
                    }
                )
            )
            items = resp.get("Items") or []
            if items:
                text = audience_guard.public_blurb(items[0])  # the SAME blurb /api/coaching-dashboard serves
                if text:
                    out[cid] = {"text": text, "as_of": str(items[0].get("created_at") or items[0].get("sk", "")[7:17])[:10]}
        except Exception as e:  # noqa: BLE001
            logger.warning("[coach_moves] position read %s failed (omitted): %s", cid, e)
    return out


def read_inputs(table: Any, today: str, coach_ids: list, names: dict) -> dict:
    """Every served input the sheet is built from. Each read is fail-soft: a failed read
    leaves its facts OFF the sheet (so nothing may cite them), never zeroed."""
    from datetime import datetime

    inputs: dict = {"names": names}
    try:
        from coach import lead_daily_read

        inputs["lead"] = lead_daily_read.latest_served(table)
    except Exception as e:  # noqa: BLE001
        logger.warning("[coach_moves] lead read unavailable: %s", e)
    try:
        from common.constants import EXPERIMENT_START_DATE
        from common.pacific_time import PACIFIC
        from web.site_api_character import _attach_pillar_absence  # the /api/character derivation itself

        pillars = [{"name": n} for n in ABSENCE_PILLARS]
        _attach_pillar_absence(pillars, table=table, now=datetime.now(PACIFIC), window_start=EXPERIMENT_START_DATE)
        inputs["pillars"] = pillars
    except Exception as e:  # noqa: BLE001
        logger.warning("[coach_moves] pillar absence unavailable: %s", e)
    try:
        from health import nutrition_logging

        from coach import coach_input_facts

        rows = coach_input_facts.fetch_macrofactor_window(table, today)
        if rows is not None:
            inputs["nutrition"] = coach_input_facts.nutrition_record(rows, today)
            inputs["protein_series"] = nutrition_logging.protein_series(rows)
    except Exception as e:  # noqa: BLE001
        logger.warning("[coach_moves] nutrition record unavailable: %s", e)
    try:
        from health import instrument_presence

        inputs["absent"] = instrument_presence.absent_coaches(table)
    except Exception as e:  # noqa: BLE001
        logger.warning("[coach_moves] instrument presence unavailable (no coach marked absent): %s", e)
    inputs["graded"] = _graded(table, coach_ids, today)
    inputs["positions"] = _positions(table, coach_ids)
    return inputs
