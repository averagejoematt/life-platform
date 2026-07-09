# HANDOVER — Backlog pay-down 64 → 18: 15 stories shipped by a 14-agent fleet, 30 epic/stale closures, everything deployed — 2026-07-08 (evening)

> Instruction: "review handover, memory, and put an efficient plan to pay down as many
> open issues in this session as possible. I pre-approve all edits, merges, deploys. You
> can sub-agent out different models as necessary. Goal: reduce our 64 open issues to as
> many as possible without sacrificing quality."

## The shape of the session

Three moves: (1) **audit before work** — 14 epics had zero open children and 3 stories
were already live but never closed → 17 closures with evidence comments, no code;
(2) **14 parallel worktree-implementer agents** (sonnet for S-effort, opus for the hard
ones) shipped 15 stories as PRs #870–#884, merged serially by the driver with the
doc-sync reconcile discipline; (3) one deploy pass + full verification, then 13 cascade
epic closures. **64 open issues → 18.**

## What shipped (15 stories, PRs #870–#884; all MERGED + DEPLOYED + VERIFIED)

- **#751** (PR #870) — main==live SHA ancestry check rides the weekly drift sentinel.
- **#823** (PR #871) — weekly fresh-eyes discovery workflow (Sun 15:00 UTC): screenshots
  the 4 doors, Haiku vision × 4 audiences, Sonnet synthesis, dedup vs open issues,
  emailed ≤5-item board; budget-tier ≥2 skips. First live run should be sanity-checked
  from the Actions tab.
- **#822** (PR #872) — cost governor persists its projection breakdown to SSM
  `/life-platform/budget-breakdown`; daily brief carries a one-line headroom readout.
- **#821** (PR #873) — 8 distinct coach opening registers + banned-scaffold list; found
  the root cause was our own prompt suggesting the same 3 opener stems to every coach.
- **#749** (PR #874) — masked-gate class killed: every lint gate reports independently
  (`if: always()`); standalone `visual-qa.yml` (dispatch + daily 20:07 UTC). Scope-(1)
  fast deploy subset already existed (ADR-117) — receipts in the PR.
- **#594** (PR #875) — portrait semantic states (speaking/writing/stance-change + hover),
  all reduced-motion guarded. NB: recipes only have mouth-rest/mouth-a frames; speaking
  uses the two real frames + ring pulse, never fabricated assets.
- **#815** (PR #876) — origin-header guard LIVE: CloudFront injects `X-AMJ-Origin`,
  both site-api lambdas enforce; direct Function-URL calls now 403 (verified), via-CF 200.
  site-api-ai had NO guard at all — added.
- **#744** (PR #877) — the real delta vs #869: `ai_calls._enforce_quality_gate` (the
  highest-fire-rate gate) never retained its verdicts; now feeds EVALRET# as surface 6.
- **#818+#817** (PR #878) — pre-commit hook actually runs `sync_doc_metadata.py --apply`
  (one writer; `update_architecture_header.sh` deleted); `.claude/README.md` under
  doc-sync (ADR range + tool count placeholders).
- **#475** (PR #879) — Hevy lifecycle closed: tombstone consumer, start-time-edit
  relocation, Pacific local-date keying (SCHEMA_VERSION 2), MAX_PAGES no longer advances
  the cursor on truncation. **Migration RUN live: 97 records re-keyed, 0 collisions,
  re-run shows 0 pending.** Watch the first real Hevy delete (event shape handled
  defensively but unconfirmed).
- **#753** (PR #880) — MCP write-audit trail: every mutation → `mcp-audit/YYYY/MM/DD/…`
  (args hashed, never stored raw), fail-open at two layers; weekly digest line;
  `mcp-audit/*` added to the bucket-policy delete deny (**applied live**).
- **#747** (PR #881) — relationships pillar renders "not yet instrumented" (deterministic
  flag from the zero-weight branch), excluded from the composite; self-clears when data
  flows. Latent bug found but left unfixed (out of scope): the social journal-fetch
  queries a wrong DDB key shape — worth a story.
