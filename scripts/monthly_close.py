#!/usr/bin/env python3
"""
monthly_close.py — PRINT-ONLY assembler for the COST_TRACKER monthly close (#3375).

Why this exists
---------------
The #1354 close ritual (docs/COST_TRACKER.md § "Monthly close ritual") is four queries
plus a hand-derived row, re-typed at every month rollover. The 2026-08-31
financial-diligence panel scripted them. This assembler runs the ritual's queries and
prints a candidate Monthly Actuals row — and NOTHING else:

  * It writes no files, no docs, no AWS state. Read-only Cost Explorer, CloudWatch and
    SSM GetParameter calls only.
  * The operator reviews the printout and appends the row BY HAND. A `Verified` stamp
    is a human claim (the #973/#2619 lesson) — this script never makes it for you.

Rent class: none standing — no cron, no alarm, no CI job. Run cost ≈ $0.02–0.04/close
(two Cost Explorer queries at $0.01 each; the CloudWatch/SSM reads are noise).

What it runs (the ritual's queries, in order)
---------------------------------------------
  1. CE actual by service (MONTHLY, UnblendedCost, grouped by SERVICE) + a DAILY
     Bedrock read for the spike/median/mean line in the Notes column.
  2. Days at tier ≥1 — LifePlatform/Budget::BudgetTier daily Maximum.
  3. Cost per reader-week — bill ÷ (mean UniqueVisitors7d × weeks in month), with n.
  4. The CallerClass loop — LifePlatform/AI::EstimatedCostUSD per class (#2892).
     Caveat printed with the numbers: the dimension is live only from 2026-08-23, so
     any window reaching earlier reads a PARTIAL stamp (the August close covered only
     a ~7-day stamped window) — the ci+dev SHARE of the stamped window is the fact to
     record, never the stamped dollars as the month's AI spend.
  5. The per-feature AI budget ledger (#3374 R3, scripts/ai_budget_ledger.py) — every
     budgeted feature's spend vs. its ledger budget, and the `unknown` bucket vs. its
     down-only ratchet, graded on the stability check's own attribution run. An
     overage is a close FAILURE (exit 1), not a note.
  Plus the dial states (SSM budget-tier / qa-level / remediation-mode), a secrets
  registry-vs-live-estate reconciliation (#3447 leg d — tests/test_secret_references
  .KNOWN_SECRETS is a CODE-REFERENCE registry, not the billable Secrets Manager
  estate; the two have already drifted, 28 registry vs 26 live as of 2026-09-02, and
  a live-but-unreferenced secret like life-platform/github-billing is billed and
  structurally invisible to the registry), and the run-twice stability check on
  scripts/ai_spend_attribution.py (its first invocation returned partial data on
  2026-08-31 — nondeterminism observed n=1, #3375).

Exit code (read it UNPIPED — `... | tail` reads the pipe's exit, the
reference_a_ci_gate_that_cannot_fail class): 0 = every query answered and the
attribution run-twice check was stable; 1 = something was unavailable or the two
attribution runs diverged — the printout says exactly what, close by hand from there.

Usage
-----
    python3 scripts/monthly_close.py                    # the month that just ended
    python3 scripts/monthly_close.py --month 2026-08    # a specific calendar month
    python3 scripts/monthly_close.py --skip-attribution # skip the run-twice check
"""

import argparse
import ast
import json
import os
import statistics
import subprocess
import sys
from datetime import date, datetime, timezone

import boto3

REGION = os.environ.get("AWS_REGION", "us-west-2")

# The CallerClass dimension only exists on datapoints emitted from this date (#2892
# rollout) — a window starting earlier reads a partial stamp.
CALLER_CLASS_LIVE_FROM = date(2026, 8, 23)
# Deliberately NOT named *_CLASSES: gate_census.py's registry-family matcher counts any
# module-level `.*_CLASSES` literal as a gate registry, and these are report iteration
# order, not gates (the sync_census_fact.py rename precedent — a spurious census row per
# entry otherwise). Mirrors the caller-class tuple in lambdas/ai/bedrock_client.py and
# cost_governor's episodic set.
CALLER_CLASS_ORDER = ("prod-cron", "remediation", "ci", "dev-session")
EPISODIC_CLASS_NAMES = ("ci", "dev-session")

DIALS = (
    "/life-platform/budget-tier",
    "/life-platform/qa-level",
    "/life-platform/remediation-mode",
)

_PROBLEMS: list[str] = []


def _problem(msg: str, label: str = "UNAVAILABLE") -> None:
    _PROBLEMS.append(msg)
    print(f"  !! {label} — {msg}")


