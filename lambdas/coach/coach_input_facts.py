"""coach_input_facts.py — #4185: coach inputs read the SERVED facts, and a coach
figure that disagrees with them is regenerated-or-held.

Three defects shipped in one served corpus (2026-09-25/26), each a premise the engine's
own served numbers contradicted:

  1. **A food-log gap that never happened.** The daily nutrition coach
     (`ai_context._build_nutrition_data`) was handed yesterday's single MacroFactor row
     and NO logging record, so the only "when was the last log" it could read was its own
     carried threads and commitments (the 09-23 "logging gap after September 19th" read,
     written while those rows had not yet been uploaded). Two days after the rows landed
     it still wrote "Six days without logs" beside `/api/nutrition_overview`'s
     `days_logged 20`, `lag_days 0`. `coach_inputs` now hands the nutrition coach the
     logging record from `health.nutrition_logging` — the SAME derivation the endpoint
     serves — plus a note saying which source wins.
  2. **A bedtime in the wrong timezone.** `sleep_start` reached coach prompts as a raw
     UTC instant; 04:45Z was narrated as a "4:45 AM onset" (it is 9:45 PM PT).
     `localize_sleep_instants` renders every sleep instant as a labelled PT time at the
     input boundary, before any coach sees it.
  3. **Figures with no window.** `served_fact_findings` compares every protein /
     days-logged / logging-gap figure a coach states against the engine's fact for the
     window the sentence names, with the fact's own 95% CI as the tolerance. It reuses
     #4194's extractor (`operational.weight_truth_qa.coach_quantity_claims`) so the
     nightly QA and this generation-time gate read prose ONE way.

  3b. **A weight the scale left behind** (the issue's item 4: "316.9 pounds … losing 3.7
     pounds per week" beside a served 313.8 lb). A bodyweight or loss-rate figure a coach
     states as current is judged against the served trajectory (`weight_fact`: the
     computed_metrics `latest_weight` / `weekly_rate_lbs` + its 80% CI, the same
     `health.weight_trend` computation `/api/journey` serves), read with the nightly QA's
     own extractors (`weights_cited_in`, `_rate_claims`).

  4. **The morning note (#4189).** Every coach's input carries the owner's own four words
     for the morning (`coach.morning_note.coach_fact` — the SAME derivation
     `/api/morning_note` and the coach packet serve), read for today or yesterday only,
     with absence stated (`state: absent`) rather than a blank the model might fill.
"""

from __future__ import annotations

import os
import re
import time
from datetime import date
from typing import Any, Optional

from common.constants import EXPERIMENT_START_DATE
from common.pacific_time import pacific_clock_label, pacific_today, parse_day_key
from health import nutrition_logging as _nl

from coach import morning_note as _mn

# ── 2. sleep instants → labelled Pacific time ────────────────────────────────

# Keys whose values are sleep INSTANTS (Whoop/Eight Sleep write UTC ISO strings). A key
# is converted only when its value actually parses as an instant — a duration or a day
# under a matching name is left alone by `pacific_clock_label` returning None.
_SLEEP_INSTANT_KEY = re.compile(r"^(?:sleep_(?:start|end|onset)\w*|bedtime\w*|wake_time\w*|in_bed_(?:start|end)\w*)$", re.IGNORECASE)


def _localize_value(v: Any) -> Any:
    if isinstance(v, str):
        return pacific_clock_label(v, with_day=True) or v
    if isinstance(v, list):
        return [_localize_value(x) for x in v]
    return v


