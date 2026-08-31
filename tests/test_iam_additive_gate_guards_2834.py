"""#2834 — the additive-IAM gate's OTHER four primitives: derivation guard, ratchet, wiring, dead-man.

(The contract test on the real wire is tests/test_iam_additive_gate_2834.py.)

  derivation guard  the namespace the gate admits is DERIVED — account/table/bucket/key from
                    cdk/stacks/constants.py, the Lambda vocabulary from ci/lambda_map.json, the
                    region set from cdk/app.py's literals. Guard the SET: every mapped function is
                    admitted, an unmapped one is refused, and the gate's source carries no
                    hand-typed copy of the account id or bucket name.
  ratchet           FORBIDDEN_ACTION_PATTERNS may only GROW; NAMESPACE_FAMILIES and
                    TOLERATED_NON_IAM may only SHRINK; every entry is dated and argued. Widening
                    either allow-set is a trust-posture change: it needs a dated ADR-065
                    amendment line AND a baseline edit here, in the same PR, on purpose.
  wiring + dead-man ci-cd.yml runs the gate in Plan with no continue-on-error, the Deploy job
                    asserts the verdict output EXISTS before doing anything, the additive deploy
                    step re-evaluates at apply time, deploys `--exclusively` from the evaluated
                    assembly, proves convergence, and writes the ledger — and the old prose grep
                    is gone (a second, wider gate on the same transcript would re-strand every
                    additive change and make this one dead code).

No third-party imports (no yaml): the workflow assertions are text pins, so this file stays
importable in the deploy-critical lane (the 2026-08-15 P4 lesson).
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "deploy"))
sys.path.insert(0, str(ROOT / "cdk"))

import iam_additive_gate as g  # noqa: E402
import iam_additive_registry as reg  # noqa: E402
from stacks import constants  # noqa: E402

pytestmark = pytest.mark.deploy_critical

WORKFLOW = ROOT / ".github" / "workflows" / "ci-cd.yml"
DECISIONS = ROOT / "docs" / "DECISIONS.md"
# Both halves of the gate: the evaluator and the registry it was extracted into (#3335).
# Named without a `GATE_`/`_BASELINE` prefix on purpose — `scripts/gate_census.py`'s
# registry family matches those names and would mint one phantom "gate" per entry, the
# #3220 name-only misfire.
EVALUATOR_SRC = (ROOT / "deploy" / "iam_additive_gate.py").read_text(encoding="utf-8")
REGISTRY_SRC = (ROOT / "deploy" / "iam_additive_registry.py").read_text(encoding="utf-8")


# ── derivation guard ───────────────────────────────────────────────────────────────


def test_namespace_derives_from_cdk_constants():
    assert g.ACCOUNT == constants.ACCT
    assert g.PLATFORM_SLUG == constants.TABLE_NAME
    assert g._C.S3_BUCKET == constants.S3_BUCKET and g._C.KMS_KEY_ID == constants.KMS_KEY_ID
    assert g.resource_in_namespace(f"arn:aws:dynamodb:{constants.REGION}:{constants.ACCT}:table/{constants.TABLE_NAME}") == "dynamodb-table"
    assert g.resource_in_namespace(f"arn:aws:s3:::{constants.S3_BUCKET}/config/x.json") == "s3-platform-bucket"
    # review R2(a), 2026-08-30: the DIL-027 replica LEFT the namespace — asserted as an
    # absence so a silent re-admission reds here, not only in the contract test.
    assert g.resource_in_namespace(f"arn:aws:s3:::{constants.RAW_BACKUP_BUCKET}/raw/x") is None
    assert g.resource_in_namespace(f"arn:aws:kms:{constants.REGION}:{constants.ACCT}:key/{constants.KMS_KEY_ID}") == "kms-platform-key"
    assert (
        g.resource_in_namespace(
            f"arn:aws:secretsmanager:{constants.REGION}:{constants.ACCT}:secret:{constants.SITE_API_ORIGIN_SECRET_NAME}-AbCdEf"
        )
        == "secrets"
    )


def test_gate_source_hand_types_no_namespace_literal():
    """The one way this registry drifts is a copied literal. Refuse the copy, not the value."""
    for literal in (constants.ACCT, constants.S3_BUCKET, constants.KMS_KEY_ID, constants.RAW_BACKUP_BUCKET):
        for name, src in (("iam_additive_gate.py", EVALUATOR_SRC), ("iam_additive_registry.py", REGISTRY_SRC)):
            assert literal not in src, f"hand-typed {literal!r} in {name} — derive it from cdk/stacks/constants.py"


def test_lambda_vocabulary_derives_from_lambda_map__guard_the_set():
    import json

    with open(ROOT / "ci" / "lambda_map.json", encoding="utf-8") as fh:
        names = sorted({e["function"] for e in json.load(fh)["lambdas"].values()})
    assert tuple(names) == g.LAMBDA_NAMES
    assert len(names) >= 100  # the platform's ~104 functions; a truncated read would shrink the namespace silently
    for name in names:
        for region in g.PLATFORM_REGIONS:
            arn = f"arn:aws:lambda:{region}:{constants.ACCT}:function:{name}"
            assert g.resource_in_namespace(arn) == "lambda-functions", arn
            assert g.resource_in_namespace(f"arn:aws:logs:{region}:{constants.ACCT}:log-group:/aws/lambda/{name}:*") == "log-groups", name
    # mutation, both directions: a name NOT in the map is refused even when it looks platform-ish
    assert g.resource_in_namespace(f"arn:aws:lambda:{constants.REGION}:{constants.ACCT}:function:daily-brief-evil") is None
    assert (
        g.resource_in_namespace(f"arn:aws:lambda:{constants.REGION}:{constants.ACCT}:function:life-platform-anything") == "lambda-functions"
    )


def test_region_set_covers_every_stack_environment_in_app_py():
    """cdk/app.py's non-default regions are string literals by #1816's rule — read them, don't guess."""
    app = (ROOT / "cdk" / "app.py").read_text(encoding="utf-8")
    literals = set(re.findall(r'region="([a-z]{2}-[a-z]+-\d)"', app))
    assert literals, "no region literals found in cdk/app.py — the parse is broken, not the app"
    assert literals <= set(g.PLATFORM_REGIONS), literals - set(g.PLATFORM_REGIONS)
    assert constants.REGION in g.PLATFORM_REGIONS and constants.RAW_BACKUP_REGION in g.PLATFORM_REGIONS


