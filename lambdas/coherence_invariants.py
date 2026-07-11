"""
coherence_invariants.py — pure correctness invariants for the intelligence layer.

The platform proves it's ALIVE (freshness, auth, errors, render) but almost
nothing proves it's RIGHT. Every painful bug this era shared one shape — a
subsystem producing INCOHERENT output while staying green — rooted in implicit
producer/consumer contracts:

  - coach predictions 100% inconclusive for weeks (every machine pred had
    threshold=None) — undetected;
  - the 30-vs-86 recovery split (coaches citing contradictory numbers);
  - the experiment arc counting 7 weeks vs the 3 the UI shows;
  - handle_predictions reading the wrong DDB field -> all-zeros, silently.

These functions are the DETECTION layer: each asserts one invariant on already-
fetched data and returns a Finding. They are PURE (no boto3, no network, no
clock) so they unit-test by replaying a known-past-bug fixture. The Lambda
(lambdas/operational/coherence_sentinel_lambda.py) fetches the live data, adapts
it to these input contracts, and turns Findings into CloudWatch metrics + a
digest. Keep this module dependency-free so it stays trivially testable.

Severity ladder: OK < WARN < ALARM. ALARM is reserved for "this is the signature
of a real past outage" (e.g. nothing ever grades); WARN is "drifting, look".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

OK = "ok"
PRE_START = "pre_start"  # #942: sanctioned countdown window (#931) — OK-severity, but distinct so the digest can say why
WARN = "warn"
ALARM = "alarm"
_RANK = {OK: 0, PRE_START: 0, WARN: 1, ALARM: 2}

# How far in the future EXPERIMENT_START_DATE may sit before a "genesis > today"
# reading stops being the sanctioned countdown window and becomes a mis-set
# constant (#942). Resets stage Day 1 ~2 days out; 7 gives headroom without
# letting a fat-fingered month/year silently pass.
PRE_START_GRACE_DAYS = 7


@dataclass
class Finding:
    """One invariant's verdict. `value` is the headline metric (emitted to CW)."""

    name: str
    status: str = OK
    value: float = 0.0
    detail: str = ""
    offenders: list = field(default_factory=list)

    @property
    def is_alarm(self) -> bool:
        return self.status == ALARM

    def worse_of(self, status: str) -> str:
        return status if _RANK[status] > _RANK[self.status] else self.status


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 1 — Prediction health
#   The C-3 outage: every metric-backed prediction was a machine spec with
#   threshold=None, so the evaluator could only ever return inconclusive. The
#   board made hundreds of calls and ZERO ever resolved, for weeks, with no
#   alarm. Signature: among predictions whose window has CLOSED, the decided
#   rate is 0. Also watch a runaway qualitative share (the other failure mode —
#   everything silently routed to un-gradable).
# ─────────────────────────────────────────────────────────────────────────────
def check_prediction_health(
    predictions,
    *,
    min_closed: int = 8,
    max_qualitative_share: float = 0.9,
) -> Finding:
    """`predictions`: list of {status, closed (bool), eval_type}.

    `closed` = the evaluation window has elapsed (so the call SHOULD have graded).
    Fires ALARM when enough calls have closed but none decided — the exact
    signature of the weeks-long all-inconclusive outage.
    """
    total = len(predictions)
    f = Finding("prediction_health", value=1.0)
    if total == 0:
        f.detail = "no predictions on the board"
        return f

    closed = [p for p in predictions if p.get("closed")]
    decided = [p for p in closed if p.get("status") in ("confirmed", "refuted")]
    qualitative = [p for p in predictions if p.get("eval_type") == "qualitative"]
    qual_share = len(qualitative) / total
    decided_rate = (len(decided) / len(closed)) if closed else None

    f.value = decided_rate if decided_rate is not None else 1.0

    if len(closed) >= min_closed and len(decided) == 0:
        f.status = ALARM
        f.detail = f"{len(closed)} predictions past their window but 0 decided — nothing is grading (C-3 signature)"
        return f
    if qual_share > max_qualitative_share and total >= min_closed:
        f.status = WARN
        f.detail = f"{qual_share:.0%} of predictions are qualitative (ungradable) — extraction may be drifting"
        return f
    if decided_rate is not None and decided_rate < 0.05 and len(closed) >= min_closed:
        f.status = WARN
        f.detail = f"only {decided_rate:.0%} of closed predictions decided"
        return f
    f.detail = f"{len(decided)}/{len(closed)} closed predictions decided, {qual_share:.0%} qualitative"
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 2 — Computed-metric internal coherence
#   A stored computed record (character level, day grade, readiness) must agree
#   with what its OWN components imply. Unit tests prove the algorithm; nothing
#   checks the live stored output still matches a re-derivation. Catches silent
#   compute drift (e.g. a rounding change inflating every recovery signal).
#   Input: list of {name, stored, expected, tol}. tol is absolute.
# ─────────────────────────────────────────────────────────────────────────────
def check_computed_coherence(checks) -> Finding:
    f = Finding("computed_coherence", value=0.0)
    offenders = []
    for c in checks:
        stored, expected = c.get("stored"), c.get("expected")
        if stored is None or expected is None:
            continue
        tol = float(c.get("tol", 0.0))
        if abs(float(stored) - float(expected)) > tol:
            offenders.append(f"{c['name']}: stored {stored} vs derived {expected} (tol {tol})")
    f.value = float(len(offenders))
    if offenders:
        f.status = ALARM
        f.offenders = offenders
        f.detail = "; ".join(offenders[:5])
    else:
        f.detail = f"{len(checks)} computed metrics agree with their components"
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 3 — Canonical-facts cross-surface agreement
#   The 30-vs-86 bug: coaches cited contradictory numbers for the same day's
#   metric. The per-generation grounding (Mode-B) catches some; this is the
#   scheduled cross-surface scan over the day's SERVED narratives. For each
#   canonical fact, find numbers cited near its keyword and flag any that
#   contradict the authoritative value beyond tolerance — plus the HRV-in-bpm
#   unit error (HRV is milliseconds).
# ─────────────────────────────────────────────────────────────────────────────
# metric_key -> (bound capture patterns, tolerance as fraction of true value).
# Each pattern binds the number TIGHTLY to its metric (adjacency + unit) so a
# value for one metric can't be misread as another's — proximity scanning
# cross-contaminates (RHR 58 in the same sentence as HRV looks like an HRV value).
# Capturing group 1 is the cited number.
# A captured number followed by a time/count word isn't a metric reading — it's a
# duration ("recovery over 4 WEEKS", "53 over 14 DAYS"). The live run flagged these.
# Reject a captured number that's really part of a larger figure or a duration/count:
# `(?!\d|,\d)` kills "4" in "4,000 steps" (comma-then-digit) WITHOUT rejecting a
# sentence comma ("86, you're primed"); _NO_TIME kills "4 weeks"/"4 points".
_NOT_PART = r"(?!\d|,\d)"
_NO_TIME = r"(?!\s*(?:week|day|month|night|hour|min|session|time|point|pt|step|k\b|x\b))"
_FACT_PATTERNS = {
    "recovery_pct": (
        [r"recovery[^.\d]{0,14}(\d{1,3}(?:\.\d+)?)" + _NOT_PART + r"\s*%?" + _NO_TIME, r"(\d{1,3}(?:\.\d+)?)\s*%\s*recovery"],
        0.20,
    ),
    # HRV value must carry the ms unit to count (the bpm form is the unit-error check below).
    "hrv_ms": ([r"hrv[^.\d]{0,14}(\d{1,3}(?:\.\d+)?)\s*ms", r"(\d{1,3}(?:\.\d+)?)\s*ms[^.]{0,14}hrv"], 0.25),
    "rhr_bpm": (
        [r"(?:resting heart rate|resting hr|rhr)[^.\d]{0,14}(\d{2,3})" + _NOT_PART + _NO_TIME, r"(\d{2,3})\s*bpm[^.]{0,18}rest"],
        0.20,
    ),
    # Weight requires an explicit lb/lbs/pounds unit so a "190 g protein" can't match.
    "latest_weight": ([r"(\d{2,3}(?:\.\d+)?)\s*(?:lbs|lb|pounds)\b"], 0.04),
    # TSB (training stress balance = CTL−ATL) — a DERIVED, duration-PROXY Banister value,
    # not a measured vital (M-8 / #493). Covered HERE (the scheduled cross-surface scan,
    # where a false alarm costs one digest line) but deliberately EXCLUDED from the tight
    # generation-time grounding_guard (ADR-109): its own "canonical" number is an estimate,
    # so block-and-regenning a coach against it is inappropriate. TSB is SIGNED and crosses
    # zero, so its tolerance is ABSOLUTE points (_ABS_TOL), not a fraction of the value — the
    # fractional band below collapses to ~0 at the zero crossing (false positives) and is
    # sign-blind — and its plausible range is an ABSOLUTE band (_ABS_PLAUSIBILITY). The
    # captured number may carry a leading '-'. `tol` here is a placeholder (abs-tol keys
    # ignore it). Wide by design: only a gross miss is a real contradiction for a proxy.
    "tsb": ([r"(?:training stress balance|tsb)\b[^.\d]{0,12}?(-?\d{1,3}(?:\.\d+)?)"], 0.0),
}
# A cited number only competes as a claim about THAT metric if it's in the metric's
# plausible range. Without this, "lost 13.8 POUNDS" reads as a current-weight claim
# contradicting a 300 lb canonical (a weight DELTA, not the weight). Multiplicative
# band vs the canonical; metrics not listed accept any value (recovery can be 0–100,
# so a real 30-vs-86 split must still fire). Tuned from the first live run.
_PLAUSIBILITY = {"latest_weight": (0.6, 1.5)}
# SIGNED facts (can be negative or ~0, e.g. TSB) need an ABSOLUTE tolerance (metric points)
# and an ABSOLUTE plausible range — the multiplicative _PLAUSIBILITY / abs(true)*frac forms
# are meaningless when the canonical value straddles zero. Keyed here, applied in
# check_facts_agreement. See ADR-109: derived/proxy values are covered by this scheduled
# scan (wide absolute tolerance), never by the tight generation-time grounding_guard.
_ABS_TOL = {"tsb": 12.0}  # ±12 TSB points — wide; TSB is a proxy estimate, only a gross miss is a real contradiction
_ABS_PLAUSIBILITY = {"tsb": (-70.0, 70.0)}  # outside this a cited number isn't a TSB claim (a stray value the regex grabbed)


