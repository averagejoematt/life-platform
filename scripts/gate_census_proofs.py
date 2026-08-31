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
}
