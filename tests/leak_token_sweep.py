"""Compatibility shim (#4270) — the leak-token sweep core now lives in qa/leak_token_sweep.py.

deploy/ and scripts/ must not import from tests/ (tests/test_deploy_does_not_import_tests_4270.py), so the
real module moved to the qa/ package. This shim keeps every existing consumer working unchanged:

  * `import leak_token_sweep` (tests on sys.path) returns the SAME module object (sys.modules alias), so monkeypatching
    and private-name access behave exactly as before.
"""

import importlib
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_mod = importlib.import_module("qa.leak_token_sweep")

# Path-loaded (importlib spec_from_file_location, no sys.modules entry): the caller keeps THIS module object,
# so mirror the public surface onto it as well.
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})

sys.modules[__name__] = _mod
