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
     seeds/content_filter.json (the policy-blocked categories) appears in published text.
  2. Structural PII (always-on) — US SSN, 16-digit card-like numbers, and
     non-allowlisted email addresses (the PII classes in DATA_GOVERNANCE.md).
  3. Literal denylist (best-effort) — partner name / employer / role / industry
     tokens loaded from a NON-committed source: env `PII_DENYLIST_JSON` (a JSON
     array, e.g. a CI secret) or the gitignored `config/pii_denylist.local.json`.
     Skipped with a notice when absent — the repo is PUBLIC, so these literals
     never live in git; the always-on arms still gate in public CI.

Usage:  python3 deploy/pii_surface_guard.py [site_dir]   # exit 1 on any violation

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
_CARD_RE = re.compile(r"\b\d{16}\b")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


def _blocked_vice_keywords() -> list:
    """The canonical public-content denylist, loaded ONLY from the committed
    policy file (seeds/content_filter.json `blocked_vice_keywords`) — never
    hardcoded here, so the literal category terms live in exactly one place.
    Fail-closed: if the policy can't be read or is empty, raise rather than
    silently scan with the vice arm disabled."""
    path = os.path.join(_ROOT, "seeds", "content_filter.json")
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
    if _CARD_RE.search(text):
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


def main(argv) -> int:
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
