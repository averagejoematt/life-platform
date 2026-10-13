# gate-entrypoint: the SS-10 tight canonical-contradiction verdict.
# `hard_canonical_contradictions` returns the hits that
# `field_notes_lambda._note_grounding_findings` HOLDS on and that
# `ai_expert_analyzer_lambda` block-and-regens on. A list of hits IS the verdict, so
# there is no raise and no exit for the AST to see: if this function silently returned
# `[]` both consumers would publish unchecked and every check would stay green — the
# exact dark-gate shape #2578 exists to count. Nothing else in the census reports it
# (#2578 adjudication of #3220's ten name-only rows).
"""grounding_guard.py — the shared TIGHT canonical-facts contradiction detector.

SS-10: one un-driftable detector for "the narrative states a physiological number
that hard-contradicts the authoritative daily record", shared by every generation
path that block-and-regens (ai_expert_analyzer's self-correction; field-notes).
Extracted verbatim from ai_expert_analyzer_lambda._hard_canonical_contradictions
(2026-07-02) so the field note — the public Third Wall, previously ungated —
gets the SAME proven guard instead of a drifting copy.

Why not the layer's coherence_invariants.check_facts_agreement: that detector is
precision-tuned for a daily ALARM (20-25% tolerances) — the live RHR-53-vs-64
incident (a 17% miss) sails through it by design. This one is the tight local
guard for generation-time correction, where a false positive only costs one
corrective rewrite, never an alarm email.

Scope: RHR / recovery / HRV only — the three MEASURED physiological vitals. Two
kinds of value are deliberately EXCLUDED (both are documented decisions, not gaps):
  - WEIGHT: loss totals ("13.8 pounds") are deltas, not bodyweight, and invite
    false positives.
  - DERIVED / PROXY values, TSB first (M-8 / #493, ADR-109): TSB (training stress
    balance = CTL−ATL) is a duration-PROXY Banister estimate, not a measurement — its
    own "canonical" number carries uncertainty, and it is signed and crosses zero, so a
    tight block-and-regen guard here would false-positive and, worse, correct a coach
    against a figure that is itself an estimate. Derived values are covered instead by
    the SCHEDULED cross-surface scan (coherence_invariants.check_facts_agreement, wide
    ABSOLUTE tolerance) where a false alarm costs a digest line, not a rewrite. This
    module stays the tight generation-time guard for the measured vitals only.

Spelled-number gap (closed here): every guard used to be digit-based, so
"recovery of twelve" passed unchecked. `_spelled_to_digits` normalizes
teens/tens/compounds ("sixty-four" → 64) before matching. "one"/"two" are
deliberately NOT converted — too ambiguous in prose ("recovery is one of…"),
and no plausible vital is spelled that small.

Bundled module (Code.from_asset lambdas/) — no layer dance to change it.
"""

import re as _re

_UNITS = {
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
}
_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}
_ONES = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9}

_COMPOUND_RE = _re.compile(r"\b(" + "|".join(_TENS) + r")(?:[-\s](" + "|".join(_ONES) + r"))?\b|\b(" + "|".join(_UNITS) + r")\b")


def _spelled_to_digits(low_text: str) -> str:
    """Normalize spelled-out numbers to digits so the metric regexes see them.
    Handles tens, tens-compounds ("sixty-four"/"sixty four"), and 3–19."""

    def _sub(m):
        if m.group(1):  # tens (+ optional unit)
            return str(_TENS[m.group(1)] + (_ONES.get(m.group(2), 0) if m.group(2) else 0))
        return str(_UNITS[m.group(3)])

    return _COMPOUND_RE.sub(_sub, low_text)


