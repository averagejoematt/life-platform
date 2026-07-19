"""scripts/data_governance_registry.py — non-owner-PII DDB partition registry (#1350).

Mirrors lambdas/phase_taxonomy.py's SOURCE_CLASS pattern: ONE explicit place a new
DDB partition that stores PII belonging to someone OTHER than Matthew must be
declared. tests/test_data_governance_retention_coverage.py enforces that every entry
here has a matching retention-policy row in docs/DATA_GOVERNANCE.md — either a
SIGNED row naming a window the code reads, or the explicit UNSIGNED marker while a
decision is pending (#1350's [gate:owner] acceptance criterion).

Why this lives in scripts/, not lambdas/: unlike phase_taxonomy.py (a real runtime
dependency of data_export_lambda.py and the reset tooling), this registry is a
doc/test-time concern only — nothing in the deployed Lambda bundle imports it. It
sits beside its checker (scripts/check_doc_facts.py) rather than riding in every
function's code bundle for no runtime reason (#781's "ONE bundle" is for what
Lambdas actually need at runtime).

Adding a new entry: any time a Lambda starts writing a DDB item that (a) is NOT
under Matthew's personal partitions and (b) carries PII (plaintext contact info,
personal narrative, etc.) belonging to someone else, add it here with the label
that must appear as a docs/DATA_GOVERNANCE.md retention-table row. The guard test
fails immediately until that row exists (as UNSIGNED at minimum).
"""

NON_OWNER_PII_PARTITIONS: dict[str, dict[str, str]] = {
    "subscribers": {
        "pk_pattern": "USER#{USER_ID}#SOURCE#subscribers / EMAIL#{sha256(email)}",
        "doc_label": "Subscriber emails",
        "owner_module": "lambdas/web/email_subscriber_lambda.py",
        "runner": "deploy/subscriber_retention_purge.py",
        "issue": "#1350",
    },
}
