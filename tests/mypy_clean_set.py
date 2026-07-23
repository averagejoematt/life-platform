"""Single source of truth for the mypy clean-module gate (#1656, eng-excellence #1648).

The clean set is the WHOLE first-party shared-engine + serving surface —
``lambdas/*.py`` and ``lambdas/web/*.py`` (non-recursive) — MINUS a small,
explicitly-documented ``DIRTY`` denylist. This is a ratchet: the denylist only
shrinks (the clean set only grows). A newly-added top-level module is covered
automatically and must pass mypy under ``mypy.ini`` or be added to ``DIRTY``
with a reason in review.

Both consumers read this list so they can never drift:
  * ``tests/test_mypy_clean_modules.py`` (gating in the Test job)
  * the ci-cd.yml "Mypy gate" step: ``python -m mypy --config-file mypy.ini
    $(python tests/mypy_clean_set.py)``

Scope note: the disable_error_code list in mypy.ini is being emptied
incrementally (#1656 landed 7 of the original 14 codes; 7 structural codes —
assignment/attr-defined/index/arg-type/return-value/return/operator — plus
check_untyped_defs/warn_return_any remain, each documented in mypy.ini). The
clean set is "clean under the CURRENT mypy.ini", so it grows again with each
future code the config removes.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories whose top-level *.py form the clean surface (non-recursive:
# subpackages like emails/, intelligence/, compute/, ingestion/ still have
# unresolved cross-Lambda flat-copy imports and are a later ratchet step).
CLEAN_DIRS = ["lambdas", "lambdas/web"]

# Modules that do NOT yet pass under mypy.ini. Each MUST carry a reason. This
# denylist only shrinks. Paths are repo-root-relative.
DIRTY = {
    # 3rd-party module with no stubs / unresolved sibling-Lambda imports
    # (import-not-found). Would need an ignore_missing_imports section.
    "lambdas/audio_encode.py",  # imports lameenc (no type stubs)
    "lambdas/coach_correction_resolver.py",  # imports ai_review_pack_lambda (sibling lambda, unresolved from root)
    # residual disabled-code / structural violations (need a dedicated pass):
    "lambdas/broadcast_sensitivity_gate.py",  # union-attr
    "lambdas/html_builder.py",  # misc
    "lambdas/meal_projection.py",  # misc
    "lambdas/training_notes.py",  # misc + var-annotated
    # platform_logger's Logger subclass narrows msg: object -> str on every
    # level method (LSP-violating override x6). Widely imported; fixing it is a
    # shared-layer change tracked separately (see #419 / this file's history).
    "lambdas/platform_logger.py",  # override (x6)
    # The 3,000-line endpoint handlers — explicitly OUT of scope (var-annotated
    # + misc + call-overload); the next ratchet step, not attempted here.
    "lambdas/web/site_api_data.py",
    "lambdas/web/site_api_observatory.py",
}

# Crown-jewel modules that must ALWAYS be in the clean set (a guard against the
# glob logic silently dropping them). Budget/auth/inference core + the split AI
# modules + the tier-2 serving helpers.
CORE = [
    "lambdas/secret_cache.py",
    "lambdas/retry_utils.py",
    "lambdas/phase_filter.py",
    "lambdas/constants.py",
    "lambdas/bedrock_client.py",
    "lambdas/scoring_engine.py",
    "lambdas/character_engine.py",
    "lambdas/intelligence_common.py",
    "lambdas/ai_calls.py",
    "lambdas/ai_context.py",
    "lambdas/ai_summaries.py",
    "lambdas/web/site_api_common.py",
    "lambdas/web/site_api_coach.py",
    "lambdas/web/site_api_intelligence.py",
    "lambdas/web/site_api_reading.py",
    "lambdas/web/site_api_vitals.py",
    "lambdas/web/site_stats_refresh_lambda.py",
    "lambdas/web/og_image_lambda.py",
    "lambdas/web/og_moments.py",
]


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
    return sorted(paths)


if __name__ == "__main__":
    for m in clean_modules():
        print(m)
