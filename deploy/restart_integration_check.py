#!/usr/bin/env python3
"""
restart_integration_check.py — the BEHAVIORAL leg of an experiment restart (#1559).

restart_verify.py asserts STATE (constants, profile, phase tags); this script proves
the pipelines still FLOW after a wipe/re-anchor. Every reset so far surfaced a Day-1
behavioral bug only when a cron fired hours later (the genesis-eve _clamp_today 500,
the Sunday-digest present-None DLQ crash ×10, /coaching/ missing its static core,
evening_ritual adoption resets). One command, four legs, one honest verdict:

  ingestion  — every source in lambdas/source_registry.py proves it flows: scheduled
               sources via a real bounded invoke (the same gap-aware run their cron
               does hourly — assert invoke success + freshness vs the registry's own
               staleness threshold, or an honest documented no-data), paused /
               event-driven sources SKIP with the registry-derived reason. The HAE
               webhook gets a healthcheck invoke always, and a full synthetic-payload
               round-trip under --synthetic (see below).
  compute    — the 4 daily compute lambdas healthcheck-invoked (boot, perms, bundle);
               with --deep they force-recompute today's records and the results are
               shape-asserted (character sheet level >= 1; a first post-genesis sheet
               is the honest Level-1 baseline). hypothesis-engine is NEVER live-invoked
               (weekly full-sweep + Bedrock cost + no healthcheck branch) — its cron
               and partition are asserted instead, skip stated. Receipts: the newest
               character sheet's receipt must be replay_verified (or honestly absent
               when no progression transitions occurred — ADR-104, never fabricated).
               Fulfillment: /api/fulfillment_index must serve either a scored day or
               the honest insufficient_signal state (never a fabricated score).
  serving    — the full qa_manifest smoke surface (path + expected status, the same
               facet deploy/smoke_test_site.sh consumes) fetched cache-busted; the
               daily-brief email dry-runs for real ({"dry_run": true} — the only email
               lambda with a no-send mode); the other six are covered by the STATIC
               present-None gate: scan_present_none_hazards() fails on any unguarded
               `.get(f"pillar_...", {})` / `.get("pillars", {})` chain read in
               lambdas/emails/ — the exact genesis-week crash class
               (reference_genesis_week_present_none; weekly-digest #1540 was fixed at
               one site while three siblings kept the pattern). tests/
               test_restart_integration_check.py runs the same scan in CI, so the
               class stays closed between resets.
  ops        — ingestion DLQ depth 0, no CloudWatch alarm firing outside the stated
               allowlist, every non-paused scheduled source's lambda has an ENABLED
               EventBridge rule (and paused sources have none), SSM
               /life-platform/experiment-cycle matches --expect-cycle when given.

Synthetic webhook round-trip (--synthetic, ADR-104 discipline):
  POSTs an unmistakably-tagged payload (date 2099-01-01, source "IntegrationTest",
  integration_test marker in the body) through the REAL HAE endpoint: water with a
  duplicated reading (proves reading-level dedup — the total must count the distinct
  readings only), CGM, blood pressure, then a second identical POST (totals must NOT
  change), then State of Mind. Asserts the normalized DDB row, then deletes it and
  verifies the delete. HONEST CAVEAT: every live webhook invocation unconditionally
  archives its raw payload under the delete-protected raw/ prefix
  (raw/matthew/health_auto_export/<now>.json + per-domain 2099/01/01.json merge-on-
  write sub-archives). Those objects cannot be deleted by matthew-admin and are left
  behind DELIBERATELY at an impossible date so they can never masquerade as real
  readings; the check prints every orphan key it created. The serving DDB layer is
  left clean — that is the ADR-104 line this check holds.

Usage:
  python3 deploy/restart_integration_check.py                  # probe mode (harness proof / post-reset)
  python3 deploy/restart_integration_check.py --deep --synthetic --expect-cycle 9
                                                               # the full post-reset execution
  python3 deploy/restart_integration_check.py --skip-serving --allow-alarm <name>

Dry-running this against the LIVE current cycle before a reset proves the harness
itself (#1559 AC) — every leg is either read-only, write-idempotent (the same invokes
the crons make), or synthetic-tagged-and-cleaned.

Exit 0 = no FAIL rows. SKIP rows always carry a reason — silence is not a pass.
Runbook: docs/RUNBOOK.md "Experiment restart"; taxonomy: docs/PHASE_TAXONOMY.md.
"""

