"""Compatibility shim (#4270) - mypy_clean_set now lives in scripts/mypy_clean_set.py.

tests/ holds tests and fixtures; this file keeps `import mypy_clean_set` (tests on sys.path) working: it returns the SAME
module object (sys.modules alias) so monkeypatching and private-name access behave exactly as before.
No workflow or tool references this path any more (tests/test_deploy_does_not_import_tests_4270.py guards that).
"""

import importlib.util
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_spec = importlib.util.spec_from_file_location("mypy_clean_set", os.path.join(_ROOT, "scripts/mypy_clean_set.py"))
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules["mypy_clean_set"] = _mod
_spec.loader.exec_module(_mod)
# Path-loaded callers (spec_from_file_location, no sys.modules lookup) keep THIS module object: mirror the surface.
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
sys.modules[__name__] = _mod

if __name__ == "__main__":  # the .claude/settings.json permission entry still names `python3 tests/mypy_clean_set.py *`
    for _m in _mod.clean_modules():
        print(_m)
