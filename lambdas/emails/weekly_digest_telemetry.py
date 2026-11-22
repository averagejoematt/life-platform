"""emails/weekly_digest_telemetry.py — the weekly digest's PROD-MON-06 gate-readout inputs (pure).

Moved out of ``weekly_digest_lambda.py`` unchanged (#6176) so the digest stays inside its module-size baseline (#1665);
the digest re-exports ``_gate_telemetry`` under its old name, so every caller and test is unchanged.
"""


def _gate_telemetry(data, profile, real_subscribers, attribution=None):
    """PROD-MON-06 gate readout inputs (pure). A wiped/genesis week stores the
    source key WITH value None — `.get(k, {})` does not guard an existing-None
    key (the 2026-07-19 Sunday-digest DLQ crash: this.withings was None the
    morning after a reset; recurs every future reset without the `or {}`)."""
    return {
        "real_subscribers": real_subscribers,
        # #1621 — list of (label, count); [] when unavailable or nothing attributed yet.
        "attribution": attribution or [],
        "current_weight": ((data.get("this") or {}).get("withings") or {}).get("weight_latest"),
        "start_weight": profile.get("journey_start_weight_lbs", 0),
        "goal_weight": profile.get("goal_weight_lbs", 185),
    }