# ── The numeric token (#3327) ────────────────────────────────────────────────────
# A number is bound to a metric ONLY when it is the metric's value. Three defects let
# ordinary duration phrases phantom-flag on this BLOCKING gate (7 of 10 phrases in the
# issue's set: "Recovery over 12 weeks" → claimed 1; "RHR over 120 days" → 120;
# "Recovery on 7.5 hours of sleep" → 7):
#   * RHR and HRV had no unit lookahead at all;
#   * recovery's lookahead sat AFTER a backtracking `(\d{1,3})`, so "12 weeks" retreated
#     to "1" and passed it, and a decimal's integer part was captured alone.
# The fix is structural, not a longer word list: the token is parsed WHOLE — anchored on
# both sides so the engine cannot retreat "12"→"1", and the decimal is consumed with its
# integer part so "7.5" can never yield "7" — and only THEN is the unit decided. Because
# the gap before the token excludes digits, a rejected token has no shorter alternative:
# the match fails at that keyword and the engine moves to the next occurrence.
_NUM_VALUE = r"(?<![\d.])(\d{1,3}(?:\.\d+)?)(?![\d.]?\d)"
# Duration / time / weight / count words: a number wearing one of these is a span or a
# tally, never an RHR, recovery, or HRV value. Bounded with \b so "hr" rejects "hrs" but
# not "hrv", and an optional hyphen covers "12-week" / "120-day". Ordinals ("12th week")
# and the multiplier "x" ("3x") are counts too. Value units stay allowed: bpm, ms, and —
# for recovery only — "%" (recovery's own unit; on RHR/HRV a percent is a change, not a
# reading, so those two reject it as well). "points"/"pts" is a delta idiom ("recovery up
# 12 points") on every one of the three.
_COUNT_UNITS = (
    r"weeks?|wks?|days?|months?|years?|yrs?|hours?|hrs?|minutes?|mins?|seconds?|secs?|nights?|mornings?|"
    r"sessions?|workouts?|reps?|sets?|rounds?|times?|pounds?|lbs?|kgs?|kilos?|grams?|miles?|km|steps?|"
    r"calories?|kcal|cal|points?|pts?|st|nd|rd|th|x"
)
_NOT_A_COUNT = r"(?!\s*(?:-\s*)?(?:" + _COUNT_UNITS + r")\b)"
_NOT_A_PERCENT = r"(?!\s*(?:%|percent\b|pct\b))"

# "RHR", "resting HR", "resting heart rate" + the value within a short gap. bpm allowed.
_RHR_RE = _re.compile(r"\b(?:rhr|resting\s+(?:heart\s+rate|hr))\b[^.\d]{0,18}" + _NUM_VALUE + _NOT_A_COUNT + _NOT_A_PERCENT)
# % optional ("recovery at 86" / "recovery of 30%" / "86% recovery") — the Sentinel's
# _NO_TIME lesson, now applied to the WHOLE token rather than after a retreating one.
_RECOVERY_RE = _re.compile(
    r"recovery[^.\d]{0,14}" + _NUM_VALUE + _NOT_A_COUNT + r"|(?<![\d.])(\d{1,3}(?:\.\d+)?)\s*%\s*recovery",
)
# HRV + the value (1-dp allowed: canonical is e.g. 25.2). ms allowed.
_HRV_RE = _re.compile(r"\bhrv\b[^.\d]{0,20}" + _NUM_VALUE + _NOT_A_COUNT + _NOT_A_PERCENT)

# ── #4866: the HRV authority is resolved over the window the narrative names ─────────────
# 2026-10-12 14:00Z (request 90f7c52f): one stored Whoop reading (136.92 ms on 10-11, every
# other reading this cycle 33-50) was taken as "the authoritative HRV" against narratives
# about weeks 2 and 5-6, so experiment_arc and integrator_month were HELD. A week/month figure
# is now compared with that window's MEDIAN (robust to exactly this outlier), a day figure
# with the day.
# N = 2.5: ordinary day-to-day HRV swings in this series stay under ~1.6x the trailing median
# (62 -> 73 -> 52 -> 50), while the 10-11 reading was 2.7x; 2.5 separates the two with margin.
HRV_OUTLIER_MULTIPLE = 2.5
HRV_OUTLIER_MIN_PRIOR = 3  # fewer trailing readings than this is no baseline to call anything an outlier
_WINDOW_DAYS = {"day": 1, "week": 7, "month": 30}
_WEEK_RE = _re.compile(r"\b(?:week|weeks|weekly|this week|7-day|seven days|seven-day)\b")
_MONTH_RE = _re.compile(r"\b(?:month|months|monthly|30-day|thirty days)\b")


