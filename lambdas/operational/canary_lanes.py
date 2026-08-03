"""canary_lanes.py — #2051: the canary's check → severity-lane registry.

Why this module exists
----------------------
On 2026-08-02 a *correct* fleet deploy was auto-reverted. Every piece of live
infrastructure was healthy — DynamoDB, S3, MCP and Bedrock all round-tripped —
and the canary still returned 500, because one synthetic ``source='canary'``
subscriber row created twelve days earlier had survived cleanup (#1954's
postcondition). `smoke-test` treated that as a smoke failure and
`rollback-on-smoke-failure` stripped the deploy back out.

While that row existed **no deploy on the platform could survive** — not one
session's, any session's.

This is exactly the class #1921 already reasoned about for qa-smoke's
content-truth findings: *a finding that describes stored state is not evidence
about the code that just shipped, and a rollback cannot fix it.* The canary
never got that treatment because its checks were one undifferentiated
``all_pass``. This registry is that differentiation, in one place:

  ``infra``         — a live round-trip against real infrastructure. If it
                      fails, the code or config that just shipped is a
                      plausible cause and a rollback is a plausible fix.
                      **Gates the pipeline.**

  ``stored_state``  — a postcondition about data sitting in the store. It can
                      have been true for weeks before this deploy, and
                      reverting code cannot delete a row. **Never gates**; it
                      alarms, emails on the first occurrence, and is shouted
                      into the CI log by the smoke oracle.

Consumers
---------
* ``canary_lambda`` tags every result with its lane and reports per-lane
  failure counts in the response body (``failed_deploy_health`` /
  ``failed_stored_state``).
* ``deploy/lib/smoke_oracle_decision.py`` gates on ``failed_deploy_health``
  only — the same key qa-smoke already publishes, so both oracles share one
  contract and the workflow needs no per-check string matching.

Stdlib-only leaf: it is imported by a Lambda handler and by tests, and must
stay importable with no AWS clients constructed.
"""

LANE_INFRA = "infra"
LANE_STORED_STATE = "stored_state"

LANES = (LANE_INFRA, LANE_STORED_STATE)

# The single source of truth for what gates a rollback. Adding a check here is
# the ONLY place a lane is decided — nothing downstream string-matches check
# names (that scattering is how the canary lost the #1921 reasoning in the
# first place).
CHECK_LANES = {
    # ── infra round-trips: a rollback is a plausible fix ──
    "dynamodb": LANE_INFRA,  # write → read → verify → delete against the real table
    "s3": LANE_INFRA,  # write → read → verify → delete against the real bucket
    "mcp": LANE_INFRA,  # MCP Function URL reachable, registry intact
    "anthropic": LANE_INFRA,  # Bedrock inference path live
    "subscribe": LANE_INFRA,  # POST /api/subscribe → DDB record appears (the live flow)
    # ── stored-state postconditions: a rollback cannot fix these ──
    # #1954's residue counter — synthetic rows left behind in the REAL
    # subscriber partition, possibly by a run days or weeks ago. This is the
    # exact check that reverted a healthy fleet on 2026-08-02 (#2051).
    "subscribe_residue": LANE_STORED_STATE,
    # The root cause under that residue: the cleanup delete failing. Alarmed in
    # its own right so it is caught on the day it happens rather than via the
    # aftermath twelve days later.
    "subscribe_cleanup": LANE_STORED_STATE,
}

# Human labels used for the alert email AND for the consecutive-failure state
# stored at USER#system / CANARY#last_state. The five pre-#2051 labels are
# byte-identical to the strings that state already holds — renaming one would
# silently reset its persistence window and suppress a real repeat alert.
CHECK_LABELS = {
    "dynamodb": "DynamoDB",
    "s3": "S3",
    "mcp": "MCP Lambda",
    "anthropic": "Anthropic API",
    "subscribe": "Subscribe flow",
    "subscribe_residue": "Subscribe residue (#1954)",
    "subscribe_cleanup": "Subscribe cleanup",
}


def lane_for(check_key: str) -> str:
    """Lane for a check key. An UNREGISTERED key is treated as ``infra``.

    Deliberately conservative, and the direction matters: an unclassified check
    keeps gating until someone decides it shouldn't. The failure mode of the
    other default — a new check silently landing in the non-gating lane — is a
    real outage nobody is paged for, which is strictly worse than the false
    rollback this module exists to prevent.
    """
    return CHECK_LANES.get(check_key, LANE_INFRA)


def label_for(check_key: str) -> str:
    """Human label for a check key (falls back to the key itself)."""
    return CHECK_LABELS.get(check_key, check_key)


def lane_counts(results: dict) -> dict:
    """Per-lane failure counts derived from the canary's ``results`` mapping.

    ``results`` is ``{check_key: {"ok": True|False|None, ...}}``. Only an
    explicit ``ok is False`` counts as a failure — ``None`` means the check was
    skipped (unresolved URL, missing client) and must not be laundered into
    either lane.

    Counts are derived from the results structure itself rather than from a
    parallel failure list, so the two can never disagree.
    """
    counts = {lane: 0 for lane in LANES}
    for key, entry in (results or {}).items():
        if not isinstance(entry, dict) or entry.get("ok") is not False:
            continue
        lane = lane_for(key)
        counts[lane] = counts.get(lane, 0) + 1
    return counts


def lane_summary(results: dict) -> dict:
    """Per-lane detail for the response body: counts plus the failing keys."""
    counts = lane_counts(results)
    summary = {lane: {"failed": counts.get(lane, 0), "failed_checks": []} for lane in LANES}
    for key, entry in sorted((results or {}).items()):
        if isinstance(entry, dict) and entry.get("ok") is False:
            summary.setdefault(lane_for(key), {"failed": 0, "failed_checks": []})["failed_checks"].append(key)
    return summary
