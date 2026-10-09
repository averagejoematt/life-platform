"""Test-only clock pin for `tests/test_reset_cadence_refusal_3601.py` (#3601).

Loaded only when that test puts this directory on PYTHONPATH for its subprocess. It
imports `restart_cadence` first and replaces the module's `datetime` with a copy whose
`date.today()` returns CADENCE_TEST_TODAY, so the cadence refusal is measured on a fixed
day instead of the wall clock. Nothing is changed when the variable is unset.
"""

import datetime as _real
import importlib
import os
import sys
import types

# Run the interpreter's own sitecustomize first (Homebrew's adds its site-packages), which
# this file would otherwise shadow.
_here = os.path.dirname(os.path.abspath(__file__))
_saved = sys.path[:]
sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != _here]
_me = sys.modules.pop("sitecustomize", None)
try:
    importlib.import_module("sitecustomize")
except ImportError:
    pass
finally:
    sys.path[:] = _saved + [p for p in sys.path if p not in _saved]
    if _me is not None:
        sys.modules["sitecustomize"] = _me

_today = os.environ.get("CADENCE_TEST_TODAY")
_deploy = os.environ.get("CADENCE_TEST_DEPLOY_DIR")
if _today and _deploy:
    if _deploy not in sys.path:
        sys.path.insert(0, _deploy)
    import restart_cadence  # noqa: E402

    _pinned = _real.date.fromisoformat(_today)

    class _PinnedDate(_real.date):
        @classmethod
        def today(cls):
            return _pinned

    _shim = types.ModuleType("datetime")
    _shim.__dict__.update(_real.__dict__)
    _shim.date = _PinnedDate
    restart_cadence._dt = _shim
