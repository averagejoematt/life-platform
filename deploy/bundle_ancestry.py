#!/usr/bin/env python3
"""
bundle_ancestry.py — is the tree we are about to ship a descendant of what is live? (#2377)

WHY THIS EXISTS
---------------
2026-08-08: an older CI run landed *after* a newer merge. Nothing refused it,
and nothing detected it, because a Lambda bundle carried no commit fingerprint —
`verify_deployed_symbol.sh` says it in its own header: "a fresh timestamp
routinely accompanies stale code." The ci-cd `concurrency` group serialises
CI-vs-CI on one ref; queued older runs still deploy in order after approval, and
a manual deploy has no mutex at all.

`build_bundle.py` now stages `build_info.json` `{git_sha, built_at, …}` into
every bundle. This module is the decision half: given the sha already deployed
and the sha we are about to ship, classify the move.

  same           deployed == shipping                        → OK (idempotent redeploy)
  fast_forward   deployed is a strict ANCESTOR of shipping    → OK (normal forward deploy)
  stale          shipping is a strict ANCESTOR of deployed    → REFUSE (the 08-08 race)
  diverged       neither is an ancestor of the other          → REFUSE (unrelated/rewritten history)
  unknown        no fingerprint on one side, or git can't resolve a sha → WARN, allow

`unknown` is deliberately permissive: functions last touched before this landed
carry no build_info, and refusing them would brick every deploy path on day one.
It is loud (non-silent) so the absence is visible rather than read as green.

The classification is a PURE function of two shas plus an ancestry oracle, so
the 08-08 scenario is replayable in an offline unit test with no AWS and no git.

CLI (used by deploy/verify_bundle_ancestry.sh):
    python3 deploy/bundle_ancestry.py --deployed <sha|-> --shipping <sha> [--mode preflight|postflight]

Exit codes: 0 = OK (or unknown/allowed), 1 = usage/internal error, 2 = REFUSED.
Set ALLOW_NON_FAST_FORWARD=1 to downgrade a refusal to a loud warning — the
deliberate-rollback escape hatch (shipping known-older code on purpose).
"""

import argparse
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

SAME = "same"
FAST_FORWARD = "fast_forward"
STALE = "stale"
DIVERGED = "diverged"
UNKNOWN = "unknown"

# Verdicts that mean "this deploy would move the fleet BACKWARDS or sideways".
REFUSING = (STALE, DIVERGED)

OVERRIDE_ENV = "ALLOW_NON_FAST_FORWARD"


def parse_build_info(raw):
    """Extract the git sha from a bundle's build_info.json text.

    Returns None for anything unusable (absent file → caller passes None,
    truncated JSON, wrong shape, empty sha). Never raises: an unreadable
    fingerprint must degrade to `unknown`, not crash a deploy.
    """
    if not raw:
        return None
    if isinstance(raw, dict):
        info = raw
    else:
        try:
            info = json.loads(raw)
        except (ValueError, TypeError):
            return None
    if not isinstance(info, dict):
        return None
    sha = info.get("git_sha")
    if not isinstance(sha, str):
        return None
    sha = sha.strip().lower()
    return sha or None


def git_is_ancestor(maybe_ancestor, descendant, repo_root=REPO_ROOT):
    """True iff `maybe_ancestor` is an ancestor of `descendant` in this checkout.

    Returns None when git cannot answer (either sha not present locally — a
    shallow clone, or a commit from a branch this checkout never fetched).
    None propagates to an `unknown` verdict; it is NEVER silently treated as
    False, which would turn "I can't tell" into a bogus `diverged` refusal.
    """
    for sha in (maybe_ancestor, descendant):
        try:
            probe = subprocess.run(
                ["git", "cat-file", "-e", f"{sha}^{{commit}}"],
                cwd=repo_root,
                capture_output=True,
                timeout=30,
            )
        except Exception:
            return None
        if probe.returncode != 0:
            return None
    try:
        proc = subprocess.run(
            ["git", "merge-base", "--is-ancestor", maybe_ancestor, descendant],
            cwd=repo_root,
            capture_output=True,
            timeout=30,
        )
    except Exception:
        return None
    if proc.returncode == 0:
        return True
    if proc.returncode == 1:
        return False
    return None  # 128 etc. — git itself failed


