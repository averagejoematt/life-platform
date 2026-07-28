"""repo_config.py — locate the repo's config/ directory without assuming nesting depth.

Several shared modules read config/*.json as an offline fallback when S3 is not
available (tests, scripts, local runs). They all resolved it the same way::

    here = os.path.dirname(os.path.abspath(__file__))
    os.path.join(os.path.dirname(here), "config", ...)

which encodes "this module sits exactly one directory below the repo root". That
was true for every module in the flat lambdas/ root and stopped being true the
moment #1653 moved them into domain subpackages: the path silently became
lambdas/config/... and the loader fell through to its empty/`{}` fallback.

The failure is quiet by design in these callers — they log a warning and degrade,
because in Lambda the real source is S3 and the local file is only a convenience.
So nothing crashes; the registry just comes back empty, offline. That is a bad
way to find out (44 persona tests went red at once, all with confusing
"registry is empty" assertions rather than a path error).

Searching upward for the directory removes the assumption instead of re-tuning it,
so no future move can reintroduce this.
"""

import os

_MAX_UP = 6


def config_dir() -> str:
    """Absolute path to the repo's config/ directory.

    Returns the historical two-levels-up guess if no config/ is found (e.g. inside
    a Lambda bundle, where config/ is not staged and S3 is the real source), so
    callers keep their existing "local read failed -> fall back" behaviour rather
    than seeing a new exception type.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(_MAX_UP):
        candidate = os.path.join(here, "config")
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(here)
        if parent == here:
            break
        here = parent
    start = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(os.path.dirname(os.path.dirname(start)), "config")


def config_path(*parts: str) -> str:
    """Absolute path to config/<parts...>."""
    return os.path.join(config_dir(), *parts)