# ── ratchet (review R5: the baseline lives where the OWNER reads) ──────────────────
#
# As shipped, the baselines below were frozen sets in THIS file, and the ratchet's rule
# ("widening needs a dated ADR-065 amendment line") was prose — so one commit could widen
# the registry and its own baseline together and nothing outside the diff would say so.
# The baseline is now parsed from the fenced ```json iam-additive-gate-baseline``` block
# in the ADR-065 amendment of 2026-08-30 (docs/DECISIONS.md). A widening still needs a
# code change AND a baseline edit in the same PR — but the baseline edit is now in the
# owner-facing decision record, not in a test file.
#
# The frozen 2026-08-30 sets stay here too, for DIRECTION: forbidden / resource-policy /
# IAM-property may only GROW, namespace / tolerance may only SHRINK. The ADR block says
# what is true today; these say which way today may differ from landing.
# (The constant names deliberately avoid the `*_BASELINE` / `GATE_*` spellings that
# `scripts/gate_census.py`'s registry family name-matches — #3220's misfire class.)

_ADR_FENCE = re.compile(r"```json iam-additive-gate-baseline\n(.*?)\n```", re.S)

FORBIDDEN_AS_SHIPPED = frozenset(
    {
        "iam:*",
        "sts:*",
        "organizations:*",
        "account:*",
        "cloudformation:*",
        "lambda:createfunction*",
        "lambda:updatefunction*",
        "lambda:deletefunction*",
        "lambda:addpermission",
        "lambda:removepermission",
        "lambda:putfunction*",
        "lambda:publishlayerversion",
        "lambda:addlayerversionpermission",
        "lambda:*eventsourcemapping",
        "events:put*",
        "events:delete*",
        "events:remove*",
        "events:disable*",
        "events:enable*",
        "kms:putkeypolicy",
        "kms:schedulekeydeletion",
        "kms:disablekey",
        "kms:createkey",
        "kms:creategrant",
        "s3:putbucketpolicy",
        "s3:deletebucketpolicy",
        "s3:putbucketacl",
        "s3:putobjectacl",
        "s3:putbucketpublicaccessblock",
        "s3:putaccountpublicaccessblock",
        "s3:deletebucket",
        "s3:putbucketversioning",
        "s3:putreplicationconfiguration",
        "s3:putlifecycleconfiguration",
        "dynamodb:deletetable",
        "dynamodb:updatetable",
        "dynamodb:updatecontinuousbackups",
        "dynamodb:deletebackup",
        "secretsmanager:deletesecret",
        "secretsmanager:putresourcepolicy",
        "secretsmanager:createsecret",
        "sns:addpermission",
        "sns:settopicattributes",
        "sqs:addpermission",
        "sqs:setqueueattributes",
        "logs:deleteloggroup",
        "logs:putresourcepolicy",
        "ssm:deleteparameter",
    }
)
# The namespace families as shipped 2026-08-30. May only shrink; adding one = ADR-065 amendment.
# `s3-raw-backup-bucket` was in the landing set and was REMOVED by the CISO review (R2a) —
# a shrink, which is the sanctioned direction.
NAMESPACE_AS_SHIPPED = frozenset(
    {
        "dynamodb-table",
        "s3-platform-bucket",
        "s3-raw-backup-bucket",
        "secrets",
        "lambda-functions",
        "sns-topics",
        "sqs-queues",
        "log-groups",
        "ssm-parameters",
        "kms-platform-key",
    }
)
# The tolerated non-IAM churn as shipped 2026-08-30 — (type, prop, logical-id prefix). May only shrink.
TOLERANCE_AS_SHIPPED = frozenset(
    {
        ("AWS::Lambda::Function", "Code", ""),
        ("AWS::Lambda::Function", "Runtime", "LogRetention"),
        ("AWS::CDK::Metadata", "Analytics", ""),
        ("*", None, ""),
    }
)
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _adr_baseline() -> dict:
    """The declared baseline, parsed from the ADR-065 amendment (review R5)."""
    text = DECISIONS.read_text(encoding="utf-8")
    hits = _ADR_FENCE.findall(text)
    assert len(hits) == 1, f"expected exactly one ```json iam-additive-gate-baseline``` block in docs/DECISIONS.md, found {len(hits)}"
    return json.loads(hits[0])


