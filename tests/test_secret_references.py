#!/usr/bin/env python3
"""
tests/test_secret_references.py — Lambda source code secret name linter.

R13-F04: Prevents a class of deployment bug where Lambda source code
references a secret name (via os.environ.get or string literal) that
either doesn't exist in AWS or has been permanently deleted.

Root cause it prevents: The March 2026 Todoist-style 2-day outage where
a Lambda was deployed with a wrong SECRET_NAME default value that pointed
at a non-existent secret. No CI test caught it; alarm fired 2 days later.

Rules:
  SR1  Every secret name literal in Lambda source must be in KNOWN_SECRETS
       or DELETED_SECRETS (to surface deleted ones explicitly)
  SR2  No Lambda source may reference a DELETED secret by name
  SR3  Residual invariant on the extractor (see its docstring — it is NOT a
       near-miss-prefix typo detector, and says why)
  SR4  Sanity: every scanned file parsed, and at least some references found
  SR5  Positive + negative controls on the extractor itself: the documented
       root-cause shape is inside the scan surface, and prose is not (#3255)

Scope: lambdas/*.py and mcp/*.py and mcp_server.py

EXTRACTION IS AST-LEVEL, NOT LINE-LEVEL (#3255, 2026-08-27)
───────────────────────────────────────────────────────────
v1.0.0 read each file as text, matched quoted `life-platform/...` with a regex,
and dropped any LINE containing one of six identifier substrings (`SECRET_NAME`,
`secret_name`, ...) as a "false positive". Those identifiers sit on the same line
as the literal in the canonical form:

    SECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/todoits")

so the line-level suppression discarded the string literal along with the
identifier — and that line IS the March-2026 outage shape this module's own
docstring cites. Measured on `main` before the fix: 38 lines carrying a secret
literal were masked against 33 that reached SR1, and 4 real secret ids at 6 sites
were audited by nothing.

The fix is not a longer suppression list — the identifier and the literal are
different tokens, so the scanner reads TOKENS. `_extract_from_source` parses the
module with `ast` and collects string CONSTANTS that are exactly a secret name.
An identifier can never be a `Constant`, a comment is not in the AST at all, and a
docstring that merely mentions an id is one long constant that does not
full-match — so the suppression list has nothing left to suppress and is gone.
Post-fix: 0 masked, 69 references audited.

Run:  python3 -m pytest tests/test_secret_references.py -v

v1.0.0 — 2026-03-15 (R13-F04)
v2.0.0 — 2026-08-27 (#3255, epic #2578): AST token extraction; mask removed
"""

import ast
import os
import re
import sys

import pytest

# #416 / ADR-117: deploy-critical lane (secret-name literal references — outage guard).
pytestmark = pytest.mark.deploy_critical

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# ── Source directories to scan ────────────────────────────────────────────────
SCAN_PATHS = [
    os.path.join(ROOT, "lambdas"),
    os.path.join(ROOT, "mcp"),
    os.path.join(ROOT, "mcp_server.py"),
]

# Files to explicitly exclude
EXCLUDE_PATTERNS = [
    "__pycache__",
    "cdk.out",
    "deprecated_secrets.txt",
    "test_secret_references.py",  # this file
    "test_iam_secrets_consistency.py",  # already covers IAM layer
]