def _month_window(month_arg: str | None) -> tuple[date, date, str]:
    """[start, end) for the requested calendar month; default = the month that just ended."""
    if month_arg:
        start = datetime.strptime(month_arg, "%Y-%m").date().replace(day=1)
    else:
        today = date.today()
        start = (today.replace(day=1) - date.resolution).replace(day=1)  # previous month
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    label = start.strftime("%b %Y")
    if date.today() < end:
        label += " (MONTH STILL OPEN — CE actual will settle; close at rollover)"
    return start, end, label


# ── Query 1: CE actual by service ────────────────────────────────────────────
def _ce_actuals(ce, start: date, end: date) -> dict:
    out: dict = {"total": None, "services": {}, "bedrock": {}, "daily_bedrock": []}
    try:
        resp = ce.get_cost_and_usage(
            TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
            Granularity="MONTHLY",
            Metrics=["UnblendedCost"],
            GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
        )
        for res in resp.get("ResultsByTime", []):
            for g in res.get("Groups", []):
                svc = g["Keys"][0]
                amt = float(g["Metrics"]["UnblendedCost"]["Amount"])
                out["services"][svc] = out["services"].get(svc, 0.0) + amt
        out["total"] = sum(out["services"].values())
        out["bedrock"] = {s: v for s, v in out["services"].items() if "Bedrock" in s}
    except Exception as e:
        _problem(f"CE by-service query failed: {e}")
        return out

    # DAILY Bedrock for the spike/median/mean Notes line. Filter list is derived from
    # the by-service names just read — never a hardcoded model list (a renamed model
    # silently vanishes from a stale filter; the cost-diligence skill's own warning).
    if out["bedrock"]:
        try:
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                Filter={"Dimensions": {"Key": "SERVICE", "Values": sorted(out["bedrock"])}},
            )
            for res in resp.get("ResultsByTime", []):
                amt = float(res["Total"]["UnblendedCost"]["Amount"])
                out["daily_bedrock"].append((res["TimePeriod"]["Start"], amt))
        except Exception as e:
            _problem(f"CE daily-Bedrock query failed: {e}")
    return out


# ── Query 2: days at tier ≥1 ─────────────────────────────────────────────────
def _days_at_tier(cw, start: date, end: date) -> int | None:
    try:
        resp = cw.get_metric_statistics(
            Namespace="LifePlatform/Budget",
            MetricName="BudgetTier",
            StartTime=datetime(start.year, start.month, 1, tzinfo=timezone.utc),
            EndTime=datetime(end.year, end.month, 1, tzinfo=timezone.utc),
            Period=86400,
            Statistics=["Maximum"],
        )
        return sum(1 for d in resp.get("Datapoints", []) if d["Maximum"] >= 1)
    except Exception as e:
        _problem(f"BudgetTier query failed: {e}")
        return None


# ── Query 2b: surge flips (#3510) ────────────────────────────────────────────
_GOVERNOR_SRC = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lambdas", "operational", "cost_governor_lambda.py"
)


def _governor_flip_bar(default: int = 2) -> int:
    """`SURGE_FLIPS_30D_ALARM` read from the governor's source by AST — the same
    two-literals-cannot-drift pattern tests/test_cost_drift_alarm_2883.py uses. Importing
    the module here would drag boto3 clients and the whole lambda import graph into a
    reporting script; restating the number would give the close a second opinion that
    ages separately from the governor that actually alerts."""
    try:
        tree = ast.parse(open(_GOVERNOR_SRC, encoding="utf-8").read(), filename=_GOVERNOR_SRC)
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SURGE_FLIPS_30D_ALARM" for t in node.targets):
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, int):
                    return node.value.value
    except Exception as e:
        _problem(f"could not read SURGE_FLIPS_30D_ALARM from the governor source: {e}")
    return default


def _surge_flips(cw, start: date, end: date) -> int | None:
    """Surge engage/disengage edges inside the month, from the governor's own
    LifePlatform/Budget::SurgeFlip series (one datapoint per edge).

    ADR-133's threshold used to sit at the MEAN of the weekly baseline, so surge mode —
    and with it the effective ceiling and all three tier bands — flipped on week-to-week
    noise: five edges in seven weeks, recorded nowhere but five owner emails and an SSM
    parameter history. The close now reads the count beside the tier-residence line, so
    a mis-set threshold shows up in the month's own record. None on a read failure — an
    unknown count must not print as a calm zero."""
    try:
        resp = cw.get_metric_statistics(
            Namespace="LifePlatform/Budget",
            MetricName="SurgeFlip",
            StartTime=datetime(start.year, start.month, 1, tzinfo=timezone.utc),
            EndTime=datetime(end.year, end.month, 1, tzinfo=timezone.utc),
            Period=86400,
            Statistics=["Sum"],
        )
        return int(sum(d["Sum"] for d in resp.get("Datapoints", [])))
    except Exception as e:
        _problem(f"SurgeFlip query failed: {e}")
        return None


