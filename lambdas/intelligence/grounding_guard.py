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
        # "RHR", "resting HR", "resting heart rate" + a 2-3 digit number nearby.
        m = _re.search(r"\b(?:rhr|resting\s+(?:heart\s+rate|hr))\b[^.\d]{0,18}(\d{2,3})", low)
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
        # % optional ("recovery at 86" / "recovery of 30%" / "86% recovery"), but reject a
        # trailing time/weight word ("recovery over 4 weeks") — the Sentinel's _NO_TIME lesson.
        m = _re.search(
            r"recovery[^.\d]{0,14}(\d{1,3})(?!\s*(?:week|day|month|year|pound|lb|hour|min))|(\d{1,3})\s*%\s*recovery",
            low,
        )
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
    if hrv is not None and not _mentions(hrv):
        m = _re.search(r"hrv[^.\d]{0,20}(\d{1,3}(?:\.\d+)?)", low)
        if m:
            claimed = float(m.group(1))
            # HRV swings day-to-day — only flag a gross (>40% AND >8 ms) miss, e.g. 50 vs 25.2.
            if abs(claimed - hrv) > 8 and abs(claimed - hrv) / max(hrv, 1) > 0.40:
                out.append(
                    {
                        "metric": "HRV",
                        "claimed": claimed,
                        "canonical": hrv,
                        "detail": f"narrative says HRV ~{claimed:g}, but the authoritative HRV is {hrv:g} ms",
                    }
                )
    return out
