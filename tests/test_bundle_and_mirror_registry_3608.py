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

import json
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
    one-bundle violations may only go DOWN from the dated baseline. It reached
    ZERO on 2026-09-19 when #3608 box 1 deleted scripts/deploy.command, so the
    claim 'all deploy paths verifiably stage through one bundle' is now TRUE
    and this assertion is what keeps it true: a new hand-zipped deploy path
    cannot be registered as an accepted violation, only fixed."""
    violations = sorted(p for p, m in reg.BUNDLE_STAGING_SITES.items() if m["status"] == "known_violation")
    assert len(violations) <= reg.MAX_KNOWN_VIOLATIONS_2026_09_19, (
        f"known_violation count ({len(violations)}: {violations}) exceeds the frozen baseline "
        f"({reg.MAX_KNOWN_VIOLATIONS_2026_09_19}) — a new one-bundle violation was registered without becoming "
        "the SUBJECT of a fix. The count only ever moves down."
    )
    for path in violations:
        meta = reg.BUNDLE_STAGING_SITES[path]
        assert "#" in meta["notes"], f"known_violation entry {path!r} has no issue reference in its notes"


def test_the_one_bundle_claim_is_true_not_merely_ratcheted():
    """#3608 box 1's actual outcome, asserted as a POSITIVE rather than as a
    ceiling. `MAX_KNOWN_VIOLATIONS_2026_09_19 <= 0` would also pass if someone
    lowered the ceiling and left the violation registered under a different
    status word; this reads the statuses themselves."""
    assert reg.MAX_KNOWN_VIOLATIONS_2026_09_19 == 0, "the ratchet is shrink-only and reached 0 on 2026-09-19 — it may not be raised"
    violations = [p for p, m in reg.BUNDLE_STAGING_SITES.items() if m["status"] == "known_violation"]
    assert violations == [], f"a one-bundle violation is registered again: {violations}"
    assert not os.path.exists(os.path.join(REPO_ROOT, "scripts", "deploy.command")), (
        "scripts/deploy.command is back. It hand-zips mcp_server.py alone and replaces the WHOLE "
        "life-platform-mcp function with one file (the 2026-03 outage). Use "
        "`bash deploy/deploy_lambda.sh life-platform-mcp mcp_server.py` — #3608 box 1."
    )


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


def test_shell_discovery_ignores_a_trailing_comment_and_a_quoted_string(tmp_path):
    """The two shapes the 2026-09-06 first-character-is-# test could not tell
    apart from a real call (#3608 box 1). Both are MENTIONS; neither runs
    anything. If this test ever goes green by the scanner matching them, the
    registry's equality assertion starts failing on doc files instead of on
    deploy paths and people learn to edit the registry to silence it."""
    fake_root = tmp_path / "repo"
    (fake_root / "deploy").mkdir(parents=True)
    (fake_root / "scripts").mkdir(parents=True)
    (fake_root / "deploy" / "trailing.sh").write_text("#!/bin/bash\necho done  # aws lambda update-function-code --function-name x\n")
    (fake_root / "deploy" / "quoted.sh").write_text('#!/bin/bash\necho "aws lambda update-function-code is the thing we do NOT do"\n')
    found = reg.discover_shell_update_function_code_sites(str(fake_root))
    assert found == set(), f"token scanner false-positived on a mention: {found}"


def test_shell_discovery_still_catches_the_real_multiline_idiom(tmp_path):
    """The must-not-over-narrow control for the test above: the backslash
    continuation idiom every real deploy script uses is still a call site."""
    fake_root = tmp_path / "repo"
    (fake_root / "deploy").mkdir(parents=True)
    (fake_root / "scripts").mkdir(parents=True)
    (fake_root / "deploy" / "real.sh").write_text(
        '#!/bin/bash\naws lambda update-function-code \\\n  --function-name "$FN" \\\n  --zip-file "fileb://$ZIP"\n'
    )
    found = reg.discover_shell_update_function_code_sites(str(fake_root))
    assert found == {os.path.join("deploy", "real.sh")}, f"token scanner lost the real multi-line call site: {found}"


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


# ══════════════════════════════════════════════════════════════════════════
# 4. #3608 box 3 — the widened CI-mirror predicate (epic #3493 devex ROW5).
# ══════════════════════════════════════════════════════════════════════════


def test_every_mirror_site_declares_which_clause_admitted_it():
    for path, meta in reg.CI_MIRROR_SITES.items():
        assert meta.get("clause") in ("A", "B", "C"), f"{path}: missing/unknown admitting clause {meta.get('clause')!r}"


def test_mirror_clause_mix_matches_the_frozen_measurement():
    """The widening is a measured fact, not a claim: 3 prose-claim members
    became 30. If a later edit collapses the predicate back to prose-only (or
    quietly widens it to bare filenames, the 60-file corpus #3608 rejected),
    the mix moves and this reds with the real numbers."""
    from collections import Counter

    live = Counter(m["clause"] for m in reg.CI_MIRROR_SITES.values())
    assert dict(live) == reg.MIRROR_CLAUSE_BASELINE_2026_09_19, (
        f"CI-mirror clause mix moved: {dict(live)} vs frozen {reg.MIRROR_CLAUSE_BASELINE_2026_09_19}. "
        "Re-measure and re-freeze deliberately — see #3608 box 3."
    )


def test_the_non_push_mirror_legs_epic_3493_named_are_members():
    """ROW5's own two examples, asserted by name. The /qa battery joins under
    clause A (it already boasted); restart_verify's NON-PUSH gate leg
    (restart_verify_gates.py, which runs Docs CI's gate set locally) joins
    under clause C and was invisible to the prose-only predicate.

    Stated honestly: `deploy/restart_verify.py` itself is NOT a member and
    should not be — its single workflow reference is running prose about
    site-deploy auto-deploying a fix (`:309`), not a mirror of any check set.
    Its two mirroring legs (`restart_verify_truth.py`, `restart_verify_gates.py`)
    both are.
    """
    members = set(reg.CI_MIRROR_SITES)
    for required in (
        os.path.join(".claude", "skills", "qa", "SKILL.md"),
        "deploy/restart_verify_gates.py",
        "deploy/restart_verify_truth.py",
    ):
        assert required in members, f"{required} is not a registered CI-mirror site — #3608 box 3 requires it"


def test_required_check_contexts_are_read_from_the_posture_file():
    """Clause B's vocabulary must be DERIVED. A hand-typed context list would
    go stale the first time the owner renames a required check, and every file
    naming the new one would silently leave the registry."""
    contexts = reg.required_check_contexts()
    assert contexts, "no required-check contexts resolved from deploy/github_posture.json"
    posture = json.loads(_read("deploy/github_posture.json"))
    declared = [c["context"] for c in posture["main_required_checks_ruleset"]["required_status_checks"]]
    assert list(contexts) == declared


def test_mirror_discovery_admits_a_planted_workflow_path_reference(tmp_path):
    """Clause C's positive control — the shape the prose-only predicate missed."""
    fake_root = tmp_path / "repo"
    (fake_root / "scripts").mkdir(parents=True)
    (fake_root / "deploy").mkdir(parents=True)
    os.makedirs(str(fake_root / ".claude" / "skills"))
    (fake_root / "scripts" / "quiet_mirror.py").write_text("GATES = parse('.github/workflows/docs-ci.yml')\n")
    found = reg.discover_ci_mirror_sites(str(fake_root))
    assert found == {os.path.join("scripts", "quiet_mirror.py")}, f"clause C missed a planted workflow-path mirror: {found}"


def test_mirror_discovery_does_not_admit_a_bare_filename_mention(tmp_path):
    """The deliberate NON-member shape (#3608 box 3): a bare `site-deploy.yml`
    in running prose. Admitting it measured 60 files on the 2026-09-19 tree
    against the path form's 29 — a registry of everything that ever named a
    workflow is the gate people learn to skip."""
    fake_root = tmp_path / "repo"
    (fake_root / "scripts").mkdir(parents=True)
    (fake_root / "deploy").mkdir(parents=True)
    os.makedirs(str(fake_root / ".claude" / "skills"))
    (fake_root / "deploy" / "prose.py").write_text("# the standing site-deploy.yml auto-deploys it, so nothing to do here\n")
    found = reg.discover_ci_mirror_sites(str(fake_root))
    assert found == set(), f"bare-filename prose was admitted as a CI mirror: {found}"