# ── Query 3: cost per reader-week ────────────────────────────────────────────
def _reader_week(cw, start: date, end: date) -> dict | None:
    try:
        resp = cw.get_metric_statistics(
            Namespace="LifePlatform/Traffic",
            MetricName="UniqueVisitors7d",
            StartTime=datetime(start.year, start.month, 1, tzinfo=timezone.utc),
            EndTime=datetime(end.year, end.month, 1, tzinfo=timezone.utc),
            Period=86400,
            Statistics=["Average", "Maximum"],
        )
        pts = sorted(resp.get("Datapoints", []), key=lambda d: d["Timestamp"])
        if not pts:
            _problem("UniqueVisitors7d has no datapoints in the window")
            return None
        peak = max(pts, key=lambda d: d["Maximum"])
        return {
            "mean": statistics.mean(d["Average"] for d in pts),
            "n": len(pts),
            "peak": peak["Maximum"],
            "peak_day": peak["Timestamp"].date().isoformat(),
        }
    except Exception as e:
        _problem(f"UniqueVisitors7d query failed: {e}")
        return None


# ── Query 4: the CallerClass loop (#2892) ────────────────────────────────────
def _caller_class(cw, start: date, end: date) -> dict[str, float]:
    out: dict[str, float] = {}
    seconds = (end - start).days * 86400
    for cls in CALLER_CLASS_ORDER:
        try:
            resp = cw.get_metric_statistics(
                Namespace="LifePlatform/AI",
                MetricName="EstimatedCostUSD",
                Dimensions=[{"Name": "CallerClass", "Value": cls}],
                StartTime=datetime(start.year, start.month, 1, tzinfo=timezone.utc),
                EndTime=datetime(end.year, end.month, 1, tzinfo=timezone.utc),
                Period=seconds,
                Statistics=["Sum"],
            )
            out[cls] = sum(d["Sum"] for d in resp.get("Datapoints", []))
        except Exception as e:
            _problem(f"CallerClass query failed for {cls}: {e}")
            out[cls] = 0.0
    return out


# ── Dial states ──────────────────────────────────────────────────────────────
def _dials(ssm) -> dict[str, str]:
    out = {}
    for name in DIALS:
        try:
            out[name] = ssm.get_parameter(Name=name)["Parameter"]["Value"]
        except Exception as e:
            out[name] = f"unreadable ({type(e).__name__})"
            _problem(f"dial {name} unreadable: {e}")
    return out


# ── Secrets reconciliation (#3447 leg d) ──────────────────────────────────────
_SECRET_REFS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "test_secret_references.py")


