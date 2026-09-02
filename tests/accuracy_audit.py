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
# #3324 anchored "None"/"null" to the WHOLE string value because they ARE common
# English/statistics vocabulary ("null hypothesis", "None when |r| >= 1") — but it
# kept "undefined"/"NaN" as a bare substring match on the premise that THOSE "never
# occur as innocent English". #3453: that premise is FALSE — the platform's own
# published prose (/method/registry/, ADR-104/105 #1370's calibration-verdict
# language) reads "...skill is undefined against a degenerate base rate..." and
# "An undefined skill (degenerate base rate) is treated as unknown...", both
# deliberate honest statistics prose, not a leak. A phrase-matched substring can't
# tell those apart from a real `Value: undefined` render — the #2959/#3003/#3199/
# #3379 family's lesson applies to a DETECTOR too: it must be structural.
#
# So "undefined"/"NaN" are now matched STRUCTURALLY: a hit only counts when it sits
# in a rendered-VALUE position — adjacent to a label/colon/punctuation/quote/bracket,
# at a line boundary, or standalone — never mid-sentence flanked by two ordinary
# words (see `_is_isolated_value` below, which is what the "leak" vs "prose" call
# actually turns on; #3453 acceptance: never fire between lowercase words).
# "[object Object]" keeps the old pure-substring match: it is JS's literal
# `Object.prototype.toString()` output, bracket-delimited, and still never occurs
# as innocent English — nothing in the #3453 finding challenges that one.
_STRUCTURAL_LEAK_RE = re.compile(r"(undefined|NaN)")
_ALWAYS_LEAK_RE = re.compile(r"\[object Object\]")
_WHOLE_VALUE_NULLISH_RE = re.compile(r"^(None|null)$")


def _is_isolated_value(text, start, end):
    """True if text[start:end] sits in a rendered-VALUE position, not embedded
    mid-sentence between two ordinary words (#3453).

    Looks past HORIZONTAL whitespace only (spaces/tabs — same-line padding, as in
    a label's `Weight:  undefined`) to the nearest non-whitespace character on
    each side. If BOTH sides are alphabetic — the token is flanked by ordinary
    words on the same line, as in "...skill is undefined against a degenerate..."
    — it's prose, not a leak. A newline is NOT skipped: it's a real line/block
    boundary in rendered prose (document.body.innerText), so `undefined` sitting
    alone on its own line (a real leak's most common shape) must not be treated
    as continuous with the word before/after it on a different line.

    Anything else on either side (a colon, quote, bracket, comma, digit, other
    punctuation, a newline, or the start/end of the string) reads as a value
    position, the way a real leak actually renders: `Value: undefined`,
    `undefined%`, a bare `undefined` alone on its own line, or `"field":
    "undefined"`.
    """
    j = start - 1
    while j >= 0 and text[j] in " \t":
        j -= 1
    prev_alpha = j >= 0 and text[j].isalpha()

    k = end
    while k < len(text) and text[k] in " \t":
        k += 1
    next_alpha = k < len(text) and text[k].isalpha()

    return not (prev_alpha and next_alpha)


def _find_leak_matches(text):
    """Yield (start, end) for every raw JS-runtime sentinel leak in `text`:
    "undefined"/"NaN" only when `_is_isolated_value` says it's in a rendered-value
    position, "[object Object]" unconditionally (see the module comment above)."""
    for m in _STRUCTURAL_LEAK_RE.finditer(text):
        if _is_isolated_value(text, m.start(), m.end()):
            yield m.start(), m.end()
    for m in _ALWAYS_LEAK_RE.finditer(text):
        yield m.start(), m.end()


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


