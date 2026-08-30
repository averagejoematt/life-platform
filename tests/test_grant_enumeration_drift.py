"""tests/test_grant_enumeration_drift.py — #2824: guard the consumer SET, not the instance.

The class (merged elite-review findings WS-B + WS-C, incident base n=16, P1×2):
**code references a resource its role no longer provides, and nothing compares the
two enumerations.** Every member failed the same way — quietly. A missing
`s3:GetObject` on `config/content_filter.json` (#2503, 2026-08-14) made the privacy
scrub a no-op AND 100%-failed the AI canary for five days with `Errors=0`; a
missing SES config-set grant (2026-05-17) killed the daily brief for two days; a
missing `ssm:GetParameter` on `/life-platform/budget-tier` disables the ADR-125
ceiling outright, which is why #3059 had to make public inference fail CLOSED on
unreadable budget state.

Four consumer-vs-grant guards already existed, each scoped to ONE resource:
`test_put_metric_data_grant_lockstep.py` (#1196 — the architecture this
generalises), `test_freshness_checker_iam_parity.py` (#1330),
`test_raw_archive_role_parity.py` (#1949), `test_iam_secrets_consistency.py`
(R8-8, and it guards the *other* direction: IAM → known-secret registry). This
file is the SET: every fail-closed channel, every wired Lambda, every CI identity
that assumes an OIDC role.

What it asserts
---------------
  A. **Lambda fleet lockstep** — for each of the ~103 `create_platform_lambda`
     call sites, every SSM param / Secret / `config/` object / SES config-set
     reachable from its handler is granted by its role.
  B. **CI identity lockstep** — for each workflow job that assumes an OIDC role,
     every channel its python entrypoints reach is granted by
     `infra/iam/<role>.permissions.json`. This is where #3059's second casualty
     lived (the diagnosis role's missing budget-tier read); the sweep found a
     third on the golden-eval role, repaired 2026-08-23 (see `_PENDING_LIVE_APPLY`
     — the doc is fixed, the out-of-band apply is the remaining step).
  C. **Ratchets that only shrink** — the open live gaps, the pending live applies
     and the dynamic (unparseable) references are dated whitelists; a stale entry
     fails as loudly as a new gap, so no list can quietly become a graveyard.
     The sweep's first run recorded 13 live gaps (2026-08-23); the repair PR the
     same day closed 12, leaving one deferred behind #3037's concurrent rework of
     `role_policies_email.py`.
  D. **Deploy path** — every `config/` object a Lambda reads has a producer (the
     L110 shape: a prefix nothing deploys).
  E. **Watch surface** — the derived content-filter/privacy-guard consumer set is
     mapped 1:1 to an alarm that exists in the CDK source, or a dated exemption.

Derivation notes live in `tests/grant_enumeration.py`. The two that decide whether
this gate is honest: consumers come from an **import-scoped call graph** (not a
file-local grep, which finds zero, and not an import closure, which invents ~35
phantoms), and grants include the **`create_platform_lambda` baseline** as well as
`role_policies_*` (reading only the latter reports ~30 false budget-tier gaps).

Mutation-proved in both directions at the bottom of this file: deleting a grant
from a COPY of a real permissions doc reds; adding an unregistered fail-closed
consumer reds; and the reachability rule is pinned so a revert to closure
attribution reds rather than silently flooding the gate.

PROPORTIONALITY: `docs/PROPORTIONALITY.md` row "grant-enumeration drift sweep".

Run:  python3 -m pytest tests/test_grant_enumeration_drift.py -v
"""

from __future__ import annotations

import ast
import copy
import fnmatch
import glob
import json
import os
import re
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import grant_enumeration as ge  # noqa: E402

REPO = ge.REPO

# #416 / ADR-117: deploy-critical lane — this is an IAM parity linter.
pytestmark = pytest.mark.deploy_critical


# ══════════════════════════════════════════════════════════════════════════════
# The dated ratchets
# ══════════════════════════════════════════════════════════════════════════════

#: OPEN LIVE GAPS found by this sweep's first run (2026-08-23, #2824). Each is a
#: real consumer whose role does not grant the channel it reaches — verified by
#: hand against the role's built statements and the handler's call chain. They are
#: recorded rather than fixed here on purpose: repairing them edits six CDK stacks
#: and needs a `cdk deploy` from main, which a gate PR must not carry (a deploy
#: from a branch reports a deceptive 0-diff). Every entry is a defect with an owner,
#: NOT a sanctioned exemption — `test_open_gap_ratchet_only_shrinks` fails the day
#: one is fixed and not deleted here.
#:
#: (source_file, channel, reference) → why it is open
#:
#: SHRUNK 2026-08-23 (#2824 repair PR): nine of the ten original entries were fixed in
#: `cdk/stacks/role_policies_{ingestion,operational,serve,compute}.py` and deleted here —
#: the guard passing IS the proof, because `test_open_gap_ratchet_only_shrinks` reds on a
#: recorded gap that no longer reproduces and `test_every_lambda_consumer_is_granted_its_channel`
#: reds on one that does. The single survivor is deferred, with its reason, below.
_OPEN_GAPS: dict[tuple, str] = {
    (
        "lambdas/emails/chronicle_email_sender_lambda.py",
        "s3config",
        "config/personas.json",
    ): "#2824 2026-08-23: _derive_board_members → persona_registry.load_registry; "
    "email_chronicle_sender() has no S3 config read. DEFERRED (not fixed with its nine "
    "siblings on 2026-08-23): the repair lands in cdk/stacks/role_policies_email.py, which "
    "#3037 is concurrently reworking — a second editor there buys a merge-union conflict on "
    "the file this class is least able to afford one in. Close it on top of #3037.",
}

