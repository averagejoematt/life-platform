"""scripts/gate_census_proofs.py — recorded can-it-fail verdicts that do not fit in
`scripts/gate_census.py`: census family 6, the drift-sentinel per-check gates
(#3129/#3160, epic #2578 slice 2), and `GUARD_PROOFS` at the foot of this file — family
2 (guard-script) records, added for the same size reason (#2834, 2026-08-30).

WHY ITS OWN MODULE
──────────────────
`scripts/gate_census.py` sits at 1,183 lines against the 1,200-line hard ceiling
(`tests/test_module_size_guard.py`, #1665) and was never baselined — #2610's policy is
extraction, never a new BASELINE entry. Fifteen `Proof` records do not fit. Same
one-way split shape as `gate_census_structural.py` / `gate_census_sentinel.py`: this
module has ZERO dependency on `gate_census`, so there is no import cycle even when
`gate_census.py` is executed directly as `__main__`. It exports plain dicts and
`gate_census` constructs its own `Proof` from them.

WHAT A RECORD HERE MEANS, AND WHAT IT DOES NOT
──────────────────────────────────────────────
The bar is `gate_census.PROVEN_CAN_FAIL`'s bar, unchanged: the defect the check exists
to detect was introduced on purpose and the check was WATCHED reporting it. For this
family the mutation lives in a test — the transports are monkeypatched, the condition
is planted on the real call shapes, and `observed` records the pytest outcome. That is
weaker than a live CI observation and stronger than reasoning; each record says which
it is.

Family 6 is held to a TWO-HALF bar that the other five families are not, because the
#3112 autopsy is what created it. `check_codeql_alerts` had a detect path that was
perfectly correct and had never once run — the API was unreadable on 3/3 recorded
sweeps, and `error` was not `drift`, so the finding reached nobody. So every record
below cites BOTH:

  (a) the planted condition the check exists to detect → reports `drift`;
  (b) the planted CANNOT-OBSERVE state → reports `error`/`degraded`/`unavailable`
      LOUDLY, and never `clean`.

`scope` carries what the green still excludes — most often the seam #3112 named: which
statuses reach `remediation/drift_report.as_signal`'s needs-human triage path, and
which only land in the record.

Re-run every record here with:
    python3 -m pytest tests/test_sentinel_canfail_2578.py tests/test_drift_sentinel.py \\
        tests/test_raw_replication_dil027.py -q
"""

from __future__ import annotations

from typing import Any

# The date family 6 became enumerable by the census (#3160 merged). Nothing here may
# predate it — a proof recorded against a gate the inventory cannot see is the #3129
# orphan-proof problem, and `tests/test_sentinel_canfail_2578.py` asserts the floor.
_PROVED_ON = "2026-08-25"

_CANFAIL_SUITE = "python3 -m pytest tests/test_sentinel_canfail_2578.py"
_DS_SUITE = "python3 -m pytest tests/test_drift_sentinel.py"
_REPL_SUITE = "python3 -m pytest tests/test_raw_replication_dil027.py"

# The as_signal seam, stated once and referenced by the scopes that share it. #3112's
# defect (c): `remediation/drift_report.as_signal` builds its needs-human `flagging`
# map from checks whose own status is exactly "drift". Everything else — error,
# degraded, unavailable — appears in the persisted record and the printed summary but
# spins up no triage run. Saying "this check can fail" without saying which of its
# failures reaches a human is the substitution this epic exists to catch.
_ERROR_IS_NOT_A_SIGNAL = (
    "The cannot-observe half reports `error`, which run_sweep aggregates to a sweep status of "
    "`degraded`. That prints loudly (print_summary emits the detail, _summary names it in its "
    "'check(s) could not run' line) but does NOT reach drift_report.as_signal's needs-human "
    "triage path, which only collects checks whose own status is `drift`. Only check_codeql_alerts "
    "(#3112) and check_sentinel_cadence (#3130) currently fail CLOSED into `drift` on unreadable. "
    "Green here therefore means 'observed clean'; degraded means 'nobody was paged'."
)