import argparse
import concurrent.futures
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

REGION = "us-west-2"
TABLE = "life-platform"
USER = "matthew"
API = "https://averagejoematt.com"
SSM_CYCLE_PARAM = "/life-platform/experiment-cycle"
DLQ_NAME = "life-platform-ingestion-dlq"
SYNTHETIC_DATE = "2099-01-01"  # impossible-by-design: can never collide with a real day
SYNTHETIC_SOURCE = "IntegrationTest"

# source_registry has no lambda-name facet — this map mirrors cdk/stacks/ingestion_stack.py
# (validated against SOURCE_REGISTRY keys by tests/test_restart_integration_check.py).
SOURCE_FN = {
    "whoop": "whoop-data-ingestion",
    "withings": "withings-data-ingestion",
    "strava": "strava-data-ingestion",
    "eightsleep": "eightsleep-data-ingestion",
    "todoist": "todoist-data-ingestion",
    "habitify": "habitify-data-ingestion",
    "hevy": "hevy-backfill",
    "notion": "notion-journal-ingestion",
    "weather": "weather-data-ingestion",
    "garmin": "garmin-data-ingestion",
    "dropbox": "dropbox-poll",
    "apple_health": "health-auto-export-webhook",
    "macrofactor": "macrofactor-data-ingestion",
    "measurements": "measurements-ingestion",
    "food_delivery": "food-delivery-ingestion",
}

COMPUTE_HEALTHCHECK_FNS = [
    "character-sheet-compute",
    "adaptive-mode-compute",
    "daily-metrics-compute",
    "daily-insight-compute",
]

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"


class Report:
    """Accumulates (leg, name, status, detail) rows; renders the summary table."""

    def __init__(self):
        self.rows = []

    def add(self, leg, name, status, detail=""):
        self.rows.append((leg, name, status, detail))
        icon = {PASS: "\033[92m✓\033[0m", FAIL: "\033[91m✗\033[0m", SKIP: "\033[93m→\033[0m"}[status]
        print(f"  {icon} [{leg}] {name}" + (f" — {detail}" if detail else ""))

    def counts(self):
        c = {PASS: 0, FAIL: 0, SKIP: 0}
        for _, _, s, _ in self.rows:
            c[s] += 1
        return c

    def render_table(self):
        lines = ["", "═" * 76, "  RESTART INTEGRATION CHECK — summary", "═" * 76]
        for leg in ("ingestion", "compute", "serving", "ops", "synthetic"):
            leg_rows = [r for r in self.rows if r[0] == leg]
            if not leg_rows:
                continue
            lines.append(f"  {leg}:")
            for _, name, status, detail in leg_rows:
                lines.append(f"    {status:<4} {name}" + (f" — {detail}" if detail else ""))
        c = self.counts()
        lines.append("─" * 76)
        lines.append(f"  {c[PASS]} pass · {c[FAIL]} fail · {c[SKIP]} skipped-with-reason")
        lines.append("═" * 76)
        return "\n".join(lines)

    @property
    def failed(self):
        return self.counts()[FAIL] > 0


# ──────────────────────────────────────────────────────────────────────────────
# Pure helpers (unit-tested offline — no AWS, no network)
# ──────────────────────────────────────────────────────────────────────────────

# The genesis-week present-None class: a dict-default chain read on character-sheet
# pillar sub-dicts. `d.get("pillar_x", {})` returns None (not {}) when the key is
# present with a None value — the writer itself acknowledges this shape
# (lambdas/compute/character_sheet_lambda.py uses `rec.get(f"pillar_{p}") or {}`).
# The guarded idiom `(d.get(k) or {})` never matches this pattern.
_PRESENT_NONE_HAZARD = re.compile(r"""\.get\(\s*(?:f?"pillar_[^"]*"|f?'pillar_[^']*'|"pillars"|'pillars')\s*,\s*\{\}\s*\)""")


def scan_present_none_hazards(text, path="<memory>"):
    """Return [(path, lineno, line)] for every unguarded pillar chain-read."""
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        if _PRESENT_NONE_HAZARD.search(line):
            hits.append((path, i, line.strip()))
    return hits


