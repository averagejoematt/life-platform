#!/usr/bin/env python3
"""tests/test_bedrock_telemetry_iam_parity_3563.py — invoke implies RECORD (#3563).

THE CLASS, MEASURED TWICE
  `lambdas/ai/bedrock_client.invoke()` is the ONE chokepoint every Claude call goes
  through (ADR-062), and it emits three telemetry families to CloudWatch on every call:

      _emit_cost_metrics    AnthropicInputTokens / AnthropicOutputTokens / EstimatedCostUSD
                            (+ the #2883 dimensionless cache twins)
      _note_truncation      TruncatedResponses / TruncatedCostUSD
      _note_cache_noop      PromptCacheNoOp

  All three are wrapped in `except Exception` with a printed `[ERROR] ... datapoints
  DROPPED`, so telemetry can never break an AI call. Correct — and by construction silent.
  A role that holds `bedrock:InvokeModel` and not `cloudwatch:PutMetricData` therefore
  bills Bedrock in full and records NOTHING, on every invocation, forever, with a green
  test suite. The tests cannot see it: no unit test asserts a CloudWatch call, and a
  mocked client cannot be denied.

  #2974 found this on the visual-qa CI role and fixed that one role. On 2026-09-14 a
  30-day CloudWatch Logs sweep of the email + operational family for #3563 found it again
  on TWELVE production roles. Eight had dropped datapoints inside the window, several
  still emitting that morning:

      ai-review-pack        2026-09-13T18:00:28Z   cost + prompt-cache + truncation
      coach-nudge           2026-09-14T15:10:21Z   cost + prompt-cache
      monday-compass        2026-09-14T15:01:17Z   cost + truncation
      weekly-digest         2026-09-13T16:01:15Z   cost + truncation
      nutrition-review      2026-09-12T17:01:43Z   cost + prompt-cache + truncation
      weekly-plate          2026-09-12T02:01:34Z   cost + truncation
      chronicle-approve     2026-09-11T18:00:45Z   cost
      monthly-digest        2026-09-07T…           cost + truncation

  The other four (chronicle-podcast, milestone-digest, partner-weekly-email,
  activity-enrichment) held the same gap with no invocation in the window — the reason
  this test derives the rule instead of listing the eight it could prove.

  Those series are not decoration. `lambdas/operational/cost_governor_lambda.py` projects
  Bedrock spend against the ADR-133 ceiling from the self-reported token/cost metrics, so
  a role that cannot emit them is a role whose spend the governor cannot see.

THE RULE (one line, derived from the role family, nothing hand-listed)
  For every Lambda in the CDK role family: if its role grants any `bedrock:Invoke*`, it
  must also grant `cloudwatch:PutMetricData`. The family itself comes from
  `tests/test_role_family_write_scope.py` (#3596) — every `create_platform_lambda(...)`
  call's `function_name` + `custom_policies=rp.<fn>()` — so a new AI-calling Lambda is
  asked the question by construction, not by someone remembering to add a row here.

  That module is imported rather than re-implemented ON PURPOSE. Its `_role_policies_
  module()` FORCES its own `aws_cdk` stub and purges cached `role_policies*` modules
  because a sibling's thinner stub drops `conditions` and makes parity pass vacuously —
  a bug it measured and documented. A second hand-rolled stub in this file would be a
  second chance to reintroduce exactly that.

WHY A LEDGER THAT IS EMPTY
  `KNOWN_GAPS` is the #3596 pattern and it is empty because the same PR closes all twelve.
  It stays, with its both-ways ratchet, so the next gap has a named, dated place to sit
  for the hours between "found" and "deployed" — and so a line whose gap is gone must be
  DELETED rather than left to rot into a lie.

Run:  python3 -m pytest tests/test_bedrock_telemetry_iam_parity_3563.py -v
"""

from __future__ import annotations

import re

import pytest
import test_role_family_write_scope as family

# #416 / ADR-117: deploy-critical lane — the same lane as its #3596 sibling.
pytestmark = pytest.mark.deploy_critical

#: The right to record the call. PutMetricData accepts no resource ARN, so the grant is
#: on "*" — registered as an account-level action in tests/test_iam_twin_free_3336.py.
TELEMETRY_ACTION = "cloudwatch:PutMetricData"

