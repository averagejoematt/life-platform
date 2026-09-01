#!/usr/bin/env python3
"""scripts/ai_budget_ledger.py — the per-feature AI budget ledger (#3374 R3).

The ``deploy/emf_namespace_ledger.py`` pattern applied to Bedrock spend: **every
budget-guard AI feature carries a row naming who owns it, where its dollars land
in the attribution instrument, and — where attribution is clean — a monthly
budget the close is graded against.** The instrument is
``scripts/ai_spend_attribution.py`` (LifePlatform/AI::EstimatedCostUSD per
``LambdaFunction`` dimension, self-emitted at the ``bedrock_client`` chokepoint);
this ledger stores exactly the facts that instrument cannot derive: the mapping
from a ``budget_guard._FEATURE_CUTOFF`` feature to the dimension value(s) that
carry its spend, and the operator's ceiling for each.

THE LEDGER'S KEYS ARE EXACTLY ``_FEATURE_CUTOFF``'s KEYS PLUS ``unknown`` — the
contract test (tests/test_ai_budget_ledger_3374.py) asserts set equality, not
containment, so a NEW AI feature cannot ship without declaring its budget row,
and a row describing a deleted feature cannot survive.

THE ``unknown`` ROW IS DOWN-ONLY, FOUNDED AT $33.19 (the August 2026 actual —
8,524 unattributed calls before #2888/#2892 closed the gap; a 2026-09-01 re-read
of the same window gave $33.21, the $0.02 being late-arriving datapoints). The
committed budget may only ever move DOWN from the founding value: unattributed
spend shrinking is the proof attribution landed; growing past the ratchet reds
the close. Raising it is deliberately a two-place edit (here AND the founding
pin in the contract test) — i.e. a reviewed decision, never a drive-by.

ATTRIBUTION HONESTY (ADR-104/105 — stated, never faked). The dimension is
per-LAMBDA, so per-feature dollars exist only where feature <-> lambda is 1:1
(``attribution=EXCLUSIVE``). Features that share an emitting lambda
(``SHARED``) or have no dedicated dimension value observed (``NONE``) carry
``monthly_budget_usd=None`` and are gated only by the ADR-063 ceiling — the gap
is visible in the row, not hidden. Budgeted rows covered $41.28 of the $84.87
August stamped spend; with ``unknown`` ($33.21) the close check grades ~88% of
stamped dollars.

THE BUDGET RULE IS DERIVED, NOT CHOSEN: ``round(max($1.00, 1.15 x founding
August actual), 2)``. 1.15 is R2's MoM growth clause (calibrated so the Jul->Aug
floor creep just trips it — see ``doc_facts_ops.monthly_close_driver_hits``);
the $1.00 floor keeps sub-dollar features from flapping the close while still
capping any of them at <0.5% of the $215 ceiling. ``validate()`` recomputes the
rule, so a budget can't drift from its stated derivation.

ENFORCEMENT PLANES (no new alarm, cron, or runtime — #3374's constraint):
  * pre-merge  — the contract test (set equality, down-only unknown, rule
                 conformance, mutation controls);
  * at close   — ``scripts/monthly_close.py`` step [5/5] evaluates this ledger
                 against its own attribution run and exits 1 on any overage;
                 standalone form: ``python3 scripts/ai_budget_ledger.py --month
                 2026-09`` (read-only CloudWatch, via the instrument).

Usage
-----
    python3 scripts/ai_budget_ledger.py --check          # structural, no AWS
    python3 scripts/ai_budget_ledger.py --month 2026-09  # close-time grade
"""

from __future__ import annotations

import argparse
import ast
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
BUDGET_GUARD_PATH = ROOT / "lambdas" / "ai" / "budget_guard.py"

# ── attribution classes ──────────────────────────────────────────────────────
EXCLUSIVE = "exclusive"  # the row's keys carry ONLY this feature's spend → budgeted
SHARED = "shared"  # keys carry >1 feature's spend → per-feature dollars don't exist
NONE = "none"  # no dedicated dimension value observed for this feature
ATTRIBUTION_KINDS = (EXCLUSIVE, SHARED, NONE)

