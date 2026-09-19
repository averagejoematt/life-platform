"""#3620 (security ROW3) — the anonymous-read prefix set is a shrink-only ratchet.

`deploy/bucket_policy.json` is the one file in this repo where a one-line edit is
a data breach: adding a `Resource` to a `Principal: "*"` / `s3:GetObject` Allow
publishes an entire bucket prefix to the internet, and nothing in the suite
noticed. This test makes the set require a deliberate edit in two places.

Direction matters. GROWING the set must red (that is the breach shape). SHRINKING
it must not (a smaller public surface is never a fault, and forcing a second edit
to remove a prefix is how ratchets teach people to delete the ratchet).

The nightly half — live bucket policy vs this file — is a command in the existing
`drift` job of .github/workflows/config-drift.yml. This half is the PR-lane half:
the nightly cannot see a change that has not deployed yet, and the PR is where an
accidental Resource addition should be stopped.
"""

import json
import os

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_POLICY = os.path.join(_REPO, "deploy", "bucket_policy.json")
_RATCHET = os.path.join(_REPO, "deploy", "anonymous_read_prefixes.txt")
_BUCKET = "matthew-life-platform"


def _committed_prefixes():
    out = []
    with open(_RATCHET) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                out.append(line)
    return set(out)


def anonymous_read_prefixes(policy: dict) -> set:
    """Every prefix an anonymous principal may GetObject under, derived from a policy doc.

    Shared with the nightly leg's derivation by shape, not by import (the
    workflow reads a LIVE policy and this reads the repo twin); both must agree
    on what "anonymously readable" means, which is: Effect Allow, Principal "*",
    an action that includes s3:GetObject, on this bucket's ARN.
    """
    prefixes = set()
    for st in policy.get("Statement", []):
        if st.get("Effect") != "Allow":
            continue
        principal = st.get("Principal")
        if principal != "*" and principal != {"AWS": "*"}:
            continue
        actions = st.get("Action")
        actions = [actions] if isinstance(actions, str) else list(actions or [])
        if not any(a in ("s3:GetObject", "s3:*", "*") for a in actions):
            continue
        resources = st.get("Resource")
        resources = [resources] if isinstance(resources, str) else list(resources or [])
        for r in resources:
            head = f"arn:aws:s3:::{_BUCKET}/"
            if r.startswith(head):
                prefixes.add(r[len(head) :].split("/")[0].rstrip("*"))
    return prefixes


def test_no_prefix_was_added_without_the_ratchet():
    live = anonymous_read_prefixes(json.load(open(_POLICY)))
    committed = _committed_prefixes()
    added = live - committed
    assert not added, (
        f"deploy/bucket_policy.json grants anonymous s3:GetObject on {sorted(added)}, "
        f"which is NOT in deploy/anonymous_read_prefixes.txt. If this is intended, add it there "
        f"in the same PR and say in the PR body what a reader may now download."
    )


def test_shrinking_is_allowed():
    """A prefix listed but no longer granted is fine — and must be reported, not failed."""
    live = anonymous_read_prefixes(json.load(open(_POLICY)))
    committed = _committed_prefixes()
    removed = committed - live
    # No assertion on `removed` by design: shrink-only. This test exists to
    # document that direction and to print the residue when it is non-empty.
    if removed:
        print(f"anonymous-read prefixes retired since the ratchet was written: {sorted(removed)}")
    assert isinstance(removed, set)


def test_the_derivation_is_not_vacuous():
    """The control: a derivation that returned the empty set would pass test 1 forever."""
    live = anonymous_read_prefixes(json.load(open(_POLICY)))
    assert live, "derivation found NO anonymous-read prefixes — it broke, the policy did not"
    assert "site" in live, f"expected the site/ prefix to be public; derived {sorted(live)}"


def test_a_planted_addition_reds():
    """Must-fail control, run against a synthetic policy — never against the real file."""
    planted = {
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{_BUCKET}/raw/*",
            }
        ]
    }
    assert anonymous_read_prefixes(planted) == {"raw"}
    assert not (anonymous_read_prefixes(planted) <= _committed_prefixes()), "a planted raw/ grant would pass the ratchet"