def _known_secrets_registry() -> set[str]:
    """``KNOWN_SECRETS`` lifted by AST — never a hand-restated copy (the same
    #3374 R1 discipline the cost-surface plane's count already uses). This is
    the CODE-REFERENCE registry (grep scope: lambdas/ + mcp/ source), not the
    live billable Secrets Manager estate — that is exactly the gap this
    reconciliation exists to surface, not to paper over."""
    tree = ast.parse(open(_SECRET_REFS_PATH, encoding="utf-8").read(), filename=_SECRET_REFS_PATH)
    for node in ast.walk(tree):
        targets = [t.id for t in node.targets if isinstance(t, ast.Name)] if isinstance(node, ast.Assign) else []
        if "KNOWN_SECRETS" in targets and isinstance(getattr(node, "value", None), ast.Set):
            names = {e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
            if names:
                return names
    raise ValueError(f"KNOWN_SECRETS not found (or empty) in {_SECRET_REFS_PATH} — the #3447 secrets reconciliation rotted")


def _secrets_reconciliation() -> tuple[set[str], set[str]]:
    """(registry, live estate) — read-only ``secretsmanager:ListSecrets``. Raises
    up to the caller on an AWS failure; the caller records it as a problem, same
    as every other query here (absence must never read as a clean reconciliation)."""
    registry = _known_secrets_registry()
    sm = boto3.client("secretsmanager", region_name=REGION)
    estate: set[str] = set()
    paginator = sm.get_paginator("list_secrets")
    for page in paginator.paginate():
        estate.update(s["Name"] for s in page.get("SecretList", []))
    return registry, estate


# ── Run-twice stability check on ai_spend_attribution.py ─────────────────────
def _attribution_run(month: str) -> dict | None:
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ai_spend_attribution.py")
    r = subprocess.run(
        [sys.executable, script, "--month", month, "--json", "--no-authoritative"],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if r.returncode != 0:
        _problem(f"ai_spend_attribution.py exited {r.returncode}: {r.stderr.strip()[:200]}")
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError as e:
        _problem(f"ai_spend_attribution.py output was not JSON: {e}")
        return None


def _attribution_stability(start: date) -> tuple[dict | None, list[str]]:
    """Run the per-feature attribution TWICE and diff — its first invocation returned
    partial data on 2026-08-31 (nondeterminism observed n=1). Divergence is a finding,
    not a formatting problem: trust neither run until a third agrees."""
    month = start.strftime("%Y-%m")
    first, second = _attribution_run(month), _attribution_run(month)
    if first is None or second is None:
        return second or first, ["run-twice check could not complete (a run failed)"]
    diffs: list[str] = []
    a = {f["feature"]: f["cost_usd"] for f in first["features"]}
    b = {f["feature"]: f["cost_usd"] for f in second["features"]}
    for feat in sorted(set(a) | set(b)):
        va, vb = a.get(feat), b.get(feat)
        if va is None or vb is None:
            diffs.append(f"feature {feat!r} present in only one run (run1={va} run2={vb})")
        elif abs(va - vb) > 0.01:
            diffs.append(f"feature {feat!r} cost diverged: run1=${va:.2f} run2=${vb:.2f}")
    return second, diffs


# ── Assembly ─────────────────────────────────────────────────────────────────
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _cycle_geneses() -> list[tuple[int, str]]:
    """[(cycle, genesis), ...] parsed from the ONE registry (#3601).

    Raises rather than returning [] — "the registry parsed empty" and "there have been
    no resets" are opposite facts, and a cadence of zero printed from the first is the
    vacuous-pass class this repo keeps re-learning.
    """
    import re as _re

    src_path = os.path.join(_REPO_ROOT, "lambdas", "web", "site_api_data.py")
    try:
        src = open(src_path, encoding="utf-8").read()
        blk = src[src.index("CYCLE_GENESES = {") :]
        blk = blk[: blk.index("\n}")]
        pairs = sorted((int(a), b) for a, b in _re.findall(r'(\d+):\s*"(\d{4}-\d{2}-\d{2})"', blk))
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"CYCLE_GENESES unreadable: {e}") from e
    if not pairs:
        raise RuntimeError("CYCLE_GENESES parsed EMPTY — a vacuous zero is not a cadence")
    return pairs


def reset_price() -> dict:
    """The measured $ per reset (#3601 box 2), from `deploy/restart_cost_model.py`.

    The model is frozen literals WITH their derivation, not a guess: each component is a
    marginal delta on the platform's own `LifePlatform/AI::EstimatedCostUSD` instrument,
    and the module can re-derive every one of them live (`measure_marginal`, read-only).
    Imported rather than restated here so the close and the proportionality row quote one
    number — the two-copies failure row 86 already demonstrated with "a few times a
    quarter".
    """
    deploy_dir = os.path.join(_REPO_ROOT, "deploy")
    if deploy_dir not in sys.path:
        sys.path.insert(0, deploy_dir)
    try:
        import restart_cost_model
    except Exception as e:  # noqa: BLE001
        return {"error": f"deploy/restart_cost_model.py unimportable: {e}"}
    try:
        restart_cost_model.validate()
    except ValueError as e:
        return {"error": f"reset cost model REFUSED to price itself: {e}"}
    return {
        "usd": restart_cost_model.total_usd(),
        "high_usd": restart_cost_model.high_usd(),
        "measured_at": restart_cost_model.MEASURED_AT.isoformat(),
        "stale": restart_cost_model.is_stale(),
        "lines": restart_cost_model.format_lines(),
        "per_quarter": restart_cost_model.per_quarter_usd,
    }


def findings_per_reset() -> dict:
    """Confirmed review findings per reset, over the newest full review's own window.

    A RATE, not an attribution: it does not claim the resets caused the findings. The
    attribution is stated separately and comes from the RCA that filed #3601 — 39 of the
    99 confirmed findings in `docs/reviews/FULLREVIEW_2026-09-05.md` live in the
    reset -> first-cron window.

    Window = (previous FULLREVIEW date, this FULLREVIEW date]; resets = geneses in it.
    Every failure mode returns an `error` rather than a number, because a
    findings-per-reset of 0.0 printed from an unparsed doc is worse than no line.
    """
    import re as _re

    rev_dir = os.path.join(_REPO_ROOT, "docs", "reviews")
    try:
        files = sorted(f for f in os.listdir(rev_dir) if _re.match(r"^FULLREVIEW_\d{4}-\d{2}-\d{2}.*\.md$", f))
    except OSError as e:
        return {"error": f"docs/reviews unreadable: {e}"}
    if len(files) < 2:
        return {"error": f"need two FULLREVIEW_*.md files to bound a window; found {len(files)}"}
    latest, previous = files[-1], files[-2]
    latest_date = date.fromisoformat(latest[len("FULLREVIEW_") :][:10])
    prev_date = date.fromisoformat(previous[len("FULLREVIEW_") :][:10])
    text = open(os.path.join(rev_dir, latest), encoding="utf-8").read()
    m = _re.search(r"(\d+)\s+findings\s+CONFIRMED", text)
    if not m:
        return {"error": f"{latest} states no '<N> findings CONFIRMED' — not parsed, so not reported as zero"}
    findings = int(m.group(1))
    try:
        pairs = _cycle_geneses()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}
    resets = [g for _, g in pairs if prev_date < date.fromisoformat(g) <= latest_date]
    if not resets:
        return {"error": f"no reset genesis in ({prev_date}, {latest_date}] — a per-reset rate needs at least one"}
    return {
        "review": latest,
        "window": f"{prev_date.isoformat()} -> {latest_date.isoformat()}",
        "findings": findings,
        "resets": len(resets),
        "reset_dates": resets,
        "rate": round(findings / len(resets), 1),
    }


