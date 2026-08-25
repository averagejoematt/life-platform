"""baseline_freshness.py — ADR-104's cycle-freshness family (#1691, epic #1687).

A coach brief can be perfectly digit-grounded against the DATA it was handed yet
still cite a STALE cycle constant. On 2026-07-22 the 07-20 briefs were frozen
with cycle-9 baselines — "starting weight of 315 lbs" (the real cycle-10 baseline
is 321.38) and "Day 1" during the pre-start window (genesis 2026-07-22, so 07-20
is PRE-START, not Day 1). `grounded:True` passed them because the number/date
gates in `grounded_generation.py` check claims-vs-DATA, never framing-vs-CYCLE-
STATE — 4 of 5 high-concern items that day were exactly this "reset-window
stale-baseline" class.

This deterministic, zero-AI family closes that gap:

  * ``baseline_freshness_findings()`` — "stale_baseline" (a cited STARTING/baseline
    weight that disagrees with the current cycle's baseline) + "stale_phase" (a
    "Day N" framing that disagrees with the true phase of the generation date).
    Takes the cycle constants as PARAMS (baseline_lbs = constants.
    EXPERIMENT_BASELINE_WEIGHT_LBS, start_date_iso = constants.EXPERIMENT_START_DATE)
    so it stays pure + unit-testable and never imports AWS or the site-api. Its
    phase logic MUST agree with site_api_common.pre_start_meta() / constants.day_n():
    gen_date < start_date -> pre_start (any "Day N" claim is stale framing);
    gen_date >= start_date -> the expected day is (gen_date - start_date).days + 1
    (1-indexed, matching day_n).
  * ``experiment_span_findings()`` (#1897) — the same arithmetic wearing word-number
    clothes: "seven days of an experiment" / "three weeks into this cycle" when the
    span exceeds the days actually elapsed.
  * ``absence_span_findings()`` (#2756) — a narrated ABSENCE span ("blank for four
    days") that disagrees with the platform's own measured dark-day count.

PROMOTION HOOK (ADR-104/105 posture): this is the deterministic layer, which CAN
graduate to a hard/HELD gate. It ships ADVISORY first (surfaced in the review pack
+ stamped into qa_archive meta at generation time); a reset-window stale brief is
exactly what its advisory finding trips, and flipping the caller from "log + stamp"
to "hold + regenerate" is the promotable suppression hook the reset AC refers to —
no restart_pipeline change is required to satisfy "no stale brief reaches a reader".

Reset suppression (AC, #1691): baseline_freshness_findings() IS the promotable
suppression hook a reset needs — restart_pipeline itself is untouched.

Moved out of grounded_generation.py 2026-08-25 (#3154, same §2-ceiling reason as
ai/behavior_logs.py #2056 and ai/regen_discard_telemetry.py #3086): grounded_generation
was sitting at its 1,200-line hard ceiling and the #3154 determiner-variant regex
fix had nowhere to land. Re-exported from grounded_generation.py so no caller's
import path changes.

Pure functions, no AWS, no HTTP.
"""

import datetime as _dt
import re

# A body-weight token: a 2-3 digit number (optionally decimal) tied to a lb/pound
# unit. The lookbehind stops it from biting a fragment of a longer number.
_WEIGHT_LB_RE = re.compile(r"(?<![\d.])(\d{2,3}(?:\.\d+)?)\s*(?:lbs?|pounds?)\b", re.IGNORECASE)

# Baseline/starting-weight FRAMING context. Only a weight sitting next to one of
# these is a candidate — a current-weight mention ("you now weigh 315 lb") never
# flags because it carries none of this framing. Mirrors band_adjective_findings'
# proximity approach (grounded_generation.py).
#
# 2026-08-25 (#3154): "start(?:ed|ing)? the experiment at" / "began the experiment
# at" hardcoded the determiner to "the" — "started THIS experiment at" (or my/our)
# sailed straight through. #3050's eval-matrix build caught it by adversarial
# canary construction (staged as a KNOWN MISS in PR #3153, flipped to CAUGHT here).
# Scoped to the same four determiners _SPAN_RE already covers below, so the fix
# closes the class without widening past it.
_BASELINE_FRAMING_RE = re.compile(
    r"\b("
    r"starting weight|start weight|baseline weight|baseline|"
    r"started at|began at|start(?:ed|ing)? (?:the|this|my|our) experiment at|began (?:the|this|my|our) experiment at|"
    r"day 1 weight|day one weight|starting point|initial weight|started out at|started from"
    r")\b",
    re.IGNORECASE,
)