def localize_sleep_instants(obj: Any) -> Any:
    """A copy of `obj` with every sleep-instant value rendered as ``"Sep 23, 9:45 PM PT"``.

    Walks dicts and lists at any depth; never mutates the input. Anything that is not a
    sleep-instant key, or does not parse as an instant, passes through unchanged.
    """
    if isinstance(obj, dict):
        return {
            k: (_localize_value(v) if isinstance(k, str) and _SLEEP_INSTANT_KEY.match(k) else localize_sleep_instants(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [localize_sleep_instants(x) for x in obj]
    return obj


# ── 1. the served nutrition logging record ───────────────────────────────────

LOGGING_RECORD_NOTE = (
    "AUTHORITATIVE food-logging record: the same computation /api/nutrition_overview serves. "
    "Ground every statement about how many days are logged, when the last log was, or a logging gap in "
    "these fields and nothing else. lag_days of 1 is the by-design end-of-day upload lag, never a gap. If "
    "your open threads, commitments or earlier reads describe a logging gap this record does not show, "
    "those rows have since arrived: the gap is closed. Say so, or leave it out; never narrate it as ongoing. "
    "When you cite a protein average, name its window (for example 'across N logged days')."
)

# How long one run's fetched facts are reused: the daily brief renders all coaches in a
# few minutes; a manual re-run later in the day must see the rows that arrived since.
_RUN_TTL_SECONDS = 900
_run: dict = {}


def data_through(data: Optional[dict]) -> Optional[str]:
    """The last data day a daily coach read is written from — the Pacific day the brief
    gathered its day rows for (`daily_brief_lambda.gather_daily_data`'s `date`)."""
    d = (data or {}).get("date")
    return str(d)[:10] if d else None


# A 30-row window is one or two 1 MB pages; a read still paginating past this is not a
# window, it is a runaway (or a fake), and an unbounded loop is never the answer.
_MAX_PAGES = 20


def fetch_macrofactor_window(table, today: str) -> Optional[list]:
    """Every macrofactor row in the `nutrition_logging.window_start` window, paginated
    past DynamoDB's 1 MB page, tombstoned rows dropped (the site's derived-read rule).
    None when the read fails — absence, never an empty (= "nothing logged") list."""
    if table is None:
        return None
    try:
        from boto3.dynamodb.conditions import Key

        start = _nl.window_start(today, EXPERIMENT_START_DATE)
        pk = f"USER#{os.environ.get('USER_ID', 'matthew')}#SOURCE#macrofactor"
        kwargs: dict = {"KeyConditionExpression": Key("pk").eq(pk) & Key("sk").between(f"DATE#{start}", f"DATE#{today}~")}
        items: list = []
        for _page in range(_MAX_PAGES):
            resp = table.query(**kwargs)
            if not isinstance(resp, dict):
                return None  # not a DynamoDB response — unknown, never "nothing logged"
            items.extend(i for i in resp.get("Items") or [] if isinstance(i, dict))
            if not resp.get("LastEvaluatedKey"):
                return [i for i in items if not i.get("tombstone")]
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        print(f"[COACH-INPUT-FACTS] macrofactor window still paginating after {_MAX_PAGES} pages — record omitted")
        return None
    except Exception as e:  # noqa: BLE001 — a coach input is never load-bearing on this read
        print(f"[COACH-INPUT-FACTS] macrofactor window read failed (record omitted): {e}")
        return None


def morning_note_fact(table, today: str) -> dict:
    """The owner's morning note as a served fact (#4189): today's, else yesterday's, else
    `absent`; a failed read is `read_failed`. Never a default word."""
    rows = _mn.read_notes(table, today, _mn.COACH_LOOKBACK_DAYS)
    if rows is None:
        return _mn.coach_fact(None, read_ok=False)
    return _mn.coach_fact(rows[0] if rows else None)


def nutrition_record(rows: list, today: str) -> dict:
    """The prompt-facing logging record: `nutrition_logging.logging_record` plus the
    protein average (with its 95% CI) over the same window."""
    rec = _nl.logging_record(rows, today)
    series = _nl.protein_series(rows)
    # Deliberately ONE protein figure (the served window's `avg_protein_g`, with its CI).
    # A second "recent" average here would be a sixth protein number for the same week —
    # the issue's item 3 — unless it matched `pro_7d_avg`'s calendar window exactly.
    full = _nl.protein_window(series)
    return {
        "window_start": _nl.window_start(today, EXPERIMENT_START_DATE),
        "days_logged": rec["days_logged"],
        "latest_log_date": rec["latest_date"],
        "lag_days": rec["lag_days"],
        "stalled": rec["stalled"],
        "today_pending": rec["today_pending"],
        "protein_avg_g": full["mean"] if full else None,
        "protein_avg_ci95_g": [full["lo"], full["hi"]] if full and full["half_width"] is not None else None,
        "protein_avg_days": full["n"] if full else 0,
        "note": LOGGING_RECORD_NOTE,
    }


def served_run_facts(data: Optional[dict] = None, *, table=None, today: Optional[str] = None) -> Optional[dict]:
    """This run's served facts: ``{"data_through", "nutrition", "protein_series"}``.

    With `data`, derives (or reuses, within `_RUN_TTL_SECONDS`, for the same data day) the
    facts — from `data["macrofactor_window"]` when a caller supplies the rows, else one
    paginated read through `table`. Without `data`, returns the current run's facts and
    never reads anything: that is how the quality gate sees the facts the coach was given.
    """
    if data is None:
        return _run.get("facts")
    today = today or pacific_today()
    key = (data_through(data), today)
    supplied = data.get("macrofactor_window")
    fresh = time.monotonic() - _run.get("at", 0.0) < _RUN_TTL_SECONDS
    if supplied is None and fresh and _run.get("key") == key and _run.get("table") is table:
        w = weight_fact(data)
        if w:  # a caller holding the trajectory refreshes it; one without it never erases it
            _run["facts"] = {**_run["facts"], "weight": w}
        return _run["facts"]
    rows = supplied if supplied is not None else fetch_macrofactor_window(table, today)
    facts = {
        "data_through": data_through(data),
        "weight": weight_fact(data),
        "nutrition": nutrition_record(rows, today) if rows is not None else None,
        "protein_series": _nl.protein_series(rows) if rows is not None else [],
        # #4189: the note is read for TODAY (Pacific) — the brief runs after the morning it
        # was written — not for `data_through`, which is the previous data day.
        "morning_note": morning_note_fact(table, today),
    }
    # The table itself is held (not its id) so an identity check can never match a
    # different object that happens to reuse a freed id.
    _run.update(key=key, table=table, at=time.monotonic(), facts=facts)
    return facts


# The served weight trajectory's field names — identical in the daily brief's `data`
# (`daily_brief_lambda` copies them off the day's computed_metrics record) and in
# `experiment.canonical_facts` (the weekly analyzer's facts), so ONE reader serves both.
WEIGHT_FACT_KEYS = ("latest_weight", "weekly_rate_lbs", "weekly_rate_ci_low", "weekly_rate_ci_high")


def weight_fact(src: Optional[dict]) -> Optional[dict]:
    """The served weight trajectory from `src`, or None when it carries neither a weight nor
    a rate (a pre-genesis record withholds both — `canonical_facts` #2113): nothing to judge."""
    out = {}
    for k in WEIGHT_FACT_KEYS:
        try:
            v = (src or {}).get(k)
            out[k] = float(v) if v is not None else None
        except (TypeError, ValueError):
            out[k] = None
    return out if out["latest_weight"] is not None or out["weekly_rate_lbs"] is not None else None


def coach_inputs(coach_id: str, domain_data: Any, data: Optional[dict], *, table=None) -> Any:
    """THE coach-input boundary (`ai_calls._run_coach_v2_pipeline`, before the upstream
    change-gate hashes anything): every coach's domain data has its sleep instants
    rendered in PT, and the nutrition coach gets the served logging record."""
    facts = served_run_facts(data or {}, table=table)
    out = localize_sleep_instants(domain_data)
    if coach_id == "nutrition_coach" and isinstance(out, dict):
        out = {**out, "logging_record": (facts or {}).get("nutrition")}
    if isinstance(out, dict):
        # #4189: every coach reads the owner's four words — the sleep and mind coaches asked
        # for them by name; the rest see the same fact so no coach narrates a morning he
        # described differently.
        out = {**out, "morning_note": (facts or {}).get("morning_note") or _mn.coach_fact(None, read_ok=False)}
    return out


# ── 3. cited figures vs the served facts (the generation-time gate) ──────────

# A logging-gap claim is judged against `lag_days` with one day of latitude: the
# end-of-day upload makes "no log since yesterday" and lag 0/1 the same honest fact.
GAP_TOLERANCE_DAYS = 1
# A cited protein figure also passes when it IS one logged day's value (a coach naming
# "yesterday's 182 g" is not claiming an average) — to this rounding.
DAY_VALUE_ROUNDING_G = 1.0
# Floor under a CI half-width: a coach rounding 152.4 to 152 is not a contradiction.
MIN_PROTEIN_TOLERANCE_G = 1.0
# A cited loss rate is a contradiction only OUTSIDE the engine's own 80% CI, widened by a
# one-decimal rounding ("4.4 lb/week" for -4.36). With no CI served, the nightly QA's
# documented fallback (`weight_truth_qa._rate_tolerance(None)`, 1.0 lb/wk) applies.
RATE_ROUNDING_LBS = 0.05
# A weight named as the ORIGIN of a change or as a GOAL is not a claim about today: "down
# 13.5 lb from 327.3", "he started at 327 pounds", "the goal of 185 lb", "on the way to 300
# pounds", "the 300-lb mark". Scoped to the words beside the figure, NOT the sentence:
# the nightly QA's sentence-wide target rule (`_VITALS_TARGET_SENTENCE`) would let Eli's
# "At 316.9 pounds …, which is aggressive and on-target" through on the word "on-target".
_WEIGHT_NOT_NOW_BEFORE = re.compile(
    r"(?:\bfrom|\bstart(?:ed|ing)?(?:\s+weight)?(?:\s+(?:at|of|was))?|\bbegan\s+at|\bbaseline(?:\s+of)?|\bgoal(?:\s+weight)?"
    r"(?:\s+(?:of|is|at))?|\btarget(?:\s+weight)?(?:\s+(?:of|is|at))?|\btowards?|\bto\s+reach|\breach(?:es|ing)?|\bhit(?:s|ting)?"
    r"|\bbelow|\bunder|\bway\s+to|\bdown\s+to\s+(?:a\s+)?(?:goal|target)\s+of)\s+(?:about\s+|roughly\s+|around\s+|the\s+)?$",
    re.IGNORECASE,
)
# A FORECAST is not a claim about today either: the physical coach's 09-27 final carries
# "The model expects weight of 314.5 lbs tomorrow morning, with the interval running from
# 310.8 to 318.1" — the #541 forecast block it was handed, cited correctly.
_WEIGHT_FORECAST_SENTENCE = re.compile(
    r"\b(?:expects?|expected|expectation|forecasts?|projects?|projected|projection|predict\w*|interval|tomorrow|next\s+week|by\s+(?:the\s+)?end\s+of)\b",
    re.IGNORECASE,
)
_WEIGHT_NOT_NOW_AFTER = re.compile(r"^[\s-]*(?:goal|target|mark|milestone)\b", re.IGNORECASE)

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
# "went dark after September 19th", "no logs since Sep 19", "nothing logged since the 19th of September",
# and (#4185 follow-up) "the six-day logging gap since September 19th" / "a two-day food-log gap since
# Sep 19" — the served 09-26 and 09-22 nutrition reads. Only the DATE is read from that phrasing (the
# last log it implies); its day count is not a `log_gap_days` claim, so a correct read whose N is off by
# the upload lag is never held on the count.
_GAP_SINCE_DATE = re.compile(
    r"\b(?:went\s+(?:dark|quiet|silent)|stopped|no\s+(?:food\s+)?logs?|nothing\s+(?:was\s+)?logged|hasn't\s+logged|haven't\s+logged"
    r"|(?:food[-\s]?)?log(?:ging)?\s+gap)"
    r"\s+(?:after|since)\s+(?:the\s+)?([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
# A window the sentence names for its protein figure, beyond "N logged days" (which the
# shared extractor already returns as a `days_logged` claim).
_NAMED_WINDOW = re.compile(r"\b(\d{1,2})[- ](?:calendar\s+)?days?\b|\b(?:this|past|last)\s+week\b|\b7-day\b", re.IGNORECASE)
# #4343: the average refutes only a figure the sentence frames as his daily intake or an
# average of it. "Morning smoothie delivers 15 g, protein shake adds 30 g", "redistribute
# 40g of protein away from dinner" and "if protein reaches 190g next week" are a serving,
# a shift and a conditional target — the 09-27 brief held the nutrition, glucose and
# explorer coaches on exactly those. A day-count window ("across 21 logged days") also frames.
_INTAKE_FRAME = re.compile(
    r"\b(?:averag\w*|mean|running|rolling|trailing|ewma|typical(?:ly)?|usual(?:ly)?|daily|per\s+day|a\s+day|each\s+day)\b"
    r"|/\s*day\b|\bg/d\b",
    re.IGNORECASE,
)


# #4343 (09-28 brief, labs): a figure the sentence names as a target, floor or the level an
# escalation moves TO is a goal, not his intake — "against a target of 190 grams", "protein
# escalation to 190 grams per day is authorized", "the 190-gram target". The average cannot
# refute a goal, so a protein figure is skipped when EVERY place it is written is framed so.
_TARGET_BEFORE = re.compile(
    r"(?:\b(?:target|floor|goal|ceiling|minimum)\s+(?:of\s+)?|\bescalat\w*\s+(?:\w+\s+){0,2}?to\s+|\btowards?\s+"
    # #4690: an ASK to "reach"/"hit" a level is a goal, not intake ("I've asked him to log food
    # consistently and reach 170 grams of protein daily"). The ask/aim word is required: a bare
    # "(to) hit N" is also a past-tense report ("he managed to hit 190 grams"), which stays judged.
    r"|\b(?:ask\w*|aim\w*|want\w*|needs?|should|must|try\w*|push\w*|plan\w*|urg\w*|encourag\w*|told|tell\w*)"
    r"(?:\s+(?!managed\b|able\b|did\b|finally\b)[\w']+){0,6}?(?:\s+(?:to|and|or))?\s+(?:reach|hit)\s+)"
    r"(?:about\s+|around\s+|roughly\s+)?$",
    re.IGNORECASE,
)
_TARGET_AFTER = re.compile(
    r"^\s*-?\s*(?:g|grams?)?\s*-?\s*(?:(?:daily|protein|a\s+day|per\s+day)\s+)?(?:target|floor|goal)\b", re.IGNORECASE
)


def _target_framed(sentence: str, value: float) -> bool:
    """True when every occurrence of `value` in `sentence` is written as a target/floor/goal."""
    num = f"{value:g}"
    hits = list(re.finditer(r"(?<![\d.,])" + re.escape(num) + r"(?:\.0+)?(?![\d])", sentence))
    return bool(hits) and all(
        # 80 chars: the #4690 ask word sits up to six words before "reach"; every alternative is $-anchored
        _TARGET_BEFORE.search(sentence[max(0, m.start() - 80) : m.start()]) or _TARGET_AFTER.match(sentence[m.end() :])
        for m in hits
    )


def _named_windows(sentence: str) -> list:
    out = []
    for m in _NAMED_WINDOW.finditer(sentence):
        out.append(int(m.group(1)) if m.group(1) else 7)
    return out


def _claimed_last_log(sentence: str, today: str) -> Optional[str]:
    m = _GAP_SINCE_DATE.search(sentence)
    if not m or m.group(1)[:3].lower() not in _MONTHS:
        return None
    t = parse_day_key(str(today)[:10])
    if t is None:
        return None
    try:
        d = date(t.year, _MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        if d > t:
            d = d.replace(year=t.year - 1)
        return d.isoformat()
    except ValueError:
        return None


def _finding(metric: str, cited: Any, canonical: Any, detail: str, sentence: str, kind: str = "contradiction") -> dict:
    # "contradiction" is a figure-grounding class (`regen_keep_predicate.FIGURE_TYPES`) and
    # `grounded_generation.correction_prompt` tells the rewrite "Use <canonical>"; a date
    # claim has no numeric canonical, so it rides the generic "remove it" correction.
    return {
        "type": kind,
        "metric": metric,
        "cited": cited,
        "canonical": canonical,
        "detail": detail,
        "excerpt": sentence.strip()[:200],
    }


def served_fact_findings(text: str, facts: Optional[dict], today: Optional[str] = None) -> list:
    """Every protein / days-logged / logging-gap / weight / loss-rate figure in `text` that
    disagrees with the served facts. Empty when the facts carry no nutrition record (nothing to judge
    against is a skip, never a pass-by-default on a made-up number)."""
    nut = (facts or {}).get("nutrition") or {}
    series = (facts or {}).get("protein_series") or []
    weight = (facts or {}).get("weight") or {}
    if not text or (not nut and not series and not weight):
        return []
    from operational.weight_truth_qa import _LOG_GAP_PATTERN, _num_token, _sentences, coach_quantity_claims

    today = today or pacific_today()
    day_values = [g for _d, g in series]
    findings = []
    for sentence in _sentences(text):
        claims = coach_quantity_claims({"analysis": sentence})
        lag, days_logged, latest = nut.get("lag_days"), nut.get("days_logged"), nut.get("latest_log_date")
        # A logging GAP is always a claim about the present record — even in a dated
        # sentence ("dark since Sep 19 — six days"), which the shared extractor skips.
        gaps = [_num_token(m.group(1)) for m in _LOG_GAP_PATTERN.finditer(sentence)]
        for v in (g for g in gaps if g == g):
            if lag is not None and abs(v - lag) > GAP_TOLERANCE_DAYS:
                findings.append(
                    _finding(
                        "log_gap_days", v, lag, f"claims {v:g} days without a food log; the served record's lag is {lag} day(s)", sentence
                    )
                )
        claimed_last = _claimed_last_log(sentence, today)
        if claimed_last and latest and claimed_last < latest:
            findings.append(
                _finding(
                    "last_log_date",
                    claimed_last,
                    latest,
                    f"claims logging stopped after {claimed_last}; the served record's last food log is {latest}",
                    sentence,
                    kind="served_fact_date",
                )
            )
        named = [int(v) for v, _c in claims.get("days_logged", [])]
        for v in named:
            if days_logged is not None and v > days_logged:
                findings.append(
                    _finding("days_logged", v, days_logged, f"claims {v} logged days; the served record has {days_logged}", sentence)
                )
        windows = named + _named_windows(sentence)
        # A day-count window frames the figure as an aggregate; "this week" alone does not
        # ("One ask this week: redistribute 40g" is a timing, not a window, #4343).
        framed = bool(named) or bool(_INTAKE_FRAME.search(sentence)) or any(m.group(1) for m in _NAMED_WINDOW.finditer(sentence))
        for v, _cls in claims.get("protein", []) if framed else []:
            win = _nl.protein_window(series, min(windows)) if windows else _nl.protein_window(series)
            if not win or win["half_width"] is None:
                continue  # no spread → no tolerance to derive; skipped, never guessed
            tol = max(float(win["half_width"]), MIN_PROTEIN_TOLERANCE_G)
            if abs(v - win["mean"]) <= tol:
                continue
            if _target_framed(sentence, v):
                continue
            if not windows:
                recent = _nl.protein_window(series, 7)
                if (
                    recent
                    and recent["half_width"] is not None
                    and abs(v - recent["mean"]) <= max(recent["half_width"], MIN_PROTEIN_TOLERANCE_G)
                ):
                    continue
                if any(abs(v - g) <= DAY_VALUE_ROUNDING_G for g in day_values):
                    continue
            span = f"the last {win['n']} logged days" if windows else f"the {win['n']} logged days served"
            findings.append(
                _finding(
                    "protein_g",
                    v,
                    win["mean"],
                    f"cites {v:g} g protein; the engine's average over {span} is {win['mean']:g} g (95% CI {win['lo']:g}-{win['hi']:g})",
                    sentence,
                )
            )
        findings.extend(weight_findings(sentence, weight))
    return findings


def _not_now(sentence: str, value: float) -> bool:
    """True when every place `value` is written in `sentence` names an origin or a goal."""
    from operational.weight_truth_qa import _WEIGHT_IN_PROSE

    hits = [m for m in _WEIGHT_IN_PROSE.finditer(sentence) if abs(float(m.group(1)) - value) < 1e-9]
    return bool(hits) and all(
        _WEIGHT_NOT_NOW_BEFORE.search(sentence[max(0, m.start() - 40) : m.start()]) or _WEIGHT_NOT_NOW_AFTER.match(sentence[m.end() :])
        for m in hits
    )


def _rate_ok(v: float, w: dict) -> bool:
    from operational.weight_truth_qa import _rate_tolerance

    lo, hi, rate = w.get("weekly_rate_ci_low"), w.get("weekly_rate_ci_high"), w["weekly_rate_lbs"]
    if lo is not None and hi is not None and (lo <= 0) == (hi <= 0):
        a, b = sorted((abs(lo), abs(hi)))
        return a - RATE_ROUNDING_LBS <= abs(v) <= b + RATE_ROUNDING_LBS
    return abs(abs(v) - abs(rate)) <= _rate_tolerance(None)


def weight_findings(sentence: str, weight: Optional[dict]) -> list:
    """#4185 item 4: a bodyweight or weekly loss-rate figure this ONE sentence states as
    current, judged against the served trajectory. The extractors are the nightly QA's
    (`weights_cited_in` drops a dated or "at Day 1"-anchored figure, `_rate_claims` a
    dated or target-framed one), so the two gates read prose one way; this gate also
    drops a forecast sentence and a goal or a change's origin ("from 327.3") beside the
    figure, because here a misfire
    HOLDS a coach (#4343). Rates are compared by magnitude (`weight_truth_qa._rate_value`)."""
    if not weight:
        return []
    from operational.weight_truth_qa import CROSS_SURFACE_WEIGHT_TOL_LBS, _rate_claims, weights_cited_in

    out = []
    latest = weight.get("latest_weight")
    if latest is not None and not _WEIGHT_FORECAST_SENTENCE.search(sentence):
        for v in weights_cited_in(sentence):
            if abs(v - latest) > CROSS_SURFACE_WEIGHT_TOL_LBS and not _not_now(sentence, v):
                out.append(
                    _finding(
                        "weight_lb",
                        v,
                        latest,
                        f"cites {v:g} lb as his weight; the latest served weigh-in is {latest:g} lb",
                        sentence,
                    )
                )
    if weight.get("weekly_rate_lbs") is not None:
        lo, hi = weight.get("weekly_rate_ci_low"), weight.get("weekly_rate_ci_high")
        ci = f" (80% CI {lo:g} to {hi:g})" if lo is not None and hi is not None else ""
        for v in _rate_claims(sentence):
            if not _rate_ok(v, weight):
                out.append(
                    _finding(
                        "weekly_rate_lb",
                        abs(v),
                        abs(weight["weekly_rate_lbs"]),
                        f"cites {abs(v):g} lb/week; the served rate is {weight['weekly_rate_lbs']:g} lb/week{ci}",
                        sentence,
                    )
                )
    return out


SERVED_FACT_REPORT_KEY = "served_fact_violations"


def served_fact_gate(report: dict, text: str, facts: Optional[dict]) -> dict:
    """Fold served-fact findings into a quality-gate report (ADR-108): a finding fails the
    report and rides its `suggestions` into the corrective regeneration, so
    `ai_calls._enforce_quality_gate` regenerates-or-holds on it exactly as it does on the
    judge's own verdict. Logged with the figure. Never raises — a failure here leaves the
    report as the gate returned it."""
    try:
        found = served_fact_findings(text, facts)
    except Exception as e:  # noqa: BLE001
        print(f"[COACH-INPUT-FACTS] served-fact check unavailable (non-blocking): {e}")
        return report
    if not found:
        return report
    print("[COACH-QUALITY-GATE] served-fact finding(s): " + "; ".join(f["detail"] for f in found)[:600])
    out = dict(report or {})
    out["passed"] = False
    out[SERVED_FACT_REPORT_KEY] = found
    out["suggestions"] = list(out.get("suggestions") or []) + [
        f"{f['detail']} — use the served figure, name its window, or leave the number out." for f in found
    ]
    return out


def gated(invoke_gate, lambda_client, coach_id: str, output_text: str, generation_brief: Any) -> dict:
    """`ai_calls._enforce_quality_gate`'s report source: the judge's verdict
    (`invoke_gate` — `ai_calls._invoke_quality_gate_sync`, passed in so a test that
    patches it still patches THIS path) with the served-fact check folded in against the
    facts this run's coach inputs were built from (`served_run_facts()`)."""
    return served_fact_gate(invoke_gate(lambda_client, coach_id, output_text, generation_brief), output_text, served_run_facts())
