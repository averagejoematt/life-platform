#!/usr/bin/env python3
"""ER-06 — PII-to-public-surface guard.

Editorial guardrails (no employer/role/industry; partner unnamed; only the two
allowed vice categories named publicly) and docs/DATA_GOVERNANCE.md exist as
*policy*. Nothing structurally stops a prompt/template change from surfacing a
guarded string — `generated/` is Lambda-written daily. This is the missing gate:
scan the about-to-be-published static site BEFORE `sync_site_to_s3.sh` ships it,
fail-closed on a hit.

Three arms:
  1. Blocked-vice leakage (always-on) — no `blocked_vice_keywords` from
     config/content_filter.json (the policy-blocked categories) appears in published text.
  2. Structural PII (always-on) — US SSN, 16-digit card-like numbers, and
     non-allowlisted email addresses (the PII classes in DATA_GOVERNANCE.md).
  3. Literal denylist (best-effort) — partner name / employer / role / industry
     tokens loaded from a NON-committed source: env `PII_DENYLIST_JSON` (a JSON
     array, e.g. a CI secret) or the gitignored `config/pii_denylist.local.json`.
     Skipped with a notice when absent — the repo is PUBLIC, so these literals
     never live in git; the always-on arms still gate in public CI.

Usage:  python3 deploy/pii_surface_guard.py [site_dir]   # exit 1 on any violation
        python3 deploy/pii_surface_guard.py --snapshots            # offline endpoint arm (#1945)
        python3 deploy/pii_surface_guard.py --endpoints [base_url] # live endpoint arm (#1945)

Endpoint arm (#1945 — the structural sibling of the #1943 genome finding): the
static-site walk above never touched the ~130 live `/api/*` JSON payloads, so the
entire dynamic public surface was ungated. The endpoint arm closes that:

  - The route set is DERIVED, never hand-enumerated: deploy/endpoint_registry.py's
    AST walk of lambdas/web/site_api_lambda.py (the same single source of truth the
    doc-sync count and the #1436 schema-completeness gate consume), filtered through
    deploy/capture_api_schemas.build_plan()'s write-path/param exemptions.
  - Offline half (CI-gating, no network): every committed shape snapshot in
    tests/api_schemas/ has its key paths scanned for genetic tells (rsid/genotype/
    allele/... — the #1943 class) and chronological-age/birth-year tells (PhenoAge
    Option A: bio-age is public, chronological age NEVER). Coverage is asserted
    fail-closed: a route with neither a snapshot nor a reasoned exemption is a
    violation, not a silent skip — an endpoint never scanned is neither a pass nor
    a finding (#1935 honesty class).
  - Live half (QA/manual, GET-only): fetches every derivable GET payload and runs
    the full scan_text arms PLUS the value/key tell arms over the real values.
    A fetch that fails is reported as `endpoint-not-scanned` — fail-closed.

The genetic/age tell arms are deliberately NOT wired into scan_site(): public
build-beat prose legitimately narrates the #1943 fix with the word "genotype" —
on a static page that word is copy about the class; inside an /api/* payload it
is a leak tell.

Pure stdlib, no AWS — importable by tests/test_public_surface_pii_guard.py (offline).
"""

import json
import os
import re
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

# Text artifacts that actually ship to the public surface.
_SCAN_EXT = (".html", ".json", ".txt", ".xml", ".webmanifest", ".svg")
# /legacy is the private rollback copy (no UI links) — out of scope here; sw.js
# is generated asset boilerplate.
_SKIP_DIRS = ("legacy",)

# Emails allowed to appear publicly (the site's own contact identities + the
# RFC 9116 security.txt contact + obvious form placeholders).
_ALLOWED_EMAILS = {
    "lifeplatform@mattsusername.com",
    "claude@mattsusername.com",
    "security@mattsusername.com",
    "hello@averagejoematt.com",
    # placeholders that are not real addresses
    "your@email.com",
    "you@example.com",
    "name@example.com",
    "email@example.com",
}
_ALLOWED_EMAIL_DOMAINS = ("averagejoematt.com", "example.com")