def scan_email_lambdas(email_dir=None):
    """Run the present-None scan over every email lambda source file."""
    email_dir = email_dir or os.path.join(REPO, "lambdas", "emails")
    hits = []
    for fn in sorted(os.listdir(email_dir)):
        if not fn.endswith(".py"):
            continue
        p = os.path.join(email_dir, fn)
        with open(p, encoding="utf-8") as f:
            hits.extend(scan_present_none_hazards(f.read(), os.path.relpath(p, REPO)))
    return hits


def build_ingestion_plan(registry, fn_map=None):
    """Classify every registry source into probe / skip-with-reason. Pure.

    Returns {source: ("probe", fn_name) | ("healthcheck", fn_name) | ("skip", reason)}.
    """
    fn_map = fn_map or SOURCE_FN
    plan = {}
    for src, facets in registry.items():
        fn = fn_map.get(src)
        if facets.get("paused"):
            plan[src] = ("skip", f"paused in source_registry ({facets.get('paused_reason', 'see registry comment')})")
        elif src == "apple_health":
            plan[src] = ("healthcheck", fn)  # webhook — full flow only via --synthetic
        elif src in ("macrofactor", "measurements", "food_delivery"):
            plan[src] = ("skip", "event-driven (S3/MCP trigger, no cron) — no bounded-fetch invoke shape")
        elif src == "supplements":
            plan[src] = ("skip", "registry-resident facets only — sourced inside the habitify pipeline")
        elif fn:
            plan[src] = ("probe", fn)
        else:
            plan[src] = ("skip", "no lambda mapping — extend SOURCE_FN if this source grew a function")
    return plan


def synthetic_water_expected_ml():
    """The dedup contract the synthetic payload proves: two readings share a
    timestamp (only one may count), one is distinct → 100 + 250."""
    return 350.0


def build_synthetic_metrics_payload():
    """The HAE-shaped synthetic payload (water dedup + CGM + BP). Tagged so it can
    never masquerade as real data (ADR-104): impossible date + source marker."""
    d = SYNTHETIC_DATE
    return {
        "integration_test": True,  # marker rides the archived raw payload too
        "data": {
            "metrics": [
                {
                    "name": "Water",
                    "units": "ml",
                    "data": [
                        {"date": f"{d} 08:00:00 -0800", "qty": 100, "source": SYNTHETIC_SOURCE},
                        {"date": f"{d} 08:00:00 -0800", "qty": 100, "source": SYNTHETIC_SOURCE},  # dup ts — must dedup
                        {"date": f"{d} 09:00:00 -0800", "qty": 250, "source": SYNTHETIC_SOURCE},
                    ],
                },
                {
                    "name": "Blood Glucose",
                    "units": "mg/dL",
                    "data": [
                        {"date": f"{d} 08:05:00 -0800", "qty": 95},
                        {"date": f"{d} 08:10:00 -0800", "qty": 101},
                    ],
                },
                {
                    "name": "Blood Pressure",
                    "data": [{"date": f"{d} 08:15:00 -0800", "systolic": 120, "diastolic": 80, "pulse": 60}],
                },
            ],
            "workouts": [],
        },
    }


def build_synthetic_som_payload():
    return {
        "integration_test": True,
        "data": {
            "stateOfMind": [
                {
                    "date": f"{SYNTHETIC_DATE} 08:00:00 -0800",  # NOT evening: -0800 evening rolls into the next UTC day (leaked a 2099-01-02 row on first execution)
                    "valence": 0.5,
                    "kind": "dailyMood",
                    "labels": ["integration_test"],
                    "associations": [],
                    "source": SYNTHETIC_SOURCE,
                }
            ]
        },
    }


def freshness_verdict(latest_date_iso, stale_hours, now=None):
    """(status, detail) for a source's newest DATE# row vs its own registry
    threshold — the same line the freshness checker draws. None → honest no-data."""
    if latest_date_iso is None:
        return ("no-data", "no DATE# rows in partition")
    now = now or datetime.now(timezone.utc)
    age_h = (now - datetime.fromisoformat(latest_date_iso).replace(tzinfo=timezone.utc)).total_seconds() / 3600
    stale_hours = stale_hours or 48
    if age_h <= stale_hours:
        return ("fresh", f"latest {latest_date_iso}, {age_h:.0f}h old (threshold {stale_hours}h)")
    return ("stale", f"latest {latest_date_iso}, {age_h:.0f}h old > {stale_hours}h threshold")


