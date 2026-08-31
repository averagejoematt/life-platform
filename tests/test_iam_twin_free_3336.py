"""tests/test_iam_twin_free_3336.py — the IAM derivation guard (#3336, epic #2842).

THE INCIDENT (2026-08-30, docs/INCIDENT_LOG.md). `deploy/setup_remediation_role.sh`
was a hand-maintained twin of `infra/iam/github-actions-remediation-role.{trust,
permissions}.json`. Its header said "the JSON wins"; nothing enforced it; the twin was
the copy that RAN. One post-merge run put its stale documents live: 15 of the JSON's 17
statements (four grants gone, because `put-role-policy` replaces the whole document)
and the pre-#687 trust subject `repo:averagejoematt/life-platform:*` — any ref of a
public repo could assume the role for ≈6 minutes. `verify_oidc_iam.py --strict` (the
#401 dead-man) caught it; the JSON restored it. The guard that should have made the
drift impossible did not exist, and #3321's own test cemented the twin by asserting a
grant string INSIDE the shell script.

WHAT IS PROVED HERE (the derivation-guard primitive, docs/CHARTER.md)
  A. no file under `deploy/` embeds an IAM policy document (the `"Version": "2012-10-17"`
     + `"Statement"` + `"Effect"` shape) that names a role with a checked-in
     `infra/iam/<role>.*.json` — the ONLY copies of those documents are the JSON files
  B. mutation proofs for the detector: a planted heredoc and a planted Python string both
     RED; policy-READING code (`policy.get("Statement")`) and a document for a role that
     has no `infra/iam/` JSON (a Lambda exec role) are NOT findings — the guard is scoped
     to the OIDC identities `verify_oidc_iam.py` owns, nothing looser, nothing stricter
  C. the apply scripts are derived: every `--policy-document` / `--assume-role-policy-
     document` they pass is a `file://` reference, they name the governed JSON files, and
     their inline policy name equals what the verifier reads back
  D. the incident's exact regression is pinned at the source: every governed role's trust
     subject is scoped to this repo and none is the any-ref wildcard

All offline: the tests read repo files only; no AWS call.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
IAM_DIR = ROOT / "infra" / "iam"
DEPLOY_DIR = ROOT / "deploy"

if str(DEPLOY_DIR) not in sys.path:
    sys.path.insert(0, str(DEPLOY_DIR))

import verify_oidc_iam  # noqa: E402  (module-level imports are stdlib only; boto3 is inside main())

# ── the detector ─────────────────────────────────────────────────────────────
# An embedded IAM policy DOCUMENT is unambiguous: the policy-language version literal
# plus a Statement array with an Effect. Code that merely READS policies
# (`policy.get("Statement", [])`) never carries the version literal, so it is not a
# finding — see the mutation proofs below.
_DOC_MARKER = re.compile(r'"Version"\s*:\s*"2012-10-17"')
_STATEMENT = re.compile(r'"Statement"\s*:')
_EFFECT = re.compile(r'"Effect"\s*:')
_POLICY_DOC_ARG = re.compile(r"--(?:assume-role-)?policy-document\s+(\S+)")

SCANNED_SUFFIXES = (".sh", ".py")


def governed_roles() -> dict[str, dict[str, Path]]:
    """Every role with a checked-in document under infra/iam/ → its trust/permissions paths."""
    roles: dict[str, dict[str, Path]] = {}
    for p in sorted(IAM_DIR.glob("*.json")):
        stem = p.name
        for kind in ("trust", "permissions"):
            suffix = f".{kind}.json"
            if stem.endswith(suffix):
                roles.setdefault(stem[: -len(suffix)], {})[kind] = p
    return roles


def find_inline_policy_documents(text: str, rel_path: str, roles) -> list[str]:
    """Findings for ONE file's text: one line per governed role the embedded document names."""
    if not (_DOC_MARKER.search(text) and _STATEMENT.search(text) and _EFFECT.search(text)):
        return []
    return [
        f"{rel_path}: embeds an IAM policy document that names {role} — the only copy of that role's "
        f"documents is infra/iam/{role}.*.json; apply it with --policy-document file://… instead"
        for role in sorted(roles)
        if role in text
    ]


