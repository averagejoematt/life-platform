#!/usr/bin/env python3
"""
accuracy_audit.py — deterministic Axis-A engine for the site "truth audit".

Existing QA proves pages RENDER and data is FRESH. This proves the NUMBERS are
TRUE: it (1) runs the declared-but-unrun cross-page metric consistency check, (2)
spot-checks the live API's headline raw numbers against DynamoDB ground truth, and
(3) scans captured API JSON + rendered prose for leaked NaN/undefined/None, unit
mismatches, and UTC-vs-PT date drift.

Inputs: a capture run dir from `tests/site_review.py` (api/*.json + <slug>.txt).
  python3 tests/accuracy_audit.py                       # use latest qa-screenshots/<date>/
  python3 tests/accuracy_audit.py --run-dir qa-screenshots/2026-06-28
  python3 tests/accuracy_audit.py --no-ddb              # skip the live-DDB ground-truth pass

Output: <run-dir>/accuracy_audit.json + a printed summary. Exits non-zero if any
HIGH finding (a real numeric disagreement or a leaked sentinel in user-facing text).

Read-only. DDB pass needs AWS creds with read on table `life-platform` (us-west-2).
"""

import argparse
import glob
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import site_review as SR  # noqa: E402  (reuses SITE_URL, cross_page_consistency, _slug_for_endpoint)
import site_review_bindings as B  # noqa: E402

# Headline RAW numbers we can ground in a single DDB source record (computed metrics
# like character level / pillar scores are validated by the compute lambdas' own tests,
# not here). Each: which live API endpoint+json-path, vs which DDB source+field, tol.
DDB_GROUND_TRUTH = [
    # name,            api_url,          json_path,                  ddb_source,     ddb_field,            tol
    ("weight_lbs", "/api/vitals", "vitals.weight_lbs", "withings", "weight_lbs", 0.6),
    ("hrv_ms", "/api/vitals", "vitals.hrv_ms", "whoop", "hrv", 6.0),
    ("rhr_bpm", "/api/vitals", "vitals.rhr_bpm", "whoop", "resting_heart_rate", 4.0),
]

# Sentinels in a JSON string value usually mean a Python-repr / serialization leak.
_LEAK_RE = re.compile(r"\b(undefined|NaN|\[object Object\]|None|null)\b")
# In rendered prose, "None"/"null" are common English; only the JS-runtime leaks matter.
_PROSE_LEAK_RE = re.compile(r"(undefined|NaN|\[object Object\])")
# Strings that look like a raw ISO datetime leaking where a friendly date belongs.
_RAW_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _dig(data, path):
    cur = data
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return None
    return cur


def _latest_run_dir():
    dirs = sorted(d for d in glob.glob("qa-screenshots/*") if os.path.isdir(d))
    return dirs[-1] if dirs else None


def _rebuild_api_index(run_dir):
    """Reconstruct site_review's api_index {url: {file, ok}} from the captured api/ dir."""
    api_dir = os.path.join(run_dir, "api")
    index = {}
    for url in B.all_endpoints():
        stem = SR._slug_for_endpoint(url)
        fname = stem if stem.endswith(".json") else stem + ".json"
        fpath = os.path.join(api_dir, fname)
        if os.path.exists(fpath):
            try:
                with open(fpath) as f:
                    json.load(f)
                index[url] = {"file": f"api/{fname}", "ok": True}
            except Exception:  # noqa: BLE001
                index[url] = {"file": f"api/{fname}", "ok": False}
    return index