def classify(deployed_sha, shipping_sha, is_ancestor=git_is_ancestor):
    """Classify a deploy move. Pure given the `is_ancestor` oracle.

    `is_ancestor(a, b)` must return True / False / None (can't tell).
    """
    if not deployed_sha or not shipping_sha:
        return UNKNOWN
    deployed_sha = deployed_sha.strip().lower()
    shipping_sha = shipping_sha.strip().lower()
    if deployed_sha == shipping_sha:
        return SAME
    # A short sha on either side still identifies the same commit — treat a
    # clean prefix match as identity so a `rev-parse --short` fingerprint from
    # an older builder doesn't read as `diverged`.
    if len(deployed_sha) != len(shipping_sha):
        short, long = sorted((deployed_sha, shipping_sha), key=len)
        if len(short) >= 7 and long.startswith(short):
            return SAME
    forward = is_ancestor(deployed_sha, shipping_sha)
    if forward is None:
        return UNKNOWN
    if forward:
        return FAST_FORWARD
    backward = is_ancestor(shipping_sha, deployed_sha)
    if backward is None:
        return UNKNOWN
    if backward:
        return STALE
    return DIVERGED


def explain(verdict, deployed_sha, shipping_sha, function_name=None, mode="preflight"):
    """One honest human line per verdict — what deploy paths print."""
    who = f" for {function_name}" if function_name else ""
    dep = (deployed_sha or "none")[:8]
    ship = (shipping_sha or "none")[:8]
    if verdict == SAME:
        return f"[ancestry] ✅ {mode}{who}: deployed sha == shipping sha ({ship})"
    if verdict == FAST_FORWARD:
        return f"[ancestry] ✅ {mode}{who}: {dep} → {ship} is a fast-forward"
    if verdict == STALE:
        return (
            f"[ancestry] ❌ {mode}{who}: REFUSING to ship {ship} over {dep} — "
            f"the shipping tree is an ANCESTOR of what is already live (this is the 2026-08-08 race). "
            f"Rebase/re-run from the newer commit, or set {OVERRIDE_ENV}=1 if this is a deliberate rollback."
        )
    if verdict == DIVERGED:
        return (
            f"[ancestry] ❌ {mode}{who}: REFUSING — {ship} and the live {dep} have diverged "
            f"(neither is an ancestor of the other). Deploy from an up-to-date main, "
            f"or set {OVERRIDE_ENV}=1 to override."
        )
    return (
        f"[ancestry] ⚠️  {mode}{who}: ancestry UNKNOWN (deployed={dep}, shipping={ship}) — "
        f"no readable build_info.json on one side, or git cannot resolve a sha here. "
        f"Allowing, but this deploy is unverified."
    )


def postflight_ok(landed_sha, expected_sha, is_ancestor=git_is_ancestor):
    """Postflight is stricter than preflight: what landed must BE what we shipped.

    A fast-forward is not good enough here — if the bundle now live is a
    descendant of ours, somebody else's deploy overwrote ours between our upload
    and our read, which the operator needs to know about.
    """
    verdict = classify(landed_sha, expected_sha, is_ancestor=is_ancestor)
    return verdict in (SAME, UNKNOWN), verdict


def main(argv=None):
    ap = argparse.ArgumentParser(description="Classify a deploy move by bundle commit ancestry (#2377).")
    ap.add_argument("--deployed", required=True, help="sha read from the LIVE bundle's build_info.json ('-' or '' = absent)")
    ap.add_argument("--shipping", required=True, help="sha of the tree being deployed")
    ap.add_argument("--mode", default="preflight", choices=["preflight", "postflight"])
    ap.add_argument("--function", default=None, help="function name, for the message only")
    ap.add_argument("--repo", default=REPO_ROOT, help="checkout to resolve ancestry in (default: this repo)")
    args = ap.parse_args(argv)

    deployed = None if args.deployed in ("-", "", "none") else args.deployed
    shipping = None if args.shipping in ("-", "", "none") else args.shipping

    def oracle(a, b):
        return git_is_ancestor(a, b, repo_root=args.repo)

    if args.mode == "postflight":
        ok, verdict = postflight_ok(deployed, shipping, is_ancestor=oracle)
        if ok:
            print(explain(verdict, deployed, shipping, args.function, mode="postflight"))
            return 0
        print(
            f"[ancestry] ❌ postflight{' for ' + args.function if args.function else ''}: "
            f"the LIVE bundle is {(deployed or 'none')[:8]}, not the {(shipping or 'none')[:8]} this run shipped "
            f"(verdict={verdict}). Another deploy landed on top of yours — re-deploy from the newest commit."
        )
        return 2

    verdict = classify(deployed, shipping, is_ancestor=oracle)
    print(explain(verdict, deployed, shipping, args.function))
    if verdict in REFUSING:
        if os.environ.get(OVERRIDE_ENV) == "1":
            print(f"[ancestry] ⚠️  {OVERRIDE_ENV}=1 — proceeding anyway (deliberate rollback).")
            return 0
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