def test_the_registry_equals_the_baseline_the_adr_declares():
    """R5: a widening cannot land in code alone — the owner-facing ADR block moves with it."""
    declared = _adr_baseline()
    shipped = reg.baseline_snapshot()
    assert set(declared) == set(shipped), set(declared) ^ set(shipped)
    for key in sorted(shipped):
        assert declared[key] == shipped[key], (
            f"{key} differs between deploy/iam_additive_registry.py and the ADR-065 fenced block. "
            "Regenerate with `python3 deploy/iam_additive_registry.py` and paste it into docs/DECISIONS.md, "
            "in the SAME PR — that is the whole point of R5."
        )


def test_the_adr_block_is_non_vacuous():
    """A positive control on the parse itself: an empty or truncated block must not pass as
    'equal'. Every ratcheted set has a floor, so a block that lost its contents reds."""
    declared = _adr_baseline()
    assert len(declared["forbidden_actions"]) >= 70
    assert len(declared["namespace_families"]) >= 8
    assert len(declared["resource_policy_types"]) >= 10
    assert len(declared["iam_property_names"]) >= 8
    assert len(declared["wildcard_resource_shapes"]) >= 4
    assert len(declared["tolerated_non_iam"]) == 4


def test_forbidden_actions_only_grow():
    shipped = set(g.FORBIDDEN_ACTION_PATTERNS)
    removed = FORBIDDEN_AS_SHIPPED - shipped
    assert not removed, f"forbidden patterns REMOVED — that widens what CI may grant: {sorted(removed)}"
    for pat, why in g.FORBIDDEN_ACTION_PATTERNS.items():
        assert pat == pat.lower() and ":" in pat, pat
        assert pat.split("*", 1)[0], f"{pat}: a pattern with an empty literal prefix would forbid every wildcard action"
        assert len(why) >= 12, pat


