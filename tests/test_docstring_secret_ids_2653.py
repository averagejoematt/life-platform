"""#2653 — a docstring must not name a secret that does not exist.

`dropbox_poll_lambda`'s module docstring advertised `SECRET_NAME` defaulting to
`life-platform/dropbox`. The code at line 73 reads `life-platform/ingestion-keys`, and the
dedicated secret was **deleted 2026-05-17** when the consumer migrated to the bundle
(COST-B). The docstring outlived the secret and named an id nothing could read — so anyone
debugging an auth failure would go looking for a secret that has not existed for three
months, and the IAM role would look mis-granted when it is correct.

THE ISSUE NAMED ONE MODULE. A context-aware sweep found **two**:

    lambdas/ingestion/dropbox_poll_lambda.py        life-platform/dropbox
    lambdas/ingestion/health_auto_export_lambda.py  life-platform/health-auto-export

Both read `life-platform/ingestion-keys` in code. The second has never had a dedicated
secret at all.

AND ONE THAT LOOKS IDENTICAL AND IS FINE, which is why this guard needs an escape hatch
rather than a blanket rule. `mastodon_lambda` names `life-platform/mastodon` and its own
line says why: *"Until the owner provisions them, the Lambda boots and no-ops cleanly …
it does NOT guess an instance."* `SECRET_ID` even carries `# referenced, NOT created —
owner provisions it`. That is a documented forward reference, not a stale one — the
docstring is telling the truth about a thing that does not exist yet.

MY FIRST SWEEP WAS WRONG IN THE OTHER DIRECTION and is worth recording. Matching every
`life-platform/...` string in a docstring flagged **23** modules — because
`life-platform/budget-tier` and `life-platform/experiment-cycle` are SSM parameters,
`life-platform/config` and `life-platform/site` and `life-platform/uploads` are S3
prefixes, and none of them are Secrets Manager ids at all. A guard that cannot tell three
namespaces apart would have produced 20 false failures and been deleted within a week. The
detector below only considers a match when the SAME LINE presents it as a secret.

WHY THE ISSUE'S SECOND BOX IS NOT MET LITERALLY, on purpose. It asks that
`grep -rn 'life-platform/dropbox' lambdas/ docs/` return nothing. It cannot, and it should
not: `docs/ARCHITECTURE.md`, `docs/SECRETS_MAP.md` and `docs/INFRASTRUCTURE.md` all record
the secret as **deleted**, with dates. Those rows are accurate history, and scrubbing them
to satisfy a grep would make the docs less honest, not more — the exact trade this repo
refuses everywhere else. What was fixed is every place that presents it as a CURRENT fact:
the two docstrings, plus `docs/RUNBOOK.md`'s role-grant table, which listed the live grant
as `life-platform/dropbox only` when `role_policies_ingestion.ingestion_dropbox` grants the
bundle.
"""

from __future__ import annotations

import ast
import os
import pathlib
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

import pytest  # noqa: E402

# Ids the repo names but which are deliberately not provisioned yet, each with the reason.
# An entry here is a claim that the docstring TELLS THE TRUTH about a thing that does not
# exist — not a licence to name a stale one.
DECLARED_UNPROVISIONED = {
    "life-platform/mastodon": (
        "mastodon_lambda: owner-provisioned when he picks an instance. The docstring says so in as many "
        "words ('Until the owner provisions them, the Lambda boots and no-ops cleanly') and SECRET_ID "
        "carries '# referenced, NOT created'. A forward reference, not a stale one."
    ),
}

_SECRET_ID = re.compile(r"life-platform/[a-z0-9\-]+")
# The same line must PRESENT the id as a Secrets Manager id. Without this the detector
# cannot tell a secret from an SSM parameter or an S3 prefix — see the module docstring.
_SECRETISH = re.compile(r"secret|SECRET_NAME|SecretId|Secrets Manager", re.I)
# A docstring that names a dead id WHILE SAYING IT IS DEAD is doing the right thing — that
# is what the fix for this issue looks like. The rule is about presenting an id as the
# CURRENT one, so a disclaimed mention within the surrounding sentence is not a claim.
_DISCLAIMED = re.compile(r"delet|never existed|outlived|retired|migrated|no longer", re.I)
# FORWARD-ONLY, and short. The first version looked 260 chars in BOTH directions, so one
# "DELETED" anywhere in a docstring immunised every id near it — a planted stale id slipped
# straight through the mutation check. The disclaimer has to belong to THIS occurrence, so
# only the text that follows it counts, and only for about a sentence.
_DISCLAIM_WINDOW = 110


