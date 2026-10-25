"""The ONE public name for a heart-rate baseline change: a neutral date, nothing else (#5029).

Owner ruling 2026-10-25: any public HR-derived chart breaks its line, or footnotes, at the date the
heart-rate baseline changed, labelled only "baseline change" -- so the drop after that date is not
read as a fitness gain. No reason is given on any reader surface, and no state, window or label
(the re-baselining label stays off public pages, same ruling).

This is the single reader-facing door onto the dated marker in `health.hr_regime` (the one source
of the date). The `site_api_*` modules import THIS module, never `hr_regime`, so the public API
layer's vocabulary stays "baseline change" and `tests/test_hr_regime_surfaces_5029.py`'s
no-public-module-names-the-marker guard keeps holding. The front-end never hard-codes the date: it
reads `baseline_change` from the payload of the endpoint that serves the series.
"""

from __future__ import annotations

from health import hr_regime


def baseline_change_date() -> str | None:
    """The newest marker's ISO date, or None when no marker is registered. Pure; no clock."""
    markers = hr_regime.HR_REGIME_MARKERS
    return str(markers[-1]["date"])[:10] if markers else None


def with_baseline_change(payload: dict) -> dict:
    """Add the neutral `baseline_change` date to an HR-series payload (additive, in place)."""
    payload["baseline_change"] = baseline_change_date()
    return payload
