"""#3830 — a vendor transient on an infra check must not gate a rollback.

THE INCIDENT THIS EXISTS FOR. 2026-09-15, CI/CD run 35013357326 on `14e8aaa93`.
`Deploy: success`, `Post-deploy integration checks: success`, and then:

    DDB ✅   S3 ✅   MCP ✅ (83 tools)   Subscribe ✅
    Anthropic: ❌ Bedrock ServiceUnavailableException: Bedrock is unable to
               process your request.
    Suppressed first-occurrence alert (1 new infra failure(s)); will alert if
               repeat next run
    Canary complete: 1 FAILURES ❌ (infra 1, stored-state 0)

`Auto-rollback (smoke failure)` then stripped 85 Lambdas back to their previous
bundles. A vendor-side 503 reverted a verified-correct fleet deploy.

Read the last two lines of that log together, because they are the actual defect:
the canary judged that datapoint too weak to send an EMAIL about, and the deploy
gate reverted 85 functions on it. Two consumers of one signal, opposite
confidence, and the more destructive consumer was the more confident one.

WHY #2051's LANE SPLIT DID NOT CATCH IT. `canary_lanes` already separates `infra`
(a rollback is a plausible fix) from `stored_state` (it cannot be). That split is
by CHECK. `anthropic` sits in `infra` and that is CORRECT — a broken inference
path genuinely is a plausible deploy cause (a lost `bedrock:InvokeModel`, a wrong
model id, a bundling break). What was never split is the FAILURE MODE: the same
check fails both in ways a deploy can cause and in ways it cannot, and only the
second kind must be demoted.

So the tests below come in pairs, always. Every case that proves the new lane
DEMOTES something is matched by one proving it still GATES the deploy-plausible
failure on the SAME check. A guard that only demonstrates the permissive
direction is precisely how #2051 recurred as #3830.
"""

import os
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (os.path.join(_REPO, "lambdas"), os.path.join(_REPO, "lambdas", "operational")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import canary_lanes as cl  # noqa: E402


def _incident_results(**overrides):
    """The REAL 19:54:50Z payload, reconstructed from the live log verbatim.

    Built as a helper rather than a fixture constant so each test can vary ONE
    field and leave the other six at the values they actually had — the point of
    several cases below is that everything else round-tripped clean.
    """
    results = {
        "dynamodb": {"ok": True},
        "s3": {"ok": True},
        "mcp": {"ok": True},
        "subscribe": {"ok": True},
        "subscribe_cleanup": {"ok": True},
        "subscribe_residue": {"ok": True},
        "anthropic": {
            "ok": False,
            "failure_code": "ServiceUnavailableException",
            "message": "Bedrock ServiceUnavailableException: Bedrock is unable to process your request.",
        },
    }
    results.update(overrides)
    return results


# ══════════════════════════════════════════════════════════════════════════════
# The incident itself, replayed
# ══════════════════════════════════════════════════════════════════════════════


def test_the_2026_09_15_payload_no_longer_gates_a_rollback():
    """The whole issue in one assertion, against the real numbers."""
    counts = cl.lane_counts(_incident_results())
    assert counts[cl.LANE_INFRA] == 0, (
        "the 2026-09-15 payload still reports failed_deploy_health>0 — `deploy/lib/smoke_oracle_decision.py` "
        "gates on exactly that key, so this is the fleet being reverted by a vendor 503 all over again"
    )
    assert counts[cl.LANE_EXTERNAL_TRANSIENT] == 1, "the failure must still be COUNTED — demoted, never dropped"
    assert counts[cl.LANE_STORED_STATE] == 0


def test_the_same_check_still_gates_on_a_deploy_plausible_failure():
    """The load-bearing control. Without this the fix is a hole, not a fix.

    `AccessDeniedException` on `anthropic` is what a bad deploy LOOKS like — an
    IAM grant lost in a CDK change, the exact class #3810 shipped telemetry for.
    It must keep gating, on the same check, in the same lane it always had.
    """
    denied = _incident_results(anthropic={"ok": False, "failure_code": "AccessDeniedException", "message": "Bedrock access denied"})
    counts = cl.lane_counts(denied)
    assert counts[cl.LANE_INFRA] == 1, (
        "AccessDenied on the inference path no longer gates — losing bedrock:InvokeModel in a deploy would "
        "now ship green. That is a strictly worse failure than the one #3830 fixed."
    )
    assert counts[cl.LANE_EXTERNAL_TRANSIENT] == 0


def test_2051_has_not_regressed():
    """The stale synthetic subscriber row that started all of this must still
    be non-gating, and must still land in `stored_state` rather than being
    swept into the new lane."""
    residue = _incident_results(anthropic={"ok": True}, subscribe_residue={"ok": False})
    counts = cl.lane_counts(residue)
    assert counts[cl.LANE_INFRA] == 0
    assert counts[cl.LANE_STORED_STATE] == 1, "the #1954 residue check belongs to stored_state, not the new lane"
    assert counts[cl.LANE_EXTERNAL_TRANSIENT] == 0


# ══════════════════════════════════════════════════════════════════════════════
# The conservative defaults — the direction that must NOT drift
# ══════════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "check,code",
    [
        ("dynamodb", "ServiceUnavailableException"),  # a real code, but not registered FOR THIS CHECK
        ("s3", "ThrottlingException"),
        ("mcp", "RequestTimeout"),
        ("subscribe", "ServiceUnavailableException"),
    ],
)
def test_transient_codes_are_per_check_not_global(check, code):
    """A code is transient FOR A CHECK, never in the abstract.

    DynamoDB and S3 are ours; if they are unavailable that is an outage worth
    stopping a deploy over, and a rollback is at least a plausible response.
    Bedrock is a third party we call. Registering these codes globally would
    have turned every one of our own infra round-trips non-gating in one edit.
    """
    counts = cl.lane_counts({check: {"ok": False, "failure_code": code}})
    assert counts[cl.LANE_INFRA] == 1, f"{check} was demoted by {code}, which is registered only for other checks"
    assert counts[cl.LANE_EXTERNAL_TRANSIENT] == 0


