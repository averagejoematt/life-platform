# Handover — 2026-07-04 Now-milestone Sonnet Paydown

## State of play

**main HEAD:** `22153698` (docs: wrap session)  
**Layer:** v95 (bedrock_client INVOCATION_CONTEXT + Context-tagged spend metrics)  
**Fleet:** all consumers on v95, postflight green, CI green  
**Now-milestone:** 0 open stories — fully closed

## What shipped this session (7 PRs)

| PR | Stories closed | What |
|---|---|---|
| #444 | #373 #375 #376 #377 | Follow link in nav + ask-the-board tab + wedge-B GitHub link + doc-truth fixes |
| #445 | #367 #372 | Cost-governor heartbeat CW alarm + scorecard "no decided predictions yet" payoff state |
| #446 | #354 #358 #368 | Privacy scrub canonicalize (site_api_common is now SOT) + write-endpoint throttle (checkin/suggest) + content-policy CI scan (ENFORCED) |
| #447 | #371 #369 | Managed-where ledger (docs/MANAGED_WHERE_LEDGER.md) + I4 GSI assertions + I22 site SHA reconciliation in post-deploy CI |
| #448 | #366 #360 | Dev-vs-prod spend attribution (INVOCATION_CONTEXT env var, Context=prod/dev CW metric, BEDROCK_SHADOW_MODE dry-run) + wedge-A gate readout in weekly digest |
| #449 | — | CI fixes: weekly_digest golden update + size-gate GRANDFATHERED |
| #450 | — | Layer v95 constant bump in cdk/stacks/constants.py |

## Session lesson

Pre-commit hook (`sync_doc_metadata.py`) updates `test_count` and other metadata in the **working tree** during the commit, but the change is NOT auto-staged — the committed file still has the old value. `test_platform_stats_truth::test_test_count_matches_suite` catches this on CI. **Reflex:** always run `python3 deploy/sync_doc_metadata.py` and stage the result before committing when adding/removing tests.

## Next wave (Next-milestone, model:sonnet — ranked)

Seed the next session with:
```bash
gh issue list --label type:story --milestone Next --state open --label model:sonnet
```

Top 10 by score:
- **#390** Coach quality gate: promote from advisory → blocking (N-06 elapsed, re-eval done). `area:data`
- **#389** sync_doc_metadata drift gate: `--check` mode asserts literals match discovered values; CI ENFORCED. `area:docs`
- **#388** Recovery vs deficit overlay (RQA-08): day-level chart overlay on Cockpit. `area:data`
- **#386** Cold newcomer hook: lead with the transformation hook, not the disengagement beat. `area:site-ux`
- **#383** Phase-filter re-evaluation at 30-day checkpoint (ADR-058 §13). `area:data`
- **#382** Guard dual deployment planes (script-pushed vs CDK assets). `area:infra`
- **#381** Hermetic unit suite: creds isolation in conftest. `area:infra`
- **#379** Fix Sentinel post-reset false alarm (BUG-05). `area:security`
- **#378** HAE webhook token out of query string (PRIV-02). `area:security`
- **#377** JS parse gate on site deploys (evidence.js 2,980-line SPOF). `area:infra`

Fable-only items (need a separate Fable session):
- **#397** Close the ask loop: reader Q→board answer as a returnable public feed
- **#396** Remediation agent earns auto mode or returns to shadow
- **#392** Split behavioral silence from infra failure in freshness alarms
- **#387** Deepen /api/ask grounding to platform-computed drivers

## What NOT to do next session
- Do NOT attempt Fable stories with Sonnet — they're labeled `model:fable` for a reason
- Do NOT run `aws s3 sync --delete` to bucket root
- Do NOT deploy from a worktree branch; always deploy from `main` in the worktree (or main repo when not locked)

## Deployment notes for next session
- `bedrock_client.py` layer changes → full build_layer.sh → CDK LifePlatformCore → CDK all consumer stacks
- site-api multi-module deploy: `bash deploy/deploy_site_api.sh` (NOT single-file)
- site-api-ai: manual full web/ zip (no dedicated script yet; pattern in this handover)
- Weekly digest and other email lambdas: `bash deploy/deploy_lambda.sh <fn-name> lambdas/emails/<file>.py`