_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# The dot-lookarounds keep float precision out of the card arm: a JSON payload's
# `1.5714285714285714` carries 16 consecutive mantissa digits, which is a number's
# tail, not a card (#1945 — found live on /api/character_receipt).
_CARD_RE = re.compile(r"(?<![\d.])\d{16}(?![\d.])")
# Same class of structural false positive, second instance (#1983): a DOI suffix is an
# opaque publisher-assigned string that can be exactly 16 digits — Sage's
# `doi.org/10.1177/0265407512453827` is one, and it is a citation, not a card. Masking
# only text that is *syntactically a DOI* (the `10.NNNN/` registrant prefix is
# mandatory) keeps the arm's teeth: a bare 16-digit run anywhere else still fires.
_DOI_RE = re.compile(r"(?:https?://(?:dx\.)?doi\.org/|\bdoi:\s*)10\.\d{4,9}/\S+", re.I)
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _blocked_vice_keywords() -> list:
    """The canonical public-content denylist, loaded ONLY from the committed
    policy file (config/content_filter.json `blocked_vice_keywords`) — never
    hardcoded here, so the literal category terms live in exactly one place.
    Fail-closed: if the policy can't be read or is empty, raise rather than
    silently scan with the vice arm disabled."""
    path = os.path.join(_ROOT, "config", "content_filter.json")
    with open(path) as f:
        kws = [k.lower() for k in json.load(f).get("blocked_vice_keywords", [])]
    if not kws:
        raise RuntimeError(f"no blocked_vice_keywords in {path} — refusing to scan with the vice arm disabled")
    return kws


def _literal_denylist() -> list:
    """Personal guarded literals (partner name, employer, role, industry) from a
    NON-committed source. Returns [] (and the arm self-skips) when absent."""
    raw = os.environ.get("PII_DENYLIST_JSON")
    if raw:
        try:
            data = json.loads(raw)
            return [str(t).lower() for t in (data if isinstance(data, list) else data.get("terms", []))]
        except Exception:
            return []
    local = os.path.join(_ROOT, "config", "pii_denylist.local.json")
    if os.path.exists(local):
        try:
            with open(local) as f:
                return [str(t).lower() for t in json.load(f).get("terms", [])]
        except Exception:
            return []
    return []