def test_the_review_R2_and_R3_narrowings_are_present():
    """Non-vacuous, one row per required addition: the review's own list, asserted by name.

    `test_forbidden_actions_only_grow` is a direction check — it cannot tell whether the
    CISO review's specific narrowings ever landed. This can, and it fails if one is dropped.
    """
    required = {
        # R2(c)
        "s3:putbucket*",
        "s3:put*configuration",
        "s3:deleteobjectversion*",
        "s3:putobjectretention",
        "s3:putobjectlegalhold",
        "s3:bypassgovernanceretention",
        # R3
        "ssm:putparameter",
        "sns:subscribe",
        "sns:unsubscribe",
        "sns:deletetopic",
        "dynamodb:updatetimetolive",
        "secretsmanager:putsecretvalue",
        "secretsmanager:updatesecret*",
        "secretsmanager:rotatesecret",
        "logs:putsubscriptionfilter",
        "logs:putretentionpolicy",
        "logs:deletelogstream",
        "sqs:purgequeue",
        "sqs:deletequeue",
        "kms:replicatekey",
        "lambda:putprovisionedconcurrencyconfig",
    }
    missing = required - set(g.FORBIDDEN_ACTION_PATTERNS)
    assert not missing, f"CISO review R2/R3 narrowings missing from the forbidden set: {sorted(missing)}"


def test_namespace_families_only_shrink_and_are_dated():
    names = {f.name for f in g.NAMESPACE_FAMILIES}
    added = names - NAMESPACE_AS_SHIPPED
    assert not added, f"namespace WIDENED without a dated ADR-065 amendment + baseline edit: {sorted(added)}"
    for fam in g.NAMESPACE_FAMILIES:
        assert _DATE.match(fam.since), fam.name
        assert len(fam.why) >= 40, f"{fam.name}: argue it (≥40 chars), a date alone proves nobody looked"
        assert fam.patterns and all(p.startswith("arn:aws:") for p in fam.patterns), fam.name
        for p in fam.patterns:
            assert "*" not in p.split(":")[4], f"{fam.name}: {p} wildcards the ACCOUNT segment"


def test_tolerated_churn_only_shrinks_and_is_dated():
    shipped = {(t.resource_type, t.prop, t.logical_id_prefix) for t in g.TOLERATED_NON_IAM}
    added = shipped - TOLERANCE_AS_SHIPPED
    assert not added, f"non-IAM tolerance WIDENED — CI would ship a class it may not: {sorted(map(str, added))}"
    for t in g.TOLERATED_NON_IAM:
        assert _DATE.match(t.since) and len(t.why) >= 40, (t.resource_type, t.prop)


def test_resource_policy_types_and_iam_property_names_only_grow():
    """R5's second half: these two sets decide which template changes are IAM-relevant AT
    ALL. Shrinking either makes a whole class invisible to the gate, which is the quietest
    possible widening — so they were unratcheted and are not any more."""
    declared = _adr_baseline()
    for key, live in (
        ("resource_policy_types", g.RESOURCE_POLICY_TYPES),
        ("iam_property_names", g.IAM_PROPERTY_NAMES),
    ):
        missing = set(declared[key]) - set(live)
        assert not missing, f"{key} SHRANK — those changes become invisible to the gate: {sorted(missing)}"
    # non-vacuity: the two entries that carry the escalation shapes must be there
    assert "AssumeRolePolicyDocument" in g.IAM_PROPERTY_NAMES and "PermissionsBoundary" in g.IAM_PROPERTY_NAMES
    assert "AWS::Lambda::Permission" in g.RESOURCE_POLICY_TYPES and "AWS::S3::BucketPolicy" in g.RESOURCE_POLICY_TYPES


def test_registry_fingerprint_moves_when_the_registry_moves(monkeypatch):
    before = g.registry_fingerprint()
    monkeypatch.setitem(g.FORBIDDEN_ACTION_PATTERNS, "zzz:test", "mutation")
    assert g.registry_fingerprint() != before


def test_the_evaluator_stays_under_the_module_ceiling():
    """#1665's ceiling is 1,200 lines and the standing rule is extraction, never a raise —
    which is why the registry is its own module. Asserted here so the next narrowing lands
    in the registry rather than growing the evaluator past it."""
    assert len(EVALUATOR_SRC.splitlines()) < 1200
    assert len(REGISTRY_SRC.splitlines()) < 1200