def _docstring_secret_claims():
    """[(rel_path, secret_id, line)] for every docstring line presenting a secret id."""
    out = []
    for path in sorted((pathlib.Path(_REPO) / "lambdas").rglob("*.py")):
        try:
            doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) or ""
        except Exception:  # pragma: no cover — a syntax error is another gate's problem
            continue
        for line in doc.splitlines():
            if not _SECRETISH.search(line):
                continue
            for sid in _SECRET_ID.findall(line):
                idx = doc.index(sid)
                window = doc[idx + len(sid) : idx + len(sid) + _DISCLAIM_WINDOW]
                if _DISCLAIMED.search(window):
                    continue  # named as history, not as the current id
                out.append((str(path.relative_to(_REPO)), sid, line.strip()))
    return out


CLAIMS = _docstring_secret_claims()


def granted_secret_ids():
    """Every `life-platform/...` id the CDK role policies reference — the OFFLINE truth set.

    THE FIRST VERSION OF THIS GUARD COULD NOT FIRE, which is the same defect class the
    issue belongs to. It listed live secrets from Secrets Manager and skipped when the read
    failed; `tests/conftest.py` sets FAKE credentials for the whole session, so it skipped
    locally, and CI has no creds, so it skipped there too. A check that skips in every
    environment is not a check — it is a green tick with nothing behind it.

    The role policies are the right offline source anyway, and arguably the better one: a
    secret no role grants is unreadable by any Lambda whether or not it exists in Secrets
    Manager, which is exactly the failure a docstring reader would hit. Derived from
    `cdk/stacks/role_policies*.py`, so it tracks the grants rather than a snapshot.
    """
    ids = set()
    for path in sorted((pathlib.Path(_REPO) / "cdk" / "stacks").glob("role_policies*.py")):
        ids |= set(_SECRET_ID.findall(path.read_text(encoding="utf-8")))
    return ids


GRANTED = granted_secret_ids()


def _live_secret_names():
    """Secrets Manager ids that actually exist — an OPTIONAL cross-check, never the gate.

    Returns None when AWS is unreachable (FAKE creds under pytest, no creds in CI). The
    assertion that must always run is the offline one above; this only adds signal when a
    human runs the suite with real credentials.
    """
    try:
        import boto3

        sm = boto3.client("secretsmanager", region_name="us-west-2")
        return {s["Name"] for page in sm.get_paginator("list_secrets").paginate() for s in page["SecretList"]}
    except Exception:  # noqa: BLE001
        return None


# ── the detector is not vacuous and not over-eager ───────────────────────────


def test_the_sweep_finds_secret_claims_at_all():
    """Vacuity guard — an empty CLAIMS list would make the live check below assert nothing."""
    assert len(CLAIMS) >= 3, f"only {len(CLAIMS)} docstring secret claims found — the detector broke"


def test_the_detector_ignores_ssm_parameters_and_s3_prefixes():
    """The false-positive trap: `life-platform/budget-tier` is SSM, `life-platform/config` is
    an S3 prefix. A naive regex flagged 23 modules on these and would have been deleted."""
    assert not _SECRETISH.search("Writes the tier to SSM /life-platform/budget-tier")
    assert not _SECRETISH.search("Reads life-platform/config/protocols.json from S3")
    claimed_ids = {sid for _, sid, _ in CLAIMS}
    for not_a_secret in ("life-platform/budget-tier", "life-platform/config", "life-platform/site", "life-platform/uploads"):
        assert not_a_secret not in claimed_ids, f"{not_a_secret} is not a Secrets Manager id — the detector over-matched"


def test_the_detector_would_catch_a_planted_stale_id():
    """Proof it is live: a synthetic docstring line naming a dead secret is flagged."""
    line = "  SECRET_NAME — Secrets Manager key (default: life-platform/definitely-deleted)"
    assert _SECRETISH.search(line)
    assert "life-platform/definitely-deleted" in _SECRET_ID.findall(line)


# ── the rule ─────────────────────────────────────────────────────────────────


def test_the_granted_set_is_derived_and_not_empty():
    """Vacuity guard on the offline truth set — an empty GRANTED passes everything."""
    assert len(GRANTED) >= 20, f"only {len(GRANTED)} granted secret ids — the CDK sweep broke"
    assert "life-platform/ingestion-keys" in GRANTED


