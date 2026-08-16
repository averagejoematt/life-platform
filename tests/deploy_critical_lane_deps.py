"""#2758 — THE single source of truth for the deploy-critical lane's dep set.

The ci-cd workflow's install step keeps the same four names LITERAL (so
``test_ci_pin_consistency`` can statically verify each is pinned, CQ-01), and
``test_deploy_critical_lane_imports_2758.test_workflow_install_list_matches_the_dep_module``
asserts exact equality between that literal list and ``LANE_THIRD_PARTY_DEPS``
— fork them in either direction and premerge reds. The lane-import guard in the
same file reads this tuple to decide which module-scope imports tests/ may use,
so the installed set and the checked set cannot drift apart silently.

Deliberately stdlib-only so it is importable anywhere, including the minimal
lane venv during collection.
"""

# The packages the deploy-critical lane pip-installs. Adding one here requires
# updating ci-cd.yml's literal list in the same commit — the parity test is
# what makes that a red instead of a convention.
LANE_THIRD_PARTY_DEPS = ("pytest", "boto3", "botocore", "hypothesis")

# Distribution → importable top-level module names it (or its hard deps) ships.
# Only names tests/ may import at MODULE SCOPE without crashing lane collection.
DEP_IMPORT_NAMES = {
    "pytest": {"pytest", "_pytest", "py", "pluggy", "iniconfig", "packaging"},
    "boto3": {"boto3", "s3transfer"},
    "botocore": {"botocore", "dateutil", "jmespath", "urllib3"},
    "hypothesis": {"hypothesis", "attr", "attrs", "sortedcontainers"},
}