# ── wiring + dead-man (text pins over ci-cd.yml; no yaml import by design) ─────────


def _job(text: str, name: str) -> str:
    m = re.search(rf"^  {name}:\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)", text, re.S | re.M)
    assert m, f"job {name!r} not found in ci-cd.yml"
    return m.group(0)


def _step(job_text: str, name_fragment: str) -> str:
    steps = re.split(r"\n(?=      - (?:name|uses):)", job_text)
    hits = [s for s in steps if name_fragment in s.split("\n", 1)[0] or f"name: {name_fragment}" in s]
    assert len(hits) == 1, f"expected exactly one step matching {name_fragment!r}, found {len(hits)}"
    return hits[0]


@pytest.fixture(scope="module")
def wf() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_old_prose_grep_is_gone(wf):
    assert "grep -qi 'iam\\|policy\\|role\\|permission'" not in wf
    assert "grep -i 'iam\\|policy\\|role\\|permission'" not in wf


def test_plan_job_runs_the_gate_and_exports_its_verdict(wf):
    plan = _job(wf, "plan")
    step = _step(plan, "CDK diff — detect IAM/infra drift")
    assert "id: cdk_diff" in step
    assert "deploy/iam_additive_gate.py --synth-dir cdk/cdk.out --live" in step
    assert '--github-output "$GITHUB_OUTPUT"' in step
    # R4 (CISO review 2026-08-30): the admitted statements go on the RUN PAGE, where the
    # production approval prompt is — not only into a collapsed ::group:: and an S3 ledger.
    assert '--step-summary "$GITHUB_STEP_SUMMARY"' in step
    assert "continue-on-error" not in step
    # exit code is honoured: a non-zero gate reds Plan (the stranded-Plan shape, now named)
    assert re.search(r'if \[ "\$GATE_EXIT" -ne 0 \]; then\n.*?exit 1', step, re.S)
    assert "npx cdk synth --all --quiet" in step
    assert "iam_gate_verdict: ${{ steps.cdk_diff.outputs.iam_gate_verdict }}" in plan
    assert "iam_additive_stacks: ${{ steps.cdk_diff.outputs.iam_additive_stacks }}" in plan
    # destruction gate still precedes the IAM gate (unchanged belt-and-braces)
    assert step.index("resource DESTRUCTIONS") < step.index("iam_additive_gate.py")


def test_deploy_job_runs_for_an_iam_only_merge(wf):
    deploy = _job(wf, "deploy")
    assert "if: needs.plan.outputs.has_deploys == 'true' || needs.plan.outputs.iam_additive_stacks != ''" in deploy
    assert "environment: production" in deploy  # the additive deploy sits behind the same click


def test_deploy_job_dead_man_asserts_the_verdict_exists(wf):
    deploy = _job(wf, "deploy")
    step = _step(deploy, "IAM gate verdict present (dead-man, #2834)")
    assert "if:" not in step.split("run:")[0], "the dead-man must run unconditionally whenever Deploy runs"
    assert "needs.plan.outputs.iam_gate_verdict" in step
    assert re.search(r'if \[ -z "\$VERDICT" \]; then\n.*?exit 1', step, re.S)
    assert "continue-on-error" not in step


def test_additive_deploy_step_evaluates_then_deploys_the_evaluated_assembly(wf):
    deploy = _job(wf, "deploy")
    step = _step(deploy, "Additive IAM deploy — evaluated == deployed (#2834)")
    assert "if: needs.plan.outputs.iam_additive_stacks != ''" in step
    assert "continue-on-error" not in step
    assert "set -euo pipefail" in step
    body = step.split("run:", 1)[1]
    i_reeval = body.index("deploy/iam_additive_gate.py --synth-dir cdk/cdk.out --live --stacks $PLAN_STACKS")
    i_deploy = body.index('npx cdk deploy "$STACK" --app cdk.out --exclusively --require-approval never')
    i_converged = body.index("--expect-converged")
    i_ledger = body.index("aws s3 cp /tmp/iam_gate_2834_converged.json")  # the final ledger write, after convergence
    assert i_reeval < i_deploy < i_converged < i_ledger, "order: re-evaluate → deploy → prove convergence → ledger"
    assert "DEPLOY_STACKS=$(grep '^iam_additive_stacks='" in body, "deploy ONLY what the apply-time evaluation still admits"
    assert "|| true" not in body and "continue-on-error" not in step
    assert "aws s3 cp /tmp/iam_gate_2834_apply.json" in body and "aws s3 cp /tmp/iam_gate_2834_converged.json" in body
    # the deploy role's existing grants cover this step: sts:AssumeRole on cdk-* + s3:PutObject on the bucket
    assert "role/github-actions-deploy-role" in _step(deploy, "Configure AWS credentials (OIDC)")