#: OPEN LIVE GAPS on the CI OIDC identities. Same rule: defects with an owner,
#: recorded because applying IAM is an out-of-band watched step (infra/iam/README.md)
#: and IAM is off the auto-merge ALLOWLIST until ADR-129 re-promotion (#2611).
#: (role, entrypoint, channel, reference) → why it is open
#:
#: EMPTIED 2026-08-23 (#2824 repair PR): all three golden-eval gaps are granted in
#: `infra/iam/github-actions-golden-eval-role.permissions.json`. The checked-in doc is now
#: AHEAD of live until the out-of-band `aws iam put-role-policy` runs — that window is
#: `_PENDING_LIVE_APPLY` below, NOT this list, because the repo-side defect is closed and
#: the two states fail for different reasons and get fixed by different people.
_OPEN_CI_GAPS: dict[tuple, str] = {}

#: Repo-side FIXED, live apply PENDING. Read ONLY by the live-parity half — the
#: `infra/iam/README.md` "STAGED, NOT yet applied" idiom, expressed where the check is.
#: An entry here means: the statement is checked in, and the account has not received it.
#: The credentialed run that observes the grant HAS landed reds on the stale entry, so this
#: list cannot outlive its apply either.
#: (role, channel, reference) → the apply that clears it
_PENDING_LIVE_APPLY: dict[tuple, str] = {}

#: Channel references whose id is computed at runtime, so no static grant check is
#: possible. Informational (ADR-103: near-zero false-red rent) — the assertion is
#: only that the list does not GROW without a deliberate entry. Keyed by
#: `channel:module.function`, never by line number, so ordinary edits don't churn it.
_DYNAMIC_REFERENCES: dict[str, str] = {
    "secret:lambdas.common.secret_cache.get_secret": "the shared cache indirection — every caller's id is its own literal",
    "secret:lambdas.common.secret_cache.get_secret_json": "same, JSON variant",
    "secret:lambdas.ingestion.eightsleep_lambda._cached_secret": "secret id is a parameter of the local cache wrapper",
    # #2846: appeared the moment health-auto-export-webhook stopped being a raw
    # `_lambda.Function` and became a create_platform_lambda call — this sweep's
    # population IS the constructor's call sites (_sweep_fleet), so for as long as
    # HAE was constructed by hand it was invisible to the grant lockstep. Same
    # local-cache-wrapper shape as its eightsleep/notion siblings above.
    "secret:lambdas.ingestion.health_auto_export_lambda._cached_secret": "secret id is a parameter of the local cache wrapper",
    "secret:lambdas.ingestion.ingestion_framework.run_ingestion": "SIMP-2 reads the id from the source registry facet",
    "secret:lambdas.ingestion.notion_lambda._cached_secret": "secret id is a parameter of the local cache wrapper",
    "secret:mcp.core.get_api_key": "id from env (MCP_API_KEY_SECRET)",
    "secret:lambdas.operational.key_rotator_lambda.create_secret": "rotation Lambda — the id IS the event payload",
    "secret:lambdas.operational.key_rotator_lambda.test_secret": "rotation Lambda — the id IS the event payload",
    "ssm:lambdas.operational.hevy_restamp_lambda._ssm_get": "param name is the wrapper's argument",
    "ssm:lambdas.operational.hevy_routine_cron_lambda._ssm_get": "param name is the wrapper's argument",
    "ssm:remediation.agent._param": "kill-switch/mode reader — param name is the wrapper's argument "
    "(the remediation role holds `parameter/life-platform/*`, so the whole namespace is granted)",
}

#: `config/` objects with no repo file behind them, and why that is correct.
_CONFIG_WITHOUT_REPO_FILE: dict[str, str] = {
    "config/content_filter.json": "ER-06 / #2370: this repo is PUBLIC and the blocked-content vocabulary is "
    "the most private string set on the platform. The runtime object is owner-provisioned out of band; "
    "`config/content_filter.example.json` is the tracked shape. Deliberately NOT a repo twin.",
}

