#!/usr/bin/env python3
"""
deploy/sentinel_producer_census.py — the producer census dead-man (#4034 box 1).

Own module (same split shape as the other `sentinel_*` siblings — module-size ceiling
#1665), imported into `deploy/drift_sentinel.py` with a one-line registration. It rides
the drift sentinel's existing Mon/Wed/Fri run in the remediation workflow: NO new
schedule, no new infrastructure, the remediation role's read-only
`cloudwatch:GetMetricData` grant.

WHAT IT ASKS
────────────
"Is every PRODUCER still running?" — for every Lambda that can write a custom-metric
namespace in `deploy/emf_namespace_ledger.py`, read `AWS/Lambda Invocations` and red on
any member silent past its stale window.

WHY THE POPULATION IS THE EMF LEDGER, NOT THE CDK SCHEDULE LIST
──────────────────────────────────────────────────────────────
`tests/test_heartbeat_completeness.py` asks its question of SCHEDULED Lambdas, and on
2026-09-17 it accepted the silent death of 51 of 83 of them as dated EXEMPT rows — every
one a producer nothing measured. A schedule list also cannot see a producer that has no
`schedule=` (site-api, the coach fan-out, the HAE webhook). The ledger's producer set is
derived by AST (`emf_namespace_discovery.discover_producers()`); a Lambda is a member when
its handler module's first-party IMPORT CLOSURE (under `lambdas/`) contains an emitting
module — so a coach Lambda that emits `LifePlatform/AI` through `ai/bedrock_client.py` is
a producer of it, exactly as the bundle it ships in is. Function -> handler module comes
from the system model's lambdas plane (`model/platform_model.json`, #2845).

WHERE EACH MEMBER'S CADENCE COMES FROM
─────────────────────────────────────
  * Scheduled members: `tests/test_heartbeat_completeness.scheduled_lambda_cadences()` —
    the #3506 resolver that sums every enabled rule per function and is itself pinned by
    a must-fail control (the same registry the heartbeat ledger's cadence claims are
    checked against). Stale window = 2 periods + one daily bucket, floored at 48h.
  * Event-driven members (no schedule): `EVENT_WINDOWS` below — a window per member,
    MEASURED from 30 days of live Invocations, never guessed.
  * `PAUSED` — a member whose source the source registry marks paused (derived, not typed).
  * `FIRST_DUE` — a scheduled member whose first scheduled fire is still ahead of it
    (dated; the row reds itself once that date + its window has passed).
  * `ON_DEMAND` — invoked only by a person or a rare external event, so silence carries no
    information. Named, dated, and printed with its last-seen age every run; this is the
    census's residual, and it is NOT a pass: it is reported as `unmeasured`, never `ok`.

VERDICT
───────
  drift     — at least one member silent past its window (the dead-man firing)
  degraded  — the Invocations read failed, or a scheduled member's cadence is unreadable
  clean     — every gradable member invoked inside its window
"""

from __future__ import annotations

import ast
import json
import os
import sys
from datetime import datetime, timedelta, timezone

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_ROOT, "deploy"), os.path.join(_ROOT, "tests"), os.path.join(_ROOT, "lambdas")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

REGION = os.environ.get("AWS_REGION", "us-west-2")
MODEL_PATH = os.path.join(_ROOT, "model", "platform_model.json")
LAMBDAS_DIR = os.path.join(_ROOT, "lambdas")

# CloudWatch keeps 1-hour-resolution data 455 days; a 1-day period reads all of it. The
# lookback must exceed the widest stale window (a quarterly cron: ~2 x 91d + 1d).
LOOKBACK_DAYS = 440
STALE_FLOOR_HOURS = 48
BUCKET_HOURS = 24
_MAX_QUERIES_PER_CALL = 500

MEASURED_ON = "2026-09-23"  # EVENT_WINDOWS: 30d hourly AWS/Lambda Invocations to this date

