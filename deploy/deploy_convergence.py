#!/usr/bin/env python3
"""deploy/deploy_convergence.py — the deploy-race false-positive class's OWNER (#2978).

WHY THIS FILE EXISTS. Five per-symptom issues (#1526 stale-edge invalidation,
#1931 leak-sweep connection reset, #1917 vitals aggregates, #2051 synthetic-row
auto-revert, #1911 inference_receipt timeout) were each closed COMPLETED, and the
measured rate of the class they belonged to went UP: 14 rows in July (1 per
2.2 days) -> 15 rows in 2026-08-01..22 (1 per 1.5 days). Nothing owned the class,
so every recurrence looked novel and got its own symptom fix.

The class has one shape. A post-deploy check runs while the deploy is FINISHED but
the system has not CONVERGED — the CDN edge still serves the prior object, the
site-api half of a change is not deployed yet, a just-updated Lambda has not paid
its cold start. The check is measuring the pre-deploy world and reporting it as a
verdict on the post-deploy one. Every fix so far has been "sleep a bit / retry a
bit", which is a guess about a duration; the 2026-07-19 05:40Z `sleep 60` lost the
race and auto-rolled back a healthy deploy.

THE STRUCTURAL ANSWER, and the two halves that make it falsifiable:

  1. **Convergence is a SIGNAL, not a duration.** Every window below names the
     observable that proves it closed — a viewer-path fingerprint match, a route
     answering, a warm container — and the gate WAITS ON THAT SIGNAL with a
     bounded budget instead of sleeping a guessed number of seconds. When the
     signal says converged (the common case: first poll, zero sleeps) the checks
     run against the world they are supposed to be judging.

  2. **A window must be DECLARED to excuse anything.** A failure inside an open,
     declared window is `raced` — rerun after convergence, never a red. A failure
     with every relevant window converged or closed is `real` and fails hard. An
     UNDECLARED ordering risk is a CLOSED window, so it excuses nothing: that is
     precisely the 2026-08-25 20:43Z merge-train rollback, where the statics
     deployed ahead of a not-yet-deployed site-api with no
     `pending_deploy_routes` entry declaring it. That rollback was CORRECT and
     must stay correct — `tests/test_deploy_convergence_2978.py` pins its
     timeline as a fixture.

  3. **Cannot-verify is never verified (#2578).** A convergence signal that is
     unreachable, unparseable or still pending past its budget yields
     `unverified`, which fails LOUDLY. The one thing this module may never do is
     turn an unreadable signal into a pass.

WHAT THIS IS NOT. It is not a retry library — `deploy/lib/resilient_curl.sh`
(transport retries, #1911) and `deploy/lib/cache_aware_fetch.sh` (bounded content
re-fetch, #1526) already cover the residue and stay exactly as they are. This is
the layer above them: it decides, from the deploy pipeline's own timestamps and
signals, whether a red is evidence about the deploy at all.

USAGE
    python3 deploy/deploy_convergence.py --table
    python3 deploy/deploy_convergence.py await --base https://averagejoematt.com \\
        --expect-build "$GITHUB_SHA"            # exit 0 converged / 2 pending / 3 unavailable

Consumers: `deploy/smoke_test_site.sh` (SMOKE_EXPECT_BUILD) and
`tests/visual_qa.py` (VISUAL_QA_EXPECT_BUILD), both wired from
`.github/workflows/site-deploy.yml`.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
API_SEQUENCING_REGISTRY = os.path.join(_HERE, "api_deploy_sequencing.json")

# ── dispositions ─────────────────────────────────────────────────────────────
RACED = "raced"  # failed inside an OPEN declared window — rerun after convergence
REAL = "real"  # every relevant window converged or closed — fail hard
UNVERIFIED = "unverified"  # a convergence signal could not be read — fail LOUDLY (#2578)

# ── convergence-signal states ────────────────────────────────────────────────
CONVERGED = "converged"  # the signal proves the window closed
PENDING = "pending"  # the signal proves the window is still open
CLOSED = "closed"  # the window never opened for this deploy (nothing declared it)
UNAVAILABLE = "unavailable"  # the signal itself could not be read

# ── the kinds of check a window can falsify ──────────────────────────────────
EDGE_CONTENT = "edge_content"  # body/marker assertions on same-deploy statics
API_ROUTE = "api_route"  # HTTP status/JSON health of an /api/* route
COLD_LATENCY = "cold_latency"  # timeout / first-hit 5xx on a just-updated Lambda
SEMANTIC = "semantic"  # an AI/reader-truth verdict about published content

CHECK_KINDS = (EDGE_CONTENT, API_ROUTE, COLD_LATENCY, SEMANTIC)

# The CloudWatch namespace. Deliberately the EXISTING QA namespace rather than a
# new one — #2837's whole finding is that namespaces were minted ad hoc until the
# invoice was the only detector, and a deploy-gate disposition is a QA-gate fact.
# Registered in deploy/emf_namespace_ledger.py.
METRIC_NAMESPACE = "LifePlatform/QA"
METRIC_BY_DISPOSITION = {
    RACED: "DeployRaceRaced",
    REAL: "DeployRaceReal",
    UNVERIFIED: "DeployRaceUnverified",
}


# ─────────────────────────────────────────────────────────────────────────────
# THE TAXONOMY. Each window is enumerated from the pipeline that opens it, and
# each names the observable that proves it closed. `evidence` cites the incident
# rows / issues that establish the window is real, not hypothetical.
# ─────────────────────────────────────────────────────────────────────────────
RACE_WINDOWS = {
    "site-edge-invalidation": {
        "pipeline": ".github/workflows/site-deploy.yml (deploy-site -> smoke / visual-qa)",
        "opens_on": "sync_site_to_s3.sh finished uploading site/ and created the CloudFront invalidation",
        "converges_on": "the VIEWER path serves the deployed build",
        "signal": "GET {base}/version.json (no-cache) .build == the deployed short SHA",
        "falsifies": (EDGE_CONTENT,),
        "evidence": (
            "#1526 — 2026-07-19 05:40Z: smoke read a stale edge for /coaching/, failed the "
            "brand-new static-core guard, auto-rollback reverted a HEALTHY deploy",
            "2026-08-04 asset race; 2026-08-16 invalidation race (the row's own verdict: "
            '"the race window is the standing class residual")',
        ),
        "blocking": True,
        "budget_s": 300,
        "poll_s": 10,
    },
    "api-before-frontend": {
        "pipeline": "site-deploy.yml (site/** auto-deploys on merge) vs ci-cd.yml deploy (production approval gate)",
        "opens_on": "a merged PR ships site/ pages consuming site-api routes whose Lambda half is not deployed — "
        "DECLARED in deploy/api_deploy_sequencing.json pending_deploy_routes",
        "converges_on": "every declared pending route answers something other than 404",
        "signal": "GET {base}{route} != 404 for each pending_deploy_routes entry",
        "falsifies": (API_ROUTE,),
        "evidence": (
            "#2831 — the registry's own header: fired >=5 times (07-09 x2 rollbacks, 07-12 "
            "edge-cache, 07-19 IAM-gate, 07-23 #1704, 08-02 #2040)",
            "2026-08-25 20:43Z merge train — statics ran ahead of the site-api with NOTHING "
            "declared, so this window was CLOSED and the rollback was correct",
        ),
        "blocking": True,
        "budget_s": 180,
        "poll_s": 15,
    },
    "lambda-cold-start": {
        "pipeline": "ci-cd.yml (deploy -> smoke-test) and the first viewer hit on a freshly-updated site-api",
        "opens_on": "a Lambda's code was just updated; the next invoke pays a cold start",
        "converges_on": "the serving container is warm",
        "signal": "GET {base}/api/healthz .checks.lambda_warm is true",
        "falsifies": (COLD_LATENCY,),
        "evidence": (
            "#1911 — /api/inference_receipt reliably tripped the 10s smoke timeout twice in "
            "two days, each time auto-reverting a correct merged fix",
            "2026-08-09 cold-Lambda row",
        ),
        # OBSERVED, NEVER AWAITED — and this is a measured correction, not a
        # preference. The first draft blocked on `lambda_warm` like the other two;
        # a live probe on 2026-08-25 (build fc1186a) spent 87.1s and 9 polls
        # before it flipped, because `_COLD_START` is a PER-CONTAINER flag and a
        # low-traffic site hands consecutive probes different fresh containers.
        # A cold-start window is therefore never globally closed: waiting on it
        # would add up to 90s to every site deploy and still prove nothing. One
        # observation is exactly enough — it feeds `classify` so a first-hit
        # timeout can read `raced`, and blocks nobody.
        "blocking": False,
        "budget_s": 0,
        "poll_s": 10,
    },
}

# Deliberately absent from the taxonomy: a window for SEMANTIC verdicts. A
# reader-truth / AI-vision finding about published content is #2959's shape, not
# this one — no convergence signal makes a wrong published number right, so a
# semantic red can never be excused as a race here.


# ─────────────────────────────────────────────────────────────────────────────
# Probes. All HTTP-only and credential-free on purpose: the site-deploy smoke job
# holds no AWS credentials (site-deploy.yml says so explicitly), and a gate that
# needs credentials to run is a gate that silently stops running.
# ─────────────────────────────────────────────────────────────────────────────


def http_fetch(url, timeout=10):
    """Return (status, body) — never raises for an HTTP error status.

    Returns (None, reason) when the request could not be made at all; callers
    read that as UNAVAILABLE, never as a pass.
    """
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "deploy-convergence/2978"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — https URL built from --base
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001 — a body we cannot read is not a verdict
            body = ""
        return e.code, body
    except Exception as e:  # noqa: BLE001 — transport/DNS/TLS: the SIGNAL is unavailable
        return None, f"{type(e).__name__}: {e}"


def _sha_matches(expected, observed):
    """Fingerprint equality across short/long SHA forms.

    version.json carries `git rev-parse --short HEAD` (7+ chars, adaptive);
    GITHUB_SHA is the full 40. Prefix-match in whichever direction is shorter —
    and require at least 7 chars so an empty/garbage stamp can never "match".
    """
    e = (expected or "").strip().lower()
    o = (observed or "").strip().lower()
    if len(e) < 7 or len(o) < 7:
        return False
    return e.startswith(o) or o.startswith(e)


def probe_site_build(base, expect_build, fetch=http_fetch):
    """site-edge-invalidation: does the VIEWER path serve the build we deployed?

    The viewer path, not the origin — the whole class is edge-vs-origin skew, so
    asserting against S3 would prove the wrong thing (memory:
    project_cloudfront_invalidation_path). version.json is uploaded no-cache by
    sync_site_to_s3.sh precisely so this comparison is apples-to-apples.
    """
    status, body = fetch(f"{base.rstrip('/')}/version.json")
    if status is None:
        return UNAVAILABLE, f"/version.json unreachable ({body})"
    if status != 200:
        return UNAVAILABLE, f"/version.json returned HTTP {status}"
    try:
        observed = json.loads(body).get("build")
    except ValueError as e:
        return UNAVAILABLE, f"/version.json is not JSON ({e})"
    if not observed:
        return UNAVAILABLE, "/version.json carries no `build` key"
    if _sha_matches(expect_build, observed):
        return CONVERGED, f"viewer-path build {observed} matches the deployed SHA"
    return PENDING, f"viewer-path build {observed} != deployed {expect_build[:12]} — edge still on the prior object"


def pending_deploy_routes(path=None):
    """The DECLARED api-before-frontend window (#2831's registry), or None.

    None means the registry could not be read — which this module reports as
    UNAVAILABLE, not as "nothing deferred". The existing consumers
    (smoke_test_site.sh, visual_qa.py) fail-soft there on purpose; a GATE may
    not, because "the file is malformed" and "no window is open" are opposite
    facts and only one of them excuses a red.
    """
    try:
        with open(path or API_SEQUENCING_REGISTRY, encoding="utf-8") as f:
            data = json.load(f)
        entries = data.get("pending_deploy_routes")
        if not isinstance(entries, list):
            return None
        return [e["route"] for e in entries if isinstance(e, dict) and e.get("route")]
    except Exception:  # noqa: BLE001 — unreadable registry == unreadable signal
        return None


def probe_pending_routes(base, routes, fetch=http_fetch):
    """api-before-frontend: the window is CLOSED unless something declared it."""
    if routes is None:
        return UNAVAILABLE, "deploy/api_deploy_sequencing.json could not be read"
    if not routes:
        return CLOSED, "no pending_deploy_routes declared — no API-before-frontend window is open"
    still_missing = []
    for route in routes:
        status, body = fetch(f"{base.rstrip('/')}{route}")
        if status is None:
            return UNAVAILABLE, f"{route} unreachable ({body})"
        if status == 404:
            still_missing.append(route)
    if still_missing:
        return PENDING, f"declared route(s) still 404: {', '.join(sorted(still_missing))}"
    return CONVERGED, f"all {len(routes)} declared pending route(s) now answer"


def probe_api_warm(base, fetch=http_fetch):
    """lambda-cold-start: /api/healthz publishes `checks.lambda_warm` for exactly this."""
    status, body = fetch(f"{base.rstrip('/')}/api/healthz")
    if status is None:
        return UNAVAILABLE, f"/api/healthz unreachable ({body})"
    if status != 200:
        return UNAVAILABLE, f"/api/healthz returned HTTP {status}"
    try:
        checks = (json.loads(body) or {}).get("checks") or {}
    except ValueError as e:
        return UNAVAILABLE, f"/api/healthz is not JSON ({e})"
    if "lambda_warm" not in checks:
        return UNAVAILABLE, "/api/healthz carries no checks.lambda_warm"
    if checks["lambda_warm"]:
        return CONVERGED, "site-api container is warm"
    return PENDING, "site-api answered from a cold container — the next check pays the cold start"


# ─────────────────────────────────────────────────────────────────────────────
# The gate: wait on signals, with a bounded budget. Never a fixed sleep.
# ─────────────────────────────────────────────────────────────────────────────


_MISSING = object()  # "read the registry yourself" vs an explicit (possibly empty) route list


def await_convergence(base, expect_build, fetch=None, sleeper=None, clock=None, routes=_MISSING):
    """Poll every window's signal until all are CONVERGED/CLOSED or the budget is spent.

    Returns a report dict:
        {"windows": {id: {"state":…, "detail":…, "polls":…}}, "overall": …, "elapsed_s": …}

    Only BLOCKING windows are polled and only they decide `overall`: UNAVAILABLE
    if any blocking signal could not be read (that beats PENDING — an unreadable
    signal is the louder fact), else PENDING if one is still open past its
    budget, else CONVERGED. Non-blocking windows are observed exactly once and
    feed `classify` alone. The common case is one poll per window and ZERO
    sleeps, because the deploy job already blocked on
    `aws cloudfront wait invalidation-completed`.
    """
    # Resolved here, not in the signature: a default bound at def time cannot be
    # monkeypatched, and a gate whose network layer cannot be substituted is a
    # gate whose tests quietly hit the live site (it did, for one commit).
    fetch = fetch or http_fetch
    sleeper = sleeper or time.sleep
    clock = clock or time.monotonic
    declared = pending_deploy_routes() if routes is _MISSING else routes
    probes = {
        "site-edge-invalidation": lambda: probe_site_build(base, expect_build, fetch=fetch),
        "api-before-frontend": lambda: probe_pending_routes(base, declared, fetch=fetch),
        "lambda-cold-start": lambda: probe_api_warm(base, fetch=fetch),
    }
    start = clock()
    windows = {wid: {"state": PENDING, "detail": "not probed yet", "polls": 0} for wid in RACE_WINDOWS}
    for wid, probe in probes.items():
        spec = RACE_WINDOWS[wid]
        deadline = start + spec["budget_s"]
        while True:
            state, detail = probe()
            windows[wid] = {"state": state, "detail": detail, "polls": windows[wid]["polls"] + 1}
            if state in (CONVERGED, CLOSED) or not spec["blocking"]:
                break
            if clock() >= deadline:
                break
            sleeper(spec["poll_s"])
    states = {w["state"] for wid, w in windows.items() if RACE_WINDOWS[wid]["blocking"]}
    if UNAVAILABLE in states:
        overall = UNAVAILABLE
    elif PENDING in states:
        overall = PENDING
    else:
        overall = CONVERGED
    return {"windows": windows, "overall": overall, "elapsed_s": round(clock() - start, 1)}


def open_windows(report, check_kind):
    """Window ids that are still OPEN (pending) and can falsify `check_kind`."""
    return sorted(wid for wid, w in report["windows"].items() if w["state"] == PENDING and check_kind in RACE_WINDOWS[wid]["falsifies"])


def unreadable_windows(report, check_kind):
    """Window ids whose SIGNAL could not be read and that could falsify `check_kind`."""
    return sorted(wid for wid, w in report["windows"].items() if w["state"] == UNAVAILABLE and check_kind in RACE_WINDOWS[wid]["falsifies"])


def classify(check_kind, report):
    """Return (disposition, reason) for ONE failing check against a convergence report.

    The whole judgment in three lines, in priority order:
      * a signal we could not read  -> unverified (fail loudly, #2578)
      * an OPEN declared window that can falsify this kind -> raced (rerun)
      * everything else             -> real (fail hard)
    """
    if check_kind not in CHECK_KINDS:
        return UNVERIFIED, f"unknown check kind {check_kind!r} — a kind with no taxonomy entry cannot be excused"
    blind = unreadable_windows(report, check_kind)
    if blind:
        return UNVERIFIED, "convergence signal unreadable for " + ", ".join(f"{w} ({report['windows'][w]['detail']})" for w in blind)
    racing = open_windows(report, check_kind)
    if racing:
        return RACED, "inside open race window(s) " + ", ".join(f"{w} ({report['windows'][w]['detail']})" for w in racing)
    relevant = [wid for wid, spec in RACE_WINDOWS.items() if check_kind in spec["falsifies"]]
    if not relevant:
        return REAL, f"no race window can falsify a {check_kind} check — this is a verdict about published state, not about convergence"
    closed = ", ".join(f"{w}={report['windows'][w]['state']}" for w in relevant)
    return REAL, f"every window that could falsify this check has converged or was never declared ({closed})"


# ─────────────────────────────────────────────────────────────────────────────
# The metric. The rate this class was measured at ("1 per 1.5 days") came from
# hand-reading docs/INCIDENT_LOG.md after the fact; a disposition emitted at the
# moment of the verdict is what makes it falsifiable going forward.
# ─────────────────────────────────────────────────────────────────────────────


def emf_record(disposition, check_kind, window_id=None, detail="", clock=time.time):
    """One EMF blob (Embedded Metric Format) — the repo's standard emit shape."""
    metric_name = METRIC_BY_DISPOSITION[disposition]
    return {
        "_aws": {
            "Timestamp": int(clock() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": METRIC_NAMESPACE,
                    # No dimensions on purpose: three flat series, not a fan-out.
                    # #2837's finding is that per-facet dimensions are how a
                    # namespace grows past anyone's attention.
                    "Dimensions": [[]],
                    "Metrics": [{"Name": metric_name, "Unit": "Count"}],
                }
            ],
        },
        metric_name: 1,
        "disposition": disposition,
        "check_kind": check_kind,
        "window": window_id or "none",
        "detail": detail[:500],
        "issue": "2978",
    }


def emit(disposition, check_kind, window_id=None, detail="", stream=None, clock=time.time):
    """Print the EMF blob; additionally PutMetricData when explicitly armed.

    Honest about its own reach: the site-deploy smoke job holds no AWS
    credentials by design, so today the durable channel is this line in the run
    log (grep `"issue": "2978"`). `DEPLOY_RACE_PUT_METRIC=1` arms the CloudWatch
    put for any caller that does have credentials; a put failure is reported and
    never changes the verdict.
    """
    record = emf_record(disposition, check_kind, window_id, detail, clock=clock)
    print(json.dumps(record), file=stream or sys.stdout)
    if os.environ.get("DEPLOY_RACE_PUT_METRIC") == "1":
        try:
            import boto3  # noqa: PLC0415 — optional, only on the armed path

            boto3.client("cloudwatch", region_name=os.environ.get("AWS_REGION", "us-west-2")).put_metric_data(
                Namespace=METRIC_NAMESPACE,
                MetricData=[{"MetricName": METRIC_BY_DISPOSITION[disposition], "Value": 1, "Unit": "Count"}],
            )
        except Exception as e:  # noqa: BLE001 — telemetry must never gate a deploy
            print(f"::warning::deploy-race metric put failed ({type(e).__name__}: {e}) — the EMF line above is still the record")
    return record


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

EXIT_CONVERGED = 0
EXIT_PENDING = 2
EXIT_UNAVAILABLE = 3


def render_table():
    """The taxonomy as a markdown table — the PR-body/doc surface."""
    lines = [
        "| window | pipeline | opens when | converges when (the SIGNAL) | falsifies | gate |",
        "|---|---|---|---|---|---|",
    ]
    for wid, spec in RACE_WINDOWS.items():
        gate = f"awaited, {spec['budget_s']}s budget" if spec["blocking"] else "observed only (never globally closes)"
        lines.append(
            f"| `{wid}` | {spec['pipeline']} | {spec['opens_on']} | {spec['converges_on']} — `{spec['signal']}` | "
            f"{', '.join(spec['falsifies'])} | {gate} |"
        )
    return "\n".join(lines)


def _print_report(report):
    print(f"── convergence gate (#2978) — overall: {report['overall'].upper()} in {report['elapsed_s']}s ──")
    for wid, w in report["windows"].items():
        icon = {CONVERGED: "✅", CLOSED: "•", PENDING: "⏳", UNAVAILABLE: "❌"}[w["state"]]
        # A non-blocking window's state is EVIDENCE for the classifier, never a
        # verdict on the deploy — say so, so "⏳ pending" is never read as a stall.
        scope = "" if RACE_WINDOWS[wid]["blocking"] else " [observed only — feeds the raced/real classification, blocks nothing]"
        print(f"  {icon} {wid}: {w['state']} ({w['polls']} poll(s)) — {w['detail']}{scope}")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Deploy-race convergence gate + taxonomy (#2978).")
    parser.add_argument("--table", action="store_true", help="print the race-window taxonomy and exit")
    sub = parser.add_subparsers(dest="cmd")
    aw = sub.add_parser("await", help="wait for every convergence signal before post-deploy checks run")
    aw.add_argument("--base", default=os.environ.get("QA_SITE_URL", "https://averagejoematt.com"))
    aw.add_argument("--expect-build", required=True, help="the SHA the deploy shipped (full or short)")
    aw.add_argument("--json", action="store_true", help="also print the raw report JSON")
    args = parser.parse_args(argv)

    if args.table or args.cmd is None:
        print(render_table())
        return 0

    report = await_convergence(args.base, args.expect_build)
    _print_report(report)
    if args.json:
        print(json.dumps(report, indent=2))

    if report["overall"] == CONVERGED:
        return EXIT_CONVERGED
    # Not converged: name the disposition the checks WOULD carry, and emit it, so
    # a non-convergent deploy is counted rather than only felt.
    blocking = [w for w in report["windows"] if RACE_WINDOWS[w]["blocking"]]
    if report["overall"] == UNAVAILABLE:
        blind = [w for w in blocking if report["windows"][w]["state"] == UNAVAILABLE]
        emit(UNVERIFIED, EDGE_CONTENT, blind[0] if blind else None, "; ".join(report["windows"][w]["detail"] for w in blind))
        print(
            "::error::convergence signal UNREADABLE — post-deploy checks cannot distinguish a race "
            "from a real failure, so this run is UNVERIFIED, never a pass (#2578)."
        )
        return EXIT_UNAVAILABLE
    stuck = [w for w in blocking if report["windows"][w]["state"] == PENDING]
    emit(RACED, EDGE_CONTENT, stuck[0] if stuck else None, "; ".join(report["windows"][w]["detail"] for w in stuck))
    print(
        f"::error::convergence NOT reached within budget for {', '.join(stuck)} — the post-deploy checks "
        "would be measuring the pre-deploy world. Re-run after the signal converges."
    )
    return EXIT_PENDING


if __name__ == "__main__":
    sys.exit(main())