#: The eight roles whose dropped datapoints were READ OFF LIVE LOGS on 2026-09-14, plus
#: the four that held the identical gap with no invocation in the 30d window. The pin
#: below asserts the whole set stays granted: this is the specimen list of a class that
#: has now recurred twice (#2974, #3563), so a silent removal must red by name.
MEASURED_3563 = (
    "ai-review-pack",
    "chronicle-approve",
    "chronicle-podcast",
    "coach-nudge",
    "milestone-digest",
    "monday-compass",
    "monthly-digest",
    "nutrition-review",
    "partner-weekly-email",
    "weekly-digest",
    "weekly-plate",
    "activity-enrichment",
)

#: function_name -> "YYYY-MM-DD (#issue): what clears this line".
#: EMPTY since 2026-09-14 — every gap the sweep found is granted in the same PR.
KNOWN_GAPS: dict = {}

_LEDGER_LINE = re.compile(r"^\d{4}-\d{2}-\d{2} \(#\d+\): .{20,}$")


def _all_roles() -> list:
    """[(function_name, policy_fn, granted_actions)] for every role in the CDK family."""
    rows = []
    for enrolment in family.ROLE_FAMILY:
        if not enrolment.policy_fn or not family.policy_is_defined(enrolment.policy_fn):
            continue
        rows.append((enrolment.function_name, enrolment.policy_fn, family.granted_actions(family.policy_statements(enrolment.policy_fn))))
    return rows


def _invokes_bedrock(actions) -> bool:
    return any(action.startswith("bedrock:Invoke") for action in actions)


def find_gaps(rows) -> dict:
    """{function_name: policy_fn} for every role that can invoke and cannot record.

    The Bedrock scoping is INSIDE this function, not applied by the caller, so the
    mutation controls exercise the same predicate the live assertion does — a scope
    filter that only runs in production is a scope filter nothing tests.
    """
    return {fn: policy for fn, policy, actions in rows if _invokes_bedrock(actions) and TELEMETRY_ACTION not in actions}


ALL_ROLES = _all_roles()
BEDROCK_ROLES = [row for row in ALL_ROLES if _invokes_bedrock(row[2])]


# ── the derivation is real ───────────────────────────────────────────────────────────
def test_the_bedrock_role_set_is_derived_and_substantial():
    """Guard the guard: an empty or tiny derived set would make every assertion vacuous.

    49 roles invoke Bedrock as of 2026-09-14. The floor is deliberately well below that —
    it catches a BROKEN extractor (family parse failure, stub regression), not normal
    growth or pruning.
    """
    assert len(BEDROCK_ROLES) >= 30, (
        f"only {len(BEDROCK_ROLES)} Bedrock-invoking roles derived from a family of "
        f"{len(family.ROLE_FAMILY)} — the extractor is broken, not the fleet. "
        "Every assertion below is vacuous until this is fixed."
    )
    names = {fn for fn, _p, _a in BEDROCK_ROLES}
    # Three roles from three different stacks, so a single stack file failing to parse
    # cannot leave this looking healthy.
    for expected in ("daily-brief", "life-platform-qa-smoke", "activity-enrichment"):
        assert expected in names, f"{expected} invokes Bedrock but is not in the derived set — the family derivation lost a stack"


def test_the_grant_side_reads_the_real_statement():
    """The rule is read from the real construct, not from the source text of this repo.

    `_bedrock_telemetry_statement()` must resolve to a PutMetricData Allow — if it is
    renamed away or its actions change, the parity assertion would otherwise pass while
    granting nothing.
    """
    statements = family.policy_statements("email_weekly_digest")
    telemetry = [s for s in statements if getattr(s, "sid", "") == "BedrockTelemetryMetric"]
    assert len(telemetry) == 1, f"expected exactly one BedrockTelemetryMetric statement on email_weekly_digest, got {len(telemetry)}"
    assert telemetry[0].actions == [TELEMETRY_ACTION], f"BedrockTelemetryMetric grants {telemetry[0].actions}, not [{TELEMETRY_ACTION}]"
    assert telemetry[0].resources == ["*"], "PutMetricData takes no resource ARN — the grant must stay on '*' (see test_iam_twin_free_3336)"


