#!/usr/bin/env python3
"""restart_cost_model.py — what ONE reset costs, measured (#3601 box 1).

WHY THIS EXISTS. `docs/PROPORTIONALITY.md` priced the reset MACHINERY (the taxonomy,
the pipeline, the doc-gate sweep) and never priced the reset EVENT. Every
reset-machinery demote trigger in that ledger is therefore judged against a cadence
(corrected to ~9.2/quarter by #3601's first cut) multiplied by a price nobody had ever
measured. This module is that price, and it is derived the way ADR-105 requires: from
the platform's own cost instrument (`LifePlatform/AI::EstimatedCostUSD`, the
`bedrock_client` chokepoint's self-metering) with n and a window stated on every number,
never from a plausible-sounding guess.

THE METHOD — a MARGINAL delta, not a day total. A reset day's total AI spend is
dominated by the attended session that ran the reset; charging that to the reset would
price the operator, not the event. So each component is measured as
`median(reset-day value) - median(non-reset-day value)` on the ONE function dimension
the reset actually drives, over the window below.

WHAT THE MEASUREMENT FOUND, and where it contradicted the issue. #3601 assumed the
price was "visual-qa full pass + truth pass + CDK deploys with vision QA". Measured:

  * `visual-ai-qa` IS the dominant cash line (+$0.24 median on a reset day).
  * `reader-truth-qa` shows **no** marginal at all (-$0.02 median — i.e. inside the
    day-to-day band): the reset commit does not buy an extra truth pass, the daily cron
    already paid for it. Recorded as a measured ZERO rather than dropped, because a
    component someone expected and measurement refutes is a finding.
  * `character-sheet-compute`, `og-image-generator`, `site-stats-refresh` and
    `chronicle-podcast` — the other four lambdas the reset invokes — have **no
    `EstimatedCostUSD` series at all** (checked against `list_metrics` for the whole
    namespace, 2026-09-20): they make zero Bedrock calls. The character rebuild, the
    single loudest-looking step of the reset, is deterministic and free.

PRECISION, STATED HONESTLY (ADR-105). n=4 reset days, and two of those four
(2026-09-04/05) are the mis-dated pair and 09-05/09-06 are back-to-back, so a
86,400-second period smears adjacent resets into each other. This number is an
ORDER-OF-MAGNITUDE claim — a reset costs tens of cents, not tens of dollars — and the
`high_usd` column, not the median, is the one to plan against. `measure_marginal()`
below re-derives all of it from live CloudWatch (read-only) so a successor never has to
trust the frozen literals.

THE POINT OF THE ROW, which the dollars understate: at ~9.2 resets/quarter the cash
price of the reset cadence is a few dollars a quarter. The cost is NOT the money — it is
the attended operator session and the defect surface (39 of the 99 confirmed findings in
`docs/reviews/FULLREVIEW_2026-09-05.md` live in the reset -> first-cron window). Those
are carried here as `NON_CASH_COSTS` so the price can never be read as the whole cost.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass

# ── The measurement's provenance ─────────────────────────────────────────────
MEASURED_AT = _dt.date(2026, 9, 20)
MEASUREMENT_WINDOW = ("2026-08-19", "2026-09-18")
# The days `restart_pipeline.py --apply` actually RAN in that window (docs/restart/
# RESET_LOG.md's report column, plus the 09-05 re-anchor that was corrected in place and
# so has no RESET_LOG line of its own). NOT the genesis dates: a future-dated genesis is
# sanctioned (#931/#939), and the spend lands on the day the pipeline ran.
RESET_RUN_DAYS = ("2026-09-01", "2026-09-04", "2026-09-05", "2026-09-06")
METRIC_NAMESPACE = "LifePlatform/AI"
METRIC_NAME = "EstimatedCostUSD"
# A frozen measurement is a fact with a shelf life. Past this many days the close prints
# it as STALE and says to re-run `measure_marginal()` — the alternative is a number that
# quietly becomes folklore, which is the failure mode row 86's "a few times a quarter"
# already demonstrated once.
STALE_AFTER_DAYS = 120

BASIS_MEASURED = "measured"  # from the platform's own cost instrument, with n
BASIS_REGISTRY = "registry-priced"  # computed from lambdas/ai/bedrock_client.PRICES
BASIS_BOUNDED = "bounded-estimate"  # an UPPER bound, stated as an estimate, never a point claim
BASIS_KINDS = (BASIS_MEASURED, BASIS_REGISTRY, BASIS_BOUNDED)


@dataclass(frozen=True)
class Component:
    """One priced line of a reset. `usd` is the planning figure, `high_usd` the worst
    observed/bounded case. `basis` and `source` are mandatory: a dollar figure in this
    repo without a stated derivation is the thing #3601 was filed about."""

    name: str
    mechanism: str
    basis: str
    usd: float
    high_usd: float
    n: str
    source: str