#: The derived content-filter/privacy-guard consumer set → its watch surface.
#: Every alarm named here is verified to exist in the CDK source below, so a
#: renamed alarm reds instead of pointing at nothing (#2203: a screen that guards
#: nothing). A NEW consumer of the channel with no entry here fails the sweep.
_CONTENT_FILTER_WATCH: dict[str, str] = {
    "lambdas/web/site_api_lambda.py": "alarm:site-api-content-filter-fallback",
    "lambdas/web/site_api_ai_lambda.py": "alarm:site-api-content-filter-fallback",
    "lambdas/emails/between_chronicle_lambda.py": "alarm:between-chronicle-scrub-failed-closed",
    "lambdas/emails/wednesday_chronicle_lambda.py": "alarm:chronicle-delivery-heartbeat",
    "lambdas/emails/coach_panel_podcast_lambda.py": "alarm:chronicle-delivery-heartbeat",
    "lambdas/operational/ai_quality_canary_lambda.py": "alarm:expert-gate-infra-hold",
    "lambdas/coach/coach_history_summarizer.py": "exempt 2026-08-23 (#2824): internal summarisation, no public surface; "
    "its output is re-screened by the chronicle/site chokepoints that DO carry alarms",
    "lambdas/coach/coach_narrative_orchestrator.py": "exempt 2026-08-23 (#2824): internal orchestration, screened again downstream",
    "lambdas/ingestion/bluesky_lambda.py": "exempt 2026-08-23 (#2824): the #1673 gate fails CLOSED (posts are held, not published) "
    "and the grant is missing today — tracked as an _OPEN_GAPS row, not as a watch surface",
    "lambdas/ingestion/mastodon_lambda.py": "exempt 2026-08-23 (#2824): see bluesky",
    "lambdas/ingestion/youtube_lambda.py": "exempt 2026-08-23 (#2824): see bluesky",
    "mcp_server.py": "exempt 2026-08-23 (#2824): owner-only MCP surface (Claude Desktop), not a reader surface",
}


# ══════════════════════════════════════════════════════════════════════════════
# Derived state (computed once)
# ══════════════════════════════════════════════════════════════════════════════

_BASELINE = ge.helper_baseline()
_WIRED = ge.wired_lambdas()


def _sweep_fleet():
    """(gaps, refs_by_lambda, dynamic) for every wired Lambda."""
    gaps, refs, dynamic = {}, {}, set()
    for source_file, wiring in sorted(_WIRED.items()):
        path = os.path.join(REPO, source_file)
        assert os.path.isfile(path), f"{source_file} is wired by create_platform_lambda but does not exist"
        consumer = ge.consumer_refs(path)
        assert consumer is not None, f"{source_file} could not be parsed — the sweep must not skip a wired handler"
        refs[source_file] = consumer
        dynamic |= consumer["dynamic"]
        for channel, ref in ge.missing_refs(consumer, ge.granted_for(wiring, _BASELINE)):
            gaps[(source_file, channel, ref)] = sorted(wiring.policy_fns)
    return gaps, refs, dynamic


FLEET_GAPS, FLEET_REFS, FLEET_DYNAMIC = _sweep_fleet()


def _sweep_ci():
    gaps, seen_roles, dynamic = {}, set(), set()
    for job in ge.ci_jobs():
        doc = ge.iam_doc(job.role)
        if doc is None:
            continue  # a role with no checked-in permissions doc is test_ci_roles_are_all_checked_in's business
        seen_roles.add(job.role)
        grants = ge.doc_grants(doc)
        for entrypoint in job.entrypoints:
            consumer = ge.consumer_refs(os.path.join(REPO, entrypoint))
            if consumer is None:
                continue
            dynamic |= consumer["dynamic"]
            for channel, ref in ge.missing_refs(consumer, grants):
                gaps[(job.role, entrypoint, channel, ref)] = f"{job.workflow}::{job.job}"
    return gaps, seen_roles, dynamic


# PyYAML is a dev dependency; the deploy-critical lane installs no packages and
# still IMPORTS this module during collection (2026-08-24: it redded the whole
# fleet lane exactly like the 2026-08-08 undeclared-PyYAML class). Collection
# must survive; the CI-half tests below skip LOUDLY instead of passing vacuously.
try:
    CI_GAPS, CI_ROLES, CI_DYNAMIC = _sweep_ci()
    _CI_SWEEP_UNAVAILABLE = None
except ImportError as _e:
    CI_GAPS, CI_ROLES, CI_DYNAMIC = {}, set(), set()
    _CI_SWEEP_UNAVAILABLE = f"CI-jobs sweep unavailable: {_e}"

require_ci_sweep = pytest.mark.skipif(
    _CI_SWEEP_UNAVAILABLE is not None,
    reason="PyYAML absent — the CI-jobs half cannot run in this lane (loud skip, never a vacuous pass)",
)


# ══════════════════════════════════════════════════════════════════════════════
# A. The Lambda fleet lockstep
# ══════════════════════════════════════════════════════════════════════════════


def test_every_lambda_consumer_is_granted_its_channel():
    """The lockstep: a handler that reaches a fail-closed channel must ride a role
    that grants it. Fails on any gap not already recorded in `_OPEN_GAPS`."""
    new = {key: fns for key, fns in FLEET_GAPS.items() if key not in _OPEN_GAPS}
    lines = [f"{sf} → rp.{'/'.join(fns) or '<none>'}()  MISSING {channel} {ref}" for (sf, channel, ref), fns in sorted(new.items())]
    assert not new, (
        "These Lambda handlers reach a fail-closed channel their role does not grant. The read "
        "will fail AccessDenied, the consumer degrades silently, and nothing pages (#2824; the "
        "#2503 / 2026-05-17 / #1196 incident class):\n  "
        + "\n  ".join(lines)
        + "\n\nFix the role in cdk/stacks/role_policies_*.py (and deploy the stack from main), or — "
        "if the reference is genuinely unreachable at runtime — say so in _OPEN_GAPS with a date."
    )