# "Day N" experiment-day framing. N is captured; N==0 is treated as a non-claim
# for the pre-start case (a "Day 0"/countdown framing is the CORRECT pre-start form).
_DAY_N_RE = re.compile(r"\bday\s+(\d{1,4})\b", re.IGNORECASE)


def _phase_for(generation_date_iso: str, start_date_iso: str):
    """Pure phase resolver mirroring pre_start_meta()/day_n().

    Returns ("pre_start", None) when generation_date < start_date, else
    ("in_experiment", expected_day) with expected_day 1-indexed off start_date.
    Returns (None, None) on unparseable dates (caller skips the phase check).
    """
    try:
        gen = _dt.date.fromisoformat(generation_date_iso)
        start = _dt.date.fromisoformat(start_date_iso)
    except (TypeError, ValueError):
        return None, None
    if gen < start:
        return "pre_start", None
    return "in_experiment", (gen - start).days + 1


# ── #1897: experiment-age claims spelled out in words ───────────────────────
# On 2026-07-27 (Day 1) /api/ai_analysis?expert=nutrition published "Zero food
# logs in seven days of an experiment". Every gate was blind to it: the number
# gate is digits-only so "seven" is invisible; 7 is in the benign-numbers set
# anyway; and _DAY_N_RE matches "Day N" tokens, not "N days OF the experiment".
# A span claim is the same arithmetic as a Day-N claim wearing different clothes.
#
# This is the parser #1922 deliberately deferred: that issue moved NUMERIC
# phase-bound claims into deterministic code and left word-numbers with the LLM
# precisely because "seven" is not arithmetic until something parses it. This
# parses it, so the class comes back to the deterministic side.
_WORD_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
    "sixty": 60,
    "ninety": 90,
    "a": 1,
    "an": 1,
}

# "N days of the experiment" / "three weeks into this experiment" / "seven days in".
# Requires the experiment framing — a bare "six days" may be about anything
# (a training block, a sleep streak), and flagging those would make the gate noise.
#
# 2026-08-25 (#3154 sibling sweep): this one already spans the/this/my/our (plus
# his/her) before the noun — no determiner-width gap here, unlike the
# _BASELINE_FRAMING_RE class this pattern sits alongside.
_SPAN_RE = re.compile(
    r"\b(?P<n>\d{1,4}|" + "|".join(sorted(_WORD_NUMBERS, key=len, reverse=True)) + r")\s+"
    r"(?P<unit>days?|weeks?|months?)\s+"
    r"(?:of|into|in\b(?!\s+a\s+row))\s+"
    r"(?:this\s+|the\s+|an\s+|my\s+|his\s+|her\s+|our\s+)?"
    r"(?:current\s+|new\s+|fresh\s+)?"
    r"(?:experiment|cycle|season|run|protocol)\b",
    re.IGNORECASE,
)
_SPAN_UNIT_DAYS = {"day": 1, "days": 1, "week": 7, "weeks": 7, "month": 30, "months": 30}


def _span_to_days(n_token: str, unit_token: str):
    """(count, unit) -> days, or None when the count is not a number we parse."""
    tok = (n_token or "").strip().lower()
    n = _WORD_NUMBERS.get(tok)
    if n is None:
        try:
            n = int(tok)
        except (TypeError, ValueError):
            return None
    return n * _SPAN_UNIT_DAYS.get((unit_token or "").strip().lower(), 1)


