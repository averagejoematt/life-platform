"""tests/test_bundle_and_mirror_registry_3608.py — the SET guard for #3608.

'All deploy paths verifiably stage through one bundle' was asserted, not true:
scripts/deploy.command (Finder-double-clickable) `zip -j`s mcp_server.py alone
and calls `aws lambda update-function-code` directly, stripping every bundled
module — and the existing guard (tests/test_deploy_bundle_paths.py) named FOUR
scripts by hand and missed this fifth, live one. This is the Charter's
registry + derivation-guard pattern (docs/CHARTER.md #1/#2) applied to the
one-bundle rule: deploy/bundle_and_mirror_registry.py is the registry, this
file is the guard that proves every consumer actually derives from it instead
of a second hand list drifting out from under the first.

GUARD THE SET, NOT THE INSTANCE. Every assertion below re-derives the live set
from the real tree (deploy/bundle_and_mirror_registry.py's own discovery
functions, which are regex/AST over source text — never a copy of the
registry) and compares it to the registry. A new bundle-staging path or
CI-mirror script that lands without a registry entry reds THIS test, by name,
whether or not anyone remembered to update a doc.

Scope, stated honestly (mirrors tests/test_time_invariant_helpers_1964.py's
own disclosure): the shell/workflow scanner is a real-vs-comment text match on
`aws lambda update-function-code`, not a shell parser — a script that
constructs that exact string dynamically (string concatenation, an eval) would
not be caught. None does today; a genuinely obfuscated call site is its own,
worse, incident class this guard does not claim to cover.
"""

import os
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "deploy"))

import bundle_and_mirror_registry as reg  # noqa: E402


def _read(rel_path: str) -> str:
    with open(os.path.join(REPO_ROOT, rel_path), encoding="utf-8") as f:
        return f.read()


# ══════════════════════════════════════════════════════════════════════════
# 1. Bundle-staging SET — every path that can put code into a Lambda.
# ══════════════════════════════════════════════════════════════════════════


def test_discovered_bundle_staging_sites_match_the_registry():
    """The live sweep and the registry must name exactly the same files.

    A NEW site (a script someone adds that calls update-function-code, a new
    CDK stack that constructs a Code.from_asset) shows up on the LEFT of this
    diff and reds by name — it is not silently absent from a doc, it fails a
    test. A site that gets DELETED (e.g. scripts/deploy.command someday) shows
    up on the RIGHT and also reds — the registry is asserted for EQUALITY, not
    subset, because unlike the #1964 file's iso-idiom ratchet, shrinking this
    set is a one-line registry edit an agent should make in the same PR that
    removes the site, not something to leave silently stale.
    """
    discovered = reg.discover_bundle_staging_sites()
    registered = set(reg.BUNDLE_STAGING_SITES)
    missing_from_registry = discovered - registered
    stale_in_registry = registered - discovered
    assert not missing_from_registry, (
        "New bundle-staging site(s) found outside deploy/bundle_and_mirror_registry.py's "
        f"BUNDLE_STAGING_SITES: {sorted(missing_from_registry)}. Register each with a status "
        "(sanctioned/known_violation/exempt) and a reason — see #3608."
    )
    assert not stale_in_registry, (
        f"deploy/bundle_and_mirror_registry.py names site(s) that no longer exist or no longer call "
        f"update-function-code / construct a Lambda code asset: {sorted(stale_in_registry)}. Prune them."
    )


def test_sanctioned_bundle_sites_actually_reference_build_bundle():
    """Every entry marked 'sanctioned' must contain textual evidence it stages
    through deploy/build_bundle.py — the flip side of the discovery sweep:
    proves the STATUS in the registry, not just the file's presence."""
    build_bundle_markers = ("build_bundle.py", "build_bundle.stage_tree", "build_bundle.stage_mcp", "staged_tree_asset")
    offenders = []
    for path, meta in reg.BUNDLE_STAGING_SITES.items():
        if meta["status"] != "sanctioned":
            continue
        text = _read(path)
        if not any(marker in text for marker in build_bundle_markers):
            offenders.append(path)
    assert not offenders, (
        f"Registry marks these 'sanctioned' but they no longer reference build_bundle.py: {offenders}. "
        "Either they regressed to hand-staging (fix the script) or the status is stale (fix the registry)."
    )


def test_known_bundle_violations_do_not_exceed_the_baseline():
    """Shrink-only ratchet (Charter primitive #3): the count of known
    one-bundle violations may only go DOWN from the dated baseline. This PR
    adds the guard without rewriting scripts/deploy.command (instrument
    first) — it still enforces that no SECOND hand-zipped deploy path can
    land without at minimum being registered and counted."""
    violations = sorted(p for p, m in reg.BUNDLE_STAGING_SITES.items() if m["status"] == "known_violation")
    assert len(violations) <= reg.MAX_KNOWN_VIOLATIONS_2026_09_06, (
        f"known_violation count ({len(violations)}: {violations}) exceeds the frozen baseline "
        f"({reg.MAX_KNOWN_VIOLATIONS_2026_09_06}) — a new one-bundle violation was registered without becoming "
        "the SUBJECT of a fix. The count only ever moves down."
    )
    for path in violations:
        meta = reg.BUNDLE_STAGING_SITES[path]
        assert "#" in meta["notes"], f"known_violation entry {path!r} has no issue reference in its notes"