- **#743** (PR #882) — grounding receipts on board_ask: same brief object feeds prompt
  AND receipt (can't drift); footer rendered site-side; receipts survive gate refusals.
- **#824** (PR #883) — one shared `FakeDdbTable` (tests/fakes.py) with behavior hooks;
  33 files migrated, 3 left deliberately (real query engines / load-bearing semantics).
- **#395** (PR #884) — **MCP registry pruned 143 → 60** (net −17.6k LOC): live 30d
  CloudWatch telemetry snapshot embedded in the new `docs/MCP_TOOL_AUDIT.md` AUDITED_AT
  ledger; KNOWN_ORPHANS 64 → 0 (22 were live view-impls behind used dispatchers —
  renamed `_`-prefixed, not deleted); no used tool removed. `docs/MCP_TOOL_CATALOG.md`
  body still lists pruned tools (banner added) — regeneration is a follow-up. Matthew:
  Claude Desktop/claude.ai clients lose the removed tool names (intended).

Also closed without code: **#552** (live, verified), **#592** (full cast verified),
**#825** (defer verdict recorded) + **27 epics** (14 pre-audited + 13 cascade).

## Driver-side fixes en route (committed direct to main)

- **f602b55d + follow-up** — #876's secret helper failed twice at deploy:
  (1) CloudFormation `{{resolve:secretsmanager:…}}` is REGION-LOCAL (a us-west-2 ARN from
  the us-east-1 WebStack → ResourceNotFoundException) → secret is now multi-region
  (primary us-west-2, replica us-east-1, same name/value); (2) partial-ARN resolution
  breaks when the name ends in hyphen+6 chars (`…-secret` does!) → reference by NAME
  (`SecretValue.secrets_manager(name)`), no suffix ambiguity.
- **#884 × #880 semantic collision** — the audit tests used `log_supplement` as their
  example write tool; the prune removed it (0 invocations/30d). Tests now use
  `log_decision` with schema-correct arguments.

## Deploys (all pre-authorized)

Ordered for the guard: secret created + replicated → `cdk deploy LifePlatformWeb` →
`cdk deploy --all` (9/9, ships pruned MCP + audit IAM + debrief fleet) → bucket policy
applied → character_sheet.json config re-uploaded → Hevy migration (dry→apply→dry-0) →
`sync_site_to_s3.sh` + fonts. **Verified:** suite **4207 passed / 0 failed** · smoke
**67/67** · visual QA **34/34** (12 warnings, daily-data class) · `verify_oidc_iam`
CLEAN · live build == main tip · direct-URL 403 / CF 200 / MCP boot 401-healthy.
The 3 red "Plan deployments" CI runs mid-train were the R8-ST6 IAM-diff HOLD working as
designed (new grants pending manual deploy — which then happened); post-deploy pushes
plan clean.

## Gotchas (new this session)

- **`git stash` is ONE STACK shared across every worktree** — two agents raced
  stash/pop and silently swapped working trees mid-task (both recovered, verified
  byte-identical before push). Ban stash in concurrent-agent sessions; it's in the
  worktree-implementer brief now — keep it there.
- **CFN secretsmanager dynamic refs: region-local + the hyphen-6-char partial-ARN trap**
  (see driver fixes above; full reflex in memory `reference_cfn_secret_dynamic_ref`).
- **`pytest … | tail -1` eats the exit code** — a `&&` chain continued past failing
  tests because tail succeeded; one bad push made before catching it (fixed on the same
  branch before merge).
- Agent worktrees + `cdk.out` staged copies still trip `test_hevy_compiler_isolation` —
  prune worktrees + `rm -rf cdk/cdk.out` before full-suite-on-main (known class, hit again).

**Build beat:** 2026-07-08-backlog-paydown-64-to-18

## The remaining 18 (all gated — nothing unblocked is left)

- **Matthew-decision:** #740 essay edit pass · #739 surge ceiling $ · #741 career-artifact
  publish · #423 parked register (stays open by design).
- **Attended-only (safety-flagged in-issue):** #687 OIDC trust-tighten · #755 DR restore
  drill · #750 site deploys through CI.
- **Data/decision-gated:** #748 (needs 4wk fulfillment data incl. a bad week) · #746
  (capture-channel decision) · #422/#421 (ACs need real-world use within a week of landing).
- **Epics riding those stories:** #723 #722 #719 #718 #717 #348 #342.
- **Watch:** first fresh-eyes Sunday run · first standalone visual-qa daily run (20:07 UTC)
  · first real Hevy delete consuming a tombstone · first mcp-audit records + weekly digest
  line · budget breakdown appearing after the next cost-governor run · coach openers on
  the next weekly expert-analysis regeneration.
- **Story candidates found, unfiled:** social journal-fetch DDB key mismatch (#881's
  finding) · email-subscriber Function URL unguarded (#876's finding) · MCP_TOOL_CATALOG
  regeneration · audit-prefix lifecycle rule.

Prior session archived at `handovers/HANDOVER_2026-07-08_highest-complexity-paydown.md`.
