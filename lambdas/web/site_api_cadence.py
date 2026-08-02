"""site_api_cadence.py — GET /api/content_cadence (#1972, epic #1890).

No surface said WHEN the next chronicle/podcast installment lands, even
though the cadence is entirely cron-derivable. This handler is the thin
AWS-facing shell: read the budget tier, read the clock, hand both to the pure
`common.content_cadence.build_payload` — never a promise the infra won't
keep (the growth-1 lesson: /subscribe/ once promised a weekly email that was
actually kill-switched for months).

Own module (not appended to site_api_lambda.py / site_api_intelligence.py —
both are near/at their size-guard baselines; see the module-size ratchet in
tests/test_module_size_guard.py), matching the codebase's one-file-per-concern
convention for web/site_api_*.py.
"""

from datetime import datetime, timezone

from common.content_cadence import BUDGET_FEATURE, build_payload

from web.site_api_common import _error, _ok, logger


def handle_content_cadence() -> dict:
    """GET /api/content_cadence — the cron-derived "next installment" line for
    the chronicle + podcast list pages. Read-only, no DB/S3 reads: pure date
    math (common/content_cadence.py) gated by the SAME budget_guard
    "chronicle" feature key both surfaces already share (see
    web/site_api_coach.py's `_regeneration_paused` for the same feature-key
    precedent). Modest cache — a live-computed date shouldn't sit stale for
    hours, though budget_guard.allow() already caches its own SSM read for
    ~5 min so this doesn't need to be any shorter.
    """
    try:
        from ai.budget_guard import allow

        allowed = allow(BUDGET_FEATURE)
        payload = build_payload(datetime.now(timezone.utc), allowed)
        return _ok(payload, cache_seconds=300)
    except Exception as e:
        logger.error(f"[site_api] /api/content_cadence failed: {e}")
        return _error(500, "content cadence unavailable")
