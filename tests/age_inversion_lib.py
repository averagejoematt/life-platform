"""Compatibility shim (#4270) - age_inversion_lib now lives in qa/age_inversion_lib.py (moved by #6083, so that
scripts/check_public_copies.py can run the attack over the archive without reaching into tests/).

tests/ holds tests and fixtures; this file keeps `import age_inversion_lib` (tests on sys.path) working: it returns the
SAME module object (sys.modules alias) so monkeypatching and private-name access behave exactly as before.
"""

import importlib
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
_mod = importlib.import_module("qa.age_inversion_lib")
# Path-loaded callers (spec_from_file_location, no sys.modules lookup) keep THIS module object: mirror the surface.
globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
if __name__ == "__main__":
    raise SystemExit(_mod.main())
else:
    sys.modules[__name__] = _mod
