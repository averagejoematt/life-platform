"""Compatibility shim (#4270) - perf_trend now lives in qa/perf_trend.py.

tests/ holds tests and fixtures; this file keeps `import perf_trend` (tests on sys.path) working: it returns the SAME
module object (sys.modules alias) so monkeypatching and private-name access behave exactly as before.
No workflow or tool references this path any more (tests/test_deploy_does_not_import_tests_4270.py guards that).
"""

import importlib
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_mod = importlib.import_module("qa.perf_trend")
# Path-loaded callers (spec_from_file_location, no sys.modules lookup) keep THIS module object: mirror the surface.
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
sys.modules[__name__] = _mod
