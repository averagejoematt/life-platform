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


# ─────────────────────────────────────────────────────────────────────────────
# RE-SAMPLED 2026-08-27 (#2999, epic #2578 slice 2). The 2026-08-16 sample was drawn at
# n_flagged 38 / 27; the populations had grown to 54 / 40 and `_render_error_bars` had
# been printing its own DRIFT warning for eleven days. #2999's second acceptance box is
# exactly that: "the risk-flag ranking rests on a live interval". Same deterministic
# every-3rd draw over the id-sorted flagged list, so the sample is reproducible from the
# census output rather than from a stored list of names.
#
# THE ADJUDICATION RULE, WRITTEN DOWN SO THE NEXT SAMPLE MEANS THE SAME THING
# ---------------------------------------------------------------------------
# The prior sample recorded "adjudicated against _static_source_flags" and no rule, which
# makes a second sample incomparable to the first. The rule used here, stated once:
#
#   vacuous-empty is a TRUE POSITIVE when the file contains NO assertion that would red
#   if the population its empty-assert is drawn from went to zero — i.e. the derivation
#   can silently return nothing and the gate still passes. It is a FALSE POSITIVE when
#   (a) the file asserts a population floor in any form (`assert names,`, `assert
#   len(X) > n`, a raise on a failed parse, a synthetic-positive test that reds when the
#   detector breaks), or (b) the flagged assertion is on a SYNTHETIC or monkeypatched
#   input where empty is the asserted meaning, not a derived population.
#
#   exempt-by-incompleteness is a TRUE POSITIVE when the `if not X: continue/return`
#   skip is satisfied by the very defect the check exists to catch, and no other path
#   reports it. It is a FALSE POSITIVE when X's absence genuinely means not-applicable,
#   when the skip fails CLOSED (stricter, not looser), or when a second path reports the
#   skipped case.
#
# The four vacuous-empty true positives found this round:
#   scripts/check_api_before_frontend.py   MEASURED, not reasoned: extract_declared_routes
#     walks for `ast.Assign` only, so annotating the route table (`ROUTES: dict[str, Any]
#     = {...}` — the exact 2026-08-13 shape this flag generalises) returns set(). Run
#     `extract_declared_routes` over both forms: `{'/api/new'}` vs `set()`. The function's
#     own docstring declares the empty return normal ("a brand-new file or a base ref
#     where the file didn't exist yet both look like 'no routes'"), so nothing downstream
#     can tell the two apart, and the gate reports "no new routes — pass".
#   tests/test_hevy_compiler_isolation.py  one test, one os.walk, no floor and no
#     synthetic positive; a grown _SKIP_DIRS empties the sweep and it stays green.
#   tests/test_lambdas_packaging_guard.py  all three assertions read `git ls-files
#     lambdas`; an empty listing passes all three.
#   tests/test_no_dead_intelligence_functions.py  the lambdas/+mcp/ walk has no floor.
#
# The three exempt-by-incompleteness true positives:
#   deploy/config_mirror_audit.py          `if not consumers: continue` — a broken
#     readers_of() skips every key and the audit reports clean. (Also a TP in the
#     2026-08-16 sample; the only item adjudicated twice, and it held.)
#   scripts/check_api_before_frontend.py   `if not source: return set()` — an unparsable
#     head source reads as "no new routes". Same file, both flags, different arms.
#   tests/test_pacific_today_guard_2414.py `if not value_has_now: continue` — the matcher
#     asks "is there a clock here?", so a Pacific `DATE#` anchored at UTC midnight has no
#     clock and is skipped. That is not hypothetical: it is the live defect #3196
#     introduced and #2817 found (memory: strptime is the INVERSE of a clock).
#
# Both flags moved toward each other and neither interval moved much: the headline
# reading is unchanged — most flags on these two are noise — but it now rests on 32
# adjudications at the live population instead of 23 at a stale one.
FLAG_PRECISION: dict[str, FlagPrecisionSample] = {
    "vacuous-empty": FlagPrecisionSample(
        n_flagged=54,
        n_sampled=18,
        n_fp=14,
        n_tp=4,
        method="deterministic every-3rd sample over the id-sorted flagged list, adjudicated against the rule above",
        sampled_on="2026-08-27",
    ),
    "exempt-by-incompleteness": FlagPrecisionSample(
        n_flagged=40,
        n_sampled=14,
        n_fp=11,
        n_tp=3,
        method="deterministic every-3rd sample over the id-sorted flagged list, adjudicated against the rule above",
        sampled_on="2026-08-27",
    ),
}

# The superseded 2026-08-16 draw, kept so a reader can see whether the estimate moved
# rather than only what it is now. 11/13 (85%) and 9/10 (90%) at n_flagged 38 / 27.
PRIOR_FLAG_PRECISION: dict[str, FlagPrecisionSample] = {
    "vacuous-empty": FlagPrecisionSample(
        n_flagged=38,
        n_sampled=13,
        n_fp=11,
        n_tp=2,
        method="deterministic every-3rd sample, adjudicated against _static_source_flags (#2639)",
        sampled_on="2026-08-16",
    ),
    "exempt-by-incompleteness": FlagPrecisionSample(
        n_flagged=27,
        n_sampled=10,
        n_fp=9,
        n_tp=1,
        method="deterministic every-3rd sample, adjudicated against _static_source_flags (#2639)",
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
        prior = PRIOR_FLAG_PRECISION.get(flag)
        if prior:
            plo, phi = _wilson_interval(prior.n_fp, prior.n_sampled)
            out.append(
                f"        prior draw {prior.sampled_on}: {prior.n_fp}/{prior.n_sampled} "
                f"({prior.n_fp / prior.n_sampled:.0%}, CI {plo:.0%}-{phi:.0%}) of {prior.n_flagged} flagged "
                "— printed so a reader sees whether the estimate MOVED, not only where it is"
            )
        live = _live_flag_count(census, flag)
        if live != sample.n_flagged:
            out.append(
                f"        DRIFT: sample recorded n_flagged={sample.n_flagged}; live count is now "
                f"{live} — the sample may be stale, re-sample before trusting this interval."
            )
    n_tp = sum(s.n_tp for s in FLAG_PRECISION.values())
    n_sampled = sum(s.n_sampled for s in FLAG_PRECISION.values())
    out.append("    Both intervals are wide and both point the same way: MOST flags on these two are")
    out.append(f"    noise, not all — {n_tp} of the {n_sampled} sampled were real (named in the FLAG_PRECISION")
    out.append("    comment, one of them measured rather than reasoned).")
    # Kept on ONE line: `tests/test_gate_census_error_bars_2639.py` asserts the phrase
    # "upper bound" survives, and a soft-wrap that splits it passes nothing and reds it.
    out.append("    Treat flag counts as an upper bound on true defects, not as defect counts.")
    return "\n".join(out)