# ── event-driven producers: a window each, from the measured max inter-invocation gap ──
# window = ~3x the 30-day max gap, floored at 3 days. `gap_h` is the evidence, kept beside
# the number so a reader can re-derive it.
EVENT_WINDOWS: dict[str, dict] = {
    "life-platform-site-api": {"window_days": 3, "gap_h": 7, "trigger": "reader traffic via CloudFront -> Function URL"},
    "life-platform-site-api-ai": {"window_days": 3, "gap_h": 24, "trigger": "reader /api/ask + /api/board_ask + the AI canary"},
    "health-auto-export-webhook": {"window_days": 3, "gap_h": 8, "trigger": "Health Auto Export phone pushes (HTTP API)"},
    "coach-computation-engine": {
        "window_days": 3,
        "gap_h": 24,
        "trigger": "invoked from the daily-brief coach pipeline (ai/ai_calls.py, emails/daily_brief_lambda.py)",
    },
    "coach-ensemble-digest": {
        "window_days": 3,
        "gap_h": 24,
        "trigger": "invoked from the daily-brief coach pipeline (ai/ai_calls.py, emails/daily_brief_lambda.py)",
    },
    "coach-narrative-orchestrator": {
        "window_days": 3,
        "gap_h": 24,
        "trigger": "invoked from the daily-brief coach pipeline (ai/ai_calls.py, emails/daily_brief_lambda.py)",
    },
    "coach-state-updater": {
        "window_days": 3,
        "gap_h": 24,
        "trigger": "invoked from the daily-brief coach pipeline (ai/ai_calls.py, emails/daily_brief_lambda.py)",
    },
    "coach-quality-gate": {"window_days": 3, "gap_h": 24, "trigger": "fire-and-forget from generation + site-api-ai board answers"},
    "macrofactor-data-ingestion": {
        "window_days": 9,
        "gap_h": 71,
        "trigger": "S3-invoked on an uploads/macrofactor/ export (owner food log)",
    },
    "elena-state-updater": {
        "window_days": 21,
        "gap_h": 168,
        "trigger": "invoked by chronicle-approve (a Function URL the owner clicks) after each chronicle",
    },
}

# ── paused: derived from the source registry's `paused` facet (never hand-typed truth) ──
PAUSED: dict[str, str] = {
    "garmin-data-ingestion": "garmin",  # ADR-074 — the facet is asserted by the census test
}

# ── first scheduled fire still ahead (dated; the row reds itself once overdue) ──
FIRST_DUE: dict[str, dict] = {
    "coach-memoir": {
        "first_due": "2026-10-01",
        "reason": "quarterly cron(0 15 1 1,4,7,10 ? *) added 2026-07-05 (#662), after the July 1 fire — zero invocations "
        "in 440 days is its designed state until the October 1 run.",
    },
}

# ── on-demand: silence carries no information (the census's named residual) ──
ON_DEMAND: dict[str, dict] = {
    "coach-observatory-renderer": {
        "since": "2026-09-23",
        "reason": "no schedule and no in-tree invoker (its docstring names site-api/API Gateway/Step Functions; none call it); last "
        "invocation 2026-05-17 — a retirement-review candidate, not a producer the census can grade.",
    },
    "email-subscriber": {
        "since": "2026-09-23",
        "reason": "reader subscribe/confirm requests only; last invocation 2026-03-26 — silence is a quiet funnel, not a dead producer.",
    },
    "food-delivery-ingestion": {
        "since": "2026-09-23",
        "reason": "S3-invoked on an owner upload (ingestion_stack add_permission s3.amazonaws.com); last invocation 2026-03-28.",
    },
    "insight-email-parser": {
        "since": "2026-09-23",
        "reason": "SES receipt rule on an inbound reply (#2821); last invocation 2026-02-27 — fires only when someone writes in.",
    },
    "life-platform-data-export": {
        "since": "2026-09-23",
        "reason": "no enabled schedule (sentinel_events.py records its targetless out-of-IaC rule, #3279); last invocation 2026-03-05.",
    },
    "progress-viewer": {
        "since": "2026-09-23",
        "reason": "owner-only progress-photo viewer (#4024, deployed 2026-09-22); zero invocations yet by design.",
    },
    "reading-cover-pipeline": {
        "since": "2026-09-23",
        "reason": "invoked from the MCP reading tools (mcp/tools_reading.py) when a book is added; last invocation 2026-07-04.",
    },
    "measurements-ingestion": {
        "since": "2026-09-23",
        "reason": "S3-invoked on an imports/measurements/ upload (ingestion_stack); 3 active days since 2026-06-14, last 2026-09-06.",
    },
    "hevy-routine-cron": {
        "since": "2026-09-23",
        "reason": "its EventBridge rule ships enabled=False (ADR-066); invoked manually — last 2026-08-25.",
    },
}

VERDICT_OK = "ok"
VERDICT_SILENT = "silent"
VERDICT_FIRST_DUE = "first-due"
VERDICT_PAUSED = "paused"
VERDICT_ON_DEMAND = "unmeasured:on-demand"
VERDICT_UNREADABLE = "unreadable-cadence"


# ── population ──────────────────────────────────────────────────────────────


def _load_model(path=MODEL_PATH) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _module_path(dotted: str):
    base = os.path.join(LAMBDAS_DIR, *dotted.split("."))
    for cand in (base + ".py", os.path.join(base, "__init__.py")):
        if os.path.isfile(cand):
            return os.path.relpath(cand, _ROOT).replace(os.sep, "/")
    return None


