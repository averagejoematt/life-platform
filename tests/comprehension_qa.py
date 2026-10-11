"""Compatibility shim (#4270) - comprehension_qa now lives in qa/comprehension_qa.py.

tests/ holds tests and fixtures; this file keeps `import comprehension_qa` (tests on sys.path) working: it returns the SAME
module object (sys.modules alias) so monkeypatching and private-name access behave exactly as before.
No workflow or tool references this path any more (tests/test_deploy_does_not_import_tests_4270.py guards that).
"""

import importlib
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_mod = importlib.import_module("qa.comprehension_qa")
# Path-loaded callers (spec_from_file_location, no sys.modules lookup) keep THIS module object: mirror the surface.
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
if __name__ == "__main__":
    _mod.main()
else:
    sys.modules[__name__] = _mod