UNKNOWN_KEY = "unknown"
# The August 2026 actual for the unattributed bucket — the down-only ratchet's
# founding value. The committed unknown budget below may equal it or move DOWN;
# tests/test_ai_budget_ledger_3374.py pins this literal too, so a raise is a
# two-file, reviewed act.
UNKNOWN_FOUNDING_USD = 33.19

# R2's MoM growth clause, reused as the per-feature headroom over the founding
# month; the floor keeps sub-dollar rows from flapping the close.
GROWTH_FACTOR = 1.15
BUDGET_FLOOR_USD = 1.00

FOUNDING_WINDOW = "2026-08"  # ai_spend_attribution --month 2026-08, run 2026-09-01


def _row(*, owner, attribution, attribution_keys=(), founding_usd=None, monthly_budget_usd=None, note):
    return {
        "owner": owner,  # the module that gates on this feature (budget_guard.allow site)
        "attribution": attribution,  # EXCLUSIVE / SHARED / NONE — see module docstring
        "attribution_keys": tuple(attribution_keys),  # LifePlatform/AI LambdaFunction dimension values
        "founding_usd": founding_usd,  # measured spend over attribution_keys, FOUNDING_WINDOW
        "monthly_budget_usd": monthly_budget_usd,  # the close ceiling; None = not per-feature gateable
        "note": note,
    }