def _iter_files(site_dir: str):
    for root, dirs, files in os.walk(site_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for name in files:
            if name.endswith(_SCAN_EXT) and name != "sw.js":
                yield os.path.join(root, name)


def _word_hits(text_low: str, terms: list) -> set:
    hits = set()
    for t in terms:
        if not t:
            continue
        if re.search(r"\b" + re.escape(t) + r"\b", text_low):
            hits.add(t)
    return hits


def scan_text(text: str, vice=None, literals=None) -> list:
    """Return a list of (arm, detail) violations for one document's text."""
    low = text.lower()
    out = []
    for kw in _word_hits(low, vice if vice is not None else _blocked_vice_keywords()):
        out.append(("blocked-vice", kw))
    if _SSN_RE.search(text):
        out.append(("pii-ssn", "SSN-shaped number"))
    if _CARD_RE.search(_DOI_RE.sub(" ", text)):
        out.append(("pii-card", "16-digit number"))
    for m in _EMAIL_RE.findall(text):
        e = m.lower()
        if e in _ALLOWED_EMAILS or any(e.endswith("@" + d) for d in _ALLOWED_EMAIL_DOMAINS):
            continue
        out.append(("pii-email", m))
    for lit in _word_hits(low, literals if literals is not None else _literal_denylist()):
        out.append(("literal-denylist", "guarded literal"))  # never echo the literal itself
    return out


def scan_site(site_dir: str) -> dict:
    """Scan the published site. Returns {violations: [(file, arm, detail)],
    literal_arm: 'on'|'skipped', files: N}."""
    vice = _blocked_vice_keywords()
    literals = _literal_denylist()
    violations, n = [], 0
    for path in _iter_files(site_dir):
        n += 1
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except Exception:
            continue
        rel = os.path.relpath(path, site_dir)
        for arm, detail in scan_text(text, vice=vice, literals=literals):
            violations.append((rel, arm, detail))
    return {"violations": violations, "literal_arm": "on" if literals else "skipped", "files": n}


# ═══ Endpoint arm (#1945) ══════════════════════════════════════════════════════
#
# Value-level tells, scanned over the serialized payload body (endpoint arm ONLY —
# see module docstring for why these never run on the static site walk).
# Genetic vocabulary kept deliberately in sync with the platform's one definition
# (lambdas/web/site_api_vitals._GENETIC_TEXT_RE and
# tests/test_public_genetic_privacy_absolute._GENETIC_KEY_RE) — asserted by
# tests/test_public_surface_pii_guard.py, not trusted to stay aligned by hand.
_GENETIC_VALUE_RE = re.compile(r"\brs\d{3,}\b|\bgenotype\b|\ballele\b|\bheterozygous\b|\bhomozygous\b", re.IGNORECASE)
_BIRTH_VALUE_RE = re.compile(
    r"\bborn\s+(?:on|in)\s+(?:19|20)\d\d\b|\bdate\s+of\s+birth\b|\bbirth\s?date\b|\bbirth\s?year\b",
    re.IGNORECASE,
)

# Key-level tells (underscore-aware boundaries: `\b` treats `_` as a word char, so
# `\bgene\b` would miss `gene_name` — these patterns don't).
_GENETIC_KEY_RE = re.compile(r"genotype|allele|zygosity|snp_id|rsid|(?:^|_)rs\d+(?:_|$)|(?:^|_)genes?(?:_|$)", re.IGNORECASE)
# Aggregate COUNTS of genetic material identify the analysis, not the person — the
# sanctioned public shape (#1943 / PRE-13). Allowlist of shapes, not of routes.
_GENETIC_AGGREGATE_KEYS = {"total_snps", "snp_count", "n_snps"}
_CHRON_AGE_KEY_RE = re.compile(
    r"(?:^|_)(?:birth_?year|birth_?date|birthday|date_of_birth|year_of_birth|dob|chronological_age)(?:_|$)",
    re.IGNORECASE,
)

_SNAPSHOT_DIR = os.path.join(_ROOT, "tests", "api_schemas")


def _import_endpoint_tools():
    """Lazy import of the shared route-enumeration machinery. Lazy so the static
    site path (sync_site_to_s3.sh) keeps zero dependencies beyond this file."""
    for p in (_HERE, os.path.join(_ROOT, "tests")):
        if p not in sys.path:
            sys.path.insert(0, p)
    import capture_api_schemas as cas  # noqa: PLC0415 — deliberate lazy import
    import endpoint_registry as er  # noqa: PLC0415

    return er, cas


def iter_payload_keys(node, path="$"):
    """Yield (json_path, key) for every dict key in a parsed JSON payload."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}"
            yield p, str(k)
            yield from iter_payload_keys(v, p)
    elif isinstance(node, list):
        for v in node:
            yield from iter_payload_keys(v, path + "[]")


def iter_shape_keys(node, path="$"):
    """Yield (json_path, key) for every payload key in a captured json_shape tree
    (tests/api_schemas/*.json — shape metadata words like 'type'/'keys'/'items'/
    'length_sample' are structure, not payload keys)."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k in ("keys", "items", "type", "length_sample"):
                yield from iter_shape_keys(v, path)
            else:
                p = f"{path}.{k}"
                yield p, str(k)
                yield from iter_shape_keys(v, p)
    elif isinstance(node, list):
        for v in node:
            yield from iter_shape_keys(v, path)


def _scan_keys(key_iter) -> list:
    """The genetic-tell + chronological-age key arms over any (json_path, key) stream."""
    out = []
    for jp, key in key_iter:
        if _GENETIC_KEY_RE.search(key) and key.lower() not in _GENETIC_AGGREGATE_KEYS:
            out.append(("pii-genetic-key", f"{jp} ({key})"))
        if _CHRON_AGE_KEY_RE.search(key):
            out.append(("pii-age-key", f"{jp} ({key})"))
    return out


def scan_endpoint_payload(text: str, vice=None, literals=None) -> list:
    """All arms over one /api/* payload body: the existing scan_text arms PLUS the
    endpoint-only value tells, PLUS the key tells when the body parses as JSON."""
    out = scan_text(text, vice=vice, literals=literals)
    if _GENETIC_VALUE_RE.search(text):
        out.append(("pii-genetic", "genetic identifier tell in payload text"))
    if _BIRTH_VALUE_RE.search(text):
        out.append(("pii-age", "birth-date/chronological-age tell in payload text"))
    try:
        data = json.loads(text)
    except Exception:
        data = None
    if data is not None:
        out.extend(_scan_keys(iter_payload_keys(data)))
    return out


def scan_schema_snapshots(snapshot_dir: str = _SNAPSHOT_DIR) -> dict:
    """Offline endpoint arm (CI-gating): key-tell scan of every committed shape
    snapshot, with route coverage asserted fail-closed against the AST-derived
    route set. Returns {violations: [(where, arm, detail)], scanned_paths: set,
    files: N}. `violations` includes one `endpoint-not-scanned` entry per route
    with neither a snapshot nor a reasoned exemption (#1935: never a silent pass).
    Raises (fail-closed) if the snapshot dir or route enumeration is unusable."""
    er, _cas = _import_endpoint_tools()
    discovered = set(er.discover_endpoint_paths())
    if len(discovered) < er.SANITY_FLOOR:
        raise RuntimeError(f"endpoint enumerator returned suspiciously few routes ({len(discovered)}) — refusing to scan")

    exemptions_path = os.path.join(snapshot_dir, "_exemptions.json")
    with open(exemptions_path) as f:
        exempt = set(json.load(f).keys())

    violations, scanned_paths, files = [], set(), 0
    snap_files = sorted(f for f in os.listdir(snapshot_dir) if f.endswith(".json") and f != "_exemptions.json")
    if not snap_files:
        raise RuntimeError(f"no shape snapshots in {snapshot_dir} — a vacuous scan is not a pass")
    for name in snap_files:
        fpath = os.path.join(snapshot_dir, name)
        try:
            with open(fpath) as f:
                snap = json.load(f)
        except Exception as e:
            violations.append((name, "endpoint-not-scanned", f"unreadable snapshot: {e}"))
            continue
        files += 1
        path = snap.get("path") or name
        scanned_paths.add(path)
        for arm, detail in _scan_keys(iter_shape_keys(snap.get("shape") or {})):
            violations.append((path, arm, detail))

    for path in sorted(discovered - scanned_paths - exempt):
        violations.append((path, "endpoint-not-scanned", "no shape snapshot and no reasoned exemption — run deploy/capture_api_schemas.py"))
    return {"violations": violations, "scanned_paths": scanned_paths, "files": files}


def scan_endpoints(base_url: str, fetcher=None, sleep_seconds: float = 0.25) -> dict:
    """Live endpoint arm (QA/manual, GET-only, serial): fetch every derivable GET
    payload from `base_url` and run scan_endpoint_payload over the real values.
    `fetcher(fetch_path) -> (status, parsed_json_or_None, err_or_None)` is
    injectable for tests; defaults to capture_api_schemas._fetch against base_url.
    Fail-closed: a route the arm planned to scan but could not read is reported as
    an `endpoint-not-scanned` violation, never folded into the pass tally (#1935)."""
    import time as _time

    er, cas = _import_endpoint_tools()
    cas.SITE_URL = base_url.rstrip("/")  # dynamic-param lookups must hit the same host
    plan = cas.build_plan()
    records = er.discover_endpoint_records()
    vice = _blocked_vice_keywords()
    literals = _literal_denylist()
    fetch = fetcher or cas._fetch

    violations, scanned, skipped = [], [], {}
    for p in plan:
        path = p["path"]
        if p["action"] != "capture":
            skipped[path] = p["category"]
            continue
        # Write-path skip DERIVED from the router's own method declarations (the
        # AST walk), not from a hand-list: a future POST-only route is skipped
        # here automatically instead of red-ing the sweep with a 405.
        rec = records.get(path)
        if rec is not None and rec.methods == {"POST"}:
            skipped[path] = "write-path (POST-only, AST-derived)"
            continue
        fetch_path = p["fetch_path"]
        if path in cas.DYNAMIC_PARAM_LOOKUP:
            spec = cas.DYNAMIC_PARAM_LOOKUP[path]
            val = cas._resolve_dynamic_param(spec) if fetcher is None else None
            if val:
                fetch_path = f"{path}?{spec['query_param']}={val}"
        status, data, err = fetch(fetch_path)
        if fetcher is None and sleep_seconds:
            _time.sleep(sleep_seconds)
        if err or status != 200 or data is None:
            violations.append((path, "endpoint-not-scanned", f"HTTP {status}: {err or 'non-200/empty'}"))
            continue
        body = json.dumps(data)
        for arm, detail in scan_endpoint_payload(body, vice=vice, literals=literals):
            violations.append((path, arm, detail))
        scanned.append(path)
    return {"violations": violations, "scanned": scanned, "skipped": skipped, "literal_arm": "on" if literals else "skipped"}


def _report_endpoint_results(res: dict, what: str) -> int:
    if res["violations"]:
        print(f"[pii-guard] ❌ {len(res['violations'])} violation(s) on the {what}:", file=sys.stderr)
        for where, arm, detail in res["violations"]:
            print(f"    {where}: [{arm}] {detail}", file=sys.stderr)
        return 1
    print(f"[pii-guard] ✅ clean — no PII tells on the {what}")
    return 0


def main(argv) -> int:
    if len(argv) > 1 and argv[1] == "--snapshots":
        res = scan_schema_snapshots()
        print(f"[pii-guard] endpoint arm (offline): scanned {res['files']} shape snapshots covering {len(res['scanned_paths'])} routes")
        return _report_endpoint_results(res, "captured /api/* surface")
    if len(argv) > 1 and argv[1] == "--endpoints":
        base_url = argv[2] if len(argv) > 2 else "https://averagejoematt.com"
        res = scan_endpoints(base_url)
        print(
            f"[pii-guard] endpoint arm (live): scanned {len(res['scanned'])} payloads from {base_url} "
            f"({len(res['skipped'])} exempt: write-path/param) — literal arm {res['literal_arm']}"
        )
        return _report_endpoint_results(res, "live /api/* surface")
    site_dir = argv[1] if len(argv) > 1 else os.path.join(_ROOT, "site")
    if not os.path.isdir(site_dir):
        print(f"[pii-guard] site dir not found: {site_dir}", file=sys.stderr)
        return 2
    res = scan_site(site_dir)
    print(f"[pii-guard] scanned {res['files']} files in {site_dir} — literal arm {res['literal_arm']}")
    if res["literal_arm"] == "skipped":
        print(
            "[pii-guard] NOTE: no personal denylist present (env PII_DENYLIST_JSON / "
            "config/pii_denylist.local.json) — literal arm skipped; structural + vice arms still enforced."
        )
    if res["violations"]:
        print(f"[pii-guard] ❌ {len(res['violations'])} violation(s) — blocking publish:", file=sys.stderr)
        for rel, arm, detail in res["violations"]:
            shown = detail if arm != "blocked-vice" else f"blocked term {detail!r}"
            print(f"    {rel}: [{arm}] {shown}", file=sys.stderr)
        return 1
    print("[pii-guard] ✅ clean — no guarded strings or PII on the public surface")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