# ── Canonical known secrets ───────────────────────────────────────────────────
# Must stay in sync with test_iam_secrets_consistency.py KNOWN_SECRETS
# and ARCHITECTURE.md Secrets Manager table.
KNOWN_SECRETS = {
    "life-platform/whoop",
    "life-platform/withings",
    "life-platform/strava",
    "life-platform/garmin",
    "life-platform/eightsleep",
    "life-platform/ai-keys",
    "life-platform/habitify",
    "life-platform/ingestion-keys",
    "life-platform/mcp-api-key",
    "life-platform/notion",
    "life-platform/dropbox",
    "life-platform/todoist",  # TD-23 (2026-05-02): added to KNOWN; Phase 2.6 (2026-05-16) added to freshness checker monitoring
    "life-platform/site-api-ai-key",
    "life-platform/eightsleep-client",
    "life-platform/hevy",  # ADR-060 / SPEC_HEVY (2026-05-25)
    "life-platform/github-dispatch-token",  # ADR-064 (2026-05-29): remediation dispatcher PAT
    "life-platform/subscriber-token-secret",  # #106 (2026-05-30): dedicated HMAC signing key for subscriber tokens
    "life-platform/pexels",  # 2026-06-29: Pexels API key for editorial cover imagery (editorial_image.py)
    "life-platform/youtube",  # #1669 (epic #1668): inbound-social YouTube channel id (key `channel_id`); keyless RSS, owner-provisioned
    "life-platform/bluesky",  # #1676 (epic #1668): inbound-social Bluesky handle (key `handle`); keyless public AppView pull, owner-provisioned
    "life-platform/mastodon",  # #1676 (epic #1668): inbound-social Mastodon instance + handle (keys `instance`/`handle`); keyless public REST pull, owner-provisioned
    "life-platform/digest",  # #1623 (2026-07-26): milestone-digest recipients + reply-to; operator-provisioned, disarmed no-op until it exists
    "life-platform/continuity-contacts",  # #1400 (2026-08-10): continuity contacts for the Permanence Contract's dead-man's switch — real people's contact details, owner-provisioned, NEVER in git (DATA_GOVERNANCE). The switch runs disarmed (falls back to the operator address and reports contacts_configured=false) until it exists.
    "life-platform/telegram",  # #2364 (2026-08-09): coach chat — per-bot tokens + chat-id allow-list + webhook_secret; owner-provisioned via setup_telegram_bots.py
    # ── #3255 (2026-08-27): the four ids the line-level mask hid ──────────────
    # All four were ALREADY in test_iam_secrets_consistency.py's KNOWN_SECRETS and in
    # ARCHITECTURE.md's Secrets Manager table; only this registry — the one whose gate
    # could not see them — had drifted. Each verified provisioned in AWS on 2026-08-27
    # via `aws secretsmanager list-secrets --region us-west-2` before being added here;
    # none was added to make a red test green.
    "life-platform/google-tts",  # 2026-06-14 (ADR-087): Google Chirp 3:HD TTS key for the podcasts — lambdas/ai/google_tts.py, lambdas/ai/gemini_tts.py
    "life-platform/hevy-write",  # ADR-066 (2026-05-31): write-capable Hevy key, separate from the read key — lambdas/training/hevy_write_client.py
    "life-platform/ritual-token-secret",  # #769 (ADR-124): HMAC key for the evening-ritual one-tap links (mint: evening-nudge, verify: site-api)
    "life-platform/site-api-origin-secret",  # #815 R22-SEC-03 / #1589: the x-amj-origin CloudFront gate value, read at runtime by the AI-quality canary
    # life-platform/google-calendar removed — retired ADR-030 (v3.7.46)
}

# Secrets permanently deleted — any source reference is an SR2 violation.
DELETED_SECRETS = {
    "life-platform/api-keys",  # deleted 2026-03-15 (TB7-4)
    "life-platform/webhook-key",  # deleted 2026-03-14 (HANDOVER_v3.7.84)
    "life-platform/anthropic-api-key",  # Phase 1.4 (2026-05-16): orphan soft-deleted, permanent 2026-05-23
}

# NOTE (#3255): there is deliberately NO false-positive suppression list here any more.
# v1.0.0 carried `FALSE_POSITIVE_PATTERNS` — twelve substrings (`SECRET_NAME`,
# `secret_name`, `SecretString`, `get_secret_value`, ...) whose presence anywhere on a
# line dropped that whole line from the scan. Every entry named an IDENTIFIER, but the
# suppression was applied at LINE scope, so it also discarded the string literal beside
# the identifier. Reading string CONSTANTS out of the AST makes the whole category
# unrepresentable: `SECRET_NAME` the identifier is an `ast.Name`, never an `ast.Constant`,
# so it cannot be a false positive to suppress. Re-introducing a line-level (or
# substring) filter here re-introduces the defect — SR5 is the regression guard.

# A string constant is a secret reference iff it is EXACTLY a secret name.
# Full-match, not search: a docstring or a log message that merely mentions an id is one
# long constant and is not a live reference (docstring ids have their own gate,
# tests/test_docstring_secret_ids_2653.py), and an SSM path like
# `/life-platform/budget-tier` is not one either — it does not start at `life-platform`.
_SECRET_NAME_RE = re.compile(r"life-platform/[a-zA-Z0-9_\-]+")

# Convention: all secret names must have this prefix.
_CONVENTION_RE = re.compile(r"^life-platform/")


# ── File collection ───────────────────────────────────────────────────────────


def _collect_files():
    """Collect all Python source files to scan.

    P3.1 (2026-05-25): walks recursively to pick up files in
    lambdas/{ingestion,compute,coach,email,web,operational,intelligence}/.
    """
    files = []
    for path in SCAN_PATHS:
        if os.path.isfile(path) and path.endswith(".py"):
            files.append(path)
        elif os.path.isdir(path):
            for root, _, fnames in os.walk(path):
                if "__pycache__" in root:
                    continue
                for fname in fnames:
                    if not fname.endswith(".py"):
                        continue
                    if any(ex in fname for ex in EXCLUDE_PATTERNS):
                        continue
                    files.append(os.path.join(root, fname))
    return sorted(files)