def sweep(root: Path, roles) -> list[str]:
    findings: list[str] = []
    for p in sorted(root.rglob("*")):
        if p.suffix not in SCANNED_SUFFIXES or not p.is_file():
            continue
        findings.extend(find_inline_policy_documents(p.read_text(encoding="utf-8", errors="replace"), str(p.relative_to(ROOT)), roles))
    return findings


# ═════════════════════════════════════════════════════════════════════════════
# A. the guard, on the real tree
# ═════════════════════════════════════════════════════════════════════════════
def test_governed_roles_are_exactly_the_verifier_owned_identities():
    """The role set the guard protects is derived from infra/iam/ and must equal what
    verify_oidc_iam.py diffs against live — one registry, read from both ends."""
    roles = governed_roles()
    assert set(roles) == set(verify_oidc_iam.ROLES), (set(roles), set(verify_oidc_iam.ROLES))
    for role, files in roles.items():
        assert {"trust", "permissions"} <= set(files), f"{role} is missing a trust or permissions JSON"
        for p in files.values():
            doc = json.loads(p.read_text(encoding="utf-8"))
            assert doc["Version"] == "2012-10-17" and doc["Statement"], p


def test_no_deploy_script_embeds_a_policy_document_for_a_governed_role():
    findings = sweep(DEPLOY_DIR, governed_roles())
    assert not findings, "inline IAM policy twins under deploy/ (#3336):\n  " + "\n  ".join(findings)


# ═════════════════════════════════════════════════════════════════════════════
# B. mutation proofs — the detector against planted defects (no real file touched)
# ═════════════════════════════════════════════════════════════════════════════
_PLANTED_HEREDOC = """#!/usr/bin/env bash
ROLE="github-actions-remediation-role"
PERM=$(cat <<JSON
{"Version":"2012-10-17","Statement":[{"Sid":"Bedrock","Effect":"Allow","Action":"bedrock:InvokeModel","Resource":"*"}]}
JSON
)
aws iam put-role-policy --role-name "$ROLE" --policy-name remediation-permissions --policy-document "$PERM"
"""

_PLANTED_PY_STRING = '''
TRUST = """{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow", "Principal": {"Federated": "x"}, "Action": "sts:AssumeRoleWithWebIdentity"}]
}"""
iam.update_assume_role_policy(RoleName="github-actions-deploy-role", PolicyDocument=TRUST)
'''

_READER_ONLY = """
role = iam.get_role(RoleName="github-actions-remediation-role")
for st in policy.get("Statement", []):
    if st.get("Effect") == "Allow":
        actions.update(st["Action"])
"""

_UNGOVERNED_ROLE_DOC = """
ROLE_NAME="life-platform-email-subscriber-role"
aws iam create-role --role-name "$ROLE_NAME" --assume-role-policy-document '{
  "Version": "2012-10-17",
  "Statement": [{"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]
}'
"""


def test_detector_reds_on_a_planted_shell_heredoc_twin():
    found = find_inline_policy_documents(_PLANTED_HEREDOC, "deploy/planted.sh", governed_roles())
    assert len(found) == 1 and "github-actions-remediation-role" in found[0], found


def test_detector_reds_on_a_planted_python_string_twin():
    found = find_inline_policy_documents(_PLANTED_PY_STRING, "deploy/planted.py", governed_roles())
    assert len(found) == 1 and "github-actions-deploy-role" in found[0], found


def test_detector_ignores_code_that_only_reads_policies():
    assert find_inline_policy_documents(_READER_ONLY, "deploy/reader.py", governed_roles()) == []


def test_detector_ignores_documents_for_roles_without_a_checked_in_json():
    """A Lambda execution role bootstrapped inline (setup_email_subscriber.sh) has no
    infra/iam/ source of truth to twin — out of this guard's scope by construction,
    and NOT a licence: the moment such a role gains an infra/iam/ JSON, it is governed."""
    assert find_inline_policy_documents(_UNGOVERNED_ROLE_DOC, "deploy/setup_email_subscriber.sh", governed_roles()) == []


def test_planted_twin_in_a_tree_is_found_by_the_sweep(tmp_path):
    (tmp_path / "ok.sh").write_text('aws iam put-role-policy --policy-document "file://x.json"\n', encoding="utf-8")
    (tmp_path / "twin.sh").write_text(_PLANTED_HEREDOC, encoding="utf-8")
    (tmp_path / "notes.md").write_text(_PLANTED_HEREDOC, encoding="utf-8")  # not a scanned suffix
    found = sweep(tmp_path, governed_roles()) if tmp_path.is_relative_to(ROOT) else _sweep_outside_root(tmp_path)
    assert len(found) == 1 and "twin.sh" in found[0], found


