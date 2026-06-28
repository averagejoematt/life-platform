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
WARN = "warn"
ALARM = "alarm"
_RANK = {OK: 0, WARN: 1, ALARM: 2}


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
_FACT_PATTERNS = {
    "recovery_pct": ([r"recovery[^.\d]{0,14}(\d{1,3}(?:\.\d+)?)\s*%?", r"(\d{1,3}(?:\.\d+)?)\s*%\s*recovery"], 0.20),
    # HRV value must carry the ms unit to count (the bpm form is the unit-error check below).
    "hrv_ms": ([r"hrv[^.\d]{0,14}(\d{1,3}(?:\.\d+)?)\s*ms", r"(\d{1,3}(?:\.\d+)?)\s*ms[^.]{0,14}hrv"], 0.25),
    "rhr_bpm": ([r"(?:resting heart rate|resting hr|rhr)[^.\d]{0,14}(\d{2,3})", r"(\d{2,3})\s*bpm[^.]{0,18}rest"], 0.20),
    # Weight requires an explicit lb/lbs/pounds unit so a "190 g protein" can't match.
    "latest_weight": ([r"(\d{2,3}(?:\.\d+)?)\s*(?:lbs|lb|pounds)\b"], 0.04),
}


def _cited_for_metric(low_text: str, patterns):
    out = []
    for pat in patterns:
        for m in re.finditer(pat, low_text):
            try:
                out.append(float(m.group(1)))
            except (ValueError, IndexError):
                pass
    return out


def check_facts_agreement(narratives, facts, *, surfaces=None) -> Finding:
    """`narratives`: list of served text blobs. `facts`: the canonical dict
    ({recovery_pct, hrv_ms, rhr_bpm, latest_weight}). Flags a cited number that
    contradicts a fact by > its tolerance, and HRV quoted in bpm."""
    f = Finding("facts_agreement", value=0.0)
    offenders = []
    labels = surfaces or [f"narrative_{i}" for i in range(len(narratives))]
    for text, label in zip(narratives, labels):
        if not text:
            continue
        low = text.lower()
        # HRV-unit error: HRV tied to a bpm reading (HRV is milliseconds).
        if re.search(r"hrv[^.]{0,30}\bbpm\b", low) or re.search(r"\bbpm\b[^.]{0,12}hrv", low):
            offenders.append(f"{label}: HRV cited in bpm (HRV is milliseconds)")
        for key, (patterns, tol) in _FACT_PATTERNS.items():
            true_val = facts.get(key)
            if true_val in (None, 0):
                continue
            true_val = float(true_val)
            band = abs(true_val) * tol
            for cited in _cited_for_metric(low, patterns):
                if cited > 0 and abs(cited - true_val) > band:
                    offenders.append(f"{label}: cited {cited:g} for '{key}' but canonical is {true_val:g}")
                    break
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
# ─────────────────────────────────────────────────────────────────────────────
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


def check_endpoint_shape(name, payload, spec) -> Finding:
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
    nd = spec.get("non_degenerate", [])
    if nd and all(_is_blank(_dig(payload, p)) for p in nd):
        problems.append(f"all of {nd} are blank/zero (degenerate payload)")
    f.value = float(len(problems))
    if problems:
        f.status = ALARM
        f.offenders = problems
        f.detail = f"{name}: " + "; ".join(problems[:4])
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


def overall_status(findings) -> str:
    """Worst severity across a set of findings."""
    worst = OK
    for f in findings:
        if _RANK[f.status] > _RANK[worst]:
            worst = f.status
    return worst