def _cited_for_metric(low_text: str, patterns):
    out = []
    for pat in patterns:
        for m in re.finditer(pat, low_text):
            try:
                out.append(float(m.group(1)))
            except (ValueError, IndexError):
                pass
    return out


def _mentions_value(low_text: str, true_val: float) -> bool:
    """Does the canonical number appear anywhere in the text (int or 1-dp form)?
    Used to recognise a grounded trend — "recovery dropped from 86 to 30" cites the
    canonical 30 even though the tight metric window only captured the historical 86."""
    forms = {str(int(round(true_val)))}
    if abs(true_val - round(true_val)) > 0.05:
        forms.add(f"{true_val:.1f}")
    return any(re.search(r"(?<![\d.])" + re.escape(v) + r"(?![\d])", low_text) for v in forms)


def check_facts_agreement(narratives, facts, *, surfaces=None) -> Finding:
    """`narratives`: list of served text blobs. `facts`: the canonical dict
    ({recovery_pct, hrv_ms, rhr_bpm, latest_weight}, plus optional derived `tsb`).
    Flags a cited number that contradicts a fact by > its tolerance, and HRV quoted
    in bpm. Tuned for PRECISION (a false alarm erodes trust) — the AI semantic pass
    carries recall. Derived values (tsb, M-8/#493) get a WIDE absolute tolerance."""
    f = Finding("facts_agreement", value=0.0)
    offenders = []
    labels = surfaces or [f"narrative_{i}" for i in range(len(narratives))]
    for text, label in zip(narratives, labels):
        if not text:
            continue
        low = text.lower()
        # HRV-unit error: an HRV value directly carried in bpm (HRV is milliseconds).
        # Require number-then-bpm right after HRV so "HRV 25 ms and RHR 64 bpm" — two
        # different metrics in one sentence — does NOT false-fire (the live-run trap).
        if re.search(r"hrv[^.\d]{0,12}\d{1,3}(?:\.\d+)?\s*bpm", low):
            offenders.append(f"{label}: HRV cited in bpm (HRV is milliseconds)")
        for key, (patterns, tol) in _FACT_PATTERNS.items():
            true_val = facts.get(key)
            signed = key in _ABS_TOL
            # 0 means "no data" for the positive vitals (recovery/hrv/rhr/weight); a SIGNED
            # metric (TSB) can legitimately be a real 0, so only skip it when truly absent.
            if true_val is None or (not signed and true_val == 0):
                continue
            true_val = float(true_val)
            if signed:
                band = _ABS_TOL[key]
                lo, hi = _ABS_PLAUSIBILITY[key]
                in_range = [c for c in _cited_for_metric(low, patterns) if lo <= c <= hi]
            else:
                band = abs(true_val) * tol
                lo, hi = _PLAUSIBILITY.get(key, (0.0, 1e9))
                # Only the in-plausible-range citations count as claims about this metric.
                in_range = [c for c in _cited_for_metric(low, patterns) if lo * true_val <= c <= hi * true_val and c > 0]
            if not in_range:
                continue
            # If the narrative cites the canonical value ANYWHERE (even inside a trend
            # — "recovery climbed from 86 to 30"), the coach is grounded on it: a
            # historical/trend reference to an off-value is not a contradiction. Only
            # flag when NO cited value (and no bare mention) lands on the canonical.
            if any(abs(c - true_val) <= band for c in in_range) or _mentions_value(low, true_val):
                continue
            off = min(in_range, key=lambda c: abs(c - true_val))
            offenders.append(f"{label}: cited {off:g} for '{key}' but canonical is {true_val:g} (no grounded value cited)")
    f.value = float(len(offenders))
    if offenders:
        f.status = ALARM if len(offenders) >= 2 else WARN
        f.offenders = offenders
        f.detail = "; ".join(offenders[:5])
    else:
        f.detail = "served narratives agree with the canonical facts"
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 4 — Endpoint contract / non-degenerate shape
#   The handle_predictions bug returned a valid-looking 200 with everything
#   zeroed (read the wrong DDB field). Liveness checks see 200 and pass. This
#   asserts required keys/types AND that the payload isn't degenerate (e.g. ALL
#   of a set of aggregate paths are zero/null when they shouldn't be).
#   spec: {required: [paths], non_degenerate: [paths]} — non_degenerate fires if
#   EVERY listed path is zero/null/empty.
#
#   BUG-05 (#379): a manual experiment reset (ADR-077) deliberately wipes cycle-
#   scoped data, so for the first few days of a new cycle "everything is zero"
#   is CORRECT, not a bug — indistinguishable from the handle_predictions outage
#   by shape alone. `experiment_age_days` (days since EXPERIMENT_START_DATE,
#   pure — the caller derives it from the clock) gates ONLY the non_degenerate
#   assertion during that grace window; a genuinely `required` key going missing
#   is never legitimate, reset or not, so that check always runs at full
#   strength.
# ─────────────────────────────────────────────────────────────────────────────
POST_RESET_GRACE_DAYS = 5