# ──────────────────────────────────────────────────────────────────────────────
# AWS-touching legs (lazy clients — module import stays offline-safe for tests)
# ──────────────────────────────────────────────────────────────────────────────


def _clients():
    import boto3
    from botocore.config import Config

    cfg = Config(read_timeout=310, retries={"max_attempts": 2})
    lam = boto3.client("lambda", region_name=REGION, config=cfg)
    ddb = boto3.resource("dynamodb", region_name=REGION)
    return lam, ddb.Table(TABLE)


def _invoke(lam, fn, payload):
    """Invoke a lambda; return (ok, detail). ok = no FunctionError + statusCode
    (when the handler returns one) is 2xx."""
    try:
        resp = lam.invoke(FunctionName=fn, Payload=json.dumps(payload).encode())
    except Exception as e:
        return False, f"invoke error: {str(e)[:120]}"
    if resp.get("FunctionError"):
        body = resp["Payload"].read()[:200]
        return False, f"FunctionError {resp['FunctionError']}: {body}"
    try:
        out = json.loads(resp["Payload"].read() or b"null")
    except Exception:
        out = None
    if isinstance(out, dict) and "statusCode" in out and not (200 <= int(out["statusCode"]) < 300):
        return False, f"handler statusCode {out['statusCode']}: {str(out.get('body'))[:150]}"
    return True, "invoked clean"


def _latest_date_row(table, source):
    from boto3.dynamodb.conditions import Key

    r = table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{USER}#SOURCE#{source}") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = r.get("Items", [])
    if not items:
        return None
    # notion-style sks carry suffixes (DATE#YYYY-MM-DD#journal#...) — take the date segment
    return items[0]["sk"].split("#")[1]


def leg_ingestion(report, args):
    import lambdas.source_registry as sr

    lam, table = _clients()
    registry = sr.SOURCE_REGISTRY
    plan = build_ingestion_plan(registry)
    stale_overrides = {}
    try:
        stale_overrides = sr.stale_hours_overrides()
    except Exception:
        pass

    probes = {s: fn for s, (kind, fn) in plan.items() if kind == "probe"}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futures = {s: ex.submit(_invoke, lam, fn, {}) for s, fn in probes.items()}
        results = {s: f.result() for s, f in futures.items()}

    for src, (kind, val) in sorted(plan.items()):
        if kind == "skip":
            report.add("ingestion", src, SKIP, val)
            continue
        if kind == "healthcheck":
            ok, detail = _invoke(lam, val, {"healthcheck": True})
            report.add("ingestion", f"{src} (webhook healthcheck)", PASS if ok else FAIL, detail)
            continue
        ok, detail = results[src]
        if not ok:
            report.add("ingestion", src, FAIL, detail)
            continue
        facets = registry.get(src, {})
        if facets.get("partition") is False or facets.get("freshness") is False:
            report.add("ingestion", src, PASS, "invoked clean (no freshness surface by design — partition/freshness False in the registry)")
            continue
        latest = _latest_date_row(table, src)
        verdict, fdetail = freshness_verdict(latest, stale_overrides.get(src))
        if verdict == "fresh":
            report.add("ingestion", src, PASS, fdetail)
        elif registry.get(src, {}).get("hae_datatypes") or _is_manualish(registry.get(src, {})):
            report.add("ingestion", src, PASS, f"invoked clean; honest no-data ({fdetail}; manual/human-side source)")
        else:
            # invoke succeeded but the partition is stale past the source's own line —
            # the pipeline flows, the provider/device does not. Documented, not hidden.
            report.add("ingestion", src, FAIL, f"invoked clean BUT {fdetail} — provider/device-side gap needs a human look")


def _is_manualish(facets):
    ch = facets.get("engagement_channel") or {}
    return bool(facets.get("manual") or ch.get("manual") or facets.get("capture_channel") in ("mcp", "hae"))