LEDGER: dict[str, dict] = {
    # ── band 1: internal/dev AI ──────────────────────────────────────────────
    "ensemble": _row(
        owner="lambdas/coach/coach_ensemble_digest.py",
        attribution=EXCLUSIVE,
        attribution_keys=("coach-ensemble-digest",),
        founding_usd=0.25,
        monthly_budget_usd=1.00,
        note="cross-coach meta-synthesis; single-purpose lambda, clean 1:1 attribution",
    ),
    "chronicle_editor": _row(
        owner="lambdas/ai/margaret_editor_pass.py",
        attribution=SHARED,
        attribution_keys=("wednesday-chronicle",),
        note="runs inside the wednesday-chronicle lambda alongside the `chronicle` feature — "
        "one dimension value, two features; Aug combined $0.29",
    ),
    "coherence_semantic": _row(
        owner="lambdas/operational/coherence_sentinel_lambda.py",
        attribution=EXCLUSIVE,
        attribution_keys=("life-platform-coherence-sentinel",),
        founding_usd=0.02,
        monthly_budget_usd=1.00,
        note="the sentinel's advisory Haiku read; single-purpose lambda",
    ),
    "eyeball_estimate": _row(
        owner="lambdas/experiment/eyeball_calibration.py",
        attribution=NONE,
        note="meal-photo vision probe; no dedicated LambdaFunction value observed in the founding window — "
        "spend lands under its host lambda's key. Budget at first close with a dedicated signal",
    ),
    "conversation_enrichment": _row(
        owner="lambdas/ai/conversation_enrichment.py",
        attribution=SHARED,
        attribution_keys=("journal-enrichment",),
        note="hosted by journal-enrichment AND journal-analyzer, both of which run other AI — "
        "per-feature dollars not separable; Aug journal-enrichment $0.01",
    ),
    # ── band 2: reader narrative ─────────────────────────────────────────────
    "coach_narrative": _row(
        owner="lambdas/coach/coach_narrative_orchestrator.py",
        attribution=EXCLUSIVE,
        attribution_keys=(
            "coach-narrative-orchestrator",
            "coach-state-updater",
            "coach-history-summarizer",
            "coach-daily-reflection",
            "elena-state-updater",
        ),
        founding_usd=10.05,
        monthly_budget_usd=11.56,
        note="the coach pipeline as a group — orchestrator/history-summarizer/elena-state-updater "
        "gate on coach_narrative directly; state-updater and daily-reflection are stages of the "
        "same pipeline with no other feature's spend",
    ),
    "state_of_matthew": _row(
        owner="lambdas/compute/state_of_matthew_lambda.py",
        attribution=EXCLUSIVE,
        attribution_keys=("state-of-matthew",),
        founding_usd=0.04,
        monthly_budget_usd=1.00,
        note="weekly brief narration; single-purpose lambda",
    ),
    "daily_debrief": _row(
        owner="lambdas/emails/daily_debrief_lambda.py",
        attribution=EXCLUSIVE,
        attribution_keys=("daily-debrief",),
        founding_usd=0.07,
        monthly_budget_usd=1.00,
        note="single-purpose lambda",
    ),
    "chronicle": _row(
        owner="lambdas/emails/wednesday_chronicle_lambda.py",
        attribution=SHARED,
        attribution_keys=("wednesday-chronicle",),
        note="shares its lambda's dimension value with chronicle_editor (Margaret's pass) — see that row",
    ),
    "horizons_retrospective": _row(
        owner="lambdas/reading/horizons_retrospective.py",
        attribution=NONE,
        note="the Mind coach's weekly grounded retrospective; no dedicated LambdaFunction value observed "
        "in the founding window — spend lands under its host lambda's key",
    ),
    "coach_nudge": _row(
        owner="lambdas/coach/coach_nudge_engine.py",
        attribution=EXCLUSIVE,
        attribution_keys=("coach-nudge",),
        founding_usd=0.00,
        monthly_budget_usd=1.00,
        note="dedicated coach-nudge lambda (email_stack); $0 stamped in the founding window — "
        "the floor budget means growth past $1/mo gets a look at close",
    ),
    "coach_diary_reaction": _row(
        owner="lambdas/coach/coach_diary_reaction.py",
        attribution=SHARED,
        attribution_keys=("telegram-coach-worker",),
        note="telegram-coach-worker carries diary reactions, social reactions AND coach chat replies — "
        "one dimension value, several features; Aug combined $0.39",
    ),
    "coach_social_reaction": _row(
        owner="lambdas/coach/coach_diary_reaction.py",
        attribution=SHARED,
        attribution_keys=("telegram-coach-worker",),
        note="see coach_diary_reaction — same worker, same dimension value",
    ),
    "semantic_recall": _row(
        owner="lambdas/ai/semantic_recall.py",
        attribution=SHARED,
        attribution_keys=(),
        note="call sites spread across site-api-ai (ask retrieval), the recall indexer, reading "
        "resonance and recall-freshness QA — spend lands under several host keys each shared "
        "with other features",
    ),
    # ── band 3: irreducible reader promises + CI gates ───────────────────────
    "reader_truth_qa": _row(
        owner="lambdas/operational/reader_truth_qa.py",
        attribution=EXCLUSIVE,
        attribution_keys=("reader-truth-qa", "life-platform-qa-smoke"),
        founding_usd=8.45,
        monthly_budget_usd=9.72,
        note="two copies of the SAME gate by design (#2888): the CI label reader-truth-qa + the "
        "nightly qa-smoke lambda, whose only AI is this gate",
    ),
    "visual_ai_qa": _row(
        owner="tests/visual_ai_qa.py",
        attribution=EXCLUSIVE,
        attribution_keys=("visual-ai-qa",),
        founding_usd=3.11,
        monthly_budget_usd=3.58,
        note="the Claude-vision CI judge; dedicated allowlisted CI label (#2888)",
    ),
    "website_ai": _row(
        owner="lambdas/web/site_api_ai_lambda.py",
        attribution=SHARED,
        attribution_keys=("life-platform-site-api-ai", "life-platform-ai-quality-canary"),
        note="life-platform-site-api-ai also carries semantic_recall's ask-retrieval spend — "
        "not separable per-feature; Aug combined $0.47",
    ),
    "daily_brief_ai": _row(
        owner="lambdas/emails/daily_brief_lambda.py",
        attribution=EXCLUSIVE,
        attribution_keys=("daily-brief",),
        founding_usd=19.29,
        monthly_budget_usd=22.18,
        note="the largest attributed line ($19.29 Aug) — 'protect longest' by design, but growth "
        "past +15% MoM is exactly what the close should see",
    ),
    # ── the residual bucket: DOWN-ONLY ───────────────────────────────────────
    UNKNOWN_KEY: _row(
        owner="lambdas/ai/bedrock_client.py::feature_name() residual",
        attribution=EXCLUSIVE,
        attribution_keys=("unknown",),
        founding_usd=UNKNOWN_FOUNDING_USD,
        monthly_budget_usd=33.19,
        note="every call that reaches the chokepoint with no lambda name and no allowlisted CI label. "
        "DOWN-ONLY: shrinking is the proof attribution landed (ratchet the budget down when it does); "
        "growing past the committed value reds the close",
    ),
}