def reset_block_lines(month_start: date, month_end_exclusive: date) -> tuple[list[str], list[tuple[str, str]]]:
    """The close's `[6/6]` reset block (#3601): the four lines, as data.

    Window is half-open, `[month_start, month_end_exclusive)` — the same `_month_window()`
    pair every other query in this file takes.

    Returns `(lines, problems)` and touches no AWS, so the whole block is testable
    without credentials — the half of #3375 that previously could only be checked by
    running a live close. `problems` is `[(label, message), ...]`; `main()` routes each
    through `_problem()`, which is what makes the close exit non-zero.
    """
    lines = ["\n[6/6] Reset cadence + price (#3601 — CYCLE_GENESES + deploy/restart_cost_model.py, both derived)"]
    problems: list[tuple[str, str]] = []
    rc = reset_cadence(month_start, month_end_exclusive)
    if rc.get("error"):
        problems.append(("RESET-CADENCE", rc["error"]))
    else:
        dates = ", ".join(rc["in_month_dates"]) or "none"
        lines.append(f"  resets this month              : {rc['in_month']}  ({dates})")
        lines.append(
            f"  lifetime cadence              : {rc['lifetime_reanchors']} re-anchors / {rc['lifetime_span_days']}d "
            f"= {rc['per_quarter']:.1f} per quarter   (median gap {rc['median_gap']}d, min {rc['min_gap']}d)"
        )
        lines.append(
            f"  current cycle                 : {rc['current_cycle']} since {rc['current_genesis']}, running {rc['current_age_days']}d"
        )
        lines.append(
            f"  gaps under the 30d minimum    : {len(rc['under_minimum'])} of {rc['lifetime_reanchors']} "
            "(historic; the [0a] preflight has enforced the rule since 2026-09-16)"
        )

    # #3601 box 2: the PRICE of the cadence above. Printed next to the count deliberately
    # — a cadence without a price and a price without a cadence are each half of the
    # demote trigger every reset-machinery row in docs/PROPORTIONALITY.md is judged on.
    rp = reset_price()
    if rp.get("error"):
        problems.append(("RESET-PRICE", rp["error"]))
    else:
        lines.append(f"  {rp['lines'][0]}")
        lines.extend(f"  {ln}" for ln in rp["lines"][1:])
        if not rc.get("error"):
            lines.append(
                f"  reset spend this month        : {rc['in_month']} x ${rp['usd']:.2f} = ${rc['in_month'] * rp['usd']:.2f} "
                f"(cash only); at the measured {rc['per_quarter']:.1f}/quarter cadence = "
                f"${rp['per_quarter'](rc['per_quarter']):.2f}/quarter"
            )
    fpr = findings_per_reset()
    if fpr.get("error"):
        problems.append(("RESET-FINDINGS", f"findings-per-reset: {fpr['error']}"))
    else:
        lines.append(
            f"  findings per reset            : {fpr['findings']} confirmed / {fpr['resets']} resets in {fpr['window']} "
            f"= {fpr['rate']}  (a RATE over {fpr['review']}'s window, not an attribution; the RCA's own attribution is "
            "39 of 99 in the reset -> first-cron window)"
        )
    lines.append(
        "  NOT PRINTED, and not invented : the DEMOTE-candidate list (#3601's fourth line). It needs a\n"
        "                                  per-instrument zero-output ledger — 30 days of non-degraded output per\n"
        "                                  instrument — which no registry in this tree holds yet. Named as missing\n"
        "                                  rather than approximated, so a shorter report cannot read as a complete one."
    )
    return lines, problems


