"""Compatibility shim (#4270) — the site review bindings map now lives in qa/site_review_bindings.py.

deploy/ and scripts/ must not import from tests/ (tests/test_deploy_does_not_import_tests_4270.py), so the
real module moved to the qa/ package. This shim keeps every existing consumer working unchanged:

  * `import site_review_bindings` (tests on sys.path) returns the SAME module object (sys.modules alias), so monkeypatching
    and private-name access behave exactly as before.
"""

import importlib
import os
import runpy
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
if __name__ == "__main__":  # `python3 tests/site_review_bindings.py ...` still works: run the real file as __main__ (its own argparse)
    runpy.run_path(os.path.join(_ROOT, "qa", "site_review_bindings.py"), run_name="__main__")
else:
    _mod = importlib.import_module("qa.site_review_bindings")
    # Path-loaded callers keep THIS module object: mirror the public surface onto it as well.
    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
    sys.modules[__name__] = _mod