def leg_compute(report, args):
    lam, table = _clients()
    from boto3.dynamodb.conditions import Key

    for fn in COMPUTE_HEALTHCHECK_FNS:
        ok, detail = _invoke(lam, fn, {"healthcheck": True})
        report.add("compute", f"{fn} healthcheck", PASS if ok else FAIL, detail)

    if args.deep:
        today = datetime.now(timezone.utc).date().isoformat()
        for fn in ("character-sheet-compute", "daily-metrics-compute", "daily-insight-compute"):
            ok, detail = _invoke(lam, fn, {"date": today, "force": True})
            report.add("compute", f"{fn} force({today})", PASS if ok else FAIL, detail)
        ok, detail = _invoke(lam, "adaptive-mode-compute", {"date": today})
        report.add("compute", f"adaptive-mode-compute ({today})", PASS if ok else FAIL, detail)

    report.add(
        "compute",
        "hypothesis-engine",
        SKIP,
        "never live-invoked by design: weekly full-sweep + Bedrock cost, no healthcheck branch — cron asserted in ops leg",
    )

    # Newest character sheet: honest shape + receipt discipline (ADR-104)
    r = table.query(
        KeyConditionExpression=Key("pk").eq(f"USER#{USER}#SOURCE#character_sheet") & Key("sk").begins_with("DATE#"),
        ScanIndexForward=False,
        Limit=1,
    )
    items = [it for it in r.get("Items", []) if not it.get("tombstone")]
    if not items:
        report.add("compute", "character sheet shape", FAIL, "no untombstoned character_sheet rows at all")
    else:
        sheet = items[0]
        lvl = sheet.get("character_level")
        lvl_f = float(lvl) if isinstance(lvl, (int, float, Decimal)) else None
        if lvl_f is not None and lvl_f >= 1:
            report.add(
                "compute", "character sheet shape", PASS, f"{sheet['sk']} level {lvl_f:g} (Level-1 baseline is the honest Day-0 shape)"
            )
        else:
            report.add("compute", "character sheet shape", FAIL, f"{sheet['sk']} character_level={lvl!r} — below the Level-1 floor")
        rec = table.get_item(Key={"pk": f"USER#{USER}#SOURCE#character_receipt", "sk": sheet["sk"]}).get("Item")
        if rec is None:
            report.add(
                "compute", "progression receipt", PASS, f"none for {sheet['sk']} — honest absence (no transitions; never fabricated)"
            )
        elif rec.get("replay_verified"):
            report.add("compute", "progression receipt", PASS, f"{sheet['sk']} replay_verified=True")
        else:
            report.add(
                "compute", "progression receipt", FAIL, f"{sheet['sk']} receipt exists but replay_verified={rec.get('replay_verified')!r}"
            )

    # Fulfillment index: scored or honestly insufficient — never a fabricated number
    try:
        with urllib.request.urlopen(f"{API}/api/fulfillment_index?cb=integ{int(time.time())}", timeout=20) as resp:
            fi = json.loads(resp.read())
        days = fi.get("days") or fi.get("recent_days") or []
        state = (days[-1].get("state") if days else fi.get("state")) or "unknown"
        if state == "insufficient_signal":
            has_score = bool(days and "score" in days[-1])
            if has_score:
                report.add("compute", "fulfillment index", FAIL, "insufficient_signal day carries a score key — fabricated number")
            else:
                report.add("compute", "fulfillment index", PASS, "insufficient_signal with no score key — honest under-coverage state")
        elif state == "unknown":
            report.add("compute", "fulfillment index", PASS, f"served (no per-day state field; keys={sorted(fi)[:6]})")
        else:
            report.add("compute", "fulfillment index", PASS, f"latest day state={state}")
    except Exception as e:
        report.add("compute", "fulfillment index", FAIL, f"/api/fulfillment_index unreachable: {str(e)[:100]}")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # the manifest's expected status is the RAW status (301 pages must report 301,
    # exactly like smoke_test_site.sh's redirect-less curl) — never auto-follow
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _fetch_status(path_expected):
    path, name, expected = path_expected
    url = f"{API}{path}{'&' if '?' in path else '?'}cb=integ{int(time.time())}"
    req = urllib.request.Request(url, headers={"User-Agent": "restart-integration-check/1559"})
    try:
        with _OPENER.open(req, timeout=25) as resp:
            return path, name, expected, resp.status
    except urllib.error.HTTPError as e:
        return path, name, expected, e.code
    except Exception:
        return path, name, expected, 0


