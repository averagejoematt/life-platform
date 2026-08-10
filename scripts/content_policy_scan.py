"""
scripts/content_policy_scan.py — repo-wide content-policy gate (#354).

Scans public-facing content files for the blocked-category terms. Exits 1 on any
match not covered by the allowlist.

Scope: site/ pages, email lambdas, MCP tools — the surfaces that reach readers.
Internal docs (handovers/, docs/, seeds/) and archive directories are excluded.

Usage (run from repo root):
    python3 scripts/content_policy_scan.py

#2370: the vocabulary comes from the ER-06 NON-COMMITTED channel
(lambdas/privacy/content_filter_channel.py — env CONTENT_FILTER_JSON /
config/content_filter.local.json / the private S3 copy), the same source the
live site's runtime filter enforces — one definition of "blocked" everywhere,
and the category names never live in a tracked file. When no channel source is
available the scan SKIPS with a loud notice (exit 0) — public CI arms it by
injecting the CONTENT_FILTER_JSON secret. Violation output is MASKED: it names
the file/line, never the term (CI logs are public).
"""

import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories to scan (relative to repo root). Only public-facing surfaces.
SCAN_DIRS = [
    "site",
    "lambdas/emails",
    "mcp",
]

# Directories within the scan dirs to skip.
SKIP_SUBDIRS = {
    # site/legacy is deliberately NOT skipped (#1905): the preserved tree is
    # publicly reachable (HTTP 200) — static pages are never "screened at
    # runtime by the API", so it must pass the same content policy as the rest
    # of the published surface.
    "__pycache__",
    ".pytest_cache",
}

# Individual files explicitly allowed to contain blocked terms.
# #2370 emptied this set: the scanner, the MCP filter constants, and the LLM
# system prompts no longer carry the terms as tracked literals — every consumer
# derives them from the non-committed channel at runtime, so NOTHING in the
# scanned tree may legitimately contain one any more. Add entries back only with
# a written justification (and expect the reviewer to push back).
ALLOWLIST_FILES: set[str] = set()

# File extensions to scan (text only).
TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".html",
    ".md",
    ".txt",
    ".json",
    ".css",
}


def load_blocked_terms() -> list[str]:
    """Load blocked keywords from the ER-06 non-committed channel (#2370)."""
    lambdas_dir = os.path.join(REPO_ROOT, "lambdas")
    if lambdas_dir not in sys.path:
        sys.path.insert(0, lambdas_dir)
    from privacy import content_filter_channel  # noqa: PLC0415 — path set just above

    return content_filter_channel.blocked_keywords(require=False)


def is_allowlisted(rel_path: str) -> bool:
    rel_path = rel_path.replace("\\", "/")
    for allowed in ALLOWLIST_FILES:
        if rel_path == allowed:
            return True
    for skip in SKIP_SUBDIRS:
        if rel_path.startswith(skip + "/") or rel_path == skip:
            return True
    return False


def should_skip_dir(abs_dir: str, name: str) -> bool:
    rel = os.path.relpath(abs_dir, REPO_ROOT).replace("\\", "/")
    for skip in SKIP_SUBDIRS:
        if rel == skip or rel.startswith(skip + "/"):
            return True
    return name in {"__pycache__", ".pytest_cache", "node_modules", ".git"}


def build_term_pattern(term: str) -> re.Pattern:
    """Return a regex that matches the term as a whole word (case-insensitive)."""
    return re.compile(r"\b" + re.escape(term) + r"\b", re.IGNORECASE)


def scan_file(path: str, rel_path: str, patterns: list[tuple[str, re.Pattern]]) -> list[str]:
    """Return list of violation descriptions found in path."""
    violations = []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                for idx, (_term, pattern) in enumerate(patterns):
                    if pattern.search(line):
                        # #2370: NEVER echo the term or the line (CI logs are public)
                        violations.append(f"  {rel_path}:{lineno}: blocked term #{idx} (masked)")
    except (OSError, UnicodeDecodeError):
        pass
    return violations


def main() -> int:
    blocked = load_blocked_terms()
    if not blocked:
        # No channel source (public CI without the secret, or a bare local clone).
        # Skip VISIBLY — never scan with an empty vocabulary and call it a pass.
        print(
            "::warning title=content-policy-scan skipped::no content-filter channel source "
            "(env CONTENT_FILTER_JSON / config/content_filter.local.json / S3) — "
            "inject the CI secret to arm this gate (#2370)."
        )
        return 0

    patterns = [(term, build_term_pattern(term)) for term in blocked]
    print(f"[content-policy-scan] Scanning {len(SCAN_DIRS)} directories for {len(blocked)} blocked terms...")

    violations = []
    for scan_dir in SCAN_DIRS:
        abs_scan = os.path.join(REPO_ROOT, scan_dir)
        if not os.path.isdir(abs_scan):
            continue
        for dirpath, dirnames, filenames in os.walk(abs_scan):
            # Prune skipped dirs in-place.
            dirnames[:] = [d for d in dirnames if not should_skip_dir(os.path.join(dirpath, d), d)]

            for filename in filenames:
                ext = os.path.splitext(filename)[1].lower()
                if ext not in TEXT_EXTENSIONS:
                    continue
                abs_path = os.path.join(dirpath, filename)
                rel_path = os.path.relpath(abs_path, REPO_ROOT).replace("\\", "/")
                if is_allowlisted(rel_path):
                    continue
                violations.extend(scan_file(abs_path, rel_path, patterns))

    if violations:
        print(f"[content-policy-scan] FAIL — {len(violations)} violation(s):")
        for v in violations[:50]:
            print(v)
        if len(violations) > 50:
            print(f"  ... and {len(violations) - 50} more")
        print()
        print("To add a deliberate exception, add the path to ALLOWLIST_FILES in")
        print("scripts/content_policy_scan.py with a justification comment.")
        return 1

    print("[content-policy-scan] PASS — 0 violations found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
