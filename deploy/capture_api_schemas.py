#!/usr/bin/env python3
"""
deploy/capture_api_schemas.py — shape-level JSON schema snapshots for every /api/*
endpoint on the live site (#1436).

WHY: ~118 public endpoints (deduped: 115, #1437) had NO per-endpoint contract baseline
— a handler could silently change a field's type, drop a key, or leak a rendered
"undefined"/"NaN" and nothing would catch it until a reader (or a downstream page)
did. This captures a SHAPE (types + keys, never raw values — #1436 AC3: privacy +
staleness) per endpoint, serially, against the live site, with per-endpoint failure
tolerance so one flaky/auth-gated/write-only route never aborts the whole run.

Endpoints come from ONE source of truth: deploy/endpoint_registry.py's AST-derived
enumeration of lambdas/web/site_api_lambda.py's ROUTES + _SIMPLE_ROUTES + inline
dispatcher checks — the same walk deploy/sync_doc_metadata.py's doc-sync count uses,
so this script's coverage and the doc-sync "115 endpoints" literal can never drift
apart (one AST walk, two consumers).

Every one of the 115 discovered paths ends up EITHER:
  - a committed shape snapshot at tests/api_schemas/<slug>.json (successful GET), or
  - an entry in tests/api_schemas/_exemptions.json with a reason:
      write-path            — POST-only, or GET-verb-but-mutating (never called live)
      requires-path-param   — needs a parameter this script can't safely synthesize
      capture-failed-<code> — attempted live, got a non-2xx status or a timeout
      deprecated            — route exists but is retired/dead (documented, not hit)
      auth-gated            — requires credentials this script doesn't have

tests/test_api_schema_completeness.py enforces that EVERY discovered path lands in
one of the two buckets — a new route with neither reds CI (#1436's structural core).

Sentinel scan (#1436 AC): every successfully-fetched LIVE response (before it is
reduced to a shape-only snapshot) is scanned by
tests/accuracy_audit.py::scan_json_value_leaks for a leaked NaN/undefined/
[object Object]/None/null string — the same regex/walk tests/site_review.py's curated
subset always used, now run across the FULL router surface. Findings are printed
loudly; they do not abort the capture run (a leak is a finding to act on, not a
capture-script crash), but `--fail-on-leak` turns them into a nonzero exit for a
human/CI run that wants that.

Usage:
    python3 deploy/capture_api_schemas.py                  # capture + write snapshots + exemptions
    python3 deploy/capture_api_schemas.py --dry-run         # print the plan, no HTTP, no writes
    python3 deploy/capture_api_schemas.py --check-drift     # capture live, diff vs committed shapes, exit 1 on drift (no writes)
    python3 deploy/capture_api_schemas.py --fail-on-leak    # nonzero exit if any sentinel leak is found

Read-only: GET requests only, serial (one endpoint at a time, courtesy sleep between
each), against https://averagejoematt.com (override with $QA_SITE_URL). Never issues
POST/PUT/PATCH/DELETE — write-path endpoints are exempted, never probed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for _p in (ROOT / "deploy", ROOT / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import accuracy_audit  # noqa: E402 — scan_json_value_leaks, the shared sentinel scan (#1436)
import endpoint_registry  # noqa: E402

SITE_URL = os.environ.get("QA_SITE_URL", "https://averagejoematt.com")
SNAPSHOT_DIR = ROOT / "tests" / "api_schemas"
EXEMPTIONS_PATH = SNAPSHOT_DIR / "_exemptions.json"
SLEEP_SECONDS = 0.4
TIMEOUT_SECONDS = 20

EXEMPTION_CATEGORIES = {"write-path", "requires-path-param", "deprecated", "auth-gated", "capture-failed"}

# ── write-path endpoints: POST-only, or a GET verb that mutates. Never called live. ──
WRITE_PATH_EXEMPT = {
    "/api/board_ask": (
        "POST-only AI panel endpoint; dispatched by a SEPARATE lambda "
        "(site_api_ai_lambda.py) — this router's ROUTES entry is a reservation "
        "placeholder only, never itself invoked"
    ),
    "/api/board_question": "POST-only — board follow-up turn (write)",
    "/api/challenge_checkin": "POST-only — records a challenge check-in (write)",
    "/api/challenge_follow": "POST-only — follow/unfollow a challenge (write)",
    "/api/challenge_vote": "POST-only — votes on a challenge (write)",
    "/api/experiment_follow": "POST-only — follow/unfollow an experiment (write)",
    "/api/experiment_suggest": "POST-only — reader-submitted experiment suggestion (write)",
    "/api/experiment_vote": "POST-only — votes on an experiment (write)",
    "/api/nudge": "POST-only — evening nudge action (write)",
    "/api/submit_finding": "POST-only — reader-submitted finding, writes to S3 (write)",
    "/api/ritual_log": (
        "GET-verb but MUTATING: one-tap evening-ritual write gated by a signed HMAC "
        "token (ADR-124, #769) — no read-only variant exists; there is no safe way to "
        "probe it that doesn't attempt a write"
    ),
}

# ── endpoints that need a parameter this script can't safely synthesize ──
REQUIRES_PARAM_EXEMPT = {
    "/api/verify_subscriber": (
        "requires ?email= — a real subscriber address; probing an arbitrary address "
        "would leak that address's subscription status (privacy), and there is no "
        "safe synthetic value"
    ),
}

# ── a concrete sample URL for a route the AST enumerator reports as a path-parameter
# PREFIX (path.startswith(...)), not a literal path. Verified live (2026-07-19): the
# domain-key form ("sleep", "mind", ...) 404s — handle_coach's persona registry keys
# on the FULL persona id ("sleep_coach", "eli_marsh", ...), same ids /api/coaches'
# roster returns. A wrong sample here doesn't crash the capture — it 404s at the
# Lambda, which CloudFront's custom-error-response maps to the static site's 404.html
# (S3-served, non-JSON), so it would land as an honest capture-failed exemption
# rather than a false "success" — but a correct sample gets real coverage instead. ──
PREFIX_SAMPLES = {
    "/api/coach/": "/api/coach/sleep_coach",  # a known-operational coach persona id (site_api_coach.py)
}

# ── endpoints resolved via a preliminary live lookup rather than a hardcoded id.
# Best-effort: if the lookup itself fails, the endpoint falls through to a plain
# capture attempt (no query params), which will most likely land as a
# capture-failed-4xx exemption — an honest signal, not a crash. ──
DYNAMIC_PARAM_LOOKUP = {
    "/api/experiment_detail": {
        # /api/experiment_library nests experiments under pillars[i].experiments[],
        # not a top-level "experiments" list — verified live (2026-07-19).
        "lookup_path": "/api/experiment_library",
        "extract": lambda data: (((data.get("pillars") or [{}])[0] or {}).get("experiments") or [{}])[0].get("id"),
        "query_param": "id",
    },
    "/api/coach_timeline": {
        # coach_id here is the SHORT domain key ("sleep"), unlike /api/coach/{id}'s
        # full persona id ("sleep_coach") — two different id vocabularies for two
        # different handlers, verified live (2026-07-19). No live lookup needed
        # (the short-key set is a stable literal in handle_coach_timeline), but
        # expressed as a lookup entry with a static list so it's documented here
        # rather than silently baked into the fetch_path.
        "lookup_path": None,
        "extract": lambda data: "sleep",
        "query_param": "coach_id",
    },
    "/api/changes-since": {
        # ?ts=EPOCH_SECONDS is required; any past epoch is valid (it's just a "since"
        # cursor), so this needs no live lookup — a static 7-day-ago timestamp,
        # computed at capture time so the snapshot never contains a stale absolute
        # value baked into the SCRIPT (the committed snapshot only records shape).
        "lookup_path": None,
        "extract": lambda data: int(time.time()) - 7 * 86400,
        "query_param": "ts",
    },
}


# ── shape extraction (privacy: types/keys only, never raw values, #1436 AC3) ──


def json_shape(node):
    """Recursively reduce a JSON value to its shape: {"type": ..., ...}.

    Objects keep their key set (recursing per key); arrays record the DISTINCT
    item shapes observed in the first 20 elements (usually 1, for a homogeneous
    list) plus a length sample; scalars record only their type. No string/number/
    bool VALUE is ever retained — this is the "shape not values" contract."""
    if node is None:
        return {"type": "null"}
    if isinstance(node, bool):  # must precede the int check — bool is an int subclass
        return {"type": "boolean"}
    if isinstance(node, int):
        return {"type": "integer"}
    if isinstance(node, float):
        return {"type": "number"}
    if isinstance(node, str):
        return {"type": "string"}
    if isinstance(node, list):
        if not node:
            return {"type": "array", "items": None, "length_sample": 0}
        seen = {}
        for item in node[:20]:
            shape = json_shape(item)
            key = json.dumps(shape, sort_keys=True)
            seen.setdefault(key, shape)
        uniq = list(seen.values())
        return {"type": "array", "items": uniq[0] if len(uniq) == 1 else uniq, "length_sample": len(node)}
    if isinstance(node, dict):
        return {"type": "object", "keys": {k: json_shape(v) for k, v in node.items()}}
    return {"type": "unknown"}


def is_valid_shape_node(node) -> bool:
    """Structural validator for a json_shape() output — used by the completeness
    test to catch a hand-edited or corrupted snapshot file."""
    if not isinstance(node, dict) or "type" not in node:
        return False
    t = node["type"]
    if t in ("null", "boolean", "integer", "number", "string", "unknown"):
        return True
    if t == "object":
        keys = node.get("keys")
        return isinstance(keys, dict) and all(is_valid_shape_node(v) for v in keys.values())
    if t == "array":
        items = node.get("items")
        if items is None:
            return True
        if isinstance(items, list):
            return all(is_valid_shape_node(i) for i in items)
        return is_valid_shape_node(items)
    return False


def diff_shape(old, new, path="$") -> list:
    """Structural diff between two shape nodes. Returns a list of human-readable
    diffs; empty means shape-identical. A KEY ADDED is reported but is not, by
    itself, a breaking change (informational) — key REMOVED and TYPE CHANGED are
    the drift classes that matter."""
    diffs = []
    if not (isinstance(old, dict) and isinstance(new, dict)):
        return [f"{path}: not comparable (malformed shape node)"]
    if old.get("type") != new.get("type"):
        diffs.append(f"{path}: type changed {old.get('type')!r} -> {new.get('type')!r}")
        return diffs
    t = old.get("type")
    if t == "object":
        old_keys = old.get("keys", {}) or {}
        new_keys = new.get("keys", {}) or {}
        for k in sorted(old_keys):
            if k not in new_keys:
                diffs.append(f"{path}.{k}: key removed")
            else:
                diffs.extend(diff_shape(old_keys[k], new_keys[k], f"{path}.{k}"))
        for k in sorted(new_keys):
            if k not in old_keys:
                diffs.append(f"{path}.{k}: key added (informational)")
    elif t == "array":
        oi, ni = old.get("items"), new.get("items")
        if oi is None or ni is None:
            return diffs
        # Normalize a single-shape item list to compare against a heterogeneous one
        # by comparing the union — a real break is a shape present in old but no
        # longer present anywhere in new.
        old_shapes = oi if isinstance(oi, list) else [oi]
        new_shapes = ni if isinstance(ni, list) else [ni]
        new_keys_set = {json.dumps(s, sort_keys=True) for s in new_shapes}
        for s in old_shapes:
            if json.dumps(s, sort_keys=True) not in new_keys_set:
                # No exact match — diff against the closest (first) new shape for a
                # readable message rather than just "shape missing".
                sub = diff_shape(s, new_shapes[0], f"{path}[]") if new_shapes else [f"{path}[]: array became empty/unknown"]
                diffs.extend(sub)
    return diffs


# ── path <-> filename ──


def slug_for(path: str, *, is_prefix: bool = False) -> str:
    s = path.strip("/").replace("/", "_").replace("-", "_")
    if is_prefix:
        s += "__prefix_sample"
    return s + ".json"


# ── HTTP ──


def _fetch(path: str):
    """GET SITE_URL+path. Returns (status_code, json_or_None, error_str_or_None)."""
    url = SITE_URL + path
    req = urllib.request.Request(url, headers={"User-Agent": "api-schema-capture/1.0 (#1436)"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:  # noqa: S310 — fixed https URL, GET only
            status = resp.getcode()
            body = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            body = ""
    except Exception as e:  # noqa: BLE001 — timeout, DNS, connection reset, ...
        return None, None, f"{type(e).__name__}: {e}"

    try:
        data = json.loads(body) if body else None
    except Exception as e:  # noqa: BLE001
        return status, None, f"non-JSON body: {e}"
    return status, data, None


def _resolve_dynamic_param(spec: dict):
    """Resolve a value to plug into a required query param.

    `lookup_path=None` means the value needs no live fetch (a static literal or a
    locally-computed value like "7 days ago") — `extract` is called directly.
    Otherwise this is a best-effort live lookup: if the lookup GET itself fails,
    returns None rather than raising (the caller falls through to a plain capture
    attempt, which will most likely land as an honest capture-failed exemption)."""
    if spec.get("lookup_path") is None:
        try:
            return spec["extract"](None)
        except Exception:  # noqa: BLE001
            return None
    status, data, err = _fetch(spec["lookup_path"])
    if err or status != 200 or not isinstance(data, dict):
        return None
    try:
        return spec["extract"](data)
    except Exception:  # noqa: BLE001
        return None


# ── capture ──


def build_plan():
    """{path: EndpointRecord} for the full discovered surface, plus the resolved
    "fetch path" (query string / prefix sample) for each non-exempt entry."""
    records = endpoint_registry.discover_endpoint_records()
    plan = []
    for path in sorted(records):
        rec = records[path]
        if path in WRITE_PATH_EXEMPT:
            plan.append({"path": path, "action": "exempt", "category": "write-path", "reason": WRITE_PATH_EXEMPT[path]})
        elif path in REQUIRES_PARAM_EXEMPT:
            plan.append({"path": path, "action": "exempt", "category": "requires-path-param", "reason": REQUIRES_PARAM_EXEMPT[path]})
        elif rec.is_prefix and path in PREFIX_SAMPLES:
            plan.append({"path": path, "action": "capture", "fetch_path": PREFIX_SAMPLES[path], "is_prefix": True})
        elif rec.is_prefix:
            plan.append(
                {
                    "path": path,
                    "action": "exempt",
                    "category": "requires-path-param",
                    "reason": "prefix route with no documented sample id in PREFIX_SAMPLES",
                }
            )
        else:
            plan.append({"path": path, "action": "capture", "fetch_path": path, "is_prefix": False})
    return plan


def run_capture(*, dry_run: bool, check_drift: bool, fail_on_leak: bool) -> int:
    plan = build_plan()
    to_capture = [p for p in plan if p["action"] == "capture"]
    to_exempt = [p for p in plan if p["action"] == "exempt"]

    print(f"── capture_api_schemas: {len(plan)} discovered endpoints ──")
    print(f"  {len(to_capture)} planned for live capture, {len(to_exempt)} pre-exempted (write-path / requires-param)")
    if dry_run:
        for p in plan:
            if p["action"] == "capture":
                print(f"  [capture] {p['path']} -> GET {p['fetch_path']}")
            else:
                print(f"  [exempt:{p['category']}] {p['path']} — {p['reason']}")
        return 0

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    exemptions: dict = {}
    for p in to_exempt:
        exemptions[p["path"]] = {"category": p["category"], "reason": p["reason"]}

    captured, failed, leaks, drift = 0, 0, [], []
    now = datetime.now(timezone.utc).isoformat()

    for i, p in enumerate(to_capture):
        path = p["path"]
        fetch_path = p["fetch_path"]

        # Resolve any dynamic param lookup for this path (currently only
        # /api/experiment_detail) before the real capture GET.
        if path in DYNAMIC_PARAM_LOOKUP:
            spec = DYNAMIC_PARAM_LOOKUP[path]
            val = _resolve_dynamic_param(spec)
            if val:
                fetch_path = f"{path}?{spec['query_param']}={val}"
            time.sleep(SLEEP_SECONDS)

        status, data, err = _fetch(fetch_path)
        time.sleep(SLEEP_SECONDS)

        if err or status is None:
            failed += 1
            exemptions[path] = {"category": "capture-failed", "reason": f"request error: {err}", "fetch_path": fetch_path}
            print(f"  [WARN] {path}: request failed — {err}")
            continue
        if status != 200 or not isinstance(data, (dict, list)):
            failed += 1
            body_type = type(data).__name__ if data is not None else "non-JSON/empty"
            exemptions[path] = {
                "category": "capture-failed",
                "reason": f"capture-failed-{status}: {body_type} body",
                "fetch_path": fetch_path,
            }
            print(f"  [WARN] {path}: HTTP {status}, body={body_type} — exempted as capture-failed-{status}")
            continue

        # Sentinel scan the LIVE response (raw values, in-memory only — never
        # written to the committed snapshot) before reducing it to shape.
        finds = accuracy_audit.scan_json_value_leaks(data, f"live:{path}")
        if finds:
            leaks.extend(finds)
            for f in finds:
                print(f"  [LEAK] {path} {f['where']}: {f['snippet']!r}")

        shape = json_shape(data)
        snapshot = {
            "path": path,
            "fetch_path": fetch_path,
            "captured_at": now,
            "status": status,
            "is_prefix_sample": p.get("is_prefix", False),
            "shape": shape,
        }

        fname = slug_for(path, is_prefix=p.get("is_prefix", False))
        fpath = SNAPSHOT_DIR / fname

        if check_drift:
            if fpath.exists():
                try:
                    old = json.loads(fpath.read_text(encoding="utf-8"))
                    d = diff_shape(old.get("shape"), shape)
                    breaking = [x for x in d if "informational" not in x]
                    if breaking:
                        drift.append({"path": path, "diffs": breaking})
                        print(f"  [DRIFT] {path}:")
                        for line in breaking:
                            print(f"      - {line}")
                except Exception as e:  # noqa: BLE001
                    print(f"  [WARN] {path}: could not diff against committed snapshot — {e}")
            else:
                print(f"  [WARN] {path}: no committed snapshot to diff against")
        else:
            fpath.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            captured += 1

        if (i + 1) % 10 == 0:
            print(f"  … {i + 1}/{len(to_capture)} captured")

    if not check_drift:
        EXEMPTIONS_PATH.write_text(json.dumps(exemptions, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"\n{captured} snapshots written, {len(exemptions)} exemptions ({failed} from live capture failures)")
        print(f"snapshots: {SNAPSHOT_DIR}")
        print(f"exemptions: {EXEMPTIONS_PATH}")
    else:
        print(f"\ncheck-drift complete: {len(drift)} endpoint(s) with breaking shape drift, {len(leaks)} sentinel leak(s)")

    if leaks:
        print(f"\n{len(leaks)} SENTINEL LEAK finding(s) — leaked NaN/undefined/[object Object]/None/null in a live response:")
        for f in leaks:
            print(f"  {f['source']} {f['where']}: {f['snippet']!r}")

    if check_drift and drift:
        return 1
    if fail_on_leak and leaks:
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", help="print the capture plan only, no HTTP, no writes")
    ap.add_argument("--check-drift", action="store_true", help="capture live, diff vs committed shapes, exit 1 on drift; no writes")
    ap.add_argument("--fail-on-leak", action="store_true", help="nonzero exit if any live sentinel leak is found")
    args = ap.parse_args()
    return run_capture(dry_run=args.dry_run, check_drift=args.check_drift, fail_on_leak=args.fail_on_leak)


if __name__ == "__main__":
    sys.exit(main())
