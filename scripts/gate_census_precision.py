"""scripts/gate_census_precision.py — the census's OWN error bars (#2639).

Split from `gate_census.py` by the module-size ratchet (the 1200-line hard ceiling,
#1665) — same public entrypoint, `gate_census` re-exports everything here, so both the
CLI report and the tests keep addressing `gate_census.*`.

A risk flag from `gate_census._static_source_flags` is a SYNTACTIC lead, not a verdict —
this module carries the hand-adjudicated false-positive rate on the two flags large
enough that the report used to call them "unmeasured", and renders the KNOWN ERROR
section that states n as a floor in both directions. Same idiom as `Proof.proved_on`:
`sampled_on` is an ISO date so a stale sample is visible as stale, and `n_flagged` is
the flag's population AT SAMPLE TIME so `_render_error_bars` can compare it to the live
count and say so if they drift, rather than silently trusting a number that no longer
matches the source.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
from typing import Any


@dataclass(frozen=True)
class FlagPrecisionSample:
    """One hand-adjudicated sample of a risk flag's false-positive rate."""

    n_flagged: int  # the flag's total population when the sample was drawn
    n_sampled: int
    n_fp: int
    n_tp: int
    method: str
    sampled_on: str  # ISO date, so a stale sample is visible as stale


FLAG_PRECISION: dict[str, FlagPrecisionSample] = {
    # 13-of-38 and 10-of-27, deterministic every-3rd sample, adjudicated against
    # gate_census's own flag definitions (`_static_source_flags`) rather than judgement
    # calls. Three of the sampled hits were real true positives (#2639's third comment):
    # deploy/config_mirror_audit.py and tests/test_csp_native_embeds_1678.py
    # (vacuous-empty), scripts/check_deploy_wedge.py (exempt-by-incompleteness).
    "vacuous-empty": FlagPrecisionSample(
        n_flagged=38,
        n_sampled=13,
        n_fp=11,
        n_tp=2,
        method="deterministic every-3rd sample, adjudicated against _static_source_flags",
        sampled_on="2026-08-16",
    ),
    "exempt-by-incompleteness": FlagPrecisionSample(
        n_flagged=27,
        n_sampled=10,
        n_fp=9,
        n_tp=1,
        method="deterministic every-3rd sample, adjudicated against _static_source_flags",
        sampled_on="2026-08-16",
    ),
}


def _wilson_interval(k: int, n: int, z: float = 1.959963985) -> tuple[float, float]:
    """95% Wilson score interval for `k` successes of `n` trials. No scipy (stdlib-only
    repo) — verified against the #2639 sample's own hand-computed table: (11, 13) ->
    0.578-0.957, (9, 10) -> 0.596-0.982."""
    phi = k / n
    denom = 1 + z**2 / n
    center = (phi + z**2 / (2 * n)) / denom
    margin = z * sqrt(phi * (1 - phi) / n + z**2 / (4 * n**2)) / denom
    return center - margin, center + margin


def _live_flag_count(census: dict[str, Any], flag: str) -> int:
    """How many gates carry `flag` in the census RIGHT NOW, for comparison against the
    recorded sample's `n_flagged` — a drift check, not a re-sample."""
    return sum(1 for g in census.get("gates") or [] if flag in (g.get("risk_flags") or []))


def _render_error_bars(census: dict[str, Any]) -> str:
    """#2639: n is a FLOOR. Print the census's own known error, in both directions.

    A census with a silent blind spot answers a different question than the one it appears
    to answer — the exact defect class #2578 exists to hunt, and it was present in the
    instrument. So the report now states, every run:

      * how many CI gates only ONE of the two detectors caught (the false-negative the
        verb-only detector was carrying, measured rather than sampled),
      * how many steps remain classified non-gate and are therefore UNADJUDICATED,
      * the measured false-positive rate on the two large risk flags (box 3), with a
        Wilson interval and a note if the live population has drifted from the sample.

    Numbers, not adjectives. `steps_nongate` is the residual a human still has to read;
    printing its size is what turns "we might be missing some" into a bounded claim.
    """
    ci = (census.get("counters") or {}).get("ci") or {}
    if not ci:
        return "-- KNOWN ERROR ----\n  CI counters absent (family not swept) — no error bars computable."
    residual = ci.get("steps_nongate", 0)
    only_enforce = ci.get("by_enforcement_only", 0)
    total_ci = ci.get("by_verb_only", 0) + only_enforce + ci.get("by_both", 0)
    out = [
        "-- KNOWN ERROR — n is a FLOOR, in both directions (#2639) ---------------------",
        f"  FALSE NEGATIVES (measured): {only_enforce} of {total_ci} CI gates are detected ONLY by their",
        "    explicit non-zero exit, not by any tool verb. Before the derivation was widened these",
        "    were counted as non-gates, so every prior n and every coverage % was under-measured.",
        f"  UNADJUDICATED: {residual} workflow steps remain classified non-gate. Nobody has read them,",
        "    so the true count is >= n, never = n. `--json` carries `counters.ci.nongate_sample`",
        "    with every one of their labels — the list exists so the residual can be worked, not",
        "    asserted away.",
        "  FALSE POSITIVES (sampled): every risk flag is a SYNTACTIC lead, and two are now",
        "    hand-adjudicated rather than anecdotal — deterministic every-3rd sample, read against",
        "    this module's own flag definitions:",
    ]
    for flag, sample in FLAG_PRECISION.items():
        lo, hi = _wilson_interval(sample.n_fp, sample.n_sampled)
        proportion = sample.n_fp / sample.n_sampled
        out.append(
            f"      {flag:<24} {sample.n_fp}/{sample.n_sampled} sampled were FP "
            f"({proportion:.0%}, 95% CI {lo:.0%}-{hi:.0%}) of {sample.n_flagged} flagged on {sample.sampled_on}"
        )
        live = _live_flag_count(census, flag)
        if live != sample.n_flagged:
            out.append(
                f"        DRIFT: sample recorded n_flagged={sample.n_flagged}; live count is now "
                f"{live} — the sample may be stale, re-sample before trusting this interval."
            )
    out.append("    Both intervals are wide and both point the same way: MOST flags on these two are")
    out.append("    noise, not all — three sampled hits were real (see FLAG_PRECISION comment). Treat")
    out.append("    flag counts as upper bounds on true defects, not defect counts themselves.")
    return "\n".join(out)