def test_open_gap_ratchet_only_shrinks():
    """A recorded gap that no longer reproduces must be DELETED, not left behind.
    An exemption list nobody prunes is how a gate becomes a graveyard."""
    stale = sorted(key for key in _OPEN_GAPS if key not in FLEET_GAPS)
    assert not stale, (
        "These _OPEN_GAPS entries no longer reproduce — the grant landed, or the consumer moved. "
        "Delete them so the ratchet stays honest (#2824):\n  " + "\n  ".join(f"{sf} {channel} {ref}" for sf, channel, ref in stale)
    )


def test_the_sweep_is_non_vacuous():
    """A green run must mean the derivation actually ran. Pins the population, the
    reference floor, and the two named incident subjects."""
    assert len(_WIRED) >= 100, f"only {len(_WIRED)} wired Lambdas found — the create_platform_lambda scan broke"
    total = sum(len(refs[c]) for refs in FLEET_REFS.values() for c in ge.CHANNELS)
    assert total >= 120, f"only {total} channel references derived across the fleet — the call graph broke"

    # #2503's subject: the site API must be seen reaching the content-filter channel.
    assert "config/content_filter.json" in FLEET_REFS["lambdas/web/site_api_lambda.py"]["s3config"]
    # ADR-125's subject: the public AI endpoint must be seen reaching the budget tier…
    assert "/life-platform/budget-tier" in FLEET_REFS["lambdas/web/site_api_ai_lambda.py"]["ssm"]
    # …and, since #3059, that reference must be a GRANTED one (the fail-closed path is live).
    assert ("lambdas/web/site_api_ai_lambda.py", "ssm", "/life-platform/budget-tier") not in FLEET_GAPS
    # 2026-05-17's subject: the SES configuration-set the daily brief sends through.
    assert "life-platform-emails" in FLEET_REFS["lambdas/emails/daily_brief_lambda.py"]["ses"]


def test_reachability_is_call_scoped_not_import_closure():
    """Pin the derivation rule that decides whether this gate is usable.

    `ai/budget_guard.py` is in almost every handler's import closure, but only three
    modules ever call `read_breakdown()`. Attributing by closure would hand ~50
    handlers a phantom `/life-platform/budget-breakdown` consumer — a gate that reds
    on nothing real gets disabled. Prove the discrimination survives.
    """
    breakdown = "/life-platform/budget-breakdown"
    readers = {sf for sf, refs in FLEET_REFS.items() if breakdown in refs["ssm"]}
    assert "lambdas/emails/daily_brief_lambda.py" in readers, "the brief's headroom line calls read_breakdown() — it must be attributed"
    assert (
        len(readers) <= 6
    ), f"{len(readers)} handlers attributed budget-breakdown — attribution has collapsed to import closure: {sorted(readers)}"
    # …while budget-TIER, which ai_calls consults on every AI path, is broadly reached.
    tier_readers = {sf for sf, refs in FLEET_REFS.items() if "/life-platform/budget-tier" in refs["ssm"]}
    assert len(tier_readers) >= 30, f"only {len(tier_readers)} handlers reach budget-tier — the call graph has collapsed to file-local"


def test_helper_baseline_is_derived_and_classified():
    """`create_platform_lambda` grants IAM of its own. It must be read from the real
    helper (not restated here), and every conditional grant must be classified —
    `helper_baseline()` raises otherwise, which is the guard-the-SET half."""
    ssm_baseline = [b for b in _BASELINE if any(a.startswith("ssm:") for a in b.actions)]
    assert ssm_baseline, "the helper's budget-tier baseline grant vanished — every role's SSM set just changed"
    resources = {r for b in ssm_baseline for r in b.resources}
    assert any("budget-tier" in r for r in resources), resources
    assert all(g in ge._KNOWN_HELPER_GUARDS for b in _BASELINE for g in b.guards)


# ══════════════════════════════════════════════════════════════════════════════
# B. The CI identity lockstep
# ══════════════════════════════════════════════════════════════════════════════


@require_ci_sweep
def test_ci_jobs_that_assume_a_role_are_discovered():
    """Non-vacuity for the CI half: the workflow scan must find the jobs and roles."""
    jobs = ge.ci_jobs()
    assert len(jobs) >= 15, f"only {len(jobs)} OIDC-assuming workflow jobs found — the workflow scan broke"
    assert {"github-actions-deploy-role", "github-actions-diagnosis-role", "github-actions-golden-eval-role"} <= {j.role for j in jobs}
    assert any(j.entrypoints for j in jobs), "no job resolved a python entrypoint — the `run:` scan broke"

    # The #3059 subject, pinned: the visual-qa job's `--reader-truth` path must be seen
    # reaching BOTH cycle params through tests/visual_ai_qa.py. If this ever goes empty
    # the CI half has stopped covering the incident it was written for — and would have
    # reported green on the exact defect #3059 found by hand.
    diagnosis = {c: set() for c in ge.CHANNELS}
    for job in jobs:
        if job.role != "github-actions-diagnosis-role":
            continue
        for entrypoint in job.entrypoints:
            refs = ge.consumer_refs(os.path.join(REPO, entrypoint))
            if refs:
                for channel in ge.CHANNELS:
                    diagnosis[channel] |= refs[channel]
    assert {"/life-platform/budget-tier", "/life-platform/experiment-cycle"} <= diagnosis["ssm"], diagnosis["ssm"]