def absence_span_findings(text: str, *, known_absence_days: dict = None) -> list:
    """#2756: a narrated ABSENCE span must match the measured one.

    Live case: the nutrition coach said MacroFactor had "been blank for four
    days" while the platform's own absence derivation said 52 — the fact pack
    carried None for an empty window and the model filled the vacuum. The span
    gate above could not catch it (4 < elapsed is a legal span); this class can,
    because the caller HANDS IT the measured truth.

    `known_absence_days` maps a category label to the measured dark-day count
    (e.g. {"food": 52}). A sentence that talks about absence (blank/dark/quiet/
    no logs/hasn't logged) and states a day-span differing from the measured
    value by more than 1 day is a finding. Precision-first: sentences without
    absence vocabulary are never touched, and a ±1 tolerance absorbs the
    end-of-day boundary. Findings use the shared {"type", "detail"} shape.
    """
    if not text or not known_absence_days:
        return []
    findings = []
    sentences = re.split(r"(?<=[.!?])\s+", text)
    word_nums = "|".join(_WORD_NUMBERS)
    span_re = re.compile(rf"\b(\d{{1,4}}|{word_nums})[-\s]day(?:s)?\b|\b(\d{{1,4}}|{word_nums})\s+days?\b", re.IGNORECASE)
    absent_re = re.compile(
        r"blank|dark|quiet|silen|no (?:food )?log|hasn'?t (?:been )?logg|nothing (?:has been )?logged|without (?:a )?(?:single )?log|unlogged",
        re.IGNORECASE,
    )
    for cat, true_days in known_absence_days.items():
        if true_days is None:
            continue
        for sent in sentences:
            if not absent_re.search(sent):
                continue
            for m in span_re.finditer(sent):
                raw = (m.group(1) or m.group(2) or "").lower()
                n = _WORD_NUMBERS.get(raw) if raw in _WORD_NUMBERS else (int(raw) if raw.isdigit() else None)
                if n is None or n == 0:
                    continue
                if abs(n - int(true_days)) > 1:
                    findings.append(
                        {
                            "type": "absence_span",
                            "category": cat,
                            "claimed_days": n,
                            "true_days": int(true_days),
                            "detail": (
                                f"the narrative states a {n}-day {cat} absence, but the measured span is "
                                f"{int(true_days)} day(s) dark — an understated absence reads as a smaller "
                                f"lapse than the record shows (#2756)"
                            ),
                        }
                    )
    return findings


def experiment_span_findings(text: str, *, generation_date_iso: str, start_date_iso: str) -> list:
    """Deterministic check on claimed experiment AGE, digits or words (#1897).

    Flags "seven days of an experiment" / "three weeks into this cycle" when the
    span exceeds the days actually elapsed. Pre-start (generation before genesis)
    flags ANY positive span — zero days of the current experiment exist yet.

    A span SHORTER than the elapsed days is correct and never flagged: trailing
    windows clamp to genesis (ADR-077 "clamped, not hidden"), which is the same
    lower-bound rule #1917 had to teach the LLM rubric after it flagged 5-on-Day-6
    three times. Only a LONGER span is impossible.

    Findings use the shared {"type", "detail"} shape (type "experiment_span") so
    they compose with grounding_findings() / correction_prompt() in grounded_generation.py.
    """
    phase, expected_day = _phase_for(generation_date_iso, start_date_iso)
    if phase is None:
        return []
    findings = []
    seen = set()
    for m in _SPAN_RE.finditer(text or ""):
        days = _span_to_days(m.group("n"), m.group("unit"))
        if days is None:
            continue
        claim = m.group(0).strip()
        if claim.lower() in seen:
            continue
        if phase == "pre_start":
            seen.add(claim.lower())
            findings.append(
                {
                    "type": "experiment_span",
                    "claim": claim,
                    "detail": (f'the narrative claims "{claim}", but the experiment has not started yet — ' f"zero days of it exist"),
                }
            )
        elif days > expected_day:
            seen.add(claim.lower())
            findings.append(
                {
                    "type": "experiment_span",
                    "claim": claim,
                    "detail": (
                        f'the narrative claims "{claim}" ({days} day(s)), but only {expected_day} day(s) '
                        f"have elapsed since genesis — that history does not exist"
                    ),
                }
            )
    return findings


