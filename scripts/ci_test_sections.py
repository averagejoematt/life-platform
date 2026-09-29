#!/usr/bin/env python3
"""scripts/ci_test_sections.py — #4252: the named sections of the post-merge Unit Tests job.

ci-test.yml ran eleven test files one at a time, each as its own named step ("IAM policy
linter (test_role_policies.py)", "Upstream-API contract tests (...)", ...), and then ran
the whole suite with coverage, so each of those files ran twice on every push to main.
The eleven steps are gone. The coverage passes already run those files, and this script
keeps the labels: it reads the passes' JUnit XML and prints one line per label with that
file's counts. A failure is annotated with the label, so a red Unit Tests job still says
"IAM policy linter" instead of only a test id.

It is a REPORT, not a gate. It always exits 0. The coverage passes are what fail the job.
A label whose file ran no tests is reported with a warning, because a renamed file would
otherwise leave its label silently empty.

USAGE:
  python3 scripts/ci_test_sections.py /tmp/junit_parallel.xml /tmp/junit_serial.xml
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET  # nosec B405 — parses the job's own pytest output

# label -> test file. The labels are the step names the eleven steps carried, verbatim.
SECTIONS = {
    "Run unit tests": "tests/test_shared_modules.py",
    "IAM policy linter (test_role_policies.py)": "tests/test_role_policies.py",
    "CDK handler consistency linter (test_cdk_handler_consistency.py)": "tests/test_cdk_handler_consistency.py",
    "CDK S3 path linter (test_cdk_s3_paths.py)": "tests/test_cdk_s3_paths.py",
    "Safety module wiring linter (test_wiring_coverage.py)": "tests/test_wiring_coverage.py",
    "DynamoDB pattern linter (test_ddb_patterns.py)": "tests/test_ddb_patterns.py",
    "MCP registry integrity linter (test_mcp_registry.py)": "tests/test_mcp_registry.py",
    "Lambda handler integration linter (test_lambda_handlers.py)": "tests/test_lambda_handlers.py",
    "IAM/secrets consistency linter (test_iam_secrets_consistency.py)": "tests/test_iam_secrets_consistency.py",
    "Secret references linter (test_secret_references.py)": "tests/test_secret_references.py",
    "Upstream-API contract tests (test_upstream_contracts.py)": "tests/test_upstream_contracts.py",
}


def _module_of(classname: str) -> str:
    """JUnit `classname` is the dotted test path, e.g. `tests.test_role_policies.TestX`."""
    parts = classname.split(".")
    for i, part in enumerate(parts):
        if part.startswith("test_"):
            return "/".join(parts[: i + 1]) + ".py"
    return ""


def tally(xml_texts: list) -> dict:
    """{test file: {"passed": n, "failed": n, "skipped": n}} over every testcase."""
    out: dict = {}
    for text in xml_texts:
        root = ET.fromstring(text)  # noqa: S314 — the job's own pytest JUnit output, not untrusted input
        for case in root.iter("testcase"):
            path = _module_of(case.get("classname", ""))
            if not path:
                continue
            row = out.setdefault(path, {"passed": 0, "failed": 0, "skipped": 0})
            if case.find("failure") is not None or case.find("error") is not None:
                row["failed"] += 1
            elif case.find("skipped") is not None:
                row["skipped"] += 1
            else:
                row["passed"] += 1
    return out


def render(counts: dict) -> list:
    lines = []
    for label, path in SECTIONS.items():
        row = counts.get(path)
        if not row or sum(row.values()) == 0:
            lines.append(f"::warning title={label}::{path} ran no tests in the coverage passes (renamed or deleted?)")
            continue
        summary = f"{label}: {row['passed']} passed, {row['failed']} failed, {row['skipped']} skipped ({path})"
        if row["failed"]:
            lines.append(f"::error title={label}::{row['failed']} failed in {path}")
        lines.append(summary)
    return lines


def main(argv: list) -> int:
    texts = []
    for path in argv[1:]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                texts.append(f.read())
        except OSError as exc:
            print(f"ci_test_sections: could not read {path} ({exc}); that pass reports nothing")
    try:
        counts = tally(texts)
    except ET.ParseError as exc:
        print(f"ci_test_sections: unparseable JUnit XML ({exc}); no sections reported")
        return 0
    print("::group::Named sections (#4252, the former single-file steps)")
    for line in render(counts):
        print(line)
    print("::endgroup::")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
