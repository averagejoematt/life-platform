"""ER-06 — PII-to-public-surface guarantee (offline, GATING).

Editorial guardrails + docs/DATA_GOVERNANCE.md are *policy*; this is the
structural test that the published static site can't leak them. Runs the same
scanner the deploy uses (deploy/pii_surface_guard.py) over the committed `site/`
tree and fails on any guarded string or PII class. Offline (no AWS) so CI gates.

The scanner runs again, fail-closed, inside `sync_site_to_s3.sh` before the S3
sync — this test is the CI half of the same gate.
"""

import json
import os
import subprocess
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_ROOT, "deploy"))
import pii_surface_guard as guard  # noqa: E402

_SITE = os.path.join(_ROOT, "site")


def test_live_site_is_clean():
    """The committed public surface must have no guarded strings or PII.
    If this fails, a real leak is about to (or did) ship — fix the artifact,
    do not weaken the guard."""
    res = guard.scan_site(_SITE)
    assert not res["violations"], "PII/guardrail violations on the public surface:\n" + "\n".join(
        f"  {f}: [{arm}] {detail}" for f, arm, detail in res["violations"]
    )


def test_blocked_vice_keyword_is_caught():
    """Load-bearing: a policy-blocked term in a published artifact must fail.
    The literal term is pulled from the policy file, not written here."""
    kw = guard._blocked_vice_keywords()[0]
    hits = guard.scan_text(f"A 30-day challenge about {kw} for good.", vice=[kw], literals=[])
    assert any(arm == "blocked-vice" for arm, _ in hits)


def test_structural_pii_is_caught():
    """Load-bearing: SSN-shaped numbers and foreign emails fail."""
    ssn = guard.scan_text("SSN 123-45-6789 on file.", vice=[], literals=[])
    assert any(arm == "pii-ssn" for arm, _ in ssn)
    email = guard.scan_text("Reach me at someone.personal@gmail.com anytime.", vice=[], literals=[])
    assert any(arm == "pii-email" for arm, _ in email)


def test_allowlisted_email_passes():
    """The site's own contact + placeholders must NOT trip the email arm."""
    ok = guard.scan_text("Contact security@mattsusername.com or type your@email.com.", vice=[], literals=[])
    assert not any(arm == "pii-email" for arm, _ in ok)


def test_literal_denylist_arm_when_provided():
    """When a personal denylist is supplied, a guarded literal fails — and the
    violation never echoes the literal back."""
    hits = guard.scan_text("An aside mentioning Acme Corp in passing.", vice=[], literals=["acme corp"])
    assert any(arm == "literal-denylist" for arm, _ in hits)
    assert all("acme" not in detail.lower() for _, detail in hits)


def test_denylist_is_not_committed_in_cleartext():
    """The repo is PUBLIC: the personal denylist must never be tracked by git.
    Only a values-free example template may be committed."""
    tracked = subprocess.run(
        ["git", "ls-files", "config/pii_denylist.local.json"], cwd=_ROOT, capture_output=True, text=True
    ).stdout.strip()
    assert tracked == "", "config/pii_denylist.local.json must be gitignored, never committed"
    example = os.path.join(_ROOT, "config", "pii_denylist.example.json")
    assert os.path.exists(example), "ship a values-free config/pii_denylist.example.json template"
    with open(example) as f:
        terms = [t for t in json.load(f).get("terms", []) if not t.startswith("<")]
    assert terms == [], "the example denylist must contain no real values (placeholders only)"
