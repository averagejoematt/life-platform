"""#3829 — the ensemble digest's success line, and the ceiling that was sized while it was dark.

THE INCIDENT. `coach-ensemble-digest` logged

    Ensemble digest produced — 7 summaries, 6 disagreements, 5 unanimous flags

at 17:15:12 on 2026-09-15, then died at its 90s ceiling. `ENSEMBLE#digest` has no
`CYCLE#2026-09-15` row. The function has a SECOND, separate success line for the
write (`Wrote ensemble digest for CYCLE#…`, in `_write_digest` after `_put_item`
returns) and it never appeared — so the missing row is not an inference, it is the
absence of the line that would have claimed it.

THE CAUSE, AND WHY IT IS NOT "DURATION CREPT". Over eight days it looks like a
creep. Over thirty it is a step function with a date:

    2026-08-15..08-30   n=16   median   1,326 ms
    2026-08-31..09-14   n=15   median  62,279 ms      47x, overnight

and no commit touched the module in that window. `budget_guard` pauses this
feature at tier >= 1 (`"ensemble": 1`), and SSM `/life-platform/budget-tier` sat
at 1 or 2 from 2026-08-05 until **17:00:12 on 2026-08-31**. The daily cron fires
at 17:00. For most of August the function was not fast — it was NOT DOING THE
WORK, returning the deterministic fallback in ~1.3s. The 90s ceiling was sized
against that idle cost, where it read as 68x headroom.

That is the shape worth guarding: an instrument that looks healthy because the
thing it measures was never running (cf. #1927's two AI gates dark 26 of 30 days
while reporting green, and #3413's 10s cap sitting below its callee's median).

WHAT THESE TESTS CAN AND CANNOT DO. They are static assertions over source and
CDK config — they cannot observe a live timeout. What they CAN hold is the
property that made the incident silent: that no line claims persistence before
`_put_item` returns, and that the ceiling is not quietly walked back to a value
derived from the dark window.
"""

import os
import re

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIGEST = os.path.join(_REPO, "lambdas", "coach", "coach_ensemble_digest.py")
_COMPUTE = os.path.join(_REPO, "cdk", "stacks", "compute_stack.py")
_GUARD = os.path.join(_REPO, "lambdas", "ai", "budget_guard.py")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


# ══════════════════════════════════════════════════════════════════════════════
# The success line may not claim what it does not know
# ══════════════════════════════════════════════════════════════════════════════


def test_the_produced_line_does_not_claim_storage():
    """`produced` is true and is not an outcome. It must say so in the line itself.

    The incident's whole silence lived here: a reader scanning the log saw a
    success sentence and no contradicting line, because the line that WOULD have
    contradicted it is only emitted on the happy path.
    """
    src = _read(_DIGEST)
    m = re.search(r'"Ensemble digest produced[^"]*"(?:\s*\n\s*"[^"]*")*', src)
    assert m, "the 'Ensemble digest produced' log line has moved or been renamed — re-point this test"
    line = m.group(0)
    assert "stored=pending" in line, (
        "the produced-line must carry `stored=pending`. Without it the sentence reads as an outcome, "
        "which is exactly how a 90s timeout between produce and write went unnoticed (#3829)."
    )


def test_only_the_write_path_claims_persistence():
    """`Wrote ensemble digest` must live inside `_write_digest`, after `_put_item`.

    If that claim ever migrates to a caller — or gets emitted before the put — the
    log regains the ability to assert a row that does not exist.
    """
    src = _read(_DIGEST)
    assert src.count('"Wrote ensemble digest for CYCLE#%s') == 1, "the write's success line is no longer unique"

    fn = src.split("def _write_digest(")[1].split("\ndef ")[0]
    assert "Wrote ensemble digest" in fn, "the write's success line left _write_digest — a caller cannot know the put succeeded"
    put_at = fn.index("_put_item(item)")
    log_at = fn.index("Wrote ensemble digest")
    assert put_at < log_at, "the write is claimed BEFORE _put_item returns — the claim must follow the call"
    assert re.search(r"if\s+success\s*:", fn), "the write's success line is no longer guarded by the put's return value"