def test_an_unrecorded_failure_code_keeps_gating():
    """No code recorded → the old behaviour, unchanged. Every pre-#3830 caller
    that never learned to pass one keeps gating exactly as it did."""
    counts = cl.lane_counts(_incident_results(anthropic={"ok": False, "message": "something broke"}))
    assert counts[cl.LANE_INFRA] == 1


def test_an_unclassified_failure_code_keeps_gating():
    """A code nobody has adjudicated is NOT transient by default.

    Same direction as `lane_for`'s unregistered-check default and for the same
    reason the module already states: a check silently landing in the non-gating
    lane is an outage nobody is paged for, which is worse than a false rollback.
    """
    counts = cl.lane_counts(_incident_results(anthropic={"ok": False, "failure_code": "SomeNewException2027"}))
    assert counts[cl.LANE_INFRA] == 1


def test_a_skipped_check_is_not_laundered_into_any_lane():
    """`ok is None` means the check did not run. It was never a failure and the
    new lane must not become a place to hide one."""
    counts = cl.lane_counts(_incident_results(anthropic={"ok": None, "message": "bedrock_client import failed"}))
    assert counts[cl.LANE_INFRA] == 0
    assert counts[cl.LANE_EXTERNAL_TRANSIENT] == 0
    assert counts[cl.LANE_STORED_STATE] == 0


def test_a_passing_check_with_a_stale_failure_code_is_not_a_failure():
    """Defensive: `ok is True` wins over any code left on the entry."""
    counts = cl.lane_counts(_incident_results(anthropic={"ok": True, "failure_code": "ServiceUnavailableException"}))
    assert sum(counts.values()) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Registry shape — the rules that keep the set honest
# ══════════════════════════════════════════════════════════════════════════════


def test_access_denied_is_absent_from_every_transient_set():
    """Stated as its own assertion because it is the one entry that would quietly
    undo this guard's whole purpose. Losing an IAM grant is a deploy-plausible
    cause on any check; it can never be classified transient."""
    for check, codes in cl.TRANSIENT_FAILURE_CODES.items():
        assert "AccessDeniedException" not in codes, f"{check} classifies AccessDenied as transient — a deploy CAN cause it"
        assert "ResourceNotFoundException" not in codes, (
            f"{check} classifies ResourceNotFoundException as transient — a revoked model/profile or a wrong id "
            "is exactly what a bad deploy looks like"
        )


def test_every_transient_registry_key_is_a_real_infra_check():
    """A typo'd key would silence nothing and look like coverage."""
    for check in cl.TRANSIENT_FAILURE_CODES:
        assert check in cl.CHECK_LANES, f"{check!r} is not a registered canary check"
        assert cl.lane_for(check) == cl.LANE_INFRA, f"{check!r} is not in the infra lane, so demoting it is meaningless — only infra gates"


def test_the_new_lane_is_enumerated_in_LANES():
    """`lane_counts` seeds its dict from `LANES`; a lane missing there reports
    zero forever and the demotion becomes a silent drop."""
    assert cl.LANE_EXTERNAL_TRANSIENT in cl.LANES


def test_lane_summary_names_the_demoted_check_by_name():
    """A non-gating failure has to be READABLE or it is a silent skip — the
    thing this repo treats as worse than a red."""
    summary = cl.lane_summary(_incident_results())
    assert summary[cl.LANE_EXTERNAL_TRANSIENT]["failed"] == 1
    assert summary[cl.LANE_EXTERNAL_TRANSIENT]["failed_checks"] == ["anthropic"]
    assert summary[cl.LANE_INFRA]["failed_checks"] == []


def test_the_registry_is_not_vacuous():
    """The scan must actually classify something. An empty registry would pass
    every demotion test above by never demoting anything, and pass every
    still-gates test trivially."""
    assert cl.TRANSIENT_FAILURE_CODES, "no transient codes registered — every test above passes vacuously"
    assert cl.transient_codes_for("anthropic"), "the check the incident happened on classifies nothing"
    assert cl.transient_codes_for("dynamodb") == frozenset(), "unregistered checks must return an empty set, not a default"
