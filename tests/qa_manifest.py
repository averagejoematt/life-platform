"""Compatibility shim (#4270) — the page registry now lives in qa/qa_manifest.py.

deploy/ and scripts/ must not import from tests/ (tests/test_deploy_does_not_import_tests_4270.py), so the
real module moved to the qa/ package. This shim keeps every existing consumer working unchanged:
  * `python3 tests/qa_manifest.py --emit ...` (CI workflows, smoke_test_site.sh) still runs the CLI;
  * `import qa_manifest` (tests on sys.path) returns the SAME module object (sys.modules alias), so monkeypatching
    and private-name access behave exactly as before.
"""

# premerge_derivation (#2924) classifies a test that imports a tree-sweeping helper by the helper's TEXT. The real
# registry's self_check() does an os.walk( over site/; the literal is repeated here so importers of this shim keep
# their classification and the structural gate ids do not shift.
import importlib
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_mod = importlib.import_module("qa.qa_manifest")

# Path-loaded (importlib spec_from_file_location, no sys.modules entry): the caller keeps THIS module object,
# so mirror the public surface onto it as well.
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})

if __name__ == "__main__":
    _mod.main()
else:
    sys.modules[__name__] = _mod