def test_additive_deploy_publishes_one_line_to_the_alert_topic(wf):
    """R4, the second half: the S3 ledger has no readers; the owner reads life-platform-alerts.

    The line is emitted AFTER convergence is proved, it names the stacks and the admitted
    statements, and it is not swallowed — a failed publish fails the step exactly like a
    failed ledger write. The grant it uses is one the deploy role already held (asserted
    from the committed policy document in the test below).
    """
    step = _step(_job(wf, "deploy"), "Additive IAM deploy — evaluated == deployed (#2834)")
    body = step.split("run:", 1)[1]
    assert "aws sns publish" in body
    assert "life-platform-alerts" in body
    assert "$DEPLOY_STACKS" in body.split("aws sns publish", 1)[1]
    assert body.index("--expect-converged") < body.index("aws sns publish"), "notify only what actually converged"
    tail = body[body.index("aws sns publish") :]
    assert "|| true" not in tail and "continue-on-error" not in tail, "an unannounced deploy is a failure, not a quiet success"


def test_the_2834_steps_run_before_any_code_deploy(wf):
    """N2 (CISO review): a grant that lands AFTER its code leaves the code live and unable to
    do its job for as long as the apply-time evaluation takes to fail — which is the
    2026-08-14 P1 shape exactly (a deployed function missing one s3:GetObject)."""
    deploy = _job(wf, "deploy")
    i_deadman = deploy.index("IAM gate verdict present (dead-man, #2834)")
    i_additive = deploy.index("Additive IAM deploy — evaluated == deployed (#2834)")
    i_creds = deploy.index("name: Configure AWS credentials (OIDC)")
    for code_step in ("Fleet deploy (shared module changed)", "Deploy MCP server", "Deploy Lambdas"):
        assert i_additive < deploy.index(code_step), f"the #2834 steps must precede {code_step!r}"
    assert i_creds < i_deadman < i_additive, "…and must still sit after the OIDC credentials step"


def test_deploy_role_needs_no_new_grant_for_the_additive_deploy():
    """The staged IAM diff for #2834 is EMPTY — pinned here so a future reviewer can see why.

    `cdk deploy` runs entirely through the CDK bootstrap roles: the caller needs only
    sts:AssumeRole on cdk-* (held since the role was codified, #401) and s3:PutObject on the
    platform bucket for the ledger (held). Both statements are asserted from the committed
    policy document, the source of truth for live IAM (infra/iam/README.md).
    """
    import json

    with open(ROOT / "infra" / "iam" / "github-actions-deploy-role.permissions.json", encoding="utf-8") as fh:
        stmts = {s["Sid"]: s for s in json.load(fh)["Statement"]}
    assume = stmts["CDKBootstrapRoleAssume"]
    assert assume["Action"] == "sts:AssumeRole" and assume["Resource"] == f"arn:aws:iam::{constants.ACCT}:role/cdk-*"
    s3 = stmts["S3DeployArtifacts"]
    assert "s3:PutObject" in s3["Action"] and f"arn:aws:s3:::{constants.S3_BUCKET}/*" in s3["Resource"]
    cfn = stmts["CloudFormationDiff"]
    assert "cloudformation:GetTemplate" in cfn["Action"], "the gate's read side (--live) uses GetTemplate"
    # R4's SNS line rides an EXISTING grant — verified here rather than added. If this ever
    # fails, the fix is to drop the notification, not to widen the deploy role in this PR.
    sns = stmts["SNS"]
    assert "sns:Publish" in sns["Action"]
    assert f"arn:aws:sns:{constants.REGION}:{constants.ACCT}:life-platform-alerts" in sns["Resource"]
