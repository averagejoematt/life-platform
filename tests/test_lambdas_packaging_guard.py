"""tests/test_lambdas_packaging_guard.py — #1653: lambdas/ stays packaged.

#1653 moved 132 loose modules out of the lambdas/ root into domain subpackages, so
`ls lambdas/` now communicates the architecture instead of listing 132 filenames.
That state is only worth the migration if it holds. Packaging rots the same way the
flat root grew: one module at a time, each individually defensible.

Two ratchets, both subset-style so the tree can only improve:

  1. No new loose *.py at the lambdas/ root. The root is package directories only.
  2. Every package directory has an __init__.py — the bundle stages lambdas/ at the
     zip root (#781) and handlers import `from <pkg> import <module>`, so a package
     that loses its __init__.py is an ImportError at cold start, not a lint nit.

Deliberately NOT asserted: that a given module lives in a particular package. The
taxonomy is a judgment call recorded in ADR-146, and moving a module between
packages is a normal refactor — this guard only defends the packaged SHAPE, which
is what silently decays.
"""

import os
import subprocess

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(_HERE)
_LAMBDAS = os.path.join(_REPO, "lambdas")

# Non-Python support directories that legitimately live under lambdas/ without being
# importable packages. Each is here with a reason, same contract as the top-level
# allowlist in tests/test_root_clutter_guard.py.
_NON_PACKAGE_DIRS = {
    "cf-auth": "Lambda@Edge JS (index.mjs) — deployed manually to us-east-1, not a Python package.",
    "dashboard": "Static dashboard assets; excluded from the bundle by build_bundle.EXCLUDE_DIRS.",
    "fonts": "Font binaries for the OG-image renderer.",
    "requirements": "Per-Lambda requirements files; excluded from the bundle.",
    "__pycache__": "Build artifact, never tracked.",
}

# Non-Python files that may sit at the lambdas/ root.
_ALLOWED_ROOT_FILES = {
    "og_image_lambda.mjs": "JS OG-image renderer, invoked as its own runtime — not part of the Python import graph.",
}


def _tracked(path_prefix):
    out = subprocess.run(
        ["git", "ls-files", path_prefix],
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def test_no_loose_python_modules_at_the_lambdas_root():
    """The #1653 end state: lambdas/ holds package directories, not modules."""
    loose = [f for f in _tracked("lambdas") if f.count("/") == 1 and f.endswith(".py")]  # lambdas/<name>.py exactly
    assert not loose, (
        "New loose Python module(s) at the lambdas/ root:\n  "
        + "\n  ".join(sorted(loose))
        + "\n\n#1653 moved all 132 root modules into domain subpackages (ai, coach, common, "
        "content, experiment, health, ingestion, privacy, training, ...). Put this module in "
        "the package it belongs to — see ADR-146 for the taxonomy. If it genuinely belongs "
        "nowhere, that is a signal about the module, not about the rule."
    )


def test_no_unexpected_non_python_files_at_the_lambdas_root():
    """Catches data/config files dropped at the root, which is how module-relative
    resource loading silently broke during #1653 (food_vocabulary.json, redirects.map)."""
    unexpected = [
        f for f in _tracked("lambdas") if f.count("/") == 1 and not f.endswith(".py") and os.path.basename(f) not in _ALLOWED_ROOT_FILES
    ]
    assert not unexpected, (
        "Unexpected file(s) at the lambdas/ root:\n  "
        + "\n  ".join(sorted(unexpected))
        + f"\n\nAllowed: {sorted(_ALLOWED_ROOT_FILES)}. Note that deploy/build_bundle.py stages "
        "some data files at the BUNDLE root at deploy time (food_vocabulary.json, redirects.map) — "
        "those are staged, not tracked here, and their loaders search upward on purpose."
    )


def test_every_lambdas_package_has_an_init():
    """A package missing __init__.py is a cold-start ImportError, not a style issue."""
    missing = []
    for name in sorted(os.listdir(_LAMBDAS)):
        d = os.path.join(_LAMBDAS, name)
        if not os.path.isdir(d) or name in _NON_PACKAGE_DIRS:
            continue
        if not any(f.endswith(".py") for f in os.listdir(d)):
            continue
        if not os.path.isfile(os.path.join(d, "__init__.py")):
            missing.append(f"lambdas/{name}")
    assert not missing, (
        "Python package(s) under lambdas/ with no __init__.py: "
        + ", ".join(missing)
        + ". The bundle stages lambdas/ at the zip root, so handlers reach these via "
        "`from <pkg> import <module>` — without __init__.py that fails at cold start."
    )