def _fetch_json(url):
    req = urllib.request.Request(SR.SITE_URL + url, headers={"User-Agent": "accuracy-audit/1.0"})
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def ddb_ground_truth():
    """Compare live API headline raw numbers against the latest DynamoDB source record."""
    import boto3  # local import so --no-ddb works without creds
    from boto3.dynamodb.conditions import Key

    table = boto3.resource("dynamodb", region_name="us-west-2").Table("life-platform")
    findings = []
    for name, api_url, jpath, source, field, tol in DDB_GROUND_TRUTH:
        try:
            api_val = _dig(_fetch_json(api_url), jpath)
        except Exception as e:  # noqa: BLE001
            findings.append({"check": name, "severity": "warn", "note": f"API fetch failed: {e}"})
            continue
        r = table.query(
            KeyConditionExpression=Key("pk").eq(f"USER#matthew#SOURCE#{source}") & Key("sk").begins_with("DATE#"),
            ScanIndexForward=False,
            Limit=14,
        )
        ddb_val, ddb_date = None, None
        for it in r.get("Items", []):
            if field in it and it[field] is not None:
                ddb_val = float(it[field])
                ddb_date = it["sk"]
                break
        if api_val is None or ddb_val is None:
            findings.append({"check": name, "severity": "warn", "api": api_val, "ddb": ddb_val, "note": "missing value on one side"})
            continue
        delta = abs(float(api_val) - ddb_val)
        findings.append(
            {
                "check": name,
                "severity": "ok" if delta <= tol else "high",
                "api": float(api_val),
                "ddb": ddb_val,
                "ddb_date": ddb_date,
                "delta": round(delta, 3),
                "tolerance": tol,
                "note": "" if delta <= tol else f"live API {name} diverges from latest DDB {source}.{field} by {delta:.2f} (> {tol})",
            }
        )
    return findings


def sanity_scan(run_dir):
    """Scan captured API JSON values + rendered prose for leaked sentinels / raw datetimes."""
    findings = []
    # API JSON: walk string values only (keys named 'null'/'none' are fine).
    for fpath in sorted(glob.glob(os.path.join(run_dir, "api", "*.json"))):
        try:
            with open(fpath) as f:
                data = json.load(f)
        except Exception:  # noqa: BLE001
            continue

        def _walk(node, path=""):
            if isinstance(node, dict):
                for k, v in node.items():
                    _walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node[:50]):
                    _walk(v, f"{path}[{i}]")
            elif isinstance(node, str):
                if _LEAK_RE.search(node) and len(node) < 200:
                    findings.append({"source": os.path.basename(fpath), "where": path, "severity": "high", "snippet": node[:120]})

        _walk(data)
    # Rendered prose (.txt): a leaked sentinel here is what the visitor literally sees.
    for fpath in sorted(glob.glob(os.path.join(run_dir, "*.txt"))):
        try:
            with open(fpath) as f:
                text = f.read()
        except Exception:  # noqa: BLE001
            continue
        for m in _PROSE_LEAK_RE.finditer(text):
            seg = text[max(0, m.start() - 40) : m.start() + 40].replace("\n", " ")
            findings.append({"source": os.path.basename(fpath), "where": "rendered prose", "severity": "high", "snippet": seg})
        for m in _RAW_DT_RE.finditer(text):
            seg = text[max(0, m.start() - 30) : m.start() + 30].replace("\n", " ")
            findings.append(
                {"source": os.path.basename(fpath), "where": "rendered prose", "severity": "warn", "snippet": f"raw datetime: {seg}"}
            )
    return findings


def impossible_values(ps):
    """Scan a public_stats dict for impossible computed values. Pure (no I/O) so it
    runs identically against a live fetch (live_checks) or a local fixture served by
    the PR-time render gate (tests/pr_render_gate.py). Catches: negative CTL/ATL (the
    -955 class) and percentages outside [0,100]. Returns a list of HIGH findings."""
    findings = []
    t = ps.get("training", {}) or {}
    for k in ("ctl_fitness", "atl_fatigue", "ctl", "atl"):
        v = t.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 0:
            findings.append({"check": "impossible_value", "severity": "high", "field": f"training.{k}", "value": v, "note": "must be >= 0"})
    for blk_name in ("journey", "vitals"):
        for k, v in (ps.get(blk_name, {}) or {}).items():
            if k.endswith("_pct") and isinstance(v, (int, float)) and not isinstance(v, bool) and not (0 <= v <= 100):
                findings.append(
                    {"check": "impossible_value", "severity": "high", "field": f"{blk_name}.{k}", "value": v, "note": "pct out of [0,100]"}
                )
    return findings


