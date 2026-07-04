"""
scripts/content_policy_scan.py — repo-wide content-policy gate (#354).

Scans public-facing content files for blocked terms from seeds/content_filter.json.
Exits 1 on any match not covered by the allowlist.

Scope: site/ pages, email lambdas, MCP tools — the surfaces that reach readers.
Internal docs (handovers/, docs/, seeds/), implementation files that define the
filter, and archive directories are explicitly excluded.

Usage (run from repo root):
    python3 scripts/content_policy_scan.py

The same term list the live site's runtime filter enforces is the source of truth
here — one definition of "blocked" everywhere.
"""

import json
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
    "site/legacy",  # preserved verbatim; screened at runtime by the API
    "__pycache__",
    ".pytest_cache",
}

# Individual files explicitly allowed to contain blocked terms.
# These are implementation files where the terms appear as filter definitions,
# test fixtures, LLM system-prompt instructions, or content-policy text —
# not as personal content served to readers.
ALLOWLIST_FILES = {
    "scripts/content_policy_scan.py",  # this scanner (contains the terms as strings)
    "mcp/tools_lifestyle.py",  # _BLOCKED_VICE_KEYWORDS constant (filter definition)
    "mcp/tools_health.py",  # same pattern
    "mcp/handler.py",  # same pattern
    "mcp/core.py",  # same pattern
    # LLM system-prompt strings that enumerate blocked terms to instruct the model
    # what NOT to mention — necessary, never served to readers.
    "lambdas/emails/wednesday_chronicle_lambda.py",
    "lambdas/emails/coach_panel_podcast_lambda.py",
}

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
    """Load blocked keywords from seeds/content_filter.json."""
    path = os.path.join(REPO_ROOT, "seeds", "content_filter.json")
    with open(path, encoding="utf-8") as f:
        cf = json.load(f)
    terms = cf.get("blocked_vice_keywords", [])
    return [t.lower() for t in terms if t]


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
                for term, pattern in patterns:
                    if pattern.search(line):
                        violations.append(f"  {rel_path}:{lineno}: '{term}' found in: {line.rstrip()[:120]}")
    except (OSError, UnicodeDecodeError):
        pass
    return violations


def main() -> int:
    blocked = load_blocked_terms()
    if not blocked:
        print("[content-policy-scan] No blocked terms loaded — check seeds/content_filter.json")
        return 1

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
