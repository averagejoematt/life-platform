#!/usr/bin/env python3
"""api_sweep_check.py — the #2652 box-3 live-route sweep (status + JSON shape).

Probes every row of `tests/qa_manifest.api_sweep_records()` — the router-derived
/api long tail no page declares as an api_dep — against the live site. This is
the sweep that closes the hole `light_pct: 106.7` shipped through: the numeric
rule existed, but only ever ran over the endpoints the manifest happened to
fetch. The route list here derives from `deploy/endpoint_registry`'s AST walk,
so a route that was never registered anywhere still gets probed.

Verdicts (per row):
  PASS  status matches the row's expectation; when 200 is expected, the body
        must also be non-empty, well-formed JSON (the same bar the #1586
        api_deps section sets)
  FAIL  wrong status, or an expected-200 body that is empty / not JSON
  WARN  transport failure (timeout / connection error) after one retry — the
        #2841 posture: a transient network fault on a pageless route must not
        auto-rollback a healthy deploy. A genuinely dead route answers with an
        HTTP status (404/5xx) and FAILs. Also: a 404 on a route deferred via
        deploy/api_deploy_sequencing.json's pending_deploy_routes (#2831 — the
        known merged-but-not-deployed-yet window).

Exit: 1 if any FAIL, or if the derivation yields ZERO rows (a sweep that
checked nothing must not report like a clean sweep — the #2578 rule); else 0.

The numeric/impossible-value scan over these routes lives in
tests/accuracy_audit.py --live, whose endpoint denominator includes these rows
(one instrument per concern — this script owns status+shape, that one owns the
numeric rubric).

Callers: deploy/smoke_test_site.sh's "Live-route sweep" section (gating), and
the driver directly — `python3 scripts/api_sweep_check.py` — to measure the
sweep against live before merging a change to it (the 2026-07-17 rule: never
arm an unmeasured widened gate).

Measured before arming (2026-08-22, live): 71/71 rows PASS — 62 generic
200+JSON, 8 measured overrides (six param-gated 400s, the board_ask 405 door,
the /api/coach/ prefix probe), plus /api/vitals and /api/character_calibration
riding along from the hand-check era; one transient timeout on
/api/ai_analysis in the first pass motivated the retry + WARN posture.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
for _p in (os.path.join(_REPO, "tests"), os.path.join(_REPO, "deploy")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DEFAULT_BASE = "https://averagejoematt.com"
SEQUENCING_PATH = os.path.join(_REPO, "deploy", "api_deploy_sequencing.json")


def pending_deploy_routes(path: str = SEQUENCING_PATH) -> set:
    """#2831: routes whose 404 is the declared merged-but-not-deployed window."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return {e["route"] for e in (data.get("pending_deploy_routes") or []) if isinstance(e, dict) and e.get("route")}
    except Exception:  # noqa: BLE001 — a missing/broken registry means no deferrals, not a crash
        return set()


def fetch(url: str, timeout: int = 15):
    """(status:int, body:bytes) — HTTP errors return their status; transport errors raise."""
    req = urllib.request.Request(url, headers={"User-Agent": "api-sweep-check/1.0 (#2652)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(2_000_000)
    except urllib.error.HTTPError as e:
        return e.code, e.read(100_000)


def verdict(rec: dict, status, body: bytes, pending: set) -> tuple:
    """(state, detail) for one fetched row — pure, offline-testable.

    status is an int, or None for a transport failure that survived the retry.
    """
    if status is None:
        return "WARN", "transport failure after retry — not counted as a gate failure (#2841 posture)"
    if str(status) != rec["expect"]:
        if status == 404 and rec["route"] in pending:
            return "WARN", "404, but DEFERRED via deploy/api_deploy_sequencing.json pending_deploy_routes (#2831)"
        return "FAIL", f"expected {rec['expect']}, got {status}"
    if rec["expect"] == "200":
        if not body:
            return "FAIL", "200 but empty body"
        try:
            json.loads(body.decode("utf-8", "replace"))
        except (json.JSONDecodeError, ValueError):
            return "FAIL", "200 but body is not valid JSON"
    return "PASS", ""


def sweep(records: list, base: str, fetcher=fetch) -> dict:
    """Run every row; returns {'pass': [...], 'warn': [...], 'fail': [...]}."""
    pending = pending_deploy_routes()
    out = {"pass": [], "warn": [], "fail": []}
    for rec in records:
        sep = "&" if "?" in rec["fetch"] else "?"
        url = f"{base}{rec['fetch']}{sep}_cb=sweep{int(time.time() * 1000)}"
        status, body = None, b""
        for attempt in (1, 2):
            try:
                status, body = fetcher(url)
                break
            except Exception as e:  # noqa: BLE001 — timeout/DNS/reset: retry once, then WARN
                if attempt == 2:
                    print(f"  ⚠️  {rec['route']:<38} transport failure after retry: {type(e).__name__} ({url})")
        state, detail = verdict(rec, status, body, pending)
        out[state.lower()].append((rec["route"], detail))
        if state == "PASS":
            print(f"  ✅ {rec['route']:<38} {rec['expect']}{' (probe ' + rec['fetch'] + ')' if rec['fetch'] != rec['route'] else ''}")
        elif state == "WARN" and status is not None:
            print(f"  ⚠️  {rec['route']:<38} {detail}")
        elif state == "FAIL":
            print(f"  ❌ {rec['route']:<38} {detail} ({url})")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Router-derived /api long-tail sweep — status + JSON shape (#2652 box 3)")
    ap.add_argument("--base", default=DEFAULT_BASE, help=f"origin to probe (default {DEFAULT_BASE})")
    args = ap.parse_args()

    import qa_manifest

    records = qa_manifest.api_sweep_records()
    if not records:
        # Blindness detector (#2578's rule): a derivation returning nothing must fail,
        # because a sweep of zero rows reports exactly like a clean sweep.
        print("❌ api_sweep derivation yielded ZERO rows — this sweep checked nothing")
        return 1

    print(f"Live-route sweep (#2652): {len(records)} router-derived rows against {args.base}")
    result = sweep(records, args.base)
    print(f"\n{len(result['pass'])} pass · {len(result['warn'])} warn · {len(result['fail'])} FAIL of {len(records)} rows")
    return 1 if result["fail"] else 0


if __name__ == "__main__":
    sys.exit(main())