def test_exempt_bundle_sites_state_a_reason():
    for path, meta in reg.BUNDLE_STAGING_SITES.items():
        if meta["status"] == "exempt":
            assert len(meta.get("notes", "")) > 20, f"exempt entry {path!r} needs a real reason, not a stub"


# ══════════════════════════════════════════════════════════════════════════
# 2. CI-mirror SET — local checks that claim to run what CI runs.
# ══════════════════════════════════════════════════════════════════════════


def test_discovered_ci_mirror_sites_match_the_registry():
    discovered = reg.discover_ci_mirror_sites()
    registered = set(reg.CI_MIRROR_SITES)
    missing_from_registry = discovered - registered
    stale_in_registry = registered - discovered
    assert not missing_from_registry, (
        f"New CI-mirror site(s) found outside CI_MIRROR_SITES: {sorted(missing_from_registry)}. A script/skill "
        "that claims parity with CI needs to be registered so the claim itself is inventoried — see #3608."
    )
    assert not stale_in_registry, f"CI_MIRROR_SITES names site(s) that no longer make the claim: {sorted(stale_in_registry)}. Prune them."


def test_ci_mirror_sites_still_contain_their_quoted_claim():
    """The flip side: each registered claim excerpt must still be live text in
    the file (word-for-word modulo whitespace/line-wrap), not a stale quote of
    prose that has since been edited away."""
    import re

    for path, meta in reg.CI_MIRROR_SITES.items():
        text = _read(path)
        normalized = re.sub(r"[#\s]+", " ", text)
        claim_normalized = re.sub(r"\s+", " ", meta["claim"]).strip()
        assert claim_normalized in normalized, f"{path}: registered claim {meta['claim']!r} not found in current file text"


# ══════════════════════════════════════════════════════════════════════════
# 3. Mutation evidence — the guard can actually FAIL (a gate must prove it).
# ══════════════════════════════════════════════════════════════════════════


def test_shell_discovery_catches_a_planted_hand_zipped_deploy(tmp_path):
    """The exact defect class: a NEW .command script that hand-zips and calls
    update-function-code directly, planted OUTSIDE the real tree so this test
    never mutates the repo, proving the scanner (not just the registry
    equality check) actually fires on the shape of bug #3608 found."""
    fake_root = tmp_path / "repo"
    (fake_root / "deploy").mkdir(parents=True)
    (fake_root / "scripts").mkdir(parents=True)
    planted = fake_root / "scripts" / "sneaky_deploy.command"
    planted.write_text(
        "#!/bin/bash\nzip -j /tmp/x.zip mcp_server.py\naws lambda update-function-code --function-name life-platform-mcp "
        "--zip-file fileb:///tmp/x.zip\n"
    )
    found = reg.discover_shell_update_function_code_sites(str(fake_root))
    assert found == {"scripts/sneaky_deploy.command"}, f"scanner did not catch the planted hand-zipped deploy: {found}"


def test_shell_discovery_ignores_a_commented_out_example():
    """A doc/comment MENTIONING the phrase (like this very registry's own
    module docstring) must not be swept up — structural, not grep-on-anything."""
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "deploy"))
        os.makedirs(os.path.join(d, "scripts"))
        with open(os.path.join(d, "deploy", "commented.sh"), "w") as f:
            f.write("#!/bin/bash\n# aws lambda update-function-code --function-name foo\necho hi\n")
        found = reg.discover_shell_update_function_code_sites(d)
        assert found == set(), f"scanner false-positived on a comment-only mention: {found}"


def test_cdk_discovery_catches_a_planted_direct_code_asset(tmp_path):
    fake_root = tmp_path / "repo"
    (fake_root / "cdk" / "stacks").mkdir(parents=True)
    planted = fake_root / "cdk" / "stacks" / "sneaky_stack.py"
    planted.write_text("code = _lambda.Code.from_asset('../somewhere')\n")
    found = reg.discover_cdk_code_asset_sites(str(fake_root))
    assert found == {os.path.join("cdk", "stacks", "sneaky_stack.py")}, f"CDK scanner missed a planted direct code asset: {found}"


def test_ci_mirror_discovery_catches_a_planted_claim(tmp_path):
    fake_root = tmp_path / "repo"
    (fake_root / "scripts").mkdir(parents=True)
    (fake_root / "deploy").mkdir(parents=True)
    os.makedirs(str(fake_root / ".claude" / "skills"))
    planted = fake_root / "scripts" / "sneaky_local_ci.py"
    planted.write_text("#!/usr/bin/env python3\n# This script mirrors the CI checks exactly, run it before you push.\n")
    found = reg.discover_ci_mirror_sites(str(fake_root))
    assert found == {os.path.join("scripts", "sneaky_local_ci.py")}, f"CI-mirror scanner missed a planted claim: {found}"