def reset_cadence(month_start: date, month_end_exclusive: date, today: date | None = None) -> dict:
    """Reset cadence for the close (#3601), derived from CYCLE_GENESES — never hand-typed.

    THE WINDOW IS HALF-OPEN, `[month_start, month_end_exclusive)`, and the parameter is
    named for it. Every other query in this file takes `_month_window()`'s `end`, which is
    the FIRST of the next month; this function compared `<= month_end` and so counted a
    2026-09-01 re-anchor inside the August close — found by running the close against
    August 2026 on 2026-09-20, not by reading it. An off-by-one in a cadence line is
    exactly the kind of small wrong number the rest of this ledger is trying to stop.

    The reset is the platform's most expensive recurring EVENT and no row priced it. Row 86
    of `docs/PROPORTIONALITY.md` said "a few times a quarter" against a measured 9.2, and
    that figure is the denominator every reset-machinery demote trigger is judged against.

    The owner ruled a 30-day minimum cycle length on 2026-09-05 (#3606 ruling 1), enforced
    from 2026-09-16 by `restart_pipeline.py`'s `[0a]` preflight. Printing the cadence every
    month is how that ruling stays observed rather than merely recorded.

    PARTIAL, and stated as such rather than left to look complete: this returns the COUNT
    and the GAPS. `$ per reset` now comes from `reset_price()` (the measured model in
    `deploy/restart_cost_model.py`, #3601 box 2) and findings-per-reset from
    `findings_per_reset()`. The DEMOTE-candidate list — the fourth line #3601 asks for —
    needs a per-instrument zero-output ledger that does not exist yet; it is named as
    missing in the printout rather than invented here.
    """
    today = today or date.today()
    try:
        pairs = _cycle_geneses()
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}

    dates = [date.fromisoformat(d) for _, d in pairs]
    in_month = [d for d in dates if month_start <= d < month_end_exclusive]
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    span = (dates[-1] - dates[0]).days
    current_age = (today - dates[-1]).days
    return {
        "in_month": len(in_month),
        "in_month_dates": [d.isoformat() for d in in_month],
        "lifetime_reanchors": len(dates) - 1,
        "lifetime_span_days": span,
        "per_quarter": (len(dates) - 1) / span * 91 if span else None,
        # statistics.median, not sorted(gaps)[n//2]. With an even n the index form returns
        # the UPPER of the two middles — 6 where the true median is 5.5 — and this number is
        # quoted in docs/PROPORTIONALITY.md row 86. Two spellings of "median" disagreeing by
        # half a day is how a doc literal and its source drift.
        "median_gap": statistics.median(gaps) if gaps else None,
        "min_gap": min(gaps) if gaps else None,
        "current_cycle": pairs[-1][0],
        "current_genesis": pairs[-1][1],
        "current_age_days": current_age,
        "under_minimum": [g for g in gaps if g < 30],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="PRINT-ONLY monthly cost-close assembler (#3375). Writes nothing, anywhere.")
    ap.add_argument("--month", help="calendar month YYYY-MM (default: the month that just ended)")
    ap.add_argument("--skip-attribution", action="store_true", help="skip the ai_spend_attribution run-twice check")
    args = ap.parse_args(argv)

    start, end, label = _month_window(args.month)
    days_in_month = (end - start).days
    weeks = days_in_month / 7.0

    ce = boto3.client("ce", region_name="us-east-1")  # CE is a us-east-1 endpoint
    cw = boto3.client("cloudwatch", region_name=REGION)
    ssm = boto3.client("ssm", region_name=REGION)

    print(f"\nMonthly close assembler — {label}  (print-only: this script writes NOTHING)\n")

    # 1. CE actual
    print("[1/6] CE actual by service (unblended)")
    actuals = _ce_actuals(ce, start, end)
    top = sorted(actuals["services"].items(), key=lambda kv: -kv[1])[:8]
    for svc, amt in top:
        print(f"  {svc:<48} ${amt:>8.2f}")
    total = actuals["total"]
    bedrock_total = sum(actuals["bedrock"].values())
    if total is not None:
        print(f"  {'TOTAL':<48} ${total:>8.2f}   (Bedrock ${bedrock_total:.2f})")
    spike_note = ""
    daily = [amt for _, amt in actuals["daily_bedrock"]]
    if daily:
        mean, median = statistics.mean(daily), statistics.median(daily)
        sd = statistics.stdev(daily) if len(daily) > 1 else 0.0
        spikes = [(d, amt) for d, amt in actuals["daily_bedrock"] if amt > mean + 2 * sd and amt > 2 * median]
        spike_note = "spikes " + ", ".join(f"{d[5:]} ${amt:.2f}" for d, amt in spikes) + "; " if spikes else ""
        spike_note += f"median ${median:.2f}/day, mean ${mean:.2f}"
        print(f"  Bedrock daily: {spike_note}")

    # 2. Days at tier ≥1
    print("\n[2/6] Days at tier >=1 (LifePlatform/Budget::BudgetTier daily max)")
    tier_days = _days_at_tier(cw, start, end)
    if tier_days is not None:
        print(f"  {tier_days} / {days_in_month} days")
    flips = _surge_flips(cw, start, end)
    gov_flip_bar = _governor_flip_bar()
    print(
        f"  surge flips this month: {flips if flips is not None else '??'}"
        + (
            f"  <-- at/above the {gov_flip_bar}-flip bar (#3510): the threshold is inside the baseline's noise"
            if (flips or 0) >= gov_flip_bar
            else ""
        )
    )

    # 3. Cost per reader-week
    print("\n[3/6] Cost per reader-week (LifePlatform/Traffic::UniqueVisitors7d)")
    readers = _reader_week(cw, start, end)
    reader_week = None
    if readers and total:
        reader_week = total / (readers["mean"] * weeks)
        print(
            f"  uniques mean {readers['mean']:.0f} (n={readers['n']} daily datapoints, "
            f"peak {readers['peak']:.0f} on {readers['peak_day']}) -> "
            f"${total:.2f} / ({readers['mean']:.0f} x {weeks:.2f}) = ${reader_week:.3f}/reader-week"
        )

    # 4. CallerClass split
    print("\n[4/6] CallerClass split (LifePlatform/AI::EstimatedCostUSD, #2892)")
    by_class = _caller_class(cw, start, end)
    stamped = sum(by_class.values())
    episodic = sum(by_class[c] for c in EPISODIC_CLASS_NAMES)
    for cls in CALLER_CLASS_ORDER:
        print(f"  {cls:<12} ${by_class[cls]:>7.2f}")
    share = (episodic / stamped * 100) if stamped else None
    if share is not None:
        print(f"  ci+dev share of the ${stamped:.2f} stamped window: {share:.0f}%")
    if start < CALLER_CLASS_LIVE_FROM:
        print(
            f"  CAVEAT: the CallerClass dimension is live only from {CALLER_CLASS_LIVE_FROM} — this window\n"
            f"  starts earlier, so the stamp is PARTIAL (the Aug 2026 close covered only a ~7-day stamped\n"
            f"  window). Record the SHARE with the stamped-window dollars named; never present the stamped\n"
            f"  dollars as the month's AI spend."
        )
    if stamped == 0:
        _problem("CallerClass split is all-zero — no signal (indistinguishable from a failed query)")

    # Dial states
    print("\nDial states (SSM, read-only)")
    for name, value in _dials(ssm).items():
        print(f"  {name:<38} {value}")

    # Secrets reconciliation (#3447 leg d)
    print("\nSecrets reconciliation (tests/test_secret_references.KNOWN_SECRETS vs live Secrets Manager estate, #3447)")
    try:
        registry, estate = _secrets_reconciliation()
    except Exception as e:
        _problem(f"secrets reconciliation failed: {e}")
    else:
        registry_only = sorted(registry - estate)
        estate_only = sorted(estate - registry)
        print(f"  registry {len(registry)} vs live estate {len(estate)}")
        if registry_only:
            print(
                f"  registry-only (declared, not currently live — verify each is a deliberately-disarmed/deferred feature): {', '.join(registry_only)}"
            )
        if estate_only:
            _problem(
                f"live secret(s) billed with NO registry row — invisible to the R1 cost-surface secrets count: {', '.join(estate_only)}"
            )
        if not registry_only and not estate_only:
            print("  registry and live estate agree exactly")

    # Run-twice stability
    attribution, diffs = (None, [])
    if args.skip_attribution:
        print("\nai_spend_attribution run-twice check: SKIPPED (--skip-attribution)")
    else:
        print("\nai_spend_attribution run-twice stability check (first run returned partial data on 2026-08-31, n=1)")
        attribution, diffs = _attribution_stability(start)
        if diffs:
            for d in diffs:
                print(f"  DIVERGED: {d}")
            print("  -> trust neither run; run a third by hand and use the numbers two runs agree on")
        elif attribution is not None:
            n = len(attribution["features"])
            print(f"  stable: two runs agree on {n} features (top: " + ", ".join(f["feature"] for f in attribution["features"][:3]) + ")")

    # 5. The per-feature AI budget ledger (#3374 R3) — graded on the SAME
    # attribution run the stability check just validated; a budgeted feature over
    # its ledger budget, or `unknown` over the down-only ratchet, FAILS the close.
    print("\n[5/6] AI budget ledger (#3374 R3, scripts/ai_budget_ledger.py)")
    import ai_budget_ledger  # sibling module — scripts/ is this file's own directory

    ledger_structural = ai_budget_ledger.validate()
    for f in ledger_structural:
        _problem(f"ai_budget_ledger structural: {f}", label="FAIL")
    if args.skip_attribution:
        month_arg = start.strftime("%Y-%m")
        print(f"  SKIPPED with --skip-attribution — run by hand: python3 scripts/ai_budget_ledger.py --month {month_arg}")
    elif attribution is None or diffs:
        # the run-twice leg already recorded its own problem/divergence → exit 1
        print("  not evaluated: no stable attribution run to grade against (see the check above)")
    else:
        ledger_failures = ai_budget_ledger.evaluate_close(attribution)
        for f in ledger_failures:
            _problem(f"ai_budget_ledger: {f}", label="FAIL")
        if not ledger_failures and not ledger_structural:
            budgeted = sum(1 for r in ai_budget_ledger.LEDGER.values() if r["monthly_budget_usd"] is not None)
            print(
                f"  ok: {budgeted} budgeted features within budget; unknown within the down-only ratchet "
                f"(${ai_budget_ledger.LEDGER[ai_budget_ledger.UNKNOWN_KEY]['monthly_budget_usd']})"
            )

    # #3601: the reset cadence, printed every month so the owner's 30-day ruling stays
    # OBSERVED rather than merely recorded. Derived from CYCLE_GENESES, never hand-typed.
    lines, problems = reset_block_lines(start, end)
    for ln in lines:
        print(ln)
    for label, msg in problems:
        _problem(msg, label)

    # The candidate row
    fmt = lambda v, spec=".2f": format(v, spec) if v is not None else "??"  # noqa: E731
    print("\n" + "=" * 78)
    print("CANDIDATE Monthly Actuals row (docs/COST_TRACKER.md — review, then append BY HAND;")
    print("fill <...> from judgment, re-read the two Verified: stamps yourself):\n")
    print(
        f"| {label.split(' (')[0]} | **${fmt(total)}** (CE actual) | **{tier_days if tier_days is not None else '??'} / {days_in_month}** | "
        f"Bedrock ${fmt(bedrock_total)}{' — ' + spike_note if spike_note else ''}. "
        f"CallerClass: ci+dev = {fmt(share, '.0f')}% of the ${fmt(stamped)} stamped window. "
        f"Cost per reader-week = ${fmt(total)} / ({fmt(readers['mean'] if readers else None, '.0f')} x {weeks:.2f}) = "
        f"**${fmt(reader_week, '.3f')}** (uniques mean {fmt(readers['mean'] if readers else None, '.0f')}, "
        f"n={readers['n'] if readers else '??'}; peak {fmt(readers['peak'] if readers else None, '.0f')} on "
        f"{readers['peak_day'] if readers else '??'}). <notes: one-time items, decisions, window states> |"
    )
    print("\nThis script wrote nothing. The append and the Verified: stamps are yours to make.")

    if _PROBLEMS or diffs:
        print(
            f"\nEXIT 1 — {len(_PROBLEMS)} problem{'' if len(_PROBLEMS) == 1 else 's'} "
            f"(unavailable queries / ledger failures), {len(diffs)} divergence(s) (listed above)."
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
