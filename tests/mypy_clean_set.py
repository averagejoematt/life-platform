"""Single source of truth for the mypy clean-module gate (#1656, eng-excellence #1648).

The clean set is now **the whole first-party Python surface**: every package under
``lambdas/`` plus ``mcp/``, with an EMPTY ``DIRTY`` denylist. Nothing first-party is
excluded from the type gate any more — a green mypy run covers all of it.

Both consumers read this list so they can never drift:
  * ``tests/test_mypy_clean_modules.py`` (gating in the Test job)
  * the ci-lint.yml "Mypy gate" step: ``python -m mypy --config-file mypy.ini
    $(python tests/mypy_clean_set.py)``

Scope note (the OTHER #1656 axis, still open): mypy.ini's ``disable_error_code`` list
still carries four structural codes — assignment / arg-type / return-value / operator —
and ``check_untyped_defs``/``warn_return_any`` are still False. "Clean" here means
"clean under the CURRENT mypy.ini". Emptying those is a separate, measured tranche
(census in the #1656 PR body); it is guarded up-only by
``tests/test_mypy_clean_modules.py::test_global_disable_list_only_shrinks``.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories whose top-level *.py form the clean surface.
#
# ⚠️ These globs are NON-RECURSIVE. A new package under ``lambdas/`` that is not listed
# here contributes ZERO modules to the gate — code would leave the type gate merely by
# being moved (the #1653 packaging trap). ``tests/test_mypy_clean_modules.py::
# test_every_first_party_package_is_in_the_clean_set`` now derives the real directory
# set from the filesystem and fails if one is missing, so the omission cannot be silent.
CLEAN_DIRS = [
    "lambdas/ai",
    "lambdas/coach",
    "lambdas/common",
    "lambdas/compute",
    "lambdas/content",
    "lambdas/emails",
    "lambdas/experiment",
    "lambdas/health",
    "lambdas/ingestion",
    "lambdas/intelligence",
    "lambdas/operational",
    "lambdas/privacy",
    "lambdas/reading",
    "lambdas/training",
    "lambdas/web",
    "mcp",
]

# Individual modules whose DIRECTORY is not in CLEAN_DIRS. Empty since #1656's
# whole-surface step: every first-party package is now listed above, so there is
# nothing left to name one-by-one. Kept as the escape hatch for a future module
# that genuinely lives outside those trees.
CLEAN_FILES: list[str] = []

# Modules that do NOT pass under mypy.ini. **EMPTY since #1656's whole-surface step.**
# This denylist only ever shrinks — re-adding an entry means a module regressed out of
# the gate, which review should treat as a revert-or-fix, not a config change. What the
# last thirteen entries needed, for the record:
#   * the Lambda-bundle dual-import fallbacks (``except ImportError: import <flat>``)
#     got the ``if not TYPE_CHECKING:`` guard the mcp/ step established, so mypy sees
#     one canonical module name and one function signature — runtime unchanged;
#   * empty-container declarations got element types (annotation only, no runtime change);
#   * ``lameenc``/``garth``/``garminconnect``/``openpyxl`` got scoped
#     ``ignore_missing_imports`` sections in mypy.ini — unstubbed third-party libs are a
#     stub gap, never a reason to blanket-ignore one of OUR modules;
#   * ``common/platform_logger.py``'s six LSP-violating overrides were fixed at the
#     source: ``msg: str`` widened to ``msg: object``, which is what ``logging.Logger``
#     itself declares (str is an object, so no caller changed).
DIRTY: set[str] = set()

# Crown-jewel modules that must ALWAYS be in the clean set (a guard against the
# glob logic silently dropping them). Budget/auth/inference core + the split AI
# modules + the tier-2 serving helpers + the formerly-DIRTY endpoint handlers.
CORE = [
    "lambdas/common/secret_cache.py",
    "lambdas/common/retry_utils.py",
    "lambdas/common/platform_logger.py",
    "lambdas/experiment/phase_filter.py",
    "lambdas/common/constants.py",
    "lambdas/ai/bedrock_client.py",
    "lambdas/ai/budget_guard.py",
    "lambdas/health/scoring_engine.py",
    "lambdas/health/character_engine.py",
    "lambdas/intelligence/intelligence_common.py",
    "lambdas/ai/ai_calls.py",
    "lambdas/ai/ai_context.py",
    "lambdas/ai/ai_summaries.py",
    "lambdas/web/site_api_common.py",
    "lambdas/web/site_api_coach.py",
    "lambdas/web/site_api_data.py",
    "lambdas/web/site_api_intelligence.py",
    "lambdas/web/site_api_reading.py",
    "lambdas/web/site_api_vitals.py",
    "lambdas/web/site_stats_refresh_lambda.py",
    "lambdas/web/og_image_lambda.py",
    "lambdas/web/og_moments.py",
    # MCP package entry + registry (joined the clean set with the #1656 mcp/ step).
    "mcp/handler.py",
    "mcp/registry.py",
    "mcp/core.py",
]


def first_party_package_dirs() -> list[str]:
    """Every directory under ``lambdas/`` (plus ``mcp/``) that holds real modules.

    Derived from the filesystem, NOT hand-listed — this is what makes the
    "a new package can't silently leave the gate" ratchet real. ``lambdas/`` itself
    is included only if it ever regains root-level modules (ADR-146/#1653 forbids it).
    """
    dirs: set[str] = set()
    for path in sorted(ROOT.glob("lambdas/**/*.py")):
        if path.name == "__init__.py":
            continue
        dirs.add(path.parent.relative_to(ROOT).as_posix())
    for path in sorted(ROOT.glob("mcp/*.py")):
        if path.name != "__init__.py":
            dirs.add("mcp")
    return sorted(dirs)


def clean_modules() -> list[str]:
    """Repo-root-relative paths of the whole clean surface (sorted, deterministic)."""
    paths: set[str] = set()
    for d in CLEAN_DIRS:
        for p in sorted((ROOT / d).glob("*.py")):
            rel = p.relative_to(ROOT).as_posix()
            if p.name == "__init__.py":
                continue
            if rel in DIRTY:
                continue
            paths.add(rel)
    for rel in CLEAN_FILES:
        if rel not in DIRTY and (ROOT / rel).is_file():
            paths.add(rel)
    return sorted(paths)


if __name__ == "__main__":
    for m in clean_modules():
        print(m)