_IMPORTS: dict[str, set] = {}


def _direct_imports(rel: str) -> set:
    if rel not in _IMPORTS:
        out: set = set()
        try:
            with open(os.path.join(_ROOT, rel), encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
        except (OSError, SyntaxError, UnicodeDecodeError):
            tree = None
        for node in ast.walk(tree) if tree is not None else ():
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for name in names:
                path = _module_path(name)
                if path:
                    out.add(path)
        _IMPORTS[rel] = out
    return _IMPORTS[rel]


def import_closure(rel: str) -> set:
    """Every first-party lambdas/ module reachable from `rel` by level-0 imports."""
    seen, stack = {rel}, [rel]
    while stack:
        for nxt in _direct_imports(stack.pop()):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def emitting_modules() -> dict[str, set]:
    """{module path: {ledger namespace, ...}} for every Python emitter the ledger owns."""
    import emf_namespace_ledger as ledger
    from emf_namespace_discovery import PRODUCER_EMIT

    out: dict[str, set] = {}
    for ns, kinds in ledger.discover_producers().items():
        if ns not in ledger.LEDGER:
            continue
        for mod in kinds.get(PRODUCER_EMIT, ()):
            out.setdefault(mod, set()).add(ns)
    return out


def census_population(model=None, emitters=None) -> dict[str, dict]:
    """{function_name: {"module": ..., "namespaces": [...]}} — every Lambda that can write
    a ledger namespace, through its handler's import closure."""
    model = _load_model() if model is None else model
    emitters = emitting_modules() if emitters is None else emitters
    out = {}
    for fn, rec in sorted((model.get("lambdas") or {}).items()):
        mod = rec.get("module")
        if not mod:
            continue
        namespaces: set = set()
        for m in import_closure(mod):
            namespaces |= emitters.get(m, set())
        if namespaces:
            out[fn] = {"module": mod, "namespaces": sorted(namespaces)}
    return out


def scheduled_cadences() -> dict:
    """{function: fires_per_day | None} from the #3506 resolver."""
    import test_heartbeat_completeness as hb

    return {fn: rate for fn, (rate, _sites) in hb.scheduled_lambda_cadences().items()}


def stale_window_hours(fires_per_day: float) -> float:
    return max(float(STALE_FLOOR_HOURS), 2.0 * 24.0 / fires_per_day + BUCKET_HOURS)


def member_windows(population: dict, cadences: dict) -> dict[str, dict]:
    """{fn: {"class": ..., "window_hours": float|None, ...}} for every member."""
    out = {}
    for fn in population:
        if fn in ON_DEMAND:
            out[fn] = {"class": VERDICT_ON_DEMAND, "window_hours": None}
        elif fn in PAUSED:
            out[fn] = {"class": VERDICT_PAUSED, "window_hours": None, "source": PAUSED[fn]}
        elif fn in EVENT_WINDOWS:
            out[fn] = {"class": "event", "window_hours": EVENT_WINDOWS[fn]["window_days"] * 24.0}
        elif fn in cadences:
            rate = cadences[fn]
            if rate is None or rate <= 0:
                out[fn] = {"class": VERDICT_UNREADABLE, "window_hours": None}
            else:
                out[fn] = {"class": "scheduled", "window_hours": stale_window_hours(rate), "fires_per_day": rate}
                if fn in FIRST_DUE:
                    out[fn]["first_due"] = FIRST_DUE[fn]["first_due"]
        else:
            out[fn] = {"class": "unregistered", "window_hours": None}
    return out


# ── the live read ───────────────────────────────────────────────────────────


def fetch_last_invocations(functions, cw, now, lookback_days=LOOKBACK_DAYS) -> dict:
    """{fn: END of the latest daily bucket with Invocations > 0, or None} — read-only."""
    fns = sorted(functions)
    queries = [
        {
            "Id": f"q{i}",
            "Label": fn,
            "MetricStat": {
                "Metric": {"Namespace": "AWS/Lambda", "MetricName": "Invocations", "Dimensions": [{"Name": "FunctionName", "Value": fn}]},
                "Period": 86400,
                "Stat": "Sum",
            },
        }
        for i, fn in enumerate(fns)
    ]
    last: dict = {fn: None for fn in fns}
    start = now - timedelta(days=lookback_days)
    for i in range(0, len(queries), _MAX_QUERIES_PER_CALL):
        token = None
        while True:
            kwargs = {
                "MetricDataQueries": queries[i : i + _MAX_QUERIES_PER_CALL],
                "StartTime": start,
                "EndTime": now,
                "ScanBy": "TimestampDescending",
            }
            if token:
                kwargs["NextToken"] = token
            resp = cw.get_metric_data(**kwargs)
            for res in resp.get("MetricDataResults", []):
                fn = res.get("Label")
                for ts, val in zip(res.get("Timestamps", []), res.get("Values", [])):
                    if val and val > 0:
                        end = (ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)) + timedelta(hours=BUCKET_HOURS)
                        end = min(end, now)
                        if fn in last and (last[fn] is None or end > last[fn]):
                            last[fn] = end
            token = resp.get("NextToken")
            if not token:
                break
    return last