def _dig(payload, path):
    cur = payload
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
    return cur


def _is_blank(v) -> bool:
    return v is None or v == 0 or v == 0.0 or v == "" or v == [] or v == {}


def check_endpoint_shape(name, payload, spec, *, experiment_age_days=None) -> Finding:
    """`experiment_age_days`: days since EXPERIMENT_START_DATE, or None if the
    caller couldn't determine it (falls back to the original, ungated behavior)."""
    f = Finding(f"endpoint_shape:{name}", value=0.0)
    problems = []
    if not isinstance(payload, dict):
        f.status = ALARM
        f.value = 1.0
        f.detail = f"{name}: payload not an object"
        return f
    for path in spec.get("required", []):
        if _dig(payload, path) is None:
            problems.append(f"missing {path}")
    in_grace = experiment_age_days is not None and 0 <= experiment_age_days < POST_RESET_GRACE_DAYS
    nd = spec.get("non_degenerate", [])
    degenerate = bool(nd) and all(_is_blank(_dig(payload, p)) for p in nd)
    if degenerate and not in_grace:
        problems.append(f"all of {nd} are blank/zero (degenerate payload)")
    f.value = float(len(problems))
    if problems:
        f.status = ALARM
        f.offenders = problems
        f.detail = f"{name}: " + "; ".join(problems[:4])
    elif degenerate and in_grace:
        f.detail = f"{name}: shape ok (post-reset day {experiment_age_days}, empty board expected)"
    else:
        f.detail = f"{name}: shape ok"
    return f


