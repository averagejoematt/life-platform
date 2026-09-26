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

Rate / weight figures (the issue's item 4) are NOT checked here — a named residual.
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
        return _run["facts"]
    rows = supplied if supplied is not None else fetch_macrofactor_window(table, today)
    facts = {
        "data_through": data_through(data),
        "nutrition": nutrition_record(rows, today) if rows is not None else None,
        "protein_series": _nl.protein_series(rows) if rows is not None else [],
    }
    # The table itself is held (not its id) so an identity check can never match a
    # different object that happens to reuse a freed id.
    _run.update(key=key, table=table, at=time.monotonic(), facts=facts)
    return facts


def coach_inputs(coach_id: str, domain_data: Any, data: Optional[dict], *, table=None) -> Any:
    """THE coach-input boundary (`ai_calls._run_coach_v2_pipeline`, before the upstream
    change-gate hashes anything): every coach's domain data has its sleep instants
    rendered in PT, and the nutrition coach gets the served logging record."""
    facts = served_run_facts(data or {}, table=table)
    out = localize_sleep_instants(domain_data)
    if coach_id == "nutrition_coach" and isinstance(out, dict):
        out = {**out, "logging_record": (facts or {}).get("nutrition")}
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

_MONTHS = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}
# "went dark after September 19th", "no logs since Sep 19", "nothing logged since the 19th of September"
_GAP_SINCE_DATE = re.compile(
    r"\b(?:went\s+(?:dark|quiet|silent)|stopped|no\s+(?:food\s+)?logs?|nothing\s+(?:was\s+)?logged|hasn't\s+logged|haven't\s+logged)"
    r"\s+(?:after|since)\s+(?:the\s+)?([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)
# A window the sentence names for its protein figure, beyond "N logged days" (which the
# shared extractor already returns as a `days_logged` claim).
_NAMED_WINDOW = re.compile(r"\b(\d{1,2})[- ](?:calendar\s+)?days?\b|\b(?:this|past|last)\s+week\b|\b7-day\b", re.IGNORECASE)


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
    """Every protein / days-logged / logging-gap figure in `text` that disagrees with the
    served facts. Empty when the facts carry no nutrition record (nothing to judge
    against is a skip, never a pass-by-default on a made-up number)."""
    nut = (facts or {}).get("nutrition") or {}
    series = (facts or {}).get("protein_series") or []
    if not text or (not nut and not series):
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
        for v, _cls in claims.get("protein", []):
            win = _nl.protein_window(series, min(windows)) if windows else _nl.protein_window(series)
            if not win or win["half_width"] is None:
                continue  # no spread → no tolerance to derive; skipped, never guessed
            tol = max(float(win["half_width"]), MIN_PROTEIN_TOLERANCE_G)
            if abs(v - win["mean"]) <= tol:
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
    return findings


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