@require_ci_sweep
def test_every_ci_consumer_is_granted_its_channel():
    """A CI job's OIDC role must grant every fail-closed channel its entrypoints
    reach. #3059 found the diagnosis role's missing budget-tier read by accident,
    four months after the role was written; this is the systematic version."""
    new = {k: v for k, v in CI_GAPS.items() if k not in _OPEN_CI_GAPS}
    lines = [f"{role} ({where}) running {entry}  MISSING {channel} {ref}" for (role, entry, channel, ref), where in sorted(new.items())]
    assert not new, (
        "These CI jobs run code that reaches a fail-closed channel their OIDC role does not "
        "grant. The read fails AccessDenied and the consumer degrades silently — a budget "
        "guard that cannot read its tier does not guard (#2824):\n  "
        + "\n  ".join(lines)
        + "\n\nAdd the statement to infra/iam/<role>.permissions.json AND apply it out of band "
        "(infra/iam/README.md); `python3 deploy/verify_oidc_iam.py` confirms repo↔live."
    )


@require_ci_sweep
def test_open_ci_gap_ratchet_only_shrinks():
    stale = sorted(key for key in _OPEN_CI_GAPS if key not in CI_GAPS)
    assert not stale, "These _OPEN_CI_GAPS entries no longer reproduce — delete them (#2824):\n  " + "\n  ".join(map(str, stale))


@require_ci_sweep
def test_every_ci_role_has_a_checked_in_permissions_doc():
    """A role assumed by a workflow with no `infra/iam/*.permissions.json` is
    invisible to both this sweep and `deploy/verify_oidc_iam.py`."""
    missing = sorted(
        {j.role for j in ge.ci_jobs()}
        - {os.path.basename(p).split(".")[0] for p in glob.glob(os.path.join(ge.IAM_DIR, "*.permissions.json"))}
    )
    assert not missing, "Workflow jobs assume these roles, but no infra/iam/<role>.permissions.json exists:\n  " + "\n  ".join(missing)