def _median(vals):
    v = sorted(vals)
    n = len(v)
    if not n:
        return None
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


# A numbered week is "Week 2" / "weeks 5-6" (1-52, not a unit): "this week 137 ms", "the past week 20 ms" are not.
_NUMBERED_WEEK_RE = _re.compile(
    r"(?<!\bthis )(?<!\bpast )(?<!\blast )(?<!\bnext )(?<!\bper )(?<!\beach )(?<!\bevery )"
    r"\bweeks?\s+(?:[1-9]|[1-4]\d|5[0-2])\b(?!\s*(?:ms|milliseconds?)\b)"
)


def narrative_window(low, start, end):
    """The window the sentence around ``low[start:end]`` names: named_week > month > week > day.

    "named_week" is a specific numbered week ("Week 2 ... HRV tanked to 33.9"): a historic window
    the trailing series cannot speak for, so it has NO authority here (see resolve_hrv_authority).
    """
    a = max(low.rfind(".", 0, start), low.rfind("\n", 0, start)) + 1
    b = [i for i in (low.find(".", end), low.find("\n", end)) if i != -1]
    sent = low[a : min(b) if b else len(low)]
    if _NUMBERED_WEEK_RE.search(sent):
        return "named_week"
    if _MONTH_RE.search(sent):
        return "month"
    if _WEEK_RE.search(sent):
        return "week"
    return "day"


def is_vendor_outlier(value, others):
    """True when ``value`` exceeds HRV_OUTLIER_MULTIPLE x the median of ``others`` (needs a baseline)."""
    others = [o for o in others if o is not None]
    if len(others) < HRV_OUTLIER_MIN_PRIOR:
        return False
    med = _median(others)
    return bool(med) and value > HRV_OUTLIER_MULTIPLE * med


def resolve_hrv_authority(facts, window):
    """-> (value, source_text, outlier_note|None) for the HRV figure over ``window``.

    day   : facts["hrv_ms"], unless it is a vendor outlier vs the trailing series, then the
            trailing median stands in and the note names the outlier.
    week / month : median of the last 7 / 30 stored days (hrv_series), falling back to the day
            value when no series is supplied (the pre-#4866 behaviour, named as such).
    """
    day_val = facts.get("hrv_ms")
    if window == "named_week":
        # A specific numbered week is not in the trailing series; comparing it with today's reading
        # (or the current week's median) is the cross-window error #4866 fixes. The allow-list gate
        # still catches an invented figure; nothing here can verify or refute this one.
        return None, "no stored series for that numbered week", None
    series = [(r.get("date"), r.get("hrv")) for r in (facts.get("hrv_series") or []) if r.get("hrv") is not None]
    src = facts.get("hrv_series_source") or "canonical facts"
    if not series:
        return day_val, f"{src} latest reading (no series supplied)", None
    series.sort()
    vals = [v for _, v in series]
    if window == "day":
        if day_val is None:
            return None, src, None
        trailing = [v for v in vals if abs(v - day_val) > 0.005]
        # Isolated only: another reading in the last 7 days above the same bar means a sustained
        # change, not a single-day glitch, and the day value stands as its own authority.
        recent_high = [v for v in trailing[-6:] if is_vendor_outlier(v, [o for o in trailing if o != v])]
        if not recent_high and is_vendor_outlier(day_val, trailing):
            med = _median(trailing)
            note = (
                f"the stored {day_val:g} ms reading is a single-day vendor outlier "
                f"(>{HRV_OUTLIER_MULTIPLE:g}x the trailing median {med:g} ms) and is not used as authority"
            )
            return med, f"{src} trailing median ({len(trailing)} readings)", note
        return day_val, f"{src} latest reading", None
    win = vals[-_WINDOW_DAYS[window] :]
    return _median(win), f"{src} {window} median ({len(win)} readings)", None