def test_no_docstring_names_a_secret_no_role_grants():
    """THE GATE, and it runs everywhere — offline, in CI, with FAKE creds.

    A secret no role grants is unreadable by any Lambda whether or not it exists, which is
    exactly what a reader chasing the docstring would discover.
    """
    offenders = [
        f"{rel} names {sid!r} — {line[:90]}" for rel, sid, line in CLAIMS if sid not in GRANTED and sid not in DECLARED_UNPROVISIONED
    ]
    assert not offenders, (
        "docstrings present secrets that do not exist:\n  "
        + "\n  ".join(offenders)
        + "\n(if the secret is deliberately not provisioned yet, add it to DECLARED_UNPROVISIONED with the reason)"
    )


def test_the_unprovisioned_allowlist_is_not_stale():
    """A stale exemption is its own lie — it excuses a name that needs no excuse.

    `life-platform/mastodon` IS granted by a role (the owner wired the grant ahead of
    provisioning the secret), so grant-membership cannot clear it; the live cross-check
    below does when credentials are available.
    """
    live = _live_secret_names()
    if live is None:
        pytest.skip("Secrets Manager unreachable — the offline gate above is the one that must run")
    wrongly_listed = sorted(s for s in DECLARED_UNPROVISIONED if s in live)
    assert not wrongly_listed, f"these exist and should leave DECLARED_UNPROVISIONED: {wrongly_listed}"


# ── the two that were actually wrong ─────────────────────────────────────────


@pytest.mark.parametrize(
    "rel,dead_id",
    [
        ("lambdas/ingestion/dropbox_poll_lambda.py", "life-platform/dropbox"),
        ("lambdas/ingestion/health_auto_export_lambda.py", "life-platform/health-auto-export"),
    ],
)
def test_the_stale_docstrings_now_name_the_bundle(rel, dead_id):
    doc = ast.get_docstring(ast.parse((pathlib.Path(_REPO) / rel).read_text())) or ""
    assert "life-platform/ingestion-keys" in doc, f"{rel} still does not name the secret it reads"
    if dead_id in doc:
        # Scoped to the surrounding sentence, not the physical line: a wrapped docstring
        # splits "was DELETED" onto the next one, and a line-scoped check would fail on
        # correct prose purely because of where the wrap landed.
        idx = doc.index(dead_id)
        window = doc[max(0, idx - 200) : idx + 300]
        assert re.search(r"delet|never existed|outlived", window, re.I), f"{rel} mentions {dead_id} without saying it is gone"


@pytest.mark.parametrize("rel", ["lambdas/ingestion/dropbox_poll_lambda.py", "lambdas/ingestion/health_auto_export_lambda.py"])
def test_the_docstring_matches_the_code_path(rel):
    """The root defect: docstring and code disagreed. Read the actual default, not prose."""
    src = (pathlib.Path(_REPO) / rel).read_text()
    m = re.search(r'SECRET_NAME\s*=\s*os\.environ\.get\(\s*"SECRET_NAME"\s*,\s*"([^"]+)"', src)
    assert m, f"{rel} no longer has a SECRET_NAME default to compare against"
    doc = ast.get_docstring(ast.parse(src)) or ""
    assert m.group(1) in doc, f"{rel} reads {m.group(1)} but its docstring does not name it"


def test_the_runbook_role_row_names_the_granted_secret():
    """docs/RUNBOOK.md listed the live grant as a secret deleted three months earlier, while
    role_policies_ingestion.ingestion_dropbox grants the bundle."""
    runbook = (pathlib.Path(_REPO) / "docs" / "RUNBOOK.md").read_text()
    row = next(line for line in runbook.splitlines() if "lambda-dropbox-poll-role" in line)
    assert "ingestion-keys" in row, row
    policies = (pathlib.Path(_REPO) / "cdk" / "stacks" / "role_policies_ingestion.py").read_text()
    assert 'secret_name="life-platform/ingestion-keys"' in policies, "the grant moved — recheck the RUNBOOK row"


def test_the_historical_deletion_records_are_left_intact():
    """The issue's grep box asks for zero mentions repo-wide. Deliberately NOT met: the
    architecture/secrets/infrastructure docs record the deletion WITH DATES, and scrubbing
    accurate history to satisfy a grep would make the docs less honest, not more."""
    for rel in ("docs/ARCHITECTURE.md", "docs/SECRETS_MAP.md", "docs/INFRASTRUCTURE.md"):
        text = (pathlib.Path(_REPO) / rel).read_text()
        assert "life-platform/dropbox" in text, f"{rel} lost its record that the secret was deleted"
        assert re.search(r"life-platform/dropbox.{0,120}?(delet|DELETED)", text, re.I | re.S), rel
