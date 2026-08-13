#!/usr/bin/env python3
"""scripts/ci_pins.py — resolve tool pins from requirements-dev.txt (CQ-01, #2609).

The one source of truth for a dev-tooling version is `requirements-dev.txt`, which is
what Dependabot bumps. Before #2609 every CI workflow carried a SECOND copy of that
version as a literal `pip install tool==X`, and the CQ-01 guard
(tests/test_ci_pin_consistency.py) required the two copies to agree — correctly, since
a local pin that disagrees with the enforced gate is real drift. But only one side had
an automated bumper, so **every dev-tooling bump was born red** and stayed red until a
human hand-edited 28 declarations across 8 workflow files.

This deletes the second copy rather than automating the hand-edit. A workflow now says
WHICH packages it needs and reads the versions:

    - name: Install test dependencies
      run: |
        PINS=$(python3 scripts/ci_pins.py pytest boto3 botocore hypothesis)
        pip install $PINS

Two properties make that safe to put in front of the enforced gates:

* **Fail loud, never silently unpinned.** A name that isn't pinned in
  requirements-dev.txt is a hard error (exit 2) naming the package, not a silently
  skipped install that would leave CI running an unpinned latest. Under GitHub's
  default `bash -eo pipefail`, the `PINS=$(...)` assignment propagates that exit.
* **No parsing surprises.** Only top-level `name==version` lines count; comments,
  blank lines, and any line with an environment marker or extra are ignored, and
  package names are compared PEP 503-normalized (`pytest-cov` == `pytest_cov`).

Nothing here reaches the network or the AWS account — it is a text read of one tracked
file, deliberately stdlib-only so it can run before any dependency is installed.
"""

from __future__ import annotations

import argparse
import os
import re
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_REQUIREMENTS = os.path.join(_REPO, "requirements-dev.txt")

# A top-level exact pin: `name==version`, optionally followed by a trailing comment.
# Anything with a marker (`; python_version < …`) or an extra (`pkg[foo]==`) is
# deliberately NOT matched — this resolver only speaks the simple pinned form the
# repo's requirements-dev.txt uses, and an unmatched name errors rather than guesses.
_PIN_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z0-9_.\-]*)==(?P<version>[0-9][0-9A-Za-z.+\-]*)\s*(?:#.*)?$")


def normalize(name: str) -> str:
    """PEP 503 name normalization, so `pytest-cov`/`pytest_cov`/`PyYAML` all match."""
    return re.sub(r"[-_.]+", "-", name).lower()


def read_pins(path: str = DEFAULT_REQUIREMENTS) -> dict:
    """{normalized name: 'name==version'} for every top-level exact pin in `path`."""
    pins = {}
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            m = _PIN_RE.match(raw.strip())
            if m:
                pins[normalize(m.group("name"))] = f"{m.group('name')}=={m.group('version')}"
    return pins


def resolve(packages, path: str = DEFAULT_REQUIREMENTS):
    """Return the `name==version` requirement for each package, in the order asked.

    Raises KeyError-free: unknown names are collected and reported together, because
    a CI operator fixing one typo should see all of them in one run.
    """
    pins = read_pins(path)
    resolved, unknown = [], []
    for pkg in packages:
        key = normalize(pkg)
        if key in pins:
            resolved.append(pins[key])
        else:
            unknown.append(pkg)
    if unknown:
        raise LookupError(
            f"not pinned in {os.path.relpath(path, _REPO)}: {', '.join(sorted(unknown))}. "
            f"Add an exact `name==version` pin there (it is the single source of truth for "
            f"tool versions — CQ-01), or correct the name in the workflow. "
            f"Known pins: {', '.join(sorted(pins))}"
        )
    return resolved


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Print the requirements-dev.txt pin for each named package, one per line.")
    parser.add_argument("packages", nargs="+", help="package names (versions come from requirements-dev.txt)")
    parser.add_argument("--requirements", default=DEFAULT_REQUIREMENTS, help="path to the pin file (default: requirements-dev.txt)")
    args = parser.parse_args(argv)
    try:
        for req in resolve(args.packages, args.requirements):
            print(req)
    except LookupError as exc:
        print(f"ci_pins: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"ci_pins: cannot read pin file: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