# ── the rule, both ways ──────────────────────────────────────────────────────────────
def test_every_bedrock_invoking_role_can_emit_its_cost_telemetry():
    """The rule. Invoke implies record, or the spend is real and the record is not."""
    gaps = find_gaps(BEDROCK_ROLES)
    unledgered = sorted(set(gaps) - set(KNOWN_GAPS))
    assert not unledgered, (
        f"{len(unledgered)} role(s) grant bedrock:InvokeModel and NOT {TELEMETRY_ACTION} — "
        "bedrock_client will bill in full and drop every cost/truncation/prompt-cache "
        "datapoint, silently (#3563, #2974):\n"
        + "\n".join(f"  {fn}  (cdk/stacks/role_policies*.py::{gaps[fn]})" for fn in unledgered)
        + "\n\nFix: add `_bedrock_telemetry_statement()` next to `_bedrock_statement()` in that role "
        "(cdk/stacks/role_policies_base.py defines it), then the driver CDK-deploys the owning stack."
    )


def test_the_gap_ledger_has_no_stale_line():
    """The other direction. A ledger line whose gap is gone is a lie about live state —
    #3596's rule, and the reason this file's own twelve lines had to be deleted to land."""
    live = set(find_gaps(BEDROCK_ROLES))
    stale = sorted(set(KNOWN_GAPS) - live)
    assert not stale, "these ledger lines no longer describe a real gap — DELETE them:\n  " + "\n  ".join(stale)


def test_every_ledger_line_is_dated_and_says_what_clears_it():
    """An undated ledger becomes a permanent exemption. Same shape as #3596's."""
    for name, reason in KNOWN_GAPS.items():
        assert _LEDGER_LINE.match(reason), f"{name}: expected 'YYYY-MM-DD (#issue): what clears this', got {reason!r}"


def test_the_twelve_measured_roles_stay_granted():
    """The incident pin. Every role the 2026-09-14 sweep found denied is granted now and
    must stay granted — a class that has recurred twice does not get to recur quietly."""
    by_name = {fn: actions for fn, _p, actions in BEDROCK_ROLES}
    missing_from_family = [fn for fn in MEASURED_3563 if fn not in by_name]
    assert not missing_from_family, (
        f"{missing_from_family} no longer derive as Bedrock-invoking roles. If a Lambda was "
        "retired, delete its line from MEASURED_3563 in the same PR; if the derivation broke, fix that."
    )
    regressed = sorted(fn for fn in MEASURED_3563 if TELEMETRY_ACTION not in by_name[fn])
    assert not regressed, f"#3563 regression — these roles lost {TELEMETRY_ACTION} again: {regressed}"


# ── mutation controls: the rule must be able to FAIL ─────────────────────────────────
def test_MUTATION_a_planted_bedrock_role_without_telemetry_reds_by_name():
    """Positive control. Without this the whole file could be a check that cannot fail."""
    planted = [("probe-fn", "probe_policy", {"bedrock:InvokeModel", "dynamodb:GetItem"})]
    gaps = find_gaps(planted)
    assert gaps == {"probe-fn": "probe_policy"}, f"a Bedrock role with no PutMetricData was not reported as a gap: {gaps}"


def test_MUTATION_a_granted_role_is_not_a_gap():
    """The other half of the control — the rule must not red on the repaired shape."""
    assert find_gaps([("probe-fn", "probe_policy", {"bedrock:InvokeModel", TELEMETRY_ACTION})]) == {}


def test_MUTATION_a_role_that_never_invokes_is_out_of_scope():
    """A non-AI role without PutMetricData is not a finding — the rule is about the
    chokepoint's telemetry, not about metrics in general."""
    assert find_gaps([("probe-fn", "probe_policy", {"dynamodb:GetItem"})]) == {}
    assert not [row for row in BEDROCK_ROLES if row[0] == "probe-fn"]


def test_MUTATION_the_ledger_legs_red_on_synthetic_sets():
    """Both ledger directions, proved on synthetic input rather than on live state —
    live state is empty today, so neither leg would otherwise be exercised at all."""
    live_gap = {"probe-fn": "probe_policy"}
    assert sorted(set(live_gap) - {"other-fn"}) == ["probe-fn"], "the unledgered leg would not fire"
    assert sorted({"other-fn"} - set(live_gap)) == ["other-fn"], "the stale-line leg would not fire"
    assert not _LEDGER_LINE.match("just a reason"), "an undated ledger line would be accepted"
    assert _LEDGER_LINE.match("2026-09-14 (#3563): cleared by the LifePlatformEmail deploy of this grant")