def scan_json_value_leaks(data, source_label):
    """Walk a parsed JSON value for leaked NaN/undefined/[object Object]/None/null
    inside STRING values (keys named 'null'/'none' are fine — only values matter).

    #3324: "None"/"null" are common English/statistics words (a `limitations`
    sentence reading "None when |r| >= 1..." or "null hypothesis"), so they are
    anchored to the WHOLE string value (`_WHOLE_VALUE_NULLISH_RE`) — a leak looks
    like `"value": "None"`, not a sentence that happens to use the word.

    #3453: "undefined"/"NaN" turned out to have the SAME false-positive risk — the
    platform's own honest calibration prose reads "...skill is undefined against a
    degenerate base rate..." — so they're no longer a bare substring match either.
    `_find_leak_matches` only counts a hit when it's in a rendered-VALUE position
    (see `_is_isolated_value`); a sentence merely containing the word does not fire.
    "[object Object]" stays a pure substring match (never innocent English).

    Extracted (#1436) so this is the ONE leak-scan walk shared by:
      - sanity_scan() below, which reads already-captured api/*.json files off disk
        (the tests/site_review.py capture flow — a curated page-binding subset), and
      - deploy/capture_api_schemas.py, which scans the LIVE response in-memory at
        capture time, across the FULL AST-discovered ~115-endpoint router surface —
        before the raw value is discarded in favor of the shape-only snapshot that
        actually gets committed (values are never checked in, #1436 AC3: shape not
        values). This is how the sentinel scan's coverage extends to every endpoint
        rather than just the page-bound subset sanity_scan's callers historically hit.

    Returns a list of {"source", "where", "severity": "high", "snippet"} findings.
    """
    findings = []

    def _walk(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                _walk(v, f"{path}.{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node[:50]):
                _walk(v, f"{path}[{i}]")
        elif isinstance(node, str):
            if len(node) < 200 and (next(_find_leak_matches(node), None) is not None or _WHOLE_VALUE_NULLISH_RE.match(node.strip())):
                findings.append({"source": source_label, "where": path, "severity": "high", "snippet": node[:120]})

    _walk(data)
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
        findings.extend(scan_json_value_leaks(data, os.path.basename(fpath)))
    # Rendered prose (.txt): a leaked sentinel here is what the visitor literally sees.
    for fpath in sorted(glob.glob(os.path.join(run_dir, "*.txt"))):
        try:
            with open(fpath) as f:
                text = f.read()
        except Exception:  # noqa: BLE001
            continue
        for start, _end in _find_leak_matches(text):
            seg = text[max(0, start - 40) : start + 40].replace("\n", " ")
            findings.append({"source": os.path.basename(fpath), "where": "rendered prose", "severity": "high", "snippet": seg})
        for m in _RAW_DT_RE.finditer(text):
            seg = text[max(0, m.start() - 30) : m.start() + 30].replace("\n", " ")
            findings.append(
                {"source": os.path.basename(fpath), "where": "rendered prose", "severity": "warn", "snippet": f"raw datetime: {seg}"}
            )
    return findings


# Percent fields that are legitimately signed. `progress_pct`: weight above the cycle
# baseline is honest negative progress (ADR-104 down-weeks-shown), bounded at -100 (the
# full goal distance regained). Keep this set SMALL and evidence-driven — a broad
# pre-exemption is how a real impossible number gets waved through.
_SIGNED_PCT_FIELDS = frozenset({"progress_pct"})


def _pct_bounds(key):
    return (-100, 100) if key in _SIGNED_PCT_FIELDS else (0, 100)


def scan_impossible_pcts(payload, source="payload"):
    """Recursively flag every `*_pct` outside its legal range, anywhere in `payload`.

    WHY RECURSIVE, AND WHY THIS EXISTS (2026-08-21). The rubric below was already
    correct — `_pct` fields belong in [0,100] — but it only ever read two top-level
    blocks of ONE document (`public_stats`). Meanwhile `/api/sleep_detail` served

        2026-08-20  deep 11.1 + rem 31.1 + light 106.7 = 148.9%

    to the public site, and nothing looked: the bad value sat inside a `sleep_trend`
    LIST, on an endpoint this scan never fetched. A correct rule with a denominator
    narrower than the live surface is #2652's defect, and this is it in the numeric
    gate — so the walk is now structure-agnostic (dicts, lists, any depth) and the
    caller decides which documents to feed it.

    Returns findings with a dotted `field` path so an operator can locate the value
    rather than re-derive where it came from.
    """
    findings = []

    def walk(node, path):
        if isinstance(node, dict):
            for k, v in node.items():
                here = f"{path}.{k}" if path else k
                if k.endswith("_pct") and isinstance(v, (int, float)) and not isinstance(v, bool):
                    lo, hi = _pct_bounds(k)
                    if not (lo <= v <= hi):
                        findings.append(
                            {
                                "check": "impossible_value",
                                "severity": "high",
                                "source": source,
                                "field": here,
                                "value": v,
                                "note": f"pct out of [{lo},{hi}]",
                            }
                        )
                walk(v, here)
        elif isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]")

    walk(payload, "")
    return findings


def impossible_values(ps):
    """Scan a public_stats dict for impossible computed values.

    Deterministic, data-source agnostic: negative training load (the -955 CTL/ATL
    class) and out-of-range percentages. Extracted from live_checks so the PR-time
    render gate (tests/pr_render_gate.py) can run the exact same numeric rubric
    against a locally-served public_stats without a live deploy. Returns findings
    (severity high/warn); an empty list means every value is in range.

    The percentage half now delegates to `scan_impossible_pcts`, so public_stats and
    every swept API payload are graded by ONE rubric — the two cannot drift into
    disagreeing about what a legal percentage is.
    """
    findings = []
    if not isinstance(ps, dict):
        return [{"check": "impossible_value", "severity": "warn", "note": "public_stats not a JSON object"}]
    t = ps.get("training", {}) or {}
    for k in ("ctl_fitness", "atl_fatigue", "ctl", "atl"):
        v = t.get(k)
        if isinstance(v, (int, float)) and v < 0:
            findings.append({"check": "impossible_value", "severity": "high", "field": f"training.{k}", "value": v, "note": "must be >= 0"})
    findings.extend(scan_impossible_pcts(ps, source="public_stats"))
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

    # ── the API surface, DERIVED — not a hand-list (#2652's lesson) ──────────────
    #
    # Until 2026-08-21 this whole check read ONE document, `public_stats.json`. The
    # rubric was right and its denominator was wrong, so `/api/sleep_detail` served
    # `sleep_trend[3].light_pct = 106.7` to the public site and nothing looked.
    #
    # The endpoint set comes from `tests/qa_manifest.py`'s declared `api_deps` — the
    # same registry the rest of the QA harness derives from — so an endpoint a page
    # starts depending on joins this sweep by construction. Hand-listing the endpoints
    # here would rebuild the exact defect one layer over.
    #
    # Measured before arming (2026-08-21, live): 59 of 59 endpoints fetched, ONE high
    # finding — the known `light_pct` defect. So this does not arrive pre-red.
    #
    # A fetch failure is a WARN, not HIGH: this is a post-deploy gate and a transient
    # 5xx on an unrelated endpoint must not auto-rollback a healthy deploy (the #2841
    # false-red class). A genuinely dead endpoint is already caught as `page_resolves`.
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import qa_manifest as QM

        endpoints = {dep for pg in QM.MANIFEST for dep in (pg.get("api_deps") or [])}
    except Exception as e:  # noqa: BLE001
        findings.append({"check": "impossible_value", "severity": "warn", "note": f"api_deps derivation failed: {e}"})
        endpoints = set()

    # #2652 box 3: widen the denominator to the router-derived long tail — the routes
    # NO page declares, where the original `light_pct` defect actually lived. Only the
    # rows a healthy bare GET answers with 200 (a param-gated route's validator 400 has
    # no numbers to scan). Derived from the same endpoint_registry walk qa_audit counts
    # coverage against, so this sweep and the coverage ledger cannot disagree.
    # Measured before arming (2026-08-22, live): all long-tail rows fetched, ZERO
    # impossible-pct findings — this widening does not arrive pre-red.
    # Derived separately from api_deps above so one broken derivation cannot silently
    # take the other half of the denominator down with it.
    try:
        endpoints |= {r["fetch"] for r in QM.api_sweep_records() if r["expect"] == "200"}
    except Exception as e:  # noqa: BLE001
        findings.append({"check": "impossible_value", "severity": "warn", "note": f"api_sweep derivation failed: {e}"})
    endpoints = sorted(endpoints)

    if not endpoints:
        # Blindness detector (#2578's rule): a derivation returning nothing must say so.
        # Silently sweeping zero endpoints would report exactly like a clean sweep.
        findings.append(
            {
                "check": "impossible_value",
                "severity": "warn",
                "note": "api_deps derivation yielded ZERO endpoints — this sweep checked nothing",
            }
        )

    for dep in endpoints:
        try:
            findings.extend(scan_impossible_pcts(_fetch_json(dep), source=dep))
        except Exception as e:  # noqa: BLE001
            findings.append({"check": "impossible_value", "severity": "warn", "source": dep, "note": f"fetch failed: {e}"})
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