# ── derivation guard: the feature vocabulary comes from budget_guard, by AST ──
def budget_guard_features() -> frozenset:
    """The keys of ``_FEATURE_CUTOFF`` — lifted by AST, never hand-restated."""
    tree = ast.parse(BUDGET_GUARD_PATH.read_text(encoding="utf-8"), filename=str(BUDGET_GUARD_PATH))
    for node in ast.walk(tree):
        targets: list[str] = []
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        if "_FEATURE_CUTOFF" in targets and isinstance(getattr(node, "value", None), ast.Dict):
            keys = frozenset(k.value for k in node.value.keys if isinstance(k, ast.Constant) and isinstance(k.value, str))
            if keys:
                return keys
    raise ValueError(f"_FEATURE_CUTOFF not found (or empty) in {BUDGET_GUARD_PATH} — the R3 derivation rotted")


def expected_budget(founding_usd: float) -> float:
    """The stated budget rule — recomputed, so a stamped budget can't drift from it."""
    return round(max(BUDGET_FLOOR_USD, GROWTH_FACTOR * founding_usd), 2)


def validate() -> list[str]:
    """Structural failures in the committed ledger (no AWS). Empty list = sound."""
    failures: list[str] = []
    features = budget_guard_features()
    expected_keys = set(features) | {UNKNOWN_KEY}
    if set(LEDGER) != expected_keys:
        missing = sorted(expected_keys - set(LEDGER))
        extra = sorted(set(LEDGER) - expected_keys)
        if missing:
            failures.append(f"features with no ledger row (a new AI feature must declare its budget row): {missing}")
        if extra:
            failures.append(f"ledger rows for features budget_guard no longer declares: {extra}")

    for name, row in sorted(LEDGER.items()):
        if row["attribution"] not in ATTRIBUTION_KINDS:
            failures.append(f"{name}: unknown attribution kind {row['attribution']!r}")
        if row["attribution"] == EXCLUSIVE:
            if not row["attribution_keys"]:
                failures.append(f"{name}: EXCLUSIVE with no attribution_keys")
            if row["founding_usd"] is None or row["monthly_budget_usd"] is None:
                failures.append(f"{name}: EXCLUSIVE rows must carry founding_usd + monthly_budget_usd")
            elif name != UNKNOWN_KEY and abs(row["monthly_budget_usd"] - expected_budget(row["founding_usd"])) > 0.005:
                failures.append(
                    f"{name}: budget ${row['monthly_budget_usd']} does not follow the stated rule "
                    f"round(max({BUDGET_FLOOR_USD}, {GROWTH_FACTOR} x {row['founding_usd']}), 2) = "
                    f"${expected_budget(row['founding_usd'])}"
                )
        elif row["monthly_budget_usd"] is not None:
            failures.append(f"{name}: a {row['attribution']} row cannot carry a budget — per-feature dollars don't exist for it")

    # down-only unknown ratchet
    unknown = LEDGER.get(UNKNOWN_KEY)
    if unknown and unknown["monthly_budget_usd"] is not None and unknown["monthly_budget_usd"] > UNKNOWN_FOUNDING_USD:
        failures.append(
            f"unknown budget ${unknown['monthly_budget_usd']} exceeds the down-only founding value "
            f"${UNKNOWN_FOUNDING_USD} — unattributed spend may shrink, never grow (#3374 R3)"
        )

    # no attribution key may be claimed EXCLUSIVE-ly by two different rows
    claimed: dict[str, str] = {}
    for name, row in sorted(LEDGER.items()):
        if row["attribution"] != EXCLUSIVE:
            continue
        for key in row["attribution_keys"]:
            if key in claimed:
                failures.append(f"attribution key {key!r} claimed exclusively by both {claimed[key]} and {name}")
            claimed[key] = name
    return failures