def hard_canonical_contradictions(text, facts):
    """Pure: does the narrative state an RHR, recovery, or HRV number that hard-
    contradicts the canonical facts? Returns [{metric, claimed, canonical, detail}].

    Scoped to the three physiological metrics the Coherence Sentinel caught coaches
    inventing across a re-run (RHR 53/56-57 vs 64; recovery 73 vs 30; HRV 50 vs 25.2).
    Tolerances are per-metric — RHR/recovery are stable (tight), HRV swings
    day-to-day (loose 40%, only catches a ~2x error).
    """
    low = _spelled_to_digits((text or "").lower())

    def _mentions(val):
        # Canonical number appears anywhere (int or 1-dp) → coach is grounded, even in
        # a trend ("RHR climbed from 64 to 66" cites 64). Mirrors the Sentinel's check
        # so the guard and the detector agree on what counts as a contradiction.
        forms = {str(int(round(val)))}
        if abs(val - round(val)) > 0.05:
            forms.add(f"{val:.1f}")
        return any(_re.search(r"(?<![\d.])" + _re.escape(v) + r"(?![\d])", low) for v in forms)

    out = []
    rhr = facts.get("rhr_bpm")
    if rhr is not None and not _mentions(rhr):
        # "RHR", "resting HR", "resting heart rate" + the value nearby (#3327: whole token,
        # duration/percent rejected — "RHR over 120 days" binds nothing).
        m = _RHR_RE.search(low)
        if m:
            claimed = float(m.group(1))
            # RHR is physiologically stable; flag a >4 bpm AND >7% miss (kills rounding noise).
            if abs(claimed - rhr) > 4 and abs(claimed - rhr) / max(rhr, 1) > 0.07:
                out.append(
                    {
                        "metric": "resting HR",
                        "claimed": claimed,
                        "canonical": rhr,
                        "detail": f"narrative says RHR ~{claimed:g}, but the authoritative resting HR is {rhr:g} bpm",
                    }
                )
    rec = facts.get("recovery_pct")
    if rec is not None and not _mentions(rec):
        # % optional ("recovery at 86" / "recovery of 30%" / "86% recovery"), a trailing
        # time/weight/count word rejects the WHOLE token (#3327: "recovery over 12 weeks"
        # used to retreat to "1"; "on 7.5 hours" to "7").
        m = _RECOVERY_RE.search(low)
        if m:
            claimed = float(m.group(1) or m.group(2))
            if claimed <= 100 and abs(claimed - rec) > 10:  # recovery 0-100; a >10-pt miss is a real contradiction
                out.append(
                    {
                        "metric": "Whoop recovery",
                        "claimed": claimed,
                        "canonical": rec,
                        "detail": f"narrative says recovery ~{claimed:g}%, but the authoritative Whoop recovery is {rec:g}%",
                    }
                )
    hrv = facts.get("hrv_ms")
    if hrv is not None:
        # #3327: whole token, duration/percent rejected — "HRV over the 120 days" binds nothing.
        m = _HRV_RE.search(low)
        if m:
            window = narrative_window(low, m.start(), m.end())  # #4866: the window the narrative names
            auth, source, outlier_note = resolve_hrv_authority(facts, window)
            claimed = float(m.group(1))
            # HRV swings day-to-day — only flag a gross (>40% AND >8 ms) miss, e.g. 50 vs 25.2.
            if auth is not None and not _mentions(auth) and abs(claimed - auth) > 8 and abs(claimed - auth) / max(auth, 1) > 0.40:
                detail = f"narrative says HRV ~{claimed:g}, but the authoritative HRV is {auth:g} ms [{window} window vs {source}]"
                if outlier_note:
                    detail += f"; {outlier_note}"
                out.append(
                    {
                        "metric": "HRV",
                        "claimed": claimed,
                        "canonical": auth,
                        "window": window,
                        "source": source,
                        "detail": detail,
                    }
                )
    return out


def comparison_basis(findings):
    """One short string naming the window + source each windowed finding compared against (#4866)."""
    seen = []
    for f in findings:
        if f.get("window"):
            b = f"{f.get('metric', f.get('type', '?'))}: {f['window']} window vs {f.get('source', '?')}"
            if b not in seen:
                seen.append(b)
    return "; ".join(seen) or "allow-list / canonical facts (no windowed comparison)"