def _extract_from_source(source, filename="<source>"):
    """Extract every secret-name string CONSTANT from Python source text.

    Returns list of (line_number, secret_name) tuples, in source order.

    Token-level by construction (#3255): only `ast.Constant` string nodes that
    full-match a secret name are collected, so identifiers, attribute names,
    comments and prose are structurally out of reach — no suppression list needed.
    Raises SyntaxError for unparseable source; the caller decides what that means.
    """
    tree = ast.parse(source, filename=filename)
    results = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _SECRET_NAME_RE.fullmatch(node.value):
            results.append((node.lineno, node.value))
    return sorted(results)


def _extract_secret_literals(filepath):
    """`_extract_from_source` over a file. Returns (refs, parse_error_or_None).

    A parse failure is RETURNED, never swallowed: v1.0.0's `except Exception: pass`
    meant a file the scanner could not read contributed zero references and said
    nothing, which is a silent false-green in a gate whose whole job is to notice
    what is missing. SR4 asserts the error list is empty.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()
    try:
        return _extract_from_source(source, filepath), None
    except SyntaxError as exc:
        return [], f"{os.path.relpath(filepath, ROOT)}: {type(exc).__name__}: {exc}"


# ── Pre-compute scan results once at module load ──────────────────────────────

_FILES = _collect_files()
_ALL_REFS: list = []
_PARSE_ERRORS: list = []
for _f in _FILES:
    _refs, _err = _extract_secret_literals(_f)
    if _err:
        _PARSE_ERRORS.append(_err)
    for _lineno, _name in _refs:
        _ALL_REFS.append((_f, _lineno, _name))


# ══════════════════════════════════════════════════════════════════════════════
# SR1 — Every referenced secret must be in KNOWN_SECRETS
# ══════════════════════════════════════════════════════════════════════════════


def test_sr1_all_secret_references_are_known():
    """SR1: Every 'life-platform/...' string literal in Lambda source must be
    a known or explicitly-deleted secret.

    Unknown names = typo, stale reference to rotated name, or new undocumented
    secret. The Todoist 2-day outage (Mar 2026) had a wrong default value that
    this test would have caught at CI time.

    Fix: Add to KNOWN_SECRETS here + ARCHITECTURE.md, or fix the source name.
    """
    violations = []
    for filepath, lineno, secret_name in _ALL_REFS:
        if secret_name in KNOWN_SECRETS:
            continue
        if secret_name in DELETED_SECRETS:
            continue  # SR2 handles these separately
        rel = os.path.relpath(filepath, ROOT)
        violations.append(f"  {rel}:{lineno} — '{secret_name}' not in KNOWN_SECRETS")

    assert not violations, (
        f"SR1 FAIL: {len(violations)} unrecognised secret name(s) in source code:\n"
        + "\n".join(violations)
        + "\n\nFix: Add to KNOWN_SECRETS in this file + ARCHITECTURE.md, "
        "or update source to use the correct secret name."
    )


# ══════════════════════════════════════════════════════════════════════════════
# SR2 — No source file may reference a deleted secret
# ══════════════════════════════════════════════════════════════════════════════


def test_sr2_no_deleted_secret_references():
    """SR2: Lambda source must not reference permanently deleted secrets.

    After deletion, any Lambda that tries to read the secret fails at runtime
    with ResourceNotFoundException. This test ensures source is cleaned up
    before the secret is destroyed.

    Fix: Update the source to use the replacement secret name and redeploy.
    """
    violations = []
    for filepath, lineno, secret_name in _ALL_REFS:
        if secret_name in DELETED_SECRETS:
            rel = os.path.relpath(filepath, ROOT)
            violations.append(f"  {rel}:{lineno} — '{secret_name}' has been permanently deleted")

    assert not violations, (
        f"SR2 FAIL: {len(violations)} source file(s) reference DELETED secret(s):\n"
        + "\n".join(violations)
        + "\n\nThese secrets no longer exist in AWS. Update source to use the "
        "replacement secret name and redeploy before traffic resumes."
    )


# ══════════════════════════════════════════════════════════════════════════════
# SR3 — Convention check: all secret names must have life-platform/ prefix
# ══════════════════════════════════════════════════════════════════════════════


def test_sr3_secret_names_follow_convention():
    """SR3: every extracted name carries the life-platform/ prefix.

    STATED SCOPE, measured 2026-08-27 (#3255) — read this before trusting the green.
    This is a RESIDUAL INVARIANT on the extractor, not a typo detector. `_SECRET_NAME_RE`
    already requires the prefix, so SR3 can only fail if that regex and `_CONVENTION_RE`
    are edited apart. It does NOT catch a near-miss prefix (`life-platorm/ai-keys`,
    `life_platform/ai-keys`) — such a string never becomes a ref in the first place.

    Why that gap was left open rather than closed here: a fuzzy-prefix rule was measured
    against the tree, and the ONLY near-miss it finds is `LifePlatform/AI` — the
    CloudWatch EMF namespace, at 67 sites. Closing the gap therefore requires a
    suppression list, which is precisely the machinery #3255 removed. It is a separate
    decision with its own trade-off, not a silent extension of this one.
    """
    violations = []
    for filepath, lineno, secret_name in _ALL_REFS:
        if not _CONVENTION_RE.match(secret_name):
            rel = os.path.relpath(filepath, ROOT)
            violations.append(f"  {rel}:{lineno} — '{secret_name}' does not follow life-platform/* convention")

    assert not violations, (
        f"SR3 FAIL: {len(violations)} secret name(s) violate naming convention:\n"
        + "\n".join(violations)
        + "\n\nAll secrets must start with 'life-platform/'."
    )


# ══════════════════════════════════════════════════════════════════════════════
# SR4 — Sanity: scanner must read every file, and find at least some references
# ══════════════════════════════════════════════════════════════════════════════


def test_sr4_secret_references_found():
    """SR4: The scanner must parse every file it walked and find some references.

    Guards against silent false-greens caused by a broken regex or empty
    SCAN_PATHS. If _ALL_REFS is empty it's the scanner that's broken, not
    the code.

    #3255 added the parse half: a file the scanner cannot read contributes zero
    references, which is indistinguishable from a clean file unless it is reported.
    """
    assert (
        not _PARSE_ERRORS
    ), f"SR4 FAIL: {len(_PARSE_ERRORS)} scanned file(s) did not parse, so they were audited " "by nothing:\n" + "\n".join(
        f"  {e}" for e in _PARSE_ERRORS
    )

    MIN_EXPECTED = 3  # conservative lower bound
    assert len(_ALL_REFS) >= MIN_EXPECTED, (
        f"SR4 FAIL: Only {len(_ALL_REFS)} secret references found across all source files. "
        f"Expected at least {MIN_EXPECTED}. The scanner may be broken — "
        f"check _SECRET_NAME_RE and SCAN_PATHS.\n"
        f"Files scanned: {len(_FILES)}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# SR5 — Controls on the extractor itself (#3255)
# ══════════════════════════════════════════════════════════════════════════════

# The canonical form the March-2026 outage took, and the form v1.0.0's line-level
# suppression discarded whole. Kept as source text so the control exercises the real
# extractor rather than a paraphrase of it.
_ENV_DEFAULT_SHAPE = 'import os\n\nSECRET_NAME = os.environ.get("SECRET_NAME", "life-platform/todoits")\n'


def test_sr5_the_env_default_shape_is_inside_the_scan_surface():
    """SR5 (positive control): the outage shape this module exists for is extracted.

    This is the assertion that fails if anyone re-introduces line-level or substring
    suppression. Before #3255 the extractor returned [] for this exact input while
    all four rules reported green — a gate that could not fail on its own root cause.
    """
    refs = _extract_from_source(_ENV_DEFAULT_SHAPE)
    assert refs == [(3, "life-platform/todoits")], (
        f"SR5 FAIL: the extractor returned {refs!r} for the canonical secret-default line. "
        'The `SECRET_NAME = os.environ.get("SECRET_NAME", ...)` form is the shape this '
        "module's docstring names as its reason to exist (#3255) — it must be scanned, and "
        "the typo'd name in it must then fail SR1."
    )
    assert "life-platform/todoits" not in KNOWN_SECRETS, "the control's typo'd name must be unknown, or it proves nothing"


def test_sr5_prose_and_identifiers_are_not_references():
    """SR5 (negative control): token scope, not line scope, in the other direction.

    Comments, docstrings and identifiers must NOT become references — otherwise the
    fix for the mask would just trade a false-green for a false-red, and the next
    author would reach for a suppression list again.
    """
    prose = (
        '"""Reads life-platform/whoop at boot; see life-platform/ai-keys."""\n\n'
        "# life-platform/webhook-key was deleted in 2026-03\n"
        "life_platform_whoop = 1\n"
    )
    assert _extract_from_source(prose) == [], "prose/identifier mentions must not be scanned as live references"


def test_sr5_a_file_that_cannot_be_parsed_is_reported_not_swallowed():
    """SR5: the parse failure is raised to the caller, which is what SR4 asserts on."""
    with pytest.raises(SyntaxError):
        _extract_from_source("def broken(:\n")


# ══════════════════════════════════════════════════════════════════════════════
# Standalone runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import subprocess

    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=ROOT,
    )
    sys.exit(result.returncode)