def test_deploy_role_grants_artifact_tagging_for_fleet_bookkeeping():
    """#3186 pin — a bash-shaped consumer the call-graph sweep cannot see.

    `deploy/deploy_fleet.sh` maintains the TB7-25 rollback artifact with an
    s3-to-s3 `aws s3 cp` of the (multipart-sized) MCP bundle; on the multipart
    path the CLI reads the source object's tags (`s3:GetObjectTagging`) and
    re-applies them at the destination, so both tagging actions must ride on the
    CI deploy role or the fleet deploy reds AFTER all function updates succeed
    and leaves `previous.zip` stale — found live 2026-08-25 (#3186). Section B
    derives consumers from python entrypoints only, so this grant is pinned by
    name. The first assert keeps the pin from outliving the code it guards:
    if the bookkeeping copy ever leaves deploy_fleet.sh, delete this test.
    """
    fleet = open(os.path.join(REPO, "deploy", "deploy_fleet.sh")).read()
    assert "previous.zip" in fleet, "deploy_fleet.sh no longer maintains rollback artifacts — delete this pin (#3186)"

    with open(os.path.join(ge.IAM_DIR, "github-actions-deploy-role.permissions.json")) as fh:
        doc = json.load(fh)

    def _as_list(v):
        return v if isinstance(v, list) else [v]

    tagging = [
        s
        for s in doc["Statement"]
        if s.get("Effect") == "Allow" and {"s3:GetObjectTagging", "s3:PutObjectTagging"} <= set(_as_list(s.get("Action")))
    ]
    resources = {r for s in tagging for r in _as_list(s["Resource"])}
    assert any(r.endswith("/deploys/*") or r.endswith(":matthew-life-platform/*") for r in resources), (
        "the CI deploy role no longer grants s3:Get/PutObjectTagging on deploys/* — the fleet "
        "deploy's rollback-artifact copies AccessDenied after every function updates (#3186)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# C. The dynamic-reference ratchet
# ══════════════════════════════════════════════════════════════════════════════


@require_ci_sweep  # unions FLEET_DYNAMIC | CI_DYNAMIC — half the observed set needs the yaml sweep
def test_dynamic_reference_ratchet_does_not_grow():
    """Runtime-computed channel ids cannot be grant-checked statically. Recording
    them is informational — the rule is only that a NEW one is a deliberate entry,
    so an indirection can't be used (accidentally) to slip past the lockstep."""
    observed = FLEET_DYNAMIC | CI_DYNAMIC
    unregistered = sorted(observed - set(_DYNAMIC_REFERENCES))
    assert not unregistered, (
        "New unparseable channel references. Each hides a resource id from the grant "
        "lockstep — register it with a reason, or make the id a literal/constant so it "
        "can be checked (#2824):\n  " + "\n  ".join(unregistered)
    )
    stale = sorted(set(_DYNAMIC_REFERENCES) - observed)
    assert not stale, "_DYNAMIC_REFERENCES entries no longer observed — delete them:\n  " + "\n  ".join(stale)


# ══════════════════════════════════════════════════════════════════════════════
# D. Every referenced config/ prefix has a deploy path (the L110 shape)
# ══════════════════════════════════════════════════════════════════════════════


def _repo_config_files() -> set:
    root = os.path.join(REPO, "config")
    return {os.path.relpath(p, REPO) for p in glob.glob(os.path.join(root, "**", "*"), recursive=True) if os.path.isfile(p)}


def test_every_referenced_config_object_has_a_producer():
    """2026-08-02's incident: a `config/` prefix a Lambda reads, that nothing in the
    repo deploys. A key here is satisfied by a tracked repo file (the #2019 twin
    that `deploy/config_twin_sync.py` pushes), by a runtime writer, or by a dated
    entry in `_CONFIG_WITHOUT_REPO_FILE` explaining why it is out of band."""
    repo_files = _repo_config_files()
    written = {ref for refs in FLEET_REFS.values() for ref in refs["s3config"]}
    orphans = []
    for key in sorted(written):
        if key in _CONFIG_WITHOUT_REPO_FILE:
            continue
        if "*" in key:
            # A wildcard segment is the #2057 alias shape: `config/{user}/x.json` serves
            # the bytes of the `config/x.json` twin. Satisfied by a direct match OR by the
            # twin the alias collapses onto.
            collapsed = re.sub(r"/\*+(?=/)", "", key)
            if any(fnmatch.fnmatch(f, key) for f in repo_files) or collapsed in repo_files:
                continue
        elif key in repo_files:
            continue
        orphans.append(key)
    assert not orphans, (
        "These `config/` objects are read by a deployed Lambda but nothing in the repo produces "
        "them — a stale or absent object serves silently (#2824, the 2026-08-02 shape):\n  "
        + "\n  ".join(orphans)
        + "\n\nAdd the repo twin under config/, or record the out-of-band channel in "
        "_CONFIG_WITHOUT_REPO_FILE with the reason."
    )


def test_config_exemptions_are_still_absent_from_the_repo():
    """The one sanctioned out-of-band config object must stay out of the repo — if
    `config/content_filter.json` ever appears as a tracked file, ER-06 has been
    broken and the exemption must go, not be kept."""
    for key in _CONFIG_WITHOUT_REPO_FILE:
        assert not os.path.exists(
            os.path.join(REPO, key)
        ), f"{key} is now a tracked file — remove its _CONFIG_WITHOUT_REPO_FILE exemption (or the file)"


# ══════════════════════════════════════════════════════════════════════════════
# E. The content-filter consumer set owns a watch surface
# ══════════════════════════════════════════════════════════════════════════════

_CONTENT_FILTER_KEY = "config/content_filter.json"


def _cdk_alarm_names() -> set:
    names = set()
    for path in glob.glob(os.path.join(REPO, "cdk", "stacks", "*.py")):
        names |= set(re.findall(r'alarm_name="([^"]+)"', open(path, encoding="utf-8").read()))
    return names


def _content_filter_consumers() -> set:
    return {sf for sf, refs in FLEET_REFS.items() if _CONTENT_FILTER_KEY in refs["s3config"]}


def test_content_filter_consumer_set_is_fully_classified():
    """#2824 acceptance: every consumer of the #2503 channel maps to a heartbeat/alarm
    or a dated exemption. Derived membership — a new consumer joins the set the day it
    lands and fails until someone decides how its failure becomes visible."""
    consumers = _content_filter_consumers()
    assert len(consumers) >= 10, f"only {len(consumers)} content-filter consumers derived — the sweep broke"
    unclassified = sorted(consumers - set(_CONTENT_FILTER_WATCH))
    assert not unclassified, (
        "New consumer(s) of the fail-closed content-filter channel with no watch surface. An "
        "unavailable vocabulary here is either a silent no-op scrub or a silent hold — neither "
        "is visible without an alarm (#2824 / #2503 / #2655):\n  "
        + "\n  ".join(unclassified)
        + "\n\nMap each to `alarm:<name>` (the alarm must exist in cdk/stacks) or to a dated exemption."
    )
    stale = sorted(set(_CONTENT_FILTER_WATCH) - consumers)
    assert not stale, "_CONTENT_FILTER_WATCH entries that no longer consume the channel — delete them:\n  " + "\n  ".join(stale)


def test_content_filter_watch_alarms_exist_in_cdk():
    """Guard the guard: a watch surface that names a non-existent alarm is a screen
    that guards nothing (#2203). Every `alarm:<name>` is checked against the real
    CDK source, so renaming an alarm reds here instead of orphaning a consumer."""
    alarms = _cdk_alarm_names()
    assert len(alarms) >= 40, f"only {len(alarms)} alarm names parsed from cdk/stacks — the scan broke"
    dangling = sorted(
        f"{consumer} → {surface}"
        for consumer, surface in _CONTENT_FILTER_WATCH.items()
        if surface.startswith("alarm:") and surface[len("alarm:") :] not in alarms
    )
    assert not dangling, "These content-filter watch surfaces name an alarm that does not exist in cdk/stacks:\n  " + "\n  ".join(dangling)


# ══════════════════════════════════════════════════════════════════════════════
# F. LIVE parity — the checked-in doc is not the grant; the live policy is
# ══════════════════════════════════════════════════════════════════════════════


def _has_aws() -> bool:
    try:
        import boto3

        boto3.client("sts", region_name="us-west-2").get_caller_identity()
        return True
    except Exception:
        return False


@pytest.mark.integration
@require_ci_sweep
def test_live_oidc_role_grants_cover_the_derived_consumer_set():
    """Everything above compares code to the REPO's IAM. `infra/iam/*.json` is the
    source of truth only in the sense that drift from it is a finding — applying it
    is an out-of-band step, so a role can be correct in git and stranded in the
    account. This half asks the account.

    Strictly read-only (`iam:GetRolePolicy`), and a LOUD skip when the run has no
    credentials — CI has none on PRs (#3043 pattern), and a silent pass is a check
    that never ran (#2876).
    """
    if os.environ.get("SKIP_AWS_TESTS"):
        pytest.skip("SKIP_AWS_TESTS set — LIVE OIDC grant parity NOT checked this run")
    if not _has_aws():
        pytest.skip("no AWS credentials — LIVE OIDC grant parity NOT checked this run (offline lane; the repo-side halves above still ran)")

    import boto3

    sys.path.insert(0, os.path.join(REPO, "deploy"))
    import verify_oidc_iam  # noqa: PLC0415 — the shipping verifier owns the role↔policy-name map

    iam = boto3.client("iam")
    consumers: dict[str, dict] = {}
    for job in ge.ci_jobs():
        for entrypoint in job.entrypoints:
            refs = ge.consumer_refs(os.path.join(REPO, entrypoint))
            if refs is None:
                continue
            bucket = consumers.setdefault(job.role, {c: set() for c in ge.CHANNELS})
            for channel in ge.CHANNELS:
                bucket[channel] |= refs[channel]

    findings, checked = [], 0
    still_pending: set = set()
    for role, spec in verify_oidc_iam.ROLES.items():
        consumer = consumers.get(role)
        if not consumer or not any(consumer[c] for c in ge.CHANNELS):
            continue
        live = iam.get_role_policy(RoleName=role, PolicyName=spec["inline_policy_name"])["PolicyDocument"]
        checked += 1
        for channel, ref in ge.missing_refs(consumer, ge.doc_grants(live)):
            if any(k[0] == role and k[2] == channel and k[3] == ref for k in _OPEN_CI_GAPS):
                continue  # a repo-side gap, already recorded and owned
            if (role, channel, ref) in _PENDING_LIVE_APPLY:
                still_pending.add((role, channel, ref))
                continue  # checked in, apply not run yet
            findings.append(f"{role}: LIVE policy does not grant {channel} {ref}")

    assert checked, "no OIDC role with a derived consumer set was checked live — the derivation broke, not the account"
    assert not findings, "LIVE IAM does not grant what the code reaches (repo↔live drift on top of a consumer):\n  " + "\n  ".join(findings)

    # Shrink-only, the same rule as every other ratchet here: once the apply lands, the
    # live policy DOES grant it and the entry must be deleted rather than left behind.
    # This is the only lane that can tell — it is the only one that asks the account.
    landed = sorted(set(_PENDING_LIVE_APPLY) - still_pending)
    assert not landed, (
        "These _PENDING_LIVE_APPLY entries are granted LIVE now — the out-of-band apply ran. "
        "Delete them so the list stays a queue, not a graveyard (#2824):\n  " + "\n  ".join(map(str, landed))
    )


# ══════════════════════════════════════════════════════════════════════════════
# G. Mutation proofs — the gate must red in BOTH directions
# ══════════════════════════════════════════════════════════════════════════════


def test_mutation_removing_a_grant_from_a_permissions_doc_reds():
    """Direction 1 (grant removed): delete the SSM statement from a COPY of the real
    diagnosis-role doc — the doc whose missing budget-tier grant #3059 found — and the
    checker must report the consumer it strands."""
    doc = ge.iam_doc("github-actions-diagnosis-role")
    assert doc is not None
    consumer = {"ssm": {"/life-platform/budget-tier"}, "secret": set(), "s3config": set(), "ses": set()}

    assert ge.missing_refs(consumer, ge.doc_grants(doc)) == [], "the live doc should already grant budget-tier (fixed by #3059)"

    mutated = copy.deepcopy(doc)
    mutated["Statement"] = [s for s in mutated["Statement"] if "ssm:GetParameter" not in (s.get("Action") or [])]
    assert mutated["Statement"] != doc["Statement"], "the SSM statement was not found to remove — re-read the doc"
    assert ge.missing_refs(consumer, ge.doc_grants(mutated)) == [("ssm", "/life-platform/budget-tier")]


def test_mutation_removing_a_role_policy_grant_reds():
    """Direction 1, fleet side: drop `config/*` from a real role's granted set and the
    lockstep must report the content-filter consumer it strands."""
    wiring = _WIRED["lambdas/web/site_api_ai_lambda.py"]
    grants = ge.granted_for(wiring, _BASELINE)
    consumer = FLEET_REFS["lambdas/web/site_api_ai_lambda.py"]
    assert not [g for g in ge.missing_refs(consumer, grants) if g[0] == "s3config"]

    mutated = {k: set(v) for k, v in grants.items()}
    mutated["s3config"] = {p for p in mutated["s3config"] if not p.startswith("config/")}
    assert ("s3config", _CONTENT_FILTER_KEY) in ge.missing_refs(consumer, mutated)


def test_mutation_an_unregistered_fail_closed_consumer_reds(tmp_path):
    """Direction 2 (consumer added): synthesise a handler that reads a brand-new
    fail-closed SSM parameter through a shared module, and prove the call graph finds
    it and the lockstep reds against a real role's grants."""
    root = tmp_path / "lambdas"
    (root / "shared").mkdir(parents=True)
    (root / "handlers").mkdir()
    (root / "shared" / "__init__.py").write_text("")
    (root / "handlers" / "__init__.py").write_text("")
    (root / "shared" / "kill_switch.py").write_text(
        "import boto3\n"
        '_PARAM = "/life-platform/publish-kill-switch"\n'
        "def enabled():\n"
        '    return boto3.client("ssm").get_parameter(Name=_PARAM)["Parameter"]["Value"] == "on"\n'
    )
    (root / "handlers" / "new_lambda.py").write_text(
        "from shared import kill_switch\n" "def lambda_handler(event, context):\n" "    return {'ok': kill_switch.enabled()}\n"
    )

    roots = (str(root),)
    consumer = ge.consumer_refs(str(root / "handlers" / "new_lambda.py"), roots=roots)
    assert consumer["ssm"] == {"/life-platform/publish-kill-switch"}, consumer["ssm"]

    grants = ge.granted_for(_WIRED["lambdas/web/site_api_ai_lambda.py"], _BASELINE)
    assert ("ssm", "/life-platform/publish-kill-switch") in ge.missing_refs(consumer, grants)


def test_mutation_an_unreferenced_shared_accessor_is_not_attributed(tmp_path):
    """The false-positive direction. A handler that imports a module must NOT inherit
    the channels of the accessors it never references — that is the import-closure
    failure mode which produced 35 phantom gaps in this sweep's design."""
    root = tmp_path / "lambdas"
    (root / "shared").mkdir(parents=True)
    (root / "shared" / "__init__.py").write_text("")
    (root / "shared" / "two_doors.py").write_text(
        "import boto3\n"
        "def used():\n"
        '    return boto3.client("ssm").get_parameter(Name="/life-platform/used")\n'
        "def never_called():\n"
        '    return boto3.client("ssm").get_parameter(Name="/life-platform/unused")\n'
    )
    (root / "handler.py").write_text("from shared import two_doors\n" "def lambda_handler(e, c):\n" "    return two_doors.used()\n")

    consumer = ge.consumer_refs(str(root / "handler.py"), roots=(str(root),))
    assert consumer["ssm"] == {"/life-platform/used"}, f"attribution leaked into an unreferenced accessor: {consumer['ssm']}"


def test_mutation_an_unclassified_helper_guard_reds(tmp_path):
    """Guard the SET on the grant side too: if `create_platform_lambda` grows a
    conditionally-applied grant under a guard nobody classified, the derivation must
    refuse rather than guess. Proved against a synthetic helper."""
    fake = tmp_path / "lambda_helpers.py"
    fake.write_text(
        "def create_platform_lambda(scope, id, brand_new_flag=None):\n"
        "    if brand_new_flag:\n"
        '        role.add_to_policy(iam.PolicyStatement(actions=["ssm:GetParameter"], resources=["arn:aws:ssm:*:*:parameter/life-platform/x"]))\n'
    )
    original = ge._HELPERS
    try:
        ge._HELPERS = str(fake)
        with pytest.raises(AssertionError, match="does not know"):
            ge.helper_baseline()
    finally:
        ge._HELPERS = original
    # …and the real helper still parses clean afterwards.
    assert ge.helper_baseline()


def test_the_derivation_reads_real_sources_not_a_baked_snapshot():
    """Fixture-must-be-the-wire: assert the three sources this sweep depends on are
    the shipping ones, not copies. A refactor that moves any of them must be noticed
    here rather than turning the gate green-and-empty."""
    assert os.path.isfile(ge._HELPERS), ge._HELPERS
    assert len(ge.POLICY_MODULES) >= 7, [m.__name__ for m in ge.POLICY_MODULES]
    assert ge.resolve_policy_fn("operational_permanence") is not None, "the #1400 sibling is not resolvable — the glob broke"
    tree = ast.parse(open(ge._HELPERS, encoding="utf-8").read())
    assert any(isinstance(n, ast.FunctionDef) and n.name == "create_platform_lambda" for n in tree.body)


if __name__ == "__main__":
    import subprocess

    sys.exit(subprocess.run(["python3", "-m", "pytest", __file__, "-v", "--tb=short"], cwd=REPO).returncode)