def baseline_freshness_findings(
    text: str,
    *,
    generation_date_iso: str,
    baseline_lbs: float = None,
    start_date_iso: str,
    weight_tolerance_lbs: float = 1.0,
    proximity: int = 45,
) -> list:
    """Deterministic cycle-freshness check for coach-authored output (#1691).

    Two finding classes, both zero-AI and framing-scoped:

    - "stale_baseline": a cited STARTING/baseline weight (a weight token within
      `proximity` chars of baseline framing — "starting weight", "baseline",
      "started at", "Day 1 weight", …) that disagrees with `baseline_lbs` by more
      than `weight_tolerance_lbs`. Current-weight mentions carry no baseline framing
      and never flag. Skipped entirely when `baseline_lbs` is None.
    - "stale_phase": a "Day N" experiment-day framing that disagrees with the true
      phase of `generation_date_iso`. If pre_start (gen < start): ANY "Day N" (N>=1)
      is a finding — correct framing is the pre-start countdown. If in-experiment:
      a cited N != the real day (day_n(gen)) is a finding.

    Same ``{"type": ..., "detail": ...}`` shape as the other grounded_generation
    finding classes, so it composes with grounding_findings()/correction_prompt().
    """
    text = text or ""
    findings = []

    # ── stale_baseline ────────────────────────────────────────────────────────
    if baseline_lbs is not None:
        try:
            baseline = float(baseline_lbs)
        except (TypeError, ValueError):
            baseline = None
        if baseline is not None:
            weight_tokens = []  # (start, end, value)
            for wm in _WEIGHT_LB_RE.finditer(text):
                try:
                    weight_tokens.append((wm.start(1), wm.end(1), float(wm.group(1))))
                except ValueError:
                    continue
            seen_tokens = set()
            for fm in _BASELINE_FRAMING_RE.finditer(text):
                f_start, f_end = fm.start(), fm.end()
                # Nearest weight token to THIS baseline-framing phrase, within window.
                best, best_dist = None, None
                for ws, we, val in weight_tokens:
                    if ws >= f_end:
                        dist = ws - f_end
                    elif we <= f_start:
                        dist = f_start - we
                    else:
                        dist = 0
                    if dist <= proximity and (best_dist is None or dist < best_dist):
                        best, best_dist = (ws, val), dist
                if best is None:
                    continue
                ws, val = best
                if ws in seen_tokens:
                    continue
                seen_tokens.add(ws)
                if abs(val - baseline) > weight_tolerance_lbs:
                    findings.append(
                        {
                            "type": "stale_baseline",
                            "claimed": round(val, 4),
                            "expected": round(baseline, 4),
                            "detail": (
                                f"the narrative cites a starting/baseline weight of {val:g} lb next to baseline framing, "
                                f"but the current cycle baseline is {baseline:g} lb"
                            ),
                        }
                    )

    # ── stale_phase ───────────────────────────────────────────────────────────
    phase, expected_day = _phase_for(generation_date_iso, start_date_iso)
    if phase is not None:
        seen_days = set()
        for dm in _DAY_N_RE.finditer(text):
            n = int(dm.group(1))
            if n in seen_days:
                continue
            if phase == "pre_start":
                if n >= 1:
                    seen_days.add(n)
                    findings.append(
                        {
                            "type": "stale_phase",
                            "claimed_day": n,
                            "detail": (
                                f'the narrative frames this as "Day {n}", but the generation date '
                                f"{generation_date_iso} is BEFORE genesis {start_date_iso} (pre-start) — the correct "
                                f"framing is the pre-start countdown, not a Day count"
                            ),
                        }
                    )
            else:  # in_experiment
                if n != expected_day:
                    seen_days.add(n)
                    findings.append(
                        {
                            "type": "stale_phase",
                            "claimed_day": n,
                            "expected_day": expected_day,
                            "detail": (
                                f'the narrative cites "Day {n}", but generation date {generation_date_iso} is '
                                f"Day {expected_day} of the experiment (genesis {start_date_iso})"
                            ),
                        }
                    )
    return findings