def evaluate_close(attribution: dict) -> list[str]:
    """Close-time failures, given ``ai_spend_attribution.py --json`` output.

    Grades every budgeted (EXCLUSIVE) row's summed spend against its budget, and
    the ``unknown`` bucket against the down-only ratchet. Absence is failure,
    never success: an empty measurement or a missing ``unknown`` datapoint is
    indistinguishable from a broken query and reds the close."""
    failures: list[str] = []
    rows = attribution.get("features") or []
    spend = {r["feature"]: float(r.get("cost_usd") or 0.0) for r in rows}
    if not spend or sum(spend.values()) <= 0:
        failures.append("attribution returned no stamped spend — indistinguishable from a broken query; close by hand")
        return failures
    if UNKNOWN_KEY not in spend:
        failures.append(
            "no `unknown` datapoint in the window — either the attribution query is broken, or attribution "
            "reached 100% (if so: ratchet the unknown budget toward $0 in scripts/ai_budget_ledger.py first)"
        )
    for name, row in sorted(LEDGER.items()):
        budget = row["monthly_budget_usd"]
        if budget is None:
            continue
        actual = sum(spend.get(k, 0.0) for k in row["attribution_keys"])
        if actual > budget + 0.005:
            over = "the down-only unknown ratchet" if name == UNKNOWN_KEY else "its budget"
            failures.append(
                f"{name}: ${actual:.2f} over {over} ${budget:.2f} "
                f"(keys {', '.join(row['attribution_keys'])}) — name the driver or raise the budget deliberately"
            )
    return failures


def _attribution_json(month: str) -> dict:
    script = ROOT / "scripts" / "ai_spend_attribution.py"
    r = subprocess.run(
        [sys.executable, str(script), "--month", month, "--json", "--no-authoritative"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ai_spend_attribution.py exited {r.returncode}: {r.stderr.strip()[:300]}")
    return json.loads(r.stdout)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Per-feature AI budget ledger (#3374 R3).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", action="store_true", help="structural validation only (no AWS)")
    g.add_argument("--month", help="grade a calendar month YYYY-MM against the ledger (read-only CloudWatch)")
    args = ap.parse_args(argv)

    failures = validate()
    for f in failures:
        print(f"STRUCTURAL FAIL: {f}")
    if args.check:
        if not failures:
            budgeted = sum(1 for r in LEDGER.values() if r["monthly_budget_usd"] is not None)
            print(
                f"ledger sound: {len(LEDGER)} rows ({budgeted} budgeted), unknown down-only at ${LEDGER[UNKNOWN_KEY]['monthly_budget_usd']}"
            )
        return 1 if failures else 0

    close_failures = evaluate_close(_attribution_json(args.month))
    for f in close_failures:
        print(f"CLOSE FAIL [{args.month}]: {f}")
    if not close_failures:
        print(f"close [{args.month}]: every budgeted feature within its ledger budget; unknown within the down-only ratchet")
    return 1 if (failures or close_failures) else 0


if __name__ == "__main__":
    raise SystemExit(main())