# ── grading (pure) ──────────────────────────────────────────────────────────


def grade(windows: dict, last_seen: dict, now) -> list[dict]:
    rows = []
    for fn in sorted(windows):
        w = windows[fn]
        seen = last_seen.get(fn)
        age_h = (now - seen).total_seconds() / 3600.0 if seen else None
        row = {"function": fn, "class": w["class"], "window_hours": w["window_hours"], "last_seen_age_hours": age_h}
        if w["class"] in (VERDICT_ON_DEMAND, VERDICT_PAUSED, VERDICT_UNREADABLE):
            row["verdict"] = w["class"]
        elif w["class"] == "unregistered":
            row["verdict"] = VERDICT_UNREADABLE
        else:
            window = w["window_hours"]
            silent = age_h is None or age_h > window
            if silent and w.get("first_due"):
                due = datetime.fromisoformat(w["first_due"]).replace(tzinfo=timezone.utc)
                silent = now > due + timedelta(hours=window)
                row["verdict"] = VERDICT_SILENT if silent else VERDICT_FIRST_DUE
            else:
                row["verdict"] = VERDICT_SILENT if silent else VERDICT_OK
        rows.append(row)
    return rows


def _silent_phrase(row: dict) -> str:
    age = row["last_seen_age_hours"]
    last = "never in the lookback" if age is None else f"last {age / 24:.1f}d ago"
    return f"{row['function']} ({last}, window {row['window_hours'] / 24:.1f}d)"


def summarize(rows: list[dict], read_error=None) -> dict:
    silent = [r for r in rows if r["verdict"] == VERDICT_SILENT]
    unreadable = [r for r in rows if r["verdict"] == VERDICT_UNREADABLE]
    graded = [r for r in rows if r["verdict"] in (VERDICT_OK, VERDICT_SILENT)]
    if read_error or not graded:
        status = "error"
        if not read_error:
            read_error = "zero members graded — a census that grades nothing has not passed (#1189)"
    elif silent:
        status = "drift"
    elif unreadable:
        status = "degraded"
    else:
        status = "clean"
    parts = []
    if read_error:
        parts.append(f"census measured NOTHING this run: {read_error}")
    if silent:
        parts.append("silent past window: " + ", ".join(_silent_phrase(r) for r in silent))
    if unreadable:
        parts.append("no gradable cadence: " + ", ".join(r["function"] for r in unreadable))
    return {
        "status": status,
        "members": len(rows),
        "graded": len(graded),
        "silent": [r["function"] for r in silent],
        "on_demand": sorted(r["function"] for r in rows if r["verdict"] == VERDICT_ON_DEMAND),
        "rows": rows,
        "detail": "; ".join(parts) or f"{len(graded)}/{len(rows)} producers invoked inside their stale window",
    }


def check_producer_census(cw=None, now=None) -> dict:
    """The drift-sentinel leg. Never raises — an unmeasured census is `error`, not clean."""
    now = now or datetime.now(timezone.utc)
    try:
        population = census_population()
        windows = member_windows(population, scheduled_cadences())
    except Exception as e:  # noqa: BLE001
        return {"status": "error", "detail": f"census population/cadence could not be derived ({type(e).__name__}: {e})"}
    try:
        if cw is None:
            import boto3

            cw = boto3.client("cloudwatch", region_name=REGION)
        last = fetch_last_invocations(windows, cw, now)
    except Exception as e:  # noqa: BLE001
        return summarize(grade(windows, {}, now), read_error=f"{type(e).__name__}: {e}")
    return summarize(grade(windows, last, now))


if __name__ == "__main__":  # pragma: no cover — operator convenience, read-only
    result = check_producer_census()
    print(f"{result['status'].upper()}: {result['detail']}")
    for r in result.get("rows", []):
        age = r["last_seen_age_hours"]
        shown = "-" if age is None else f"{age / 24:6.1f}d"
        print(f"  {r['function']:38s} {r['verdict']:22s} last {shown}")
    sys.exit(0 if result["status"] in ("clean", "degraded") else 1)