def _sweep_outside_root(root: Path) -> list[str]:
    # tmp_path is normally outside the repo; relative_to(ROOT) would raise, so path-label by name.
    findings: list[str] = []
    for p in sorted(root.rglob("*")):
        if p.suffix in SCANNED_SUFFIXES and p.is_file():
            findings.extend(find_inline_policy_documents(p.read_text(encoding="utf-8"), p.name, governed_roles()))
    return findings


# ═════════════════════════════════════════════════════════════════════════════
# C. the apply scripts are DERIVED from the JSON, not parallel to it
# ═════════════════════════════════════════════════════════════════════════════
APPLY_SCRIPTS = {
    "github-actions-remediation-role": DEPLOY_DIR / "setup_remediation_role.sh",
    "github-actions-deploy-role": DEPLOY_DIR / "setup_github_oidc.sh",
}


@pytest.mark.parametrize("role", sorted(APPLY_SCRIPTS))
def test_apply_script_passes_only_file_references_and_names_the_governed_json(role):
    script = APPLY_SCRIPTS[role]
    text = script.read_text(encoding="utf-8")
    rel = script.relative_to(ROOT)

    args = _POLICY_DOC_ARG.findall(text)
    assert args, f"{rel}: no --policy-document at all — it no longer applies anything?"
    for arg in args:
        assert arg.strip('"').startswith("file://"), f"{rel}: --policy-document {arg} is not a file:// reference to infra/iam/"

    for kind in ("trust", "permissions"):
        assert f"{role}.{kind}.json" in text, f"{rel}: must apply infra/iam/{role}.{kind}.json by name"

    for verb in ("create-role", "update-assume-role-policy", "put-role-policy"):
        assert f"aws iam {verb}" in text, f"{rel}: lost the `aws iam {verb}` step"

    expected_policy_name = verify_oidc_iam.ROLES[role]["inline_policy_name"]
    assert (
        f'POLICY_NAME="{expected_policy_name}"' in text
    ), f"{rel}: inline policy name must be {expected_policy_name!r} — that is the name verify_oidc_iam.py reads back"
    assert "verify_oidc_iam.py" in text and "--strict" in text, f"{rel}: the apply must end with the read-only verifier as its proof"


def test_verifier_docstring_records_the_one_source_rule():
    doc = verify_oidc_iam.__doc__ or ""
    assert "#3336" in doc and "setup_remediation_role.sh" in doc and "file://" in doc


# ═════════════════════════════════════════════════════════════════════════════
# D. the incident's regression, pinned at the source
# ═════════════════════════════════════════════════════════════════════════════
def _trust_subjects(doc) -> list[str]:
    subs: list[str] = []
    for st in doc["Statement"]:
        like = st.get("Condition", {}).get("StringLike", {}).get("token.actions.githubusercontent.com:sub")
        eq = st.get("Condition", {}).get("StringEquals", {}).get("token.actions.githubusercontent.com:sub")
        for v in (like, eq):
            if isinstance(v, str):
                subs.append(v)
            elif isinstance(v, list):
                subs.extend(v)
    return subs


def test_remediation_role_trust_is_main_only():
    doc = json.loads((IAM_DIR / "github-actions-remediation-role.trust.json").read_text(encoding="utf-8"))
    assert _trust_subjects(doc) == ["repo:averagejoematt/life-platform:ref:refs/heads/main"]


@pytest.mark.parametrize("role", sorted(governed_roles()))
def test_no_governed_role_trusts_the_any_ref_wildcard(role):
    doc = json.loads((IAM_DIR / f"{role}.trust.json").read_text(encoding="utf-8"))
    subs = _trust_subjects(doc)
    assert subs, f"{role}: trust has no OIDC subject condition at all"
    for sub in subs:
        assert sub.startswith("repo:averagejoematt/life-platform:"), (role, sub)
        assert not sub.endswith(":*"), f"{role}: {sub!r} is the any-ref subject the 2026-08-30 twin put live"


def test_scanned_tree_is_the_deploy_dir_and_exists():
    assert DEPLOY_DIR.is_dir() and os.access(DEPLOY_DIR, os.R_OK)