def leg_serving(report, args):
    import subprocess

    out = subprocess.run(
        ["python3", os.path.join(REPO, "tests", "qa_manifest.py"), "--emit", "smoke"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = []
    for line in out.strip().splitlines():
        parts = line.split("|")
        if len(parts) >= 3:
            rows.append((parts[0], parts[1], parts[2]))
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        for path, name, expected, got in ex.map(_fetch_status, rows):
            expected_codes = {int(x) for x in re.findall(r"\d{3}", expected)} or {200}
            if got not in expected_codes:
                failures.append(f"{path} expected {expected} got {got}")
    if failures:
        report.add("serving", f"qa_manifest smoke ({len(rows)} urls)", FAIL, "; ".join(failures[:5]) + (" …" if len(failures) > 5 else ""))
    else:
        report.add("serving", f"qa_manifest smoke ({len(rows)} urls)", PASS, "every path served its expected status")

    if args.brief_full:
        import boto3
        from botocore.config import Config

        # a full generation runs 7.5-15+ min (fn timeout 900) and costs one brief's Bedrock
        # tokens — deliberate, once per reset, never casually (the first execution tripped
        # the ai-tokens-daily-brief-daily alarm on repeated runs).
        brief_lam = boto3.client("lambda", region_name=REGION, config=Config(read_timeout=910, retries={"max_attempts": 1}))
        ok, detail = _invoke(brief_lam, "daily-brief", {"dry_run": True})
        report.add("serving", "daily-brief dry-run (no-send, full generation)", PASS if ok else FAIL, detail)
    else:
        report.add(
            "serving",
            "daily-brief dry-run",
            SKIP,
            "full generation costs a brief's Bedrock tokens + up to 15 min — pass --brief-full (reset runs); "
            "the invoke/boot path is covered by the compute healthchecks and the next 17:00 UTC brief is the standing proof",
        )

    hits = scan_email_lambdas()
    if hits:
        sample = "; ".join(f"{p}:{ln}" for p, ln, _ in hits[:6])
        report.add(
            "serving",
            f"email present-None gate ({len(hits)} hazard(s))",
            FAIL,
            f"unguarded pillar chain-reads (genesis-week crash class): {sample}" + (" …" if len(hits) > 6 else ""),
        )
    else:
        report.add("serving", "email present-None gate", PASS, "no unguarded pillar chain-reads in lambdas/emails/")


def leg_ops(report, args):
    import boto3

    import lambdas.source_registry as sr

    sqs = boto3.client("sqs", region_name=REGION)
    try:
        url = sqs.get_queue_url(QueueName=DLQ_NAME)["QueueUrl"]
        depth = int(
            sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["ApproximateNumberOfMessages"])["Attributes"][
                "ApproximateNumberOfMessages"
            ]
        )
        report.add("ops", "ingestion DLQ depth", PASS if depth == 0 else FAIL, f"{depth} message(s)")
    except Exception as e:
        report.add("ops", "ingestion DLQ depth", FAIL, f"queue lookup failed: {str(e)[:100]}")

    cw = boto3.client("cloudwatch", region_name=REGION)
    firing, token = [], None
    while True:
        kw = {"StateValue": "ALARM", "MaxRecords": 100}
        if token:
            kw["NextToken"] = token
        page = cw.describe_alarms(**kw)
        firing += [a["AlarmName"] for a in page.get("MetricAlarms", [])] + [a["AlarmName"] for a in page.get("CompositeAlarms", [])]
        token = page.get("NextToken")
        if not token:
            break
    allowed = set(args.allow_alarm or [])
    unexpected = [a for a in firing if a not in allowed]
    waived = [a for a in firing if a in allowed]
    detail = ""
    if waived:
        detail = f"waived (stated allowlist): {', '.join(waived)}"
    if unexpected:
        report.add("ops", "cloudwatch alarms", FAIL, f"firing: {', '.join(unexpected[:6])}" + (f" | {detail}" if detail else ""))
    else:
        report.add("ops", "cloudwatch alarms", PASS, detail or "none firing")

    # EventBridge: every non-paused scheduled source fn has >=1 ENABLED rule targeting it;
    # paused sources must have none (the I24 list_rules+targets sweep, no name pinning).
    eb = boto3.client("events", region_name=REGION)
    fn_rules = {}
    token = None
    while True:
        kw = {"NextToken": token} if token else {}
        page = eb.list_rules(Limit=100, **kw)
        for rule in page.get("Rules", []):
            if rule.get("State") != "ENABLED":
                continue
            for tgt in eb.list_targets_by_rule(Rule=rule["Name"]).get("Targets", []):
                arn = tgt.get("Arn", "")
                if ":function:" in arn:
                    fn_rules.setdefault(arn.rsplit(":", 1)[-1], []).append(rule["Name"])
        token = page.get("NextToken")
        if not token:
            break

    plan = build_ingestion_plan(sr.SOURCE_REGISTRY)
    missing, wrongly_armed = [], []
    for src, (kind, fn) in plan.items():
        if kind == "probe" and fn not in fn_rules:
            missing.append(f"{src}→{fn}")
        if kind == "skip" and "paused" in str(fn) and SOURCE_FN.get(src) in fn_rules:
            wrongly_armed.append(f"{src}→{SOURCE_FN[src]}")
    for fn in COMPUTE_HEALTHCHECK_FNS + ["hypothesis-engine", "daily-brief"]:
        if fn not in fn_rules:
            missing.append(fn)
    if missing or wrongly_armed:
        bits = []
        if missing:
            bits.append(f"no ENABLED rule for: {', '.join(missing)}")
        if wrongly_armed:
            bits.append(f"paused source has an armed rule: {', '.join(wrongly_armed)}")
        report.add("ops", "eventbridge crons armed", FAIL, "; ".join(bits))
    else:
        report.add("ops", "eventbridge crons armed", PASS, f"{len(fn_rules)} enabled-rule targets swept")

    ssm = boto3.client("ssm", region_name=REGION)
    try:
        cycle = ssm.get_parameter(Name=SSM_CYCLE_PARAM)["Parameter"]["Value"]
        if args.expect_cycle is not None:
            ok = str(args.expect_cycle) == cycle
            report.add("ops", "SSM experiment-cycle", PASS if ok else FAIL, f"live={cycle} expected={args.expect_cycle}")
        else:
            report.add("ops", "SSM experiment-cycle", PASS, f"live={cycle} (no --expect-cycle given — reported, not asserted)")
    except Exception as e:
        report.add("ops", "SSM experiment-cycle", FAIL, str(e)[:100])


def leg_synthetic(report, args):
    """The full HAE round-trip. Live writes: one DDB row (deleted + verified) and
    delete-protected raw/ archives at the impossible date (printed honestly)."""
    import boto3

    cfn = boto3.client("cloudformation", region_name=REGION)
    endpoint = None
    for out in cfn.describe_stacks(StackName="LifePlatformIngestion")["Stacks"][0].get("Outputs", []):
        if out["OutputKey"] == "HaeWebhookApiEndpoint":
            endpoint = out["OutputValue"].rstrip("/")
    if not endpoint:
        report.add("synthetic", "endpoint discovery", FAIL, "HaeWebhookApiEndpoint output not found on LifePlatformIngestion")
        return
    sm = boto3.client("secretsmanager", region_name=REGION)
    keys = json.loads(sm.get_secret_value(SecretId="life-platform/ingestion-keys")["SecretString"])
    api_key = keys.get("health_auto_export_api_key") or keys.get("api_key")

    def post(payload):
        req = urllib.request.Request(
            f"{endpoint}/ingest",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=310) as resp:
            return resp.status

    _, table = _clients()
    key = {"pk": f"USER#{USER}#SOURCE#apple_health", "sk": f"DATE#{SYNTHETIC_DATE}"}
    pre = table.get_item(Key=key).get("Item")
    if pre is not None:
        table.delete_item(Key=key)  # a prior aborted run left its row — clear before proving

    status = post(build_synthetic_metrics_payload())
    row = table.get_item(Key=key).get("Item") or {}
    water = float(row.get("water_intake_ml") or 0)
    cgm_n = int(row.get("blood_glucose_readings_count") or 0)
    bp_sys = row.get("bp_systolic") or row.get("blood_pressure_systolic")
    ok1 = status == 200 and abs(water - synthetic_water_expected_ml()) < 0.01 and cgm_n == 2 and bp_sys is not None
    report.add(
        "synthetic",
        "webhook POST + normalization + dedup",
        PASS if ok1 else FAIL,
        f"http {status}; water {water}ml (expect {synthetic_water_expected_ml():g}, dup ts collapsed); cgm n={cgm_n}; bp_sys={bp_sys}",
    )

    status2 = post(build_synthetic_metrics_payload())  # idempotent re-send
    row2 = table.get_item(Key=key).get("Item") or {}
    water2 = float(row2.get("water_intake_ml") or 0)
    ok2 = status2 == 200 and abs(water2 - water) < 0.01
    report.add(
        "synthetic",
        "idempotent re-send (reading-level dedup)",
        PASS if ok2 else FAIL,
        f"water after re-send: {water2}ml (must equal {water}ml)",
    )

    status3 = post(build_synthetic_som_payload())
    row3 = table.get_item(Key=key).get("Item") or {}
    som_n = int(row3.get("som_check_in_count") or 0)
    if som_n == 0:  # tz-drift fallback — check the next-UTC-day row before failing
        alt = table.get_item(Key={"pk": key["pk"], "sk": "DATE#2099-01-02"}).get("Item") or {}
        som_n = int(alt.get("som_check_in_count") or 0)
    report.add(
        "synthetic",
        "state-of-mind normalization",
        PASS if (status3 == 200 and som_n >= 1) else FAIL,
        f"http {status3}; som_check_in_count={som_n}",
    )

    keys = [key, {"pk": key["pk"], "sk": "DATE#2099-01-02"}]  # tz-rollover belt: an -0800 evening ts lands next UTC day
    for k in keys:
        table.delete_item(Key=k)
    gone = all(table.get_item(Key=k).get("Item") is None for k in keys)
    report.add(
        "synthetic", "cleanup verified", PASS if gone else FAIL, "DDB rows DATE#2099-01-01 + DATE#2099-01-02 deleted and confirmed absent"
    )
    now = datetime.now(timezone.utc)
    print(
        "  ⚠ honest residue (delete-protected raw/ prefix, isolated at the impossible date):\n"
        f"     raw/{USER}/health_auto_export/{now:%Y/%m}/… (3 payload archives from this run)\n"
        f"     raw/{USER}/cgm_readings/2099/01/01.json · raw/{USER}/blood_pressure/2099/01/01.json · "
        f"raw/{USER}/state_of_mind/2099/01/01.json (merge-on-write — stable across runs)"
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--deep", action="store_true", help="force-recompute today's daily compute records (post-reset mode)")
    ap.add_argument("--synthetic", action="store_true", help="run the HAE synthetic webhook round-trip (tagged writes + verified cleanup)")
    ap.add_argument(
        "--brief-full", action="store_true", help="synchronous full daily-brief dry-run (Bedrock cost + up to 15 min; reset runs)"
    )
    ap.add_argument("--expect-cycle", type=int, default=None, help="assert SSM /life-platform/experiment-cycle equals this")
    ap.add_argument("--allow-alarm", action="append", help="alarm name(s) allowed to be firing (stated exemptions; repeatable)")
    for leg in ("ingestion", "compute", "serving", "ops"):
        ap.add_argument(f"--skip-{leg}", action="store_true")
    args = ap.parse_args()

    report = Report()
    t0 = time.time()
    print("restart_integration_check (#1559) — behavioral verification, four legs\n")
    if not args.skip_ingestion:
        print("── ingestion ──")
        leg_ingestion(report, args)
    if not args.skip_compute:
        print("── compute ──")
        leg_compute(report, args)
    if not args.skip_serving:
        print("── serving ──")
        leg_serving(report, args)
    if not args.skip_ops:
        print("── ops ──")
        leg_ops(report, args)
    if args.synthetic:
        print("── synthetic webhook round-trip ──")
        leg_synthetic(report, args)

    print(report.render_table())
    print(f"  completed in {time.time() - t0:.0f}s")
    sys.exit(1 if report.failed else 0)


if __name__ == "__main__":
    main()