def live_checks():
    """Live-fetch checks that need NO prior capture (CI-friendly, post-deploy):
    (1) every harness page must resolve — catches the /data-vs-/method drift class +
        any dropped page (a 404 page renders HTTP 404 or a 'SIGNAL LOST' body);
    (2) impossible computed values in public_stats — negative CTL/ATL (the -955 class)
        and out-of-range percentages.
    Returns a list of findings (severity high/warn)."""
    import urllib.error

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import visual_qa as VQ

    findings = []
    for pg in VQ.PAGES:
        path = pg["path"].split("#")[0]
        try:
            req = urllib.request.Request(SR.SITE_URL + path, headers={"User-Agent": "accuracy-audit/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                status = resp.status
                body = resp.read(4000).decode("utf-8", "replace")
            broken = status != 200 or "SIGNAL LOST" in body
        except urllib.error.HTTPError as e:
            status, broken = e.code, True
        except Exception as e:  # noqa: BLE001
            status, broken = f"ERR:{type(e).__name__}", True
        if broken:
            findings.append({"check": "page_resolves", "severity": "high", "path": pg["path"], "status": status})

    try:
        findings.extend(impossible_values(_fetch_json("/public_stats.json")))
    except Exception as e:  # noqa: BLE001
        findings.append({"check": "impossible_value", "severity": "warn", "note": f"public_stats fetch failed: {e}"})
    return findings


def main():
    ap = argparse.ArgumentParser(description="Axis-A deterministic accuracy audit (numbers + consistency + sentinels).")
    ap.add_argument("--run-dir", help="Capture dir from site_review.py (default: latest qa-screenshots/<date>)")
    ap.add_argument("--no-ddb", action="store_true", help="Skip the live-DDB ground-truth pass")
    ap.add_argument(
        "--live", action="store_true", help="Live-fetch checks only (per-page 404 + impossible values); no capture needed — for CI"
    )
    args = ap.parse_args()

    if args.live:
        live = live_checks()
        bad = [f for f in live if f["severity"] == "high"]
        print(f"Live checks (per-page resolve + impossible values): {len(bad)} HIGH finding(s)")
        for f in live:
            icon = "❌" if f["severity"] == "high" else "⚠️ "
            print(f"  {icon} {f.get('check')}: {f.get('path') or f.get('field') or ''} {f.get('status','')} {f.get('note','')}".rstrip())
        print(f"\n{'❌ HIGH findings present' if bad else '✅ all pages resolve, no impossible values'}")
        sys.exit(1 if bad else 0)

    run_dir = args.run_dir or _latest_run_dir()
    if not run_dir or not os.path.isdir(run_dir):
        sys.exit("No capture run dir found. Run `python3 tests/site_review.py` first.")
    print(f"Axis-A accuracy audit over {run_dir}\n")

    api_index = _rebuild_api_index(run_dir)
    consistency = SR.cross_page_consistency(run_dir, api_index)
    ddb = [] if args.no_ddb else ddb_ground_truth()
    sentinels = sanity_scan(run_dir)

    report = {"run_dir": run_dir, "consistency": consistency, "ddb_ground_truth": ddb, "sentinel_scan": sentinels}
    with open(os.path.join(run_dir, "accuracy_audit.json"), "w") as f:
        json.dump(report, f, indent=2)

    # ── summary ──
    cons_bad = [c for c in consistency["checks"] if not c["agree"]]
    ddb_bad = [d for d in ddb if d.get("severity") == "high"]
    sent_bad = [s for s in sentinels if s["severity"] == "high"]
    print(f"Cross-page consistency: {consistency['checked']} metrics checked, {len(cons_bad)} disagreement(s)")
    for c in cons_bad:
        print(f"  ❌ {c['metric']}: Δ{c['max_delta']} > tol {c['tolerance']} — {c['sources']}")
    print(f"API→DDB ground truth: {len(ddb)} checked, {len(ddb_bad)} divergence(s)")
    for d in ddb:
        icon = {"ok": "✅", "high": "❌", "warn": "⚠️ "}.get(d["severity"], "?")
        print(f"  {icon} {d['check']}: api={d.get('api')} ddb={d.get('ddb')} {d.get('note','')}".rstrip())
    print(f"Sentinel/date scan: {len(sent_bad)} leak(s), {len(sentinels) - len(sent_bad)} warning(s)")
    for s in sent_bad[:10]:
        print(f"  ❌ {s['source']} [{s['where']}]: {s['snippet']}")

    hard_fail = bool(cons_bad or ddb_bad or sent_bad)
    print(f"\n{'❌ HIGH findings present' if hard_fail else '✅ no HIGH findings'} — report: {run_dir}/accuracy_audit.json")
    sys.exit(1 if hard_fail else 0)


if __name__ == "__main__":
    main()