# ─────────────────────────────────────────────────────────────────────────────
# Invariant 5 — Cross-surface count agreement
#   The arc-7-vs-3 bug: the experiment arc counted weeks differently from the
#   week list the UI renders. Two surfaces describing the same set must agree on
#   its size. Input: list of {name, a, b} — a mismatch is the bug.
# ─────────────────────────────────────────────────────────────────────────────
def check_count_agreement(pairs) -> Finding:
    f = Finding("count_agreement", value=0.0)
    offenders = []
    for p in pairs:
        a, b = p.get("a"), p.get("b")
        if a is None or b is None:
            continue
        if int(a) != int(b):
            offenders.append(f"{p['name']}: {a} vs {b}")
    f.value = float(len(offenders))
    if offenders:
        f.status = ALARM
        f.offenders = offenders
        f.detail = "; ".join(offenders[:5])
    else:
        f.detail = "cross-surface counts agree"
    return f


def check_experiment_continuity(genesis: str, today: str, surfaced_weeks) -> Finding:
    """SS-05 — the experiment runs CONTINUOUSLY (a reset is an explicit, manual
    `restart_pipeline.py` act, never automated), so week/day counters legitimately
    grow without bound. What is NOT legitimate is a counter that DISAGREES with the
    genesis date: a surfaced week far ABOVE the one the genesis date implies is the
    ADR-077 reset signature (stale pre-reset high-week posts leaking back into
    selection — the "arc counts 7 weeks vs the 3 the UI shows" class), and a
    genesis-derived week below 1 means a misconfigured/future genesis — except
    inside the sanctioned pre-start countdown window (#931/#942): genesis up to
    PRE_START_GRACE_DAYS in the future reports PRE_START (OK-severity note),
    anything further stays ALARM.

    Pure (no clock): the caller passes `genesis` and `today` as 'YYYY-MM-DD' and
    `surfaced_weeks` as a list of {name, week} actually shown to readers (latest
    chronicle week, experiment-arc week_count, …). Verifies each is within the band
    [1, derived_week + tolerance]. ALARM on a genesis underflow or a week wildly
    above the derived value; WARN on a small over-count.
    """
    import datetime as _dt

    f = Finding("experiment_continuity", value=0.0)
    try:
        g = _dt.date.fromisoformat(genesis[:10])
        t = _dt.date.fromisoformat(today[:10])
    except Exception:
        f.detail = "could not parse genesis/today — skipped"
        return f
    derived_week = ((t - g).days // 7) + 1
    f.value = float(derived_week)
    if derived_week < 1:
        # #942: a future genesis within the sanctioned pre-start countdown window
        # (#931/#939 — restart_pipeline stages Day 1 a few days out) is expected,
        # not the mis-set-constant failure. Bounded grace: ≤ PRE_START_GRACE_DAYS
        # in the future → pre_start (OK-severity, distinct note); beyond that a
        # far-future genesis is still the real bad-constant ALARM.
        days_until = (g - t).days
        if 0 < days_until <= PRE_START_GRACE_DAYS:
            f.status = PRE_START
            f.detail = f"pre_start: genesis {genesis} is {days_until} day(s) ahead of today {today} — sanctioned countdown window (#931)"
        else:
            f.status = ALARM
            f.detail = (
                f"genesis {genesis} is {days_until} days after today {today} (> {PRE_START_GRACE_DAYS}-day pre-start grace) "
                f"→ derived week {derived_week} (<1): counter underflow / bad genesis"
            )
        return f

    tolerance = 1  # a current-week post can be one ahead of the strict genesis math at a week boundary
    offenders = []
    for s in surfaced_weeks or []:
        wk = s.get("week")
        if wk is None:
            continue
        try:
            wk = int(wk)
        except (TypeError, ValueError):
            continue
        if wk < 1:
            offenders.append(f"{s.get('name', 'week')}={wk} (<1)")
        elif wk > derived_week + tolerance:
            offenders.append(f"{s.get('name', 'week')}={wk} (genesis implies ~{derived_week})")
    if offenders:
        # A week far above derived is the stale-pre-reset leak (ADR-077); a small
        # over-count is more likely a boundary/timezone artifact → WARN unless egregious.
        egregious = any("(<1)" in o for o in offenders) or any(
            int(s.get("week", 0) or 0) > derived_week + 2 for s in surfaced_weeks or [] if str(s.get("week", "")).lstrip("-").isdigit()
        )
        f.status = ALARM if egregious else WARN
        f.offenders = offenders
        f.detail = "experiment counter disagrees with genesis: " + "; ".join(offenders[:5])
    else:
        f.detail = f"continuous experiment coherent at ~week {derived_week} (genesis {genesis})"
    return f


def overall_status(findings) -> str:
    """Worst severity across a set of findings."""
    worst = OK
    for f in findings:
        if _RANK[f.status] > _RANK[worst]:
            worst = f.status
    return worst