RESET_COST_COMPONENTS = (
    Component(
        name="visual-ai-qa passes on the reset commit",
        mechanism="the reset commit touches site/** -> site-deploy -> the gating Bedrock vision sweep (ADR-076 layer 3)",
        basis=BASIS_MEASURED,
        usd=0.239,
        high_usd=0.757,
        n="n=4 reset days vs 14 baseline days",
        source="LifePlatform/AI::EstimatedCostUSD{LambdaFunction=visual-ai-qa}, median reset-day minus median baseline-day",
    ),
    Component(
        name="daily-brief regen invocation",
        mechanism="restart_site_copy_sync's REGEN_LAMBDAS step invokes daily-brief {dry_run: true} to rebuild public_stats/pulse",
        basis=BASIS_MEASURED,
        usd=0.032,
        high_usd=0.172,
        n="n=4 reset days vs 27 baseline days",
        source="LifePlatform/AI::EstimatedCostUSD{LambdaFunction=daily-brief}, median reset-day minus median baseline-day",
    ),
    Component(
        name="reader-truth-qa pass",
        mechanism="assumed by #3601 ('truth pass'); the daily cron already pays for it and the reset adds no run",
        basis=BASIS_MEASURED,
        usd=0.0,
        high_usd=0.0,
        n="n=4 reset days vs 19 baseline days; median delta -$0.023, i.e. inside the day-to-day band",
        source="LifePlatform/AI::EstimatedCostUSD{LambdaFunction=reader-truth-qa} — a measured ZERO, kept rather than dropped",
    ),
    Component(
        name="recall corpus re-embed (Titan v2)",
        mechanism="backfill_recall_embeddings --kinds chronicle, run as the recall_corpus_sync step (#2858)",
        basis=BASIS_REGISTRY,
        usd=0.004,
        high_usd=0.02,
        n="bound: <=1M input tokens for the chronicle corpus",
        source="lambdas/ai/bedrock_client.PRICES['titan']['in'] = $0.02/1M input tokens, input-only (#1384/#2883)",
    ),
    Component(
        name="deterministic reset compute (CDK deploy + the 4 non-AI regen lambdas)",
        mechanism="cdk deploy --all (CloudFormation + Lambda code updates are free), S3 asset PUTs, character-sheet-compute once per day since genesis",
        basis=BASIS_BOUNDED,
        usd=0.01,
        high_usd=0.05,
        n="no EstimatedCostUSD series exists for any of these four functions (list_metrics, whole namespace, 2026-09-20) — zero Bedrock calls",
        source="S3 PUT + Lambda GB-second list pricing; bounded, not metered — stated as an estimate",
    ),
)

# The part of the price that is not dollars. Carried in the same module deliberately:
# a reader who takes `total_usd()` as "what a reset costs" has the wrong number, and the
# only reliable fix is for the two to be impossible to read apart.
NON_CASH_COSTS = (
    "attended operator session — the pipeline is ~20 steps and attended end to end; no reset has ever run unwatched",
    "defect surface — 39 of the 99 confirmed findings in docs/reviews/FULLREVIEW_2026-09-05.md live in the reset -> first-cron window",
    "evidence — a cycle shorter than a pre-registered bet's horizon can never grade it; exactly 1 of the 11 cycles since 2026-07-12 could mature a 14-day bet (#3606 ruling 1)",
)


def validate() -> None:
    """Refuse a vacuous or unsourced model. Called by the tests and by `format_lines()`.

    The failure this exists for: a component list that parses empty, or a dollar figure
    with `basis=''`, would print as a confident `$0.00 per reset` — the exact shape of
    claim the honest-numbers standard (ADR-104) forbids.
    """
    if not RESET_COST_COMPONENTS:
        raise ValueError("RESET_COST_COMPONENTS is EMPTY — a model with no components is not a price of zero")
    for c in RESET_COST_COMPONENTS:
        if c.basis not in BASIS_KINDS:
            raise ValueError(f"component {c.name!r} has basis {c.basis!r}, not one of {BASIS_KINDS}")
        if not c.source.strip() or not c.n.strip():
            raise ValueError(f"component {c.name!r} states a dollar figure with no source/n — unsourced numbers do not ship (#3601)")
        if c.high_usd < c.usd:
            raise ValueError(f"component {c.name!r}: high_usd {c.high_usd} is below the planning figure {c.usd}")
    if not NON_CASH_COSTS:
        raise ValueError("NON_CASH_COSTS is EMPTY — the cash price alone misrepresents what a reset costs")