def test_the_gap_between_produce_and_write_is_timed():
    """Nothing between the two success lines emitted a timestamp, which is why the
    timeout could not be attributed without reading the source. The grounding gate
    — one corrective regen, i.e. a SECOND Bedrock call — is the expensive step in
    that gap and is now measured."""
    src = _read(_DIGEST)
    assert "Grounding gate finished in" in src, "the grounding gate is untimed again — the produce→write gap goes dark"
    # `index` would match the `def _apply_grounding_gate(...)` line, which contains the
    # same substring — find the CALL site (the assignment), not the definition.
    gate_call = src.index("digest, adr104_findings = _apply_grounding_gate(")
    timer = src.rindex("_t_gate = time.monotonic()", 0, gate_call)
    assert timer < gate_call, "the gate's timer must start before the call it measures"


def test_every_elapsed_figure_shares_one_clock():
    """A per-line clock would make two elapsed figures incomparable."""
    src = _read(_DIGEST)
    assert "_t_start = time.monotonic()" in src
    assert src.count("_t_start = time.monotonic()") == 1, "more than one invocation clock — elapsed figures stop being comparable"


# ══════════════════════════════════════════════════════════════════════════════
# The ceiling, and the reason it may not be walked back
# ══════════════════════════════════════════════════════════════════════════════


def _ensemble_block():
    src = _read(_COMPUTE)
    i = src.index('function_name="coach-ensemble-digest"')
    return src[src.rindex("create_platform_lambda(", 0, i) : src.index("create_platform_lambda(", i)]


def test_the_ceiling_is_above_the_measured_working_median():
    """90s sat at ~1.4x the post-08-31 median (62.3s) and was breached on 3 of the
    last 4 cycles. Anything at or near that is the same defect returning."""
    block = _ensemble_block()
    m = re.search(r"timeout_seconds=(\d+)", block)
    assert m, "coach-ensemble-digest no longer declares timeout_seconds"
    secs = int(m.group(1))
    assert secs >= 180, (
        f"timeout_seconds={secs} is at or near the ceiling that failed. The measured median on the "
        "WORKING window (post-2026-08-31) is 62.3s and the distribution is censored at the old 90s "
        "bound, so the true tail is unknown — a value in that range is guessing against a number "
        "nobody has (#3829)."
    )


def test_the_ceiling_carries_its_measurement_and_its_censoring():
    """A raised timeout with no recorded reasoning is indistinguishable from someone
    rounding up until the red stopped. The comment must carry BOTH the step-change
    evidence and the admission that this is not a derived percentile."""
    block = _ensemble_block()
    assert "#3829" in block, "the ceiling change cites no issue"
    assert "budget" in block.lower() or "tier" in block.lower(), (
        "the comment must name WHY the old ceiling looked generous — the feature was budget-paused, "
        "so 90s was sized against an idle cost, not against the work"
    )
    # Deliberately NOT a bare `"censor" in ...`: the comment also says it wants to
    # "UNCENSOR the measurement", and that substring alone kept this assertion green
    # when the mutation run stripped the actual claim. Require the claim.
    low = block.lower()
    assert "distribution is censored" in low or "is censored at" in low, (
        "the comment must STATE that the post-08-31 distribution is censored at the old ceiling — not "
        "merely mention censoring in passing. Recording 300s as a derived p95 over a censored sample "
        "would be a fabricated statistic (ADR-105)."
    )
    assert "not" in low and "p95" in low, "the comment must disclaim 300s as a derived percentile, in words"


def test_the_feature_is_still_budget_paused_at_tier_one():
    """The whole causal story rests on this one registry line. If the ensemble ever
    stops being tier-gated, the dark-window explanation above stops being true and
    this test file's reasoning needs re-reading rather than trusting."""
    guard = _read(_GUARD)
    m = re.search(r'"ensemble"\s*:\s*(\d+)', guard)
    assert m, "budget_guard no longer registers `ensemble` — #3829's cause analysis rests on this line"
    assert int(m.group(1)) == 1, (
        f"`ensemble` is now gated at tier {m.group(1)}, not 1. The 2026-08-31 step change was the tier "
        "dropping to 0 and un-pausing this feature; if the threshold moved, re-derive rather than assume."
    )


@pytest.mark.parametrize("marker", ["47x", "62,279", "1,326"])
def test_the_step_change_evidence_survives_in_the_source(marker):
    """The numbers that justify the raise live next to it, not only in an issue.

    An operator reading `timeout_seconds=300` in two years should be able to see
    why without a GitHub round-trip — the same reason the census lineage notes
    carry their own measurements.
    """
    assert marker in _ensemble_block(), f"the ceiling's evidence lost {marker!r} — the raise stops being auditable in-tree"