SENTINEL_PROOFS: dict[str, dict[str, Any]] = {
    # ── the ten defined in deploy/drift_sentinel.py ───────────────────────────
    "sentinel::deploy/drift_sentinel.py::check_cfn_drift": {
        "gate_name": "check_cfn_drift",
        "command": f"{_DS_SUITE} -k cfn_drift -q",
        "mutation": (
            "(a) a fake CloudFormation client returning StackDriftStatus=DRIFTED for LifePlatformServe with "
            "two resource drifts — one documented #1781 noise (a case-only Cors/AllowHeaders difference) and one "
            "real (/Policies/0 changed on SiteApiLambdaRole). (b) every stack's detect_stack_drift raising "
            "AccessDenied, and separately a non-AccessDenied Throttling error."
        ),
        "observed": (
            "(a) exit 0 with the assertion holding: status='drift', only SiteApiLambdaRole in `drifted`, the CORS "
            "resource moved to `filtered_noise` — a mutation that removed the real diff flips the same check to "
            "'clean', so the filter is not swallowing findings. (b) all-AccessDenied -> status='error' plus "
            "`dead_capability` (pre-#1227 this returned the soft 'degraded' and would have failed this assertion); "
            "Throttling -> status='degraded'. No case reports clean."
        ),
        "scope": (
            "Per-stack fail-soft: ONE stack erroring leaves the other nine reporting, and the sweep reads "
            "'degraded' — a drifted stack behind an AccessDenied on a different stack is still found. The "
            "escalation to `error` requires ALL stacks AccessDenied AND every detail containing that string, so a "
            "mixed authorization failure stays soft. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/drift_sentinel.py::check_postflight": {
        "gate_name": "check_postflight",
        "command": f"{_CANFAIL_SUITE} -k postflight -q",
        "mutation": (
            "(a) a fake session_postflight module on the real call shapes, one sub-check at a time: a function still "
            "referencing the retired life-platform-shared-utils layer (#781), a lambda whose live timeout differs "
            "from its CDK declaration, and a deployed zip missing a root module. (b) each sub-check raising "
            "AccessDenied in turn, and — the interesting one — `import session_postflight` itself raising ImportError."
        ),
        "observed": (
            "(a) exit 0 with each sub-check reporting status='drift' and naming the planted function; the same fakes "
            "returning empty report 'clean', so the drift is the plant and not a constant. (b) each raising sub-check "
            "-> status='error' carrying the planted reason. The import mutation FAILED against the pre-fix code: it "
            "raised ImportError out of check_postflight and therefore out of run_sweep(), which wraps nothing — under "
            "the remediation workflow's `continue-on-error: true` that meant no drift-log record, no red step and all "
            "fifteen checks dark. Fixed in the same change; the three sub-checks now report `error`."
        ),
        "scope": (
            "This was the ONE unguarded statement in the sweep and the reason its cannot-observe half matters more "
            "than most: a raise here is not a degraded check, it is a degraded SWEEP. "
            "test_a_crashed_postflight_would_have_taken_the_whole_sweep_with_it pins that run_sweep() still has no "
            "try of its own, so the per-check fail-soft stays load-bearing rather than stylistic. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/drift_sentinel.py::check_orphan_functions": {
        "gate_name": "check_orphan_functions",
        "command": f"{_CANFAIL_SUITE} -k orphan_functions -q",
        "mutation": (
            "(a) a live Lambda list containing 'console-made-hotfix' against a stack resource list that does not "
            "carry it. (b) BOTH vacuum directions: list_functions raising AccessDenied (live side unreadable) and "
            "list_stack_resources raising AccessDenied (IaC side unreadable)."
        ),
        "observed": (
            "(a) exit 0, status='drift', orphans==['console-made-hotfix']; the same fake with the function present in "
            "the stack list, and with the two allowlisted CDK-toolkit prefixes added, reports 'clean'. (b) live side "
            "-> status='error' naming list_functions; IaC side -> status='error' naming list_stack_resources, with no "
            "`orphans` key at all. Neither vacuum reports clean or publishes a list."
        ),
        "scope": (
            "The two failures are asymmetric and both are ruled out here: an empty LIVE set computes live-managed == "
            "empty and would have read clean (a silent pass), while an empty MANAGED set would have declared every "
            "live Lambda an orphan (a dozen false positives). Region-scoped to us-west-2 by design — a Lambda created "
            "out of band in another region is outside this check entirely. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/drift_sentinel.py::check_oidc_iam": {
        "gate_name": "check_oidc_iam",
        "command": f"{_DS_SUITE} -k oidc_iam -q  &&  {_CANFAIL_SUITE} -k oidc_iam -q",
        "mutation": (
            "(a) the delegated deploy/verify_oidc_iam.py comparator stubbed to exit 1 with two '[DRIFT]' stdout "
            "lines. (b) subprocess.run raising FileNotFoundError (the comparator missing / interpreter gone), and "
            "separately exit 1 with a traceback carrying no '[DRIFT]' lines at all."
        ),
        "observed": (
            "(a) exit 0 with status='drift' and the two mismatch lines harvested; exit 0 from the comparator reports "
            "'clean'. (b) the raise -> status='error' naming verify_oidc_iam; the traceback case -> status='drift' "
            "with an EMPTY mismatches list."
        ),
        "scope": (
            "IMPORTANT and recorded because the second observation is a mislabel, not a pass: the check maps ANY "
            "non-zero exit of the comparator to `drift` and only harvests '[DRIFT]'-prefixed lines for the detail. A "
            "comparator that dies of its own bug therefore reads as an IAM identity change with no mismatches listed. "
            "Loud, so not a dark gate — but 'drift' here must not be read as 'a specific identity differs'. The "
            "verdict is on this wrapper; the comparison itself is verify_oidc_iam.py's own gate."
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/drift_sentinel.py::check_bucket_policy": {
        "gate_name": "check_bucket_policy",
        "command": f"{_DS_SUITE} -k bucket_policy -q",
        "mutation": (
            "against the REAL deploy/bucket_policy.json as the expectation: (a) the live policy with the raw/* "
            "resource removed from the ProtectDataFromDeployScripts Deny, and separately with that whole statement "
            "deleted. (b) get_bucket_policy raising."
        ),
        "observed": (
            "exit 0 with: (a) status='drift' listing the dropped prefix, and status='drift' with the full expected "
            "prefix set reported missing when the statement is gone; the unmodified source policy reports 'clean' "
            "with missing_prefixes==[]. (b) status='error'. No mutation produced a clean verdict."
        ),
        "scope": (
            "Compares the Deny's RESOURCE set only. A statement whose Sid, Effect and s3:DeleteObject action all "
            "still match but whose Principal or Condition was loosened passes this check — the prefixes are intact, "
            "the protection may not be. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/drift_sentinel.py::check_s3_lifecycle": {
        "gate_name": "check_s3_lifecycle",
        "command": f"{_DS_SUITE} -k s3_lifecycle -q",
        "mutation": (
            "against the REAL deploy/s3_lifecycle.json: (a) a declared rule ID absent from the live configuration, a "
            "live rule whose NoncurrentVersionExpiration was weakened, and a live rule ID that is not declared at "
            "all. (b) get_bucket_lifecycle_configuration raising, and separately the declared JSON file unreadable."
        ),
        "observed": (
            "exit 0 with all three (a) shapes reporting status='drift' in the right bucket (missing_rule_ids / "
            "changed_rule_ids / extra_rule_ids) and a detail naming which; the untouched configuration reports "
            "'clean'. (b) both unreadable sides -> status='error' naming which read failed."
        ),
        "scope": (
            "Compares six fields per rule (Filter, Status, Expiration, NoncurrentVersionExpiration, Transitions, "
            "AbortIncompleteMultipartUpload). A live rule differing ONLY outside that set is invisible. Single-writer "
            "by construction — apply_s3_lifecycle.sh PUTs the same JSON verbatim — so there is no second expectation "
            "to drift against. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/drift_sentinel.py::check_dynamodb_ttl": {
        "gate_name": "check_dynamodb_ttl",
        "command": f"{_DS_SUITE} -k dynamodb_ttl -q",
        "mutation": (
            "NEW 2026-08-25 (#2799 residual table-config-noop-ttl, #951 recurrence): (a) a fake "
            "describe_time_to_live returning the #951 shape itself — TimeToLiveStatus=ENABLED but "
            "AttributeName='expires_at' against the declared 'ttl' (cdk/stacks/constants.py "
            "TABLE_TTL_ATTRIBUTE), and separately TimeToLiveStatus=DISABLED on the correct attribute. "
            "(b) describe_time_to_live raising."
        ),
        "observed": (
            "exit 0 with (a) both shapes reporting status='drift' — the attribute-mismatch case names "
            "both the live and declared attribute in `detail` and cites #951; the disabled case says "
            "'never reaped'. The matching ENABLED/'ttl' response reports 'clean'. (b) -> status='error' "
            "naming describe_time_to_live; never clean."
        ),
        "scope": (
            "Declared-vs-live on ONE table config leg (which attribute, and whether it's enabled) — same "
            "idiom as check_s3_lifecycle, one rule instead of several. It does NOT check that any "
            "individual item WRITER keys its expiry field to the declared attribute (the actual #951 "
            "defect was a writer using 'expires_at'); that would need a repo-wide writer sweep, which is "
            "out of scope for this check and not yet built. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/drift_sentinel.py::check_site_sha_ancestry": {
        "gate_name": "check_site_sha_ancestry",
        "command": f"{_DS_SUITE} -k site_sha_ancestry -q",
        "mutation": (
            "(a) a fake /version.json build SHA with `git merge-base --is-ancestor` stubbed to return 1 (exists but "
            "diverged) and separately 128 (unknown to git entirely). (b) the HTTPS GET raising, and separately a "
            "version.json whose `build` field is missing."
        ),
        "observed": (
            "exit 0 with (a) both returncodes reporting status='drift', each with a detail distinguishing 'not an "
            "ancestor of origin/main' from 'not found in git history at all'; returncode 0 reports 'clean'. (b) both "
            "-> status='error'. A failing `git fetch` is separately proved NON-fatal (falls back to the local ref) "
            "rather than silently clean."
        ),
        "scope": (
            "Compares against whatever origin/main the RUNNER has. A shallow or stale clone can make a legitimate "
            "SHA look unknown (returncode 128) and produce a false drift — which is why the fetch failure is proved "
            "non-fatal but visible. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/drift_sentinel.py::check_doc_literals": {
        "gate_name": "check_doc_literals",
        "command": f"{_CANFAIL_SUITE} -k doc_literals -q",
        "mutation": (
            "(a) a fake CloudWatch returning exactly the REAL documented alarm_count PLUS ONE (never a hand-typed "
            "number — the expectation is read live from sync_doc_metadata.PLATFORM_FACTS, since a hand-typed one is "
            "the very drift this check exists to catch). (b) describe_alarms raising AccessDenied, and separately "
            "`import sync_doc_metadata` raising ImportError."
        ),
        "observed": (
            "(a) exit 0, status='drift' with fact='alarm_count', documented==N, live==N+1 and a fix line naming "
            "sync_doc_metadata; feeding exactly N reports 'clean' with no mismatches. A two-page paginated response "
            "plus composite alarms is separately proved to SUM (a page-1-only read would under-count and false-red "
            "forever). (b) both -> status='error' naming which read failed; neither reports clean."
        ),
        "scope": (
            "alarm_count ONLY. PLATFORM_FACTS carries a dozen literals; the live comparison here covers one of them, "
            "and the lambda_count/test_count literals moved to the generated lambdas/web/platform_counts.py in #3101 "
            "with their own derivation. So this check's green means 'the alarm literal matches live', never 'the doc "
            "literals are in sync'. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/drift_sentinel.py::check_codeql_alerts": {
        "gate_name": "check_codeql_alerts",
        "command": f"{_DS_SUITE} -k codeql -q",
        "mutation": (
            "CITED, NOT RE-PROVED — #3112 (merged 2026-08-24) is the model this family is measured against. (a) an "
            "open alert planted in the code-scanning API response. (b) the alert list unreadable (auth/scope error), "
            "and separately a non-list body."
        ),
        "observed": (
            "exit 0 across both halves, and the assertion goes further than the record: each planted state is "
            "followed through drift_report.as_signal and asserted to land in its needs-human `flagging` map — "
            "surfacing that lands nowhere is the same as not firing. The pre-#3112 code FAILED the (b) half: an "
            "unreadable list returned status='error', which as_signal drops. Live evidence, not synthetic: 3/3 "
            "persisted drift-log records carried status='error' while 7 open alerts sat 13-14 days un-triaged."
        ),
        "scope": (
            "The exception in this family: BOTH halves fail CLOSED into `drift`, so both reach triage. Budget is a "
            "hard 0 open alerts, so a fix merged since CodeQL's last analysis of main shows as drift for one push "
            "cycle by design. Requires `security-events: read` in the calling workflow's permissions block — the "
            "absence of that grant is one of the three defects that kept this dark, and it is pinned by "
            "test_remediation_workflow_grants_security_events_read."
        ),
        "proved_on": "2026-08-24",
    },
    "sentinel::deploy/drift_sentinel.py::check_hae_webhook_ingress": {
        "gate_name": "check_hae_webhook_ingress",
        "command": f"{_DS_SUITE} -k hae_webhook -q",
        "mutation": (
            "(a) three shapes on the Lambda's live resource policy: a SECOND apigateway-invoke statement (the #1946 "
            "orphan console API), a single grant widened to the bare `/*/*` wildcard, and zero invoke statements. "
            "(b) the CDK API-id derivation returning zero or multiple ApiGatewayV2::Api resources, and get_policy "
            "raising."
        ),
        "observed": (
            "exit 0 with all three (a) shapes reporting status='drift' and a detail naming the excess/widened grant; "
            "exactly one grant scoped to the derived api id + '/*/*/ingest' reports 'clean', and a non-apigateway "
            "principal is proved not to be counted. (b) both -> status='error'."
        ),
        "scope": (
            "Guard-the-SET: the expected API id is derived live from LifePlatformIngestion's own resource list, so a "
            "stack replacement does not false-positive and a third console API is not missed. Scoped to the ONE "
            "function health-auto-export-webhook — an out-of-IaC grant on any other Lambda is outside this check. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": _PROVED_ON,
    },
    # ── the five in the #1665-extracted siblings ──────────────────────────────
    "sentinel::deploy/sentinel_github.py::check_github_config": {
        "gate_name": "check_github_config",
        "command": f"{_DS_SUITE} -k github_config -q",
        "mutation": (
            "against the checked-in deploy/github_posture.json: (a) a live `production` environment with no "
            "reviewers (the #1319 dead-approval-gate class), vulnerability alerts disabled, the main ruleset "
            "weakened, the ruleset deleted outright, a required-check context dropped, the bot bypass removed, and "
            "an out-of-band review rule added. (b) the admin-read surfaces returning a 403 scope error, and the "
            "bypass-actor user lookup unavailable. (c) #3207, in tests/test_posture_pending_marker.py: the SAME "
            "absent-ruleset / auto-merge-off live shape judged against `applied: true` vs `applied: false`, plus a "
            "surface that IS applied live while still marked `applied: false`, plus the spec renamed so the "
            "classification cannot be keyed on a name."
        ),
        "observed": (
            "exit 0 with every (a) shape reporting status='drift' on the specific surface; the posture file's own "
            "declared state reports 'clean'. (b) scope gap -> status='unavailable' with a needs_owner line naming "
            "the exact fine-grained-PAT permission ('Administration:read') and the secret ('GH_POSTURE_TOKEN'); the "
            "user-lookup gap -> degraded. (c) `applied: true` + absent -> 'drift' with the --apply fix intact; "
            "`applied: false` + absent -> the distinct status 'pending', naming blocked_on and carrying NO --apply "
            "recommendation; `applied: false` + applied-live -> 'drift' on the STALE MARKER, so the suppression "
            "cannot rot into a false green; the rename does not change any verdict. Never clean, never a silent pass."
        ),
        "scope": (
            "The cannot-observe verdict is the third status `unavailable`, and it aggregates as CLEAN at sweep level "
            "by deliberate #1320 design (a fork without the PAT must not red-wall). It is honest rather than the "
            "#3156 shape — the status is distinct, print_summary emits the needs-owner line, and nothing falls back "
            "to a remembered value while claiming it measured — but it means green on this check can mean 'four "
            "surfaces asserted' or 'two asserted, two unreadable'. Read the needs_owner line, not the colour. "
            "A FIFTH status exists since #3207: `pending`, for a posture entry marked `applied: false`. It "
            "aggregates below `unavailable` and above `clean`, never reaches the needs-human triage, and is always "
            "printed with its blocker — the suppression is scoped to the ABSENCE of a surface the posture itself "
            "declares unapplied, and the opposite arm (applied live, marker still false) is drift."
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/sentinel_github.py::check_github_push_runs": {
        "gate_name": "check_github_push_runs",
        "command": f"{_DS_SUITE} -k push_runs -q",
        "mutation": (
            "(a) a trigger-matching commit on main older than the grace window with no queued push-event run — the "
            "2026-07-19 six-merge ABSENT incident, replayed. (b) the /actions/runs surface returning a 403 scope "
            "error while /commits still answers."
        ),
        "observed": (
            "exit 0 with (a) status='drift' naming the stalled head; and the false-positive suppressions hold in the "
            "same run — the historical six-merge gap, an 18-commit batch push, a commit touching only non-trigger "
            "paths, a bot reconcile commit and anything inside the grace window all report 'clean'. (b) -> "
            "status='unavailable' with a needs_owner line naming 'Actions:read'."
        ),
        "scope": (
            "Same `unavailable`-aggregates-as-clean seam as check_github_config above. Path-filter aware, so a merge "
            "touching only handovers/ legitimately triggers nothing and is not drift — which also means a genuine "
            "trigger regression on a path OUTSIDE PUSH_TRIGGER_GLOBS is invisible here."
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/sentinel_quota.py::check_github_quota": {
        "gate_name": "check_github_quota",
        "command": f"{_DS_SUITE} -k github_quota -q",
        "mutation": (
            "(a) a billing-usage payload at 2,200 of 3,000 included minutes on a PRIVATE repo (73%, over the 70% "
            "warn), and separately a paid-overage netAmount. (b) the billing endpoint returning None — the real "
            "steady state, since the ambient GITHUB_TOKEN lacks the `user` scope the billing API needs."
        ),
        "observed": (
            "exit 0 with (a) status='drift' carrying the warn string, which run_sweep is separately proved to "
            "propagate into the sweep summary; 900 minutes (30%) reports 'clean', and the SAME 73% on a PUBLIC repo "
            "is proved to suppress the warn (public minutes are free). (b) -> status='unavailable' with "
            "billing_api.available False and a detail naming the missing `user` scope, plus the independent "
            "`gh run list` wall-clock proxy still populated."
        ),
        "scope": (
            "The load-bearing caveat: without GH_BILLING_TOKEN this check's STEADY STATE is `unavailable`, so its "
            "drift half — proved able to fire here — is rarely armed live. What remains armed without the PAT is the "
            "top-workflows wall-clock proxy, which is attributive, not a threshold. An unavailable quota check does "
            "not drag the sweep, so a quota problem during a PAT outage is simply not observed."
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/sentinel_replication.py::check_raw_replication": {
        "gate_name": "check_raw_replication",
        "command": f"{_REPL_SUITE} -q",
        "mutation": (
            "eight independent shapes on fakes built to the real call shapes: no replication configuration at all, a "
            "disabled rule, DeleteMarkerReplication turned on live, a redirected destination, a widened prefix, an "
            "unversioned destination bucket, a source object reporting COMPLETED whose replica does not exist, "
            "replication FAILED, an object stuck PENDING past the grace window, and the earliest object having no "
            "replica (the un-backfilled history). (b) every sampled object predating the configuration, and the "
            "source registry failing to import."
        ),
        "observed": (
            "exit 0 with each of the (a) shapes reporting status='drift' and a detail naming the specific breakage; "
            "the correct configuration with a confirmed replica reports 'clean', and a PENDING object INSIDE the "
            "grace window is proved not to red. (b) both vacuum shapes -> status='degraded' with 'NOT verified end "
            "to end' in the detail — explicitly never clean."
        ),
        "scope": (
            "The most complete pre-existing pair in this family, and the only one whose vacuous-pass guard was "
            "designed in rather than added later. Prefixes come from source_registry's raw_layout facets, not a hand "
            "list, so a plausible-but-dead key cannot make the probe silently sample nothing. `degraded` still does "
            "not reach as_signal's needs-human path. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": _PROVED_ON,
    },
    "sentinel::deploy/sentinel_cadence.py::check_sentinel_cadence": {
        "gate_name": "check_sentinel_cadence",
        "command": f"{_DS_SUITE} -k sentinel_cadence -q",
        "mutation": (
            "CITED, NOT RE-PROVED — #3130 arrived 2026-08-24 with nine mutation proofs. (a) a drift-log listing with "
            "an expected weekly date removed (the 2026-08-17 run that died before persist() and that nothing "
            "noticed), and separately a log whose newest record is stale with no named gap. (b) the log listing "
            "unreadable, and a truly empty log."
        ),
        "observed": (
            "exit 0 across all nine: (a) both gap shapes report status='drift' naming the missing/stale date, while "
            "a fully-populated fresh cadence reports 'clean'. (b) an unreadable log fails CLOSED to `drift`, not "
            "`error` — so it reaches triage — and an empty log is drift too. Pagination of list_objects_v2 is "
            "separately proved, and the expected weekdays are proved to be derived from the workflow cron rather "
            "than hand-typed."
        ),
        "scope": (
            "One of only two checks in this family that fail CLOSED on unreadable (the other is check_codeql_alerts) "
            "— deliberate, because a dead-man that cannot read its own evidence is exactly the failure it exists to "
            "catch. Detects a MISSED run one cadence late by construction: it is the next run that notices, so a "
            "sweep that dies is surfaced within a week, not immediately."
        ),
        "proved_on": "2026-08-24",
    },
    "sentinel::deploy/sentinel_events.py::check_eventbridge_rules": {
        "gate_name": "check_eventbridge_rules",
        "command": "python3 -m pytest tests/test_sentinel_events_3279.py -q",
        "mutation": (
            "(a) three planted shapes on fakes built to the real call shapes: an ENABLED rule with zero targets (the "
            "live life-platform-monthly-export condition, #3279), a live rule absent from every stack's resource list "
            "and from KNOWN_OUT_OF_IAC_RULES, and an ALLOWLISTED rule that is enabled-targetless (the allowlist must "
            "not suppress the dangling half). (b) list_rules raising, list_stack_resources raising (the vacuum that "
            "would red every rule as an orphan), and list_targets_by_rule raising."
        ),
        "observed": (
            "exit 0 with each (a) shape reporting status='drift' naming the exact rule, reaching "
            "drift_report.as_signal's flagging map through run_sweep; the all-managed all-targeted baseline reports "
            "'clean', and the CFN ARN-shaped PhysicalResourceId (10 of 93 live managed rules) is proved to match its "
            "live bare-name twin rather than false-positive. (b) all three cannot-observe shapes -> status='error' "
            "naming the failing call; the unread-IaC shape publishes NO orphan list."
        ),
        "scope": (
            "Default event bus, REGION only (mirrors check_orphan_functions; zero AWS::Events::Rule live in the "
            "us-east-1/us-east-2 stacks, measured 2026-08-29). A DISABLED targetless rule does not drift — disabled "
            "rules fire nothing. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": "2026-08-29",
    },
    "sentinel::deploy/sentinel_log_retention.py::check_log_retention": {
        "gate_name": "check_log_retention",
        "command": "python3 -m pytest tests/test_security_log_retention_3278.py -q",
        "mutation": (
            "(a) the 2026-08-30 live sweep planted verbatim on fakes built to the DescribeRegions/DescribeLogGroups call "
            "shapes (retentionInDays ABSENT for never-expire, prefix semantics on the read): 17 security-tier groups across "
            "7 regions, 10 NEVER_EXPIRE Lambda@Edge replicas + 7 at 30d against the declared 90d; plus a single 60d group "
            "among an otherwise-clean set; plus a longer-named sibling (`-canary-v2`) that a prefix read must not count. "
            "(b) describe_regions raising (the region set cannot be enumerated), one region's describe_log_groups raising "
            "with every other region clean, and a sweep that finds zero groups anywhere."
        ),
        "observed": (
            "exit 0 with (a) reporting status='drift' naming all 17 groups with region + live value, NEVER_EXPIRE spelled "
            "out and the apply command in the detail, reaching drift_report.as_signal's flagging map through run_sweep as "
            "needs-human; the all-at-90 baseline reports 'clean' and the -v2 sibling neither drifts nor substitutes. (b) "
            "all three -> status='error' (the region-set failure names ec2:DescribeRegions and the role file; the partial "
            "sweep says 'not clean'; the empty sweep says ZERO), never 'clean'. The doc-side guard in the same file reds on "
            "a planted 90->30 doc-down edit and on a function dropped from the row."
        ),
        "scope": (
            "Detection, not prevention: a Lambda@Edge replica group created by a newly-served region arrives at "
            "NEVER_EXPIRE and is caught by the NEXT weekly sweep (<=7 days), fixed by the attended apply script — CDK "
            "owns one region per stack and CloudWatch Logs has no account-level retention default. Live steady state "
            "until the driver runs the apply + LifePlatformOperational deploy is DRIFT (17 groups), by design. " + _ERROR_IS_NOT_A_SIGNAL
        ),
        "proved_on": "2026-08-30",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# GUARD_PROOFS — census family 2 (guard-script). Same `Proof` bar as
# `gate_census.PROVEN_CAN_FAIL`; here only because `gate_census.py` sits at ~1,175 of its
# 1,200-line ceiling (#1665) and the standing rule is extraction, never a baseline raise.
# ─────────────────────────────────────────────────────────────────────────────

GUARD_PROOFS: dict[str, dict[str, Any]] = {
    "guard::deploy/iam_additive_gate.py": {
        "gate_name": "deploy/iam_additive_gate.py",
        "command": (
            "python3 -m pytest tests/test_iam_additive_gate_2834.py -q   # 164 probes, each one a mutation of a "
            "REAL `cdk synth` slice run through the module or its CLI; plus the out-of-band CLI transcript in "
            "`observed`, re-runnable as: python3 deploy/iam_additive_gate.py --synth-dir <slice> --deployed-dir <slice>"
        ),
        "mutation": (
            "Six defects, one at a time, planted into a copy of the committed synth slice "
            "(tests/fixtures/iam_additive_gate/LifePlatformEmail.slice.template.json) with the deployed side held at "
            "the clean original: (A) a new Allow carrying `iam:PassRole` on the CDK cfn-exec role; (B) the review-R1 "
            "shape — a legitimate additive `s3:GetObject config/content_filter.json` grant riding with the function's "
            "`Code.S3Bucket` repointed at `attacker-public-bucket`; (C) the review-R2 shape — `s3:DeleteObject` on "
            "`raw/*`; (D) the review-R3 shape — `ssm:PutParameter` on `/life-platform/remediation-mode`, the "
            "remediation kill-switch; (E) the dead-man — the deployed-side template removed entirely; (F) the "
            "positive control — the 2026-08-14 P1 grant alone, which must still be admitted."
        ),
        "observed": (
            "2026-08-30, watched in both directions. BASELINE (synth == deployed) exit 0, NO-IAM-CHANGE. "
            "(A) exit 1, OWNER-REQUIRED, `forbidden-action:iam:PassRole (matches iam:*)` + "
            "`out-of-namespace-resource:arn:aws:iam::<acct>:role/cdk-hnb659fds-cfn-exec-role-...`. "
            "(B) exit 1, OWNER-REQUIRED, `rides-with-non-iam-change` naming "
            "\"Code.S3Bucket 'attacker-public-bucket' is not this environment's CDK asset bucket "
            "'cdk-hnb659fds-assets-<acct>-us-west-2'\" — this shape was ALLOW-ADDITIVE before review R1. "
            "(C) exit 1, `s3-protected-prefix: … bucket_policy.json Deny 'ProtectDataFromDeployScripts' protects raw/ "
            "against s3:deleteobject*` — ALLOW-ADDITIVE before review R2. "
            "(D) exit 1, `forbidden-action:ssm:PutParameter` — ALLOW-ADDITIVE before review R3. "
            "(E) exit 2, OWNER-REQUIRED, `UNEVALUABLE (fails closed)`. "
            "REVERTED exit 0, NO-IAM-CHANGE. (F) exit 0, ALLOW-ADDITIVE. "
            "The committed suite re-runs every one of these classes: 164 passed."
        ),
        "scope": (
            "This is a verdict on the DECISION, not on the deploy. The gate decides from two JSON templates; whether "
            "CI then applies what it admitted is the ci-cd.yml Deploy job's two #2834 steps, which are census gates of "
            "their own and are UNPROVEN — proving them means watching an approval-gated production deploy fail, which "
            "is not a local mutation. Also out of scope: the `--live` fetch path (an `aws cloudformation get-template` "
            "call; the proof above uses --deployed-dir, the same evaluate_all code path with the fetch stubbed by a "
            "file), and anything the SYNTH itself gets wrong — the gate reads cdk.out, so a defect CDK does not emit "
            "into the template is invisible to it by construction."
        ),
        "proved_on": "2026-08-30",
    },
    # #3515: the "as of" freshness guard sync_site_to_s3.sh runs right after the PII
    # guard. Not a synthetic plant — the mutation IS the real historical defect: a
    # `git archive origin/main@c0122242` snapshot taken before this fix still carried
    # v4_build_evidence.py's 33-day-stale bake (v4_build_evidence.py was never in the
    # deploy path's builder list). Watching the guard fire on the real specimen is a
    # stronger proof than a synthetic one — the exact defect it exists to catch.
    "guard::scripts/check_proof_freshness.py": {
        "gate_name": "scripts/check_proof_freshness.py",
        "command": "python3 scripts/check_proof_freshness.py --root <tree>   # tests/test_check_proof_freshness_3515.py covers it as pure logic",
        "mutation": (
            "a full snapshot of origin/main@c0122242 (git archive, before #3515's fix): "
            "site/data/index.html and site/protocols/index.html both still carry the baked "
            "'as of 2026-08-02' stamp because v4_build_evidence.py was never in "
            "deploy/sync_site_to_s3.sh's builder list."
        ),
        "observed": (
            "MUTATED (--root pointed at the origin/main@c0122242 snapshot): exit 1 — "
            "\"2 stale baked 'as of' stamp(s): site/data/index.html: 'as of 2026-08-02' is "
            "34d old (> 7d) — rebuild before publish; site/protocols/index.html: 'as of "
            "2026-08-02' is 34d old (> 7d) — rebuild before publish\". REVERTED (this "
            'branch, the fix applied): exit 0 — "all baked proof pages carry a fresh '
            "'as of' stamp\". Both watched 2026-09-06. Positive control also carried in "
            "tests/test_check_proof_freshness_3515.py "
            "(test_positive_control_stale_stamp_fails, "
            "test_main_exits_nonzero_on_stale_and_zero_when_clean, 7 cases total)."
        ),
        "scope": (
            "Watches only the six named proof pages' baked 'as of <date>' stamps against a "
            "fixed 7-day ceiling — a staleness class with no 'as of' literal at all (a wrong "
            "number stamped with a fresh date) is invisible to it by construction; that class "
            "is the doc-sync literal gate's job (sync_doc_metadata.py), not this one's."
        ),
        "proved_on": "2026-09-06",
    },
    # #3518: the plan-figure grounding class. Family 2 by NAME (`*_gate.py`) and by the
    # bool-verdict API the classifier saw (`plan_figure_findings` returns the findings the
    # caller HOLDS on). Not a synthetic plant — the mutation IS the live R4 specimen the
    # class exists to catch, and the widened-plan control is what turns the verdict OFF.
    "guard::lambdas/ai/plan_facts_gate.py": {
        "gate_name": "lambdas/ai/plan_facts_gate.py",
        "command": (
            "python3 -m pytest tests/test_plan_facts_gate_3518.py tests/test_grounding_corpus_3614.py -q   # 42 + 24 tests; "
            "the specimen row is tests/grounding_corpus/2026-09-04-physical-8000-steps-shelf-protocol.json"
        ),
        "mutation": (
            "The live 2026-09-04 physical position_summary, verbatim — 'Garmin step data isn't syncing to my dashboard "
            "yet, which blocks meaningful tracking of his 8,000+ steps/day protocol' — graded against the plan block "
            "derived from config/user_goals.json (daily_steps_range [6000, 7000]); then the same sentence pushed through "
            "the REAL coach_state_updater._gate_derived_prose with the regen returning the same condensation; then the "
            "control: the identical specimen against a plan whose range is widened to [6000, 9000]."
        ),
        "observed": (
            "RED: plan_figure_findings returns one `plan_figure_contradiction` (quantity steps, claimed 8000.0, plan "
            "[6000.0, 7000.0]); through _gate_derived_prose the derived set is HELD (derived_prose_held True, "
            "public_summary None) after the one regen fails to remove it. GREEN: the '6,000-step floor' control and the "
            "narrative's own 6,000-7,000 range return []; the widened plan returns [] for the specimen "
            "(test_a_specimen_that_stops_failing_is_visible), so the verdict is the plan's, not the sentence's. "
            "Both files pass on the merged tree: 42 passed + 24 passed."
        ),
        "scope": (
            "FRAMING-SCOPED: only a figure with plan framing (protocol/floor/target/goal/minimum/prescribed/...) in its "
            "own clause is graded, bound to the NEAREST number, so an observation ('walked 4,312 steps') is never a "
            "finding here — the numbers class owns it. The derived-prose seam grades steps and calories ONLY "
            "(DERIVED_PROSE_QUANTITIES): protein/fiber have a second configured source (the profile target the "
            "AUTHORITATIVE FACTS block hands every coach) that seam does not hold; a caller passing `observed` grades "
            "all four. DISARMED (returns [], one WARNING per container) when the plan cannot load from the repo file "
            "or S3 — never a guess. Armed on one surface (coach_state_updater), not registered as a GATE_CLASSES "
            "member in tests/grounding_wiring.py, so the other 31 surfaces are not covered by this verdict."
        ),
        "proved_on": "2026-09-06",
    },
    # #3570: same idiom as check_proof_freshness.py directly above — the mutation is
    # the REAL pre-fix registry (origin/main, before this PR's source_registry.py
    # additions), not a synthetic plant, watched against the actual live bucket.
    "guard::scripts/check_raw_zone_drift.py": {
        "gate_name": "scripts/check_raw_zone_drift.py",
        "command": "python3 scripts/check_raw_zone_drift.py   # live read-only S3 check; tests/test_raw_zone_drift_3570.py covers the pure logic (check_coverage/expand_prefix/prefix_root/known_prefix_roots) offline",
        "mutation": (
            "origin/main@4ba5c490d's lambdas/ingestion/source_registry.py (before this PR's "
            "additions), loaded via `git show` in place of the current module — no apple_health "
            "gz-export unmodeled_legacy, no NON_INGESTION_RAW_PREFIXES entries (labs/inbound_email/"
            "matthew-matthew), and none of the 9 X-9 no-user-segment predecessor generations "
            "(withings/strava/eightsleep/garmin/macrofactor/cgm_readings/state_of_mind/workouts/"
            "health_auto_export) this PR's #3570 fix documents."
        ),
        "observed": (
            "MUTATED (known_prefix_roots() built from the origin/main module, checked against the "
            "SAME live top-level prefix lists this script reads from S3): 14 uncovered — "
            "raw/apple_health, raw/cgm_readings, raw/eightsleep, raw/garmin, raw/health_auto_export, "
            "raw/inbound_email, raw/macrofactor, raw/state_of_mind, raw/strava, raw/workouts, "
            "raw/matthew/apple_health, raw/matthew/inbound_email, raw/matthew/labs, "
            "raw/matthew/matthew — exactly the #3570 finding's own live count (9,634-object "
            "raw/matthew/matthew/** plus the apple_health/labs/inbound_email gaps plus the 9 "
            "previously-undocumented X-9 legacy prefixes the drift check itself surfaced). "
            "REVERTED (this branch, `python3 scripts/check_raw_zone_drift.py`, live, read-only, "
            'against s3://matthew-life-platform): exit 0 — "CLEAN — 16 raw/ prefixes + 17 '
            'raw/matthew/ prefixes all covered." Both watched 2026-09-06.'
        ),
        "scope": (
            "A LIST-only read (ListObjectsV2, Delimiter='/', one level under raw/ and raw/matthew/) "
            "against facets a human still writes — it proves the registry and the bucket agree at "
            "the top level, not that a `raw_layout`'s deeper claim (scheme/filename) matches every "
            "object inside a covered prefix (DIL-028's job, tests/test_dil028_raw_layout_replay.py). "
            "Not wired into CI or the reset pipeline (see the script's own docstring) — an operator "
            "runs it periodically; a new undocumented prefix is caught at the NEXT run, not on write."
        ),
        "proved_on": "2026-09-06",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# STRUCTURAL_HAND_PROOFS — census family 5 (structural-test) records that don't fit
# `gate_census_mutations.MUTATION_SPECS`' auto-rerunnable harness (which requires a
# brand-new, never-tracked plant file — #2999's `_dirty()` precondition): this gate's
# real assertions read a COMMITTED build artifact (site/sitemap.xml, site/subscribe.html)
# and the LIVE page registry, not "does any new file in the tree carry a defect". Same
# hand-performed-and-watched bar as gate_census.py's own structural PROVEN_CAN_FAIL
# records (e.g. test_fixture_frame_pairing_3222.py) — extracted here only because
# gate_census.py sits at its 1,200-line ceiling (#1665).
# ─────────────────────────────────────────────────────────────────────────────

STRUCTURAL_HAND_PROOFS: dict[str, dict[str, Any]] = {
    # #3548: the a11y ledger's own guard — five source-level checks (the archi-
    # tecture SVG's <title>, cap-h/hb-group heading levels, /subscribe/confirm/'s
    # h1, the 18 tabs.js dx-read hosts, the cycle-comparison table's corner <th>)
    # plus a set-derivation floor. The must-fail proof is the ONE case that has a
    # real historical specimen to revert to: the retired <article data-dx-read>
    # tabpanel host, whose reintroduction is exactly the aria-allowed-role
    # regression the issue reported.
    "structural::test_a11y_ledger_3548.py": {
        "gate_name": "test_a11y_ledger_3548.py",
        "command": "python3 -m pytest tests/test_a11y_ledger_3548.py -q",
        "mutation": (
            'site/coaching/read/index.html\'s `<div class="dx-read" data-dx-read>` '
            'reverted in place to the pre-#3548 `<article class="dx-read" '
            'data-dx-read>` — the exact tag tabs.js::markActiveTab\'s role="tabpanel" '
            "override is illegal on (aria-allowed-role), and the shape all 18 "
            "dx-read hosts carried before this PR."
        ),
        "observed": (
            "MUTATED: 1 of 11 FAILED — test_no_dx_read_panel_is_an_article: "
            '"found <article data-dx-read> (should be <div>): '
            '[.../site/coaching/read/index.html]". REVERTED: 11 passed. '
            "Both watched 2026-09-07."
        ),
        "scope": (
            "Proves the os.walk sweep (test_no_dx_read_panel_is_an_article) and, by "
            "the same population, test_dx_read_div_count_matches_the_known_seventeen_"
            "plus_home's floor. The other four checks in this file (svg <title>, "
            "cap-h/hb-group heading level, /subscribe/confirm/'s h1, the empty "
            "corner <th>) are each pinned by their own negative-control test in the "
            "same file (see the test docstrings) but do not have a real pre-fix "
            "tree snapshot to revert to the way the dx-read/article shape does — "
            "this record proves the file CAN fail, not that every one of its five "
            "checks has been watched against history."
        ),
        "proved_on": "2026-09-07",
    },
    "structural::test_v4_build_sitemap_3567.py": {
        "gate_name": "test_v4_build_sitemap_3567.py",
        "command": "python3 -m pytest tests/test_v4_build_sitemap_3567.py -q -p no:cacheprovider",
        "mutation": (
            "the gate's own test file, copied into a `git archive origin/main@c0122242` "
            "snapshot (before #3567's fix) and run there against the OLD "
            "scripts/v4_build_sitemap.py + the OLD site/sitemap.xml + site/subscribe.html — "
            "the real pre-fix specimens, not a synthetic plant."
        ),
        "observed": (
            "MUTATED (origin/main@c0122242 snapshot): 5 of 6 FAILED. Two AttributeErrors "
            "(`module 'v4_build_sitemap' has no attribute 'registry_urls'` / "
            "`'file_for_path'` — the old module lacks the registry-derivation functions "
            "entirely) and, functionally, "
            "test_real_repo_sitemap_has_no_dead_fragment_or_duplicate_subscribe_url FAILED "
            "with 'the dead extensionless fragment URL is back' "
            "(https://averagejoematt.com/journal/essays/org-chart-of-one/body present in "
            "the OLD sitemap.xml), and "
            "test_real_repo_subscribe_html_stub_is_noindex_with_a_matching_canonical FAILED "
            "on the OLD subscribe.html (no noindex). REVERTED (this branch, the fix "
            "applied): 6 passed. Both watched 2026-09-06."
        ),
        "scope": (
            "Three of its six cases (the tmp_path-fixtured registry-derivation tests) are "
            "pure-logic and were unaffected by the tree snapshot either way; only the three "
            "real-repo cases are what this mutation proves. `test_every_indexable_registry_"
            "page_has_a_self_matching_canonical` reads the LIVE `qa_manifest.MANIFEST`, so it "
            "proves canonical presence/agreement only for pages the registry already knows "
            "about — a wholly new, unregistered page is outside its reach by the same "
            "registry-scoping #3567 itself argues for."
        ),
        "proved_on": "2026-09-06",
    },
}

# ── #3529/#3534: the reset sweep's two declared-exemption registries ──────────────────
# Both entered the inventory 2026-09-05 with the one derivation that closed #3529/#3531/#3534,
# and both arrive with a verdict rather than joining the unproven pile: each is a DECLARED
# EXCEPTION to a rule, and an exception nobody has watched failing is indistinguishable from
# a rule that was never enforced.
GUARD_PROOFS.update(
    {
        "registry::deploy/restart_verify_gates.py::MULTILINE_RUN_EXEMPT::Install census dependency (PyYAML)": {
            "gate_name": "MULTILINE_RUN_EXEMPT[Install census dependency (PyYAML)]",
            "command": (
                "cp .github/workflows/docs-ci.yml /tmp/nc/docs-ci.yml; "
                "printf '      - name: A thirteenth gate hiding in a block scalar\\n        if: always()\\n"
                "        run: |\\n          python3 scripts/check_doc_links.py\\n' >> /tmp/nc/docs-ci.yml; "
                "python3 -c \"import sys,pathlib; sys.path.insert(0,'deploy'); import restart_verify_gates as r; "
                "r.WORKFLOW=pathlib.Path('/tmp/nc/docs-ci.yml'); sys.argv=['x','--skip-js','--skip-pytest']; "
                "print('EXIT', r.main())\""
            ),
            "mutation": (
                "appended a REAL gate (`python3 scripts/check_doc_links.py`) to a scratch copy of the live "
                "docs-ci.yml in `run: |` block-scalar form — the one shape the sweep's line parser cannot see, "
                "and therefore the one shape that would be derived silently as nothing."
            ),
            "observed": (
                "ARMED: exit 2, `UNEVALUABLE (not a pass): docs-ci.yml has \\`run: |\\` step(s) invoking python3 "
                "that this sweep cannot derive: · A thirteenth gate hiding in a block scalar`. Unmutated control "
                "on the same scratch copy: exit 0, the exempted PyYAML bootstrap NOT reported. Both directions "
                "watched 2026-09-05."
            ),
            "scope": (
                "Detection is textual: a python3 invocation reached indirectly (a shell variable, a `bash -c`, a "
                "composite action) is not seen. The exemption itself is name-keyed, so a step RENAME would strand "
                "it — `test_multiline_exemptions_still_name_live_workflow_steps` is the guard for that, and it is "
                "a static assertion, not a mutation proof."
            ),
            "proved_on": "2026-09-05",
        },
        "registry::deploy/restart_verify_gates.py::MUTATING_GATES::scripts/skill_lint.py --self-test": {
            "gate_name": "MUTATING_GATES[scripts/skill_lint.py --self-test]",
            "command": (
                "python3 -m pytest tests/test_restart_verify_gates_3477.py -q -k "
                "'read_only_by_effect or CAUGHT_by_effect or DOES_NOT_RESTORE'"
            ),
            "mutation": (
                "two, because the entry has two failure directions. (A) a fixture gate OUTSIDE the exemption that "
                "creates a file inside the repo — the read-only-by-EFFECT measurement must catch it. (B) a fixture "
                "gate INSIDE the exemption that writes and never restores — the exemption's own restoration "
                "assertion must catch that. (B) is the direction that matters: `skill_lint.py --self-test` restores "
                "its victim on a good day, so without (B) the entry would be a declaration with no teeth."
            ),
            "observed": (
                "ARMED (A): exit 1, `READ-ONLY VIOLATION` + `MUTATED the working tree`. ARMED (B): exit 1, "
                "`DID NOT RESTORE THE TREE`. CONTROL: the same sweep over a no-op fixture gate exits 0 with "
                "`git status --porcelain` byte-identical before and after. Live full sweep 2026-09-05 ran the real "
                "`scripts/skill_lint.py --self-test` LAST and reported no restoration failure."
            ),
            "scope": (
                "The measurement is `git status --porcelain` on the repo root, so a gate that writes OUTSIDE the "
                "repo, or writes and restores within one gate's own runtime, is invisible to it. It also does not "
                "cover the pytest or JS legs — only the derived docs-ci gates are measured, because those are the "
                "ones contracted to be `--check` forms."
            ),
            "proved_on": "2026-09-05",
        },
    }
)

# ─────────────────────────────────────────────────────────────────────────────
# QA_PROOFS — census family 3 (qa-smoke-check). Same `Proof` bar; here, like
# GUARD_PROOFS above, only because `gate_census.py` sits at its 1,200-line ceiling
# (#1665) and the standing rule is extraction, never a baseline raise.
# ─────────────────────────────────────────────────────────────────────────────

QA_PROOFS: dict[str, dict[str, Any]] = {
    "qa::lambdas/operational/qa_check_subscriber_promise.py::check_subscriber_promise_cadence": {
        "gate_name": "check_subscriber_promise_cadence",
        "command": (
            'cd lambdas && python3 -c "from operational import qa_check_subscriber_promise as q; '
            'print(q.check_subscriber_promise_cadence())"'
        ),
        "mutation": (
            "none needed — the defect was live. The check fetches the real /subscribe/ and compares "
            "it against the promise rendered from the senders' own crons "
            "(common/subscriber_cadence.promise_sentence). Production still serves the #3564 copy, so "
            "the first run of this gate was a real FAIL on a real defect rather than a synthetic one "
            "(the 'fail-closed paths need a live proof' bar)."
        ),
        "observed": (
            "ARMED 2026-09-05: passed=False, message 'the page states [one] emails a week instead' — it "
            "named the stale count AND the expected sentence. Positive control (a page carrying the "
            "derived sentence) returns ok, and a page carrying BOTH the new sentence and a leftover "
            "'One email a week' fails as a contradiction: tests/test_subscriber_cadence_promise_3564.py, "
            "3 assessor cases."
        ),
        "scope": (
            "Fail-soft on fetch errors by design (a transient blip must not red the nightly), so its green "
            "is only load-bearing while /subscribe/ is reachable. It reads the PAGE, not the senders' live "
            "schedules — the mirror-vs-CDK half is the pytest gate."
        ),
        "proved_on": "2026-09-05",
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# REGISTRY_PROOFS — census family "registry" (#3544). The eight entries of
# `tests/test_token_contrast.py::RECEDE_TEXT_RULES`: one per CSS rule in the site's
# "recede" state grammar, each measured as ink-token-over-background composited at the
# opacity PARSED from the live sheet, in all three palette blocks.
#
# The bar is `gate_census.PROVEN_CAN_FAIL`'s bar and it is met PER ENTRY, not once for
# the set: `test_recede_guard_reds_when_the_shipped_opacity_comes_back` is parametrised
# over all eight, and each parameter restores THAT rule's own pre-#3544 opacity into a
# copy of the live sheet and requires the evaluator to name that selector under-AA. A
# ninth entry added with no control row reds `test_every_measured_rule_has_a_negative_
# control`, so the set cannot grow unproven — which is the failure mode #3544 itself was
# (five dim-the-card rules accumulated to ~230 axe nodes with no composite guard at all).
# ─────────────────────────────────────────────────────────────────────────────

_RECEDE_COMMAND = (
    "python3 -m pytest tests/test_token_contrast.py -q   "
    "# 21 tests; the 8 parametrised cases of "
    "test_recede_guard_reds_when_the_shipped_opacity_comes_back are the per-entry controls"
)
_RECEDE_SCOPE = (
    "A verdict on the ARITHMETIC and on the CSS parse, offline — not on the rendered page. It composites "
    "each rule's ink tokens over --page and --surface at the opacity parsed from the sheet; it does not know "
    "which background a given instance actually lands on, does not see a wash/image ground (the .ch-state "
    "class, guarded separately by test_ch_state_grounds_on_a_ramp_step_not_an_accent_wash), and does not see "
    "inline styles or JS-set colours. The live arbiter stays tests/visual_qa.py's axe sweep. Also scoped: the "
    "companion set-completeness check test_every_opacity_declaration_is_classified sweeps evidence.css ONLY — "
    "tokens.css's ~40 further opacity declarations are deliberately unclassified rather than asserted "
    "text-free on inspection this change did not do."
)


def _recede_proof(selector: str, alpha: float, observed: str) -> dict:
    return {
        "gate_name": f"RECEDE_TEXT_RULES[{selector}]",
        "command": _RECEDE_COMMAND,
        "mutation": (
            f"Restored `{selector}`'s own pre-#3544 declaration — `opacity: {alpha}` — into a copy of the live "
            "sheet, leaving the other seven rules fixed, and re-ran the same _recede_failures() evaluator the "
            "shipping test calls."
        ),
        "observed": observed,
        "scope": _RECEDE_SCOPE,
        "proved_on": "2026-09-05",
    }


_RECEDE_OBSERVED = {
    # selector: (alpha, n failures produced, worst ratio per palette block)
    ".ch-rung.is-locked": (0.55, 16, "dark 2.56:1 / @media-light 2.16:1 / data-theme-light 2.16:1"),
    ".ch-fx": (0.75, 11, "dark 3.70:1 / @media-light 3.03:1 / data-theme-light 3.03:1"),
    ".ch-fx.is-inert": (0.55, 16, "dark 2.56:1 / @media-light 2.16:1 / data-theme-light 2.16:1"),
    ".ch-badge": (0.55, 10, "dark 2.56:1 / @media-light 2.16:1 / data-theme-light 2.16:1"),
    ".ch-tl li.ch-tl-muted": (0.75, 11, "dark 3.70:1 / @media-light 3.03:1 / data-theme-light 3.03:1"),
    ".ev-intro__note": (0.8, 4, "@media-light 3.35:1 / data-theme-light 3.35:1 — dark held 5.13:1 and did NOT fail"),
    ".rdg-abandoned .rdg-face": (0.72, 6, "dark 3.52:1 / @media-light 2.87:1 / data-theme-light 2.87:1"),
    ".vg-off": (0.55, 12, "dark 2.56:1 / @media-light 2.16:1 / data-theme-light 2.16:1"),
}

REGISTRY_PROOFS: dict[str, dict[str, Any]] = {
    f"registry::tests/test_token_contrast.py::RECEDE_TEXT_RULES::{selector}": _recede_proof(
        selector,
        alpha,
        (
            f"2026-09-05, watched in both directions. CLEAN sheets: 0 failures, pytest exit 0 (21 passed). "
            f"MUTATED: {n} AA failures naming `{selector} @ opacity {alpha}` — worst per block {worst}. "
            "REVERTED: 0 failures, exit 0. The whole-file control run "
            "(`.ch-rung.is-locked` restored in the real working tree, not a copy) was watched separately "
            "at exit 1 with the same numbers, and `.ev-intro__note`'s light-only scope is asserted "
            "explicitly by the control rather than assumed."
        ),
    )
    for selector, (alpha, n, worst) in _RECEDE_OBSERVED.items()
}


# ── #3520: deploy/ joins the cast guard's scan set, with four declared exceptions ──────
#
# `tests/test_cast_roster_consistency.PROMPT_LITERAL_DIRS` grew `deploy/` because
# `deploy/seed_genesis_preregistration.py` hand-typed a coach roster naming a coach
# retired at the cycle-13 genesis, and that roster is the input to the content-hash
# SEALED pre-registration — the one reader-bound artifact that can never be corrected.
# Widening the set brought four files with legitimate real-expert mentions into scope,
# each of which gets an allowlist ENTRY, and each entry is a census gate of its own.
#
# An exception nobody has watched failing is indistinguishable from a rule that was never
# enforced, so each entry is proved in BOTH directions:
#   (a) LOAD-BEARING — delete the entry and the guard reds, naming that file. If it did
#       not, the entry would be decoration over a file that never had a finding.
#   (b) NOT A BLANKET EXEMPTION — plant an off-cast name the entry does NOT cover into
#       the same file and the guard still reds. This is the direction that matters: a
#       per-file allowlist that swallowed everything in its file would have re-opened
#       exactly the hole #2384 closed.
_CAST_ALLOWLIST_SUITE = (
    "python3 -m pytest tests/test_cast_roster_consistency.py -q -p no:cacheprovider -k prompt_literals_name_only_the_live_cast"
)

_CAST_ALLOWLIST_ENTRANTS = {
    "deploy/restart_leadin_repair.py": (
        "the privacy repair table's DEFECT strings — the pre-launch chronicle passage naming the three "
        "real experts the fictional board was modelled on, which the script cannot find in order to "
        "remove without quoting, plus the same three names in its `privacy absolutes` deny vocabulary",
        '`PLANT_3520 = "Dr. Nakamura is enthusiastic and occasionally tangential."` — the retired short '
        "form this very file used to emit as its REPLACEMENT text before #3520",
    ),
    "deploy/archive/onetime/add_experiments.py": (
        'literature citations in a frozen one-time script ("Šrámek et al., 2000; Huberman Lab")',
        '`PLANT_3520 = "Coach Maya Rodriguez reviews the stack."`',
    ),
    "deploy/archive/onetime/patch_deficit_ceiling.py": (
        "a frozen one-time script's section labels citing the real experts a threshold was sourced from",
        '`PLANT_3520 = "Dr. Kai Nakamura signs off on the ceiling."`',
    ),
    "deploy/archive/onetime/prepend_changelog.py": (
        "a changelog entry listing the seven PODCASTS on config/podcast_watchlist.json",
        '`PLANT_3520 = "Dr. Kai Nakamura writes the changelog."`',
    ),
}

REGISTRY_PROOFS.update(
    {
        f"registry::tests/test_cast_roster_consistency.py::PROMPT_LITERAL_ALLOWLIST::{path}": {
            "gate_name": f"PROMPT_LITERAL_ALLOWLIST[{path}]",
            "command": _CAST_ALLOWLIST_SUITE,
            "mutation": (
                f"(a) the entry's own line deleted from PROMPT_LITERAL_ALLOWLIST, leaving {what} unexcused. "
                f"(b) the entry left in place and {plant} appended to the real file — an off-cast name the "
                "entry does not cover."
            ),
            "observed": (
                f"ARMED (a): exit 1, `FAILED ...::test_prompt_literals_name_only_the_live_cast[{path}]`, "
                "1 failed / 232 passed. ARMED (b): exit 1, the SAME test id fails on the planted name while "
                "the allowlisted ones stay excused. REVERTED after each: the full file passes, 254 passed, "
                "exit 0. All six runs watched 2026-09-06 on this branch."
            ),
            "scope": (
                "Detection is AST string literals with docstrings excluded, so a name assembled at runtime "
                "(an f-string join, a name read from config) is invisible to it — the same reach the "
                "#2384 half of this guard has always had. The entry is keyed by PATH, so a file RENAME "
                "strands it; `test_prompt_allowlist_entries_are_real_and_in_use` is the guard for that, "
                "and it is a static assertion rather than a mutation proof."
            ),
            "proved_on": "2026-09-06",
        }
        for path, (what, plant) in _CAST_ALLOWLIST_ENTRANTS.items()
    }
)


# ── #3645: tests/test_no_tool_attribution_3005.py::ALLOWLIST, eight entrants ───────────
#
# #3645 widened the #3005 guard's sweep-1 mention patterns to catch a paraphrase that had
# been slipping past it (spelled out in that test file's own header, not repeated here —
# repeating it in THIS file would make gate_census_proofs.py itself the next offender).
# Every tracked file that legitimately STATES the ban rather than instructing it became a
# new offender the moment the wider pattern landed, because sweep 1 is whole-FILE: a file
# not on `ALLOWLIST` is scanned in full, with no per-line/per-entry narrowing.
#
# ONE direction is provable here, not two: `ALLOWLIST` exempts an entire file by path, so
# there is no "(b) not a blanket exemption" arm the way `PROMPT_LITERAL_ALLOWLIST` above
# has (that registry matches by NAME within a shared file; this one matches by FILE, so an
# allowlisted file has no narrower boundary within it to test). The one direction that
# matters is LOAD-BEARING: delete the entry and the guard reds, naming exactly that file —
# proving the entry excuses a REAL hit, not decoration over a file with nothing to find.
_ATTRIBUTION_ALLOWLIST_SUITE = "python3 -m pytest tests/test_no_tool_attribution_3005.py::test_no_tracked_file_instructs_the_trailer -q"

# path -> what real content on that path the entry excuses. Descriptions are deliberately
# indirect (no literal quoting of the banned vocabulary) so this file does not become the
# next offender the sweep it documents would catch.
_ATTRIBUTION_ALLOWLIST_ENTRANTS = {
    ".claude/README.md": "its one-line summary of the owner's 2026-08-12 authorship-ban decision",
    ".claude/agents/worktree-implementer.md": (
        "step 9's post-#3645 wording, which spells out each of the three banned forms by name so a "
        "lane recognizes exactly what to refuse — the PR #3639 incident this issue fixes"
    ),
    "CONTRIBUTING.md": "its own commit-step line restating the same owner decision",
    "docs/CONVENTIONS.md": "the §9 registry row citing #3005's guard and naming what it bans",
    "handovers/HANDOVER_LATEST.md": "a session's own incident narrative reporting that a lane emitted the banned form",
    "remediation/prompt.md": "the remediation agent's own prompt restating the owner authorship decision",
    "scripts/gate_census_mutations.py": "a mutation-spec `detects=` string describing this very guard's own coverage",
    "tests/test_worktree_implementer_no_footer_instruction_3645.py": (
        "this PR's own regression test, which spells out all three forms in docstrings/fixtures to prove " "the widened sweep catches them"
    ),
}

REGISTRY_PROOFS.update(
    {
        f"registry::tests/test_no_tool_attribution_3005.py::ALLOWLIST::{path}": {
            "gate_name": f"ALLOWLIST[{path}]",
            "command": _ATTRIBUTION_ALLOWLIST_SUITE,
            "mutation": f"the entry's own line deleted from ALLOWLIST, leaving {what} unexcused.",
            "observed": (
                f"ARMED: exit 1, `FAILED ...::test_no_tracked_file_instructs_the_trailer`, naming `{path}` and the exact "
                "form(s) matched (1 failed / N passed). REVERTED: exit 0 (the full sweep passes again). Watched "
                "2026-09-06 on this branch for all eight entries — see PR #3658/#3645."
            ),
            "scope": (
                "Load-bearing only (no 'not a blanket exemption' arm — see the block header above): proves the entry "
                "excuses a real hit, not that the allowlist is narrow within the file. Keyed by PATH; a file rename "
                "strands the entry silently until the next full-tree run re-derives the census."
            ),
            "proved_on": "2026-09-06",
        }
        for path, what in _ATTRIBUTION_ALLOWLIST_ENTRANTS.items()
    }
)


# ── #3544 (second pass): the nine entries of DERIVED_OPACITY_EXEMPT ────────────────────
#
# The first #3544 pass measured a hand-written list of six selectors. A hand list holds
# only the members someone thought of, and this one missed `.ndots-more` — the "+N"
# overflow badge on a sample-size dot row, which charts.js::nDots emits ONLY when
# n > cap (12). When the correlations crossed 12 overlapping days it appeared, composited
# its INHERITED --ember at 4.47:1 dark / 3.51:1 light, and rolled the site back three
# times (site-deploy 34056404335, 34057051481, 34066269969), CONFIRMED each time by the
# #2978 re-probe.
#
# So the second pass DERIVES the set: every `opacity: <1` rule in every shipped
# stylesheet, text-bearing decided from the CSS itself, colour resolved through
# inheritance. Nine of those rules are genuinely exempt from WCAG 1.4.3 (text-free marks,
# aria-hidden decoration, one disabled control) and each gets a row in
# `tests/test_token_contrast.py::DERIVED_OPACITY_EXEMPT` — and each row is a census gate.
#
# An exemption nobody has watched failing is indistinguishable from a rule that was never
# enforced (the #3520 lesson, one file up), so every entry is proved in BOTH directions:
#   (a) LOAD-BEARING — delete the row and the MEASURED half reds, naming that selector in
#       all three palette blocks. If it did not, the row would be decoration over a rule
#       that was never below AA in the first place.
#   (b) NOT A BLANKET PASS — the row is keyed to a rule that must still EXIST with an
#       opacity. Strip the opacity out of the CSS and
#       `test_derived_scan_is_live_and_its_exemptions_are_not_stale` reds by name, so a
#       renamed or retired rule cannot leave a live-looking excuse behind.
# ─────────────────────────────────────────────────────────────────────────────

_DERIVED_DECOR_COMMAND = (
    "python3 -m pytest tests/test_token_contrast.py -q   "
    "# 38 tests; the 9 parametrised cases of test_every_derived_exemption_is_load_bearing "
    "are the per-entry (a) controls, and test_derived_scan_is_live_and_its_exemptions_are_not_stale is (b)"
)
_DERIVED_DECOR_SCOPE = (
    "A verdict on the ARITHMETIC and on the CSS parse, offline — not on the rendered page. Each rule's "
    "ink is composited over --page and --surface at the opacity parsed from the sheet, in all three palette "
    "blocks; the guard does not know which background a given instance actually lands on and does not see a "
    "wash ground (that is test_ch_state_grounds_on_a_ramp_step_not_an_accent_wash and "
    "test_flagged_row_names_the_ndots_parent_not_three_of_its_four_states), inline styles, or JS-set colours. "
    "The 'is this text?' decision is the CSS's own statement — a declared text property, or a descendant rule "
    "that declares one — so a wrapper that styles nothing and whose text lives in a sibling is outside its "
    "reach. Whether the exempt selector really carries no text node is a HUMAN judgement recorded as the row's "
    "written reason (aria-hidden in the emitting JS/HTML, an SVG-only child, a :disabled control); the guard "
    "proves the row is load-bearing and still points at a live rule, not that the reason is true. The live "
    "arbiter stays tests/visual_qa.py's axe sweep."
)

# selector: (alpha, n failures when un-exempted, worst ratio per palette block)
_DERIVED_DECOR_OBSERVED = {
    ".wall-cell": (0.9, 6, "dark 1.05:1 / @media-light 1.06:1 / data-theme-light 1.06:1"),
    ".imark-rail": (0.35, 6, "dark 1.70:1 / @media-light 1.60:1 / data-theme-light 1.60:1"),
    ".wf-arrow": (0.55, 6, "dark 2.69:1 / @media-light 2.28:1 / data-theme-light 2.28:1"),
    ".wf-sep": (0.7, 6, "dark 3.45:1 / @media-light 2.77:1 / data-theme-light 2.77:1"),
    ".loop-ribbon .lr-arrow": (0.55, 6, "dark 2.69:1 / @media-light 2.28:1 / data-theme-light 2.28:1"),
    ".loop-ribbon .lr-sep": (0.7, 6, "dark 3.45:1 / @media-light 2.77:1 / data-theme-light 2.77:1"),
    ".portrait .pt-hatch": (0.75, 6, "dark 4.02:1 / @media-light 3.22:1 / data-theme-light 3.22:1"),
    ".art-band": (0.6, 6, "dark 2.83:1 / @media-light 2.35:1 / data-theme-light 2.35:1"),
    ".predict-btn:disabled": (0.5, 12, "dark 1.03:1 / @media-light 1.05:1 / data-theme-light 1.05:1"),
}

REGISTRY_PROOFS.update(
    {
        f"registry::tests/test_token_contrast.py::DERIVED_OPACITY_EXEMPT::{selector}": {
            "gate_name": f"DERIVED_OPACITY_EXEMPT[{selector}]",
            "command": _DERIVED_DECOR_COMMAND,
            "mutation": (
                f"(a) the entry's own row deleted from DERIVED_OPACITY_EXEMPT, leaving `{selector}` "
                f"(opacity {alpha}) measured. (b) the row left in place and `opacity: {alpha}` stripped out of "
                "the rule in the real stylesheet, so the exemption points at a rule that no longer recedes."
            ),
            "observed": (
                f"2026-09-06, watched in both directions. CLEAN: 0 derived failures, 38 passed, exit 0. "
                f"ARMED (a): {n} AA failures naming `{selector} @ opacity {alpha}` — worst per block {worst} — "
                f"and test_derived_text_opacity_rules_composite_to_aa reds. ARMED (b): "
                "test_derived_scan_is_live_and_its_exemptions_are_not_stale reds naming the selector. "
                "The whole-file real-tree control was watched separately for `.wf-arrow` (direction a: 6 failed / "
                "31 passed, exit 1) and `.wf-sep` (direction b: 2 failed / 36 passed, exit 1) — mutating the "
                "actual working tree, not a copy — and both REVERTED to 38 passed, exit 0."
            ),
            "scope": _DERIVED_DECOR_SCOPE,
            "proved_on": "2026-09-06",
        }
        for selector, (alpha, n, worst) in _DERIVED_DECOR_OBSERVED.items()
    }
)