def total_usd() -> float:
    """The planning figure: sum of the per-component medians/bounds."""
    return round(sum(c.usd for c in RESET_COST_COMPONENTS), 4)


def high_usd() -> float:
    """The worst observed/bounded reset. Plan against this one, not the median."""
    return round(sum(c.high_usd for c in RESET_COST_COMPONENTS), 4)


def per_quarter_usd(resets_per_quarter: float) -> float:
    """Cash cost of a CADENCE, which is the number the proportionality ledger wants."""
    return round(total_usd() * float(resets_per_quarter), 2)


def is_stale(today: _dt.date | None = None) -> bool:
    today = today or _dt.date.today()
    return (today - MEASURED_AT).days > STALE_AFTER_DAYS


def format_lines(today: _dt.date | None = None) -> list[str]:
    """The block the monthly close prints. Pure — no AWS call, no I/O."""
    validate()
    out = [
        f"$/reset (model): ${total_usd():.2f} median, ${high_usd():.2f} worst observed "
        f"— measured {MEASURED_AT.isoformat()} over {MEASUREMENT_WINDOW[0]}..{MEASUREMENT_WINDOW[1]}, "
        f"n={len(RESET_RUN_DAYS)} reset runs"
    ]
    for c in RESET_COST_COMPONENTS:
        out.append(f"    ${c.usd:>6.3f}  (hi ${c.high_usd:.3f})  {c.name}  [{c.basis}; {c.n}]")
    out.append("  and the part that is not dollars:")
    out.extend(f"    - {t}" for t in NON_CASH_COSTS)
    if is_stale(today):
        out.append(
            f"    STALE — this model was measured {MEASURED_AT.isoformat()}, more than {STALE_AFTER_DAYS}d ago. "
            "Re-derive with restart_cost_model.measure_marginal() (read-only) before quoting it."
        )
    return out


# ── The live re-derivation (read-only; this is how the frozen numbers were made) ──
def measure_marginal(cw, function_name: str, reset_run_days, start: _dt.date, end: _dt.date) -> dict:
    """Re-measure one component from live CloudWatch. Read-only: GetMetricStatistics only.

    Returns {'baseline_median', 'baseline_n', 'reset_values', 'delta_median'} — or
    {'error': ...} when the series has no datapoints, because "no data" and "costs
    nothing" are opposite facts that would otherwise print identically.

        python3 -c "import boto3,datetime as d,sys; sys.path.insert(0,'deploy'); \
import restart_cost_model as m; print(m.measure_marginal(boto3.client('cloudwatch',region_name='us-west-2'), \
'visual-ai-qa', m.RESET_RUN_DAYS, d.date(2026,8,19), d.date(2026,9,18)))"
    """
    import statistics as _st

    resp = cw.get_metric_statistics(
        Namespace=METRIC_NAMESPACE,
        MetricName=METRIC_NAME,
        Dimensions=[{"Name": "LambdaFunction", "Value": function_name}],
        StartTime=_dt.datetime(start.year, start.month, start.day),
        EndTime=_dt.datetime(end.year, end.month, end.day),
        Period=86400,
        Statistics=["Sum"],
    )
    daily = {d["Timestamp"].date().isoformat(): round(d["Sum"], 4) for d in resp.get("Datapoints", [])}
    if not daily:
        return {"error": f"no {METRIC_NAMESPACE}::{METRIC_NAME}{{LambdaFunction={function_name}}} datapoints in the window — not a zero"}
    run_days = set(reset_run_days)
    baseline = [v for k, v in daily.items() if k not in run_days]
    reset_values = {k: v for k, v in daily.items() if k in run_days}
    if not baseline or not reset_values:
        return {"error": f"window holds {len(baseline)} baseline and {len(reset_values)} reset day(s) — a delta needs both"}
    bm = _st.median(baseline)
    return {
        "baseline_median": round(bm, 4),
        "baseline_n": len(baseline),
        "reset_values": reset_values,
        "delta_median": round(_st.median([v - bm for v in reset_values.values()]), 4),
    }


if __name__ == "__main__":  # pragma: no cover - operator convenience
    for line in format_lines():
        print(line)
